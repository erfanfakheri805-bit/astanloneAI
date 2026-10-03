"""Prompt 708 - Section 6 tool-step execution adapter (`planning/tool_step_executor.py`).

Focused tests for `execute_plan_tool_step(plan, step_id, request, registry) -> ToolStepExecutionResult`, which only composes
validate_plan -> start_plan_step -> execute_tool_step (Prompt 707) -> complete_plan_step / fail_plan_step.
Nothing here wires the adapter into process_input() or the Agent Loop. Docs: docs/section6_f1_decision_prompt708.md
"""
import ast
import copy
import hashlib
import inspect
import json
import os
import unittest
from unittest import mock

from planning import tool_step_executor as exec_mod
from planning.plan import Plan, PlanStep
from planning.plan_step_execution import complete_plan_step
from planning.plan_validation import validate_plan
from planning.tool_step_executor import (STATUS_TOOL_STEP_COMPLETED, STATUS_TOOL_STEP_FAILED, STATUS_TOOL_STEP_REJECTED,
                                         TOOL_STEP_BRIDGE_EXCEPTION, TOOL_STEP_BRIDGE_REJECTED, TOOL_STEP_INVALID_PLAN,
                                         TOOL_STEP_INVALID_PLAN_OBJECT, TOOL_STEP_OUTPUT_NOT_RECORDED, TOOL_STEP_TOOL_FAILED,
                                         ToolStepExecutionResult, execute_plan_tool_step)
from tools.in_process_tool_registry import InProcessToolRegistry, ToolSpec
from tools.tool_request import create_tool_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

RESULT_KEYS = {"ok", "status", "step_id", "previous_state", "final_state", "bridge_called", "tool_result", "recorded_output",
               "reason", "failures"}
TOOL_RESULT_KEYS = {"ok", "status", "failure_source", "step_id", "tool_name", "execution_status", "outcome_code",
                    "authorization_decision", "authorization_accepted", "handler_called", "output_available", "output",
                    "failures", "sequence"}


class Counting:
    def __init__(self, fn=None):
        self.fn, self.calls = fn, []

    def __call__(self, tool_input):
        self.calls.append(tool_input)
        return self.fn(tool_input) if self.fn else {"echo": tool_input}

    @property
    def count(self):
        return len(self.calls)


def make_registry(cls=InProcessToolRegistry):
    reg, h = cls(), {}

    def add(name, fn=None, **kw):
        h[name] = Counting(fn)
        res = reg.register(ToolSpec(name=name, description="d " + name, handler=h[name], input_schema={"type": "object"},
                                    output_description="o", enabled=kw.pop("enabled", True), **kw))
        assert res.ok, res.codes()

    def boom(_):
        raise RuntimeError("kaput")

    add("echo")
    add("net", permissions=["network"])
    add("confirm", permissions=["user_confirmation"])
    add("needs_cap", capabilities=["cap_a"])
    add("boom", boom)
    add("badout", lambda _: (1, 2))
    add("typed", lambda _: 1, output_type="string")
    add("off", enabled=False)
    return reg, h


def make_plan(*ids, authorized=True, chain=False):
    ids = ids or ("s1",)
    steps = []
    for n, i in enumerate(ids):
        deps = [ids[n - 1]] if chain and n else []
        steps.append(PlanStep(i, "step " + i, dependencies=deps))
    return Plan("p", "g", steps=steps, created_at="1970-01-01T00:00:00+00:00",
                metadata={"phase": "planning", "executed": False, "execution_authorized": authorized})


def req(name, tool_input=None, perms=None, caps=None, confirmed=False):
    res = create_tool_request(name, {} if tool_input is None else tool_input, perms, caps, confirmed)
    assert res.ok, res.codes()
    return res.request


def snapshot(plan):
    return json.dumps({"steps": [s.to_dict() for s in plan.steps], "metadata": plan.metadata}, sort_keys=True)


def step_of(plan, step_id):
    return next(s for s in plan.steps if s.step_id == step_id)


