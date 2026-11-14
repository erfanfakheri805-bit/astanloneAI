"""
Persian conversation brain - the cloud brain in the chat (Prompt 959, stage A)
==============================================================================
Three entry points, called from `hub_hooks` / `brain.py` (FULL scope only):

  early(brain, text)          the emergency words («ایست» / «ادامه»), the answer to the cloud brain's own open question
                              (service -> consent -> key -> personal details -> forget), and a key pasted by accident
  command(brain, turn)        «مغز ابری را فعال/خاموش کن», «وضعیت مغز ابری», «مدل مغز ابری را ... کن», «کلید را فراموش کن» ...
  reply(brain, turn, intent)  a free sentence nothing else answered: an answer kept from before (offline) or the cloud brain's - the cloud
                              only when the user switched it on

The setup is a short conversation in which NOTHING is saved before the user's explicit «بله»:

    «مغز ابری را فعال کن» -> which service? -> the consent card (exact host, what is sent, what never is, cost, VPN) -> «بله»
    -> «paste the key» -> the key is stored, the chat log row that held it is deleted, a tiny test request is sent
    -> (if it works) «may personal details go too?» -> done.

The open question lives in a key of its own (`persian_brain.brain_pending.v1`): the dialogue module's closed set of question types
is pinned by tests and must not be widened. It is still ONE open question at a time: asking it clears the hub's and the
dialogue's, and any message that does not answer it withdraws it (nothing is saved by a withdrawn question).
"""

import time

from self_builder import fa_text

from brain_v2 import get_brain, privacy, providers

from . import hub_brain_commands as BC
from . import hub_messages_brain as BM
from . import hub_state
from . import intents as I
from . import normalization as nz

PENDING_KEY = "persian_brain.brain_pending.v1"
PENDING_TTL_SECONDS = 30 * 60
MAX_ANSWER_CHARS = 400            # an answer to the cloud brain's question is short (a key is the longest)
MAX_ASK_CHARS = 2000
TYPES = ("provider", "url", "consent", "key", "private", "forget")


# ================================================================== access
def _hub(brain):
    try:
        from brain_hub import service as hub_service
        return hub_service.get_hub(brain.memory)
    except Exception:
        return None


def service(brain):
    """The `BrainV2` of this brain's hub, or None (no hub: the chat then behaves as before)."""
    hub = _hub(brain)
    return get_brain(hub) if hub is not None else None


# ================================================================== the one open question (own key, own validation)
def _now(clock):
    """Seconds now. `clock` may be None: the real application builds its brain as `PersianBrain(memory)` WITHOUT a clock (only tests
    inject one), and calling None here made the whole setup fail silently on the phone (Prompt 959, found on a real phone)."""
    return float((clock or time.time)())


def _valid(ptype, data):
    if ptype not in TYPES or not isinstance(data, dict):
        return False
    if ptype == "consent":
        base = data.get("base_url")
        return (set(data) == {"provider", "base_url"} and data["provider"] in providers.ORDER and isinstance(base, str)
                and ((data["provider"] == providers.CUSTOM and providers.valid_custom_base(base)[0] == base)
                     or (data["provider"] != providers.CUSTOM and base == "")))
    if ptype == "key":
        return set(data) == {"changing"} and isinstance(data["changing"], bool)
    return data == {}


def _load(memory, clock):
    """(type, data) of the open cloud-brain question, or None (none, expired, or not valid)."""
    try:
        raw = memory.get_state(PENDING_KEY, None)
    except Exception:
        return None
    if not isinstance(raw, dict) or set(raw) != {"type", "ts", "data"}:
        return None
    ts = raw["ts"]
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not 0 <= _now(clock) - ts <= PENDING_TTL_SECONDS:
        return None
    return (raw["type"], raw["data"]) if _valid(raw["type"], raw["data"]) else None


def _clear(memory):
    try:
        if memory.get_state(PENDING_KEY, None) is not None:
            memory.set_state(PENDING_KEY, None)
    except Exception:
        pass


