"""
Tests for Prompt 427 - Structured Backend Generation Request.

`build_generation_request()` (language_intelligence/
response_generation_request.py) turns the existing, bounded
`ResponseGenerationContext` (Prompt 426) into a `BackendGenerationRequest`
- everything a language backend needs to generate a response, plus
`sentence_structure` (Prompt 422), the one field a
`ResponseGenerationContext` does not carry. Still no natural-language
generation, no new planning system, no new conversation-context system.

Unit-level tests build a real `ResponsePlan`/`ResponseGenerationContext`
the same way test_response_generation_context.py does, then build a
request from it. Integration-level tests drive the real `Core` entry
points and the Local Language Model path to confirm
`ResponseGenerationRequest.generation_request`, `InferenceRequest.
generation_request`, the deterministic fallback backend, and Prompts
421-426 are all unaffected.

Run directly:
    python -m unittest tests.test_response_generation_request -v
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
    ResponsePlanner, STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED,
    ACTION_GREET, ACTION_PROVIDE_INFORMATION,
)
from language_intelligence.response_generation import (
    ResponseGenerationRequest, STATUS_DEFERRED,
)
from language_intelligence.response_generation_context import (
    build_generation_context, generation_context_from_understanding,
)
from language_intelligence.response_generation_request import (
    BackendGenerationRequest, build_generation_request, generation_request_from_understanding,
)
from language_intelligence.inference import InferenceRequest

from core.core import Core
from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT, _core
from tests.test_local_inference_response_generation import TextRuntime

GREETING_PATTERN = "good morning"
QUESTION_PATTERN = "what is {{topic}}"


# ----------------------------------------------------------------------
class _PlanCase(unittest.TestCase):
    """Same composition test_response_generation_context.py's _PlanCase
    builds - a real Understanding Engine, real Prompt 416-424 stores, a
    deterministic backend wired to them, and a LanguageIntelligenceCore."""

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

    def request_for(self, text, **overrides):
        """(understanding, plan, request) triple - request built the
        SAME way the Local Language Model backend builds it (via
        generation_request_from_understanding), never by hand."""
        understanding, plan = self.plan(text, **overrides)
        return understanding, plan, generation_request_from_understanding(understanding)


# ----------------------------------------------------------------------
class TestContextToRequest(_PlanCase):
    """1. A ResponseGenerationContext produces a BackendGenerationRequest."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")

    def test_build_from_a_live_context_object(self):
        understanding, plan = self.plan("what is python")
        context = build_generation_context(plan)
        request = build_generation_request(context)
        self.assertIsInstance(request, BackendGenerationRequest)
        self.assertEqual(request.status, STATUS_RESOLVED)
        self.assertEqual(request.response_action, ACTION_PROVIDE_INFORMATION)

    def test_build_from_the_contexts_to_dict(self):
        understanding, plan = self.plan("what is python")
        context_dict = build_generation_context(plan).to_dict()
        request = build_generation_request(context_dict)
        self.assertEqual(request.status, STATUS_RESOLVED)
        self.assertEqual(request.meaning, plan.meaning)

    def test_generation_request_from_understanding_reads_the_attached_plan(self):
        understanding = self.understand("what is python")
        request = generation_request_from_understanding(understanding)
        self.assertIsInstance(request, BackendGenerationRequest)
        self.assertEqual(request.status, understanding.response_plan["status"])

    def test_generation_request_from_understanding_is_none_without_a_plan(self):
        understanding = self.backend.understand("what is python")  # never planned
        self.assertIsNone(understanding.response_plan)
        self.assertIsNone(generation_request_from_understanding(understanding))

    def test_a_non_context_non_dict_raises_type_error(self):
        with self.assertRaises(TypeError):
            build_generation_request(object())

    def test_the_request_is_json_shaped(self):
        _, _, request = self.request_for("what is python")
        json.dumps(request.to_dict(), ensure_ascii=False)

    def test_resolved_ambiguous_unresolved_properties_match_status(self):
        _, _, request = self.request_for("what is python")
        self.assertTrue(request.resolved)
        self.assertFalse(request.ambiguous)
        self.assertFalse(request.unresolved)


