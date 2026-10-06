"""
Runtime growth - Controlled Growth Cycle (Prompt 952)
======================================================
`run_controlled_runtime_growth_cycle(request_data)` composes the existing pure
Runtime Growth stages of Prompts 939-951, in this exact order, into one
deterministic cycle:

  1. 939 create_runtime_growth_request
  2. 940 validate_runtime_growth_request
  3. 941 analyze_runtime_growth_request
  4. 942 build_runtime_growth_plan
  5. 943 build_runtime_growth_proposal
  6. 944 validate_runtime_growth_proposal
  7. 945 evaluate_runtime_growth_application_boundary
  8. 946 build_runtime_growth_application_request
  9. 947 build_runtime_growth_application_contract
 10. 948 build_runtime_growth_application_result
 11. 949 build_runtime_growth_application_transaction
 12. 950 apply_runtime_growth_transaction
 13. 951 verify_runtime_growth_application

The stage functions are the authoritative implementations: no validation rule is
duplicated or reimplemented here, no stage is bypassed or skipped, and no
intermediate object is fabricated. The cycle only checks that each stage returned
its own success status and stops at the first stage that did not, returning the
fixed unavailable result. Whether a request is supported (IMPROVE_RUNTIME,
target "runtime_growth", proposal type "runtime_improvement", change scope
"bounded_runtime_change_design") is decided by those stages - Prompt 950 applies
only that operation and Prompt 951 re-verifies it. "controlled_runtime_growth" is
the Prompt 950 operation name, never a change scope.

The result has exactly 16 keys. "verified" is returned only after the Prompt 951
verification of the Prompt 950 application succeeded and its request id equals
the Prompt 939 request id. A verified result means only that the controlled
IN-MEMORY application was correctly represented: it never claims persistence,
source modification, autonomous or code execution, permission or authorization,
and has no fields for them beyond persistent / source_modified, both False.
Anything invalid, unsupported, forged, malformed or unavailable yields the fixed
unavailable result with no untrusted field copied.

No file, memory.db, network, subprocess, eval/exec, generated code, clock,
randomness or UUID; the input is never mutated; nothing raises. Not wired into
Core, RuntimeCore, AEL, Android, capabilities, upgrades, authorization or
Section 18.
"""

from runtime_growth import runtime_growth_analysis as _analysis
from runtime_growth import runtime_growth_application_boundary as _boundary
from runtime_growth import runtime_growth_application_contract as _contract
from runtime_growth import runtime_growth_application_request as _app_request
from runtime_growth import runtime_growth_application_result as _app_result
from runtime_growth import runtime_growth_application_transaction as _transaction
from runtime_growth import runtime_growth_application_verification as _verification
from runtime_growth import runtime_growth_controlled_application as _application
from runtime_growth import runtime_growth_plan as _plan
from runtime_growth import runtime_growth_proposal as _proposal
from runtime_growth import runtime_growth_proposal_validation as _proposal_validation
from runtime_growth import runtime_growth_request as _request
from runtime_growth import runtime_growth_request_validation as _request_validation

CYCLE_VERSION = "1"
STATUS_VERIFIED = "verified"
STATUS_UNAVAILABLE = "unavailable"

FIELDS = ("version", "available", "status", "request_id", "request_status", "plan_status",
          "proposal_status", "boundary_status", "application_request_status",
          "contract_status", "transaction_status", "application_status",
          "verification_status", "application_verified", "persistent", "source_modified")


def _unavailable_cycle():
    return {"version": CYCLE_VERSION, "available": False, "status": STATUS_UNAVAILABLE,
            "request_id": None, "request_status": STATUS_UNAVAILABLE,
            "plan_status": STATUS_UNAVAILABLE, "proposal_status": STATUS_UNAVAILABLE,
            "boundary_status": STATUS_UNAVAILABLE,
            "application_request_status": STATUS_UNAVAILABLE,
            "contract_status": STATUS_UNAVAILABLE, "transaction_status": STATUS_UNAVAILABLE,
            "application_status": STATUS_UNAVAILABLE,
            "verification_status": STATUS_UNAVAILABLE, "application_verified": False,
            "persistent": False, "source_modified": False}


