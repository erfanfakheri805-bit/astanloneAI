"""
Tests for Prompt 415 - End-to-End Local Language Pipeline Verification.

This is a focused INTEGRATION verification, not a new feature. It drives the
whole path a real user message takes, through the actual `Core.process_input`
entry point (never calling `LanguageIntelligenceCore` in isolation), and
checks that every stage built across Prompts 397-414 hands off correctly to
the next one:

    user message
      -> Core.process_input -> Core._handle_conversation
      -> conversation context selection (get_relevant_context /
         resolve_reference / active_topic tracking, Prompts 390-393)
      -> language/context preparation (LanguageContext, Prompt 401)
      -> LanguageIntelligenceCore.understand() / .generate_response()
      -> backend readiness/selection (Prompt 414's select_backend())
      -> LocalLanguageModelBackend (Prompt 398-413) when the model is ready
         OR DeterministicFallbackBackend (Prompt 406) when it is not
      -> a standardized InferenceResult / ResponseGenerationResult
         (Prompts 399/412)
      -> the final reply Core.process_input returns

No real model, no cloud AI, no download: every scenario below uses the
existing test doubles at the `LocalModelRuntime` boundary (`TextRuntime`,
imported from the Prompt 413 test module) exactly like the rest of this
suite already does - this file adds no new double implementation.

Run directly:
    python -m unittest tests.test_e2e_local_language_pipeline -v
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.backend import (
    BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK,
)
from language_intelligence.inference import (
    STATUS_MODEL_NOT_CONFIGURED as INF_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE as INF_UNAVAILABLE,
    STATUS_MODEL_LOAD_FAILED as INF_LOAD_FAILED,
    STATUS_TIMEOUT as INF_TIMEOUT,
    STATUS_SUCCESS as INF_SUCCESS,
    ERROR_NO_CONFIGURATION, ERROR_RUNTIME_DEPENDENCY_MISSING, ERROR_LOAD_FAILED,
)
from language_intelligence.local_model_runtime import ModelLoadError
from language_intelligence.response_generation import (
    STATUS_GENERATED, STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE,
    STATUS_MODEL_FAILED,
)
from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT, _core
from tests.test_local_inference_response_generation import TextRuntime


class E2ECase(GuardCase):
    """Shared plumbing: a scripted `TextRuntime` (Prompt 413's test double)
    plus a fresh `Core` wired to it through the real, public
    `use_local_language_model` entry point - never a hand-built
    LanguageIntelligenceCore, so every scenario below exercises the exact
    object graph a real caller would."""

    def runtime(self, **overrides):
        return TextRuntime(self.config(**overrides))

    def wired_core(self, runtime):
        core, _tmp = _core(self)
        core.use_local_language_model(runtime=runtime)
        return core

    def control_reply(self, message=MESSAGE):
        """What the deterministic pipeline alone (no model at all) answers
        for `message` - the fallback reply every not-ready scenario below
        must reproduce exactly."""
        control, _tmp = _core(self)
        return control.process_input(message)


class TestScenario1LocalModelReady(E2ECase):
    """1. Local model ready: a scripted runtime reports MODEL_READY."""

    def test_end_to_end_ready_model_path(self):
        rt = self.runtime()
        core = self.wired_core(rt)

        self.assertEqual(core.get_local_model_readiness().status, "MODEL_READY")

        reply = core.process_input(MESSAGE)

        # local inference is reached
        self.assertEqual((rt.generate_calls, rt.load_calls, rt.inferences), (1, 1, 1))
        self.assertEqual(rt.requests[0].user_input, MESSAGE)

        # generated text reaches the response result
        response = core.get_last_language_response()
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(response.response_text, MODEL_TEXT)
        self.assertEqual(response.inference_status, INF_SUCCESS)
        self.assertTrue(response.is_generated)
        self.assertEqual(reply, MODEL_TEXT)

        # response identifies the local backend
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(response.selected_backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertTrue(core.language_intelligence.last_backend_selection.local_model_selected)

        # conversation context selection ran and fed the understanding step
        understanding = core.get_last_language_understanding()
        self.assertEqual(understanding.original_input, MESSAGE)
        self.assertEqual(understanding.source_backend, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertIsNotNone(understanding.language_context)

        # conversation context is preserved (the turn was recorded normally)
        self.assertEqual(core.get_recent_turns()[-1], {"user": MESSAGE, "assistant": MODEL_TEXT})

    def test_follow_up_message_still_carries_selected_history_to_the_model(self):
        rt = self.runtime()
        core = self.wired_core(rt)
        core.process_input("What is Python?")
        core.process_input("how do I install it?")

        # conversation-context selection (Prompts 390/392/393) still ran and
        # its result reached the request the model actually received.
        second_request = rt.requests[-1]
        self.assertEqual(second_request.user_input, "how do I install it?")
        self.assertIn(
            ("user", "What is Python?"),
            [(m.role, m.content) for m in second_request.conversation],
        )
        understanding = core.get_last_language_understanding()
        self.assertIsNotNone(understanding.active_topic)


class TestScenario2ModelNotConfigured(E2ECase):
    """2. Model not configured: the runtime reports MODEL_NOT_CONFIGURED."""

    def test_end_to_end_not_configured_path(self):
        rt = TextRuntime(None)
        core = self.wired_core(rt)
        self.assertEqual(core.get_local_model_readiness().status, "MODEL_NOT_CONFIGURED")

        expected_reply = self.control_reply()
        reply = core.process_input(MESSAGE)

        # local inference is never called
        self.assertEqual((rt.generate_calls, rt.load_calls, rt.inferences), (0, 0, 0))
        self.assertEqual(rt.requests, [])

        # deterministic fallback is selected and its reply is returned
        response = core.get_last_language_response()
        self.assertEqual(response.selected_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(reply, expected_reply)
        self.assertFalse(response.is_generated)
        self.assertTrue(response.needs_fallback)

        # the original structured reason is preserved
        self.assertEqual(response.status, STATUS_MODEL_NOT_CONFIGURED)
        self.assertEqual(response.inference_status, INF_NOT_CONFIGURED)
        self.assertEqual(response.error_code, ERROR_NO_CONFIGURATION)
        self.assertIsNone(response.response_text)

        # response identifies the fallback backend
        self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)


class TestScenario3ModelUnavailable(E2ECase):
    """3. Model unavailable: same behavior as Scenario 2, MODEL_UNAVAILABLE."""

    def test_end_to_end_unavailable_path(self):
        rt = self.runtime()
        rt.dependency_ok = False
        core = self.wired_core(rt)
        self.assertEqual(core.get_local_model_readiness().status, "MODEL_UNAVAILABLE")

        expected_reply = self.control_reply()
        reply = core.process_input(MESSAGE)

        self.assertEqual((rt.generate_calls, rt.load_calls, rt.inferences), (0, 0, 0))
        self.assertEqual(rt.requests, [])

        response = core.get_last_language_response()
        self.assertEqual(response.selected_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(reply, expected_reply)

        self.assertEqual(response.status, STATUS_MODEL_UNAVAILABLE)
        self.assertEqual(response.inference_status, INF_UNAVAILABLE)
        self.assertEqual(response.error_code, ERROR_RUNTIME_DEPENDENCY_MISSING)
        self.assertIsNone(response.response_text)
        self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)


class TestScenario4ModelLoadFailed(E2ECase):
    """4. Model load failure: same behavior as Scenario 2, MODEL_LOAD_FAILED."""

    def test_end_to_end_load_failed_path(self):
        rt = self.runtime()
        rt.load_error = ModelLoadError("corrupt weights")
        rt.load()  # the one, real, already-failed load attempt
        self.assertEqual(rt.load_calls, 1)

        core = self.wired_core(rt)
        self.assertEqual(core.get_local_model_readiness().status, "MODEL_LOAD_FAILED")

        expected_reply = self.control_reply()
        reply = core.process_input(MESSAGE)

        # the failed load is not retried, and inference is never attempted
        self.assertEqual(rt.load_calls, 1)
        self.assertEqual((rt.generate_calls, rt.inferences), (0, 0))
        self.assertEqual(rt.requests, [])

        response = core.get_last_language_response()
        self.assertEqual(response.selected_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(reply, expected_reply)

        self.assertEqual(response.status, STATUS_MODEL_UNAVAILABLE)
        self.assertEqual(response.inference_status, INF_LOAD_FAILED)
        self.assertEqual(response.error_code, ERROR_LOAD_FAILED)
        self.assertIsNone(response.response_text)
        self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)


class TestScenario5ReadyModelInferenceFailure(E2ECase):
    """5. The model reports ready, but inference itself times out."""

    def test_end_to_end_ready_model_but_inference_fails(self):
        rt = self.runtime(timeout_seconds=5.0)
        rt.spend, rt.poll = 6.0, True  # exceeds the configured timeout
        core = self.wired_core(rt)
        self.assertEqual(core.get_local_model_readiness().status, "MODEL_READY")

        expected_reply = self.control_reply()
        reply = core.process_input(MESSAGE)

        # inference really was attempted (this is not a pre-inference block)
        self.assertEqual((rt.generate_calls, rt.load_calls, rt.inferences), (1, 1, 1))

        response = core.get_last_language_response()
        # the local backend remains the selected backend
        self.assertEqual(response.selected_backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)

        # the failure remains structured
        self.assertEqual(response.status, STATUS_MODEL_FAILED)
        self.assertEqual(response.inference_status, INF_TIMEOUT)
        self.assertTrue(response.error_code)

        # the system never claims the local model successfully generated
        self.assertFalse(response.is_generated)
        self.assertIsNone(response.response_text)
        self.assertNotEqual(reply, MODEL_TEXT)

        # Prompt 406 fallback behavior still applies
        self.assertTrue(response.needs_fallback)
        self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(reply, expected_reply)


class TestScenario6ConversationContinuity(E2ECase):
    """6. deterministic fallback, then the model becomes ready mid-conversation."""

    def test_conversation_state_survives_the_backend_switch(self):
        rt = TextRuntime(None)
        core = self.wired_core(rt)

        # A parallel, plain-deterministic core with the identical turns,
        # used only as the ground truth for what conversation tracking
        # should look like without any model ever being involved.
        control, _tmp = _core(self)

        first_reply = core.process_input("What is Python?")
        control_first = control.process_input("What is Python?")
        self.assertEqual(first_reply, control_first)
        first_response = core.get_last_language_response()
        self.assertEqual(first_response.selected_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual((rt.generate_calls, rt.inferences), (0, 0))

        # the model becomes ready
        rt.configure(self.config())
        self.assertEqual(core.get_local_model_readiness().status, "MODEL_READY")

        second_reply = core.process_input("how do I install it?")
        control.process_input("how do I install it?")

        # the local backend is now used, and exactly once
        second_response = core.get_last_language_response()
        self.assertEqual(second_response.selected_backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(second_reply, MODEL_TEXT)
        self.assertEqual(rt.inferences, 1)

        # existing conversation state, topic and history remain intact
        # across the switch - identical to the never-switched control core.
        self.assertEqual(
            core.get_recent_turns(),
            [
                {"user": "What is Python?", "assistant": first_reply},
                {"user": "how do I install it?", "assistant": second_reply},
            ],
        )
        self.assertEqual(core.topic_tracker.current.topic, control.topic_tracker.current.topic)
        self.assertEqual(
            {k: v for k, v in core.conversation_state.to_dict().items()},
            {k: v for k, v in control.conversation_state.to_dict().items()},
        )
        self.assertEqual(
            core.get_last_language_understanding().original_input, "how do I install it?"
        )

        # relevant history reached the now-ready model
        history = [(m.role, m.content) for m in rt.requests[-1].conversation]
        self.assertIn(("user", "What is Python?"), history)
        self.assertIn(("assistant", first_reply), history)
        self.assertEqual(second_response.selected_backend_kind, BACKEND_KIND_LOCAL_MODEL)


if __name__ == "__main__":
    unittest.main()
