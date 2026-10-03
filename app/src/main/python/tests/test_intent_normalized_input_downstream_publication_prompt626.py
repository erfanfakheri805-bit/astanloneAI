"""
Tests for Prompt 626 - Section 2: Language Intelligence and Request
Understanding - verifying the final publication boundary from
`ResponsePlan` into the existing downstream response-generation
context, so `intent` and `normalized_input` stay correlated to the
SAME request and can never become mixed or stale.

Trace verified by this prompt:

    ResponsePlan                              (response_planning.py,
                                                Prompt 425/609/623)
      -> ResponseGenerationContext            (response_generation_context.py,
         build_generation_context()            Prompt 426/610)
      -> ResponseGenerationOutcome            (response_generation_outcome.py,
         build_response_generation_outcome()   Prompt 428/611)
      -> ConversationResponse                 (conversation_response.py,
         build_conversation_response()          Prompt 431/612)

Finding: `normalized_input` is already threaded, read-only and
verbatim, through every one of these four stages - Prompts 609, 610,
611 and 612 already did the propagation this prompt was asked to
verify. Each stage either deep-copies a dict containing the value
(`ResponsePlan.to_dict()`, `ResponseGenerationContext.to_dict()`) or
reads it straight off an attribute (`_normalized_input()`,
`build_conversation_response()`'s own `getattr(outcome,
"normalized_input", None)`); `copy.deepcopy` treats `str` as an atomic
type and returns the identical object rather than a new one, so the
exact same string object a `ResponsePlan` was built with is still the
object every downstream stage carries - verified below with
`assertIs`, never `id()`.

`intent` is NOT one of these already-exposed fields: it exists only
inside `ResponsePlan.understanding_state["intent"]` (Prompt 623) and is
never read by `build_generation_context()`, `ResponseGenerationContext`,
`build_response_generation_outcome()`, `ResponseGenerationOutcome`,
`build_conversation_response()`, or `ConversationResponse` - none of
those modules' `_READ_FIELDS`/constructors/docstrings mention it. Per
this prompt's requirement 5, that is not a gap this file invents new
architecture to fill; it is simply confirmed, with a direct `hasattr`
check, to be the existing, correct scope of what is published past
`ResponsePlan` today.

Per this prompt's requirement 9, THIS FILE ADDS NO PRODUCTION CHANGES -
the existing publication boundary is already correct. It is locked
down here with focused regression coverage: identity-preserving
same-request correspondence at every hop, A/B request-lifecycle
isolation (using held references and `assertIs`, never raw `id()`
comparisons), every requested transition shape, a failure/recovery
sequence, repeated-read stability, and legacy-safe construction when
`normalized_input` is absent.

Run directly:
    python -m unittest tests.test_intent_normalized_input_downstream_publication_prompt626 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import types
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_planning import (
    ResponsePlan, STATUS_RESOLVED, STATUS_UNRESOLVED,
)
from language_intelligence.response_generation_context import (
    ResponseGenerationContext, build_generation_context,
)
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult,
    STATUS_GENERATED, STATUS_MODEL_FAILED,
)
from language_intelligence.response_generation_outcome import (
    build_response_generation_outcome,
    STATUS_SUCCESS, STATUS_FAILED,
)
from language_intelligence.conversation_response import build_conversation_response


# ----------------------------------------------------------------------
def _bare_plan_kwargs():
    """A minimal, valid set of `ResponsePlan` constructor kwargs - the
    same "hand-built plan" posture other test modules' own
    `_bare_plan_kwargs()`/`_base_plan_kwargs()` helpers already use
    (see e.g. test_response_generation_context.py)."""
    return dict(
        original_message="hi", detected_language="english", locale=None,
        status=STATUS_UNRESOLVED, reason=None, needs_clarification=False,
        response_action=None, response_action_source=None,
        meaning=None, meaning_candidates=[], matched_pattern=None,
        pattern_candidates=[], variables={}, expression_meanings=[],
        active_topic=None, references=[], context=None, required_items=[],
        unresolved_requirements=[], understanding_state={}, warnings=[])


def _make_plan(original_message, normalized_input=None, intent=None):
    kwargs = _bare_plan_kwargs()
    kwargs["original_message"] = original_message
    kwargs["understanding_state"] = {"intent": intent}
    return ResponsePlan(normalized_input=normalized_input, **kwargs)


def _fake_understanding(plan):
    """The one thing `ResponseGenerationRequest` actually reads off its
    `understanding` argument for this boundary: `response_plan` (the
    plan's own `to_dict()`, exactly as `LanguageIntelligenceCore`
    attaches it) plus the additive, optional fields it also probes with
    `getattr(..., None)`. A plain namespace, not a new subsystem."""
    return types.SimpleNamespace(
        response_plan=plan.to_dict(),
        learned_sentence_structure=None,
        correction_application_candidate=None,
        correction_application_result=None,
        learned_knowledge_context=None,
    )


def _build_chain(original_message, normalized_input, intent,
                  response_text="a generated reply", backend_kind="test_backend"):
    """The full existing publication chain, built from one request's own
    values: ResponsePlan -> ResponseGenerationContext ->
    ResponseGenerationRequest -> ResponseGenerationResult ->
    ResponseGenerationOutcome -> ConversationResponse."""
    plan = _make_plan(original_message, normalized_input=normalized_input, intent=intent)
    context_obj = build_generation_context(plan)
    request = ResponseGenerationRequest(_fake_understanding(plan))
    result = ResponseGenerationResult(
        status=STATUS_GENERATED, response_text=response_text, backend_kind=backend_kind)
    outcome = build_response_generation_outcome(result, request=request)
    conversation_response = build_conversation_response(result, request=request, outcome=outcome)
    return plan, context_obj, request, result, outcome, conversation_response


def _build_failed_chain(original_message, normalized_input, intent):
    """Same chain, but the underlying `ResponseGenerationResult` is a
    model failure with no fallback backend configured - the existing
    FAILED outcome path."""
    plan = _make_plan(original_message, normalized_input=normalized_input, intent=intent)
    context_obj = build_generation_context(plan)
    request = ResponseGenerationRequest(_fake_understanding(plan))
    result = ResponseGenerationResult(
        status=STATUS_MODEL_FAILED, response_text=None, backend_kind="test_backend",
        reason="model failed")
    outcome = build_response_generation_outcome(result, request=request)
    conversation_response = build_conversation_response(result, request=request, outcome=outcome)
    return plan, context_obj, request, result, outcome, conversation_response


# ======================================================================
class TestSameRequestIdentityAtEveryHop(unittest.TestCase):
    """`normalized_input` on a single request's `ResponsePlan` is the
    SAME string object on every downstream stage - `assertIs`, never
    `id()`, and always against a held reference to the original plan's
    own attribute."""

    def test_identity_preserved_context_outcome_conversation_response(self):
        held_normalized_input = "  What is Python?  ".strip()
        plan, context_obj, request, result, outcome, conv = _build_chain(
            "  What is Python?  ", held_normalized_input, "ask_question")

        # Held reference: the plan's own attribute.
        self.assertIs(plan.normalized_input, held_normalized_input)
        # ResponsePlan -> ResponseGenerationContext
        self.assertIs(context_obj.normalized_input, held_normalized_input)
        # ResponseGenerationContext -> the dict a backend actually reads
        # (ResponseGenerationRequest.generation_context)
        self.assertIs(request.generation_context["normalized_input"], held_normalized_input)
        # ResponseGenerationContext -> ResponseGenerationOutcome
        self.assertIs(outcome.normalized_input, held_normalized_input)
        # ResponseGenerationOutcome -> ConversationResponse
        self.assertIs(conv.normalized_input, held_normalized_input)

    def test_plan_to_dict_preserves_identity_too(self):
        """`ResponsePlan.to_dict()` deep-copies the whole structure, but
        `copy.deepcopy` treats `str` as atomic - the value inside the
        dict is still the exact object the plan was built with."""
        held = "explain indentation"
        plan = _make_plan("Explain indentation.", normalized_input=held, intent="request_action")
        self.assertIs(plan.to_dict()["normalized_input"], held)
        # Stable across repeated calls too.
        self.assertIs(plan.to_dict()["normalized_input"], held)


# ======================================================================
class TestIntentStaysScopedToResponsePlan(unittest.TestCase):
    """`intent` is only ever exposed on `ResponsePlan.understanding_state`
    (Prompt 623) - never read, forwarded, or re-derived by any of the
    three downstream stages. Confirmed directly, not assumed."""

    def test_intent_present_on_plan_understanding_state(self):
        plan = _make_plan("I need to refactor this.", normalized_input="i need to refactor this.",
                           intent="goal_request")
        self.assertEqual(plan.understanding_state["intent"], "goal_request")
        self.assertEqual(plan.to_dict()["understanding_state"]["intent"], "goal_request")

    def test_intent_not_exposed_on_any_downstream_object(self):
        plan, context_obj, request, result, outcome, conv = _build_chain(
            "I need to refactor this.", "i need to refactor this.", "goal_request")

        self.assertFalse(hasattr(context_obj, "intent"))
        self.assertNotIn("intent", request.generation_context)
        self.assertFalse(hasattr(outcome, "intent"))
        self.assertFalse(hasattr(conv, "intent"))
        # The plan itself is unaffected by that absence downstream.
        self.assertEqual(plan.understanding_state["intent"], "goal_request")


# ======================================================================
class TestRequestAThenRequestBIsolation(unittest.TestCase):
    """Request A's `intent`/`normalized_input` must never appear on any
    downstream object built for request B, and building B must never
    retroactively change anything already returned for A."""

    def test_full_chain_isolation(self):
        (plan_a, context_a, request_a, result_a, outcome_a,
         conv_a) = _build_chain("What is Python?", "what is python?", "ask_question")
        (plan_b, context_b, request_b, result_b, outcome_b,
         conv_b) = _build_chain("I need to build a script.", "i need to build a script.",
                                 "goal_request")

        # B contains only B's own values.
        self.assertEqual(conv_b.normalized_input, "i need to build a script.")
        self.assertEqual(plan_b.understanding_state["intent"], "goal_request")
        self.assertIs(conv_b.normalized_input, plan_b.normalized_input)

        # None of B's objects carry anything from A.
        self.assertNotEqual(conv_b.normalized_input, conv_a.normalized_input)
        self.assertIsNot(conv_b.normalized_input, conv_a.normalized_input)
        self.assertNotEqual(
            plan_b.understanding_state["intent"], plan_a.understanding_state["intent"])

        # A's own already-returned objects are untouched by B's construction.
        self.assertEqual(conv_a.normalized_input, "what is python?")
        self.assertEqual(plan_a.understanding_state["intent"], "ask_question")
        self.assertIs(conv_a.normalized_input, plan_a.normalized_input)
        self.assertIs(outcome_a.normalized_input, plan_a.normalized_input)
        self.assertIs(context_a.normalized_input, plan_a.normalized_input)

    def test_shared_understanding_state_dict_does_not_leak_between_plans(self):
        """Two plans built from two SEPARATE `understanding_state` dict
        literals (the normal case) never share state; mutating one
        plan's dict after the fact cannot reach the other plan's
        already-published `to_dict()` snapshot, because `to_dict()`
        deep-copies the container itself (only the atomic string
        values inside are identity-preserved)."""
        state_a = {"intent": "ask_question"}
        state_b = {"intent": "goal_request"}
        kwargs = _bare_plan_kwargs()
        del kwargs["understanding_state"]
        plan_a = ResponsePlan(understanding_state=state_a, normalized_input="a", **kwargs)
        plan_b = ResponsePlan(understanding_state=state_b, normalized_input="b", **kwargs)

        snapshot_a = plan_a.to_dict()
        state_a["intent"] = "mutated_after_publication"

        self.assertEqual(snapshot_a["understanding_state"]["intent"], "ask_question")
        self.assertEqual(plan_b.understanding_state["intent"], "goal_request")


# ======================================================================
class TestFailureAndRecoveryBoundary(unittest.TestCase):
    """A failed/unresolved boundary must still correctly forward
    `normalized_input` (it comes from the request's own generation
    context, independent of the underlying result's status), and a
    fresh subsequent request must produce a cleanly correlated,
    non-contaminated downstream state."""

    def test_normalized_input_survives_a_failed_outcome(self):
        plan, context_obj, request, result, outcome, conv = _build_failed_chain(
            "Explain indentation.", "explain indentation.", "request_action")

        self.assertEqual(outcome.status, STATUS_FAILED)
        self.assertIsNone(outcome.generated_text)
        self.assertIs(outcome.normalized_input, plan.normalized_input)
        self.assertIs(conv.normalized_input, plan.normalized_input)
        self.assertEqual(conv.generation_status, STATUS_MODEL_FAILED)

    def test_recovery_after_failure_is_freshly_correlated(self):
        failed = _build_failed_chain(
            "Explain indentation.", "explain indentation.", "request_action")
        failed_plan, _, _, _, failed_outcome, failed_conv = failed

        recovered_plan, _, _, recovered_result, recovered_outcome, recovered_conv = _build_chain(
            "What is Python?", "what is python?", "ask_question")

        self.assertEqual(recovered_outcome.status, STATUS_SUCCESS)
        self.assertEqual(recovered_conv.normalized_input, "what is python?")
        self.assertIs(recovered_conv.normalized_input, recovered_plan.normalized_input)

        # No trace of the failed request's values leaked into recovery.
        self.assertNotEqual(recovered_conv.normalized_input, failed_conv.normalized_input)
        self.assertIsNot(recovered_conv.normalized_input, failed_outcome.normalized_input)

        # The failed request's own already-returned objects are unchanged.
        self.assertEqual(failed_conv.normalized_input, "explain indentation.")
        self.assertIs(failed_conv.normalized_input, failed_plan.normalized_input)


# ======================================================================
class TestRepeatedReadStability(unittest.TestCase):
    """Reading the same downstream object's `normalized_input` (or
    rebuilding the request's `generation_context` dict) repeatedly must
    always report the same value - a fresh dict each time
    (`to_dict()`/`generation_context` are not cached), but never a
    different value."""

    def test_repeated_generation_context_reads_are_fresh_but_equal(self):
        plan, context_obj, request, result, outcome, conv = _build_chain(
            "What is Python?", "what is python?", "ask_question")

        first = request.generation_context
        second = request.generation_context
        self.assertIsNot(first, second)
        self.assertEqual(first["normalized_input"], second["normalized_input"])
        self.assertIs(first["normalized_input"], second["normalized_input"])

    def test_repeated_outcome_and_conversation_response_reads_are_stable(self):
        plan, context_obj, request, result, outcome, conv = _build_chain(
            "What is Python?", "what is python?", "ask_question")

        for _ in range(3):
            self.assertEqual(outcome.normalized_input, "what is python?")
            self.assertEqual(conv.normalized_input, "what is python?")
            self.assertIs(outcome.normalized_input, plan.normalized_input)
            self.assertIs(conv.normalized_input, plan.normalized_input)


# ======================================================================
class TestTransitionShapes(unittest.TestCase):
    """Every requested transition shape, at this boundary: both values
    present, normalized-input present -> ordinary/None, ordinary/None ->
    normalized-input present, and a case where several fields change at
    once."""

    def test_both_values_present(self):
        plan, context_obj, request, result, outcome, conv = _build_chain(
            "  I need   help.  ", "i need help.", "goal_request")
        self.assertEqual(conv.normalized_input, "i need help.")
        self.assertEqual(plan.understanding_state["intent"], "goal_request")

    def test_normalized_input_present_to_ordinary(self):
        first = _build_chain("  What   is   Python?  ", "what is python?", "ask_question")
        second = _build_chain("What is Python", "What is Python", "ask_question")

        self.assertEqual(first[5].normalized_input, "what is python?")
        self.assertEqual(second[5].normalized_input, "What is Python")
        self.assertNotEqual(first[5].normalized_input, second[5].normalized_input)

    def test_ordinary_to_normalized_input_present(self):
        first = _build_chain("What is Python", "What is Python", "ask_question")
        second = _build_chain("  What   is   Python?  ", "what is python?", "ask_question")

        self.assertEqual(first[5].normalized_input, "What is Python")
        self.assertEqual(second[5].normalized_input, "what is python?")
        self.assertNotEqual(first[5].normalized_input, second[5].normalized_input)

    def test_none_to_normalized_input_present(self):
        first = _build_chain("hi", None, None)
        second = _build_chain("What is Python?", "what is python?", "ask_question")

        self.assertIsNone(first[5].normalized_input)
        self.assertEqual(second[5].normalized_input, "what is python?")

    def test_normalized_input_present_to_none(self):
        first = _build_chain("What is Python?", "what is python?", "ask_question")
        second = _build_chain("hi", None, None)

        self.assertEqual(first[5].normalized_input, "what is python?")
        self.assertIsNone(second[5].normalized_input)

    def test_both_intent_and_normalized_input_change_together(self):
        first = _build_chain(
            "   Python   is   a   language.   ", "Python is a language.",
            "provide_information")
        second = _build_chain("i need to   build   a script", "i need to build a script",
                               "goal_request")

        self.assertEqual(first[0].understanding_state["intent"], "provide_information")
        self.assertEqual(second[0].understanding_state["intent"], "goal_request")
        self.assertNotEqual(
            first[0].understanding_state["intent"], second[0].understanding_state["intent"])
        self.assertNotEqual(first[5].normalized_input, second[5].normalized_input)


# ======================================================================
class TestLegacyConstructionSafety(unittest.TestCase):
    """A hand-built plan/dict/outcome predating Prompts 609-612 - no
    `normalized_input` anywhere - must flow safely to `None` at every
    stage, never raise, and never be silently invented."""

    def test_legacy_plan_dict_missing_normalized_input(self):
        """A bare dict (no `normalized_input` key at all, as a plan
        built before Prompt 609 would look) fed straight into
        `build_generation_context()`."""
        kwargs = _bare_plan_kwargs()
        legacy_dict = {
            "original_message": kwargs["original_message"],
            "detected_language": kwargs["detected_language"],
            "locale": kwargs["locale"],
            "status": kwargs["status"],
            "response_action": None,
            "meaning": None,
            "meaning_candidates": [],
            "matched_pattern": None,
            "variables": {},
            "active_topic": None,
            "references": [],
            "context": None,
            "unresolved_requirements": [],
            "correction_application_result_usable": False,
            # deliberately no "normalized_input" key
        }
        context_obj = build_generation_context(legacy_dict)
        self.assertIsNone(context_obj.normalized_input)

    def test_legacy_plan_object_defaults_normalized_input_to_none(self):
        kwargs = _bare_plan_kwargs()
        plan = ResponsePlan(**kwargs)  # normalized_input omitted entirely
        self.assertIsNone(plan.normalized_input)
        self.assertIsNone(plan.to_dict()["normalized_input"])

        context_obj = build_generation_context(plan)
        self.assertIsNone(context_obj.normalized_input)

        request = ResponseGenerationRequest(_fake_understanding(plan))
        self.assertIsNone(request.generation_context["normalized_input"])

        result = ResponseGenerationResult(
            status=STATUS_GENERATED, response_text="ok", backend_kind="test_backend")
        outcome = build_response_generation_outcome(result, request=request)
        self.assertIsNone(outcome.normalized_input)

        conv = build_conversation_response(result, request=request, outcome=outcome)
        self.assertIsNone(conv.normalized_input)

    def test_legacy_outcome_missing_normalized_input_attribute_entirely(self):
        """A hand-built outcome-like object that predates Prompt 611 and
        therefore has no `normalized_input` attribute at all -
        `build_conversation_response()` must default to None via
        `getattr(..., None)` rather than raising."""
        legacy_outcome = types.SimpleNamespace(
            generated_text="ok", status=STATUS_SUCCESS, language=None, locale=None,
            backend_kind="test_backend", fallback_used=False, failure_reason=None,
            metadata=None, correction_application_result_usable=False,
            # deliberately no `normalized_input` attribute
        )
        result = ResponseGenerationResult(
            status=STATUS_GENERATED, response_text="ok", backend_kind="test_backend")
        conv = build_conversation_response(result, request=None, outcome=legacy_outcome)
        self.assertIsNone(conv.normalized_input)

    def test_no_request_means_no_normalized_input_on_outcome(self):
        result = ResponseGenerationResult(
            status=STATUS_GENERATED, response_text="ok", backend_kind="test_backend")
        outcome = build_response_generation_outcome(result, request=None)
        self.assertIsNone(outcome.normalized_input)


if __name__ == "__main__":
    unittest.main()
