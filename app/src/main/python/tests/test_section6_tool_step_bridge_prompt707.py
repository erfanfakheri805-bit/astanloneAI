"""Prompt 707 - Section 6 structured tool-step bridge (`planning/tool_step_bridge.py`).

Focused tests for the pure, caller-driven bridge `execute_tool_step(plan, step_id, request, registry) -> ToolStepBridgeResult`.
Nothing here wires the bridge into process_input(), the Agent Loop or the Planner. Docs: docs/section6_tool_step_bridge_prompt707.md
"""
import ast
import copy
import hashlib
import inspect
import json
import os
import unittest

from planning import tool_step_bridge as bridge_mod
from planning.plan import Plan, PlanStep, ensure_structured_data
from planning.plan_step_execution import complete_plan_step, fail_plan_step, start_plan_step
from planning.tool_step_bridge import (BRIDGE_FAILED, BRIDGE_INVALID_PLAN, BRIDGE_INVALID_REGISTRY, BRIDGE_INVALID_REQUEST,
                                       BRIDGE_INVALID_STEP_ID, BRIDGE_REJECTED, BRIDGE_SUCCEEDED, BRIDGE_UNKNOWN_STEP,
                                       ToolStepBridgeResult, execute_tool_step)
from tools.in_process_tool_registry import InProcessToolRegistry, ToolExecutionResult, ToolSpec
from tools.tool_request import ToolRequest, create_tool_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

RESULT_KEYS = {"ok", "status", "failure_source", "step_id", "tool_name", "execution_status", "outcome_code",
               "authorization_decision", "authorization_accepted", "handler_called", "output_available", "output",
               "failures", "sequence"}
BRIDGE_CODES = {BRIDGE_INVALID_PLAN, BRIDGE_INVALID_STEP_ID, BRIDGE_UNKNOWN_STEP, BRIDGE_INVALID_REQUEST,
                BRIDGE_INVALID_REGISTRY}


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
    reg, h = InProcessToolRegistry(), {}

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


def make_plan(*ids):
    steps = [PlanStep(i, "step " + i) for i in (ids or ("s1",))]
    return Plan("p", "g", steps=steps, created_at="1970-01-01T00:00:00+00:00",
                metadata={"phase": "planning", "executed": False, "execution_authorized": True})


def req(name, tool_input=None, perms=None, caps=None, confirmed=False):
    res = create_tool_request(name, {} if tool_input is None else tool_input, perms, caps, confirmed)
    assert res.ok, res.codes()
    return res.request


class TestSuccess(unittest.TestCase):
    def test_successful_execution_returns_bridge_success_with_output(self):
        reg, h = make_registry()
        res = execute_tool_step(make_plan(), "s1", req("echo", {"a": [1, 2]}), reg)
        self.assertIsInstance(res, ToolStepBridgeResult)
        self.assertTrue(res.ok)
        self.assertEqual((res.status, res.failure_source, res.step_id, res.tool_name), (BRIDGE_SUCCEEDED, None, "s1", "echo"))
        self.assertEqual((res.execution_status, res.outcome_code), ("succeeded", "TOOL_COMPLETED"))
        self.assertEqual((res.authorization_decision, res.authorization_accepted), ("not_required", True))
        self.assertEqual((res.handler_called, res.output_available, res.failures, res.sequence), (True, True, [], 1))
        self.assertEqual(res.output, {"echo": {"a": [1, 2]}})
        self.assertEqual(h["echo"].count, 1)

    def test_authorized_request_succeeds_using_only_its_own_grants(self):
        reg, h = make_registry()
        res = execute_tool_step(make_plan(), "s1", req("confirm", perms=["user_confirmation"], confirmed=True), reg)
        self.assertEqual((res.status, res.authorization_decision), (BRIDGE_SUCCEEDED, "accepted"))
        res = execute_tool_step(make_plan(), "s1", req("needs_cap", caps=["cap_a"]), reg)
        self.assertEqual(res.status, BRIDGE_SUCCEEDED)


