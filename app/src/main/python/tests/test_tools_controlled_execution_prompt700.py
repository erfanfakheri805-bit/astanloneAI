"""Prompt 700 - controlled execution contract (InProcessToolRegistry.execute / ToolExecutionResult). Pure in-memory."""
import ast
import hashlib
import os
import unittest

from tools import in_process_tool_registry as mod
from tools.in_process_tool_registry import InProcessToolRegistry, ToolExecutionResult, ToolSpec

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
RESULT_KEYS = ["authorization_accepted", "authorization_decision", "execution_status", "failures", "handler_called",
               "ok", "outcome_code", "output", "output_available", "sequence", "tool_name"]


class Handler:
    def __init__(self, result=None, exc=None):
        self.calls, self.result, self.exc = [], result, exc

    def __call__(self, tool_input):
        self.calls.append(tool_input)
        if self.exc:
            raise self.exc
        return {"echo": tool_input} if self.result is None else self.result


def make(name="exec_tool", permissions=None, handler=None, enabled=True):
    return ToolSpec(name=name, description="d", handler=handler or Handler(), input_schema={"type": "object"},
                    output_description="o", enabled=enabled, permissions=permissions)


def reg_with(*specs):
    reg = InProcessToolRegistry()
    for s in specs:
        assert reg.register(s).ok
    return reg


