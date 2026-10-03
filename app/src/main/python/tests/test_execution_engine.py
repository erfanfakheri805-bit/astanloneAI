"""
Tests for ExecutionEngine (execution/ foundation), including its
connection to PlanStep's own status system (see execution_engine.py's
module docstring).

Covers: successful execution, a handler that raises, invalid plan,
invalid step, a step that isn't READY, the fields/duration recorded on
the returned ExecutionResult, the requirement that a handler must be
explicitly supplied, that a successful/failed execution now syncs the
PlanStep's status to match the ExecutionResult, that a completed
step's dependents get refreshed (and a failed step's dependents stay
blocked), that an already-terminal step is never re-executed or
rewritten, and that no automatic next-step execution ever happens.

Run directly:
    python -m unittest tests.test_execution_engine -v
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
    STATUS_PENDING, STATUS_READY, STATUS_BLOCKED, STATUS_IN_PROGRESS,
    STATUS_COMPLETED, STATUS_FAILED,
)
from execution.execution_engine import ExecutionEngine
from execution.execution_history import ExecutionHistory
from execution.execution_result import (
    ExecutionResult, STATUS_RUNNING, STATUS_COMPLETED as EXEC_STATUS_COMPLETED,
    STATUS_FAILED as EXEC_STATUS_FAILED,
)


class TestExecutionEngineBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.engine = ExecutionEngine(self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _ready_step(self, description="Do the thing"):
        step = self.plans.add_step(self.plan.plan_id, description)
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        return step


class TestConstruction(unittest.TestCase):
    def test_requires_a_plan_manager_instance(self):
        with self.assertRaises(TypeError):
            ExecutionEngine("not-a-plan-manager")


class TestSuccessfulExecution(TestExecutionEngineBase):
    def test_successful_handler_produces_completed_result_with_output(self):
        step = self._ready_step()

        def handler(plan_step):
            return f"handled {plan_step.step_id}"

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)

        self.assertIsInstance(result, ExecutionResult)
        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(result.output, f"handled {step.step_id}")
        self.assertIsNone(result.error)

    def test_handler_is_called_with_the_actual_plan_step_object(self):
        step = self._ready_step()
        received = []

        def handler(plan_step):
            received.append(plan_step)
            return "ok"

        self.engine.execute_step(self.plan.plan_id, step.step_id, handler)
        self.assertEqual(len(received), 1)
        self.assertIs(received[0], step)


class TestHandlerFailure(TestExecutionEngineBase):
    def test_handler_exception_produces_failed_result_with_safe_error(self):
        step = self._ready_step()

        def handler(plan_step):
            raise ValueError("boom")

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertIsNone(result.output)
        self.assertIn("ValueError", result.error)
        self.assertIn("boom", result.error)

    def test_handler_exception_does_not_crash_the_engine(self):
        step = self._ready_step()

        def handler(plan_step):
            raise RuntimeError("kaboom")

        try:
            result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"execute_step raised instead of returning a FAILED result: {exc}")
        self.assertEqual(result.status, EXEC_STATUS_FAILED)

    def test_handler_error_never_contains_a_raw_traceback(self):
        step = self._ready_step()

        def handler(plan_step):
            raise KeyError("missing_key")

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)
        self.assertNotIn("Traceback", result.error)
        self.assertNotIn("File \"", result.error)


class TestInvalidPlan(TestExecutionEngineBase):
    def test_unknown_plan_returns_failed_result_without_calling_handler(self):
        called = []

        def handler(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.execute_step("does-not-exist", "some-step", handler)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(called, [])
        self.assertIn("does-not-exist", result.error)


class TestInvalidStep(TestExecutionEngineBase):
    def test_unknown_step_returns_failed_result_without_calling_handler(self):
        called = []

        def handler(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.execute_step(self.plan.plan_id, "no-such-step", handler)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(called, [])
        self.assertIn("no-such-step", result.error)


class TestNonReadyStep(TestExecutionEngineBase):
    def test_pending_step_returns_failed_result_without_calling_handler(self):
        step = self.plans.add_step(self.plan.plan_id, "Not ready yet")
        self.assertEqual(step.status, STATUS_PENDING)
        called = []

        def handler(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(called, [])
        self.assertIn(STATUS_PENDING, result.error)

    def test_blocked_step_returns_failed_result_without_calling_handler(self):
        step = self.plans.add_step(self.plan.plan_id, "Waiting on something")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_BLOCKED)
        called = []

        def handler(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(called, [])

    def test_already_completed_step_is_not_re_executed(self):
        step = self.plans.add_step(self.plan.plan_id, "Already done")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)
        called = []

        def handler(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(called, [])


class TestExecutionResultFields(TestExecutionEngineBase):
    def test_result_carries_expected_plan_and_step_ids(self):
        step = self._ready_step()
        result = self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertEqual(result.plan_id, self.plan.plan_id)
        self.assertEqual(result.step_id, step.step_id)
        self.assertTrue(result.execution_id)

    def test_every_result_has_a_unique_execution_id(self):
        step_one = self._ready_step("First")
        step_two = self._ready_step("Second")

        first = self.engine.execute_step(self.plan.plan_id, step_one.step_id, lambda s: "ok")
        second = self.engine.execute_step(self.plan.plan_id, step_two.step_id, lambda s: "ok")

        self.assertNotEqual(first.execution_id, second.execution_id)

    def test_to_dict_reports_every_expected_field(self):
        step = self._ready_step()
        result = self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")
        data = result.to_dict()

        self.assertEqual(
            set(data.keys()),
            {
                "execution_id", "plan_id", "step_id", "status", "output", "error",
                "started_at", "finished_at", "duration", "metadata",
            },
        )


class TestExecutionDuration(TestExecutionEngineBase):
    def test_successful_execution_records_started_finished_and_duration(self):
        step = self._ready_step()
        result = self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertTrue(result.started_at)
        self.assertTrue(result.finished_at)
        self.assertIsNotNone(result.duration)
        self.assertGreaterEqual(result.duration, 0.0)

    def test_failed_handler_still_records_duration(self):
        step = self._ready_step()

        def handler(plan_step):
            raise ValueError("boom")

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)
        self.assertTrue(result.started_at)
        self.assertTrue(result.finished_at)
        self.assertIsNotNone(result.duration)

    def test_precondition_failure_still_records_duration(self):
        result = self.engine.execute_step("does-not-exist", "no-step", lambda s: "ok")
        self.assertTrue(result.started_at)
        self.assertTrue(result.finished_at)
        self.assertIsNotNone(result.duration)


class TestNoExecutionWithoutExplicitHandler(TestExecutionEngineBase):
    def test_missing_handler_argument_raises_type_error(self):
        step = self._ready_step()
        with self.assertRaises(TypeError):
            self.engine.execute_step(self.plan.plan_id, step.step_id)

    def test_none_handler_raises_type_error_and_runs_nothing(self):
        step = self._ready_step()
        with self.assertRaises(TypeError):
            self.engine.execute_step(self.plan.plan_id, step.step_id, None)
        # nothing ran, so the step's status is exactly as it was
        self.assertEqual(step.status, STATUS_READY)

    def test_non_callable_handler_raises_type_error(self):
        step = self._ready_step()
        with self.assertRaises(TypeError):
            self.engine.execute_step(self.plan.plan_id, step.step_id, "not a function")


class TestNoSideEffects(TestExecutionEngineBase):
    """Side effects this engine still must never cause, even now that
    it syncs PlanStep status on a real execution (see
    TestPlanStepSync below for the sync behavior itself)."""

    def test_plan_step_count_is_unchanged_after_execution(self):
        step = self._ready_step()
        before = len(self.plan.steps)
        self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")
        self.assertEqual(len(self.plan.steps), before)

    def test_precondition_failure_never_touches_plan_step_status(self):
        """Unknown plan/step/non-READY step: no PlanStep was actually
        run, so none of these should ever call update_step_status or
        otherwise change a step's status."""
        step = self.plans.add_step(self.plan.plan_id, "Not ready yet")
        calls = []
        original = self.plans.update_step_status

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        self.plans.update_step_status = spy
        try:
            self.engine.execute_step("does-not-exist", "some-step", lambda s: "ok")
            self.engine.execute_step(self.plan.plan_id, "no-such-step", lambda s: "ok")
            self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")
        finally:
            self.plans.update_step_status = original
        self.assertEqual(calls, [])
        self.assertEqual(step.status, STATUS_PENDING)

    def test_engine_reuses_plan_manager_update_step_status_rather_than_writing_directly(self):
        """Requirement 10: the sync goes through
        PlanManager.update_step_status (so its existing validation/
        rules still apply) instead of this engine setting
        `step.status` itself."""
        step = self._ready_step()
        calls = []
        original = self.plans.update_step_status

        def spy(*args, **kwargs):
            calls.append(args[1:])
            return original(*args, **kwargs)

        self.plans.update_step_status = spy
        try:
            self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")
        finally:
            self.plans.update_step_status = original
        self.assertEqual(calls, [(step.step_id, STATUS_COMPLETED)])

    def test_no_automatic_next_step_execution(self):
        """Requirement 7: completing one step never causes another
        READY/newly-READY step to run on its own."""
        first = self._ready_step("First")
        second = self.plans.add_step(
            self.plan.plan_id, "Second", dependencies=[first.step_id]
        )
        calls = []

        def handler(plan_step):
            calls.append(plan_step.step_id)
            return "ok"

        self.engine.execute_step(self.plan.plan_id, first.step_id, handler)

        # second is now READY (see TestPlanStepSync), but nothing ran it.
        self.assertEqual(second.status, STATUS_READY)
        self.assertEqual(calls, [first.step_id])


