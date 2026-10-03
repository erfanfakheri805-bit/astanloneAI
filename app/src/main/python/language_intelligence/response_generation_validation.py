"""
Language Intelligence - Response-Generation Result Validation
====================================================================
Prompt 430. A small, deterministic consistency check over a
`ResponseGenerationResult` (response_generation.py) and the structured
`ResponseGenerationOutcome` (response_generation_outcome.py, Prompts
428/429) derived from it, so an invalid or internally inconsistent
response-generation result is reported instead of passing through the
language pipeline unnoticed.

Only fields and rules that already exist are checked; nothing is added to
`ResponseGenerationResult` or `ResponseGenerationOutcome`, and no second
result model exists - `ResponseGenerationValidation` below only WRAPS the
original outcome together with the list of problems found.

Rules (outcome status -> what must hold)
------------------------------------------------------------------------
    SUCCESS     generated_text is a non-empty string; failure_reason is
                None (no failure indicated); fallback_used is False.
    FALLBACK    generated_text is a non-empty string; fallback_used is
                True.
    FAILED      failure_reason is present (a non-empty dict); it is not
                treated as a success: generated_text is None and
                fallback_used is False.
    UNRESOLVED  stays unresolved: generated_text is None, failure_reason
                is None, fallback_used is False (no text is invented).

Result-level rules (inconsistencies the four-status outcome would
otherwise hide, e.g. a STATUS_GENERATED result with no text is mapped to
UNRESOLVED by the outcome builder):
    - the value must be a `ResponseGenerationResult` with a known status;
    - STATUS_GENERATED must carry a non-empty `response_text`;
    - STATUS_DEFERRED / STATUS_NOT_IMPLEMENTED must carry no
      `response_text`;
    - a model-failure status without a fallback backend must carry no
      `response_text`.

Behavior
------------------------------------------------------------------------
Pure and deterministic: no model, no inference, no network, no scoring,
no randomness. Never raises for a bad input - it returns an INVALID
validation. Never mutates the result, the outcome or the request. A valid
validation carries the SAME outcome object it was given (or built), so
generated text, backend kind, language, locale, failure reason,
fallback_used and metadata are preserved exactly. An invalid one still
carries that outcome untouched plus a copy of the result's own fields; it
never turns anything into SUCCESS and never writes response text.

Note: today a real FALLBACK (a failed local model handed to the
deterministic fallback backend, Prompt 406/414) carries no text of its own
- the reply is produced afterwards by Core's existing pipeline - so it is
reported here as INVALID with `ISSUE_FALLBACK_WITHOUT_TEXT`. That is the
rule as specified, reported honestly; validation only reports and changes
no behavior.
"""

from .response_generation import (
    ResponseGenerationResult, ALL_STATUSES, STATUS_GENERATED, STATUS_DEFERRED,
    STATUS_NOT_IMPLEMENTED, MODEL_FAILURE_STATUSES,
)
from .response_generation_outcome import (
    ResponseGenerationOutcome, build_response_generation_outcome,
    STATUS_SUCCESS, STATUS_FALLBACK, STATUS_FAILED, STATUS_UNRESOLVED,
)

VALIDATION_VALID = "VALID"
VALIDATION_INVALID = "INVALID"

ISSUE_NOT_A_RESULT = "not_a_result"
ISSUE_UNKNOWN_STATUS = "unknown_status"
ISSUE_OUTCOME_UNAVAILABLE = "outcome_unavailable"
ISSUE_GENERATED_WITHOUT_TEXT = "generated_without_text"
ISSUE_TEXT_ON_UNRESOLVED = "text_on_unresolved_result"
ISSUE_TEXT_ON_FAILURE = "text_on_failed_result"
ISSUE_SUCCESS_WITHOUT_TEXT = "success_without_text"
ISSUE_SUCCESS_WITH_FAILURE = "success_with_failure_reason"
ISSUE_SUCCESS_WITH_FALLBACK = "success_with_fallback_used"
ISSUE_FALLBACK_WITHOUT_TEXT = "fallback_without_text"
ISSUE_FALLBACK_NOT_USED = "fallback_used_not_true"
ISSUE_FAILED_WITHOUT_REASON = "failed_without_failure_reason"
ISSUE_FAILED_WITH_TEXT = "failed_with_text"
ISSUE_FAILED_WITH_FALLBACK = "failed_with_fallback_used"
ISSUE_UNRESOLVED_WITH_TEXT = "unresolved_with_text"
ISSUE_UNRESOLVED_WITH_FAILURE = "unresolved_with_failure_reason"
ISSUE_UNRESOLVED_WITH_FALLBACK = "unresolved_with_fallback_used"


