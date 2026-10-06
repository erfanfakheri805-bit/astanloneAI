"""
Capability Implementation Contract (Prompt 888, Section 16 - Capability Creation & Improvement)
================================================================================================
A deterministic, read-only, DESCRIPTIVE implementation contract derived from the fully
validated capability-evolution chain through Prompt 887:

    request -> analysis -> specification -> plan -> proposal -> candidate -> readiness
            -> implementation design -> design validation result (885)
            -> implementation blueprint (886) -> blueprint validation result (887)
            -> implementation contract

The contract lists the structural REQUIREMENTS a future implementation would have to
satisfy. It is not an implementation: it contains no source code, patch, command,
filesystem path or executable / automatic action, and it never claims that any
implementation has occurred. Nothing is generated, written, persisted (Memory), executed
(AEL / research), installed, loaded, replaced or sent over a network / API / model; the
registry and project are untouched; self-modification is never performed or authorized.
Caller data is never normalized, altered or repaired (everything is copied into fresh
objects).

  build_capability_implementation_contract(evolution_request, analysis_result, specification,
        plan, proposal, candidate, readiness_result, design, validation_result, blueprint,
        blueprint_validation_result, contract_id=None)
  validate_capability_implementation_contract(contract)

The public validators / builders of Prompts 876-887 are reused, not re-implemented.
Build checks run in this fixed order; the first failure decides the status:
   1 request invalid                       invalid_request
   2 analysis invalid                      invalid_analysis
   3 specification invalid                 invalid_specification
   4 Prompt 879 context invalid result     invalid_validation
   5 plan invalid                          invalid_plan
   6 proposal invalid                      invalid_proposal
   7 definition candidate invalid          invalid_candidate
   8 readiness result invalid, or valid but not status "ready" / ready True /
     execution_allowed False               invalid_readiness
   9 implementation design invalid         invalid_design
  10 Prompt 885 validation result invalid, or valid but not status "valid" / valid True
                                           invalid_design_validation
  11 implementation blueprint invalid      invalid_blueprint
  12 Prompt 887 validation result invalid, or valid but not status "valid" / valid True
                                           invalid_blueprint_validation
  13 chain disagreement                    context_mismatch
      the complete chain is re-validated with the Prompt 887 context validator; the
      supplied Prompt 887 result must equal (type-strict) the result it derives and agree
      with the trusted objects (request_id, capability_name, operation, analysis_status,
      plan_id, proposal_id, candidate_id, design_id, blueprint_id). A forged but
      individually valid object (including a forged "valid" validation result) never passes.
  14 contract_id missing or invalid        invalid_contract_id
  15 unsupported operation / status        unsupported_status
      supported: create  + create_required  + create_implementation
                 improve + improve_required + improve_implementation
      (improve_or_conflict never produces a contract)
  16 built contract fails its validator    contract_error
Any unexpected internal failure -> validation_error.

contract_id is caller-supplied (text, <= 64 chars, the request-id rule), never generated.

Normalized contract (exactly these seventeen keys):
  {"version", "contract_id", "request_id", "operation", "capability_name", "purpose",
   "inputs", "outputs", "constraints", "existing_capability", "analysis_status", "plan_id",
   "proposal_id", "candidate_id", "design_id", "blueprint_id", "requirements"}
  version integer 1; purpose / inputs / outputs / constraints / existing_capability /
  every id from the trusted validated chain (order kept, deep copies); requirements:
      create  -> interface_must_be_defined, inputs_must_be_validated,
                 outputs_must_be_defined, constraints_must_be_respected,
                 behavior_boundary_must_be_defined, tests_must_cover_required_behavior
      improve -> existing_behavior_must_be_preserved, interface_delta_must_be_defined,
                 inputs_must_be_validated, outputs_must_remain_valid,
                 constraints_must_be_respected, regression_tests_must_cover_existing_behavior
  There is no execution flag inside the normalized contract.

Builder result (exactly these keys, fresh every call):
  {"status", "contract", "execution_allowed", "executed"}
status "ready" only together with a valid contract (else contract is None); both flags False.

validate_capability_implementation_contract(contract) checks the exact 17-key shape and every
invariant (reusing the Prompt 886 blueprint validator on a blueprint-shaped view for the
shared fields). Result: {"valid", "errors", "execution_allowed", "executed"}, errors
[{"code", "where"}], at most MAX_ERRORS; purely structural, read-only, never raises.
"""

