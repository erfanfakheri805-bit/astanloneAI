"""
Approval Authority Source Contract (Prompt 898, Section 17: Controlled Autonomy)
================================================================================
A deterministic, read-only, DESCRIPTIVE contract. It describes WHAT KIND of authority could
provide a future approval for a controlled-implementation flow. It is not an approval.

Describing an authority that is capable of approving is not the same as approving. Nothing
here approves, authorizes, permits implementation or execution, generates code, modifies
anything, persists anything, starts a subprocess, touches the filesystem or the network, uses
an external AI / API, or acts automatically. There is no "approved" status, no approval field
and no permission state: implementation_allowed and execution_allowed are ALWAYS False.

  build_approval_authority_source(authority_id, authority_type, scope, purpose, trusted,
        approval_capable, implementation_allowed=False, execution_allowed=False)
  validate_approval_authority_source(descriptor)

Descriptor (exactly these nine keys, a fresh dict on every call, primitive values only):
  {"version", "authority_id", "authority_type", "scope", "purpose", "trusted",
   "approval_capable", "implementation_allowed", "execution_allowed"}

  version              the integer 1
  authority_id         lower-case snake_case label, 1-64 chars (a-z, 0-9, "_"), starts with a
                       letter. A label only: never a URL, command, code, key or callable
  authority_type       exactly one of "user", "system_policy", "trusted_internal_controller"
  scope, purpose       snake_case labels of the same shape (no wildcard scope such as "all")
  trusted              bool: whether the source is trusted BY POLICY (a description only)
  approval_capable     bool: whether the source is conceptually capable of issuing approval
                       (a description only; it does not issue anything)
  implementation_allowed, execution_allowed
                       bool, and MUST be False. True is rejected (forbidden_permission)

trusted and approval_capable are independent descriptive flags. Neither confers any permission
and neither is checked against any real user, account, Android permission, UI, storage or
service: this module is connected to no external authority.

Validation result (fresh dict):
  {"status", "valid", "errors", "execution_allowed", "executed"}
valid is True only for status "valid"; execution_allowed and executed are always False.
errors is a list of {"code", "where"} (at most MAX_ERRORS). Checks run in a fixed order and
the first failing group decides the status:
   1 not a dict; missing key; unexpected key; non-str key; wrong version ..... invalid_authority
     (an unexpected key that names an approval / status concept, e.g. "approved", "status",
      "approval_status", "granted") ........................................... unsupported_status
   2 authority_id not a valid label ........................................... invalid_authority_id
   3 authority_type not a supported type ...................................... unsupported_authority_type
     (authority_type that is itself an approval / status word, e.g. "approved") unsupported_status
   4 scope not a valid label .................................................. invalid_scope
   5 purpose not a valid label ................................................ invalid_purpose
   6 any of the four flags not a real bool .................................... invalid_flags
   7 implementation_allowed or execution_allowed is True ...................... forbidden_permission
   8 everything holds ......................................................... valid
Any unexpected internal failure -> validation_error. The vocabulary is exactly: valid,
invalid_authority, invalid_authority_id, unsupported_authority_type, invalid_scope,
invalid_purpose, invalid_flags, forbidden_permission, unsupported_status, validation_error.

Labels that look executable or dynamic are rejected: a label may not contain a segment such as
http, url, endpoint, api, key, secret, token, password, credential, callback, lambda, exec,
eval, import, subprocess, shell, command, script, approved, granted, authorized or allowed.
Callables, objects, bytes, numbers and every other non-str value are rejected by type.

build_approval_authority_source(...) assembles the candidate, validates it and returns
  {"status", "descriptor", "execution_allowed", "executed"}
descriptor is the fresh valid descriptor only for status "valid"; it is None otherwise, so a
rejected request never yields a descriptor (and never a forged one). Inputs are never modified.
"""

import re

from capabilities.capability_registry import MAX_ERRORS

DESCRIPTOR_VERSION = 1

