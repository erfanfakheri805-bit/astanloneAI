"""
Capability Implementation Request Validation (Prompt 892, Section 16)
=====================================================================
A deterministic, read-only validation boundary over the complete Section 16 chain through
Prompt 891:

    request -> analysis -> specification -> plan -> proposal -> candidate -> readiness
            -> design -> design validation result (885) -> blueprint (886)
            -> blueprint validation result (887) -> contract (888)
            -> contract validation result (888 validator) -> contract readiness result (889)
            -> boundary result (890) -> implementation request (891)

It answers only: "is this implementation request exactly the request derivable from the
trusted, validated chain?" It never generates code or patches, creates or modifies files,
touches the registry or project, starts an implementation, or executes, installs, writes,
persists (Memory), researches (AEL), networks, calls an API or model, loads / replaces a
capability or self-modifies. Caller data is never normalized, altered or repaired.
implementation_allowed and execution_allowed of a valid request are ALWAYS False.

  validate_capability_implementation_request_context(evolution_request, analysis_result,
        specification, plan, proposal, candidate, readiness_result, design,
        validation_result, blueprint, blueprint_validation_result, contract,
        contract_validation_result, contract_readiness_result, boundary_result,
        implementation_request)
  validate_capability_implementation_request_validation_result(result)

The public validators / builders of Prompts 876-891 are reused, not re-implemented. The
upstream chain (checks 1-15 and the context / support decision) is decided by the Prompt 890
boundary evaluation of the supplied chain; checks run in this fixed order and the first
failure decides the status:
   1-15 invalid_request, invalid_analysis, invalid_specification, invalid_validation,
        invalid_plan, invalid_proposal, invalid_candidate, invalid_readiness,
        invalid_design, invalid_design_validation, invalid_blueprint,
        invalid_blueprint_validation, invalid_contract, invalid_contract_validation,
        invalid_contract_readiness
        (analysis status improve_or_conflict -> unsupported_status; no downstream chain is
        ever derived or validated for it)
   16 Prompt 890 boundary result not valid / not "ready" / a permission flag True
                                                   invalid_boundary
   17 Prompt 890 boundary result differs from the one the chain derives (forged)
                                                   context_mismatch
   18 implementation request fails the Prompt 891 validator (shape, version, ids, flags)
                                                   invalid_implementation_request
   19 implementation request differs from the request the Prompt 891 builder derives from
      the trusted chain: type-strict comparison of implementation_request_id, request_id,
      capability_name, operation, analysis_status, plan_id, contract_id, boundary_status,
      purpose, inputs, outputs, constraints, existing_capability, implementation_allowed,
      execution_allowed and the whole object        context_mismatch
   20 unsupported operation / status               unsupported_status
   21 determination                                valid
Any unexpected internal failure -> validation_error.

Result (exactly these twelve keys, fresh every call):
  {"version", "status", "valid", "implementation_request_id", "request_id",
   "capability_name", "operation", "analysis_status", "plan_id", "contract_id",
   "boundary_status", "reason"}
version is the integer 1; valid is True only when status == "valid"; reason equals the
status. Identity comes only from trusted objects: invalid_request and validation_error carry
none; invalid_analysis carries the request identity only; every other non-valid status
carries the request identity and analysis_status; implementation_request_id, plan_id,
contract_id and boundary_status are populated only for "valid". The result has no execution
flag; its validator's report (like every validator of the series) carries
execution_allowed / executed False.
"""

from .capability_evolution_proposal import validate_capability_evolution_proposal
from .capability_evolution_request import validate_capability_evolution_request
from .capability_implementation_boundary import (
    evaluate_capability_implementation_boundary,
    validate_capability_implementation_boundary_result)
from .capability_implementation_request import (
    build_capability_implementation_request, validate_capability_implementation_request)
from .capability_registry import MAX_ERRORS

VALIDATION_VERSION = 1