# ----------------------------------------------------------------------
class TestOriginalMessagePreservation(_PlanCase):
    """2. The original message is preserved exactly, never normalized."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_verbatim_original_message(self):
        text = "  Good   Morning!! \n"
        understanding, plan, request = self.request_for(text)
        self.assertEqual(request.original_message, text)
        self.assertEqual(request.original_message, plan.original_message)
        self.assertEqual(request.original_message, understanding.original_input)
        self.assertNotEqual(request.original_message, understanding.normalized_input)

    def test_normalized_text_remains_separately_available(self):
        # not on the request itself - it stays where it already is
        text = "  Good   Morning!! \n"
        understanding, plan, request = self.request_for(text)
        self.assertNotEqual(understanding.normalized_input, text)
        self.assertNotIn("normalized", request.to_dict())


# ----------------------------------------------------------------------
class TestResponseActionPreservation(_PlanCase):
    """3. The response action is preserved, never invented."""

    def test_greet_action_is_preserved(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        _, plan, request = self.request_for("good morning")
        self.assertEqual(request.response_action, ACTION_GREET)
        self.assertEqual(request.response_action, plan.response_action)

    def test_provide_information_action_is_preserved(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan, request = self.request_for("what is python")
        self.assertEqual(request.response_action, ACTION_PROVIDE_INFORMATION)

    def test_no_action_is_invented_for_an_unresolved_plan(self):
        self.teach(QUESTION_PATTERN)  # matched, never bound to a meaning
        _, plan, request = self.request_for("what is python")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertIsNone(request.response_action)


# ----------------------------------------------------------------------
class TestMeaningPreservation(_PlanCase):
    """4. The resolved meaning/intention is preserved verbatim."""

    def test_the_bound_meaning_is_preserved(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question", source="unit-test")
        understanding, plan, request = self.request_for("what is python")
        self.assertEqual(request.meaning, plan.meaning)
        self.assertEqual(request.meaning["meaning_name"], "ask_question")

    def test_no_meaning_for_a_fully_unresolved_message(self):
        _, plan, request = self.request_for("qwerty zzznoxyzzz unmapped concept")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertIsNone(request.meaning)


# ----------------------------------------------------------------------
class TestMeaningCandidatesPreservation(_PlanCase):
    """5. Meaning candidates are preserved, none silently picked."""

    def test_ambiguous_candidates_are_all_kept(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        _, plan, request = self.request_for("thanks bob")
        self.assertEqual(plan.status, STATUS_AMBIGUOUS)
        self.assertEqual(request.status, STATUS_AMBIGUOUS)
        self.assertEqual(request.meaning_candidates, plan.meaning_candidates)
        self.assertEqual(len(request.meaning_candidates), 2)
        self.assertIsNone(request.response_action)

    def test_no_candidates_for_a_resolved_plan(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, _, request = self.request_for("what is python")
        self.assertEqual(request.meaning_candidates, [])


# ----------------------------------------------------------------------
class TestLearnedPatternPreservation(_PlanCase):
    """6. The matched learned pattern is preserved."""

    def test_matched_pattern_is_preserved(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan, request = self.request_for("what is python")
        self.assertEqual(request.matched_pattern, plan.matched_pattern)
        self.assertEqual(request.matched_pattern["pattern_text"], QUESTION_PATTERN)

    def test_no_pattern_for_a_fully_unresolved_message(self):
        _, plan, request = self.request_for("qwerty zzznoxyzzz unmapped concept")
        self.assertIsNone(request.matched_pattern)


# ----------------------------------------------------------------------
class TestSentenceStructurePreservation(_PlanCase):
    """7. The learned sentence structure is preserved - the one field
    not already on ResponseGenerationContext."""

    def test_structure_is_carried_from_the_understanding(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        understanding, plan, request = self.request_for("what is python")
        self.assertIsNotNone(understanding.learned_sentence_structure)
        self.assertEqual(request.sentence_structure, understanding.learned_sentence_structure)

    def test_no_match_is_recorded_as_not_found_never_invented(self):
        # the structure extractor still returns its own honest
        # "nothing matched" descriptor (Prompt 422) - never None and
        # never a fabricated match; this module only carries it through
        _, plan, request = self.request_for("qwerty zzznoxyzzz unmapped concept")
        self.assertIsNotNone(request.sentence_structure)
        self.assertFalse(request.sentence_structure["matched"])
        self.assertIsNone(request.sentence_structure["matched_pattern_text"])

    def test_a_bare_generation_context_yields_no_structure(self):
        # per the module docstring: a ResponseGenerationContext alone
        # cannot supply it - only reading understanding directly can.
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan = self.plan("what is python")
        context = build_generation_context(plan)
        request = build_generation_request(context)  # no sentence_structure passed
        self.assertIsNone(request.sentence_structure)

    def test_structure_is_not_on_the_response_plan_or_context(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan = self.plan("what is python")
        self.assertNotIn("sentence_structure", plan.to_dict())
        self.assertNotIn("sentence_structure", build_generation_context(plan).to_dict())


# ----------------------------------------------------------------------
class TestExtractedVariablesPreservation(_PlanCase):
    """8. Extracted variables are preserved, verbatim."""

    def test_variables_are_carried_through(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        understanding, plan, request = self.request_for("what is machine learning")
        self.assertEqual(request.variables, {"topic": "machine learning"})
        self.assertEqual(request.variables, plan.variables)

    def test_no_variable_is_invented(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        _, _, request = self.request_for("good morning")
        self.assertEqual(request.variables, {})


# ----------------------------------------------------------------------
class TestTopicPreservation(_PlanCase):
    """9. Active topic is preserved."""

    TURNS = [{"user": "I love Python", "assistant": "Noted."}]

    def setUp(self):
        super().setUp()
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        self.topic = ActiveTopicResult("python", "current_input", 0.7, True, None, "first_topic")

    def test_active_topic_is_preserved(self):
        understanding, plan, request = self.request_for("what is it", active_topic=self.topic)
        self.assertEqual(request.active_topic, plan.active_topic)
        self.assertEqual(request.active_topic["topic"], "python")

    def test_no_topic_is_invented(self):
        _, _, request = self.request_for("what is python")
        self.assertIsNone(request.active_topic)


# ----------------------------------------------------------------------
class TestReferencePreservation(_PlanCase):
    """10. Resolved references are preserved."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        self.reference = ResolvedReference(True, "it", "I love Python", 0.9, False, "resolved")

    def test_references_are_preserved(self):
        understanding, plan, request = self.request_for(
            "what is it", resolved_reference=self.reference)
        self.assertEqual(request.references, plan.references)
        self.assertEqual(request.references[0]["reference_text"], "it")

    def test_no_reference_is_invented(self):
        _, _, request = self.request_for("what is python")
        self.assertEqual(request.references, [])

    def test_an_ambiguous_reference_stays_in_unresolved_requirements(self):
        ambiguous = ResolvedReference(True, "it", None, 0.4, True, "two_candidates")
        _, plan, request = self.request_for("what is it", resolved_reference=ambiguous)
        self.assertEqual(request.unresolved_requirements, plan.unresolved_requirements)
        self.assertTrue(any(r["kind"] == "reference" for r in request.unresolved_requirements))


