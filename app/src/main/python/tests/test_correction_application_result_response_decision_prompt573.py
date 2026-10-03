"""
Tests for Prompt 573 - Expose Correction Result to Response Decision.

Prompt 572 made the real Core path attach a real
`CorrectionApplicationResult` (Prompt 474/570) as
`understanding.correction_application_result`, and Prompt 571 already
confirmed the existing response-GENERATION pipeline (`ResponseGenerationContext`
via `ResponseGenerationRequest.generation_context`) carries it.

This prompt makes the existing response DECISION/PLANNING layer -
`ResponsePlan`/`ResponsePlanner` (response_planning.py, Prompt 425), the
smallest existing object that already receives a
`LanguageUnderstandingResult` and decides what a response must contain -
aware of that same result too. `ResponsePlanner.plan()` now reads the
already-produced `understanding.correction_application_result` and
forwards it, unchanged, as `ResponsePlan.correction_application_result`.
Nothing about `status`, `response_action`, `required_items`, or any
other planning decision is affected.

Covers:
    1. Real Core processing produces a correction application result.
    2. The existing response decision/planning object (`ResponsePlan`)
       receives that same result.
    3. The exact original/corrected values are preserved.
    4. Ordinary non-correction messages receive None.
    5. Existing callers that do not provide the new field remain
       compatible (positional/keyword construction without it; old
       `to_dict()` consumers gain one extra, ignorable key).
    6. No second application operation occurs.
    7. No second retrieval occurs.
    8. No second candidate selection occurs.
    9. Final response text remains unchanged.
    10. Repeated identical processing remains deterministic.

Run directly:
    python -m unittest tests.test_correction_application_result_response_decision_prompt573 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
import core.core as core_module
from language_intelligence import correction_application_candidate_operation as operation_module
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult, STATUS_APPLIED,
)
from language_intelligence.response_planning import ResponsePlan, STATUS_RESOLVED
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


def _make_core():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
    skills_dir = os.path.join(tmpdir.name, "skills")
    core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)
    return core, tmpdir


def _store_a_correction(store, original_expression="dgo", corrected_expression="dog",
                         language="en", locale="en-US", confidence=0.9):
    """Same real-store seeding helper Prompt 572's own test module uses."""
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


def _wrap_and_count(obj, attr_name):
    original = getattr(obj, attr_name)
    call_count = [0]

    def counting(*args, **kwargs):
        call_count[0] += 1
        return original(*args, **kwargs)

    setattr(obj, attr_name, counting)

    def restore():
        setattr(obj, attr_name, original)

    return call_count, restore


