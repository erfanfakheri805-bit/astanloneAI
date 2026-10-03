"""Prompt 706 - Section 6 integration boundary contract (Section 4 Planner/Plan steps <-> Section 5 controlled tools).

Read-only contract/audit. The ONLY production change this prompt made is the root-cause fix audited in `TestDefectCyclicStructuredData`
(`planning.plan.ensure_structured_data` now rejects self-containing containers with the documented TypeError).

`ToolStepBridge` below is a TEST-LOCAL reference of the PROPOSED boundary. It is not production code and nothing imports it.
It shows that the boundary can be built from the existing public APIs only:

    trusted caller -> ToolStepBridge(registry, grants, confirmed)          (grants live in the caller-owned executor, never in the plan)
    execute_plan_step(plan, step_id, bridge)                               (Prompt 691: validate -> authorize -> start -> executor once)
      -> bridge(step_input)                                                (step-scoped dict; names the tool via input_data["tool_request"])
      -> create_tool_request(name, input, caller grants, caller confirmation)
      -> registry.execute_request(request)                                 (Section 5: _evaluate -> handler -> validation -> ONE audit record)
      -> ToolExecutionResult: succeeded -> returned as step output -> complete_plan_step
                              anything else -> ToolStepFailure raised   -> fail_plan_step   (Section 4 has no other failure channel)

Each test class maps to one numbered item of the Prompt 706 request (see docs/section6_integration_boundary_prompt706.md).
"""
import ast
import builtins
import copy
import hashlib
import inspect
import os
import socket
import sqlite3
import subprocess
import threading
import time
import unittest
from unittest import mock

from capabilities.capability_system import PLANNED_CAPABILITIES
from execution.execution_engine import ExecutionEngine
from planning import plan as plan_mod
from planning.plan import Plan, PlanStep, ensure_structured_data
from planning.plan_runner import run_plan_steps
from planning.plan_step_execution import complete_plan_step, fail_plan_step, start_plan_step
from planning.plan_step_orchestration import execute_plan_step
from tools import in_process_tool_registry as reg_mod
from tools import tool_request as req_mod
from tools.in_process_tool_registry import (InProcessToolRegistry, ToolExecutionResult, ToolInvocationRecord, ToolSpec,
                                            normalize_tool_output)
from tools.tool_definition import SUPPORTED_PERMISSIONS
from tools.tool_request import ToolRequest, create_tool_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

BRIDGE_MODULE = "planning/tool_step_bridge.py"      # Prompt 707: the single planning module allowed to import tools
STEP_INPUT_KEYS = {"step_id", "description", "input_data", "expected_output", "required_capabilities"}
RECORD_KEYS = {"sequence", "tool_name", "status", "ok", "outcome_code", "handler_called", "input_json_safe", "input_type",
               "input", "output_available", "output", "failures", "authorization_decision", "authorization_code",
               "required_permissions", "granted_permissions", "confirmed", "required_capabilities",
               "granted_capabilities"}
REQUEST_ARG_KEYS = {"name", "tool_input", "granted_permissions", "confirmed", "granted_capabilities"}


# ----------------------------------------------------------------------------------------------------------------------
# Test-local reference of the proposed boundary (NOT production code)
# ----------------------------------------------------------------------------------------------------------------------
class ToolStepFailure(Exception):
    """Raised by the bridge for anything that is not a succeeded ToolExecutionResult (Section 4's only failure channel)."""


class ToolStepBridge:
    """Caller-owned executor. Grants and confirmation are held HERE (trusted caller data), never read from the plan."""

    def __init__(self, registry, granted_permissions=(), granted_capabilities=(), confirmed=False):
        self.registry = registry
        self._permissions = tuple(granted_permissions)
        self._capabilities = tuple(granted_capabilities)
        self._confirmed = confirmed
        self.requests = []          # the ToolRequests it built (for assertions)

    def __call__(self, step_input):
        spec = step_input["input_data"].get("tool_request") if isinstance(step_input.get("input_data"), dict) else None
        if not isinstance(spec, dict):
            raise ToolStepFailure("MISSING_TOOL_REQUEST|request_rejected|seq=none")
        created = create_tool_request(spec.get("name"), spec.get("input"), list(self._permissions),
                                      list(self._capabilities), self._confirmed)
        if not created.ok:
            raise ToolStepFailure("|".join(created.codes()) + "|request_rejected|seq=none")
        self.requests.append(created.request)
        result = self.registry.execute_request(created.request)
        if not result.ok:
            raise ToolStepFailure(f"{result.outcome_code}|{result.execution_status}|seq={result.sequence}")
        return {"tool_result": result.to_dict()}


class Counting:
    def __init__(self, fn=None):
        self.fn, self.calls = fn, []

    def __call__(self, tool_input):
        self.calls.append(tool_input)
        return self.fn(tool_input) if self.fn else {"echo": tool_input}

    @property
    def count(self):
        return len(self.calls)


def make_registry():
    """A registry with one tool per failure family. Returns (registry, {tool name: Counting handler})."""
    reg, h = InProcessToolRegistry(), {}

    def add(name, fn=None, **kw):
        h[name] = Counting(fn)
        res = reg.register(ToolSpec(name=name, description="d " + name, handler=h[name], input_schema={"type": "object"},
                                    output_description="o", enabled=kw.pop("enabled", True), **kw))
        assert res.ok, res.codes()

    def boom(_):
        raise RuntimeError("x" * 10000)

    add("echo")
    add("net", permissions=["network"])
    add("confirm", permissions=["user_confirmation"])
    add("needs_cap", capabilities=["cap_a"])
    add("boom", boom)
    add("badout", lambda _: (1, 2))
    add("typed", lambda _: 1, output_type="string")
    add("off", enabled=False)
    return reg, h


def step(sid, name=None, tool_input=None, deps=None, caps=None, extra=None, description="a step"):
    data = None
    if name is not None:
        data = {"tool_request": {"name": name, "input": {} if tool_input is None else tool_input}}
        if extra:
            data["tool_request"].update(extra)
    return PlanStep(sid, description, dependencies=deps, required_capabilities=caps, input_data=data)


def plan_of(*steps, authorized=True):
    return Plan("p", "g", steps=list(steps), created_at="1970-01-01T00:00:00+00:00",
                metadata={"phase": "planning", "executed": False, "execution_authorized": authorized})


def reason_parts(plan, sid):
    """(outcome code or request code, status label, seq) from a failed step's stored reason payload."""
    st = next(s for s in plan.steps if s.step_id == sid)
    assert st.status == "failed", st.status
    assert st.output_data["code"] == "EXECUTOR_EXCEPTION" and st.output_data["exception_type"] == "ToolStepFailure"
    return tuple(st.output_data["message"].split("|"))