class TestPlanStepSync(TestExecutionEngineBase):
    """Requirements 1-6, 8-9: ExecutionEngine now synchronizes a real
    execution's outcome onto the PlanStep it just ran."""

    def test_successful_step_becomes_completed(self):
        step = self._ready_step()
        result = self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(step.status, STATUS_COMPLETED)

    def test_failed_step_becomes_failed(self):
        step = self._ready_step()

        def handler(plan_step):
            raise ValueError("boom")

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(step.status, STATUS_FAILED)

    def test_execution_result_and_plan_step_status_stay_consistent(self):
        """Requirement: execution result and PlanStep status stay
        consistent, for both outcomes."""
        ok_step = self._ready_step("Will succeed")
        ok_result = self.engine.execute_step(self.plan.plan_id, ok_step.step_id, lambda s: "ok")
        self.assertEqual(ok_result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(ok_step.status, STATUS_COMPLETED)

        fail_step = self._ready_step("Will fail")

        def handler(plan_step):
            raise RuntimeError("nope")

        fail_result = self.engine.execute_step(self.plan.plan_id, fail_step.step_id, handler)
        self.assertEqual(fail_result.status, EXEC_STATUS_FAILED)
        self.assertEqual(fail_step.status, STATUS_FAILED)

    def test_dependent_step_becomes_ready_after_successful_completion(self):
        upstream = self._ready_step("Upstream")
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id]
        )
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id)
        self.assertEqual(downstream.status, STATUS_BLOCKED)

        self.engine.execute_step(self.plan.plan_id, upstream.step_id, lambda s: "ok")

        self.assertEqual(upstream.status, STATUS_COMPLETED)
        self.assertEqual(downstream.status, STATUS_READY)

    def test_dependent_step_remains_blocked_after_failure(self):
        upstream = self._ready_step("Upstream")
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id]
        )
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id)
        self.assertEqual(downstream.status, STATUS_BLOCKED)

        def handler(plan_step):
            raise ValueError("boom")

        self.engine.execute_step(self.plan.plan_id, upstream.step_id, handler)

        self.assertEqual(upstream.status, STATUS_FAILED)
        self.assertEqual(downstream.status, STATUS_BLOCKED)

    def test_already_completed_step_is_not_re_executed_or_rewritten(self):
        step = self.plans.add_step(self.plan.plan_id, "Already done")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)
        called = []

        def handler(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(called, [])
        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(step.status, STATUS_COMPLETED)

    def test_already_failed_step_is_not_re_executed_or_rewritten(self):
        step = self.plans.add_step(self.plan.plan_id, "Already failed")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)
        called = []

        def handler(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(called, [])
        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertEqual(step.status, STATUS_FAILED)

    def test_step_never_left_in_progress_after_execution(self):
        """Requirement 4: RUNNING/IN_PROGRESS is only ever a transient
        mid-call state - a returned result always corresponds to a
        step that has already settled into COMPLETED or FAILED."""
        ok_step = self._ready_step("Ok")
        self.engine.execute_step(self.plan.plan_id, ok_step.step_id, lambda s: "ok")
        self.assertNotEqual(ok_step.status, STATUS_IN_PROGRESS)

        fail_step = self._ready_step("Fails")

        def handler(plan_step):
            raise ValueError("boom")

        self.engine.execute_step(self.plan.plan_id, fail_step.step_id, handler)
        self.assertNotEqual(fail_step.status, STATUS_IN_PROGRESS)

    def test_capability_system_is_forwarded_to_dependent_refresh(self):
        """Requirement 8/9: capability_system is only ever forwarded
        read-only into the existing refresh logic - never used to
        create/enable/install/execute a capability itself."""

        class FakeCapabilitySystem:
            def all(self):
                return []

        upstream = self._ready_step("Upstream")
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream",
            dependencies=[upstream.step_id],
            required_capabilities=["some_capability"],
        )
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id)

        fake_caps = FakeCapabilitySystem()
        self.engine.execute_step(
            self.plan.plan_id, upstream.step_id, lambda s: "ok",
            capability_system=fake_caps,
        )

        # required_capabilities isn't registered in fake_caps, so the
        # dependent stays BLOCKED - proving the capability_system was
        # actually consulted (read-only) by the refresh.
        self.assertEqual(downstream.status, STATUS_BLOCKED)


