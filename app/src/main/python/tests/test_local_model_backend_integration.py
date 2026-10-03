"""
Tests for Prompt 399 - the real LocalLanguageModelBackend -> LocalModelRuntime
integration (language_intelligence/local_model_backend.py,
local_model_mapping.py, and LocalModelRuntime.availability()).

IMPORTANT - about the test double: `StubRuntime` below is a TEST DOUBLE
used only at the runtime boundary. Its "output" is whatever string a test
scripts into it; it is NOT a language model and performs NO inference.
No model is downloaded, no network is used.

Run directly:
    python -m unittest tests.test_local_model_backend_integration -v
(from app/src/main/python/)
"""

import os
import re
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language_intelligence
from understanding.engine import UnderstandingEngine
from context.conversation_context import ConversationContext
from core.core import Core

from language_intelligence.backend import (
    BACKEND_KIND_DETERMINISTIC_FALLBACK, BACKEND_KIND_LOCAL_MODEL,
)
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.response_generation import (
    ResponseGenerationResult, STATUS_DEFERRED, STATUS_GENERATED,
    STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_FAILED,
)
from language_intelligence.local_model_config import LocalModelConfig
from language_intelligence.inference import (
    InferenceRequest, InferenceResult, STATUS_SUCCESS,
    STATUS_MODEL_NOT_CONFIGURED as INF_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE as INF_UNAVAILABLE,
    STATUS_MODEL_LOAD_FAILED as INF_LOAD_FAILED,
    STATUS_INFERENCE_FAILED, STATUS_INVALID_REQUEST, STATUS_RESOURCE_LIMIT,
    STATUS_TIMEOUT, STATUS_CANCELLED, ALL_INFERENCE_STATUSES,
    ERROR_NO_CONFIGURATION, ERROR_MODEL_DISABLED, ERROR_INVALID_CONFIGURATION,
    ERROR_RUNTIME_DEPENDENCY_MISSING, ERROR_MODEL_FILE_NOT_FOUND,
    ERROR_MODEL_EXCEEDS_MEMORY_LIMIT, ERROR_LOAD_FAILED, ERROR_INFERENCE_FAILED,
    ERROR_TIMED_OUT, ERROR_CANCELLED, ERROR_CONTEXT_LENGTH_EXCEEDED,
    ERROR_OUT_OF_MEMORY, ERROR_INVALID_RUNTIME_OUTPUT, ERROR_INVALID_REQUEST,
)
from language_intelligence.local_model_runtime import (
    LocalModelRuntime, ModelAvailability, ModelLoadError, InferenceExecutionError,
    ResourceLimitExceeded, CancellationToken, RuntimeOutput,
    STATE_NOT_CONFIGURED, STATE_RUNTIME_UNAVAILABLE, STATE_UNLOADED, STATE_READY,
    STATE_LOAD_FAILED,
)
from language_intelligence.unavailable_runtime import UnavailableLocalModelRuntime
from language_intelligence.local_model_backend import (
    LocalLanguageModelBackend, LocalModelBackendError,
)
from language_intelligence import local_model_mapping
from language_intelligence.local_model_mapping import (
    build_inference_request, map_inference_result, conversation_from_context,
    INFERENCE_TO_RESPONSE_STATUS,
)


# ----------------------------------------------------------------------
# Test doubles (NOT a language model)
# ----------------------------------------------------------------------
class FakeClock:
    def __init__(self):
        self.now = 500.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class StubRuntime(LocalModelRuntime):
    """TEST DOUBLE at the runtime boundary. Returns what a test scripts."""

    def __init__(self, config=None, clock=None):
        super().__init__(config=config, clock=clock)
        self.dependency_available = True
        self.load_calls = 0
        self.requests = []
        self.load_error = None
        self.infer_error = None
        self.output = RuntimeOutput("stub-output", "stop", prompt_tokens=7, output_tokens=2)
        self.advance_clock_by = 0.0

    @property
    def runtime_name(self):
        return "stub-runtime"

    def dependency_status(self):
        return (True, "") if self.dependency_available else (False, "stub engine missing")

    def _load_model(self, config):
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error

    def _run_inference(self, request, params, config, control):
        self.requests.append(request)
        if self.advance_clock_by:
            self._clock.advance(self.advance_clock_by)
            control.check()
        if self.infer_error is not None:
            raise self.infer_error
        return self.output


