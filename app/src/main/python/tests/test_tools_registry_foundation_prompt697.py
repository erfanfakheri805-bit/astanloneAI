"""Prompt 697 - in-process Tool Registry and tool metadata contract (Section 5 foundation). Pure in-memory."""
import ast
import copy
import hashlib
import os
import unittest

from tools import in_process_tool_registry as mod
from tools.in_process_tool_registry import InProcessToolRegistry, ToolSpec, validate_tool_spec

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


class Handler:
    def __init__(self, result=None, exc=None):
        self.calls, self.result, self.exc = [], result, exc

    def __call__(self, tool_input):
        self.calls.append(tool_input)
        if self.exc:
            raise self.exc
        return {"echo": tool_input} if self.result is None else self.result


def spec(name="echo_tool", handler=None, **kw):
    args = dict(name=name, description="Echoes its input.", handler=handler or Handler(),
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
                output_description="The input, echoed.", enabled=True)
    args.update(kw)
    return ToolSpec(**args)


class TestRegistration(unittest.TestCase):
    def test_valid_registration(self):
        reg = InProcessToolRegistry()
        res = reg.register(spec())
        self.assertTrue(res.ok)
        self.assertEqual((res.status, res.name, res.failures), ("registered", "echo_tool", []))
        self.assertEqual((len(reg), reg.has("echo_tool")), (1, True))
        self.assertEqual(res.to_dict()["ok"], True)

    def test_metadata_contract_fields(self):
        reg = InProcessToolRegistry()
        reg.register(spec())
        d = reg.describe("echo_tool")
        self.assertEqual(sorted(d), ["description", "enabled", "input_schema", "name", "output_description"])
        self.assertNotIn("handler", d)
        self.assertEqual(d["input_schema"]["type"], "object")

    def test_duplicate_rejected_and_first_kept(self):
        reg, first, second = InProcessToolRegistry(), Handler(), Handler()
        self.assertTrue(reg.register(spec(handler=first, description="first")).ok)
        for _ in range(2):
            res = reg.register(spec(handler=second, description="second"))
            self.assertFalse(res.ok)
            self.assertEqual(res.codes(), ["DUPLICATE_TOOL_NAME"])
        self.assertEqual(len(reg), 1)
        self.assertEqual(reg.describe("echo_tool")["description"], "first")
        reg.invoke("echo_tool", {})
        self.assertEqual((len(first.calls), len(second.calls)), (1, 0))

    def test_case_variants_are_not_duplicates_and_are_invalid(self):
        reg = InProcessToolRegistry()
        self.assertTrue(reg.register(spec("abc")).ok)
        self.assertEqual(reg.register(spec("ABC")).codes(), ["INVALID_TOOL_NAME"])

    def test_registry_keeps_private_copy(self):
        reg, s = InProcessToolRegistry(), spec()
        reg.register(s)
        s.enabled, s.description = False, "changed"
        s.input_schema["type"] = "changed"
        d = reg.describe("echo_tool")
        self.assertEqual((d["enabled"], d["description"], d["input_schema"]["type"]), (True, "Echoes its input.", "object"))
        d["input_schema"]["type"] = "tampered"
        self.assertEqual(reg.describe("echo_tool")["input_schema"]["type"], "object")

    def test_instances_are_independent(self):
        a, b = InProcessToolRegistry(), InProcessToolRegistry()
        a.register(spec())
        self.assertFalse(b.has("echo_tool"))
        self.assertTrue(b.register(spec()).ok)


