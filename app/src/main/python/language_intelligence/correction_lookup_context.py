"""
Language Intelligence - Correction Lookup Decision Context
========================================================================
Prompt 465. A small, deterministic, READ-ONLY context object built
ONLY from the EXISTING structured exact lookup result (Prompt 464,
`correction_learning_exact_lookup_result.
CorrectionLearningExactLookupResult` /
`lookup_correction_learning_input_by_original_expression_with_result()`).

This module adds no new lookup logic, no new matching, and no new
inference of any kind - it takes an already-built
`CorrectionLearningExactLookupResult` and copies its pieces into one
small, read-only `CorrectionLookupContext`, the SAME "wrap an existing
result as a small, flatter, read-only structure" posture
`correction_understanding_result.py` (Prompt 441/448) already uses for
`CorrectionUnderstanding` -> `CorrectionUnderstandingResult`.

    lookup_correction_learning_input_by_original_expression_with_result(...)
        (Prompt 464, unchanged)
        -> CorrectionLearningExactLookupResult (status, original_expression,
           records, reason)
    build_correction_lookup_context(...)   (THIS module)
        -> CorrectionLookupContext

Prompt 465 is explicitly NOT wired into the language-understanding
flow or any conversation pipeline yet - nothing in this module calls
itself automatically, and nothing elsewhere is changed to call it.
That connection, if it ever happens, is a separate, future, explicitly
scoped step.

Fields (only these seven; nothing else is carried)
----------------------------------------------------
    status                copied through unchanged from the lookup
                           result (`FOUND` / `NOT_FOUND` / `FAILED` -
                           `correction_learning_exact_lookup_result`'s
                           own `ALL_STATUSES`, imported here, never
                           redefined).
    original_expression   copied through unchanged - the expression
                           that was looked up, so a `NOT_FOUND`/
                           `FAILED` context still says what was
                           searched for.
    records                every matching stored correction record,
                           deep-copied from the lookup result's own
                           `records` list, in that SAME existing
                           order - never ranked, scored, merged, or
                           reduced to one, and never re-sorted (Prompt
                           463's/464's own existing storage order is
                           preserved exactly). `[]` for `NOT_FOUND` and
                           `FAILED`.
    language               `records[0]["language"]` when there is
                           EXACTLY ONE matching record (the one case
                           where a single language is already,
                           unambiguously, available without picking
                           among several) - `None` otherwise (zero
                           records, or more than one record, possibly
                           spanning different languages; choosing one
                           of several would be a selection this module
                           does not make - see `records` above).
    locale                 always `None`. `locale` was never part of
                           the stored correction-learning shape in the
                           first place (Prompt 455's own documented
                           decision, carried unchanged through Prompts
                           460-464); this context does not invent a
                           place for it either.
    source                 `records[0]["source"]` when there is
                           EXACTLY ONE matching record - the SAME
                           "only when unambiguous" rule `language`
                           uses, and for the SAME reason. `None`
                           otherwise.
    reason                 the lookup result's own `reason`, copied
                           through unchanged - only ever non-`None` for
                           `FAILED` (Prompt 464's own convention); this
                           module invents no new failure text.

Not-found / failed representation
----------------------------------
`NOT_FOUND` -> `records=[]`, `language=None`, `locale=None`,
`source=None`, `reason=None` - a context that unambiguously represents
"no correction was found" (see `has_match` below), never a guessed or
invented correction.

`FAILED` -> `records=[]`, `language=None`, `locale=None`,
`source=None`, `reason=<the lookup's own existing reason>` - the
failure state is preserved exactly as the lookup reported it; no
correction is invented in its place.

Read-only from the caller's perspective
-----------------------------------------
`CorrectionLookupContext` uses `__slots__` (no dynamic attributes) and
exposes no setters. `records` is deep-copied at construction time (the
SAME `copy.deepcopy()` convention `CorrectionUnderstandingResult.copy()`
(Prompt 448) already uses for its own mutable field) - mutating the
`CorrectionLearningExactLookupResult` (or its `records` list) the
context was built from afterwards never changes the context, and
mutating a dict inside `context.records` never reaches back into the
lookup result or the underlying store. `to_dict()` also returns a
fresh, independent structure (`records` deep-copied again) on every
call, the SAME "never hand back shared mutable state" posture already
used throughout this package.

This module does not touch `LearningAnalyzer`, correction detection,
`CorrectionUnderstanding`, `CorrectionUnderstandingResult`,
`CorrectionFeedbackRecord`, the language-understanding flow, response
generation, or the Local Model Runtime; it adds no Memory or Knowledge
integration, no new persistence or database, no ranking/scoring/
fuzzy/semantic matching or spelling correction, and makes no
network/API call. It does not modify
`lookup_correction_learning_input_by_original_expression_with_result()`,
`CorrectionLearningExactLookupResult`, or anything upstream of it - a
thin, read-only wrapper over a result that already exists.
"""

