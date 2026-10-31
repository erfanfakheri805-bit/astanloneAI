"""
native_bridge.screen - reading and operating the screen of OTHER apps (Android's accessibility service)
=======================================================================================================
This is the door through which the assistant can "go into" another app (ChatGPT, Claude, a browser ...) the way a person
would: read what is on the screen, type into a field, press a button. Android allows it only through an accessibility
service that THE USER switches on in Android's settings - the app can never enable it by itself.

Safety rules enforced here (in addition to Android's own):
* the service must be connected (the user enabled it) - otherwise "not_enabled";
* only apps the user allowed for this task (`allowed_fn()` returns the set, with an expiry kept by the teacher) are touched;
* a fixed deny-list is never touched even when allowed: Android settings, the package installer, the permission controller,
  the Play Store and the system UI - so no recipe can grant a permission, install an app or flip a system switch;
* the text of password fields is never read (the Java side leaves it out and flags the node);
* every node list is bounded; nothing is stored here.

The Java side is `PyAccessibilityService` (static methods; see its source). UNVERIFIED ON DEVICE.
"""

import json

from .doors import _Door
from .result import fail, ok

__all__ = ["ScreenDoor", "HARD_DENY", "SERVICE_CLASS", "FEATURE"]

FEATURE = "accessibility"
SERVICE_CLASS = "com.erfan.standaloneai.PyAccessibilityService"
MAX_NODES = 250
MAX_TEXT = 4000
HARD_DENY = frozenset({
    "com.android.settings", "com.android.packageinstaller", "com.google.android.packageinstaller",
    "com.samsung.android.packageinstaller", "com.miui.packageinstaller", "com.android.permissioncontroller",
    "com.google.android.permissioncontroller", "com.android.vending", "com.android.systemui",
    "com.google.android.gms", "com.android.shell"})
_GLOBAL_ACTIONS = ("back", "home", "recents", "notifications")


