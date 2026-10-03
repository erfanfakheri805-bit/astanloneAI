"""
Tests for Prompt 625 - Section 2: Language Intelligence and Request
Understanding - verifying that `LanguageIntelligenceCore.last_response_plan`
(the existing public access path to the most recent `ResponsePlan`)
stays correctly correlated with the CURRENT request's `intent` and
`normalized_input`, with no stale or mixed-generation state.

Trace performed by this prompt:

    LanguageUnderstandingResult                (Prompts 397-424)
      -> ResponsePlanner.plan()                (response_planning.py,
         stateless - Prompt 624 confirmed no cache/instance state)
      -> ResponsePlan
      -> LanguageIntelligenceCore._attach_response_plan(result)
         (language_intelligence_core.py):

             self.last_response_plan = None            # <- unconditional,
                                                         #    every call
             if not isinstance(result, LanguageUnderstandingResult):
                 return result
             if result.response_plan is not None:
                 return result
             try:
                 plan = self.response_planner.plan(result)
                 result.response_plan = plan.to_dict()
                 self.last_response_plan = plan          # <- only on success
             except Exception as exc:
                 result.warnings = ... + [f"response_plan_error: {exc}"]
             return result

      -> LanguageIntelligenceCore.last_response_plan  (existing public
         attribute - the only existing access path; there is no
         separate getter method)

Finding: `self.last_response_plan = None` runs UNCONDITIONALLY at the
top of every `_attach_response_plan()` call, before the type check,
before the "already has a plan" early-return, and before the
plan()/exception boundary. This means:

  - a non-understanding `result`, or a `result` that already carries a
    plan, leaves `last_response_plan` at `None` - never a previous
    request's plan;
  - a planning failure leaves `last_response_plan` at `None` - never
    the previous request's plan, and never a mismatched partial one;
  - only a plan produced for THIS call's own `result` is ever assigned
    to `last_response_plan`.

Combined with `ResponsePlanner.plan()` being a pure, stateless function
of its `understanding` argument (Prompt 624), `last_response_plan` -
whenever it is not `None` - is therefore, by construction, always the
plan for the CURRENT request's own `intent`/`normalized_input`, never a
stale or mixed-generation one.

Per this prompt's requirement 11, THIS FILE ADDS NO PRODUCTION
CHANGES - it locks the existing, already-correct behavior down with
focused regression coverage: current-plan publication, A/B isolation,
intent+normalized_input correspondence, normalized<->ordinary
transitions, a simulated planning-failure boundary (via a monkeypatched
`response_planner.plan`, never a production change) followed by
successful recovery, repeated-read stability, and legacy-safe
construction.

Run directly:
    python -m unittest tests.test_response_plan_public_lifecycle_consistency_prompt625 -v
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
from language_intelligence.response_planning import ResponsePlanner, STATUS_RESOLVED, STATUS_UNRESOLVED


def _make_backend():
    return DeterministicFallbackBackend(UnderstandingEngine())


def _make_lic():
    return LanguageIntelligenceCore(backend=_make_backend())


class _RaisingPlanner:
    """A stand-in for `response_planner.plan` that raises once, used
    ONLY to observe the existing, already-implemented failure boundary
    in `_attach_response_plan()` - never a production change; this is a
    test-side monkeypatch of a constructor-supplied collaborator, the
    exact seam `LanguageIntelligenceCore(response_planner=...)` already
    exposes for callers."""

    def plan(self, understanding):
        raise RuntimeError("simulated planning failure")


# ======================================================================
class TestCurrentPlanPublication(unittest.TestCase):
    """`last_response_plan` reflects the plan for the request that was
    just understood, reachable only through the existing public
    attribute - there is no other access path."""

    def test_last_response_plan_matches_the_just_returned_understanding(self):
        lic = _make_lic()
        understanding = lic.understand("What is Python?")
        self.assertIsNotNone(lic.last_response_plan)
        self.assertEqual(lic.last_response_plan.to_dict(), understanding.response_plan)
        self.assertEqual(lic.last_response_plan.normalized_input, "What is Python?")
        self.assertEqual(
            lic.last_response_plan.understanding_state["intent"], INTENT_ASK_QUESTION)

    def test_last_response_plan_is_none_before_any_call(self):
        lic = _make_lic()
        self.assertIsNone(lic.last_response_plan)


# ======================================================================
class TestABRequestIsolation(unittest.TestCase):
    """Request A with intent A + normalized A, then request B with
    intent B + normalized B, on the SAME reused core: `last_response_plan`
    after B must correspond ONLY to B."""

    def test_last_response_plan_after_b_reflects_only_b(self):
        lic = _make_lic()

        understanding_a = lic.understand("What is Python?")
        plan_a_snapshot = lic.last_response_plan.to_dict()
        self.assertEqual(plan_a_snapshot["normalized_input"], "What is Python?")
        self.assertEqual(plan_a_snapshot["understanding_state"]["intent"], INTENT_ASK_QUESTION)

        understanding_b = lic.understand("I need to refactor this function.")
        self.assertIsNot(lic.last_response_plan.to_dict(), plan_a_snapshot)
        self.assertEqual(
            lic.last_response_plan.normalized_input, "I need to refactor this function.")
        self.assertEqual(
            lic.last_response_plan.understanding_state["intent"], INTENT_GOAL_REQUEST)

        # last_response_plan after B must not equal A's values.
        self.assertNotEqual(lic.last_response_plan.normalized_input,
                             plan_a_snapshot["normalized_input"])
        self.assertNotEqual(lic.last_response_plan.understanding_state["intent"],
                             plan_a_snapshot["understanding_state"]["intent"])

        # A's own already-taken snapshot is untouched by B's call.
        self.assertEqual(plan_a_snapshot["normalized_input"], "What is Python?")
        self.assertEqual(understanding_a.intent, INTENT_ASK_QUESTION)
        self.assertEqual(understanding_b.intent, INTENT_GOAL_REQUEST)


# ======================================================================
class TestTransitions(unittest.TestCase):
    """Normalized-input-present -> ordinary/None-equivalent and back;
    intent-category changes - each checked against `last_response_plan`
    directly."""

    def test_normalized_input_present_then_ordinary(self):
        lic = _make_lic()
        lic.understand("   what   is   python?   ")
        self.assertEqual(lic.last_response_plan.normalized_input, "what is python?")
        self.assertNotEqual(
            lic.last_response_plan.normalized_input, lic.last_response_plan.original_message)

        lic.understand("what is python")
        self.assertEqual(lic.last_response_plan.normalized_input, "what is python")

    def test_ordinary_then_normalized_input_present(self):
        lic = _make_lic()
        lic.understand("what is python")
        self.assertEqual(lic.last_response_plan.normalized_input, "what is python")

        lic.understand("   what   is   python?   ")
        self.assertEqual(lic.last_response_plan.normalized_input, "what is python?")

    def test_empty_input_yields_none_equivalent_normalized_input_then_recovers(self):
        lic = _make_lic()
        lic.understand("")
        self.assertEqual(lic.last_response_plan.normalized_input, "")
        self.assertEqual(lic.last_response_plan.understanding_state["intent"], INTENT_UNKNOWN)

        lic.understand("Explain indentation.")
        self.assertEqual(lic.last_response_plan.normalized_input, "Explain indentation.")
        self.assertEqual(
            lic.last_response_plan.understanding_state["intent"], INTENT_REQUEST_ACTION)

    def test_intent_category_changes_across_calls(self):
        lic = _make_lic()
        for raw, expected in (
            ("What is Python?", INTENT_ASK_QUESTION),
            ("Python is a programming language.", INTENT_PROVIDE_INFORMATION),
            ("Explain indentation.", INTENT_REQUEST_ACTION),
            ("I need to refactor this function.", INTENT_GOAL_REQUEST),
        ):
            lic.understand(raw)
            self.assertEqual(lic.last_response_plan.understanding_state["intent"], expected)


# ======================================================================
class TestIntentAndNormalizedInputCorrespondToSameUnderstanding(unittest.TestCase):
    """`ResponsePlan.understanding_state["intent"]` and
    `ResponsePlan.normalized_input`, read off `last_response_plan`,
    must be the SAME values carried by the `LanguageUnderstandingResult`
    that produced them - held object references checked with
    `assertIs`, never `id()`."""

    def test_last_response_plan_holds_the_same_references_as_the_understanding(self):
        lic = _make_lic()
        understanding = lic.understand("What is Python?")
        self.assertIs(lic.last_response_plan.understanding_state["intent"], understanding.intent)
        self.assertIs(lic.last_response_plan.normalized_input, understanding.normalized_input)


# ======================================================================
class TestFailureBoundaryDoesNotExposeStalePlan(unittest.TestCase):
    """A planning failure must never leave the PREVIOUS request's plan
    sitting on `last_response_plan` looking current; it must be reset
    to `None`. A successful call afterward must publish ITS OWN plan
    correctly (recovery)."""

    def test_planning_failure_resets_last_response_plan_not_leaves_stale_one(self):
        backend = _make_backend()
        lic = LanguageIntelligenceCore(backend=backend)

        first = lic.understand("What is Python?")
        self.assertIsNotNone(lic.last_response_plan)
        self.assertEqual(lic.last_response_plan.normalized_input, "What is Python?")

        # Swap in a raising planner to observe the existing, unmodified
        # failure boundary for exactly one call, then restore it.
        real_planner = lic.response_planner
        lic.response_planner = _RaisingPlanner()
        try:
            second = lic.understand("I need to refactor this function.")
        finally:
            lic.response_planner = real_planner

        # The failure must reset last_response_plan to None - never
        # leave the FIRST request's plan looking like it belongs to the
        # second, failed request.
        self.assertIsNone(lic.last_response_plan)
        self.assertIsNone(second.response_plan)
        self.assertTrue(
            any(w.startswith("response_plan_error:") for w in second.warnings))
        # The understanding itself (intent/normalized_input) is still
        # correct for request 2 even though planning failed for it.
        self.assertEqual(second.normalized_input, "I need to refactor this function.")
        self.assertEqual(second.intent, INTENT_GOAL_REQUEST)

    def test_recovery_after_failure_publishes_the_new_requests_own_plan(self):
        backend = _make_backend()
        lic = LanguageIntelligenceCore(backend=backend)

        real_planner = lic.response_planner
        lic.response_planner = _RaisingPlanner()
        try:
            lic.understand("Broken request.")
        finally:
            lic.response_planner = real_planner
        self.assertIsNone(lic.last_response_plan)

        recovered = lic.understand("What is Python?")
        self.assertIsNotNone(lic.last_response_plan)
        self.assertEqual(lic.last_response_plan.normalized_input, "What is Python?")
        self.assertEqual(
            lic.last_response_plan.understanding_state["intent"], INTENT_ASK_QUESTION)
        self.assertEqual(lic.last_response_plan.to_dict(), recovered.response_plan)


# ======================================================================
class TestResolvedUnresolvedResolvedRecoveryThroughRealPipeline(unittest.TestCase):
    """Successful/resolved -> unresolved -> successful/recovered, using
    the existing pipeline's own RESOLVED/UNRESOLVED statuses (not a
    simulated error), mirroring the fixture Prompt 624's own lifecycle
    test already established - reused, not duplicated at length."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        memory = MemorySystem(os.path.join(self._tmpdir.name, "memory.db"))
        items = LanguageLearningStore(memory)
        knowledge = KnowledgeSystem(memory)
        rels = LanguageRelationshipStore(memory, items, knowledge)
        resolver = MeaningResolver(items, rels, knowledge=knowledge)
        disambiguator = LearnedMeaningDisambiguator()
        matcher = LearnedPatternMatcher(items)
        extractor = LearnedSentenceStructureExtractor(matcher)
        teacher = LearnedPatternTeacher(items)
        binder = LearnedPatternMeaningBinder(items, rels, disambiguator)
        backend = DeterministicFallbackBackend(
            UnderstandingEngine(), meaning_resolver=resolver, meaning_disambiguator=disambiguator,
            pattern_matcher=matcher, structure_extractor=extractor, pattern_meaning_binder=binder)
        self.lic = LanguageIntelligenceCore(backend=backend)
        result = teacher.teach("en", "what is {{topic}}", source="unit-test")
        self.assertEqual(result.status, STATUS_CREATED, result.errors)
        bind_result = binder.bind("en", "what is {{topic}}", "ask_question", source="unit-test")
        self.assertTrue(bind_result.success, bind_result.errors)

    def test_resolved_unresolved_resolved_last_response_plan_tracks_current(self):
        self.lic.understand("what is python")
        self.assertEqual(self.lic.last_response_plan.status, STATUS_RESOLVED)
        self.assertEqual(self.lic.last_response_plan.normalized_input, "what is python")

        self.lic.understand("Python is a programming language.")
        self.assertEqual(self.lic.last_response_plan.status, STATUS_UNRESOLVED)
        self.assertEqual(
            self.lic.last_response_plan.normalized_input, "Python is a programming language.")

        self.lic.understand("what is java")
        self.assertEqual(self.lic.last_response_plan.status, STATUS_RESOLVED)
        self.assertEqual(self.lic.last_response_plan.normalized_input, "what is java")
        self.assertEqual(
            self.lic.last_response_plan.understanding_state["intent"], INTENT_ASK_QUESTION)


