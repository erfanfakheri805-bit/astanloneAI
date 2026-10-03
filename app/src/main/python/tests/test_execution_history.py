"""
Tests for ExecutionHistory (execution/execution_history.py).

Covers: recording a result, retrieving by execution_id, listing for a
plan, listing for a step, retrieving the latest execution for a step,
order preservation, a failed execution's presence in history,
duplicate protection, unknown execution/plan/step lookups, and that
none of this executes or mutates anything.

Run directly:
    python -m unittest tests.test_execution_history -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.execution_history import ExecutionHistory
from execution.execution_result import (
    ExecutionResult, STATUS_COMPLETED, STATUS_FAILED,
)


def _make_result(plan_id="plan-1", step_id="plan-1-step-1", execution_id=None):
    result = ExecutionResult(plan_id=plan_id, step_id=step_id, execution_id=execution_id)
    result.mark_running()
    return result


class TestConstruction(unittest.TestCase):
    def test_new_history_is_empty(self):
        history = ExecutionHistory()
        self.assertEqual(len(history), 0)
        self.assertEqual(history.all_results(), [])


class TestRecording(unittest.TestCase):
    def test_record_stores_and_returns_the_result(self):
        history = ExecutionHistory()
        result = _make_result()
        result.mark_completed(output="ok")

        returned = history.record(result)

        self.assertIs(returned, result)
        self.assertEqual(len(history), 1)

    def test_record_rejects_non_execution_result(self):
        history = ExecutionHistory()
        with self.assertRaises(TypeError):
            history.record("not an execution result")
        self.assertEqual(len(history), 0)

    def test_record_preserves_the_original_object_and_its_data(self):
        """Requirement 4: the exact object is stored, not a copy - a
        later in-place change to the same object is visible through
        history too."""
        history = ExecutionHistory()
        result = _make_result()
        result.mark_completed(output={"detail": "first"})
        history.record(result)

        result.metadata["note"] = "added after recording"

        stored = history.get(result.execution_id)
        self.assertIs(stored, result)
        self.assertEqual(stored.metadata["note"], "added after recording")
        self.assertEqual(stored.output, {"detail": "first"})


class TestRetrievalByExecutionId(unittest.TestCase):
    def test_get_returns_the_recorded_result(self):
        history = ExecutionHistory()
        result = _make_result()
        result.mark_completed(output="ok")
        history.record(result)

        self.assertIs(history.get(result.execution_id), result)

    def test_get_returns_none_for_unknown_execution_id(self):
        history = ExecutionHistory()
        self.assertIsNone(history.get("does-not-exist"))


class TestListForPlan(unittest.TestCase):
    def test_lists_only_results_for_the_given_plan(self):
        history = ExecutionHistory()
        a = _make_result(plan_id="plan-a", step_id="plan-a-step-1")
        a.mark_completed(output="ok")
        b = _make_result(plan_id="plan-b", step_id="plan-b-step-1")
        b.mark_completed(output="ok")
        history.record(a)
        history.record(b)

        self.assertEqual(history.list_for_plan("plan-a"), [a])
        self.assertEqual(history.list_for_plan("plan-b"), [b])

    def test_unknown_plan_returns_empty_list(self):
        history = ExecutionHistory()
        self.assertEqual(history.list_for_plan("does-not-exist"), [])


class TestListForStep(unittest.TestCase):
    def test_lists_only_results_for_the_given_step(self):
        history = ExecutionHistory()
        step_one = _make_result(plan_id="plan-1", step_id="plan-1-step-1")
        step_one.mark_completed(output="ok")
        step_two = _make_result(plan_id="plan-1", step_id="plan-1-step-2")
        step_two.mark_completed(output="ok")
        history.record(step_one)
        history.record(step_two)

        self.assertEqual(history.list_for_step("plan-1", "plan-1-step-1"), [step_one])
        self.assertEqual(history.list_for_step("plan-1", "plan-1-step-2"), [step_two])

    def test_unknown_step_returns_empty_list(self):
        history = ExecutionHistory()
        result = _make_result()
        result.mark_completed(output="ok")
        history.record(result)

        self.assertEqual(history.list_for_step("plan-1", "no-such-step"), [])


class TestLatestForStep(unittest.TestCase):
    def test_returns_the_most_recently_recorded_execution(self):
        history = ExecutionHistory()
        first = _make_result(execution_id="execution-1")
        first.mark_completed(output="first")
        second = _make_result(execution_id="execution-2")
        second.mark_failed("boom")
        history.record(first)
        history.record(second)

        self.assertIs(history.latest_for_step("plan-1", "plan-1-step-1"), second)

    def test_returns_none_when_step_has_no_recorded_execution(self):
        history = ExecutionHistory()
        self.assertIsNone(history.latest_for_step("plan-1", "plan-1-step-1"))


class TestExecutionOrder(unittest.TestCase):
    def test_all_results_preserves_recording_order(self):
        history = ExecutionHistory()
        results = []
        for i in range(5):
            result = _make_result(execution_id=f"execution-{i}")
            result.mark_completed(output=i)
            history.record(result)
            results.append(result)

        self.assertEqual(history.all_results(), results)

    def test_list_for_plan_preserves_recording_order_across_steps(self):
        history = ExecutionHistory()
        first = _make_result(plan_id="plan-1", step_id="plan-1-step-1", execution_id="e1")
        first.mark_completed(output="ok")
        second = _make_result(plan_id="plan-1", step_id="plan-1-step-2", execution_id="e2")
        second.mark_completed(output="ok")
        third = _make_result(plan_id="plan-1", step_id="plan-1-step-1", execution_id="e3")
        third.mark_completed(output="ok")
        history.record(first)
        history.record(second)
        history.record(third)

        self.assertEqual(history.list_for_plan("plan-1"), [first, second, third])


class TestFailedExecutionHistory(unittest.TestCase):
    def test_a_failed_result_is_recorded_and_retrievable_like_any_other(self):
        history = ExecutionHistory()
        result = _make_result()
        result.mark_failed("ValueError: boom")
        history.record(result)

        self.assertEqual(history.get(result.execution_id).status, STATUS_FAILED)
        self.assertEqual(history.list_for_step("plan-1", "plan-1-step-1"), [result])
        self.assertIs(history.latest_for_step("plan-1", "plan-1-step-1"), result)


class TestDuplicateProtection(unittest.TestCase):
    def test_recording_the_same_result_twice_does_not_duplicate_it(self):
        history = ExecutionHistory()
        result = _make_result()
        result.mark_completed(output="ok")

        history.record(result)
        history.record(result)

        self.assertEqual(len(history), 1)
        self.assertEqual(history.list_for_step("plan-1", "plan-1-step-1"), [result])

    def test_a_second_result_with_the_same_execution_id_does_not_replace_the_first(self):
        history = ExecutionHistory()
        first = _make_result(execution_id="same-id")
        first.mark_completed(output="first")
        history.record(first)

        second = _make_result(execution_id="same-id")
        second.mark_failed("boom")
        returned = history.record(second)

        # the already-recorded object wins; the second is not stored.
        self.assertIs(returned, first)
        self.assertIs(history.get("same-id"), first)
        self.assertEqual(len(history), 1)


class TestNoSideEffects(unittest.TestCase):
    def test_record_never_mutates_the_result_it_is_given(self):
        history = ExecutionHistory()
        result = _make_result()
        result.mark_completed(output="ok")
        before = result.to_dict()

        history.record(result)

        self.assertEqual(result.to_dict(), before)

    def test_read_only_methods_never_change_stored_count(self):
        history = ExecutionHistory()
        result = _make_result()
        result.mark_completed(output="ok")
        history.record(result)

        history.get(result.execution_id)
        history.list_for_plan("plan-1")
        history.list_for_step("plan-1", "plan-1-step-1")
        history.latest_for_step("plan-1", "plan-1-step-1")
        history.get("does-not-exist")
        history.list_for_plan("does-not-exist")

        self.assertEqual(len(history), 1)


if __name__ == "__main__":
    unittest.main()
