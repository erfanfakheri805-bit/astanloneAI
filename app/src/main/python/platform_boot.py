"""
platform_boot - the Python calls the Android activity makes outside the web page
================================================================================
`MainActivity` (Java) is the only caller, and it names exactly this module (plus `android_entry`), so the Java side stays thin:

    prepare(files_dir)               the FIRST Python call, made BEFORE `android_entry` is imported. It lets the pack system (see
                                     `pack_system`) make the active, user-approved packs importable, run its safe-mode bookkeeping and
                                     returns a small plain dict for the log. It can never keep the app from starting.
    inbox_dir(files_dir)             where files that come from OUTSIDE the web page are put (a model file the user picked with the
                                     file dialog, a text another app shared into this one): `<files dir>/data/brain_hub/inbox` - the
                                     same folder the hub itself calls its inbox (a test keeps the two equal).
    on_shared_text(files_dir, text)  text another app shared INTO this one (the user pressed «Share» in an assistant app and chose this
                                     app). It is saved as `shared_<time>_<id>.txt` in the inbox - nothing more: it is not run, not
                                     installed and not sent anywhere; the chat reads it only when the user says the answer came, or the
                                     user presses send on the copy the page puts into the message box.
                                     Returns a small JSON string for the page.

Kept as a tiny top-level module (no import of the app at import time) so that it is cheap to call and cannot fail on start-up.
"""

import json
import os
import time

__all__ = ["prepare", "inbox_dir", "hub_root", "on_shared_text", "HUB_DIRNAME", "INBOX_DIRNAME", "MAX_SHARED_CHARS", "MAX_OFFERED_CHARS",
           "KEEP_SHARED_FILES"]

HUB_DIRNAME = "brain_hub"                 # = brain_hub.service.ROOT_DIRNAME            (a test keeps them equal)
INBOX_DIRNAME = "inbox"                   # = brain_hub.builtin_tools.INBOX_DIR
MAX_SHARED_CHARS = 400_000                # = teacher.capture.MAX_TEXT_CHARS
KEEP_SHARED_FILES = 12                    # the newest `shared_*.txt` (and the newest `done_shared_*.txt`) that are kept
MAX_OFFERED_CHARS = 200_000               # = the page's MAX_ATTACH_BYTES: a longer shared text is kept in the inbox but not offered to the message box
_OPEN_FOR_CHAT = frozenset({"sent", "running", "captured"})        # = persian_brain.hub_teacher.OPEN_FOR_CHAT
_STALE_PARTIAL_SECONDS = 600


def prepare(files_dir):
    try:
        from pack_system import boot
        return boot.prepare(str(files_dir))
    except BaseException as exc:                                # pragma: no cover - last line of defence
        if isinstance(exc, KeyboardInterrupt):
            raise
        return {"ok": False, "error": type(exc).__name__}


def hub_root(files_dir):
    """`<files dir>/data/brain_hub` - where the brain hub (and the teacher's state) live on the phone."""
    return os.path.join(os.fspath(files_dir), "data", HUB_DIRNAME)


def inbox_dir(files_dir):
    """The inbox folder (nothing is created here)."""
    return os.path.join(hub_root(files_dir), INBOX_DIRNAME)


def on_shared_text(files_dir, text, clock=time.time):
    """Save a text another app shared into this one. Never raises; returns a JSON string:

        {"ok": bool, "code": "saved" | "empty" | "io_error" | "error", "chars": int, "name": str, "truncated": bool,
         "mission_open": bool, "text": str}

    `mission_open` says whether the teacher has a request that is waiting for an answer: then the page tells the chat that the answer came
    (the chat reads the saved file itself) and `text` is empty. Otherwise `text` is the shared text itself (when it is not longer than
    MAX_OFFERED_CHARS) so that the page can put it into the message box for the user to read and send; nothing is sent for him.
    (`clock` is only for tests: it is the teacher's clock.)"""
    result = {"ok": False, "code": "error", "chars": 0, "name": "", "truncated": False, "mission_open": False, "text": ""}
    try:
        if not isinstance(text, str) or not text.strip():
            result["code"] = "empty"
            return json.dumps(result, ensure_ascii=False)
        truncated = len(text) > MAX_SHARED_CHARS
        body = text[:MAX_SHARED_CHARS]
        raw = body.encode("utf-8", "replace")                   # a lone surrogate becomes "?" - in the file and in the copy for the page alike
        directory = inbox_dir(files_dir)
        os.makedirs(directory, exist_ok=True)
        name = "shared_%d_%s.txt" % (int(time.time() * 1000), os.urandom(3).hex())
        path = os.path.join(directory, name)
        temp = path + ".partial"
        with open(temp, "wb") as handle:
            handle.write(raw)
        os.replace(temp, path)
        _prune(directory)
        mission_open = _mission_open(files_dir, clock)
        offered = "" if mission_open or truncated or len(body) > MAX_OFFERED_CHARS else raw.decode("utf-8")
        result.update(ok=True, code="saved", chars=len(body), name=name, truncated=truncated, mission_open=mission_open, text=offered)
    except OSError:
        result["code"] = "io_error"
    except Exception:                                           # nothing may travel back to Java as an exception
        result["code"] = "error"
    return json.dumps(result, ensure_ascii=False)


def _prune(directory):
    """Keep the inbox from filling up with old shared texts. Best effort; never raises."""
    try:
        now = time.time()
        groups = {"shared_": [], "done_shared_": []}
        for entry in os.listdir(directory)[:2000]:
            path = os.path.join(directory, entry)
            try:
                if os.path.islink(path) or not os.path.isfile(path):
                    continue
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if entry.endswith(".partial") and entry.startswith("shared_"):
                if now - mtime > _STALE_PARTIAL_SECONDS:
                    os.remove(path)
                continue
            if not entry.endswith(".txt"):
                continue
            for prefix, items in groups.items():
                if entry.startswith(prefix):
                    items.append((mtime, entry))
                    break
        for items in groups.values():
            items.sort(reverse=True)
            for _, entry in items[KEEP_SHARED_FILES:]:
                try:
                    os.remove(os.path.join(directory, entry))
                except OSError:
                    pass
    except Exception:
        pass


def _mission_open(files_dir, clock=time.time):
    try:
        from teacher.store import TeacherStore
        latest = TeacherStore(hub_root(files_dir), clock).latest(only_open=True)
        return bool(latest and latest.get("state") in _OPEN_FOR_CHAT)
    except Exception:
        return False
