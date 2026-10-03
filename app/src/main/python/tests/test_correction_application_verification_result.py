"""
Tests for Prompt 481 - Create Correction Application Verification Result.

`CorrectionApplicationVerificationResult`
(language_intelligence/correction_application_verification_result.py)
is a pure data model - not an operation - representing whether an
existing `CorrectionApplicationResult` passed deterministic
verification. It performs no validation itself, applies no
corrections, and never mutates anything passed to it. Covers:

    1. VALID result
    2. INVALID result
    3. status/valid boolean consistency
    4. reason preservation
    5. metadata preservation (and independence from the caller's dict)
    6. safe copy() preserves status/reason/metadata and is independent
    7. to_dict() (serialization) preserves all four fields
    8. equality/comparison accounts for all four fields
    9. invalid status is rejected (ValueError), per this package's
       existing "status not in ALL_STATUSES -> raise" convention

Run directly:
    python -m unittest tests.test_correction_application_verification_result -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_application_verification_result import (
    CorrectionApplicationVerificationResult,
    STATUS_VALID, STATUS_INVALID, ALL_STATUSES,
)


class TestCorrectionApplicationVerificationResult(unittest.TestCase):

    def test_valid_result(self):
        result = CorrectionApplicationVerificationResult(STATUS_VALID)
        self.assertEqual(result.status, STATUS_VALID)
        self.assertTrue(result.valid)

    def test_invalid_result(self):
        result = CorrectionApplicationVerificationResult(
            STATUS_INVALID, reason="matched_text_does_not_match_request",
        )
        self.assertEqual(result.status, STATUS_INVALID)
        self.assertFalse(result.valid)

    def test_status_and_valid_are_always_consistent(self):
        for status in ALL_STATUSES:
            result = CorrectionApplicationVerificationResult(status)
            self.assertEqual(result.valid, status == STATUS_VALID)

    def test_reason_is_preserved(self):
        result = CorrectionApplicationVerificationResult(
            STATUS_INVALID, reason="text_after_does_not_match_replacement",
        )
        self.assertEqual(
            result.reason, "text_after_does_not_match_replacement",
        )

    def test_reason_defaults_to_none(self):
        result = CorrectionApplicationVerificationResult(STATUS_VALID)
        self.assertIsNone(result.reason)

    def test_metadata_is_preserved(self):
        result = CorrectionApplicationVerificationResult(
            STATUS_VALID, metadata={"checked_by": "prompt_480_validator"},
        )
        self.assertEqual(
            result.metadata, {"checked_by": "prompt_480_validator"},
        )

    def test_metadata_defaults_to_empty_dict(self):
        result = CorrectionApplicationVerificationResult(STATUS_VALID)
        self.assertEqual(result.metadata, {})

    def test_metadata_is_independent_of_caller_dict(self):
        source = {"key": "value"}
        result = CorrectionApplicationVerificationResult(
            STATUS_VALID, metadata=source,
        )
        source["key"] = "mutated"
        self.assertEqual(result.metadata, {"key": "value"})

    def test_metadata_attribute_is_the_live_stored_dict(self):
        # Only to_dict() returns an independent copy (see the test
        # below) - direct attribute access reflects the stored dict,
        # the same convention CorrectionApplicationResult.metadata
        # (Prompt 474) already uses.
        result = CorrectionApplicationVerificationResult(
            STATUS_VALID, metadata={"key": "value"},
        )
        result.metadata["key"] = "mutated"
        self.assertEqual(result.metadata, {"key": "mutated"})

    def test_copy_preserves_fields_and_is_independent(self):
        original = CorrectionApplicationVerificationResult(
            STATUS_INVALID,
            reason="match_count_not_greater_than_zero",
            metadata={"source": "prompt_480"},
        )
        copied = original.copy()
        self.assertEqual(copied.status, original.status)
        self.assertEqual(copied.valid, original.valid)
        self.assertEqual(copied.reason, original.reason)
        self.assertEqual(copied.metadata, original.metadata)
        self.assertEqual(copied, original)
        copied.metadata["source"] = "mutated"
        self.assertEqual(original.metadata, {"source": "prompt_480"})

    def test_to_dict_preserves_all_fields(self):
        result = CorrectionApplicationVerificationResult(
            STATUS_INVALID,
            reason="text_before_missing",
            metadata={"note": "example"},
        )
        as_dict = result.to_dict()
        self.assertEqual(as_dict, {
            "status": STATUS_INVALID,
            "valid": False,
            "reason": "text_before_missing",
            "metadata": {"note": "example"},
        })

    def test_to_dict_returns_independent_metadata_copy(self):
        result = CorrectionApplicationVerificationResult(
            STATUS_VALID, metadata={"key": "value"},
        )
        as_dict = result.to_dict()
        as_dict["metadata"]["key"] = "mutated"
        self.assertEqual(result.metadata, {"key": "value"})

    def test_equality_accounts_for_all_fields(self):
        base = CorrectionApplicationVerificationResult(
            STATUS_VALID, reason=None, metadata={"a": 1},
        )
        same = CorrectionApplicationVerificationResult(
            STATUS_VALID, reason=None, metadata={"a": 1},
        )
        different_status = CorrectionApplicationVerificationResult(
            STATUS_INVALID, reason=None, metadata={"a": 1},
        )
        different_reason = CorrectionApplicationVerificationResult(
            STATUS_VALID, reason="something", metadata={"a": 1},
        )
        different_metadata = CorrectionApplicationVerificationResult(
            STATUS_VALID, reason=None, metadata={"a": 2},
        )
        self.assertEqual(base, same)
        self.assertNotEqual(base, different_status)
        self.assertNotEqual(base, different_reason)
        self.assertNotEqual(base, different_metadata)

    def test_equality_with_non_matching_type_returns_not_implemented(self):
        result = CorrectionApplicationVerificationResult(STATUS_VALID)
        self.assertNotEqual(result, "not a verification result")
        self.assertNotEqual(result, {"status": STATUS_VALID})

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(ValueError):
            CorrectionApplicationVerificationResult("BOGUS")
        with self.assertRaises(ValueError):
            CorrectionApplicationVerificationResult(None)
        with self.assertRaises(ValueError):
            CorrectionApplicationVerificationResult("valid")  # wrong case

    def test_deep_copy_preserves_fields(self):
        result = CorrectionApplicationVerificationResult(
            STATUS_INVALID, reason="reason text", metadata={"a": [1, 2]},
        )
        deep_copied = copy.deepcopy(result)
        self.assertEqual(deep_copied, result)
        deep_copied.metadata["a"].append(3)
        self.assertEqual(result.metadata, {"a": [1, 2]})

    def test_does_not_perform_validation_or_mutate_anything(self):
        # Construction is pure data-recording: passing in unrelated
        # objects never inspects, applies, or modifies them - this
        # class has no method that does either.
        result = CorrectionApplicationVerificationResult(
            STATUS_VALID, metadata={"note": "no validation performed here"},
        )
        self.assertFalse(hasattr(result, "validate"))
        self.assertFalse(hasattr(result, "apply"))


if __name__ == "__main__":
    unittest.main()
