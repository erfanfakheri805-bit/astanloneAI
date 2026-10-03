"""
Tests for the Plan/PlanStep model and PlanManager (planning/ foundation).

Covers: creating a plan for an existing goal, adding a step, retrieving
a plan, invalid goal/plan input, and the structured (debugging)
representation - plus a couple of checks that Core wires PlanManager
in without touching existing behaviour.

Run directly:
    python -m unittest tests.test_plan_manager -v
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
from planning.plan import (
    Plan, PlanStep, STATUS_PENDING, STATUS_READY, STATUS_BLOCKED,
    STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_FAILED, ALL_STEP_STATUSES,
)
from planning.plan_manager import PlanManager
from core.core import Core
from memory.memory_system import MemorySystem
from capabilities.capability_system import CapabilitySystem


class TestCreatePlan(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Book a flight to Tokyo")

    def test_create_plan_returns_a_plan_with_expected_fields(self):
        plan = self.plans.create_plan(self.goal.goal_id)

        self.assertIsInstance(plan, Plan)
        self.assertTrue(plan.plan_id)
        self.assertEqual(plan.goal_id, self.goal.goal_id)
        self.assertEqual(plan.steps, [])
        self.assertEqual(plan.dependencies, [])
        self.assertEqual(plan.required_capabilities, [])
        self.assertEqual(plan.expected_outputs, [])
        self.assertEqual(plan.status, STATUS_PENDING)
        self.assertEqual(plan.warnings, [])
        self.assertTrue(plan.created_at)
        self.assertEqual(plan.metadata, {})
        self.assertGreaterEqual(plan.confidence, 0.0)
        self.assertLessEqual(plan.confidence, 1.0)

    def test_create_plan_accepts_dependencies_capabilities_outputs_and_metadata(self):
        plan = self.plans.create_plan(
            self.goal.goal_id,
            dependencies=["plan-0"],
            required_capabilities=["flight_booking_api"],
            expected_outputs=["confirmed itinerary"],
            metadata={"priority": "high"},
        )
        self.assertEqual(plan.dependencies, ["plan-0"])
        self.assertEqual(plan.required_capabilities, ["flight_booking_api"])
        self.assertEqual(plan.expected_outputs, ["confirmed itinerary"])
        self.assertEqual(plan.metadata, {"priority": "high"})

    def test_created_plans_are_stored_and_get_unique_ids(self):
        first = self.plans.create_plan(self.goal.goal_id)
        second = self.plans.create_plan(self.goal.goal_id)
        self.assertNotEqual(first.plan_id, second.plan_id)
        self.assertEqual(len(self.plans), 2)

    def test_multiple_plans_can_target_the_same_goal(self):
        first = self.plans.create_plan(self.goal.goal_id)
        second = self.plans.create_plan(self.goal.goal_id)
        self.assertEqual(first.goal_id, second.goal_id)


class TestAddStep(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Plan a birthday party")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def test_add_step_returns_a_step_with_expected_fields(self):
        step = self.plans.add_step(
            self.plan.plan_id,
            "Book a venue",
            dependencies=[],
            required_capabilities=["calendar_access"],
            expected_output="venue confirmation",
        )
        self.assertIsInstance(step, PlanStep)
        self.assertTrue(step.step_id)
        self.assertEqual(step.description, "Book a venue")
        self.assertEqual(step.dependencies, [])
        self.assertEqual(step.required_capabilities, ["calendar_access"])
        self.assertEqual(step.expected_output, "venue confirmation")
        self.assertEqual(step.status, STATUS_PENDING)

    def test_added_step_is_appended_to_the_plan(self):
        self.plans.add_step(self.plan.plan_id, "Book a venue")
        self.plans.add_step(self.plan.plan_id, "Send invitations")
        self.assertEqual(len(self.plan.steps), 2)
        self.assertEqual(self.plan.steps[0].description, "Book a venue")
        self.assertEqual(self.plan.steps[1].description, "Send invitations")

    def test_step_ids_are_unique_within_a_plan(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(self.plan.plan_id, "Send invitations")
        self.assertNotEqual(first.step_id, second.step_id)

    def test_step_can_declare_dependency_on_another_step(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=[first.step_id]
        )
        self.assertEqual(second.dependencies, [first.step_id])


class TestStepStatusManagement(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Plan a birthday party")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def test_new_step_defaults_to_pending(self):
        step = self.plans.add_step(self.plan.plan_id, "Book a venue")
        self.assertEqual(step.status, STATUS_PENDING)

    def test_get_step_returns_the_stored_step(self):
        step = self.plans.add_step(self.plan.plan_id, "Book a venue")
        fetched = self.plans.get_step(self.plan.plan_id, step.step_id)
        self.assertIs(fetched, step)

    def test_get_step_returns_none_for_unknown_step_id(self):
        self.assertIsNone(self.plans.get_step(self.plan.plan_id, "does-not-exist"))

    def test_get_step_returns_none_for_unknown_plan_id(self):
        self.assertIsNone(self.plans.get_step("does-not-exist", "any-step"))

    def test_update_step_status_sets_the_new_status(self):
        step = self.plans.add_step(self.plan.plan_id, "Book a venue")
        updated = self.plans.update_step_status(
            self.plan.plan_id, step.step_id, STATUS_IN_PROGRESS
        )
        self.assertIs(updated, step)
        self.assertEqual(step.status, STATUS_IN_PROGRESS)

    def test_update_step_status_accepts_every_recognized_status(self):
        step = self.plans.add_step(self.plan.plan_id, "Book a venue")
        for status in ALL_STEP_STATUSES:
            self.plans.update_step_status(self.plan.plan_id, step.step_id, status)
            self.assertEqual(step.status, status)

    def test_update_step_status_rejects_unknown_status(self):
        step = self.plans.add_step(self.plan.plan_id, "Book a venue")
        with self.assertRaises(ValueError):
            self.plans.update_step_status(self.plan.plan_id, step.step_id, "not_a_real_status")
        # Rejected update must not have touched the existing status.
        self.assertEqual(step.status, STATUS_PENDING)

    def test_update_step_status_for_unknown_step_raises(self):
        with self.assertRaises(ValueError):
            self.plans.update_step_status(self.plan.plan_id, "does-not-exist", STATUS_READY)

    def test_update_step_status_for_unknown_plan_raises(self):
        with self.assertRaises(ValueError):
            self.plans.update_step_status("does-not-exist", "any-step", STATUS_READY)

    def test_plan_step_set_status_rejects_unknown_status_directly(self):
        step = self.plans.add_step(self.plan.plan_id, "Book a venue")
        with self.assertRaises(ValueError):
            step.set_status("not_a_real_status")
        self.assertEqual(step.status, STATUS_PENDING)

    def test_step_with_no_dependencies_refreshes_to_ready(self):
        step = self.plans.add_step(self.plan.plan_id, "Book a venue")
        refreshed = self.plans.refresh_step_status(self.plan.plan_id, step.step_id)
        self.assertIs(refreshed, step)
        self.assertEqual(step.status, STATUS_READY)

    def test_step_with_unresolved_dependency_refreshes_to_blocked(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=[first.step_id]
        )
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)
        self.assertEqual(second.status, STATUS_BLOCKED)

    def test_step_with_dangling_dependency_refreshes_to_blocked(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=["no-such-step"]
        )
        self.plans.refresh_step_status(self.plan.plan_id, step.step_id)
        self.assertEqual(step.status, STATUS_BLOCKED)

    def test_step_becomes_ready_once_dependency_completes(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=[first.step_id]
        )
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)
        self.assertEqual(second.status, STATUS_BLOCKED)

        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_COMPLETED)
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)
        self.assertEqual(second.status, STATUS_READY)

    def test_refresh_does_not_overwrite_in_progress_or_terminal_status(self):
        step = self.plans.add_step(self.plan.plan_id, "Book a venue")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_IN_PROGRESS)
        self.plans.refresh_step_status(self.plan.plan_id, step.step_id)
        self.assertEqual(step.status, STATUS_IN_PROGRESS)

        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)
        self.plans.refresh_step_status(self.plan.plan_id, step.step_id)
        self.assertEqual(step.status, STATUS_FAILED)

    def test_refresh_plan_step_statuses_updates_every_eligible_step(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=[first.step_id]
        )
        self.plans.refresh_plan_step_statuses(self.plan.plan_id)
        self.assertEqual(first.status, STATUS_READY)
        self.assertEqual(second.status, STATUS_BLOCKED)

    def test_refresh_step_status_for_unknown_step_raises(self):
        with self.assertRaises(ValueError):
            self.plans.refresh_step_status(self.plan.plan_id, "does-not-exist")

    def test_refresh_step_status_for_unknown_plan_raises(self):
        with self.assertRaises(ValueError):
            self.plans.refresh_step_status("does-not-exist", "any-step")

    def test_refresh_plan_step_statuses_for_unknown_plan_raises(self):
        with self.assertRaises(ValueError):
            self.plans.refresh_plan_step_statuses("does-not-exist")

    def test_status_updates_do_not_auto_execute_or_touch_other_steps(self):
        """Updating/refreshing one step's status is pure bookkeeping -
        it must never change another step's status as a side effect
        (that's the future Execution Engine's job, not this one's)."""
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(self.plan.plan_id, "Send invitations")
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_COMPLETED)
        self.assertEqual(second.status, STATUS_PENDING)


