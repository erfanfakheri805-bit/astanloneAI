"""Prompt 683 - deterministic stable topological ordering of validated plan steps.

Every test builds its own disposable database (tempfile); nothing here opens or writes the shipped database
except the read-only SHA-256 check."""
import copy
import hashlib
import json
import os
import tempfile
import unittest

from core.core import Core
from planning import plan_builder as pb
from planning.plan import Plan, PlanStep
from planning.plan_builder import build_plan_from_context, order_plan_steps

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items")


def steps(*pairs):
    return [PlanStep(sid, f"do {sid}", dependencies=deps, input_data={"n": sid}) for sid, deps in pairs]


def position(result):
    return {sid: i for i, sid in enumerate(result.ordered_step_ids)}


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


class TestDependencyBeforeDependent(unittest.TestCase):
    def test_every_dependency_precedes_its_dependent(self):
        plan = Plan("p", "g", steps=steps(("a", []), ("b", ["a"]), ("c", ["a", "b"]), ("d", ["c"])))
        res = order_plan_steps(plan)
        self.assertTrue(res.ok)
        self.assertEqual(res.status, pb.STATUS_ORDERED)
        pos = position(res)
        for s in plan.steps:
            for dep in s.dependencies:
                self.assertLess(pos[dep], pos[s.step_id])
        self.assertEqual(res.ordered_step_ids, ["a", "b", "c", "d"])
        self.assertEqual([s.step_id for s in res.steps], res.ordered_step_ids)
        json.dumps(res.to_dict())

    def test_accepts_plain_step_list(self):
        res = order_plan_steps(steps(("a", []), ("b", ["a"])))
        self.assertEqual(res.ordered_step_ids, ["a", "b"])


class TestStableIndependentOrder(unittest.TestCase):
    def test_independent_steps_keep_declared_order(self):
        res = order_plan_steps(steps(("z", []), ("m", []), ("a", []), ("k", [])))
        self.assertEqual(res.ordered_step_ids, ["z", "m", "a", "k"])   # declared order, not sorted by name

    def test_independent_branches_keep_declared_order(self):
        res = order_plan_steps(steps(("root", []), ("x", ["root"]), ("y", ["root"]), ("w", ["root"]),
                                     ("end", ["x", "y", "w"])))
        self.assertEqual(res.ordered_step_ids, ["root", "x", "y", "w", "end"])

    def test_builder_output_orders_to_its_declared_ids(self):
        plan = self._rich_plan()
        res = order_plan_steps(plan)
        self.assertTrue(res.ok)
        self.assertEqual(res.ordered_step_ids, [s.step_id for s in plan.steps])

    def _rich_plan(self):
        tmp = tempfile.mkdtemp()
        core = Core(memory_db_path=os.path.join(tmp, "c.db"), skill_definitions_dir=os.path.join(tmp, "s"))
        try:
            core.learning.teach("Python", "a language", source="user")
            core.learning.teach("Java", "another language", source="user")
            built = build_plan_from_context(core.prepare_request_context("What is Python and Java and Zorblax?"))
            self.assertTrue(built.ok)
            return built.plan
        finally:
            core.memory._conn.close()


class TestMultiLevel(unittest.TestCase):
    def test_multi_level_graph(self):
        plan = Plan("p", "g", steps=steps(("s1", []), ("s2", ["s1"]), ("s3", ["s1"]), ("s4", ["s2"]),
                                          ("s5", ["s3", "s4"]), ("s6", ["s1", "s5"])))
        res = order_plan_steps(plan)
        self.assertTrue(res.ok)
        pos = position(res)
        for s in plan.steps:
            for dep in s.dependencies:
                self.assertLess(pos[dep], pos[s.step_id])
        self.assertEqual(res.ordered_step_ids, ["s1", "s2", "s3", "s4", "s5", "s6"])
        self.assertEqual(sorted(res.ordered_step_ids), sorted(s.step_id for s in plan.steps))


class TestDeterminism(unittest.TestCase):
    def test_repeated_ordering_identical(self):
        def make():
            return Plan("p", "g", steps=steps(("a", []), ("b", []), ("c", ["a"]), ("d", ["a", "b"]),
                                              ("e", ["c", "d"])))
        first = order_plan_steps(make()).to_dict()
        for _ in range(5):
            self.assertEqual(order_plan_steps(make()).to_dict(), first)
        plan = make()
        self.assertEqual(order_plan_steps(plan).to_dict(), order_plan_steps(plan).to_dict())

    def test_rejection_is_deterministic(self):
        def run():
            return order_plan_steps(steps(("a", ["b"]), ("b", ["a"]))).to_dict()
        self.assertEqual(run(), run())


