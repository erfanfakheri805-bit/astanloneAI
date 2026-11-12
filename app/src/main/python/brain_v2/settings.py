"""
brain_v2.settings - what the user decided about the cloud brain
===============================================================
`<hub root>/brain_v2/settings.json` (private, atomic, strict). It holds ONLY decisions, never the key (the key has its own file,
see `secrets`) and never any conversation.

    mode          "off" (nothing is ever sent) | "auto" (a sentence the local layers cannot answer may go to the cloud brain)
                  | "local" (the setup is kept but nothing is sent - the quick "offline" switch)
    provider      one of `providers.ORDER`, or "" before the setup
    base_url      only for the custom provider (https, validated)
    model         the model name sent to the service ("" = the provider's default)
    consent       {"host", "ts", "provider"}: the user said «بله» to sending his messages to THIS host; None before that
    share_private may messages with personal details (name, phone, e-mail ...) go out? Secrets (keys, cards, one-time codes) NEVER do.
    halted        the emergency stop: while True nothing goes out
    memory_on     may the app keep answers it got once, to give them again offline?  (default True; the user can switch it off)
    kept_note     the one-time "I kept this answer" note has been shown

A damaged or foreign file is set aside and the defaults apply (mode "off": fail closed).
"""

import threading
import time

from . import providers, store

__all__ = ["Settings", "DEFAULTS", "MODES", "FILE_NAME"]

FILE_NAME = "settings.json"
MAX_BYTES = 8192
MODES = ("off", "auto", "local")
DEFAULTS = {"schema": 1, "mode": "off", "provider": "", "base_url": "", "model": "", "consent": None, "share_private": False,
            "halted": False, "memory_on": True, "kept_note": False}
_BOOLS = ("share_private", "halted", "memory_on", "kept_note")


def _valid_consent(value):
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {"host", "ts", "provider"}:
        return False
    ts = value["ts"]
    return (isinstance(value["host"], str) and bool(providers.host_of("https://%s/" % value["host"]))
            and not isinstance(ts, bool) and isinstance(ts, (int, float)) and value["provider"] in providers.ORDER)


def _check(key, value):
    """True when `value` is acceptable for the setting `key`."""
    if key == "mode":
        return value in MODES
    if key == "provider":
        return value == "" or value in providers.ORDER
    if key == "base_url":
        return value == "" or providers.valid_custom_base(value)[0] == value
    if key == "model":
        return value == "" or providers.valid_model(value)
    if key == "consent":
        return _valid_consent(value)
    if key in _BOOLS:
        return isinstance(value, bool)
    return False


class Settings:
    def __init__(self, path, clock=time.time):
        self.path = path
        self._clock = clock
        self._lock = threading.RLock()
        self._data = None
        self.recovery = None           # set when a damaged file was moved aside

    def _load(self):
        if self._data is not None:
            return self._data
        data = dict(DEFAULTS)
        try:
            doc = store.read_json(self.path, MAX_BYTES)
        except FileNotFoundError:
            doc = None
        except (ValueError, OSError):
            doc = False
        if doc is False or (doc is not None and not self._acceptable(doc)):
            self.recovery = {"moved_to": store.set_aside(self.path), "at": float(self._clock())}
        elif doc is not None:
            data.update(doc)
        self._data = data
        return data

    @staticmethod
    def _acceptable(doc):
        if not isinstance(doc, dict) or doc.get("schema") != 1 or not set(doc) <= set(DEFAULTS):
            return False
        return all(_check(k, v) for k, v in doc.items() if k != "schema")

    def get(self):
        with self._lock:
            return dict(self._load())

    def update(self, **changes):
        """Change settings (all-or-nothing). Raises ValueError for an unknown key or a bad value; OSError when it cannot be saved."""
        with self._lock:
            data = dict(self._load())
            for key, value in changes.items():
                if key not in DEFAULTS or key == "schema" or not _check(key, value):
                    raise ValueError("bad setting: %s" % str(key)[:30])
                data[key] = dict(value) if isinstance(value, dict) else value
            store.write_private_json(self.path, data)
            self._data = data
            return dict(data)

    def reset(self):
        with self._lock:
            data = dict(DEFAULTS)
            store.write_private_json(self.path, data)
            self._data = data
            return dict(data)