class TestSuccess(unittest.TestCase):
    def test_successful_tool_step_completes_the_step_with_the_tool_output(self):
        reg, h = make_registry()
        plan = make_plan()
        res = execute_plan_tool_step(plan, "s1", req("echo", {"a": [1, 2]}), reg)
        self.assertIsInstance(res, ToolStepExecutionResult)
        self.assertTrue(res.ok)
        self.assertEqual((res.status, res.step_id, res.previous_state, res.final_state), (STATUS_TOOL_STEP_COMPLETED, "s1",
                                                                                          "pending", "completed"))
        self.assertEqual((res.bridge_called, res.reason, res.failures), (True, None, []))
        step = step_of(plan, "s1")
        self.assertEqual(step.status, "completed")
        self.assertEqual(step.output_data["tool_result"]["output"], {"echo": {"a": [1, 2]}})
        self.assertEqual(step.output_data, {"tool_result": res.tool_result})
        self.assertEqual(res.recorded_output, step.output_data)
        self.assertEqual(plan.metadata["executed"], True)
        self.assertEqual(h["echo"].count, 1)
        self.assertTrue(validate_plan(plan).valid)

    def test_completed_output_integrity_keeps_every_bridge_field(self):
        reg, _ = make_registry()
        plan = make_plan()
        res = execute_plan_tool_step(plan, "s1", req("confirm", perms=["user_confirmation"], confirmed=True), reg)
        tr = step_of(plan, "s1").output_data["tool_result"]
        self.assertEqual(set(tr), TOOL_RESULT_KEYS)
        self.assertEqual((tr["ok"], tr["status"], tr["failure_source"], tr["step_id"], tr["tool_name"]),
                         (True, "succeeded", None, "s1", "confirm"))
        self.assertEqual((tr["execution_status"], tr["outcome_code"], tr["authorization_decision"],
                          tr["authorization_accepted"], tr["handler_called"], tr["output_available"], tr["failures"],
                          tr["sequence"]), ("succeeded", "TOOL_COMPLETED", "accepted", True, True, True, [], 1))
        record = reg.get_invocation_history()[0]
        self.assertEqual((tr["sequence"], tr["outcome_code"], tr["authorization_decision"]),
                         (record["sequence"], record["outcome_code"], record["authorization_decision"]))
        self.assertEqual(set(res.to_dict()), RESULT_KEYS)

    def test_result_and_step_output_are_isolated_copies(self):
        shared = {"k": [1]}
        reg, _ = make_registry()
        reg.register(ToolSpec(name="shared", description="d", handler=lambda _: shared, input_schema={"type": "object"},
                              output_description="o"))
        plan = make_plan()
        res = execute_plan_tool_step(plan, "s1", req("shared"), reg)
        shared["k"].append(2)
        res.tool_result["output"]["k"].append(99)
        res.to_dict()["tool_result"]["output"]["k"].append(98)
        self.assertEqual(step_of(plan, "s1").output_data["tool_result"]["output"], {"k": [1]})

    def test_dependent_step_becomes_runnable_only_after_completion(self):
        reg, _ = make_registry()
        plan = make_plan("s1", "s2", chain=True)
        early = execute_plan_tool_step(plan, "s2", req("echo"), reg)
        self.assertEqual((early.status, early.codes()), (STATUS_TOOL_STEP_REJECTED, ["STEP_NOT_READY"]))
        self.assertEqual(execute_plan_tool_step(plan, "s1", req("echo"), reg).status, STATUS_TOOL_STEP_COMPLETED)
        self.assertEqual(execute_plan_tool_step(plan, "s2", req("echo"), reg).status, STATUS_TOOL_STEP_COMPLETED)


