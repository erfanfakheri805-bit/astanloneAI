"""
Language Intelligence - Correction Learning Handoff -> Learning Input
========================================================================
Prompt 460. A small, deterministic adapter that converts an ACCEPTED
`CorrectionLearningHandoffResult` (Prompt 458,
correction_learning_handoff_result.py) back into the project's
EXISTING language-learning input structure - the same plain dict
`correction_feedback_learning_input_adapter.
convert_correction_feedback_to_learning_input()` (Prompt 455) already
builds, and the same shape `LanguageLearningStore.learn_item()`
(Prompt 416) already accepts as keyword arguments.

Why this needs both the result AND the original learning input
------------------------------------------------------------------------
`CorrectionLearningHandoffResult` (Prompt 458) carries only four
fields - `status`, `accepted`, `source`, `reason` - it does not carry
`key`, `meaning`, `language`, `item_type`, `confidence`, or
`source_context`. Those live on the learning input dict that was
ALREADY BUILT by Prompt 455's adapter and ALREADY PASSED to
`handoff_correction_learning_input_with_result()` (Prompt 458) by the
caller in the first place - the "original correction information
already available through the existing correction-feedback flow" this
stage is asked to preserve. So this adapter takes both:

    CorrectionFeedbackRecord (Prompt 449)
        -> convert_correction_feedback_to_learning_input(...)      (Prompt 455) -> learning_input
        -> handoff_correction_learning_input_with_result(          (Prompt 458)
               learning_input, store)                                -> handoff_result
        -> convert_accepted_correction_handoff_to_learning_input(  (THIS module)
               handoff_result, learning_input)
        -> learning_input, unchanged - or None

and returns the SAME `learning_input` dict (a deep copy of it) when
`handoff_result` is a structurally valid, `ACCEPTED`
`CorrectionLearningHandoffResult` - or the project's existing
empty-result convention (`None`, the SAME value Prompt 455's own
adapter and `LanguageLearningStore.get_item()` already return for
"nothing to give back") for anything else.

This is a plain, direct pass-through, not a new learning-input model:
reusing Prompt 455's own dict shape (rather than inventing a second
"learning input" class) is exactly what requirement 5 of this stage
asks for. No new field is added, renamed, or reinterpreted - `key`,
`meaning`, `language`, `item_type`, `confidence`, `source`, and
`source_context` are all copied through exactly as they already were.
`language` (Prompt 455's own copy of the record's `language`) is
preserved exactly like every other field; `locale` was never part of
this dict in the first place (Prompt 455's own module docstring: "Not
copied anywhere, not folded into another field, not dropped into
`meaning`/`source_context` as a workaround") and this module does not
invent a place for it either - nothing is guessed or added beyond what
`learning_input` already carries.

Gating rules
------------
    - `handoff_result` must be a structurally VALID
      `CorrectionLearningHandoffResult` - checked by REUSING Prompt
      459's own `validate_correction_learning_handoff_result()`
      (imported, never re-implemented) - and its `status` must be
      `STATUS_ACCEPTED` (imported from correction_learning_handoff_
      result.py, never redefined). Anything else - `REJECTED`,
      `FAILED`, a structurally INVALID result, or a value that is not
      even a `CorrectionLearningHandoffResult` - returns `None`
      immediately; `learning_input` is never inspected or returned in
      that case.
    - `learning_input` must be a dict (the shape Prompt 455's adapter
      produces) once `handoff_result` clears the check above; any
      other value returns `None` rather than inventing a learning
      input from nothing.

This module performs no actual learning: it never calls
`LanguageLearningStore.learn_item()`, `handoff_correction_learning_
input()`, or `handoff_correction_learning_input_with_result()`, and
writes to no database or persistent storage of any kind. It does not
touch `LearningAnalyzer`, correction detection, `CorrectionUnderstanding`,
`CorrectionUnderstandingResult`, or `CorrectionFeedbackRecord`; it adds
no Memory, Knowledge, Meaning Resolution, Pattern Matching, or Response
Generation integration; it does not modify the Local Model Runtime or
perform any network/API call. Pure and deterministic: the same
`(handoff_result, learning_input)` pair always produces the same
result; neither argument is ever mutated (the returned dict, when one
is returned, is a `copy.deepcopy()` of `learning_input` - the same
"mutable caller-shaped JSON value gets a safe copy" convention Prompt
455's own adapter already applies to `meaning`).
"""

import copy

from language_intelligence.correction_learning_handoff_result import (
    STATUS_ACCEPTED,
)
from language_intelligence.correction_learning_handoff_result_validation import (
    validate_correction_learning_handoff_result,
)


def convert_accepted_correction_handoff_to_learning_input(handoff_result, learning_input):
    """Convert an ACCEPTED `CorrectionLearningHandoffResult` back into
    the existing learning-input dict it was built from.

    Returns a `copy.deepcopy()` of `learning_input` - never the same
    object - when `handoff_result` is a structurally valid (Prompt
    459's `validate_correction_learning_handoff_result()`, reused
    unchanged) `CorrectionLearningHandoffResult` whose `status` is
    `STATUS_ACCEPTED`, AND `learning_input` is a dict.

    Returns `None` - the project's existing empty-result convention -
    for a `REJECTED` or `FAILED` result, a structurally invalid
    result, a value that is not a `CorrectionLearningHandoffResult`
    at all, or a `learning_input` that is not a dict. Neither argument
    is mutated; no learning happens here.
    """
    validation = validate_correction_learning_handoff_result(handoff_result)
    if not validation.valid:
        return None

    if handoff_result.status != STATUS_ACCEPTED:
        return None

    if not isinstance(learning_input, dict):
        return None

    return copy.deepcopy(learning_input)