class TestExecutionHistoryIntegration(TestExecutionEngineBase):
    """Requirement 10 (stage 24): every terminal ExecutionResult this
    engine produces is also recorded into its ExecutionHistory."""

    def test_successful_execution_is_recorded(self):
        step = self._ready_step()
        result = self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertIs(self.engine.history.get(result.execution_id), result)

    def test_failed_handler_execution_is_recorded(self):
        step = self._ready_step()

        def handler(plan_step):
            raise ValueError("boom")

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)

        self.assertIs(self.engine.history.get(result.execution_id), result)
        self.assertEqual(self.engine.history.get(result.execution_id).status, EXEC_STATUS_FAILED)

    def test_precondition_failure_is_also_recorded(self):
        result = self.engine.execute_step("does-not-exist", "some-step", lambda s: "ok")
        self.assertIs(self.engine.history.get(result.execution_id), result)

    def test_history_can_be_queried_by_plan_and_step_after_execution(self):
        step = self._ready_step()
        result = self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertEqual(self.engine.history.list_for_plan(self.plan.plan_id), [result])
        self.assertEqual(
            self.engine.history.list_for_step(self.plan.plan_id, step.step_id), [result]
        )
        self.assertIs(
            self.engine.history.latest_for_step(self.plan.plan_id, step.step_id), result
        )

    def test_a_shared_history_can_be_supplied_explicitly(self):
        shared = ExecutionHistory()
        engine = ExecutionEngine(self.plans, history=shared)
        step = self._ready_step()

        result = engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertIs(shared.get(result.execution_id), result)
        self.assertIs(engine.history, shared)

    def test_constructor_rejects_a_non_execution_history_object(self):
        with self.assertRaises(TypeError):
            ExecutionEngine(self.plans, history="not a history")

    def test_default_history_is_private_per_engine_instance(self):
        other_engine = ExecutionEngine(self.plans)
        self.assertIsNot(self.engine.history, other_engine.history)


