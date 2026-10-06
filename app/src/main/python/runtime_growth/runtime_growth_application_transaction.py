"""
Runtime growth - Application Transaction (Prompt 949)
======================================================
`build_runtime_growth_application_transaction(application_contract,
application_result)` is a pure, deterministic PREPARED-TRANSACTION DESCRIPTION for
a future controlled application step. It returns a fresh dict with exactly:
version, available, status, request_id, proposal_type, target, change_scope,
transaction_mode, precondition_status, execution_allowed, applied.

It is valid only when `application_contract` passes the Prompt 947 contract shape
check (re-validated here, never trusted: exact keys and types, status
"contracted", supported proposal_type with its exact change_scope, application_mode
"controlled", execution_allowed False) and `application_result` EXACTLY equals the
Prompt 948 result freshly derived from that contract, with status "not_applied",
execution_attempted False and applied False. A valid input yields status
"prepared", transaction_mode "controlled", precondition_status "satisfied", with
request_id, proposal_type, target and change_scope copied from the trusted
contract. Anything invalid, forged, mismatched, malformed or unavailable yields the
unavailable result (available False, status "unavailable", data fields None,
precondition_status "not_satisfied") without copying any untrusted field.

"prepared" is NOT approved, authorized, permitted, executed, attempted, applied or
committed: execution_allowed and applied are always False and no approval,
permission, commit or code fields exist. No file, memory.db, network, subprocess,
clock, randomness, UUID or exec/eval access; inputs are never mutated; nothing
raises. Not wired into Core, RuntimeCore, AEL, Android, capabilities, upgrades,
authorization or Section 18.
"""

from runtime_growth import runtime_growth_application_request as _request
from runtime_growth import runtime_growth_application_result as _result

TRANSACTION_VERSION = "1"
STATUS_PREPARED = "prepared"
STATUS_UNAVAILABLE = "unavailable"
TRANSACTION_MODE_CONTROLLED = "controlled"
PRECONDITION_SATISFIED = "satisfied"
PRECONDITION_NOT_SATISFIED = "not_satisfied"

FIELDS = ("version", "available", "status", "request_id", "proposal_type", "target",
          "change_scope", "transaction_mode", "precondition_status", "execution_allowed",
          "applied")


def _unavailable_transaction():
    return {"version": TRANSACTION_VERSION, "available": False, "status": STATUS_UNAVAILABLE,
            "request_id": None, "proposal_type": None, "target": None, "change_scope": None,
            "transaction_mode": None, "precondition_status": PRECONDITION_NOT_SATISFIED,
            "execution_allowed": False, "applied": False}


def build_runtime_growth_application_transaction(application_contract, application_result):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not _result._is_valid_application_contract(application_contract):
            return _unavailable_transaction()
        expected = _result.build_runtime_growth_application_result(application_contract)
        if expected.get("status") != _result.STATUS_NOT_APPLIED \
                or expected.get("execution_attempted") is not False \
                or expected.get("applied") is not False \
                or not isinstance(application_result, dict) \
                or application_result != expected:
            return _unavailable_transaction()
        if application_contract["application_mode"] != _request.APPLICATION_MODE_CONTROLLED \
                or application_contract["execution_allowed"] is not False:
            return _unavailable_transaction()
        c = application_contract
        return {"version": TRANSACTION_VERSION, "available": True, "status": STATUS_PREPARED,
                "request_id": c["request_id"], "proposal_type": c["proposal_type"],
                "target": c["target"], "change_scope": c["change_scope"],
                "transaction_mode": TRANSACTION_MODE_CONTROLLED,
                "precondition_status": PRECONDITION_SATISFIED,
                "execution_allowed": False, "applied": False}
    except Exception:  # noqa: BLE001 - the transaction builder never raises
        return _unavailable_transaction()
