"""
brain_hub.permissions - what the USER has allowed the app to do on its own
==========================================================================
One closed set of app-level permissions (today only `network`), stored in `<root>/permissions.json`.

* A permission is granted only by `grant(name, user_approved=True)`; anything else is refused, so no code path can
  grant it "by accident" (the chat layer calls it only after an explicit yes).
* The file is written atomically BEFORE the in-memory state changes, so the app never behaves as if it had a
  permission that was not saved (and never loses one it reported as saved).
* A damaged or foreign file is set aside and nothing is granted (fail closed).
* `gate()` is the live `net_tools` gate: it reads the CURRENT state at every request, so a revoke takes effect at once.

Android permissions (microphone, camera ...) are NOT stored here: Android itself is their only source of truth
(`android_adapters`). Per-extension grants (clock / storage / network) live with the extension manager.
"""

import os
import threading
import time
from dataclasses import dataclass

from net_tools import CallableGate

from . import atomic

__all__ = ["HUB_PERMISSIONS", "PermissionChange", "PermissionStore", "FILE_NAME"]

FILE_NAME = "permissions.json"
MAX_FILE_BYTES = 8192

HUB_PERMISSIONS = {
    "network": {
        "label_fa": "دسترسی به اینترنت",
        "label_en": "Internet access",
        "covers_fa": "خواندن صفحه‌های وب و دانلود فایل‌هایی که خودت جداگانه تأیید کنی (مثل مدل‌ها)",
        "covers_en": "reading web pages and downloading files you approve separately (such as models)",
    },
}


@dataclass(frozen=True)
class PermissionChange:
    ok: bool
    code: str  # ok | already_granted | not_granted | approval_required | unknown_permission | io_error
    name: str
    granted: bool
    message_fa: str
    message_en: str


def _label(name):
    meta = HUB_PERMISSIONS.get(name)
    return (meta["label_fa"], meta["label_en"]) if meta else (str(name)[:40], str(name)[:40])


class PermissionStore:
    def __init__(self, root, clock=time.time):
        if not isinstance(root, (str, os.PathLike)) or not str(root):
            raise ValueError("root must be a path")
        self.root = os.fspath(root)
        self.path = os.path.join(self.root, FILE_NAME)
        self._clock = clock
        self._lock = threading.RLock()
        self._grants = None
        self.recovery = None  # set when a damaged file was found and moved aside

    # ---- loading (lazy, strict, fail closed) ---------------------------------------------------
    def _load(self):
        if self._grants is not None:
            return self._grants
        grants = {}
        if os.path.exists(self.path) or os.path.islink(self.path):
            try:
                doc = atomic.read_json_bounded(self.path, MAX_FILE_BYTES)
                if type(doc) is not dict or set(doc) != {"schema", "granted"} or doc["schema"] != 1 \
                        or type(doc["granted"]) is not dict:
                    raise ValueError("structure")
                for name, info in doc["granted"].items():
                    if name not in HUB_PERMISSIONS or type(info) is not dict or set(info) != {"at", "by"} \
                            or isinstance(info["at"], bool) or not isinstance(info["at"], (int, float)) \
                            or not isinstance(info["by"], str) or len(info["by"]) > 40:
                        raise ValueError("entry")
                    grants[name] = {"at": float(info["at"]), "by": info["by"]}
            except (ValueError, OSError):
                grants = {}
                self.recovery = {"moved_to": atomic.set_aside(self.path), "at": float(self._clock())}
        self._grants = grants
        return grants

    def _persist(self, grants):
        atomic.write_json_atomic(self.path, {"schema": 1, "granted": {k: dict(v) for k, v in sorted(grants.items())}})

    # ---- reading ---------------------------------------------------------------------------------
    def is_granted(self, name):
        with self._lock:
            return isinstance(name, str) and name in self._load()

    def snapshot(self):
        """{name: {"at", "by"}} of everything granted right now."""
        with self._lock:
            return {k: dict(v) for k, v in self._load().items()}

    def describe(self):
        """One row per known permission (granted or not) for display."""
        with self._lock:
            grants = self._load()
            rows = []
            for name, meta in HUB_PERMISSIONS.items():
                info = grants.get(name)
                rows.append({"name": name, "granted": info is not None, "at": info["at"] if info else None,
                             "by": info["by"] if info else None, "label_fa": meta["label_fa"], "label_en": meta["label_en"],
                             "covers_fa": meta["covers_fa"], "covers_en": meta["covers_en"]})
            return rows

    def gate(self):
        """A live `net_tools` permission gate (fails closed on any error)."""
        return CallableGate(self.is_granted)

    # ---- changing ----------------------------------------------------------------------------------
    def grant(self, name, *, user_approved=False, by="user"):
        if name not in HUB_PERMISSIONS:
            return PermissionChange(False, "unknown_permission", str(name)[:40], False,
                                    "چنین مجوزی در برنامه وجود ندارد.", "There is no such permission in the app.")
        fa, en = _label(name)
        if user_approved is not True:
            return PermissionChange(False, "approval_required", name, self.is_granted(name),
                                    "برای «%s» باید خودت صریحاً تأیید کنی." % fa, "“%s” needs your explicit approval." % en)
        with self._lock:
            grants = self._load()
            if name in grants:
                return PermissionChange(True, "already_granted", name, True, "«%s» از قبل فعال بود." % fa,
                                        "“%s” was already on." % en)
            updated = dict(grants)
            updated[name] = {"at": float(self._clock()), "by": str(by)[:40] or "user"}
            try:
                self._persist(updated)
            except OSError:
                return PermissionChange(False, "io_error", name, False, "ذخیرهٔ مجوز ناموفق بود؛ چیزی فعال نشد.",
                                        "Saving the permission failed; nothing was turned on.")
            self._grants = updated
            return PermissionChange(True, "ok", name, True, "«%s» فعال شد." % fa, "“%s” is now on." % en)

    def revoke(self, name, *, by="user"):
        if name not in HUB_PERMISSIONS:
            return PermissionChange(False, "unknown_permission", str(name)[:40], False,
                                    "چنین مجوزی در برنامه وجود ندارد.", "There is no such permission in the app.")
        fa, en = _label(name)
        with self._lock:
            grants = self._load()
            if name not in grants:
                return PermissionChange(True, "not_granted", name, False, "«%s» از قبل خاموش بود." % fa,
                                        "“%s” was already off." % en)
            updated = {k: v for k, v in grants.items() if k != name}
            try:
                self._persist(updated)
            except OSError:
                return PermissionChange(False, "io_error", name, True, "ذخیرهٔ تغییر ناموفق بود؛ مجوز هنوز فعال است.",
                                        "Saving the change failed; the permission is still on.")
            self._grants = updated
            return PermissionChange(True, "ok", name, False, "«%s» خاموش شد." % fa, "“%s” is now off." % en)
