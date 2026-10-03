"""Prompt 717 - tool-step dispatch decision layer (planning/tool_step_dispatch.py).

The dispatch layer turns the Prompt 716 route into a data-only, caller-facing decision and selects which caller-owned payload belongs to
that route. These tests pin the route semantics (propagated from Prompt 716, never re-decided), payload validation/isolation, result
immutability, and the module's isolation (no ToolRequest/registry/execution/Plan/AgentLoop/process_input dependency, no wiring anywhere).
Docs: docs/section6_tool_step_dispatch_prompt717.md
"""
import ast
import collections
import copy
import enum
import glob
import hashlib
import inspect
import os
import subprocess
import sys
import unittest
from unittest import mock

from planning import tool_step_dispatch as disp_mod
from planning import tool_step_route as route_mod
from planning.plan import Plan, PlanStep
from planning.tool_step_dispatch import (DISPATCH_CODE_LEGACY_INPUT_SELECTED, DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT,
                                         DISPATCH_CODE_REJECTED_PAYLOAD_INVALID, DISPATCH_CODE_TOOL_INPUT_SELECTED, DISPATCH_CODES,
                                         DISPATCH_KIND_LEGACY, DISPATCH_KIND_SECTION6_TOOL, DISPATCH_KINDS, DISPATCH_STATUS_READY,
                                         DISPATCH_STATUS_REJECTED, DISPATCH_STATUSES, MAX_PAYLOAD_DEPTH, MAX_PAYLOAD_NODES,
                                         PAYLOAD_SOURCE_LEGACY_INPUT, PAYLOAD_SOURCE_TOOL_INPUT, PAYLOAD_SOURCES, DispatchResolutionResult,
                                         resolve_tool_step_dispatch)
from planning.tool_step_route import (ROUTE_CODE_EXPLICIT_LEGACY, ROUTE_CODE_EXPLICIT_SECTION6, ROUTE_CODE_FALLBACK_ABSENT,
                                      ROUTE_CODE_FALLBACK_MALFORMED, ROUTE_CODE_FALLBACK_UNKNOWN, ROUTE_LEGACY_CAPABILITY,
                                      ROUTE_SECTION6_TOOL, RouteResolutionResult, resolve_execution_route)
from tests.test_section6_agent_loop_adapter_prompt714 import FROZEN_PLAN_MANAGER_SHA256
from tests.test_section6_agent_loop_handover_decision_prompt713 import (FROZEN_LEGACY_DIGEST, FROZEN_SECTION6_DIGEST, SECTION6, digest)
from tests.test_section6_agent_loop_routing_decision_prompt715 import (FROZEN_ADAPTER_SHA256, FROZEN_AGENT_LOOP_SHA256,
                                                                       FROZEN_CORE_SHA256)
from tests.test_section6_final_acceptance_prompt712 import FROZEN_SECTION45_DIGEST
from tests.test_section6_tool_step_route_prompt716 import Spy, production_files

from tests.section6_agent_loop_baseline_prompt719c import file_bytes as _baseline_file_bytes, read_text as _baseline_read_text   # Prompt 719-C: exact-path exemption for agent/agent_loop.py, see that helper
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISPATCH_REL = "planning/tool_step_dispatch.py"
ROUTE_REL = "planning/tool_step_route.py"
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT)))), "docs", "section6_tool_step_dispatch_prompt717.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
TOOL, LEGACY = ROUTE_SECTION6_TOOL, ROUTE_LEGACY_CAPABILITY
TOOL_PAYLOAD = {"name": "echo", "arguments": {"text": "hi", "n": 2, "flags": [True, None, 1.5]}}
LEGACY_PAYLOAD = {"capability": "text.echo", "input": ["a", {"b": 1}]}


def read(rel):
    return _baseline_read_text(rel)          # Prompt 719-C: agent/agent_loop.py is read without the sanctioned additions


def sha(rel):
    return hashlib.sha256(_baseline_file_bytes(rel)).hexdigest()         # Prompt 719-C: agent_loop.py read without the sanctioned additions


class StrSub(str):
    """A str subclass that records every protocol call."""
    calls = []

    def __eq__(self, other):
        StrSub.calls.append("__eq__")
        return True

    def __hash__(self):
        StrSub.calls.append("__hash__")
        return 0


class IntSub(int):
    pass


class Color(enum.Enum):
    RED = "red"


class StrEnum(str, enum.Enum):
    A = "a"


class DictSub(dict):
    pass


class ListSub(list):
    pass


def assert_ready(tc, res, route, payload_source, code, payload):
    tc.assertEqual((res.route, res.dispatch_status, res.dispatch_code, res.payload_source), (route, DISPATCH_STATUS_READY, code, payload_source))
    tc.assertTrue(res.is_ready)
    tc.assertFalse(res.is_rejected)
    tc.assertTrue(res.has_payload)
    tc.assertEqual(res.payload, payload)