class TestRefreshAfterStepChange(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Plan a birthday party")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def test_completing_step_one_makes_step_two_ready(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=[first.step_id]
        )
        self.plans.refresh_plan_step_statuses(self.plan.plan_id)
        self.assertEqual(second.status, STATUS_BLOCKED)

        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_COMPLETED)
        self.plans.refresh_after_step_change(self.plan.plan_id, first.step_id)

        self.assertEqual(second.status, STATUS_READY)

    def test_multi_step_dependency_chain_ready_propagates_one_link_at_a_time(self):
        # 1 -> 2 -> 3: completing 1 only frees 2 (which is still
        # PENDING); 3 stays BLOCKED until 2 itself is COMPLETED - a
        # single refresh never skips ahead in the chain.
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=[first.step_id]
        )
        third = self.plans.add_step(
            self.plan.plan_id, "Order the cake", dependencies=[second.step_id]
        )
        self.plans.refresh_plan_step_statuses(self.plan.plan_id)
        self.assertEqual(first.status, STATUS_READY)
        self.assertEqual(second.status, STATUS_BLOCKED)
        self.assertEqual(third.status, STATUS_BLOCKED)

        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_COMPLETED)
        self.plans.refresh_after_step_change(self.plan.plan_id, first.step_id)
        self.assertEqual(second.status, STATUS_READY)
        self.assertEqual(third.status, STATUS_BLOCKED)

        self.plans.update_step_status(self.plan.plan_id, second.step_id, STATUS_COMPLETED)
        self.plans.refresh_after_step_change(self.plan.plan_id, second.step_id)
        self.assertEqual(third.status, STATUS_READY)

    def test_unfinished_dependency_keeps_a_step_blocked(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=[first.step_id]
        )
        self.plans.refresh_after_step_change(self.plan.plan_id, first.step_id)
        self.assertEqual(first.status, STATUS_READY)
        self.assertEqual(second.status, STATUS_BLOCKED)

    def test_completed_steps_remain_unchanged(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_COMPLETED)
        second = self.plans.add_step(self.plan.plan_id, "Send invitations")
        self.plans.refresh_after_step_change(self.plan.plan_id, second.step_id)
        self.assertEqual(first.status, STATUS_COMPLETED)

    def test_in_progress_steps_remain_unchanged(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_IN_PROGRESS)
        self.plans.refresh_after_step_change(self.plan.plan_id, first.step_id)
        self.assertEqual(first.status, STATUS_IN_PROGRESS)

    def test_failed_dependency_does_not_produce_ready(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=[first.step_id]
        )
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_FAILED)
        self.plans.refresh_after_step_change(self.plan.plan_id, first.step_id)
        self.assertEqual(second.status, STATUS_BLOCKED)

    def test_invalid_dependency_reference_is_handled_safely(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=["no-such-step"]
        )
        # Refreshing after a change to a *real* step must not choke on
        # another step's dangling dependency - it should just stay
        # BLOCKED, never raise and never become READY.
        other = self.plans.add_step(self.plan.plan_id, "Book a venue")
        self.plans.refresh_after_step_change(self.plan.plan_id, other.step_id)
        self.assertEqual(step.status, STATUS_BLOCKED)

    def test_refresh_after_step_change_for_unknown_plan_raises(self):
        with self.assertRaises(ValueError):
            self.plans.refresh_after_step_change("does-not-exist", "any-step")

    def test_refresh_after_step_change_for_unknown_step_raises(self):
        with self.assertRaises(ValueError):
            self.plans.refresh_after_step_change(self.plan.plan_id, "does-not-exist")

    def test_refresh_after_step_change_returns_refreshed_steps(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=[first.step_id]
        )
        result = self.plans.refresh_after_step_change(self.plan.plan_id, first.step_id)
        self.assertEqual(result, [first, second])


