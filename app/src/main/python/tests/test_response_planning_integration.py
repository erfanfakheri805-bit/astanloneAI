"""
Tests for Prompt 425 - Structured Response Planning, integration.

The plan (`ResponsePlanner`, language_intelligence/response_planning.py)
is produced by `LanguageIntelligenceCore` for every understanding and
exposed on `understanding.response_plan`. These tests drive it through
the real entry points - `Core.process_input`, `Core.understand_language`,
`Core.use_local_language_model` - and check that nothing existing changed:
the conversation reply, the deterministic fallback, the Local Language
Model path, Conversation Context, and ResponseGeneration. No test double
here produces a plan or a reply for the planner; the only text-producing
double is a scripted local-model runtime (the suite's existing one) and a
tiny backend that reads the plan, to show ResponseGeneration CAN consume it.

Run directly:
    python -m unittest tests.test_response_planning_integration -v
"""

import copy
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine

from language_intelligence.backend import LanguageIntelligenceBackend, BACKEND_KIND_LOCAL_MODEL
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.language_understanding_result import LanguageUnderstandingResult
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult, STATUS_DEFERRED, STATUS_GENERATED,
)
from language_intelligence.response_planning import (
    ResponsePlanner, ResponsePlan, STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED,
    ACTION_GREET, ACTION_PROVIDE_INFORMATION,
)
from language_intelligence.learned_pattern_matching import STATUS_MATCHED
from language_intelligence.learned_pattern_meaning import (
    STATUS_BOUND, STATUS_ALREADY_BOUND,
)
from language_intelligence.learned_pattern_teaching import STATUS_CREATED

from core.core import Core
from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT, _core
from tests.test_local_inference_response_generation import TextRuntime

QUESTION = "what is {{topic}}"
GREETING = "good morning"


class _ExplodingPlanner(ResponsePlanner):
    def plan(self, understanding):
        raise RuntimeError("planner boom")


def _teach(core, pattern, meaning, language="en"):
    assert core.teach_sentence_pattern(language, pattern).status == STATUS_CREATED
    assert core.bind_pattern_meaning(language, pattern, meaning).status in (
        STATUS_BOUND, STATUS_ALREADY_BOUND)


class _CoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.core = self.make_core("core.db")

    def make_core(self, name):
        # no skill definitions: the keyword `greet` skill would otherwise
        # answer greetings before the language pipeline runs
        return Core(memory_db_path=os.path.join(self._tmp.name, name),
                    skill_definitions_dir=os.path.join(self._tmp.name, "skills_" + name))


# ----------------------------------------------------------------------
class TestCoreExposesThePlan(_CoreCase):
    """Integration with the existing language-intelligence / Core flow."""

    def test_core_owns_one_planner_shared_with_the_language_core(self):
        self.assertIsInstance(self.core.response_planner, ResponsePlanner)
        self.assertIs(self.core.language_intelligence.response_planner, self.core.response_planner)

    def test_no_plan_before_any_conversation(self):
        self.assertIsNone(self.core.get_last_response_plan())

    def test_a_learned_greeting_is_planned_through_process_input(self):
        _teach(self.core, GREETING, "greeting")
        self.core.process_input("good morning")
        plan = self.core.get_last_response_plan()
        self.assertEqual(plan["status"], STATUS_RESOLVED)
        self.assertEqual(plan["response_action"], ACTION_GREET)
        self.assertEqual(plan["original_message"], "good morning")
        self.assertEqual(plan, self.core.get_last_language_understanding().response_plan)

    def test_a_learned_question_is_planned_through_process_input(self):
        _teach(self.core, QUESTION, "ask_question")
        self.core.process_input("what is python")
        plan = self.core.get_last_response_plan()
        self.assertEqual(plan["response_action"], ACTION_PROVIDE_INFORMATION)
        self.assertEqual(plan["variables"], {"topic": "python"})
        self.assertEqual(plan["required_items"][0]["query"]["variables"], {"topic": "python"})
        self.assertFalse(plan["required_items"][0]["retrieval"]["performed"])

    def test_plan_language_response_matches_the_attached_plan(self):
        _teach(self.core, QUESTION, "ask_question")
        understanding = self.core.understand_language("what is python")
        plan = self.core.plan_language_response(understanding)
        self.assertIsInstance(plan, ResponsePlan)
        self.assertEqual(plan.to_dict(), understanding.response_plan)

    def test_understand_language_is_still_read_only_and_planned(self):
        _teach(self.core, GREETING, "greeting")
        turns_before = self.core.get_recent_turns()
        understanding = self.core.understand_language("good morning")
        self.assertEqual(understanding.response_plan["response_action"], ACTION_GREET)
        self.assertEqual(self.core.get_recent_turns(), turns_before)
        self.assertIsNone(self.core.get_last_response_plan())   # no conversational turn happened

    def test_ambiguous_and_unknown_messages_keep_their_state_through_core(self):
        self.core.teach_sentence_pattern("en", "thanks {{who}}")
        self.core.bind_pattern_meaning("en", "thanks {{who}}", "gratitude")
        self.core.bind_pattern_meaning("en", "thanks {{who}}", "farewell")
        self.core.process_input("thanks bob")
        ambiguous = self.core.get_last_response_plan()
        self.assertEqual(ambiguous["status"], STATUS_AMBIGUOUS)
        self.assertEqual(len(ambiguous["meaning_candidates"]), 2)
        self.assertTrue(ambiguous["needs_clarification"])
        self.core.process_input("qwerty zzznoxyzzz unmapped concept")
        unknown = self.core.get_last_response_plan()
        self.assertEqual(unknown["status"], STATUS_UNRESOLVED)
        self.assertIsNone(unknown["response_action"])
        self.assertEqual(unknown["required_items"], [])

    def test_ael_input_makes_no_plan(self):
        self.core.process_input("TEACH sun IS a star at the center of the solar system")
        self.assertIsNone(self.core.get_last_response_plan())


