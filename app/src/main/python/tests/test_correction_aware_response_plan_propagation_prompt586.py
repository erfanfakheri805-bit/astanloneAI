"""
Tests for Prompt 586 - Correction-Aware ResponsePlan Propagation.

Inspection performed by this prompt: traced the actual production path
from `LanguageUnderstandingResult` into `ResponsePlan`
(`ResponsePlanner.plan()`, language_intelligence/response_planning.py)
and onward into `ResponseGenerationContext`
(`build_generation_context()`, response_generation_context.py).

Finding: propagation is already complete at every step.
`ResponsePlanner.plan()` reads `correction_application_result` out of
`understanding.to_dict()` via the existing `_READ_FIELDS` list (it is
one of those fields) and passes it, unread and unmodified, straight
into `ResponsePlan.__init__`, which alone derives
`correction_application_result_usable` from it via the existing
`is_correction_application_result_usable()` criteria (Prompt 484) -
never recomputed anywhere else. `build_generation_context()` then reads
`response_plan.correction_application_result_usable` directly off the
plan's own `to_dict()`, the same way it reads every other plan field,
and forwards it unchanged onto `ResponseGenerationContext.
correction_application_result_usable`. No missing propagation or
validation point was found, so no production code changes were made
(Prompt 586 requirement 3) - this file is the smallest regression
coverage proving that complete handoff holds, end to end, from a real
`LanguageUnderstandingResult` (not a hand-built stand-in) through both
steps.

Covers:
    1. usable=True propagates from `LanguageUnderstandingResult` all
       the way to `ResponseGenerationContext`.
    2. usable=False propagates the same way.
    3. None / legacy input (no `correction_application_result` at all,
       and a plan built before Prompt 574) stays False throughout.
    4. `ResponsePlan.correction_application_result_usable` and
       `ResponseGenerationContext.correction_application_result_usable`
       always agree for the same plan.
    5. Neither `ResponsePlanner.plan()` nor `build_generation_context()`
       mutates the original `understanding.correction_application_
       result` / `response_plan.correction_application_result`, and
       planning the same understanding twice is deterministic.

Run directly:
    python -m unittest tests.test_correction_aware_response_plan_propagation_prompt586 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_correction_aware_response_decision_prompt576 import (
    _make_core, _store_a_correction, _base_plan_kwargs,
)
from language_intelligence.response_planning import ResponsePlan, ResponsePlanner
from language_intelligence.response_generation_context import build_generation_context


def _usable_understanding(core, text="not dgo, I mean dog."):
    _store_a_correction(core.language_learning, "dgo", "dog")
    return core.understand_language(text)


def _unusable_understanding(core, text="hello there"):
    return core.understand_language(text)


class TestUsableTruePropagation(unittest.TestCase):
    """1: True flows unchanged from a real LanguageUnderstandingResult
    through ResponsePlan into ResponseGenerationContext."""

    def test_true_reaches_plan_and_context(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core)
            self.assertTrue(
                understanding.correction_application_result.applied)

            plan = ResponsePlanner().plan(understanding)
            self.assertTrue(plan.correction_application_result_usable)

            context = build_generation_context(plan)
            self.assertTrue(context.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestUsableFalsePropagation(unittest.TestCase):
    """2: False flows unchanged for an ordinary message with no
    correction anywhere in the picture."""

    def test_false_reaches_plan_and_context(self):
        core, tmpdir = _make_core()
        try:
            understanding = _unusable_understanding(core)
            self.assertIsNone(understanding.correction_application_result)

            plan = ResponsePlanner().plan(understanding)
            self.assertFalse(plan.correction_application_result_usable)

            context = build_generation_context(plan)
            self.assertFalse(context.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestNoneOrLegacyInput(unittest.TestCase):
    """3: an understanding with no correction_application_result at
    all, and a ResponsePlan built before Prompt 574's field existed,
    both stay safely False through the whole chain."""

    def test_understanding_without_correction_attribute(self):
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("hello there")
            # confirm no correction data is present at all - the
            # legacy/absent case this handoff must tolerate.
            self.assertIsNone(understanding.correction_application_result)

            plan = ResponsePlanner().plan(understanding)
            self.assertFalse(plan.correction_application_result_usable)
            context = build_generation_context(plan)
            self.assertFalse(context.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_legacy_plan_dict_without_the_field(self):
        plan = ResponsePlan(**_base_plan_kwargs())
        as_dict = plan.to_dict()
        self.assertIn("correction_application_result_usable", as_dict)
        self.assertFalse(as_dict["correction_application_result_usable"])

        context = build_generation_context(as_dict)
        self.assertFalse(context.correction_application_result_usable)

    def test_bare_dict_missing_the_key_entirely(self):
        """A plan dict from before Prompt 574 existed - the key is
        simply absent, not present-and-False."""
        plan = ResponsePlan(**_base_plan_kwargs())
        as_dict = plan.to_dict()
        del as_dict["correction_application_result_usable"]
        context = build_generation_context(as_dict)
        self.assertFalse(context.correction_application_result_usable)


class TestPlanContextConsistency(unittest.TestCase):
    """4: the plan's own field and the context built from it always
    agree, across both usable states."""

    def test_consistent_when_true(self):
        core, tmpdir = _make_core()
        try:
            plan = ResponsePlanner().plan(_usable_understanding(core))
            context = build_generation_context(plan)
            self.assertEqual(
                plan.correction_application_result_usable,
                context.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_consistent_when_false(self):
        core, tmpdir = _make_core()
        try:
            plan = ResponsePlanner().plan(_unusable_understanding(core))
            context = build_generation_context(plan)
            self.assertEqual(
                plan.correction_application_result_usable,
                context.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestNoRecomputationOrMutation(unittest.TestCase):
    """5: neither step mutates the source data, and planning the same
    understanding twice yields equal, independent results."""

    def test_understanding_correction_result_untouched_by_planning(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core)
            before = copy.deepcopy(understanding.correction_application_result.to_dict())

            ResponsePlanner().plan(understanding)

            after = understanding.correction_application_result.to_dict()
            self.assertEqual(before, after)
        finally:
            tmpdir.cleanup()

    def test_plan_correction_result_untouched_by_context_building(self):
        core, tmpdir = _make_core()
        try:
            plan = ResponsePlanner().plan(_usable_understanding(core))
            before = copy.deepcopy(plan.correction_application_result)

            build_generation_context(plan)

            self.assertEqual(plan.correction_application_result, before)
            self.assertTrue(plan.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_repeated_planning_is_deterministic_and_independent(self):
        core, tmpdir = _make_core()
        try:
            first = ResponsePlanner().plan(_usable_understanding(core))
            second = ResponsePlanner().plan(_usable_understanding(core))
            self.assertEqual(
                first.correction_application_result_usable,
                second.correction_application_result_usable)
            self.assertTrue(first.correction_application_result_usable)

            first_context = build_generation_context(first)
            second_context = build_generation_context(second)
            self.assertEqual(
                first_context.correction_application_result_usable,
                second_context.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
