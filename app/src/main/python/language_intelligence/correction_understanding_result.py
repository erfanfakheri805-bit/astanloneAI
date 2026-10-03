"""
Language Intelligence - Correction Understanding Result (compact form)
========================================================================
Prompt 441. A small, deterministic result model built ONLY from the
existing `CorrectionUnderstanding` (Prompt 439,
language_intelligence/correction_understanding.py - the class the
project imports here under that shorter name; its own module exposes
it publicly as `CorrectionUnderstandingResult`, same object).

This module does not detect, parse or infer anything, and does not add
a second correction system. It takes an already-built
`CorrectionUnderstanding` and copies its pieces into one flatter,
JSON-shaped record - `corrected_expression` and `corrected_meaning`
collapse into a single `corrected_expression_or_meaning` field, since a
resolved correction only ever has one populated (Prompt 439's own
decision order never fills both from the caller's meaning side once an
expression side is present). Nothing is guessed, normalized, translated
or reworded - every field is either a straight copy or, for the merged
field, a fixed choice between two already-existing values.

Fields (only these seven; nothing else is carried)
----------------------------------------------------
    status                          one of `ALL_STATUSES` (imported from
                                     `correction_understanding.py` -
                                     never redefined here)
    original_expression              copied through, unchanged
    corrected_expression_or_meaning  `corrected_expression` if it is not
                                      None, otherwise `corrected_meaning`,
                                      otherwise None - never both, never
                                      invented
    language                         copied through, unchanged
    locale                           copied through, unchanged
    source_text                      copied through, unchanged - the
                                      original user message, verbatim
    confidence                       copied through, unchanged

Not connected to Learning, Memory, Knowledge, Meaning Resolution,
Response Generation or Pattern Matching; no persistent storage; does
not change the Language Intelligence Core architecture, the Local
Model Runtime, or any existing `CorrectionUnderstanding` behavior.

`build_correction_understanding_result()` is pure and deterministic:
the same `CorrectionUnderstanding` always produces the same result,
and nothing is mutated, stored or looked up anywhere.

Prompt 445 adds four small read-only status helpers to this class
(`is_resolved`, `is_ambiguous`, `is_unresolved`, `is_not_correction`) -
simple deterministic equality checks against the existing `status`
field. No new status values, no mutation, no new status system.

Prompt 446 adds `get_summary()`, a small structured (JSON-shaped)
summary of this result - status, original_expression,
corrected_expression_or_meaning, language, locale and confidence, each
copied straight through from the existing attribute (no `source_text`;
see `get_summary()`'s own docstring). Reuses this project's existing
`get_X_summary()` plain-dict convention rather than introducing a new
representation; nothing is invented, derived or looked up.

Prompt 447 adds `__eq__`, a small, deterministic equality comparison
over this class's own seven fields (status, original_expression,
corrected_expression_or_meaning, language, locale, source_text,
confidence) - same "isinstance check, then compare fields directly"
convention already used by `Token.__eq__` in
understanding/nl_tokenizer.py. A value that is not a
`CorrectionUnderstandingResult` simply compares unequal (never raises,
never coerced). No field is normalized, reordered or fuzzily matched;
two results are equal only when every one of the seven fields is
exactly equal. Read-only and side-effect-free: comparing two results
never mutates either one.

Prompt 448 adds `copy()`, a small, deterministic safe-copy operation:
returns a new, independent `CorrectionUnderstandingResult` with the
same seven fields (so `original.copy() == original`, Prompt 447's
`__eq__`). `status`, `original_expression`, `language`, `locale`,
`source_text` and `confidence` are always plain immutable values
(`str`/`float`/`None`) and are simply passed through, unchanged, to
the new instance - the same "no unnecessary copying of immutable
values" posture `response_planning.py` already follows for its own
plain fields. `corrected_expression_or_meaning` is the one field that
can carry a mutable, caller-shaped JSON value (it may be
`corrected_meaning`, documented in correction_understanding.py as
"any caller-shaped JSON value"), so it is copied with
`copy.deepcopy()` - the same convention `response_planning.py` already
uses for its own mutable fields - so the copy can never share that
mutable state with the original. Pure and deterministic; never
mutates the original result.
"""

import copy

