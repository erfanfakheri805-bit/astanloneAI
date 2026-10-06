"""
Capability identity and versioning (Prompt 842, Section 13 - Capability System)
===============================================================================
A small deterministic, read-only layer on top of the Prompt 841 capability
descriptor and registry. It describes and compares; it never registers,
replaces, upgrades, downgrades or executes anything, and it does not touch a
registry at all.

  parse_capability_version(value)                  -> version result
  compare_capability_versions(left, right)         -> comparison result
  build_capability_identity(descriptor)            -> identity result
  compare_capability_identities(left, right)       -> identity comparison
  classify_capability_descriptors(existing, candidate) -> classification

Version format (the existing descriptor `version` field, unchanged): an exact
`int` from 1 to MAX_VERSION. bool, int subclasses, floats, strings ("1",
"1.0", "v1"), None and out-of-range numbers are malformed: nothing is
coerced, parsed out of text or guessed. Versions are ordered numerically.

Identity: the exact capability `name` of a structurally valid descriptor
(Prompt 841 rules). The version, purpose, inputs, outputs, constraints and
enabled flag are NOT part of the identity. Names are compared by exact string
equality only: no trimming, case folding, normalisation, prefix or fuzzy
matching (names that would need it are simply invalid descriptors).

Classification of `candidate` relative to `existing` (both full descriptors):

  same_version        same identity, same version
  newer_version       same identity, candidate version is higher
  older_version       same identity, candidate version is lower
  different_identity  different names
  invalid             either descriptor is not a structurally valid
                      descriptor (nothing else is concluded)

`content_identical` is True/False for the three same-identity classes (is the
whole descriptor equal?) and None otherwise. The classification is advice
only: `executed` is always False, nothing is changed and no action follows
from it.

Result shapes (fixed key order, JSON-safe; `executed` always False; errors
are [{"code", "where"}], at most MAX_ERRORS, with `truncated`):

  version        {"version", "valid", "number", "errors", "truncated", "executed"}
  comparison     {"version", "valid", "relation", "left", "right", "errors",
                  "truncated", "executed"}
                 relation: "equal" / "newer" / "older" (left relative to right)
                 or None when invalid; left/right are the parsed numbers
  identity       {"version", "valid", "identity", "errors", "truncated", "executed"}
                 identity: {"name"} or None
  id comparison  {"version", "valid", "relation", "errors", "truncated", "executed"}
                 relation: "same" / "different" / None
  classification {"version", "classification", "identity_match",
                  "version_relation", "content_identical", "existing_name",
                  "candidate_name", "errors", "truncated", "executed"}

Bounded work (the Prompt 841 bounds apply), read-only with respect to its
inputs, deterministic, always fresh, never raises. Pure stdlib plus the
Prompt 841 module; no Core, Memory, AEL, NLU, reasoning, execution, LLM,
network or filesystem.
"""

from .capability_registry import (
    MAX_ERRORS, MAX_VERSION, validate_capability_descriptor,
)

IDENTITY_VERSION = 1

REL_EQUAL = "equal"
REL_NEWER = "newer"
REL_OLDER = "older"
ID_SAME = "same"
ID_DIFFERENT = "different"

CLASS_SAME_VERSION = "same_version"
CLASS_NEWER_VERSION = "newer_version"
CLASS_OLDER_VERSION = "older_version"
CLASS_DIFFERENT_IDENTITY = "different_identity"
CLASS_INVALID = "invalid"
CLASSIFICATIONS = (CLASS_SAME_VERSION, CLASS_NEWER_VERSION, CLASS_OLDER_VERSION,
                   CLASS_DIFFERENT_IDENTITY, CLASS_INVALID)

ERR_VERSION_TYPE = "invalid_version_type"
ERR_VERSION_RANGE = "version_out_of_range"
ERR_DESCRIPTOR_INVALID = "descriptor_invalid"
ERR_INTERNAL = "identity_error"


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


def _version_error(value):
    """Error code for a malformed version, or None when it is valid."""
    if type(value) is not int:
        return ERR_VERSION_TYPE
    if not 1 <= value <= MAX_VERSION:
        return ERR_VERSION_RANGE
    return None


def _prefixed(errors, side, validation):
    """Add the errors of a descriptor validation, located under `side`."""
    for item in validation["errors"]:
        errors.add(item["code"], "%s.%s" % (side, item["where"]))
    if validation["truncated"]:
        errors.truncated = True


# --------------------------------------------------------------- versions

def _version_result(valid, number, errors):
    return {"version": IDENTITY_VERSION, "valid": valid, "number": number,
            "errors": errors.items, "truncated": errors.truncated, "executed": False}


