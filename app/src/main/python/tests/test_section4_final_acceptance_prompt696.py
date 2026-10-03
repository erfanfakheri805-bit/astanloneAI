"""Prompt 696 - Section 4 final acceptance: one cross-cutting check per acceptance criterion (1-15).

Read-only over production code. Every Core uses a disposable tempfile database; the shipped database is only hashed."""
import ast
import copy
import hashlib
import itertools
import os
import tempfile
import unittest

from core.core import Core
from planning import (plan_builder, plan_run_summary, plan_runner, plan_status_rollup, plan_step_execution,
                      plan_step_orchestration, plan_step_report)
from planning.plan import Plan, PlanStep
from planning.plan_builder import (build_plan_from_context, evaluate_plan_progress, get_ready_plan_steps,
                                   order_plan_steps, validate_plan_step_states, validate_step_dependencies)
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
SECTION4_MODULES = ("request_context", "plan_validation", "plan_builder", "plan_step_execution",
                    "plan_step_orchestration", "plan_step_report", "plan_status_rollup", "plan_runner",
                    "plan_run_summary")


def diamond(authorized=True, executed=False):
    steps = [PlanStep("step-001", "a", input_data={"k": [1]}, required_capabilities=[]),
             PlanStep("step-002", "b", dependencies=["step-001"]),
             PlanStep("step-003", "c", dependencies=["step-001"]),
             PlanStep("step-004", "d", dependencies=["step-002", "step-003"])]
    return Plan("p", "g", steps=steps, created_at="1970-01-01T00:00:00+00:00",
                metadata={"phase": "planning", "executed": executed, "execution_authorized": authorized})


def snap(plan):
    return copy.deepcopy(plan.to_dict())


class Recorder:
    def __init__(self, fail_on=None, result=None):
        self.calls, self.inputs, self.fail_on, self.result = [], [], fail_on, result

    def __call__(self, step_input):
        self.calls.append(step_input["step_id"])
        self.inputs.append(copy.deepcopy(step_input))
        if step_input["step_id"] == self.fail_on:
            raise RuntimeError("boom")
        return self.result if self.result is not None else {"done": step_input["step_id"]}


class CoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.core = Core(memory_db_path=os.path.join(self.tmp, "c.db"),
                         skill_definitions_dir=os.path.join(self.tmp, "s"))

    def tearDown(self):
        try:
            self.core.memory._conn.close()
        except Exception:  # noqa: BLE001
            pass


class TestCriteria1to3Planning(CoreBase):
    def test_1_valid_request_gives_deterministic_plan_without_invented_capabilities(self):
        a = build_plan_from_context(self.core.prepare_request_context("I want to build a calculator"))
        b = build_plan_from_context(self.core.prepare_request_context("I want to build a calculator"))
        self.assertTrue(a.ok)
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertTrue(validate_plan(a.plan).valid)
        self.assertTrue(all(s.required_capabilities == [] and s.status == "pending" for s in a.plan.steps))
        self.assertIs(a.plan.metadata["executed"], False)
        self.assertIs(a.plan.metadata["execution_authorized"], False)

    def test_2_invalid_incomplete_or_blocking_conditions_rejected_deterministically(self):
        self.core.learning.teach("Python", "upper", source="user")
        self.core.learning.teach("PYTHON", "lower", source="user")
        cases = [None, "text", self.core.prepare_request_context("   "),
                 self.core.prepare_request_context("What is python?")]
        for bad in cases:
            r1, r2 = build_plan_from_context(bad), build_plan_from_context(bad)
            self.assertFalse(r1.ok)
            self.assertIsNone(r1.plan)
            self.assertTrue(r1.failures)
            self.assertEqual(r1.to_dict(), r2.to_dict())

    def test_3_dependency_graphs_validated_and_ordering_deterministic(self):
        plan = diamond()
        self.assertTrue(validate_step_dependencies(plan).valid)
        order = order_plan_steps(plan)
        self.assertEqual([s.step_id for s in order.steps], ["step-001", "step-002", "step-003", "step-004"])
        self.assertEqual(order_plan_steps(plan).to_dict(), order.to_dict())
        for bad_dep in (["step-009"], ["step-002"], ["step-004"]):      # unknown, cycle-forming, forward/self
            broken = diamond()
            broken.steps[0].dependencies = bad_dep
            self.assertFalse(validate_step_dependencies(broken).valid)
            self.assertFalse(order_plan_steps(broken).ok)
            self.assertFalse(get_ready_plan_steps(broken).ok)
            self.assertFalse(rollup_plan_status(broken).ok)