class TestInvalidGraphRejection(unittest.TestCase):
    def assertRejected(self, res, issue_code):
        self.assertFalse(res.ok)
        self.assertEqual(res.status, pb.STATUS_REJECTED)
        self.assertEqual(res.codes(), [pb.FAIL_DEPENDENCY_GRAPH])
        self.assertIn(issue_code, [i["code"] for i in res.failures[0]["issues"]])
        self.assertEqual(res.ordered_step_ids, [])
        self.assertEqual(res.steps, [])
        self.assertFalse(res.dependency_validation.valid)
        self.assertEqual((res.executed, res.execution_authorized), (False, False))
        json.dumps(res.to_dict())

    def test_cycle(self):
        self.assertRejected(order_plan_steps(steps(("a", ["b"]), ("b", ["a"]))), pb.DEP_CYCLE)

    def test_self_unknown_duplicate(self):
        self.assertRejected(order_plan_steps(steps(("a", ["a"]))), pb.DEP_SELF)
        self.assertRejected(order_plan_steps(steps(("a", []), ("b", ["zz"]))), pb.DEP_UNKNOWN)
        self.assertRejected(order_plan_steps(steps(("a", []), ("b", ["a", "a"]))), pb.DEP_DUPLICATE)

    def test_forward_and_unordered_are_rejected_not_reordered(self):
        forward = steps(("a", ["b"]), ("b", []))
        self.assertRejected(order_plan_steps(forward), pb.DEP_FORWARD)
        self.assertEqual([s.step_id for s in forward], ["a", "b"])
        unordered = steps(("a", []), ("b", []), ("c", ["b", "a"]))
        self.assertRejected(order_plan_steps(unordered), pb.DEP_UNORDERED)
        self.assertEqual(unordered[2].dependencies, ["b", "a"])

    def test_bad_inputs_never_raise(self):
        for bad in (None, 5, "x", {}, object()):
            res = order_plan_steps(bad)
            self.assertFalse(res.ok)
            self.assertEqual(res.codes(), [pb.FAIL_DEPENDENCY_GRAPH])


class TestOriginalUnchanged(unittest.TestCase):
    def test_plan_not_mutated_and_result_steps_are_copies(self):
        plan = Plan("p", "g", steps=steps(("a", []), ("b", ["a"]), ("c", ["a", "b"])), warnings=["w"],
                    metadata={"k": "v"})
        before = copy.deepcopy(plan.to_dict())
        original_steps = list(plan.steps)
        res = order_plan_steps(plan)
        self.assertEqual(plan.to_dict(), before)
        self.assertEqual(plan.steps, original_steps)
        for orig, new in zip(plan.steps, res.steps):
            self.assertIsNot(orig, new)
            self.assertIsNot(orig.dependencies, new.dependencies)
            self.assertEqual(orig.to_dict(), new.to_dict())
        res.steps[2].dependencies.append("x")
        res.steps[0].set_input({"changed": True})
        self.assertEqual(plan.to_dict(), before)

    def test_rejected_input_not_mutated(self):
        bad = steps(("a", ["b", "b"]), ("b", ["a"]))
        before = [s.to_dict() for s in bad]
        order_plan_steps(bad)
        self.assertEqual([s.to_dict() for s in bad], before)

    def test_generated_ids_and_dependencies_unchanged(self):
        plan = TestStableIndependentOrder()._rich_plan()
        before = [(s.step_id, list(s.dependencies)) for s in plan.steps]
        res = order_plan_steps(plan)
        self.assertEqual([(s.step_id, s.dependencies) for s in res.steps], before)
        self.assertEqual([(s.step_id, s.dependencies) for s in plan.steps], before)


class TestNoExecutionNoSideEffects(Base):
    def test_ordering_executes_nothing_and_writes_nothing(self):
        self.ls.teach("Python", "a language", source="user")
        built = build_plan_from_context(self.core.prepare_request_context("What is Python?"))
        before_db, before_plan = self.snap(), built.plan.to_dict()
        for _ in range(3):
            res = order_plan_steps(built.plan)
        self.assertEqual(self.snap(), before_db)
        self.assertEqual(built.plan.to_dict(), before_plan)
        self.assertEqual((res.executed, res.execution_authorized), (False, False))
        self.assertTrue(all(s.status == "pending" and s.output_data is None for s in res.steps))
        self.assertIs(built.plan.metadata["executed"], False)
        self.assertIs(built.plan.metadata["execution_authorized"], False)

    def test_result_has_no_execution_surface(self):
        res = order_plan_steps(steps(("a", [])))
        for name in dir(res):
            if callable(getattr(res, name)) and not name.startswith("__"):
                self.assertFalse(name.lstrip("_").startswith(("run", "execute", "start", "apply", "invoke")), name)

    def test_process_input_and_core_do_not_reference_ordering(self):
        with open(os.path.join(PY_ROOT, "core", "core.py"), encoding="utf-8") as fh:
            self.assertNotIn("order_plan_steps", fh.read())

    def test_shipped_database_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