# ----------------------------------------------------------------------
class TestConversationContextIsCarried(_CoreCase):
    """Active topic, references and context flow from Core's own computation."""

    def test_topic_reference_and_context_are_the_ones_core_computed(self):
        _teach(self.core, QUESTION, "ask_question")
        self.core.process_input("I love Python")
        self.core.process_input("what is it")
        understanding = self.core.get_last_language_understanding()
        plan = self.core.get_last_response_plan()

        self.assertEqual(plan["active_topic"], understanding.active_topic)
        self.assertIsNotNone(plan["active_topic"]["topic"])
        self.assertEqual(plan["references"], understanding.referenced_items)
        self.assertEqual(plan["references"][0]["reference_text"], "it")
        self.assertEqual(plan["references"][0]["resolved_context"], "I love Python")
        self.assertEqual(plan["context"], understanding.conversation_context)
        self.assertEqual(plan["context"]["selected"][0]["turn"]["user"], "I love Python")

        item = plan["required_items"][0]
        self.assertEqual(item["topic"], plan["active_topic"]["topic"])
        self.assertEqual(item["references"], plan["references"])

    def test_conversation_context_itself_is_unchanged_by_planning(self):
        _teach(self.core, QUESTION, "ask_question")
        self.core.process_input("I love Python")
        self.core.process_input("what is it")
        turns = self.core.get_recent_turns()
        self.core.plan_language_response(self.core.get_last_language_understanding())
        self.assertEqual(self.core.get_recent_turns(), turns)
        self.assertEqual([t["user"] for t in turns], ["I love Python", "what is it"])


# ----------------------------------------------------------------------
class TestFallbackBehaviourIsUnchanged(_CoreCase):
    """The reply is whatever the existing pipeline produced; planning
    neither adds text nor changes it - not even when planning fails."""

    MESSAGES = ("I love Python", "what is python", "qwerty zzznoxyzzz unmapped concept",
                "good morning", "what is it")

    def run_conversation(self, core):
        return [core.process_input(text) for text in self.MESSAGES]

    def test_replies_are_identical_with_a_failing_planner(self):
        _teach(self.core, QUESTION, "ask_question")
        _teach(self.core, GREETING, "greeting")
        control = self.make_core("control.db")
        _teach(control, QUESTION, "ask_question")
        _teach(control, GREETING, "greeting")
        control.language_intelligence.response_planner = _ExplodingPlanner()

        planned = self.run_conversation(self.core)
        unplanned = self.run_conversation(control)
        self.assertEqual(planned, unplanned)
        self.assertIsNone(control.get_last_response_plan())

    def test_a_failing_planner_never_breaks_understanding(self):
        self.core.language_intelligence.response_planner = _ExplodingPlanner()
        understanding = self.core.understand_language("what is python")
        self.assertIsNone(understanding.response_plan)
        self.assertTrue(any(w.startswith("response_plan_error: planner boom")
                            for w in understanding.warnings))
        self.assertEqual(understanding.original_input, "what is python")
        self.assertIsNone(self.core.language_intelligence.last_response_plan)

    def test_the_deterministic_fallback_reply_is_not_replaced_by_plan_text(self):
        _teach(self.core, GREETING, "greeting")
        reply = self.core.process_input("good morning")
        self.assertIsInstance(reply, str)
        self.assertNotIn("greet", reply.lower().split())
        response = self.core.get_last_language_response()
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(response.response_text)
        self.assertFalse(response.is_generated)


