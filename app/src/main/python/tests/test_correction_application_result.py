"""
Tests for Prompt 474 - Create Correction Application Result.

`CorrectionApplicationResult`
(language_intelligence/correction_application_result.py) is a small,
deterministic result shape for a future correction-application step.
It performs no text replacement and is not connected to Learning,
Memory, Knowledge, Correction Understanding/Lookup/Selection,
`ResponseGenerationContext`, or the Local Model Runtime. Covers:

    1. each valid status (APPLIED / NOT_APPLIED / FAILED)
    2. successful application result
    3. not-applied result
    4. failed result
    5. required field preservation
    6. metadata preservation (and independence from the caller's dict)
    7. invalid status rejection

Prompt 478 additions - matched_text / replacement_text / match_count:
    8. successful (APPLIED) result carries the exact matched text
    9. successful (APPLIED) result carries the exact replacement text
    10. successful (APPLIED) result carries the correct match count
    11. NOT_APPLIED result has match_count == 0
    12. FAILED result has match_count == 0
    13. existing (Prompt 474) fields are unchanged by the new fields
    14. a deep copy preserves the new fields
    15. to_dict() (existing serialization) includes the new fields
    16. equality (existing __eq__) accounts for the new fields

Prompt 479 additions - text_before / text_after:
    17. APPLIED preserves before/after text
    18. NOT_APPLIED preserves identical before/after text
    19. FAILED preserves safe before/after state (with and without a
        safely-available target text)
    20. existing fields remain unchanged
    21. match_count remains correct
    22. a deep copy preserves both new fields
    23. to_dict() includes both new fields
    24. equality accounts for both new fields
    25. repeated construction is deterministic

Run directly:
    python -m unittest tests.test_correction_application_result -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_application_result import (
    CorrectionApplicationResult,
    STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED, ALL_STATUSES,
)


class TestCorrectionApplicationResult(unittest.TestCase):

    def test_all_statuses_are_constructible(self):
        for status in ALL_STATUSES:
            result = CorrectionApplicationResult(status)
            self.assertEqual(result.status, status)

    def test_applied_result(self):
        result = CorrectionApplicationResult(
            STATUS_APPLIED, original_text="dgo", corrected_text="dog",
        )
        self.assertEqual(result.status, STATUS_APPLIED)
        self.assertTrue(result.applied)
        self.assertEqual(result.original_text, "dgo")
        self.assertEqual(result.corrected_text, "dog")
        self.assertIsNone(result.reason)

    def test_not_applied_result(self):
        result = CorrectionApplicationResult(
            STATUS_NOT_APPLIED, reason="request_not_ready",
        )
        self.assertEqual(result.status, STATUS_NOT_APPLIED)
        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "request_not_ready")

    def test_failed_result(self):
        result = CorrectionApplicationResult(
            STATUS_FAILED, reason="storage_unavailable",
        )
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "storage_unavailable")

    def test_applied_is_only_true_for_applied_status(self):
        self.assertTrue(CorrectionApplicationResult(STATUS_APPLIED).applied)
        self.assertFalse(CorrectionApplicationResult(STATUS_NOT_APPLIED).applied)
        self.assertFalse(CorrectionApplicationResult(STATUS_FAILED).applied)

    def test_required_fields_are_preserved(self):
        result = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo",
            corrected_text="dog",
            reason=None,
            metadata={"source": "user_correction"},
        )
        as_dict = result.to_dict()
        self.assertEqual(as_dict["status"], STATUS_APPLIED)
        self.assertTrue(as_dict["applied"])
        self.assertEqual(as_dict["original_text"], "dgo")
        self.assertEqual(as_dict["corrected_text"], "dog")
        self.assertIsNone(as_dict["reason"])
        self.assertEqual(as_dict["metadata"], {"source": "user_correction"})

    def test_metadata_defaults_to_empty_dict(self):
        result = CorrectionApplicationResult(STATUS_APPLIED)
        self.assertEqual(result.metadata, {})

    def test_metadata_is_preserved_and_independent(self):
        original_metadata = {"confidence": 0.9}
        result = CorrectionApplicationResult(
            STATUS_APPLIED, metadata=original_metadata,
        )
        self.assertEqual(result.metadata, {"confidence": 0.9})

        # Mutating the caller's dict after construction must never
        # reach the result.
        original_metadata["confidence"] = 0.1
        self.assertEqual(result.metadata, {"confidence": 0.9})

        # Mutating the dict returned by to_dict() must never reach
        # back into the result.
        as_dict = result.to_dict()
        as_dict["confidence"] = "MUTATED"
        self.assertEqual(result.metadata, {"confidence": 0.9})

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(ValueError):
            CorrectionApplicationResult("BOGUS")
        with self.assertRaises(ValueError):
            CorrectionApplicationResult(None)
        with self.assertRaises(ValueError):
            CorrectionApplicationResult("applied")  # wrong case

    # -- Prompt 478: matched_text / replacement_text / match_count --

    def test_applied_result_carries_exact_matched_text(self):
        result = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="a dgo here",
            corrected_text="a dog here",
            matched_text="dgo",
            replacement_text="dog",
            match_count=1,
        )
        self.assertEqual(result.matched_text, "dgo")

    def test_applied_result_carries_exact_replacement_text(self):
        result = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="a dgo here",
            corrected_text="a dog here",
            matched_text="dgo",
            replacement_text="dog",
            match_count=1,
        )
        self.assertEqual(result.replacement_text, "dog")

    def test_applied_result_carries_correct_match_count(self):
        result = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo dgo dgo",
            corrected_text="dog dog dog",
            matched_text="dgo",
            replacement_text="dog",
            match_count=3,
        )
        self.assertEqual(result.match_count, 3)
        self.assertGreater(result.match_count, 0)

    def test_not_applied_result_has_zero_match_count(self):
        result = CorrectionApplicationResult(
            STATUS_NOT_APPLIED, reason="original_expression_not_found_in_target_text",
        )
        self.assertEqual(result.match_count, 0)
        self.assertIsNone(result.matched_text)
        self.assertIsNone(result.replacement_text)

    def test_failed_result_has_zero_match_count(self):
        result = CorrectionApplicationResult(
            STATUS_FAILED, reason="request_not_valid",
        )
        self.assertEqual(result.match_count, 0)
        self.assertIsNone(result.matched_text)
        self.assertIsNone(result.replacement_text)

    def test_existing_fields_unchanged_by_new_fields(self):
        result = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo",
            corrected_text="dog",
            reason=None,
            metadata={"occurrences_replaced": 1},
            matched_text="dgo",
            replacement_text="dog",
            match_count=1,
        )
        self.assertEqual(result.status, STATUS_APPLIED)
        self.assertTrue(result.applied)
        self.assertEqual(result.original_text, "dgo")
        self.assertEqual(result.corrected_text, "dog")
        self.assertIsNone(result.reason)
        self.assertEqual(result.metadata, {"occurrences_replaced": 1})

    def test_deep_copy_preserves_new_fields(self):
        result = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo",
            corrected_text="dog",
            matched_text="dgo",
            replacement_text="dog",
            match_count=1,
        )
        copied = copy.deepcopy(result)
        self.assertEqual(copied.matched_text, "dgo")
        self.assertEqual(copied.replacement_text, "dog")
        self.assertEqual(copied.match_count, 1)
        self.assertEqual(copied, result)

    def test_to_dict_includes_new_fields(self):
        result = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo",
            corrected_text="dog",
            matched_text="dgo",
            replacement_text="dog",
            match_count=1,
        )
        as_dict = result.to_dict()
        self.assertEqual(as_dict["matched_text"], "dgo")
        self.assertEqual(as_dict["replacement_text"], "dog")
        self.assertEqual(as_dict["match_count"], 1)

    def test_equality_accounts_for_new_fields(self):
        base = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo",
            corrected_text="dog",
            matched_text="dgo",
            replacement_text="dog",
            match_count=1,
        )
        same = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo",
            corrected_text="dog",
            matched_text="dgo",
            replacement_text="dog",
            match_count=1,
        )
        different_count = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo",
            corrected_text="dog",
            matched_text="dgo",
            replacement_text="dog",
            match_count=2,
        )
        self.assertEqual(base, same)
        self.assertNotEqual(base, different_count)

    def test_new_fields_default_safely_for_existing_callers(self):
        # Existing callers that never pass the new keyword arguments
        # (e.g. Prompt 474/475/477 call sites predating this prompt)
        # must keep working unchanged.
        result = CorrectionApplicationResult(
            STATUS_APPLIED, original_text="dgo", corrected_text="dog",
        )
        self.assertIsNone(result.matched_text)
        self.assertIsNone(result.replacement_text)
        self.assertEqual(result.match_count, 0)

    # -- Prompt 479: text_before / text_after --

    def test_applied_preserves_before_and_after_text(self):
        result = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="a dgo here",
            corrected_text="a dog here",
            matched_text="dgo",
            replacement_text="dog",
            match_count=1,
        )
        self.assertEqual(result.text_before, "a dgo here")
        self.assertEqual(result.text_after, "a dog here")
        self.assertTrue(result.applied)
        self.assertEqual(result.match_count, 1)

    def test_not_applied_preserves_identical_before_and_after_text(self):
        result = CorrectionApplicationResult(
            STATUS_NOT_APPLIED,
            original_text="no match here",
            corrected_text="no match here",
            reason="original_expression_not_found_in_target_text",
        )
        self.assertEqual(result.text_before, "no match here")
        self.assertEqual(result.text_after, "no match here")
        self.assertFalse(result.applied)
        self.assertEqual(result.match_count, 0)

    def test_failed_preserves_safe_before_after_state_with_text(self):
        # target_text was a string, so it is safely available.
        result = CorrectionApplicationResult(
            STATUS_FAILED, original_text="some text",
            reason="request_not_valid",
        )
        self.assertEqual(result.text_before, "some text")
        self.assertEqual(result.text_after, "some text")
        self.assertFalse(result.applied)
        self.assertEqual(result.match_count, 0)

    def test_failed_preserves_safe_before_after_state_without_text(self):
        # target_text was not a string, so nothing is safely
        # available - text_after must never falsely claim success.
        result = CorrectionApplicationResult(
            STATUS_FAILED, original_text=None,
            reason="target_text_not_a_string",
        )
        self.assertIsNone(result.text_before)
        self.assertIsNone(result.text_after)
        self.assertFalse(result.applied)
        self.assertEqual(result.match_count, 0)

    def test_existing_fields_unchanged_by_text_before_after(self):
        result = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo",
            corrected_text="dog",
            reason=None,
            metadata={"occurrences_replaced": 1},
            matched_text="dgo",
            replacement_text="dog",
            match_count=1,
        )
        self.assertEqual(result.status, STATUS_APPLIED)
        self.assertTrue(result.applied)
        self.assertEqual(result.original_text, "dgo")
        self.assertEqual(result.corrected_text, "dog")
        self.assertIsNone(result.reason)
        self.assertEqual(result.metadata, {"occurrences_replaced": 1})
        self.assertEqual(result.matched_text, "dgo")
        self.assertEqual(result.replacement_text, "dog")

    def test_deep_copy_preserves_text_before_after(self):
        result = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo",
            corrected_text="dog",
            match_count=1,
        )
        copied = copy.deepcopy(result)
        self.assertEqual(copied.text_before, "dgo")
        self.assertEqual(copied.text_after, "dog")
        self.assertEqual(copied, result)

    def test_to_dict_includes_text_before_after(self):
        result = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo",
            corrected_text="dog",
            match_count=1,
        )
        as_dict = result.to_dict()
        self.assertEqual(as_dict["text_before"], "dgo")
        self.assertEqual(as_dict["text_after"], "dog")

    def test_equality_accounts_for_text_before_after(self):
        base = CorrectionApplicationResult(
            STATUS_APPLIED, original_text="dgo", corrected_text="dog",
        )
        same = CorrectionApplicationResult(
            STATUS_APPLIED, original_text="dgo", corrected_text="dog",
        )
        different_after = CorrectionApplicationResult(
            STATUS_APPLIED, original_text="dgo", corrected_text="dog",
            text_after="something else",
        )
        self.assertEqual(base, same)
        self.assertNotEqual(base, different_after)

    def test_repeated_construction_is_deterministic(self):
        first = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo dgo",
            corrected_text="dog dog",
            matched_text="dgo",
            replacement_text="dog",
            match_count=2,
        )
        second = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="dgo dgo",
            corrected_text="dog dog",
            matched_text="dgo",
            replacement_text="dog",
            match_count=2,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.text_before, second.text_before)
        self.assertEqual(first.text_after, second.text_after)


if __name__ == "__main__":
    unittest.main()
