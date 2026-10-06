"""
Understanding - semantic interpretation layer (Prompt 831)
==========================================================
One compact, read-only "semantic view" of an analyzed message that
combines what the existing NLU stack already says:

  intent     primary intent, effective intent (the primary one unless the
             context block already resolved another), recognized flag
  context    the relevant explicit context reference: turn index,
             continuation marker, again / refers_to_previous, repeat info,
             referenced turn, inherited intent. `present` is True only when
             at least one of those references is actually set.
  slots      the explicit Prompt 829 slots, reduced to kind / key / value
  relations  the explicit Prompt 830 relations, reduced to kind / subject /
             relation / value / slot (index into `slots`)

Shape (always the same keys, in this order):

  {"version", "intent": {"primary", "effective", "recognized"},
   "context": {"present", "turn_index", "continuation", "again",
               "refers_to_previous", "repeat_count", "repeat_of",
               "referenced_turn", "inherited_intent"},
   "slots": [...], "relations": [...],
   "bounds": {"slots_truncated", "relations_truncated", "relations_ambiguous"}}

Nothing is detected or inferred here: every value is copied from the
normalized analysis (understanding/nlu_structured_output.py), so slots and
relations keep the bounds of Prompts 829/830 (<= 16 each). An unknown or
empty message gives intent "unknown", no context reference, no slots and no
relations. Pure, deterministic, stdlib only, JSON-safe; never raises; the
analysis and its normalized output are never modified and the result is
always a fresh, detached dict. Nothing is stored and Memory/AEL/Core are
not involved.
"""

import copy

from .nlu_structured_output import normalize_nlu_analysis

SEMANTIC_VIEW_VERSION = 1

_SLOT_FIELDS = ("kind", "key", "value")
_RELATION_FIELDS = ("kind", "subject", "relation", "value", "slot")


def empty_semantic_view():
    return {
        "version": SEMANTIC_VIEW_VERSION,
        "intent": {"primary": "unknown", "effective": "unknown", "recognized": False},
        "context": {"present": False, "turn_index": None, "continuation": None,
                    "again": False, "refers_to_previous": False, "repeat_count": 0,
                    "repeat_of": None, "referenced_turn": None, "inherited_intent": None},
        "slots": [],
        "relations": [],
        "bounds": {"slots_truncated": False, "relations_truncated": False,
                   "relations_ambiguous": 0},
    }


def _dict(v):
    return v if isinstance(v, dict) else {}


def _list_of_dicts(v):
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def semantic_view_from_normalized(normalized):
    """Build the view from a `normalize_nlu_analysis` dict. Never raises."""
    out = empty_semantic_view()
    n = _dict(normalized)

    primary = n.get("intent") if isinstance(n.get("intent"), str) else "unknown"
    ctx = _dict(n.get("context"))
    ref = _dict(ctx.get("reference"))
    effective = ref.get("effective_intent")
    if not isinstance(effective, str):
        effective = primary
    out["intent"] = {"primary": primary, "effective": effective,
                     "recognized": primary != "unknown"}

    c = out["context"]
    c["turn_index"] = ctx.get("turn_index")
    c["continuation"] = ctx.get("continuation")
    c["again"] = ref.get("again") is True
    c["refers_to_previous"] = ref.get("refers_to_previous") is True
    c["repeat_count"] = ref.get("repeat_count") if isinstance(ref.get("repeat_count"), int) else 0
    c["repeat_of"] = ref.get("repeat_of")
    c["referenced_turn"] = ref.get("referenced_turn")
    c["inherited_intent"] = ref.get("inherited_intent")
    # A context reference is "relevant" only when something is explicitly set.
    c["present"] = bool(c["again"] or c["refers_to_previous"] or c["repeat_count"] > 0
                        or c["referenced_turn"] is not None
                        or c["inherited_intent"] is not None
                        or c["continuation"] is not None)

    slots = _dict(n.get("slots"))
    rels = _dict(n.get("relations"))
    out["slots"] = [{f: s.get(f) for f in _SLOT_FIELDS} for s in _list_of_dicts(slots.get("items"))]
    out["relations"] = [{f: r.get(f) for f in _RELATION_FIELDS}
                        for r in _list_of_dicts(rels.get("items"))]
    out["bounds"] = {"slots_truncated": slots.get("truncated") is True,
                     "relations_truncated": rels.get("truncated") is True,
                     "relations_ambiguous": rels.get("ambiguous")
                     if isinstance(rels.get("ambiguous"), int) else 0}
    return copy.deepcopy(out)


def build_semantic_view(analysis):
    """Semantic view of an `NLUAnalysis` (or None / anything analysis-like).
    Never raises, never modifies the analysis."""
    try:
        return semantic_view_from_normalized(normalize_nlu_analysis(analysis))
    except Exception:  # pragma: no cover - defensive: the view is optional
        return empty_semantic_view()
