"""
Tests for Prompt 406 - Local model failure & fallback handling.

Exercises the whole existing flow

    Core.process_input -> LanguageIntelligenceCore (now with an optional
    fallback backend) -> LocalLanguageModelBackend -> provider -> runtime

with deterministic test doubles at the runtime boundary (nothing here is a
language model, no model file is read, nothing is downloaded), and checks
that every local-model failure is a structured result, that the existing
deterministic pipeline then answers, that nothing is retried, and that the
successful model path is unchanged.

Run directly:
    python -m unittest tests.test_local_model_failure_fallback -v
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from language_intelligence.backend import (
    LanguageIntelligenceBackend, BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK,
)
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.local_model_backend import LocalLanguageModelBackend, LocalModelBackendError
from language_intelligence.local_model_config import LocalModelConfig
from language_intelligence.local_model_runtime import (
    LocalModelRuntime, RuntimeOutput, ModelLoadError, InferenceExecutionError,
    InferenceCancelled, ResourceLimitExceeded,
)
from language_intelligence.inference import (
    GenerationParameters, STATUS_SUCCESS, STATUS_MODEL_NOT_CONFIGURED as INF_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE as INF_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED as INF_LOAD_FAILED,
    STATUS_INFERENCE_FAILED as INF_INFERENCE_FAILED, STATUS_INVALID_REQUEST as INF_INVALID,
    STATUS_RESOURCE_LIMIT as INF_RESOURCE, STATUS_TIMEOUT as INF_TIMEOUT,
    STATUS_CANCELLED as INF_CANCELLED,
    ERROR_NO_CONFIGURATION, ERROR_RUNTIME_DEPENDENCY_MISSING, ERROR_LOAD_FAILED,
    ERROR_INFERENCE_FAILED, ERROR_TIMED_OUT, ERROR_CANCELLED, ERROR_INVALID_REQUEST,
    ERROR_OUT_OF_MEMORY, ERROR_MODEL_EXCEEDS_MEMORY_LIMIT,
)
from language_intelligence.response_generation import (
    ResponseGenerationResult, STATUS_GENERATED, STATUS_DEFERRED, STATUS_MODEL_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_FAILED, MODEL_FAILURE_STATUSES,
)

MESSAGE = "qwerty zzznoxyzzz unmapped concept"
MODEL_TEXT = "text that only the model double can produce"


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ScriptedRuntime(LocalModelRuntime):
    """TEST DOUBLE at the runtime engine boundary. Counts every load and
    every inference and does exactly what a test scripts."""

    def __init__(self, config=None, clock=None):
        super().__init__(config=config, clock=clock or FakeClock())
        self.dependency_available = True
        self.load_calls = 0
        self.requests = []
        self.load_error = None
        self.infer_error = None
        self.advance_clock_by = 0.0
        self.output = RuntimeOutput(MODEL_TEXT, "stop", prompt_tokens=7, output_tokens=5)

    @property
    def runtime_name(self):
        return "scripted-runtime"

    def dependency_status(self):
        return (True, "") if self.dependency_available else (False, "scripted engine missing")

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


class RaisingBackend(LanguageIntelligenceBackend):
    """Breaks the backend contract: generate_response() raises / returns junk."""

    def __init__(self, value=None):
        self.calls = 0
        self.value = value

    @property
    def backend_kind(self):
        return BACKEND_KIND_LOCAL_MODEL

    def understand(self, *args, **kwargs):
        raise RuntimeError("secret internal detail /data/model.bin")

    def generate_response(self, understanding, context=None):
        self.calls += 1
        if self.value is not None:
            return self.value
        raise RuntimeError("secret internal detail /data/model.bin")


class FlowCase(unittest.TestCase):
    """A real Core whose LanguageIntelligenceCore is (local backend,
    deterministic fallback); plus a control Core that never has a model."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.core = self._core("main")
        self.control = self._core("control")
        handle = tempfile.NamedTemporaryFile(suffix=".gguf", delete=False, dir=self._tmp.name)
        handle.write(b"\0" * 16)
        handle.close()
        self.model_path = handle.name

    def tearDown(self):
        self._tmp.cleanup()

    def _core(self, name):
        return Core(memory_db_path=os.path.join(self._tmp.name, f"{name}.sqlite3"),
                    skill_definitions_dir=os.path.join(self._tmp.name, f"{name}_skills"))

    def config(self, **overrides):
        values = dict(model_id="test-model", model_path=self.model_path, context_length=512,
                      max_output_tokens=64, timeout_seconds=10.0)
        values.update(overrides)
        return LocalModelConfig(**values)

    def runtime(self, **config_overrides):
        return ScriptedRuntime(self.config(**config_overrides))

    def install(self, runtime=None, **backend_kwargs):
        backend = LocalLanguageModelBackend(runtime=runtime, **backend_kwargs)
        self.core.language_intelligence = LanguageIntelligenceCore(
            backend, fallback_backend=DeterministicFallbackBackend(self.core.understanding))
        return backend

    def expected_fallback_reply(self, message=MESSAGE):
        return self.control.process_input(message)

    def assert_structured_failure(self, status, inference_status, error_code=None):
        response = self.core.get_last_language_response()
        self.assertIsInstance(response, ResponseGenerationResult)
        self.assertEqual(response.status, status)
        self.assertEqual(response.inference_status, inference_status)
        if error_code is not None:
            self.assertEqual(response.error_code, error_code)
        self.assertIsNone(response.response_text)
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        return response

    def assert_deterministic_reply(self, reply, message=MESSAGE):
        self.assertEqual(reply, self.expected_fallback_reply(message))
        self.assertNotIn(MODEL_TEXT, reply)


