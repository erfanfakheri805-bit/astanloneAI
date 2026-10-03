"""Prompt 702 - deterministic validation and normalization of tool outputs. Pure in-memory."""
import ast
import hashlib
import os
import unittest

from tools import in_process_tool_registry as mod
from tools.in_process_tool_registry import (InProcessToolRegistry, ToolSpec, normalize_tool_output,
                                            output_matches_type, validate_tool_spec, MAX_OUTPUT_DEPTH, OUTPUT_TYPES)

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


class Returning:
    def __init__(self, value=None, exc=None):
        self.value, self.exc, self.calls = value, exc, []

    def __call__(self, tool_input):
        self.calls.append(tool_input)
        if self.exc:
            raise self.exc
        return self.value


def make(name="out_tool", handler=None, output_type=None, **kw):
    return ToolSpec(name=name, description="d", handler=handler or Returning({}), input_schema={"type": "object"},
                    output_description="free text, never parsed", enabled=kw.pop("enabled", True),
                    output_type=output_type, **kw)


def reg_with(*specs):
    reg = InProcessToolRegistry()
    for s in specs:
        assert reg.register(s).ok
    return reg


class Boom:
    """Any of these hooks running would mean handler-supplied code executed during normalization."""
    ran = []


class BoomStr(str):
    def __str__(self):
        Boom.ran.append("str")
        return "x"


class BoomInt(int):
    def __int__(self):
        Boom.ran.append("int")
        return 1


class BoomFloat(float):
    def __float__(self):
        Boom.ran.append("float")
        return 1.0


class BoomList(list):
    def __iter__(self):
        Boom.ran.append("list")
        return iter([])

    def __deepcopy__(self, memo):
        Boom.ran.append("deepcopy")
        return []


class BoomDict(dict):
    def items(self):
        Boom.ran.append("items")
        return []

    def __iter__(self):
        Boom.ran.append("iter")
        return iter([])

    def __deepcopy__(self, memo):
        Boom.ran.append("deepcopy")
        return {}


class TestOutputTypeDeclaration(unittest.TestCase):
    def test_valid_and_invalid_declarations(self):
        for t in (None,) + OUTPUT_TYPES:
            self.assertEqual(validate_tool_spec(make(output_type=t)), [])
        for bad in ("dict", "Object", "", 5, ["object"], b"object", True):
            self.assertEqual([f["code"] for f in validate_tool_spec(make(output_type=bad))],
                             ["INVALID_TOOL_OUTPUT_TYPE"], repr(bad))
        reg = InProcessToolRegistry()
        self.assertEqual(reg.register(make(output_type="map")).codes(), ["INVALID_TOOL_OUTPUT_TYPE"])
        self.assertEqual(len(reg), 0)
        self.assertIsNone(ToolSpec().output_type)

    def test_getter_and_describe_unchanged(self):
        reg = reg_with(make(output_type="array"), make("plain"))
        self.assertEqual((reg.get_output_type("out_tool"), reg.get_output_type("plain"), reg.get_output_type("zzz")),
                         ("array", None, None))
        self.assertEqual(sorted(reg.describe("out_tool")),
                         ["description", "enabled", "input_schema", "name", "output_description"])


class TestValidOutputs(unittest.TestCase):
    def test_valid_outputs_per_declared_type(self):
        cases = [("object", {"a": [1, {"b": None}]}), ("array", [1, "x", None]), ("string", ""), ("number", 1),
                 ("number", 1.5), ("integer", 0), ("boolean", False), ("null", None)]
        for otype, value in cases:
            h = Returning(value)
            reg = reg_with(make(handler=h, output_type=otype))
            res = reg.execute("out_tool", {})
            self.assertEqual((res.execution_status, res.outcome_code, res.output, res.output_available, res.handler_called),
                             ("succeeded", "TOOL_COMPLETED", value, True, True), (otype, value))
            self.assertEqual(len(h.calls), 1)

    def test_no_declared_type_accepts_any_json_safe_output_backward_compatible(self):
        for value in ({}, [], "s", 3, 2.5, True, None, {"k": [1, {"z": None}]}):
            res = reg_with(make(handler=Returning(value))).execute("out_tool", {})
            self.assertEqual((res.ok, res.output, res.output_available), (True, value, True))

    def test_no_coercion_number_integer_boolean(self):
        self.assertTrue(output_matches_type(1, "number") and output_matches_type(1.5, "number"))
        self.assertFalse(output_matches_type(1.5, "integer"))
        self.assertFalse(output_matches_type(True, "number") or output_matches_type(True, "integer"))
        self.assertFalse(output_matches_type(1, "boolean") or output_matches_type("1", "integer"))
        res = reg_with(make(handler=Returning(1.0), output_type="integer")).execute("out_tool", {})
        self.assertEqual((res.outcome_code, res.output), ("TOOL_OUTPUT_VALIDATION_FAILED", None))


