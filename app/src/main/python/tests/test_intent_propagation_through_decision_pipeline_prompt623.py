"""
Tests for Prompt 623 - Section 2: Language Intelligence and Request
Understanding - verifying that the intent value returned by
`DeterministicFallbackBackend._classify_intent(...)` is preserved
correctly through the Language Intelligence decision/planning
pipeline.

Trace performed by this prompt:

    DeterministicFallbackBackend._classify_intent(normalized_text,
        sentence_type)                          (unchanged, Prompt 622)
      -> intent                                  (returned value)
      -> LanguageUnderstandingResult.intent       (language_intelligence/
         deterministic_fallback_backend.py: `understand()` passes the
         SAME `intent` local variable straight into the constructor -
         see that module's `understand()` method)
      -> LanguageIntelligenceCore._attach_response_plan(result)
         (language_intelligence/language_intelligence_core.py) calls
         `ResponsePlanner.plan(result)` and stores the plan's own
         `to_dict()` on `result.response_plan`
      -> ResponsePlanner.plan()                  (language_intelligence/
         response_planning.py) reads `intent` (already in the fixed
         `_READ_FIELDS` tuple) off `understanding.to_dict()` and echoes
         it, VERBATIM, into `ResponsePlan.understanding_state["intent"]`
         - for every plan status (RESOLVED, AMBIGUOUS, and UNRESOLVED
         alike; `understanding_state` is built unconditionally, before
         the RESOLVED/AMBIGUOUS/UNRESOLVED branch is even decided)
      -> ResponsePlan.to_dict()["understanding_state"]["intent"]
         (the existing downstream decision/planning consumer)

Finding: the classified intent is ALREADY stored, unchanged, on
`LanguageUnderstandingResult.intent` at classification time, and is
ALREADY propagated - read-only, verbatim, never re-derived or
re-classified - into `ResponsePlan.understanding_state["intent"]` by
the existing `ResponsePlanner`, which is the one existing downstream
decision/planning consumer that legitimately needs it. There is no
field loss and no second, competing intent representation anywhere on
this path.

Per this prompt's requirement 4, THIS FILE ADDS NO PRODUCTION CHANGES -
it locks the existing, already-correct propagation down with focused
regression coverage. Its central technique (requirement 9) is a spy on
the real `_classify_intent` boundary, run underneath the FULL pipeline
(`DeterministicFallbackBackend` + `LanguageIntelligenceCore` +
`ResponsePlanner`), to confirm the exact value observed at
classification time is the SAME value (via `assertIs`/`assertEqual`,
never `id()`) that surfaces in the response plan's
`understanding_state`.

Run directly:
    python -m unittest tests.test_intent_propagation_through_decision_pipeline_prompt623 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine

from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_understanding_result import (
    LanguageUnderstandingResult, INTENT_ASK_QUESTION, INTENT_PROVIDE_INFORMATION,
    INTENT_REQUEST_ACTION, INTENT_GOAL_REQUEST, INTENT_UNKNOWN,
)
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.response_planning import ResponsePlanner


def _make_backend():
    return DeterministicFallbackBackend(UnderstandingEngine())


def _make_lic():
    return LanguageIntelligenceCore(backend=_make_backend())


class _SpyingClassifyIntent:
    """Context manager that replaces
    `DeterministicFallbackBackend._classify_intent` with a spy that
    records the exact value it returned (as a held object reference,
    not a re-derived copy) while still delegating to the real
    implementation, then restores the original staticmethod on exit."""

    def __init__(self):
        self.calls = []
        self._original = None

    def __enter__(self):
        self._original = DeterministicFallbackBackend.__dict__["_classify_intent"]
        real = self._original.__func__

        def spy(normalized_text, sentence_type):
            result = real(normalized_text, sentence_type)
            self.calls.append((normalized_text, sentence_type, result))
            return result

        DeterministicFallbackBackend._classify_intent = staticmethod(spy)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        DeterministicFallbackBackend._classify_intent = self._original
        return False


# ======================================================================
class TestClassifiedIntentReachesResponsePlanUnderstandingState(unittest.TestCase):
    """Representative intent categories: the value the spy observes at
    the classifier boundary must be the exact value that surfaces on
    the response plan's `understanding_state["intent"]`, through the
    full `LanguageIntelligenceCore` pipeline (classification ->
    understanding -> planning -> plan dict)."""

    def _run(self, raw_text):
        lic = _make_lic()
        with _SpyingClassifyIntent() as spy:
            understanding = lic.understand(raw_text)
        self.assertEqual(len(spy.calls), 1)
        _, _, classified_intent = spy.calls[0]
        return understanding, classified_intent

    def test_ask_question_intent_propagates_to_plan(self):
        understanding, classified = self._run("What is Python?")
        self.assertEqual(classified, INTENT_ASK_QUESTION)
        self.assertIs(understanding.intent, classified)
        self.assertEqual(
            understanding.response_plan["understanding_state"]["intent"], classified)

    def test_provide_information_intent_propagates_to_plan(self):
        understanding, classified = self._run("Python is a programming language.")
        self.assertEqual(classified, INTENT_PROVIDE_INFORMATION)
        self.assertIs(understanding.intent, classified)
        self.assertEqual(
            understanding.response_plan["understanding_state"]["intent"], classified)

    def test_request_action_intent_propagates_to_plan(self):
        understanding, classified = self._run("Explain indentation.")
        self.assertEqual(classified, INTENT_REQUEST_ACTION)
        self.assertIs(understanding.intent, classified)
        self.assertEqual(
            understanding.response_plan["understanding_state"]["intent"], classified)

    def test_goal_request_intent_propagates_to_plan(self):
        understanding, classified = self._run("I need to refactor this function.")
        self.assertEqual(classified, INTENT_GOAL_REQUEST)
        self.assertIs(understanding.intent, classified)
        self.assertEqual(
            understanding.response_plan["understanding_state"]["intent"], classified)


# ======================================================================
class TestNormalizationEffectOnIntentPropagation(unittest.TestCase):
    """Whether or not normalization changes the raw text, the
    classified intent that reaches the plan must be identical to the
    one produced by the classifier for that (normalized) text."""

    def test_normalization_changes_text_intent_still_propagates(self):
        lic = _make_lic()
        raw = "   what   is   python?   "
        understanding = lic.understand(raw)
        self.assertNotEqual(understanding.original_input, understanding.normalized_input)
        self.assertEqual(understanding.normalized_input, "what is python?")
        self.assertEqual(understanding.intent, INTENT_ASK_QUESTION)
        self.assertEqual(
            understanding.response_plan["understanding_state"]["intent"], INTENT_ASK_QUESTION)

    def test_normalization_does_not_change_text_intent_still_propagates(self):
        lic = _make_lic()
        raw = "what is python"
        understanding = lic.understand(raw)
        self.assertEqual(understanding.original_input, understanding.normalized_input)
        self.assertEqual(understanding.intent, INTENT_ASK_QUESTION)
        self.assertEqual(
            understanding.response_plan["understanding_state"]["intent"], INTENT_ASK_QUESTION)


# ======================================================================
class TestUnknownOrMinimalInputIntentPropagation(unittest.TestCase):
    """Empty/minimal input must still resolve to the documented
    INTENT_UNKNOWN and propagate that (not omit the field, not invent
    a different one) into the plan's understanding_state."""

    def test_empty_input(self):
        lic = _make_lic()
        understanding = lic.understand("")
        self.assertEqual(understanding.intent, INTENT_UNKNOWN)
        self.assertEqual(
            understanding.response_plan["understanding_state"]["intent"], INTENT_UNKNOWN)

    def test_none_input(self):
        lic = _make_lic()
        understanding = lic.understand(None)
        self.assertEqual(understanding.intent, INTENT_UNKNOWN)
        self.assertEqual(
            understanding.response_plan["understanding_state"]["intent"], INTENT_UNKNOWN)

    def test_whitespace_only_input(self):
        lic = _make_lic()
        understanding = lic.understand("   \t\n  ")
        self.assertEqual(understanding.intent, INTENT_UNKNOWN)
        self.assertEqual(
            understanding.response_plan["understanding_state"]["intent"], INTENT_UNKNOWN)


