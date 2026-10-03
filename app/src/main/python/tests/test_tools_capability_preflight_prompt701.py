"""Prompt 701 - tool capability requirements and deterministic preflight. Pure in-memory."""
import ast
import hashlib
import os
import unittest

from tools import in_process_tool_registry as mod
from tools.in_process_tool_registry import (InProcessToolRegistry, ToolPreflightResult, ToolSpec, validate_tool_spec)

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
PREFLIGHT_KEYS = ["authorization_accepted", "authorization_decision", "confirmed", "failure_codes", "failures",
                  "granted_capabilities", "granted_permissions", "input_valid", "missing_capabilities", "ok",
                  "outcome_code", "preflight_status", "required_capabilities", "required_permissions", "tool_enabled",
                  "tool_exists", "tool_name"]


class Handler:
    def __init__(self):
        self.calls = []

    def __call__(self, tool_input):
        self.calls.append(tool_input)
        return {"echo": tool_input}


def make(name="cap_tool", permissions=None, capabilities=None, handler=None, enabled=True):
    return ToolSpec(name=name, description="d", handler=handler or Handler(), input_schema={"type": "object"},
                    output_description="o", enabled=enabled, permissions=permissions, capabilities=capabilities)


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


class TestCapabilityDeclaration(unittest.TestCase):
    def test_valid_requirements(self):
        for caps in (None, [], ["code_generation"], ("file_input", "code_analysis"), ["a", "b_2", "x" * 1]):
            self.assertEqual(validate_tool_spec(make(capabilities=caps)), [])
        self.assertEqual(ToolSpec().capabilities, [])
        reg = reg_with(make(capabilities=["file_input", "code_analysis"]))
        self.assertEqual(reg.get_required_capabilities("cap_tool"), ["code_analysis", "file_input"])
        self.assertIsNone(reg.get_required_capabilities("nope"))

    def test_invalid_names_rejected(self):
        for bad in ("code_generation", {"a"}, [1], [None], ["Bad"], ["has space"], [""], ["9x"], ["a-b"], ["x" * 65],
                    ["ok", "Bad"], [["nested"]]):
            self.assertEqual([f["code"] for f in validate_tool_spec(make(capabilities=bad))],
                             ["INVALID_TOOL_CAPABILITIES"], repr(bad))
        reg = InProcessToolRegistry()
        self.assertEqual(reg.register(make(capabilities=["Bad"])).codes(), ["INVALID_TOOL_CAPABILITIES"])
        self.assertEqual(len(reg), 0)

    def test_duplicates_rejected(self):
        self.assertEqual([f["code"] for f in validate_tool_spec(make(capabilities=["a", "b", "a"]))],
                         ["DUPLICATE_TOOL_CAPABILITY"])
        reg = InProcessToolRegistry()
        self.assertEqual(reg.register(make(capabilities=("x", "x"))).codes(), ["DUPLICATE_TOOL_CAPABILITY"])
        self.assertEqual(len(reg), 0)

    def test_failure_order_permissions_before_capabilities(self):
        s = make(permissions=["bogus"], capabilities=["Bad"])
        self.assertEqual([f["code"] for f in validate_tool_spec(s)], ["INVALID_TOOL_PERMISSIONS", "INVALID_TOOL_CAPABILITIES"])

    def test_registry_keeps_private_copy_and_describe_unchanged(self):
        spec = make(capabilities=["b_cap", "a_cap"])
        reg = reg_with(spec)
        spec.capabilities.append("c_cap")
        self.assertEqual(reg.get_required_capabilities("cap_tool"), ["a_cap", "b_cap"])
        out = reg.get_required_capabilities("cap_tool")
        out.append("z")
        self.assertEqual(reg.get_required_capabilities("cap_tool"), ["a_cap", "b_cap"])
        self.assertEqual(sorted(reg.describe("cap_tool")),
                         ["description", "enabled", "input_schema", "name", "output_description"])


