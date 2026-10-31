"""
Persian conversation brain - the hub's open question
====================================================
Everything the hub does that changes something (install an extension, roll one back, switch the internet on,
download a model ...) is first PROPOSED in the chat and happens only after the user's explicit «بله». The question
that is waiting for that answer lives here, in the application's own key-value store (`memory.set_state`), so it
survives a restart exactly like the dialogue state does - but in a key of its own: the dialogue module's closed set
of question types is pinned by tests and the hub must not widen it.

Rules:
* at most ONE open question; a new one replaces the old one;
* it expires after 30 minutes and is size-bounded;
* the value is validated on load - a damaged, foreign or hand-edited value is ignored (never raised, never acted on);
* nothing is written when there is nothing to write.

A second, tiny record keeps the user's last unsupported wish (24 hours) so «پرامپت افزونه» can embed it.
"""

import re
import time

PENDING_KEY = "persian_brain.hub_pending.v1"
WISH_KEY = "persian_brain.hub_wish.v1"
LLM_NOTE_KEY = "persian_brain.llm_note.v1"
PENDING_TTL_SECONDS = 30 * 60
WISH_TTL_SECONDS = 24 * 3600
MAX_WISH_CHARS = 600

PACK_TYPES = frozenset({"pack_install", "pack_install_risky", "pack_rollback", "pack_disable", "pack_enable", "pack_remove",
                        "pack_safe_leave"})
TEACHER_TYPES = frozenset({"teacher_send", "teacher_screen"})
PENDING_TYPES = frozenset({"install", "rollback", "disable", "enable", "perm_grant", "net_on", "model_download",
                           "model_license", "model_remove", "model_import", "repair_store"}) | PACK_TYPES | TEACHER_TYPES

_PROPOSAL_RE = re.compile(r"^p[0-9a-f]{6,24}$")
_PACK_PROPOSAL_RE = re.compile(r"^q[0-9a-f]{8,24}$")
_MISSION_RE = re.compile(r"^m[0-9a-f]{10}\Z")
_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+){1,8}\Z")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,59}$")
_MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
_PERMISSION_RE = re.compile(r"^[a-z_]{3,20}$")


def _text(value, limit):
    return isinstance(value, str) and 0 < len(value) <= limit


def _int_or_none(value):
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and 0 < value < 10 ** 6)


def _data_is_valid(type_, d):
    """Does `d` have the exact shape the question `type_` needs? (anything else is treated as 'no question')"""
    if not isinstance(d, dict):
        return False
    if type_ == "install":
        return (isinstance(d.get("proposal_id"), str) and bool(_PROPOSAL_RE.match(d["proposal_id"]))
                and isinstance(d.get("capability_id"), str) and bool(_ID_RE.match(d["capability_id"]))
                and _text(d.get("title"), 200) and d.get("action") in ("create", "update")
                and _int_or_none(d.get("planned_version")))
    if type_ in ("rollback", "disable", "enable", "perm_grant"):
        ok = isinstance(d.get("capability_id"), str) and bool(_ID_RE.match(d["capability_id"])) and _text(d.get("title"), 200)
        if type_ == "rollback":
            return ok and _int_or_none(d.get("to_version"))
        if type_ == "perm_grant":
            return ok and isinstance(d.get("permission"), str) and bool(_PERMISSION_RE.match(d["permission"]))
        return ok
    if type_ in ("model_download", "model_license", "model_remove"):
        return isinstance(d.get("model_id"), str) and bool(_MODEL_RE.match(d["model_id"]))
    if type_ == "model_import":      # one file of the app's own inbox (a plain name) that becomes the model `model_id`
        return (set(d) == {"file_name", "model_id"} and isinstance(d["file_name"], str) and bool(_FILE_RE.match(d["file_name"]))
                and isinstance(d["model_id"], str) and bool(_MODEL_RE.match(d["model_id"])))
    if type_ in PACK_TYPES:
        return _pack_data_is_valid(type_, d)
    if type_ in TEACHER_TYPES:
        return _teacher_data_is_valid(type_, d)
    if type_ == "net_on":      # optionally remembers the page the user wanted to read when the internet was off
        return set(d) <= {"url"} and (d.get("url") is None or (_text(d.get("url"), 600) and d["url"].lower().startswith("https://")))
    return type_ == "repair_store" and not d


