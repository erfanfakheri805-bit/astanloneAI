"""Prompt 719-A - caller-side Tool Step Intent adapter (agent/tool_step_intent.py).

Focused ONLY on the new module: structural validation of the explicit intent, construction of the `ToolRequest` through the existing
`create_tool_request`, stable failure codes, immutable/fresh-copy result, input isolation, and the module's isolation (no execution,
registry, AgentLoop, Plan or Core dependency; not wired anywhere).
Docs: docs/section6_tool_step_intent_prompt719a.md
"""
import ast
import collections
import copy
import os
import pickle
import subprocess
import sys
import unittest
from unittest import mock

from agent import tool_step_intent as mod
from agent.tool_step_intent import (INTENT_FAILURE_CODES, MAX_INTENT_DEPTH, ToolStepIntentResult, build_tool_step_intent)
from tools.tool_request import ToolRequest, create_tool_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def valid(**overrides):
    intent = {"plan_id": "plan-1", "step_id": "step-1",
              "tool_request": {"name": "echo_tool", "tool_input": {"text": "hi", "n": [1, 2.5, None, True]},
                               "granted_permissions": ["network"], "granted_capabilities": ["cap_a", "cap_b"], "confirmed": True},
              "max_attempts": 3}
    intent.update(overrides)
    return intent


def with_tool_request(**changes):
    intent = valid()
    intent["tool_request"].update(changes)
    return intent


def without(intent, *path):
    target = intent
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return intent


class ValidIntentTests(unittest.TestCase):
    def test_valid_minimal_intent(self):
        result = build_tool_step_intent(valid())
        self.assertTrue(result.ok)
        self.assertEqual(result.failures, [])
        self.assertEqual((result.plan_id, result.step_id, result.max_attempts), ("plan-1", "step-1", 3))
        self.assertIsNone(result.required_capabilities)      # optional fields are not invented
        self.assertIsNone(result.capability_mapping)

    def test_valid_intent_with_optional_fields_and_tuples(self):
        mapping = [{"capability": "Write files", "grants": ("cap_a", "cap_b")}]
        result = build_tool_step_intent(valid(required_capabilities=("Write files",), capability_mapping=mapping))
        self.assertTrue(result.ok)
        self.assertEqual(result.required_capabilities, ("Write files",))
        self.assertEqual(result.capability_mapping, mapping)
        self.assertIsInstance(result.capability_mapping[0]["grants"], tuple)   # container kinds preserved for Prompt 710
        tuple_grants = with_tool_request(granted_permissions=("network",), granted_capabilities=())
        self.assertTrue(build_tool_step_intent(tuple_grants).ok)

    def test_valid_tool_request_creation(self):
        result = build_tool_step_intent(valid())
        request = result.request
        self.assertIsInstance(request, ToolRequest)
        self.assertEqual(request.name, "echo_tool")
        self.assertEqual(request.input, {"text": "hi", "n": [1, 2.5, None, True]})
        self.assertEqual(request.granted_permissions, ("network",))
        self.assertEqual(request.granted_capabilities, ("cap_a", "cap_b"))   # caller order preserved, nothing added
        self.assertIs(request.confirmed, True)
        self.assertEqual(request, create_tool_request("echo_tool", {"text": "hi", "n": [1, 2.5, None, True]}, ["network"],
                                                      ["cap_a", "cap_b"], True).request)

    def test_create_tool_request_called_once_with_only_explicit_values(self):
        with mock.patch.object(mod, "create_tool_request", wraps=create_tool_request) as spy:
            self.assertTrue(build_tool_step_intent(valid()).ok)
        spy.assert_called_once_with("echo_tool", {"text": "hi", "n": [1, 2.5, None, True]}, ["network"], ["cap_a", "cap_b"], True)


