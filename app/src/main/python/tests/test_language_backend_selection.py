"""
Tests for Prompt 414 - Language Backend Selection.

`LanguageIntelligenceCore.select_backend()` chooses between the local-model
backend and the (Prompt 406) deterministic fallback backend from the model's
readiness: MODEL_READY -> local; MODEL_NOT_CONFIGURED / MODEL_UNAVAILABLE /
MODEL_LOAD_FAILED -> deterministic fallback, with the local model not called
at all and the structured reason preserved. Every response says which backend
was selected. Test doubles only at the runtime boundary - no model.

Run directly:
    python -m unittest tests.test_language_backend_selection -v
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK
from language_intelligence.backend_selection import BackendSelection
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.local_model_provider import RuntimeBackedProvider
from language_intelligence.local_model_runtime import LocalModelError, ModelLoadError
from language_intelligence.inference import (
    STATUS_SUCCESS, STATUS_MODEL_NOT_CONFIGURED as INF_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE as INF_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED as INF_LOAD_FAILED,
    STATUS_TIMEOUT as INF_TIMEOUT,
    READINESS_MODEL_READY, READINESS_MODEL_NOT_CONFIGURED, READINESS_MODEL_UNAVAILABLE,
    READINESS_MODEL_LOAD_FAILED,
    ERROR_NO_CONFIGURATION, ERROR_RUNTIME_DEPENDENCY_MISSING, ERROR_LOAD_FAILED,
)
from language_intelligence.response_generation import (
    ResponseGenerationResult, STATUS_DEFERRED, STATUS_GENERATED, STATUS_MODEL_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_FAILED,
)
from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT, _core
from tests.test_local_inference_response_generation import TextRuntime


class SpyBackend(LocalLanguageModelBackend):
    """The real local backend, counting how often the selection layer calls it."""
    generate_calls = 0

    def generate_response(self, understanding, context=None, cancellation_token=None):
        SpyBackend.generate_calls += 1
        return super().generate_response(understanding, context, cancellation_token)


class SelectCase(GuardCase):
    def setUp(self):
        super().setUp()
        SpyBackend.generate_calls = 0

    def runtime(self, **overrides):
        return TextRuntime(self.config(**overrides))

    def states(self):
        """name -> (runtime, readiness status, response status, inference status, error code)"""
        unavailable = self.runtime(); unavailable.dependency_ok = False
        load_failed = self.runtime(); load_failed.load_error = ModelLoadError("corrupt")
        load_failed.load()  # the one explicit, failed load attempt
        return {
            "not_configured": (TextRuntime(None), READINESS_MODEL_NOT_CONFIGURED,
                               STATUS_MODEL_NOT_CONFIGURED, INF_NOT_CONFIGURED, ERROR_NO_CONFIGURATION),
            "unavailable": (unavailable, READINESS_MODEL_UNAVAILABLE, STATUS_MODEL_UNAVAILABLE,
                            INF_UNAVAILABLE, ERROR_RUNTIME_DEPENDENCY_MISSING),
            "load_failed": (load_failed, READINESS_MODEL_LOAD_FAILED, STATUS_MODEL_UNAVAILABLE,
                            INF_LOAD_FAILED, ERROR_LOAD_FAILED),
        }

    def language_core(self, runtime, core=None, backend_class=LocalLanguageModelBackend):
        core = core or _core(self)[0]
        return LanguageIntelligenceCore(
            backend_class(runtime=runtime),
            fallback_backend=DeterministicFallbackBackend(core.understanding))

    def touched(self, runtime):
        return (runtime.generate_calls, runtime.load_calls, runtime.inferences)


class TestReadyModelSelectsLocalBackend(SelectCase):
    """1."""

    def test_selection_and_response(self):
        rt = self.runtime()
        li = self.language_core(rt)
        selection = li.select_backend()
        self.assertIsInstance(selection, BackendSelection)
        self.assertEqual(selection.selected_backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertTrue(selection.local_model_selected)
        self.assertFalse(selection.fallback_selected)
        self.assertEqual(selection.readiness.status, READINESS_MODEL_READY)
        self.assertIsNone(selection.reason)
        self.assertIsNone(selection.not_ready_response)
        response = li.generate_response(self.understanding())
        self.assertEqual((response.status, response.response_text), (STATUS_GENERATED, MODEL_TEXT))
        self.assertEqual(response.selected_backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertIs(li.last_backend_selection.local_model_selected, True)
        self.assertEqual(rt.inferences, 1)

    def test_through_core_the_reply_is_the_model_text(self):
        core, _ = _core(self)
        core.use_local_language_model(runtime=self.runtime())
        self.assertEqual(core.process_input(MESSAGE), MODEL_TEXT)
        self.assertEqual(core.get_last_language_response().selected_backend_kind, BACKEND_KIND_LOCAL_MODEL)


class TestNotReadySelectsTheFallback(SelectCase):
    """2 + 3 + 4."""

    def test_each_not_ready_state_selects_the_deterministic_fallback(self):
        for name, (rt, readiness, status, inference_status, code) in self.states().items():
            with self.subTest(state=name):
                li = self.language_core(rt)
                selection = li.select_backend()
                self.assertEqual(selection.selected_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
                self.assertFalse(selection.local_model_selected)
                self.assertTrue(selection.fallback_selected)
                self.assertEqual(selection.readiness.status, readiness)
                self.assertIn(readiness, selection.reason)
                self.assertIn(code, selection.reason)

    def test_the_structured_reason_for_not_using_the_model_is_preserved(self):
        for name, (rt, readiness, status, inference_status, code) in self.states().items():
            with self.subTest(state=name):
                response = self.language_core(rt).generate_response(self.understanding())
                self.assertEqual((response.status, response.inference_status, response.error_code),
                                 (status, inference_status, code))
                self.assertIsNone(response.response_text)
                self.assertFalse(response.is_generated)
                self.assertTrue(response.needs_fallback)
                self.assertTrue(response.reason)
                self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)

    def test_the_reason_is_the_same_as_a_blocked_request_reported_before_selection(self):
        for name, (rt, *_rest) in self.states().items():
            with self.subTest(state=name):
                direct = LocalLanguageModelBackend(runtime=rt).generate_response(self.understanding())
                routed = self.language_core(rt).generate_response(self.understanding())
                self.assertEqual((direct.status, direct.inference_status, direct.error_code, direct.reason),
                                 (routed.status, routed.inference_status, routed.error_code, routed.reason))

    def test_selection_follows_the_model_state_deterministically(self):
        rt = TextRuntime(None)
        li = self.language_core(rt)
        first = [li.select_backend().selected_backend_kind for _ in range(3)]
        self.assertEqual(first, [BACKEND_KIND_DETERMINISTIC_FALLBACK] * 3)
        rt.configure(self.config())
        self.assertEqual(li.select_backend().selected_backend_kind, BACKEND_KIND_LOCAL_MODEL)
        rt.dependency_ok = False
        self.assertEqual(li.select_backend().selected_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)


class TestSelectedBackendIsIdentifiable(SelectCase):
    """5."""

    def test_local_fallback_and_failed_local_responses_are_all_distinguishable(self):
        ok = self.language_core(self.runtime()).generate_response(self.understanding())
        blocked = self.language_core(TextRuntime(None)).generate_response(self.understanding())
        slow = self.runtime(timeout_seconds=5.0); slow.spend, slow.poll = 6.0, True
        failed = self.language_core(slow).generate_response(self.understanding())

        self.assertEqual((ok.selected_backend_kind, ok.is_generated, ok.needs_fallback),
                         (BACKEND_KIND_LOCAL_MODEL, True, False))
        self.assertEqual((blocked.selected_backend_kind, blocked.is_generated, blocked.needs_fallback),
                         (BACKEND_KIND_DETERMINISTIC_FALLBACK, False, True))
        # selected and tried the local model, which then failed at inference (Prompt 406 handling)
        self.assertEqual((failed.selected_backend_kind, failed.inference_status, failed.needs_fallback),
                         (BACKEND_KIND_LOCAL_MODEL, INF_TIMEOUT, True))
        self.assertEqual(failed.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(ok.to_dict()["selected_backend_kind"], BACKEND_KIND_LOCAL_MODEL)

    def test_the_fallback_is_never_presented_as_the_local_model(self):
        blocked = self.language_core(TextRuntime(None)).generate_response(self.understanding())
        self.assertNotEqual(blocked.selected_backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertNotIn(MODEL_TEXT, str(blocked.to_dict()))

    def test_default_deterministic_core_reports_the_deterministic_backend(self):
        core, _ = _core(self)
        core.process_input(MESSAGE)
        response = core.get_last_language_response()
        self.assertEqual((response.status, response.selected_backend_kind),
                         (STATUS_DEFERRED, BACKEND_KIND_DETERMINISTIC_FALLBACK))


class TestConversationIsPreserved(SelectCase):
    """6."""

    def turns(self, core):
        return [core.process_input("What is Python?"), core.process_input("how do I install it?")]

    def test_not_ready_model_leaves_the_deterministic_conversation_untouched(self):
        control, _ = _core(self)
        expected = self.turns(control)
        core, _ = _core(self)
        core.use_local_language_model(runtime=TextRuntime(None))
        self.assertEqual(self.turns(core), expected)
        self.assertEqual(core.get_recent_turns(), control.get_recent_turns())
        self.assertEqual(core.topic_tracker.current.topic, control.topic_tracker.current.topic)
        self.assertEqual(core.conversation_state.to_dict(), control.conversation_state.to_dict())
        self.assertEqual(core.get_last_language_understanding().original_input, "how do I install it?")
        self.assertEqual(core.get_last_language_response().selected_backend_kind,
                         BACKEND_KIND_DETERMINISTIC_FALLBACK)

    def test_ready_model_still_receives_context_language_and_message(self):
        rt = self.runtime()
        core, _ = _core(self)
        core.use_local_language_model(runtime=rt)
        self.turns(core)
        second = rt.requests[-1]
        self.assertEqual(second.user_input, "how do I install it?")
        self.assertIn(("user", "What is Python?"), [(m.role, m.content) for m in second.conversation])
        self.assertEqual(second.language_context.conversation_language, "english")

    def test_switching_from_fallback_to_model_mid_conversation_keeps_history(self):
        rt = self.runtime(); rt.dependency_ok = False
        core, _ = _core(self)
        core.use_local_language_model(runtime=rt)
        first = core.process_input("What is Python?")
        rt.dependency_ok = True
        self.assertEqual(core.process_input("how do I install it?"), MODEL_TEXT)
        history = [(m.role, m.content) for m in rt.requests[-1].conversation]
        self.assertIn(("user", "What is Python?"), history)
        self.assertIn(("assistant", first), history)
        self.assertEqual(rt.inferences, 1)


class TestExistingFallbackStaysCompatible(SelectCase):
    """7."""

    def test_reply_equals_the_deterministic_reply_for_every_not_ready_state(self):
        expected = _core(self)[0].process_input(MESSAGE)
        for name, (rt, *_rest) in self.states().items():
            with self.subTest(state=name):
                core, _ = _core(self)
                core.use_local_language_model(runtime=rt)
                self.assertEqual(core.process_input(MESSAGE), expected)

    def test_without_a_fallback_backend_nothing_is_chosen_and_behaviour_is_as_before(self):
        li = LanguageIntelligenceCore(LocalLanguageModelBackend(runtime=TextRuntime(None)))
        selection = li.select_backend()
        self.assertEqual(selection.selected_backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertFalse(selection.fallback_selected)
        response = li.generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_NOT_CONFIGURED)
        self.assertIsNone(response.fallback_backend_kind)

    def test_deterministic_primary_is_selected_as_before(self):
        core, _ = _core(self)
        li = LanguageIntelligenceCore(DeterministicFallbackBackend(core.understanding))
        selection = li.select_backend()
        self.assertEqual(selection.selected_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(li.generate_response(self.understanding()).status, STATUS_DEFERRED)

    def test_backend_used_directly_is_unchanged(self):
        response = LocalLanguageModelBackend(runtime=TextRuntime(None)).generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_NOT_CONFIGURED)
        self.assertIsNone(response.selected_backend_kind)  # only a core routes and labels

    def test_old_style_results_and_a_custom_backend_still_work(self):
        self.assertIsNone(ResponseGenerationResult(STATUS_DEFERRED).selected_backend_kind)

        class Legacy(DeterministicFallbackBackend):
            def generate_response(self, understanding, context=None, cancellation_token=None):
                return ResponseGenerationResult(STATUS_DEFERRED, reason="legacy")

        core, _ = _core(self)
        li = LanguageIntelligenceCore(Legacy(core.understanding))
        self.assertEqual(li.generate_response(self.understanding()).reason, "legacy")


class TestNoInferenceWhenNotReady(SelectCase):
    """8."""

    def test_nothing_reaches_the_backend_provider_or_runtime(self):
        for name, (rt, *_rest) in self.states().items():
            with self.subTest(state=name):
                SpyBackend.generate_calls = 0
                before = self.touched(rt)
                calls = []

                class SpyProvider(RuntimeBackedProvider):
                    def generate(self, request, cancellation_token=None):
                        calls.append(1)
                        return super().generate(request, cancellation_token)

                core, _ = _core(self)
                li = LanguageIntelligenceCore(
                    SpyBackend(provider=SpyProvider(rt)),
                    fallback_backend=DeterministicFallbackBackend(core.understanding))
                for _ in range(3):
                    li.generate_response(self.understanding())
                self.assertEqual(SpyBackend.generate_calls, 0)   # the local backend was not even asked
                self.assertEqual(calls, [])
                self.assertEqual(self.touched(rt), before)       # no runtime call, load or inference
                self.assertEqual(rt.requests, [])

    def test_selecting_never_loads_or_infers(self):
        rt = self.runtime()
        li = self.language_core(rt)
        for _ in range(3):
            li.select_backend()
        self.assertEqual(self.touched(rt), (0, 0, 0))

    def test_not_ready_through_core_runs_no_inference_and_no_retry(self):
        rt = self.runtime(); rt.load_error = ModelLoadError("corrupt"); rt.load()
        core, _ = _core(self)
        core.use_local_language_model(runtime=rt)
        before = self.touched(rt)
        for _ in range(3):
            core.process_input(MESSAGE)
        self.assertEqual(self.touched(rt), before)


if __name__ == "__main__":
    unittest.main()
