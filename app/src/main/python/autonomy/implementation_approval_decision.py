"""
Implementation Approval Decision (Prompt 896, Section 17: Controlled Autonomy)
==============================================================================
A deterministic, read-only DECISION-STATE CONTRACT. It represents the state of an
implementation approval request BEFORE any approval decision is made:

    "an approval decision has NOT yet been made"  ->  approval_status "pending_approval"

Prompt 896 creates an approval-decision state, not an approval mechanism. There is no
"approved" status, no approval field, no user approval, no AEL approval and no automatic
approval. approval_required is True; implementation_allowed, execution_allowed,
implementation_started and executed are ALWAYS False. Nothing is generated, patched,
written, registered, installed, persisted, executed, researched, networked, sent to an API /
model, approved or self-modified. Caller data is never normalized, altered or repaired
(everything is copied into fresh objects).

  build_implementation_approval_decision(evolution_request, analysis_result, specification,
        plan, proposal, candidate, readiness_result, design, validation_result, blueprint,
        blueprint_validation_result, contract, contract_validation_result,
        contract_readiness_result, boundary_result, implementation_request,
        request_validation_result, policy, approval_request,
        approval_request_validation_result, decision_id=None)
  validate_implementation_approval_decision(decision)

Nothing supplied by the caller is trusted. The Prompt 892 context validation re-derives the
verdict on the whole chain (reusing the Prompt 876-891 validators and the Prompt 890
boundary), the Prompt 894 builder re-derives the policy, and the Prompt 895 builder
re-derives the approval request; the supplied objects must equal the derived ones
(type-strict), so a forged but individually valid object never passes. Checks run in this
fixed order; the first failure decides the status:
   1 Prompt 892 chain evaluation of the supplied objects
       invalid_request, invalid_implementation_request        invalid_request
       context_mismatch                                       context_mismatch
       unsupported_status (e.g. improve_or_conflict)          unsupported_status
       validation_error                                       validation_error
       any other invalid stage (876-890, boundary, readiness) invalid_request_validation
   2 supplied Prompt 892 result malformed / not "valid"       invalid_request_validation
   3 supplied Prompt 892 result differs from the derived one  context_mismatch
   4 policy fails the Prompt 894 validator or is not "eligible" (ineligible, blocked,
     unsupported, invalid ... policies)                       invalid_policy
   5 policy differs from the re-derived Prompt 894 policy     context_mismatch
   6 approval request fails the Prompt 895 validator          invalid_approval_request
   7 supplied Prompt 895 validation result malformed or not valid
                                                              invalid_approval_request_validation
   8 re-derived Prompt 895 builder status is not "ready_for_approval", or the supplied
     approval request / validation result differ from the derived ones
                                                              context_mismatch
   9 decision_id missing / invalid                            invalid_decision_id
  10 identity of chain / policy / approval request disagrees  context_mismatch
  11 operation not create / improve                           unsupported_status
  12 built decision fails its validator                       decision_error
  13 determination                                            pending_approval
Any unexpected internal failure -> validation_error.

decision_id is caller-supplied (text, <= 64 chars, the request-id rule), never generated.

Normalized decision (exactly these fourteen keys):
  {"version", "decision_id", "request_id", "implementation_request_id",
   "approval_request_id", "capability_name", "operation", "approval_status",
   "approval_required", "implementation_allowed", "execution_allowed",
   "implementation_started", "executed", "reason"}
version is the integer 1; approval_status is "pending_approval"; reason is
"approval_decision_not_made"; approval_required is True; the four flags are False.

Builder result (exactly these keys, fresh every call):
  {"status", "decision", "execution_allowed", "executed"}
decision is set only for "pending_approval" (else None); both flags are False.
"""

from capabilities.capability_evolution_proposal import validate_capability_evolution_proposal
from capabilities.capability_evolution_request import validate_capability_evolution_request
from capabilities.capability_implementation_request_validation import (
    validate_capability_implementation_request_context,
    validate_capability_implementation_request_validation_result)
from capabilities.capability_registry import MAX_ERRORS

from .implementation_approval_request import (
    build_implementation_approval_request, validate_implementation_approval_request)
from .implementation_permission_policy import (
    build_implementation_permission_policy, validate_implementation_permission_policy)

DECISION_VERSION = 1

