"""
Tests for StepExecutionController (execution/step_execution_controller.py)
- a small, explicit orchestration layer that runs exactly one named
plan step by gating through the existing StepExecutionPreparation
checkpoint and, only if that passes, delegating the actual run to the
existing ExecutionEngine.execute_capability_step - never duplicating
any of the preflight, readiness, execution, history, or event-logging
logic those two already implement.

Covers: successful execution of a step with no required capabilities,
missing plan, missing step, a blocked step, an unavailable (disabled)
capability, a missing handler, a preparation failure in general,
successful capability execution, failed capability execution, output
storage, ExecutionResult/ExecutionHistory/ExecutionEventLog
integration, correct final step status on both success and failure,
dependent step status refresh, that no automatic next-step or
whole-plan execution ever happens, protection against re-executing an
already-COMPLETED step, and backward compatibility with the existing
ExecutionEngine (execute_step/execute_capability_step/retry_step all
keep working unchanged alongside this controller).

Run directly:
    python -m unittest tests.test_step_execution_controller -v
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

from execution.step_execution_controller import StepExecutionController
from execution.step_execution_preparation import (
    StepExecutionPreparation, CHECK_HANDLERS_REGISTERED,
)
from execution.preflight import (
    CHECK_PLAN_EXISTS, CHECK_STEP_EXISTS, CHECK_STEP_READY,
    CHECK_DEPENDENCIES_SATISFIED, CHECK_CAPABILITIES_AVAILABLE,
)
from execution.execution_engine import ExecutionEngine
from execution.execution_history import ExecutionHistory
from execution.execution_event_log import ExecutionEventLog
from execution.execution_event import (
    EVENT_PREPARATION_STARTED, EVENT_PREPARATION_COMPLETED,
    EVENT_PREPARATION_FAILED, EVENT_EXECUTION_CREATED, EVENT_EXECUTION_STARTED,
    EVENT_CAPABILITY_STARTED, EVENT_CAPABILITY_COMPLETED, EVENT_CAPABILITY_FAILED,
    EVENT_OUTPUT_CREATED, EVENT_EXECUTION_COMPLETED, EVENT_EXECUTION_FAILED,
)
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.executable_registry import ExecutableCapabilityRegistry


class FakeCapabilitySystem:
    """Minimal stand-in for capabilities.capability_system.CapabilitySystem
    - same convention already used by tests/test_preflight.py and
    tests/test_step_execution_preparation.py's own FakeCapabilitySystem."""

    def __init__(self, registered=None):
        self._registered = dict(registered) if registered else {}

    def all(self):
        return [
            {"name": name, "enabled": enabled, "status": "enabled" if enabled else "disabled"}
            for name, enabled in self._registered.items()
        ]


class StepExecutionControllerTestBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.controller = StepExecutionController(self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _ready_step(self, description="Do the thing", **kwargs):
        step = self.plans.add_step(self.plan.plan_id, description, **kwargs)
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        return step

    def _register_handler(self, capability_name, handler):
        self.controller.capability_handlers.register(capability_name, handler)


# --------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------
class TestConstruction(unittest.TestCase):
    def test_requires_a_plan_manager_instance(self):
        with self.assertRaises(TypeError):
            StepExecutionController("not-a-plan-manager")

    def test_rejects_bad_execution_engine_type(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            StepExecutionController(plans, execution_engine=object())

    def test_rejects_bad_preparation_type(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            StepExecutionController(plans, preparation=object())

    def test_default_collaborators_are_created_when_omitted(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = StepExecutionController(plans)
        self.assertIsInstance(controller.capability_handlers, CapabilityHandlerRegistry)
        self.assertIsInstance(controller.executable_capabilities, ExecutableCapabilityRegistry)
        self.assertIsInstance(controller.history, ExecutionHistory)
        self.assertIsInstance(controller.event_log, ExecutionEventLog)

    def test_existing_execution_engine_is_reused_unchanged(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        controller = StepExecutionController(plans, execution_engine=engine)
        self.assertIs(controller._engine, engine)
        self.assertIs(controller.history, engine.history)
        self.assertIs(controller.event_log, engine.event_log)
        self.assertIs(controller.capability_handlers, engine.capability_handlers)

    def test_explicit_shared_collaborators_are_wired_onto_existing_engine(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        shared_history = ExecutionHistory()
        shared_log = ExecutionEventLog()
        shared_handlers = CapabilityHandlerRegistry()
        controller = StepExecutionController(
            plans, execution_engine=engine, history=shared_history,
            event_log=shared_log, capability_handlers=shared_handlers,
        )
        self.assertIs(engine.history, shared_history)
        self.assertIs(engine.event_log, shared_log)
        self.assertIs(engine.capability_handlers, shared_handlers)
        self.assertIs(controller.history, shared_history)

    def test_existing_preparation_is_reused_unchanged(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        prep = StepExecutionPreparation(plans)
        controller = StepExecutionController(plans, preparation=prep)
        self.assertIs(controller._preparation, prep)


# --------------------------------------------------------------------
# Successful execution (no required capabilities)
# --------------------------------------------------------------------
class TestSuccessfulStepExecution(StepExecutionControllerTestBase):
    def test_successful_step_execution_completes_and_reports_success(self):
        step = self._ready_step()
        result = self.controller.execute_step(self.plan.plan_id, step.step_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["plan_id"], self.plan.plan_id)
        self.assertEqual(result["step_id"], step.step_id)
        self.assertIsNotNone(result["execution_id"])
        self.assertEqual(result["step_status"], STATUS_COMPLETED)
        self.assertIsNone(result["error"])
        self.assertEqual(step.status, STATUS_COMPLETED)

    def test_execution_context_is_built_and_returned(self):
        step = self._ready_step()
        result = self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertIsInstance(result["context"], dict)
        self.assertEqual(result["context"]["plan_id"], self.plan.plan_id)
        self.assertEqual(result["context"]["step_id"], step.step_id)


# --------------------------------------------------------------------
# Missing plan / missing step
# --------------------------------------------------------------------
class TestMissingPlanOrStep(StepExecutionControllerTestBase):
    def test_missing_plan(self):
        result = self.controller.execute_step("no-such-plan", "no-such-step")
        self.assertFalse(result["success"])
        self.assertIsNone(result["execution_id"])
        self.assertIsNone(result["step_status"])
        self.assertIn(CHECK_PLAN_EXISTS, result["error"])
        self.assertIsNone(result["context"])

    def test_missing_step(self):
        result = self.controller.execute_step(self.plan.plan_id, "no-such-step")
        self.assertFalse(result["success"])
        self.assertIsNone(result["execution_id"])
        self.assertIsNone(result["step_status"])
        self.assertIn(CHECK_STEP_EXISTS, result["error"])

    def test_missing_plan_never_creates_an_execution_result(self):
        result = self.controller.execute_step("no-such-plan", "no-such-step")
        self.assertEqual(len(self.controller.history), 0)
        self.assertIsNone(result["execution_id"])


# --------------------------------------------------------------------
# Blocked step
# --------------------------------------------------------------------
class TestBlockedStep(StepExecutionControllerTestBase):
    def test_blocked_step_is_not_executed(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Needs a dependency", dependencies=["missing-dep"],
        )
        self.plans.refresh_step_status(self.plan.plan_id, step.step_id)
        self.assertEqual(step.status, STATUS_BLOCKED)

        result = self.controller.execute_step(self.plan.plan_id, step.step_id)

        self.assertFalse(result["success"])
        self.assertIsNone(result["execution_id"])
        self.assertEqual(result["step_status"], STATUS_BLOCKED)
        self.assertEqual(step.status, STATUS_BLOCKED)
        self.assertIn(CHECK_STEP_READY, result["error"])


# --------------------------------------------------------------------
# Unavailable capability / missing handler
# --------------------------------------------------------------------
class TestUnavailableCapability(StepExecutionControllerTestBase):
    def test_unavailable_capability_blocks_execution(self):
        step = self._ready_step(required_capabilities=["draw_image"])
        self._register_handler("draw_image", lambda s: "ignored")
        fake_caps = FakeCapabilitySystem({"draw_image": False})

        result = self.controller.execute_step(
            self.plan.plan_id, step.step_id, capability_system=fake_caps,
        )

        self.assertFalse(result["success"])
        self.assertIn(CHECK_CAPABILITIES_AVAILABLE, result["error"])
        self.assertEqual(step.status, STATUS_READY)


class TestMissingHandler(StepExecutionControllerTestBase):
    def test_missing_handler_blocks_execution(self):
        step = self._ready_step(required_capabilities=["draw_image"])
        # No handler registered at all.
        result = self.controller.execute_step(self.plan.plan_id, step.step_id)

        self.assertFalse(result["success"])
        self.assertIn(CHECK_HANDLERS_REGISTERED, result["error"])
        self.assertEqual(step.status, STATUS_READY)
        self.assertIsNone(result["execution_id"])


# --------------------------------------------------------------------
# Preparation failure - general contract (requirement 4)
# --------------------------------------------------------------------
class TestPreparationFailureContract(StepExecutionControllerTestBase):
    def test_preparation_failure_records_preparation_failed_event(self):
        step = self.plans.add_step(self.plan.plan_id, "Blocked step")
        # PENDING, never marked READY -> preflight's step_ready check fails.

        result = self.controller.execute_step(self.plan.plan_id, step.step_id)

        self.assertFalse(result["success"])
        self.assertIn(EVENT_PREPARATION_FAILED, result["events_recorded"])
        matching = [
            e for e in self.controller.event_log.list_for_step(self.plan.plan_id, step.step_id)
            if e.event_type == EVENT_PREPARATION_FAILED
        ]
        self.assertEqual(len(matching), 1)

    def test_preparation_failure_never_calls_a_handler(self):
        step = self._ready_step(required_capabilities=["draw_image"])
        called = []

        def handler(plan_step):
            called.append(True)
            return "should never run"

        self._register_handler("draw_image", handler)
        fake_caps = FakeCapabilitySystem({"draw_image": False})

        self.controller.execute_step(
            self.plan.plan_id, step.step_id, capability_system=fake_caps,
        )
        self.assertEqual(called, [])

    def test_preparation_failure_never_marks_step_completed(self):
        step = self.plans.add_step(self.plan.plan_id, "Blocked step")
        self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertNotEqual(step.status, STATUS_COMPLETED)


# --------------------------------------------------------------------
# Successful / failed capability execution
# --------------------------------------------------------------------
class TestSuccessfulCapabilityExecution(StepExecutionControllerTestBase):
    def test_successful_capability_execution(self):
        step = self._ready_step(required_capabilities=["draw_image"])

        def handler(plan_step):
            return {"image": "a-nice-drawing"}

        self._register_handler("draw_image", handler)

        result = self.controller.execute_step(self.plan.plan_id, step.step_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["output"], {"draw_image": {"image": "a-nice-drawing"}})
        self.assertEqual(step.status, STATUS_COMPLETED)


class TestFailedCapabilityExecution(StepExecutionControllerTestBase):
    def test_failed_capability_execution(self):
        step = self._ready_step(required_capabilities=["draw_image"])

        def handler(plan_step):
            raise ValueError("could not draw")

        self._register_handler("draw_image", handler)

        result = self.controller.execute_step(self.plan.plan_id, step.step_id)

        self.assertFalse(result["success"])
        self.assertIsNotNone(result["execution_id"])
        self.assertIn("ValueError", result["error"])
        self.assertIn("could not draw", result["error"])
        self.assertEqual(step.status, STATUS_FAILED)
        self.assertEqual(result["step_status"], STATUS_FAILED)


# --------------------------------------------------------------------
# Output storage
# --------------------------------------------------------------------
class TestOutputStorage(StepExecutionControllerTestBase):
    def test_successful_output_is_synced_onto_the_step(self):
        step = self._ready_step(required_capabilities=["summarize"])

        def handler(plan_step):
            return "a short summary"

        self._register_handler("summarize", handler)

        result = self.controller.execute_step(self.plan.plan_id, step.step_id)

        self.assertEqual(step.output_data, {"summarize": "a short summary"})
        self.assertEqual(result["output"], {"summarize": "a short summary"})

    def test_failed_execution_never_touches_output_data(self):
        step = self._ready_step(required_capabilities=["summarize"])

        def handler(plan_step):
            raise RuntimeError("nope")

        self._register_handler("summarize", handler)

        self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertIsNone(step.output_data)


# --------------------------------------------------------------------
# ExecutionResult / ExecutionHistory / ExecutionEventLog integration
# --------------------------------------------------------------------
class TestExecutionResultIntegration(StepExecutionControllerTestBase):
    def test_returned_execution_id_matches_a_real_execution_result(self):
        step = self._ready_step()
        result = self.controller.execute_step(self.plan.plan_id, step.step_id)

        stored = self.controller.history.get(result["execution_id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, "completed")
        self.assertEqual(stored.plan_id, self.plan.plan_id)
        self.assertEqual(stored.step_id, step.step_id)


class TestExecutionHistoryIntegration(StepExecutionControllerTestBase):
    def test_every_run_is_recorded_into_history(self):
        step = self._ready_step()
        self.assertEqual(len(self.controller.history), 0)
        self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertEqual(len(self.controller.history), 1)

    def test_preparation_failure_records_nothing_into_history(self):
        step = self.plans.add_step(self.plan.plan_id, "Not ready")
        self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertEqual(len(self.controller.history), 0)

    def test_shared_history_is_honored(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        shared_history = ExecutionHistory()
        controller = StepExecutionController(plans, history=shared_history)
        goal = goals.create_goal("Do a thing")
        plan = plans.create_plan(goal.goal_id)
        step = plans.add_step(plan.plan_id, "Step one")
        plans.update_step_status(plan.plan_id, step.step_id, STATUS_READY)

        controller.execute_step(plan.plan_id, step.step_id)
        self.assertEqual(len(shared_history), 1)


class TestExecutionEventLogIntegration(StepExecutionControllerTestBase):
    def test_successful_run_records_full_lifecycle_events(self):
        step = self._ready_step(required_capabilities=["draw_image"])
        self._register_handler("draw_image", lambda s: "ok")

        result = self.controller.execute_step(self.plan.plan_id, step.step_id)

        for event_type in (
            EVENT_PREPARATION_STARTED, EVENT_PREPARATION_COMPLETED,
            EVENT_EXECUTION_CREATED, EVENT_EXECUTION_STARTED,
            EVENT_CAPABILITY_STARTED, EVENT_CAPABILITY_COMPLETED,
            EVENT_OUTPUT_CREATED, EVENT_EXECUTION_COMPLETED,
        ):
            self.assertIn(event_type, result["events_recorded"])

    def test_failed_run_records_failure_events(self):
        step = self._ready_step(required_capabilities=["draw_image"])

        def handler(plan_step):
            raise ValueError("boom")

        self._register_handler("draw_image", handler)

        result = self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertIn(EVENT_CAPABILITY_FAILED, result["events_recorded"])
        self.assertIn(EVENT_EXECUTION_FAILED, result["events_recorded"])

    def test_shared_event_log_is_honored(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        shared_log = ExecutionEventLog()
        controller = StepExecutionController(plans, event_log=shared_log)
        goal = goals.create_goal("Do a thing")
        plan = plans.create_plan(goal.goal_id)
        step = plans.add_step(plan.plan_id, "Step one")
        plans.update_step_status(plan.plan_id, step.step_id, STATUS_READY)

        controller.execute_step(plan.plan_id, step.step_id)
        self.assertGreater(len(shared_log), 0)


# --------------------------------------------------------------------
# Final step status
# --------------------------------------------------------------------
class TestFinalStepStatus(StepExecutionControllerTestBase):
    def test_success_leaves_step_completed(self):
        step = self._ready_step()
        self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertEqual(step.status, STATUS_COMPLETED)

    def test_failure_leaves_step_failed(self):
        step = self._ready_step(required_capabilities=["draw_image"])
        self._register_handler("draw_image", lambda s: 1 / 0)
        self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertEqual(step.status, STATUS_FAILED)

    def test_step_is_never_left_in_progress(self):
        step = self._ready_step()
        self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertNotIn(step.status, ("in_progress",))


# --------------------------------------------------------------------
# Dependent step status refresh
# --------------------------------------------------------------------
class TestDependentStepRefresh(StepExecutionControllerTestBase):
    def test_dependent_becomes_ready_after_success(self):
        upstream = self._ready_step("Upstream")
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id],
        )
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id)
        self.assertEqual(downstream.status, STATUS_BLOCKED)

        self.controller.execute_step(self.plan.plan_id, upstream.step_id)

        self.assertEqual(downstream.status, STATUS_READY)

    def test_dependent_stays_blocked_after_failure(self):
        upstream = self._ready_step("Upstream", required_capabilities=["draw_image"])
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id],
        )
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id)

        self._register_handler("draw_image", lambda s: 1 / 0)
        self.controller.execute_step(self.plan.plan_id, upstream.step_id)

        self.assertEqual(downstream.status, STATUS_BLOCKED)


# --------------------------------------------------------------------
# No automatic next-step / whole-plan execution
# --------------------------------------------------------------------
class TestNoAutomaticExecution(StepExecutionControllerTestBase):
    def test_only_the_requested_step_is_touched(self):
        first = self._ready_step("First")
        second = self._ready_step("Second")

        self.controller.execute_step(self.plan.plan_id, first.step_id)

        self.assertEqual(first.status, STATUS_COMPLETED)
        # The second READY step is never automatically run by this call.
        self.assertEqual(second.status, STATUS_READY)

    def test_newly_ready_dependent_is_not_automatically_executed(self):
        upstream = self._ready_step("Upstream")
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id],
        )
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id)

        self.controller.execute_step(self.plan.plan_id, upstream.step_id)

        # Downstream became READY (refreshed), but was never executed.
        self.assertEqual(downstream.status, STATUS_READY)
        self.assertIsNone(downstream.output_data)


# --------------------------------------------------------------------
# Completed-step protection
# --------------------------------------------------------------------
class TestCompletedStepProtection(StepExecutionControllerTestBase):
    def test_completed_step_is_never_re_executed(self):
        step = self._ready_step()
        calls = []

        first_result = self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertTrue(first_result["success"])
        self.assertEqual(step.status, STATUS_COMPLETED)

        second_result = self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertFalse(second_result["success"])
        self.assertIn(CHECK_STEP_READY, second_result["error"])
        # Still COMPLETED - never rewritten by the refused second call.
        self.assertEqual(step.status, STATUS_COMPLETED)

    def test_completed_step_with_capability_handler_is_never_re_called(self):
        step = self._ready_step(required_capabilities=["draw_image"])
        calls = []

        def handler(plan_step):
            calls.append(1)
            return "ok"

        self._register_handler("draw_image", handler)

        self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertEqual(len(calls), 1)

        self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertEqual(len(calls), 1)


# --------------------------------------------------------------------
# Backward compatibility with the existing ExecutionEngine
# --------------------------------------------------------------------
class TestBackwardCompatibility(StepExecutionControllerTestBase):
    def test_engine_execute_step_with_explicit_handler_still_works(self):
        step = self._ready_step()

        def handler(plan_step):
            return "handled directly"

        result = self.controller._engine.execute_step(
            self.plan.plan_id, step.step_id, handler,
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, "handled directly")

    def test_engine_retry_step_still_works_after_a_controller_failure(self):
        step = self._ready_step(required_capabilities=["draw_image"])

        attempts = {"count": 0}

        def handler(plan_step):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise ValueError("first attempt fails")
            return "ok on retry"

        self._register_handler("draw_image", handler)

        first = self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertFalse(first["success"])
        self.assertEqual(step.status, STATUS_FAILED)

        def direct_handler(plan_step):
            return handler(plan_step)

        retry_result = self.controller._engine.retry_step(
            self.plan.plan_id, step.step_id, direct_handler,
        )
        self.assertEqual(retry_result.status, "completed")
        self.assertEqual(step.status, STATUS_COMPLETED)

    def test_controller_and_engine_share_the_same_history_by_default(self):
        step = self._ready_step()
        self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertEqual(len(self.controller._engine.history), 1)
        self.assertIs(self.controller.history, self.controller._engine.history)

    def test_existing_execution_engine_tests_are_unaffected_by_controller_presence(self):
        # Constructing a StepExecutionController for one PlanManager must
        # never change how a completely separate ExecutionEngine, wired
        # to its own PlanManager, behaves.
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        goal = goals.create_goal("Independent goal")
        plan = plans.create_plan(goal.goal_id)
        step = plans.add_step(plan.plan_id, "Independent step")
        plans.update_step_status(plan.plan_id, step.step_id, STATUS_READY)

        result = engine.execute_step(plan.plan_id, step.step_id, lambda s: "fine")
        self.assertEqual(result.status, "completed")


# --------------------------------------------------------------------
# Prompt 311: connect a step's own COMPLETED output to its direct
# dependents' inputs via the existing DataFlowManager
# (planning/data_flow_manager.py), unchanged - reused here through
# self.context_builder.data_flow_manager, the exact same instance
# ExecutionContextBuilder already builds dependency-output contexts
# from (never a second, disagreeing DataFlowManager). Propagation only
# ever runs after a real COMPLETED status, never for a FAILED run, and
# only ever touches the source's direct dependents.
# --------------------------------------------------------------------
class TestDataFlowPropagationOnCompletion(StepExecutionControllerTestBase):
    def test_completed_step_output_reaches_direct_dependent(self):
        """1. A completed step output reaches its direct dependent step."""
        source = self._ready_step("Produces output", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda step: {"value": 42})
        dependent = self.plans.add_step(
            self.plan.plan_id, "Consumes output", dependencies=[source.step_id],
        )

        result = self.controller.execute_step(self.plan.plan_id, source.step_id)

        self.assertTrue(result["success"])
        self.assertIsNotNone(result["data_flow"])
        self.assertIn(dependent.step_id, result["data_flow"]["propagated_steps"])
        self.assertEqual(dependent.input_data, {"make_thing": {"value": 42}})

    def test_existing_target_input_is_not_overwritten(self):
        """2. Existing target input is not overwritten (existing
        conflict behavior is preserved, unchanged)."""
        source = self._ready_step("Produces output", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda step: {"value": 42})
        dependent = self.plans.add_step(
            self.plan.plan_id, "Consumes output", dependencies=[source.step_id],
        )
        self.plans.set_step_input(self.plan.plan_id, dependent.step_id, {"preset": True})

        result = self.controller.execute_step(self.plan.plan_id, source.step_id)

        self.assertTrue(result["success"])
        self.assertEqual(
            [c["step_id"] for c in result["data_flow"]["conflicts"]], [dependent.step_id],
        )
        self.assertNotIn(dependent.step_id, result["data_flow"]["propagated_steps"])
        # Untouched - the pre-existing input survives exactly as set.
        self.assertEqual(dependent.input_data, {"preset": True})

    def test_failed_step_does_not_propagate_output(self):
        """3. A failed step does not propagate output."""
        source = self._ready_step("Will fail", required_capabilities=["boom"])

        def failing_handler(step):
            raise RuntimeError("kaboom")

        self._register_handler("boom", failing_handler)
        dependent = self.plans.add_step(
            self.plan.plan_id, "Consumes output", dependencies=[source.step_id],
        )

        result = self.controller.execute_step(self.plan.plan_id, source.step_id)

        self.assertFalse(result["success"])
        self.assertIsNone(result["data_flow"])
        self.assertIsNone(dependent.input_data)

    def test_output_not_sent_to_unrelated_steps(self):
        """4. Output is not sent to unrelated steps."""
        source = self._ready_step("Produces output", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda step: {"value": 42})
        unrelated = self.plans.add_step(self.plan.plan_id, "Unrelated step")

        result = self.controller.execute_step(self.plan.plan_id, source.step_id)

        self.assertTrue(result["success"])
        self.assertNotIn(unrelated.step_id, result["data_flow"]["propagated_steps"])
        self.assertIsNone(unrelated.input_data)

    def test_dependent_step_is_not_automatically_executed(self):
        """5. Dependent steps are not automatically executed."""
        source = self._ready_step("Produces output", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda step: {"value": 42})
        dependent = self.plans.add_step(
            self.plan.plan_id, "Consumes output", dependencies=[source.step_id],
        )

        self.controller.execute_step(self.plan.plan_id, source.step_id)

        # Input was propagated, but the dependent itself was never run:
        # still not COMPLETED, and only the one, explicit execute_step
        # call above is reflected in history.
        self.assertEqual(dependent.input_data, {"make_thing": {"value": 42}})
        self.assertNotEqual(dependent.status, STATUS_COMPLETED)
        self.assertEqual(len(self.controller.history), 1)

    def test_source_with_no_dependents_propagates_nothing(self):
        source = self._ready_step("Only step")
        result = self.controller.execute_step(self.plan.plan_id, source.step_id)
        self.assertTrue(result["success"])
        self.assertEqual(result["data_flow"]["propagated_steps"], [])
        self.assertTrue(result["data_flow"]["warnings"])

    def test_never_creates_a_new_plan_step(self):
        source = self._ready_step("Produces output", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda step: {"value": 42})
        self.plans.add_step(
            self.plan.plan_id, "Consumes output", dependencies=[source.step_id],
        )
        before = len(self.plans.get_plan(self.plan.plan_id).steps)

        self.controller.execute_step(self.plan.plan_id, source.step_id)

        after = len(self.plans.get_plan(self.plan.plan_id).steps)
        self.assertEqual(before, after)

    def test_never_modifies_dependency_relationships(self):
        source = self._ready_step("Produces output", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda step: {"value": 42})
        dependent = self.plans.add_step(
            self.plan.plan_id, "Consumes output", dependencies=[source.step_id],
        )

        self.controller.execute_step(self.plan.plan_id, source.step_id)

        self.assertEqual(dependent.dependencies, [source.step_id])

    def test_uses_the_existing_shared_data_flow_manager(self):
        """Reuses DataFlowManager.propagate_completed_step unchanged,
        via the exact same instance already shared through
        self.context_builder - never a second, disagreeing one."""
        from unittest.mock import patch

        source = self._ready_step("Only step")
        real_propagate = (
            self.controller.context_builder.data_flow_manager.propagate_completed_step
        )

        with patch.object(
            self.controller.context_builder.data_flow_manager,
            "propagate_completed_step", side_effect=real_propagate,
        ) as spy:
            result = self.controller.execute_step(self.plan.plan_id, source.step_id)

        spy.assert_called_once_with(self.plan.plan_id, source.step_id)
        self.assertTrue(result["success"])


# --------------------------------------------------------------------
# 6. Existing tests remain compatible: adding automatic
# DataFlowManager propagation on completion must not change anything
# about StepExecutionController's own pre-existing behavior for a
# plan with no dependents at all.
# --------------------------------------------------------------------
class TestDataFlowPropagationIsBackwardCompatible(StepExecutionControllerTestBase):
    def test_simple_successful_execution_is_unaffected(self):
        step = self._ready_step()
        result = self.controller.execute_step(self.plan.plan_id, step.step_id)
        self.assertTrue(result["success"])
        self.assertEqual(step.status, STATUS_COMPLETED)

    def test_result_shape_gains_only_the_new_data_flow_key(self):
        step = self._ready_step()
        result = self.controller.execute_step(self.plan.plan_id, step.step_id)
        for key in (
            "success", "plan_id", "step_id", "execution_id", "step_status",
            "output", "error", "warnings", "events_recorded", "context", "data_flow",
        ):
            self.assertIn(key, result)

    def test_preparation_failure_still_reports_no_data_flow(self):
        result = self.controller.execute_step(self.plan.plan_id, "no-such-step")
        self.assertFalse(result["success"])
        self.assertIsNone(result["data_flow"])


if __name__ == "__main__":
    unittest.main()