class StructureRejectionTests(unittest.TestCase):
    def test_non_dict_intent(self):
        for bad in (None, [], (), "intent", 5, True, valid().items(), collections.OrderedDict(valid()), mock.Mock()):
            with self.subTest(bad=type(bad).__name__):
                result = build_tool_step_intent(bad)
                self.assertFalse(result.ok)
                self.assertEqual(result.codes(), ["INTENT_NOT_A_DICT"])
                self.assertIsNone(result.request)

    def test_missing_top_level_fields(self):
        for field in ("plan_id", "step_id", "tool_request", "max_attempts"):
            with self.subTest(field=field):
                result = build_tool_step_intent(without(valid(), field))
                self.assertEqual(result.codes(), ["INTENT_MISSING_FIELD"])
                self.assertEqual(result.failures[0]["field"], field)
        self.assertEqual(build_tool_step_intent({}).codes(), ["INTENT_MISSING_FIELD"] * 4)

    def test_missing_tool_request_and_authorization_fields(self):
        for field in ("name", "tool_input", "granted_permissions", "granted_capabilities", "confirmed"):
            with self.subTest(field=field):
                result = build_tool_step_intent(without(valid(), "tool_request", field))
                self.assertEqual(result.codes(), ["INTENT_TOOL_REQUEST_MISSING_FIELD"])
                self.assertEqual(result.failures[0]["field"], "tool_request." + field)
        with mock.patch.object(mod, "create_tool_request") as spy:      # nothing is defaulted: None is not "no grants"
            for field in ("granted_permissions", "granted_capabilities", "confirmed"):
                self.assertFalse(build_tool_step_intent(with_tool_request(**{field: None})).ok)
            self.assertFalse(build_tool_step_intent(with_tool_request(granted_permissions=set())).ok)
            spy.assert_not_called()
        self.assertEqual(build_tool_step_intent(valid(tool_request={})).codes(), ["INTENT_TOOL_REQUEST_MISSING_FIELD"] * 5)

    def test_extra_and_alternate_fields(self):
        result = build_tool_step_intent(valid(extra=1, another=2))
        self.assertEqual(result.codes(), ["INTENT_UNEXPECTED_FIELD"] * 2)
        self.assertEqual([f["field"] for f in result.failures], ["another", "extra"])      # sorted, deterministic
        renamed = valid()
        renamed["toolRequest"] = renamed.pop("tool_request")
        self.assertEqual(build_tool_step_intent(renamed).codes(), ["INTENT_MISSING_FIELD", "INTENT_UNEXPECTED_FIELD"])
        inner_extra = with_tool_request(input={"a": 1})         # "input" is not an accepted alias of "tool_input"
        self.assertEqual(build_tool_step_intent(inner_extra).codes(), ["INTENT_TOOL_REQUEST_UNEXPECTED_FIELD"])
        self.assertEqual(build_tool_step_intent(valid(**{"max_attempt": 2})).codes(), ["INTENT_UNEXPECTED_FIELD"])
        self.assertEqual(build_tool_step_intent({**valid(), 7: "x"}).codes(), ["INTENT_INVALID_FIELD_NAME"])

    def test_wrong_types(self):
        cases = [
            (valid(plan_id=5), "INTENT_INVALID_PLAN_ID"), (valid(plan_id=""), "INTENT_INVALID_PLAN_ID"),
            (valid(plan_id="   "), "INTENT_INVALID_PLAN_ID"), (valid(step_id=None), "INTENT_INVALID_STEP_ID"),
            (valid(step_id=["s"]), "INTENT_INVALID_STEP_ID"), (valid(tool_request=[]), "INTENT_INVALID_TOOL_REQUEST"),
            (valid(tool_request=None), "INTENT_INVALID_TOOL_REQUEST"),
            (with_tool_request(name=5), "INTENT_INVALID_TOOL_NAME"),
            (with_tool_request(granted_permissions="network"), "INTENT_INVALID_GRANTED_PERMISSIONS"),
            (with_tool_request(granted_permissions=["network", 1]), "INTENT_INVALID_GRANTED_PERMISSIONS"),
            (with_tool_request(granted_permissions={"network"}), "INTENT_INVALID_GRANTED_PERMISSIONS"),
            (with_tool_request(granted_capabilities=frozenset({"cap_a"})), "INTENT_INVALID_GRANTED_CAPABILITIES"),
            (with_tool_request(granted_capabilities=[None]), "INTENT_INVALID_GRANTED_CAPABILITIES"),
            (with_tool_request(confirmed=1), "INTENT_INVALID_CONFIRMED"), (with_tool_request(confirmed="true"), "INTENT_INVALID_CONFIRMED"),
            (valid(required_capabilities="a"), "INTENT_INVALID_REQUIRED_CAPABILITIES"),
            (valid(required_capabilities=None), "INTENT_INVALID_REQUIRED_CAPABILITIES"),
            (valid(required_capabilities=["a", 2]), "INTENT_INVALID_REQUIRED_CAPABILITIES"),
            (valid(capability_mapping={"a": ["b"]}), "INTENT_INVALID_CAPABILITY_MAPPING"),
            (valid(capability_mapping=None), "INTENT_INVALID_CAPABILITY_MAPPING"),
            (valid(capability_mapping=[{"capability": object()}]), "INTENT_INVALID_CAPABILITY_MAPPING"),
            (valid(capability_mapping=[{1: "x"}]), "INTENT_INVALID_CAPABILITY_MAPPING"),
        ]
        for intent, code in cases:
            with self.subTest(code=code):
                result = build_tool_step_intent(intent)
                self.assertFalse(result.ok)
                self.assertEqual(result.codes(), [code])
        subclass = type("S", (str,), {})
        self.assertEqual(build_tool_step_intent(valid(plan_id=subclass("p"))).codes(), ["INTENT_INVALID_PLAN_ID"])
        self.assertEqual(build_tool_step_intent(with_tool_request(name=subclass("echo"))).codes(), ["INTENT_INVALID_TOOL_NAME"])

    def test_invalid_max_attempts(self):
        self.assertEqual(build_tool_step_intent(without(valid(), "max_attempts")).codes(), ["INTENT_MISSING_FIELD"])
        for bad in (0, -1, True, False, 1.0, 2.5, "3", None, [3], float("nan")):
            with self.subTest(bad=repr(bad)):
                self.assertEqual(build_tool_step_intent(valid(max_attempts=bad)).codes(), ["INTENT_INVALID_MAX_ATTEMPTS"])
        self.assertEqual(build_tool_step_intent(valid(max_attempts=1)).max_attempts, 1)

    def test_all_problems_reported_in_field_order_and_codes_are_declared(self):
        result = build_tool_step_intent({"plan_id": 1, "step_id": 2, "tool_request": {"name": 3}, "max_attempts": 0, "zzz": 1})
        self.assertEqual(result.codes(), ["INTENT_UNEXPECTED_FIELD", "INTENT_INVALID_PLAN_ID", "INTENT_INVALID_STEP_ID"]
                         + ["INTENT_TOOL_REQUEST_MISSING_FIELD"] * 4 + ["INTENT_INVALID_TOOL_NAME", "INTENT_INVALID_MAX_ATTEMPTS"])
        self.assertEqual(result.codes(), build_tool_step_intent({"plan_id": 1, "step_id": 2, "tool_request": {"name": 3},
                                                                 "max_attempts": 0, "zzz": 1}).codes())   # deterministic
        self.assertTrue(set(result.codes()) <= set(INTENT_FAILURE_CODES))