class TestMissingAndAcceptedCapabilities(unittest.TestCase):
    def test_missing_capability_rejects_without_handler(self):
        h = Handler()
        reg = reg_with(make(capabilities=["a_cap", "b_cap"], handler=h))
        for grant in (None, [], ["a_cap"], ["other_cap"], ("b_cap",)):
            res = reg.execute("cap_tool", {"x": 1}, granted_capabilities=grant)
            self.assertEqual((res.execution_status, res.outcome_code, res.handler_called, res.authorization_accepted,
                              res.authorization_decision),
                             ("authorization_rejected", "TOOL_CAPABILITY_MISSING", False, False, "capability_missing"))
        self.assertEqual(h.calls, [])
        res = reg.invoke("cap_tool", {}, granted_capabilities=["a_cap"])
        self.assertEqual((res.codes(), res.handler_called, res.failures[0]["missing_capabilities"]),
                         (["TOOL_CAPABILITY_MISSING"], False, ["b_cap"]))
        rec = reg.get_invocation_history()[-1]
        self.assertEqual((rec["handler_called"], rec["authorization_decision"], rec["authorization_code"],
                          rec["outcome_code"], rec["required_capabilities"], rec["granted_capabilities"]),
                         (False, "capability_missing", "TOOL_CAPABILITY_MISSING", "TOOL_CAPABILITY_MISSING",
                          ["a_cap", "b_cap"], ["a_cap"]))
        self.assertEqual(h.calls, [])

    def test_accepted_capabilities(self):
        h = Handler()
        reg = reg_with(make(capabilities=["a_cap", "b_cap"], handler=h))
        for grant in (["a_cap", "b_cap"], ("b_cap", "a_cap", "a_cap"), {"a_cap", "b_cap", "extra_cap"}):
            res = reg.execute("cap_tool", {"x": 1}, granted_capabilities=grant)
            self.assertEqual((res.execution_status, res.authorization_decision, res.handler_called), (
                "succeeded", "accepted", True))
        self.assertEqual(len(h.calls), 3)
        rec = reg.get_invocation_history()[-1]
        self.assertEqual((rec["granted_capabilities"], rec["required_capabilities"]),
                         (["a_cap", "b_cap", "extra_cap"], ["a_cap", "b_cap"]))

    def test_no_capabilities_declared_is_backward_compatible(self):
        h = Handler()
        reg = reg_with(make(handler=h), make("perm_tool", permissions=["network"], handler=h))
        res = reg.execute("cap_tool", {})
        self.assertEqual((res.ok, res.authorization_decision), (True, "not_required"))
        self.assertTrue(reg.execute("perm_tool", {}, ["network"]).ok)
        self.assertEqual(reg.execute("perm_tool", {}).outcome_code, "TOOL_PERMISSION_DENIED")
        # extra capability grants for a tool that declares none are harmless
        self.assertTrue(reg.execute("cap_tool", {}, granted_capabilities=["anything_cap"]).ok)

    def test_capabilities_not_inferred_from_permissions_or_names(self):
        h = Handler()
        reg = reg_with(make("code_generation", permissions=["filesystem"], capabilities=["code_generation"], handler=h))
        res = reg.execute("code_generation", {}, granted_permissions=["filesystem"])
        self.assertEqual(res.outcome_code, "TOOL_CAPABILITY_MISSING")
        self.assertEqual(h.calls, [])

    def test_malformed_capability_grant_is_invalid_authorization(self):
        h = Handler()
        reg = reg_with(make(capabilities=["a_cap"], handler=h), make("plain", handler=h))
        for grant in ("a_cap", ["Bad"], [1], {"a_cap": True}, 5, [None]):
            for tool in ("cap_tool", "plain"):
                res = reg.execute(tool, {}, granted_capabilities=grant)
                self.assertEqual((res.outcome_code, res.handler_called, res.authorization_decision),
                                 ("INVALID_TOOL_AUTHORIZATION", False, "invalid"))
        self.assertEqual(h.calls, [])


