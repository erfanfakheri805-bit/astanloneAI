"""
Tests for Prompt 627 - Section 2: Language Intelligence and Request
Understanding - full-lifecycle isolation and correlation verification,
from a REAL `LanguageUnderstandingResult` (not a hand-built
`ResponsePlan`, as Prompts 623-626 already used) all the way through
`ConversationResponse`:

    LanguageUnderstandingResult          (language_understanding_result.py)
      -> ResponsePlanner.plan()          (response_planning.py, Prompt 425)
      -> ResponsePlan
      -> build_generation_context()      (response_generation_context.py)
      -> ResponseGenerationContext
      -> ResponseGenerationRequest/Result (response_generation.py)
      -> build_response_generation_outcome() (response_generation_outcome.py)
      -> ResponseGenerationOutcome
      -> build_conversation_response()   (conversation_response.py)
      -> ConversationResponse

Prompts 609-626 already verified every individual hop of this chain in
isolation (see e.g. test_intent_normalized_input_downstream_publication_
prompt626.py, which starts from a hand-built `ResponsePlan`, and
test_intent_normalized_input_lifecycle_consistency_prompt624.py /
test_intent_propagation_through_decision_pipeline_prompt623.py, which
cover `ResponsePlanner.plan()` statelessness). What none of those files
does is drive the FULL chain starting from a genuine
`LanguageUnderstandingResult` object through `ResponsePlanner.plan()`
itself, or exercise a RESOLVED -> UNRESOLVED -> RESOLVED sequence
through one shared `ResponsePlanner` instance. That is the gap this
file closes.

Finding: the architecture already guarantees the required behavior.
`ResponsePlanner.plan()` is a pure, stateless function of its
`understanding` argument (it deep-copies every field it reads via
`_READ_FIELDS` and stores nothing on `self`), and every downstream
builder (`build_generation_context`, `build_response_generation_outcome`,
`build_conversation_response`) reads only the object it is directly
given. No production changes were needed; this file adds focused
regression coverage only.

Run directly:
    python -m unittest tests.test_request_understanding_full_lifecycle_isolation_prompt627 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import types
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.language_understanding_result import LanguageUnderstandingResult
from language_intelligence.response_planning import (
    ResponsePlanner, STATUS_RESOLVED, STATUS_UNRESOLVED,
)
from language_intelligence.response_generation_context import build_generation_context
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult,
    STATUS_GENERATED, STATUS_MODEL_FAILED,
)
from language_intelligence.response_generation_outcome import (
    build_response_generation_outcome, STATUS_SUCCESS, STATUS_FAILED,
)
from language_intelligence.conversation_response import build_conversation_response


# ----------------------------------------------------------------------
def _make_understanding(original_input, normalized_input, intent, resolved=True,
                         meaning=None):
    """A genuine `LanguageUnderstandingResult`, not a hand-built plan or
    dict. `resolved=True` gives it a real, explicitly bound
    `learned_pattern_meaning` (RESOLVED); `resolved=False` leaves
    `learned_pattern_match`/`learned_pattern_meaning` both `None`, the
    existing "nothing learned at all" UNRESOLVED path
    (`REASON_NO_LEARNED_UNDERSTANDING`)."""
    meaning = meaning if meaning is not None else {"response_action": "greet"}
    learned_pattern_meaning = None
    if resolved:
        learned_pattern_meaning = {
            "status": "RESOLVED",
            "reason": "exactly_one_candidate",
            "meaning": meaning,
            "variables": {},
        }
    return LanguageUnderstandingResult(
        original_input=original_input,
        detected_language="english",
        normalized_input=normalized_input,
        intent=intent,
        entities=[],
        referenced_items=[],
        active_topic=None,
        conversation_context=None,
        confidence=1.0,
        ambiguity=None,
        needs_clarification=False,
        learned_pattern_meaning=learned_pattern_meaning,
    )


def _fake_generation_understanding(plan):
    """The one thing `ResponseGenerationRequest` reads off its
    `understanding` argument at this boundary: `response_plan`, plus
    the additive fields it probes with `getattr(..., None)`."""
    return types.SimpleNamespace(
        response_plan=plan.to_dict(),
        learned_sentence_structure=None,
        correction_application_candidate=None,
        correction_application_result=None,
        learned_knowledge_context=None,
    )


def _run_full_chain(planner, original_input, normalized_input, intent, resolved=True,
                     fail=False):
    """Drives one request through the ENTIRE lifecycle, starting from a
    real `LanguageUnderstandingResult`, and returns every stage's
    object so a test can assert identity/correlation across all of
    them at once."""
    understanding = _make_understanding(original_input, normalized_input, intent,
                                         resolved=resolved)
    plan = planner.plan(understanding)
    context_obj = build_generation_context(plan)
    request = ResponseGenerationRequest(_fake_generation_understanding(plan))
    if fail:
        result = ResponseGenerationResult(
            status=STATUS_MODEL_FAILED, response_text=None, backend_kind="test_backend",
            reason="model failed")
    else:
        result = ResponseGenerationResult(
            status=STATUS_GENERATED, response_text="a generated reply",
            backend_kind="test_backend")
    outcome = build_response_generation_outcome(result, request=request)
    conv = build_conversation_response(result, request=request, outcome=outcome)
    return understanding, plan, context_obj, request, outcome, conv


# ======================================================================
class TestFullChainIdentityFromRealUnderstanding(unittest.TestCase):
    """`original_input`/`normalized_input` starting from a genuine
    `LanguageUnderstandingResult` (never a hand-built `ResponsePlan`)
    stay the SAME object at every hop through `ConversationResponse`,
    and `intent` stays correctly correlated via
    `ResponsePlan.understanding_state`."""

    def test_identity_preserved_end_to_end(self):
        planner = ResponsePlanner()
        held_original = "  What is Python?  "
        held_normalized = "what is python?"
        understanding, plan, context_obj, request, outcome, conv = _run_full_chain(
            planner, held_original, held_normalized, "ask_question")

        # Held references: the real understanding's own attributes.
        self.assertIs(understanding.original_input, held_original)
        self.assertIs(understanding.normalized_input, held_normalized)
        self.assertEqual(understanding.intent, "ask_question")

        # LanguageUnderstandingResult -> ResponsePlan
        self.assertIs(plan.original_message, held_original)
        self.assertIs(plan.normalized_input, held_normalized)
        self.assertEqual(plan.understanding_state["intent"], "ask_question")
        self.assertEqual(plan.status, STATUS_RESOLVED)

        # ResponsePlan -> every downstream stage
        self.assertIs(context_obj.normalized_input, held_normalized)
        self.assertIs(request.generation_context["normalized_input"], held_normalized)
        self.assertIs(outcome.normalized_input, held_normalized)
        self.assertIs(conv.normalized_input, held_normalized)

        # The source understanding is never mutated by any of this.
        self.assertIs(understanding.original_input, held_original)
        self.assertIs(understanding.normalized_input, held_normalized)


# ======================================================================
class TestFullChainRequestAThenRequestBIsolation(unittest.TestCase):
    """Two independently-built real understandings, run through the
    SAME shared `ResponsePlanner` instance, must never cross-
    contaminate at any downstream stage."""

    def test_full_chain_isolation_with_shared_planner(self):
        planner = ResponsePlanner()
        (understanding_a, plan_a, _, _, outcome_a, conv_a) = _run_full_chain(
            planner, "What is Python?", "what is python?", "ask_question")
        (understanding_b, plan_b, _, _, outcome_b, conv_b) = _run_full_chain(
            planner, "I need to build a script.", "i need to build a script.",
            "goal_request")

        # B carries only B's own values, correctly correlated.
        self.assertEqual(conv_b.normalized_input, "i need to build a script.")
        self.assertEqual(plan_b.understanding_state["intent"], "goal_request")
        self.assertIs(conv_b.normalized_input, understanding_b.normalized_input)
        self.assertIs(plan_b.original_message, understanding_b.original_input)

        # Nothing from A leaked into B.
        self.assertIsNot(conv_b.normalized_input, conv_a.normalized_input)
        self.assertNotEqual(conv_b.normalized_input, conv_a.normalized_input)
        self.assertNotEqual(
            plan_b.understanding_state["intent"], plan_a.understanding_state["intent"])

        # A's already-returned objects are untouched by B's construction
        # through the shared planner.
        self.assertEqual(conv_a.normalized_input, "what is python?")
        self.assertEqual(plan_a.understanding_state["intent"], "ask_question")
        self.assertIs(conv_a.normalized_input, understanding_a.normalized_input)
        self.assertIs(outcome_a.normalized_input, understanding_a.normalized_input)
        self.assertIs(understanding_a.original_input, "What is Python?")


# ======================================================================
class TestResolvedUnresolvedResolvedSequence(unittest.TestCase):
    """A RESOLVED -> UNRESOLVED -> RESOLVED sequence through one shared
    `ResponsePlanner`, verifying each plan's `status` and downstream
    publication are correct for THAT request and independent of the
    request immediately before it."""

    def test_resolved_then_unresolved_then_resolved(self):
        planner = ResponsePlanner()

        first = _run_full_chain(
            planner, "Good morning.", "good morning.", "greeting", resolved=True)
        second = _run_full_chain(
            planner, "asdkjalksdj", "asdkjalksdj", None, resolved=False)
        third = _run_full_chain(
            planner, "What is Python?", "what is python?", "ask_question", resolved=True)

        _, plan1, _, _, outcome1, conv1 = first
        _, plan2, _, _, outcome2, conv2 = second
        _, plan3, _, _, outcome3, conv3 = third

        self.assertEqual(plan1.status, STATUS_RESOLVED)
        self.assertEqual(outcome1.status, STATUS_SUCCESS)
        self.assertEqual(conv1.normalized_input, "good morning.")

        self.assertEqual(plan2.status, STATUS_UNRESOLVED)
        self.assertIsNone(plan2.response_action)
        self.assertEqual(conv2.normalized_input, "asdkjalksdj")
        # The UNRESOLVED request carries no trace of the prior RESOLVED one.
        self.assertNotEqual(conv2.normalized_input, conv1.normalized_input)

        self.assertEqual(plan3.status, STATUS_RESOLVED)
        self.assertEqual(outcome3.status, STATUS_SUCCESS)
        self.assertEqual(conv3.normalized_input, "what is python?")
        # The second RESOLVED request carries no trace of the
        # intervening UNRESOLVED one, nor of the first RESOLVED one.
        self.assertNotEqual(conv3.normalized_input, conv2.normalized_input)
        self.assertNotEqual(conv3.normalized_input, conv1.normalized_input)


# ======================================================================
class TestSuccessFailureRecoveryBoundary(unittest.TestCase):
    """A successful request, followed by a failure, followed by a fresh
    successful recovery - all through the SAME shared `ResponsePlanner`
    - must publish only each request's own state; recovery must never
    republish the stale state of the request before the failure."""

    def test_success_then_failure_then_recovery(self):
        planner = ResponsePlanner()

        success = _run_full_chain(
            planner, "What is Python?", "what is python?", "ask_question")
        failure = _run_full_chain(
            planner, "Explain indentation.", "explain indentation.", "request_action",
            fail=True)
        recovery = _run_full_chain(
            planner, "Good morning.", "good morning.", "greeting")

        _, _, _, _, success_outcome, success_conv = success
        _, _, _, _, failure_outcome, failure_conv = failure
        _, recovery_plan, _, _, recovery_outcome, recovery_conv = recovery

        self.assertEqual(success_outcome.status, STATUS_SUCCESS)

        self.assertEqual(failure_outcome.status, STATUS_FAILED)
        self.assertIsNone(failure_outcome.generated_text)
        self.assertEqual(failure_conv.normalized_input, "explain indentation.")
        self.assertEqual(failure_conv.generation_status, STATUS_MODEL_FAILED)

        # Recovery publishes the NEW request's own state, not the
        # failed request's, and not the earlier success's either.
        self.assertEqual(recovery_outcome.status, STATUS_SUCCESS)
        self.assertEqual(recovery_conv.normalized_input, "good morning.")
        self.assertIs(recovery_conv.normalized_input, recovery_plan.normalized_input)
        self.assertNotEqual(recovery_conv.normalized_input, failure_conv.normalized_input)
        self.assertNotEqual(recovery_conv.normalized_input, success_conv.normalized_input)

        # The failed request's own already-returned objects are
        # unaffected by the recovery that came after it.
        self.assertEqual(failure_conv.normalized_input, "explain indentation.")
        self.assertEqual(failure_outcome.status, STATUS_FAILED)


# ======================================================================
class TestRepeatedPlanCallsDoNotMutateOrRebuildState(unittest.TestCase):
    """Calling `ResponsePlanner.plan()` more than once on the SAME
    understanding object never mutates that understanding, and produces
    independently-correlated (but equal) plans each time - never a
    cached/reused plan object."""

    def test_repeated_plan_calls_are_stable_and_non_mutating(self):
        planner = ResponsePlanner()
        understanding = _make_understanding(
            "What is Python?", "what is python?", "ask_question")

        plan_first = planner.plan(understanding)
        # Reading it again must not have changed the source understanding.
        self.assertEqual(understanding.original_input, "What is Python?")
        self.assertEqual(understanding.normalized_input, "what is python?")
        self.assertEqual(understanding.intent, "ask_question")

        plan_second = planner.plan(understanding)
        plan_third = planner.plan(understanding)

        self.assertIsNot(plan_first, plan_second)
        self.assertIsNot(plan_second, plan_third)
        self.assertEqual(plan_first.normalized_input, plan_second.normalized_input)
        self.assertEqual(plan_second.normalized_input, plan_third.normalized_input)
        self.assertEqual(plan_first.status, plan_second.status)
        self.assertEqual(
            plan_first.understanding_state["intent"],
            plan_third.understanding_state["intent"])

    def test_repeated_full_chain_reads_are_stable(self):
        planner = ResponsePlanner()
        _, plan, _, request, outcome, conv = _run_full_chain(
            planner, "What is Python?", "what is python?", "ask_question")

        for _ in range(3):
            self.assertEqual(outcome.normalized_input, "what is python?")
            self.assertEqual(conv.normalized_input, "what is python?")
            self.assertIs(outcome.normalized_input, plan.normalized_input)
            self.assertIs(conv.normalized_input, plan.normalized_input)
            # A fresh dict each read, but the same value inside it.
            first = request.generation_context
            second = request.generation_context
            self.assertIsNot(first, second)
            self.assertIs(first["normalized_input"], second["normalized_input"])


if __name__ == "__main__":
    unittest.main()