from language_intelligence.correction_understanding import (
    CorrectionUnderstandingResult as CorrectionUnderstanding,
    ALL_STATUSES,
    STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED, STATUS_NOT_CORRECTION,
)


class CorrectionUnderstandingResult:
    """Plain, read-only, JSON-shaped compact record of one explicit
    correction - same `to_dict()` convention used throughout this
    package. Never constructed from raw text; built only from an
    already-built `CorrectionUnderstanding` (see
    `build_correction_understanding_result()` below).
    """

    def __init__(self, status, source_text, original_expression=None,
                 corrected_expression_or_meaning=None, language=None,
                 locale=None, confidence=0.0):
        if status not in ALL_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        self.status = status
        self.source_text = source_text
        self.original_expression = original_expression
        self.corrected_expression_or_meaning = corrected_expression_or_meaning
        self.language = language
        self.locale = locale
        self.confidence = confidence

    def to_dict(self):
        return {
            "status": self.status,
            "original_expression": self.original_expression,
            "corrected_expression_or_meaning": self.corrected_expression_or_meaning,
            "language": self.language,
            "locale": self.locale,
            "source_text": self.source_text,
            "confidence": self.confidence,
        }

    # ------------------------------------------------------------------
    # Prompt 445: small, read-only status helpers. Each is a simple
    # deterministic equality check against the existing `status` field -
    # no new status values, no side effects, same `is_*` `@property`
    # convention already used elsewhere in this package (see
    # `ResponseGenerationResult.is_generated` in response_generation.py
    # and `CorrectionUnderstandingResultCompleteness.complete` in
    # correction_understanding_result_completeness.py).
    # ------------------------------------------------------------------

    @property
    def is_resolved(self):
        """True when `status` is STATUS_RESOLVED."""
        return self.status == STATUS_RESOLVED

    @property
    def is_ambiguous(self):
        """True when `status` is STATUS_AMBIGUOUS."""
        return self.status == STATUS_AMBIGUOUS

    @property
    def is_unresolved(self):
        """True when `status` is STATUS_UNRESOLVED."""
        return self.status == STATUS_UNRESOLVED

    @property
    def is_not_correction(self):
        """True when `status` is STATUS_NOT_CORRECTION."""
        return self.status == STATUS_NOT_CORRECTION

    # ------------------------------------------------------------------
    # Prompt 446: a small structured (JSON-shaped) summary - same
    # `get_X_summary()` plain-dict convention already used elsewhere in
    # this project (see `RevenueTask.get_status_summary()` in
    # financial/revenue_task.py). Every value is copied straight through
    # from an existing attribute, exactly as `to_dict()` already does -
    # nothing is guessed, derived or looked up. Unlike `to_dict()`, this
    # intentionally leaves out `source_text`: the summary is meant as a
    # short, at-a-glance view of the correction itself (status, the two
    # expressions, language/locale, confidence), not the original
    # message it came from.
    # ------------------------------------------------------------------

    def get_summary(self):
        """A small structured (JSON-shaped) summary of this result:
        status, original_expression, corrected_expression_or_meaning,
        language, locale and confidence - each copied straight through
        from the existing attribute of the same name. Never modifies
        this result, never re-detects or re-resolves anything, and
        never touches Learning, Memory, Knowledge, Meaning Resolution,
        Pattern Matching or Response Generation."""
        return {
            "status": self.status,
            "original_expression": self.original_expression,
            "corrected_expression_or_meaning": self.corrected_expression_or_meaning,
            "language": self.language,
            "locale": self.locale,
            "confidence": self.confidence,
        }

    def __repr__(self):
        return (
            f"CorrectionUnderstandingResult(status={self.status!r}, "
            f"original_expression={self.original_expression!r}, "
            f"corrected_expression_or_meaning={self.corrected_expression_or_meaning!r})"
        )

    # ------------------------------------------------------------------
    # Prompt 447: a small, deterministic equality comparison - same
    # "isinstance check, then compare fields directly" convention
    # already used by `Token.__eq__` in
    # understanding/nl_tokenizer.py. Compares exactly the seven fields
    # this class defines (status, original_expression,
    # corrected_expression_or_meaning, language, locale, source_text,
    # confidence); nothing is normalized or fuzzily matched. A value
    # that is not a `CorrectionUnderstandingResult` simply compares
    # unequal - never raises. Never mutates either side.
    # ------------------------------------------------------------------

    def __eq__(self, other):
        return (
            isinstance(other, CorrectionUnderstandingResult)
            and self.status == other.status
            and self.original_expression == other.original_expression
            and self.corrected_expression_or_meaning == other.corrected_expression_or_meaning
            and self.language == other.language
            and self.locale == other.locale
            and self.source_text == other.source_text
            and self.confidence == other.confidence
        )

    # ------------------------------------------------------------------
    # Prompt 448: a small, deterministic safe-copy operation - reuses
    # this class's own constructor (no second result model), and the
    # `copy.deepcopy()` convention response_planning.py already uses
    # for its own mutable fields. `status`, `original_expression`,
    # `language`, `locale`, `source_text` and `confidence` are always
    # plain immutable values here and are passed through unchanged;
    # `corrected_expression_or_meaning` is the one field that can carry
    # a mutable, caller-shaped JSON value, so it alone is deep-copied.
    # Never mutates this result.
    # ------------------------------------------------------------------

    def copy(self):
        """Return a new, independent `CorrectionUnderstandingResult`
        with the same seven fields (`self.copy() == self`, Prompt
        447's `__eq__`). Shares no mutable state with `self`: the one
        field that can carry a mutable value
        (`corrected_expression_or_meaning`) is deep-copied; every other
        field is an already-immutable value passed through as-is.
        Never modifies `self`."""
        return CorrectionUnderstandingResult(
            status=self.status,
            source_text=self.source_text,
            original_expression=self.original_expression,
            corrected_expression_or_meaning=copy.deepcopy(self.corrected_expression_or_meaning),
            language=self.language,
            locale=self.locale,
            confidence=self.confidence,
        )


