"""
Persian conversation brain - the BODY in the chat  (Prompt 959, stage B)
========================================================================
The user cannot run a terminal and tests the app on his own phone, where Android and HyperOS close a background app hard. This module is
the conversation about the app's BODY (`brain_hub.body`, `brain_hub.selftest`, `native_bridge`):

  command(brain, turn)        «گزارش آزمایشی» (+ «کپی کن»), «چک‌لیست دسترسی‌ها», «صفحهٔ باتری را باز کن», «تنظیمات برنامه را باز کن»,
                              «تنظیمات اعلان را باز کن», «کد پیامک را بخوان», «مجوز پیامک را بده»
  after_emergency(brain, r)   «ایست» also runs the body's stop (a local answer in the making, the notification of the background service)
  tick(brain)                 at the start of every turn: a one-time code that was shown earlier is masked in the stored chat history

Only ever on his order, and nothing is changed by the phone's settings pages it opens (he switches things himself). The one-time code of an
SMS needs the READ_SMS permission that HE gives through Android's own dialog; only the code, the sender and the age come back from the door
(never the text of the message), the reply is shown in the chat only, nothing is sent anywhere, and the code and the sender are masked in the
stored chat history a few seconds later - the history is what the chat shows again after the app restarts, and `allowBackup` may copy it.
A mask that could not run in time (the app was closed within seconds) is done at the next message: the reply carries a fixed mark that is
found again without knowing the code.
"""

import re
import threading

from . import hub_body_commands as BC
from . import hub_brain
from . import hub_messages_body as HB
from . import hub_messages_brain as HBr
from . import hub_messages_tools as HT
from . import hub_ownbrain

SCRUB_KEY = "persian_brain.body_scrub_due.v1"          # {"ts": <seconds>}: a code reply was shown at that time and its stored copy is not yet masked
SCRUB_DELAYS = (4.0, 20.0)                             # seconds after the reply (the core stores the reply only when `respond` has returned)
_CODE_RE = re.compile(re.escape(HB.CODE_PREFIX) + r"\S{1,40}(\n" + re.escape(HB.SENDER_PREFIX) + r"[^\n]{0,160})?")
_TIMERS = []                                           # the pending timers (so a test can wait for them; daemon threads, never joined by the app)
_TIMERS_LOCK = threading.Lock()


# ================================================================== the doors
def _hub(brain):
    return hub_brain._hub(brain)


def _doors(hub):
    from native_bridge import facade
    return facade.for_app(hub)


# ================================================================== masking a shown code in the stored history
def _mask(text):
    """`text` with every code block of a code reply masked (the code, and the sender line under it). Already masked text is returned unchanged."""
    def one(match):
        return HB.CODE_PREFIX + HB.CODE_MASK + (("\n" + HB.SENDER_PREFIX + HB.SENDER_MASK) if match.group(1) else "")
    return _CODE_RE.sub(one, text)


def scrub_codes(memory):
    """Mask the codes of the code replies in the stored chat history and overwrite the old bytes in the database file (the same
    `secure_delete` care as the pasted key's). Returns how many rows changed; never raises."""
    changed = 0
    previous = None
    try:
        with memory._lock:
            rows = memory.query("SELECT id, content FROM conversation_log WHERE content LIKE ?", ("%" + HB.CODE_PREFIX + "%",))
            todo = []
            for row in rows:
                masked = _mask(row["content"])
                if masked != row["content"]:
                    todo.append((row["id"], masked))
            if not todo:
                return 0
            previous = hub_brain._secure_delete(memory, 1)
            try:
                for rid, masked in todo:
                    memory._run("UPDATE conversation_log SET content = ? WHERE id = ?", (masked, rid))
                    changed += 1
            finally:
                if previous is not None:
                    hub_brain._secure_delete(memory, previous)
    except Exception:
        pass
    return changed


def _timer_job(memory):
    try:
        scrub_codes(memory)
    finally:
        with _TIMERS_LOCK:
            me = threading.current_thread()
            if me in _TIMERS:
                _TIMERS.remove(me)


def _plan_scrub(brain):
    """A code was just shown: remember that (so the next message masks it even if the app is closed first) and mask it soon. True when the
    plan is in place (the reply may then promise the mask)."""
    try:
        brain.memory.set_state(SCRUB_KEY, {"ts": hub_brain._now(brain._clock)})
    except Exception:
        return False
    for delay in SCRUB_DELAYS:
        try:
            timer = threading.Timer(float(delay), _timer_job, (brain.memory,))
            timer.daemon = True
            with _TIMERS_LOCK:
                _TIMERS.append(timer)
            timer.start()
        except Exception:
            continue
    return True


def _finished(timer):
    try:
        return bool(timer.finished.is_set())
    except Exception:
        return False


def pending_timers():
    """The scrub timers that have not finished (tests wait for them). A CANCELLED timer has finished: its job, the one that removes it from the
    list, never runs, so it is dropped here (otherwise one cancelled timer would stay pending for the rest of the process)."""
    with _TIMERS_LOCK:
        _TIMERS[:] = [timer for timer in _TIMERS if not _finished(timer)]
        return list(_TIMERS)