def contains_callable(value):
    if callable(value):
        return True
    if isinstance(value, dict):
        return any(contains_callable(k) or contains_callable(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_callable(v) for v in value)
    return False


def assert_consistent(tc, res, rec):
    tc.assertEqual(res.tool_name, rec["tool_name"])
    tc.assertEqual(res.outcome_code, rec["outcome_code"])
    tc.assertEqual(res.authorization_decision, rec["authorization_decision"])
    tc.assertEqual(res.handler_called, rec["handler_called"])
    tc.assertEqual(res.ok, rec["ok"])
    tc.assertEqual(res.output_available, rec["output_available"])
    tc.assertEqual(res.output, rec["output"])
    tc.assertEqual(res.failures, rec["failures"])
    tc.assertEqual(res.sequence, rec["sequence"])


class TestRejectionBoundaries(unittest.TestCase):
    def setUp(self):
        self.h = Handler()
        self.reg = reg_with(make("gated", ["network", "user_confirmation"], self.h),
                            make("off", handler=self.h, enabled=False), make("open", handler=self.h))

    def check(self, res, status, code, auth_accepted, decision):
        self.assertIsInstance(res, ToolExecutionResult)
        self.assertEqual((res.execution_status, res.outcome_code, res.authorization_accepted,
                          res.authorization_decision, res.handler_called, res.ok, res.output_available, res.output),
                         (status, code, auth_accepted, decision, False, False, False, None))
        self.assertEqual([f["code"] for f in res.failures], [code])
        self.assertEqual(self.h.calls, [])
        assert_consistent(self, res, self.reg.get_invocation_history()[-1])

    def test_unknown_tool(self):
        for bad in ("nope", "Open", "", None, 5):
            self.check(self.reg.execute(bad, {}), "tool_rejected", "UNKNOWN_TOOL", False, "not_evaluated")

    def test_disabled_tool(self):
        self.check(self.reg.execute("off", {}, ["network"], True), "tool_rejected", "TOOL_DISABLED", False, "not_evaluated")

    def test_permission_missing(self):
        self.check(self.reg.execute("gated", {}), "authorization_rejected", "TOOL_PERMISSION_DENIED", False, "denied")
        self.check(self.reg.execute("gated", {}, confirmed=True), "authorization_rejected", "TOOL_PERMISSION_DENIED",
                   False, "denied")

    def test_confirmation_missing(self):
        self.check(self.reg.execute("gated", {}, ["network"]), "authorization_rejected", "TOOL_CONFIRMATION_REQUIRED",
                   False, "confirmation_required")

    def test_invalid_authorization_arguments(self):
        self.check(self.reg.execute("gated", {}, "network", True), "authorization_rejected", "INVALID_TOOL_AUTHORIZATION",
                   False, "invalid")
        self.check(self.reg.execute("open", {}, None, 1), "authorization_rejected", "INVALID_TOOL_AUTHORIZATION",
                   False, "invalid")

    def test_input_validation_failure_after_accepted_authorization(self):
        for bad in ("text", None, [1], {"k": object()}, {"k": float("nan")}, {1: "a"}):
            self.check(self.reg.execute("gated", bad, ["network"], True), "input_rejected", "INVALID_TOOL_INPUT", True,
                       "accepted")
            self.check(self.reg.execute("open", bad), "input_rejected", "INVALID_TOOL_INPUT", True, "not_required")

    def test_authorization_checked_before_input(self):
        self.check(self.reg.execute("gated", "bad"), "authorization_rejected", "TOOL_PERMISSION_DENIED", False, "denied")


class TestSuccessAndFailure(unittest.TestCase):
    def test_successful_execution(self):
        h = Handler()
        reg = reg_with(make(permissions=["network", "user_confirmation"], handler=h))
        res = reg.execute("exec_tool", {"a": [1, 2]}, granted_permissions=["network"], confirmed=True)
        self.assertEqual((res.execution_status, res.outcome_code, res.authorization_accepted, res.handler_called, res.ok,
                          res.output_available, res.output, res.failures, res.sequence),
                         ("succeeded", "TOOL_COMPLETED", True, True, True, True, {"echo": {"a": [1, 2]}}, [], 1))
        self.assertEqual(h.calls, [{"a": [1, 2]}])
        assert_consistent(self, res, reg.get_invocation_history()[0])

    def test_tool_without_permissions_succeeds_as_not_required(self):
        reg = reg_with(make())
        res = reg.execute("exec_tool", {})
        self.assertEqual((res.execution_status, res.authorization_accepted, res.authorization_decision),
                         ("succeeded", True, "not_required"))

    def test_null_output_is_distinguished_by_output_available(self):
        reg = reg_with(make(handler=lambda i: None))
        res = reg.execute("exec_tool", {})
        self.assertEqual((res.ok, res.output, res.output_available), (True, None, True))

    def test_handler_exception(self):
        h = Handler(exc=ValueError("boom"))
        reg = reg_with(make(permissions=["network"], handler=h))
        res = reg.execute("exec_tool", {"a": 1}, ["network"])
        self.assertEqual((res.execution_status, res.outcome_code, res.authorization_accepted, res.handler_called,
                          res.ok, res.output_available, res.output),
                         ("handler_failed", "TOOL_HANDLER_EXCEPTION", True, True, False, False, None))
        self.assertEqual(res.failures[0]["exception_type"], "ValueError")
        self.assertEqual(len(h.calls), 1)
        assert_consistent(self, res, reg.get_invocation_history()[0])

    def test_non_json_output_is_handler_failed(self):
        h = Handler(result={"bad": object()})
        reg = reg_with(make(handler=h))
        res = reg.execute("exec_tool", {})
        self.assertEqual((res.execution_status, res.outcome_code, res.handler_called, res.output), (
            "handler_failed", "TOOL_OUTPUT_INVALID", True, None))
        self.assertEqual(len(h.calls), 1)
        assert_consistent(self, res, reg.get_invocation_history()[0])

    def test_base_exception_still_propagates(self):
        reg = reg_with(make(handler=Handler(exc=KeyboardInterrupt())))
        with self.assertRaises(KeyboardInterrupt):
            reg.execute("exec_tool", {})


class TestExactlyOnce(unittest.TestCase):
    def test_one_handler_call_and_one_record_per_execute(self):
        h = Handler()
        reg = reg_with(make(permissions=["filesystem"], handler=h))
        for i in range(1, 4):
            self.assertTrue(reg.execute("exec_tool", {"i": i}, ["filesystem"]).ok)
            self.assertEqual((len(h.calls), reg.invocation_count()), (i, i))
        self.assertEqual([c["i"] for c in h.calls], [1, 2, 3])

    def test_failing_handler_is_not_retried(self):
        h = Handler(exc=RuntimeError("x"))
        reg = reg_with(make(handler=h))
        reg.execute("exec_tool", {})
        self.assertEqual((len(h.calls), reg.invocation_count()), (1, 1))

    def test_rejections_add_one_record_and_no_handler_call(self):
        h = Handler()
        reg = reg_with(make(permissions=["network"], handler=h))
        for _ in range(3):
            reg.execute("exec_tool", {})
        self.assertEqual((len(h.calls), reg.invocation_count()), (0, 3))

    def test_invoke_unchanged_and_still_returns_invocation_result(self):
        h = Handler()
        reg = reg_with(make(handler=h))
        res = reg.invoke("exec_tool", {"a": 1})
        self.assertNotIsInstance(res, ToolExecutionResult)
        self.assertEqual((res.ok, res.status, res.handler_called), (True, "completed", True))
        self.assertEqual(reg.invocation_count(), 1)


class TestIsolationAndStructure(unittest.TestCase):
    def test_input_is_defensively_copied(self):
        seen = []

        def handler(tool_input):
            seen.append(tool_input)
            tool_input["list"].append("mutated")
            return {"n": len(tool_input["list"])}
        reg = reg_with(make(handler=handler))
        data = {"list": [1]}
        res = reg.execute("exec_tool", data)
        self.assertEqual(data, {"list": [1]})
        self.assertEqual(res.output, {"n": 2})
        self.assertEqual(reg.get_invocation_history()[0]["input"], {"list": [1]})

    def test_output_isolation(self):
        shared = {"items": [1, 2]}
        reg = reg_with(make(handler=lambda i: shared))
        res = reg.execute("exec_tool", {})
        res.output["items"].append(99)
        d = res.to_dict()
        d["output"]["items"].append(100)
        d["failures"].append("x")
        shared["items"].append(7)
        self.assertEqual(res.to_dict()["output"], {"items": [1, 2, 99]})
        self.assertEqual(reg.get_invocation_history()[0]["output"], {"items": [1, 2]})
        again = reg.execute("exec_tool", {})
        self.assertEqual(again.output, {"items": [1, 2, 7]})

    def test_failures_isolated_from_audit_record(self):
        reg = reg_with(make(permissions=["network"]))
        res = reg.execute("exec_tool", {})
        res.failures[0]["code"] = "TAMPERED"
        self.assertEqual(reg.get_invocation_history()[0]["failures"][0]["code"], "TOOL_PERMISSION_DENIED")

    def test_result_structure_is_stable_and_deterministic(self):
        def run():
            h = Handler()
            reg = reg_with(make(permissions=["network", "user_confirmation"], handler=h),
                           make("bad", handler=Handler(exc=ValueError("v"))))
            out = [reg.execute("exec_tool", {"a": 1}).to_dict(),
                   reg.execute("exec_tool", {"a": 1}, ["network"]).to_dict(),
                   reg.execute("exec_tool", {"a": 1}, ["network"], True).to_dict(),
                   reg.execute("exec_tool", "bad", ["network"], True).to_dict(),
                   reg.execute("bad", {}).to_dict(), reg.execute("zzz", {}).to_dict()]
            return out, reg.get_invocation_history()
        (a, ha), (b, hb) = run(), run()
        self.assertEqual((a, ha), (b, hb))
        for d in a:
            self.assertEqual(sorted(d), RESULT_KEYS)
        self.assertEqual([d["execution_status"] for d in a], ["authorization_rejected", "authorization_rejected",
                                                              "succeeded", "input_rejected", "handler_failed",
                                                              "tool_rejected"])
        self.assertEqual([d["sequence"] for d in a], [1, 2, 3, 4, 5, 6])

    def test_status_matches_every_known_outcome_code(self):
        codes = {"TOOL_COMPLETED", "TOOL_HANDLER_EXCEPTION", "TOOL_OUTPUT_INVALID", "TOOL_PERMISSION_DENIED",
                 "TOOL_CONFIRMATION_REQUIRED", "INVALID_TOOL_AUTHORIZATION", "INVALID_TOOL_INPUT", "UNKNOWN_TOOL",
                 "TOOL_DISABLED",
                 "TOOL_CAPABILITY_MISSING", "TOOL_OUTPUT_VALIDATION_FAILED", "INVALID_TOOL_REQUEST"}   # Prompt 704: one new code
        self.assertEqual(set(mod._EXEC_STATUS_BY_CODE), codes)

    def test_no_handler_exposure(self):
        h = Handler()
        reg = reg_with(make(permissions=["network"], handler=h), make("bad", handler=Handler(exc=ValueError("v"))))
        results = [reg.execute("exec_tool", {}), reg.execute("exec_tool", {}, ["network"]), reg.execute("bad", {}),
                   reg.execute("zzz", {})]
        for res in results:
            self.assertFalse(contains_callable(res.to_dict()))
            self.assertNotIn("handler", res.__slots__)
            self.assertFalse(any(v is h for v in (getattr(res, n) for n in res.__slots__)))
            self.assertFalse(hasattr(res, "__dict__"))
        self.assertFalse(contains_callable(reg.get_invocation_history()))
        self.assertNotIn("handler", reg.describe("exec_tool"))


class TestBoundaries(unittest.TestCase):
    def test_imports_unchanged_and_not_wired_in(self):
        with open(os.path.join(PY_ROOT, "tools", "in_process_tool_registry.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add(node.module or "")
        self.assertEqual(mods, {"copy", "math", "re", "tools.tool_definition", "tools.tool_request"})  # Prompt 704: lazy import in execute_request()
        for sub in ("core", "agent", "planning", "execution", "reasoning", "context", "understanding"):
            for root, _d, files in os.walk(os.path.join(PY_ROOT, sub)):
                for f in files:
                    if f.endswith(".py") and f != "tool_step_bridge.py":      # Prompt 707: the one sanctioned, caller-driven consumer
                        with open(os.path.join(root, f), encoding="utf-8") as fh:
                            self.assertNotIn("in_process_tool_registry", fh.read(), f)

    def test_no_module_level_registry_state(self):
        self.assertFalse([n for n, v in vars(mod).items() if isinstance(v, InProcessToolRegistry)])

    def test_shipped_database_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