def _arm(brain, ptype, data, turn=None):
    """Open ONE question: the hub's and the dialogue's are closed first, so only this one is open."""
    if not _valid(ptype, data):
        return False
    try:
        brain.memory.set_state(PENDING_KEY, {"type": ptype, "ts": _now(brain._clock), "data": dict(data)})
    except Exception:
        return False
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
    return True


def _touch(brain, ptype, data):
    """Keep the same question open for another try (a mistyped URL or key) without clearing anything else."""
    try:
        brain.memory.set_state(PENDING_KEY, {"type": ptype, "ts": _now(brain._clock), "data": dict(data)})
    except Exception:
        pass


# ================================================================== keeping a pasted key out of the chat history
def _secure_delete(memory, value):
    """Set SQLite's `secure_delete` for this connection and return the PREVIOUS setting (an int), or None when it cannot be read or set.
    With it ON the bytes of a deleted row are overwritten with zeros instead of staying in the file's free space. Prompt 959: found by a
    test - a SQLite built without that default (the phone's may be) kept the pasted key in `memory.db` after its row was deleted."""
    try:
        conn = memory._conn
        row = conn.execute("PRAGMA secure_delete").fetchone()
        conn.execute("PRAGMA secure_delete = %d" % int(value))
        return int(row[0]) if row else None
    except Exception:
        return None


def scrub_log(memory, secret):
    """Delete the chat-log rows that contain `secret` (the pasted key) and overwrite their bytes in the database file.
    Returns how many rows were removed; never raises."""
    if not privacy.contains_text(secret, secret):          # shorter than 8 characters: not something to search for
        return 0
    like = "%" + secret.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    previous = None
    try:
        with memory._lock:                                  # the connection lock is re-entrant: _run takes it again
            previous = _secure_delete(memory, 1)
            try:
                cur = memory._run("DELETE FROM conversation_log WHERE content LIKE ? ESCAPE '\\'", (like,))
            finally:
                if previous is not None:
                    _secure_delete(memory, previous)
        return max(0, int(getattr(cur, "rowcount", 0) or 0))
    except Exception:
        return 0


def _key_candidate(text):
    """The key a message holds, or '' (the whole message must be ONE token of key characters, optionally in quotes/backticks)."""
    body = (text or "").strip().strip("`'\"«»<>").strip()
    if not body or len(body) > 320 or any(ch.isspace() for ch in body) or "://" in body:
        return ""
    return body if providers.valid_key(body) else ""


def _stray_key(text):
    """A key-shaped message (one token of letters, digits, - and _) with no question open: never stored, scrubbed from the log."""
    import re
    body = (text or "").strip().strip("`'\"")
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]{20,300}", body)) and privacy.check(body).kind == "key"


# ================================================================== early
def early(brain, text):
    """`(sub, reply)` or None. Never raises."""
    try:
        return _early(brain, text)
    except Exception as exc:
        brain._log_error(exc, "")                              # the text may be a key: never log it
        return None


def _early(brain, text):
    svc = service(brain)
    if svc is None:
        return None
    svc.begin_turn()                                           # what was answered in the turn before is now "the previous answer"
    toks = fa_text.words(nz.normalize(text)) if len(text) <= MAX_ANSWER_CHARS else []
    if BC.is_halt(toks):
        _clear(brain.memory)
        svc.halt()
        return "brain_halt", BM.halt_done()
    if BC.is_resume(toks) and svc.settings.get()["halted"]:
        svc.resume()
        return "brain_resume", BM.resume_done()
    state = _load(brain.memory, brain._clock)
    if state is None:
        if len(text) <= 320 and _stray_key(text):
            scrub_log(brain.memory, text.strip().strip("`'\""))
            return "brain_stray_key", BM.stray_key()
        return None
    ptype, data = state
    word = I.answer_word(toks) if toks else None
    cancel = word in ("deny", "cancel")
    if word is None and BC.is_clarify(toks):                    # «چرا؟» / «یعنی چی؟» / «از کجا بگیرم؟»: explain THIS step; the question stays open
        _touch(brain, ptype, data)
        return "brain_clarify:" + ptype, _clarify(brain, svc, ptype, data)
    step = _STEPS[ptype]
    reply = step(brain, svc, data, text, toks, word, cancel)
    if reply is _WITHDRAW:
        _clear(brain.memory)                                    # any other message withdraws the open question; nothing was saved
        return None
    return "brain_answer:" + ptype, reply


