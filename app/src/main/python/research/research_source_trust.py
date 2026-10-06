"""
Research Source Trust Evaluation (Prompt 867, Section 15 - Autonomous Research & Learning)
==========================================================================================
A small, deterministic, read-only check of whether ONE research source satisfies
the minimum trust requirement declared by a Research Request. It performs no
source matching or selection, and never opens, accesses, loads, fetches or
executes anything from a source. Trust comes ONLY from the source's own
`trust_level` field: nothing is inferred from location, URL, name, type,
content or any outside information, and trust is never upgraded. No network,
filesystem, subprocess, LLM, Core, Memory or AEL.

  evaluate_research_source_trust(research_request, source) -> trust result
  validate_research_source_trust(result)                   -> validation result

Reuses the public validators of Prompt 863 (validate_research_request) and
Prompt 864 (validate_research_source) and the TRUST_LEVELS ordering
"trusted" > "standard" > "untrusted".

Minimum trust constraint (the only one; not a constraint language or parser)
  A request constraint that is exactly "min_trust:<level>", with <level> one of
  TRUST_LEVELS (exact, case-sensitive), in the same exact-prefix style as the
  "source_type:<type>" constraint of Prompt 865. Any other constraint is
  ignored. A "min_trust:" entry with an unknown level makes the request
  invalid (never guessed). If several entries are declared, all must hold, so
  the highest level applies. No entry means no minimum.

Evaluation (in this order)
  1. request invalid                      -> "invalid_request"
  2. source invalid                       -> "invalid_source"
  3. source not enabled                   -> "not_trusted" (source_disabled)
  4. trust_level below the declared min   -> "not_trusted" (below_minimum_trust)
  5. otherwise                            -> "trusted" (meets_minimum_trust, or
                                             no_minimum_declared when none is declared)

Trust result (exactly these seven keys, fixed order, fresh on every call):

  {"status", "trusted", "source_id", "trust_level", "reason",
   "execution_allowed", "executed"}

  status            one of STATUSES: "trusted", "not_trusted", "invalid_request",
                    "invalid_source", "trust_evaluation_error"
  trusted           True only when status is "trusted"
  source_id         the source's exact source_id for "trusted"/"not_trusted",
                    else None (nothing is echoed from an invalid source)
  trust_level       the source's exact trust_level, same rule
  reason            one of REASONS, fixed per status
  execution_allowed always exactly False
  executed          always exactly False

validate_research_source_trust(result)
  Structural and consistency check, never repairs. Result (fixed keys, fresh):
  {"valid", "errors", "execution_allowed", "executed"}. Codes: missing_result,
  result_not_dict, too_many_fields, unexpected_field, missing_field,
  invalid_status, invalid_trusted, invalid_source_id, invalid_trust_level,
  invalid_reason, inconsistent_result, invalid_execution_allowed,
  invalid_executed, validation_error.

Bounded work, read-only (inputs are never modified or kept), deterministic,
never raises.
"""

from research.research_request import validate_research_request
from research.research_source import MAX_ID_LENGTH, TRUST_LEVELS, validate_research_source

MIN_TRUST_PREFIX = "min_trust:"

MAX_ERRORS = 16
MAX_FIELDS = 16

STATUS_TRUSTED = "trusted"
STATUS_NOT_TRUSTED = "not_trusted"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_INVALID_SOURCE = "invalid_source"
STATUS_ERROR = "trust_evaluation_error"
STATUSES = (STATUS_TRUSTED, STATUS_NOT_TRUSTED, STATUS_INVALID_REQUEST,
            STATUS_INVALID_SOURCE, STATUS_ERROR)

REASON_MEETS = "meets_minimum_trust"
REASON_NO_MINIMUM = "no_minimum_declared"
REASON_BELOW = "below_minimum_trust"
REASON_DISABLED = "source_disabled"
REASON_INVALID_REQUEST = "invalid_request"
REASON_INVALID_SOURCE = "invalid_source"
REASON_ERROR = "trust_evaluation_error"
REASONS = (REASON_MEETS, REASON_NO_MINIMUM, REASON_BELOW, REASON_DISABLED,
           REASON_INVALID_REQUEST, REASON_INVALID_SOURCE, REASON_ERROR)

_REASONS_OF_STATUS = {STATUS_TRUSTED: (REASON_MEETS, REASON_NO_MINIMUM),
                      STATUS_NOT_TRUSTED: (REASON_BELOW, REASON_DISABLED),
                      STATUS_INVALID_REQUEST: (REASON_INVALID_REQUEST,),
                      STATUS_INVALID_SOURCE: (REASON_INVALID_SOURCE,),
                      STATUS_ERROR: (REASON_ERROR,)}