class TestCriteria4to6Authorization(unittest.TestCase):
    def test_4_authorization_is_permission_only_never_execution(self):
        plan = diamond(authorized=True, executed=False)
        self.assertTrue(validate_plan_step_states(plan).valid)
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, ["step-001"])
        self.assertTrue(all(s.status == "pending" and s.output_data is None for s in plan.steps))
        self.assertEqual(rollup_plan_status(plan).status, "pending")
        self.assertIs(plan.metadata["executed"], False)
        run_plan_steps(plan, Recorder(), 1)
        self.assertIs(plan.metadata["execution_authorized"], True)      # never changed by any layer

    def test_5_readiness_from_step_state_and_completed_dependencies(self):
        plan = diamond()
        seen = []
        for _ in range(4):
            ready = get_ready_plan_steps(plan).ready_step_ids
            seen.append(list(ready))
            self.assertEqual(ready, evaluate_plan_progress(plan).ready_step_ids)
            self.assertEqual(ready, rollup_plan_status(plan).ready_step_ids)
            self.assertTrue(start_plan_step(plan, ready[0]).ok)
            self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, [i for i in ready[1:]])
            self.assertTrue(complete_plan_step(plan, ready[0], {"o": 1}).ok)
        self.assertEqual(seen, [["step-001"], ["step-002", "step-003"], ["step-003"], ["step-004"]])
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, [])

    def test_6_execution_is_explicit_and_caller_driven(self):
        plan, rec = diamond(), Recorder()
        for fn in (validate_plan, validate_plan_step_states, get_ready_plan_steps, evaluate_plan_progress,
                   rollup_plan_status, order_plan_steps):
            fn(plan)
        self.assertEqual(rec.calls, [])
        self.assertTrue(all(s.status == "pending" for s in plan.steps))
        self.assertTrue(execute_plan_step(plan, "step-001", rec).ok)
        self.assertEqual([s.status for s in plan.steps], ["completed", "pending", "pending", "pending"])
        self.assertEqual(rec.calls, ["step-001"])                          # nothing else ran on its own
        r = run_plan_steps(plan, rec, 1)
        self.assertEqual((r.stop_reason, r.steps_attempted), ("MAX_STEPS_REACHED", 1))
        self.assertEqual(rec.calls, ["step-001", "step-002"])              # exactly max_steps, first-ready-first


class TestCriteria7to10ExecutionBoundaries(unittest.TestCase):
    def test_7_executor_injected_and_receives_only_step_scoped_input(self):
        plan, rec = diamond(), Recorder()

        def mutating(inp):
            inp["input_data"]["k"].append(99)
            inp["required_capabilities"].append("x")
            return rec(inp)
        run_plan_steps(plan, mutating, 1)
        self.assertEqual(sorted(rec.inputs[0]),
                         ["description", "expected_output", "input_data", "required_capabilities", "step_id"])
        self.assertEqual(plan.steps[0].input_data, {"k": [1]})           # deep copy: executor cannot reach the plan
        self.assertEqual(plan.steps[0].required_capabilities, [])
        self.assertFalse(any(isinstance(v, (Plan, PlanStep)) for v in rec.inputs[0].values()))
        box = {"a": [1]}
        plan2 = diamond()
        execute_plan_step(plan2, "step-001", lambda i: box)
        box["a"].append(2)
        self.assertEqual(plan2.steps[0].output_data, {"a": [1]})          # stored output is not aliased

    def test_8_no_automatic_retries(self):
        plan, rec = diamond(), Recorder(fail_on="step-001")
        r = run_plan_steps(plan, rec, 10)
        self.assertEqual(rec.calls, ["step-001"])
        again = Recorder()
        self.assertEqual(run_plan_steps(plan, again, 10).stop_reason, "NO_READY_STEPS")
        self.assertEqual(again.calls, [])
        self.assertEqual(execute_plan_step(plan, "step-001", again).codes(), ["STEP_NOT_READY"])
        self.assertEqual(again.calls, [])
        self.assertEqual(r.failed_step_ids, ["step-001"])

    def test_9_failed_execution_stops_the_runner(self):
        plan = diamond()
        plan.steps[3].dependencies = ["step-001"]             # step-002/3/4 all ready after step-001
        rec = Recorder(fail_on="step-002")
        r = run_plan_steps(plan, rec, 10)
        self.assertEqual((r.stop_reason, r.ok, r.steps_attempted), ("STEP_FAILED", False, 2))
        self.assertEqual(rec.calls, ["step-001", "step-002"])
        self.assertEqual(r.final_plan_status, "failed")
        self.assertEqual(rollup_plan_status(plan).status, "failed")
        summary = summarize_plan_run(r)
        self.assertEqual((summary.outcome, summary.ended_by_execution_failure), ("failed", True))

    def test_10_rejected_preconditions_do_not_call_executor_or_mutate_plan(self):
        rec = Recorder()
        unauthorized = diamond(authorized=False)
        inconsistent = diamond(authorized=True)
        inconsistent.steps[0].status = "completed"            # completed while executed=False
        cyclic = diamond()
        cyclic.steps[0].dependencies = ["step-004"]
        for plan in (unauthorized, inconsistent, cyclic):
            before = snap(plan)
            self.assertEqual(execute_plan_step(plan, "step-001", rec).status, "rejected")
            self.assertEqual(run_plan_steps(plan, rec, 5).ok, False)
            self.assertEqual(start_plan_step(plan, "step-001").status, "rejected")
            self.assertEqual(snap(plan), before)
        for bad in ((None, rec, 3), (diamond(), None, 3), (diamond(), rec, 0), (diamond(), rec, True),
                    (diamond(), rec, "3")):
            self.assertEqual(run_plan_steps(*bad).ok, False)
        self.assertEqual(rec.calls, [])
        self.assertEqual(execute_plan_step(diamond(), "nope", rec).codes(), ["UNKNOWN_STEP"])
        self.assertEqual(rec.calls, [])


