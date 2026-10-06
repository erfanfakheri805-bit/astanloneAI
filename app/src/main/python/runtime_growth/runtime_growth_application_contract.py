"""
Runtime growth - Application Contract (Prompt 947)
===================================================
`build_runtime_growth_application_contract(application_request)` is a pure,
deterministic DESCRIPTION of what a future controlled application executor would
be allowed to receive. It accepts only a valid Prompt 946 application request and
returns a fresh dict with exactly: version, available, status, request_id,
proposal_type, target, goal, change_scope, application_mode, execution_allowed.

The request is validated internally: exactly the ten Prompt 946 keys; version
"1"; available True; status "ready"; non-empty string request_id; a supported
proposal_type whose change_scope is the exact Prompt 943 mapped value; string
target and goal; application_mode "controlled"; execution_allowed False. A valid
request yields status "contracted" with the data fields copied. Anything invalid,
forged, malformed or unavailable yields the unavailable result (available False,
status "unavailable", every data field None, execution_allowed False) exposing no
partially trusted field.

The contract is NOT execution permission, approval, authorization or a capability
/ upgrade invocation: execution_allowed is always False and no approval mechanism
exists here. Nothing is executed, applied, generated or written; no file,
memory.db, network, subprocess, clock, randomness or exec/eval access; inputs are
never mutated; nothing raises. Not wired into Core, RuntimeCore, AEL, Android,
capabilities, upgrades, authorization or Section 18.
"""

from runtime_growth import runtime_growth_application_request as _request
from runtime_growth import runtime_growth_proposal_validation as _proposal_validation

CONTRACT_VERSION = "1"
STATUS_CONTRACTED = "contracted"
STATUS_UNAVAILABLE = "unavailable"

FIELDS = _request.FIELDS


def _unavailable_contract():
    return {"version": CONTRACT_VERSION, "available": False, "status": STATUS_UNAVAILABLE,
            "request_id": None, "proposal_type": None, "target": None, "goal": None,
            "change_scope": None, "application_mode": None, "execution_allowed": False}


def _is_valid_application_request(r):
    """True only for exactly what Prompt 946 produces for a ready request."""
    if not isinstance(r, dict) or set(r) != set(FIELDS):
        return False
    scopes = _proposal_validation.PROPOSAL_TYPE_SCOPES
    return (isinstance(r["version"], str) and r["version"] == _request.REQUEST_VERSION
            and r["available"] is True
            and isinstance(r["status"], str) and r["status"] == _request.STATUS_READY
            and isinstance(r["request_id"], str) and r["request_id"] != ""
            and isinstance(r["proposal_type"], str) and r["proposal_type"] in scopes
            and isinstance(r["target"], str) and isinstance(r["goal"], str)
            and isinstance(r["change_scope"], str)
            and scopes[r["proposal_type"]] == r["change_scope"]
            and isinstance(r["application_mode"], str)
            and r["application_mode"] == _request.APPLICATION_MODE_CONTROLLED
            and r["execution_allowed"] is False)


def build_runtime_growth_application_contract(application_request):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not _is_valid_application_request(application_request):
            return _unavailable_contract()
        r = application_request
        return {"version": CONTRACT_VERSION, "available": True, "status": STATUS_CONTRACTED,
                "request_id": r["request_id"], "proposal_type": r["proposal_type"],
                "target": r["target"], "goal": r["goal"], "change_scope": r["change_scope"],
                "application_mode": _request.APPLICATION_MODE_CONTROLLED,
                "execution_allowed": False}
    except Exception:  # noqa: BLE001 - the contract builder never raises
        return _unavailable_contract()