FIELDS = ("status", "trusted", "source_id", "trust_level", "reason",
          "execution_allowed", "executed")


def _result(status, reason, source=None):
    return {"status": status, "trusted": status == STATUS_TRUSTED,
            "source_id": source["source_id"] if source else None,
            "trust_level": source["trust_level"] if source else None,
            "reason": reason, "execution_allowed": False, "executed": False}


def _minimum_rank(request):
    """Highest declared minimum as a TRUST_LEVELS index, -1 if none, None if malformed."""
    rank = -1
    for constraint in request["constraints"]:
        if constraint.startswith(MIN_TRUST_PREFIX):
            level = constraint[len(MIN_TRUST_PREFIX):]
            if level not in TRUST_LEVELS:
                return None
            rank = max(rank, TRUST_LEVELS.index(level))
    return rank


def evaluate_research_source_trust(research_request=None, source=None):
    """Fresh trust result; inputs are never modified and no source is accessed."""
    try:
        if not validate_research_request(research_request)["valid"]:
            return _result(STATUS_INVALID_REQUEST, REASON_INVALID_REQUEST)
        minimum = _minimum_rank(research_request)
        if minimum is None:
            return _result(STATUS_INVALID_REQUEST, REASON_INVALID_REQUEST)
        if not validate_research_source(source)["valid"]:
            return _result(STATUS_INVALID_SOURCE, REASON_INVALID_SOURCE)
        if source["enabled"] is not True:
            return _result(STATUS_NOT_TRUSTED, REASON_DISABLED, source)
        if TRUST_LEVELS.index(source["trust_level"]) < minimum:
            return _result(STATUS_NOT_TRUSTED, REASON_BELOW, source)
        return _result(STATUS_TRUSTED, REASON_MEETS if minimum >= 0 else REASON_NO_MINIMUM,
                       source)
    except Exception:
        return _result(STATUS_ERROR, REASON_ERROR)


def _add(errors, code, where):
    if len(errors) < MAX_ERRORS and {"code": code, "where": where} not in errors:
        errors.append({"code": code, "where": where})


def _result_errors(result):
    errors = []
    if type(result) is not dict:
        _add(errors, "missing_result" if result is None else "result_not_dict", "result")
        return errors
    if len(result) > MAX_FIELDS:
        _add(errors, "too_many_fields", "result")
        return errors
    for key in result:
        if type(key) is not str or key not in FIELDS:
            _add(errors, "unexpected_field", key if type(key) is str and 0 < len(key) <= 40
                 else "<field>")
    for field in FIELDS:
        if field not in result:
            _add(errors, "missing_field", field)
    if errors:
        return errors
    status, reason = result["status"], result["reason"]
    status_ok = type(status) is str and status in STATUSES
    if not status_ok:
        _add(errors, "invalid_status", "status")
    if type(result["trusted"]) is not bool or (status_ok and result["trusted"] != (status == STATUS_TRUSTED)):
        _add(errors, "invalid_trusted", "trusted")
    if not (type(reason) is str and reason in REASONS):
        _add(errors, "invalid_reason", "reason")
    evaluated = status in (STATUS_TRUSTED, STATUS_NOT_TRUSTED)
    source_id, level = result["source_id"], result["trust_level"]
    if evaluated:
        if type(source_id) is not str or not 0 < len(source_id) <= MAX_ID_LENGTH:
            _add(errors, "invalid_source_id", "source_id")
        if type(level) is not str or level not in TRUST_LEVELS:
            _add(errors, "invalid_trust_level", "trust_level")
    else:
        if source_id is not None:
            _add(errors, "invalid_source_id", "source_id")
        if level is not None:
            _add(errors, "invalid_trust_level", "trust_level")
    for field in ("execution_allowed", "executed"):
        if result[field] is not False:
            _add(errors, "invalid_" + field, field)
    if not errors:
        if (reason not in _REASONS_OF_STATUS[status]
                or (reason == REASON_BELOW and level == TRUST_LEVELS[-1])):
            _add(errors, "inconsistent_result", "result")
    return errors


def validate_research_source_trust(result=None):
    """Validation result for a trust result; nothing is repaired."""
    try:
        errors = _result_errors(result)
    except Exception:
        errors = [{"code": "validation_error", "where": "result"}]
    return {"valid": not errors, "errors": errors, "execution_allowed": False, "executed": False}
