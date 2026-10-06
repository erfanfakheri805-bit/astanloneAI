"""
Research Evidence Contract (Prompt 868, Section 15 - Autonomous Research & Learning)
====================================================================================
A strict, JSON-safe description of ONE piece of evidence that a future
controlled research step may record about an already-selected research source.
It is a data contract only: it retrieves, fetches, parses and synthesises
nothing, opens no file, accesses no URL or source, makes no network or API
request, invokes no external model, runs no command, learns nothing, and is not
connected to Core, Memory, AEL or any external service. `source_id` is only a
reference: the source is never looked up or inspected, and nothing about it is
checked beyond the id text. Nothing is inferred, generated, coerced, trimmed or
repaired: a missing or malformed value is an error, never replaced by a guess
(ids are never generated, confidence and evidence type are never inferred).

  build_research_evidence(evidence=None)    -> build result
  validate_research_evidence(evidence)      -> validation result

Same lightweight contract style as research/research_source.py (Prompt 864);
the shared bounds are reused from it.

Normalized research evidence (exactly these eight keys):

  {"version", "evidence_id", "source_id", "claim", "evidence_type",
   "confidence", "constraints", "execution_allowed"}

  version            exactly the string "1"
  evidence_id        text, <= MAX_ID_LENGTH
  source_id          text, <= MAX_ID_LENGTH (a reference to a Prompt 864 source;
                     same text rules as that contract's source_id)
  claim              text, <= MAX_CLAIM_LENGTH
  evidence_type      exactly one of EVIDENCE_TYPES: "fact", "observation",
                     "user_statement", "learned_record"
  confidence         an exact `float` or `int` (never bool, never a subclass,
                     never a string or other numeric type), finite and in the
                     inclusive range 0.0 to 1.0. The value is kept exactly as
                     given (0 stays 0, 1 stays 1); it is never converted.
  constraints        list of text, <= MAX_ITEMS items, each <= MAX_ITEM_LENGTH
                     (an empty list is a stated value; duplicates are kept)
  execution_allowed  exactly the bool False (evidence never allows execution)

  "text" follows the Prompt 841 / 849 / 864 convention: an exact `str` (no
  subclass), non-empty, no leading/trailing whitespace, no control
  characters, bounded. Enum values are compared exactly (case-sensitive).

build_research_evidence(evidence)
  `evidence` is an exact dict with the six required keys evidence_id,
  source_id, claim, evidence_type, confidence, constraints. `version` and
  `execution_allowed` are optional; when omitted they take their only legal
  values ("1" and False), when supplied they must already be exactly those
  values (execution_allowed=True is rejected, never ignored). Any other key is
  rejected. Missing keys are errors (nothing is defaulted or inferred). None is
  `missing_evidence`. Result (fixed keys, fresh on every call):
    {"valid", "errors", "evidence", "execution_allowed", "executed"}
  `evidence` is a fresh normalized copy (constraints list copied) when valid,
  else None. The result flags (not part of the evidence object) are always
  False, as in the other Section 15 build results.

validate_research_evidence(evidence)
  The same checks on an already normalized evidence object: all eight keys are
  required, no others. Result (fixed keys, fresh on every call):
    {"valid", "errors", "execution_allowed", "executed"}

errors: [{"code", "where"}], at most MAX_ERRORS, in a fixed order (evidence
shape, then fields in the order above). Codes: missing_evidence,
evidence_not_dict, too_many_fields, unexpected_field, missing_field,
invalid_version, invalid_evidence_id, invalid_source_id, invalid_claim,
invalid_evidence_type, invalid_confidence, invalid_constraints,
invalid_execution_allowed, too_many_items, invalid_item (where
"constraints[i]"), validation_error (unexpected internal failure).

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises. No filesystem, network, LLM, Core, Memory or AEL.
"""

from research.research_source import MAX_ID_LENGTH, MAX_ITEM_LENGTH, MAX_ITEMS

EVIDENCE_VERSION = "1"

EVIDENCE_TYPES = ("fact", "observation", "user_statement", "learned_record")

MAX_CLAIM_LENGTH = 500
MAX_ERRORS = 16
MAX_FIELDS = 16

FIELDS = ("version", "evidence_id", "source_id", "claim", "evidence_type", "confidence",
          "constraints", "execution_allowed")
_OPTIONAL = ("version", "execution_allowed")
_TEXT_LIMITS = {"evidence_id": MAX_ID_LENGTH, "source_id": MAX_ID_LENGTH,
                "claim": MAX_CLAIM_LENGTH}

ERR_MISSING_EVIDENCE = "missing_evidence"
ERR_NOT_DICT = "evidence_not_dict"
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


def _is_confidence(value):
    """Exact float/int (not bool), finite, 0.0 <= value <= 1.0 (NaN/inf fail the range test)."""
    return type(value) in (float, int) and 0.0 <= value <= 1.0


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
    """Errors of an evidence dict that must hold all eight fields."""
    errors = []
    if type(data) is not dict:
        _add(errors, ERR_MISSING_EVIDENCE if data is None else ERR_NOT_DICT, "evidence")
        return errors
    if len(data) > MAX_FIELDS:
        _add(errors, ERR_TOO_MANY_FIELDS, "evidence")
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
            if type(value) is not str or value != EVIDENCE_VERSION:
                _add(errors, "invalid_version", field)
        elif field in _TEXT_LIMITS:
            if not _is_text(value, _TEXT_LIMITS[field]):
                _add(errors, "invalid_" + field, field)
        elif field == "evidence_type":
            if type(value) is not str or value not in EVIDENCE_TYPES:
                _add(errors, "invalid_evidence_type", field)
        elif field == "confidence":
            if not _is_confidence(value):
                _add(errors, "invalid_confidence", field)
        elif field == "constraints":
            _check_constraints(errors, value)
        elif value is not False:
            _add(errors, "invalid_execution_allowed", field)
    return errors


def _validation(errors):
    return {"valid": not errors, "errors": errors,
            "execution_allowed": False, "executed": False}


def validate_research_evidence(evidence=None):
    """Validation result for a normalized research evidence object."""
    try:
        return _validation(_errors(evidence))
    except Exception:
        return _validation([{"code": ERR_INTERNAL, "where": "evidence"}])


def build_research_evidence(evidence=None):
    """Build a fresh normalized research evidence object from `evidence`, or report errors."""
    try:
        data = evidence
        if type(evidence) is dict and len(evidence) <= MAX_FIELDS:
            data = dict(evidence)
            for field in _OPTIONAL:
                data.setdefault(field, EVIDENCE_VERSION if field == "version" else False)
        errors = _errors(data)
        built = None
        if not errors:
            built = {"version": data["version"], "evidence_id": data["evidence_id"],
                     "source_id": data["source_id"], "claim": data["claim"],
                     "evidence_type": data["evidence_type"], "confidence": data["confidence"],
                     "constraints": list(data["constraints"]), "execution_allowed": False}
        return {"valid": not errors, "errors": errors, "evidence": built,
                "execution_allowed": False, "executed": False}
    except Exception:
        return {"valid": False, "errors": [{"code": ERR_INTERNAL, "where": "evidence"}],
                "evidence": None, "execution_allowed": False, "executed": False}
