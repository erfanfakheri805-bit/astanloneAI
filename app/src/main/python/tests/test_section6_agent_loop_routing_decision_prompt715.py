"""Prompt 715 - Agent Loop tool-step routing decision & contract audit (read-only decision stage).

Pins docs/section6_agent_loop_routing_decision_prompt715.md against the CURRENT implementation. Nothing here wires or implements a router:
every behavioural test uses existing public APIs on test-owned objects; source-level tests only read files.
Decisions: (1) B explicit plan-scoped route; (2) mixed plans rejected; (3) Section 4 states only for tool route; (4) F3 reject before start;
(5) caller-owned ToolRequest; (6) the adapter is the only tool-step entry.
"""
import ast
import glob
import hashlib
import inspect
import os
import unittest

from agent import agent_loop as agent_loop_mod
from execution import execution_engine as engine_mod
from execution import plan_execution_controller as controller_mod
from planning import plan as plan_mod
from planning import tool_step_agent_adapter as adapter_mod
from planning.goal_manager import GoalManager
from planning.plan import Plan, PlanStep
from planning.plan_builder import get_ready_plan_steps, validate_plan_step_states
from planning.plan_manager import PlanManager
from planning.plan_validation import validate_plan
from planning.tool_step_agent_adapter import (ADAPTER_EXECUTION_NOT_AUTHORIZED, ADAPTER_INVALID_MAPPING_ARGUMENTS,
                                              ADAPTER_INVALID_MAX_ATTEMPTS, ADAPTER_INVALID_PLAN_OBJECT,
                                              ADAPTER_INVALID_STEP_ID, ADAPTER_LEGACY_STEP_STATE, ADAPTER_UNKNOWN_STEP,
                                              MAX_ADAPTER_ATTEMPTS, STATUS_ADAPTER_COMPLETED, STATUS_ADAPTER_FAILED,
                                              STATUS_ADAPTER_REJECTED, execute_agent_tool_step)
from tests.test_section6_agent_loop_handover_decision_prompt713 import (FROZEN_LEGACY_DIGEST, FROZEN_SECTION6_DIGEST, SECTION6,
                                                                        digest, legacy_plan)
from tests.test_section6_final_acceptance_prompt712 import FROZEN_SECTION45_DIGEST
from tests.test_section6_tool_step_executor_prompt708 import make_plan, make_registry, req, snapshot, step_of
from tests.test_section6_tool_step_preflight_prompt709 import registry_state, spy_registry_class
from tools.tool_request import ToolRequest, create_tool_request

from tests.section6_agent_loop_baseline_prompt719c import file_bytes as _baseline_file_bytes, read_text as _baseline_read_text   # Prompt 719-C: exact-path exemption for agent/agent_loop.py, see that helper
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT)))), "docs",
                   "section6_agent_loop_routing_decision_prompt715.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
FROZEN_AGENT_LOOP_SHA256 = "b69e217564345cad5ae30b76fe6af97c0d6d263098ad4344954d5946b7631157"
FROZEN_PLAN_MANAGER_SHA256 = "885b8835a48ce53e86a9a65d9d0d873d41821c8547d8c1606e6021521b686dc3"
FROZEN_CORE_SHA256 = "d5e8755b5c20b2806eabc5e0152a87db74f478c15b9139edb51e85fa5e32b841"   # core/core.py holds process_input()
FROZEN_ADAPTER_SHA256 = "e739477f9b6fe7cd71f20b6a9879a70f8ec15e0ea4fa653fcc54367b72d88216"
NAN, INF = float("nan"), float("inf")
ROUTE_LEGACY, ROUTE_TOOL = "legacy_capability", "section6_tool"
ROUTE_RESOLVER_REL = "planning/tool_step_route.py"     # Prompt 716: sanctioned routing-metadata module (test-only exemption below)
ADAPTER_PARAMS = ["plan", "step_id", "request", "registry", "max_attempts", "required_capabilities", "capability_mapping", "attempt_log"]


def read(path):
    return _baseline_read_text(path)          # Prompt 719-C: agent/agent_loop.py is read without the sanctioned additions


