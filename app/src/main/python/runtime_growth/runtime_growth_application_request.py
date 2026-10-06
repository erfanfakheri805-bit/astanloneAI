"""
Runtime growth - Application Request (Prompt 946)
==================================================
`build_runtime_growth_application_request(proposal, validation, boundary)` is a
pure, deterministic PREPARATION step: it turns an eligible, validated growth
proposal into a controlled application request. It returns a fresh dict with
exactly: version, available, status, request_id, proposal_type, target, goal,
change_scope, application_mode, execution_allowed.

A request is built (available True, status "ready", application_mode
"controlled", fields copied from the proposal) only when the proposal is a dict,
`validation` exactly equals a fresh Prompt 944 validation of it and is valid, and
`boundary` exactly equals a fresh Prompt 945 boundary evaluation of the proposal
and that validation, reporting eligible True, execution_allowed False and
descriptive_only True. Anything invalid, forged, unavailable or mismatched yields
the unavailable result (available False, status "unavailable", every data field
None, execution_allowed False) with no untrusted proposal data.

"ready" means ready to enter a future controlled application step - nothing is
applied. There is no approval, authorization or execution permission here:
execution_allowed is always False. No file, memory.db, network, subprocess, clock,
randomness or exec/eval access; inputs are never mutated; nothing raises. Not
wired into Core, RuntimeCore, AEL, Android, capabilities, upgrades, authorization
or Section 18.
"""

from runtime_growth import runtime_growth_application_boundary as _boundary
from runtime_growth import runtime_growth_proposal_validation as _validation

REQUEST_VERSION = "1"
STATUS_READY = "ready"
STATUS_UNAVAILABLE = "unavailable"
APPLICATION_MODE_CONTROLLED = "controlled"

FIELDS = ("version", "available", "status", "request_id", "proposal_type", "target", "goal",
          "change_scope", "application_mode", "execution_allowed")


def _unavailable_request():
    return {"version": REQUEST_VERSION, "available": False, "status": STATUS_UNAVAILABLE,
            "request_id": None, "proposal_type": None, "target": None, "goal": None,
            "change_scope": None, "application_mode": None, "execution_allowed": False}


def build_runtime_growth_application_request(proposal, validation, boundary):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not all(isinstance(x, dict) for x in (proposal, validation, boundary)):
            return _unavailable_request()
        expected_validation = _validation.validate_runtime_growth_proposal(proposal)
        if expected_validation.get("valid") is not True or validation != expected_validation:
            return _unavailable_request()
        expected_boundary = _boundary.evaluate_runtime_growth_application_boundary(
            proposal, expected_validation)
        if expected_boundary.get("status") != _boundary.STATUS_ELIGIBLE \
                or boundary != expected_boundary:
            return _unavailable_request()
        if expected_boundary.get("eligible") is not True \
                or expected_boundary.get("execution_allowed") is not False \
                or expected_boundary.get("descriptive_only") is not True:
            return _unavailable_request()
        return {"version": REQUEST_VERSION, "available": True, "status": STATUS_READY,
                "request_id": proposal["request_id"],
                "proposal_type": proposal["proposal_type"], "target": proposal["target"],
                "goal": proposal["goal"], "change_scope": proposal["change_scope"],
                "application_mode": APPLICATION_MODE_CONTROLLED, "execution_allowed": False}
    except Exception:  # noqa: BLE001 - the application request builder never raises
        return _unavailable_request()
