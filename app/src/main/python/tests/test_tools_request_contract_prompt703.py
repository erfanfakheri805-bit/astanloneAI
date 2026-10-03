"""Prompt 703 - explicit, immutable ToolRequest contract and its conversion to registry arguments. Pure in-memory."""
import ast
import copy
import hashlib
import json
import os
import pickle
import unittest

from tools import in_process_tool_registry as registry_mod
from tools import tool_request as mod
from tools.in_process_tool_registry import InProcessToolRegistry, ToolSpec
from tools.tool_request import ToolRequest, ToolRequestResult, create_tool_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, tool_input):
        self.calls.append(tool_input)
        return {"echo": tool_input}


def make_registry(name="req_tool", permissions=None, capabilities=None):
    handler = Recorder()
    reg = InProcessToolRegistry()
    assert reg.register(ToolSpec(name=name, description="d", handler=handler, input_schema={"type": "object"},
                                 output_description="echo", permissions=permissions or [],
                                 capabilities=capabilities or [])).ok
    return reg, handler


def ok_request(**kw):
    args = dict(name="req_tool", tool_input={"a": 1}, granted_permissions=None, granted_capabilities=None, confirmed=False)
    args.update(kw)
    result = create_tool_request(**args)
    assert result.ok, result.failures
    return result.request


class ValidCreationTests(unittest.TestCase):
    def test_valid_request_fields(self):
        res = create_tool_request("req_tool", {"a": [1, {"b": None}]}, ["network", "filesystem"], ["web_search"], True)
        self.assertIsInstance(res, ToolRequestResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.failures, [])
        self.assertEqual(res.codes(), [])
        req = res.request
        self.assertIsInstance(req, ToolRequest)
        self.assertEqual(req.name, "req_tool")
        self.assertEqual(req.input, {"a": [1, {"b": None}]})
        self.assertEqual(req.granted_permissions, ("network", "filesystem"))
        self.assertEqual(req.granted_capabilities, ("web_search",))
        self.assertIs(req.confirmed, True)

    def test_defaults_mean_no_grants_and_unconfirmed(self):
        req = create_tool_request("t", {}).request
        self.assertEqual(req.granted_permissions, ())
        self.assertEqual(req.granted_capabilities, ())
        self.assertIs(req.confirmed, False)

    def test_caller_intent_preserved_exactly(self):
        req = ok_request(granted_permissions=["network", "filesystem", "network"], granted_capabilities=["b_cap", "a_cap", "b_cap"])
        self.assertEqual(req.granted_permissions, ("network", "filesystem", "network"))   # order and repeats kept
        self.assertEqual(req.granted_capabilities, ("b_cap", "a_cap", "b_cap"))
        self.assertEqual(req.name, "req_tool")

    def test_unordered_collections_are_stored_sorted(self):
        for coll in (set, frozenset):
            req = ok_request(granted_permissions=coll(["network", "filesystem"]), granted_capabilities=coll(["z_cap", "a_cap"]))
            self.assertEqual(req.granted_permissions, ("filesystem", "network"))
            self.assertEqual(req.granted_capabilities, ("a_cap", "z_cap"))

    def test_tuple_collections_accepted(self):
        req = ok_request(granted_permissions=("network",), granted_capabilities=("c_one",))
        self.assertEqual(req.granted_permissions, ("network",))

    def test_user_confirmation_grant_is_not_a_confirmation(self):
        req = ok_request(granted_permissions=["user_confirmation"])
        self.assertEqual(req.granted_permissions, ("user_confirmation",))
        self.assertIs(req.confirmed, False)

    def test_unknown_tool_name_is_not_checked_against_any_registry(self):
        self.assertTrue(create_tool_request("no_such_tool_anywhere", {}).ok)


class InvalidNameTests(unittest.TestCase):
    def test_invalid_names(self):
        for bad in (None, "", " ", "Tool", "1tool", "_tool", "tool-name", "tool name", " tool", "tool ", "tool\n", "\ntool", "a" * 65,
                    "tööl", 5, b"tool", ["tool"], object()):
            res = create_tool_request(bad, {})
            self.assertFalse(res.ok, repr(bad))
            self.assertIsNone(res.request)
            self.assertEqual(res.codes(), ["INVALID_TOOL_REQUEST_NAME"], repr(bad))

    def test_boundary_valid_names(self):
        self.assertTrue(create_tool_request("a", {}).ok)
        self.assertTrue(create_tool_request("a" * 64, {}).ok)

    def test_name_is_not_normalized(self):
        self.assertFalse(create_tool_request("Req_Tool", {}).ok)
        self.assertFalse(create_tool_request(" req_tool", {}).ok)


