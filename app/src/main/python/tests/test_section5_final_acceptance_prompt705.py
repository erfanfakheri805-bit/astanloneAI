"""Prompt 705 - Section 5 ("Tools & Controlled Task Execution") end-to-end acceptance. Pure in-memory, no production changes.

Path under acceptance:
    ToolSpec -> InProcessToolRegistry -> ToolRequest -> execute_request() -> execute() -> invoke() -> _invoke() -> _evaluate()
    -> handler -> ToolExecutionResult -> ToolInvocationRecord (audit).
Each test class below maps to one item of the Prompt 705 checklist (see docs/section5_final_acceptance_prompt705.md).
"""
import ast
import copy
import hashlib
import inspect
import os
import pickle
import re
import tempfile
import threading
import unittest
from unittest import mock

from tools import in_process_tool_registry as mod
from tools import tool_request as req_mod
from tools.in_process_tool_registry import (InProcessToolRegistry, ToolExecutionResult, ToolSpec, ToolPreflightResult,
                                            normalize_tool_output, validate_tool_spec)
from tools.tool_definition import SUPPORTED_PERMISSIONS, ToolDefinition
from tools.tool_registry import ToolRegistry
from tools.tool_request import ToolRequest, create_tool_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

RECORD_KEYS = {"sequence", "tool_name", "status", "ok", "outcome_code", "handler_called", "input_json_safe", "input_type",
               "input", "output_available", "output", "failures", "authorization_decision", "authorization_code",
               "required_permissions", "granted_permissions", "confirmed", "required_capabilities",
               "granted_capabilities"}
RESULT_KEYS = {"tool_name", "execution_status", "outcome_code", "authorization_accepted", "authorization_decision",
               "handler_called", "output_available", "output", "failures", "sequence", "ok"}
REQUEST_ARG_KEYS = {"name", "tool_input", "granted_permissions", "confirmed", "granted_capabilities"}
# execution_status -> the audit record status it must pair with
STATUS_PAIRING = {"succeeded": "completed", "handler_failed": "failed", "output_invalid": "failed",
                  "authorization_rejected": "rejected", "input_rejected": "rejected", "tool_rejected": "rejected"}


class Handler:
    """Counting handler. `fn(tool_input)` may raise or return; by default returns {"echo": input}."""

    def __init__(self, fn=None, value=None):
        self.fn, self.value, self.calls = fn, value, []

    def __call__(self, tool_input):
        self.calls.append(tool_input)
        if self.fn is not None:
            return self.fn(tool_input)
        return {"echo": tool_input} if self.value is None else self.value

    @property
    def count(self):
        return len(self.calls)


class ForbiddenHandler(Handler):
    def __call__(self, tool_input):
        self.calls.append(tool_input)
        raise AssertionError("handler must not be called")


def spec(name, handler=None, **kw):
    return ToolSpec(name=name, description="d", handler=handler if handler is not None else Handler(),
                    input_schema={"type": "object"}, output_description="o", **kw)


def make_registry(*specs):
    reg = InProcessToolRegistry()
    for s in specs:
        res = reg.register(s)
        assert res.ok, (s, res.failures)
    return reg


def make_request(name, tool_input=None, perms=None, caps=None, confirmed=False):
    res = create_tool_request(name, {"a": [1]} if tool_input is None else tool_input, perms, caps, confirmed)
    assert res.ok, res.failures
    return res.request


def nested_dict(depth):
    """dict nested `depth` levels deep, built iteratively (never recursive)."""
    value = {}
    for _ in range(depth - 1):
        value = {"k": value}
    return value


def forged(**slots):
    """A ToolRequest built WITHOUT create_tool_request() (object.__new__), with any slots filled in by hand."""
    obj = object.__new__(ToolRequest)
    for key, value in slots.items():
        object.__setattr__(obj, "_" + key, value)
    return obj


