"""
Language Intelligence - Correction Retrieval Trigger (Prompt 566)
========================================================================
Prompt 566. A small, deterministic decision layer that answers exactly
one question a normal user message needs answered before Prompt 565's
retrieval chain (`correction_retrieval_understanding_adapter.py`) is
ever called: "should correction retrieval be attempted for this
message at all?" This module decides that question ONLY - it never
performs the retrieval itself.

Audit: what existing signal was found
--------------------------------------
Prompt 563's own audit
(diagnostics/section2_correction_retrieval_application_audit_prompt563.py,
finding `no_trigger_exists_for_when_to_look_up_a_stored_correction`)
and Prompt 565's own doc
(docs/section2_correction_retrieval_to_understanding_connection_prompt565.md,
section 6) both already concluded that nothing in `core/core.py`,
`understanding/`, or `language_intelligence/` decides *when* an
ordinary message's expression should be checked against previously
stored corrections. Re-inspection for this prompt confirms that
conclusion still holds, with one refinement:

The ONLY existing, deterministic signal anywhere in this codebase that
identifies a specific expression as "correction-relevant" *without*
touching the correction-learning store is Prompt 439/440's own
existing chain - `understanding/correction_detection.py`'s ONE fixed,
explicit marker (`"not <original>, i mean/meant <corrected>"`) feeding
`correction_understanding.build_correction_understanding()`, exposed
as `LanguageUnderstandingResult.correction_understanding` (a
`CorrectionUnderstandingResult.to_dict()`, or `None` when the message
did not match that one fixed marker at all).

This module reuses that EXACT existing signal - no new natural-
language detector, keyword list, or heuristic is added anywhere in
this file. Per section 3's instruction to "use existing correction
signals first," and because that signal only ever fires on the one
explicit, unambiguous marker Prompt 440 already recognizes, it is safe
to reuse as the retrieval trigger's own input.

What was missing, and the smallest thing added to cover it
-------------------------------------------------------------
`CorrectionUnderstandingResult` already tells a caller whether the
CURRENT message names a correction-relevant expression, and how
completely. It does not, by itself, say "retrieval should be
attempted" - that decision (which statuses count, and how
conservative to be about the ones that don't) did not exist anywhere
before this prompt. This module is exactly that smallest missing
piece: a fixed, table-driven mapping from
`CorrectionUnderstandingResult.status` to a boolean decision, plus the
one piece of minimal lookup information (`original_expression`,
`language`) a future retrieval call would need - nothing else is
invented, computed, or inferred.

Decision table (fixed; no scoring, no guessing)
--------------------------------------------------
    RESOLVED        -> ATTEMPT.   The existing pipeline fully
                       identified BOTH an original expression and a
                       corrected expression/meaning from the one fixed
                       explicit marker - the strongest, least
                       ambiguous signal this codebase produces. Its
                       `original_expression` is exposed as this
                       trigger's own minimal lookup information.
    AMBIGUOUS       -> DO NOT ATTEMPT. More than one corrected
                       candidate was present and nothing picked one;
                       reused conservatively, not resolved here.
    UNRESOLVED      -> DO NOT ATTEMPT. Only part of a correction was
                       identified (e.g. an original expression with no
                       corrected form) - not enough evidence per
                       Prompt 566's own safety rule.
    NOT_CORRECTION  -> DO NOT ATTEMPT. Nothing correction-related was
                       identified in the message at all.
    None (no candidate at all - the ordinary case for almost every
    message, including generic conversational phrases such as
    "I mean this is interesting.", "What do you mean?",
    "I meant to ask you something.", "Actually, tell me about dogs.",
    or "No, that's not what I asked" that do not match the one fixed
    marker) -> DO NOT ATTEMPT. This is why those examples never
    trigger retrieval: they never produce a `CorrectionUnderstanding`
    candidate in the first place, so this module never even sees a
    correction-relevant signal for them.

Why this stays conservative
-------------------------------
Only the single, unambiguous RESOLVED case attempts retrieval. Every
other outcome - including a message that merely LOOKS correction-
shaped (AMBIGUOUS, UNRESOLVED) - stays conservative, exactly as
Prompt 566 section 4 requires. No generic conversational phrase can
ever reach a non-`None` status here, because
`understanding/correction_detection.py` only recognizes the one fixed
marker; nothing in this module loosens that.

What this module deliberately does NOT do
------------------------------------------
- retrieve anything from the correction-learning store
- call any of Prompt 464/465/469/470/565's retrieval/selection/
  candidate/adapter functions
- modify memory, the database, or the user's input
- generate a replacement expression or apply any correction
- decide AMBIGUOUS/UNRESOLVED cases by guessing or scoring
- duplicate `correction_detection.py` or
  `correction_understanding.py`'s own logic - it only reads their
  already-computed output

Contract (only these four fields; nothing else is carried)
---------------------------------------------------------------
    should_attempt        `True` only for the RESOLVED case described
                           above; `False` for every other case.
    reason                one of the REASON_* constants below -
                           always explains why, never omitted.
    original_expression   the minimal lookup information a future
                           retrieval call would need - copied through
                           unchanged from the existing
                           `CorrectionUnderstandingResult` ONLY when
                           `should_attempt` is `True`; `None`
                           otherwise (nothing to look up).
    language               same rule as `original_expression` - copied
                           through unchanged only when `should_attempt`
                           is `True`; `None` otherwise.

Zero retrieval/storage side effects
---------------------------------------
`build_correction_retrieval_trigger()` performs no I/O, no database
access, no store lookup, and no import of anything from the
correction-retrieval chain (`correction_learning_exact_lookup_result`,
`correction_lookup_context`, `correction_lookup_selection`,
`correction_application_candidate`,
`correction_retrieval_understanding_adapter`) - this file imports only
the existing `CorrectionUnderstandingResult`/status constants it reads
from, nothing that can reach storage. Pure and deterministic: the same
input always produces an equal (`==`) trigger.

Not called from anywhere else in this codebase
-----------------------------------------------
Nothing in `core/core.py`, `language_intelligence_core.py`, any
backend, or `correction_retrieval_understanding_adapter.py` calls this
module. This prompt establishes only the decision boundary; connecting
it to Prompt 565's adapter (calling
`retrieve_and_attach_correction_application_candidate()` only when
`trigger.should_attempt` is `True`, using `trigger.original_expression`
and `trigger.language`) is the next, separately-scoped stage.
"""

