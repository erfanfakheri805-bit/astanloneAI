"""
Language Intelligence - Correction Feedback Learning Input Adapter
========================================================================
Prompt 455. A small, deterministic adapter that converts a valid
`CorrectionFeedbackRecord` (Prompt 449, correction_feedback_record.py)
into the project's EXISTING language-learning input shape - the
keyword-argument set `LanguageLearningStore.learn_item()`
(language_learning_store.py, Prompt 416) already accepts.

This module does not learn anything, store anything, or call
`learn_item()` itself. It only performs one small, pure conversion:

    CorrectionFeedbackRecord
        -> convert_correction_feedback_to_learning_input(...)
        -> a plain dict shaped like learn_item()'s own keyword
           arguments, ready for a *future*, separately-scoped caller to
           pass as `store.learn_item(**learning_input)` - or the
           project's existing empty-result convention (`None`, the
           same value `LanguageLearningStore.get_item()` already
           returns when there is nothing to give back) when the
           record is not valid feedback.

Why `learn_item()`'s own keyword-argument set, and not a new class
-------------------------------------------------------------------
`language_learning_store.py` has exactly one caller-facing "give me a
learning input" shape: the arguments `learn_item(language, item_type,
key, meaning=None, examples=None, relationships=None, confidence=None,
source=None, source_context=None, learning_method=None)` accepts -
`LanguageLearningItem` itself is the STORE'S OWN OUTPUT record (it
carries `item_id`, `version`, `created_at`, `updated_at` - fields only
the store assigns on a successful write, never a caller). Reusing
`learn_item()`'s keyword-argument set is therefore reusing the
existing learning-input structure, not inventing a second one; a
plain dict with exactly those keys is the smallest possible shape that
"already existed", contributes no new schema, and is what a future
caller would already be able to expand straight into `learn_item()`.

Field mapping
-------------
A `CorrectionFeedbackRecord` carries nine fields (see
correction_feedback_record.py). Of those, six have a direct,
same-meaning counterpart among `learn_item()`'s keyword arguments and
are copied through UNCHANGED - never renamed in meaning, never
reinterpreted:

    record.language                    -> language
    record.original_expression         -> key
                                           (the learned text itself -
                                           the same role `key` already
                                           plays for every other
                                           learn_item() caller: "the
                                           learned text, verbatim - a
                                           word, a phrase, or a
                                           sentence-pattern template",
                                           see language_learning_store.py)
    record.corrected_expression_or_meaning -> meaning
                                           (both are documented,
                                           word-for-word, as "an
                                           arbitrary, caller-shaped
                                           JSON-safe value" -
                                           see both modules' own
                                           docstrings - so this is a
                                           direct, same-shape copy,
                                           not a reinterpretation)
    record.confidence                  -> confidence
    record.source                      -> source
    record.source_text                 -> source_context
                                           (both documented as "the
                                           sentence/text/conversation
                                           excerpt this item was
                                           learned from" -
                                           language_learning_store.py's
                                           own `source_context` entry)

`item_type` has no counterpart on `CorrectionFeedbackRecord` at all -
a correction record does not say whether the correction concerns a
word, a phrase, or a pattern. Rather than guess, this module reuses
`language_learning_store.py`'s own documented policy that `item_type`
is "a short, caller-chosen, non-empty label" with "NO new item_type
system" required for a new kind of learned item ("A future learning
module is free to use its own item_type strings ... without this
module changing at all" - language_learning_store.py's own module
docstring). `ITEM_TYPE_CORRECTION` below is exactly that: one more
caller-chosen label, following the identical convention
`ITEM_TYPE_WORD`/`ITEM_TYPE_PHRASE`/`ITEM_TYPE_PATTERN` already use,
added here (not in language_learning_store.py, which is not modified
by this stage) because only this adapter knows its inputs are always
corrections.

Two `CorrectionFeedbackRecord` fields have NO counterpart anywhere in
`learn_item()`'s keyword arguments, and this module does not invent
one for them, per this stage's own instructions ("If the existing
learning structure cannot represent one of the feedback fields, do
not redesign it in this prompt. Simply preserve the information that
the existing structure already supports."):

    record.locale       `learn_item()` has no `locale` parameter -
                         only `language` (itself canonicalized via
                         `language_context.canonical_language`,
                         Prompt 401). Not copied anywhere, not folded
                         into another field, not dropped into
                         `meaning`/`source_context` as a workaround -
                         simply absent from the returned dict, exactly
                         as it is absent from every other
                         `learn_item()` call in this codebase today.
    record.created_at   `learn_item()` has no timestamp parameter -
                         `created_at`/`updated_at` are the STORE'S OWN
                         output fields, assigned only on a successful
                         write (see `LanguageLearningItem` above).
                         Not copied anywhere.

`examples`, `relationships`, and `learning_method` are `learn_item()`
keyword arguments with no matching `CorrectionFeedbackRecord` field
either; this module does not invent values for them (no synonyms, no
relationships, no learning-method guess) - they are simply left out of
the returned dict, exactly the same "None means nothing was given"
default `learn_item()` itself already applies to a caller who omits
them.

Validity rule
-------------
Only a record with `is_valid_feedback is True` is converted -
identical to the rule `CorrectionFeedbackRecord` itself already
derived from `CorrectionUnderstandingResult.status ==
STATUS_RESOLVED` (see correction_feedback_record.py). For an invalid
record (AMBIGUOUS / UNRESOLVED / NOT_CORRECTION, or any other falsy
`is_valid_feedback`), this function returns `None` - the project's
existing safe-empty-result convention already used by
`LanguageLearningStore.get_item()` for "nothing to give back" - rather
than inventing any learning data from feedback that was never
validated.

Nothing is guessed, normalized, translated, resolved into a synonym,
or given a relationship anywhere in this module. The function is pure
and deterministic: the same `CorrectionFeedbackRecord` always produces
the same dict (or the same `None`), the input record is never mutated,
and nothing is stored, learned, or looked up - no `LanguageLearningStore`,
`MemorySystem`, `LearningAnalyzer`, `CorrectionUnderstanding`,
`CorrectionUnderstandingResult`, Knowledge, Meaning Resolution, Pattern
Matching, or Response Generation integration is introduced or touched
by this stage. Calling `learn_item()` with the dict this function
returns is left entirely to a later, separately-scoped prompt.
"""

