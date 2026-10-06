"""
Capability Registry foundation (Prompt 841, Section 13 - Capability System)
===========================================================================
A small deterministic in-memory registry of EXPLICITLY DEFINED capability
descriptors. A descriptor only describes a capability; nothing is executed,
inferred, invented, loaded or connected.

  validate_capability_descriptor(descriptor) -> validation result
  CapabilityRegistry().register(descriptor)  -> registration result
  CapabilityRegistry().lookup(name)          -> lookup result
  CapabilityRegistry().list_capabilities()   -> listing result

Descriptor (exactly these keys, JSON-safe):

  {"name", "version", "purpose", "inputs", "outputs", "constraints", "enabled"}

  name         stable identity: lowercase snake_case, 1..MAX_NAME_LENGTH chars
               (never normalised, trimmed or derived)
  version      positive int (not bool), at most MAX_VERSION
  purpose      non-empty text, no surrounding whitespace, no control
               characters, at most MAX_TEXT_LENGTH chars
  inputs       list of unique snake_case identifiers (may be empty)
  outputs      list of unique snake_case identifiers (at least one)
  constraints  list of unique texts like `purpose` (may be empty), each at
               most MAX_CONSTRAINT_LENGTH chars
  enabled      bool (a descriptor flag only; it never runs anything)

Lists hold at most MAX_ITEMS entries. Anything else (a handler, tool,
callable, module path, code, url, ...) is an unexpected field and is
rejected, never stored. Only exact built-in types are accepted (dict, list,
str, int, bool); subclasses and other objects are malformed.

Registration (each descriptor is validated first; the registry is unchanged
unless the result is "registered"):

  rejected / malformed   the descriptor is not structurally valid
  rejected / duplicate   the same name is already registered with an
                         identical descriptor
  rejected / conflict    the same name is already registered with a
                         different descriptor (different version or content)
  rejected / full        MAX_CAPABILITIES are already registered
  registered             the descriptor was stored (as a private copy)

Identity is the exact name; there is no case folding or trimming. Existing
entries are never replaced, updated or removed.

Lookup is by exact name only (no prefix, case-insensitive or fuzzy match).
Listing is sorted by name (code point order), independent of registration
order. Every result is a fresh structure with fresh copies of descriptors, so
mutating a result, or the dict that was registered, never changes the
registry.

Result shapes (fixed key order, JSON-safe, `executed` always False):

  validation   {"version", "valid", "error_count", "errors", "truncated"}
               errors: [{"code", "where"}], at most MAX_ERRORS
  registration {"version", "status", "reason", "name", "errors", "executed"}
  lookup       {"version", "found", "reason", "descriptor", "executed"}
  listing      {"version", "count", "capabilities", "executed"}

Bounded work, read-only with respect to its inputs, deterministic, never
raises. Pure stdlib; no Core, Memory, AEL, NLU, reasoning, execution, LLM,
network, filesystem or global registry.
"""

import copy
import itertools
import re

REGISTRY_VERSION = 1

MAX_NAME_LENGTH = 64
MAX_TEXT_LENGTH = 200
MAX_CONSTRAINT_LENGTH = 120
MAX_ITEMS = 16
MAX_VERSION = 1000000
MAX_ERRORS = 16
MAX_FIELDS = 7
MAX_CAPABILITIES = 256

STATUS_REGISTERED = "registered"
STATUS_REJECTED = "rejected"

REASON_REGISTERED = "registered"
REASON_MALFORMED = "malformed"
REASON_DUPLICATE = "duplicate"
REASON_CONFLICT = "conflict"
REASON_FULL = "registry_full"
REASON_FOUND = "found"
REASON_NOT_FOUND = "not_found"
REASON_INVALID_NAME = "invalid_name"
REASON_REGISTRY_ERROR = "registry_error"

