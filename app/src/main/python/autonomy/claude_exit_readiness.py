"""
Claude Exit Readiness Contract (Prompt 902, Section 18: Claude Exit / Autonomy Validation)
==========================================================================================
The first Section 18 contract. A deterministic, read-only DESCRIPTION of whether a
capability-evolution request is structurally ready to continue to the next controlled
internal stage without asking Claude (an external builder) to design the missing architecture.

This is NOT autonomous execution. Nothing here implements, generates code, modifies a project
file or capability, self-modifies, persists, executes, touches the filesystem, starts a
subprocess, uses the network, uses an external AI / API or calls Claude. There is no "approved"
or "authorized" readiness status. claude_independent=True is DESCRIPTIVE ONLY: it says the
request carries enough structured, validated context for the next controlled internal stage. It
never grants implementation or execution: implementation_allowed, execution_allowed,
implementation_started and executed are ALWAYS False in every result.

  build_claude_exit_readiness(authority_descriptor, scope_descriptor, evolution_request,
        analysis_result, specification, plan, proposal, candidate, readiness_result, design,
        validation_result, blueprint, blueprint_validation_result, contract,
        contract_validation_result, contract_readiness_result, boundary_result,
        implementation_request, request_validation_result, policy, approval_request,
        approval_request_validation_result, decision, decision_validation_result)
  validate_claude_exit_readiness(result)

Nothing supplied is trusted and nothing is re-implemented. The real Section 16 / Section 17
validators and builders re-derive every stage, and every supplied object (including every
"valid" result) must be exactly equal (type-strict) to what the chain derives, so a forged or
manually altered upstream validation result is rejected instead of being trusted for its
valid=True field. Evaluation order (the first failing prerequisite decides the status and is the
single entry of missing_requirements):
   0 a permission / execution flag set anywhere in the supplied objects ... forbidden_execution_state
   1 a request_id / capability_name / operation that differs between stages ... context_mismatch
   2 Section 16 chain (Prompt 892 context validation of the supplied chain)
       unsupported operation / analysis status ............................ unsupported_operation
       forged stage ....................................................... context_mismatch
       missing or invalid stage ........................................... not_ready
   3 supplied Prompt 892 result malformed / not valid ..................... not_ready
     supplied Prompt 892 result differs from the derived one .............. context_mismatch
   4 controlled-autonomy policy, 5 approval request, 6 approval decision
     (missing / invalid -> not_ready, individually valid but forged -> context_mismatch,
      ineligible policy -> unsupported_operation)
   7 Prompt 897 decision context, then the Prompt 898 authority and the Prompt 899 scope
       authority or scope missing / invalid ............................... not_ready
       scope differs from authority / request ............................. context_mismatch
       any other inconsistent decision context ............................ invalid_context
   8 everything holds ..................................................... ready_without_claude
Any unexpected internal failure -> validation_error.

Result (exactly these fourteen keys, a fresh dict on every call, primitive values only):
  {"version", "status", "valid", "claude_independent", "request_id",
   "implementation_request_id", "capability_name", "operation", "reason",
   "missing_requirements", "implementation_allowed", "execution_allowed",
   "implementation_started", "executed"}
version is the integer 1; valid and claude_independent are True only for
"ready_without_claude"; reason equals the status; missing_requirements is [] for
"ready_without_claude" and exactly one deterministic requirement name otherwise. The identity
fields are filled (from the trusted, validated objects) only for "ready_without_claude" and are
None for every other status, so a rejected result never carries untrusted values.

validate_claude_exit_readiness(result) checks that exact shape and returns
{"valid", "errors", "execution_allowed", "executed"}; purely structural, read-only, never
raises. Inputs are never modified and never shared with a result.
"""

from autonomy.approval_authority_scope import validate_approval_authority_scope_context
from autonomy.approval_authority_source import validate_approval_authority_source
from autonomy.implementation_approval_decision import (
    build_implementation_approval_decision, validate_implementation_approval_decision)
from autonomy.implementation_approval_decision_validation import (
    validate_implementation_approval_decision_context,
    validate_implementation_approval_decision_validation_result)
from autonomy.implementation_approval_request import (
    build_implementation_approval_request, validate_implementation_approval_request)
