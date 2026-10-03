"""Prompt 689 - controlled plan step execution state transitions. Pure in-memory tests."""
import ast
import copy
import hashlib
import os
import unittest

from planning import plan_step_execution as pse
from planning.plan import Plan, PlanStep
from planning.plan_builder import evaluate_plan_progress, get_ready_plan_steps, validate_plan_step_states
from planning.plan_step_execution import complete_plan_step, fail_plan_step, start_plan_step

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def mk(authorized=True, executed=False):
    steps = [PlanStep("step-001", "a"), PlanStep("step-002", "b", dependencies=["step-001"]),
             PlanStep("step-003", "c")]
    return Plan("p", "g", steps=steps, created_at="1970-01-01T00:00:00+00:00", metadata={"phase": "planning", "executed": executed,
                                                 "execution_authorized": authorized})


def snap(plan):
    return copy.deepcopy(plan.to_dict())


class TestStart(unittest.TestCase):
    def test_valid_start(self):
        plan = mk()
        res = start_plan_step(plan, "step-001")
        self.assertTrue(res.ok)
        self.assertEqual((res.previous_state, res.new_state), ("pending", "in_progress"))
        self.assertEqual(plan.steps[0].status, "in_progress")
        self.assertEqual(res.step.status, "in_progress")
        self.assertIsNot(res.step, plan.steps[0])
        self.assertEqual([s.status for s in plan.steps[1:]], ["pending", "pending"])

    def test_start_produces_no_output(self):
        plan = mk()
        res = start_plan_step(plan, "step-001")
        self.assertIsNone(plan.steps[0].output_data)
        self.assertIsNone(res.step.output_data)

    def test_start_keeps_plan_consistent_and_authorization_untouched(self):
        plan = mk()
        start_plan_step(plan, "step-001")
        self.assertTrue(validate_plan_step_states(plan).valid)
        self.assertIs(plan.metadata["executed"], True)
        self.assertIs(plan.metadata["execution_authorized"], True)
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, ["step-003"])

    def test_start_not_ready_dependency_pending(self):
        plan = mk()
        before = snap(plan)
        res = start_plan_step(plan, "step-002")
        self.assertEqual(res.codes(), [pse.TRANSITION_STEP_NOT_READY])
        self.assertEqual(snap(plan), before)

    def test_start_not_ready_dependency_in_progress_or_failed(self):
        for finish in (lambda p: None, lambda p: fail_plan_step(p, "step-001", "boom")):
            plan = mk()
            start_plan_step(plan, "step-001")
            finish(plan)
            before = snap(plan)
            self.assertEqual(start_plan_step(plan, "step-002").codes(), [pse.TRANSITION_STEP_NOT_READY])
            self.assertEqual(snap(plan), before)

    def test_start_ready_after_dependency_completed(self):
        plan = mk()
        start_plan_step(plan, "step-001")
        complete_plan_step(plan, "step-001", {"ok": 1})
        self.assertTrue(start_plan_step(plan, "step-002").ok)

    def test_start_twice_rejected(self):
        plan = mk()
        start_plan_step(plan, "step-001")
        before = snap(plan)
        self.assertEqual(start_plan_step(plan, "step-001").codes(), [pse.TRANSITION_STEP_NOT_READY])
        self.assertEqual(snap(plan), before)

    def test_start_terminal_states_rejected(self):
        plan = mk()
        start_plan_step(plan, "step-001")
        complete_plan_step(plan, "step-001", "done")
        start_plan_step(plan, "step-003")
        fail_plan_step(plan, "step-003", "bad")
        before = snap(plan)
        for sid in ("step-001", "step-003"):
            self.assertEqual(start_plan_step(plan, sid).codes(), [pse.TRANSITION_STEP_NOT_READY])
        self.assertEqual(snap(plan), before)

    def test_start_bad_inputs(self):
        plan = mk()
        before = snap(plan)
        self.assertEqual(start_plan_step(None, "step-001").codes(), [pse.TRANSITION_INVALID_PLAN])
        for bad in (None, "", "  ", 5):
            self.assertEqual(start_plan_step(plan, bad).codes(), [pse.TRANSITION_INVALID_STEP_ID])
        self.assertEqual(start_plan_step(plan, "nope").codes(), [pse.TRANSITION_UNKNOWN_STEP])
        self.assertEqual(snap(plan), before)

    def test_start_invalid_graph_or_flags_rejected(self):
        plan = mk()
        plan.steps[0].dependencies = ["step-002"]      # cycle
        before = snap(plan)
        self.assertFalse(start_plan_step(plan, "step-003").ok)
        self.assertEqual(snap(plan), before)
        bad = mk()
        bad.metadata["executed"] = "no"
        before = snap(bad)
        self.assertEqual(start_plan_step(bad, "step-001").codes(), [pse.TRANSITION_INVALID_PLAN_STATE])
        self.assertEqual(snap(bad), before)