# ---------------------------------------------------------------------------------------------------------------------
class TestRouteSemantics(unittest.TestCase):
    def test_exact_section6_tool_declaration_selects_tool_dispatch(self):
        res = resolve_tool_step_dispatch("section6_tool", LEGACY_PAYLOAD, TOOL_PAYLOAD)
        assert_ready(self, res, TOOL, PAYLOAD_SOURCE_TOOL_INPUT, DISPATCH_CODE_TOOL_INPUT_SELECTED, TOOL_PAYLOAD)
        self.assertEqual((res.explicit, res.fallback, res.declaration_valid, res.route_code), (True, False, True, ROUTE_CODE_EXPLICIT_SECTION6))
        self.assertEqual(res.dispatch_kind, DISPATCH_KIND_SECTION6_TOOL)
        self.assertTrue(res.is_section6_tool)
        self.assertFalse(res.is_legacy_capability)

    def test_exact_legacy_capability_declaration_selects_legacy_dispatch(self):
        res = resolve_tool_step_dispatch("legacy_capability", LEGACY_PAYLOAD, TOOL_PAYLOAD)
        assert_ready(self, res, LEGACY, PAYLOAD_SOURCE_LEGACY_INPUT, DISPATCH_CODE_LEGACY_INPUT_SELECTED, LEGACY_PAYLOAD)
        self.assertEqual((res.explicit, res.fallback, res.declaration_valid, res.route_code), (True, False, True, ROUTE_CODE_EXPLICIT_LEGACY))
        self.assertEqual(res.dispatch_kind, DISPATCH_KIND_LEGACY)
        self.assertFalse(res.is_section6_tool)
        self.assertTrue(res.is_legacy_capability)

    def test_omitted_and_none_declarations_are_the_same_absent_case(self):
        omitted = resolve_tool_step_dispatch(legacy_input=LEGACY_PAYLOAD, tool_input=TOOL_PAYLOAD)
        none = resolve_tool_step_dispatch(None, LEGACY_PAYLOAD, TOOL_PAYLOAD)
        self.assertEqual(omitted, none)
        assert_ready(self, omitted, LEGACY, PAYLOAD_SOURCE_LEGACY_INPUT, DISPATCH_CODE_LEGACY_INPUT_SELECTED, LEGACY_PAYLOAD)
        self.assertEqual((omitted.explicit, omitted.fallback, omitted.declaration_valid, omitted.route_code),
                         (False, True, False, ROUTE_CODE_FALLBACK_ABSENT))
        self.assertEqual(resolve_tool_step_dispatch().route, LEGACY)

    def test_unknown_string_declarations_fall_back_to_legacy_never_tool(self):
        for declaration in ("", "Section6_Tool", "section6_tool ", " section6_tool", "SECTION6_TOOL", "tool", "legacy", "Legacy_Capability", "section6_tool\n"):
            res = resolve_tool_step_dispatch(declaration, LEGACY_PAYLOAD, TOOL_PAYLOAD)
            assert_ready(self, res, LEGACY, PAYLOAD_SOURCE_LEGACY_INPUT, DISPATCH_CODE_LEGACY_INPUT_SELECTED, LEGACY_PAYLOAD)
            self.assertEqual((res.explicit, res.fallback, res.declaration_valid, res.route_code),
                             (False, True, False, ROUTE_CODE_FALLBACK_UNKNOWN), declaration)
            self.assertFalse(res.is_section6_tool)

    def test_malformed_declarations_fall_back_to_legacy_never_tool(self):
        for declaration in (1, 0, True, False, 1.5, b"section6_tool", ["section6_tool"], ("section6_tool",), {"route": "section6_tool"},
                            {"section6_tool"}, object(), Color.RED, StrEnum.A, IntSub(1), ListSub(["section6_tool"])):
            res = resolve_tool_step_dispatch(declaration, LEGACY_PAYLOAD, TOOL_PAYLOAD)
            assert_ready(self, res, LEGACY, PAYLOAD_SOURCE_LEGACY_INPUT, DISPATCH_CODE_LEGACY_INPUT_SELECTED, LEGACY_PAYLOAD)
            self.assertEqual((res.explicit, res.fallback, res.declaration_valid, res.route_code),
                             (False, True, False, ROUTE_CODE_FALLBACK_MALFORMED), type(declaration).__name__)

    def test_fallback_always_preserves_legacy_route_and_is_never_upgraded(self):
        for declaration in (None, "x", 5, StrSub("section6_tool"), {"a": 1}):
            res = resolve_tool_step_dispatch(declaration, LEGACY_PAYLOAD, TOOL_PAYLOAD)
            self.assertTrue(res.fallback)
            self.assertEqual((res.route, res.dispatch_kind, res.payload_source), (LEGACY, DISPATCH_KIND_LEGACY, PAYLOAD_SOURCE_LEGACY_INPUT))
            self.assertIsNot(res.route, TOOL)
            self.assertFalse(res.is_section6_tool)

    def test_fallback_is_not_upgraded_even_when_only_a_tool_input_is_supplied(self):
        res = resolve_tool_step_dispatch("nonsense", None, TOOL_PAYLOAD)
        self.assertEqual((res.route, res.dispatch_status, res.dispatch_code), (LEGACY, DISPATCH_STATUS_REJECTED, DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT))
        self.assertIsNone(res.payload)

    def test_route_is_never_inferred_from_payload_contents_or_shapes(self):
        tricky = {"route": "section6_tool", "declaration": "section6_tool", "execution_authorized": True, "tool": "echo",
                  "required_capabilities": ["section6_tool"], "steps": [{"step_id": "s1"}]}
        self.assertEqual(resolve_tool_step_dispatch(None, tricky, tricky).route, LEGACY)
        self.assertEqual(resolve_tool_step_dispatch("legacy_capability", tricky, tricky).route, LEGACY)
        self.assertEqual(resolve_tool_step_dispatch("section6_tool", {"route": "legacy_capability"}, {"route": "legacy_capability"}).route, TOOL)
        plan = Plan("p1", "g1", steps=[PlanStep("section6_tool", "section6_tool", required_capabilities=["section6_tool"])],
                    metadata={"route": "section6_tool", "execution_authorized": True})
        res = resolve_tool_step_dispatch(plan, plan, plan)             # plan objects are never a route and never a payload
        self.assertEqual((res.route, res.route_code, res.dispatch_code), (LEGACY, ROUTE_CODE_FALLBACK_MALFORMED, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID))

    def test_prompt716_result_is_propagated_exactly(self):
        for declaration in (None, "section6_tool", "legacy_capability", "x", "", 7, [], StrSub("legacy_capability")):
            expected = resolve_execution_route(declaration)
            res = resolve_tool_step_dispatch(declaration, LEGACY_PAYLOAD, TOOL_PAYLOAD)
            self.assertEqual(res.route_result, expected)
            self.assertIs(type(res.route_result), RouteResolutionResult)
            self.assertEqual((res.route, res.explicit, res.fallback, res.declaration_valid, res.route_code, res.route_reason),
                             (expected.route, expected.explicit, expected.fallback, expected.declaration_valid, expected.code, expected.reason))
            self.assertEqual(res.is_section6_tool, expected.is_section6_tool)

    def test_resolver_is_called_exactly_once_with_the_declaration(self):
        for declaration in ("section6_tool", "legacy_capability", None, "bad", 3):
            spy = mock.Mock(wraps=resolve_execution_route)
            with mock.patch.object(disp_mod, "resolve_execution_route", spy):
                resolve_tool_step_dispatch(declaration, LEGACY_PAYLOAD, TOOL_PAYLOAD)
            self.assertEqual(spy.call_count, 1)
            self.assertEqual(spy.call_args, mock.call(declaration))

    def test_route_comes_only_from_the_resolver(self):
        forced = route_mod._make(TOOL, True, False, True, ROUTE_CODE_EXPLICIT_SECTION6)
        with mock.patch.object(disp_mod, "resolve_execution_route", return_value=forced):
            res = resolve_tool_step_dispatch("legacy_capability", LEGACY_PAYLOAD, TOOL_PAYLOAD)
        self.assertEqual((res.route, res.payload_source), (TOOL, PAYLOAD_SOURCE_TOOL_INPUT))
        self.assertEqual(res.payload, TOOL_PAYLOAD)

    def test_an_unexpected_resolver_route_is_a_loud_error_not_a_reinterpretation(self):
        bogus = mock.Mock(route="something_else")
        with mock.patch.object(disp_mod, "resolve_execution_route", return_value=bogus):
            with self.assertRaises(ValueError):
                resolve_tool_step_dispatch("section6_tool", LEGACY_PAYLOAD, TOOL_PAYLOAD)

    def test_str_subclass_declaration_is_malformed_and_never_called(self):
        StrSub.calls.clear()
        for declaration in (StrSub("section6_tool"), StrSub("legacy_capability"), StrEnum.A):
            res = resolve_tool_step_dispatch(declaration, LEGACY_PAYLOAD, TOOL_PAYLOAD)
            self.assertEqual((res.route, res.route_code), (LEGACY, ROUTE_CODE_FALLBACK_MALFORMED))
        self.assertEqual(StrSub.calls, [])

    def test_unusual_declaration_objects_are_never_inspected(self):
        spy = Spy()
        res = resolve_tool_step_dispatch(spy, LEGACY_PAYLOAD, TOOL_PAYLOAD)
        self.assertEqual((res.route, res.route_code), (LEGACY, ROUTE_CODE_FALLBACK_MALFORMED))
        self.assertEqual(spy.calls, [])