def rel_read(rel):
    return read(os.path.join(PY_ROOT, rel))


def sha(rel):
    return hashlib.sha256(_baseline_file_bytes(rel)).hexdigest()         # Prompt 719-C: agent_loop.py read without the sanctioned additions


def production_files():
    skip = os.sep + "tests" + os.sep
    return [p for p in glob.glob(os.path.join(PY_ROOT, "**", "*.py"), recursive=True) if skip not in p]


def imports_of(rel):
    found = []
    for node in ast.walk(ast.parse(rel_read(rel))):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
    return found


def run(plan, request, reg, n=3, step_id="s1", **kw):
    return execute_agent_tool_step(plan, step_id, request, reg, n, **kw)


class TestDecisionDocument(unittest.TestCase):
    def test_document_records_all_six_decisions(self):
        text = read(DOC)
        for marker in ("DECISION-1: B-EXPLICIT-PLAN-SCOPED-ROUTE", "DECISION-2: MIXED-PLANS-REJECTED",
                       "DECISION-3: SECTION4-STATES-ONLY-FOR-TOOL-ROUTE", "DECISION-4: F3-REJECT-BEFORE-START",
                       "DECISION-5: CALLER-OWNED-TOOLREQUEST", "DECISION-6: ADAPTER-IS-THE-ONLY-TOOL-STEP-ENTRY"):
            self.assertIn(marker, text)
        for heading in ("Tool-step eligibility contract", "Legacy capability-step contract", "Exact future boundary",
                        "Implementation gaps", "Recommended Prompt 716"):
            self.assertIn(heading, text)
        self.assertIn("nothing is wired", text.lower())

    def test_document_states_the_hard_rules(self):
        text = read(DOC)
        for needle in ("legacy `retry_step` does not apply", "no `PlanManager.refresh_*` during tool execution", "NaN/inf",
                       "never** derived from tool names", "absent, unknown or malformed declaration => **legacy**",
                       "ADAPTER_LEGACY_STEP_STATE", "G1", "G2", "G3", "G4", "deferred"):
            self.assertIn(needle.lower(), text.lower(), needle)

    def test_document_boundary_names_every_stage_in_order(self):
        text = read(DOC)
        block = text[text.index("## 5. Exact future boundary"):text.index("## 6. Implementation gaps")]
        chain = ["routing decision", "ToolRequest construction", "execute_agent_tool_step", "execute_plan_tool_step_with_retry",
                 "InProcessToolRegistry"]
        positions = [block.index(item) for item in chain]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("AgentLoop.run -> PlanExecutionController", text)