class TestToolFailuresLeaveATerminalFailedStep(unittest.TestCase):
    def assert_failed(self, request, code, execution_status, handler_called, name):
        reg, h = make_registry()
        plan = make_plan()
        res = execute_plan_tool_step(plan, "s1", request, reg)
        record = reg.get_invocation_history()[-1]
        step = step_of(plan, "s1")
        self.assertFalse(res.ok)
        self.assertEqual((res.status, res.reason, res.previous_state, res.final_state, res.bridge_called),
                         (STATUS_TOOL_STEP_FAILED, TOOL_STEP_TOOL_FAILED, "pending", "failed", True))
        self.assertNotEqual(step.status, "in_progress")
        self.assertEqual(step.status, "failed")
        self.assertEqual(step.output_data["code"], TOOL_STEP_TOOL_FAILED)
        tr = step.output_data["tool_result"]
        self.assertEqual(tr, res.tool_result)
        self.assertEqual((tr["status"], tr["failure_source"], tr["ok"]), ("failed", "tool", False))
        self.assertEqual((tr["outcome_code"], tr["execution_status"], tr["handler_called"], tr["tool_name"]),
                         (code, execution_status, handler_called, name))
        self.assertEqual((tr["sequence"], tr["outcome_code"], tr["handler_called"], tr["failures"],
                          tr["authorization_decision"]), (record["sequence"], record["outcome_code"],
                                                          record["handler_called"], record["failures"],
                                                          record["authorization_decision"]))
        self.assertEqual((step.output_data["outcome_code"], step.output_data["sequence"]), (code, record["sequence"]))
        self.assertEqual((tr["output_available"], tr["output"]), (False, None))
        self.assertEqual(sum(x.count for x in h.values()), 1 if handler_called else 0)
        self.assertEqual(reg.invocation_count(), 1)
        self.assertTrue(validate_plan(plan).valid)
        return res, tr

    def test_unknown_tool(self):
        _, tr = self.assert_failed(req("nope"), "UNKNOWN_TOOL", "tool_rejected", False, "nope")
        self.assertEqual(tr["authorization_decision"], "not_evaluated")

    def test_disabled_tool(self):
        self.assert_failed(req("off"), "TOOL_DISABLED", "tool_rejected", False, "off")

    def test_permission_denial(self):
        _, tr = self.assert_failed(req("net"), "TOOL_PERMISSION_DENIED", "authorization_rejected", False, "net")
        self.assertEqual((tr["authorization_decision"], tr["authorization_accepted"]), ("denied", False))
        self.assertEqual(tr["failures"][0]["missing_permissions"], ["network"])

    def test_confirmation_denial(self):
        _, tr = self.assert_failed(req("confirm", perms=["user_confirmation"]), "TOOL_CONFIRMATION_REQUIRED",
                                   "authorization_rejected", False, "confirm")
        self.assertEqual(tr["authorization_decision"], "confirmation_required")

    def test_user_confirmation_grant_alone_is_not_confirmation(self):
        self.assert_failed(req("confirm", perms=["user_confirmation"], confirmed=False), "TOOL_CONFIRMATION_REQUIRED",
                           "authorization_rejected", False, "confirm")

    def test_capability_denial(self):
        _, tr = self.assert_failed(req("needs_cap"), "TOOL_CAPABILITY_MISSING", "authorization_rejected", False, "needs_cap")
        self.assertEqual((tr["authorization_decision"], tr["failures"][0]["missing_capabilities"]),
                         ("capability_missing", ["cap_a"]))

    def test_handler_failure(self):
        _, tr = self.assert_failed(req("boom"), "TOOL_HANDLER_EXCEPTION", "handler_failed", True, "boom")
        self.assertEqual(tr["failures"][0]["exception_type"], "RuntimeError")

    def test_invalid_tool_output_not_json_safe(self):
        self.assert_failed(req("badout"), "TOOL_OUTPUT_INVALID", "handler_failed", True, "badout")

    def test_invalid_tool_output_type_mismatch(self):
        _, tr = self.assert_failed(req("typed"), "TOOL_OUTPUT_VALIDATION_FAILED", "output_invalid", True, "typed")
        self.assertEqual((tr["failures"][0]["expected_type"], tr["failures"][0]["actual_type"]), ("string", "integer"))

    def test_forged_request_is_reported_by_the_registry_not_the_adapter(self):
        from tools.tool_request import ToolRequest
        reg, h = make_registry()
        plan = make_plan()
        res = execute_plan_tool_step(plan, "s1", ToolRequest.__new__(ToolRequest), reg)
        self.assertEqual((res.status, res.tool_result["outcome_code"], res.tool_result["sequence"]),
                         (STATUS_TOOL_STEP_FAILED, "INVALID_TOOL_REQUEST", 1))
        self.assertEqual((step_of(plan, "s1").status, sum(x.count for x in h.values())), ("failed", 0))


