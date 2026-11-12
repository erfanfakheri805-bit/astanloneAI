"""
brain_v2.history - the short memory the cloud brain gets with each question
===========================================================================
So that «و پایتختش؟» after «فرانسه کجاست؟» makes sense, the last few exchanges are sent along with the new question. This keeps
them on the phone (`<hub root>/brain_v2/history.json`, private, atomic):

* at most `MAX_TURNS` exchanges, each side cut at `MAX_CHARS`; an exchange older than `TTL_SECONDS` is forgotten;
* only exchanges whose user message PASSED the privacy check ever get in (the caller's job; `add` refuses to store a blocked one);
* the user can wipe it any time («تاریخچهٔ مغز ابری را پاک کن»); a damaged file is set aside and the history starts empty.
"""

import threading
import time

from . import store

__all__ = ["History", "MAX_TURNS", "MAX_CHARS", "TTL_SECONDS", "FILE_NAME"]

FILE_NAME = "history.json"
MAX_TURNS = 6
MAX_CHARS = 1200
TTL_SECONDS = 6 * 3600
MAX_BYTES = 64 * 1024


def _valid_turn(item):
    return (isinstance(item, dict) and set(item) == {"u", "a", "ts"} and isinstance(item["u"], str) and isinstance(item["a"], str)
            and not isinstance(item["ts"], bool) and isinstance(item["ts"], (int, float)))


class History:
    def __init__(self, path, clock=time.time):
        self.path = path
        self._clock = clock
        self._lock = threading.RLock()
        self._turns = None
        self.recovery = None

    def _load(self):
        if self._turns is not None:
            return self._turns
        turns = []
        try:
            doc = store.read_json(self.path, MAX_BYTES)
            if not isinstance(doc, dict) or doc.get("schema") != 1 or not isinstance(doc.get("turns"), list) \
                    or not all(_valid_turn(t) for t in doc["turns"]):
                raise ValueError("structure")
            turns = [dict(t) for t in doc["turns"]][-MAX_TURNS:]
        except FileNotFoundError:
            pass
        except (ValueError, OSError):
            self.recovery = {"moved_to": store.set_aside(self.path), "at": float(self._clock())}
        self._turns = turns
        return turns

    def _fresh(self):
        now = float(self._clock())
        return [t for t in self._load() if -60 <= now - t["ts"] <= TTL_SECONDS]

    def turns(self):
        with self._lock:
            return [(t["u"], t["a"]) for t in self._fresh()]

    def messages(self):
        """The turns as chat messages, oldest first."""
        out = []
        for user, assistant in self.turns():
            out.append({"role": "user", "content": user})
            out.append({"role": "assistant", "content": assistant})
        return out

    def count(self):
        with self._lock:
            return len(self._fresh())

    def add(self, user, assistant, skip_repeat=False):
        """Remember one exchange. False when either side is empty or the file cannot be written (the chat carries on).
        `skip_repeat`: when the newest remembered exchange is exactly this one, only its time is renewed in memory (no second copy)."""
        user, assistant = str(user or "").strip()[:MAX_CHARS], str(assistant or "").strip()[:MAX_CHARS]
        if not user or not assistant:
            return False
        with self._lock:
            fresh = self._fresh()
            if skip_repeat and fresh and (fresh[-1]["u"], fresh[-1]["a"]) == (user, assistant):
                return True
            turns = fresh + [{"u": user, "a": assistant, "ts": float(self._clock())}]
            turns = turns[-MAX_TURNS:]
            try:
                store.write_private_json(self.path, {"schema": 1, "turns": turns})
            except OSError:
                return False
            self._turns = turns
            return True

    def clear(self):
        """Forget everything; returns how many exchanges were forgotten."""
        with self._lock:
            n = len(self._fresh())
            store.remove(self.path)
            self._turns = []
            return n
