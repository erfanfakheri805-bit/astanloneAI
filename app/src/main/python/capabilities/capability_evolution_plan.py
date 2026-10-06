"""
Capability Evolution Plan (Prompt 880, Section 16 - Capability Creation & Improvement)
=======================================================================================
A deterministic, read-only PLAN CONTRACT: once the Prompt 876 request, Prompt 877
analysis and Prompt 878 specification form a valid evolution context (Prompt 879
status "ready"), the plan records WHAT evolution is needed - a new capability
definition (create) or the existing capability definition as the target
(improve). It is data only: it generates no code, patch, file path or
executable action, modifies no capability, descriptor or registry, writes no
file, persists nothing, and touches no Memory, AEL, research, network, API or
model. It never executes anything and never performs or allows self-modification.

  build_capability_evolution_plan(evolution_request, analysis_result, specification,
                                  plan_id=None)   -> build result
  validate_capability_evolution_plan(plan)        -> validation result

The public validators of Prompts 876-879 are reused, not re-implemented:
validate_capability_evolution_request / _analysis / _specification, and
validate_capability_evolution (+ _result) for the combined context.

Build checks run in this fixed order; the first failure decides the status:
   1 request invalid                         invalid_request
   2 analysis invalid                        invalid_analysis
   3 specification invalid                   invalid_specification
   4 Prompt 879 result (computed here from the three inputs) is itself an
     invalid result                          invalid_validation
   5-7 request/analysis, request/specification and analysis/specification
     mismatches (the Prompt 879 context_mismatch)   context_mismatch
   8 the Prompt 879 result's identity fields disagree with the inputs
                                             context_mismatch
   9 plan_id missing or invalid              invalid_plan_id
  10 context not "ready", or analysis status not create_required /
     improve_required (improve_or_conflict has no plan)   unsupported_status
  11 the built plan fails its own validator  plan_error
Any unexpected internal failure -> validation_error.

plan_id is caller-supplied (text, <= 64 chars, same rule as a request id); it is
never generated or defaulted.

Normalized plan (exactly these twelve keys):
  {"version", "plan_id", "request_id", "operation", "capability_name", "goal",
   "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
   "execution_allowed"}
  version "1"; request_id/operation/capability_name/goal/inputs/outputs/constraints
  exactly as in the request (lists copied, order kept);
  create  -> analysis_status "create_required",  existing_capability None;
  improve -> analysis_status "improve_required", existing_capability a deep copy
             of the validated matching descriptor;
  execution_allowed exactly False.

Build result (exactly these keys, fresh every call):
  {"status", "plan", "execution_allowed", "executed"}
status "ready" only together with a valid plan (else plan is None); both flags
are always False.

validate_capability_evolution_plan(plan) validates the exact 12-key shape and
every semantic invariant above (missing/extra keys, types, ids, operation,
analysis status, create/improve consistency, existing descriptor, execution
flag). It returns {"valid", "errors", "execution_allowed", "executed"} with
errors [{"code", "where"}] (at most MAX_ERRORS), reads its input only, and never
raises. Bounded work, deterministic.
"""

import copy

from .capability_evolution_analysis import (STATUS_CREATE_REQUIRED, STATUS_IMPROVE_REQUIRED,
                                            validate_capability_evolution_analysis)
from .capability_evolution_request import (REQUEST_VERSION,
                                           validate_capability_evolution_request)
from .capability_evolution_specification import validate_capability_evolution_specification
from .capability_evolution_validation import (STATUS_CONTEXT_MISMATCH, STATUS_READY,
                                              validate_capability_evolution,
                                              validate_capability_evolution_result)
from .capability_registry import MAX_ERRORS, validate_capability_descriptor

PLAN_VERSION = REQUEST_VERSION

STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_ANALYSIS = "invalid_analysis"
STATUS_INVALID_SPECIFICATION = "invalid_specification"
STATUS_INVALID_VALIDATION = "invalid_validation"
STATUS_CONTEXT = "context_mismatch"
STATUS_INVALID_PLAN_ID = "invalid_plan_id"
STATUS_UNSUPPORTED = "unsupported_status"
STATUS_PLAN_ERROR = "plan_error"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_READY, STATUS_INVALID_REQUEST, STATUS_INVALID_ANALYSIS,
            STATUS_INVALID_SPECIFICATION, STATUS_INVALID_VALIDATION, STATUS_CONTEXT,
            STATUS_INVALID_PLAN_ID, STATUS_UNSUPPORTED, STATUS_PLAN_ERROR, STATUS_ERROR)

FIELDS = ("version", "plan_id", "request_id", "operation", "capability_name", "goal",
          "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
          "execution_allowed")

# operation -> the only analysis status a plan may carry
PLAN_STATUS = {"create": STATUS_CREATE_REQUIRED, "improve": STATUS_IMPROVE_REQUIRED}

