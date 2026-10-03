"""Prompt 681 - deterministic plan builder: RequestContext -> unexecuted Plan.

Every test builds its own disposable database (tempfile); nothing here opens or writes the shipped database
except the read-only SHA-256 check."""
import ast
import hashlib
import json
import os
import tempfile
import unittest

from core.core import Core
from planning import plan_builder as pb
from planning.plan import Plan
from planning.plan_builder import PlanBuildResult, build_plan_from_context
from planning.plan_validation import validate_plan
from planning.request_context import RequestContext

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items")


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

    def ctx(self, text="I want to build a calculator"):
        return self.core.prepare_request_context(text)


class TestValidContextToPlan(Base):
    def test_goal_context_produces_planned_result(self):
        res = build_plan_from_context(self.ctx())
        self.assertIsInstance(res, PlanBuildResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.status, pb.STATUS_PLANNED)
        self.assertIsInstance(res.plan, Plan)
        self.assertEqual(res.failures, [])
        self.assertTrue(res.validation.valid)
        self.assertEqual(res.validation.ordered_step_ids, [s.step_id for s in res.plan.steps])
        json.dumps(res.to_dict())

    def test_original_request_and_intent_preserved(self):
        raw = "  I want   to build a calculator "
        ctx = self.ctx(raw)
        res = self.core.build_plan_from_context(ctx)
        md = res.plan.metadata
        self.assertEqual(md["original_input"], raw)
        self.assertEqual(md["normalized_request"], ctx.normalized_request)
        self.assertEqual(md["intent"], ctx.intent)
        self.assertEqual(md["goal"], ctx.goal)
        self.assertEqual(res.plan.steps[0].input_data["original_input"], raw)

    def test_question_context_with_current_knowledge_gets_review_step(self):
        self.ls.teach("Python", "a language", source="user")
        res = build_plan_from_context(self.ctx("What is Python?"))
        self.assertTrue(res.ok)
        descs = [s.description for s in res.plan.steps]
        self.assertTrue(any("Review current knowledge about Python" in d for d in descs))
        review = [s for s in res.plan.steps if s.expected_output == "knowledge_reviewed"]
        self.assertEqual(review[0].dependencies, ["step-001"])

    def test_non_blocking_gap_becomes_step_and_warning(self):
        res = build_plan_from_context(self.ctx("What is Zorblax?"))
        self.assertTrue(res.ok)
        gap_steps = [s for s in res.plan.steps if s.expected_output == "gap_addressed"]
        self.assertTrue(gap_steps)
        self.assertEqual(gap_steps[0].input_data["code"], "UNKNOWN_INFORMATION")
        self.assertTrue(any("UNKNOWN_INFORMATION" in w for w in res.plan.warnings))


class TestDeterminismAndOrdering(Base):
    def test_same_context_same_plan(self):
        a = build_plan_from_context(self.ctx()).to_dict()
        b = build_plan_from_context(self.ctx()).to_dict()
        self.assertEqual(a, b)
        c = build_plan_from_context(self.ctx())
        self.assertEqual(c.to_dict(), a)

    def test_ids_derive_from_content_only(self):
        a = build_plan_from_context(self.ctx("I want to build a calculator")).plan
        b = build_plan_from_context(self.ctx("I want to build a calculator")).plan
        c = build_plan_from_context(self.ctx("I want to build a website")).plan
        self.assertEqual((a.plan_id, a.goal_id), (b.plan_id, b.goal_id))
        self.assertNotEqual(a.plan_id, c.plan_id)
        self.assertTrue(a.plan_id.startswith("plan-") and a.goal_id.startswith("request-"))
        self.assertEqual(a.created_at, pb.PLAN_CREATED_AT)

    def test_step_ids_sequential_unique_and_ordered(self):
        self.ls.teach("Python", "a language", source="user")
        plan = build_plan_from_context(self.ctx("What is Python and Zorblax?")).plan
        ids = [s.step_id for s in plan.steps]
        self.assertEqual(ids, [f"step-{i:03d}" for i in range(1, len(ids) + 1)])
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(plan.steps[0].expected_output, "confirmed_request")
        self.assertEqual(plan.steps[-1].expected_output, "response_prepared")
        self.assertEqual(plan.steps[-1].dependencies, ids[:-1])

    def test_dependencies_only_point_backwards(self):
        plan = build_plan_from_context(self.ctx("What is Zorblax?")).plan
        seen = set()
        for s in plan.steps:
            self.assertTrue(set(s.dependencies) <= seen, s.step_id)
            seen.add(s.step_id)

    def test_existing_validator_and_handoff_accept_plan(self):
        ctx = self.ctx()
        res = build_plan_from_context(ctx)
        v = self.core.validate_plan(res.plan, goal=ctx.goal)
        self.assertTrue(v.valid and v.execution_eligible)
        h = self.core.prepare_execution_handoff(res.plan, ctx)
        self.assertEqual((h.status, h.executed, h.inert, h.execution_authorized),
                         ("ready_for_executor", False, True, False))


