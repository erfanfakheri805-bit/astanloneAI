"""
Language Intelligence - Correction Application Candidate Readiness
========================================================================
Prompt 472. A small, deterministic, READ-ONLY readiness check over an
EXISTING Prompt 470 `CorrectionApplicationCandidate`
(correction_application_candidate.py). This module answers exactly one
question - "does this already-built candidate contain enough valid
information for a future, separately-scoped correction-application
step to use?" - and nothing else. It does not apply the correction,
does not replace any text, does not generate response text, does not
perform fuzzy or semantic matching, does not perform inference, does
not rank candidates, does not create new learning, and does not write
to storage.

    build_correction_application_candidate(...)   (Prompt 470, unchanged)
        -> CorrectionApplicationCandidate
    is_correction_application_candidate_ready(...) (THIS module)
        -> True / False

Rule (is_correction_application_candidate_ready -> what must hold)
------------------------------------------------------------------------
True only when ALL of the following hold:
    - `candidate` is a `CorrectionApplicationCandidate` (Prompt 470)
      instance;
    - `candidate.is_valid` is `True` - the SAME field Prompt 470
      already sets to `True` only for a `SELECTED`
      `CorrectionSelectionResult` (Prompt 469's own `OUTCOME_SELECTED`);
      an `AMBIGUOUS`/`NOT_FOUND`/`FAILED`-derived candidate is never
      ready;
    - `candidate.original_expression` is present and non-blank text
      (`correction_understanding._is_blank()`, imported, never
      reimplemented - the SAME "required and non-blank" rule
      `correction_learning_input_eligibility.py`'s own
      `is_correction_learning_input_eligible()` already applies to
      `key`);
    - `candidate.corrected_expression_or_meaning` is present and
      non-blank text - the SAME rule that module already applies to
      `meaning`;
    - `candidate.language` names a real language/locale
      (`language_context.canonical_language()`, imported, never
      reimplemented - the SAME "language" requirement that module
      already applies).

False for anything else, including a non-`CorrectionApplicationCandidate`
argument - this function never raises; an unready or malformed input
simply returns `False`.

Never applies anything
-------------------------
`is_correction_application_candidate_ready()` never applies the
correction, never replaces text, never generates response text, never
performs fuzzy/semantic matching, ranking, or inference, never creates
new learning, and never writes to storage. It is a read-only readiness
check only - deciding whether or how to apply a ready candidate is a
separate, future, explicitly scoped step.

Read-only and non-mutating
-----------------------------
This function only reads `candidate.is_valid`,
`candidate.original_expression`, `candidate.corrected_expression_or_meaning`,
and `candidate.language` - it never sets, appends, or otherwise
mutates `candidate` or anything upstream of it. The same candidate
always produces the same readiness result (pure and deterministic;
repeated calls never change behavior).

Not yet connected
--------------------
This module does not touch `ResponseGenerationContext`,
`LanguageUnderstandingResult`, correction detection,
`CorrectionUnderstanding`, `CorrectionUnderstandingResult`,
`LearningAnalyzer`, Memory, Knowledge, Response Generation, or the
Local Model Runtime; it adds no new persistence, no new database, no
ranking/scoring/fuzzy/semantic matching, no inference, and makes no
network/API call. It does not modify `CorrectionApplicationCandidate`,
`build_correction_application_candidate()`, or anything upstream of
them.
"""

from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate,
)
from language_intelligence.correction_understanding import _is_blank
from language_intelligence.language_context import canonical_language


def _is_real_language(value):
    """Same rule `is_correction_learning_input_eligible()` already
    applies (imported `canonical_language`, never reimplemented):
    non-blank text that names an actual language/locale. Never
    raises - an unready candidate is a normal outcome here, not an
    error."""
    if _is_blank(value) or not isinstance(value, str):
        return False
    return canonical_language(value) is not None


def is_correction_application_candidate_ready(candidate):
    """True only when `candidate` (a `CorrectionApplicationCandidate` -
    see the module docstring for the exact rule) contains enough valid
    information for a future correction-application step to use.

    Pure, deterministic, and read-only: never mutates `candidate`,
    never applies anything, never raises - a non-candidate or
    incomplete candidate simply returns `False`.
    """
    if not isinstance(candidate, CorrectionApplicationCandidate):
        return False

    if candidate.is_valid is not True:
        return False

    if _is_blank(candidate.original_expression):
        return False

    if _is_blank(candidate.corrected_expression_or_meaning):
        return False

    if not _is_real_language(candidate.language):
        return False

    return True