class TestInvalidOutputs(unittest.TestCase):
    def test_type_mismatch_is_output_invalid_not_handler_failed(self):
        h = Returning("text")
        reg = reg_with(make(handler=h, output_type="object"))
        res = reg.execute("out_tool", {"a": 1})
        self.assertEqual((res.execution_status, res.outcome_code, res.ok, res.handler_called, res.output_available,
                          res.output, res.authorization_accepted),
                         ("output_invalid", "TOOL_OUTPUT_VALIDATION_FAILED", False, True, False, None, True))
        self.assertEqual([(f["code"], f["expected_type"], f["actual_type"]) for f in res.failures],
                         [("TOOL_OUTPUT_VALIDATION_FAILED", "object", "string")])
        self.assertEqual(len(h.calls), 1)                      # ran exactly once, never retried
        inv = reg.invoke("out_tool", {})
        self.assertEqual((inv.status, inv.ok, inv.handler_called, inv.output), ("failed", False, True, None))

    def test_actual_type_names_are_json_names(self):
        for value, name in (({"a": 1}, "object"), ([1], "array"), ("s", "string"), (1, "integer"), (1.5, "number"),
                            (True, "boolean"), (None, "null")):
            other = "array" if name == "object" else "object"
            res = reg_with(make(handler=Returning(value), output_type=other)).execute("out_tool", {})
            self.assertEqual(res.failures[0]["actual_type"], name)

    def test_invalid_output_value_never_exposed(self):
        reg = reg_with(make(handler=Returning({"secret": 1}), output_type="array"))
        res = reg.execute("out_tool", {})
        rec = reg.get_invocation_history()[0]
        self.assertEqual((res.output, rec["output"], rec["output_available"]), (None, None, False))
        self.assertNotIn("secret", repr(res.to_dict()) + repr(rec))


class TestNonJsonSafeOutputs(unittest.TestCase):
    BAD = [(1, 2), {1, 2}, b"x", object(), float("nan"), float("inf"), {1: "a"}, [object()], {"k": (1,)}, len,
           complex(1, 2), bytearray(b"x")]

    def test_non_json_safe_output_remains_failed_execution(self):
        for bad in self.BAD:
            for otype in (None, "object", "array"):
                h = Returning(bad)
                reg = reg_with(make(handler=h, output_type=otype))
                res = reg.execute("out_tool", {})
                self.assertEqual((res.execution_status, res.outcome_code, res.handler_called, res.output), (
                    "handler_failed", "TOOL_OUTPUT_INVALID", True, None), repr(bad))
                inv = reg.get_invocation_history()[0]
                self.assertEqual((inv["status"], inv["outcome_code"], inv["handler_called"]),
                                 ("failed", "TOOL_OUTPUT_INVALID", True))
                self.assertEqual(len(h.calls), 1)

    def test_cyclic_and_too_deep_outputs_are_rejected_not_raised(self):
        cyc = []
        cyc.append(cyc)
        cd = {}
        cd["self"] = cd
        deep = current = []
        for _ in range(MAX_OUTPUT_DEPTH + 5):
            nxt = []
            current.append(nxt)
            current = nxt
        for bad in (cyc, cd, deep):
            res = reg_with(make(handler=Returning(bad))).execute("out_tool", {})
            self.assertEqual((res.outcome_code, res.handler_called), ("TOOL_OUTPUT_INVALID", True))
        ok = current = []
        for _ in range(MAX_OUTPUT_DEPTH - 1):
            nxt = []
            current.append(nxt)
            current = nxt
        self.assertTrue(normalize_tool_output(ok)[0])


