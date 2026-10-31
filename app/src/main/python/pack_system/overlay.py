"""
pack_system.overlay - how installed pack files become importable modules
========================================================================
A `PackFinder` sits FIRST in `sys.meta_path` and maps exact module names to files of installed pack versions:

* a pack's own modules (`my_feature`, `my_feature.main` ...) - so no `sys.path` entry is ever added;
* a module a pack REPLACES (`persian_brain.messages`) - Python then loads the pack's file instead of the one in the APK.

Replacement only works for modules that have not been imported yet in this process, which is why the manager asks for a
restart after installing such a pack, and why `platform_boot.prepare()` runs before the app's own modules are imported.
Pack files are never compiled to cached bytecode (the store stays exactly as installed, read-only).
"""

import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys
import threading

__all__ = ["PackFinder", "install_mapping", "uninstall", "current_mapping", "build_mapping", "finder"]

_LOCK = threading.RLock()
_FINDER = None


class _NoCacheLoader(importlib.machinery.SourceFileLoader):
    def set_data(self, path, data, *, _mode=0o666):          # never write __pycache__ next to installed pack files
        return None

    def get_code(self, fullname):                              # and never trust a cache that someone else left behind
        source_path = self.get_filename(fullname)
        data = self.get_data(source_path)
        return self.source_to_code(data, source_path)


class PackFinder(importlib.abc.MetaPathFinder):
    def __init__(self):
        self._map = {}

    def set_mapping(self, mapping):
        self._map = dict(mapping)

    def mapping(self):
        return dict(self._map)

    def find_spec(self, fullname, path=None, target=None):
        entry = self._map.get(fullname)
        if entry is None:
            return None
        file_path, is_package = entry[0], entry[1]
        if not os.path.isfile(file_path):
            return None
        loader = _NoCacheLoader(fullname, file_path)
        if is_package:
            return importlib.util.spec_from_file_location(fullname, file_path, loader=loader,
                                                          submodule_search_locations=[os.path.dirname(file_path)])
        return importlib.util.spec_from_file_location(fullname, file_path, loader=loader)


def finder():
    return _FINDER


def build_mapping(pack_id, files_dir, paths):
    """{module name: (file path, is_package, pack_id)} for the `.py` relative `paths` stored under `files_dir`."""
    out = {}
    for rel in paths:
        if not rel.endswith(".py"):
            continue
        parts = rel[:-3].split("/")
        is_package = parts[-1] == "__init__"
        if is_package:
            parts = parts[:-1]
        if not parts:
            continue
        out[".".join(parts)] = (os.path.join(files_dir, *rel.split("/")), is_package, pack_id)
    return out


def install_mapping(mapping):
    """Make the finder the first entry of `sys.meta_path` and give it `mapping` (a full replacement)."""
    global _FINDER
    with _LOCK:
        if _FINDER is None:
            _FINDER = PackFinder()
        sys.meta_path[:] = [f for f in sys.meta_path if f is not _FINDER]
        sys.meta_path.insert(0, _FINDER)
        _FINDER.set_mapping(mapping)
        return _FINDER


def current_mapping():
    return _FINDER.mapping() if _FINDER is not None else {}


def uninstall():
    """Remove the finder (tests, safe mode). Modules already imported from packs stay imported."""
    global _FINDER
    with _LOCK:
        if _FINDER is not None:
            sys.meta_path[:] = [f for f in sys.meta_path if f is not _FINDER]
            _FINDER = None