from autonomy.implementation_permission_policy import (
    build_implementation_permission_policy, validate_implementation_permission_policy)
from capabilities.capability_evolution_proposal import validate_capability_evolution_proposal
from capabilities.capability_evolution_request import validate_capability_evolution_request
from capabilities.capability_implementation_request_validation import (
    validate_capability_implementation_request_context,
    validate_capability_implementation_request_validation_result)
from capabilities.capability_registry import MAX_ERRORS

RESULT_VERSION = 1

STATUS_READY = "ready_without_claude"
STATUS_NOT_READY = "not_ready"
STATUS_INVALID_CONTEXT = "invalid_context"
STATUS_CONTEXT = "context_mismatch"
STATUS_UNSUPPORTED = "unsupported_operation"
STATUS_FORBIDDEN = "forbidden_execution_state"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_NOT_READY, STATUS_INVALID_CONTEXT, STATUS_CONTEXT,
            STATUS_UNSUPPORTED, STATUS_FORBIDDEN, STATUS_ERROR)

RESULT_KEYS = ("version", "status", "valid", "claude_independent", "request_id",
               "implementation_request_id", "capability_name", "operation", "reason",
               "missing_requirements", "implementation_allowed", "execution_allowed",
               "implementation_started", "executed")
IDENTITY_KEYS = ("request_id", "implementation_request_id", "capability_name", "operation")
FALSE_FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started",
               "executed")
SUPPORTED_OPERATIONS = ("create", "improve")

# The seventeen readiness dimensions, in evaluation order, plus two generic entries.
REQ_REQUEST_IDENTITY = "request_identity_consistent"
REQ_CAPABILITY_IDENTITY = "capability_identity_consistent"
REQ_OPERATION = "operation_supported"
REQ_ANALYSIS = "analysis_valid"
REQ_SPECIFICATION = "specification_valid"
REQ_DEFINITION = "definition_readiness_valid"
REQ_DESIGN = "implementation_design_valid"
REQ_BLUEPRINT = "implementation_blueprint_valid"
REQ_CONTRACT = "implementation_contract_valid"
REQ_BOUNDARY = "implementation_boundary_valid"
REQ_IMPL_REQUEST = "implementation_request_valid"
REQ_REQUEST_VALIDATION = "implementation_request_validation_valid"
REQ_POLICY = "controlled_autonomy_policy_valid"
REQ_APPROVAL_REQUEST = "approval_request_valid"
REQ_DECISION = "approval_decision_valid"
REQ_AUTHORITY_SCOPE = "authority_scope_context_valid"
REQ_NO_FORBIDDEN = "no_forbidden_execution_state"
REQ_CONTEXT = "context_consistent"
REQ_EVALUATION = "evaluation_completed"

DIMENSIONS = (REQ_REQUEST_IDENTITY, REQ_CAPABILITY_IDENTITY, REQ_OPERATION, REQ_ANALYSIS,
              REQ_SPECIFICATION, REQ_DEFINITION, REQ_DESIGN, REQ_BLUEPRINT, REQ_CONTRACT,
              REQ_BOUNDARY, REQ_IMPL_REQUEST, REQ_REQUEST_VALIDATION, REQ_POLICY,
              REQ_APPROVAL_REQUEST, REQ_DECISION, REQ_AUTHORITY_SCOPE, REQ_NO_FORBIDDEN)
REQUIREMENTS = DIMENSIONS + (REQ_CONTEXT, REQ_EVALUATION)

# Prompt 892 stage status -> readiness dimension (anything else -> context_consistent)
_CHAIN_REQUIREMENT = {
    "invalid_request": REQ_REQUEST_IDENTITY,
    "invalid_analysis": REQ_ANALYSIS,
    "invalid_specification": REQ_SPECIFICATION,
    "invalid_validation": REQ_SPECIFICATION,
    "invalid_plan": REQ_DEFINITION,
    "invalid_proposal": REQ_DEFINITION,
    "invalid_candidate": REQ_DEFINITION,
    "invalid_readiness": REQ_DEFINITION,
    "invalid_design": REQ_DESIGN,
    "invalid_design_validation": REQ_DESIGN,
    "invalid_blueprint": REQ_BLUEPRINT,
    "invalid_blueprint_validation": REQ_BLUEPRINT,
    "invalid_contract": REQ_CONTRACT,
    "invalid_contract_validation": REQ_CONTRACT,
    "invalid_contract_readiness": REQ_CONTRACT,
    "invalid_boundary": REQ_BOUNDARY,
    "invalid_implementation_request": REQ_IMPL_REQUEST,
}