def _pack_data_is_valid(type_, d):
    """The questions of the pack system (see `pack_system`): a pack proposal, or an action on one installed pack."""
    if type_ == "pack_safe_leave":
        return not d
    ok = isinstance(d.get("pack_id"), str) and bool(_ID_RE.match(d["pack_id"])) and _text(d.get("title"), 200)
    if type_ in ("pack_install", "pack_install_risky"):
        return (ok and isinstance(d.get("proposal_id"), str) and bool(_PACK_PROPOSAL_RE.match(d["proposal_id"]))
                and d.get("kind") in ("code.v1", "lang.v1") and _int_or_none(d.get("planned_version")))
    if type_ == "pack_rollback":
        return ok and _int_or_none(d.get("to_version"))
    return ok


def _teacher_data_is_valid(type_, d):
    """The questions of the teacher (asking another assistant, or letting the app look into another app): see `teacher`."""
    if not (isinstance(d.get("mission_id"), str) and _MISSION_RE.match(d["mission_id"])):
        return False
    if type_ == "teacher_send":
        return (set(d) == {"mission_id", "assistant", "kind"} and isinstance(d.get("assistant"), str) and bool(_ID_RE.match(d["assistant"]))
                and d.get("kind") in ("code", "lang", "ask"))
    return (set(d) == {"mission_id", "package"} and isinstance(d.get("package"), str) and len(d["package"]) <= 150
            and bool(_PACKAGE_RE.match(d["package"])))


def _now(clock):
    try:
        return float((clock or time.time)())
    except Exception:
        return time.time()


def load(memory, clock=None):
    """`(type, data)` of the open question, or None (none, expired, damaged, from the future). Never raises."""
    try:
        value = memory.get_state(PENDING_KEY)
    except Exception:
        return None
    if not isinstance(value, dict):
        return None
    type_, ts, data = value.get("type"), value.get("ts"), value.get("data")
    if type_ not in PENDING_TYPES or isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    now = _now(clock)
    if not (-60 <= now - ts <= PENDING_TTL_SECONDS) or not _data_is_valid(type_, data):
        return None
    return type_, dict(data)


def lapsed(memory, clock=None):
    """`(type, data)` of an intact question that was left unanswered for more than 30 minutes, else None. Never raises."""
    try:
        value = memory.get_state(PENDING_KEY)
    except Exception:
        return None
    if not isinstance(value, dict):
        return None
    type_, ts, data = value.get("type"), value.get("ts"), value.get("data")
    if type_ not in PENDING_TYPES or isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    if _now(clock) - ts <= PENDING_TTL_SECONDS or not _data_is_valid(type_, data):
        return None
    return type_, dict(data)


def save(memory, type_, data, clock=None):
    """Open the question `type_` (replacing any other). False when the data is not valid or the store fails."""
    if type_ not in PENDING_TYPES or not _data_is_valid(type_, data):
        return False
    try:
        memory.set_state(PENDING_KEY, {"type": type_, "ts": _now(clock), "data": dict(data)})
    except Exception:
        return False
    return True


def clear(memory):
    """Forget the open question (writes only when there was a record). Never raises."""
    try:
        if memory.get_state(PENDING_KEY) is not None:
            memory.set_state(PENDING_KEY, None)
    except Exception:
        return False
    return True


def save_wish(memory, text, clock=None):
    """Remember the last thing the user asked for that the app cannot do (for the extension prompt)."""
    wish = " ".join(str(text or "").split())[:MAX_WISH_CHARS]
    if not wish:
        return False
    try:
        memory.set_state(WISH_KEY, {"ts": _now(clock), "text": wish})
    except Exception:
        return False
    return True


def load_wish(memory, clock=None):
    """The remembered wish, or '' (none / older than 24 hours / damaged)."""
    try:
        value = memory.get_state(WISH_KEY)
    except Exception:
        return ""
    if not isinstance(value, dict) or not isinstance(value.get("text"), str):
        return ""
    ts = value.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not (-60 <= _now(clock) - ts <= WISH_TTL_SECONDS):
        return ""
    return value["text"][:MAX_WISH_CHARS]


def llm_note_shown(memory, model_id):
    """Has the one-time note about a language model's answers already been shown for this model? Never raises."""
    try:
        return memory.get_state(LLM_NOTE_KEY) == str(model_id)
    except Exception:
        return True            # when it cannot be known, do not nag


def mark_llm_note(memory, model_id):
    try:
        memory.set_state(LLM_NOTE_KEY, str(model_id)[:64])
    except Exception:
        return False
    return True


__all__ = ["PENDING_KEY", "WISH_KEY", "LLM_NOTE_KEY", "llm_note_shown", "mark_llm_note", "PENDING_TYPES", "PACK_TYPES", "TEACHER_TYPES", "PENDING_TTL_SECONDS", "WISH_TTL_SECONDS", "load",
           "lapsed", "save", "clear", "save_wish", "load_wish"]