class TestInvalidToolInputAndBridgeRejection(unittest.TestCase):
    def test_invalid_tool_input_never_becomes_a_request_and_a_missing_request_fails_the_started_step(self):
        for bad in ([1], "x", None, {"k": float("nan")}, {1: 2}, {"t": (1, 2)}):
            created = create_tool_request("echo", bad)
            self.assertFalse(created.ok)
            reg, h = make_registry()
            plan = make_plan()
            res = execute_plan_tool_step(plan, "s1", created.request, reg)      # request is None
            self.assertEqual((res.status, res.reason, res.final_state), (STATUS_TOOL_STEP_FAILED, TOOL_STEP_BRIDGE_REJECTED,
                                                                          "failed"))
            self.assertEqual((reg.invocation_count(), h["echo"].count), (0, 0))

    def test_bridge_rejection_fails_the_step_and_preserves_the_bridge_result(self):
        cases = [("request", lambda reg: ("not a request", reg), "INVALID_BRIDGE_REQUEST"),
                 ("registry none", lambda reg: (req("echo"), None), "INVALID_BRIDGE_REGISTRY"),
                 ("registry dict", lambda reg: (req("echo"), {"echo": 1}), "INVALID_BRIDGE_REGISTRY")]
        for label, build, code in cases:
            reg, h = make_registry()
            plan = make_plan()
            request, registry = build(reg)
            res = execute_plan_tool_step(plan, "s1", request, registry)
            step = step_of(plan, "s1")
            self.assertEqual((res.status, res.reason, res.previous_state, res.final_state, res.bridge_called),
                             (STATUS_TOOL_STEP_FAILED, TOOL_STEP_BRIDGE_REJECTED, "pending", "failed", True), label)
            self.assertEqual((step.status, step.output_data["code"], step.output_data["outcome_code"]),
                             ("failed", TOOL_STEP_BRIDGE_REJECTED, code), label)
            tr = step.output_data["tool_result"]
            self.assertEqual((tr["status"], tr["failure_source"], tr["outcome_code"], tr["sequence"], tr["handler_called"],
                              tr["execution_status"], tr["authorization_decision"], tr["step_id"]),
                             ("rejected", "bridge", code, None, False, None, None, "s1"), label)
            self.assertEqual(tr["failures"][0]["code"], code)
            self.assertEqual((reg.invocation_count(), h["echo"].count), (0, 0), label)

    def test_bridge_rejection_keeps_the_tool_name_when_known(self):
        plan = make_plan()
        execute_plan_tool_step(plan, "s1", req("echo"), None)
        self.assertEqual(step_of(plan, "s1").output_data["tool_result"]["tool_name"], "echo")