class ResponseGenerationValidation:
    """Plain, JSON-shaped, read-only value (same `to_dict()` convention as
    the rest of this package).

        status   VALIDATION_VALID or VALIDATION_INVALID.
        issues   list of `{"code": ..., "message": ...}` - empty when valid.
        outcome  the ORIGINAL `ResponseGenerationOutcome`, unchanged (the
                 same object - never a rebuilt or "repaired" one), or None
                 when none could be built.
        result   `ResponseGenerationResult.to_dict()` of the validated
                 result (a copy), or None when it was not a result.
    """

    def __init__(self, status, issues=None, outcome=None, result=None):
        if status not in (VALIDATION_VALID, VALIDATION_INVALID):
            raise ValueError("status must be VALID or INVALID")
        self.status = status
        self.issues = [dict(issue) for issue in (issues or [])]
        self.outcome = outcome
        self.result = dict(result) if result else None

    @property
    def valid(self):
        return self.status == VALIDATION_VALID

    @property
    def issue_codes(self):
        return [issue["code"] for issue in self.issues]

    def __repr__(self):
        return f"ResponseGenerationValidation(status={self.status!r}, issues={self.issue_codes})"

    def to_dict(self):
        return {
            "status": self.status,
            "issues": [dict(issue) for issue in self.issues],
            "outcome": self.outcome.to_dict() if self.outcome is not None else None,
            "result": dict(self.result) if self.result else None,
        }


def _has_text(value):
    return isinstance(value, str) and bool(value.strip())


def _issue(code, message):
    return {"code": code, "message": message}


def _result_issues(result):
    issues = []
    if result.status not in ALL_STATUSES:
        return [_issue(ISSUE_UNKNOWN_STATUS, f"unknown result status {result.status!r}")]
    has_text = _has_text(result.response_text)
    if result.status == STATUS_GENERATED and not has_text:
        issues.append(_issue(ISSUE_GENERATED_WITHOUT_TEXT,
                             "a generated result must carry non-empty response text"))
    if result.status in (STATUS_DEFERRED, STATUS_NOT_IMPLEMENTED) and result.response_text is not None:
        issues.append(_issue(ISSUE_TEXT_ON_UNRESOLVED,
                             "an unresolved result must not carry response text"))
    if (result.status in MODEL_FAILURE_STATUSES and result.fallback_backend_kind is None
            and result.response_text is not None):
        issues.append(_issue(ISSUE_TEXT_ON_FAILURE,
                             "a failed result must not carry response text"))
    return issues


def _outcome_issues(outcome):
    issues = []
    text_ok = _has_text(outcome.generated_text)
    reason = outcome.failure_reason
    if outcome.status == STATUS_SUCCESS:
        if not text_ok:
            issues.append(_issue(ISSUE_SUCCESS_WITHOUT_TEXT, "SUCCESS requires non-empty generated text"))
        if reason:
            issues.append(_issue(ISSUE_SUCCESS_WITH_FAILURE, "SUCCESS must not carry a failure reason"))
        if outcome.fallback_used:
            issues.append(_issue(ISSUE_SUCCESS_WITH_FALLBACK, "SUCCESS must not have fallback_used"))
    elif outcome.status == STATUS_FALLBACK:
        if not text_ok:
            issues.append(_issue(ISSUE_FALLBACK_WITHOUT_TEXT, "FALLBACK requires non-empty generated text"))
        if outcome.fallback_used is not True:
            issues.append(_issue(ISSUE_FALLBACK_NOT_USED, "FALLBACK requires fallback_used to be true"))
    elif outcome.status == STATUS_FAILED:
        if not (isinstance(reason, dict) and reason):
            issues.append(_issue(ISSUE_FAILED_WITHOUT_REASON, "FAILED requires a failure reason"))
        if outcome.generated_text is not None:
            issues.append(_issue(ISSUE_FAILED_WITH_TEXT, "FAILED must not be treated as a generated response"))
        if outcome.fallback_used:
            issues.append(_issue(ISSUE_FAILED_WITH_FALLBACK, "FAILED must not have fallback_used"))
    elif outcome.status == STATUS_UNRESOLVED:
        if outcome.generated_text is not None:
            issues.append(_issue(ISSUE_UNRESOLVED_WITH_TEXT, "UNRESOLVED must not carry generated text"))
        if reason:
            issues.append(_issue(ISSUE_UNRESOLVED_WITH_FAILURE, "UNRESOLVED must not carry a failure reason"))
        if outcome.fallback_used:
            issues.append(_issue(ISSUE_UNRESOLVED_WITH_FALLBACK, "UNRESOLVED must not have fallback_used"))
    return issues


def validate_response_generation_result(result, outcome=None, request=None):
    """Validate `result` (a `ResponseGenerationResult`) and its structured
    `outcome` (built with `build_response_generation_outcome(result,
    request)` when not given). Returns a `ResponseGenerationValidation`;
    never raises, never mutates `result`, `outcome` or `request`."""
    if not isinstance(result, ResponseGenerationResult):
        return ResponseGenerationValidation(
            VALIDATION_INVALID,
            [_issue(ISSUE_NOT_A_RESULT, "the value is not a ResponseGenerationResult")])
    issues = _result_issues(result)
    if outcome is None:
        try:
            outcome = build_response_generation_outcome(result, request=request)
        except Exception:  # noqa: BLE001 - validation reports, never raises
            outcome = None
    if not isinstance(outcome, ResponseGenerationOutcome):
        issues.append(_issue(ISSUE_OUTCOME_UNAVAILABLE, "no structured outcome could be built"))
        outcome = None
    else:
        issues.extend(_outcome_issues(outcome))
    return ResponseGenerationValidation(
        VALIDATION_INVALID if issues else VALIDATION_VALID, issues, outcome=outcome,
        result=result.to_dict())