STATUS_VALID = "valid"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_ANALYSIS = "invalid_analysis"
STATUS_INVALID_SPECIFICATION = "invalid_specification"
STATUS_INVALID_VALIDATION = "invalid_validation"
STATUS_INVALID_PLAN = "invalid_plan"
STATUS_INVALID_PROPOSAL = "invalid_proposal"
STATUS_INVALID_CANDIDATE = "invalid_candidate"
STATUS_INVALID_READINESS = "invalid_readiness"
STATUS_INVALID_DESIGN = "invalid_design"
STATUS_INVALID_DESIGN_VALIDATION = "invalid_design_validation"
STATUS_INVALID_BLUEPRINT = "invalid_blueprint"
STATUS_INVALID_BLUEPRINT_VALIDATION = "invalid_blueprint_validation"
STATUS_INVALID_CONTRACT = "invalid_contract"
STATUS_INVALID_CONTRACT_VALIDATION = "invalid_contract_validation"
STATUS_INVALID_CONTRACT_READINESS = "invalid_contract_readiness"
STATUS_INVALID_BOUNDARY = "invalid_boundary"
STATUS_INVALID_IMPLEMENTATION_REQUEST = "invalid_implementation_request"
STATUS_CONTEXT = "context_mismatch"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_VALID, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_INVALID_VALIDATION, STATUS_INVALID_PLAN,
            STATUS_INVALID_PROPOSAL, STATUS_INVALID_CANDIDATE, STATUS_INVALID_READINESS,
            STATUS_INVALID_DESIGN, STATUS_INVALID_DESIGN_VALIDATION, STATUS_INVALID_BLUEPRINT,
            STATUS_INVALID_BLUEPRINT_VALIDATION, STATUS_INVALID_CONTRACT,
            STATUS_INVALID_CONTRACT_VALIDATION, STATUS_INVALID_CONTRACT_READINESS,
            STATUS_INVALID_BOUNDARY, STATUS_INVALID_IMPLEMENTATION_REQUEST, STATUS_CONTEXT,
            STATUS_UNSUPPORTED, STATUS_ERROR)

RESULT_KEYS = ("version", "status", "valid", "implementation_request_id", "request_id",
               "capability_name", "operation", "analysis_status", "plan_id", "contract_id",
               "boundary_status", "reason")

COMPARED_FIELDS = ("implementation_request_id", "request_id", "capability_name", "operation",
                   "analysis_status", "plan_id", "contract_id", "boundary_status", "purpose",
                   "inputs", "outputs", "constraints", "existing_capability",
                   "implementation_allowed", "execution_allowed")

SUPPORTED = (("create", "create_required"), ("improve", "improve_required"))
_ANALYSIS_STATUSES = ("create_required", "improve_required", "improve_or_conflict")

_NO_IDS = frozenset((STATUS_INVALID_REQUEST, STATUS_ERROR))
_REQUEST_ONLY = frozenset((STATUS_INVALID_ANALYSIS,))
_IDS = ("request_id", "capability_name", "operation")
_LATER = ("implementation_request_id", "plan_id", "contract_id", "boundary_status")

ERR_NOT_DICT = "result_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_VALID = "invalid_valid"
ERR_INVALID_IDENTITY = "invalid_identity"
ERR_INVALID_REASON = "invalid_reason"
ERR_INCONSISTENT = "inconsistent_result"
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


def _result(status, request=None, analysis_status=None, implementation_request_id=None,
            plan_id=None, contract_id=None, boundary_status=None):
    ids = (None, None, None)
    if request is not None:
        ids = (request["request_id"], request["capability_name"], request["operation"])
    return {"version": VALIDATION_VERSION, "status": status, "valid": status == STATUS_VALID,
            "implementation_request_id": implementation_request_id,
            "request_id": ids[0], "capability_name": ids[1], "operation": ids[2],
            "analysis_status": analysis_status, "plan_id": plan_id, "contract_id": contract_id,
            "boundary_status": boundary_status, "reason": status}


