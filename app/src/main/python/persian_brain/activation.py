"""
Persian conversation brain - where it is switched on
====================================================
The brain reaches the conversation through ONE seam: the application's
SkillSystem (skills/skill_system.py asks `persian_brain.dynamic_skill(memory, text)`
through its defensive `_dynamic_skill` method before it looks at the stored keyword skills - the very first step of
Core._handle_conversation). Which messages it may answer depends on the
runtime it is running in:

  scope "full"          the application runtime: social talk (greetings,
                        thanks, goodbyes), taught knowledge and personal
                        memory questions, statements, feedback, plus
                        everything of scope "capabilities". Selected when the
                        installed platform adapter is not the plain desktop
                        one - i.e. inside the Android app, where
                        android_entry.start() installs its own adapter before
                        Core is constructed - or when the environment
                        variable STANDALONE_AI_PERSIAN_BRAIN is 1/true/on, or
                        explicitly through enable(memory).

  scope "capabilities"  everything else (a plain Core / the library on a
                        desktop): only the capability domain - requests to
                        build a capability, questions/commands about the
                        capability registry, calling a built capability and
                        the follow-ups of those. A plain Core therefore keeps
                        answering ordinary Persian small talk exactly as it
                        always did (the existing frozen tests pin that).

STANDALONE_AI_PERSIAN_BRAIN=0/false/off (or disable(memory)) turns the brain
off completely for that process / MemorySystem.
"""

import os
import threading
import weakref

ENV_VAR = "STANDALONE_AI_PERSIAN_BRAIN"
SCOPE_FULL = "full"
SCOPE_CAPABILITIES = "capabilities"
SCOPE_OFF = "off"

_LOCK = threading.Lock()
_OVERRIDES = weakref.WeakKeyDictionary()  # MemorySystem -> scope


def enable(memory, scope=SCOPE_FULL):
    """Force `scope` for this MemorySystem (embedding code, tests)."""
    if scope not in (SCOPE_FULL, SCOPE_CAPABILITIES, SCOPE_OFF):
        raise ValueError(f"unknown scope {scope!r}")
    with _LOCK:
        _OVERRIDES[memory] = scope


def disable(memory):
    enable(memory, SCOPE_OFF)


def reset(memory):
    """Back to the automatic choice."""
    with _LOCK:
        _OVERRIDES.pop(memory, None)


def _application_runtime():
    """True when the installed platform adapter is not the plain desktop one."""
    try:
        from platform_layer import DesktopPlatformAdapter, get_platform
        return not isinstance(get_platform(), DesktopPlatformAdapter)
    except Exception:
        return False


def scope_for(memory):
    """The scope the brain may act in for this MemorySystem."""
    with _LOCK:
        forced = _OVERRIDES.get(memory)
    if forced is not None:
        return forced
    env = (os.environ.get(ENV_VAR) or "").strip().lower()
    if env in ("1", "true", "yes", "on", "full"):
        return SCOPE_FULL
    if env in ("0", "false", "no", "off"):
        return SCOPE_OFF
    return SCOPE_FULL if _application_runtime() else SCOPE_CAPABILITIES


__all__ = ["enable", "disable", "reset", "scope_for", "ENV_VAR", "SCOPE_FULL", "SCOPE_CAPABILITIES", "SCOPE_OFF"]
