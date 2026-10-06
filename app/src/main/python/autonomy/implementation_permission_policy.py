"""
Implementation Permission Policy (Prompt 894, Section 17: Controlled Autonomy)
===============================================================================
A deterministic, read-only POLICY GATE that states whether a validated capability
implementation request MAY BE CONSIDERED for a future, separately controlled approval step.

It never implements anything. It generates no source code and no patch, modifies no file,
registry, Memory or AEL state, starts nothing and executes nothing. "eligible" is NOT a
permission: implementation_allowed, execution_allowed, implementation_started and executed
are ALWAYS False, whatever the status.

  build_implementation_permission_policy(evolution_request, analysis_result, specification,
        plan, proposal, candidate, readiness_result, design, validation_result, blueprint,
        blueprint_validation_result, contract, contract_validation_result,
        contract_readiness_result, boundary_result, implementation_request,
        request_validation_result, policy_id, permission_state=None)
  validate_implementation_permission_policy(policy)

The Section 16 chain is judged by the Prompt 892 context validation (which itself reuses the
Prompt 876-891 validators and the Prompt 890 boundary); nothing is re-implemented here.
Checks run in this fixed order; the first failure decides the status:
   0 policy_id missing / not valid ID text                  validation_error
   1 Prompt 892 chain evaluation of the supplied objects
       invalid_request, invalid_implementation_request      invalid_request
       invalid_analysis .. invalid_candidate, invalid_validation,
         invalid_readiness (definition chain, 876-883)      invalid_definition_readiness
       invalid_design .. invalid_contract_validation        invalid_contract
       invalid_contract_readiness                           invalid_contract_readiness
       invalid_boundary                                     invalid_boundary
       context_mismatch                                     context_mismatch
       unsupported_status (e.g. improve_or_conflict)        unsupported
       validation_error                                     validation_error
   2 supplied Prompt 892 result malformed / not "valid"     invalid_request_validation
   3 supplied Prompt 892 result differs from the derived one (forged)
                                                            context_mismatch
   4 permission_state malformed                             validation_error
   5 any implementation / execution permission or start already recorded
     (permission_state), i.e. a grant already exists        blocked
   6 request not inside the controlled-autonomy boundary (boundary not "ready", operation /
     analysis pair not supported)                           ineligible
   7 everything holds                                       eligible

permission_state is an OPTIONAL caller-supplied record of what has already been granted: a
dict with exactly the keys implementation_allowed, execution_allowed, implementation_started,
executed, all bool. None means nothing has been granted. It is only read, never altered.

Policy (exactly these thirteen keys, fresh every call):
  {"version", "policy_id", "request_id", "implementation_request_id", "capability_name",
   "operation", "status", "reason", "eligible", "implementation_allowed", "execution_allowed",
   "implementation_started", "executed"}
version is the integer 1; reason equals the status; eligible is True only for "eligible".
Identity comes only from trusted objects: invalid_request and validation_error carry none;
implementation_request_id is populated only for eligible, blocked and ineligible.
"""

from capabilities.capability_evolution_proposal import validate_capability_evolution_proposal
from capabilities.capability_evolution_request import validate_capability_evolution_request
from capabilities.capability_implementation_request_validation import (
    validate_capability_implementation_request_context,
    validate_capability_implementation_request_validation_result)
from capabilities.capability_registry import MAX_ERRORS

POLICY_VERSION = 1

STATUS_ELIGIBLE = "eligible"
STATUS_INELIGIBLE = "ineligible"
STATUS_BLOCKED = "blocked"
STATUS_UNSUPPORTED = "unsupported"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_REQUEST_VALIDATION = "invalid_request_validation"
STATUS_INVALID_BOUNDARY = "invalid_boundary"
STATUS_INVALID_CONTRACT = "invalid_contract"
STATUS_INVALID_CONTRACT_READINESS = "invalid_contract_readiness"
STATUS_INVALID_DEFINITION_READINESS = "invalid_definition_readiness"
STATUS_CONTEXT = "context_mismatch"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_ELIGIBLE, STATUS_INELIGIBLE, STATUS_BLOCKED, STATUS_UNSUPPORTED,
            STATUS_INVALID_REQUEST, STATUS_INVALID_REQUEST_VALIDATION,
            STATUS_INVALID_BOUNDARY, STATUS_INVALID_CONTRACT,
            STATUS_INVALID_CONTRACT_READINESS, STATUS_INVALID_DEFINITION_READINESS,
            STATUS_CONTEXT, STATUS_ERROR)

