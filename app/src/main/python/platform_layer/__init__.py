"""
Platform abstraction layer.

The AI core and application services depend on this package, never on
`os` path arithmetic or `sys.platform` checks for the concerns covered
here (persistent storage location, temp storage, logging, network
status). See adapter.py for the interface and desktop.py for the only
implementation that exists today.
"""

from .adapter import PlatformAdapter
from .desktop import DesktopPlatformAdapter
from .registry import get_platform, set_platform, reset_platform

__all__ = [
    "PlatformAdapter",
    "DesktopPlatformAdapter",
    "get_platform",
    "set_platform",
    "reset_platform",
]
