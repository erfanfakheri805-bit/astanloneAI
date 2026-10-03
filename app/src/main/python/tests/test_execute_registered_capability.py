"""
Tests for ExecutionEngine.execute_registered_capability
(execution/execution_engine.py) - running one registered `Capability`
(execution/capability.py), looked up from
`self.executable_capabilities` (an `ExecutableCapabilityRegistry` -
execution/executable_registry.py), directly against caller-supplied
input, with no PlanStep involved at all.

Covers: successful execution, a missing capability, a disabled
capability, an invalid handler, invalid input, successful output,
handler failure, ExecutionResult contents, ExecutionHistory recording,
the handler receiving the correct input, and the handler never being
called when validation fails.

Run directly:
    python -m unittest tests.test_execute_registered_capability -v
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
from execution.execution_engine import ExecutionEngine, CAPABILITY_EXECUTION_PLAN_ID
from execution.execution_result import (
    STATUS_COMPLETED as EXEC_STATUS_COMPLETED, STATUS_FAILED as EXEC_STATUS_FAILED,
)
from execution.capability import Capability

GREET_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string", "required": True}},
}


def _echo(data):
    return {"received": data}


class TestExecuteRegisteredCapabilityBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.engine = ExecutionEngine(self.plans)


# ----------------------------------------------------------------------
# Successful execution
# ----------------------------------------------------------------------
class TestSuccessfulExecution(TestExecuteRegisteredCapabilityBase):
    def test_execute_registered_capability_completes(self):
        self.engine.executable_capabilities.register(
            Capability("greet", _echo, input_schema=GREET_SCHEMA)
        )

        result = self.engine.execute_registered_capability("greet", {"name": "Erfan"})

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertIsNone(result.error)

    def test_successful_output_matches_handler_return_value(self):
        self.engine.executable_capabilities.register(
            Capability("greet", _echo, input_schema=GREET_SCHEMA)
        )

        result = self.engine.execute_registered_capability("greet", {"name": "Erfan"})

        self.assertEqual(result.output, {"received": {"name": "Erfan"}})

    def test_no_schema_capability_still_executes(self):
        self.engine.executable_capabilities.register(Capability("greet", _echo))

        result = self.engine.execute_registered_capability("greet", {"anything": 1})

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(result.output, {"received": {"anything": 1}})


# ----------------------------------------------------------------------
# Missing capability
# ----------------------------------------------------------------------
class TestMissingCapability(TestExecuteRegisteredCapabilityBase):
    def test_missing_capability_returns_a_failed_result(self):
        result = self.engine.execute_registered_capability("never_registered", {})
        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertIn("never_registered", result.error)

    def test_missing_capability_never_raises(self):
        try:
            self.engine.execute_registered_capability("never_registered", {})
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"execute_registered_capability raised for a missing capability: {exc}")

    def test_missing_capability_is_still_recorded_in_history(self):
        result = self.engine.execute_registered_capability("never_registered", {})
        self.assertIs(self.engine.history.get(result.execution_id), result)


# ----------------------------------------------------------------------
# Disabled capability
# ----------------------------------------------------------------------
class TestDisabledCapability(TestExecuteRegisteredCapabilityBase):
    def test_disabled_capability_returns_a_failed_result(self):
        self.engine.executable_capabilities.register(
            Capability("greet", _echo), enabled=False
        )
        result = self.engine.execute_registered_capability("greet", {"name": "Erfan"})
        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertIn("disabled", result.error.lower())

    def test_disabled_capability_never_calls_the_handler(self):
        calls = []

        def handler(data):
            calls.append(data)
            return data

        self.engine.executable_capabilities.register(
            Capability("greet", handler), enabled=False
        )
        self.engine.execute_registered_capability("greet", {"name": "Erfan"})
        self.assertEqual(calls, [])


# ----------------------------------------------------------------------
# Invalid handler
# ----------------------------------------------------------------------
class TestInvalidHandler(TestExecuteRegisteredCapabilityBase):
    def test_handler_mutated_to_non_callable_is_refused(self):
        capability = Capability("greet", _echo)
        self.engine.executable_capabilities.register(capability)
        # A Capability's handler is a plain, mutable attribute - mutate
        # it after registration to simulate an invalid handler.
        capability.handler = "not-callable-anymore"

        result = self.engine.execute_registered_capability("greet", {"name": "Erfan"})

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertIn("handler", result.error.lower())


# ----------------------------------------------------------------------
# Invalid input
# ----------------------------------------------------------------------
class TestInvalidInput(TestExecuteRegisteredCapabilityBase):
    def setUp(self):
        super().setUp()
        self.engine.executable_capabilities.register(
            Capability("greet", _echo, input_schema=GREET_SCHEMA)
        )

    def test_invalid_input_returns_a_failed_result(self):
        result = self.engine.execute_registered_capability("greet", {})
        self.assertEqual(result.status, EXEC_STATUS_FAILED)

    def test_invalid_input_never_reaches_the_handler(self):
        calls = []

        def handler(data):
            calls.append(data)
            return data

        self.engine.executable_capabilities.register(
            Capability("strict_greet", handler, input_schema=GREET_SCHEMA)
        )
        self.engine.execute_registered_capability("strict_greet", {})
        self.assertEqual(calls, [])

    def test_invalid_input_validation_details_are_captured(self):
        result = self.engine.execute_registered_capability("greet", {})
        self.assertFalse(result.metadata["validation"]["valid"])
        self.assertTrue(
            any(err["field"] == "name" for err in result.metadata["validation"]["errors"])
        )


# ----------------------------------------------------------------------
# Handler failure
# ----------------------------------------------------------------------
class TestHandlerFailure(TestExecuteRegisteredCapabilityBase):
    def test_handler_exception_becomes_a_failed_result(self):
        def failing_handler(data):
            raise RuntimeError("boom")

        self.engine.executable_capabilities.register(Capability("greet", failing_handler))

        result = self.engine.execute_registered_capability("greet", {})

        self.assertEqual(result.status, EXEC_STATUS_FAILED)
        self.assertIn("RuntimeError", result.error)
        self.assertIn("boom", result.error)

    def test_handler_exception_never_propagates(self):
        def failing_handler(data):
            raise ValueError("nope")

        self.engine.executable_capabilities.register(Capability("greet", failing_handler))

        try:
            result = self.engine.execute_registered_capability("greet", {})
        except ValueError:
            self.fail("execute_registered_capability must not let a handler's exception propagate.")
        self.assertEqual(result.status, EXEC_STATUS_FAILED)


# ----------------------------------------------------------------------
# ExecutionResult contents
# ----------------------------------------------------------------------
class TestExecutionResultContents(TestExecuteRegisteredCapabilityBase):
    def test_result_carries_capability_name_and_synthetic_plan_step_ids(self):
        self.engine.executable_capabilities.register(
            Capability("greet", _echo, input_schema=GREET_SCHEMA)
        )

        result = self.engine.execute_registered_capability("greet", {"name": "Erfan"})

        self.assertEqual(result.plan_id, CAPABILITY_EXECUTION_PLAN_ID)
        self.assertEqual(result.step_id, "greet")
        self.assertEqual(result.metadata["capability_name"], "greet")

    def test_result_carries_validation_result(self):
        self.engine.executable_capabilities.register(
            Capability("greet", _echo, input_schema=GREET_SCHEMA)
        )

        result = self.engine.execute_registered_capability("greet", {"name": "Erfan"})

        self.assertIn("validation", result.metadata)
        self.assertTrue(result.metadata["validation"]["valid"])

    def test_result_carries_timing(self):
        self.engine.executable_capabilities.register(Capability("greet", _echo))

        result = self.engine.execute_registered_capability("greet", {})

        self.assertIsNotNone(result.started_at)
        self.assertIsNotNone(result.finished_at)
        self.assertIsNotNone(result.duration)

    def test_result_has_a_unique_execution_id(self):
        self.engine.executable_capabilities.register(Capability("greet", _echo))
        result = self.engine.execute_registered_capability("greet", {})
        self.assertTrue(result.execution_id)


# ----------------------------------------------------------------------
# ExecutionHistory recording
# ----------------------------------------------------------------------
class TestExecutionHistoryRecording(TestExecuteRegisteredCapabilityBase):
    def test_successful_execution_is_recorded(self):
        self.engine.executable_capabilities.register(Capability("greet", _echo))
        result = self.engine.execute_registered_capability("greet", {})
        self.assertIs(self.engine.history.get(result.execution_id), result)

    def test_failed_execution_is_recorded(self):
        result = self.engine.execute_registered_capability("never_registered", {})
        self.assertIs(self.engine.history.get(result.execution_id), result)

    def test_history_can_be_looked_up_by_capability_name_as_step_id(self):
        self.engine.executable_capabilities.register(Capability("greet", _echo))
        self.engine.execute_registered_capability("greet", {})
        self.engine.execute_registered_capability("greet", {})

        records = self.engine.history.list_for_step(CAPABILITY_EXECUTION_PLAN_ID, "greet")
        self.assertEqual(len(records), 2)

    def test_multiple_calls_each_get_their_own_history_entry(self):
        self.engine.executable_capabilities.register(Capability("greet", _echo))
        first = self.engine.execute_registered_capability("greet", {})
        second = self.engine.execute_registered_capability("greet", {})
        self.assertNotEqual(first.execution_id, second.execution_id)
        self.assertIs(self.engine.history.get(first.execution_id), first)
        self.assertIs(self.engine.history.get(second.execution_id), second)


# ----------------------------------------------------------------------
# Handler receives correct input / is not called on invalid input
# ----------------------------------------------------------------------
class TestHandlerReceivesCorrectInput(TestExecuteRegisteredCapabilityBase):
    def test_handler_receives_exactly_the_supplied_input_data(self):
        received = []

        def handler(data):
            received.append(data)
            return "ok"

        self.engine.executable_capabilities.register(
            Capability("greet", handler, input_schema=GREET_SCHEMA)
        )

        self.engine.execute_registered_capability("greet", {"name": "Erfan"})

        self.assertEqual(received, [{"name": "Erfan"}])

    def test_handler_not_called_when_validation_fails(self):
        received = []

        def handler(data):
            received.append(data)
            return "ok"

        self.engine.executable_capabilities.register(
            Capability("greet", handler, input_schema=GREET_SCHEMA)
        )

        self.engine.execute_registered_capability("greet", {})

        self.assertEqual(received, [])

    def test_handler_not_called_for_missing_or_disabled_capability(self):
        received = []

        def handler(data):
            received.append(data)
            return "ok"

        self.engine.executable_capabilities.register(
            Capability("bye", handler), enabled=False
        )

        self.engine.execute_registered_capability("never_registered", {})
        self.engine.execute_registered_capability("bye", {})

        self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()
