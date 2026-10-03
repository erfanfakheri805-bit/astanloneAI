"""
Tests for the PlanStep input/output data-flow layer (added this
stage): PlanStep.set_input/set_output/get_input/get_output,
PlanManager.set_step_input/get_step_output, and the ExecutionEngine's
optional syncing of a successful ExecutionResult's output onto its
PlanStep's own output_data.

Covers: setting/getting step input and output directly on a PlanStep
and via PlanManager, structured dict/list data round-tripping intact,
rejection of non-serializable data, to_dict()/serialization staying
backward compatible, a successful execution storing output on the
step, a failed execution never creating a successful output, unknown
plan/step handling, and that none of this ever executes anything or
propagates data to another step automatically.

Run directly:
    python -m unittest tests.test_step_io -v
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
from planning.plan import PlanStep, STATUS_READY
from execution.execution_engine import ExecutionEngine


class _Unserializable:
    """A plain object with no JSON-safe shape - used to confirm
    input/output setters reject arbitrary Python objects."""
    pass


class TestPlanStepInputOutput(unittest.TestCase):
    def _step(self, **kwargs):
        return PlanStep(step_id="plan-1-step-1", description="Do the thing", **kwargs)

    def test_defaults_are_none(self):
        step = self._step()
        self.assertIsNone(step.get_input())
        self.assertIsNone(step.get_output())

    def test_set_and_get_input(self):
        step = self._step()
        step.set_input({"query": "weather"})
        self.assertEqual(step.get_input(), {"query": "weather"})

    def test_set_and_get_output(self):
        step = self._step()
        step.set_output({"result": "sunny"})
        self.assertEqual(step.get_output(), {"result": "sunny"})

    def test_structured_dict_and_list_data_round_trips(self):
        step = self._step()
        data = {
            "items": [1, 2, 3],
            "nested": {"a": [True, False, None], "b": "text"},
            "count": 3.5,
        }
        step.set_input(data)
        self.assertEqual(step.get_input(), data)
        # Defensive copy: mutating the caller's original doesn't reach
        # back into the step's stored state.
        data["items"].append(4)
        self.assertEqual(step.get_input()["items"], [1, 2, 3])

    def test_set_input_none_clears_existing_input(self):
        step = self._step()
        step.set_input({"a": 1})
        step.set_input(None)
        self.assertIsNone(step.get_input())

    def test_set_input_rejects_unserializable_object(self):
        step = self._step()
        with self.assertRaises(TypeError):
            step.set_input(_Unserializable())
        # Rejected assignment leaves prior state untouched.
        self.assertIsNone(step.get_input())

    def test_set_output_rejects_unserializable_nested_object(self):
        step = self._step()
        with self.assertRaises(TypeError):
            step.set_output({"ok": 1, "bad": _Unserializable()})
        self.assertIsNone(step.get_output())

    def test_set_input_rejects_non_string_dict_keys(self):
        step = self._step()
        with self.assertRaises(TypeError):
            step.set_input({1: "a"})

    def test_constructor_accepts_input_and_output_data(self):
        step = self._step(input_data={"x": 1}, output_data={"y": 2})
        self.assertEqual(step.get_input(), {"x": 1})
        self.assertEqual(step.get_output(), {"y": 2})

    def test_constructor_rejects_unserializable_input_data(self):
        with self.assertRaises(TypeError):
            self._step(input_data=_Unserializable())

    def test_existing_fields_not_overwritten(self):
        step = self._step(
            dependencies=["dep-1"], required_capabilities=["cap"],
            expected_output="a report", input_data={"x": 1},
        )
        self.assertEqual(step.dependencies, ["dep-1"])
        self.assertEqual(step.required_capabilities, ["cap"])
        self.assertEqual(step.expected_output, "a report")
        self.assertEqual(step.get_input(), {"x": 1})


class TestPlanStepSerializationCompatibility(unittest.TestCase):
    def test_to_dict_includes_existing_keys(self):
        step = PlanStep(step_id="s1", description="Do it")
        described = step.to_dict()
        for key in (
            "step_id", "description", "dependencies", "required_capabilities",
            "expected_output", "status",
        ):
            self.assertIn(key, described)

    def test_to_dict_includes_input_output_keys(self):
        step = PlanStep(step_id="s1", description="Do it")
        described = step.to_dict()
        self.assertIn("input_data", described)
        self.assertIn("output_data", described)
        self.assertIsNone(described["input_data"])
        self.assertIsNone(described["output_data"])

    def test_to_dict_reflects_set_input_output(self):
        step = PlanStep(step_id="s1", description="Do it")
        step.set_input({"a": 1})
        step.set_output({"b": 2})
        described = step.to_dict()
        self.assertEqual(described["input_data"], {"a": 1})
        self.assertEqual(described["output_data"], {"b": 2})

    def test_existing_step_construction_still_works_without_io(self):
        # Old-style construction (no input_data/output_data at all)
        # must still work exactly as before.
        step = PlanStep(
            step_id="s1", description="Do it", dependencies=["s0"],
            required_capabilities=["cap"], expected_output="thing",
        )
        self.assertEqual(step.dependencies, ["s0"])
        self.assertIsNone(step.get_input())
        self.assertIsNone(step.get_output())


class TestPlanManagerStepIO(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.goal = self.goals.create_goal("Ship the feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)
        self.step = self.plans.add_step(self.plan.plan_id, "Write tests")

    def test_set_step_input_stores_data(self):
        self.plans.set_step_input(self.plan.plan_id, self.step.step_id, {"a": 1})
        self.assertEqual(self.step.get_input(), {"a": 1})

    def test_get_step_output_returns_none_before_set(self):
        self.assertIsNone(self.plans.get_step_output(self.plan.plan_id, self.step.step_id))

    def test_get_step_output_returns_stored_output(self):
        self.step.set_output({"result": "done"})
        output = self.plans.get_step_output(self.plan.plan_id, self.step.step_id)
        self.assertEqual(output, {"result": "done"})

    def test_add_step_accepts_input_and_output_data(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Another step",
            input_data={"x": 1}, output_data={"y": 2},
        )
        self.assertEqual(step.get_input(), {"x": 1})
        self.assertEqual(step.get_output(), {"y": 2})

    def test_set_step_input_unknown_plan_raises(self):
        with self.assertRaises(ValueError):
            self.plans.set_step_input("no-such-plan", self.step.step_id, {"a": 1})

    def test_set_step_input_unknown_step_raises(self):
        with self.assertRaises(ValueError):
            self.plans.set_step_input(self.plan.plan_id, "no-such-step", {"a": 1})

    def test_get_step_output_unknown_plan_returns_none(self):
        self.assertIsNone(self.plans.get_step_output("no-such-plan", self.step.step_id))

    def test_get_step_output_unknown_step_returns_none(self):
        self.assertIsNone(self.plans.get_step_output(self.plan.plan_id, "no-such-step"))

    def test_set_step_input_rejects_unserializable_data(self):
        with self.assertRaises(TypeError):
            self.plans.set_step_input(self.plan.plan_id, self.step.step_id, _Unserializable())


class TestExecutionEngineOutputSync(unittest.TestCase):
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

    def test_successful_execution_stores_output_on_step(self):
        step = self._ready_step()
        handler = lambda s: {"answer": 42}
        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(result.output, {"answer": 42})
        self.assertEqual(step.get_output(), {"answer": 42})
        self.assertEqual(
            self.plans.get_step_output(self.plan.plan_id, step.step_id),
            {"answer": 42},
        )

    def test_failed_execution_does_not_create_successful_output(self):
        step = self._ready_step()

        def handler(s):
            raise RuntimeError("boom")

        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(result.status, "failed")
        self.assertIsNone(step.get_output())

    def test_sync_output_false_does_not_touch_step_output_data(self):
        step = self._ready_step()
        handler = lambda s: {"answer": 42}
        result = self.engine.execute_step(
            self.plan.plan_id, step.step_id, handler, sync_output=False,
        )

        self.assertEqual(result.output, {"answer": 42})
        self.assertIsNone(step.get_output())

    def test_unserializable_handler_output_is_not_synced_but_execution_still_succeeds(self):
        step = self._ready_step()
        handler = lambda s: _Unserializable()
        result = self.engine.execute_step(self.plan.plan_id, step.step_id, handler)

        self.assertEqual(result.status, "completed")
        self.assertIsNone(step.get_output())

    def test_no_automatic_execution_on_construction_or_plan_creation(self):
        # Creating a plan/step, or the engine itself, never runs
        # anything or produces any output on its own.
        step = self.plans.add_step(self.plan.plan_id, "Untouched step")
        self.assertIsNone(step.get_output())
        self.assertEqual(self.engine.history.list_for_step(self.plan.plan_id, step.step_id), [])

    def test_execute_step_never_propagates_output_to_another_step(self):
        first = self._ready_step("First step")
        second_step = self.plans.add_step(self.plan.plan_id, "Second step")

        handler = lambda s: {"value": "from-first"}
        self.engine.execute_step(self.plan.plan_id, first.step_id, handler)

        self.assertEqual(first.get_output(), {"value": "from-first"})
        self.assertIsNone(second_step.get_input())
        self.assertIsNone(second_step.get_output())


if __name__ == "__main__":
    unittest.main()
