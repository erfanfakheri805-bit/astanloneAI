"""
Tests for the Prompt 482 correction-application verification
operation.

`verify_correction_application_result()`
(language_intelligence/correction_application_verification.py) wraps
the existing Prompt 480 `validate_applied_correction_result()` and
reports the outcome as an existing Prompt 481
`CorrectionApplicationVerificationResult`. It performs no validation
rules of its own and never mutates `request` or `result`. Covers:

    1. a valid applied correction verifies as VALID
    2. an invalid/tampered result verifies as INVALID
    3. status/valid boolean consistency on the returned object
    4. reason is carried through from the underlying validator
    5. verification never mutates request or result
    6. deterministic repeated verification

Run directly:
    python -m unittest tests.test_correction_application_verification -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_lookup_selection import (
    CorrectionSelectionResult, OUTCOME_SELECTED,
)
from language_intelligence.correction_application_candidate import (
    build_correction_application_candidate,
)
from language_intelligence.correction_application_request import (
    build_correction_application_request,
)
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult, STATUS_APPLIED,
)
from language_intelligence.correction_application import (
    apply_correction_request,
)
from language_intelligence.correction_application_verification_result import (
    CorrectionApplicationVerificationResult,
    STATUS_VALID, STATUS_INVALID,
)
from language_intelligence.correction_application_verification import (
    verify_correction_application_result,
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


def _ready_request(**overrides):
    record = _valid_record(**overrides)
    result = CorrectionSelectionResult(OUTCOME_SELECTED, correction=record)
    candidate = build_correction_application_candidate(result)
    return build_correction_application_request(candidate)


class TestVerifyCorrectionApplicationResult(unittest.TestCase):

    def test_valid_applied_correction_verifies_as_valid(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgo here")
        verification = verify_correction_application_result(request, result)
        self.assertIsInstance(
            verification, CorrectionApplicationVerificationResult,
        )
        self.assertEqual(verification.status, STATUS_VALID)
        self.assertTrue(verification.valid)

    def test_tampered_result_verifies_as_invalid(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgo here")
        tampered = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text=result.original_text,
            corrected_text=result.corrected_text,
            matched_text="wrong-expression",
            replacement_text=result.replacement_text,
            match_count=result.match_count,
            text_before=result.text_before,
            text_after=result.text_after,
        )
        verification = verify_correction_application_result(request, tampered)
        self.assertEqual(verification.status, STATUS_INVALID)
        self.assertFalse(verification.valid)

    def test_status_and_valid_are_consistent(self):
        request = _ready_request(key="dgo", meaning="dog")
        valid_result = apply_correction_request(request, "a dgo here")
        valid_verification = verify_correction_application_result(
            request, valid_result,
        )
        self.assertEqual(
            valid_verification.valid,
            valid_verification.status == STATUS_VALID,
        )

        invalid_result = CorrectionApplicationResult(STATUS_APPLIED)
        invalid_verification = verify_correction_application_result(
            request, invalid_result,
        )
        self.assertEqual(
            invalid_verification.valid,
            invalid_verification.status == STATUS_VALID,
        )

    def test_reason_is_carried_through_from_validator(self):
        request = _ready_request(key="dgo", meaning="dog")
        broken = CorrectionApplicationResult(STATUS_APPLIED)
        verification = verify_correction_application_result(request, broken)
        self.assertIsNotNone(verification.reason)

    def test_verification_does_not_mutate_request_or_result(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgo here")
        result_before = result.to_dict()
        request_before = request.to_dict()
        verify_correction_application_result(request, result)
        self.assertEqual(result.to_dict(), result_before)
        self.assertEqual(request.to_dict(), request_before)

    def test_repeated_verification_is_deterministic(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgo here")
        first = verify_correction_application_result(request, result)
        second = verify_correction_application_result(request, result)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