ERR_NOT_DICT = "descriptor_not_dict"
ERR_MISSING_FIELD = "missing_field"
ERR_UNEXPECTED_FIELD = "unexpected_field"
ERR_INVALID_NAME = "invalid_name"
ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_PURPOSE = "invalid_purpose"
ERR_INVALID_INPUTS = "invalid_inputs"
ERR_INVALID_OUTPUTS = "invalid_outputs"
ERR_INVALID_CONSTRAINTS = "invalid_constraints"
ERR_INVALID_ENABLED = "invalid_enabled"
ERR_NO_OUTPUTS = "no_outputs"
ERR_TOO_MANY_ITEMS = "too_many_items"
ERR_INVALID_ITEM = "invalid_item"
ERR_DUPLICATE_ITEM = "duplicate_item"
ERR_VALIDATOR = "validator_error"

DESCRIPTOR_FIELDS = ("name", "version", "purpose", "inputs", "outputs",
                     "constraints", "enabled")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


# ---------------------------------------------------------------- helpers

def _is_text(value, limit):
    """Exact non-empty str, no outer whitespace, no control chars, bounded."""
    if type(value) is not str or not value or len(value) > limit:
        return False
    if value != value.strip():
        return False
    return not any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _is_identifier(value, limit):
    return (type(value) is str and 0 < len(value) <= limit
            and _IDENTIFIER.match(value) is not None)


def _where(key):
    return key if type(key) is str and 0 < len(key) <= 40 else "<field>"


class _Errors:
    def __init__(self):
        self.items = []
        self._seen = set()
        self.truncated = False

    def add(self, code, where):
        if (code, where) in self._seen:
            return
        if len(self.items) >= MAX_ERRORS:
            self.truncated = True
            return
        self._seen.add((code, where))
        self.items.append({"code": code, "where": where})


def _check_items(errors, field, value, bad_code, limit, require_one=False,
                 identifiers=True):
    if type(value) is not list:
        errors.add(bad_code, field)
        return
    if len(value) > MAX_ITEMS:
        errors.add(ERR_TOO_MANY_ITEMS, field)
    if require_one and not value:
        errors.add(ERR_NO_OUTPUTS, field)
    seen = set()
    for index, item in enumerate(value[:MAX_ITEMS]):
        where = "%s[%d]" % (field, index)
        ok = _is_identifier(item, limit) if identifiers else _is_text(item, limit)
        if not ok:
            errors.add(ERR_INVALID_ITEM, where)
        elif item in seen:
            errors.add(ERR_DUPLICATE_ITEM, where)
        else:
            seen.add(item)


def _validation(errors):
    return {"version": REGISTRY_VERSION, "valid": not errors.items,
            "error_count": len(errors.items), "errors": errors.items,
            "truncated": errors.truncated}


# -------------------------------------------------------------- validator

def validate_capability_descriptor(descriptor):
    """Validation result for `descriptor` (see module docstring). Only reads
    the descriptor; never raises."""
    try:
        errors = _Errors()
        if type(descriptor) is not dict:
            errors.add(ERR_NOT_DICT, "descriptor")
            return _validation(errors)

        for field in DESCRIPTOR_FIELDS:
            if field not in descriptor:
                errors.add(ERR_MISSING_FIELD, field)
        for key in itertools.islice(descriptor, MAX_FIELDS + 1):
            if key not in DESCRIPTOR_FIELDS:
                errors.add(ERR_UNEXPECTED_FIELD, _where(key))

        if "name" in descriptor and not _is_identifier(descriptor["name"], MAX_NAME_LENGTH):
            errors.add(ERR_INVALID_NAME, "name")
        if "version" in descriptor:
            v = descriptor["version"]
            if type(v) is not int or not 1 <= v <= MAX_VERSION:
                errors.add(ERR_INVALID_VERSION, "version")
        if "purpose" in descriptor and not _is_text(descriptor["purpose"], MAX_TEXT_LENGTH):
            errors.add(ERR_INVALID_PURPOSE, "purpose")
        if "inputs" in descriptor:
            _check_items(errors, "inputs", descriptor["inputs"], ERR_INVALID_INPUTS,
                         MAX_NAME_LENGTH)
        if "outputs" in descriptor:
            _check_items(errors, "outputs", descriptor["outputs"], ERR_INVALID_OUTPUTS,
                         MAX_NAME_LENGTH, require_one=True)
        if "constraints" in descriptor:
            _check_items(errors, "constraints", descriptor["constraints"],
                         ERR_INVALID_CONSTRAINTS, MAX_CONSTRAINT_LENGTH, identifiers=False)
        if "enabled" in descriptor and type(descriptor["enabled"]) is not bool:
            errors.add(ERR_INVALID_ENABLED, "enabled")
        return _validation(errors)
    except Exception:
        errors = _Errors()
        errors.add(ERR_VALIDATOR, "descriptor")
        return _validation(errors)