class MalformedAuthorizationTests(unittest.TestCase):
    def test_malformed_permissions(self):
        for bad in ("network", ["nope"], ["Network"], [1], [None], [["network"]], {"network": True}, 5, True, b"network",
                    ["network", "nope"], [" network"], iter(["network"])):
            res = create_tool_request("t", {}, granted_permissions=bad)
            self.assertEqual(res.codes(), ["INVALID_TOOL_REQUEST_PERMISSIONS"], repr(bad))
            self.assertIsNone(res.request)

    def test_malformed_capabilities(self):
        for bad in ("web_search", ["Bad"], [1], [None], ["with space"], ["1abc"], [""], {"a": 1}, 3, b"x", ["a" * 65], ["cap\n"],
                    iter(["web_search"])):
            res = create_tool_request("t", {}, granted_capabilities=bad)
            self.assertEqual(res.codes(), ["INVALID_TOOL_REQUEST_CAPABILITIES"], repr(bad))

    def test_malformed_confirmation(self):
        for bad in (None, 1, 0, "true", "False", [], {}):
            res = create_tool_request("t", {}, confirmed=bad)
            self.assertEqual(res.codes(), ["INVALID_TOOL_REQUEST_CONFIRMATION"], repr(bad))

    def test_malformed_input(self):
        for bad in (None, [], "x", 5, {1: "a"}, {"a": (1, 2)}, {"a": {1, 2}}, {"a": float("nan")}, {"a": b"x"}, {"a": object()}):
            res = create_tool_request("t", bad)
            self.assertEqual(res.codes(), ["INVALID_TOOL_REQUEST_INPUT"], repr(bad))

    def test_cyclic_input_is_a_failure_not_a_crash(self):
        cyc = {}
        cyc["self"] = cyc
        self.assertEqual(create_tool_request("t", cyc).codes(), ["INVALID_TOOL_REQUEST_INPUT"])

    def test_all_problems_reported_in_field_order(self):
        res = create_tool_request("Bad", 5, "x", "y", "z")
        self.assertEqual(res.codes(), ["INVALID_TOOL_REQUEST_NAME", "INVALID_TOOL_REQUEST_INPUT",
                                       "INVALID_TOOL_REQUEST_PERMISSIONS", "INVALID_TOOL_REQUEST_CAPABILITIES",
                                       "INVALID_TOOL_REQUEST_CONFIRMATION"])
        self.assertFalse(res.to_dict()["ok"])
        self.assertIsNone(res.to_dict()["request"])

    def test_failure_codes_are_stable_and_repeatable(self):
        a = create_tool_request("Bad", 5, ["x"], ["Y"], 3)
        b = create_tool_request("Bad", 5, ["x"], ["Y"], 3)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_hostile_subclass_hooks_do_not_run(self):
        ran = []

        class EvilList(list):
            def __iter__(self):
                ran.append("iter")
                return iter([])

        class EvilStr(str):
            def __eq__(self, other):
                ran.append("eq")
                return True

            def __hash__(self):
                ran.append("hash")
                return 1

        class EvilDict(dict):
            def items(self):
                ran.append("items")
                return []

            def __deepcopy__(self, memo):
                ran.append("deepcopy")
                return {}

        res = create_tool_request("t", EvilDict({"k": EvilStr("v")}), EvilList([EvilStr("network")]), EvilList([EvilStr("a_cap")]))
        self.assertTrue(res.ok)
        self.assertEqual(ran, [])
        self.assertEqual(res.request.input, {"k": "v"})
        self.assertEqual(res.request.granted_permissions, ("network",))
        self.assertIs(type(res.request.granted_permissions[0]), str)
        self.assertIs(type(res.request.input["k"]), str)


