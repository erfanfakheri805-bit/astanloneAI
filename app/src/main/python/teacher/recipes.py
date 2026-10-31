"""
teacher.recipes - how to ask a given assistant APP, as data
===========================================================
A recipe is a short list of steps from a CLOSED vocabulary - data, not code - so a recipe that comes inside a pack can never
do more than: open the assistant's app, wait, type a text into its message field, press a button, scroll, press back/home and
read the screen. The runner drives them through the `screen` door (so everything the door enforces applies: the accessibility
service must be on, the app must have been allowed by the user, deny-listed apps are never touched, password fields are never
read).

    {"assistant": "chatgpt", "title_fa": "...", "package": "<optional: only for an app not in the catalog>",
     "steps": [{"op": "open"}, {"op": "wait", "seconds": 3}, {"op": "type", "text": "{request}", "hint_any": ["Message", ""]},
               {"op": "click", "any": ["Send"]}, {"op": "wait_stable", "seconds": 4, "max_seconds": 150}, {"op": "read"}, {"op": "capture"}]}

UNVERIFIED ON DEVICE: no real assistant app was driven in this delivery. The default recipe is a generic guess (find a text
field, type, press something called "Send", wait until the screen stops changing, read it). Real apps differ and change; when a
recipe fails the app says so and offers the manual route, and a better recipe can be added as a pack.
"""

import hashlib
import time

from native_bridge.doors import valid_https_url, valid_package

__all__ = ["DEFAULT_RECIPE", "validate", "RecipeRunner", "RecipeResult", "extract_answer", "MAX_STEPS", "OPS"]

MAX_STEPS = 40
MAX_TOTAL_SECONDS = 600
MAX_NEEDLES = 8
STOP_WORDS = ("stop generating", "stop streaming", "stop responding", "توقف", "stop")
OPS = {
    "open": (), "wait": ("seconds",), "wait_for_text": ("any", "seconds", "optional"), "type": ("text", "hint_any"),
    "click": ("any", "exact", "last", "optional"), "wait_stable": ("seconds", "max_seconds"), "read": (),
    "scroll": ("times", "forward"), "key": ("name",), "capture": (), "capture_clipboard": (),
}
_KEYS = ("back", "home", "recents", "notifications")

DEFAULT_RECIPE = {
    "assistant": "", "title_fa": "روش عمومی برای برنامه‌های گفتگو", "version": 1,
    "steps": [
        {"op": "open"},
        {"op": "wait_for_text", "any": ["Message", "Ask", "Type", "Reply", "پیام", "بپرس", "بنویس"], "seconds": 25, "optional": True},
        {"op": "type", "text": "{request}", "hint_any": ["Message", "Ask anything", "Ask", "Type a message", "Reply", "پیام", "بپرسید", ""]},
        {"op": "click", "any": ["Send message", "Send", "ارسال", "Submit"], "exact": False},
        {"op": "wait", "seconds": 4},
        {"op": "wait_stable", "seconds": 4, "max_seconds": 150},
        {"op": "read"},
        {"op": "capture"},
    ]}


def _needles(value, name):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_NEEDLES or not all(isinstance(v, str) and len(v) <= 60 for v in value):
        raise ValueError("«%s» باید فهرستی از ۱ تا %d متن کوتاه باشد" % (name, MAX_NEEDLES))
    return [str(v) for v in value]


