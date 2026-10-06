"""
Approval Authority Scope Boundary (Prompt 899, Section 17: Controlled Autonomy)
===============================================================================
A deterministic, read-only, DESCRIPTIVE contract. Given a valid Prompt 898 approval authority
descriptor it describes the BOUNDARY of what that authority source could one day be asked to
approve: one authority, one capability, one operation. The scope is a boundary, not a grant.

Nothing here approves, authorizes, permits implementation or execution, generates code,
modifies anything, persists anything, starts a subprocess, touches the filesystem or the
network, uses an external AI / API, authenticates anyone, or acts automatically. There is no
"approved" status, no approval field and no permission state: implementation_allowed and
execution_allowed are ALWAYS False. A valid scope is only a well-formed description.

  build_approval_authority_scope(authority_descriptor, scope_id, capability_name, operation,
        scope, purpose, approval_capable=None, implementation_allowed=False,
        execution_allowed=False, authority_id=None)
  validate_approval_authority_scope(scope_descriptor)
  validate_approval_authority_scope_context(authority_descriptor, scope_descriptor)

Scope descriptor (exactly these ten keys, a fresh dict on every call, primitive values only):
  {"version", "scope_id", "authority_id", "capability_name", "operation", "scope", "purpose",
   "approval_capable", "implementation_allowed", "execution_allowed"}

  version              the integer 1
  scope_id             plain snake_case label (the Prompt 898 convention), 1-64 chars
  authority_id         label of the ONE authority this scope is tied to
  capability_name      label of the ONE capability this scope is tied to
  operation            exactly "create" or "improve" ("improve_or_conflict" is not supported)
  scope, purpose       labels describing the boundary (no wildcard scope such as "all")
  approval_capable     bool, copied from the trusted Prompt 898 descriptor
  implementation_allowed, execution_allowed
                       bool, and MUST be False. True is rejected (forbidden_permission)

Every label (scope_id, authority_id, capability_name, scope, purpose) is judged by the Prompt
898 validator itself, so the exact same rules apply (lower-case snake_case, no URL / command /
code / key / credential / approval-word segment, no wildcard for scope and capability_name).
Nothing is re-implemented here.

Checks run in a fixed order; the first failing group decides the status:
 context validation only:
   0 authority descriptor fails the Prompt 898 validator ..................... invalid_authority
     (it fails only because of an approval / status concept) ................. unsupported_status
 structural checks (also run alone by validate_approval_authority_scope):
   1 not a dict; missing / unexpected / non-str key; wrong version;
     authority_id not a valid label ........................................... invalid_authority
     (an unexpected key naming an approval / status concept: "approved",
      "authorization", "status", "granted" ... ................................ unsupported_status)
   2 scope_id not a valid label ............................................... invalid_scope_id
   3 capability_name not a valid label ........................................ invalid_capability
   4 operation not "create" / "improve" ....................................... invalid_operation
     (operation "improve_or_conflict" or an approval / status word) ........... unsupported_status
   5 scope or purpose not a valid label; any of the three flags not a real bool invalid_scope
   6 implementation_allowed or execution_allowed is True ...................... forbidden_permission
 context validation only:
   7 authority_id differs from the Prompt 898 descriptor's, or approval_capable
     differs from the Prompt 898 descriptor's .................................. context_mismatch
   8 everything holds ......................................................... valid
Any unexpected internal failure -> validation_error. The vocabulary is exactly: valid,
invalid_authority, invalid_scope, invalid_scope_id, invalid_capability, invalid_operation,
context_mismatch, forbidden_permission, unsupported_status, validation_error. None of them
grants approval, authorization, permission or execution.

validate_approval_authority_scope(scope_descriptor) is purely structural (checks 1-6) and does
not know the authority; only validate_approval_authority_scope_context also checks the
descriptor against the authority (checks 0-8). Both return a fresh
  {"status", "valid", "errors", "execution_allowed", "executed"}
valid is True only for "valid"; execution_allowed and executed are always False; errors is a
list of {"code", "where"} (at most MAX_ERRORS).

build_approval_authority_scope(...) copies authority_id and (when approval_capable is None)
approval_capable from the authority descriptor, validates the candidate with the context
validation and returns
  {"status", "scope_descriptor", "execution_allowed", "executed"}
scope_descriptor is the fresh valid descriptor only for "valid" and is None otherwise, so a
rejected request never yields a permission-bearing (or any) result. Inputs are never modified
and are never shared with the result.
"""

from capabilities.capability_registry import MAX_ERRORS

from .approval_authority_source import AUTHORITY_TYPES, validate_approval_authority_source

SCOPE_VERSION = 1

