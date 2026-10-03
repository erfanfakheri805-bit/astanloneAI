"""
Tests for Prompt 408 - Expose Local Model Readiness.

`Core.get_local_model_readiness()` lets the higher-level language system
ask "is the local language model currently ready?" and returns the
existing `ModelReadiness` (Prompt 407) produced by
LanguageIntelligenceCore -> LocalLanguageModelBackend -> provider ->
runtime. Deterministic runtime doubles only.

Run directly:
    python -m unittest tests.test_core_model_readiness -v
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.local_model_config import LocalModelConfig
from language_intelligence.local_model_runtime import (
    LocalModelRuntime, RuntimeOutput, ModelLoadError,
)
from language_intelligence.inference import (
    ModelReadiness, READINESS_MODEL_READY, READINESS_MODEL_NOT_CONFIGURED,
    READINESS_MODEL_UNAVAILABLE, READINESS_MODEL_LOAD_FAILED,
    ERROR_NO_CONFIGURATION, ERROR_RUNTIME_DEPENDENCY_MISSING, ERROR_LOAD_FAILED,
)


class CountingRuntime(LocalModelRuntime):
    """TEST DOUBLE (not a model): counts loads, generate() calls, inferences."""

    def __init__(self, config=None):
        super().__init__(config=config)
        self.dependency_available = True
        self.load_calls = 0
        self.generate_calls = 0
        self.inferences = 0
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
        return RuntimeOutput("double output", "stop")

    def generate(self, request, cancellation_token=None):
        self.generate_calls += 1
        return super().generate(request, cancellation_token)

    def untouched(self):
        return (self.load_calls, self.generate_calls, self.inferences) == (0, 0, 0)


class CoreReadinessCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.core = Core(memory_db_path=os.path.join(self._tmp.name, "m.sqlite3"),
                         skill_definitions_dir=os.path.join(self._tmp.name, "skills"))
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

    def install(self, runtime, with_fallback=False):
        fallback = DeterministicFallbackBackend(self.core.understanding) if with_fallback else None
        self.core.language_intelligence = LanguageIntelligenceCore(
            LocalLanguageModelBackend(runtime=runtime), fallback_backend=fallback)
        return runtime


class TestHigherLevelLayerCanAskForReadiness(CoreReadinessCase):
    """1. the higher-level language layer can request model readiness"""

    def test_core_returns_a_structured_model_readiness(self):
        self.install(CountingRuntime(self.config()))
        readiness = self.core.get_local_model_readiness()
        self.assertIsInstance(readiness, ModelReadiness)
        self.assertEqual(readiness.to_dict()["status"], READINESS_MODEL_READY)

    def test_it_is_the_very_result_the_language_intelligence_core_reports(self):
        self.install(CountingRuntime(self.config()))
        self.assertEqual(self.core.get_local_model_readiness().to_dict(),
                         self.core.language_intelligence.check_model_readiness().to_dict())

    def test_default_core_has_no_local_model(self):
        readiness = self.core.get_local_model_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_NOT_CONFIGURED)
        self.assertFalse(readiness)

    def test_works_with_and_without_a_fallback_backend(self):
        for with_fallback in (False, True):
            self.install(CountingRuntime(self.config()), with_fallback)
            self.assertEqual(self.core.get_local_model_readiness().status, READINESS_MODEL_READY)


class TestStatesPropagate(CoreReadinessCase):
    """2-5. every readiness state propagates unchanged"""

    def test_model_not_configured(self):
        runtime = self.install(CountingRuntime(config=None))
        readiness = self.core.get_local_model_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_NOT_CONFIGURED)
        self.assertEqual(readiness.error_code, ERROR_NO_CONFIGURATION)
        self.assertFalse(readiness.ready)
        self.assertTrue(runtime.untouched())

    def test_model_not_configured_when_no_runtime_is_given(self):
        self.core.language_intelligence = LanguageIntelligenceCore(LocalLanguageModelBackend())
        self.assertEqual(self.core.get_local_model_readiness().status,
                         READINESS_MODEL_NOT_CONFIGURED)

    def test_model_unavailable(self):
        runtime = CountingRuntime(self.config())
        runtime.dependency_available = False
        self.install(runtime)
        readiness = self.core.get_local_model_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_UNAVAILABLE)
        self.assertEqual(readiness.error_code, ERROR_RUNTIME_DEPENDENCY_MISSING)
        self.assertFalse(readiness.ready)
        self.assertTrue(runtime.untouched())

    def test_model_ready(self):
        runtime = self.install(CountingRuntime(self.config()))
        readiness = self.core.get_local_model_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_READY)
        self.assertTrue(readiness.ready)
        self.assertIsNone(readiness.error_code)
        self.assertEqual(readiness.model_id, "test-model")
        self.assertTrue(runtime.untouched())

    def test_model_load_failed(self):
        runtime = CountingRuntime(self.config())
        runtime.load_error = ModelLoadError("corrupt weights")
        self.install(runtime, with_fallback=True)
        self.core.process_input("qwerty zzznoxyzzz unmapped concept")  # the one real load attempt
        self.assertEqual(runtime.load_calls, 1)
        readiness = self.core.get_local_model_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_LOAD_FAILED)
        self.assertEqual(readiness.error_code, ERROR_LOAD_FAILED)
        self.assertFalse(readiness.ready)

    def test_status_follows_the_runtime_over_time(self):
        runtime = self.install(CountingRuntime(config=None))
        self.assertEqual(self.core.get_local_model_readiness().status, READINESS_MODEL_NOT_CONFIGURED)
        runtime.configure(self.config())
        self.assertEqual(self.core.get_local_model_readiness().status, READINESS_MODEL_READY)
        runtime.dependency_available = False
        self.assertEqual(self.core.get_local_model_readiness().status, READINESS_MODEL_UNAVAILABLE)


class TestReadinessRequestDoesNotInfer(CoreReadinessCase):
    """6. the readiness request does not trigger inference"""

    def test_repeated_requests_never_load_generate_or_infer(self):
        runtime = self.install(CountingRuntime(self.config()), with_fallback=True)
        for _ in range(5):
            self.core.get_local_model_readiness()
        self.assertTrue(runtime.untouched())

    def test_failed_load_is_not_retried_by_readiness_requests(self):
        runtime = CountingRuntime(self.config())
        runtime.load_error = ModelLoadError("x")
        self.install(runtime, with_fallback=True)
        self.core.process_input("qwerty zzznoxyzzz unmapped concept")
        for _ in range(3):
            self.core.get_local_model_readiness()
        self.assertEqual((runtime.load_calls, runtime.inferences), (1, 0))

    def test_conversation_state_is_untouched(self):
        runtime = self.install(CountingRuntime(self.config()), with_fallback=True)
        self.core.process_input("I am building a robot game.")
        turns = list(self.core.get_recent_turns())
        response = self.core.get_last_language_response()
        understanding = self.core.get_last_language_understanding()
        state = self.core.conversation_state.to_dict()
        messages = len(self.core.recent_messages(100))
        calls = (runtime.load_calls, runtime.generate_calls, runtime.inferences)
        self.core.get_local_model_readiness()
        self.assertEqual(self.core.get_recent_turns(), turns)
        self.assertIs(self.core.get_last_language_response(), response)
        self.assertIs(self.core.get_last_language_understanding(), understanding)
        self.assertEqual(self.core.conversation_state.to_dict(), state)
        self.assertEqual(len(self.core.recent_messages(100)), messages)
        self.assertEqual((runtime.load_calls, runtime.generate_calls, runtime.inferences), calls)

    def test_a_readiness_request_does_not_change_the_next_reply(self):
        runtime = self.install(CountingRuntime(self.config()), with_fallback=True)
        self.core.get_local_model_readiness()
        reply = self.core.process_input("Tell me something about rivers.")
        self.assertEqual(reply, "double output")
        self.assertEqual((runtime.generate_calls, runtime.inferences), (1, 1))


if __name__ == "__main__":
    unittest.main()
