"""
Implementation Approval Request (Prompt 895, Section 17: Controlled Autonomy)
==============================================================================
A deterministic, read-only REQUEST CONTRACT meaning only:

    "an implementation request has passed the eligibility policy and may now be SUBMITTED
     for controlled approval."

It is not an approval, not an implementation permission and not an execution permission.
Creating it starts nothing: approval_required is True, while implementation_allowed,
execution_allowed, implementation_started and executed are ALWAYS False. Nothing is
generated, patched, written, registered, installed, persisted, executed, researched,
networked, sent to an API / model, approved automatically or self-modified. Caller data is
never normalized, altered or repaired (everything is copied into fresh objects).

  build_implementation_approval_request(evolution_request, analysis_result, specification,
        plan, proposal, candidate, readiness_result, design, validation_result, blueprint,
        blueprint_validation_result, contract, contract_validation_result,
        contract_readiness_result, boundary_result, implementation_request,
        request_validation_result, policy, approval_request_id=None)
  validate_implementation_approval_request(request)

Eligibility is never taken from the caller: the Prompt 892 context validation re-derives the
verdict on the whole chain (reusing the Prompt 876-891 validators and the Prompt 890
boundary), and the Prompt 894 builder re-derives the policy from that chain. Nothing is
re-implemented here. Checks run in this fixed order; the first failure decides the status:
   1 Prompt 892 chain evaluation of the supplied objects
       invalid_request, invalid_implementation_request        invalid_request
       invalid_boundary                                       invalid_boundary
       invalid_contract_readiness                             invalid_contract_readiness
       context_mismatch                                       context_mismatch
       unsupported_status (e.g. improve_or_conflict)          unsupported_status
       validation_error                                       validation_error
       any other invalid stage of the chain (876-889)         invalid_request_validation
   2 supplied Prompt 892 result malformed / not "valid"       invalid_request_validation
   3 supplied Prompt 892 result differs from the derived one  context_mismatch
   4 policy fails the Prompt 894 validator, or its status is not "eligible" /
     eligible is not True (ineligible, blocked, unsupported, invalid ... policies)
                                                              invalid_policy
   5 policy differs from the Prompt 894 policy re-derived from the chain (forged)
                                                              context_mismatch
   6 approval_request_id missing / invalid                    invalid_approval_request_id
   7 request / implementation request / policy identity disagree
                                                              context_mismatch
   8 operation not create / improve                           unsupported_status
   9 built request fails its validator                        approval_request_error
  10 determination                                            ready_for_approval
Any unexpected internal failure -> validation_error. There is no "approved" status and no
status that grants permission; "ready_for_approval" is the only success status.

approval_request_id is caller-supplied (text, <= 64 chars, the request-id rule), never
generated.

Normalized approval request (exactly these seventeen keys):
  {"version", "approval_request_id", "request_id", "implementation_request_id",
   "capability_name", "operation", "policy_status", "purpose", "inputs", "outputs",
   "constraints", "existing_capability", "approval_required", "implementation_allowed",
   "execution_allowed", "implementation_started", "executed"}
version is the integer 1; policy_status is "eligible"; purpose / inputs / outputs /
constraints / existing_capability are deep copies of the trusted Prompt 891 request.

Builder result (exactly these keys, fresh every call):
  {"status", "approval_request", "execution_allowed", "executed"}
approval_request is set only for "ready_for_approval" (else None); both flags are False.
"""

import copy

from capabilities.capability_evolution_proposal import validate_capability_evolution_proposal
from capabilities.capability_implementation_request import (
    validate_capability_implementation_request)
from capabilities.capability_implementation_request_validation import (
    validate_capability_implementation_request_context,
    validate_capability_implementation_request_validation_result)
from capabilities.capability_registry import MAX_ERRORS

from .implementation_permission_policy import (
    build_implementation_permission_policy, validate_implementation_permission_policy)

APPROVAL_REQUEST_VERSION = 1