class TestRetryStepBase(TestExecutionEngineBase):
    """Shared helper: a step that has already been made READY, run
    once through execute_step, and failed - the standard starting
    point for most retry_step tests."""

    def _failed_step(self, description="Will fail then retry"):
        step = self._ready_step(description)

        def failing_handler(plan_step):
            raise ValueError("boom")

        self.engine.execute_step(self.plan.plan_id, step.step_id, failing_handler)
        self.assertEqual(step.status, STATUS_FAILED)
        return step


class TestFirstRetryAfterFailure(TestRetryStepBase):
    def test_retry_is_allowed_and_calls_the_handler(self):
        step = self._failed_step()
        called = []

        def handler(plan_step):
            called.append(plan_step.step_id)
            return "fixed"

        result = self.engine.retry_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(called, [step.step_id])
        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)


class TestSuccessfulRetry(TestRetryStepBase):
    def test_successful_retry_produces_completed_result_with_output(self):
        step = self._failed_step()

        result = self.engine.retry_step(
            self.plan.plan_id, step.step_id, lambda s: "fixed now"
        )

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(result.output, "fixed now")
        self.assertIsNone(result.error)

    def test_successful_retry_updates_plan_step_to_completed(self):
        """Requirement 10: uses the existing sync logic
        (PlanManager.update_step_status), same path execute_step
        already uses."""
        step = self._failed_step()
        self.engine.retry_step(self.plan.plan_id, step.step_id, lambda s: "fixed")
        self.assertEqual(step.status, STATUS_COMPLETED)

    def test_successful_retry_refreshes_dependents(self):
        upstream = self._failed_step("Upstream")
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id]
        )
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id)
        self.assertEqual(downstream.status, STATUS_BLOCKED)

        self.engine.retry_step(self.plan.plan_id, upstream.step_id, lambda s: "ok")

        self.assertEqual(upstream.status, STATUS_COMPLETED)
        self.assertEqual(downstream.status, STATUS_READY)


