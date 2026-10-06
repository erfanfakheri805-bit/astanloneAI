"""
Runtime growth - Application Verification (Prompt 951)
=======================================================
`verify_runtime_growth_application(application_contract, transaction,
application_result)` is a pure, deterministic VERIFIER for the Prompt 950
controlled in-memory application. It returns a fresh dict with exactly: version,
available, status, valid, request_id, verification_type, application_verified,
persistent, source_modified, execution_verified.

Steps (nothing supplied is trusted):
  1. the Prompt 947 contract is re-validated;
  2. the Prompt 949 transaction is re-derived from it and the supplied
     transaction must match exactly (keys, values, value types);
  3. the Prompt 950 application result is re-derived from contract + transaction
     and the supplied result must match exactly, including application_state;
  4. the supported operation is re-checked explicitly: target "runtime_growth",
     proposal_type "runtime_improvement", change_scope
     "bounded_runtime_change_design", operation "controlled_runtime_growth",
     status "applied", execution_attempted True, applied True, application_mode and
     transaction_mode "controlled", state "applied_in_memory", persistent False,
     source_modified False.

A valid application yields status "verified", valid True, verification_type
"controlled_runtime_growth", application_verified True, persistent False,
source_modified False, execution_verified True, request_id copied only from the
freshly validated contract. Anything else yields the unavailable result (no
untrusted field copied).

execution_verified True means ONLY that the supplied Prompt 950 result correctly
represents the controlled in-memory application. It is not arbitrary or source
code execution, autonomous execution, permission, authorization, approval,
persistent self-modification or Android execution. The Prompt 943/944/947 scope
mappings and Prompt 950 behavior are unchanged; "controlled_runtime_growth" is
only the operation name, never a change_scope. No file, memory.db, network,
subprocess, eval/exec, generated code, clock, randomness or UUID; inputs are never
mutated; nothing raises. Not wired into Core, RuntimeCore, AEL, Android,
capabilities, upgrades, authorization or Section 18.
"""

from runtime_growth import runtime_growth_application_result as _result
from runtime_growth import runtime_growth_application_transaction as _transaction
from runtime_growth import runtime_growth_controlled_application as _applied

VERIFICATION_VERSION = "1"
STATUS_VERIFIED = "verified"
STATUS_UNAVAILABLE = "unavailable"
VERIFICATION_TYPE = "controlled_runtime_growth"

FIELDS = ("version", "available", "status", "valid", "request_id", "verification_type",
          "application_verified", "persistent", "source_modified", "execution_verified")


def _unavailable_verification():
    return {"version": VERIFICATION_VERSION, "available": False, "status": STATUS_UNAVAILABLE,
            "valid": False, "request_id": None, "verification_type": None,
            "application_verified": False, "persistent": False, "source_modified": False,
            "execution_verified": False}


def _is_exact_controlled_application(a, c):
    """Explicit re-check of every Prompt 951 requirement against the trusted contract."""
    s = a.get("application_state")
    return (list(a) == list(_applied.FIELDS)
            and a["version"] == "1" and a["available"] is True
            and a["status"] == _applied.STATUS_APPLIED
            and a["request_id"] == c["request_id"]
            and a["target"] == _applied.SUPPORTED_TARGET == c["target"]
            and a["proposal_type"] == _applied.SUPPORTED_PROPOSAL_TYPE == c["proposal_type"]
            and a["change_scope"] == _applied.SUPPORTED_CHANGE_SCOPE == c["change_scope"]
            and a["application_mode"] == "controlled"
            and a["transaction_mode"] == "controlled"
            and a["execution_attempted"] is True and a["applied"] is True
            and isinstance(s, dict) and list(s) == list(_applied.STATE_FIELDS)
            and s["state"] == _applied.STATE_APPLIED_IN_MEMORY
            and s["request_id"] == c["request_id"]
            and s["operation"] == VERIFICATION_TYPE
            and s["persistent"] is False and s["source_modified"] is False)


def verify_runtime_growth_application(application_contract, transaction, application_result):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not _result._is_valid_application_contract(application_contract):
            return _unavailable_verification()
        c = application_contract
        expected_tx = _transaction.build_runtime_growth_application_transaction(
            c, _result.build_runtime_growth_application_result(c))
        if expected_tx.get("status") != _transaction.STATUS_PREPARED \
                or not isinstance(transaction, dict) \
                or not _applied._strictly_equal(transaction, expected_tx):
            return _unavailable_verification()
        expected_app = _applied.apply_runtime_growth_transaction(expected_tx, c)
        if expected_app.get("status") != _applied.STATUS_APPLIED \
                or not isinstance(application_result, dict) \
                or not _applied._strictly_equal(application_result, expected_app) \
                or list(application_result) != list(_applied.FIELDS) \
                or not _is_exact_controlled_application(application_result, c):
            return _unavailable_verification()
        return {"version": VERIFICATION_VERSION, "available": True, "status": STATUS_VERIFIED,
                "valid": True, "request_id": c["request_id"],
                "verification_type": VERIFICATION_TYPE, "application_verified": True,
                "persistent": False, "source_modified": False, "execution_verified": True}
    except Exception:  # noqa: BLE001 - the verifier never raises
        return _unavailable_verification()