STATUS_READY = "ready_for_approval"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_REQUEST_VALIDATION = "invalid_request_validation"
STATUS_INVALID_BOUNDARY = "invalid_boundary"
STATUS_INVALID_CONTRACT_READINESS = "invalid_contract_readiness"
STATUS_INVALID_POLICY = "invalid_policy"
STATUS_CONTEXT = "context_mismatch"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_INVALID_APPROVAL_REQUEST_ID = "invalid_approval_request_id"
STATUS_APPROVAL_REQUEST_ERROR = "approval_request_error"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_INVALID_REQUEST, STATUS_INVALID_REQUEST_VALIDATION,
            STATUS_INVALID_BOUNDARY, STATUS_INVALID_CONTRACT_READINESS,
            STATUS_INVALID_POLICY, STATUS_CONTEXT, STATUS_UNSUPPORTED,
            STATUS_INVALID_APPROVAL_REQUEST_ID, STATUS_APPROVAL_REQUEST_ERROR,
            STATUS_ERROR)

FIELDS = ("version", "approval_request_id", "request_id", "implementation_request_id",
          "capability_name", "operation", "policy_status", "purpose", "inputs", "outputs",
          "constraints", "existing_capability", "approval_required",
          "implementation_allowed", "execution_allowed", "implementation_started",
          "executed")
RESULT_KEYS = ("status", "approval_request", "execution_allowed", "executed")
FALSE_FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started",
               "executed")

SUPPORTED_OPERATIONS = ("create", "improve")
POLICY_STATUS = "eligible"
_ANALYSIS_STATUS = {"create": "create_required", "improve": "improve_required"}

# Prompt 892 status -> approval request status (any other invalid stage of the chain
# becomes invalid_request_validation)
_CHAIN_STATUS = {
    "invalid_request": STATUS_INVALID_REQUEST,
    "invalid_implementation_request": STATUS_INVALID_REQUEST,
    "invalid_boundary": STATUS_INVALID_BOUNDARY,
    "invalid_contract_readiness": STATUS_INVALID_CONTRACT_READINESS,
    "context_mismatch": STATUS_CONTEXT,
    "unsupported_status": STATUS_UNSUPPORTED,
    "validation_error": STATUS_ERROR,
}

ERR_NOT_DICT = "request_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_APPROVAL_REQUEST_ID = "invalid_approval_request_id"
ERR_INVALID_POLICY_STATUS = "invalid_policy_status"
ERR_INVALID_FLAG = "invalid_flag"
ERR_INCONSISTENT = "inconsistent_approval_request"
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


