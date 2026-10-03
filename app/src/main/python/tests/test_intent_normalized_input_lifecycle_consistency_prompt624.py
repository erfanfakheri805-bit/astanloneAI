"""
Tests for Prompt 624 - Section 2: Language Intelligence and Request
Understanding - verifying that `intent` and `normalized_input` stay
correlated to the SAME request lifecycle, from language understanding
through `ResponsePlan`, with no stale or mixed-generation state.

Trace performed by this prompt:

    raw_text
      -> DeterministicFallbackBackend.understand()   (Prompt 622/623:
         intent and normalized_input both come from the SAME
         `UnderstandingEngine.understand()` call's `result` object -
         `intent = self._classify_intent(result.normalized_text, ...)`
         and `normalized_input=result.normalized_text` in the SAME
         `LanguageUnderstandingResult(...)` constructor call)
      -> LanguageIntelligenceCore._attach_response_plan(result)
         (language_intelligence_core.py) - calls
         `self.response_planner.plan(result)` with THIS call's own
         `result`, never a stored/previous one
      -> ResponsePlanner.plan()          (response_planning.py) - reads
         `data = {name: copy.deepcopy(source.get(name)) for name in
         _READ_FIELDS}` fresh from `understanding.to_dict()` on EVERY
         call (no memoization, no module- or instance-level cache), and
         forwards `intent` into `understanding_state["intent"]` and
         `normalized_input` into `ResponsePlan.normalized_input`

Finding: `ResponsePlanner` is documented and implemented as fully
stateless and dependency-free (`plan()` reads only its `understanding`
argument, deep-copies every field it touches, and stores nothing
between calls); `DeterministicFallbackBackend` and `UnderstandingEngine`
are likewise stateless (no per-instance mutable state); and
`LanguageIntelligenceCore.understand()` builds a brand-new `result` for
every call, passing it straight to `_attach_response_plan()` in the
same call. There is no cache, no shared buffer, and no attribute that
carries a value from one request into the next call's plan. `intent`
and `normalized_input` on a given `ResponsePlan` are therefore
guaranteed, by construction, to both belong to the SAME request that
produced that plan.

Per this prompt's requirement 4, THIS FILE ADDS NO PRODUCTION CHANGES -
it locks the existing, already-correct lifecycle isolation down with
focused regression coverage: independent request pairs, every
requested transition shape (normalized<->ordinary text,
intent-category changes, a case where BOTH values change at once so a
stale-state bug could not accidentally pass), a
success/unresolved/success status-recovery sequence using the existing
pipeline's own RESOLVED/UNRESOLVED statuses, repeated-read immutability,
and legacy construction safety when either field is absent.

Run directly:
    python -m unittest tests.test_intent_normalized_input_lifecycle_consistency_prompt624 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

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
from language_intelligence.language_understanding_result import (
    LanguageUnderstandingResult, INTENT_ASK_QUESTION, INTENT_PROVIDE_INFORMATION,
    INTENT_REQUEST_ACTION, INTENT_GOAL_REQUEST, INTENT_UNKNOWN,
)
from language_intelligence.response_planning import (
    ResponsePlanner, ResponsePlan, STATUS_RESOLVED, STATUS_UNRESOLVED,
)


def _make_backend():
    return DeterministicFallbackBackend(UnderstandingEngine())


def _make_lic():
    return LanguageIntelligenceCore(backend=_make_backend())


# ======================================================================
class TestIndependentRequestsDoNotLeakState(unittest.TestCase):
    """Request A with intent X + normalized A, then request B with
    intent Y + normalized B on the SAME reused core/backend instance:
    B's plan must contain only B's values, and re-checking A's own
    already-returned plan/understanding afterward must still show A's
    original values."""

    def test_request_b_contains_only_request_b_values(self):
        lic = _make_lic()

        understanding_a = lic.understand("What is Python?")
        plan_a = understanding_a.response_plan

        understanding_b = lic.understand("I need to refactor this function.")
        plan_b = understanding_b.response_plan

        self.assertEqual(understanding_a.intent, INTENT_ASK_QUESTION)
        self.assertEqual(understanding_a.normalized_input, "What is Python?")
        self.assertEqual(plan_a["normalized_input"], "What is Python?")
        self.assertEqual(plan_a["understanding_state"]["intent"], INTENT_ASK_QUESTION)

        self.assertEqual(understanding_b.intent, INTENT_GOAL_REQUEST)
        self.assertEqual(understanding_b.normalized_input, "I need to refactor this function.")
        self.assertEqual(plan_b["normalized_input"], "I need to refactor this function.")
        self.assertEqual(plan_b["understanding_state"]["intent"], INTENT_GOAL_REQUEST)

        # B must not carry anything from A.
        self.assertNotEqual(plan_b["normalized_input"], plan_a["normalized_input"])
        self.assertNotEqual(
            plan_b["understanding_state"]["intent"], plan_a["understanding_state"]["intent"])

        # A's own already-returned objects are untouched by B's call.
        self.assertEqual(understanding_a.intent, INTENT_ASK_QUESTION)
        self.assertEqual(understanding_a.normalized_input, "What is Python?")
        self.assertEqual(plan_a["normalized_input"], "What is Python?")
        self.assertEqual(plan_a["understanding_state"]["intent"], INTENT_ASK_QUESTION)

    def test_request_b_on_a_reused_planner_and_backend_directly(self):
        """Same guarantee one layer down: a single reused
        `DeterministicFallbackBackend` + `ResponsePlanner` pair (not
        going through `LanguageIntelligenceCore`) must not leak state
        between two `.understand()` / `.plan()` calls either."""
        backend = _make_backend()
        planner = ResponsePlanner()

        understanding_a = backend.understand("Explain indentation.")
        plan_a = planner.plan(understanding_a)

        understanding_b = backend.understand("Python is a programming language.")
        plan_b = planner.plan(understanding_b)

        self.assertEqual(plan_a.understanding_state["intent"], INTENT_REQUEST_ACTION)
        self.assertEqual(plan_a.normalized_input, "Explain indentation.")
        self.assertEqual(plan_b.understanding_state["intent"], INTENT_PROVIDE_INFORMATION)
        self.assertEqual(plan_b.normalized_input, "Python is a programming language.")

        # Re-check plan_a after plan_b was built - no leakage either way.
        self.assertEqual(plan_a.understanding_state["intent"], INTENT_REQUEST_ACTION)
        self.assertEqual(plan_a.normalized_input, "Explain indentation.")


# ======================================================================
class TestRequestedTransitionShapes(unittest.TestCase):
    """Every transition shape requirement 6 asks for, each verified as
    a fresh pair of calls on one reused core instance."""

    def test_normalized_to_ordinary_transition(self):
        lic = _make_lic()
        # First request: normalization changes the raw text.
        first = lic.understand("   what   is   python?   ")
        self.assertNotEqual(first.original_input, first.normalized_input)
        self.assertEqual(first.normalized_input, "what is python?")
        self.assertEqual(first.response_plan["normalized_input"], "what is python?")

        # Second request: already-clean text - normalization is a no-op.
        second = lic.understand("what is python")
        self.assertEqual(second.original_input, second.normalized_input)
        self.assertEqual(second.normalized_input, "what is python")
        self.assertEqual(second.response_plan["normalized_input"], "what is python")
        self.assertNotEqual(
            second.response_plan["normalized_input"], first.response_plan["normalized_input"])

    def test_ordinary_to_normalized_transition(self):
        lic = _make_lic()
        # First request: already-clean text.
        first = lic.understand("what is python")
        self.assertEqual(first.original_input, first.normalized_input)
        self.assertEqual(first.response_plan["normalized_input"], "what is python")

        # Second request: normalization changes the raw text.
        second = lic.understand("   what   is   python?   ")
        self.assertNotEqual(second.original_input, second.normalized_input)
        self.assertEqual(second.normalized_input, "what is python?")
        self.assertEqual(second.response_plan["normalized_input"], "what is python?")
        self.assertNotEqual(
            second.response_plan["normalized_input"], first.response_plan["normalized_input"])

    def test_intent_bearing_request_to_a_different_intent(self):
        lic = _make_lic()
        first = lic.understand("I need to refactor this function.")
        self.assertEqual(first.response_plan["understanding_state"]["intent"],
                          INTENT_GOAL_REQUEST)

        second = lic.understand("What is Python?")
        self.assertEqual(second.response_plan["understanding_state"]["intent"],
                          INTENT_ASK_QUESTION)
        self.assertNotEqual(
            second.response_plan["understanding_state"]["intent"],
            first.response_plan["understanding_state"]["intent"])

        third = lic.understand("Explain indentation.")
        self.assertEqual(third.response_plan["understanding_state"]["intent"],
                          INTENT_REQUEST_ACTION)
        self.assertNotEqual(
            third.response_plan["understanding_state"]["intent"],
            second.response_plan["understanding_state"]["intent"])

    def test_both_intent_and_normalized_input_change_together(self):
        """Requirement 8: a case where BOTH values differ from the
        previous request at once - a naive stale-cache bug that only
        refreshed one field would be caught here."""
        lic = _make_lic()
        first = lic.understand("   Python   is   a   programming   language.   ")
        self.assertEqual(first.response_plan["normalized_input"],
                          "Python is a programming language.")
        self.assertEqual(first.response_plan["understanding_state"]["intent"],
                          INTENT_PROVIDE_INFORMATION)

        second = lic.understand("i need to   build   a script")
        self.assertEqual(second.response_plan["normalized_input"], "i need to build a script")
        self.assertEqual(second.response_plan["understanding_state"]["intent"],
                          INTENT_GOAL_REQUEST)

        self.assertNotEqual(
            second.response_plan["normalized_input"], first.response_plan["normalized_input"])
        self.assertNotEqual(
            second.response_plan["understanding_state"]["intent"],
            first.response_plan["understanding_state"]["intent"])


# ======================================================================
class _StatusRecoveryCase(unittest.TestCase):
    """Fixture mirroring test_response_planning.py's own composition
    (ONE learning store, ONE relationship store, resolver,
    disambiguator, matcher, extractor, teacher, binder) - reused here,
    never re-implemented - so RESOLVED-status plans can be produced
    through the real, existing pipeline the same way that suite already
    does."""

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

    def teach_and_bind(self, pattern, meaning, language="en", **kwargs):
        result = self.teacher.teach(language, pattern, **kwargs)
        self.assertEqual(result.status, STATUS_CREATED, result.errors)
        bind_result = self.binder.bind(language, pattern, meaning, **kwargs)
        self.assertTrue(bind_result.success, bind_result.errors)
        return bind_result


class TestSuccessUnresolvedSuccessRecovery(_StatusRecoveryCase):
    """Requirement 6's final transition: a RESOLVED plan, followed by
    an UNRESOLVED one for an unrelated ordinary message, followed by a
    RESOLVED plan again - intent and normalized_input must correctly
    track each step, on the same reused core instance."""

    def setUp(self):
        super().setUp()
        self.teach_and_bind("what is {{topic}}", "ask_question", source="unit-test")

    def test_resolved_unresolved_resolved_sequence_tracks_current_request(self):
        first = self.lic.understand("what is python")
        self.assertEqual(first.response_plan["status"], STATUS_RESOLVED)
        self.assertEqual(first.response_plan["normalized_input"], "what is python")
        self.assertEqual(
            first.response_plan["understanding_state"]["intent"], INTENT_ASK_QUESTION)

        second = self.lic.understand("Python is a programming language.")
        self.assertEqual(second.response_plan["status"], STATUS_UNRESOLVED)
        self.assertEqual(
            second.response_plan["normalized_input"], "Python is a programming language.")
        self.assertEqual(
            second.response_plan["understanding_state"]["intent"], INTENT_PROVIDE_INFORMATION)
        # No leftover RESOLVED-request values from `first`.
        self.assertNotEqual(
            second.response_plan["normalized_input"], first.response_plan["normalized_input"])

        third = self.lic.understand("what is java")
        self.assertEqual(third.response_plan["status"], STATUS_RESOLVED)
        self.assertEqual(third.response_plan["normalized_input"], "what is java")
        self.assertEqual(
            third.response_plan["understanding_state"]["intent"], INTENT_ASK_QUESTION)
        # No leftover UNRESOLVED-request values from `second`.
        self.assertNotEqual(
            third.response_plan["normalized_input"], second.response_plan["normalized_input"])

        # First's own already-returned plan is still exactly as it was.
        self.assertEqual(first.response_plan["normalized_input"], "what is python")
        self.assertEqual(first.response_plan["status"], STATUS_RESOLVED)


# ======================================================================
class TestPairCorrespondsToTheSameCurrentRequest(unittest.TestCase):
    """Requirement 7: `understanding_state["intent"]` and
    `normalized_input` on a given plan are a unit describing ONE
    request - verified by cross-checking against an independently
    recomputed understanding for the same text, and by held-object
    identity where the same object genuinely travels through, per
    requirement 11 (`assertIs`, never `id()`)."""

    def test_plan_pair_matches_a_fresh_independent_understand_of_the_same_text(self):
        raw = "  Build   me   a   script.  "
        backend = _make_backend()
        planner = ResponsePlanner()

        understanding = backend.understand(raw)
        plan = planner.plan(understanding)

        independent = backend.understand(raw)
        self.assertEqual(plan.normalized_input, independent.normalized_input)
        self.assertEqual(plan.understanding_state["intent"], independent.intent)

    def test_plan_object_holds_the_same_intent_reference_as_the_understanding(self):
        backend = _make_backend()
        planner = ResponsePlanner()
        understanding = backend.understand("What is Python?")
        plan = planner.plan(understanding)
        self.assertIs(plan.understanding_state["intent"], understanding.intent)
        self.assertIs(plan.normalized_input, understanding.normalized_input)


# ======================================================================
class TestRepeatedReadsDoNotMutateEitherValue(unittest.TestCase):
    """Reading the plan (object or serialized dict) repeatedly must
    never mutate `normalized_input` or `understanding_state["intent"]`."""

    def test_repeated_to_dict_calls_are_stable_for_both_fields(self):
        backend = _make_backend()
        understanding = backend.understand("  what   is   python?  ")
        plan = ResponsePlanner().plan(understanding)

        first = plan.to_dict()
        second = plan.to_dict()
        self.assertEqual(first["normalized_input"], "what is python?")
        self.assertEqual(first["understanding_state"]["intent"], INTENT_ASK_QUESTION)
        self.assertEqual(second["normalized_input"], first["normalized_input"])
        self.assertEqual(
            second["understanding_state"]["intent"], first["understanding_state"]["intent"])

        # Mutating a returned dict must never reach back into the plan.
        first["normalized_input"] = "MUTATED"
        first["understanding_state"]["intent"] = "MUTATED"
        third = plan.to_dict()
        self.assertEqual(third["normalized_input"], "what is python?")
        self.assertEqual(third["understanding_state"]["intent"], INTENT_ASK_QUESTION)
        self.assertEqual(plan.normalized_input, "what is python?")
        self.assertEqual(plan.understanding_state["intent"], INTENT_ASK_QUESTION)

    def test_repeated_plan_calls_over_the_same_understanding_are_identical(self):
        backend = _make_backend()
        understanding = backend.understand("Explain indentation.")
        planner = ResponsePlanner()
        plans = [planner.plan(understanding) for _ in range(5)]
        normalized_values = {p.normalized_input for p in plans}
        intents = {p.understanding_state["intent"] for p in plans}
        self.assertEqual(len(normalized_values), 1)
        self.assertEqual(len(intents), 1)
        self.assertEqual(normalized_values.pop(), "Explain indentation.")
        self.assertEqual(intents.pop(), INTENT_REQUEST_ACTION)


# ======================================================================
class TestLegacyConstructionWhenEitherFieldIsAbsent(unittest.TestCase):
    """Legacy construction remains safe when `normalized_input` is
    absent on the plan (pre-Prompt-609 shape) or when the understanding
    dict itself carries no `intent`/`normalized_input` at all."""

    def test_legacy_response_plan_construction_without_normalized_input(self):
        legacy_plan = ResponsePlan(
            original_message="hi there", detected_language="english", locale=None,
            status=STATUS_UNRESOLVED, reason="no_learned_understanding",
            needs_clarification=False, response_action=None, response_action_source=None,
            meaning=None, meaning_candidates=[], matched_pattern=None, pattern_candidates=[],
            variables={}, expression_meanings=[], active_topic=None, references=[],
            context=None, required_items=[], unresolved_requirements=[],
            understanding_state={"intent": INTENT_UNKNOWN}, warnings=[],
        )
        self.assertIsNone(legacy_plan.normalized_input)
        self.assertEqual(legacy_plan.understanding_state["intent"], INTENT_UNKNOWN)
        self.assertEqual(legacy_plan.to_dict().get("normalized_input"), None)

    def test_plan_from_understanding_dict_missing_both_fields(self):
        minimal_dict = {
            "original_input": "hi there",
            "detected_language": "english",
            "confidence": 0.5,
            "ambiguity": False,
            "needs_clarification": False,
        }
        plan = ResponsePlanner().plan(minimal_dict)
        self.assertIsNone(plan.normalized_input)
        self.assertIsNone(plan.understanding_state["intent"])
        self.assertEqual(plan.original_message, "hi there")

    def test_plan_from_legacy_language_understanding_result_with_normalized_input_none(self):
        legacy = LanguageUnderstandingResult(
            original_input="hi there", detected_language="english", normalized_input=None,
            intent=INTENT_UNKNOWN, entities=[], referenced_items=[], active_topic=None,
            conversation_context=None, confidence=0.5, ambiguity=False,
            needs_clarification=False,
        )
        plan = ResponsePlanner().plan(legacy)
        self.assertIsNone(plan.normalized_input)
        self.assertEqual(plan.understanding_state["intent"], INTENT_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