class TestRoutingArchitecture(unittest.TestCase):
    """DECISION-1: B. Option A cannot be expressed by the current data model; no route exists in production code."""

    def test_planstep_cannot_carry_a_step_type_so_option_a_is_a_gap(self):
        self.assertEqual(PlanStep.__slots__, ("step_id", "description", "dependencies", "required_capabilities", "expected_output",
                                              "status", "input_data", "output_data"))
        with self.assertRaises(AttributeError):
            PlanStep("s", "d").step_type = "tool"
        self.assertIn("metadata", Plan.__slots__)

    def test_no_route_vocabulary_exists_in_production_code(self):
        for path in production_files():
            if path.endswith(ROUTE_RESOLVER_REL):        # Prompt 716: the one sanctioned route resolver (routing metadata only, no execution)
                continue
            if os.path.relpath(path, PY_ROOT).replace(os.sep, "/") == "planning/tool_step_dispatch.py":   # Prompt 717: exact-path exemption (data-only dispatch decision)
                continue
            text = read(path)
            for token in ('"%s"' % ROUTE_LEGACY, '"%s"' % ROUTE_TOOL, "execution_route", "resolve_execution_route"):
                self.assertNotIn(token, text, (path, token))

    def test_adapter_signature_has_no_route_parameter(self):
        self.assertEqual(list(inspect.signature(execute_agent_tool_step).parameters), ADAPTER_PARAMS)
        self.assertEqual(adapter_mod.MAX_ADAPTER_ATTEMPTS, 10)

    def test_routing_never_uses_names_capabilities_registry_or_handlers(self):
        tree = ast.parse(rel_read("planning/tool_step_agent_adapter.py"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertNotIn("required_capabilities", attrs)            # never reads a step's own capabilities
        self.assertNotIn("name", attrs)
        for forbidden in ("get_handler", "list_tools", "has_tool", "tools", "handlers"):
            self.assertNotIn(forbidden, attrs)

    def test_tool_route_has_no_default_entry(self):
        self.assertIs(inspect.signature(execute_agent_tool_step).parameters["request"].default, inspect.Parameter.empty)
        self.assertIs(inspect.signature(execute_agent_tool_step).parameters["max_attempts"].default, inspect.Parameter.empty)


class TestLegacyAudit(unittest.TestCase):
    def test_agent_loop_runs_only_the_legacy_controller(self):
        src = rel_read("agent/agent_loop.py")
        self.assertIn("self._controller.execute_plan(plan_id)", src)
        imports = imports_of("agent/agent_loop.py")
        for bad in ("planning.tool_step_agent_adapter", "planning.tool_step_bridge", "planning.tool_step_executor",
                    "planning.tool_step_retry", "planning.tool_capability_mapping", "tools.in_process_tool_registry",
                    "tools.tool_request"):
            self.assertNotIn(bad, imports)
        self.assertFalse([m for m in imports if m.startswith("tools")])

    def test_legacy_controller_refreshes_the_whole_plan_first(self):
        src = inspect.getsource(controller_mod.PlanExecutionController.execute_plan)
        self.assertIn("refresh_plan_step_statuses", src)
        self.assertIn("get_next_ready_step", src)
        self.assertIn("refresh_after_step_change", src)

    def test_legacy_required_capabilities_are_handler_names_run_in_order(self):
        src = inspect.getsource(engine_mod.ExecutionEngine.execute_capability_step)
        self.assertIn("step.required_capabilities", src)
        self.assertIn("retry_step", inspect.getsource(engine_mod.ExecutionEngine))

    def test_legacy_only_considers_ready_steps(self):
        from execution.plan_execution_coordinator import PlanExecutionCoordinator
        self.assertIn("STATUS_READY", inspect.getsource(PlanExecutionCoordinator.get_next_ready_step))

    def test_adapter_and_section6_do_not_touch_legacy_retry_or_engine(self):
        for rel in ("planning/tool_step_agent_adapter.py", "planning/tool_step_retry.py", "planning/tool_step_executor.py",
                    "planning/tool_step_bridge.py", "planning/tool_capability_mapping.py"):
            text = rel_read(rel)
            code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("#", '"', "'")))
            self.assertFalse([m for m in imports_of(rel) if m.startswith("execution")], rel)
            self.assertNotIn("ExecutionEngine(", code)
            self.assertNotIn(".retry_step(", code)