class TestOrderAndPermissionGateIntact(unittest.TestCase):
    def setUp(self):
        self.h = Handler()
        self.reg = reg_with(make("full", permissions=["network", "user_confirmation"], capabilities=["a_cap"],
                                 handler=self.h), make("off", capabilities=["a_cap"], handler=self.h, enabled=False))

    def codes(self, *a, **k):
        return self.reg.preflight(*a, **k).outcome_code

    def test_deterministic_evaluation_order(self):
        r = self.reg
        self.assertEqual(self.codes("nope", "bad"), "UNKNOWN_TOOL")
        self.assertEqual(self.codes("off", "bad"), "TOOL_DISABLED")
        self.assertEqual(self.codes("full", "bad"), "TOOL_PERMISSION_DENIED")
        self.assertEqual(self.codes("full", "bad", ["network"]), "TOOL_CONFIRMATION_REQUIRED")
        self.assertEqual(self.codes("full", "bad", ["network"], True), "TOOL_CAPABILITY_MISSING")
        self.assertEqual(self.codes("full", "bad", ["network"], True, ["a_cap"]), "INVALID_TOOL_INPUT")
        self.assertEqual(self.codes("full", {"ok": 1}, ["network"], True, ["a_cap"]), "TOOL_PREFLIGHT_PASSED")
        self.assertEqual(r.invocation_count(), 0)
        self.assertEqual(self.h.calls, [])

    def test_existing_permission_and_confirmation_behavior_intact(self):
        res = self.reg.execute("full", {}, granted_capabilities=["a_cap"])
        self.assertEqual((res.outcome_code, res.authorization_decision), ("TOOL_PERMISSION_DENIED", "denied"))
        res = self.reg.execute("full", {}, ["network"], False, ["a_cap"])
        self.assertEqual((res.outcome_code, res.authorization_decision), ("TOOL_CONFIRMATION_REQUIRED",
                                                                          "confirmation_required"))
        res = self.reg.execute("full", {}, ["user_confirmation", "network"], False, ["a_cap"])
        self.assertEqual(res.outcome_code, "TOOL_CONFIRMATION_REQUIRED")     # naming it is not confirmation
        self.assertEqual(self.h.calls, [])
        res = self.reg.execute("full", {"a": 1}, ["network"], True, ["a_cap"])
        self.assertEqual((res.ok, res.handler_called, res.authorization_decision), (True, True, "accepted"))
        self.assertEqual(len(self.h.calls), 1)

    def test_invalid_input_rejected_after_accepted_authorization(self):
        res = self.reg.execute("full", "bad", ["network"], True, ["a_cap"])
        self.assertEqual((res.execution_status, res.authorization_accepted, res.handler_called),
                         ("input_rejected", True, False))
        self.assertEqual(self.h.calls, [])


