"""
Tests for the Planner (planning/planner.py).

Covers: creating the first PlanStep for a Goal, linking it to the
correct Goal and Plan, retrieving the generated Plan, invalid/missing
Goal handling, idempotency on repeated calls, and a check that Core
wires Planner in without touching existing behaviour.

Run directly:
    python -m unittest tests.test_planner -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planning.goal_manager import GoalManager
from planning.plan import Plan, STATUS_PENDING
from planning.plan_manager import PlanManager
from planning.planner import Planner
from core.core import Core


class TestCreateFirstStep(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.planner = Planner(self.goals, self.plans)
        self.goal = self.goals.create_goal("Create a calculator")

    def test_returns_a_plan_with_exactly_one_step(self):
        plan = self.planner.create_first_step(self.goal.goal_id)

        self.assertIsInstance(plan, Plan)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.status, STATUS_PENDING)

    def test_first_step_description_matches_the_worked_example(self):
        plan = self.planner.create_first_step(self.goal.goal_id)

        self.assertEqual(
            plan.steps[0].description,
            "Understand the requirements of the requested calculator",
        )

    def test_first_step_falls_back_to_full_text_without_a_known_verb(self):
        goal = self.goals.create_goal("Calculator improvements")
        plan = self.planner.create_first_step(goal.goal_id)

        self.assertEqual(
            plan.steps[0].description,
            "Understand the requirements of the requested Calculator improvements",
        )

    def test_first_step_status_is_pending(self):
        plan = self.planner.create_first_step(self.goal.goal_id)
        self.assertEqual(plan.steps[0].status, STATUS_PENDING)


class TestLinkingToGoalAndPlan(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.planner = Planner(self.goals, self.plans)
        self.goal = self.goals.create_goal("Build a chat app")

    def test_plan_goal_id_matches_the_source_goal(self):
        plan = self.planner.create_first_step(self.goal.goal_id)
        self.assertEqual(plan.goal_id, self.goal.goal_id)

    def test_plan_is_stored_in_the_shared_plan_manager(self):
        plan = self.planner.create_first_step(self.goal.goal_id)
        self.assertIs(self.plans.get_plan(plan.plan_id), plan)
        self.assertEqual(len(self.plans), 1)

    def test_step_has_a_step_id_scoped_to_the_plan(self):
        plan = self.planner.create_first_step(self.goal.goal_id)
        self.assertTrue(plan.steps[0].step_id.startswith(plan.plan_id))

    def test_reuses_an_existing_plan_instead_of_creating_a_second_one(self):
        pre_existing = self.plans.create_plan(self.goal.goal_id)
        plan = self.planner.create_first_step(self.goal.goal_id)

        self.assertEqual(plan.plan_id, pre_existing.plan_id)
        self.assertEqual(len(self.plans), 1)
        self.assertEqual(len(plan.steps), 1)

    def test_calling_twice_does_not_add_a_second_first_step(self):
        first_call = self.planner.create_first_step(self.goal.goal_id)
        second_call = self.planner.create_first_step(self.goal.goal_id)

        self.assertEqual(first_call.plan_id, second_call.plan_id)
        self.assertEqual(len(second_call.steps), 1)


class TestRetrievePlan(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.planner = Planner(self.goals, self.plans)
        self.goal = self.goals.create_goal("Write a report")

    def test_generated_plan_is_retrievable_by_id(self):
        created = self.planner.create_first_step(self.goal.goal_id)
        fetched = self.plans.get_plan(created.plan_id)

        self.assertIs(fetched, created)
        self.assertEqual(fetched.steps[0].description, created.steps[0].description)

    def test_generated_plan_describe_matches_to_dict(self):
        created = self.planner.create_first_step(self.goal.goal_id)
        described = self.plans.describe_plan(created.plan_id)

        self.assertEqual(described, created.to_dict())
        self.assertEqual(len(described["steps"]), 1)


class TestCreateSecondStep(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.planner = Planner(self.goals, self.plans)
        self.goal = self.goals.create_goal("Create a calculator")

    def test_creates_two_steps(self):
        plan = self.planner.create_second_step(self.goal.goal_id)

        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(
            plan.steps[0].description,
            "Understand the requirements of the requested calculator",
        )
        self.assertEqual(
            plan.steps[1].description,
            "Design a solution for the requested calculator",
        )

    def test_second_step_depends_on_first_step(self):
        plan = self.planner.create_second_step(self.goal.goal_id)

        first_step, second_step = plan.steps
        self.assertEqual(second_step.dependencies, [first_step.step_id])
        # First step itself stays free of dependencies - only the
        # second step gets the new edge.
        self.assertEqual(first_step.dependencies, [])

    def test_step_ids_are_unique(self):
        plan = self.planner.create_second_step(self.goal.goal_id)

        step_ids = [s.step_id for s in plan.steps]
        self.assertEqual(len(step_ids), len(set(step_ids)))

    def test_preserves_existing_first_step_when_called_directly(self):
        first_plan = self.planner.create_first_step(self.goal.goal_id)
        first_step_before = first_plan.steps[0]

        second_plan = self.planner.create_second_step(self.goal.goal_id)

        self.assertEqual(second_plan.plan_id, first_plan.plan_id)
        self.assertEqual(len(second_plan.steps), 2)
        self.assertEqual(second_plan.steps[0].step_id, first_step_before.step_id)
        self.assertEqual(
            second_plan.steps[0].description, first_step_before.description
        )

    def test_calling_twice_does_not_add_a_third_step(self):
        first_call = self.planner.create_second_step(self.goal.goal_id)
        second_call = self.planner.create_second_step(self.goal.goal_id)

        self.assertEqual(first_call.plan_id, second_call.plan_id)
        self.assertEqual(len(second_call.steps), 2)
        self.assertEqual(
            [s.step_id for s in first_call.steps],
            [s.step_id for s in second_call.steps],
        )

    def test_retrieving_the_complete_plan(self):
        created = self.planner.create_second_step(self.goal.goal_id)
        fetched = self.plans.get_plan(created.plan_id)

        self.assertIs(fetched, created)
        self.assertEqual(len(fetched.steps), 2)
        described = self.plans.describe_plan(created.plan_id)
        self.assertEqual(described, created.to_dict())
        self.assertEqual(len(described["steps"]), 2)
        self.assertEqual(
            described["steps"][1]["dependencies"], [described["steps"][0]["step_id"]]
        )

    def test_unknown_goal_id_raises(self):
        with self.assertRaises(ValueError):
            self.planner.create_second_step("does-not-exist")

    def test_reuses_an_existing_plan_instead_of_creating_a_second_one(self):
        pre_existing = self.plans.create_plan(self.goal.goal_id)
        plan = self.planner.create_second_step(self.goal.goal_id)

        self.assertEqual(plan.plan_id, pre_existing.plan_id)
        self.assertEqual(len(self.plans), 1)
        self.assertEqual(len(plan.steps), 2)


class TestCreateThirdStep(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.planner = Planner(self.goals, self.plans)
        self.goal = self.goals.create_goal("Create a calculator")

    def test_creates_three_steps(self):
        plan = self.planner.create_third_step(self.goal.goal_id)

        self.assertEqual(len(plan.steps), 3)
        self.assertEqual(
            plan.steps[0].description,
            "Understand the requirements of the requested calculator",
        )
        self.assertEqual(
            plan.steps[1].description,
            "Design a solution for the requested calculator",
        )
        self.assertEqual(
            plan.steps[2].description,
            "Validate the planned solution for the requested calculator",
        )

    def test_dependency_chain_step3_to_step2_to_step1(self):
        plan = self.planner.create_third_step(self.goal.goal_id)

        first_step, second_step, third_step = plan.steps
        self.assertEqual(first_step.dependencies, [])
        self.assertEqual(second_step.dependencies, [first_step.step_id])
        self.assertEqual(third_step.dependencies, [second_step.step_id])

    def test_step_ids_are_unique(self):
        plan = self.planner.create_third_step(self.goal.goal_id)

        step_ids = [s.step_id for s in plan.steps]
        self.assertEqual(len(step_ids), len(set(step_ids)))
        self.assertEqual(len(step_ids), 3)

    def test_preserves_existing_first_and_second_steps_when_called_directly(self):
        second_plan = self.planner.create_second_step(self.goal.goal_id)
        steps_before = list(second_plan.steps)

        third_plan = self.planner.create_third_step(self.goal.goal_id)

        self.assertEqual(third_plan.plan_id, second_plan.plan_id)
        self.assertEqual(len(third_plan.steps), 3)
        self.assertEqual(third_plan.steps[0].step_id, steps_before[0].step_id)
        self.assertEqual(third_plan.steps[0].description, steps_before[0].description)
        self.assertEqual(third_plan.steps[1].step_id, steps_before[1].step_id)
        self.assertEqual(third_plan.steps[1].description, steps_before[1].description)
        self.assertEqual(third_plan.steps[1].dependencies, steps_before[1].dependencies)

    def test_calling_twice_does_not_add_a_fourth_step(self):
        first_call = self.planner.create_third_step(self.goal.goal_id)
        second_call = self.planner.create_third_step(self.goal.goal_id)

        self.assertEqual(first_call.plan_id, second_call.plan_id)
        self.assertEqual(len(second_call.steps), 3)
        self.assertEqual(
            [s.step_id for s in first_call.steps],
            [s.step_id for s in second_call.steps],
        )

    def test_retrieving_the_complete_plan(self):
        created = self.planner.create_third_step(self.goal.goal_id)
        fetched = self.plans.get_plan(created.plan_id)

        self.assertIs(fetched, created)
        self.assertEqual(len(fetched.steps), 3)
        described = self.plans.describe_plan(created.plan_id)
        self.assertEqual(described, created.to_dict())
        self.assertEqual(len(described["steps"]), 3)
        self.assertEqual(
            described["steps"][1]["dependencies"], [described["steps"][0]["step_id"]]
        )
        self.assertEqual(
            described["steps"][2]["dependencies"], [described["steps"][1]["step_id"]]
        )

    def test_unknown_goal_id_raises(self):
        with self.assertRaises(ValueError):
            self.planner.create_third_step("does-not-exist")

    def test_reuses_an_existing_plan_instead_of_creating_a_second_one(self):
        pre_existing = self.plans.create_plan(self.goal.goal_id)
        plan = self.planner.create_third_step(self.goal.goal_id)

        self.assertEqual(plan.plan_id, pre_existing.plan_id)
        self.assertEqual(len(self.plans), 1)
        self.assertEqual(len(plan.steps), 3)


class TestInvalidGoalHandling(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.planner = Planner(self.goals, self.plans)

    def test_unknown_goal_id_raises(self):
        with self.assertRaises(ValueError):
            self.planner.create_first_step("does-not-exist")

    def test_empty_goal_id_raises(self):
        with self.assertRaises(ValueError):
            self.planner.create_first_step("")

    def test_none_goal_id_raises(self):
        with self.assertRaises(ValueError):
            self.planner.create_first_step(None)

    def test_failed_planning_creates_no_plan(self):
        try:
            self.planner.create_first_step("does-not-exist")
        except ValueError:
            pass
        self.assertEqual(len(self.plans), 0)

    def test_planner_requires_a_goal_manager(self):
        with self.assertRaises(TypeError):
            Planner(goal_manager=None, plan_manager=self.plans)

    def test_planner_requires_a_plan_manager(self):
        with self.assertRaises(TypeError):
            Planner(goal_manager=self.goals, plan_manager=None)


class TestCoreIntegration(unittest.TestCase):
    """Confirms Planner is wired into Core without changing any
    existing behaviour (AEL/conversation routing untouched)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_core_plan_first_step_creates_a_linked_plan_and_step(self):
        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_first_step(goal.goal_id)

        self.assertEqual(plan.goal_id, goal.goal_id)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(
            plan.steps[0].description,
            "Understand the requirements of the requested calculator",
        )
        self.assertEqual(self.core.get_plan(plan.plan_id).plan_id, plan.plan_id)

    def test_core_plan_first_step_for_unknown_goal_raises(self):
        with self.assertRaises(ValueError):
            self.core.plan_first_step("does-not-exist")

    def test_core_plan_first_step_called_twice_does_not_duplicate(self):
        """Prompt 303: calling Core.plan_first_step() twice for the
        same goal_id must be a no-op the second time - same plan_id,
        still exactly one step, no second Plan created alongside it.
        Exercises Core's own delegation to the existing, already
        idempotent Planner.create_first_step() (see
        TestLinkingToGoalAndPlan.test_calling_twice_does_not_add_a_second_first_step
        above for the same guarantee at the Planner level)."""
        goal = self.core.create_goal("Create a calculator")

        first_call = self.core.plan_first_step(goal.goal_id)
        second_call = self.core.plan_first_step(goal.goal_id)

        self.assertEqual(first_call.plan_id, second_call.plan_id)
        self.assertEqual(len(second_call.steps), 1)
        self.assertEqual(second_call.steps[0].step_id, first_call.steps[0].step_id)
        self.assertEqual(len(self.core.plans), 1)

    def test_existing_conversation_flow_is_unaffected(self):
        reply = self.core.process_input("hello")
        self.assertIsInstance(reply, str)
        self.assertEqual(len(self.core.goals), 0)
        self.assertEqual(len(self.core.plans), 0)

    def test_core_plan_second_step_creates_two_linked_steps(self):
        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_second_step(goal.goal_id)

        self.assertEqual(plan.goal_id, goal.goal_id)
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(
            plan.steps[1].dependencies, [plan.steps[0].step_id]
        )
        self.assertEqual(self.core.get_plan(plan.plan_id).plan_id, plan.plan_id)

    def test_core_plan_second_step_for_unknown_goal_raises(self):
        with self.assertRaises(ValueError):
            self.core.plan_second_step("does-not-exist")

    def test_core_plan_third_step_creates_three_chained_steps(self):
        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_third_step(goal.goal_id)

        self.assertEqual(plan.goal_id, goal.goal_id)
        self.assertEqual(len(plan.steps), 3)
        self.assertEqual(plan.steps[1].dependencies, [plan.steps[0].step_id])
        self.assertEqual(plan.steps[2].dependencies, [plan.steps[1].step_id])
        self.assertEqual(self.core.get_plan(plan.plan_id).plan_id, plan.plan_id)

    def test_core_plan_third_step_for_unknown_goal_raises(self):
        with self.assertRaises(ValueError):
            self.core.plan_third_step("does-not-exist")


if __name__ == "__main__":
    unittest.main()
