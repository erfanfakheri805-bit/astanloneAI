"""
Language Intelligence - Apply Correction Application Candidate
========================================================================
Prompt 570. A small, deterministic, PURE operation that connects
Prompt 569's eligibility boundary
(`correction_application_candidate_eligibility.
evaluate_correction_application_candidate_eligibility()`) to the
EXISTING, already-complete correction-application chain built by
Prompts 473-477 - `build_correction_application_request()`,
`apply_correction_request_with_validation()` - so that a candidate can
be safely offered to that existing chain WITHOUT ever bypassing
eligibility and WITHOUT ever raising for a `None`, malformed, or
not-ready candidate.

    evaluate_correction_application_candidate_eligibility(candidate)
                                                        (Prompt 569, unchanged)
        -> CorrectionApplicationCandidateEligibility
    build_correction_application_request(candidate)     (Prompt 473, unchanged)
        -> CorrectionApplicationRequest
    apply_correction_request_with_validation(request, target_text)
                                                        (Prompt 477, unchanged)
        -> CorrectionApplicationResult
    apply_correction_application_candidate(candidate, target_text)
                                                        (THIS module)
        -> CorrectionApplicationResult

Why this module exists at all
----------------------------------
Auditing the project (see docs/section2_correction_application_operation_prompt570.md
for the full inventory) found that a complete, deterministic,
exact-match-only correction-application pipeline already exists and
was already fully built by Prompts 473-484 - it was simply never
connected to Prompt 569's candidate-level eligibility decision, and
never callable directly from a `CorrectionApplicationCandidate`
without risking a `TypeError`:
`build_correction_application_request()` (Prompt 473) raises
`TypeError` for anything that is not already a
`CorrectionApplicationCandidate` instance, which is the right contract
for ITS caller (a caller that already knows it has a real candidate),
but is the wrong contract for a candidate that may be `None` or
malformed - exactly the cases Prompt 570 requires a deterministic,
non-raising, non-applicable result for instead.

This module adds NO new correction-application logic, NO new matching
rule, NO new result shape, and NO new validation - every actual
decision is still made by Prompt 569's eligibility function or by the
existing Prompt 473/477 chain, unmodified. Its only original
contribution is the thin `None`/eligibility dispatch in front of that
existing chain.

Behavior
---------
    1. `candidate` is evaluated with the EXISTING, unmodified
       `evaluate_correction_application_candidate_eligibility()`
       (Prompt 569) - this is the single source of truth for whether
       `candidate` may be considered at all. This function never
       inspects `candidate`'s own fields directly to make that
       decision itself, and never bypasses this check.

    2. NOT eligible (`eligible is False` - covers `candidate is None`,
       `candidate` not a `CorrectionApplicationCandidate`, and a real
       but not-ready candidate; see Prompt 569's own `REASON_*`
       constants) - a deterministic `CorrectionApplicationResult`
       (Prompt 474/478/479, existing, unmodified) is returned:
       `status=STATUS_FAILED`, `original_text` set to `target_text`
       when it is already a string (else `None` - the SAME rule every
       `FAILED` outcome elsewhere in this package already uses),
       `corrected_text` left `None`, and `reason` set to the
       eligibility decision's own `reason` verbatim (never an invented
       explanation) - `build_correction_application_request()` is
       never called in this branch, so its `TypeError` for a
       non-candidate is never reached.

    3. Eligible (`eligible is True`) - `candidate` is by construction
       already a real, ready `CorrectionApplicationCandidate`, so
       `build_correction_application_request(candidate)` (Prompt 473,
       unchanged) cannot raise here; its result is passed, together
       with `target_text`, straight to
       `apply_correction_request_with_validation()` (Prompt 477,
       unchanged) and that result is returned exactly as produced -
       `APPLIED`, `NOT_APPLIED`, or `FAILED`, with `matched_text`/
       `replacement_text`/`match_count`/`text_before`/`text_after`
       already populated by that existing, unmodified chain. See
       correction_application.py, correction_application_target_
       validation.py, correction_application_guarded.py, and
       correction_application_verification.py for the exact rules
       this delegates to.

Preserves exact correction semantics
-----------------------------------------
No fuzzy matching, similarity scoring, embeddings, semantic matching,
spelling correction, case normalization, or guessing is introduced
here or anywhere in the chain this delegates to - only the EXISTING
exact, literal, case-sensitive substring behavior
`apply_correction_request()` (Prompt 475) already defines. This module
never performs substring replacement itself; it only decides whether
`candidate` may be handed to the existing operation that does.

Minimal result contract - reused, not duplicated
------------------------------------------------------
`CorrectionApplicationResult` (Prompt 474/478/479) already distinguishes
application possible (`status=APPLIED`, `applied=True`) from not
possible (`NOT_APPLIED`/`FAILED`, `applied=False`), already carries the
original expression (`matched_text`/`text_before`/`original_text`) and
corrected expression (`replacement_text`/`text_after`/`corrected_text`)
exactly as given, and already carries a `reason` for every non-applied
outcome. No new result type is created here.

Pure, deterministic, and side-effect free
----------------------------------------------
This function performs no database or storage access, no correction
retrieval, no correction selection, and no ranking - it calls exactly
one of `evaluate_correction_application_candidate_eligibility()` or
(`build_correction_application_request()` then
`apply_correction_request_with_validation()`), all of which already
guarantee the same. It never mutates `candidate`, `target_text` (an
immutable `str` when it is one), `LanguageUnderstandingResult`, or
`ResponseGenerationContext`. The same `candidate` and `target_text`
always produce an equal result.

Never generates a response, never changes user-visible output
--------------------------------------------------------------------
Producing a `CorrectionApplicationResult` is the entire operation. It
does not modify `ResponseGenerationContext`, does not modify
generated response text, does not call Response Generation, and is not
connected to `Core`, `generate_language_response()`,
`generate_response()`, or any conversation-handling path - see the
docs report for why automatic invocation remains disabled. A future,
separately-scoped prompt decides when and how this operation's result
is actually used.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed. Every function this module
calls (`evaluate_correction_application_candidate_eligibility()`,
`build_correction_application_request()`,
`apply_correction_request_with_validation()`) is reused exactly as it
already exists.
"""

