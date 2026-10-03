"""Prompt 694 - plan run summary. Pure in-memory tests."""
import ast
import copy
import hashlib
import os
import unittest
from unittest import mock

from planning.plan import Plan, PlanStep
from planning.plan_run_summary import summarize_plan_run
from planning.plan_runner import PlanRunResult, run_plan_steps
from planning.plan_step_report import PlanStepExecutionReport

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def mk(kind="chain", authorized=True):
    if kind == "chain":
        steps = [PlanStep("step-001", "a"), PlanStep("step-002", "b", dependencies=["step-001"]),
                 PlanStep("step-003", "c", dependencies=["step-002"])]
    else:
        steps = [PlanStep("step-001", "a"), PlanStep("step-002", "b"), PlanStep("step-003", "c")]
    return Plan("p", "g", steps=steps, created_at="1970-01-01T00:00:00+00:00",
                metadata={"phase": "planning", "executed": False, "execution_authorized": authorized})


class Spy:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, step_input):
        self.calls.append(step_input["step_id"])
        if step_input["step_id"] == self.fail_on:
            raise RuntimeError("kaput")
        return "out"


def run(kind="chain", max_steps=10, fail_on=None, authorized=True):
    return run_plan_steps(mk(kind, authorized), Spy(fail_on), max_steps)


class TestOutcomes(unittest.TestCase):
    def test_complete_run(self):
        s = summarize_plan_run(run())
        self.assertTrue(s.ok)
        self.assertEqual((s.outcome, s.run_ok, s.stop_reason, s.is_complete), ("complete", True, "PLAN_COMPLETE", True))
        self.assertEqual((s.ended_by_execution_failure, s.ended_by_rejection, s.ended_abnormally),
                         (False, False, False))
        self.assertEqual((s.steps_attempted, s.report_count, s.final_plan_status), (3, 3, "complete"))
        self.assertEqual(s.completed_step_ids, ["step-001", "step-002", "step-003"])
        self.assertEqual(s.progress_counts["completed_count"], 3)
        self.assertEqual((s.ready_step_ids, s.blocked_step_ids), ([], []))

    def test_max_steps_stop(self):
        s = summarize_plan_run(run(max_steps=1))
        self.assertEqual((s.outcome, s.run_ok, s.stop_reason, s.is_complete, s.ended_abnormally),
                         ("stopped", True, "MAX_STEPS_REACHED", False, False))
        self.assertEqual((s.ready_step_ids, s.final_plan_status, s.report_count), (["step-002"], "pending", 1))

    def test_no_ready_step_stop(self):
        from planning.plan_step_execution import start_plan_step
        plan = mk()
        start_plan_step(plan, "step-001")
        s = summarize_plan_run(run_plan_steps(plan, Spy(), 3))
        self.assertEqual((s.outcome, s.stop_reason, s.steps_attempted, s.final_plan_status),
                         ("stopped", "NO_READY_STEPS", 0, "in_progress"))
        self.assertFalse(s.ended_abnormally)

    def test_failed_run(self):
        s = summarize_plan_run(run("parallel", fail_on="step-002"))
        self.assertEqual((s.outcome, s.run_ok, s.stop_reason), ("failed", False, "STEP_FAILED"))
        self.assertEqual((s.ended_by_execution_failure, s.ended_by_rejection, s.ended_abnormally),
                         (True, False, True))
        self.assertEqual((s.completed_step_ids, s.failed_step_ids, s.final_plan_status),
                         (["step-001"], ["step-002"], "failed"))
        self.assertEqual((s.progress_counts["failed_count"], s.ready_step_ids), (1, ["step-003"]))

    def test_failed_chain_blocked_ids(self):
        s = summarize_plan_run(run(fail_on="step-001"))
        self.assertEqual(s.blocked_step_ids, ["step-002", "step-003"])

    def test_execution_rejection(self):
        s = summarize_plan_run(run(authorized=False))
        self.assertEqual((s.outcome, s.run_ok, s.stop_reason), ("rejected", False, "EXECUTION_REJECTED"))
        self.assertEqual((s.ended_by_execution_failure, s.ended_by_rejection), (False, True))
        self.assertEqual((s.steps_attempted, s.report_count, s.completed_step_ids, s.failed_step_ids),
                         (1, 0, [], []))

    def test_report_rejection(self):
        rejected = PlanStepExecutionReport()
        rejected.failures = [{"code": "EXECUTION_INCONSISTENT", "message": "x"}]
        with mock.patch("planning.plan_runner.report_plan_step_execution", return_value=rejected):
            r = run_plan_steps(mk(), Spy(), 5)
        self.assertEqual(r.stop_reason, "REPORT_REJECTED")
        s = summarize_plan_run(r)
        self.assertTrue(s.ok)
        self.assertEqual((s.outcome, s.ended_by_rejection, s.ended_by_execution_failure, s.report_count),
                         ("rejected", True, False, 0))

    def test_precondition_rejection(self):
        ex = Spy()
        s = summarize_plan_run(run_plan_steps(mk(), ex, 0))
        self.assertEqual((s.outcome, s.stop_reason, s.steps_attempted, s.final_plan_status),
                         ("rejected", "INVALID_MAX_STEPS", 0, None))
        self.assertEqual(ex.calls, [])


