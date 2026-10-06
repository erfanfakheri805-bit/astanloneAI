"""
Approval Scope Context Validation (Prompt 900, Section 17: Controlled Autonomy)
===============================================================================
A deterministic, read-only VALIDATION BOUNDARY. It checks that the Prompt 899 approval
authority scope is contextually consistent with the existing Prompt 895 approval request and
the Prompt 896 / 897 approval-decision chain (and, through them, the Section 16 chain).

Validating a context is not approving it. Nothing here grants approval, creates an
authorization, permits implementation or execution, creates an "approved" state, executes
anything, generates code, modifies project files or capabilities, self-modifies, persists
anything, touches the filesystem, starts a subprocess, uses the network, uses an external AI /
API or authenticates against any account. There is no "approved" status, no approval field and
no permission state: implementation_allowed, execution_allowed and executed are ALWAYS False in
every result. A scope never grants permission: approval_capable may be True while
implementation_allowed and execution_allowed stay False.

  validate_approval_scope_context(authority_descriptor, scope_descriptor, evolution_request,
        analysis_result, specification, plan, proposal, candidate, readiness_result, design,
        validation_result, blueprint, blueprint_validation_result, contract,
        contract_validation_result, contract_readiness_result, boundary_result,
        implementation_request, request_validation_result, policy, approval_request,
        approval_request_validation_result, decision, decision_validation_result)
  validate_approval_scope_context_result(result)

Nothing supplied is trusted and nothing is re-implemented. The Prompt 898 validator judges the
authority, the Prompt 899 context validator judges the scope against the authority, the
Prompt 895 / 896 validators judge the approval request and decision, and the Prompt 897
context validation re-derives the whole chain (Prompt 892 chain, Prompt 894 policy, Prompt 895
approval request, Prompt 896 decision) and must agree with the supplied objects (type-strict),
so a forged but individually valid object never passes. Checks run in this fixed order; the
first failure decides the status:
   1 authority fails the Prompt 898 validator ........................ invalid_authority
     (it fails only because of an approval / status concept) ......... unsupported_status
   2 scope fails the Prompt 899 context validation ................... invalid_scope
     (scope names an approval concept / improve_or_conflict) ......... unsupported_status
     (scope authority_id or approval_capable differs from authority) . context_mismatch
   3 approval request fails the Prompt 895 validator (malformed, altered flags, altered
     policy_status) .................................................. invalid_approval_request
   4 decision fails the Prompt 896 validator (malformed, non-pending approval_status, altered
     flags or reason) ................................................ invalid_approval_decision
   5 supplied Prompt 897 result malformed or not "valid" ............. invalid_decision_validation
   (in 3-5: an unexpected key naming an approval / status concept such as "approved" or
    "authorization", an approval word as approval_status / status, or the operation
    "improve_or_conflict") ........................................... unsupported_status
   6 Prompt 897 context validation of the supplied objects is not valid:
       context_mismatch ............................................. context_mismatch
       unsupported_status ........................................... unsupported_status
       validation_error ............................................. validation_error
       invalid approval-request validation result ................... invalid_approval_request
       invalid decision / decision_id ............................... invalid_approval_decision
       any other invalid stage (request, Section 16 chain, policy) .. invalid_context
   7 supplied Prompt 897 result differs from the re-derived one
     (forged identity) ............................................... context_mismatch
   8 authority_id, scope_id-bound capability_name / operation, request_id,
     implementation_request_id, approval_request_id, decision_id, plan_id, contract_id,
     boundary_status or approval_status disagree across the stages ... context_mismatch
   9 everything holds ................................................ valid
Any unexpected internal failure -> validation_error. The vocabulary is exactly: valid,
invalid_authority, invalid_scope, invalid_approval_request, invalid_approval_decision,
invalid_decision_validation, invalid_context, context_mismatch, unsupported_status,
validation_error. None of them grants approval, authorization, permission or execution.

Result (exactly these fifteen keys, a fresh dict on every call, primitive values only):
  {"version", "status", "valid", "authority_id", "scope_id", "capability_name", "operation",
   "request_id", "implementation_request_id", "approval_request_id", "decision_id", "reason",
   "implementation_allowed", "execution_allowed", "executed"}
version is the integer 1; valid is True only for status "valid"; reason equals status;
implementation_allowed, execution_allowed and executed are ALWAYS False. The identity fields
are filled (from the trusted, validated objects) only for "valid" and are None for every other
status, so a rejected result never carries untrusted values.

validate_approval_scope_context_result(result) checks that exact shape and returns
{"valid", "errors", "execution_allowed", "executed"}; purely structural, read-only, never
raises. Inputs are never modified and never shared with a result.
"""