class TestNoModelConfigured(FlowCase):
    """1. no model configured"""

    def test_default_backend_reports_not_configured_and_fallback_answers(self):
        self.install(runtime=None)  # no runtime => explicit "not configured"
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_NOT_CONFIGURED, INF_NOT_CONFIGURED)
        self.assert_deterministic_reply(reply)

    def test_unconfigured_runtime_is_recognised_without_loading_or_inferring(self):
        runtime = ScriptedRuntime(config=None)
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_NOT_CONFIGURED, INF_NOT_CONFIGURED,
                                       ERROR_NO_CONFIGURATION)
        self.assertEqual((runtime.load_calls, runtime.requests), (0, []))
        self.assert_deterministic_reply(reply)

    def test_understanding_fallback_is_identifiable_and_says_why(self):
        self.install(runtime=None)
        self.core.process_input(MESSAGE)
        self.assertEqual(self.core.language_intelligence.last_understanding_fallback,
                         f"LocalModelBackendError:{ERROR_NO_CONFIGURATION}")
        self.assertEqual(self.core.get_last_language_understanding().source_backend,
                         BACKEND_KIND_DETERMINISTIC_FALLBACK)


class TestModelUnavailable(FlowCase):
    """2. model unavailable"""

    def test_missing_engine_is_unavailable_not_loaded_not_run(self):
        runtime = self.runtime()
        runtime.dependency_available = False
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_UNAVAILABLE, INF_UNAVAILABLE,
                                       ERROR_RUNTIME_DEPENDENCY_MISSING)
        self.assertEqual((runtime.load_calls, runtime.requests), (0, []))
        self.assert_deterministic_reply(reply)

    def test_shipped_unavailable_runtime_is_unavailable(self):
        from language_intelligence.unavailable_runtime import UnavailableLocalModelRuntime
        self.install(UnavailableLocalModelRuntime(self.config()))
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_UNAVAILABLE, INF_UNAVAILABLE)
        self.assert_deterministic_reply(reply)


