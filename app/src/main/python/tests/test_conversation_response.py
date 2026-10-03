"""
Tests for Prompt 431 - Unified Conversation Response.

`build_conversation_response()` (language_intelligence/
conversation_response.py) derives an immutable `ConversationResponse` from
a `ResponseGenerationResult` (via its Prompt 428 outcome and Prompt 430
validation); `LanguageIntelligenceCore` exposes it through
`get_last_conversation_response()` / `generate_conversation_response()`.

Run directly:
    python -m unittest tests.test_conversation_response -v
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.conversation_response import ConversationResponse, build_conversation_response
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult, STATUS_DEFERRED, STATUS_GENERATED,
    STATUS_MODEL_FAILED,
)
from language_intelligence.response_generation_outcome import (
    STATUS_SUCCESS, STATUS_FALLBACK, STATUS_FAILED, STATUS_UNRESOLVED,
)
from language_intelligence import response_generation_validation as rgv

from tests.test_core_response_generation_outcome import OutcomeCoreCase
from tests.test_pre_inference_readiness_guard import MODEL_TEXT, MESSAGE, _core

FAILURE = {"error_code": "timed_out", "inference_status": "timeout", "reason": "the model timed out"}


def success_result(text="hello there", metadata=None):
    return ResponseGenerationResult(STATUS_GENERATED, response_text=text, reason="ok",
                                    backend_kind=BACKEND_KIND_LOCAL_MODEL, metadata=metadata,
                                    selected_backend_kind=BACKEND_KIND_LOCAL_MODEL)


def fallback_result(text=None):
    return ResponseGenerationResult(
        STATUS_MODEL_FAILED, response_text=text, reason="failed", backend_kind=BACKEND_KIND_LOCAL_MODEL,
        inference_status="timeout", error_code="timed_out",
        fallback_backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)


def failed_result():
    return ResponseGenerationResult(
        STATUS_MODEL_FAILED, backend_kind=BACKEND_KIND_LOCAL_MODEL, reason="the model timed out",
        inference_status="timeout", error_code="timed_out")


def unresolved_result():
    return ResponseGenerationResult(STATUS_DEFERRED, reason="deferred",
                                    backend_kind=BACKEND_KIND_DETERMINISTIC_FALLBACK)


class TestConversions(unittest.TestCase):
    def test_success(self):
        response = build_conversation_response(success_result())
        self.assertIsInstance(response, ConversationResponse)
        self.assertEqual(response.status, STATUS_SUCCESS)
        self.assertEqual(response.response_text, "hello there")
        self.assertTrue(response.valid)
        self.assertEqual(response.validation_issues, ())
        self.assertFalse(response.fallback_used)
        self.assertIsNone(response.failure_reason)

    def test_fallback(self):
        response = build_conversation_response(fallback_result("fallback reply"))
        self.assertEqual(response.status, STATUS_FALLBACK)
        self.assertTrue(response.fallback_used)
        self.assertEqual(response.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(response.generation_backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(response.response_text, "fallback reply")
        self.assertTrue(response.valid)

    def test_fallback_without_text_stays_textless_and_is_marked_invalid(self):
        response = build_conversation_response(fallback_result(None))
        self.assertEqual(response.status, STATUS_FALLBACK)
        self.assertIsNone(response.response_text)
        self.assertFalse(response.valid)
        self.assertEqual(response.validation_issues, (rgv.ISSUE_FALLBACK_WITHOUT_TEXT,))

    def test_failed(self):
        response = build_conversation_response(failed_result())
        self.assertEqual(response.status, STATUS_FAILED)
        self.assertIsNone(response.response_text)
        self.assertFalse(response.fallback_used)
        self.assertEqual(dict(response.failure_reason), FAILURE)
        self.assertTrue(response.valid)

    def test_unresolved(self):
        response = build_conversation_response(unresolved_result())
        self.assertEqual(response.status, STATUS_UNRESOLVED)
        self.assertIsNone(response.response_text)
        self.assertIsNone(response.failure_reason)
        self.assertFalse(response.fallback_used)
        self.assertTrue(response.valid)


class TestPreservation(unittest.TestCase):
    def test_response_text_is_preserved_exactly(self):
        for text in ("  padded \n", "Zażółć — سلام — 你好", "a\nb"):
            with self.subTest(text=text):
                self.assertEqual(build_conversation_response(success_result(text)).response_text, text)

    def test_metadata_is_preserved(self):
        metadata = {"model_id": "m", "elapsed_seconds": 0.5, "nested": {"k": [1, 2]}}
        response = build_conversation_response(success_result(metadata=metadata))
        self.assertEqual(dict(response.metadata), metadata)
        self.assertEqual(response.to_dict()["metadata"], metadata)

    def test_backend_fields_are_preserved(self):
        response = build_conversation_response(success_result())
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(response.generation_backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(response.selected_backend_kind, BACKEND_KIND_LOCAL_MODEL)

    def test_every_result_field_is_carried(self):
        result = fallback_result()
        response = build_conversation_response(result)
        self.assertEqual(response.generation_status, result.status)
        self.assertEqual(response.reason, result.reason)
        self.assertEqual(response.inference_status, result.inference_status)
        self.assertEqual(response.error_code, result.error_code)
        self.assertEqual(response.fallback_backend_kind, result.fallback_backend_kind)

    def test_no_request_means_no_language_or_locale(self):
        response = build_conversation_response(success_result())
        self.assertIsNone(response.language)
        self.assertIsNone(response.locale)

    def test_conversion_is_deterministic(self):
        result = failed_result()
        self.assertEqual(build_conversation_response(result).to_dict(),
                         build_conversation_response(result).to_dict())

    def test_rejects_bad_inputs(self):
        with self.assertRaises(TypeError):
            build_conversation_response("text")
        with self.assertRaises(TypeError):
            build_conversation_response(success_result(), request="request")


class TestNoInventedText(unittest.TestCase):
    def test_failed_never_becomes_success(self):
        for result in (failed_result(), ResponseGenerationResult(STATUS_MODEL_FAILED)):
            with self.subTest(reason=result.reason):
                response = build_conversation_response(result)
                self.assertNotEqual(response.status, STATUS_SUCCESS)
                self.assertIsNone(response.response_text)

    def test_unresolved_stays_unresolved(self):
        response = build_conversation_response(unresolved_result())
        self.assertEqual((response.status, response.response_text), (STATUS_UNRESOLVED, None))

    def test_empty_or_invalid_generated_text_stays_invalid(self):
        for text in (None, "", "   "):
            with self.subTest(text=text):
                result = ResponseGenerationResult(STATUS_GENERATED, response_text=text,
                                                  backend_kind=BACKEND_KIND_LOCAL_MODEL)
                response = build_conversation_response(result)
                self.assertFalse(response.valid)
                self.assertIn(rgv.ISSUE_GENERATED_WITHOUT_TEXT, response.validation_issues)
                self.assertNotEqual(response.status, STATUS_SUCCESS)
                self.assertIsNone(response.response_text)

    def test_failed_without_reason_is_invalid_not_success(self):
        response = build_conversation_response(ResponseGenerationResult(STATUS_MODEL_FAILED))
        self.assertEqual(response.status, STATUS_FAILED)
        self.assertEqual(response.validation_issues, (rgv.ISSUE_FAILED_WITHOUT_REASON,))


class TestImmutabilityAndNoSharedState(unittest.TestCase):
    def test_attributes_cannot_be_set_or_deleted(self):
        response = build_conversation_response(success_result())
        with self.assertRaises(AttributeError):
            response.response_text = "changed"
        with self.assertRaises(AttributeError):
            response.status = STATUS_FAILED
        with self.assertRaises(AttributeError):
            del response.status
        with self.assertRaises(AttributeError):
            response.extra = 1

    def test_metadata_and_failure_reason_are_read_only(self):
        with_metadata = build_conversation_response(success_result(metadata={"model_id": "m"}))
        with self.assertRaises(TypeError):
            with_metadata.metadata["model_id"] = "changed"
        failed = build_conversation_response(failed_result())
        with self.assertRaises(TypeError):
            failed.failure_reason["reason"] = "changed"

    def test_internal_result_state_is_protected(self):
        result = success_result(metadata={"model_id": "m", "nested": {"k": [1]}})
        before = copy.deepcopy(result.to_dict())
        response = build_conversation_response(result)
        result.metadata["nested"]["k"].append(2)  # later internal change
        self.assertEqual(response.metadata["nested"]["k"], [1])
        data = response.to_dict()
        data["metadata"]["nested"]["k"].append(3)
        data["response_text"] = "changed"
        self.assertEqual(response.metadata["nested"]["k"], [1])
        self.assertEqual(response.response_text, "hello there")
        result.metadata["nested"]["k"].remove(2)
        self.assertEqual(result.to_dict(), before)

    def test_building_does_not_mutate_the_result(self):
        for result in (success_result(metadata={"m": 1}), fallback_result(), failed_result(),
                       unresolved_result()):
            before = copy.deepcopy(result.to_dict())
            build_conversation_response(result)
            self.assertEqual(result.to_dict(), before)


class TestCoreIntegration(OutcomeCoreCase):
    def test_success_through_core(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        result = core.generate_response(self.understanding())
        response = core.get_last_conversation_response()
        self.assertEqual((response.status, response.response_text), (STATUS_SUCCESS, MODEL_TEXT))
        self.assertEqual(response.response_text, result.response_text)
        self.assertTrue(response.valid)
        self.assertEqual(dict(response.metadata), result.metadata)

    def test_fallback_through_core(self):
        core = self.core(self.blocked_runtime(), with_fallback=True)
        result = core.generate_response(self.understanding())
        response = core.get_last_conversation_response()
        self.assertEqual(response.status, STATUS_FALLBACK)
        self.assertTrue(response.fallback_used)
        self.assertEqual(response.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertIsNone(response.response_text)  # nothing invented
        self.assertEqual(response.selected_backend_kind, result.selected_backend_kind)
        self.assertEqual(response.error_code, result.error_code)

    def test_failed_through_core(self):
        core = self.core(self.blocked_runtime(), with_fallback=False)
        result = core.generate_response(self.understanding())
        response = core.get_last_conversation_response()
        self.assertEqual(response.status, STATUS_FAILED)
        self.assertEqual(response.failure_reason["error_code"], result.error_code)
        self.assertIsNone(response.response_text)

    def test_unresolved_through_core(self):
        backend = DeterministicFallbackBackend(self.engine())
        core = LanguageIntelligenceCore(backend)
        core.generate_response(self.understanding())
        response = core.get_last_conversation_response()
        self.assertEqual((response.status, response.response_text), (STATUS_UNRESOLVED, None))

    def test_language_and_locale_through_core(self):
        understanding = self.planned_understanding()
        expected = ResponseGenerationRequest(understanding).generation_context
        core = self.core(self.ready_runtime(), with_fallback=True)
        core.generate_response(understanding)
        response = core.get_last_conversation_response()
        self.assertEqual((response.language, response.locale), (expected["language"], expected["locale"]))

    def test_generate_conversation_response_returns_the_stored_response(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        self.assertIsNone(core.get_last_conversation_response())
        response = core.generate_conversation_response(self.understanding())
        self.assertIs(response, core.get_last_conversation_response())
        self.assertEqual(response.response_text, MODEL_TEXT)

    def test_matches_the_recorded_outcome_and_validation(self):
        core = self.core(self.blocked_runtime(), with_fallback=True)
        core.generate_response(self.understanding())
        response = core.get_last_conversation_response()
        validation = core.get_last_response_generation_validation()
        self.assertEqual(response.valid, validation.valid)
        self.assertEqual(list(response.validation_issues), validation.issue_codes)
        self.assertEqual(response.status, core.get_last_response_generation_result().status)

    def test_reset_and_non_result_backend_return(self):
        backend = DeterministicFallbackBackend(self.engine())
        core = LanguageIntelligenceCore(backend)
        core.generate_response(self.understanding())
        self.assertIsNotNone(core.get_last_conversation_response())
        with mock.patch.object(backend, "generate_response", return_value=object()):
            core.generate_response(self.understanding())
        self.assertIsNone(core.get_last_conversation_response())

    def test_a_conversion_failure_never_breaks_generation(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        target = "language_intelligence.language_intelligence_core.build_conversation_response"
        with mock.patch(target, side_effect=RuntimeError("boom")):
            result = core.generate_response(self.understanding())
        self.assertEqual(result.response_text, MODEL_TEXT)
        self.assertIsNone(core.get_last_conversation_response())
        self.assertIsNotNone(core.get_last_response_generation_result())

    def test_generate_response_is_unchanged_for_existing_callers(self):
        core = self.core(self.ready_runtime(), with_fallback=True)
        result = core.generate_response(self.understanding())
        self.assertIsInstance(result, ResponseGenerationResult)
        self.assertEqual((result.status, result.response_text), (STATUS_GENERATED, MODEL_TEXT))
        result.response_text = "caller change"  # the raw result stays mutable, as before
        self.assertEqual(core.get_last_conversation_response().response_text, MODEL_TEXT)

    def test_the_conversation_reply_path_is_unchanged(self):
        control, _ = _core(self)
        expected = control.process_input(MESSAGE)
        core, _ = _core(self)
        reply = core.process_input(MESSAGE)
        self.assertEqual(reply, expected)
        self.assertIsInstance(core.get_last_language_response(), ResponseGenerationResult)
        self.assertIsNotNone(core.language_intelligence.get_last_conversation_response())

    @staticmethod
    def engine():
        from understanding.engine import UnderstandingEngine
        return UnderstandingEngine()


if __name__ == "__main__":
    unittest.main()