class TestHandlerFailureAndRejections(unittest.TestCase):
    def test_handler_exception_unchanged(self):
        h = Returning(exc=ValueError("boom"))
        reg = reg_with(make(handler=h, output_type="object"))
        res = reg.execute("out_tool", {})
        self.assertEqual((res.execution_status, res.outcome_code, res.handler_called, res.output),
                         ("handler_failed", "TOOL_HANDLER_EXCEPTION", True, None))
        self.assertEqual(len(h.calls), 1)

    def test_rejections_before_handler_distinct_from_output_invalid(self):
        h = Returning("text")
        reg = reg_with(make(handler=h, output_type="object", permissions=["network"], capabilities=["a_cap"]),
                       make("off", handler=h, output_type="object", enabled=False))
        got = [reg.execute("nope", {}), reg.execute("off", {}), reg.execute("out_tool", {}),
               reg.execute("out_tool", {}, ["network"]),
               reg.execute("out_tool", "bad", ["network"], False, ["a_cap"])]
        self.assertEqual([r.execution_status for r in got],
                         ["tool_rejected", "tool_rejected", "authorization_rejected", "authorization_rejected",
                          "input_rejected"])
        self.assertTrue(all((not r.handler_called) and r.output is None for r in got))
        self.assertEqual(h.calls, [])
        after = reg.execute("out_tool", {}, ["network"], False, ["a_cap"])
        self.assertEqual((after.execution_status, after.handler_called), ("output_invalid", True))
        self.assertNotIn(after.execution_status, [r.execution_status for r in got])
        self.assertEqual(len(h.calls), 1)

    def test_preflight_never_validates_or_calls_output(self):
        h = Returning("text")
        reg = reg_with(make(handler=h, output_type="object"))
        self.assertTrue(reg.preflight("out_tool", {}).ok)
        self.assertEqual((h.calls, reg.invocation_count()), ([], 0))