def _clarify(brain, svc, ptype, data):
    """The explanation of the open question's step, ending with the question itself again."""
    if ptype == "provider":
        return BM.clarify_provider()
    if ptype == "url":
        return BM.clarify_url()
    if ptype == "consent":
        provider = providers.get(data["provider"])
        host = providers.host_of(providers.endpoint(data["provider"], data["base_url"]))
        return BM.clarify_consent(provider, host)
    if ptype == "key":
        return BM.clarify_key(providers.get(svc.status()["provider"]) or providers.get(providers.ORDER[0]))
    if ptype == "private":
        return BM.clarify_private()
    return BM.ask_forget()


_WITHDRAW = object()


def _step_provider(brain, svc, data, text, toks, word, cancel):
    if cancel:
        _clear(brain.memory)
        return BM.setup_cancelled()
    pid = providers.parse_provider_word(text)
    if pid is None:
        if word == "confirm":                                    # «بله» does not choose a service: say so and keep asking
            _touch(brain, "provider", data)
            return BM.provider_again()
        return _WITHDRAW
    if pid == providers.CUSTOM:
        return BM.ask_custom_url() if _arm(brain, "url", {}) else BM.setup_failed()
    return _ask_consent(brain, pid, "")


def _step_url(brain, svc, data, text, toks, word, cancel):
    if cancel:
        _clear(brain.memory)
        return BM.setup_cancelled()
    clean, why = providers.valid_custom_base(text)
    if clean:
        return _ask_consent(brain, providers.CUSTOM, clean)
    if "." in text or "http" in text.lower():                   # an attempt at a URL: say what is wrong and keep asking
        _touch(brain, "url", {})
        return BM.bad_custom_url(why)
    if word == "confirm":
        _touch(brain, "url", {})
        return BM.ask_custom_url()
    return _WITHDRAW


def _ask_consent(brain, provider_id, base_url):
    provider = providers.get(provider_id)
    host = providers.host_of(providers.endpoint(provider_id, base_url))
    if provider is None or not host or not _arm(brain, "consent", {"provider": provider_id, "base_url": base_url}):
        _clear(brain.memory)
        return BM.setup_failed()
    return BM.consent_card(provider, host)


def _grant_network(brain):
    hub = _hub(brain)
    try:
        if hub is not None and not hub.permissions.is_granted("network"):
            hub.grant_permission("network", user_approved=True)
        return hub is not None and hub.permissions.is_granted("network")
    except Exception:
        return False


def _step_consent(brain, svc, data, text, toks, word, cancel):
    if cancel or word == "deny":
        _clear(brain.memory)
        return BM.setup_cancelled()
    if word != "confirm":
        return _WITHDRAW
    try:
        svc.choose_provider(data["provider"], data["base_url"])
    except ValueError:
        _clear(brain.memory)
        return BM.setup_failed()
    provider = providers.get(data["provider"])
    if not svc.give_consent():
        _clear(brain.memory)
        return BM.setup_failed()
    _grant_network(brain)
    if not _arm(brain, "key", {"changing": False}):
        return BM.setup_failed()
    return BM.ask_key(provider)


