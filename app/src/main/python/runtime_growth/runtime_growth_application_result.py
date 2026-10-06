"""
Runtime growth - Application Result (Prompt 948)
=================================================
`build_runtime_growth_application_result(application_contract)` is a pure,
deterministic RESULT SCHEMA for a future controlled application operation. It
accepts only a valid Prompt 947 application contract and returns a fresh dict
with exactly: version, available, status, request_id, proposal_type, target,
change_scope, application_mode, execution_attempted, applied.

The contract is validated internally: exactly the ten Prompt 947 keys; version
"1"; available True; status "contracted"; non-empty string request_id; a
supported proposal_type whose change_scope is the exact Prompt 943 mapped value;
string target and goal; application_mode "controlled"; execution_allowed False.
A valid contract yields status "not_applied" with request_id, proposal_type,
target and change_scope copied. Anything invalid, forged, malformed or
unavailable yields the unavailable result (available False, status
"unavailable", every data field None) exposing no partially trusted field.

Only two states exist in this prompt - a valid contract and an application not
yet attempted. "applied" and "execution_attempted" are always False; nothing is
performed, claimed, approved or permitted. No file, memory.db, network,
subprocess, clock, randomness or exec/eval access; inputs are never mutated;
nothing raises. Not wired into Core, RuntimeCore, AEL, Android, capabilities,
upgrades, authorization or Section 18.
"""

from runtime_growth import runtime_growth_application_contract as _contract
from runtime_growth import runtime_growth_application_request as _request
from runtime_growth import runtime_growth_proposal_validation as _proposal_validation

RESULT_VERSION = "1"
STATUS_NOT_APPLIED = "not_applied"
STATUS_UNAVAILABLE = "unavailable"

FIELDS = ("version", "available", "status", "request_id", "proposal_type", "target",
          "change_scope", "application_mode", "execution_attempted", "applied")


def _unavailable_result():
    return {"version": RESULT_VERSION, "available": False, "status": STATUS_UNAVAILABLE,
            "request_id": None, "proposal_type": None, "target": None, "change_scope": None,
            "application_mode": None, "execution_attempted": False, "applied": False}


def _is_valid_application_contract(c):
    """True only for exactly what Prompt 947 produces for a contracted request."""
    if not isinstance(c, dict) or set(c) != set(_contract.FIELDS):
        return False
    scopes = _proposal_validation.PROPOSAL_TYPE_SCOPES
    return (isinstance(c["version"], str) and c["version"] == _contract.CONTRACT_VERSION
            and c["available"] is True
            and isinstance(c["status"], str) and c["status"] == _contract.STATUS_CONTRACTED
            and isinstance(c["request_id"], str) and c["request_id"] != ""
            and isinstance(c["proposal_type"], str) and c["proposal_type"] in scopes
            and isinstance(c["target"], str) and isinstance(c["goal"], str)
            and isinstance(c["change_scope"], str)
            and scopes[c["proposal_type"]] == c["change_scope"]
            and isinstance(c["application_mode"], str)
            and c["application_mode"] == _request.APPLICATION_MODE_CONTROLLED
            and c["execution_allowed"] is False)


def build_runtime_growth_application_result(application_contract):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not _is_valid_application_contract(application_contract):
            return _unavailable_result()
        c = application_contract
        return {"version": RESULT_VERSION, "available": True, "status": STATUS_NOT_APPLIED,
                "request_id": c["request_id"], "proposal_type": c["proposal_type"],
                "target": c["target"], "change_scope": c["change_scope"],
                "application_mode": _request.APPLICATION_MODE_CONTROLLED,
                "execution_attempted": False, "applied": False}
    except Exception:  # noqa: BLE001 - the result builder never raises
        return _unavailable_result()
