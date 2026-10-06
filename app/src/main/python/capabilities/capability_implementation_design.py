"""
Capability Implementation Design (Prompt 884, Section 16 - Capability Creation & Improvement)
===============================================================================================
A deterministic, read-only implementation-DESIGN CONTRACT for a capability definition that
passed the Prompt 883 readiness boundary. It describes WHAT an eventual implementation would
need to satisfy; it is not the implementation. No source code or patch is generated; no
capability is created, modified, installed, loaded or replaced; the registry is untouched;
nothing is written, executed, persisted (Memory), run (AEL / research) or sent over a
network / API / model; self-modification is never performed or authorized. Caller data is
never normalized, altered or repaired (everything is copied into fresh objects).

Readiness (Prompt 883) means "the definition candidate may enter a design stage". The design
therefore NEVER claims the implementation is ready: implementation_ready and
execution_allowed are always False.

  build_capability_implementation_design(evolution_request, analysis_result, specification,
                                         plan, proposal, candidate, readiness_result,
                                         design_id=None)
  validate_capability_implementation_design(design)

Prompts 876-883 public validators / builders are reused, not re-implemented (request,
analysis, specification, validate_capability_evolution(+_result), plan, proposal, definition
candidate, readiness result). Build checks run in this fixed order; first failure decides:
   1 request invalid                    invalid_request
   2 analysis invalid                   invalid_analysis
   3 specification invalid              invalid_specification
   4 Prompt 879 context invalid result  invalid_validation
   5 plan invalid                       invalid_plan
   6 proposal invalid                   invalid_proposal
   7 candidate invalid                  invalid_candidate
   8 readiness result invalid, or valid but not status "ready" / ready True /
     execution_allowed False            invalid_readiness
   9-11 chain disagreement              context_mismatch
      explicit type-strict comparison of every shared field between request, analysis,
      specification, plan, proposal and candidate; the candidate must equal the one the
      Prompt 882 builder derives from the first five objects and the supplied candidate_id
      (covers candidate_id); the readiness result must equal the one the Prompt 883
      evaluator derives from the six objects AND agree field by field (request_id,
      capability_name, operation, analysis_status, plan_id, proposal_id). A forged but
      individually valid readiness result therefore never passes.
  12 design_id missing or invalid       invalid_design_id
  13 unsupported operation/status       unsupported_status
      supported: create + create_required + create_capability,
                 improve + improve_required + improve_capability
      (improve_or_conflict never produces a design; it is stopped earlier and this is the
      final guard)
  14 built design fails its validator   design_error
Any unexpected internal failure -> validation_error.

design_id is caller-supplied (text, <= 64 chars, the request-id rule), never generated.

Normalized design (exactly these seventeen keys):
  {"version", "design_id", "request_id", "operation", "capability_name", "purpose", "inputs",
   "outputs", "constraints", "existing_capability", "analysis_status", "plan_id",
   "proposal_id", "candidate_id", "design_type", "implementation_ready", "execution_allowed"}
  version integer 1 (not the text "1"; corrected in Prompt 885); purpose is exactly the request goal; lists copied
  with order kept; create -> analysis_status "create_required", design_type
  "create_implementation", existing_capability None; improve -> "improve_required",
  "improve_implementation", existing_capability a deep copy of the validated matching
  descriptor; implementation_ready and execution_allowed exactly False.

Builder result (exactly these keys, fresh every call):
  {"status", "design", "execution_allowed", "executed"}
status "ready" only together with a valid design (else design is None); both flags False.

validate_capability_implementation_design(design) checks the exact 17-key shape and every
invariant (reusing the Prompt 882 candidate validator on a candidate-shaped view for the
shared fields). Result: {"valid", "errors", "execution_allowed", "executed"}, errors
[{"code", "where"}], at most MAX_ERRORS; purely structural, read-only, never raises.
"""

import copy

from .capability_definition_candidate import (build_capability_definition_candidate,
                                              validate_capability_definition_candidate)
from .capability_definition_readiness import (evaluate_capability_definition_readiness,
                                              validate_capability_definition_readiness)
from .capability_evolution_analysis import validate_capability_evolution_analysis
from .capability_evolution_plan import validate_capability_evolution_plan
from .capability_evolution_proposal import validate_capability_evolution_proposal
from .capability_evolution_request import (REQUEST_VERSION,
                                           validate_capability_evolution_request)
from .capability_evolution_specification import validate_capability_evolution_specification
from .capability_evolution_validation import (validate_capability_evolution,
                                              validate_capability_evolution_result)
from .capability_registry import MAX_ERRORS

DESIGN_VERSION = 1  # integer (Prompt 885 correction); the request/candidate version stays text