class TestFailedRetry(TestRetryStepBase):
    def test_failed_retry_produces_failed_result_with_safe_error(self):
        step = self._failed_step()

        def handler(plan_step):
            raise RuntimeError("still broken")

        result = self.engine.retry_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertIn("RuntimeError", result.error)
        self.assertIn("still broken", result.error)

    def test_failed_retry_leaves_plan_step_failed(self):
        step = self._failed_step()

        def handler(plan_step):
            raise RuntimeError("still broken")

        self.engine.retry_step(self.plan.plan_id, step.step_id, handler)
        self.assertEqual(step.status, STATUS_FAILED)

    def test_failed_retry_does_not_refresh_dependents(self):
        upstream = self._failed_step("Upstream")
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id]
        )
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id)

        def handler(plan_step):
            raise RuntimeError("still broken")

        self.engine.retry_step(self.plan.plan_id, upstream.step_id, handler)
        self.assertEqual(downstream.status, STATUS_BLOCKED)


class TestRetryNumbering(TestRetryStepBase):
    def test_first_retry_has_retry_number_one(self):
        step = self._failed_step()

        def handler(plan_step):
            raise RuntimeError("still broken")

        result = self.engine.retry_step(self.plan.plan_id, step.step_id, handler)
        self.assertEqual(result.metadata["retry_number"], 1)

    def test_second_retry_has_retry_number_two(self):
        step = self._failed_step()

        def failing(plan_step):
            raise RuntimeError("still broken")

        self.engine.retry_step(self.plan.plan_id, step.step_id, failing)
        second = self.engine.retry_step(self.plan.plan_id, step.step_id, failing)

        self.assertEqual(second.metadata["retry_number"], 2)

    def test_retry_number_is_derived_from_history_not_a_global_counter(self):
        """Requirement 7: a second, independent step's retries never
        influence this step's own retry_number."""
        other = self._failed_step("Other step")

        def failing(plan_step):
            raise RuntimeError("still broken")

        # Retry an unrelated step several times first.
        self.engine.retry_step(self.plan.plan_id, other.step_id, failing)
        self.engine.retry_step(self.plan.plan_id, other.step_id, failing)

        step = self._failed_step("Fresh step")
        result = self.engine.retry_step(self.plan.plan_id, step.step_id, failing)
        self.assertEqual(result.metadata["retry_number"], 1)


class TestRetryOfReference(TestRetryStepBase):
    def test_retry_of_points_to_the_failed_execution_it_retried(self):
        step = self._failed_step()
        original = self.engine.history.latest_for_step(self.plan.plan_id, step.step_id)

        result = self.engine.retry_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertEqual(result.metadata["retry_of"], original.execution_id)

    def test_retry_of_chains_to_the_previous_retry_on_a_second_attempt(self):
        step = self._failed_step()

        def failing(plan_step):
            raise RuntimeError("still broken")

        first_retry = self.engine.retry_step(self.plan.plan_id, step.step_id, failing)
        second_retry = self.engine.retry_step(self.plan.plan_id, step.step_id, failing)

        self.assertEqual(second_retry.metadata["retry_of"], first_retry.execution_id)

    def test_retry_produces_a_new_distinct_execution_id(self):
        step = self._failed_step()
        original = self.engine.history.latest_for_step(self.plan.plan_id, step.step_id)

        result = self.engine.retry_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertNotEqual(result.execution_id, original.execution_id)