def tick(brain):
    """At the start of every turn: when a code reply was shown before, mask it now (the timers may never have run - the app can be closed within
    seconds). One state read when nothing is due. A plan of ANY age is carried out: the older it is, the more it is owed. Never raises."""
    try:
        if brain.memory.get_state(SCRUB_KEY, None) is None:
            return
        scrub_codes(brain.memory)
        brain.memory.set_state(SCRUB_KEY, None)
    except Exception as exc:
        brain._log_error(exc, "")


# ================================================================== the commands
def command(brain, turn):
    """`(kind, reply)` when the sentence is a body command, else None. (An open question was already closed by the early path, like for every
    other sentence that is not its answer.)"""
    try:
        hub = _hub(brain)
        if hub is None:
            return None
        cmd = BC.classify(turn.text, turn.norm, turn.toks)
        if cmd is None:
            return None
    except Exception as exc:
        brain._log_error(exc, turn.text)
        return None
    try:
        return "body_" + cmd.kind, _run(brain, hub, cmd)
    except Exception as exc:
        brain._log_error(exc, turn.text)
        return "body_" + cmd.kind, HT.unexpected()


def _run(brain, hub, cmd):
    kind = cmd.kind
    if kind == BC.SELFTEST:
        return _selftest(hub, bool(cmd.slots.get("copy")))
    if kind == BC.ACCESS:
        return _access(hub)
    if kind == BC.OPEN:
        return _open(hub, str(cmd.slots.get("target") or ""))
    if kind == BC.SMS:
        return _sms(brain, hub, int(cmd.slots.get("minutes") or BC.DEFAULT_MINUTES))
    if kind == BC.SMS_PERMISSION:
        return _sms_permission(hub)
    return HT.unexpected()


def _selftest(hub, copy):
    from brain_hub import selftest
    text = HB.selftest(selftest.collect(hub))
    if not copy:
        return text + "\n\n" + HB.selftest_hint()
    result = _doors(hub).clipboard.set_text(text, label="گزارش آزمایشی")
    return text + "\n\n" + HB.copied(bool(result.ok), str(result.code or ""))


def _access(hub):
    from brain_hub import selftest
    return HB.access_checklist(selftest.quick(hub))


def _open(hub, target):
    if target not in ("battery", "app", "notifications"):
        return HT.unexpected()
    result = _doors(hub).settings.open_settings(target)
    return HB.opened(target) if result.ok else HB.open_failed(str(result.code or ""), target)


def _sms(brain, hub, minutes):
    result = _doors(hub).sms.latest_code(minutes)
    if result.ok:
        return HB.sms_code(result.data, scrubbed=_plan_scrub(brain))
    code = str(result.code or "")
    if code == "empty":
        return HB.sms_empty(minutes)
    return HB.sms_failed(code)


def _sms_permission(hub):
    sms = _doors(hub).sms
    have = sms.has_permission()
    if have.ok and (have.data or {}).get("granted"):
        return HB.sms_permission_have()
    asked = sms.request_permission()
    if not asked.ok:
        return HB.sms_failed(str(asked.code or ""))
    return HB.sms_permission_have() if (asked.data or {}).get("granted") else HB.sms_permission_shown()


# ================================================================== «ایست»
def after_emergency(brain, mine):
    """`mine` is the `(sub, reply)` of the emergency words after the own brain added its line: «ایست» also runs the body's stop (the answer a local
    model was making, the cloud brain when it was not halted yet, the background service's notification). Anything else is returned unchanged.
    Never raises."""
    try:
        sub, reply = mine
        if sub != "brain_halt":
            return mine
        hub = _hub(brain)
        if hub is None:
            return mine
        from brain_hub import body
        service = body.get_body(hub)
        if service is None:
            return mine
        done = service.emergency_stop()
        extra = HB.emergency_extra(done.get("stopped"), done.get("released"))
        if extra:
            return sub, reply + "\n\n" + extra
    except Exception as exc:
        brain._log_error(exc, "")
    return mine


def stop_while_busy(brain):
    """«ایست» that arrives while ANOTHER turn of this brain still runs (see `hub_hooks.emergency_while_busy`): the same stops as the normal path,
    but only the ones that need no lock - the cloud brain's halted flag (the open question of the cloud brain is closed), the own brain's download,
    the engine's cancel request and the background service. `(sub, reply)`, or None when there is no hub to stop (the normal path then answers)."""
    from brain_hub import body
    hub = _hub(brain)
    svc = hub_brain.service(brain)
    if hub is None or svc is None:
        return None
    hub_brain._clear(brain.memory)
    svc.halt()
    mine = hub_ownbrain.after_emergency(brain, ("brain_halt", HBr.halt_done()))
    service = body.get_body(hub)
    if service is not None:
        done = service.emergency_stop()
        extra = HB.emergency_extra(done.get("stopped"), done.get("released"))
        if extra:
            mine = (mine[0], mine[1] + "\n\n" + extra)
    return mine


__all__ = ["command", "after_emergency", "stop_while_busy", "tick", "scrub_codes", "pending_timers", "SCRUB_KEY", "SCRUB_DELAYS"]