# ----------------------------------------------------------------------
class _LocalPath(GuardCase):
    def core(self):
        core, _ = _core(self)
        return core


class TestLocalLanguageModelPath(_LocalPath):
    """The Local Language Model path keeps working and its understanding is planned too."""

    def test_use_local_language_model_keeps_the_same_planner(self):
        core = self.core()
        core.use_local_language_model(runtime=TextRuntime(self.config()))
        self.assertIs(core.language_intelligence.response_planner, core.response_planner)
        self.assertEqual(core.language_intelligence.backend_kind, BACKEND_KIND_LOCAL_MODEL)

    def test_ready_model_reply_is_untouched_and_the_understanding_is_planned(self):
        core = self.core()
        _teach(core, QUESTION, "ask_question")
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        reply = core.process_input("what is python")
        self.assertEqual(reply, MODEL_TEXT)                        # the model's text, verbatim
        self.assertEqual(runtime.requests[0].user_input, "what is python")
        plan = core.get_last_response_plan()
        self.assertEqual(plan["status"], STATUS_RESOLVED)
        self.assertEqual(plan["response_action"], ACTION_PROVIDE_INFORMATION)
        self.assertNotIn(MODEL_TEXT, str(plan))                    # nothing flows back into the plan

    def test_the_plan_is_not_sent_to_the_model(self):
        core = self.core()
        _teach(core, QUESTION, "ask_question")
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        core.process_input("what is python")
        request = runtime.requests[0]
        for value in (request.user_input, request.system_prompt or ""):
            self.assertNotIn("response_action", value)
        self.assertNotIn("provide_information", str(request.conversation))

    def test_model_not_configured_falls_back_and_is_still_planned(self):
        control, _ = _core(self)
        expected = control.process_input(MESSAGE)
        core = self.core()
        _teach(core, QUESTION, "ask_question")
        core.use_local_language_model(runtime=TextRuntime(None))
        self.assertEqual(core.process_input(MESSAGE), expected)   # existing fallback reply
        plan = core.get_last_response_plan()
        self.assertEqual(plan["status"], STATUS_UNRESOLVED)
        self.assertIsNone(plan["response_action"])
        response = core.get_last_language_response()
        self.assertTrue(response.needs_fallback)
        self.assertIsNone(response.response_text)

    def test_model_not_configured_still_plans_a_learned_message(self):
        core = self.core()
        _teach(core, GREETING, "greeting")
        core.use_local_language_model(runtime=TextRuntime(None))
        core.process_input("good morning")
        self.assertEqual(core.get_last_response_plan()["response_action"], ACTION_GREET)


# ----------------------------------------------------------------------
class _PlanReadingBackend(LanguageIntelligenceBackend):
    """Test double: understands like the deterministic backend and, when
    asked to generate, reads ONLY the plan attached to the understanding
    it is handed - the way a future generating backend would."""

    def __init__(self, inner):
        self.inner = inner

    @property
    def backend_kind(self):
        return "deterministic_fallback"

    def understand(self, raw_text, **kwargs):
        return self.inner.understand(raw_text, **kwargs)

    def generate_response(self, understanding, context=None, cancellation_token=None):
        plan = ResponseGenerationRequest(understanding, context).response_plan
        action = plan["response_action"] if plan else None
        return ResponseGenerationResult(
            status=STATUS_GENERATED, response_text=f"<action:{action}>",
            reason="test double", backend_kind=self.backend_kind)