def sha256_of(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class Scenario:
    """A full registry covering every outcome kind, plus the handlers so tests can compare real call counts."""

    def __init__(self):
        self.h = {n: Handler() for n in ("ok", "net", "confirm", "both", "cap", "disabled", "raise", "badout", "typed_bad",
                                         "typed_ok", "big")}
        self.h["raise"] = Handler(fn=lambda i: (_ for _ in ()).throw(RuntimeError("boom")))
        self.h["badout"] = Handler(value=("tuple", "is", "not", "json"))
        self.h["typed_bad"] = Handler(value="a string")
        self.h["typed_ok"] = Handler(value=5)
        self.reg = make_registry(
            spec("ok", self.h["ok"]),
            spec("net", self.h["net"], permissions=["network"]),
            spec("confirm", self.h["confirm"], permissions=["user_confirmation"]),
            spec("both", self.h["both"], permissions=["network", "user_confirmation"]),
            spec("cap", self.h["cap"], capabilities=["web_search"]),
            spec("disabled", self.h["disabled"], enabled=False),
            spec("raise", self.h["raise"]),
            spec("badout", self.h["badout"]),
            spec("typed_bad", self.h["typed_bad"], output_type="integer"),
            spec("typed_ok", self.h["typed_ok"], output_type="integer"),
        )

    def run_all(self):
        """Returns [(label, expected_outcome_code, expected_execution_status, tool_key_or_None, result)] in call order."""
        r, out = self.reg, []

        def go(label, code, status, key, result):
            out.append((label, code, status, key, result))

        go("success", "TOOL_COMPLETED", "succeeded", "ok", r.execute_request(make_request("ok", {"q": 1})))
        go("typed_ok", "TOOL_COMPLETED", "succeeded", "typed_ok", r.execute_request(make_request("typed_ok")))
        go("net_granted", "TOOL_COMPLETED", "succeeded", "net", r.execute_request(make_request("net", perms=["network"])))
        go("net_denied", "TOOL_PERMISSION_DENIED", "authorization_rejected", "net", r.execute_request(make_request("net")))
        go("confirm_missing", "TOOL_CONFIRMATION_REQUIRED", "authorization_rejected", "confirm",
           r.execute_request(make_request("confirm", perms=["user_confirmation"])))
        go("cap_missing", "TOOL_CAPABILITY_MISSING", "authorization_rejected", "cap", r.execute_request(make_request("cap")))
        go("disabled", "TOOL_DISABLED", "tool_rejected", "disabled", r.execute_request(make_request("disabled")))
        go("unknown", "UNKNOWN_TOOL", "tool_rejected", None, r.execute_request(make_request("nope")))
        go("handler_exc", "TOOL_HANDLER_EXCEPTION", "handler_failed", "raise", r.execute_request(make_request("raise")))
        go("bad_output", "TOOL_OUTPUT_INVALID", "handler_failed", "badout", r.execute_request(make_request("badout")))
        go("wrong_type", "TOOL_OUTPUT_VALIDATION_FAILED", "output_invalid", "typed_bad",
           r.execute_request(make_request("typed_bad")))
        go("invalid_request", "INVALID_TOOL_REQUEST", "tool_rejected", None, r.execute_request("not a request"))
        go("invalid_authorization", "INVALID_TOOL_AUTHORIZATION", "authorization_rejected", "ok",
           r.execute("ok", {"a": 1}, granted_permissions="network"))
        go("invalid_input", "INVALID_TOOL_INPUT", "input_rejected", "ok", r.execute("ok", ["not", "a", "dict"]))
        go("success_after_all", "TOOL_COMPLETED", "succeeded", "ok", r.execute_request(make_request("ok", {"z": 2})))
        return out


# --------------------------------------------------------------------------------------------------------------------
class T01RegistrationAndExactNames(unittest.TestCase):
    def test_valid_names_register(self):
        reg = InProcessToolRegistry()
        for name in ("a", "tool", "web_search", "t1", "x_" + "y" * 62, "a" * 64):
            self.assertTrue(reg.register(spec(name)).ok, name)
            self.assertTrue(reg.has(name))
        self.assertEqual(reg.list_names(), sorted(reg.list_names()))

    def test_invalid_names_are_rejected_and_not_stored(self):
        reg = InProcessToolRegistry()
        bad = ["", "Tool", "TOOL", "1tool", "_tool", "tool-x", "tool x", " tool", "tool ", "tool\n", "\ntool", "tool\r",
               "to\nol", "a" * 65, "tööl", "tool\x00", None, 5, b"tool", ["tool"], ("tool",)]
        for name in bad:
            res = reg.register(spec(name))
            self.assertFalse(res.ok, repr(name))
            self.assertEqual(res.codes()[0], "INVALID_TOOL_NAME", repr(name))
        self.assertEqual(len(reg), 0)

    def test_lookup_is_exact_never_fuzzy(self):
        reg = make_registry(spec("web_search"))
        for probe in ("Web_Search", "web_search ", " web_search", "web_search\n", "web-search", "websearch", "web_searc", "",
                      None, 3, ["web_search"]):
            self.assertFalse(reg.has(probe), repr(probe))
            self.assertIsNone(reg.describe(probe))
            self.assertFalse(reg.is_invokable(probe))
            self.assertFalse(reg.enable(probe))
            self.assertFalse(reg.disable(probe))
        self.assertTrue(reg.has("web_search"))

    def test_duplicate_is_rejected_and_first_registration_untouched(self):
        first, second = Handler(value={"who": "first"}), Handler(value={"who": "second"})
        reg = make_registry(spec("dup", first))
        res = reg.register(spec("dup", second, enabled=False))
        self.assertFalse(res.ok)
        self.assertEqual(res.codes(), ["DUPLICATE_TOOL_NAME"])
        self.assertTrue(reg.is_enabled("dup"))
        self.assertEqual(reg.execute_request(make_request("dup")).output, {"who": "first"})
        self.assertEqual((first.count, second.count), (1, 0))

    def test_invalid_spec_is_rejected_never_raises_never_stored(self):
        reg = InProcessToolRegistry()
        for bad in (None, "x", 5, {"name": "x"}, ToolSpec(), ToolSpec(name="x"), spec("ok1", handler=42),
                    ToolSpec(name="ok2", description=" ", handler=Handler(), output_description="o"),
                    spec("ok3", enabled="yes"), spec("ok4", permissions=["bogus"]), spec("ok5", capabilities=["Bad"]),
                    spec("ok6", output_type="tuple")):
            self.assertFalse(reg.register(bad).ok, repr(bad))
        self.assertEqual(len(reg), 0)
        self.assertEqual(validate_tool_spec(None)[0]["code"], "INVALID_TOOL_SPEC")

    def test_register_never_calls_handler(self):
        h = ForbiddenHandler()
        reg = make_registry(spec("quiet", h))
        reg.describe("quiet"), reg.list_descriptions(), reg.preflight("quiet", {})
        self.assertEqual(h.count, 0)

    def test_spec_edits_after_register_change_nothing(self):
        original, other = Handler(value={"who": "orig"}), Handler(value={"who": "other"})
        s = spec("frozen_copy", original, permissions=["network"], capabilities=["c1"])
        s.input_schema = {"type": "object", "props": [1]}
        reg = make_registry(s)
        s.name, s.description, s.handler, s.enabled = "renamed", "changed", other, False
        s.permissions.append("filesystem")
        s.capabilities.append("c2")
        s.input_schema["props"].append(2)
        self.assertTrue(reg.has("frozen_copy") and not reg.has("renamed"))
        self.assertTrue(reg.is_enabled("frozen_copy"))
        self.assertEqual(reg.get_required_permissions("frozen_copy"), ["network"])
        self.assertEqual(reg.get_required_capabilities("frozen_copy"), ["c1"])
        self.assertEqual(reg.describe("frozen_copy")["input_schema"], {"type": "object", "props": [1]})
        res = reg.execute_request(make_request("frozen_copy", perms=["network"], caps=["c1"]))
        self.assertEqual(res.output, {"who": "orig"})
        self.assertEqual((original.count, other.count), (1, 0))

    def test_describe_never_exposes_handler(self):
        reg = make_registry(spec("shown"))
        for d in [reg.describe("shown")] + reg.list_descriptions():
            self.assertEqual(set(d), {"name", "description", "input_schema", "output_description", "enabled"})
            self.assertFalse(any(callable(v) for v in d.values()))


class T02EnabledDisabled(unittest.TestCase):
    def test_disabled_tool_is_rejected_without_handler(self):
        h = ForbiddenHandler()
        reg = make_registry(spec("off", h, enabled=False))
        res = reg.execute_request(make_request("off"))
        self.assertEqual((res.execution_status, res.outcome_code, res.handler_called), ("tool_rejected", "TOOL_DISABLED", False))
        self.assertFalse(reg.is_invokable("off"))
        self.assertTrue(reg.has("off"))
        self.assertEqual(h.count, 0)

    def test_enable_then_disable_round_trip(self):
        h = Handler()
        reg = make_registry(spec("flip", h, enabled=False))
        self.assertTrue(reg.enable("flip"))
        self.assertTrue(reg.execute_request(make_request("flip")).ok)
        self.assertTrue(reg.disable("flip"))
        res = reg.execute_request(make_request("flip"))
        self.assertEqual(res.outcome_code, "TOOL_DISABLED")
        self.assertEqual(h.count, 1)
        self.assertTrue(reg.enable("flip"))
        self.assertTrue(reg.execute_request(make_request("flip")).ok)
        self.assertEqual(h.count, 2)

    def test_disabled_is_checked_before_authorization_and_input(self):
        reg = make_registry(spec("off_net", ForbiddenHandler(), enabled=False, permissions=["network", "user_confirmation"],
                                 capabilities=["c"]))
        res = reg.execute("off_net", "not even a dict")
        self.assertEqual(res.outcome_code, "TOOL_DISABLED")
        self.assertEqual(res.authorization_decision, "not_evaluated")
        self.assertFalse(res.authorization_accepted)

    def test_unknown_is_checked_before_everything(self):
        reg = InProcessToolRegistry()
        res = reg.execute("ghost", "junk", granted_permissions="junk", confirmed="junk")
        self.assertEqual(res.outcome_code, "UNKNOWN_TOOL")
        self.assertEqual(res.execution_status, "tool_rejected")

    def test_enable_does_not_grant_anything(self):
        reg = make_registry(spec("gated", ForbiddenHandler(), enabled=False, permissions=["network"]))
        reg.enable("gated")
        self.assertEqual(reg.execute_request(make_request("gated")).outcome_code, "TOOL_PERMISSION_DENIED")

    def test_enabled_flag_is_the_registry_own(self):
        s = spec("own_flag")
        reg = make_registry(s)
        s.enabled = False
        self.assertTrue(reg.is_enabled("own_flag"))
        reg.disable("own_flag")
        s.enabled = True
        self.assertFalse(reg.is_enabled("own_flag"))


class T03ToolRequestCreationAndImmutability(unittest.TestCase):
    def test_creation_preserves_caller_intent_exactly(self):
        r = make_request("web_search", {"q": "x", "n": [1, {"y": None}]}, ["network", "network", "filesystem"], ["b", "a", "a"], True)
        self.assertEqual((r.name, r.input, r.confirmed), ("web_search", {"q": "x", "n": [1, {"y": None}]}, True))
        self.assertEqual(r.granted_permissions, ("network", "network", "filesystem"))
        self.assertEqual(r.granted_capabilities, ("b", "a", "a"))
        self.assertEqual(make_request("t").granted_permissions, ())
        self.assertIs(make_request("t").confirmed, False)

    def test_sets_are_stored_sorted(self):
        r = make_request("t", perms={"network", "filesystem"}, caps=frozenset({"zz", "aa"}))
        self.assertEqual(r.granted_permissions, ("filesystem", "network"))
        self.assertEqual(r.granted_capabilities, ("aa", "zz"))

    def test_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            ToolRequest(object(), "t", {}, (), (), False)
        with self.assertRaises(TypeError):
            ToolRequest()
        with self.assertRaises(TypeError):
            class Sub(ToolRequest):
                pass

    def test_instances_are_immutable(self):
        r = make_request("t")
        for attr in ("name", "input", "granted_permissions", "granted_capabilities", "confirmed", "_name", "_input", "extra"):
            with self.assertRaises(AttributeError, msg=attr):
                setattr(r, attr, "x")
            with self.assertRaises(AttributeError, msg=attr):
                delattr(r, attr)
        self.assertFalse(hasattr(r, "__dict__"))

    def test_caller_mutation_after_creation_changes_nothing(self):
        data, perms, caps = {"a": [1, {"b": 2}]}, ["network"], ["c"]
        r = make_request("t", data, perms, caps)
        data["a"].append(99)
        data["new"] = 1
        perms.append("filesystem")
        caps.append("d")
        self.assertEqual(r.input, {"a": [1, {"b": 2}]})
        self.assertEqual((r.granted_permissions, r.granted_capabilities), (("network",), ("c",)))

    def test_reads_return_fresh_copies(self):
        r = make_request("t", {"a": [1]})
        r.input["a"].append(2)
        r.to_dict()["input"]["a"].append(3)
        r.to_registry_arguments()["tool_input"]["a"].append(4)
        r.to_dict()["granted_permissions"].append("x")
        r.to_registry_arguments()["granted_capabilities"].append("x")
        self.assertEqual(r.input, {"a": [1]})
        self.assertEqual(r.to_dict()["granted_permissions"], [])
        self.assertIsNot(r.input, r.input)

    def test_copy_pickle_hash_equality(self):
        r = make_request("t", {"a": 1})
        self.assertIs(copy.copy(r), r)
        self.assertIs(copy.deepcopy(r), r)
        with self.assertRaises(TypeError):
            pickle.dumps(r)
        with self.assertRaises(TypeError):
            hash(r)
        self.assertEqual(r, make_request("t", {"a": 1}))
        self.assertNotEqual(r, make_request("t", {"a": 2}))
        self.assertNotEqual(r, {"name": "t"})

    def test_request_carries_no_handler_registry_or_callable(self):
        r = make_request("t", {"a": [1]}, ["network"], ["c"], True)
        blobs = [r.to_dict(), r.to_registry_arguments()]
        def has_callable(v):
            return callable(v) or (isinstance(v, dict) and any(map(has_callable, v.values()))) or (
                isinstance(v, (list, tuple)) and any(map(has_callable, v)))
        self.assertFalse(any(has_callable(b) for b in blobs))
        self.assertFalse(hasattr(r, "handler") or hasattr(r, "registry"))
        self.assertEqual(set(r.to_registry_arguments()), REQUEST_ARG_KEYS)

    def test_bad_data_reports_all_codes_in_order_and_never_raises(self):
        res = create_tool_request("Bad Name", [1], ["bogus"], ["Bad"], "yes")
        self.assertFalse(res.ok)
        self.assertIsNone(res.request)
        self.assertEqual(res.codes(), ["INVALID_TOOL_REQUEST_NAME", "INVALID_TOOL_REQUEST_INPUT",
                                       "INVALID_TOOL_REQUEST_PERMISSIONS", "INVALID_TOOL_REQUEST_CAPABILITIES",
                                       "INVALID_TOOL_REQUEST_CONFIRMATION"])
        for bad_confirm in (1, 0, None, "True", [], 1.0):
            self.assertIn("INVALID_TOOL_REQUEST_CONFIRMATION", create_tool_request("t", {}, None, None, bad_confirm).codes())
        for bad_input in (None, [], "s", 5, {1: 2}, {"a": (1,)}, {"a": {1}}, {"a": float("nan")}, {"a": b"x"}, {"a": object()}):
            self.assertIn("INVALID_TOOL_REQUEST_INPUT", create_tool_request("t", bad_input).codes(), repr(bad_input))
        for bad_grants in ("network", b"network", {"network": 1}, 5, ["network", 5], [["network"]]):
            self.assertIn("INVALID_TOOL_REQUEST_PERMISSIONS", create_tool_request("t", {}, bad_grants).codes(), repr(bad_grants))

    def test_creating_and_reading_a_request_never_touches_a_registry(self):
        h = ForbiddenHandler()
        reg = make_registry(spec("watched", h))
        r = make_request("watched")
        r.to_dict(), r.to_registry_arguments(), r.input, repr(r)
        self.assertEqual((h.count, reg.invocation_count()), (0, 0))


class T04ExecuteRequestUsesExactlyTheRequestArguments(unittest.TestCase):
    def test_execute_request_calls_execute_once_with_exactly_the_request_arguments(self):
        seen = []

        class Spy(InProcessToolRegistry):
            def execute(self, *args, **kwargs):
                seen.append((args, kwargs))
                return super().execute(*args, **kwargs)

        reg = Spy()
        reg.register(spec("spy_tool", permissions=["network", "user_confirmation"], capabilities=["c1"]))
        request = make_request("spy_tool", {"k": [1, {"z": 2}]}, ["network", "user_confirmation"], ["c1"], True)
        expected = request.to_registry_arguments()
        res = reg.execute_request(request)
        self.assertTrue(res.ok)
        self.assertEqual(len(seen), 1)
        args, kwargs = seen[0]
        self.assertEqual(args, ())
        self.assertEqual(kwargs, expected)
        self.assertEqual(set(kwargs), REQUEST_ARG_KEYS)

    def test_no_argument_is_added_dropped_or_repaired(self):
        for perms, caps, confirmed in ((None, None, False), (["network"], None, False), (None, ["c1"], False),
                                       (["network", "user_confirmation"], ["c1"], True), (["user_confirmation"], None, False)):
            with self.subTest(perms=perms, caps=caps, confirmed=confirmed):
                seen = []

                class Spy(InProcessToolRegistry):
                    def invoke(self, name, tool_input, granted_permissions=None, confirmed=False, granted_capabilities=None):
                        seen.append((name, tool_input, granted_permissions, confirmed, granted_capabilities))
                        return super().invoke(name, tool_input, granted_permissions, confirmed, granted_capabilities)

                reg = Spy()
                reg.register(spec("spy_tool"))
                request = make_request("spy_tool", {"q": 1}, perms, caps, confirmed)
                reg.execute_request(request)
                self.assertEqual(seen, [("spy_tool", {"q": 1}, list(request.granted_permissions), confirmed,
                                         list(request.granted_capabilities))])

    def test_equivalent_to_direct_execute_on_a_fresh_registry(self):
        def build():
            return make_registry(spec("eq", Handler(value={"v": [1, 2]}), permissions=["network", "user_confirmation"],
                                      capabilities=["c1"], output_type="object"))
        for perms, caps, confirmed in ((["network"], ["c1"], True), ([], ["c1"], True), (["network"], [], True),
                                       (["network"], ["c1"], False)):
            request = make_request("eq", {"in": 1}, perms, caps, confirmed)
            a, b = build(), build()
            via_request = a.execute_request(request)
            direct = b.execute("eq", {"in": 1}, perms, confirmed, caps)
            self.assertEqual(via_request.to_dict(), direct.to_dict())
            self.assertEqual(a.get_invocation_history(), b.get_invocation_history())

    def test_request_named_tool_is_the_only_tool_run(self):
        a, b = Handler(value={"who": "a"}), Handler(value={"who": "b"})
        reg = make_registry(spec("tool_a", a), spec("tool_b", b))
        self.assertEqual(reg.execute_request(make_request("tool_b")).output, {"who": "b"})
        self.assertEqual((a.count, b.count), (0, 1))

    def test_handler_receives_exactly_the_request_input(self):
        h = Handler()
        reg = make_registry(spec("inp", h))
        reg.execute_request(make_request("inp", {"q": "x", "n": [1, {"y": [2]}]}))
        self.assertEqual(h.calls, [{"q": "x", "n": [1, {"y": [2]}]}])

    def test_full_pipeline_spec_to_audit(self):
        h = Handler(value={"answer": 42})
        s = spec("pipeline", h, permissions=["network"], capabilities=["c1"], output_type="object")
        reg = InProcessToolRegistry()
        self.assertTrue(reg.register(s).ok)
        request = create_tool_request("pipeline", {"q": "life"}, ["network"], ["c1"]).request
        self.assertIsInstance(request, ToolRequest)
        res = reg.execute_request(request)
        self.assertIsInstance(res, ToolExecutionResult)
        rec = reg.get_invocation_history()[0]
        self.assertEqual((res.execution_status, res.output, res.sequence), ("succeeded", {"answer": 42}, 1))
        self.assertEqual((rec["tool_name"], rec["status"], rec["outcome_code"], rec["input"], rec["output"]),
                         ("pipeline", "completed", "TOOL_COMPLETED", {"q": "life"}, {"answer": 42}))
        self.assertEqual((rec["required_permissions"], rec["granted_permissions"], rec["required_capabilities"],
                          rec["granted_capabilities"]), (["network"], ["network"], ["c1"], ["c1"]))
        self.assertEqual(h.calls, [{"q": "life"}])


class T05AuthorizationCannotBeBypassed(unittest.TestCase):
    def setUp(self):
        self.h = Handler()
        self.reg = make_registry(spec("guarded", self.h, permissions=["network", "filesystem", "user_confirmation"],
                                      capabilities=["cap_a", "cap_b"]))

    def run_req(self, perms=None, caps=None, confirmed=False):
        return self.reg.execute_request(make_request("guarded", {"q": 1}, perms, caps, confirmed))

    def test_deny_by_default(self):
        res = self.run_req()
        self.assertEqual(res.outcome_code, "TOOL_PERMISSION_DENIED")
        self.assertEqual(res.failures[0]["missing_permissions"], ["filesystem", "network"])
        self.assertEqual(self.h.count, 0)

    def test_each_missing_permission_denies(self):
        for perms in (["network"], ["filesystem"], []):
            self.assertEqual(self.run_req(perms, ["cap_a", "cap_b"], True).outcome_code, "TOOL_PERMISSION_DENIED")
        self.assertEqual(self.h.count, 0)

    def test_naming_user_confirmation_is_not_a_confirmation(self):
        res = self.run_req(["network", "filesystem", "user_confirmation"], ["cap_a", "cap_b"], False)
        self.assertEqual((res.outcome_code, res.authorization_decision), ("TOOL_CONFIRMATION_REQUIRED", "confirmation_required"))
        self.assertEqual(self.h.count, 0)

    def test_permission_denial_is_reported_before_missing_confirmation_and_capabilities(self):
        self.assertEqual(self.run_req(["network"], [], False).outcome_code, "TOOL_PERMISSION_DENIED")
        self.assertEqual(self.run_req(["network", "filesystem"], [], False).outcome_code, "TOOL_CONFIRMATION_REQUIRED")
        self.assertEqual(self.run_req(["network", "filesystem"], [], True).outcome_code, "TOOL_CAPABILITY_MISSING")
        self.assertEqual(self.h.count, 0)

    def test_every_capability_is_required(self):
        for caps in ([], ["cap_a"], ["cap_b"], ["other"]):
            res = self.run_req(["network", "filesystem"], caps, True)
            self.assertEqual(res.outcome_code, "TOOL_CAPABILITY_MISSING", caps)
            self.assertEqual(res.authorization_decision, "capability_missing")
            self.assertFalse(res.authorization_accepted)
        self.assertEqual(self.h.count, 0)

    def test_full_authorization_runs_the_handler_exactly_once(self):
        res = self.run_req(["network", "filesystem", "user_confirmation"], ["cap_a", "cap_b", "extra"], True)
        self.assertTrue(res.ok)
        self.assertEqual((res.authorization_decision, res.authorization_accepted, self.h.count), ("accepted", True, 1))

    def test_confirmation_must_be_a_real_true(self):
        for bad in ("yes", 1, "True", [True], None):
            res = self.reg.execute("guarded", {"q": 1}, ["network", "filesystem"], bad, ["cap_a", "cap_b"])
            self.assertEqual(res.outcome_code, "INVALID_TOOL_AUTHORIZATION", repr(bad))
        self.assertEqual(self.h.count, 0)

    def test_malformed_authorization_arguments_are_rejected(self):
        for perms in ("network", b"network", 5, {"network": True}, ["bogus"], [None], [["network"]], object()):
            res = self.reg.execute("guarded", {"q": 1}, perms, True, ["cap_a", "cap_b"])
            self.assertEqual(res.outcome_code, "INVALID_TOOL_AUTHORIZATION", repr(perms))
        for caps in ("cap_a", 5, ["Bad"], ["cap_a\n"], [None], {"cap_a": 1}):
            res = self.reg.execute("guarded", {"q": 1}, ["network", "filesystem"], True, caps)
            self.assertEqual(res.outcome_code, "INVALID_TOOL_AUTHORIZATION", repr(caps))
        self.assertEqual(self.h.count, 0)

    def test_invalid_input_is_rejected_after_authorization(self):
        full = (["network", "filesystem"], True, ["cap_a", "cap_b"])
        for bad in (None, [], "s", 5, {1: 2}, {"a": (1,)}, {"a": float("inf")}, {"a": object()}):
            res = self.reg.execute("guarded", bad, *full)
            self.assertEqual((res.outcome_code, res.execution_status), ("INVALID_TOOL_INPUT", "input_rejected"), repr(bad))
            self.assertTrue(res.authorization_accepted)
        self.assertEqual(self.h.count, 0)
        # ...and authorization is judged first: bad input with no grants is an authorization failure
        self.assertEqual(self.reg.execute("guarded", None).outcome_code, "TOOL_PERMISSION_DENIED")

    def test_authorization_is_never_remembered_between_calls(self):
        self.assertTrue(self.run_req(["network", "filesystem"], ["cap_a", "cap_b"], True).ok)
        self.assertEqual(self.run_req().outcome_code, "TOOL_PERMISSION_DENIED")
        self.assertEqual(self.run_req(["network", "filesystem"], ["cap_a", "cap_b"], False).outcome_code, "TOOL_CONFIRMATION_REQUIRED")
        self.assertEqual(self.run_req(["network", "filesystem"], [], True).outcome_code, "TOOL_CAPABILITY_MISSING")
        self.assertEqual(self.h.count, 1)

    def test_one_tools_grants_do_not_carry_to_another_tool(self):
        other = ForbiddenHandler()
        self.reg.register(spec("other_net", other, permissions=["network"]))
        self.assertTrue(self.run_req(["network", "filesystem"], ["cap_a", "cap_b"], True).ok)
        self.assertEqual(self.reg.execute_request(make_request("other_net")).outcome_code, "TOOL_PERMISSION_DENIED")

    def test_forged_requests_cannot_bypass_the_registry(self):
        gated = ForbiddenHandler()
        self.reg.register(spec("gated_net", gated, permissions=["network"]))
        cases = {
            "unfilled slots": (object.__new__(ToolRequest), "INVALID_TOOL_REQUEST"),
            "no grants": (forged(name="gated_net", input={}, granted_permissions=(), granted_capabilities=(), confirmed=False),
                          "TOOL_PERMISSION_DENIED"),
            "string grants": (forged(name="gated_net", input={}, granted_permissions="network", granted_capabilities=(),
                                     confirmed=True), "INVALID_TOOL_AUTHORIZATION"),
            "bogus grant": (forged(name="gated_net", input={}, granted_permissions=("bogus",), granted_capabilities=(),
                                   confirmed=True), "INVALID_TOOL_AUTHORIZATION"),
            "non-bool confirmation": (forged(name="gated_net", input={}, granted_permissions=("network",),
                                             granted_capabilities=(), confirmed="yes"), "INVALID_TOOL_AUTHORIZATION"),
            "non-dict input": (forged(name="gated_net", input=[1], granted_permissions=("network",), granted_capabilities=(),
                                      confirmed=False), "INVALID_TOOL_INPUT"),
            "non-json input": (forged(name="gated_net", input={"a": object()}, granted_permissions=("network",),
                                      granted_capabilities=(), confirmed=False), "INVALID_TOOL_INPUT"),
            "unknown name": (forged(name="ghost", input={}, granted_permissions=(), granted_capabilities=(), confirmed=False),
                             "UNKNOWN_TOOL"),
            "non-str name": (forged(name=["gated_net"], input={}, granted_permissions=("network",), granted_capabilities=(),
                                    confirmed=False), "UNKNOWN_TOOL"),
        }
        for label, (request, code) in cases.items():
            res = self.reg.execute_request(request)
            self.assertEqual(res.outcome_code, code, label)
            self.assertFalse(res.handler_called, label)
        self.assertEqual(gated.count, 0)

    def test_non_request_objects_are_rejected(self):
        class Duck:
            def to_registry_arguments(self):
                return {"name": "guarded", "tool_input": {}, "granted_permissions": ["network", "filesystem"],
                        "confirmed": True, "granted_capabilities": ["cap_a", "cap_b"]}
        before = self.reg.invocation_count()
        junk = [None, "guarded", 5, {}, [], {"name": "guarded"}, ToolRequest, Duck(), object(), make_request("guarded").to_dict(),
                make_request("guarded").to_registry_arguments()]
        for i, obj in enumerate(junk, 1):
            res = self.reg.execute_request(obj)
            self.assertEqual((res.outcome_code, res.execution_status, res.handler_called, res.tool_name),
                             ("INVALID_TOOL_REQUEST", "tool_rejected", False, None), repr(obj))
            self.assertEqual(self.reg.invocation_count(), before + i)
        self.assertEqual(self.h.count, 0)

    def test_preflight_agrees_with_execution_for_every_pre_handler_rejection(self):
        cases = [("guarded", {"q": 1}, None, False, None), ("guarded", {"q": 1}, ["network", "filesystem"], False, None),
                 ("guarded", {"q": 1}, ["network", "filesystem"], True, None),
                 ("guarded", None, ["network", "filesystem"], True, ["cap_a", "cap_b"]), ("ghost", {}, None, False, None),
                 ("guarded", {}, "network", False, None)]
        for name, tool_input, perms, confirmed, caps in cases:
            pre = self.reg.preflight(name, tool_input, perms, confirmed, caps)
            self.assertIsInstance(pre, ToolPreflightResult)
            res = self.reg.execute(name, tool_input, perms, confirmed, caps)
            self.assertEqual(pre.outcome_code, res.outcome_code)
            self.assertFalse(pre.ok)
        self.assertEqual(self.h.count, 0)

    def test_preflight_never_calls_handler_or_audits(self):
        before = self.reg.invocation_count()
        pre = self.reg.preflight("guarded", {"q": 1}, ["network", "filesystem"], True, ["cap_a", "cap_b"])
        self.assertTrue(pre.ok)
        self.assertEqual((self.h.count, self.reg.invocation_count()), (0, before))


class T06HandlerCalledAtMostOnceAndOnlyAfterPreconditions(unittest.TestCase):
    def test_exactly_one_handler_call_site_in_the_registry(self):
        tree = ast.parse(inspect.getsource(mod))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and (
            (isinstance(n.func, ast.Name) and n.func.id == "handler")
            or (isinstance(n.func, ast.Attribute) and n.func.attr == "handler")
            or (isinstance(n.func, ast.Subscript) and isinstance(n.func.slice, ast.Constant) and n.func.slice.value == "handler"))]
        self.assertEqual(len(calls), 1)
        # ...and it lives inside _invoke, after the failure return
        func = next(f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == "_invoke")
        self.assertIn(calls[0], list(ast.walk(func)))

    def test_call_counts_for_every_outcome_kind(self):
        sc = Scenario()
        called = {"success": 1, "typed_ok": 1, "net_granted": 1, "net_denied": 0, "confirm_missing": 0, "cap_missing": 0,
                  "disabled": 0, "unknown": 0, "handler_exc": 1, "bad_output": 1, "wrong_type": 1, "invalid_request": 0,
                  "invalid_authorization": 0, "invalid_input": 0, "success_after_all": 1}
        for label, code, status, key, res in sc.run_all():
            self.assertEqual(res.handler_called, bool(called[label]), label)
        self.assertEqual({k: v.count for k, v in sc.h.items()},
                         {"ok": 2, "net": 1, "confirm": 0, "both": 0, "cap": 0, "disabled": 0, "raise": 1, "badout": 1,
                          "typed_bad": 1, "typed_ok": 1, "big": 0})

    def test_evaluate_runs_before_the_handler_and_gates_it(self):
        log = []
        h = Handler(fn=lambda i: log.append("handler") or {"ok": 1})

        class Watch(InProcessToolRegistry):
            def _evaluate(self, *a, **k):
                log.append("evaluate")
                return super()._evaluate(*a, **k)

        reg = Watch()
        reg.register(spec("watched", h, permissions=["network"]))
        reg.execute_request(make_request("watched"))
        self.assertEqual(log, ["evaluate"])
        reg.execute_request(make_request("watched", perms=["network"]))
        self.assertEqual(log, ["evaluate", "evaluate", "handler"])
        reg.preflight("watched", {}, ["network"])
        self.assertEqual(log[-1], "evaluate")
        self.assertEqual(h.count, 1)

    def test_handler_never_retried_after_failure(self):
        for fn, value in ((lambda i: 1 / 0, None), (None, {1: "bad key"}), (None, float("nan")), (None, object())):
            h = Handler(fn=fn, value=value)
            reg = make_registry(spec("flaky", h))
            res = reg.execute_request(make_request("flaky"))
            self.assertEqual((res.execution_status, h.count, reg.invocation_count()), ("handler_failed", 1, 1))

    def test_same_request_twice_is_two_independent_executions(self):
        h = Handler()
        reg = make_registry(spec("twice", h))
        r = make_request("twice")
        a, b = reg.execute_request(r), reg.execute_request(r)
        self.assertEqual((h.count, a.sequence, b.sequence, reg.invocation_count()), (2, 1, 2, 2))

    def test_reentrant_handler_keeps_sequences_and_results_consistent(self):
        reg = InProcessToolRegistry()
        reg.register(spec("inner", Handler(value={"who": "inner"})))
        reg.register(spec("outer", Handler(fn=lambda i: {"nested": reg.execute_request(make_request("inner")).to_dict()})))
        res = reg.execute_request(make_request("outer"))
        history = reg.get_invocation_history()
        self.assertEqual([(r["sequence"], r["tool_name"]) for r in history], [(1, "inner"), (2, "outer")])
        self.assertEqual((res.sequence, res.tool_name), (2, "outer"))
        self.assertEqual(res.output["nested"]["sequence"], 1)
        self.assertEqual(history[1]["output"], res.output)