STATUS_VALID = "valid"
STATUS_INVALID_AUTHORITY = "invalid_authority"
STATUS_INVALID_AUTHORITY_ID = "invalid_authority_id"
STATUS_UNSUPPORTED_AUTHORITY_TYPE = "unsupported_authority_type"
STATUS_INVALID_SCOPE = "invalid_scope"
STATUS_INVALID_PURPOSE = "invalid_purpose"
STATUS_INVALID_FLAGS = "invalid_flags"
STATUS_FORBIDDEN_PERMISSION = "forbidden_permission"
STATUS_UNSUPPORTED_STATUS = "unsupported_status"
STATUS_ERROR = "validation_error"

STATUSES = (STATUS_VALID, STATUS_INVALID_AUTHORITY, STATUS_INVALID_AUTHORITY_ID,
            STATUS_UNSUPPORTED_AUTHORITY_TYPE, STATUS_INVALID_SCOPE, STATUS_INVALID_PURPOSE,
            STATUS_INVALID_FLAGS, STATUS_FORBIDDEN_PERMISSION, STATUS_UNSUPPORTED_STATUS,
            STATUS_ERROR)

AUTHORITY_TYPES = ("user", "system_policy", "trusted_internal_controller")

DESCRIPTOR_KEYS = ("version", "authority_id", "authority_type", "scope", "purpose", "trusted",
                   "approval_capable", "implementation_allowed", "execution_allowed")
DESCRIPTIVE_FLAGS = ("trusted", "approval_capable")
PERMISSION_FLAGS = ("implementation_allowed", "execution_allowed")
FLAGS = DESCRIPTIVE_FLAGS + PERMISSION_FLAGS

MAX_LABEL_LENGTH = 64
_LABEL = re.compile(r"[a-z][a-z0-9_]*")

# Approval / status concepts. They are not authority sources and not descriptor fields.
_APPROVAL_WORDS = frozenset((
    "approved", "approval", "approval_status", "approved_by", "granted", "authorized",
    "authorised", "allowed", "status", "permitted", "permission", "pending_approval"))

# Segments (split on "_") that make a label look executable, dynamic or credential-like.
_FORBIDDEN_SEGMENTS = frozenset((
    "http", "https", "ftp", "www", "url", "uri", "endpoint", "api", "apikey", "key", "secret",
    "token", "password", "credential", "callback", "lambda", "exec", "eval", "compile",
    "import", "subprocess", "shell", "cmd", "command", "script", "curl", "wget", "sudo",
    "approved", "granted", "authorized", "authorised", "allowed"))
_FORBIDDEN_SUBSTRINGS = ("http", "www", "apikey", "password", "secret", "lambda",
                         "subprocess", "credential")
_WILDCARD_SEGMENTS = frozenset(("all", "any", "global", "unrestricted", "wildcard", "everything"))

ERR_NOT_DICT = "descriptor_not_dict"
ERR_MISSING_KEY = "missing_key"
ERR_UNEXPECTED_KEY = "unexpected_key"
ERR_APPROVAL_CONCEPT = "approval_concept"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_AUTHORITY_ID = "invalid_authority_id"
ERR_INVALID_AUTHORITY_TYPE = "invalid_authority_type"
ERR_INVALID_SCOPE = "invalid_scope"
ERR_INVALID_PURPOSE = "invalid_purpose"
ERR_INVALID_FLAG = "invalid_flag"
ERR_FORBIDDEN_PERMISSION = "forbidden_permission"
ERR_INTERNAL = "validation_error"


def _label_ok(value, wildcard_allowed=True):
    """A plain snake_case label: a str of safe characters, not executable-looking."""
    if type(value) is not str or not 0 < len(value) <= MAX_LABEL_LENGTH:
        return False
    if _LABEL.fullmatch(value) is None:
        return False
    segments = value.split("_")
    if any(not segment for segment in segments):
        return False
    if any(segment in _FORBIDDEN_SEGMENTS for segment in segments):
        return False
    if any(text in value for text in _FORBIDDEN_SUBSTRINGS):
        return False
    if not wildcard_allowed and any(segment in _WILDCARD_SEGMENTS for segment in segments):
        return False
    return True


