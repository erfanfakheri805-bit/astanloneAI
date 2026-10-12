"""
Persian conversation brain - dialogue state
===========================================
What the brain remembers BETWEEN two messages, kept in the application's own
persistent key-value store (`memory.set_state`, table `state` of memory.db) so
that a question the brain asked before the app was killed ("Which units should
I convert between?") can still be answered after a restart:

  pending   the one open question the brain is waiting for an answer to
            {"type", "ts", "attempts", "data"}; types:
              clarify_build   a build request is missing a detail
              confirm_build   the builder asks for a go-ahead (confirmation)
              offer_build     "I do not have this capability - build it?"
              ask_inputs      a capability needs more input values
              confirm_rollback  "go back to the previous version?"
              confirm_disable   "switch this capability off?"
              confirm_teach   "should I remember this sentence?"
            A pending question expires after PENDING_TTL_SECONDS.
  last      the thing the conversation is about right now (last capability
            used / built / described, last knowledge answer) - what words like
            "همان" ("that one") and "ادامه بده" ("go on") refer to.

The state is written ONLY when it changes (never for a plain greeting), it is
size-bounded and sanitised on load (a damaged or foreign value is ignored, it
never breaks a conversation).
"""

import json
import time

STATE_KEY = "persian_brain.dialogue.v1"
PENDING_TTL_SECONDS = 30 * 60
MAX_PENDING_ATTEMPTS = 3
MAX_STATE_BYTES = 12_000

PENDING_TYPES = frozenset({"clarify_build", "confirm_build", "offer_build", "ask_inputs", "confirm_rollback",
                           "confirm_disable", "confirm_teach"})
LAST_KINDS = frozenset({"invoke", "build", "describe", "list", "knowledge", "rollback", "teach", "feedback"})