# ---------------------------------------------------------------------------------------------------------------------
class TestPayloadSelection(unittest.TestCase):
    def test_tool_payload_is_selected_only_for_the_tool_route(self):
        for declaration in ("section6_tool",):
            res = resolve_tool_step_dispatch(declaration, {"legacy": 1}, {"tool": 1})
            self.assertEqual((res.payload, res.payload_source), ({"tool": 1}, PAYLOAD_SOURCE_TOOL_INPUT))
        for declaration in (None, "legacy_capability", "bad", 9):
            res = resolve_tool_step_dispatch(declaration, {"legacy": 1}, {"tool": 1})
            self.assertEqual((res.payload, res.payload_source), ({"legacy": 1}, PAYLOAD_SOURCE_LEGACY_INPUT))

    def test_legacy_payload_is_selected_only_for_the_legacy_route(self):
        res = resolve_tool_step_dispatch("section6_tool", {"legacy": 1}, None)
        self.assertEqual((res.route, res.dispatch_status, res.dispatch_code), (TOOL, DISPATCH_STATUS_REJECTED, DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT))
        res = resolve_tool_step_dispatch("legacy_capability", None, {"tool": 1})
        self.assertEqual((res.route, res.dispatch_status, res.dispatch_code), (LEGACY, DISPATCH_STATUS_REJECTED, DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT))

    def test_the_unselected_payload_is_never_inspected_copied_or_returned(self):
        spy = Spy()
        res = resolve_tool_step_dispatch("section6_tool", spy, TOOL_PAYLOAD)
        self.assertEqual(res.dispatch_status, DISPATCH_STATUS_READY)
        res = resolve_tool_step_dispatch("legacy_capability", LEGACY_PAYLOAD, spy)
        self.assertEqual(res.dispatch_status, DISPATCH_STATUS_READY)
        self.assertEqual(spy.calls, [])
        # an invalid unselected payload is irrelevant: it neither rejects the dispatch nor changes the route
        res = resolve_tool_step_dispatch("section6_tool", object(), TOOL_PAYLOAD)
        self.assertEqual((res.route, res.dispatch_status), (TOOL, DISPATCH_STATUS_READY))
        res = resolve_tool_step_dispatch("legacy_capability", LEGACY_PAYLOAD, float("nan"))
        self.assertEqual((res.route, res.dispatch_status), (LEGACY, DISPATCH_STATUS_READY))

    def test_absent_payload_is_rejected_without_inventing_a_default(self):
        for declaration, route, kind in (("section6_tool", TOOL, DISPATCH_KIND_SECTION6_TOOL), ("legacy_capability", LEGACY, DISPATCH_KIND_LEGACY), (None, LEGACY, DISPATCH_KIND_LEGACY)):
            res = resolve_tool_step_dispatch(declaration)
            self.assertEqual((res.route, res.dispatch_kind, res.dispatch_status, res.dispatch_code, res.has_payload),
                             (route, kind, DISPATCH_STATUS_REJECTED, DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT, False))
            self.assertIsNone(res.payload)

    def test_falsy_but_valid_payloads_are_not_absent_and_are_not_coerced(self):
        for value in ("", 0, 0.0, False, [], {}):
            res = resolve_tool_step_dispatch("section6_tool", None, value)
            self.assertEqual(res.dispatch_status, DISPATCH_STATUS_READY, repr(value))
            self.assertIs(type(res.payload), type(value))
            self.assertEqual(res.payload, value)

    def test_accepted_payload_types(self):
        value = {"s": "x", "i": 3, "f": 2.5, "t": True, "f2": False, "n": None, "l": [1, [2, [3]], {"k": []}], "d": {"a": {"b": {}}}, "": 1}
        res = resolve_tool_step_dispatch("section6_tool", None, value)
        self.assertEqual(res.dispatch_status, DISPATCH_STATUS_READY)
        self.assertEqual(res.payload, value)
        self.assertEqual(list(res.payload), list(value))                # key order preserved
        for scalar in ("text", 7, -1.25, True, [1], {"a": 1}):
            self.assertEqual(resolve_tool_step_dispatch(None, scalar).payload, scalar)


