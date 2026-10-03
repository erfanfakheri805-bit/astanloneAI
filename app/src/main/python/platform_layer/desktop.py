"""
Desktop / server PlatformAdapter.

Backward-compatible by construction: app_data_dir() and
skill_definitions_dir() resolve to the exact same directories that
memory/memory_system.py and skills/skill_system.py used to compute
inline (via os.path.dirname(__file__) arithmetic) before Stage 2 -
python/data and python/skills/definitions respectively. Existing
installations keep reading and writing the same SQLite database and
skill files with no migration step.

Override the data root with the STANDALONE_AI_DATA_DIR environment
variable, or by passing data_dir= explicitly (used by the test suite to
get a fully isolated, temp-directory-backed adapter).
"""

import os
import sys
import tempfile

from .adapter import PlatformAdapter

# python/ - two levels up from platform_layer/desktop.py
_PYTHON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DATA_DIR = os.path.join(_PYTHON_ROOT, "data")
_DEFAULT_SKILLS_DIR = os.path.join(_PYTHON_ROOT, "skills", "definitions")


class DesktopPlatformAdapter(PlatformAdapter):
    def __init__(self, data_dir=None, skills_dir=None):
        self._data_dir = (
            data_dir
            or os.environ.get("STANDALONE_AI_DATA_DIR")
            or _DEFAULT_DATA_DIR
        )
        self._skills_dir = (
            skills_dir
            or os.environ.get("STANDALONE_AI_SKILLS_DIR")
            or _DEFAULT_SKILLS_DIR
        )

    def app_data_dir(self):
        self.ensure_dir(self._data_dir)
        return self._data_dir

    def skill_definitions_dir(self):
        self.ensure_dir(self._skills_dir)
        return self._skills_dir

    def temp_dir(self):
        path = os.path.join(tempfile.gettempdir(), "standalone_ai")
        self.ensure_dir(path)
        return path

    def log(self, component, message, level="INFO"):
        try:
            sys.stderr.write(f"[{level}] {component}: {message}\n")
        except Exception:
            pass  # logging must never crash the caller
