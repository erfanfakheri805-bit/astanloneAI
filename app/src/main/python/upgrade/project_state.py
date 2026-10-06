"""
Upgrade Project State (Prompt 850, Section 14 - Self-Upgrade Engine)
====================================================================
A small, JSON-safe snapshot of the project state a future self-upgrade planner
may need, built ONLY from structured metadata supplied by the caller. It
describes supplied state and nothing else: it reads, writes, scans and
discovers no file, runs no test, changes no capability, generates no patch or
code, performs no upgrade and is not connected to Core, Memory, AEL, the
Capability System or any external service. Nothing is inferred, coerced,
trimmed or repaired: a missing or malformed value is an error, never replaced
by a guess.

  build_project_state(source=None)       -> build result
  validate_project_state(project_state)  -> validation result

Normalized project state (exactly these eight keys):

  {"version", "project_id", "revision", "files", "capabilities", "tests",
   "constraints", "execution_allowed"}

  version            exactly the string "1"
  project_id         text, <= MAX_ID_LENGTH
  revision           text, <= MAX_ID_LENGTH
  files              list, <= MAX_FILES descriptors; each descriptor is an exact
                     dict with exactly the keys path, kind, status
                       path    text, <= MAX_PATH_LENGTH
                       kind    text, <= MAX_ID_LENGTH
                       status  text, <= MAX_ID_LENGTH
  capabilities       list, <= MAX_CAPABILITIES items, each text <= MAX_ID_LENGTH
  tests              list, <= MAX_TESTS items, each text <= MAX_ITEM_LENGTH
  constraints        list, <= MAX_CONSTRAINTS items, each text <= MAX_ITEM_LENGTH
  execution_allowed  exactly the bool False (a snapshot never allows execution)

  "text" is the Prompt 849 / 841 convention (reused from upgrade_request): an
  exact `str` (no subclass), non-empty, no leading/trailing whitespace, no
  control characters, bounded. Containers must be the exact built-in `dict` /
  `list`. Empty lists are stated values, not guesses. Lists are never
  de-duplicated, sorted or otherwise normalised; a file's path is an opaque
  caller-supplied label and is never opened, resolved or checked.

build_project_state(source)
  `source` is an exact dict with the six required keys project_id, revision,
  files, capabilities, tests, constraints. `version` and `execution_allowed`
  are optional; when omitted they take their only legal values ("1" and
  False), when supplied they must already be exactly those values
  (execution_allowed=True is rejected, never ignored). Any other key is
  rejected, missing keys are errors, None is `missing_source`.
  Result (fixed keys, fresh on every call):
    {"valid", "errors", "project_state", "execution_allowed", "executed"}
  `project_state` is a fresh normalized copy (lists and descriptors copied)
  when valid, else None. The normalized object itself carries no "executed".

validate_project_state(project_state)
  The same checks on an already normalized state: all eight keys required, no
  others. Result (fixed keys, fresh on every call):
    {"valid", "errors", "execution_allowed", "executed"}

errors: [{"code", "where"}], at most MAX_ERRORS (reused from upgrade_request),
in a fixed order (shape, then fields in the order above). Codes:
missing_source / missing_state (None input), source_not_dict / state_not_dict,
too_many_fields, unexpected_field, missing_field, invalid_version,
invalid_project_id, invalid_revision, invalid_files, invalid_capabilities,
invalid_tests, invalid_constraints, invalid_execution_allowed, too_many_items
(where = the field), invalid_item (where "capabilities[i]" etc.),
invalid_file (descriptor not an exact dict, where "files[i]"),
too_many_file_fields, unexpected_file_field, missing_file_field,
invalid_file_path / invalid_file_kind / invalid_file_status (where
"files[i].path" etc.), validation_error (unexpected internal failure).

`execution_allowed` and `executed` are always False in every result: a valid
project state never implies permission to execute, test or change anything.

Bounded work (oversized containers are rejected without scanning their
items), read-only (inputs are never modified or kept), deterministic, never
raises. Only the Prompt 849 helpers are imported; no filesystem, network, LLM,
Core, Memory or AEL.
"""

from upgrade.upgrade_request import (
    ERR_INTERNAL,
    ERR_INVALID_ITEM,
    ERR_TOO_MANY_FIELDS,
    ERR_TOO_MANY_ITEMS,
    ERR_UNEXPECTED_FIELD,
    ERR_MISSING_FIELD,
    MAX_FIELDS,
    _add,
    _is_text,
    _where,
)

STATE_VERSION = "1"

MAX_ID_LENGTH = 64
MAX_PATH_LENGTH = 200
MAX_ITEM_LENGTH = 200
MAX_FILES = 256
MAX_CAPABILITIES = 64
MAX_TESTS = 128
MAX_CONSTRAINTS = 16

FIELDS = ("version", "project_id", "revision", "files", "capabilities", "tests",
          "constraints", "execution_allowed")
