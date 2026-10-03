"""
Tests for Prompt 426 - Response Generation Context.

`build_generation_context()` (language_intelligence/
response_generation_context.py) turns the existing structured
`ResponsePlan` (Prompt 425) into a small, bounded, read-only
`ResponseGenerationContext` a language backend's generation path can
read - never response text, never a second planning system. Every
meaning/pattern/topic/reference asserted below was taught, bound or
supplied by the test itself; the bridge is only ever shown to carry
values the plan already had, never to add one.

Unit-level tests build a real `ResponsePlan` the same way
test_response_planning.py does (a real Understanding Engine + a real
`DeterministicFallbackBackend`/`LanguageIntelligenceCore`, teaching
patterns/meanings through the real Prompt 416-424 stores) and then
build a generation context from it. Integration-level tests
(`TestResponseGenerationIntegration`, `TestLocalModelPathReceivesContext`,
`TestRegressionPrompts421To425`) drive the real `Core` entry points to
confirm ResponseGeneration, the Local Language Model path, the
deterministic fallback, and Prompts 421-425 are all unaffected.

Run directly:
    python -m unittest tests.test_response_generation_context -v
"""

import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine
from context.active_topic import ActiveTopicResult
from context.message_reference_resolution import ResolvedReference
from context.relevance import select_relevant_turns

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from language_intelligence.language_learning_store import LanguageLearningStore
from language_intelligence.language_relationships import LanguageRelationshipStore
from language_intelligence.meaning_resolution import MeaningResolver
from language_intelligence.learned_meaning_disambiguation import LearnedMeaningDisambiguator
from language_intelligence.learned_pattern_matching import LearnedPatternMatcher
from language_intelligence.learned_sentence_structure import LearnedSentenceStructureExtractor
from language_intelligence.learned_pattern_teaching import LearnedPatternTeacher, STATUS_CREATED
from language_intelligence.learned_pattern_meaning import LearnedPatternMeaningBinder
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.response_planning import (
    ResponsePlanner, ResponsePlan, STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED,
    ACTION_GREET, ACTION_PROVIDE_INFORMATION,
)
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult, STATUS_DEFERRED, STATUS_GENERATED,
)
from language_intelligence.response_generation_context import (
    ResponseGenerationContext, build_generation_context, generation_context_from_understanding,
)
from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL

from core.core import Core
from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT, _core
from tests.test_local_inference_response_generation import TextRuntime

GREETING_PATTERN = "good morning"
QUESTION_PATTERN = "what is {{topic}}"


def _bare_plan_kwargs():
    """A minimal, valid set of `ResponsePlan` constructor kwargs with no
    `normalized_input` supplied - the SAME "hand-built plan" posture
    other test modules' `_base_plan_kwargs()` helpers already use (see
    e.g. test_correction_aware_response_decision_prompt574.py)."""
    return dict(
        original_message="hi", detected_language="english", locale=None,
        status=STATUS_UNRESOLVED, reason=None, needs_clarification=False,
        response_action=None, response_action_source=None,
        meaning=None, meaning_candidates=[], matched_pattern=None,
        pattern_candidates=[], variables={}, expression_meanings=[],
        active_topic=None, references=[], context=None, required_items=[],
        unresolved_requirements=[], understanding_state={}, warnings=[])