class TestToolStepEligibility(unittest.TestCase):
    """The eligibility contract as enforced today by the adapter (the final pre-execution boundary)."""

    def setUp(self):
        self.calls = []
        self.reg, self.h = make_registry(spy_registry_class(self.calls))
        self.before_reg = registry_state(self.reg)

    def assertRejectedUntouched(self, res, plan, before, code):
        self.assertEqual((res.ok, res.status, res.failure_code, res.execution_started), (False, STATUS_ADAPTER_REJECTED, code, False))
        self.assertEqual(snapshot(plan), before)
        self.assertEqual((self.calls, self.reg.invocation_count(), registry_state(self.reg)), ([], 0, self.before_reg))
        for counter in self.h.values():
            self.assertEqual(counter.count, 0)

    def test_valid_plan_step_request_completes(self):
        plan = make_plan()
        res = run(plan, req("echo", {"a": 1}), self.reg)
        self.assertEqual((res.ok, res.status, res.final_step_state), (True, STATUS_ADAPTER_COMPLETED, "completed"))
        self.assertEqual(step_of(plan, "s1").status, "completed")

    def test_each_eligibility_condition_is_enforced_before_start(self):
        cases = [("plan object", lambda: ("not a plan", "s1", 3, {}), ADAPTER_INVALID_PLAN_OBJECT),
                 ("step id", lambda: (make_plan(), "", 3, {}), ADAPTER_INVALID_STEP_ID),
                 ("unknown step", lambda: (make_plan(), "zz", 3, {}), ADAPTER_UNKNOWN_STEP),
                 ("authorization", lambda: (make_plan(authorized=False), "s1", 3, {}), ADAPTER_EXECUTION_NOT_AUTHORIZED),
                 ("retry limit low", lambda: (make_plan(), "s1", 0, {}), ADAPTER_INVALID_MAX_ATTEMPTS),
                 ("retry limit high", lambda: (make_plan(), "s1", MAX_ADAPTER_ATTEMPTS + 1, {}), ADAPTER_INVALID_MAX_ATTEMPTS),
                 ("retry limit bool", lambda: (make_plan(), "s1", True, {}), ADAPTER_INVALID_MAX_ATTEMPTS),
                 ("mapping pair", lambda: (make_plan(), "s1", 3, {"required_capabilities": ["Needs A"]}), ADAPTER_INVALID_MAPPING_ARGUMENTS)]
        for label, build, code in cases:
            with self.subTest(label):
                plan, step_id, n, kw = build()
                before = snapshot(plan) if isinstance(plan, Plan) else None
                res = execute_agent_tool_step(plan, step_id, req("echo"), self.reg, n, **kw)
                self.assertEqual((res.ok, res.status, res.failure_code, res.execution_started), (False, STATUS_ADAPTER_REJECTED, code, False))
                if before is not None:
                    self.assertEqual(snapshot(plan), before)
                self.assertEqual((self.calls, self.reg.invocation_count()), ([], 0))

    def test_unsupported_step_state_is_rejected(self):
        plan = make_plan()
        step_of(plan, "s1").status = "in_progress"
        before = snapshot(plan)
        res = run(plan, req("echo"), self.reg)
        self.assertEqual((res.ok, res.execution_started, self.calls, self.reg.invocation_count()), (False, False, [], 0))
        self.assertEqual(snapshot(plan), before)

    def test_request_must_be_caller_constructed_toolrequest(self):
        for bogus in ({"name": "echo", "tool_input": {}}, "echo", None, object()):
            with self.subTest(type(bogus).__name__):
                plan = make_plan()
                before = snapshot(plan)
                res = run(plan, bogus, self.reg)
                self.assertEqual((res.ok, res.status, res.execution_started), (False, STATUS_ADAPTER_REJECTED, False))
                self.assertEqual((snapshot(plan), self.calls, self.reg.invocation_count()), (before, [], 0))
        self.assertTrue(ToolRequest.__slots__)

    def test_registry_availability_is_required_before_start(self):
        for bogus in (None, object(), "registry"):
            with self.subTest(type(bogus).__name__):
                plan = make_plan()
                before = snapshot(plan)
                res = run(plan, req("echo"), bogus)
                self.assertEqual((res.ok, res.execution_started, res.failure_source), (False, False, "pre_start"))
                self.assertEqual(snapshot(plan), before)

    def test_capability_pair_is_explicit_and_never_inferred(self):
        plan = Plan("p", "g", steps=[PlanStep("s1", "d", required_capabilities=["Needs A"])], created_at="1970-01-01T00:00:00+00:00",
                    metadata={"phase": "planning", "executed": False, "execution_authorized": True})
        res = run(plan, req("echo"), self.reg)                                       # step names a capability; no pair supplied -> not used
        self.assertTrue(res.ok)
        self.assertIsNone(res.mapping)

    def test_a_failed_step_is_terminal_and_not_rerun(self):
        plan = make_plan()
        res = run(plan, req("boom"), self.reg)
        self.assertEqual((res.status, res.failure_source, res.final_step_state), (STATUS_ADAPTER_FAILED, "tool_execution", "failed"))
        calls_after = self.h["boom"].count
        again = run(plan, req("boom"), self.reg)
        self.assertEqual((again.ok, again.execution_started), (False, False))
        self.assertEqual(self.h["boom"].count, calls_after)


