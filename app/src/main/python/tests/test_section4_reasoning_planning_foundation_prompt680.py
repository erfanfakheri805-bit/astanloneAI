"""Prompt 680 - Section 4 foundation: Request Context -> Reasoning -> Gaps -> Plan -> Validation -> inert handoff.

Every test builds its own disposable database (tempfile); nothing here opens or writes the shipped database
except the read-only SHA-256 check."""
import ast
import hashlib
import json
import os
import tempfile
import unittest

from core.core import Core
from planning import plan_validation as pv
from planning.execution_handoff import (
    STATUS_READY_FOR_EXECUTOR, STATUS_REJECTED, ExecutionHandoff, prepare_execution_handoff,
)
from planning.plan import Plan, PlanStep
from planning.plan_validation import validate_plan
from planning.request_context import RequestContext, build_request_context
from reasoning.reasoning_contract import build_reasoning_outcome, classify_current_terms
from reasoning.reasoning_result import ReasoningResult

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items")


def step(sid, deps=None, caps=None, desc="do it"):
    return PlanStep(sid, desc, dependencies=deps, required_capabilities=caps)


def plan_of(*steps, goal_id="goal-1", plan_id="plan-x"):
    return Plan(plan_id, goal_id, steps=list(steps))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.core = Core(memory_db_path=os.path.join(self.tmp, "c.db"),
                         skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.k, self.ls, self.m = self.core.knowledge, self.core.learning, self.core.memory

    def tearDown(self):
        try:
            self.m._conn.close()
        except Exception:  # noqa: BLE001
            pass

    def snap(self):
        return {t: self.m.query(f"SELECT * FROM {t} ORDER BY id") for t in TABLES}

    def enable(self, name, on=True):
        self.core.capabilities.set_enabled(name, on)


class TestRequestContext(Base):
    def test_fields_for_question(self):
        self.ls.teach("Python", "a language", source="user")
        ctx = self.core.prepare_request_context("  What is   Python? ")
        self.assertIsInstance(ctx, RequestContext)
        self.assertEqual(ctx.original_input, "  What is   Python? ")
        self.assertEqual(ctx.normalized_request, "What is Python?")
        self.assertEqual(ctx.intent, "what_is")
        self.assertIn("python", ctx.terms)
        self.assertIsNone(ctx.goal)
        self.assertIsNone(ctx.proposed_plan)
        self.assertIsNone(ctx.validation)
        self.assertFalse(ctx.execution_eligible)
        self.assertFalse(ctx.persistent)
        self.assertEqual(ctx.reasoning.answer, "a language")
        self.assertEqual({c["name"] for c in ctx.capabilities["registered"]} >= {"code_analysis"}, True)

    def test_goal_request_sets_goal_and_intent(self):
        ctx = self.core.prepare_request_context("I want to build a calculator")
        self.assertEqual(ctx.intent, "goal_request")
        self.assertEqual(ctx.goal, "I want to build a calculator")

    def test_empty_request_is_blocking_gap(self):
        for raw in ("", "   ", None):
            ctx = self.core.prepare_request_context(raw)
            self.assertEqual([g["code"] for g in ctx.blocking_gaps()], ["EMPTY_REQUEST"])
            self.assertIsNone(ctx.reasoning)

    def test_to_dict_is_json_safe_and_not_persisted(self):
        self.ls.teach("Python", "a language", source="user")
        ctx = self.core.prepare_request_context("I want to learn Python", propose_plan=True)
        json.dumps(ctx.to_dict())
        self.assertFalse(ctx.to_dict()["persistent"])
        self.assertEqual(self.m.query("SELECT name FROM sqlite_master WHERE name LIKE '%request_context%'"), [])

    def test_building_context_writes_nothing(self):
        self.ls.teach("Python", "a language", source="user")
        before = self.snap()
        turns = len(self.core.context)
        goals, plans = len(self.core.goals.all_goals()), len(self.core.plans)
        for text in ("What is Python?", "What is it?", "I want to build a calculator", ""):
            self.core.prepare_request_context(text)
        self.assertEqual(self.snap(), before)
        self.assertEqual(len(self.core.context), turns)
        self.assertEqual((len(self.core.goals.all_goals()), len(self.core.plans)), (goals, plans))

    def test_observations_are_bounded_working_notes(self):
        ctx = RequestContext("x")
        for i in range(80):
            ctx.add_observation("note", i)
        self.assertEqual(len(ctx.observations), 50)
        self.assertEqual(ctx.observations[-1]["detail"], 79)

    def test_reference_without_context_is_blocking_gap(self):
        ctx = self.core.prepare_request_context("What is it?", use_context=False)
        self.assertEqual(ctx.reasoning.status, "ambiguous")
        self.assertIn("AMBIGUOUS_REFERENCE", [g["code"] for g in ctx.blocking_gaps()])
        self.assertEqual(ctx.reasoning.next_action, "clarify")


class TestReasoningContract(Base):
    def test_engine_result_and_reason_are_unchanged(self):
        self.ls.teach("Python", "a language", source="user")
        r = self.core.reason("What is Python?")
        d = r.to_dict()
        build_reasoning_outcome(r, self.k)
        self.assertEqual(r.to_dict(), d)
        self.assertEqual(r.status, "answered")

    def test_answered_outcome(self):
        self.ls.teach("Python", "a language", source="user")
        out = build_reasoning_outcome(self.core.reason("What is Python?"), self.k)
        self.assertEqual((out.status, out.effective_status, out.next_action),
                         ("answered", "answered", "answer"))
        self.assertEqual(out.answer, "a language")
        self.assertEqual(out.relevant_knowledge[0]["name"], "Python")
        self.assertEqual(out.uncertainty["confidence"], out.to_dict()["uncertainty"]["confidence"])
        self.assertGreater(out.evidence["supporting_facts"], 0)
        self.assertFalse(out.is_ambiguous)
        json.dumps(out.to_dict())

    def test_unknown_outcome(self):
        out = build_reasoning_outcome(self.core.reason("What is Zorblax?"), self.k)
        self.assertEqual((out.status, out.next_action), ("unknown", "gather_information"))
        self.assertIsNone(out.answer)
        self.assertTrue(out.uncertainty["unknowns"])

    def test_case_insensitive_match_is_recorded_as_assumption(self):
        self.ls.teach("Python", "a language", source="user")
        out = build_reasoning_outcome(self.core.reason("What is python?"), self.k)
        self.assertTrue(any("ignoring case" in a for a in out.assumptions))

    def test_context_resolved_reference_is_an_assumption(self):
        self.ls.teach("Python", "a language", source="user")
        self.core.learn_from_text("Python is a programming language.")
        out = build_reasoning_outcome(self.core.reason("What is it?"), self.k)
        if out.status == "answered":
            self.assertTrue(any("resolved" in a for a in out.assumptions))

    def test_unresolvable_reference_is_ambiguous(self):
        r = self.core.reasoning.reason("What is it?", context=None, request_forms=True)
        out = build_reasoning_outcome(r, self.k)
        self.assertEqual((out.status, out.effective_status), ("ambiguous", "ambiguous"))
        self.assertTrue(out.ambiguity["reference_ambiguous"])

    def test_case_ambiguous_knowledge_is_recovered_without_changing_engine_contract(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")
        r = self.core.reason("What is python?")
        self.assertEqual(r.status, "unknown")                    # Section 3 contract, untouched
        out = build_reasoning_outcome(r, self.k)
        self.assertEqual(out.status, "unknown")                  # engine value preserved
        self.assertEqual(out.effective_status, "ambiguous")      # planning sees the ambiguity
        self.assertEqual(out.next_action, "clarify")
        self.assertEqual(out.ambiguity["ambiguous_terms"][0]["candidates"], ["PYTHON", "Python"])
        self.assertIsNone(out.answer)
        self.assertEqual(out.relevant_knowledge, [])             # nothing chosen
        blob = json.dumps(out.to_dict())
        self.assertNotIn("upper", blob)
        self.assertNotIn("lower", blob)

    def test_contradiction_outcome(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.teach("language", "words", source="user")
        self.k.relate("Python", "language", "IS_A")
        self.k.relate("Python", "language", "IS_NOT_A")
        r = self.core.reason("Is Python a language?")
        out = build_reasoning_outcome(r, self.k)
        if r.status == "contradiction":
            self.assertEqual(out.next_action, "resolve_contradiction")
            self.assertGreater(out.uncertainty["contradictions"], 0)
            ctx = self.core.prepare_request_context("Is Python a language?")
            self.assertIn("CONTRADICTORY_KNOWLEDGE", [g["code"] for g in ctx.blocking_gaps()])

    def test_classify_without_knowledge_is_empty(self):
        self.assertEqual(classify_current_terms(None, ["a"]),
                         {"current": [], "ambiguous": [], "inactive": [], "unknown": []})


class TestCurrentKnowledgeIntegration(Base):
    def test_current_knowledge_is_used(self):
        self.ls.teach("Python", "a language", source="user")
        ctx = self.core.prepare_request_context("What is Python?")
        self.assertEqual([r["name"] for r in ctx.knowledge_context["current"]], ["Python"])

    def test_inactive_knowledge_is_not_current(self):
        self.ls.teach("Python", "SECRET-DESC", source="user")
        self.ls.set_status("Python", "inactive")
        ctx = self.core.prepare_request_context("What is Python?")
        self.assertEqual(ctx.knowledge_context["current"], [])
        self.assertEqual(ctx.knowledge_context["inactive"], ["python"])
        self.assertIsNone(ctx.reasoning.answer)
        self.assertEqual(ctx.reasoning.relevant_knowledge, [])
        self.assertNotIn("SECRET-DESC", json.dumps(ctx.to_dict()))
        self.assertIn("INACTIVE_KNOWLEDGE_TERM", [g["code"] for g in ctx.information_gaps])
        self.assertEqual(ctx.blocking_gaps(), [])                # informational, not blocking

    def test_reactivation_is_effective_immediately(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.set_status("Python", "inactive")
        self.assertEqual(self.core.prepare_request_context("What is Python?").reasoning.status, "unknown")
        self.ls.set_status("Python", "active")
        self.assertEqual(self.core.prepare_request_context("What is Python?").reasoning.answer, "a language")

    def test_ambiguous_knowledge_is_a_blocking_gap_and_never_chosen(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")
        ctx = self.core.prepare_request_context("What is python?")
        self.assertEqual(ctx.knowledge_context["current"], [])
        self.assertEqual(ctx.knowledge_context["ambiguous"][0]["candidates"], ["PYTHON", "Python"])
        codes = [g["code"] for g in ctx.blocking_gaps()]
        self.assertIn("AMBIGUOUS_KNOWLEDGE_TERM", codes)
        self.assertNotIn("UNKNOWN_INFORMATION", [g["code"] for g in ctx.information_gaps])
        self.assertEqual(ctx.reasoning.effective_status, "ambiguous")

    def test_active_plus_inactive_variant_is_not_ambiguous(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")
        self.ls.set_status("PYTHON", "inactive")
        ctx = self.core.prepare_request_context("What is python?")
        self.assertEqual(ctx.blocking_gaps(), [])
        self.assertEqual(ctx.reasoning.answer, "upper")

    def test_historical_learning_events_are_not_current_knowledge(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.set_status("Python", "inactive")
        self.assertTrue(self.m.recent_learning_events(50))       # history exists ...
        ctx = self.core.prepare_request_context("What is Python?")
        self.assertEqual(ctx.knowledge_context["current"], [])   # ... but is never current
        self.assertNotIn("a language", json.dumps(ctx.to_dict()))

    def test_raw_and_current_boundaries_unchanged(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.set_status("Python", "inactive")
        self.core.prepare_request_context("What is Python?")
        self.assertEqual(self.k.resolve_name("Python")["status"], "exact")          # raw stays raw
        self.assertEqual(self.k.resolve_current_name("Python")["status"], "inactive")

    def test_goal_with_ambiguous_term_proposes_no_plan(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")
        ctx = self.core.prepare_request_context("I want to learn python", propose_plan=True)
        self.assertIsNone(ctx.proposed_plan)
        self.assertFalse(ctx.execution_eligible)
        self.assertEqual(len(self.core.plans), 0)
        self.assertEqual(ctx.observations[-1]["kind"], "plan_not_proposed")


class TestPlanValidation(Base):
    def test_valid_plan_with_reused_planner(self):
        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_third_step(goal.goal_id)
        res = self.core.validate_plan(plan)
        self.assertTrue(res.valid)
        self.assertTrue(res.execution_eligible)
        self.assertEqual(res.ordered_step_ids, [s.step_id for s in plan.steps])
        self.assertEqual(self.core.validate_plan(plan.plan_id).to_dict(), res.to_dict())

    def test_non_plan_and_unknown_plan_id(self):
        self.assertEqual(validate_plan(None).codes(), ["INVALID_PLAN_OBJECT"])
        res = self.core.validate_plan("plan-999")
        self.assertEqual(res.codes(), ["INVALID_PLAN_OBJECT"])
        self.assertFalse(res.valid)

    def test_empty_goal(self):
        p = plan_of(step("s1"))
        self.assertIn("EMPTY_GOAL", validate_plan(p, goal="   ").codes())
        self.assertIn("EMPTY_GOAL", validate_plan(plan_of(step("s1"), goal_id="")).codes())
        self.assertNotIn("EMPTY_GOAL", validate_plan(p, goal="Do things").codes())

    def test_empty_plan(self):
        res = validate_plan(plan_of(), goal="g")
        self.assertIn("EMPTY_PLAN", res.codes())
        self.assertFalse(res.valid)
        self.assertFalse(res.execution_eligible)

    def test_duplicate_step_ids(self):
        res = validate_plan(plan_of(step("a"), step("a")), goal="g")
        self.assertEqual(res.codes().count("DUPLICATE_STEP_ID"), 1)
        self.assertEqual(res.ordered_step_ids, [])

    def test_invalid_step_id_and_description(self):
        p = plan_of(step("a"), step(""), PlanStep("b", "  "))
        codes = validate_plan(p, goal="g").codes()
        self.assertIn("INVALID_STEP_ID", codes)
        self.assertIn("EMPTY_STEP_DESCRIPTION", codes)

    def test_invalid_dependencies(self):
        res = validate_plan(plan_of(step("a", ["ghost"]), step("b", ["b"])), goal="g")
        msgs = [i["message"] for i in res.issues if i["code"] == "INVALID_DEPENDENCY"]
        self.assertEqual(len(msgs), 2)
        self.assertTrue(any("ghost" in m for m in msgs))
        self.assertTrue(any("itself" in m for m in msgs))

    def test_cycle_detection(self):
        res = validate_plan(plan_of(step("a", ["c"]), step("b", ["a"]), step("c", ["b"])), goal="g")
        self.assertEqual(res.codes(), ["DEPENDENCY_CYCLE"])
        cycle = res.issues[0]["cycle"]
        self.assertEqual(cycle[0], cycle[-1])
        self.assertEqual(set(cycle), {"a", "b", "c"})
        self.assertFalse(res.valid)

    def test_two_node_cycle_and_acyclic_diamond(self):
        self.assertIn("DEPENDENCY_CYCLE",
                      validate_plan(plan_of(step("a", ["b"]), step("b", ["a"])), goal="g").codes())
        diamond = plan_of(step("d", ["b", "c"]), step("b", ["a"]), step("c", ["a"]), step("a"))
        res = validate_plan(diamond, goal="g")
        self.assertTrue(res.valid)
        self.assertEqual(res.ordered_step_ids, ["a", "b", "c", "d"])

    def test_unknown_capability(self):
        res = validate_plan(plan_of(step("a", caps=["teleport"])), goal="g",
                            capability_system=self.core.capabilities)
        self.assertEqual(res.codes(), ["UNKNOWN_CAPABILITY"])
        self.assertEqual(res.issues[0]["capability"], "teleport")

    def test_missing_capability_is_registered_but_disabled(self):
        res = validate_plan(plan_of(step("a", caps=["code_generation"])), goal="g",
                            capability_system=self.core.capabilities)
        self.assertEqual(res.codes(), ["MISSING_CAPABILITY"])
        self.enable("code_generation")
        ok = validate_plan(plan_of(step("a", caps=["code_generation"])), goal="g",
                           capability_system=self.core.capabilities)
        self.assertTrue(ok.valid and ok.execution_eligible)

    def test_capability_semantics_match_plan_manager(self):
        goal = self.core.create_goal("Create a tool")
        p = self.core.plans.all_plans()[0]
        self.enable("code_analysis")
        self.core.add_plan_step(p.plan_id, "one", required_capabilities=["code_analysis"])
        self.core.add_plan_step(p.plan_id, "two", required_capabilities=["file_input", "nope"])
        report = {r["capability_name"]: r["available"]
                  for r in self.core.plans.check_plan_capabilities(p.plan_id, self.core.capabilities)}
        res = self.core.validate_plan(p)
        flagged = {i["capability"] for i in res.issues if "capability" in i}
        self.assertEqual(flagged, {n for n, ok in report.items() if not ok})
        self.assertEqual(flagged, {"file_input", "nope"})

    def test_unchecked_capabilities_are_valid_but_not_eligible(self):
        res = validate_plan(plan_of(step("a", caps=["code_analysis"])), goal="g")
        self.assertTrue(res.valid)
        self.assertFalse(res.execution_eligible)
        self.assertEqual(res.warnings[0]["code"], "CAPABILITIES_UNCHECKED")
        self.assertTrue(validate_plan(plan_of(step("a")), goal="g").execution_eligible)

    def test_impossible_execution_eligibility(self):
        bad = validate_plan(plan_of(), goal="g", claimed_execution_eligible=True)
        self.assertIn("IMPOSSIBLE_EXECUTION_ELIGIBILITY", bad.codes())
        unchecked = validate_plan(plan_of(step("a", caps=["x"])), goal="g", claimed_execution_eligible=True)
        self.assertIn("IMPOSSIBLE_EXECUTION_ELIGIBILITY", unchecked.codes())
        fine = validate_plan(plan_of(step("a")), goal="g", claimed_execution_eligible=True)
        self.assertTrue(fine.valid)
        self.assertNotIn("IMPOSSIBLE_EXECUTION_ELIGIBILITY",
                         validate_plan(plan_of(), goal="g", claimed_execution_eligible=False).codes())

    def test_validation_never_repairs_or_mutates(self):
        self.enable("code_analysis")
        p = plan_of(step("a", ["ghost"], caps=["teleport", "code_analysis"]), step("a"))
        before = p.to_dict()
        caps_before = self.core.capabilities.all()
        res = validate_plan(p, goal="", capability_system=self.core.capabilities)
        self.assertFalse(res.valid)
        self.assertEqual(p.to_dict(), before)
        self.assertEqual(self.core.capabilities.all(), caps_before)

    def test_validation_is_deterministic(self):
        p = plan_of(step("a", ["c", "zz"]), step("b", ["a"]), step("c", ["b"]), step("a"))
        self.assertEqual(validate_plan(p, goal="g").to_dict(), validate_plan(p, goal="g").to_dict())


class TestCapabilityAwarePlanning(Base):
    def test_no_capabilities_invented(self):
        before = self.core.capabilities.all()
        ctx = self.core.prepare_request_context("I want to build a calculator", propose_plan=True)
        self.assertEqual(self.core.capabilities.all(), before)
        for s in ctx.proposed_plan.steps:
            self.assertEqual(s.required_capabilities, [])
        self.assertEqual({c["name"] for c in ctx.capabilities["registered"]},
                         {r["name"] for r in before})

    def test_context_reflects_enabled_state_and_executable_registry(self):
        self.enable("code_analysis")
        ctx = self.core.prepare_request_context("What is Python?")
        state = {c["name"]: c["enabled"] for c in ctx.capabilities["registered"]}
        self.assertTrue(state["code_analysis"])
        self.assertFalse(state["image_input"])
        self.assertIsInstance(ctx.capabilities["executable"], list)

    def test_plan_with_unavailable_capability_is_rejected_by_handoff(self):
        goal = self.core.create_goal("Create a tool")
        p = self.core.plans.all_plans()[0]
        self.core.add_plan_step(p.plan_id, "analyse", required_capabilities=["code_generation"])
        h = self.core.prepare_execution_handoff(p)
        self.assertEqual(h.status, STATUS_REJECTED)
        self.assertIn("MISSING_CAPABILITY", h.rejection_reasons)
        self.enable("code_generation")
        h2 = self.core.prepare_execution_handoff(p)
        self.assertEqual(h2.status, STATUS_READY_FOR_EXECUTOR)
        self.assertEqual(h2.required_capabilities, ["code_generation"])


class TestInvalidPlanRejection(Base):
    def test_handoff_rejects_each_invalid_plan(self):
        cases = {
            "EMPTY_PLAN": plan_of(),
            "DUPLICATE_STEP_ID": plan_of(step("a"), step("a")),
            "INVALID_DEPENDENCY": plan_of(step("a", ["ghost"])),
            "DEPENDENCY_CYCLE": plan_of(step("a", ["b"]), step("b", ["a"])),
            "UNKNOWN_CAPABILITY": plan_of(step("a", caps=["teleport"])),
        }
        for code, p in cases.items():
            with self.subTest(code):
                h = self.core.prepare_execution_handoff(p)
                self.assertEqual(h.status, STATUS_REJECTED)
                self.assertIn(code, h.rejection_reasons)
                self.assertEqual(h.steps, [])
                self.assertFalse(h.ready)

    def test_context_never_eligible_for_invalid_plan(self):
        ctx = RequestContext("x")
        ctx.attach_plan(plan_of())
        ctx.attach_validation(validate_plan(ctx.proposed_plan, goal="g"))
        self.assertFalse(ctx.execution_eligible)

    def test_blocking_gap_prevents_eligibility_even_for_valid_plan(self):
        ctx = RequestContext("x")
        ctx.add_gap("AMBIGUOUS_KNOWLEDGE_TERM", "m", True)
        p = plan_of(step("a"))
        ctx.attach_plan(p)
        ctx.attach_validation(validate_plan(p, goal="g", capability_system=self.core.capabilities))
        self.assertFalse(ctx.execution_eligible)
        h = prepare_execution_handoff(p, ctx.validation, request_context=ctx)
        self.assertEqual(h.status, STATUS_REJECTED)
        self.assertIn("BLOCKING_INFORMATION_GAPS", h.rejection_reasons)
        self.assertEqual(h.blocking_gaps[0]["code"], "AMBIGUOUS_KNOWLEDGE_TERM")

    def test_validation_for_another_plan_is_rejected(self):
        a, b = plan_of(step("a"), plan_id="plan-a"), plan_of(step("a"), plan_id="plan-b")
        h = prepare_execution_handoff(a, validate_plan(b, goal="g"))
        self.assertEqual(h.status, STATUS_REJECTED)
        self.assertIn("VALIDATION_MISSING_OR_FOR_ANOTHER_PLAN", h.rejection_reasons)
        self.assertEqual(prepare_execution_handoff(a, None).status, STATUS_REJECTED)
        self.assertEqual(prepare_execution_handoff(None, None).status, STATUS_REJECTED)


class TestInertExecutionBoundary(Base):
    def make_ready(self):
        ctx = self.core.prepare_request_context("I want to build a calculator", propose_plan=True)
        return ctx, self.core.prepare_execution_handoff(ctx.proposed_plan, ctx)

    def test_ready_handoff_is_inert(self):
        ctx, h = self.make_ready()
        self.assertIsInstance(h, ExecutionHandoff)
        self.assertEqual(h.status, STATUS_READY_FOR_EXECUTOR)
        self.assertTrue(ctx.execution_eligible)
        self.assertEqual((h.executed, h.inert, h.execution_authorized), (False, True, False))
        self.assertEqual([s["step_id"] for s in h.steps], ctx.validation.ordered_step_ids)
        d = h.to_dict()
        json.dumps(d)
        self.assertEqual((d["executed"], d["inert"], d["execution_authorized"]), (False, True, False))
        self.assertIn("Nothing has been executed", d["boundary"])

    def test_handoff_has_no_execution_surface(self):
        _, h = self.make_ready()
        for name in dir(h):
            if callable(getattr(h, name)) and not name.startswith("__"):
                self.assertFalse(name.lstrip("_").startswith(("run", "execute", "start", "apply", "invoke")), name)
        self.assertIs(h.executed, False)
        for value in h.to_dict()["steps"]:
            self.assertFalse(any(callable(v) for v in value.values()))

    def test_handoff_changes_no_plan_step_status_and_creates_no_execution_records(self):
        ctx, _ = self.make_ready()
        plan = ctx.proposed_plan
        before = plan.to_dict()
        history = list(self.core.step_controller.history.list_all()) \
            if hasattr(self.core.step_controller.history, "list_all") else None
        for _ in range(3):
            self.core.prepare_execution_handoff(plan, ctx)
        self.assertEqual(plan.to_dict(), before)
        self.assertTrue(all(s.status == "pending" for s in plan.steps))
        if history is not None:
            self.assertEqual(list(self.core.step_controller.history.list_all()), history)

    def test_handoff_is_a_snapshot(self):
        ctx, h = self.make_ready()
        ctx.proposed_plan.steps[0].description = "CHANGED LATER"
        self.assertNotIn("CHANGED LATER", json.dumps(h.to_dict()))

    def test_handoff_is_deterministic(self):
        ctx, h = self.make_ready()
        self.assertEqual(self.core.prepare_execution_handoff(ctx.proposed_plan, ctx).to_dict(), h.to_dict())

    def test_handoff_module_imports_no_execution_or_system_modules(self):
        src = open(os.path.join(PY_ROOT, "planning", "execution_handoff.py"), encoding="utf-8").read()
        mods = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertEqual(mods, {"planning"})              # only planning.plan (data model) is imported
        body = src.split('"""')[2]                        # code after the module docstring
        for banned in ("subprocess", "socket", "shutil", "importlib", "eval(", "exec(", "open(", "os."):
            self.assertNotIn(banned, body)

    def test_new_planning_modules_import_no_execution_layer(self):
        for rel in ("planning/request_context.py", "planning/plan_validation.py",
                    "planning/execution_handoff.py", "reasoning/reasoning_contract.py"):
            tree = ast.parse(open(os.path.join(PY_ROOT, rel), encoding="utf-8").read())
            for node in ast.walk(tree):
                mod = ""
                if isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                elif isinstance(node, ast.Import):
                    mod = " ".join(a.name for a in node.names)
                for banned in ("execution", "subprocess", "socket", "urllib", "shutil", "http"):
                    self.assertNotIn(banned, mod.split(".")[0].split(" "), rel)

    def test_process_input_does_not_use_section4_entry_points(self):
        src = open(os.path.join(PY_ROOT, "core", "core.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        core_cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Core")
        for fn in core_cls.body:
            if isinstance(fn, ast.FunctionDef) and fn.name in (
                    "process_input", "_handle_conversation", "_handle_goal_or_conversation", "_handle_ael"):
                seg = ast.get_source_segment(src, fn)
                for name in ("prepare_request_context", "prepare_execution_handoff", "validate_plan"):
                    self.assertNotIn(name, seg, fn.name)


class TestSection3Compatibility(Base):
    def test_process_input_behaviour_unchanged(self):
        self.ls.teach("Python", "a language", source="user")
        before = self.snap()
        self.assertEqual(self.core.reason("What is Python?").answer, "a language")
        self.assertIn("I don't have enough information", self.core.process_input("Tell me about Zorblax"))
        goals = len(self.core.goals.all_goals())
        self.core.process_input("I want to build a calculator")
        self.assertEqual(len(self.core.goals.all_goals()), goals + 1)
        self.core.prepare_request_context("What is Python?")
        self.assertEqual(len(self.core.goals.all_goals()), goals + 1)
        self.assertEqual(self.snap()["knowledge"], before["knowledge"])

    def test_section3_ambiguity_and_inactive_contracts_still_hold(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")
        self.assertEqual(self.core.reason("What is python?").status, "unknown")
        self.assertEqual(self.k.resolve_current_name("python")["status"], "ambiguous")
        self.ls.set_status("PYTHON", "inactive")
        self.assertEqual(self.core.reason("What is python?").answer, "upper")
        self.assertEqual(self.k.resolve_name("python")["status"], "ambiguous")

    def test_existing_plan_apis_unchanged(self):
        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_third_step(goal.goal_id)
        self.assertEqual(len(plan.steps), 3)
        self.assertEqual(plan.steps[1].dependencies, [plan.steps[0].step_id])
        report = self.core.plans.check_plan_readiness(plan.plan_id, self.core.capabilities)
        self.assertIn("ready", report)
        self.assertTrue(self.core.prepare_first_step(goal.goal_id)["prepared"])

    def test_shipped_database_is_pristine(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