ERR_NOT_DICT = "plan_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_PLAN_ID = "invalid_plan_id"
ERR_INVALID_EXISTING = "invalid_existing_capability"
ERR_INVALID_ANALYSIS_STATUS = "invalid_analysis_status"
ERR_INCONSISTENT = "inconsistent_plan"
ERR_INTERNAL = "validation_error"


# ------------------------------------------------------------------ build

def _build_result(status, plan=None):
    return {"status": status, "plan": plan, "execution_allowed": False, "executed": False}


def _plan_id_valid(plan_id):
    """Reuse the Prompt 876 text rule (plan_id takes the `requested_by` slot)."""
    view = {"version": "1", "request_id": "r", "operation": "create", "capability_name": "c",
            "goal": "g", "inputs": [], "outputs": ["o"], "constraints": [],
            "requested_by": plan_id, "execution_allowed": False}
    return validate_capability_evolution_request(view)["valid"]


def build_capability_evolution_plan(evolution_request=None, analysis_result=None,
                                    specification=None, plan_id=None):
    """Build a fresh normalized plan, or report the first failing check."""
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
        if context["status"] == STATUS_CONTEXT_MISMATCH:
            return _build_result(STATUS_CONTEXT)
        if context["status"] == STATUS_READY and (
                context["request_id"] != request["request_id"]
                or context["capability_name"] != request["capability_name"]
                or context["operation"] != request["operation"]
                or context["analysis_status"] != analysis["status"]):
            return _build_result(STATUS_CONTEXT)

        if plan_id is None or not _plan_id_valid(plan_id):
            return _build_result(STATUS_INVALID_PLAN_ID)
        if (context["status"] != STATUS_READY or context["ready"] is not True
                or analysis["status"] != PLAN_STATUS[request["operation"]]):
            return _build_result(STATUS_UNSUPPORTED)

        plan = {
            "version": PLAN_VERSION,
            "plan_id": plan_id,
            "request_id": request["request_id"],
            "operation": request["operation"],
            "capability_name": request["capability_name"],
            "goal": request["goal"],
            "inputs": list(request["inputs"]),
            "outputs": list(request["outputs"]),
            "constraints": list(request["constraints"]),
            "existing_capability": copy.deepcopy(analysis["existing"]),
            "analysis_status": analysis["status"],
            "execution_allowed": False,
        }
        if _plan_errors(plan):
            return _build_result(STATUS_PLAN_ERROR)
        return _build_result(STATUS_READY, plan)
    except Exception:
        return _build_result(STATUS_ERROR)


# ------------------------------------------------------------- validation

def _plan_errors(plan):
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(plan) is not dict:
        add(ERR_NOT_DICT, "plan")
        return errors
    for key in FIELDS:
        if key not in plan:
            add(ERR_MISSING_KEY, key)
    for key in plan:
        if type(key) is not str or key not in FIELDS:
            add(ERR_UNEXPECTED_KEY, key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    # Shared fields: reuse the Prompt 876 validator on a request-shaped view.
    view = {"version": plan["version"], "request_id": plan["request_id"],
            "operation": plan["operation"], "capability_name": plan["capability_name"],
            "goal": plan["goal"], "inputs": plan["inputs"], "outputs": plan["outputs"],
            "constraints": plan["constraints"], "requested_by": plan["plan_id"],
            "execution_allowed": plan["execution_allowed"]}
    for error in validate_capability_evolution_request(view)["errors"]:
        if error["where"] == "requested_by":
            add(ERR_INVALID_PLAN_ID, "plan_id")
        else:
            add(error["code"], error["where"])

    existing = plan["existing_capability"]
    if existing is not None and not (
            type(existing) is dict and validate_capability_descriptor(existing)["valid"]):
        add(ERR_INVALID_EXISTING, "existing_capability")
    status = plan["analysis_status"]
    if type(status) is not str or status not in PLAN_STATUS.values():
        add(ERR_INVALID_ANALYSIS_STATUS, "analysis_status")
    if errors:
        return errors

    # create/improve semantics (every field is individually well formed here)
    operation = plan["operation"]
    if PLAN_STATUS[operation] != status:
        add(ERR_INCONSISTENT, "analysis_status")
    if operation == "create" and existing is not None:
        add(ERR_INCONSISTENT, "existing_capability")
    if operation == "improve":
        if existing is None:
            add(ERR_INCONSISTENT, "existing_capability")
        elif existing["name"] != plan["capability_name"]:
            add(ERR_INCONSISTENT, "capability_name")
    return errors


def validate_capability_evolution_plan(plan=None):
    """Validation result for a normalized capability evolution plan."""
    try:
        errors = _plan_errors(plan)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "plan"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