class RaisingRuntime:
    """Breaks the runtime contract: generate() raises."""

    def generate(self, request, cancellation_token=None):
        raise RuntimeError("secret internal detail /data/model.bin")

    def readiness(self):
        return STATE_UNLOADED, None, ""

    def availability(self):
        raise RuntimeError("secret internal detail")


class WrongTypeRuntime(RaisingRuntime):
    """Breaks the runtime contract: generate() returns the wrong type."""

    def __init__(self, value):
        self.value = value

    def generate(self, request, cancellation_token=None):
        return self.value


def _config(path="/nonexistent/model.gguf", **overrides):
    values = dict(model_id="test-model", model_path=path, context_length=512,
                  max_output_tokens=64, timeout_seconds=10.0)
    values.update(overrides)
    return LocalModelConfig(**values)


class _Files:
    def setUp(self):
        self._files = []

    def tearDown(self):
        for path in self._files:
            if os.path.exists(path):
                os.remove(path)

    def model_file(self, size_bytes=16):
        handle = tempfile.NamedTemporaryFile(suffix=".gguf", delete=False)
        handle.write(b"\0" * size_bytes)
        handle.close()
        self._files.append(handle.name)
        return handle.name

    def runtime(self, **config_overrides):
        clock = FakeClock()
        return StubRuntime(_config(self.model_file(), **config_overrides), clock=clock)

    @staticmethod
    def understanding(text="What is Python?"):
        return DeterministicFallbackBackend(UnderstandingEngine()).understand(text)


# ======================================================================
class TestNoConfiguredModel(_Files, unittest.TestCase):
    """1. backend with no configured model"""

    def test_default_backend_reports_not_configured(self):
        backend = LocalLanguageModelBackend()
        response = backend.generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_NOT_CONFIGURED)
        self.assertIsNone(response.response_text)
        self.assertEqual(response.error_code, ERROR_NO_CONFIGURATION)
        self.assertEqual(response.inference_status, INF_NOT_CONFIGURED)
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertTrue(response.reason)

    def test_availability_is_structured_not_configured(self):
        availability = LocalLanguageModelBackend().check_availability()
        self.assertIsInstance(availability, ModelAvailability)
        self.assertFalse(availability.configured)
        self.assertFalse(availability.enabled)
        self.assertFalse(availability.can_infer)
        self.assertFalse(availability)
        self.assertEqual(availability.state, STATE_NOT_CONFIGURED)
        self.assertEqual(availability.error_code, ERROR_NO_CONFIGURATION)

    def test_stub_runtime_without_config_is_not_configured(self):
        backend = LocalLanguageModelBackend(StubRuntime())
        response = backend.generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_NOT_CONFIGURED)
        self.assertEqual(backend.runtime.requests, [])

    def test_invalid_configuration_is_not_configured_and_says_why(self):
        runtime = StubRuntime(LocalModelConfig(model_id="", model_path="https://x/m.gguf"))
        availability = LocalLanguageModelBackend(runtime).check_availability()
        self.assertFalse(availability.configured)
        self.assertEqual(availability.error_code, ERROR_INVALID_CONFIGURATION)
        self.assertIn("LOCAL path", availability.message)

    def test_understand_is_explicit_and_raises_no_fake_result(self):
        with self.assertRaises(LocalModelBackendError) as ctx:
            LocalLanguageModelBackend().understand("hello")
        self.assertEqual(ctx.exception.status, STATUS_MODEL_NOT_CONFIGURED)


