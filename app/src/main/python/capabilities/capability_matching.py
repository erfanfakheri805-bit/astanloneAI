"""
Capability discovery and matching foundation (Prompt 845, Section 13 - Capability System)
=========================================================================================
ONE read-only function that looks for a capability in an EXPLICITLY SUPPLIED
`CapabilityRegistry` (Prompt 841) and reports, deterministically, whether an
exact, valid match exists. It adds no rules of its own: descriptor structure
and validity come from Prompt 844 (`validate_capability`, which composes
Prompt 841), version ordering from Prompt 842 (`compare_capability_versions`,
`parse_capability_version`, `build_capability_identity`). Nothing is
registered, replaced, enabled, disabled, executed or mutated, and nothing is
invented, normalised, guessed or inferred.

  match_capability(requirement, registry) -> matching result

Requirement (a plain dict; only these keys, nothing else is accepted):

  {"name", "minimum_version", "required_inputs", "expected_outputs"}

  name              REQUIRED. A capability identity name (the Prompt 841 name
                    rule). Compared with registered names by exact string
                    equality only: no trimming, case folding, prefix,
                    substring, alias, fuzzy or semantic matching.
  minimum_version   optional exact int 1..MAX_VERSION (Prompt 842 rule). The
                    candidate version must be equal or newer.
  required_inputs   optional list (<= MAX_ITEMS) of unique identifiers. Every
                    one must be among the candidate's declared `inputs`
                    (exact identifiers; the candidate may declare more).
  expected_outputs  optional list (<= MAX_ITEMS) of unique identifiers. Every
                    one must be among the candidate's declared `outputs`.

  An omitted key and an empty list both mean "no such requirement". An
  explicit None is malformed. Capabilities are never inferred from inputs or
  outputs: only the exact name selects candidates.

Discovery: only the supplied registry is read (never a global one). Scanning
is bounded to MAX_SCAN entries in name order (code point order). A candidate
is a registry entry whose key or descriptor name equals the requirement name.
The `enabled` descriptor flag is NOT a matching criterion and is never
inferred from or changed; it is simply part of the returned descriptor.

Result (always these keys, in this order, JSON-safe, fresh on every call):

  {"status", "matched", "candidate_count", "matches", "rejected", "truncated",
   "execution_allowed", "executed"}

  status           "matched"              at least one valid match
                   "no_match"             no candidate has that exact name
                   "no_valid_match"       candidates exist but all were rejected
                   "invalid_requirement"  the requirement is malformed
                   "invalid_registry"     the registry is not a usable
                                          CapabilityRegistry
                   "matching_error"       unexpected internal failure
  matched          True only for status "matched"
  candidate_count  candidates found among the scanned entries
  matches          at most MAX_MATCHES of
                   {"identity": {"name"}, "version", "descriptor"} where
                   `descriptor` is a fresh copy of the explicitly registered
                   descriptor and identity/version come from Prompt 842
  rejected         at most MAX_REJECTED of
                   {"subject", "name", "version", "reasons"}; subject is
                   "candidate", "requirement" or "registry"; reasons are
                   [{"code", "where"}] (at most MAX_ERRORS): the Prompt 844
                   validation errors, "registry_key_mismatch"/"registry",
                   "descriptor_name_mismatch"/"name",
                   "version_below_minimum"/"minimum_version",
                   "required_input_missing"/"required_inputs[i]",
                   "expected_output_missing"/"expected_outputs[i]", or the
                   requirement / registry problems (invalid_name, ...)
  truncated        True when the scan bound was reached or any bounded list
                   (matches, rejected, reasons) was cut
  execution_allowed, executed
                   always False; a match never implies that the capability
                   can or will execute

Bounded work, read-only (inputs and the registry are never modified or kept),
deterministic, never raises. Pure Python plus the Prompt 841-844 modules; no
Core, Memory, AEL, NLU, reasoning, execution, LLM, network or filesystem.
"""

import copy
import itertools

from .capability_registry import (
    MAX_CAPABILITIES, MAX_ERRORS, MAX_ITEMS, MAX_NAME_LENGTH, MAX_VERSION,
    CapabilityRegistry, _is_identifier, _where,
)
from .capability_identity import (
    REL_OLDER, build_capability_identity, compare_capability_versions,
    parse_capability_version,
)
from .capability_validation import validate_capability

MATCHING_VERSION = 1

MAX_SCAN = MAX_CAPABILITIES
MAX_MATCHES = 16
MAX_REJECTED = 16