class DefensiveCopyTests(unittest.TestCase):
    def test_caller_input_mutation_after_creation_changes_nothing(self):
        src = {"a": [1, 2], "b": {"c": "x"}}
        req = ok_request(tool_input=src)
        src["a"].append(3)
        src["b"]["c"] = "changed"
        src["new"] = 1
        self.assertEqual(req.input, {"a": [1, 2], "b": {"c": "x"}})

    def test_mutating_returned_input_changes_nothing(self):
        req = ok_request(tool_input={"a": [1]})
        first = req.input
        first["a"].append(2)
        first["z"] = 9
        self.assertEqual(req.input, {"a": [1]})
        self.assertIsNot(req.input, req.input)
        self.assertEqual(req.to_dict()["input"], {"a": [1]})

    def test_mutating_to_dict_changes_nothing(self):
        req = ok_request(granted_permissions=["network"], granted_capabilities=["a_cap"])
        d = req.to_dict()
        d["granted_permissions"].append("filesystem")
        d["granted_capabilities"].clear()
        d["input"]["x"] = 1
        d["confirmed"] = True
        self.assertEqual(req.to_dict(), {"name": "req_tool", "input": {"a": 1}, "granted_permissions": ["network"],
                                         "granted_capabilities": ["a_cap"], "confirmed": False})

    def test_caller_grant_list_mutation_after_creation_changes_nothing(self):
        perms, caps = ["network"], ["a_cap"]
        req = ok_request(granted_permissions=perms, granted_capabilities=caps)
        perms.append("filesystem")
        caps.append("b_cap")
        self.assertEqual(req.granted_permissions, ("network",))
        self.assertEqual(req.granted_capabilities, ("a_cap",))

    def test_mutating_conversion_output_changes_nothing(self):
        req = ok_request(tool_input={"a": [1]}, granted_permissions=["network"], granted_capabilities=["a_cap"])
        args = req.to_registry_arguments()
        args["tool_input"]["a"].append(2)
        args["granted_permissions"].append("filesystem")
        args["granted_capabilities"].append("b_cap")
        args["confirmed"] = True
        again = req.to_registry_arguments()
        self.assertEqual(again["tool_input"], {"a": [1]})
        self.assertEqual(again["granted_permissions"], ["network"])
        self.assertEqual(again["granted_capabilities"], ["a_cap"])
        self.assertIs(again["confirmed"], False)


class ImmutabilityTests(unittest.TestCase):
    def test_attribute_assignment_and_deletion_rejected(self):
        req = ok_request()
        for attr in ("name", "input", "granted_permissions", "granted_capabilities", "confirmed", "_name", "_input",
                     "_confirmed", "extra", "handler"):
            with self.assertRaises(AttributeError, msg=attr):
                setattr(req, attr, "x")
            with self.assertRaises(AttributeError, msg=attr):
                delattr(req, attr)
        self.assertEqual(req.name, "req_tool")

    def test_no_instance_dict(self):
        self.assertFalse(hasattr(ok_request(), "__dict__"))

    def test_grants_are_tuples(self):
        req = ok_request(granted_permissions=["network"], granted_capabilities=["a_cap"])
        self.assertIsInstance(req.granted_permissions, tuple)
        self.assertIsInstance(req.granted_capabilities, tuple)
        with self.assertRaises(TypeError):
            req.granted_permissions[0] = "x"

    def test_direct_construction_and_subclassing_refused(self):
        with self.assertRaises(TypeError):
            ToolRequest(object(), "t", {}, (), (), False)
        with self.assertRaises(TypeError):
            ToolRequest("t")
        with self.assertRaises(TypeError):
            class Sub(ToolRequest):
                pass

    def test_copy_returns_same_immutable_object_and_pickle_refused(self):
        req = ok_request()
        self.assertIs(copy.copy(req), req)
        self.assertIs(copy.deepcopy(req), req)
        with self.assertRaises(TypeError):
            pickle.dumps(req)

    def test_unhashable_but_comparable(self):
        req = ok_request()
        with self.assertRaises(TypeError):
            hash(req)
        self.assertEqual(req, ok_request())
        self.assertNotEqual(req, ok_request(confirmed=True))
        self.assertNotEqual(req, req.to_dict())