from language_intelligence.correction_understanding import (
    CorrectionUnderstandingResult,
    STATUS_RESOLVED,
    STATUS_AMBIGUOUS,
    STATUS_UNRESOLVED,
    STATUS_NOT_CORRECTION,
)

REASON_RESOLVED_CORRECTION_IDENTIFIED = "resolved_correction_identified"
REASON_NO_CORRECTION_SIGNAL = "no_correction_signal"
REASON_AMBIGUOUS_CORRECTION = "correction_understanding_ambiguous"
REASON_UNRESOLVED_CORRECTION = "correction_understanding_unresolved"
REASON_NOT_CORRECTION = "correction_understanding_not_correction"
REASON_INVALID_INPUT = "invalid_correction_understanding_input"

ALL_REASONS = (
    REASON_RESOLVED_CORRECTION_IDENTIFIED,
    REASON_NO_CORRECTION_SIGNAL,
    REASON_AMBIGUOUS_CORRECTION,
    REASON_UNRESOLVED_CORRECTION,
    REASON_NOT_CORRECTION,
    REASON_INVALID_INPUT,
)

_STATUS_TO_REASON = {
    STATUS_AMBIGUOUS: REASON_AMBIGUOUS_CORRECTION,
    STATUS_UNRESOLVED: REASON_UNRESOLVED_CORRECTION,
    STATUS_NOT_CORRECTION: REASON_NOT_CORRECTION,
}