class TestGetReadyStepIds(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Plan a birthday party")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def test_step_with_no_dependencies_is_ready(self):
        step = self.plans.add_step(self.plan.plan_id, "Book a venue")
        self.assertEqual(self.plans.get_ready_step_ids(self.plan.plan_id), [step.step_id])

    def test_step_with_unfinished_dependency_is_not_ready(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=[first.step_id]
        )
        ready = self.plans.get_ready_step_ids(self.plan.plan_id)
        self.assertIn(first.step_id, ready)
        self.assertNotIn(second.step_id, ready)

    def test_step_with_completed_dependency_is_ready(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=[first.step_id]
        )
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_COMPLETED)
        # `first` is now COMPLETED (no longer PENDING) so it drops out
        # of the ready list; `second`'s only dependency is resolved.
        self.assertEqual(self.plans.get_ready_step_ids(self.plan.plan_id), [second.step_id])

    def test_multiple_ready_steps_are_all_returned_in_order(self):
        first = self.plans.add_step(self.plan.plan_id, "Book a venue")
        second = self.plans.add_step(self.plan.plan_id, "Send invitations")
        third = self.plans.add_step(
            self.plan.plan_id, "Order the cake", dependencies=["no-such-step"]
        )
        self.assertEqual(
            self.plans.get_ready_step_ids(self.plan.plan_id),
            [first.step_id, second.step_id],
        )
        self.assertNotIn(third.step_id, self.plans.get_ready_step_ids(self.plan.plan_id))

    def test_step_with_invalid_dependency_reference_is_not_ready(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Send invitations", dependencies=["no-such-step"]
        )
        self.assertEqual(self.plans.get_ready_step_ids(self.plan.plan_id), [])

    def test_get_ready_step_ids_never_mutates_step_status(self):
        step = self.plans.add_step(self.plan.plan_id, "Book a venue")
        self.plans.get_ready_step_ids(self.plan.plan_id)
        self.assertEqual(step.status, STATUS_PENDING)

    def test_get_ready_step_ids_excludes_non_pending_steps(self):
        step = self.plans.add_step(self.plan.plan_id, "Book a venue")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_IN_PROGRESS)
        self.assertEqual(self.plans.get_ready_step_ids(self.plan.plan_id), [])

    def test_get_ready_step_ids_for_unknown_plan_raises(self):
        with self.assertRaises(ValueError):
            self.plans.get_ready_step_ids("does-not-exist")


