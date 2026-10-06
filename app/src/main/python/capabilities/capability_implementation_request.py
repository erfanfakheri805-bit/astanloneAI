"""
Capability Implementation Request (Prompt 891, Section 16 - Capability Creation & Improvement)
===============================================================================================
A deterministic, read-only REQUEST CONTRACT that represents a controlled request to ENTER a
future implementation stage, created only after the Prompt 890 boundary has been reached:

    request -> analysis -> specification -> plan -> proposal -> candidate -> readiness
            -> design -> design validation result (885) -> blueprint (886)
            -> blueprint validation result (887) -> contract (888)
            -> contract validation result (888 validator) -> contract readiness result (889)
            -> boundary result (890) -> implementation request

The object is a request to enter a future stage, NOT permission to implement:
implementation_allowed and execution_allowed are ALWAYS False, even for a valid request.
Nothing is generated, patched, written, registered, installed, persisted (Memory), executed
(AEL / research), loaded, replaced, sent over a network / API / model, or self-modified, the
registry and project are untouched, and caller data is never normalized, altered or repaired
(everything is copied into fresh objects).

  build_capability_implementation_request(evolution_request, analysis_result, specification,
        plan, proposal, candidate, readiness_result, design, validation_result, blueprint,
        blueprint_validation_result, contract, contract_validation_result,
        contract_readiness_result, boundary_result, implementation_request_id=None)
  validate_capability_implementation_request(request)

The public validators / builders of Prompts 876-890 are reused, not re-implemented. The
complete trusted chain is validated before the request is built; the first failing check
decides the status (checks 1-15 are exactly those of the Prompt 890 boundary, which is
re-derived from the supplied chain):
   1-15 invalid_request, invalid_analysis, invalid_specification, invalid_validation,
        invalid_plan, invalid_proposal, invalid_candidate, invalid_readiness,
        invalid_design, invalid_design_validation, invalid_blueprint,
        invalid_blueprint_validation, invalid_contract, invalid_contract_validation,
        invalid_contract_readiness
        (analysis status improve_or_conflict -> unsupported_status, never a request)
  16   supplied Prompt 890 boundary result not a valid "ready" result with
       implementation_allowed / implementation_started / execution_allowed / executed all
       False                                      invalid_boundary
  17   chain disagreement                         context_mismatch
       the supplied boundary result must equal (type-strict) the result the trusted chain
       derives, so a forged but individually valid boundary result never passes
  18   implementation_request_id missing / invalid invalid_implementation_request_id
  19   unsupported operation / status             unsupported_status
       supported: create  + create_required, improve + improve_required
  20   built request fails its validator          request_error
Any unexpected internal failure -> validation_error.

implementation_request_id is caller-supplied (text, <= 64 chars, the request-id rule), never
generated.

Normalized request (exactly these sixteen keys):
  {"version", "implementation_request_id", "request_id", "capability_name", "operation",
   "analysis_status", "plan_id", "contract_id", "boundary_status", "purpose", "inputs",
   "outputs", "constraints", "existing_capability", "implementation_allowed",
   "execution_allowed"}
  version is the integer 1; request_id / capability_name / operation come from the trusted
  request, purpose from the trusted candidate, inputs / outputs / constraints from the trusted
  request (order kept, deep copies), existing_capability from the trusted analysis,
  analysis_status / plan_id / contract_id from the trusted chain; boundary_status is "ready";
  implementation_allowed and execution_allowed are False. The normalized request has no status
  field and no automatic execution field.

Builder result (exactly these keys, fresh every call):
  {"status", "request", "execution_allowed", "executed"}
status "ready" only together with a valid request (else request is None); both flags False.

validate_capability_implementation_request(request) checks the exact 16-key shape and every
invariant (reusing the Prompt 886 blueprint validator on a blueprint-shaped view for the
shared fields). Result: {"valid", "errors", "execution_allowed", "executed"}, errors
[{"code", "where"}], at most MAX_ERRORS; purely structural, read-only, never raises.
"""

import copy

from .capability_evolution_proposal import validate_capability_evolution_proposal
from .capability_evolution_request import validate_capability_evolution_request
from .capability_implementation_blueprint import (STEPS_BY_OPERATION,
                                                  validate_capability_implementation_blueprint)
from .capability_implementation_boundary import (
    evaluate_capability_implementation_boundary,
    validate_capability_implementation_boundary_result)
from .capability_registry import MAX_ERRORS