def map_correction_understanding_to_result(correction_understanding):
    """Convert a `CorrectionUnderstanding` (Prompt 439) into a
    `CorrectionUnderstandingResult` (Prompt 441). Prompt 442: the one
    small, deterministic mapping between the two - same
    `map_<source>_<to>_<target>` convention already used for
    structured-result-to-structured-result conversion elsewhere in this
    package (see local_model_mapping.py's `map_inference_result`). Pure
    and deterministic - reuses the existing structure's fields exactly
    as they are; never re-detects, re-resolves or invents anything, and
    never touches Learning, Memory, Knowledge, Meaning Resolution,
    Pattern Matching, Response Generation or any storage.

    Preserves: `status`, `original_expression`, `language`, `locale`,
    `source_text`, `confidence` - copied through unchanged, None stays
    None exactly as the source left it (never defaulted or invented
    here; `CorrectionUnderstandingResult.__init__` still applies its own
    existing `confidence=0.0` default only when the caller omits the
    argument entirely, same as any other caller of that constructor).

    `corrected_expression` and `corrected_meaning` are merged into
    `corrected_expression_or_meaning`: the expression wins when both are
    present (matching Prompt 439's own decision order, where a resolved
    correction is never built with a meaningful value on both sides at
    once), otherwise whichever one is not None, otherwise None.
    """
    if not isinstance(correction_understanding, CorrectionUnderstanding):
        raise TypeError(
            "correction_understanding must be a CorrectionUnderstanding "
            "(language_intelligence.correction_understanding."
            "CorrectionUnderstandingResult) instance"
        )

    corrected_expression_or_meaning = (
        correction_understanding.corrected_expression
        if correction_understanding.corrected_expression is not None
        else correction_understanding.corrected_meaning
    )

    return CorrectionUnderstandingResult(
        status=correction_understanding.status,
        source_text=correction_understanding.source_text,
        original_expression=correction_understanding.original_expression,
        corrected_expression_or_meaning=corrected_expression_or_meaning,
        language=correction_understanding.language,
        locale=correction_understanding.locale,
        confidence=correction_understanding.confidence,
    )


def build_correction_understanding_result(correction_understanding):
    """Prompt 441's original name for `map_correction_understanding_to_result()`
    (Prompt 442) - kept as a thin, behavior-identical alias so every
    existing caller keeps working unchanged. New callers should prefer
    `map_correction_understanding_to_result()`, which follows this
    package's naming convention for result-to-result mappings; both
    names do exactly the same thing."""
    return map_correction_understanding_to_result(correction_understanding)
