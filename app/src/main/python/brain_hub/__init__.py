"""
brain_hub - the ONE place where the app's capabilities are listed, checked and run (Prompt 957)
================================================================================================
The hub connects what already exists - the Persian conversation brain, Self-Builder, the extension runtime, the web
reader, the local-model manager and the Android adapters - behind one honest registry and one execution entry point:

    graph.py        CapabilityGraph / CapabilityNode: every capability with an exact state
                    (active, available, registered, permission_blocked, dependency_blocked, pending_approval,
                    scaffold_only, not_implemented, policy_blocked, broken, disabled) and the exact blockers
    catalog.py      what is connected, and what is only a contract / scaffold in this build (stated truthfully)
    gaps.py         the things people ask for that cannot be done yet, each with the exact missing piece
    permissions.py  the user's app-level permissions (internet) - explicit, persisted atomically, revocable
    audit.py        a hash-chained, append-only history of hub-level decisions
    service.py      HubService: extensions (propose -> explicit approval -> verified activation -> rollback),
                    permissions, restart recovery; mixes in builtin_tools.py (web, local models, Android)
    invoker.py      build_graph(hub) from the LIVE systems and execute(hub, node, action, ...) as the single choke point
    templates.py    the prompt a user can give to any assistant to obtain an extension package for this app

Nothing here calls an external AI service, evaluates user text, runs downloaded code outside the extension sandbox,
installs an APK, runs a shell command or grants itself a permission. Nothing is written to disk until it is needed.
Imports are lazy so that `import brain_hub.graph` stays cheap.
"""

__all__ = ["HubService", "get_hub", "set_hub", "reset_hub", "default_root", "CapabilityGraph", "CapabilityNode",
           "build_graph", "execute", "build_prompt"]

_LAZY = {
    "HubService": ("service", "HubService"), "get_hub": ("service", "get_hub"), "set_hub": ("service", "set_hub"),
    "reset_hub": ("service", "reset_hub"), "default_root": ("service", "default_root"),
    "CapabilityGraph": ("graph", "CapabilityGraph"), "CapabilityNode": ("graph", "CapabilityNode"),
    "build_graph": ("invoker", "build_graph"), "execute": ("invoker", "execute"),
    "build_prompt": ("templates", "build_prompt"),
}


def __getattr__(name):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError("module %r has no attribute %r" % (__name__, name))
    import importlib
    value = getattr(importlib.import_module("." + target[0], __name__), target[1])
    globals()[name] = value
    return value
