"""
Capability Evolution Proposal (Prompt 881, Section 16 - Capability Creation & Improvement)
==========================================================================================
A deterministic, read-only PROPOSAL CONTRACT: a structured description of the
intended capability evolution (create a new capability definition, or improve the
existing one), built from a Prompt 876 request, Prompt 877 analysis, Prompt 878
specification and Prompt 880 plan that are individually valid and mutually
consistent. It is data only: no source code, patch, implementation instruction,
file operation, registry mutation or executable action is produced, nothing is
executed, and no filesystem, network, API, model, Memory, AEL or research access
happens. It never performs or allows self-modification. Caller data is never
normalized, altered or repaired.

  build_capability_evolution_proposal(evolution_request, analysis_result,
                                      specification, plan, proposal_id=None)
  validate_capability_evolution_proposal(proposal)

The public validators of Prompts 876-880 are reused, not re-implemented:
request / analysis / specification validators, validate_capability_evolution
(+ _result) for the combined context, and validate_capability_evolution_plan.

Build checks run in this fixed order; the first failure decides the status:
   1 request invalid                      invalid_request
   2 analysis invalid                     invalid_analysis
   3 specification invalid                invalid_specification
   4 Prompt 879 context (computed here) is an invalid result   invalid_validation
   5 plan invalid                         invalid_plan
 6-11 mismatches, all reported as context_mismatch:
       6 request/analysis   (operation, capability name)
       7 request/specification (request id, operation, name, goal, inputs,
         outputs, constraints)
       8 request/plan       (the same seven fields)
       9 analysis/specification (status, existing capability)
      10 analysis/plan      (status, existing capability)
      11 specification/plan (all shared fields, existing capability, status)
     Steps 6 and 9 are decided by the Prompt 879 context_mismatch result.
  12 proposal_id missing or invalid       invalid_proposal_id
  13 context not "ready", or (operation, analysis status) not
     create + create_required / improve + improve_required   unsupported_status
  14 the built proposal fails its own validator   proposal_error
Any unexpected internal failure -> validation_error.

improve_or_conflict is never supported. Because a valid plan carries only
create_required or improve_required, such an analysis is stopped earlier (the plan
is invalid, or it disagrees with the analysis -> context_mismatch); step 13 is the
final guard. proposal_id is caller-supplied (text, <= 64 chars, the request-id
rule) and is never generated or defaulted.

Normalized proposal (exactly these fourteen keys):
  {"version", "proposal_id", "request_id", "operation", "capability_name", "goal",
   "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
   "plan_id", "execution_allowed", "proposal_type"}
  version "1"; request fields and plan_id exactly as supplied (lists copied, order
  kept); create  -> analysis_status "create_required",  proposal_type
  "create_capability",  existing_capability None; improve -> analysis_status
  "improve_required", proposal_type "improve_capability", existing_capability a
  deep copy of the validated matching descriptor; execution_allowed exactly False.

Build result (exactly these keys, fresh every call):
  {"status", "proposal", "execution_allowed", "executed"}
status "ready" only together with a valid proposal (else proposal is None); both
flags are always False.

validate_capability_evolution_proposal(proposal) validates the exact 14-key shape
and every invariant above. The shared fields, existing capability and the
operation/status/existing semantics are checked by the Prompt 880 plan validator
on a plan-shaped view of the proposal. Result:
  {"valid", "errors", "execution_allowed", "executed"}
errors [{"code", "where"}], at most MAX_ERRORS; read-only, never raises.
Bounded work, deterministic.
"""

import copy

from .capability_evolution_analysis import validate_capability_evolution_analysis
from .capability_evolution_plan import (PLAN_STATUS, validate_capability_evolution_plan)
from .capability_evolution_request import (REQUEST_VERSION,
                                           validate_capability_evolution_request)
from .capability_evolution_specification import validate_capability_evolution_specification
from .capability_evolution_validation import (STATUS_CONTEXT_MISMATCH, STATUS_READY,
                                              validate_capability_evolution,
                                              validate_capability_evolution_result)
from .capability_registry import MAX_ERRORS

PROPOSAL_VERSION = REQUEST_VERSION

STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_ANALYSIS = "invalid_analysis"
STATUS_INVALID_SPECIFICATION = "invalid_specification"
STATUS_INVALID_VALIDATION = "invalid_validation"
STATUS_INVALID_PLAN = "invalid_plan"
STATUS_CONTEXT = "context_mismatch"
STATUS_INVALID_PROPOSAL_ID = "invalid_proposal_id"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_PROPOSAL_ERROR = "proposal_error"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_INVALID_VALIDATION, STATUS_INVALID_PLAN,
            STATUS_CONTEXT, STATUS_INVALID_PROPOSAL_ID, STATUS_UNSUPPORTED,
            STATUS_PROPOSAL_ERROR, STATUS_ERROR)

FIELDS = ("version", "proposal_id", "request_id", "operation", "capability_name", "goal",
          "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
          "plan_id", "execution_allowed", "proposal_type")

