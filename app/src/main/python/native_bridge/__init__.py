"""
native_bridge - the doors from the app's Python out to the phone (and, with the user's permission, to other apps)
================================================================================================================
    jvm       JavaBridge (NullJava / ChaquopyJava): the one place where Python touches Java
    result    DoorResult - every door answers with an exact code, never an exception, never a pretence
    doors     clipboard, share/open app/open url, settings pages, notifications, speech, voice input, battery
    screen    the accessibility door: read / type into / click in OTHER apps (user-enabled, per-app allow-list, deny-list)
    rawjvm    the unsafe door for packs that declared `unsafe_native` (any allowed Android class)
    facade    `for_pack` / `for_app`: permission checks, rate limits, audit

Nothing here changes the app by itself: a door only does what its caller asks, and the callers (chat commands, packs) are
gated by the user's confirmation.
"""

from .result import DoorPermissionError, DoorResult

__all__ = ["DoorResult", "DoorPermissionError", "jvm", "doors", "screen", "rawjvm", "facade", "result"]
