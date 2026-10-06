"""
Reasoning - foundation request/planning representation (Prompt 834)
===================================================================
A small deterministic layer on top of the Prompt 833 NLU reasoning input
(`understanding.nlu_reasoning_input.build_reasoning_input`). It turns that
input into one bounded request/planning record that keeps five things
apart:

  goal         the intent the message states (effective intent) and where
               it came from; never a goal the input does not carry
  known        explicit slots, relations and a RESOLVED reference
  unresolved   present-but-undetermined items (unresolved/ambiguous
               reference, ambiguous relations) - never guessed
  missing      information that is absent (fixed-vocabulary codes)
  next_action  ONE possible next step as a label; it is never executed

  build_reasoning_request(reasoning_input)

Result (always the same keys, in this order):

  {"version", "status",
   "goal":   {"intent", "source", "state"},
   "known":  {"slots", "relations", "reference"},
   "unresolved": [{"code", "detail"}, ...],
   "missing": [codes],
   "next_action": {"action", "reason", "executed"}}

  status   "ambiguous" > "unresolved" > "unknown" > "missing" > "ready"
           ambiguous   reference or relations are ambiguous
           unresolved  a reference cue points at nothing available
           unknown     no goal (intent unknown) or no usable input
           missing     a goal is known but information is absent
           ready       goal known, nothing unresolved, nothing missing
  goal     intent None / source None / state "unresolved" when no goal is
           stated; source is "primary" or "inherited" (inherited only when
           the input carries an inherited intent equal to the effective one)
  unresolved codes  reference_unresolved, reference_ambiguous,
           relations_ambiguous (detail: the reason string, or the count)
  missing codes     reasoning_input_missing, reasoning_input_invalid,
           intent_unknown, slots_truncated, relations_truncated
  next_action  proceed (ready) | clarify (ambiguous) |
           request_information (everything else); `reason` is the first
           unresolved/missing code, or "goal_known"; `executed` is always
           False.

The status is recomputed from the input's explicit fields, not copied from
its own `status` string. Slots and relations are bounded at MAX_ITEMS
(a cut adds the matching *_truncated code); only JSON-safe values are kept.
Anything that is not a well-formed reasoning input gives status "unknown"
with a missing code; nothing is invented. Pure stdlib, deterministic,
never raises, never modifies its input, always returns a fresh dict. No
Memory, AEL, Core, NLU change, execution, LLM or network.
"""

import copy
import json

FOUNDATION_VERSION = 1
MAX_ITEMS = 16
MAX_TEXT_CHARS = 200

STATUS_READY = "ready"
STATUS_UNKNOWN = "unknown"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_UNRESOLVED = "unresolved"
STATUS_MISSING = "missing"

GOAL_KNOWN = "known"
GOAL_UNRESOLVED = "unresolved"
SOURCE_PRIMARY = "primary"
SOURCE_INHERITED = "inherited"

UNRESOLVED_REFERENCE_UNRESOLVED = "reference_unresolved"
UNRESOLVED_REFERENCE_AMBIGUOUS = "reference_ambiguous"
UNRESOLVED_RELATIONS_AMBIGUOUS = "relations_ambiguous"

MISSING_INPUT_MISSING = "reasoning_input_missing"
MISSING_INPUT_INVALID = "reasoning_input_invalid"
MISSING_INTENT_UNKNOWN = "intent_unknown"
MISSING_SLOTS_TRUNCATED = "slots_truncated"
MISSING_RELATIONS_TRUNCATED = "relations_truncated"

ACTION_PROCEED = "proceed"
ACTION_CLARIFY = "clarify"
ACTION_REQUEST_INFORMATION = "request_information"

REASON_GOAL_KNOWN = "goal_known"


def empty_reasoning_request(missing_code=MISSING_INPUT_MISSING):
    return {
        "version": FOUNDATION_VERSION,
        "status": STATUS_UNKNOWN,
        "goal": {"intent": None, "source": None, "state": GOAL_UNRESOLVED},
        "known": {"slots": [], "relations": [], "reference": None},
        "unresolved": [],
        "missing": [missing_code],
        "next_action": {"action": ACTION_REQUEST_INFORMATION,
                        "reason": missing_code, "executed": False},
    }


def _safe(value):
    """A detached JSON-safe copy of `value`, or raises (caller skips it)."""
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _dict(v):
    return v if isinstance(v, dict) else {}