class TestPayloadRejectionDoesNotChangeRoute(unittest.TestCase):
    def bad_payloads(self):
        cyc_list = []
        cyc_list.append(cyc_list)
        cyc_dict = {}
        cyc_dict["self"] = cyc_dict
        deep = cur = []
        for _ in range(MAX_PAYLOAD_DEPTH + 2):
            nxt = []
            cur.append(nxt)
            cur = nxt
        wide = [[0] * 1000 for _ in range(MAX_PAYLOAD_NODES // 1000 + 1)]
        return [("tuple", (1, 2)), ("set", {1}), ("frozenset", frozenset([1])), ("bytes", b"x"), ("bytearray", bytearray(b"x")),
                ("nan", float("nan")), ("inf", float("inf")), ("-inf", float("-inf")), ("nested nan", {"a": [float("nan")]}),
                ("non-str key", {1: "a"}), ("none key", {None: "a"}), ("tuple key", {(1,): "a"}), ("str-subclass key", {StrSub("k"): 1}),
                ("str subclass", StrSub("x")), ("int subclass", IntSub(1)), ("str enum", StrEnum.A), ("enum", Color.RED),
                ("dict subclass", DictSub(a=1)), ("list subclass", ListSub([1])), ("ordered dict", collections.OrderedDict(a=1)),
                ("defaultdict", collections.defaultdict(list)), ("object", object()), ("lambda", lambda: 1), ("class", dict), ("complex", 1j),
                ("nested object", {"a": [object()]}), ("nested tuple", {"a": (1,)}), ("cyclic list", cyc_list), ("cyclic dict", cyc_dict),
                ("too deep", deep), ("too many nodes", wide), ("plan", Plan("p", "g")), ("plan step", PlanStep("s", "d")),
                ("handler", print), ("module", sys), ("spy", Spy())]

    def test_malformed_tool_payload_does_not_change_the_route_to_legacy(self):
        for label, bad in self.bad_payloads():
            res = resolve_tool_step_dispatch("section6_tool", LEGACY_PAYLOAD, bad)
            self.assertEqual((res.route, res.dispatch_kind, res.dispatch_status, res.dispatch_code, res.payload_source, res.explicit, res.declaration_valid),
                             (TOOL, DISPATCH_KIND_SECTION6_TOOL, DISPATCH_STATUS_REJECTED, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID,
                              PAYLOAD_SOURCE_TOOL_INPUT, True, True), label)
            self.assertTrue(res.is_section6_tool)
            self.assertIsNone(res.payload)
            self.assertFalse(res.has_payload)

    def test_malformed_legacy_payload_does_not_change_the_route_to_tool(self):
        for label, bad in self.bad_payloads():
            for declaration in ("legacy_capability", None, "bad"):
                res = resolve_tool_step_dispatch(declaration, bad, TOOL_PAYLOAD)
                self.assertEqual((res.route, res.dispatch_kind, res.dispatch_status, res.dispatch_code, res.payload_source),
                                 (LEGACY, DISPATCH_KIND_LEGACY, DISPATCH_STATUS_REJECTED, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID,
                                  PAYLOAD_SOURCE_LEGACY_INPUT), label)
                self.assertFalse(res.is_section6_tool)

    def test_a_fallback_with_a_bad_payload_keeps_its_fallback_flags(self):
        res = resolve_tool_step_dispatch("nope", object(), TOOL_PAYLOAD)
        self.assertEqual((res.route, res.explicit, res.fallback, res.declaration_valid, res.route_code, res.dispatch_status),
                         (LEGACY, False, True, False, ROUTE_CODE_FALLBACK_UNKNOWN, DISPATCH_STATUS_REJECTED))

    def test_rejected_payload_objects_are_never_called_or_stringified(self):
        StrSub.calls.clear()
        spy = Spy()
        for bad in (StrSub("x"), {"k": StrSub("v")}, [spy], {"k": spy}, spy):
            resolve_tool_step_dispatch("section6_tool", None, bad)
        self.assertEqual(StrSub.calls, [])
        self.assertEqual(spy.calls, [])

    def test_repr_is_never_used_on_payloads(self):
        class Boom:
            def __repr__(self):
                raise AssertionError("repr() must not be called")

            __str__ = __repr__

            def __getattribute__(self, name):
                raise AssertionError("attribute access must not happen: " + name)

        for bad in (Boom(), [Boom()], {"a": Boom()}):
            res = resolve_tool_step_dispatch("section6_tool", None, bad)
            self.assertEqual(res.dispatch_code, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID)
        with mock.patch("builtins.repr", side_effect=AssertionError("repr() called")):
            resolve_tool_step_dispatch("section6_tool", LEGACY_PAYLOAD, TOOL_PAYLOAD)
            resolve_tool_step_dispatch(None, object(), object())

    def test_depth_and_size_limits_are_exact(self):
        ok = cur = []
        for _ in range(MAX_PAYLOAD_DEPTH):
            nxt = []
            cur.append(nxt)
            cur = nxt
        self.assertEqual(resolve_tool_step_dispatch("section6_tool", None, ok).dispatch_status, DISPATCH_STATUS_READY)
        too_deep = [ok]
        self.assertEqual(resolve_tool_step_dispatch("section6_tool", None, too_deep).dispatch_code, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID)
        self.assertEqual(resolve_tool_step_dispatch("section6_tool", None, [0] * (MAX_PAYLOAD_NODES - 1)).dispatch_status, DISPATCH_STATUS_READY)
        self.assertEqual(resolve_tool_step_dispatch("section6_tool", None, [0] * MAX_PAYLOAD_NODES).dispatch_code, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID)

    def test_shared_substructure_is_accepted_but_cycles_are_not(self):
        shared = [1, 2]
        res = resolve_tool_step_dispatch("section6_tool", None, {"a": shared, "b": shared})
        self.assertEqual(res.payload, {"a": [1, 2], "b": [1, 2]})
        self.assertIsNot(res.payload["a"], res.payload["b"])             # no aliasing inside the returned copy either

    def test_bad_payload_leaves_the_caller_input_untouched(self):
        bad = {"a": [1, 2, (3,)], "b": object()}
        snapshot = list(bad), list(bad["a"])
        resolve_tool_step_dispatch("section6_tool", None, bad)
        self.assertEqual((list(bad), list(bad["a"])), snapshot)


# ---------------------------------------------------------------------------------------------------------------------
class TestInputIsolation(unittest.TestCase):
    def test_caller_inputs_are_not_mutated(self):
        legacy, tool = copy.deepcopy(LEGACY_PAYLOAD), copy.deepcopy(TOOL_PAYLOAD)
        for declaration in ("section6_tool", "legacy_capability", None, "x", 4):
            resolve_tool_step_dispatch(declaration, legacy, tool)
        self.assertEqual((legacy, tool), (LEGACY_PAYLOAD, TOOL_PAYLOAD))
        self.assertEqual((list(legacy), list(tool)), (list(LEGACY_PAYLOAD), list(TOOL_PAYLOAD)))

    def test_later_mutation_of_caller_inputs_cannot_reach_the_result(self):
        tool = {"name": "echo", "arguments": {"items": [1, 2, 3]}}
        legacy = {"items": [1, 2, 3]}
        tres = resolve_tool_step_dispatch("section6_tool", legacy, tool)
        lres = resolve_tool_step_dispatch("legacy_capability", legacy, tool)
        tool["arguments"]["items"].append(99)
        tool["name"] = "changed"
        tool.clear()
        legacy["items"].clear()
        legacy["new"] = True
        self.assertEqual(tres.payload, {"name": "echo", "arguments": {"items": [1, 2, 3]}})
        self.assertEqual(lres.payload, {"items": [1, 2, 3]})

    def test_the_payload_is_a_fresh_copy_on_every_access(self):
        res = resolve_tool_step_dispatch("section6_tool", None, {"a": [1, {"b": 2}]})
        first, second = res.payload, res.payload
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first["a"], second["a"])
        first["a"].append(3)
        first["a"][1]["b"] = 99
        first["z"] = 1
        self.assertEqual(res.payload, {"a": [1, {"b": 2}]})

    def test_the_result_never_holds_the_callers_objects(self):
        tool = {"a": [1]}
        res = resolve_tool_step_dispatch("section6_tool", None, tool)
        self.assertIsNot(res.payload, tool)
        self.assertIsNot(res.payload["a"], tool["a"])
        self.assertIsNot(res._payload, tool)
        self.assertIsNot(res._payload["a"], tool["a"])

    def test_as_dict_is_fresh_and_isolated(self):
        res = resolve_tool_step_dispatch("section6_tool", None, {"a": [1]})
        d1, d2 = res.as_dict(), res.as_dict()
        self.assertIsNot(d1, d2)
        self.assertEqual(d1, d2)
        self.assertEqual(sorted(d1), sorted(["route", "explicit", "fallback", "declaration_valid", "route_code", "route_reason", "dispatch_kind",
                                             "dispatch_status", "dispatch_code", "dispatch_reason", "payload_source", "has_payload", "payload",
                                             "is_section6_tool"]))
        d1["payload"]["a"].append(2)
        d1["route"] = "legacy_capability"
        d1.clear()
        self.assertEqual(res.as_dict(), d2)
        self.assertEqual(res.payload, {"a": [1]})

    def test_strings_are_shared_safely_because_they_are_immutable(self):
        value = {"k": "v"}
        res = resolve_tool_step_dispatch("section6_tool", None, value)
        self.assertEqual(res.payload, {"k": "v"})


# ---------------------------------------------------------------------------------------------------------------------
class TestDeterminismAndImmutability(unittest.TestCase):
    def test_repeated_calls_are_deterministic(self):
        for declaration in ("section6_tool", "legacy_capability", None, "x", 1):
            results = [resolve_tool_step_dispatch(declaration, copy.deepcopy(LEGACY_PAYLOAD), copy.deepcopy(TOOL_PAYLOAD)) for _ in range(5)]
            self.assertTrue(all(r == results[0] for r in results))
            self.assertEqual(len({hash(r) for r in results}), 1)
            self.assertEqual(len({repr(r) for r in results}), 1)
            self.assertEqual([r.as_dict() for r in results], [results[0].as_dict()] * 5)
            self.assertIsNot(results[0], results[1])

    def test_results_with_different_routes_payloads_or_statuses_differ(self):
        a = resolve_tool_step_dispatch("section6_tool", None, {"a": 1})
        self.assertNotEqual(a, resolve_tool_step_dispatch("section6_tool", None, {"a": 2}))
        self.assertNotEqual(a, resolve_tool_step_dispatch("legacy_capability", {"a": 1}, None))
        self.assertNotEqual(a, resolve_tool_step_dispatch("section6_tool", None, object()))
        self.assertNotEqual(a, resolve_tool_step_dispatch(None, {"a": 1}, None))
        self.assertNotEqual(resolve_tool_step_dispatch(None, {"a": 1}), resolve_tool_step_dispatch("legacy_capability", {"a": 1}))   # fallback vs explicit
        self.assertNotEqual(a, "not a result")

    def test_equality_is_type_exact_for_payloads(self):
        self.assertNotEqual(resolve_tool_step_dispatch("section6_tool", None, {"a": True}), resolve_tool_step_dispatch("section6_tool", None, {"a": 1}))
        self.assertNotEqual(resolve_tool_step_dispatch("section6_tool", None, [1]), resolve_tool_step_dispatch("section6_tool", None, [1.0]))
        self.assertEqual(resolve_tool_step_dispatch("section6_tool", None, {"a": [1]}), resolve_tool_step_dispatch("section6_tool", None, {"a": [1]}))
        self.assertNotEqual(resolve_tool_step_dispatch("section6_tool", None, {"a": 1, "b": 2}), resolve_tool_step_dispatch("section6_tool", None, {"b": 2, "a": 1}))

    def test_result_is_immutable(self):
        res = resolve_tool_step_dispatch("section6_tool", None, {"a": 1})
        for name in ("route", "payload", "dispatch_status", "_payload", "_status", "anything", "explicit"):
            with self.assertRaises(AttributeError):
                setattr(res, name, "x")
            with self.assertRaises(AttributeError):
                delattr(res, name)
        self.assertFalse(hasattr(res, "__dict__"))
        self.assertEqual(res.payload, {"a": 1})

    def test_result_cannot_be_subclassed_or_built_directly(self):
        with self.assertRaises(TypeError):
            class Sub(DispatchResolutionResult):
                pass
        route = resolve_execution_route("section6_tool")
        with self.assertRaises(TypeError):
            DispatchResolutionResult(object(), route, DISPATCH_KIND_SECTION6_TOOL, DISPATCH_STATUS_READY, DISPATCH_CODE_TOOL_INPUT_SELECTED,
                                     PAYLOAD_SOURCE_TOOL_INPUT, {})
        with self.assertRaises(TypeError):
            DispatchResolutionResult()

    def test_result_survives_copy_and_deepcopy_unchanged(self):
        res = resolve_tool_step_dispatch("legacy_capability", {"a": [1]}, None)
        self.assertIs(copy.copy(res), res)
        self.assertIs(copy.deepcopy(res), res)
        self.assertEqual(copy.deepcopy(res).payload, {"a": [1]})

    def test_repr_is_data_only_and_never_shows_the_payload(self):
        res = resolve_tool_step_dispatch("section6_tool", None, {"secret": "PAYLOAD-MARKER-123"})
        text = repr(res)
        self.assertNotIn("PAYLOAD-MARKER-123", text)
        self.assertIn("route='section6_tool'", text)
        self.assertIn("dispatch_status='ready'", text)
        self.assertIn("EXPLICIT_SECTION6_TOOL", text)

    def test_public_constants_are_exact_tuples_of_distinct_strings(self):
        self.assertEqual(DISPATCH_STATUSES, ("ready", "rejected"))
        self.assertEqual(DISPATCH_KINDS, ("legacy_capability_dispatch", "section6_tool_dispatch"))
        self.assertEqual(PAYLOAD_SOURCES, ("legacy_input", "tool_input"))
        self.assertEqual(DISPATCH_CODES, ("LEGACY_INPUT_SELECTED", "TOOL_INPUT_SELECTED", "REJECTED_PAYLOAD_ABSENT", "REJECTED_PAYLOAD_INVALID"))
        for group in (DISPATCH_STATUSES, DISPATCH_KINDS, PAYLOAD_SOURCES, DISPATCH_CODES):
            self.assertIs(type(group), tuple)
            self.assertEqual(len(set(group)), len(group))

    def test_every_code_has_a_fixed_reason_sentence(self):
        reasons = {resolve_tool_step_dispatch("section6_tool", None, {}).dispatch_reason,
                   resolve_tool_step_dispatch("legacy_capability", {}, None).dispatch_reason,
                   resolve_tool_step_dispatch("section6_tool").dispatch_reason,
                   resolve_tool_step_dispatch("section6_tool", None, object()).dispatch_reason}
        self.assertEqual(len(reasons), 4)
        self.assertTrue(all(type(r) is str and r.endswith(".") for r in reasons))

    def test_public_api_is_small_and_explicit(self):
        self.assertEqual(list(inspect.signature(resolve_tool_step_dispatch).parameters), ["declaration", "legacy_input", "tool_input"])
        for param in inspect.signature(resolve_tool_step_dispatch).parameters.values():
            self.assertIsNone(param.default)
        self.assertEqual(sorted(n for n in dir(disp_mod) if not n.startswith("_") and inspect.isroutine(getattr(disp_mod, n))
                                and getattr(disp_mod, n).__module__ == disp_mod.__name__), ["resolve_tool_step_dispatch"])
        self.assertEqual(sorted(n for n in dir(disp_mod) if not n.startswith("_") and inspect.isclass(getattr(disp_mod, n))
                                and getattr(disp_mod, n).__module__ == disp_mod.__name__), ["DispatchResolutionResult"])


# ---------------------------------------------------------------------------------------------------------------------
BLOCKED_MODULES = ("planning.plan", "planning.plan_manager", "planning.plan_builder", "planning.plan_validation", "planning.goal_manager",
                   "planning.tool_step_agent_adapter", "planning.tool_step_bridge", "planning.tool_step_executor", "planning.tool_step_retry",
                   "planning.tool_capability_mapping", "tools", "tools.tool_registry", "tools.tool_request", "tools.in_process_tool_registry",
                   "execution", "execution.execution_engine", "execution.plan_execution_controller", "agent", "agent.agent_loop", "core",
                   "core.core", "capabilities", "ael")
ISOLATION_SCRIPT = r"""
import sys
for name in %r:
    sys.modules[name] = None                      # any import of these raises ImportError
import planning.tool_step_dispatch as m
loaded = sorted(n for n in sys.modules if sys.modules[n] is not None and n.split(".")[0] in ("tools", "execution", "agent", "core", "ael", "capabilities"))
assert not loaded, loaded
assert sorted(n for n in sys.modules if n.startswith("planning.") and sys.modules[n] is not None) == ["planning.tool_step_dispatch", "planning.tool_step_route"]
r = m.resolve_tool_step_dispatch("section6_tool", {"l": 1}, {"t": 1})
assert (r.route, r.payload, r.payload_source, r.is_section6_tool) == ("section6_tool", {"t": 1}, "tool_input", True)
r = m.resolve_tool_step_dispatch(None, {"l": 1}, {"t": 1})
assert (r.route, r.payload, r.fallback, r.explicit) == ("legacy_capability", {"l": 1}, True, False)
assert m.resolve_tool_step_dispatch("section6_tool", None, object()).dispatch_code == "REJECTED_PAYLOAD_INVALID"
print("ISOLATED-OK")
""" % (BLOCKED_MODULES,)


class TestNoExecutionAuthorityAndIsolation(unittest.TestCase):
    def test_module_imports_only_math_and_the_prompt716_resolver(self):
        tree = ast.parse(read(DISPATCH_REL))
        mods = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods += [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                mods.append(n.module)
        self.assertEqual(sorted(mods), ["math", "planning.tool_step_route"])
        frm = next(n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))
        self.assertEqual(sorted(a.name for a in frm.names), ["ROUTE_LEGACY_CAPABILITY", "ROUTE_SECTION6_TOOL", "resolve_execution_route"])

    def test_module_works_with_every_other_project_layer_blocked_from_import(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run([sys.executable, "-c", ISOLATION_SCRIPT], cwd=PY_ROOT, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, "ISOLATED-OK"), proc.stderr)

    def test_code_never_touches_plans_registries_handlers_requests_permissions_or_execution(self):
        tree = ast.parse(read(DISPATCH_REL))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        names |= {a.arg for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) for a in n.args.args}
        for name in names:
            lowered = name.lower()
            if name.startswith(("ROUTE_", "DISPATCH_", "PAYLOAD_", "MAX_PAYLOAD")) or name in ("is_legacy_capability", "is_section6_tool", "resolve_execution_route",
                                                                                               "resolve_tool_step_dispatch", "DispatchResolutionResult",
                                                                                               "payload_source", "route_code", "route_reason", "route_result"):
                continue
            for word in ("plan", "registry", "handler", "capabilit", "permission", "toolrequest", "tool_request", "agent", "loop", "process_input",
                         "retry", "adapter", "bridge", "executor", "engine", "execut", "authoriz", "spec", "invoke", "run"):
                self.assertNotIn(word, lowered, name)

    def test_no_execution_or_construction_calls_exist(self):
        code = ast.parse(read(DISPATCH_REL))
        called = {n.func.id for n in ast.walk(code) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        called |= {n.func.attr for n in ast.walk(code) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn("resolve_execution_route", called)
        self.assertEqual({c for c in called if c in ("open", "eval", "exec", "compile", "__import__", "getattr", "setattr", "repr", "str", "print",
                                                      "vars", "globals", "locals", "input", "copy", "deepcopy", "sorted")}, set())
        idents = {n.id for n in ast.walk(code) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(code) if isinstance(n, ast.Attribute)}
        self.assertEqual({i for i in idents if "ToolRequest" in i or "execution_authorized" in i or "registry" in i.lower() or "Plan" in i}, set())
        self.assertEqual(sum(1 for n in ast.walk(code) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "resolve_execution_route"), 1)

    def test_dispatch_calls_no_handler_registry_or_execution_even_when_they_are_passed_in(self):
        handler_calls = []

        def handler(*a, **k):
            handler_calls.append((a, k))

        class Registry:
            def __getattribute__(self, name):
                handler_calls.append(name)
                raise AssertionError("registry touched")

        for declaration in ("section6_tool", "legacy_capability", None):
            for payload in (handler, Registry(), {"h": handler}, [Registry()]):
                res = resolve_tool_step_dispatch(declaration, payload, payload)
                self.assertEqual(res.dispatch_code, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID)
        self.assertEqual(handler_calls, [])

    def test_plan_data_and_authorization_flags_are_just_data(self):
        payload = {"plan": {"plan_id": "p", "steps": [{"step_id": "s"}]}, "execution_authorized": True, "permissions": ["all"], "capabilities": ["x"]}
        res = resolve_tool_step_dispatch("section6_tool", None, payload)
        self.assertEqual(res.payload, payload)                                    # carried verbatim, never interpreted or granted
        self.assertEqual(set(res.as_dict()) & {"execution_authorized", "permissions", "capabilities", "plan"}, set())
        plan = Plan("p1", "g1", steps=[PlanStep("s1", "d")], metadata={"route": "section6_tool"})
        before = copy.deepcopy(plan.metadata)
        resolve_tool_step_dispatch(None, None, None)
        self.assertEqual(plan.metadata, before)

    def test_no_module_level_mutable_state_or_registry(self):
        tree = ast.parse(read(DISPATCH_REL))
        for n in tree.body:
            if isinstance(n, ast.Assign):
                self.assertNotIsInstance(n.value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp), ast.dump(n)[:80])
            self.assertNotIsInstance(n, (ast.Global, ast.Nonlocal))
        self.assertFalse([n for n in dir(disp_mod) if "registry" in n.lower() or "register" in n.lower()])
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))])
        before = {k: v for k, v in vars(disp_mod).items() if not k.startswith("__")}
        resolve_tool_step_dispatch("section6_tool", None, {"a": 1})
        resolve_tool_step_dispatch(None, {"a": 1}, None)
        after = {k: v for k, v in vars(disp_mod).items() if not k.startswith("__")}
        self.assertEqual(before.keys(), after.keys())
        for key in before:
            self.assertIs(before[key], after[key], key)

    def test_no_persistence_network_threading_clock_or_randomness(self):
        tree = ast.parse(read(DISPATCH_REL))
        roots = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                roots |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                roots.add((n.module or "").split(".")[0])
        self.assertEqual(roots, {"math", "planning"})                   # no sqlite3/socket/threading/time/random/os/subprocess/json/pickle ...
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal, ast.Await, ast.AsyncFunctionDef, ast.Lambda))], [])


