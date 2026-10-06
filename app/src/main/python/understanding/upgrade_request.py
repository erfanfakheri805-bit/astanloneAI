"""
Self-Upgrade Request Contract (Prompt 849, Section 14 - Self-Upgrade Engine)
============================================================================
A strict, JSON-safe description of WHAT upgrade is being requested. It is a
data contract only: it plans nothing, inspects and generates no source code,
modifies no project file, executes nothing and is not connected to Core,
Memory, AEL, the Capability System or any external service. Nothing is
inferred, coerced, trimmed or repaired: a missing or malformed value is an
error, never replaced by a guess.

  build_upgrade_request(request=None)    -> build result
  validate_upgrade_request(upgrade_request) -> validation result

Normalized upgrade request (exactly these seven keys):

  {"version", "request_id", "goal", "scope", "constraints", "requested_by",
   "execution_allowed"}

  version            exactly the string "1"
  request_id         text, <= MAX_ID_LENGTH
  goal               text, <= MAX_GOAL_LENGTH
  scope              list of text, <= MAX_ITEMS items, each <= MAX_ITEM_LENGTH
  constraints        list of text, <= MAX_ITEMS items, each <= MAX_ITEM_LENGTH
  requested_by       text, <= MAX_ID_LENGTH
  execution_allowed  exactly the bool False (a request never allows execution)

  "text" follows the Prompt 841 text convention: an exact `str` (no subclass),
  non-empty, no leading/trailing whitespace, no control characters, bounded.
  `scope` and `constraints` are exact lists (possibly empty; an empty list is
  a stated value, not a guess) whose items are all valid text. Lists are not
  de-duplicated, sorted or otherwise normalised.

build_upgrade_request(request)
  `request` is an exact dict with the five required keys request_id, goal,
  scope, constraints, requested_by. `version` and `execution_allowed` are
  optional; when omitted they take their only legal values ("1" and False),
  when supplied they must already be exactly those values (execution_allowed=
  True is rejected, never ignored). Any other key is rejected. Missing keys
  are errors (nothing is defaulted or inferred). None is `missing_request`.
  Result (fixed keys, fresh on every call):
    {"valid", "errors", "upgrade_request", "execution_allowed", "executed"}
  `upgrade_request` is a fresh normalized copy (lists copied) when valid,
  else None.

validate_upgrade_request(upgrade_request)
  The same checks on an already normalized request: all seven keys are
  required, no others. Result (fixed keys, fresh on every call):
    {"valid", "errors", "execution_allowed", "executed"}

errors: [{"code", "where"}], at most MAX_ERRORS, in a fixed order (request
shape, then fields in the order above). Codes: missing_request,
request_not_dict, too_many_fields, unexpected_field, missing_field,
invalid_version, invalid_request_id, invalid_goal, invalid_scope,
invalid_constraints, invalid_requested_by, invalid_execution_allowed,
too_many_items, invalid_item (where "scope[i]" / "constraints[i]"),
validation_error (unexpected internal failure).

`execution_allowed` and `executed` are always False in every result: a valid
upgrade request never implies permission to execute anything.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises. Pure Python with no imports; no filesystem, network, LLM, Core,
Memory or AEL.
"""

REQUEST_VERSION = "1"

MAX_ID_LENGTH = 64
MAX_GOAL_LENGTH = 500
MAX_ITEM_LENGTH = 200
MAX_ITEMS = 16
MAX_ERRORS = 16
MAX_FIELDS = 16

FIELDS = ("version", "request_id", "goal", "scope", "constraints", "requested_by",
          "execution_allowed")
_BUILD_REQUIRED = ("request_id", "goal", "scope", "constraints", "requested_by")
_LIST_FIELDS = ("scope", "constraints")
_TEXT_LIMITS = {"request_id": MAX_ID_LENGTH, "goal": MAX_GOAL_LENGTH,
                "requested_by": MAX_ID_LENGTH}

ERR_MISSING_REQUEST = "missing_request"
ERR_NOT_DICT = "request_not_dict"
ERR_TOO_MANY_FIELDS = "too_many_fields"
ERR_UNEXPECTED_FIELD = "unexpected_field"
ERR_MISSING_FIELD = "missing_field"
ERR_TOO_MANY_ITEMS = "too_many_items"
ERR_INVALID_ITEM = "invalid_item"
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
    elif len(value) > MAX_ITEMS:
        _add(errors, ERR_TOO_MANY_ITEMS, field)
    else:
        for index, item in enumerate(value):
            if not _is_text(item, MAX_ITEM_LENGTH):
                _add(errors, ERR_INVALID_ITEM, "%s[%d]" % (field, index))


def _errors(data):
    """Errors of a request dict that must hold all seven fields."""
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
        elif field in _TEXT_LIMITS:
            if not _is_text(value, _TEXT_LIMITS[field]):
                _add(errors, "invalid_" + field, field)
        elif field in _LIST_FIELDS:
            _check_list(errors, field, value)
        elif value is not False:
            _add(errors, "invalid_execution_allowed", field)
    return errors


def _validation(errors):
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}


def validate_upgrade_request(upgrade_request=None):
    """Validation result for a normalized upgrade request."""
    try:
        return _validation(_errors(upgrade_request))
    except Exception:
        return _validation([{"code": ERR_INTERNAL, "where": "request"}])


def build_upgrade_request(request=None):
    """Build a fresh normalized upgrade request from `request`, or report errors."""
    try:
        data = request
        if type(request) is dict and len(request) <= MAX_FIELDS:
            data = dict(request)
            for field in FIELDS:
                if field in _BUILD_REQUIRED:
                    continue
                data.setdefault(field, REQUEST_VERSION if field == "version" else False)
        errors = _errors(data)
        upgrade_request = None
        if not errors:
            upgrade_request = {
                "version": data["version"], "request_id": data["request_id"],
                "goal": data["goal"], "scope": list(data["scope"]),
                "constraints": list(data["constraints"]),
                "requested_by": data["requested_by"], "execution_allowed": False}
        return {"valid": not errors, "errors": errors, "upgrade_request": upgrade_request,
                "execution_allowed": False, "executed": False}
    except Exception:
        return {"valid": False, "errors": [{"code": ERR_INTERNAL, "where": "request"}],
                "upgrade_request": None, "execution_allowed": False, "executed": False}
