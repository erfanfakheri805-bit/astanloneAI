"""Prompt 691 - controlled plan step execution orchestration. Pure in-memory tests."""
import ast
import copy
import hashlib
import os
import unittest

from planning import plan_step_orchestration as orch
from planning.plan import Plan, PlanStep
from planning.plan_builder import evaluate_plan_progress, get_ready_plan_steps, validate_plan_step_states
from planning.plan_status_rollup import rollup_plan_status
from planning.plan_step_execution import complete_plan_step, start_plan_step
from planning.plan_step_orchestration import execute_plan_step
from planning.plan_validation import validate_plan

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def mk(authorized=True, executed=False):
    steps = [PlanStep("step-001", "a", input_data={"n": 1}, expected_output="num",
                      required_capabilities=["cap.x"]),
             PlanStep("step-002", "b", dependencies=["step-001"]),
             PlanStep("step-003", "c")]
    return Plan("p", "g", steps=steps, created_at="1970-01-01T00:00:00+00:00",
                metadata={"phase": "planning", "executed": executed, "execution_authorized": authorized})


def snap(plan):
    return copy.deepcopy(plan.to_dict())


DEFAULT = object()


class Spy:
    def __init__(self, value="done", exc=None):
        self.value, self.exc, self.calls = value, exc, []

    def __call__(self, step_input):
        self.calls.append(step_input)
        if self.exc is not None:
            raise self.exc
        return self.value


class TestSuccess(unittest.TestCase):
    def test_successful_execution(self):
        plan, ex = mk(), Spy({"answer": 42})
        res = execute_plan_step(plan, "step-001", ex)
        self.assertTrue(res.ok)
        self.assertEqual((res.status, res.previous_state, res.final_state), ("completed", "pending", "completed"))
        self.assertEqual(res.output, {"answer": 42})
        self.assertIsNone(res.reason)
        self.assertEqual(res.failures, [])
        self.assertEqual(plan.steps[0].status, "completed")
        self.assertEqual([s.status for s in plan.steps[1:]], ["pending", "pending"])

    def test_executor_called_exactly_once(self):
        ex = Spy("x")
        execute_plan_step(mk(), "step-001", ex)
        self.assertEqual(len(ex.calls), 1)

    def test_output_stored_on_step(self):
        plan = mk()
        execute_plan_step(plan, "step-001", Spy({"k": [1, 2]}))
        self.assertEqual(plan.steps[0].output_data, {"k": [1, 2]})

    def test_executor_receives_only_step_data(self):
        plan, ex = mk(), Spy("x")
        execute_plan_step(plan, "step-001", ex)
        self.assertEqual(ex.calls[0], {"step_id": "step-001", "description": "a", "input_data": {"n": 1},
                                       "expected_output": "num", "required_capabilities": ["cap.x"]})

    def test_executor_cannot_mutate_plan_through_input(self):
        plan = mk()

        def ex(step_input):
            step_input["input_data"]["n"] = 999
            step_input["required_capabilities"].append("evil")
            return "ok"

        execute_plan_step(plan, "step-001", ex)
        self.assertEqual(plan.steps[0].input_data, {"n": 1})
        self.assertEqual(plan.steps[0].required_capabilities, ["cap.x"])

    def test_state_is_in_progress_while_executor_runs(self):
        plan, seen = mk(), []
        execute_plan_step(plan, "step-001", lambda si: seen.append(plan.steps[0].status) or "ok")
        self.assertEqual(seen, ["in_progress"])

    def test_chain_dependent_step_becomes_ready(self):
        plan = mk()
        execute_plan_step(plan, "step-001", Spy("a"))
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, ["step-002", "step-003"])
        self.assertTrue(execute_plan_step(plan, "step-002", Spy("b")).ok)