class TestPreStartRejection(unittest.TestCase):
    def assert_rejected_untouched(self, plan, step_id, codes, request=None):
        reg, h = make_registry()
        before = snapshot(plan)
        res = execute_plan_tool_step(plan, step_id, request or req("echo"), reg)
        self.assertEqual((res.status, res.bridge_called, res.tool_result, res.recorded_output),
                         (STATUS_TOOL_STEP_REJECTED, False, None, None))
        self.assertEqual(res.codes(), codes)
        self.assertEqual(res.reason, codes[0])
        self.assertEqual(res.final_state, res.previous_state)
        self.assertEqual(snapshot(plan), before)
        self.assertEqual((reg.invocation_count(), reg.get_invocation_history(), h["echo"].count), (0, [], 0))
        return res

    def test_plan_step_start_rejection_unauthorized(self):
        res = self.assert_rejected_untouched(make_plan(authorized=False), "s1", ["EXECUTION_NOT_AUTHORIZED"])
        self.assertEqual(res.previous_state, "pending")

    def test_plan_step_start_rejection_unknown_step(self):
        self.assert_rejected_untouched(make_plan(), "zzz", ["UNKNOWN_STEP"])

    def test_plan_step_start_rejection_invalid_step_id(self):
        for bad in (None, "", "  ", 1):
            self.assert_rejected_untouched(make_plan(), bad, ["INVALID_STEP_ID"])

    def test_plan_step_start_rejection_dependency_not_completed(self):
        self.assert_rejected_untouched(make_plan("s1", "s2", chain=True), "s2", ["STEP_NOT_READY"])

    def test_plan_step_start_rejection_for_terminal_and_running_steps(self):
        for state in ("completed", "failed", "in_progress"):
            plan = make_plan()
            step = plan.steps[0]
            if state == "in_progress":
                plan.metadata["executed"] = True
            step.status = state
            if state == "completed":
                step.output_data = {"x": 1}
                plan.metadata["executed"] = True
            if state == "failed":
                step.output_data = {"x": 1}
                plan.metadata["executed"] = True
            self.assert_rejected_untouched(plan, "s1", ["STEP_NOT_READY"])

    def test_not_a_plan(self):
        for bad in (None, "plan", {}, 5):
            reg, h = make_registry()
            res = execute_plan_tool_step(bad, "s1", req("echo"), reg)
            self.assertEqual((res.status, res.codes(), res.bridge_called), (STATUS_TOOL_STEP_REJECTED,
                                                                            [TOOL_STEP_INVALID_PLAN_OBJECT], False))
            self.assertEqual((res.previous_state, res.final_state), (None, None))
            self.assertEqual((reg.invocation_count(), h["echo"].count), (0, 0))

    def test_invalid_plan(self):
        empty = Plan("p", "g", steps=[], created_at="1970-01-01T00:00:00+00:00",
                     metadata={"phase": "planning", "executed": False, "execution_authorized": True})
        res = self.assert_rejected_untouched(empty, "s1", [TOOL_STEP_INVALID_PLAN])
        self.assertTrue(res.failures[0]["issues"])
        plan = make_plan("s1", "s2")
        plan.steps[1].dependencies = ["ghost"]
        self.assert_rejected_untouched(plan, "s1", [TOOL_STEP_INVALID_PLAN])

    def test_request_and_registry_are_not_touched_before_the_step_started(self):
        # A hostile registry/request object is never consulted when the plan side rejects first.
        class Trap:
            def __getattr__(self, name):
                raise AssertionError("touched " + name)
        for plan, sid in ((make_plan(authorized=False), "s1"), (make_plan(), "zzz"), (None, "s1")):
            res = execute_plan_tool_step(plan, sid, Trap(), Trap())
            self.assertEqual((res.status, res.bridge_called), (STATUS_TOOL_STEP_REJECTED, False))