class TestInvalidMetadata(unittest.TestCase):
    def test_each_field_rejected_with_stable_code(self):
        cases = [
            (dict(name=None), "INVALID_TOOL_NAME"), (dict(name=""), "INVALID_TOOL_NAME"),
            (dict(name=" echo"), "INVALID_TOOL_NAME"), (dict(name="1abc"), "INVALID_TOOL_NAME"),
            (dict(name="a-b"), "INVALID_TOOL_NAME"), (dict(name="a" * 65), "INVALID_TOOL_NAME"),
            (dict(name=5), "INVALID_TOOL_NAME"),
            (dict(description=""), "INVALID_TOOL_DESCRIPTION"), (dict(description="  "), "INVALID_TOOL_DESCRIPTION"),
            (dict(description=None), "INVALID_TOOL_DESCRIPTION"),
            (dict(handler="not callable"), "INVALID_TOOL_HANDLER"),
            (dict(input_schema=[1]), "INVALID_TOOL_INPUT_SCHEMA"),
            (dict(input_schema={"a": object()}), "INVALID_TOOL_INPUT_SCHEMA"),
            (dict(input_schema={1: "x"}), "INVALID_TOOL_INPUT_SCHEMA"),
            (dict(input_schema={"a": float("nan")}), "INVALID_TOOL_INPUT_SCHEMA"),
            (dict(output_description=""), "INVALID_TOOL_OUTPUT_DESCRIPTION"),
            (dict(output_description=3), "INVALID_TOOL_OUTPUT_DESCRIPTION"),
            (dict(enabled=1), "INVALID_TOOL_ENABLED"), (dict(enabled="yes"), "INVALID_TOOL_ENABLED"),
            (dict(enabled=None), "INVALID_TOOL_ENABLED"),
        ]
        for kw, code in cases:
            reg = InProcessToolRegistry()
            s = spec(**kw)
            self.assertEqual(validate_tool_spec(s)[0]["code"], code, kw)
            res = reg.register(s)
            self.assertEqual((res.ok, res.codes()), (False, [code]), kw)
            self.assertEqual(len(reg), 0)

    def test_non_spec_rejected(self):
        reg = InProcessToolRegistry()
        for bad in (None, {}, "tool", 5, object()):
            self.assertEqual(reg.register(bad).codes(), ["INVALID_TOOL_SPEC"])
        self.assertEqual(len(reg), 0)

    def test_multiple_problems_reported_in_field_order(self):
        s = ToolSpec(name="Bad Name", description="", handler=None, input_schema=[], output_description="", enabled=1)
        self.assertEqual([f["code"] for f in validate_tool_spec(s)],
                         ["INVALID_TOOL_NAME", "INVALID_TOOL_DESCRIPTION", "INVALID_TOOL_HANDLER",
                          "INVALID_TOOL_INPUT_SCHEMA", "INVALID_TOOL_OUTPUT_DESCRIPTION", "INVALID_TOOL_ENABLED"])

    def test_default_schema_is_empty_dict_and_construction_never_raises(self):
        self.assertEqual(ToolSpec().input_schema, {})
        self.assertTrue(validate_tool_spec(ToolSpec()))
        self.assertEqual(validate_tool_spec(spec(input_schema=None)), [])


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.reg = InProcessToolRegistry()
        for n in ("zeta", "alpha", "mid_tool"):
            self.reg.register(spec(n))

    def test_exact_lookup_only(self):
        for ok in ("alpha", "zeta", "mid_tool"):
            self.assertTrue(self.reg.has(ok))
        for bad in ("Alpha", "alpha ", " alpha", "alph", "alpha_", "", None, 5, ["alpha"], b"alpha"):
            self.assertFalse(self.reg.has(bad), bad)
            self.assertIsNone(self.reg.describe(bad))
            self.assertFalse(self.reg.is_invokable(bad))

    def test_listing_is_sorted_and_deterministic(self):
        self.assertEqual(self.reg.list_names(), ["alpha", "mid_tool", "zeta"])
        self.assertEqual(self.reg.list_descriptions(), self.reg.list_descriptions())
        other = InProcessToolRegistry()
        for n in ("mid_tool", "zeta", "alpha"):
            other.register(spec(n))
        self.assertEqual(other.list_descriptions(), self.reg.list_descriptions())

    def test_lookup_is_read_only(self):
        before = self.reg.list_descriptions()
        h = self.reg._entries["alpha"]["handler"]
        self.reg.has("alpha"), self.reg.describe("alpha"), self.reg.list_names(), self.reg.is_invokable("alpha")
        self.assertEqual((self.reg.list_descriptions(), h.calls), (before, []))


class TestDisabledAndUnknown(unittest.TestCase):
    def test_disabled_at_registration_is_not_invokable(self):
        reg, h = InProcessToolRegistry(), Handler()
        reg.register(spec(handler=h, enabled=False))
        self.assertFalse(reg.is_invokable("echo_tool"))
        res = reg.invoke("echo_tool", {})
        self.assertEqual((res.status, res.codes(), res.handler_called), ("rejected", ["TOOL_DISABLED"], False))
        self.assertEqual(h.calls, [])

    def test_disable_and_enable_are_explicit(self):
        reg, h = InProcessToolRegistry(), Handler()
        reg.register(spec(handler=h))
        self.assertTrue(reg.invoke("echo_tool", {}).ok)
        self.assertTrue(reg.disable("echo_tool"))
        self.assertEqual(reg.invoke("echo_tool", {}).codes(), ["TOOL_DISABLED"])
        self.assertFalse(reg.describe("echo_tool")["enabled"])
        self.assertTrue(reg.enable("echo_tool"))
        self.assertTrue(reg.invoke("echo_tool", {}).ok)
        self.assertEqual(len(h.calls), 2)

    def test_unknown_names_cannot_be_invoked_or_toggled(self):
        reg, h = InProcessToolRegistry(), Handler()
        reg.register(spec(handler=h))
        for bad in ("nope", "Echo_Tool", "", None, 3):
            res = reg.invoke(bad, {})
            self.assertEqual((res.status, res.codes(), res.handler_called), ("rejected", ["UNKNOWN_TOOL"], False))
            self.assertFalse(reg.enable(bad))
            self.assertFalse(reg.disable(bad))
        self.assertEqual(h.calls, [])
        self.assertEqual(len(reg), 1)