class ScreenDoor(_Door):
    def __init__(self, jvm, allowed_fn=None):
        super().__init__(jvm)
        self._allowed_fn = allowed_fn or (lambda: frozenset())

    # ---- plumbing ---------------------------------------------------------------------------------------------
    def _service(self):
        return self._jvm.jclass(SERVICE_CLASS)

    def _check(self, *, allow_any_app=False):
        """None when it is fine to act now, else the `DoorResult` that says why not."""
        service = self._service()
        if not bool(service.isConnected()):
            return fail("not_enabled", "سرویس «دسترس‌پذیری» روشن نیست؛ باید خودت در تنظیمات اندروید روشنش کنی.", needs="accessibility_service")
        package = str(service.activePackage() or "")
        if allow_any_app:
            return None
        if not package:
            return fail("no_window", "پنجرهٔ فعالی دیده نمی‌شود.")
        if package in HARD_DENY:
            return fail("not_allowed", "این برنامه (%s) هیچ‌وقت خودکار کنترل نمی‌شود." % package[:60])
        try:
            allowed = frozenset(self._allowed_fn() or ())
        except Exception:
            allowed = frozenset()
        if package not in allowed:
            return fail("not_allowed", "تو هنوز اجازه نداده‌ای به برنامهٔ «%s» سر بزنم." % package[:60], needs="user_allow:" + package)
        return None

    # ---- reading ----------------------------------------------------------------------------------------------
    def status(self):
        def run():
            service = self._service()
            connected = bool(service.isConnected())
            package = str(service.activePackage() or "") if connected else ""
            return ok({"enabled": connected, "package": package})
        return self._run(run, feature=FEATURE)

    def active_package(self):
        def run():
            refusal = self._check(allow_any_app=True)
            if refusal is not None:
                return refusal
            return ok({"package": str(self._service().activePackage() or "")})
        return self._run(run, feature=FEATURE)

    def read(self, max_nodes=150):
        if not isinstance(max_nodes, int) or isinstance(max_nodes, bool) or not 1 <= max_nodes <= MAX_NODES:
            return fail("bad_arguments", "حداکثر تعداد گره باید بین ۱ و %d باشد." % MAX_NODES)

        def run():
            refusal = self._check()
            if refusal is not None:
                return refusal
            raw = self._service().readScreen(max_nodes)
            if raw is None:
                return fail("no_window", "صفحه‌ای برای خواندن نیست.")
            try:
                parsed = json.loads(str(raw)[:400_000])
            except (ValueError, RecursionError):
                return fail("java_error", "خروجی خواندن صفحه معتبر نبود.")
            return ok(_clean_screen(parsed, max_nodes))
        return self._run(run, feature=FEATURE)

    # ---- acting -----------------------------------------------------------------------------------------------
    def click(self, text="", exact=False, view_id="", last=False):
        """Press the first (or, with `last`, the LAST) button on the screen whose text/description contains `text`."""
        text, view_id = str(text or "")[:200], str(view_id or "")[:200]
        if not text and not view_id:
            return fail("bad_arguments", "برای کلیک باید متن یا شناسهٔ دکمه داده شود.")

        def run():
            refusal = self._check()
            if refusal is not None:
                return refusal
            done = bool(self._service().clickNode(text, bool(exact), view_id, bool(last)))
            return ok({"clicked": True}) if done else fail("not_found", "دکمه‌ای با این مشخصات روی صفحه پیدا نشد.")
        return self._run(run, feature=FEATURE)

    def set_text(self, text, hint="", view_id=""):
        text = str(text if text is not None else "")
        if len(text) > MAX_TEXT * 4:
            return fail("too_large", "متن برای نوشتن در فیلد بزرگ است.")

        def run():
            refusal = self._check()
            if refusal is not None:
                return refusal
            done = bool(self._service().setText(str(hint or "")[:200], str(view_id or "")[:200], text))
            return ok({"chars": len(text)}) if done else fail("not_found", "فیلد متنیِ قابل‌نوشتن روی صفحه پیدا نشد.")
        return self._run(run, feature=FEATURE)

    def key(self, name):
        if name not in _GLOBAL_ACTIONS:
            return fail("bad_arguments", "کلید ناشناخته است.")

        def run():
            refusal = self._check(allow_any_app=True)
            if refusal is not None:
                return refusal
            return ok({"key": name}) if bool(self._service().globalAction(name)) else fail("java_error", "اندروید این کلید را اجرا نکرد.")
        return self._run(run, feature=FEATURE)

    def scroll(self, forward=True):
        def run():
            refusal = self._check()
            if refusal is not None:
                return refusal
            return ok({"scrolled": True}) if bool(self._service().scroll(bool(forward))) else fail("not_found", "چیزی برای اسکرول پیدا نشد.")
        return self._run(run, feature=FEATURE)


def _clean_screen(parsed, max_nodes):
    """The screen as plain, bounded data: password fields lose their text; only known keys survive."""
    if not isinstance(parsed, dict):
        return {"package": "", "nodes": [], "texts": [], "truncated": False}
    nodes = []
    for raw in list(parsed.get("nodes") or [])[:max_nodes]:
        if not isinstance(raw, dict):
            continue
        password = bool(raw.get("p"))
        node = {"text": "" if password else str(raw.get("t") or "")[:MAX_TEXT], "desc": "" if password else str(raw.get("d") or "")[:300],
                "id": str(raw.get("id") or "")[:120], "cls": str(raw.get("c") or "")[:80], "clickable": bool(raw.get("k")),
                "editable": bool(raw.get("e")), "focused": bool(raw.get("f")), "scrollable": bool(raw.get("s")), "password": password}
        box = raw.get("b")
        if isinstance(box, list) and len(box) == 4 and all(isinstance(v, int) and not isinstance(v, bool) for v in box):
            node["bounds"] = list(box)
        nodes.append(node)
    texts = [n["text"] for n in nodes if n["text"].strip() and not n["editable"]]
    return {"package": str(parsed.get("package") or "")[:150], "nodes": nodes, "texts": texts, "truncated": bool(parsed.get("truncated"))}