class TestPlanningIsNotExecution(Base):
    def test_all_steps_pending_and_plan_marked_unexecuted(self):
        res = build_plan_from_context(self.ctx())
        self.assertEqual(res.plan.status, "pending")
        self.assertTrue(all(s.status == "pending" for s in res.plan.steps))
        self.assertTrue(all(s.output_data is None for s in res.plan.steps))
        self.assertEqual(res.plan.metadata["phase"], "planning")
        self.assertIs(res.plan.metadata["executed"], False)
        self.assertIs(res.plan.metadata["execution_authorized"], False)
        self.assertEqual((res.executed, res.execution_authorized), (False, False))
        self.assertEqual(res.plan.required_capabilities, [])
        self.assertTrue(all(s.required_capabilities == [] for s in res.plan.steps))

    def test_result_has_no_execution_surface(self):
        res = build_plan_from_context(self.ctx())
        for name in dir(res):
            if callable(getattr(res, name)) and not name.startswith("__"):
                self.assertFalse(name.lstrip("_").startswith(("run", "execute", "start", "apply", "invoke")), name)


class TestInvalidContextRejection(Base):
    def assertRejected(self, res, *codes):
        self.assertFalse(res.ok)
        self.assertEqual(res.status, pb.STATUS_REJECTED)
        self.assertIsNone(res.plan)
        self.assertIsNone(res.validation)
        self.assertEqual(res.codes(), list(codes))
        json.dumps(res.to_dict())

    def test_non_context_inputs(self):
        for bad in (None, "text", 5, {}, [], object()):
            self.assertRejected(build_plan_from_context(bad), pb.FAIL_INVALID_CONTEXT)

    def test_empty_request(self):
        for raw in ("", "   ", "\n\t"):
            res = build_plan_from_context(self.ctx(raw))
            self.assertRejected(res, pb.FAIL_EMPTY_REQUEST, pb.FAIL_BLOCKING_GAPS)
            self.assertEqual(res.failures[1]["gaps"][0]["code"], "EMPTY_REQUEST")

    def test_incomplete_context(self):
        c = RequestContext("hello")
        c.normalized_request = "hello"
        res = build_plan_from_context(c)
        self.assertRejected(res, pb.FAIL_INCOMPLETE_CONTEXT)
        self.assertEqual(res.failures[0]["missing"], ["intent", "reasoning"])

    def test_non_string_original_input_is_incomplete(self):
        c = self.ctx()
        c.original_input = 42
        self.assertRejected(build_plan_from_context(c), pb.FAIL_INCOMPLETE_CONTEXT)

    def test_persistent_context_rejected(self):
        c = self.ctx()
        c.persistent = True
        self.assertRejected(build_plan_from_context(c), pb.FAIL_PERSISTENT_CONTEXT)

    def test_blocking_gap_rejected_without_guessing(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")
        c = self.ctx("What is python?")
        self.assertTrue(c.blocking_gaps())
        res = build_plan_from_context(c)
        self.assertRejected(res, pb.FAIL_BLOCKING_GAPS)
        self.assertIn("AMBIGUOUS_KNOWLEDGE_TERM", [g["code"] for g in res.failures[0]["gaps"]])

    def test_unresolved_reference_rejected(self):
        c = self.core.prepare_request_context("What is it?", use_context=False)
        res = build_plan_from_context(c)
        self.assertRejected(res, pb.FAIL_BLOCKING_GAPS)
        self.assertIn("AMBIGUOUS_REFERENCE", [g["code"] for g in res.failures[0]["gaps"]])

    def test_rejection_is_deterministic(self):
        c = RequestContext("hello")
        self.assertEqual(build_plan_from_context(c).to_dict(), build_plan_from_context(c).to_dict())


class TestNoSideEffects(Base):
    def test_planning_writes_nothing_and_does_not_mutate_context(self):
        self.ls.teach("Python", "a language", source="user")
        ctx = self.ctx("What is Python?")
        before_ctx = ctx.to_dict()
        before_db = self.snap()
        goals_before = list(self.core.goals.list_goals()) if hasattr(self.core.goals, "list_goals") else None
        plans_before = len(self.core.plans.list_plans()) if hasattr(self.core.plans, "list_plans") else None
        for _ in range(3):
            build_plan_from_context(ctx)
            self.core.build_plan_from_context(ctx)
        self.assertEqual(ctx.to_dict(), before_ctx)
        self.assertIsNone(ctx.proposed_plan)
        self.assertFalse(ctx.execution_eligible)
        self.assertEqual(self.snap(), before_db)
        if goals_before is not None:
            self.assertEqual(list(self.core.goals.list_goals()), goals_before)
        if plans_before is not None:
            self.assertEqual(len(self.core.plans.list_plans()), plans_before)

    def test_rejected_planning_also_writes_nothing(self):
        before = self.snap()
        build_plan_from_context(self.ctx(""))
        build_plan_from_context(None)
        self.assertEqual(self.snap(), before)

    def test_module_imports_no_execution_or_system_modules(self):
        with open(os.path.join(PY_ROOT, "planning", "plan_builder.py"), encoding="utf-8") as fh:
            src = fh.read()
        mods = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertEqual(mods, {"hashlib", "planning"})
        body = src.split('"""')[2]
        for banned in ("subprocess", "socket", "shutil", "importlib", "eval(", "exec(", "open(", "os.",
                       "requests", "urllib", "http"):
            self.assertNotIn(banned, body)

    def test_shipped_database_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