class CorrectionRetrievalTrigger:
    """The minimum useful fields describing one correction-retrieval
    trigger decision - nothing more. See the module docstring for the
    exact meaning of each field.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior beyond `to_dict()` and `copy()`. Never retrieves, stores,
    or applies anything - see the module docstring.
    """

    __slots__ = ("should_attempt", "reason", "original_expression", "language")

    def __init__(self, should_attempt, reason, original_expression=None, language=None):
        if reason not in ALL_REASONS:
            raise ValueError(f"invalid reason: {reason!r}")
        self.should_attempt = bool(should_attempt)
        self.reason = reason
        self.original_expression = original_expression
        self.language = language

    def to_dict(self):
        """This trigger as a plain, JSON-shaped dict - the same
        `to_dict()` convention used throughout this package."""
        return {
            "should_attempt": self.should_attempt,
            "reason": self.reason,
            "original_expression": self.original_expression,
            "language": self.language,
        }

    def copy(self):
        """Return a new, independent `CorrectionRetrievalTrigger` with
        the same four fields (`self.copy() == self`). Never mutates
        `self`."""
        return CorrectionRetrievalTrigger(
            should_attempt=self.should_attempt,
            reason=self.reason,
            original_expression=self.original_expression,
            language=self.language,
        )

    def __eq__(self, other):
        if not isinstance(other, CorrectionRetrievalTrigger):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "CorrectionRetrievalTrigger(%r)" % (self.to_dict(),)


def _as_status_dict(correction_understanding):
    """Normalize the accepted input shapes - `None`, a plain dict (the
    SAME shape `LanguageUnderstandingResult.correction_understanding`
    already carries, i.e. `CorrectionUnderstandingResult.to_dict()`),
    or a `CorrectionUnderstandingResult` instance itself - into a
    plain dict, or `None` for "no signal at all". Raises `TypeError`
    for any other input shape, the SAME "isinstance check, then raise"
    posture the rest of this package already uses. Never mutates its
    argument."""
    if correction_understanding is None:
        return None
    if isinstance(correction_understanding, CorrectionUnderstandingResult):
        return correction_understanding.to_dict()
    if isinstance(correction_understanding, dict):
        return correction_understanding
    raise TypeError(
        "correction_understanding must be None, a dict (as produced by "
        "CorrectionUnderstandingResult.to_dict()), or a "
        "CorrectionUnderstandingResult instance"
    )


def build_correction_retrieval_trigger(correction_understanding):
    """Build a `CorrectionRetrievalTrigger` from the EXISTING Prompt
    439/440 `CorrectionUnderstandingResult` (or its `.to_dict()` shape
    - the SAME value `LanguageUnderstandingResult.correction_understanding`
    already carries), or `None` when the current message produced no
    correction candidate at all (the ordinary case for almost every
    message).

    Performs no retrieval, no lookup, no storage access, and no
    natural-language detection of its own - see the module docstring
    for the fixed decision table this function applies. Never guesses:
    an unrecognized/malformed `status` inside a dict is treated the
    same as "no usable signal" (conservative `should_attempt=False`,
    `REASON_INVALID_INPUT`) rather than raising, the SAME "malformed
    input is treated like absent input" posture
    `deterministic_fallback_backend._build_correction_understanding()`
    already uses for a malformed correction candidate.

    Pure and deterministic: the same `correction_understanding` value
    always produces an equal (`==`) trigger, and nothing is mutated,
    stored, retrieved, or applied by this function.
    """
    status_dict = _as_status_dict(correction_understanding)

    if status_dict is None:
        return CorrectionRetrievalTrigger(
            should_attempt=False, reason=REASON_NO_CORRECTION_SIGNAL)

    status = status_dict.get("status")

    if status == STATUS_RESOLVED:
        original_expression = status_dict.get("original_expression")
        if not isinstance(original_expression, str) or not original_expression.strip():
            # RESOLVED without a usable original_expression should not
            # happen given how build_correction_understanding() works
            # (RESOLVED always sets it) - defensive, conservative
            # fallback rather than attempting a lookup with nothing to
            # look up.
            return CorrectionRetrievalTrigger(
                should_attempt=False, reason=REASON_INVALID_INPUT)
        return CorrectionRetrievalTrigger(
            should_attempt=True,
            reason=REASON_RESOLVED_CORRECTION_IDENTIFIED,
            original_expression=original_expression,
            language=status_dict.get("language"),
        )

    reason = _STATUS_TO_REASON.get(status)
    if reason is None:
        # status is missing, or is not one of the four ALL_STATUSES
        # values CorrectionUnderstandingResult ever produces - treat
        # exactly like "no usable signal", never raise.
        reason = REASON_INVALID_INPUT

    return CorrectionRetrievalTrigger(should_attempt=False, reason=reason)