class TestModelLoadFailure(FlowCase):
    """3. model load failure"""

    def test_load_failure_is_reported_as_load_failed_and_fallback_answers(self):
        runtime = self.runtime()
        runtime.load_error = ModelLoadError("corrupt weights")
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_UNAVAILABLE, INF_LOAD_FAILED, ERROR_LOAD_FAILED)
        self.assertEqual(runtime.requests, [])
        self.assert_deterministic_reply(reply)

    def test_failed_load_is_not_retried_and_the_failure_is_not_hidden(self):
        runtime = self.runtime()
        runtime.load_error = ModelLoadError("corrupt weights")
        self.install(runtime)
        self.core.process_input(MESSAGE)
        self.core.process_input(MESSAGE + " again")
        self.assertEqual(runtime.load_calls, 1)
        self.assert_structured_failure(STATUS_MODEL_UNAVAILABLE, INF_LOAD_FAILED)  # still reported

    def test_missing_model_file_is_not_loaded(self):
        runtime = ScriptedRuntime(self.config(model_path=os.path.join(self._tmp.name, "gone.gguf")))
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_UNAVAILABLE, INF_LOAD_FAILED)
        self.assertEqual(runtime.load_calls, 0)
        self.assert_deterministic_reply(reply)


class TestInferenceFailure(FlowCase):
    """4. inference failure"""

    def test_engine_error_is_an_inference_failure_and_fallback_answers(self):
        runtime = self.runtime()
        runtime.infer_error = InferenceExecutionError("engine crashed")
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_FAILED, INF_INFERENCE_FAILED, ERROR_INFERENCE_FAILED)
        self.assert_deterministic_reply(reply)

    def test_unexpected_exception_in_the_engine_does_not_crash_the_conversation(self):
        runtime = self.runtime()
        runtime.infer_error = ValueError("boom")
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_FAILED, INF_INFERENCE_FAILED)
        self.assert_deterministic_reply(reply)

    def test_empty_model_output_is_a_failure_never_an_empty_reply(self):
        runtime = self.runtime()
        runtime.output = RuntimeOutput("   ", "stop")
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_FAILED, INF_INFERENCE_FAILED)
        self.assert_deterministic_reply(reply)

    def test_a_backend_that_raises_is_reported_by_type_only(self):
        backend = RaisingBackend()
        self.core.language_intelligence = LanguageIntelligenceCore(
            backend, fallback_backend=DeterministicFallbackBackend(self.core.understanding))
        reply = self.core.process_input(MESSAGE)
        response = self.assert_structured_failure(STATUS_MODEL_FAILED, INF_INFERENCE_FAILED,
                                                  ERROR_INFERENCE_FAILED)
        self.assertIn("RuntimeError", response.reason)
        self.assertNotIn("secret", response.reason)
        self.assertEqual(backend.calls, 1)
        self.assert_deterministic_reply(reply)

    def test_a_backend_returning_the_wrong_type_is_a_failure(self):
        self.core.language_intelligence = LanguageIntelligenceCore(
            RaisingBackend(value="just a string"),
            fallback_backend=DeterministicFallbackBackend(self.core.understanding))
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_FAILED, INF_INFERENCE_FAILED)
        self.assert_deterministic_reply(reply)


class TestTimeout(FlowCase):
    """5. timeout"""

    def test_timeout_is_reported_as_timeout_and_fallback_answers(self):
        runtime = self.runtime(timeout_seconds=1.0)
        runtime.advance_clock_by = 2.0
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_FAILED, INF_TIMEOUT, ERROR_TIMED_OUT)
        self.assertEqual(len(runtime.requests), 1)  # one attempt, not repeated
        self.assert_deterministic_reply(reply)


class TestCancellation(FlowCase):
    """6. cancellation"""

    def test_cancellation_is_reported_as_cancelled_not_as_a_failure_of_the_model(self):
        runtime = self.runtime()
        runtime.infer_error = InferenceCancelled("caller cancelled")
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_FAILED, INF_CANCELLED, ERROR_CANCELLED)
        self.assertEqual(len(runtime.requests), 1)
        self.assert_deterministic_reply(reply)

    def test_cancellation_is_not_retried(self):
        runtime = self.runtime()
        runtime.infer_error = InferenceCancelled("caller cancelled")
        self.install(runtime)
        self.core.process_input(MESSAGE)
        self.assertEqual(len(runtime.requests), 1)


