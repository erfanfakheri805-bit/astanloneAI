"""
Tests for StepExecutionPreparation (execution/step_execution_preparation.py)
- a read-only preparation layer that validates a single PlanStep is
safe to execute, built entirely on the existing PreflightValidator /
PlanExecutionCoordinator / CapabilityHandlerRegistry /
ExecutableCapabilityRegistry readiness logic, and never executes
anything itself.

Covers: a missing plan, a missing step, a blocked step, a completed
step, a missing dependency, a missing capability, an unavailable
(disabled) capability, a missing handler, a valid executable step, a
valid step with input data, and invalid/missing input data. Also
covers that a successful `prepare()` never mutates the plan/step, and
that construction rejects bad collaborator types (matching
PlanExecutionCoordinator's own construction guards).

Run directly:
    python -m unittest tests.test_step_execution_preparation -v
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
    STATUS_PENDING, STATUS_READY, STATUS_BLOCKED, STATUS_COMPLETED,
)
from execution.step_execution_preparation import (
    StepExecutionPreparation,
    CHECK_HANDLERS_REGISTERED,
    CHECK_INPUT_DATA_VALID,
)
from execution.preflight import (
    CHECK_PLAN_EXISTS,
    CHECK_STEP_EXISTS,
    CHECK_STEP_READY,
    CHECK_DEPENDENCIES_SATISFIED,
    CHECK_CAPABILITIES_AVAILABLE,
)
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


def _noop_handler(step):
    """A trivial, never-actually-called handler for registration tests
    - StepExecutionPreparation must never call this (see
    test_prepare_never_calls_handler_or_executes)."""
    raise AssertionError("StepExecutionPreparation must never call a handler.")


class StepExecutionPreparationTestBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.handlers = CapabilityHandlerRegistry()
        self.prep = StepExecutionPreparation(self.plans, capability_handlers=self.handlers)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)


class TestConstruction(unittest.TestCase):
    def test_requires_plan_manager_instance(self):
        with self.assertRaises(TypeError):
            StepExecutionPreparation(object())

    def test_rejects_bad_capability_handlers_type(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            StepExecutionPreparation(plans, capability_handlers=object())

    def test_rejects_bad_executable_capabilities_type(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            StepExecutionPreparation(plans, executable_capabilities=object())

    def test_default_registries_are_created_when_omitted(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        prep = StepExecutionPreparation(plans)
        self.assertIsInstance(prep.capability_handlers, CapabilityHandlerRegistry)


class TestMissingPlanOrStep(StepExecutionPreparationTestBase):
    def test_missing_plan(self):
        result = self.prep.prepare("no-such-plan", "no-such-step")
        self.assertFalse(result["prepared"])
        self.assertEqual(result["plan_id"], "no-such-plan")
        self.assertEqual(result["step_id"], "no-such-step")
        self.assertIsNone(result["status"])
        self.assertEqual(result["capabilities"], [])
        self.assertIsNone(result["input_data"])
        checks = [fc["check"] for fc in result["failed_checks"]]
        self.assertIn(CHECK_PLAN_EXISTS, checks)

    def test_missing_step(self):
        result = self.prep.prepare(self.plan.plan_id, "no-such-step")
        self.assertFalse(result["prepared"])
        self.assertIsNone(result["status"])
        self.assertEqual(result["capabilities"], [])
        checks = [fc["check"] for fc in result["failed_checks"]]
        self.assertIn(CHECK_STEP_EXISTS, checks)


class TestStepStatusChecks(StepExecutionPreparationTestBase):
    def test_blocked_step(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Do a thing", status=STATUS_BLOCKED,
        )
        result = self.prep.prepare(self.plan.plan_id, step.step_id)
        self.assertFalse(result["prepared"])
        self.assertEqual(result["status"], STATUS_BLOCKED)
        checks = [fc["check"] for fc in result["failed_checks"]]
        self.assertIn(CHECK_STEP_READY, checks)

    def test_completed_step(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Do a thing", status=STATUS_COMPLETED,
        )
        result = self.prep.prepare(self.plan.plan_id, step.step_id)
        self.assertFalse(result["prepared"])
        self.assertEqual(result["status"], STATUS_COMPLETED)
        checks = [fc["check"] for fc in result["failed_checks"]]
        self.assertIn(CHECK_STEP_READY, checks)


class TestDependencyAndCapabilityChecks(StepExecutionPreparationTestBase):
    def test_missing_dependency(self):
        step = self.plans.add_step(
            self.plan.plan_id,
            "Do a thing",
            dependencies=["never-created-step"],
            status=STATUS_READY,
        )
        result = self.prep.prepare(self.plan.plan_id, step.step_id)
        self.assertFalse(result["prepared"])
        checks = [fc["check"] for fc in result["failed_checks"]]
        self.assertIn(CHECK_DEPENDENCIES_SATISFIED, checks)

    def test_missing_capability(self):
        step = self.plans.add_step(
            self.plan.plan_id,
            "Do a thing",
            required_capabilities=["search_web"],
            status=STATUS_READY,
        )
        caps = FakeCapabilitySystem()  # nothing registered
        result = self.prep.prepare(self.plan.plan_id, step.step_id, caps)
        self.assertFalse(result["prepared"])
        checks = [fc["check"] for fc in result["failed_checks"]]
        self.assertIn(CHECK_CAPABILITIES_AVAILABLE, checks)
        self.assertEqual(result["capabilities"], ["search_web"])

    def test_unavailable_capability(self):
        step = self.plans.add_step(
            self.plan.plan_id,
            "Do a thing",
            required_capabilities=["search_web"],
            status=STATUS_READY,
        )
        self.handlers.register("search_web", _noop_handler)
        caps = FakeCapabilitySystem({"search_web": False})  # registered, disabled
        result = self.prep.prepare(self.plan.plan_id, step.step_id, caps)
        self.assertFalse(result["prepared"])
        checks = [fc["check"] for fc in result["failed_checks"]]
        self.assertIn(CHECK_CAPABILITIES_AVAILABLE, checks)

    def test_missing_handler(self):
        step = self.plans.add_step(
            self.plan.plan_id,
            "Do a thing",
            required_capabilities=["search_web"],
            status=STATUS_READY,
        )
        # Capability itself is registered and enabled, but no handler
        # has been registered for it anywhere.
        caps = FakeCapabilitySystem({"search_web": True})
        result = self.prep.prepare(self.plan.plan_id, step.step_id, caps)
        self.assertFalse(result["prepared"])
        checks = [fc["check"] for fc in result["failed_checks"]]
        self.assertIn(CHECK_HANDLERS_REGISTERED, checks)
        self.assertNotIn(CHECK_CAPABILITIES_AVAILABLE, checks)


class TestValidPreparation(StepExecutionPreparationTestBase):
    def test_valid_executable_step(self):
        step = self.plans.add_step(
            self.plan.plan_id,
            "Do a thing",
            required_capabilities=["search_web"],
            status=STATUS_READY,
        )
        self.handlers.register("search_web", _noop_handler)
        caps = FakeCapabilitySystem({"search_web": True})
        result = self.prep.prepare(self.plan.plan_id, step.step_id, caps)
        self.assertTrue(result["prepared"])
        self.assertEqual(result["failed_checks"], [])
        self.assertEqual(result["status"], STATUS_READY)
        self.assertEqual(result["capabilities"], ["search_web"])
        # Preparing must never actually execute the step.
        self.assertEqual(step.status, STATUS_READY)

    def test_valid_step_with_input_data(self):
        step = self.plans.add_step(
            self.plan.plan_id,
            "Do a thing",
            status=STATUS_READY,
            input_data={"query": "weather", "count": 3},
        )
        result = self.prep.prepare(self.plan.plan_id, step.step_id)
        self.assertTrue(result["prepared"])
        self.assertEqual(result["input_data"], {"query": "weather", "count": 3})

    def test_missing_input_data_does_not_block(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Do a thing", status=STATUS_READY,
        )
        result = self.prep.prepare(self.plan.plan_id, step.step_id)
        self.assertTrue(result["prepared"])
        self.assertIsNone(result["input_data"])

    def test_invalid_input_data_blocks_preparation(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Do a thing", status=STATUS_READY,
        )
        # Simulate tampered/corrupted state bypassing PlanStep.set_input's
        # own ensure_structured_data guard, so prepare()'s defensive
        # re-validation has something real to catch.
        step.input_data = object()
        result = self.prep.prepare(self.plan.plan_id, step.step_id)
        self.assertFalse(result["prepared"])
        checks = [fc["check"] for fc in result["failed_checks"]]
        self.assertIn(CHECK_INPUT_DATA_VALID, checks)

    def test_prepare_never_calls_handler_or_executes(self):
        step = self.plans.add_step(
            self.plan.plan_id,
            "Do a thing",
            required_capabilities=["search_web"],
            status=STATUS_READY,
        )
        self.handlers.register("search_web", _noop_handler)
        caps = FakeCapabilitySystem({"search_web": True})
        # _noop_handler raises AssertionError if ever actually called -
        # this only passes if prepare() never invokes it.
        result = self.prep.prepare(self.plan.plan_id, step.step_id, caps)
        self.assertTrue(result["prepared"])

    def test_prepare_does_not_mutate_plan_or_step(self):
        step = self.plans.add_step(
            self.plan.plan_id,
            "Do a thing",
            required_capabilities=["search_web"],
            status=STATUS_READY,
            input_data={"a": 1},
        )
        self.handlers.register("search_web", _noop_handler)
        caps = FakeCapabilitySystem({"search_web": True})
        before = step.to_dict()
        self.prep.prepare(self.plan.plan_id, step.step_id, caps)
        after = step.to_dict()
        self.assertEqual(before, after)
        self.assertEqual(len(self.plan.steps), 1)


class TestFailedPreparationLeavesStateUntouched(StepExecutionPreparationTestBase):
    def test_failed_preparation_does_not_change_status(self):
        step = self.plans.add_step(
            self.plan.plan_id,
            "Do a thing",
            dependencies=["never-created-step"],
            status=STATUS_READY,
        )
        self.prep.prepare(self.plan.plan_id, step.step_id)
        self.assertEqual(step.status, STATUS_READY)


if __name__ == "__main__":
    unittest.main()