POLICY_KEYS = ("version", "policy_id", "request_id", "implementation_request_id",
               "capability_name", "operation", "status", "reason", "eligible",
               "implementation_allowed", "execution_allowed", "implementation_started",
               "executed")
FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started", "executed")

SUPPORTED_OPERATIONS = ("create", "improve")
SUPPORTED = (("create", "create_required"), ("improve", "improve_required"))

# Prompt 892 status -> policy status
_STATUS_MAP = {
    "invalid_request": STATUS_INVALID_REQUEST,
    "invalid_implementation_request": STATUS_INVALID_REQUEST,
    "invalid_analysis": STATUS_INVALID_DEFINITION_READINESS,
    "invalid_specification": STATUS_INVALID_DEFINITION_READINESS,
    "invalid_validation": STATUS_INVALID_DEFINITION_READINESS,
    "invalid_plan": STATUS_INVALID_DEFINITION_READINESS,
    "invalid_proposal": STATUS_INVALID_DEFINITION_READINESS,
    "invalid_candidate": STATUS_INVALID_DEFINITION_READINESS,
    "invalid_readiness": STATUS_INVALID_DEFINITION_READINESS,
    "invalid_design": STATUS_INVALID_CONTRACT,
    "invalid_design_validation": STATUS_INVALID_CONTRACT,
    "invalid_blueprint": STATUS_INVALID_CONTRACT,
    "invalid_blueprint_validation": STATUS_INVALID_CONTRACT,
    "invalid_contract": STATUS_INVALID_CONTRACT,
    "invalid_contract_validation": STATUS_INVALID_CONTRACT,
    "invalid_contract_readiness": STATUS_INVALID_CONTRACT_READINESS,
    "invalid_boundary": STATUS_INVALID_BOUNDARY,
    "context_mismatch": STATUS_CONTEXT,
    "unsupported_status": STATUS_UNSUPPORTED,
    "validation_error": STATUS_ERROR,
}

_NO_IDS = frozenset((STATUS_INVALID_REQUEST, STATUS_ERROR))
_WITH_IMPL_ID = frozenset((STATUS_ELIGIBLE, STATUS_BLOCKED, STATUS_INELIGIBLE))
_IDS = ("request_id", "capability_name", "operation")

ERR_NOT_DICT = "policy_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_POLICY_ID = "invalid_policy_id"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_ELIGIBLE = "invalid_eligible"
ERR_INVALID_FLAG = "invalid_flag"
ERR_INVALID_IDENTITY = "invalid_identity"
ERR_INCONSISTENT = "inconsistent_policy"
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


def _policy(status, policy_id=None, request_id=None, implementation_request_id=None,
            capability_name=None, operation=None):
    return {"version": POLICY_VERSION, "policy_id": policy_id, "request_id": request_id,
            "implementation_request_id": implementation_request_id,
            "capability_name": capability_name, "operation": operation, "status": status,
            "reason": status, "eligible": status == STATUS_ELIGIBLE,
            "implementation_allowed": False, "execution_allowed": False,
            "implementation_started": False, "executed": False}


