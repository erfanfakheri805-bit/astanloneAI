"""
Language Intelligence - Structured Exact Correction Lookup Result
========================================================================
Prompt 464. A small, structured outcome for the EXISTING exact
correction lookup operation (Prompt 463,
`correction_learning_input_retrieval.
lookup_stored_correction_learning_input_by_original_expression()`).
This module adds no new lookup logic and no new matching behavior - it
only names, as one small result object, the outcome that lookup
already produces today, the SAME "wrap an existing operation's outcome
as a small structured result" convention Prompt 458's
`CorrectionLearningHandoffResult` already established for the
correction-learning HANDOFF path (correction_learning_handoff_result.py):

    lookup_stored_correction_learning_input_by_original_expression(store, expr, language)
        -> store not a LanguageLearningStore -> raises TypeError  (Prompt 463, unchanged)
        -> no exact record(s) exist          -> returns []        (Prompt 463, unchanged)
        -> exact record(s) exist             -> returns [dict, ...] (Prompt 463, unchanged)

`lookup_correction_learning_input_by_original_expression_with_result()`
(THIS module) calls that EXACT function - never re-implementing exact
matching, the language-optional lookup, or the store's own ordering -
and reports which of those three outcomes happened as a
`CorrectionLearningExactLookupResult`:

    FOUND      - one or more exact records were found (`records`
                 holds all of them, EACH ONE the SAME dict shape
                 `get_item()`/`find_items()` already return -
                 `key`, `meaning`, `language`, `confidence`, `source`,
                 `source_context`, plus `id`/`version`/`created_at`/
                 `updated_at` - preserved UNCHANGED, in the SAME order
                 Prompt 463's own lookup already returns them in
                 (the store's existing `language, item_type, id`
                 ordering - never re-sorted, ranked, scored, or
                 reduced to one here).
    NOT_FOUND  - no exact record exists (`lookup_stored_correction_
                 learning_input_by_original_expression()` returned the
                 empty list - Prompt 463's own existing NOT_FOUND/empty
                 convention) - `records` is `[]`.
    FAILED     - the underlying lookup itself failed (`store` was not
                 a `LanguageLearningStore`, or `language`/
                 `original_expression` failed Prompt 416's own existing
                 argument validation - the SAME `TypeError`/`ValueError`
                 Prompt 463's lookup, `find_items()`, and
                 `_resolve_language()`/`_require_text()` already raise
                 for every other caller) - `records` is `[]` and
                 `reason` carries the existing exception's own message
                 (`str(exc)`), reused verbatim, the SAME "reuse the
                 existing exception text, invent nothing new" posture
                 `CorrectionLearningHandoffResult`'s own FAILED case
                 (Prompt 458) already uses.

`original_expression` is always the value the caller looked up,
echoed back unchanged - so a `NOT_FOUND`/`FAILED` result still says
what was searched for.

Multiple exact records (the same original expression learned under
more than one language) are never collapsed, ranked, scored, or
auto-selected down to one here - `records` simply carries every one
Prompt 463's own lookup already returned, in that same existing order.
Choosing among them, if a caller ever needs to, is that caller's own
decision - not this module's.

This module does not touch `LearningAnalyzer`, correction detection,
`CorrectionUnderstanding`, `CorrectionUnderstandingResult`,
`CorrectionFeedbackRecord`, response generation, or the Local Model
Runtime; it adds no Memory or Knowledge integration, no new
persistence or database, no ranking/scoring/fuzzy/semantic matching,
and makes no network/API call. It does not modify
`lookup_stored_correction_learning_input_by_original_expression()`,
`retrieve_stored_correction_learning_input()`,
`store_accepted_correction_learning_input()`, or
`LanguageLearningStore` in any way - it is a thin, read-only wrapper
over an outcome that already exists.
"""

from language_intelligence.correction_learning_input_retrieval import (
    lookup_stored_correction_learning_input_by_original_expression,
)

STATUS_FOUND = "FOUND"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_FAILED = "FAILED"
ALL_STATUSES = (STATUS_FOUND, STATUS_NOT_FOUND, STATUS_FAILED)