def _items(v):
    """(bounded list of JSON-safe dict items, was_cut)."""
    if not isinstance(v, list):
        return [], False
    out = []
    for x in v:
        if isinstance(x, dict):
            try:
                out.append(_safe(x))
            except Exception:
                continue
    return out[:MAX_ITEMS], len(out) > MAX_ITEMS


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _well_formed(ri):
    if not isinstance(ri, dict):
        return False
    intent, known, unresolved = ri.get("intent"), ri.get("known"), ri.get("unresolved")
    return (isinstance(intent, dict) and isinstance(known, dict)
            and isinstance(unresolved, dict)
            and isinstance(known.get("reference"), dict))


def _reference(ref):
    """The resolved reference as known information, else None."""
    if ref.get("status") != "resolved":
        return None
    out = {"cues": [c for c in ref.get("cues", []) if isinstance(c, str)]
           if isinstance(ref.get("cues"), list) else [],
           "continuation": ref.get("continuation") if isinstance(ref.get("continuation"), str) else None,
           "referenced_turn": ref.get("referenced_turn") if _is_int(ref.get("referenced_turn")) else None,
           "referenced": None}
    r = ref.get("referenced")
    if isinstance(r, dict):
        text = r.get("text")
        intent = r.get("intent")
        out["referenced"] = {
            "turn_index": r.get("turn_index") if _is_int(r.get("turn_index")) else None,
            "intent": intent if isinstance(intent, str) else None,
            "text": text[:MAX_TEXT_CHARS] if isinstance(text, str) else None,
        }
    return out


def build_reasoning_request(reasoning_input):
    """Reasoning request/planning record for `reasoning_input` (see module
    docstring). Never raises."""
    try:
        if reasoning_input is None:
            return empty_reasoning_request(MISSING_INPUT_MISSING)
        if not _well_formed(reasoning_input):
            return empty_reasoning_request(MISSING_INPUT_INVALID)

        intent = reasoning_input["intent"]
        known = reasoning_input["known"]
        unres = reasoning_input["unresolved"]
        ref_in = known["reference"]

        slots, slots_cut = _items(known.get("slots"))
        relations, rels_cut = _items(known.get("relations"))

        effective = intent.get("effective")
        goal_known = isinstance(effective, str) and effective not in ("", "unknown")
        inherited = intent.get("inherited")
        goal = {"intent": effective if goal_known else None, "source": None,
                "state": GOAL_KNOWN if goal_known else GOAL_UNRESOLVED}
        if goal_known:
            goal["source"] = (SOURCE_INHERITED if isinstance(inherited, str)
                              and inherited == effective else SOURCE_PRIMARY)

        ref_status = unres.get("reference_status")
        ref_reason = unres.get("reference_reason")
        ref_reason = ref_reason if isinstance(ref_reason, str) else None
        amb = unres.get("ambiguous_relations")
        amb = amb if _is_int(amb) and amb > 0 else 0

        unresolved = []
        if ref_status == "unresolved":
            unresolved.append({"code": UNRESOLVED_REFERENCE_UNRESOLVED, "detail": ref_reason})
        if ref_status == "ambiguous":
            unresolved.append({"code": UNRESOLVED_REFERENCE_AMBIGUOUS, "detail": ref_reason})
        if amb:
            unresolved.append({"code": UNRESOLVED_RELATIONS_AMBIGUOUS, "detail": amb})

        missing = []
        if not goal_known:
            missing.append(MISSING_INTENT_UNKNOWN)
        if slots_cut or unres.get("slots_truncated") is True:
            missing.append(MISSING_SLOTS_TRUNCATED)
        if rels_cut or unres.get("relations_truncated") is True:
            missing.append(MISSING_RELATIONS_TRUNCATED)

        if ref_status == "ambiguous" or amb:
            status = STATUS_AMBIGUOUS
        elif ref_status == "unresolved":
            status = STATUS_UNRESOLVED
        elif not goal_known and not slots and not relations:
            status = STATUS_UNKNOWN
        elif missing:
            status = STATUS_MISSING
        else:
            status = STATUS_READY

        if status == STATUS_READY:
            action, reason = ACTION_PROCEED, REASON_GOAL_KNOWN
        elif status == STATUS_AMBIGUOUS:
            action, reason = ACTION_CLARIFY, unresolved[0]["code"]
        else:
            action = ACTION_REQUEST_INFORMATION
            reason = (unresolved[0]["code"] if unresolved else missing[0])

        return copy.deepcopy({
            "version": FOUNDATION_VERSION,
            "status": status,
            "goal": goal,
            "known": {"slots": slots, "relations": relations,
                      "reference": _reference(ref_in)},
            "unresolved": unresolved,
            "missing": missing,
            "next_action": {"action": action, "reason": reason, "executed": False},
        })
    except Exception:  # pragma: no cover - defensive: the layer is optional
        return empty_reasoning_request(MISSING_INPUT_INVALID)