def _id_ok(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


def _permission_state_ok(state):
    if state is None:
        return True
    if type(state) is not dict or sorted(state, key=repr) != sorted(FLAGS):
        return False
    return all(type(state[key]) is bool for key in FLAGS)


def _from_derived(status, policy_id, derived, with_impl_id=False):
    """Policy carrying only the identity of the trusted Prompt 892 derivation."""
    if status in _NO_IDS:
        return _policy(status, policy_id)
    impl_id = derived["implementation_request_id"] if with_impl_id else None
    return _policy(status, policy_id, derived["request_id"], impl_id,
                   derived["capability_name"], derived["operation"])


def build_implementation_permission_policy(
        evolution_request=None, analysis_result=None, specification=None, plan=None,
        proposal=None, candidate=None, readiness_result=None, design=None,
        validation_result=None, blueprint=None, blueprint_validation_result=None,
        contract=None, contract_validation_result=None, contract_readiness_result=None,
        boundary_result=None, implementation_request=None, request_validation_result=None,
        policy_id=None, permission_state=None):
    """Eligibility policy for a validated implementation request (read-only, no permission)."""
    try:
        if policy_id is None or not _id_ok(policy_id):
            return _policy(STATUS_ERROR)

        derived = validate_capability_implementation_request_context(
            evolution_request, analysis_result, specification, plan, proposal, candidate,
            readiness_result, design, validation_result, blueprint,
            blueprint_validation_result, contract, contract_validation_result,
            contract_readiness_result, boundary_result, implementation_request)
        if not validate_capability_implementation_request_validation_result(
                derived)["valid"]:
            return _policy(STATUS_ERROR)
        if derived["status"] != "valid":
            status = _STATUS_MAP.get(derived["status"], STATUS_ERROR)
            return _from_derived(status, None if status == STATUS_ERROR else policy_id,
                                 derived)

        supplied = request_validation_result
        if (not validate_capability_implementation_request_validation_result(
                supplied)["valid"] or supplied["status"] != "valid"
                or supplied["valid"] is not True):
            return _from_derived(STATUS_INVALID_REQUEST_VALIDATION, policy_id, derived)
        if not _same(supplied, derived):
            return _from_derived(STATUS_CONTEXT, policy_id, derived)

        if not _permission_state_ok(permission_state):
            return _policy(STATUS_ERROR)
        if permission_state is not None and any(permission_state[k] for k in FLAGS):
            return _from_derived(STATUS_BLOCKED, policy_id, derived, True)

        if (derived["boundary_status"] != "ready"
                or (derived["operation"], derived["analysis_status"]) not in SUPPORTED):
            return _from_derived(STATUS_INELIGIBLE, policy_id, derived, True)
        return _from_derived(STATUS_ELIGIBLE, policy_id, derived, True)
    except Exception:
        return _policy(STATUS_ERROR)


def _policy_errors(policy):
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(policy) is not dict:
        add(ERR_NOT_DICT, "policy")
        return errors
    for key in POLICY_KEYS:
        if key not in policy:
            add(ERR_MISSING_KEY, key)
    for key in policy:
        if type(key) is not str or key not in POLICY_KEYS:
            add(ERR_UNEXPECTED_KEY,
                key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    if type(policy["version"]) is not int or policy["version"] != POLICY_VERSION:
        add(ERR_INVALID_VERSION, "version")
    status = policy["status"]
    status_ok = type(status) is str and status in STATUSES
    if not status_ok:
        add(ERR_INVALID_STATUS, "status")
    if type(policy["reason"]) is not str or (status_ok and policy["reason"] != status):
        add(ERR_INVALID_REASON, "reason")
    if type(policy["eligible"]) is not bool:
        add(ERR_INVALID_ELIGIBLE, "eligible")
    elif status_ok and policy["eligible"] != (status == STATUS_ELIGIBLE):
        add(ERR_INVALID_ELIGIBLE, "eligible")
    for key in FLAGS:
        if policy[key] is not False:
            add(ERR_INVALID_FLAG, key)
    if not status_ok:
        return errors

    if status == STATUS_ERROR:
        if policy["policy_id"] is not None:
            add(ERR_INVALID_POLICY_ID, "policy_id")
    elif not _id_ok(policy["policy_id"]):
        add(ERR_INVALID_POLICY_ID, "policy_id")

    if status in _NO_IDS:
        for key in _IDS + ("implementation_request_id",):
            if policy[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors
    view = {"version": "1", "request_id": policy["request_id"],
            "operation": policy["operation"], "capability_name": policy["capability_name"],
            "goal": "g", "inputs": [], "outputs": ["o"], "constraints": [],
            "requested_by": "r", "execution_allowed": False}
    for error in validate_capability_evolution_request(view)["errors"]:
        if error["where"] in _IDS:
            add(ERR_INVALID_IDENTITY, error["where"])
    if status in _WITH_IMPL_ID:
        if not _id_ok(policy["implementation_request_id"]):
            add(ERR_INVALID_IDENTITY, "implementation_request_id")
        if policy["operation"] not in SUPPORTED_OPERATIONS:
            add(ERR_INCONSISTENT, "operation")
    elif policy["implementation_request_id"] is not None:
        add(ERR_INVALID_IDENTITY, "implementation_request_id")
    return errors


def validate_implementation_permission_policy(policy=None):
    """Validation result for a normalized implementation permission policy."""
    try:
        errors = _policy_errors(policy)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "policy"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