class ConversionTests(unittest.TestCase):
    def test_arguments_have_exact_registry_keywords(self):
        req = ok_request(tool_input={"a": 1}, granted_permissions=["network"], granted_capabilities=["a_cap"], confirmed=True)
        args = req.to_registry_arguments()
        self.assertEqual(args, {"name": "req_tool", "tool_input": {"a": 1}, "granted_permissions": ["network"],
                                "confirmed": True, "granted_capabilities": ["a_cap"]})
        import inspect
        for method in (InProcessToolRegistry.preflight, InProcessToolRegistry.invoke, InProcessToolRegistry.execute):
            inspect.signature(method).bind(None, **args)

    def test_conversion_is_deterministic(self):
        req = ok_request(tool_input={"k": [1, 2]}, granted_permissions={"network", "filesystem"})
        first = req.to_registry_arguments()
        for _ in range(5):
            self.assertEqual(req.to_registry_arguments(), first)
        self.assertEqual(json.dumps(first, sort_keys=False), json.dumps(req.to_registry_arguments(), sort_keys=False))

    def test_conversion_does_not_execute_or_touch_registry(self):
        reg, handler = make_registry()
        req = ok_request()
        req.to_registry_arguments()
        req.to_dict()
        self.assertEqual(handler.calls, [])
        self.assertEqual(reg.invocation_count(), 0)

    def test_preflight_with_request_arguments_passes_without_running_handler(self):
        reg, handler = make_registry()
        pre = reg.preflight(**ok_request().to_registry_arguments())
        self.assertTrue(pre.ok)
        self.assertEqual(handler.calls, [])
        self.assertEqual(reg.invocation_count(), 0)

    def test_execute_with_request_arguments_runs_handler_once_via_existing_path(self):
        reg, handler = make_registry(permissions=["network", "user_confirmation"], capabilities=["web_search"])
        req = ok_request(tool_input={"q": "x"}, granted_permissions=["network"], granted_capabilities=["web_search"],
                         confirmed=True)
        res = reg.execute(**req.to_registry_arguments())
        self.assertTrue(res.ok)
        self.assertEqual(handler.calls, [{"q": "x"}])
        self.assertEqual(reg.invocation_count(), 1)
        self.assertEqual(res.output, {"echo": {"q": "x"}})

    def test_creating_and_converting_never_calls_handler(self):
        reg, handler = make_registry()
        for _ in range(3):
            req = ok_request()
            req.to_registry_arguments()
            repr(req)
            req == ok_request()
        self.assertEqual(handler.calls, [])


class NoHandlerTests(unittest.TestCase):
    def test_request_never_contains_a_callable(self):
        reg, handler = make_registry()
        req = ok_request()
        self.assertFalse(hasattr(req, "handler"))
        for slot in ToolRequest.__slots__:
            value = getattr(req, slot)
            self.assertFalse(callable(value), slot)
        self.assertEqual(sorted(ToolRequest.__slots__),
                         sorted(["_name", "_input", "_granted_permissions", "_granted_capabilities", "_confirmed"]))
        json.dumps(req.to_dict())                              # plain JSON only
        json.dumps(req.to_registry_arguments())
        self.assertNotIn("handler", json.dumps(req.to_dict()).lower())

    def test_callable_input_values_are_rejected(self):
        self.assertEqual(create_tool_request("t", {"cb": lambda x: x}).codes(), ["INVALID_TOOL_REQUEST_INPUT"])
        self.assertEqual(create_tool_request("t", {"cb": Recorder()}).codes(), ["INVALID_TOOL_REQUEST_INPUT"])


