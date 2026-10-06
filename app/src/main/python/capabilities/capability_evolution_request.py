"""
Capability Evolution Request Contract (Prompt 876, Section 16 - Capability Creation & Improvement)
===================================================================================================
A strict, JSON-safe description of WHAT capability change is requested: the
creation of a capability that does not exist yet, or the improvement of an
existing one. It is a data contract only: it generates no code and no patch,
modifies no capability, registry or descriptor, looks nothing up, performs no
filesystem I/O, subprocess, network, API or model call, and is not connected
to Core, Memory, AEL, research or any external service. It never performs or
allows self-modification. Nothing is inferred, coerced, trimmed, re-cased or
repaired: a missing or malformed value is an error, never replaced by a guess,
and the request id is always supplied by the caller (never generated).

  build_capability_evolution_request(request=None)   -> build result
  validate_capability_evolution_request(request)     -> validation result

Same lightweight contract style as research/research_request.py (Prompt 863);
the shared bounds are reused from capabilities/capability_registry.py.

Normalized request (exactly these ten keys):

  {"version", "request_id", "operation", "capability_name", "goal", "inputs",
   "outputs", "constraints", "requested_by", "execution_allowed"}

  version            exactly the string "1"
  request_id         text, <= MAX_ID_LENGTH
  operation          exactly "create" or "improve"
  capability_name    text, <= MAX_NAME_LENGTH
  goal               text, <= MAX_GOAL_LENGTH
  inputs             list (may be empty) of UNIQUE text, <= MAX_ITEMS items, each
                     <= MAX_NAME_LENGTH; caller order is preserved
  outputs            NON-EMPTY list of UNIQUE text, same bounds; order preserved
  constraints        list of text, <= MAX_ITEMS items, each <= MAX_CONSTRAINT_LENGTH
                     (an empty list is a stated value; duplicates are kept)
  requested_by       text, <= MAX_ID_LENGTH
  execution_allowed  exactly the bool False (a request never allows execution)

  "text" follows the Prompt 841 / 849 / 863 convention: an exact `str` (no
  subclass, so a bool is never text), non-empty, no leading/trailing
  whitespace, no control characters, bounded. Inputs and outputs are compared
  exactly (case-sensitive); nothing is sorted, de-duplicated or generated.

build_capability_evolution_request(request)
  `request` is an exact dict with the eight required keys request_id,
  operation, capability_name, goal, inputs, outputs, constraints, requested_by.
  `version` and `execution_allowed` are optional; when omitted they take their
  only legal values ("1" and False), when supplied they must already be
  exactly those values (execution_allowed=True is rejected, never ignored).
  Any other key is rejected. Missing keys are errors (nothing is defaulted or
  inferred). None is `missing_request`. Result (fixed keys, fresh every call):
    {"valid", "errors", "evolution_request", "execution_allowed", "executed"}
  `evolution_request` is a fresh normalized copy (lists copied) when valid,
  else None.

validate_capability_evolution_request(request)
  The same checks on an already normalized request: all ten keys are
  required, no others. Result (fixed keys, fresh on every call):
    {"valid", "errors", "execution_allowed", "executed"}

errors: [{"code", "where"}], at most MAX_ERRORS, in a fixed order (request
shape, then fields in the order above). Codes: missing_request,
request_not_dict, too_many_fields, unexpected_field, missing_field,
invalid_version, invalid_request_id, invalid_operation, invalid_capability_name,
invalid_goal, invalid_inputs, invalid_outputs, empty_outputs,
invalid_constraints, invalid_requested_by, invalid_execution_allowed,
too_many_items, invalid_item (where "inputs[i]" / "outputs[i]" /
"constraints[i]"), duplicate_item (where "inputs[i]" / "outputs[i]" of the
repeat), validation_error (unexpected internal failure).

`execution_allowed` and `executed` are always False in every result: a valid
evolution request never implies permission to create, change or execute
anything.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises.
"""

from .capability_registry import (MAX_CONSTRAINT_LENGTH, MAX_ERRORS, MAX_ITEMS,
                                  MAX_NAME_LENGTH, MAX_TEXT_LENGTH)

REQUEST_VERSION = "1"
OPERATIONS = ("create", "improve")

MAX_ID_LENGTH = 64
MAX_GOAL_LENGTH = MAX_TEXT_LENGTH
MAX_FIELDS = 16

FIELDS = ("version", "request_id", "operation", "capability_name", "goal", "inputs",
          "outputs", "constraints", "requested_by", "execution_allowed")
_BUILD_REQUIRED = ("request_id", "operation", "capability_name", "goal", "inputs", "outputs",
                   "constraints", "requested_by")