class TestToolFailuresPreserveSection5Information(unittest.TestCase):
    def assert_failed_like_registry(self, request, expect_code, expect_exec, handler_called, name=None):
        """The bridge result must equal what the registry itself reported, field for field."""
        reg, _ = make_registry()
        res = execute_tool_step(make_plan(), "s1", request, reg)
        record = reg.get_invocation_history()[-1]
        self.assertFalse(res.ok)
        self.assertEqual((res.status, res.failure_source), (BRIDGE_FAILED, "tool"))
        self.assertEqual((res.outcome_code, res.execution_status, res.handler_called), (expect_code, expect_exec, handler_called))
        self.assertEqual(res.tool_name, name)
        self.assertEqual((res.output_available, res.output), (False, None))
        self.assertEqual(res.failures, record["failures"])
        self.assertEqual(res.authorization_decision, record["authorization_decision"])
        self.assertEqual((res.sequence, res.outcome_code, res.handler_called), (record["sequence"], record["outcome_code"],
                                                                                 record["handler_called"]))
        self.assertEqual(res.step_id, "s1")
        self.assertEqual(res.codes()[0], expect_code)
        return res, reg

    def test_unknown_tool(self):
        res, _ = self.assert_failed_like_registry(req("nope"), "UNKNOWN_TOOL", "tool_rejected", False, name="nope")
        self.assertEqual(res.authorization_decision, "not_evaluated")

    def test_disabled_tool(self):
        self.assert_failed_like_registry(req("off"), "TOOL_DISABLED", "tool_rejected", False, name="off")

    def test_permission_rejection(self):
        res, _ = self.assert_failed_like_registry(req("net"), "TOOL_PERMISSION_DENIED", "authorization_rejected", False,
                                                  name="net")
        self.assertEqual((res.authorization_decision, res.authorization_accepted), ("denied", False))
        self.assertEqual(res.failures[0]["missing_permissions"], ["network"])

    def test_confirmation_rejection(self):
        res, _ = self.assert_failed_like_registry(req("confirm", perms=["user_confirmation"]), "TOOL_CONFIRMATION_REQUIRED",
                                                  "authorization_rejected", False, name="confirm")
        self.assertEqual(res.authorization_decision, "confirmation_required")

    def test_naming_user_confirmation_as_a_grant_is_not_confirmation(self):
        self.assert_failed_like_registry(req("confirm", perms=["user_confirmation"], confirmed=False),
                                         "TOOL_CONFIRMATION_REQUIRED", "authorization_rejected", False, name="confirm")

    def test_capability_rejection(self):
        res, _ = self.assert_failed_like_registry(req("needs_cap"), "TOOL_CAPABILITY_MISSING", "authorization_rejected",
                                                  False, name="needs_cap")
        self.assertEqual((res.authorization_decision, res.failures[0]["missing_capabilities"]), ("capability_missing", ["cap_a"]))

    def test_handler_failure(self):
        res, reg = self.assert_failed_like_registry(req("boom"), "TOOL_HANDLER_EXCEPTION", "handler_failed", True, name="boom")
        self.assertEqual(res.failures[0]["exception_type"], "RuntimeError")

    def test_invalid_output_not_json_safe(self):
        self.assert_failed_like_registry(req("badout"), "TOOL_OUTPUT_INVALID", "handler_failed", True, name="badout")

    def test_invalid_output_type_mismatch(self):
        res, _ = self.assert_failed_like_registry(req("typed"), "TOOL_OUTPUT_VALIDATION_FAILED", "output_invalid", True,
                                                  name="typed")
        self.assertEqual((res.failures[0]["expected_type"], res.failures[0]["actual_type"]), ("string", "integer"))

    def test_forged_request_is_a_tool_failure_reported_by_the_registry(self):
        reg, h = make_registry()
        forged = ToolRequest.__new__(ToolRequest)
        res = execute_tool_step(make_plan(), "s1", forged, reg)
        self.assertEqual((res.status, res.outcome_code, res.execution_status, res.tool_name, res.sequence),
                         (BRIDGE_FAILED, "INVALID_TOOL_REQUEST", "tool_rejected", None, 1))
        self.assertEqual((res.handler_called, sum(x.count for x in h.values())), (False, 0))


