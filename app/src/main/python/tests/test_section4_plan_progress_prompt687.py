"""Prompt 687 - deterministic plan progress evaluation. Pure in-memory tests; no database is opened."""
import copy
import hashlib
import inspect
import os
import unittest

from planning import plan_builder as pb
from planning.plan import Plan, PlanStep
from planning.plan_builder import evaluate_plan_progress

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def mk(spec, executed=False, authorized=False):
    steps = [PlanStep(f"step-{i:03d}", f"do {i}", dependencies=deps, status=st)
             for i, (st, deps) in enumerate(spec, 1)]
    return Plan("p", "g", steps=steps, metadata={"phase": "planning", "executed": executed,
                                                 "execution_authorized": authorized})


def counts(r):
    return (r.total_steps, r.pending_count, r.in_progress_count, r.completed_count, r.failed_count)


class TestProgress(unittest.TestCase):
    def test_all_pending(self):
        r = evaluate_plan_progress(mk([("pending", []), ("pending", ["step-001"]), ("pending", [])]))
        self.assertTrue(r.ok)
        self.assertEqual(counts(r), (3, 3, 0, 0, 0))
        self.assertEqual(r.ready_step_ids, ["step-001", "step-003"])
        self.assertFalse(r.is_complete)
        self.assertFalse(r.is_blocked)
        self.assertFalse(r.executed)
        self.assertFalse(r.execution_authorized)

    def test_partially_completed_with_ready(self):
        r = evaluate_plan_progress(mk([("completed", []), ("pending", ["step-001"]), ("in_progress", [])],
                                      executed=True))
        self.assertEqual(counts(r), (3, 1, 1, 1, 0))
        self.assertEqual(r.ready_step_ids, ["step-002"])
        self.assertFalse(r.is_complete)
        self.assertFalse(r.is_blocked)

    def test_completed_plan(self):
        r = evaluate_plan_progress(mk([("completed", []), ("completed", ["step-001"])], executed=True))
        self.assertEqual(counts(r), (2, 0, 0, 2, 0))
        self.assertTrue(r.is_complete)
        self.assertFalse(r.is_blocked)
        self.assertEqual(r.ready_step_ids, [])

    def test_failed_plan_without_pending_is_not_blocked_or_complete(self):
        r = evaluate_plan_progress(mk([("completed", []), ("failed", ["step-001"])], executed=True))
        self.assertEqual(counts(r), (2, 0, 0, 1, 1))
        self.assertFalse(r.is_complete)
        self.assertFalse(r.is_blocked)          # nothing pending is stuck; the failure itself is in failed_count

    def test_blocked_by_failed_dependency(self):
        r = evaluate_plan_progress(mk([("failed", []), ("pending", ["step-001"])], executed=True))
        self.assertTrue(r.ok)
        self.assertTrue(r.is_blocked)
        self.assertEqual(r.blocked_step_ids, ["step-002"])
        self.assertEqual(r.ready_step_ids, [])

    def test_ready_step_prevents_blocked(self):
        r = evaluate_plan_progress(mk([("failed", []), ("pending", ["step-001"]), ("pending", [])],
                                      executed=True))
        self.assertEqual(r.ready_step_ids, ["step-003"])
        self.assertEqual(r.blocked_step_ids, ["step-002"])
        self.assertFalse(r.is_blocked)

    def test_in_progress_step_prevents_blocked(self):
        r = evaluate_plan_progress(mk([("failed", []), ("pending", ["step-001"]), ("in_progress", [])],
                                      executed=True))
        self.assertFalse(r.is_blocked)

    def test_authorized_plan_startable_step_prevents_blocked(self):
        r = evaluate_plan_progress(mk([("failed", []), ("pending", ["step-001"]), ("pending", [])],
                                      executed=True, authorized=True))
        self.assertEqual(r.ready_step_ids, ["step-003"])   # authorization does not hide ready steps (Prompt 688)
        self.assertFalse(r.is_blocked)

    def test_multi_level(self):
        r = evaluate_plan_progress(mk([("completed", []), ("failed", ["step-001"]), ("pending", ["step-002"]),
                                       ("pending", ["step-003"])], executed=True))
        self.assertTrue(r.is_blocked)
        self.assertEqual(r.blocked_step_ids, ["step-003", "step-004"])   # transitive, plan order
        r = evaluate_plan_progress(mk([("completed", []), ("completed", ["step-001"]), ("pending", ["step-002"]),
                                       ("pending", ["step-003"])], executed=True))
        self.assertEqual(r.ready_step_ids, ["step-003"])
        self.assertFalse(r.is_blocked)

    def test_empty_plan(self):
        r = evaluate_plan_progress(mk([]))
        self.assertTrue(r.ok)
        self.assertEqual(counts(r), (0, 0, 0, 0, 0))
        self.assertEqual(r.ready_step_ids, [])
        self.assertFalse(r.is_complete)
        self.assertFalse(r.is_blocked)

    def test_invalid_input_rejected(self):
        self.assertEqual(evaluate_plan_progress("x").codes(), [pb.READY_INVALID_PLAN])
        r = evaluate_plan_progress(mk([("pending", ["nope"])]))
        self.assertFalse(r.ok)
        self.assertEqual(r.codes(), [pb.FAIL_DEPENDENCY_GRAPH])
        self.assertEqual((r.total_steps, r.ready_step_ids, r.is_complete, r.is_blocked), (0, [], False, False))
        plan = mk([("pending", [])])
        plan.steps[0].status = "ready"
        self.assertEqual(evaluate_plan_progress(plan).codes(), [pb.READY_UNSUPPORTED_STATE])
        plan = mk([("pending", [])])
        plan.metadata["executed"] = "no"
        self.assertEqual(evaluate_plan_progress(plan).codes(), [pb.READY_INVALID_FLAG])

    def test_deterministic_and_ordering(self):
        plan = mk([("completed", []), ("pending", ["step-001"]), ("pending", []), ("failed", []),
                   ("pending", ["step-004"])], executed=True)
        first = evaluate_plan_progress(plan).to_dict()
        for _ in range(5):
            self.assertEqual(evaluate_plan_progress(plan).to_dict(), first)
        self.assertEqual(first["ready_step_ids"], ["step-002", "step-003"])
        self.assertEqual(first["blocked_step_ids"], ["step-005"])
        self.assertEqual([s.step_id for s in plan.steps], [f"step-{i:03d}" for i in range(1, 6)])

    def test_no_mutation(self):
        plan = mk([("completed", []), ("pending", ["step-001"]), ("failed", []), ("pending", ["step-003"])],
                  executed=True)
        before = copy.deepcopy(plan.to_dict())
        r = evaluate_plan_progress(plan)
        r.ready_step_ids.append("zzz")
        r.blocked_step_ids.clear()
        self.assertEqual(plan.to_dict(), before)
        self.assertTrue(plan.metadata["executed"])
        self.assertFalse(plan.metadata["execution_authorized"])

    def test_no_execution_imports(self):
        src = inspect.getsource(pb.evaluate_plan_progress)
        for word in ("subprocess", "socket", "open(", "process_input"):
            self.assertNotIn(word, src)


class TestDbUntouched(unittest.TestCase):
    def test_pristine_db(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
