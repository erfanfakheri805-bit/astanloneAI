"""
Runtime growth - Controlled Application (Prompt 950)
=====================================================
`apply_runtime_growth_transaction(transaction, application_contract)` performs
exactly ONE deliberately narrow, deterministic, IN-MEMORY application operation
and returns its state as a fresh dict with exactly: version, available, status,
request_id, proposal_type, target, change_scope, application_mode,
transaction_mode, execution_attempted, applied, application_state.

Accepted input: a valid Prompt 949 prepared transaction plus the matching valid
Prompt 947 application contract. The contract is re-validated here (never
trusted), the Prompt 948 result and Prompt 949 transaction are RE-DERIVED from it,
and the supplied transaction must match the re-derived one exactly (same keys,
same values, same value types).

SUPPORTED OPERATION (the only one that can reach "applied"):
    target == "runtime_growth"
    proposal_type == "runtime_improvement", whose Prompt 943 change_scope
    ("bounded_runtime_change_design") is the only scope the earlier stages allow
    for a runtime-growth operation. The operation itself is named
    "controlled_runtime_growth". (No earlier stage can emit a change_scope literally
    equal to "controlled_runtime_growth"; the proposal-type/scope mapping of
    Prompts 943/944/947 is kept unchanged and consistent.)

For that operation an immutable-style application_state is created in memory:
    {"state": "applied_in_memory", "request_id": <trusted contract id>,
     "operation": "controlled_runtime_growth", "persistent": False,
     "source_modified": False}
and status "applied", execution_attempted True, applied True. The state is
verified against its exact expected shape before being returned.

Anything else - malformed, forged, mismatched, unsupported target / proposal type
/ scope, already-applied, wrong mode, execution_allowed True, extra keys -
returns the fixed unavailable result (available False, status "unavailable",
data fields None, execution_attempted False, applied False, application_state
None) without copying any untrusted field and without performing anything.

This is NOT permission, authorization, approval, arbitrary execution, source
modification or a persistent self-upgrade. Nothing is written to disk or
memory.db; no source/Core/RuntimeCore/Android/capability/upgrade file is touched;
no generated code is imported or executed; no subprocess, network, eval/exec,
clock, randomness or UUID. Inputs are never mutated; nothing raises. Not wired
into Core, RuntimeCore, AEL, Android, capabilities, upgrades, authorization or
Section 18.
"""

from runtime_growth import runtime_growth_application_request as _request
from runtime_growth import runtime_growth_application_result as _result
from runtime_growth import runtime_growth_application_transaction as _transaction
from runtime_growth import runtime_growth_proposal_validation as _proposal_validation

APPLICATION_VERSION = "1"
STATUS_APPLIED = "applied"
STATUS_UNAVAILABLE = "unavailable"
APPLICATION_MODE_CONTROLLED = "controlled"
TRANSACTION_MODE_CONTROLLED = "controlled"
STATE_APPLIED_IN_MEMORY = "applied_in_memory"
OPERATION_CONTROLLED_RUNTIME_GROWTH = "controlled_runtime_growth"

SUPPORTED_TARGET = "runtime_growth"
SUPPORTED_PROPOSAL_TYPE = "runtime_improvement"
SUPPORTED_CHANGE_SCOPE = _proposal_validation.PROPOSAL_TYPE_SCOPES[SUPPORTED_PROPOSAL_TYPE]

FIELDS = ("version", "available", "status", "request_id", "proposal_type", "target",
          "change_scope", "application_mode", "transaction_mode", "execution_attempted",
          "applied", "application_state")
STATE_FIELDS = ("state", "request_id", "operation", "persistent", "source_modified")


def _unavailable_application():
    return {"version": APPLICATION_VERSION, "available": False, "status": STATUS_UNAVAILABLE,
            "request_id": None, "proposal_type": None, "target": None, "change_scope": None,
            "application_mode": None, "transaction_mode": None, "execution_attempted": False,
            "applied": False, "application_state": None}


def _strictly_equal(a, b):
    """Dict equality that also requires identical value types (True != 1)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return set(a) == set(b) and all(_strictly_equal(a[k], b[k]) for k in a)
    return a == b


def _build_application_state(request_id):
    return {"state": STATE_APPLIED_IN_MEMORY, "request_id": request_id,
            "operation": OPERATION_CONTROLLED_RUNTIME_GROWTH, "persistent": False,
            "source_modified": False}


def _is_valid_application_state(state, request_id):
    expected = {"state": STATE_APPLIED_IN_MEMORY, "request_id": request_id,
                "operation": OPERATION_CONTROLLED_RUNTIME_GROWTH, "persistent": False,
                "source_modified": False}
    return (isinstance(state, dict) and list(state) == list(STATE_FIELDS)
            and _strictly_equal(state, expected))


def apply_runtime_growth_transaction(transaction, application_contract):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not _result._is_valid_application_contract(application_contract):
            return _unavailable_application()
        c = application_contract
        expected_result = _result.build_runtime_growth_application_result(c)
        expected_tx = _transaction.build_runtime_growth_application_transaction(
            c, expected_result)
        if expected_tx.get("status") != _transaction.STATUS_PREPARED \
                or expected_tx.get("available") is not True \
                or expected_tx.get("transaction_mode") != _transaction.TRANSACTION_MODE_CONTROLLED \
                or expected_tx.get("execution_allowed") is not False \
                or expected_tx.get("applied") is not False \
                or not isinstance(transaction, dict) \
                or not _strictly_equal(transaction, expected_tx):
            return _unavailable_application()
        if c["application_mode"] != _request.APPLICATION_MODE_CONTROLLED \
                or c["execution_allowed"] is not False:
            return _unavailable_application()
        if c["target"] != SUPPORTED_TARGET \
                or c["proposal_type"] != SUPPORTED_PROPOSAL_TYPE \
                or c["change_scope"] != SUPPORTED_CHANGE_SCOPE:
            return _unavailable_application()
        state = _build_application_state(c["request_id"])
        if not _is_valid_application_state(state, c["request_id"]):
            return _unavailable_application()
        return {"version": APPLICATION_VERSION, "available": True, "status": STATUS_APPLIED,
                "request_id": c["request_id"], "proposal_type": c["proposal_type"],
                "target": c["target"], "change_scope": c["change_scope"],
                "application_mode": APPLICATION_MODE_CONTROLLED,
                "transaction_mode": TRANSACTION_MODE_CONTROLLED,
                "execution_attempted": True, "applied": True, "application_state": state}
    except Exception:  # noqa: BLE001 - the controlled application never raises
        return _unavailable_application()
