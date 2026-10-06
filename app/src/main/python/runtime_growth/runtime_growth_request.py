"""
Runtime growth - Runtime Growth Request (Prompt 939)
====================================================
The first, smallest component of the internal growth path: a plain-data request
from the running application to create or improve one of its capabilities (or its
runtime). It only RECORDS the request; later growth stages decide what to do.

`create_runtime_growth_request(data)` is a pure, deterministic constructor and
normalizer. `data` is a dict with `kind`, `goal`, `target` (required) and
`reason`, `source` (optional). It returns a fresh dict with exactly the fields
version, request_id, kind, goal, target, reason, source, status:

  - valid   -> status "requested"; text fields stripped with inner whitespace
               collapsed; `request_id` derived from the normalized content only
               (SHA-256 of canonical JSON), so equivalent inputs give equal ids
               and meaningfully different inputs give different ids;
  - invalid -> the exact safe state (status "invalid", every other field None)
               for a non-dict, an unknown kind, a missing/empty goal or target,
               a non-string or over-long value, or an unexpected key.

It has no execution, approval, code or modification fields and does none of
those things: no file, memory.db, network, clock, randomness or environment
access, and the input is never mutated. It never raises. It is not wired into
Core, AEL, capabilities, upgrades, Android or Section 18.
"""

import hashlib
import json

REQUEST_VERSION = "1"

KIND_CREATE_CAPABILITY = "CREATE_CAPABILITY"
KIND_IMPROVE_CAPABILITY = "IMPROVE_CAPABILITY"
KIND_IMPROVE_RUNTIME = "IMPROVE_RUNTIME"
REQUEST_KINDS = (KIND_CREATE_CAPABILITY, KIND_IMPROVE_CAPABILITY, KIND_IMPROVE_RUNTIME)

STATUS_REQUESTED = "requested"
STATUS_INVALID = "invalid"

DEFAULT_SOURCE = "runtime"
REQUEST_ID_PREFIX = "growth_req_"
REQUEST_ID_DIGITS = 16
MAX_TEXT_LENGTH = 500

FIELDS = ("version", "request_id", "kind", "goal", "target", "reason", "source", "status")
_INPUT_KEYS = ("kind", "goal", "target", "reason", "source")


def _normalize_text(value):
    """Stripped text with runs of whitespace collapsed to one space, or None when
    the value is not a string or is longer than MAX_TEXT_LENGTH."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text if len(text) <= MAX_TEXT_LENGTH else None


def _invalid_request():
    return {"version": REQUEST_VERSION, "request_id": None, "kind": None, "goal": None,
            "target": None, "reason": None, "source": None, "status": STATUS_INVALID}


def derive_runtime_growth_request_id(kind, goal, target, reason, source):
    """Deterministic bounded id from the normalized request content only."""
    text = json.dumps({"version": REQUEST_VERSION, "kind": kind, "goal": goal, "target": target,
                       "reason": reason, "source": source},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return REQUEST_ID_PREFIX + hashlib.sha256(text.encode("ascii")).hexdigest()[:REQUEST_ID_DIGITS]


def create_runtime_growth_request(data):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not isinstance(data, dict) or any(k not in _INPUT_KEYS for k in data):
            return _invalid_request()
        kind = _normalize_text(data.get("kind"))
        goal = _normalize_text(data.get("goal"))
        target = _normalize_text(data.get("target"))
        reason = _normalize_text(data.get("reason", ""))
        source = _normalize_text(data.get("source", DEFAULT_SOURCE))
        if kind not in REQUEST_KINDS or not goal or not target or reason is None or not source:
            return _invalid_request()
        return {"version": REQUEST_VERSION,
                "request_id": derive_runtime_growth_request_id(kind, goal, target, reason, source),
                "kind": kind, "goal": goal, "target": target, "reason": reason,
                "source": source, "status": STATUS_REQUESTED}
    except Exception:  # noqa: BLE001 - the constructor never raises
        return _invalid_request()