def _approval_word(value):
    return type(value) is str and value.strip().lower() in _APPROVAL_WORDS


def _result(status, errors=None):
    return {"status": status, "valid": status == STATUS_VALID,
            "errors": list(errors) if errors else [],
            "execution_allowed": False, "executed": False}


def _check(descriptor):
    """(status, errors) for a candidate descriptor; the first failing group decides."""
    errors = []

    def add(code, where):
        if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
            errors.append({"code": code, "where": where})

    if type(descriptor) is not dict:
        add(ERR_NOT_DICT, "descriptor")
        return STATUS_INVALID_AUTHORITY, errors

    concept = False
    for key in DESCRIPTOR_KEYS:
        if key not in descriptor:
            add(ERR_MISSING_KEY, key)
    for key in descriptor:
        if type(key) is not str or key not in DESCRIPTOR_KEYS:
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

    if type(descriptor["version"]) is not int or descriptor["version"] != DESCRIPTOR_VERSION:
        add(ERR_INVALID_VERSION, "version")
        return STATUS_INVALID_AUTHORITY, errors
    if not _label_ok(descriptor["authority_id"]):
        add(ERR_INVALID_AUTHORITY_ID, "authority_id")
        return STATUS_INVALID_AUTHORITY_ID, errors

    authority_type = descriptor["authority_type"]
    if type(authority_type) is not str or authority_type not in AUTHORITY_TYPES:
        if _approval_word(authority_type):
            add(ERR_APPROVAL_CONCEPT, "authority_type")
            return STATUS_UNSUPPORTED_STATUS, errors
        add(ERR_INVALID_AUTHORITY_TYPE, "authority_type")
        return STATUS_UNSUPPORTED_AUTHORITY_TYPE, errors

    if not _label_ok(descriptor["scope"], wildcard_allowed=False):
        add(ERR_INVALID_SCOPE, "scope")
        return STATUS_INVALID_SCOPE, errors
    if not _label_ok(descriptor["purpose"]):
        add(ERR_INVALID_PURPOSE, "purpose")
        return STATUS_INVALID_PURPOSE, errors

    for key in FLAGS:
        if type(descriptor[key]) is not bool:
            add(ERR_INVALID_FLAG, key)
    if errors:
        return STATUS_INVALID_FLAGS, errors
    for key in PERMISSION_FLAGS:
        if descriptor[key] is not False:
            add(ERR_FORBIDDEN_PERMISSION, key)
    if errors:
        return STATUS_FORBIDDEN_PERMISSION, errors
    return STATUS_VALID, errors


def validate_approval_authority_source(descriptor=None):
    """Validation result for an approval authority source descriptor (read-only, no approval)."""
    try:
        status, errors = _check(descriptor)
        return _result(status, errors)
    except Exception:
        return _result(STATUS_ERROR, [{"code": ERR_INTERNAL, "where": "descriptor"}])


def build_approval_authority_source(authority_id=None, authority_type=None, scope=None,
                                    purpose=None, trusted=None, approval_capable=None,
                                    implementation_allowed=False, execution_allowed=False):
    """Descriptor of an approval authority source (describes a kind of authority, grants nothing)."""
    try:
        candidate = {"version": DESCRIPTOR_VERSION, "authority_id": authority_id,
                     "authority_type": authority_type, "scope": scope, "purpose": purpose,
                     "trusted": trusted, "approval_capable": approval_capable,
                     "implementation_allowed": implementation_allowed,
                     "execution_allowed": execution_allowed}
        status, _errors = _check(candidate)
        descriptor = candidate if status == STATUS_VALID else None
        return {"status": status, "descriptor": descriptor,
                "execution_allowed": False, "executed": False}
    except Exception:
        return {"status": STATUS_ERROR, "descriptor": None,
                "execution_allowed": False, "executed": False}
