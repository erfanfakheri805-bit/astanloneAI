"""
Language Intelligence - Correction Feedback Record
========================================================================
Prompt 449. A small, deterministic record built ONLY from the existing
`CorrectionUnderstandingResult` (Prompt 441,
correction_understanding_result.py). It represents one explicit
correction, shaped so it can later be consumed by the learning system -
but this module does not connect to Learning, Memory, Knowledge,
Meaning Resolution, Pattern Matching or Response Generation, and adds
no storage of any kind.

This module does not detect, parse, re-resolve or infer anything, and
does not add a second correction system. It takes an already-built
`CorrectionUnderstandingResult` and copies its pieces into one small,
JSON-shaped feedback record, plus one deterministic boolean
(`is_valid_feedback`) derived from that result's existing `status`.

Fields (originally seven; Prompt 451 added an eighth, `source`; Prompt
452 adds a ninth, `created_at` - see below)
----------------------------------------------------
    original_expression              copied through, unchanged
    corrected_expression_or_meaning  copied through, unchanged
    language                         copied through, unchanged
    locale                           copied through, unchanged
    source_text                      copied through, unchanged
    confidence                       copied through, unchanged
    is_valid_feedback                True only when the source result's
                                       `status` is STATUS_RESOLVED
                                       (imported from
                                       correction_understanding.py -
                                       never redefined here); False for
                                       AMBIGUOUS, UNRESOLVED and
                                       NOT_CORRECTION.

Nothing is guessed, normalized, translated or invented - every field
other than `is_valid_feedback` is a straight copy of the matching
attribute already present on the `CorrectionUnderstandingResult`.

`map_correction_understanding_result_to_feedback_record()` is pure and
deterministic: the same `CorrectionUnderstandingResult` always produces
the same record, and nothing is mutated, stored or looked up anywhere.

Prompt 451 adds one more field, `source` - a small, deterministic
identifier for where a `CorrectionFeedbackRecord` came from. For this
stage there is exactly one valid value, `SOURCE_USER_CORRECTION`
("USER_CORRECTION"), exposed alongside `ALL_SOURCES` - the same
`STATUS_*` / `ALL_STATUSES` module-level string-constant convention
`correction_understanding.py` already uses, applied here to `source`
instead of `status`. A record built from a `CorrectionUnderstandingResult`
via `map_correction_understanding_result_to_feedback_record()` always
gets `source=SOURCE_USER_CORRECTION` - the only kind of correction
feedback this stage knows how to produce. `__init__` validates `source`
against `ALL_SOURCES` exactly the way `CorrectionUnderstandingResult.__init__`
already validates its own `status` argument (`correction_understanding_result.py`):
an unrecognized value raises `ValueError` at construction time. No new
source system or registry is introduced, and no other source type is
added - `ALL_SOURCES` holds exactly one value for this stage.

Prompt 452 adds one more field, `created_at` - when the record was
created. This reuses the project's existing timestamp convention
already found throughout the codebase (e.g. `planning/plan.py`,
`planning/goal.py`, `financial/revenue_task.py`,
`language_intelligence/language_learning_store.py`): an ISO 8601
string in UTC, produced by a module-level `_now_iso()` helper built on
`datetime.now(timezone.utc).isoformat()`, defaulted at construction
time when not supplied (`created_at=None` -> `_now_iso()`), stored
as-is, and included in `to_dict()`. No new time/date framework is
introduced. `map_correction_understanding_result_to_feedback_record()`
lets `created_at` default the same way - the only non-deterministic
part of an otherwise pure, deterministic conversion. This stage adds
only a creation timestamp - no update timestamp, no expiration, no
history and no retention logic of any kind.

Prompt 453 hardens the existing `to_dict()` (introduced with this
class in Prompt 449) rather than adding a new operation: it already
returned all nine current fields, but did not yet apply this
project's existing "mutable fields get a safe copy" convention to
`corrected_expression_or_meaning` - the one field on this record that
can carry a mutable, caller-shaped JSON value. `to_dict()` now returns
a `copy.deepcopy()` of that field, the same convention
`CorrectionUnderstandingResult.copy()` already applies to its own
identical field (Prompt 448). Every other field is always a plain
immutable value and is passed through unchanged, exactly as before.
`to_dict()` remains pure and deterministic: it never mutates `self`,
and the same record always produces an equal (but independent) dict.
No new serialization framework, database, file-writing, or Learning /
Memory / Knowledge / Meaning Resolution / Pattern Matching / Response
Generation integration is introduced by this stage.

Prompt 454 adds the matching deserialization operation, `from_dict()`
(a classmethod), so a `CorrectionFeedbackRecord` can be rebuilt from
the dict `to_dict()` produces. It is a thin wrapper around `__init__`
itself: required fields are taken as given (a `data` missing one
raises `TypeError` from `__init__`'s own required-argument check -
nothing is invented or defaulted for them), optional fields (`source`,
`created_at`) fall back to `__init__`'s own existing defaults when
absent, and an unrecognized `source` still raises `ValueError` exactly
as direct construction already does. `corrected_expression_or_meaning`
is deep-copied out of the input dict before construction - the same
`copy.deepcopy()` convention `to_dict()` and
`CorrectionUnderstandingResult.copy()` already use for this identical
mutable field - so the new record shares no mutable state with the
dict it was read from. `data` itself is never mutated. No new
serialization framework, database, file I/O, or Learning / Memory /
Knowledge / Meaning Resolution / Pattern Matching / Response
Generation integration is introduced by this stage.
"""