class TestAuthorizationIsPermissionOnly(unittest.TestCase):
    def test_authorization_does_not_execute_anything(self):
        plan = mk(authorized=True)
        self.assertEqual([s.status for s in plan.steps], ["pending"] * 3)
        self.assertIs(plan.metadata["executed"], False)
        self.assertTrue(all(s.output_data is None for s in plan.steps))
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, ["step-001", "step-003"])
        progress = evaluate_plan_progress(plan)
        self.assertEqual((progress.pending_count, progress.completed_count), (3, 0))

    def test_unauthorized_plan_cannot_start(self):
        plan = mk(authorized=False)
        before = snap(plan)
        res = start_plan_step(plan, "step-001")
        self.assertEqual(res.codes(), [pse.TRANSITION_NOT_AUTHORIZED])
        self.assertEqual(snap(plan), before)
        self.assertIs(plan.metadata["executed"], False)

    def test_authorizing_later_never_advances_a_step(self):
        plan = mk(authorized=False)
        plan.metadata["execution_authorized"] = True
        self.assertEqual([s.status for s in plan.steps], ["pending"] * 3)
        self.assertTrue(start_plan_step(plan, "step-001").ok)
        self.assertEqual([s.status for s in plan.steps], ["in_progress", "pending", "pending"])


class TestCompleteAndFail(unittest.TestCase):
    def started(self, sid="step-001"):
        plan = mk()
        self.assertTrue(start_plan_step(plan, sid).ok)
        return plan

    def test_valid_completion_with_output(self):
        plan = self.started()
        res = complete_plan_step(plan, "step-001", {"answer": [1, 2]})
        self.assertTrue(res.ok)
        self.assertEqual((res.previous_state, res.new_state), ("in_progress", "completed"))
        self.assertEqual(plan.steps[0].status, "completed")
        self.assertEqual(plan.steps[0].output_data, {"answer": [1, 2]})
        self.assertEqual(res.step.output_data, {"answer": [1, 2]})
        self.assertTrue(validate_plan_step_states(plan).valid)

    def test_valid_failure_with_reason(self):
        plan = self.started()
        res = fail_plan_step(plan, "step-001", "dependency exploded")
        self.assertTrue(res.ok)
        self.assertEqual((res.previous_state, res.new_state), ("in_progress", "failed"))
        self.assertEqual(plan.steps[0].status, "failed")
        self.assertEqual(plan.steps[0].output_data, "dependency exploded")
        self.assertTrue(validate_plan_step_states(plan).valid)

    def test_valid_failure_with_structured_output(self):
        plan = self.started()
        self.assertTrue(fail_plan_step(plan, "step-001", {"code": "E1", "detail": "x"}).ok)
        self.assertEqual(plan.steps[0].output_data, {"code": "E1", "detail": "x"})

    def test_complete_and_fail_require_in_progress(self):
        for op in (lambda p, s: complete_plan_step(p, s, "out"), lambda p, s: fail_plan_step(p, s, "why")):
            plan = mk()
            before = snap(plan)
            res = op(plan, "step-001")                        # pending
            self.assertEqual(res.codes(), [pse.TRANSITION_NOT_IN_PROGRESS])
            self.assertEqual(snap(plan), before)
            self.assertIsNone(plan.steps[0].output_data)

    def test_terminal_steps_cannot_transition_again(self):
        plan = self.started()
        complete_plan_step(plan, "step-001", "first")
        start_plan_step(plan, "step-003")
        fail_plan_step(plan, "step-003", "bad")
        before = snap(plan)
        for sid in ("step-001", "step-003"):
            self.assertEqual(complete_plan_step(plan, sid, "again").codes(), [pse.TRANSITION_NOT_IN_PROGRESS])
            self.assertEqual(fail_plan_step(plan, sid, "again").codes(), [pse.TRANSITION_NOT_IN_PROGRESS])
        self.assertEqual(snap(plan), before)

    def test_missing_output_rejected_without_mutation(self):
        for op in (complete_plan_step, fail_plan_step):
            for bad in (None, "", "   "):
                plan = self.started()
                before = snap(plan)
                self.assertEqual(op(plan, "step-001", bad).codes(), [pse.TRANSITION_MISSING_OUTPUT])
                self.assertEqual(snap(plan), before)
                self.assertEqual(plan.steps[0].status, "in_progress")

    def test_unsafe_output_rejected_without_mutation(self):
        for op in (complete_plan_step, fail_plan_step):
            for bad in (object(), {1: "x"}, {"k": {1, 2}}):
                plan = self.started()
                before = snap(plan)
                self.assertEqual(op(plan, "step-001", bad).codes(), [pse.TRANSITION_INVALID_OUTPUT])
                self.assertEqual(snap(plan), before)

    def test_output_is_defensively_copied(self):
        plan = self.started()
        data = {"items": [1]}
        complete_plan_step(plan, "step-001", data)
        data["items"].append(2)
        self.assertEqual(plan.steps[0].output_data, {"items": [1]})

    def test_unknown_step_and_bad_plan(self):
        plan = self.started()
        before = snap(plan)
        self.assertEqual(complete_plan_step(plan, "zzz", "x").codes(), [pse.TRANSITION_UNKNOWN_STEP])
        self.assertEqual(fail_plan_step(None, "step-001", "x").codes(), [pse.TRANSITION_INVALID_PLAN])
        self.assertEqual(snap(plan), before)