from language_intelligence.correction_application_candidate_eligibility import (
    evaluate_correction_application_candidate_eligibility,
)
from language_intelligence.correction_application_request import (
    build_correction_application_request,
)
from language_intelligence.correction_application_guarded import (
    apply_correction_request_with_validation,
)
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult,
    STATUS_FAILED,
)


def apply_correction_application_candidate(candidate, target_text):
    """Apply `candidate` (a `CorrectionApplicationCandidate`, Prompt
    470) to `target_text`, gated by Prompt 569's eligibility decision,
    and return the outcome as an EXISTING `CorrectionApplicationResult`
    (Prompt 474/478/479) - see the module docstring for the exact
    eligible / not-eligible behavior.

    Never raises: an ineligible `candidate` (`None`, not a
    `CorrectionApplicationCandidate`, or not ready) produces a
    deterministic `FAILED` result rather than an exception or a call
    into `build_correction_application_request()`. Pure and
    deterministic: the same `candidate` and `target_text` always
    produce an equal result. Performs zero database/storage access,
    zero retrieval, and zero selection - every operation this
    delegates to already guarantees the same, and this function adds
    none of its own.
    """
    eligibility = evaluate_correction_application_candidate_eligibility(candidate)

    if not eligibility.eligible:
        return CorrectionApplicationResult(
            STATUS_FAILED,
            original_text=target_text if isinstance(target_text, str) else None,
            reason=eligibility.reason,
        )

    request = build_correction_application_request(candidate)
    return apply_correction_request_with_validation(request, target_text)