class ToolRequestPropagationTests(unittest.TestCase):
    def test_tool_request_rejections_are_propagated_verbatim(self):
        cases = [with_tool_request(name="Bad Name"), with_tool_request(name="echo\n"), with_tool_request(granted_permissions=["teleport"]),
                 with_tool_request(granted_capabilities=["Bad Cap"]), with_tool_request(tool_input=["not", "a", "dict"]),
                 with_tool_request(tool_input="text"), with_tool_request(name="Bad", granted_permissions=["teleport"])]
        for intent in cases:
            with self.subTest(intent=intent["tool_request"]):
                tr = intent["tool_request"]
                expected = create_tool_request(tr["name"], tr["tool_input"], tr["granted_permissions"], tr["granted_capabilities"],
                                               tr["confirmed"])
                self.assertFalse(expected.ok)
                result = build_tool_step_intent(intent)
                self.assertFalse(result.ok)
                self.assertIsNone(result.request)
                self.assertEqual(result.codes(), expected.codes())
                self.assertEqual([f["message"] for f in result.failures], [f["message"] for f in expected.failures])
                self.assertTrue(all(f["field"] == "tool_request" for f in result.failures))

    def test_structural_failure_means_create_tool_request_is_never_called(self):
        with mock.patch.object(mod, "create_tool_request") as spy:
            self.assertFalse(build_tool_step_intent(valid(max_attempts=0)).ok)
            self.assertFalse(build_tool_step_intent(valid(extra=1)).ok)
            spy.assert_not_called()