class TestConsistencyAndDeterminism(unittest.TestCase):
    def test_state_output_consistency_across_lifecycle(self):
        plan = mk()
        self.assertTrue(all(s.status == "pending" and s.output_data is None for s in plan.steps))
        start_plan_step(plan, "step-001")
        self.assertEqual((plan.steps[0].status, plan.steps[0].output_data), ("in_progress", None))
        complete_plan_step(plan, "step-001", {"v": 1})
        self.assertEqual((plan.steps[0].status, plan.steps[0].output_data), ("completed", {"v": 1}))
        start_plan_step(plan, "step-003")
        fail_plan_step(plan, "step-003", "nope")
        self.assertEqual((plan.steps[2].status, plan.steps[2].output_data), ("failed", "nope"))
        for step in plan.steps:                       # output exists only where execution finished
            if step.output_data is not None:
                self.assertIn(step.status, ("completed", "failed"))
        self.assertTrue(validate_plan_step_states(plan).valid)
        progress = evaluate_plan_progress(plan)
        self.assertEqual((progress.completed_count, progress.failed_count, progress.pending_count), (1, 1, 1))
        self.assertEqual(progress.ready_step_ids, ["step-002"])

    def test_deterministic_results(self):
        def run():
            plan = mk()
            out = [start_plan_step(plan, "step-002").to_dict(), start_plan_step(plan, "step-001").to_dict(),
                   complete_plan_step(plan, "step-001", {"a": 1}).to_dict(),
                   fail_plan_step(plan, "step-001", "x").to_dict(), start_plan_step(plan, "step-002").to_dict()]
            return out, plan.to_dict()
        first, second = run(), run()
        self.assertEqual(first, second)

    def test_rejected_result_reports_unchanged_state(self):
        plan = mk()
        res = start_plan_step(plan, "step-002")
        self.assertEqual((res.previous_state, res.new_state), ("pending", "pending"))
        self.assertIsNone(res.step)

    def test_other_steps_and_plan_status_untouched(self):
        plan = mk()
        start_plan_step(plan, "step-001")
        self.assertEqual(plan.status, "pending")
        self.assertEqual(plan.steps[1].to_dict(), PlanStep("step-002", "b", dependencies=["step-001"]).to_dict())


class TestIsolation(unittest.TestCase):
    def test_no_process_input_or_execution_imports(self):
        path = os.path.join(PY_ROOT, "planning", "plan_step_execution.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {"planning.plan", "planning.plan_builder"})

    def test_database_unchanged(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