class TestNoRetryNoBypass(unittest.TestCase):
    def test_no_retry_after_failure(self):
        reg, h = make_registry()
        plan = make_plan()
        first = execute_plan_tool_step(plan, "s1", req("boom"), reg)
        after_first = snapshot(plan)
        self.assertEqual((first.status, h["boom"].count, reg.invocation_count()), (STATUS_TOOL_STEP_FAILED, 1, 1))
        second = execute_plan_tool_step(plan, "s1", req("boom"), reg)          # a failed step is final
        self.assertEqual((second.status, second.codes()), (STATUS_TOOL_STEP_REJECTED, ["STEP_NOT_READY"]))
        self.assertEqual((h["boom"].count, reg.invocation_count(), snapshot(plan)), (1, 1, after_first))

    def test_a_completed_step_is_not_run_again(self):
        reg, h = make_registry()
        plan = make_plan()
        execute_plan_tool_step(plan, "s1", req("echo"), reg)
        again = execute_plan_tool_step(plan, "s1", req("echo"), reg)
        self.assertEqual((again.status, h["echo"].count, reg.invocation_count()), (STATUS_TOOL_STEP_REJECTED, 1, 1))

    def test_bridge_is_called_exactly_once_and_with_the_callers_own_objects(self):
        reg, _ = make_registry()
        plan, request = make_plan(), req("boom")
        with mock.patch.object(exec_mod, "execute_tool_step", wraps=exec_mod.execute_tool_step) as spy:
            execute_plan_tool_step(plan, "s1", request, reg)
        self.assertEqual(spy.call_count, 1)
        args = spy.call_args[0]
        self.assertIs(args[0], plan)
        self.assertEqual(args[1], "s1")
        self.assertIs(args[2], request)
        self.assertIs(args[3], reg)
        self.assertEqual(spy.call_args[1], {})

    def test_only_execute_request_is_used_on_the_registry_and_handler_runs_only_through_it(self):
        calls = []

        class Spy(InProcessToolRegistry):
            def execute_request(self, request):
                calls.append(("execute_request", request.name))
                return super().execute_request(request)

            def execute(self, *a, **k):
                calls.append(("execute",))
                return super().execute(*a, **k)

            def preflight(self, *a, **k):
                calls.append(("preflight",))
                return super().preflight(*a, **k)

        reg, h = make_registry(Spy)
        execute_plan_tool_step(make_plan(), "s1", req("echo"), reg)
        self.assertEqual(calls, [("execute_request", "echo"), ("execute",)])      # execute() only via execute_request()
        self.assertEqual(h["echo"].count, 1)

    def test_adapter_source_never_reaches_a_handler_a_registry_or_selects_a_tool(self):
        src = inspect.getsource(exec_mod)
        tree = ast.parse(src)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
        # Prompt 709: `copy` (dry-run start on a copy of the plan) is the only import added to the adapter module.
        # Prompt 710: `planning.tool_capability_mapping` (pure F2 translation table) is the only import added since.
        self.assertEqual(imports, {"copy", "planning.plan", "planning.plan_builder", "planning.plan_step_execution",
                                   "planning.plan_validation", "planning.tool_capability_mapping",
                                   "planning.tool_step_bridge"})
        code_only = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        # Prompt 709: `registry.preflight(...)` is the single sanctioned registry call of this module (pre-start check only);
        # `execute_request`/`execute` stay unreachable from here and are only used through the Prompt 707 bridge.
        self.assertIn("preflight", attrs)
        for forbidden in ("handler", "execute_request", "execute", "register", "describe", "list_tools",
                          "required_capabilities", "input_data", "expected_output", "description", "granted_permissions",
                          "granted_capabilities", "confirmed", "create_tool_request", "ToolRequest"):
            self.assertNotIn(forbidden, attrs, forbidden)
            # Prompt 710: `required_capabilities` is now the caller-supplied PARAMETER of execute_plan_tool_step_mapped(); it is
            # still never read as a step attribute (asserted above via `attrs`), so only the bare-name check is relaxed.
            if forbidden != "required_capabilities":
                self.assertNotIn(forbidden, names, forbidden)
        self.assertNotIn("time", imports)
        self.assertNotIn("random", imports)
        del code_only

    def test_signature_has_no_grant_confirmation_or_tool_arguments(self):
        self.assertEqual(list(inspect.signature(execute_plan_tool_step).parameters), ["plan", "step_id", "request", "registry"])
        for extra in ({"confirmed": True}, {"granted_permissions": ["network"]}, {"tool_name": "echo"}, {"retries": 3}):
            reg, _ = make_registry()
            with self.assertRaises(TypeError):
                execute_plan_tool_step(make_plan(), "s1", req("echo"), reg, **extra)