REQUEST_VERSION = 1
BOUNDARY_STATUS = "ready"

STATUS_READY = "ready"
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
STATUS_CONTEXT = "context_mismatch"
STATUS_INVALID_IMPLEMENTATION_REQUEST_ID = "invalid_implementation_request_id"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_REQUEST_ERROR = "request_error"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_INVALID_VALIDATION, STATUS_INVALID_PLAN,
            STATUS_INVALID_PROPOSAL, STATUS_INVALID_CANDIDATE, STATUS_INVALID_READINESS,
            STATUS_INVALID_DESIGN, STATUS_INVALID_DESIGN_VALIDATION, STATUS_INVALID_BLUEPRINT,
            STATUS_INVALID_BLUEPRINT_VALIDATION, STATUS_INVALID_CONTRACT,
            STATUS_INVALID_CONTRACT_VALIDATION, STATUS_INVALID_CONTRACT_READINESS,
            STATUS_INVALID_BOUNDARY, STATUS_CONTEXT, STATUS_INVALID_IMPLEMENTATION_REQUEST_ID,
            STATUS_UNSUPPORTED, STATUS_REQUEST_ERROR, STATUS_ERROR)

FIELDS = ("version", "implementation_request_id", "request_id", "capability_name", "operation",
          "analysis_status", "plan_id", "contract_id", "boundary_status", "purpose", "inputs",
          "outputs", "constraints", "existing_capability", "implementation_allowed",
          "execution_allowed")

# (operation, analysis status)
SUPPORTED = (("create", "create_required"), ("improve", "improve_required"))

# Statuses decided by the Prompt 890 evaluation of the supplied chain; each is also a status
# of this module.
_CHAIN_STATUSES = frozenset(STATUSES) - {STATUS_READY, STATUS_INVALID_BOUNDARY,
                                         STATUS_INVALID_IMPLEMENTATION_REQUEST_ID,
                                         STATUS_REQUEST_ERROR}

ERR_NOT_DICT = "request_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_IMPLEMENTATION_REQUEST_ID = "invalid_implementation_request_id"
ERR_INVALID_CONTRACT_ID = "invalid_contract_id"
ERR_INVALID_BOUNDARY_STATUS = "invalid_boundary_status"
ERR_INVALID_FLAG = "invalid_flag"
ERR_INCONSISTENT = "inconsistent_request"
ERR_INTERNAL = "validation_error"


# ------------------------------------------------------------------ helpers

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


def _build_result(status, request=None):
    return {"status": status, "request": request, "execution_allowed": False,
            "executed": False}