class T07ValidOutputReachesOutputValidation(unittest.TestCase):
    def test_output_goes_through_normalize_and_type_check(self):
        raw = {"a": [1, 2, {"b": None}]}
        h = Handler(value=raw)
        reg = make_registry(spec("norm", h, output_type="object"))
        seen_norm, seen_type = [], []
        real_norm, real_type = mod.normalize_tool_output, mod.output_matches_type
        with mock.patch.object(mod, "normalize_tool_output", side_effect=lambda v: (seen_norm.append(v), real_norm(v))[1]), \
                mock.patch.object(mod, "output_matches_type", side_effect=lambda v, t: (seen_type.append((v, t)), real_type(v, t))[1]):
            res = reg.execute_request(make_request("norm"))
        self.assertTrue(res.ok)
        self.assertTrue(any(v is raw for v in seen_norm))
        self.assertEqual(seen_type, [({"a": [1, 2, {"b": None}]}, "object")])

    def test_output_is_a_fresh_plain_json_copy(self):
        class D(dict):
            pass

        class L(list):
            pass

        class S(str):
            pass

        raw = D(a=L([1, S("x")]), b=D(c=None))
        reg = make_registry(spec("plain", Handler(value=raw)))
        res = reg.execute_request(make_request("plain"))
        self.assertEqual(res.output, {"a": [1, "x"], "b": {"c": None}})
        self.assertIs(type(res.output), dict)
        self.assertIs(type(res.output["a"]), list)
        self.assertIs(type(res.output["a"][1]), str)
        self.assertIsNot(res.output, raw)
        self.assertIsNot(reg.get_invocation_history()[0]["output"], res.output)

    def test_output_key_order_is_preserved(self):
        reg = make_registry(spec("ordered", Handler(value={"z": 1, "a": 2, "m": 3})))
        self.assertEqual(list(reg.execute_request(make_request("ordered")).output), ["z", "a", "m"])

    def test_declared_output_type_accepts_matching_values(self):
        cases = {"object": {"a": 1}, "array": [1], "string": "s", "number": 1.5, "integer": 3, "boolean": False, "null": None}
        for output_type, value in cases.items():
            reg = make_registry(spec("typed", Handler(value=value) if value is not None else Handler(fn=lambda i: None),
                                     output_type=output_type))
            res = reg.execute_request(make_request("typed"))
            self.assertTrue(res.ok, output_type)
            self.assertEqual(res.output, value)
        self.assertTrue(make_registry(spec("n", Handler(value=3), output_type="number")).execute_request(make_request("n")).ok)

    def test_declared_output_type_rejects_mismatches_without_exposing_output(self):
        cases = [("integer", True), ("integer", 1.5), ("number", True), ("number", "1"), ("string", 1), ("object", [1]),
                 ("array", {"a": 1}), ("boolean", 0), ("null", 0), ("null", {})]
        for output_type, value in cases:
            reg = make_registry(spec("typed", Handler(value=value), output_type=output_type))
            res = reg.execute_request(make_request("typed"))
            self.assertEqual((res.execution_status, res.outcome_code, res.handler_called, res.output_available, res.output),
                             ("output_invalid", "TOOL_OUTPUT_VALIDATION_FAILED", True, False, None), (output_type, value))
            self.assertEqual(res.failures[0]["expected_type"], output_type)
            self.assertNotIn("output", reg.get_invocation_history()[0]["failures"][0])

    def test_no_declared_type_means_no_type_check(self):
        for value in (1, "s", [1], None, {"a": 1}, True):
            reg = make_registry(spec("free", Handler(fn=lambda i, v=value: v)))
            self.assertTrue(reg.execute_request(make_request("free")).ok)


