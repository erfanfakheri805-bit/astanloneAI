"""
Tests for Prompt 480 - Validate Applied Correction Result.

`validate_applied_correction_result()`
(language_intelligence/correction_application_result_validation.py)
checks whether an existing `CorrectionApplicationResult` is
structurally consistent with the `CorrectionApplicationRequest` it
claims to fulfill, using EXACT string comparison only. It never
applies, retries, or modifies anything. Covers:

    1. valid APPLIED result -> VALID
    2. incorrect before-text -> INVALID
    3. incorrect after-text -> INVALID
    4. incorrect matched expression -> INVALID
    5. incorrect replacement expression -> INVALID
    6. incorrect match count -> INVALID
    7. result that does not correspond to exact replacement -> INVALID
    8. valid NOT_APPLIED result -> VALID
    9. invalid NOT_APPLIED result -> INVALID
    10. valid FAILED result -> VALID
    11. failed result falsely marked applied -> INVALID
    12. deterministic repeated validation

Run directly:
    python -m unittest tests.test_correction_application_result_validation -v
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
    CorrectionApplicationRequest, build_correction_application_request,
)
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult,
    STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED,
)
from language_intelligence.correction_application import (
    apply_correction_request,
)
from language_intelligence.correction_application_result_validation import (
    validate_applied_correction_result,
    CorrectionApplicationResultValidation,
    STATUS_VALID, STATUS_INVALID,
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


class TestValidateAppliedCorrectionResult(unittest.TestCase):

    def test_valid_applied_result_is_valid(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgo here")
        validation = validate_applied_correction_result(request, result)
        self.assertEqual(validation.status, STATUS_VALID)
        self.assertTrue(validation.valid)

    def test_incorrect_before_text_is_invalid(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgo here")
        tampered = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text=result.original_text,
            corrected_text=result.corrected_text,
            matched_text=result.matched_text,
            replacement_text=result.replacement_text,
            match_count=result.match_count,
            text_before="totally unrelated text",
            text_after=result.text_after,
        )
        validation = validate_applied_correction_result(request, tampered)
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_incorrect_after_text_is_invalid(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgo here")
        tampered = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text=result.original_text,
            corrected_text="something else entirely",
            matched_text=result.matched_text,
            replacement_text=result.replacement_text,
            match_count=result.match_count,
            text_before=result.text_before,
            text_after="something else entirely",
        )
        validation = validate_applied_correction_result(request, tampered)
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_incorrect_matched_expression_is_invalid(self):
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
        validation = validate_applied_correction_result(request, tampered)
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_incorrect_replacement_expression_is_invalid(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgo here")
        tampered = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text=result.original_text,
            corrected_text=result.corrected_text,
            matched_text=result.matched_text,
            replacement_text="wrong-replacement",
            match_count=result.match_count,
            text_before=result.text_before,
            text_after=result.text_after,
        )
        validation = validate_applied_correction_result(request, tampered)
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_incorrect_match_count_is_invalid(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgo here")
        tampered = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text=result.original_text,
            corrected_text=result.corrected_text,
            matched_text=result.matched_text,
            replacement_text=result.replacement_text,
            match_count=0,
            text_before=result.text_before,
            text_after=result.text_after,
        )
        validation = validate_applied_correction_result(request, tampered)
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_result_not_corresponding_to_exact_replacement_is_invalid(self):
        request = _ready_request(key="dgo", meaning="dog")
        # matched_text/replacement_text and match_count all look
        # right individually, but text_after was not actually
        # produced by replacing matched_text with replacement_text
        # in text_before.
        tampered = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="a dgo here",
            corrected_text="a dog here, extra words added",
            matched_text="dgo",
            replacement_text="dog",
            match_count=1,
            text_before="a dgo here",
            text_after="a dog here, extra words added",
        )
        validation = validate_applied_correction_result(request, tampered)
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_valid_not_applied_result_is_valid(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "no match here")
        validation = validate_applied_correction_result(request, result)
        self.assertEqual(validation.status, STATUS_VALID)

    def test_invalid_not_applied_result_is_invalid(self):
        request = _ready_request(key="dgo", meaning="dog")
        tampered = CorrectionApplicationResult(
            STATUS_NOT_APPLIED,
            original_text="no match here",
            corrected_text="no match here",
            text_before="no match here",
            text_after="different text",  # should equal text_before
        )
        validation = validate_applied_correction_result(request, tampered)
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_valid_failed_result_is_valid(self):
        request = CorrectionApplicationRequest(is_valid=False)
        result = apply_correction_request(request, "some text")
        validation = validate_applied_correction_result(request, result)
        self.assertEqual(validation.status, STATUS_VALID)

    def test_failed_result_falsely_marked_applied_is_invalid(self):
        request = CorrectionApplicationRequest(is_valid=False)
        # Construct a FAILED-status object whose match_count claims
        # a successful replacement happened - must not be accepted.
        tampered = CorrectionApplicationResult(
            STATUS_FAILED,
            original_text="some text",
            match_count=1,
        )
        validation = validate_applied_correction_result(request, tampered)
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_deterministic_repeated_validation(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgo here")
        first = validate_applied_correction_result(request, result)
        second = validate_applied_correction_result(request, result)
        self.assertEqual(first, second)

    def test_invalid_request_type_is_invalid(self):
        result = CorrectionApplicationResult(STATUS_NOT_APPLIED)
        validation = validate_applied_correction_result("not a request", result)
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_invalid_result_type_is_invalid(self):
        request = _ready_request(key="dgo", meaning="dog")
        validation = validate_applied_correction_result(request, "not a result")
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_validation_never_mutates_result(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgo here")
        before = result.to_dict()
        validate_applied_correction_result(request, result)
        self.assertEqual(result.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