class TestPreflight(unittest.TestCase):
    def test_result_fields_for_each_stage(self):
        h = Handler()
        reg = reg_with(make("full", permissions=["network"], capabilities=["b_cap", "a_cap"], handler=h),
                       make("off", handler=h, enabled=False))
        d = reg.preflight("nope", {}).to_dict()
        self.assertEqual((d["tool_name"], d["tool_exists"], d["tool_enabled"], d["input_valid"], d["preflight_status"],
                          d["failure_codes"], d["authorization_decision"]),
                         ("nope", False, False, None, "rejected", ["UNKNOWN_TOOL"], "not_evaluated"))
        d = reg.preflight("off", {}).to_dict()
        self.assertEqual((d["tool_exists"], d["tool_enabled"], d["failure_codes"]), (True, False, ["TOOL_DISABLED"]))
        d = reg.preflight("full", {"a": 1}, ["network"], granted_capabilities=["a_cap"]).to_dict()
        self.assertEqual((d["tool_exists"], d["tool_enabled"], d["authorization_decision"], d["authorization_accepted"],
                          d["required_capabilities"], d["granted_capabilities"], d["missing_capabilities"],
                          d["input_valid"], d["preflight_status"], d["outcome_code"], d["failure_codes"], d["ok"]),
                         (True, True, "capability_missing", False, ["a_cap", "b_cap"], ["a_cap"], ["b_cap"], None,
                          "rejected", "TOOL_CAPABILITY_MISSING", ["TOOL_CAPABILITY_MISSING"], False))
        d = reg.preflight("full", "bad", ["network"], granted_capabilities=["a_cap", "b_cap"]).to_dict()
        self.assertEqual((d["input_valid"], d["authorization_accepted"], d["failure_codes"]),
                         (False, True, ["INVALID_TOOL_INPUT"]))
        p = reg.preflight("full", {"a": 1}, ["network"], granted_capabilities=["a_cap", "b_cap"])
        self.assertIsInstance(p, ToolPreflightResult)
        d = p.to_dict()
        self.assertEqual((d["input_valid"], d["authorization_accepted"], d["missing_capabilities"], d["failure_codes"],
                          d["preflight_status"], d["outcome_code"], d["ok"]),
                         (True, True, [], [], "passed", "TOOL_PREFLIGHT_PASSED", True))
        self.assertEqual(h.calls, [])

    def test_never_calls_handler_or_records(self):
        h = Handler()
        reg = reg_with(make(permissions=["network"], capabilities=["a_cap"], handler=h))
        for _ in range(3):
            reg.preflight("cap_tool", {"a": 1}, ["network"], True, ["a_cap"])
            reg.preflight("cap_tool", {"a": 1})
            reg.preflight("nope", {})
        self.assertEqual((h.calls, reg.invocation_count(), reg.get_invocation_history()), ([], 0, []))

    def test_preflight_pass_does_not_run_or_authorize_a_later_call(self):
        h = Handler()
        reg = reg_with(make(capabilities=["a_cap"], handler=h))
        self.assertTrue(reg.preflight("cap_tool", {}, granted_capabilities=["a_cap"]).ok)
        res = reg.execute("cap_tool", {})
        self.assertEqual(res.outcome_code, "TOOL_CAPABILITY_MISSING")
        self.assertEqual(h.calls, [])

    def test_deterministic_and_isolated(self):
        def run():
            reg = reg_with(make(permissions=["network"], capabilities=["a_cap"]))
            return [reg.preflight("cap_tool", {"a": 1}, g, c, cap).to_dict()
                    for g, c, cap in ((None, False, None), (["network"], False, None), (["network"], False, ["a_cap"]))]
        a, b = run(), run()
        self.assertEqual(a, b)
        for d in a:
            self.assertEqual(sorted(d), PREFLIGHT_KEYS)
        reg = reg_with(make(capabilities=["a_cap"]))
        p = reg.preflight("cap_tool", {}, granted_capabilities=["a_cap"])
        first = p.to_dict()
        first["granted_capabilities"].append("x")
        p.granted_capabilities.append("y")
        p.failures.append("z")
        self.assertEqual(p.to_dict()["granted_capabilities"], ["a_cap", "y"])
        self.assertEqual(reg.preflight("cap_tool", {}, granted_capabilities=["a_cap"]).to_dict(), a_fresh(reg))

    def test_preflight_does_not_mutate_input_or_grants(self):
        reg = reg_with(make(capabilities=["a_cap"]))
        data, grant = {"list": [1]}, ["a_cap"]
        reg.preflight("cap_tool", data, granted_capabilities=grant)
        self.assertEqual((data, grant), ({"list": [1]}, ["a_cap"]))

    def test_no_handler_exposure(self):
        h = Handler()
        reg = reg_with(make(permissions=["network"], capabilities=["a_cap"], handler=h))
        for p in (reg.preflight("cap_tool", {}), reg.preflight("cap_tool", {}, ["network"], False, ["a_cap"]),
                  reg.preflight("nope", {})):
            self.assertFalse(contains_callable(p.to_dict()))
            self.assertNotIn("handler", p.__slots__)
            self.assertFalse(any(getattr(p, n) is h for n in p.__slots__))
            self.assertFalse(hasattr(p, "__dict__"))
        reg.execute("cap_tool", {}, ["network"], False, ["a_cap"])
        self.assertFalse(contains_callable(reg.get_invocation_history()))
        self.assertNotIn("handler", reg.describe("cap_tool"))


def a_fresh(reg):
    return reg.preflight("cap_tool", {}, granted_capabilities=["a_cap"]).to_dict()