def _seconds(value, name, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= high:
        raise ValueError("«%s» باید عددی بین ۰ و %d باشد" % (name, high))
    return float(value)


def validate(recipe):
    """The normalized recipe, or `ValueError` with a Persian reason. Pure data check; nothing is run."""
    if not isinstance(recipe, dict):
        raise ValueError("دستور باید یک شیء (dict) باشد")
    steps = recipe.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError("تعداد گام‌ها باید بین ۱ و %d باشد" % MAX_STEPS)
    package = recipe.get("package")
    if package is not None and not valid_package(package):
        raise ValueError("نام بستهٔ برنامه معتبر نیست")
    site = recipe.get("site")
    if site is not None and not valid_https_url(site):
        raise ValueError("نشانی سایت باید https معتبر باشد")
    out = []
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict) or step.get("op") not in OPS:
            raise ValueError("گام %d: عمل ناشناخته" % i)
        op, allowed = step["op"], OPS[step["op"]]
        extra = set(step) - set(allowed) - {"op"}
        if extra:
            raise ValueError("گام %d: کلید ناشناخته %s" % (i, sorted(extra)[0][:20]))
        norm = {"op": op}
        try:
            if op in ("wait", "wait_for_text", "wait_stable"):
                norm["seconds"] = _seconds(step.get("seconds", 2 if op != "wait_stable" else 4), "seconds", 60)
            if op == "wait_stable":
                norm["max_seconds"] = _seconds(step.get("max_seconds", 120), "max_seconds", 300)
            if op in ("wait_for_text", "click"):
                norm["any"] = _needles(step.get("any"), "any")
                norm["optional"] = bool(step.get("optional", False))
            if op == "click":
                norm["exact"], norm["last"] = bool(step.get("exact", False)), bool(step.get("last", False))
            if op == "type":
                text = step.get("text", "{request}")
                if not isinstance(text, str) or len(text) > 300:
                    raise ValueError("«text» باید متن کوتاه یا {request} باشد")
                norm["text"] = text
                norm["hint_any"] = _needles(step.get("hint_any", [""]), "hint_any")
            if op == "scroll":
                times = step.get("times", 1)
                if isinstance(times, bool) or not isinstance(times, int) or not 1 <= times <= 10:
                    raise ValueError("«times» باید بین ۱ و ۱۰ باشد")
                norm["times"], norm["forward"] = times, bool(step.get("forward", True))
            if op == "key":
                if step.get("name") not in _KEYS:
                    raise ValueError("«name» باید یکی از %s باشد" % "، ".join(_KEYS))
                norm["name"] = step["name"]
        except ValueError as exc:
            raise ValueError("گام %d (%s): %s" % (i, op, exc)) from None
        out.append(norm)
    return {"assistant": str(recipe.get("assistant") or "")[:30], "title_fa": str(recipe.get("title_fa") or "")[:80], "version": int(recipe.get("version") or 1),
            "package": package, "site": site, "steps": out}


class RecipeResult:
    def __init__(self, ok, code, detail_fa="", text="", steps_done=0):
        self.ok, self.code, self.detail_fa, self.text, self.steps_done = ok, code, detail_fa, text, steps_done

    def to_dict(self):
        return {"ok": self.ok, "code": self.code, "detail_fa": self.detail_fa, "chars": len(self.text), "steps_done": self.steps_done}


def _contains(texts, needles):
    low = [t.casefold() for t in texts if t]
    return any(n.casefold() in t for n in needles for t in low if n)


def extract_answer(texts, request):
    """The answer part of a chat screen: texts that are not the echo of our own request nor short interface labels."""
    request = " ".join(str(request or "").split())
    head = request[:40]
    out = []
    for text in texts:
        flat = " ".join(str(text).split())
        if len(flat) <= 12 or (head and flat.startswith(head)) or (len(flat) > 30 and flat in request):
            continue
        out.append(str(text).strip())
    return "\n".join(out)


