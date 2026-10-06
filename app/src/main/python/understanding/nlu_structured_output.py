"""
Understanding - normalized structured NLU output (Prompt 828)
=============================================================
`NLUAnalysis` carries the primary result plus a free-form `structure`
dict whose blocks exist only when an annotator had something to say.
That is convenient for the pipeline but awkward for consumers
(Reasoning, Memory, AEL): every read needs `.get()` chains and a block
may be missing, or - with a custom registry - carry unexpected fields.

`normalize_nlu_analysis(analysis)` turns an analysis into ONE plain
dict with a fixed shape (`SCHEMA_VERSION`):

  * the same keys always exist, in the same order;
  * every built-in block (question, request, negation, correction,
    context) is present with `"present": False` and safe defaults when
    the annotator did not fire;
  * values are coerced to their documented type (str|None, bool, int|None,
    list of str) - a malformed value becomes the safe default, never an
    exception;
  * unknown blocks added by custom components are kept, untouched except
    for a deep copy, under `"extras"` (sorted by name).

Prompt 829 appends one more key, `"slots"`: the simple explicit values
(names, quoted text, key/value forms, plain numbers) found in the
message, extracted by `understanding/nlu_slots.py` as
`{"version", "items", "count", "truncated"}`. It is additive - every
Prompt 828 key keeps its meaning and position and `schema_version` stays 1.

Prompt 830 appends one more key after it, `"relations"`: the relationships
the message states explicitly between those slots (name ownership,
key/value assignment, request target, quoted-text target), extracted by
`understanding/nlu_relations.py` as `{"version", "items", "count",
"truncated", "ambiguous"}`. Same rules: additive, nothing inferred.

It only re-shapes what the analysis already says: no new intent
detection, the primary intent is copied verbatim, nothing is inferred,
and the input is never modified. Pure, deterministic, stdlib only; no
Memory, AEL, network or I/O. Output is JSON-serializable and detached
from the analysis (mutating it cannot affect the analysis).
"""

import copy

from .nlu_slots import extract_slots_from_analysis
from .nlu_relations import extract_relations_from_analysis

SCHEMA_VERSION = 1

# Fixed defaults for each built-in block. Insertion order is the output order.
_BLOCK_DEFAULTS = {
    "question": {"type": None, "marker": None, "has_question_mark": False, "topic": None},
    "request": {"form": None, "marker": None, "action": None, "argument": None,
                "prohibition": False},
    "negation": {"markers": [], "kinds": [], "count": 0, "folded_into_intent": False},
    "correction": {"kind": None, "marker": None, "explicit": False,
                   "corrected_text": None, "refers_to": None},
    "context": {"turn_index": None, "previous_intent": None, "previous_text": None,
                "same_intent_as_previous": False, "is_repeat": False,
                "follows_question": False, "continuation": None,
                "reference": {"repeat_count": 0, "repeat_of": None, "again": False,
                              "refers_to_previous": False, "referenced_turn": None,
                              "inherited_intent": None, "effective_intent": None}},
}
BUILTIN_BLOCKS = tuple(_BLOCK_DEFAULTS)

_REFERS_TO_DEFAULTS = {"turn_index": None, "intent": None, "normalized_text": None}


# --- coercion helpers (never raise) -----------------------------------

def _str_or_none(v):
    return v if isinstance(v, str) else None


def _bool(v):
    return v is True


