"""Prompt 698 - invocation record and audit trail for InProcessToolRegistry.invoke(). Pure in-memory."""
import ast
import hashlib
import os
import unittest

from tools import in_process_tool_registry as mod
from tools.in_process_tool_registry import InProcessToolRegistry, ToolSpec

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
RECORD_KEYS = ["authorization_code", "authorization_decision", "confirmed", "failures", "granted_capabilities",
               "granted_permissions", "handler_called", "input", "input_json_safe", "input_type", "ok", "outcome_code",
               "output", "output_available", "required_capabilities", "required_permissions", "sequence", "status",
               "tool_name"]


class Handler:
    def __init__(self, result=None, exc=None):
        self.calls, self.result, self.exc = [], result, exc

    def __call__(self, tool_input):
        self.calls.append(tool_input)
        if self.exc:
            raise self.exc
        return {"echo": tool_input} if self.result is None else self.result


def make(name="echo_tool", handler=None, enabled=True):
    return ToolSpec(name=name, description="d", handler=handler or Handler(), input_schema={"type": "object"},
                    output_description="o", enabled=enabled)


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


class TestSuccessRecord(unittest.TestCase):
    def test_successful_invocation_record(self):
        reg = reg_with(make())
        res = reg.invoke("echo_tool", {"text": "hi", "n": [1, 2]})
        self.assertTrue(res.ok)
        (rec,) = reg.get_invocation_history()
        self.assertEqual(sorted(rec), RECORD_KEYS)
        self.assertEqual(rec, {"sequence": 1, "tool_name": "echo_tool", "status": "completed", "ok": True,
                               "outcome_code": "TOOL_COMPLETED", "handler_called": True, "input_json_safe": True,
                               "input_type": "dict", "input": {"text": "hi", "n": [1, 2]},
                               "output_available": True, "output": {"echo": {"text": "hi", "n": [1, 2]}},
                               "failures": [], "authorization_decision": "not_required", "authorization_code": None,
                               "required_permissions": [], "granted_permissions": [], "confirmed": False,
                               "required_capabilities": [], "granted_capabilities": []})

    def test_null_output_is_distinguished_by_output_available(self):
        reg = reg_with(make(handler=lambda i: None))
        reg.invoke("echo_tool", {})
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["ok"], rec["output"], rec["output_available"]), (True, None, True))


class TestRejectedRecords(unittest.TestCase):
    def test_unknown_tool_records(self):
        h = Handler()
        reg = reg_with(make(handler=h))
        for bad in ("nope", "Echo_Tool", "", None, 5):
            reg.invoke(bad, {"a": 1})
        hist = reg.get_invocation_history()
        self.assertEqual(len(hist), 5)
        for rec, bad in zip(hist, ("nope", "Echo_Tool", "", None, 5)):
            self.assertEqual((rec["status"], rec["ok"], rec["outcome_code"], rec["handler_called"]),
                             ("rejected", False, "UNKNOWN_TOOL", False))
            self.assertEqual(rec["tool_name"], bad if isinstance(bad, str) else None)
            self.assertEqual((rec["input"], rec["output"], rec["output_available"]), ({"a": 1}, None, False))
        self.assertEqual(h.calls, [])

    def test_disabled_tool_record(self):
        h = Handler()
        reg = reg_with(make(handler=h, enabled=False))
        reg.invoke("echo_tool", {"x": 1})
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["status"], rec["outcome_code"], rec["handler_called"], rec["tool_name"]),
                         ("rejected", "TOOL_DISABLED", False, "echo_tool"))
        self.assertEqual(rec["failures"][0]["code"], "TOOL_DISABLED")
        self.assertEqual(h.calls, [])

    def test_invalid_input_records_use_safe_representation(self):
        h = Handler()
        reg = reg_with(make(handler=h))
        bads = [None, "text", [1], {1: 2}, {"a": object()}, {"a": float("inf")}]
        for bad in bads:
            reg.invoke("echo_tool", bad)
        for rec, bad in zip(reg.get_invocation_history(), bads):
            self.assertEqual((rec["status"], rec["outcome_code"], rec["handler_called"]),
                             ("rejected", "INVALID_TOOL_INPUT", False))
            self.assertEqual((rec["input_json_safe"], rec["input"], rec["input_type"]),
                             (False, None, type(bad).__name__))
        self.assertEqual(h.calls, [])

    def test_invalid_input_record_is_deterministic_even_for_objects(self):
        def run():
            reg = reg_with(make())
            reg.invoke("echo_tool", {"a": object()})
            return reg.get_invocation_history()
        self.assertEqual(run(), run())        # no memory addresses / reprs leak into records


