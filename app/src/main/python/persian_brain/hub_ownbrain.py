"""
Persian conversation brain - the OWN BRAIN («مغز خودکار») in the chat  (Prompt 959, stage B)
============================================================================================
The user wants an assistant that provides what it lacks BY ITSELF: no key, no cost, no other AI service. The own brain is a free,
open language model (a file) that the app fetches from the internet, checks against a hash it already knows, and runs on the phone
(`brain_hub.ownbrain` does the work). This module is its conversation:

  early(brain, text)          the answer to the own brain's open question (consent card -> «بله»; delete -> «بله»), and the cheap `tick`
                              that continues a download the user agreed to after the app was closed
  command(brain, turn)        «مغز خودت را بگیر», «وضعیت مغز», «دانلود مغز را متوقف کن», «ادامه دانلود مغز», «مغز را پاک کن», «آزمایش مغز»,
                              «مغز را دوباره امتحان کن», «مغز خودکار چیست؟»
  after_emergency(brain, r)   «ایست» also stops the download (what was fetched stays), «ادامه» also continues THAT download
  after_net_off(brain)        «اینترنت را خاموش کن» also stops a running download at once (what was fetched stays)
  snapshot_part(brain)        one small fact for the «I do not know» replies (they lead with the own-brain way)

NOTHING starts before the user's explicit «بله» to a card that names the size, the cost, the source, the hash check and what is not promised.
Like the cloud brain's conversation it keeps ONE open question at a time, in a key of its own (the dialogue module's closed set of
question types is pinned by tests), and any other message withdraws the open question - nothing is saved or started by a withdrawn one.
"""

from self_builder import fa_text

from . import hub_brain
from . import hub_brain_commands as BC
from . import hub_messages_ownbrain as BM
from . import hub_messages_tools as HT
from . import hub_ownbrain_commands as OC
from . import hub_state
from . import normalization as nz

PENDING_KEY = "persian_brain.ownbrain_pending.v1"
PENDING_TTL_SECONDS = 30 * 60
MAX_ANSWER_CHARS = 200
TYPES = ("consent", "delete")
_WITHDRAW = object()


# ================================================================== access
def service(brain):
    """The `OwnBrain` of this brain's hub, or None (no hub: the chat then behaves as before). Nothing is written by asking for it."""
    hub = hub_brain._hub(brain)
    if hub is None:
        return None
    try:
        from brain_hub.ownbrain import get_ownbrain
        return get_ownbrain(hub)
    except Exception:
        return None


# ================================================================== the one open question (own key, own validation)
def _valid(ptype, data):
    if ptype not in TYPES or not isinstance(data, dict):
        return False
    if ptype == "consent":
        return set(data) == {"choice"} and isinstance(data["choice"], str) and 0 < len(data["choice"]) <= 24
    return data == {}


def _load(memory, clock):
    """(type, data) of the open own-brain question, or None (none, expired, or not valid)."""
    try:
        raw = memory.get_state(PENDING_KEY, None)
    except Exception:
        return None
    if not isinstance(raw, dict) or set(raw) != {"type", "ts", "data"}:
        return None
    ts = raw["ts"]
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not 0 <= hub_brain._now(clock) - ts <= PENDING_TTL_SECONDS:
        return None
    return (raw["type"], raw["data"]) if _valid(raw["type"], raw["data"]) else None


def _clear(memory):
    try:
        if memory.get_state(PENDING_KEY, None) is not None:
            memory.set_state(PENDING_KEY, None)
    except Exception:
        pass


def _close_others(brain, turn=None):
    """Only ONE question may be open: the hub's, the dialogue's and the cloud brain's are closed (this module's own is replaced by `_arm`)."""
    try:
        hub_state.clear(brain.memory)
    except Exception:
        pass
    try:
        if turn is not None:
            turn.dlg.clear_pending()
        else:
            from .dialogue import Dialogue
            dlg = Dialogue(brain.memory, brain._clock).load()
            dlg.clear_pending()
            dlg.commit()
    except Exception:
        pass
    hub_brain._clear(brain.memory)


def _arm(brain, ptype, data, turn=None):
    if not _valid(ptype, data):
        return False
    try:
        brain.memory.set_state(PENDING_KEY, {"type": ptype, "ts": hub_brain._now(brain._clock), "data": dict(data)})
    except Exception:
        return False
    _close_others(brain, turn)
    return True