class TestResourceLimit(FlowCase):
    """7. resource / memory limit failure"""

    def test_engine_resource_limit_is_structured_and_limits_are_not_raised(self):
        config = self.config()
        runtime = ScriptedRuntime(config)
        runtime.infer_error = ResourceLimitExceeded("kv cache too large")
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_FAILED, INF_RESOURCE)
        self.assertEqual((config.context_length, config.max_output_tokens, config.timeout_seconds),
                         (512, 64, 10.0))
        self.assertEqual(len(runtime.requests), 1)
        self.assert_deterministic_reply(reply)

    def test_out_of_memory_does_not_crash(self):
        runtime = self.runtime()
        runtime.infer_error = MemoryError()
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_FAILED, INF_RESOURCE, ERROR_OUT_OF_MEMORY)
        self.assert_deterministic_reply(reply)

    def test_model_larger_than_the_memory_budget_is_refused_before_loading(self):
        with open(self.model_path, "wb") as handle:
            handle.write(b"\0" * (2 * 1024 * 1024))
        config = self.config(max_memory_mb=1)
        runtime = ScriptedRuntime(config)
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        response = self.core.get_last_language_response()
        self.assertEqual(response.error_code, ERROR_MODEL_EXCEEDS_MEMORY_LIMIT)
        self.assertIn(response.inference_status, (INF_RESOURCE, INF_LOAD_FAILED))
        self.assertEqual(runtime.load_calls, 0)
        self.assertEqual(config.max_memory_mb, 1)  # never silently raised
        self.assertIsNone(response.response_text)
        self.assert_deterministic_reply(reply)

    def test_prompt_longer_than_the_context_is_refused_before_loading(self):
        runtime = self.runtime(context_length=70, max_output_tokens=64)
        self.install(runtime)
        long_message = ("word " * 200).strip()
        reply = self.core.process_input(long_message)
        self.assert_structured_failure(STATUS_MODEL_FAILED, INF_RESOURCE)
        self.assertEqual((runtime.load_calls, runtime.requests), (0, []))
        self.assertEqual(self.core.get_last_language_understanding().original_input, long_message)
        self.assertNotIn(MODEL_TEXT, reply)


class TestInvalidRequest(FlowCase):
    """the invalid-request state (one of the eight)"""

    def test_invalid_request_is_reported_and_never_reaches_the_engine(self):
        runtime = self.runtime()
        self.install(runtime, generation_parameters=GenerationParameters(temperature=9.0))
        reply = self.core.process_input(MESSAGE)
        self.assert_structured_failure(STATUS_MODEL_FAILED, INF_INVALID, ERROR_INVALID_REQUEST)
        self.assertEqual((runtime.load_calls, runtime.requests), (0, []))
        self.assert_deterministic_reply(reply)