STATUS_PENDING = "pending_approval"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_REQUEST_VALIDATION = "invalid_request_validation"
STATUS_INVALID_POLICY = "invalid_policy"
STATUS_INVALID_APPROVAL_REQUEST = "invalid_approval_request"
STATUS_INVALID_APPROVAL_REQUEST_VALIDATION = "invalid_approval_request_validation"
STATUS_CONTEXT = "context_mismatch"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_INVALID_DECISION_ID = "invalid_decision_id"
STATUS_DECISION_ERROR = "decision_error"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_PENDING, STATUS_INVALID_REQUEST, STATUS_INVALID_REQUEST_VALIDATION,
            STATUS_INVALID_POLICY, STATUS_INVALID_APPROVAL_REQUEST,
            STATUS_INVALID_APPROVAL_REQUEST_VALIDATION, STATUS_CONTEXT,
            STATUS_UNSUPPORTED, STATUS_INVALID_DECISION_ID, STATUS_DECISION_ERROR,
            STATUS_ERROR)

FIELDS = ("version", "decision_id", "request_id", "implementation_request_id",
          "approval_request_id", "capability_name", "operation", "approval_status",
          "approval_required", "implementation_allowed", "execution_allowed",
          "implementation_started", "executed", "reason")
RESULT_KEYS = ("status", "decision", "execution_allowed", "executed")
FALSE_FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started",
               "executed")

SUPPORTED_OPERATIONS = ("create", "improve")
APPROVAL_STATUS = "pending_approval"
REASON = "approval_decision_not_made"
_VALIDATION_KEYS = ("valid", "errors", "execution_allowed", "executed")

_CHAIN_STATUS = {
    "invalid_request": STATUS_INVALID_REQUEST,
    "invalid_implementation_request": STATUS_INVALID_REQUEST,
    "context_mismatch": STATUS_CONTEXT,
    "unsupported_status": STATUS_UNSUPPORTED,
    "validation_error": STATUS_ERROR,
}

ERR_NOT_DICT = "decision_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_ID = "invalid_id"
ERR_INVALID_STATUS = "invalid_approval_status"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_FLAG = "invalid_flag"
ERR_INCONSISTENT = "inconsistent_decision"
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


def _build_result(status, decision=None):
    return {"status": status, "decision": decision,
            "execution_allowed": False, "executed": False}