# ======================================================================
class TestDisabledOrUnavailableRuntime(_Files, unittest.TestCase):
    """2. backend with a disabled / unavailable runtime"""

    def test_disabled_model_is_configured_but_not_enabled(self):
        runtime = StubRuntime(_config(self.model_file(), enabled=False))
        backend = LocalLanguageModelBackend(runtime)
        availability = backend.check_availability()
        self.assertTrue(availability.configured)
        self.assertFalse(availability.enabled)
        self.assertFalse(availability.can_infer)
        self.assertEqual(availability.error_code, ERROR_MODEL_DISABLED)

        response = backend.generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_NOT_CONFIGURED)
        self.assertEqual(response.error_code, ERROR_MODEL_DISABLED)
        self.assertIsNone(response.response_text)
        self.assertEqual(runtime.requests, [])
        self.assertEqual(runtime.load_calls, 0)

    def test_missing_engine_is_unavailable(self):
        runtime = self.runtime()
        runtime.dependency_available = False
        backend = LocalLanguageModelBackend(runtime)
        availability = backend.check_availability()
        self.assertTrue(availability.configured)
        self.assertTrue(availability.enabled)
        self.assertFalse(availability.runtime_available)
        self.assertFalse(availability.loadable)
        self.assertFalse(availability.can_infer)
        self.assertEqual(availability.state, STATE_RUNTIME_UNAVAILABLE)

        response = backend.generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_UNAVAILABLE)
        self.assertEqual(response.error_code, ERROR_RUNTIME_DEPENDENCY_MISSING)
        self.assertEqual(response.inference_status, INF_UNAVAILABLE)
        self.assertEqual(runtime.load_calls, 0)

    def test_shipped_unavailable_runtime_is_explicit(self):
        backend = LocalLanguageModelBackend(UnavailableLocalModelRuntime(_config()))
        availability = backend.check_availability()
        self.assertFalse(availability.runtime_available)
        self.assertEqual(availability.runtime_name, "unavailable")
        response = backend.generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_UNAVAILABLE)
        self.assertIsNone(response.response_text)


# ======================================================================
class TestAvailabilityCheck(_Files, unittest.TestCase):
    """Structured availability: side-effect free, never loads."""

    def test_unloaded_but_loadable(self):
        runtime = self.runtime()
        availability = LocalLanguageModelBackend(runtime).check_availability()
        self.assertTrue(availability.configured and availability.enabled)
        self.assertTrue(availability.runtime_available)
        self.assertTrue(availability.loadable)
        self.assertFalse(availability.loaded)
        self.assertTrue(availability.can_infer)
        self.assertTrue(availability.ok)
        self.assertEqual(availability.state, STATE_UNLOADED)
        self.assertEqual(availability.model_id, "test-model")
        self.assertEqual(availability.runtime_name, "stub-runtime")
        self.assertEqual(runtime.load_calls, 0)          # checking never loads

    def test_missing_model_file_is_not_loadable(self):
        runtime = StubRuntime(_config("/definitely/missing/model.gguf"))
        availability = LocalLanguageModelBackend(runtime).check_availability()
        self.assertTrue(availability.runtime_available)
        self.assertFalse(availability.loadable)
        self.assertFalse(availability.can_infer)
        self.assertEqual(availability.error_code, ERROR_MODEL_FILE_NOT_FOUND)
        self.assertEqual(runtime.load_calls, 0)

    def test_model_larger_than_memory_budget_is_not_loadable(self):
        big = self.model_file(3 * 1024 * 1024)
        runtime = StubRuntime(_config(big, max_memory_mb=1))
        availability = runtime.availability()
        self.assertFalse(availability.loadable)
        self.assertEqual(availability.error_code, ERROR_MODEL_EXCEEDS_MEMORY_LIMIT)
        self.assertEqual(runtime.load_calls, 0)

    def test_loaded_state_and_failed_load_state(self):
        runtime = self.runtime()
        backend = LocalLanguageModelBackend(runtime)
        backend.generate_response(self.understanding())
        loaded = backend.check_availability()
        self.assertTrue(loaded.loaded and loaded.loadable and loaded.can_infer)
        self.assertEqual(loaded.state, STATE_READY)

        failing = self.runtime()
        failing.load_error = ModelLoadError("nope")
        failing_backend = LocalLanguageModelBackend(failing)
        failing_backend.generate_response(self.understanding())
        after = failing_backend.check_availability()
        self.assertEqual(after.state, STATE_LOAD_FAILED)
        self.assertFalse(after.loadable)
        self.assertFalse(after.can_infer)
        self.assertEqual(after.error_code, ERROR_LOAD_FAILED)

    def test_availability_to_dict_is_plain_data(self):
        data = self.runtime().availability().to_dict()
        for key in ("configured", "enabled", "runtime_available", "loadable", "loaded",
                    "can_infer", "state", "error_code", "message", "model_id",
                    "runtime_name"):
            self.assertIn(key, data)

    def test_broken_runtime_yields_explicit_unavailable_not_exception(self):
        availability = LocalLanguageModelBackend(RaisingRuntime()).check_availability()
        self.assertFalse(availability.can_infer)
        self.assertNotIn("secret", availability.message)


