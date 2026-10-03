"""
Language Intelligence - Correction Retrieval -> Language Understanding
Adapter (Prompt 565)
========================================================================
The smallest safe runtime connection between the EXISTING correction-
learning retrieval chain and the EXISTING (Prompt 564)
`LanguageUnderstandingResult.correction_application_candidate` slot -
see docs/section2_correction_retrieval_to_understanding_connection_
prompt565.md for the full architecture trace this module is built
from.

Prompt 563's own audit
(diagnostics/section2_correction_retrieval_application_audit_prompt563.py,
finding `no_trigger_exists_for_when_to_look_up_a_stored_correction`)
found no existing, deterministic concept anywhere in this codebase of
"this expression, in this ordinary message, is one Core has a
previously stored correction for; look it up before replying." Prompt
565's own instructions forbid inventing that trigger here. This module
therefore adds NO trigger and performs NO lookup on its own initiative
- it exposes pure functions that a future, separately-scoped caller
(Core, once it decides on a trigger and which expression to check) can
call to run the EXISTING chain exactly once and attach the result to
an EXISTING `LanguageUnderstandingResult`:

    lookup_correction_learning_input_by_original_expression_with_result(...)  (Prompt 464, unchanged)
        -> CorrectionLearningExactLookupResult
    build_correction_lookup_context(...)                                     (Prompt 465, unchanged)
        -> CorrectionLookupContext
    select_unique_stored_correction(...)                                     (Prompt 469, unchanged)
        -> CorrectionSelectionResult
    build_correction_application_candidate(...)                              (Prompt 470, unchanged)
        -> CorrectionApplicationCandidate
    attach_correction_application_candidate(...)                             (THIS module)
        -> understanding.correction_application_candidate populated, or
           left None (Prompt 564's own field, unchanged)

No new retrieval, selection, or candidate logic is added anywhere in
this module - every step above is the exact, unchanged, already-
tested existing function (see FILES_INSPECTED in the Prompt 563 audit
for each one's own module). This module only wires them together, in
their existing order, and assigns the final result onto an existing
`LanguageUnderstandingResult` - the one missing "call site" step the
audit named as the smallest concrete foundation for a later prompt.

Not called from anywhere else in this codebase
-----------------------------------------------
Nothing in core/core.py, language_intelligence_core.py, any backend,
or anywhere else in this project calls any function in this module -
it is dependency-injection surface only, held ready for whichever
future prompt supplies the trigger decision the Prompt 563 audit found
missing, plus the (already trivial, once this module exists) one-line
call from Core using its own `self.language_learning` store and the
`LanguageUnderstandingResult` `self.language_intelligence.understand()`
already returns. No database lookup happens for every normal message
- or for any message at all - merely because this module exists; a
lookup only ever happens when a caller explicitly calls
`build_correction_application_candidate_from_store()` or
`retrieve_and_attach_correction_application_candidate()` below, and
each such call performs at most one lookup.

What this module deliberately does NOT do
------------------------------------------
- decide WHEN a message should trigger a correction lookup (the
  missing trigger above - a genuine future design decision)
- perform a fuzzy, global, or best-effort search (the underlying
  chain is exact-match only, unchanged)
- create a new storage layer, database, or global singleton
- give `LanguageUnderstandingResult` direct ownership of, or a
  reference to, any store
- automatically apply a correction to a message, or touch response
  generation in any way
- overwrite a candidate a result already carries
"""

from language_intelligence.correction_learning_exact_lookup_result import (
    lookup_correction_learning_input_by_original_expression_with_result,
)
from language_intelligence.correction_lookup_context import build_correction_lookup_context
from language_intelligence.correction_lookup_selection import select_unique_stored_correction
from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate, build_correction_application_candidate,
)
from language_intelligence.language_understanding_result import LanguageUnderstandingResult


