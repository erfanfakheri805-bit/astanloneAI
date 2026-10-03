"""
Tests for Prompt 437 - Learned Response Integration.

`decide_learned_response()` (language_intelligence/
learned_response_decision.py) runs inside
`LanguageIntelligenceCore.generate_response()` BEFORE normal backend
routing. A learned response - uniquely selected (434), bound (435),
rendered (436) and valid under the Prompt 430 rules - becomes an ordinary
`ResponseGenerationResult` (STATUS_GENERATED, backend_kind
"learned_response") and is the reply; in every other case routing (backend
selection, local model, deterministic fallback) runs exactly as before.

Real Understanding Engine, real Prompt 416-424 stores and a real `Core`;
the only test double is the existing runtime-boundary `TextRuntime`.

Run directly:
    python -m unittest tests.test_learned_response_integration -v
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL, ALL_BACKEND_KINDS
from language_intelligence.conversation_response import ConversationResponse
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult, STATUS_DEFERRED, STATUS_GENERATED,
)
from language_intelligence.response_generation_outcome import (
    STATUS_SUCCESS, STATUS_FALLBACK, STATUS_UNRESOLVED,
)
from language_intelligence.response_generation_validation import (
    ResponseGenerationValidation, VALIDATION_INVALID, VALIDATION_VALID,
)
from language_intelligence.learned_response_pattern_selection import RESPONSE_PATTERNS_KEY
from language_intelligence.learned_response_decision import (
    decide_learned_response, LearnedResponseDecision, BACKEND_KIND_LEARNED_RESPONSE,
    RESPONSE_SOURCE_LEARNED_RESPONSE, REASON_USED, REASON_NO_REQUEST,
    REASON_SELECTION_NOT_RESOLVED, REASON_BINDING_NOT_RESOLVED, REASON_RENDERING_NOT_RESOLVED,
    REASON_VALIDATION_FAILED,
)

from tests import test_learned_response_pattern_binding as _b
from tests import test_response_generation_request as _r

QUESTION_PATTERN = _b.QUESTION_PATTERN
PREFERENCE_PATTERN = _b.PREFERENCE_PATTERN
MESSAGE = "what is python"
LEARNED_TEXT = "About python."


class _CoreCase(_r._LocalPath):
    """A real Core with a taught `what is {{topic}}` sentence pattern bound
    to the meaning `ask_question`; response patterns are taught on that
    meaning through the existing `learn_language_item`."""

    def taught_core(self, patterns=None, model=None):
        core = self.core()
        assert core.teach_sentence_pattern("en", QUESTION_PATTERN).status == _r.STATUS_CREATED
        bound = core.bind_pattern_meaning("en", QUESTION_PATTERN, "ask_question")
        assert bound.success, bound.errors
        if patterns is not None:
            core.learn_language_item("en", "meaning", "ask_question", meaning={
                "response_action": "provide_information", RESPONSE_PATTERNS_KEY: patterns})
        if model is not None:
            core.use_local_language_model(runtime=model)
        return core

    @staticmethod
    def valid_pattern(template="About {{topic}}."):
        return [{"id": "answer_question", "template": template}]

    def generate(self, core, text=MESSAGE):
        understanding = core.understand_language(text)
        response = core.language_intelligence.generate_response(understanding, context=core.context)
        return understanding, response, core.language_intelligence


# ----------------------------------------------------------------------
class TestValidLearnedResponseIsUsed(_CoreCase):
    def test_the_learned_text_is_the_reply_and_no_model_is_called(self):
        runtime = _r.TextRuntime(self.config())
        core = self.taught_core(self.valid_pattern(), model=runtime)
        self.assertEqual(core.process_input(MESSAGE), LEARNED_TEXT)
        self.assertEqual(runtime.requests, [])

    def test_the_result_is_an_ordinary_generated_result(self):
        _, response, lic = self.generate(self.taught_core(self.valid_pattern()))
        self.assertIsInstance(response, ResponseGenerationResult)
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertTrue(response.is_generated)
        self.assertFalse(response.needs_fallback)
        self.assertIsNone(response.fallback_backend_kind)
        self.assertIsNone(response.inference_status)
        self.assertIsNone(response.error_code)

    def test_the_decision_is_recorded(self):
        _, _, lic = self.generate(self.taught_core(self.valid_pattern()))
        decision = lic.last_learned_response_decision
        self.assertIsInstance(decision, LearnedResponseDecision)
        self.assertTrue(decision.used)
        self.assertEqual((decision.reason, decision.pattern_id), (REASON_USED, "answer_question"))

    def test_the_backend_is_not_selected_or_called(self):
        core = self.taught_core(self.valid_pattern())
        lic = core.language_intelligence
        with mock.patch.object(lic.backend, "generate_response") as backend_call, \
                mock.patch.object(lic, "select_backend") as select:
            understanding = core.understand_language(MESSAGE)
            response = lic.generate_response(understanding, context=core.context)
        backend_call.assert_not_called()
        select.assert_not_called()
        self.assertEqual(response.response_text, LEARNED_TEXT)
        self.assertIsNone(lic.last_backend_selection)


class TestLearnedTextPreservedExactly(_CoreCase):
    def test_text_is_exactly_the_rendered_text(self):
        for template in ("About {{topic}}.", "  spaced {{topic}}  \n", "{{topic}}", "A {{topic}} {{topic}}!",
                         "چرا {{topic}}؟ 😀 $1 \\1 {x}"):
            with self.subTest(template=template):
                _, response, _ = self.generate(self.taught_core(self.valid_pattern(template)))
                self.assertEqual(response.response_text,
                                 template.replace("{{topic}}", "python"))

    def test_process_input_returns_it_unchanged(self):
        core = self.taught_core(self.valid_pattern("  Exactly {{topic}}  "))
        self.assertEqual(core.process_input(MESSAGE), "  Exactly python  ")


class TestSourceIsIdentifiable(_CoreCase):
    def test_result_fields_name_the_learned_source(self):
        _, response, _ = self.generate(self.taught_core(self.valid_pattern()))
        self.assertEqual(response.backend_kind, BACKEND_KIND_LEARNED_RESPONSE)
        self.assertEqual(response.selected_backend_kind, BACKEND_KIND_LEARNED_RESPONSE)
        self.assertEqual(response.metadata["response_source"], RESPONSE_SOURCE_LEARNED_RESPONSE)
        self.assertEqual(response.metadata["pattern_id"], "answer_question")
        self.assertEqual(response.metadata["bound_variables"], {"topic": "python"})

    def test_conversation_response_is_a_normal_success_from_the_learned_source(self):
        _, _, lic = self.generate(self.taught_core(self.valid_pattern()))
        conversation = lic.get_last_conversation_response()
        self.assertIsInstance(conversation, ConversationResponse)
        self.assertEqual(conversation.response_text, LEARNED_TEXT)
        self.assertEqual(conversation.status, STATUS_SUCCESS)
        self.assertEqual(conversation.classification, "NORMAL")
        self.assertEqual(conversation.backend_kind, BACKEND_KIND_LEARNED_RESPONSE)
        self.assertEqual(conversation.selected_backend_kind, BACKEND_KIND_LEARNED_RESPONSE)
        self.assertEqual(conversation.metadata["response_source"], RESPONSE_SOURCE_LEARNED_RESPONSE)
        self.assertFalse(conversation.fallback_used)
        self.assertIsNone(conversation.failure_reason)
        self.assertTrue(conversation.valid)
        self.assertEqual(lic.get_last_response_generation_validation().status, VALIDATION_VALID)
        self.assertEqual(lic.get_last_response_generation_result().status, STATUS_SUCCESS)

    def test_it_is_distinct_from_the_local_model_fallback_and_unresolved(self):
        runtime = _r.TextRuntime(self.config())
        core = self.taught_core(None, model=runtime)
        _, model_response, lic = self.generate(core)
        self.assertEqual(model_response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(lic.get_last_conversation_response().backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertNotIn("response_source", model_response.metadata or {})
        unready = self.taught_core(None, model=_r.TextRuntime(None))
        _, failed, lic2 = self.generate(unready)
        self.assertEqual(lic2.get_last_conversation_response().status, STATUS_FALLBACK)
        self.assertNotEqual(failed.backend_kind, BACKEND_KIND_LEARNED_RESPONSE)
        _, deferred, lic3 = self.generate(self.taught_core(None))
        self.assertEqual(lic3.get_last_conversation_response().status, STATUS_UNRESOLVED)
        self.assertNotEqual(deferred.backend_kind, BACKEND_KIND_LEARNED_RESPONSE)

    def test_the_learned_source_is_not_a_backend(self):
        self.assertNotIn(BACKEND_KIND_LEARNED_RESPONSE, ALL_BACKEND_KINDS)


# ----------------------------------------------------------------------
class TestFallsThroughToExistingPipeline(_CoreCase):
    """9. A learned response is never used for an ambiguous / not found
    selection, an unresolved binding, a failed render or a failed
    validation - the existing pipeline answers."""

    def _falls_through(self, patterns):
        runtime = _r.TextRuntime(self.config())
        core = self.taught_core(patterns, model=runtime)
        reply = core.process_input(MESSAGE)
        self.assertEqual(reply, _r.MODEL_TEXT)
        self.assertEqual(len(runtime.requests), 1)
        response = core.get_last_language_response()
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertNotIn("response_source", response.metadata or {})
        decision = core.language_intelligence.last_learned_response_decision
        self.assertFalse(decision.used)
        return runtime, decision

    def test_ambiguous_pattern_falls_through(self):
        _, decision = self._falls_through([{"id": "one", "template": "One"},
                                           {"id": "two", "template": "Two"}])
        self.assertEqual(decision.reason, REASON_SELECTION_NOT_RESOLVED)

    def test_no_learned_response_falls_through(self):
        _, decision = self._falls_through(None)
        self.assertEqual(decision.reason, REASON_SELECTION_NOT_RESOLVED)

    def test_missing_variable_falls_through(self):
        _, decision = self._falls_through(self.valid_pattern("About {{topic}} for {{audience}}."))
        self.assertEqual(decision.reason, REASON_BINDING_NOT_RESOLVED)

    def test_rendering_failure_falls_through(self):
        _, decision = self._falls_through([{"id": "answer_question"}])  # nothing to render
        self.assertEqual(decision.reason, REASON_RENDERING_NOT_RESOLVED)

    def test_validation_failure_falls_through(self):
        runtime = _r.TextRuntime(self.config())
        core = self.taught_core(self.valid_pattern(), model=runtime)
        invalid = ResponseGenerationValidation(VALIDATION_INVALID, [{"code": "x", "message": "x"}])
        with mock.patch("language_intelligence.learned_response_decision."
                        "validate_response_generation_result", return_value=invalid):
            reply = core.process_input(MESSAGE)
        self.assertEqual(reply, _r.MODEL_TEXT)
        decision = core.language_intelligence.last_learned_response_decision
        self.assertEqual((decision.used, decision.reason), (False, REASON_VALIDATION_FAILED))
        self.assertIsNone(decision.response)

    def test_a_tampered_sub_result_is_never_used(self):
        core = self.taught_core(self.valid_pattern())
        understanding = core.understand_language(MESSAGE)
        for section, status in (("response_pattern_selection", "AMBIGUOUS"),
                                ("response_pattern_binding", "UNRESOLVED"),
                                ("response_pattern_rendering", "UNRESOLVED")):
            with self.subTest(section=section):
                request = ResponseGenerationRequest(understanding).generation_request
                request[section]["status"] = status
                with mock.patch.object(ResponseGenerationRequest, "generation_request",
                                       new_callable=mock.PropertyMock, return_value=request):
                    self.assertFalse(decide_learned_response(understanding).used)

    def test_no_plan_means_no_decision_to_use(self):
        class _NoPlan:
            response_plan = None
            learned_sentence_structure = None
        decision = decide_learned_response(_NoPlan())
        self.assertEqual((decision.used, decision.reason), (False, REASON_NO_REQUEST))

    def test_a_failing_decision_never_breaks_generation(self):
        core = self.taught_core(self.valid_pattern())
        with mock.patch("language_intelligence.language_intelligence_core.decide_learned_response",
                        side_effect=RuntimeError("boom")):
            understanding = core.understand_language(MESSAGE)
            response = core.language_intelligence.generate_response(understanding, context=core.context)
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(core.language_intelligence.last_learned_response_decision)


class TestExistingBehaviourWhenNoLearnedResponse(_CoreCase):
    def test_local_model_remains_usable(self):
        runtime = _r.TextRuntime(self.config())
        core = self.taught_core(None, model=runtime)
        self.assertEqual(core.process_input(MESSAGE), _r.MODEL_TEXT)
        self.assertEqual(len(runtime.requests), 1)
        response = core.get_last_language_response()
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(response.selected_backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertIsNotNone(core.language_intelligence.last_backend_selection)

    def test_deterministic_fallback_remains_usable(self):
        control, _ = _r._core(self)
        expected = control.process_input(_r.MESSAGE)
        core = self.taught_core(None, model=_r.TextRuntime(None))
        self.assertEqual(core.process_input(_r.MESSAGE), expected)
        response = core.get_last_language_response()
        self.assertTrue(response.needs_fallback)
        self.assertIsNone(response.response_text)
        selection = core.language_intelligence.last_backend_selection
        self.assertTrue(selection.fallback_selected)

    def test_the_deterministic_backend_still_defers_with_no_text(self):
        core = self.taught_core(None)
        response = core.generate_language_response(core.understand_language(MESSAGE))
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(response.response_text)

    def test_a_valid_learned_response_answers_even_when_the_model_is_not_ready(self):
        """Additional source, not a replacement: backend selection is not consulted."""
        core = self.taught_core(self.valid_pattern(), model=_r.TextRuntime(None))
        self.assertEqual(core.process_input(MESSAGE), LEARNED_TEXT)
        self.assertFalse(core.get_last_language_response().needs_fallback)

    def test_result_and_conversation_response_shapes_are_unchanged(self):
        keys = {"status", "response_text", "reason", "backend_kind", "inference_status", "error_code",
                "metadata", "fallback_backend_kind", "selected_backend_kind",
                "used_verified_correction"}  # Prompt 500: additive key, always False here
        for patterns in (None, self.valid_pattern()):
            _, response, lic = self.generate(self.taught_core(patterns))
            self.assertEqual(set(response.to_dict()), keys)
            conversation = lic.get_last_conversation_response()
            self.assertIsInstance(conversation, ConversationResponse)
            self.assertEqual(set(conversation.to_dict()), set(
                self.generate(self.taught_core(None))[2].get_last_conversation_response().to_dict()))
            with self.assertRaises(Exception):
                conversation.response_text = "changed"


# ----------------------------------------------------------------------
class TestPreservation(_b._PipelineCase):
    def test_language_locale_and_message_are_preserved(self):
        self.teach(PREFERENCE_PATTERN, language="fa", locale="fa-IR", meaning={
            RESPONSE_PATTERNS_KEY: [{"id": "ask_why", "language": "fa", "locale": "fa-IR",
                                     "template": "چرا {{X}} را دوست داری؟"}]})
        self.bind_meaning(PREFERENCE_PATTERN, "express_preference", language="fa")
        message = "من چای را دوست دارم"
        understanding = self.understand(message, requested_language="fa")
        conversation = self.lic.generate_conversation_response(understanding)
        self.assertEqual(conversation.response_text, "چرا چای را دوست داری؟")
        self.assertEqual((conversation.language, conversation.locale), ("persian", "fa-IR"))
        self.assertEqual(conversation.backend_kind, BACKEND_KIND_LEARNED_RESPONSE)
        meta = conversation.metadata
        self.assertEqual((meta["language"], meta["locale"]), ("persian", "fa-IR"))
        self.assertEqual(meta["original_message"], message)
        self.assertEqual(meta["bound_variables"], {"X": "چای"})
        self.assertEqual(meta["pattern_id"], "ask_why")
        self.assertEqual(understanding.original_text if hasattr(understanding, "original_text")
                         else understanding.response_plan["original_message"], message)

    def test_request_context_and_understanding_are_unchanged_by_the_decision(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "variables": ["topic"], "template": "About {{topic}}."}]})
        understanding = self.understand(MESSAGE)
        plan_before = copy.deepcopy(understanding.response_plan)
        request_before = ResponseGenerationRequest(understanding).generation_request
        context_before = ResponseGenerationRequest(understanding).generation_context
        def stored():
            return copy.deepcopy(self.items.items_for_language("en"))
        items_before = stored()
        self.assertTrue(items_before)
        response = self.lic.generate_response(understanding)
        self.assertEqual(response.response_text, "About python.")
        self.assertEqual(understanding.response_plan, plan_before)
        self.assertEqual(ResponseGenerationRequest(understanding).generation_request, request_before)
        self.assertEqual(ResponseGenerationRequest(understanding).generation_context, context_before)
        for key in ("response_pattern_selection", "response_pattern_binding",
                    "response_pattern_rendering", "language_guidance"):
            self.assertIsNotNone(request_before[key])
        self.assertEqual(request_before["original_message"], MESSAGE)
        self.assertEqual(stored(), items_before)

    def test_repeated_identical_input_gives_the_same_decision(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "template": "About {{topic}}."}]})
        understanding = self.understand(MESSAGE)
        first = decide_learned_response(understanding)
        for _ in range(4):
            again = decide_learned_response(understanding)
            self.assertEqual((again.used, again.reason, again.pattern_id),
                             (first.used, first.reason, first.pattern_id))
            self.assertEqual(again.response.to_dict(), first.response.to_dict())
        results = [self.lic.generate_response(understanding).to_dict() for _ in range(3)]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])
        self.assertEqual(results[0]["response_text"], "About python.")

    def test_a_fresh_understanding_of_the_same_message_gives_the_same_decision(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "template": "About {{topic}}."}]})
        a = decide_learned_response(self.understand(MESSAGE))
        b = decide_learned_response(self.understand(MESSAGE))
        self.assertEqual(a.response.to_dict(), b.response.to_dict())

    def test_a_missing_variable_leaves_the_deterministic_result_untouched(self):
        control = self.lic.generate_response(self.understand(MESSAGE)).to_dict()
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "p", "template": "About {{topic}} for {{audience}}."}]})
        response = self.lic.generate_response(self.understand(MESSAGE))
        self.assertEqual(response.to_dict(), control)
        self.assertEqual(response.status, STATUS_DEFERRED)


if __name__ == "__main__":
    unittest.main()