class TestExistingResponseGeneration(_CoreCase):
    """The plan is prepared for ResponseGeneration; ResponseGeneration is unchanged."""

    def setUp(self):
        super().setUp()
        _teach(self.core, GREETING, "greeting")

    def test_deterministic_generation_is_still_deferred_with_no_text(self):
        understanding = self.core.understand_language("good morning")
        response = self.core.generate_language_response(understanding)
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(response.response_text)
        self.assertEqual(response.backend_kind, "deterministic_fallback")

    def test_generation_result_is_identical_with_and_without_a_plan(self):
        with_plan = self.core.understand_language("good morning")
        without_plan = copy.copy(with_plan)
        without_plan.response_plan = None
        a = self.core.generate_language_response(with_plan).to_dict()
        b = self.core.generate_language_response(without_plan).to_dict()
        self.assertEqual(a, b)

    def test_the_plan_never_contains_generated_text(self):
        understanding = self.core.understand_language("good morning")
        plan = understanding.response_plan
        self.assertNotIn("response_text", plan)
        self.assertNotIn("Hello", str(plan))

    def test_the_request_holder_exposes_the_plan(self):
        understanding = self.core.understand_language("good morning")
        request = ResponseGenerationRequest(understanding, context=self.core.context)
        self.assertEqual(request.response_plan, understanding.response_plan)
        self.assertEqual(request.response_plan["response_action"], ACTION_GREET)
        self.assertIsNone(ResponseGenerationRequest(object()).response_plan)

    def test_a_generating_backend_can_consume_the_plan_through_the_language_core(self):
        inner = self.core.language_intelligence.backend
        lic = LanguageIntelligenceCore(backend=_PlanReadingBackend(inner))
        understanding = lic.understand("good morning")   # the backend never planned; the core did
        self.assertEqual(understanding.response_plan["response_action"], ACTION_GREET)
        response = lic.generate_response(understanding)
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(response.response_text, "<action:greet>")

    def test_that_generated_text_becomes_the_reply_through_the_existing_path(self):
        inner = self.core.language_intelligence.backend
        self.core.language_intelligence = LanguageIntelligenceCore(
            backend=_PlanReadingBackend(inner))
        self.assertEqual(self.core.process_input("good morning"), "<action:greet>")


# ----------------------------------------------------------------------
class TestLanguageCoreRobustness(unittest.TestCase):
    """The language core plans what it is given, and leaves alone what it cannot."""

    def setUp(self):
        self.backend = DeterministicFallbackBackend(UnderstandingEngine())

    def test_a_directly_built_understanding_has_no_plan(self):
        bare = self.backend.understand("hello world")
        self.assertIsNone(bare.response_plan)
        self.assertIn("response_plan", bare.to_dict())
        self.assertIsNone(bare.to_dict()["response_plan"])

    def test_a_result_that_is_not_an_understanding_is_returned_untouched(self):
        sentinel = object()

        class Odd(LanguageIntelligenceBackend):
            backend_kind = "deterministic_fallback"

            def understand(self, raw_text, **kwargs):
                return sentinel

        lic = LanguageIntelligenceCore(backend=Odd())
        self.assertIs(lic.understand("hello"), sentinel)
        self.assertIsNone(lic.last_response_plan)

    def test_a_backend_supplied_plan_is_kept(self):
        marker = {"status": "RESOLVED", "from": "backend"}

        class Planning(DeterministicFallbackBackend):
            def understand(inner, raw_text, **kwargs):
                result = super().understand(raw_text, **kwargs)
                result.response_plan = marker
                return result

        lic = LanguageIntelligenceCore(backend=Planning(UnderstandingEngine()))
        self.assertIs(lic.understand("hello").response_plan, marker)

    def test_the_fallback_backends_understanding_is_planned_too(self):
        class Failing(LanguageIntelligenceBackend):
            backend_kind = BACKEND_KIND_LOCAL_MODEL

            def understand(self, raw_text, **kwargs):
                raise RuntimeError("understanding not implemented")

        lic = LanguageIntelligenceCore(backend=Failing(), fallback_backend=self.backend)
        understanding = lic.understand("hello world")
        self.assertEqual(lic.last_understanding_fallback, "RuntimeError")
        self.assertEqual(understanding.source_backend, "deterministic_fallback")
        self.assertEqual(understanding.response_plan["status"], STATUS_UNRESOLVED)

    def test_without_a_fallback_a_failing_backend_still_raises_as_before(self):
        class Failing(LanguageIntelligenceBackend):
            backend_kind = BACKEND_KIND_LOCAL_MODEL

            def understand(self, raw_text, **kwargs):
                raise RuntimeError("understanding not implemented")

        with self.assertRaises(RuntimeError):
            LanguageIntelligenceCore(backend=Failing()).understand("hello")

    def test_plan_response_raises_for_a_bad_value_unlike_automatic_planning(self):
        lic = LanguageIntelligenceCore(backend=self.backend)
        with self.assertRaises(TypeError):
            lic.plan_response("not an understanding")