def imported_modules(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            mods.add(base)
            mods.update(f"{base}.{a.name}" for a in node.names)
    return mods


def production_files(exclude_dirs=("tests", "__pycache__")):
    for root, dirs, files in os.walk(PY_ROOT):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def rel(path):
    return os.path.relpath(path, PY_ROOT).replace(os.sep, "/")


# ----------------------------------------------------------------------------------------------------------------------
# 1. Planner / plan steps -> tool execution boundary
# ----------------------------------------------------------------------------------------------------------------------
class TestBoundaryPlanToTool(unittest.TestCase):
    def test_executor_gets_only_step_scoped_plain_data(self):
        reg, _ = make_registry()
        seen = []
        plan = plan_of(step("s1", "echo", {"a": 1}, caps=["cap_a"]))
        execute_plan_step(plan, "s1", lambda si: seen.append(si) or {"ok": 1})
        self.assertEqual(set(seen[0]), STEP_INPUT_KEYS)
        self.assertNotIsInstance(seen[0], (Plan, PlanStep))
        self.assertEqual(seen[0]["input_data"], {"tool_request": {"name": "echo", "input": {"a": 1}}})
        self.assertEqual(reg.invocation_count(), 0)      # the plan layer alone never touches a registry

    def test_unauthorized_plan_never_reaches_registry(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", "echo"), authorized=False)
        res = execute_plan_step(plan, "s1", ToolStepBridge(reg, confirmed=True))
        self.assertEqual((res.status, res.reason, res.executor_called), ("rejected", "EXECUTION_NOT_AUTHORIZED", False))
        self.assertEqual((plan.steps[0].status, reg.invocation_count(), h["echo"].count), ("pending", 0, 0))

    def test_unready_step_never_reaches_registry(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", "echo"), step("s2", "echo", deps=["s1"]))
        res = execute_plan_step(plan, "s2", ToolStepBridge(reg))
        self.assertEqual((res.status, res.reason), ("rejected", "STEP_NOT_READY"))
        self.assertEqual((reg.invocation_count(), h["echo"].count), (0, 0))

    def test_invalid_plan_never_reaches_registry(self):
        reg, h = make_registry()
        bad = plan_of(step("s1", "echo", deps=["missing"]))
        res = execute_plan_step(bad, "s1", ToolStepBridge(reg))
        self.assertEqual(res.status, "rejected")
        self.assertEqual((reg.invocation_count(), h["echo"].count), (0, 0))

    def test_planning_and_tools_packages_do_not_import_each_other(self):
        for path in production_files():
            r = rel(path)
            mods = imported_modules(path)
            if r.startswith("planning/") and r != BRIDGE_MODULE:      # Prompt 707: the bridge is the one sanctioned importer
                self.assertFalse({m for m in mods if m == "tools" or m.startswith("tools.")}, r)
            if r.startswith("tools/"):
                self.assertFalse({m for m in mods if m.split(".")[0] in ("planning", "agent", "execution")}, r)

    def test_no_production_module_outside_tools_imports_tools(self):
        offenders = [rel(p) for p in production_files() if not rel(p).startswith("tools/")
                     and any(m == "tools" or m.startswith("tools.") for m in imported_modules(p))]
        self.assertEqual(sorted(offenders), sorted([BRIDGE_MODULE, "agent/tool_step_intent.py"]))      # Prompt 707: the caller-driven tool-step bridge; Prompt 719-A: the caller-side intent adapter (imports only tools.tool_request)

    def test_agent_loop_is_not_wired_to_section4_step_layer_or_tools(self):
        step_layer = {"planning.plan_step_execution", "planning.plan_step_orchestration", "planning.plan_runner",
                      "planning.plan_step_report", "planning.plan_run_summary", "planning.plan_status_rollup"}
        offenders = [rel(p) for p in production_files() if not rel(p).startswith("planning/")
                     and imported_modules(p) & step_layer]
        self.assertEqual(offenders, [], "Prompt 706 audit: the Prompt 689-694 step layer is not consumed outside planning/.")
        self.assertIn("execution.plan_execution_controller", imported_modules(os.path.join(PY_ROOT, "agent", "agent_loop.py")))


# ----------------------------------------------------------------------------------------------------------------------
# 2. A plan step explicitly identifies a requested tool (no invented tools)
# ----------------------------------------------------------------------------------------------------------------------
class TestExplicitToolIdentification(unittest.TestCase):
    def test_plan_step_has_no_tool_field_and_contract_is_unchanged(self):
        self.assertEqual(PlanStep.__slots__, ("step_id", "description", "dependencies", "required_capabilities",
                                              "expected_output", "status", "input_data", "output_data"))
        self.assertFalse([s for s in PlanStep.__slots__ + Plan.__slots__ if "tool" in s])

    def test_step_names_tool_through_input_data_only(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", "echo", {"k": [1, 2]}))
        bridge = ToolStepBridge(reg)
        self.assertTrue(execute_plan_step(plan, "s1", bridge).ok)
        self.assertEqual((bridge.requests[0].name, bridge.requests[0].input), ("echo", {"k": [1, 2]}))
        self.assertEqual(h["echo"].calls, [{"k": [1, 2]}])

    def test_description_text_never_selects_a_tool(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", description="please run the echo tool with a=1"))
        res = execute_plan_step(plan, "s1", ToolStepBridge(reg))
        self.assertEqual(res.status, "failed")
        self.assertEqual(reason_parts(plan, "s1")[0], "MISSING_TOOL_REQUEST")
        self.assertEqual((reg.invocation_count(), h["echo"].count), (0, 0))

    def test_expected_output_and_capabilities_never_select_a_tool(self):
        reg, h = make_registry()
        st = PlanStep("s1", "x", required_capabilities=["cap_a"], expected_output="echo")
        res = execute_plan_step(plan_of(st), "s1", ToolStepBridge(reg, granted_capabilities=["cap_a"], confirmed=True))
        self.assertEqual(res.status, "failed")
        self.assertEqual(sum(x.count for x in h.values()), 0)

    def test_unknown_names_are_never_guessed(self):
        for name in ("Echo", "ech", "echo2", "echo_", "ECHO", "echo tool"):
            with self.subTest(name=name):
                reg, h = make_registry()
                plan = plan_of(step("s1", name))
                execute_plan_step(plan, "s1", ToolStepBridge(reg))
                code, status, seq = reason_parts(plan, "s1")
                self.assertTrue(code in ("UNKNOWN_TOOL", "INVALID_TOOL_REQUEST_NAME"), code)
                self.assertEqual(sum(x.count for x in h.values()), 0)

    def test_trailing_newline_and_whitespace_names_rejected(self):
        for name in ("echo\n", " echo", "echo ", "", None, 5):
            with self.subTest(name=name):
                reg, h = make_registry()
                plan = plan_of(PlanStep("s1", "x", input_data={"tool_request": {"name": name, "input": {}}}))
                execute_plan_step(plan, "s1", ToolStepBridge(reg))
                self.assertEqual(reason_parts(plan, "s1")[0], "INVALID_TOOL_REQUEST_NAME")
                self.assertEqual((reg.invocation_count(), h["echo"].count), (0, 0))

    def test_bridge_never_lists_or_describes_registry_tools(self):
        reg, _ = make_registry()
        boom = AssertionError("discovery/selection attempted")
        with mock.patch.object(InProcessToolRegistry, "list_names", side_effect=boom), \
                mock.patch.object(InProcessToolRegistry, "list_descriptions", side_effect=boom), \
                mock.patch.object(InProcessToolRegistry, "describe", side_effect=boom):
            self.assertTrue(execute_plan_step(plan_of(step("s1", "echo")), "s1", ToolStepBridge(reg)).ok)
            plan = plan_of(step("s1", "nope"))
            execute_plan_step(plan, "s1", ToolStepBridge(reg))
            self.assertEqual(reason_parts(plan, "s1")[0], "UNKNOWN_TOOL")

    def test_registered_tools_are_not_run_unless_a_step_names_them(self):
        reg, h = make_registry()
        plan = plan_of(step("s1"), step("s2", description="echo net confirm"))
        run_plan_steps(plan, ToolStepBridge(reg, confirmed=True), 5)
        self.assertEqual((sum(x.count for x in h.values()), reg.invocation_count()), (0, 0))


# ----------------------------------------------------------------------------------------------------------------------
# 3. Who supplies granted permissions and capabilities
# ----------------------------------------------------------------------------------------------------------------------
class TestGrantsAreCallerSupplied(unittest.TestCase):
    def run_tool(self, name, bridge_kwargs=None, extra=None, caps=None, authorized=True):
        reg, h = make_registry()
        plan = plan_of(step("s1", name, extra=extra, caps=caps), authorized=authorized)
        res = execute_plan_step(plan, "s1", ToolStepBridge(reg, **(bridge_kwargs or {})))
        return reg, h, plan, res

    def test_grants_in_step_data_are_ignored(self):
        claims = {"granted_permissions": ["network"], "granted_capabilities": ["cap_a"], "confirmed": True,
                  "permissions": ["network"], "authorized": True}
        reg, h, plan, res = self.run_tool("net", extra=claims)
        self.assertEqual(reason_parts(plan, "s1")[:2], ("TOOL_PERMISSION_DENIED", "authorization_rejected"))
        self.assertEqual(h["net"].count, 0)

    def test_grants_in_step_input_data_top_level_are_ignored(self):
        reg, h = make_registry()
        st = PlanStep("s1", "x", input_data={"tool_request": {"name": "confirm", "input": {}}, "confirmed": True,
                                             "granted_permissions": ["user_confirmation"]})
        plan = plan_of(st)
        execute_plan_step(plan, "s1", ToolStepBridge(reg))
        self.assertEqual(reason_parts(plan, "s1")[0], "TOOL_CONFIRMATION_REQUIRED")

    def test_caller_grants_authorize_and_are_visible_in_the_audit_record(self):
        reg, h, plan, res = self.run_tool("net", {"granted_permissions": ["network", "network"]})
        self.assertTrue(res.ok)
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["granted_permissions"], rec["required_permissions"]), (["network"], ["network"]))

    def test_step_required_capabilities_are_a_requirement_not_a_grant(self):
        reg, h, plan, res = self.run_tool("needs_cap", caps=["cap_a"])
        self.assertEqual(reason_parts(plan, "s1")[:2], ("TOOL_CAPABILITY_MISSING", "authorization_rejected"))
        self.assertEqual(h["needs_cap"].count, 0)
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["granted_capabilities"], rec["required_capabilities"]), ([], ["cap_a"]))

    def test_caller_capability_grant_is_honored(self):
        reg, h, plan, res = self.run_tool("needs_cap", {"granted_capabilities": ["cap_a"]})
        self.assertTrue(res.ok)
        self.assertEqual(h["needs_cap"].count, 1)

    def test_plan_authorization_is_not_a_tool_grant(self):
        reg, h, plan, res = self.run_tool("net", authorized=True)
        self.assertEqual(plan.metadata["execution_authorized"], True)
        self.assertEqual(reason_parts(plan, "s1")[0], "TOOL_PERMISSION_DENIED")

    def test_tool_grants_are_not_plan_authorization(self):
        reg, h, plan, res = self.run_tool("echo", {"granted_permissions": list(SUPPORTED_PERMISSIONS),
                                                   "granted_capabilities": ["cap_a"], "confirmed": True},
                                          authorized=False)
        self.assertEqual((res.status, res.reason), ("rejected", "EXECUTION_NOT_AUTHORIZED"))
        self.assertEqual((plan.steps[0].status, reg.invocation_count()), ("pending", 0))

    def test_registry_keeps_no_authorization_state_between_calls(self):
        reg, h = make_registry()
        first = ToolStepBridge(reg, granted_permissions=["network"])
        second = ToolStepBridge(reg)
        self.assertTrue(execute_plan_step(plan_of(step("s1", "net")), "s1", first).ok)
        plan = plan_of(step("s1", "net"))
        execute_plan_step(plan, "s1", second)
        self.assertEqual(reason_parts(plan, "s1")[0], "TOOL_PERMISSION_DENIED")

    def test_tools_package_never_derives_grants_from_capability_system_or_plan_data(self):
        for path in production_files():
            if rel(path).startswith("tools/"):
                mods = imported_modules(path)
                self.assertFalse({m for m in mods if m.split(".")[0] in ("capabilities", "planning", "execution", "memory")},
                                 rel(path))

    def test_bridge_signature_takes_grants_only_from_its_constructor(self):
        self.assertEqual(list(inspect.signature(ToolStepBridge.__init__).parameters),
                         ["self", "registry", "granted_permissions", "granted_capabilities", "confirmed"])
        self.assertEqual(list(inspect.signature(ToolStepBridge.__call__).parameters), ["self", "step_input"])


# ----------------------------------------------------------------------------------------------------------------------
# 4. Explicit user confirmation
# ----------------------------------------------------------------------------------------------------------------------
class TestConfirmation(unittest.TestCase):
    def outcome(self, **kw):
        reg, h = make_registry()
        plan = plan_of(step("s1", "confirm"))
        res = execute_plan_step(plan, "s1", ToolStepBridge(reg, **kw))
        return reg, h, plan, res

    def test_unconfirmed_is_rejected_before_the_handler(self):
        reg, h, plan, res = self.outcome()
        self.assertEqual(reason_parts(plan, "s1")[:2], ("TOOL_CONFIRMATION_REQUIRED", "authorization_rejected"))
        self.assertEqual(h["confirm"].count, 0)

    def test_confirmed_true_is_the_only_confirmation(self):
        reg, h, plan, res = self.outcome(confirmed=True)
        self.assertTrue(res.ok)
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["confirmed"], rec["authorization_decision"]), (True, "accepted"))

    def test_naming_user_confirmation_as_a_permission_is_not_confirmation(self):
        reg, h, plan, res = self.outcome(granted_permissions=["user_confirmation"])
        self.assertEqual(reason_parts(plan, "s1")[0], "TOOL_CONFIRMATION_REQUIRED")
        self.assertEqual(h["confirm"].count, 0)

    def test_non_bool_confirmation_never_reaches_the_registry(self):
        for value in ("true", "yes", 1, 0, None, [], {"confirmed": True}):
            with self.subTest(value=value):
                reg, h, plan, res = self.outcome(confirmed=value)
                self.assertEqual(reason_parts(plan, "s1")[:1], ("INVALID_TOOL_REQUEST_CONFIRMATION",))
                self.assertEqual((reg.invocation_count(), h["confirm"].count), (0, 0))

    def test_confirmation_is_per_call_and_never_remembered(self):
        reg, h = make_registry()
        self.assertTrue(execute_plan_step(plan_of(step("s1", "confirm")), "s1", ToolStepBridge(reg, confirmed=True)).ok)
        plan = plan_of(step("s1", "confirm"))
        execute_plan_step(plan, "s1", ToolStepBridge(reg))
        self.assertEqual(reason_parts(plan, "s1")[0], "TOOL_CONFIRMATION_REQUIRED")
        self.assertEqual(h["confirm"].count, 1)

    def test_plan_and_step_have_no_confirmation_or_permission_fields(self):
        names = " ".join(PlanStep.__slots__ + Plan.__slots__)
        for word in ("confirm", "permission", "granted", "authoriz"):
            self.assertNotIn(word, names)

    def test_known_gap_confirmation_is_scoped_to_the_executor_not_to_a_request(self):
        """Pinned architectural gap: one confirmed executor confirms EVERY step it runs (the bridge is per-scope, not per-request)."""
        reg, h = make_registry()
        plan = plan_of(step("s1", "confirm"), step("s2", "confirm", {"other": 1}))
        result = run_plan_steps(plan, ToolStepBridge(reg, confirmed=True), 5)
        self.assertEqual(result.completed_step_ids, ["s1", "s2"])
        self.assertEqual(h["confirm"].count, 2)


