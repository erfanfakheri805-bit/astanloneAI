"""
Platform Adapter
================
Defines the boundary between the AI core / application services and
whatever operating system or runtime they happen to be running under
(desktop/server Python today, Android via Chaquopy in a future
packaging stage).

Nothing in core/, memory/, knowledge/, concepts/, learning/, reasoning/,
skills/, capabilities/, self_upgrade/, ael/, code_intelligence/, or
understanding/ should compute filesystem paths from __file__, assume a
desktop directory layout, or check sys.platform directly. They should
ask a PlatformAdapter (via platform_layer.get_platform()) instead.

This module defines the *interface* only. platform_layer/desktop.py is
the one implementation that exists today. A future Android packaging
stage can add platform_layer/android.py implementing the same
interface - backed by Android's app-private storage, lifecycle
callbacks, notifications, etc. - without any other module changing.
See android_entry.py for the entry point where such an adapter would
be installed via set_platform().
"""

import os
from abc import ABC, abstractmethod


class PlatformAdapter(ABC):
    """Abstract boundary for everything that differs across desktop,
    server, and (future) Android runtimes."""

    @abstractmethod
    def app_data_dir(self):
        """Directory for persistent application data (the SQLite
        database, etc). Must exist (be created if missing) by the time
        this returns. Must survive application restarts."""

    @abstractmethod
    def skill_definitions_dir(self):
        """Directory where learned skill definitions (JSON files) are
        stored. Persistent, same durability requirement as
        app_data_dir(). Kept as its own method (rather than folded into
        app_data_dir()) because on desktop it historically lives next to
        the source tree, not under the data root - see desktop.py."""

    @abstractmethod
    def temp_dir(self):
        """Directory for scratch/temporary files. May be cleared between
        runs; nothing durable should be kept here."""

    @abstractmethod
    def log(self, component, message, level="INFO"):
        """Best-effort diagnostic logging hook. Must never raise -
        a logging failure must never crash the caller."""

    def network_available(self):
        """Whether the platform currently reports network connectivity.
        The AI core must never require this to be True for anything -
        it exists only so a future, explicitly opt-in feature could
        check before attempting something network-related. No part of
        this application currently uses it for that purpose."""
        return False

    def ensure_dir(self, path):
        """Cross-platform directory creation shared by adapters. An
        adapter may override this if its runtime needs something else
        (e.g. a content-provider-backed location on Android)."""
        os.makedirs(path, exist_ok=True)
        return path