class TestMixedPlanPolicyAndReadyBlocked(unittest.TestCase):
    """DECISION-2 and DECISION-3, proved with the real legacy PlanManager and the real adapter."""

    def test_fresh_section4_plan_is_tool_eligible_and_dependents_stay_pending(self):
        pm, plan, a, b = legacy_plan()
        self.assertEqual([s.status for s in plan.steps], ["pending", "pending"])
        self.assertTrue(validate_plan_step_states(plan).valid)
        reg, _ = make_registry()
        res = run(plan, req("echo"), reg, step_id=a)
        self.assertTrue(res.ok)
        self.assertEqual([s.status for s in plan.steps], ["completed", "pending"])
        self.assertEqual(list(get_ready_plan_steps(plan).ready_step_ids), [b])

    def test_legacy_refresh_makes_the_plan_tool_ineligible_without_conversion(self):
        pm, plan, a, b = legacy_plan()
        pm.refresh_plan_step_statuses(plan.plan_id)
        self.assertEqual([s.status for s in plan.steps], ["ready", "blocked"])
        self.assertFalse(validate_plan_step_states(plan).valid)
        self.assertTrue(validate_plan(plan).valid)                                   # conflict C2 still present at the validation level
        reg, h = make_registry()
        before = snapshot(plan)
        res = run(plan, req("echo"), reg, step_id=a)
        self.assertEqual((res.ok, res.status, res.failure_code, res.execution_started), (False, STATUS_ADAPTER_REJECTED,
                                                                                         ADAPTER_LEGACY_STEP_STATE, False))
        self.assertEqual(snapshot(plan), before)                                     # no conversion, no repair
        self.assertEqual(h["echo"].count, 0)

    def test_adapter_never_calls_refresh(self):
        pm, plan, a, b = legacy_plan()
        reg, _ = make_registry()
        calls = []
        for name in ("refresh_plan_step_statuses", "refresh_after_step_change", "refresh_step_status"):
            setattr(pm, name, lambda *a_, _n=name, **k: calls.append(_n))
        self.assertTrue(run(plan, req("echo"), reg, step_id=a).ok)
        self.assertEqual(calls, [])
        self.assertNotIn("PlanManager", inspect.getsource(adapter_mod).replace("PlanManager.refresh_*", ""))

    def test_legacy_completion_flips_a_dependent_to_ready_and_makes_it_tool_ineligible(self):
        pm, plan, a, b = legacy_plan()
        pm.update_step_status(plan.plan_id, a, "completed")
        pm.refresh_after_step_change(plan.plan_id, a)
        self.assertEqual([s.status for s in plan.steps], ["completed", "ready"])
        reg, _ = make_registry()
        res = run(plan, req("echo"), reg, step_id=b)
        self.assertEqual((res.ok, res.failure_code), (False, ADAPTER_LEGACY_STEP_STATE))

    def test_one_legacy_label_anywhere_rejects_the_whole_plan(self):
        plan = make_plan("s1", "s2")
        step_of(plan, "s2").status = "ready"
        reg, h = make_registry()
        before = snapshot(plan)
        res = run(plan, req("echo"), reg, step_id="s1")
        self.assertEqual((res.ok, res.failure_code, res.execution_started), (False, ADAPTER_LEGACY_STEP_STATE, False))
        self.assertEqual((snapshot(plan), h["echo"].count), (before, 0))

    def test_failed_tool_step_leaves_dependents_pending_not_blocked(self):
        plan = make_plan("s1", "s2", chain=True)
        reg, _ = make_registry()
        res = run(plan, req("boom"), reg, step_id="s1")
        self.assertEqual(res.final_step_state, "failed")
        self.assertEqual([s.status for s in plan.steps], ["failed", "pending"])      # no cross-stack propagation is defined
        self.assertEqual(list(get_ready_plan_steps(plan).ready_step_ids), [])

    def test_legacy_controller_would_relabel_a_tool_plan(self):
        pm, plan, a, b = legacy_plan()
        pm.refresh_plan_step_statuses(plan.plan_id)                                  # what execute_plan does first
        self.assertEqual([s.status for s in plan.steps], ["ready", "blocked"])       # hence a plan must never be given to both stacks

    def test_states_vocabulary_differs_between_stacks(self):
        self.assertEqual(plan_mod.STATUS_READY, "ready")
        self.assertEqual(plan_mod.STATUS_BLOCKED, "blocked")
        self.assertEqual(adapter_mod.LEGACY_STEP_STATES, ("ready", "blocked"))
        from planning.plan_builder import STEP_STATES
        self.assertEqual(STEP_STATES, ("pending", "in_progress", "completed", "failed"))