class TestInvalidInput(unittest.TestCase):
    def test_invalid_tool_input_never_becomes_a_request(self):
        for bad in ([1], "x", None, {"k": float("nan")}, {1: 2}, {"t": (1, 2)}, {"s": {1}}):
            created = create_tool_request("echo", bad)
            self.assertFalse(created.ok, bad)
            self.assertIn("INVALID_TOOL_REQUEST_INPUT", created.codes())
            self.assertIsNone(created.request)

    def test_non_request_arguments_are_rejected_before_the_registry(self):
        for bad in (None, {}, "echo", {"name": "echo", "tool_input": {}}, req("echo").to_dict(), object(), 5):
            reg, h = make_registry()
            res = execute_tool_step(make_plan(), "s1", bad, reg)
            self.assertEqual((res.status, res.failure_source, res.outcome_code), (BRIDGE_REJECTED, "bridge", BRIDGE_INVALID_REQUEST))
            self.assertEqual((reg.invocation_count(), h["echo"].count), (0, 0))

    def test_toolrequest_cannot_be_built_directly(self):
        with self.assertRaises(TypeError):
            ToolRequest(object(), "echo", {}, (), (), False)


class TestBridgeRejection(unittest.TestCase):
    def test_each_invalid_bridge_argument_is_rejected_with_its_code(self):
        reg, h = make_registry()
        r = req("echo")
        cases = [((None, "s1", r, reg), BRIDGE_INVALID_PLAN), (("plan", "s1", r, reg), BRIDGE_INVALID_PLAN),
                 ((make_plan(), None, r, reg), BRIDGE_INVALID_STEP_ID), ((make_plan(), "", r, reg), BRIDGE_INVALID_STEP_ID),
                 ((make_plan(), "  ", r, reg), BRIDGE_INVALID_STEP_ID), ((make_plan(), 1, r, reg), BRIDGE_INVALID_STEP_ID),
                 ((make_plan(), "zzz", r, reg), BRIDGE_UNKNOWN_STEP), ((make_plan(), "s1", None, reg), BRIDGE_INVALID_REQUEST),
                 ((make_plan(), "s1", r, None), BRIDGE_INVALID_REGISTRY), ((make_plan(), "s1", r, object()), BRIDGE_INVALID_REGISTRY),
                 ((make_plan(), "s1", r, {"echo": h["echo"]}), BRIDGE_INVALID_REGISTRY)]
        for args, code in cases:
            res = execute_tool_step(*args)
            self.assertEqual((res.status, res.outcome_code, res.codes()[0]), (BRIDGE_REJECTED, code, code), args)
            self.assertIn(code, BRIDGE_CODES)
            self.assertEqual((res.handler_called, res.output_available, res.output, res.sequence, res.execution_status,
                              res.authorization_decision), (False, False, None, None, None, None))
        self.assertEqual((reg.invocation_count(), h["echo"].count), (0, 0))

    def test_all_problems_are_reported_at_once_in_argument_order(self):
        res = execute_tool_step("plan", 7, "req", "reg")
        self.assertEqual(res.codes(), [BRIDGE_INVALID_PLAN, BRIDGE_INVALID_STEP_ID, BRIDGE_INVALID_REQUEST, BRIDGE_INVALID_REGISTRY])
        self.assertEqual((res.step_id, res.tool_name), (None, None))

    def test_rejection_keeps_known_step_id_and_tool_name(self):
        res = execute_tool_step(make_plan(), "s1", req("echo"), None)
        self.assertEqual((res.step_id, res.tool_name, res.codes()), ("s1", "echo", [BRIDGE_INVALID_REGISTRY]))
        res = execute_tool_step(make_plan(), "nope", req("echo"), InProcessToolRegistry())
        self.assertEqual((res.step_id, res.tool_name, res.codes()), ("nope", "echo", [BRIDGE_UNKNOWN_STEP]))

    def test_no_handler_call_and_no_audit_record_on_bridge_rejection(self):
        reg, h = make_registry()
        execute_tool_step(make_plan(), "missing", req("echo"), reg)
        execute_tool_step(make_plan(), "s1", "not a request", reg)
        execute_tool_step(None, "s1", req("echo"), reg)
        self.assertEqual((reg.invocation_count(), reg.get_invocation_history(), h["echo"].count), (0, [], 0))

    def test_bridge_does_not_read_step_state(self):
        # Step state gating (pending/in_progress/...) belongs to Section 4; the bridge only locates the step.
        plan = make_plan("s1")
        for state in ("pending", "in_progress", "completed", "failed"):
            plan.steps[0].status = state
            reg, _ = make_registry()
            self.assertEqual(execute_tool_step(plan, "s1", req("echo"), reg).status, BRIDGE_SUCCEEDED, state)


