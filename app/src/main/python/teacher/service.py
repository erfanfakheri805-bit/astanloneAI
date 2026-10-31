"""
teacher.service - asking another assistant for what the app cannot do itself
===========================================================================
One `TeacherService` per app folder. It never decides anything for the user; the chat commands (see `persian_brain.hub_teacher`)
ask the user first and call it:

    draft(wish, kind, assistant)   build the request text and remember the mission (nothing leaves the app)
    deliver(mission, route)        hand the request to the assistant: through the share sheet straight into its app, by copying it
                                   and opening the app, or by copying it and opening its website
    start_screen_run(mission)      (optional, user-enabled accessibility service + the user's per-app allowance) type the request
                                   into the assistant's app and read the answer back, in the background
    capture(mission)               find the answer: what the screen run read, a text shared into the inbox, the clipboard
    allow_app / revoke / allowed   the apps the user lets the assistant look into, each for a limited time

Everything the assistant sends back is only TEXT: a pack goes through the pack system's own review (static scan, versioning, the
user's «بله»), an answer is shown to the user. Nothing is run or installed here.
"""

import os
import threading
import time

from native_bridge import facade as native_facade
from native_bridge.doors import MAX_SHARE_CHARS

from . import assistants as A
from . import capture as C
from . import recipes as RC
from . import request as R
from .store import OPEN_STATES, TeacherStore

__all__ = ["TeacherService", "get_service", "reset_for_tests", "OWN_PACKAGE", "DEFAULT_ORDER"]

OWN_PACKAGE = "com.erfan.standaloneai"
DEFAULT_ORDER = ("chatgpt", "claude", "gemini", "copilot", "perplexity", "deepseek", "grok")
_SERVICES = {}
_SERVICES_LOCK = threading.Lock()


def _ok(code, detail_fa="", **extra):
    out = {"ok": True, "code": code, "detail_fa": detail_fa}
    out.update(extra)
    return out


def _no(code, detail_fa="", **extra):
    out = {"ok": False, "code": code, "detail_fa": detail_fa}
    out.update(extra)
    return out