def build_correction_application_candidate_from_store(store, original_expression, language=None):
    """Run the EXISTING retrieval -> lookup-context -> selection ->
    candidate chain exactly once for `original_expression` (and,
    optionally, `language`), and return the resulting
    `CorrectionApplicationCandidate`.

    This performs exactly one store lookup - never a fuzzy or global
    search - and every intermediate step is the SAME existing,
    unchanged function the Prompt 563 audit already confirmed works;
    this function invents no new one (see the module docstring for the
    exact chain). A `store` that is not a `LanguageLearningStore` (or
    any other argument problem the underlying lookup already
    validates) does not raise here - it flows through the chain's own
    existing `STATUS_FAILED` -> `OUTCOME_FAILED` -> `is_valid=False`
    convention, exactly as it would for any other caller of
    `lookup_correction_learning_input_by_original_expression_with_result()`.

    Deterministic: the same store state and arguments always produce
    an equal (`==`) candidate, and nothing is mutated, stored, or
    applied by this function.
    """
    lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
        store, original_expression, language=language)
    lookup_context = build_correction_lookup_context(lookup_result)
    selection = select_unique_stored_correction(lookup_context)
    return build_correction_application_candidate(selection)


def attach_correction_application_candidate(understanding, candidate):
    """Assign an already-built `CorrectionApplicationCandidate` (Prompt
    470 - typically from `build_correction_application_candidate_from_
    store()` above, or built directly by a caller) onto an EXISTING
    `LanguageUnderstandingResult`'s `correction_application_candidate`
    field (Prompt 564).

    Adapter only: performs no lookup, selection, or decision of its
    own about whether a candidate should be attached - `candidate`
    must already be built. `understanding` must be a
    `LanguageUnderstandingResult` (`TypeError` otherwise, the same
    "isinstance check, then raise" posture the rest of this chain
    already uses). `candidate` may be `None` (nothing to attach - a
    no-op) or a `CorrectionApplicationCandidate` (`TypeError` for any
    other type).

    If `understanding` already carries a candidate
    (`correction_application_candidate is not None`), it is left
    completely untouched - this function never overwrites an existing
    candidate, mirroring `LanguageIntelligenceCore._attach_response_
    plan()`'s own "a result that already carries a plan keeps it" rule
    for `response_plan`.

    Never automatically applies the correction, never touches response
    generation, and never looks anything up itself - `understanding`
    is only ever mutated by having this one attribute set.

    Returns `understanding` (the same object, mutated in place, for
    convenient chaining) - never a new result.
    """
    if not isinstance(understanding, LanguageUnderstandingResult):
        raise TypeError(
            "understanding must be a LanguageUnderstandingResult "
            "(language_intelligence.language_understanding_result."
            "LanguageUnderstandingResult) instance"
        )
    if candidate is not None and not isinstance(candidate, CorrectionApplicationCandidate):
        raise TypeError(
            "candidate must be a CorrectionApplicationCandidate "
            "(language_intelligence.correction_application_candidate."
            "CorrectionApplicationCandidate) instance, or None"
        )
    if understanding.correction_application_candidate is not None:
        return understanding
    if candidate is not None:
        understanding.correction_application_candidate = candidate
    return understanding


def retrieve_and_attach_correction_application_candidate(
        understanding, store, original_expression, language=None):
    """Convenience: run
    `build_correction_application_candidate_from_store()` exactly once
    and attach the result via `attach_correction_application_candidate()`
    above - still no trigger decision of its own. Whether to call this
    function at all, and which `original_expression` (and `language`)
    to check, must already be decided by the caller; see the module
    docstring for why no such decision is made inside this package.

    Only an `is_valid=True` candidate is ever attached - `AMBIGUOUS`,
    `NOT_FOUND`, and `FAILED` outcomes are computed (so a caller can
    still inspect why, via the return value of
    `build_correction_application_candidate_from_store()` directly, if
    it wants to) but are NOT attached here, so
    `understanding.correction_application_candidate` only ever becomes
    non-None for a genuinely usable candidate - never a placeholder
    for "nothing found", matching Prompt 565's own "leave the
    candidate as None when no valid candidate exists" requirement.

    If `understanding` already carries a candidate, this function
    performs the lookup (so behavior is otherwise identical either
    way) but does not overwrite it - see
    `attach_correction_application_candidate()`.

    Exactly one store lookup per call. Returns `understanding` (the
    same object, mutated in place, for convenient chaining).
    """
    candidate = build_correction_application_candidate_from_store(
        store, original_expression, language=language)
    if candidate.is_valid:
        attach_correction_application_candidate(understanding, candidate)
    return understanding