class TestMaximumRetryLimit(TestRetryStepBase):
    def test_retry_beyond_the_configured_maximum_is_refused(self):
        engine = ExecutionEngine(self.plans, max_retries=1)
        step = self._ready_step()

        def failing(plan_step):
            raise RuntimeError("still broken")

        engine.execute_step(self.plan.plan_id, step.step_id, failing)
        first_retry = engine.retry_step(self.plan.plan_id, step.step_id, failing)
        self.assertEqual(first_retry.status, EXEC_STATUS_FAILED)
        self.assertEqual(first_retry.metadata["retry_number"], 1)

        called = []

        def should_not_run(plan_step):
            called.append(True)
            return "should not run"

        second_retry = engine.retry_step(self.plan.plan_id, step.step_id, should_not_run)

        self.assertEqual(called, [])
        self.assertEqual(second_retry.status, EXEC_STATUS_FAILED)
        self.assertTrue(second_retry.metadata.get("max_retries_reached"))

    def test_step_is_not_modified_when_the_maximum_is_reached(self):
        engine = ExecutionEngine(self.plans, max_retries=1)
        step = self._ready_step()

        def failing(plan_step):
            raise RuntimeError("still broken")

        engine.execute_step(self.plan.plan_id, step.step_id, failing)
        engine.retry_step(self.plan.plan_id, step.step_id, failing)
        self.assertEqual(step.status, STATUS_FAILED)

        engine.retry_step(self.plan.plan_id, step.step_id, lambda s: "should not run")
        # Still FAILED - refusing the retry never touched the step.
        self.assertEqual(step.status, STATUS_FAILED)

    def test_max_retries_can_be_overridden_per_call(self):
        step = self._failed_step()

        def failing(plan_step):
            raise RuntimeError("still broken")

        result = self.engine.retry_step(
            self.plan.plan_id, step.step_id, failing, max_retries=1
        )
        self.assertEqual(result.status, EXEC_STATUS_FAILED)

        called = []

        def should_not_run(plan_step):
            called.append(True)
            return "should not run"

        blocked = self.engine.retry_step(
            self.plan.plan_id, step.step_id, should_not_run, max_retries=1
        )
        self.assertEqual(called, [])
        self.assertTrue(blocked.metadata.get("max_retries_reached"))

    def test_default_max_retries_is_configurable_at_construction(self):
        engine = ExecutionEngine(self.plans, max_retries=5)
        self.assertEqual(engine.max_retries, 5)

    def test_constructor_rejects_a_non_positive_max_retries(self):
        with self.assertRaises(ValueError):
            ExecutionEngine(self.plans, max_retries=0)