def _id_valid(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


def _boundary_ok(result):
    """The supplied Prompt 890 result must be a valid, ready, fully non-permissive result."""
    if not validate_capability_implementation_boundary_result(result)["valid"]:
        return False
    return (result["status"] == "ready" and result["ready"] is True
            and result["implementation_allowed"] is False
            and result["implementation_started"] is False
            and result["execution_allowed"] is False and result["executed"] is False)


def _boundary_mismatch(result, derived, request, analysis, plan, contract):
    """True when the supplied Prompt 890 result is not the one the chain derives."""
    if not _same(result, derived):
        return True
    pairs = [(result["request_id"], request["request_id"]),
             (result["capability_name"], request["capability_name"]),
             (result["operation"], request["operation"]),
             (result["analysis_status"], analysis["status"]),
             (result["plan_id"], plan["plan_id"]),
             (result["contract_id"], contract["contract_id"])]
    return any(not _same(a, b) for a, b in pairs)


# -------------------------------------------------------------------- build

def build_capability_implementation_request(
        evolution_request=None, analysis_result=None, specification=None, plan=None,
        proposal=None, candidate=None, readiness_result=None, design=None,
        validation_result=None, blueprint=None, blueprint_validation_result=None,
        contract=None, contract_validation_result=None, contract_readiness_result=None,
        boundary_result=None, implementation_request_id=None):
    """Build a fresh normalized implementation request, or report the first failing check."""
    try:
        request, analysis, spec = evolution_request, analysis_result, specification
        readiness, vresult, bresult = readiness_result, validation_result, \
            blueprint_validation_result
        creport, rresult = contract_validation_result, contract_readiness_result

        # Checks 1-15 and the context / support decision of the trusted chain: the Prompt 890
        # boundary re-derives the whole chain (valid objects, forged 887 / 888 / 889 results).
        derived = evaluate_capability_implementation_boundary(
            request, analysis, spec, plan, proposal, candidate, readiness, design, vresult,
            blueprint, bresult, contract, creport, rresult)
        if derived["status"] != "ready":
            status = derived["status"]
            return _build_result(status if status in _CHAIN_STATUSES else STATUS_ERROR)

        # The chain is trusted: validate the supplied Prompt 890 boundary result against it.
        if not validate_capability_evolution_request(request)["valid"]:
            return _build_result(STATUS_INVALID_REQUEST)
        if not _boundary_ok(boundary_result):
            return _build_result(STATUS_INVALID_BOUNDARY)
        if _boundary_mismatch(boundary_result, derived, request, analysis, plan, contract):
            return _build_result(STATUS_CONTEXT)

        if implementation_request_id is None or not _id_valid(implementation_request_id):
            return _build_result(STATUS_INVALID_IMPLEMENTATION_REQUEST_ID)
        if (request["operation"], analysis["status"]) not in SUPPORTED:
            return _build_result(STATUS_UNSUPPORTED)

        built = {
            "version": REQUEST_VERSION,
            "implementation_request_id": implementation_request_id,
            "request_id": request["request_id"],
            "capability_name": request["capability_name"],
            "operation": request["operation"],
            "analysis_status": analysis["status"],
            "plan_id": plan["plan_id"],
            "contract_id": contract["contract_id"],
            "boundary_status": BOUNDARY_STATUS,
            "purpose": candidate["purpose"],
            "inputs": list(request["inputs"]),
            "outputs": list(request["outputs"]),
            "constraints": list(request["constraints"]),
            "existing_capability": copy.deepcopy(analysis["existing"]),
            "implementation_allowed": False,
            "execution_allowed": False,
        }
        if _request_errors(built):
            return _build_result(STATUS_REQUEST_ERROR)
        return _build_result(STATUS_READY, built)
    except Exception:
        return _build_result(STATUS_ERROR)


# --------------------------------------------------------------- validation

def _blueprint_view(request):
    # The request shares every identity / content field with a blueprint; the blueprint-only
    # fields are fixed here so the Prompt 886 validator checks the shared fields (ids, text,
    # lists, existing capability, operation / status consistency) without re-implementing them.
    operation = request["operation"]
    steps = STEPS_BY_OPERATION.get(operation) if type(operation) is str else None
    return {"version": REQUEST_VERSION, "blueprint_id": "bp", "request_id": request["request_id"],
            "operation": operation, "capability_name": request["capability_name"],
            "purpose": request["purpose"], "inputs": request["inputs"],
            "outputs": request["outputs"], "constraints": request["constraints"],
            "existing_capability": request["existing_capability"],
            "analysis_status": request["analysis_status"], "plan_id": request["plan_id"],
            "proposal_id": "prop", "candidate_id": "cand", "design_id": "des",
            "implementation_steps": list(steps) if steps is not None else []}


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

    if type(request["version"]) is not int or request["version"] != REQUEST_VERSION:
        add(ERR_INVALID_VERSION, "version")
    if not _id_valid(request["implementation_request_id"]):
        add(ERR_INVALID_IMPLEMENTATION_REQUEST_ID, "implementation_request_id")
    if not _id_valid(request["contract_id"]):
        add(ERR_INVALID_CONTRACT_ID, "contract_id")
    if type(request["boundary_status"]) is not str or \
            request["boundary_status"] != BOUNDARY_STATUS:
        add(ERR_INVALID_BOUNDARY_STATUS, "boundary_status")
    for key in ("implementation_allowed", "execution_allowed"):
        if request[key] is not False:
            add(ERR_INVALID_FLAG, key)

    for error in validate_capability_implementation_blueprint(_blueprint_view(request))["errors"]:
        code, where = error["code"], error["where"]
        if where in ("version", "blueprint_id", "implementation_steps", "proposal_id",
                     "candidate_id", "design_id"):
            continue  # blueprint-only view fields
        if code == "inconsistent_blueprint":
            code = ERR_INCONSISTENT
        add(code, where)

    pair = (request["operation"], request["analysis_status"])
    if type(pair[0]) is str and type(pair[1]) is str and pair not in SUPPORTED:
        add(ERR_INCONSISTENT, "operation")
    return errors


def validate_capability_implementation_request(request=None):
    """Validation result for a normalized capability implementation request."""
    try:
        errors = _request_errors(request)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "request"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
