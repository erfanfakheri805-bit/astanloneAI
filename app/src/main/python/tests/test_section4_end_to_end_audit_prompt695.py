"""Prompt 695 - end-to-end consistency audit of the Prompt 684-694 planning/execution pipeline (in-memory)."""
import copy
import hashlib
import itertools
import os
import unittest

from planning.plan import Plan, PlanStep
from planning.plan_builder import evaluate_plan_progress, get_ready_plan_steps, validate_plan_step_states
from planning.plan_run_summary import summarize_plan_run
from planning.plan_runner import run_plan_steps
from planning.plan_status_rollup import rollup_plan_status
from planning.plan_step_execution import complete_plan_step, fail_plan_step, start_plan_step
from planning.plan_step_orchestration import execute_plan_step
from planning.plan_step_report import report_plan_step_execution
from planning.plan_validation import validate_plan

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def mk(authorized=True, executed=False):
    steps = [PlanStep("step-001", "a"), PlanStep("step-002", "b", dependencies=["step-001"]),
             PlanStep("step-003", "c", dependencies=["step-001"]), PlanStep("step-004", "d"),
             PlanStep("step-005", "e", dependencies=["step-002", "step-003"])]
    return Plan("p", "g", steps=steps, created_at="1970-01-01T00:00:00+00:00",
                metadata={"phase": "planning", "executed": executed, "execution_authorized": authorized})


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


def assert_layers_agree(tc, plan):
    """One snapshot: every read-only layer must tell the same story about the same plan."""
    tc.assertTrue(validate_plan(plan).valid)
    tc.assertTrue(validate_plan_step_states(plan).valid)
    ready = get_ready_plan_steps(plan)
    prog = evaluate_plan_progress(plan)
    roll = rollup_plan_status(plan)
    tc.assertTrue(ready.ok and prog.ok and roll.ok)
    tc.assertEqual(prog.ready_step_ids, ready.ready_step_ids)
    tc.assertEqual(roll.ready_step_ids, ready.ready_step_ids)
    tc.assertEqual(roll.blocked_step_ids, prog.blocked_step_ids)
    counts = [s.status for s in plan.steps]
    for state, n in (("pending", prog.pending_count), ("in_progress", prog.in_progress_count),
                     ("completed", prog.completed_count), ("failed", prog.failed_count)):
        tc.assertEqual(counts.count(state), n)
    tc.assertEqual((roll.pending_count, roll.in_progress_count, roll.completed_count, roll.failed_count),
                   (prog.pending_count, prog.in_progress_count, prog.completed_count, prog.failed_count))
    order = [s.step_id for s in plan.steps]
    tc.assertEqual(ready.ready_step_ids, [i for i in order if i in ready.ready_step_ids])   # plan order
    tc.assertEqual(roll.status == "complete", prog.is_complete)
    tc.assertEqual(roll.status == "failed", prog.failed_count > 0)
    # executed flag agrees with step evidence; authorization never counts as execution
    progressed = any(s.status != "pending" for s in plan.steps)
    tc.assertEqual(plan.metadata["executed"], progressed)
    return ready, prog, roll


