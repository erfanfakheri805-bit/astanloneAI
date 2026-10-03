"""Prompt 699 - explicit caller-supplied permission/confirmation gate for InProcessToolRegistry.invoke(). Pure in-memory."""
import ast
import hashlib
import os
import unittest

from tools import in_process_tool_registry as mod
from tools.in_process_tool_registry import InProcessToolRegistry, ToolSpec, validate_tool_spec
from tools.tool_definition import SUPPORTED_PERMISSIONS

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


class Handler:
    def __init__(self):
        self.calls = []

    def __call__(self, tool_input):
        self.calls.append(tool_input)
        return {"echo": tool_input}


def make(name="gated_tool", permissions=None, handler=None):
    return ToolSpec(name=name, description="d", handler=handler or Handler(), input_schema={"type": "object"},
                    output_description="o", enabled=True, permissions=permissions)


def reg_with(*specs):
    reg = InProcessToolRegistry()
    for s in specs:
        assert reg.register(s).ok
    return reg


class TestSpecPermissions(unittest.TestCase):
    def test_reuses_existing_vocabulary_and_validates(self):
        self.assertEqual(validate_tool_spec(make(permissions=list(SUPPORTED_PERMISSIONS))), [])
        for bad in (["root"], "network", [1], ["network", None], {"network"}):
            self.assertEqual([f["code"] for f in validate_tool_spec(make(permissions=bad))], ["INVALID_TOOL_PERMISSIONS"])
        self.assertEqual(ToolSpec().permissions, [])
        reg = InProcessToolRegistry()
        self.assertEqual(reg.register(make(permissions=["bogus"])).codes(), ["INVALID_TOOL_PERMISSIONS"])
        self.assertEqual(len(reg), 0)

    def test_registry_keeps_sorted_deduped_copy(self):
        spec = make(permissions=["network", "filesystem", "network"])
        reg = reg_with(spec)
        spec.permissions.append("user_account")
        self.assertEqual(reg.get_required_permissions("gated_tool"), ["filesystem", "network"])
        self.assertIsNone(reg.get_required_permissions("nope"))


class TestDefaultDenial(unittest.TestCase):
    def test_default_denial_and_audit(self):
        h = Handler()
        reg = reg_with(make(permissions=["network"], handler=h))
        res = reg.invoke("gated_tool", {"a": 1})
        self.assertEqual((res.ok, res.status, res.handler_called, res.codes()), (False, "rejected", False,
                                                                                 ["TOOL_PERMISSION_DENIED"]))
        self.assertEqual(res.failures[0]["missing_permissions"], ["network"])
        self.assertEqual(h.calls, [])
        (rec,) = reg.get_invocation_history()
        self.assertEqual((rec["handler_called"], rec["authorization_decision"], rec["authorization_code"],
                          rec["outcome_code"], rec["required_permissions"], rec["granted_permissions"], rec["confirmed"]),
                         (False, "denied", "TOOL_PERMISSION_DENIED", "TOOL_PERMISSION_DENIED", ["network"], [], False))

    def test_partial_grant_still_denied(self):
        h = Handler()
        reg = reg_with(make(permissions=["network", "filesystem"], handler=h))
        res = reg.invoke("gated_tool", {}, granted_permissions=["network"])
        self.assertEqual(res.codes(), ["TOOL_PERMISSION_DENIED"])
        self.assertEqual(res.failures[0]["missing_permissions"], ["filesystem"])
        self.assertEqual(h.calls, [])

    def test_confirmed_true_alone_is_not_a_permission(self):
        h = Handler()
        reg = reg_with(make(permissions=["network"], handler=h))
        self.assertEqual(reg.invoke("gated_tool", {}, confirmed=True).codes(), ["TOOL_PERMISSION_DENIED"])
        self.assertEqual(h.calls, [])


