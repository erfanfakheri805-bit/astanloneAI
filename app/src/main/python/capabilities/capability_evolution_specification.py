"""
Capability Evolution Specification (Prompt 878, Section 16 - Capability Creation & Improvement)
===============================================================================================
Turns a validated Prompt 876 evolution request and a Prompt 877 analysis result
into a deterministic, JSON-safe SPECIFICATION of the requested capability
creation or improvement, for a future stage to consume. It is a data contract
only: it generates no code and no patch, modifies no descriptor, registry or
capability, inspects no filesystem, touches no Memory, AEL, research source,
network, API or model, executes nothing, and never performs or allows
self-modification. Nothing is inferred, merged, ranked, enriched, normalized or
repaired, and the specification id is never generated.

  build_capability_evolution_specification(evolution_request, analysis_result,
                                           existing_capability=None,
                                           specification_id=None)  -> build result
  validate_capability_evolution_specification(specification)       -> validation result

specification_id is supplied by the caller (the required three-argument form has
no other place to carry it, so it is an optional fourth keyword argument). If it
is missing (None) the build fails with `missing_specification_id`; it is never
generated or defaulted.

Build checks run in this fixed order; the first failure is returned as the only
error, {"code", "where"}:
  1 invalid_evolution_request     request fails validate_capability_evolution_request
  2 invalid_analysis_result       analysis fails validate_capability_evolution_analysis
  3 operation_mismatch            analysis["operation"] != request["operation"]
  4 capability_name_mismatch      analysis["capability_name"] != request["capability_name"]
  5 invalid_existing_capability   existing_capability is not None and is not a valid
                                  descriptor (validate_capability_descriptor)
  6 existing_identity_mismatch    existing_capability is not None and != analysis["existing"]
  7 unsupported_analysis_status   status not create_required / improve_required /
                                  improve_or_conflict (missing_target never yields one)
    missing_specification_id / invalid_specification_id
  8 specification_error           the built specification fails its own validator

existing_capability is optional: when None, the descriptor already carried by the
analysis result is used. When given, it must be a valid descriptor equal to
analysis["existing"] (so a create_required analysis accepts only None).

Normalized specification (exactly these eleven keys):
  {"version", "specification_id", "request_id", "operation", "capability_name",
   "goal", "inputs", "outputs", "constraints", "existing_capability",
   "analysis_status", "execution_allowed"}

  version              exactly "1"
  specification_id     caller-supplied text, <= MAX_ID_LENGTH
  request_id ... constraints   exactly as in the request (lists copied, order kept)
  existing_capability  None for create_required; otherwise a deep copy of the
                       validated matching descriptor
  analysis_status      the exact Prompt 877 status (improve_or_conflict is kept)
  execution_allowed    exactly False

Build result (fresh every call):
  {"valid", "errors", "specification", "execution_allowed", "executed"}
specification is a fresh dict when valid, else None; the two flags are always False.

validate_capability_evolution_specification(specification) checks only the
normalized specification, reusing the Prompt 876 request validator for the shared
fields and the registry descriptor validator for existing_capability, and rejects
inconsistent combinations (create with an existing capability, improve without
one, create_required with one, improve_required without one, missing_target or
any other non-supported status, wrong flags, extra or missing keys). Result:
  {"valid", "errors", "execution_allowed", "executed"}
errors: [{"code", "where"}], at most MAX_ERRORS.

Bounded work, read-only (inputs are never modified or retained), deterministic,
never raises.
"""

import copy

from .capability_evolution_analysis import (STATUS_CREATE_REQUIRED, STATUS_IMPROVE_OR_CONFLICT,
                                            STATUS_IMPROVE_REQUIRED, STATUSES,
                                            validate_capability_evolution_analysis)
from .capability_evolution_request import (REQUEST_VERSION,
                                           validate_capability_evolution_request)
from .capability_registry import MAX_ERRORS, validate_capability_descriptor

SPEC_VERSION = REQUEST_VERSION
SUPPORTED_STATUSES = (STATUS_CREATE_REQUIRED, STATUS_IMPROVE_REQUIRED, STATUS_IMPROVE_OR_CONFLICT)

FIELDS = ("version", "specification_id", "request_id", "operation", "capability_name", "goal",
          "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
          "execution_allowed")

# status -> operation the specification must carry
_STATUS_OPERATION = {STATUS_CREATE_REQUIRED: "create", STATUS_IMPROVE_OR_CONFLICT: "create",
                     STATUS_IMPROVE_REQUIRED: "improve"}

ERR_INVALID_REQUEST = "invalid_evolution_request"
ERR_INVALID_ANALYSIS = "invalid_analysis_result"
ERR_OPERATION_MISMATCH = "operation_mismatch"
ERR_NAME_MISMATCH = "capability_name_mismatch"
ERR_INVALID_EXISTING = "invalid_existing_capability"
ERR_IDENTITY_MISMATCH = "existing_identity_mismatch"
ERR_UNSUPPORTED_STATUS = "unsupported_analysis_status"
ERR_MISSING_ID = "missing_specification_id"
ERR_INVALID_ID = "invalid_specification_id"
ERR_SPEC_ERROR = "specification_error"

ERR_NOT_DICT = "specification_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_INVALID_STATUS = "invalid_analysis_status"
ERR_INVALID_EXISTING_SPEC = "invalid_existing_capability"
ERR_INCONSISTENT = "inconsistent_specification"
ERR_INTERNAL = "validation_error"