import copy
from datetime import datetime, timezone

from language_intelligence.correction_understanding_result import (
    CorrectionUnderstandingResult,
)

SOURCE_USER_CORRECTION = "USER_CORRECTION"
ALL_SOURCES = (SOURCE_USER_CORRECTION,)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class CorrectionFeedbackRecord:
    """Plain, read-only, JSON-shaped record of one explicit correction -
    same `to_dict()` convention used throughout this package. Never
    constructed from raw text; built only from an already-built
    `CorrectionUnderstandingResult` (see
    `map_correction_understanding_result_to_feedback_record()` below).
    """

    def __init__(self, original_expression, corrected_expression_or_meaning,
                 language, locale, source_text, confidence, is_valid_feedback,
                 source=SOURCE_USER_CORRECTION, created_at=None):
        if source not in ALL_SOURCES:
            raise ValueError(f"invalid source: {source!r}")
        self.original_expression = original_expression
        self.corrected_expression_or_meaning = corrected_expression_or_meaning
        self.language = language
        self.locale = locale
        self.source_text = source_text
        self.confidence = confidence
        self.is_valid_feedback = bool(is_valid_feedback)
        self.source = source
        self.created_at = created_at if created_at is not None else _now_iso()

    def to_dict(self):
        """Plain, JSON-shaped dictionary with all nine current fields
        (Prompt 453). Every field other than `corrected_expression_or_meaning`
        is always a plain immutable value (`str`/`float`/`bool`/`None`)
        and is passed through as-is - the same "no unnecessary copying
        of immutable values" posture `CorrectionUnderstandingResult.copy()`
        already follows for its own plain fields.
        `corrected_expression_or_meaning` is the one field that can
        carry a mutable, caller-shaped JSON value (documented in
        `correction_understanding.py` as "any caller-shaped JSON
        value"), so - same as `CorrectionUnderstandingResult.copy()`'s
        own `copy.deepcopy()` convention for that identical field - it
        is returned as a `copy.deepcopy()`. This means the returned
        dict never shares mutable state with this record: mutating a
        nested structure inside the returned dict can never affect
        `self`, and calling `to_dict()` never modifies `self`."""
        return {
            "original_expression": self.original_expression,
            "corrected_expression_or_meaning": copy.deepcopy(
                self.corrected_expression_or_meaning),
            "language": self.language,
            "locale": self.locale,
            "source_text": self.source_text,
            "confidence": self.confidence,
            "is_valid_feedback": self.is_valid_feedback,
            "source": self.source,
            "created_at": self.created_at,
        }

    def __repr__(self):
        return (
            f"CorrectionFeedbackRecord(is_valid_feedback={self.is_valid_feedback!r}, "
            f"source={self.source!r}, "
            f"created_at={self.created_at!r}, "
            f"original_expression={self.original_expression!r}, "
            f"corrected_expression_or_meaning={self.corrected_expression_or_meaning!r})"
        )

    @classmethod
    def from_dict(cls, data):
        """Reconstruct a `CorrectionFeedbackRecord` from a plain dict
        shaped like `to_dict()`'s output (Prompt 454). This is the
        `__init__`/keyword-argument convention already used elsewhere
        in this package for reconstructing a record from its own
        `to_dict()` (see `tests/test_correction_feedback_record_timestamp.py`'s
        `CorrectionFeedbackRecord(**record.to_dict())`), promoted to a
        small classmethod rather than left to every caller to repeat.

        `data` must be a dict; anything else raises `TypeError` - same
        "isinstance check, then raise" posture already used by
        `map_correction_understanding_result_to_feedback_record()`
        above. `data` is never mutated (a local copy is read from).

        Required fields (`original_expression`,
        `corrected_expression_or_meaning`, `language`, `locale`,
        `source_text`, `confidence`, `is_valid_feedback`) are taken
        exactly as given - a `data` missing one of them raises
        `TypeError` from `__init__` itself (Python's own "missing
        required argument" behavior), the same way any other caller
        omitting a required constructor argument would fail today.
        Nothing is silently invented or defaulted for these fields.

        Optional fields (`source`, `created_at`) fall back to
        `__init__`'s own existing defaults
        (`source=SOURCE_USER_CORRECTION`, `created_at=None` ->
        `_now_iso()`) when absent from `data` - the same defaulting
        `__init__` already applies to a direct caller who omits them;
        nothing new is invented here. An unrecognized `source` still
        raises `ValueError` from `__init__` exactly as it does for
        direct construction (Prompt 451) - `from_dict()` adds no
        separate validation of its own.

        `corrected_expression_or_meaning` is the one field that can
        carry a mutable, caller-shaped JSON value, so - same
        `copy.deepcopy()` convention `to_dict()` (Prompt 453) and
        `CorrectionUnderstandingResult.copy()` (Prompt 448) already
        apply to this identical field - it is deep-copied out of
        `data` before being handed to `__init__`. This means the new
        record never shares mutable state with the dict it was built
        from, in either direction: mutating `data` afterward, or
        mutating the record, can never affect the other.
        """
        if not isinstance(data, dict):
            raise TypeError(
                "CorrectionFeedbackRecord.from_dict requires a dict, got "
                f"{type(data).__name__!r}"
            )
        kwargs = dict(data)
        if "corrected_expression_or_meaning" in kwargs:
            kwargs["corrected_expression_or_meaning"] = copy.deepcopy(
                kwargs["corrected_expression_or_meaning"])
        return cls(**kwargs)