# ----------------------------------------------------------------------
class _PlanCase(unittest.TestCase):
    """Same composition test_response_planning.py's _PlanCase builds -
    a real Understanding Engine, real Prompt 416-424 stores, a
    deterministic backend wired to them, and a LanguageIntelligenceCore
    (which plans every understanding it returns)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.memory = MemorySystem(os.path.join(self._tmpdir.name, "memory.db"))
        self.items = LanguageLearningStore(self.memory)
        self.knowledge = KnowledgeSystem(self.memory)
        self.rels = LanguageRelationshipStore(self.memory, self.items, self.knowledge)
        self.resolver = MeaningResolver(self.items, self.rels, knowledge=self.knowledge)
        self.disambiguator = LearnedMeaningDisambiguator()
        self.matcher = LearnedPatternMatcher(self.items)
        self.extractor = LearnedSentenceStructureExtractor(self.matcher)
        self.teacher = LearnedPatternTeacher(self.items)
        self.binder = LearnedPatternMeaningBinder(self.items, self.rels, self.disambiguator)
        self.backend = DeterministicFallbackBackend(
            UnderstandingEngine(), meaning_resolver=self.resolver,
            meaning_disambiguator=self.disambiguator, pattern_matcher=self.matcher,
            structure_extractor=self.extractor, pattern_meaning_binder=self.binder)
        self.planner = ResponsePlanner()
        self.lic = LanguageIntelligenceCore(backend=self.backend, response_planner=self.planner)

    def teach(self, pattern, language="en", **kwargs):
        result = self.teacher.teach(language, pattern, **kwargs)
        self.assertEqual(result.status, STATUS_CREATED, result.errors)
        return result

    def bind(self, pattern, meaning, language="en", **kwargs):
        result = self.binder.bind(language, pattern, meaning, **kwargs)
        self.assertTrue(result.success, result.errors)
        return result

    def teach_and_bind(self, pattern, meaning, language="en", **kwargs):
        self.teach(pattern, language)
        return self.bind(pattern, meaning, language, **kwargs)

    def understand(self, text, **context):
        return self.lic.understand(text, **context)

    def plan(self, text, **context):
        understanding = self.understand(text, **context)
        return understanding, self.planner.plan(understanding)

    def context_for(self, text, **overrides):
        """(understanding, plan, generation_context) triple."""
        understanding, plan = self.plan(text, **overrides)
        return understanding, plan, build_generation_context(plan)


# ----------------------------------------------------------------------
class TestResponsePlanToGenerationContext(_PlanCase):
    """1. A ResponsePlan produces a ResponseGenerationContext."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")

    def test_build_from_a_live_response_plan_object(self):
        _, plan, ctx = self.context_for("what is python")
        self.assertIsInstance(plan, ResponsePlan)
        self.assertIsInstance(ctx, ResponseGenerationContext)

    def test_build_from_the_plans_to_dict(self):
        _, plan, _ = self.context_for("what is python")
        ctx = build_generation_context(plan.to_dict())
        self.assertEqual(ctx.status, STATUS_RESOLVED)
        self.assertEqual(ctx.response_action, ACTION_PROVIDE_INFORMATION)

    def test_generation_context_from_understanding_reads_the_attached_plan(self):
        understanding = self.understand("what is python")
        ctx = generation_context_from_understanding(understanding)
        self.assertIsInstance(ctx, ResponseGenerationContext)
        self.assertEqual(ctx.status, understanding.response_plan["status"])

    def test_generation_context_from_understanding_is_none_without_a_plan(self):
        understanding = self.backend.understand("what is python")  # never planned
        self.assertIsNone(understanding.response_plan)
        self.assertIsNone(generation_context_from_understanding(understanding))

    def test_a_non_plan_non_dict_raises_type_error(self):
        with self.assertRaises(TypeError):
            build_generation_context(object())

    def test_the_context_is_json_shaped(self):
        _, _, ctx = self.context_for("what is python")
        json.dumps(ctx.to_dict(), ensure_ascii=False)

    def test_resolved_ambiguous_unresolved_properties_match_status(self):
        _, _, ctx = self.context_for("what is python")
        self.assertTrue(ctx.resolved)
        self.assertFalse(ctx.ambiguous)
        self.assertFalse(ctx.unresolved)


