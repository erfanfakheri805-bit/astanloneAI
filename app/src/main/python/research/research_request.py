"""
Research Request Contract (Prompt 863, Section 15 - Autonomous Research & Learning)
===================================================================================
A strict, JSON-safe description of WHAT is to be researched. It is a data
contract only: it performs no research, retrieves no source, makes no web,
network, API or external AI call, performs no filesystem I/O or subprocess,
generates no topics and is not connected to Core, Memory, AEL or any external
service. Nothing is inferred, coerced, trimmed or repaired: a missing or
malformed value is an error, never replaced by a guess.

  build_research_request(request=None)        -> build result
  validate_research_request(research_request) -> validation result

Same lightweight contract style as upgrade/upgrade_request.py (Prompt 849).

Normalized research request (exactly these seven keys):

  {"version", "request_id", "goal", "topics", "constraints", "requested_by",
   "execution_allowed"}

  version            exactly the string "1"
  request_id         text, <= MAX_ID_LENGTH
  goal               text, <= MAX_GOAL_LENGTH
  topics             NON-EMPTY list of UNIQUE text, <= MAX_ITEMS items, each
                     <= MAX_ITEM_LENGTH; caller order is preserved
  constraints        list of text, <= MAX_ITEMS items, each <= MAX_ITEM_LENGTH
                     (an empty list is a stated value, not a guess; duplicates
                     are not an error and are kept)
  requested_by       text, <= MAX_ID_LENGTH
  execution_allowed  exactly the bool False (a request never allows execution)

  "text" follows the Prompt 841 / 849 convention: an exact `str` (no
  subclass), non-empty, no leading/trailing whitespace, no control
  characters, bounded. Topics are compared exactly (case-sensitive, no
  normalisation); nothing is sorted, de-duplicated or generated.

build_research_request(request)
  `request` is an exact dict with the five required keys request_id, goal,
  topics, constraints, requested_by. `version` and `execution_allowed` are
  optional; when omitted they take their only legal values ("1" and False),
  when supplied they must already be exactly those values (execution_allowed=
  True is rejected, never ignored). Any other key is rejected. Missing keys
  are errors (nothing is defaulted or inferred). None is `missing_request`.
  Result (fixed keys, fresh on every call):
    {"valid", "errors", "research_request", "execution_allowed", "executed"}
  `research_request` is a fresh normalized copy (lists copied) when valid,
  else None.

validate_research_request(research_request)
  The same checks on an already normalized request: all seven keys are
  required, no others. Result (fixed keys, fresh on every call):
    {"valid", "errors", "execution_allowed", "executed"}

errors: [{"code", "where"}], at most MAX_ERRORS, in a fixed order (request
shape, then fields in the order above). Codes: missing_request,
request_not_dict, too_many_fields, unexpected_field, missing_field,
invalid_version, invalid_request_id, invalid_goal, invalid_topics,
empty_topics, invalid_constraints, invalid_requested_by,
invalid_execution_allowed, too_many_items, invalid_item (where "topics[i]" /
"constraints[i]"), duplicate_topic (where "topics[i]" of the repeat),
validation_error (unexpected internal failure).

`execution_allowed` and `executed` are always False in every result: a valid
research request never implies permission to research or execute anything.

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

FIELDS = ("version", "request_id", "goal", "topics", "constraints", "requested_by",
          "execution_allowed")
_BUILD_REQUIRED = ("request_id", "goal", "topics", "constraints", "requested_by")
_LIST_FIELDS = ("topics", "constraints")
_TEXT_LIMITS = {"request_id": MAX_ID_LENGTH, "goal": MAX_GOAL_LENGTH,
                "requested_by": MAX_ID_LENGTH}

ERR_MISSING_REQUEST = "missing_request"
ERR_NOT_DICT = "request_not_dict"
ERR_TOO_MANY_FIELDS = "too_many_fields"
ERR_UNEXPECTED_FIELD = "unexpected_field"
ERR_MISSING_FIELD = "missing_field"
ERR_TOO_MANY_ITEMS = "too_many_items"
ERR_INVALID_ITEM = "invalid_item"
ERR_EMPTY_TOPICS = "empty_topics"
ERR_DUPLICATE_TOPIC = "duplicate_topic"
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
    if field == "topics" and not value:
        _add(errors, ERR_EMPTY_TOPICS, field)
        return
    seen = set()
    for index, item in enumerate(value):
        if not _is_text(item, MAX_ITEM_LENGTH):
            _add(errors, ERR_INVALID_ITEM, "%s[%d]" % (field, index))
        elif field == "topics":
            if item in seen:
                _add(errors, ERR_DUPLICATE_TOPIC, "%s[%d]" % (field, index))
            seen.add(item)


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


def validate_research_request(research_request=None):
    """Validation result for a normalized research request."""
    try:
        return _validation(_errors(research_request))
    except Exception:
        return _validation([{"code": ERR_INTERNAL, "where": "request"}])


def build_research_request(request=None):
    """Build a fresh normalized research request from `request`, or report errors."""
    try:
        data = request
        if type(request) is dict and len(request) <= MAX_FIELDS:
            data = dict(request)
            for field in FIELDS:
                if field in _BUILD_REQUIRED:
                    continue
                data.setdefault(field, REQUEST_VERSION if field == "version" else False)
        errors = _errors(data)
        research_request = None
        if not errors:
            research_request = {
                "version": data["version"], "request_id": data["request_id"],
                "goal": data["goal"], "topics": list(data["topics"]),
                "constraints": list(data["constraints"]),
                "requested_by": data["requested_by"], "execution_allowed": False}
        return {"valid": not errors, "errors": errors, "research_request": research_request,
                "execution_allowed": False, "executed": False}
    except Exception:
        return {"valid": False, "errors": [{"code": ERR_INTERNAL, "where": "request"}],
                "research_request": None, "execution_allowed": False, "executed": False}
