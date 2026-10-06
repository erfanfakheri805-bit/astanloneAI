"""
Reasoning - deterministic reasoning plan (Prompt 835)
=====================================================
A small planning layer on top of the Prompt 834 reasoning request
(`reasoning.reasoning_foundation.build_reasoning_request`). It turns the
request into an ordered list of explicit, read-only steps with stable ids.
A step is a description of what to consider or what is still needed; it
names no tool, capability or action to run, and nothing is executed.

  build_reasoning_plan(reasoning_request)

Result (always the same keys, in this order):

  {"version", "status", "request_status", "goal",
   "steps": [...], "step_count", "truncated", "executed"}

  status   "ready"               goal known, nothing unresolved or missing
           "needs_clarification" an ambiguity is present
           "needs_information"   everything else (unresolved reference,
                                 missing information, unknown goal, no or
                                 malformed request)
  goal     the request's goal block, copied
  step     {"id", "kind", "ref", "detail", "depends_on", "executed"}
           ids are stable: kind, or "kind.code" for clarify / need steps
           (unique within a plan; the same request always gives the same ids)
           kinds: consider_reference, consider_slots, consider_relations,
                  address_goal, clarify, need
           `ref` is the intent / code the step is about, `detail` a value
           copied from the request (count, turn index, reason), `executed`
           is always False, `depends_on` lists earlier step ids.

Ready plan (in order): consider_reference (only if the request holds a
resolved reference), consider_slots and consider_relations (only if it
holds any), then address_goal (the goal's intent), which depends on every
earlier step. A plan that is not ready contains ONLY clarify / need steps -
one per unresolved item (clarify for an ambiguity, need for an unresolved
reference), then one need step per missing code - and never an
address_goal step: insufficient information is asked for, not guessed.

The status is recomputed from the request's own goal / unresolved / missing
fields, not copied from its `status`. A request that is not a well-formed
Prompt 834 record, or that carries a code outside the Prompt 834
vocabulary, gives "needs_information" with a need step (nothing is
trusted). Steps are bounded at MAX_STEPS. Pure stdlib, deterministic,
never raises, never modifies the request, always returns a fresh dict. No
Memory, AEL, Core, NLU change, execution, LLM or network.
"""

import copy

from .reasoning_foundation import (
    UNRESOLVED_REFERENCE_UNRESOLVED, UNRESOLVED_REFERENCE_AMBIGUOUS,
    UNRESOLVED_RELATIONS_AMBIGUOUS, MISSING_INPUT_MISSING, MISSING_INPUT_INVALID,
    MISSING_INTENT_UNKNOWN, MISSING_SLOTS_TRUNCATED, MISSING_RELATIONS_TRUNCATED,
)

PLAN_VERSION = 1
MAX_STEPS = 8

STATUS_READY = "ready"
STATUS_NEEDS_CLARIFICATION = "needs_clarification"
STATUS_NEEDS_INFORMATION = "needs_information"

KIND_CONSIDER_REFERENCE = "consider_reference"
KIND_CONSIDER_SLOTS = "consider_slots"
KIND_CONSIDER_RELATIONS = "consider_relations"
KIND_ADDRESS_GOAL = "address_goal"
KIND_CLARIFY = "clarify"
KIND_NEED = "need"

MISSING_REQUEST_MISSING = "reasoning_request_missing"
MISSING_REQUEST_INVALID = "reasoning_request_invalid"

_AMBIGUITY_CODES = (UNRESOLVED_REFERENCE_AMBIGUOUS, UNRESOLVED_RELATIONS_AMBIGUOUS)
_UNRESOLVED_CODES = (UNRESOLVED_REFERENCE_UNRESOLVED,) + _AMBIGUITY_CODES
_MISSING_CODES = (MISSING_INPUT_MISSING, MISSING_INPUT_INVALID, MISSING_INTENT_UNKNOWN,
                  MISSING_SLOTS_TRUNCATED, MISSING_RELATIONS_TRUNCATED)
_EMPTY_GOAL = {"intent": None, "source": None, "state": "unresolved"}


def _step(kind, ref=None, detail=None, depends_on=()):
    sid = kind if kind not in (KIND_CLARIFY, KIND_NEED) else f"{kind}.{ref}"
    return {"id": sid, "kind": kind, "ref": ref, "detail": detail,
            "depends_on": list(depends_on), "executed": False}