class TestCriteria11to12Agreement(unittest.TestCase):
    def check_agreement(self, plan):
        progress, rollup = evaluate_plan_progress(plan), rollup_plan_status(plan)
        self.assertTrue(progress.ok and rollup.ok)
        self.assertEqual(progress.ready_step_ids, rollup.ready_step_ids)
        self.assertEqual(progress.blocked_step_ids, rollup.blocked_step_ids)
        self.assertEqual((progress.pending_count, progress.in_progress_count, progress.completed_count,
                          progress.failed_count),
                         (rollup.pending_count, rollup.in_progress_count, rollup.completed_count,
                          rollup.failed_count))
        return progress, rollup

    def test_11_progress_readiness_status_reports_runner_and_summary_agree(self):
        for fail_on in (None, "step-001", "step-002", "step-004"):
            for limit in (1, 2, 10):
                plan, rec = diamond(), Recorder(fail_on=fail_on)
                run = run_plan_steps(plan, rec, limit)
                progress, rollup = self.check_agreement(plan)
                self.assertEqual(run.final_plan_status, rollup.status)
                self.assertEqual(run.final_progress["ready_step_ids"], progress.ready_step_ids)
                self.assertEqual(run.completed_step_ids, rollup.completed_step_ids[:len(run.completed_step_ids)])
                last = run.reports[-1]
                self.assertEqual(last["plan"]["status"], rollup.status)
                self.assertEqual(last["plan"]["ready_step_ids"], progress.ready_step_ids)
                summary = summarize_plan_run(run)
                self.assertTrue(summary.ok)
                self.assertEqual(summary.final_plan_status, rollup.status)
                self.assertEqual(summary.completed_step_ids, run.completed_step_ids)
                self.assertEqual(summary.failed_step_ids, run.failed_step_ids)
                self.assertEqual(summary.report_count, len(run.reports))
                self.assertEqual(summary.run_ok, run.ok)
                self.assertEqual(rec.calls, run.completed_step_ids + run.failed_step_ids)
                self.assertTrue(validate_plan(plan).valid)
                self.assertTrue(validate_plan_step_states(plan).valid)

    def test_11b_single_step_report_matches_plan_state(self):
        plan = diamond()
        res = execute_plan_step(plan, "step-001", Recorder())
        rep = report_plan_step_execution(plan, res)
        self.assertTrue(rep.ok)
        self.assertEqual(rep.plan_status, rollup_plan_status(plan).status)
        self.assertEqual(rep.ready_step_ids, get_ready_plan_steps(plan).ready_step_ids)
        rejected = execute_plan_step(diamond(False), "step-001", Recorder())
        self.assertEqual(report_plan_step_execution(plan, rejected).codes(), ["EXECUTION_NOT_REPORTABLE"])

    def test_12_invalid_state_flag_combinations_rejected_consistently_everywhere(self):
        states, flags = ("pending", "in_progress", "completed", "failed"), ((False, False), (True, False),
                                                                          (False, True), (True, True))
        for st, (executed, auth) in itertools.product(states, flags):
            plan = diamond(authorized=auth, executed=executed)
            plan.steps[0].status = st
            if st != "pending":
                plan.steps[0].output_data = {"o": 1} if st != "in_progress" else None
            valid = validate_plan_step_states(plan).valid
            before, rec = snap(plan), Recorder()
            self.assertEqual(rollup_plan_status(plan).ok, valid, (st, executed, auth))
            if not valid:
                self.assertEqual(start_plan_step(plan, "step-001").codes(), ["INVALID_PLAN_STATE"])
                self.assertEqual(snap(plan), before)
            run = run_plan_steps(plan, rec, 5)
            if not valid:
                self.assertEqual(run.stop_reason, "INVALID_PLAN_STATE", (st, executed, auth))
                self.assertEqual(rec.calls, [])
                self.assertEqual(snap(plan), before)
                self.assertEqual(execute_plan_step(plan, "step-001", rec).status, "rejected")
        for bad_flag in (1, 0, "yes", None):
            plan = diamond()
            plan.metadata["execution_authorized"] = bad_flag
            self.assertFalse(validate_plan_step_states(plan).valid)
            self.assertFalse(get_ready_plan_steps(plan).ok)
            self.assertEqual(run_plan_steps(plan, Recorder(), 3).ok, False)