class TestHandlerFailures(unittest.TestCase):
    def test_handler_exception_record(self):
        h = Handler(exc=ValueError("boom"))
        reg = reg_with(make(handler=h))
        res = reg.invoke("echo_tool", {"k": 1})
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["status"], rec["ok"], rec["outcome_code"], rec["handler_called"]),
                         ("failed", False, "TOOL_HANDLER_EXCEPTION", True))
        self.assertEqual((rec["failures"][0]["exception_type"], rec["failures"][0]["exception_message"]),
                         ("ValueError", "boom"))
        self.assertEqual((rec["input"], rec["output"], rec["output_available"]), ({"k": 1}, None, False))
        self.assertEqual(rec["failures"], res.failures)
        self.assertEqual(len(h.calls), 1)          # no retry, and the audit adds no second call
        self.assertEqual(reg.invocation_count(), 1)

    def test_invalid_output_record(self):
        reg = reg_with(make(handler=Handler(result={1: 2})))
        reg.invoke("echo_tool", {})
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["status"], rec["outcome_code"], rec["handler_called"], rec["output_available"],
                          rec["output"]), ("failed", "TOOL_OUTPUT_INVALID", True, False, None))

    def test_base_exception_propagates_unrecorded(self):
        reg = reg_with(make(handler=Handler(exc=KeyboardInterrupt())))
        with self.assertRaises(KeyboardInterrupt):
            reg.invoke("echo_tool", {})
        self.assertEqual(reg.get_invocation_history(), [])


class TestHandlerCalledCorrectness(unittest.TestCase):
    def test_handler_called_matches_actual_calls_for_every_outcome(self):
        good, bad, off = Handler(), Handler(exc=RuntimeError("x")), Handler()
        reg = reg_with(make("good", good), make("bad", bad), make("off", off, enabled=False))
        plan = [("good", {}), ("bad", {}), ("off", {}), ("missing", {}), ("good", "notdict"), ("good", {"a": 1})]
        before = [0, 0, 0]
        for name, inp in plan:
            counts = [len(good.calls), len(bad.calls), len(off.calls)]
            reg.invoke(name, inp)
            delta = sum(len(h.calls) for h in (good, bad, off)) - sum(counts)
            self.assertEqual(reg.get_invocation_history()[-1]["handler_called"], delta == 1)
        self.assertEqual([r["handler_called"] for r in reg.get_invocation_history()],
                         [True, True, False, False, False, True])
        self.assertEqual((len(good.calls), len(bad.calls), len(off.calls)), (2, 1, 0))


class TestOrdering(unittest.TestCase):
    def test_records_follow_invocation_order_with_sequence(self):
        reg = reg_with(make("b_tool"), make("a_tool", enabled=False))
        order = ["b_tool", "a_tool", "zzz", "b_tool", "a_tool"]
        for n in order:
            reg.invoke(n, {})
        hist = reg.get_invocation_history()
        self.assertEqual([r["tool_name"] for r in hist], order)
        self.assertEqual([r["sequence"] for r in hist], [1, 2, 3, 4, 5])
        self.assertEqual(reg.invocation_count(), 5)

    def test_registration_and_lookups_create_no_records(self):
        reg = reg_with(make())
        reg.has("echo_tool"), reg.describe("echo_tool"), reg.list_names(), reg.disable("echo_tool"), reg.enable("echo_tool")
        reg.register(make())                      # duplicate rejected
        self.assertEqual(reg.get_invocation_history(), [])

    def test_history_is_instance_local(self):
        a, b = reg_with(make()), reg_with(make())
        a.invoke("echo_tool", {})
        self.assertEqual((a.invocation_count(), b.invocation_count()), (1, 0))