class TestIsolationAndDeterminism(unittest.TestCase):
    def test_output_is_a_fresh_copy_separate_from_handler_object_and_audit(self):
        shared = {"items": [1, 2], "meta": {"k": "v"}}
        reg = reg_with(make(handler=Returning(shared), output_type="object"))
        res = reg.execute("out_tool", {})
        self.assertIsNot(res.output, shared)
        self.assertIsNot(res.output["items"], shared["items"])
        res.output["items"].append(99)
        res.to_dict()["output"]["meta"]["k"] = "changed"
        shared["items"].append(7)
        rec = reg.get_invocation_history()[0]
        self.assertEqual(rec["output"], {"items": [1, 2], "meta": {"k": "v"}})
        rec["output"]["items"].append("x")
        self.assertEqual(reg.get_invocation_history()[0]["output"], {"items": [1, 2], "meta": {"k": "v"}})
        self.assertEqual(reg.invoke("out_tool", {}).output, {"items": [1, 2, 7], "meta": {"k": "v"}})

    def test_normalization_never_runs_handler_supplied_code(self):
        Boom.ran.clear()
        value = {"s": BoomStr("a"), "i": BoomInt(3), "f": BoomFloat(2.5), "l": BoomList([1]), "d": BoomDict(z=1),
                 BoomStr("k"): BoomStr("v")}
        ok, out = normalize_tool_output(value)
        self.assertTrue(ok)
        self.assertEqual(Boom.ran, [])
        self.assertEqual(out, {"s": "a", "i": 3, "f": 2.5, "l": [1], "d": {"z": 1}, "k": "v"})
        for v in (out["s"], out["i"], out["f"], out["l"], out["d"], *out):
            self.assertIn(type(v), (str, int, float, list, dict))
        self.assertIs(type(out["i"]), int)
        self.assertIs(type(list(out)[-1]), str)
        res = reg_with(make(handler=Returning(value), output_type="object")).execute("out_tool", {})
        self.assertEqual((res.ok, res.output), (True, out))
        self.assertEqual(Boom.ran, [])

    def test_no_type_coercion_of_values(self):
        for value in ("1", 1, 1.0, True, None, [], {}, "", 0, False):
            ok, out = normalize_tool_output(value)
            self.assertTrue(ok)
            self.assertEqual((type(out), out), (type(value), value))
        self.assertEqual(normalize_tool_output((1, 2)), (False, None))
        self.assertEqual(normalize_tool_output({1: 2}), (False, None))
        self.assertEqual(normalize_tool_output(float("nan")), (False, None))

    def test_normalization_is_pure_deterministic_and_order_preserving(self):
        value = {"b": [1, {"y": 2, "x": 1}], "a": "s"}
        snapshot = {"b": [1, {"y": 2, "x": 1}], "a": "s"}
        first, second = normalize_tool_output(value), normalize_tool_output(value)
        self.assertEqual(first, second)
        self.assertEqual(value, snapshot)
        self.assertEqual(list(first[1]), ["b", "a"])
        self.assertEqual(list(first[1]["b"][1]), ["y", "x"])
        self.assertIsNot(first[1], second[1])

    def test_deterministic_execution_results(self):
        def run():
            reg = reg_with(make(handler=Returning({"a": [1]}), output_type="object"),
                           make("bad", handler=Returning([1]), output_type="object"),
                           make("worse", handler=Returning((1,))), make("boom", handler=Returning(exc=KeyError("k"))))
            return ([reg.execute(n, {}).to_dict() for n in ("out_tool", "bad", "worse", "boom", "zzz")],
                    reg.get_invocation_history())
        self.assertEqual(run(), run())
        results, _ = run()
        self.assertEqual([d["execution_status"] for d in results],
                         ["succeeded", "output_invalid", "handler_failed", "handler_failed", "tool_rejected"])


class TestAuditConsistency(unittest.TestCase):
    def test_result_and_record_agree_for_every_output_outcome(self):
        reg = reg_with(make("good", handler=Returning({"a": 1}), output_type="object"),
                       make("mismatch", handler=Returning("s"), output_type="object"),
                       make("nonjson", handler=Returning((1,))),
                       make("boom", handler=Returning(exc=RuntimeError("x"))),
                       make("gated", handler=Returning({}), permissions=["network"]))
        for name in ("good", "mismatch", "nonjson", "boom", "gated", "zzz"):
            res = reg.execute(name, {})
            rec = reg.get_invocation_history()[-1]
            self.assertEqual((res.tool_name, res.outcome_code, res.authorization_decision, res.handler_called, res.ok,
                              res.output_available, res.output, res.failures, res.sequence),
                             (rec["tool_name"], rec["outcome_code"], rec["authorization_decision"],
                              rec["handler_called"], rec["ok"], rec["output_available"], rec["output"],
                              rec["failures"], rec["sequence"]), name)
        self.assertEqual(reg.invocation_count(), 6)
        recs = reg.get_invocation_history()
        self.assertEqual([r["outcome_code"] for r in recs],
                         ["TOOL_COMPLETED", "TOOL_OUTPUT_VALIDATION_FAILED", "TOOL_OUTPUT_INVALID",
                          "TOOL_HANDLER_EXCEPTION", "TOOL_PERMISSION_DENIED", "UNKNOWN_TOOL"])
        self.assertEqual([r["handler_called"] for r in recs], [True, True, True, True, False, False])
        self.assertEqual([r["status"] for r in recs], ["completed", "failed", "failed", "failed", "rejected", "rejected"])
        self.assertEqual([r["output_available"] for r in recs], [True, False, False, False, False, False])


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

    def test_no_module_level_registry_state(self):
        self.assertFalse([n for n, v in vars(mod).items() if isinstance(v, InProcessToolRegistry)])

    def test_shipped_database_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
