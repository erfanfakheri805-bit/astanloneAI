"""
teacher.store - the teacher's small memory: missions and the list of apps the user allowed
=========================================================================================
`<hub root>/teacher/state.json` (atomic writes, bounded, validated on load - a damaged file is set aside and the teacher
starts empty; it never raises into the app):

* missions   what the user asked another assistant to do, and how far it got (no pack text is kept here - a captured pack
             goes straight into the pack system's own proposal; only a plain `ask` answer is kept, bounded)
* allow      `{package: expires_at}` - the apps the user allowed the assistant to look into, each for a limited time
"""

import os
import re
import threading
import time

from brain_hub import atomic
from native_bridge.doors import valid_package

__all__ = ["TeacherStore", "STATES", "OPEN_STATES", "ROUTES", "KINDS", "FILE_NAME"]

FILE_NAME = "state.json"
KINDS = ("code", "lang", "ask")
ROUTES = ("", "share", "copy_open", "site", "screen")
STATES = ("drafted", "sent", "running", "captured", "proposed", "done", "failed", "cancelled")
OPEN_STATES = frozenset({"drafted", "sent", "running", "captured"})
MAX_MISSIONS = 12
MISSION_TTL = 7 * 24 * 3600
MAX_ALLOWED = 8
MAX_ALLOW_MINUTES = 120
MAX_ANSWER_CHARS = 8000
MAX_FILE_BYTES = 400_000
_ID_RE = re.compile(r"^m[0-9a-f]{10}\Z")
_ASSISTANT_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}\Z")


def _clip(value, limit):
    return str(value or "")[:limit]


class TeacherStore:
    def __init__(self, root, clock=time.time):
        self.dir = os.path.join(os.fspath(root), "teacher")
        self.path = os.path.join(self.dir, FILE_NAME)
        self._clock = clock
        self._lock = threading.RLock()

    # ---- disk -----------------------------------------------------------------------------------------------------
    def _load(self):
        empty = {"v": 1, "missions": [], "allow": {}}
        try:
            raw = atomic.read_json_bounded(self.path, MAX_FILE_BYTES)
        except FileNotFoundError:
            return empty
        except (ValueError, OSError):
            atomic.set_aside(self.path)
            return empty
        if not isinstance(raw, dict):
            atomic.set_aside(self.path)
            return empty
        now = float(self._clock())
        missions = []
        for item in raw.get("missions") if isinstance(raw.get("missions"), list) else []:
            mission = self._valid_mission(item)
            if mission is not None and now - mission["created"] <= MISSION_TTL:
                missions.append(mission)
        allow = {}
        if isinstance(raw.get("allow"), dict):
            for package, expires in raw["allow"].items():
                if valid_package(package) and isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires > now:
                    allow[package] = float(expires)
        return {"v": 1, "missions": missions[-MAX_MISSIONS:], "allow": dict(sorted(allow.items(), key=lambda kv: kv[1])[-MAX_ALLOWED:])}

    @staticmethod
    def _valid_mission(item):
        if not isinstance(item, dict):
            return None
        try:
            mission = {"id": str(item["id"]), "kind": str(item["kind"]), "wish": _clip(item.get("wish"), 700), "assistant": str(item.get("assistant") or ""),
                       "route": str(item.get("route") or ""), "state": str(item["state"]), "created": float(item["created"]),
                       "updated": float(item.get("updated") or item["created"]), "note": _clip(item.get("note"), 300),
                       "answer": _clip(item.get("answer"), MAX_ANSWER_CHARS), "request_chars": int(item.get("request_chars") or 0),
                       "request_sha": _clip(item.get("request_sha"), 16)}
        except (KeyError, TypeError, ValueError):
            return None
        if (not _ID_RE.match(mission["id"]) or mission["kind"] not in KINDS or mission["state"] not in STATES or mission["route"] not in ROUTES
                or (mission["assistant"] and not _ASSISTANT_RE.match(mission["assistant"]))):
            return None
        return mission

    def _save(self, data):
        atomic.write_json_atomic(self.path, data)

    # ---- missions -------------------------------------------------------------------------------------------------
    def create(self, kind, wish, assistant="", request_chars=0, request_sha=""):
        if kind not in KINDS:
            raise ValueError("bad kind")
        with self._lock:
            data = self._load()
            now = float(self._clock())
            mission = {"id": "m" + os.urandom(5).hex(), "kind": kind, "wish": _clip(wish, 700), "assistant": str(assistant or ""), "route": "",
                       "state": "drafted", "created": now, "updated": now, "note": "", "answer": "", "request_chars": int(request_chars),
                       "request_sha": _clip(request_sha, 16)}
            data["missions"] = (data["missions"] + [mission])[-MAX_MISSIONS:]
            self._save(data)
            return dict(mission)

    def get(self, mission_id):
        with self._lock:
            for mission in self._load()["missions"]:
                if mission["id"] == mission_id:
                    return dict(mission)
        return None

    def update(self, mission_id, **changes):
        with self._lock:
            data = self._load()
            for mission in data["missions"]:
                if mission["id"] != mission_id:
                    continue
                for key, value in changes.items():
                    if key == "state" and value not in STATES:
                        raise ValueError("bad state")
                    if key == "route" and value not in ROUTES:
                        raise ValueError("bad route")
                    if key in ("state", "route", "assistant"):
                        mission[key] = str(value)
                    elif key == "note":
                        mission[key] = _clip(value, 300)
                    elif key == "answer":
                        mission[key] = _clip(value, MAX_ANSWER_CHARS)
                    elif key == "request_chars":
                        mission[key] = int(value)
                    elif key == "request_sha":
                        mission[key] = _clip(value, 16)
                    else:
                        raise ValueError("unknown field " + key)
                mission["updated"] = float(self._clock())
                self._save(data)
                return dict(mission)
        return None

    def missions(self):
        with self._lock:
            return [dict(m) for m in self._load()["missions"]]

    def latest(self, only_open=True):
        with self._lock:
            for mission in reversed(self._load()["missions"]):
                if not only_open or mission["state"] in OPEN_STATES:
                    return dict(mission)
        return None

    def cancel_open(self, keep=None):
        """Cancel every open mission (except the one with id `keep`). Returns how many were cancelled."""
        with self._lock:
            data = self._load()
            count = 0
            for mission in data["missions"]:
                if mission["state"] in OPEN_STATES and mission["id"] != keep:
                    mission["state"], mission["updated"] = "cancelled", float(self._clock())
                    count += 1
            if count:
                self._save(data)
            return count

    # ---- the apps the user allowed -----------------------------------------------------------------------------------
    def allow(self, package, minutes=30):
        if not valid_package(package):
            raise ValueError("bad package")
        minutes = max(1, min(int(minutes), MAX_ALLOW_MINUTES))
        with self._lock:
            data = self._load()
            expires = float(self._clock()) + minutes * 60
            data["allow"][package] = expires
            data["allow"] = dict(sorted(data["allow"].items(), key=lambda kv: kv[1])[-MAX_ALLOWED:])
            self._save(data)
            return expires

    def revoke(self, package=None):
        with self._lock:
            data = self._load()
            before = len(data["allow"])
            if package is None:
                data["allow"] = {}
            else:
                data["allow"].pop(package, None)
            if len(data["allow"]) != before:
                self._save(data)
            return before - len(data["allow"])

    def allowed_now(self):
        try:
            return frozenset(self._load()["allow"])
        except Exception:
            return frozenset()

    def allow_list(self):
        now = float(self._clock())
        with self._lock:
            return [(p, max(0, int(e - now))) for p, e in sorted(self._load()["allow"].items())]
