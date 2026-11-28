"""
brain_hub.body - the app's BODY: what keeps a long job alive, and the one thing that stops everything  (Prompt 959, stage B)
============================================================================================================================
Two jobs, both small:

1. KEEP A LONG JOB ALIVE. While the own brain is downloaded (2.6 GB, many minutes) Android may kill an app that is not on the screen - and a
   phone that saves battery the way HyperOS does kills it fast. The body tells the phone's ONE foreground service (`BodyService.java`, reached
   through the app-only door `native_bridge.body.BodyDoor`) what is running: a job is registered with a title, a line of text and a percent, the
   service shows ONE notification with a stop button «ایست», and when the last job ends the service goes away. The body is the OwnBrain's
   notifier (`on_ownbrain`): «downloading» / «installing» keep the service, every other phase lets it go.

2. THE EMERGENCY STOP («ایست»). `emergency_stop()` stops everything that runs for this hub: the own brain's download (its sockets are cut at
   once, what was fetched stays), the answer a local model may be making (the engine's own cancel - a request, never a kill; the model manager
   only says how many loaded engines it ASKED, not whether one was answering, so the name is "engine" and nothing more is claimed), the cloud
   brain (it is only halted when it was switched on: the same flag the chat word «ایست» sets) - and then the service is released. The notification's
   button (`StopReceiver.java` -> `platform_boot.emergency_stop` -> `emergency_stop_all`) and the chat word run the same code, so there is one
   meaning of «ایست».

What it never does: it starts nothing by itself (a job exists only because the own brain, which the user agreed to, is running), it keeps no
text of the user, and a door that can never work in this build (an APK without the native piece, a desktop run) is not called again.
Every public method is safe to call from any thread and never raises.
"""

import re
import threading
import time

__all__ = ["Body", "get_body", "peek_body", "emergency_stop_all", "describe_ownbrain", "JOB_OWNBRAIN", "MAX_JOBS", "MIN_GAP_SECONDS"]

JOB_OWNBRAIN = "ownbrain"
MAX_JOBS = 8
MIN_GAP_SECONDS = 1.5                      # a progress update of the notification is passed on at most this often (a change of kind always goes through)
MAX_TITLE, MAX_TEXT = 60, 160              # = native_bridge.body.MAX_TITLE / MAX_TEXT (a test keeps them equal)
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}\Z")
# answers of the door after which calling it again is pointless: this APK / this platform cannot have the service
_PERMANENT = frozenset({"unavailable_platform", "native_feature_missing", "bad_class_name"})
_GB, _MB = 1_000_000_000, 1_000_000
_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa(value):
    return str(value).translate(_DIGITS).replace(".", "٫")


