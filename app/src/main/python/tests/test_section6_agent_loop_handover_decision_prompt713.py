"""Prompt 713 - Section 6 Agent-Loop hand-over decision record (read-only decision stage).

Pins the four decisions of docs/section6_agent_loop_handover_decision_prompt713.md against the CURRENT implementation. Nothing here
requires or implements an integration: every test uses existing public APIs on test-owned objects, and the source-level tests only read
files. Decisions: (1) Section 4 step stack owns tool steps; (2) Section 4 pending/ready contract; (3) non-finite numbers rejected at
request creation, before any step starts; (4) a failed step is terminal.
"""
import ast
import glob
import hashlib
import inspect
import json
import os
import re
import unittest

from agent import agent_loop as agent_loop_mod
from execution.plan_execution_coordinator import PlanExecutionCoordinator
from planning import plan as plan_mod
from planning import plan_builder as builder_mod
from planning import tool_step_executor as exec_mod
from planning import tool_step_retry as retry_mod
from planning.goal_manager import GoalManager
from planning.plan import Plan, PlanStep
from planning.plan_builder import STEP_STATES, get_ready_plan_steps, validate_plan_step_states
from planning.plan_manager import PlanManager
from planning.plan_step_execution import complete_plan_step, fail_plan_step, start_plan_step
from planning.plan_validation import validate_plan
from planning.tool_step_executor import (OUTCOME_PRE_REGISTRY_REJECTION, OUTCOME_TOOL_EXECUTION_FAILURE,
                                         execute_plan_tool_step_preflighted)
from planning.tool_step_retry import STOP_NON_RETRYABLE, execute_plan_tool_step_with_retry, is_retryable_prestart_result
from tools.in_process_tool_registry import InProcessToolRegistry, ToolSpec
from tools.tool_request import create_tool_request
from tests.test_section6_final_acceptance_prompt712 import FROZEN_SECTION45_DIGEST
from tests.test_section6_tool_step_executor_prompt708 import make_plan, make_registry, req, step_of

from tests.section6_agent_loop_baseline_prompt719c import file_bytes as _baseline_file_bytes, read_text as _baseline_read_text   # Prompt 719-C: exact-path exemption for agent/agent_loop.py, see that helper
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT)))), "docs",
                   "section6_agent_loop_handover_decision_prompt713.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
# Frozen by Prompt 713 (identical to Prompt 712): the four Section 6 modules, and the legacy stack (execution/*.py + agent/agent_loop.py).
FROZEN_SECTION6_DIGEST = "32925269625dc3398f33723bdbc61bbd80e9874623a6e8b7c8caa00496ba3af0"
FROZEN_LEGACY_DIGEST = "686e135bb67df59ede7d05223d53f90c53cf97d72c315d6c62c60a387ff6e969"
SECTION6 = ["planning/tool_step_bridge.py", "planning/tool_step_executor.py", "planning/tool_capability_mapping.py",
            "planning/tool_step_retry.py"]
NAN, INF = float("nan"), float("inf")


def read(path):
    return _baseline_read_text(path)          # Prompt 719-C: agent/agent_loop.py is read without the sanctioned additions


def rel_read(rel):
    return read(os.path.join(PY_ROOT, rel))


def digest(rels):
    h = hashlib.sha256()
    for rel in rels:
        h.update(rel.encode() + b"\0" + hashlib.sha256(_baseline_file_bytes(rel)).digest())     # Prompt 719-C: agent_loop.py read without the sanctioned additions
    return h.hexdigest()


def imports_of(rel):
    found = []
    for node in ast.walk(ast.parse(rel_read(rel))):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
    return found


def legacy_plan():
    """A plan owned by the legacy PlanManager (test-owned): A, and B depending on A, both pending, authorized."""
    gm = GoalManager()
    goal = gm.create_goal("g")
    pm = PlanManager(gm)
    plan = pm.create_plan(goal.goal_id, metadata={"phase": "planning", "executed": False, "execution_authorized": True})
    a = pm.add_step(plan.plan_id, "A")
    b = pm.add_step(plan.plan_id, "B", dependencies=[a.step_id])
    return pm, plan, a.step_id, b.step_id