import copy

from .capability_definition_candidate import validate_capability_definition_candidate
from .capability_definition_readiness import validate_capability_definition_readiness
from .capability_evolution_analysis import validate_capability_evolution_analysis
from .capability_evolution_plan import validate_capability_evolution_plan
from .capability_evolution_proposal import validate_capability_evolution_proposal
from .capability_evolution_request import validate_capability_evolution_request
from .capability_evolution_specification import validate_capability_evolution_specification
from .capability_evolution_validation import (validate_capability_evolution,
                                              validate_capability_evolution_result)
from .capability_implementation_blueprint import (STEPS_BY_OPERATION,
                                                  validate_capability_implementation_blueprint)
from .capability_implementation_blueprint_validation import (
    validate_capability_implementation_blueprint_context,
    validate_capability_implementation_blueprint_validation_result)
from .capability_implementation_design import validate_capability_implementation_design
from .capability_implementation_design_validation import (
    validate_capability_implementation_design_validation_result)
from .capability_registry import MAX_ERRORS

CONTRACT_VERSION = 1

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
STATUS_CONTEXT = "context_mismatch"
STATUS_INVALID_CONTRACT_ID = "invalid_contract_id"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_CONTRACT_ERROR = "contract_error"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_INVALID_VALIDATION, STATUS_INVALID_PLAN,
            STATUS_INVALID_PROPOSAL, STATUS_INVALID_CANDIDATE, STATUS_INVALID_READINESS,
            STATUS_INVALID_DESIGN, STATUS_INVALID_DESIGN_VALIDATION, STATUS_INVALID_BLUEPRINT,
            STATUS_INVALID_BLUEPRINT_VALIDATION, STATUS_CONTEXT, STATUS_INVALID_CONTRACT_ID,
            STATUS_UNSUPPORTED, STATUS_CONTRACT_ERROR, STATUS_ERROR)

FIELDS = ("version", "contract_id", "request_id", "operation", "capability_name", "purpose",
          "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
          "plan_id", "proposal_id", "candidate_id", "design_id", "blueprint_id",
          "requirements")

# (operation, analysis status, design type)
SUPPORTED = (("create", "create_required", "create_implementation"),
             ("improve", "improve_required", "improve_implementation"))

CREATE_REQUIREMENTS = ("interface_must_be_defined", "inputs_must_be_validated",
                       "outputs_must_be_defined", "constraints_must_be_respected",
                       "behavior_boundary_must_be_defined",
                       "tests_must_cover_required_behavior")
IMPROVE_REQUIREMENTS = ("existing_behavior_must_be_preserved", "interface_delta_must_be_defined",
                        "inputs_must_be_validated", "outputs_must_remain_valid",
                        "constraints_must_be_respected",
                        "regression_tests_must_cover_existing_behavior")
REQUIREMENTS_BY_OPERATION = {"create": CREATE_REQUIREMENTS, "improve": IMPROVE_REQUIREMENTS}

ERR_NOT_DICT = "contract_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_CONTRACT_ID = "invalid_contract_id"
ERR_INVALID_BLUEPRINT_ID = "invalid_blueprint_id"
ERR_INVALID_REQUIREMENTS = "invalid_requirements"
ERR_INCONSISTENT = "inconsistent_contract"
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


def _build_result(status, contract=None):
    return {"status": status, "contract": contract, "execution_allowed": False,
            "executed": False}


