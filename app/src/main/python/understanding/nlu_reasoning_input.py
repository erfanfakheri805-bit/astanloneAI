"""
Understanding - NLU -> reasoning bridge (Prompt 833)
====================================================
A small deterministic bridge from the existing NLU layers (the Prompt 831
semantic view and the Prompt 832 meaning bridge) into one compact,
read-only, reasoning-ready request representation.

  build_reasoning_input(subject, context=None)

`subject` is an `NLUAnalysis`, a semantic view dict or a normalized dict.
`context` is an optional `NLUConversationContext` (only read, via the
Prompt 832 bridge).

Result (always the same keys, in this order):

  {"version", "status",
   "intent":  {"primary", "effective", "inherited", "recognized"},
   "known":   {"slots": [...], "relations": [...], "reference": {...}},
   "unresolved": {"reference_status", "reference_reason",
                  "ambiguous_relations", "slots_truncated",
                  "relations_truncated"},
   "missing": [codes]}

  status   "unknown"     intent unknown and nothing explicit is known
           "ready"       something is known and nothing is unresolved
           "unresolved"  a reference cue points at nothing available
           "ambiguous"   a reference or a relation is ambiguous
           (ambiguous wins over unresolved, which wins over ready/unknown)
  known      only what the message / context explicitly state, copied from
             the existing layers (slots and relations keep their <= 16
             bounds). `reference` is {"status", "cues", "continuation",
             "referenced_turn", "referenced"}; the turn and inherited
             intent are kept only when the bridge status is "resolved".
  unresolved what could NOT be established; never filled in here.
             `reference_status` is None, "unresolved" or "ambiguous".
  missing    fixed-vocabulary codes, in fixed order, from:
             intent_unknown, reference_unresolved, reference_ambiguous,
             relations_ambiguous, slots_truncated, relations_truncated

Nothing is detected or invented: no goals, entities or missing slot values.
Bounded, JSON-safe, deterministic, never raises, never modifies the
analysis, view or context, and always returns a fresh dict. Pure stdlib; no
Memory, AEL, Core, storage, LLM or network.
"""

import copy

from .nlu_meaning_bridge import (
    resolve_references, STATUS_NONE, STATUS_UNRESOLVED, STATUS_AMBIGUOUS,
    _as_view,
)

REASONING_INPUT_VERSION = 1

STATUS_UNKNOWN = "unknown"
STATUS_READY = "ready"

MISSING_INTENT_UNKNOWN = "intent_unknown"
MISSING_REFERENCE_UNRESOLVED = "reference_unresolved"
MISSING_REFERENCE_AMBIGUOUS = "reference_ambiguous"
MISSING_RELATIONS_AMBIGUOUS = "relations_ambiguous"
MISSING_SLOTS_TRUNCATED = "slots_truncated"
MISSING_RELATIONS_TRUNCATED = "relations_truncated"


def empty_reasoning_input():
    return {
        "version": REASONING_INPUT_VERSION,
        "status": STATUS_UNKNOWN,
        "intent": {"primary": "unknown", "effective": "unknown",
                   "inherited": None, "recognized": False},
        "known": {"slots": [], "relations": [],
                  "reference": {"status": STATUS_NONE, "cues": [], "continuation": None,
                                "referenced_turn": None, "referenced": None}},
        "unresolved": {"reference_status": None, "reference_reason": None,
                       "ambiguous_relations": 0, "slots_truncated": False,
                       "relations_truncated": False},
        "missing": [MISSING_INTENT_UNKNOWN],
    }


def _dict(v):
    return v if isinstance(v, dict) else {}


def _dicts(v):
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def build_reasoning_input(subject, context=None):
    """Reasoning-ready representation of `subject` (see module docstring)."""
    try:
        view = _as_view(subject)
        res = resolve_references(view, context)
        bounds = _dict(view.get("bounds"))
        slots = _dicts(view.get("slots"))
        relations = _dicts(view.get("relations"))

        primary = res["primary_intent"]
        effective = res["effective_intent"]
        inherited = res["inherited_intent"]
        r_status, r_reason = res["status"], res["reason"]
        amb_rel = bounds.get("relations_ambiguous")
        amb_rel = amb_rel if isinstance(amb_rel, int) and not isinstance(amb_rel, bool) and amb_rel > 0 else 0
        slots_trunc = bounds.get("slots_truncated") is True
        rels_trunc = bounds.get("relations_truncated") is True

        missing = []
        if effective == "unknown":
            missing.append(MISSING_INTENT_UNKNOWN)
        if r_status == STATUS_UNRESOLVED:
            missing.append(MISSING_REFERENCE_UNRESOLVED)
        if r_status == STATUS_AMBIGUOUS:
            missing.append(MISSING_REFERENCE_AMBIGUOUS)
        if amb_rel:
            missing.append(MISSING_RELATIONS_AMBIGUOUS)
        if slots_trunc:
            missing.append(MISSING_SLOTS_TRUNCATED)
        if rels_trunc:
            missing.append(MISSING_RELATIONS_TRUNCATED)

        if r_status == STATUS_AMBIGUOUS or amb_rel:
            status = STATUS_AMBIGUOUS
        elif r_status == STATUS_UNRESOLVED:
            status = STATUS_UNRESOLVED
        elif effective == "unknown" and not slots and not relations:
            status = STATUS_UNKNOWN
        else:
            status = STATUS_READY

        out = {
            "version": REASONING_INPUT_VERSION,
            "status": status,
            "intent": {"primary": primary, "effective": effective,
                       "inherited": inherited, "recognized": primary != "unknown"},
            "known": {
                "slots": slots,
                "relations": relations,
                "reference": {"status": r_status, "cues": res["cues"],
                              "continuation": res["continuation"],
                              "referenced_turn": res["referenced_turn"],
                              "referenced": res["referenced"]},
            },
            "unresolved": {
                "reference_status": r_status if r_status in (STATUS_UNRESOLVED, STATUS_AMBIGUOUS) else None,
                "reference_reason": r_reason,
                "ambiguous_relations": amb_rel,
                "slots_truncated": slots_trunc,
                "relations_truncated": rels_trunc,
            },
            "missing": missing,
        }
        return copy.deepcopy(out)
    except Exception:  # pragma: no cover - defensive: the bridge is optional
        return empty_reasoning_input()