def _step_key(brain, svc, data, text, toks, word, cancel):
    if cancel:
        _clear(brain.memory)
        return BM.setup_cancelled()
    key = _key_candidate(text)
    if not key:
        if len(text) > 60 or len(toks) > 4:                      # a normal sentence, not a failed paste: the question is withdrawn
            return _WITHDRAW
        _touch(brain, "key", data)
        return BM.key_not_a_key()
    scrub_log(brain.memory, key)                                  # the message was logged before the brain saw it
    if not svc.set_key(key):
        _touch(brain, "key", data)
        return BM.key_not_a_key()
    _clear(brain.memory)
    svc.set_mode("auto")
    result = svc.probe()
    st = svc.status()
    if result.ok:
        if not _arm(brain, "private", {}):
            return BM.setup_done(False)
        return BM.key_check_ok(st["model"], st["model_is_default"])
    forgot = result.code == "bad_key"
    if forgot:
        svc.forget_key()
    return BM.key_check_failed(result.reason_fa, result.detail, forgot)


def _step_private(brain, svc, data, text, toks, word, cancel):
    if word not in ("confirm", "deny", "cancel"):
        return _WITHDRAW
    _clear(brain.memory)
    private = word == "confirm"
    svc.set_share_private(private)
    return BM.setup_done(private)


def _step_forget(brain, svc, data, text, toks, word, cancel):
    if word == "confirm":
        _clear(brain.memory)
        return BM.forgotten(svc.forget_key(), svc.learned.count())
    if cancel or word == "deny":
        _clear(brain.memory)
        return BM.forget_cancelled()
    return _WITHDRAW


_STEPS = {"provider": _step_provider, "url": _step_url, "consent": _step_consent, "key": _step_key, "private": _step_private,
          "forget": _step_forget}


# ================================================================== commands
def command(brain, turn):
    """`(kind, reply)` when the sentence is a cloud-brain command, else None. Never raises."""
    try:
        svc = service(brain)
        if svc is None:
            return None
        wrong = _wrong(svc, turn)
        if wrong is not None:
            return wrong
        cmd = BC.classify(turn.text, turn.norm, turn.toks)
        if cmd is None:
            return None
        turn.dlg.clear_pending()
        _clear(brain.memory)
        return "brain_" + cmd.kind, _run(brain, svc, turn, cmd)
    except Exception as exc:
        brain._log_error(exc, "")
        return None


def _wrong(svc, turn):
    """«این جواب غلط بود» - claimed ONLY when the reply just before was an answer of the cloud brain (from the cloud or from the kept
    answers). After anything else (a built capability, a command ...) the older feedback handling of the app answers it, unchanged."""
    if svc.last_answer() is None:
        return None
    intent = I.classify(turn.text, I.Context(None, None, False))
    if not (intent.is_(I.FEEDBACK) and intent.sub == "negative"):
        return None
    outcome = svc.forget_last_answer()
    if outcome is None:
        return None
    turn.dlg.clear_pending()
    return "brain_wrong", BM.wrong_dropped() if outcome == "dropped" else BM.wrong_not_kept()


def _start_setup(brain, turn, how=False):
    if not _arm(brain, "provider", {}, turn):
        return BM.setup_failed()                               # never worded like the user's own «no» (that wording hid a real bug on the phone)
    return (BM.setup_how_lead() if how else "") + BM.setup_intro()