# ----------------------------------------------------------------------
class TestBoundedContext(_PlanCase):
    """11. The request stays bounded - reuses the already-bounded
    Prompt 426 context, adds nothing unbounded."""

    def test_no_conversation_history_or_store_fields_exist(self):
        _, _, request = self.request_for("what is python")
        as_dict = request.to_dict()
        for forbidden in ("conversation_history", "memory", "knowledge", "memory_database"):
            self.assertNotIn(forbidden, as_dict)

    def test_context_is_exactly_the_planners_own_bounded_context(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        turns = [{"user": f"turn {i}", "assistant": "ok"} for i in range(50)]
        relevant = select_relevant_turns("what is it", turns)
        understanding, plan, request = self.request_for("what is it", relevant_context=relevant)
        self.assertEqual(request.context, plan.context)
        self.assertEqual(request.context, relevant.to_dict())

    def test_sentence_structure_is_one_messages_worth_not_history(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, _, request = self.request_for("what is python")
        # a single message's structure, never a list of turns
        self.assertNotIsInstance(request.sentence_structure, list)


# ----------------------------------------------------------------------
class TestLanguageAndLocalePreservation(_PlanCase):
    """12. Language and locale are preserved."""

    def test_language_and_locale_of_an_english_message(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question", locale="en-US")
        understanding, plan, request = self.request_for("what is python")
        self.assertEqual(request.language, plan.detected_language)
        self.assertEqual(request.locale, plan.locale)

    def test_no_locale_is_derived_from_the_language(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        _, plan, request = self.request_for("good morning")
        self.assertIsNone(plan.locale)
        self.assertIsNone(request.locale)
        self.assertIsNotNone(request.language)


# ----------------------------------------------------------------------
class TestMutableStateIsolation(_PlanCase):
    """13. No mutable-state leakage in either direction."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")

    def test_mutating_the_returned_dict_never_touches_the_request(self):
        _, plan, request = self.request_for("what is python")
        first = request.to_dict()
        first["variables"]["topic"] = "HIJACKED"
        first.setdefault("sentence_structure", {})
        second = request.to_dict()
        self.assertEqual(second["variables"], {"topic": "python"})

    def test_mutating_the_request_object_never_touches_the_plan(self):
        understanding, plan, request = self.request_for("what is python")
        request.variables["topic"] = "HIJACKED"
        request.references.append({"fake": True})
        self.assertEqual(plan.variables, {"topic": "python"})
        self.assertEqual(plan.references, [])

    def test_mutating_the_request_object_never_touches_the_understanding(self):
        understanding, plan, request = self.request_for("what is python")
        if request.sentence_structure is not None:
            request.sentence_structure["hijacked"] = True
        self.assertNotIn("hijacked", understanding.learned_sentence_structure or {})

    def test_mutating_a_live_response_plan_after_building_never_touches_the_request(self):
        understanding, plan, _ = self.request_for("what is python")
        context = build_generation_context(plan)
        request = build_generation_request(
            context, sentence_structure=understanding.learned_sentence_structure)
        plan.variables["topic"] = "HIJACKED"
        self.assertEqual(request.variables, {"topic": "python"})

    def test_mutating_the_source_sentence_structure_after_building_never_touches_the_request(self):
        understanding, plan, _ = self.request_for("what is python")
        structure = copy.deepcopy(understanding.learned_sentence_structure)
        context = build_generation_context(plan)
        request = build_generation_request(context, sentence_structure=structure)
        if isinstance(structure, dict):
            structure["hijacked"] = True
        self.assertNotIn("hijacked", request.sentence_structure or {})

    def test_two_builds_from_the_same_context_share_no_mutable_object(self):
        _, plan, _ = self.request_for("what is python")
        context = build_generation_context(plan)
        a = build_generation_request(context)
        b = build_generation_request(context)
        a.variables["topic"] = "HIJACKED"
        self.assertEqual(b.variables, {"topic": "python"})


# ----------------------------------------------------------------------
class TestResponseGenerationIntegration(unittest.TestCase):
    """14 (accessor half). ResponseGenerationRequest.generation_request
    exposes the structured request for any backend; existing callers
    that never ask for it are unaffected (18)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.core = Core(memory_db_path=os.path.join(self._tmp.name, "core.db"),
                         skill_definitions_dir=os.path.join(self._tmp.name, "skills"))
        assert self.core.teach_sentence_pattern("en", GREETING_PATTERN).status == STATUS_CREATED
        bound = self.core.bind_pattern_meaning("en", GREETING_PATTERN, "greeting")
        assert bound.success, bound.errors

    def test_request_exposes_a_generation_request_matching_the_plan(self):
        understanding = self.core.understand_language("good morning")
        request = ResponseGenerationRequest(understanding, context=self.core.context)
        generation_request = request.generation_request
        self.assertIsNotNone(generation_request)
        self.assertEqual(generation_request["status"], understanding.response_plan["status"])
        self.assertEqual(generation_request["response_action"], "greet")
        self.assertEqual(generation_request["original_message"], "good morning")
        self.assertIn("sentence_structure", generation_request)

    def test_no_generation_request_without_a_plan(self):
        understanding = self.core.understand_language("good morning")
        understanding.response_plan = None
        request = ResponseGenerationRequest(understanding, context=self.core.context)
        self.assertIsNone(request.generation_request)

    def test_no_generation_request_for_an_object_with_no_plan_attribute(self):
        self.assertIsNone(ResponseGenerationRequest(object()).generation_request)

    def test_deterministic_generation_is_still_deferred_with_no_text(self):
        """(15) An existing caller that ignores generation_request entirely
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

    def test_the_generation_request_never_contains_generated_text(self):
        understanding = self.core.understand_language("good morning")
        generation_request = ResponseGenerationRequest(
            understanding, context=self.core.context).generation_request
        self.assertNotIn("response_text", generation_request)


# ----------------------------------------------------------------------
class _LocalPath(GuardCase):
    def core(self):
        core, _ = _core(self)
        return core


class TestLocalModelPathReceivesRequest(_LocalPath):
    """14. The Local Language Model path receives the structured
    request (and still receives generation_context, Prompt 426)."""

    def test_the_inference_request_carries_the_generation_request(self):
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
        self.assertIsInstance(request, InferenceRequest)
        self.assertIsNotNone(request.generation_request)
        self.assertIsInstance(request.generation_request, BackendGenerationRequest)
        self.assertEqual(request.generation_request.status, STATUS_RESOLVED)
        self.assertEqual(request.generation_request.response_action, ACTION_PROVIDE_INFORMATION)
        self.assertEqual(request.generation_request.variables, {"topic": "python"})
        # Prompt 426's field is still populated, unchanged, alongside it
        self.assertIsNotNone(request.generation_context)
        self.assertEqual(request.generation_context.status, request.generation_request.status)
        # travels next to the text; never inside the prompt text itself
        self.assertNotIn("provide_information", request.user_input)

    def test_no_generation_request_when_no_plan_is_attached(self):
        core = self.core()
        runtime = TextRuntime(self.config())
        deterministic = DeterministicFallbackBackend(UnderstandingEngine())
        bare = deterministic.understand("hello there")
        self.assertIsNone(bare.response_plan)
        from language_intelligence.local_model_backend import LocalLanguageModelBackend
        local_backend = LocalLanguageModelBackend(runtime=runtime)
        local_backend.generate_response(bare)
        self.assertIsNone(runtime.requests[0].generation_request)
        self.assertIsNone(runtime.requests[0].generation_context)

    def test_model_not_configured_path_is_unaffected(self):
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
    """15. The deterministic fallback backend remains fully compatible;
    it is never forced to use the fields it did not use before."""

    def test_generate_response_signature_and_result_are_unchanged(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        understanding = self.understand("good morning")
        response = self.backend.generate_response(understanding, context=None)
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(response.response_text)
        self.assertEqual(response.backend_kind, self.backend.backend_kind)

    def test_the_request_is_still_reachable_through_the_request_holder(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        understanding = self.understand("good morning")
        generation_request = ResponseGenerationRequest(understanding).generation_request
        self.assertEqual(generation_request["response_action"], "greet")


# ----------------------------------------------------------------------
class TestAmbiguousStatePreservation(_PlanCase):
    """16. An AMBIGUOUS plan's state survives into the request."""

    def test_ambiguous_status_and_no_response_action(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        _, plan, request = self.request_for("thanks bob")
        self.assertEqual(request.status, STATUS_AMBIGUOUS)
        self.assertTrue(request.ambiguous)
        self.assertFalse(request.resolved)
        self.assertIsNone(request.response_action)
        self.assertIsNone(request.meaning)
        self.assertEqual(len(request.meaning_candidates), 2)


# ----------------------------------------------------------------------
class TestUnresolvedStatePreservation(_PlanCase):
    """17. An UNRESOLVED plan's state survives into the request."""

    def test_unresolved_status_and_no_response_action(self):
        _, plan, request = self.request_for("qwerty zzznoxyzzz unmapped concept")
        self.assertEqual(request.status, STATUS_UNRESOLVED)
        self.assertTrue(request.unresolved)
        self.assertIsNone(request.response_action)
        self.assertIsNone(request.meaning)
        self.assertEqual(request.meaning_candidates, [])

    def test_unresolved_because_the_pattern_has_no_bound_meaning(self):
        self.teach(QUESTION_PATTERN)  # matched, never bound
        _, plan, request = self.request_for("what is python")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertEqual(request.status, STATUS_UNRESOLVED)
        self.assertIsNone(request.response_action)
        self.assertEqual(request.variables, {"topic": "python"})
        self.assertIsNotNone(request.matched_pattern)


# ----------------------------------------------------------------------
class TestRegressionPrompts421To426(_PlanCase):
    """18-21. Existing-caller compatibility plus Prompt 421-426
    regressions: matching, structure extraction, meaning binding,
    planning and the Prompt 426 context all behave exactly as before,
    whether or not a BackendGenerationRequest is ever built."""

    def test_build_inference_request_without_a_generation_request_still_works(self):
        # (18) an existing caller of build_inference_request that never
        # passes generation_request keeps getting exactly the old shape
        from language_intelligence.local_model_mapping import build_inference_request
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        understanding = self.understand("good morning")
        request = build_inference_request(understanding, system_prompt="Be brief.")
        self.assertIsNone(request.generation_request)
        self.assertEqual(request.user_input, "good morning")

    def test_pattern_matching_and_planning_are_unaffected(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        understanding, plan = self.plan("what is python")
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertEqual(understanding.learned_pattern_match["matched_pattern_text"],
                         QUESTION_PATTERN)
        build_generation_request(build_generation_context(plan))
        understanding2, plan2 = self.plan("what is python")
        self.assertEqual(plan2.to_dict(), plan.to_dict())

    def test_the_prompt_426_context_is_still_built_the_same_way(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        understanding = self.understand("what is python")
        context = generation_context_from_understanding(understanding)
        self.assertEqual(context.status, STATUS_RESOLVED)
        self.assertEqual(context.response_action, ACTION_PROVIDE_INFORMATION)
        # building a 427 request from the same understanding changes nothing about it
        generation_request_from_understanding(understanding)
        context_again = generation_context_from_understanding(understanding)
        self.assertEqual(context.to_dict(), context_again.to_dict())

    def test_ambiguous_and_unresolved_plans_are_unaffected(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        _, plan = self.plan("thanks bob")
        before = plan.to_dict()
        build_generation_request(build_generation_context(plan))
        self.assertEqual(plan.to_dict(), before)

    def test_the_plan_still_never_contains_response_text(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        _, plan = self.plan("good morning")
        self.assertNotIn("response_text", plan.to_dict())
        request = build_generation_request(build_generation_context(plan))
        self.assertNotIn("response_text", request.to_dict())


if __name__ == "__main__":
    unittest.main()
