"""Prompt 692 - plan step execution report. Pure in-memory tests."""
import ast
import copy
import hashlib
import os
import unittest

from planning.plan import Plan, PlanStep
from planning.plan_builder import evaluate_plan_progress
from planning.plan_status_rollup import rollup_plan_status
from planning.plan_step_orchestration import PlanStepExecutionResult, execute_plan_step
from planning.plan_step_report import report_plan_step_execution

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def mk(n=3, chain=True):
    steps = [PlanStep("step-001", "a", input_data={"n": 1})]
    for i in range(2, n + 1):
        deps = ["step-%03d" % (i - 1)] if chain else []
        steps.append(PlanStep("step-%03d" % i, "s%d" % i, dependencies=deps))
    return Plan("p", "g", steps=steps, created_at="1970-01-01T00:00:00+00:00",
                metadata={"phase": "planning", "executed": False, "execution_authorized": True})


def snap(plan):
    return copy.deepcopy(plan.to_dict())


def boom(_):
    raise RuntimeError("kaput")


class TestReport(unittest.TestCase):
    def test_success_with_progress(self):
        plan = mk()
        res = execute_plan_step(plan, "step-001", lambda s: {"answer": 42})
        rep = report_plan_step_execution(plan, res)
        self.assertTrue(rep.ok)
        self.assertEqual((rep.step_id, rep.execution_ok, rep.previous_state, rep.final_state, rep.executor_called),
                         ("step-001", True, "pending", "completed", True))
        self.assertEqual(rep.output, {"answer": 42})
        self.assertIsNone(rep.reason)
        self.assertEqual(rep.execution_failures, [])
        self.assertEqual(rep.plan_status, "pending")
        self.assertEqual((rep.progress["completed_count"], rep.progress["pending_count"],
                          rep.progress["total_steps"]), (1, 2, 3))

    def test_failed_step_and_plan_status(self):
        plan = mk()
        res = execute_plan_step(plan, "step-001", boom)
        rep = report_plan_step_execution(plan, res)
        self.assertTrue(rep.ok)
        self.assertFalse(rep.execution_ok)
        self.assertEqual((rep.previous_state, rep.final_state), ("pending", "failed"))
        self.assertEqual(rep.reason, "EXECUTOR_EXCEPTION")
        self.assertEqual(rep.execution_failures, res.failures)     # preserved, no recovery/retry
        self.assertEqual(rep.plan_status, "failed")
        self.assertEqual(rep.blocked_step_ids, ["step-002", "step-003"])
        self.assertEqual(rep.ready_step_ids, [])
        self.assertEqual(plan.steps[0].status, "failed")           # not retried

    def test_remaining_ready_steps(self):
        plan = mk(chain=False)
        res = execute_plan_step(plan, "step-002", lambda s: "ok")
        rep = report_plan_step_execution(plan, res)
        self.assertEqual(rep.ready_step_ids, ["step-001", "step-003"])
        self.assertEqual(rep.blocked_step_ids, [])
        self.assertEqual(rep.ready_step_ids, evaluate_plan_progress(plan).ready_step_ids)

    def test_dependent_becomes_ready(self):
        plan = mk()
        rep = report_plan_step_execution(plan, execute_plan_step(plan, "step-001", lambda s: "x"))
        self.assertEqual(rep.ready_step_ids, ["step-002"])

    def test_completed_plan(self):
        plan = mk(2)
        report_plan_step_execution(plan, execute_plan_step(plan, "step-001", lambda s: "x"))
        rep = report_plan_step_execution(plan, execute_plan_step(plan, "step-002", lambda s: "y"))
        self.assertEqual(rep.plan_status, "complete")
        self.assertTrue(rep.progress["is_complete"])
        self.assertEqual((rep.ready_step_ids, rep.blocked_step_ids), ([], []))
        self.assertEqual(rep.plan_status, rollup_plan_status(plan).status)

    def test_execution_and_plan_status_distinct(self):
        plan = mk(2)
        d = report_plan_step_execution(plan, execute_plan_step(plan, "step-001", boom)).to_dict()
        self.assertFalse(d["execution"]["ok"])
        self.assertEqual(d["execution"]["status"], "failed")
        self.assertEqual(d["plan"]["status"], "failed")
        self.assertEqual(set(d), {"ok", "status", "execution", "plan", "failures"})
        plan2 = mk(2)
        d2 = report_plan_step_execution(plan2, execute_plan_step(plan2, "step-001", lambda s: "x")).to_dict()
        self.assertTrue(d2["execution"]["ok"])
        self.assertEqual(d2["execution"]["status"], "completed")
        self.assertEqual(d2["plan"]["status"], "pending")          # step completed != plan complete

    def test_no_executor_call_or_extra_execution(self):
        plan = mk()
        res = execute_plan_step(plan, "step-001", lambda s: "x")
        report_plan_step_execution(plan, res)
        self.assertEqual([s.status for s in plan.steps], ["completed", "pending", "pending"])


