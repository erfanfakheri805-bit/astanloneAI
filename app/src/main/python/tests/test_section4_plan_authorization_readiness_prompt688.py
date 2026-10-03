"""Prompt 688 - plan authorization (permission) vs step readiness/execution (evidence). Pure in-memory tests."""
import copy
import hashlib
import os
import unittest

from planning import plan_builder as pb
from planning.plan import Plan, PlanStep
from planning.plan_builder import evaluate_plan_progress, get_ready_plan_steps, validate_plan_step_states

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def mk(spec, executed=False, authorized=False):
    steps = [PlanStep(f"step-{i:03d}", f"do {i}", dependencies=deps, status=st)
             for i, (st, deps) in enumerate(spec, 1)]
    return Plan("p", "g", steps=steps, metadata={"phase": "planning", "executed": executed,
                                                 "execution_authorized": authorized})


SPEC = [("pending", []), ("pending", ["step-001"]), ("pending", [])]


class TestAuthorizationVsReadiness(unittest.TestCase):
    def test_unauthorized_ready_steps(self):
        res = get_ready_plan_steps(mk(SPEC))
        self.assertTrue(res.ok)
        self.assertEqual(res.ready_step_ids, ["step-001", "step-003"])

    def test_authorized_same_ready_steps(self):
        un = get_ready_plan_steps(mk(SPEC))
        au = get_ready_plan_steps(mk(SPEC, authorized=True))
        self.assertTrue(au.ok)
        self.assertEqual(au.ready_step_ids, un.ready_step_ids)
        self.assertEqual([s.to_dict() for s in au.steps], [s.to_dict() for s in un.steps])

    def test_authorized_completed_and_remaining_ready(self):
        plan = mk([("completed", []), ("pending", ["step-001"]), ("pending", ["step-002"]), ("pending", [])],
                  executed=True, authorized=True)
        plan.steps[0].set_output({"x": 1})
        self.assertTrue(validate_plan_step_states(plan).valid)
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, ["step-002", "step-004"])

    def test_authorized_no_ready_steps(self):
        for spec, ex in (([("completed", []), ("completed", ["step-001"])], True),
                         ([("in_progress", []), ("pending", ["step-001"])], True),
                         ([("failed", []), ("pending", ["step-001"])], True),
                         ([], False)):
            res = get_ready_plan_steps(mk(spec, executed=ex, authorized=True))
            self.assertTrue(res.ok)
            self.assertEqual(res.ready_step_ids, [])

    def test_pending_step_with_output_never_ready_even_if_authorized(self):
        plan = mk([("pending", [])], authorized=True)
        plan.steps[0].set_output({"x": 1})
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, [])
        self.assertIn(pb.STATE_EXECUTED_PENDING, validate_plan_step_states(plan).codes())

    def test_dependencies_still_required_when_authorized(self):
        res = get_ready_plan_steps(mk([("in_progress", []), ("pending", ["step-001"])], executed=True,
                                      authorized=True))
        self.assertEqual(res.ready_step_ids, [])
        res = get_ready_plan_steps(mk([("pending", ["nope"])], authorized=True))
        self.assertFalse(res.ok)
        self.assertEqual(res.codes(), [pb.FAIL_DEPENDENCY_GRAPH])

    def test_authorization_marks_nothing_executed(self):
        plan = mk(SPEC, authorized=True)
        self.assertTrue(validate_plan_step_states(plan).valid)     # authorized-but-unexecuted is valid
        for fn in (get_ready_plan_steps, evaluate_plan_progress):
            r = fn(plan)
            self.assertFalse(r.executed)
            self.assertFalse(r.execution_authorized)               # queries never authorize/execute
        self.assertEqual([s.status for s in plan.steps], ["pending"] * 3)
        self.assertTrue(all(s.output_data is None for s in plan.steps))
        self.assertFalse(plan.metadata["executed"])
        self.assertTrue(plan.metadata["execution_authorized"])

    def test_progress_consistent(self):
        for authorized in (False, True):
            plan = mk(SPEC, authorized=authorized)
            r = evaluate_plan_progress(plan)
            self.assertTrue(r.ok)
            self.assertEqual(r.ready_step_ids, get_ready_plan_steps(plan).ready_step_ids)
            self.assertEqual((r.pending_count, r.completed_count), (3, 0))
            self.assertFalse(r.is_complete)
            self.assertFalse(r.is_blocked)
        done = evaluate_plan_progress(mk([("completed", [])], executed=True, authorized=True))
        self.assertTrue(done.is_complete)
        self.assertEqual(done.ready_step_ids, [])
        blocked = evaluate_plan_progress(mk([("failed", []), ("pending", ["step-001"])], executed=True,
                                            authorized=True))
        self.assertTrue(blocked.is_blocked)
        self.assertEqual(blocked.ready_step_ids, [])

    def test_invalid_combinations_still_rejected(self):
        # execution implied without authorization / execution flag
        p = mk([("completed", [])], executed=True, authorized=False)
        self.assertIn(pb.STATE_UNAUTHORIZED_EXECUTION, validate_plan_step_states(p).codes())
        p = mk([("completed", [])], executed=False, authorized=True)
        self.assertIn(pb.STATE_EXECUTION_NOT_OCCURRED, validate_plan_step_states(p).codes())
        p = mk([("pending", [])], executed=True, authorized=True)
        self.assertIn(pb.STATE_EXECUTED_NO_PROGRESS, validate_plan_step_states(p).codes())
        # non-boolean flags rejected by readiness and progress, authorized or not
        for bad in (1, 0, "true", None):
            p = mk([("pending", [])])
            p.metadata["execution_authorized"] = bad
            self.assertEqual(get_ready_plan_steps(p).codes(), [pb.READY_INVALID_FLAG])
            self.assertFalse(evaluate_plan_progress(p).ok)
            self.assertIn(pb.STATE_INVALID_FLAG, validate_plan_step_states(p).codes())
        p = mk([("pending", [])], authorized=True)
        p.steps[0].status = "bogus"
        self.assertEqual(get_ready_plan_steps(p).codes(), [pb.READY_UNSUPPORTED_STATE])

    def test_deterministic_and_no_mutation(self):
        plan = mk(SPEC, authorized=True)
        before = copy.deepcopy(plan.to_dict())
        a, b = get_ready_plan_steps(plan), get_ready_plan_steps(plan)
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(evaluate_plan_progress(plan).to_dict(), evaluate_plan_progress(plan).to_dict())
        validate_plan_step_states(plan)
        self.assertEqual(plan.to_dict(), before)
        for s in a.steps:
            self.assertFalse(any(s is o for o in plan.steps))
        a.steps[0].set_status("completed")
        self.assertEqual(plan.to_dict(), before)


class TestDbUntouched(unittest.TestCase):
    def test_pristine_db(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