class TestRetryingAStepWithNoPreviousFailure(TestRetryStepBase):
    def test_retrying_a_never_run_step_is_refused(self):
        step = self._ready_step()
        called = []

        def handler(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.retry_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(called, [])
        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertIn("no prior FAILED execution", result.error)

    def test_retrying_a_step_whose_latest_execution_succeeded_is_refused(self):
        step = self._ready_step()
        self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")
        self.assertEqual(step.status, STATUS_COMPLETED)

        # Move it back to a non-terminal status so the "already
        # COMPLETED" check isn't what's actually being exercised here.
        step.set_status(STATUS_FAILED)
        called = []

        def handler(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.retry_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(called, [])
        self.assertEqual(result.status, EXEC_STATUS_FAILED)


class TestRetryingACompletedStep(TestRetryStepBase):
    def test_retrying_a_completed_step_is_refused_without_calling_handler(self):
        step = self._ready_step()
        self.engine.execute_step(self.plan.plan_id, step.step_id, lambda s: "ok")
        self.assertEqual(step.status, STATUS_COMPLETED)
        called = []

        def handler(plan_step):
            called.append(True)
            return "should not run"

        result = self.engine.retry_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(called, [])
        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertIn("already COMPLETED", result.error)
        self.assertEqual(step.status, STATUS_COMPLETED)


class TestRetryWithoutAHandler(TestRetryStepBase):
    def test_missing_handler_argument_raises_type_error(self):
        step = self._failed_step()
        with self.assertRaises(TypeError):
            self.engine.retry_step(self.plan.plan_id, step.step_id)

    def test_none_handler_raises_type_error_and_runs_nothing(self):
        step = self._failed_step()
        with self.assertRaises(TypeError):
            self.engine.retry_step(self.plan.plan_id, step.step_id, None)
        self.assertEqual(step.status, STATUS_FAILED)

    def test_non_callable_handler_raises_type_error(self):
        step = self._failed_step()
        with self.assertRaises(TypeError):
            self.engine.retry_step(self.plan.plan_id, step.step_id, "not a function")


class TestRetryExecutionHistoryCorrectness(TestRetryStepBase):
    def test_retry_result_is_recorded_in_history(self):
        step = self._failed_step()
        result = self.engine.retry_step(self.plan.plan_id, step.step_id, lambda s: "ok")

        self.assertIs(self.engine.history.get(result.execution_id), result)

    def test_history_for_step_includes_original_and_retry_in_order(self):
        step = self._failed_step()
        original = self.engine.history.latest_for_step(self.plan.plan_id, step.step_id)

        retry_result = self.engine.retry_step(
            self.plan.plan_id, step.step_id, lambda s: "ok"
        )

        history = self.engine.history.list_for_step(self.plan.plan_id, step.step_id)
        self.assertEqual(history, [original, retry_result])

    def test_latest_for_step_reflects_the_retry_after_it_runs(self):
        step = self._failed_step()
        retry_result = self.engine.retry_step(
            self.plan.plan_id, step.step_id, lambda s: "ok"
        )

        self.assertIs(
            self.engine.history.latest_for_step(self.plan.plan_id, step.step_id),
            retry_result,
        )

    def test_refused_retry_at_the_max_is_also_recorded(self):
        engine = ExecutionEngine(self.plans, max_retries=1)
        step = self._ready_step()

        def failing(plan_step):
            raise RuntimeError("still broken")

        engine.execute_step(self.plan.plan_id, step.step_id, failing)
        engine.retry_step(self.plan.plan_id, step.step_id, failing)
        before = len(engine.history)

        refused = engine.retry_step(self.plan.plan_id, step.step_id, failing)

        self.assertEqual(len(engine.history), before + 1)
        self.assertIs(engine.history.get(refused.execution_id), refused)


class TestNoAutomaticRetry(TestRetryStepBase):
    def test_execute_step_never_retries_a_failed_step_on_its_own(self):
        """Requirement 12: nothing about a failed execute_step call
        ever triggers a retry_step call automatically."""
        step = self._ready_step()

        def failing(plan_step):
            raise RuntimeError("still broken")

        self.engine.execute_step(self.plan.plan_id, step.step_id, failing)

        # Exactly one execution recorded - no retry happened on its own.
        self.assertEqual(
            len(self.engine.history.list_for_step(self.plan.plan_id, step.step_id)), 1
        )
        self.assertEqual(step.status, STATUS_FAILED)

    def test_a_failed_retry_does_not_trigger_another_retry_on_its_own(self):
        step = self._failed_step()

        def failing(plan_step):
            raise RuntimeError("still broken")

        self.engine.retry_step(self.plan.plan_id, step.step_id, failing)

        # Exactly two executions recorded (original failure + the one
        # retry actually requested) - nothing retried itself further.
        self.assertEqual(
            len(self.engine.history.list_for_step(self.plan.plan_id, step.step_id)), 2
        )

    def test_successful_retry_does_not_automatically_execute_dependents(self):
        """Requirement 13."""
        upstream = self._failed_step("Upstream")
        downstream = self.plans.add_step(
            self.plan.plan_id, "Downstream", dependencies=[upstream.step_id]
        )
        self.plans.refresh_step_status(self.plan.plan_id, downstream.step_id)
        calls = []

        def downstream_handler(plan_step):
            calls.append(plan_step.step_id)
            return "should not run automatically"

        self.engine.retry_step(self.plan.plan_id, upstream.step_id, lambda s: "ok")

        self.assertEqual(downstream.status, STATUS_READY)
        self.assertEqual(calls, [])
        self.assertEqual(
            len(self.engine.history.list_for_step(self.plan.plan_id, downstream.step_id)), 0
        )


if __name__ == "__main__":
    unittest.main()
