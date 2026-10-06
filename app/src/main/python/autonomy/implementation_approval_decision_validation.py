"""
Implementation Approval Decision Validation (Prompt 897, Section 17: Controlled Autonomy)
=========================================================================================
A deterministic, read-only VALIDATION BOUNDARY for the Prompt 896 approval-decision contract.
It checks that a "pending_approval" decision is structurally valid and consistent with the
complete trusted chain (Section 16 -> Prompt 892 -> Prompt 894 -> Prompt 895 -> Prompt 896).

It never approves anything and never converts "pending_approval" into approval: there is no
"approved" status, no approval field, no authorization, no implementation, no execution, no
persistence, no code or patch generation, no network / API / model use, and no automatic
behavior. Nothing supplied is modified; every result is a fresh object.

  validate_implementation_approval_decision_context(evolution_request, analysis_result,
        specification, plan, proposal, candidate, readiness_result, design,
        validation_result, blueprint, blueprint_validation_result, contract,
        contract_validation_result, contract_readiness_result, boundary_result,
        implementation_request, request_validation_result, policy, approval_request,
        approval_request_validation_result, decision)
  validate_implementation_approval_decision_validation_result(result)

Nothing supplied is trusted. The Prompt 892 context validation re-derives the chain verdict
(reusing the Prompt 876-891 validators and the Prompt 890 boundary), the Prompt 894 builder
re-derives the policy, the Prompt 895 builder re-derives the approval request and the
Prompt 896 builder re-derives the decision; each supplied object must equal the derived one
(type-strict), so a forged but individually valid object never passes. Nothing is
re-implemented here. Checks run in this fixed order; the first failure decides the status:
   1 decision fails the Prompt 896 validator (malformed, wrong version, missing / extra key,
     non-pending approval_status, altered approval or implementation / execution flags,
     altered reason) ................................................ invalid_decision
     (only the decision_id value is invalid) ......................... invalid_decision_id
   2 Prompt 892 chain evaluation of the supplied objects
       context_mismatch .............................................. context_mismatch
       unsupported_status (e.g. improve_or_conflict) ................. unsupported_status
       validation_error .............................................. validation_error
       any other invalid stage (request, 876-890, boundary, readiness) invalid_request_validation
   3 supplied Prompt 892 result malformed / not "valid" .............. invalid_request_validation
   4 supplied Prompt 892 result differs from the derived one ......... context_mismatch
   5 policy fails the Prompt 894 validator ........................... invalid_request_validation
     policy valid but not "eligible" (ineligible, blocked, unsupported) unsupported_status
   6 policy differs from the re-derived Prompt 894 policy ............ context_mismatch
   7 approval request fails the Prompt 895 validator, or its supplied validation result is
     malformed / not valid .......................................... invalid_approval_request_validation
   8 re-derived Prompt 895 status is not "ready_for_approval", or the supplied approval
     request / validation result differ from the derived ones ....... context_mismatch
   9 decision differs from the re-derived Prompt 896 decision, or request_id,
     implementation_request_id, approval_request_id, capability_name, operation,
     policy_status, plan_id, contract_id, boundary_status or approval_status disagree
     across the stages ............................................... context_mismatch
  10 operation not create / improve ................................... unsupported_status
  11 everything holds ................................................. valid
Any unexpected internal failure -> validation_error. The vocabulary is exactly: valid,
invalid_decision, invalid_decision_id, invalid_request_validation,
invalid_approval_request_validation, context_mismatch, unsupported_status, validation_error.
Nothing in it grants approval, permission or execution.

Result (exactly these twelve keys, fresh every call):
  {"version", "status", "valid", "decision_id", "request_id", "implementation_request_id",
   "approval_request_id", "capability_name", "operation", "reason", "execution_allowed",
   "executed"}
version is the integer 1; valid is True only for status "valid"; reason equals status;
execution_allowed and executed are ALWAYS False. The identity fields are filled (from the
trusted, re-derived objects) only for "valid" and are None for every other status, so a
rejected result never carries forged values.

validate_implementation_approval_decision_validation_result(result) checks that exact shape
and returns {"valid", "errors", "execution_allowed", "executed"}; purely structural,
read-only, never raises.
"""

from capabilities.capability_evolution_proposal import validate_capability_evolution_proposal
from capabilities.capability_evolution_request import validate_capability_evolution_request
from capabilities.capability_implementation_request_validation import (
    validate_capability_implementation_request_context,
    validate_capability_implementation_request_validation_result)
from capabilities.capability_registry import MAX_ERRORS

from .implementation_approval_decision import (
    build_implementation_approval_decision, validate_implementation_approval_decision)
from .implementation_approval_request import (
    build_implementation_approval_request, validate_implementation_approval_request)
from .implementation_permission_policy import (
    build_implementation_permission_policy, validate_implementation_permission_policy)

