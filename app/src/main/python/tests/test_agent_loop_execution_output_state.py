"""
Tests for Prompt 313: connecting the existing execution output back
into `AgentLoop` state (agent/agent_loop.py).

This stage adds no new model and no new execution path - it only
connects data `PlanExecutionController.execute_plan` (itself already
built on the existing, unmodified `ExecutionResult`/`ExecutionContext`
stack) already returns back into `AgentLoop.run()`'s own state, so a
step's own output - together with its own `execution_id` - is
available, unmodified, to the next pass of `run()`'s bounded `while`
loop and in the final result (see `AgentLoop._step_execution_outputs`/
`_result`'s own docstrings).

Covers:
  1. a successfully completed step's output is available to a later
     AgentLoop iteration within the same `run()` call;
  2. the recorded entry keeps the correct step_id;
  3. a failed execution never contributes a "successful output" entry;
  4. the output is transferred unmodified (identical value, including
     nested structured data);
  5. existing iteration limits (`max_iterations`/`max_steps_per_run`)
     are completely unchanged by this connection;
  6. every existing AgentLoop test remains compatible (the new
     `step_outputs` field is purely additive).

Run directly:
    python -m unittest tests.test_agent_loop_execution_output_state -v
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

from execution.plan_execution_controller import PlanExecutionController
from execution.execution_result import ExecutionResult

from agent.agent_loop import AgentLoop, STATUS_SATISFIED, STATUS_FAILED


class AgentLoopExecutionOutputStateTestBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.controller = PlanExecutionController(self.plans)
        self.loop = AgentLoop(self.goals, self.plans, self.controller)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _add_step(self, description="Do the thing", **kwargs):
        return self.plans.add_step(self.plan.plan_id, description, **kwargs)

    def _register_handler(self, capability_name, handler):
        self.controller.capability_handlers.register(capability_name, handler)


# --------------------------------------------------------------------
# 1. Successful step output is available to the next AgentLoop
#    iteration (within the same run() call).
# --------------------------------------------------------------------
class TestOutputAvailableToNextIteration(AgentLoopExecutionOutputStateTestBase):
    def test_first_iterations_output_survives_into_later_iterations(self):
        # One step per iteration (max_steps_per_run=1), so a 3-step
        # chain forces 3 separate AgentLoop iterations within one
        # run() call - exactly the scenario TestMaxIterationsGreaterThanOne
        # already exercises for iteration counting; here we check the
        # *output* survives across those same iterations.
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(self.goals, self.plans, controller)

        step1 = self._add_step("First", required_capabilities=["make_thing"])
        step2 = self._add_step(
            "Second", dependencies=[step1.step_id], required_capabilities=["make_thing"]
        )
        step3 = self._add_step("Third", dependencies=[step2.step_id])

        controller.capability_handlers.register("make_thing", lambda ctx: {"value": 1})

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=5)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], STATUS_SATISFIED)
        self.assertEqual(result["iterations"], 3)

        # step1 completed on iteration 1; by the time the loop
        # finishes (iteration 3), its output is still present,
        # unmodified (identical to the plain `outputs` entry
        # PlanExecutionController.execute_plan itself already
        # produced for it), having survived every later iteration.
        self.assertIn(step1.step_id, result["step_outputs"])
        self.assertEqual(
            result["step_outputs"][step1.step_id]["output"], result["outputs"][step1.step_id],
        )
        # step2 (iteration 2) is present too - this isn't a "keep only
        # the most recent" overwrite, every completed step accumulates.
        self.assertIn(step2.step_id, result["step_outputs"])

    def test_available_mid_run_before_the_run_call_returns(self):
        # Verify the connection is live *during* the loop, not just
        # assembled after the fact: a later step's own handler can
        # already see, via the plan's own existing data-flow wiring
        # (DataFlowManager.propagate_completed_step, run right after
        # step1 completes - see step_execution_controller.py's Prompt
        # 311 connection), the earlier step's output while the
        # AgentLoop run is still in progress - and that exact same
        # output is what ends up recorded in AgentLoop's own
        # step_outputs once the run finishes.
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(self.goals, self.plans, controller)

        seen = {}

        step1 = self._add_step("First", required_capabilities=["produce"])
        step2 = self._add_step(
            "Second", dependencies=[step1.step_id], required_capabilities=["consume"]
        )

        controller.capability_handlers.register("produce", lambda ctx: {"n": 7})

        def consume(step, context):
            seen["input"] = context.get_input()
            return {"consumed": True}

        controller.capability_handlers.register("consume", consume)

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=5)

        self.assertTrue(result["success"])
        self.assertEqual(seen["input"], result["step_outputs"][step1.step_id]["output"])


# --------------------------------------------------------------------
# 2. The recorded entry keeps the correct step_id (and its own,
#    correct execution_id).
# --------------------------------------------------------------------
class TestStepIdAndExecutionIdAreCorrect(AgentLoopExecutionOutputStateTestBase):
    def test_step_outputs_are_keyed_by_the_correct_step_id(self):
        step1 = self._add_step("First", required_capabilities=["a"])
        step2 = self._add_step(
            "Second", dependencies=[step1.step_id], required_capabilities=["b"]
        )
        self._register_handler("a", lambda ctx: {"who": "step1"})
        self._register_handler("b", lambda ctx: {"who": "step2"})

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["step_outputs"][step1.step_id]["step_id"], step1.step_id)
        self.assertEqual(result["step_outputs"][step2.step_id]["step_id"], step2.step_id)
        self.assertEqual(result["step_outputs"][step1.step_id]["output"], {"a": {"who": "step1"}})
        self.assertEqual(result["step_outputs"][step2.step_id]["output"], {"b": {"who": "step2"}})
        # Never cross-wired.
        self.assertNotEqual(
            result["step_outputs"][step1.step_id]["output"],
            result["step_outputs"][step2.step_id]["output"],
        )

    def test_execution_id_matches_the_real_recorded_execution_result(self):
        step = self._add_step("Only step", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda ctx: {"value": 99})

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        recorded = self.controller.history.latest_for_step(self.plan.plan_id, step.step_id)
        self.assertIsInstance(recorded, ExecutionResult)
        self.assertEqual(
            result["step_outputs"][step.step_id]["execution_id"], recorded.execution_id,
        )
        self.assertEqual(result["step_outputs"][step.step_id]["output"], recorded.output)

    def test_execution_id_is_never_none_for_a_completed_step(self):
        step = self._add_step("Only step", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda ctx: {"value": 1})

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertIsNotNone(result["step_outputs"][step.step_id]["execution_id"])


# --------------------------------------------------------------------
# 3. Failed execution does not provide a successful output.
# --------------------------------------------------------------------
class TestFailedExecutionProvidesNoOutput(AgentLoopExecutionOutputStateTestBase):
    def test_failed_step_has_no_entry_in_step_outputs(self):
        step = self._add_step("Will fail", required_capabilities=["boom"])
        self._register_handler(
            "boom", lambda ctx: (_ for _ in ()).throw(RuntimeError("kaboom"))
        )

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertNotIn(step.step_id, result["step_outputs"])
        self.assertEqual(result["step_outputs"], {})

    def test_completed_step_before_a_later_failure_keeps_its_own_output_only(self):
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(self.goals, self.plans, controller)

        step1 = self._add_step("Succeeds", required_capabilities=["ok"])
        step2 = self._add_step(
            "Fails", dependencies=[step1.step_id], required_capabilities=["boom"]
        )

        controller.capability_handlers.register("ok", lambda ctx: {"value": 1})
        controller.capability_handlers.register(
            "boom", lambda ctx: (_ for _ in ()).throw(RuntimeError("kaboom"))
        )

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=5)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], STATUS_FAILED)
        # step1's own output is preserved even though the run overall
        # ends in failure ...
        self.assertIn(step1.step_id, result["step_outputs"])
        # ... but step2 (the one that failed) never contributes one.
        self.assertNotIn(step2.step_id, result["step_outputs"])

    def test_no_handler_registered_never_produces_a_phantom_output(self):
        self._add_step("Stuck", required_capabilities=["missing_capability"])
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["step_outputs"], {})


# --------------------------------------------------------------------
# 4. Output is not modified during transfer.
# --------------------------------------------------------------------
class TestOutputIsNotModifiedDuringTransfer(AgentLoopExecutionOutputStateTestBase):
    def test_structured_dict_output_transfers_unchanged(self):
        payload = {"items": [1, 2, 3], "nested": {"a": [True, False, None]}, "n": 7}
        step = self._add_step("Only step", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda ctx: payload)

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        # The engine wraps a single handler's return value as
        # {capability_name: value} (pre-existing, unrelated to this
        # stage) - the payload itself must still come through intact.
        self.assertEqual(
            result["step_outputs"][step.step_id]["output"]["make_thing"], payload,
        )

    def test_output_equals_the_underlying_execution_results_output_exactly(self):
        step = self._add_step("Only step", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda ctx: {"a": 1, "b": [1, 2]})

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        recorded = self.controller.history.latest_for_step(self.plan.plan_id, step.step_id)
        self.assertEqual(result["step_outputs"][step.step_id]["output"], recorded.output)
        # Also unchanged relative to the plain outputs dict this stage
        # never alters (requirement: backward compatible).
        self.assertEqual(result["outputs"][step.step_id], result["step_outputs"][step.step_id]["output"])

    def test_string_and_scalar_outputs_transfer_unchanged(self):
        step = self._add_step("Only step", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda ctx: "plain string output")

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(
            result["step_outputs"][step.step_id]["output"]["make_thing"],
            "plain string output",
        )


# --------------------------------------------------------------------
# 5. Existing iteration limits remain unchanged.
# --------------------------------------------------------------------
class TestIterationLimitsUnchanged(AgentLoopExecutionOutputStateTestBase):
    def test_max_iterations_still_enforced_with_outputs_present(self):
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(self.goals, self.plans, controller)
        step1 = self._add_step("First", required_capabilities=["make_thing"])
        step2 = self._add_step(
            "Second", dependencies=[step1.step_id], required_capabilities=["make_thing"]
        )
        controller.capability_handlers.register("make_thing", lambda ctx: {"value": 1})

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        # Same cap-respecting behavior as before this stage: only one
        # iteration ran, only one step executed, even though its
        # output is now also tracked in step_outputs.
        self.assertEqual(result["iterations"], 1)
        self.assertEqual(result["executed_steps"], [step1.step_id])
        self.assertIn(step1.step_id, result["step_outputs"])
        self.assertNotIn(step2.step_id, result["step_outputs"])

    def test_invalid_max_iterations_still_raises(self):
        with self.assertRaises(ValueError):
            self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=0)
        with self.assertRaises(ValueError):
            self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=-1)
        with self.assertRaises(ValueError):
            self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=True)

    def test_max_steps_per_run_safety_cap_still_enforced(self):
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(self.goals, self.plans, controller)
        step1 = self._add_step("First")
        step2 = self._add_step("Second", dependencies=[step1.step_id])

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        from agent.agent_loop import STATUS_MAX_ITERATIONS_REACHED
        self.assertEqual(result["status"], STATUS_MAX_ITERATIONS_REACHED)
        self.assertEqual(result["executed_steps"], [step1.step_id])

    def test_no_step_executed_automatically_beyond_plan_execution_controllers_own_run(self):
        # This connection never triggers extra execution on its own -
        # a single-step plan still executes exactly one step in one
        # iteration, exactly as before.
        step = self._add_step("Only step")
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=5)
        self.assertEqual(result["executed_steps"], [step.step_id])
        self.assertEqual(result["iterations"], 1)


# --------------------------------------------------------------------
# 6. Existing tests / result shape remain compatible.
# --------------------------------------------------------------------
class TestBackwardCompatibility(AgentLoopExecutionOutputStateTestBase):
    def test_result_still_contains_every_previously_existing_key(self):
        step = self._add_step("Only step")
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)
        for key in (
            "success", "goal_id", "plan_id", "status", "iterations", "goal_status",
            "executed_steps", "completed_steps", "failed_steps", "blocked_steps",
            "outputs", "evidence", "warnings", "error", "learning_context", "next_step",
        ):
            self.assertIn(key, result)

    def test_plain_outputs_dict_is_unchanged_in_shape_and_content(self):
        step = self._add_step("Only step", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda ctx: {"value": 5})

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertIsInstance(result["outputs"], dict)
        self.assertEqual(result["outputs"], {step.step_id: {"make_thing": {"value": 5}}})

    def test_step_outputs_defaults_to_empty_dict_for_invalid_input(self):
        result = self.loop.run("no-such-goal", self.plan.plan_id)
        self.assertIn("step_outputs", result)
        self.assertEqual(result["step_outputs"], {})

    def test_step_outputs_defaults_to_empty_dict_when_goal_already_satisfied(self):
        step = self._add_step("Only step")
        self.plans.update_step_status(
            self.plan.plan_id, step.step_id,
            __import__("planning.plan", fromlist=["STATUS_COMPLETED"]).STATUS_COMPLETED,
        )
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["step_outputs"], {})

    def test_no_new_execution_result_model_field_introduced(self):
        # ExecutionResult itself must remain untouched: still exactly
        # its original slot set.
        self.assertEqual(
            set(ExecutionResult.__slots__),
            {
                "execution_id", "plan_id", "step_id", "status", "output", "error",
                "started_at", "finished_at", "metadata", "capability_outputs",
            },
        )


if __name__ == "__main__":
    unittest.main()