class TestRealCoreProducesResultAndPlanReceivesIt(unittest.TestCase):
    """1 & 2: real Core processing produces a real
    `CorrectionApplicationResult`, and re-planning that same, already-
    produced understanding (the existing `plan_response()` entry point)
    yields a `ResponsePlan` carrying the identical result."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_understanding_carries_a_real_result(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        self.assertIsInstance(
            understanding.correction_application_result, CorrectionApplicationResult)
        self.assertEqual(understanding.correction_application_result.status, STATUS_APPLIED)

    def test_response_plan_receives_the_same_result(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        plan = self.core.language_intelligence.plan_response(understanding)
        self.assertIsInstance(plan, ResponsePlan)
        # `ResponsePlanner.plan()` builds from `understanding.to_dict()`
        # (the same "read from the dict form" rule every other field this
        # planner reads already follows), so the value on the plan is the
        # SAME already-produced result, in its `to_dict()` shape.
        self.assertEqual(
            plan.correction_application_result,
            understanding.correction_application_result.to_dict())

    def test_response_plan_to_dict_carries_the_same_result_dict(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        plan = self.core.language_intelligence.plan_response(understanding)
        as_dict = plan.to_dict()
        self.assertEqual(
            as_dict["correction_application_result"],
            understanding.correction_application_result.to_dict())


class TestOriginalAndCorrectedValuesPreserved(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_exact_values_reach_the_plan_unchanged(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        plan = self.core.language_intelligence.plan_response(understanding)
        result = plan.correction_application_result
        self.assertEqual(result["matched_text"], "dgo")
        self.assertEqual(result["replacement_text"], "dog")
        self.assertEqual(result["original_text"], "not dgo, I mean dog.")
        self.assertEqual(result["corrected_text"], "not dog, I mean dog.")


class TestOrdinaryMessagesReceiveNone(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ordinary_message_plan_has_none(self):
        understanding = self.core.understand_language("Hello, how are you today?")
        self.assertIsNone(understanding.correction_application_result)
        plan = self.core.language_intelligence.plan_response(understanding)
        self.assertIsNone(plan.correction_application_result)

    def test_no_stored_correction_leaves_plan_field_none(self):
        understanding = self.core.understand_language("not dgo, I mean dog.")
        self.assertIsNone(understanding.correction_application_result)
        plan = self.core.language_intelligence.plan_response(understanding)
        self.assertIsNone(plan.correction_application_result)


class TestExistingCallersRemainCompatible(unittest.TestCase):
    """5: a caller building/consuming a `ResponsePlan` without ever
    mentioning the new field keeps working exactly as before."""

    def _plan_without_the_new_field(self):
        return ResponsePlan(
            original_message="hi", detected_language="english", locale=None,
            status=STATUS_RESOLVED, reason=None, needs_clarification=False,
            response_action="greet", response_action_source=None,
            meaning=None, meaning_candidates=[], matched_pattern=None,
            pattern_candidates=[], variables={}, expression_meanings=[],
            active_topic=None, references=[], context=None, required_items=[],
            unresolved_requirements=[], understanding_state={}, warnings=[])

    def test_construction_without_the_new_field_defaults_to_none(self):
        plan = self._plan_without_the_new_field()
        self.assertIsNone(plan.correction_application_result)

    def test_to_dict_still_has_every_previously_existing_key(self):
        plan = self._plan_without_the_new_field()
        as_dict = plan.to_dict()
        self.assertEqual(as_dict["status"], STATUS_RESOLVED)
        self.assertEqual(as_dict["response_action"], "greet")
        self.assertIn("correction_application_result", as_dict)
        self.assertIsNone(as_dict["correction_application_result"])

    def test_plan_on_an_understanding_with_no_such_attribute_is_none(self):
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("Hello there")
            # An ordinary understanding from before this prompt would not
            # have carried the attribute at all in the same way; the
            # planner must not raise or invent a value either way.
            plan = core.language_intelligence.response_planner.plan(understanding)
            self.assertIsNone(plan.correction_application_result)
        finally:
            tmpdir.cleanup()


class TestNoSecondApplicationRetrievalOrSelection(unittest.TestCase):
    """6, 7, 8: planning again touches none of the correction machinery -
    it only reads what Core already attached."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_planning_again_does_not_reapply(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        call_count, restore = _wrap_and_count(
            core_module, "apply_correction_application_candidate")
        try:
            self.core.language_intelligence.plan_response(understanding)
        finally:
            restore()
        self.assertEqual(call_count[0], 0)

    def test_planning_again_does_not_re_retrieve(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        call_count, restore = _wrap_and_count(
            core_module, "retrieve_and_attach_correction_application_candidate")
        try:
            self.core.language_intelligence.plan_response(understanding)
        finally:
            restore()
        self.assertEqual(call_count[0], 0)

    def test_planning_again_does_not_re_evaluate_eligibility(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        call_count, restore = _wrap_and_count(
            operation_module, "evaluate_correction_application_candidate_eligibility")
        try:
            self.core.language_intelligence.plan_response(understanding)
        finally:
            restore()
        self.assertEqual(call_count[0], 0)


class TestFinalResponseTextUnchanged(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_process_input_reply_is_a_plain_string_as_before(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        reply = self.core.process_input("not dgo, I mean dog.")
        self.assertIsInstance(reply, str)

    def test_response_plan_never_carries_response_text(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        plan = self.core.language_intelligence.plan_response(understanding)
        self.assertNotIn("response_text", plan.to_dict())


class TestDeterminism(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_repeated_identical_processing_produces_equal_plans(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        first_understanding = self.core.understand_language("not dgo, I mean dog.")
        second_understanding = self.core.understand_language("not dgo, I mean dog.")
        first_plan = self.core.language_intelligence.plan_response(first_understanding)
        second_plan = self.core.language_intelligence.plan_response(second_understanding)
        self.assertEqual(
            first_plan.to_dict()["correction_application_result"],
            second_plan.to_dict()["correction_application_result"],
        )


if __name__ == "__main__":
    unittest.main()