class T08InvalidHandlerOutput(unittest.TestCase):
    def check(self, value):
        h = Handler(fn=lambda i: value)
        reg = make_registry(spec("bad_out", h, output_type="object"))
        res = reg.execute_request(make_request("bad_out"))
        rec = reg.get_invocation_history()[0]
        self.assertEqual((res.execution_status, res.outcome_code, res.handler_called, res.output_available, res.output, res.ok),
                         ("handler_failed", "TOOL_OUTPUT_INVALID", True, False, None, False))
        self.assertEqual((rec["status"], rec["outcome_code"], rec["output_available"], rec["output"], rec["ok"]),
                         ("failed", "TOOL_OUTPUT_INVALID", False, None, False))
        self.assertEqual(h.count, 1)
        return res

    def test_non_json_values(self):
        cyclic_list = []
        cyclic_list.append(cyclic_list)
        cyclic_dict = {}
        cyclic_dict["me"] = cyclic_dict
        for value in ((1, 2), {1, 2}, frozenset(), b"bytes", bytearray(b"x"), object(), len, lambda: 1, float("nan"),
                      float("inf"), float("-inf"), {1: "int key"}, {("t",): 1}, {"a": (1,)}, {"a": {1}}, 1 + 2j, range(3),
                      cyclic_list, cyclic_dict, nested_dict(mod.MAX_OUTPUT_DEPTH + 2)):
            self.check(value)

    def test_failure_detail_is_documented_shape(self):
        res = self.check((1,))
        self.assertEqual(list(f["code"] for f in res.failures), ["TOOL_OUTPUT_INVALID"])
        self.assertEqual(set(res.failures[0]), {"code", "message"})

    def test_non_json_output_does_not_leak_into_result_or_audit(self):
        marker = object()
        h = Handler(fn=lambda i: {"a": marker})
        reg = make_registry(spec("leak", h))
        res = reg.execute_request(make_request("leak"))
        self.assertNotIn("object at", repr(res.to_dict()))
        self.assertNotIn("object at", repr(reg.get_invocation_history()))

    def test_depth_boundary_matches_documented_limit(self):
        limit = mod.MAX_OUTPUT_DEPTH
        self.assertTrue(normalize_tool_output(nested_dict(limit + 1))[0])
        self.assertFalse(normalize_tool_output(nested_dict(limit + 2))[0])

    def test_registry_remains_usable_after_invalid_output(self):
        reg = make_registry(spec("bad", Handler(value=(1,))), spec("good"))
        reg.execute_request(make_request("bad"))
        self.assertTrue(reg.execute_request(make_request("good")).ok)
        self.assertEqual([r["sequence"] for r in reg.get_invocation_history()], [1, 2])