class TestDecisionDocument(unittest.TestCase):
    def test_document_exists_and_records_all_four_decisions(self):
        text = read(DOC)
        for marker in ("DECISION-1: A", "DECISION-2: SECTION4-PENDING-READY", "DECISION-3: REJECT-BEFORE-START-AT-REQUEST",
                       "DECISION-4: FAILED-IS-TERMINAL"):
            self.assertIn(marker, text)
        self.assertIn("Nothing is implemented", text)
        for heading in ("APIs future integration MAY call", "APIs that MUST remain untouched", "Recorded conflicts",
                        "Recommended Prompt 714"):
            self.assertIn(heading, text)

    def test_document_names_every_allowed_api_and_each_exists(self):
        text = read(DOC)
        allowed = {"execute_plan_tool_step_with_retry": retry_mod, "execute_plan_tool_step_mapped": exec_mod,
                   "execute_plan_tool_step_preflighted": exec_mod, "get_ready_plan_steps": builder_mod,
                   "validate_plan_step_states": builder_mod}
        for name, module in allowed.items():
            self.assertIn(name, text)
            self.assertTrue(callable(getattr(module, name)), name)
        for name in ("validate_plan", "create_tool_request", "map_required_capabilities"):
            self.assertIn(name, text)

    def test_document_records_conflicts_for_the_implementation_prompt(self):
        text = read(DOC)
        for needle in ("C1.", "C2.", "C3.", "refresh_plan_step_statuses", "validate_plan_step_states", "retry_step",
                       "max_attempts", "**new** adapter module"):
            self.assertIn(needle, text)


