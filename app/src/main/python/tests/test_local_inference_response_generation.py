"""
Tests for Prompt 413 - Connect Local Inference to Response Generation.

`Core.use_local_language_model()` opts a Core in to the path
    runtime -> provider -> LocalLanguageModelBackend -> standardized
    InferenceResult -> ResponseGenerationResult -> the reply,
with the deterministic backend as the Prompt 406 fallback. Successful model
text is the reply exactly as produced; every failure stays a structured
`ResponseGenerationResult` (`needs_fallback`) and the existing deterministic
pipeline answers. Test doubles only at the runtime boundary - no model.

Run directly:
    python -m unittest tests.test_local_inference_response_generation -v
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.inference import (
    GenerationParameters, STATUS_SUCCESS, STATUS_MODEL_NOT_CONFIGURED as INF_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE as INF_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED as INF_LOAD_FAILED,
    STATUS_INFERENCE_FAILED as INF_FAILED, STATUS_RESOURCE_LIMIT as INF_RESOURCE,
    STATUS_TIMEOUT as INF_TIMEOUT,
)
from language_intelligence.local_model_provider import RuntimeBackedProvider
from language_intelligence.local_model_runtime import LocalModelError, ModelLoadError, RuntimeOutput
from language_intelligence.response_generation import (
    ResponseGenerationResult, STATUS_DEFERRED, STATUS_GENERATED, STATUS_MODEL_FAILED,
    STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE, MODEL_FAILURE_STATUSES,
)
from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT, _core
from tests.test_standardized_inference_result import Double


class TextRuntime(Double):
    """Double whose model text is scripted (exact bytes matter to these tests)."""

    def __init__(self, config, text=MODEL_TEXT):
        super().__init__(config)
        self.text = text
        self.requests = []
        self.generate_calls = 0

    def generate(self, request, cancellation_token=None):
        self.generate_calls += 1
        return super().generate(request, cancellation_token)

    def _run_inference(self, request, params, config, control):
        self.requests.append(request)
        if self.infer_error is not None:
            self.inferences += 1
            raise self.infer_error
        self.inferences += 1
        self.clock.advance(self.spend)
        if self.poll:
            control.check()
        return RuntimeOutput(self.text, "stop", prompt_tokens=7, output_tokens=5)


class ConnectCase(GuardCase):
    def runtime(self, text=MODEL_TEXT, **overrides):
        return TextRuntime(self.config(**overrides), text)

    def model_core(self, runtime=None, **options):
        core, _ = _core(self)
        core.use_local_language_model(runtime=runtime, **options)
        return core

    def control_reply(self, message=MESSAGE):
        core, _ = _core(self)
        return core.process_input(message)


class TestSuccessReachesResponseGeneration(ConnectCase):
    """1. successful local inference reaches Response Generation"""

    def test_reply_is_the_model_text_and_result_is_a_generated_response(self):
        rt = self.runtime()
        core = self.model_core(rt)
        self.assertEqual(core.process_input(MESSAGE), MODEL_TEXT)
        response = core.get_last_language_response()
        self.assertIsInstance(response, ResponseGenerationResult)
        self.assertEqual((response.status, response.inference_status), (STATUS_GENERATED, STATUS_SUCCESS))
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertTrue(response.is_generated)
        self.assertFalse(response.needs_fallback)
        self.assertIsNone(response.fallback_backend_kind)
        self.assertEqual(response.metadata["model_id"], "test-model")
        self.assertEqual(rt.inferences, 1)

    def test_it_flows_runtime_provider_backend_response(self):
        rt = self.runtime()
        provider = RuntimeBackedProvider(rt)
        core, _ = _core(self)
        core.use_local_language_model(provider=provider)
        self.assertEqual(core.process_input(MESSAGE), MODEL_TEXT)
        self.assertEqual(core.get_local_model_readiness().status, "MODEL_READY")

    def test_generate_language_response_path_matches(self):
        core = self.model_core(self.runtime())
        response = core.generate_language_response(core.understand_language(MESSAGE))
        self.assertEqual((response.status, response.response_text), (STATUS_GENERATED, MODEL_TEXT))


class TestGeneratedTextIsPreserved(ConnectCase):
    """2. generated model text is not rewritten, duplicated or discarded"""

    def test_exact_text_including_whitespace_and_unicode(self):
        for text in ("  leading and trailing  \n", "line one\n\n  line two\n\tline three",
                     "Zażółć gęślą jaźń — سلام — 你好", "Text with  double  spaces."):
            with self.subTest(text=text):
                rt = self.runtime(text)
                core = self.model_core(rt)
                self.assertEqual(core.process_input(MESSAGE), text)
                self.assertEqual(core.get_last_language_response().response_text, text)

    def test_the_same_text_is_what_memory_and_context_record(self):
        core = self.model_core(self.runtime("exact model text"))
        core.process_input(MESSAGE)
        self.assertEqual(core.get_recent_turns()[-1], {"user": MESSAGE, "assistant": "exact model text"})
        rows = core.memory.recent_messages()
        self.assertEqual(sum(1 for r in rows if "exact model text" in str(r)), 1)

    def test_one_inference_per_message_and_no_repetition(self):
        rt = self.runtime("once")
        core = self.model_core(rt)
        reply = core.process_input(MESSAGE)
        self.assertEqual(reply, "once")
        self.assertEqual(reply.count("once"), 1)
        self.assertEqual((rt.load_calls, rt.inferences), (1, 1))
        core.process_input(MESSAGE + " again")
        self.assertEqual((rt.load_calls, rt.inferences), (1, 2))


class TestFailureReachesTheExistingFallback(ConnectCase):
    """3 + 4. a model failure is a structured needs_fallback result; no fake output"""

    def failing(self):
        unavailable = self.runtime(); unavailable.dependency_ok = False
        load_failed = self.runtime(); load_failed.load_error = ModelLoadError("corrupt")
        infer_failed = self.runtime(); infer_failed.infer_error = LocalModelError("crashed")
        timeout = self.runtime(timeout_seconds=5.0); timeout.spend, timeout.poll = 6.0, True
        return (
            ("not_configured", None, STATUS_MODEL_NOT_CONFIGURED, INF_NOT_CONFIGURED, {}),
            ("unavailable", unavailable, STATUS_MODEL_UNAVAILABLE, INF_UNAVAILABLE, {}),
            ("load_failed", load_failed, STATUS_MODEL_UNAVAILABLE, INF_LOAD_FAILED, {}),
            ("inference_failed", infer_failed, STATUS_MODEL_FAILED, INF_FAILED, {}),
            ("resource_limit", self.runtime(max_output_tokens=64), STATUS_MODEL_FAILED, INF_RESOURCE,
             {"generation_parameters": GenerationParameters(max_output_tokens=65)}),
            ("timeout", timeout, STATUS_MODEL_FAILED, INF_TIMEOUT, {}),
        )

    def test_each_failure_is_answered_by_the_deterministic_pipeline(self):
        expected = self.control_reply()
        for name, rt, status, inference_status, options in self.failing():
            with self.subTest(failure=name):
                core = self.model_core(rt, **options)
                self.assertEqual(core.process_input(MESSAGE), expected)
                response = core.get_last_language_response()
                self.assertEqual((response.status, response.inference_status),
                                 (status, inference_status))
                self.assertTrue(response.needs_fallback)
                self.assertFalse(response.is_generated)
                self.assertIn(response.status, MODEL_FAILURE_STATUSES)
                self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
                self.assertTrue(response.error_code)
                self.assertTrue(response.reason)

    def test_no_model_text_is_ever_produced_for_a_failed_request(self):
        for name, rt, *_rest in self.failing():
            options = _rest[-1]
            with self.subTest(failure=name):
                core = self.model_core(rt, **options)
                reply = core.process_input(MESSAGE)
                response = core.get_last_language_response()
                self.assertIsNone(response.response_text)
                self.assertNotIn(MODEL_TEXT, reply)
                self.assertNotIn(MODEL_TEXT, str(response.to_dict()))

    def test_failure_details_are_kept_on_the_result(self):
        core = self.model_core(self.runtime(max_output_tokens=64),
                               generation_parameters=GenerationParameters(max_output_tokens=65))
        core.process_input(MESSAGE)
        response = core.get_last_language_response()
        self.assertEqual(response.metadata["details"], {"requested": 65, "limit": 64})
        self.assertEqual(response.metadata["model_id"], "test-model")

    def test_the_model_answers_again_once_it_can(self):
        rt = self.runtime(); rt.dependency_ok = False
        core = self.model_core(rt)
        self.assertNotEqual(core.process_input(MESSAGE), MODEL_TEXT)
        rt.dependency_ok = True
        self.assertEqual(core.process_input(MESSAGE + " two"), MODEL_TEXT)


class TestDeterministicBehaviourWithoutAModel(ConnectCase):
    """5."""

    def test_default_core_is_unchanged(self):
        core, _ = _core(self)
        reply = core.process_input(MESSAGE)
        response = core.get_last_language_response()
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertFalse(response.is_generated)
        self.assertFalse(response.needs_fallback)
        self.assertEqual(response.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(reply, self.control_reply())
        self.assertEqual(core.get_local_model_readiness().status, "MODEL_NOT_CONFIGURED")

    def test_opting_in_without_any_runtime_answers_deterministically(self):
        core, _ = _core(self)
        core.use_local_language_model()
        self.assertEqual(core.process_input(MESSAGE), self.control_reply())
        response = core.get_last_language_response()
        self.assertEqual((response.status, response.inference_status),
                         (STATUS_MODEL_NOT_CONFIGURED, INF_NOT_CONFIGURED))
        self.assertIsNone(response.response_text)

    def test_skills_and_goals_still_take_priority_over_the_model(self):
        rt = self.runtime()
        core = self.model_core(rt)
        goal_reply = core.process_input("I want to learn Python")
        control, _ = _core(self)
        self.assertEqual(goal_reply.splitlines()[0], control.process_input("I want to learn Python").splitlines()[0])
        self.assertEqual(rt.inferences, 0)


class TestConversationIsPreserved(ConnectCase):
    """6."""

    def two_turns(self, core):
        return [core.process_input("What is Python?"), core.process_input("how do I install it?")]

    def test_context_language_and_user_message_reach_the_model_intact(self):
        rt = self.runtime()
        core = self.model_core(rt)
        self.two_turns(core)
        first, second = rt.requests
        self.assertEqual((first.user_input, second.user_input), ("What is Python?", "how do I install it?"))
        history = [(m.role, m.content) for m in second.conversation]
        self.assertIn(("user", "What is Python?"), history)
        self.assertIn(("assistant", MODEL_TEXT), history)
        self.assertEqual(first.language_context.detected_language, "english")
        self.assertEqual(second.language_context.conversation_language, "english")

    def test_topic_reference_and_state_match_a_deterministic_run(self):
        control, _ = _core(self)
        self.two_turns(control)
        core = self.model_core(self.runtime())
        self.two_turns(core)
        self.assertEqual(core.topic_tracker.current.topic, control.topic_tracker.current.topic)
        self.assertEqual(core.topic_tracker.current.topic_source, control.topic_tracker.current.topic_source)
        self.assertEqual(core.get_last_language_understanding().original_input, "how do I install it?")
        self.assertEqual(core.conversation_state.to_dict(), control.conversation_state.to_dict())

    def test_turns_and_messages_are_stored_once_each(self):
        core = self.model_core(self.runtime())
        self.two_turns(core)
        turns = core.get_recent_turns()
        self.assertEqual([t["user"] for t in turns], ["What is Python?", "how do I install it?"])
        self.assertTrue(all(t["assistant"] == MODEL_TEXT for t in turns))
        users = [r for r in core.memory.recent_messages() if "What is Python?" in str(r)]
        self.assertEqual(len(users), 1)

    def test_a_failed_turn_keeps_the_conversation_going(self):
        rt = self.runtime(); rt.dependency_ok = False
        core = self.model_core(rt)
        deterministic = core.process_input("What is Python?")
        rt.dependency_ok = True
        self.assertEqual(core.process_input("how do I install it?"), MODEL_TEXT)
        history = [(m.role, m.content) for m in rt.requests[-1].conversation]
        self.assertIn(("user", "What is Python?"), history)
        self.assertIn(("assistant", deterministic), history)


class TestExistingCallersAreCompatible(ConnectCase):
    """7."""

    def test_result_shape_and_statuses_are_unchanged(self):
        # additive since Prompt 414 (selected_backend_kind): every earlier key is still there
        self.assertLessEqual({"status", "response_text", "reason", "backend_kind", "inference_status",
                              "error_code", "metadata", "fallback_backend_kind"},
                             set(ResponseGenerationResult(STATUS_GENERATED).to_dict()))
        old_style = ResponseGenerationResult(STATUS_DEFERRED, None, "why", "deterministic_fallback")
        self.assertFalse(old_style.is_generated or old_style.needs_fallback)

    def test_is_generated_needs_real_text(self):
        self.assertFalse(ResponseGenerationResult(STATUS_GENERATED, None).is_generated)
        self.assertFalse(ResponseGenerationResult(STATUS_GENERATED, "  ").is_generated)
        self.assertTrue(ResponseGenerationResult(STATUS_GENERATED, "x").is_generated)
        for status in MODEL_FAILURE_STATUSES:
            self.assertTrue(ResponseGenerationResult(status).needs_fallback)

    def test_direct_use_of_the_language_core_still_works(self):
        from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
        from language_intelligence.local_model_backend import LocalLanguageModelBackend
        core, _ = _core(self)
        core.language_intelligence = LanguageIntelligenceCore(
            LocalLanguageModelBackend(runtime=self.runtime()),
            fallback_backend=DeterministicFallbackBackend(core.understanding))
        self.assertEqual(core.process_input(MESSAGE), MODEL_TEXT)

    def test_process_input_still_returns_a_string_for_every_outcome(self):
        for rt in (None, self.runtime()):
            core = self.model_core(rt)
            self.assertIsInstance(core.process_input(MESSAGE), str)


if __name__ == "__main__":
    unittest.main()