class T09HandlerExceptions(unittest.TestCase):
    def run_exc(self, exc):
        h = Handler(fn=lambda i: (_ for _ in ()).throw(exc))
        reg = make_registry(spec("raiser", h))
        return reg, h, reg.execute_request(make_request("raiser"))

    def test_exceptions_become_documented_failure_result(self):
        class Custom(Exception):
            pass

        for exc in (RuntimeError("boom"), ValueError(), KeyError("k"), ZeroDivisionError("z"), Custom("c"), OSError("io"),
                    RecursionError("deep"), AssertionError("a"), StopIteration(), Exception()):
            reg, h, res = self.run_exc(exc)
            self.assertEqual((res.execution_status, res.outcome_code, res.handler_called, res.output_available, res.output),
                             ("handler_failed", "TOOL_HANDLER_EXCEPTION", True, False, None), repr(exc))
            self.assertEqual(res.failures[0]["exception_type"], type(exc).__name__)
            self.assertFalse(res.ok)
            self.assertEqual(h.count, 1)
            rec = reg.get_invocation_history()[0]
            self.assertEqual((rec["status"], rec["outcome_code"], rec["handler_called"], rec["output_available"]),
                             ("failed", "TOOL_HANDLER_EXCEPTION", True, False))

    def test_long_message_is_truncated_and_hostile_str_is_survived(self):
        _, _, res = self.run_exc(RuntimeError("x" * 5000))
        self.assertEqual(len(res.failures[0]["exception_message"]), 500)

        class Hostile(Exception):
            def __str__(self):
                raise ValueError("no str for you")

        _, _, res = self.run_exc(Hostile())
        self.assertEqual((res.outcome_code, res.failures[0]["exception_message"]), ("TOOL_HANDLER_EXCEPTION", ""))

    def test_registry_remains_usable_and_history_intact_after_exception(self):
        reg, h, _ = self.run_exc(RuntimeError("boom"))
        reg.register(spec("fine"))
        self.assertTrue(reg.execute_request(make_request("fine")).ok)
        self.assertEqual([(r["sequence"], r["outcome_code"]) for r in reg.get_invocation_history()],
                         [(1, "TOOL_HANDLER_EXCEPTION"), (2, "TOOL_COMPLETED")])

    def test_exception_result_carries_no_traceback_object_or_handler(self):
        _, _, res = self.run_exc(RuntimeError("boom"))
        for value in res.to_dict().values():
            self.assertFalse(callable(value) or isinstance(value, BaseException))
        self.assertEqual(set(res.failures[0]), {"code", "message", "exception_type", "exception_message"})


class T10T11AuditRecordsAndResultsAgree(unittest.TestCase):
    def setUp(self):
        self.sc = Scenario()
        self.runs = self.sc.run_all()
        self.history = self.sc.reg.get_invocation_history()

    def test_exactly_one_record_per_returned_execution_in_order(self):
        self.assertEqual(len(self.history), len(self.runs))
        self.assertEqual(self.sc.reg.invocation_count(), len(self.runs))
        self.assertEqual([r["sequence"] for r in self.history], list(range(1, len(self.runs) + 1)))
        self.assertEqual([res.sequence for *_, res in self.runs], list(range(1, len(self.runs) + 1)))

    def test_every_outcome_kind_has_the_expected_code_and_status(self):
        for i, (label, code, status, key, res) in enumerate(self.runs):
            rec = self.history[i]
            self.assertEqual((res.outcome_code, res.execution_status), (code, status), label)
            self.assertEqual(rec["outcome_code"], code, label)
            self.assertEqual(rec["status"], STATUS_PAIRING[status], label)

    def test_result_and_record_agree_field_by_field(self):
        for i, (label, code, status, key, res) in enumerate(self.runs):
            rec = self.history[i]
            self.assertEqual(set(rec), RECORD_KEYS)
            self.assertEqual(set(res.to_dict()), RESULT_KEYS)
            self.assertEqual(res.tool_name, rec["tool_name"], label)
            self.assertEqual(res.outcome_code, rec["outcome_code"], label)
            self.assertEqual(res.handler_called, rec["handler_called"], label)
            self.assertEqual(res.output_available, rec["output_available"], label)
            self.assertEqual(res.output, rec["output"], label)
            self.assertEqual(res.failures, rec["failures"], label)
            self.assertEqual(res.sequence, rec["sequence"], label)
            self.assertEqual(res.authorization_decision, rec["authorization_decision"], label)
            self.assertEqual(res.ok, rec["ok"], label)
            self.assertEqual(res.ok, res.execution_status == "succeeded", label)
            self.assertEqual(res.output_available, res.ok, label)
            self.assertEqual(res.output is not None or not res.ok, True, label)
            self.assertEqual(res.authorization_accepted, rec["authorization_decision"] in ("accepted", "not_required"), label)
            self.assertEqual(rec["authorization_code"] is None, res.execution_status not in ("authorization_rejected",), label)

    def test_handler_called_matches_the_real_handler_call_count(self):
        per_tool = {}
        for (label, code, status, key, res), rec in zip(self.runs, self.history):
            if key is not None:
                per_tool[key] = per_tool.get(key, 0) + int(rec["handler_called"])
        for key, handler in self.sc.h.items():
            self.assertEqual(handler.count, per_tool.get(key, 0), key)

    def test_failures_are_empty_exactly_when_succeeded(self):
        for (label, *_rest, res), rec in zip(self.runs, self.history):
            self.assertEqual(bool(res.failures), not res.ok, label)
            self.assertEqual(rec["failures"] == [], rec["ok"], label)

    def test_rejected_before_handler_records_have_no_output_and_no_handler(self):
        for (label, code, status, key, res), rec in zip(self.runs, self.history):
            if status in ("authorization_rejected", "input_rejected", "tool_rejected"):
                self.assertEqual((rec["handler_called"], rec["output_available"], rec["output"], rec["status"]),
                                 (False, False, None, "rejected"), label)

    def test_authorization_fields_are_recorded_as_supplied(self):
        reg = make_registry(spec("auth", permissions=["network", "user_confirmation"], capabilities=["c2", "c1"]))
        reg.execute_request(make_request("auth", {"q": 1}, ["user_confirmation", "network", "network"], ["c1", "c2", "c9"], True))
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["required_permissions"], rec["granted_permissions"], rec["confirmed"]),
                         (["network", "user_confirmation"], ["network", "user_confirmation"], True))
        self.assertEqual((rec["required_capabilities"], rec["granted_capabilities"]), (["c1", "c2"], ["c1", "c2", "c9"]))
        self.assertEqual((rec["authorization_decision"], rec["authorization_code"]), ("accepted", None))

    def test_input_is_audited_as_the_callers_original_input(self):
        reg = make_registry(spec("mut", Handler(fn=lambda i: i.update({"mutated": True}) or {"ok": 1})))
        reg.execute_request(make_request("mut", {"q": [1, 2]}))
        self.assertEqual(reg.get_invocation_history()[0]["input"], {"q": [1, 2]})

    def test_invalid_request_record_shape(self):
        reg = InProcessToolRegistry()
        res = reg.execute_request(None)
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["tool_name"], rec["input"], rec["input_json_safe"], rec["input_type"], rec["handler_called"],
                          rec["outcome_code"], rec["status"], rec["authorization_decision"]),
                         (None, None, False, "NoneType", False, "INVALID_TOOL_REQUEST", "rejected", "not_evaluated"))
        self.assertEqual((res.sequence, res.tool_name, res.authorization_accepted), (1, None, False))

    def test_every_outcome_code_maps_to_exactly_one_execution_status(self):
        table = mod._EXEC_STATUS_BY_CODE
        produced = {code for _, code, *_ in self.runs}
        self.assertTrue(produced <= set(table))
        self.assertEqual(set(table.values()), set(STATUS_PAIRING))
        for name in dir(mod):
            value = getattr(mod, name)
            if name.startswith("TOOL_") and isinstance(value, str) and value.isupper() and value not in (
                    "TOOL_PREFLIGHT_PASSED",) and not value.startswith(("INVALID_TOOL_SPEC", "DUPLICATE_TOOL_NAME")):
                if value in {"TOOL_COMPLETED", "TOOL_HANDLER_EXCEPTION", "TOOL_OUTPUT_INVALID", "TOOL_OUTPUT_VALIDATION_FAILED",
                             "TOOL_PERMISSION_DENIED", "TOOL_CONFIRMATION_REQUIRED", "TOOL_CAPABILITY_MISSING",
                             "TOOL_DISABLED"}:
                    self.assertIn(value, table, name)

    def test_history_reads_are_pure(self):
        a, b = self.sc.reg.get_invocation_history(), self.sc.reg.get_invocation_history()
        self.assertEqual(a, b)
        self.assertEqual(self.sc.reg.invocation_count(), len(a))


