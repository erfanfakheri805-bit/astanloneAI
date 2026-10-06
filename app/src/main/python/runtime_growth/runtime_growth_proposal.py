"""
Runtime growth - Runtime Growth Proposal (Prompt 943)
======================================================
`build_runtime_growth_proposal(request, validation, analysis, plan)` is a pure,
deterministic, DESCRIPTIVE change proposal built from a validated, analyzed and
planned growth request. It returns a fresh dict with exactly: version, available,
status, proposal_type, request_id, target, goal, reason, plan_steps, change_scope,
execution_allowed, descriptive_only.

A proposal is produced only when the request is valid per Prompt 940 and
`validation`, `analysis` and `plan` each exactly equal a fresh Prompt 940 / 941 /
942 result for that request. Anything invalid, unavailable, forged or mismatched
yields the safe unavailable proposal (available False, status "unavailable", every
value None, plan_steps [], execution_allowed False, descriptive_only True).

Proposal type and change scope depend only on the exact request kind. Nothing is
executed, approved, applied, generated or written; execution_allowed is always
False. No file, memory.db, network, subprocess, clock, randomness or exec/eval
access; inputs are never mutated; nothing raises. Not wired into Core, RuntimeCore,
AEL, Android, capabilities, upgrades or Section 18.
"""

from runtime_growth import runtime_growth_analysis as _analysis
from runtime_growth import runtime_growth_plan as _plan
from runtime_growth import runtime_growth_request as _request
from runtime_growth import runtime_growth_request_validation as _validation

PROPOSAL_VERSION = "1"
STATUS_PROPOSED = "proposed"
STATUS_UNAVAILABLE = "unavailable"

FIELDS = ("version", "available", "status", "proposal_type", "request_id", "target", "goal",
          "reason", "plan_steps", "change_scope", "execution_allowed", "descriptive_only")

_PROPOSALS = {
    _request.KIND_CREATE_CAPABILITY: (
        "capability_creation", "capability_definition_and_implementation_design"),
    _request.KIND_IMPROVE_CAPABILITY: (
        "capability_improvement", "existing_capability_improvement_design"),
    _request.KIND_IMPROVE_RUNTIME: (
        "runtime_improvement", "bounded_runtime_change_design"),
}


def _unavailable_proposal():
    return {"version": PROPOSAL_VERSION, "available": False, "status": STATUS_UNAVAILABLE,
            "proposal_type": None, "request_id": None, "target": None, "goal": None,
            "reason": None, "plan_steps": [], "change_scope": None,
            "execution_allowed": False, "descriptive_only": True}


def build_runtime_growth_proposal(request, validation, analysis, plan):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not all(isinstance(x, dict) for x in (request, validation, analysis, plan)):
            return _unavailable_proposal()
        expected_validation = _validation.validate_runtime_growth_request(request)
        if expected_validation.get("valid") is not True or validation != expected_validation:
            return _unavailable_proposal()
        expected_analysis = _analysis.analyze_runtime_growth_request(request, expected_validation)
        if expected_analysis.get("status") != _analysis.STATUS_ANALYZED \
                or analysis != expected_analysis:
            return _unavailable_proposal()
        expected_plan = _plan.build_runtime_growth_plan(request, expected_validation,
                                                        expected_analysis)
        if expected_plan.get("status") != _plan.STATUS_PLANNED or plan != expected_plan:
            return _unavailable_proposal()
        kind = request["kind"]
        if kind not in _PROPOSALS:
            return _unavailable_proposal()
        proposal_type, change_scope = _PROPOSALS[kind]
        return {"version": PROPOSAL_VERSION, "available": True, "status": STATUS_PROPOSED,
                "proposal_type": proposal_type, "request_id": request["request_id"],
                "target": request["target"], "goal": request["goal"],
                "reason": request["reason"], "plan_steps": list(expected_plan["steps"]),
                "change_scope": change_scope, "execution_allowed": False,
                "descriptive_only": True}
    except Exception:  # noqa: BLE001 - the proposal builder never raises
        return _unavailable_proposal()
