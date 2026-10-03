"""
Language Intelligence - Correction Learning Handoff Result
========================================================================
Prompt 458. A small, structured outcome for the EXISTING correction
learning handoff operation (Prompt 457,
`correction_learning_input_handoff.handoff_correction_learning_input()`).
This module adds no new learning logic, no new eligibility rule, and
no new learning-layer behavior - it only names, as one small result
object, the outcome that handoff already produces today:

    handoff_correction_learning_input(learning_input, store)
        -> ineligible input           -> returns None            (Prompt 456/457, unchanged)
        -> eligible, store.learn_item() succeeds -> returns a dict (Prompt 416, unchanged)
        -> eligible, store.learn_item() raises   -> raises ValueError/TypeError (Prompt 416, unchanged)

`handoff_correction_learning_input_with_result()` (THIS module) calls
that EXACT function - never re-implementing eligibility or the
learn_item() call - and reports which of those three outcomes
happened as a `CorrectionLearningHandoffResult`:

    ACCEPTED  - the eligible learning input was successfully handed
                to the existing learning layer (handoff returned a
                dict).
    REJECTED  - the input was not eligible, so it was never handed
                off (handoff returned `None`).
    FAILED    - the input was eligible, but the existing
                learning-layer handoff failed (handoff raised
                `ValueError`/`TypeError` - the SAME exceptions
                `LanguageLearningStore.learn_item()` already raises
                for every other caller; see `handoff_correction_
                learning_input()`'s own docstring).

`handoff_correction_learning_input()` ITSELF is not modified in any
way - it keeps returning `None`/a dict, or raising, exactly as Prompt
457 left it, so every existing caller and every existing test of that
function keeps working unchanged. This module only adds a second,
optional entry point for callers that want the outcome as a small
structured result instead of a return-value-or-raise; it is a thin
wrapper, not a replacement.

`accepted` is a boolean, always consistent with `status`
(`status == STATUS_ACCEPTED`) - never set independently.

`source` identifies the source of the learning input. This handoff
path exists ONLY for correction-derived learning input (Prompt 455's
adapter always builds it from a `CorrectionFeedbackRecord` whose
`source` is the project's existing `SOURCE_USER_CORRECTION` constant -
see correction_feedback_record.py, Prompt 451), so `source` is always
that same, reused constant - imported here, never re-implemented or
re-derived from the (possibly missing, for a rejected input)
`learning_input` dict.

`reason` carries an EXISTING failure/rejection reason only when one is
already available, and nothing is invented for it here:

    ACCEPTED -> no failure occurred; `reason` is `None`.
    REJECTED -> `is_correction_learning_input_eligible()` (Prompt 456)
                reports ineligibility as a plain boolean only, with no
                reason text of its own; since none exists to reuse,
                `reason` is `None` rather than a guessed explanation.
    FAILED   -> the existing exception's own message (`str(exc)`,
                Prompt 416's own `ValueError`/`TypeError` text) is
                reused verbatim as `reason` - the exact, already-
                available text the learning layer itself raised, not
                a new explanation authored here.

This module does not touch `LearningAnalyzer`, correction detection,
`CorrectionUnderstanding`, `CorrectionUnderstandingResult`, or
`CorrectionFeedbackRecord`; it does not add Memory, Knowledge, Meaning
Resolution, Pattern Matching, or Response Generation integration; it
does not modify the Local Model Runtime; it adds no database or
persistent storage, no automatic learning algorithm, and no new
inference, meaning, synonym, relationship, or grammar-rule generation.
It is a small, deterministic, read-only wrapper over an outcome that
already exists.
"""

from language_intelligence.correction_feedback_record import (
    SOURCE_USER_CORRECTION,
)
from language_intelligence.correction_learning_input_handoff import (
    handoff_correction_learning_input,
)

STATUS_ACCEPTED = "ACCEPTED"
STATUS_REJECTED = "REJECTED"
STATUS_FAILED = "FAILED"
ALL_STATUSES = (STATUS_ACCEPTED, STATUS_REJECTED, STATUS_FAILED)


class CorrectionLearningHandoffResult:
    """The minimum useful fields describing one correction-learning
    handoff attempt's outcome - nothing more.

        status    - one of ALL_STATUSES (ACCEPTED / REJECTED / FAILED).
        accepted  - bool; always `status == STATUS_ACCEPTED`, never set
                    independently of `status`.
        source    - always `SOURCE_USER_CORRECTION` (Prompt 451's
                    existing constant, reused/imported, never
                    re-implemented) - this handoff path exists only
                    for correction-derived learning input.
        reason    - an EXISTING failure/rejection reason, reused
                    verbatim, when one is already available (only for
                    `STATUS_FAILED` today - see module docstring);
                    `None` otherwise. Never an invented explanation.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior of its own beyond `to_dict()`.
    """

    __slots__ = ("status", "accepted", "source", "reason")

    def __init__(self, status, reason=None):
        if status not in ALL_STATUSES:
            raise ValueError(
                "status must be one of %r, got %r" % (ALL_STATUSES, status)
            )
        self.status = status
        self.accepted = status == STATUS_ACCEPTED
        self.source = SOURCE_USER_CORRECTION
        self.reason = reason

    def to_dict(self):
        """This result as a plain, JSON-shaped dict - the same
        "small, JSON-shaped" convention this project's other result
        objects already follow (e.g. `CorrectionFeedbackRecord`)."""
        return {
            "status": self.status,
            "accepted": self.accepted,
            "source": self.source,
            "reason": self.reason,
        }

    def __eq__(self, other):
        if not isinstance(other, CorrectionLearningHandoffResult):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "CorrectionLearningHandoffResult(%r)" % (self.to_dict(),)


def handoff_correction_learning_input_with_result(learning_input, store):
    """Attempt the EXISTING correction learning handoff
    (`handoff_correction_learning_input()`, Prompt 457 - called here
    exactly as any other caller would call it, never re-implemented)
    and report the outcome as a `CorrectionLearningHandoffResult`
    instead of a return-value-or-raise:

        - `handoff_correction_learning_input()` returns `None`
          (the input was not eligible - Prompt 456's EXISTING check,
          reused via that call, decided this) -> `STATUS_REJECTED`,
          `reason=None`.
        - it returns a dict (the eligible input was handed to
          `LanguageLearningStore.learn_item()`, Prompt 416, and that
          call succeeded) -> `STATUS_ACCEPTED`, `reason=None`.
        - it raises `ValueError` or `TypeError` (the eligible input's
          handoff to the existing learning layer failed - the SAME
          exceptions `learn_item()`/`handoff_correction_learning_
          input()` already raise for every other caller, per their
          own docstrings) -> `STATUS_FAILED`, `reason=str(exc)` (the
          exception's own, already-existing message, reused
          verbatim).

    Any other exception is not one of this pipeline's documented
    outcomes and propagates unchanged, exactly as it would from a
    direct call to `handoff_correction_learning_input()` - this
    wrapper invents no handling for it.

    Pure aside from `handoff_correction_learning_input()`'s own
    existing side effects (which may write to `store`'s underlying
    storage exactly as before - no second storage mechanism is
    introduced here). `learning_input` is never mutated by this
    function itself.
    """
    try:
        outcome = handoff_correction_learning_input(learning_input, store)
    except (ValueError, TypeError) as exc:
        return CorrectionLearningHandoffResult(STATUS_FAILED, reason=str(exc))

    if outcome is None:
        return CorrectionLearningHandoffResult(STATUS_REJECTED)

    return CorrectionLearningHandoffResult(STATUS_ACCEPTED)
