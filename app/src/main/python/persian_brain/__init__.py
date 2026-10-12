"""
Persian conversation brain
==========================
The deterministic Persian conversation layer that sits in front of the
application's existing pipeline (see skills/skill_system.py for the single,
defensive seam) and gives ordinary Persian input a real, state-aware reply:

    text -> normalization -> intent (GREETING | QUESTION | REQUEST | COMMAND |
            STATEMENT | TEACHING | CONTINUATION | REFERENCE | FEEDBACK | UNKNOWN)
         -> handler (memory / knowledge / Self-Builder capabilities / dialogue state)
         -> reply

It is NOT a language model and keeps no giant answer dictionary: replies are
built from what is actually stored (taught knowledge, the stored user name,
the capability registry, the dialogue state), through small closed word lists
(lexicon.py) and fixed message templates (messages.py). Anything it cannot
really handle is returned as None, which leaves the message to the
application's existing Persian NLU / reasoning / fallback exactly as before.

Importing this package has no side effects.
"""

__all__ = ["get_brain", "dynamic_skill"]


def get_brain(memory):
    """The (cached) brain of a MemorySystem. Nothing is created on disk."""
    from .brain import get_brain as _get
    return _get(memory)


def dynamic_skill(memory, text):
    """The 'skill' the SkillSystem hands to Core when the brain answers `text`
    ({"name", "response", ...}), else None. Never raises."""
    try:
        from .brain import dynamic_skill as _dynamic
        return _dynamic(memory, text)
    except Exception:
        return None