class TestInvalid(unittest.TestCase):
    def _bad(self, r, code="INCONSISTENT_RUN_RESULT"):
        s = summarize_plan_run(r)
        self.assertFalse(s.ok)
        self.assertEqual((s.status, s.codes(), s.outcome), ("rejected", [code], None))
        return s

    def test_wrong_type(self):
        for v in (None, {}, "x", run().to_dict()):
            self._bad(v, "INVALID_RUN_RESULT")

    def test_blank_result_inconsistent(self):
        self._bad(PlanRunResult())

    def test_tampered_records(self):
        def tweak(fn):
            r = run("parallel", fail_on="step-002")
            fn(r)
            self._bad(r)
        tweak(lambda r: setattr(r, "stop_reason", "BOGUS"))
        tweak(lambda r: setattr(r, "stop_reason", "PLAN_COMPLETE"))
        tweak(lambda r: setattr(r, "failed_step_ids", []))
        tweak(lambda r: setattr(r, "completed_step_ids", ["step-009"]))
        tweak(lambda r: r.reports.pop())
        tweak(lambda r: setattr(r, "steps_attempted", 7))
        tweak(lambda r: setattr(r, "ok", True))
        tweak(lambda r: setattr(r, "final_progress", {}))
        tweak(lambda r: setattr(r, "final_plan_status", None))
        tweak(lambda r: setattr(r, "reports", "nope"))
        tweak(lambda r: setattr(r, "steps_attempted", True))

    def test_tampered_precondition_and_rejection(self):
        r = run_plan_steps(mk(), Spy(), 0)
        r.steps_attempted = 1
        self._bad(r)
        r = run(authorized=False)
        r.execution_results[-1]["status"] = "completed"
        self._bad(r)


class TestReadOnly(unittest.TestCase):
    def test_no_mutation_and_no_execution(self):
        for r in (run(), run(max_steps=1), run(fail_on="step-002"), run(authorized=False)):
            before = copy.deepcopy(r.to_dict())
            s = summarize_plan_run(r)
            self.assertEqual(r.to_dict(), before)
            s.completed_step_ids.append("x")
            s.ready_step_ids.append("x")
            s.progress_counts["completed_count"] = 99
            self.assertEqual(r.to_dict(), before)

    def test_executor_never_called(self):
        ex = Spy()
        r = run_plan_steps(mk(), ex, 2)
        calls = list(ex.calls)
        plan_calls = mock.Mock()
        with mock.patch("planning.plan_runner.execute_plan_step", plan_calls), \
             mock.patch("planning.plan_runner.run_plan_steps", plan_calls):
            summarize_plan_run(r)
        self.assertEqual(ex.calls, calls)
        plan_calls.assert_not_called()

    def test_deterministic(self):
        r = run("parallel", fail_on="step-003")
        first = summarize_plan_run(r).to_dict()
        for _ in range(3):
            self.assertEqual(summarize_plan_run(r).to_dict(), first)
        self.assertEqual(summarize_plan_run(run("parallel", fail_on="step-003")).to_dict(), first)


class TestIsolation(unittest.TestCase):
    def test_only_planning_imports(self):
        with open(os.path.join(PY_ROOT, "planning", "plan_run_summary.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {"copy", "planning.plan_builder", "planning.plan_runner"})

    def test_database_unchanged(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