class TestAuditSequence(unittest.TestCase):
    def test_sequence_matches_the_registry_audit_record(self):
        reg, _ = make_registry()
        plan = make_plan("s1", "s2", "s3")
        results = [execute_tool_step(plan, "s1", req("echo"), reg), execute_tool_step(plan, "s2", req("net"), reg),
                   execute_tool_step(plan, "s3", req("boom"), reg)]
        self.assertEqual([r.sequence for r in results], [1, 2, 3])
        hist = reg.get_invocation_history()
        self.assertEqual([h["sequence"] for h in hist], [1, 2, 3])
        self.assertEqual([(r.step_id, r.tool_name) for r in results], [("s1", "echo"), ("s2", "net"), ("s3", "boom")])
        self.assertEqual([h["tool_name"] for h in hist], [r.tool_name for r in results])
        self.assertEqual([h["outcome_code"] for h in hist], [r.outcome_code for r in results])

    def test_one_call_appends_exactly_one_record_and_bridge_rejections_append_none(self):
        reg, _ = make_registry()
        execute_tool_step(make_plan(), "s1", req("echo"), reg)
        self.assertEqual(reg.invocation_count(), 1)
        execute_tool_step(make_plan(), "bad", req("echo"), reg)
        self.assertEqual(reg.invocation_count(), 1)

    def test_no_retry_handler_runs_at_most_once_even_when_it_fails(self):
        reg, h = make_registry()
        execute_tool_step(make_plan(), "s1", req("boom"), reg)
        self.assertEqual((h["boom"].count, reg.invocation_count()), (1, 1))

    def test_only_execute_request_is_used_on_the_registry(self):
        calls = []

        class Spy(InProcessToolRegistry):
            def execute_request(self, request):
                calls.append("execute_request")
                return super().execute_request(request)

            def execute(self, *a, **k):
                calls.append("execute")
                return super().execute(*a, **k)

            def invoke(self, *a, **k):
                calls.append("invoke")
                return super().invoke(*a, **k)

            def preflight(self, *a, **k):
                calls.append("preflight")
                return super().preflight(*a, **k)

            def enable(self, *a, **k):
                calls.append("enable")

            def disable(self, *a, **k):
                calls.append("disable")

            def register(self, *a, **k):
                calls.append("register")

        spy = Spy()
        self.assertTrue(InProcessToolRegistry.register(spy, ToolSpec(name="echo", description="d", handler=lambda i: i,
                                                                   input_schema={}, output_description="o")).ok)
        execute_tool_step(make_plan(), "s1", req("echo", {"a": 1}), spy)
        # execute_request delegates to execute()/invoke() internally (Prompt 704); the bridge itself made exactly one call.
        self.assertEqual(calls[0], "execute_request")
        self.assertEqual(calls.count("execute_request"), 1)
        self.assertFalse({"preflight", "enable", "disable", "register"} & set(calls))