FILE_FIELDS = ("path", "kind", "status")
_BUILD_REQUIRED = ("project_id", "revision", "files", "capabilities", "tests",
                   "constraints")
_TEXT_LIMITS = {"project_id": MAX_ID_LENGTH, "revision": MAX_ID_LENGTH}
_FILE_LIMITS = {"path": MAX_PATH_LENGTH, "kind": MAX_ID_LENGTH, "status": MAX_ID_LENGTH}
# field -> (max items, max item length)
_LIST_LIMITS = {"capabilities": (MAX_CAPABILITIES, MAX_ID_LENGTH),
                "tests": (MAX_TESTS, MAX_ITEM_LENGTH),
                "constraints": (MAX_CONSTRAINTS, MAX_ITEM_LENGTH)}

ERR_MISSING_SOURCE = "missing_source"
ERR_MISSING_STATE = "missing_state"
ERR_SOURCE_NOT_DICT = "source_not_dict"
ERR_STATE_NOT_DICT = "state_not_dict"


def _check_text_list(errors, field, value):
    max_items, max_length = _LIST_LIMITS[field]
    if type(value) is not list:
        _add(errors, "invalid_" + field, field)
    elif len(value) > max_items:
        _add(errors, ERR_TOO_MANY_ITEMS, field)
    else:
        for index, item in enumerate(value):
            if not _is_text(item, max_length):
                _add(errors, ERR_INVALID_ITEM, "%s[%d]" % (field, index))


def _check_file(errors, index, descriptor):
    where = "files[%d]" % index
    if type(descriptor) is not dict:
        _add(errors, "invalid_file", where)
        return
    if len(descriptor) > MAX_FIELDS:
        _add(errors, "too_many_file_fields", where)
        return
    for key in descriptor:
        if type(key) is not str or key not in FILE_FIELDS:
            _add(errors, "unexpected_file_field", "%s.%s" % (where, _where(key)))
    for field in FILE_FIELDS:
        if field not in descriptor:
            _add(errors, "missing_file_field", "%s.%s" % (where, field))
        elif not _is_text(descriptor[field], _FILE_LIMITS[field]):
            _add(errors, "invalid_file_" + field, "%s.%s" % (where, field))


def _check_files(errors, value):
    if type(value) is not list:
        _add(errors, "invalid_files", "files")
    elif len(value) > MAX_FILES:
        _add(errors, ERR_TOO_MANY_ITEMS, "files")
    else:
        for index, descriptor in enumerate(value):
            _check_file(errors, index, descriptor)


def _errors(data, not_dict_code, missing_code):
    """Errors of a dict that must hold all eight fields."""
    errors = []
    if type(data) is not dict:
        _add(errors, missing_code if data is None else not_dict_code,
             "source" if missing_code == ERR_MISSING_SOURCE else "state")
        return errors
    if len(data) > MAX_FIELDS:
        _add(errors, ERR_TOO_MANY_FIELDS, "state")
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
            if type(value) is not str or value != STATE_VERSION:
                _add(errors, "invalid_version", field)
        elif field in _TEXT_LIMITS:
            if not _is_text(value, _TEXT_LIMITS[field]):
                _add(errors, "invalid_" + field, field)
        elif field == "files":
            _check_files(errors, value)
        elif field in _LIST_LIMITS:
            _check_text_list(errors, field, value)
        elif value is not False:
            _add(errors, "invalid_execution_allowed", field)
    return errors


def _validation(errors):
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}


def validate_project_state(project_state=None):
    """Validation result for a normalized project state."""
    try:
        return _validation(_errors(project_state, ERR_STATE_NOT_DICT, ERR_MISSING_STATE))
    except Exception:
        return _validation([{"code": ERR_INTERNAL, "where": "state"}])


def build_project_state(source=None):
    """Build a fresh normalized project state from `source`, or report errors."""
    try:
        data = source
        if type(source) is dict and len(source) <= MAX_FIELDS:
            data = dict(source)
            for field in FIELDS:
                if field in _BUILD_REQUIRED:
                    continue
                data.setdefault(field, STATE_VERSION if field == "version" else False)
        errors = _errors(data, ERR_SOURCE_NOT_DICT, ERR_MISSING_SOURCE)
        project_state = None
        if not errors:
            project_state = {
                "version": data["version"], "project_id": data["project_id"],
                "revision": data["revision"],
                "files": [{"path": d["path"], "kind": d["kind"], "status": d["status"]}
                          for d in data["files"]],
                "capabilities": list(data["capabilities"]),
                "tests": list(data["tests"]),
                "constraints": list(data["constraints"]),
                "execution_allowed": False}
        return {"valid": not errors, "errors": errors, "project_state": project_state,
                "execution_allowed": False, "executed": False}
    except Exception:
        return {"valid": False, "errors": [{"code": ERR_INTERNAL, "where": "state"}],
                "project_state": None, "execution_allowed": False, "executed": False}