# ---------------------------------------------------------------------------------------------------------------------
class TestNothingIsWiredAndProtectedFilesAreUntouched(unittest.TestCase):
    def test_no_production_module_other_than_the_dispatch_layer_references_the_resolver_or_dispatch(self):
        tokens = ("tool_step_dispatch", "resolve_tool_step_dispatch", "DispatchResolutionResult", "tool_step_route", "resolve_execution_route",
                  "RouteResolutionResult")
        referencing = []
        for path in production_files():
            rel = os.path.relpath(path, PY_ROOT).replace(os.sep, "/")
            text = read(rel)
            if any(token in text for token in tokens):
                referencing.append(rel)
        self.assertEqual(sorted(referencing), [DISPATCH_REL, ROUTE_REL])        # exact: the resolver and its single sanctioned consumer

    def test_nothing_imports_the_dispatch_layer(self):
        for path in production_files():
            rel = os.path.relpath(path, PY_ROOT).replace(os.sep, "/")
            self.assertNotIn("tool_step_dispatch", read(rel).replace("planning/tool_step_dispatch.py", "") if rel != DISPATCH_REL else "", rel)

    def test_the_guard_exemptions_are_limited_to_exactly_this_file(self):
        # every relaxed guard exempts the exact relative path "planning/tool_step_dispatch.py" and nothing else
        for rel, marker in (("tests/test_section6_tool_step_route_prompt716.py", 'rel == ROUTE_REL or rel == "planning/tool_step_dispatch.py"'),
                            ("tests/test_section6_agent_loop_routing_decision_prompt715.py", '== "planning/tool_step_dispatch.py"'),
                            ("tests/test_section6_agent_loop_handover_decision_prompt713.py", 'rel == "planning/tool_step_dispatch.py"')):
            self.assertEqual(read(rel).count("tool_step_dispatch"), 1, rel)
            self.assertIn(marker, read(rel), rel)
        # the exempted production tokens exist ONLY in the two sanctioned modules (see the test above), so the exemption cannot hide anything else
        for path in production_files():
            rel = os.path.relpath(path, PY_ROOT).replace(os.sep, "/")
            if rel in (DISPATCH_REL, ROUTE_REL):
                continue
            text = read(rel)
            for token in ('"section6_tool"', '"legacy_capability"', "execution_route", "resolve_execution_route", "tool_step_route", "tool_step_dispatch"):
                self.assertNotIn(token, text, (rel, token))
        # Prompt 712 consumers list changed by exactly one entry
        consumers = []
        for path in production_files():
            rel = os.path.relpath(path, PY_ROOT).replace(os.sep, "/")
            tree = ast.parse(read(rel))
            for n in ast.walk(tree):
                mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""] if isinstance(n, ast.ImportFrom) else []
                if any("tool_step" in m or "tool_capability_mapping" in m for m in mods):
                    consumers.append(rel)
        self.assertEqual(sorted(set(consumers)), ["agent/tool_step_runner.py", "planning/tool_step_agent_adapter.py", DISPATCH_REL, "planning/tool_step_executor.py", "planning/tool_step_retry.py"])

    def test_only_one_dispatch_module_and_no_other_new_dispatch_or_route_files(self):
        self.assertEqual(sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/") for f in glob.glob(os.path.join(PY_ROOT, "**", "*dispatch*.py"), recursive=True)
                                if os.sep + "tests" + os.sep not in f and os.path.relpath(f, PY_ROOT).replace(os.sep, "/") not in ("multimedia/image_operation_dispatcher.py", "multimedia/audio_operation_dispatcher.py", "web/web_request_dispatcher.py", "voice/voice_enrollment_dispatcher.py", "voice/voice_verification_dispatcher.py")),
                         [DISPATCH_REL])      # Prompt 755 (Section 8): one exact-path exemption for the multimedia image operation dispatcher; Prompt 768 adds the audio dispatcher; Prompt 782 adds the web request dispatcher; Prompt 794 adds the voice enrollment dispatcher; Prompt 803 adds the voice verification dispatcher
        self.assertEqual(sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/") for f in glob.glob(os.path.join(PY_ROOT, "**", "*route*.py"), recursive=True)
                                if os.sep + "tests" + os.sep not in f), [ROUTE_REL])

    def test_agent_loop_process_input_and_execution_are_untouched_and_unaware(self):
        self.assertEqual(sha("agent/agent_loop.py"), FROZEN_AGENT_LOOP_SHA256)
        self.assertEqual(sha("core/core.py"), FROZEN_CORE_SHA256)
        self.assertEqual(sum(1 for n in ast.walk(ast.parse(read("core/core.py"))) if isinstance(n, ast.FunctionDef) and n.name == "process_input"), 1)
        files = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/") for f in glob.glob(os.path.join(PY_ROOT, "execution", "*.py")))
        files.append("agent/agent_loop.py")
        self.assertEqual((digest(files), len(files)), (FROZEN_LEGACY_DIGEST, 27))
        for rel in files + ["core/core.py", "planning/plan.py", "planning/plan_manager.py", "planning/planner.py"]:
            text = read(rel)
            for token in ("tool_step", "dispatch_decision", "resolve_tool_step_dispatch", "DispatchResolutionResult", "resolve_execution_route"):
                self.assertNotIn(token, text, (rel, token))

    def test_plan_model_plan_manager_section4_section5_and_section6_modules_are_untouched(self):
        files = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/")
                       for f in glob.glob(os.path.join(PY_ROOT, "planning", "*.py")) + glob.glob(os.path.join(PY_ROOT, "tools", "*.py"))
                       if not any(k in f for k in ("tool_step_", "tool_capability_mapping")))
        self.assertEqual((digest(files), len(files)), (FROZEN_SECTION45_DIGEST, 31))
        self.assertEqual(sha("planning/plan_manager.py"), FROZEN_PLAN_MANAGER_SHA256)
        self.assertEqual(digest(sorted(SECTION6)), FROZEN_SECTION6_DIGEST)
        self.assertEqual(sha("planning/tool_step_agent_adapter.py"), FROZEN_ADAPTER_SHA256)
        self.assertEqual(PlanStep.__slots__, ("step_id", "description", "dependencies", "required_capabilities", "expected_output", "status", "input_data", "output_data"))

    def test_prompt716_resolver_behaviour_and_source_are_unchanged(self):
        src = read(ROUTE_REL)
        self.assertNotIn("dispatch", src)
        self.assertEqual([n for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        self.assertEqual(resolve_execution_route("section6_tool").code, ROUTE_CODE_EXPLICIT_SECTION6)
        self.assertEqual(resolve_execution_route("legacy_capability").code, ROUTE_CODE_EXPLICIT_LEGACY)
        self.assertEqual(resolve_execution_route().code, ROUTE_CODE_FALLBACK_ABSENT)
        self.assertEqual(resolve_execution_route("x").code, ROUTE_CODE_FALLBACK_UNKNOWN)
        self.assertEqual(resolve_execution_route(1).code, ROUTE_CODE_FALLBACK_MALFORMED)

    def test_adapter_still_has_no_route_or_dispatch_parameter(self):
        from planning.tool_step_agent_adapter import execute_agent_tool_step
        self.assertEqual(list(inspect.signature(execute_agent_tool_step).parameters),
                         ["plan", "step_id", "request", "registry", "max_attempts", "required_capabilities", "capability_mapping", "attempt_log"])

    def test_no_package_export_or_global_routing_registry(self):
        init = read("planning/__init__.py").lower()
        self.assertNotIn("dispatch", init)
        self.assertNotIn("route", init)

    def test_pristine_database_hash(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_no_pycache_or_pyc_files_in_the_project(self):
        found = []
        for root, dirs, files in os.walk(PY_ROOT):
            found += [os.path.join(root, d) for d in dirs if d == "__pycache__"]
            found += [os.path.join(root, f) for f in files if f.endswith(".pyc")]
        self.assertEqual(found, [])


class TestDocumentation(unittest.TestCase):
    def test_doc_exists_and_states_the_boundary(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for phrase in ("Prompt 716 decides the route", "Prompt 717 converts that route into a caller-facing dispatch decision",
                       "Neither module performs actual execution", "AgentLoop", "process_input", "intentionally deferred",
                       "resolve_tool_step_dispatch", "DispatchResolutionResult", "resolve_execution_route", "legacy_input", "tool_input",
                       "section6_tool", "legacy_capability", "fallback", "REJECTED_PAYLOAD_INVALID", "REJECTED_PAYLOAD_ABSENT", "ToolRequest",
                       "does not execute", "JSON-safe"):
            self.assertIn(phrase, text, phrase)


if __name__ == "__main__":
    unittest.main()
