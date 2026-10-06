"""
Capability Implementation Blueprint Validation (Prompt 887, Section 16)
=========================================================================
A deterministic, read-only validation boundary over the complete Section 16 chain through
Prompt 886:

    request -> analysis -> specification -> plan -> proposal -> candidate -> readiness
            -> implementation design -> design validation result -> implementation blueprint

It answers only: "is this blueprint exactly the blueprint derivable from the trusted,
validated chain?" It never generates code, creates files, touches the registry or project,
and never executes, writes, persists, researches, networks, calls an API or model,
installs / loads / replaces a capability, or self-modifies. Caller data is never
normalized, altered or repaired.

  validate_capability_implementation_blueprint_context(evolution_request, analysis_result,
        specification, plan, proposal, candidate, readiness_result, design,
        validation_result, blueprint)
  validate_capability_implementation_blueprint_validation_result(result)

The public validators / builders of Prompts 876-886 are reused, not re-implemented.
Checks run in this fixed order; the first failure decides the status:
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
  12-17 chain disagreement                 context_mismatch
      explicit type-strict comparison of request_id, capability_name, operation,
      goal/purpose, inputs, outputs, constraints, existing_capability, analysis_status,
      plan_id, proposal_id, candidate_id, design_id, design_type, blueprint_id and
      implementation_steps across all objects; the candidate, readiness result, design,
      Prompt 885 validation result and blueprint must each equal the object the Prompt
      882 / 883 / 884 / 885 / 886 builders and validators derive from the rest of the
      chain, so a forged but individually valid object cannot pass.
  18 unsupported operation / status        unsupported_status
      supported: create  + create_required  + create_capability  + create_implementation
                 improve + improve_required + improve_capability + improve_implementation
      (improve_or_conflict never validates)
  19 determination                         valid
Any unexpected internal failure -> validation_error.

Result (exactly these thirteen keys, fresh every call):
  {"version", "status", "valid", "request_id", "capability_name", "operation",
   "analysis_status", "plan_id", "proposal_id", "candidate_id", "design_id",
   "blueprint_id", "reason"}
version is the integer 1; valid is True only when status == "valid"; reason equals the
status; there is no execution flag in the result itself (the result validator's own report,
like every validator of the series, carries execution_allowed / executed False). Identity
fields come only from validated, trusted objects: invalid_request and validation_error carry
none; every other non-valid status carries only the request identity (request_id,
capability_name, operation) and, once the analysis is validated, its analysis_status
(invalid_analysis: request identity only); plan_id, proposal_id, candidate_id, design_id and
blueprint_id are populated only for "valid".
"""

from .capability_definition_candidate import validate_capability_definition_candidate
from .capability_definition_readiness import validate_capability_definition_readiness
from .capability_evolution_analysis import validate_capability_evolution_analysis
from .capability_evolution_plan import validate_capability_evolution_plan
from .capability_evolution_proposal import validate_capability_evolution_proposal
from .capability_evolution_request import validate_capability_evolution_request
from .capability_evolution_specification import validate_capability_evolution_specification
from .capability_evolution_validation import (validate_capability_evolution,
                                              validate_capability_evolution_result)
from .capability_implementation_blueprint import (build_capability_implementation_blueprint,
                                                  validate_capability_implementation_blueprint)
from .capability_implementation_design import validate_capability_implementation_design
from .capability_implementation_design_validation import (
    validate_capability_implementation_design_context,
    validate_capability_implementation_design_validation_result)
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
STATUS_CONTEXT = "context_mismatch"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_VALID, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_INVALID_VALIDATION, STATUS_INVALID_PLAN,
            STATUS_INVALID_PROPOSAL, STATUS_INVALID_CANDIDATE, STATUS_INVALID_READINESS,
            STATUS_INVALID_DESIGN, STATUS_INVALID_DESIGN_VALIDATION, STATUS_INVALID_BLUEPRINT,
            STATUS_CONTEXT, STATUS_UNSUPPORTED, STATUS_ERROR)

RESULT_KEYS = ("version", "status", "valid", "request_id", "capability_name", "operation",
               "analysis_status", "plan_id", "proposal_id", "candidate_id", "design_id",
               "blueprint_id", "reason")

# (operation, analysis status, proposal type, design type)
SUPPORTED = (("create", "create_required", "create_capability", "create_implementation"),
             ("improve", "improve_required", "improve_capability", "improve_implementation"))
