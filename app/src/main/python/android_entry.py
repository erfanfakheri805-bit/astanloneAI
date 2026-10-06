"""
Android bridge entry point.
=============================
Called from MainActivity.java via Chaquopy. Starts the exact same
Core + HTTP server from interface/server.py, but pointed at
app-writable storage (Android's app-private files directory) instead
of the desktop-relative "data/" folder, and runs the server loop on a
background thread instead of blocking the caller.

Nothing else about the application's logic is changed.

This file is also the concrete example of the "future Android adapter"
plug-in point described in platform_layer/adapter.py: AndroidFilesDir
Adapter below is a minimal PlatformAdapter backed by the files_dir
Chaquopy hands us, installed via platform_layer.set_platform() *before*
Core is constructed. Because MemorySystem and SkillSystem now resolve
their default storage locations through platform_layer.get_platform()
(see memory/memory_system.py and skills/skill_system.py), Core no
longer needs explicit memory_db_path / skill_definitions_dir arguments
here at all - installing the adapter is enough. This is still just
architectural wiring, not a real Android implementation: no lifecycle
handling, notifications, or secure storage are implemented, per Stage
2's scope.
"""

import os
import threading

from core.core import Core
from runtime_integration.runtime_core import RuntimeCore
from core.config import UIConfig
from interface.server import make_handler
from platform_layer import PlatformAdapter, set_platform
from http.server import ThreadingHTTPServer

_ui_config = UIConfig()
HOST = _ui_config.host
PORT = _ui_config.port

_server = None
_lock = threading.Lock()


class AndroidFilesDirAdapter(PlatformAdapter):
    """Minimal PlatformAdapter backed by the app-private files_dir path
    Chaquopy passes into start(). Same directory layout the previous,
    pre-Stage-2 version of this file built by hand (files_dir/data and
    files_dir/skills_definitions), just expressed through the shared
    interface so Core/MemorySystem/SkillSystem don't need to know
    they're running on Android at all."""

    def __init__(self, files_dir):
        self._files_dir = files_dir

    def app_data_dir(self):
        return self.ensure_dir(os.path.join(self._files_dir, "data"))

    def skill_definitions_dir(self):
        return self.ensure_dir(os.path.join(self._files_dir, "skills_definitions"))

    def temp_dir(self):
        return self.ensure_dir(os.path.join(self._files_dir, "tmp"))

    def log(self, component, message, level="INFO"):
        try:
            print(f"[{level}] {component}: {message}")
        except Exception:
            pass  # logging must never crash the caller

    def network_available(self):
        return False  # unknown/unused here; the core never requires this


def start(files_dir):
    """Idempotent: safe to call every time the Activity is (re)created."""
    global _server
    with _lock:
        if _server is not None:
            return f"http://{HOST}:{PORT}"

        set_platform(AndroidFilesDirAdapter(files_dir))

        core = RuntimeCore()
        handler_cls = make_handler(core)
        _server = ThreadingHTTPServer((HOST, PORT), handler_cls)

        thread = threading.Thread(target=_server.serve_forever, daemon=True)
        thread.start()

        return f"http://{HOST}:{PORT}"
