"""
Runtime growth - Runtime Growth Plan (Prompt 942)
==================================================
`build_runtime_growth_plan(request, validation, analysis)` is a pure,
deterministic, DESCRIPTIVE plan for a validated and analyzed growth request. It
returns a fresh dict with exactly: version, available, status, plan_type,
request_id, target, goal, reason, steps, descriptive_only.

A plan is produced only when all three inputs are verified by re-running the
existing stages: the request is valid per Prompt 940, `validation` equals the
validation result for that request, and `analysis` equals the Prompt 941 analysis
of that request. A forged, mismatched, invalid or unavailable input yields the safe
unavailable plan (available False, status "unavailable", every value None, steps
[], descriptive_only True).

The plan type and the four conceptual step descriptions depend only on the exact
request kind; goal text is copied, never interpreted. Steps are fixed strings:
no ids, clock, randomness or dynamic content. Nothing is executed, approved,
applied, generated or modified; there is no file, memory.db, network, subprocess
or exec/eval access. Inputs are never mutated and nothing raises. It is not wired
into Core, RuntimeCore, AEL, Android, capabilities, upgrades or Section 18.
"""

from runtime_growth import runtime_growth_analysis as _analysis
from runtime_growth import runtime_growth_request as _request
from runtime_growth import runtime_growth_request_validation as _validation

PLAN_VERSION = "1"
STATUS_PLANNED = "planned"
STATUS_UNAVAILABLE = "unavailable"

PLAN_CAPABILITY_CREATION = "capability_creation"
PLAN_CAPABILITY_IMPROVEMENT = "capability_improvement"
PLAN_RUNTIME_IMPROVEMENT = "runtime_improvement"

FIELDS = ("version", "available", "status", "plan_type", "request_id", "target", "goal",
          "reason", "steps", "descriptive_only")

_PLANS = {
    _request.KIND_CREATE_CAPABILITY: (PLAN_CAPABILITY_CREATION, (
        "define capability", "validate capability definition",
        "design implementation", "verify proposed change")),
    _request.KIND_IMPROVE_CAPABILITY: (PLAN_CAPABILITY_IMPROVEMENT, (
        "inspect existing capability", "identify improvement target",
        "design improvement", "verify proposed change")),
    _request.KIND_IMPROVE_RUNTIME: (PLAN_RUNTIME_IMPROVEMENT, (
        "inspect runtime target", "identify bounded improvement",
        "design runtime change", "verify proposed change")),
}


def _unavailable_plan():
    return {"version": PLAN_VERSION, "available": False, "status": STATUS_UNAVAILABLE,
            "plan_type": None, "request_id": None, "target": None, "goal": None,
            "reason": None, "steps": [], "descriptive_only": True}


def build_runtime_growth_plan(request, validation, analysis):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not isinstance(request, dict) or not isinstance(validation, dict) \
                or not isinstance(analysis, dict):
            return _unavailable_plan()
        expected_validation = _validation.validate_runtime_growth_request(request)
        if expected_validation.get("valid") is not True or validation != expected_validation:
            return _unavailable_plan()
        expected_analysis = _analysis.analyze_runtime_growth_request(request, expected_validation)
        if expected_analysis.get("status") != _analysis.STATUS_ANALYZED \
                or analysis != expected_analysis:
            return _unavailable_plan()
        kind = request["kind"]
        if kind not in _PLANS:
            return _unavailable_plan()
        plan_type, steps = _PLANS[kind]
        return {"version": PLAN_VERSION, "available": True, "status": STATUS_PLANNED,
                "plan_type": plan_type, "request_id": request["request_id"],
                "target": request["target"], "goal": request["goal"],
                "reason": request["reason"], "steps": list(steps), "descriptive_only": True}
    except Exception:  # noqa: BLE001 - the plan builder never raises
        return _unavailable_plan()
