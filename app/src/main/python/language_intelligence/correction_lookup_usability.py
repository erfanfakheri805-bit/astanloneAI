"""
Language Intelligence - Correction Lookup Context Usability
========================================================================
Prompt 468. A small, deterministic usability check over the EXISTING
Prompt 465 `CorrectionLookupContext`
(correction_lookup_context.py). This module answers exactly one
question - "does this already-built lookup context contain at least
one stored correction record that is actually usable?" - and nothing
else. It does not perform a lookup, does not choose or rank among
several usable records, does not apply a correction, and does not
generate any response text.

    build_correction_lookup_context(...)   (Prompt 465, unchanged)
        -> CorrectionLookupContext
    is_correction_lookup_context_usable(...)   (THIS module)
        -> True / False

Why a plain boolean, not a new result class
--------------------------------------------
Same reasoning Prompt 456's `correction_learning_input_eligibility.py`
already documents for its own, structurally identical question: this
is a single, small, deterministic fact about an already-built object,
not a new structure with a status and an issues list to maintain.
`is_correction_lookup_context_usable()` is the entire answer this
stage needs.

What "usable" means
---------------------
A `CorrectionLookupContext` is usable only when ALL of the following
hold:

    - `status` is `FOUND` (`correction_learning_exact_lookup_result.
      STATUS_FOUND`, imported here, never redefined) - `NOT_FOUND` and
      `FAILED` are never usable, regardless of what `records` happens
      to contain.
    - at least one entry in `records` is itself a usable stored
      correction record (see below) - an empty `records` list is
      never usable.

A stored record (one entry of `records` - the SAME dict shape
`LanguageLearningStore.learn_item()` / `get_item()` already return,
unchanged since Prompt 463/464 - see correction_lookup_context.py's
own module docstring) is usable only when it is a dict and BOTH of
the following, the required correction information this project's
existing correction-learning structures already define, are present
and non-blank (`correction_understanding._is_blank()`, imported,
never re-implemented - the SAME "nothing supplied" rule
`correction_learning_input_eligibility.py` already applies to this
identical pair of fields before they ever become a learning input):

    - `key`      the original expression that was corrected
    - `meaning`  the corrected expression or meaning

Nothing else about a record (`language`, `confidence`, `source`,
`source_context`, `id`, `version`, timestamps, ...) is inspected -
this check answers only "is there a usable correction here", not
"which one" or "how good".

Multiple records, never a selection
-------------------------------------
When more than one record is present, EVERY one is checked and the
context is usable as soon as ANY one of them qualifies
(`any(...)` - short-circuits, never ranks, scores, merges, or picks a
"best" record). Which record(s) actually qualify is not reported here
and not decided here - a future, separately-scoped stage that
actually reads/applies a correction is the one that would pick among
them, not this module.

Pure, deterministic, non-mutating
------------------------------------
`is_correction_lookup_context_usable()` only reads `context.status`
and `context.records` (and each record's `key`/`meaning`) - it never
sets, appends, or otherwise mutates `context`, any record dict inside
`context.records`, or anything else. The same `CorrectionLookupContext`
always produces the same boolean.

Not yet connected
--------------------
This module does not touch `ResponseGenerationContext`
(response_generation_context.py, Prompt 467), `LanguageUnderstandingResult`
(Prompt 466), correction detection, `CorrectionUnderstanding`,
`CorrectionUnderstandingResult`, `LearningAnalyzer`, Memory, Knowledge,
Response Generation, or the Local Model Runtime; it adds no new
persistence, no new database, no ranking/scoring/fuzzy/semantic
matching, no inference, and makes no network/API call. It does not
modify `CorrectionLookupContext`, `build_correction_lookup_context()`,
or anything upstream of them - a thin, read-only check over an object
that already exists.
"""

from language_intelligence.correction_lookup_context import CorrectionLookupContext
from language_intelligence.correction_learning_exact_lookup_result import STATUS_FOUND
from language_intelligence.correction_understanding import _is_blank


def _is_usable_record(record):
    """True only when `record` is a dict carrying BOTH required pieces
    of correction information (`key`, `meaning`), each non-blank - see
    the module docstring. Never raises for a malformed record; an
    unusable record simply returns False. Never mutates `record`."""
    if not isinstance(record, dict):
        return False
    if _is_blank(record.get("key")):
        return False
    if _is_blank(record.get("meaning")):
        return False
    return True


def is_correction_lookup_context_usable(context):
    """True only when `context` (a `CorrectionLookupContext` -
    required; `TypeError` otherwise, the SAME "isinstance check, then
    raise" posture `build_correction_lookup_context()` already uses)
    has `status == STATUS_FOUND` AND at least one entry in `records`
    is a usable stored correction record (see the module docstring for
    exactly what that means).

    `NOT_FOUND` and `FAILED` are always False. An empty `records` list
    is always False. A record missing `key` and/or `meaning` does not
    count, but does not disqualify any OTHER record in the same
    context - several usable records simply make this True without
    picking one.

    Pure and deterministic; never mutates `context` or anything inside
    it; never applies, chooses, ranks, or generates anything - purely
    informational, exactly like Prompt 466's own `CorrectionLookupContext`
    and Prompt 467's carry-through into `ResponseGenerationContext`.
    """
    if not isinstance(context, CorrectionLookupContext):
        raise TypeError(
            "context must be a CorrectionLookupContext "
            "(language_intelligence.correction_lookup_context."
            "CorrectionLookupContext) instance"
        )

    if context.status != STATUS_FOUND:
        return False

    return any(_is_usable_record(record) for record in context.records)