# ======================================================================
class TestExactIntentPreservationFromClassifierToPlanObject(unittest.TestCase):
    """Confirm preservation using the `ResponsePlanner`/`ResponsePlan`
    object directly (not just the serialized dict), and using
    `assertIs` for held-reference identity rather than `id()`."""

    def test_response_planner_plan_object_understanding_state_is_same_value(self):
        backend = _make_backend()
        with _SpyingClassifyIntent() as spy:
            understanding = backend.understand("What is Python?")
        _, _, classified_intent = spy.calls[0]
        plan = ResponsePlanner().plan(understanding)
        self.assertIs(plan.understanding_state["intent"], classified_intent)
        self.assertIs(plan.understanding_state["intent"], understanding.intent)

    def test_plan_to_dict_carries_the_same_intent_value(self):
        backend = _make_backend()
        understanding = backend.understand("Build a script that sorts a list.")
        plan = ResponsePlanner().plan(understanding)
        plan_dict = plan.to_dict()
        self.assertEqual(plan_dict["understanding_state"]["intent"], understanding.intent)

    def test_original_input_and_normalized_input_remain_distinct_from_intent(self):
        """The three fields must never collapse into one another on the
        plan: original_input, normalized_input, and the intent stay
        separate, distinguishable values."""
        backend = _make_backend()
        raw = "  What   is   Python?  "
        understanding = backend.understand(raw)
        plan = ResponsePlanner().plan(understanding)
        self.assertEqual(plan.original_message, raw)
        self.assertEqual(plan.normalized_input, "What is Python?")
        self.assertEqual(plan.understanding_state["intent"], INTENT_ASK_QUESTION)
        self.assertNotEqual(plan.original_message, plan.normalized_input)
        self.assertNotIn(plan.understanding_state["intent"], (plan.original_message,
                                                                plan.normalized_input))


