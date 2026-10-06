"""
Reasoning - decision pipeline (Prompt 837)
==========================================
Connects the existing reasoning layers into one validated decision:

    reasoning request (Prompt 834)
      -> build_reasoning_plan   (Prompt 835, the existing planner)
      -> validate_reasoning_plan (Prompt 836, the existing validator)
      -> decision

  decide_reasoning(reasoning_request, plan_builder=build_reasoning_plan)

`plan_builder` defaults to the existing planner; it is only a seam so the
pipeline can be exercised against a faulty planner. Its result is never
repaired: whatever it returns is validated as it is.

Result (always the same keys, in this order):

  {"version", "decision", "reason", "request_status", "plan_status",
   "validation", "next_step", "executed"}

  decision  "ready"               request ready, plan valid and ready
            "needs_clarification" an ambiguity blocks the request
            "needs_information"   information is unresolved, missing or
                                  unknown (also: no / malformed request)
            "invalid_plan"        the plan failed validation (or the
                                  planner returned nothing usable)
  reason    "ready"; the first plan step's ref (e.g. "intent_unknown");
            "request_status_conflict"; or, for invalid_plan, the first
            validation error code
  request_status  the request's own status string when it is one of
            ready / unknown / ambiguous / unresolved / missing, else None
  plan_status     the plan's status when the plan is valid (or a known
            status string on an invalid plan), else None
  validation      the Prompt 836 validation result, copied unchanged
  next_step       None, or {"id", "kind", "ref", "detail", "remaining"}:
            the first step of a VALID plan (it has no dependencies; the
            others follow it) and how many steps remain after it; it only
            describes a step, nothing is run
  executed        always False

A decision is "ready" only when the request's status is "ready", the plan
is valid, and the plan is ready (so nothing unresolved, ambiguous or
missing blocks it). A valid plan that is ready while the request does not
say "ready" is a conflict: it is never "ready" - it is needs_clarification
when the request says "ambiguous", otherwise needs_information, with reason
"request_status_conflict" and no next step. A valid plan that is not ready
gives the decision of its own status. A plan that fails validation is
"invalid_plan" with no next step.

Nothing is executed, repaired, modified or invented; the request is only
read. Bounded (the validation result is bounded), JSON-safe, deterministic,
never raises, always a fresh dict. Pure stdlib; no Memory, AEL, Core, NLU
change, LLM or network.
"""

import copy

from .reasoning_plan import (
    build_reasoning_plan, STATUS_READY, STATUS_NEEDS_CLARIFICATION,
    STATUS_NEEDS_INFORMATION,
)
from .reasoning_plan_validation import validate_reasoning_plan

DECISION_VERSION = 1

DECISION_READY = "ready"
DECISION_NEEDS_CLARIFICATION = "needs_clarification"
DECISION_NEEDS_INFORMATION = "needs_information"
DECISION_INVALID_PLAN = "invalid_plan"

REASON_READY = "ready"
REASON_REQUEST_STATUS_CONFLICT = "request_status_conflict"
REASON_PLAN_INVALID = "plan_invalid"

_REQUEST_STATUSES = ("ready", "unknown", "ambiguous", "unresolved", "missing")
_PLAN_STATUSES = (STATUS_READY, STATUS_NEEDS_CLARIFICATION, STATUS_NEEDS_INFORMATION)


def _result(decision, reason, request_status, plan_status, validation, next_step):
    return {"version": DECISION_VERSION, "decision": decision, "reason": reason,
            "request_status": request_status, "plan_status": plan_status,
            "validation": validation, "next_step": next_step, "executed": False}


def _request_status(request):
    status = request.get("status") if isinstance(request, dict) else None
    return status if isinstance(status, str) and status in _REQUEST_STATUSES else None


def _next_step(plan):
    """First step of an already VALIDATED plan, as a description."""
    steps = plan["steps"]
    first = steps[0]
    return {"id": first["id"], "kind": first["kind"], "ref": first["ref"],
            "detail": first["detail"], "remaining": len(steps) - 1}


def decide_reasoning(reasoning_request, plan_builder=build_reasoning_plan):
    """Validated reasoning decision for `reasoning_request` (see module
    docstring). Never raises."""
    request_status = None
    try:
        request_status = _request_status(reasoning_request)
        try:
            plan = plan_builder(reasoning_request)
        except Exception:
            plan = None
        validation = validate_reasoning_plan(plan)

        if not validation["valid"]:
            plan_status = None
            if isinstance(plan, dict) and isinstance(plan.get("status"), str) \
                    and plan["status"] in _PLAN_STATUSES:
                plan_status = plan["status"]
            reason = validation["errors"][0]["code"] if validation["errors"] else REASON_PLAN_INVALID
            return copy.deepcopy(_result(DECISION_INVALID_PLAN, reason, request_status,
                                         plan_status, validation, None))

        plan_status = plan["status"]
        if plan_status == STATUS_READY:
            if request_status == "ready":
                return copy.deepcopy(_result(DECISION_READY, REASON_READY, request_status,
                                             plan_status, validation, _next_step(plan)))
            decision = (DECISION_NEEDS_CLARIFICATION if request_status == "ambiguous"
                        else DECISION_NEEDS_INFORMATION)
            return copy.deepcopy(_result(decision, REASON_REQUEST_STATUS_CONFLICT,
                                         request_status, plan_status, validation, None))

        decision = (DECISION_NEEDS_CLARIFICATION if plan_status == STATUS_NEEDS_CLARIFICATION
                    else DECISION_NEEDS_INFORMATION)
        step = _next_step(plan)
        return copy.deepcopy(_result(decision, step["ref"], request_status,
                                     plan_status, validation, step))
    except Exception:  # pragma: no cover - defensive: the pipeline is optional
        validation = validate_reasoning_plan(None)
        return _result(DECISION_INVALID_PLAN, validation["errors"][0]["code"],
                       request_status, None, validation, None)
