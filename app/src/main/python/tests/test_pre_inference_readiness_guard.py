"""
Tests for Prompt 409 - Pre-Inference Readiness Guard.

`LocalLanguageModelBackend.generate_response()` checks readiness first;
MODEL_NOT_CONFIGURED / MODEL_UNAVAILABLE / MODEL_LOAD_FAILED never reach
the provider/runtime and come back as the existing structured failure
(Prompt 406's fallback then applies); MODEL_READY continues to the existing
inference path. Test doubles only at the runtime boundary - no model.

Run directly:
    python -m unittest tests.test_pre_inference_readiness_guard -v
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.local_model_config import LocalModelConfig
from language_intelligence.local_model_mapping import build_inference_request, map_inference_result
from language_intelligence.local_model_provider import LocalModelProvider, RuntimeBackedProvider
from language_intelligence.local_model_runtime import LocalModelRuntime, RuntimeOutput, ModelLoadError
from language_intelligence.inference import (
    STATUS_SUCCESS, STATUS_MODEL_NOT_CONFIGURED as INF_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE as INF_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED as INF_LOAD_FAILED,
    STATUS_RESOURCE_LIMIT as INF_RESOURCE, STATUS_INFERENCE_FAILED as INF_INFERENCE_FAILED,
    ERROR_NO_CONFIGURATION, ERROR_RUNTIME_DEPENDENCY_MISSING, ERROR_LOAD_FAILED,
    ERROR_MODEL_FILE_NOT_FOUND, ERROR_MODEL_EXCEEDS_MEMORY_LIMIT,
)
from language_intelligence.response_generation import (
    STATUS_GENERATED, STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_FAILED,
)
from understanding.engine import UnderstandingEngine

MESSAGE = "qwerty zzznoxyzzz unmapped concept"
MODEL_TEXT = "text that only the model double can produce"


class CountingRuntime(LocalModelRuntime):
    """TEST DOUBLE at the runtime boundary (not a model)."""

    def __init__(self, config=None):
        super().__init__(config=config)
        self.dependency_available = True
        self.load_calls = 0
        self.generate_calls = 0
        self.inferences = 0
        self.requests = []
        self.load_error = None

    @property
    def runtime_name(self):
        return "counting-runtime"

    def dependency_status(self):
        return (True, "") if self.dependency_available else (False, "counting engine missing")

    def _load_model(self, config):
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error

    def _run_inference(self, request, params, config, control):
        self.inferences += 1
        self.requests.append(request)
        return RuntimeOutput(MODEL_TEXT, "stop", prompt_tokens=7, output_tokens=5)

    def generate(self, request, cancellation_token=None):
        self.generate_calls += 1
        return super().generate(request, cancellation_token)

    def reached_runtime(self):
        return self.generate_calls or self.load_calls or self.inferences


class GuardCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.model_path = os.path.join(self._tmp.name, "model.gguf")
        with open(self.model_path, "wb") as handle:
            handle.write(b"\0" * 16)

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, **overrides):
        values = dict(model_id="test-model", model_path=self.model_path, context_length=512,
                      max_output_tokens=64, timeout_seconds=10.0)
        values.update(overrides)
        return LocalModelConfig(**values)

    @staticmethod
    def understanding(text="What is Python?"):
        return DeterministicFallbackBackend(UnderstandingEngine()).understand(text)

    def not_configured(self):
        return CountingRuntime(config=None)

    def unavailable(self):
        runtime = CountingRuntime(self.config())
        runtime.dependency_available = False
        return runtime

    def load_failed(self):
        """Fail one real load first (the single, permitted attempt)."""
        runtime = CountingRuntime(self.config())
        runtime.load_error = ModelLoadError("corrupt weights")
        LocalLanguageModelBackend(runtime=runtime).generate_response(self.understanding())
        return runtime

    def blocked_cases(self):
        return (
            ("not_configured", self.not_configured, STATUS_MODEL_NOT_CONFIGURED, INF_NOT_CONFIGURED,
             ERROR_NO_CONFIGURATION),
            ("unavailable", self.unavailable, STATUS_MODEL_UNAVAILABLE, INF_UNAVAILABLE,
             ERROR_RUNTIME_DEPENDENCY_MISSING),
            ("load_failed", self.load_failed, STATUS_MODEL_UNAVAILABLE, INF_LOAD_FAILED,
             ERROR_LOAD_FAILED),
        )


class TestReadyModelContinues(GuardCase):
    """1 + 7. MODEL_READY allows inference; the existing path is unchanged"""

    def test_ready_model_reaches_the_runtime_and_generates(self):
        runtime = CountingRuntime(self.config())
        response = LocalLanguageModelBackend(runtime=runtime).generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(response.response_text, MODEL_TEXT)
        self.assertEqual(response.inference_status, STATUS_SUCCESS)
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual((runtime.generate_calls, runtime.load_calls, runtime.inferences), (1, 1, 1))

    def test_request_reaching_the_runtime_is_the_normal_one(self):
        runtime = CountingRuntime(self.config())
        understanding = self.understanding("What is Python?")
        LocalLanguageModelBackend(runtime=runtime).generate_response(understanding)
        self.assertEqual(runtime.requests[0].user_input, understanding.original_input)

    def test_loaded_model_keeps_being_used_without_reloading(self):
        runtime = CountingRuntime(self.config())
        backend = LocalLanguageModelBackend(runtime=runtime)
        for _ in range(3):
            self.assertEqual(backend.generate_response(self.understanding()).status, STATUS_GENERATED)
        self.assertEqual((runtime.load_calls, runtime.inferences), (1, 3))

    def test_ready_model_through_core_replies_with_the_model_text(self):
        core, tmp = _core(self)
        core.language_intelligence = LanguageIntelligenceCore(
            LocalLanguageModelBackend(runtime=CountingRuntime(self.config())),
            fallback_backend=DeterministicFallbackBackend(core.understanding))
        self.assertEqual(core.process_input(MESSAGE), MODEL_TEXT)


class TestNotReadyBlocksInference(GuardCase):
    """2-4. NOT_CONFIGURED / UNAVAILABLE / LOAD_FAILED never reach inference"""

    def test_runtime_is_not_called_in_any_blocked_state(self):
        for name, make, *_ in self.blocked_cases():
            with self.subTest(state=name):
                runtime = make()
                before = (runtime.generate_calls, runtime.load_calls, runtime.inferences)
                LocalLanguageModelBackend(runtime=runtime).generate_response(self.understanding())
                self.assertEqual(
                    (runtime.generate_calls, runtime.load_calls, runtime.inferences), before)
                self.assertEqual(runtime.requests, [])

    def test_provider_is_not_called_either(self):
        for name, make, *_ in self.blocked_cases():
            with self.subTest(state=name):
                class SpyProvider(RuntimeBackedProvider):
                    calls = 0

                    def generate(self, request, cancellation_token=None):
                        SpyProvider.calls += 1
                        return super().generate(request, cancellation_token)

                LocalLanguageModelBackend(provider=SpyProvider(make())).generate_response(
                    self.understanding())
                self.assertEqual(SpyProvider.calls, 0)

    def test_no_request_is_built_for_a_blocked_model(self):
        import language_intelligence.local_model_backend as module
        original = module.build_inference_request
        calls = []
        module.build_inference_request = lambda *a, **k: calls.append(1) or original(*a, **k)
        try:
            LocalLanguageModelBackend(runtime=self.not_configured()).generate_response(
                self.understanding())
        finally:
            module.build_inference_request = original
        self.assertEqual(calls, [])

    def test_repeated_blocked_requests_never_retry_the_load(self):
        runtime = self.load_failed()
        backend = LocalLanguageModelBackend(runtime=runtime)
        for _ in range(4):
            backend.generate_response(self.understanding())
        self.assertEqual((runtime.load_calls, runtime.inferences, runtime.generate_calls), (1, 0, 1))

    def test_missing_file_and_over_budget_model_are_blocked_before_the_runtime(self):
        runtime = CountingRuntime(self.config(model_path=os.path.join(self._tmp.name, "gone.gguf")))
        response = LocalLanguageModelBackend(runtime=runtime).generate_response(self.understanding())
        self.assertEqual((response.status, response.inference_status, response.error_code),
                         (STATUS_MODEL_UNAVAILABLE, INF_LOAD_FAILED, ERROR_MODEL_FILE_NOT_FOUND))
        with open(self.model_path, "wb") as handle:
            handle.write(b"\0" * (2 * 1024 * 1024))
        big = CountingRuntime(self.config(max_memory_mb=1))
        response = LocalLanguageModelBackend(runtime=big).generate_response(self.understanding())
        self.assertEqual((response.status, response.inference_status, response.error_code),
                         (STATUS_MODEL_FAILED, INF_RESOURCE, ERROR_MODEL_EXCEEDS_MEMORY_LIMIT))
        self.assertFalse(runtime.reached_runtime() or big.reached_runtime())

    def test_a_provider_that_cannot_report_availability_does_not_block(self):
        class Silent(LocalModelProvider):
            generate_calls = 0

            @property
            def provider_id(self):
                return "silent"

            def availability(self):
                raise RuntimeError("secret internal detail")

            def generate(self, request, cancellation_token=None):
                Silent.generate_calls += 1
                raise RuntimeError("secret internal detail")

        response = LocalLanguageModelBackend(provider=Silent()).generate_response(self.understanding())
        self.assertEqual(Silent.generate_calls, 1)  # the existing path decided
        self.assertEqual((response.status, response.inference_status),
                         (STATUS_MODEL_FAILED, INF_INFERENCE_FAILED))
        self.assertNotIn("secret", response.reason)


class TestBlockedResultIsTheExistingStructuredFailure(GuardCase):
    """5. a blocked inference returns the correct existing structured failure"""

    def test_status_inference_status_code_and_no_text(self):
        for name, make, status, inference_status, code in self.blocked_cases():
            with self.subTest(state=name):
                response = LocalLanguageModelBackend(runtime=make()).generate_response(
                    self.understanding())
                self.assertEqual((response.status, response.inference_status, response.error_code),
                                 (status, inference_status, code))
                self.assertIsNone(response.response_text)
                self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
                self.assertTrue(response.reason)
                self.assertIn("provider_id", response.metadata)
                self.assertNotIn(MODEL_TEXT, str(response.to_dict()))

    def test_identical_to_what_the_runtime_itself_reports(self):
        for name, make, *_ in self.blocked_cases():
            with self.subTest(state=name):
                runtime = make()
                understanding = self.understanding()
                guarded = LocalLanguageModelBackend(runtime=runtime).generate_response(understanding)
                direct = map_inference_result(
                    runtime.generate(build_inference_request(understanding, None)),
                    BACKEND_KIND_LOCAL_MODEL)
                self.assertEqual(
                    (guarded.status, guarded.inference_status, guarded.error_code),
                    (direct.status, direct.inference_status, direct.error_code))

    def test_block_reports_the_model_and_runtime_names_it_knows(self):
        response = LocalLanguageModelBackend(runtime=self.unavailable()).generate_response(
            self.understanding())
        self.assertEqual((response.metadata["model_id"], response.metadata["runtime_name"]),
                         ("test-model", "counting-runtime"))


def _core(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    core = Core(memory_db_path=os.path.join(tmp.name, "m.sqlite3"),
                skill_definitions_dir=os.path.join(tmp.name, "skills"))
    return core, tmp


class TestFallbackStillWorksAfterABlockedRequest(GuardCase):
    """6. Prompt 406's fallback handling applies to a readiness-blocked request"""

    def test_deterministic_pipeline_replies_and_the_failure_is_marked(self):
        control, _ = _core(self)
        expected = control.process_input(MESSAGE)
        for name, make, status, inference_status, _code in self.blocked_cases():
            with self.subTest(state=name):
                core, _ = _core(self)
                runtime = make()
                before = runtime.generate_calls
                core.language_intelligence = LanguageIntelligenceCore(
                    LocalLanguageModelBackend(runtime=runtime),
                    fallback_backend=DeterministicFallbackBackend(core.understanding))
                reply = core.process_input(MESSAGE)
                self.assertEqual(reply, expected)
                response = core.get_last_language_response()
                self.assertEqual((response.status, response.inference_status),
                                 (status, inference_status))
                self.assertIsNone(response.response_text)
                self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
                self.assertEqual(runtime.generate_calls, before)  # blocked: runtime untouched
                self.assertEqual(core.get_last_language_understanding().original_input, MESSAGE)

    def test_the_model_is_used_again_as_soon_as_it_becomes_ready(self):
        core, _ = _core(self)
        runtime = CountingRuntime(config=None)
        core.language_intelligence = LanguageIntelligenceCore(
            LocalLanguageModelBackend(runtime=runtime),
            fallback_backend=DeterministicFallbackBackend(core.understanding))
        self.assertNotEqual(core.process_input(MESSAGE), MODEL_TEXT)
        self.assertEqual(runtime.generate_calls, 0)
        runtime.configure(self.config())
        self.assertEqual(core.process_input(MESSAGE + " two"), MODEL_TEXT)
        self.assertEqual(runtime.generate_calls, 1)

    def test_without_a_fallback_backend_behaviour_is_unchanged(self):
        backend = LocalLanguageModelBackend()
        li = LanguageIntelligenceCore(backend)
        response = li.generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_NOT_CONFIGURED)
        self.assertIsNone(response.fallback_backend_kind)


if __name__ == "__main__":
    unittest.main()