from capabilities.capability_evolution_proposal import validate_capability_evolution_proposal
from capabilities.capability_evolution_request import validate_capability_evolution_request
from capabilities.capability_implementation_request_validation import (
    validate_capability_implementation_request_context,
    validate_capability_implementation_request_validation_result)
from capabilities.capability_registry import MAX_ERRORS

from .approval_authority_scope import (
    validate_approval_authority_scope, validate_approval_authority_scope_context)
from .approval_authority_source import (
    DESCRIPTOR_KEYS as AUTHORITY_KEYS, validate_approval_authority_source)
from .implementation_approval_decision import (
    FIELDS as DECISION_FIELDS, validate_implementation_approval_decision)
from .implementation_approval_decision_validation import (
    RESULT_KEYS as DECISION_RESULT_KEYS,
    validate_implementation_approval_decision_context,
    validate_implementation_approval_decision_validation_result)
from .implementation_approval_request import (
    FIELDS as APPROVAL_REQUEST_FIELDS, validate_implementation_approval_request)

RESULT_VERSION = 1

STATUS_VALID = "valid"
STATUS_INVALID_AUTHORITY = "invalid_authority"
STATUS_INVALID_SCOPE = "invalid_scope"
STATUS_INVALID_APPROVAL_REQUEST = "invalid_approval_request"
STATUS_INVALID_APPROVAL_DECISION = "invalid_approval_decision"
STATUS_INVALID_DECISION_VALIDATION = "invalid_decision_validation"
STATUS_INVALID_CONTEXT = "invalid_context"
STATUS_CONTEXT = "context_mismatch"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_VALID, STATUS_INVALID_AUTHORITY, STATUS_INVALID_SCOPE,
            STATUS_INVALID_APPROVAL_REQUEST, STATUS_INVALID_APPROVAL_DECISION,
            STATUS_INVALID_DECISION_VALIDATION, STATUS_INVALID_CONTEXT, STATUS_CONTEXT,
            STATUS_UNSUPPORTED, STATUS_ERROR)

RESULT_KEYS = ("version", "status", "valid", "authority_id", "scope_id", "capability_name",
               "operation", "request_id", "implementation_request_id", "approval_request_id",
               "decision_id", "reason", "implementation_allowed", "execution_allowed",
               "executed")
IDENTITY_KEYS = ("authority_id", "scope_id", "capability_name", "operation", "request_id",
                 "implementation_request_id", "approval_request_id", "decision_id")
FALSE_FLAGS = ("implementation_allowed", "execution_allowed", "executed")
SUPPORTED_OPERATIONS = ("create", "improve")
PENDING = "pending_approval"
POLICY_ELIGIBLE = "eligible"

# Approval / status concepts. They are not fields or values of any supported object.
_APPROVAL_WORDS = frozenset((
    "approved", "approval", "approval_status", "approved_by", "authorization", "authorisation",
    "authorized", "authorised", "granted", "allowed", "permitted", "permission", "status"))
_UNSUPPORTED_OPERATION = "improve_or_conflict"