_TEXT_LIMITS = {"request_id": MAX_ID_LENGTH, "capability_name": MAX_NAME_LENGTH,
                "goal": MAX_GOAL_LENGTH, "requested_by": MAX_ID_LENGTH}
_LIST_LIMITS = {"inputs": MAX_NAME_LENGTH, "outputs": MAX_NAME_LENGTH,
                "constraints": MAX_CONSTRAINT_LENGTH}
_UNIQUE_LISTS = ("inputs", "outputs")

ERR_MISSING_REQUEST = "missing_request"
ERR_NOT_DICT = "request_not_dict"
ERR_TOO_MANY_FIELDS = "too_many_fields"
ERR_UNEXPECTED_FIELD = "unexpected_field"
ERR_MISSING_FIELD = "missing_field"
ERR_TOO_MANY_ITEMS = "too_many_items"
ERR_INVALID_ITEM = "invalid_item"
ERR_EMPTY_OUTPUTS = "empty_outputs"
ERR_DUPLICATE_ITEM = "duplicate_item"
ERR_INTERNAL = "validation_error"


def _is_text(value, limit):
    """Exact non-empty str, no outer whitespace, no control chars, bounded."""
    if type(value) is not str or not value or len(value) > limit:
        return False
    if value != value.strip():
        return False
    return not any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _where(key):
    return key if type(key) is str and 0 < len(key) <= 40 else "<field>"


def _add(errors, code, where):
    if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
        errors.append({"code": code, "where": where})


def _check_list(errors, field, value):
    if type(value) is not list:
        _add(errors, "invalid_" + field, field)
        return
    if len(value) > MAX_ITEMS:
        _add(errors, ERR_TOO_MANY_ITEMS, field)
        return
    if field == "outputs" and not value:
        _add(errors, ERR_EMPTY_OUTPUTS, field)
        return
    seen = set()
    for index, item in enumerate(value):
        if not _is_text(item, _LIST_LIMITS[field]):
            _add(errors, ERR_INVALID_ITEM, "%s[%d]" % (field, index))
        elif field in _UNIQUE_LISTS:
            if item in seen:
                _add(errors, ERR_DUPLICATE_ITEM, "%s[%d]" % (field, index))
            seen.add(item)


def _errors(data):
    """Errors of a request dict that must hold all ten fields."""
    errors = []
    if type(data) is not dict:
        _add(errors, ERR_MISSING_REQUEST if data is None else ERR_NOT_DICT, "request")
        return errors
    if len(data) > MAX_FIELDS:
        _add(errors, ERR_TOO_MANY_FIELDS, "request")
        return errors
    for key in data:
        if type(key) is not str or key not in FIELDS:
            _add(errors, ERR_UNEXPECTED_FIELD, _where(key))
    for field in FIELDS:
        if field not in data:
            _add(errors, ERR_MISSING_FIELD, field)
            continue
        value = data[field]
        if field == "version":
            if type(value) is not str or value != REQUEST_VERSION:
                _add(errors, "invalid_version", field)
        elif field == "operation":
            if type(value) is not str or value not in OPERATIONS:
                _add(errors, "invalid_operation", field)
        elif field in _TEXT_LIMITS:
            if not _is_text(value, _TEXT_LIMITS[field]):
                _add(errors, "invalid_" + field, field)
        elif field in _LIST_LIMITS:
            _check_list(errors, field, value)
        elif value is not False:
            _add(errors, "invalid_execution_allowed", field)
    return errors


def _validation(errors):
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}


def validate_capability_evolution_request(request=None):
    """Validation result for a normalized capability evolution request."""
    try:
        return _validation(_errors(request))
    except Exception:
        return _validation([{"code": ERR_INTERNAL, "where": "request"}])


def build_capability_evolution_request(request=None):
    """Build a fresh normalized evolution request from `request`, or report errors."""
    try:
        data = request
        if type(request) is dict and len(request) <= MAX_FIELDS:
            data = dict(request)
            for field in FIELDS:
                if field in _BUILD_REQUIRED:
                    continue
                data.setdefault(field, REQUEST_VERSION if field == "version" else False)
        errors = _errors(data)
        evolution_request = None
        if not errors:
            evolution_request = {
                "version": data["version"], "request_id": data["request_id"],
                "operation": data["operation"], "capability_name": data["capability_name"],
                "goal": data["goal"], "inputs": list(data["inputs"]),
                "outputs": list(data["outputs"]), "constraints": list(data["constraints"]),
                "requested_by": data["requested_by"], "execution_allowed": False}
        return {"valid": not errors, "errors": errors, "evolution_request": evolution_request,
                "execution_allowed": False, "executed": False}
    except Exception:
        return {"valid": False, "errors": [{"code": ERR_INTERNAL, "where": "request"}],
                "evolution_request": None, "execution_allowed": False, "executed": False}
