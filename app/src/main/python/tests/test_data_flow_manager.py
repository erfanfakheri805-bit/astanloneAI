"""
Tests for DataFlowManager.propagate_completed_step (planning/
data_flow_manager.py) - plan-wide propagation of one completed step's
output to its direct dependents, built on top of
PlanManager.propagate_step_output.

Covers: a single dependent, multiple dependents, no dependents, a
dependent that already has input_data (conflict), a source step that
isn't COMPLETED, a missing source step, that unrelated steps are never
touched, that the source's own output_data is never modified, and
that nothing here executes any step.

Run directly:
    python -m unittest tests.test_data_flow_manager -v
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
from planning.plan import STATUS_COMPLETED, STATUS_PENDING
from planning.data_flow_manager import DataFlowManager


class TestDataFlowManagerBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.flow = DataFlowManager(self.plans)
        self.goal = self.goals.create_goal("Ship the feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _complete(self, step, output):
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)
        step.set_output(output)


class TestConstruction(unittest.TestCase):
    def test_requires_plan_manager_instance(self):
        with self.assertRaises(TypeError):
            DataFlowManager(object())


class TestOneDependent(TestDataFlowManagerBase):
    def setUp(self):
        super().setUp()
        self.source = self.plans.add_step(self.plan.plan_id, "Fetch data")
        self.target = self.plans.add_step(
            self.plan.plan_id, "Use data", dependencies=[self.source.step_id],
        )

    def test_propagates_to_single_dependent(self):
        self._complete(self.source, {"result": "sunny"})
        result = self.flow.propagate_completed_step(self.plan.plan_id, self.source.step_id)

        self.assertEqual(result["propagated_steps"], [self.target.step_id])
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["skipped_steps"], [])
        self.assertEqual(self.target.get_input(), {"result": "sunny"})

    def test_result_shape_has_all_required_keys(self):
        self._complete(self.source, {"a": 1})
        result = self.flow.propagate_completed_step(self.plan.plan_id, self.source.step_id)
        for key in (
            "plan_id", "source_step_id", "propagated_steps", "skipped_steps",
            "conflicts", "warnings",
        ):
            self.assertIn(key, result)
        self.assertEqual(result["plan_id"], self.plan.plan_id)
        self.assertEqual(result["source_step_id"], self.source.step_id)

    def test_source_output_remains_unchanged(self):
        data = {"result": "sunny"}
        self._complete(self.source, data)
        self.flow.propagate_completed_step(self.plan.plan_id, self.source.step_id)
        self.assertEqual(self.source.get_output(), {"result": "sunny"})

    def test_no_automatic_execution_of_dependent(self):
        self._complete(self.source, {"a": 1})
        self.flow.propagate_completed_step(self.plan.plan_id, self.source.step_id)
        self.assertEqual(self.target.status, STATUS_PENDING)

    def test_does_not_change_dependency_relationships(self):
        self._complete(self.source, {"a": 1})
        self.flow.propagate_completed_step(self.plan.plan_id, self.source.step_id)
        self.assertEqual(self.target.dependencies, [self.source.step_id])


class TestMultipleDependents(TestDataFlowManagerBase):
    def setUp(self):
        super().setUp()
        self.source = self.plans.add_step(self.plan.plan_id, "Fetch data")
        self.target_a = self.plans.add_step(
            self.plan.plan_id, "Use data A", dependencies=[self.source.step_id],
        )
        self.target_b = self.plans.add_step(
            self.plan.plan_id, "Use data B", dependencies=[self.source.step_id],
        )

    def test_propagates_to_every_direct_dependent(self):
        self._complete(self.source, {"value": 42})
        result = self.flow.propagate_completed_step(self.plan.plan_id, self.source.step_id)

        self.assertEqual(
            set(result["propagated_steps"]), {self.target_a.step_id, self.target_b.step_id}
        )
        self.assertEqual(self.target_a.get_input(), {"value": 42})
        self.assertEqual(self.target_b.get_input(), {"value": 42})

    def test_mixed_conflict_and_success_across_dependents(self):
        self.target_b.set_input({"existing": True})
        self._complete(self.source, {"value": 42})
        result = self.flow.propagate_completed_step(self.plan.plan_id, self.source.step_id)

        self.assertEqual(result["propagated_steps"], [self.target_a.step_id])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["conflicts"][0]["step_id"], self.target_b.step_id)
        self.assertEqual(self.target_b.get_input(), {"existing": True})


class TestNoDependents(TestDataFlowManagerBase):
    def test_no_dependent_steps_produces_warning_and_no_propagation(self):
        source = self.plans.add_step(self.plan.plan_id, "Lonely step")
        self._complete(source, {"a": 1})
        result = self.flow.propagate_completed_step(self.plan.plan_id, source.step_id)

        self.assertEqual(result["propagated_steps"], [])
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["skipped_steps"], [])
        self.assertTrue(result["warnings"])


class TestDependentWithExistingInput(TestDataFlowManagerBase):
    def test_existing_input_is_not_overwritten_and_reported_as_conflict(self):
        source = self.plans.add_step(self.plan.plan_id, "Fetch data")
        target = self.plans.add_step(
            self.plan.plan_id, "Use data", dependencies=[source.step_id],
        )
        target.set_input({"existing": True})
        self._complete(source, {"new": "data"})

        result = self.flow.propagate_completed_step(self.plan.plan_id, source.step_id)

        self.assertEqual(result["propagated_steps"], [])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["conflicts"][0]["step_id"], target.step_id)
        self.assertEqual(target.get_input(), {"existing": True})


class TestSourceNotCompleted(TestDataFlowManagerBase):
    def test_source_step_not_completed_propagates_nothing(self):
        source = self.plans.add_step(self.plan.plan_id, "Fetch data")
        target = self.plans.add_step(
            self.plan.plan_id, "Use data", dependencies=[source.step_id],
        )
        # source is still PENDING - never completed.
        result = self.flow.propagate_completed_step(self.plan.plan_id, source.step_id)

        self.assertEqual(result["propagated_steps"], [])
        self.assertIsNone(target.get_input())
        self.assertTrue(result["warnings"])


class TestMissingSourceStep(TestDataFlowManagerBase):
    def test_missing_source_step_reports_warning_not_exception(self):
        result = self.flow.propagate_completed_step(self.plan.plan_id, "no-such-step")

        self.assertEqual(result["propagated_steps"], [])
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["skipped_steps"], [])
        self.assertTrue(result["warnings"])

    def test_unknown_plan_id_raises(self):
        with self.assertRaises(ValueError):
            self.flow.propagate_completed_step("no-such-plan", "no-such-step")


class TestUnrelatedStepsIgnored(TestDataFlowManagerBase):
    def test_unrelated_steps_are_never_touched(self):
        source = self.plans.add_step(self.plan.plan_id, "Fetch data")
        dependent = self.plans.add_step(
            self.plan.plan_id, "Use data", dependencies=[source.step_id],
        )
        unrelated = self.plans.add_step(self.plan.plan_id, "Totally unrelated step")

        self._complete(source, {"a": 1})
        result = self.flow.propagate_completed_step(self.plan.plan_id, source.step_id)

        self.assertEqual(result["propagated_steps"], [dependent.step_id])
        self.assertIsNone(unrelated.get_input())
        self.assertIsNone(unrelated.get_output())
        self.assertEqual(unrelated.status, STATUS_PENDING)

    def test_dependents_of_a_different_source_are_not_touched(self):
        source_1 = self.plans.add_step(self.plan.plan_id, "Fetch A")
        source_2 = self.plans.add_step(self.plan.plan_id, "Fetch B")
        dependent_of_2 = self.plans.add_step(
            self.plan.plan_id, "Use B", dependencies=[source_2.step_id],
        )
        self._complete(source_1, {"a": 1})
        self._complete(source_2, {"b": 2})

        result = self.flow.propagate_completed_step(self.plan.plan_id, source_1.step_id)

        self.assertEqual(result["propagated_steps"], [])
        self.assertIsNone(dependent_of_2.get_input())


if __name__ == "__main__":
    unittest.main()