class TestImmutabilityAndNoSelection(unittest.TestCase):
    def test_request_is_not_modified_and_stays_the_same_object(self):
        reg, _ = make_registry()
        r = req("echo", {"a": [1, {"b": 2}]}, perms=["network"], caps=["cap_a"], confirmed=True)
        before, before_repr = r.to_dict(), repr(r)
        for _ in range(2):
            execute_tool_step(make_plan(), "s1", r, reg)
        self.assertEqual((r.to_dict(), repr(r)), (before, before_repr))
        with self.assertRaises(AttributeError):
            r.confirmed = False
        with self.assertRaises(AttributeError):
            r.name = "other"

    def test_plan_is_not_mutated(self):
        plan = make_plan("s1", "s2")
        before = copy.deepcopy(plan.to_dict())
        reg, _ = make_registry()
        for name in ("echo", "net", "boom", "nope"):
            execute_tool_step(plan, "s1", req(name), reg)
        execute_tool_step(plan, "zzz", req("echo"), reg)
        self.assertEqual(plan.to_dict(), before)

    def test_handler_input_mutation_cannot_reach_the_request(self):
        reg = InProcessToolRegistry()
        reg.register(ToolSpec(name="mut", description="d", handler=lambda i: i.setdefault("x", []).append(1) or i,
                              input_schema={}, output_description="o"))
        r = req("mut", {"k": 1})
        res = execute_tool_step(make_plan(), "s1", r, reg)
        self.assertEqual(res.output, {"k": 1, "x": [1]})
        self.assertEqual(r.input, {"k": 1})

    def test_step_data_never_selects_a_tool_or_grants_anything(self):
        reg, h = make_registry()
        step = PlanStep("s1", "use the net tool please", input_data={"tool_request": {"name": "net"}, "confirmed": True,
                                                                     "granted_permissions": ["network"], "authorized": True},
                        required_capabilities=["cap_a"], expected_output="net")
        plan = Plan("p", "g", steps=[step], created_at="1970-01-01T00:00:00+00:00",
                    metadata={"phase": "planning", "executed": False, "execution_authorized": True})
        res = execute_tool_step(plan, "s1", req("echo"), reg)
        self.assertEqual((res.tool_name, res.status), ("echo", BRIDGE_SUCCEEDED))
        self.assertEqual((h["net"].count, h["echo"].count), (0, 1))
        res = execute_tool_step(plan, "s1", req("net"), reg)         # request lacks the grant; step data does not supply it
        self.assertEqual((res.outcome_code, res.authorization_decision), ("TOOL_PERMISSION_DENIED", "denied"))
        self.assertEqual([x["granted_permissions"] for x in reg.get_invocation_history()], [[], []])

    def test_bridge_grants_and_confirms_nothing_on_its_own(self):
        reg, h = make_registry()
        for name in ("net", "confirm", "needs_cap"):
            execute_tool_step(make_plan(), "s1", req(name), reg)
        for rec in reg.get_invocation_history():
            self.assertEqual((rec["granted_permissions"], rec["granted_capabilities"], rec["confirmed"]), ([], [], False))
        self.assertEqual(sum(x.count for x in h.values()), 0)