STATUS_MATCHED = "matched"
STATUS_NO_MATCH = "no_match"
STATUS_NO_VALID_MATCH = "no_valid_match"
STATUS_INVALID_REQUIREMENT = "invalid_requirement"
STATUS_INVALID_REGISTRY = "invalid_registry"
STATUS_ERROR = "matching_error"
STATUSES = (STATUS_MATCHED, STATUS_NO_MATCH, STATUS_NO_VALID_MATCH,
            STATUS_INVALID_REQUIREMENT, STATUS_INVALID_REGISTRY, STATUS_ERROR)

SUBJECT_CANDIDATE = "candidate"
SUBJECT_REQUIREMENT = "requirement"
SUBJECT_REGISTRY = "registry"

REQUIREMENT_FIELDS = ("name", "minimum_version", "required_inputs", "expected_outputs")

ERR_REQUIREMENT_NOT_DICT = "requirement_not_dict"
ERR_MISSING_FIELD = "missing_field"
ERR_UNEXPECTED_FIELD = "unexpected_field"
ERR_INVALID_NAME = "invalid_name"
ERR_INVALID_REQUIRED_INPUTS = "invalid_required_inputs"
ERR_INVALID_EXPECTED_OUTPUTS = "invalid_expected_outputs"
ERR_TOO_MANY_ITEMS = "too_many_items"
ERR_INVALID_ITEM = "invalid_item"
ERR_DUPLICATE_ITEM = "duplicate_item"
ERR_REGISTRY_NOT_REGISTRY = "registry_not_capability_registry"
ERR_REGISTRY_ENTRIES = "registry_entries_invalid"
ERR_KEY_MISMATCH = "registry_key_mismatch"
ERR_NAME_MISMATCH = "descriptor_name_mismatch"
ERR_VERSION_BELOW = "version_below_minimum"
ERR_INPUT_MISSING = "required_input_missing"
ERR_OUTPUT_MISSING = "expected_output_missing"
ERR_CANDIDATE = "candidate_error"
ERR_MATCHING = "matching_error"


class _Reasons:
    """Bounded, de-duplicated list of {"code", "where"} items."""

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


def _result(status, candidate_count=0, matches=None, rejected=None, truncated=False):
    return {"status": status, "matched": status == STATUS_MATCHED,
            "candidate_count": candidate_count,
            "matches": matches if matches is not None else [],
            "rejected": rejected if rejected is not None else [],
            "truncated": truncated, "execution_allowed": False, "executed": False}


def _rejection(subject, name, version, reasons):
    return {"subject": subject, "name": name, "version": version,
            "reasons": list(reasons.items)}


# ------------------------------------------------------------ requirement

def _check_identifier_list(reasons, field, value, bad_code):
    """Validate an optional list of unique identifiers; returns the checked
    list (possibly empty) or None when it is malformed."""
    if type(value) is not list:
        reasons.add(bad_code, field)
        return None
    ok = True
    if len(value) > MAX_ITEMS:
        reasons.add(ERR_TOO_MANY_ITEMS, field)
        ok = False
    seen = set()
    for index, item in enumerate(value[:MAX_ITEMS]):
        where = "%s[%d]" % (field, index)
        if not _is_identifier(item, MAX_NAME_LENGTH):
            reasons.add(ERR_INVALID_ITEM, where)
            ok = False
        elif item in seen:
            reasons.add(ERR_DUPLICATE_ITEM, where)
            ok = False
        else:
            seen.add(item)
    return list(value) if ok else None


def _parse_requirement(requirement):
    """Returns (parsed, reasons); parsed is None when the requirement is
    malformed. parsed = (name, minimum_version|None, inputs, outputs)."""
    reasons = _Reasons()
    if type(requirement) is not dict:
        reasons.add(ERR_REQUIREMENT_NOT_DICT, "requirement")
        return None, reasons
    if "name" not in requirement:
        reasons.add(ERR_MISSING_FIELD, "name")
    for key in itertools.islice(requirement, len(REQUIREMENT_FIELDS) + 1):
        if key not in REQUIREMENT_FIELDS:
            reasons.add(ERR_UNEXPECTED_FIELD, _where(key))
    name = requirement.get("name")
    if "name" in requirement and not _is_identifier(name, MAX_NAME_LENGTH):
        reasons.add(ERR_INVALID_NAME, "name")

    minimum = None
    if "minimum_version" in requirement:
        parsed = parse_capability_version(requirement["minimum_version"])
        if parsed["valid"]:
            minimum = parsed["number"]
        else:
            for item in parsed["errors"]:
                reasons.add(item["code"], "minimum_version")
    inputs, outputs = [], []
    if "required_inputs" in requirement:
        inputs = _check_identifier_list(reasons, "required_inputs",
                                        requirement["required_inputs"],
                                        ERR_INVALID_REQUIRED_INPUTS)
    if "expected_outputs" in requirement:
        outputs = _check_identifier_list(reasons, "expected_outputs",
                                         requirement["expected_outputs"],
                                         ERR_INVALID_EXPECTED_OUTPUTS)
    if reasons.items:
        return None, reasons
    return (name, minimum, inputs, outputs), reasons


