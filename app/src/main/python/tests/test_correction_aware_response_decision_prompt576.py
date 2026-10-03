"""
Tests for Prompt 576 - Use Correction-Aware State in Response Generation
Decision.

Prompt 574 gave `ResponsePlan` a derived `correction_application_result_usable`
field. Prompt 575 forwarded it, unchanged, onto `ResponseGenerationContext`.
Nothing that actually DECIDES a response action could see it yet.

This prompt makes the smallest existing response-generation decision point -
`decide_learned_response()` / `LearnedResponseDecision`
(language_intelligence/learned_response_decision.py, Prompt 437) - recognize
it: `LearnedResponseDecision` gains ONE small, backward-compatible field,
`correction_application_result_usable`, read straight off the SAME
`ResponsePlan` the decision is already made from (via
`ResponseGenerationRequest.response_plan`) - never recomputed, never
re-derived from a `CorrectionApplicationResult`. It is set on every returned
decision, used or not, and never changes `used`, `reason`, `pattern_id` or
the produced response text.

Covers:
    1. usable correction state reaches the decision layer
    2. usable=True produces the intended new decision-state behavior
    3. usable=False preserves the previous behavior
    4. missing/legacy context preserves the previous behavior
    5. ordinary non-correction messages remain unchanged
    6. existing decision fields remain intact
    7. no second correction application/retrieval/selection occurs
    8. backward-compatible construction
    9. deterministic repeated behavior

Run directly:
    python -m unittest tests.test_correction_aware_response_decision_prompt576 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import types
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult, STATUS_APPLIED, STATUS_NOT_APPLIED,
)
from language_intelligence.response_planning import ResponsePlan, STATUS_RESOLVED
from language_intelligence.response_generation import ResponseGenerationRequest
from language_intelligence import correction_application_result_usability as _usability_module
from language_intelligence.learned_response_decision import (
    decide_learned_response, LearnedResponseDecision,
    REASON_NO_REQUEST, REASON_SELECTION_NOT_RESOLVED,
)
from language_intelligence.correction_understanding import build_correction_understanding
from language_intelligence.correction_understanding_result import (
    map_correction_understanding_to_result,
)
from language_intelligence.correction_feedback_record import (
    map_correction_understanding_result_to_feedback_record,
)
from language_intelligence.correction_feedback_learning_input_adapter import (
    convert_correction_feedback_to_learning_input,
)
from language_intelligence.correction_learning_handoff_result import (
    handoff_correction_learning_input_with_result,
)
from language_intelligence.correction_learning_input_storage import (
    store_accepted_correction_learning_input,
)

from tests import test_learned_response_pattern_binding as _b
from language_intelligence.learned_response_pattern_selection import RESPONSE_PATTERNS_KEY
from language_intelligence.learned_pattern_teaching import STATUS_CREATED


def _make_core():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
    skills_dir = os.path.join(tmpdir.name, "skills")
    core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)
    return core, tmpdir


def _store_a_correction(store, original_expression="dgo", corrected_expression="dog",
                         language="en", locale="en-US", confidence=0.9):
    """Same real-store seeding helper Prompt 572/573/574/575's own test
    modules use."""
    source = build_correction_understanding(
        "no I mean %s not %s" % (corrected_expression, original_expression),
        original_expression=original_expression,
        corrected_expression=corrected_expression, language=language,
        locale=locale, confidence=confidence)
    result = map_correction_understanding_to_result(source)
    record = map_correction_understanding_result_to_feedback_record(result)
    learning_input = convert_correction_feedback_to_learning_input(record)
    handoff_result = handoff_correction_learning_input_with_result(learning_input, store)
    store_accepted_correction_learning_input(handoff_result, learning_input, store)


def _base_plan_kwargs():
    return dict(
        original_message="hi", detected_language="english", locale=None,
        status=STATUS_RESOLVED, reason=None, needs_clarification=False,
        response_action="greet", response_action_source=None,
        meaning=None, meaning_candidates=[], matched_pattern=None,
        pattern_candidates=[], variables={}, expression_meanings=[],
        active_topic=None, references=[], context=None, required_items=[],
        unresolved_requirements=[], understanding_state={}, warnings=[])


def _applied_result_dict():
    return CorrectionApplicationResult(
        status=STATUS_APPLIED, match_count=1,
        text_before="dgo is here", text_after="dog is here",
        matched_text="dgo", replacement_text="dog").to_dict()


def _not_applied_result_dict():
    return CorrectionApplicationResult(status=STATUS_NOT_APPLIED, match_count=0).to_dict()


def _understanding_with_plan(plan):
    """A bare stand-in for `LanguageUnderstandingResult`: the only thing
    `decide_learned_response` / `ResponseGenerationRequest` read off it is
    `.response_plan` (real Core code attaches the plan's `to_dict()`
    there - see `_attach_response_plan`, language_intelligence_core.py)."""
    return types.SimpleNamespace(response_plan=plan)


class TestUsableCorrectionStateReachesTheDecision(unittest.TestCase):
    """1: `correction_application_result_usable=True` on the plan is
    visible on the returned `LearnedResponseDecision`, even though this
    plan has nothing a learned response could ever be selected from
    (no matched pattern) - `used` stays False for the ordinary reason."""

    def test_usable_true_reaches_decision(self):
        plan = ResponsePlan(correction_application_result=_applied_result_dict(),
                             **_base_plan_kwargs())
        self.assertTrue(plan.correction_application_result_usable)
        understanding = _understanding_with_plan(plan.to_dict())
        decision = decide_learned_response(understanding)
        self.assertTrue(decision.correction_application_result_usable)


class TestUsableTrueProducesIntendedDecisionState(unittest.TestCase):
    """2: usable=True is exposed identically whether the plan is passed as
    a `ResponsePlan` object or as its `to_dict()` - both already-accepted
    shapes - and never flips `used` on its own."""

    def test_usable_true_via_dict_plan(self):
        plan = ResponsePlan(correction_application_result=_applied_result_dict(),
                             **_base_plan_kwargs())
        understanding = _understanding_with_plan(plan.to_dict())
        decision = decide_learned_response(understanding)
        self.assertTrue(decision.correction_application_result_usable)
        self.assertFalse(decision.used)
        self.assertEqual(decision.reason, REASON_SELECTION_NOT_RESOLVED)

    def test_usable_true_via_plan_object(self):
        plan = ResponsePlan(correction_application_result=_applied_result_dict(),
                             **_base_plan_kwargs())
        understanding = _understanding_with_plan(plan)
        decision = decide_learned_response(understanding)
        self.assertTrue(decision.correction_application_result_usable)

    def test_usable_true_from_real_correction_pipeline(self):
        """End-to-end: a real applied correction, produced by the actual
        correction pipeline (exactly as Prompt 574/575's own end-to-end
        tests build it), reaches the decision unchanged."""
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            self.assertEqual(understanding.correction_application_result.status, STATUS_APPLIED)
            plan = core.language_intelligence.plan_response(understanding)
            self.assertTrue(plan.correction_application_result_usable)
            understanding.response_plan = plan.to_dict()
            decision = decide_learned_response(understanding, context=core.context)
            self.assertTrue(decision.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestUsableFalsePreservesPreviousBehavior(unittest.TestCase):
    """3: `False` / a not-applied result leaves the decision's new field
    False, and leaves everything else exactly as Prompt 437 already
    produced it."""

    def test_none_correction_result(self):
        plan = ResponsePlan(correction_application_result=None, **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)
        understanding = _understanding_with_plan(plan.to_dict())
        decision = decide_learned_response(understanding)
        self.assertFalse(decision.correction_application_result_usable)
        self.assertFalse(decision.used)
        self.assertEqual(decision.reason, REASON_SELECTION_NOT_RESOLVED)

    def test_not_applied_correction_result(self):
        plan = ResponsePlan(correction_application_result=_not_applied_result_dict(),
                             **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)
        understanding = _understanding_with_plan(plan.to_dict())
        decision = decide_learned_response(understanding)
        self.assertFalse(decision.correction_application_result_usable)


class TestMissingOrLegacyContextPreservesBehavior(unittest.TestCase):
    """4: no plan at all, and a legacy plan dict built before Prompt 574
    (no such key), both safely default to False - and to exactly the same
    `used` / `reason` as before this prompt."""

    def test_no_plan_at_all(self):
        understanding = _understanding_with_plan(None)
        decision = decide_learned_response(understanding)
        self.assertFalse(decision.correction_application_result_usable)
        self.assertFalse(decision.used)
        self.assertEqual(decision.reason, REASON_NO_REQUEST)

    def test_legacy_plan_dict_missing_the_key(self):
        plan = ResponsePlan(correction_application_result=_applied_result_dict(),
                             **_base_plan_kwargs())
        legacy = plan.to_dict()
        del legacy["correction_application_result_usable"]
        self.assertNotIn("correction_application_result_usable", legacy)
        understanding = _understanding_with_plan(legacy)
        decision = decide_learned_response(understanding)
        self.assertFalse(decision.correction_application_result_usable)

    def test_no_understanding_attribute_at_all(self):
        understanding = types.SimpleNamespace()
        decision = decide_learned_response(understanding)
        self.assertFalse(decision.correction_application_result_usable)
        self.assertFalse(decision.used)
        self.assertEqual(decision.reason, REASON_NO_REQUEST)


class TestOrdinaryMessagesUnchanged(unittest.TestCase):
    """5: an ordinary message with no correction anywhere in the picture -
    including one for which a learned response IS actually used - behaves
    exactly as it did before this prompt, with the new field simply
    False."""

    @staticmethod
    def _taught_core():
        core, tmpdir = _make_core()
        pattern = _b.QUESTION_PATTERN
        assert core.teach_sentence_pattern("en", pattern).status == STATUS_CREATED
        bound = core.bind_pattern_meaning("en", pattern, "ask_question")
        assert bound.success, bound.errors
        core.learn_language_item("en", "meaning", "ask_question", meaning={
            "response_action": "provide_information",
            RESPONSE_PATTERNS_KEY: [{"id": "answer_question", "template": "About {{topic}}."}],
        })
        return core, tmpdir

    def test_ordinary_message_no_learned_pattern(self):
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("hello there")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            decision = decide_learned_response(understanding, context=core.context)
            self.assertFalse(decision.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_ordinary_message_with_learned_response_used(self):
        core, tmpdir = self._taught_core()
        try:
            understanding = core.understand_language("what is python")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            decision = decide_learned_response(understanding, context=core.context)
            self.assertTrue(decision.used)
            self.assertFalse(decision.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestExistingDecisionFieldsIntact(unittest.TestCase):
    """6: `used`, `reason`, `response`, `pattern_id` are all still present
    and unaffected by the new field being attached."""

    def test_fields_present_and_unaffected(self):
        plan = ResponsePlan(correction_application_result=_applied_result_dict(),
                             **_base_plan_kwargs())
        understanding = _understanding_with_plan(plan.to_dict())
        decision = decide_learned_response(understanding)
        self.assertTrue(hasattr(decision, "used"))
        self.assertTrue(hasattr(decision, "reason"))
        self.assertTrue(hasattr(decision, "response"))
        self.assertTrue(hasattr(decision, "pattern_id"))
        self.assertIsInstance(decision.used, bool)
        self.assertIsNone(decision.response)
        self.assertIsNone(decision.pattern_id)


class TestNoSecondCorrectionOperationOccurs(unittest.TestCase):
    """7: `decide_learned_response` never re-derives usability - the
    existing usability check function is never called by this decision
    path."""

    def test_usability_function_not_called_again(self):
        plan = ResponsePlan(correction_application_result=_applied_result_dict(),
                             **_base_plan_kwargs())
        understanding = _understanding_with_plan(plan.to_dict())
        original = _usability_module.is_correction_application_result_usable
        calls = []

        def counting(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        _usability_module.is_correction_application_result_usable = counting
        try:
            decision = decide_learned_response(understanding)
        finally:
            _usability_module.is_correction_application_result_usable = original
        self.assertEqual(len(calls), 0)
        self.assertTrue(decision.correction_application_result_usable)

    def test_no_second_generation_context_build_through_result_usable(self):
        """The value decide_learned_response exposes must equal the value
        already on ResponseGenerationContext (Prompt 575) built from the
        SAME plan - confirming it is read, not independently derived."""
        plan = ResponsePlan(correction_application_result=_applied_result_dict(),
                             **_base_plan_kwargs())
        understanding = _understanding_with_plan(plan.to_dict())
        context = ResponseGenerationRequest(understanding).generation_context
        decision = decide_learned_response(understanding)
        self.assertEqual(
            decision.correction_application_result_usable,
            context["correction_application_result_usable"])


class TestBackwardCompatibleConstruction(unittest.TestCase):
    """8: existing call sites that construct `LearnedResponseDecision`
    without the new keyword argument are unaffected."""

    def test_default_is_false(self):
        decision = LearnedResponseDecision(True, "some_reason")
        self.assertFalse(decision.correction_application_result_usable)

    def test_positional_construction_still_works(self):
        decision = LearnedResponseDecision(False, "some_reason", None, "pattern_x")
        self.assertEqual(decision.pattern_id, "pattern_x")
        self.assertFalse(decision.correction_application_result_usable)

    def test_repr_does_not_raise(self):
        decision = LearnedResponseDecision(True, "some_reason")
        self.assertIsInstance(repr(decision), str)


class TestDeterministicRepeatedBehavior(unittest.TestCase):
    """9: the same input always produces the same decision, repeatedly."""

    def test_repeated_calls_are_identical(self):
        plan = ResponsePlan(correction_application_result=_applied_result_dict(),
                             **_base_plan_kwargs())
        understanding = _understanding_with_plan(plan.to_dict())
        first = decide_learned_response(understanding)
        second = decide_learned_response(understanding)
        third = decide_learned_response(understanding)
        for other in (second, third):
            self.assertEqual(first.used, other.used)
            self.assertEqual(first.reason, other.reason)
            self.assertEqual(first.pattern_id, other.pattern_id)
            self.assertEqual(
                first.correction_application_result_usable,
                other.correction_application_result_usable)


if __name__ == "__main__":
    unittest.main()
