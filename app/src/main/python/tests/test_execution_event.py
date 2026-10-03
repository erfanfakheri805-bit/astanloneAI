"""
Tests for the ExecutionEvent model (execution/execution_event.py).

Covers: safe construction (and its guards), the event-type and
severity controlled vocabularies, structured-data-only `data`/
`metadata`, `to_dict()`, `is_error()`, and that event ids are always
unique - this module only defines the structured event record, so
there's nothing here about the ExecutionEngine actually recording one.

Run directly:
    python -m unittest tests.test_execution_event -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    EVENT_EXECUTION_CANCELLED,
    EVENT_AGENT_LOOP_STARTED,
    EVENT_AGENT_ITERATION_STARTED,
    EVENT_AGENT_EVALUATION_COMPLETED,
    EVENT_AGENT_EXECUTION_COMPLETED,
    EVENT_AGENT_LOOP_COMPLETED,
    EVENT_AGENT_LOOP_STOPPED,
    EVENT_AGENT_LOOP_FAILED,
    ALL_EVENT_TYPES,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SEVERITY_ERROR,
    ALL_SEVERITIES,
)


class TestConstruction(unittest.TestCase):
    def test_default_construction_has_expected_fields(self):
        event = ExecutionEvent(
            event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="plan-1-step-1",
        )

        self.assertTrue(event.event_id)
        self.assertIsNone(event.execution_id)
        self.assertEqual(event.plan_id, "plan-1")
        self.assertEqual(event.step_id, "plan-1-step-1")
        self.assertEqual(event.event_type, EVENT_EXECUTION_CREATED)
        self.assertEqual(event.message, "")
        self.assertTrue(event.timestamp)
        self.assertEqual(event.data, {})
        self.assertEqual(event.severity, SEVERITY_INFO)
        self.assertEqual(event.metadata, {})

    def test_explicit_fields_are_honored(self):
        event = ExecutionEvent(
            event_type=EVENT_EXECUTION_STARTED,
            plan_id="plan-1",
            step_id="plan-1-step-1",
            execution_id="execution-7",
            message="Started.",
            data={"attempt": 1},
            severity=SEVERITY_WARNING,
            metadata={"source": "engine"},
            timestamp="2024-01-01T00:00:00+00:00",
            event_id="custom-event-id",
        )

        self.assertEqual(event.event_id, "custom-event-id")
        self.assertEqual(event.execution_id, "execution-7")
        self.assertEqual(event.message, "Started.")
        self.assertEqual(event.data, {"attempt": 1})
        self.assertEqual(event.severity, SEVERITY_WARNING)
        self.assertEqual(event.metadata, {"source": "engine"})
        self.assertEqual(event.timestamp, "2024-01-01T00:00:00+00:00")

    def test_two_events_get_unique_default_ids(self):
        first = ExecutionEvent(
            event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="step-1",
        )
        second = ExecutionEvent(
            event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="step-1",
        )
        self.assertNotEqual(first.event_id, second.event_id)

    def test_metadata_and_data_default_to_independent_dicts(self):
        first = ExecutionEvent(
            event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="step-1",
        )
        second = ExecutionEvent(
            event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="step-1",
        )
        first.data["x"] = 1
        first.metadata["y"] = 2
        self.assertEqual(second.data, {})
        self.assertEqual(second.metadata, {})


class TestRequiredIdentifiers(unittest.TestCase):
    def test_missing_plan_id_raises(self):
        with self.assertRaises(ValueError):
            ExecutionEvent(event_type=EVENT_EXECUTION_CREATED, plan_id=None, step_id="step-1")

    def test_empty_plan_id_raises(self):
        with self.assertRaises(ValueError):
            ExecutionEvent(event_type=EVENT_EXECUTION_CREATED, plan_id="", step_id="step-1")

    def test_missing_step_id_raises(self):
        with self.assertRaises(ValueError):
            ExecutionEvent(event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id=None)

    def test_empty_step_id_raises(self):
        with self.assertRaises(ValueError):
            ExecutionEvent(event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="")

    def test_non_string_plan_id_raises(self):
        with self.assertRaises(ValueError):
            ExecutionEvent(event_type=EVENT_EXECUTION_CREATED, plan_id=123, step_id="step-1")

    def test_execution_id_may_be_none(self):
        event = ExecutionEvent(
            event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="step-1",
            execution_id=None,
        )
        self.assertIsNone(event.execution_id)

    def test_empty_execution_id_raises(self):
        with self.assertRaises(ValueError):
            ExecutionEvent(
                event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="step-1",
                execution_id="   ",
            )

    def test_non_string_execution_id_raises(self):
        with self.assertRaises(ValueError):
            ExecutionEvent(
                event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="step-1",
                execution_id=42,
            )


class TestEventTypes(unittest.TestCase):
    def test_all_documented_event_types_are_supported(self):
        expected = {
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
            EVENT_EXECUTION_CANCELLED,
            EVENT_AGENT_LOOP_STARTED,
            EVENT_AGENT_ITERATION_STARTED,
            EVENT_AGENT_EVALUATION_COMPLETED,
            EVENT_AGENT_EXECUTION_COMPLETED,
            EVENT_AGENT_LOOP_COMPLETED,
            EVENT_AGENT_LOOP_STOPPED,
            EVENT_AGENT_LOOP_FAILED,
        }
        self.assertEqual(expected, set(ALL_EVENT_TYPES))

    def test_every_event_type_can_construct_a_valid_event(self):
        for event_type in ALL_EVENT_TYPES:
            event = ExecutionEvent(event_type=event_type, plan_id="plan-1", step_id="step-1")
            self.assertEqual(event.event_type, event_type)

    def test_invalid_event_type_raises(self):
        with self.assertRaises(ValueError):
            ExecutionEvent(event_type="NOT_A_REAL_EVENT", plan_id="plan-1", step_id="step-1")

    def test_none_event_type_raises(self):
        with self.assertRaises(ValueError):
            ExecutionEvent(event_type=None, plan_id="plan-1", step_id="step-1")


class TestSeverity(unittest.TestCase):
    def test_all_documented_severities_are_supported(self):
        self.assertEqual({SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR}, set(ALL_SEVERITIES))

    def test_every_severity_can_construct_a_valid_event(self):
        for severity in ALL_SEVERITIES:
            event = ExecutionEvent(
                event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="step-1",
                severity=severity,
            )
            self.assertEqual(event.severity, severity)

    def test_invalid_severity_raises(self):
        with self.assertRaises(ValueError):
            ExecutionEvent(
                event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="step-1",
                severity="CRITICAL",
            )

    def test_default_severity_is_info(self):
        event = ExecutionEvent(
            event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="step-1",
        )
        self.assertEqual(event.severity, SEVERITY_INFO)


class TestStructuredData(unittest.TestCase):
    def test_safe_nested_data_is_accepted(self):
        event = ExecutionEvent(
            event_type=EVENT_OUTPUT_CREATED, plan_id="plan-1", step_id="step-1",
            data={"nested": {"a": [1, 2, {"b": None}]}},
            metadata={"tags": ["x", "y"]},
        )
        self.assertEqual(event.data, {"nested": {"a": [1, 2, {"b": None}]}})
        self.assertEqual(event.metadata, {"tags": ["x", "y"]})

    def test_data_containing_a_live_object_raises_type_error(self):
        class Unsafe:
            pass

        with self.assertRaises(TypeError):
            ExecutionEvent(
                event_type=EVENT_OUTPUT_CREATED, plan_id="plan-1", step_id="step-1",
                data={"bad": Unsafe()},
            )

    def test_metadata_containing_a_callable_raises_type_error(self):
        with self.assertRaises(TypeError):
            ExecutionEvent(
                event_type=EVENT_OUTPUT_CREATED, plan_id="plan-1", step_id="step-1",
                metadata={"bad": lambda: None},
            )

    def test_data_never_executed_or_evaluated(self):
        # A string that merely *looks* like code must be stored as an
        # inert string, never evaluated or executed.
        event = ExecutionEvent(
            event_type=EVENT_OUTPUT_CREATED, plan_id="plan-1", step_id="step-1",
            data={"payload": "__import__('os').system('echo pwned')"},
        )
        self.assertEqual(
            event.data["payload"], "__import__('os').system('echo pwned')"
        )

    def test_data_returned_from_to_dict_is_a_defensive_copy(self):
        event = ExecutionEvent(
            event_type=EVENT_OUTPUT_CREATED, plan_id="plan-1", step_id="step-1",
            data={"a": 1},
        )
        as_dict = event.to_dict()
        as_dict["data"]["a"] = 999
        self.assertEqual(event.data, {"a": 1})


class TestToDict(unittest.TestCase):
    def test_to_dict_contains_all_documented_fields(self):
        event = ExecutionEvent(
            event_type=EVENT_EXECUTION_COMPLETED,
            plan_id="plan-1",
            step_id="step-1",
            execution_id="execution-1",
            message="Done.",
            data={"k": "v"},
            severity=SEVERITY_INFO,
            metadata={"m": 1},
        )
        as_dict = event.to_dict()
        self.assertEqual(
            set(as_dict.keys()),
            {
                "event_id", "execution_id", "plan_id", "step_id", "event_type",
                "message", "timestamp", "data", "severity", "metadata",
            },
        )
        self.assertEqual(as_dict["plan_id"], "plan-1")
        self.assertEqual(as_dict["step_id"], "step-1")
        self.assertEqual(as_dict["execution_id"], "execution-1")
        self.assertEqual(as_dict["event_type"], EVENT_EXECUTION_COMPLETED)
        self.assertEqual(as_dict["message"], "Done.")
        self.assertEqual(as_dict["data"], {"k": "v"})
        self.assertEqual(as_dict["severity"], SEVERITY_INFO)
        self.assertEqual(as_dict["metadata"], {"m": 1})

    def test_to_dict_is_deterministic(self):
        event = ExecutionEvent(
            event_type=EVENT_EXECUTION_COMPLETED, plan_id="plan-1", step_id="step-1",
            event_id="fixed-id", timestamp="2024-01-01T00:00:00+00:00",
        )
        self.assertEqual(event.to_dict(), event.to_dict())


class TestIsError(unittest.TestCase):
    def test_error_severity_reports_true(self):
        event = ExecutionEvent(
            event_type=EVENT_EXECUTION_FAILED, plan_id="plan-1", step_id="step-1",
            severity=SEVERITY_ERROR,
        )
        self.assertTrue(event.is_error())

    def test_info_severity_reports_false(self):
        event = ExecutionEvent(
            event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="step-1",
            severity=SEVERITY_INFO,
        )
        self.assertFalse(event.is_error())

    def test_warning_severity_reports_false(self):
        event = ExecutionEvent(
            event_type=EVENT_EXECUTION_CREATED, plan_id="plan-1", step_id="step-1",
            severity=SEVERITY_WARNING,
        )
        self.assertFalse(event.is_error())


if __name__ == "__main__":
    unittest.main()