class RecipeRunner:
    """Runs a validated recipe through the doors. Never raises; a failure is a `RecipeResult` with an exact code."""

    def __init__(self, doors, *, sleep=time.sleep, clock=time.monotonic, cancelled=None, progress=None):
        self._doors, self._sleep, self._clock = doors, sleep, clock
        self._cancelled = cancelled or (lambda: False)
        self._progress = progress or (lambda note: None)
        self._screen, self._texts, self._request = None, [], ""

    def _nap(self, seconds):
        end = self._clock() + seconds
        while self._clock() < end:
            if self._cancelled():
                return False
            self._sleep(min(0.5, max(0.0, end - self._clock())))
        return not self._cancelled()

    def _read(self, limit=250):
        result = self._doors.screen.read(limit)
        if result.ok:
            self._screen = result.data
            self._texts = list(result.data.get("texts") or ()) + [n.get("desc") for n in result.data.get("nodes", ()) if n.get("desc")]
        return result

    def run(self, recipe, request_text, package):
        try:
            recipe = validate(recipe)
        except ValueError as exc:
            return RecipeResult(False, "bad_recipe", str(exc))
        package = recipe.get("package") or package
        self._request = str(request_text or "")
        started, total = self._clock(), 0
        answer = ""
        for index, step in enumerate(recipe["steps"], 1):
            if self._cancelled():
                return RecipeResult(False, "cancelled", "متوقف شد.", answer, total)
            if self._clock() - started > MAX_TOTAL_SECONDS:
                return RecipeResult(False, "timeout", "کلِ کار از %d ثانیه بیشتر شد." % MAX_TOTAL_SECONDS, answer, total)
            self._progress("گام %d از %d: %s" % (index, len(recipe["steps"]), step["op"]))
            failure = self._step(step, request_text, package)
            if isinstance(failure, str):
                answer = failure
            elif failure is not None:
                failure.steps_done = total
                failure.text = answer
                return failure
            total += 1
        return RecipeResult(True, "ok", "", answer, total)

    # ---- one step: returns None (fine), a str (the captured text), or a failing RecipeResult ----------------------------
    def _step(self, step, request_text, package):
        op, d = step["op"], self._doors
        if op == "open":
            result = d.share.open_app(package) if package else None
            if result is None:
                return RecipeResult(False, "no_package", "برای این دستیار نام برنامه‌ای نیست.")
            return None if result.ok else RecipeResult(False, "open_failed", result.detail_fa or "برنامه باز نشد.")
        if op == "wait":
            return None if self._nap(step["seconds"]) else RecipeResult(False, "cancelled", "متوقف شد.")
        if op == "wait_for_text":
            end = self._clock() + step["seconds"]
            while True:
                r = self._read(80)
                if not r.ok and r.code in ("not_enabled", "native_feature_missing", "unavailable_platform", "not_allowed"):
                    return RecipeResult(False, r.code, r.detail_fa)
                if r.ok and _contains(self._texts, step["any"]):
                    return None
                if self._clock() >= end or not self._nap(1.0):
                    return None if step["optional"] else RecipeResult(False, "timeout", "متن مورد انتظار روی صفحه نیامد.")
        if op == "type":
            text = step["text"].replace("{request}", request_text)
            last = None
            for hint in step["hint_any"]:
                last = d.screen.set_text(text, hint=hint)
                if last.ok:
                    return None
                if last.code in ("not_enabled", "not_allowed", "native_feature_missing", "unavailable_platform"):
                    break
            return RecipeResult(False, last.code if last else "no_input", (last.detail_fa if last else "") or "فیلد پیام پیدا نشد.")
        if op == "click":
            last = None
            for needle in step["any"]:
                last = d.screen.click(needle, step["exact"], "", step["last"])
                if last.ok:
                    return None
                if last.code in ("not_enabled", "not_allowed", "native_feature_missing", "unavailable_platform"):
                    break
            if step["optional"]:
                return None
            return RecipeResult(False, last.code if last else "no_button", (last.detail_fa if last else "") or "دکمه پیدا نشد.")
        if op == "wait_stable":
            return self._wait_stable(step)
        if op == "read":
            r = self._read()
            return None if r.ok else RecipeResult(False, r.code, r.detail_fa)
        if op == "scroll":
            for _ in range(step["times"]):
                d.screen.scroll(step["forward"])
                if not self._nap(0.6):
                    return RecipeResult(False, "cancelled", "متوقف شد.")
            return None
        if op == "key":
            r = d.screen.key(step["name"])
            return None if r.ok else RecipeResult(False, r.code, r.detail_fa)
        if op == "capture":
            text = extract_answer(self._texts, self._request)
            return text if text.strip() else RecipeResult(False, "empty", "از صفحه متنی برای برداشتن پیدا نشد.")
        if op == "capture_clipboard":
            r = d.clipboard.get_text()
            return r.data["text"] if r.ok else RecipeResult(False, r.code, r.detail_fa)
        return RecipeResult(False, "bad_recipe", "گام ناشناخته.")

    def _wait_stable(self, step):
        quiet, limit = step["seconds"], step["max_seconds"]
        started = self._clock()
        last_sig, last_change = None, self._clock()
        while self._clock() - started <= limit:
            r = self._read()
            if not r.ok:
                if r.code in ("not_enabled", "not_allowed", "native_feature_missing", "unavailable_platform"):
                    return RecipeResult(False, r.code, r.detail_fa)
            else:
                signature = hashlib.sha1("\n".join(self._texts).encode("utf-8", "replace")).hexdigest()
                if signature != last_sig:
                    last_sig, last_change = signature, self._clock()
                generating = _contains([t for t in self._texts if len(t) <= 40], STOP_WORDS)
                if not generating and self._clock() - last_change >= quiet:
                    return None
            if not self._nap(1.0):
                return RecipeResult(False, "cancelled", "متوقف شد.")
        return RecipeResult(False, "timeout", "پاسخ تا %d ثانیه تمام نشد." % limit)