class TestAcceptance(unittest.TestCase):
    def test_explicit_permission_acceptance(self):
        h = Handler()
        reg = reg_with(make(permissions=["network"], handler=h))
        res = reg.invoke("gated_tool", {"a": 1}, granted_permissions=["network", "network"])
        self.assertTrue(res.ok)
        self.assertEqual(h.calls, [{"a": 1}])
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["authorization_decision"], rec["authorization_code"], rec["outcome_code"],
                          rec["granted_permissions"], rec["handler_called"]),
                         ("accepted", None, "TOOL_COMPLETED", ["network"], True))

    def test_accepts_tuple_set_frozenset(self):
        h = Handler()
        reg = reg_with(make(permissions=["network"], handler=h))
        for grant in (("network",), {"network"}, frozenset({"network"})):
            self.assertTrue(reg.invoke("gated_tool", {}, granted_permissions=grant).ok)
        self.assertEqual(len(h.calls), 3)

    def test_tool_without_permissions_is_not_required(self):
        h = Handler()
        reg = reg_with(make(handler=h))
        self.assertTrue(reg.invoke("gated_tool", {}).ok)
        self.assertEqual(reg.get_invocation_history()[0]["authorization_decision"], "not_required")
        self.assertEqual(len(h.calls), 1)


class TestConfirmation(unittest.TestCase):
    def test_missing_confirmation(self):
        h = Handler()
        reg = reg_with(make(permissions=["user_confirmation"], handler=h))
        res = reg.invoke("gated_tool", {})
        self.assertEqual((res.status, res.handler_called, res.codes()), ("rejected", False,
                                                                        ["TOOL_CONFIRMATION_REQUIRED"]))
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["authorization_decision"], rec["authorization_code"], rec["handler_called"]),
                         ("confirmation_required", "TOOL_CONFIRMATION_REQUIRED", False))
        self.assertEqual(h.calls, [])

    def test_naming_user_confirmation_as_permission_is_not_confirmation(self):
        h = Handler()
        reg = reg_with(make(permissions=["user_confirmation"], handler=h))
        res = reg.invoke("gated_tool", {}, granted_permissions=["user_confirmation"])
        self.assertEqual(res.codes(), ["TOOL_CONFIRMATION_REQUIRED"])
        self.assertEqual(h.calls, [])

    def test_explicit_confirmation_acceptance(self):
        h = Handler()
        reg = reg_with(make(permissions=["user_confirmation"], handler=h))
        self.assertTrue(reg.invoke("gated_tool", {"x": 1}, confirmed=True).ok)
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["authorization_decision"], rec["confirmed"], rec["handler_called"]), ("accepted", True, True))
        self.assertEqual(h.calls, [{"x": 1}])

    def test_permission_denial_reported_before_confirmation(self):
        h = Handler()
        reg = reg_with(make(permissions=["network", "user_confirmation"], handler=h))
        self.assertEqual(reg.invoke("gated_tool", {}).codes(), ["TOOL_PERMISSION_DENIED"])
        self.assertEqual(reg.invoke("gated_tool", {}, granted_permissions=["network"]).codes(),
                         ["TOOL_CONFIRMATION_REQUIRED"])
        self.assertEqual(h.calls, [])
        self.assertTrue(reg.invoke("gated_tool", {}, granted_permissions=["network"], confirmed=True).ok)
        self.assertEqual(len(h.calls), 1)


class TestMalformedAuthorization(unittest.TestCase):
    def test_malformed_arguments_rejected_without_handler(self):
        h = Handler()
        reg = reg_with(make(permissions=["network"], handler=h), make(name="open_tool", handler=h))
        for grant, conf in (("network", False), (["bogus"], False), ([1], False), ({"network": True}, False),
                            (["network"], 1), (["network"], "yes"), (["network"], None)):
            for tool in ("gated_tool", "open_tool"):
                res = reg.invoke(tool, {}, granted_permissions=grant, confirmed=conf)
                self.assertEqual((res.codes(), res.handler_called), (["INVALID_TOOL_AUTHORIZATION"], False))
        self.assertEqual(h.calls, [])
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["authorization_decision"], rec["authorization_code"]),
                         ("invalid", "INVALID_TOOL_AUTHORIZATION"))

    def test_unknown_and_disabled_tools_not_evaluated(self):
        h = Handler()
        reg = reg_with(make(permissions=["network"], handler=h))
        reg.invoke("nope", {}, granted_permissions=["network"])
        reg.disable("gated_tool")
        reg.invoke("gated_tool", {}, granted_permissions=["network"], confirmed=True)
        recs = reg.get_invocation_history()
        self.assertEqual([r["authorization_decision"] for r in recs], ["not_evaluated", "not_evaluated"])
        self.assertEqual([r["outcome_code"] for r in recs], ["UNKNOWN_TOOL", "TOOL_DISABLED"])
        self.assertEqual(h.calls, [])

    def test_invalid_input_after_accepted_gate_records_decision(self):
        h = Handler()
        reg = reg_with(make(permissions=["network"], handler=h))
        res = reg.invoke("gated_tool", "not a dict", granted_permissions=["network"])
        self.assertEqual(res.codes(), ["INVALID_TOOL_INPUT"])
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["authorization_decision"], rec["handler_called"]), ("accepted", False))
        self.assertEqual(h.calls, [])


