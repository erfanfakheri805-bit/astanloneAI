"""
Tests for Prompt 410 - Local Inference Resource Guard.

After the readiness check (Prompt 409), `LocalLanguageModelBackend.generate_response()`
asks the provider whether the built request is within the model's configured
limits (the runtime's existing output-token / timeout / context checks). A request
over a limit never reaches provider.generate()/the runtime's load or inference and
comes back as the existing structured STATUS_RESOURCE_LIMIT failure, so Prompt 406's
fallback applies unchanged. Test doubles only at the runtime boundary - no model.

Run directly:
    python -m unittest tests.test_local_inference_resource_guard -v
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.local_model_mapping import build_inference_request, map_inference_result
from language_intelligence.local_model_provider import LocalModelProvider, RuntimeBackedProvider
from language_intelligence.inference import (
    GenerationParameters, InferenceRequest, STATUS_SUCCESS, STATUS_RESOURCE_LIMIT as INF_RESOURCE,
    STATUS_MODEL_NOT_CONFIGURED as INF_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE as INF_UNAVAILABLE,
    ERROR_CONTEXT_LENGTH_EXCEEDED, ERROR_MAX_OUTPUT_TOKENS_EXCEEDED, ERROR_TIMEOUT_EXCEEDS_LIMIT,
    ERROR_NO_CONFIGURATION, ERROR_RUNTIME_DEPENDENCY_MISSING,
)
from language_intelligence.response_generation import (
    STATUS_GENERATED, STATUS_MODEL_FAILED, STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE,
)
from tests.test_pre_inference_readiness_guard import (
    CountingRuntime, GuardCase, MESSAGE, MODEL_TEXT, _core,
)


class ResourceCase(GuardCase):
    def oversized_text(self):
        # context_length=512 tokens (~3 chars/token estimated): far above it
        return "word " * 2000

    def backend(self, runtime, **kwargs):
        return LocalLanguageModelBackend(runtime=runtime, **kwargs)


class TestWithinLimitsReachesInference(ResourceCase):
    """1. a request within the configured limits reaches inference normally"""

    def test_within_limits_is_generated_by_the_runtime(self):
        runtime = CountingRuntime(self.config())
        response = self.backend(runtime).generate_response(self.understanding())
        self.assertEqual((response.status, response.inference_status),
                         (STATUS_GENERATED, STATUS_SUCCESS))
        self.assertEqual(response.response_text, MODEL_TEXT)
        self.assertEqual((runtime.generate_calls, runtime.load_calls, runtime.inferences), (1, 1, 1))

    def test_explicit_output_size_at_the_limit_is_allowed(self):
        runtime = CountingRuntime(self.config(max_output_tokens=64))
        backend = self.backend(runtime, generation_parameters=GenerationParameters(max_output_tokens=64))
        self.assertEqual(backend.generate_response(self.understanding()).status, STATUS_GENERATED)
        self.assertEqual(runtime.inferences, 1)

    def test_check_request_limits_is_none_within_limits(self):
        runtime = CountingRuntime(self.config())
        request = build_inference_request(self.understanding(), None)
        self.assertIsNone(runtime.check_request_limits(request))
        self.assertEqual((runtime.load_calls, runtime.inferences), (0, 0))


class TestOversizedRequestRejectedBeforeInference(ResourceCase):
    """2. an oversized request is rejected before inference"""

    def test_oversized_input_never_reaches_provider_or_runtime(self):
        class SpyProvider(RuntimeBackedProvider):
            calls = 0

            def generate(self, request, cancellation_token=None):
                SpyProvider.calls += 1
                return super().generate(request, cancellation_token)

        runtime = CountingRuntime(self.config())
        response = LocalLanguageModelBackend(provider=SpyProvider(runtime)).generate_response(
            self.understanding(self.oversized_text()))
        self.assertEqual(SpyProvider.calls, 0)
        self.assertEqual((runtime.generate_calls, runtime.load_calls, runtime.inferences), (0, 0, 0))
        self.assertEqual(response.inference_status, INF_RESOURCE)
        self.assertEqual(response.error_code, ERROR_CONTEXT_LENGTH_EXCEEDED)
        self.assertIsNone(response.response_text)

    def test_the_same_request_still_fits_once_it_is_small(self):
        runtime = CountingRuntime(self.config())
        backend = self.backend(runtime)
        self.assertEqual(backend.generate_response(
            self.understanding(self.oversized_text())).inference_status, INF_RESOURCE)
        self.assertEqual(backend.generate_response(self.understanding()).status, STATUS_GENERATED)
        self.assertEqual(runtime.inferences, 1)

    def test_deterministic_repeated_rejections(self):
        runtime = CountingRuntime(self.config())
        backend = self.backend(runtime)
        results = [backend.generate_response(self.understanding(self.oversized_text()))
                   for _ in range(3)]
        self.assertEqual({(r.status, r.inference_status, r.error_code) for r in results}, {
            (STATUS_MODEL_FAILED, INF_RESOURCE, ERROR_CONTEXT_LENGTH_EXCEEDED)})
        self.assertEqual(runtime.reached_runtime(), 0)


class TestOversizedOutputConfigurationRejected(ResourceCase):
    """3. an oversized output (or timeout) configuration is rejected before inference"""

    def test_output_tokens_above_the_configured_limit(self):
        runtime = CountingRuntime(self.config(max_output_tokens=64))
        backend = self.backend(runtime, generation_parameters=GenerationParameters(max_output_tokens=65))
        response = backend.generate_response(self.understanding())
        self.assertEqual((response.inference_status, response.error_code),
                         (INF_RESOURCE, ERROR_MAX_OUTPUT_TOKENS_EXCEEDED))
        self.assertEqual(runtime.reached_runtime(), 0)

    def test_timeout_above_the_configured_limit(self):
        runtime = CountingRuntime(self.config(timeout_seconds=10.0))
        response = self.backend(runtime, timeout_seconds=11.0).generate_response(self.understanding())
        self.assertEqual((response.inference_status, response.error_code),
                         (INF_RESOURCE, ERROR_TIMEOUT_EXCEEDS_LIMIT))
        self.assertEqual(runtime.reached_runtime(), 0)


class TestResourceFailureIsTheExistingStructuredFailure(ResourceCase):
    """4. a resource-limit failure returns the existing structured failure type"""

    def test_status_code_backend_and_metadata(self):
        runtime = CountingRuntime(self.config())
        response = self.backend(runtime).generate_response(self.understanding(self.oversized_text()))
        self.assertEqual((response.status, response.inference_status), (STATUS_MODEL_FAILED, INF_RESOURCE))
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertTrue(response.reason)
        self.assertIn("provider_id", response.metadata)
        self.assertEqual(response.metadata["model_id"], "test-model")
        self.assertNotIn(MODEL_TEXT, str(response.to_dict()))

    def test_identical_to_what_the_runtime_itself_reports(self):
        runtime = CountingRuntime(self.config())
        understanding = self.understanding(self.oversized_text())
        guarded = self.backend(runtime).generate_response(understanding)
        direct = map_inference_result(
            runtime.generate(build_inference_request(understanding, None)), BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual((guarded.status, guarded.inference_status, guarded.error_code),
                         (direct.status, direct.inference_status, direct.error_code))

    def test_runtime_check_returns_the_same_result_generate_would(self):
        runtime = CountingRuntime(self.config(max_output_tokens=64))
        request = InferenceRequest("hello", parameters=GenerationParameters(max_output_tokens=200))
        checked = runtime.check_request_limits(request)
        actual = runtime.generate(request)
        self.assertEqual((checked.status, checked.error_code), (INF_RESOURCE, ERROR_MAX_OUTPUT_TOKENS_EXCEEDED))
        self.assertEqual((checked.status, checked.error_code, checked.details),
                         (actual.status, actual.error_code, actual.details))

    def test_check_never_answers_for_invalid_or_unconfigured(self):
        self.assertIsNone(CountingRuntime(self.config()).check_request_limits(InferenceRequest("")))
        self.assertIsNone(CountingRuntime(config=None).check_request_limits(InferenceRequest("hi")))
        self.assertIsNone(CountingRuntime(self.config()).check_request_limits(object()))

    def test_provider_without_an_opinion_does_not_block(self):
        class Plain(LocalModelProvider):
            generate_calls = 0

            @property
            def provider_id(self):
                return "plain"

            def availability(self):
                return CountingRuntime(GuardCase.config(self)).availability()

            def resource_status(self):
                return {"state": "ready", "loaded": False, "limits": None}

            def generate(self, request, cancellation_token=None):
                Plain.generate_calls += 1
                raise RuntimeError("boom")

        Plain.config = lambda: None
        LocalLanguageModelBackend(provider=Plain()).generate_response(self.understanding())
        self.assertEqual(Plain.generate_calls, 1)  # the default check() is None: existing path decides


class TestFallbackAfterResourceLimit(ResourceCase):
    """5. the existing fallback behaviour still works after a resource-limit failure"""

    def test_deterministic_pipeline_replies_and_failure_is_marked(self):
        control, _ = _core(self)
        big = MESSAGE + " " + self.oversized_text()
        expected = control.process_input(big)
        core, _ = _core(self)
        runtime = CountingRuntime(self.config())
        core.language_intelligence = LanguageIntelligenceCore(
            LocalLanguageModelBackend(runtime=runtime),
            fallback_backend=DeterministicFallbackBackend(core.understanding))
        reply = core.process_input(big)
        self.assertEqual(reply, expected)
        response = core.get_last_language_response()
        self.assertEqual((response.status, response.inference_status), (STATUS_MODEL_FAILED, INF_RESOURCE))
        self.assertIsNone(response.response_text)
        self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(runtime.reached_runtime(), 0)

    def test_fallback_marks_the_failure_and_the_model_is_used_for_the_next_in_limit_request(self):
        runtime = CountingRuntime(self.config())
        li = LanguageIntelligenceCore(
            LocalLanguageModelBackend(runtime=runtime),
            fallback_backend=DeterministicFallbackBackend(_core(self)[0].understanding))
        first = li.generate_response(self.understanding(self.oversized_text()))
        self.assertEqual((first.status, first.inference_status), (STATUS_MODEL_FAILED, INF_RESOURCE))
        self.assertEqual(first.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(runtime.reached_runtime(), 0)
        second = li.generate_response(self.understanding())
        self.assertEqual((second.status, second.response_text), (STATUS_GENERATED, MODEL_TEXT))
        self.assertEqual(runtime.inferences, 1)


class TestReadinessKeepsPriority(ResourceCase):
    """6. a readiness failure still takes priority over the resource guard"""

    def test_oversized_request_on_a_not_ready_model_reports_readiness(self):
        cases = (
            (self.not_configured, STATUS_MODEL_NOT_CONFIGURED, INF_NOT_CONFIGURED, ERROR_NO_CONFIGURATION),
            (self.unavailable, STATUS_MODEL_UNAVAILABLE, INF_UNAVAILABLE, ERROR_RUNTIME_DEPENDENCY_MISSING),
        )
        for make, status, inference_status, code in cases:
            with self.subTest(code=code):
                runtime = make()
                response = self.backend(runtime).generate_response(
                    self.understanding(self.oversized_text()))
                self.assertEqual((response.status, response.inference_status, response.error_code),
                                 (status, inference_status, code))
                self.assertEqual(runtime.reached_runtime(), 0)

    def test_resource_check_is_not_consulted_when_not_ready(self):
        class Spy(RuntimeBackedProvider):
            checks = 0

            def check_request_limits(self, request):
                Spy.checks += 1
                return super().check_request_limits(request)

        LocalLanguageModelBackend(provider=Spy(self.unavailable())).generate_response(
            self.understanding(self.oversized_text()))
        self.assertEqual(Spy.checks, 0)


if __name__ == "__main__":
    unittest.main()