# Prompt 897 status -> status of this boundary (any other one becomes invalid_context)
_DECISION_VALIDATION_STATUS = {
    "context_mismatch": STATUS_CONTEXT,
    "unsupported_status": STATUS_UNSUPPORTED,
    "validation_error": STATUS_ERROR,
    "invalid_approval_request_validation": STATUS_INVALID_APPROVAL_REQUEST,
    "invalid_decision": STATUS_INVALID_APPROVAL_DECISION,
    "invalid_decision_id": STATUS_INVALID_APPROVAL_DECISION,
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

# A fixed, valid Prompt 899 scope used only to judge one label at a time.
_PROBE = {"version": 1, "scope_id": "label_check", "authority_id": "label_check",
          "capability_name": "label_check", "operation": "create",
          "scope": "label_check", "purpose": "label_check", "approval_capable": False,
          "implementation_allowed": False, "execution_allowed": False}


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


def _result(status, identity=None):
    """Result for a status; identity only for "valid" (taken from trusted objects)."""
    ids = dict.fromkeys(IDENTITY_KEYS)
    if status == STATUS_VALID:
        ids = {key: identity[key] for key in IDENTITY_KEYS}
    out = {"version": RESULT_VERSION, "status": status, "valid": status == STATUS_VALID}
    out.update(ids)
    out.update({"reason": status, "implementation_allowed": False,
                "execution_allowed": False, "executed": False})
    return out


def _id_ok(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


def _word(value):
    return type(value) is str and value.strip().lower() in _APPROVAL_WORDS


def _unsupported(value, fields, status_key=None):
    """True if a dict names an approval concept, or carries improve_or_conflict.

    An unexpected key that is an approval / status word ("approved", "authorization" ...),
    an approval word as the value of `status_key`, or the operation "improve_or_conflict".
    """
    if type(value) is not dict:
        return False
    for key in value:
        if type(key) is str and key not in fields and _word(key):
            return True
    operation = value.get("operation")
    if type(operation) is str and operation == _UNSUPPORTED_OPERATION:
        return True
    return status_key is not None and _word(value.get(status_key))


def _evaluate(authority, scope, chain, request_validation_result, policy, approval_request,
              approval_request_validation_result, decision, decision_validation_result):
    """(status, identity) for the whole context; the first failing check decides."""
    # 1 authority
    authority_status = validate_approval_authority_source(authority)["status"]
    if authority_status != "valid":
        unsupported = (authority_status == "unsupported_status"
                       or _unsupported(authority, AUTHORITY_KEYS, "authority_type"))
        return (STATUS_UNSUPPORTED if unsupported else STATUS_INVALID_AUTHORITY), None

    # 2 scope, judged by the Prompt 899 validator against the authority
    scope_status = validate_approval_authority_scope_context(authority, scope)["status"]
    if scope_status == "unsupported_status":
        return STATUS_UNSUPPORTED, None
    if scope_status == "context_mismatch":
        return STATUS_CONTEXT, None
    if scope_status != "valid":
        return STATUS_INVALID_SCOPE, None

    # 3 approval request, 4 decision, 5 supplied Prompt 897 result (shape only)
    if _unsupported(approval_request, APPROVAL_REQUEST_FIELDS):
        return STATUS_UNSUPPORTED, None
    if not validate_implementation_approval_request(approval_request)["valid"]:
        return STATUS_INVALID_APPROVAL_REQUEST, None
    if _unsupported(decision, DECISION_FIELDS, "approval_status"):
        return STATUS_UNSUPPORTED, None
    if not validate_implementation_approval_decision(decision)["valid"]:
        return STATUS_INVALID_APPROVAL_DECISION, None
    if _unsupported(decision_validation_result, DECISION_RESULT_KEYS, "status"):
        return STATUS_UNSUPPORTED, None
    if (not validate_implementation_approval_decision_validation_result(
            decision_validation_result)["valid"]
            or decision_validation_result["status"] != "valid"
            or decision_validation_result["valid"] is not True):
        return STATUS_INVALID_DECISION_VALIDATION, None

    # 6 the Prompt 897 context validation re-derives the whole trusted chain
    expected = validate_implementation_approval_decision_context(
        *chain, request_validation_result, policy, approval_request,
        approval_request_validation_result, decision)
    if not validate_implementation_approval_decision_validation_result(expected)["valid"]:
        return STATUS_ERROR, None
    if expected["status"] != "valid":
        return _DECISION_VALIDATION_STATUS.get(expected["status"],
                                               STATUS_INVALID_CONTEXT), None

    # 7 the supplied Prompt 897 result must equal the re-derived one
    if not _same(decision_validation_result, expected):
        return STATUS_CONTEXT, None

    # 8 identity across the stages (Section 16 identity comes from the re-derived result)
    derived = validate_capability_implementation_request_context(*chain)
    if (not validate_capability_implementation_request_validation_result(derived)["valid"]
            or derived["status"] != "valid"):
        return STATUS_ERROR, None
    request, boundary, impl = chain[0], chain[14], chain[15]
    dres = decision_validation_result
    pairs = (
        (scope["authority_id"], authority["authority_id"]),
        (scope["capability_name"], decision["capability_name"]),
        (scope["capability_name"], approval_request["capability_name"]),
        (scope["capability_name"], impl["capability_name"]),
        (scope["capability_name"], request["capability_name"]),
        (scope["capability_name"], derived["capability_name"]),
        (scope["capability_name"], dres["capability_name"]),
        (scope["operation"], decision["operation"]),
        (scope["operation"], approval_request["operation"]),
        (scope["operation"], impl["operation"]),
        (scope["operation"], request["operation"]),
        (scope["operation"], derived["operation"]),
        (scope["operation"], dres["operation"]),
        (decision["request_id"], approval_request["request_id"]),
        (decision["request_id"], request["request_id"]),
        (decision["request_id"], impl["request_id"]),
        (decision["request_id"], derived["request_id"]),
        (decision["request_id"], dres["request_id"]),
        (decision["implementation_request_id"], approval_request["implementation_request_id"]),
        (decision["implementation_request_id"], impl["implementation_request_id"]),
        (decision["implementation_request_id"], derived["implementation_request_id"]),
        (decision["implementation_request_id"], dres["implementation_request_id"]),
        (decision["approval_request_id"], approval_request["approval_request_id"]),
        (decision["approval_request_id"], dres["approval_request_id"]),
        (decision["decision_id"], dres["decision_id"]),
        (derived["plan_id"], impl["plan_id"]),
        (derived["contract_id"], impl["contract_id"]),
        (derived["boundary_status"], impl["boundary_status"]),
        (derived["boundary_status"], boundary["status"]),
        (decision["approval_status"], PENDING),
        (approval_request["policy_status"], POLICY_ELIGIBLE),
        (approval_request["policy_status"], policy["status"]))
    if any(not _same(left, right) for left, right in pairs):
        return STATUS_CONTEXT, None
    if scope["operation"] not in SUPPORTED_OPERATIONS:
        return STATUS_UNSUPPORTED, None

    identity = {"authority_id": authority["authority_id"], "scope_id": scope["scope_id"],
                "capability_name": decision["capability_name"],
                "operation": decision["operation"], "request_id": decision["request_id"],
                "implementation_request_id": decision["implementation_request_id"],
                "approval_request_id": decision["approval_request_id"],
                "decision_id": decision["decision_id"]}
    return STATUS_VALID, identity


def validate_approval_scope_context(
        authority_descriptor=None, scope_descriptor=None, evolution_request=None,
        analysis_result=None, specification=None, plan=None, proposal=None, candidate=None,
        readiness_result=None, design=None, validation_result=None, blueprint=None,
        blueprint_validation_result=None, contract=None, contract_validation_result=None,
        contract_readiness_result=None, boundary_result=None, implementation_request=None,
        request_validation_result=None, policy=None, approval_request=None,
        approval_request_validation_result=None, decision=None,
        decision_validation_result=None):
    """Validation result for a scope against the trusted approval chain (grants nothing)."""
    try:
        chain = (evolution_request, analysis_result, specification, plan, proposal,
                 candidate, readiness_result, design, validation_result, blueprint,
                 blueprint_validation_result, contract, contract_validation_result,
                 contract_readiness_result, boundary_result, implementation_request)
        status, identity = _evaluate(
            authority_descriptor, scope_descriptor, chain, request_validation_result, policy,
            approval_request, approval_request_validation_result, decision,
            decision_validation_result)
        return _result(status, identity)
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
    for key in FALSE_FLAGS:
        if result[key] is not False:
            add(ERR_INVALID_FLAG, key)
    if not status_ok:
        return errors

    if status != STATUS_VALID:
        for key in IDENTITY_KEYS:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors

    # labels are judged by the Prompt 899 validator, one at a time, in a fixed valid scope
    for key in ("authority_id", "scope_id", "capability_name", "operation"):
        probe = dict(_PROBE)
        probe[key] = result[key]
        if validate_approval_authority_scope(probe)["status"] != "valid":
            add(ERR_INVALID_IDENTITY, key)
    if result["operation"] not in SUPPORTED_OPERATIONS:
        add(ERR_INVALID_IDENTITY, "operation")
    for key in ("implementation_request_id", "approval_request_id", "decision_id"):
        if not _id_ok(result[key]):
            add(ERR_INVALID_IDENTITY, key)
    view = {"version": "1", "request_id": result["request_id"], "operation": "create",
            "capability_name": result["capability_name"], "goal": "g", "inputs": [],
            "outputs": ["o"], "constraints": [], "requested_by": "r",
            "execution_allowed": False}
    for error in validate_capability_evolution_request(view)["errors"]:
        if error["where"] in ("request_id", "capability_name"):
            add(ERR_INVALID_IDENTITY, error["where"])
    return errors


def validate_approval_scope_context_result(result=None):
    """Validation result for a normalized scope-context validation result."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