_ANALYSIS_STATUSES = ("create_required", "improve_required", "improve_or_conflict")

_NO_IDS = frozenset((STATUS_INVALID_REQUEST, STATUS_ERROR))
_REQUEST_ONLY = frozenset((STATUS_INVALID_ANALYSIS,))
_IDS = ("request_id", "capability_name", "operation")
_LATER_IDS = ("plan_id", "proposal_id", "candidate_id", "design_id", "blueprint_id")

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


def _result(status, request=None, analysis_status=None, plan_id=None, proposal_id=None,
            candidate_id=None, design_id=None, blueprint_id=None):
    ids = (None, None, None)
    if request is not None:
        ids = (request["request_id"], request["capability_name"], request["operation"])
    return {"version": VALIDATION_VERSION, "status": status, "valid": status == STATUS_VALID,
            "request_id": ids[0], "capability_name": ids[1], "operation": ids[2],
            "analysis_status": analysis_status, "plan_id": plan_id,
            "proposal_id": proposal_id, "candidate_id": candidate_id,
            "design_id": design_id, "blueprint_id": blueprint_id, "reason": status}


def _chain_mismatch(request, analysis, spec, plan, proposal, candidate, readiness, design,
                    vresult, blueprint):
    """Explicit field-by-field comparison of every shared field of the chain."""
    r_id, r_name, r_op = request["request_id"], request["capability_name"], request["operation"]
    status, existing = analysis["status"], analysis["existing"]
    goal = request["goal"]
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
        (candidate["proposal_id"], proposal["proposal_id"]), (candidate["purpose"], goal),
        (readiness["request_id"], r_id), (readiness["capability_name"], r_name),
        (readiness["operation"], r_op), (readiness["analysis_status"], status),
        (readiness["plan_id"], plan["plan_id"]),
        (readiness["proposal_id"], proposal["proposal_id"]),
        (design["request_id"], r_id), (design["capability_name"], r_name),
        (design["operation"], r_op), (design["analysis_status"], status),
        (design["existing_capability"], existing), (design["plan_id"], plan["plan_id"]),
        (design["proposal_id"], proposal["proposal_id"]),
        (design["candidate_id"], candidate["candidate_id"]), (design["purpose"], goal),
        (vresult["request_id"], r_id), (vresult["capability_name"], r_name),
        (vresult["operation"], r_op), (vresult["analysis_status"], status),
        (vresult["plan_id"], plan["plan_id"]), (vresult["proposal_id"], proposal["proposal_id"]),
        (vresult["candidate_id"], candidate["candidate_id"]),
        (vresult["design_id"], design["design_id"]),
        (blueprint["request_id"], r_id), (blueprint["capability_name"], r_name),
        (blueprint["operation"], r_op), (blueprint["analysis_status"], status),
        (blueprint["existing_capability"], existing), (blueprint["plan_id"], plan["plan_id"]),
        (blueprint["proposal_id"], proposal["proposal_id"]),
        (blueprint["candidate_id"], candidate["candidate_id"]),
        (blueprint["design_id"], design["design_id"]), (blueprint["purpose"], goal),
        (blueprint["purpose"], design["purpose"]),
    ]
    for key in ("goal", "inputs", "outputs", "constraints"):
        for doc in (spec, plan, proposal):
            pairs.append((doc[key], request[key]))
    for key in ("inputs", "outputs", "constraints"):
        pairs.append((candidate[key], request[key]))
        pairs.append((design[key], request[key]))
        pairs.append((blueprint[key], request[key]))
    return any(not _same(a, b) for a, b in pairs)


# --------------------------------------------------------------- validation

