"""
Process-wide PlatformAdapter registry.

Application code asks get_platform() for platform services instead of
importing a concrete adapter directly. That keeps core/application code
decoupled from *which* platform is active.

A future Android entry point installs its adapter once, early in
startup, via set_platform(AndroidPlatformAdapter(...)) - see the
plug-in point already prepared in android_entry.py. Desktop code
(interface/server.py's run()) never needs to call this at all;
DesktopPlatformAdapter is the default.
"""

import threading

from .desktop import DesktopPlatformAdapter

_lock = threading.Lock()
_adapter = None


def get_platform():
    global _adapter
    with _lock:
        if _adapter is None:
            _adapter = DesktopPlatformAdapter()
        return _adapter


def set_platform(adapter):
    """Install a different PlatformAdapter. Affects only code that
    calls get_platform() *after* this - Core's subsystems resolve their
    default paths at construction time, so call this before creating
    Core if you want it to take effect."""
    global _adapter
    with _lock:
        _adapter = adapter


def reset_platform():
    """Restores the default DesktopPlatformAdapter. Mainly for tests
    that call set_platform() and need to clean up afterwards."""
    global _adapter
    with _lock:
        _adapter = None
