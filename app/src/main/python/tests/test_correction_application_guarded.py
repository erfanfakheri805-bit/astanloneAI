"""
Tests for Prompt 477 - Guard Correction Application with Validation.

`apply_correction_request_with_validation()`
(language_intelligence/correction_application_guarded.py) runs the
EXISTING Prompt 476 `validate_correction_application_target()` guard
before delegating to the EXISTING Prompt 475
`apply_correction_request()`. Covers:

    1. READY validation -> correction is applied
    2. NOT_READY validation -> correction is not applied
    3. INVALID validation -> correction is not applied, status FAILED
    4. target text unchanged when application is rejected (NOT_READY)
    5. target text unchanged when application is rejected (INVALID)
    6. successful exact replacement still works
    7. multiple exact occurrences preserve existing behavior
    8. validator is actually consulted before application
    9. repeated execution produces deterministic results
    10. existing Prompt 475 behavior remains compatible (non-guarded
        apply_correction_request is untouched)

Prompt 482 additions - verification gate after application:
    11. valid exact correction -> APPLIED
    12. valid correction passes verification
    13. invalid produced result -> FAILED (verification catches it)
    14. failed verification cannot produce APPLIED
    15. original target is preserved on verification failure
    16. corrected target is preserved on verification success
    17. match count remains correct on verification success
    18. match_count is 0 for a verification-failure FAILED result
    19. no correction is retried after failed verification
    20. repeated execution remains deterministic (verification path)

Run directly:
    python -m unittest tests.test_correction_application_guarded -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest
from unittest import mock

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
from language_intelligence import correction_application_guarded
from language_intelligence.correction_application_guarded import (
    apply_correction_request_with_validation,
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


class TestApplyCorrectionRequestWithValidation(unittest.TestCase):

    def test_ready_validation_applies_correction(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request_with_validation(
            request, "I saw a dgo today.",
        )
        self.assertEqual(result.status, STATUS_APPLIED)
        self.assertTrue(result.applied)
        self.assertEqual(result.corrected_text, "I saw a dog today.")

    def test_not_ready_validation_does_not_apply(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request_with_validation(
            request, "I saw a cat today.",
        )
        self.assertEqual(result.status, STATUS_NOT_APPLIED)
        self.assertFalse(result.applied)

    def test_invalid_validation_produces_failed(self):
        request = CorrectionApplicationRequest(is_valid=False)
        result = apply_correction_request_with_validation(
            request, "some text",
        )
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertFalse(result.applied)

    def test_invalid_non_string_target_produces_failed(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request_with_validation(request, None)
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertFalse(result.applied)
        self.assertIsNone(result.original_text)

    def test_target_text_unchanged_when_not_ready(self):
        request = _ready_request(key="dgo", meaning="dog")
        target = "no matching expression here"
        result = apply_correction_request_with_validation(request, target)
        self.assertEqual(result.original_text, target)
        self.assertEqual(result.corrected_text, target)
        self.assertEqual(target, "no matching expression here")

    def test_target_text_unchanged_when_invalid(self):
        request = CorrectionApplicationRequest(is_valid=False)
        target = "some text"
        result = apply_correction_request_with_validation(request, target)
        self.assertEqual(result.original_text, target)
        self.assertIsNone(result.corrected_text)
        self.assertEqual(target, "some text")

    def test_successful_exact_replacement_still_works(self):
        request = _ready_request(key="teh", meaning="the")
        result = apply_correction_request_with_validation(
            request, "teh quick fox",
        )
        self.assertEqual(result.status, STATUS_APPLIED)
        self.assertEqual(result.corrected_text, "the quick fox")

    def test_multiple_exact_occurrences_preserved(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request_with_validation(
            request, "dgo dgo dgo saw another dgo",
        )
        self.assertEqual(result.status, STATUS_APPLIED)
        self.assertEqual(result.corrected_text, "dog dog dog saw another dog")
        self.assertEqual(result.metadata.get("occurrences_replaced"), 4)

    def test_validator_is_consulted_before_application(self):
        request = _ready_request(key="dgo", meaning="dog")
        with mock.patch.object(
            correction_application_guarded,
            "validate_correction_application_target",
            wraps=correction_application_guarded.validate_correction_application_target,
        ) as spy:
            apply_correction_request_with_validation(request, "a dgo")
            self.assertTrue(spy.called)

    def test_apply_not_called_when_validation_rejects(self):
        request = _ready_request(key="dgo", meaning="dog")
        with mock.patch.object(
            correction_application_guarded,
            "apply_correction_request",
        ) as spy:
            apply_correction_request_with_validation(request, "no match here")
            spy.assert_not_called()

    def test_repeated_execution_is_deterministic(self):
        request = _ready_request(key="dgo", meaning="dog")
        target = "a dgo walked by"
        first = apply_correction_request_with_validation(request, target)
        second = apply_correction_request_with_validation(request, target)
        self.assertEqual(first, second)

    def test_repeated_execution_deterministic_for_rejected_cases(self):
        request = CorrectionApplicationRequest(is_valid=False)
        first = apply_correction_request_with_validation(request, "text")
        second = apply_correction_request_with_validation(request, "text")
        self.assertEqual(first, second)

    def test_applied_result_reports_match_details(self):
        # Prompt 478: the guarded APPLIED result also carries
        # matched_text / replacement_text / match_count, passed
        # through unchanged from the delegated Prompt 475 call.
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request_with_validation(request, "a dgo")
        self.assertEqual(result.matched_text, "dgo")
        self.assertEqual(result.replacement_text, "dog")
        self.assertEqual(result.match_count, 1)

    def test_not_ready_result_has_zero_match_count(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request_with_validation(
            request, "no match here",
        )
        self.assertEqual(result.match_count, 0)

    def test_invalid_result_has_zero_match_count(self):
        request = CorrectionApplicationRequest(is_valid=False)
        result = apply_correction_request_with_validation(request, "text")
        self.assertEqual(result.match_count, 0)

    def test_applied_result_preserves_before_and_after_text(self):
        # Prompt 479: passed through unchanged from the delegated
        # Prompt 475 call.
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request_with_validation(request, "a dgo")
        self.assertEqual(result.text_before, "a dgo")
        self.assertEqual(result.text_after, "a dog")

    def test_invalid_result_preserves_safe_before_after_state(self):
        request = CorrectionApplicationRequest(is_valid=False)
        result = apply_correction_request_with_validation(request, "text")
        self.assertEqual(result.text_before, "text")
        self.assertEqual(result.text_after, "text")

    def test_prompt_475_behavior_remains_compatible(self):
        # The existing, unguarded Prompt 475 operation is untouched
        # and still behaves exactly as before.
        request = _ready_request(key="dgo", meaning="dog")
        direct = apply_correction_request(request, "a dgo here")
        guarded = apply_correction_request_with_validation(
            request, "a dgo here",
        )
        self.assertEqual(direct, guarded)

    # -- Prompt 482: verification gate after application --

    def test_valid_exact_correction_is_applied(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request_with_validation(
            request, "a dgo here",
        )
        self.assertEqual(result.status, STATUS_APPLIED)
        self.assertTrue(result.applied)

    def test_valid_correction_passes_verification(self):
        # A genuinely correct APPLIED result is never rejected by the
        # verification gate.
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request_with_validation(
            request, "a dgo here",
        )
        self.assertEqual(result.status, STATUS_APPLIED)
        self.assertEqual(result.matched_text, "dgo")
        self.assertEqual(result.replacement_text, "dog")

    def test_invalid_produced_result_becomes_failed(self):
        request = _ready_request(key="dgo", meaning="dog")
        tampered = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="a dgo here",
            corrected_text="a dog here",
            matched_text="wrong-expression",  # inconsistent with request
            replacement_text="dog",
            match_count=1,
            text_before="a dgo here",
            text_after="a dog here",
        )
        with mock.patch.object(
            correction_application_guarded, "apply_correction_request",
            return_value=tampered,
        ):
            result = apply_correction_request_with_validation(
                request, "a dgo here",
            )
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertFalse(result.applied)
        self.assertEqual(result.match_count, 0)
        self.assertIsNotNone(result.reason)

    def test_failed_verification_cannot_produce_applied(self):
        request = _ready_request(key="dgo", meaning="dog")
        tampered = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="a dgo here",
            corrected_text="something unrelated",
            matched_text="dgo",
            replacement_text="dog",
            match_count=1,
            text_before="a dgo here",
            text_after="something unrelated",
        )
        with mock.patch.object(
            correction_application_guarded, "apply_correction_request",
            return_value=tampered,
        ):
            result = apply_correction_request_with_validation(
                request, "a dgo here",
            )
        self.assertNotEqual(result.status, STATUS_APPLIED)
        self.assertFalse(result.applied)

    def test_original_target_preserved_on_verification_failure(self):
        request = _ready_request(key="dgo", meaning="dog")
        tampered = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="a dgo here",
            corrected_text="a dog here",
            matched_text="wrong-expression",
            replacement_text="dog",
            match_count=1,
            text_before="a dgo here",
            text_after="a dog here",
        )
        with mock.patch.object(
            correction_application_guarded, "apply_correction_request",
            return_value=tampered,
        ):
            result = apply_correction_request_with_validation(
                request, "a dgo here",
            )
        self.assertEqual(result.original_text, "a dgo here")

    def test_corrected_target_preserved_on_verification_success(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request_with_validation(
            request, "a dgo here",
        )
        self.assertEqual(result.corrected_text, "a dog here")

    def test_match_count_correct_on_verification_success(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request_with_validation(
            request, "dgo dgo dgo",
        )
        self.assertEqual(result.match_count, 3)

    def test_match_count_zero_on_verification_failure(self):
        request = _ready_request(key="dgo", meaning="dog")
        tampered = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="a dgo here",
            corrected_text="a dog here",
            matched_text="wrong-expression",
            replacement_text="dog",
            match_count=5,
            text_before="a dgo here",
            text_after="a dog here",
        )
        with mock.patch.object(
            correction_application_guarded, "apply_correction_request",
            return_value=tampered,
        ):
            result = apply_correction_request_with_validation(
                request, "a dgo here",
            )
        self.assertEqual(result.match_count, 0)

    def test_no_correction_retried_after_failed_verification(self):
        request = _ready_request(key="dgo", meaning="dog")
        tampered = CorrectionApplicationResult(
            STATUS_APPLIED,
            original_text="a dgo here",
            corrected_text="a dog here",
            matched_text="wrong-expression",
            replacement_text="dog",
            match_count=1,
            text_before="a dgo here",
            text_after="a dog here",
        )
        with mock.patch.object(
            correction_application_guarded, "apply_correction_request",
            return_value=tampered,
        ) as spy:
            apply_correction_request_with_validation(request, "a dgo here")
            self.assertEqual(spy.call_count, 1)

    def test_repeated_execution_deterministic_with_verification(self):
        request = _ready_request(key="dgo", meaning="dog")
        target = "a dgo here"
        first = apply_correction_request_with_validation(request, target)
        second = apply_correction_request_with_validation(request, target)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
