"""
Tests for Prompt 430 - Response-Generation Result Validation.

`validate_response_generation_result()` (language_intelligence/
response_generation_validation.py) deterministically checks a
`ResponseGenerationResult` and its Prompt 428 `ResponseGenerationOutcome`
for internal consistency and reports a `ResponseGenerationValidation`.
`LanguageIntelligenceCore.generate_response()` records it as
`get_last_response_generation_validation()`.

Run directly:
    python -m unittest tests.test_response_generation_validation -v
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult, STATUS_DEFERRED, STATUS_GENERATED,
    STATUS_NOT_IMPLEMENTED, STATUS_MODEL_FAILED,
)
from language_intelligence.response_generation_outcome import (
    ResponseGenerationOutcome, build_response_generation_outcome,
    STATUS_SUCCESS, STATUS_FALLBACK, STATUS_FAILED, STATUS_UNRESOLVED,
)
from language_intelligence import response_generation_validation as rgv
from language_intelligence.response_generation_validation import (
    ResponseGenerationValidation, validate_response_generation_result,
    VALIDATION_VALID, VALIDATION_INVALID,
)

from tests.test_core_response_generation_outcome import OutcomeCoreCase
from tests.test_pre_inference_readiness_guard import MODEL_TEXT

FAILURE = {"error_code": "timed_out", "inference_status": "timeout", "reason": "the model timed out"}


def success_result(text="hello there", metadata=None):
    return ResponseGenerationResult(STATUS_GENERATED, response_text=text, reason="ok",
                                    backend_kind=BACKEND_KIND_LOCAL_MODEL, metadata=metadata)


def fallback_result(text="fallback reply"):
    return ResponseGenerationResult(
        STATUS_MODEL_FAILED, response_text=text, reason="failed", backend_kind=BACKEND_KIND_LOCAL_MODEL,
        inference_status="timeout", error_code="timed_out",
        fallback_backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)


def failed_result(**overrides):
    values = dict(status=STATUS_MODEL_FAILED, backend_kind=BACKEND_KIND_LOCAL_MODEL,
                  reason="the model timed out", inference_status="timeout", error_code="timed_out")
    values.update(overrides)
    return ResponseGenerationResult(**values)


def unresolved_result():
    return ResponseGenerationResult(STATUS_DEFERRED, reason="deferred",
                                    backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)


class TestValidResults(unittest.TestCase):
    def check_valid(self, result):
        validation = validate_response_generation_result(result)
        self.assertEqual(validation.status, VALIDATION_VALID, validation.issues)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.issues, [])
        return validation

    def test_valid_success(self):
        validation = self.check_valid(success_result())
        self.assertEqual(validation.outcome.status, STATUS_SUCCESS)

    def test_valid_fallback(self):
        validation = self.check_valid(fallback_result())
        self.assertEqual(validation.outcome.status, STATUS_FALLBACK)
        self.assertTrue(validation.outcome.fallback_used)

    def test_valid_failed(self):
        validation = self.check_valid(failed_result())
        self.assertEqual(validation.outcome.status, STATUS_FAILED)
        self.assertEqual(validation.outcome.failure_reason, FAILURE)

    def test_valid_unresolved(self):
        for result in (unresolved_result(), ResponseGenerationResult(STATUS_NOT_IMPLEMENTED)):
            with self.subTest(status=result.status):
                validation = self.check_valid(result)
                self.assertEqual(validation.outcome.status, STATUS_UNRESOLVED)
                self.assertIsNone(validation.outcome.generated_text)


class TestInvalidSuccess(unittest.TestCase):
    def test_success_outcome_without_text(self):
        for text in (None, "", "   \n"):
            with self.subTest(text=text):
                outcome = ResponseGenerationOutcome(STATUS_SUCCESS, generated_text=text,
                                                    backend_kind=BACKEND_KIND_LOCAL_MODEL)
                validation = validate_response_generation_result(success_result(), outcome=outcome)
                self.assertFalse(validation.valid)
                self.assertIn(rgv.ISSUE_SUCCESS_WITHOUT_TEXT, validation.issue_codes)

    def test_success_outcome_with_a_failure_reason(self):
        outcome = ResponseGenerationOutcome(STATUS_SUCCESS, generated_text="hi", failure_reason=FAILURE)
        validation = validate_response_generation_result(success_result("hi"), outcome=outcome)
        self.assertIn(rgv.ISSUE_SUCCESS_WITH_FAILURE, validation.issue_codes)

    def test_success_outcome_with_fallback_used(self):
        outcome = ResponseGenerationOutcome(STATUS_SUCCESS, generated_text="hi", fallback_used=True)
        validation = validate_response_generation_result(success_result("hi"), outcome=outcome)
        self.assertIn(rgv.ISSUE_SUCCESS_WITH_FALLBACK, validation.issue_codes)

    def test_generated_result_without_text_is_invalid_and_not_turned_into_success(self):
        for text in (None, "", "  "):
            with self.subTest(text=text):
                result = ResponseGenerationResult(STATUS_GENERATED, response_text=text,
                                                  backend_kind=BACKEND_KIND_LOCAL_MODEL)
                validation = validate_response_generation_result(result)
                self.assertFalse(validation.valid)
                self.assertIn(rgv.ISSUE_GENERATED_WITHOUT_TEXT, validation.issue_codes)
                self.assertNotEqual(validation.outcome.status, STATUS_SUCCESS)
                self.assertIsNone(validation.outcome.generated_text)


class TestInvalidFallback(unittest.TestCase):
    def test_fallback_without_fallback_used(self):
        outcome = ResponseGenerationOutcome(STATUS_FALLBACK, generated_text="reply",
                                            backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK,
                                            fallback_used=False)
        validation = validate_response_generation_result(fallback_result(), outcome=outcome)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.issue_codes, [rgv.ISSUE_FALLBACK_NOT_USED])

    def test_fallback_without_text(self):
        validation = validate_response_generation_result(fallback_result(text=None))
        self.assertFalse(validation.valid)
        self.assertEqual(validation.issue_codes, [rgv.ISSUE_FALLBACK_WITHOUT_TEXT])
        self.assertIsNone(validation.outcome.generated_text)  # nothing invented


class TestInvalidFailedAndUnresolved(unittest.TestCase):
    def test_failed_without_failure_reason(self):
        result = ResponseGenerationResult(STATUS_MODEL_FAILED, backend_kind=BACKEND_KIND_LOCAL_MODEL)
        validation = validate_response_generation_result(result)
        self.assertEqual(validation.outcome.status, STATUS_FAILED)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.issue_codes, [rgv.ISSUE_FAILED_WITHOUT_REASON])

    def test_failed_is_never_a_generated_response(self):
        outcome = ResponseGenerationOutcome(STATUS_FAILED, generated_text="oops", failure_reason=FAILURE)
        validation = validate_response_generation_result(failed_result(), outcome=outcome)
        self.assertIn(rgv.ISSUE_FAILED_WITH_TEXT, validation.issue_codes)

    def test_failed_result_carrying_text_is_invalid(self):
        validation = validate_response_generation_result(failed_result(response_text="model text"))
        self.assertIn(rgv.ISSUE_TEXT_ON_FAILURE, validation.issue_codes)

    def test_unresolved_with_text_is_invalid(self):
        result = ResponseGenerationResult(STATUS_DEFERRED, response_text="invented")
        validation = validate_response_generation_result(result)
        self.assertFalse(validation.valid)
        self.assertIn(rgv.ISSUE_TEXT_ON_UNRESOLVED, validation.issue_codes)
        outcome = ResponseGenerationOutcome(STATUS_UNRESOLVED, generated_text="invented")
        codes = validate_response_generation_result(unresolved_result(), outcome=outcome).issue_codes
        self.assertEqual(codes, [rgv.ISSUE_UNRESOLVED_WITH_TEXT])

    def test_unresolved_with_failure_or_fallback_is_invalid(self):
        outcome = ResponseGenerationOutcome(STATUS_UNRESOLVED, failure_reason=FAILURE, fallback_used=True)
        codes = validate_response_generation_result(unresolved_result(), outcome=outcome).issue_codes
        self.assertEqual(set(codes), {rgv.ISSUE_UNRESOLVED_WITH_FAILURE, rgv.ISSUE_UNRESOLVED_WITH_FALLBACK})


class TestPreservationAndInvalidHandling(unittest.TestCase):
    def test_valid_result_fields_are_preserved_exactly(self):
        result = success_result("Zażółć — سلام — 你好\n", metadata={"model_id": "m", "elapsed_seconds": 0.5})
        outcome = ResponseGenerationOutcome(
            STATUS_SUCCESS, generated_text=result.response_text, backend_kind=BACKEND_KIND_LOCAL_MODEL,
            language="fa", locale="fa-IR", metadata=result.metadata)
        before = copy.deepcopy(outcome.to_dict())
        validation = validate_response_generation_result(result, outcome=outcome)
        self.assertTrue(validation.valid)
        self.assertIs(validation.outcome, outcome)
        self.assertEqual(validation.outcome.to_dict(), before)
        self.assertEqual(validation.outcome.generated_text, "Zażółć — سلام — 你好\n")
        self.assertEqual((validation.outcome.language, validation.outcome.locale), ("fa", "fa-IR"))
        self.assertEqual(validation.outcome.metadata, {"model_id": "m", "elapsed_seconds": 0.5})

    def test_valid_failed_fields_are_preserved(self):
        validation = validate_response_generation_result(failed_result())
        self.assertEqual(validation.outcome.failure_reason, FAILURE)
        self.assertEqual(validation.outcome.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertFalse(validation.outcome.fallback_used)

    def test_invalid_result_keeps_the_original_information(self):
        outcome = ResponseGenerationOutcome(STATUS_SUCCESS, generated_text=None,
                                            backend_kind=BACKEND_KIND_LOCAL_MODEL, language="en")
        result = success_result()
        validation = validate_response_generation_result(result, outcome=outcome)
        self.assertFalse(validation.valid)
        self.assertIs(validation.outcome, outcome)  # never repaired or replaced
        self.assertEqual(validation.outcome.language, "en")
        self.assertEqual(validation.result, result.to_dict())
        self.assertEqual(validation.to_dict()["status"], VALIDATION_INVALID)

    def test_a_non_result_is_reported_not_raised(self):
        for value in (None, "text", object(), {"status": "generated"}):
            with self.subTest(value=value):
                validation = validate_response_generation_result(value)
                self.assertEqual(validation.issue_codes, [rgv.ISSUE_NOT_A_RESULT])
                self.assertIsNone(validation.outcome)
                self.assertIsNone(validation.result)

    def test_an_unknown_status_is_invalid(self):
        validation = validate_response_generation_result(ResponseGenerationResult("bogus"))
        self.assertIn(rgv.ISSUE_UNKNOWN_STATUS, validation.issue_codes)

    def test_no_text_is_invented_for_any_invalid_result(self):
        results = (
            ResponseGenerationResult(STATUS_GENERATED, response_text=None),
            ResponseGenerationResult(STATUS_MODEL_FAILED),
            fallback_result(text=None),
            unresolved_result(),
        )
        for result in results:
            with self.subTest(status=result.status):
                validation = validate_response_generation_result(result)
                self.assertIsNone(validation.outcome.generated_text)
                self.assertIsNone(result.response_text)

    def test_validation_is_deterministic_and_does_not_mutate(self):
        result = failed_result(metadata={"model_id": "m"})
        outcome = build_response_generation_outcome(result)
        before = (copy.deepcopy(result.to_dict()), copy.deepcopy(outcome.to_dict()))
        first = validate_response_generation_result(result, outcome=outcome).to_dict()
        second = validate_response_generation_result(result, outcome=outcome).to_dict()
        self.assertEqual(first, second)
        self.assertEqual((result.to_dict(), outcome.to_dict()), before)

    def test_validation_constructor_rejects_an_unknown_status(self):
        with self.assertRaises(ValueError):
            ResponseGenerationValidation("MAYBE")


class TestCoreIntegration(OutcomeCoreCase):
    def test_success_is_valid_and_carries_the_recorded_outcome(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        response = core.generate_response(self.understanding())
        validation = core.get_last_response_generation_validation()
        self.assertIsInstance(validation, ResponseGenerationValidation)
        self.assertTrue(validation.valid, validation.issues)
        self.assertIs(validation.outcome, core.get_last_response_generation_result())
        self.assertEqual(validation.outcome.generated_text, MODEL_TEXT)
        self.assertEqual(response.response_text, MODEL_TEXT)

    def test_failed_and_unresolved_are_valid(self):
        failed = self.core(self.blocked_runtime(), with_fallback=False)
        failed.generate_response(self.understanding())
        self.assertTrue(failed.get_last_response_generation_validation().valid)
        self.assertEqual(failed.get_last_response_generation_result().status, STATUS_FAILED)
        unresolved = LanguageIntelligenceCore(DeterministicFallbackBackend(self.engine()))
        unresolved.generate_response(self.understanding())
        self.assertTrue(unresolved.get_last_response_generation_validation().valid)
        self.assertEqual(unresolved.get_last_response_generation_result().status, STATUS_UNRESOLVED)

    def test_a_real_fallback_carries_no_text_and_is_reported_invalid_without_changing_anything(self):
        core = self.core(self.blocked_runtime(), with_fallback=True)
        response = core.generate_response(self.understanding())
        validation = core.get_last_response_generation_validation()
        self.assertEqual(validation.issue_codes, [rgv.ISSUE_FALLBACK_WITHOUT_TEXT])
        # reporting only: same result, same outcome, still no text invented
        self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertIsNone(response.response_text)
        self.assertEqual(core.get_last_response_generation_result().status, STATUS_FALLBACK)
        self.assertIs(validation.outcome, core.get_last_response_generation_result())

    def test_none_before_the_first_response_and_reset_on_a_raising_backend(self):
        core = self.core(self.ready_runtime(), with_fallback=False)
        self.assertIsNone(core.get_last_response_generation_validation())
        core.generate_response(self.understanding())
        self.assertIsNotNone(core.get_last_response_generation_validation())
        with mock.patch.object(core.backend, "generate_response", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                core.generate_response(self.understanding())
        self.assertIsNone(core.get_last_response_generation_validation())

    def test_a_non_result_backend_return_is_reported_invalid(self):
        backend = DeterministicFallbackBackend(self.engine())
        core = LanguageIntelligenceCore(backend)
        sentinel = object()
        with mock.patch.object(backend, "generate_response", return_value=sentinel):
            self.assertIs(core.generate_response(self.understanding()), sentinel)
        self.assertEqual(core.get_last_response_generation_validation().issue_codes,
                         [rgv.ISSUE_NOT_A_RESULT])

    def test_a_validator_failure_never_breaks_generation(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        target = "language_intelligence.language_intelligence_core.validate_response_generation_result"
        with mock.patch(target, side_effect=RuntimeError("boom")):
            response = core.generate_response(self.understanding())
        self.assertEqual(response.response_text, MODEL_TEXT)
        self.assertIsNotNone(core.get_last_response_generation_result())
        self.assertIsNone(core.get_last_response_generation_validation())

    def test_returned_result_and_request_are_not_mutated(self):
        understanding = self.planned_understanding()
        request = ResponseGenerationRequest(understanding)
        before = (copy.deepcopy(understanding.to_dict()), copy.deepcopy(request.generation_context))
        core = self.core(self.ready_runtime(), with_fallback=True)
        response = core.generate_response(understanding)
        result_before = copy.deepcopy(response.to_dict())
        core.get_last_response_generation_validation().to_dict()
        self.assertEqual(response.to_dict(), result_before)
        self.assertEqual((understanding.to_dict(), request.generation_context), before)

    def test_language_and_locale_survive_validation(self):
        understanding = self.planned_understanding()
        expected = ResponseGenerationRequest(understanding).generation_context
        core = self.core(self.ready_runtime(), with_fallback=True)
        core.generate_response(understanding)
        outcome = core.get_last_response_generation_validation().outcome
        self.assertEqual((outcome.language, outcome.locale), (expected["language"], expected["locale"]))

    @staticmethod
    def engine():
        from understanding.engine import UnderstandingEngine
        return UnderstandingEngine()


if __name__ == "__main__":
    unittest.main()