def _clean_json(value, depth=0):
    """JSON-safe copy (dict/list/str/number/bool/None only, bounded depth)."""
    if depth > 6:
        return None
    if isinstance(value, dict):
        return {str(k)[:60]: _clean_json(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_clean_json(v, depth + 1) for v in list(value)[:40]]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    return str(value)[:600]


def _is_text(value, limit=600):
    return isinstance(value, str) and 0 < len(value) <= limit


def _opt_text(value):
    return value is None or isinstance(value, str)


def _opt_number(value):
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def _opt_dict(value):
    return value is None or isinstance(value, dict)


def _opt_text_list(value):
    return value is None or (isinstance(value, list) and all(isinstance(v, str) for v in value))


def _pending_data_is_valid(type_, d):
    """Does `data` have the shape the question of kind `type_` needs?

    The dialogue state is plain JSON in the application's own database; only this code writes it, but a
    damaged, truncated or hand-edited value must never reach a handler (a handler that trusts its data
    could build, roll back or answer from garbage). A pending question whose data does not have the
    shape below is treated as if no question had been asked."""
    if type_ == "offer_build":
        return (_is_text(d.get("archetype"), 40) and isinstance(d.get("slots"), dict)
                and _opt_number(d.get("value")) and _opt_text(d.get("payload")) and _opt_text(d.get("question")))
    if type_ == "confirm_build":
        req = d.get("request")
        return (isinstance(req, dict) and _opt_text(req.get("status")) and _opt_text(req.get("kind"))
                and isinstance(req.get("slots", {}), dict) and _opt_text_list(req.get("missing", []))
                and _opt_text(d.get("text")))
    if type_ == "confirm_rollback":
        return _is_text(d.get("capability_id"), 80) and _opt_number(d.get("version"))
    if type_ == "confirm_disable":
        return _is_text(d.get("capability_id"), 80)
    if type_ == "confirm_teach":
        return _is_text(d.get("sentence"))
    if type_ == "clarify_build":
        return (_opt_text(d.get("kind")) and isinstance(d.get("slots"), dict) and _opt_text_list(d.get("missing"))
                and _opt_text(d.get("note")) and _opt_text(d.get("text")))
    if type_ == "ask_inputs":
        return (_is_text(d.get("capability_id"), 80) and _opt_text(d.get("title")) and _opt_text(d.get("need"))
                and _opt_dict(d.get("have")) and _opt_text_list(d.get("missing")))
    return False


def _last_is_valid(last):
    return (_opt_text(last.get("capability_id")) and _opt_text(last.get("title")) and _opt_dict(last.get("inputs"))
            and _opt_number(last.get("version")) and _opt_text(last.get("name")))


class Dialogue:
    """One conversation's state, loaded fresh at the start of each message
    (`load()`) and written back by `commit()` only when it changed."""

    def __init__(self, memory, clock=None):
        self._memory = memory
        self._clock = clock or time.time
        self._pending = None
        self._last = None
        self._loaded_json = None

    # ------------------------------------------------------------------ load
    def now(self):
        return float(self._clock())

    def load(self):
        raw = None
        try:
            raw = self._memory.get_state(STATE_KEY)
        except Exception:
            raw = None
        pending, last = None, None
        if isinstance(raw, dict) and raw.get("v") == 1:
            pending = self._sanitize_pending(raw.get("pending"))
            last = self._sanitize_last(raw.get("last"))
        self._pending, self._last = pending, last
        # what the database holds right now (so an expired pending is written back as cleared)
        self._loaded_json = self._dump(self._sanitize_pending_raw(raw), self._sanitize_last_raw(raw))
        return self

    def _sanitize_pending_raw(self, raw):
        if isinstance(raw, dict) and raw.get("v") == 1:
            p = raw.get("pending")
            return p if isinstance(p, dict) else None
        return None

    def _sanitize_last_raw(self, raw):
        if isinstance(raw, dict) and raw.get("v") == 1:
            l = raw.get("last")
            return l if isinstance(l, dict) else None
        return None

    def _sanitize_pending(self, p):
        if not isinstance(p, dict) or p.get("type") not in PENDING_TYPES:
            return None
        try:
            ts = float(p.get("ts", 0))
            attempts = int(p.get("attempts", 0))
        except (TypeError, ValueError):
            return None
        if self.now() - ts > PENDING_TTL_SECONDS or ts - self.now() > 60:
            return None  # expired (or a clock from the future)
        data = p.get("data")
        data = _clean_json(data) if isinstance(data, dict) else {}
        if not _pending_data_is_valid(p["type"], data):
            return None  # damaged / foreign data: no handler ever sees it
        return {"type": p["type"], "ts": ts, "attempts": max(0, min(attempts, 20)), "data": data}

    def _sanitize_last(self, l):
        if not isinstance(l, dict) or l.get("kind") not in LAST_KINDS:
            return None
        l = _clean_json(l)
        return l if _last_is_valid(l) else None

    # ------------------------------------------------------------- accessors
    @property
    def pending(self):
        return self._pending

    @property
    def pending_type(self):
        return self._pending["type"] if self._pending else None

    @property
    def last(self):
        return self._last

    # -------------------------------------------------------------- mutation
    def set_pending(self, type_, data=None, attempts=0):
        if type_ not in PENDING_TYPES:
            raise ValueError(f"unknown pending type {type_!r}")
        self._pending = {"type": type_, "ts": self.now(), "attempts": int(attempts),
                         "data": _clean_json(data or {})}

    def clear_pending(self):
        self._pending = None

    def bump_attempts(self):
        """Count one more failed answer to the pending question; returns the new count."""
        if self._pending is None:
            return 0
        self._pending["attempts"] += 1
        self._pending["ts"] = self.now()
        return self._pending["attempts"]

    def update_pending_data(self, **fields):
        if self._pending is not None:
            self._pending["data"] = dict(self._pending["data"], **_clean_json(fields))
            self._pending["ts"] = self.now()

    def set_last(self, kind, **fields):
        if kind not in LAST_KINDS:
            raise ValueError(f"unknown last kind {kind!r}")
        self._last = _clean_json(dict(fields, kind=kind, ts=self.now()))

    def clear_last(self):
        self._last = None

    # ---------------------------------------------------------------- commit
    @staticmethod
    def _dump(pending, last):
        # `ts` values move on every touch; they are part of the state but the
        # comparison for "did anything change" ignores pure re-stamping of `last`
        return json.dumps({"v": 1, "pending": pending, "last": last}, sort_keys=True, ensure_ascii=False)

    def commit(self):
        """Write the state back if (and only if) it changed. Never raises."""
        payload = {"v": 1, "pending": self._pending, "last": self._last}
        try:
            text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            if len(text.encode("utf-8")) > MAX_STATE_BYTES:
                payload["last"] = None  # the pending question matters more than the topic
                text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            if len(text.encode("utf-8")) > MAX_STATE_BYTES:
                payload["pending"] = None
                text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            if text == self._loaded_json:
                return False
            self._memory.set_state(STATE_KEY, payload)
            self._loaded_json = text
            return True
        except Exception:
            return False


__all__ = ["Dialogue", "STATE_KEY", "PENDING_TTL_SECONDS", "MAX_PENDING_ATTEMPTS", "PENDING_TYPES", "LAST_KINDS"]