ERR_NOT_DICT = "result_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_VALID = "invalid_valid"
ERR_INVALID_INDEPENDENT = "invalid_claude_independent"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_MISSING = "invalid_missing_requirements"
ERR_INVALID_FLAG = "invalid_flag"
ERR_INVALID_IDENTITY = "invalid_identity"
ERR_INTERNAL = "validation_error"

_MAX_SCAN_NODES = 20000
_MAX_SCAN_DEPTH = 12


class _Outcome(Exception):
    """Internal early exit carrying (status, requirement); never leaves this module."""

    def __init__(self, status, requirement):
        Exception.__init__(self, status)
        self.status = status
        self.requirement = requirement


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


def _result(status, requirement=None, identity=None):
    """Result for a status; identity only for the ready status (from trusted objects)."""
    ready = status == STATUS_READY
    ids = dict.fromkeys(IDENTITY_KEYS)
    if ready:
        ids = {key: identity[key] for key in IDENTITY_KEYS}
    out = {"version": RESULT_VERSION, "status": status, "valid": ready,
           "claude_independent": ready}
    out.update(ids)
    out.update({"reason": status,
                "missing_requirements": [] if ready else [requirement or REQ_EVALUATION],
                "implementation_allowed": False, "execution_allowed": False,
                "implementation_started": False, "executed": False})
    return out


def _forbidden_state(objects):
    """True if any supplied dict (at any depth) sets a permission / execution flag."""
    stack = [(obj, 0) for obj in objects]
    seen = 0
    while stack:
        node, depth = stack.pop()
        seen += 1
        if seen > _MAX_SCAN_NODES or depth > _MAX_SCAN_DEPTH:
            continue
        if type(node) is dict:
            for key, value in node.items():
                if type(key) is str and key in FALSE_FLAGS:
                    try:
                        if bool(value):
                            return True
                    except Exception:
                        return True
                stack.append((value, depth + 1))
        elif type(node) in (list, tuple):
            for value in node:
                stack.append((value, depth + 1))
    return False


def _identity_conflict(objects):
    """Dimension of the first request_id / capability_name / operation that differs."""
    for key, requirement in (("request_id", REQ_REQUEST_IDENTITY),
                             ("capability_name", REQ_CAPABILITY_IDENTITY),
                             ("operation", REQ_OPERATION)):
        values = set()
        for obj in objects:
            if type(obj) is dict and type(obj.get(key)) is str:
                values.add(obj[key])
        if len(values) > 1:
            return requirement
    return None


def _report_ok(report):
    """A supplied Prompt 895 validation report must be a dict that says valid."""
    return type(report) is dict and report.get("valid") is True