class TestIsolationAndConsistency(unittest.TestCase):
    def test_capability_authorization_isolated_between_calls(self):
        h = Handler()
        reg = reg_with(make(capabilities=["a_cap"], handler=h))
        self.assertTrue(reg.execute("cap_tool", {}, granted_capabilities=["a_cap"]).ok)
        self.assertEqual(reg.execute("cap_tool", {}).outcome_code, "TOOL_CAPABILITY_MISSING")
        self.assertTrue(reg.execute("cap_tool", {}, granted_capabilities=("a_cap",)).ok)
        self.assertEqual(reg.execute("cap_tool", {}, granted_capabilities=[]).outcome_code, "TOOL_CAPABILITY_MISSING")
        self.assertEqual(len(h.calls), 2)
        self.assertEqual([r["authorization_decision"] for r in reg.get_invocation_history()],
                         ["accepted", "capability_missing", "accepted", "capability_missing"])

    def test_no_shared_or_persisted_capability_state(self):
        h = Handler()
        a = reg_with(make(capabilities=["a_cap"], handler=h))
        b = reg_with(make(capabilities=["a_cap"], handler=h))
        self.assertTrue(a.execute("cap_tool", {}, granted_capabilities=["a_cap"]).ok)
        self.assertEqual(b.execute("cap_tool", {}).outcome_code, "TOOL_CAPABILITY_MISSING")
        self.assertFalse([n for n in vars(a) if any(k in n for k in ("grant", "auth", "confirm", "cache"))])
        self.assertEqual(sorted(vars(a)), ["_entries", "_history"])
        self.assertFalse([n for n in vars(mod) if isinstance(getattr(mod, n), InProcessToolRegistry)])

    def test_caller_grant_object_not_retained(self):
        reg = reg_with(make(capabilities=["a_cap"]))
        grant = ["a_cap"]
        reg.invoke("cap_tool", {}, granted_capabilities=grant)
        grant.clear()
        rec = reg.get_invocation_history()[0]
        self.assertEqual(rec["granted_capabilities"], ["a_cap"])
        rec["granted_capabilities"].append("x")
        self.assertEqual(reg.get_invocation_history()[0]["granted_capabilities"], ["a_cap"])

    def test_execute_and_invoke_cannot_bypass_and_agree_with_preflight(self):
        scenarios = [("nope", {}, None, False, None), ("off", {}, None, False, None),
                     ("full", {}, None, False, None), ("full", {}, ["network"], False, None),
                     ("full", {}, ["network"], True, None), ("full", {}, ["network"], True, ["a_cap"]),
                     ("full", "bad", ["network"], True, ["a_cap"]), ("full", {}, "network", True, ["a_cap"]),
                     ("full", {}, ["network"], True, "a_cap"), ("plain", {}, None, False, None)]
        for name, data, perms, conf, caps in scenarios:
            h = Handler()
            reg = reg_with(make("full", permissions=["network", "user_confirmation"], capabilities=["a_cap"], handler=h),
                           make("off", capabilities=["a_cap"], handler=h, enabled=False), make("plain", handler=h))
            pre = reg.preflight(name, data, perms, conf, caps)
            self.assertEqual(h.calls, [], name)
            ex = reg.execute(name, data, perms, conf, caps)
            rec = reg.get_invocation_history()[0]
            self.assertEqual(ex.outcome_code == "TOOL_COMPLETED", pre.ok, (name, ex.outcome_code, pre.outcome_code))
            if not pre.ok:
                self.assertEqual(ex.outcome_code, pre.outcome_code)
                self.assertEqual([f["code"] for f in ex.failures], pre.failure_codes)
                self.assertEqual((len(h.calls), ex.handler_called, rec["handler_called"]), (0, False, False))
            else:
                self.assertEqual((len(h.calls), ex.handler_called), (1, True))
            self.assertEqual(rec["authorization_decision"], pre.authorization_decision)
            self.assertEqual(ex.authorization_accepted, pre.authorization_accepted)
            self.assertEqual(rec["required_capabilities"], pre.required_capabilities)
            self.assertEqual(rec["granted_capabilities"], pre.granted_capabilities)
            self.assertEqual(reg.invocation_count(), 1)

    def test_execution_result_and_record_agree_on_capability_rejection(self):
        reg = reg_with(make(capabilities=["a_cap"]))
        res = reg.execute("cap_tool", {})
        rec = reg.get_invocation_history()[0]
        self.assertEqual((res.outcome_code, res.authorization_decision, res.handler_called, res.ok, res.failures),
                         (rec["outcome_code"], rec["authorization_decision"], rec["handler_called"], rec["ok"],
                          rec["failures"]))

    def test_exactly_once_after_all_checks(self):
        h = Handler()
        reg = reg_with(make(capabilities=["a_cap"], handler=h))
        reg.execute("cap_tool", {"i": 1}, granted_capabilities=["a_cap"])
        self.assertEqual(h.calls, [{"i": 1}])


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
        for sub in ("core", "agent", "planning", "execution", "reasoning", "context", "understanding", "capabilities"):
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
