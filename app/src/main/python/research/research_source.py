"""
Research Source Contract (Prompt 864, Section 15 - Autonomous Research & Learning)
==================================================================================
A strict, JSON-safe description of WHERE a future controlled research step may
look. It is a data contract only: it opens no file, accesses no URL, makes no
network or API request, invokes no external model, runs no command, retrieves
no source content, and is not connected to Core, Memory, AEL or any external
service. `location` is opaque text: it is never parsed, resolved, normalised or
checked for existence. Nothing is inferred, coerced, trimmed or repaired: a
missing or malformed value is an error, never replaced by a guess.

  build_research_source(source=None) -> build result
  validate_research_source(source)   -> validation result

Self-contained (no imports); same lightweight contract style as the Prompt 849
and 863 contracts, without depending on Section 14 helpers.

Normalized research source (exactly these eight keys):

  {"version", "source_id", "source_type", "location", "trust_level",
   "constraints", "enabled", "execution_allowed"}

  version            exactly the string "1"
  source_id          text, <= MAX_ID_LENGTH
  source_type        exactly one of SOURCE_TYPES: "local_file", "user_input",
                     "learned_record", "web", "api", "external_model"
  location           text, <= MAX_LOCATION_LENGTH (opaque, never interpreted)
  trust_level        exactly one of TRUST_LEVELS: "untrusted", "standard",
                     "trusted"
  constraints        list of text, <= MAX_ITEMS items, each <= MAX_ITEM_LENGTH
                     (an empty list is a stated value; duplicates are kept)
  enabled            exactly a bool (True or False), a stated value
  execution_allowed  exactly the bool False (a source never allows execution;
                     enabled=True is only a declaration, not permission)

  "text" follows the Prompt 841 / 849 convention: an exact `str` (no
  subclass), non-empty, no leading/trailing whitespace, no control
  characters, bounded. Enum values are compared exactly (case-sensitive).

build_research_source(source)
  `source` is an exact dict with the six required keys source_id, source_type,
  location, trust_level, constraints, enabled. `version` and
  `execution_allowed` are optional; when omitted they take their only legal
  values ("1" and False), when supplied they must already be exactly those
  values (execution_allowed=True is rejected, never ignored). Any other key is
  rejected. Missing keys are errors (nothing is defaulted or inferred, not
  even `enabled`). None is `missing_source`. Result (fixed keys, fresh):
    {"valid", "errors", "source", "execution_allowed", "executed"}
  `source` is a fresh normalized copy (constraints list copied) when valid,
  else None.

validate_research_source(source)
  The same checks on an already normalized source: all eight keys are
  required, no others. Result (fixed keys, fresh on every call):
    {"valid", "errors", "execution_allowed", "executed"}

errors: [{"code", "where"}], at most MAX_ERRORS, in a fixed order (source
shape, then fields in the order above). Codes: missing_source,
source_not_dict, too_many_fields, unexpected_field, missing_field,
invalid_version, invalid_source_id, invalid_source_type, invalid_location,
invalid_trust_level, invalid_constraints, invalid_enabled,
invalid_execution_allowed, too_many_items, invalid_item (where
"constraints[i]"), validation_error (unexpected internal failure).

`execution_allowed` and `executed` are always False in every result.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises. Pure Python with no imports; no filesystem, network, LLM, Core,
Memory or AEL.
"""

SOURCE_VERSION = "1"

SOURCE_TYPES = ("local_file", "user_input", "learned_record", "web", "api", "external_model")
TRUST_LEVELS = ("untrusted", "standard", "trusted")

MAX_ID_LENGTH = 64
MAX_LOCATION_LENGTH = 500
MAX_ITEM_LENGTH = 200
MAX_ITEMS = 16
MAX_ERRORS = 16
MAX_FIELDS = 16

FIELDS = ("version", "source_id", "source_type", "location", "trust_level", "constraints",
          "enabled", "execution_allowed")
_OPTIONAL = ("version", "execution_allowed")
_TEXT_LIMITS = {"source_id": MAX_ID_LENGTH, "location": MAX_LOCATION_LENGTH}
_ENUMS = {"source_type": SOURCE_TYPES, "trust_level": TRUST_LEVELS}

ERR_MISSING_SOURCE = "missing_source"
ERR_NOT_DICT = "source_not_dict"
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


def _check_constraints(errors, value):
    if type(value) is not list:
        _add(errors, "invalid_constraints", "constraints")
    elif len(value) > MAX_ITEMS:
        _add(errors, ERR_TOO_MANY_ITEMS, "constraints")
    else:
        for index, item in enumerate(value):
            if not _is_text(item, MAX_ITEM_LENGTH):
                _add(errors, ERR_INVALID_ITEM, "constraints[%d]" % index)


def _errors(data):
    """Errors of a source dict that must hold all eight fields."""
    errors = []
    if type(data) is not dict:
        _add(errors, ERR_MISSING_SOURCE if data is None else ERR_NOT_DICT, "source")
        return errors
    if len(data) > MAX_FIELDS:
        _add(errors, ERR_TOO_MANY_FIELDS, "source")
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
            if type(value) is not str or value != SOURCE_VERSION:
                _add(errors, "invalid_version", field)
        elif field in _TEXT_LIMITS:
            if not _is_text(value, _TEXT_LIMITS[field]):
                _add(errors, "invalid_" + field, field)
        elif field in _ENUMS:
            if type(value) is not str or value not in _ENUMS[field]:
                _add(errors, "invalid_" + field, field)
        elif field == "constraints":
            _check_constraints(errors, value)
        elif field == "enabled":
            if type(value) is not bool:
                _add(errors, "invalid_enabled", field)
        elif value is not False:
            _add(errors, "invalid_execution_allowed", field)
    return errors


def _validation(errors):
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}


def validate_research_source(source=None):
    """Validation result for a normalized research source."""
    try:
        return _validation(_errors(source))
    except Exception:
        return _validation([{"code": ERR_INTERNAL, "where": "source"}])


def build_research_source(source=None):
    """Build a fresh normalized research source from `source`, or report errors."""
    try:
        data = source
        if type(source) is dict and len(source) <= MAX_FIELDS:
            data = dict(source)
            for field in _OPTIONAL:
                data.setdefault(field, SOURCE_VERSION if field == "version" else False)
        errors = _errors(data)
        built = None
        if not errors:
            built = {"version": data["version"], "source_id": data["source_id"],
                     "source_type": data["source_type"], "location": data["location"],
                     "trust_level": data["trust_level"],
                     "constraints": list(data["constraints"]),
                     "enabled": data["enabled"], "execution_allowed": False}
        return {"valid": not errors, "errors": errors, "source": built,
                "execution_allowed": False, "executed": False}
    except Exception:
        return {"valid": False, "errors": [{"code": ERR_INTERNAL, "where": "source"}],
                "source": None, "execution_allowed": False, "executed": False}