class TestF3Contract(unittest.TestCase):
    """DECISION-4: Section 4 accepts non-finite plan data; ToolRequest rejects it; nothing is converted; the tool step never starts."""

    def test_section4_accepts_nonfinite_plan_data(self):
        for bad in (NAN, INF, -INF):
            step = PlanStep("s1", "d", input_data={"x": bad})
            plan = Plan("p", "g", steps=[step], metadata={"phase": "planning", "executed": False, "execution_authorized": True})
            self.assertTrue(validate_plan(plan).valid)
            self.assertTrue(validate_plan_step_states(plan).valid)

    def test_toolrequest_rejects_nonfinite_numbers_without_conversion(self):
        for bad in (NAN, INF, -INF):
            for payload in ({"x": bad}, {"a": [1, {"b": bad}]}):
                res = create_tool_request("echo", payload)
                self.assertFalse(res.ok)
                self.assertEqual(res.codes(), ["INVALID_TOOL_REQUEST_INPUT"])
                self.assertIsNone(res.request)
        self.assertTrue(create_tool_request("echo", {"x": 1.5}).ok)

    def test_tool_step_fails_before_start_when_the_request_has_nonfinite_numbers(self):
        plan = Plan("p", "g", steps=[PlanStep("s1", "d", input_data={"x": NAN})], created_at="1970-01-01T00:00:00+00:00",
                    metadata={"phase": "planning", "executed": False, "execution_authorized": True})
        before = snapshot(plan)
        made = create_tool_request("echo", {"x": NAN})
        self.assertFalse(made.ok)                                                    # no ToolRequest exists to hand over
        reg, h = make_registry()
        res = run(plan, made.request, reg)                                           # a caller that ignores the failure still cannot start
        self.assertEqual((res.ok, res.status, res.execution_started), (False, STATUS_ADAPTER_REJECTED, False))
        self.assertEqual((snapshot(plan), h["echo"].count, reg.invocation_count()), (before, 0, 0))

    def test_adapter_and_routing_modules_do_not_sanitise_numbers(self):
        for rel in ("planning/tool_step_agent_adapter.py", "planning/tool_step_retry.py"):
            code = rel_read(rel)
            for token in ("isnan", "isfinite", "isinf", "nan_to_num"):
                self.assertNotIn(token, code, (rel, token))


class TestToolRequestOwnership(unittest.TestCase):
    """DECISION-5."""

    def test_no_request_builder_or_intent_inference_module_exists(self):
        names = [os.path.basename(p) for p in production_files()]
        for name in names:
            self.assertNotIn("request_builder", name)
            self.assertNotIn("tool_intent", name)

    def test_adapter_and_agent_loop_never_construct_requests(self):
        for rel in ("planning/tool_step_agent_adapter.py", "agent/agent_loop.py", "core/core.py"):
            self.assertNotIn("create_tool_request", rel_read(rel), rel)
            self.assertNotIn("ToolRequest(", rel_read(rel), rel)

    def test_request_carries_only_explicit_caller_supplied_grants(self):
        res = create_tool_request("echo", {}, None, None, False)
        self.assertTrue(res.ok)
        r = res.request
        self.assertEqual((r.granted_permissions, r.granted_capabilities, r.confirmed), ((), (), False) if isinstance(
            r.granted_permissions, tuple) else ([], [], False))

    def test_adapter_does_not_change_the_request_it_receives(self):
        reg, _ = make_registry()
        request = req("echo", {"a": 1})
        before = (request.name, request.input)
        self.assertTrue(run(make_plan(), request, reg).ok)
        self.assertEqual((request.name, request.input), before)


