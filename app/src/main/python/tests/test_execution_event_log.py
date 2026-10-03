"""
Tests for ExecutionEventLog (execution/execution_event_log.py).

Covers: recording an event, listing all events, listing for an
execution/plan/step, retrieving the latest event, clearing the log,
chronological order preservation, duplicate protection, and unknown
lookups - this module only stores/retrieves ExecutionEvent objects the
caller already built, so there's nothing here about the
ExecutionEngine actually deciding when to record one.

Run directly:
    python -m unittest tests.test_execution_event_log -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.execution_event import ExecutionEvent, EVENT_EXECUTION_CREATED, EVENT_EXECUTION_COMPLETED
from execution.execution_event_log import ExecutionEventLog


def _make_event(
    plan_id="plan-1", step_id="step-1", execution_id=None,
    event_type=EVENT_EXECUTION_CREATED, event_id=None,
):
    return ExecutionEvent(
        event_type=event_type, plan_id=plan_id, step_id=step_id,
        execution_id=execution_id, event_id=event_id,
    )


class TestRecord(unittest.TestCase):
    def setUp(self):
        self.log = ExecutionEventLog()

    def test_record_returns_the_same_event(self):
        event = _make_event()
        recorded = self.log.record(event)
        self.assertIs(recorded, event)

    def test_record_rejects_non_execution_event(self):
        with self.assertRaises(TypeError):
            self.log.record("not-an-event")

    def test_record_increases_length(self):
        self.assertEqual(len(self.log), 0)
        self.log.record(_make_event())
        self.assertEqual(len(self.log), 1)


class TestListAll(unittest.TestCase):
    def test_empty_log_returns_empty_list(self):
        self.assertEqual(ExecutionEventLog().list_all(), [])

    def test_list_all_returns_every_recorded_event(self):
        log = ExecutionEventLog()
        first = _make_event(event_id="event-1")
        second = _make_event(event_id="event-2")
        log.record(first)
        log.record(second)
        self.assertEqual(log.list_all(), [first, second])

    def test_list_all_returns_a_copy(self):
        log = ExecutionEventLog()
        log.record(_make_event(event_id="event-1"))
        result = log.list_all()
        result.append("tampered")
        self.assertEqual(len(log.list_all()), 1)


class TestListForExecution(unittest.TestCase):
    def setUp(self):
        self.log = ExecutionEventLog()

    def test_returns_only_matching_execution(self):
        a = _make_event(execution_id="execution-1", event_id="e1")
        b = _make_event(execution_id="execution-2", event_id="e2")
        c = _make_event(execution_id="execution-1", event_id="e3")
        for event in (a, b, c):
            self.log.record(event)

        self.assertEqual(self.log.list_for_execution("execution-1"), [a, c])

    def test_unknown_execution_id_returns_empty_list(self):
        self.log.record(_make_event(execution_id="execution-1", event_id="e1"))
        self.assertEqual(self.log.list_for_execution("no-such-execution"), [])

    def test_none_execution_id_matches_events_with_no_execution_id(self):
        without_id = _make_event(execution_id=None, event_id="e1")
        with_id = _make_event(execution_id="execution-1", event_id="e2")
        self.log.record(without_id)
        self.log.record(with_id)
        self.assertEqual(self.log.list_for_execution(None), [without_id])


class TestListForPlan(unittest.TestCase):
    def test_returns_only_matching_plan(self):
        log = ExecutionEventLog()
        a = _make_event(plan_id="plan-1", event_id="e1")
        b = _make_event(plan_id="plan-2", event_id="e2")
        log.record(a)
        log.record(b)
        self.assertEqual(log.list_for_plan("plan-1"), [a])

    def test_unknown_plan_id_returns_empty_list(self):
        log = ExecutionEventLog()
        log.record(_make_event(plan_id="plan-1", event_id="e1"))
        self.assertEqual(log.list_for_plan("plan-missing"), [])


class TestListForStep(unittest.TestCase):
    def test_returns_only_matching_plan_and_step(self):
        log = ExecutionEventLog()
        a = _make_event(plan_id="plan-1", step_id="step-1", event_id="e1")
        b = _make_event(plan_id="plan-1", step_id="step-2", event_id="e2")
        c = _make_event(plan_id="plan-2", step_id="step-1", event_id="e3")
        for event in (a, b, c):
            log.record(event)
        self.assertEqual(log.list_for_step("plan-1", "step-1"), [a])

    def test_unknown_step_returns_empty_list(self):
        log = ExecutionEventLog()
        log.record(_make_event(plan_id="plan-1", step_id="step-1", event_id="e1"))
        self.assertEqual(log.list_for_step("plan-1", "missing-step"), [])


class TestLatest(unittest.TestCase):
    def test_empty_log_returns_none(self):
        self.assertIsNone(ExecutionEventLog().latest())

    def test_returns_most_recently_recorded_event(self):
        log = ExecutionEventLog()
        first = _make_event(event_id="e1")
        second = _make_event(event_id="e2")
        log.record(first)
        log.record(second)
        self.assertIs(log.latest(), second)

    def test_duplicate_record_does_not_change_latest(self):
        log = ExecutionEventLog()
        first = _make_event(event_id="e1")
        second = _make_event(event_id="e2")
        log.record(first)
        log.record(second)
        log.record(first)  # duplicate id, should be a no-op
        self.assertIs(log.latest(), second)


class TestClear(unittest.TestCase):
    def test_clear_empties_the_log(self):
        log = ExecutionEventLog()
        log.record(_make_event(event_id="e1"))
        log.record(_make_event(event_id="e2"))
        log.clear()
        self.assertEqual(len(log), 0)
        self.assertEqual(log.list_all(), [])
        self.assertIsNone(log.latest())

    def test_clear_on_empty_log_is_a_no_op(self):
        log = ExecutionEventLog()
        log.clear()
        self.assertEqual(len(log), 0)

    def test_can_record_again_after_clear(self):
        log = ExecutionEventLog()
        log.record(_make_event(event_id="e1"))
        log.clear()
        event = _make_event(event_id="e1")
        log.record(event)
        self.assertEqual(log.list_all(), [event])


class TestChronologicalOrdering(unittest.TestCase):
    def test_events_are_returned_in_insertion_order(self):
        log = ExecutionEventLog()
        events = [
            _make_event(event_id=f"e{i}", event_type=EVENT_EXECUTION_CREATED)
            for i in range(5)
        ]
        for event in events:
            log.record(event)
        self.assertEqual(log.list_all(), events)
        self.assertEqual(log.list_for_plan("plan-1"), events)
        self.assertEqual(log.list_for_step("plan-1", "step-1"), events)


class TestDuplicateProtection(unittest.TestCase):
    def test_recording_same_event_id_twice_keeps_first_object(self):
        log = ExecutionEventLog()
        original = _make_event(event_id="dup")
        duplicate = ExecutionEvent(
            event_type=EVENT_EXECUTION_COMPLETED, plan_id="plan-1", step_id="step-1",
            event_id="dup",
        )

        log.record(original)
        result = log.record(duplicate)

        self.assertIs(result, original)
        self.assertEqual(len(log), 1)
        self.assertEqual(log.list_all(), [original])

    def test_duplicate_recording_does_not_move_insertion_order(self):
        log = ExecutionEventLog()
        first = _make_event(event_id="e1")
        second = _make_event(event_id="e2")
        log.record(first)
        log.record(second)
        log.record(first)  # duplicate; should not move to the end
        self.assertEqual(log.list_all(), [first, second])


if __name__ == "__main__":
    unittest.main()