# ======================================================================
class TestSuccessfulRuntimeInference(_Files, unittest.TestCase):
    """3. successful inference with a lightweight test double"""

    def test_full_flow_core_backend_runtime(self):
        runtime = self.runtime()
        runtime.output = RuntimeOutput("double says hi", "stop", 9, 3)
        core = LanguageIntelligenceCore(backend=LocalLanguageModelBackend(runtime))
        response = core.generate_response(self.understanding("What is Python?"))
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(response.response_text, "double says hi")
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(response.inference_status, STATUS_SUCCESS)
        self.assertIsNone(response.error_code)
        self.assertEqual(len(runtime.requests), 1)

    def test_loading_is_lazy_and_happens_once(self):
        runtime = self.runtime()
        backend = LocalLanguageModelBackend(runtime)
        self.assertEqual(runtime.load_calls, 0)          # construction never loads
        backend.check_availability()
        self.assertEqual(runtime.load_calls, 0)          # availability never loads
        backend.generate_response(self.understanding())
        backend.generate_response(self.understanding())
        self.assertEqual(runtime.load_calls, 1)
        self.assertEqual(len(runtime.requests), 2)

    def test_runtime_receives_only_an_inference_request(self):
        runtime = self.runtime()
        context = ConversationContext()
        context.add_turn("first q", "first a")
        context.add_turn("second q", "second a")
        backend = LocalLanguageModelBackend(runtime, system_prompt="Be brief.",
                                            max_context_turns=1)
        backend.generate_response(self.understanding("third q"), context=context)
        request = runtime.requests[0]
        self.assertIsInstance(request, InferenceRequest)
        self.assertEqual(request.user_input, "third q")
        self.assertEqual(request.system_prompt, "Be brief.")
        self.assertEqual([(m.role, m.content) for m in request.conversation],
                         [("user", "second q"), ("assistant", "second a")])
        self.assertEqual(sorted(request.to_dict()),
                         sorted(["request_id", "system_prompt", "user_input", "conversation",
                                 "parameters", "structured_output", "timeout_seconds",
                                 "language_context",  # Prompt 401 added language_context
                                 "generation_context",  # Prompt 426 added generation_context
                                 "generation_request"]))  # Prompt 427 added generation_request

    def test_context_is_read_only(self):
        runtime = self.runtime()
        context = ConversationContext()
        context.add_turn("q", "a")
        LocalLanguageModelBackend(runtime).generate_response(self.understanding(),
                                                             context=context)
        self.assertEqual(context.get_recent_turns(), [{"user": "q", "assistant": "a"}])

    def test_request_timeout_can_only_lower_the_configured_limit(self):
        runtime = self.runtime(timeout_seconds=10.0)
        ok = LocalLanguageModelBackend(runtime, timeout_seconds=2.0)
        self.assertEqual(ok.generate_response(self.understanding()).status, STATUS_GENERATED)
        too_high = LocalLanguageModelBackend(runtime, timeout_seconds=99.0)
        response = too_high.generate_response(self.understanding())
        self.assertEqual((response.status, response.inference_status),
                         (STATUS_MODEL_FAILED, STATUS_RESOURCE_LIMIT))


# ======================================================================
class TestRuntimeLoadFailure(_Files, unittest.TestCase):
    """4. runtime load failure"""

    def test_engine_load_error(self):
        runtime = self.runtime()
        runtime.load_error = ModelLoadError("corrupt weights")
        response = LocalLanguageModelBackend(runtime).generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_UNAVAILABLE)
        self.assertEqual(response.inference_status, INF_LOAD_FAILED)
        self.assertEqual(response.error_code, ERROR_LOAD_FAILED)
        self.assertIsNone(response.response_text)
        self.assertEqual(runtime.requests, [])
        self.assertIn("corrupt weights", response.reason)

    def test_missing_model_file(self):
        runtime = StubRuntime(_config("/definitely/missing/model.gguf"))
        response = LocalLanguageModelBackend(runtime).generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_UNAVAILABLE)
        self.assertEqual(response.error_code, ERROR_MODEL_FILE_NOT_FOUND)
        self.assertEqual(runtime.load_calls, 0)

    def test_failed_load_is_not_silently_retried(self):
        runtime = self.runtime()
        runtime.load_error = ModelLoadError("x")
        backend = LocalLanguageModelBackend(runtime)
        backend.generate_response(self.understanding())
        backend.generate_response(self.understanding())
        self.assertEqual(runtime.load_calls, 1)

    def test_out_of_memory_on_load_is_a_resource_failure(self):
        runtime = self.runtime()
        runtime.load_error = MemoryError()
        response = LocalLanguageModelBackend(runtime).generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_FAILED)
        self.assertEqual(response.inference_status, STATUS_RESOURCE_LIMIT)
        self.assertEqual(response.error_code, ERROR_OUT_OF_MEMORY)