class NoAuthorizationBypassTests(unittest.TestCase):
    def test_request_alone_grants_nothing(self):
        reg, handler = make_registry(permissions=["network"])
        req = ok_request()                                     # no grants supplied
        self.assertEqual(req.to_registry_arguments()["granted_permissions"], [])
        pre = reg.preflight(**req.to_registry_arguments())
        self.assertFalse(pre.ok)
        self.assertEqual(pre.outcome_code, "TOOL_PERMISSION_DENIED")
        res = reg.execute(**req.to_registry_arguments())
        self.assertEqual(res.execution_status, "authorization_rejected")
        self.assertEqual(handler.calls, [])

    def test_wrong_permission_grant_is_still_denied(self):
        reg, handler = make_registry(permissions=["network"])
        res = reg.execute(**ok_request(granted_permissions=["filesystem"]).to_registry_arguments())
        self.assertEqual(res.outcome_code, "TOOL_PERMISSION_DENIED")
        self.assertEqual(handler.calls, [])

    def test_confirmation_is_not_inferred(self):
        reg, handler = make_registry(permissions=["user_confirmation"])
        for grants in ([], ["user_confirmation"]):
            res = reg.execute(**ok_request(granted_permissions=grants).to_registry_arguments())
            self.assertEqual(res.outcome_code, "TOOL_CONFIRMATION_REQUIRED")
        self.assertEqual(handler.calls, [])
        self.assertTrue(reg.execute(**ok_request(granted_permissions=[], confirmed=True).to_registry_arguments()).ok)

    def test_capabilities_are_not_inferred(self):
        reg, handler = make_registry(capabilities=["web_search"])
        res = reg.execute(**ok_request(granted_capabilities=["other_cap"]).to_registry_arguments())
        self.assertEqual(res.outcome_code, "TOOL_CAPABILITY_MISSING")
        self.assertEqual(handler.calls, [])

    def test_unknown_and_disabled_tools_still_rejected(self):
        reg, handler = make_registry()
        self.assertEqual(reg.preflight(**ok_request(name="ghost_tool").to_registry_arguments()).outcome_code, "UNKNOWN_TOOL")
        reg.disable("req_tool")
        self.assertEqual(reg.execute(**ok_request().to_registry_arguments()).outcome_code, "TOOL_DISABLED")
        self.assertEqual(handler.calls, [])

    def test_name_is_not_corrected_to_a_registered_tool(self):
        reg, handler = make_registry()
        self.assertFalse(create_tool_request("Req_Tool", {}).ok)
        self.assertEqual(reg.preflight(**ok_request(name="req_tool_x").to_registry_arguments()).outcome_code, "UNKNOWN_TOOL")

    def test_registry_validation_is_not_weakened_by_a_request(self):
        reg, handler = make_registry()
        req = ok_request()
        self.assertTrue(reg.preflight(**req.to_registry_arguments()).input_valid)
        self.assertEqual(reg.invocation_count(), 0)
        reg.execute(**req.to_registry_arguments())
        reg.execute(**req.to_registry_arguments())
        self.assertEqual(len(handler.calls), 2)                # each execute is a separate explicit caller action
        self.assertEqual(reg.invocation_count(), 2)            # ... and each is audited by the registry


class EquivalenceAndStateTests(unittest.TestCase):
    def test_repeated_equivalent_requests_give_equivalent_data(self):
        args = dict(name="req_tool", tool_input={"a": [1, {"b": 2}]}, granted_permissions=["network", "filesystem"],
                    granted_capabilities=["a_cap"], confirmed=True)
        results = [create_tool_request(**args) for _ in range(5)]
        first = results[0].request
        for r in results[1:]:
            self.assertEqual(r.request, first)
            self.assertEqual(r.request.to_dict(), first.to_dict())
            self.assertEqual(r.request.to_registry_arguments(), first.to_registry_arguments())
            self.assertIsNot(r.request, first)
        self.assertEqual(json.dumps(results[1].to_dict()), json.dumps(results[2].to_dict()))

    def test_set_iteration_order_does_not_matter(self):
        a = ok_request(granted_permissions={"network", "filesystem", "user_account"})
        b = ok_request(granted_permissions=frozenset(["user_account", "filesystem", "network"]))
        self.assertEqual(a, b)

    def test_key_order_of_input_is_preserved(self):
        req = ok_request(tool_input={"z": 1, "a": 2})
        self.assertEqual(list(req.input), ["z", "a"])

    def test_no_module_level_state_and_no_registry_side_effects(self):
        before = {k: repr(v) for k, v in vars(mod).items() if not k.startswith("__")}
        for _ in range(3):
            ok_request()
        after = {k: repr(v) for k, v in vars(mod).items() if not k.startswith("__")}
        self.assertEqual(before, after)
        self.assertFalse(any(isinstance(v, (list, dict, set)) for k, v in vars(mod).items() if not k.startswith("__")))


class StaticGuardTests(unittest.TestCase):
    def test_imports_are_minimal(self):
        with open(os.path.join(PY_ROOT, "tools", "tool_request.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                roots.add((node.module or "").split(".")[0])
        self.assertEqual(roots, {"copy", "tools"})

    def test_registry_and_planner_do_not_reference_requests(self):
        for rel in (("core", "core.py"), ("agent", "agent_loop.py")):      # Prompt 704: only the registry's entry point uses requests
            with open(os.path.join(PY_ROOT, *rel), encoding="utf-8") as fh:
                self.assertNotIn("tool_request", fh.read(), rel)
        self.assertFalse(hasattr(registry_mod, "ToolRequest"))

    def test_pristine_db_hash(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
