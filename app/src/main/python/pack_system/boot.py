"""
pack_system.boot - start-up of the pack system: import overlay, last-good bookkeeping, safe mode
================================================================================================
`platform_boot.prepare(files_dir)` is the FIRST Python call the Android activity makes - before `android_entry` is
imported - so that packs which replace app modules are already importable when the app imports them.

A start is "good" once the app has been alive for BOOT_GOOD_AFTER_SECONDS (or has served a message after a few
seconds). Until then the state file says `boot.pending`. If the next start still finds `pending`, the last start did
not get that far and it is counted:

    1 failed start   every pack that is not at its last good version goes back to it (a pack that never had a good
                     version is switched off); the app starts normally
    2 failed starts  SAFE MODE: no code pack is loaded at all - the app runs exactly as shipped. Language packs (pure
                     data) stay. The user can leave safe mode from the chat ("حالت امن را تمام کن").

Nothing here can keep the app from starting: `prepare` never raises.
"""

import os
import threading
import time

from . import limits
from .manager import PackManager

__all__ = ["prepare", "manager", "manager_for", "ensure_manager", "note_message_served", "packs_root", "reset_for_tests"]

_MANAGER = None
_BY_ROOT = {}
_STARTED = None
_TIMER = None
_LOCK = threading.Lock()


def packs_root(base_dir):
    """`<files dir>/data/packs` - next to the app's database and the hub (`<files dir>/data/brain_hub`)."""
    return os.path.join(os.fspath(base_dir), "data", "packs")


def manager():
    return _MANAGER


def _auto_rollback(mgr):
    """After a failed start: put every pack back to its last good version; switch off packs that never had one."""
    changed = []
    state = mgr.state
    for pid, rec in sorted(state["packs"].items()):
        if rec["kind"] != limits.CODE_SCHEMA or rec.get("active") is None or not rec.get("enabled", True):
            continue
        good = state["last_good"].get(pid)
        if good == rec["active"]:
            continue
        if good is not None and str(good) in rec["versions"] and mgr.store.verify(pid, good)[0]:
            rec["active"] = good
            changed.append((pid, "reverted"))
        else:
            rec["enabled"] = False
            changed.append((pid, "disabled"))
    if changed:
        mgr.store.save()
        for pid, what in changed:
            mgr.audit.append("pack.boot_rollback", pid, {"what": what})
    return changed


def prepare(base_dir, clock=time.time, *, start_timer=True):
    """Create the manager, decide normal / recovery / safe mode, load the active packs. Never raises."""
    global _MANAGER, _STARTED, _TIMER
    report = {"ok": False, "loaded": 0, "failed": 0, "safe_level": 0, "rolled_back": 0, "error": ""}
    try:
        with _LOCK:
            mgr = PackManager(packs_root(base_dir), clock)
            _MANAGER, _STARTED = mgr, time.monotonic()
            boot = mgr.state["boot"]
            if boot.get("pending"):
                boot["crashes"] = int(boot.get("crashes") or 0) + 1
                mgr.audit.append("pack.boot_failed_before", "", {"crashes": boot["crashes"]})
            safe = int(boot.get("safe_level") or 0)
            if boot.get("crashes", 0) >= limits.SAFE_MODE_AFTER_FAILED_STARTS and safe == 0:
                boot["safe_level"], boot["safe_reason"] = 1, "failed_starts:%d" % boot["crashes"]
                mgr.audit.append("pack.safe_mode_entered", "", {"crashes": boot["crashes"]})
            elif boot.get("crashes", 0) == 1 and safe == 0:
                report["rolled_back"] = len(_auto_rollback(mgr))
            boot["pending"] = {"ts": round(float(clock()), 3), "pid": os.getpid()}
            mgr.store.save()
            report["safe_level"] = int(boot.get("safe_level") or 0)
            if report["safe_level"] == 0:
                loaded = mgr.activate_all(at_boot=True)
                report["loaded"], report["failed"] = len(loaded["loaded"]), len(loaded["failed"])
        if start_timer:
            _TIMER = threading.Timer(limits.BOOT_GOOD_AFTER_SECONDS, _timer_good)
            _TIMER.daemon = True
            _TIMER.start()
        report["ok"] = True
    except BaseException as exc:                                 # the app must start even if the pack system cannot
        if isinstance(exc, KeyboardInterrupt):
            raise
        report["error"] = type(exc).__name__
    return report


def _timer_good():
    mgr = _MANAGER
    if mgr is not None:
        try:
            mgr.mark_good()
        except Exception:
            pass


def note_message_served():
    """Called by the chat layer after a reply: a start that has answered a message a few seconds in is a good start."""
    mgr = _MANAGER
    if mgr is None or _STARTED is None:
        return
    if mgr.state["boot"].get("pending") and time.monotonic() - _STARTED >= 5.0:
        try:
            mgr.mark_good()
        except Exception:
            pass


def ensure_manager(base_dir, clock=time.time):
    """The process manager; created (and its packs loaded, without a restart) when `prepare` was never called."""
    global _MANAGER
    with _LOCK:
        if _MANAGER is not None:
            return _MANAGER
        mgr = PackManager(packs_root(base_dir), clock)
        if int(mgr.state["boot"].get("safe_level") or 0) == 0:
            try:
                mgr.activate_all(at_boot=False)
            except Exception:
                pass
        _MANAGER = mgr
        return mgr


def manager_for(memory, clock=time.time):
    """The manager of the app whose database `memory` is (its packs live next to that database), or None.

    On the phone this is the manager `prepare` created. Anywhere else (tests, a second app folder) it is created on first
    use and - when there already are packs on disk and the safe mode is off - the active ones are loaded without a restart."""
    db_path = getattr(memory, "db_path", None)
    if not db_path:
        return _MANAGER
    root = os.path.join(os.path.dirname(os.path.abspath(os.fspath(db_path))), "packs")
    with _LOCK:
        mgr = _BY_ROOT.get(root)
        if mgr is not None:
            return mgr
        if _MANAGER is not None and os.path.abspath(_MANAGER.store.root) == root:
            mgr = _MANAGER
        else:
            mgr = PackManager(root, clock)
            if os.path.isdir(root) and int(mgr.state["boot"].get("safe_level") or 0) == 0:
                try:
                    mgr.activate_all(at_boot=False)
                except Exception:
                    pass
        _BY_ROOT[root] = mgr
        return mgr


def reset_for_tests():
    global _MANAGER, _STARTED, _TIMER
    if _TIMER is not None:
        _TIMER.cancel()
    _MANAGER, _STARTED, _TIMER = None, None, None
    _BY_ROOT.clear()