class TestConfirmationBelongsToTheRequest(unittest.TestCase):
    def test_confirmation_cannot_leak_between_requests(self):
        reg, h = make_registry()
        confirmed = req("confirm", perms=["user_confirmation"], confirmed=True)
        unconfirmed = req("confirm", perms=["user_confirmation"], confirmed=False)
        plan = make_plan("s1", "s2", "s3")
        a = execute_tool_step(plan, "s1", confirmed, reg)
        b = execute_tool_step(plan, "s2", unconfirmed, reg)
        c = execute_tool_step(plan, "s3", confirmed, reg)
        self.assertEqual((a.status, b.status, c.status), (BRIDGE_SUCCEEDED, BRIDGE_FAILED, BRIDGE_SUCCEEDED))
        self.assertEqual(b.outcome_code, "TOOL_CONFIRMATION_REQUIRED")
        self.assertEqual([x["confirmed"] for x in reg.get_invocation_history()], [True, False, True])
        self.assertEqual(h["confirm"].count, 2)

    def test_confirmation_for_one_tool_does_not_authorize_another_request_or_tool(self):
        reg, h = make_registry()
        execute_tool_step(make_plan(), "s1", req("echo", confirmed=True), reg)
        res = execute_tool_step(make_plan(), "s1", req("confirm", perms=["user_confirmation"]), reg)
        self.assertEqual(res.outcome_code, "TOOL_CONFIRMATION_REQUIRED")
        res = execute_tool_step(make_plan(), "s1", req("net", confirmed=True), reg)     # confirmation is not a permission grant
        self.assertEqual(res.outcome_code, "TOOL_PERMISSION_DENIED")

    def test_bridge_signature_has_no_confirmation_grant_or_tool_parameters(self):
        params = list(inspect.signature(execute_tool_step).parameters)
        self.assertEqual(params, ["plan", "step_id", "request", "registry"])
        reg, _ = make_registry()
        for extra in ("confirmed", "granted_permissions", "granted_capabilities", "tool_name", "name", "tool_input"):
            with self.assertRaises(TypeError, msg=extra):
                execute_tool_step(make_plan(), "s1", req("confirm", perms=["user_confirmation"]), reg, **{extra: True})
        self.assertEqual(reg.invocation_count(), 0)

    def test_no_module_level_state_or_class_holds_confirmation(self):
        public = {n: v for n, v in vars(bridge_mod).items() if not n.startswith("__")}
        self.assertFalse([n for n, v in public.items() if isinstance(v, (InProcessToolRegistry, ToolRequest, dict, set))])
        classes = [v for v in public.values() if inspect.isclass(v) and v.__module__ == bridge_mod.__name__]
        self.assertEqual([c.__name__ for c in classes], ["ToolStepBridgeResult"])
        self.assertFalse([n for n in dir(ToolStepBridgeResult) if "confirm" in n.lower() or "grant" in n.lower()])


