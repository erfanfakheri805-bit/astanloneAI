"""
Capability Implementation Boundary Gate (Prompt 890, Section 16)
=================================================================
A deterministic, read-only BOUNDARY DECISION between the validated Section 16 planning /
contract chain and any FUTURE implementation stage:

    request -> analysis -> specification -> plan -> proposal -> candidate -> readiness
            -> design -> design validation result (885) -> blueprint (886)
            -> blueprint validation result (887) -> contract (888)
            -> contract validation result (888 validator) -> contract readiness result (889)

"ready" means ONLY: the validated chain has crossed the structural boundary and may be
considered for a future implementation stage. It never means implementation has started or is
permitted: implementation_allowed, implementation_started, execution_allowed and executed are
ALWAYS False. Nothing is generated, patched, written, registered, installed, persisted,
executed, researched, networked, sent to an API / model, loaded, replaced or self-modified,
and caller data is never normalized, altered or repaired.

  evaluate_capability_implementation_boundary(evolution_request, analysis_result,
        specification, plan, proposal, candidate, readiness_result, design, validation_result,
        blueprint, blueprint_validation_result, contract, contract_validation_result,
        contract_readiness_result)
  validate_capability_implementation_boundary_result(result)

The public validators / builders of Prompts 876-889 are reused, not re-implemented.
Checks run in this fixed order; the first failure decides the status:
   1 request invalid                      invalid_request
   2 analysis invalid                     invalid_analysis
   3 specification invalid                invalid_specification
   4 Prompt 879 context invalid result    invalid_validation
     (analysis status improve_or_conflict unsupported_status -- never ready, decided once the
      request / analysis / specification / Prompt 879 result are trusted)
   5 plan invalid                         invalid_plan
   6 proposal invalid                     invalid_proposal
   7 definition candidate invalid         invalid_candidate
   8 readiness result invalid, or valid but not "ready" / ready True / execution_allowed False
                                          invalid_readiness
   9 implementation design invalid        invalid_design
  10 Prompt 885 result invalid / not "valid"
                                          invalid_design_validation
  11 blueprint invalid                    invalid_blueprint
  12 Prompt 887 result invalid / status not "valid"
                                          invalid_blueprint_validation
  13 contract invalid                     invalid_contract
  14 contract validation result: not the valid 4-key Prompt 888 shape (valid True, errors [],
     execution_allowed False, executed False)
                                          invalid_contract_validation
  15 Prompt 889 readiness result invalid, or valid but not status "ready" / ready True /
     execution_allowed False / executed False
                                          invalid_contract_readiness
  16-22 chain disagreement                context_mismatch
      type-strict comparison of request_id, capability_name, operation, goal / purpose, inputs,
      outputs, constraints, existing_capability, analysis_status, plan_id, proposal_id,
      candidate_id, design_id, blueprint_id, contract_id and requirements across all objects.
      The Prompt 887 result, the contract (Prompt 888 builder), the contract validation result
      (Prompt 888 validator) and the Prompt 889 readiness result must each equal what the
      trusted chain derives, so a forged but individually valid object never passes.
  23 boundary determination
      supported: create  + create_required  + create_capability  + create_implementation
                 improve + improve_required + improve_capability + improve_implementation
      anything else                       unsupported_status
      supported and consistent            ready
Any unexpected internal failure -> validation_error.

Result (exactly these fourteen keys, fresh every call):
  {"version", "status", "ready", "request_id", "capability_name", "operation",
   "analysis_status", "plan_id", "contract_id", "reason", "execution_allowed", "executed",
   "implementation_started", "implementation_allowed"}
version is the integer 1; ready is True only when status == "ready"; reason equals the status.
Identity comes only from trusted objects: invalid_request and validation_error carry none;
invalid_analysis carries the request identity only; every other non-ready status carries the
request identity and analysis_status; plan_id and contract_id only for "ready".
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
from .capability_implementation_blueprint import validate_capability_implementation_blueprint
from .capability_implementation_blueprint_validation import (
    validate_capability_implementation_blueprint_validation_result)
from .capability_implementation_contract import validate_capability_implementation_contract
from .capability_implementation_contract_readiness import (
    evaluate_capability_implementation_contract_readiness,
    validate_capability_implementation_contract_readiness)
from .capability_implementation_design import validate_capability_implementation_design
from .capability_implementation_design_validation import (
    validate_capability_implementation_design_validation_result)
from .capability_registry import MAX_ERRORS

BOUNDARY_VERSION = 1

STATUS_READY = "ready"
STATUS_NOT_READY = "not_ready"
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
STATUS_CONTEXT = "context_mismatch"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_NOT_READY, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_INVALID_VALIDATION, STATUS_INVALID_PLAN,
            STATUS_INVALID_PROPOSAL, STATUS_INVALID_CANDIDATE, STATUS_INVALID_READINESS,
            STATUS_INVALID_DESIGN, STATUS_INVALID_DESIGN_VALIDATION, STATUS_INVALID_BLUEPRINT,
            STATUS_INVALID_BLUEPRINT_VALIDATION, STATUS_INVALID_CONTRACT,
            STATUS_INVALID_CONTRACT_VALIDATION, STATUS_INVALID_CONTRACT_READINESS,
            STATUS_CONTEXT, STATUS_UNSUPPORTED, STATUS_ERROR)

RESULT_KEYS = ("version", "status", "ready", "request_id", "capability_name", "operation",
               "analysis_status", "plan_id", "contract_id", "reason", "execution_allowed",
               "executed", "implementation_started", "implementation_allowed")
_FLAGS = ("execution_allowed", "executed", "implementation_started", "implementation_allowed")

# (operation, analysis status, proposal type, design type)
SUPPORTED = (("create", "create_required", "create_capability", "create_implementation"),
             ("improve", "improve_required", "improve_capability", "improve_implementation"))
_ANALYSIS_STATUSES = ("create_required", "improve_required", "improve_or_conflict")

_NO_IDS = frozenset((STATUS_INVALID_REQUEST, STATUS_ERROR))
_REQUEST_ONLY = frozenset((STATUS_INVALID_ANALYSIS,))
_IDS = ("request_id", "capability_name", "operation")
_LATER_IDS = ("plan_id", "contract_id")

ERR_NOT_DICT = "result_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_READY = "invalid_ready"
ERR_INVALID_IDENTITY = "invalid_identity"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_FLAG = "invalid_flag"
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


def _result(status, request=None, analysis_status=None, plan_id=None, contract_id=None):
    ids = (None, None, None)
    if request is not None:
        ids = (request["request_id"], request["capability_name"], request["operation"])
    return {"version": BOUNDARY_VERSION, "status": status, "ready": status == STATUS_READY,
            "request_id": ids[0], "capability_name": ids[1], "operation": ids[2],
            "analysis_status": analysis_status, "plan_id": plan_id,
            "contract_id": contract_id, "reason": status, "execution_allowed": False,
            "executed": False, "implementation_started": False,
            "implementation_allowed": False}


def _id_ok(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


def _validation_report_ok(report):
    """The valid 4-key Prompt 888 contract validation shape."""
    if type(report) is not dict or sorted(report, key=repr) != [
            "errors", "executed", "execution_allowed", "valid"]:
        return False
    return (report["valid"] is True and type(report["errors"]) is list
            and report["errors"] == [] and report["execution_allowed"] is False
            and report["executed"] is False)


def _readiness_ok(result):
    return (validate_capability_implementation_contract_readiness(result)["valid"]
            and result["status"] == "ready" and result["ready"] is True
            and result["execution_allowed"] is False and result["executed"] is False)


def _readiness_mismatch(result, request, analysis, plan, proposal, contract):
    pairs = [(result["request_id"], request["request_id"]),
             (result["capability_name"], request["capability_name"]),
             (result["operation"], request["operation"]),
             (result["analysis_status"], analysis["status"]),
             (result["plan_id"], plan["plan_id"]),
             (result["proposal_id"], proposal["proposal_id"]),
             (result["contract_id"], contract["contract_id"])]
    return any(not _same(a, b) for a, b in pairs)


def evaluate_capability_implementation_boundary(
        evolution_request=None, analysis_result=None, specification=None, plan=None,
        proposal=None, candidate=None, readiness_result=None, design=None,
        validation_result=None, blueprint=None, blueprint_validation_result=None,
        contract=None, contract_validation_result=None, contract_readiness_result=None):
    """Boundary decision for a validated capability implementation chain (read-only)."""
    try:
        request, analysis, spec = evolution_request, analysis_result, specification
        readiness, vresult, bresult = readiness_result, validation_result, \
            blueprint_validation_result
        creport, rresult = contract_validation_result, contract_readiness_result
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
        if status == "improve_or_conflict":
            return _result(STATUS_UNSUPPORTED, request, status)
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
        if not validate_capability_implementation_blueprint_validation_result(
                bresult)["valid"]:
            return _result(STATUS_INVALID_BLUEPRINT_VALIDATION, request, status)
        if bresult["status"] != "valid" or bresult["valid"] is not True:
            return _result(STATUS_INVALID_BLUEPRINT_VALIDATION, request, status)
        if not validate_capability_implementation_contract(contract)["valid"]:
            return _result(STATUS_INVALID_CONTRACT, request, status)
        if not _validation_report_ok(creport):
            return _result(STATUS_INVALID_CONTRACT_VALIDATION, request, status)
        if not _readiness_ok(rresult):
            return _result(STATUS_INVALID_CONTRACT_READINESS, request, status)

        # the Prompt 889 boundary re-derives the whole chain (887 result, contract, 888
        # validation result); the supplied readiness result must equal what it derives
        derived = evaluate_capability_implementation_contract_readiness(
            request, analysis, spec, plan, proposal, candidate, readiness, design, vresult,
            blueprint, bresult, contract, creport)
        if derived["status"] == "unsupported_status":
            return _result(STATUS_UNSUPPORTED, request, status)
        if derived["status"] != "ready":
            return _result(STATUS_CONTEXT, request, status)
        if _readiness_mismatch(rresult, request, analysis, plan, proposal, contract):
            return _result(STATUS_CONTEXT, request, status)
        if not _same(rresult, derived):
            return _result(STATUS_CONTEXT, request, status)

        combo = (request["operation"], status, proposal["proposal_type"],
                 design["design_type"])
        if combo not in SUPPORTED or context["ready"] is not True:
            return _result(STATUS_UNSUPPORTED, request, status)
        return _result(STATUS_READY, request, status, plan["plan_id"], contract["contract_id"])
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

    if type(result["version"]) is not int or result["version"] != BOUNDARY_VERSION:
        add(ERR_INVALID_VERSION, "version")
    status = result["status"]
    status_ok = type(status) is str and status in STATUSES
    if not status_ok:
        add(ERR_INVALID_STATUS, "status")
    if type(result["ready"]) is not bool:
        add(ERR_INVALID_READY, "ready")
    elif status_ok and result["ready"] != (status == STATUS_READY):
        add(ERR_INVALID_READY, "ready")
    if type(result["reason"]) is not str or (status_ok and result["reason"] != status):
        add(ERR_INVALID_REASON, "reason")
    for key in _FLAGS:
        if result[key] is not False:
            add(ERR_INVALID_FLAG, key)
    if not status_ok:
        return errors

    if status in _NO_IDS:
        for key in _IDS + ("analysis_status",) + _LATER_IDS:
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
        for key in ("analysis_status",) + _LATER_IDS:
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors
    if type(result["analysis_status"]) is not str or \
            result["analysis_status"] not in _ANALYSIS_STATUSES:
        add(ERR_INVALID_IDENTITY, "analysis_status")
    if status == STATUS_READY:
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


def validate_capability_implementation_boundary_result(result=None):
    """Validation result for a normalized boundary result."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