# ======================================================================
class TestRuntimeInferenceFailure(_Files, unittest.TestCase):
    """5. runtime inference failure"""

    def test_engine_inference_error(self):
        runtime = self.runtime()
        runtime.infer_error = InferenceExecutionError("engine crashed")
        response = LocalLanguageModelBackend(runtime).generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_FAILED)
        self.assertEqual(response.inference_status, STATUS_INFERENCE_FAILED)
        self.assertEqual(response.error_code, ERROR_INFERENCE_FAILED)
        self.assertIsNone(response.response_text)
        self.assertIn("engine crashed", response.reason)

    def test_unexpected_engine_exception_is_translated(self):
        runtime = self.runtime()
        runtime.infer_error = ValueError("boom")
        response = LocalLanguageModelBackend(runtime).generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_FAILED)
        self.assertEqual(response.inference_status, STATUS_INFERENCE_FAILED)

    def test_empty_model_output_is_not_a_success(self):
        runtime = self.runtime()
        runtime.output = RuntimeOutput("   ")
        response = LocalLanguageModelBackend(runtime).generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_FAILED)
        self.assertIsNone(response.response_text)

    def test_bad_understanding_is_reported_not_raised(self):
        runtime = self.runtime()
        response = LocalLanguageModelBackend(runtime).generate_response(None)
        self.assertEqual((response.status, response.inference_status),
                         (STATUS_MODEL_FAILED, STATUS_INVALID_REQUEST))
        self.assertEqual(response.error_code, ERROR_INVALID_REQUEST)
        self.assertEqual(runtime.requests, [])

    def test_runtime_that_raises_is_reported_with_type_only(self):
        response = LocalLanguageModelBackend(RaisingRuntime()).generate_response(
            self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_FAILED)
        self.assertEqual(response.error_code, ERROR_INFERENCE_FAILED)
        self.assertIsNone(response.response_text)
        self.assertIn("RuntimeError", response.reason)
        self.assertNotIn("secret", response.reason)
        self.assertNotIn("/data/model.bin", str(response.to_dict()))

    def test_runtime_returning_wrong_type_is_a_failure(self):
        for value in (None, "plain text", {"status": "success", "text": "x"}):
            with self.subTest(value=value):
                response = LocalLanguageModelBackend(
                    WrongTypeRuntime(value)).generate_response(self.understanding())
                self.assertEqual(response.status, STATUS_MODEL_FAILED)
                self.assertEqual(response.error_code, ERROR_INVALID_RUNTIME_OUTPUT)
                self.assertIsNone(response.response_text)

    def test_success_status_without_text_is_a_failure(self):
        for text in (None, "", "  ", 42):
            with self.subTest(text=text):
                broken = InferenceResult(STATUS_SUCCESS, text=text)
                mapped = map_inference_result(broken, BACKEND_KIND_LOCAL_MODEL)
                self.assertEqual(mapped.status, STATUS_MODEL_FAILED)
                self.assertIsNone(mapped.response_text)