class TestResultContract(unittest.TestCase):
    def test_to_dict_has_fixed_keys_and_is_json_and_plan_safe(self):
        reg, _ = make_registry()
        for r in (req("echo", {"a": 1}), req("net"), req("boom"), req("typed"), req("nope")):
            d = execute_tool_step(make_plan(), "s1", r, reg).to_dict()
            self.assertEqual(set(d), RESULT_KEYS)
            self.assertEqual(json.loads(json.dumps(d)), d)
            self.assertEqual(ensure_structured_data(d), d)
        d = execute_tool_step(make_plan(), "zzz", req("echo"), reg).to_dict()
        self.assertEqual(set(d), RESULT_KEYS)
        self.assertEqual(json.loads(json.dumps(d)), d)

    def test_result_structure_is_deterministic(self):
        def run():
            reg, _ = make_registry()
            plan = make_plan("s1", "s2")
            return [execute_tool_step(plan, "s1", req("echo", {"z": 1, "a": [1]}), reg).to_dict(),
                    execute_tool_step(plan, "s2", req("confirm", perms=["user_confirmation"]), reg).to_dict(),
                    execute_tool_step(plan, "s2", req("boom"), reg).to_dict(),
                    execute_tool_step(plan, "x", req("echo"), reg).to_dict()]
        first, second = run(), run()
        self.assertEqual(first, second)
        self.assertEqual(json.dumps(first), json.dumps(second))
        self.assertEqual(list(first[0]), ["ok", "status", "failure_source", "step_id", "tool_name", "execution_status",
                                          "outcome_code", "authorization_decision", "authorization_accepted", "handler_called",
                                          "output_available", "output", "failures", "sequence"])

    def test_success_and_failure_field_values(self):
        reg, _ = make_registry()
        ok = execute_tool_step(make_plan(), "s1", req("echo", {"a": 1}), reg).to_dict()
        self.assertEqual((ok["ok"], ok["status"], ok["failure_source"], ok["failures"]), (True, "succeeded", None, []))
        bad = execute_tool_step(make_plan(), "s1", req("net"), reg).to_dict()
        self.assertEqual((bad["ok"], bad["status"], bad["failure_source"]), (False, "failed", "tool"))
        rej = execute_tool_step(make_plan(), "zzz", req("net"), reg).to_dict()
        self.assertEqual((rej["ok"], rej["status"], rej["failure_source"], rej["tool_name"]), (False, "rejected", "bridge", "net"))

    def test_result_matches_registry_execution_result_fields(self):
        reg1, _ = make_registry()
        reg2, _ = make_registry()
        direct = reg1.execute_request(req("typed")).to_dict()
        bridged = execute_tool_step(make_plan(), "s1", req("typed"), reg2).to_dict()
        for key in set(direct) & set(bridged):
            self.assertEqual(direct[key], bridged[key], key)
        self.assertEqual(set(bridged) - set(direct), {"status", "failure_source", "step_id"})

    def test_result_is_immutable_and_cannot_be_built_directly(self):
        reg, _ = make_registry()
        res = execute_tool_step(make_plan(), "s1", req("echo"), reg)
        for attr, value in (("status", "x"), ("output", {}), ("_output", {}), ("new", 1), ("sequence", 9)):
            with self.assertRaises(AttributeError):
                setattr(res, attr, value)
        with self.assertRaises(AttributeError):
            del res.status
        self.assertFalse(hasattr(res, "__dict__"))
        with self.assertRaises(TypeError):
            ToolStepBridgeResult(object(), "succeeded", "s1", "echo", None, None, None, None, None, None, None, [], 1)
        with self.assertRaises(TypeError):
            class Sub(ToolStepBridgeResult):
                pass
        with self.assertRaises(TypeError):
            import pickle
            pickle.dumps(res)
        self.assertIs(copy.deepcopy(res), res)
        self.assertEqual(res, execute_tool_step(make_plan(), "s1", req("echo"), make_registry()[0]))

    def test_result_does_not_expose_mutable_registry_internals(self):
        reg, h = make_registry()
        res = execute_tool_step(make_plan(), "s1", req("echo", {"a": [1]}), reg)
        hist_before = reg.get_invocation_history()
        res.output["echo"]["a"].append(99)                 # property returns a fresh copy each time
        res.to_dict()["output"]["echo"]["a"].append(99)
        res.failures.append({"code": "X"})
        res.to_dict()["failures"].append({"code": "X"})
        self.assertEqual(res.output, {"echo": {"a": [1]}})
        self.assertEqual((res.failures, res.to_dict()["failures"]), ([], []))
        self.assertEqual(reg.get_invocation_history(), hist_before)
        self.assertIsNot(res.output, res.output)
        # the handler's own input/output objects are not reachable from the result
        self.assertIsNot(res.output["echo"], h["echo"].calls[0])
        exposed = [v for v in (getattr(res, s) for s in ToolStepBridgeResult.__slots__)]
        self.assertFalse([v for v in exposed if isinstance(v, (InProcessToolRegistry, ToolRequest, ToolExecutionResult, Counting))
                          or callable(v)])
        self.assertEqual([k for k in res.to_dict() if "handler" in k], ["handler_called"])

    def test_failure_details_are_copies_of_the_audit_record(self):
        reg, _ = make_registry()
        res = execute_tool_step(make_plan(), "s1", req("net"), reg)
        res.failures[0]["missing_permissions"].append("filesystem")
        self.assertEqual(reg.get_invocation_history()[0]["failures"][0]["missing_permissions"], ["network"])