def _run(brain, svc, turn, cmd):
    kind, st = cmd.kind, svc.status()
    if kind == BC.STATUS:
        return BM.status(st)
    if kind == BC.HELP:
        return BM.help_text(st)
    if kind == BC.SETUP:
        if st["provider"] and st["consent"] and st["key"]:
            if st["mode"] != "auto":
                svc.set_mode("auto")
            _grant_network(brain)
            return BM.turned_on(svc.status())
        return _start_setup(brain, turn, bool(cmd.slots.get("how")))
    if kind == BC.OFF:
        if st["mode"] == "off" and not st["provider"]:
            return BM.status(st)
        svc.set_mode("local")
        return BM.turned_off()
    if kind == BC.PROBE:
        if not st["ready"]:
            return BM.not_ready_probe(st["why"])
        result = svc.probe()
        return BM.probe_ok(st["model"]) if result.ok else BM.probe_failed(result.reason_fa, result.detail)
    if kind == BC.MODEL:
        if cmd.slots.get("missing"):
            return BM.model_missing()
        if not st["provider"]:
            return BM.need_setup()
        try:
            svc.set_model(cmd.slots["model"])
        except ValueError:
            return BM.model_bad()
        now = svc.status()
        return BM.model_set(now["model"], not now["model_is_default"])
    if kind in (BC.PRIVATE_ON, BC.PRIVATE_OFF):
        svc.set_share_private(kind == BC.PRIVATE_ON)
        return BM.private_set(kind == BC.PRIVATE_ON)
    if kind == BC.HISTORY_CLEAR:
        return BM.history_cleared(svc.clear_history())
    if kind == BC.MEM_STATUS:
        return BM.memory_status(st)
    if kind == BC.MEM_ON:
        svc.set_memory(True)
        return BM.memory_on_done()
    if kind == BC.MEM_OFF:
        svc.set_memory(False)
        return BM.memory_off_done(st["learned"])
    if kind == BC.MEM_CLEAR:
        return BM.memory_cleared(svc.clear_learned())
    if kind == BC.FORGET_KEY:
        if not st["key"]:
            return BM.no_key_to_forget()
        return BM.ask_forget() if _arm(brain, "forget", {}, turn) else BM.setup_failed()
    if kind == BC.CHANGE_KEY:
        if not (st["provider"] and st["consent"]):
            return BM.need_key_first()
        provider = providers.get(st["provider"])
        return BM.ask_key(provider, changing=True) if _arm(brain, "key", {"changing": True}, turn) else BM.setup_failed()
    return BM.status(st)


# ================================================================== a free sentence
def reply(brain, turn, intent=None):
    """The cloud brain's answer to a sentence nothing else in the app answered, or None (it is not for the cloud brain, or the cloud
    brain is not switched on). An answer is only TEXT - never run, never taken as a command. Never raises."""
    try:
        text = (turn.text or "").strip()
        if not text or len(text) > MAX_ASK_CHARS or sum(ch.isalpha() for ch in text) < 2 or I.answer_word(turn.toks):
            return None                                        # a bare yes / no, a number, a symbol: not a question for a model
        if len(turn.toks) < 2 and "?" not in text and "؟" not in text:
            return None
        svc = service(brain)
        if svc is None:
            return None
        return _render(svc, svc.reply(text))
    except Exception as exc:
        brain._log_error(exc, "")
        return None


def is_on(brain):
    """True when the user has switched his cloud brain on (mode «auto»): a sentence nothing else answered was already offered to it, so the
    app's «I do not know» replies must not tell him to switch it on. Never raises."""
    try:
        svc = service(brain)
        return bool(svc is not None and svc.status()["mode"] == "auto")
    except Exception:
        return False


def _render(svc, r):
    kind = r.kind
    if kind == "answer":
        return r.text + (BM.cut_note() if r.truncated else "") + (BM.kept_first_note() if r.first_keep else "")
    if kind == "memory":
        return r.text + BM.memory_footer(r.age_s, r.exact)
    if kind == "blocked":
        return BM.blocked(r.code, r.label_fa, r.secret)
    if kind == "failed":
        return BM.failed(r.reason_fa, r.detail)
    if kind == "halted":
        return BM.halted()
    if kind == "rate":
        return BM.rate_limited()
    if kind == "too_long":
        return BM.too_long()
    if kind == "not_ready" and r.code in ("no_network", "no_key") and svc.settings.get()["mode"] == "auto":
        return BM.fixable_not_ready(r.code)
    return None


__all__ = ["early", "command", "reply", "service", "scrub_log", "is_on", "PENDING_KEY", "TYPES"]
