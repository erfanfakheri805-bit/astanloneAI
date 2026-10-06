"""
Capability Implementation Contract Readiness (Prompt 889, Section 16)
======================================================================
A deterministic, read-only validation boundary that answers only: "is this fully validated
implementation contract structurally ready to enter a FUTURE implementation stage?"

    request -> analysis -> specification -> plan -> proposal -> candidate -> readiness
            -> implementation design -> design validation result (885)
            -> implementation blueprint (886) -> blueprint validation result (887)
            -> implementation contract (888) -> contract validation result (888 validator)

It does NOT implement, generate, execute, modify, persist, register, install or otherwise act
on the capability. Nothing is written, researched, networked, sent to an API or model,
loaded, replaced or self-modified, and caller data is never normalized, altered or repaired.

  evaluate_capability_implementation_contract_readiness(evolution_request, analysis_result,
        specification, plan, proposal, candidate, readiness_result, design, validation_result,
        blueprint, blueprint_validation_result, contract, contract_validation_result)
  validate_capability_implementation_contract_readiness(result)

The public validators / builders of Prompts 876-888 are reused, not re-implemented.
Checks run in this fixed order; the first failure decides the status:
   1 request invalid                       invalid_request
   2 analysis invalid                      invalid_analysis
   3 specification invalid                 invalid_specification
   4 Prompt 879 context invalid result     invalid_validation
     (analysis status improve_or_conflict  unsupported_status -- never ready, decided as soon
      as the request / analysis / specification / Prompt 879 result are trusted)
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
  13 implementation contract invalid       invalid_contract
  14 contract validation result invalid, or not valid (valid True, no errors)
                                           invalid_contract_validation
  15-20 chain disagreement                 context_mismatch
      explicit type-strict comparison of request_id, capability_name, operation, goal /
      purpose, inputs, outputs, constraints, existing_capability, analysis_status, plan_id,
      proposal_id, candidate_id, design_id, blueprint_id, contract_id and requirements across
      all objects; the Prompt 887 result must equal the result the Prompt 887 context validator
      derives, the contract must equal the contract the Prompt 888 builder derives from the
      trusted chain, and the contract validation result must equal the report the Prompt 888
      validator derives from that contract, so a forged but individually valid object (a forged
      contract, a forged "valid" validation result) never passes.
  21 readiness determination
      supported: create  + create_required  + create_capability  + create_implementation
                 improve + improve_required + improve_capability + improve_implementation
      anything else                        unsupported_status
      supported and everything consistent  ready
Any unexpected internal failure -> validation_error.

"Contract validation result" is the report of validate_capability_implementation_contract
(Prompt 888): {"valid", "errors", "execution_allowed", "executed"}. It carries no text status,
so "valid with status valid" means valid True, errors [] and both flags False.

Result (exactly these thirteen keys, fresh every call):
  {"version", "status", "ready", "request_id", "capability_name", "operation",
   "analysis_status", "plan_id", "proposal_id", "contract_id", "reason",
   "execution_allowed", "executed"}
version is the integer 1; ready is True only when status == "ready"; reason equals the status;
execution_allowed and executed are ALWAYS False. Identity fields come only from validated,
trusted objects: invalid_request and validation_error carry none; invalid_analysis carries the
request identity only (request_id, capability_name, operation); every other non-ready status
carries the request identity and the analysis_status; plan_id, proposal_id and contract_id are
populated only for "ready".
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
    validate_capability_implementation_blueprint_context,
    validate_capability_implementation_blueprint_validation_result)
from .capability_implementation_contract import (build_capability_implementation_contract,
                                                 validate_capability_implementation_contract)
from .capability_implementation_design import validate_capability_implementation_design
from .capability_implementation_design_validation import (
    validate_capability_implementation_design_validation_result)
from .capability_registry import MAX_ERRORS

READINESS_VERSION = 1

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
STATUS_CONTEXT = "context_mismatch"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_NOT_READY, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_INVALID_VALIDATION, STATUS_INVALID_PLAN,
            STATUS_INVALID_PROPOSAL, STATUS_INVALID_CANDIDATE, STATUS_INVALID_READINESS,
            STATUS_INVALID_DESIGN, STATUS_INVALID_DESIGN_VALIDATION, STATUS_INVALID_BLUEPRINT,
            STATUS_INVALID_BLUEPRINT_VALIDATION, STATUS_INVALID_CONTRACT,
            STATUS_INVALID_CONTRACT_VALIDATION, STATUS_CONTEXT, STATUS_UNSUPPORTED,
            STATUS_ERROR)

RESULT_KEYS = ("version", "status", "ready", "request_id", "capability_name", "operation",
               "analysis_status", "plan_id", "proposal_id", "contract_id", "reason",
               "execution_allowed", "executed")

# (operation, analysis status, proposal type, design type)
SUPPORTED = (("create", "create_required", "create_capability", "create_implementation"),
             ("improve", "improve_required", "improve_capability", "improve_implementation"))
_ANALYSIS_STATUSES = ("create_required", "improve_required", "improve_or_conflict")

_NO_IDS = frozenset((STATUS_INVALID_REQUEST, STATUS_ERROR))
_REQUEST_ONLY = frozenset((STATUS_INVALID_ANALYSIS,))
_IDS = ("request_id", "capability_name", "operation")
_LATER_IDS = ("plan_id", "proposal_id", "contract_id")

ERR_NOT_DICT = "result_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_READY = "invalid_ready"
ERR_INVALID_IDENTITY = "invalid_identity"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_FLAG = "invalid_execution_flag"
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
            contract_id=None):
    ids = (None, None, None)
    if request is not None:
        ids = (request["request_id"], request["capability_name"], request["operation"])
    return {"version": READINESS_VERSION, "status": status, "ready": status == STATUS_READY,
            "request_id": ids[0], "capability_name": ids[1], "operation": ids[2],
            "analysis_status": analysis_status, "plan_id": plan_id,
            "proposal_id": proposal_id, "contract_id": contract_id, "reason": status,
            "execution_allowed": False, "executed": False}


def _id_ok(value):
    """Reuse the Prompt 881 proposal validator for the text rule of an id."""
    view = {"version": "1", "proposal_id": value, "request_id": "r", "operation": "create",
            "capability_name": "c", "goal": "g", "inputs": [], "outputs": ["o"],
            "constraints": [], "existing_capability": None,
            "analysis_status": "create_required", "plan_id": "p", "execution_allowed": False,
            "proposal_type": "create_capability"}
    return validate_capability_evolution_proposal(view)["valid"]


def _validation_report_ok(report):
    """The supplied contract validation result: the exact Prompt 888 report shape, valid."""
    if type(report) is not dict or sorted(report, key=repr) != [
            "errors", "executed", "execution_allowed", "valid"]:
        return False
    return (report["valid"] is True and type(report["errors"]) is list
            and report["errors"] == [] and report["execution_allowed"] is False
            and report["executed"] is False)


def _chain_mismatch(request, analysis, spec, plan, proposal, candidate, design, blueprint,
                    contract):
    """Explicit field-by-field comparison of every shared field of the chain and contract."""
    r_id, r_name, r_op = request["request_id"], request["capability_name"], request["operation"]
    status, existing, goal = analysis["status"], analysis["existing"], request["goal"]
    pairs = [
        (contract["request_id"], r_id), (contract["capability_name"], r_name),
        (contract["operation"], r_op), (contract["analysis_status"], status),
        (contract["existing_capability"], existing), (contract["purpose"], goal),
        (contract["purpose"], blueprint["purpose"]), (contract["purpose"], design["purpose"]),
        (contract["purpose"], candidate["purpose"]), (contract["purpose"], spec["goal"]),
        (contract["plan_id"], plan["plan_id"]), (contract["proposal_id"], proposal["proposal_id"]),
        (contract["candidate_id"], candidate["candidate_id"]),
        (contract["design_id"], design["design_id"]),
        (contract["blueprint_id"], blueprint["blueprint_id"]),
    ]
    for key in ("inputs", "outputs", "constraints"):
        for doc in (spec, plan, proposal, candidate, design, blueprint, contract):
            pairs.append((doc[key], request[key]))
    return any(not _same(a, b) for a, b in pairs)


# --------------------------------------------------------------- evaluation

def evaluate_capability_implementation_contract_readiness(
        evolution_request=None, analysis_result=None, specification=None, plan=None,
        proposal=None, candidate=None, readiness_result=None, design=None,
        validation_result=None, blueprint=None, blueprint_validation_result=None,
        contract=None, contract_validation_result=None):
    """Readiness result for a validated implementation contract (read-only)."""
    try:
        request, analysis, spec = evolution_request, analysis_result, specification
        readiness, vresult, bresult = readiness_result, validation_result, \
            blueprint_validation_result
        creport = contract_validation_result
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

        # the Prompt 887 boundary re-validates the whole request..blueprint chain
        derived = validate_capability_implementation_blueprint_context(
            request, analysis, spec, plan, proposal, candidate, readiness, design, vresult,
            blueprint)
        if derived["status"] == "unsupported_status":
            return _result(STATUS_UNSUPPORTED, request, status)
        if derived["status"] != "valid" or not _same(bresult, derived):
            return _result(STATUS_CONTEXT, request, status)
        if _chain_mismatch(request, analysis, spec, plan, proposal, candidate, design,
                           blueprint, contract):
            return _result(STATUS_CONTEXT, request, status)
        # the contract must be exactly the one the Prompt 888 builder derives from the chain
        built = build_capability_implementation_contract(
            request, analysis, spec, plan, proposal, candidate, readiness, design, vresult,
            blueprint, bresult, contract["contract_id"])
        if built["status"] == "unsupported_status":
            return _result(STATUS_UNSUPPORTED, request, status)
        if built["status"] != "ready" or not _same(built["contract"], contract):
            return _result(STATUS_CONTEXT, request, status)
        if not _same(creport, validate_capability_implementation_contract(contract)):
            return _result(STATUS_CONTEXT, request, status)

        combo = (request["operation"], status, proposal["proposal_type"],
                 design["design_type"])
        if combo not in SUPPORTED or context["ready"] is not True:
            return _result(STATUS_UNSUPPORTED, request, status)
        return _result(STATUS_READY, request, status, plan["plan_id"],
                       proposal["proposal_id"], contract["contract_id"])
    except Exception:
        return _result(STATUS_ERROR)


# ------------------------------------------------------- result validation

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

    if type(result["version"]) is not int or result["version"] != READINESS_VERSION:
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
    for key in ("execution_allowed", "executed"):
        if result[key] is not False:
            add(ERR_INVALID_FLAG, key)
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


def validate_capability_implementation_contract_readiness(result=None):
    """Validation result for a normalized contract readiness result."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
