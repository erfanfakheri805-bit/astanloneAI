"""
Tests for PlanExecutionController (execution/plan_execution_controller.py)
- controlled, sequential execution of an existing Plan's steps, built
entirely on the existing PlanManager/PlanExecutionCoordinator/
StepExecutionController/ExecutionEngine stack, never a second copy of
any of their logic.

Covers: empty plan, missing plan, one-step plan, multi-step sequential
plan, dependency ordering, multiple independent steps, a blocked step,
a failed step, an unavailable capability, a missing handler, plan
completion, plan failure, plan blocked state, cycle detection,
max_steps_per_run, correct execution order, output propagation,
ExecutionHistory/ExecutionEventLog integration, no duplicate
execution, no execution of blocked steps, no automatic retry, and no
arbitrary code execution.

Run directly:
    python -m unittest tests.test_plan_execution_controller -v
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

from execution.plan_execution_controller import (
    PlanExecutionController, PLAN_RUN_COMPLETED, PLAN_RUN_BLOCKED,
    PLAN_RUN_FAILED, PLAN_RUN_WAITING, DEFAULT_MAX_STEPS_PER_RUN,
)
from execution.plan_execution_coordinator import PlanExecutionCoordinator
from execution.step_execution_controller import StepExecutionController
from execution.execution_engine import ExecutionEngine
from execution.execution_history import ExecutionHistory
from execution.execution_event_log import ExecutionEventLog
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.executable_registry import ExecutableCapabilityRegistry


class FakeCapabilitySystem:
    """Minimal stand-in for capabilities.capability_system.CapabilitySystem
    - same convention already used across this project's execution
    tests (test_preflight.py, test_step_execution_controller.py, ...)."""

    def __init__(self, registered=None):
        self._registered = dict(registered) if registered else {}

    def all(self):
        return [
            {"name": name, "enabled": enabled, "status": "enabled" if enabled else "disabled"}
            for name, enabled in self._registered.items()
        ]


class PlanExecutionControllerTestBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.controller = PlanExecutionController(self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _add_step(self, description="Do the thing", **kwargs):
        return self.plans.add_step(self.plan.plan_id, description, **kwargs)

    def _register_handler(self, capability_name, handler):
        self.controller.capability_handlers.register(capability_name, handler)


# --------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------
class TestConstruction(unittest.TestCase):
    def test_requires_a_plan_manager_instance(self):
        with self.assertRaises(TypeError):
            PlanExecutionController("not-a-plan-manager")

    def test_rejects_bad_coordinator_type(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            PlanExecutionController(plans, coordinator=object())

    def test_rejects_bad_step_controller_type(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            PlanExecutionController(plans, step_controller=object())

    def test_rejects_non_positive_max_steps_per_run(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(ValueError):
            PlanExecutionController(plans, max_steps_per_run=0)
        with self.assertRaises(ValueError):
            PlanExecutionController(plans, max_steps_per_run=-1)
        with self.assertRaises(ValueError):
            PlanExecutionController(plans, max_steps_per_run="5")

    def test_default_collaborators_created_when_omitted(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.assertIsInstance(controller.capability_handlers, CapabilityHandlerRegistry)
        self.assertIsInstance(controller.executable_capabilities, ExecutableCapabilityRegistry)
        self.assertIsInstance(controller.history, ExecutionHistory)
        self.assertIsInstance(controller.event_log, ExecutionEventLog)
        self.assertEqual(controller.max_steps_per_run, DEFAULT_MAX_STEPS_PER_RUN)

    def test_existing_step_controller_is_reused_unchanged(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        step_controller = StepExecutionController(plans)
        controller = PlanExecutionController(plans, step_controller=step_controller)
        self.assertIs(controller._step_controller, step_controller)
        self.assertIs(controller.history, step_controller.history)
        self.assertIs(controller.event_log, step_controller.event_log)
        self.assertIs(controller.capability_handlers, step_controller.capability_handlers)

    def test_existing_coordinator_is_reused_unchanged(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        coordinator = PlanExecutionCoordinator(plans)
        controller = PlanExecutionController(plans, coordinator=coordinator)
        self.assertIs(controller._coordinator, coordinator)

    def test_step_controller_property_exposes_the_shared_instance(self):
        """Public, read-only access (added alongside agent/agent_loop.py's
        Prompt 310 single-step connection) - the exact same
        StepExecutionController execute_plan itself already calls
        execute_step on, never a second, disagreeing one."""
        goals = GoalManager()
        plans = PlanManager(goals)
        step_controller = StepExecutionController(plans)
        controller = PlanExecutionController(plans, step_controller=step_controller)
        self.assertIs(controller.step_controller, step_controller)
        self.assertIs(controller.step_controller, controller._step_controller)

    def test_shared_registries_used_by_step_controller_and_coordinator(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.assertIs(controller._coordinator.capability_handlers, controller.capability_handlers)
        self.assertIs(
            controller._coordinator.executable_capabilities, controller.executable_capabilities,
        )

    def test_public_coordinator_property_exposes_the_same_instance(self):
        """Prompt 309: AgentLoop reads `get_next_ready_step` through
        this public property - it must be the exact same coordinator
        `execute_plan` itself already calls into, never a second,
        disagreeing one."""
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.assertIs(controller.coordinator, controller._coordinator)
        self.assertIsInstance(controller.coordinator, PlanExecutionCoordinator)

    def test_public_coordinator_property_reflects_an_explicit_coordinator(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        coordinator = PlanExecutionCoordinator(plans)
        controller = PlanExecutionController(plans, coordinator=coordinator)
        self.assertIs(controller.coordinator, coordinator)


# --------------------------------------------------------------------
# Empty plan
# --------------------------------------------------------------------
class TestEmptyPlan(PlanExecutionControllerTestBase):
    def test_empty_plan_is_trivially_completed(self):
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_COMPLETED)
        self.assertEqual(result["executed_steps"], [])
        self.assertEqual(result["completed_steps"], [])
        self.assertEqual(result["failed_steps"], [])
        self.assertEqual(result["blocked_steps"], [])
        self.assertEqual(result["skipped_steps"], [])
        self.assertEqual(result["execution_ids"], [])
        self.assertEqual(result["outputs"], {})
        self.assertIsNone(result["error"])


# --------------------------------------------------------------------
# Missing plan
# --------------------------------------------------------------------
class TestMissingPlan(PlanExecutionControllerTestBase):
    def test_missing_plan_reports_structured_failure(self):
        result = self.controller.execute_plan("no-such-plan")
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_FAILED)
        self.assertEqual(result["executed_steps"], [])
        self.assertIn("no-such-plan", result["error"])

    def test_missing_plan_never_executes_anything(self):
        self.controller.execute_plan("no-such-plan")
        self.assertEqual(len(self.controller.history), 0)
        self.assertEqual(len(self.controller.event_log), 0)


# --------------------------------------------------------------------
# One-step plan
# --------------------------------------------------------------------
class TestOneStepPlan(PlanExecutionControllerTestBase):
    def test_single_step_completes_the_plan(self):
        self._add_step("Only step")
        result = self.controller.execute_plan(self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_COMPLETED)
        self.assertEqual(len(result["executed_steps"]), 1)
        self.assertEqual(result["completed_steps"], result["executed_steps"])
        self.assertEqual(result["failed_steps"], [])
        self.assertEqual(len(result["execution_ids"]), 1)
        self.assertIsNotNone(result["execution_ids"][0])


# --------------------------------------------------------------------
# Multi-step sequential plan / dependency ordering / execution order
# --------------------------------------------------------------------
class TestMultiStepSequentialPlan(PlanExecutionControllerTestBase):
    def test_dependent_steps_run_in_dependency_order(self):
        step1 = self._add_step("First")
        step2 = self._add_step("Second", dependencies=[step1.step_id])
        step3 = self._add_step("Third", dependencies=[step2.step_id])

        result = self.controller.execute_plan(self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_COMPLETED)
        self.assertEqual(
            result["executed_steps"], [step1.step_id, step2.step_id, step3.step_id],
        )
        self.assertEqual(result["completed_steps"], result["executed_steps"])
        self.assertEqual(step1.status, STATUS_COMPLETED)
        self.assertEqual(step2.status, STATUS_COMPLETED)
        self.assertEqual(step3.status, STATUS_COMPLETED)

    def test_dependent_step_is_not_ready_until_dependency_completes(self):
        step1 = self._add_step("First")
        step2 = self._add_step("Second", dependencies=[step1.step_id])
        self.plans.refresh_plan_step_statuses(self.plan.plan_id)
        self.assertEqual(step2.status, STATUS_BLOCKED)

        self.controller.execute_plan(self.plan.plan_id)

        self.assertEqual(step1.status, STATUS_COMPLETED)
        self.assertEqual(step2.status, STATUS_COMPLETED)


# --------------------------------------------------------------------
# Multiple independent steps
# --------------------------------------------------------------------
class TestMultipleIndependentSteps(PlanExecutionControllerTestBase):
    def test_all_independent_steps_execute(self):
        a = self._add_step("A")
        b = self._add_step("B")
        c = self._add_step("C")

        result = self.controller.execute_plan(self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_COMPLETED)
        self.assertEqual(set(result["executed_steps"]), {a.step_id, b.step_id, c.step_id})
        self.assertEqual(len(result["executed_steps"]), 3)


# --------------------------------------------------------------------
# Blocked step (never executed)
# --------------------------------------------------------------------
class TestBlockedStep(PlanExecutionControllerTestBase):
    def test_step_blocked_on_missing_dependency_is_never_executed(self):
        self._add_step("Needs a dependency", dependencies=["missing-dep"])

        result = self.controller.execute_plan(self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_BLOCKED)
        self.assertEqual(result["executed_steps"], [])
        self.assertEqual(result["completed_steps"], [])
        self.assertEqual(len(result["blocked_steps"]), 1)
        self.assertEqual(len(self.controller.history), 0)


# --------------------------------------------------------------------
# Failed step
# --------------------------------------------------------------------
class TestFailedStep(PlanExecutionControllerTestBase):
    def test_failing_step_stops_plan_execution(self):
        step1 = self._add_step("Will fail", required_capabilities=["boom"])
        step2 = self._add_step("Never reached", dependencies=[step1.step_id])

        def failing_handler(step):
            raise RuntimeError("kaboom")

        self._register_handler("boom", failing_handler)

        result = self.controller.execute_plan(self.plan.plan_id)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_FAILED)
        self.assertEqual(result["executed_steps"], [step1.step_id])
        self.assertEqual(result["failed_steps"], [step1.step_id])
        self.assertEqual(result["completed_steps"], [])
        self.assertIsNotNone(result["error"])
        self.assertEqual(step1.status, STATUS_FAILED)
        # step2 was never touched/refreshed/executed.
        self.assertNotIn(step2.step_id, result["executed_steps"])

    def test_failure_does_not_refresh_dependent_steps(self):
        step1 = self._add_step("Will fail", required_capabilities=["boom"])
        step2 = self._add_step("Depends on failure", dependencies=[step1.step_id])
        self.plans.refresh_plan_step_statuses(self.plan.plan_id)
        status_before = step2.status

        def failing_handler(step):
            raise RuntimeError("kaboom")

        self._register_handler("boom", failing_handler)
        self.controller.execute_plan(self.plan.plan_id)

        # Still blocked - never promoted, since refresh_after_step_change
        # is only ever called on a *successful* step.
        self.assertEqual(step2.status, status_before)


# --------------------------------------------------------------------
# Unavailable capability
# --------------------------------------------------------------------
class TestUnavailableCapability(PlanExecutionControllerTestBase):
    def test_unavailable_capability_blocks_the_plan_without_executing(self):
        self._add_step("Needs draw_image", required_capabilities=["draw_image"])
        self._register_handler("draw_image", lambda step: "ignored")
        fake_caps = FakeCapabilitySystem({"draw_image": False})

        result = self.controller.execute_plan(self.plan.plan_id, capability_system=fake_caps)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_BLOCKED)
        self.assertEqual(result["executed_steps"], [])
        self.assertEqual(len(self.controller.history), 0)


# --------------------------------------------------------------------
# Missing handler
# --------------------------------------------------------------------
class TestMissingHandler(PlanExecutionControllerTestBase):
    def test_missing_handler_blocks_the_plan_without_executing(self):
        self._add_step("Needs draw_image", required_capabilities=["draw_image"])
        # No handler registered at all.

        result = self.controller.execute_plan(self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_BLOCKED)
        self.assertEqual(result["executed_steps"], [])
        self.assertEqual(len(self.controller.history), 0)


# --------------------------------------------------------------------
# Plan completion / failure / blocked state (whole-plan status)
# --------------------------------------------------------------------
class TestPlanCompletion(PlanExecutionControllerTestBase):
    def test_all_steps_completed_reports_plan_completed(self):
        self._add_step("Only step")
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(result["status"], PLAN_RUN_COMPLETED)


class TestPlanFailure(PlanExecutionControllerTestBase):
    def test_any_failed_step_reports_plan_failed(self):
        self._add_step("Will fail", required_capabilities=["boom"])
        self._register_handler("boom", lambda step: (_ for _ in ()).throw(RuntimeError("x")))
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(result["status"], PLAN_RUN_FAILED)


class TestPlanBlocked(PlanExecutionControllerTestBase):
    def test_permanently_blocked_plan_reports_plan_blocked(self):
        self._add_step("Stuck", dependencies=["nowhere"])
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(result["status"], PLAN_RUN_BLOCKED)

    def test_dependency_on_a_failed_step_leaves_plan_blocked_after_stop(self):
        # A separate, independent failing branch and a step depending
        # on it: after the run stops on the failure, the plan-level
        # status is FAILED (any failed step wins) - this test instead
        # exercises the case where an *unrelated* branch is stuck on
        # a capability that will never become available, with nothing
        # failed.
        self._add_step("Stuck forever", required_capabilities=["never_registered"])
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(result["status"], PLAN_RUN_BLOCKED)
        self.assertTrue(result["success"])


# --------------------------------------------------------------------
# Cycle detection
# --------------------------------------------------------------------
class TestCycleDetection(PlanExecutionControllerTestBase):
    def test_direct_two_step_cycle_is_detected(self):
        step_a = self._add_step("A")
        step_b = self._add_step("B", dependencies=[step_a.step_id])
        # Introduce a cycle: A now depends on B too.
        step_a.dependencies.append(step_b.step_id)

        result = self.controller.execute_plan(self.plan.plan_id)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_BLOCKED)
        self.assertIn("cycle", result["error"].lower())
        self.assertEqual(result["executed_steps"], [])
        self.assertEqual(len(self.controller.history), 0)

    def test_self_dependency_cycle_is_detected(self):
        step = self._add_step("Self-referential")
        step.dependencies.append(step.step_id)

        result = self.controller.execute_plan(self.plan.plan_id)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_BLOCKED)
        self.assertEqual(result["executed_steps"], [])

    def test_three_step_cycle_is_detected_and_does_not_hang(self):
        step_a = self._add_step("A")
        step_b = self._add_step("B", dependencies=[step_a.step_id])
        step_c = self._add_step("C", dependencies=[step_b.step_id])
        step_a.dependencies.append(step_c.step_id)

        result = self.controller.execute_plan(self.plan.plan_id)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_BLOCKED)
        self.assertEqual(result["executed_steps"], [])

    def test_acyclic_plan_with_diamond_dependencies_is_not_flagged(self):
        top = self._add_step("Top")
        left = self._add_step("Left", dependencies=[top.step_id])
        right = self._add_step("Right", dependencies=[top.step_id])
        bottom = self._add_step("Bottom", dependencies=[left.step_id, right.step_id])

        result = self.controller.execute_plan(self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_COMPLETED)
        self.assertEqual(result["executed_steps"][0], top.step_id)
        self.assertEqual(result["executed_steps"][-1], bottom.step_id)


# --------------------------------------------------------------------
# max_steps_per_run
# --------------------------------------------------------------------
class TestMaxStepsPerRun(PlanExecutionControllerTestBase):
    def test_limit_stops_execution_and_returns_waiting_with_warning(self):
        steps = [self._add_step(f"Step {i}") for i in range(5)]

        result = self.controller.execute_plan(self.plan.plan_id, max_steps_per_run=2)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], PLAN_RUN_WAITING)
        self.assertEqual(len(result["executed_steps"]), 2)
        self.assertTrue(any("max_steps_per_run" in w for w in result["warnings"]))
        # The remaining, still-executable steps are reported as skipped.
        self.assertEqual(len(result["skipped_steps"]), 3)

    def test_default_limit_is_conservative_and_finite(self):
        self.assertIsInstance(DEFAULT_MAX_STEPS_PER_RUN, int)
        self.assertGreater(DEFAULT_MAX_STEPS_PER_RUN, 0)
        self.assertLess(DEFAULT_MAX_STEPS_PER_RUN, 1000)

    def test_per_call_override_takes_precedence_over_instance_default(self):
        controller = PlanExecutionController(self.plans, max_steps_per_run=10)
        for i in range(5):
            self._add_step(f"Step {i}")
        result = controller.execute_plan(self.plan.plan_id, max_steps_per_run=1)
        self.assertEqual(len(result["executed_steps"]), 1)
        self.assertEqual(result["status"], PLAN_RUN_WAITING)

    def test_execute_plan_rejects_non_positive_override(self):
        self._add_step("Only step")
        with self.assertRaises(ValueError):
            self.controller.execute_plan(self.plan.plan_id, max_steps_per_run=0)


# --------------------------------------------------------------------
# Output propagation
# --------------------------------------------------------------------
class TestOutputPropagation(PlanExecutionControllerTestBase):
    def test_step_output_is_preserved_in_outputs_dict(self):
        step = self._add_step("Produces output", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda ctx: {"value": 42})

        result = self.controller.execute_plan(self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertIn(step.step_id, result["outputs"])


# --------------------------------------------------------------------
# ExecutionHistory / ExecutionEventLog integration
# --------------------------------------------------------------------
class TestExecutionHistoryIntegration(PlanExecutionControllerTestBase):
    def test_each_executed_step_is_recorded_in_history(self):
        self._add_step("A")
        self._add_step("B")
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(len(self.controller.history), len(result["executed_steps"]))
        for execution_id in result["execution_ids"]:
            self.assertIsNotNone(self.controller.history.get(execution_id))


class TestExecutionEventLogIntegration(PlanExecutionControllerTestBase):
    def test_events_are_recorded_for_each_executed_step(self):
        self._add_step("A")
        result = self.controller.execute_plan(self.plan.plan_id)
        events = self.controller.event_log.list_for_plan(self.plan.plan_id)
        self.assertGreater(len(events), 0)


# --------------------------------------------------------------------
# No duplicate execution / no execution of blocked steps
# --------------------------------------------------------------------
class TestNoDuplicateExecution(PlanExecutionControllerTestBase):
    def test_each_step_executes_at_most_once_per_call(self):
        step = self._add_step("Only step")
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(result["executed_steps"].count(step.step_id), 1)

    def test_second_call_does_not_re_execute_completed_steps(self):
        self._add_step("Only step")
        first = self.controller.execute_plan(self.plan.plan_id)
        second = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(second["executed_steps"], [])
        self.assertEqual(second["status"], PLAN_RUN_COMPLETED)
        self.assertEqual(len(self.controller.history), len(first["executed_steps"]))


class TestNoExecutionOfBlockedFailedCancelledCompletedSteps(PlanExecutionControllerTestBase):
    def test_blocked_step_never_appears_in_executed_steps(self):
        self._add_step("Stuck", dependencies=["missing"])
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(result["executed_steps"], [])

    def test_already_failed_step_is_never_re_executed(self):
        step = self._add_step("Pre-failed")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(result["executed_steps"], [])
        self.assertEqual(result["status"], PLAN_RUN_FAILED)

    def test_already_completed_step_is_never_re_executed(self):
        step = self._add_step("Pre-completed")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(result["executed_steps"], [])
        self.assertEqual(result["status"], PLAN_RUN_COMPLETED)


# --------------------------------------------------------------------
# No automatic retry
# --------------------------------------------------------------------
class TestNoAutomaticRetry(PlanExecutionControllerTestBase):
    def test_failed_step_is_not_retried_within_the_same_call(self):
        self._add_step("Will fail", required_capabilities=["boom"])
        self._register_handler("boom", lambda step: (_ for _ in ()).throw(RuntimeError("x")))
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(result["executed_steps"].count(result["failed_steps"][0]), 1)

    def test_engine_retry_step_remains_available_and_unaffected(self):
        step = self._add_step("Will fail", required_capabilities=["boom"])
        attempts = {"count": 0}

        def sometimes_fails(ctx):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("first try fails")
            return "ok"

        self._register_handler("boom", sometimes_fails)
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(result["status"], PLAN_RUN_FAILED)
        self.assertEqual(step.status, STATUS_FAILED)

        # PlanExecutionController never retries; the engine's own
        # retry_step remains the explicit, separate way to retry, and
        # is entirely unaffected by this controller existing.
        engine = self.controller._step_controller._engine
        retry_result = engine.retry_step(self.plan.plan_id, step.step_id, sometimes_fails)
        self.assertEqual(retry_result.status, STATUS_COMPLETED)
        self.assertEqual(step.status, STATUS_COMPLETED)


# --------------------------------------------------------------------
# No arbitrary code execution
# --------------------------------------------------------------------
class TestNoArbitraryCodeExecution(PlanExecutionControllerTestBase):
    def test_string_input_data_is_never_evaluated_as_code(self):
        step = self._add_step(
            "Has suspicious-looking input",
            required_capabilities=["echo"],
            input_data={"payload": "os.system('echo hacked')"},
        )
        seen = {}

        def echo_handler(ctx):
            seen["input"] = ctx.input_data if hasattr(ctx, "input_data") else None
            return "handled"

        self._register_handler("echo", echo_handler)
        result = self.controller.execute_plan(self.plan.plan_id)
        self.assertEqual(result["status"], PLAN_RUN_COMPLETED)
        # The string was handed through as plain data, never executed.
        self.assertEqual(step.input_data, {"payload": "os.system('echo hacked')"})

    def test_controller_module_uses_no_dangerous_builtins(self):
        import inspect
        from execution import plan_execution_controller as mod

        source = inspect.getsource(mod)
        for forbidden in ("eval(", "exec(", "subprocess", "os.system", "__import__"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
