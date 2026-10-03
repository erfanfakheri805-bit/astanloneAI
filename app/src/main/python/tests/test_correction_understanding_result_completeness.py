"""
Tests for Prompt 444 - Correction Understanding Result Completeness.

`check_correction_understanding_result_completeness()` /
`CorrectionUnderstandingResultCompleteness`
(language_intelligence/correction_understanding_result_completeness.py)
check only whether a `CorrectionUnderstandingResult` (Prompt 441) carries
enough information to be structurally complete for its current status.
Only:

    1. a complete RESOLVED result
    2. an incomplete RESOLVED result
    3. a complete AMBIGUOUS result
    4. a complete UNRESOLVED result
    5. a valid (complete) NOT_CORRECTION result
    6. further incomplete result cases (UNRESOLVED, NOT_CORRECTION, a
       non-result value, and an unknown status)

Run directly:
    python -m unittest tests.test_correction_understanding_result_completeness -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_understanding_result import (
    CorrectionUnderstandingResult,
)
from language_intelligence.correction_understanding_result_completeness import (
    check_correction_understanding_result_completeness,
    is_correction_understanding_result_complete,
    COMPLETENESS_COMPLETE, COMPLETENESS_INCOMPLETE,
    REASON_NOT_A_RESULT, REASON_UNKNOWN_STATUS, REASON_MISSING_SOURCE_TEXT,
    REASON_RESOLVED_MISSING_ORIGINAL, REASON_RESOLVED_MISSING_CORRECTED,
    REASON_UNRESOLVED_MISSING_FIELD,
)


class TestCompleteResolvedResult(unittest.TestCase):
    """1. A complete RESOLVED result."""

    def test_resolved_with_both_sides_present_is_complete(self):
        result = CorrectionUnderstandingResult(
            status="RESOLVED", source_text="not dgo, I mean dog.",
            original_expression="dgo", corrected_expression_or_meaning="dog",
            language="en", locale="en-US", confidence=0.9)
        completeness = check_correction_understanding_result_completeness(result)
        self.assertEqual(completeness.status, COMPLETENESS_COMPLETE)
        self.assertTrue(completeness.complete)
        self.assertEqual(completeness.reasons, [])
        self.assertEqual(completeness.result, result.to_dict())
        self.assertTrue(is_correction_understanding_result_complete(result))


class TestIncompleteResolvedResult(unittest.TestCase):
    """2. An incomplete RESOLVED result."""

    def test_resolved_missing_original_expression_is_incomplete(self):
        result = CorrectionUnderstandingResult(
            status="RESOLVED", source_text="src",
            corrected_expression_or_meaning="dog")
        completeness = check_correction_understanding_result_completeness(result)
        self.assertEqual(completeness.status, COMPLETENESS_INCOMPLETE)
        self.assertFalse(completeness.complete)
        self.assertIn(REASON_RESOLVED_MISSING_ORIGINAL, completeness.reason_codes)
        self.assertFalse(is_correction_understanding_result_complete(result))

    def test_resolved_missing_corrected_field_is_incomplete(self):
        result = CorrectionUnderstandingResult(
            status="RESOLVED", source_text="src", original_expression="dgo")
        completeness = check_correction_understanding_result_completeness(result)
        self.assertFalse(completeness.complete)
        self.assertIn(REASON_RESOLVED_MISSING_CORRECTED, completeness.reason_codes)

    def test_resolved_missing_both_sides_reports_both_reasons(self):
        result = CorrectionUnderstandingResult(status="RESOLVED", source_text="src")
        completeness = check_correction_understanding_result_completeness(result)
        self.assertFalse(completeness.complete)
        self.assertIn(REASON_RESOLVED_MISSING_ORIGINAL, completeness.reason_codes)
        self.assertIn(REASON_RESOLVED_MISSING_CORRECTED, completeness.reason_codes)


class TestCompleteAmbiguousResult(unittest.TestCase):
    """3. A complete AMBIGUOUS result."""

    def test_ambiguous_with_source_text_is_complete(self):
        result = CorrectionUnderstandingResult(
            status="AMBIGUOUS", source_text="not dgo", original_expression="dgo")
        completeness = check_correction_understanding_result_completeness(result)
        self.assertTrue(completeness.complete)
        self.assertEqual(completeness.reasons, [])

    def test_ambiguous_with_no_original_expression_either_is_still_complete(self):
        # AMBIGUOUS never carries a corrected_expression_or_meaning (Prompt
        # 439's own decision order); its absence is not incompleteness.
        result = CorrectionUnderstandingResult(status="AMBIGUOUS", source_text="not dgo")
        completeness = check_correction_understanding_result_completeness(result)
        self.assertTrue(completeness.complete)


class TestCompleteUnresolvedResult(unittest.TestCase):
    """4. A complete UNRESOLVED result."""

    def test_unresolved_with_only_original_is_complete(self):
        result = CorrectionUnderstandingResult(
            status="UNRESOLVED", source_text="dgo", original_expression="dgo")
        completeness = check_correction_understanding_result_completeness(result)
        self.assertTrue(completeness.complete)
        self.assertEqual(completeness.reasons, [])

    def test_unresolved_with_only_corrected_is_complete(self):
        result = CorrectionUnderstandingResult(
            status="UNRESOLVED", source_text="dog",
            corrected_expression_or_meaning="dog")
        completeness = check_correction_understanding_result_completeness(result)
        self.assertTrue(completeness.complete)


class TestValidNotCorrectionResult(unittest.TestCase):
    """5. A valid (complete) NOT_CORRECTION result."""

    def test_not_correction_with_neither_field_is_complete(self):
        result = CorrectionUnderstandingResult(
            status="NOT_CORRECTION", source_text="hello there")
        completeness = check_correction_understanding_result_completeness(result)
        self.assertTrue(completeness.complete)
        self.assertEqual(completeness.reasons, [])


class TestFurtherIncompleteResultCases(unittest.TestCase):
    """6. Further incomplete result cases."""

    def test_unresolved_with_neither_field_is_incomplete(self):
        result = CorrectionUnderstandingResult(status="UNRESOLVED", source_text="src")
        completeness = check_correction_understanding_result_completeness(result)
        self.assertFalse(completeness.complete)
        self.assertIn(REASON_UNRESOLVED_MISSING_FIELD, completeness.reason_codes)

    def test_blank_source_text_is_incomplete_regardless_of_status(self):
        result = CorrectionUnderstandingResult(status="NOT_CORRECTION", source_text="   ")
        completeness = check_correction_understanding_result_completeness(result)
        self.assertFalse(completeness.complete)
        self.assertIn(REASON_MISSING_SOURCE_TEXT, completeness.reason_codes)

    def test_none_source_text_on_ambiguous_is_incomplete(self):
        result = CorrectionUnderstandingResult(status="AMBIGUOUS", source_text=None)
        completeness = check_correction_understanding_result_completeness(result)
        self.assertFalse(completeness.complete)
        self.assertIn(REASON_MISSING_SOURCE_TEXT, completeness.reason_codes)

    def test_non_result_value_is_incomplete(self):
        completeness = check_correction_understanding_result_completeness({"status": "RESOLVED"})
        self.assertEqual(completeness.status, COMPLETENESS_INCOMPLETE)
        self.assertIn(REASON_NOT_A_RESULT, completeness.reason_codes)
        self.assertIsNone(completeness.result)

    def test_none_is_incomplete(self):
        completeness = check_correction_understanding_result_completeness(None)
        self.assertFalse(completeness.complete)
        self.assertIn(REASON_NOT_A_RESULT, completeness.reason_codes)

    def test_unknown_status_set_via_object_mutation_is_incomplete(self):
        result = CorrectionUnderstandingResult(status="RESOLVED", source_text="src")
        result.status = "TOTALLY_MADE_UP"
        completeness = check_correction_understanding_result_completeness(result)
        self.assertFalse(completeness.complete)
        self.assertIn(REASON_UNKNOWN_STATUS, completeness.reason_codes)


class TestNoMutationAndSerialization(unittest.TestCase):
    """Completeness checking never mutates the result, and produces a
    to_dict()-able value (deterministic, using the project's existing
    conventions)."""

    def test_checking_does_not_change_the_result_object(self):
        result = CorrectionUnderstandingResult(
            status="RESOLVED", source_text="src", original_expression="dgo",
            corrected_expression_or_meaning="dog", confidence=0.8)
        before = result.to_dict()
        check_correction_understanding_result_completeness(result)
        self.assertEqual(result.to_dict(), before)

    def test_result_copy_is_independent_of_the_original(self):
        result = CorrectionUnderstandingResult(status="NOT_CORRECTION", source_text="src")
        completeness = check_correction_understanding_result_completeness(result)
        completeness.result["status"] = "SOMETHING_ELSE"
        self.assertEqual(result.status, "NOT_CORRECTION")

    def test_completeness_to_dict_round_trips(self):
        result = CorrectionUnderstandingResult(status="NOT_CORRECTION", source_text="src")
        completeness = check_correction_understanding_result_completeness(result)
        as_dict = completeness.to_dict()
        self.assertEqual(as_dict["status"], COMPLETENESS_COMPLETE)
        self.assertEqual(as_dict["reasons"], [])
        self.assertEqual(as_dict["result"], result.to_dict())


if __name__ == "__main__":
    unittest.main()
