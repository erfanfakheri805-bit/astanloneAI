"""
Tests for PlanManager.propagate_step_output - controlled data
propagation between two dependent PlanSteps in the same Plan (added
this stage; see planning/plan_manager.py's own docstring for the full
contract).

Covers: successful propagation, every refusal/conflict case (source
not completed, source output missing, unknown source/target step,
target not declaring the source as a dependency, unrelated steps,
target already holding input), that structured dict/list output
propagates and round-trips intact, that the source step's own
output_data is never touched, that nothing here executes anything or
propagates across a whole plan automatically, and that an unknown
plan_id is a hard error.

Run directly:
    python -m unittest tests.test_step_propagation -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from planning.plan import STATUS_COMPLETED, STATUS_PENDING, STATUS_READY


class TestPropagateStepOutputBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Ship the feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)


class TestSuccessfulPropagation(TestPropagateStepOutputBase):
    def setUp(self):
        super().setUp()
        self.source = self.plans.add_step(self.plan.plan_id, "Fetch data")
        self.target = self.plans.add_step(
            self.plan.plan_id, "Use data", dependencies=[self.source.step_id],
        )

    def _complete_source(self, output):
        self.plans.update_step_status(
            self.plan.plan_id, self.source.step_id, STATUS_COMPLETED
        )
        self.source.set_output(output)

    def test_successful_propagation_copies_output_to_input(self):
        self._complete_source({"result": "sunny"})
        result = self.plans.propagate_step_output(
            self.plan.plan_id, self.source.step_id, self.target.step_id
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["propagated"])
        self.assertEqual(self.target.get_input(), {"result": "sunny"})

    def test_result_shape_has_all_required_keys(self):
        self._complete_source({"a": 1})
        result = self.plans.propagate_step_output(
            self.plan.plan_id, self.source.step_id, self.target.step_id
        )
        for key in (
            "success", "plan_id", "source_step_id", "target_step_id",
            "propagated", "reason", "output_summary",
        ):
            self.assertIn(key, result)
        self.assertEqual(result["plan_id"], self.plan.plan_id)
        self.assertEqual(result["source_step_id"], self.source.step_id)
        self.assertEqual(result["target_step_id"], self.target.step_id)
        self.assertTrue(result["reason"])

    def test_structured_dict_and_list_output_propagates_intact(self):
        data = {"items": [1, 2, 3], "nested": {"a": [True, False, None]}}
        self._complete_source(data)
        result = self.plans.propagate_step_output(
            self.plan.plan_id, self.source.step_id, self.target.step_id
        )
        self.assertTrue(result["success"])
        self.assertEqual(self.target.get_input(), data)

    def test_propagated_input_is_defensive_copy(self):
        data = {"items": [1, 2, 3]}
        self._complete_source(data)
        self.plans.propagate_step_output(
            self.plan.plan_id, self.source.step_id, self.target.step_id
        )
        # Mutating the original dict/list afterwards must not reach
        # into the target's stored input.
        data["items"].append(4)
        self.assertEqual(self.target.get_input()["items"], [1, 2, 3])

    def test_source_output_remains_unchanged_after_propagation(self):
        data = {"result": "sunny"}
        self._complete_source(data)
        self.plans.propagate_step_output(
            self.plan.plan_id, self.source.step_id, self.target.step_id
        )
        self.assertEqual(self.source.get_output(), {"result": "sunny"})

    def test_no_automatic_execution_of_target_step(self):
        self._complete_source({"a": 1})
        self.plans.propagate_step_output(
            self.plan.plan_id, self.source.step_id, self.target.step_id
        )
        # Propagation never changes the target's own status - that
        # remains whatever it was (still PENDING here), and there is
        # no execution history for it anywhere.
        self.assertEqual(self.target.status, STATUS_PENDING)

    def test_output_summary_reflects_source_output(self):
        self._complete_source({"a": 1, "b": 2})
        result = self.plans.propagate_step_output(
            self.plan.plan_id, self.source.step_id, self.target.step_id
        )
        self.assertEqual(result["output_summary"], {"type": "dict", "keys": ["a", "b"]})


class TestPropagationRefusals(TestPropagateStepOutputBase):
    def setUp(self):
        super().setUp()
        self.source = self.plans.add_step(self.plan.plan_id, "Fetch data")
        self.target = self.plans.add_step(
            self.plan.plan_id, "Use data", dependencies=[self.source.step_id],
        )

    def test_source_step_not_completed_refuses(self):
        # source is still PENDING
        result = self.plans.propagate_step_output(
            self.plan.plan_id, self.source.step_id, self.target.step_id
        )
        self.assertFalse(result["success"])
        self.assertFalse(result["propagated"])
        self.assertIsNone(self.target.get_input())

    def test_source_output_missing_refuses(self):
        self.plans.update_step_status(
            self.plan.plan_id, self.source.step_id, STATUS_COMPLETED
        )
        # Completed but no output_data was ever set.
        result = self.plans.propagate_step_output(
            self.plan.plan_id, self.source.step_id, self.target.step_id
        )
        self.assertFalse(result["success"])
        self.assertIsNone(self.target.get_input())

    def test_unknown_source_step_refuses(self):
        result = self.plans.propagate_step_output(
            self.plan.plan_id, "no-such-step", self.target.step_id
        )
        self.assertFalse(result["success"])
        self.assertIsNone(result["output_summary"])

    def test_unknown_target_step_refuses(self):
        self.plans.update_step_status(
            self.plan.plan_id, self.source.step_id, STATUS_COMPLETED
        )
        self.source.set_output({"a": 1})
        result = self.plans.propagate_step_output(
            self.plan.plan_id, self.source.step_id, "no-such-step"
        )
        self.assertFalse(result["success"])

    def test_target_does_not_depend_on_source_refuses(self):
        other_target = self.plans.add_step(self.plan.plan_id, "Unrelated step")
        self.plans.update_step_status(
            self.plan.plan_id, self.source.step_id, STATUS_COMPLETED
        )
        self.source.set_output({"a": 1})
        result = self.plans.propagate_step_output(
            self.plan.plan_id, self.source.step_id, other_target.step_id
        )
        self.assertFalse(result["success"])
        self.assertIsNone(other_target.get_input())

    def test_unrelated_steps_across_different_dependency_never_propagate(self):
        unrelated_source = self.plans.add_step(self.plan.plan_id, "Another source")
        self.plans.update_step_status(
            self.plan.plan_id, unrelated_source.step_id, STATUS_COMPLETED
        )
        unrelated_source.set_output({"z": 9})
        # self.target depends on self.source, not on unrelated_source.
        result = self.plans.propagate_step_output(
            self.plan.plan_id, unrelated_source.step_id, self.target.step_id
        )
        self.assertFalse(result["success"])
        self.assertIsNone(self.target.get_input())

    def test_target_already_has_input_refuses_and_reports_conflict(self):
        self.plans.update_step_status(
            self.plan.plan_id, self.source.step_id, STATUS_COMPLETED
        )
        self.source.set_output({"a": 1})
        self.target.set_input({"existing": True})

        result = self.plans.propagate_step_output(
            self.plan.plan_id, self.source.step_id, self.target.step_id
        )
        self.assertFalse(result["success"])
        self.assertFalse(result["propagated"])
        self.assertIn("already has input_data", result["reason"])
        # Existing target input must be left untouched.
        self.assertEqual(self.target.get_input(), {"existing": True})

    def test_unknown_plan_id_raises(self):
        with self.assertRaises(ValueError):
            self.plans.propagate_step_output(
                "no-such-plan", self.source.step_id, self.target.step_id
            )


if __name__ == "__main__":
    unittest.main()
