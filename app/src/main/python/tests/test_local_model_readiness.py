"""
Tests for Prompt 407 - Local Model Readiness Check.

`LocalLanguageModelBackend.check_readiness()` /
`LanguageIntelligenceCore.check_model_readiness()` summarise the existing
`ModelAvailability` as MODEL_READY / MODEL_NOT_CONFIGURED /
MODEL_UNAVAILABLE / MODEL_LOAD_FAILED. Deterministic runtime doubles only;
no model is read, loaded for these checks, or downloaded.

Run directly:
    python -m unittest tests.test_local_model_readiness -v
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.local_model_config import LocalModelConfig
from language_intelligence.local_model_provider import LocalModelProvider, RuntimeBackedProvider
from language_intelligence.local_model_runtime import (
    LocalModelRuntime, RuntimeOutput, ModelLoadError, ModelReadiness, model_readiness,
    READINESS_MODEL_READY, READINESS_MODEL_NOT_CONFIGURED, READINESS_MODEL_UNAVAILABLE,
    READINESS_MODEL_LOAD_FAILED, ALL_READINESS_STATUSES,
    ModelAvailability, STATE_READY, STATE_UNLOADED,
)
from language_intelligence.inference import (
    ERROR_NO_CONFIGURATION, ERROR_MODEL_DISABLED, ERROR_RUNTIME_DEPENDENCY_MISSING,
    ERROR_MODEL_FILE_NOT_FOUND, ERROR_MODEL_EXCEEDS_MEMORY_LIMIT, ERROR_LOAD_FAILED,
)
from language_intelligence.unavailable_runtime import UnavailableLocalModelRuntime
from understanding.engine import UnderstandingEngine


class CountingRuntime(LocalModelRuntime):
    """TEST DOUBLE (not a model). Counts loads, generate() calls and
    engine inferences so a test can prove a check did none of them."""

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

    def assert_untouched(self, test):
        test.assertEqual((self.load_calls, self.generate_calls, self.inferences), (0, 0, 0))


class ReadinessCase(unittest.TestCase):
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
    def backend(runtime):
        return LocalLanguageModelBackend(runtime=runtime)

    @staticmethod
    def understanding():
        return DeterministicFallbackBackend(UnderstandingEngine()).understand("What is Python?")


class TestNoModelConfigured(ReadinessCase):
    """1. no model configured -> MODEL_NOT_CONFIGURED"""

    def test_default_backend(self):
        readiness = LocalLanguageModelBackend().check_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_NOT_CONFIGURED)
        self.assertFalse(readiness.ready)
        self.assertFalse(readiness)

    def test_runtime_without_configuration(self):
        runtime = CountingRuntime(config=None)
        readiness = self.backend(runtime).check_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_NOT_CONFIGURED)
        self.assertEqual(readiness.error_code, ERROR_NO_CONFIGURATION)
        runtime.assert_untouched(self)

    def test_disabled_model_is_not_ready_either(self):
        readiness = self.backend(CountingRuntime(self.config(enabled=False))).check_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_NOT_CONFIGURED)
        self.assertEqual(readiness.error_code, ERROR_MODEL_DISABLED)

    def test_invalid_configuration(self):
        readiness = self.backend(CountingRuntime(self.config(context_length=-5))).check_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_NOT_CONFIGURED)

    def test_through_the_language_intelligence_core(self):
        core = LanguageIntelligenceCore(LocalLanguageModelBackend())
        self.assertEqual(core.check_model_readiness().status, READINESS_MODEL_NOT_CONFIGURED)

    def test_deterministic_backend_has_no_local_model(self):
        core = LanguageIntelligenceCore(DeterministicFallbackBackend(UnderstandingEngine()))
        readiness = core.check_model_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_NOT_CONFIGURED)
        self.assertFalse(readiness)


class TestModelUnavailable(ReadinessCase):
    """2. configured but unavailable -> MODEL_UNAVAILABLE"""

    def test_engine_library_missing(self):
        runtime = CountingRuntime(self.config())
        runtime.dependency_available = False
        readiness = self.backend(runtime).check_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_UNAVAILABLE)
        self.assertEqual(readiness.error_code, ERROR_RUNTIME_DEPENDENCY_MISSING)
        self.assertIn("engine", readiness.message)
        runtime.assert_untouched(self)

    def test_shipped_unavailable_runtime(self):
        readiness = self.backend(UnavailableLocalModelRuntime(self.config())).check_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_UNAVAILABLE)

    def test_model_file_missing(self):
        config = self.config(model_path=os.path.join(self._tmp.name, "gone.gguf"))
        runtime = CountingRuntime(config)
        readiness = self.backend(runtime).check_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_UNAVAILABLE)
        self.assertEqual(readiness.error_code, ERROR_MODEL_FILE_NOT_FOUND)
        runtime.assert_untouched(self)

    def test_model_larger_than_the_memory_budget(self):
        with open(self.model_path, "wb") as handle:
            handle.write(b"\0" * (2 * 1024 * 1024))
        readiness = self.backend(CountingRuntime(self.config(max_memory_mb=1))).check_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_UNAVAILABLE)
        self.assertEqual(readiness.error_code, ERROR_MODEL_EXCEEDS_MEMORY_LIMIT)

    def test_a_provider_that_breaks_its_contract_is_unavailable_not_an_exception(self):
        class BrokenProvider(LocalModelProvider):
            @property
            def provider_id(self):
                return "broken"

            def availability(self):
                raise RuntimeError("secret internal detail")

        readiness = LocalLanguageModelBackend(provider=BrokenProvider()).check_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_UNAVAILABLE)
        self.assertNotIn("secret", readiness.message)

    def test_core_survives_a_backend_that_cannot_report(self):
        class BadBackend(DeterministicFallbackBackend):
            def check_readiness(self):
                raise RuntimeError("boom")

        readiness = LanguageIntelligenceCore(
            BadBackend(UnderstandingEngine())).check_model_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_UNAVAILABLE)


class TestModelReady(ReadinessCase):
    """3. model available / ready -> MODEL_READY"""

    def test_loadable_model_is_ready_before_it_is_loaded(self):
        runtime = CountingRuntime(self.config())
        readiness = self.backend(runtime).check_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_READY)
        self.assertTrue(readiness.ready)
        self.assertTrue(readiness)
        self.assertFalse(readiness.loaded)
        self.assertIsNone(readiness.error_code)
        self.assertEqual((readiness.model_id, readiness.runtime_name),
                         ("test-model", "counting-runtime"))
        runtime.assert_untouched(self)  # ready means "may be attempted", not "loaded now"

    def test_loaded_model_is_ready_and_reports_loaded(self):
        runtime = CountingRuntime(self.config())
        backend = self.backend(runtime)
        backend.generate_response(self.understanding())  # one real request loads it
        readiness = backend.check_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_READY)
        self.assertTrue(readiness.loaded)

    def test_through_the_language_intelligence_core(self):
        core = LanguageIntelligenceCore(self.backend(CountingRuntime(self.config())))
        self.assertEqual(core.check_model_readiness().status, READINESS_MODEL_READY)

    def test_readiness_follows_reconfiguration(self):
        runtime = CountingRuntime(self.config())
        backend = self.backend(runtime)
        self.assertTrue(backend.check_readiness())
        runtime.configure(None)
        self.assertEqual(backend.check_readiness().status, READINESS_MODEL_NOT_CONFIGURED)
        runtime.configure(self.config())
        self.assertTrue(backend.check_readiness())


class TestModelLoadFailed(ReadinessCase):
    """4. model load failure -> MODEL_LOAD_FAILED"""

    def _failed(self):
        runtime = CountingRuntime(self.config())
        runtime.load_error = ModelLoadError("corrupt weights")
        backend = self.backend(runtime)
        backend.generate_response(self.understanding())  # the one load attempt
        return runtime, backend

    def test_failed_load_is_reported(self):
        runtime, backend = self._failed()
        readiness = backend.check_readiness()
        self.assertEqual(readiness.status, READINESS_MODEL_LOAD_FAILED)
        self.assertEqual(readiness.error_code, ERROR_LOAD_FAILED)
        self.assertIn("corrupt weights", readiness.message)
        self.assertFalse(readiness)

    def test_checking_readiness_does_not_retry_the_load(self):
        runtime, backend = self._failed()
        for _ in range(3):
            backend.check_readiness()
        self.assertEqual(runtime.load_calls, 1)
        self.assertEqual(runtime.inferences, 0)

    def test_before_any_load_attempt_a_broken_model_is_not_yet_reported_failed(self):
        # Honest: readiness is a cheap preflight; the engine may still
        # reject the file on the first (lazy) load.
        runtime = CountingRuntime(self.config())
        runtime.load_error = ModelLoadError("corrupt weights")
        self.assertEqual(self.backend(runtime).check_readiness().status, READINESS_MODEL_READY)
        self.assertEqual(runtime.load_calls, 0)


class TestReadinessDoesNotInfer(ReadinessCase):
    """5. the readiness check does not perform inference"""

    def test_repeated_checks_never_load_generate_or_infer(self):
        runtime = CountingRuntime(self.config())
        backend = self.backend(runtime)
        core = LanguageIntelligenceCore(backend)
        for _ in range(5):
            backend.check_readiness()
            core.check_model_readiness()
        runtime.assert_untouched(self)

    def test_provider_generate_is_never_called(self):
        runtime = CountingRuntime(self.config())

        class SpyProvider(RuntimeBackedProvider):
            generate_calls = 0

            def generate(self, request, cancellation_token=None):
                SpyProvider.generate_calls += 1
                return super().generate(request, cancellation_token)

        LocalLanguageModelBackend(provider=SpyProvider(runtime)).check_readiness()
        self.assertEqual(SpyProvider.generate_calls, 0)
        runtime.assert_untouched(self)

    def test_a_check_before_a_request_leaves_the_request_unchanged(self):
        runtime = CountingRuntime(self.config())
        backend = self.backend(runtime)
        self.assertTrue(backend.check_readiness())
        response = backend.generate_response(self.understanding())
        self.assertEqual(response.response_text, "double output")
        self.assertEqual((runtime.generate_calls, runtime.inferences, runtime.load_calls), (1, 1, 1))

    def test_every_state_is_covered_and_serialisable(self):
        self.assertEqual(len(set(ALL_READINESS_STATUSES)), 4)
        readiness = self.backend(CountingRuntime(self.config())).check_readiness()
        self.assertEqual(readiness.to_dict()["status"], READINESS_MODEL_READY)
        self.assertIs(readiness.to_dict()["ready"], True)

    def test_mapping_is_a_pure_summary_of_availability(self):
        ready = ModelAvailability(True, True, True, True, False, True, STATE_UNLOADED)
        self.assertEqual(model_readiness(ready).status, READINESS_MODEL_READY)
        self.assertIsInstance(model_readiness(ready), ModelReadiness)
        cannot = ModelAvailability(True, True, True, False, False, False, STATE_READY)
        self.assertEqual(model_readiness(cannot).status, READINESS_MODEL_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