class TestCriteria13to15Boundaries(unittest.TestCase):
    def test_13_no_external_tools_network_background_or_self_modification(self):
        banned_modules = {"os", "sys", "subprocess", "socket", "threading", "multiprocessing", "asyncio",
                          "urllib", "http", "requests", "shutil", "importlib", "sched", "signal", "ctypes",
                          "pathlib", "sqlite3", "tempfile"}
        banned_calls = {"eval", "exec", "open", "compile", "__import__"}
        for name in SECTION4_MODULES:
            with open(os.path.join(PY_ROOT, "planning", name + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse({a.name.split(".")[0] for a in node.names} & banned_modules, name)
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0], banned_modules, name)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, banned_calls, name)

    def test_14_backwards_compatible_public_surface_and_generated_plans(self):
        for mod, names in ((plan_builder, ("build_plan_from_context", "validate_step_dependencies", "order_plan_steps",
                                           "validate_plan_step_states", "get_ready_plan_steps",
                                           "evaluate_plan_progress")),
                           (plan_step_execution, ("start_plan_step", "complete_plan_step", "fail_plan_step")),
                           (plan_step_orchestration, ("execute_plan_step",)),
                           (plan_step_report, ("report_plan_step_execution",)),
                           (plan_status_rollup, ("rollup_plan_status",)),
                           (plan_runner, ("run_plan_steps",)), (plan_run_summary, ("summarize_plan_run",))):
            for n in names:
                self.assertTrue(callable(getattr(mod, n)), n)
        self.assertEqual(plan_runner.run_plan_steps.__code__.co_varnames[:3], ("plan", "executor", "max_steps"))
        tmp = tempfile.mkdtemp()
        core = Core(memory_db_path=os.path.join(tmp, "c.db"), skill_definitions_dir=os.path.join(tmp, "s"))
        try:
            plan = build_plan_from_context(core.prepare_request_context("I want to build a calculator")).plan
            self.assertTrue(validate_plan_step_states(plan).valid)      # builder plans still validate clean
            self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, ["step-001"])
            self.assertEqual(rollup_plan_status(plan).status, "pending")
            r = run_plan_steps(plan, Recorder(), 5)                      # not authorized by the builder
            self.assertEqual(r.stop_reason, "EXECUTION_REJECTED")
            self.assertEqual([s.status for s in plan.steps], ["pending"] * len(plan.steps))
        finally:
            core.memory._conn.close()

    def test_15_shipped_database_pristine_and_no_bytecode(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


class TestIntentionalLimitationsPinned(unittest.TestCase):
    def test_new_explicit_run_may_start_independent_ready_step_after_a_failure(self):
        """The runner stops at the first failure WITHIN a run and never retries the failed step. A later, separate,
        caller-initiated run can still start an independent ready step (readiness is dependency/state based)."""
        plan = diamond()
        plan.steps[3].dependencies = ["step-001"]
        first = run_plan_steps(plan, Recorder(fail_on="step-002"), 10)
        self.assertEqual(first.stop_reason, "STEP_FAILED")
        rec = Recorder()
        second = run_plan_steps(plan, rec, 10)
        self.assertNotIn("step-002", rec.calls)
        self.assertEqual(rec.calls[:1], ["step-003"])
        self.assertFalse(second.ok)                                       # plan status stays failed


if __name__ == "__main__":
    unittest.main()