def map_correction_understanding_result_to_feedback_record(
        correction_understanding_result, created_at=None):
    """Convert a `CorrectionUnderstandingResult` (Prompt 441) into a
    `CorrectionFeedbackRecord` (Prompt 449). Pure and deterministic
    apart from obtaining the creation timestamp - reuses the existing
    result's fields and its existing `status` exactly as they are;
    never re-detects, re-resolves or invents anything, and never
    touches Learning, Memory, Knowledge, Meaning Resolution, Pattern
    Matching, Response Generation or any storage.

    Preserves: `original_expression`, `corrected_expression_or_meaning`,
    `language`, `locale`, `source_text`, `confidence` - copied through
    unchanged, None stays None exactly as the source left it (never
    defaulted or invented here).

    `is_valid_feedback` is True only when
    `correction_understanding_result.status == STATUS_RESOLVED`; it is
    False for AMBIGUOUS, UNRESOLVED and NOT_CORRECTION. Reuses the
    result's existing `is_resolved` property (Prompt 445) rather than
    re-implementing the status check.

    `source` is always `SOURCE_USER_CORRECTION` (Prompt 451): a record
    built this way - from an explicit `CorrectionUnderstandingResult` -
    always identifies itself as coming from the user's own correction,
    the only source this stage knows about.

    `created_at` (Prompt 452) defaults to the current time (project's
    existing `_now_iso()` convention) when not supplied. An explicit
    `created_at` can be passed for deterministic tests or callers that
    already have a timestamp; this is purely additive and does not
    change behavior for any existing caller that omits it.
    """
    if not isinstance(correction_understanding_result, CorrectionUnderstandingResult):
        raise TypeError(
            "correction_understanding_result must be a "
            "CorrectionUnderstandingResult (language_intelligence."
            "correction_understanding_result.CorrectionUnderstandingResult) instance"
        )

    return CorrectionFeedbackRecord(
        original_expression=correction_understanding_result.original_expression,
        corrected_expression_or_meaning=(
            correction_understanding_result.corrected_expression_or_meaning
        ),
        language=correction_understanding_result.language,
        locale=correction_understanding_result.locale,
        source_text=correction_understanding_result.source_text,
        confidence=correction_understanding_result.confidence,
        is_valid_feedback=correction_understanding_result.is_resolved,
        source=SOURCE_USER_CORRECTION,
        created_at=created_at,
    )