class TestRejection(unittest.TestCase):
    def setUp(self):
        self.plan = mk()
        self.res = execute_plan_step(self.plan, "step-001", lambda s: "x")

    def _rej(self, plan, res, code):
        rep = report_plan_step_execution(plan, res)
        self.assertFalse(rep.ok)
        self.assertEqual(rep.status, "rejected")
        self.assertEqual(rep.codes(), [code])
        self.assertIsNone(rep.plan_status)
        return rep

    def test_bad_types(self):
        self._rej(None, self.res, "INVALID_PLAN_OBJECT")
        self._rej(self.plan, {"ok": True}, "INVALID_EXECUTION_RESULT")
        self._rej(self.plan, None, "INVALID_EXECUTION_RESULT")

    def test_rejected_execution_not_reportable(self):
        rejected = execute_plan_step(self.plan, "step-001", lambda s: "x")     # no longer ready
        self.assertEqual(rejected.status, "rejected")
        self._rej(self.plan, rejected, "EXECUTION_NOT_REPORTABLE")

    def test_unknown_step(self):
        self.res.step_id = "nope"
        self._rej(self.plan, self.res, "UNKNOWN_STEP")

    def test_inconsistent_with_plan(self):
        other = mk()                                   # step-001 is still pending there
        self._rej(other, self.res, "EXECUTION_INCONSISTENT")

    def test_tampered_fields(self):
        for attr, value in (("executor_called", False), ("previous_state", "in_progress"),
                            ("final_state", "failed"), ("output", "different"), ("reason", "X")):
            plan = mk()
            res = execute_plan_step(plan, "step-001", lambda s: "x")
            setattr(res, attr, value)
            self._rej(plan, res, "EXECUTION_INCONSISTENT")

    def test_failed_without_failures(self):
        plan = mk()
        res = execute_plan_step(plan, "step-001", boom)
        res.failures = []
        self._rej(plan, res, "EXECUTION_INCONSISTENT")

    def test_rejection_does_not_mutate(self):
        before = snap(self.plan)
        self.res.output = "tampered"
        self._rej(self.plan, self.res, "EXECUTION_INCONSISTENT")
        self.assertEqual(snap(self.plan), before)


class TestReadOnlyAndDeterminism(unittest.TestCase):
    def test_does_not_mutate_plan(self):
        for executor in (lambda s: {"a": [1]}, boom):
            plan = mk()
            res = execute_plan_step(plan, "step-001", executor)
            before, res_before = snap(plan), copy.deepcopy(res.to_dict())
            report_plan_step_execution(plan, res)
            self.assertEqual(snap(plan), before)
            self.assertEqual(res.to_dict(), res_before)

    def test_report_output_is_a_copy(self):
        plan = mk()
        res = execute_plan_step(plan, "step-001", lambda s: {"a": [1]})
        rep = report_plan_step_execution(plan, res)
        rep.output["a"].append(2)
        self.assertEqual(plan.steps[0].output_data, {"a": [1]})
        self.assertEqual(res.output, {"a": [1]})

    def test_deterministic(self):
        plan = mk()
        res = execute_plan_step(plan, "step-001", boom)
        first = report_plan_step_execution(plan, res).to_dict()
        for _ in range(3):
            self.assertEqual(report_plan_step_execution(plan, res).to_dict(), first)


class TestIsolation(unittest.TestCase):
    def test_only_planning_imports(self):
        path = os.path.join(PY_ROOT, "planning", "plan_step_report.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {"copy", "planning.plan", "planning.plan_builder", "planning.plan_status_rollup",
                                    "planning.plan_step_orchestration"})

    def test_database_unchanged(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
