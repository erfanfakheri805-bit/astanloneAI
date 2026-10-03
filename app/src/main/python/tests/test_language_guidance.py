"""
Tests for Prompt 433 - Learned Language Guidance for Response Generation.

`build_language_guidance()` / `language_guidance_from_understanding()`
(language_intelligence/language_guidance.py) connect the existing
learned-language information (Prompt 416-424: learned meanings, learned
expressions, learned sentence patterns, learned pattern meanings,
resolved language relationships, recognized sentence structure) to the
response-generation context (`ResponseGenerationContext.language_guidance`,
`BackendGenerationRequest.language_guidance`) - never a new
language-learning store, never response text.

Unit-level tests build a real `ResponsePlan`/understanding the same way
test_response_generation_context.py's `_PlanCase` does (a real
Understanding Engine + real Prompt 416-424 stores, teaching patterns/
meanings through them) and inspect the guidance built from it.
Integration-level tests drive `ResponseGenerationContext` /
`BackendGenerationRequest` / `Core` to confirm nothing else changed.

Run directly:
    python -m unittest tests.test_language_guidance -v
"""

import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine

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
)
from language_intelligence.response_generation_context import (
    ResponseGenerationContext, build_generation_context, generation_context_from_understanding,
)
from language_intelligence.response_generation_request import (
    BackendGenerationRequest, build_generation_request, generation_request_from_understanding,
)
from language_intelligence.response_generation import ResponseGenerationRequest
from language_intelligence.language_guidance import (
    LearnedLanguageGuidance, build_language_guidance, language_guidance_from_understanding,
    STATUS_RESOLVED as GUIDANCE_RESOLVED, STATUS_AMBIGUOUS as GUIDANCE_AMBIGUOUS,
)

from core.core import Core

GREETING_PATTERN = "good morning"
QUESTION_PATTERN = "what is {{topic}}"
GIVING_PATTERN = "من {{X}} را به {{Y}} می‌دهم"


