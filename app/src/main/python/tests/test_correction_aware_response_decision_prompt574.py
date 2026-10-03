"""
Tests for Prompt 574 - Add Correction-Aware Response Decision.

Prompt 573 gave `ResponsePlan` a `correction_application_result` field
(the dict form of an existing `CorrectionApplicationResult`, Prompt
474/570/571, forwarded unchanged from the understanding). This prompt
adds `ResponsePlan.correction_application_result_usable`: `True` only
when that dict represents a result the EXISTING Prompt 484
`is_correction_application_result_usable()` criteria would itself call
usable (`status == "APPLIED"`, `applied is True`, `match_count > 0`,
and `text_before`/`text_after`/`matched_text`/`replacement_text` all
present); `False` for `None`, `NOT_APPLIED`, `FAILED`, or an
incomplete result. Derived only - never independently settable - and
consulted by no other planning decision.

Covers:
    1. A real successful correction result produces the new
       correction-aware decision (`True`).
    2. `None` does not activate the decision.
    3. `FAILED` does not activate it.
    4. Invalid/incomplete results do not activate it.
    5. The original and corrected expressions remain unchanged.
    6. Existing response-plan fields remain unchanged.
    7. Ordinary non-correction processing remains unchanged.
    8. No second application occurs.
    9. No retrieval or selection occurs during planning.
    10. Repeated planning is deterministic.
    11. Existing callers remain backward compatible.

Run directly:
    python -m unittest tests.test_correction_aware_response_decision_prompt574 -v
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
    CorrectionApplicationResult, STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED,
)
from language_intelligence.response_planning import (
    ResponsePlan, ResponsePlanner, STATUS_RESOLVED,
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


def _make_core():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
    skills_dir = os.path.join(tmpdir.name, "skills")
    core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)
    return core, tmpdir


def _store_a_correction(store, original_expression="dgo", corrected_expression="dog",
                         language="en", locale="en-US", confidence=0.9):
    """Same real-store seeding helper Prompt 572/573's own test modules use."""
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


def _base_plan_kwargs():
    return dict(
        original_message="hi", detected_language="english", locale=None,
        status=STATUS_RESOLVED, reason=None, needs_clarification=False,
        response_action="greet", response_action_source=None,
        meaning=None, meaning_candidates=[], matched_pattern=None,
        pattern_candidates=[], variables={}, expression_meanings=[],
        active_topic=None, references=[], context=None, required_items=[],
        unresolved_requirements=[], understanding_state={}, warnings=[])


class TestRealSuccessfulResultActivatesTheDecision(unittest.TestCase):
    """1: a real successful correction produces `True`."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_applied_result_from_real_core_is_usable(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        self.assertEqual(understanding.correction_application_result.status, STATUS_APPLIED)
        plan = self.core.language_intelligence.plan_response(understanding)
        self.assertTrue(plan.correction_application_result_usable)
        self.assertTrue(plan.to_dict()["correction_application_result_usable"])


class TestNoneDoesNotActivate(unittest.TestCase):
    """2: `None` leaves the decision `False`."""

    def test_none_result_is_not_usable(self):
        plan = ResponsePlan(correction_application_result=None, **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)

    def test_ordinary_core_message_is_not_usable(self):
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("Hello, how are you today?")
            self.assertIsNone(understanding.correction_application_result)
            plan = core.language_intelligence.plan_response(understanding)
            self.assertFalse(plan.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestFailedDoesNotActivate(unittest.TestCase):
    """3: `FAILED` leaves the decision `False`."""

    def test_failed_result_is_not_usable(self):
        failed = CorrectionApplicationResult(status=STATUS_FAILED).to_dict()
        plan = ResponsePlan(correction_application_result=failed, **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)

    def test_not_applied_result_is_not_usable(self):
        not_applied = CorrectionApplicationResult(status=STATUS_NOT_APPLIED).to_dict()
        plan = ResponsePlan(correction_application_result=not_applied, **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)


class TestInvalidOrIncompleteDoesNotActivate(unittest.TestCase):
    """4: structurally incomplete results (even with status APPLIED) stay
    `False` - never guessed, never "close enough"."""

    def _applied_dict(self, **overrides):
        base = CorrectionApplicationResult(
            status=STATUS_APPLIED, original_text="not dgo, I mean dog.",
            corrected_text="not dog, I mean dog.", matched_text="dgo",
            replacement_text="dog", match_count=1).to_dict()
        base.update(overrides)
        return base

    def test_zero_match_count_is_not_usable(self):
        plan = ResponsePlan(
            correction_application_result=self._applied_dict(match_count=0),
            **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)

    def test_missing_matched_text_is_not_usable(self):
        plan = ResponsePlan(
            correction_application_result=self._applied_dict(matched_text=None),
            **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)

    def test_missing_replacement_text_is_not_usable(self):
        plan = ResponsePlan(
            correction_application_result=self._applied_dict(replacement_text=None),
            **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)

    def test_missing_text_before_is_not_usable(self):
        plan = ResponsePlan(
            correction_application_result=self._applied_dict(text_before=None),
            **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)

    def test_missing_text_after_is_not_usable(self):
        plan = ResponsePlan(
            correction_application_result=self._applied_dict(text_after=None),
            **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)

    def test_applied_false_with_applied_status_is_not_usable(self):
        plan = ResponsePlan(
            correction_application_result=self._applied_dict(applied=False),
            **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)

    def test_non_dict_value_is_not_usable(self):
        plan = ResponsePlan(
            correction_application_result="not-a-dict", **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)

    def test_string_match_count_is_not_usable(self):
        plan = ResponsePlan(
            correction_application_result=self._applied_dict(match_count="1"),
            **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)

    def test_complete_applied_dict_is_usable(self):
        plan = ResponsePlan(
            correction_application_result=self._applied_dict(), **_base_plan_kwargs())
        self.assertTrue(plan.correction_application_result_usable)


class TestOriginalAndCorrectedExpressionsUnchanged(unittest.TestCase):
    """5: the underlying values themselves are untouched by this decision."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_matched_and_replacement_text_unchanged(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        plan = self.core.language_intelligence.plan_response(understanding)
        result = plan.correction_application_result
        self.assertEqual(result["matched_text"], "dgo")
        self.assertEqual(result["replacement_text"], "dog")
        self.assertEqual(result["original_text"], "not dgo, I mean dog.")
        self.assertEqual(result["corrected_text"], "not dog, I mean dog.")
        # The candidate itself is untouched.
        candidate = understanding.correction_application_candidate
        self.assertEqual(candidate.original_expression, "dgo")