class TestInvocation(unittest.TestCase):
    def test_single_explicit_call_with_copied_input_and_output(self):
        reg, box = InProcessToolRegistry(), {"k": [1]}
        h = Handler(result=box)
        reg.register(spec(handler=h))
        payload = {"text": "hi", "n": [1, 2]}
        res = reg.invoke("echo_tool", payload)
        self.assertEqual((res.ok, res.status, res.handler_called, res.failures), (True, "completed", True, []))
        self.assertEqual(len(h.calls), 1)
        self.assertIsNot(h.calls[0], payload)
        h.calls[0]["n"].append(9)
        self.assertEqual(payload, {"text": "hi", "n": [1, 2]})
        box["k"].append(2)
        self.assertEqual(res.output, {"k": [1]})

    def test_bad_input_rejected_before_handler(self):
        reg, h = InProcessToolRegistry(), Handler()
        reg.register(spec(handler=h))
        for bad in (None, "text", [1], {1: 2}, {"a": object()}, {"a": float("inf")}):
            res = reg.invoke("echo_tool", bad)
            self.assertEqual((res.status, res.codes(), res.handler_called), ("rejected", ["INVALID_TOOL_INPUT"], False))
        self.assertEqual(h.calls, [])

    def test_handler_exception_reported_not_raised_and_not_retried(self):
        reg, h = InProcessToolRegistry(), Handler(exc=ValueError("boom"))
        reg.register(spec(handler=h))
        res = reg.invoke("echo_tool", {})
        self.assertEqual((res.status, res.ok, res.handler_called, res.codes()), ("failed", False, True,
                                                                                 ["TOOL_HANDLER_EXCEPTION"]))
        self.assertEqual((res.failures[0]["exception_type"], res.failures[0]["exception_message"]), ("ValueError", "boom"))
        self.assertEqual(len(h.calls), 1)                       # no automatic retry
        self.assertTrue(reg.is_invokable("echo_tool"))          # failure does not disable or unregister

    def test_base_exception_is_not_swallowed(self):
        reg = InProcessToolRegistry()
        reg.register(spec(handler=Handler(exc=KeyboardInterrupt())))
        with self.assertRaises(KeyboardInterrupt):
            reg.invoke("echo_tool", {})

    def test_invalid_output_reported(self):
        for out in (object(), {1: 2}, float("nan"), {"a": {1, 2}}):
            reg = InProcessToolRegistry()
            reg.register(spec(handler=Handler(result=out)))
            res = reg.invoke("echo_tool", {})
            self.assertEqual((res.status, res.codes(), res.output), ("failed", ["TOOL_OUTPUT_INVALID"], None))

    def test_falsy_json_outputs_are_valid(self):
        for out in (0, False, "", [], {}):
            reg = InProcessToolRegistry()
            reg.register(spec(handler=lambda i, o=out: o))
            res = reg.invoke("echo_tool", {})
            self.assertTrue(res.ok)
            self.assertEqual(res.output, out)

    def test_handler_return_none_is_valid_json_null(self):
        reg = InProcessToolRegistry()
        reg.register(spec(handler=lambda i: None))
        res = reg.invoke("echo_tool", {})
        self.assertEqual((res.ok, res.output), (True, None))


class TestDeterminism(unittest.TestCase):
    def test_same_operations_same_results(self):
        def run():
            reg = InProcessToolRegistry()
            out = [reg.register(spec("b_tool")).to_dict(), reg.register(spec("a_tool")).to_dict(),
                   reg.register(spec("a_tool")).to_dict(), reg.register(spec("Bad")).to_dict()]
            reg.disable("a_tool")
            out += [reg.invoke("a_tool", {}).to_dict(), reg.invoke("b_tool", {"x": 1}).to_dict(),
                    reg.invoke("zzz", {}).to_dict(), reg.list_descriptions()]
            return out
        self.assertEqual(run(), run())


class TestBoundaries(unittest.TestCase):
    def test_module_imports_only_copy_math_re(self):
        with open(os.path.join(PY_ROOT, "tools", "in_process_tool_registry.py"), encoding="utf-8") as fh:
            src = fh.read()
        mods = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertEqual(mods, {"copy", "math", "re", "tools"})  # Prompt 699: existing permission vocabulary
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, ("eval", "exec", "open", "compile", "__import__"))

    def test_not_wired_into_existing_flow(self):
        for sub in ("core", "agent", "planning", "execution", "reasoning", "context", "understanding"):
            base = os.path.join(PY_ROOT, sub)
            for root, _dirs, files in os.walk(base):
                for f in files:
                    if f.endswith(".py") and f != "tool_step_bridge.py":      # Prompt 707: the one sanctioned, caller-driven consumer
                        with open(os.path.join(root, f), encoding="utf-8") as fh:
                            self.assertNotIn("in_process_tool_registry", fh.read(), f)

    def test_no_module_level_registry_state(self):
        self.assertFalse([n for n, v in vars(mod).items() if isinstance(v, InProcessToolRegistry)])

    def test_existing_tool_definition_registry_untouched(self):
        from tools.tool_definition import ToolDefinition
        from tools.tool_registry import ToolRegistry
        reg = ToolRegistry()
        reg.register(ToolDefinition(name="x", description="d"))
        self.assertTrue(reg.has("x"))

    def test_shipped_database_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