class TestCheckPlanCapabilities(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        self.memory = MemorySystem(db_path)
        self.capabilities = CapabilitySystem(self.memory)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_plan_with_no_required_capabilities_returns_empty_list(self):
        self.plans.add_step(self.plan.plan_id, "Write the changelog entry")
        result = self.plans.check_plan_capabilities(self.plan.plan_id, self.capabilities)
        self.assertEqual(result, [])

    def test_plan_with_no_steps_returns_empty_list(self):
        result = self.plans.check_plan_capabilities(self.plan.plan_id, self.capabilities)
        self.assertEqual(result, [])

    def test_one_required_capability_registered_and_enabled(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        self.capabilities.set_enabled("code_analysis", True, status="active")
        step = self.plans.add_step(
            self.plan.plan_id, "Review the diff", required_capabilities=["code_analysis"]
        )

        result = self.plans.check_plan_capabilities(self.plan.plan_id, self.capabilities)

        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry["capability_name"], "code_analysis")
        self.assertTrue(entry["available"])
        self.assertEqual(entry["status"], "active")
        self.assertEqual(entry["required_by_steps"], [step.step_id])

    def test_one_required_capability_registered_but_disabled(self):
        self.capabilities.register("image_input", "Accept images.")
        step = self.plans.add_step(
            self.plan.plan_id, "Read the mockup", required_capabilities=["image_input"]
        )

        result = self.plans.check_plan_capabilities(self.plan.plan_id, self.capabilities)

        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry["capability_name"], "image_input")
        self.assertFalse(entry["available"])
        self.assertEqual(entry["status"], "planned")
        self.assertEqual(entry["required_by_steps"], [step.step_id])

    def test_multiple_distinct_capabilities_are_all_reported(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        self.capabilities.set_enabled("code_analysis", True, status="active")
        self.capabilities.register("file_input", "Accept files.")

        step_one = self.plans.add_step(
            self.plan.plan_id, "Read the file", required_capabilities=["file_input"]
        )
        step_two = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )

        result = self.plans.check_plan_capabilities(self.plan.plan_id, self.capabilities)
        by_name = {entry["capability_name"]: entry for entry in result}

        self.assertEqual(set(by_name.keys()), {"file_input", "code_analysis"})
        self.assertEqual(by_name["file_input"]["required_by_steps"], [step_one.step_id])
        self.assertEqual(by_name["code_analysis"]["required_by_steps"], [step_two.step_id])
        self.assertTrue(by_name["code_analysis"]["available"])
        self.assertFalse(by_name["file_input"]["available"])

    def test_duplicate_capability_requirement_across_steps_is_collapsed(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        self.capabilities.set_enabled("code_analysis", True, status="active")

        step_one = self.plans.add_step(
            self.plan.plan_id, "Review file A", required_capabilities=["code_analysis"]
        )
        step_two = self.plans.add_step(
            self.plan.plan_id, "Review file B", required_capabilities=["code_analysis"]
        )

        result = self.plans.check_plan_capabilities(self.plan.plan_id, self.capabilities)

        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry["capability_name"], "code_analysis")
        self.assertEqual(entry["required_by_steps"], [step_one.step_id, step_two.step_id])

    def test_duplicate_capability_requirement_within_one_step_is_not_repeated(self):
        step = self.plans.add_step(
            self.plan.plan_id,
            "Review file A twice",
            required_capabilities=["code_analysis", "code_analysis"],
        )
        result = self.plans.check_plan_capabilities(self.plan.plan_id, self.capabilities)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["required_by_steps"], [step.step_id])

    def test_mixed_registered_and_unregistered_capabilities(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        self.capabilities.set_enabled("code_analysis", True, status="active")

        step_one = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )
        step_two = self.plans.add_step(
            self.plan.plan_id,
            "Do something not built yet",
            required_capabilities=["time_travel"],
        )

        result = self.plans.check_plan_capabilities(self.plan.plan_id, self.capabilities)
        by_name = {entry["capability_name"]: entry for entry in result}

        self.assertTrue(by_name["code_analysis"]["available"])
        self.assertEqual(by_name["code_analysis"]["status"], "active")
        self.assertFalse(by_name["time_travel"]["available"])
        self.assertEqual(by_name["time_travel"]["status"], "unregistered")
        self.assertEqual(by_name["time_travel"]["required_by_steps"], [step_two.step_id])

    def test_unknown_plan_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.plans.check_plan_capabilities("does-not-exist", self.capabilities)

    def test_no_side_effects_on_capability_registry_or_steps(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        step = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )
        before_status = step.status
        before_registry = self.capabilities.all()

        self.plans.check_plan_capabilities(self.plan.plan_id, self.capabilities)

        self.assertEqual(step.status, before_status)
        after_registry = self.capabilities.all()
        self.assertEqual(
            [dict(row) for row in before_registry], [dict(row) for row in after_registry]
        )

    def test_no_side_effects_on_returned_list_mutation(self):
        """Mutating the returned list/dicts must never reach back into
        plan state - same "hand back a fresh structure" convention as
        describe_plan/to_dict."""
        step = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )
        result = self.plans.check_plan_capabilities(self.plan.plan_id, self.capabilities)
        result[0]["required_by_steps"].append("bogus-step")
        result[0]["capability_name"] = "mutated"

        fresh = self.plans.check_plan_capabilities(self.plan.plan_id, self.capabilities)
        self.assertEqual(fresh[0]["capability_name"], "code_analysis")
        self.assertEqual(fresh[0]["required_by_steps"], [step.step_id])


