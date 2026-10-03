"""
Language Intelligence - Correction Application Candidate Eligibility
========================================================================
Prompt 569. A small, deterministic, READ-ONLY eligibility decision over
the EXISTING Prompt 470 `CorrectionApplicationCandidate`
(correction_application_candidate.py) - the SAME candidate object that
now flows, end to end, through the verified Section 2 pipeline:

    CorrectionUnderstanding                                (Prompt 439/440)
        -> CorrectionRetrievalTrigger                       (Prompt 566)
        -> Existing Retrieval Adapter                       (Prompt 565)
        -> CorrectionApplicationCandidate                   (Prompt 470)
        -> LanguageUnderstandingResult                       (Prompt 564)
        -> ResponseGenerationContext                        (Prompt 471/568)

Prompt 568 stopped this pipeline deliberately short of any correction
*application*. This module answers exactly one further question -
"is this already-attached candidate eligible to be considered by a
later, separately-scoped application stage?" - and nothing else. It
does not apply the correction, does not replace any text, does not
generate response text, does not perform fuzzy or semantic matching,
does not perform inference, does not rank candidates, does not create
new learning, and does not write to storage.

Reusing the existing guarantee, not duplicating it
----------------------------------------------------
Prompt 472's `correction_application_candidate_readiness.
is_correction_application_candidate_ready()` already answers this
EXACT question for this EXACT class - see that module's own docstring:
"does this already-built candidate contain enough valid information
for a future, separately-scoped correction-application step to use?"
That is, word for word, the eligibility question this prompt asks.
Prompt 472's check was built and tested against
`CorrectionApplicationCandidate` before the Section 2 retrieval
pipeline (Prompts 561-568) existed, but it was never re-derived or
narrowed to any particular candidate source - it inspects only the
candidate's own four fields (`is_valid`, `original_expression`,
`corrected_expression_or_meaning`, `language`), which are exactly the
fields `build_correction_application_candidate()` (Prompt 470, still
the SAME constructor the Section 2 pipeline's own
`build_correction_application_candidate_from_store()` calls) populates
regardless of which caller triggered it. So the guarantee already
exists for this pipeline's own candidate, and this module reuses it
rather than re-implementing any of its checks
(`_is_blank`/`canonical_language`, both still imported only inside
`correction_application_candidate_readiness.py`, never duplicated
here).

This module therefore adds NO new candidate-content validation of its
own. Its only original logic is distinguishing three cases a plain
readiness boolean does not itself distinguish - "no candidate was
attached at all" (`None`, the ordinary Prompt 564 default for a
non-correction message), "the value given is not a candidate at all"
(a defensive, conservative case), and "a real candidate was attached
but is not ready" - so a later stage can log or reason about *why* a
decision came out ineligible without re-deriving that from the
candidate's fields itself.

    build_correction_application_candidate(...)          (Prompt 470, unchanged)
        -> CorrectionApplicationCandidate
    is_correction_application_candidate_ready(...)        (Prompt 472, unchanged)
        -> True / False
    evaluate_correction_application_candidate_eligibility(...)  (THIS module)
        -> CorrectionApplicationCandidateEligibility

Fields (only these two; nothing else is carried)
----------------------------------------------------
    eligible    `True` only when `candidate` is a
                `CorrectionApplicationCandidate` instance AND
                `is_correction_application_candidate_ready(candidate)`
                is `True`. `False` otherwise.
    reason      one of four fixed, deterministic string constants
                (see below) explaining `eligible` - never free text,
                never derived from candidate content, never a new
                natural-language heuristic.

        REASON_ELIGIBLE = "candidate_ready"
            `eligible=True` - the candidate is a real,
            `CorrectionApplicationCandidate` that Prompt 472's
            readiness check reports as ready.
        REASON_NO_CANDIDATE = "no_candidate"
            `candidate is None` - the ordinary case for a message with
            no attached correction candidate (Prompt 564's own
            default, and Prompt 566/567's own conservative behavior
            for AMBIGUOUS/UNRESOLVED correction understanding, which
            never attaches a candidate in the first place).
        REASON_INVALID_CANDIDATE = "invalid_candidate"
            `candidate` is neither `None` nor a
            `CorrectionApplicationCandidate` instance - a defensive,
            conservative case; this function never raises for it.
        REASON_CANDIDATE_NOT_READY = "candidate_not_ready"
            `candidate` is a real `CorrectionApplicationCandidate` but
            `is_correction_application_candidate_ready(candidate)` is
            `False` (e.g. `is_valid=False`, because the originating
            selection was AMBIGUOUS/NOT_FOUND/FAILED, or a required
            field is missing/blank, or `language` names no real
            language/locale - see Prompt 472's own docstring for the
            exact rule this module does not repeat).

Why a small decision object here, and not another plain boolean
-------------------------------------------------------------------
Every other eligibility/readiness/usability check already documented
in this package (`correction_learning_input_eligibility.py`, Prompt
456; `correction_lookup_usability.py`, Prompt 468;
`correction_application_candidate_readiness.py`, Prompt 472) is a
plain boolean, and each one explains why: a single fact about an
already-built object needs no status-plus-issues structure. This
module keeps that same posture for the underlying validation (it adds
none), but the later application stage this prompt exists for needs to
tell "no candidate was ever attached" apart from "a candidate was
attached but rejected" without importing and re-deriving that from
`correction_application_candidate_readiness.py` itself - so the
smallest useful addition here is a two-field, immutable value (not a
new validation framework, not a new class hierarchy) that packages the
SAME boolean Prompt 472 already computes together with which of the
four fixed cases above produced it.

Never applies anything
-------------------------
`evaluate_correction_application_candidate_eligibility()` and
`CorrectionApplicationCandidateEligibility` never apply the
correction, never modify the user's message, never modify generated
response text, never modify any stored learning record, never write
to storage, never touch Memory, Knowledge, the Learning algorithms,
Response Generation, Language Understanding, or the Local Model
Runtime, and never perform fuzzy/semantic matching, ranking, scoring,
or inference. Producing this decision is the entire operation -
deciding whether or how to use an eligible candidate is a separate,
future, explicitly scoped step.

Read-only and non-mutating
-----------------------------
This module only reads `candidate` itself (via `isinstance` and the
imported, unmodified `is_correction_application_candidate_ready()`) -
it never sets, appends, or otherwise mutates `candidate`,
`LanguageUnderstandingResult`, `ResponseGenerationContext`, or
anything upstream of them. The same candidate (by value) always
produces an equal decision (pure and deterministic).

Zero storage, zero retrieval
--------------------------------
This module performs no database access, no store lookup, and no
correction-learning retrieval of any kind - it does not import
`correction_learning_input_storage.py`,
`correction_learning_input_retrieval.py`,
`correction_lookup_selection.py`,
`correction_retrieval_understanding_adapter.py`, or
`correction_retrieval_trigger.py`. Evaluating eligibility operates
entirely on the already-produced candidate passed in; for one
response-generation operation, this stage adds no additional
retrieval path.

Not yet connected
--------------------
This module does not modify `CorrectionApplicationCandidate`,
`build_correction_application_candidate()`,
`is_correction_application_candidate_ready()`,
`LanguageUnderstandingResult`, `ResponseGenerationContext`,
`Core._attach_correction_application_candidate()`, or any correction-
application/apply/guarded/verification module. It is not called from
anywhere else in this codebase - dependency-injection surface only,
held ready for whichever future, separately-scoped prompt implements
actual correction application.
"""