import copy

from .correction_feedback_record import CorrectionFeedbackRecord

# One more caller-chosen item_type label, following the exact
# convention language_learning_store.py's own ITEM_TYPE_WORD /
# ITEM_TYPE_PHRASE / ITEM_TYPE_PATTERN already use - see the module
# docstring above. language_learning_store.py itself is not modified.
ITEM_TYPE_CORRECTION = "correction"


def convert_correction_feedback_to_learning_input(record):
    """Convert a valid `CorrectionFeedbackRecord` into a plain dict
    shaped like `LanguageLearningStore.learn_item()`'s own keyword
    arguments (see this module's docstring for the exact field
    mapping and what is intentionally left out).

    `record` must be a `CorrectionFeedbackRecord`; anything else
    raises `TypeError` - the same "isinstance check, then raise"
    posture `map_correction_understanding_result_to_feedback_record()`
    (correction_feedback_record.py) already uses for its own input.

    Only a record with `is_valid_feedback is True` is converted. For
    any other record this returns `None` - the project's existing
    empty-result convention (`LanguageLearningStore.get_item()`) -
    rather than inventing learning data from unvalidated feedback.

    Pure and deterministic: `record` is never mutated, and nothing is
    stored, learned, or looked up anywhere by this function.
    `meaning` in the returned dict is a `copy.deepcopy()` of
    `record.corrected_expression_or_meaning` - the same "mutable
    caller-shaped JSON value gets a safe copy" convention
    `CorrectionFeedbackRecord.to_dict()` (Prompt 453) and
    `CorrectionUnderstandingResult.copy()` (Prompt 448) already apply
    to this identical field - so the returned dict shares no mutable
    state with `record`.
    """
    if not isinstance(record, CorrectionFeedbackRecord):
        raise TypeError(
            "record must be a CorrectionFeedbackRecord (language_intelligence."
            "correction_feedback_record.CorrectionFeedbackRecord) instance"
        )

    if not record.is_valid_feedback:
        return None

    return {
        "language": record.language,
        "item_type": ITEM_TYPE_CORRECTION,
        "key": record.original_expression,
        "meaning": copy.deepcopy(record.corrected_expression_or_meaning),
        "confidence": record.confidence,
        "source": record.source,
        "source_context": record.source_text,
    }