# ----------------------------------------------------------------------
class TestOriginalMessagePreservation(_PlanCase):
    """2. The original message is preserved exactly, never normalized."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_verbatim_original_message(self):
        text = "  Good   Morning!! \n"
        understanding, plan, ctx = self.context_for(text)
        self.assertEqual(ctx.original_message, text)
        self.assertEqual(ctx.original_message, plan.original_message)
        self.assertEqual(ctx.original_message, understanding.original_input)
        self.assertNotEqual(ctx.original_message, understanding.normalized_input)


# ----------------------------------------------------------------------
class TestResponseActionPreservation(_PlanCase):
    """3. The response action is preserved, never invented."""

    def test_greet_action_is_preserved(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        _, plan, ctx = self.context_for("good morning")
        self.assertEqual(ctx.response_action, ACTION_GREET)
        self.assertEqual(ctx.response_action, plan.response_action)

    def test_provide_information_action_is_preserved(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan, ctx = self.context_for("what is python")
        self.assertEqual(ctx.response_action, ACTION_PROVIDE_INFORMATION)
        self.assertEqual(ctx.response_action, plan.response_action)

    def test_a_taught_action_passes_through_unchanged(self):
        self.teach(GREETING_PATTERN, meaning={"response_action": "wave"})
        self.bind(GREETING_PATTERN, "wave_hello")
        _, plan, ctx = self.context_for("good morning")
        self.assertEqual(ctx.response_action, "wave")
        self.assertEqual(ctx.response_action, plan.response_action)

    def test_no_action_is_invented_for_an_unresolved_plan(self):
        self.teach(QUESTION_PATTERN)  # matched, never bound to a meaning
        _, plan, ctx = self.context_for("what is python")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertIsNone(ctx.response_action)

    def test_no_action_is_invented_for_a_resolved_plan_with_no_taught_action(self):
        self.teach_and_bind(QUESTION_PATTERN, "some_unmapped_meaning_name")
        _, plan, ctx = self.context_for("what is python")
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertIsNone(ctx.response_action)


# ----------------------------------------------------------------------
class TestMeaningPreservation(_PlanCase):
    """4. The resolved meaning/intention is preserved verbatim."""

    def test_the_bound_meaning_is_preserved(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question", source="unit-test")
        understanding, plan, ctx = self.context_for("what is python")
        self.assertEqual(ctx.meaning, plan.meaning)
        self.assertEqual(ctx.meaning, understanding.learned_pattern_meaning["meaning"])
        self.assertEqual(ctx.meaning["meaning_name"], "ask_question")

    def test_matched_pattern_is_preserved(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan, ctx = self.context_for("what is python")
        self.assertEqual(ctx.matched_pattern, plan.matched_pattern)
        self.assertEqual(ctx.matched_pattern["pattern_text"], QUESTION_PATTERN)

    def test_no_meaning_or_pattern_for_a_fully_unresolved_message(self):
        _, plan, ctx = self.context_for("qwerty zzznoxyzzz unmapped concept")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertIsNone(ctx.meaning)
        self.assertIsNone(ctx.matched_pattern)


# ----------------------------------------------------------------------
class TestMeaningCandidatesPreservation(_PlanCase):
    """5. Meaning candidates are preserved, none silently picked."""

    def test_ambiguous_candidates_are_all_kept(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        _, plan, ctx = self.context_for("thanks bob")
        self.assertEqual(plan.status, STATUS_AMBIGUOUS)
        self.assertEqual(ctx.status, STATUS_AMBIGUOUS)
        self.assertEqual(ctx.meaning_candidates, plan.meaning_candidates)
        self.assertEqual(len(ctx.meaning_candidates), 2)
        self.assertIsNone(ctx.response_action)   # never a winner picked

    def test_no_candidates_for_a_resolved_plan(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, _, ctx = self.context_for("what is python")
        self.assertEqual(ctx.meaning_candidates, [])


# ----------------------------------------------------------------------
class TestExtractedVariablesPreservation(_PlanCase):
    """6. Extracted variables are preserved, verbatim."""

    def test_variables_are_carried_through(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        understanding, plan, ctx = self.context_for("what is machine learning")
        self.assertEqual(ctx.variables, {"topic": "machine learning"})
        self.assertEqual(ctx.variables, plan.variables)
        self.assertEqual(ctx.variables, understanding.learned_pattern_match["variables"])

    def test_variables_are_kept_for_an_ambiguous_plan(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        _, plan, ctx = self.context_for("thanks bob")
        self.assertEqual(plan.status, STATUS_AMBIGUOUS)
        self.assertEqual(ctx.variables, {"who": "bob"})

    def test_no_variable_is_invented(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        _, _, ctx = self.context_for("good morning")
        self.assertEqual(ctx.variables, {})


# ----------------------------------------------------------------------
class TestTopicAndReferencePreservation(_PlanCase):
    """7. Active topic and references are preserved."""

    TURNS = [{"user": "I love Python", "assistant": "Noted."}]

    def setUp(self):
        super().setUp()
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        self.topic = ActiveTopicResult("python", "current_input", 0.7, True, None, "first_topic")
        self.relevant = select_relevant_turns("what is it", self.TURNS)
        self.reference = ResolvedReference(True, "it", "I love Python", 0.9, False, "resolved")

    def context_kwargs(self, **overrides):
        values = dict(active_topic=self.topic, relevant_context=self.relevant,
                      resolved_reference=self.reference)
        values.update(overrides)
        return values

    def test_active_topic_is_preserved(self):
        understanding, plan, ctx = self.context_for("what is it", **self.context_kwargs())
        self.assertEqual(ctx.active_topic, plan.active_topic)
        self.assertEqual(ctx.active_topic, understanding.active_topic)
        self.assertEqual(ctx.active_topic["topic"], "python")

    def test_no_topic_is_invented(self):
        _, _, ctx = self.context_for("what is python")
        self.assertIsNone(ctx.active_topic)

    def test_references_are_preserved(self):
        understanding, plan, ctx = self.context_for("what is it", **self.context_kwargs())
        self.assertEqual(ctx.references, plan.references)
        self.assertEqual(ctx.references, understanding.referenced_items)
        self.assertEqual(ctx.references[0]["reference_text"], "it")

    def test_no_reference_is_invented(self):
        _, _, ctx = self.context_for("what is python")
        self.assertEqual(ctx.references, [])

    def test_relevant_conversation_context_is_preserved(self):
        understanding, plan, ctx = self.context_for("what is it", **self.context_kwargs())
        self.assertEqual(ctx.context, plan.context)
        self.assertEqual(ctx.context, understanding.conversation_context)
        self.assertEqual(ctx.context["selected"][0]["turn"]["user"], "I love Python")

    def test_no_context_is_invented(self):
        _, _, ctx = self.context_for("what is python")
        self.assertIsNone(ctx.context)

    def test_unresolved_requirements_of_an_ambiguous_reference_are_preserved(self):
        ambiguous = ResolvedReference(True, "it", None, 0.4, True, "two_candidates")
        understanding, plan, ctx = self.context_for(
            "what is it", **self.context_kwargs(resolved_reference=ambiguous))
        self.assertEqual(ctx.unresolved_requirements, plan.unresolved_requirements)
        self.assertTrue(any(r["kind"] == "reference" for r in ctx.unresolved_requirements))


# ----------------------------------------------------------------------
class TestLanguageAndLocalePreservation(_PlanCase):
    """8. Language and locale are preserved, never derived from one another."""

    def test_language_and_locale_of_an_english_message(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question", locale="en-US")
        understanding, plan, ctx = self.context_for("what is python")
        self.assertEqual(ctx.language, plan.detected_language)
        self.assertEqual(ctx.language, understanding.detected_language)
        self.assertEqual(ctx.locale, plan.locale)

    def test_no_locale_is_derived_from_the_language(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")   # no locale ever taught
        _, plan, ctx = self.context_for("good morning")
        self.assertIsNone(plan.locale)
        self.assertIsNone(ctx.locale)
        self.assertIsNotNone(ctx.language)


# ----------------------------------------------------------------------
class TestAmbiguousPlanPreservation(_PlanCase):
    """9. An AMBIGUOUS plan's state is preserved end to end."""

    def test_ambiguous_status_and_no_response_action(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        _, plan, ctx = self.context_for("thanks bob")
        self.assertEqual(ctx.status, STATUS_AMBIGUOUS)
        self.assertTrue(ctx.ambiguous)
        self.assertFalse(ctx.resolved)
        self.assertFalse(ctx.unresolved)
        self.assertIsNone(ctx.response_action)
        self.assertIsNone(ctx.meaning)
        self.assertEqual(len(ctx.meaning_candidates), 2)

    def test_ambiguous_pattern_candidates_do_not_leak_a_meaning(self):
        self.teach("thanks {{who}}")
        self.teach("thanks {{who}} very much")
        _, plan, ctx = self.context_for("thanks bob very much")
        # either genuinely AMBIGUOUS or UNRESOLVED depending on the match -
        # either way, never RESOLVED with an invented meaning
        self.assertIn(ctx.status, (STATUS_AMBIGUOUS, STATUS_UNRESOLVED))
        self.assertIsNone(ctx.response_action)
        self.assertIsNone(ctx.meaning)


# ----------------------------------------------------------------------
class TestUnresolvedPlanPreservation(_PlanCase):
    """10. An UNRESOLVED plan's state is preserved end to end."""

    def test_unresolved_status_and_no_response_action(self):
        _, plan, ctx = self.context_for("qwerty zzznoxyzzz unmapped concept")
        self.assertEqual(ctx.status, STATUS_UNRESOLVED)
        self.assertTrue(ctx.unresolved)
        self.assertFalse(ctx.resolved)
        self.assertFalse(ctx.ambiguous)
        self.assertIsNone(ctx.response_action)
        self.assertIsNone(ctx.meaning)
        self.assertEqual(ctx.meaning_candidates, [])

    def test_unresolved_because_the_pattern_has_no_bound_meaning(self):
        self.teach(QUESTION_PATTERN)  # matched, never bound
        _, plan, ctx = self.context_for("what is python")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertEqual(ctx.status, STATUS_UNRESOLVED)
        self.assertIsNone(ctx.response_action)
        self.assertEqual(ctx.variables, {"topic": "python"})  # variables still kept
        self.assertIsNotNone(ctx.matched_pattern)              # the match itself is kept


# ----------------------------------------------------------------------
class TestBoundedContext(_PlanCase):
    """11. The generation context stays bounded - no unlimited history,
    no memory-database duplication, nothing beyond the plan's own
    already-bounded lists."""

    def test_no_conversation_history_field_exists(self):
        understanding, plan, ctx = self.context_for("what is python")
        as_dict = ctx.to_dict()
        self.assertNotIn("conversation_history", as_dict)
        self.assertNotIn("memory", as_dict)
        self.assertNotIn("knowledge", as_dict)

    def test_context_is_exactly_the_planners_own_bounded_context(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        turns = [{"user": f"turn {i}", "assistant": "ok"} for i in range(50)]
        relevant = select_relevant_turns("what is it", turns)
        understanding, plan, ctx = self.context_for("what is it", relevant_context=relevant)
        # whatever the existing relevance selection bounded it to, the
        # generation context carries the SAME thing, never more
        self.assertEqual(ctx.context, plan.context)
        self.assertEqual(ctx.context, relevant.to_dict())

    def test_meaning_candidates_are_the_plans_own_bounded_list(self):
        self.teach("thanks {{who}}")
        for i in range(3):
            self.bind("thanks {{who}}", f"meaning_{i}")
        _, plan, ctx = self.context_for("thanks bob")
        self.assertEqual(ctx.meaning_candidates, plan.meaning_candidates)
        self.assertLessEqual(len(ctx.meaning_candidates), len(plan.meaning_candidates))

    def test_unresolved_requirements_are_the_plans_own_bounded_list(self):
        _, plan, ctx = self.context_for("qwerty zzznoxyzzz unmapped concept")
        self.assertEqual(ctx.unresolved_requirements, plan.unresolved_requirements)


# ----------------------------------------------------------------------
class TestMutableStateIsolation(_PlanCase):
    """12. No mutable-state leakage in either direction."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")

    def test_mutating_the_returned_dict_never_touches_the_context(self):
        _, plan, ctx = self.context_for("what is python")
        first = ctx.to_dict()
        first["variables"]["topic"] = "HIJACKED"
        first["unresolved_requirements"].append({"kind": "fake"})
        second = ctx.to_dict()
        self.assertEqual(second["variables"], {"topic": "python"})
        self.assertEqual(second["unresolved_requirements"], [])

    def test_mutating_the_context_object_never_touches_the_plan(self):
        understanding, plan, ctx = self.context_for("what is python")
        ctx.variables["topic"] = "HIJACKED"
        ctx.references.append({"fake": True})
        self.assertEqual(plan.variables, {"topic": "python"})
        self.assertEqual(plan.references, [])
        self.assertEqual(understanding.response_plan["variables"], {"topic": "python"})

    def test_mutating_the_context_object_never_touches_the_understanding(self):
        understanding, plan, ctx = self.context_for("what is python")
        if ctx.meaning is not None:
            ctx.meaning["meaning_name"] = "HIJACKED"
        self.assertEqual(
            understanding.learned_pattern_meaning["meaning"]["meaning_name"], "ask_question")

    def test_mutating_the_source_plan_dict_after_building_never_touches_the_context(self):
        _, plan, _ = self.context_for("what is python")
        plan_dict = plan.to_dict()
        ctx = build_generation_context(plan_dict)
        plan_dict["variables"]["topic"] = "HIJACKED"
        plan_dict["status"] = "TOTALLY_DIFFERENT"
        self.assertEqual(ctx.variables, {"topic": "python"})
        self.assertEqual(ctx.status, STATUS_RESOLVED)

    def test_mutating_a_live_response_plan_after_building_never_touches_the_context(self):
        _, plan, _ = self.context_for("what is python")
        ctx = build_generation_context(plan)
        plan.variables["topic"] = "HIJACKED"
        plan.status = "TOTALLY_DIFFERENT"
        self.assertEqual(ctx.variables, {"topic": "python"})
        self.assertEqual(ctx.status, STATUS_RESOLVED)

    def test_two_builds_from_the_same_plan_share_no_mutable_object(self):
        _, plan, _ = self.context_for("what is python")
        a = build_generation_context(plan)
        b = build_generation_context(plan)
        a.variables["topic"] = "HIJACKED"
        self.assertEqual(b.variables, {"topic": "python"})


# ----------------------------------------------------------------------
class TestResponseGenerationIntegration(unittest.TestCase):
    """13. ResponseGeneration receives/exposes the generation context;
    existing callers that never ask for it are unaffected (16)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.core = Core(memory_db_path=os.path.join(self._tmp.name, "core.db"),
                         skill_definitions_dir=os.path.join(self._tmp.name, "skills"))
        assert self.core.teach_sentence_pattern("en", GREETING_PATTERN).status == STATUS_CREATED
        bound = self.core.bind_pattern_meaning("en", GREETING_PATTERN, "greeting")
        assert bound.success, bound.errors

    def test_request_exposes_a_generation_context_matching_the_plan(self):
        understanding = self.core.understand_language("good morning")
        request = ResponseGenerationRequest(understanding, context=self.core.context)
        ctx = request.generation_context
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["status"], understanding.response_plan["status"])
        self.assertEqual(ctx["response_action"], "greet")
        self.assertEqual(ctx["original_message"], "good morning")

    def test_no_generation_context_without_a_plan(self):
        understanding = self.core.understand_language("good morning")
        understanding.response_plan = None
        request = ResponseGenerationRequest(understanding, context=self.core.context)
        self.assertIsNone(request.generation_context)

    def test_no_generation_context_for_an_object_with_no_plan_attribute(self):
        self.assertIsNone(ResponseGenerationRequest(object()).generation_context)

    def test_deterministic_generation_is_still_deferred_with_no_text(self):
        """(16) An existing caller that ignores generation_context entirely
        still gets exactly the old, unchanged STATUS_DEFERRED result."""
        understanding = self.core.understand_language("good morning")
        response = self.core.generate_language_response(understanding)
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(response.response_text)

    def test_generation_result_is_identical_with_and_without_a_plan(self):
        with_plan = self.core.understand_language("good morning")
        without_plan = copy.copy(with_plan)
        without_plan.response_plan = None
        a = self.core.generate_language_response(with_plan).to_dict()
        b = self.core.generate_language_response(without_plan).to_dict()
        self.assertEqual(a, b)

    def test_the_generation_context_never_contains_generated_text(self):
        understanding = self.core.understand_language("good morning")
        ctx = ResponseGenerationRequest(understanding, context=self.core.context).generation_context
        self.assertNotIn("response_text", ctx)


# ----------------------------------------------------------------------
class _LocalPath(GuardCase):
    def core(self):
        core, _ = _core(self)
        return core


class TestLocalModelPathReceivesContext(_LocalPath):
    """14. The Local Language Model path receives the generation context."""

    def test_the_inference_request_carries_the_generation_context(self):
        core = self.core()
        assert core.teach_sentence_pattern("en", QUESTION_PATTERN).status == STATUS_CREATED
        bound = core.bind_pattern_meaning("en", QUESTION_PATTERN, "ask_question")
        assert bound.success, bound.errors
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        reply = core.process_input("what is python")
        self.assertEqual(reply, MODEL_TEXT)
        self.assertEqual(len(runtime.requests), 1)
        request = runtime.requests[0]
        self.assertIsNotNone(request.generation_context)
        self.assertEqual(request.generation_context.status, STATUS_RESOLVED)
        self.assertEqual(request.generation_context.response_action, ACTION_PROVIDE_INFORMATION)
        self.assertEqual(request.generation_context.variables, {"topic": "python"})
        # travels next to the text; never inside the prompt text itself
        self.assertNotIn("provide_information", request.user_input)

    def test_no_generation_context_when_no_plan_is_attached(self):
        core = self.core()
        runtime = TextRuntime(self.config())
        deterministic = DeterministicFallbackBackend(UnderstandingEngine())
        bare = deterministic.understand("hello there")
        self.assertIsNone(bare.response_plan)
        from language_intelligence.local_model_backend import LocalLanguageModelBackend
        local_backend = LocalLanguageModelBackend(runtime=runtime)
        local_backend.generate_response(bare)
        self.assertIsNone(runtime.requests[0].generation_context)

    def test_model_not_configured_path_is_unaffected(self):
        """The readiness guard, fallback selection and failure reporting
        are unchanged by generation_context being available."""
        control, _ = _core(self)
        expected = control.process_input(MESSAGE)
        core = self.core()
        assert core.teach_sentence_pattern("en", QUESTION_PATTERN).status == STATUS_CREATED
        bound = core.bind_pattern_meaning("en", QUESTION_PATTERN, "ask_question")
        assert bound.success, bound.errors
        core.use_local_language_model(runtime=TextRuntime(None))
        self.assertEqual(core.process_input(MESSAGE), expected)
        response = core.get_last_language_response()
        self.assertTrue(response.needs_fallback)
        self.assertIsNone(response.response_text)


# ----------------------------------------------------------------------
class TestDeterministicFallbackCompatibility(_PlanCase):
    """15. The deterministic fallback backend remains fully compatible."""

    def test_generate_response_signature_and_result_are_unchanged(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        understanding = self.understand("good morning")
        response = self.backend.generate_response(understanding, context=None)
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(response.response_text)
        self.assertEqual(response.backend_kind, self.backend.backend_kind)

    def test_the_context_is_still_reachable_through_the_request_holder(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        understanding = self.understand("good morning")
        ctx = ResponseGenerationRequest(understanding).generation_context
        self.assertEqual(ctx["response_action"], "greet")


# ----------------------------------------------------------------------
class TestRegressionPrompts421To425(_PlanCase):
    """17-18. Prompt 421-425 (and, transitively, 397-420) regressions:
    matching, structure extraction, meaning binding and planning
    behave exactly as before, whether or not a generation context is
    ever built from their output."""

    def test_pattern_matching_and_planning_are_unaffected(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        understanding, plan = self.plan("what is python")
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertEqual(understanding.learned_pattern_match["matched_pattern_text"],
                         QUESTION_PATTERN)
        self.assertEqual(understanding.response_plan, plan.to_dict())
        # building (or not building) a generation context changes nothing above
        build_generation_context(plan)
        understanding2, plan2 = self.plan("what is python")
        self.assertEqual(plan2.to_dict(), plan.to_dict())

    def test_ambiguous_and_unresolved_plans_are_unaffected(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        _, plan = self.plan("thanks bob")
        before = plan.to_dict()
        build_generation_context(plan)
        self.assertEqual(plan.to_dict(), before)

    def test_the_plan_still_never_contains_response_text(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        _, plan = self.plan("good morning")
        self.assertNotIn("response_text", plan.to_dict())
        ctx = build_generation_context(plan)
        self.assertNotIn("response_text", ctx.to_dict())


# ----------------------------------------------------------------------
class TestNormalizedInputPreservation(_PlanCase):
    """Prompt 610: `ResponseGenerationContext.normalized_input` forwards
    `ResponsePlan.normalized_input` (itself Prompt 609's forwarding of
    `LanguageUnderstandingResult.normalized_input`) verbatim - never a
    second normalization, never mixed up with `original_message`."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_normalized_input_is_present_on_the_context(self):
        understanding, plan, ctx = self.context_for("  good   morning  ")
        self.assertTrue(hasattr(ctx, "normalized_input"))
        self.assertEqual(ctx.normalized_input, "good morning")

    def test_exact_value_is_preserved_from_the_plan(self):
        understanding, plan, ctx = self.context_for("  good   morning  ")
        self.assertEqual(ctx.normalized_input, plan.normalized_input)
        self.assertEqual(ctx.to_dict()["normalized_input"], plan.normalized_input)

    def test_none_remains_none_when_the_plan_carries_none(self):
        plan = ResponsePlan(**_bare_plan_kwargs())
        self.assertIsNone(plan.normalized_input)
        ctx = build_generation_context(plan)
        self.assertIsNone(ctx.normalized_input)
        self.assertIsNone(ctx.to_dict()["normalized_input"])

    def test_original_input_is_unchanged(self):
        text = "  good   morning  "
        understanding, plan, ctx = self.context_for(text)
        self.assertEqual(ctx.original_message, text)
        self.assertEqual(ctx.original_message, understanding.original_input)
        self.assertNotEqual(ctx.original_message, ctx.normalized_input)

    def test_already_normalized_text_is_not_transformed_again(self):
        understanding, plan, ctx = self.context_for("good morning")
        self.assertEqual(ctx.normalized_input, "good morning")
        self.assertEqual(ctx.normalized_input, understanding.normalized_input)

    def test_legacy_direct_construction_defaults_safely(self):
        ctx = ResponseGenerationContext(
            original_message="Hello", status=STATUS_UNRESOLVED, response_action=None,
            meaning=None, meaning_candidates=[], matched_pattern=None, variables={},
            active_topic=None, references=[], context=None, language="english",
            locale=None, unresolved_requirements=[])
        self.assertIsNone(ctx.normalized_input)
        self.assertIsNone(ctx.to_dict()["normalized_input"])

    def test_no_second_normalization_occurs(self):
        # A message whose whitespace is not yet collapsed proves the value
        # on the context is exactly the understanding's OWN normalization
        # output - never re-derived from `original_message` a second time
        # by this bridge (which would, coincidentally, produce the same
        # whitespace-collapse here and mask a duplicate implementation).
        understanding, plan, ctx = self.context_for("good   \t morning")
        self.assertEqual(understanding.normalized_input, "good morning")
        self.assertEqual(ctx.normalized_input, understanding.normalized_input)


if __name__ == "__main__":
    unittest.main()