class TestFallbackBehaviour(FlowCase):
    """8. appropriate fallback behaviour"""

    def test_every_failure_status_is_marked_and_none_carries_text(self):
        for status in MODEL_FAILURE_STATUSES:
            primary = RaisingBackend(value=ResponseGenerationResult(
                status, response_text=None, reason="scripted", backend_kind=BACKEND_KIND_LOCAL_MODEL))
            li = LanguageIntelligenceCore(
                primary, fallback_backend=DeterministicFallbackBackend(self.core.understanding))
            response = li.generate_response(None)
            self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
            self.assertIsNone(response.response_text)
            self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)  # who failed

    def test_non_failures_are_left_untouched(self):
        for status, text in ((STATUS_GENERATED, "hello"), (STATUS_DEFERRED, None)):
            primary = RaisingBackend(value=ResponseGenerationResult(
                status, response_text=text, backend_kind=BACKEND_KIND_LOCAL_MODEL))
            li = LanguageIntelligenceCore(
                primary, fallback_backend=DeterministicFallbackBackend(self.core.understanding))
            response = li.generate_response(None)
            self.assertIsNone(response.fallback_backend_kind)
            self.assertEqual(response.response_text, text)

    def test_usable_model_still_gets_understanding_from_the_fallback_backend(self):
        # A usable model cannot produce a LanguageUnderstandingResult yet
        # (NotImplementedError by design); the deterministic backend does,
        # and the model still generates the reply.
        self.install(self.runtime())
        self.core.process_input(MESSAGE)
        self.assertEqual(self.core.language_intelligence.last_understanding_fallback,
                         "NotImplementedError")
        self.assertEqual(self.core.get_last_language_understanding().source_backend,
                         BACKEND_KIND_DETERMINISTIC_FALLBACK)

    def test_fallback_reply_is_the_deterministic_pipelines_own_reply(self):
        self.core.process_input("TEACH Python IS Programming Language")
        self.control.process_input("TEACH Python IS Programming Language")
        self.install(self.runtime())
        self.core.language_intelligence.backend = LocalLanguageModelBackend()  # not configured
        self.assertEqual(self.core.process_input("What is Python?"),
                         self.control.process_input("What is Python?"))

    def test_without_a_fallback_backend_nothing_changes(self):
        backend = LocalLanguageModelBackend()
        li = LanguageIntelligenceCore(backend)
        self.assertIsNone(li.fallback_backend)
        with self.assertRaises(LocalModelBackendError):
            li.understand(MESSAGE)
        response = li.generate_response(
            DeterministicFallbackBackend(self.core.understanding).understand(MESSAGE))
        self.assertEqual(response.status, STATUS_MODEL_NOT_CONFIGURED)
        self.assertIsNone(response.fallback_backend_kind)
        with self.assertRaises(RuntimeError):
            LanguageIntelligenceCore(RaisingBackend()).generate_response(None)

    def test_fallback_backend_is_validated(self):
        backend = DeterministicFallbackBackend(self.core.understanding)
        with self.assertRaises(TypeError):
            LanguageIntelligenceCore(backend, fallback_backend=object())
        with self.assertRaises(ValueError):
            LanguageIntelligenceCore(backend, fallback_backend=backend)

    def test_result_serialises_the_fallback_marker(self):
        self.install(runtime=None)
        self.core.process_input(MESSAGE)
        self.assertEqual(self.core.get_last_language_response().to_dict()["fallback_backend_kind"],
                         BACKEND_KIND_DETERMINISTIC_FALLBACK)


class TestNoDuplicateRequestAndNoRetryLoop(FlowCase):
    """9. no duplicate model request"""

    def test_one_message_makes_at_most_one_model_request(self):
        for error in (InferenceExecutionError("x"), InferenceCancelled("x"),
                      ResourceLimitExceeded("x"), MemoryError(), ValueError("x")):
            with self.subTest(error=type(error).__name__):
                runtime = self.runtime()
                runtime.infer_error = error
                self.install(runtime)
                self.core.process_input(MESSAGE)
                self.assertEqual(len(runtime.requests), 1)

    def test_n_messages_make_n_requests_and_each_failure_is_reported(self):
        runtime = self.runtime()
        runtime.infer_error = InferenceExecutionError("x")
        self.install(runtime)
        for i in range(3):
            self.core.process_input(f"{MESSAGE} {i}")
            self.assert_structured_failure(STATUS_MODEL_FAILED, INF_INFERENCE_FAILED)
        self.assertEqual(len(runtime.requests), 3)

    def test_understanding_and_availability_checks_never_call_the_model(self):
        runtime = self.runtime()
        backend = self.install(runtime)
        self.core.understand_language(MESSAGE)
        backend.check_availability()
        self.assertEqual((runtime.load_calls, runtime.requests), (0, []))

    def test_a_failure_does_not_poison_the_next_request(self):
        runtime = self.runtime()
        self.install(runtime)
        runtime.infer_error = InferenceExecutionError("once")
        self.core.process_input(MESSAGE)
        runtime.infer_error = None
        reply = self.core.process_input("second message")
        self.assertEqual(reply, MODEL_TEXT)
        self.assertEqual(len(runtime.requests), 2)


