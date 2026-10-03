"""
Tests for ExecutionEngine's integration with ExecutionEventLog
(execution/execution_event.py, execution/execution_event_log.py).

Covers: that execute_step/execute_capability_step/
execute_registered_capability record the documented lifecycle events
(creation, preparation started/completed/failed, execution
started/completed/failed, capability started/completed/failed, output
created) in the right order, that a caller-supplied event_log is
honored, that event logging never breaks an otherwise-successful or
otherwise-failed execution even when the event log itself is broken,
and that none of this changes any pre-existing ExecutionEngine
behavior (ExecutionResult/PlanStep/ExecutionHistory outcomes are
unaffected by whether events are recorded).

Run directly:
    python -m unittest tests.test_execution_engine_events -v
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
from planning.plan import STATUS_READY, STATUS_COMPLETED, STATUS_FAILED

from execution.execution_engine import ExecutionEngine
from execution.execution_event import (
    ExecutionEvent,
    EVENT_EXECUTION_CREATED,
    EVENT_PREPARATION_STARTED,
    EVENT_PREPARATION_COMPLETED,
    EVENT_PREPARATION_FAILED,
    EVENT_EXECUTION_STARTED,
    EVENT_CAPABILITY_STARTED,
    EVENT_CAPABILITY_COMPLETED,
    EVENT_CAPABILITY_FAILED,
    EVENT_OUTPUT_CREATED,
    EVENT_EXECUTION_COMPLETED,
    EVENT_EXECUTION_FAILED,
    SEVERITY_ERROR,
)
from execution.execution_event_log import ExecutionEventLog
from execution.execution_result import (
    STATUS_COMPLETED as EXEC_STATUS_COMPLETED, STATUS_FAILED as EXEC_STATUS_FAILED,
)


class TestExecutionEngineEventsBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.engine = ExecutionEngine(self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _ready_step(self, **kwargs):
        step = self.plans.add_step(self.plan.plan_id, "Do the thing", **kwargs)
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        return step

    def _event_types(self):
        return [event.event_type for event in self.engine.event_log.list_all()]


class TestConstructionWiring(unittest.TestCase):
    def test_default_engine_has_its_own_event_log(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        self.assertIsInstance(engine.event_log, ExecutionEventLog)
        self.assertEqual(len(engine.event_log), 0)

    def test_explicit_event_log_is_honored(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        shared_log = ExecutionEventLog()
        engine = ExecutionEngine(plans, event_log=shared_log)
        self.assertIs(engine.event_log, shared_log)

    def test_rejects_non_event_log_instance(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            ExecutionEngine(plans, event_log="not-a-log")

    def test_engine_starts_with_no_event_logging_errors(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        self.assertEqual(engine.event_logging_errors, [])


class TestExecuteStepSuccessEvents(TestExecutionEngineEventsBase):
    def test_success_records_expected_event_sequence(self):
        step = self._ready_step()

        self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "done")

        self.assertEqual(
            self._event_types(),
            [
                EVENT_PREPARATION_STARTED,
                EVENT_PREPARATION_COMPLETED,
                EVENT_EXECUTION_CREATED,
                EVENT_EXECUTION_STARTED,
                EVENT_OUTPUT_CREATED,
                EVENT_EXECUTION_COMPLETED,
            ],
        )

    def test_events_carry_the_result_execution_id(self):
        step = self._ready_step()

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "done")

        for event in self.engine.event_log.list_for_execution(result.execution_id):
            self.assertEqual(event.execution_id, result.execution_id)
        # Every post-creation event should carry the execution_id.
        tagged_types = {
            e.event_type for e in self.engine.event_log.list_for_execution(result.execution_id)
        }
        self.assertIn(EVENT_EXECUTION_COMPLETED, tagged_types)

    def test_events_carry_plan_id_and_step_id(self):
        step = self._ready_step()
        self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "done")

        for event in self.engine.event_log.list_all():
            self.assertEqual(event.plan_id, self.plan.plan_id)
            self.assertEqual(event.step_id, step.step_id)


class TestExecuteStepPreparationFailureEvents(TestExecutionEngineEventsBase):
    def test_unready_step_records_preparation_failed_not_started_events(self):
        step = self.plans.add_step(self.plan.plan_id, "Not ready yet")

        self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "done")

        self.assertEqual(
            self._event_types(),
            [EVENT_PREPARATION_STARTED, EVENT_PREPARATION_FAILED],
        )

    def test_preparation_failed_event_is_error_severity(self):
        step = self.plans.add_step(self.plan.plan_id, "Not ready yet")
        self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "done")

        failure_events = [
            e for e in self.engine.event_log.list_all() if e.event_type == EVENT_PREPARATION_FAILED
        ]
        self.assertEqual(len(failure_events), 1)
        self.assertTrue(failure_events[0].is_error())
        self.assertEqual(failure_events[0].severity, SEVERITY_ERROR)

    def test_unknown_plan_records_preparation_failed(self):
        self.engine.execute_step("no-such-plan", "no-such-step", lambda s: "done")
        self.assertEqual(
            self._event_types(),
            [EVENT_PREPARATION_STARTED, EVENT_PREPARATION_FAILED],
        )


class TestFailedExecutionEvents(TestExecutionEngineEventsBase):
    def test_handler_exception_records_execution_failed_not_completed(self):
        step = self._ready_step()

        def boom(_step):
            raise RuntimeError("kaboom")

        self.engine.execute_step(self.plan.plan_id, step.step_id, boom)

        self.assertEqual(
            self._event_types(),
            [
                EVENT_PREPARATION_STARTED,
                EVENT_PREPARATION_COMPLETED,
                EVENT_EXECUTION_CREATED,
                EVENT_EXECUTION_STARTED,
                EVENT_EXECUTION_FAILED,
            ],
        )

    def test_execution_failed_event_is_error_severity_with_safe_message(self):
        step = self._ready_step()

        def boom(_step):
            raise RuntimeError("kaboom")

        self.engine.execute_step(self.plan.plan_id, step.step_id, boom)

        failure_event = self.engine.event_log.latest()
        self.assertEqual(failure_event.event_type, EVENT_EXECUTION_FAILED)
        self.assertTrue(failure_event.is_error())
        self.assertIn("RuntimeError", failure_event.message)
        self.assertIn("kaboom", failure_event.message)

    def test_failed_step_status_unaffected_by_event_logging(self):
        step = self._ready_step()

        def boom(_step):
            raise RuntimeError("kaboom")

        self.engine.execute_step(self.plan.plan_id, step.step_id, boom)
        self.assertEqual(
            self.plans.get_step(self.plan.plan_id, step.step_id).status, STATUS_FAILED,
        )


class TestExecuteCapabilityStepLifecycleEvents(TestExecutionEngineEventsBase):
    def test_successful_single_capability_records_expected_sequence(self):
        step = self._ready_step(required_capabilities=["send_email"])
        self.engine.capability_handlers.register("send_email", lambda s: "sent")

        self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(
            self._event_types(),
            [
                EVENT_PREPARATION_STARTED,
                EVENT_PREPARATION_COMPLETED,
                EVENT_EXECUTION_CREATED,
                EVENT_EXECUTION_STARTED,
                EVENT_CAPABILITY_STARTED,
                EVENT_CAPABILITY_COMPLETED,
                EVENT_OUTPUT_CREATED,
                EVENT_EXECUTION_COMPLETED,
            ],
        )

    def test_multiple_capabilities_each_get_started_and_completed_events(self):
        step = self._ready_step(required_capabilities=["first", "second"])
        self.engine.capability_handlers.register("first", lambda s: "1")
        self.engine.capability_handlers.register("second", lambda s: "2")

        self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        capability_events = [
            (e.event_type, e.data.get("capability_name"))
            for e in self.engine.event_log.list_all()
            if e.event_type in (EVENT_CAPABILITY_STARTED, EVENT_CAPABILITY_COMPLETED)
        ]
        self.assertEqual(
            capability_events,
            [
                (EVENT_CAPABILITY_STARTED, "first"),
                (EVENT_CAPABILITY_COMPLETED, "first"),
                (EVENT_CAPABILITY_STARTED, "second"),
                (EVENT_CAPABILITY_COMPLETED, "second"),
            ],
        )

    def test_failing_capability_records_capability_failed_and_stops(self):
        step = self._ready_step(required_capabilities=["first", "second"])

        def boom(_step):
            raise RuntimeError("capability broke")

        self.engine.capability_handlers.register("first", boom)
        self.engine.capability_handlers.register(
            "second", lambda s: self.fail("second handler must not run")
        )

        self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(
            self._event_types(),
            [
                EVENT_PREPARATION_STARTED,
                EVENT_PREPARATION_COMPLETED,
                EVENT_EXECUTION_CREATED,
                EVENT_EXECUTION_STARTED,
                EVENT_CAPABILITY_STARTED,
                EVENT_CAPABILITY_FAILED,
                EVENT_EXECUTION_FAILED,
            ],
        )

    def test_capability_failed_event_is_error_and_names_the_capability(self):
        step = self._ready_step(required_capabilities=["first"])

        def boom(_step):
            raise RuntimeError("capability broke")

        self.engine.capability_handlers.register("first", boom)
        self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        failure_events = [
            e for e in self.engine.event_log.list_all() if e.event_type == EVENT_CAPABILITY_FAILED
        ]
        self.assertEqual(len(failure_events), 1)
        self.assertTrue(failure_events[0].is_error())
        self.assertEqual(failure_events[0].data.get("capability_name"), "first")

    def test_not_ready_step_records_preparation_failed_via_readiness_check(self):
        step = self._ready_step(required_capabilities=["missing_capability"])

        self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(
            self._event_types(),
            [EVENT_PREPARATION_STARTED, EVENT_PREPARATION_FAILED],
        )


class TestExecutionEngineIntegrationDoesNotChangeBehavior(TestExecutionEngineEventsBase):
    """Event logging is purely additive - the engine's existing return
    values, PlanStep status, and ExecutionHistory contents must be
    identical to what they were before event logging existed."""

    def test_successful_execution_result_unaffected(self):
        step = self._ready_step()
        result = self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(result.output, "ok")
        self.assertEqual(
            self.plans.get_step(self.plan.plan_id, step.step_id).status, STATUS_COMPLETED,
        )
        self.assertEqual(len(self.engine.history), 1)

    def test_failed_execution_result_unaffected(self):
        step = self._ready_step()

        def boom(_step):
            raise ValueError("nope")

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, boom)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertIn("nope", result.error)
        self.assertEqual(
            self.plans.get_step(self.plan.plan_id, step.step_id).status, STATUS_FAILED,
        )

    def test_no_extra_plan_steps_are_ever_executed(self):
        first = self._ready_step()
        second = self.plans.add_step(self.plan.plan_id, "Second step")

        self.engine.execute_step(self.plan.plan_id, first.step_id, lambda s: "ok")

        self.assertNotEqual(
            self.plans.get_step(self.plan.plan_id, second.step_id).status, STATUS_COMPLETED,
        )


class _BrokenEventLog(ExecutionEventLog):
    """A stand-in ExecutionEventLog whose `record` always raises, used
    to prove that a broken event log can never break an execution
    attempt (requirement: "event logging must never cause the actual
    execution to fail")."""

    def record(self, event):
        raise RuntimeError("event log is broken")


class TestEventLoggingFailureIsolation(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.engine = ExecutionEngine(self.plans, event_log=_BrokenEventLog())
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _ready_step(self, **kwargs):
        step = self.plans.add_step(self.plan.plan_id, "Do the thing", **kwargs)
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        return step

    def test_successful_execution_still_succeeds_with_a_broken_event_log(self):
        step = self._ready_step()

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(result.output, "ok")
        self.assertEqual(
            self.plans.get_step(self.plan.plan_id, step.step_id).status, STATUS_COMPLETED,
        )

    def test_failed_execution_still_reports_failure_with_a_broken_event_log(self):
        step = self._ready_step()

        def boom(_step):
            raise RuntimeError("kaboom")

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, boom)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(
            self.plans.get_step(self.plan.plan_id, step.step_id).status, STATUS_FAILED,
        )

    def test_capability_execution_still_succeeds_with_a_broken_event_log(self):
        step = self._ready_step(required_capabilities=["send_email"])
        self.engine.capability_handlers.register("send_email", lambda s: "sent")

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)

    def test_event_logging_errors_are_recorded_safely(self):
        step = self._ready_step()
        self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertGreater(len(self.engine.event_logging_errors), 0)
        for entry in self.engine.event_logging_errors:
            self.assertIsInstance(entry, dict)
            self.assertIn("event_type", entry)
            self.assertIn("error", entry)
            self.assertIsInstance(entry["error"], str)

    def test_no_exception_ever_escapes_execute_step(self):
        step = self._ready_step()
        try:
            self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"execute_step raised unexpectedly: {exc!r}")


class TestConstructionRejectsMisuse(unittest.TestCase):
    def test_event_log_shared_across_engines_accumulates_from_both(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        shared_log = ExecutionEventLog()
        engine_one = ExecutionEngine(plans, event_log=shared_log)
        engine_two = ExecutionEngine(plans, event_log=shared_log)

        goal = goals.create_goal("Shared goal")
        plan = plans.create_plan(goal.goal_id)
        step_one = plans.add_step(plan.plan_id, "Step one")
        plans.update_step_status(plan.plan_id, step_one.step_id, STATUS_READY)
        step_two = plans.add_step(plan.plan_id, "Step two")
        plans.update_step_status(plan.plan_id, step_two.step_id, STATUS_READY)

        engine_one.execute_step(plan.plan_id, step_one.step_id, lambda s: "a")
        engine_two.execute_step(plan.plan_id, step_two.step_id, lambda s: "b")

        self.assertEqual(len(shared_log), len(engine_one.event_log))
        self.assertGreaterEqual(len(shared_log.list_for_step(plan.plan_id, step_one.step_id)), 1)
        self.assertGreaterEqual(len(shared_log.list_for_step(plan.plan_id, step_two.step_id)), 1)


if __name__ == "__main__":
    unittest.main()
