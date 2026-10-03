"""
Tests for ExecutionContext (execution/execution_context.py) - a
small, safe, structured runtime-context record for one execution
attempt, plus its backward-compatible integration into
ExecutionEngine.execute_capability_step (execution/execution_engine.py).

Covers: context creation, required identifiers, input data, previous
outputs, metadata, get(), default values, add_previous_output(),
set_metadata(), to_dict(), missing optional values, identifier
protection, and backward compatibility with existing (single-argument)
capability handlers.

Run directly:
    python -m unittest tests.test_execution_context -v
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
from planning.plan import STATUS_READY, STATUS_COMPLETED
from execution.execution_context import (
    ExecutionContext,
    PROTECTED_IDENTIFIER_KEYS,
    call_handler_with_context,
)
from execution.execution_engine import ExecutionEngine
from execution.execution_result import STATUS_COMPLETED as EXEC_STATUS_COMPLETED


class _Unserializable:
    """A plain object that can never pass ensure_structured_data -
    same helper other tests in this project already use for this
    purpose (see tests/test_step_io.py)."""
    pass


class TestContextCreation(unittest.TestCase):
    def test_creates_with_required_identifiers(self):
        context = ExecutionContext(plan_id="plan-1", step_id="plan-1-step-1")
        self.assertEqual(context.plan_id, "plan-1")
        self.assertEqual(context.step_id, "plan-1-step-1")
        self.assertIsNotNone(context.execution_id)
        self.assertIsNotNone(context.created_at)

    def test_auto_generated_execution_ids_are_unique(self):
        a = ExecutionContext(plan_id="plan-1", step_id="step-1")
        b = ExecutionContext(plan_id="plan-1", step_id="step-1")
        self.assertNotEqual(a.execution_id, b.execution_id)

    def test_explicit_execution_id_is_respected(self):
        context = ExecutionContext(
            plan_id="plan-1", step_id="step-1", execution_id="exec-fixed-1",
        )
        self.assertEqual(context.execution_id, "exec-fixed-1")


class TestRequiredIdentifiers(unittest.TestCase):
    def test_missing_plan_id_raises(self):
        with self.assertRaises(ValueError):
            ExecutionContext(plan_id="", step_id="step-1")

    def test_missing_step_id_raises(self):
        with self.assertRaises(ValueError):
            ExecutionContext(plan_id="plan-1", step_id="")

    def test_non_string_plan_id_raises(self):
        with self.assertRaises(ValueError):
            ExecutionContext(plan_id=123, step_id="step-1")

    def test_non_string_capability_name_raises(self):
        with self.assertRaises(TypeError):
            ExecutionContext(plan_id="plan-1", step_id="step-1", capability_name=123)


class TestInputData(unittest.TestCase):
    def test_stores_and_returns_input_data(self):
        context = ExecutionContext(
            plan_id="plan-1", step_id="step-1", input_data={"query": "weather"},
        )
        self.assertEqual(context.get_input(), {"query": "weather"})

    def test_rejects_unserializable_input_data(self):
        with self.assertRaises(TypeError):
            ExecutionContext(
                plan_id="plan-1", step_id="step-1", input_data=_Unserializable(),
            )

    def test_input_data_defaults_to_none(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        self.assertIsNone(context.get_input())


class TestPreviousOutputs(unittest.TestCase):
    def test_stores_and_returns_previous_outputs(self):
        context = ExecutionContext(
            plan_id="plan-1", step_id="step-1",
            previous_outputs={"step-0": {"result": "ok"}},
        )
        self.assertEqual(context.get_previous_outputs(), {"step-0": {"result": "ok"}})

    def test_get_previous_outputs_returns_a_defensive_copy(self):
        context = ExecutionContext(
            plan_id="plan-1", step_id="step-1",
            previous_outputs={"step-0": "value"},
        )
        snapshot = context.get_previous_outputs()
        snapshot["step-0"] = "mutated"
        self.assertEqual(context.get_previous_outputs(), {"step-0": "value"})

    def test_rejects_non_dict_previous_outputs(self):
        with self.assertRaises(TypeError):
            ExecutionContext(plan_id="plan-1", step_id="step-1", previous_outputs="nope")

    def test_rejects_unserializable_previous_output_value(self):
        with self.assertRaises(TypeError):
            ExecutionContext(
                plan_id="plan-1", step_id="step-1",
                previous_outputs={"step-0": _Unserializable()},
            )

    def test_previous_outputs_defaults_to_empty_dict(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        self.assertEqual(context.get_previous_outputs(), {})


class TestMetadata(unittest.TestCase):
    def test_constructor_metadata_is_stored(self):
        context = ExecutionContext(
            plan_id="plan-1", step_id="step-1", metadata={"attempt": 1},
        )
        self.assertEqual(context.get_metadata(), {"attempt": 1})

    def test_get_metadata_returns_a_defensive_copy(self):
        context = ExecutionContext(
            plan_id="plan-1", step_id="step-1", metadata={"attempt": 1},
        )
        snapshot = context.get_metadata()
        snapshot["attempt"] = 999
        self.assertEqual(context.get_metadata(), {"attempt": 1})

    def test_metadata_rejects_unserializable_value(self):
        with self.assertRaises(TypeError):
            ExecutionContext(
                plan_id="plan-1", step_id="step-1",
                metadata={"bad": _Unserializable()},
            )

    def test_metadata_defaults_to_empty_dict(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        self.assertEqual(context.get_metadata(), {})

    def test_constructor_metadata_rejects_protected_key(self):
        with self.assertRaises(ValueError):
            ExecutionContext(
                plan_id="plan-1", step_id="step-1", metadata={"plan_id": "hijack"},
            )


class TestGet(unittest.TestCase):
    def setUp(self):
        self.context = ExecutionContext(
            plan_id="plan-1", step_id="step-1", capability_name="send_email",
            input_data={"to": "a@example.com"},
            previous_outputs={"step-0": "done"},
            metadata={"attempt": 2},
        )

    def test_get_metadata_key(self):
        self.assertEqual(self.context.get("attempt"), 2)

    def test_get_identifier_keys(self):
        self.assertEqual(self.context.get("plan_id"), "plan-1")
        self.assertEqual(self.context.get("step_id"), "step-1")
        self.assertEqual(self.context.get("capability_name"), "send_email")
        self.assertEqual(self.context.get("execution_id"), self.context.execution_id)

    def test_get_input_data_and_previous_outputs_keys(self):
        self.assertEqual(self.context.get("input_data"), {"to": "a@example.com"})
        self.assertEqual(self.context.get("previous_outputs"), {"step-0": "done"})

    def test_get_unknown_key_returns_default(self):
        self.assertIsNone(self.context.get("does_not_exist"))
        self.assertEqual(self.context.get("does_not_exist", "fallback"), "fallback")

    def test_get_never_raises_for_unknown_key(self):
        try:
            self.context.get("totally_unknown")
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get() raised unexpectedly: {exc}")


class TestAddPreviousOutput(unittest.TestCase):
    def test_adds_a_new_entry(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        context.add_previous_output("step-0", {"value": 42})
        self.assertEqual(context.get_previous_outputs(), {"step-0": {"value": 42}})

    def test_overwrites_existing_entry(self):
        context = ExecutionContext(
            plan_id="plan-1", step_id="step-1", previous_outputs={"step-0": "old"},
        )
        context.add_previous_output("step-0", "new")
        self.assertEqual(context.get_previous_outputs(), {"step-0": "new"})

    def test_returns_self_for_chaining(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        returned = context.add_previous_output("step-0", "value")
        self.assertIs(returned, context)

    def test_rejects_empty_step_id(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        with self.assertRaises(ValueError):
            context.add_previous_output("", "value")

    def test_rejects_unserializable_output(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        with self.assertRaises(TypeError):
            context.add_previous_output("step-0", _Unserializable())

    def test_allows_none_output(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        context.add_previous_output("step-0", None)
        self.assertEqual(context.get_previous_outputs(), {"step-0": None})


class TestSetMetadata(unittest.TestCase):
    def test_sets_a_new_key(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        context.set_metadata("attempt", 1)
        self.assertEqual(context.get_metadata(), {"attempt": 1})

    def test_overwrites_existing_key(self):
        context = ExecutionContext(
            plan_id="plan-1", step_id="step-1", metadata={"attempt": 1},
        )
        context.set_metadata("attempt", 2)
        self.assertEqual(context.get_metadata(), {"attempt": 2})

    def test_returns_self_for_chaining(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        returned = context.set_metadata("attempt", 1)
        self.assertIs(returned, context)

    def test_rejects_empty_key(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        with self.assertRaises(ValueError):
            context.set_metadata("", 1)

    def test_rejects_unserializable_value(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        with self.assertRaises(TypeError):
            context.set_metadata("bad", _Unserializable())


class TestToDict(unittest.TestCase):
    def test_shape_and_values(self):
        context = ExecutionContext(
            plan_id="plan-1", step_id="step-1", capability_name="send_email",
            input_data={"to": "a@example.com"},
            previous_outputs={"step-0": "done"},
            metadata={"attempt": 1},
        )
        data = context.to_dict()
        self.assertEqual(data["plan_id"], "plan-1")
        self.assertEqual(data["step_id"], "step-1")
        self.assertEqual(data["capability_name"], "send_email")
        self.assertEqual(data["input_data"], {"to": "a@example.com"})
        self.assertEqual(data["previous_outputs"], {"step-0": "done"})
        self.assertEqual(data["metadata"], {"attempt": 1})
        self.assertEqual(data["execution_id"], context.execution_id)
        self.assertEqual(data["created_at"], context.created_at)

    def test_to_dict_always_has_all_keys_even_when_empty(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        data = context.to_dict()
        for key in (
            "execution_id", "plan_id", "step_id", "capability_name",
            "input_data", "previous_outputs", "metadata", "created_at",
        ):
            self.assertIn(key, data)

    def test_to_dict_previous_outputs_and_metadata_are_copies(self):
        context = ExecutionContext(
            plan_id="plan-1", step_id="step-1", previous_outputs={"a": 1},
        )
        data = context.to_dict()
        data["previous_outputs"]["a"] = 999
        self.assertEqual(context.get_previous_outputs(), {"a": 1})


class TestMissingOptionalValues(unittest.TestCase):
    def test_only_required_identifiers_are_needed(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        self.assertIsNone(context.capability_name)
        self.assertIsNone(context.get_input())
        self.assertEqual(context.get_previous_outputs(), {})
        self.assertEqual(context.get_metadata(), {})


class TestIdentifierProtection(unittest.TestCase):
    def test_protected_keys_constant_matches_expected_fields(self):
        self.assertEqual(
            PROTECTED_IDENTIFIER_KEYS,
            frozenset({"execution_id", "plan_id", "step_id", "capability_name"}),
        )

    def test_set_metadata_rejects_every_protected_key(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        for key in PROTECTED_IDENTIFIER_KEYS:
            with self.assertRaises(ValueError):
                context.set_metadata(key, "hijacked")

    def test_identifiers_unchanged_after_failed_metadata_attempt(self):
        context = ExecutionContext(
            plan_id="plan-1", step_id="step-1", capability_name="send_email",
        )
        original_execution_id = context.execution_id
        try:
            context.set_metadata("plan_id", "hijacked")
        except ValueError:
            pass
        self.assertEqual(context.plan_id, "plan-1")
        self.assertEqual(context.step_id, "step-1")
        self.assertEqual(context.capability_name, "send_email")
        self.assertEqual(context.execution_id, original_execution_id)

    def test_no_public_setter_exists_for_identifiers(self):
        context = ExecutionContext(plan_id="plan-1", step_id="step-1")
        with self.assertRaises(AttributeError):
            context.plan_id = "hijacked"
        with self.assertRaises(AttributeError):
            context.step_id = "hijacked"
        with self.assertRaises(AttributeError):
            context.execution_id = "hijacked"
        with self.assertRaises(AttributeError):
            context.capability_name = "hijacked"

    def test_constructor_metadata_cannot_smuggle_in_an_identifier(self):
        with self.assertRaises(ValueError):
            ExecutionContext(
                plan_id="plan-1", step_id="step-1",
                metadata={"execution_id": "hijacked"},
            )


class TestCallHandlerWithContext(unittest.TestCase):
    def setUp(self):
        self.context = ExecutionContext(plan_id="plan-1", step_id="step-1")

    def test_single_argument_handler_receives_only_step(self):
        received = {}

        def handler(step):
            received["step"] = step
            return "ok"

        result = call_handler_with_context(handler, "the-step", self.context)
        self.assertEqual(result, "ok")
        self.assertEqual(received["step"], "the-step")

    def test_two_argument_handler_receives_step_and_context(self):
        received = {}

        def handler(step, context):
            received["step"] = step
            received["context"] = context
            return "ok"

        result = call_handler_with_context(handler, "the-step", self.context)
        self.assertEqual(result, "ok")
        self.assertEqual(received["step"], "the-step")
        self.assertIs(received["context"], self.context)

    def test_lambda_handler_still_works(self):
        result = call_handler_with_context(lambda step: f"handled {step}", "s1", self.context)
        self.assertEqual(result, "handled s1")


class TestExecutionEngineBackwardCompatibility(unittest.TestCase):
    """Integration: ExecutionEngine.execute_capability_step must
    continue to work unchanged for existing, single-argument
    handlers, while a new, context-aware handler transparently
    receives an ExecutionContext."""

    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.engine = ExecutionEngine(self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _ready_step(self, **kwargs):
        step = self.plans.add_step(self.plan.plan_id, "Do a thing", **kwargs)
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        return step

    def test_existing_single_argument_handler_still_works(self):
        step = self._ready_step(required_capabilities=["send_email"])
        self.engine.capability_handlers.register(
            "send_email", lambda plan_step: f"sent for {plan_step.step_id}"
        )

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(result.output, {"send_email": f"sent for {step.step_id}"})
        self.assertEqual(
            self.plans.get_step(self.plan.plan_id, step.step_id).status,
            STATUS_COMPLETED,
        )

    def test_context_aware_handler_receives_a_real_execution_context(self):
        step = self._ready_step(
            required_capabilities=["send_email"], input_data={"to": "a@example.com"},
        )
        captured = {}

        def handler(plan_step, context):
            captured["plan_step"] = plan_step
            captured["context"] = context
            return "sent"

        self.engine.capability_handlers.register("send_email", handler)

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertIs(captured["plan_step"], step)
        context = captured["context"]
        self.assertIsInstance(context, ExecutionContext)
        self.assertEqual(context.plan_id, self.plan.plan_id)
        self.assertEqual(context.step_id, step.step_id)
        self.assertEqual(context.capability_name, "send_email")
        self.assertEqual(context.get_input(), {"to": "a@example.com"})

    def test_context_execution_id_matches_the_execution_result(self):
        step = self._ready_step(required_capabilities=["send_email"])
        captured = {}

        def handler(plan_step, context):
            captured["execution_id"] = context.execution_id
            return "sent"

        self.engine.capability_handlers.register("send_email", handler)

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(captured["execution_id"], result.execution_id)

    def test_second_handler_sees_first_handlers_output_as_previous_output(self):
        step = self._ready_step(required_capabilities=["first", "second"])
        captured = {}

        self.engine.capability_handlers.register("first", lambda s: "first-output")

        def second_handler(plan_step, context):
            captured["previous"] = context.get_previous_outputs()
            return "second-output"

        self.engine.capability_handlers.register("second", second_handler)

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(captured["previous"], {"first": "first-output"})

    def test_capability_step_never_auto_executes_another_step(self):
        first = self._ready_step(required_capabilities=["send_email"])
        second = self.plans.add_step(self.plan.plan_id, "Second step")

        self.engine.capability_handlers.register("send_email", lambda s: "sent")
        self.engine.execute_capability_step(self.plan.plan_id, first.step_id)

        # The second step was never executed automatically.
        self.assertNotEqual(
            self.plans.get_step(self.plan.plan_id, second.step_id).status,
            STATUS_COMPLETED,
        )
        self.assertEqual(self.engine.history.list_for_step(self.plan.plan_id, second.step_id), [])


if __name__ == "__main__":
    unittest.main()