def parse_capability_version(value):
    """Validate one capability version; `number` is the version when valid."""
    try:
        errors = _Errors()
        code = _version_error(value)
        if code is not None:
            errors.add(code, "version")
            return _version_result(False, None, errors)
        return _version_result(True, value, errors)
    except Exception:
        errors = _Errors()
        errors.add(ERR_INTERNAL, "version")
        return _version_result(False, None, errors)


def _comparison_result(relation, left, right, errors):
    return {"version": IDENTITY_VERSION, "valid": relation is not None,
            "relation": relation, "left": left, "right": right,
            "errors": errors.items, "truncated": errors.truncated, "executed": False}


def compare_capability_versions(left, right):
    """Compare two versions: relation of `left` to `right`."""
    try:
        errors = _Errors()
        for side, value in (("left", left), ("right", right)):
            code = _version_error(value)
            if code is not None:
                errors.add(code, side)
        if errors.items:
            return _comparison_result(None, None, None, errors)
        if left == right:
            relation = REL_EQUAL
        elif left > right:
            relation = REL_NEWER
        else:
            relation = REL_OLDER
        return _comparison_result(relation, left, right, errors)
    except Exception:
        errors = _Errors()
        errors.add(ERR_INTERNAL, "versions")
        return _comparison_result(None, None, None, errors)


# -------------------------------------------------------------- identities

def _identity_result(identity, errors):
    return {"version": IDENTITY_VERSION, "valid": identity is not None,
            "identity": identity, "errors": errors.items,
            "truncated": errors.truncated, "executed": False}


def build_capability_identity(descriptor):
    """Identity `{"name": ...}` of a structurally valid descriptor."""
    try:
        errors = _Errors()
        validation = validate_capability_descriptor(descriptor)
        if not validation["valid"]:
            _prefixed(errors, "descriptor", validation)
            return _identity_result(None, errors)
        return _identity_result({"name": descriptor["name"]}, errors)
    except Exception:
        errors = _Errors()
        errors.add(ERR_INTERNAL, "descriptor")
        return _identity_result(None, errors)


def _id_comparison_result(relation, errors):
    return {"version": IDENTITY_VERSION, "valid": relation is not None,
            "relation": relation, "errors": errors.items,
            "truncated": errors.truncated, "executed": False}


def compare_capability_identities(left, right):
    """Compare the identities of two descriptors by exact name."""
    try:
        errors = _Errors()
        for side, descriptor in (("left", left), ("right", right)):
            validation = validate_capability_descriptor(descriptor)
            if not validation["valid"]:
                _prefixed(errors, side, validation)
        if errors.items:
            return _id_comparison_result(None, errors)
        relation = ID_SAME if left["name"] == right["name"] else ID_DIFFERENT
        return _id_comparison_result(relation, errors)
    except Exception:
        errors = _Errors()
        errors.add(ERR_INTERNAL, "descriptors")
        return _id_comparison_result(None, errors)


# ---------------------------------------------------------- classification

def _classification(classification, identity_match, version_relation, content_identical,
                    existing_name, candidate_name, errors):
    return {"version": IDENTITY_VERSION, "classification": classification,
            "identity_match": identity_match, "version_relation": version_relation,
            "content_identical": content_identical, "existing_name": existing_name,
            "candidate_name": candidate_name, "errors": errors.items,
            "truncated": errors.truncated, "executed": False}


def classify_capability_descriptors(existing, candidate):
    """Classify `candidate` relative to `existing` (see module docstring)."""
    try:
        errors = _Errors()
        for side, descriptor in (("existing", existing), ("candidate", candidate)):
            validation = validate_capability_descriptor(descriptor)
            if not validation["valid"]:
                _prefixed(errors, side, validation)
        if errors.items:
            return _classification(CLASS_INVALID, None, None, None, None, None, errors)

        existing_name, candidate_name = existing["name"], candidate["name"]
        if existing_name != candidate_name:
            return _classification(CLASS_DIFFERENT_IDENTITY, False, None, None,
                                   existing_name, candidate_name, errors)

        relation = compare_capability_versions(candidate["version"], existing["version"])["relation"]
        identical = all(existing[k] == candidate[k] for k in
                        ("version", "purpose", "inputs", "outputs", "constraints", "enabled"))
        label = {REL_EQUAL: CLASS_SAME_VERSION, REL_NEWER: CLASS_NEWER_VERSION,
                 REL_OLDER: CLASS_OLDER_VERSION}[relation]
        return _classification(label, True, relation, identical,
                               existing_name, candidate_name, errors)
    except Exception:
        errors = _Errors()
        errors.add(ERR_INTERNAL, "descriptors")
        return _classification(CLASS_INVALID, None, None, None, None, None, errors)