def _id_valid(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


def _blueprint_validation_mismatch(result, derived, request, analysis, plan, proposal,
                                   candidate, design, blueprint):
    """True when the supplied Prompt 887 result is not the one the chain derives."""
    if not _same(result, derived):
        return True
    pairs = [(result["request_id"], request["request_id"]),
             (result["capability_name"], request["capability_name"]),
             (result["operation"], request["operation"]),
             (result["analysis_status"], analysis["status"]),
             (result["plan_id"], plan["plan_id"]),
             (result["proposal_id"], proposal["proposal_id"]),
             (result["candidate_id"], candidate["candidate_id"]),
             (result["design_id"], design["design_id"]),
             (result["blueprint_id"], blueprint["blueprint_id"])]
    return any(not _same(a, b) for a, b in pairs)


# -------------------------------------------------------------------- build

def build_capability_implementation_contract(evolution_request=None, analysis_result=None,
                                             specification=None, plan=None, proposal=None,
                                             candidate=None, readiness_result=None,
                                             design=None, validation_result=None,
                                             blueprint=None, blueprint_validation_result=None,
                                             contract_id=None):
    """Build a fresh normalized contract, or report the first failing check."""
    try:
        request, analysis, spec = evolution_request, analysis_result, specification
        readiness, vresult, bresult = readiness_result, validation_result, \
            blueprint_validation_result
        if not validate_capability_evolution_request(request)["valid"]:
            return _build_result(STATUS_INVALID_REQUEST)
        if not validate_capability_evolution_analysis(analysis)["valid"]:
            return _build_result(STATUS_INVALID_ANALYSIS)
        if not validate_capability_evolution_specification(spec)["valid"]:
            return _build_result(STATUS_INVALID_SPECIFICATION)
        context = validate_capability_evolution(request, analysis, spec)
        if not validate_capability_evolution_result(context)["valid"]:
            return _build_result(STATUS_INVALID_VALIDATION)
        if not validate_capability_evolution_plan(plan)["valid"]:
            return _build_result(STATUS_INVALID_PLAN)
        if not validate_capability_evolution_proposal(proposal)["valid"]:
            return _build_result(STATUS_INVALID_PROPOSAL)
        if not validate_capability_definition_candidate(candidate)["valid"]:
            return _build_result(STATUS_INVALID_CANDIDATE)
        if not validate_capability_definition_readiness(readiness)["valid"]:
            return _build_result(STATUS_INVALID_READINESS)
        if (readiness["status"] != "ready" or readiness["ready"] is not True
                or readiness["execution_allowed"] is not False):
            return _build_result(STATUS_INVALID_READINESS)
        if not validate_capability_implementation_design(design)["valid"]:
            return _build_result(STATUS_INVALID_DESIGN)
        if not validate_capability_implementation_design_validation_result(vresult)["valid"]:
            return _build_result(STATUS_INVALID_DESIGN_VALIDATION)
        if vresult["status"] != "valid" or vresult["valid"] is not True:
            return _build_result(STATUS_INVALID_DESIGN_VALIDATION)
        if not validate_capability_implementation_blueprint(blueprint)["valid"]:
            return _build_result(STATUS_INVALID_BLUEPRINT)
        if not validate_capability_implementation_blueprint_validation_result(
                bresult)["valid"]:
            return _build_result(STATUS_INVALID_BLUEPRINT_VALIDATION)
        if bresult["status"] != "valid" or bresult["valid"] is not True:
            return _build_result(STATUS_INVALID_BLUEPRINT_VALIDATION)

        derived = validate_capability_implementation_blueprint_context(
            request, analysis, spec, plan, proposal, candidate, readiness, design, vresult,
            blueprint)
        if derived["status"] == "unsupported_status":
            return _build_result(STATUS_UNSUPPORTED)
        if derived["status"] != "valid":
            return _build_result(STATUS_CONTEXT)
        if _blueprint_validation_mismatch(bresult, derived, request, analysis, plan, proposal,
                                          candidate, design, blueprint):
            return _build_result(STATUS_CONTEXT)

        if contract_id is None or not _id_valid(contract_id):
            return _build_result(STATUS_INVALID_CONTRACT_ID)
        combo = (request["operation"], analysis["status"], design["design_type"])
        if combo not in SUPPORTED or context["ready"] is not True:
            return _build_result(STATUS_UNSUPPORTED)

        contract = {
            "version": CONTRACT_VERSION,
            "contract_id": contract_id,
            "request_id": request["request_id"],
            "operation": request["operation"],
            "capability_name": request["capability_name"],
            "purpose": blueprint["purpose"],
            "inputs": list(request["inputs"]),
            "outputs": list(request["outputs"]),
            "constraints": list(request["constraints"]),
            "existing_capability": copy.deepcopy(analysis["existing"]),
            "analysis_status": analysis["status"],
            "plan_id": plan["plan_id"],
            "proposal_id": proposal["proposal_id"],
            "candidate_id": candidate["candidate_id"],
            "design_id": design["design_id"],
            "blueprint_id": blueprint["blueprint_id"],
            "requirements": list(REQUIREMENTS_BY_OPERATION[request["operation"]]),
        }
        if _contract_errors(contract):
            return _build_result(STATUS_CONTRACT_ERROR)
        return _build_result(STATUS_READY, contract)
    except Exception:
        return _build_result(STATUS_ERROR)


# --------------------------------------------------------------- validation

def _blueprint_view(contract):
    # The contract shares every identity / content field with a blueprint; the blueprint-only
    # fields are fixed here so the Prompt 886 validator checks the shared fields (ids, text,
    # lists, existing capability, operation / status consistency) without re-implementing them.
    operation = contract["operation"]
    steps = STEPS_BY_OPERATION.get(operation) if type(operation) is str else None
    return {"version": CONTRACT_VERSION, "blueprint_id": "bp", "request_id": contract["request_id"],
            "operation": operation, "capability_name": contract["capability_name"],
            "purpose": contract["purpose"], "inputs": contract["inputs"],
            "outputs": contract["outputs"], "constraints": contract["constraints"],
            "existing_capability": contract["existing_capability"],
            "analysis_status": contract["analysis_status"], "plan_id": contract["plan_id"],
            "proposal_id": contract["proposal_id"], "candidate_id": contract["candidate_id"],
            "design_id": contract["design_id"],
            "implementation_steps": list(steps) if steps is not None else []}


def _contract_errors(contract):
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(contract) is not dict:
        add(ERR_NOT_DICT, "contract")
        return errors
    for key in FIELDS:
        if key not in contract:
            add(ERR_MISSING_KEY, key)
    for key in contract:
        if type(key) is not str or key not in FIELDS:
            add(ERR_UNEXPECTED_KEY,
                key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    if type(contract["version"]) is not int or contract["version"] != CONTRACT_VERSION:
        add(ERR_INVALID_VERSION, "version")
    if not _id_valid(contract["contract_id"]):
        add(ERR_INVALID_CONTRACT_ID, "contract_id")
    if not _id_valid(contract["blueprint_id"]):
        add(ERR_INVALID_BLUEPRINT_ID, "blueprint_id")

    for error in validate_capability_implementation_blueprint(_blueprint_view(contract))["errors"]:
        code, where = error["code"], error["where"]
        if where in ("version", "blueprint_id", "implementation_steps"):
            continue  # blueprint-only view fields
        if code == "inconsistent_blueprint":
            code = ERR_INCONSISTENT
        add(code, where)

    requirements = contract["requirements"]
    operation = contract["operation"]
    expected = REQUIREMENTS_BY_OPERATION.get(operation) if type(operation) is str else None
    if type(requirements) is not list or any(type(r) is not str for r in requirements):
        add(ERR_INVALID_REQUIREMENTS, "requirements")
    elif expected is not None and not _same(requirements, list(expected)):
        add(ERR_INVALID_REQUIREMENTS, "requirements")
    return errors


def validate_capability_implementation_contract(contract=None):
    """Validation result for a normalized capability implementation contract."""
    try:
        errors = _contract_errors(contract)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "contract"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