class T12Isolation(unittest.TestCase):
    def test_caller_input_mutated_after_execution_does_not_change_audit(self):
        data = {"a": [1, {"b": 2}]}
        reg = make_registry(spec("iso"))
        reg.execute("iso", data)
        data["a"].append("late")
        data["b"] = 1
        self.assertEqual(reg.get_invocation_history()[0]["input"], {"a": [1, {"b": 2}]})

    def test_handler_mutation_of_its_input_does_not_reach_caller_request_or_audit(self):
        def mutate(tool_input):
            tool_input["injected"] = True
            tool_input["a"].append("x")
            tool_input["a"][1]["b"] = "changed"
            return {"ok": 1}

        data = {"a": [1, {"b": 2}]}
        request = make_request("mut_in", data)
        reg = make_registry(spec("mut_in", Handler(fn=mutate)))
        reg.execute_request(request)
        reg.execute("mut_in", data)
        self.assertEqual(data, {"a": [1, {"b": 2}]})
        self.assertEqual(request.input, {"a": [1, {"b": 2}]})
        self.assertEqual([r["input"] for r in reg.get_invocation_history()], [{"a": [1, {"b": 2}]}] * 2)

    def test_handler_input_is_a_private_copy_per_call(self):
        h = Handler()
        reg = make_registry(spec("priv", h))
        request = make_request("priv", {"a": [1]})
        reg.execute_request(request), reg.execute_request(request)
        self.assertIsNot(h.calls[0], h.calls[1])
        self.assertIsNot(h.calls[0]["a"], h.calls[1]["a"])

    def test_handler_keeping_its_output_reference_cannot_alter_result_or_audit(self):
        kept = {"items": [1, 2]}
        reg = make_registry(spec("keep", Handler(value=kept)))
        res = reg.execute_request(make_request("keep"))
        kept["items"].append(3)
        kept["late"] = True
        self.assertEqual(res.output, {"items": [1, 2]})
        self.assertEqual(reg.get_invocation_history()[0]["output"], {"items": [1, 2]})

    def test_mutating_results_never_changes_history(self):
        reg = make_registry(spec("res", Handler(value={"items": [1]})), spec("net", permissions=["network"]))
        res = reg.execute_request(make_request("res"))
        res.output["items"].append(2), res.failures.append({"x": 1})
        res.to_dict()["output"]["items"].append(3)
        denied = reg.execute_request(make_request("net"))
        denied.failures[0]["message"] = "tampered"
        denied.failures[0].setdefault("missing_permissions", []).append("zzz")
        history = reg.get_invocation_history()
        self.assertEqual(history[0]["output"], {"items": [1]})
        self.assertNotEqual(history[1]["failures"][0]["message"], "tampered")
        self.assertEqual(history[1]["failures"][0]["missing_permissions"], ["network"])

    def test_mutating_an_invoke_result_never_changes_the_audit_record(self):
        reg = make_registry(spec("inv", Handler(value={"items": [1]}), permissions=["network"]))
        ok = reg.invoke("inv", {"a": [1]}, ["network"])
        ok.output["items"].append(2)
        ok.failures.append({"code": "X"})
        denied = reg.invoke("inv", {"a": [1]})
        denied.failures[0]["message"] = "tampered"
        denied.authorization["granted_permissions"].append("network")
        history = reg.get_invocation_history()
        self.assertEqual(history[0]["output"], {"items": [1]})
        self.assertEqual(history[0]["failures"], [])
        self.assertNotEqual(history[1]["failures"][0]["message"], "tampered")
        self.assertEqual(history[1]["granted_permissions"], [])

    def test_mutating_history_dicts_never_changes_registry_history(self):
        reg = make_registry(spec("hist", Handler(value={"items": [1]})))
        reg.execute_request(make_request("hist", {"a": [1]}))
        h = reg.get_invocation_history()
        h[0]["output"]["items"].append(2), h[0]["input"]["a"].append(2), h[0]["failures"].append(1)
        h[0]["status"] = "tampered"
        h.append({"junk": 1}), h.clear()
        again = reg.get_invocation_history()
        self.assertEqual((len(again), again[0]["status"], again[0]["output"], again[0]["input"]),
                         (1, "completed", {"items": [1]}, {"a": [1]}))
        self.assertEqual(reg.invocation_count(), 1)

    def test_describe_and_listings_are_copies(self):
        reg = make_registry(ToolSpec(name="desc", description="d", handler=Handler(), input_schema={"p": [1]},
                                     output_description="o"))
        reg.describe("desc")["input_schema"]["p"].append(2)
        reg.list_descriptions()[0]["input_schema"]["p"].append(3)
        reg.list_names().append("junk")
        reg.get_required_permissions("desc").append("network")
        reg.get_required_capabilities("desc").append("c")
        self.assertEqual(reg.describe("desc")["input_schema"], {"p": [1]})
        self.assertEqual((reg.list_names(), reg.get_required_permissions("desc"), reg.get_required_capabilities("desc")),
                         (["desc"], [], []))

    def test_request_grants_are_isolated_from_caller_and_from_execution(self):
        perms, caps = ["network"], ["c"]
        request = make_request("iso2", {}, perms, caps)
        reg = make_registry(spec("iso2", permissions=["network"], capabilities=["c"]))
        args = request.to_registry_arguments()
        args["granted_permissions"].append("filesystem")
        perms.clear(), caps.clear()
        self.assertTrue(reg.execute_request(request).ok)
        self.assertEqual(request.granted_permissions, ("network",))

    def test_dict_subclass_with_hooks_cannot_leak_into_or_run_inside_the_handler(self):
        hooks = []

        class Hooked(dict):
            def __deepcopy__(self, memo):
                hooks.append("deepcopy")
                return self

            def __iter__(self):
                hooks.append("iter")
                return super().__iter__()

            def items(self):
                hooks.append("items")
                return super().items()

            def keys(self):
                hooks.append("keys")
                return super().keys()

            def __getitem__(self, key):
                hooks.append("getitem")
                return super().__getitem__(key)

        class HookedList(list):
            def __iter__(self):
                hooks.append("list_iter")
                return super().__iter__()

            def __deepcopy__(self, memo):
                hooks.append("list_deepcopy")
                return self

        caller = Hooked(a=HookedList([1, 2]))
        h = Handler()
        reg = make_registry(spec("hooked", h))
        res = reg.execute("hooked", caller)
        self.assertTrue(res.ok)
        self.assertEqual(hooks, [])
        received = h.calls[0]
        self.assertIs(type(received), dict)
        self.assertIs(type(received["a"]), list)
        self.assertIsNot(received, caller)
        self.assertIsNot(received["a"], dict.__getitem__(caller, "a"))
        self.assertEqual(hooks, [])
        # a request built from the same object is equally immune
        request = make_request("hooked", caller)
        self.assertEqual(hooks, [])
        self.assertIs(type(request.input), dict)

    def test_str_subclass_hooks_are_not_run(self):
        ran = []

        class S(str):
            def __str__(self):
                ran.append("str")
                return "hostile"

            def __hash__(self):
                ran.append("hash")
                return 1

        reg = make_registry(spec("strs", Handler(fn=lambda i: {"v": S("out")})))
        res = reg.execute("strs", {"k": S("in")})
        self.assertEqual((res.output, ran), ({"v": "out"}, []))


class T13RejectedRequestsNeverCallTheHandler(unittest.TestCase):
    def test_every_rejection_kind_through_every_entry_point(self):
        h = ForbiddenHandler()
        reg = make_registry(spec("gate", h, permissions=["network", "user_confirmation"], capabilities=["c"]),
                            spec("off", h, enabled=False))
        request_variants = [make_request("gate"), make_request("gate", perms=["network"]),
                            make_request("gate", perms=["network"], confirmed=True), make_request("off"),
                            make_request("missing")]
        for r in request_variants:
            res = reg.execute_request(r)
            self.assertFalse(res.handler_called)
            self.assertFalse(res.ok)
            args = r.to_registry_arguments()
            self.assertFalse(reg.execute(**args).handler_called)
            self.assertFalse(reg.invoke(**args).handler_called)
            self.assertFalse(reg.preflight(**args).ok)
        for bad in (None, 5, "x", {}, object(), forged()):
            self.assertFalse(reg.execute_request(bad).handler_called)
        self.assertEqual(reg.execute("gate", "bad", "bad", "bad", "bad").outcome_code, "INVALID_TOOL_AUTHORIZATION")
        self.assertEqual(h.count, 0)

    def test_rejections_are_audited_but_leave_no_other_trace(self):
        h = ForbiddenHandler()
        reg = make_registry(spec("gate", h, permissions=["network"]))
        for _ in range(3):
            reg.execute_request(make_request("gate"))
        self.assertEqual(reg.invocation_count(), 3)
        self.assertTrue(all(r["status"] == "rejected" and not r["handler_called"] for r in reg.get_invocation_history()))
        self.assertEqual((len(reg), reg.list_names(), reg.is_enabled("gate")), (1, ["gate"], True))


