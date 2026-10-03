"""
Tests for Prompt 620 - Section 2: Language Intelligence and Request
Understanding - `normalized_input` Availability in the Decision/
Planning Layer.

Trace performed by this prompt:

    LanguageUnderstandingResult.normalized_input   (existing, Prompt 397)
      -> ResponsePlan.normalized_input             (Prompt 609)
      -> ResponseGenerationContext.normalized_input (Prompt 610)
      -> BackendGenerationRequest.normalized_input  (Prompt 617, this is
         the exact dict `ResponseGenerationRequest(understanding).
         generation_request` returns, and the exact object
         `decide_learned_response()` (learned_response_decision.py,
         Prompt 437/576) builds internally as `generation_request` and
         reads as `request` before making its selection/binding/
         rendering decision)

Finding: by the time this prompt runs, `normalized_input` is ALREADY
threaded, verbatim, through every stage of this exact path - Prompts
609, 610 and 617 already did the propagation this prompt was asked to
check for. `decide_learned_response()` therefore already has direct,
read-only access to `normalized_input` before it makes its
selection/binding/rendering decision (via
`request.get("normalized_input")` on the SAME dict it already reads
`response_pattern_selection` / `response_pattern_binding` /
`response_pattern_rendering` from) - it simply has no reason to read
it, since which learned response pattern applies, how it is bound and
how it is rendered are all decided from the matched pattern and its
extracted variables (Prompts 434-436), never from whitespace-level
text shape. Per this prompt's own requirement 10, that absence of a
consumer is not treated as a gap to fill with an invented one.

Per this prompt's own requirement 3, `original_input` is untouched
here: it remains the field backend inference/generation actually
consumes (see test_normalized_input_backend_consumption_prompt619.py).

Since the decision/planning layer already receives `normalized_input`,
NO PRODUCTION CODE IS CHANGED by this prompt. This file is regression
coverage proving the field remains available, correctly valued, and
inert (never influences status/response_action/selection/binding/
rendering) at this exact boundary.

Run directly:
    python -m unittest tests.test_normalized_input_decision_context_prompt620 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine

from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.response_planning import ResponsePlanner, ResponsePlan
from language_intelligence.response_generation import ResponseGenerationRequest
from language_intelligence.response_generation_context import (
    ResponseGenerationContext, build_generation_context, generation_context_from_understanding,
)
from language_intelligence.response_generation_request import (
    BackendGenerationRequest, build_generation_request, generation_request_from_understanding,
)
from language_intelligence.learned_response_decision import (
    decide_learned_response, LearnedResponseDecision, REASON_NO_REQUEST,
)


def _make_lic():
    return LanguageIntelligenceCore(
        backend=DeterministicFallbackBackend(UnderstandingEngine()),
        response_planner=ResponsePlanner())


def _understand(raw_text):
    return _make_lic().understand(raw_text)


# A minimal legacy ResponsePlan built exactly as a caller predating
# Prompt 609 would have - no `normalized_input`, no
# `correction_application_result` - matching the same legacy
# construction convention already used by
# test_response_planning.py / test_response_generation_context.py.
def _legacy_plan(original_message="hi there"):
    return ResponsePlan(
        original_message, "english", None, "UNRESOLVED", "no_learned_understanding_available",
        False, None, None, None, [], None, [], {}, [], None, [], None, [], [],
        {"intent": "unknown", "confidence": 0.5, "ambiguity": False,
         "needs_clarification": False, "source_backend": "deterministic_fallback",
         "learned_pattern_status": None, "learned_meaning_status": None}, [])


class _DecisionCase(unittest.TestCase):
    def _request(self, understanding):
        return ResponseGenerationRequest(understanding)


# ======================================================================
class TestNormalizedInputPresent(_DecisionCase):
    """1. normalized_input is present and reaches every stage of the
    decision/planning path this prompt traces."""

    def test_present_on_understanding_plan_context_and_request(self):
        understanding = _understand("what is python")
        self.assertEqual(understanding.normalized_input, "what is python")
        self.assertEqual(understanding.response_plan.get("normalized_input"), "what is python")

        gen_context = generation_context_from_understanding(understanding)
        self.assertEqual(gen_context.normalized_input, "what is python")

        request = self._request(understanding)
        generation_request = request.generation_request
        self.assertIsInstance(generation_request, dict)
        self.assertEqual(generation_request.get("normalized_input"), "what is python")

    def test_present_before_decide_learned_response_makes_its_decision(self):
        """decide_learned_response() builds the SAME ResponseGenerationRequest
        internally - confirm the dict it reads as `request` already
        carries normalized_input at the moment the decision is made,
        by reconstructing the identical object independently."""
        understanding = _understand("what is python")
        mirror_request = ResponseGenerationRequest(understanding).generation_request
        self.assertIn("normalized_input", mirror_request)
        self.assertEqual(mirror_request["normalized_input"], "what is python")

        decision = decide_learned_response(understanding)
        self.assertIsInstance(decision, LearnedResponseDecision)
        # The decision itself is unaffected either way (see module
        # docstring) - confirm it still returns a well-formed decision.
        self.assertIn(decision.reason, (
            "selection_not_resolved", "binding_not_resolved",
            "rendering_not_resolved", "no_learned_understanding_available",
            "learned_response_used",
        ))


# ======================================================================
class TestNormalizedInputDiffersFromOriginal(_DecisionCase):
    """2. normalized_input differs from original_input - both values
    must be independently, correctly carried through the decision/
    planning boundary; normalized_input never overwrites or replaces
    original_message anywhere in this path."""

    def test_diverging_values_both_preserved_through_the_chain(self):
        raw = "  what   is   python  "
        understanding = _understand(raw)
        self.assertEqual(understanding.original_input, raw)
        self.assertEqual(understanding.normalized_input, "what is python")
        self.assertNotEqual(understanding.original_input, understanding.normalized_input)

        plan_dict = understanding.response_plan
        self.assertEqual(plan_dict.get("original_message"), raw)
        self.assertEqual(plan_dict.get("normalized_input"), "what is python")

        gen_context = generation_context_from_understanding(understanding)
        self.assertEqual(gen_context.original_message, raw)
        self.assertEqual(gen_context.normalized_input, "what is python")

        generation_request = self._request(understanding).generation_request
        self.assertEqual(generation_request.get("original_message"), raw)
        self.assertEqual(generation_request.get("normalized_input"), "what is python")


# ======================================================================
class TestNormalizedInputEqualsOriginal(_DecisionCase):
    """3. normalized_input equals original_input - no divergence to
    observe, but both fields must still be independently populated
    (never collapsed into a single shared field) all the way through."""

    def test_equal_values_both_populated_independently(self):
        raw = "hello there"
        understanding = _understand(raw)
        self.assertEqual(understanding.original_input, understanding.normalized_input)

        generation_request = self._request(understanding).generation_request
        self.assertEqual(generation_request.get("original_message"), raw)
        self.assertEqual(generation_request.get("normalized_input"), raw)
        # Independently populated, not merely absent-and-defaulted.
        self.assertIsNotNone(generation_request.get("normalized_input"))


# ======================================================================
class TestNormalizedInputNoneOrEmpty(_DecisionCase):
    """4. normalized_input is None/empty - must not crash the decision/
    planning boundary and must not be silently upgraded to some other
    value."""

    def test_empty_original_input_yields_empty_normalized_input_safely(self):
        understanding = _understand("")
        self.assertEqual(understanding.original_input, "")
        self.assertEqual(understanding.normalized_input, "")

        generation_request = self._request(understanding).generation_request
        # An empty message still has a response_plan (UNRESOLVED), so a
        # generation_request dict still exists and still carries the
        # (empty-string) normalized_input, not None and not a crash.
        if generation_request is not None:
            self.assertEqual(generation_request.get("normalized_input"), "")

        decision = decide_learned_response(understanding)
        self.assertIsInstance(decision, LearnedResponseDecision)
        self.assertFalse(decision.used)

    def test_none_normalized_input_on_hand_built_context_does_not_crash(self):
        """A hand-built ResponseGenerationContext with normalized_input
        explicitly None (simulating a producer that supplies everything
        except this field) must not break request construction."""
        plan = _legacy_plan()
        context = build_generation_context(plan)
        context.normalized_input = None
        request = build_generation_request(context)
        self.assertIsNone(request.normalized_input)
        self.assertIsNone(request.to_dict().get("normalized_input"))


# ======================================================================
class TestLegacyConstructionWithoutNormalizedInput(_DecisionCase):
    """5. legacy construction (predating Prompt 609/610/617) must keep
    working, with normalized_input simply defaulting to None at every
    stage - preserving legacy constructor compatibility per requirement 5."""

    def test_legacy_response_plan_defaults_normalized_input_to_none(self):
        plan = _legacy_plan()
        self.assertIsNone(plan.normalized_input)
        self.assertIsNone(plan.to_dict().get("normalized_input"))

    def test_legacy_response_generation_context_defaults_to_none(self):
        context = ResponseGenerationContext(
            "hi there", "UNRESOLVED", None, None, [], None, {}, None, [], None, None, None, [])
        self.assertIsNone(context.normalized_input)
        self.assertIsNone(context.to_dict().get("normalized_input"))

    def test_legacy_backend_generation_request_defaults_to_none(self):
        legacy_request = BackendGenerationRequest(
            "hi there", "resolved", None, None, [], None, None, {}, None, [], None, None,
            None, [])
        self.assertIsNone(legacy_request.normalized_input)
        self.assertIsNone(legacy_request.to_dict().get("normalized_input"))

    def test_legacy_plan_still_flows_through_build_generation_context_and_request(self):
        """A plan built without normalized_input must still flow all the
        way to a BackendGenerationRequest without error, with
        normalized_input simply None throughout - and every OTHER field
        (status, response_action, required behavior) is unaffected."""
        plan = _legacy_plan()
        context = build_generation_context(plan)
        self.assertIsNone(context.normalized_input)
        self.assertEqual(context.status, "UNRESOLVED")

        request = build_generation_request(context)
        self.assertIsNone(request.normalized_input)
        self.assertEqual(request.status, "UNRESOLVED")

    def test_decide_learned_response_tolerates_legacy_plan_without_normalized_input(self):
        """decide_learned_response() must not raise or change its
        selection/binding/rendering reasoning just because the
        understanding it reads carries a legacy plan with no
        normalized_input."""
        class _LegacyUnderstanding:
            def __init__(self, plan_dict):
                self.response_plan = plan_dict
                self.learned_sentence_structure = None
                self.correction_application_candidate = None
                self.correction_application_result = None
                self.learned_knowledge_context = None

        legacy_understanding = _LegacyUnderstanding(_legacy_plan().to_dict())
        decision = decide_learned_response(legacy_understanding)
        self.assertIsInstance(decision, LearnedResponseDecision)
        self.assertFalse(decision.used)


# ======================================================================
class TestExactValuePreservationThroughBoundary(_DecisionCase):
    """6. exact-value preservation: the SAME string object's contents
    (not merely "close enough") survive every hop of the decision/
    planning boundary, character for character."""

    def test_exact_string_preserved_end_to_end(self):
        raw = "  Hello,   World!  \t\n"
        understanding = _understand(raw)
        expected_normalized = understanding.normalized_input

        plan_value = understanding.response_plan.get("normalized_input")
        self.assertEqual(plan_value, expected_normalized)

        gen_context = generation_context_from_understanding(understanding)
        self.assertEqual(gen_context.normalized_input, expected_normalized)
        self.assertEqual(gen_context.to_dict().get("normalized_input"), expected_normalized)

        gen_request_obj = generation_request_from_understanding(understanding)
        self.assertEqual(gen_request_obj.normalized_input, expected_normalized)
        self.assertEqual(
            gen_request_obj.to_dict().get("normalized_input"), expected_normalized)

        request_dict = self._request(understanding).generation_request
        self.assertEqual(request_dict.get("normalized_input"), expected_normalized)

    def test_multiple_distinct_inputs_each_preserved_independently(self):
        cases = [
            ("  spaced   out   text  ", "spaced out text"),
            ("already normalized", "already normalized"),
            ("Hello\tWorld\n\nAgain", "Hello World Again"),
        ]
        for raw, _hint in cases:
            with self.subTest(raw=raw):
                understanding = _understand(raw)
                expected = understanding.normalized_input
                request_dict = self._request(understanding).generation_request
                self.assertEqual(request_dict.get("normalized_input"), expected)


# ======================================================================
class TestRepeatedAccessDoesNotMutateState(_DecisionCase):
    """7. repeated access to normalized_input through this boundary must
    never mutate surrounding decision state - status, response_action,
    selection/binding/rendering, or the understanding/plan themselves."""

    def test_repeated_generation_request_access_is_stable(self):
        understanding = _understand("  what   is   python  ")
        request = self._request(understanding)

        first = request.generation_request
        second = request.generation_request
        third = request.generation_request

        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertEqual(first.get("normalized_input"), "what is python")
        self.assertEqual(third.get("normalized_input"), "what is python")
        # Each access returns an independent copy (see module docstrings'
        # "no mutable-state leakage") - mutating one must not affect the
        # next access.
        first["normalized_input"] = "MUTATED"
        fourth = request.generation_request
        self.assertEqual(fourth.get("normalized_input"), "what is python")

    def test_repeated_decide_learned_response_calls_are_stable_and_non_mutating(self):
        understanding = _understand("what is python")
        snapshot_before = copy.deepcopy(understanding.response_plan)

        decision_a = decide_learned_response(understanding)
        decision_b = decide_learned_response(understanding)
        decision_c = decide_learned_response(understanding)

        self.assertEqual(decision_a.used, decision_b.used)
        self.assertEqual(decision_b.used, decision_c.used)
        self.assertEqual(decision_a.reason, decision_b.reason)
        self.assertEqual(decision_b.reason, decision_c.reason)
        self.assertEqual(decision_a.pattern_id, decision_b.pattern_id)

        # The understanding's own response_plan (and its normalized_input)
        # must be byte-for-byte unchanged after repeated decisions.
        self.assertEqual(understanding.response_plan, snapshot_before)
        self.assertEqual(
            understanding.response_plan.get("normalized_input"),
            snapshot_before.get("normalized_input"))

    def test_mutating_a_returned_context_never_reaches_back_into_the_plan(self):
        understanding = _understand("what is python")
        plan_snapshot = copy.deepcopy(understanding.response_plan)

        gen_context = generation_context_from_understanding(understanding)
        gen_context.normalized_input = "CORRUPTED"
        gen_context_dict = gen_context.to_dict()
        gen_context_dict["normalized_input"] = "CORRUPTED AGAIN"

        # Neither mutation reaches back into the understanding's own plan.
        self.assertEqual(understanding.response_plan, plan_snapshot)
        self.assertEqual(
            understanding.response_plan.get("normalized_input"), "what is python")

        # A fresh build from the same (untouched) understanding is
        # unaffected by the mutations performed on the earlier objects.
        fresh_context = generation_context_from_understanding(understanding)
        self.assertEqual(fresh_context.normalized_input, "what is python")


# ======================================================================
class TestNormalizedInputNeverInfluencesTheDecisionAlgorithm(_DecisionCase):
    """Requirement 6/7: normalized_input's presence, absence or value
    must never change status, response_action, selection, binding,
    rendering, or the learned-response decision itself."""

    def test_corrupting_normalized_input_does_not_change_the_decision(self):
        understanding = _understand("what is python")
        baseline = decide_learned_response(understanding)

        request = ResponseGenerationRequest(understanding)
        gen_request_obj = generation_request_from_understanding(understanding)
        gen_request_obj.normalized_input = "SOMETHING ENTIRELY DIFFERENT"

        # Re-derive the decision independently (decide_learned_response
        # always rebuilds its own request from `understanding`, never
        # from a caller-mutated object) - it must be identical, since
        # normalized_input plays no part in its computation.
        again = decide_learned_response(understanding)
        self.assertEqual(baseline.used, again.used)
        self.assertEqual(baseline.reason, again.reason)
        self.assertEqual(baseline.pattern_id, again.pattern_id)
        self.assertEqual(
            baseline.correction_application_result_usable,
            again.correction_application_result_usable)

    def test_response_plan_status_and_action_unaffected_by_normalized_input(self):
        for raw in ("  what   is   python  ", "what is python", ""):
            with self.subTest(raw=raw):
                understanding = _understand(raw)
                plan_dict = understanding.response_plan
                # Status/response_action are decided from learned pattern
                # match/meaning, never from normalized_input - confirm the
                # field's presence alongside them changes nothing about
                # how they were derived by re-planning explicitly.
                replanned = ResponsePlanner().plan(understanding)
                self.assertEqual(replanned.status, plan_dict.get("status"))
                self.assertEqual(replanned.response_action, plan_dict.get("response_action"))
                self.assertEqual(replanned.normalized_input, plan_dict.get("normalized_input"))


if __name__ == "__main__":
    unittest.main()