def validate_capability_implementation_blueprint_context(
        evolution_request=None, analysis_result=None, specification=None, plan=None,
        proposal=None, candidate=None, readiness_result=None, design=None,
        validation_result=None, blueprint=None):
    """Validation result for the complete request..blueprint chain (read-only)."""
    try:
        request, analysis, spec = evolution_request, analysis_result, specification
        readiness, vresult = readiness_result, validation_result
        if not validate_capability_evolution_request(request)["valid"]:
            return _result(STATUS_INVALID_REQUEST)
        if not validate_capability_evolution_analysis(analysis)["valid"]:
            return _result(STATUS_INVALID_ANALYSIS, request)
        status = analysis["status"]
        if not validate_capability_evolution_specification(spec)["valid"]:
            return _result(STATUS_INVALID_SPECIFICATION, request, status)
        context = validate_capability_evolution(request, analysis, spec)
        if not validate_capability_evolution_result(context)["valid"]:
            return _result(STATUS_INVALID_VALIDATION, request, status)
        if not validate_capability_evolution_plan(plan)["valid"]:
            return _result(STATUS_INVALID_PLAN, request, status)
        if not validate_capability_evolution_proposal(proposal)["valid"]:
            return _result(STATUS_INVALID_PROPOSAL, request, status)
        if not validate_capability_definition_candidate(candidate)["valid"]:
            return _result(STATUS_INVALID_CANDIDATE, request, status)
        if not validate_capability_definition_readiness(readiness)["valid"]:
            return _result(STATUS_INVALID_READINESS, request, status)
        if (readiness["status"] != "ready" or readiness["ready"] is not True
                or readiness["execution_allowed"] is not False):
            return _result(STATUS_INVALID_READINESS, request, status)
        if not validate_capability_implementation_design(design)["valid"]:
            return _result(STATUS_INVALID_DESIGN, request, status)
        if not validate_capability_implementation_design_validation_result(vresult)["valid"]:
            return _result(STATUS_INVALID_DESIGN_VALIDATION, request, status)
        if vresult["status"] != "valid" or vresult["valid"] is not True:
            return _result(STATUS_INVALID_DESIGN_VALIDATION, request, status)
        if not validate_capability_implementation_blueprint(blueprint)["valid"]:
            return _result(STATUS_INVALID_BLUEPRINT, request, status)

        # the Prompt 885 boundary re-validates the whole request..design chain
        derived = validate_capability_implementation_design_context(
            request, analysis, spec, plan, proposal, candidate, readiness, design)
        if derived["status"] == "unsupported_status":
            return _result(STATUS_UNSUPPORTED, request, status)
        if derived["status"] != "valid":
            return _result(STATUS_CONTEXT, request, status)
        if _chain_mismatch(request, analysis, spec, plan, proposal, candidate, readiness,
                           design, vresult, blueprint):
            return _result(STATUS_CONTEXT, request, status)
        if not _same(vresult, derived):
            return _result(STATUS_CONTEXT, request, status)
        built = build_capability_implementation_blueprint(
            request, analysis, spec, plan, proposal, candidate, readiness, design, vresult,
            blueprint["blueprint_id"])
        if built["status"] == "unsupported_status":
            return _result(STATUS_UNSUPPORTED, request, status)
        if built["status"] != "ready" or not _same(built["blueprint"], blueprint):
            return _result(STATUS_CONTEXT, request, status)

        combo = (request["operation"], status, proposal["proposal_type"], design["design_type"])
        if combo not in SUPPORTED or context["ready"] is not True:
            return _result(STATUS_UNSUPPORTED, request, status)
        return _result(STATUS_VALID, request, status, plan["plan_id"], proposal["proposal_id"],
                       candidate["candidate_id"], design["design_id"],
                       blueprint["blueprint_id"])
    except Exception:
        return _result(STATUS_ERROR)


# ------------------------------------------------------- result validation

def _id_ok(value):
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
        for key in _IDS + ("analysis_status",) + _LATER_IDS:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors
    # request identity: reuse the Prompt 876 request validator for the text rules
    view = {"version": "1", "request_id": result["request_id"],
            "operation": result["operation"], "capability_name": result["capability_name"],
            "goal": "g", "inputs": [], "outputs": ["o"], "constraints": [],
            "requested_by": "r", "execution_allowed": False}
    for error in validate_capability_evolution_request(view)["errors"]:
        if error["where"] in _IDS:
            add(ERR_INVALID_IDENTITY, error["where"])
    if status in _REQUEST_ONLY:
        for key in ("analysis_status",) + _LATER_IDS:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors
    if type(result["analysis_status"]) is not str or \
            result["analysis_status"] not in _ANALYSIS_STATUSES:
        add(ERR_INVALID_IDENTITY, "analysis_status")
    if status == STATUS_VALID:
        for key in _LATER_IDS:
            if not _id_ok(result[key]):
                add(ERR_INVALID_IDENTITY, key)
        if (result["operation"], result["analysis_status"]) not in tuple(
                (op, st) for op, st, _, _ in SUPPORTED):
            add(ERR_INCONSISTENT, "status")
    else:
        for key in _LATER_IDS:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
    return errors


def validate_capability_implementation_blueprint_validation_result(result=None):
    """Validation result for a normalized blueprint validation result."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
