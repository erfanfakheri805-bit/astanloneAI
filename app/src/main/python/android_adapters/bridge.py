"""
android_adapters.bridge - the only door from Python to the Android runtime
==========================================================================
`AndroidBridge` is the narrow interface the layer talks to. Two implementations exist:

* `NullBridge` - anything that is not Android (CI, desktop, tests): every answer is
  "unavailable_platform" / "unknown"; nothing is ever pretended.
* `ChaquopyBridge` - on a device, through Chaquopy's `java` module. EVERY Java access is guarded:
  a Java exception becomes a safe "unknown"/"not dispatched" answer and never propagates.

UNVERIFIED ON DEVICE: the Chaquopy calls below follow Chaquopy's and Android's documented APIs but
have only been exercised against hand-written fakes in this delivery. `verified_on_device` stays
False everywhere until a real device run says otherwise.

The Java side (`MainActivity`) advertises what THIS APK really contains:
    public static final String[] NATIVE_FEATURES          e.g. {"file_chooser", "permission_request"}
    public static boolean requestAndroidPermissions(String[] permissions)
An older APK without them simply has no native features - that is how old and new APKs are told
apart honestly. `requestAndroidPermissions` only DISPATCHES the system dialog; the user's decision
is observed later by re-checking the permission.
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, FrozenSet, Optional, Sequence

from .catalog import valid_permission_name

__all__ = ["AndroidBridge", "NullBridge", "ChaquopyBridge", "BridgeRequestResult", "BridgeConnectivity", "detect_bridge",
           "MAIN_ACTIVITY_CLASS", "GET_PERMISSIONS_FLAG"]

MAIN_ACTIVITY_CLASS = "com.erfan.standaloneai.MainActivity"
GET_PERMISSIONS_FLAG = 4096          # PackageManager.GET_PERMISSIONS
_CAP_INTERNET, _CAP_VALIDATED = 12, 16   # NetworkCapabilities.NET_CAPABILITY_INTERNET / _VALIDATED
_MAX_REQUEST = 8
_SPECIAL_WRITE_SETTINGS = "android.permission.WRITE_SETTINGS"


def _chaquopy_java():
    """Chaquopy's `java` module. It exists only inside a Chaquopy runtime (it is never pip-installed and never on a desktop),
    so it is reached through importlib: a static `import java` would be read by the project's import-boundary test (the APK
    ships the standard library only) as a missing third-party dependency, which it is not."""
    return importlib.import_module("java")


@dataclass(frozen=True)
class BridgeRequestResult:
    dispatched: bool
    code: str
    detail: str = ""


@dataclass(frozen=True)
class BridgeConnectivity:
    state: str   # "online" | "offline" | "unknown"
    code: str


class AndroidBridge(ABC):
    platform_name: str = "none"

    @abstractmethod
    def sdk_int(self) -> Optional[int]: ...

    @abstractmethod
    def check_permission(self, name: str) -> str:
        """'granted' | 'denied' | 'unknown'."""

    @abstractmethod
    def declared_permissions(self) -> Optional[FrozenSet[str]]:
        """Permissions the installed manifest declares; None when that cannot be read."""

    @abstractmethod
    def native_features(self) -> FrozenSet[str]: ...

    @abstractmethod
    def request_permissions(self, names: Sequence[str]) -> BridgeRequestResult: ...

    @abstractmethod
    def connectivity(self) -> BridgeConnectivity: ...

    @abstractmethod
    def special_permission_granted(self, name: str) -> Optional[bool]: ...


class NullBridge(AndroidBridge):
    platform_name = "none"

    def sdk_int(self) -> Optional[int]:
        return None

    def check_permission(self, name: str) -> str:
        return "unknown"

    def declared_permissions(self) -> Optional[FrozenSet[str]]:
        return None

    def native_features(self) -> FrozenSet[str]:
        return frozenset()

    def request_permissions(self, names: Sequence[str]) -> BridgeRequestResult:
        return BridgeRequestResult(False, "unavailable_platform")

    def connectivity(self) -> BridgeConnectivity:
        return BridgeConnectivity("unknown", "unavailable_platform")

    def special_permission_granted(self, name: str) -> Optional[bool]:
        return None


class ChaquopyBridge(AndroidBridge):
    platform_name = "android"

    def __init__(self, jclass: Optional[Callable[[str], Any]] = None, jarray: Optional[Callable[[Any], Any]] = None,
                 context_getter: Optional[Callable[[], Any]] = None) -> None:
        if jclass is None or jarray is None:
            java = _chaquopy_java()                                          # only exists inside Chaquopy
            jclass, jarray = jclass or java.jclass, jarray or java.jarray
        self._jclass, self._jarray = jclass, jarray
        self._context_getter = context_getter or self._default_context
        self._context: Any = None

    # ---- plumbing ------------------------------------------------------------

    def _default_context(self) -> Any:
        python = self._jclass("com.chaquo.python.Python")
        try:
            return python.getPlatform().getApplication()
        except Exception:
            return python.getInstance().getPlatform().getApplication()

    def _ctx(self) -> Any:
        if self._context is None:
            self._context = self._context_getter()
        if self._context is None:
            raise RuntimeError("no application context")
        return self._context

    @staticmethod
    def _is_security_exception(exc: BaseException) -> bool:
        return type(exc).__name__ == "SecurityException"

    # ---- reads ---------------------------------------------------------------

    def sdk_int(self) -> Optional[int]:
        try:
            value = self._jclass("android.os.Build$VERSION").SDK_INT
            return int(value) if not isinstance(value, bool) and int(value) > 0 else None
        except Exception:
            return None

    def check_permission(self, name: str) -> str:
        if not valid_permission_name(name):
            return "unknown"
        try:
            result = self._jclass("androidx.core.content.ContextCompat").checkSelfPermission(self._ctx(), name)
            return "granted" if result == 0 else "denied" if result == -1 else "unknown"
        except Exception:
            return "unknown"

    def declared_permissions(self) -> Optional[FrozenSet[str]]:
        try:
            context = self._ctx()
            info = context.getPackageManager().getPackageInfo(context.getPackageName(), GET_PERMISSIONS_FLAG)
            requested = info.requestedPermissions
            if requested is None:
                return frozenset()
            return frozenset(str(item) for item in requested)
        except Exception:
            return None

    def native_features(self) -> FrozenSet[str]:
        try:
            names = getattr(self._jclass(MAIN_ACTIVITY_CLASS), "NATIVE_FEATURES")
            if names is None:
                return frozenset()
            return frozenset(str(item) for item in names)
        except Exception:  # an APK built before this field existed has no native features
            return frozenset()

    def special_permission_granted(self, name: str) -> Optional[bool]:
        if name != _SPECIAL_WRITE_SETTINGS:
            return None
        try:
            sdk = self.sdk_int()
            if sdk is not None and sdk < 23:
                return True  # before API 23 WRITE_SETTINGS is an ordinary install-time permission
            return bool(self._jclass("android.provider.Settings$System").canWrite(self._ctx()))
        except Exception:
            return None

    def connectivity(self) -> BridgeConnectivity:
        try:
            manager = self._ctx().getSystemService("connectivity")
            if manager is None:
                return BridgeConnectivity("unknown", "no_connectivity_service")
            sdk = self.sdk_int()
            if sdk is None:
                return BridgeConnectivity("unknown", "sdk_unknown")
            if sdk >= 23:
                network = manager.getActiveNetwork()
                if network is None:
                    return BridgeConnectivity("offline", "no_active_network")
                caps = manager.getNetworkCapabilities(network)
                if caps is None:
                    return BridgeConnectivity("offline", "no_capabilities")
                if not caps.hasCapability(_CAP_INTERNET):
                    return BridgeConnectivity("offline", "no_internet_capability")
                if not caps.hasCapability(_CAP_VALIDATED):
                    return BridgeConnectivity("unknown", "not_validated")  # captive portal or still checking
                return BridgeConnectivity("online", "validated")
            info = manager.getActiveNetworkInfo()
            if info is None or not info.isConnected():
                return BridgeConnectivity("offline", "not_connected")
            return BridgeConnectivity("online", "legacy_api")
        except Exception as exc:
            if self._is_security_exception(exc):
                return BridgeConnectivity("unknown", "permission_not_declared")
            return BridgeConnectivity("unknown", "bridge_error")

    # ---- the one action: ask Android to show the permission dialog -------------

    def request_permissions(self, names: Sequence[str]) -> BridgeRequestResult:
        names = list(names) if isinstance(names, (list, tuple)) else []
        if not names or len(names) > _MAX_REQUEST or not all(valid_permission_name(n) for n in names):
            return BridgeRequestResult(False, "invalid_request")
        try:
            array = self._jarray(self._jclass("java.lang.String"))(names)
            dispatched = bool(getattr(self._jclass(MAIN_ACTIVITY_CLASS), "requestAndroidPermissions")(array))
        except Exception as exc:
            return BridgeRequestResult(False, "bridge_error", type(exc).__name__)
        return BridgeRequestResult(dispatched, "dispatched" if dispatched else "not_dispatched")


def detect_bridge() -> AndroidBridge:
    """A `ChaquopyBridge` only when Chaquopy's `java` module really exists; otherwise a `NullBridge`."""
    try:
        java = _chaquopy_java()
        java.jarray, java.jclass                                             # both must exist (AttributeError otherwise)
    except (ImportError, AttributeError):
        return NullBridge()
    try:
        return ChaquopyBridge()
    except Exception:
        return NullBridge()
