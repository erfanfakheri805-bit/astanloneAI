"""
Tests for Prompt 469 - Select a Unique Stored Correction.

`select_unique_stored_correction()`
(language_intelligence/correction_lookup_selection.py) is a small,
deterministic selection operation over an already-built Prompt 465
`CorrectionLookupContext`. It does not perform a lookup, does not
fuzzy/semantic match, does not rank or score candidates, does not
guess intent, does not apply a correction, and does not generate any
response text. Covers:

    1. exactly one valid correction -> SELECTED
    2. multiple valid corrections -> AMBIGUOUS
    3. zero corrections -> NOT_FOUND
    4. FOUND status but every record unusable -> NOT_FOUND
    5. NOT_FOUND context -> NOT_FOUND
    6. failed context -> FAILED (reason preserved)
    7. invalid correction records are ignored per existing validation
    8. selected correction preserves all original fields
    9. ambiguous candidates are preserved, in order
    10. selection does not modify stored/context data
    11. repeated selection produces the same result
    12. non-CorrectionLookupContext argument raises TypeError

Run directly:
    python -m unittest tests.test_correction_lookup_selection -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_lookup_context import (
    CorrectionLookupContext, build_correction_lookup_context,
)
from language_intelligence.correction_learning_exact_lookup_result import (
    CorrectionLearningExactLookupResult,
    STATUS_FOUND, STATUS_NOT_FOUND, STATUS_FAILED,
)
from language_intelligence.correction_lookup_selection import (
    CorrectionSelectionResult, select_unique_stored_correction,
    OUTCOME_SELECTED, OUTCOME_AMBIGUOUS, OUTCOME_NOT_FOUND, OUTCOME_FAILED,
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


def _found_context(records):
    result = CorrectionLearningExactLookupResult(
        status=STATUS_FOUND, original_expression="dgo", records=records,
    )
    return build_correction_lookup_context(result)


def _not_found_context():
    result = CorrectionLearningExactLookupResult(
        status=STATUS_NOT_FOUND, original_expression="dgo", records=[],
    )
    return build_correction_lookup_context(result)


def _failed_context(reason="storage_unavailable"):
    result = CorrectionLearningExactLookupResult(
        status=STATUS_FAILED, original_expression="dgo", records=[],
        reason=reason,
    )
    return build_correction_lookup_context(result)


class TestCorrectionLookupSelection(unittest.TestCase):

    def test_exactly_one_valid_correction_is_selected(self):
        record = _valid_record()
        context = _found_context([record])
        result = select_unique_stored_correction(context)
        self.assertEqual(result.outcome, OUTCOME_SELECTED)
        self.assertEqual(result.correction, record)
        self.assertEqual(result.candidates, [])
        self.assertIsNone(result.reason)

    def test_multiple_valid_corrections_are_ambiguous(self):
        record_a = _valid_record(key="dgo", meaning="dog")
        record_b = _valid_record(key="dgo", meaning="dog", language="fr", id=2)
        context = _found_context([record_a, record_b])
        result = select_unique_stored_correction(context)
        self.assertEqual(result.outcome, OUTCOME_AMBIGUOUS)
        self.assertIsNone(result.correction)

    def test_zero_corrections_is_not_found(self):
        context = _found_context([])
        result = select_unique_stored_correction(context)
        self.assertEqual(result.outcome, OUTCOME_NOT_FOUND)
        self.assertIsNone(result.correction)
        self.assertEqual(result.candidates, [])

    def test_found_status_with_all_unusable_records_is_not_found(self):
        context = _found_context([_valid_record(key=""), _valid_record(meaning=None)])
        result = select_unique_stored_correction(context)
        self.assertEqual(result.outcome, OUTCOME_NOT_FOUND)

    def test_not_found_status_context_is_not_found(self):
        result = select_unique_stored_correction(_not_found_context())
        self.assertEqual(result.outcome, OUTCOME_NOT_FOUND)
        self.assertIsNone(result.correction)
        self.assertEqual(result.candidates, [])

    def test_failed_context_is_failed_with_reason_preserved(self):
        context = _failed_context(reason="storage_unavailable")
        result = select_unique_stored_correction(context)
        self.assertEqual(result.outcome, OUTCOME_FAILED)
        self.assertEqual(result.reason, "storage_unavailable")
        self.assertIsNone(result.correction)
        self.assertEqual(result.candidates, [])

    def test_invalid_records_are_ignored_leaving_one_valid_selected(self):
        valid = _valid_record(key="dgo", meaning="dog")
        invalid_missing_key = _valid_record(key="", meaning="dog", id=2)
        invalid_missing_meaning = _valid_record(key="dgo", meaning=None, id=3)
        invalid_not_dict = "not_a_record"
        context = _found_context(
            [invalid_missing_key, valid, invalid_missing_meaning, invalid_not_dict]
        )
        result = select_unique_stored_correction(context)
        self.assertEqual(result.outcome, OUTCOME_SELECTED)
        self.assertEqual(result.correction, valid)

    def test_invalid_records_ignored_among_multiple_valid_is_ambiguous(self):
        valid_a = _valid_record(key="dgo", meaning="dog")
        valid_b = _valid_record(key="dgo", meaning="dog", language="fr", id=2)
        invalid = _valid_record(key="", meaning="dog", id=3)
        context = _found_context([invalid, valid_a, valid_b])
        result = select_unique_stored_correction(context)
        self.assertEqual(result.outcome, OUTCOME_AMBIGUOUS)
        self.assertEqual(result.candidates, [valid_a, valid_b])

    def test_selected_correction_preserves_all_original_fields(self):
        record = _valid_record(
            key="dgo", meaning="dog", language="en", confidence=0.75,
            source="user_correction", source_context="chat_message",
            learning_method="explicit_correction", version=3,
            id=42, created_at="2026-02-01T00:00:00",
            updated_at="2026-02-02T00:00:00",
        )
        context = _found_context([record])
        result = select_unique_stored_correction(context)
        self.assertEqual(result.correction, record)
        for field, value in record.items():
            self.assertEqual(result.correction[field], value)

    def test_ambiguous_candidates_preserved_in_order(self):
        record_a = _valid_record(key="dgo", meaning="dog", id=1)
        record_b = _valid_record(key="dgo", meaning="doggo", id=2)
        record_c = _valid_record(key="dgo", meaning="puppy", id=3)
        context = _found_context([record_a, record_b, record_c])
        result = select_unique_stored_correction(context)
        self.assertEqual(result.outcome, OUTCOME_AMBIGUOUS)
        self.assertEqual(result.candidates, [record_a, record_b, record_c])

    def test_selection_does_not_modify_context_or_records(self):
        record = _valid_record()
        context = _found_context([record])
        before = context.to_dict()
        result = select_unique_stored_correction(context)
        self.assertEqual(context.to_dict(), before)

        # Mutating the returned correction must never reach the context.
        result.correction["meaning"] = "MUTATED"
        self.assertEqual(context.records[0]["meaning"], "dog")

    def test_selection_does_not_modify_ambiguous_candidates_source(self):
        record_a = _valid_record(key="dgo", meaning="dog", id=1)
        record_b = _valid_record(key="dgo", meaning="doggo", id=2)
        context = _found_context([record_a, record_b])
        result = select_unique_stored_correction(context)
        result.candidates[0]["meaning"] = "MUTATED"
        self.assertEqual(context.records[0]["meaning"], "dog")

    def test_repeated_selection_produces_same_result_selected(self):
        context = _found_context([_valid_record()])
        first = select_unique_stored_correction(context)
        second = select_unique_stored_correction(context)
        self.assertEqual(first, second)

    def test_repeated_selection_produces_same_result_ambiguous(self):
        context = _found_context([_valid_record(id=1), _valid_record(id=2)])
        first = select_unique_stored_correction(context)
        second = select_unique_stored_correction(context)
        self.assertEqual(first, second)

    def test_repeated_selection_produces_same_result_not_found(self):
        context = _not_found_context()
        first = select_unique_stored_correction(context)
        second = select_unique_stored_correction(context)
        self.assertEqual(first, second)

    def test_repeated_selection_produces_same_result_failed(self):
        context = _failed_context()
        first = select_unique_stored_correction(context)
        second = select_unique_stored_correction(context)
        self.assertEqual(first, second)

    def test_non_context_argument_raises_type_error(self):
        with self.assertRaises(TypeError):
            select_unique_stored_correction({"status": "FOUND"})
        with self.assertRaises(TypeError):
            select_unique_stored_correction(None)

    def test_result_to_dict_is_independent_copy(self):
        context = _found_context([_valid_record()])
        result = select_unique_stored_correction(context)
        d = result.to_dict()
        d["correction"]["meaning"] = "MUTATED"
        self.assertEqual(result.correction["meaning"], "dog")

    def test_selection_result_equality_and_repr(self):
        context = _found_context([_valid_record()])
        result = select_unique_stored_correction(context)
        other = CorrectionSelectionResult(OUTCOME_SELECTED, correction=_valid_record())
        self.assertEqual(result, other)
        self.assertIn("CorrectionSelectionResult", repr(result))


if __name__ == "__main__":
    unittest.main()