class TestSingleEntryPoint(unittest.TestCase):
    """DECISION-6."""

    def test_only_the_adapter_imports_the_retry_layer(self):
        users = sorted(os.path.relpath(p, PY_ROOT).replace(os.sep, "/") for p in production_files()
                       if "execute_plan_tool_step_with_retry" in read(p) and not p.endswith("tool_step_retry.py"))
        self.assertEqual(users, ["agent/tool_step_runner.py", "planning/tool_step_agent_adapter.py"])      # Prompt 719-B: the caller-side runner is the second sanctioned caller

    def test_nothing_in_production_imports_the_adapter(self):
        for path in production_files():
            if path.endswith("tool_step_agent_adapter.py"):
                continue
            text = read(path)
            self.assertNotIn("tool_step_agent_adapter", text, path)
            self.assertNotIn("execute_agent_tool_step", text, path)

    def test_adapter_calls_only_the_retry_entry_for_execution(self):
        tree = ast.parse(rel_read("planning/tool_step_agent_adapter.py"))
        called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        attrs = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn("execute_plan_tool_step_with_retry", called)
        for forbidden in ("execute_plan_tool_step", "execute_tool_step", "execute_plan_tool_step_preflighted",
                          "execute_plan_tool_step_mapped", "start_plan_step", "complete_plan_step", "fail_plan_step"):
            self.assertNotIn(forbidden, called)
        for forbidden in ("execute", "execute_request", "invoke", "refresh_plan_step_statuses", "refresh_after_step_change"):
            self.assertNotIn(forbidden, attrs)


class TestNothingWired(unittest.TestCase):
    def test_section4_and_section5_are_unchanged(self):
        files = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/")
                       for f in glob.glob(os.path.join(PY_ROOT, "planning", "*.py")) + glob.glob(os.path.join(PY_ROOT, "tools", "*.py"))
                       if not any(k in f for k in ("tool_step_", "tool_capability_mapping")))
        self.assertEqual((digest(files), len(files)), (FROZEN_SECTION45_DIGEST, 31))

    def test_section6_modules_and_adapter_are_unchanged(self):
        self.assertEqual(digest(sorted(SECTION6)), FROZEN_SECTION6_DIGEST)
        self.assertEqual(sha("planning/tool_step_agent_adapter.py"), FROZEN_ADAPTER_SHA256)

    def test_legacy_stack_is_untouched(self):
        files = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/") for f in glob.glob(os.path.join(PY_ROOT, "execution", "*.py")))
        files.append("agent/agent_loop.py")
        self.assertEqual((digest(files), len(files)), (FROZEN_LEGACY_DIGEST, 27))

    def test_agent_loop_plan_manager_and_process_input_are_untouched(self):
        self.assertEqual(sha("agent/agent_loop.py"), FROZEN_AGENT_LOOP_SHA256)
        self.assertEqual(sha("planning/plan_manager.py"), FROZEN_PLAN_MANAGER_SHA256)
        self.assertEqual(sha("core/core.py"), FROZEN_CORE_SHA256)
        self.assertEqual(sum(1 for n in ast.walk(ast.parse(rel_read("core/core.py"))) if isinstance(n, ast.FunctionDef)
                             and n.name == "process_input"), 1)
        self.assertFalse(hasattr(agent_loop_mod, "execute_agent_tool_step"))

    def test_no_new_production_module_and_no_pycache_in_tree(self):
        for path in production_files():
            base = os.path.basename(path)
            if base.startswith("tool_step_") or base == "tool_capability_mapping.py":
                continue
            self.assertNotIn("planning.tool_step_", read(path), path)
        # Prompt 716 sanctions exactly one route module, as routing metadata only (it executes nothing and is not wired anywhere).
        self.assertEqual(sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/")
                                for f in glob.glob(os.path.join(PY_ROOT, "**", "tool_step_route*.py"), recursive=True)
                                if os.sep + "tests" + os.sep not in f), [ROUTE_RESOLVER_REL])

    def test_pristine_project_database(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