# --------------------------------------------------------------- matching

def _is_candidate(key, entry, name):
    if type(key) is str and key == name:
        return True
    if type(entry) is dict:
        entry_name = entry.get("name")
        return type(entry_name) is str and entry_name == name
    return False


def _evaluate(key, entry, parsed):
    """Reasons a candidate is rejected (empty list items = valid match)."""
    name, minimum, inputs, outputs = parsed
    reasons = _Reasons()
    if not (type(key) is str and key == name):
        reasons.add(ERR_KEY_MISMATCH, "registry")
    validation = validate_capability(entry)
    for item in validation["errors"]:
        reasons.add(item["code"], item["where"])
    if validation["truncated"]:
        reasons.truncated = True
    if not validation["valid"]:
        return reasons, None
    if entry["name"] != name:
        reasons.add(ERR_NAME_MISMATCH, "name")
    if minimum is not None:
        relation = compare_capability_versions(entry["version"], minimum)["relation"]
        if relation == REL_OLDER:
            reasons.add(ERR_VERSION_BELOW, "minimum_version")
    for index, item in enumerate(inputs):
        if item not in entry["inputs"]:
            reasons.add(ERR_INPUT_MISSING, "required_inputs[%d]" % index)
    for index, item in enumerate(outputs):
        if item not in entry["outputs"]:
            reasons.add(ERR_OUTPUT_MISSING, "expected_outputs[%d]" % index)
    return reasons, entry["version"]


def _match_entry(entry):
    identity = build_capability_identity(entry)
    return {"identity": dict(identity["identity"]), "version": entry["version"],
            "descriptor": copy.deepcopy(entry)}


def match_capability(requirement=None, registry=None):
    """Find exact, valid matches for `requirement` in `registry`."""
    try:
        parsed, req_reasons = _parse_requirement(requirement)
        if parsed is None:
            return _result(STATUS_INVALID_REQUIREMENT,
                           rejected=[_rejection(SUBJECT_REQUIREMENT, None, None, req_reasons)],
                           truncated=req_reasons.truncated)

        entries = getattr(registry, "_entries", None) if type(registry) is CapabilityRegistry else None
        if type(entries) is not dict:
            reg_reasons = _Reasons()
            reg_reasons.add(ERR_REGISTRY_NOT_REGISTRY if type(registry) is not CapabilityRegistry
                            else ERR_REGISTRY_ENTRIES, "registry")
            return _result(STATUS_INVALID_REGISTRY,
                           rejected=[_rejection(SUBJECT_REGISTRY, None, None, reg_reasons)])

        name = parsed[0]
        scanned = list(itertools.islice(entries.items(), MAX_SCAN + 1))
        truncated = len(scanned) > MAX_SCAN
        scanned = scanned[:MAX_SCAN]
        scanned.sort(key=lambda kv: (type(kv[0]) is not str, kv[0] if type(kv[0]) is str else ""))

        candidate_count = 0
        matches, rejected = [], []
        for key, entry in scanned:
            if not _is_candidate(key, entry, name):
                continue
            candidate_count += 1
            try:
                reasons, version = _evaluate(key, entry, parsed)
                if reasons.items:
                    item = _rejection(SUBJECT_CANDIDATE, name, version, reasons)
                    wrapped = len(rejected) < MAX_REJECTED
                    if wrapped:
                        rejected.append(item)
                    else:
                        truncated = True
                else:
                    if len(matches) < MAX_MATCHES:
                        matches.append(_match_entry(entry))
                    else:
                        truncated = True
                if reasons.truncated:
                    truncated = True
            except Exception:
                broken = _Reasons()
                broken.add(ERR_CANDIDATE, "registry")
                if len(rejected) < MAX_REJECTED:
                    rejected.append(_rejection(SUBJECT_CANDIDATE, name, None, broken))
                else:
                    truncated = True

        if matches:
            status = STATUS_MATCHED
        elif candidate_count == 0:
            status = STATUS_NO_MATCH
        else:
            status = STATUS_NO_VALID_MATCH
        return _result(status, candidate_count, matches, rejected, truncated)
    except Exception:
        broken = _Reasons()
        broken.add(ERR_MATCHING, "matching")
        return _result(STATUS_ERROR, rejected=[_rejection(SUBJECT_REQUIREMENT, None, None, broken)])