def _evaluate(authority, scope, chain, request_validation_result, policy, approval_request,
              approval_request_validation_result, decision, decision_validation_result):
    """(status, requirement, identity) for the whole context; the first failure decides."""
    objects = (authority, scope) + chain + (
        request_validation_result, policy, approval_request,
        approval_request_validation_result, decision, decision_validation_result)

    # 0 forbidden execution / implementation state anywhere
    if _forbidden_state(objects):
        raise _Outcome(STATUS_FORBIDDEN, REQ_NO_FORBIDDEN)

    # 1 identity across stages (a stage with a different identity is a mismatch)
    conflict = _identity_conflict(objects)
    if conflict is not None:
        raise _Outcome(STATUS_CONTEXT, conflict)

    # 2 Section 16 chain, re-derived by the real Prompt 892 validator
    derived = validate_capability_implementation_request_context(*chain)
    if not validate_capability_implementation_request_validation_result(derived)["valid"]:
        raise _Outcome(STATUS_ERROR, REQ_EVALUATION)
    if derived["status"] == "unsupported_status":
        raise _Outcome(STATUS_UNSUPPORTED, REQ_OPERATION)
    if derived["status"] == "context_mismatch":
        raise _Outcome(STATUS_CONTEXT, REQ_IMPL_REQUEST)
    if derived["status"] == "validation_error":
        raise _Outcome(STATUS_ERROR, REQ_EVALUATION)
    if derived["status"] != "valid":
        raise _Outcome(STATUS_NOT_READY,
                       _CHAIN_REQUIREMENT.get(derived["status"], REQ_CONTEXT))

    # 3 the supplied Prompt 892 result must be the derived one (never trusted for valid=True)
    supplied = request_validation_result
    if (not validate_capability_implementation_request_validation_result(supplied)["valid"]
            or supplied["status"] != "valid" or supplied["valid"] is not True):
        raise _Outcome(STATUS_NOT_READY, REQ_REQUEST_VALIDATION)
    if not _same(supplied, derived):
        raise _Outcome(STATUS_CONTEXT, REQ_REQUEST_VALIDATION)

    # 4 controlled-autonomy policy
    if not validate_implementation_permission_policy(policy)["valid"]:
        raise _Outcome(STATUS_NOT_READY, REQ_POLICY)
    if policy["status"] != "eligible":
        raise _Outcome(STATUS_UNSUPPORTED, REQ_POLICY)
    expected_policy = build_implementation_permission_policy(
        *chain, derived, policy["policy_id"])
    if expected_policy["status"] != "eligible" or not _same(policy, expected_policy):
        raise _Outcome(STATUS_CONTEXT, REQ_POLICY)

    # 5 approval request
    if (not validate_implementation_approval_request(approval_request)["valid"]
            or not _report_ok(approval_request_validation_result)):
        raise _Outcome(STATUS_NOT_READY, REQ_APPROVAL_REQUEST)
    expected_approval = build_implementation_approval_request(
        *chain, derived, policy, approval_request["approval_request_id"])
    if (expected_approval["status"] != "ready_for_approval"
            or not _same(approval_request, expected_approval["approval_request"])
            or not _same(approval_request_validation_result,
                         validate_implementation_approval_request(
                             expected_approval["approval_request"]))):
        raise _Outcome(STATUS_CONTEXT, REQ_APPROVAL_REQUEST)

    # 6 approval decision
    if not validate_implementation_approval_decision(decision)["valid"]:
        raise _Outcome(STATUS_NOT_READY, REQ_DECISION)
    expected_decision = build_implementation_approval_decision(
        *chain, derived, policy, approval_request, approval_request_validation_result,
        decision["decision_id"])
    if (expected_decision["status"] != "pending_approval"
            or not _same(decision, expected_decision["decision"])):
        raise _Outcome(STATUS_CONTEXT, REQ_DECISION)

    # 7 Prompt 897 decision context, then the Prompt 898 authority and Prompt 899 scope
    decision_context = validate_implementation_approval_decision_context(
        *chain, request_validation_result, policy, approval_request,
        approval_request_validation_result, decision)
    if decision_context["status"] != "valid":
        status = decision_context["status"]
        if status == "unsupported_status":
            raise _Outcome(STATUS_UNSUPPORTED, REQ_OPERATION)
        if status == "validation_error":
            raise _Outcome(STATUS_ERROR, REQ_EVALUATION)
        if status == "context_mismatch":
            raise _Outcome(STATUS_CONTEXT, REQ_DECISION)
        raise _Outcome(STATUS_INVALID_CONTEXT, REQ_CONTEXT)
    if (not validate_implementation_approval_decision_validation_result(
            decision_validation_result)["valid"]
            or decision_validation_result["status"] != "valid"
            or decision_validation_result["valid"] is not True):
        raise _Outcome(STATUS_NOT_READY, REQ_DECISION)
    if not _same(decision_validation_result, decision_context):
        raise _Outcome(STATUS_CONTEXT, REQ_DECISION)

    authority_status = validate_approval_authority_source(authority)["status"]
    if authority_status != "valid":
        raise _Outcome(STATUS_UNSUPPORTED if authority_status == "unsupported_status"
                       else STATUS_NOT_READY, REQ_AUTHORITY_SCOPE)
    scope_status = validate_approval_authority_scope_context(authority, scope)["status"]
    if scope_status == "unsupported_status":
        raise _Outcome(STATUS_UNSUPPORTED, REQ_AUTHORITY_SCOPE)
    if scope_status == "context_mismatch":
        raise _Outcome(STATUS_CONTEXT, REQ_AUTHORITY_SCOPE)
    if scope_status != "valid":
        raise _Outcome(STATUS_NOT_READY, REQ_AUTHORITY_SCOPE)
    if (not _same(scope["capability_name"], chain[0]["capability_name"])
            or not _same(scope["operation"], chain[0]["operation"])):
        raise _Outcome(STATUS_CONTEXT, REQ_AUTHORITY_SCOPE)

    # 8 everything holds
    request, impl = chain[0], chain[15]
    identity = {"request_id": request["request_id"],
                "implementation_request_id": impl["implementation_request_id"],
                "capability_name": request["capability_name"],
                "operation": request["operation"]}
    if identity["operation"] not in SUPPORTED_OPERATIONS:
        raise _Outcome(STATUS_UNSUPPORTED, REQ_OPERATION)
    return STATUS_READY, None, identity


