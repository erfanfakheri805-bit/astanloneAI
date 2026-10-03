"""
Language Intelligence - Correction Learning Input Eligibility
========================================================================
Prompt 456. A small, deterministic eligibility check over the learning
input dict Prompt 455's adapter produces
(`correction_feedback_learning_input_adapter.py`:
`convert_correction_feedback_to_learning_input()`).

This module answers exactly one question - "is this already-built
learning input eligible to be handed to the learning system?" - and
nothing else. It does not build a learning input, does not call
`LanguageLearningStore.learn_item()`, does not learn or store
anything, and does not touch `LearningAnalyzer`,
`CorrectionUnderstanding`, `CorrectionUnderstandingResult`, or
`CorrectionFeedbackRecord` (all of those stay exactly as Prompt 455
left them).

Why a plain boolean, not a new result class
--------------------------------------------
`CorrectionFeedbackRecordValidation`
(correction_feedback_record_validation.py, Prompt 450) already exists
as this project's "wrap the value, report issues, never mutate"
convention - but it validates the STRUCTURE of a
`CorrectionFeedbackRecord`, a different object from the plain dict
Prompt 455 produces. Building a second `...Validation` class here,
just to hold a status and an issues list for a four-field dict, would
be the "second validation framework" this stage is explicitly told
not to create. A single, small, deterministic boolean is the entire
answer this stage needs; `is_correction_learning_input_eligible()`
is that boolean, computed by reusing existing helpers rather than
re-implementing their checks.

What is inspected
------------------
ONLY fields already present in the learning input dict itself - see
`correction_feedback_learning_input_adapter.py`'s own field-mapping
table for exactly what that dict can contain
(`language`, `item_type`, `key`, `meaning`, `confidence`, `source`,
`source_context`). Nothing outside that dict is read, and nothing
about it is re-derived from a `CorrectionFeedbackRecord`,
`CorrectionUnderstandingResult`, or any other source.

    "represents valid user correction feedback"
        Prompt 455's adapter already enforces this at the point the
        input is built: it returns `None` for any
        `CorrectionFeedbackRecord` with `is_valid_feedback` not
        `True`, and a dict only for one that does (see that module's
        own docstring). So `learning_input is None` - or anything
        else that is not a dict - IS "not valid correction feedback"
        for this stage; this check does not re-derive or second-guess
        that decision, it simply requires a dict to have been
        produced at all.
    "the original expression is present"
        `learning_input["key"]` (Prompt 455's mapping of
        `original_expression`) must be non-blank - reuses
        `correction_understanding.py`'s own `_is_blank()`, the exact
        same "nothing supplied" check
        `correction_feedback_record_validation.py` already applies to
        this identical piece of information before it becomes a
        learning input.
    "the corrected expression or meaning is present"
        `learning_input["meaning"]` (Prompt 455's mapping of
        `corrected_expression_or_meaning`) must be non-blank - same
        `_is_blank()` reuse.
    "the required language information is present according to the
    existing learning structure"
        `learning_input["language"]` must be non-blank text AND name
        a real language/locale under
        `language_context.canonical_language()` - reusing that
        function (imported, never re-implemented) is reusing the
        EXACT rule `language_learning_store._resolve_language()`
        already enforces for every other `learn_item()` caller today
        ("Raises ValueError for anything that names no real
        language/locale (None, '', 'unknown', ...)" - see that
        function's own docstring). This check mirrors that rule
        without raising, since an ineligible input is an ordinary,
        expected outcome here, not an error.

Nothing is inferred, normalized, translated, or filled in anywhere in
this module: a missing/blank field simply makes the input ineligible,
it is never guessed or defaulted. The function is pure and
deterministic - the same learning input always produces the same
boolean - and never mutates the dict it is given.
"""

from language_intelligence.correction_understanding import _is_blank
from language_intelligence.language_context import canonical_language


def _is_real_language(value):
    """Same rule `language_learning_store._resolve_language()` already
    enforces (imported `canonical_language`, never re-implemented):
    non-blank text that names an actual language/locale. Never raises -
    an ineligible input is a normal outcome here, not an error."""
    if _is_blank(value) or not isinstance(value, str):
        return False
    return canonical_language(value) is not None


def is_correction_learning_input_eligible(learning_input):
    """True only when `learning_input` (the dict
    `correction_feedback_learning_input_adapter.
    convert_correction_feedback_to_learning_input()` returns) is
    eligible to be passed to the learning system:

        - it is a dict at all (Prompt 455's adapter returns `None`
          for feedback that was not valid correction feedback - see
          this module's own docstring);
        - `key` (the original expression) is present and non-blank;
        - `meaning` (the corrected expression or meaning) is present
          and non-blank;
        - `language` is present and names a real language/locale, the
          same requirement `language_learning_store.py`'s own
          `learn_item()` already enforces.

    Pure and deterministic; never mutates `learning_input`; never
    raises for a malformed or incomplete input - an ineligible input
    simply returns `False`.
    """
    if not isinstance(learning_input, dict):
        return False

    if _is_blank(learning_input.get("key")):
        return False

    if _is_blank(learning_input.get("meaning")):
        return False

    if not _is_real_language(learning_input.get("language")):
        return False

    return True
