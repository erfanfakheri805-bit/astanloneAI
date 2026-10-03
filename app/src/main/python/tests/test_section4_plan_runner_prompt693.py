"""Prompt 693 - caller-driven multi-step plan runner. Pure in-memory tests."""
import ast
import copy
import hashlib
import os
import unittest

from planning.plan import Plan, PlanStep
from planning.plan_runner import run_plan_steps
from planning.plan_status_rollup import rollup_plan_status
from planning.plan_step_execution import start_plan_step

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def mk(kind="chain", authorized=True):
    if kind == "chain":
        steps = [PlanStep("step-001", "a"), PlanStep("step-002", "b", dependencies=["step-001"]),
                 PlanStep("step-003", "c", dependencies=["step-002"])]
    elif kind == "parallel":
        steps = [PlanStep("step-001", "a"), PlanStep("step-002", "b"), PlanStep("step-003", "c")]
    else:
        steps = [PlanStep("step-001", "a")]
    return Plan("p", "g", steps=steps, created_at="1970-01-01T00:00:00+00:00",
                metadata={"phase": "planning", "executed": False, "execution_authorized": authorized})


def snap(plan):
    return copy.deepcopy(plan.to_dict())


class Spy:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, step_input):
        self.calls.append(step_input["step_id"])
        if step_input["step_id"] == self.fail_on:
            raise RuntimeError("kaput")
        return "out-" + step_input["step_id"]


class TestRuns(unittest.TestCase):
    def test_one_step_success(self):
        plan, ex = mk("single"), Spy()
        r = run_plan_steps(plan, ex, 5)
        self.assertTrue(r.ok)
        self.assertEqual((r.stop_reason, r.steps_attempted, r.completed_step_ids, r.failed_step_ids),
                         ("PLAN_COMPLETE", 1, ["step-001"], []))
        self.assertEqual(len(r.reports), 1)
        self.assertEqual(r.final_plan_status, "complete")
        self.assertTrue(r.final_progress["is_complete"])

    def test_multiple_sequential(self):
        plan, ex = mk("chain"), Spy()
        r = run_plan_steps(plan, ex, 10)
        self.assertEqual(ex.calls, ["step-001", "step-002", "step-003"])
        self.assertEqual((r.ok, r.stop_reason, r.steps_attempted), (True, "PLAN_COMPLETE", 3))
        self.assertEqual([x["execution"]["step_id"] for x in r.reports], ex.calls)
        self.assertEqual(r.final_plan_status, rollup_plan_status(plan).status)

    def test_deterministic_first_ready_ordering(self):
        ex = Spy()
        run_plan_steps(mk("parallel"), ex, 3)
        self.assertEqual(ex.calls, ["step-001", "step-002", "step-003"])

    def test_max_steps_stops(self):
        plan, ex = mk("chain"), Spy()
        r = run_plan_steps(plan, ex, 2)
        self.assertEqual((r.ok, r.stop_reason, r.steps_attempted), (True, "MAX_STEPS_REACHED", 2))
        self.assertEqual(ex.calls, ["step-001", "step-002"])
        self.assertEqual(r.final_progress["ready_step_ids"], ["step-003"])
        self.assertEqual(r.final_plan_status, "pending")

    def test_completion_beats_max_steps(self):
        r = run_plan_steps(mk("chain"), Spy(), 3)
        self.assertEqual(r.stop_reason, "PLAN_COMPLETE")

    def test_already_complete_plan(self):
        plan = mk("single")
        run_plan_steps(plan, Spy(), 1)
        ex = Spy()
        r = run_plan_steps(plan, ex, 3)
        self.assertEqual((r.stop_reason, r.steps_attempted, ex.calls), ("PLAN_COMPLETE", 0, []))

    def test_no_ready_steps(self):
        plan = mk("chain")
        self.assertTrue(start_plan_step(plan, "step-001").ok)       # a step in flight, nothing ready
        ex = Spy()
        r = run_plan_steps(plan, ex, 3)
        self.assertEqual((r.stop_reason, r.steps_attempted, ex.calls), ("NO_READY_STEPS", 0, []))
        self.assertEqual(r.final_plan_status, "in_progress")
        self.assertTrue(r.ok)

    def test_first_failure_stops_and_not_retried(self):
        plan, ex = mk("parallel"), Spy(fail_on="step-002")
        r = run_plan_steps(plan, ex, 10)
        self.assertFalse(r.ok)
        self.assertEqual((r.stop_reason, r.steps_attempted), ("STEP_FAILED", 2))
        self.assertEqual((r.completed_step_ids, r.failed_step_ids), (["step-001"], ["step-002"]))
        self.assertEqual(ex.calls, ["step-001", "step-002"])           # step-003 never run, no retry
        self.assertEqual(plan.steps[1].status, "failed")
        self.assertEqual(plan.steps[2].status, "pending")
        self.assertEqual(r.final_plan_status, "failed")
        self.assertEqual(r.reports[-1]["execution"]["reason"], "EXECUTOR_EXCEPTION")
        self.assertEqual(r.codes(), ["EXECUTOR_EXCEPTION"])
        again = Spy()
        run_plan_steps(plan, again, 10)                                # a second run does not retry it
        self.assertNotIn("step-002", again.calls)

    def test_failure_of_chain_head(self):
        plan, ex = mk("chain"), Spy(fail_on="step-001")
        r = run_plan_steps(plan, ex, 10)
        self.assertEqual((r.stop_reason, ex.calls, r.final_progress["blocked_step_ids"]),
                         ("STEP_FAILED", ["step-001"], ["step-002", "step-003"]))

    def test_executor_call_count_and_reports(self):
        ex = Spy()
        r = run_plan_steps(mk("parallel"), ex, 2)
        self.assertEqual(len(ex.calls), 2)
        self.assertEqual(len(r.reports), r.steps_attempted)
        self.assertEqual(len(r.execution_results), r.steps_attempted)
        for rep in r.reports:
            self.assertTrue(rep["ok"])
            self.assertIn("plan", rep)

    def test_executor_only_gets_step_scoped_input(self):
        seen = []
        run_plan_steps(mk("single"), lambda s: seen.append(s) or "x", 1)
        self.assertEqual(set(seen[0]), {"step_id", "description", "input_data", "expected_output",
                                        "required_capabilities"})


