"""
Tests for Prompt 459 - Validate Correction Learning Handoff Result.

`validate_correction_learning_handoff_result()`
(language_intelligence/correction_learning_handoff_result_validation.py)
is a small, deterministic STRUCTURAL check over an already-built
`CorrectionLearningHandoffResult` (Prompt 458). It builds nothing,
calls no handoff, and performs no inference - only field presence/type/
consistency checks.

    - valid ACCEPTED result
    - valid REJECTED result
    - valid FAILED result
    - invalid status
    - invalid `accepted` value
    - missing/invalid required fields
    - consistency between `status` and `accepted`

Run directly:
    python -m unittest tests.test_correction_learning_handoff_result_validation -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_feedback_record import SOURCE_USER_CORRECTION
from language_intelligence.correction_learning_handoff_result import (
    STATUS_ACCEPTED,
    STATUS_REJECTED,
    STATUS_FAILED,
    CorrectionLearningHandoffResult,
)
from language_intelligence.correction_learning_handoff_result_validation import (
    VALIDATION_VALID,
    VALIDATION_INVALID,
    ISSUE_NOT_A_RESULT,
    ISSUE_UNKNOWN_STATUS,
    ISSUE_ACCEPTED_NOT_BOOL,
    ISSUE_ACCEPTED_STATUS_MISMATCH,
    ISSUE_INVALID_SOURCE,
    ISSUE_MISSING_REASON_FOR_FAILED,
    ISSUE_UNEXPECTED_REASON,
    validate_correction_learning_handoff_result,
)


class TestValidAcceptedResult(unittest.TestCase):
    """A valid ACCEPTED result."""

    def test_is_valid(self):
        result = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        validation = validate_correction_learning_handoff_result(result)
        self.assertEqual(validation.status, VALIDATION_VALID)
        self.assertEqual(validation.issues, [])

    def test_result_copy_matches_original(self):
        result = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        validation = validate_correction_learning_handoff_result(result)
        self.assertEqual(validation.result, result.to_dict())


class TestValidRejectedResult(unittest.TestCase):
    """A valid REJECTED result."""

    def test_is_valid(self):
        result = CorrectionLearningHandoffResult(STATUS_REJECTED)
        validation = validate_correction_learning_handoff_result(result)
        self.assertEqual(validation.status, VALIDATION_VALID)
        self.assertEqual(validation.issues, [])


class TestValidFailedResult(unittest.TestCase):
    """A valid FAILED result."""

    def test_is_valid_with_a_reason(self):
        result = CorrectionLearningHandoffResult(
            STATUS_FAILED, reason="confidence must be a number")
        validation = validate_correction_learning_handoff_result(result)
        self.assertEqual(validation.status, VALIDATION_VALID)
        self.assertEqual(validation.issues, [])


class TestInvalidStatus(unittest.TestCase):
    """Invalid status."""

    def test_unknown_status_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        result.status = "NOT_A_REAL_STATUS"
        validation = validate_correction_learning_handoff_result(result)
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertEqual(validation.issue_codes, [ISSUE_UNKNOWN_STATUS])

    def test_unknown_status_short_circuits_other_checks(self):
        # An unknown status makes the result structurally meaningless,
        # so nothing else is checked - only one issue is reported even
        # though accepted/source are also inconsistent here.
        result = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        result.status = "BOGUS"
        result.accepted = "not a bool"
        result.source = "SOMETHING_ELSE"
        validation = validate_correction_learning_handoff_result(result)
        self.assertEqual(validation.issue_codes, [ISSUE_UNKNOWN_STATUS])


class TestInvalidAcceptedValue(unittest.TestCase):
    """Invalid `accepted` value."""

    def test_non_bool_accepted_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        result.accepted = "yes"
        validation = validate_correction_learning_handoff_result(result)
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertIn(ISSUE_ACCEPTED_NOT_BOOL, validation.issue_codes)

    def test_none_accepted_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_REJECTED)
        result.accepted = None
        validation = validate_correction_learning_handoff_result(result)
        self.assertIn(ISSUE_ACCEPTED_NOT_BOOL, validation.issue_codes)

    def test_int_accepted_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        result.accepted = 1
        validation = validate_correction_learning_handoff_result(result)
        self.assertIn(ISSUE_ACCEPTED_NOT_BOOL, validation.issue_codes)


class TestMissingOrInvalidRequiredFields(unittest.TestCase):
    """Missing/invalid required fields."""

    def test_not_a_result_at_all(self):
        validation = validate_correction_learning_handoff_result(None)
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertEqual(validation.issue_codes, [ISSUE_NOT_A_RESULT])
        self.assertIsNone(validation.result)

    def test_plain_dict_is_not_a_result(self):
        validation = validate_correction_learning_handoff_result(
            {"status": STATUS_ACCEPTED, "accepted": True,
             "source": SOURCE_USER_CORRECTION, "reason": None})
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertEqual(validation.issue_codes, [ISSUE_NOT_A_RESULT])

    def test_wrong_source_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        result.source = "SOME_OTHER_SOURCE"
        validation = validate_correction_learning_handoff_result(result)
        self.assertIn(ISSUE_INVALID_SOURCE, validation.issue_codes)

    def test_blank_source_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        result.source = ""
        validation = validate_correction_learning_handoff_result(result)
        self.assertIn(ISSUE_INVALID_SOURCE, validation.issue_codes)

    def test_failed_without_reason_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_FAILED)
        validation = validate_correction_learning_handoff_result(result)
        self.assertIn(ISSUE_MISSING_REASON_FOR_FAILED, validation.issue_codes)

    def test_failed_with_blank_reason_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_FAILED, reason="   ")
        validation = validate_correction_learning_handoff_result(result)
        self.assertIn(ISSUE_MISSING_REASON_FOR_FAILED, validation.issue_codes)

    def test_failed_with_non_text_reason_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_FAILED, reason={"why": "bad"})
        validation = validate_correction_learning_handoff_result(result)
        self.assertIn(ISSUE_MISSING_REASON_FOR_FAILED, validation.issue_codes)

    def test_accepted_with_unexpected_reason_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        result.reason = "made up explanation"
        validation = validate_correction_learning_handoff_result(result)
        self.assertIn(ISSUE_UNEXPECTED_REASON, validation.issue_codes)

    def test_rejected_with_unexpected_reason_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_REJECTED)
        result.reason = "made up explanation"
        validation = validate_correction_learning_handoff_result(result)
        self.assertIn(ISSUE_UNEXPECTED_REASON, validation.issue_codes)


class TestAcceptedStatusConsistency(unittest.TestCase):
    """Consistency between `status` and `accepted`."""

    def test_accepted_true_with_non_accepted_status_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_REJECTED)
        result.accepted = True
        validation = validate_correction_learning_handoff_result(result)
        self.assertIn(ISSUE_ACCEPTED_STATUS_MISMATCH, validation.issue_codes)

    def test_accepted_false_with_accepted_status_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        result.accepted = False
        validation = validate_correction_learning_handoff_result(result)
        self.assertIn(ISSUE_ACCEPTED_STATUS_MISMATCH, validation.issue_codes)

    def test_failed_status_with_accepted_true_is_invalid(self):
        result = CorrectionLearningHandoffResult(STATUS_FAILED, reason="boom")
        result.accepted = True
        validation = validate_correction_learning_handoff_result(result)
        self.assertIn(ISSUE_ACCEPTED_STATUS_MISMATCH, validation.issue_codes)

    def test_naturally_constructed_results_are_always_consistent(self):
        for status, reason in (
            (STATUS_ACCEPTED, None), (STATUS_REJECTED, None), (STATUS_FAILED, "x")):
            result = CorrectionLearningHandoffResult(status, reason=reason)
            validation = validate_correction_learning_handoff_result(result)
            self.assertTrue(validation.valid, validation.issue_codes)


class TestValidationDoesNotMutateTheResult(unittest.TestCase):
    def test_result_object_unchanged_after_validation(self):
        result = CorrectionLearningHandoffResult(STATUS_FAILED, reason="boom")
        before = result.to_dict()
        validate_correction_learning_handoff_result(result)
        self.assertEqual(result.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
