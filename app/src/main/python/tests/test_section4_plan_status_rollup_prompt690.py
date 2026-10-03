"""Prompt 690 - plan-level status rollup. Pure in-memory tests."""
import ast
import copy
import hashlib
import os
import unittest
from unittest import mock

from planning import plan_status_rollup as psr
from planning.plan import Plan, PlanStep
from planning.plan_builder import evaluate_plan_progress
from planning.plan_status_rollup import rollup_plan_status
from planning.plan_step_execution import complete_plan_step, start_plan_step

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def mk(states=("pending", "pending", "pending"), authorized=True, executed=None, deps=None, steps=None):
    """Plan of step-001..N. step-002 depends on step-001 unless `deps` overrides."""
    deps = {"step-002": ["step-001"]} if deps is None else deps
    if steps is None:
        steps = []
        for i, state in enumerate(states, 1):
            sid = f"step-{i:03d}"
            step = PlanStep(sid, f"s{i}", dependencies=deps.get(sid, []), status=state)
            if state == "completed":
                step.output_data = {"ok": True}
            steps.append(step)
    if executed is None:
        executed = any(s.status != "pending" for s in steps)
    return Plan("p", "g", steps=steps, created_at="1970-01-01T00:00:00+00:00",
                metadata={"phase": "planning", "executed": executed, "execution_authorized": authorized})


def snap(plan):
    return copy.deepcopy(plan.to_dict())


class TestRollupStatuses(unittest.TestCase):
    def test_empty_plan(self):
        res = rollup_plan_status(mk(steps=[]))
        self.assertTrue(res.ok)
        self.assertEqual((res.status, res.reason, res.total_steps), ("pending", psr.REASON_EMPTY_PLAN, 0))
        self.assertEqual(res.failures, [])

    def test_all_pending(self):
        res = rollup_plan_status(mk())
        self.assertEqual((res.status, res.reason), ("pending", psr.REASON_PENDING))
        self.assertEqual((res.total_steps, res.pending_count), (3, 3))
        self.assertEqual(res.pending_step_ids, ["step-001", "step-002", "step-003"])
        self.assertEqual(res.ready_step_ids, ["step-001", "step-003"])
        self.assertEqual(res.blocked_step_ids, [])

    def test_completed_plan(self):
        res = rollup_plan_status(mk(("completed", "completed", "completed")))
        self.assertEqual((res.status, res.reason), ("complete", psr.REASON_ALL_COMPLETED))
        self.assertEqual((res.completed_count, res.pending_count), (3, 0))
        self.assertEqual(res.completed_step_ids, ["step-001", "step-002", "step-003"])

    def test_in_progress_plan(self):
        res = rollup_plan_status(mk(("in_progress", "pending", "pending")))
        self.assertEqual((res.status, res.reason), ("in_progress", psr.REASON_STEP_IN_PROGRESS))
        self.assertEqual(res.in_progress_step_ids, ["step-001"])
        self.assertEqual(res.in_progress_count, 1)

    def test_failed_plan(self):
        res = rollup_plan_status(mk(("failed", "pending", "pending")))
        self.assertEqual((res.status, res.reason), ("failed", psr.REASON_STEP_FAILED))
        self.assertEqual((res.failed_step_ids, res.failed_count), (["step-001"], 1))
        self.assertEqual(res.blocked_step_ids, ["step-002"])     # stuck behind the failure, still reported

    def test_failed_wins_over_in_progress(self):
        res = rollup_plan_status(mk(("failed", "pending", "in_progress")))
        self.assertEqual(res.status, "failed")

    def test_blocked_follows_progress_contract(self):
        # Under Prompt 687 a stuck pending step always sits behind a failed step (rule 3 wins), so the blocked branch
        # is defensive: drive it with a progress result that reports is_blocked and no failures.
        plan = mk()
        progress = evaluate_plan_progress(plan)
        progress.is_blocked = True
        with mock.patch.object(psr, "evaluate_plan_progress", return_value=progress):
            res = rollup_plan_status(plan)
        self.assertEqual((res.status, res.reason), ("blocked", psr.REASON_NO_EXECUTABLE_PATH))

    def test_failure_with_stuck_steps_is_not_blocked_status(self):
        plan = mk(("failed", "pending"), deps={"step-002": ["step-001"]})
        self.assertTrue(evaluate_plan_progress(plan).is_blocked)
        self.assertEqual(rollup_plan_status(plan).status, "failed")

    def test_mixed_completed_pending(self):
        res = rollup_plan_status(mk(("completed", "pending", "pending")))
        self.assertEqual((res.status, res.reason), ("pending", psr.REASON_PENDING))
        self.assertEqual((res.completed_count, res.pending_count), (1, 2))
        self.assertEqual(res.ready_step_ids, ["step-002", "step-003"])

    def test_vocabulary(self):
        self.assertEqual(set(psr.ROLLUP_STATUSES),
                         {"pending", "in_progress", "completed", "failed", "blocked", "complete"})


