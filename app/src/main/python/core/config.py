"""
Configuration
=============
Three small, deliberately separate configuration namespaces instead of
one grab-bag object, so it is always obvious which layer a setting
belongs to:

    CoreConfig     - facts about the AI itself. Never platform- or
                     UI-dependent (today: just the app version label).

    PlatformConfig - where things live and what the runtime can do
                     (paths, network availability). Backed by
                     platform_layer's active PlatformAdapter - this is
                     the ONE place that turns "which platform are we
                     on" into concrete values the rest of the app uses.

    UIConfig       - settings specific to the HTTP presentation layer
                     (host, port). Only interface/server.py and
                     android_entry.py should ever read this.

This is not a general-purpose configuration framework - just three
small, explicit dataclasses, kept deliberately simple.
"""

import os
from dataclasses import dataclass

from platform_layer import get_platform, PlatformAdapter


@dataclass(frozen=True)
class CoreConfig:
    app_version: str = "0.2.0-foundation"


@dataclass(frozen=True)
class PlatformConfig:
    data_dir: str
    skills_dir: str
    temp_dir: str
    network_available: bool

    @classmethod
    def from_adapter(cls, adapter: "PlatformAdapter" = None):
        adapter = adapter or get_platform()
        return cls(
            data_dir=adapter.app_data_dir(),
            skills_dir=adapter.skill_definitions_dir(),
            temp_dir=adapter.temp_dir(),
            network_available=adapter.network_available(),
        )


@dataclass(frozen=True)
class UIConfig:
    host: str = "127.0.0.1"
    port: int = 8420


def default_memory_db_path(platform_config: PlatformConfig = None):
    """The single place that turns a data directory into the memory
    database's file path - used by memory_system.py's default and by
    android_entry.py, so both agree on the same convention."""
    pc = platform_config or PlatformConfig.from_adapter()
    return os.path.join(pc.data_dir, "memory.db")