# ----------------------------------------------------------------------------------------------------------------------
# 5. ToolRequest is created from trusted caller data
# ----------------------------------------------------------------------------------------------------------------------
class TestToolRequestCreation(unittest.TestCase):
    def test_request_combines_step_name_input_with_caller_grants_exactly(self):
        reg, _ = make_registry()
        bridge = ToolStepBridge(reg, ["network", "filesystem"], ["cap_a"], True)
        plan = plan_of(step("s1", "echo", {"x": {"y": [1, 2]}}))
        execute_plan_step(plan, "s1", bridge)
        req = bridge.requests[0]
        self.assertEqual(req.to_dict(), {"name": "echo", "input": {"x": {"y": [1, 2]}},
                                         "granted_permissions": ["network", "filesystem"],
                                         "granted_capabilities": ["cap_a"], "confirmed": True})

    def test_only_the_factory_builds_requests_and_they_hold_no_callables(self):
        with self.assertRaises(TypeError):
            ToolRequest(object(), "echo", {}, (), (), False)
        req = create_tool_request("echo", {"a": 1}).request
        with self.assertRaises(AttributeError):
            req.confirmed = True
        self.assertFalse(hasattr(req, "__dict__"))
        self.assertFalse([v for v in req.to_dict().values() if callable(v)])

    def test_request_is_isolated_from_the_step_and_the_caller_input(self):
        reg, _ = make_registry()
        bridge = ToolStepBridge(reg)
        plan = plan_of(step("s1", "echo", {"a": [1]}))
        execute_plan_step(plan, "s1", bridge)
        bridge.requests[0].input["a"].append(99)
        self.assertEqual(plan.steps[0].input_data["tool_request"]["input"], {"a": [1]})
        self.assertEqual(bridge.requests[0].input, {"a": [1]})

    def test_malformed_request_data_fails_at_creation_and_is_not_audited(self):
        cases = [({"tool_request": {"name": "echo", "input": [1]}}, "INVALID_TOOL_REQUEST_INPUT"),
                 ({"tool_request": {"name": "echo", "input": "text"}}, "INVALID_TOOL_REQUEST_INPUT"),
                 ({"tool_request": {"name": "echo", "input": {"n": float("nan")}}}, "INVALID_TOOL_REQUEST_INPUT"),
                 ({"tool_request": {"name": "echo"}}, "INVALID_TOOL_REQUEST_INPUT"),
                 ({"tool_request": {"name": "Echo!", "input": {}}}, "INVALID_TOOL_REQUEST_NAME"),
                 ({"tool_request": "echo"}, "MISSING_TOOL_REQUEST"),
                 ({"other": 1}, "MISSING_TOOL_REQUEST")]
        for data, code in cases:
            with self.subTest(data=data):
                reg, h = make_registry()
                plan = plan_of(PlanStep("s1", "x", input_data=data))
                execute_plan_step(plan, "s1", ToolStepBridge(reg))
                self.assertEqual(reason_parts(plan, "s1")[0], code)
                self.assertEqual((reg.invocation_count(), h["echo"].count), (0, 0))

    def test_malformed_caller_grants_fail_at_creation_not_in_the_registry(self):
        for kw, code in (({"granted_permissions": ["bogus"]}, "INVALID_TOOL_REQUEST_PERMISSIONS"),
                         ({"granted_capabilities": ["Bad-Name"]}, "INVALID_TOOL_REQUEST_CAPABILITIES"),
                         ({"granted_capabilities": ["cap.x"]}, "INVALID_TOOL_REQUEST_CAPABILITIES")):
            with self.subTest(kw=kw):
                reg, h = make_registry()
                plan = plan_of(step("s1", "echo"))
                execute_plan_step(plan, "s1", ToolStepBridge(reg, **kw))
                self.assertEqual(reason_parts(plan, "s1")[0], code)
                self.assertEqual(reg.invocation_count(), 0)