class TestBridgeDefects(unittest.TestCase):
    def test_unexpected_exception_from_a_defective_registry_leaves_a_failed_step_and_is_not_retried(self):
        n = []

        class Broken(InProcessToolRegistry):
            def execute_request(self, request):
                n.append(1)
                raise RuntimeError("registry defect")

        plan = make_plan()
        res = execute_plan_tool_step(plan, "s1", req("echo"), Broken())
        step = step_of(plan, "s1")
        self.assertEqual((res.status, res.reason, res.final_state, step.status), (STATUS_TOOL_STEP_FAILED,
                                                                                 TOOL_STEP_BRIDGE_EXCEPTION, "failed", "failed"))
        self.assertEqual((step.output_data["exception_type"], step.output_data["exception_message"],
                          step.output_data["tool_result"], len(n)), ("RuntimeError", "registry defect", None, 1))
        self.assertTrue(validate_plan(plan).valid)

    def test_base_exception_records_a_failed_step_then_propagates(self):
        class Interrupted(InProcessToolRegistry):
            def execute_request(self, request):
                raise KeyboardInterrupt()

        plan = make_plan()
        with self.assertRaises(KeyboardInterrupt):
            execute_plan_tool_step(plan, "s1", req("echo"), Interrupted())
        step = step_of(plan, "s1")
        self.assertEqual((step.status, step.output_data["code"], step.output_data["exception_type"]),
                         ("failed", TOOL_STEP_BRIDGE_EXCEPTION, "KeyboardInterrupt"))

    def test_unrecordable_success_still_ends_in_a_terminal_failed_step(self):
        reg, _ = make_registry()
        plan = make_plan()
        pending = make_plan()
        refused = complete_plan_step(pending, "s1", {"x": 1})            # a real, refused transition result
        self.assertFalse(refused.ok)
        with mock.patch.object(exec_mod, "complete_plan_step", return_value=refused):
            res = execute_plan_tool_step(plan, "s1", req("echo"), reg)
        step = step_of(plan, "s1")
        self.assertEqual((res.status, res.reason, step.status), (STATUS_TOOL_STEP_FAILED, TOOL_STEP_OUTPUT_NOT_RECORDED,
                                                                "failed"))
        self.assertEqual(step.output_data["tool_result"]["status"], "succeeded")      # the tool result is not lost
        self.assertEqual(step.output_data["rejected_by"], "STEP_NOT_IN_PROGRESS")

    def test_unrecordable_failure_is_reported_not_raised(self):
        reg, _ = make_registry()
        plan = make_plan()
        refused = complete_plan_step(make_plan(), "s1", {"x": 1})
        with mock.patch.object(exec_mod, "fail_plan_step", return_value=refused):
            res = execute_plan_tool_step(plan, "s1", req("boom"), reg)
        self.assertEqual(res.status, STATUS_TOOL_STEP_FAILED)
        self.assertEqual(res.codes(), [TOOL_STEP_TOOL_FAILED, "STEP_TRANSITION_FAILED"])
        self.assertIsNone(res.recorded_output)


class TestAuditSequence(unittest.TestCase):
    def test_tool_audit_sequence_is_preserved_per_step(self):
        reg, _ = make_registry()
        plan = make_plan("s1", "s2", "s3")
        results = [execute_plan_tool_step(plan, "s1", req("echo"), reg), execute_plan_tool_step(plan, "s2", req("net"), reg),
                   execute_plan_tool_step(plan, "s3", req("boom"), reg)]
        hist = reg.get_invocation_history()
        seqs = [step_of(plan, s).output_data["tool_result"]["sequence"] for s in ("s1", "s2", "s3")]
        self.assertEqual(seqs, [1, 2, 3])
        self.assertEqual(seqs, [h["sequence"] for h in hist])
        self.assertEqual([r.tool_result["sequence"] for r in results], seqs)
        self.assertEqual([step_of(plan, s).output_data["tool_result"]["tool_name"] for s in ("s1", "s2", "s3")],
                         [h["tool_name"] for h in hist])
        self.assertEqual([step_of(plan, s).output_data["tool_result"]["outcome_code"] for s in ("s1", "s2", "s3")],
                         [h["outcome_code"] for h in hist])
        self.assertEqual([step_of(plan, s).status for s in ("s1", "s2", "s3")], ["completed", "failed", "failed"])

    def test_one_execution_appends_exactly_one_record_and_pre_start_rejections_none(self):
        reg, _ = make_registry()
        execute_plan_tool_step(make_plan(), "s1", req("echo"), reg)
        self.assertEqual(reg.invocation_count(), 1)
        execute_plan_tool_step(make_plan(authorized=False), "s1", req("echo"), reg)
        execute_plan_tool_step(make_plan(), "nope", req("echo"), reg)
        execute_plan_tool_step(make_plan(), "s1", req("echo"), None)      # bridge rejection: no record either (H3, unchanged)
        self.assertEqual(reg.invocation_count(), 1)


