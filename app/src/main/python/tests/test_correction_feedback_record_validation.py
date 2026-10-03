"""
Tests for Prompt 450 - Correction Feedback Record Validation.

`validate_correction_feedback_record()`
(language_intelligence/correction_feedback_record_validation.py) is a
small, deterministic structural check over a `CorrectionFeedbackRecord`
(Prompt 449). Only:

    1. a valid feedback record passes validation
    2. a valid is_valid_feedback=False record is handled correctly
    3. invalid is_valid_feedback values are rejected per convention
    4. a valid correction with the required fields passes
    5. an incomplete valid correction is rejected
    6. invalid feedback records do not incorrectly become valid
    7. validation does not mutate the original record

Run directly:
    python -m unittest tests.test_correction_feedback_record_validation -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_feedback_record import CorrectionFeedbackRecord
from language_intelligence.correction_feedback_record_validation import (
    VALIDATION_VALID, VALIDATION_INVALID,
    ISSUE_NOT_A_RECORD, ISSUE_IS_VALID_FEEDBACK_NOT_BOOL, ISSUE_MISSING_SOURCE_TEXT,
    ISSUE_INVALID_CONFIDENCE, ISSUE_VALID_FEEDBACK_MISSING_ORIGINAL,
    ISSUE_VALID_FEEDBACK_MISSING_CORRECTED,
    CorrectionFeedbackRecordValidation,
    validate_correction_feedback_record,
)


def _valid_feedback_record(**overrides):
    fields = dict(
        original_expression="dgo",
        corrected_expression_or_meaning="dog",
        language="en",
        locale="en-US",
        source_text="no I mean dog not dgo",
        confidence=0.9,
        is_valid_feedback=True,
    )
    fields.update(overrides)
    return CorrectionFeedbackRecord(**fields)


def _invalid_feedback_record(**overrides):
    fields = dict(
        original_expression=None,
        corrected_expression_or_meaning=None,
        language=None,
        locale=None,
        source_text="hello there",
        confidence=0.0,
        is_valid_feedback=False,
    )
    fields.update(overrides)
    return CorrectionFeedbackRecord(**fields)


class TestValidFeedbackRecordPasses(unittest.TestCase):
    """1. A valid feedback record passes validation."""

    def test_complete_valid_feedback_record_is_valid(self):
        record = _valid_feedback_record()
        validation = validate_correction_feedback_record(record)
        self.assertIsInstance(validation, CorrectionFeedbackRecordValidation)
        self.assertEqual(validation.status, VALIDATION_VALID)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.issues, [])


class TestFalseFeedbackHandledCorrectly(unittest.TestCase):
    """2. A valid is_valid_feedback=False record is handled correctly."""

    def test_false_record_with_no_correction_fields_is_valid(self):
        record = _invalid_feedback_record()
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.status, VALIDATION_VALID)

    def test_false_record_with_partial_correction_fields_is_still_valid(self):
        # is_valid_feedback=False: incomplete correction fields must not
        # make the record structurally invalid.
        record = _invalid_feedback_record(
            original_expression="dgo", corrected_expression_or_meaning=None)
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.status, VALIDATION_VALID)


class TestInvalidIsValidFeedbackValuesRejected(unittest.TestCase):
    """3. Invalid is_valid_feedback values are rejected per project
    convention (must be an actual bool, never coerced or accepted as
    truthy/falsy)."""

    def test_non_correction_feedback_record_value_is_rejected(self):
        validation = validate_correction_feedback_record({"is_valid_feedback": True})
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertIn(ISSUE_NOT_A_RECORD, validation.issue_codes)
        self.assertIsNone(validation.record)

    def test_none_is_rejected(self):
        validation = validate_correction_feedback_record(None)
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertIn(ISSUE_NOT_A_RECORD, validation.issue_codes)

    def test_constructor_always_coerces_is_valid_feedback_to_bool(self):
        # CorrectionFeedbackRecord.__init__ applies bool(...), so a
        # truthy/falsy non-bool passed in still ends up as an actual
        # bool on the record - confirming the "never coerced elsewhere"
        # convention this validator relies on.
        record = CorrectionFeedbackRecord(
            original_expression="dgo", corrected_expression_or_meaning="dog",
            language="en", locale="en-US", source_text="src", confidence=0.5,
            is_valid_feedback=1)
        self.assertIsInstance(record.is_valid_feedback, bool)
        self.assertTrue(record.is_valid_feedback)
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.status, VALIDATION_VALID)


class TestValidCorrectionWithRequiredFieldsPasses(unittest.TestCase):
    """4. A valid correction with the required fields passes."""

    def test_required_fields_present_passes(self):
        record = _valid_feedback_record(
            original_expression="teh", corrected_expression_or_meaning="the")
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.status, VALIDATION_VALID)
        self.assertEqual(validation.record["original_expression"], "teh")
        self.assertEqual(validation.record["corrected_expression_or_meaning"], "the")


class TestIncompleteValidCorrectionIsRejected(unittest.TestCase):
    """5. An incomplete valid correction is rejected."""

    def test_true_missing_original_expression_is_invalid(self):
        record = _valid_feedback_record(original_expression=None)
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertIn(ISSUE_VALID_FEEDBACK_MISSING_ORIGINAL, validation.issue_codes)

    def test_true_missing_corrected_expression_or_meaning_is_invalid(self):
        record = _valid_feedback_record(corrected_expression_or_meaning=None)
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertIn(ISSUE_VALID_FEEDBACK_MISSING_CORRECTED, validation.issue_codes)

    def test_true_missing_both_reports_both_issues(self):
        record = _valid_feedback_record(
            original_expression=None, corrected_expression_or_meaning=None)
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertIn(ISSUE_VALID_FEEDBACK_MISSING_ORIGINAL, validation.issue_codes)
        self.assertIn(ISSUE_VALID_FEEDBACK_MISSING_CORRECTED, validation.issue_codes)

    def test_true_blank_string_fields_are_treated_as_missing(self):
        record = _valid_feedback_record(
            original_expression="   ", corrected_expression_or_meaning="")
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.status, VALIDATION_INVALID)


class TestInvalidFeedbackRecordsDoNotBecomeValid(unittest.TestCase):
    """6. Invalid feedback records do not incorrectly become valid."""

    def test_missing_source_text_is_invalid_regardless_of_is_valid_feedback(self):
        for flag in (True, False):
            record = _valid_feedback_record(is_valid_feedback=flag, source_text="")
            validation = validate_correction_feedback_record(record)
            self.assertEqual(validation.status, VALIDATION_INVALID)
            self.assertIn(ISSUE_MISSING_SOURCE_TEXT, validation.issue_codes)

    def test_out_of_range_confidence_is_invalid(self):
        record = _valid_feedback_record(confidence=1.5)
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertIn(ISSUE_INVALID_CONFIDENCE, validation.issue_codes)

    def test_boolean_confidence_is_invalid(self):
        record = _valid_feedback_record(confidence=True)
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertIn(ISSUE_INVALID_CONFIDENCE, validation.issue_codes)


class TestValidationDoesNotMutateOriginalRecord(unittest.TestCase):
    """7. Validation does not mutate the original record."""

    def test_record_fields_unchanged_after_validation(self):
        record = _valid_feedback_record()
        before = record.to_dict()
        validate_correction_feedback_record(record)
        after = record.to_dict()
        self.assertEqual(before, after)

    def test_returned_record_snapshot_is_a_copy_not_the_original_dict(self):
        record = _valid_feedback_record()
        validation = validate_correction_feedback_record(record)
        validation.record["original_expression"] = "mutated"
        self.assertEqual(record.original_expression, "dgo")

    def test_invalid_record_case_also_leaves_original_untouched(self):
        record = _valid_feedback_record(original_expression=None)
        before = record.to_dict()
        validate_correction_feedback_record(record)
        after = record.to_dict()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
