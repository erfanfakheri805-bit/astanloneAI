"""
Tests for Prompt 473 - Create Correction Application Request.

`build_correction_application_request()`
(language_intelligence/correction_application_request.py) is a small,
deterministic request built over an already-built Prompt 470
`CorrectionApplicationCandidate`, gated by the existing Prompt 472
`is_correction_application_candidate_ready()`. It never applies the
correction, never modifies the candidate, and never touches storage.
Covers:

    1. ready candidate -> valid application request
    2. not-ready candidate -> invalid/no request
    3. original expression is preserved
    4. corrected expression/meaning is preserved
    5. language and locale are preserved
    6. source and confidence are preserved
    7. request creation does not mutate the candidate
    8. repeated conversion produces the same result

Run directly:
    python -m unittest tests.test_correction_application_request -v
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
    OUTCOME_SELECTED, OUTCOME_NOT_FOUND,
)
from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate, build_correction_application_candidate,
)
from language_intelligence.correction_application_request import (
    CorrectionApplicationRequest, build_correction_application_request,
    REQUEST_KIND_APPLY_CORRECTION,
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


def _ready_candidate(**overrides):
    record = _valid_record(**overrides)
    result = CorrectionSelectionResult(OUTCOME_SELECTED, correction=record)
    return build_correction_application_candidate(result)


class TestCorrectionApplicationRequest(unittest.TestCase):

    def test_ready_candidate_produces_valid_request(self):
        candidate = _ready_candidate()
        request = build_correction_application_request(candidate)
        self.assertTrue(request.is_valid)
        self.assertEqual(request.kind, REQUEST_KIND_APPLY_CORRECTION)

    def test_not_ready_candidate_produces_invalid_request(self):
        # is_valid=False on the candidate -> never ready.
        candidate = CorrectionApplicationCandidate(is_valid=False)
        request = build_correction_application_request(candidate)
        self.assertFalse(request.is_valid)
        self.assertIsNone(request.kind)
        self.assertIsNone(request.original_expression)
        self.assertIsNone(request.corrected_expression_or_meaning)
        self.assertIsNone(request.language)
        self.assertIsNone(request.locale)
        self.assertIsNone(request.source)
        self.assertIsNone(request.confidence)

    def test_not_ready_missing_field_produces_invalid_request(self):
        # Valid candidate but missing a required field -> not ready.
        candidate = _ready_candidate(key="")
        request = build_correction_application_request(candidate)
        self.assertFalse(request.is_valid)

    def test_not_found_derived_candidate_produces_invalid_request(self):
        result = CorrectionSelectionResult(OUTCOME_NOT_FOUND)
        candidate = build_correction_application_candidate(result)
        request = build_correction_application_request(candidate)
        self.assertFalse(request.is_valid)

    def test_original_expression_is_preserved(self):
        candidate = _ready_candidate(key="dgo")
        request = build_correction_application_request(candidate)
        self.assertEqual(request.original_expression, "dgo")

    def test_corrected_expression_or_meaning_is_preserved(self):
        candidate = _ready_candidate(meaning="dog")
        request = build_correction_application_request(candidate)
        self.assertEqual(request.corrected_expression_or_meaning, "dog")

    def test_language_and_locale_are_preserved(self):
        candidate = _ready_candidate(language="fr")
        request = build_correction_application_request(candidate)
        self.assertEqual(request.language, "fr")
        self.assertEqual(request.locale, candidate.locale)
        self.assertIsNone(request.locale)

    def test_source_and_confidence_are_preserved(self):
        candidate = _ready_candidate(source="user_correction", confidence=0.75)
        request = build_correction_application_request(candidate)
        self.assertEqual(request.source, "user_correction")
        self.assertEqual(request.confidence, 0.75)

    def test_request_creation_does_not_mutate_candidate(self):
        candidate = _ready_candidate()
        before = candidate.to_dict()
        request = build_correction_application_request(candidate)
        self.assertEqual(candidate.to_dict(), before)

        # Mutating the returned request must never reach the candidate.
        request.corrected_expression_or_meaning = "MUTATED"
        self.assertEqual(candidate.to_dict(), before)

    def test_repeated_conversion_produces_the_same_result(self):
        candidate = _ready_candidate()
        first = build_correction_application_request(candidate)
        second = build_correction_application_request(candidate)
        self.assertEqual(first, second)

    def test_non_candidate_argument_raises_type_error(self):
        with self.assertRaises(TypeError):
            build_correction_application_request(None)
        with self.assertRaises(TypeError):
            build_correction_application_request({})


if __name__ == "__main__":
    unittest.main()