class TestExistingPlanFieldsUnchanged(unittest.TestCase):
    """6: adding the new field changes nothing else on the plan."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_status_and_response_action_unaffected(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        plan = self.core.language_intelligence.plan_response(understanding)
        # A correction message with no learned pattern/meaning is still
        # UNRESOLVED, exactly as it was before this prompt - the new
        # field is purely additional.
        self.assertEqual(plan.status, understanding.response_plan["status"])
        self.assertEqual(
            plan.response_action, understanding.response_plan["response_action"])


class TestOrdinaryProcessingUnchanged(unittest.TestCase):
    """7: an ordinary conversational turn is unaffected."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ordinary_reply_is_a_plain_string(self):
        reply = self.core.process_input("Hello, how are you today?")
        self.assertIsInstance(reply, str)


class TestNoSecondApplicationRetrievalOrSelection(unittest.TestCase):
    """8, 9: computing the new field never re-applies, re-retrieves, or
    re-selects anything - it only reads the dict already on the plan."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_planning_does_not_reapply(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        call_count, restore = _wrap_and_count(
            core_module, "apply_correction_application_candidate")
        try:
            self.core.language_intelligence.plan_response(understanding)
        finally:
            restore()
        self.assertEqual(call_count[0], 0)

    def test_planning_does_not_re_retrieve(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        call_count, restore = _wrap_and_count(
            core_module, "retrieve_and_attach_correction_application_candidate")
        try:
            self.core.language_intelligence.plan_response(understanding)
        finally:
            restore()
        self.assertEqual(call_count[0], 0)

    def test_planning_does_not_re_evaluate_eligibility(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        call_count, restore = _wrap_and_count(
            operation_module, "evaluate_correction_application_candidate_eligibility")
        try:
            self.core.language_intelligence.plan_response(understanding)
        finally:
            restore()
        self.assertEqual(call_count[0], 0)


class TestDeterminism(unittest.TestCase):
    """10: repeated planning is deterministic."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_repeated_planning_produces_equal_decisions(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        first_understanding = self.core.understand_language("not dgo, I mean dog.")
        second_understanding = self.core.understand_language("not dgo, I mean dog.")
        first_plan = self.core.language_intelligence.plan_response(first_understanding)
        second_plan = self.core.language_intelligence.plan_response(second_understanding)
        self.assertEqual(
            first_plan.correction_application_result_usable,
            second_plan.correction_application_result_usable)
        self.assertTrue(first_plan.correction_application_result_usable)


class TestExistingCallersRemainCompatible(unittest.TestCase):
    """11: a caller that never mentions the new field, or that predates
    it, keeps working exactly as before."""

    def test_construction_without_the_new_field_defaults_to_false(self):
        plan = ResponsePlan(**_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)

    def test_to_dict_still_has_every_previously_existing_key(self):
        plan = ResponsePlan(**_base_plan_kwargs())
        as_dict = plan.to_dict()
        self.assertEqual(as_dict["status"], STATUS_RESOLVED)
        self.assertEqual(as_dict["response_action"], "greet")
        self.assertIn("correction_application_result_usable", as_dict)
        self.assertFalse(as_dict["correction_application_result_usable"])

    def test_planner_plan_still_works_for_understanding_without_the_attribute(self):
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("Hello there")
            plan = ResponsePlanner().plan(understanding)
            self.assertFalse(plan.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