from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate,
)
from language_intelligence.correction_application_candidate_readiness import (
    is_correction_application_candidate_ready,
)

REASON_ELIGIBLE = "candidate_ready"
REASON_NO_CANDIDATE = "no_candidate"
REASON_INVALID_CANDIDATE = "invalid_candidate"
REASON_CANDIDATE_NOT_READY = "candidate_not_ready"


class CorrectionApplicationCandidateEligibility:
    """The minimum useful information describing one eligibility
    decision over a `CorrectionApplicationCandidate` - nothing more.
    See the module docstring for the exact meaning of each field.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior beyond `to_dict()`. Never applies anything - see the
    module docstring.
    """

    __slots__ = ("eligible", "reason")

    def __init__(self, eligible, reason):
        self.eligible = bool(eligible)
        self.reason = reason

    def to_dict(self):
        """This decision as a plain, JSON-shaped dict - the same
        `to_dict()` convention used throughout this package."""
        return {"eligible": self.eligible, "reason": self.reason}

    def __eq__(self, other):
        if not isinstance(other, CorrectionApplicationCandidateEligibility):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "CorrectionApplicationCandidateEligibility(%r)" % (self.to_dict(),)


def evaluate_correction_application_candidate_eligibility(candidate):
    """Return a `CorrectionApplicationCandidateEligibility` describing
    whether `candidate` is eligible to be considered by a later,
    separately-scoped correction-application stage.

    All candidate-content validation is delegated, unchanged, to
    Prompt 472's `is_correction_application_candidate_ready()` - see
    the module docstring for why this function adds no validation of
    its own. This function only distinguishes `candidate is None`
    (`REASON_NO_CANDIDATE`) and "not a `CorrectionApplicationCandidate`
    at all" (`REASON_INVALID_CANDIDATE`) from an actual candidate that
    readiness accepts (`REASON_ELIGIBLE`) or rejects
    (`REASON_CANDIDATE_NOT_READY`).

    Pure, deterministic, and read-only: never mutates `candidate`,
    never applies anything, never raises, never performs storage or
    retrieval access - an ineligible input simply produces an
    ineligible decision.
    """
    if candidate is None:
        return CorrectionApplicationCandidateEligibility(
            eligible=False, reason=REASON_NO_CANDIDATE)

    if not isinstance(candidate, CorrectionApplicationCandidate):
        return CorrectionApplicationCandidateEligibility(
            eligible=False, reason=REASON_INVALID_CANDIDATE)

    if not is_correction_application_candidate_ready(candidate):
        return CorrectionApplicationCandidateEligibility(
            eligible=False, reason=REASON_CANDIDATE_NOT_READY)

    return CorrectionApplicationCandidateEligibility(
        eligible=True, reason=REASON_ELIGIBLE)