class TeacherService:
    def __init__(self, root, doors=None, *, registry=None, hub=None, clock=time.time, sleep=time.sleep, monotonic=time.monotonic,
                 inbox_dir=None, run_async=True):
        self.root = os.fspath(root)
        self.store = TeacherStore(root, clock)
        self._doors, self._registry, self._hub = doors, registry, hub
        self._clock, self._sleep, self._monotonic = clock, sleep, monotonic
        self._inbox = inbox_dir
        self._run_async = run_async
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread = None
        self._screen_text = {}            # mission id -> text the screen run read (memory only)

    # ---- plumbing -------------------------------------------------------------------------------------------------
    @property
    def doors(self):
        if self._doors is None:
            self._doors = native_facade.for_app(self._hub)
        return self._doors

    def inbox_dir(self):
        if self._inbox:
            return self._inbox
        try:
            return self._hub.inbox_dir()
        except Exception:
            return os.path.join(os.path.dirname(self.root), "inbox")

    def _audit(self, kind, subject, detail=None):
        try:
            self._hub.audit.append(kind, subject, detail or {})
        except Exception:
            pass

    def install_allow_provider(self):
        """Tell the screen door which apps the user currently allowed (the store is the single source)."""
        native_facade.set_allowed_apps_provider(self.store.allowed_now)

    # ---- the assistants ---------------------------------------------------------------------------------------------
    def assistants(self):
        rows = []
        share = self.doors.share
        for a in A.ASSISTANTS:
            visible = share.assistants_visible(a.packages)
            rows.append({"id": a.assistant_id, "title": a.title, "installed": bool(visible), "package": visible[0] if visible else "", "site": a.site})
        return rows

    def default_assistant(self, rows=None):
        rows = rows if rows is not None else self.assistants()
        by_id = {r["id"]: r for r in rows}
        for assistant_id in DEFAULT_ORDER:
            if by_id.get(assistant_id, {}).get("installed"):
                return assistant_id
        return DEFAULT_ORDER[0]

    # ---- a mission ---------------------------------------------------------------------------------------------------
    def draft(self, wish, kind="code", assistant_id=None):
        wish = R.clean_wish(wish)
        if not wish:
            return _no("empty_wish", "متن درخواست خالی است.")
        assistant = A.get(assistant_id) or A.get(self.default_assistant())
        text, kind = R.build(wish, kind, assistant.title)
        mission = self.store.create(kind, wish, assistant.assistant_id, len(text), C.sha16(text))
        self._audit("teacher.draft", mission["id"], {"assistant": assistant.assistant_id, "kind": kind, "chars": len(text)})
        return _ok("drafted", mission=mission, request_chars=len(text), assistant=assistant.assistant_id, title=assistant.title)

    def request_text(self, mission):
        assistant = A.get(mission["assistant"]) or A.get(DEFAULT_ORDER[0])
        text, _kind = R.build(mission["wish"], mission["kind"], assistant.title)
        return text

    def _mission(self, mission_id):
        mission = self.store.get(mission_id) if mission_id else self.store.latest(only_open=True)
        return mission

    # ---- delivering the request ------------------------------------------------------------------------------------------
    def deliver(self, mission_id=None, route=None):
        mission = self._mission(mission_id)
        if mission is None:
            return _no("no_mission", "ماموریت بازی نیست.")
        assistant = A.get(mission["assistant"])
        if assistant is None:
            return _no("no_assistant", "دستیار این ماموریت شناخته نیست.")
        text = self.request_text(mission)
        if C.sha16(text) != mission.get("request_sha"):
            self.store.update(mission["id"], request_sha=C.sha16(text), request_chars=len(text))
        visible = self.doors.share.assistants_visible(assistant.packages)
        package = visible[0] if visible else ""
        route = route if route in ("share", "copy_open", "site") else ("share" if package else "site")
        if route in ("share", "copy_open") and not package:
            route = "site"
        steps, result = [], None
        if route == "share" and len(text) <= MAX_SHARE_CHARS:
            # the share sheet is no proof that the other app put the text into its box: keep a copy on the clipboard as well
            steps.append(("copy", self.doors.clipboard.set_text(text).code))
            r = self.doors.share.send_text(text, package=package)
            steps.append(("share", r.code))
            result = r if r.ok else None
            if result is None:
                route = "copy_open"                       # the app did not take the share: copy and open it instead
        elif route == "share":
            route = "copy_open"
        if result is None and route in ("copy_open", "site"):
            copied = self.doors.clipboard.set_text(text)
            steps.append(("copy", copied.code))
            if not copied.ok:
                self._audit("teacher.deliver", mission["id"], {"route": route, "ok": False, "code": copied.code})
                return _no("copy_failed", copied.detail_fa or "کلیپ‌بورد پر نشد.", steps=steps)
            opened = self.doors.share.open_app(package) if route == "copy_open" else self.doors.share.open_url(assistant.site)
            steps.append(("open", opened.code))
            if not opened.ok:
                self._audit("teacher.deliver", mission["id"], {"route": route, "ok": False, "code": opened.code})
                return _no("open_failed", opened.detail_fa or "باز نشد.", steps=steps, route=route, copied=True)
            result = opened
        self.store.update(mission["id"], route=route, state="sent", note="")
        self._audit("teacher.deliver", mission["id"], {"route": route, "ok": True, "assistant": assistant.assistant_id})
        return _ok("delivered", route=route, steps=steps, assistant=assistant.assistant_id, title=assistant.title, package=package,
                   mission=mission["id"], chars=len(text))

    # ---- the answer ------------------------------------------------------------------------------------------------------
    def capture(self, mission_id=None):
        mission = self._mission(mission_id)
        if mission is None:
            return _no("no_mission", "ماموریت بازی نیست.")
        candidates = []
        screen_text = self._screen_text.get(mission["id"])
        if screen_text:
            candidates.append(("screen", screen_text))
        shared = C.newest_shared_text(self.inbox_dir(), mission["created"] - 5)
        shared_name = ""
        if shared is not None:
            shared_name = shared[0]
            candidates.append(("shared", shared[1]))
        clip = self.doors.clipboard.get_text()
        if clip.ok:
            candidates.append(("clipboard", clip.data["text"]))
        source, text, klass, skipped = C.pick(mission["kind"], candidates, mission.get("request_sha", ""))
        if source is None:
            self._audit("teacher.capture", mission["id"], {"ok": False, "skipped": [list(s) for s in skipped][:4]})
            return _no("nothing", "جوابی پیدا نشد.", skipped=skipped, clipboard_code=clip.code, mission=mission)
        if source == "shared" and shared_name:
            self._retire_shared(shared_name)
        self.store.update(mission["id"], state="captured")
        self._audit("teacher.capture", mission["id"], {"ok": True, "source": source, "class": klass, "chars": len(text)})
        return _ok("captured", source=source, text=text, klass=klass, mission=mission, skipped=skipped)

    def _retire_shared(self, name):
        directory = self.inbox_dir()
        try:
            os.replace(os.path.join(directory, name), os.path.join(directory, "done_" + name))
        except OSError:
            pass

    def finish(self, mission_id, state, note="", answer=None):
        fields = {"state": state, "note": note}
        if answer is not None:
            fields["answer"] = answer
        self._screen_text.pop(mission_id, None)
        return self.store.update(mission_id, **fields)

    def cancel(self):
        self._cancel.set()
        count = self.store.cancel_open()
        self._screen_text.clear()
        return count

    def supersede(self, keep_id):
        """A new mission replaces the open ones: cancel them (and stop a running screen job), keep `keep_id`."""
        if self._thread is not None and self._thread.is_alive():
            self._cancel.set()
        for other in list(self._screen_text):
            if other != keep_id:
                self._screen_text.pop(other, None)
        return self.store.cancel_open(keep=keep_id)

    # ---- the apps the user allowed -------------------------------------------------------------------------------------------
    def allow_app(self, package, minutes=30):
        expires = self.store.allow(package, minutes)
        self._audit("teacher.allow", package, {"minutes": minutes})
        return expires

    def revoke_apps(self, package=None):
        count = self.store.revoke(package)
        self._audit("teacher.revoke", package or "all", {"count": count})
        return count

    def allowed_apps(self):
        return self.store.allow_list()

    # ---- the typing recipe (optional) -----------------------------------------------------------------------------------------
    def recipe_for(self, assistant_id):
        """`(recipe, origin)`: the newest pack-provided recipe for this assistant, else the generic default."""
        best = None
        try:
            registered = self._registry.recipes() if self._registry is not None else {}
        except Exception:
            registered = {}
        for recipe in registered.values():
            if isinstance(recipe, dict) and recipe.get("assistant") == assistant_id:
                try:
                    norm = RC.validate(recipe)
                except ValueError:
                    continue
                if best is None or norm["version"] >= best["version"]:
                    best = norm
        if best is not None:
            return best, "pack"
        return RC.validate(RC.DEFAULT_RECIPE), "default"

    def screen_state(self, mission):
        """Can the typing recipe start now? A dict with `code`: ready / not_enabled / not_allowed / no_app / ..."""
        assistant = A.get(mission["assistant"])
        recipe, _origin = self.recipe_for(mission["assistant"])
        package = recipe.get("package") or (self.doors.share.assistants_visible(assistant.packages) or [""])[0]
        if not package:
            return _no("no_app", "برنامهٔ این دستیار روی گوشی دیده نمی‌شود.")
        status = self.doors.screen.status()
        if not status.ok:
            return _no(status.code, status.detail_fa, needs=status.needs, package=package)
        if not status.data.get("enabled"):
            return _no("not_enabled", "سرویس «دسترس‌پذیری» روشن نیست.", package=package)
        if package not in self.store.allowed_now():
            return _no("not_allowed", "هنوز اجازهٔ سر زدن به این برنامه را نداده‌ای.", package=package)
        return _ok("ready", package=package)

    def start_screen_run(self, mission_id=None):
        mission = self._mission(mission_id)
        if mission is None:
            return _no("no_mission", "ماموریت بازی نیست.")
        state = self.screen_state(mission)
        if not state["ok"]:
            return state
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return _no("busy", "یک اجرای دیگر هنوز در کار است.")
            self._cancel.clear()
            recipe, origin = self.recipe_for(mission["assistant"])
            text = self.request_text(mission)
            self.store.update(mission["id"], route="screen", state="running", note="شروع شد", request_sha=C.sha16(text), request_chars=len(text))
            self._audit("teacher.screen_run", mission["id"], {"assistant": mission["assistant"], "recipe": origin, "package": state["package"]})
            job = lambda: self._screen_job(mission, recipe, text, state["package"])
            if not self._run_async:
                job()
            else:
                self._thread = threading.Thread(target=job, name="teacher-screen-run", daemon=True)
                self._thread.start()
        return _ok("started", package=state["package"], recipe=origin, mission=mission["id"])

    def _screen_job(self, mission, recipe, text, package):
        mission_id = mission["id"]
        try:
            runner = RC.RecipeRunner(self.doors, sleep=self._sleep, clock=self._monotonic, cancelled=self._cancel.is_set,
                                     progress=lambda note: self.store.update(mission_id, note=note))
            result = runner.run(recipe, text, package)
        except Exception as exc:                                    # a recipe can never take the app down
            result = RC.RecipeResult(False, "crashed", type(exc).__name__)
        if result.ok and result.text.strip():
            self._screen_text[mission_id] = result.text
            self.store.update(mission_id, state="captured", note="جواب از صفحه خوانده شد (%d نویسه)" % len(result.text))
        else:
            self.store.update(mission_id, state="sent", note=("ناموفق: " + (result.detail_fa or result.code))[:300])
        self._audit("teacher.screen_run_end", mission_id, {"ok": result.ok, "code": result.code, "steps": result.steps_done, "chars": len(result.text)})
        try:                                                          # bring our own app back to the front, and tell the user
            self.doors.share.open_app(OWN_PACKAGE)
            self.doors.notify.show("دستیار هوشمند", "کار با دستیار بیرونی تمام شد؛ در چت بگو «جواب آمد».")
        except Exception:
            pass

    def run_state(self):
        mission = self.store.latest(only_open=False)
        running = self._thread is not None and self._thread.is_alive()
        return {"running": running, "mission": mission}


def get_service(hub):
    """The service of this hub's folder (created on first use; nothing is written until a mission is made)."""
    try:
        root = os.fspath(hub.root)
    except Exception:
        return None
    with _SERVICES_LOCK:
        service = _SERVICES.get(root)
        if service is None:
            try:
                from pack_system.registry import REGISTRY
                registry = REGISTRY
            except Exception:
                registry = None
            hub_clock = getattr(hub, "clock", None)               # the hub's clock, so every expiry in the app follows one time source
            service = TeacherService(root, registry=registry, hub=hub, clock=hub_clock if callable(hub_clock) else time.time)
            service.install_allow_provider()
            _SERVICES[root] = service
        return service


def reset_for_tests():
    with _SERVICES_LOCK:
        _SERVICES.clear()
