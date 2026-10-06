"""
Runtime growth - Runtime Growth Analysis (Prompt 941)
======================================================
`analyze_runtime_growth_request(request, validation)` is a pure, deterministic,
descriptive analysis of an already validated Prompt 940 request. It returns a
fresh dict with exactly: version, available, status, kind, target, goal, reason,
source, analysis_type, needs_creation, needs_improvement, needs_runtime_change,
descriptive_only.

  - the request must be a dict that Prompt 940 judges valid AND `validation` must
    be the matching valid result (available, status "valid", valid True, no
    errors); otherwise the safe unavailable analysis is returned (status
    "unavailable", available False, every other value None / False except
    descriptive_only, which is always True);
  - otherwise status is "analyzed" and the analysis follows ONLY from the exact
    request kind:
        CREATE_CAPABILITY  -> capability_creation   (needs_creation)
        IMPROVE_CAPABILITY -> capability_improvement (needs_improvement)
        IMPROVE_RUNTIME    -> runtime_improvement    (needs_runtime_change)
    The natural-language goal is copied, never interpreted.

It is descriptive only: no execution, approval, code generation, file change,
capability creation or runtime modification; no AI model, filesystem, memory.db,
network, subprocess, clock, randomness or exec/eval. Neither input is mutated and
nothing raises. It is not wired into Core, RuntimeCore, AEL, Android,
capabilities, upgrades or Section 18.
"""

from runtime_growth import runtime_growth_request as _request
from runtime_growth import runtime_growth_request_validation as _validation

ANALYSIS_VERSION = "1"

STATUS_ANALYZED = "analyzed"
STATUS_UNAVAILABLE = "unavailable"

ANALYSIS_CAPABILITY_CREATION = "capability_creation"
ANALYSIS_CAPABILITY_IMPROVEMENT = "capability_improvement"
ANALYSIS_RUNTIME_IMPROVEMENT = "runtime_improvement"

FIELDS = ("version", "available", "status", "kind", "target", "goal", "reason", "source",
          "analysis_type", "needs_creation", "needs_improvement", "needs_runtime_change",
          "descriptive_only")

# kind -> (analysis_type, needs_creation, needs_improvement, needs_runtime_change)
_ANALYSIS_BY_KIND = {
    _request.KIND_CREATE_CAPABILITY: (ANALYSIS_CAPABILITY_CREATION, True, False, False),
    _request.KIND_IMPROVE_CAPABILITY: (ANALYSIS_CAPABILITY_IMPROVEMENT, False, True, False),
    _request.KIND_IMPROVE_RUNTIME: (ANALYSIS_RUNTIME_IMPROVEMENT, False, False, True),
}


def _unavailable_analysis():
    return {"version": ANALYSIS_VERSION, "available": False, "status": STATUS_UNAVAILABLE,
            "kind": None, "target": None, "goal": None, "reason": None, "source": None,
            "analysis_type": None, "needs_creation": False, "needs_improvement": False,
            "needs_runtime_change": False, "descriptive_only": True}


def _validation_is_valid(validation):
    return (isinstance(validation, dict)
            and validation.get("available") is True
            and validation.get("status") == _validation.STATUS_VALID
            and validation.get("valid") is True
            and validation.get("error_count") == 0
            and validation.get("errors") == [])


def analyze_runtime_growth_request(request, validation):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not isinstance(request, dict) or not _validation_is_valid(validation):
            return _unavailable_analysis()
        # The supplied validation must agree with Prompt 940's own verdict.
        if _validation.validate_runtime_growth_request(request).get("valid") is not True:
            return _unavailable_analysis()
        kind = request["kind"]
        if kind not in _ANALYSIS_BY_KIND:
            return _unavailable_analysis()
        analysis_type, creation, improvement, runtime_change = _ANALYSIS_BY_KIND[kind]
        return {"version": ANALYSIS_VERSION, "available": True, "status": STATUS_ANALYZED,
                "kind": kind, "target": request["target"], "goal": request["goal"],
                "reason": request["reason"], "source": request["source"],
                "analysis_type": analysis_type, "needs_creation": creation,
                "needs_improvement": improvement, "needs_runtime_change": runtime_change,
                "descriptive_only": True}
    except Exception:  # noqa: BLE001 - the analysis never raises
        return _unavailable_analysis()
