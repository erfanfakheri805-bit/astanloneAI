"""
native_bridge.jvm - the one place where Python touches Java
===========================================================
`JavaBridge` is the narrow interface every door uses. Two implementations:

* `NullJava`    - anything that is not Android (CI, desktop, tests without a fake): every call says "unavailable_platform".
* `ChaquopyJava` - on the phone, through Chaquopy's `java` module (reached with importlib: a static `import java` would be
  read by the project's import-boundary test as a missing third-party dependency - it is Chaquopy's own module).

UNVERIFIED ON DEVICE: the Chaquopy calls follow Chaquopy's documented API (`jclass`, `jarray`, `dynamic_proxy`) and have only
been exercised against hand-written fakes in this delivery. Every Java exception is turned into a `DoorResult` by the doors.
"""

import importlib
import re
from abc import ABC, abstractmethod

__all__ = ["JavaBridge", "NullJava", "ChaquopyJava", "NativeUnavailable", "detect_jvm", "MAIN_ACTIVITY", "valid_class_name"]

MAIN_ACTIVITY = "com.erfan.standaloneai.MainActivity"
_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\$[A-Za-z_][A-Za-z0-9_]*)*\Z")


def valid_class_name(name):
    return isinstance(name, str) and 3 <= len(name) <= 200 and bool(_CLASS_RE.match(name))


class NativeUnavailable(Exception):
    """The Java side (or this part of it) is not there; `code` says which."""

    def __init__(self, code="unavailable_platform", detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


class JavaBridge(ABC):
    platform_name = "none"

    def available(self):
        return False

    @abstractmethod
    def jclass(self, name): ...

    @abstractmethod
    def context(self): ...

    def sdk_int(self):
        return None

    def native_features(self):
        return frozenset()

    def proxy(self, interface_name, methods):
        raise NativeUnavailable("unavailable_platform")

    def run_on_main(self, fn):
        raise NativeUnavailable("unavailable_platform")

    def string_array(self, items):
        raise NativeUnavailable("unavailable_platform")


class NullJava(JavaBridge):
    platform_name = "none"

    def jclass(self, name):
        raise NativeUnavailable("unavailable_platform")

    def context(self):
        raise NativeUnavailable("unavailable_platform")


class ChaquopyJava(JavaBridge):
    platform_name = "android"

    def __init__(self, java_module=None, context_getter=None):
        self._java = java_module if java_module is not None else importlib.import_module("java")
        self._context_getter = context_getter
        self._context = None

    def available(self):
        return True

    def jclass(self, name):
        if not valid_class_name(name):
            raise NativeUnavailable("bad_class_name")
        try:
            return self._java.jclass(name)
        except Exception as exc:
            raise NativeUnavailable("class_missing", type(exc).__name__) from exc

    def context(self):
        if self._context is None:
            if self._context_getter is not None:
                self._context = self._context_getter()
            else:
                python = self.jclass("com.chaquo.python.Python")
                try:
                    self._context = python.getPlatform().getApplication()
                except Exception:
                    self._context = python.getInstance().getPlatform().getApplication()
        if self._context is None:
            raise NativeUnavailable("no_context")
        return self._context

    def sdk_int(self):
        try:
            value = int(self.jclass("android.os.Build$VERSION").SDK_INT)
            return value if value > 0 else None
        except Exception:
            return None

    def native_features(self):
        try:
            names = getattr(self.jclass(MAIN_ACTIVITY), "NATIVE_FEATURES")
            return frozenset(str(item) for item in names) if names is not None else frozenset()
        except Exception:                    # an APK built before the field existed has no native features
            return frozenset()

    def proxy(self, interface_name, methods):
        """A Java object implementing `interface_name` whose methods are the Python callables in `methods`."""
        iface = self.jclass(interface_name)
        base = self._java.dynamic_proxy(iface)
        namespace = {}
        for name, fn in dict(methods).items():
            namespace[name] = _bind(fn)
        return type("NativeProxy", (base,), namespace)()

    def run_on_main(self, fn):
        looper = self.jclass("android.os.Looper").getMainLooper()
        handler = self.jclass("android.os.Handler")(looper)
        return bool(handler.post(self.proxy("java.lang.Runnable", {"run": fn})))

    def string_array(self, items):
        return self._java.jarray(self.jclass("java.lang.String"))([str(i) for i in items])


def _bind(fn):
    def method(self, *args):
        return fn(*args)
    return method


def detect_jvm():
    """A `ChaquopyJava` only when Chaquopy's `java` module really exists; otherwise a `NullJava`."""
    try:
        java = importlib.import_module("java")
        java.jclass
    except (ImportError, AttributeError):
        return NullJava()
    try:
        return ChaquopyJava(java)
    except Exception:
        return NullJava()