class TestLifecycle(unittest.TestCase):
    def test_authorization_is_not_execution(self):
        plan = mk(authorized=True)
        ready, prog, roll = assert_layers_agree(self, plan)
        self.assertEqual(ready.ready_step_ids, ["step-001", "step-004"])
        self.assertFalse(plan.metadata["executed"])
        self.assertEqual((roll.status, prog.completed_count, prog.in_progress_count), ("pending", 0, 0))
        self.assertFalse(any(r.executed or r.execution_authorized for r in (ready, prog)))
        self.assertTrue(all(s.status == "pending" and s.output_data is None for s in plan.steps))

    def test_full_pipeline_step_by_step(self):
        plan, ex = mk(), Spy()
        expected = [("step-001", ["step-002", "step-003", "step-004"], "pending"),
                    ("step-002", ["step-003", "step-004"], "pending"),
                    ("step-003", ["step-004", "step-005"], "pending"),
                    ("step-004", ["step-005"], "pending"),
                    ("step-005", [], "complete")]
        for step_id, ready_after, plan_status in expected:
            ready_now, _, _ = assert_layers_agree(self, plan)
            self.assertEqual(ready_now.ready_step_ids[0], step_id)              # first ready, deterministic
            before = snap(plan)
            res = execute_plan_step(plan, step_id, ex)
            self.assertTrue(res.ok and res.executor_called)
            self.assertEqual((res.previous_state, res.final_state), ("pending", "completed"))
            self.assertNotEqual(snap(plan), before)
            _, prog, roll = assert_layers_agree(self, plan)
            rep = report_plan_step_execution(plan, res)
            self.assertTrue(rep.ok)
            self.assertEqual((rep.ready_step_ids, rep.blocked_step_ids), (prog.ready_step_ids, prog.blocked_step_ids))
            self.assertEqual((rep.plan_status, rep.final_state), (roll.status, plan.steps[int(step_id[-1]) - 1].status))
            self.assertEqual(rep.ready_step_ids, ready_after)
            self.assertEqual(rep.plan_status, plan_status)
            self.assertEqual(rep.output, plan.steps[int(step_id[-1]) - 1].output_data)
        self.assertEqual(ex.calls, ["step-001", "step-002", "step-003", "step-004", "step-005"])

    def test_dependent_becomes_ready_only_after_dependency_completes(self):
        plan = mk()
        self.assertNotIn("step-002", get_ready_plan_steps(plan).ready_step_ids)
        self.assertTrue(start_plan_step(plan, "step-001").ok)
        self.assertNotIn("step-002", get_ready_plan_steps(plan).ready_step_ids)       # in_progress != completed
        self.assertTrue(complete_plan_step(plan, "step-001", "x").ok)
        self.assertIn("step-002", get_ready_plan_steps(plan).ready_step_ids)

    def test_runner_summary_agree_with_plan_after_complete_run(self):
        plan, ex = mk(), Spy()
        run = run_plan_steps(plan, ex, 50)
        summ = summarize_plan_run(run)
        _, prog, roll = assert_layers_agree(self, plan)
        self.assertEqual((run.ok, run.stop_reason, summ.outcome), (True, "PLAN_COMPLETE", "complete"))
        self.assertEqual((run.final_plan_status, summ.final_plan_status), (roll.status, roll.status))
        self.assertEqual(summ.progress_counts["completed_count"], prog.completed_count)
        self.assertEqual(run.completed_step_ids, [s.step_id for s in plan.steps])
        self.assertEqual((summ.steps_attempted, summ.report_count, len(ex.calls)), (5, 5, 5))
        self.assertEqual(run.final_progress["ready_step_ids"], prog.ready_step_ids)

    def test_failure_yields_exactly_one_failed_step_and_stops(self):
        plan, ex = mk(), Spy(fail_on="step-002")
        run = run_plan_steps(plan, ex, 50)
        summ = summarize_plan_run(run)
        _, prog, roll = assert_layers_agree(self, plan)
        self.assertEqual([s.status for s in plan.steps].count("failed"), 1)
        self.assertEqual(ex.calls, ["step-001", "step-002"])
        self.assertEqual((run.ok, run.stop_reason, run.failed_step_ids), (False, "STEP_FAILED", ["step-002"]))
        self.assertEqual((roll.status, summ.outcome, summ.final_plan_status), ("failed", "failed", "failed"))
        self.assertEqual(summ.blocked_step_ids, prog.blocked_step_ids)
        self.assertEqual(prog.blocked_step_ids, ["step-005"])
        self.assertEqual(summ.ready_step_ids, prog.ready_step_ids)
        self.assertEqual(run.reports[-1]["plan"]["status"], "failed")
        again = Spy()
        rerun = run_plan_steps(plan, again, 50)                    # failed step is never retried
        self.assertNotIn("step-002", again.calls)
        self.assertEqual(plan.steps[1].status, "failed")
        self.assertFalse(rerun.ok)
        self.assertTrue(summarize_plan_run(rerun).ok)

    def test_step_transitions_cannot_bypass_validation(self):
        plan = mk()
        before = snap(plan)
        for step_id in ("step-002", "step-005", "nope"):               # not ready / unknown
            self.assertFalse(start_plan_step(plan, step_id).ok)
        self.assertFalse(complete_plan_step(plan, "step-001", "x").ok)  # pending, not in_progress
        self.assertFalse(fail_plan_step(plan, "step-001", "x").ok)
        self.assertEqual(snap(plan), before)


