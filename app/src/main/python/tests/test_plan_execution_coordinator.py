"""
Tests for PlanExecutionCoordinator (execution/plan_execution_coordinator.py)
- read-only inspection of which PlanStep should run next, built
entirely on the existing PreflightValidator/CapabilityHandlerRegistry
readiness logic.

Covers: an empty plan, a missing plan, completed/failed/blocked steps
being skipped, a READY step with every requirement available, a READY
step with a missing/unavailable capability, a READY step with a
missing handler, multiple READY steps and correct first-executable
selection, and inspect_execution_state's structured summary.

Run directly:
    python -m unittest tests.test_plan_execution_coordinator -v
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
from planning.plan import (
    STATUS_PENDING, STATUS_READY, STATUS_BLOCKED, STATUS_COMPLETED, STATUS_FAILED,
)
from execution.plan_execution_coordinator import PlanExecutionCoordinator
from execution.capability_handlers import CapabilityHandlerRegistry


class FakeCapabilitySystem:
    """Minimal stand-in for capabilities.capability_system.CapabilitySystem
    - exposes only the read-only `.all()` registry lookup, same
    convention already used by tests/test_preflight.py's own
    FakeCapabilitySystem."""

    def __init__(self, registered=None):
        self._registered = dict(registered) if registered else {}

    def all(self):
        return [
            {"name": name, "enabled": enabled, "status": "enabled" if enabled else "disabled"}
            for name, enabled in self._registered.items()
        ]


class TestCoordinatorBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.handlers = CapabilityHandlerRegistry()
        self.coordinator = PlanExecutionCoordinator(self.plans, capability_handlers=self.handlers)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)


class TestConstruction(unittest.TestCase):
    def test_requires_plan_manager_instance(self):
        with self.assertRaises(TypeError):
            PlanExecutionCoordinator(object())

    def test_rejects_bad_capability_handlers_type(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            PlanExecutionCoordinator(plans, capability_handlers=object())

    def test_rejects_bad_executable_capabilities_type(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            PlanExecutionCoordinator(plans, executable_capabilities=object())

    def test_default_registries_are_created_when_omitted(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        coordinator = PlanExecutionCoordinator(plans)
        self.assertIsInstance(coordinator.capability_handlers, CapabilityHandlerRegistry)


class TestEmptyPlan(TestCoordinatorBase):
    def test_get_next_ready_step_on_empty_plan(self):
        result = self.coordinator.get_next_ready_step(self.plan.plan_id)
        self.assertFalse(result["executable"])
        self.assertIsNone(result["step_id"])
        self.assertIsNone(result["step"])

    def test_inspect_execution_state_on_empty_plan(self):
        state = self.coordinator.inspect_execution_state(self.plan.plan_id)
        self.assertEqual(state["total_steps"], 0)
        self.assertEqual(state["ready_steps"], 0)
        self.assertEqual(state["executable_steps"], 0)
        self.assertIsNone(state["next_step_id"])
        self.assertTrue(state["warnings"])


class TestMissingPlan(TestCoordinatorBase):
    def test_get_next_ready_step_missing_plan_returns_structured_result(self):
        result = self.coordinator.get_next_ready_step("no-such-plan")
        self.assertFalse(result["executable"])
        self.assertIsNone(result["step_id"])
        self.assertTrue(result["reason"])

    def test_inspect_execution_state_missing_plan_raises(self):
        with self.assertRaises(ValueError):
            self.coordinator.inspect_execution_state("no-such-plan")


class TestCompletedAndFailedStepsSkipped(TestCoordinatorBase):
    def test_completed_step_never_selected(self):
        step = self.plans.add_step(self.plan.plan_id, "Done already")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)

        result = self.coordinator.get_next_ready_step(self.plan.plan_id)
        self.assertFalse(result["executable"])
        self.assertIsNone(result["step_id"])

    def test_failed_step_never_selected(self):
        step = self.plans.add_step(self.plan.plan_id, "Blew up")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)

        result = self.coordinator.get_next_ready_step(self.plan.plan_id)
        self.assertFalse(result["executable"])

    def test_completed_and_failed_counted_in_inspect_state(self):
        completed = self.plans.add_step(self.plan.plan_id, "Done")
        failed = self.plans.add_step(self.plan.plan_id, "Broke")
        self.plans.update_step_status(self.plan.plan_id, completed.step_id, STATUS_COMPLETED)
        self.plans.update_step_status(self.plan.plan_id, failed.step_id, STATUS_FAILED)

        state = self.coordinator.inspect_execution_state(self.plan.plan_id)
        self.assertEqual(state["completed_steps"], 1)
        self.assertEqual(state["failed_steps"], 1)
        self.assertEqual(state["ready_steps"], 0)


class TestBlockedSteps(TestCoordinatorBase):
    def test_blocked_step_never_selected(self):
        upstream = self.plans.add_step(self.plan.plan_id, "Upstream")
        blocked = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id],
        )
        self.plans.refresh_plan_step_statuses(self.plan.plan_id)
        self.assertEqual(blocked.status, STATUS_BLOCKED)

        result = self.coordinator.get_next_ready_step(self.plan.plan_id)
        # upstream itself has no dependencies, so refresh makes it
        # READY and it's correctly selected - the point of this test
        # is that the BLOCKED step is never the one chosen.
        self.assertNotEqual(result.get("step_id"), blocked.step_id)
        self.assertEqual(result["step_id"], upstream.step_id)

    def test_blocked_step_counted_in_inspect_state(self):
        upstream = self.plans.add_step(self.plan.plan_id, "Upstream")
        self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id],
        )
        self.plans.refresh_plan_step_statuses(self.plan.plan_id)

        state = self.coordinator.inspect_execution_state(self.plan.plan_id)
        self.assertEqual(state["blocked_steps"], 1)


class TestReadyStepFullyAvailable(TestCoordinatorBase):
    def test_ready_step_with_no_required_capabilities_is_executable(self):
        step = self.plans.add_step(self.plan.plan_id, "Simple step")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)

        result = self.coordinator.get_next_ready_step(self.plan.plan_id)
        self.assertTrue(result["executable"])
        self.assertEqual(result["step_id"], step.step_id)
        self.assertIs(result["step"], step)

    def test_ready_step_with_available_capability_and_handler_is_executable(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Needs a capability", required_capabilities=["net_fetch"],
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        self.handlers.register("net_fetch", lambda s: "ok")
        capability_system = FakeCapabilitySystem({"net_fetch": True})

        result = self.coordinator.get_next_ready_step(self.plan.plan_id, capability_system)
        self.assertTrue(result["executable"])
        self.assertEqual(result["step_id"], step.step_id)


class TestReadyStepMissingCapability(TestCoordinatorBase):
    def test_ready_step_with_unregistered_capability_is_not_executable(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Needs a capability", required_capabilities=["net_fetch"],
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        self.handlers.register("net_fetch", lambda s: "ok")
        capability_system = FakeCapabilitySystem({})  # nothing registered

        result = self.coordinator.get_next_ready_step(self.plan.plan_id, capability_system)
        self.assertFalse(result["executable"])
        self.assertIsNone(result["step_id"])
        self.assertTrue(result["warnings"])

    def test_ready_step_with_disabled_capability_is_not_executable(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Needs a capability", required_capabilities=["net_fetch"],
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        self.handlers.register("net_fetch", lambda s: "ok")
        capability_system = FakeCapabilitySystem({"net_fetch": False})

        result = self.coordinator.get_next_ready_step(self.plan.plan_id, capability_system)
        self.assertFalse(result["executable"])


class TestReadyStepMissingHandler(TestCoordinatorBase):
    def test_ready_step_with_no_registered_handler_is_not_executable(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Needs a capability", required_capabilities=["net_fetch"],
        )
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        # Capability is available, but no handler was ever registered.
        capability_system = FakeCapabilitySystem({"net_fetch": True})

        result = self.coordinator.get_next_ready_step(self.plan.plan_id, capability_system)
        self.assertFalse(result["executable"])
        self.assertIsNone(result["step_id"])
        self.assertIn("missing handlers", result["warnings"][0])


class TestMultipleReadySteps(TestCoordinatorBase):
    def test_selects_first_executable_step_in_plan_order(self):
        step_a = self.plans.add_step(self.plan.plan_id, "First")
        step_b = self.plans.add_step(self.plan.plan_id, "Second")
        self.plans.update_step_status(self.plan.plan_id, step_a.step_id, STATUS_READY)
        self.plans.update_step_status(self.plan.plan_id, step_b.step_id, STATUS_READY)

        result = self.coordinator.get_next_ready_step(self.plan.plan_id)
        self.assertEqual(result["step_id"], step_a.step_id)

    def test_skips_non_executable_ready_step_and_picks_next(self):
        step_a = self.plans.add_step(
            self.plan.plan_id, "Needs missing capability",
            required_capabilities=["net_fetch"],
        )
        step_b = self.plans.add_step(self.plan.plan_id, "Plain step")
        self.plans.update_step_status(self.plan.plan_id, step_a.step_id, STATUS_READY)
        self.plans.update_step_status(self.plan.plan_id, step_b.step_id, STATUS_READY)
        capability_system = FakeCapabilitySystem({})  # net_fetch not registered

        result = self.coordinator.get_next_ready_step(self.plan.plan_id, capability_system)
        self.assertTrue(result["executable"])
        self.assertEqual(result["step_id"], step_b.step_id)
        self.assertTrue(result["warnings"])  # step_a's problem recorded

    def test_all_ready_steps_unexecutable_returns_none(self):
        step_a = self.plans.add_step(
            self.plan.plan_id, "Needs missing capability A",
            required_capabilities=["cap_a"],
        )
        step_b = self.plans.add_step(
            self.plan.plan_id, "Needs missing capability B",
            required_capabilities=["cap_b"],
        )
        self.plans.update_step_status(self.plan.plan_id, step_a.step_id, STATUS_READY)
        self.plans.update_step_status(self.plan.plan_id, step_b.step_id, STATUS_READY)
        capability_system = FakeCapabilitySystem({})

        result = self.coordinator.get_next_ready_step(self.plan.plan_id, capability_system)
        self.assertFalse(result["executable"])
        self.assertIsNone(result["step_id"])
        self.assertEqual(len(result["warnings"]), 2)


class TestInspectExecutionState(TestCoordinatorBase):
    def test_result_shape_has_all_required_keys(self):
        step = self.plans.add_step(self.plan.plan_id, "Simple step")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)

        state = self.coordinator.inspect_execution_state(self.plan.plan_id)
        for key in (
            "plan_id", "total_steps", "ready_steps", "executable_steps",
            "blocked_steps", "completed_steps", "failed_steps", "next_step_id",
            "warnings",
        ):
            self.assertIn(key, state)

    def test_counts_reflect_mixed_plan(self):
        ready_executable = self.plans.add_step(self.plan.plan_id, "Ready and fine")
        ready_blocked_cap = self.plans.add_step(
            self.plan.plan_id, "Ready but missing capability",
            required_capabilities=["cap_x"],
        )
        upstream = self.plans.add_step(self.plan.plan_id, "Upstream")
        blocked = self.plans.add_step(
            self.plan.plan_id, "Blocked", dependencies=[upstream.step_id],
        )
        completed = self.plans.add_step(self.plan.plan_id, "Completed")
        failed = self.plans.add_step(self.plan.plan_id, "Failed")

        self.plans.update_step_status(self.plan.plan_id, ready_executable.step_id, STATUS_READY)
        self.plans.update_step_status(self.plan.plan_id, ready_blocked_cap.step_id, STATUS_READY)
        self.plans.refresh_plan_step_statuses(self.plan.plan_id)
        self.plans.update_step_status(self.plan.plan_id, completed.step_id, STATUS_COMPLETED)
        self.plans.update_step_status(self.plan.plan_id, failed.step_id, STATUS_FAILED)

        capability_system = FakeCapabilitySystem({})  # cap_x unavailable
        state = self.coordinator.inspect_execution_state(self.plan.plan_id, capability_system)

        self.assertEqual(state["total_steps"], 6)
        self.assertEqual(state["ready_steps"], 3)
        self.assertEqual(state["executable_steps"], 2)
        self.assertEqual(state["blocked_steps"], 1)
        self.assertEqual(state["completed_steps"], 1)
        self.assertEqual(state["failed_steps"], 1)
        self.assertEqual(state["next_step_id"], ready_executable.step_id)


class TestNoExecutionSideEffects(TestCoordinatorBase):
    def test_get_next_ready_step_never_changes_status(self):
        step = self.plans.add_step(self.plan.plan_id, "Simple step")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)

        self.coordinator.get_next_ready_step(self.plan.plan_id)
        self.assertEqual(step.status, STATUS_READY)

    def test_inspect_execution_state_never_changes_status(self):
        step = self.plans.add_step(self.plan.plan_id, "Simple step")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)

        self.coordinator.inspect_execution_state(self.plan.plan_id)
        self.assertEqual(step.status, STATUS_READY)

    def test_no_output_or_input_data_is_ever_written(self):
        step = self.plans.add_step(self.plan.plan_id, "Simple step")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)

        self.coordinator.get_next_ready_step(self.plan.plan_id)
        self.coordinator.inspect_execution_state(self.plan.plan_id)
        self.assertIsNone(step.get_input())
        self.assertIsNone(step.get_output())


if __name__ == "__main__":
    unittest.main()