class TestNoImplementationInThisPrompt(unittest.TestCase):
    """Decision stage: nothing was implemented, nothing in the existing stacks was modified."""

    def test_section4_and_section5_are_unchanged(self):
        files = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/")
                       for f in glob.glob(os.path.join(PY_ROOT, "planning", "*.py")) + glob.glob(os.path.join(PY_ROOT, "tools", "*.py"))
                       if not any(k in f for k in ("tool_step_", "tool_capability_mapping")))
        self.assertEqual((digest(files), len(files)), (FROZEN_SECTION45_DIGEST, 31))

    def test_section6_modules_are_unchanged(self):
        self.assertEqual(digest(sorted(SECTION6)), FROZEN_SECTION6_DIGEST)

    def test_legacy_stack_and_agent_loop_are_unchanged(self):
        files = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/") for f in glob.glob(os.path.join(PY_ROOT, "execution", "*.py")))
        files.append("agent/agent_loop.py")                       # fixed order: sorted execution/*.py, then the Agent Loop
        self.assertEqual((digest(files), len(files)), (FROZEN_LEGACY_DIGEST, 27))

    def test_no_new_production_module_references_section6(self):
        for path in glob.glob(os.path.join(PY_ROOT, "**", "*.py"), recursive=True):
            rel = os.path.relpath(path, PY_ROOT).replace(os.sep, "/")
            if rel.startswith("tests/") or rel in SECTION6 or rel == "planning/tool_step_agent_adapter.py" or rel == "planning/tool_step_dispatch.py" or rel == "agent/tool_step_intent.py" or rel == "agent/tool_step_runner.py":     # Prompt 714: the one sanctioned adapter; Prompt 717: exact-path exemption for the dispatch decision layer; Prompt 719-A: exact-path exemption for the caller-side intent adapter
                continue
            text = read(path)
            for token in ("tool_step_", "tool_capability_mapping", "execute_plan_tool_step", "execute_tool_step"):
                self.assertNotIn(token, text, rel)

    def test_pristine_database_hash(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


class TestDecision1ExecutionAuthority(unittest.TestCase):
    def test_legacy_stack_has_no_tool_contract_and_no_authorization_gate(self):
        for path in glob.glob(os.path.join(PY_ROOT, "execution", "*.py")):
            rel = os.path.relpath(path, PY_ROOT)
            for mod in imports_of(rel):
                self.assertNotEqual(mod.split(".")[0], "tools", rel)
            self.assertNotIn("execution_authorized", read(path), rel)
            self.assertNotIn("InProcessToolRegistry", read(path), rel)

    def test_section4_step_stack_has_the_authorization_gate_the_legacy_stack_lacks(self):
        plan = make_plan(authorized=False)
        res = start_plan_step(plan, "s1")
        self.assertEqual((res.ok, res.codes(), step_of(plan, "s1").status), (False, ["EXECUTION_NOT_AUTHORIZED"], "pending"))

    def test_agent_loop_currently_drives_only_the_legacy_controller(self):
        text = rel_read("agent/agent_loop.py")
        self.assertIn("PlanExecutionController", text)
        self.assertNotIn("tool_step", text)
        self.assertNotIn("retry_step", text)
        self.assertNotIn("execute_plan_tool_step", text)

    def test_stacks_are_mutually_independent(self):
        for rel in SECTION6:
            for mod in imports_of(rel):
                self.assertFalse(mod.startswith(("execution", "agent")), (rel, mod))
        for path in glob.glob(os.path.join(PY_ROOT, "execution", "*.py")):
            for mod in imports_of(os.path.relpath(path, PY_ROOT)):
                self.assertNotIn("plan_step_execution", mod)
                self.assertNotIn("tool_step", mod)

    def test_only_the_bridge_bridges_planning_to_tools(self):
        offenders = sorted({os.path.relpath(p, PY_ROOT).replace(os.sep, "/")
                            for p in glob.glob(os.path.join(PY_ROOT, "planning", "*.py"))
                            if any(m.split(".")[0] == "tools" for m in imports_of(os.path.relpath(p, PY_ROOT)))})
        self.assertEqual(offenders, ["planning/tool_step_bridge.py"])

    def test_allowed_entry_points_have_the_documented_signatures(self):
        sig = lambda fn: list(inspect.signature(fn).parameters)
        self.assertEqual(sig(retry_mod.execute_plan_tool_step_with_retry),
                         ["plan", "step_id", "request", "registry", "max_attempts", "required_capabilities", "capability_mapping",
                          "attempt_log"])
        self.assertEqual(sig(exec_mod.execute_plan_tool_step_preflighted), ["plan", "step_id", "request", "registry", "rejection_log"])

    def test_lower_level_executor_judges_request_only_after_start(self):
        """Why integration must not call execute_plan_tool_step() directly: an unusable request fails the STARTED step."""
        reg, h = make_registry()
        plan = make_plan()
        res = exec_mod.execute_plan_tool_step(plan, "s1", "not a request", reg)
        self.assertEqual((res.status, res.final_state, step_of(plan, "s1").status), ("failed", "failed", "failed"))
        plan = make_plan()
        pre = execute_plan_tool_step_preflighted(plan, "s1", "not a request", reg)
        self.assertEqual((pre.status, step_of(plan, "s1").status), ("rejected", "pending"))


class TestDecision2ReadySemantics(unittest.TestCase):
    def test_section4_state_vocabulary_has_no_ready_or_blocked(self):
        self.assertEqual(STEP_STATES, ("pending", "in_progress", "completed", "failed"))
        self.assertIn("ready", plan_mod.ALL_STEP_STATUSES)           # the legacy labels exist on PlanStep ...
        self.assertIn("blocked", plan_mod.ALL_STEP_STATUSES)
        self.assertNotIn("ready", STEP_STATES)                        # ... but are not Section 4 states
        self.assertNotIn("blocked", STEP_STATES)

    def test_ready_means_pending_no_output_dependencies_completed(self):
        plan = make_plan("a", "b", "c", chain=True)
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, ["a"])
        start_plan_step(plan, "a")
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, [])              # in_progress is never ready
        complete_plan_step(plan, "a", {"ok": 1})
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, ["b"])           # completed dependency releases b only
        start_plan_step(plan, "b")
        fail_plan_step(plan, "b", {"code": "X"})
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, [])              # failed does not release c
        self.assertEqual([step_of(plan, s).status for s in "abc"], ["completed", "failed", "pending"])

    def test_pending_step_with_output_is_not_ready(self):
        plan = make_plan()
        plan.steps[0].output_data = {"x": 1}
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, [])

    def test_readiness_ignores_authorization_but_start_requires_it(self):
        authorized, unauthorized = make_plan(authorized=True), make_plan(authorized=False)
        self.assertEqual(get_ready_plan_steps(authorized).ready_step_ids, ["s1"])
        self.assertEqual(get_ready_plan_steps(unauthorized).ready_step_ids, ["s1"])   # ready != authorized
        self.assertEqual(start_plan_step(unauthorized, "s1").codes(), ["EXECUTION_NOT_AUTHORIZED"])
        self.assertTrue(start_plan_step(authorized, "s1").ok)

    def test_flags_must_be_explicit_booleans_for_readiness(self):
        for flags in ({"phase": "planning"}, {"executed": "no", "execution_authorized": True},
                      {"executed": False, "execution_authorized": 1}):
            plan = make_plan()
            plan.metadata = flags
            result = get_ready_plan_steps(plan)
            self.assertFalse(result.ok, flags)
            self.assertEqual(result.ready_step_ids, [])

    def test_section4_is_the_authority_over_the_dependency_graph(self):
        plan = make_plan("a", "b")
        plan.steps[1].dependencies = ["ghost"]
        result = get_ready_plan_steps(plan)
        self.assertFalse(result.ok)

    def test_plan_with_ready_label_is_ineligible_for_tool_steps(self):
        reg, h = make_registry()
        plan = make_plan()
        plan.steps[0].status = "ready"
        self.assertFalse(get_ready_plan_steps(plan).ok)
        self.assertFalse(validate_plan_step_states(plan).valid)
        self.assertEqual(start_plan_step(plan, "s1").codes(), ["INVALID_PLAN_STATE"])
        res = execute_plan_tool_step_preflighted(plan, "s1", req("echo"), reg)
        self.assertEqual((res.outcome_kind, res.reason, step_of(plan, "s1").status), (OUTCOME_PRE_REGISTRY_REJECTION,
                                                                                     "INVALID_PLAN_STATE", "ready"))
        self.assertEqual((h["echo"].count, reg.invocation_count()), (0, 0))
        self.assertFalse(is_retryable_prestart_result(res))                          # never retried, never auto-repaired
        retried = execute_plan_tool_step_with_retry(plan, "s1", req("echo"), reg, 5)
        self.assertEqual((retried.stop_reason, retried.attempts_made), (STOP_NON_RETRYABLE, 1))
        self.assertEqual(step_of(plan, "s1").status, "ready")                         # left exactly as found

    def test_conflict_c2_validate_plan_accepts_what_start_rejects(self):
        plan = make_plan()
        plan.steps[0].status = "ready"
        self.assertTrue(validate_plan(plan).valid)                                    # recorded conflict C2
        self.assertFalse(validate_plan_step_states(plan).valid)                       # the gate the adapter must use

    def test_stacks_disagree_on_pending_plans_and_section4_wins_for_tool_steps(self):
        pm, plan, a, b = legacy_plan()
        coordinator = PlanExecutionCoordinator(pm)
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, [a])              # Section 4: A is ready
        self.assertIsNone(coordinator.get_next_ready_step(plan.plan_id)["step_id"])   # legacy: no READY-labelled step
        self.assertEqual(pm.get_ready_step_ids(plan.plan_id), [a])                    # weaker third notion agrees only by accident
        self.assertTrue(start_plan_step(plan, a).ok)                                  # Section 4 can start it as-is

    def test_conflict_c1_legacy_refresh_makes_the_plan_ineligible_for_section4(self):
        pm, plan, a, b = legacy_plan()
        coordinator = PlanExecutionCoordinator(pm)
        pm.refresh_plan_step_statuses(plan.plan_id)                                    # legacy writes derived labels
        self.assertEqual([s.status for s in plan.steps], ["ready", "blocked"])
        self.assertEqual(coordinator.get_next_ready_step(plan.plan_id)["step_id"], a)  # legacy: A runnable
        result = get_ready_plan_steps(plan)
        self.assertFalse(result.ok)
        self.assertEqual({f["code"] for f in result.failures}, {"UNSUPPORTED_STEP_STATE"})
        self.assertEqual(start_plan_step(plan, a).codes(), ["INVALID_PLAN_STATE"])     # Section 4: not eligible; nothing converted
        self.assertEqual([s.status for s in plan.steps], ["ready", "blocked"])         # ... and nothing repaired either

    def test_readiness_functions_are_pure_read_only(self):
        plan = make_plan("a", "b", chain=True)
        before = json.dumps([(s.step_id, s.status, s.output_data, s.dependencies) for s in plan.steps]) + repr(plan.metadata)
        get_ready_plan_steps(plan)
        validate_plan_step_states(plan)
        validate_plan(plan)
        after = json.dumps([(s.step_id, s.status, s.output_data, s.dependencies) for s in plan.steps]) + repr(plan.metadata)
        self.assertEqual(before, after)


