"""
pack_system - how the app grows from the inside, without a new APK
===================================================================
Two kinds of "pack" can be added while the app is installed - always only after the user's explicit yes, always
versioned, hash-verified, revertible and switched off by safe mode if they ever break the start:

    code.v1   Python modules: new abilities, or replacements of ordinary (non-protected) modules of the app
    lang.v1   Persian language data: question -> answer entries with many phrasings

Parts: `intake` (find a package in pasted text / a file), `manifest` (validate), `scan` (static safety scan of pack
code), `store` (files, versions, proposals), `overlay` (the import hook that makes installed pack modules importable),
`manager` (propose / approve / activate / roll back), `boot` (start-up and safe mode), `registry` + `api` (what a pack may
register and use), `lang` (retrieval for language packs).

Importing this package imports nothing heavy; the names below load on first use.
"""

__all__ = ["PackManager", "REGISTRY", "PackError", "LangService", "boot", "limits"]

_LAZY = {"PackManager": ("manager", "PackManager"), "REGISTRY": ("registry", "REGISTRY"),
         "PackError": ("errors", "PackError"), "LangService": ("lang", "LangService")}


def __getattr__(name):
    import importlib
    if name in _LAZY:
        module, attr = _LAZY[name]
        return getattr(importlib.import_module("." + module, __name__), attr)
    if name in ("boot", "limits"):
        return importlib.import_module("." + name, __name__)
    raise AttributeError(name)
