"""
Tests for Prompt 425 - Structured Response Planning.

`ResponsePlanner` (language_intelligence/response_planning.py) turns what
the existing language-understanding pipeline already extracted into a
`ResponsePlan`: what a response must contain, never the response itself.
Every learned pattern and meaning asserted below was taught or bound by
the test itself - the planner is only ever shown to carry them, never to
add one.

The understanding is produced by the real pipeline (Understanding Engine,
Prompts 418-424 collaborators, `LanguageIntelligenceCore`), built exactly
the way Core builds it. Core / ResponseGeneration / Local Language Model
integration lives in test_response_planning_integration.py.

Run directly:
    python -m unittest tests.test_response_planning -v
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
from language_intelligence.language_relationships import (
    LanguageRelationshipStore, item_ref, concept_ref,
)
from language_intelligence.meaning_resolution import MeaningResolver
from language_intelligence.learned_meaning_disambiguation import LearnedMeaningDisambiguator
from language_intelligence.learned_pattern_matching import LearnedPatternMatcher
from language_intelligence.learned_sentence_structure import LearnedSentenceStructureExtractor
from language_intelligence.learned_pattern_teaching import LearnedPatternTeacher, STATUS_CREATED
from language_intelligence.learned_pattern_meaning import LearnedPatternMeaningBinder
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.language_understanding_result import (
    LanguageUnderstandingResult, INTENT_ASK_QUESTION,
)
from language_intelligence.response_planning import (
    ResponsePlanner, ResponsePlan, STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED,
    ACTION_GREET, ACTION_PROVIDE_INFORMATION, SOURCE_LEARNED_MEANING, SOURCE_LEARNED_PATTERN,
    SOURCE_MEANING_NAME, ITEM_GREETING, ITEM_INFORMATION, KIND_MEANING, KIND_REFERENCE,
    KIND_SENTENCE_STRUCTURE, KIND_EXPRESSION_MEANING, KIND_RESPONSE_ACTION,
    REASON_AMBIGUOUS_MEANING, REASON_AMBIGUOUS_PATTERN, REASON_AMBIGUOUS_REFERENCE,
    REASON_UNRESOLVED_REFERENCE, REASON_NO_RESPONSE_ACTION, REASON_NO_LEARNED_UNDERSTANDING,
    REASON_PATTERN_MEANING_NOT_AVAILABLE, REASON_AMBIGUOUS_EXPRESSION_MEANING,
    WARNING_INVALID_RESPONSE_ACTION,
)

GREETING_PATTERN = "good morning"
QUESTION_PATTERN = "what is {{topic}}"
LIKE = "من {{X}} را دوست دارم"
GIVE = "من {{X}} را به {{Y}} می\u200cدهم"


class _PlanCase(unittest.TestCase):
    """A fresh on-disk MemorySystem and the composition Core itself builds
    (ONE learning store, ONE relationship store, resolver, disambiguator,
    matcher, extractor, teacher, binder), a deterministic backend wired to
    them, and a LanguageIntelligenceCore (which plans every understanding)."""

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
        self.backend = self.make_backend()
        self.planner = ResponsePlanner()
        self.lic = LanguageIntelligenceCore(backend=self.backend, response_planner=self.planner)

    def make_backend(self, **overrides):
        parts = dict(
            meaning_resolver=self.resolver, meaning_disambiguator=self.disambiguator,
            pattern_matcher=self.matcher, structure_extractor=self.extractor,
            pattern_meaning_binder=self.binder)
        parts.update(overrides)
        return DeterministicFallbackBackend(UnderstandingEngine(), **parts)

    # ---- teaching -----------------------------------------------------
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

    # ---- understanding / planning --------------------------------------
    def understand(self, text, **context):
        return self.lic.understand(text, **context)

    def plan(self, text, **context):
        understanding = self.understand(text, **context)
        return understanding, self.planner.plan(understanding)

    def table_counts(self):
        return {name: self.memory.query_one(f"SELECT COUNT(*) AS c FROM {name}")["c"]
                for name in ("language_learning_items", "language_item_relationships", "learning_events")}


# ----------------------------------------------------------------------
class TestResolvedLearnedIntention(_PlanCase):
    """1. A resolved learned intention produces a response plan."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(QUESTION_PATTERN, "ask_question", source="unit-test")

    def test_plan_reports_the_resolved_meaning_and_pattern(self):
        understanding, plan = self.plan("what is python")
        self.assertIsInstance(plan, ResponsePlan)
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertTrue(plan.resolved)
        self.assertFalse(plan.ambiguous)
        self.assertEqual(plan.meaning_name, "ask_question")
        self.assertEqual(plan.matched_pattern_text, QUESTION_PATTERN)
        self.assertEqual(plan.matched_pattern["pattern_id"],
                         understanding.learned_pattern_match["matched_pattern_id"])
        self.assertEqual(plan.meaning, understanding.learned_pattern_meaning["meaning"])

    def test_reason_is_the_existing_pipelines_reason_verbatim(self):
        understanding, plan = self.plan("what is python")
        self.assertEqual(plan.reason, understanding.learned_pattern_meaning["reason"])

    def test_resolved_plan_needs_no_clarification(self):
        _, plan = self.plan("what is python")
        self.assertFalse(plan.needs_clarification)
        self.assertEqual(plan.meaning_candidates, [])
        self.assertEqual(plan.pattern_candidates, [])

    def test_the_plan_is_json_shaped(self):
        _, plan = self.plan("what is python")
        as_dict = plan.to_dict()
        json.dumps(as_dict, ensure_ascii=False)
        for key in ("original_message", "detected_language", "locale", "status", "reason",
                    "response_action", "meaning", "meaning_candidates", "matched_pattern",
                    "variables", "active_topic", "references", "context", "required_items",
                    "unresolved_requirements", "understanding_state"):
            self.assertIn(key, as_dict)
        self.assertEqual(as_dict["status"], STATUS_RESOLVED)

    def test_the_plan_is_attached_to_the_understanding_by_the_core(self):
        understanding, plan = self.plan("what is python")
        self.assertEqual(understanding.response_plan, plan.to_dict())
        self.assertEqual(understanding.to_dict()["response_plan"], plan.to_dict())
        self.assertEqual(self.lic.last_response_plan.to_dict(), plan.to_dict())

    def test_planning_from_the_dict_gives_the_same_plan(self):
        understanding = self.understand("what is python")
        self.assertEqual(self.planner.plan(understanding.to_dict()).to_dict(),
                         self.planner.plan(understanding).to_dict())

    def test_a_value_that_is_not_an_understanding_is_refused(self):
        for bad in (None, "what is python", 42, ["what is python"]):
            with self.assertRaises(TypeError):
                self.planner.plan(bad)