def _plan(status, request_status, goal, steps):
    truncated = len(steps) > MAX_STEPS
    steps = steps[:MAX_STEPS]
    return {"version": PLAN_VERSION, "status": status, "request_status": request_status,
            "goal": goal, "steps": steps, "step_count": len(steps),
            "truncated": truncated, "executed": False}


def empty_reasoning_plan(code=MISSING_REQUEST_MISSING):
    return _plan(STATUS_NEEDS_INFORMATION, None, dict(_EMPTY_GOAL), [_step(KIND_NEED, code)])


def _scalar(v):
    return v if v is None or isinstance(v, (str, int)) and not isinstance(v, bool) else None


def _parse(req):
    """(goal, slots_n, relations_n, reference, unresolved, missing) or None."""
    if not isinstance(req, dict):
        return None
    goal, known = req.get("goal"), req.get("known")
    unresolved, missing = req.get("unresolved"), req.get("missing")
    if not (isinstance(goal, dict) and isinstance(known, dict)
            and isinstance(unresolved, list) and isinstance(missing, list)
            and isinstance(known.get("slots"), list) and isinstance(known.get("relations"), list)
            and (known.get("reference") is None or isinstance(known.get("reference"), dict))):
        return None
    intent, source, state = goal.get("intent"), goal.get("source"), goal.get("state")
    if not ((intent is None or isinstance(intent, str)) and (source is None or isinstance(source, str))
            and isinstance(state, str)):
        return None
    items = []
    for u in unresolved:
        if not isinstance(u, dict) or u.get("code") not in _UNRESOLVED_CODES:
            return None
        items.append((u["code"], _scalar(u.get("detail"))))
    if any(m not in _MISSING_CODES for m in missing):
        return None
    return ({"intent": intent, "source": source, "state": state},
            len(known["slots"]), len(known["relations"]), known.get("reference"),
            items, list(missing))


def build_reasoning_plan(reasoning_request):
    """Deterministic read-only plan for `reasoning_request` (see module
    docstring). Never raises."""
    try:
        if reasoning_request is None:
            return empty_reasoning_plan(MISSING_REQUEST_MISSING)
        parsed = _parse(reasoning_request)
        if parsed is None:
            return empty_reasoning_plan(MISSING_REQUEST_INVALID)
        goal, n_slots, n_rels, ref, unresolved, missing = parsed
        raw = reasoning_request.get("status")
        request_status = raw if isinstance(raw, str) else None

        goal_known = goal["state"] == "known" and isinstance(goal["intent"], str) \
            and goal["intent"] not in ("", "unknown")
        if not goal_known and MISSING_INTENT_UNKNOWN not in missing:
            missing = [MISSING_INTENT_UNKNOWN] + missing   # a goal that is not known is missing

        if unresolved or missing:
            steps = []
            for code, detail in unresolved:
                kind = KIND_CLARIFY if code in _AMBIGUITY_CODES else KIND_NEED
                steps.append(_step(kind, code, detail))
            for code in missing:
                steps.append(_step(KIND_NEED, code))
            status = (STATUS_NEEDS_CLARIFICATION if any(c in _AMBIGUITY_CODES for c, _d in unresolved)
                      else STATUS_NEEDS_INFORMATION)
            return copy.deepcopy(_plan(status, request_status, goal, steps))

        steps = []
        if ref is not None:
            turn = ref.get("referenced_turn")
            steps.append(_step(KIND_CONSIDER_REFERENCE, "reference",
                               turn if isinstance(turn, int) and not isinstance(turn, bool) else None))
        if n_slots:
            steps.append(_step(KIND_CONSIDER_SLOTS, "slots", n_slots))
        if n_rels:
            steps.append(_step(KIND_CONSIDER_RELATIONS, "relations", n_rels))
        steps.append(_step(KIND_ADDRESS_GOAL, goal["intent"], goal["source"],
                           [s["id"] for s in steps]))
        return copy.deepcopy(_plan(STATUS_READY, request_status, goal, steps))
    except Exception:  # pragma: no cover - defensive: the layer is optional
        return empty_reasoning_plan(MISSING_REQUEST_INVALID)