class TestCapabilityAwareStepStatus(unittest.TestCase):
    """refresh_step_status/refresh_plan_step_statuses/
    refresh_after_step_change, extended so a step also needs its
    required capabilities available (not just its dependencies
    resolved) before it can become READY."""

    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        self.memory = MemorySystem(db_path)
        self.capabilities = CapabilitySystem(self.memory)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_no_dependencies_and_no_required_capabilities_is_ready(self):
        step = self.plans.add_step(self.plan.plan_id, "Write the changelog")
        refreshed = self.plans.refresh_step_status(
            self.plan.plan_id, step.step_id, self.capabilities
        )
        self.assertEqual(refreshed.status, STATUS_READY)

    def test_dependencies_satisfied_and_capability_available_is_ready(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        self.capabilities.set_enabled("code_analysis", True, status="active")
        first = self.plans.add_step(self.plan.plan_id, "Write the code")
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_COMPLETED)
        second = self.plans.add_step(
            self.plan.plan_id,
            "Review the code",
            dependencies=[first.step_id],
            required_capabilities=["code_analysis"],
        )

        refreshed = self.plans.refresh_step_status(
            self.plan.plan_id, second.step_id, self.capabilities
        )
        self.assertEqual(refreshed.status, STATUS_READY)

    def test_dependency_blocked_stays_blocked_even_with_available_capability(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        self.capabilities.set_enabled("code_analysis", True, status="active")
        first = self.plans.add_step(self.plan.plan_id, "Write the code")
        second = self.plans.add_step(
            self.plan.plan_id,
            "Review the code",
            dependencies=[first.step_id],
            required_capabilities=["code_analysis"],
        )

        refreshed = self.plans.refresh_step_status(
            self.plan.plan_id, second.step_id, self.capabilities
        )
        self.assertEqual(refreshed.status, STATUS_BLOCKED)

    def test_missing_capability_blocks_step_with_no_unresolved_dependencies(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )
        refreshed = self.plans.refresh_step_status(
            self.plan.plan_id, step.step_id, self.capabilities
        )
        self.assertEqual(refreshed.status, STATUS_BLOCKED)

    def test_registered_but_disabled_capability_blocks_step(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        step = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )
        refreshed = self.plans.refresh_step_status(
            self.plan.plan_id, step.step_id, self.capabilities
        )
        self.assertEqual(refreshed.status, STATUS_BLOCKED)

    def test_mixed_available_and_unavailable_capabilities_blocks_step(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        self.capabilities.set_enabled("code_analysis", True, status="active")
        step = self.plans.add_step(
            self.plan.plan_id,
            "Review and add tests",
            required_capabilities=["code_analysis", "file_input"],
        )
        refreshed = self.plans.refresh_step_status(
            self.plan.plan_id, step.step_id, self.capabilities
        )
        self.assertEqual(refreshed.status, STATUS_BLOCKED)

    def test_capability_becoming_available_lets_step_become_ready(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        step = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )
        first = self.plans.refresh_step_status(
            self.plan.plan_id, step.step_id, self.capabilities
        )
        self.assertEqual(first.status, STATUS_BLOCKED)

        self.capabilities.set_enabled("code_analysis", True, status="active")
        second = self.plans.refresh_step_status(
            self.plan.plan_id, step.step_id, self.capabilities
        )
        self.assertEqual(second.status, STATUS_READY)

    def test_completed_failed_in_progress_are_never_overwritten_by_capability_check(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )
        for terminal_status in (STATUS_COMPLETED, STATUS_FAILED, STATUS_IN_PROGRESS):
            self.plans.update_step_status(self.plan.plan_id, step.step_id, terminal_status)
            refreshed = self.plans.refresh_step_status(
                self.plan.plan_id, step.step_id, self.capabilities
            )
            self.assertEqual(refreshed.status, terminal_status)

    def test_no_required_capabilities_preserves_previous_dependency_only_behavior(self):
        """A step with no required_capabilities behaves identically
        whether or not a capability_system is passed in."""
        step = self.plans.add_step(self.plan.plan_id, "Write the changelog")

        without_registry = self.plans.refresh_step_status(self.plan.plan_id, step.step_id)
        self.assertEqual(without_registry.status, STATUS_READY)

        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_PENDING)
        with_registry = self.plans.refresh_step_status(
            self.plan.plan_id, step.step_id, self.capabilities
        )
        self.assertEqual(with_registry.status, STATUS_READY)

    def test_omitting_capability_system_skips_the_capability_check_entirely(self):
        """Backward compatibility: existing callers that don't pass
        capability_system at all still get the old dependency-only
        behavior, even for a step that requires a capability that
        doesn't exist anywhere in the registry."""
        step = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )
        refreshed = self.plans.refresh_step_status(self.plan.plan_id, step.step_id)
        self.assertEqual(refreshed.status, STATUS_READY)

    def test_refresh_plan_step_statuses_applies_capability_check_to_every_step(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        self.capabilities.set_enabled("code_analysis", True, status="active")
        ready_step = self.plans.add_step(self.plan.plan_id, "Write the changelog")
        blocked_step = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["file_input"]
        )
        available_cap_step = self.plans.add_step(
            self.plan.plan_id, "Review other code", required_capabilities=["code_analysis"]
        )

        refreshed = self.plans.refresh_plan_step_statuses(self.plan.plan_id, self.capabilities)
        by_id = {s.step_id: s for s in refreshed}

        self.assertEqual(by_id[ready_step.step_id].status, STATUS_READY)
        self.assertEqual(by_id[blocked_step.step_id].status, STATUS_BLOCKED)
        self.assertEqual(by_id[available_cap_step.step_id].status, STATUS_READY)

    def test_refresh_after_step_change_propagates_capability_check(self):
        first = self.plans.add_step(self.plan.plan_id, "Write the code")
        second = self.plans.add_step(
            self.plan.plan_id,
            "Review the code",
            dependencies=[first.step_id],
            required_capabilities=["code_analysis"],
        )
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_COMPLETED)

        # capability not registered yet -> dependency resolved but
        # capability unavailable, so still BLOCKED
        refreshed = self.plans.refresh_after_step_change(
            self.plan.plan_id, first.step_id, self.capabilities
        )
        by_id = {s.step_id: s for s in refreshed}
        self.assertEqual(by_id[second.step_id].status, STATUS_BLOCKED)

        # now register and enable it, refresh again -> becomes READY
        self.capabilities.register("code_analysis", "Analyze source code.")
        self.capabilities.set_enabled("code_analysis", True, status="active")
        refreshed_again = self.plans.refresh_after_step_change(
            self.plan.plan_id, first.step_id, self.capabilities
        )
        by_id_again = {s.step_id: s for s in refreshed_again}
        self.assertEqual(by_id_again[second.step_id].status, STATUS_READY)

    def test_refresh_never_registers_enables_or_executes_a_capability(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )
        self.plans.refresh_step_status(self.plan.plan_id, step.step_id, self.capabilities)
        # nothing was auto-registered as a side effect of the check
        self.assertEqual(self.capabilities.all(), [])