class MalformedToolInputTests(unittest.TestCase):
    def test_non_json_safe_tool_input_is_rejected(self):
        cyclic = {}
        cyclic["self"] = cyclic
        deep = cur = {}
        for _ in range(MAX_INTENT_DEPTH + 5):
            cur["k"] = {}
            cur = cur["k"]
        cases = [{"t": (1, 2)}, {"t": {1, 2}}, {"t": b"bytes"}, {"t": float("nan")}, {"t": float("inf")}, {1: "non-str key"},
                 {"t": object()}, {"t": lambda: 1}, collections.OrderedDict(a=1), {"t": collections.OrderedDict()}, cyclic, deep,
                 {"t": type("I", (int,), {})(1)}, {"t": {"a": [1, {"b": object()}]}}]
        for value in cases:
            with self.subTest(value=type(value).__name__):
                with mock.patch.object(mod, "create_tool_request") as spy:
                    result = build_tool_step_intent(with_tool_request(tool_input=value))
                    spy.assert_not_called()
                self.assertEqual(result.codes(), ["INTENT_INVALID_TOOL_INPUT"])
                self.assertEqual(result.failures[0]["field"], "tool_request.tool_input")

    def test_rejected_values_are_never_inspected(self):
        class Booby:
            def __repr__(self): raise AssertionError("repr called")
            def __eq__(self, other): raise AssertionError("eq called")
            __hash__ = None
            def __deepcopy__(self, memo): raise AssertionError("deepcopy called")
        result = build_tool_step_intent(with_tool_request(tool_input={"x": [Booby()]}))
        self.assertEqual(result.codes(), ["INTENT_INVALID_TOOL_INPUT"])

    def test_empty_and_nested_json_input_is_valid_plain_data(self):
        for value in ({}, {"a": {"b": [1, "x", None, False, 1.5, {"c": []}]}}):
            self.assertTrue(build_tool_step_intent(with_tool_request(tool_input=value)).ok)


class ResultImmutabilityAndIsolationTests(unittest.TestCase):
    def setUp(self):
        self.mapping = [{"capability": "Write files", "grants": ["cap_a"]}]
        self.intent = valid(required_capabilities=["Write files"], capability_mapping=self.mapping)
        self.result = build_tool_step_intent(self.intent)
        self.assertTrue(self.result.ok)

    def test_result_is_immutable_and_data_only(self):
        for name in ("ok", "plan_id", "step_id", "request", "max_attempts", "required_capabilities", "capability_mapping", "failures"):
            with self.assertRaises(AttributeError):
                setattr(self.result, name, "x")
            with self.assertRaises(AttributeError):
                delattr(self.result, name)
        with self.assertRaises(AttributeError):
            self.result.extra = 1
        self.assertFalse(hasattr(self.result, "__dict__"))
        with self.assertRaises(TypeError):
            ToolStepIntentResult(object(), True, None, None, None, None, None, None, ())
        with self.assertRaises(TypeError):
            type("Sub", (ToolStepIntentResult,), {})
        with self.assertRaises(TypeError):
            pickle.dumps(self.result)
        self.assertIs(copy.copy(self.result), self.result)
        self.assertIs(copy.deepcopy(self.result), self.result)
        with self.assertRaises(TypeError):
            hash(self.result)
        with self.assertRaises(AttributeError):
            self.result.request.name = "other"      # the ToolRequest is itself immutable

    def test_reads_return_fresh_copies(self):
        self.result.capability_mapping[0]["grants"].append("hacked")
        self.result.required_capabilities.append("hacked")
        self.assertEqual(self.result.capability_mapping, self.mapping)
        self.assertEqual(self.result.required_capabilities, ["Write files"])
        self.assertIsNot(self.result.capability_mapping, self.result.capability_mapping)
        failed = build_tool_step_intent({})
        failed.failures.append({"code": "X"})
        failed.failures[0]["code"] = "Y"
        self.assertEqual(failed.codes(), ["INTENT_MISSING_FIELD"] * 4)
        view = self.result.to_dict()
        view["request"]["input"]["text"] = "changed"
        view["capability_mapping"][0]["capability"] = "changed"
        self.assertEqual(self.result.request.input["text"], "hi")
        self.assertEqual(self.result.capability_mapping[0]["capability"], "Write files")

    def test_caller_input_is_not_mutated_and_not_retained(self):
        snapshot = copy.deepcopy(self.intent)
        again = build_tool_step_intent(self.intent)
        self.assertEqual(self.intent, snapshot)
        self.intent["tool_request"]["tool_input"]["text"] = "mutated"
        self.intent["tool_request"]["granted_capabilities"].append("cap_z")
        self.intent["required_capabilities"].append("late")
        self.mapping[0]["grants"].append("late")
        self.mapping.append({"capability": "late", "grants": ["cap_b"]})
        self.assertEqual(again.request.input["text"], "hi")
        self.assertEqual(again.request.granted_capabilities, ("cap_a", "cap_b"))
        self.assertEqual(again.required_capabilities, ["Write files"])
        self.assertEqual(again.capability_mapping, [{"capability": "Write files", "grants": ["cap_a"]}])
        failing = {"plan_id": 1, "extra": [1]}
        snapshot = copy.deepcopy(failing)
        build_tool_step_intent(failing)
        self.assertEqual(failing, snapshot)

    def test_results_compare_by_data_and_are_deterministic(self):
        self.assertEqual(self.result, build_tool_step_intent(copy.deepcopy(self.intent)))
        self.assertNotEqual(self.result, build_tool_step_intent(valid()))
        self.assertEqual(build_tool_step_intent(valid()).to_dict(), build_tool_step_intent(valid()).to_dict())