# ------------------------------------------------------------------ build

def _failure(code, where):
    return {"valid": False, "errors": [{"code": code, "where": where}], "specification": None,
            "execution_allowed": False, "executed": False}


def build_capability_evolution_specification(evolution_request=None, analysis_result=None,
                                             existing_capability=None, specification_id=None):
    """Build a fresh normalized specification, or report the first failing check."""
    try:
        if not validate_capability_evolution_request(evolution_request)["valid"]:
            return _failure(ERR_INVALID_REQUEST, "evolution_request")
        if not validate_capability_evolution_analysis(analysis_result)["valid"]:
            return _failure(ERR_INVALID_ANALYSIS, "analysis_result")
        if analysis_result["operation"] != evolution_request["operation"]:
            return _failure(ERR_OPERATION_MISMATCH, "operation")
        if analysis_result["capability_name"] != evolution_request["capability_name"]:
            return _failure(ERR_NAME_MISMATCH, "capability_name")
        if existing_capability is not None:
            if not validate_capability_descriptor(existing_capability)["valid"]:
                return _failure(ERR_INVALID_EXISTING, "existing_capability")
            if existing_capability != analysis_result["existing"]:
                return _failure(ERR_IDENTITY_MISMATCH, "existing_capability")
        status = analysis_result["status"]
        if status not in SUPPORTED_STATUSES:
            return _failure(ERR_UNSUPPORTED_STATUS, "analysis_status")
        if specification_id is None:
            return _failure(ERR_MISSING_ID, "specification_id")

        specification = {
            "version": SPEC_VERSION,
            "specification_id": specification_id,
            "request_id": evolution_request["request_id"],
            "operation": evolution_request["operation"],
            "capability_name": evolution_request["capability_name"],
            "goal": evolution_request["goal"],
            "inputs": list(evolution_request["inputs"]),
            "outputs": list(evolution_request["outputs"]),
            "constraints": list(evolution_request["constraints"]),
            "existing_capability": copy.deepcopy(analysis_result["existing"]),
            "analysis_status": status,
            "execution_allowed": False,
        }
        errors = _specification_errors(specification)
        if errors:
            if {"code": ERR_INVALID_ID, "where": "specification_id"} in errors:
                return _failure(ERR_INVALID_ID, "specification_id")
            return _failure(ERR_SPEC_ERROR, "specification")
        return {"valid": True, "errors": [], "specification": specification,
                "execution_allowed": False, "executed": False}
    except Exception:
        return _failure(ERR_SPEC_ERROR, "specification")


# ------------------------------------------------------------- validation

def _specification_errors(spec):
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(spec) is not dict:
        add(ERR_NOT_DICT, "specification")
        return errors
    for key in FIELDS:
        if key not in spec:
            add(ERR_MISSING_KEY, key)
    for key in spec:
        if type(key) is not str or key not in FIELDS:
            add(ERR_UNEXPECTED_KEY, key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if errors:
        return errors

    # Shared fields: reuse the Prompt 876 validator on a request-shaped view. The
    # specification id takes the slot of `requested_by` (same text rule and bound).
    view = {"version": spec["version"], "request_id": spec["request_id"],
            "operation": spec["operation"], "capability_name": spec["capability_name"],
            "goal": spec["goal"], "inputs": spec["inputs"], "outputs": spec["outputs"],
            "constraints": spec["constraints"], "requested_by": spec["specification_id"],
            "execution_allowed": spec["execution_allowed"]}
    for error in validate_capability_evolution_request(view)["errors"]:
        if error["where"] == "requested_by":
            add(ERR_INVALID_ID, "specification_id")
        else:
            add(error["code"], error["where"])

    existing = spec["existing_capability"]
    existing_ok = existing is None or (
        type(existing) is dict and validate_capability_descriptor(existing)["valid"])
    if not existing_ok:
        add(ERR_INVALID_EXISTING_SPEC, "existing_capability")

    status = spec["analysis_status"]
    if type(status) is not str or status not in STATUSES:
        add(ERR_INVALID_STATUS, "analysis_status")
    elif status not in SUPPORTED_STATUSES:
        add(ERR_UNSUPPORTED_STATUS, "analysis_status")

    if errors:
        return errors

    # cross-field consistency (every field is individually well formed here)
    operation = spec["operation"]
    if operation == "create" and existing is not None and status == STATUS_CREATE_REQUIRED:
        add(ERR_INCONSISTENT, "existing_capability")
    if operation == "improve" and existing is None:
        add(ERR_INCONSISTENT, "existing_capability")
    if _STATUS_OPERATION[status] != operation:
        add(ERR_INCONSISTENT, "operation")
    if status == STATUS_CREATE_REQUIRED and existing is not None:
        add(ERR_INCONSISTENT, "existing_capability")
    if status != STATUS_CREATE_REQUIRED and existing is None:
        add(ERR_INCONSISTENT, "existing_capability")
    if existing is not None and existing["name"] != spec["capability_name"]:
        add(ERR_INCONSISTENT, "capability_name")
    return errors


def validate_capability_evolution_specification(specification=None):
    """Validation result for a normalized capability evolution specification."""
    try:
        errors = _specification_errors(specification)
    except Exception:
        errors = [{"code": ERR_INTERNAL, "where": "specification"}]
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}
