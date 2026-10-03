"""
Language Intelligence - Correction Learning Input Handoff
========================================================================
Prompt 457. The one small, controlled handoff from a correction-derived
learning input (Prompt 455,
correction_feedback_learning_input_adapter.py) to the project's
EXISTING learning layer, `LanguageLearningStore.learn_item()`
(language_learning_store.py, Prompt 416) - gated by the EXISTING
eligibility check (Prompt 456,
correction_learning_input_eligibility.py).

    CorrectionFeedbackRecord (Prompt 449)
        -> convert_correction_feedback_to_learning_input(...)   (Prompt 455)
        -> is_correction_learning_input_eligible(...)           (Prompt 456)
        -> handoff_correction_learning_input(...)               (THIS module)
        -> LanguageLearningStore.learn_item(...)                (Prompt 416,
                                                                   unchanged)

This module adds NO new learning logic of any kind. It is three steps,
in this exact order, and nothing else:

    1. check the input's EXISTING eligibility
       (`is_correction_learning_input_eligible()`, Prompt 456 -
       imported, never re-implemented or re-derived here);
    2. not eligible -> return `None`, the project's existing
       safe-empty-result convention (the SAME value Prompt 455's own
       adapter already returns for feedback that was never valid, and
       the SAME value `LanguageLearningStore.get_item()` already
       returns for "nothing to give back") - the input never reaches
       `store` at all in this case;
    3. eligible -> call `store.learn_item(**learning_input)` -
       `learn_item()`'s own keyword-argument set IS the learning-input
       structure Prompt 455 built the dict to match in the first
       place, so this is a plain, direct expansion, not a new wrapper
       or adapter object. Whatever `learn_item()` returns (a dict,
       Prompt 416) or raises (`ValueError`/`TypeError` for a
       structurally bad value - the same exceptions it already raises
       for every other caller) is passed straight back, unchanged and
       uncaught. This module invents no new success/failure shape of
       its own for the learning layer's own outcome.

`LanguageLearningStore` remains entirely responsible for what actually
happens to a learned item - matching, inserting, updating, versioning,
episodic history - none of that is touched, re-implemented, or
second-guessed here. This module only decides WHETHER a call happens
and, when it does, passes the input through unchanged.

`store` must be a `LanguageLearningStore` instance (imported from
language_learning_store.py, never re-implemented or subclassed by
this module); an ineligible input's handoff never even inspects
`store`, so this check only runs on the eligible path, when `store`
is actually about to be used.

Nothing is guessed, normalized, translated, or invented here - no
synonym, meaning, relationship, grammar rule, or sentence pattern is
generated, and no new inference, persistence mechanism, or database is
introduced. `learning_input` is never mutated: it is read (via
dict-unpacking) but never written to. No `LearningAnalyzer`,
`CorrectionUnderstanding`, `CorrectionUnderstandingResult`, or
`CorrectionFeedbackRecord` code is touched by this stage; Memory,
Knowledge, Meaning Resolution, Pattern Matching, Response Generation
and the Local Model Runtime are not integrated with here either.
"""

from language_intelligence.correction_learning_input_eligibility import (
    is_correction_learning_input_eligible,
)
from language_intelligence.language_learning_store import LanguageLearningStore


def handoff_correction_learning_input(learning_input, store):
    """Hand `learning_input` (the dict
    `correction_feedback_learning_input_adapter.
    convert_correction_feedback_to_learning_input()` produces) off to
    `store` (an existing `LanguageLearningStore` instance) - but only
    when Prompt 456's `is_correction_learning_input_eligible()` says
    it is eligible.

    Not eligible (including `learning_input` being `None`, exactly
    what Prompt 455's own adapter returns for invalid feedback, or any
    other non-eligible shape) -> returns `None` immediately; `store`
    is never called or even inspected.

    Eligible -> `store` must be a `LanguageLearningStore`
    (`TypeError` otherwise - the same "isinstance check, then raise"
    posture the rest of this correction-feedback pipeline already
    uses), and this function returns exactly
    `store.learn_item(**learning_input)`'s own result. Any exception
    `learn_item()` itself raises (e.g. `ValueError`/`TypeError` for a
    structurally invalid value) propagates unchanged - this module
    adds no new error handling or result convention of its own for
    the learning layer's own outcome.

    Pure and deterministic apart from `learn_item()`'s own existing
    behavior (which may write to `store`'s underlying storage exactly
    as it already does for any other caller - no second storage
    mechanism is introduced here). `learning_input` is never mutated.
    """
    if not is_correction_learning_input_eligible(learning_input):
        return None

    if not isinstance(store, LanguageLearningStore):
        raise TypeError(
            "store must be a LanguageLearningStore (language_intelligence."
            "language_learning_store.LanguageLearningStore) instance"
        )

    return store.learn_item(**learning_input)