STATUS_VALID = "valid"
STATUS_INVALID_AUTHORITY = "invalid_authority"
STATUS_INVALID_SCOPE = "invalid_scope"
STATUS_INVALID_SCOPE_ID = "invalid_scope_id"
STATUS_INVALID_CAPABILITY = "invalid_capability"
STATUS_INVALID_OPERATION = "invalid_operation"
STATUS_CONTEXT = "context_mismatch"
STATUS_FORBIDDEN_PERMISSION = "forbidden_permission"
STATUS_UNSUPPORTED_STATUS = "unsupported_status"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_VALID, STATUS_INVALID_AUTHORITY, STATUS_INVALID_SCOPE,
            STATUS_INVALID_SCOPE_ID, STATUS_INVALID_CAPABILITY, STATUS_INVALID_OPERATION,
            STATUS_CONTEXT, STATUS_FORBIDDEN_PERMISSION, STATUS_UNSUPPORTED_STATUS,
            STATUS_ERROR)

SCOPE_KEYS = ("version", "scope_id", "authority_id", "capability_name", "operation", "scope",
              "purpose", "approval_capable", "implementation_allowed", "execution_allowed")
SUPPORTED_OPERATIONS = ("create", "improve")
BOOL_FLAGS = ("approval_capable", "implementation_allowed", "execution_allowed")
PERMISSION_FLAGS = ("implementation_allowed", "execution_allowed")

# Approval / status concepts. They are not scope fields and not operations.
_APPROVAL_WORDS = frozenset((
    "approved", "approval", "approval_status", "approved_by", "authorization", "authorisation",
    "authorized", "authorised", "granted", "allowed", "permitted", "permission", "status",
    "pending_approval"))
_UNSUPPORTED_OPERATIONS = frozenset(("improve_or_conflict",))

ERR_NOT_DICT = "scope_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_APPROVAL_CONCEPT = "approval_concept"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_AUTHORITY_ID = "invalid_authority_id"
ERR_INVALID_SCOPE_ID = "invalid_scope_id"
ERR_INVALID_CAPABILITY = "invalid_capability_name"
ERR_INVALID_OPERATION = "invalid_operation"
ERR_UNSUPPORTED_OPERATION = "unsupported_operation"
ERR_INVALID_SCOPE = "invalid_scope"
ERR_INVALID_PURPOSE = "invalid_purpose"
ERR_INVALID_FLAG = "invalid_flag"
ERR_FORBIDDEN_PERMISSION = "forbidden_permission"
ERR_INVALID_AUTHORITY = "invalid_authority_descriptor"
ERR_MISMATCH = "context_mismatch"
ERR_INTERNAL = "validation_error"


def _label_ok(value, slot):
    """Judge a label with the Prompt 898 validator, placed in the descriptor field `slot`.

    slot "authority_id" = plain label, "scope" = label without a wildcard,
    "purpose" = plain label. The rest of the probe descriptor is fixed and valid.
    """
    probe = {"version": 1, "authority_id": "label_check", "authority_type": AUTHORITY_TYPES[0],
             "scope": "label_check", "purpose": "label_check", "trusted": False,
             "approval_capable": False, "implementation_allowed": False,
             "execution_allowed": False}
    probe[slot] = value
    return validate_approval_authority_source(probe)["status"] == "valid"


def _approval_word(value):
    return type(value) is str and value.strip().lower() in _APPROVAL_WORDS


def _result(status, errors=None):
    return {"status": status, "valid": status == STATUS_VALID,
            "errors": list(errors) if errors else [],
            "execution_allowed": False, "executed": False}