STATUS_READY = "ready"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_ANALYSIS = "invalid_analysis"
STATUS_INVALID_SPECIFICATION = "invalid_specification"
STATUS_INVALID_VALIDATION = "invalid_validation"
STATUS_INVALID_PLAN = "invalid_plan"
STATUS_INVALID_PROPOSAL = "invalid_proposal"
STATUS_INVALID_CANDIDATE = "invalid_candidate"
STATUS_INVALID_READINESS = "invalid_readiness"
STATUS_CONTEXT = "context_mismatch"
STATUS_INVALID_DESIGN_ID = "invalid_design_id"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_DESIGN_ERROR = "design_error"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_INVALID_VALIDATION, STATUS_INVALID_PLAN,
            STATUS_INVALID_PROPOSAL, STATUS_INVALID_CANDIDATE, STATUS_INVALID_READINESS,
            STATUS_CONTEXT, STATUS_INVALID_DESIGN_ID, STATUS_UNSUPPORTED, STATUS_DESIGN_ERROR,
            STATUS_ERROR)

FIELDS = ("version", "design_id", "request_id", "operation", "capability_name", "purpose",
          "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
          "plan_id", "proposal_id", "candidate_id", "design_type", "implementation_ready",
          "execution_allowed")

# (operation, analysis status, proposal type, design type)
SUPPORTED = (("create", "create_required", "create_capability", "create_implementation"),
             ("improve", "improve_required", "improve_capability", "improve_implementation"))
DESIGN_TYPES = ("create_implementation", "improve_implementation")

ERR_NOT_DICT = "design_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_DESIGN_ID = "invalid_design_id"
ERR_INVALID_CANDIDATE_ID = "invalid_candidate_id"
ERR_INVALID_DESIGN_TYPE = "invalid_design_type"
ERR_INVALID_IMPLEMENTATION_READY = "invalid_implementation_ready"
ERR_INVALID_EXECUTION_ALLOWED = "invalid_execution_allowed"
ERR_INCONSISTENT = "inconsistent_design"
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


def _build_result(status, design=None):
    return {"status": status, "design": design, "execution_allowed": False, "executed": False}