# ----------------------------------------------------------------------
class TestPrompts421To424Regression(_CoreCase):
    """The plan is additive: what Prompts 421-424 report is exactly as before."""

    def setUp(self):
        super().setUp()
        self.core.teach_sentence_pattern("fa", "من {{X}} را دوست دارم", locale="fa-IR",
                                         meaning={"intent": "likes_thing"})
        self.core.bind_pattern_meaning("fa", "من {{X}} را دوست دارم", "express_preference",
                                       locale="fa-IR", examples=["من کتاب را دوست دارم"])
        _teach(self.core, QUESTION, "ask_question")
        self.core.learn_language_item("english", "word", "python", meaning={"gloss": "a language"})

    def unplanned(self, text):
        """The same understanding, without the Prompt 425 step at all."""
        return self.core.language_intelligence.backend.understand(text)

    def test_every_earlier_field_is_identical_with_and_without_the_plan(self):
        for text in ("من چای را دوست دارم", "what is python", "nothing learned here"):
            planned = self.core.understand_language(text, use_context=False).to_dict()
            plain = self.unplanned(text).to_dict()
            self.assertIsNotNone(planned.pop("response_plan"), text)
            plain.pop("response_plan")
            self.assertEqual(planned, plain, text)

    def test_421_pattern_match_is_untouched_and_agrees_with_the_plan(self):
        understanding = self.core.understand_language("من چای را دوست دارم", use_context=False)
        match = understanding.learned_pattern_match
        self.assertEqual(match["status"], STATUS_MATCHED)
        self.assertEqual(match["variables"], {"X": "چای"})
        self.assertEqual(match["meaning"], {"intent": "likes_thing", "locale": "fa-IR"})
        plan = understanding.response_plan
        self.assertEqual(plan["matched_pattern"]["pattern_id"], match["matched_pattern_id"])
        self.assertEqual(plan["variables"], match["variables"])
        # the pattern's own stored meaning is reported as taught, not as an action
        self.assertEqual(plan["matched_pattern"]["meaning"], match["meaning"])
        self.assertIsNone(plan["response_action"])

    def test_422_structure_is_untouched(self):
        understanding = self.core.understand_language("من چای را دوست دارم", use_context=False)
        structure = understanding.learned_sentence_structure
        self.assertEqual([c["kind"] for c in structure["components"]],
                         ["fixed", "variable", "fixed"])
        self.assertEqual(structure["original_message"], "من چای را دوست دارم")
        self.assertEqual(understanding.response_plan["locale"], structure["locale"])

    def test_423_teaching_and_424_binding_results_are_unchanged(self):
        again = self.core.teach_sentence_pattern("fa", "من {{X}} را دوست دارم")
        self.assertEqual(again.status, "ALREADY_EXISTS")
        rebound = self.core.bind_pattern_meaning("fa", "من {{X}} را دوست دارم",
                                                 "express_preference")
        self.assertEqual(rebound.status, STATUS_ALREADY_BOUND)
        invalid = self.core.teach_sentence_pattern("fa", "{{X}}")
        self.assertEqual(invalid.status, "INVALID")

    def test_424_resolution_is_untouched_and_agrees_with_the_plan(self):
        understanding = self.core.understand_language("من چای را دوست دارم", use_context=False)
        direct = self.core.resolve_pattern_meaning("من چای را دوست دارم", language="fa")
        meaning = understanding.learned_pattern_meaning
        self.assertEqual(meaning["status"], direct.status)
        self.assertEqual(meaning["meaning_name"], "express_preference")
        self.assertEqual(understanding.response_plan["meaning"], meaning["meaning"])
        self.assertEqual(understanding.response_plan["reason"], meaning["reason"])

    def test_419_420_learned_and_disambiguated_meanings_are_untouched(self):
        understanding = self.core.understand_language("what is python", use_context=False)
        self.assertEqual([m["expression"].lower() for m in understanding.learned_meanings
                          if m["status"] == "RESOLVED"], ["python"])
        self.assertEqual(understanding.disambiguated_meanings[0]["status"], "RESOLVED")
        plan_entry = understanding.response_plan["expression_meanings"][0]
        self.assertEqual(plan_entry["resolved_meaning"],
                         understanding.disambiguated_meanings[0]["resolved_meaning"])

    def test_planning_writes_nothing_to_learning_or_memory(self):
        def counts():
            return {t: self.core.memory.query_one(f"SELECT COUNT(*) AS c FROM {t}")["c"]
                    for t in ("language_learning_items", "language_item_relationships",
                              "learning_events")}
        understanding = self.core.understand_language("what is python", use_context=False)
        before = counts()
        for _ in range(3):
            self.core.plan_language_response(understanding)
            self.core.understand_language("what is python", use_context=False)
        self.assertEqual(counts(), before)


if __name__ == "__main__":
    unittest.main()