def _touch(brain, ptype, data):
    try:
        brain.memory.set_state(PENDING_KEY, {"type": ptype, "ts": hub_brain._now(brain._clock), "data": dict(data)})
    except Exception:
        pass


# ================================================================== early: the answer to the open question
def early(brain, text):
    """`(sub, reply)` or None. Never raises."""
    try:
        return _early(brain, text)
    except Exception as exc:
        brain._log_error(exc, text)
        return None


def _early(brain, text):
    ob = service(brain)
    if ob is None:
        return None
    ob.tick()                                                   # an agreed download that the app's closing interrupted continues now
    state = _load(brain.memory, brain._clock)
    if state is None:
        return None
    ptype, data = state
    toks = fa_text.words(nz.normalize(text)) if len(text) <= MAX_ANSWER_CHARS else []
    word = OC.confirm_word(toks) if toks else None
    reply = (_step_consent if ptype == "consent" else _step_delete)(brain, ob, data, toks, word)
    if reply is _WITHDRAW:
        _clear(brain.memory)                                    # any other message withdraws the open question; nothing was started
        return None
    return "ownbrain_answer:" + ptype, reply


def _step_consent(brain, ob, data, toks, word):
    choice = ob.choice(data["choice"])
    if choice is None:
        return _WITHDRAW
    if word is None:
        pick = OC.choose_word(toks)
        if pick is not None:
            return _switch(brain, ob, choice, pick)
        if BC.is_clarify(toks):                                 # «چرا؟» / «یعنی چی؟»: explain; the same question stays open
            _touch(brain, "consent", data)
            return BM.clarify_consent(choice)
        return _WITHDRAW
    _clear(brain.memory)
    if word in ("deny", "cancel"):
        return BM.cancelled()
    was_on = ob.network_on()
    result = ob.start(choice.key, consent=True)                 # «بله»: the one thing that starts it (and, said on the card, switches the internet on)
    return _started_or_blocked(ob, choice, result, net_turned_on=not was_on and ob.network_on())


def _switch(brain, ob, current, pick_key):
    """The user picked «سبک» / «قوی» while the card was open: the card of that brain (when it fits the phone), the question stays open."""
    other = ob.choice(pick_key)
    if other is None:
        return _WITHDRAW
    plan = ob.plan()
    row = next((o for o in plan["options"] if o["key"] == other.key), None)
    facts = plan["facts"]
    if row is None or row["fit"] != "ok":
        _touch(brain, "consent", {"choice": current.key})
        why = BM.blocked(row["fit"] if row else "unknown_choice", _detail(row["fit"], facts, row["need"]) if row else "", other, facts)
        return why + "\n\n(مغزِ قبلی سر جایش است؛ بگو «بله» یا «نه».)"
    _touch(brain, "consent", {"choice": other.key})
    alt = next((c for c in ob.choices() if c.key != other.key and _fits(plan, c.key)), None)
    return BM.offer_card(other, alt, facts, row["partial"])


def _fits(plan, key):
    return any(o["key"] == key and o["fit"] == "ok" for o in plan["options"])


def _detail(code, facts, need):
    have = facts.get("ram") if code == "ram_too_small" else facts.get("free") if code == "not_enough_space" else 0
    return "%d/%d" % (int(have or 0), int(need or 0))


def _started_or_blocked(ob, choice, result, net_turned_on=False):
    if result.ok:
        return BM.started(choice, net_turned_on=net_turned_on)
    if result.code in ("already_ready",):
        return BM.status(ob.status())
    return BM.blocked(result.code, result.detail, choice, ob.facts())


def _step_delete(brain, ob, data, toks, word):
    if word not in ("confirm", "deny", "cancel"):
        return _WITHDRAW
    _clear(brain.memory)
    if word != "confirm":
        return BM.delete_cancelled()
    result = ob.delete()
    if result.get("busy"):
        return BM.busy_installing()
    return BM.deleted(int(result.get("freed") or 0))


# ================================================================== command
def command(brain, turn):
    """`(kind, reply)` when the sentence is an own-brain command, else None. A command is a new topic: it withdraws any open question."""
    try:
        ob = service(brain)
        if ob is None:
            return None
        cmd = OC.classify(turn.text, turn.norm, turn.toks)
        if cmd is None:
            return None
    except Exception as exc:
        brain._log_error(exc, turn.text)
        return None
    try:
        reply = _run(brain, ob, turn, cmd)
    except Exception as exc:
        brain._log_error(exc, turn.text)
        return "ownbrain_" + cmd.kind, HT.unexpected()
    return None if reply is None else ("ownbrain_" + cmd.kind, reply)