def _id_valid(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


def _chain_mismatch(request, analysis, spec, plan, proposal, candidate, readiness):
    r_id, r_name, r_op = request["request_id"], request["capability_name"], request["operation"]
    status, existing = analysis["status"], analysis["existing"]
    pairs = [
        (analysis["operation"], r_op), (analysis["capability_name"], r_name),
        (spec["request_id"], r_id), (spec["operation"], r_op),
        (spec["capability_name"], r_name), (spec["analysis_status"], status),
        (spec["existing_capability"], existing),
        (plan["request_id"], r_id), (plan["operation"], r_op),
        (plan["capability_name"], r_name), (plan["analysis_status"], status),
        (plan["existing_capability"], existing),
        (proposal["request_id"], r_id), (proposal["operation"], r_op),
        (proposal["capability_name"], r_name), (proposal["analysis_status"], status),
        (proposal["existing_capability"], existing), (proposal["plan_id"], plan["plan_id"]),
        (candidate["request_id"], r_id), (candidate["operation"], r_op),
        (candidate["capability_name"], r_name), (candidate["analysis_status"], status),
        (candidate["existing_capability"], existing), (candidate["plan_id"], plan["plan_id"]),
        (candidate["proposal_id"], proposal["proposal_id"]),
        (candidate["purpose"], request["goal"]),
        (readiness["request_id"], r_id), (readiness["capability_name"], r_name),
        (readiness["operation"], r_op), (readiness["analysis_status"], status),
        (readiness["plan_id"], plan["plan_id"]),
        (readiness["proposal_id"], proposal["proposal_id"]),
    ]
    for key in ("goal", "inputs", "outputs", "constraints"):
        for doc in (spec, plan, proposal):
            pairs.append((doc[key], request[key]))
    for key in ("inputs", "outputs", "constraints"):
        pairs.append((candidate[key], request[key]))
    return any(not _same(a, b) for a, b in pairs)


# -------------------------------------------------------------------- build

def build_capability_implementation_design(evolution_request=None, analysis_result=None,
                                           specification=None, plan=None, proposal=None,
                                           candidate=None, readiness_result=None,
                                           design_id=None):
    """Build a fresh normalized design, or report the first failing check."""
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

        if _chain_mismatch(request, analysis, spec, plan, proposal, candidate, readiness):
            return _build_result(STATUS_CONTEXT)
        derived_candidate = build_capability_definition_candidate(
            request, analysis, spec, plan, proposal, candidate["candidate_id"])
        if derived_candidate["status"] != "ready" or not _same(derived_candidate["candidate"],
                                                               candidate):
            return _build_result(STATUS_CONTEXT)
        derived_readiness = evaluate_capability_definition_readiness(
            request, analysis, spec, plan, proposal, candidate)
        if not _same(derived_readiness, readiness):
            return _build_result(STATUS_CONTEXT)

        if design_id is None or not _id_valid(design_id):
            return _build_result(STATUS_INVALID_DESIGN_ID)
        combo = (request["operation"], analysis["status"], proposal["proposal_type"])
        design_type = None
        for operation, status, kind, dtype in SUPPORTED:
            if combo == (operation, status, kind):
                design_type = dtype
        if design_type is None or context["ready"] is not True:
            return _build_result(STATUS_UNSUPPORTED)

        design = {
            "version": DESIGN_VERSION,
            "design_id": design_id,
            "request_id": request["request_id"],
            "operation": request["operation"],
            "capability_name": request["capability_name"],
            "purpose": request["goal"],
            "inputs": list(request["inputs"]),
            "outputs": list(request["outputs"]),
            "constraints": list(request["constraints"]),
            "existing_capability": copy.deepcopy(analysis["existing"]),
            "analysis_status": analysis["status"],
            "plan_id": plan["plan_id"],
            "proposal_id": proposal["proposal_id"],
            "candidate_id": candidate["candidate_id"],
            "design_type": design_type,
            "implementation_ready": False,
            "execution_allowed": False,
        }
        if _design_errors(design):
            return _build_result(STATUS_DESIGN_ERROR)
        return _build_result(STATUS_READY, design)
    except Exception:
        return _build_result(STATUS_ERROR)


# --------------------------------------------------------------- validation

def _candidate_view(design):
    # the Prompt 882 candidate carries the text version "1"; the design's own integer
    # version is checked separately in _design_errors
    return {"version": REQUEST_VERSION, "candidate_id": design["candidate_id"],
            "request_id": design["request_id"], "operation": design["operation"],
            "capability_name": design["capability_name"], "purpose": design["purpose"],
            "inputs": design["inputs"], "outputs": design["outputs"],
            "constraints": design["constraints"],
            "existing_capability": design["existing_capability"],
            "analysis_status": design["analysis_status"], "plan_id": design["plan_id"],
            "proposal_id": design["proposal_id"],
            "execution_allowed": design["execution_allowed"],
            "implementation_ready": design["implementation_ready"]}


def _design_errors(design):
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(design) is not dict:
        add(ERR_NOT_DICT, "design")
        return errors
    for key in FIELDS:
        if key not in design:
            add(ERR_MISSING_KEY, key)
    for key in design:
        if type(key) is not str or key not in FIELDS:
            add(ERR_UNEXPECTED_KEY,
                key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    # Everything shared with a candidate (ids, text, lists, existing capability, status
    # consistency, both flags) is checked by the Prompt 882 validator.
    for error in validate_capability_definition_candidate(_candidate_view(design))["errors"]:
        code = error["code"]
        if code == "invalid_implementation_ready":
            code = ERR_INVALID_IMPLEMENTATION_READY
        elif code == "invalid_execution_allowed":
            code = ERR_INVALID_EXECUTION_ALLOWED
        add(code, error["where"])
    if type(design["version"]) is not int or design["version"] != DESIGN_VERSION:
        add(ERR_INVALID_VERSION, "version")
    if design["implementation_ready"] is not False:
        add(ERR_INVALID_IMPLEMENTATION_READY, "implementation_ready")
    if design["execution_allowed"] is not False:
        add(ERR_INVALID_EXECUTION_ALLOWED, "execution_allowed")
    if not _id_valid(design["design_id"]):
        add(ERR_INVALID_DESIGN_ID, "design_id")

    dtype = design["design_type"]
    if type(dtype) is not str or dtype not in DESIGN_TYPES:
        add(ERR_INVALID_DESIGN_TYPE, "design_type")
    elif (design["operation"], design["analysis_status"], dtype) not in tuple(
            (op, st, dt) for op, st, _, dt in SUPPORTED):
        add(ERR_INCONSISTENT, "design_type")
    if (type(design["operation"]) is str and type(design["analysis_status"]) is str
            and (design["operation"], design["analysis_status"]) not in tuple(
                (op, st) for op, st, _, _ in SUPPORTED)):
        add(ERR_INCONSISTENT, "analysis_status")
    return errors


def validate_capability_implementation_design(design=None):
    """Validation result for a normalized capability implementation design."""
    try:
        errors = _design_errors(design)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "design"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