def _size(n):
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        return ""
    if n >= _GB:
        return "%s گیگابایت" % _fa(round(n / _GB, 1))
    if n >= _MB:
        return "%s مگابایت" % _fa((n + _MB // 2) // _MB)
    return "%s کیلوبایت" % _fa(max(1, (n + 500) // 1000))


def _eta(seconds):
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0:
        return ""
    if seconds < 60:
        return "کمتر از یک دقیقه مانده"
    minutes = (seconds + 30) // 60                  # half-up (Python's round() goes to the even number: 150 s would be 2 minutes, 210 s 4)
    if minutes < 60:
        return "حدود %s دقیقه مانده" % _fa(minutes)
    hours, rest = divmod(minutes, 60)
    return "حدود %s ساعت%s مانده" % (_fa(hours), (" و %s دقیقه" % _fa(rest)) if rest else "")


def _whole(value, default=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        return default
    return int(value)


def _elapsed(seconds):
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds != seconds or seconds in (float("inf"), float("-inf")) or seconds < 0:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return "%s ثانیه" % _fa(seconds)
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return "%s دقیقه%s" % (_fa(minutes), (" و %s ثانیه" % _fa(rest)) if rest else "")
    hours, minutes = divmod(minutes, 60)
    return "%s ساعت%s" % (_fa(hours), (" و %s دقیقه" % _fa(minutes)) if minutes else "")


_INSTALL_STEPS_FA = {"verify": "بررسیِ فایل", "compatibility": "سازگاری", "load": "بارگذاریِ مغز", "smoke": "آزمایشِ اول"}


def _describe_install(inst):
    """The notification of the install step from `status()["install"]`, or None when that holds no step yet (an older status, or the file is just
    being registered). The percent is the service's; «حدودی» marks the steps whose percent is an estimate; the time is what really passed."""
    if not isinstance(inst, dict) or _whole(inst.get("step")) < 1 or _whole(inst.get("steps")) < 1:
        return None
    percent, stage = max(0, min(100, _whole(inst.get("percent")))), inst.get("stage")
    parts = ["%s٪%s" % (_fa(percent), " (حدودی)" if inst.get("estimated") else ""),
             "مرحلهٔ %s از %s: %s" % (_fa(_whole(inst.get("step"))), _fa(_whole(inst.get("steps"))),
                                     _INSTALL_STEPS_FA.get(stage, "…") if isinstance(stage, str) else "…")]
    passed = _elapsed(inst.get("elapsed"))
    if passed:
        parts.append(passed)
    return "در حال نصبِ مغز", " · ".join(parts), percent


def describe_ownbrain(status):
    """`(title, text, percent)` of the notification for the own brain's `status()`; percent is -1 when it cannot be told. Pure."""
    phase = str((status or {}).get("phase") or "")
    if phase == "installing":
        described = _describe_install((status or {}).get("install"))
        if described is not None:
            return described
        return "در حال نصبِ مغز", "فایل بررسی و مغز آزمایش می‌شود؛ چند دقیقه طول می‌کشد.", -1
    have, total = int((status or {}).get("bytes") or 0), int((status or {}).get("total") or 0)
    percent = max(0, min(100, int((status or {}).get("percent") or 0))) if total > 0 else -1
    if str((status or {}).get("sub") or "") == "verify":
        return "در حال گرفتنِ مغز", "فایلِ گرفته‌شده با اثرِ انگشتش مقایسه می‌شود (هش).", percent
    parts = []
    if percent >= 0:
        parts.append("%s٪" % _fa(percent))
    if total > 0:
        parts.append("%s از %s" % (_size(have) or "۰", _size(total)))
    eta = _eta((status or {}).get("eta"))
    if eta:
        parts.append(eta)
    return "در حال گرفتنِ مغز", " · ".join(parts) or "شروع شد…", percent


class Body:
    def __init__(self, hub, *, doors=None, monotonic=time.monotonic):
        self._hub = hub
        self._doors = doors                    # an object with `.body` (the real one is made on first use)
        self._mono = monotonic
        self._lock = threading.RLock()         # the state below
        self._io = threading.Lock()            # one door call at a time (a late "hold" must never come after a "release")
        self._jobs = {}                        # name -> {"title", "text", "percent", "order"}
        self._order = 0
        self._holding = False                  # does the phone's service run because of us (the last answer of the door)
        self._last = None                      # (title, text, percent) the door last took
        self._last_at = 0.0
        self._code = ""                        # the door's last answer ("" = none yet)
        self._dead = ""                        # a code from `_PERMANENT`: the door is not called again

    # ================================================================== the door
    def _door(self):
        doors = self._doors
        if doors is None:
            from native_bridge import facade
            doors = self._doors = facade.for_app(self._hub)
        return doors.body

    def _wanted(self):
        """The notification the jobs ask for - `(title, text, percent, more)` where `more` is the number of other jobs - or None when there is
        no job. Called under `_lock`. The text of the first job gives way to the «and N other jobs» note, never the other way round."""
        if not self._jobs:
            return None
        ordered = sorted(self._jobs.values(), key=lambda job: job["order"])
        first, more = ordered[0], len(ordered) - 1
        note = (" · و %s کارِ دیگر" % _fa(more)) if more else ""
        return first["title"][:MAX_TITLE], first["text"][:max(0, MAX_TEXT - len(note))] + note, first["percent"], more

    def _sync(self, force=False):
        """Make the phone's service match the jobs: hold (or update) it, or release it. One door call at a time; never raises."""
        try:
            with self._io:
                with self._lock:
                    want, holding, last, last_at, dead = self._wanted(), self._holding, self._last, self._last_at, self._dead
                now = self._mono()
                if want is None:
                    if not holding:
                        return
                    result = self._door().release()
                    with self._lock:
                        self._code = str(getattr(result, "code", ""))
                        self._holding, self._last = False, None
                    return
                if dead:
                    return
                if not force and want == last and holding:
                    return
                if not force and holding and last is not None and want[0] == last[0] and want[3] == last[3] and now - last_at < MIN_GAP_SECONDS:
                    return                      # the same job moved a little, and the last update was a moment ago (a new or ended job always goes through)
                result = self._door().hold(want[0], want[1], want[2])
                code = str(getattr(result, "code", ""))
                with self._lock:
                    self._code = code
                    if getattr(result, "ok", False):
                        self._holding, self._last, self._last_at = True, want, now
                    else:
                        self._holding = False
                        if code in _PERMANENT:
                            self._dead = code
        except Exception:
            pass

    # ================================================================== jobs
    def job(self, name, title, text="", percent=-1):
        """Register (or update) a long job. A false return means nothing was registered (a bad name or too many jobs)."""
        try:
            if not isinstance(name, str) or not _NAME_RE.match(name):
                return False
            title = " ".join(str(title or "").split())[:MAX_TITLE]
            text = " ".join(str(text or "").split())[:MAX_TEXT]
            if not title or isinstance(percent, bool) or not isinstance(percent, int) or not -1 <= percent <= 100:
                return False
            with self._lock:
                if name not in self._jobs:
                    if len(self._jobs) >= MAX_JOBS:
                        return False
                    self._order += 1
                    self._jobs[name] = {"order": self._order}
                self._jobs[name].update(title=title, text=text, percent=percent)
        except Exception:
            return False
        self._sync()
        return True

    def done(self, name):
        """The job ended (or never ran): drop it. The service goes away with the last job. True when there was such a job."""
        with self._lock:
            had = self._jobs.pop(name, None) is not None
        self._sync()
        return had

    def jobs(self):
        with self._lock:
            return sorted(self._jobs)

    def on_ownbrain(self, status):
        """The own brain's notifier: the service stays while it downloads or installs, and goes when it does not."""
        try:
            phase = str((status or {}).get("phase") or "")
            if phase in ("downloading", "installing"):
                title, text, percent = describe_ownbrain(status)
                self.job(JOB_OWNBRAIN, title, text, percent)
            else:
                self.done(JOB_OWNBRAIN)
        except Exception:
            pass

    def status(self):
        """`{holding, jobs, code, dead}` - what the body believes (the phone's own answer is `running()`)."""
        with self._lock:
            return {"holding": self._holding, "jobs": sorted(self._jobs), "code": self._code, "dead": self._dead}

    def running(self):
        """Does the phone say the service is running? `None` when the door cannot tell (not in an app, an older APK). Never raises."""
        try:
            result = self._door().running()
            if getattr(result, "ok", False):
                return bool((getattr(result, "data", None) or {}).get("running"))
        except Exception:
            pass
        return None

    # ================================================================== the emergency stop
    def emergency_stop(self):
        """«ایست»: stop everything that runs for this hub, then let the service go. `{"stopped": [...], "released": bool}`: the names of what
        was stopped or asked to stop ("download", "engine" = a loaded local model's engine was asked to drop the answer it makes, "cloud") and
        whether the foreground service was up and has been released. Never raises. The stops come first - the service (a call into Java) is
        released last.

        One step is left alone: while the own brain INSTALLS a finished download (verify, load, the first test question) nothing can be
        interrupted - the first test question is part of that step, and asking the engine to drop it would only make the brain's first test
        fail. The engine is not asked, the job and the service stay (the install goes on, so does its notification) and the answer carries
        `"busy": True` (the key is there ONLY then): `{"stopped": [...], "released": False, "busy": True}`. The cloud brain is still halted."""
        hub, stopped = self._hub, []
        brain = getattr(hub, "_own_brain", None)
        try:
            if brain is not None and brain.halt():
                stopped.append("download")
        except Exception:
            pass
        installing = _installing(brain)                          # asked AFTER the halt: a download that has just ended is installing now
        if not installing:
            try:
                if int(hub.cancel_model_generation() or 0) > 0:
                    stopped.append("engine")
            except Exception:
                pass
        try:
            if _halt_cloud(hub):
                stopped.append("cloud")
        except Exception:
            pass
        if installing:
            return {"stopped": stopped, "released": False, "busy": True}
        with self._lock:
            held = self._holding
            self._jobs.clear()
        self._sync(force=True)
        return {"stopped": stopped, "released": bool(held)}


def _installing(brain):
    """True while the own brain verifies, loads and first-tests a finished download (`status()["phase"] == "installing"`): the step that cannot
    be interrupted (docs/own_brain_prompt959.md; the chat's «ایست» says so). A brain that cannot say counts as not installing. Never raises."""
    try:
        return brain is not None and brain.status().get("phase") == "installing"
    except Exception:
        return False


def _halt_cloud(hub):
    """Halt the cloud brain only when it is switched on and not halted already (nothing is created or written for an app that never used it)."""
    from brain_v2 import get_brain
    brain = get_brain(hub)
    if brain is None:
        return False
    settings = brain.settings.get()
    if settings.get("mode") != "auto" or settings.get("halted"):
        return False
    brain.halt()
    return True


# ====================================================================================================== module API
_GET_LOCK = threading.Lock()


def get_body(hub, **kwargs):
    """The one `Body` of this hub (created on first use; nothing is written, nothing is called), or None for something that is not a hub.
    `kwargs` (tests: fake doors) only count for the call that creates it."""
    if hub is None or not hasattr(hub, "root") or not hasattr(hub, "cancel_model_generation"):
        return None
    body = getattr(hub, "_body", None)
    if isinstance(body, Body):
        return body
    with _GET_LOCK:
        body = getattr(hub, "_body", None)
        if not isinstance(body, Body):
            body = Body(hub, **kwargs)
            try:
                hub._body = body
            except Exception:
                return body
        return body


def peek_body(hub):
    """The `Body` of this hub if it has one already, else None (nothing is created)."""
    body = getattr(hub, "_body", None) if hub is not None else None
    return body if isinstance(body, Body) else None


def emergency_stop_all():
    """The emergency stop for every hub of this process (the notification's button reaches Python without a chat behind it). Returns
    `{"hubs": n, "stopped": [names...], "released": bool}` where `n` is the number of hubs the stop was SENT to (a hub whose stop failed was
    still asked); with `"busy": True` added - and only then - while a step that cannot be interrupted (the own brain's install) still runs in
    one of them. Never raises."""
    names, count, released, busy = [], 0, False, False
    try:
        from . import service
        hubs = service.live_hubs()
    except Exception:
        hubs = []
    for hub in hubs:
        try:
            body = get_body(hub)
            if body is None:
                continue
            count += 1
            done = body.emergency_stop()
            released = released or bool(done.get("released"))
            busy = busy or bool(done.get("busy"))
            for name in done["stopped"]:
                if name not in names:
                    names.append(name)
        except Exception:
            continue
    result = {"hubs": count, "stopped": names, "released": released}
    if busy:
        result["busy"] = True
    return result
