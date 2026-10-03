"""Prompt 684 - deterministic plan step state validation.

Every test builds its own disposable database (tempfile); nothing here opens or writes the shipped database
except the read-only SHA-256 check."""
import ast
import copy
import hashlib
import json
import os
import tempfile
import unittest

from core.core import Core
from planning import plan_builder as pb
from planning.plan import Plan, PlanStep
from planning.plan_builder import (build_plan_from_context, order_plan_steps, validate_plan_step_states)

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items")


def mk(states, executed=False, authorized=False, outputs=None, plan_status="pending", flags=True):
    outputs = outputs or {}
    steps = [PlanStep(f"step-{i:03d}", f"do {i}", status=st, output_data=outputs.get(i))
             for i, st in enumerate(states, 1)]
    md = {"phase": "planning"}
    if flags:
        md.update({"executed": executed, "execution_authorized": authorized})
    return Plan("p", "g", steps=steps, status=plan_status, metadata=md)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.core = Core(memory_db_path=os.path.join(self.tmp, "c.db"),
                         skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.ls, self.m = self.core.learning, self.core.memory

    def tearDown(self):
        try:
            self.m._conn.close()
        except Exception:  # noqa: BLE001
            pass

    def snap(self):
        return {t: self.m.query(f"SELECT * FROM {t} ORDER BY id") for t in TABLES}


class TestValidStates(Base):
    def test_supported_state_set(self):
        self.assertEqual(pb.STEP_STATES, ("pending", "in_progress", "completed", "failed"))

    def test_all_pending_unexecuted_unauthorized_is_valid(self):
        res = validate_plan_step_states(mk(["pending", "pending"]))
        self.assertTrue(res.valid)
        self.assertEqual(res.issues, [])
        self.assertEqual(res.states, {"step-001": "pending", "step-002": "pending"})
        json.dumps(res.to_dict())

    def test_executed_authorized_plan_with_progress_is_valid(self):
        plan = mk(["completed", "in_progress", "pending"], executed=True, authorized=True,
                  outputs={1: {"ok": True}}, plan_status="in_progress")
        self.assertTrue(validate_plan_step_states(plan).valid)
        self.assertTrue(validate_plan_step_states(mk(["failed"], True, True, plan_status="failed")).valid)

    def test_generated_plans_unchanged_and_valid(self):
        self.ls.teach("Python", "a language", source="user")
        for text in ("I want to build a calculator", "What is Python and Zorblax?"):
            built = build_plan_from_context(self.core.prepare_request_context(text))
            self.assertTrue(built.ok)
            self.assertTrue(validate_plan_step_states(built.plan).valid)
            self.assertTrue(all(s.status == "pending" and s.output_data is None for s in built.plan.steps))
            self.assertIs(built.plan.metadata["executed"], False)
            self.assertIs(built.plan.metadata["execution_authorized"], False)
            ordered = order_plan_steps(built.plan)
            self.assertTrue(all(s.status == "pending" for s in ordered.steps))


class TestInvalidValues(unittest.TestCase):
    def test_unsupported_step_states(self):
        for bad in ("ready", "blocked", "cancelled", "done", "", None, 5):
            plan = mk(["pending", "pending"])
            plan.steps[1].status = bad     # bypass set_status on purpose: the validator must still catch it
            res = validate_plan_step_states(plan)
            self.assertFalse(res.valid, bad)
            self.assertEqual(res.codes(), [pb.STATE_UNSUPPORTED], bad)
            self.assertEqual(res.issues[0]["step_id"], "step-002")

    def test_unsupported_plan_state(self):
        plan = mk(["pending"])
        plan.status = "weird"
        self.assertEqual(validate_plan_step_states(plan).codes(), [pb.STATE_UNSUPPORTED])

    def test_empty_or_non_string_ids(self):
        for bad in ("", "   ", None, 7):
            plan = mk(["pending", "pending"])
            plan.steps[0].step_id = bad
            res = validate_plan_step_states(plan)
            self.assertEqual(res.codes(), [pb.STATE_INVALID_STEP_ID], bad)
            self.assertEqual(res.issues[0]["index"], 0)

    def test_non_flag_values(self):
        for bad in (None, 0, 1, "false", "true", [], {}):
            plan = mk(["pending"])
            plan.metadata["executed"] = bad
            res = validate_plan_step_states(plan)
            self.assertEqual(res.codes(), [pb.STATE_INVALID_FLAG], repr(bad))
            self.assertEqual(res.issues[0]["flag"], "executed")
            plan = mk(["pending"])
            plan.metadata["execution_authorized"] = bad
            self.assertEqual(validate_plan_step_states(plan).issues[0]["flag"], "execution_authorized")

    def test_missing_flags(self):
        res = validate_plan_step_states(mk(["pending"], flags=False))
        self.assertEqual(res.codes(), [pb.STATE_INVALID_FLAG, pb.STATE_INVALID_FLAG])
        self.assertEqual([i["flag"] for i in res.issues], ["executed", "execution_authorized"])

    def test_non_plan_inputs_never_raise(self):
        for bad in (None, 5, "x", {}, [], object()):
            res = validate_plan_step_states(bad)
            self.assertEqual(res.codes(), [pb.STATE_INVALID_PLAN])
            self.assertFalse(res.valid)


class TestContradictoryFlags(unittest.TestCase):
    def test_execution_states_without_execution(self):
        for st in ("in_progress", "completed", "failed"):
            res = validate_plan_step_states(mk([st], executed=False, authorized=False))
            self.assertEqual(res.codes(), [pb.STATE_EXECUTION_NOT_OCCURRED, pb.STATE_UNAUTHORIZED_EXECUTION], st)

    def test_output_implies_execution(self):
        res = validate_plan_step_states(mk(["pending"], outputs={1: {"x": 1}}))
        self.assertTrue(res.has(pb.STATE_EXECUTED_PENDING))
        self.assertTrue(res.has(pb.STATE_EXECUTION_NOT_OCCURRED))

    def test_executed_step_cannot_remain_pending(self):
        res = validate_plan_step_states(mk(["pending", "completed"], True, True, outputs={1: {"x": 1}},
                                           plan_status="in_progress"))
        self.assertEqual(res.codes(), [pb.STATE_EXECUTED_PENDING])
        self.assertEqual(res.issues[0]["step_id"], "step-001")

    def test_plan_state_implies_execution(self):
        res = validate_plan_step_states(mk(["pending"], plan_status="completed"))
        self.assertEqual(res.codes(), [pb.STATE_EXECUTION_NOT_OCCURRED])

    def test_executed_without_authorization(self):
        res = validate_plan_step_states(mk(["completed"], executed=True, authorized=False))
        self.assertEqual(res.codes(), [pb.STATE_UNAUTHORIZED_EXECUTION, pb.STATE_UNAUTHORIZED_EXECUTION])

    def test_executed_flag_without_any_progress(self):
        res = validate_plan_step_states(mk(["pending", "pending"], executed=True, authorized=True))
        self.assertEqual(res.codes(), [pb.STATE_EXECUTED_NO_PROGRESS])

    def test_authorized_but_unexecuted_is_allowed(self):
        self.assertTrue(validate_plan_step_states(mk(["pending"], executed=False, authorized=True)).valid)


class TestDuplicateIds(unittest.TestCase):
    def test_duplicate_step_ids(self):
        plan = mk(["pending", "pending", "pending"])
        plan.steps[2].step_id = "step-001"
        res = validate_plan_step_states(plan)
        self.assertEqual(res.codes(), [pb.STATE_DUPLICATE_STEP_ID])
        self.assertEqual(res.issues[0]["step_id"], "step-001")
        self.assertEqual(sorted(res.states), ["step-001", "step-002"])


class TestDeterminismAndNoSideEffects(Base):
    def test_repeatable_output_and_stable_issue_order(self):
        def bad():
            plan = mk(["completed", "ready", "pending"], executed=False, authorized=False,
                      outputs={3: {"x": 1}})
            plan.steps[2].step_id = "step-001"
            plan.metadata["execution_authorized"] = "no"
            return plan
        first = validate_plan_step_states(bad()).to_dict()
        for _ in range(5):
            self.assertEqual(validate_plan_step_states(bad()).to_dict(), first)
        self.assertEqual([i["code"] for i in first["issues"]],
                         [pb.STATE_INVALID_FLAG, pb.STATE_EXECUTION_NOT_OCCURRED, pb.STATE_UNSUPPORTED,
                          pb.STATE_DUPLICATE_STEP_ID])

    def test_input_never_mutated_or_repaired(self):
        plan = mk(["completed", "pending", "pending"], executed=False, authorized=None, outputs={3: {"x": 1}})
        plan.steps[1].status = "bogus"
        before = copy.deepcopy(plan.to_dict())
        validate_plan_step_states(plan)
        self.assertEqual(plan.to_dict(), before)
        self.assertEqual(plan.steps[1].status, "bogus")
        self.assertIsNone(plan.metadata["execution_authorized"])

    def test_no_writes_no_execution(self):
        self.ls.teach("Python", "a language", source="user")
        built = build_plan_from_context(self.core.prepare_request_context("What is Python?"))
        before_db, before_plan = self.snap(), built.plan.to_dict()
        for _ in range(3):
            validate_plan_step_states(built.plan)
        self.assertEqual(self.snap(), before_db)
        self.assertEqual(built.plan.to_dict(), before_plan)
        self.assertEqual((built.executed, built.execution_authorized), (False, False))

    def test_module_stays_dependency_free_and_core_untouched(self):
        with open(os.path.join(PY_ROOT, "planning", "plan_builder.py"), encoding="utf-8") as fh:
            src = fh.read()
        mods = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertEqual(mods, {"hashlib", "planning"})
        with open(os.path.join(PY_ROOT, "core", "core.py"), encoding="utf-8") as fh:
            self.assertNotIn("validate_plan_step_states", fh.read())

    def test_shipped_database_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