def build_claude_exit_readiness(
        authority_descriptor=None, scope_descriptor=None, evolution_request=None,
        analysis_result=None, specification=None, plan=None, proposal=None, candidate=None,
        readiness_result=None, design=None, validation_result=None, blueprint=None,
        blueprint_validation_result=None, contract=None, contract_validation_result=None,
        contract_readiness_result=None, boundary_result=None, implementation_request=None,
        request_validation_result=None, policy=None, approval_request=None,
        approval_request_validation_result=None, decision=None,
        decision_validation_result=None):
    """Readiness description for the chain (descriptive only; grants nothing, never raises)."""
    try:
        chain = (evolution_request, analysis_result, specification, plan, proposal,
                 candidate, readiness_result, design, validation_result, blueprint,
                 blueprint_validation_result, contract, contract_validation_result,
                 contract_readiness_result, boundary_result, implementation_request)
        status, requirement, identity = _evaluate(
            authority_descriptor, scope_descriptor, chain, request_validation_result, policy,
            approval_request, approval_request_validation_result, decision,
            decision_validation_result)
        return _result(status, requirement, identity)
    except _Outcome as outcome:
        return _result(outcome.status, outcome.requirement)
    except Exception:
        return _result(STATUS_ERROR, REQ_EVALUATION)


def _text_ok(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


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
    ready = status_ok and status == STATUS_READY
    for key in ("valid", "claude_independent"):
        if type(result[key]) is not bool or (status_ok and result[key] != ready):
            add(ERR_INVALID_VALID if key == "valid" else ERR_INVALID_INDEPENDENT, key)
    if type(result["reason"]) is not str or (status_ok and result["reason"] != status):
        add(ERR_INVALID_REASON, "reason")
    for key in FALSE_FLAGS:
        if result[key] is not False:
            add(ERR_INVALID_FLAG, key)

    missing = result["missing_requirements"]
    if type(missing) is not list or any(type(m) is not str or m not in REQUIREMENTS
                                        for m in missing):
        add(ERR_INVALID_MISSING, "missing_requirements")
    elif status_ok and ready != (missing == []):
        add(ERR_INVALID_MISSING, "missing_requirements")
    elif status_ok and not ready and len(missing) != 1:
        add(ERR_INVALID_MISSING, "missing_requirements")
    if not status_ok:
        return errors

    if not ready:
        for key in IDENTITY_KEYS:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors

    if result["operation"] not in SUPPORTED_OPERATIONS:
        add(ERR_INVALID_IDENTITY, "operation")
    if not _text_ok(result["implementation_request_id"]):
        add(ERR_INVALID_IDENTITY, "implementation_request_id")
    view = {"version": "1", "request_id": result["request_id"], "operation": "create",
            "capability_name": result["capability_name"], "goal": "g", "inputs": [],
            "outputs": ["o"], "constraints": [], "requested_by": "r",
            "execution_allowed": False}
    for error in validate_capability_evolution_request(view)["errors"]:
        if error["where"] in ("request_id", "capability_name"):
            add(ERR_INVALID_IDENTITY, error["where"])
    return errors


def validate_claude_exit_readiness(result=None):
    """Validation result for a normalized readiness result (structural, never raises)."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