# ======================================================================
class TestRepeatedReadsDoNotMutateOrRebuild(unittest.TestCase):
    """Reading `last_response_plan` repeatedly must be a plain attribute
    read - no rebuild, no mutation."""

    def test_repeated_attribute_reads_return_the_same_object(self):
        lic = _make_lic()
        lic.understand("What is Python?")
        first_read = lic.last_response_plan
        second_read = lic.last_response_plan
        self.assertIs(first_read, second_read)

    def test_repeated_to_dict_calls_on_last_response_plan_are_stable(self):
        lic = _make_lic()
        lic.understand("  what   is   python?  ")
        first = lic.last_response_plan.to_dict()
        second = lic.last_response_plan.to_dict()
        self.assertEqual(first["normalized_input"], "what is python?")
        self.assertEqual(second["normalized_input"], "what is python?")
        first["normalized_input"] = "MUTATED"
        third = lic.last_response_plan.to_dict()
        self.assertEqual(third["normalized_input"], "what is python?")
        self.assertEqual(lic.last_response_plan.normalized_input, "what is python?")


# ======================================================================
class TestLegacySafeBehavior(unittest.TestCase):
    """`last_response_plan` stays legacy-safe: absent before any call,
    absent when the backend result already carries a plan, and absent
    when planning a non-understanding value would raise - matching the
    documented, unmodified `_attach_response_plan` contract."""

    def test_absent_when_result_already_carries_a_plan(self):
        backend = _make_backend()
        lic = LanguageIntelligenceCore(backend=backend)
        preplanned = LanguageUnderstandingResult(
            original_input="hi there", detected_language="english",
            normalized_input="hi there", intent=INTENT_UNKNOWN, entities=[],
            referenced_items=[], active_topic=None, conversation_context=None,
            confidence=0.5, ambiguity=False, needs_clarification=False,
        )
        preplanned.response_plan = {"already": "planned"}
        result = lic._attach_response_plan(preplanned)
        self.assertIsNone(lic.last_response_plan)
        self.assertEqual(result.response_plan, {"already": "planned"})

    def test_planning_directly_from_a_dict_missing_intent_and_normalized_input(self):
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


if __name__ == "__main__":
    unittest.main()