class TestRejectionsNeverExecuteOrMutate(unittest.TestCase):
    def test_unauthorized_never_calls_executor(self):
        plan, ex = mk(authorized=False), Spy()
        before = snap(plan)
        res = execute_plan_step(plan, "step-001", ex)
        run = run_plan_steps(plan, ex, 5)
        self.assertEqual((res.status, res.executor_called, run.stop_reason, ex.calls),
                         ("rejected", False, "EXECUTION_REJECTED", []))
        self.assertEqual(snap(plan), before)
        self.assertFalse(plan.metadata["executed"])
        self.assertTrue(summarize_plan_run(run).ok)

    def test_invalid_state_combinations_rejected_consistently(self):
        """Every state/flag combination the step-state validator rejects is refused by every layer that
        promises consistency, with no executor call and no mutation."""
        states = ["pending", "in_progress", "completed", "failed"]
        checked = 0
        for auth, executed in itertools.product((True, False), repeat=2):
            for st in itertools.product(states, repeat=2):
                plan = mk(auth, executed)
                for step, state in zip(plan.steps[:2], st):
                    step.status = state
                    if state in ("completed", "failed"):
                        step.output_data = "o"
                if validate_plan_step_states(plan).valid:
                    continue
                checked += 1
                before, ex = snap(plan), Spy()
                self.assertFalse(rollup_plan_status(plan).ok)
                self.assertFalse(execute_plan_step(plan, plan.steps[0].step_id, ex).ok)
                self.assertFalse(start_plan_step(plan, plan.steps[0].step_id).ok)
                run = run_plan_steps(plan, ex, 5)
                self.assertEqual((run.ok, run.stop_reason, run.steps_attempted), (False, "INVALID_PLAN_STATE", 0))
                summ = summarize_plan_run(run)
                self.assertTrue(summ.ok)
                self.assertEqual((summ.outcome, summ.ended_by_rejection), ("rejected", True))
                self.assertEqual((ex.calls, snap(plan)), ([], before))
        self.assertGreater(checked, 20)

    def test_regression_inconsistent_state_never_reports_complete(self):
        """Defect found by the 695 audit: readiness/progress accept flag/state contradictions (684 keeps that check
        separate), so the runner used to report PLAN_COMPLETE/ok=True with no final status for a plan whose steps
        are all `completed` but `executed=False`, and the summary then rejected that run record."""
        plan = mk(authorized=False, executed=False)
        for step in plan.steps:
            step.status, step.output_data = "completed", "o"
        self.assertTrue(evaluate_plan_progress(plan).is_complete)      # progress alone cannot tell
        self.assertFalse(rollup_plan_status(plan).ok)                  # rollup can
        run = run_plan_steps(plan, Spy(), 5)
        self.assertEqual((run.ok, run.stop_reason, run.steps_attempted), (False, "INVALID_PLAN_STATE", 0))
        summ = summarize_plan_run(run)
        self.assertTrue(summ.ok)
        self.assertEqual((summ.outcome, summ.is_complete, summ.stop_reason), ("rejected", False, "INVALID_PLAN_STATE"))

    def test_regression_no_run_record_is_unsummarizable(self):
        """Any run the runner can produce must be summarizable (summary and runner agree on their contract)."""
        cases = []
        for ex_flag, auth in itertools.product((True, False), repeat=2):
            for st in itertools.product(("pending", "in_progress", "completed", "failed"), repeat=2):
                plan = mk(auth, ex_flag)
                for step, state in zip(plan.steps[:2], st):
                    step.status = state
                    if state in ("completed", "failed"):
                        step.output_data = "o"
                cases.append(plan)
        cases.append(mk())
        cases.append(mk(False))
        for plan in cases:
            for fail_on in (None, "step-002"):
                run = run_plan_steps(plan, Spy(fail_on), 3)
                summ = summarize_plan_run(run)
                self.assertTrue(summ.ok, (run.stop_reason, summ.failures))
                self.assertEqual(summ.run_ok, run.ok)


class TestDeterminism(unittest.TestCase):
    def test_repeat_runs_identical(self):
        outs = []
        for _ in range(3):
            plan = mk()
            run = run_plan_steps(plan, Spy(fail_on="step-003"), 50)
            outs.append((run.to_dict(), summarize_plan_run(run).to_dict(), snap(plan)))
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[1], outs[2])


class TestDatabase(unittest.TestCase):
    def test_database_unchanged(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
