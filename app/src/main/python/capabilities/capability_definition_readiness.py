"""
Capability Definition Readiness (Prompt 883, Section 16 - Capability Creation & Improvement)
==============================================================================================
A deterministic, read-only readiness boundary for the Capability Definition Candidate of
Prompt 882. It answers only:

    "Is this validated capability definition candidate structurally ready to enter a
     later implementation-design stage?"

"ready" means exactly that. It does NOT mean implementation ready, execution ready,
registry ready, installation ready, deployment ready or self-modification authorized.
No source code or patch is generated; no capability is created, modified, installed,
loaded or replaced; the registry is untouched; nothing is written, executed, persisted
(Memory), run (AEL / research) or sent over a network / API / model. Caller data is
never normalized, altered or repaired.

  evaluate_capability_definition_readiness(evolution_request, analysis_result,
                                           specification, plan, proposal, candidate)
  validate_capability_definition_readiness(result)

The public validators of Prompts 876-882 are reused (request, analysis, specification,
validate_capability_evolution + _result, plan, proposal, definition candidate); their rules
are not duplicated. On top of them this boundary performs explicit, type-strict identity /
context comparisons across the whole chain, so forged objects that are each individually
valid still cannot pass.

Checks run in this fixed order; the first failure decides the status:
   1 request invalid                        invalid_request
   2 analysis invalid                       invalid_analysis
   3 specification invalid                  invalid_specification
   4 Prompt 879 context is an invalid result invalid_validation
   5 plan invalid                           invalid_plan
   6 proposal invalid                       invalid_proposal
   7 candidate invalid (incl. implementation_ready / execution_allowed True)
                                            invalid_candidate
   8 request / analysis / specification / plan / proposal disagree
                                            context_mismatch
   9 candidate disagrees with the chain     context_mismatch
  10 unsupported operation / status         unsupported_status
      supported: create  + create_required  + create_capability
                 improve + improve_required + improve_capability
      (improve_or_conflict is never ready)
  11 readiness determination                ready  (not_ready if the Prompt 879
                                            context is supported but not ready)
Any unexpected internal failure -> validation_error.

Result (exactly these eleven keys, fresh every call):
  {"version", "status", "ready", "request_id", "capability_name", "operation",
   "analysis_status", "plan_id", "proposal_id", "reason", "execution_allowed"}
version "1"; ready is True only when status == "ready"; execution_allowed is always
False; there is no "executed" field; reason is the fixed text equal to the status.

Identity fields (never copied from an object that failed validation or a comparison):
  invalid_request                      all six None
  invalid_analysis                     request identity only
  every other non-ready status         request identity + analysis_status (both already
                                       validated); plan_id / proposal_id None
                                       (validation_error: all six None)
  ready                                all six populated from the validated chain
"""

from .capability_definition_candidate import validate_capability_definition_candidate
from .capability_evolution_analysis import validate_capability_evolution_analysis
from .capability_evolution_plan import validate_capability_evolution_plan
from .capability_evolution_proposal import (validate_capability_evolution_proposal)
from .capability_evolution_request import (REQUEST_VERSION,
                                           validate_capability_evolution_request)
from .capability_evolution_specification import validate_capability_evolution_specification
from .capability_evolution_validation import (STATUS_READY as CONTEXT_READY,
                                              validate_capability_evolution,
                                              validate_capability_evolution_result)

READINESS_VERSION = REQUEST_VERSION

STATUS_READY = "ready"
STATUS_NOT_READY = "not_ready"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_ANALYSIS = "invalid_analysis"
STATUS_INVALID_SPECIFICATION = "invalid_specification"
STATUS_INVALID_VALIDATION = "invalid_validation"
STATUS_INVALID_PLAN = "invalid_plan"
STATUS_INVALID_PROPOSAL = "invalid_proposal"
STATUS_INVALID_CANDIDATE = "invalid_candidate"
STATUS_CONTEXT = "context_mismatch"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_NOT_READY, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_INVALID_VALIDATION, STATUS_INVALID_PLAN,
            STATUS_INVALID_PROPOSAL, STATUS_INVALID_CANDIDATE, STATUS_CONTEXT,
            STATUS_UNSUPPORTED, STATUS_ERROR)

RESULT_KEYS = ("version", "status", "ready", "request_id", "capability_name", "operation",
               "analysis_status", "plan_id", "proposal_id", "reason", "execution_allowed")

# (operation, analysis status, proposal type) combinations that can be ready
SUPPORTED = (("create", "create_required", "create_capability"),
             ("improve", "improve_required", "improve_capability"))
_ANALYSIS_STATUSES = ("create_required", "improve_required", "improve_or_conflict")

# which identity fields each status carries
_NO_IDS = frozenset((STATUS_INVALID_REQUEST, STATUS_ERROR))
_REQUEST_IDS = frozenset((STATUS_INVALID_ANALYSIS,))

ERR_NOT_DICT = "result_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_STATUS = "invalid_status"
ERR_INVALID_READY = "invalid_ready"
ERR_INVALID_IDENTITY = "invalid_identity"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_EXECUTION_ALLOWED = "invalid_execution_allowed"
ERR_INCONSISTENT = "inconsistent_result"
ERR_INTERNAL = "validation_error"

MAX_ERRORS = 20


# --------------------------------------------------------------- helpers

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