class TestOriginalMessageAndContextPreserved(FlowCase):
    """10. original user message (and context) remain unchanged"""

    ODD = "Robots need BOSS-fights, right??"

    def test_original_message_reaches_understanding_and_the_model_verbatim(self):
        runtime = self.runtime()
        self.install(runtime)
        self.core.process_input(self.ODD)
        self.assertEqual(self.core.get_last_language_understanding().original_input, self.ODD)
        self.assertEqual(runtime.requests[0].user_input, self.ODD)

    def test_original_message_is_intact_after_a_failure(self):
        runtime = self.runtime()
        runtime.infer_error = InferenceExecutionError("x")
        self.install(runtime)
        self.core.process_input(self.ODD)
        self.assertEqual(self.core.get_last_language_understanding().original_input, self.ODD)
        self.assertEqual(self.core.get_recent_turns()[-1]["user"], self.ODD)

    def test_context_is_preserved_and_stored_exactly_once(self):
        self.core.process_input("I am building a robot game about a boss.")
        turns_before = list(self.core.get_recent_turns())
        state_before = self.core.conversation_state.to_dict()
        runtime = self.runtime()
        runtime.infer_error = InferenceExecutionError("x")
        self.install(runtime)
        self.core.process_input("What about the boss?")
        turns = self.core.get_recent_turns()
        self.assertEqual(turns[:len(turns_before)], turns_before)
        self.assertEqual(len(turns), len(turns_before) + 1)
        self.assertEqual(state_before["topic"]["topic"],
                         self.core.conversation_state.to_dict()["topic"]["topic"])

    def test_previous_turns_still_reach_the_model_request(self):
        self.core.process_input("I am building a robot game about a boss.")
        runtime = self.runtime()
        self.install(runtime, max_context_turns=4)
        self.core.process_input("What about the boss?")
        sent = " ".join(m.content for m in runtime.requests[0].conversation)
        self.assertIn("robot game", sent)


class TestSuccessfulModelPathUnchanged(FlowCase):
    """11. the existing successful local-model path remains unchanged"""

    def test_model_reply_is_returned_and_is_marked_as_the_models(self):
        runtime = self.runtime()
        self.install(runtime)
        reply = self.core.process_input(MESSAGE)
        self.assertEqual(reply, MODEL_TEXT)
        response = self.core.get_last_language_response()
        self.assertEqual((response.status, response.inference_status, response.backend_kind),
                         (STATUS_GENERATED, STATUS_SUCCESS, BACKEND_KIND_LOCAL_MODEL))
        self.assertEqual(response.response_text, MODEL_TEXT)
        self.assertIsNone(response.error_code)
        self.assertIsNone(response.fallback_backend_kind)
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(runtime.load_calls, 1)

    def test_fallback_backend_does_not_change_a_successful_result(self):
        with_fallback, without = self.runtime(), self.runtime()
        understanding = DeterministicFallbackBackend(self.core.understanding).understand(MESSAGE)
        a = LanguageIntelligenceCore(
            LocalLanguageModelBackend(with_fallback),
            fallback_backend=DeterministicFallbackBackend(self.core.understanding)
        ).generate_response(understanding)
        b = LanguageIntelligenceCore(LocalLanguageModelBackend(without)).generate_response(understanding)
        strip = lambda r: {k: v for k, v in r.to_dict().items() if k not in ("metadata",)}
        self.assertEqual(strip(a), strip(b))

    def test_success_is_stored_once_and_repeats_use_the_loaded_model(self):
        runtime = self.runtime()
        self.install(runtime)
        before = len(self.core.recent_messages(100))
        self.core.process_input(MESSAGE)
        self.core.process_input(MESSAGE + " two")
        self.assertEqual(len(self.core.recent_messages(100)) - before, 4)
        self.assertEqual(runtime.load_calls, 1)
        self.assertEqual(len(runtime.requests), 2)

    def test_default_core_is_unchanged(self):
        self.assertIsNone(self.core.language_intelligence.fallback_backend)
        self.assertEqual(self.core.process_input(MESSAGE), self.expected_fallback_reply())
        self.assertEqual(self.core.get_last_language_response().status, STATUS_DEFERRED)
        self.assertIsNone(self.core.get_last_language_response().fallback_backend_kind)


if __name__ == "__main__":
    unittest.main()