# ----------------------------------------------------------------------
class _PlanCase(unittest.TestCase):
    """Same composition test_response_generation_context.py's _PlanCase
    builds - a real Understanding Engine, real Prompt 416-424 stores, a
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

    def learn_word(self, key, meaning, language="en", **kwargs):
        return self.items.learn_item(language, "word", key, meaning=meaning, **kwargs)

    def understand(self, text, **context):
        return self.lic.understand(text, **context)

    def plan(self, text, **context):
        understanding = self.understand(text, **context)
        return understanding, self.planner.plan(understanding)

    def guidance_for(self, text, **overrides):
        """(understanding, plan, guidance) triple."""
        understanding, plan = self.plan(text, **overrides)
        return understanding, plan, language_guidance_from_understanding(understanding)


# ----------------------------------------------------------------------
class TestResolvedLearnedMeaningBecomesGuidance(_PlanCase):
    """1. A resolved learned (pattern) meaning becomes guidance."""

    def test_resolved_pattern_meaning_is_guidance(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question", source="unit-test")
        _, plan, guidance = self.guidance_for("what is python")
        self.assertEqual(plan.status, STATUS_RESOLVED)
        self.assertIsNotNone(guidance.pattern_meaning)
        self.assertEqual(guidance.pattern_meaning["status"], GUIDANCE_RESOLVED)
        self.assertEqual(guidance.pattern_meaning["meaning"]["meaning_name"], "ask_question")
        self.assertEqual(guidance.pattern_meaning["candidates"], [])

    def test_resolved_meaning_preserves_language_confidence_and_source(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question", source="unit-test",
                            confidence=0.9)
        _, _, guidance = self.guidance_for("what is python")
        meaning = guidance.pattern_meaning["meaning"]
        self.assertEqual(meaning["language"], "english")
        self.assertEqual(meaning["source"], "unit-test")
        self.assertAlmostEqual(meaning["confidence"], 0.9)
        self.assertEqual(meaning["key"], "ask_question")


# ----------------------------------------------------------------------
class TestLearnedExpressionBecomesGuidance(_PlanCase):
    """2. A learned expression (word/phrase) becomes guidance."""

    def test_a_learned_word_in_the_message_becomes_an_expression_meaning(self):
        self.learn_word("python", {"gloss": "a programming language"}, source="unit-test")
        _, plan, guidance = self.guidance_for("I like python")
        self.assertEqual(guidance.expression_meanings, plan.expression_meanings)
        expressions = [e["expression"] for e in guidance.expression_meanings]
        self.assertIn("python", expressions)
        entry = next(e for e in guidance.expression_meanings if e["expression"] == "python")
        self.assertEqual(entry["status"], GUIDANCE_RESOLVED)
        self.assertEqual(entry["resolved_meaning"]["meaning"], {"gloss": "a programming language"})
        self.assertEqual(entry["resolved_meaning"]["source"], "unit-test")


# ----------------------------------------------------------------------
class TestLearnedSentencePatternBecomesGuidance(_PlanCase):
    """3. A learned sentence pattern (its recognized structure) becomes
    guidance."""

    def test_a_matched_pattern_structure_is_guidance(self):
        self.teach(GIVING_PATTERN, language="fa")
        _, plan, guidance = self.guidance_for(
            "من کتاب را به علی می‌دهم", requested_language="fa")
        self.assertIsNotNone(guidance.sentence_structure)
        self.assertEqual(guidance.sentence_structure["status"], "MATCHED")
        kinds = [c["kind"] for c in guidance.sentence_structure["components"]]
        self.assertIn("variable", kinds)
        self.assertIn("fixed", kinds)


# ----------------------------------------------------------------------
class TestLearnedPatternMeaningBecomesGuidance(_PlanCase):
    """4. A learned pattern meaning (explicit binding) becomes guidance."""

    def test_bound_pattern_meaning_is_reflected_in_guidance(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        _, plan, guidance = self.guidance_for("good morning")
        self.assertEqual(guidance.pattern_meaning["status"], GUIDANCE_RESOLVED)
        self.assertEqual(guidance.pattern_meaning["meaning"]["meaning_name"], "greeting")


# ----------------------------------------------------------------------
class TestRelevantInformationIsIncluded(_PlanCase):
    """5. Information relevant to the current request is included."""

    def test_expression_meaning_for_a_word_actually_in_the_message_is_included(self):
        self.learn_word("python", {"gloss": "a language"})
        _, _, guidance = self.guidance_for("I like python")
        self.assertTrue(
            any(e["expression"] == "python" for e in guidance.expression_meanings))

    def test_matched_pattern_meaning_for_the_current_message_is_included(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, _, guidance = self.guidance_for("what is rust")
        self.assertEqual(guidance.pattern_meaning["meaning"]["meaning_name"], "ask_question")


# ----------------------------------------------------------------------
class TestUnrelatedLearnedInformationIsExcluded(_PlanCase):
    """6. Unrelated learned information is excluded."""

    def test_a_word_not_in_the_message_is_not_included(self):
        self.learn_word("python", {"gloss": "a language"})
        self.learn_word("rust", {"gloss": "another language"})
        _, _, guidance = self.guidance_for("I like python")
        expressions = [e["expression"] for e in guidance.expression_meanings]
        self.assertIn("python", expressions)
        self.assertNotIn("rust", expressions)

    def test_an_unrelated_taught_pattern_does_not_leak_into_guidance(self):
        self.teach_and_bind(GREETING_PATTERN, "greeting")
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, _, guidance = self.guidance_for("good morning")
        self.assertEqual(guidance.pattern_meaning["meaning"]["meaning_name"], "greeting")
        self.assertNotEqual(guidance.pattern_meaning["meaning"]["meaning_name"], "ask_question")


# ----------------------------------------------------------------------
class TestAmbiguousInformationRemainsCandidates(_PlanCase):
    """7. AMBIGUOUS learned information remains as candidates, never
    collapsed to one."""

    def test_ambiguous_pattern_meaning_keeps_every_candidate(self):
        self.teach("thanks {{who}}")
        self.bind("thanks {{who}}", "gratitude")
        self.bind("thanks {{who}}", "farewell")
        _, plan, guidance = self.guidance_for("thanks bob")
        self.assertEqual(plan.status, STATUS_AMBIGUOUS)
        self.assertEqual(guidance.pattern_meaning["status"], GUIDANCE_AMBIGUOUS)
        self.assertIsNone(guidance.pattern_meaning["meaning"])
        self.assertEqual(len(guidance.pattern_meaning["candidates"]), 2)
        names = {c["meaning_name"] for c in guidance.pattern_meaning["candidates"]}
        self.assertEqual(names, {"gratitude", "farewell"})


# ----------------------------------------------------------------------
class TestNotFoundProducesNoInventedGuidance(_PlanCase):
    """8. NOT_FOUND produces no invented guidance."""

    def test_no_pattern_meaning_guidance_when_nothing_is_bound(self):
        self.teach(QUESTION_PATTERN)  # matched, never bound to a meaning
        _, plan, guidance = self.guidance_for("what is python")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertIsNone(guidance.pattern_meaning)

    def test_no_sentence_structure_guidance_when_no_pattern_matches(self):
        _, plan, guidance = self.guidance_for("qwerty zzznoxyzzz unmapped concept")
        self.assertIsNone(guidance.sentence_structure)

    def test_fully_unresolved_message_has_empty_guidance(self):
        _, plan, guidance = self.guidance_for("qwerty zzznoxyzzz unmapped concept")
        self.assertEqual(plan.status, STATUS_UNRESOLVED)
        self.assertIsNone(guidance.pattern_meaning)
        self.assertEqual(guidance.expression_meanings, [])
        self.assertIsNone(guidance.sentence_structure)
        self.assertTrue(guidance.is_empty)


# ----------------------------------------------------------------------
class TestLanguageAndLocaleArePreserved(_PlanCase):
    """9. Language and locale are preserved."""

    def test_pattern_meaning_language_and_locale(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question", locale="en-US")
        _, _, guidance = self.guidance_for("what is python")
        meaning = guidance.pattern_meaning["meaning"]
        self.assertEqual(meaning["language"], "english")
        self.assertEqual(meaning["locale"], "en-US")

    def test_sentence_structure_language_and_locale(self):
        self.teach(GIVING_PATTERN, language="fa", locale="fa-IR")
        _, _, guidance = self.guidance_for(
            "من کتاب را به علی می‌دهم", requested_language="fa")
        self.assertEqual(guidance.sentence_structure["language"], "persian")
        self.assertEqual(guidance.sentence_structure["locale"], "fa-IR")


# ----------------------------------------------------------------------
class TestOriginalUserMessageIsPreserved(_PlanCase):
    """10. The original user message is preserved (never touched by
    this module, never rewritten inside guidance)."""

    def test_the_context_original_message_is_untouched(self):
        text = "  What   IS   Python?? \n"
        self.teach_and_bind(QUESTION_PATTERN.replace("what is", "what is").lower(),
                            "ask_question")
        understanding, plan = self.plan(text)
        ctx = build_generation_context(plan)
        self.assertEqual(ctx.original_message, text)
        self.assertEqual(ctx.original_message, understanding.original_input)

    def test_guidance_carries_no_original_message_field_of_its_own(self):
        """Guidance never duplicates or rewrites the message; the
        message stays solely on the context/plan/understanding."""
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, _, guidance = self.guidance_for("what is python")
        self.assertNotIn("original_message", guidance.to_dict())


# ----------------------------------------------------------------------
class TestRequestAndContextAreNotMutated(_PlanCase):
    """11. Request/context are not mutated by building guidance."""

    def test_building_guidance_twice_from_the_same_plan_is_independent(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan = self.plan("what is python")
        a = build_language_guidance(plan)
        b = build_language_guidance(plan)
        a.expression_meanings.append({"fake": True})
        a_meaning = a.pattern_meaning
        if a_meaning is not None:
            a_meaning["status"] = "HIJACKED"
        self.assertEqual(b.expression_meanings, [])
        self.assertNotEqual(b.pattern_meaning, a.pattern_meaning)

    def test_mutating_the_returned_dict_never_touches_the_guidance(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan = self.plan("what is python")
        guidance = build_language_guidance(plan)
        first = guidance.to_dict()
        first["expression_meanings"].append({"fake": True})
        first["pattern_meaning"]["status"] = "HIJACKED"
        second = guidance.to_dict()
        self.assertEqual(second["expression_meanings"], [])
        self.assertEqual(second["pattern_meaning"]["status"], GUIDANCE_RESOLVED)

    def test_mutating_the_source_plan_after_building_never_touches_guidance(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan = self.plan("what is python")
        plan_dict = plan.to_dict()
        guidance = build_language_guidance(plan_dict)
        plan_dict["meaning"]["meaning_name"] = "HIJACKED"
        plan_dict["expression_meanings"].append({"fake": True})
        self.assertEqual(guidance.pattern_meaning["meaning"]["meaning_name"], "ask_question")
        self.assertEqual(guidance.expression_meanings, [])

    def test_building_a_generation_context_never_mutates_the_plan(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        understanding, plan = self.plan("what is python")
        before = plan.to_dict()
        build_generation_context(
            plan, sentence_structure=understanding.learned_sentence_structure)
        self.assertEqual(plan.to_dict(), before)

    def test_building_guidance_never_mutates_the_understanding(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        understanding, plan = self.plan("what is python")
        before = understanding.to_dict()
        language_guidance_from_understanding(understanding)
        self.assertEqual(understanding.to_dict(), before)


# ----------------------------------------------------------------------
class TestGuidanceRemainsBounded(_PlanCase):
    """12. Guidance stays bounded - no conversation history, no memory
    database, no full learning-store dump."""

    def test_guidance_dict_carries_no_history_or_store_fields(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, _, guidance = self.guidance_for("what is python")
        as_dict = guidance.to_dict()
        self.assertNotIn("conversation_history", as_dict)
        self.assertNotIn("memory", as_dict)
        self.assertNotIn("knowledge", as_dict)
        self.assertNotIn("language_learning_store", as_dict)

    def test_expression_meanings_never_exceed_the_planners_own_bound(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan, guidance = self.guidance_for("what is python")
        self.assertLessEqual(len(guidance.expression_meanings), len(plan.expression_meanings) + 0)
        self.assertEqual(guidance.expression_meanings, plan.expression_meanings)

    def test_the_guidance_is_json_shaped(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, _, guidance = self.guidance_for("what is python")
        json.dumps(guidance.to_dict(), ensure_ascii=False)


# ----------------------------------------------------------------------
class TestExistingResponseGenerationRemainsCompatible(_PlanCase):
    """13. Existing response generation remains compatible - every
    prior ResponseGenerationContext / BackendGenerationRequest field is
    unchanged; language_guidance is purely additive."""

    def test_context_gains_language_guidance_but_keeps_every_prior_field(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        understanding, plan = self.plan("what is python")
        ctx = generation_context_from_understanding(understanding)
        self.assertIsInstance(ctx, ResponseGenerationContext)
        as_dict = ctx.to_dict()
        for field in ("original_message", "status", "response_action", "meaning",
                      "meaning_candidates", "matched_pattern", "variables", "active_topic",
                      "references", "context", "language", "locale",
                      "unresolved_requirements"):
            self.assertIn(field, as_dict)
        self.assertIn("language_guidance", as_dict)
        self.assertIsNotNone(as_dict["language_guidance"])

    def test_request_gains_language_guidance_but_keeps_every_prior_field(self):
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        understanding, plan = self.plan("what is python")
        request = generation_request_from_understanding(understanding)
        self.assertIsInstance(request, BackendGenerationRequest)
        as_dict = request.to_dict()
        self.assertIn("sentence_structure", as_dict)  # Prompt 427 field, untouched
        self.assertIn("language_guidance", as_dict)
        self.assertEqual(
            as_dict["language_guidance"]["pattern_meaning"]["meaning"]["meaning_name"],
            "ask_question")

    def test_context_without_a_plan_is_still_none(self):
        self.assertIsNone(generation_context_from_understanding(object()))

    def test_a_bare_understanding_with_no_plan_yields_no_guidance(self):
        bare = self.backend.understand("hello there")  # never planned
        self.assertIsNone(bare.response_plan)
        self.assertIsNone(language_guidance_from_understanding(bare))

    def test_build_generation_context_without_sentence_structure_still_works(self):
        """Backward compatible: existing single-argument call sites are
        unaffected; language_guidance.sentence_structure is simply None."""
        self.teach_and_bind(QUESTION_PATTERN, "ask_question")
        _, plan = self.plan("what is python")
        ctx = build_generation_context(plan)  # old call shape, no sentence_structure
        self.assertIsNone(ctx.language_guidance["sentence_structure"])
        self.assertIsNotNone(ctx.language_guidance["pattern_meaning"])

    def test_a_non_plan_non_dict_raises_type_error(self):
        with self.assertRaises(TypeError):
            build_language_guidance(object())


# ----------------------------------------------------------------------
class TestCoreIntegrationUnaffected(unittest.TestCase):
    """Regression: Core's existing understand/generate path (Prompts
    397-431) is unaffected by the presence of language_guidance."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.core = Core(memory_db_path=os.path.join(self._tmp.name, "core.db"),
                         skill_definitions_dir=os.path.join(self._tmp.name, "skills"))
        assert self.core.teach_sentence_pattern("en", GREETING_PATTERN).status == STATUS_CREATED
        bound = self.core.bind_pattern_meaning("en", GREETING_PATTERN, "greeting")
        assert bound.success, bound.errors

    def test_generation_context_via_core_includes_language_guidance(self):
        understanding = self.core.understand_language("good morning")
        request = ResponseGenerationRequest(understanding, context=self.core.context)
        ctx = request.generation_context
        self.assertIsNotNone(ctx)
        self.assertIn("language_guidance", ctx)
        self.assertEqual(ctx["language_guidance"]["pattern_meaning"]["meaning"]["meaning_name"],
                         "greeting")
        # every prior field is still exactly as before
        self.assertEqual(ctx["response_action"], "greet")
        self.assertEqual(ctx["original_message"], "good morning")

    def test_deterministic_generation_is_still_deferred_with_no_text(self):
        from language_intelligence.response_generation import STATUS_DEFERRED
        understanding = self.core.understand_language("good morning")
        response = self.core.generate_language_response(understanding)
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(response.response_text)

    def test_generation_request_via_core_includes_language_guidance(self):
        understanding = self.core.understand_language("good morning")
        request = ResponseGenerationRequest(understanding, context=self.core.context)
        req = request.generation_request
        self.assertIsNotNone(req)
        self.assertIn("language_guidance", req)
        self.assertEqual(req["language_guidance"]["pattern_meaning"]["meaning"]["meaning_name"],
                         "greeting")


if __name__ == "__main__":
    unittest.main()