class TestExecutorFailure(unittest.TestCase):
    def test_exception_marks_failed_and_is_not_raised(self):
        plan, ex = mk(), Spy(exc=ValueError("boom"))
        res = execute_plan_step(plan, "step-001", ex)       # must not raise
        self.assertFalse(res.ok)
        self.assertEqual((res.status, res.previous_state, res.final_state), ("failed", "pending", "failed"))
        self.assertEqual(res.reason, orch.ORCH_EXECUTOR_EXCEPTION)
        self.assertEqual(res.failures[0]["exception_type"], "ValueError")
        self.assertIsNone(res.output)
        self.assertTrue(res.executor_called)
        self.assertEqual(plan.steps[0].status, "failed")
        self.assertEqual(plan.steps[0].output_data,
                         {"code": "EXECUTOR_EXCEPTION", "exception_type": "ValueError", "message": "boom"})

    def test_failed_state_is_consistent_with_existing_validation(self):
        plan = mk()
        execute_plan_step(plan, "step-001", Spy(exc=RuntimeError("x")))
        self.assertTrue(validate_plan_step_states(plan).valid)
        self.assertTrue(validate_plan(plan).valid)
        self.assertIs(plan.metadata["executed"], True)
        self.assertIs(plan.metadata["execution_authorized"], True)
        self.assertEqual(rollup_plan_status(plan).status, "failed")
        self.assertTrue(evaluate_plan_progress(plan).ok)

    def test_failed_executor_is_not_retried(self):
        plan, ex = mk(), Spy(exc=RuntimeError("x"))
        execute_plan_step(plan, "step-001", ex)
        again = execute_plan_step(plan, "step-001", ex)
        self.assertFalse(again.ok)
        self.assertEqual(again.codes(), ["STEP_NOT_READY"])
        self.assertEqual(len(ex.calls), 1)

    def test_dependents_of_failed_step_stay_blocked(self):
        plan, ex = mk(), Spy("x")
        execute_plan_step(plan, "step-001", Spy(exc=RuntimeError("x")))
        res = execute_plan_step(plan, "step-002", ex)
        self.assertEqual(res.codes(), ["STEP_NOT_READY"])
        self.assertEqual(ex.calls, [])

    def test_invalid_output_fails_started_step(self):
        for bad in (None, "", "   ", object(), {1: "x"}):
            plan, ex = mk(), Spy(bad)
            res = execute_plan_step(plan, "step-001", ex)
            self.assertFalse(res.ok)
            self.assertEqual((res.final_state, res.reason), ("failed", orch.ORCH_EXECUTOR_OUTPUT_INVALID))
            self.assertEqual(len(ex.calls), 1)
            self.assertEqual(plan.steps[0].status, "failed")
            self.assertTrue(validate_plan_step_states(plan).valid)

    def test_unrepresentable_exception_message_is_safe(self):
        class Odd(Exception):
            def __str__(self):
                raise RuntimeError("no str")

        plan = mk()
        res = execute_plan_step(plan, "step-001", Spy(exc=Odd()))
        self.assertEqual((res.final_state, res.failures[0]["exception_type"]), ("failed", "Odd"))


class TestRejectedPreconditions(unittest.TestCase):
    def check_rejected(self, plan, step_id, executor, code):
        before = snap(plan)
        ex = Spy("x") if executor is DEFAULT else executor
        res = execute_plan_step(plan, step_id, ex)
        self.assertFalse(res.ok)
        self.assertEqual(res.status, "rejected")
        self.assertEqual(res.reason, code)
        self.assertEqual(res.codes()[0], code)
        self.assertFalse(res.executor_called)
        self.assertEqual(res.previous_state, res.final_state)
        self.assertIsNone(res.output)
        self.assertEqual(snap(plan), before)
        if isinstance(ex, Spy):
            self.assertEqual(ex.calls, [])
        return res

    def test_unauthorized_plan(self):
        res = self.check_rejected(mk(authorized=False), "step-001", DEFAULT, "EXECUTION_NOT_AUTHORIZED")
        self.assertEqual(res.previous_state, "pending")

    def test_non_ready_step(self):
        res = self.check_rejected(mk(), "step-002", DEFAULT, "STEP_NOT_READY")
        self.assertEqual(res.previous_state, "pending")

    def test_already_started_or_completed_step(self):
        plan = mk()
        start_plan_step(plan, "step-001")
        self.check_rejected(plan, "step-001", DEFAULT, "STEP_NOT_READY")
        complete_plan_step(plan, "step-001", "out")
        self.check_rejected(plan, "step-001", DEFAULT, "STEP_NOT_READY")

    def test_invalid_step(self):
        self.check_rejected(mk(), "nope", DEFAULT, "UNKNOWN_STEP")
        for bad in (None, "", "  ", 5):
            self.check_rejected(mk(), bad, DEFAULT, "INVALID_STEP_ID")

    def test_invalid_executor(self):
        for bad in (None, "x", 5, {}):
            self.check_rejected(mk(), "step-001", bad, "INVALID_EXECUTOR")

    def test_invalid_plan(self):
        res = execute_plan_step("not a plan", "step-001", Spy())
        self.assertEqual((res.ok, res.reason, res.executor_called), (False, "INVALID_PLAN_OBJECT", False))
        empty = Plan("p", "g", metadata={"executed": False, "execution_authorized": True})
        self.check_rejected(empty, "step-001", DEFAULT, "INVALID_PLAN")
        no_goal = mk()
        no_goal.goal_id = ""
        self.check_rejected(no_goal, "step-001", DEFAULT, "INVALID_PLAN")
        cyc = mk()
        cyc.steps[0].dependencies = ["step-002"]
        self.check_rejected(cyc, "step-001", DEFAULT, "INVALID_PLAN")

    def test_inconsistent_state_rejected(self):
        plan = mk()
        plan.metadata["executed"] = "yes"
        self.check_rejected(plan, "step-001", DEFAULT, "INVALID_PLAN_STATE")

    def test_readiness_and_validation_never_run_executor(self):
        ex, plan = Spy(), mk()
        get_ready_plan_steps(plan)
        validate_plan(plan)
        validate_plan_step_states(plan)
        self.assertEqual(ex.calls, [])

    def test_authorization_alone_never_executes(self):
        plan = mk(authorized=True)
        self.assertTrue(all(s.status == "pending" for s in plan.steps))
        self.assertIs(plan.metadata["executed"], False)


