"""
Tests for the Local Language Model Runtime Foundation (Prompt 398,
language_intelligence/local_model_*.py, inference.py,
unavailable_runtime.py).

IMPORTANT - about the test double: `ScriptedTestRuntime` below is a
TEST DOUBLE used only to exercise the runtime *boundary* (state
handling, limits, error translation, backend mapping). Its "output" is
whatever string a test scripts into it. It is NOT a language model, it
performs NO inference, and nothing here claims otherwise. No model file
is needed; nothing is downloaded.

Run directly:
    python -m unittest tests.test_local_model_runtime -v
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
    ResponseGenerationResult, STATUS_DEFERRED, STATUS_GENERATED, STATUS_NOT_IMPLEMENTED,
    STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_FAILED, ALL_STATUSES,
)
from language_intelligence.local_model_config import (
    LocalModelConfig, ConfigValidationResult, MODEL_FORMAT_GGUF, MODEL_FORMAT_ONNX,
    DEFAULT_CONTEXT_LENGTH,
)
from language_intelligence.inference import (
    InferenceRequest, InferenceResult, GenerationParameters, ConversationMessage,
    StructuredOutputRequirement, ALL_INFERENCE_STATUSES,
    STATUS_SUCCESS, STATUS_MODEL_NOT_CONFIGURED as INF_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE as INF_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED,
    STATUS_INFERENCE_FAILED, STATUS_INVALID_REQUEST, STATUS_RESOURCE_LIMIT,
    STATUS_TIMEOUT, STATUS_CANCELLED,
    ERROR_NO_CONFIGURATION, ERROR_MODEL_DISABLED, ERROR_INVALID_CONFIGURATION,
    ERROR_RUNTIME_DEPENDENCY_MISSING, ERROR_MODEL_FILE_NOT_FOUND,
    ERROR_MODEL_EXCEEDS_MEMORY_LIMIT, ERROR_OUT_OF_MEMORY, ERROR_LOAD_FAILED,
    ERROR_CONTEXT_LENGTH_EXCEEDED, ERROR_MAX_OUTPUT_TOKENS_EXCEEDED,
    ERROR_TIMEOUT_EXCEEDS_LIMIT, ERROR_OUTPUT_EXCEEDS_LIMIT, ERROR_TIMED_OUT,
    ERROR_COMPLETED_AFTER_DEADLINE, ERROR_CANCELLED, ERROR_INFERENCE_FAILED,
    ERROR_EMPTY_OUTPUT, ERROR_INVALID_RUNTIME_OUTPUT, ERROR_STRUCTURED_OUTPUT_INVALID,
    ERROR_INVALID_REQUEST, ERROR_MODEL_NOT_LOADED,
)
from language_intelligence.local_model_runtime import (
    LocalModelRuntime, ModelLoadError, InferenceExecutionError, ResourceLimitExceeded,
    CancellationToken, RuntimeOutput,
    STATE_NOT_CONFIGURED, STATE_RUNTIME_UNAVAILABLE, STATE_UNLOADED, STATE_READY,
    STATE_LOAD_FAILED, LOAD_OK, LOAD_NOT_CONFIGURED, LOAD_RUNTIME_UNAVAILABLE,
    LOAD_FAILED, LOAD_RESOURCE_LIMIT,
)
from language_intelligence.unavailable_runtime import (
    UnavailableLocalModelRuntime, MISSING_DEPENDENCY_MESSAGE,
)
from language_intelligence.local_model_backend import (
    LocalLanguageModelBackend, LocalModelBackendError,
)


# ----------------------------------------------------------------------
# Test doubles (NOT a language model)
# ----------------------------------------------------------------------
class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ScriptedTestRuntime(LocalModelRuntime):
    """TEST DOUBLE. Returns exactly what a test scripts; performs no
    inference of any kind."""

    def __init__(self, config=None, clock=None):
        super().__init__(config=config, clock=clock)
        self.dependency_available = True
        self.load_calls = 0
        self.unload_calls = 0
        self.infer_calls = []
        self.load_side_effect = None      # exception instance to raise
        self.infer_side_effect = None     # exception instance to raise
        self.scripted_output = RuntimeOutput("scripted-test-double-output", "stop")
        self.advance_clock_by = 0.0       # simulated time spent "inferring"
        self.poll_control = False         # call control.check() while "running"
        self.cancel_token_during_run = None

    @property
    def runtime_name(self):
        return "scripted-test-double"

    def dependency_status(self):
        if self.dependency_available:
            return True, ""
        return False, "test double: engine missing"

    def _load_model(self, config):
        self.load_calls += 1
        if self.load_side_effect is not None:
            raise self.load_side_effect

    def _unload_model(self):
        self.unload_calls += 1

    def _run_inference(self, request, params, config, control):
        self.infer_calls.append((request, params, config))
        if self.cancel_token_during_run is not None:
            self.cancel_token_during_run.cancel()
        if self.advance_clock_by:
            self._clock.advance(self.advance_clock_by)
        if self.poll_control:
            control.check()
        if self.infer_side_effect is not None:
            raise self.infer_side_effect
        return self.scripted_output


def _model_file(size_bytes=16):
    handle = tempfile.NamedTemporaryFile(suffix=".gguf", delete=False)
    handle.write(b"\0" * size_bytes)
    handle.close()
    return handle.name


def _config(path="/nonexistent/but/valid/model.gguf", **overrides):
    values = dict(model_id="test-model", model_path=path, context_length=512,
                  max_output_tokens=64, timeout_seconds=10.0)
    values.update(overrides)
    return LocalModelConfig(**values)


def _request(text="Hello there.", **kwargs):
    return InferenceRequest(user_input=text, **kwargs)


class _TempFilesMixin:
    def setUp(self):
        self._files = []

    def tearDown(self):
        for path in self._files:
            if os.path.exists(path):
                os.remove(path)

    def model_file(self, size_bytes=16):
        path = _model_file(size_bytes)
        self._files.append(path)
        return path

    def ready_runtime(self, clock=None, **config_overrides):
        clock = clock or FakeClock()
        runtime = ScriptedTestRuntime(_config(self.model_file(), **config_overrides), clock=clock)
        return runtime, clock


# ======================================================================
class TestValidModelConfiguration(unittest.TestCase):
    """1. valid model configuration"""

    def test_defaults_with_id_and_path_are_valid(self):
        config = LocalModelConfig(model_id="m", model_path="/data/m.gguf")
        result = config.validate()
        self.assertIsInstance(result, ConfigValidationResult)
        self.assertTrue(result.valid)
        self.assertTrue(result)
        self.assertEqual(result.problems, [])
        self.assertEqual(config.context_length, DEFAULT_CONTEXT_LENGTH)
        self.assertEqual(config.model_format, MODEL_FORMAT_GGUF)
        self.assertTrue(config.enabled)

    def test_fully_specified_config_is_valid(self):
        config = LocalModelConfig(
            model_id="m", model_path="/data/m.onnx", model_format=MODEL_FORMAT_ONNX,
            context_length=4096, max_output_tokens=512, temperature=0.0, top_p=1.0,
            cpu_threads=4, max_memory_mb=1500, timeout_seconds=30, enabled=True)
        self.assertTrue(config.validate().valid)

    def test_disabled_config_may_omit_the_path(self):
        self.assertTrue(LocalModelConfig(model_id="m", enabled=False).validate().valid)

    def test_from_dict_roundtrip(self):
        original = _config(cpu_threads=2)
        rebuilt = LocalModelConfig.from_dict(original.to_dict())
        self.assertEqual(rebuilt.to_dict(), original.to_dict())
        self.assertTrue(rebuilt.validate().valid)

    def test_validation_does_not_touch_the_filesystem(self):
        self.assertTrue(_config("/definitely/not/here.gguf").validate().valid)


class TestInvalidModelConfiguration(unittest.TestCase):
    """2. invalid model configuration"""

    def _problems(self, config):
        result = config.validate()
        self.assertFalse(result.valid)
        return " | ".join(result.problems)

    def test_missing_model_id(self):
        self.assertIn("model_id", self._problems(LocalModelConfig(model_path="/x.gguf")))
        self.assertIn("model_id", self._problems(_config(model_id="   ")))

    def test_enabled_config_requires_path(self):
        self.assertIn("model_path", self._problems(LocalModelConfig(model_id="m")))

    def test_remote_model_locations_are_rejected(self):
        for url in ("https://example.com/m.gguf", "http://x/m", "ftp://x/m", "s3://bucket/m"):
            self.assertIn("LOCAL path", self._problems(_config(url)))

    def test_windows_style_local_path_is_not_mistaken_for_a_url(self):
        self.assertTrue(_config("C:\\models\\m.gguf").validate().valid)

    def test_nul_in_path(self):
        self.assertIn("NUL", self._problems(_config("/a\x00b")))

    def test_unknown_format(self):
        self.assertIn("model_format", self._problems(_config(model_format="pickle")))

    def test_bad_numeric_values(self):
        for field, value in (
            ("context_length", 0), ("context_length", -5), ("context_length", 10 ** 9),
            ("context_length", 2.5), ("max_output_tokens", 0), ("temperature", -0.1),
            ("temperature", 5), ("top_p", 0), ("top_p", 1.5), ("cpu_threads", 0),
            ("max_memory_mb", 0), ("timeout_seconds", 0), ("timeout_seconds", -1),
        ):
            with self.subTest(field=field, value=value):
                self.assertIn(field, self._problems(_config(**{field: value})))

    def test_booleans_and_nan_are_not_accepted_as_numbers(self):
        self.assertIn("context_length", self._problems(_config(context_length=True)))
        self.assertIn("temperature", self._problems(_config(temperature=float("nan"))))
        self.assertIn("timeout_seconds", self._problems(_config(timeout_seconds=float("inf"))))

    def test_output_tokens_must_leave_room_in_context(self):
        self.assertIn("max_output_tokens",
                      self._problems(_config(context_length=100, max_output_tokens=100)))

    def test_wrong_types_never_raise(self):
        for bad in (
            _config(model_id=None), _config(temperature="hot"), _config(context_length=None),
            _config(enabled="yes"), _config(model_path=123), _config(cpu_threads="4"),
        ):
            self.assertFalse(bad.validate().valid)

    def test_all_problems_are_reported_not_just_the_first(self):
        result = _config(context_length=0, temperature=9, top_p=0).validate()
        self.assertGreaterEqual(len(result.problems), 3)

    def test_unknown_fields_and_non_dict_are_reported(self):
        config = LocalModelConfig.from_dict({"model_id": "m", "model_path": "/x", "api_key": "k"})
        self.assertIn("api_key", " ".join(config.validate().problems))
        self.assertFalse(LocalModelConfig.from_dict("nope").validate().valid)
        self.assertFalse(LocalModelConfig.from_dict(None).validate().valid)


# ======================================================================
class TestInferenceRequestCreation(unittest.TestCase):
    """3. inference request creation"""

    def test_minimal_request_is_valid(self):
        request = InferenceRequest(user_input="Hi")
        self.assertEqual(request.validate(), [])
        self.assertEqual(request.conversation, [])
        self.assertIsInstance(request.parameters, GenerationParameters)
        self.assertIsNone(request.structured_output)

    def test_full_request(self):
        request = InferenceRequest(
            user_input="Q?", system_prompt="Be brief.",
            conversation=[{"role": "user", "content": "a"},
                          ConversationMessage("assistant", "b")],
            parameters=GenerationParameters(max_output_tokens=10, temperature=0.2, top_p=0.9,
                                            seed=1, stop_sequences=["\n\n"]),
            structured_output=StructuredOutputRequirement(required_keys=["answer"]),
            timeout_seconds=5)
        self.assertEqual(request.validate(), [])
        self.assertTrue(all(isinstance(m, ConversationMessage) for m in request.conversation))
        as_dict = request.to_dict()
        self.assertEqual(as_dict["system_prompt"], "Be brief.")
        self.assertEqual(as_dict["parameters"]["max_output_tokens"], 10)
        self.assertEqual(as_dict["structured_output"]["required_keys"], ["answer"])

    def test_request_ids_are_unique_unless_given(self):
        self.assertNotEqual(InferenceRequest("a").request_id, InferenceRequest("a").request_id)
        self.assertEqual(InferenceRequest("a", request_id="r1").request_id, "r1")

    def test_invalid_requests_are_reported_not_raised(self):
        cases = [
            InferenceRequest(user_input=""),
            InferenceRequest(user_input=None),
            InferenceRequest(user_input="x", system_prompt=5),
            InferenceRequest(user_input="x", conversation="not a list"),
            InferenceRequest(user_input="x", conversation=[{"role": "robot", "content": "a"}]),
            InferenceRequest(user_input="x", conversation=[{"role": "user", "content": 3}]),
            InferenceRequest(user_input="x", conversation=[42]),
            InferenceRequest(user_input="x", parameters=GenerationParameters(max_output_tokens=0)),
            InferenceRequest(user_input="x", parameters=GenerationParameters(temperature=9)),
            InferenceRequest(user_input="x", parameters=GenerationParameters(top_p=0)),
            InferenceRequest(user_input="x", parameters=GenerationParameters(seed="s")),
            InferenceRequest(user_input="x", parameters="nope"),
            InferenceRequest(user_input="x",
                             structured_output=StructuredOutputRequirement(output_format="xml")),
            InferenceRequest(user_input="x", timeout_seconds=0),
        ]
        for request in cases:
            with self.subTest(request=request.to_dict()):
                self.assertTrue(request.validate())

    def test_input_char_count(self):
        request = InferenceRequest(user_input="abc", system_prompt="de",
                                   conversation=[{"role": "user", "content": "f"}])
        self.assertEqual(request.input_char_count(), 6)


class TestInferenceResultCreation(unittest.TestCase):
    """4. inference result creation"""

    def test_success_result(self):
        result = InferenceResult.success("text", runtime_name="r", model_id="m", request_id="1",
                                         output_tokens=3, finish_reason="stop")
        self.assertTrue(result.ok)
        self.assertEqual(result.status, STATUS_SUCCESS)
        self.assertEqual(result.text, "text")
        self.assertIsNone(result.error_code)
        self.assertEqual(result.to_dict()["output_tokens"], 3)

    def test_failure_result_has_no_text(self):
        result = InferenceResult.failure(STATUS_TIMEOUT, ERROR_TIMED_OUT, "too slow",
                                         details={"limit": 1})
        self.assertFalse(result.ok)
        self.assertIsNone(result.text)
        self.assertEqual(result.error_code, ERROR_TIMED_OUT)
        self.assertEqual(result.to_dict()["details"], {"limit": 1})

    def test_failure_cannot_claim_success(self):
        with self.assertRaises(ValueError):
            InferenceResult.failure(STATUS_SUCCESS, "x", "y")

    def test_status_vocabulary_covers_every_required_outcome(self):
        for status in (STATUS_SUCCESS, INF_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED,
                       STATUS_INFERENCE_FAILED, STATUS_INVALID_REQUEST, STATUS_RESOURCE_LIMIT,
                       STATUS_TIMEOUT, STATUS_CANCELLED, INF_NOT_CONFIGURED):
            self.assertIn(status, ALL_INFERENCE_STATUSES)
        self.assertEqual(len(set(ALL_INFERENCE_STATUSES)), len(ALL_INFERENCE_STATUSES))


# ======================================================================
class TestUnavailableModelState(unittest.TestCase):
    """5. unavailable model state"""

    def test_valid_config_but_no_engine_is_explicitly_unavailable(self):
        runtime = UnavailableLocalModelRuntime(_config())
        self.assertEqual(runtime.state, STATE_RUNTIME_UNAVAILABLE)
        result = runtime.generate(_request())
        self.assertEqual(result.status, INF_UNAVAILABLE)
        self.assertEqual(result.error_code, ERROR_RUNTIME_DEPENDENCY_MISSING)
        self.assertEqual(result.error_message, MISSING_DEPENDENCY_MESSAGE)
        self.assertIsNone(result.text)
        self.assertEqual(result.runtime_name, "unavailable")
        self.assertIn("docs/local_model_runtime.md", MISSING_DEPENDENCY_MESSAGE)

    def test_load_reports_runtime_unavailable(self):
        loaded = UnavailableLocalModelRuntime(_config()).load()
        self.assertFalse(loaded.ok)
        self.assertEqual(loaded.status, LOAD_RUNTIME_UNAVAILABLE)

    def test_scripted_runtime_reports_unavailable_when_dependency_missing(self):
        runtime = ScriptedTestRuntime(_config())
        runtime.dependency_available = False
        self.assertEqual(runtime.generate(_request()).status, INF_UNAVAILABLE)
        self.assertEqual(runtime.load_calls, 0)

    def test_unavailable_runtime_never_produces_text_under_any_call(self):
        runtime = UnavailableLocalModelRuntime(_config())
        for _ in range(3):
            self.assertIsNone(runtime.generate(_request()).text)

    def test_describe_is_read_only_diagnostics(self):
        info = UnavailableLocalModelRuntime(_config()).describe()
        self.assertEqual(info["state"], STATE_RUNTIME_UNAVAILABLE)
        self.assertFalse(info["runtime_dependency_available"])


class TestMissingModelConfiguration(unittest.TestCase):
    """6. missing model configuration"""

    def test_no_configuration(self):
        for runtime in (UnavailableLocalModelRuntime(), ScriptedTestRuntime()):
            with self.subTest(runtime=runtime.runtime_name):
                self.assertEqual(runtime.state, STATE_NOT_CONFIGURED)
                result = runtime.generate(_request())
                self.assertEqual(result.status, INF_NOT_CONFIGURED)
                self.assertEqual(result.error_code, ERROR_NO_CONFIGURATION)
                self.assertIsNone(result.text)
                self.assertEqual(runtime.load().status, LOAD_NOT_CONFIGURED)

    def test_disabled_configuration_is_not_configured(self):
        runtime = ScriptedTestRuntime(_config(enabled=False))
        result = runtime.generate(_request())
        self.assertEqual(result.status, INF_NOT_CONFIGURED)
        self.assertEqual(result.error_code, ERROR_MODEL_DISABLED)
        self.assertEqual(runtime.load_calls, 0)

    def test_invalid_configuration_is_not_configured_and_says_why(self):
        runtime = ScriptedTestRuntime(_config(context_length=0))
        result = runtime.generate(_request())
        self.assertEqual(result.status, INF_NOT_CONFIGURED)
        self.assertEqual(result.error_code, ERROR_INVALID_CONFIGURATION)
        self.assertIn("context_length", result.error_message)
        self.assertEqual(runtime.load_calls, 0)

    def test_non_config_object_is_not_configured(self):
        runtime = ScriptedTestRuntime()
        runtime.configure({"model_id": "m"})
        self.assertEqual(runtime.generate(_request()).status, INF_NOT_CONFIGURED)

    def test_reconfiguring_recovers(self):
        runtime = ScriptedTestRuntime()
        self.assertEqual(runtime.generate(_request()).status, INF_NOT_CONFIGURED)
        with tempfile.NamedTemporaryFile(suffix=".gguf") as handle:
            runtime.configure(_config(handle.name))
            self.assertEqual(runtime.generate(_request()).status, STATUS_SUCCESS)


# ======================================================================
class TestModelLoadingFailure(_TempFilesMixin, unittest.TestCase):
    """7. loading failure"""

    def test_missing_model_file(self):
        runtime = ScriptedTestRuntime(_config("/no/such/model.gguf"), clock=FakeClock())
        result = runtime.generate(_request())
        self.assertEqual(result.status, STATUS_MODEL_LOAD_FAILED)
        self.assertEqual(result.error_code, ERROR_MODEL_FILE_NOT_FOUND)
        self.assertEqual(runtime.load_calls, 0)
        self.assertEqual(runtime.state, STATE_LOAD_FAILED)

    def test_engine_load_error_is_translated(self):
        runtime, _ = self.ready_runtime()
        runtime.load_side_effect = ModelLoadError("corrupt weights", "corrupt")
        result = runtime.generate(_request())
        self.assertEqual(result.status, STATUS_MODEL_LOAD_FAILED)
        self.assertEqual(result.error_code, "corrupt")
        self.assertIn("corrupt weights", result.error_message)

    def test_unexpected_load_exception_is_translated_not_raised(self):
        runtime, _ = self.ready_runtime()
        runtime.load_side_effect = RuntimeError("boom")
        result = runtime.generate(_request())
        self.assertEqual(result.status, STATUS_MODEL_LOAD_FAILED)
        self.assertEqual(result.error_code, ERROR_LOAD_FAILED)
        self.assertIn("RuntimeError", result.error_message)

    def test_memory_limit_checked_against_model_file_size(self):
        path = self.model_file(size_bytes=3 * 1024 * 1024)
        runtime = ScriptedTestRuntime(_config(path, max_memory_mb=1), clock=FakeClock())
        result = runtime.generate(_request())
        self.assertEqual(result.status, STATUS_RESOURCE_LIMIT)
        self.assertEqual(result.error_code, ERROR_MODEL_EXCEEDS_MEMORY_LIMIT)
        self.assertEqual(runtime.load_calls, 0)
        self.assertEqual(runtime.load().status, LOAD_RESOURCE_LIMIT)

    def test_model_within_memory_limit_loads(self):
        path = self.model_file(size_bytes=1024)
        runtime = ScriptedTestRuntime(_config(path, max_memory_mb=1), clock=FakeClock())
        self.assertTrue(runtime.load().ok)

    def test_engine_out_of_memory_on_load(self):
        runtime, _ = self.ready_runtime()
        runtime.load_side_effect = MemoryError()
        loaded = runtime.load()
        self.assertEqual(loaded.status, LOAD_RESOURCE_LIMIT)
        self.assertEqual(loaded.error_code, ERROR_OUT_OF_MEMORY)

    def test_failed_load_is_not_silently_retried_but_can_be_retried_explicitly(self):
        runtime, _ = self.ready_runtime()
        runtime.load_side_effect = ModelLoadError("first failure")
        self.assertEqual(runtime.generate(_request()).status, STATUS_MODEL_LOAD_FAILED)
        self.assertEqual(runtime.generate(_request()).status, STATUS_MODEL_LOAD_FAILED)
        self.assertEqual(runtime.load_calls, 1)          # no automatic retry

        runtime.load_side_effect = None
        self.assertTrue(runtime.load().ok)               # explicit retry
        self.assertEqual(runtime.state, STATE_READY)
        self.assertEqual(runtime.generate(_request()).status, STATUS_SUCCESS)

    def test_load_is_lazy_and_happens_once(self):
        runtime, _ = self.ready_runtime()
        self.assertEqual(runtime.state, STATE_UNLOADED)
        self.assertEqual(runtime.load_calls, 0)
        runtime.generate(_request())
        runtime.generate(_request())
        self.assertEqual(runtime.load_calls, 1)
        self.assertEqual(runtime.state, STATE_READY)

    def test_unload_and_reconfigure_release_the_model(self):
        runtime, _ = self.ready_runtime()
        runtime.generate(_request())
        runtime.unload()
        self.assertEqual(runtime.unload_calls, 1)
        self.assertEqual(runtime.state, STATE_UNLOADED)
        runtime.generate(_request())
        runtime.configure(None)
        self.assertEqual(runtime.unload_calls, 2)
        self.assertEqual(runtime.state, STATE_NOT_CONFIGURED)


class TestInferenceFailure(_TempFilesMixin, unittest.TestCase):
    """8. inference failure"""

    def test_success_returns_exactly_what_the_runtime_returned(self):
        runtime, _ = self.ready_runtime()
        runtime.scripted_output = RuntimeOutput("some text", "stop", prompt_tokens=5,
                                                output_tokens=2)
        result = runtime.generate(_request())
        self.assertTrue(result.ok)
        self.assertEqual(result.text, "some text")
        self.assertEqual((result.prompt_tokens, result.output_tokens), (5, 2))
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.model_id, "test-model")

    def test_engine_inference_error(self):
        runtime, _ = self.ready_runtime()
        runtime.infer_side_effect = InferenceExecutionError("kv cache full", "kv_full")
        result = runtime.generate(_request())
        self.assertEqual(result.status, STATUS_INFERENCE_FAILED)
        self.assertEqual(result.error_code, "kv_full")
        self.assertIsNone(result.text)

    def test_unexpected_inference_exception_is_translated(self):
        runtime, _ = self.ready_runtime()
        runtime.infer_side_effect = ValueError("bad tensor")
        result = runtime.generate(_request())
        self.assertEqual(result.status, STATUS_INFERENCE_FAILED)
        self.assertEqual(result.error_code, ERROR_INFERENCE_FAILED)
        self.assertIn("ValueError", result.error_message)

    def test_failed_inference_leaves_model_loaded(self):
        runtime, _ = self.ready_runtime()
        runtime.infer_side_effect = ValueError("x")
        runtime.generate(_request())
        self.assertEqual(runtime.state, STATE_READY)
        runtime.infer_side_effect = None
        self.assertTrue(runtime.generate(_request()).ok)

    def test_empty_output_is_a_failure_not_a_success(self):
        runtime, _ = self.ready_runtime()
        for text in ("", "   \n"):
            runtime.scripted_output = RuntimeOutput(text)
            result = runtime.generate(_request())
            self.assertEqual(result.status, STATUS_INFERENCE_FAILED)
            self.assertEqual(result.error_code, ERROR_EMPTY_OUTPUT)

    def test_malformed_runtime_output_is_a_failure(self):
        runtime, _ = self.ready_runtime()
        for bad in ("plain string", None, RuntimeOutput(None), RuntimeOutput(42)):
            runtime.scripted_output = bad
            result = runtime.generate(_request())
            self.assertEqual(result.status, STATUS_INFERENCE_FAILED)
            self.assertEqual(result.error_code, ERROR_INVALID_RUNTIME_OUTPUT)

    def test_invalid_request_never_reaches_the_model(self):
        runtime, _ = self.ready_runtime()
        result = runtime.generate(_request(text=""))
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)
        self.assertEqual(result.error_code, ERROR_INVALID_REQUEST)
        self.assertEqual(runtime.infer_calls, [])
        self.assertEqual(runtime.load_calls, 0)
        self.assertEqual(runtime.generate("not a request").status, STATUS_INVALID_REQUEST)
        self.assertEqual(runtime.generate(None).status, STATUS_INVALID_REQUEST)

    def test_structured_output_valid_json(self):
        runtime, _ = self.ready_runtime()
        runtime.scripted_output = RuntimeOutput('{"answer": 1, "extra": 2}')
        result = runtime.generate(_request(
            structured_output=StructuredOutputRequirement(required_keys=["answer"])))
        self.assertTrue(result.ok)
        self.assertEqual(result.structured_output, {"answer": 1, "extra": 2})

    def test_structured_output_not_json_is_reported(self):
        runtime, _ = self.ready_runtime()
        runtime.scripted_output = RuntimeOutput("definitely not json")
        result = runtime.generate(_request(structured_output=StructuredOutputRequirement()))
        self.assertEqual(result.status, STATUS_INFERENCE_FAILED)
        self.assertEqual(result.error_code, ERROR_STRUCTURED_OUTPUT_INVALID)
        self.assertIsNone(result.text)
        self.assertIn("output_preview", result.details)

    def test_structured_output_missing_keys_or_wrong_shape(self):
        runtime, _ = self.ready_runtime()
        requirement = StructuredOutputRequirement(required_keys=["answer"])
        for text in ('{"other": 1}', "[1, 2]"):
            runtime.scripted_output = RuntimeOutput(text)
            result = runtime.generate(_request(structured_output=requirement))
            self.assertEqual(result.error_code, ERROR_STRUCTURED_OUTPUT_INVALID)

    def test_request_defaults_come_from_configuration(self):
        runtime, _ = self.ready_runtime(temperature=0.3, top_p=0.8, max_output_tokens=32)
        runtime.generate(_request())
        _request_seen, params, _config_seen = runtime.infer_calls[0]
        self.assertEqual((params.temperature, params.top_p, params.max_output_tokens),
                         (0.3, 0.8, 32))

    def test_request_parameters_override_configuration(self):
        runtime, _ = self.ready_runtime()
        runtime.generate(_request(parameters=GenerationParameters(
            temperature=0.0, max_output_tokens=8, seed=7, stop_sequences=["END"])))
        params = runtime.infer_calls[0][1]
        self.assertEqual((params.temperature, params.max_output_tokens, params.seed,
                          params.stop_sequences), (0.0, 8, 7, ["END"]))


class TestTimeoutAndResourceHandling(_TempFilesMixin, unittest.TestCase):
    """9. timeout / cancellation / resource handling"""

    def test_context_length_exceeded_is_a_resource_limit_before_loading(self):
        runtime, _ = self.ready_runtime(context_length=100, max_output_tokens=50)
        result = runtime.generate(_request(text="x" * 5000))
        self.assertEqual(result.status, STATUS_RESOURCE_LIMIT)
        self.assertEqual(result.error_code, ERROR_CONTEXT_LENGTH_EXCEEDED)
        self.assertEqual(runtime.load_calls, 0)
        self.assertEqual(runtime.infer_calls, [])
        self.assertIn("prompt_tokens_estimate", result.details)

    def test_conversation_history_counts_toward_context(self):
        runtime, _ = self.ready_runtime(context_length=100, max_output_tokens=50)
        history = [{"role": "user", "content": "y" * 400}]
        self.assertEqual(runtime.generate(_request(conversation=history)).error_code,
                         ERROR_CONTEXT_LENGTH_EXCEEDED)

    def test_prompt_that_fits_runs(self):
        runtime, _ = self.ready_runtime(context_length=512, max_output_tokens=64)
        self.assertTrue(runtime.generate(_request(text="short")).ok)

    def test_requested_output_tokens_above_configured_maximum(self):
        runtime, _ = self.ready_runtime(max_output_tokens=64)
        result = runtime.generate(_request(parameters=GenerationParameters(max_output_tokens=65)))
        self.assertEqual(result.status, STATUS_RESOURCE_LIMIT)
        self.assertEqual(result.error_code, ERROR_MAX_OUTPUT_TOKENS_EXCEEDED)
        self.assertEqual(runtime.infer_calls, [])

    def test_requested_timeout_above_configured_limit(self):
        runtime, _ = self.ready_runtime(timeout_seconds=10.0)
        result = runtime.generate(_request(timeout_seconds=11))
        self.assertEqual(result.status, STATUS_RESOURCE_LIMIT)
        self.assertEqual(result.error_code, ERROR_TIMEOUT_EXCEEDS_LIMIT)

    def test_lower_request_timeout_is_allowed_and_applied(self):
        runtime, clock = self.ready_runtime(timeout_seconds=10.0)
        runtime.advance_clock_by = 3.0
        runtime.poll_control = True
        result = runtime.generate(_request(timeout_seconds=2))
        self.assertEqual(result.status, STATUS_TIMEOUT)

    def test_cooperative_timeout_interrupts_the_runtime(self):
        runtime, _ = self.ready_runtime(timeout_seconds=5.0)
        runtime.advance_clock_by = 6.0
        runtime.poll_control = True
        result = runtime.generate(_request())
        self.assertEqual(result.status, STATUS_TIMEOUT)
        self.assertEqual(result.error_code, ERROR_TIMED_OUT)
        self.assertIsNone(result.text)

    def test_runtime_that_ignores_the_deadline_is_still_reported_as_timeout(self):
        runtime, _ = self.ready_runtime(timeout_seconds=5.0)
        runtime.advance_clock_by = 6.0          # never polls control.check()
        result = runtime.generate(_request())
        self.assertEqual(result.status, STATUS_TIMEOUT)
        self.assertEqual(result.error_code, ERROR_COMPLETED_AFTER_DEADLINE)
        self.assertIsNone(result.text)          # late output is discarded

    def test_finishing_exactly_within_the_limit_succeeds(self):
        runtime, _ = self.ready_runtime(timeout_seconds=5.0)
        runtime.advance_clock_by = 5.0
        self.assertTrue(runtime.generate(_request()).ok)

    def test_load_time_does_not_count_against_the_inference_timeout(self):
        runtime, clock = self.ready_runtime(timeout_seconds=5.0)
        original_load = runtime._load_model
        runtime._load_model = lambda config: (clock.advance(100), original_load(config))
        self.assertTrue(runtime.generate(_request()).ok)

    def test_cancelled_before_start_never_loads_or_runs(self):
        runtime, _ = self.ready_runtime()
        token = CancellationToken()
        token.cancel()
        result = runtime.generate(_request(), cancellation_token=token)
        self.assertEqual(result.status, STATUS_CANCELLED)
        self.assertEqual(result.error_code, ERROR_CANCELLED)
        self.assertEqual((runtime.load_calls, runtime.infer_calls), (0, []))

    def test_cancelled_during_inference_interrupts_a_polling_runtime(self):
        runtime, _ = self.ready_runtime()
        token = CancellationToken()
        runtime.cancel_token_during_run = token
        runtime.poll_control = True
        result = runtime.generate(_request(), cancellation_token=token)
        self.assertEqual(result.status, STATUS_CANCELLED)
        self.assertIsNone(result.text)

    def test_cancellation_that_a_runtime_ignores_still_discards_output(self):
        runtime, _ = self.ready_runtime()
        token = CancellationToken()
        runtime.cancel_token_during_run = token   # runtime does not poll
        result = runtime.generate(_request(), cancellation_token=token)
        self.assertEqual(result.status, STATUS_CANCELLED)
        self.assertIsNone(result.text)

    def test_uncancelled_token_does_not_interfere(self):
        runtime, _ = self.ready_runtime()
        self.assertTrue(runtime.generate(_request(), cancellation_token=CancellationToken()).ok)

    def test_engine_out_of_memory_during_inference(self):
        runtime, _ = self.ready_runtime()
        runtime.infer_side_effect = MemoryError()
        result = runtime.generate(_request())
        self.assertEqual(result.status, STATUS_RESOURCE_LIMIT)
        self.assertEqual(result.error_code, ERROR_OUT_OF_MEMORY)

    def test_engine_signalled_resource_limit(self):
        runtime, _ = self.ready_runtime()
        runtime.infer_side_effect = ResourceLimitExceeded("too much", "custom_limit")
        result = runtime.generate(_request())
        self.assertEqual((result.status, result.error_code), (STATUS_RESOURCE_LIMIT, "custom_limit"))

    def test_runtime_reporting_more_output_tokens_than_allowed(self):
        runtime, _ = self.ready_runtime(max_output_tokens=10)
        runtime.scripted_output = RuntimeOutput("text", output_tokens=11)
        result = runtime.generate(_request())
        self.assertEqual(result.status, STATUS_RESOURCE_LIMIT)
        self.assertEqual(result.error_code, ERROR_OUTPUT_EXCEEDS_LIMIT)


# ======================================================================
class TestLocalLanguageModelBackendIntegration(_TempFilesMixin, unittest.TestCase):
    """10. LocalLanguageModelBackend integration"""

    def _understanding(self, text="What is Python?"):
        return DeterministicFallbackBackend(UnderstandingEngine()).understand(text)

    def test_backend_declares_local_model_kind(self):
        self.assertEqual(LocalLanguageModelBackend().backend_kind, BACKEND_KIND_LOCAL_MODEL)

    def test_default_backend_uses_the_unavailable_runtime(self):
        backend = LocalLanguageModelBackend()
        self.assertIsInstance(backend.runtime, UnavailableLocalModelRuntime)

    def test_no_model_configured_is_explicit(self):
        lic = LanguageIntelligenceCore(backend=LocalLanguageModelBackend())
        response = lic.generate_response(self._understanding())
        self.assertIsInstance(response, ResponseGenerationResult)
        self.assertEqual(response.status, STATUS_MODEL_NOT_CONFIGURED)
        self.assertIsNone(response.response_text)
        self.assertEqual(response.error_code, ERROR_NO_CONFIGURATION)
        self.assertEqual(response.inference_status, INF_NOT_CONFIGURED)
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertTrue(response.reason)

    def test_configured_but_no_engine_is_explicit_unavailable(self):
        backend = LocalLanguageModelBackend(UnavailableLocalModelRuntime(_config()))
        response = LanguageIntelligenceCore(backend=backend).generate_response(
            self._understanding())
        self.assertEqual(response.status, STATUS_MODEL_UNAVAILABLE)
        self.assertEqual(response.error_code, ERROR_RUNTIME_DEPENDENCY_MISSING)
        self.assertIsNone(response.response_text)

    def test_full_flow_core_backend_runtime_with_test_double(self):
        runtime, _ = self.ready_runtime()
        runtime.scripted_output = RuntimeOutput("double says hi", "stop")
        lic = LanguageIntelligenceCore(backend=LocalLanguageModelBackend(runtime))
        response = lic.generate_response(self._understanding("What is Python?"))
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(response.response_text, "double says hi")
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(response.inference_status, STATUS_SUCCESS)
        self.assertEqual(len(runtime.infer_calls), 1)
        self.assertEqual(runtime.infer_calls[0][0].user_input, "What is Python?")

    def test_system_prompt_and_context_turns_reach_the_runtime(self):
        runtime, _ = self.ready_runtime()
        context = ConversationContext()
        context.add_turn("first question", "first answer")
        context.add_turn("second question", "second answer")
        backend = LocalLanguageModelBackend(runtime, system_prompt="Be concise.",
                                            max_context_turns=1)
        backend.generate_response(self._understanding("third"), context=context)
        request = runtime.infer_calls[0][0]
        self.assertEqual(request.system_prompt, "Be concise.")
        self.assertEqual([(m.role, m.content) for m in request.conversation],
                         [("user", "second question"), ("assistant", "second answer")])

    def test_context_is_only_read_never_written(self):
        runtime, _ = self.ready_runtime()
        context = ConversationContext()
        context.add_turn("q", "a")
        LocalLanguageModelBackend(runtime).generate_response(self._understanding(),
                                                             context=context)
        self.assertEqual(context.get_recent_turns(), [{"user": "q", "assistant": "a"}])

    def test_zero_context_turns_and_no_context(self):
        runtime, _ = self.ready_runtime()
        context = ConversationContext()
        context.add_turn("q", "a")
        LocalLanguageModelBackend(runtime, max_context_turns=0).generate_response(
            self._understanding(), context=context)
        LocalLanguageModelBackend(runtime).generate_response(self._understanding())
        self.assertEqual([r[0].conversation for r in runtime.infer_calls], [[], []])

    def test_generation_parameters_are_forwarded(self):
        runtime, _ = self.ready_runtime()
        backend = LocalLanguageModelBackend(
            runtime, generation_parameters=GenerationParameters(temperature=0.1))
        backend.generate_response(self._understanding())
        self.assertEqual(runtime.infer_calls[0][1].temperature, 0.1)

    def test_runtime_failures_map_to_explicit_statuses(self):
        cases = [
            (ModelLoadError("x"), None, STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED),
            (None, InferenceExecutionError("x"), STATUS_MODEL_FAILED, STATUS_INFERENCE_FAILED),
            (None, MemoryError(), STATUS_MODEL_FAILED, STATUS_RESOURCE_LIMIT),
        ]
        for load_error, infer_error, response_status, inference_status in cases:
            with self.subTest(inference_status=inference_status):
                runtime, _ = self.ready_runtime()
                runtime.load_side_effect = load_error
                runtime.infer_side_effect = infer_error
                response = LocalLanguageModelBackend(runtime).generate_response(
                    self._understanding())
                self.assertEqual(response.status, response_status)
                self.assertEqual(response.inference_status, inference_status)
                self.assertIsNone(response.response_text)

    def test_timeout_and_cancel_map_to_model_failed(self):
        runtime, _ = self.ready_runtime(timeout_seconds=1.0)
        runtime.advance_clock_by = 2.0
        response = LocalLanguageModelBackend(runtime).generate_response(self._understanding())
        self.assertEqual((response.status, response.inference_status),
                         (STATUS_MODEL_FAILED, STATUS_TIMEOUT))

    def test_bad_understanding_is_reported_not_raised(self):
        runtime, _ = self.ready_runtime()
        response = LocalLanguageModelBackend(runtime).generate_response(None)
        self.assertEqual((response.status, response.inference_status),
                         (STATUS_MODEL_FAILED, STATUS_INVALID_REQUEST))
        self.assertEqual(runtime.infer_calls, [])

    def test_understand_is_explicit_when_model_not_usable(self):
        with self.assertRaises(LocalModelBackendError) as ctx:
            LocalLanguageModelBackend().understand("hello")
        self.assertEqual(ctx.exception.status, STATUS_MODEL_NOT_CONFIGURED)
        self.assertEqual(ctx.exception.error_code, ERROR_NO_CONFIGURATION)

        with self.assertRaises(LocalModelBackendError) as ctx:
            LocalLanguageModelBackend(UnavailableLocalModelRuntime(_config())).understand("hello")
        self.assertEqual(ctx.exception.status, STATUS_MODEL_UNAVAILABLE)

    def test_understand_never_fabricates_a_result_even_with_a_usable_model(self):
        runtime, _ = self.ready_runtime()
        with self.assertRaises(NotImplementedError):
            LocalLanguageModelBackend(runtime).understand("hello")
        self.assertEqual(runtime.infer_calls, [])       # and never invoked the model

    def test_understand_does_not_trigger_loading(self):
        runtime, _ = self.ready_runtime()
        with self.assertRaises(NotImplementedError):
            LocalLanguageModelBackend(runtime).understand("hello")
        self.assertEqual(runtime.load_calls, 0)


class TestDeterministicFallbackRemainsSeparate(_TempFilesMixin, unittest.TestCase):
    """11. deterministic fallback remains separate"""

    def test_deterministic_backend_still_defers_and_is_labeled_as_such(self):
        backend = DeterministicFallbackBackend(UnderstandingEngine())
        response = LanguageIntelligenceCore(backend=backend).generate_response(
            backend.understand("Hello."))
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertEqual(response.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertIsNone(response.inference_status)

    def test_local_backend_never_answers_with_deferred_or_deterministic_output(self):
        understanding = DeterministicFallbackBackend(UnderstandingEngine()).understand("Hello.")
        for backend in (LocalLanguageModelBackend(),
                        LocalLanguageModelBackend(UnavailableLocalModelRuntime(_config()))):
            response = backend.generate_response(understanding)
            self.assertNotEqual(response.status, STATUS_DEFERRED)
            self.assertNotEqual(response.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
            self.assertIsNone(response.response_text)

    def test_local_backend_module_does_not_reference_the_deterministic_backend(self):
        path = os.path.join(os.path.dirname(language_intelligence.__file__),
                            "local_model_backend.py")
        code = _strip_docstrings_and_comments(_read(path))
        self.assertNotIn("deterministic_fallback_backend", code)
        self.assertNotIn("DeterministicFallbackBackend", code)

    def test_the_same_core_can_be_built_with_either_backend(self):
        understanding = DeterministicFallbackBackend(UnderstandingEngine()).understand("Hi.")
        runtime, _ = self.ready_runtime()
        deterministic = LanguageIntelligenceCore(
            backend=DeterministicFallbackBackend(UnderstandingEngine()))
        local = LanguageIntelligenceCore(backend=LocalLanguageModelBackend(runtime))
        self.assertEqual(deterministic.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(local.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(deterministic.generate_response(understanding).status, STATUS_DEFERRED)
        self.assertEqual(local.generate_response(understanding).status, STATUS_GENERATED)


class TestPrompt397Compatibility(unittest.TestCase):
    """12. existing Prompt 397 behavior remains compatible"""

    def test_real_core_still_uses_the_deterministic_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Core(memory_db_path=os.path.join(tmp, "test_memory.sqlite3"),
                        skill_definitions_dir=os.path.join(tmp, "skills"))
            self.assertEqual(core.language_intelligence.backend_kind,
                             BACKEND_KIND_DETERMINISTIC_FALLBACK)
            self.assertNotIsInstance(core.language_intelligence.backend,
                                     LocalLanguageModelBackend)
            understanding = core.understand_language("What is Python?")
            response = core.generate_language_response(understanding)
            self.assertEqual(response.status, STATUS_DEFERRED)

    def test_response_result_old_constructor_and_statuses_still_work(self):
        result = ResponseGenerationResult(STATUS_DEFERRED, None, "why", "deterministic_fallback")
        self.assertEqual(result.reason, "why")
        as_dict = result.to_dict()
        for key in ("status", "response_text", "reason", "backend_kind"):
            self.assertIn(key, as_dict)
        for status in (STATUS_DEFERRED, STATUS_GENERATED, STATUS_NOT_IMPLEMENTED,
                       STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE,
                       STATUS_MODEL_FAILED):
            self.assertIn(status, ALL_STATUSES)

    def test_backend_kinds_unchanged(self):
        self.assertEqual(BACKEND_KIND_DETERMINISTIC_FALLBACK, "deterministic_fallback")
        self.assertEqual(BACKEND_KIND_LOCAL_MODEL, "local_model")


class TestNoCloudAiOrNetwork(unittest.TestCase):
    """The runtime foundation is on-device only: no network/cloud imports,
    no API keys, no SDKs."""

    MODULES = ("local_model_config.py", "inference.py", "local_model_runtime.py",
               "unavailable_runtime.py", "local_model_backend.py")
    FORBIDDEN_IMPORTS = {
        "requests", "urllib", "urllib3", "http", "httpx", "socket", "ssl", "aiohttp",
        "openai", "anthropic", "google", "boto3", "ftplib", "smtplib", "websocket",
    }

    def test_no_forbidden_imports_and_no_api_keys(self):
        base = os.path.dirname(language_intelligence.__file__)
        for name in self.MODULES:
            with self.subTest(module=name):
                source = _read(os.path.join(base, name))
                imported = set()
                for match in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][\w]*)", source, re.M):
                    imported.add(match.group(1))
                self.assertEqual(imported & self.FORBIDDEN_IMPORTS, set())
                code = _strip_docstrings_and_comments(source).lower()
                self.assertNotIn("api_key", code)
                self.assertNotIn("apikey", code)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _strip_docstrings_and_comments(source):
    source = re.sub(r'"""[\s\S]*?"""', "", source)
    return re.sub(r"#.*", "", source)


if __name__ == "__main__":
    unittest.main()
