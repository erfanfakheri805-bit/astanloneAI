"""
Tests for Prompt 443 - Correction Understanding Result Validation.

`validate_correction_understanding_result()` /
`CorrectionUnderstandingResultValidation`
(language_intelligence/correction_understanding_result_validation.py)
check only the structural validity of a `CorrectionUnderstandingResult`
(Prompt 441). Only:

    1. a valid RESOLVED result
    2. a valid AMBIGUOUS result
    3. a valid UNRESOLVED result
    4. a valid NOT_CORRECTION result
    5. invalid status values
    6. invalid required-field values (source_text, and the
       status-conditional original_expression /
       corrected_expression_or_meaning rules)
    7. invalid confidence values

Run directly:
    python -m unittest tests.test_correction_understanding_result_validation -v
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
from language_intelligence.correction_understanding_result_validation import (
    validate_correction_understanding_result,
    VALIDATION_VALID, VALIDATION_INVALID,
    ISSUE_NOT_A_RESULT, ISSUE_UNKNOWN_STATUS, ISSUE_MISSING_SOURCE_TEXT,
    ISSUE_INVALID_CONFIDENCE, ISSUE_RESOLVED_MISSING_ORIGINAL,
    ISSUE_RESOLVED_MISSING_CORRECTED, ISSUE_AMBIGUOUS_HAS_CORRECTED,
    ISSUE_UNRESOLVED_MISSING_FIELD, ISSUE_UNRESOLVED_HAS_BOTH_FIELDS,
    ISSUE_NOT_CORRECTION_HAS_ORIGINAL, ISSUE_NOT_CORRECTION_HAS_CORRECTED,
)


class TestValidResolvedResult(unittest.TestCase):
    """1. A valid RESOLVED result."""

    def test_resolved_with_both_sides_present_is_valid(self):
        result = CorrectionUnderstandingResult(
            status="RESOLVED", source_text="not dgo, I mean dog.",
            original_expression="dgo", corrected_expression_or_meaning="dog",
            language="en", locale="en-US", confidence=0.9)
        validation = validate_correction_understanding_result(result)
        self.assertEqual(validation.status, VALIDATION_VALID)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.issues, [])
        self.assertEqual(validation.result, result.to_dict())


class TestValidAmbiguousResult(unittest.TestCase):
    """2. A valid AMBIGUOUS result."""

    def test_ambiguous_with_no_corrected_field_is_valid(self):
        result = CorrectionUnderstandingResult(
            status="AMBIGUOUS", source_text="not dgo", original_expression="dgo")
        validation = validate_correction_understanding_result(result)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.issues, [])

    def test_ambiguous_with_no_original_expression_either_is_valid(self):
        result = CorrectionUnderstandingResult(status="AMBIGUOUS", source_text="not dgo")
        validation = validate_correction_understanding_result(result)
        self.assertTrue(validation.valid)


class TestValidUnresolvedResult(unittest.TestCase):
    """3. A valid UNRESOLVED result."""

    def test_unresolved_with_only_original_is_valid(self):
        result = CorrectionUnderstandingResult(
            status="UNRESOLVED", source_text="dgo", original_expression="dgo")
        validation = validate_correction_understanding_result(result)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.issues, [])

    def test_unresolved_with_only_corrected_is_valid(self):
        result = CorrectionUnderstandingResult(
            status="UNRESOLVED", source_text="dog",
            corrected_expression_or_meaning="dog")
        validation = validate_correction_understanding_result(result)
        self.assertTrue(validation.valid)


class TestValidNotCorrectionResult(unittest.TestCase):
    """4. A valid NOT_CORRECTION result."""

    def test_not_correction_with_neither_field_is_valid(self):
        result = CorrectionUnderstandingResult(
            status="NOT_CORRECTION", source_text="hello there")
        validation = validate_correction_understanding_result(result)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.issues, [])


class TestInvalidStatusValues(unittest.TestCase):
    """5. Invalid status values."""

    def test_non_result_value_is_invalid(self):
        validation = validate_correction_understanding_result({"status": "RESOLVED"})
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertIn(ISSUE_NOT_A_RESULT, validation.issue_codes)
        self.assertIsNone(validation.result)

    def test_none_is_invalid(self):
        validation = validate_correction_understanding_result(None)
        self.assertFalse(validation.valid)
        self.assertIn(ISSUE_NOT_A_RESULT, validation.issue_codes)

    def test_unknown_status_set_via_object_mutation_is_invalid(self):
        # CorrectionUnderstandingResult itself validates status only at
        # construction time - simulate a result that later became
        # inconsistent, which is exactly what structural validation is for.
        result = CorrectionUnderstandingResult(status="RESOLVED", source_text="src")
        result.status = "TOTALLY_MADE_UP"
        validation = validate_correction_understanding_result(result)
        self.assertFalse(validation.valid)
        self.assertIn(ISSUE_UNKNOWN_STATUS, validation.issue_codes)


class TestInvalidRequiredFieldValues(unittest.TestCase):
    """6. Invalid required-field values according to existing project
    conventions."""

    def test_blank_source_text_is_invalid(self):
        result = CorrectionUnderstandingResult(status="NOT_CORRECTION", source_text="   ")
        validation = validate_correction_understanding_result(result)
        self.assertFalse(validation.valid)
        self.assertIn(ISSUE_MISSING_SOURCE_TEXT, validation.issue_codes)

    def test_none_source_text_is_invalid(self):
        result = CorrectionUnderstandingResult(status="NOT_CORRECTION", source_text=None)
        validation = validate_correction_understanding_result(result)
        self.assertIn(ISSUE_MISSING_SOURCE_TEXT, validation.issue_codes)

    def test_resolved_missing_original_expression_is_invalid(self):
        result = CorrectionUnderstandingResult(
            status="RESOLVED", source_text="src", corrected_expression_or_meaning="dog")
        validation = validate_correction_understanding_result(result)
        self.assertFalse(validation.valid)
        self.assertIn(ISSUE_RESOLVED_MISSING_ORIGINAL, validation.issue_codes)

    def test_resolved_missing_corrected_field_is_invalid(self):
        result = CorrectionUnderstandingResult(
            status="RESOLVED", source_text="src", original_expression="dgo")
        validation = validate_correction_understanding_result(result)
        self.assertIn(ISSUE_RESOLVED_MISSING_CORRECTED, validation.issue_codes)

    def test_ambiguous_carrying_a_corrected_field_is_invalid(self):
        result = CorrectionUnderstandingResult(
            status="AMBIGUOUS", source_text="src",
            corrected_expression_or_meaning="dog")
        validation = validate_correction_understanding_result(result)
        self.assertIn(ISSUE_AMBIGUOUS_HAS_CORRECTED, validation.issue_codes)

    def test_unresolved_with_neither_field_is_invalid(self):
        result = CorrectionUnderstandingResult(status="UNRESOLVED", source_text="src")
        validation = validate_correction_understanding_result(result)
        self.assertIn(ISSUE_UNRESOLVED_MISSING_FIELD, validation.issue_codes)

    def test_unresolved_with_both_fields_is_invalid(self):
        result = CorrectionUnderstandingResult(
            status="UNRESOLVED", source_text="src", original_expression="dgo",
            corrected_expression_or_meaning="dog")
        validation = validate_correction_understanding_result(result)
        self.assertIn(ISSUE_UNRESOLVED_HAS_BOTH_FIELDS, validation.issue_codes)

    def test_not_correction_with_original_expression_is_invalid(self):
        result = CorrectionUnderstandingResult(
            status="NOT_CORRECTION", source_text="src", original_expression="dgo")
        validation = validate_correction_understanding_result(result)
        self.assertIn(ISSUE_NOT_CORRECTION_HAS_ORIGINAL, validation.issue_codes)

    def test_not_correction_with_corrected_field_is_invalid(self):
        result = CorrectionUnderstandingResult(
            status="NOT_CORRECTION", source_text="src",
            corrected_expression_or_meaning="dog")
        validation = validate_correction_understanding_result(result)
        self.assertIn(ISSUE_NOT_CORRECTION_HAS_CORRECTED, validation.issue_codes)


class TestInvalidConfidenceValues(unittest.TestCase):
    """7. Invalid confidence values."""

    def test_confidence_above_one_is_invalid(self):
        result = CorrectionUnderstandingResult(
            status="NOT_CORRECTION", source_text="src", confidence=1.5)
        validation = validate_correction_understanding_result(result)
        self.assertIn(ISSUE_INVALID_CONFIDENCE, validation.issue_codes)

    def test_confidence_below_zero_is_invalid(self):
        result = CorrectionUnderstandingResult(
            status="NOT_CORRECTION", source_text="src", confidence=-0.1)
        validation = validate_correction_understanding_result(result)
        self.assertIn(ISSUE_INVALID_CONFIDENCE, validation.issue_codes)

    def test_non_numeric_confidence_is_invalid(self):
        result = CorrectionUnderstandingResult(
            status="NOT_CORRECTION", source_text="src", confidence="high")
        validation = validate_correction_understanding_result(result)
        self.assertIn(ISSUE_INVALID_CONFIDENCE, validation.issue_codes)

    def test_boolean_confidence_is_invalid(self):
        result = CorrectionUnderstandingResult(
            status="NOT_CORRECTION", source_text="src", confidence=True)
        validation = validate_correction_understanding_result(result)
        self.assertIn(ISSUE_INVALID_CONFIDENCE, validation.issue_codes)

    def test_valid_confidence_at_the_boundaries_is_accepted(self):
        for confidence in (0.0, 1.0, 0.5):
            result = CorrectionUnderstandingResult(
                status="NOT_CORRECTION", source_text="src", confidence=confidence)
            validation = validate_correction_understanding_result(result)
            self.assertTrue(validation.valid)


class TestNoMutationAndSerialization(unittest.TestCase):
    """Validation never mutates the result, and produces a to_dict()-able
    value (spec requirement: no unexpected mutation, deterministic result
    using the project's existing conventions)."""

    def test_validating_does_not_change_the_result_object(self):
        result = CorrectionUnderstandingResult(
            status="RESOLVED", source_text="src", original_expression="dgo",
            corrected_expression_or_meaning="dog", confidence=0.8)
        before = result.to_dict()
        validate_correction_understanding_result(result)
        self.assertEqual(result.to_dict(), before)

    def test_result_copy_is_independent_of_the_original(self):
        result = CorrectionUnderstandingResult(status="NOT_CORRECTION", source_text="src")
        validation = validate_correction_understanding_result(result)
        validation.result["status"] = "SOMETHING_ELSE"
        self.assertEqual(result.status, "NOT_CORRECTION")

    def test_validation_to_dict_round_trips(self):
        result = CorrectionUnderstandingResult(status="NOT_CORRECTION", source_text="src")
        validation = validate_correction_understanding_result(result)
        as_dict = validation.to_dict()
        self.assertEqual(as_dict["status"], VALIDATION_VALID)
        self.assertEqual(as_dict["issues"], [])
        self.assertEqual(as_dict["result"], result.to_dict())


if __name__ == "__main__":
    unittest.main()