class TestCheckPlanReadiness(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        self.memory = MemorySystem(db_path)
        self.capabilities = CapabilitySystem(self.memory)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_empty_plan_is_not_ready(self):
        result = self.plans.check_plan_readiness(self.plan.plan_id, self.capabilities)

        self.assertEqual(result["plan_id"], self.plan.plan_id)
        self.assertFalse(result["ready"])
        self.assertEqual(result["total_steps"], 0)
        self.assertEqual(result["ready_steps"], 0)
        self.assertEqual(result["blocked_steps"], 0)
        self.assertEqual(result["unavailable_capabilities"], [])
        self.assertEqual(result["unresolved_dependencies"], {})
        self.assertIn("Plan has no steps.", result["warnings"])

    def test_fully_ready_plan(self):
        self.plans.add_step(self.plan.plan_id, "Write the changelog")
        self.plans.add_step(self.plan.plan_id, "Tag the release")

        result = self.plans.check_plan_readiness(self.plan.plan_id, self.capabilities)

        self.assertTrue(result["ready"])
        self.assertEqual(result["total_steps"], 2)
        self.assertEqual(result["ready_steps"], 2)
        self.assertEqual(result["blocked_steps"], 0)
        self.assertEqual(result["unavailable_capabilities"], [])
        self.assertEqual(result["unresolved_dependencies"], {})
        self.assertEqual(result["warnings"], [])

    def test_plan_with_blocked_dependency_is_not_ready(self):
        first = self.plans.add_step(self.plan.plan_id, "Write the code")
        second = self.plans.add_step(
            self.plan.plan_id, "Review the code", dependencies=[first.step_id]
        )

        result = self.plans.check_plan_readiness(self.plan.plan_id, self.capabilities)

        self.assertFalse(result["ready"])
        self.assertEqual(result["total_steps"], 2)
        self.assertEqual(result["ready_steps"], 1)
        self.assertEqual(result["blocked_steps"], 1)
        self.assertEqual(result["unresolved_dependencies"], {second.step_id: [first.step_id]})

    def test_plan_with_unavailable_capability_is_not_ready(self):
        self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )

        result = self.plans.check_plan_readiness(self.plan.plan_id, self.capabilities)

        self.assertFalse(result["ready"])
        self.assertEqual(result["total_steps"], 1)
        self.assertEqual(result["ready_steps"], 0)
        self.assertEqual(result["blocked_steps"], 1)
        self.assertEqual(len(result["unavailable_capabilities"]), 1)
        entry = result["unavailable_capabilities"][0]
        self.assertEqual(entry["capability_name"], "code_analysis")
        self.assertFalse(entry["available"])
        self.assertEqual(entry["status"], "unregistered")

    def test_plan_with_mixed_ready_and_blocked_steps(self):
        ready_step = self.plans.add_step(self.plan.plan_id, "Write the changelog")
        blocked_step = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )

        result = self.plans.check_plan_readiness(self.plan.plan_id, self.capabilities)

        self.assertFalse(result["ready"])
        self.assertEqual(result["total_steps"], 2)
        self.assertEqual(result["ready_steps"], 1)
        self.assertEqual(result["blocked_steps"], 1)
        self.assertEqual(
            result["unavailable_capabilities"][0]["required_by_steps"], [blocked_step.step_id]
        )

    def test_plan_with_multiple_unavailable_capabilities(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        step = self.plans.add_step(
            self.plan.plan_id,
            "Review and read files",
            required_capabilities=["code_analysis", "file_input"],
        )

        result = self.plans.check_plan_readiness(self.plan.plan_id, self.capabilities)

        self.assertFalse(result["ready"])
        self.assertEqual(result["blocked_steps"], 1)
        names = {entry["capability_name"] for entry in result["unavailable_capabilities"]}
        self.assertEqual(names, {"code_analysis", "file_input"})
        for entry in result["unavailable_capabilities"]:
            self.assertEqual(entry["required_by_steps"], [step.step_id])

    def test_readiness_recognizes_available_capabilities(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        self.capabilities.set_enabled("code_analysis", True, status="active")
        self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )

        result = self.plans.check_plan_readiness(self.plan.plan_id, self.capabilities)

        self.assertTrue(result["ready"])
        self.assertEqual(result["ready_steps"], 1)
        self.assertEqual(result["blocked_steps"], 0)
        self.assertEqual(result["unavailable_capabilities"], [])

    def test_correct_step_counts_across_several_steps(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        self.capabilities.set_enabled("code_analysis", True, status="active")
        self.plans.add_step(self.plan.plan_id, "Ready step one")
        self.plans.add_step(self.plan.plan_id, "Ready step two", required_capabilities=["code_analysis"])
        self.plans.add_step(self.plan.plan_id, "Blocked - missing capability", required_capabilities=["file_input"])
        first = self.plans.add_step(self.plan.plan_id, "Not yet completed dependency")
        self.plans.add_step(
            self.plan.plan_id, "Blocked - dependency", dependencies=[first.step_id]
        )

        result = self.plans.check_plan_readiness(self.plan.plan_id, self.capabilities)

        self.assertEqual(result["total_steps"], 5)
        self.assertEqual(result["ready_steps"], 3)
        self.assertEqual(result["blocked_steps"], 2)
        self.assertEqual(result["ready_steps"] + result["blocked_steps"], result["total_steps"])

    def test_unknown_plan_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.plans.check_plan_readiness("does-not-exist", self.capabilities)

    def test_no_side_effects_on_step_status_capability_registry_or_plan_status(self):
        self.capabilities.register("code_analysis", "Analyze source code.")
        step = self.plans.add_step(
            self.plan.plan_id, "Review the code", required_capabilities=["code_analysis"]
        )
        before_step_status = step.status
        before_plan_status = self.plan.status
        before_registry = self.capabilities.all()

        self.plans.check_plan_readiness(self.plan.plan_id, self.capabilities)

        self.assertEqual(step.status, before_step_status)
        self.assertEqual(self.plan.status, before_plan_status)
        after_registry = self.capabilities.all()
        self.assertEqual(
            [dict(row) for row in before_registry], [dict(row) for row in after_registry]
        )

    def test_no_side_effects_on_returned_result_mutation(self):
        self.plans.add_step(self.plan.plan_id, "Write the changelog")
        result = self.plans.check_plan_readiness(self.plan.plan_id, self.capabilities)
        result["ready"] = False
        result["warnings"].append("bogus")

        fresh = self.plans.check_plan_readiness(self.plan.plan_id, self.capabilities)
        self.assertTrue(fresh["ready"])
        self.assertEqual(fresh["warnings"], [])


class TestRetrievePlan(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Write a report")

    def test_get_plan_returns_the_stored_plan(self):
        created = self.plans.create_plan(self.goal.goal_id)
        fetched = self.plans.get_plan(created.plan_id)
        self.assertIs(fetched, created)

    def test_get_plan_returns_none_for_unknown_id(self):
        self.assertIsNone(self.plans.get_plan("does-not-exist"))

    def test_all_plans_returns_every_stored_plan(self):
        first = self.plans.create_plan(self.goal.goal_id)
        second = self.plans.create_plan(self.goal.goal_id)
        self.assertEqual(self.plans.all_plans(), [first, second])


class TestStructuredRepresentation(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Ship the feature")

    def test_describe_plan_matches_to_dict(self):
        plan = self.plans.create_plan(self.goal.goal_id, required_capabilities=["ci_access"])
        self.plans.add_step(plan.plan_id, "Write tests")
        described = self.plans.describe_plan(plan.plan_id)
        self.assertEqual(described, plan.to_dict())

    def test_describe_plan_is_json_shaped(self):
        plan = self.plans.create_plan(self.goal.goal_id)
        self.plans.add_step(plan.plan_id, "Write tests")
        described = self.plans.describe_plan(plan.plan_id)
        for key in (
            "plan_id", "goal_id", "steps", "dependencies", "required_capabilities",
            "expected_outputs", "status", "confidence", "warnings", "created_at", "metadata",
        ):
            self.assertIn(key, described)
        for step_key in (
            "step_id", "description", "dependencies", "required_capabilities",
            "expected_output", "status",
        ):
            self.assertIn(step_key, described["steps"][0])

    def test_describe_plan_returns_none_for_unknown_id(self):
        self.assertIsNone(self.plans.describe_plan("does-not-exist"))

    def test_debug_state_reports_every_plan(self):
        self.plans.create_plan(self.goal.goal_id)
        self.plans.create_plan(self.goal.goal_id)
        state = self.plans.debug_state()
        self.assertEqual(state["plan_count"], 2)
        self.assertEqual(len(state["plans"]), 2)


class TestInvalidInput(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Refactor the parser")

    def test_create_plan_for_unknown_goal_id_raises(self):
        with self.assertRaises(ValueError):
            self.plans.create_plan("does-not-exist")

    def test_create_plan_for_empty_goal_id_raises(self):
        with self.assertRaises(ValueError):
            self.plans.create_plan("")

    def test_create_plan_for_none_goal_id_raises(self):
        with self.assertRaises(ValueError):
            self.plans.create_plan(None)

    def test_failed_plan_creation_stores_nothing(self):
        try:
            self.plans.create_plan("does-not-exist")
        except ValueError:
            pass
        self.assertEqual(len(self.plans), 0)

    def test_add_step_to_unknown_plan_raises(self):
        with self.assertRaises(ValueError):
            self.plans.add_step("does-not-exist", "Do something")

    def test_add_step_with_empty_description_raises(self):
        plan = self.plans.create_plan(self.goal.goal_id)
        with self.assertRaises(ValueError):
            self.plans.add_step(plan.plan_id, "")

    def test_add_step_with_whitespace_only_description_raises(self):
        plan = self.plans.create_plan(self.goal.goal_id)
        with self.assertRaises(ValueError):
            self.plans.add_step(plan.plan_id, "   \n\t  ")

    def test_failed_step_addition_leaves_plan_unchanged(self):
        plan = self.plans.create_plan(self.goal.goal_id)
        try:
            self.plans.add_step(plan.plan_id, "")
        except ValueError:
            pass
        self.assertEqual(len(plan.steps), 0)

    def test_plan_rejects_unknown_status_directly(self):
        with self.assertRaises(ValueError):
            Plan(plan_id="plan-x", goal_id="goal-x", status="not_a_real_status")

    def test_plan_step_rejects_unknown_status_directly(self):
        with self.assertRaises(ValueError):
            PlanStep(step_id="step-x", description="x", status="not_a_real_status")

    def test_plan_rejects_step_only_status_ready(self):
        # READY/BLOCKED are step-only concepts (dependency readiness);
        # a Plan's own status vocabulary doesn't include them.
        with self.assertRaises(ValueError):
            Plan(plan_id="plan-x", goal_id="goal-x", status=STATUS_READY)

    def test_plan_manager_requires_a_goal_manager(self):
        with self.assertRaises(TypeError):
            PlanManager(goal_manager=object())


class TestCoreIntegration(unittest.TestCase):
    """Confirms PlanManager is wired into Core without changing any
    existing behaviour (AEL/conversation routing untouched)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_core_exposes_plan_creation_step_addition_and_retrieval(self):
        goal = self.core.create_goal("Refactor the parser")
        plan = self.core.create_plan(goal.goal_id, required_capabilities=["code_analysis"])
        step = self.core.add_plan_step(plan.plan_id, "Read the existing parser")

        self.assertEqual(self.core.get_plan(plan.plan_id).plan_id, plan.plan_id)
        described = self.core.describe_plan(plan.plan_id)
        self.assertEqual(described["goal_id"], goal.goal_id)
        self.assertEqual(described["steps"][0]["step_id"], step.step_id)

    def test_create_plan_for_unknown_goal_raises_through_core(self):
        with self.assertRaises(ValueError):
            self.core.create_plan("does-not-exist")

    def test_existing_conversation_flow_is_unaffected(self):
        reply = self.core.process_input("hello")
        self.assertIsInstance(reply, str)
        self.assertEqual(len(self.core.goals), 0)
        self.assertEqual(len(self.core.plans), 0)


if __name__ == "__main__":
    unittest.main()
