"""Prompt 686 - deterministic plan step readiness. Pure in-memory tests; no database is opened."""
import copy
import hashlib
import os
import unittest

from planning import plan_builder as pb
from planning.plan import Plan, PlanStep
from planning.plan_builder import get_ready_plan_steps

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def mk(spec, executed=False, authorized=False):
    """spec: list of (state, deps) with ids step-001.. in order."""
    steps = [PlanStep(f"step-{i:03d}", f"do {i}", dependencies=deps, status=st)
             for i, (st, deps) in enumerate(spec, 1)]
    return Plan("p", "g", steps=steps, metadata={"phase": "planning", "executed": executed,
                                                 "execution_authorized": authorized})


class TestReadiness(unittest.TestCase):
    def test_independent_step_ready(self):
        res = get_ready_plan_steps(mk([("pending", [])]))
        self.assertTrue(res.ok)
        self.assertEqual(res.ready_step_ids, ["step-001"])
        self.assertFalse(res.executed)
        self.assertFalse(res.execution_authorized)

    def test_dependency_not_completed(self):
        res = get_ready_plan_steps(mk([("pending", []), ("pending", ["step-001"])]))
        self.assertEqual(res.ready_step_ids, ["step-001"])

    def test_completed_dependency(self):
        res = get_ready_plan_steps(mk([("completed", []), ("pending", ["step-001"])], executed=True))
        self.assertTrue(res.ok)
        self.assertEqual(res.ready_step_ids, ["step-002"])

    def test_multi_level(self):
        plan = mk([("completed", []), ("completed", ["step-001"]), ("pending", ["step-002"]),
                   ("pending", ["step-003"])], executed=True)
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, ["step-003"])
        plan = mk([("completed", []), ("pending", ["step-001"]), ("pending", ["step-002"])], executed=True)
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, ["step-002"])

    def test_multiple_ready_stable_order(self):
        plan = mk([("completed", []), ("pending", ["step-001"]), ("pending", []), ("pending", ["step-001"]),
                   ("pending", ["step-002"])], executed=True)
        first = get_ready_plan_steps(plan).ready_step_ids
        self.assertEqual(first, ["step-002", "step-003", "step-004"])
        for _ in range(5):
            self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, first)

    def test_failed_or_in_progress_dependency_blocks(self):
        for state in ("failed", "in_progress"):
            plan = mk([(state, []), ("pending", ["step-001"])], executed=True)
            res = get_ready_plan_steps(plan)
            self.assertTrue(res.ok)
            self.assertEqual(res.ready_step_ids, [])

    def test_non_pending_and_output_steps_not_ready(self):
        plan = mk([("completed", []), ("in_progress", []), ("failed", []), ("pending", [])], executed=True)
        plan.steps[3].set_output({"x": 1})
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, [])

    def test_authorized_plan_still_reports_ready_steps(self):   # corrected by Prompt 688
        res = get_ready_plan_steps(mk([("pending", [])], authorized=True))
        self.assertTrue(res.ok)
        self.assertEqual(res.ready_step_ids, ["step-001"])

    def test_invalid_graph_rejected(self):
        for spec in ([("pending", ["nope"])], [("pending", ["step-001"])],
                     [("pending", ["step-002"]), ("pending", ["step-001"])]):
            res = get_ready_plan_steps(mk(spec))
            self.assertFalse(res.ok)
            self.assertEqual(res.codes(), [pb.FAIL_DEPENDENCY_GRAPH])
            self.assertEqual(res.ready_step_ids, [])
        self.assertEqual(get_ready_plan_steps("nope").codes(), [pb.READY_INVALID_PLAN])

    def test_invalid_flags_and_states_rejected(self):
        plan = mk([("pending", [])])
        plan.metadata.pop("executed")
        self.assertEqual(get_ready_plan_steps(plan).codes(), [pb.READY_INVALID_FLAG])
        plan = mk([("pending", [])])
        plan.steps[0].status = "ready"
        self.assertEqual(get_ready_plan_steps(plan).codes(), [pb.READY_UNSUPPORTED_STATE])

    def test_no_mutation(self):
        plan = mk([("completed", []), ("pending", ["step-001"]), ("pending", [])], executed=True)
        before = copy.deepcopy(plan.to_dict())
        res = get_ready_plan_steps(plan)
        self.assertEqual(plan.to_dict(), before)
        for copy_step in res.steps:
            self.assertFalse(any(copy_step is s for s in plan.steps))
        res.steps[0].set_status("completed")
        res.steps[0].dependencies.append("zzz")
        self.assertEqual(plan.to_dict(), before)
        self.assertEqual(plan.metadata["executed"], True)
        self.assertFalse(plan.metadata["execution_authorized"])


class TestDbUntouched(unittest.TestCase):
    def test_pristine_db(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
