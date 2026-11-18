"""
brain_hub.ownbrain_state - what the phone has (memory, free space) and the small file that remembers where the own brain stands
==============================================================================================================================
Two plain helpers for `ownbrain`:

* `ram_bytes()` / `device_facts()`: the phone's total memory (from `/proc/meminfo`, which Android also has) and the free space where
  the model will live. A fact that cannot be read is 0 - never a guess - and the caller then says so.
* `StateFile`: `<hub root>/own_brain/state.json`, written atomically, read strictly. It holds only plain facts (which brain, which phase,
  how many bytes, the last failure code, when the user agreed). A damaged or foreign file is set aside and the state starts empty, so a
  broken file can never make the app believe it has a brain it does not have. Nothing secret is ever stored here.
"""

import os
import shutil
import time

from . import atomic

__all__ = ["ram_bytes", "free_bytes", "device_facts", "StateFile", "PHASES", "DIR_NAME", "STATE_FILE", "default_state"]

DIR_NAME = "own_brain"
STATE_FILE = "state.json"
MAX_STATE_BYTES = 8192
PHASES = ("idle", "downloading", "installing", "ready", "failed", "paused")
_MEMINFO = "/proc/meminfo"


def ram_bytes(path=_MEMINFO):
    """Total memory of the phone in bytes, or 0 when it cannot be read."""
    try:
        with open(path, "r", encoding="ascii", errors="replace") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    value = int(parts[1])
                    unit = parts[2].lower() if len(parts) > 2 else "kb"
                    scale = {"kb": 1024, "mb": 1024 * 1024, "b": 1}.get(unit, 1024)
                    return value * scale if 0 < value < 1 << 40 else 0
    except (OSError, ValueError, IndexError):
        return 0
    return 0


def free_bytes(path, usage_fn=shutil.disk_usage):
    """Free bytes on the disk that holds `path` (its nearest existing parent), or 0 when it cannot be read."""
    probe = os.path.abspath(os.fspath(path))
    for _ in range(12):
        if os.path.exists(probe):
            break
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        usage = usage_fn(probe)
        free = getattr(usage, "free", None)
        return int(free if free is not None else usage[2])
    except Exception:
        return 0


def device_facts(path, usage_fn=shutil.disk_usage, meminfo=_MEMINFO):
    return {"ram": ram_bytes(meminfo), "free": free_bytes(path, usage_fn)}


def default_state():
    return {"v": 1, "choice": "", "phase": "idle", "consent_at": 0.0, "bytes": 0, "total": 0, "code": "", "detail": "", "updated": 0.0,
            "model_id": "", "ready_at": 0.0}


def _clean(raw):
    """A dict that has exactly the fields of `default_state` with the right types, or None."""
    base = default_state()
    if not isinstance(raw, dict) or raw.get("v") != 1 or set(raw) - set(base):
        return None
    out = dict(base)
    for key, default in base.items():
        value = raw.get(key, default)
        if isinstance(default, str):
            if not isinstance(value, str) or len(value) > 200 or any(ord(c) < 32 for c in value):
                return None
        elif isinstance(default, float):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 4e12:
                return None
            value = float(value)
        elif key == "v":
            value = 1
        else:
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 1 << 45:
                return None
        out[key] = value
    return out if out["phase"] in PHASES else None


class StateFile:
    def __init__(self, directory, clock=time.time):
        self.directory = os.path.abspath(os.fspath(directory))
        self.path = os.path.join(self.directory, STATE_FILE)
        self._clock = clock

    def load(self):
        """`(state, note)`: the saved state and '' - or a fresh one and why (`missing`, `damaged`). Never raises."""
        try:
            raw = atomic.read_json_bounded(self.path, MAX_STATE_BYTES)
        except FileNotFoundError:
            return default_state(), "missing"
        except (OSError, ValueError):
            atomic.set_aside(self.path)
            return default_state(), "damaged"
        state = _clean(raw)
        if state is None:
            atomic.set_aside(self.path)
            return default_state(), "damaged"
        return state, ""

    def save(self, state):
        """Write the state; False (and nothing changed) when it is not valid or the disk refuses. Never raises."""
        state = dict(state, updated=float(self._clock()))
        if _clean(state) is None:
            return False
        try:
            atomic.write_json_atomic(self.path, state)
            return True
        except OSError:
            return False

    def remove(self):
        try:
            if os.path.lexists(self.path):
                os.unlink(self.path)
            return True
        except OSError:
            return False