def _id_ok(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


def _boundary_ok(result):
    if not validate_capability_implementation_boundary_result(result)["valid"]:
        return False
    return (result["status"] == "ready" and result["ready"] is True
            and result["implementation_allowed"] is False
            and result["implementation_started"] is False
            and result["execution_allowed"] is False and result["executed"] is False)


def validate_capability_implementation_request_context(
        evolution_request=None, analysis_result=None, specification=None, plan=None,
        proposal=None, candidate=None, readiness_result=None, design=None,
        validation_result=None, blueprint=None, blueprint_validation_result=None,
        contract=None, contract_validation_result=None, contract_readiness_result=None,
        boundary_result=None, implementation_request=None):
    """Validation of an implementation request against its trusted chain (read-only)."""
    try:
        chain = (evolution_request, analysis_result, specification, plan, proposal, candidate,
                 readiness_result, design, validation_result, blueprint,
                 blueprint_validation_result, contract, contract_validation_result,
                 contract_readiness_result)
        request, analysis = evolution_request, analysis_result

        derived = evaluate_capability_implementation_boundary(*chain)
        if derived["status"] != "ready":
            status = derived["status"]
            if status not in STATUSES or status in (STATUS_VALID,):
                return _result(STATUS_ERROR)
            ident = None if status in _NO_IDS else request
            analysis_status = None if status in _NO_IDS or status in _REQUEST_ONLY \
                else analysis["status"]
            return _result(status, ident, analysis_status)
        analysis_status = analysis["status"]

        if not _boundary_ok(boundary_result):
            return _result(STATUS_INVALID_BOUNDARY, request, analysis_status)
        if not _same(boundary_result, derived):
            return _result(STATUS_CONTEXT, request, analysis_status)

        if not validate_capability_implementation_request(implementation_request)["valid"]:
            return _result(STATUS_INVALID_IMPLEMENTATION_REQUEST, request, analysis_status)

        built = build_capability_implementation_request(
            *chain, boundary_result, implementation_request["implementation_request_id"])
        if built["status"] == "unsupported_status":
            return _result(STATUS_UNSUPPORTED, request, analysis_status)
        if built["status"] != "ready":
            return _result(STATUS_CONTEXT, request, analysis_status)
        expected = built["request"]
        for field in COMPARED_FIELDS:
            if not _same(implementation_request[field], expected[field]):
                return _result(STATUS_CONTEXT, request, analysis_status)
        if not _same(implementation_request, expected):
            return _result(STATUS_CONTEXT, request, analysis_status)

        if (request["operation"], analysis_status) not in SUPPORTED:
            return _result(STATUS_UNSUPPORTED, request, analysis_status)
        return _result(STATUS_VALID, request, analysis_status,
                       expected["implementation_request_id"], expected["plan_id"],
                       expected["contract_id"], expected["boundary_status"])
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

    if type(result["version"]) is not int or result["version"] != VALIDATION_VERSION:
        add(ERR_INVALID_VERSION, "version")
    status = result["status"]
    status_ok = type(status) is str and status in STATUSES
    if not status_ok:
        add(ERR_INVALID_STATUS, "status")
    if type(result["valid"]) is not bool:
        add(ERR_INVALID_VALID, "valid")
    elif status_ok and result["valid"] != (status == STATUS_VALID):
        add(ERR_INVALID_VALID, "valid")
    if type(result["reason"]) is not str or (status_ok and result["reason"] != status):
        add(ERR_INVALID_REASON, "reason")
    if not status_ok:
        return errors

    if status in _NO_IDS:
        for key in _IDS + ("analysis_status",) + _LATER:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors
    view = {"version": "1", "request_id": result["request_id"],
            "operation": result["operation"], "capability_name": result["capability_name"],
            "goal": "g", "inputs": [], "outputs": ["o"], "constraints": [],
            "requested_by": "r", "execution_allowed": False}
    for error in validate_capability_evolution_request(view)["errors"]:
        if error["where"] in _IDS:
            add(ERR_INVALID_IDENTITY, error["where"])
    if status in _REQUEST_ONLY:
        for key in ("analysis_status",) + _LATER:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors
    if type(result["analysis_status"]) is not str or \
            result["analysis_status"] not in _ANALYSIS_STATUSES:
        add(ERR_INVALID_IDENTITY, "analysis_status")
    if status == STATUS_VALID:
        for key in ("implementation_request_id", "plan_id", "contract_id"):
            if not _id_ok(result[key]):
                add(ERR_INVALID_IDENTITY, key)
        if type(result["boundary_status"]) is not str or result["boundary_status"] != "ready":
            add(ERR_INVALID_IDENTITY, "boundary_status")
        if (result["operation"], result["analysis_status"]) not in SUPPORTED:
            add(ERR_INCONSISTENT, "status")
    else:
        for key in _LATER:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
    return errors


def validate_capability_implementation_request_validation_result(result=None):
    """Validation result for a normalized implementation request validation result."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