class TestAuthorization(unittest.TestCase):
    def test_authorization_does_not_change_status(self):
        for states in (("pending",) * 3, ("completed", "pending", "pending"), ("failed", "pending", "pending"),
                       ("in_progress", "pending", "pending"), ("completed",) * 3):
            executed = any(s != "pending" for s in states)
            on = rollup_plan_status(mk(states, authorized=True, executed=executed))
            off = rollup_plan_status(mk(states, authorized=False, executed=executed))
            if executed:                      # execution without authorization is an inconsistent state
                self.assertFalse(off.ok)
                self.assertIn(psr.ROLLUP_INVALID_PLAN_STATE, off.codes())
            else:
                self.assertEqual(on.to_dict(), off.to_dict())
            self.assertTrue(on.ok)

    def test_authorized_pending_plan_stays_pending(self):
        res = rollup_plan_status(mk(authorized=True, executed=False))
        self.assertEqual(res.status, "pending")


class TestRejection(unittest.TestCase):
    def test_non_plan(self):
        for bad in (None, {}, "plan", 5):
            res = rollup_plan_status(bad)
            self.assertFalse(res.ok)
            self.assertIsNone(res.status)
            self.assertEqual(res.codes(), [psr.ROLLUP_INVALID_PLAN])

    def test_inconsistent_state(self):
        res = rollup_plan_status(mk(("pending",) * 3, executed=True))
        self.assertEqual(res.codes(), [psr.ROLLUP_INVALID_PLAN_STATE])
        self.assertIsNone(res.status)
        self.assertTrue(res.failures[0]["issues"])

    def test_invalid_flag(self):
        plan = mk()
        plan.metadata["executed"] = "no"
        self.assertEqual(rollup_plan_status(plan).codes(), [psr.ROLLUP_INVALID_PLAN_STATE])

    def test_unsupported_state(self):
        plan = mk()
        plan.steps[0].status = "cancelled"
        self.assertEqual(rollup_plan_status(plan).codes(), [psr.ROLLUP_INVALID_PLAN_STATE])

    def test_invalid_dependencies(self):
        res = rollup_plan_status(mk(deps={"step-002": ["step-999"]}))
        self.assertEqual(res.codes(), [psr.ROLLUP_PROGRESS_UNDETERMINED])
        self.assertIsNone(res.status)

    def test_rejected_result_is_stable(self):
        plan = mk(("pending",) * 3, executed=True)
        self.assertEqual(rollup_plan_status(plan).to_dict(), rollup_plan_status(plan).to_dict())


class TestReadOnlyAndDeterministic(unittest.TestCase):
    def test_no_mutation(self):
        for plan in (mk(), mk(("completed", "pending", "pending")), mk(("failed", "pending", "pending")),
                     mk(("in_progress", "pending", "pending")), mk(steps=[]), mk(("pending",) * 3, executed=True)):
            before = snap(plan)
            statuses = [s.status for s in plan.steps]
            rollup_plan_status(plan)
            self.assertEqual(snap(plan), before)
            self.assertEqual([s.status for s in plan.steps], statuses)

    def test_deterministic_repeated_calls(self):
        plan = mk(("completed", "pending", "pending"))
        first = rollup_plan_status(plan).to_dict()
        for _ in range(5):
            self.assertEqual(rollup_plan_status(plan).to_dict(), first)

    def test_result_lists_are_fresh_copies(self):
        plan = mk()
        res = rollup_plan_status(plan)
        res.pending_step_ids.append("x")
        self.assertEqual(rollup_plan_status(plan).pending_step_ids, ["step-001", "step-002", "step-003"])

    def test_follows_prompt_689_transitions_without_being_applied_by_rollup(self):
        plan = mk()
        self.assertEqual(rollup_plan_status(plan).status, "pending")
        start_plan_step(plan, "step-001")
        self.assertEqual(rollup_plan_status(plan).status, "in_progress")
        complete_plan_step(plan, "step-001", {"ok": 1})
        self.assertEqual(rollup_plan_status(plan).status, "pending")
        for sid in ("step-002", "step-003"):
            start_plan_step(plan, sid)
            complete_plan_step(plan, sid, {"ok": 1})
        self.assertEqual(rollup_plan_status(plan).status, "complete")

    def test_to_dict_shape(self):
        d = rollup_plan_status(mk()).to_dict()
        for key in ("status", "reason", "total_steps", "pending_count", "in_progress_count", "completed_count",
                    "failed_count", "pending_step_ids", "in_progress_step_ids", "completed_step_ids",
                    "failed_step_ids", "ready_step_ids", "blocked_step_ids", "failures"):
            self.assertIn(key, d)


class TestIsolation(unittest.TestCase):
    def test_module_imports_only_planning(self):
        with open(psr.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertEqual(mods, {"planning"})

    def test_shipped_db_unchanged(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