class TestFutureExecutorMapping(unittest.TestCase):
    """Uses only public Section 4 transitions to show that a future executor loses nothing (no wiring is added)."""

    def test_tool_failure_maps_to_a_failed_step_keeping_all_section5_information(self):
        reg, _ = make_registry()
        plan = make_plan("s1")
        self.assertTrue(start_plan_step(plan, "s1").ok)
        res = execute_tool_step(plan, "s1", req("net"), reg)
        self.assertFalse(res.ok)
        self.assertTrue(fail_plan_step(plan, "s1", res.to_dict()).ok)
        stored = plan.steps[0]
        self.assertEqual(stored.status, "failed")
        self.assertEqual(stored.output_data, res.to_dict())
        self.assertEqual(stored.output_data["outcome_code"], "TOOL_PERMISSION_DENIED")
        self.assertEqual((stored.output_data["sequence"], stored.output_data["authorization_decision"]), (1, "denied"))
        self.assertEqual(stored.output_data["failures"], reg.get_invocation_history()[0]["failures"])

    def test_bridge_rejection_and_success_also_map_cleanly(self):
        reg, _ = make_registry()
        plan = make_plan("s1", "s2")
        self.assertTrue(start_plan_step(plan, "s1").ok)
        ok = execute_tool_step(plan, "s1", req("echo", {"v": 1}), reg)
        self.assertTrue(complete_plan_step(plan, "s1", ok.to_dict()).ok)
        self.assertEqual(plan.steps[0].output_data["output"], {"echo": {"v": 1}})
        self.assertTrue(start_plan_step(plan, "s2").ok)
        rej = execute_tool_step(plan, "s2", None, reg)
        self.assertTrue(fail_plan_step(plan, "s2", rej.to_dict()).ok)
        self.assertEqual((plan.steps[1].status, plan.steps[1].output_data["outcome_code"]), ("failed", BRIDGE_INVALID_REQUEST))


class TestIsolationAndIntegrity(unittest.TestCase):
    BANNED = {"socket", "http", "urllib", "requests", "subprocess", "threading", "multiprocessing", "asyncio", "sched", "sqlite3",
              "pickle", "shelve", "json", "os", "sys", "shutil", "tempfile", "time", "random", "importlib", "datetime", "logging"}

    def imports(self, path):
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add(node.module or "")
        return mods

    def production_files(self):
        for root, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for f in files:
                if f.endswith(".py"):
                    yield os.path.join(root, f)

    def test_bridge_imports_are_minimal_and_pure(self):
        mods = self.imports(bridge_mod.__file__)
        self.assertEqual(mods, {"copy", "planning.plan", "tools.in_process_tool_registry", "tools.tool_request"})
        self.assertFalse({m.split(".")[0] for m in mods} & self.BANNED)

    def test_bridge_is_the_only_planning_module_importing_tools(self):
        offenders = sorted(os.path.relpath(p, PY_ROOT).replace(os.sep, "/") for p in self.production_files()
                           if os.path.relpath(p, PY_ROOT).startswith("planning")
                           and any(m == "tools" or m.startswith("tools.") for m in self.imports(p)))
        self.assertEqual(offenders, ["planning/tool_step_bridge.py"])

    def test_bridge_is_not_wired_into_any_production_module(self):
        # Prompt 708 adds exactly ONE sanctioned importer: the caller-driven adapter planning/tool_step_executor.py.
        offenders = [os.path.relpath(p, PY_ROOT) for p in self.production_files()
                     if "planning.tool_step_bridge" in self.imports(p)]
        self.assertEqual(offenders, [os.path.join("planning", "tool_step_executor.py")])
        for path in self.production_files():
            if path.endswith(os.path.join("planning", "tool_step_bridge.py")) or \
                    path.endswith(os.path.join("planning", "tool_step_executor.py")):
                continue
            with open(path, encoding="utf-8") as fh:
                self.assertNotIn("tool_step_bridge", fh.read(), path)

    def test_tools_package_does_not_import_planning(self):
        for path in self.production_files():
            if os.path.relpath(path, PY_ROOT).startswith("tools" + os.sep):
                self.assertFalse({m for m in self.imports(path) if m.split(".")[0] in ("planning", "agent", "execution")}, path)

    def test_no_background_work_or_module_state(self):
        import threading
        before = threading.active_count()
        reg, _ = make_registry()
        execute_tool_step(make_plan(), "s1", req("echo"), reg)
        self.assertEqual(threading.active_count(), before)
        src = inspect.getsource(bridge_mod)
        for word in ("import socket", "import threading", "import sqlite3", "open(", "global "):
            self.assertNotIn(word, src)

    def test_database_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
