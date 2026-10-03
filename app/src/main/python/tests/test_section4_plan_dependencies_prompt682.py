"""Prompt 682 - deterministic plan step dependencies: declaration, validation, rejection.

Every test builds its own disposable database (tempfile); nothing here opens or writes the shipped database
except the read-only SHA-256 check."""
import ast
import copy
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

from core.core import Core
from planning import plan_builder as pb
from planning.plan import Plan, PlanStep
from planning.plan_builder import build_plan_from_context, validate_step_dependencies

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items")


def step(sid, deps=None):
    return PlanStep(sid, f"do {sid}", dependencies=deps)


def chain(*pairs):
    return [step(sid, deps) for sid, deps in pairs]


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

    def ctx(self, text):
        return self.core.prepare_request_context(text)

    def rich_plan(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.teach("Java", "another language", source="user")
        res = build_plan_from_context(self.ctx("What is Python and Java and Zorblax?"))
        self.assertTrue(res.ok)
        return res


class TestValidDependencyGraph(Base):
    def test_builder_output_has_valid_graph(self):
        res = self.rich_plan()
        dv = res.dependency_validation
        self.assertTrue(dv.valid)
        self.assertEqual(dv.issues, [])
        self.assertEqual(dv.ordered_step_ids, [s.step_id for s in res.plan.steps])
        self.assertEqual(dv.graph, {s.step_id: s.dependencies for s in res.plan.steps})
        json.dumps(res.to_dict())

    def test_meaningful_dependencies(self):
        plan = self.rich_plan().plan
        ids = [s.step_id for s in plan.steps]
        self.assertEqual(plan.steps[0].dependencies, [])
        for s in plan.steps[1:-1]:
            self.assertEqual(s.dependencies, ["step-001"], s.step_id)
        self.assertEqual(plan.steps[-1].dependencies, ids[:-1])

    def test_validator_accepts_plan_and_step_list(self):
        steps = chain(("a", []), ("b", ["a"]), ("c", ["a", "b"]))
        self.assertTrue(validate_step_dependencies(steps).valid)
        self.assertTrue(validate_step_dependencies(Plan("p", "g", steps=steps)).valid)


class TestIndependentSteps(Base):
    def test_review_and_gap_steps_are_mutually_independent(self):
        plan = self.rich_plan().plan
        middle = plan.steps[1:-1]
        self.assertGreaterEqual(len(middle), 3)
        middle_ids = {s.step_id for s in middle}
        for s in middle:
            self.assertFalse(set(s.dependencies) & middle_ids, s.step_id)

    def test_simple_request_adds_no_invented_dependencies(self):
        plan = build_plan_from_context(self.ctx("I want to build a calculator")).plan
        edges = sum(len(s.dependencies) for s in plan.steps)
        self.assertEqual(edges, len(plan.steps[-1].dependencies))
        self.assertEqual(plan.steps[0].dependencies, [])

    def test_validator_keeps_independent_steps_valid(self):
        res = validate_step_dependencies(chain(("a", []), ("b", []), ("c", [])))
        self.assertTrue(res.valid)
        self.assertEqual(res.graph, {"a": [], "b": [], "c": []})


class TestStableOrdering(Base):
    def test_dependency_lists_follow_step_order(self):
        plan = self.rich_plan().plan
        index = {s.step_id: i for i, s in enumerate(plan.steps)}
        for s in plan.steps:
            positions = [index[d] for d in s.dependencies]
            self.assertEqual(positions, sorted(positions))
            self.assertTrue(all(p < index[s.step_id] for p in positions))

    def test_unordered_dependency_list_rejected_not_sorted(self):
        steps = chain(("a", []), ("b", []), ("c", ["b", "a"]))
        res = validate_step_dependencies(steps)
        self.assertFalse(res.valid)
        self.assertEqual(res.codes(), [pb.DEP_UNORDERED])
        self.assertEqual(steps[2].dependencies, ["b", "a"])  # never silently repaired

    def test_forward_dependency_rejected(self):
        res = validate_step_dependencies(chain(("a", ["b"]), ("b", [])))
        self.assertEqual(res.codes(), [pb.DEP_FORWARD])

    def test_issue_order_is_step_order(self):
        steps = chain(("a", ["zz"]), ("b", ["b"]), ("c", ["a", "a"]))
        self.assertEqual(validate_step_dependencies(steps).codes(),
                         [pb.DEP_UNKNOWN, pb.DEP_SELF, pb.DEP_DUPLICATE])


class TestInvalidGraphs(Base):
    def assertBuilderRejects(self, steps, code):
        with mock.patch.object(pb, "_build_steps", return_value=(steps, [])):
            res = build_plan_from_context(self.ctx("I want to build a calculator"))
        self.assertFalse(res.ok)
        self.assertEqual(res.status, pb.STATUS_REJECTED)
        self.assertIsNone(res.plan)
        self.assertIsNone(res.validation)
        self.assertEqual(res.codes(), [pb.FAIL_DEPENDENCY_GRAPH])
        self.assertIn(code, [i["code"] for i in res.failures[0]["issues"]])
        self.assertFalse(res.dependency_validation.valid)
        self.assertEqual((res.executed, res.execution_authorized), (False, False))
        json.dumps(res.to_dict())
        return res

    def test_unknown_dependency(self):
        steps = chain(("step-001", []), ("step-002", ["step-099"]))
        res = validate_step_dependencies(steps)
        self.assertEqual(res.codes(), [pb.DEP_UNKNOWN])
        self.assertEqual(res.issues[0]["dependency"], "step-099")
        self.assertEqual(steps[1].dependencies, ["step-099"])
        self.assertBuilderRejects(steps, pb.DEP_UNKNOWN)

    def test_non_string_dependency_is_unknown(self):
        res = validate_step_dependencies(chain(("a", []), ("b", [None, 5])))
        self.assertEqual(res.codes(), [pb.DEP_UNKNOWN, pb.DEP_UNKNOWN])

    def test_self_dependency(self):
        steps = chain(("step-001", []), ("step-002", ["step-002"]))
        res = validate_step_dependencies(steps)
        self.assertEqual(res.codes(), [pb.DEP_SELF])
        self.assertBuilderRejects(steps, pb.DEP_SELF)

    def test_cycle(self):
        steps = chain(("step-001", ["step-002"]), ("step-002", ["step-001"]))
        res = validate_step_dependencies(steps)
        self.assertTrue(res.has(pb.DEP_CYCLE))
        cyc = [i for i in res.issues if i["code"] == pb.DEP_CYCLE][0]["cycle"]
        self.assertEqual(cyc, ["step-001", "step-002", "step-001"])
        self.assertBuilderRejects(steps, pb.DEP_CYCLE)

    def test_longer_cycle_detected(self):
        res = validate_step_dependencies(chain(("a", ["c"]), ("b", ["a"]), ("c", ["b"])))
        self.assertTrue(res.has(pb.DEP_CYCLE))

    def test_duplicate_dependency(self):
        steps = chain(("step-001", []), ("step-002", ["step-001", "step-001"]))
        res = validate_step_dependencies(steps)
        self.assertEqual(res.codes(), [pb.DEP_DUPLICATE])
        self.assertEqual(steps[1].dependencies, ["step-001", "step-001"])
        self.assertBuilderRejects(steps, pb.DEP_DUPLICATE)

    def test_duplicate_step_id_and_non_list_dependencies(self):
        self.assertEqual(validate_step_dependencies(chain(("a", []), ("a", []))).codes(),
                         [pb.DEP_DUPLICATE_STEP_ID])
        bad = chain(("a", []), ("b", []))
        bad[1].dependencies = "a"
        self.assertEqual(validate_step_dependencies(bad).codes(), [pb.DEP_INVALID_DEPENDENCIES])

    def test_bad_inputs_never_raise(self):
        for bad in (None, 5, "x", {}, object()):
            res = validate_step_dependencies(bad)
            self.assertFalse(res.valid)
            self.assertEqual(res.codes(), [pb.DEP_INVALID_DEPENDENCIES])

    def test_invalid_graph_never_reaches_existing_validator_or_plan(self):
        steps = chain(("step-001", []), ("step-002", ["step-002"]))
        with mock.patch.object(pb, "_build_steps", return_value=(steps, [])), \
                mock.patch.object(pb, "validate_plan") as vp:
            res = build_plan_from_context(self.ctx("I want to build a calculator"))
        vp.assert_not_called()
        self.assertIsNone(res.plan)


class TestDeterminism(Base):
    def test_same_context_same_plan_and_graph(self):
        self.ls.teach("Python", "a language", source="user")
        a = build_plan_from_context(self.ctx("What is Python and Zorblax?")).to_dict()
        b = build_plan_from_context(self.ctx("What is Python and Zorblax?")).to_dict()
        self.assertEqual(a, b)
        self.assertEqual(a["dependency_validation"]["graph"],
                         {s["step_id"]: s["dependencies"] for s in a["plan"]["steps"]})

    def test_rejection_output_is_deterministic(self):
        def run():
            steps = chain(("step-001", ["step-002"]), ("step-002", ["step-001", "step-001", "nope"]))
            with mock.patch.object(pb, "_build_steps", return_value=(steps, [])):
                return build_plan_from_context(self.ctx("I want to build a calculator")).to_dict()
        first = run()
        self.assertEqual(first, run())
        self.assertEqual([i["code"] for i in first["failures"][0]["issues"]],
                         [pb.DEP_FORWARD, pb.DEP_DUPLICATE, pb.DEP_UNKNOWN, pb.DEP_CYCLE])

    def test_validator_is_repeatable(self):
        steps = chain(("a", []), ("b", ["a", "a", "x"]), ("c", ["c"]))
        self.assertEqual(validate_step_dependencies(steps).to_dict(), validate_step_dependencies(steps).to_dict())


class TestNoSideEffects(Base):
    def test_validator_does_not_mutate_steps_or_plan(self):
        plan = Plan("p", "g", steps=chain(("a", ["b", "b"]), ("b", ["a"]), ("c", ["zz", "c"])))
        before = copy.deepcopy(plan.to_dict())
        validate_step_dependencies(plan)
        self.assertEqual(plan.to_dict(), before)
        self.assertTrue(all(s.status == "pending" for s in plan.steps))

    def test_planning_writes_nothing_and_stays_unexecuted(self):
        self.ls.teach("Python", "a language", source="user")
        ctx = self.ctx("What is Python?")
        before_ctx, before_db = ctx.to_dict(), self.snap()
        for _ in range(3):
            res = build_plan_from_context(ctx)
        self.assertEqual(ctx.to_dict(), before_ctx)
        self.assertEqual(self.snap(), before_db)
        self.assertIsNone(ctx.proposed_plan)
        self.assertEqual((res.executed, res.execution_authorized), (False, False))
        self.assertIs(res.plan.metadata["executed"], False)
        self.assertIs(res.plan.metadata["execution_authorized"], False)
        self.assertTrue(all(s.status == "pending" and s.output_data is None for s in res.plan.steps))

    def test_rejected_dependency_planning_writes_nothing(self):
        before = self.snap()
        steps = chain(("step-001", ["step-001"]))
        with mock.patch.object(pb, "_build_steps", return_value=(steps, [])):
            build_plan_from_context(self.ctx("I want to build a calculator"))
        self.assertEqual(self.snap(), before)

    def test_module_stays_dependency_free(self):
        with open(os.path.join(PY_ROOT, "planning", "plan_builder.py"), encoding="utf-8") as fh:
            src = fh.read()
        mods = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertEqual(mods, {"hashlib", "planning"})

    def test_shipped_database_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