def _id_ok(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


def _policy_ok(policy):
    """A structurally valid Prompt 894 policy that is eligible and grants nothing."""
    if not validate_implementation_permission_policy(policy)["valid"]:
        return False
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


def build_implementation_approval_decision(
        evolution_request=None, analysis_result=None, specification=None, plan=None,
        proposal=None, candidate=None, readiness_result=None, design=None,
        validation_result=None, blueprint=None, blueprint_validation_result=None,
        contract=None, contract_validation_result=None, contract_readiness_result=None,
        boundary_result=None, implementation_request=None, request_validation_result=None,
        policy=None, approval_request=None, approval_request_validation_result=None,
        decision_id=None):
    """Pending-approval decision state for an approval request (no approval, no permission)."""
    try:
        chain = (evolution_request, analysis_result, specification, plan, proposal,
                 candidate, readiness_result, design, validation_result, blueprint,
                 blueprint_validation_result, contract, contract_validation_result,
                 contract_readiness_result, boundary_result, implementation_request)
        derived = validate_capability_implementation_request_context(*chain)
        if not validate_capability_implementation_request_validation_result(
                derived)["valid"]:
            return _build_result(STATUS_ERROR)
        if derived["status"] != "valid":
            return _build_result(_CHAIN_STATUS.get(derived["status"],
                                                   STATUS_INVALID_REQUEST_VALIDATION))

        supplied = request_validation_result
        if (not validate_capability_implementation_request_validation_result(
                supplied)["valid"] or supplied["status"] != "valid"
                or supplied["valid"] is not True):
            return _build_result(STATUS_INVALID_REQUEST_VALIDATION)
        if not _same(supplied, derived):
            return _build_result(STATUS_CONTEXT)

        if not _policy_ok(policy):
            return _build_result(STATUS_INVALID_POLICY)
        expected_policy = build_implementation_permission_policy(
            *chain, derived, policy["policy_id"])
        if expected_policy["status"] != "eligible" or not _same(policy, expected_policy):
            return _build_result(STATUS_CONTEXT)

        if not validate_implementation_approval_request(approval_request)["valid"]:
            return _build_result(STATUS_INVALID_APPROVAL_REQUEST)
        if not _validation_report_ok(approval_request_validation_result):
            return _build_result(STATUS_INVALID_APPROVAL_REQUEST_VALIDATION)
        expected = build_implementation_approval_request(
            *chain, derived, policy, approval_request["approval_request_id"])
        if (expected["status"] != "ready_for_approval"
                or not _same(approval_request, expected["approval_request"])
                or not _same(approval_request_validation_result,
                             validate_implementation_approval_request(
                                 expected["approval_request"]))):
            return _build_result(STATUS_CONTEXT)

        if decision_id is None or not _id_ok(decision_id):
            return _build_result(STATUS_INVALID_DECISION_ID)

        request, impl = evolution_request, implementation_request
        pairs = ((approval_request["request_id"], request["request_id"]),
                 (approval_request["request_id"], policy["request_id"]),
                 (approval_request["implementation_request_id"],
                  impl["implementation_request_id"]),
                 (approval_request["implementation_request_id"],
                  policy["implementation_request_id"]),
                 (approval_request["capability_name"], impl["capability_name"]),
                 (approval_request["capability_name"], policy["capability_name"]),
                 (approval_request["operation"], request["operation"]),
                 (approval_request["operation"], policy["operation"]),
                 (approval_request["policy_status"], policy["status"]))
        if any(not _same(a, b) for a, b in pairs):
            return _build_result(STATUS_CONTEXT)
        if approval_request["operation"] not in SUPPORTED_OPERATIONS:
            return _build_result(STATUS_UNSUPPORTED)

        decision = {
            "version": DECISION_VERSION,
            "decision_id": decision_id,
            "request_id": approval_request["request_id"],
            "implementation_request_id": approval_request["implementation_request_id"],
            "approval_request_id": approval_request["approval_request_id"],
            "capability_name": approval_request["capability_name"],
            "operation": approval_request["operation"],
            "approval_status": APPROVAL_STATUS,
            "approval_required": True,
            "implementation_allowed": False,
            "execution_allowed": False,
            "implementation_started": False,
            "executed": False,
            "reason": REASON,
        }
        if not validate_implementation_approval_decision(decision)["valid"]:
            return _build_result(STATUS_DECISION_ERROR)
        return _build_result(STATUS_PENDING, decision)
    except Exception:
        return _build_result(STATUS_ERROR)


def _decision_errors(decision):
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(decision) is not dict:
        add(ERR_NOT_DICT, "decision")
        return errors
    for key in FIELDS:
        if key not in decision:
            add(ERR_MISSING_KEY, key)
    for key in decision:
        if type(key) is not str or key not in FIELDS:
            add(ERR_UNEXPECTED_KEY,
                key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    if type(decision["version"]) is not int or decision["version"] != DECISION_VERSION:
        add(ERR_INVALID_VERSION, "version")
    for key in ("decision_id", "implementation_request_id", "approval_request_id"):
        if not _id_ok(decision[key]):
            add(ERR_INVALID_ID, key)
    if (type(decision["approval_status"]) is not str
            or decision["approval_status"] != APPROVAL_STATUS):
        add(ERR_INVALID_STATUS, "approval_status")
    if type(decision["reason"]) is not str or decision["reason"] != REASON:
        add(ERR_INVALID_REASON, "reason")
    if decision["approval_required"] is not True:
        add(ERR_INVALID_FLAG, "approval_required")
    for key in FALSE_FLAGS:
        if decision[key] is not False:
            add(ERR_INVALID_FLAG, key)

    operation = decision["operation"]
    if type(operation) is not str or operation not in SUPPORTED_OPERATIONS:
        add(ERR_INCONSISTENT, "operation")
    view = {"version": "1", "request_id": decision["request_id"], "operation": "create",
            "capability_name": decision["capability_name"], "goal": "g", "inputs": [],
            "outputs": ["o"], "constraints": [], "requested_by": "r",
            "execution_allowed": False}
    for error in validate_capability_evolution_request(view)["errors"]:
        if error["where"] in ("request_id", "capability_name"):
            add(ERR_INVALID_ID, error["where"])
    return errors


def validate_implementation_approval_decision(decision=None):
    """Validation result for a normalized implementation approval decision."""
    try:
        errors = _decision_errors(decision)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "decision"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