def _status_is(stage_output, expected):
    return isinstance(stage_output, dict) and stage_output.get("status") == expected


def run_controlled_runtime_growth_cycle(request_data):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        request = _request.create_runtime_growth_request(request_data)                  # 939
        if not _status_is(request, _request.STATUS_REQUESTED):
            return _unavailable_cycle()
        validation = _request_validation.validate_runtime_growth_request(request)       # 940
        if not _status_is(validation, _request_validation.STATUS_VALID):
            return _unavailable_cycle()
        analysis = _analysis.analyze_runtime_growth_request(request, validation)        # 941
        if not _status_is(analysis, _analysis.STATUS_ANALYZED):
            return _unavailable_cycle()
        plan = _plan.build_runtime_growth_plan(request, validation, analysis)           # 942
        if not _status_is(plan, _plan.STATUS_PLANNED):
            return _unavailable_cycle()
        proposal = _proposal.build_runtime_growth_proposal(
            request, validation, analysis, plan)                                        # 943
        if not _status_is(proposal, _proposal.STATUS_PROPOSED):
            return _unavailable_cycle()
        proposal_validation = _proposal_validation.validate_runtime_growth_proposal(
            proposal)                                                                   # 944
        if not _status_is(proposal_validation, _proposal_validation.STATUS_VALID):
            return _unavailable_cycle()
        boundary = _boundary.evaluate_runtime_growth_application_boundary(
            proposal, proposal_validation)                                              # 945
        if not _status_is(boundary, _boundary.STATUS_ELIGIBLE):
            return _unavailable_cycle()
        app_request = _app_request.build_runtime_growth_application_request(
            proposal, proposal_validation, boundary)                                    # 946
        if not _status_is(app_request, _app_request.STATUS_READY):
            return _unavailable_cycle()
        contract = _contract.build_runtime_growth_application_contract(app_request)     # 947
        if not _status_is(contract, _contract.STATUS_CONTRACTED):
            return _unavailable_cycle()
        result = _app_result.build_runtime_growth_application_result(contract)          # 948
        if not _status_is(result, _app_result.STATUS_NOT_APPLIED):
            return _unavailable_cycle()
        transaction = _transaction.build_runtime_growth_application_transaction(
            contract, result)                                                           # 949
        if not _status_is(transaction, _transaction.STATUS_PREPARED):
            return _unavailable_cycle()
        application = _application.apply_runtime_growth_transaction(
            transaction, contract)                                                      # 950
        if not _status_is(application, _application.STATUS_APPLIED):
            return _unavailable_cycle()
        verification = _verification.verify_runtime_growth_application(
            contract, transaction, application)                                         # 951
        if not _status_is(verification, _verification.STATUS_VERIFIED) \
                or verification.get("valid") is not True \
                or verification.get("application_verified") is not True \
                or verification.get("execution_verified") is not True \
                or verification.get("persistent") is not False \
                or verification.get("source_modified") is not False:
            return _unavailable_cycle()
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or request_id == "" \
                or verification.get("request_id") != request_id \
                or contract.get("request_id") != request_id \
                or application.get("request_id") != request_id:
            return _unavailable_cycle()
        return {"version": CYCLE_VERSION, "available": True, "status": STATUS_VERIFIED,
                "request_id": request_id, "request_status": validation["status"],
                "plan_status": plan["status"], "proposal_status": proposal["status"],
                "boundary_status": boundary["status"],
                "application_request_status": app_request["status"],
                "contract_status": contract["status"],
                "transaction_status": transaction["status"],
                "application_status": application["status"],
                "verification_status": verification["status"],
                "application_verified": True, "persistent": False, "source_modified": False}
    except Exception:  # noqa: BLE001 - the cycle never raises
        return _unavailable_cycle()