class TestDecision3NonFiniteBoundary(unittest.TestCase):
    CASES = (("nan", NAN), ("inf", INF), ("-inf", -INF), ("nested dict", {"a": {"b": NAN}}), ("nested list", {"a": [1, [2, INF]]}),
             ("nested tuple", {"a": (1, -INF)}), ("deep", {"a": [{"b": [{"c": NAN}]}]}))

    def test_request_creation_rejects_every_non_finite_value_at_any_depth(self):
        for label, value in self.CASES:
            built = create_tool_request("echo", value, None, None, False)
            self.assertFalse(built.ok, label)
            self.assertEqual(built.codes(), ["INVALID_TOOL_REQUEST_INPUT"], label)
            self.assertIsNone(getattr(built, "request", None), label)

    def test_finite_floats_are_accepted_and_never_coerced(self):
        reg, h = make_registry()
        plan = make_plan()
        value = {"f": 1.5, "neg": -0.25, "big": 1e308, "i": 3}
        res = execute_plan_tool_step_preflighted(plan, "s1", req("echo", value), reg)
        self.assertTrue(res.ok)
        self.assertEqual(h["echo"].calls, [value])

    def test_rejection_happens_before_any_step_can_start(self):
        reg, h = make_registry()
        plan = make_plan()
        before = json.dumps([(s.step_id, s.status, s.output_data) for s in plan.steps]) + repr(plan.metadata)
        built = create_tool_request("echo", {"v": NAN}, None, None, False)
        self.assertFalse(built.ok)
        # no request exists, so no executor can be reached: nothing started, nothing invoked, no sequence consumed
        self.assertEqual(json.dumps([(s.step_id, s.status, s.output_data) for s in plan.steps]) + repr(plan.metadata), before)
        self.assertEqual((reg.invocation_count(), reg.get_invocation_history(), h["echo"].count), (0, [], 0))
        self.assertTrue(execute_plan_tool_step_preflighted(plan, "s1", req("echo"), reg).ok)
        self.assertEqual(reg.get_invocation_history()[0]["sequence"], 1)

    def test_registry_independently_rejects_non_finite_input(self):
        reg, h = make_registry()
        for label, value in self.CASES:
            res = reg.preflight("echo", value)
            self.assertFalse(res.ok, label)
            self.assertEqual([f["code"] for f in res.failures], ["INVALID_TOOL_INPUT"], label)
        self.assertEqual((reg.invocation_count(), h["echo"].count), (0, 0))

    def test_plan_data_never_reaches_a_tool_implicitly(self):
        reg, h = make_registry()
        plan = make_plan()
        plan.steps[0].input_data = {"v": NAN}                                         # Section 4 accepts it (recorded asymmetry)
        self.assertTrue(validate_plan(plan).valid)
        res = execute_plan_tool_step_preflighted(plan, "s1", req("echo", {"v": 1}), reg)
        self.assertTrue(res.ok)
        self.assertEqual(h["echo"].calls, [{"v": 1}])                                 # only the caller-built request was used

    def test_plan_generated_input_gets_the_same_verdict_as_direct_input(self):
        plan = make_plan()
        plan.steps[0].input_data = {"v": [1, NAN]}
        plan_built = create_tool_request("echo", plan.steps[0].input_data, None, None, False)
        direct_built = create_tool_request("echo", {"v": [1, NAN]}, None, None, False)
        self.assertEqual((plan_built.ok, plan_built.codes()), (direct_built.ok, direct_built.codes()))
        self.assertFalse(plan_built.ok)

    def test_forged_request_is_rejected_before_start(self):
        reg, h = make_registry()
        plan = make_plan()
        forged = object.__new__(type(req("echo")))
        res = execute_plan_tool_step_preflighted(plan, "s1", forged, reg)
        self.assertEqual((res.status, step_of(plan, "s1").status, reg.invocation_count()), ("rejected", "pending", 0))

    def test_non_finite_tool_output_is_rejected_and_never_stored_on_the_step(self):
        reg = InProcessToolRegistry()
        reg.register(ToolSpec(name="bad", description="d", handler=lambda _: {"v": NAN}, input_schema={"type": "object"},
                              output_description="o"))
        plan = make_plan()
        res = execute_plan_tool_step_preflighted(plan, "s1", req("bad"), reg)
        self.assertEqual((res.status, res.outcome_kind, step_of(plan, "s1").status), ("failed", OUTCOME_TOOL_EXECUTION_FAILURE, "failed"))
        self.assertEqual(res.execution["tool_result"]["outcome_code"], "TOOL_OUTPUT_INVALID")
        json.dumps(step_of(plan, "s1").output_data, allow_nan=False)                   # strict JSON: no NaN/inf stored

    def test_recorded_asymmetry_section4_still_accepts_non_finite_plan_data(self):
        plan = make_plan()
        start_plan_step(plan, "s1")
        self.assertTrue(complete_plan_step(plan, "s1", {"x": NAN}).ok)                 # documented, deliberately not changed here
        self.assertEqual(PlanStep("z", "d", input_data={"x": INF}).input_data, {"x": INF})