RESULT_VERSION = 1

STATUS_VALID = "valid"
STATUS_INVALID_DECISION = "invalid_decision"
STATUS_INVALID_DECISION_ID = "invalid_decision_id"
STATUS_INVALID_REQUEST_VALIDATION = "invalid_request_validation"
STATUS_INVALID_APPROVAL_REQUEST_VALIDATION = "invalid_approval_request_validation"
STATUS_CONTEXT = "context_mismatch"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_VALID, STATUS_INVALID_DECISION, STATUS_INVALID_DECISION_ID,
            STATUS_INVALID_REQUEST_VALIDATION, STATUS_INVALID_APPROVAL_REQUEST_VALIDATION,
            STATUS_CONTEXT, STATUS_UNSUPPORTED, STATUS_ERROR)

RESULT_KEYS = ("version", "status", "valid", "decision_id", "request_id",
               "implementation_request_id", "approval_request_id", "capability_name",
               "operation", "reason", "execution_allowed", "executed")
IDENTITY_KEYS = ("decision_id", "request_id", "implementation_request_id",
                 "approval_request_id", "capability_name", "operation")
SUPPORTED_OPERATIONS = ("create", "improve")
PENDING = "pending_approval"
_VALIDATION_KEYS = ("valid", "errors", "execution_allowed", "executed")

_CHAIN_STATUS = {
    "context_mismatch": STATUS_CONTEXT,
    "unsupported_status": STATUS_UNSUPPORTED,
    "validation_error": STATUS_ERROR,
}

ERR_NOT_DICT = "result_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_VALID = "invalid_valid"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_FLAG = "invalid_flag"
ERR_INVALID_IDENTITY = "invalid_identity"
ERR_INTERNAL = "validation_error"


def _same(left, right):
    """Type-strict deep equality (True != 1, tuple != list)."""
    if type(left) is not type(right):
        return False
    if type(left) is list:
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    if type(left) is dict:
        return (sorted(left, key=repr) == sorted(right, key=repr)
                and all(_same(left[k], right[k]) for k in left))
    return left == right


def _result(status, decision=None):
    """Result for a status; identity only for "valid" (taken from a trusted decision)."""
    ids = dict.fromkeys(IDENTITY_KEYS)
    if status == STATUS_VALID:
        ids = {key: decision[key] for key in IDENTITY_KEYS}
    out = {"version": RESULT_VERSION, "status": status, "valid": status == STATUS_VALID}
    out.update(ids)
    out.update({"reason": status, "execution_allowed": False, "executed": False})
    return out