class TestIsolationAndDeterminism(unittest.TestCase):
    def test_authorization_is_per_invocation(self):
        h = Handler()
        reg = reg_with(make(permissions=["network", "user_confirmation"], handler=h))
        self.assertTrue(reg.invoke("gated_tool", {}, granted_permissions=["network"], confirmed=True).ok)
        # the next call supplies nothing: previous grant/confirmation must not carry over
        self.assertEqual(reg.invoke("gated_tool", {}).codes(), ["TOOL_PERMISSION_DENIED"])
        self.assertEqual(reg.invoke("gated_tool", {}, granted_permissions=["network"]).codes(),
                         ["TOOL_CONFIRMATION_REQUIRED"])
        self.assertEqual(len(h.calls), 1)
        self.assertEqual([r["authorization_decision"] for r in reg.get_invocation_history()],
                         ["accepted", "denied", "confirmation_required"])

    def test_no_authorization_state_or_sharing_between_registries(self):
        h = Handler()
        a = reg_with(make(permissions=["network"], handler=h))
        b = reg_with(make(permissions=["network"], handler=h))
        self.assertTrue(a.invoke("gated_tool", {}, granted_permissions=["network"]).ok)
        self.assertEqual(b.invoke("gated_tool", {}).codes(), ["TOOL_PERMISSION_DENIED"])
        self.assertFalse([n for n in vars(a) if "grant" in n or "auth" in n or "confirm" in n])
        self.assertFalse([n for n in vars(mod) if isinstance(getattr(mod, n), InProcessToolRegistry)])

    def test_caller_grant_object_not_retained_or_mutated(self):
        reg = reg_with(make(permissions=["network"]))
        grant = ["network"]
        reg.invoke("gated_tool", {}, granted_permissions=grant)
        grant.clear()
        rec = reg.get_invocation_history()[0]
        self.assertEqual(rec["granted_permissions"], ["network"])
        rec["granted_permissions"].append("x")
        self.assertEqual(reg.get_invocation_history()[0]["granted_permissions"], ["network"])

    def test_deterministic_repeated_behavior(self):
        def run():
            h = Handler()
            reg = reg_with(make(permissions=["filesystem", "user_confirmation"], handler=h))
            reg.invoke("gated_tool", {"a": 1})
            reg.invoke("gated_tool", {"a": 1}, granted_permissions={"filesystem"})
            reg.invoke("gated_tool", {"a": 1}, granted_permissions=("filesystem",), confirmed=True)
            reg.invoke("gated_tool", {"a": 1}, granted_permissions="filesystem")
            return reg.get_invocation_history(), h.calls
        self.assertEqual(run(), run())
        hist, calls = run()
        self.assertEqual([r["outcome_code"] for r in hist], ["TOOL_PERMISSION_DENIED", "TOOL_CONFIRMATION_REQUIRED",
                                                           "TOOL_COMPLETED", "INVALID_TOOL_AUTHORIZATION"])
        self.assertEqual([r["handler_called"] for r in hist], [False, False, True, False])
        self.assertEqual(len(calls), 1)


class TestBoundaries(unittest.TestCase):
    def test_imports_and_not_wired_in(self):
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

    def test_shipped_database_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