def _private_copy(descriptor):
    """Fixed-order copy of a validated descriptor (plain built-in types)."""
    return {
        "name": descriptor["name"],
        "version": descriptor["version"],
        "purpose": descriptor["purpose"],
        "inputs": list(descriptor["inputs"]),
        "outputs": list(descriptor["outputs"]),
        "constraints": list(descriptor["constraints"]),
        "enabled": descriptor["enabled"],
    }


def _registration(status, reason, name, errors=None):
    return {"version": REGISTRY_VERSION, "status": status, "reason": reason,
            "name": name, "errors": errors if errors is not None else [],
            "executed": False}


def _lookup(found, reason, descriptor):
    return {"version": REGISTRY_VERSION, "found": found, "reason": reason,
            "descriptor": descriptor, "executed": False}


# --------------------------------------------------------------- registry

class CapabilityRegistry:
    """In-memory registry of explicitly defined capability descriptors.

    Each instance is independent (no global state). Entries can only be added;
    they are never replaced, updated or removed. Descriptors are stored as
    private copies and always returned as fresh copies."""

    def __init__(self):
        self._entries = {}

    def __len__(self):
        return len(self._entries)

    def register(self, descriptor):
        """Register one valid descriptor; returns a registration result."""
        try:
            validation = validate_capability_descriptor(descriptor)
            if not validation["valid"]:
                name = descriptor.get("name") if type(descriptor) is dict else None
                name = name if _is_identifier(name, MAX_NAME_LENGTH) else None
                return _registration(STATUS_REJECTED, REASON_MALFORMED, name,
                                     validation["errors"])
            candidate = _private_copy(descriptor)
            name = candidate["name"]
            existing = self._entries.get(name)
            if existing is not None:
                reason = REASON_DUPLICATE if existing == candidate else REASON_CONFLICT
                return _registration(STATUS_REJECTED, reason, name)
            if len(self._entries) >= MAX_CAPABILITIES:
                return _registration(STATUS_REJECTED, REASON_FULL, name)
            self._entries[name] = candidate
            return _registration(STATUS_REGISTERED, REASON_REGISTERED, name)
        except Exception:
            return _registration(STATUS_REJECTED, REASON_REGISTRY_ERROR, None)

    def lookup(self, name):
        """Exact-name lookup; returns a lookup result with a fresh copy."""
        try:
            if not _is_identifier(name, MAX_NAME_LENGTH):
                return _lookup(False, REASON_INVALID_NAME, None)
            entry = self._entries.get(name)
            if entry is None:
                return _lookup(False, REASON_NOT_FOUND, None)
            return _lookup(True, REASON_FOUND, copy.deepcopy(entry))
        except Exception:
            return _lookup(False, REASON_REGISTRY_ERROR, None)

    def list_capabilities(self):
        """All descriptors sorted by name; fresh copies."""
        try:
            items = [copy.deepcopy(self._entries[name]) for name in sorted(self._entries)]
            return {"version": REGISTRY_VERSION, "count": len(items),
                    "capabilities": items, "executed": False}
        except Exception:
            return {"version": REGISTRY_VERSION, "count": 0,
                    "capabilities": [], "executed": False}