import copy

from language_intelligence.correction_learning_exact_lookup_result import (
    CorrectionLearningExactLookupResult,
    STATUS_FOUND, STATUS_NOT_FOUND, STATUS_FAILED, ALL_STATUSES,
)


class CorrectionLookupContext:
    """The minimum useful fields describing one exact correction
    lookup's outcome, as a small, read-only context - nothing more.
    See the module docstring for the exact meaning of each field.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior beyond `to_dict()`, `copy()`, and the read-only `has_match`
    property.
    """

    __slots__ = (
        "status", "original_expression", "records",
        "language", "locale", "source", "reason",
    )

    def __init__(self, status, original_expression, records=None,
                 language=None, locale=None, source=None, reason=None):
        if status not in ALL_STATUSES:
            raise ValueError(
                "status must be one of %r, got %r" % (ALL_STATUSES, status)
            )
        self.status = status
        self.original_expression = original_expression
        self.records = copy.deepcopy(list(records)) if records else []
        self.language = language
        self.locale = locale
        self.source = source
        self.reason = reason

    @property
    def has_match(self):
        """True only when `status` is `FOUND` and at least one record
        is present - the SAME `is_*`-style read-only status helper
        convention `CorrectionUnderstandingResult.is_resolved` (Prompt
        445) already uses. `NOT_FOUND` and `FAILED` are always
        `False`, so a caller can check "was a correction found?"
        without inspecting `status` or `records` directly."""
        return self.status == STATUS_FOUND and bool(self.records)

    def to_dict(self):
        """This context as a plain, JSON-shaped dict - the same
        `to_dict()` convention used throughout this package. `records`
        is deep-copied again here, so mutating the returned dict never
        reaches back into this context."""
        return {
            "status": self.status,
            "original_expression": self.original_expression,
            "records": copy.deepcopy(self.records),
            "language": self.language,
            "locale": self.locale,
            "source": self.source,
            "reason": self.reason,
        }

    def copy(self):
        """Return a new, independent `CorrectionLookupContext` with
        the same seven fields (`self.copy() == self`). `records` (the
        one field that can carry mutable, caller-shaped values) is
        deep-copied again; every other field is an already-immutable
        value passed through as-is - the SAME convention
        `CorrectionUnderstandingResult.copy()` (Prompt 448) already
        follows. Never mutates `self`."""
        return CorrectionLookupContext(
            status=self.status,
            original_expression=self.original_expression,
            records=copy.deepcopy(self.records),
            language=self.language,
            locale=self.locale,
            source=self.source,
            reason=self.reason,
        )

    def __eq__(self, other):
        if not isinstance(other, CorrectionLookupContext):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "CorrectionLookupContext(%r)" % (self.to_dict(),)


def build_correction_lookup_context(lookup_result):
    """Build a `CorrectionLookupContext` from an EXISTING
    `CorrectionLearningExactLookupResult` (Prompt 464 - required;
    `TypeError` otherwise, the SAME "isinstance check, then raise"
    posture the rest of this package already uses).

    `status`, `original_expression`, `records`, and `reason` are
    copied straight through, unchanged (`records` deep-copied - see
    the module/class docstrings for why). `language` and `source` are
    taken from `records[0]` ONLY when there is exactly one record -
    zero records (`NOT_FOUND`/`FAILED`) or more than one (several
    exact matches, possibly in different languages) leave both `None`
    rather than guessing or picking one; `locale` is always `None`
    (never part of the underlying stored shape - see module
    docstring).

    Pure and deterministic: the same `CorrectionLearningExactLookupResult`
    always produces an equal context, and nothing is mutated, stored,
    looked up, or connected to the conversation pipeline here.
    """
    if not isinstance(lookup_result, CorrectionLearningExactLookupResult):
        raise TypeError(
            "lookup_result must be a CorrectionLearningExactLookupResult "
            "(language_intelligence.correction_learning_exact_lookup_result."
            "CorrectionLearningExactLookupResult) instance"
        )

    records = lookup_result.records
    if len(records) == 1:
        language = records[0].get("language")
        source = records[0].get("source")
    else:
        language = None
        source = None

    return CorrectionLookupContext(
        status=lookup_result.status,
        original_expression=lookup_result.original_expression,
        records=records,
        language=language,
        locale=None,
        source=source,
        reason=lookup_result.reason,
    )
