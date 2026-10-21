"""
brain_hub.audit - the hub's own append-only, hash-chained history
=================================================================
`<root>/hub_audit.jsonl`: one JSON object per line,

    {"seq": n, "ts": t, "kind": "...", "subject": "...", "detail": {...}, "prev": "<sha256>", "hash": "<sha256>"}

where `hash = sha256(prev + "|" + canonical_json(seq, ts, kind, subject, detail))`. Changing, removing or reordering a
line makes `verify()` report the first bad entry. Extensions keep their own (also hash-chained) history in `hub.db`;
this log records the hub-level decisions: permissions granted or revoked, web reads (host only, never the query
string), model approvals and downloads, Android permission requests, hub restarts and recoveries.

* every detail value is clipped and JSON-safe; secrets, full URLs and user text are the caller's to leave out;
* a crash in the middle of an append leaves a torn last line, which is cut off at the next start;
* above `MAX_BYTES` the file rotates to `hub_audit.jsonl.1` and the chain simply continues in the new file;
* `append` never raises: a failed write is counted in `failures` and the caller carries on (the hub reports it).
"""

import hashlib
import json
import os
import re
import threading
import time

__all__ = ["HubAudit", "FILE_NAME", "MAX_BYTES"]

FILE_NAME = "hub_audit.jsonl"
MAX_BYTES = 1_000_000
MAX_STR = 200
MAX_KEYS = 12
_KIND_RE = re.compile(r"^[a-z][a-z0-9_.]{1,40}$")
_GENESIS = "0" * 64


def _clean(value, depth=0):
    if depth > 2:
        return None
    if isinstance(value, dict):
        return {str(k)[:40]: _clean(v, depth + 1) for k, v in list(value.items())[:MAX_KEYS]}
    if isinstance(value, (list, tuple)):
        return [_clean(v, depth + 1) for v in list(value)[:MAX_KEYS]]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    return str(value)[:MAX_STR]


def _digest(prev, seq, ts, kind, subject, detail):
    body = json.dumps({"seq": seq, "ts": ts, "kind": kind, "subject": subject, "detail": detail}, sort_keys=True,
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256((prev + "|" + body).encode("utf-8")).hexdigest()


class HubAudit:
    def __init__(self, path, clock=time.time):
        self.path = os.fspath(path)
        self._clock = clock
        self._lock = threading.RLock()
        self._seq = None
        self._prev = _GENESIS
        self.failures = 0
        self.repaired_tail = False

    # ---- state -------------------------------------------------------------------------------------
    def _read_lines(self):
        try:
            with open(self.path, "rb") as handle:
                return handle.read().split(b"\n")
        except FileNotFoundError:
            return []

    def _load(self):
        if self._seq is not None:
            return
        self._seq, self._prev = 0, _GENESIS
        try:
            lines = self._read_lines()
            if lines and lines[-1] != b"":                       # the file does not end with a newline: a torn append
                torn = lines.pop()
                keep = len(b"\n".join(lines)) + (1 if lines else 0)
                try:
                    json.loads(torn.decode("utf-8"))
                    with open(self.path, "ab") as handle:         # complete JSON, only the newline is missing
                        handle.write(b"\n")
                    lines.append(torn)
                except (ValueError, UnicodeDecodeError):
                    with open(self.path, "r+b") as handle:
                        handle.truncate(keep)
                    self.repaired_tail = True
            for raw in reversed([ln for ln in lines if ln]):
                try:
                    last = json.loads(raw.decode("utf-8"))
                    self._seq, self._prev = int(last["seq"]), str(last["hash"])
                    break
                except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                    continue
        except OSError:
            self.failures += 1

    # ---- writing -------------------------------------------------------------------------------------
    def append(self, kind, subject="", detail=None):
        """Record one event; returns the stored entry, or None when the write failed (counted in `failures`)."""
        with self._lock:
            self._load()
            kind = kind if isinstance(kind, str) and _KIND_RE.match(kind) else "unknown"
            subject = str(subject)[:MAX_STR]
            clean = _clean(detail or {})
            ts = round(float(self._clock()), 3)
            seq = self._seq + 1
            entry = {"seq": seq, "ts": ts, "kind": kind, "subject": subject, "detail": clean, "prev": self._prev,
                     "hash": _digest(self._prev, seq, ts, kind, subject, clean)}
            line = (json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
                if os.path.exists(self.path) and os.path.getsize(self.path) > MAX_BYTES:
                    os.replace(self.path, self.path + ".1")
                with open(self.path, "ab") as handle:
                    handle.write(line)
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError:
                self.failures += 1
                return None
            self._seq, self._prev = seq, entry["hash"]
            return entry

    # ---- reading -------------------------------------------------------------------------------------
    def entries(self):
        """Every parsable entry of the current file (oldest first)."""
        with self._lock:
            out = []
            try:
                for raw in self._read_lines():
                    if not raw:
                        continue
                    try:
                        out.append(json.loads(raw.decode("utf-8")))
                    except (ValueError, UnicodeDecodeError):
                        continue
            except OSError:
                self.failures += 1
            return out

    def tail(self, limit=20):
        limit = max(1, min(int(limit), 200))
        return self.entries()[-limit:]

    def verify(self):
        """{"ok", "entries", "first_bad_seq"}: the chain inside the current file (its first `prev` is the anchor)."""
        with self._lock:
            prev, expected_seq, count = None, None, 0
            try:
                lines = [ln for ln in self._read_lines() if ln]
            except OSError:
                return {"ok": False, "entries": 0, "first_bad_seq": 0}
            for index, raw in enumerate(lines, 1):
                try:
                    e = json.loads(raw.decode("utf-8"))
                    seq, ts, kind, subject, detail = e["seq"], e["ts"], e["kind"], e["subject"], e["detail"]
                    stored_prev, stored_hash = e["prev"], e["hash"]
                except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                    return {"ok": False, "entries": count, "first_bad_seq": index}
                if prev is not None and (stored_prev != prev or seq != expected_seq):
                    return {"ok": False, "entries": count, "first_bad_seq": seq if isinstance(seq, int) else index}
                if _digest(stored_prev, seq, ts, kind, subject, detail) != stored_hash:
                    return {"ok": False, "entries": count, "first_bad_seq": seq if isinstance(seq, int) else index}
                prev, expected_seq, count = stored_hash, seq + 1, count + 1
            return {"ok": True, "entries": count, "first_bad_seq": None}