class TestDeterminismAndIsolation(unittest.TestCase):
    def run_flow(self):
        reg, _ = make_registry()
        plan = make_plan("s1", "s2", "s3", "s4")
        out = [execute_plan_tool_step(plan, "s1", req("echo", {"n": 1}), reg).to_dict(),
               execute_plan_tool_step(plan, "s2", req("boom"), reg).to_dict(),
               execute_plan_tool_step(plan, "s3", req("net"), reg).to_dict(),
               execute_plan_tool_step(plan, "s4", None, reg).to_dict(),
               execute_plan_tool_step(plan, "s1", req("echo"), reg).to_dict()]
        return json.dumps(out, sort_keys=True), snapshot(plan), reg.get_invocation_history()

    def test_repeated_runs_are_identical(self):
        a, b, c = self.run_flow(), self.run_flow(), self.run_flow()
        self.assertEqual(a, b)
        self.assertEqual(b, c)

    def test_request_grant_and_confirmation_do_not_leak_between_executions(self):
        reg, h = make_registry()
        plan = make_plan("s1", "s2", "s3", "s4")
        ok = execute_plan_tool_step(plan, "s1", req("confirm", perms=["user_confirmation"], confirmed=True), reg)
        self.assertEqual(ok.status, STATUS_TOOL_STEP_COMPLETED)
        # a later, unconfirmed request for the SAME tool gets no benefit from the earlier confirmation
        denied = execute_plan_tool_step(plan, "s2", req("confirm", perms=["user_confirmation"]), reg)
        self.assertEqual(denied.tool_result["outcome_code"], "TOOL_CONFIRMATION_REQUIRED")
        # a permission granted to one request does not authorize another tool's request
        execute_plan_tool_step(plan, "s3", req("echo", perms=["network"]), reg)
        net = execute_plan_tool_step(plan, "s4", req("net"), reg)
        self.assertEqual(net.tool_result["outcome_code"], "TOOL_PERMISSION_DENIED")
        self.assertEqual(h["confirm"].count, 1)
        self.assertEqual(h["net"].count, 0)

    def test_grants_of_one_plan_run_do_not_survive_into_a_fresh_registry_or_plan(self):
        reg1, _ = make_registry()
        execute_plan_tool_step(make_plan(), "s1", req("net", perms=["network"]), reg1)
        reg2, h2 = make_registry()
        res = execute_plan_tool_step(make_plan(), "s1", req("net"), reg2)
        self.assertEqual(res.tool_result["outcome_code"], "TOOL_PERMISSION_DENIED")
        self.assertEqual(h2["net"].count, 0)

    def test_plan_authorization_is_not_a_tool_grant(self):
        reg, h = make_registry()
        plan = make_plan(authorized=True)
        plan.metadata["granted_permissions"] = ["network"]           # plan data can never grant anything
        plan.steps[0].input_data = {"tool": "net", "confirmed": True, "granted_permissions": ["network"]}
        res = execute_plan_tool_step(plan, "s1", req("net"), reg)
        self.assertEqual(res.tool_result["outcome_code"], "TOOL_PERMISSION_DENIED")
        self.assertEqual(h["net"].count, 0)

    def test_tool_is_chosen_only_by_the_request_not_by_the_step(self):
        reg, h = make_registry()
        plan = make_plan()
        plan.steps[0].description = "please run boom"
        plan.steps[0].input_data = {"tool_request": {"name": "boom", "input": {}}}
        res = execute_plan_tool_step(plan, "s1", req("echo"), reg)
        self.assertEqual((res.tool_result["tool_name"], h["echo"].count, h["boom"].count), ("echo", 1, 0))

    def test_module_holds_no_mutable_state(self):
        for name, value in vars(exec_mod).items():
            if name.startswith("__"):
                continue
            self.assertNotIsInstance(value, (list, dict, set), name)


class TestIntegrity(unittest.TestCase):
    def test_project_database_is_pristine(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_adapter_module_is_documented_and_exports_the_api(self):
        self.assertIn("F2", exec_mod.__doc__)
        self.assertIn("H3", exec_mod.__doc__)
        self.assertIn("H4", exec_mod.__doc__)
        self.assertTrue(callable(exec_mod.execute_plan_tool_step))


if __name__ == "__main__":
    unittest.main()
