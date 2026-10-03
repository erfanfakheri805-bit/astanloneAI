"""
Tests for Prompt 472 - Correction Candidate Application Readiness.

`is_correction_application_candidate_ready()`
(language_intelligence/correction_application_candidate_readiness.py)
is a small, deterministic, read-only readiness check over an existing
Prompt 470 `CorrectionApplicationCandidate`. It never applies the
correction, never modifies the candidate, and never touches storage.
Covers:

    1. valid selected candidate -> ready
    2. missing original expression -> not ready
    3. missing corrected expression/meaning -> not ready
    4. invalid candidate (is_valid=False) -> not ready
    5. non-selected/invalid source state (AMBIGUOUS/NOT_FOUND/FAILED
       derived candidates) -> not ready
    6. language information follows existing conventions
       (blank/unreal language -> not ready)
    7. readiness check does not mutate the candidate
    8. repeated checks return the same result

Run directly:
    python -m unittest tests.test_correction_application_candidate_readiness -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_lookup_selection import (
    CorrectionSelectionResult,
    OUTCOME_SELECTED, OUTCOME_AMBIGUOUS, OUTCOME_NOT_FOUND, OUTCOME_FAILED,
)
from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate, build_correction_application_candidate,
)
from language_intelligence.correction_application_candidate_readiness import (
    is_correction_application_candidate_ready,
)


def _valid_record(key="dgo", meaning="dog", language="en", **overrides):
    record = {
        "id": 1, "language": language, "item_type": "correction", "key": key,
        "meaning": meaning, "examples": [], "relationships": [],
        "confidence": 0.9, "source": "user_correction", "source_context": None,
        "learning_method": "explicit_correction", "version": 1,
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
    }
    record.update(overrides)
    return record


def _selected_candidate(**overrides):
    record = _valid_record(**overrides)
    result = CorrectionSelectionResult(OUTCOME_SELECTED, correction=record)
    return build_correction_application_candidate(result)


class TestCorrectionApplicationCandidateReadiness(unittest.TestCase):

    def test_valid_selected_candidate_is_ready(self):
        candidate = _selected_candidate()
        self.assertTrue(is_correction_application_candidate_ready(candidate))

    def test_missing_original_expression_is_not_ready(self):
        candidate = _selected_candidate(key="")
        self.assertFalse(is_correction_application_candidate_ready(candidate))

    def test_missing_corrected_expression_or_meaning_is_not_ready(self):
        candidate = _selected_candidate(meaning="")
        self.assertFalse(is_correction_application_candidate_ready(candidate))

    def test_invalid_candidate_is_not_ready(self):
        candidate = CorrectionApplicationCandidate(is_valid=False)
        self.assertFalse(is_correction_application_candidate_ready(candidate))

    def test_ambiguous_derived_candidate_is_not_ready(self):
        records = [_valid_record(id=1), _valid_record(id=2)]
        result = CorrectionSelectionResult(OUTCOME_AMBIGUOUS, candidates=records)
        candidate = build_correction_application_candidate(result)
        self.assertFalse(is_correction_application_candidate_ready(candidate))

    def test_not_found_derived_candidate_is_not_ready(self):
        result = CorrectionSelectionResult(OUTCOME_NOT_FOUND)
        candidate = build_correction_application_candidate(result)
        self.assertFalse(is_correction_application_candidate_ready(candidate))

    def test_failed_derived_candidate_is_not_ready(self):
        result = CorrectionSelectionResult(OUTCOME_FAILED, reason="storage_unavailable")
        candidate = build_correction_application_candidate(result)
        self.assertFalse(is_correction_application_candidate_ready(candidate))

    def test_blank_language_is_not_ready(self):
        candidate = _selected_candidate(language="")
        self.assertFalse(is_correction_application_candidate_ready(candidate))

    def test_unreal_language_is_not_ready(self):
        candidate = _selected_candidate(language="unknown")
        self.assertFalse(is_correction_application_candidate_ready(candidate))

    def test_non_candidate_argument_is_not_ready(self):
        self.assertFalse(is_correction_application_candidate_ready(None))
        self.assertFalse(is_correction_application_candidate_ready({}))
        self.assertFalse(is_correction_application_candidate_ready("not a candidate"))

    def test_readiness_check_does_not_mutate_candidate(self):
        candidate = _selected_candidate()
        before = candidate.to_dict()
        is_correction_application_candidate_ready(candidate)
        self.assertEqual(candidate.to_dict(), before)

    def test_repeated_checks_return_the_same_result(self):
        candidate = _selected_candidate()
        first = is_correction_application_candidate_ready(candidate)
        second = is_correction_application_candidate_ready(candidate)
        third = is_correction_application_candidate_ready(candidate)
        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertTrue(first)


if __name__ == "__main__":
    unittest.main()
