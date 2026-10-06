"""
Capability Implementation Blueprint (Prompt 886, Section 16 - Capability Creation & Improvement)
==================================================================================================
A deterministic, read-only, DESCRIPTIVE implementation blueprint derived from the validated
capability-evolution chain through Prompt 885:

    request -> analysis -> specification -> plan -> proposal -> candidate -> readiness
            -> implementation design -> design validation result -> blueprint

It describes HOW a capability would eventually be implemented, as an ordered list of short
structural phase identifiers only. It contains no code, patch, file, path, command, shell or
execution instruction, and it never claims that any implementation has occurred. Nothing is
generated, written, persisted (Memory), executed (AEL / research), installed, loaded,
replaced or sent over a network / API / model; the registry and project are untouched;
self-modification is never performed or authorized. Caller data is never normalized,
altered or repaired (everything is copied into fresh objects).

  build_capability_implementation_blueprint(evolution_request, analysis_result, specification,
                                            plan, proposal, candidate, readiness_result,
                                            design, validation_result, blueprint_id=None)
  validate_capability_implementation_blueprint(blueprint)

The public validators / builders of Prompts 876-885 are reused, not re-implemented.
Build checks run in this fixed order; the first failure decides the status:
   1 request invalid                      invalid_request
   2 analysis invalid                     invalid_analysis
   3 specification invalid                invalid_specification
   4 Prompt 879 context invalid result    invalid_validation
   5 plan invalid                         invalid_plan
   6 proposal invalid                     invalid_proposal
   7 definition candidate invalid         invalid_candidate
   8 readiness result invalid, or valid but not status "ready" / ready True /
     execution_allowed False              invalid_readiness
   9 implementation design invalid        invalid_design
  10 Prompt 885 validation result invalid, or valid but not status "valid" / valid True
                                          invalid_design_validation
  11 chain disagreement                   context_mismatch
      the complete chain is re-validated with the Prompt 885 context validator; the
      supplied validation result must equal (type-strict) the result it derives and agree
      with the trusted objects (request_id, capability_name, operation, analysis_status,
      plan_id, proposal_id, candidate_id, design_id). A forged but individually valid object
      (including a forged "valid" validation result) therefore never passes.
  12 blueprint_id missing or invalid      invalid_blueprint_id
  13 unsupported operation / status       unsupported_status
      supported: create  + create_required  + create_implementation
                 improve + improve_required + improve_implementation
      (improve_or_conflict never produces a blueprint)
  14 built blueprint fails its validator  blueprint_error
Any unexpected internal failure -> validation_error.

blueprint_id is caller-supplied (text, <= 64 chars, the request-id rule), never generated.

Normalized blueprint (exactly these sixteen keys):
  {"version", "blueprint_id", "request_id", "operation", "capability_name", "purpose",
   "inputs", "outputs", "constraints", "existing_capability", "analysis_status", "plan_id",
   "proposal_id", "candidate_id", "design_id", "implementation_steps"}
  version integer 1; purpose from the validated design (equal to the candidate purpose and
  the request goal); inputs / outputs / constraints preserved exactly (order kept);
  existing_capability a deep copy of the validated value; analysis_status, plan_id,
  proposal_id, candidate_id, design_id from their trusted validated objects.
  implementation_steps (structural phase identifiers only):
      create  -> define_interface, define_validation, define_behavior_boundary, define_tests
      improve -> inspect_existing_behavior, define_interface_delta, define_behavior_boundary,
                 define_regression_tests

Builder result (exactly these keys, fresh every call):
  {"status", "blueprint", "execution_allowed", "executed"}
status "ready" only together with a valid blueprint (else blueprint is None); both flags False.

validate_capability_implementation_blueprint(blueprint) checks the exact 16-key shape and
every invariant (reusing the Prompt 884 design validator on a design-shaped view for the
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
from .capability_implementation_design import validate_capability_implementation_design
from .capability_implementation_design_validation import (
    validate_capability_implementation_design_context,
    validate_capability_implementation_design_validation_result)
from .capability_registry import MAX_ERRORS

BLUEPRINT_VERSION = 1

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
STATUS_CONTEXT = "context_mismatch"
STATUS_INVALID_BLUEPRINT_ID = "invalid_blueprint_id"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_BLUEPRINT_ERROR = "blueprint_error"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_INVALID_VALIDATION, STATUS_INVALID_PLAN,
            STATUS_INVALID_PROPOSAL, STATUS_INVALID_CANDIDATE, STATUS_INVALID_READINESS,
            STATUS_INVALID_DESIGN, STATUS_INVALID_DESIGN_VALIDATION, STATUS_CONTEXT,
            STATUS_INVALID_BLUEPRINT_ID, STATUS_UNSUPPORTED, STATUS_BLUEPRINT_ERROR,
            STATUS_ERROR)

FIELDS = ("version", "blueprint_id", "request_id", "operation", "capability_name", "purpose",
          "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
          "plan_id", "proposal_id", "candidate_id", "design_id", "implementation_steps")

# (operation, analysis status, design type)
SUPPORTED = (("create", "create_required", "create_implementation"),
             ("improve", "improve_required", "improve_implementation"))

CREATE_STEPS = ("define_interface", "define_validation", "define_behavior_boundary",
                "define_tests")
IMPROVE_STEPS = ("inspect_existing_behavior", "define_interface_delta",
                 "define_behavior_boundary", "define_regression_tests")
STEPS_BY_OPERATION = {"create": CREATE_STEPS, "improve": IMPROVE_STEPS}

ERR_NOT_DICT = "blueprint_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_BLUEPRINT_ID = "invalid_blueprint_id"
ERR_INVALID_STEPS = "invalid_implementation_steps"
ERR_INCONSISTENT = "inconsistent_blueprint"
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


def _build_result(status, blueprint=None):
    return {"status": status, "blueprint": blueprint, "execution_allowed": False,
            "executed": False}


def _id_valid(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


def _validation_result_mismatch(result, derived, request, analysis, plan, proposal,
                                candidate, design):
    """True when the supplied Prompt 885 result is not the one the chain derives."""
    if not _same(result, derived):
        return True
    pairs = [(result["request_id"], request["request_id"]),
             (result["capability_name"], request["capability_name"]),
             (result["operation"], request["operation"]),
             (result["analysis_status"], analysis["status"]),
             (result["plan_id"], plan["plan_id"]),
             (result["proposal_id"], proposal["proposal_id"]),
             (result["candidate_id"], candidate["candidate_id"]),
             (result["design_id"], design["design_id"])]
    return any(not _same(a, b) for a, b in pairs)


# -------------------------------------------------------------------- build

def build_capability_implementation_blueprint(evolution_request=None, analysis_result=None,
                                              specification=None, plan=None, proposal=None,
                                              candidate=None, readiness_result=None,
                                              design=None, validation_result=None,
                                              blueprint_id=None):
    """Build a fresh normalized blueprint, or report the first failing check."""
    try:
        request, analysis, spec = evolution_request, analysis_result, specification
        readiness = readiness_result
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
        if not validate_capability_implementation_design_validation_result(
                validation_result)["valid"]:
            return _build_result(STATUS_INVALID_DESIGN_VALIDATION)
        if validation_result["status"] != "valid" or validation_result["valid"] is not True:
            return _build_result(STATUS_INVALID_DESIGN_VALIDATION)

        derived = validate_capability_implementation_design_context(
            request, analysis, spec, plan, proposal, candidate, readiness, design)
        if derived["status"] == "unsupported_status":
            return _build_result(STATUS_UNSUPPORTED)
        if derived["status"] != "valid":
            return _build_result(STATUS_CONTEXT)
        if _validation_result_mismatch(validation_result, derived, request, analysis, plan,
                                       proposal, candidate, design):
            return _build_result(STATUS_CONTEXT)

        if blueprint_id is None or not _id_valid(blueprint_id):
            return _build_result(STATUS_INVALID_BLUEPRINT_ID)
        combo = (request["operation"], analysis["status"], design["design_type"])
        if combo not in SUPPORTED or context["ready"] is not True:
            return _build_result(STATUS_UNSUPPORTED)

        blueprint = {
            "version": BLUEPRINT_VERSION,
            "blueprint_id": blueprint_id,
            "request_id": request["request_id"],
            "operation": request["operation"],
            "capability_name": request["capability_name"],
            "purpose": design["purpose"],
            "inputs": list(request["inputs"]),
            "outputs": list(request["outputs"]),
            "constraints": list(request["constraints"]),
            "existing_capability": copy.deepcopy(analysis["existing"]),
            "analysis_status": analysis["status"],
            "plan_id": plan["plan_id"],
            "proposal_id": proposal["proposal_id"],
            "candidate_id": candidate["candidate_id"],
            "design_id": design["design_id"],
            "implementation_steps": list(STEPS_BY_OPERATION[request["operation"]]),
        }
        if _blueprint_errors(blueprint):
            return _build_result(STATUS_BLUEPRINT_ERROR)
        return _build_result(STATUS_READY, blueprint)
    except Exception:
        return _build_result(STATUS_ERROR)


# --------------------------------------------------------------- validation

def _design_view(blueprint):
    # The blueprint shares every identity / content field with a design; the design-only
    # fields are fixed here so the Prompt 884 validator checks the shared fields (ids, text,
    # lists, existing capability, operation / status consistency) without re-implementing them.
    operation = blueprint["operation"]
    dtype = {"create": "create_implementation",
             "improve": "improve_implementation"}.get(operation)
    return {"version": BLUEPRINT_VERSION, "design_id": blueprint["design_id"],
            "request_id": blueprint["request_id"], "operation": operation,
            "capability_name": blueprint["capability_name"], "purpose": blueprint["purpose"],
            "inputs": blueprint["inputs"], "outputs": blueprint["outputs"],
            "constraints": blueprint["constraints"],
            "existing_capability": blueprint["existing_capability"],
            "analysis_status": blueprint["analysis_status"], "plan_id": blueprint["plan_id"],
            "proposal_id": blueprint["proposal_id"], "candidate_id": blueprint["candidate_id"],
            "design_type": dtype, "implementation_ready": False, "execution_allowed": False}


def _blueprint_errors(blueprint):
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(blueprint) is not dict:
        add(ERR_NOT_DICT, "blueprint")
        return errors
    for key in FIELDS:
        if key not in blueprint:
            add(ERR_MISSING_KEY, key)
    for key in blueprint:
        if type(key) is not str or key not in FIELDS:
            add(ERR_UNEXPECTED_KEY,
                key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    if type(blueprint["version"]) is not int or blueprint["version"] != BLUEPRINT_VERSION:
        add(ERR_INVALID_VERSION, "version")
    if not _id_valid(blueprint["blueprint_id"]):
        add(ERR_INVALID_BLUEPRINT_ID, "blueprint_id")

    for error in validate_capability_implementation_design(_design_view(blueprint))["errors"]:
        code, where = error["code"], error["where"]
        if where in ("design_type", "implementation_ready", "execution_allowed", "version",
                     "design_id"):
            continue  # design-only view fields / checked explicitly below
        add(code, where)
    if not _id_valid(blueprint["design_id"]):
        add("invalid_design_id", "design_id")

    steps = blueprint["implementation_steps"]
    operation = blueprint["operation"]
    expected = STEPS_BY_OPERATION.get(operation) if type(operation) is str else None
    if type(steps) is not list or any(type(s) is not str for s in steps):
        add(ERR_INVALID_STEPS, "implementation_steps")
    elif expected is not None and not _same(steps, list(expected)):
        add(ERR_INVALID_STEPS, "implementation_steps")
    if (type(blueprint["operation"]) is str and type(blueprint["analysis_status"]) is str
            and (blueprint["operation"], blueprint["analysis_status"]) not in tuple(
                (op, st) for op, st, _ in SUPPORTED)):
        add(ERR_INCONSISTENT, "analysis_status")
    return errors


def validate_capability_implementation_blueprint(blueprint=None):
    """Validation result for a normalized capability implementation blueprint."""
    try:
        errors = _blueprint_errors(blueprint)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "blueprint"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