# ======================================================================
class TestRuntimeResourceAndTimeoutFailure(_Files, unittest.TestCase):
    """6. runtime resource / timeout failure"""

    def test_timeout(self):
        runtime = self.runtime(timeout_seconds=1.0)
        runtime.advance_clock_by = 2.0
        response = LocalLanguageModelBackend(runtime).generate_response(self.understanding())
        self.assertEqual((response.status, response.inference_status, response.error_code),
                         (STATUS_MODEL_FAILED, STATUS_TIMEOUT, ERROR_TIMED_OUT))
        self.assertIsNone(response.response_text)

    def test_context_length_limit_is_checked_before_loading(self):
        runtime = self.runtime(context_length=70, max_output_tokens=64)
        response = LocalLanguageModelBackend(runtime).generate_response(
            self.understanding("word " * 200))
        self.assertEqual((response.status, response.inference_status, response.error_code),
                         (STATUS_MODEL_FAILED, STATUS_RESOURCE_LIMIT,
                          ERROR_CONTEXT_LENGTH_EXCEEDED))
        self.assertEqual(runtime.load_calls, 0)
        self.assertEqual(runtime.requests, [])

    def test_engine_signalled_resource_limit(self):
        runtime = self.runtime()
        runtime.infer_error = ResourceLimitExceeded("kv cache too large")
        response = LocalLanguageModelBackend(runtime).generate_response(self.understanding())
        self.assertEqual((response.status, response.inference_status),
                         (STATUS_MODEL_FAILED, STATUS_RESOURCE_LIMIT))

    def test_engine_out_of_memory_during_inference(self):
        runtime = self.runtime()
        runtime.infer_error = MemoryError()
        response = LocalLanguageModelBackend(runtime).generate_response(self.understanding())
        self.assertEqual((response.status, response.error_code),
                         (STATUS_MODEL_FAILED, ERROR_OUT_OF_MEMORY))

    def test_cancellation_is_reported_by_the_runtime(self):
        runtime = self.runtime()
        token = CancellationToken()
        token.cancel()
        result = runtime.generate(InferenceRequest("hi"), cancellation_token=token)
        mapped = map_inference_result(result, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual((mapped.status, mapped.inference_status, mapped.error_code),
                         (STATUS_MODEL_FAILED, STATUS_CANCELLED, ERROR_CANCELLED))

    def test_a_failure_does_not_poison_the_next_request(self):
        runtime = self.runtime()
        backend = LocalLanguageModelBackend(runtime)
        runtime.infer_error = InferenceExecutionError("once")
        self.assertEqual(backend.generate_response(self.understanding()).status,
                         STATUS_MODEL_FAILED)
        runtime.infer_error = None
        self.assertEqual(backend.generate_response(self.understanding()).status,
                         STATUS_GENERATED)


# ======================================================================
class TestResultConversion(_Files, unittest.TestCase):
    """7. correct conversion of runtime output into ResponseGenerationResult"""

    def test_success_conversion_carries_text_and_metadata(self):
        runtime = self.runtime()
        runtime.output = RuntimeOutput("hello from the double", "stop", 11, 4)
        response = LocalLanguageModelBackend(runtime).generate_response(self.understanding())
        self.assertIsInstance(response, ResponseGenerationResult)
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(response.response_text, "hello from the double")
        self.assertIn("test-model", response.reason)
        self.assertIn("stub-runtime", response.reason)
        meta = response.metadata
        self.assertEqual(meta["model_id"], "test-model")
        self.assertEqual(meta["runtime_name"], "stub-runtime")
        self.assertEqual(meta["prompt_tokens"], 11)
        self.assertEqual(meta["output_tokens"], 4)
        self.assertEqual(meta["finish_reason"], "stop")
        self.assertTrue(meta["request_id"])
        self.assertIn("elapsed_seconds", meta)
        self.assertEqual(response.to_dict()["metadata"], meta)

    def test_token_counts_are_never_invented(self):
        runtime = self.runtime()
        runtime.output = RuntimeOutput("text")
        meta = LocalLanguageModelBackend(runtime).generate_response(
            self.understanding()).metadata
        self.assertIsNone(meta["prompt_tokens"])
        self.assertIsNone(meta["output_tokens"])

    def test_metadata_never_contains_prompt_or_response_text(self):
        runtime = self.runtime()
        runtime.output = RuntimeOutput("distinctive-response-xyz")
        response = LocalLanguageModelBackend(runtime).generate_response(
            self.understanding("distinctive-prompt-abc"))
        self.assertNotIn("distinctive", str(response.metadata))

    def test_failure_conversion_has_no_text_but_keeps_error_information(self):
        runtime = self.runtime()
        runtime.infer_error = InferenceExecutionError("engine crashed")
        response = LocalLanguageModelBackend(runtime).generate_response(self.understanding())
        self.assertIsNone(response.response_text)
        self.assertEqual(response.metadata["model_id"], "test-model")
        self.assertEqual(response.error_code, ERROR_INFERENCE_FAILED)

    def test_every_inference_status_maps_explicitly(self):
        expected = {
            STATUS_SUCCESS: STATUS_GENERATED,
            INF_NOT_CONFIGURED: STATUS_MODEL_NOT_CONFIGURED,
            INF_UNAVAILABLE: STATUS_MODEL_UNAVAILABLE,
            INF_LOAD_FAILED: STATUS_MODEL_UNAVAILABLE,
            STATUS_INFERENCE_FAILED: STATUS_MODEL_FAILED,
            STATUS_INVALID_REQUEST: STATUS_MODEL_FAILED,
            STATUS_RESOURCE_LIMIT: STATUS_MODEL_FAILED,
            STATUS_TIMEOUT: STATUS_MODEL_FAILED,
            STATUS_CANCELLED: STATUS_MODEL_FAILED,
        }
        self.assertEqual(set(expected), set(ALL_INFERENCE_STATUSES))
        for inference_status, response_status in expected.items():
            with self.subTest(inference_status=inference_status):
                if inference_status == STATUS_SUCCESS:
                    result = InferenceResult.success("real text", model_id="m",
                                                     runtime_name="r")
                else:
                    result = InferenceResult.failure(inference_status, "code", "message")
                mapped = map_inference_result(result, BACKEND_KIND_LOCAL_MODEL)
                self.assertEqual(mapped.status, response_status)
                self.assertEqual(mapped.inference_status, inference_status)
                self.assertEqual(mapped.response_text is not None,
                                 inference_status == STATUS_SUCCESS)

    def test_unknown_inference_status_is_a_failure_never_a_success(self):
        mapped = map_inference_result(InferenceResult("something_new"), "local_model")
        self.assertEqual(mapped.status, STATUS_MODEL_FAILED)
        self.assertIsNone(mapped.response_text)

    def test_mapping_table_only_lists_non_failure_translations(self):
        for value in INFERENCE_TO_RESPONSE_STATUS.values():
            self.assertIn(value, (STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE))

    def test_build_inference_request_handles_bad_input_without_raising(self):
        for understanding in (None, object(), "text"):
            with self.subTest(understanding=understanding):
                request = build_inference_request(understanding)
                self.assertTrue(request.validate())        # reported, not raised

    def test_conversation_mapping_skips_malformed_turns(self):
        class Ctx:
            def get_recent_turns(self, n):
                return [{"user": "q", "assistant": "a"}, {"user": "only"}, "junk", None]
        messages = conversation_from_context(Ctx(), 4)
        self.assertEqual([(m.role, m.content) for m in messages],
                         [("user", "q"), ("assistant", "a")])
        self.assertEqual(conversation_from_context(Ctx(), 0), [])
        self.assertEqual(conversation_from_context(None, 4), [])
        self.assertEqual(conversation_from_context(Ctx(), True), [])


# ======================================================================
class TestDeterministicFallbackRemainsSeparate(_Files, unittest.TestCase):
    """8. deterministic fallback remains separate"""

    def test_fallback_still_defers_and_carries_no_model_metadata(self):
        backend = DeterministicFallbackBackend(UnderstandingEngine())
        response = LanguageIntelligenceCore(backend=backend).generate_response(
            backend.understand("Hello."))
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertEqual(response.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertIsNone(response.inference_status)
        self.assertIsNone(response.metadata)

    def test_local_backend_failure_is_never_replaced_by_fallback_output(self):
        understanding = self.understanding("Hello.")
        for backend in (LocalLanguageModelBackend(),
                        LocalLanguageModelBackend(UnavailableLocalModelRuntime(_config())),
                        LocalLanguageModelBackend(RaisingRuntime())):
            response = backend.generate_response(understanding)
            self.assertNotEqual(response.status, STATUS_DEFERRED)
            self.assertNotEqual(response.status, STATUS_GENERATED)
            self.assertNotEqual(response.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
            self.assertIsNone(response.response_text)

    def test_fallback_works_while_the_local_model_is_broken(self):
        broken = LanguageIntelligenceCore(backend=LocalLanguageModelBackend())
        fallback = LanguageIntelligenceCore(
            backend=DeterministicFallbackBackend(UnderstandingEngine()))
        self.assertEqual(broken.generate_response(self.understanding()).status,
                         STATUS_MODEL_NOT_CONFIGURED)
        result = fallback.understand("What is Python?")
        self.assertEqual(result.source_backend, BACKEND_KIND_DETERMINISTIC_FALLBACK)

    def test_local_modules_do_not_reference_the_deterministic_backend(self):
        base = os.path.dirname(language_intelligence.__file__)
        for name in ("local_model_backend.py", "local_model_mapping.py",
                     "local_model_runtime.py"):
            with self.subTest(module=name):
                code = _strip(_read(os.path.join(base, name)))
                self.assertNotIn("deterministic_fallback_backend", code)
                self.assertNotIn("DeterministicFallbackBackend", code)

    def test_deterministic_backend_does_not_reference_the_local_model_path(self):
        base = os.path.dirname(language_intelligence.__file__)
        code = _strip(_read(os.path.join(base, "deterministic_fallback_backend.py")))
        for name in ("local_model_runtime", "local_model_backend", "local_model_mapping",
                     "LocalModelRuntime"):
            self.assertNotIn(name, code)


# ======================================================================
class TestLanguageIntelligenceCoreCompatibility(_Files, unittest.TestCase):
    """9. existing LanguageIntelligenceCore behavior remains compatible"""

    def test_core_routes_to_whichever_backend_it_holds(self):
        runtime = self.runtime()
        understanding = self.understanding("Hi.")
        deterministic = LanguageIntelligenceCore(
            backend=DeterministicFallbackBackend(UnderstandingEngine()))
        local = LanguageIntelligenceCore(backend=LocalLanguageModelBackend(runtime))
        self.assertEqual(deterministic.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(local.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(deterministic.generate_response(understanding).status,
                         STATUS_DEFERRED)
        self.assertEqual(local.generate_response(understanding).status, STATUS_GENERATED)

    def test_real_project_core_still_uses_the_deterministic_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Core(memory_db_path=os.path.join(tmp, "test_memory.sqlite3"),
                        skill_definitions_dir=os.path.join(tmp, "skills"))
            self.assertEqual(core.language_intelligence.backend_kind,
                             BACKEND_KIND_DETERMINISTIC_FALLBACK)
            self.assertNotIsInstance(core.language_intelligence.backend,
                                     LocalLanguageModelBackend)
            response = core.generate_language_response(core.understand_language("Hi"))
            self.assertEqual(response.status, STATUS_DEFERRED)

    def test_response_result_is_backward_compatible(self):
        old_style = ResponseGenerationResult(STATUS_DEFERRED, None, "why", "deterministic_fallback")
        self.assertIsNone(old_style.metadata)
        as_dict = old_style.to_dict()
        for key in ("status", "response_text", "reason", "backend_kind",
                    "inference_status", "error_code"):
            self.assertIn(key, as_dict)

    def test_understand_on_local_backend_never_loads_or_fabricates(self):
        runtime = self.runtime()
        with self.assertRaises(NotImplementedError):
            LocalLanguageModelBackend(runtime).understand("hello")
        self.assertEqual(runtime.load_calls, 0)
        self.assertEqual(runtime.requests, [])


# ======================================================================
class TestNoCloudNoNetworkNoFakeModel(unittest.TestCase):
    FORBIDDEN_IMPORTS = {
        "requests", "urllib", "urllib3", "http", "httpx", "socket", "ssl", "aiohttp",
        "openai", "anthropic", "google", "boto3", "ftplib", "smtplib", "websocket",
        "random",
    }

    def test_mapping_and_backend_are_on_device_only(self):
        base = os.path.dirname(language_intelligence.__file__)
        for name in ("local_model_mapping.py", "local_model_backend.py"):
            with self.subTest(module=name):
                source = _read(os.path.join(base, name))
                imported = {m.group(1) for m in re.finditer(
                    r"^\s*(?:from|import)\s+([A-Za-z_]\w*)", source, re.M)}
                self.assertEqual(imported & self.FORBIDDEN_IMPORTS, set())
                code = _strip(source).lower()
                self.assertNotIn("api_key", code)
                self.assertNotIn("apikey", code)

    def test_mapping_module_exposes_no_text_generation(self):
        names = [n for n in dir(local_model_mapping)
                 if not n.startswith("_") and callable(getattr(local_model_mapping, n))]
        self.assertFalse([n for n in names if "generate" in n.lower()
                          or "fake" in n.lower() or "canned" in n.lower()])


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _strip(source):
    source = re.sub(r'"""[\s\S]*?"""', "", source)
    return re.sub(r"#.*", "", source)


if __name__ == "__main__":
    unittest.main()
