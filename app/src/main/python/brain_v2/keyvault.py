"""
brain_v2.keyvault - the user's own API key, kept on the phone and nowhere else
=============================================================================
The key is typed (pasted) by the user in the chat, validated (one token of printable ASCII: no spaces, quotes or control
characters, so a header can never be forged with it), and stored in `<hub root>/brain_v2/key.dat`:

* created with mode 0600 inside the app's private data folder, written atomically;
* never logged, never put in an audit line, never shown again - the chat can only show a MASK («AIza…r2», first four and last
  two characters) so the user can tell which key is stored;
* removed by `forget()` (the file is deleted; nothing else keeps a copy);
* it is only ever read by `BrainV2` when it makes a request to the host the user consented to.

Honest limits: this is the protection every Android app has for its private files, not hardware-backed encryption
(Android Keystore is a later step). Someone who can read the app's private folder (a rooted phone, a malicious backup tool)
could read the key; a key with a spending limit set at the provider is the real safety net - the chat says so.
"""

import threading

from . import providers, store

__all__ = ["KeyVault", "mask", "FILE_NAME"]

FILE_NAME = "key.dat"
MAX_BYTES = 1024


def mask(key):
    key = str(key or "")
    return "%s…%s" % (key[:4], key[-2:]) if len(key) >= 12 else "…"


class KeyVault:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()

    def put(self, key):
        """Store `key` (replacing any other). False when it is not an acceptable key or cannot be saved."""
        key = str(key or "").strip()
        if not providers.valid_key(key):
            return False
        with self._lock:
            try:
                store.write_private_text(self.path, key + "\n")
            except OSError:
                return False
        return True

    def get(self):
        """The stored key, or '' (none, damaged, or hand-edited into something that is not a key)."""
        with self._lock:
            try:
                text = store.read_text(self.path, MAX_BYTES).strip()
            except (OSError, ValueError):
                return ""
        return text if providers.valid_key(text) else ""

    def exists(self):
        return bool(self.get())

    def masked(self):
        return mask(self.get()) if self.exists() else ""

    def forget(self):
        """Delete the key file. True when no key is left."""
        with self._lock:
            return store.remove(self.path)