def _build_result(status, approval_request=None):
    return {"status": status, "approval_request": approval_request,
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
    return (policy["status"] == POLICY_STATUS and policy["eligible"] is True
            and policy["implementation_allowed"] is False
            and policy["execution_allowed"] is False
            and policy["implementation_started"] is False
            and policy["executed"] is False)


def build_implementation_approval_request(
        evolution_request=None, analysis_result=None, specification=None, plan=None,
        proposal=None, candidate=None, readiness_result=None, design=None,
        validation_result=None, blueprint=None, blueprint_validation_result=None,
        contract=None, contract_validation_result=None, contract_readiness_result=None,
        boundary_result=None, implementation_request=None, request_validation_result=None,
        policy=None, approval_request_id=None):
    """Approval request for an eligible implementation request (read-only, no permission)."""
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
        if expected_policy["status"] != POLICY_STATUS or not _same(policy, expected_policy):
            return _build_result(STATUS_CONTEXT)

        if approval_request_id is None or not _id_ok(approval_request_id):
            return _build_result(STATUS_INVALID_APPROVAL_REQUEST_ID)

        request, impl = evolution_request, implementation_request
        pairs = ((policy["request_id"], request["request_id"]),
                 (policy["request_id"], impl["request_id"]),
                 (policy["implementation_request_id"], impl["implementation_request_id"]),
                 (policy["capability_name"], request["capability_name"]),
                 (policy["capability_name"], impl["capability_name"]),
                 (policy["operation"], request["operation"]),
                 (policy["operation"], impl["operation"]))
        if any(not _same(a, b) for a, b in pairs):
            return _build_result(STATUS_CONTEXT)
        if impl["operation"] not in SUPPORTED_OPERATIONS:
            return _build_result(STATUS_UNSUPPORTED)

        approval = {
            "version": APPROVAL_REQUEST_VERSION,
            "approval_request_id": approval_request_id,
            "request_id": impl["request_id"],
            "implementation_request_id": impl["implementation_request_id"],
            "capability_name": impl["capability_name"],
            "operation": impl["operation"],
            "policy_status": policy["status"],
            "purpose": impl["purpose"],
            "inputs": copy.deepcopy(impl["inputs"]),
            "outputs": copy.deepcopy(impl["outputs"]),
            "constraints": copy.deepcopy(impl["constraints"]),
            "existing_capability": copy.deepcopy(impl["existing_capability"]),
            "approval_required": True,
            "implementation_allowed": False,
            "execution_allowed": False,
            "implementation_started": False,
            "executed": False,
        }
        if not validate_implementation_approval_request(approval)["valid"]:
            return _build_result(STATUS_APPROVAL_REQUEST_ERROR)
        return _build_result(STATUS_READY, approval)
    except Exception:
        return _build_result(STATUS_ERROR)


def _implementation_view(request):
    """A Prompt 891-shaped view carrying the shared fields of an approval request."""
    return {"version": 1, "implementation_request_id": request["implementation_request_id"],
            "request_id": request["request_id"], "capability_name": request["capability_name"],
            "operation": request["operation"],
            "analysis_status": _ANALYSIS_STATUS[request["operation"]],
            "plan_id": "p", "contract_id": "c", "boundary_status": "ready",
            "purpose": request["purpose"], "inputs": request["inputs"],
            "outputs": request["outputs"], "constraints": request["constraints"],
            "existing_capability": request["existing_capability"],
            "implementation_allowed": False, "execution_allowed": False}


_SHARED = ("implementation_request_id", "request_id", "capability_name", "operation",
           "purpose", "inputs", "outputs", "constraints", "existing_capability")


def _request_errors(request):
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(request) is not dict:
        add(ERR_NOT_DICT, "request")
        return errors
    for key in FIELDS:
        if key not in request:
            add(ERR_MISSING_KEY, key)
    for key in request:
        if type(key) is not str or key not in FIELDS:
            add(ERR_UNEXPECTED_KEY,
                key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    if type(request["version"]) is not int or request["version"] != APPROVAL_REQUEST_VERSION:
        add(ERR_INVALID_VERSION, "version")
    if not _id_ok(request["approval_request_id"]):
        add(ERR_INVALID_APPROVAL_REQUEST_ID, "approval_request_id")
    if type(request["policy_status"]) is not str or request["policy_status"] != POLICY_STATUS:
        add(ERR_INVALID_POLICY_STATUS, "policy_status")
    if request["approval_required"] is not True:
        add(ERR_INVALID_FLAG, "approval_required")
    for key in FALSE_FLAGS:
        if request[key] is not False:
            add(ERR_INVALID_FLAG, key)

    operation = request["operation"]
    if type(operation) is not str or operation not in SUPPORTED_OPERATIONS:
        add(ERR_INCONSISTENT, "operation")
        return errors
    # shared fields (ids, name, operation, purpose, inputs, outputs, constraints, existing
    # capability and their consistency) are checked by the Prompt 891 validator
    for error in validate_capability_implementation_request(
            _implementation_view(request))["errors"]:
        if error["where"] in _SHARED:
            add(error["code"], error["where"])
    return errors


def validate_implementation_approval_request(request=None):
    """Validation result for a normalized implementation approval request."""
    try:
        errors = _request_errors(request)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "request"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
