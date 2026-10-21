"""
android_adapters.layer - truthful, permission-aware access to Android features
===============================================================================
`AndroidAdapterLayer(bridge)` answers three questions about every feature in the catalog:

* `status(feature_id)`  - what is the exact situation (wrong platform, API too old, native piece
  missing from this APK, permission not declared, permission/special permission needed, limited by
  Android policy, or ready)? `ready` only means the PRE-CONDITIONS hold; `implemented`/`actions`
  say whether this layer can really DO anything with the feature.
* `request_permission(feature_id, user_approved=...)` - asks Android to show its permission dialog.
  It refuses unless `user_approved is True`, only for declared runtime permissions of features that
  have an implemented action (least privilege: no permission "just in case"), and only when the APK
  really has the native request hook. It reports `dispatched`, never "granted": the user's answer is
  seen later by re-checking the status.
* `invoke(feature_id, action)` - runs an implemented action (today only `network_state.read`).
  Everything else is refused with a precise code such as `action_not_implemented`.

Nothing here has run on a device: `FeatureStatus.verified_on_device` is always False. A misbehaving
bridge can never make the layer raise.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .bridge import AndroidBridge, BridgeConnectivity, NullBridge
from .catalog import (FEATURES, FeatureSpec, NATIVE_PERMISSION_REQUEST, PERMISSION_CHECK, get_feature)

__all__ = ["AndroidAdapterLayer", "FeatureStatus", "PermissionRequestResult", "InvokeResult", "UnknownFeatureError", "STATES"]

STATES = ("unavailable_platform", "native_bridge_missing", "permission_not_declared", "permission_required",
          "special_permission_required", "ready", "not_supported_on_this_android", "limited_by_android_policy")


class UnknownFeatureError(KeyError):
    """The feature id is not in the catalog."""


@dataclass(frozen=True)
class FeatureStatus:
    feature_id: str
    state: str
    code: str
    message_fa: str
    message_en: str
    missing: Tuple[str, ...] = ()
    can_request_permission: bool = False
    implemented: bool = False
    actions: Tuple[str, ...] = ()
    verified_on_device: bool = field(default=False, init=False)  # NOTHING in this delivery has run on a device

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PermissionRequestResult:
    feature_id: str
    dispatched: bool
    code: str
    message_fa: str
    message_en: str
    permissions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class InvokeResult:
    feature_id: str
    action: str
    ok: bool
    code: str
    message_fa: str
    message_en: str
    data: Optional[dict] = None


def _read_network(layer: "AndroidAdapterLayer", params: Optional[dict]) -> dict:
    connectivity = layer._connectivity()
    return {"state": connectivity.state, "code": connectivity.code}


DEFAULT_HANDLERS: Dict[Tuple[str, str], Callable[["AndroidAdapterLayer", Optional[dict]], dict]] = {
    ("network_state", "read"): _read_network,
}

_STATE_TEXT = {
    "unavailable_platform": ("این قابلیت فقط داخل برنامهٔ اندروید در دسترس است.", "This feature exists only inside the Android app."),
    "native_bridge_missing": ("این نسخهٔ برنامه (APK) بخش بومی لازم را ندارد؛ باید APK جدید ساخته و نصب شود.",
                              "This build of the app (APK) lacks the native part this needs; a new APK has to be built and installed."),
    "permission_not_declared": ("مجوز لازم در مانیفست برنامه اعلام نشده؛ بدون ساخت APK جدید نمی‌شود آن را گرفت.",
                                "The needed permission is not declared in the app manifest; it cannot be obtained without a new APK."),
    "permission_required": ("مجوز اندروید لازم است و هنوز داده نشده.", "An Android permission is required and has not been granted."),
    "special_permission_required": ("مجوز ویژه لازم است که فقط خودت از تنظیمات اندروید می‌توانی بدهی.",
                                    "A special permission is required that only you can grant in Android settings."),
    "not_supported_on_this_android": ("نسخهٔ اندروید این گوشی برای این قابلیت کافی نیست.", "This phone's Android version is too old for the feature."),
}


def _guard(fn: Callable[[], Any], default: Any) -> Any:
    try:
        return fn()
    except Exception:
        return default


class AndroidAdapterLayer:
    def __init__(self, bridge: Optional[AndroidBridge] = None, *, features: Optional[Mapping[str, FeatureSpec]] = None,
                 handlers: Optional[Mapping[Tuple[str, str], Callable]] = None) -> None:
        self._bridge: AndroidBridge = bridge if bridge is not None else NullBridge()
        self._features: Mapping[str, FeatureSpec] = features if features is not None else FEATURES
        self._handlers = dict(handlers) if handlers is not None else dict(DEFAULT_HANDLERS)

    # ---- guarded bridge reads ---------------------------------------------------

    def _platform(self) -> str:
        return str(_guard(lambda: self._bridge.platform_name, "none"))

    def _sdk(self) -> Optional[int]:
        value = _guard(self._bridge.sdk_int, None)
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

    def _native(self) -> frozenset:
        value = _guard(self._bridge.native_features, frozenset())
        return frozenset(v for v in value if isinstance(v, str)) if isinstance(value, (set, frozenset, list, tuple)) else frozenset()

    def _declared(self) -> Optional[frozenset]:
        value = _guard(self._bridge.declared_permissions, None)
        return frozenset(v for v in value if isinstance(v, str)) if isinstance(value, (set, frozenset, list, tuple)) else None

    def _connectivity(self) -> BridgeConnectivity:
        value = _guard(self._bridge.connectivity, None)
        if isinstance(value, BridgeConnectivity) and value.state in ("online", "offline", "unknown"):
            return value
        return BridgeConnectivity("unknown", "bridge_error")

    def _spec(self, feature_id: object) -> FeatureSpec:
        spec = self._features.get(feature_id) if isinstance(feature_id, str) else None
        if spec is None:
            raise UnknownFeatureError(feature_id)
        return spec

    # ---- status -------------------------------------------------------------------

    def _build(self, spec: FeatureSpec, state: str, code: str, fa: str, en: str, missing=(), can_request=False) -> FeatureStatus:
        actions = tuple(sorted(spec.implemented_actions))
        return FeatureStatus(spec.feature_id, state, code, fa, en, tuple(missing), bool(can_request), bool(actions), actions)

    def _permission_view(self, spec: FeatureSpec, sdk: int, native: frozenset) -> Tuple[str, Tuple[str, ...], bool]:
        """('ok'|'not_declared'|'required'|'special'|'unknown_special', missing permissions, can_request)."""
        needed = spec.permissions_needed(sdk)
        if not needed:
            return "ok", (), False
        declared = self._declared()
        undeclared = tuple(p for p in needed if declared is not None and p not in declared)
        if spec.permission_kind == "special":
            blocked = tuple(p for p in needed if self._special(p) is not True)
            if undeclared:
                return "not_declared", undeclared, False
            return ("special", blocked, False) if blocked else ("ok", (), False)
        denied = tuple(p for p in needed if _guard(lambda p=p: self._bridge.check_permission(p), "unknown") != "granted")
        if spec.permission_kind == "install":
            return ("not_declared", denied, False) if denied else ("ok", (), False)
        if undeclared:
            return "not_declared", undeclared, False
        if not denied:
            return "ok", (), False
        can_request = declared is not None and NATIVE_PERMISSION_REQUEST in native
        return "required", denied, can_request

    def _special(self, name: str) -> Optional[bool]:
        value = _guard(lambda: self._bridge.special_permission_granted(name), None)
        return value if isinstance(value, bool) else None

    def status(self, feature_id: str) -> FeatureStatus:
        spec = self._spec(feature_id)
        title_fa, title_en = spec.title_fa, spec.title_en

        def early(state: str, code: str, missing=()) -> FeatureStatus:
            fa, en = _STATE_TEXT[state]
            return self._build(spec, state, code, "«%s»: %s" % (title_fa, fa), "'%s': %s" % (title_en, en), missing)

        if self._platform() != "android":
            return early("unavailable_platform", "not_android")
        sdk = self._sdk()
        if sdk is None:
            return early("unavailable_platform", "sdk_unknown")
        if sdk < spec.min_sdk:
            return early("not_supported_on_this_android", "sdk_too_low", ("android_api_%d" % spec.min_sdk,))
        native = self._native()
        if spec.needs_native_feature and spec.needs_native_feature not in native:
            return early("native_bridge_missing", "native_feature_absent", (spec.needs_native_feature,))
        kind, missing, can_request = self._permission_view(spec, sdk, native)
        if spec.policy_limited:
            note_fa = " مجوز لازم هنوز آماده نیست." if kind != "ok" else ""
            note_en = " The needed permission is not ready either." if kind != "ok" else ""
            return self._build(spec, "limited_by_android_policy", "android_policy",
                               "«%s»: %s%s" % (title_fa, spec.limitations_fa, note_fa),
                               "'%s': %s%s" % (title_en, spec.limitations_en, note_en), missing, can_request)
        if kind == "not_declared":
            return early("permission_not_declared", "not_declared", missing)
        if kind == "special":
            return early("special_permission_required", "special_not_granted", missing)
        if kind == "required":
            return self._build(spec, "permission_required", "denied",
                               "«%s»: %s" % (title_fa, _STATE_TEXT["permission_required"][0]),
                               "'%s': %s" % (title_en, _STATE_TEXT["permission_required"][1]), missing, can_request)
        actions = tuple(sorted(spec.implemented_actions))
        if actions:
            fa = "«%s»: پیش‌نیازها آماده است. عملیات پیاده‌شده: %s." % (title_fa, "، ".join(actions))
            en = "'%s': prerequisites are ready. Implemented actions: %s." % (title_en, ", ".join(actions))
        else:
            fa = "«%s»: پیش‌نیازها آماده است ولی هنوز هیچ عملیاتی برای آن پیاده‌سازی نشده است. %s" % (title_fa, spec.limitations_fa)
            en = "'%s': prerequisites are ready, but no action is implemented for it yet. %s" % (title_en, spec.limitations_en)
        return self._build(spec, "ready", "ok", fa, en)

    def all_statuses(self) -> List[FeatureStatus]:
        return [self.status(feature_id) for feature_id in self._features]

    # ---- asking for a permission -----------------------------------------------------

    def _refuse_request(self, spec_id: str, code: str, fa: str, en: str, permissions=()) -> PermissionRequestResult:
        return PermissionRequestResult(spec_id, False, code, fa, en, tuple(permissions))

    def request_permission(self, feature_id: str, *, user_approved: bool = False) -> PermissionRequestResult:
        try:
            spec = self._spec(feature_id)
        except UnknownFeatureError:
            return self._refuse_request(str(feature_id)[:40], "unknown_feature", "چنین قابلیتی در فهرست نیست.", "No such feature.")
        if user_approved is not True:
            return self._refuse_request(spec.feature_id, "approval_required", "برای درخواست مجوز اندروید باید خودت صریحاً تأیید کنی.",
                                        "Asking Android for a permission needs your explicit approval.")
        status = self.status(spec.feature_id)
        if status.state in ("unavailable_platform", "not_supported_on_this_android", "native_bridge_missing", "permission_not_declared"):
            return self._refuse_request(spec.feature_id, status.state, status.message_fa, status.message_en, status.missing)
        if spec.permission_kind != "runtime":
            code = "no_permission_needed" if spec.permission_kind == "none" else "not_runtime_permission"
            fa = ("این قابلیت مجوزی نمی‌خواهد." if code == "no_permission_needed"
                  else "این مجوز را فقط خودت می‌توانی در تنظیمات اندروید بدهی؛ برنامه نمی‌تواند آن را درخواست یا به خودش بدهد.")
            en = ("This feature needs no permission." if code == "no_permission_needed"
                  else "Only you can grant this permission in Android settings; the app cannot request it or give it to itself.")
            return self._refuse_request(spec.feature_id, code, fa, en)
        if not status.missing:
            return self._refuse_request(spec.feature_id, "already_granted", "این مجوز از قبل داده شده است.", "The permission is already granted.")
        if not spec.implemented_actions:
            return self._refuse_request(spec.feature_id, "feature_not_implemented",
                                        "هنوز هیچ عملیاتی از «%s» پیاده‌سازی نشده؛ پس مجوز بی‌دلیل درخواست نمی‌شود." % spec.title_fa,
                                        "No action of '%s' is implemented yet, so no permission is requested for nothing." % spec.title_en,
                                        status.missing)
        if not status.can_request_permission:
            return self._refuse_request(spec.feature_id, "cannot_request", "الان نمی‌شود این مجوز را درخواست کرد (بخش بومی یا مانیفست آماده نیست).",
                                        "The permission cannot be requested right now (the native part or manifest is not ready).", status.missing)
        result = _guard(lambda: self._bridge.request_permissions(list(status.missing)), None)
        if result is None or not hasattr(result, "dispatched"):
            return self._refuse_request(spec.feature_id, "bridge_error", "ارتباط با اندروید خطا داد.", "The call into Android failed.", status.missing)
        if not result.dispatched:
            return self._refuse_request(spec.feature_id, str(result.code)[:40] or "not_dispatched", "پنجرهٔ درخواست مجوز نمایش داده نشد.",
                                        "The permission dialog was not shown.", status.missing)
        return PermissionRequestResult(spec.feature_id, True, "dispatched",
                                       "پنجرهٔ درخواست مجوز اندروید نمایش داده شد؛ تصمیم تو بعداً با بررسی دوبارهٔ وضعیت دیده می‌شود (هنوز نمی‌دانم قبول کردی یا نه).",
                                       "Android's permission dialog was shown; your decision is seen later by re-checking the status (I do not know yet whether you accepted).",
                                       status.missing)

    # ---- running an implemented action --------------------------------------------------

    def invoke(self, feature_id: str, action: str, params: Optional[dict] = None, *, user_approved: bool = False) -> InvokeResult:
        try:
            spec = self._spec(feature_id)
        except UnknownFeatureError:
            return InvokeResult(str(feature_id)[:40], str(action)[:40], False, "unknown_feature", "چنین قابلیتی در فهرست نیست.", "No such feature.")
        if not isinstance(action, str) or not 0 < len(action) <= 40:
            return InvokeResult(spec.feature_id, "", False, "bad_arguments", "نام عمل معتبر نیست.", "The action name is not valid.")
        if params is not None and not isinstance(params, dict):
            return InvokeResult(spec.feature_id, action, False, "bad_arguments", "پارامترها معتبر نیستند.", "The parameters are not valid.")
        status = self.status(spec.feature_id)
        if action == PERMISSION_CHECK:
            return InvokeResult(spec.feature_id, action, True, "ok", status.message_fa, status.message_en, status.to_dict())
        if status.state != "ready":
            return InvokeResult(spec.feature_id, action, False, status.state, status.message_fa, status.message_en, {"missing": list(status.missing)})
        handler = self._handlers.get((spec.feature_id, action))
        if action not in spec.implemented_actions or handler is None:
            return InvokeResult(spec.feature_id, action, False, "action_not_implemented",
                                "عمل «%s» برای «%s» پیاده‌سازی نشده است." % (action, spec.title_fa),
                                "The action '%s' is not implemented for '%s'." % (action, spec.title_en))
        try:
            data = handler(self, params)
        except Exception as exc:
            return InvokeResult(spec.feature_id, action, False, "action_failed", "اجرای عمل ناموفق بود.",
                                "The action failed (%s)." % type(exc).__name__)
        return InvokeResult(spec.feature_id, action, True, "ok", "انجام شد.", "Done.", data if isinstance(data, dict) else None)

    # ---- network ----------------------------------------------------------------------

    def network_probe(self) -> Optional[bool]:
        """True online / False offline / None unknown - the shape `net_tools.network_status(probe=...)` expects."""
        try:
            if self.status("network_state").state != "ready":
                return None
        except UnknownFeatureError:
            return None
        state = self._connectivity().state
        return True if state == "online" else False if state == "offline" else None