# ----------------------------------------------------------------------------------------------------------------------
# 6. execute_request() is reached without bypassing Section 5 validation
# ----------------------------------------------------------------------------------------------------------------------
class TestExecuteRequestPath(unittest.TestCase):
    def test_one_evaluate_precedes_one_handler_call_per_step(self):
        reg, _ = make_registry()
        events = []
        orig = InProcessToolRegistry._evaluate

        def spy(self, *a, **k):
            events.append("evaluate")
            return orig(self, *a, **k)

        reg2 = InProcessToolRegistry()
        reg2.register(ToolSpec("echo", "d", lambda i: events.append("handler") or {"ok": 1}, {}, "o", True))
        with mock.patch.object(InProcessToolRegistry, "_evaluate", spy):
            self.assertTrue(execute_plan_step(plan_of(step("s1", "echo")), "s1", ToolStepBridge(reg2)).ok)
        self.assertEqual(events, ["evaluate", "handler"])

    def test_bridge_reaches_the_registry_only_through_execute_request(self):
        reg, _ = make_registry()
        with mock.patch.object(InProcessToolRegistry, "execute_request", autospec=True,
                               side_effect=InProcessToolRegistry.execute_request) as er, \
                mock.patch.object(InProcessToolRegistry, "invoke", autospec=True, side_effect=InProcessToolRegistry.invoke) as inv, \
                mock.patch.object(InProcessToolRegistry, "execute", autospec=True, side_effect=InProcessToolRegistry.execute) as ex:
            execute_plan_step(plan_of(step("s1", "echo")), "s1", ToolStepBridge(reg))
        self.assertEqual((er.call_count, ex.call_count, inv.call_count), (1, 1, 1))
        self.assertIsInstance(er.call_args[0][1], ToolRequest)

    def test_execute_request_arguments_are_exactly_to_registry_arguments(self):
        req = create_tool_request("echo", {"a": 1}, ["network"], ["cap_a"], True).request
        self.assertEqual(set(req.to_registry_arguments()), REQUEST_ARG_KEYS)
        reg, _ = make_registry()
        sentinel = object()
        with mock.patch.object(InProcessToolRegistry, "execute", autospec=True, return_value=sentinel) as ex:
            self.assertIs(reg.execute_request(req), sentinel)
        self.assertEqual((ex.call_args[0], ex.call_args[1]), ((reg,), req.to_registry_arguments()))

    def test_forged_and_non_request_objects_are_rejected_before_any_handler(self):
        reg, h = make_registry()
        for obj in (object.__new__(ToolRequest), {"name": "echo", "tool_input": {}}, "echo", None, 5):
            with self.subTest(obj=type(obj).__name__):
                res = reg.execute_request(obj)
                self.assertEqual((res.outcome_code, res.execution_status, res.handler_called),
                                 ("INVALID_TOOL_REQUEST", "tool_rejected", False))
        self.assertEqual(sum(x.count for x in h.values()), 0)
        self.assertEqual(reg.invocation_count(), 5)

    def test_step_data_cannot_carry_a_request_or_handler_into_the_registry(self):
        reg, h = make_registry()
        req = create_tool_request("echo", {}, [], [], True).request
        with self.assertRaises(Exception):
            PlanStep("s1", "x", input_data={"tool_request": {"name": "echo", "input": {}}, "request": req})
        with self.assertRaises(Exception):
            PlanStep("s1", "x", input_data={"handler": h["echo"]})

    def test_check_order_is_unchanged_through_the_boundary(self):
        reg, h = make_registry()
        for name, code in (("off", "TOOL_DISABLED"), ("nope", "UNKNOWN_TOOL"), ("net", "TOOL_PERMISSION_DENIED"),
                           ("confirm", "TOOL_CONFIRMATION_REQUIRED"), ("needs_cap", "TOOL_CAPABILITY_MISSING")):
            plan = plan_of(step("s1", name))
            execute_plan_step(plan, "s1", ToolStepBridge(reg))
            self.assertEqual(reason_parts(plan, "s1")[0], code)
        self.assertEqual(sum(x.count for x in h.values()), 0)

    def test_caller_side_preflight_leaves_plan_and_audit_untouched(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", "net"))
        req = create_tool_request("net", {}, [], [], False).request
        pre = reg.preflight(**req.to_registry_arguments())
        self.assertEqual((pre.preflight_status, pre.outcome_code), ("rejected", "TOOL_PERMISSION_DENIED"))
        self.assertEqual((plan.steps[0].status, plan.metadata["executed"], reg.invocation_count(), h["net"].count),
                         ("pending", False, 0, 0))


# ----------------------------------------------------------------------------------------------------------------------
# 7. ToolExecutionResult flows back to the plan step
# ----------------------------------------------------------------------------------------------------------------------
class TestResultFlowsBack(unittest.TestCase):
    def test_success_becomes_the_step_output(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", "echo", {"n": 1}))
        res = execute_plan_step(plan, "s1", ToolStepBridge(reg))
        self.assertTrue(res.ok)
        out = plan.steps[0].output_data
        self.assertEqual(set(out), {"tool_result"})
        self.assertEqual(out["tool_result"], reg_result_dict(reg, 1))
        self.assertEqual(out["tool_result"]["output"], {"echo": {"n": 1}})
        self.assertEqual((plan.steps[0].status, res.final_state), ("completed", "completed"))

    def test_step_output_is_plain_json_and_holds_no_handler(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", "echo"))
        execute_plan_step(plan, "s1", ToolStepBridge(reg))
        ok, plain = normalize_tool_output(plan.steps[0].output_data)
        self.assertTrue(ok)
        self.assertEqual(plain, plan.steps[0].output_data)
        keys, stack = set(), [plan.steps[0].output_data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                keys |= set(cur)
                stack += list(cur.values())
            elif isinstance(cur, list):
                stack += cur
            self.assertFalse(callable(cur))
        self.assertNotIn("handler", keys)

    def test_mutation_isolation_between_step_output_and_audit_history(self):
        reg, _ = make_registry()
        plan = plan_of(step("s1", "echo", {"n": [1]}))
        execute_plan_step(plan, "s1", ToolStepBridge(reg))
        plan.steps[0].output_data["tool_result"]["output"]["echo"]["n"].append(2)
        hist = reg.get_invocation_history()
        self.assertEqual(hist[0]["output"], {"echo": {"n": [1]}})
        hist[0]["output"]["echo"]["n"].append(3)
        self.assertEqual(reg.get_invocation_history()[0]["output"], {"echo": {"n": [1]}})

    def test_every_execution_status_is_json_safe_for_a_step(self):
        """All ToolExecutionResult shapes are accepted by Section 4's structured-data check (tool output is the stricter side)."""
        reg, _ = make_registry()
        for name in ("echo", "net", "confirm", "needs_cap", "boom", "badout", "typed", "off", "nope"):
            res = reg.execute(name, {})
            ensure_structured_data(res.to_dict())

    def test_known_hazard_returning_a_rejected_result_completes_the_step(self):
        """Pinned Section 4 limit: the only failure channel is raising. A naive executor that RETURNS a non-succeeded
        ToolExecutionResult dict makes the step COMPLETED. The bridge must raise (see the failure-mapping tests)."""
        reg, h = make_registry()

        def naive(step_input):
            spec = step_input["input_data"]["tool_request"]
            req = create_tool_request(spec["name"], spec["input"]).request
            return reg.execute_request(req).to_dict()

        plan = plan_of(step("s1", "net"))
        res = execute_plan_step(plan, "s1", naive)
        self.assertEqual((res.status, plan.steps[0].status), ("completed", "completed"))
        self.assertEqual(plan.steps[0].output_data["execution_status"], "authorization_rejected")
        self.assertEqual(h["net"].count, 0)

    def test_dependents_only_start_after_a_succeeded_tool_step(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", "net"), step("s2", "echo", deps=["s1"]))
        result = run_plan_steps(plan, ToolStepBridge(reg), 5)
        self.assertEqual((result.stop_reason, result.failed_step_ids), ("STEP_FAILED", ["s1"]))
        self.assertEqual([s.status for s in plan.steps], ["failed", "pending"])
        self.assertEqual(h["echo"].count, 0)


def reg_result_dict(reg, sequence):
    """The ToolExecutionResult dict that corresponds to audit record `sequence` (rebuilt from the record alone)."""
    rec = reg._history[sequence - 1]
    return ToolExecutionResult(rec).to_dict()


# ----------------------------------------------------------------------------------------------------------------------
# 8. ToolInvocationRecord / audit information stays available
# ----------------------------------------------------------------------------------------------------------------------
class TestAuditAvailability(unittest.TestCase):
    def test_one_record_per_tool_attempt_in_order_with_matching_sequence(self):
        reg, _ = make_registry()
        plan = plan_of(step("a", "echo", {"i": 1}), step("b", "net", deps=["a"]))
        bridge = ToolStepBridge(reg)
        self.assertTrue(execute_plan_step(plan, "a", bridge).ok)
        execute_plan_step(plan, "b", bridge)
        hist = reg.get_invocation_history()
        self.assertEqual([(r["sequence"], r["tool_name"], r["outcome_code"]) for r in hist],
                         [(1, "echo", "TOOL_COMPLETED"), (2, "net", "TOOL_PERMISSION_DENIED")])
        self.assertEqual(reason_parts(plan, "b")[2], "seq=2")
        self.assertEqual(plan.steps[0].output_data["tool_result"]["sequence"], 1)

    def test_records_expose_the_full_authorization_context_and_no_handler(self):
        reg, _ = make_registry()
        bridge = ToolStepBridge(reg, ["network", "network"], ["cap_a"], True)
        execute_plan_step(plan_of(step("s1", "net", {"q": 1})), "s1", bridge)
        rec = reg.get_invocation_history()[0]
        self.assertEqual(set(rec), RECORD_KEYS)
        self.assertEqual((rec["input"], rec["granted_permissions"], rec["granted_capabilities"], rec["confirmed"],
                          rec["handler_called"]), ({"q": 1}, ["network"], ["cap_a"], True, True))
        self.assertFalse([v for v in rec.values() if callable(v)])

    def test_history_is_read_only_and_survives_plan_changes(self):
        reg, _ = make_registry()
        plan = plan_of(step("s1", "echo"))
        execute_plan_step(plan, "s1", ToolStepBridge(reg))
        snapshot = copy.deepcopy(reg.get_invocation_history())
        reg.get_invocation_history().clear()
        plan.steps.clear()
        plan.steps.append(PlanStep("z", "other"))
        self.assertEqual(reg.get_invocation_history(), snapshot)
        self.assertNotIn("sequence", repr(plan.to_dict()))

    def test_request_creation_failures_and_plan_rejections_leave_no_record(self):
        """Pinned finding: ONLY calls that reach execute_request() are audited by Section 5."""
        reg, _ = make_registry()
        plan = plan_of(PlanStep("s1", "x", input_data={"tool_request": {"name": "Bad!", "input": {}}}))
        execute_plan_step(plan, "s1", ToolStepBridge(reg))
        execute_plan_step(plan_of(step("s2", "echo"), authorized=False), "s2", ToolStepBridge(reg))
        self.assertEqual(reg.invocation_count(), 0)

    def test_record_class_shape_is_unchanged(self):
        self.assertEqual(set(ToolInvocationRecord.__slots__), RECORD_KEYS)
        self.assertEqual(set(ToolExecutionResult.__slots__), {"tool_name", "execution_status", "outcome_code",
                                                              "authorization_accepted", "authorization_decision",
                                                              "handler_called", "output_available", "output",
                                                              "failures", "sequence"})


# ----------------------------------------------------------------------------------------------------------------------
# 9. Failure mapping
# ----------------------------------------------------------------------------------------------------------------------
# (tool name, bridge kwargs, expected outcome/request code, expected execution status label, expected handler calls)
FAILURE_MAP = [
    ("net", {}, "TOOL_PERMISSION_DENIED", "authorization_rejected", 0),
    ("confirm", {}, "TOOL_CONFIRMATION_REQUIRED", "authorization_rejected", 0),
    ("needs_cap", {}, "TOOL_CAPABILITY_MISSING", "authorization_rejected", 0),
    ("boom", {}, "TOOL_HANDLER_EXCEPTION", "handler_failed", 1),
    ("badout", {}, "TOOL_OUTPUT_INVALID", "handler_failed", 1),
    ("typed", {}, "TOOL_OUTPUT_VALIDATION_FAILED", "output_invalid", 1),
    ("off", {}, "TOOL_DISABLED", "tool_rejected", 0),
    ("nope", {}, "UNKNOWN_TOOL", "tool_rejected", 0),
]


class TestFailureMapping(unittest.TestCase):
    def test_every_registry_failure_fails_the_step_with_its_code_status_and_sequence(self):
        for name, kw, code, status, calls in FAILURE_MAP:
            with self.subTest(tool=name):
                reg, h = make_registry()
                plan = plan_of(step("s1", name))
                res = execute_plan_step(plan, "s1", ToolStepBridge(reg, **kw))
                self.assertEqual((res.status, res.final_state, res.reason, plan.steps[0].status),
                                 ("failed", "failed", "EXECUTOR_EXCEPTION", "failed"))
                self.assertEqual(reason_parts(plan, "s1"), (code, status, "seq=1"))
                self.assertEqual(h[name].count if name in h else 0, calls)
                self.assertEqual(reg.invocation_count(), 1)
                self.assertEqual(reg.get_invocation_history()[0]["outcome_code"], code)
                self.assertEqual(reg.get_invocation_history()[0]["handler_called"], bool(calls))

    def test_code_survives_the_500_char_reason_truncation_even_for_huge_handler_messages(self):
        reg, _ = make_registry()
        plan = plan_of(step("s1", "boom"))
        execute_plan_step(plan, "s1", ToolStepBridge(reg))
        msg = plan.steps[0].output_data["message"]
        self.assertTrue(msg.startswith("TOOL_HANDLER_EXCEPTION|handler_failed|seq="))
        self.assertLess(len(msg), 100)

    def test_invalid_input_is_rejected_at_the_request_layer_and_by_the_registry_as_defense_in_depth(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", "echo", [1, 2]))
        execute_plan_step(plan, "s1", ToolStepBridge(reg))
        self.assertEqual(reason_parts(plan, "s1")[:2], ("INVALID_TOOL_REQUEST_INPUT", "request_rejected"))
        self.assertEqual(reg.invocation_count(), 0)
        direct = reg.execute("echo", [1, 2])      # only reachable by bypassing ToolRequest
        self.assertEqual((direct.outcome_code, direct.execution_status, direct.handler_called),
                         ("INVALID_TOOL_INPUT", "input_rejected", False))

    def test_invalid_authorization_is_rejected_at_the_request_layer_and_by_the_registry(self):
        reg, _ = make_registry()
        direct = reg.execute("echo", {}, granted_permissions=["bogus"])
        self.assertEqual((direct.outcome_code, direct.execution_status), ("INVALID_TOOL_AUTHORIZATION", "authorization_rejected"))
        plan = plan_of(step("s1", "echo"))
        execute_plan_step(plan, "s1", ToolStepBridge(reg, granted_permissions=["bogus"]))
        self.assertEqual(reason_parts(plan, "s1")[0], "INVALID_TOOL_REQUEST_PERMISSIONS")

    def test_failed_step_is_final_no_retry_no_restart(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", "boom"))
        bridge = ToolStepBridge(reg)
        execute_plan_step(plan, "s1", bridge)
        again = execute_plan_step(plan, "s1", ToolStepBridge(reg, granted_permissions=list(SUPPORTED_PERMISSIONS), confirmed=True))
        self.assertEqual((again.status, again.reason, again.executor_called), ("rejected", "STEP_NOT_READY", False))
        self.assertEqual((h["boom"].count, reg.invocation_count()), (1, 1))

    def test_runner_stops_at_the_first_failed_tool_step_and_never_retries(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", "echo"), step("s2", "boom", deps=["s1"]), step("s3", "echo", deps=["s2"]))
        result = run_plan_steps(plan, ToolStepBridge(reg), 10)
        self.assertEqual((result.stop_reason, result.completed_step_ids, result.failed_step_ids, result.ok),
                         ("STEP_FAILED", ["s1"], ["s2"], False))
        self.assertEqual([s.status for s in plan.steps], ["completed", "failed", "pending"])
        self.assertEqual((h["echo"].count, h["boom"].count), (1, 1))
        self.assertEqual([r["outcome_code"] for r in reg.get_invocation_history()], ["TOOL_COMPLETED", "TOOL_HANDLER_EXCEPTION"])

    def test_rejected_tool_leaves_the_step_failed_not_stuck_in_progress(self):
        reg, _ = make_registry()
        plan = plan_of(step("s1", "net"))
        execute_plan_step(plan, "s1", ToolStepBridge(reg))
        self.assertNotIn("in_progress", [s.status for s in plan.steps])

    def test_mapping_table_covers_every_execution_status_and_outcome_of_the_registry(self):
        covered = {(c, s) for _, _, c, s, _ in FAILURE_MAP}
        for code, status in reg_mod._EXEC_STATUS_BY_CODE.items():
            if status == "succeeded":
                continue
            reachable_via_request = code not in ("INVALID_TOOL_INPUT", "INVALID_TOOL_AUTHORIZATION", "INVALID_TOOL_REQUEST")
            if reachable_via_request:
                self.assertIn((code, status), covered, code)


# ----------------------------------------------------------------------------------------------------------------------
# 10. No implicit authorization, selection, retries, persistence, scheduling, background work, networking, external APIs
# ----------------------------------------------------------------------------------------------------------------------
class TestNoImplicitBehavior(unittest.TestCase):
    def full_flow(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", "echo"), step("s2", "net", deps=["s1"]), step("s3", "boom", deps=["s1"]))
        bridge = ToolStepBridge(reg, ["network"], confirmed=True)
        run_plan_steps(plan, bridge, 5)
        execute_plan_step(plan, "s3", bridge)
        return reg, h

    def test_flow_starts_no_threads_processes_sockets_databases_files_or_sleeps(self):
        threads = threading.active_count()
        deny = AssertionError("forbidden side effect")
        with mock.patch.object(socket, "socket", side_effect=deny), \
                mock.patch.object(subprocess, "Popen", side_effect=deny), \
                mock.patch.object(threading.Thread, "start", side_effect=deny), \
                mock.patch.object(sqlite3, "connect", side_effect=deny), \
                mock.patch.object(time, "sleep", side_effect=deny), \
                mock.patch.object(os, "system", side_effect=deny), \
                mock.patch.object(builtins, "open", side_effect=deny):
            reg, h = self.full_flow()
        self.assertEqual(threading.active_count(), threads)
        self.assertEqual(reg.invocation_count(), 3)

    def test_no_retry_each_handler_runs_at_most_once_per_step(self):
        reg, h = self.full_flow()
        self.assertEqual({k: v.count for k, v in h.items() if v.count}, {"echo": 1, "net": 1, "boom": 1})

    def test_no_state_shared_between_registries_and_no_module_level_registry(self):
        reg, _ = self.full_flow()
        self.assertEqual(InProcessToolRegistry().invocation_count(), 0)
        for mod in (reg_mod, req_mod):
            self.assertFalse([n for n, v in vars(mod).items() if isinstance(v, (InProcessToolRegistry, ToolRequest))], mod.__name__)

    def test_tools_and_step_layer_modules_use_no_network_process_thread_or_persistence_imports(self):
        banned = {"socket", "http", "urllib", "requests", "subprocess", "threading", "multiprocessing", "asyncio", "sched",
                  "sqlite3", "pickle", "shelve", "json", "os", "sys", "shutil", "tempfile", "time", "random", "importlib"}
        for path in production_files():
            r = rel(path)
            if r.startswith("tools/") or r in ("planning/plan_step_execution.py", "planning/plan_step_orchestration.py",
                                                "planning/plan_runner.py"):
                found = {m.split(".")[0] for m in imported_modules(path)} & banned
                self.assertFalse(found, f"{r}: {sorted(found)}")

    def test_no_automatic_selection_granting_or_confirmation_anywhere_in_the_bridge_path(self):
        reg, h = make_registry()
        plan = plan_of(step("s1", "confirm"), step("s2", "net"))
        bridge = ToolStepBridge(reg)
        run_plan_steps(plan, bridge, 5)
        self.assertEqual([r["granted_permissions"] for r in reg.get_invocation_history()], [[]])
        self.assertEqual([r["confirmed"] for r in reg.get_invocation_history()], [False])
        self.assertEqual(sum(x.count for x in h.values()), 0)


# ----------------------------------------------------------------------------------------------------------------------
# 11. Existing Section 4 and Section 5 contracts are preserved
# ----------------------------------------------------------------------------------------------------------------------
class TestContractsPreserved(unittest.TestCase):
    def sig(self, fn):
        return str(inspect.signature(fn))

    def test_section4_public_signatures(self):
        self.assertEqual(self.sig(execute_plan_step), "(plan, step_id, executor)")
        self.assertEqual(self.sig(run_plan_steps), "(plan, executor, max_steps)")
        self.assertEqual(self.sig(start_plan_step), "(plan, step_id)")
        self.assertEqual(self.sig(complete_plan_step), "(plan, step_id, output)")
        self.assertEqual(self.sig(fail_plan_step), "(plan, step_id, reason)")

    def test_ensure_structured_data_keeps_its_public_parameters(self):
        params = list(inspect.signature(ensure_structured_data).parameters.values())
        self.assertEqual([p.name for p in params[:2]], ["value", "_path"])
        self.assertEqual(params[1].default, "value")
        self.assertTrue(all(p.default is None for p in params[2:]))

    def test_section5_public_signatures(self):
        self.assertEqual(self.sig(create_tool_request),
                         "(name, tool_input, granted_permissions=None, granted_capabilities=None, confirmed=False)")
        self.assertEqual(self.sig(InProcessToolRegistry.execute_request), "(self, request)")
        self.assertEqual(self.sig(InProcessToolRegistry.execute),
                         "(self, name, tool_input, granted_permissions=None, confirmed=False, granted_capabilities=None)")
        self.assertEqual(self.sig(InProcessToolRegistry.preflight),
                         "(self, name, tool_input, granted_permissions=None, confirmed=False, granted_capabilities=None)")

    def test_section4_step_input_and_step_dict_shapes(self):
        st = PlanStep("s", "d")
        self.assertEqual(set(st.to_dict()), {"step_id", "description", "dependencies", "required_capabilities",
                                             "expected_output", "status", "input_data", "output_data"})
        seen = []
        execute_plan_step(plan_of(step("s1", "echo")), "s1", lambda si: seen.append(set(si)) or "x")
        self.assertEqual(seen, [STEP_INPUT_KEYS])

    def test_section4_execution_semantics_are_unchanged_for_valid_data(self):
        plan = plan_of(step("s1", "echo"))
        res = execute_plan_step(plan, "s1", lambda si: {"answer": [1, {"b": None}], "t": (1, 2)})
        self.assertEqual((res.status, plan.steps[0].output_data), ("completed", {"answer": [1, {"b": None}], "t": [1, 2]}))
        p2 = plan_of(step("s1", "echo"))
        res2 = execute_plan_step(p2, "s1", lambda si: None)
        self.assertEqual((res2.status, res2.reason), ("failed", "EXECUTOR_OUTPUT_INVALID"))

    def test_section5_tuple_status_and_code_vocabularies(self):
        self.assertEqual(set(reg_mod._EXEC_STATUS_BY_CODE.values()),
                         {"succeeded", "handler_failed", "authorization_rejected", "output_invalid", "input_rejected",
                          "tool_rejected"})
        self.assertEqual(req_mod.REQUEST_INVALID_NAME, "INVALID_TOOL_REQUEST_NAME")
        self.assertEqual(reg_mod.TOOL_INVALID_REQUEST, "INVALID_TOOL_REQUEST")


# ----------------------------------------------------------------------------------------------------------------------
# 12. Contradictory or duplicated authority (audit findings, each pinned by a test)
# ----------------------------------------------------------------------------------------------------------------------
class TestAuthorityAudit(unittest.TestCase):
    def test_F1_two_step_execution_stacks_exist_and_only_the_legacy_one_is_used_by_the_agent_loop(self):
        """FINDING F1: legacy ExecutionEngine/PlanExecutionController (used by AgentLoop; has retry_step, never reads
        metadata['execution_authorized']) vs the Prompt 689-694 layer (authorization flag, no retry, unused by AgentLoop)."""
        self.assertTrue(hasattr(ExecutionEngine, "retry_step"))
        for sub in ("agent", "execution"):
            for path in production_files():
                if rel(path).startswith(sub + "/"):
                    with open(path, encoding="utf-8") as fh:
                        self.assertNotIn("execution_authorized", fh.read(), rel(path))

    def test_F1b_step_layer_never_calls_the_legacy_engine_or_retry(self):
        for name in ("plan_step_execution", "plan_step_orchestration", "plan_runner", "plan_step_report"):
            mods = imported_modules(os.path.join(PY_ROOT, "planning", name + ".py"))
            self.assertFalse({m for m in mods if m.startswith("execution")}, name)

    def test_F2_three_capability_concepts_and_one_grant_vocabulary(self):
        """FINDING F2: Section 4 step.required_capabilities is free-form (checked against CapabilitySystem availability);
        Section 5 grants are strict names. A step may require a name that can never be granted."""
        ok_names = [n for n, _ in PLANNED_CAPABILITIES]
        for n in ok_names:
            self.assertTrue(create_tool_request("echo", {}, None, [n]).ok, n)
        self.assertEqual(PlanStep("s", "d", required_capabilities=["cap.x"]).required_capabilities, ["cap.x"])
        self.assertEqual(create_tool_request("echo", {}, None, ["cap.x"]).codes(), ["INVALID_TOOL_REQUEST_CAPABILITIES"])

    def test_F3_json_safety_asymmetry_is_fail_closed_in_both_directions(self):
        """FINDING F3: Section 4 structured data is more lenient (NaN/inf) than Section 5 JSON. plan->tool fails closed at
        create_tool_request; tool->plan is always accepted (Section 5 output is a subset of Section 4 structured data)."""
        for bad in (float("nan"), float("inf")):
            self.assertEqual(ensure_structured_data({"x": bad}), {"x": bad})
            self.assertEqual(create_tool_request("echo", {"x": bad}).codes(), ["INVALID_TOOL_REQUEST_INPUT"])
        samples = [None, True, 1, 1.5, "s", [], {}, {"a": [1, {"b": None}]}, [[[]]], {"k": {"k": {"k": 1}}}]
        for value in samples:
            valid, plain = normalize_tool_output(value)
            self.assertTrue(valid)
            self.assertEqual(ensure_structured_data(plain), plain)

    def test_F4_single_authority_for_names_and_permissions(self):
        self.assertIs(req_mod._NAME_RE, reg_mod._NAME_RE)
        self.assertIs(req_mod.SUPPORTED_PERMISSIONS, SUPPORTED_PERMISSIONS)
        self.assertIs(reg_mod.SUPPORTED_PERMISSIONS, SUPPORTED_PERMISSIONS)
        self.assertIs(req_mod.normalize_tool_output, reg_mod.normalize_tool_output)

    def test_F5_confirmation_and_authorization_have_one_owner_each(self):
        """FINDING F5: plan authorization (metadata flag) permits STEP execution; tool grants/confirmation (per-call
        ToolRequest arguments, evaluated only by the registry) permit TOOL calls. Neither derives from the other."""
        reg, _ = make_registry()
        plan = plan_of(step("s1", "confirm"))
        self.assertTrue(start_plan_step(plan, "s1").ok)
        self.assertEqual(reg.invocation_count(), 0)
        self.assertEqual(plan.metadata["execution_authorized"], True)
        self.assertEqual(reg.execute("confirm", {}).outcome_code, "TOOL_CONFIRMATION_REQUIRED")
        self.assertEqual(plan.metadata["execution_authorized"], True)

    def test_F6_step_failure_channel_is_binary_return_or_raise(self):
        """FINDING F6: execute_plan_step has no structured 'tool failed' outcome; a failure is a raised exception and only
        its type and (truncated) message reach the step. The bridge encodes code|status|seq in the message."""
        plan = plan_of(step("s1", "echo"))
        execute_plan_step(plan, "s1", lambda si: (_ for _ in ()).throw(ToolStepFailure("CODE|status|seq=7")))
        self.assertEqual(set(plan.steps[0].output_data), {"code", "exception_type", "message"})
        self.assertEqual(reason_parts(plan, "s1"), ("CODE", "status", "seq=7"))

    def test_F7_registry_and_request_share_the_same_execution_path_no_second_authority(self):
        fn = ast.parse(inspect.getsource(InProcessToolRegistry.execute_request).replace("    def", "def", 1).replace("\n    ", "\n"))
        body = fn.body[0].body[1:]                       # drop the docstring
        names = {n.attr for st in body for n in ast.walk(st) if isinstance(n, ast.Attribute)}
        names |= {n.id for st in body for n in ast.walk(st) if isinstance(n, ast.Name)}
        self.assertIn("execute", names)
        self.assertFalse(names & {"_evaluate", "_invoke", "invoke", "_entries", "handler", "preflight"}, names)
        self.assertEqual(inspect.getsource(req_mod.ToolRequest.to_registry_arguments).count("deepcopy"), 1)


# ----------------------------------------------------------------------------------------------------------------------
# Defect found by this audit: self-containing structured data escaped Section 4 as RecursionError
# ----------------------------------------------------------------------------------------------------------------------
def cyclic_list():
    c = []
    c.append(c)
    return c


def cyclic_dict():
    d = {}
    d["self"] = d
    return d


class TestDefectCyclicStructuredData(unittest.TestCase):
    """Root cause: `ensure_structured_data` documented `TypeError` for 'a container that contains itself' but recursed until
    `RecursionError`. Through the boundary, an executor returning such a value escaped `execute_plan_step` (documented 'never raises for
    executor failures') and left the step stranded `in_progress`."""

    def test_self_containing_values_raise_typeerror(self):
        inner = []
        inner.append({"back": inner})
        for value in (cyclic_list(), cyclic_dict(), {"a": [cyclic_list()]}, (cyclic_list(),), inner):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(TypeError):
                    ensure_structured_data(value)

    def test_shared_non_cyclic_references_and_valid_data_are_unchanged(self):
        shared = [1, {"k": "v"}]
        out = ensure_structured_data({"a": shared, "b": shared, "c": (shared, shared)})
        self.assertEqual(out, {"a": [1, {"k": "v"}], "b": [1, {"k": "v"}], "c": [[1, {"k": "v"}], [1, {"k": "v"}]]})
        self.assertIsNot(out["a"], shared)
        self.assertEqual(ensure_structured_data([None, True, 1, 1.5, "s"]), [None, True, 1, 1.5, "s"])

    def test_error_paths_and_existing_typeerrors_are_kept(self):
        with self.assertRaisesRegex(TypeError, r"non-string key"):
            ensure_structured_data({1: "x"})
        with self.assertRaisesRegex(TypeError, r"contains a object"):
            ensure_structured_data({"a": [object()]})

    def test_planstep_setters_reject_cycles_and_store_nothing(self):
        st = PlanStep("s", "d", input_data={"keep": 1})
        with self.assertRaises(TypeError):
            st.set_input(cyclic_dict())
        with self.assertRaises(TypeError):
            st.set_output(cyclic_list())
        with self.assertRaises(TypeError):
            PlanStep("t", "d", input_data=cyclic_dict())
        self.assertEqual((st.input_data, st.output_data), ({"keep": 1}, None))

    def test_complete_plan_step_rejects_a_cycle_and_changes_nothing(self):
        plan = plan_of(step("s1", "echo"))
        self.assertTrue(start_plan_step(plan, "s1").ok)
        before = copy.deepcopy(plan.to_dict())
        res = complete_plan_step(plan, "s1", cyclic_list())
        self.assertEqual((res.ok, res.codes()), (False, ["INVALID_EXECUTION_OUTPUT"]))
        self.assertEqual(plan.to_dict(), before)

    def test_execute_plan_step_fails_the_step_cleanly_for_a_cyclic_executor_output(self):
        for bad in (cyclic_list(), cyclic_dict()):
            plan = plan_of(step("s1", "echo"), step("s2", "echo"))
            res = execute_plan_step(plan, "s1", lambda si, bad=bad: bad)
            self.assertEqual((res.status, res.reason, res.final_state), ("failed", "EXECUTOR_OUTPUT_INVALID", "failed"))
            self.assertEqual([s.status for s in plan.steps], ["failed", "pending"])
            self.assertEqual(plan.steps[0].output_data["rejected_by"], "INVALID_EXECUTION_OUTPUT")

    def test_tool_bridge_output_can_carry_no_cycle_and_a_cyclic_tool_output_never_reaches_the_step(self):
        reg = InProcessToolRegistry()
        reg.register(ToolSpec("cyc", "d", lambda i: cyclic_list(), {}, "o", True))
        plan = plan_of(step("s1", "cyc"))
        execute_plan_step(plan, "s1", ToolStepBridge(reg))
        self.assertEqual(reason_parts(plan, "s1")[:2], ("TOOL_OUTPUT_INVALID", "handler_failed"))


# ----------------------------------------------------------------------------------------------------------------------
# Integrity
# ----------------------------------------------------------------------------------------------------------------------
class TestIntegrity(unittest.TestCase):
    def test_database_is_unchanged_by_the_flow(self):
        reg, _ = make_registry()
        run_plan_steps(plan_of(step("s1", "echo"), step("s2", "boom", deps=["s1"])), ToolStepBridge(reg), 5)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_no_pycache_or_pyc_files_in_the_project(self):
        found = []
        for root, dirs, files in os.walk(PY_ROOT):
            found += [os.path.join(root, d) for d in dirs if d == "__pycache__"]
            found += [os.path.join(root, f) for f in files if f.endswith((".pyc", ".pyo"))]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
