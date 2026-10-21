"""
android_adapters.catalog - the Android features this app knows about, and what is REALLY implemented
==================================================================================================
One `FeatureSpec` per platform feature. A spec says what Android needs for the feature (which
permission, of which kind, from which API level, which native piece of THIS APK) and - most
importantly - which actions the Python layer can really perform through supported APIs.

`implemented_actions` is deliberately tiny. An action is listed only when its code path exists in
`android_adapters.layer` AND is covered by tests. Everything else is an empty set, so the layer
can never answer "done" for something nobody wrote: `network_state` can be read; the microphone,
camera, notifications, settings, telephony, battery and clipboard are described and permission-
checked but have NO implemented action yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple

__all__ = ["FeatureSpec", "FEATURES", "PERMISSION_KINDS", "feature_ids", "get_feature", "NATIVE_FILE_CHOOSER",
           "NATIVE_PERMISSION_REQUEST", "PERMISSION_CHECK", "valid_permission_name"]

PERMISSION_KINDS = ("none", "install", "runtime", "special")
NATIVE_FILE_CHOOSER = "file_chooser"
NATIVE_PERMISSION_REQUEST = "permission_request"
PERMISSION_CHECK = "permission_check"  # the generic action every feature supports

_PERMISSION_PREFIX = "android.permission."


def valid_permission_name(name: object) -> bool:
    """Only plain `android.permission.UPPER_CASE` names may ever be handed to Android."""
    if not isinstance(name, str) or not name.startswith(_PERMISSION_PREFIX):
        return False
    tail = name[len(_PERMISSION_PREFIX):]
    return 1 <= len(tail) <= 60 and all(ch.isascii() and (ch.isupper() or ch.isdigit() or ch == "_") for ch in tail)


@dataclass(frozen=True)
class FeatureSpec:
    feature_id: str
    title_fa: str
    title_en: str
    android_permissions: Tuple[str, ...]
    permission_kind: str                      # none | install | runtime | special
    min_sdk: int
    needs_native_feature: Optional[str]       # an entry of MainActivity.NATIVE_FEATURES, or None
    implemented_actions: FrozenSet[str]       # what this layer can really DO (not merely check)
    limitations_fa: str
    limitations_en: str
    runtime_from_sdk: int = 0                 # a runtime permission that only exists from this API level (0 = always)
    policy_limited: bool = False              # Android itself forbids what the user wants (see the limitations text)

    def __post_init__(self) -> None:
        if self.permission_kind not in PERMISSION_KINDS:
            raise ValueError("bad permission_kind")
        if not all(valid_permission_name(p) for p in self.android_permissions):
            raise ValueError("bad permission name")
        if (self.permission_kind == "none") != (not self.android_permissions):
            raise ValueError("permission_kind and android_permissions disagree")

    def permissions_needed(self, sdk_int: int) -> Tuple[str, ...]:
        """The permissions that apply on this Android version (POST_NOTIFICATIONS only exists from API 33)."""
        if self.permission_kind == "none":
            return ()
        if self.runtime_from_sdk and sdk_int < self.runtime_from_sdk:
            return ()
        return self.android_permissions


def _spec(**kw) -> FeatureSpec:
    kw.setdefault("implemented_actions", frozenset())
    return FeatureSpec(**kw)


FEATURES: Dict[str, FeatureSpec] = {spec.feature_id: spec for spec in (
    _spec(feature_id="file_picker", title_fa="انتخاب فایل", title_en="File selection", android_permissions=(),
          permission_kind="none", min_sdk=24, needs_native_feature=NATIVE_FILE_CHOOSER,
          limitations_fa="انتخاب فایل را خود وب‌ویو (دکمهٔ پیوست در گفتگو) انجام می‌دهد؛ پایتون خودش فایل‌های گوشی را باز نمی‌کند و فقط متنی را که تو انتخاب کرده‌ای دریافت می‌کند.",
          limitations_en="The WebView (the attach button in the chat) does the picking; Python never opens phone files itself and only receives text you selected."),
    _spec(feature_id="microphone", title_fa="میکروفون", title_en="Microphone", android_permissions=("android.permission.RECORD_AUDIO",),
          permission_kind="runtime", min_sdk=24, needs_native_feature=None,
          limitations_fa="فقط وضعیت مجوز بررسی می‌شود؛ ضبط صدا، تشخیص گفتار و کلمهٔ بیدارباش «جارویس» هنوز پیاده‌سازی نشده‌اند.",
          limitations_en="Only the permission state is checked; audio recording, speech recognition and the 'Jarvis' wake word are not implemented yet."),
    _spec(feature_id="camera", title_fa="دوربین", title_en="Camera", android_permissions=("android.permission.CAMERA",),
          permission_kind="runtime", min_sdk=24, needs_native_feature=None,
          limitations_fa="فقط وضعیت مجوز بررسی می‌شود؛ گرفتن عکس یا فیلم هنوز پیاده‌سازی نشده است.",
          limitations_en="Only the permission state is checked; taking photos or video is not implemented yet."),
    _spec(feature_id="notifications", title_fa="اعلان‌ها", title_en="Notifications",
          android_permissions=("android.permission.POST_NOTIFICATIONS",), permission_kind="runtime", min_sdk=24,
          needs_native_feature=None, runtime_from_sdk=33,
          limitations_fa="از اندروید ۱۳ به بعد مجوز زمان اجرا لازم است؛ ارسال اعلان هنوز پیاده‌سازی نشده است.",
          limitations_en="From Android 13 a runtime permission is required; sending notifications is not implemented yet."),
    _spec(feature_id="settings_write", title_fa="تغییر تنظیمات سیستم", title_en="System settings (write)",
          android_permissions=("android.permission.WRITE_SETTINGS",), permission_kind="special", min_sdk=24,
          needs_native_feature=None,
          limitations_fa="مجوز ویژه است: فقط خودت از صفحهٔ تنظیمات اندروید می‌توانی بدهی و برنامه نمی‌تواند به خودش بدهد؛ تغییر تنظیمات هنوز پیاده‌سازی نشده است.",
          limitations_en="A special permission only you can grant in Android settings (the app cannot grant it to itself); changing settings is not implemented yet."),
    _spec(feature_id="telephony", title_fa="تماس تلفنی", title_en="Phone calls",
          android_permissions=("android.permission.ANSWER_PHONE_CALLS",), permission_kind="runtime", min_sdk=26,
          needs_native_feature=None, policy_limited=True,
          limitations_fa="اندروید به برنامه‌های معمولی اجازهٔ دسترسی به صدای تماس را نمی‌دهد؛ پس برنامه نمی‌تواند با تماس‌گیرنده گفت‌وگو کند. فقط پذیرش/رد تماس و غربال‌گری آن هم با نقش «غربال‌گر تماس» که کاربر باید خودش بدهد ممکن است و هیچ‌کدام هنوز پیاده‌سازی نشده است.",
          limitations_en="Android does not give ordinary apps call audio, so the app cannot hold a conversation with a caller. At most it could accept/reject a call, and screening needs the call-screening role the user must grant; none of it is implemented yet."),
    _spec(feature_id="network_state", title_fa="وضعیت شبکه", title_en="Network state",
          android_permissions=("android.permission.ACCESS_NETWORK_STATE",), permission_kind="install", min_sdk=24,
          needs_native_feature=None, implemented_actions=frozenset({"read"}),
          limitations_fa="فقط می‌گوید گوشی اینترنت دارد یا نه؛ این به معنای در دسترس بودن یک سایت مشخص نیست.",
          limitations_en="It only says whether the phone has internet; that does not mean a particular site is reachable."),
    _spec(feature_id="battery_status", title_fa="وضعیت باتری", title_en="Battery status", android_permissions=(),
          permission_kind="none", min_sdk=24, needs_native_feature=None,
          limitations_fa="هنوز پیاده‌سازی نشده است.", limitations_en="Not implemented yet."),
    _spec(feature_id="clipboard", title_fa="کلیپ‌بورد", title_en="Clipboard", android_permissions=(),
          permission_kind="none", min_sdk=24, needs_native_feature=None,
          limitations_fa="هنوز پیاده‌سازی نشده است.", limitations_en="Not implemented yet."),
)}


def feature_ids() -> Tuple[str, ...]:
    return tuple(FEATURES)


def get_feature(feature_id: object) -> Optional[FeatureSpec]:
    return FEATURES.get(feature_id) if isinstance(feature_id, str) else None
