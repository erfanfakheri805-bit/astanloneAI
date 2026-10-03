"""
Language Intelligence - Apply Correction Request (Exact Matching Only)
========================================================================
Prompt 475. A small, deterministic operation that applies an EXISTING
Prompt 473 `CorrectionApplicationRequest` to a specifically provided
target text, using EXACT text matching only, and reports the outcome
as an EXISTING Prompt 474 `CorrectionApplicationResult`.

    build_correction_application_request(...)  (Prompt 473, unchanged)
        -> CorrectionApplicationRequest
    apply_correction_request(request, target_text)   (THIS module)
        -> CorrectionApplicationResult

This module adds no new lookup, selection, matching, or readiness
logic - it only reads an already-built, already-ready request's
existing fields and performs one exact, literal substring replacement
against the text it is given. It never re-derives, re-validates, or
second-guesses `request.is_valid` beyond checking it, and it never
looks at anything other than the `request` and `target_text` it is
given.

Matching rule - EXACT ONLY
------------------------------
`request.original_expression` is matched against `target_text` with a
plain, literal, case-sensitive substring search
(Python's own `str.replace()`/`in`) - nothing else. No fuzzy matching,
similarity scoring, embeddings, semantic matching, spelling
correction, case normalization, automatic guessing, or partial-word
guessing is ever performed. Every exact, non-overlapping occurrence of
`original_expression` in `target_text` is replaced with
`corrected_expression_or_meaning` (`str.replace()`'s own existing
"replace all occurrences" behavior - reused, not reimplemented); no
text outside those exact occurrences is ever touched.

Outcomes
---------
    APPLIED       `request.is_valid` is `True`, both
                  `original_expression` and
                  `corrected_expression_or_meaning` are non-blank
                  strings, `target_text` is a string, and
                  `original_expression` occurs at least once in
                  `target_text` (exact match). `corrected_text` is
                  `target_text` with every exact occurrence replaced;
                  `original_text` is `target_text`, unchanged.
                  `metadata["occurrences_replaced"]` records how many
                  exact occurrences were replaced.
    NOT_APPLIED   the request and target text are both structurally
                  usable (as above), but `original_expression` does
                  not occur anywhere in `target_text` - nothing went
                  wrong, the correction simply does not apply to this
                  text. `target_text` is returned unmodified as both
                  `original_text` and `corrected_text`.
    FAILED        the request is not usable (`request.is_valid` is not
                  `True`, or `original_expression`/
                  `corrected_expression_or_meaning` is missing, blank,
                  or not text) or `target_text` is not a string.
                  `target_text` is never modified; `original_text` is
                  `target_text` when it is at least a string, else
                  `None`, and `corrected_text` is always `None`.
                  `reason` names which precondition failed.

Never applies anything beyond this one operation
----------------------------------------------------
`apply_correction_request()` performs exactly one exact-match
substring replacement and returns the result - it never modifies the
user's message, generated response text, or any stored learning
record, never writes to storage, never touches Memory, Knowledge, the
Learning algorithms, Response Generation, `ResponseGenerationContext`,
`AgentLoop`, Self-Upgrade, or the Local Model Runtime, and is not
connected to the normal conversation/response pipeline. It never
mutates `request` or `target_text`; `target_text` is a Python `str`,
already immutable, and `request`'s fields are only read, never set.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.

Prompt 478 addendum - matched_text / replacement_text / match_count
------------------------------------------------------------------------
The `APPLIED` result now also carries `matched_text` (the same
`original_expression` this function already matched exactly),
`replacement_text` (the same `corrected_expression` it already
substituted), and `match_count` (the same `occurrences` count it
already computes for `metadata["occurrences_replaced"]`). No new
matching, counting, or replacement logic is added - these are the
existing, already-computed values, simply also passed through to the
result's three new fields. `NOT_APPLIED` and `FAILED` results are
unchanged: `match_count` remains `0` by the result's own default and
`matched_text`/`replacement_text` remain `None`.
"""

from language_intelligence.correction_application_request import (
    CorrectionApplicationRequest,
)
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult,
    STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED,
)
from language_intelligence.correction_understanding import _is_blank


def _is_usable_text(value):
    """Same rule this package already uses elsewhere for "required,
    non-blank text": a real `str` that is not blank
    (`correction_understanding._is_blank()`, imported, never
    reimplemented)."""
    return isinstance(value, str) and not _is_blank(value)


def apply_correction_request(request, target_text):
    """Apply `request` (a `CorrectionApplicationRequest`, Prompt 473)
    to `target_text` using EXACT matching only, and return the
    outcome as a `CorrectionApplicationResult` (Prompt 474) - see the
    module docstring for the exact APPLIED / NOT_APPLIED / FAILED
    rules.

    Never raises: a structurally invalid `request` or a non-string
    `target_text` produces a `FAILED` result rather than an
    exception - `target_text` is never modified in that case. Pure
    and deterministic: the same `request` and `target_text` always
    produce an equal result.
    """
    if not isinstance(request, CorrectionApplicationRequest):
        return CorrectionApplicationResult(
            STATUS_FAILED,
            original_text=target_text if isinstance(target_text, str) else None,
            reason="request_not_a_correction_application_request",
        )

    if not isinstance(target_text, str):
        return CorrectionApplicationResult(
            STATUS_FAILED,
            original_text=None,
            reason="target_text_not_a_string",
        )

    if request.is_valid is not True:
        return CorrectionApplicationResult(
            STATUS_FAILED,
            original_text=target_text,
            reason="request_not_valid",
        )

    if not _is_usable_text(request.original_expression):
        return CorrectionApplicationResult(
            STATUS_FAILED,
            original_text=target_text,
            reason="original_expression_missing_or_not_text",
        )

    if not _is_usable_text(request.corrected_expression_or_meaning):
        return CorrectionApplicationResult(
            STATUS_FAILED,
            original_text=target_text,
            reason="corrected_expression_or_meaning_missing_or_not_text",
        )

    original_expression = request.original_expression
    corrected_expression = request.corrected_expression_or_meaning

    occurrences = target_text.count(original_expression)
    if occurrences == 0:
        return CorrectionApplicationResult(
            STATUS_NOT_APPLIED,
            original_text=target_text,
            corrected_text=target_text,
            reason="original_expression_not_found_in_target_text",
        )

    corrected_text = target_text.replace(
        original_expression, corrected_expression,
    )
    return CorrectionApplicationResult(
        STATUS_APPLIED,
        original_text=target_text,
        corrected_text=corrected_text,
        metadata={"occurrences_replaced": occurrences},
        matched_text=original_expression,
        replacement_text=corrected_expression,
        match_count=occurrences,
    )