def _result(status, request=None, analysis_status=None, plan_id=None, proposal_id=None):
    ids = (None, None, None)
    if request is not None:
        ids = (request["request_id"], request["capability_name"], request["operation"])
    return {"version": READINESS_VERSION, "status": status, "ready": status == STATUS_READY,
            "request_id": ids[0], "capability_name": ids[1], "operation": ids[2],
            "analysis_status": analysis_status, "plan_id": plan_id,
            "proposal_id": proposal_id, "reason": status, "execution_allowed": False}


# ------------------------------------------------------------- evaluation

def _chain_mismatch(request, analysis, spec, plan, proposal, candidate):
    """True if the validated chain disagrees anywhere (explicit, type-strict)."""
    r_id, r_name, r_op = request["request_id"], request["capability_name"], request["operation"]
    status, existing = analysis["status"], analysis["existing"]
    content = ("goal", "inputs", "outputs", "constraints")
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
        (proposal["existing_capability"], existing),
        (proposal["plan_id"], plan["plan_id"]),
        (candidate["request_id"], r_id), (candidate["operation"], r_op),
        (candidate["capability_name"], r_name), (candidate["analysis_status"], status),
        (candidate["existing_capability"], existing),
        (candidate["plan_id"], plan["plan_id"]),
        (candidate["proposal_id"], proposal["proposal_id"]),
        (candidate["purpose"], request["goal"]),
    ]
    for key in content:
        for doc in (spec, plan, proposal):
            pairs.append((doc[key], request[key]))
    for key in ("inputs", "outputs", "constraints"):
        pairs.append((candidate[key], request[key]))
    return any(not _same(a, b) for a, b in pairs)


def evaluate_capability_definition_readiness(evolution_request=None, analysis_result=None,
                                             specification=None, plan=None, proposal=None,
                                             candidate=None):
    """Readiness result for the complete request..candidate chain (read-only)."""
    try:
        request, analysis, spec = evolution_request, analysis_result, specification
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

        if context["status"] == "context_mismatch" or _chain_mismatch(
                request, analysis, spec, plan, proposal, candidate):
            return _result(STATUS_CONTEXT, request, status)
        if context["status"] == CONTEXT_READY and not (
                context["ready"] is True
                and _same(context["request_id"], request["request_id"])
                and _same(context["capability_name"], request["capability_name"])
                and _same(context["operation"], request["operation"])
                and _same(context["analysis_status"], status)):
            return _result(STATUS_CONTEXT, request, status)

        if (request["operation"], status, proposal["proposal_type"]) not in SUPPORTED:
            return _result(STATUS_UNSUPPORTED, request, status)
        if context["status"] != CONTEXT_READY:
            return _result(STATUS_NOT_READY, request, status)
        return _result(STATUS_READY, request, status, plan["plan_id"], proposal["proposal_id"])
    except Exception:
        return _result(STATUS_ERROR)


# ------------------------------------------------------------- validation

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

    if type(result["version"]) is not str or result["version"] != READINESS_VERSION:
        add(ERR_INVALID_VERSION, "version")
    status = result["status"]
    status_ok = type(status) is str and status in STATUSES
    if not status_ok:
        add(ERR_INVALID_STATUS, "status")
    if type(result["ready"]) is not bool:
        add(ERR_INVALID_READY, "ready")
    elif status_ok and result["ready"] != (status == STATUS_READY):
        add(ERR_INVALID_READY, "ready")
    if result["execution_allowed"] is not False:
        add(ERR_INVALID_EXECUTION_ALLOWED, "execution_allowed")
    if status_ok and (type(result["reason"]) is not str or result["reason"] != status):
        add(ERR_INVALID_REASON, "reason")
    elif not status_ok and type(result["reason"]) is not str:
        add(ERR_INVALID_REASON, "reason")

    if not status_ok:
        return errors
    ids = ("request_id", "capability_name", "operation")
    if status in _NO_IDS:
        for key in ids + ("analysis_status", "plan_id", "proposal_id"):
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors
    # request identity: reuse the Prompt 876 request validator for the text rules
    view = {"version": "1", "request_id": result["request_id"],
            "operation": result["operation"], "capability_name": result["capability_name"],
            "goal": "g", "inputs": [], "outputs": ["o"], "constraints": [],
            "requested_by": "r", "execution_allowed": False}
    for error in validate_capability_evolution_request(view)["errors"]:
        if error["where"] in ids:
            add(ERR_INVALID_IDENTITY, error["where"])
    if status in _REQUEST_IDS:
        for key in ("analysis_status", "plan_id", "proposal_id"):
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
        return errors
    if result["analysis_status"] not in _ANALYSIS_STATUSES or \
            type(result["analysis_status"]) is not str:
        add(ERR_INVALID_IDENTITY, "analysis_status")
    if status == STATUS_READY:
        for key in ("plan_id", "proposal_id"):
            if not _text_ok(result[key]):
                add(ERR_INVALID_IDENTITY, key)
        if (result["operation"], result["analysis_status"]) not in \
                tuple((op, st) for op, st, _ in SUPPORTED):
            add(ERR_INCONSISTENT, "status")
    else:
        for key in ("plan_id", "proposal_id"):
            if result[key] is not None:
                add(ERR_INVALID_IDENTITY, key)
    return errors


def validate_capability_definition_readiness(result=None):
    """Validation result for a normalized readiness result."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "result"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