class T14NoHiddenStateSelectionRetryPersistenceOrBackgroundWork(unittest.TestCase):
    PUBLIC = {"register", "has", "is_enabled", "is_invokable", "enable", "disable", "describe", "list_names",
              "list_descriptions", "get_required_permissions", "get_output_type", "get_required_capabilities", "preflight",
              "invoke", "execute", "execute_request", "get_invocation_history", "invocation_count"}
    FORBIDDEN_IMPORTS = {"os", "sys", "io", "pathlib", "shutil", "tempfile", "sqlite3", "shelve", "pickle", "json", "socket",
                         "ssl", "http", "urllib", "requests", "subprocess", "threading", "multiprocessing", "concurrent",
                         "asyncio", "sched", "time", "datetime", "random", "uuid", "atexit", "signal", "logging", "importlib"}

    def test_registry_state_is_exactly_entries_and_history(self):
        reg = make_registry(spec("state", permissions=["network"], capabilities=["c"]))
        before = set(vars(reg))
        reg.execute_request(make_request("state", perms=["network"], caps=["c"], confirmed=True))
        reg.execute_request(make_request("state"))
        self.assertEqual(before, {"_entries", "_history"})
        self.assertEqual(set(vars(reg)), {"_entries", "_history"})
        self.assertEqual(set(reg._entries["state"]), {"description", "handler", "input_schema", "output_description", "enabled",
                                                       "permissions", "capabilities", "output_type"})

    def test_public_surface_has_no_select_retry_schedule_persist_or_grant_methods(self):
        public = {n for n, v in inspect.getmembers(InProcessToolRegistry, callable) if not n.startswith("_")}
        self.assertEqual(public, self.PUBLIC)
        for word in ("retry", "select", "choose", "auto", "schedule", "queue", "save", "load", "persist", "grant", "remember",
                     "background", "run_all", "batch", "plan"):
            self.assertFalse([n for n in public if word in n], word)

    def test_no_tool_is_selected_or_substituted_automatically(self):
        h = Handler()
        reg = make_registry(spec("only_tool", h))
        for name in ("only_tol", "Only_Tool", "tool", "only-tool", "only_tool2", "only_tool ", "only_tool\n"):
            res = reg.execute(name, {})
            self.assertEqual(res.outcome_code, "UNKNOWN_TOOL", repr(name))
        self.assertEqual(h.count, 0)

    def test_authorization_state_never_persists_on_registry_or_request(self):
        reg = make_registry(spec("net", permissions=["network"]))
        request = make_request("net", perms=["network"])
        self.assertTrue(reg.execute_request(request).ok)
        self.assertEqual(reg.execute("net", {}).outcome_code, "TOOL_PERMISSION_DENIED")
        self.assertEqual(request.granted_permissions, ("network",))
        self.assertTrue(reg.execute_request(request).ok)
        self.assertEqual(set(vars(reg)), {"_entries", "_history"})

    def test_no_module_level_mutable_state(self):
        for module in (mod, req_mod):
            tree = ast.parse(inspect.getsource(module))
            for node in tree.body:
                if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Dict, ast.Set, ast.ListComp,
                                                                            ast.DictComp, ast.SetComp)):
                    # only read-only ALL-CAPS lookup tables (e.g. _EXEC_STATUS_BY_CODE) may be module-level containers
                    for target in node.targets:
                        self.assertRegex(target.id, r"^_?[A-Z][A-Z0-9_]*$", ast.dump(node)[:120])

    def test_section5_modules_import_nothing_that_could_do_io_retry_or_schedule(self):
        base = os.path.join(PY_ROOT, "tools")
        for filename in ("in_process_tool_registry.py", "tool_request.py", "tool_definition.py", "tool_registry.py"):
            with open(os.path.join(base, filename), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                roots = []
                if isinstance(node, ast.Import):
                    roots = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    roots = [node.module.split(".")[0]]
                for root in roots:
                    self.assertNotIn(root, self.FORBIDDEN_IMPORTS, f"{filename} imports {root}")
                    self.assertIn(root, {"copy", "math", "re", "tools"}, f"{filename} imports {root}")

    def test_section5_is_not_referenced_from_outside_the_tools_package_or_tests(self):
        offenders = []
        for dirpath, dirnames, filenames in os.walk(PY_ROOT):
            rel = os.path.relpath(dirpath, PY_ROOT)
            if rel.split(os.sep)[0] in ("tools", "tests"):
                continue
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        names = [("." * node.level) + (node.module or "")] + [a.name for a in node.names]
                    else:
                        continue
                    if any(re.match(r"^\.*tools(\.|$)", n) for n in names) or (
                            isinstance(node, ast.ImportFrom) and any(a.name in ("tools", "in_process_tool_registry",
                                                                                 "tool_request") for a in node.names)):
                        offenders.append(os.path.relpath(path, PY_ROOT))
        # Prompt 707: the caller-driven tool-step bridge is the single sanctioned consumer outside tools/; nothing else.
        # Prompt 719-A: plus the caller-side intent adapter, which imports only tools.tool_request (asserted by its own tests).
        self.assertEqual(sorted(set(offenders)), [os.path.join("agent", "tool_step_intent.py"), os.path.join("planning", "tool_step_bridge.py")])

    def test_full_run_does_no_io_network_subprocess_threading_or_sleep(self):
        boom = AssertionError("forbidden side effect")
        threads_before = threading.active_count()
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                with mock.patch("builtins.open", side_effect=boom), mock.patch("socket.socket", side_effect=boom), \
                        mock.patch("subprocess.Popen", side_effect=boom), mock.patch("threading.Thread.start", side_effect=boom), \
                        mock.patch("time.sleep", side_effect=boom), mock.patch("os.system", side_effect=boom):
                    runs = Scenario().run_all()
            finally:
                os.chdir(cwd)
            self.assertEqual(os.listdir(tmp), [])
        self.assertEqual(len(runs), 15)
        self.assertEqual(threading.active_count(), threads_before)

    def test_deterministic_across_fresh_registries(self):
        first, second = Scenario(), Scenario()
        a = [res.to_dict() for *_, res in first.run_all()]
        b = [res.to_dict() for *_, res in second.run_all()]
        self.assertEqual(a, b)
        self.assertEqual(first.reg.get_invocation_history(), second.reg.get_invocation_history())

    def test_no_activity_happens_without_an_explicit_call(self):
        h = ForbiddenHandler()
        reg = make_registry(spec("idle", h))
        r = make_request("idle")
        reg.enable("idle"), reg.disable("idle"), reg.enable("idle")
        reg.preflight(**r.to_registry_arguments())
        reg.describe("idle"), reg.list_descriptions(), reg.get_invocation_history()
        self.assertEqual((h.count, reg.invocation_count()), (0, 0))


class T15BackwardsCompatibility(unittest.TestCase):
    def test_public_signatures_are_unchanged(self):
        sig = lambda f: list(inspect.signature(f).parameters)
        self.assertEqual(sig(InProcessToolRegistry.register), ["self", "spec"])
        self.assertEqual(sig(InProcessToolRegistry.invoke),
                         ["self", "name", "tool_input", "granted_permissions", "confirmed", "granted_capabilities"])
        self.assertEqual(sig(InProcessToolRegistry.execute),
                         ["self", "name", "tool_input", "granted_permissions", "confirmed", "granted_capabilities"])
        self.assertEqual(sig(InProcessToolRegistry.preflight),
                         ["self", "name", "tool_input", "granted_permissions", "confirmed", "granted_capabilities"])
        self.assertEqual(sig(InProcessToolRegistry.execute_request), ["self", "request"])
        self.assertEqual(sig(ToolSpec.__init__), ["self", "name", "description", "handler", "input_schema", "output_description",
                                                  "enabled", "permissions", "capabilities", "output_type"])
        self.assertEqual(sig(create_tool_request),
                         ["name", "tool_input", "granted_permissions", "granted_capabilities", "confirmed"])
        for f in (InProcessToolRegistry.has, InProcessToolRegistry.enable, InProcessToolRegistry.disable,
                  InProcessToolRegistry.describe, InProcessToolRegistry.is_enabled, InProcessToolRegistry.is_invokable):
            self.assertEqual(sig(f), ["self", "name"])

    def test_legacy_two_argument_flow_still_works(self):
        h = Handler(value={"legacy": True})
        reg = InProcessToolRegistry()
        self.assertTrue(reg.register(ToolSpec("legacy", "d", h, {"type": "object"}, "o")).ok)
        res = reg.invoke("legacy", {"q": 1})
        self.assertEqual((res.ok, res.status, res.output, res.handler_called, res.tool_name), (True, "completed",
                                                                                                {"legacy": True}, True, "legacy"))
        ex = reg.execute("legacy", {"q": 1})
        self.assertEqual((ex.execution_status, ex.authorization_decision, ex.sequence), ("succeeded", "not_required", 2))
        self.assertEqual(reg.invoke("nope", {}).codes(), ["UNKNOWN_TOOL"])
        reg.disable("legacy")
        self.assertEqual(reg.invoke("legacy", {}).codes(), ["TOOL_DISABLED"])

    def test_direct_paths_and_request_path_give_the_same_audit_history(self):
        def run(kind):
            reg = make_registry(spec("same", Handler(value={"v": 1})))
            request = make_request("same", {"q": 1})
            if kind == "request":
                reg.execute_request(request)
            elif kind == "execute":
                reg.execute(**request.to_registry_arguments())
            else:
                reg.invoke(**request.to_registry_arguments())
            return reg.get_invocation_history()
        self.assertEqual(run("request"), run("execute"))
        self.assertEqual(run("request"), run("invoke"))

    def test_tool_spec_defaults_and_registry_documented_constants(self):
        s = ToolSpec()
        self.assertEqual((s.enabled, s.permissions, s.capabilities, s.output_type, s.input_schema), (True, [], [], None, {}))
        expected = {"STATUS_REGISTERED": "registered", "STATUS_INVOCATION_COMPLETED": "completed",
                    "STATUS_INVOCATION_FAILED": "failed", "STATUS_INVOCATION_REJECTED": "rejected",
                    "TOOL_COMPLETED": "TOOL_COMPLETED", "TOOL_UNKNOWN": "UNKNOWN_TOOL", "TOOL_DISABLED": "TOOL_DISABLED",
                    "TOOL_INVALID_INPUT": "INVALID_TOOL_INPUT", "TOOL_HANDLER_EXCEPTION": "TOOL_HANDLER_EXCEPTION",
                    "TOOL_OUTPUT_INVALID": "TOOL_OUTPUT_INVALID", "TOOL_PERMISSION_DENIED": "TOOL_PERMISSION_DENIED",
                    "TOOL_CONFIRMATION_REQUIRED": "TOOL_CONFIRMATION_REQUIRED",
                    "TOOL_INVALID_AUTHORIZATION": "INVALID_TOOL_AUTHORIZATION",
                    "TOOL_CAPABILITY_MISSING": "TOOL_CAPABILITY_MISSING",
                    "TOOL_OUTPUT_VALIDATION_FAILED": "TOOL_OUTPUT_VALIDATION_FAILED",
                    "TOOL_INVALID_REQUEST": "INVALID_TOOL_REQUEST", "TOOL_DUPLICATE_NAME": "DUPLICATE_TOOL_NAME",
                    "EXEC_SUCCEEDED": "succeeded", "EXEC_HANDLER_FAILED": "handler_failed",
                    "EXEC_AUTHORIZATION_REJECTED": "authorization_rejected", "EXEC_OUTPUT_INVALID": "output_invalid",
                    "EXEC_INPUT_REJECTED": "input_rejected", "EXEC_TOOL_REJECTED": "tool_rejected",
                    "MAX_OUTPUT_DEPTH": 100}
        for name, value in expected.items():
            self.assertEqual(getattr(mod, name), value, name)
        self.assertEqual(mod.OUTPUT_TYPES, ("object", "array", "string", "number", "integer", "boolean", "null"))

    def test_result_and_record_contracts_have_stable_keys(self):
        reg = make_registry(spec("keys"))
        res = reg.execute("keys", {})
        self.assertEqual(set(res.to_dict()), RESULT_KEYS)
        self.assertEqual(set(reg.get_invocation_history()[0]), RECORD_KEYS)
        self.assertEqual(set(reg.describe("keys")), {"name", "description", "input_schema", "output_description", "enabled"})
        self.assertEqual(set(reg.register(spec("keys")).to_dict()), {"ok", "status", "name", "failures"})
        self.assertEqual(set(reg.invoke("keys", {}).to_dict()), {"ok", "status", "tool_name", "handler_called", "output", "failures"})
        self.assertEqual(set(reg.preflight("keys", {}).to_dict()),
                         {"tool_name", "tool_exists", "tool_enabled", "authorization_decision", "authorization_accepted",
                          "required_permissions", "granted_permissions", "confirmed", "required_capabilities",
                          "granted_capabilities", "missing_capabilities", "input_valid", "preflight_status", "outcome_code",
                          "failure_codes", "failures", "ok"})

    def test_legacy_definition_only_registry_is_unchanged(self):
        reg = ToolRegistry()
        tool = ToolDefinition(name="web_search", description="d", permissions=["network"], capabilities=["search"])
        self.assertIs(reg.register(tool), tool)
        self.assertTrue(reg.has("web_search") and reg.is_available("web_search"))
        self.assertTrue(reg.disable("web_search") and not reg.is_available("web_search"))
        self.assertTrue(reg.enable("web_search") and reg.is_available("web_search"))
        self.assertEqual([t["name"] for t in reg.list_all()], ["web_search"])
        with self.assertRaises(ValueError):
            reg.register(ToolDefinition(name="web_search"))
        with self.assertRaises(TypeError):
            reg.register("not a tool")
        self.assertTrue(reg.unregister("web_search"))
        self.assertFalse(reg.unregister("web_search"))
        self.assertEqual(ToolDefinition(name="x").is_valid(), True)
        self.assertEqual(ToolDefinition(name="x").access_level, "local")
        self.assertEqual(SUPPORTED_PERMISSIONS, ("network", "filesystem", "external_application", "user_account",
                                                 "user_confirmation"))

    def test_legacy_registries_do_not_know_about_the_new_ones(self):
        legacy = ToolRegistry()
        self.assertFalse(hasattr(legacy, "execute") or hasattr(legacy, "invoke") or hasattr(legacy, "execute_request"))
        self.assertFalse(hasattr(ToolDefinition("x"), "handler"))


class T16PreviouslyFixedDefectsStayFixed(unittest.TestCase):
    # ---- trailing-newline names -------------------------------------------------------------------------------------
    def test_trailing_newline_names_are_rejected_everywhere(self):
        reg = InProcessToolRegistry()
        for bad in ("tool\n", "tool\r\n", "tool\n\n", "a\n"):
            self.assertEqual(reg.register(spec(bad)).codes()[0], "INVALID_TOOL_NAME", repr(bad))
            self.assertIn("INVALID_TOOL_REQUEST_NAME", create_tool_request(bad, {}).codes(), repr(bad))
        self.assertEqual(len(reg), 0)
        self.assertIsNone(mod._NAME_RE.match("tool\n"))
        self.assertIsNotNone(mod._NAME_RE.match("tool"))

    def test_trailing_newline_capabilities_are_rejected_everywhere(self):
        self.assertEqual(InProcessToolRegistry().register(spec("t", capabilities=["cap\n"])).codes(), ["INVALID_TOOL_CAPABILITIES"])
        self.assertIn("INVALID_TOOL_REQUEST_CAPABILITIES", create_tool_request("t", {}, None, ["cap\n"]).codes())
        h = Handler()
        reg = make_registry(spec("t", h, capabilities=["cap"]))
        res = reg.execute("t", {}, None, False, ["cap", "cap\n"])
        self.assertEqual(res.outcome_code, "INVALID_TOOL_AUTHORIZATION")
        self.assertEqual(reg.execute("t", {}, None, False, ["cap\n"]).outcome_code, "INVALID_TOOL_AUTHORIZATION")
        self.assertEqual(h.count, 0)

    def test_newline_variant_of_a_registered_name_is_unknown(self):
        h = Handler()
        reg = make_registry(spec("tool", h))
        self.assertFalse(reg.has("tool\n"))
        self.assertIsNone(reg.describe("tool\n"))
        self.assertEqual(reg.execute("tool\n", {}).outcome_code, "UNKNOWN_TOOL")
        self.assertEqual(reg.preflight("tool\n", {}).outcome_code, "UNKNOWN_TOOL")
        self.assertEqual(h.count, 0)

    # ---- recursion / deep input -------------------------------------------------------------------------------------
    def test_cyclic_input_never_raises_and_is_audited(self):
        cyc = {}
        cyc["self"] = cyc
        cyc_list = {"a": []}
        cyc_list["a"].append(cyc_list)
        h = Handler()
        reg = make_registry(spec("cyc", h))
        for value in (cyc, cyc_list):
            pre = reg.preflight("cyc", value)
            self.assertEqual((pre.outcome_code, pre.input_valid), ("INVALID_TOOL_INPUT", False))
            self.assertEqual(reg.invoke("cyc", value).codes(), ["INVALID_TOOL_INPUT"])
            res = reg.execute("cyc", value)
            self.assertEqual((res.execution_status, res.handler_called), ("input_rejected", False))
        rec = reg.get_invocation_history()[-1]
        self.assertEqual((rec["input_json_safe"], rec["input"], rec["input_type"], rec["sequence"]), (False, None, "dict", 4))
        self.assertEqual(reg.invocation_count(), 4)
        self.assertEqual(h.count, 0)

    def test_very_deep_input_never_raises_at_any_depth(self):
        h = Handler()
        reg = make_registry(spec("deep", h))
        for depth in (mod.MAX_OUTPUT_DEPTH + 2, 1000, 50000):
            value = nested_dict(depth)
            self.assertEqual(reg.preflight("deep", value).outcome_code, "INVALID_TOOL_INPUT", depth)
            res = reg.execute("deep", value)
            self.assertEqual((res.outcome_code, res.handler_called), ("INVALID_TOOL_INPUT", False), depth)
        self.assertEqual(h.count, 0)
        self.assertEqual(reg.invocation_count(), 3)

    def test_input_at_the_depth_limit_is_still_accepted(self):
        h = Handler(value={"ok": 1})      # a handler that echoes its input would itself exceed the (output) depth limit
        reg = make_registry(spec("edge", h))
        self.assertTrue(reg.execute("edge", nested_dict(mod.MAX_OUTPUT_DEPTH + 1)).ok)
        self.assertEqual(reg.execute("edge", nested_dict(mod.MAX_OUTPUT_DEPTH + 2)).outcome_code, "INVALID_TOOL_INPUT")
        self.assertEqual(h.count, 1)

    def test_cyclic_or_deep_schema_is_rejected_at_register_without_raising(self):
        cyc = {}
        cyc["self"] = cyc
        for schema in (cyc, nested_dict(50000)):
            reg = InProcessToolRegistry()
            res = reg.register(ToolSpec(name="t", description="d", handler=Handler(), input_schema=schema, output_description="o"))
            self.assertEqual(res.codes(), ["INVALID_TOOL_INPUT_SCHEMA"])
            self.assertEqual(len(reg), 0)

    def test_cyclic_or_deep_request_input_is_rejected_at_creation(self):
        cyc = {}
        cyc["self"] = cyc
        for value in (cyc, nested_dict(50000)):
            res = create_tool_request("t", value)
            self.assertEqual(res.codes(), ["INVALID_TOOL_REQUEST_INPUT"])
            self.assertIsNone(res.request)

    def test_cyclic_or_deep_handler_output_is_a_documented_failure(self):
        cyc = []
        cyc.append(cyc)
        for value in (cyc, nested_dict(50000)):
            reg = make_registry(spec("out", Handler(value=value)))
            res = reg.execute_request(make_request("out"))
            self.assertEqual((res.outcome_code, res.execution_status, res.handler_called),
                             ("TOOL_OUTPUT_INVALID", "handler_failed", True))

    def test_one_json_safety_authority(self):
        cyc = {}
        cyc["self"] = cyc
        for value in ({"a": [1, {"b": None}]}, cyc, nested_dict(5000), {"a": (1,)}, {"a": float("nan")}, [1], {1: 2}):
            self.assertEqual(mod._json_safe(value), normalize_tool_output(value)[0])

    # ---- input isolation --------------------------------------------------------------------------------------------
    def test_handler_never_receives_the_callers_own_object(self):
        class Selfish(dict):
            def __deepcopy__(self, memo):
                return self

        class SelfishList(list):
            def __deepcopy__(self, memo):
                return self

        caller = Selfish(a=SelfishList([1, {"b": 2}]), c={"d": [3]})
        h = Handler()
        reg = make_registry(spec("selfish", h))
        reg.execute("selfish", caller)
        received = h.calls[0]
        for got, mine in ((received, caller), (received["a"], caller["a"]), (received["c"], caller["c"]),
                          (received["c"]["d"], caller["c"]["d"])):
            self.assertIsNot(got, mine)
        received["a"].append("handler wrote here")
        received["c"]["d"].append("and here")
        self.assertEqual(list(caller["a"]), [1, {"b": 2}])
        self.assertEqual(caller["c"], {"d": [3]})
        self.assertEqual(reg.get_invocation_history()[0]["input"], {"a": [1, {"b": 2}], "c": {"d": [3]}})

    def test_handler_input_is_plain_json_even_for_subclass_input(self):
        class D(dict):
            pass

        h = Handler()
        reg = make_registry(spec("plain_in", h))
        reg.execute("plain_in", D(a=D(b=[1])))
        self.assertIs(type(h.calls[0]), dict)
        self.assertIs(type(h.calls[0]["a"]), dict)

    def test_request_holds_plain_data_only(self):
        class D(dict):
            def __deepcopy__(self, memo):
                return self

        request = make_request("t", D(a=D(b=1)))
        self.assertIs(type(request.input), dict)
        self.assertIs(type(request.input["a"]), dict)
        self.assertIs(type(request.to_registry_arguments()["tool_input"]), dict)


class T17ProjectIntegrity(unittest.TestCase):
    def test_pristine_database_is_untouched(self):
        self.assertEqual(sha256_of(PROJECT_DB), PRISTINE_SHA256)

    def test_running_the_acceptance_flow_does_not_change_the_database(self):
        Scenario().run_all()
        self.assertEqual(sha256_of(PROJECT_DB), PRISTINE_SHA256)

    def test_acceptance_document_exists_and_lists_every_checklist_item(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT)))), "docs",
                            "section5_final_acceptance_prompt705.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for n in range(1, 17):
            self.assertRegex(text, rf"(?m)^\| {n} \|", f"checklist row {n}")
        self.assertIn("Intentional limitations", text)


if __name__ == "__main__":
    unittest.main()