class TestDefensiveCopiesAndReadOnly(unittest.TestCase):
    def test_mutating_returned_history_does_not_change_it(self):
        reg = reg_with(make())
        reg.invoke("echo_tool", {"n": [1]})
        snap = reg.get_invocation_history()
        snap[0]["input"]["n"].append(99)
        snap[0]["output"]["echo"]["n"].append(99)
        snap[0]["failures"].append({"code": "X"})
        snap[0]["outcome_code"] = "HACKED"
        snap.append({"fake": 1})
        self.assertEqual(reg.invocation_count(), 1)
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["input"], rec["outcome_code"], rec["failures"]), ({"n": [1]}, "TOOL_COMPLETED", []))
        self.assertEqual(rec["output"], {"echo": {"n": [1]}})

    def test_record_is_a_snapshot_of_caller_data(self):
        reg = reg_with(make(handler=lambda i: box))
        box, payload = {"o": [1]}, {"p": [1]}
        reg.invoke("echo_tool", payload)
        payload["p"].append(2)
        box["o"].append(2)
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["input"], rec["output"]), ({"p": [1]}, {"o": [1]}))

    def test_reading_does_not_mutate_or_invoke(self):
        h = Handler()
        reg = reg_with(make(handler=h))
        reg.invoke("echo_tool", {"a": 1})
        first = reg.get_invocation_history()
        for _ in range(3):
            self.assertEqual(reg.get_invocation_history(), first)
            reg.invocation_count()
        self.assertEqual((len(h.calls), reg.invocation_count()), (1, 1))


class TestDeterminismAndNoHandlerExposure(unittest.TestCase):
    def test_same_operations_give_identical_history(self):
        def run():
            reg = reg_with(make("a_tool"), make("b_tool", handler=Handler(exc=ValueError("e")), enabled=True),
                           make("c_tool", enabled=False))
            for n, i in (("a_tool", {"x": 1}), ("b_tool", {}), ("c_tool", {}), ("zz", {}), ("a_tool", 3)):
                reg.invoke(n, i)
            return reg.get_invocation_history()
        self.assertEqual(run(), run())

    def test_records_never_expose_the_handler(self):
        h = Handler()
        reg = reg_with(make(handler=h), make("bad_tool", handler=Handler(exc=ValueError("e"))),
                       make("off_tool", enabled=False))
        for n in ("echo_tool", "bad_tool", "off_tool", "nope"):
            reg.invoke(n, {})
        hist = reg.get_invocation_history()
        self.assertFalse(contains_callable(hist))
        self.assertTrue(all("handler" not in r or False for r in hist))     # no "handler" key itself
        self.assertEqual({k for r in hist for k in r if "handler" in k}, {"handler_called"})
        for r in reg._history:
            self.assertNotIn("handler", r.__slots__)
            self.assertEqual([x for x in r.__slots__ if "handler" in x], ["handler_called"])
            self.assertFalse(any(callable(getattr(r, s)) for s in r.__slots__))
        self.assertFalse(any(repr(h) in repr(r) for r in hist))


class TestBackwardsCompatibility(unittest.TestCase):
    def test_invoke_results_unchanged_by_auditing(self):
        reg = reg_with(make(), make("off_tool", enabled=False))
        ok = reg.invoke("echo_tool", {"a": 1})
        self.assertEqual((ok.status, ok.output, ok.handler_called), ("completed", {"echo": {"a": 1}}, True))
        self.assertEqual(reg.invoke("off_tool", {}).codes(), ["TOOL_DISABLED"])
        self.assertEqual(reg.invoke("nope", {}).codes(), ["UNKNOWN_TOOL"])
        self.assertEqual(reg.invoke("echo_tool", 5).codes(), ["INVALID_TOOL_INPUT"])
        self.assertEqual(sorted(reg.describe("echo_tool")), ["description", "enabled", "input_schema",
                                                             "name", "output_description"])

    def test_spec_validation_and_schema_semantics_untouched(self):
        self.assertEqual(mod.validate_tool_spec(make()), [])
        self.assertEqual(mod.validate_tool_spec(ToolSpec())[0]["code"], "INVALID_TOOL_NAME")
        reg = InProcessToolRegistry()
        self.assertEqual(reg.register(make(name="Bad")).codes(), ["INVALID_TOOL_NAME"])
        reg.register(make())
        self.assertEqual(reg.register(make()).codes(), ["DUPLICATE_TOOL_NAME"])


class TestBoundaries(unittest.TestCase):
    def test_imports_unchanged_and_not_wired_in(self):
        with open(os.path.join(PY_ROOT, "tools", "in_process_tool_registry.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertEqual(mods, {"copy", "math", "re", "tools"})  # Prompt 699: existing permission vocabulary
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