# ======================================================================
class TestLegacyConstructionWithoutIntentAwareFields(unittest.TestCase):
    """Legacy callers that construct `LanguageUnderstandingResult` or
    plan directly from a dict lacking some newer, unrelated fields must
    still see `intent` land correctly on the plan - no new
    intent-carrying abstraction was introduced, so nothing new needs to
    be supplied for this to keep working."""

    def test_plan_from_minimal_legacy_understanding_dict(self):
        legacy_dict = {
            "original_input": "hi there",
            "normalized_input": "hi there",
            "detected_language": "english",
            "intent": INTENT_UNKNOWN,
            "confidence": 0.5,
            "ambiguity": False,
            "needs_clarification": False,
        }
        plan = ResponsePlanner().plan(legacy_dict)
        self.assertEqual(plan.understanding_state["intent"], INTENT_UNKNOWN)

    def test_plan_from_legacy_language_understanding_result_object(self):
        legacy = LanguageUnderstandingResult(
            original_input="Build a thing.",
            detected_language="english",
            normalized_input="Build a thing.",
            intent=INTENT_REQUEST_ACTION,
            entities=[],
            referenced_items=[],
            active_topic=None,
            conversation_context=None,
            confidence=0.7,
            ambiguity=False,
            needs_clarification=False,
        )
        plan = ResponsePlanner().plan(legacy)
        self.assertEqual(plan.understanding_state["intent"], INTENT_REQUEST_ACTION)


# ======================================================================
class TestRepeatedReadsDoNotMutateDecisionState(unittest.TestCase):
    """Reading `understanding_state`/`to_dict()` repeatedly must never
    mutate the plan, the understanding, or the propagated intent."""

    def test_repeated_to_dict_calls_do_not_mutate_intent(self):
        backend = _make_backend()
        understanding = backend.understand("What is Python?")
        plan = ResponsePlanner().plan(understanding)
        first = plan.to_dict()
        second = plan.to_dict()
        self.assertEqual(first["understanding_state"]["intent"], INTENT_ASK_QUESTION)
        self.assertEqual(second["understanding_state"]["intent"], INTENT_ASK_QUESTION)
        # Mutating a returned dict must never reach back into the plan
        # or the understanding it was built from.
        first["understanding_state"]["intent"] = "MUTATED"
        third = plan.to_dict()
        self.assertEqual(third["understanding_state"]["intent"], INTENT_ASK_QUESTION)
        self.assertEqual(understanding.intent, INTENT_ASK_QUESTION)
        self.assertEqual(plan.understanding_state["intent"], INTENT_ASK_QUESTION)

    def test_repeated_plan_calls_over_the_same_understanding_are_stable(self):
        backend = _make_backend()
        understanding = backend.understand("Explain indentation.")
        planner = ResponsePlanner()
        plans = [planner.plan(understanding) for _ in range(5)]
        intents = {p.understanding_state["intent"] for p in plans}
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents.pop(), INTENT_REQUEST_ACTION)


# ======================================================================
class TestDifferentInputsDoNotRetainAPreviousIntent(unittest.TestCase):
    """Each call must reflect only its own message's classified
    intent; nothing carries over from a prior call on the same
    backend/planner/core instance."""

    def test_sequential_calls_on_the_same_backend_do_not_leak_intent(self):
        backend = _make_backend()
        planner = ResponsePlanner()

        first_understanding = backend.understand("I need to refactor this function.")
        first_plan = planner.plan(first_understanding)
        self.assertEqual(first_plan.understanding_state["intent"], INTENT_GOAL_REQUEST)

        second_understanding = backend.understand("What is Python?")
        second_plan = planner.plan(second_understanding)
        self.assertEqual(second_plan.understanding_state["intent"], INTENT_ASK_QUESTION)

        third_understanding = backend.understand("")
        third_plan = planner.plan(third_understanding)
        self.assertEqual(third_plan.understanding_state["intent"], INTENT_UNKNOWN)

        # Re-checking the first plan/understanding confirms nothing was
        # mutated by the later calls.
        self.assertEqual(first_plan.understanding_state["intent"], INTENT_GOAL_REQUEST)
        self.assertEqual(first_understanding.intent, INTENT_GOAL_REQUEST)

    def test_sequential_calls_through_full_core_do_not_leak_intent(self):
        lic = _make_lic()
        results = []
        for raw in ("Explain indentation.", "Python is a programming language.",
                    "What is Python?", "I need to refactor this function."):
            results.append(lic.understand(raw))

        expected = [
            INTENT_REQUEST_ACTION, INTENT_PROVIDE_INFORMATION,
            INTENT_ASK_QUESTION, INTENT_GOAL_REQUEST,
        ]
        for understanding, expected_intent in zip(results, expected):
            self.assertEqual(understanding.intent, expected_intent)
            self.assertEqual(
                understanding.response_plan["understanding_state"]["intent"], expected_intent)


if __name__ == "__main__":
    unittest.main()