class TestDecision4FailedIsTerminal(unittest.TestCase):
    def failed_plan(self, *ids, chain=False):
        plan = make_plan(*ids, chain=chain)
        first = plan.steps[0].step_id
        start_plan_step(plan, first)
        fail_plan_step(plan, first, {"code": "TOOL_STEP_TOOL_FAILED"})
        return plan, first

    def test_no_transition_can_leave_failed(self):
        plan, sid = self.failed_plan()
        self.assertEqual(start_plan_step(plan, sid).codes(), ["STEP_NOT_READY"])
        self.assertEqual(complete_plan_step(plan, sid, {"a": 1}).codes(), ["STEP_NOT_IN_PROGRESS"])
        self.assertEqual(fail_plan_step(plan, sid, {"a": 1}).codes(), ["STEP_NOT_IN_PROGRESS"])
        self.assertEqual((step_of(plan, sid).status, step_of(plan, sid).output_data), ("failed", {"code": "TOOL_STEP_TOOL_FAILED"}))
        self.assertTrue(validate_plan_step_states(plan).valid)
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, [])

    def test_no_reset_or_rerun_api_exists_in_planning_or_section6(self):
        forbidden = {"reset", "reopen", "rerun", "revive", "restart", "unfail"}     # whole snake_case/CamelCase words ('prestart' is fine)

        def words(name):
            return {w.lower() for w in re.findall(r"[A-Za-z][a-z0-9]*", name.replace("_", " "))}

        def offends(name):
            lowered = name.lower()
            return bool(words(name) & forbidden) or "re_run" in lowered or "retry_failed" in lowered or "retryfailed" in lowered

        for path in glob.glob(os.path.join(PY_ROOT, "planning", "*.py")):
            tree = ast.parse(read(path))
            names = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
            self.assertEqual([n for n in names if offends(n)], [], path)
        for name in dir(plan_mod.PlanStep):
            if not name.startswith("__"):
                self.assertFalse(offends(name), name)
        self.assertTrue(offends("reset_step") and offends("rerun_failed_step") and offends("retry_failed_step"))   # guard bites
        self.assertFalse(offends("is_retryable_prestart_result"))

    def test_rewriting_a_failed_step_back_to_pending_is_detected_not_a_reset_path(self):
        plan, sid = self.failed_plan()
        step_of(plan, sid).status = "pending"                                          # out-of-contract tampering
        check = validate_plan_step_states(plan)
        self.assertFalse(check.valid)
        self.assertEqual(start_plan_step(plan, sid).codes(), ["INVALID_PLAN_STATE"])
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, [])

    def test_retry_layer_never_reruns_a_failed_step(self):
        reg, h = make_registry()
        plan = make_plan()
        first = execute_plan_tool_step_with_retry(plan, "s1", req("boom"), reg, 3)
        self.assertEqual((first.status, first.attempts_made, reg.invocation_count()), ("failed", 1, 1))
        again = execute_plan_tool_step_with_retry(plan, "s1", req("echo"), reg, 9)
        self.assertEqual((again.stop_reason, again.attempts_made, again.reason), (STOP_NON_RETRYABLE, 1, "STEP_NOT_READY"))
        self.assertEqual((h["echo"].count, reg.invocation_count(), step_of(plan, "s1").status), (0, 1, "failed"))

    def test_dependents_of_a_failed_step_are_never_released(self):
        plan, sid = self.failed_plan("a", "b", "c", chain=True)
        self.assertEqual(get_ready_plan_steps(plan).ready_step_ids, [])
        reg, h = make_registry()
        res = execute_plan_tool_step_with_retry(plan, "b", req("echo"), reg, 3)
        self.assertEqual((res.stop_reason, res.attempts_made, res.reason), ("attempt_limit_reached", 3, "STEP_NOT_READY"))
        self.assertEqual((step_of(plan, "b").status, h["echo"].count, reg.invocation_count()), ("pending", 0, 0))

    def test_another_attempt_is_a_new_step_in_a_new_plan_with_its_own_invocation_record(self):
        reg, h = make_registry()
        old = make_plan()
        execute_plan_tool_step_with_retry(old, "s1", req("boom"), reg, 2)
        old_output = json.dumps(step_of(old, "s1").output_data, sort_keys=True)
        new = make_plan("s1-attempt-2")
        res = execute_plan_tool_step_with_retry(new, "s1-attempt-2", req("echo"), reg, 2)
        self.assertTrue(res.ok)
        history = reg.get_invocation_history()
        self.assertEqual([(r["sequence"], r["tool_name"], r["ok"]) for r in history], [(1, "boom", False), (2, "echo", True)])
        self.assertEqual((step_of(old, "s1").status, json.dumps(step_of(old, "s1").output_data, sort_keys=True)), ("failed", old_output))
        self.assertEqual(res.final["sequence"], 2)

    def test_prestart_rejections_still_consume_no_sequence_for_the_new_attempt(self):
        reg, h = make_registry()
        old = make_plan()
        execute_plan_tool_step_with_retry(old, "s1", req("boom"), reg, 1)
        rejected = execute_plan_tool_step_with_retry(make_plan("n1"), "n1", req("off"), reg, 3)
        self.assertEqual(rejected.attempts_made, 3)
        good = execute_plan_tool_step_with_retry(make_plan("n2"), "n2", req("echo"), reg, 1)
        self.assertEqual(good.final["sequence"], 2)

    def test_legacy_retry_step_exists_but_is_not_part_of_the_tool_step_path(self):
        engine_src = rel_read("execution/execution_engine.py")
        self.assertIn("def retry_step(", engine_src)                                  # legacy capability-step retry (conflict recorded)
        for rel in SECTION6:
            self.assertNotIn("retry_step", rel_read(rel), rel)
        self.assertNotIn("retry_step", rel_read("agent/agent_loop.py"))


if __name__ == "__main__":
    unittest.main()