def _bare_applies(kind, st):
    """A phrase without the word «مغز» («دانلود را متوقف کن», «ادامه دانلود», «دوباره امتحان کن», «چقدر مونده؟») is ours only while the own brain
    has a job or a failure they could mean; otherwise another command (the model downloads of the hub, ...) may have them."""
    phase = st["phase"]
    if kind == OC.PAUSE:
        return phase in ("downloading", "installing")
    if kind == OC.RESUME:
        return bool(st.get("resumable"))
    if kind == OC.RETRY:
        return phase in ("failed", "paused")
    if kind == OC.STATUS:
        return phase in ("downloading", "installing", "paused", "failed")
    return False


def _run(brain, ob, turn, cmd):
    kind = cmd.kind
    st = ob.status(deep=True)
    if cmd.slots.get("bare") and not _bare_applies(kind, st):
        return None
    _close_others(brain, turn)
    _clear(brain.memory)
    if kind == OC.GET:
        return _get(brain, ob, turn, st)
    if kind == OC.HELP:
        return _help(ob, st)
    if kind == OC.STATUS:
        return BM.status(st)
    if kind == OC.PAUSE:
        return BM.paused(ob.status()) if ob.cancel() else BM.nothing_running(st)
    if kind == OC.RESUME:
        return _resume(ob, st)
    if kind == OC.DELETE:
        return _delete(brain, ob, turn, st)
    if kind == OC.TEST:
        return _test(ob, st, soft=bool(cmd.slots.get("soft")))
    if kind == OC.RETRY:
        return _retry(ob, st)
    return None


def _offer(ob):
    """`(choice, alt, plan, blocked_text)`: the brain to offer on this phone and the other one that also fits - or why none can be offered."""
    plan = ob.plan()
    facts = plan["facts"]
    if not facts["engine_ok"]:
        return None, None, plan, BM.blocked("engine_missing", facts.get("engine_code", ""), facts=facts)
    rec = ob.choice(plan["recommended"]) if plan["recommended"] else None
    if rec is None:
        return None, None, plan, _none_fits(ob, plan)
    if facts["online"] == "offline":
        return None, None, plan, BM.blocked("offline")
    alt = next((c for c in ob.choices() if c.key != rec.key and _fits(plan, c.key)), None)
    return rec, alt, plan, ""


def _none_fits(ob, plan):
    facts = plan["facts"]
    lightest = min(ob.choices(), key=lambda c: c.size_hint) if ob.choices() else None
    row = next((o for o in plan["options"] if lightest is not None and o["key"] == lightest.key), None)
    if row is None:
        return BM.none_fits(facts)
    if row["fit"] in ("ram_too_small", "not_enough_space", "ram_unknown"):
        return BM.blocked(row["fit"], _detail(row["fit"], facts, row["need"]), lightest, facts)
    return BM.none_fits(facts)


def _get(brain, ob, turn, st):
    phase = st["phase"]
    if phase == "ready":
        return BM.status(st)
    if phase in ("downloading", "installing"):
        return BM.blocked("already_running") + "\n\n" + BM.status(st)
    if phase in ("paused", "failed"):
        if st.get("resumable"):
            return _resume(ob, st)
        return BM.status(st)                                    # a failure that more downloading cannot fix: the status says what to do
    choice, alt, plan, blocked = _offer(ob)
    if choice is None:
        return blocked
    row = next((o for o in plan["options"] if o["key"] == choice.key), {"partial": 0})
    if not _arm(brain, "consent", {"choice": choice.key}, turn):
        return BM.setup_failed()
    return BM.offer_card(choice, alt, plan["facts"], row["partial"])


def _help(ob, st):
    if st["phase"] != "idle":
        return BM.status(st)
    choice, alt, plan, blocked = _offer(ob)
    if choice is None:
        return "🧠 %s\n\nولی الان نمی‌شود: %s" % (BM.what_it_is(), blocked)        # the explanation is given even when nothing can be started
    row = next((o for o in plan["options"] if o["key"] == choice.key), {"partial": 0})
    return BM.offer_card(choice, alt, plan["facts"], row["partial"], ask=False)


