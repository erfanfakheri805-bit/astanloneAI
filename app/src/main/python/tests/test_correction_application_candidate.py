"""
Tests for Prompt 470 - Create Selected Correction Application Candidate.

`build_correction_application_candidate()`
(language_intelligence/correction_application_candidate.py) is a
small, deterministic candidate built over an already-built Prompt 469
`CorrectionSelectionResult`. It never applies a correction, never
modifies the user's message, never modifies a stored learning record,
never generates response text, and never performs fuzzy/semantic
matching, ranking, or inference. Covers:

    1. SELECTED result -> valid application candidate
    2. AMBIGUOUS -> no valid candidate
    3. NOT_FOUND -> no valid candidate
    4. FAILED -> no valid candidate
    5. correction fields (original expression, meaning) are preserved
    6. language and locale are preserved (locale always None)
    7. source and confidence are preserved
    8. candidate creation does not modify the original result
    9. candidate creation is deterministic
    10. non-CorrectionSelectionResult argument raises TypeError

Run directly:
    python -m unittest tests.test_correction_application_candidate -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
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


def _valid_record(key="dgo", meaning="dog", **overrides):
    record = {
        "id": 1, "language": "en", "item_type": "correction", "key": key,
        "meaning": meaning, "examples": [], "relationships": [],
        "confidence": 0.9, "source": "user_correction", "source_context": None,
        "learning_method": "explicit_correction", "version": 1,
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
    }
    record.update(overrides)
    return record


def _selected_result(record):
    return CorrectionSelectionResult(OUTCOME_SELECTED, correction=record)


def _ambiguous_result(records):
    return CorrectionSelectionResult(OUTCOME_AMBIGUOUS, candidates=records)


def _not_found_result():
    return CorrectionSelectionResult(OUTCOME_NOT_FOUND)


def _failed_result(reason="storage_unavailable"):
    return CorrectionSelectionResult(OUTCOME_FAILED, reason=reason)


class TestCorrectionApplicationCandidate(unittest.TestCase):

    def test_selected_result_produces_valid_candidate(self):
        record = _valid_record()
        candidate = build_correction_application_candidate(_selected_result(record))
        self.assertTrue(candidate.is_valid)

    def test_ambiguous_result_produces_no_valid_candidate(self):
        records = [_valid_record(id=1), _valid_record(id=2)]
        candidate = build_correction_application_candidate(_ambiguous_result(records))
        self.assertFalse(candidate.is_valid)
        self.assertIsNone(candidate.original_expression)
        self.assertIsNone(candidate.corrected_expression_or_meaning)
        self.assertIsNone(candidate.language)
        self.assertIsNone(candidate.locale)
        self.assertIsNone(candidate.source)
        self.assertIsNone(candidate.confidence)

    def test_not_found_result_produces_no_valid_candidate(self):
        candidate = build_correction_application_candidate(_not_found_result())
        self.assertFalse(candidate.is_valid)
        self.assertIsNone(candidate.original_expression)
        self.assertIsNone(candidate.corrected_expression_or_meaning)

    def test_failed_result_produces_no_valid_candidate(self):
        candidate = build_correction_application_candidate(_failed_result())
        self.assertFalse(candidate.is_valid)
        self.assertIsNone(candidate.original_expression)
        self.assertIsNone(candidate.corrected_expression_or_meaning)

    def test_correction_fields_are_preserved(self):
        record = _valid_record(key="dgo", meaning="dog")
        candidate = build_correction_application_candidate(_selected_result(record))
        self.assertEqual(candidate.original_expression, "dgo")
        self.assertEqual(candidate.corrected_expression_or_meaning, "dog")

    def test_language_is_preserved_and_locale_is_none(self):
        record = _valid_record(language="fr")
        candidate = build_correction_application_candidate(_selected_result(record))
        self.assertEqual(candidate.language, "fr")
        self.assertIsNone(candidate.locale)

    def test_source_and_confidence_are_preserved(self):
        record = _valid_record(source="user_correction", confidence=0.75)
        candidate = build_correction_application_candidate(_selected_result(record))
        self.assertEqual(candidate.source, "user_correction")
        self.assertEqual(candidate.confidence, 0.75)

    def test_candidate_creation_does_not_modify_original_result(self):
        record = _valid_record()
        selection_result = _selected_result(record)
        before = selection_result.to_dict()
        candidate = build_correction_application_candidate(selection_result)
        self.assertEqual(selection_result.to_dict(), before)

        # Mutating the returned candidate must never reach the result.
        candidate.corrected_expression_or_meaning = "MUTATED"
        self.assertEqual(selection_result.correction["meaning"], "dog")

    def test_candidate_creation_does_not_modify_selection_correction_dict(self):
        record = _valid_record()
        selection_result = _selected_result(record)
        build_correction_application_candidate(selection_result)
        self.assertEqual(selection_result.correction, record)

    def test_candidate_creation_is_deterministic_selected(self):
        record = _valid_record()
        selection_result = _selected_result(record)
        first = build_correction_application_candidate(selection_result)
        second = build_correction_application_candidate(selection_result)
        self.assertEqual(first, second)

    def test_candidate_creation_is_deterministic_ambiguous(self):
        selection_result = _ambiguous_result(
            [_valid_record(id=1), _valid_record(id=2)])
        first = build_correction_application_candidate(selection_result)
        second = build_correction_application_candidate(selection_result)
        self.assertEqual(first, second)

    def test_candidate_creation_is_deterministic_not_found(self):
        selection_result = _not_found_result()
        first = build_correction_application_candidate(selection_result)
        second = build_correction_application_candidate(selection_result)
        self.assertEqual(first, second)

    def test_candidate_creation_is_deterministic_failed(self):
        selection_result = _failed_result()
        first = build_correction_application_candidate(selection_result)
        second = build_correction_application_candidate(selection_result)
        self.assertEqual(first, second)

    def test_non_selection_result_argument_raises_type_error(self):
        with self.assertRaises(TypeError):
            build_correction_application_candidate({"outcome": "SELECTED"})
        with self.assertRaises(TypeError):
            build_correction_application_candidate(None)

    def test_candidate_to_dict_is_independent_copy(self):
        record = _valid_record()
        candidate = build_correction_application_candidate(_selected_result(record))
        d = candidate.to_dict()
        d["corrected_expression_or_meaning"] = "MUTATED"
        self.assertEqual(candidate.corrected_expression_or_meaning, "dog")

    def test_candidate_copy_is_independent_and_equal(self):
        record = _valid_record()
        candidate = build_correction_application_candidate(_selected_result(record))
        duplicate = candidate.copy()
        self.assertEqual(candidate, duplicate)
        duplicate.corrected_expression_or_meaning = "MUTATED"
        self.assertEqual(candidate.corrected_expression_or_meaning, "dog")

    def test_candidate_equality_and_repr(self):
        record = _valid_record()
        candidate = build_correction_application_candidate(_selected_result(record))
        other = CorrectionApplicationCandidate(
            is_valid=True, original_expression="dgo",
            corrected_expression_or_meaning="dog", language="en",
            locale=None, source="user_correction", confidence=0.9,
        )
        self.assertEqual(candidate, other)
        self.assertIn("CorrectionApplicationCandidate", repr(candidate))

    def test_no_original_expression_field_is_invented_for_invalid(self):
        # AMBIGUOUS/NOT_FOUND/FAILED candidates must all be identical
        # empty placeholders - never a guessed or partially-filled one.
        ambiguous = build_correction_application_candidate(
            _ambiguous_result([_valid_record(id=1), _valid_record(id=2)]))
        not_found = build_correction_application_candidate(_not_found_result())
        failed = build_correction_application_candidate(_failed_result())
        self.assertEqual(ambiguous, not_found)
        self.assertEqual(not_found, failed)


if __name__ == "__main__":
    unittest.main()