class CorrectionLearningExactLookupResult:
    """The minimum useful fields describing one exact correction
    lookup's outcome - nothing more.

        status                - one of ALL_STATUSES (FOUND / NOT_FOUND
                                 / FAILED).
        original_expression   - the expression that was looked up,
                                 echoed back unchanged.
        records                - a list of stored correction records
                                 (each the SAME dict shape Prompt 463's
                                 lookup already returns - `key`
                                 (original expression), `meaning`
                                 (corrected expression or meaning),
                                 `language`, `confidence`, `source`,
                                 `source_context`, ... - preserved
                                 unchanged, in the store's existing
                                 order). `[]` for NOT_FOUND and FAILED.
                                 Never reduced to one record when more
                                 than one exists - see module
                                 docstring.
        reason                 - an EXISTING failure reason, reused
                                 verbatim, only for STATUS_FAILED
                                 (Prompt 463's/`find_items()`'s own
                                 exception message); `None` otherwise.
                                 Never an invented explanation.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior of its own beyond `to_dict()`.
    """

    __slots__ = ("status", "original_expression", "records", "reason")

    def __init__(self, status, original_expression, records=None, reason=None):
        if status not in ALL_STATUSES:
            raise ValueError(
                "status must be one of %r, got %r" % (ALL_STATUSES, status)
            )
        self.status = status
        self.original_expression = original_expression
        self.records = list(records) if records else []
        self.reason = reason

    def to_dict(self):
        """This result as a plain, JSON-shaped dict - the same
        "small, JSON-shaped" convention this project's other result
        objects already follow (e.g. `CorrectionLearningHandoffResult`)."""
        return {
            "status": self.status,
            "original_expression": self.original_expression,
            "records": list(self.records),
            "reason": self.reason,
        }

    def __eq__(self, other):
        if not isinstance(other, CorrectionLearningExactLookupResult):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "CorrectionLearningExactLookupResult(%r)" % (self.to_dict(),)


def lookup_correction_learning_input_by_original_expression_with_result(
        store, original_expression, language=None):
    """Attempt the EXISTING exact correction lookup
    (`lookup_stored_correction_learning_input_by_original_expression()`,
    Prompt 463 - called here exactly as any other caller would call
    it, never re-implemented) and report the outcome as a
    `CorrectionLearningExactLookupResult` instead of a
    list-or-raise:

        - it returns a non-empty list (one or more exact records
          exist) -> `STATUS_FOUND`, `records` holding all of them,
          unchanged and in that same existing order, `reason=None`.
        - it returns `[]` (no exact record exists - Prompt 463's own
          existing NOT_FOUND/empty convention) -> `STATUS_NOT_FOUND`,
          `records=[]`, `reason=None`.
        - it raises `TypeError` or `ValueError` (`store` was not a
          `LanguageLearningStore`, or `language`/`original_expression`
          failed the existing argument validation - the SAME
          exceptions Prompt 463's lookup and `LanguageLearningStore`
          already raise for every other caller) -> `STATUS_FAILED`,
          `records=[]`, `reason=str(exc)` (the exception's own,
          already-existing message, reused verbatim).

    Any other exception is not one of this pipeline's documented
    outcomes and propagates unchanged, exactly as it would from a
    direct call to
    `lookup_stored_correction_learning_input_by_original_expression()` -
    this wrapper invents no handling for it.

    `original_expression` is always echoed back on the result exactly
    as given, regardless of outcome.

    Read-only and deterministic aside from the underlying lookup's own
    existing read-only guarantee: never creates, updates, or deletes
    anything, and never mutates `store` or any argument.
    """
    try:
        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, original_expression, language=language)
    except (TypeError, ValueError) as exc:
        return CorrectionLearningExactLookupResult(
            STATUS_FAILED, original_expression, records=[], reason=str(exc))

    if not matches:
        return CorrectionLearningExactLookupResult(
            STATUS_NOT_FOUND, original_expression, records=[])

    return CorrectionLearningExactLookupResult(
        STATUS_FOUND, original_expression, records=matches)