# ----------------------------------------------------------------------
class TestGreetingLikeIntention(_PlanCase):
    """2. A greeting-like learned intention."""

    def test_a_greeting_meaning_plans_the_greet_action(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        _, plan = self.plan("good morning")
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertEqual(plan.response_action, ACTION_GREET)
        self.assertEqual(plan.response_action, "greet")
        self.assertEqual(plan.response_action_source, SOURCE_MEANING_NAME)
        self.assertEqual(plan.required_items, [{"kind": ITEM_GREETING, "action": ACTION_GREET}])
        self.assertEqual(plan.unresolved_requirements, [])

    def test_the_meaning_name_lookup_is_exact_but_format_tolerant(self):
        self.teach_and_bind(GREETING_PATTERN, "Greet")
        self.assertEqual(self.plan("good morning")[1].response_action, ACTION_GREET)

    def test_a_greeting_taught_in_persian_with_an_explicit_action(self):
        # the meaning item's own stored value carries the action; binding
        # reuses that existing meaning item
        self.items.learn_item("fa", "meaning", "احوالپرسی", meaning={"response_action": "greet"})
        self.teach_and_bind("درود", "احوالپرسی", language="fa")
        understanding, plan = self.plan("درود")
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertEqual(plan.meaning_name, "احوالپرسی")
        self.assertEqual(plan.response_action, ACTION_GREET)
        self.assertEqual(plan.response_action_source, SOURCE_LEARNED_MEANING)
        self.assertEqual(plan.detected_language, "persian")

    def test_a_learned_meaning_outranks_the_heuristic_intent(self):
        # the Understanding Engine's heuristic labels a plain statement
        # "provide_information" (the USER states something); the explicitly
        # learned meaning is what decides the response action.
        self.teach_and_bind("درود", "greeting", language="fa")
        understanding, plan = self.plan("درود")
        self.assertEqual(understanding.intent, "provide_information")
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertEqual(plan.response_action, ACTION_GREET)
        self.assertNotEqual(plan.response_action, understanding.intent)
        # ...and the heuristic state is still reported, unchanged
        self.assertEqual(plan.understanding_state["intent"], "provide_information")
        self.assertEqual(plan.understanding_state["needs_clarification"],
                         understanding.needs_clarification)


# ----------------------------------------------------------------------
class TestInformationRequestLikeIntention(_PlanCase):
    """3. An information-request-like learned intention."""

    def test_a_question_meaning_plans_provide_information(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan = self.plan("what is python")
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertEqual(plan.response_action, ACTION_PROVIDE_INFORMATION)
        self.assertEqual(plan.response_action, "provide_information")
        self.assertEqual(plan.response_action_source, SOURCE_MEANING_NAME)
        self.assertEqual(len(plan.required_items), 1)
        self.assertEqual(plan.required_items[0]["kind"], ITEM_INFORMATION)

    def test_the_information_need_is_described_not_retrieved(self):
        self.teach_and_bind(QUESTION_PATTERN, "information_request")
        _, plan = self.plan("what is python")
        item = plan.required_items[0]
        self.assertEqual(item["query"]["message"], "what is python")
        self.assertEqual(item["query"]["variables"], {"topic": "python"})
        self.assertEqual(item["query"]["pattern_text"], QUESTION_PATTERN)
        self.assertEqual(item["retrieval"], {"from": ["knowledge", "memory"], "performed": False})
        self.assertNotIn("answer", item)
        self.assertNotIn("response_text", plan.to_dict())

    def test_an_explicit_action_taught_with_the_pattern_is_used(self):
        self.teach(QUESTION_PATTERN, meaning={"response_action": "provide_information"})
        self.bind(QUESTION_PATTERN, "definition_lookup")
        _, plan = self.plan("what is python")
        self.assertEqual(plan.response_action, ACTION_PROVIDE_INFORMATION)
        self.assertEqual(plan.response_action_source, SOURCE_LEARNED_PATTERN)

    def test_a_taught_action_outranks_the_meaning_name_and_the_meaning_item_outranks_the_pattern(self):
        self.items.learn_item("en", "meaning", "greeting", meaning={"response_action": "acknowledge"})
        self.teach(GREETING_PATTERN, meaning={"response_action": "wave"})
        self.bind(GREETING_PATTERN, "greeting")
        _, plan = self.plan("good morning")
        self.assertEqual(plan.response_action, "acknowledge")   # not "greet", not "wave"
        self.assertEqual(plan.response_action_source, SOURCE_LEARNED_MEANING)

    def test_a_taught_action_the_planner_has_no_item_for_is_passed_through_without_items(self):
        self.teach(GREETING_PATTERN, meaning={"response_action": "  acknowledge  "})
        self.bind(GREETING_PATTERN, "farewell_like")
        _, plan = self.plan("good morning")
        self.assertEqual(plan.response_action, "acknowledge")
        self.assertEqual(plan.required_items, [])
        self.assertEqual(plan.unresolved_requirements, [])

    def test_an_invalid_taught_action_is_ignored_with_a_warning_never_repaired(self):
        self.items.learn_item("en", "meaning", "greeting", meaning={"response_action": ""})
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        _, plan = self.plan("good morning")
        self.assertIn(f"{WARNING_INVALID_RESPONSE_ACTION}: {SOURCE_LEARNED_MEANING}", plan.warnings)
        # the fixed name lookup still applies - the action is not invented from the bad value
        self.assertEqual(plan.response_action, ACTION_GREET)
        self.assertEqual(plan.response_action_source, SOURCE_MEANING_NAME)

    def test_a_meaning_with_no_taught_action_and_no_known_name_has_no_action(self):
        self.teach_and_bind(QUESTION_PATTERN, "express_curiosity")
        understanding, plan = self.plan("what is python")
        self.assertEqual(plan.status, STATUS_RESOLVED)          # the meaning is known...
        self.assertIsNone(plan.response_action)                 # ...what to do about it is not
        self.assertIsNone(plan.response_action_source)
        self.assertEqual(plan.required_items, [])
        self.assertEqual([(r["kind"], r["reason"]) for r in plan.unresolved_requirements],
                         [(KIND_RESPONSE_ACTION, REASON_NO_RESPONSE_ACTION)])
        self.assertFalse(plan.needs_clarification)              # a gap in the plan, not for the user

    def test_the_heuristic_intent_never_selects_an_action(self):
        self.teach_and_bind(QUESTION_PATTERN, "express_curiosity")
        understanding, plan = self.plan("what is python")
        self.assertEqual(understanding.intent, INTENT_ASK_QUESTION)
        self.assertIsNone(plan.response_action)
        self.assertEqual(plan.understanding_state["intent"], INTENT_ASK_QUESTION)


# ----------------------------------------------------------------------
class TestExtractedVariablesPreserved(_PlanCase):
    """4. Extracted variables are preserved, verbatim and separate."""

    def test_variables_of_the_matched_pattern(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        understanding, plan = self.plan("what is python")
        self.assertEqual(plan.variables, {"topic": "python"})
        self.assertEqual(plan.variables, understanding.learned_pattern_match["variables"])

    def test_two_persian_variables_stay_separate(self):
        self.teach_and_bind(GIVE, "give_item", language="fa")
        understanding, plan = self.plan("من کتاب را به علی می\u200cدهم")
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertEqual(plan.variables, {"X": "کتاب", "Y": "علی"})
        self.assertEqual(plan.variables, understanding.learned_pattern_meaning["variables"])

    def test_variables_are_carried_into_the_information_query(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan = self.plan("what is machine learning")
        self.assertEqual(plan.variables, {"topic": "machine learning"})
        self.assertEqual(plan.required_items[0]["query"]["variables"],
                         {"topic": "machine learning"})

    def test_variables_are_kept_when_the_meaning_is_ambiguous(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        _, plan = self.plan("thanks bob")
        self.assertEqual(plan.status, STATUS_AMBIGUOUS)
        self.assertEqual(plan.variables, {"who": "bob"})

    def test_variables_are_kept_when_the_pattern_has_no_bound_meaning(self):
        self.teach(QUESTION_PATTERN)
        _, plan = self.plan("what is python")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertEqual(plan.variables, {"topic": "python"})

    def test_no_variable_is_invented(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        self.assertEqual(self.plan("good morning")[1].variables, {})
        self.assertEqual(self.plan("something unrelated entirely")[1].variables, {})


# ----------------------------------------------------------------------
class TestContextPreserved(_PlanCase):
    """5-7. Active topic, references and conversation context are preserved."""

    TURNS = [{"user": "I love Python", "assistant": "Noted."}]

    def setUp(self):
        super().setUp()
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        self.topic = ActiveTopicResult("python", "current_input", 0.7, True, None, "first_topic")
        self.relevant = select_relevant_turns("what is it", self.TURNS)
        self.reference = ResolvedReference(True, "it", "I love Python", 0.9, False, "resolved")

    def context(self, **overrides):
        values = dict(active_topic=self.topic, relevant_context=self.relevant,
                      resolved_reference=self.reference)
        values.update(overrides)
        return values

    def test_active_topic_is_preserved(self):
        understanding, plan = self.plan("what is it", **self.context())
        self.assertEqual(plan.active_topic, self.topic.to_dict())
        self.assertEqual(plan.active_topic["topic"], "python")
        self.assertEqual(plan.active_topic, understanding.active_topic)

    def test_the_active_topic_is_named_by_the_information_need(self):
        _, plan = self.plan("what is it", **self.context())
        self.assertEqual(plan.required_items[0]["topic"], "python")

    def test_no_topic_is_invented(self):
        _, plan = self.plan("what is it")
        self.assertIsNone(plan.active_topic)
        self.assertIsNone(plan.required_items[0]["topic"])

    def test_resolved_references_are_preserved(self):
        understanding, plan = self.plan("what is it", **self.context())
        self.assertEqual(plan.references, understanding.referenced_items)
        self.assertEqual(plan.references[0]["reference_text"], "it")
        self.assertEqual(plan.references[0]["resolved_context"], "I love Python")
        self.assertEqual(plan.required_items[0]["references"], plan.references)
        self.assertEqual(plan.unresolved_requirements, [])
        self.assertFalse(plan.needs_clarification)

    def test_an_ambiguous_reference_is_kept_and_asks_for_clarification(self):
        ambiguous = ResolvedReference(True, "it", None, 0.4, True, "two_candidates")
        understanding, plan = self.plan("what is it", **self.context(resolved_reference=ambiguous))
        self.assertEqual(plan.status, STATUS_RESOLVED)          # the intention is known
        self.assertTrue(plan.references[0]["ambiguous"])
        self.assertEqual([(r["kind"], r["reason"]) for r in plan.unresolved_requirements],
                         [(KIND_REFERENCE, REASON_AMBIGUOUS_REFERENCE)])
        self.assertEqual(plan.unresolved_requirements[0]["detail"]["reference_text"], "it")
        self.assertTrue(plan.needs_clarification)

    def test_an_unresolved_reference_is_kept_and_asks_for_clarification(self):
        unresolved = ResolvedReference(True, "it", None, 0.0, False, "nothing_to_point_to")
        _, plan = self.plan("what is it", **self.context(resolved_reference=unresolved))
        self.assertEqual([(r["kind"], r["reason"]) for r in plan.unresolved_requirements],
                         [(KIND_REFERENCE, REASON_UNRESOLVED_REFERENCE)])
        self.assertTrue(plan.needs_clarification)

    def test_no_reference_is_invented(self):
        _, plan = self.plan("what is python")
        self.assertEqual(plan.references, [])

    def test_relevant_conversation_context_is_preserved(self):
        understanding, plan = self.plan("what is it", **self.context())
        self.assertEqual(plan.context, self.relevant.to_dict())
        self.assertEqual(plan.context, understanding.conversation_context)
        self.assertEqual(plan.context["selected"][0]["turn"]["user"], "I love Python")

    def test_no_context_is_invented(self):
        _, plan = self.plan("what is python")
        self.assertIsNone(plan.context)

    def test_context_is_preserved_for_unresolved_messages_too(self):
        _, plan = self.plan("qwerty zzznoxyzzz unmapped concept", **self.context())
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertEqual(plan.active_topic["topic"], "python")
        self.assertEqual(plan.context, self.relevant.to_dict())

    def test_linked_knowledge_concepts_are_named_but_not_read(self):
        # a Knowledge concept the message's own expression was already
        # linked to (Prompts 417/418) is preserved as a pointer only
        self.knowledge.learn("Python", "A programming language", kind="concept")
        self.items.learn_item("english", "word", "python", meaning={"gloss": "a language"})
        self.rels.relate(item_ref("english", "word", "python"), concept_ref("Python"),
                         "expresses_concept")
        understanding, plan = self.plan("what is python")
        item = plan.required_items[0]
        self.assertEqual([c["concept"] for c in item["concepts"]], ["Python"])
        self.assertEqual(item["concepts"][0]["expression"].lower(), "python")
        # the planner names the concept; it does not read Knowledge itself
        self.assertEqual(set(item["concepts"][0]), {"concept", "expression", "relation_type"})
        self.assertNotIn("A programming language", json.dumps(item))
        self.assertFalse(item["retrieval"]["performed"])


# ----------------------------------------------------------------------
class TestAmbiguity(_PlanCase):
    """8. Ambiguity is preserved, never resolved by picking a winner."""

    def test_several_bound_meanings_give_an_ambiguous_plan(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        understanding, plan = self.plan("thanks bob")
        self.assertEqual(plan.status, "AMBIGUOUS")
        self.assertEqual(plan.status, STATUS_AMBIGUOUS)
        self.assertTrue(plan.ambiguous)
        self.assertFalse(plan.resolved)
        self.assertEqual(plan.reason, understanding.learned_pattern_meaning["reason"])

    def test_every_valid_candidate_is_preserved_and_none_is_selected(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude", confidence=0.4)
        self.bind("thanks {{who}}", "farewell", confidence=0.9)   # higher confidence must not win
        understanding, plan = self.plan("thanks bob")
        self.assertEqual(sorted(c["meaning_name"] for c in plan.meaning_candidates),
                         ["farewell", "gratitude"])
        self.assertEqual(plan.meaning_candidates,
                         understanding.learned_pattern_meaning["candidates"])
        self.assertIsNone(plan.meaning)
        self.assertIsNone(plan.meaning_name)
        self.assertIsNone(plan.response_action)
        self.assertEqual(plan.required_items, [])

    def test_clarification_may_be_required(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        _, plan = self.plan("thanks bob")
        self.assertTrue(plan.needs_clarification)
        self.assertEqual([(r["kind"], r["reason"]) for r in plan.unresolved_requirements],
                         [(KIND_MEANING, REASON_AMBIGUOUS_MEANING)])
        self.assertEqual(sorted(plan.unresolved_requirements[0]["detail"]["candidates"]),
                         ["farewell", "gratitude"])

    def test_context_that_distinguishes_the_meanings_resolves_them_as_before(self):
        # Prompt 420 decides; the planner does not second-guess it.
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude", examples=["thanks bob for the gift"])
        self.bind("thanks {{who}}", "farewell", examples=["thanks bob see you tomorrow"])
        understanding = self.understand("thanks bob")
        plan = self.planner.plan(understanding)
        self.assertEqual(plan.status, understanding.learned_pattern_meaning["status"])
        self.assertEqual(plan.meaning is None, understanding.learned_pattern_meaning["meaning"] is None)

    def test_two_patterns_matching_equally_are_ambiguous_with_both_preserved(self):
        self.teach("{{a}} is nice")
        self.teach("tea is {{b}}")
        understanding, plan = self.plan("tea is nice")
        self.assertEqual(plan.status, STATUS_AMBIGUOUS)
        self.assertEqual(sorted(c["pattern_text"] for c in plan.pattern_candidates),
                         ["tea is {{b}}", "{{a}} is nice"])
        self.assertEqual(plan.pattern_candidates, understanding.learned_pattern_match["candidates"])
        self.assertIsNone(plan.matched_pattern)
        self.assertIsNone(plan.meaning)
        self.assertEqual(plan.variables, {})            # each candidate keeps its own
        self.assertTrue(plan.needs_clarification)
        self.assertEqual([(r["kind"], r["reason"]) for r in plan.unresolved_requirements],
                         [(KIND_MEANING, REASON_AMBIGUOUS_PATTERN)])

    def test_an_expression_with_several_undecided_meanings_is_ambiguous_without_an_intention(self):
        self.items.learn_item("english", "sense_a", "bank", meaning={"gloss": "a financial institution"})
        self.items.learn_item("english", "sense_b", "bank", meaning={"gloss": "the side of a river"})
        understanding, plan = self.plan("The bank is closed.")
        self.assertEqual(plan.status, STATUS_AMBIGUOUS)
        self.assertEqual(plan.reason, REASON_AMBIGUOUS_EXPRESSION_MEANING)
        entry = [e for e in plan.expression_meanings if e["expression"].lower() == "bank"][0]
        self.assertEqual(entry["status"], "AMBIGUOUS")
        self.assertEqual(len(entry["candidates"]), 2)
        self.assertIsNone(entry["resolved_meaning"])
        self.assertIsNone(plan.response_action)
        self.assertTrue(plan.needs_clarification)
        self.assertIn((KIND_EXPRESSION_MEANING, REASON_AMBIGUOUS_EXPRESSION_MEANING),
                      [(r["kind"], r["reason"]) for r in plan.unresolved_requirements])

    def test_an_ambiguous_word_does_not_undo_a_resolved_intention(self):
        self.items.learn_item("english", "sense_a", "bank", meaning={"gloss": "a financial institution"})
        self.items.learn_item("english", "sense_b", "bank", meaning={"gloss": "the side of a river"})
        self.teach_and_bind("where is the {{place}}", "ask_question")
        _, plan = self.plan("where is the bank")
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertEqual(plan.response_action, ACTION_PROVIDE_INFORMATION)
        self.assertTrue(plan.needs_clarification)                   # the word is still open
        self.assertIn(KIND_EXPRESSION_MEANING,
                      [r["kind"] for r in plan.unresolved_requirements])

    def test_a_meaning_of_an_ambiguous_word_never_becomes_a_concept_reference(self):
        self.knowledge.learn("River", "Flowing water", kind="concept")
        self.items.learn_item("english", "sense_a", "bank", meaning={"gloss": "a financial institution"})
        self.items.learn_item("english", "sense_b", "bank", meaning={"gloss": "the side of a river"})
        self.rels.relate(item_ref("english", "sense_b", "bank"), concept_ref("River"),
                         "expresses_concept")
        self.teach_and_bind("where is the {{place}}", "ask_question")
        _, plan = self.plan("where is the bank")
        self.assertEqual(plan.required_items[0]["concepts"], [])


# ----------------------------------------------------------------------
class TestUnknownAndUnresolvedMessages(_PlanCase):
    """9. An unknown/unresolved message keeps its unresolved state."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(GREETING_PATTERN, "greeting")

    def test_a_message_with_no_learned_pattern_is_unresolved(self):
        understanding, plan = self.plan("qwerty zzznoxyzzz unmapped concept")
        self.assertEqual(plan.status, "UNRESOLVED")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertTrue(plan.unresolved)
        self.assertEqual(plan.reason, understanding.learned_pattern_match["reason"])

    def test_no_intention_is_fabricated(self):
        _, plan = self.plan("qwerty zzznoxyzzz unmapped concept")
        self.assertIsNone(plan.meaning)
        self.assertEqual(plan.meaning_candidates, [])
        self.assertIsNone(plan.matched_pattern)
        self.assertIsNone(plan.response_action)
        self.assertIsNone(plan.response_action_source)
        self.assertEqual(plan.required_items, [])
        self.assertEqual(plan.variables, {})

    def test_the_existing_understanding_state_is_preserved(self):
        understanding, plan = self.plan("qwerty zzznoxyzzz unmapped concept")
        state = plan.understanding_state
        self.assertEqual(state["intent"], understanding.intent)
        self.assertEqual(state["confidence"], round(understanding.confidence, 4))
        self.assertEqual(state["ambiguity"], understanding.ambiguity)
        self.assertEqual(state["needs_clarification"], understanding.needs_clarification)
        self.assertEqual(state["source_backend"], understanding.source_backend)
        self.assertEqual(state["learned_pattern_status"], "NOT_FOUND")
        self.assertEqual(state["learned_meaning_status"], "NOT_FOUND")

    def test_the_unresolved_meaning_is_listed_as_an_unresolved_requirement(self):
        _, plan = self.plan("qwerty zzznoxyzzz unmapped concept")
        self.assertEqual([(r["kind"], r["reason"]) for r in plan.unresolved_requirements],
                         [(KIND_MEANING, plan.reason)])

    def test_clarification_follows_the_existing_understanding_for_unresolved_messages(self):
        for text in ("qwerty zzznoxyzzz unmapped concept", "zzz", "?"):
            understanding, plan = self.plan(text)
            self.assertEqual(plan.status, STATUS_UNRESOLVED, text)
            self.assertEqual(plan.needs_clarification, bool(understanding.needs_clarification), text)

    def test_a_matched_pattern_with_no_bound_meaning_is_unresolved_not_guessed(self):
        self.teach(QUESTION_PATTERN)         # taught, never bound
        understanding, plan = self.plan("what is python")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertEqual(plan.reason, understanding.learned_pattern_meaning["reason"])
        self.assertEqual(plan.reason, "no_learned_meaning")
        self.assertEqual(plan.matched_pattern_text, QUESTION_PATTERN)     # the match is kept
        self.assertIsNone(plan.meaning)
        self.assertIsNone(plan.response_action)
        self.assertEqual(plan.required_items, [])

    def test_a_pattern_whose_structure_is_not_determined_stays_unresolved(self):
        self.teach("give {{a}} {{b}} now")
        understanding, plan = self.plan("give red book now")
        self.assertEqual(understanding.learned_pattern_match["status"], "NOT_RESOLVED")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertEqual(plan.reason, understanding.learned_pattern_match["reason"])
        self.assertEqual(plan.variables, {})
        self.assertIsNone(plan.meaning)
        structure = [r for r in plan.unresolved_requirements if r["kind"] == KIND_SENTENCE_STRUCTURE]
        self.assertEqual(len(structure), 1)
        self.assertEqual(structure[0]["detail"]["text"], "red book")        # preserved, not split
        self.assertEqual(structure[0]["detail"]["variable_names"], ["a", "b"])

    def test_nothing_learned_at_all_is_unresolved(self):
        other = _PlanCase("run")
        other.setUp()
        try:
            _, plan = other.plan("hello world")
            self.assertEqual(plan.status, STATUS_UNRESOLVED)
            self.assertIsNone(plan.response_action)
        finally:
            other.doCleanups()

    def test_without_pattern_meaning_the_state_is_reported_not_guessed(self):
        lic = LanguageIntelligenceCore(backend=self.make_backend(pattern_meaning_binder=None))
        understanding = lic.understand("good morning")
        self.assertIsNone(understanding.learned_pattern_meaning)
        plan = ResponsePlanner().plan(understanding)
        self.assertEqual(understanding.learned_pattern_match["status"], "MATCHED")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertEqual(plan.reason, REASON_PATTERN_MEANING_NOT_AVAILABLE)
        self.assertIsNone(plan.meaning)
        self.assertEqual(plan.matched_pattern_text, GREETING_PATTERN)

    def test_without_any_learned_understanding_the_state_is_reported_not_guessed(self):
        bare = LanguageIntelligenceCore(backend=DeterministicFallbackBackend(UnderstandingEngine()))
        understanding = bare.understand("good morning")
        self.assertIsNone(understanding.learned_pattern_match)
        plan = ResponsePlanner().plan(understanding)
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertEqual(plan.reason, REASON_NO_LEARNED_UNDERSTANDING)
        self.assertIsNone(plan.response_action)

    def test_an_empty_message_stays_honestly_unresolved(self):
        understanding, plan = self.plan("")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertEqual(plan.original_message, "")
        self.assertEqual(plan.needs_clarification, bool(understanding.needs_clarification))


# ----------------------------------------------------------------------
class TestOriginalMessagePreservation(_PlanCase):
    """10. The original message is reported verbatim."""

    def test_the_message_is_never_normalized_or_rewritten(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        messy = "  what   is\u00a0python  "
        understanding, plan = self.plan(messy)
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertEqual(plan.original_message, messy)
        self.assertEqual(plan.to_dict()["original_message"], messy)
        self.assertEqual(understanding.response_plan["original_message"], messy)
        self.assertEqual(plan.required_items[0]["query"]["message"], messy)
        self.assertNotEqual(understanding.normalized_input, messy)

    def test_persian_text_is_preserved_exactly(self):
        self.teach_and_bind(LIKE, "express_preference", language="fa")
        text = "  من  چای را دوست دارم "
        _, plan = self.plan(text)
        self.assertEqual(plan.original_message, text)

    def test_unresolved_and_ambiguous_messages_are_preserved_too(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        for text in ("  thanks   bob ", " zzz qqq  "):
            self.assertEqual(self.plan(text)[1].original_message, text)


# ----------------------------------------------------------------------
class TestLanguageAndLocalePreservation(_PlanCase):
    """11. Language and locale are preserved."""

    def test_the_detected_language_is_the_understandings(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        self.teach_and_bind(LIKE, "express_preference", language="fa")
        for text, expected in (("what is python", "english"), ("من چای را دوست دارم", "persian")):
            understanding, plan = self.plan(text)
            self.assertEqual(plan.detected_language, expected)
            self.assertEqual(plan.detected_language, understanding.detected_language)

    def test_the_language_is_kept_for_unresolved_messages(self):
        _, plan = self.plan("این یک جمله ناشناخته است")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertEqual(plan.detected_language, "persian")

    def test_a_locale_is_never_invented(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan = self.plan("what is python")
        self.assertEqual(plan.detected_language, "english")
        self.assertIsNone(plan.locale)

    def test_the_locale_the_pattern_and_binding_were_taught_under_is_preserved(self):
        self.teach_and_bind(LIKE, "express_preference", language="fa", locale="fa-IR")
        # teach() above was without a locale; a locale-carrying pattern too:
        _, plan = self.plan("من چای را دوست دارم")
        self.assertEqual(plan.locale, "fa-IR")                      # the binding's locale
        self.assertEqual(plan.meaning["locale"], "fa-IR")

    def test_the_patterns_own_locale_is_preserved(self):
        self.teach(LIKE, language="fa", locale="fa-IR")
        self.bind(LIKE, "express_preference", language="fa")
        understanding, plan = self.plan("من چای را دوست دارم")
        self.assertEqual(understanding.learned_sentence_structure["locale"], "fa-IR")
        self.assertEqual(plan.locale, "fa-IR")
        self.assertEqual(plan.matched_pattern["language"], "persian")

    def test_persian_intention_end_to_end(self):
        self.teach_and_bind(LIKE, "express_preference", language="fa", locale="fa-IR")
        _, plan = self.plan("من چای را دوست دارم")
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertEqual(plan.meaning_name, "express_preference")
        self.assertEqual(plan.variables, {"X": "چای"})
        self.assertEqual(plan.detected_language, "persian")
        # nothing says what to do for this meaning, so nothing is invented
        self.assertIsNone(plan.response_action)


# ----------------------------------------------------------------------
class TestPlannerNeverInventsOrWrites(_PlanCase):
    """The planner is a pure function of one understanding result."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")

    def test_planning_writes_nothing(self):
        understanding = self.understand("what is python")
        before = self.table_counts()
        for _ in range(3):
            self.planner.plan(understanding)
        self.assertEqual(self.table_counts(), before)

    def test_planning_does_not_change_the_understanding(self):
        understanding = self.understand("what is python")
        before = copy.deepcopy(understanding.to_dict())
        self.planner.plan(understanding)
        self.assertEqual(understanding.to_dict(), before)

    def test_a_plan_shares_no_mutable_state_with_the_understanding(self):
        topic = ActiveTopicResult("python", "current_input", 0.7, True, None, "first_topic")
        understanding = self.understand("what is python", active_topic=topic)
        plan = self.planner.plan(understanding)
        plan.active_topic["topic"] = "CHANGED"
        plan.variables["topic"] = "CHANGED"
        plan.meaning["meaning_name"] = "CHANGED"
        self.assertEqual(understanding.active_topic["topic"], "python")
        self.assertEqual(understanding.learned_pattern_meaning["variables"]["topic"], "python")
        self.assertEqual(understanding.learned_pattern_meaning["meaning"]["meaning_name"], "ask_question")
        again = plan.to_dict()
        again["variables"]["topic"] = "CHANGED TOO"
        self.assertEqual(plan.variables["topic"], "CHANGED")

    def test_planning_is_deterministic(self):
        understanding = self.understand("what is python")
        self.assertEqual(self.planner.plan(understanding).to_dict(),
                         self.planner.plan(understanding).to_dict())

    def test_a_plan_never_contains_response_text(self):
        for text in ("what is python", "thanks bob", "zzz qqq"):
            plan = self.plan(text)[1].to_dict()
            self.assertNotIn("response_text", json.dumps(plan))

    def test_only_what_the_understanding_carries_appears_in_the_plan(self):
        # a hand-built understanding that says nothing learned -> nothing planned
        bare = LanguageUnderstandingResult(
            original_input="what is python", detected_language="english",
            normalized_input="what is python", intent=INTENT_ASK_QUESTION, entities=[],
            referenced_items=[], active_topic=None, conversation_context=None,
            confidence=0.9, ambiguity=False, needs_clarification=False)
        plan = self.planner.plan(bare)
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertIsNone(plan.response_action)
        self.assertEqual(plan.required_items, [])
        self.assertEqual(plan.variables, {})
        self.assertIsNone(plan.meaning)

    def test_the_planner_holds_no_reference_to_any_store(self):
        self.assertEqual(vars(ResponsePlanner()), {})


# ----------------------------------------------------------------------
class TestNormalizedInputForwarding(_PlanCase):
    """Prompt 609: `ResponsePlan.normalized_input` forwards the existing
    understanding's own `normalized_input` (already produced once by the
    Understanding Engine's normalization, understanding/normalization.py)
    verbatim - never a second normalization, never mixed up with
    `original_message`."""

    def test_original_message_is_unchanged_by_the_new_field(self):
        understanding, plan = self.plan("  what   is python  ")
        self.assertEqual(plan.original_message, understanding.original_input)
        self.assertEqual(plan.original_message, "  what   is python  ")

    def test_normalized_input_is_populated_from_the_existing_normalization(self):
        understanding, plan = self.plan("  what   is python  ")
        self.assertEqual(understanding.normalized_input, "what is python")
        self.assertEqual(plan.normalized_input, understanding.normalized_input)
        self.assertEqual(plan.to_dict()["normalized_input"], "what is python")

    def test_already_normalized_input_is_stable(self):
        understanding, plan = self.plan("what is python")
        self.assertEqual(plan.normalized_input, "what is python")
        self.assertEqual(plan.normalized_input, understanding.normalized_input)

    def test_legacy_construction_without_normalized_input_defaults_safely(self):
        bare = LanguageUnderstandingResult(
            original_input="Hello", detected_language="english",
            normalized_input="Hello", intent=INTENT_ASK_QUESTION, entities=[],
            referenced_items=[], active_topic=None, conversation_context=None,
            confidence=0.9, ambiguity=False, needs_clarification=False)
        legacy_dict = bare.to_dict()
        del legacy_dict["normalized_input"]
        plan = self.planner.plan(legacy_dict)
        self.assertIsNone(plan.normalized_input)
        self.assertEqual(plan.to_dict()["normalized_input"], None)

    def test_downstream_plan_receives_the_same_normalized_value_as_understanding(self):
        understanding, plan = self.plan("what   is python")
        self.assertEqual(plan.normalized_input, understanding.to_dict()["normalized_input"])

    def test_normalization_is_not_performed_twice(self):
        # A pre-normalized understanding (as if normalization already
        # collapsed the whitespace) must come through unchanged - if the
        # planner re-normalized, an already-single-spaced string would
        # simply look the same, so this instead proves no OTHER
        # transformation (case folding, trimming beyond whitespace) is
        # applied by asserting byte-for-byte equality with the source.
        understanding, plan = self.plan("What   IS Python")
        self.assertEqual(plan.normalized_input, understanding.normalized_input)
        self.assertEqual(plan.normalized_input, "What IS Python")


if __name__ == "__main__":
    unittest.main()