def _structure(scope):
    """(status, errors) for the structural checks 1-6; the first failing group decides."""
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(scope) is not dict:
        add(ERR_NOT_DICT, "scope")
        return STATUS_INVALID_AUTHORITY, errors

    concept = False
    for key in SCOPE_KEYS:
        if key not in scope:
            add(ERR_MISSING_KEY, key)
    for key in scope:
        if type(key) is not str or key not in SCOPE_KEYS:
            if _approval_word(key):
                concept = True
                add(ERR_APPROVAL_CONCEPT, key.strip().lower()[:40])
            else:
                add(ERR_UNEXPECTED_KEY,
                    key if type(key) is str and 0 < len(key) <= 40 else "<key>")
    if concept:
        return STATUS_UNSUPPORTED_STATUS, errors
    if errors:
        return STATUS_INVALID_AUTHORITY, errors

    if type(scope["version"]) is not int or scope["version"] != SCOPE_VERSION:
        add(ERR_INVALID_VERSION, "version")
        return STATUS_INVALID_AUTHORITY, errors
    if not _label_ok(scope["authority_id"], "authority_id"):
        add(ERR_INVALID_AUTHORITY_ID, "authority_id")
        return STATUS_INVALID_AUTHORITY, errors
    if not _label_ok(scope["scope_id"], "authority_id"):
        add(ERR_INVALID_SCOPE_ID, "scope_id")
        return STATUS_INVALID_SCOPE_ID, errors
    if not _label_ok(scope["capability_name"], "scope"):
        add(ERR_INVALID_CAPABILITY, "capability_name")
        return STATUS_INVALID_CAPABILITY, errors

    operation = scope["operation"]
    if type(operation) is not str or operation not in SUPPORTED_OPERATIONS:
        if type(operation) is str and (operation in _UNSUPPORTED_OPERATIONS
                                       or _approval_word(operation)):
            add(ERR_UNSUPPORTED_OPERATION, "operation")
            return STATUS_UNSUPPORTED_STATUS, errors
        add(ERR_INVALID_OPERATION, "operation")
        return STATUS_INVALID_OPERATION, errors

    if not _label_ok(scope["scope"], "scope"):
        add(ERR_INVALID_SCOPE, "scope")
    if not _label_ok(scope["purpose"], "purpose"):
        add(ERR_INVALID_PURPOSE, "purpose")
    for key in BOOL_FLAGS:
        if type(scope[key]) is not bool:
            add(ERR_INVALID_FLAG, key)
    if errors:
        return STATUS_INVALID_SCOPE, errors

    for key in PERMISSION_FLAGS:
        if scope[key] is not False:
            add(ERR_FORBIDDEN_PERMISSION, key)
    if errors:
        return STATUS_FORBIDDEN_PERMISSION, errors
    return STATUS_VALID, errors


def _context(authority, scope):
    """(status, errors) for context checks 0-8."""
    authority_check = validate_approval_authority_source(authority)
    if authority_check["status"] != "valid":
        if authority_check["status"] == "unsupported_status":
            status = STATUS_UNSUPPORTED_STATUS
        else:
            status = STATUS_INVALID_AUTHORITY
        return status, [{"code": ERR_INVALID_AUTHORITY, "where": "authority"}]

    status, errors = _structure(scope)
    if status != STATUS_VALID:
        return status, errors

    mismatches = []
    if scope["authority_id"] != authority["authority_id"]:
        mismatches.append({"code": ERR_MISMATCH, "where": "authority_id"})
    if scope["approval_capable"] is not authority["approval_capable"]:
        mismatches.append({"code": ERR_MISMATCH, "where": "approval_capable"})
    if mismatches:
        return STATUS_CONTEXT, mismatches
    return STATUS_VALID, []


def validate_approval_authority_scope(scope_descriptor=None):
    """Structural validation of a scope descriptor (read-only, no approval)."""
    try:
        status, errors = _structure(scope_descriptor)
        return _result(status, errors)
    except Exception:
        return _result(STATUS_ERROR, [{"code": ERR_INTERNAL, "where": "scope"}])


def validate_approval_authority_scope_context(authority_descriptor=None, scope_descriptor=None):
    """Validation of a scope descriptor against its Prompt 898 authority (read-only)."""
    try:
        status, errors = _context(authority_descriptor, scope_descriptor)
        return _result(status, errors)
    except Exception:
        return _result(STATUS_ERROR, [{"code": ERR_INTERNAL, "where": "scope"}])


def build_approval_authority_scope(authority_descriptor=None, scope_id=None,
                                   capability_name=None, operation=None, scope=None,
                                   purpose=None, approval_capable=None,
                                   implementation_allowed=False, execution_allowed=False,
                                   authority_id=None):
    """Scope descriptor for one authority / capability / operation (describes, grants nothing)."""
    try:
        authority_ok = (validate_approval_authority_source(authority_descriptor)["status"]
                        == "valid")
        candidate = {
            "version": SCOPE_VERSION, "scope_id": scope_id,
            "authority_id": (authority_descriptor["authority_id"]
                             if authority_id is None and authority_ok else authority_id),
            "capability_name": capability_name, "operation": operation, "scope": scope,
            "purpose": purpose,
            "approval_capable": (authority_descriptor["approval_capable"]
                                 if approval_capable is None and authority_ok
                                 else approval_capable),
            "implementation_allowed": implementation_allowed,
            "execution_allowed": execution_allowed}
        status, _errors = _context(authority_descriptor, candidate)
        return {"status": status,
                "scope_descriptor": candidate if status == STATUS_VALID else None,
                "execution_allowed": False, "executed": False}
    except Exception:
        return {"status": STATUS_ERROR, "scope_descriptor": None,
                "execution_allowed": False, "executed": False}