PROPOSAL_TYPE = {"create": "create_capability", "improve": "improve_capability"}

# fields every document derived from the request must carry unchanged
_SHARED = ("request_id", "operation", "capability_name", "goal", "inputs", "outputs",
           "constraints")

ERR_NOT_DICT = "proposal_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_PROPOSAL_ID = "invalid_proposal_id"
ERR_INVALID_PROPOSAL_TYPE = "invalid_proposal_type"
ERR_INCONSISTENT = "inconsistent_proposal"
ERR_INTERNAL = "validation_error"


# ------------------------------------------------------------------ build

def _build_result(status, proposal=None):
    return {"status": status, "proposal": proposal, "execution_allowed": False,
            "executed": False}


def _text_valid(value):
    """Reuse the Prompt 876 text rule (the value takes the `requested_by` slot)."""
    view = {"version": "1", "request_id": "r", "operation": "create", "capability_name": "c",
            "goal": "g", "inputs": [], "outputs": ["o"], "constraints": [],
            "requested_by": value, "execution_allowed": False}
    return validate_capability_evolution_request(view)["valid"]


def _differs(left, right, fields):
    return any(left[f] != right[f] for f in fields)


def build_capability_evolution_proposal(evolution_request=None, analysis_result=None,
                                        specification=None, plan=None, proposal_id=None):
    """Build a fresh normalized proposal, or report the first failing check."""
    try:
        request, analysis, spec = evolution_request, analysis_result, specification
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

        status = analysis["status"]
        mismatch = (
            context["status"] == STATUS_CONTEXT_MISMATCH                      # 6, 9
            or (context["status"] == STATUS_READY and (
                context["request_id"] != request["request_id"]
                or context["capability_name"] != request["capability_name"]
                or context["operation"] != request["operation"]
                or context["analysis_status"] != status))
            or _differs(request, spec, _SHARED)                               # 7
            or _differs(request, plan, _SHARED)                               # 8
            or plan["analysis_status"] != status                              # 10
            or plan["existing_capability"] != analysis["existing"]            # 10
            or _differs(spec, plan, _SHARED + ("existing_capability",))       # 11
            or spec["analysis_status"] != plan["analysis_status"])            # 11
        if mismatch:
            return _build_result(STATUS_CONTEXT)

        if proposal_id is None or not _text_valid(proposal_id):
            return _build_result(STATUS_INVALID_PROPOSAL_ID)
        if (context["status"] != STATUS_READY or context["ready"] is not True
                or PLAN_STATUS[request["operation"]] != status):
            return _build_result(STATUS_UNSUPPORTED)

        proposal = {
            "version": PROPOSAL_VERSION,
            "proposal_id": proposal_id,
            "request_id": request["request_id"],
            "operation": request["operation"],
            "capability_name": request["capability_name"],
            "goal": request["goal"],
            "inputs": list(request["inputs"]),
            "outputs": list(request["outputs"]),
            "constraints": list(request["constraints"]),
            "existing_capability": copy.deepcopy(analysis["existing"]),
            "analysis_status": status,
            "plan_id": plan["plan_id"],
            "execution_allowed": False,
            "proposal_type": PROPOSAL_TYPE[request["operation"]],
        }
        if _proposal_errors(proposal):
            return _build_result(STATUS_PROPOSAL_ERROR)
        return _build_result(STATUS_READY, proposal)
    except Exception:
        return _build_result(STATUS_ERROR)


# ------------------------------------------------------------- validation

def _proposal_errors(proposal):
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(proposal) is not dict:
        add(ERR_NOT_DICT, "proposal")
        return errors
    for key in FIELDS:
        if key not in proposal:
            add(ERR_MISSING_KEY, key)
    for key in proposal:
        if type(key) is not str or key not in FIELDS:
            add(ERR_UNEXPECTED_KEY,
                key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    if not _text_valid(proposal["proposal_id"]):
        add(ERR_INVALID_PROPOSAL_ID, "proposal_id")

    # Everything shared with a plan is checked by the Prompt 880 plan validator on a
    # plan-shaped view (plan_id, request fields, existing capability, status,
    # create/improve semantics, execution flag).
    view = {key: proposal[key] for key in FIELDS
            if key not in ("proposal_id", "proposal_type")}
    for error in validate_capability_evolution_plan(view)["errors"]:
        code = ERR_INCONSISTENT if error["code"] == "inconsistent_plan" else error["code"]
        add(code, error["where"])

    kind = proposal["proposal_type"]
    if type(kind) is not str or kind not in PROPOSAL_TYPE.values():
        add(ERR_INVALID_PROPOSAL_TYPE, "proposal_type")
    elif not errors and PROPOSAL_TYPE[proposal["operation"]] != kind:
        add(ERR_INCONSISTENT, "proposal_type")
    return errors


def validate_capability_evolution_proposal(proposal=None):
    """Validation result for a normalized capability evolution proposal."""
    try:
        errors = _proposal_errors(proposal)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "proposal"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