class TestRejections(unittest.TestCase):
    def test_invalid_max_steps(self):
        for bad in (0, -1, None, "3", 1.5, True):
            plan, ex = mk(), Spy()
            before = snap(plan)
            r = run_plan_steps(plan, ex, bad)
            self.assertFalse(r.ok)
            self.assertEqual((r.stop_reason, r.steps_attempted, ex.calls), ("INVALID_MAX_STEPS", 0, []))
            self.assertEqual(snap(plan), before)

    def test_unauthorized_plan(self):
        plan, ex = mk(authorized=False), Spy()
        before = snap(plan)
        r = run_plan_steps(plan, ex, 3)
        self.assertFalse(r.ok)
        self.assertEqual((r.stop_reason, ex.calls), ("EXECUTION_REJECTED", []))
        self.assertEqual(r.codes(), ["EXECUTION_NOT_AUTHORIZED"])
        self.assertEqual((r.steps_attempted, r.reports, len(r.execution_results)), (1, [], 1))
        self.assertEqual(snap(plan), before)

    def test_invalid_preconditions(self):
        plan, ex = mk(), Spy()
        before = snap(plan)
        self.assertEqual(run_plan_steps(None, ex, 1).stop_reason, "INVALID_PLAN_OBJECT")
        self.assertEqual(run_plan_steps(plan, None, 1).stop_reason, "INVALID_EXECUTOR")
        bad = mk()
        bad.steps[0].dependencies = ["ghost"]
        bad_before = snap(bad)
        r = run_plan_steps(bad, ex, 1)
        self.assertEqual(r.stop_reason, "INVALID_PLAN")
        self.assertEqual((ex.calls, snap(plan), snap(bad)), ([], before, bad_before))

    def test_invalid_output_stops_as_failure(self):
        plan = mk("chain")
        r = run_plan_steps(plan, lambda s: None, 5)
        self.assertEqual((r.stop_reason, r.failed_step_ids, r.steps_attempted),
                         ("STEP_FAILED", ["step-001"], 1))


class TestDeterminismAndIsolation(unittest.TestCase):
    def test_deterministic_repeat(self):
        results = []
        for _ in range(3):
            results.append(run_plan_steps(mk("parallel"), Spy(fail_on="step-003"), 10).to_dict())
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    def test_only_planning_imports(self):
        with open(os.path.join(PY_ROOT, "planning", "plan_runner.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {"planning.plan", "planning.plan_builder", "planning.plan_status_rollup",
                                    "planning.plan_step_orchestration", "planning.plan_step_report",
                                    "planning.plan_validation"})

    def test_database_unchanged(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