def _int_or_none(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def _str_list(v):
    if not isinstance(v, (list, tuple)):
        return []
    return [x for x in v if isinstance(x, str)]


def _float(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _dict(v):
    return v if isinstance(v, dict) else {}


# --- per-block normalizers --------------------------------------------

def _refers_to(v):
    if not isinstance(v, dict):
        return None
    return {"turn_index": _int_or_none(v.get("turn_index")),
            "intent": _str_or_none(v.get("intent")),
            "normalized_text": _str_or_none(v.get("normalized_text"))}


def _reference(v, primary_intent):
    v = _dict(v)
    effective = _str_or_none(v.get("effective_intent"))
    return {
        "repeat_count": _int(v.get("repeat_count")),
        "repeat_of": _int_or_none(v.get("repeat_of")),
        "again": _bool(v.get("again")),
        "refers_to_previous": _bool(v.get("refers_to_previous")),
        "referenced_turn": _int_or_none(v.get("referenced_turn")),
        "inherited_intent": _str_or_none(v.get("inherited_intent")),
        # With no context information the effective intent IS the primary one.
        "effective_intent": effective if effective is not None else primary_intent,
    }


def _normalize_block(name, raw, primary_intent):
    present = isinstance(raw, dict)
    b = _dict(raw)
    if name == "question":
        body = {"type": _str_or_none(b.get("type")), "marker": _str_or_none(b.get("marker")),
                "has_question_mark": _bool(b.get("has_question_mark")),
                "topic": _str_or_none(b.get("topic"))}
    elif name == "request":
        body = {"form": _str_or_none(b.get("form")), "marker": _str_or_none(b.get("marker")),
                "action": _str_or_none(b.get("action")),
                "argument": _str_or_none(b.get("argument")),
                "prohibition": _bool(b.get("prohibition"))}
    elif name == "negation":
        markers = _str_list(b.get("markers"))
        body = {"markers": markers, "kinds": sorted(set(_str_list(b.get("kinds")))),
                "count": _int(b.get("count")),
                "folded_into_intent": _bool(b.get("folded_into_intent"))}
    elif name == "correction":
        body = {"kind": _str_or_none(b.get("kind")), "marker": _str_or_none(b.get("marker")),
                "explicit": _bool(b.get("explicit")),
                "corrected_text": _str_or_none(b.get("corrected_text")),
                "refers_to": _refers_to(b.get("refers_to"))}
    else:  # context
        body = {"turn_index": _int_or_none(b.get("turn_index")),
                "previous_intent": _str_or_none(b.get("previous_intent")),
                "previous_text": _str_or_none(b.get("previous_text")),
                "same_intent_as_previous": _bool(b.get("same_intent_as_previous")),
                "is_repeat": _bool(b.get("is_repeat")),
                "follows_question": _bool(b.get("follows_question")),
                "continuation": _str_or_none(b.get("continuation")),
                "reference": _reference(b.get("reference"), primary_intent)}
    out = {"present": present}
    out.update(body)
    return out


def _facts(v):
    out = []
    if isinstance(v, (list, tuple)):
        for f in v:
            if isinstance(f, dict):
                out.append({"subject": _str_or_none(f.get("subject")),
                            "predicate": _str_or_none(f.get("predicate")),
                            "value": _str_or_none(f.get("value"))})
    return out


def _entities(v):
    if not isinstance(v, dict):
        return {}
    return {k: copy.deepcopy(v[k]) for k in sorted(v, key=str) if isinstance(k, str)}


def _errors(v):
    out = []
    if isinstance(v, (list, tuple)):
        for e in v:
            if isinstance(e, (list, tuple)) and len(e) == 2:
                out.append([str(e[0]), str(e[1])])
    return out


# --- public entry point -----------------------------------------------

def normalize_nlu_analysis(analysis):
    """Normalize an `NLUAnalysis` (or None / anything analysis-like) into
    the fixed-shape dict described in the module docstring. Never raises
    for a malformed or missing analysis; never modifies it."""
    result = getattr(analysis, "result", None)
    intent = _str_or_none(getattr(result, "intent", None)) or "unknown"
    structure = _dict(getattr(analysis, "structure", None))

    out = {
        "schema_version": SCHEMA_VERSION,
        "intent": intent,
        "recognized": intent != "unknown",
        "confidence": _float(getattr(result, "confidence", None)),
        "matched_rule": _str_or_none(getattr(result, "matched_rule", None)),
        "normalized_text": _str_or_none(getattr(result, "normalized_text", None)) or "",
        "entities": _entities(getattr(result, "entities", None)),
        "facts": _facts(getattr(result, "facts", None)),
        "decided_by": _str_or_none(getattr(analysis, "component", None)),
    }
    for name in BUILTIN_BLOCKS:
        out[name] = _normalize_block(name, structure.get(name), intent)
    out["extras"] = {k: copy.deepcopy(structure[k]) for k in sorted(structure, key=str)
                     if isinstance(k, str) and k not in _BLOCK_DEFAULTS
                     and isinstance(structure[k], dict)}
    out["errors"] = _errors(getattr(analysis, "errors", None))
    # Prompt 829: additive, appended last so the Prompt 828 keys keep their
    # exact order. Explicit values only (see understanding/nlu_slots.py).
    slots = extract_slots_from_analysis(analysis)
    out["slots"] = slots
    # Prompt 830: additive, appended after "slots". Only relationships the
    # text states explicitly (see understanding/nlu_relations.py).
    out["relations"] = extract_relations_from_analysis(analysis, slots)
    return out