def _resume(ob, st):
    if st["phase"] == "ready":
        return BM.status(st)
    if st["phase"] in ("downloading", "installing"):
        return BM.blocked("already_running") + "\n\n" + BM.status(st)     # it is already going: «continue» has nothing to do (never "no download")
    result = ob.resume()
    choice = ob.choice(st["choice"])
    if result.ok and choice is not None:
        return BM.started(choice, resumed=bool(st.get("resumable")))       # nothing to continue from (a discarded file): it starts again, and says so
    return BM.blocked(result.code, result.detail, choice, ob.facts())


def _delete(brain, ob, turn, st):
    if st["phase"] == "installing":
        return BM.busy_installing()                             # nothing is removed from under the install / first test
    held = ob.footprint()
    if st["phase"] == "idle" and not held:
        return BM.nothing_to_delete()
    if not _arm(brain, "delete", {}, turn):
        return BM.setup_failed()
    return BM.ask_delete({"held": held})


def _test(ob, st, soft=False):
    if st["phase"] != "ready":
        return BM.status(st) if soft else BM.not_ready_for_test(st)
    result = ob.test()
    if result["ok"]:
        return BM.test_ok(result["text"], result["seconds"])
    return BM.test_failed(result["code"], result["seconds"])


def _retry(ob, st):
    if st["phase"] == "idle":
        return BM.status(st)
    result = ob.retry()
    if not result.ok:
        return BM.blocked(result.code, result.detail, ob.choice(st["choice"]), ob.facts())
    return BM.retry_started() + "\n\n" + BM.status(ob.status())


# ================================================================== the emergency words
def after_emergency(brain, mine):
    """`mine` is the `(sub, reply)` of the emergency words (`hub_brain.early`): «ایست» also stops the own brain's download (what was fetched stays),
    and «ادامه» also continues a download THAT stop paused. Anything else is returned unchanged. Never raises."""
    try:
        sub, reply = mine
        ob = service(brain)
        if ob is None:
            return mine
        if sub == "brain_halt":
            if ob.halt():
                return sub, reply + "\n\n" + BM.halted_note()
            if ob.status().get("phase") == "installing":
                return sub, reply + "\n\n" + BM.install_not_stoppable_note()
        if sub == "brain_resume":
            result = ob.resume_after_halt()
            if result is not None and result.ok:
                return sub, reply + "\n\n" + BM.resumed_note()
    except Exception as exc:
        brain._log_error(exc, "")
    return mine


def after_net_off(brain):
    """The app's internet switch was just turned off («اینترنت را خاموش کن»): a running own-brain download stops at once (what was fetched stays).
    The sentence to add to that reply, or '' when no download of the own brain was running. Never raises."""
    try:
        ob = service(brain)
        if ob is None:
            return ""
        ob.net_off()
        st = ob.status()
        if st["phase"] == "paused" and st["code"] == "net_off":
            return BM.net_off_note(st)
    except Exception as exc:
        brain._log_error(exc, "")
    return ""


# ================================================================== for the «I do not know» replies and the capability list
def snapshot_part(brain):
    """`{phase, percent, title}` for `hub_self`: phase is none | downloading | installing | paused | failed | ready. Never raises."""
    try:
        ob = service(brain)
        if ob is None:
            return {"phase": "none"}
        st = ob.status(deep=True)
        phase = "none" if st["phase"] == "idle" else st["phase"]
        return {"phase": phase, "percent": int(st["percent"]), "title": st["title_fa"]}
    except Exception:
        return {"phase": "none"}


def unusable_reply(brain):
    """What to say when the own brain was ready but could not answer because it is not usable any more (a load that never finished, a removed
    file): the real reason from its status, and what to say. Never raises."""
    try:
        ob = service(brain)
        if ob is not None:
            st = ob.status(deep=True)
            if st["phase"] != "ready":
                return BM.status(st)
    except Exception:
        pass
    return BM.llm_failed("model_not_usable")


def own_model_id(brain):
    """The model id of the own brain while it is ready, else ''. Never raises."""
    try:
        ob = service(brain)
        return ob.model_id() if ob is not None else ""
    except Exception:
        return ""


__all__ = ["early", "command", "after_emergency", "after_net_off", "snapshot_part", "own_model_id", "unusable_reply", "service", "PENDING_KEY", "PENDING_TTL_SECONDS",
           "TYPES"]