class IsolationTests(unittest.TestCase):
    def test_module_imports_only_the_request_factory(self):
        with open(mod.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module)
        self.assertEqual(sorted(imported), ["math", "tools.tool_request"])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("execute", "execute_request", "invoke", "preflight", "start_plan_step", "AgentLoop", "process_input", "PlanManager",
                          "InProcessToolRegistry", "map_required_capabilities", "resolve_execution_route", "subprocess", "threading"):
            self.assertNotIn(forbidden, names)
        self.assertEqual([n.targets[0].id for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, (ast.List, ast.Dict, ast.Set))], [])

    def test_import_loads_no_execution_registry_agentloop_plan_or_core_modules(self):
        script = (
            "import sys\n"
            "for name in ('agent.agent_loop','core','core.core','execution','planning','planning.plan','planning.plan_manager',"
            "'ael','capabilities','tools.tool_registry'):\n"
            "    sys.modules[name] = None\n"
            "import agent.tool_step_intent as m\n"
            "loaded = sorted(n for n in sys.modules if sys.modules[n] is not None and n.split('.')[0] in ('agent','tools','planning','core','execution','ael','capabilities'))\n"
            "assert loaded == ['agent','agent.tool_step_intent','tools','tools.in_process_tool_registry','tools.tool_definition','tools.tool_request'], loaded\n"
            "r = m.build_tool_step_intent({'plan_id':'p','step_id':'s','tool_request':{'name':'echo','tool_input':{},'granted_permissions':[],"
            "'granted_capabilities':[],'confirmed':False},'max_attempts':1})\n"
            "assert r.ok and r.request.name == 'echo'\n")
        done = subprocess.run([sys.executable, "-c", script], cwd=PY_ROOT, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_building_an_intent_never_touches_a_registry_or_handler(self):
        from tools import in_process_tool_registry as registry_mod
        calls = []
        with mock.patch.object(registry_mod.InProcessToolRegistry, "__init__", side_effect=lambda *a, **k: calls.append("init")), \
             mock.patch.object(registry_mod.InProcessToolRegistry, "execute", side_effect=lambda *a, **k: calls.append("execute")), \
             mock.patch.object(registry_mod.InProcessToolRegistry, "preflight", side_effect=lambda *a, **k: calls.append("preflight")), \
             mock.patch.object(registry_mod.InProcessToolRegistry, "invoke", side_effect=lambda *a, **k: calls.append("invoke")):
            self.assertTrue(build_tool_step_intent(valid()).ok)
            self.assertFalse(build_tool_step_intent({}).ok)
        self.assertEqual(calls, [])

    def test_module_is_not_wired_into_any_production_module(self):
        offenders = []
        for folder, _dirs, files in os.walk(PY_ROOT):
            if os.path.basename(folder) in ("tests", "__pycache__"):
                continue
            for name in files:
                path = os.path.join(folder, name)
                if name.endswith(".py") and os.path.abspath(path) != os.path.abspath(mod.__file__):
                    with open(path, encoding="utf-8") as handle:
                        if "tool_step_intent" in handle.read():
                            offenders.append(os.path.relpath(path, PY_ROOT))
        # Prompt 719-B: the caller-side runner is the one sanctioned consumer; any other wiring is still an offender.
        # Prompt 719-C: exact-path exemption - agent/agent_loop.py imports it for the single routed Agent Loop entry point.
        self.assertEqual(sorted(offenders), [os.path.join("agent", "agent_loop.py"), os.path.join("agent", "tool_step_runner.py")])


if __name__ == "__main__":
    unittest.main()