class TestDeterminismAndAuthority(unittest.TestCase):
    def test_result_structure_is_deterministic(self):
        r1 = execute_plan_step(mk(), "step-001", Spy({"a": 1})).to_dict()
        r2 = execute_plan_step(mk(), "step-001", Spy({"a": 1})).to_dict()
        self.assertEqual(r1, r2)
        self.assertEqual(sorted(r1), ["executor_called", "failures", "final_state", "ok", "output",
                                      "previous_state", "reason", "status", "step_id"])
        f1 = execute_plan_step(mk(), "step-001", Spy(exc=KeyError("k"))).to_dict()
        f2 = execute_plan_step(mk(), "step-001", Spy(exc=KeyError("k"))).to_dict()
        self.assertEqual(f1, f2)
        self.assertEqual(sorted(f1), sorted(r1))
        self.assertIs(f1["ok"], False)

    def test_existing_transitions_remain_authoritative(self):
        via_orch, manual = mk(), mk()
        execute_plan_step(via_orch, "step-001", Spy({"v": 1}))
        start_plan_step(manual, "step-001")
        complete_plan_step(manual, "step-001", {"v": 1})
        self.assertEqual(snap(via_orch), snap(manual))

    def test_orchestration_uses_transition_api(self):
        calls = []
        real = (orch.start_plan_step, orch.complete_plan_step, orch.fail_plan_step)
        orch.start_plan_step = lambda p, s: calls.append("start") or real[0](p, s)
        orch.complete_plan_step = lambda p, s, o: calls.append("complete") or real[1](p, s, o)
        orch.fail_plan_step = lambda p, s, r: calls.append("fail") or real[2](p, s, r)
        try:
            execute_plan_step(mk(), "step-001", Spy("x"))
            execute_plan_step(mk(), "step-001", Spy(exc=RuntimeError()))
        finally:
            orch.start_plan_step, orch.complete_plan_step, orch.fail_plan_step = real
        self.assertEqual(calls, ["start", "complete", "start", "fail"])

    def test_prior_output_and_other_steps_untouched(self):
        plan = mk()
        execute_plan_step(plan, "step-001", Spy("one"))
        before = snap(plan)
        execute_plan_step(plan, "step-003", Spy("three"))
        after = snap(plan)
        self.assertEqual(after["steps"][0], before["steps"][0])
        self.assertEqual(after["steps"][1], before["steps"][1])


class TestIsolation(unittest.TestCase):
    def test_only_planning_imports(self):
        path = os.path.join(PY_ROOT, "planning", "plan_step_orchestration.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {"planning.plan", "planning.plan_builder", "planning.plan_step_execution",
                                    "planning.plan_validation"})

    def test_database_unchanged(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