def _id_ok(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


def _policy_eligible(policy):
    return (policy["status"] == "eligible" and policy["eligible"] is True
            and policy["implementation_allowed"] is False
            and policy["execution_allowed"] is False
            and policy["implementation_started"] is False
            and policy["executed"] is False)


def _validation_report_ok(report):
    """A well-formed Prompt 895 validation result that says valid, with no errors."""
    return (type(report) is dict and sorted(report, key=repr) == sorted(_VALIDATION_KEYS)
            and report["valid"] is True and type(report["errors"]) is list
            and report["errors"] == [] and report["execution_allowed"] is False
            and report["executed"] is False)


def validate_implementation_approval_decision_context(
        evolution_request=None, analysis_result=None, specification=None, plan=None,
        proposal=None, candidate=None, readiness_result=None, design=None,
        validation_result=None, blueprint=None, blueprint_validation_result=None,
        contract=None, contract_validation_result=None, contract_readiness_result=None,
        boundary_result=None, implementation_request=None, request_validation_result=None,
        policy=None, approval_request=None, approval_request_validation_result=None,
        decision=None):
    """Validation result for a pending-approval decision against the trusted chain."""
    try:
        report = validate_implementation_approval_decision(decision)
        if not report["valid"]:
            only_id = all(e["where"] == "decision_id" and e["code"] == "invalid_id"
                          for e in report["errors"])
            return _result(STATUS_INVALID_DECISION_ID if only_id
                           else STATUS_INVALID_DECISION)

        chain = (evolution_request, analysis_result, specification, plan, proposal,
                 candidate, readiness_result, design, validation_result, blueprint,
                 blueprint_validation_result, contract, contract_validation_result,
                 contract_readiness_result, boundary_result, implementation_request)
        derived = validate_capability_implementation_request_context(*chain)
        if not validate_capability_implementation_request_validation_result(
                derived)["valid"]:
            return _result(STATUS_ERROR)
        if derived["status"] != "valid":
            return _result(_CHAIN_STATUS.get(derived["status"],
                                             STATUS_INVALID_REQUEST_VALIDATION))

        supplied = request_validation_result
        if (not validate_capability_implementation_request_validation_result(
                supplied)["valid"] or supplied["status"] != "valid"
                or supplied["valid"] is not True):
            return _result(STATUS_INVALID_REQUEST_VALIDATION)
        if not _same(supplied, derived):
            return _result(STATUS_CONTEXT)

        if not validate_implementation_permission_policy(policy)["valid"]:
            return _result(STATUS_INVALID_REQUEST_VALIDATION)
        if not _policy_eligible(policy):
            return _result(STATUS_UNSUPPORTED)
        expected_policy = build_implementation_permission_policy(
            *chain, derived, policy["policy_id"])
        if expected_policy["status"] != "eligible" or not _same(policy, expected_policy):
            return _result(STATUS_CONTEXT)

        if (not validate_implementation_approval_request(approval_request)["valid"]
                or not _validation_report_ok(approval_request_validation_result)):
            return _result(STATUS_INVALID_APPROVAL_REQUEST_VALIDATION)
        expected_approval = build_implementation_approval_request(
            *chain, derived, policy, approval_request["approval_request_id"])
        if (expected_approval["status"] != "ready_for_approval"
                or not _same(approval_request, expected_approval["approval_request"])
                or not _same(approval_request_validation_result,
                             validate_implementation_approval_request(
                                 expected_approval["approval_request"]))):
            return _result(STATUS_CONTEXT)

        expected = build_implementation_approval_decision(
            *chain, derived, policy, approval_request, approval_request_validation_result,
            decision["decision_id"])
        if expected["status"] != PENDING or not _same(decision, expected["decision"]):
            return _result(STATUS_CONTEXT)

        request, impl, boundary = evolution_request, implementation_request, boundary_result
        pairs = ((decision["request_id"], request["request_id"]),
                 (decision["request_id"], derived["request_id"]),
                 (decision["implementation_request_id"], impl["implementation_request_id"]),
                 (decision["implementation_request_id"], derived["implementation_request_id"]),
                 (decision["approval_request_id"], approval_request["approval_request_id"]),
                 (decision["capability_name"], request["capability_name"]),
                 (decision["capability_name"], derived["capability_name"]),
                 (decision["operation"], request["operation"]),
                 (decision["operation"], derived["operation"]),
                 (approval_request["policy_status"], policy["status"]),
                 (derived["plan_id"], impl["plan_id"]),
                 (derived["contract_id"], impl["contract_id"]),
                 (derived["boundary_status"], impl["boundary_status"]),
                 (derived["boundary_status"], boundary["status"]),
                 (decision["approval_status"], PENDING))
        if any(not _same(a, b) for a, b in pairs):
            return _result(STATUS_CONTEXT)
        if decision["operation"] not in SUPPORTED_OPERATIONS:
            return _result(STATUS_UNSUPPORTED)
        return _result(STATUS_VALID, decision)
    except Exception:
        return _result(STATUS_ERROR)


def _result_errors(result):
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(result) is not dict:
        add(ERR_NOT_DICT, "result")
        return errors
    for key in RESULT_KEYS:
        if key not in result:
            add(ERR_MISSING_KEY, key)
    for key in result:
        if type(key) is not str or key not in RESULT_KEYS:
            add(ERR_UNEXPECTED_KEY,
                key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    if type(result["version"]) is not int or result["version"] != RESULT_VERSION:
        add(ERR_INVALID_VERSION, "version")
    status = result["status"]
    status_ok = type(status) is str and status in STATUSES
    if not status_ok:
        add(ERR_INVALID_STATUS, "status")
    if type(result["valid"]) is not bool or (status_ok and result["valid"]
                                             != (status == STATUS_VALID)):
        add(ERR_INVALID_VALID, "valid")
    if type(result["reason"]) is not str or (status_ok and result["reason"] != status):
        add(ERR_INVALID_REASON, "reason")
    for key in ("execution_allowed", "executed"):
        if result[key] is not False:
            add(ERR_INVALID_FLAG, key)
    if not status_ok:
        return errors

    if status != STATUS_VALID:
        for key in IDENTITY_KEYS:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors
    for key in ("decision_id", "implementation_request_id", "approval_request_id"):
        if not _id_ok(result[key]):
            add(ERR_INVALID_IDENTITY, key)
    view = {"version": "1", "request_id": result["request_id"],
            "operation": result["operation"], "capability_name": result["capability_name"],
            "goal": "g", "inputs": [], "outputs": ["o"], "constraints": [],
            "requested_by": "r", "execution_allowed": False}
    for error in validate_capability_evolution_request(view)["errors"]:
        if error["where"] in ("request_id", "capability_name", "operation"):
            add(ERR_INVALID_IDENTITY, error["where"])
    if result["operation"] not in SUPPORTED_OPERATIONS:
        add(ERR_INVALID_IDENTITY, "operation")
    return errors


def validate_implementation_approval_decision_validation_result(result=None):
    """Validation result for a normalized decision-validation result."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
