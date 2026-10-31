"""
native_bridge.facade - `api.android`: the doors, behind the pack's declared permissions
======================================================================================
`for_pack(pack_id, permissions, hub)` is what `PackAPI.android` returns. It hands out the doors a pack declared and refuses
the rest with `DoorPermissionError`:

    permission "android"       share, settings, notify, speech, voice, device
    permission "clipboard"     clipboard
    permission "screen"        screen (other apps' screens; the user must have enabled the accessibility service AND allowed the app)
    permission "unsafe_native" jvm (any allowed Android class)

Every door call is rate-limited per pack and (except quiet reads) written to the hub's hash-chained audit log - without the
clipboard text, notification text or screen contents, which never go to a log.
"""

import threading
import time

from . import doors as _doors
from .jvm import detect_jvm
from .rawjvm import RawJvm
from .result import DoorPermissionError, fail
from .screen import ScreenDoor

__all__ = ["Doors", "for_pack", "for_app", "set_jvm", "get_jvm", "set_allowed_apps_provider", "RATE_LIMITS", "reset_for_tests"]

# door -> (calls, seconds): a runaway pack cannot spam notifications or hammer the screen
RATE_LIMITS = {"clipboard": (60, 600), "share": (20, 600), "settings": (10, 600), "notify": (12, 3600), "speech": (60, 3600),
               "voice": (30, 600), "device": (120, 600), "screen": (900, 600)}
_QUIET = frozenset({("screen", "read"), ("screen", "status"), ("screen", "active_package"), ("voice", "take_result"),
                    ("clipboard", "get_text"), ("share", "visible"), ("share", "assistants_visible"), ("device", "battery"), ("device", "info")})
_DOOR_PERMISSION = {"clipboard": "clipboard", "share": "android", "settings": "android", "notify": "android", "speech": "android",
                    "voice": "android", "device": "android", "screen": "screen", "jvm": "unsafe_native"}

_LOCK = threading.RLock()
_JVM = None
_SHARED = {}                  # door name -> the one door object (the TTS engine must be created once)
_ALLOWED_PROVIDER = None
_STAMPS = {}                  # (pack_id, door) -> list of call times


def set_jvm(jvm):
    """Use this JavaBridge from now on (tests, or a different runtime). `None` goes back to automatic detection."""
    global _JVM
    with _LOCK:
        _JVM = jvm
        _SHARED.clear()


def get_jvm():
    global _JVM
    with _LOCK:
        if _JVM is None:
            _JVM = detect_jvm()
        return _JVM


def set_allowed_apps_provider(fn):
    """`fn()` -> the set of package names the user currently allowed the assistant to look into (kept by the teacher)."""
    global _ALLOWED_PROVIDER
    _ALLOWED_PROVIDER = fn


def _allowed_now():
    fn = _ALLOWED_PROVIDER
    return frozenset(fn() or ()) if fn is not None else frozenset()


def reset_for_tests():
    global _JVM, _ALLOWED_PROVIDER
    with _LOCK:
        _JVM, _ALLOWED_PROVIDER = None, None
        _SHARED.clear()
        _STAMPS.clear()


def _door_object(name, jvm):
    with _LOCK:
        door = _SHARED.get(name)
        if door is None:
            door = {"clipboard": lambda: _doors.ClipboardDoor(jvm), "share": lambda: _doors.ShareDoor(jvm),
                    "settings": lambda: _doors.SettingsDoor(jvm), "notify": lambda: _doors.NotifyDoor(jvm),
                    "speech": lambda: _doors.SpeechDoor(jvm), "voice": lambda: _doors.VoiceDoor(jvm),
                    "device": lambda: _doors.DeviceDoor(jvm), "screen": lambda: ScreenDoor(jvm, _allowed_now)}[name]()
            _SHARED[name] = door
        return door


class _Guarded:
    """A door as one pack sees it: its public methods only, each one rate-limited and audited.

    The raw door and the owner live only inside the closures below (nothing is stored as an attribute), so a pack cannot
    simply reach `api.android.share._door`; the pack scan additionally refuses any `_private` attribute behind `api`."""
    __slots__ = ("__dict__",)

    def __init__(self, owner, name, door):
        invoke = owner._invoke
        for attr in dir(door):
            if attr.startswith("_"):
                continue
            target = getattr(door, attr)
            if callable(target):
                setattr(self, attr, _wrap(invoke, name, attr, target))


def _wrap(invoke, door_name, action, target):
    def call(*args, **kwargs):
        return invoke(door_name, action, target, args, kwargs)
    call.__name__ = action
    return call


class Doors:
    def __init__(self, pack_id, permissions, hub=None, jvm=None, clock=time.time):
        self.pack_id = str(pack_id)
        self.permissions = frozenset(permissions or ())
        self._hub, self._jvm, self._clock = hub, jvm, clock

    # ---- plumbing -------------------------------------------------------------------------------------------------
    def _need(self, door):
        permission = _DOOR_PERMISSION[door]
        if permission not in self.permissions:
            raise DoorPermissionError("بستهٔ «%s» مجوز «%s» را برای این در اعلام نکرده است." % (self.pack_id, permission))

    def _jvm_now(self):
        return self._jvm if self._jvm is not None else get_jvm()

    def _door(self, name):
        self._need(name)
        return _Guarded(self, name, _door_object(name, self._jvm_now()))

    def _rate_limited(self, door):
        limit = RATE_LIMITS.get(door)
        if limit is None:
            return False
        calls, seconds = limit
        now = float(self._clock())
        with _LOCK:
            stamps = [t for t in _STAMPS.get((self.pack_id, door), ()) if now - t < seconds]
            if len(stamps) >= calls:
                _STAMPS[(self.pack_id, door)] = stamps
                return True
            stamps.append(now)
            _STAMPS[(self.pack_id, door)] = stamps
        return False

    def _invoke(self, door, action, fn, args, kwargs):
        if self._rate_limited(door):
            return fail("rate_limited", "این در در این بازه بیش از حد استفاده شد؛ کمی بعد دوباره امتحان کن.")
        result = fn(*args, **kwargs)
        if (door, action) not in _QUIET:
            self._audit(door, action, result)
        return result

    def _audit(self, door, action, result):
        hub = self._hub
        try:
            hub.audit.append("native.%s" % door, self.pack_id, {"action": action, "ok": bool(getattr(result, "ok", False)),
                                                                "code": str(getattr(result, "code", ""))})
        except Exception:
            pass

    # ---- the doors --------------------------------------------------------------------------------------------------
    @property
    def clipboard(self):
        return self._door("clipboard")

    @property
    def share(self):
        return self._door("share")

    @property
    def settings(self):
        return self._door("settings")

    @property
    def notify(self):
        return self._door("notify")

    @property
    def speech(self):
        return self._door("speech")

    @property
    def voice(self):
        return self._door("voice")

    @property
    def device(self):
        return self._door("device")

    @property
    def screen(self):
        return self._door("screen")

    @property
    def jvm(self):
        self._need("jvm")
        return RawJvm(self._jvm_now())

    # ---- facts ----------------------------------------------------------------------------------------------------------
    def platform(self):
        jvm = self._jvm_now()
        return {"platform": jvm.platform_name, "sdk": jvm.sdk_int(), "native_features": sorted(jvm.native_features())}


def for_pack(pack_id, permissions, hub=None):
    return Doors(pack_id, permissions, hub)


def for_app(hub=None, *, jvm=None, clock=time.time):
    """The doors the APP itself uses (the teacher, the chat commands): every door except the unsafe one."""
    return Doors("app", ("android", "clipboard", "screen"), hub, jvm, clock)
