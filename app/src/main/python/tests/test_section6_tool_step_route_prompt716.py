"""Prompt 716 - explicit tool-step execution route resolver (planning/tool_step_route.py).

The resolver is routing metadata only: a pure, stateless function over one caller-provided declaration. These tests pin its exact-match
behaviour, the legacy fallback, the result's immutability, and its isolation (no Plan/PlanStep/registry/tool/AgentLoop/execution
dependency, no wiring anywhere). Docs: docs/section6_tool_step_route_prompt716.md
"""
import ast
import copy
import enum
import glob
import hashlib
import inspect
import os
import subprocess
import sys
import unittest

from planning import tool_step_route as route_mod
from planning.plan import Plan, PlanStep
from planning.tool_step_route import (ROUTE_CODE_EXPLICIT_LEGACY, ROUTE_CODE_EXPLICIT_SECTION6, ROUTE_CODE_FALLBACK_ABSENT,
                                      ROUTE_CODE_FALLBACK_MALFORMED, ROUTE_CODE_FALLBACK_UNKNOWN, ROUTE_CODES,
                                      ROUTE_LEGACY_CAPABILITY, ROUTE_SECTION6_TOOL, VALID_ROUTES, RouteResolutionResult,
                                      resolve_execution_route)
from tests.test_section6_agent_loop_adapter_prompt714 import FROZEN_PLAN_MANAGER_SHA256
from tests.test_section6_agent_loop_handover_decision_prompt713 import (FROZEN_LEGACY_DIGEST, FROZEN_SECTION6_DIGEST, SECTION6,
                                                                        digest)
from tests.test_section6_agent_loop_routing_decision_prompt715 import (FROZEN_ADAPTER_SHA256, FROZEN_AGENT_LOOP_SHA256,
                                                                       FROZEN_CORE_SHA256)
from tests.test_section6_final_acceptance_prompt712 import FROZEN_SECTION45_DIGEST

from tests.section6_agent_loop_baseline_prompt719c import file_bytes as _baseline_file_bytes, read_text as _baseline_read_text   # Prompt 719-C: exact-path exemption for agent/agent_loop.py, see that helper
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_REL = "planning/tool_step_route.py"
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT)))), "docs", "section6_tool_step_route_prompt716.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def read(rel):
    return _baseline_read_text(rel)          # Prompt 719-C: agent/agent_loop.py is read without the sanctioned additions


def production_files():
    skip = os.sep + "tests" + os.sep
    return [p for p in glob.glob(os.path.join(PY_ROOT, "**", "*.py"), recursive=True) if skip not in p]


def sha(rel):
    return hashlib.sha256(_baseline_file_bytes(rel)).hexdigest()         # Prompt 719-C: agent_loop.py read without the sanctioned additions


def assert_legacy_fallback(tc, declaration, code):
    res = resolve_execution_route(declaration)
    tc.assertEqual((res.route, res.explicit, res.fallback, res.declaration_valid, res.code),
                   (ROUTE_LEGACY_CAPABILITY, False, True, False, code), type(declaration).__name__)   # never repr() the declaration
    tc.assertIsNot(res.route, ROUTE_SECTION6_TOOL)
    tc.assertFalse(res.is_section6_tool)
    return res


class Spy:
    """Records every protocol/dunder access so a test can prove the resolver never inspects a declaration beyond its type."""

    def __init__(self):
        self.calls = []

    def _note(self, name):
        self.calls.append(name)

    def __eq__(self, other):
        self._note("__eq__")
        return True

    def __ne__(self, other):
        self._note("__ne__")
        return False

    def __hash__(self):
        self._note("__hash__")
        return 1

    def __str__(self):
        self._note("__str__")
        return "section6_tool"

    def __repr__(self):
        self._note("__repr__")
        return "section6_tool"

    def __bool__(self):
        self._note("__bool__")
        return True

    def __len__(self):
        self._note("__len__")
        return 1

    def __iter__(self):
        self._note("__iter__")
        return iter(["section6_tool"])

    def __getitem__(self, key):
        self._note("__getitem__")
        return "section6_tool"

    def __contains__(self, item):
        self._note("__contains__")
        return True

    def __getattr__(self, name):
        if not name.startswith("__") and name != "calls":
            self._note("getattr:" + name)
        raise AttributeError(name)


class StrSpy(str):
    """A str subclass that carries the exact valid value and records any method the resolver might call."""
    calls = []

    def __eq__(self, other):
        StrSpy.calls.append("__eq__")
        return True

    def __ne__(self, other):
        StrSpy.calls.append("__ne__")
        return False

    def __hash__(self):
        StrSpy.calls.append("__hash__")
        return 1

    def strip(self, *a):
        StrSpy.calls.append("strip")
        return "section6_tool"

    def lower(self):
        StrSpy.calls.append("lower")
        return "section6_tool"

    def __str__(self):
        StrSpy.calls.append("__str__")
        return "section6_tool"


class PlainStrSub(str):
    pass


class StrEnum6(str, enum.Enum):
    TOOL = "section6_tool"
    LEGACY = "legacy_capability"


class LyingClass:
    @property
    def __class__(self):
        return str


# --------------------------------------------------------------------------------------------------------------------
class TestConstantsAndApi(unittest.TestCase):
    def test_route_constants_are_exactly_the_two_decided_values(self):
        self.assertEqual(ROUTE_LEGACY_CAPABILITY, "legacy_capability")
        self.assertEqual(ROUTE_SECTION6_TOOL, "section6_tool")
        self.assertEqual(VALID_ROUTES, ("legacy_capability", "section6_tool"))
        self.assertIs(type(ROUTE_LEGACY_CAPABILITY), str)
        self.assertIs(type(ROUTE_SECTION6_TOOL), str)

    def test_public_surface_and_signature(self):
        params = inspect.signature(resolve_execution_route).parameters
        self.assertEqual(list(params), ["declaration"])
        self.assertIsNone(params["declaration"].default)
        public = sorted(n for n in dir(route_mod) if not n.startswith("_"))
        self.assertEqual(public, sorted(["ROUTE_LEGACY_CAPABILITY", "ROUTE_SECTION6_TOOL", "ROUTE_CODE_EXPLICIT_LEGACY",
                                         "ROUTE_CODE_EXPLICIT_SECTION6", "ROUTE_CODE_FALLBACK_ABSENT", "ROUTE_CODE_FALLBACK_UNKNOWN",
                                         "ROUTE_CODE_FALLBACK_MALFORMED", "VALID_ROUTES", "ROUTE_CODES", "RouteResolutionResult",
                                         "resolve_execution_route"]))

    def test_result_type_and_fields(self):
        res = resolve_execution_route("section6_tool")
        self.assertIs(type(res), RouteResolutionResult)
        for field, kind in (("route", str), ("explicit", bool), ("fallback", bool), ("declaration_valid", bool), ("code", str), ("reason", str)):
            self.assertIs(type(getattr(res, field)), kind, field)
        self.assertIn(res.code, ROUTE_CODES)
        self.assertTrue(res.reason)

    def test_codes_are_distinct_and_have_distinct_reasons(self):
        self.assertEqual(len(set(ROUTE_CODES)), 5)
        reasons = {c: resolve_execution_route(d).reason for c, d in (
            (ROUTE_CODE_EXPLICIT_LEGACY, "legacy_capability"), (ROUTE_CODE_EXPLICIT_SECTION6, "section6_tool"),
            (ROUTE_CODE_FALLBACK_ABSENT, None), (ROUTE_CODE_FALLBACK_UNKNOWN, "x"), (ROUTE_CODE_FALLBACK_MALFORMED, 5))}
        self.assertEqual(len(set(reasons.values())), 5)


class TestExplicitValidDeclarations(unittest.TestCase):
    def test_exact_section6_tool(self):
        res = resolve_execution_route("section6_tool")
        self.assertEqual((res.route, res.explicit, res.fallback, res.declaration_valid, res.code),
                         (ROUTE_SECTION6_TOOL, True, False, True, ROUTE_CODE_EXPLICIT_SECTION6))
        self.assertTrue(res.is_section6_tool)
        self.assertFalse(res.is_legacy_capability)

    def test_exact_legacy_capability(self):
        res = resolve_execution_route("legacy_capability")
        self.assertEqual((res.route, res.explicit, res.fallback, res.declaration_valid, res.code),
                         (ROUTE_LEGACY_CAPABILITY, True, False, True, ROUTE_CODE_EXPLICIT_LEGACY))
        self.assertTrue(res.is_legacy_capability)
        self.assertFalse(res.is_section6_tool)

    def test_keyword_and_positional_calls_agree(self):
        self.assertEqual(resolve_execution_route(declaration="section6_tool"), resolve_execution_route("section6_tool"))

    def test_dynamically_built_exact_strings_are_valid(self):
        self.assertEqual(resolve_execution_route("".join(["section6", "_", "tool"])).route, ROUTE_SECTION6_TOOL)
        self.assertEqual(resolve_execution_route(b"legacy_capability".decode("ascii")).route, ROUTE_LEGACY_CAPABILITY)
        self.assertEqual(resolve_execution_route(str("section6_tool")).code, ROUTE_CODE_EXPLICIT_SECTION6)

    def test_explicit_legacy_is_distinguishable_from_fallback_legacy(self):
        explicit = resolve_execution_route("legacy_capability")
        for fallback in (resolve_execution_route(), resolve_execution_route("nope"), resolve_execution_route(3)):
            self.assertEqual(explicit.route, fallback.route)
            self.assertNotEqual(explicit, fallback)
            self.assertNotEqual(explicit.code, fallback.code)
            self.assertTrue(explicit.explicit and not explicit.fallback and explicit.declaration_valid)
            self.assertTrue(fallback.fallback and not fallback.explicit and not fallback.declaration_valid)

    def test_three_fallback_kinds_are_distinguishable(self):
        codes = {resolve_execution_route().code, resolve_execution_route("nope").code, resolve_execution_route(3).code}
        self.assertEqual(codes, {ROUTE_CODE_FALLBACK_ABSENT, ROUTE_CODE_FALLBACK_UNKNOWN, ROUTE_CODE_FALLBACK_MALFORMED})


class TestFallbackToLegacy(unittest.TestCase):
    def test_absent_declaration(self):
        res = resolve_execution_route()
        self.assertEqual((res.route, res.explicit, res.fallback, res.declaration_valid, res.code),
                         (ROUTE_LEGACY_CAPABILITY, False, True, False, ROUTE_CODE_FALLBACK_ABSENT))

    def test_none_is_absent(self):
        assert_legacy_fallback(self, None, ROUTE_CODE_FALLBACK_ABSENT)
        self.assertEqual(resolve_execution_route(None), resolve_execution_route())

    def test_empty_string_is_unknown(self):
        assert_legacy_fallback(self, "", ROUTE_CODE_FALLBACK_UNKNOWN)

    def test_unknown_strings(self):
        for value in ("tool", "legacy", "section6", "section6_tools", "section6_tool_", "_section6_tool", "section_6_tool", "section6-tool",
                      "section6tool", "section6 tool", "section6.tool", "section6_tool,legacy_capability", "legacy_capability,section6_tool",
                      "legacy_capability|section6_tool", "none", "None", "null", "auto", "default", "tool_step", "capability", "0", "1",
                      "true", "false", "section 6", "Section 6", "sect1on6_tool", "section6_t00l", "section6_tool\\n", "'section6_tool'",
                      '"section6_tool"', "section6_tool#", "section6_tool;", "execute_agent_tool_step", "resolve_execution_route"):
            assert_legacy_fallback(self, value, ROUTE_CODE_FALLBACK_UNKNOWN)

    def test_wrong_scalar_types_are_malformed(self):
        for value in (0, 1, -1, 2 ** 70, 1.5, float("nan"), float("inf"), True, False, 1j, b"section6_tool", b"legacy_capability",
                      bytearray(b"section6_tool"), memoryview(b"section6_tool"), Ellipsis, NotImplemented):
            assert_legacy_fallback(self, value, ROUTE_CODE_FALLBACK_MALFORMED)

    def test_containers_are_malformed_and_never_searched(self):
        for value in (["section6_tool"], ["legacy_capability"], [], [["section6_tool"]], {"section6_tool"}, set(), frozenset({"section6_tool"}),
                      ("section6_tool",), (), {"route": "section6_tool"}, {"section6_tool": True}, {}, range(3), iter(["section6_tool"]),
                      ("section6_tool", "legacy_capability"), {"declaration": "section6_tool", "route": "section6_tool"}):
            assert_legacy_fallback(self, value, ROUTE_CODE_FALLBACK_MALFORMED)

    def test_object_like_values_are_malformed(self):
        for value in (object(), type("Anything", (), {})(), type("Anything", (), {"route": "section6_tool"})(), lambda: "section6_tool",
                      len, str, int, ROUTE_MOD_TYPE, Plan, PlanStep, LyingClass()):
            assert_legacy_fallback(self, value, ROUTE_CODE_FALLBACK_MALFORMED)

    def test_object_like_values_are_never_inspected(self):
        spy = Spy()
        assert_legacy_fallback(self, spy, ROUTE_CODE_FALLBACK_MALFORMED)
        self.assertEqual(spy.calls, [])                 # no __eq__/__hash__/__str__/__repr__/__bool__/__len__/__iter__/getattr

    def test_plan_and_plan_step_objects_are_not_declarations(self):
        plan = Plan("p1", "g1", steps=[PlanStep("s1", "d", required_capabilities=["section6_tool"])], metadata={"route": "section6_tool"})
        for value in (plan, plan.steps[0], PlanStep("s1", "section6_tool", input_data={"route": "section6_tool"})):
            assert_legacy_fallback(self, value, ROUTE_CODE_FALLBACK_MALFORMED)

    def test_only_exact_str_type_can_declare(self):
        self.assertIs(type(LyingClass().__class__), type)     # the lie is visible through __class__ ...
        assert_legacy_fallback(self, LyingClass(), ROUTE_CODE_FALLBACK_MALFORMED)       # ... but the resolver looks at the real type only


ROUTE_MOD_TYPE = type(route_mod)


class TestNoNormalisationOrFuzzyMatching(unittest.TestCase):
    def test_whitespace_variants_are_unknown(self):
        for base in ("section6_tool", "legacy_capability"):
            for value in (" " + base, base + " ", " " + base + " ", "\t" + base, base + "\t", "\n" + base, base + "\n", base + "\r\n",
                          "\u00a0" + base, base + "\u00a0", "\u2003" + base, base + "\u200b", "\ufeff" + base, "\u200b" + base,
                          base.replace("_", " "), base.replace("_", "\t"), base[:4] + " " + base[4:], base + "\x00", "\x00" + base,
                          base.replace("_", "__"), base.replace("_", "_ ")):
                assert_legacy_fallback(self, value, ROUTE_CODE_FALLBACK_UNKNOWN)

    def test_case_variants_are_unknown(self):
        for base in ("section6_tool", "legacy_capability"):
            for value in (base.upper(), base.title(), base.capitalize(), base.swapcase(), base.casefold().upper(),
                          "".join(c.upper() if i % 2 else c for i, c in enumerate(base))):
                if value != base:
                    assert_legacy_fallback(self, value, ROUTE_CODE_FALLBACK_UNKNOWN)
        for value in ("SECTION6_TOOL", "Section6_Tool", "section6_TOOL", "LEGACY_CAPABILITY", "Legacy_Capability", "legacy_CAPABILITY"):
            assert_legacy_fallback(self, value, ROUTE_CODE_FALLBACK_UNKNOWN)

    def test_unicode_lookalikes_and_normalisation_forms_are_unknown(self):
        for value in ("\uff53ection6_tool", "s\u0435ction6_tool", "section\uff16_tool", "section6_t\u043eol", "\u212aegacy_capability",
                      "legacy_capabilit\u0443", "section6\uff3ftool", "section6_tool\u0301", "\u017fection6_tool"):
            assert_legacy_fallback(self, value, ROUTE_CODE_FALLBACK_UNKNOWN)

    def test_no_single_edit_of_a_valid_value_is_ever_accepted(self):
        alphabet = "abcxyz_ 0169-\t\n\u00a0S"
        for valid in ("section6_tool", "legacy_capability"):
            variants = set()
            for i in range(len(valid) + 1):
                for ch in alphabet:
                    variants.add(valid[:i] + ch + valid[i:])                    # insertion
                    if i < len(valid):
                        variants.add(valid[:i] + ch + valid[i + 1:])            # substitution
                if i < len(valid):
                    variants.add(valid[:i] + valid[i + 1:])                     # deletion
                    variants.add(valid[:i] + valid[i].upper() + valid[i + 1:])  # case flip
            variants.discard(valid)
            self.assertGreater(len(variants), 300)
            for value in sorted(variants):
                res = resolve_execution_route(value)
                self.assertEqual((res.route, res.code, res.explicit, res.declaration_valid),
                                 (ROUTE_LEGACY_CAPABILITY, ROUTE_CODE_FALLBACK_UNKNOWN, False, False), repr(value))

    def test_values_are_not_trimmed_or_split_or_prefix_matched(self):
        assert_legacy_fallback(self, "section6_tool extra", ROUTE_CODE_FALLBACK_UNKNOWN)
        assert_legacy_fallback(self, "extra section6_tool", ROUTE_CODE_FALLBACK_UNKNOWN)
        assert_legacy_fallback(self, "section6_tool\nlegacy_capability", ROUTE_CODE_FALLBACK_UNKNOWN)
        assert_legacy_fallback(self, "section6_tool" * 2, ROUTE_CODE_FALLBACK_UNKNOWN)
        assert_legacy_fallback(self, "section6", ROUTE_CODE_FALLBACK_UNKNOWN)


class TestStrSubclassAndStringLikeEdgeCases(unittest.TestCase):
    def test_plain_str_subclass_with_valid_value_is_malformed(self):
        for value in (PlainStrSub("section6_tool"), PlainStrSub("legacy_capability")):
            self.assertEqual(value, value.__str__())                               # it really looks valid
            assert_legacy_fallback(self, value, ROUTE_CODE_FALLBACK_MALFORMED)

    def test_str_enum_members_are_malformed(self):
        for value in (StrEnum6.TOOL, StrEnum6.LEGACY):
            assert_legacy_fallback(self, value, ROUTE_CODE_FALLBACK_MALFORMED)
        self.assertEqual(resolve_execution_route(StrEnum6.TOOL.value).route, ROUTE_SECTION6_TOOL)   # the plain value is fine

    def test_str_subclass_methods_are_never_called(self):
        StrSpy.calls = []
        for value in (StrSpy("section6_tool"), StrSpy("legacy_capability"), StrSpy("anything")):
            assert_legacy_fallback(self, value, ROUTE_CODE_FALLBACK_MALFORMED)
        self.assertEqual(StrSpy.calls, [])

    def test_str_subclass_with_lying_eq_cannot_reach_the_tool_route(self):
        res = resolve_execution_route(StrSpy("not a route"))
        self.assertEqual(res.route, ROUTE_LEGACY_CAPABILITY)
        self.assertFalse(res.declaration_valid)

    def test_result_route_is_a_plain_constant_never_the_input_object(self):
        for value in ("section6_tool", "legacy_capability", "x", None, 1, PlainStrSub("section6_tool")):
            res = resolve_execution_route(value)
            self.assertIs(type(res.route), str)
            self.assertIn(res.route, VALID_ROUTES)
            self.assertIn(res.route, (ROUTE_LEGACY_CAPABILITY, ROUTE_SECTION6_TOOL))
        sub = PlainStrSub("section6_tool")
        self.assertIsNot(resolve_execution_route(sub).route, sub)

    def test_declaration_is_not_mutated_and_not_retained(self):
        container = {"route": "section6_tool"}
        before = copy.deepcopy(container)
        res = resolve_execution_route(container)
        self.assertEqual(container, before)
        container["route"] = "legacy_capability"
        self.assertEqual((res.route, res.code), (ROUTE_LEGACY_CAPABILITY, ROUTE_CODE_FALLBACK_MALFORMED))
        self.assertEqual(sorted(RouteResolutionResult.__slots__), sorted(["_route", "_explicit", "_fallback", "_declaration_valid", "_code"]))


class TestSection6RouteIsImpossibleWithoutExactDeclaration(unittest.TestCase):
    def candidates(self):
        yield None
        yield from ("", " ", "section6", "legacy_capability", "SECTION6_TOOL", " section6_tool", "section6_tool ", "tool")
        yield from (0, 1, True, False, 1.0, b"section6_tool", ["section6_tool"], ("section6_tool",), {"section6_tool"}, {"a": "section6_tool"},
                    object(), Spy(), PlainStrSub("section6_tool"), StrEnum6.TOOL, StrSpy("section6_tool"), LyingClass(), Plan, PlanStep, str, len)
        yield "section6_tool"

    def test_route_is_section6_if_and_only_if_declaration_is_exactly_the_string(self):
        seen_tool = 0
        for value in self.candidates():
            res = resolve_execution_route(value)
            exact = type(value) is str and value == "section6_tool"
            self.assertEqual(res.route == ROUTE_SECTION6_TOOL, exact, repr(type(value)))
            self.assertEqual(res.is_section6_tool, exact)
            self.assertEqual(res.explicit and res.route == ROUTE_SECTION6_TOOL, exact)
            seen_tool += exact
        self.assertEqual(seen_tool, 1)

    def test_every_non_tool_declaration_falls_back_or_is_explicit_legacy(self):
        for value in self.candidates():
            res = resolve_execution_route(value)
            if res.route != ROUTE_SECTION6_TOOL:
                self.assertEqual(res.route, ROUTE_LEGACY_CAPABILITY)
                self.assertEqual(res.fallback or res.code == ROUTE_CODE_EXPLICIT_LEGACY, True)

    def test_flag_combinations_are_consistent(self):
        for value in self.candidates():
            res = resolve_execution_route(value)
            self.assertEqual(res.explicit, res.declaration_valid)
            self.assertNotEqual(res.explicit, res.fallback)                    # exactly one of explicit / fallback
            if res.fallback:
                self.assertEqual(res.route, ROUTE_LEGACY_CAPABILITY)
                self.assertFalse(res.declaration_valid)

    def test_no_module_state_can_change_the_answer(self):
        self.assertIs(type(route_mod.VALID_ROUTES), tuple)
        self.assertIs(type(route_mod.ROUTE_CODES), tuple)
        self.assertEqual(resolve_execution_route("section6_tool").route, ROUTE_SECTION6_TOOL)
        self.assertEqual(resolve_execution_route("x").route, ROUTE_LEGACY_CAPABILITY)
        self.assertEqual(resolve_execution_route().route, ROUTE_LEGACY_CAPABILITY)

    def test_result_cannot_be_forged(self):
        for token in (None, object(), 0, "token"):
            with self.assertRaises(TypeError):
                RouteResolutionResult(token, ROUTE_SECTION6_TOOL, True, False, True, ROUTE_CODE_EXPLICIT_SECTION6)
        with self.assertRaises(TypeError):
            RouteResolutionResult()


class TestDeterminismAndStatelessness(unittest.TestCase):
    INPUTS = ("section6_tool", "legacy_capability", None, "", "x", " section6_tool", 5, ["section6_tool"], PlainStrSub("section6_tool"))

    def test_repeated_resolution_is_identical(self):
        for value in self.INPUTS:
            first = resolve_execution_route(value)
            for _ in range(200):
                again = resolve_execution_route(value)
                self.assertEqual(again, first)
                self.assertEqual(again.as_dict(), first.as_dict())
                self.assertEqual(hash(again), hash(first))

    def test_order_of_calls_does_not_matter(self):
        expected = {i: resolve_execution_route(v) for i, v in enumerate(self.INPUTS)}
        for order in (list(range(len(self.INPUTS))), list(reversed(range(len(self.INPUTS)))), [4, 0, 8, 2, 6, 1, 7, 3, 5]):
            for _ in range(3):
                for i in order:
                    self.assertEqual(resolve_execution_route(self.INPUTS[i]), expected[i])

    def test_a_tool_declaration_does_not_leak_into_later_calls(self):
        self.assertEqual(resolve_execution_route("section6_tool").route, ROUTE_SECTION6_TOOL)
        for _ in range(5):
            self.assertEqual(resolve_execution_route().code, ROUTE_CODE_FALLBACK_ABSENT)
            self.assertEqual(resolve_execution_route(None).route, ROUTE_LEGACY_CAPABILITY)

    def test_module_holds_no_mutable_module_state(self):
        tree = ast.parse(read(ROUTE_REL))
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))], [])
        for name, value in vars(route_mod).items():
            if name.startswith("__"):
                continue
            self.assertTrue(isinstance(value, (str, tuple, type, type(resolve_execution_route), type(len))) or value is route_mod._CREATE_TOKEN,
                            (name, type(value)))
        self.assertEqual(type(route_mod._REASONS), tuple)
        self.assertTrue(all(type(pair) is tuple for pair in route_mod._REASONS))

    def test_thread_free_and_io_free_source(self):
        src = read(ROUTE_REL)
        for word in ("import socket", "import threading", "import sqlite3", "import time", "import random", "import os", "import sys",
                     "open(", "global ", "print(", "logging", "datetime"):
            self.assertNotIn(word, src, word)


class TestImmutableAndFreshResults(unittest.TestCase):
    def test_attributes_cannot_be_set_or_deleted(self):
        res = resolve_execution_route("section6_tool")
        for field in ("route", "explicit", "fallback", "declaration_valid", "code", "reason", "is_section6_tool", "_route", "_code", "new_field"):
            with self.assertRaises(AttributeError, msg=field):
                setattr(res, field, "legacy_capability")
            with self.assertRaises(AttributeError, msg=field):
                delattr(res, field)
        self.assertEqual((res.route, res.explicit, res.code), (ROUTE_SECTION6_TOOL, True, ROUTE_CODE_EXPLICIT_SECTION6))

    def test_no_instance_dict_and_slots_only(self):
        res = resolve_execution_route("x")
        self.assertFalse(hasattr(res, "__dict__"))
        self.assertEqual(len(RouteResolutionResult.__slots__), 5)

    def test_result_cannot_be_subclassed(self):
        with self.assertRaises(TypeError):
            type("Sub", (RouteResolutionResult,), {})

    def test_results_are_fresh_objects_but_equal(self):
        a, b = resolve_execution_route("section6_tool"), resolve_execution_route("section6_tool")
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, resolve_execution_route("legacy_capability"))
        self.assertNotEqual(a, a.as_dict())
        self.assertNotEqual(a, "section6_tool")

    def test_as_dict_returns_a_fresh_copy_each_time(self):
        res = resolve_execution_route("section6_tool")
        d1, d2 = res.as_dict(), res.as_dict()
        self.assertIsNot(d1, d2)
        self.assertEqual(d1, d2)
        self.assertEqual(sorted(d1), ["code", "declaration_valid", "explicit", "fallback", "reason", "route"])
        d1["route"] = "legacy_capability"
        d1["explicit"] = False
        d1.clear()
        self.assertEqual(res.as_dict(), d2)
        self.assertEqual(res.route, ROUTE_SECTION6_TOOL)
        self.assertEqual(resolve_execution_route("section6_tool").as_dict(), d2)

    def test_result_survives_deepcopy_unchanged(self):
        res = resolve_execution_route("legacy_capability")
        self.assertEqual(copy.deepcopy(res), res)
        self.assertEqual(copy.copy(res), res)

    def test_repr_is_data_only(self):
        text = repr(resolve_execution_route("section6_tool"))
        self.assertIn("route='section6_tool'", text)
        self.assertIn("EXPLICIT_SECTION6_TOOL", text)


# --------------------------------------------------------------------------------------------------------------------
BLOCKED_MODULES = ("planning.plan", "planning.plan_manager", "planning.plan_builder", "planning.plan_validation", "planning.goal_manager",
                   "planning.tool_step_agent_adapter", "planning.tool_step_bridge", "planning.tool_step_executor", "planning.tool_step_retry",
                   "planning.tool_capability_mapping", "tools", "tools.tool_registry", "tools.tool_request", "execution",
                   "execution.execution_engine", "execution.plan_execution_controller", "agent", "agent.agent_loop", "core", "core.core",
                   "capabilities", "ael")

ISOLATION_SCRIPT = r"""
import sys
for name in %r:
    sys.modules[name] = None                      # any import of these raises ImportError
import planning.tool_step_route as m
loaded = sorted(n for n in sys.modules if sys.modules[n] is not None and n.split(".")[0] in ("tools", "execution", "agent", "core", "ael", "capabilities"))
assert not loaded, loaded
assert sorted(n for n in sys.modules if n.startswith("planning.") and sys.modules[n] is not None) == ["planning.tool_step_route"]
assert m.resolve_execution_route("section6_tool").route == "section6_tool"
assert m.resolve_execution_route("legacy_capability").explicit is True
assert m.resolve_execution_route().route == "legacy_capability"
assert m.resolve_execution_route({"route": "section6_tool"}).code == "FALLBACK_MALFORMED_DECLARATION"
print("ISOLATED-OK")
""" % (BLOCKED_MODULES,)


class TestIsolationFromPlanningToolsAgentAndExecution(unittest.TestCase):
    def test_module_imports_nothing_at_all(self):
        tree = ast.parse(read(ROUTE_REL))
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [])                                   # not even the standard library

    def test_module_works_with_every_project_layer_blocked_from_import(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run([sys.executable, "-c", ISOLATION_SCRIPT], cwd=PY_ROOT, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, "ISOLATED-OK"), proc.stderr)

    def test_code_names_do_not_mention_plans_registries_tools_agents_or_execution(self):
        tree = ast.parse(read(ROUTE_REL))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        names |= {a.arg for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) for a in n.args.args}
        for name in names:
            lowered = name.lower()
            if name.startswith("ROUTE_") or name in ("VALID_ROUTES", "is_legacy_capability", "is_section6_tool"):    # route names, not capability logic
                continue
            for word in ("plan", "step", "registry", "handler", "capabilit", "permission", "toolrequest", "tool_request", "agent", "loop",
                         "process_input", "retry", "adapter", "bridge", "executor", "engine", "state", "spec"):
                self.assertNotIn(word, lowered, name)

    def test_only_the_declaration_parameter_is_read(self):
        self.assertEqual(list(inspect.signature(resolve_execution_route).parameters), ["declaration"])
        tree = ast.parse(read(ROUTE_REL))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "resolve_execution_route")
        loaded = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        self.assertEqual(loaded, {"declaration", "type", "str", "_make", "ROUTE_LEGACY_CAPABILITY", "ROUTE_SECTION6_TOOL",
                                  "ROUTE_CODE_FALLBACK_ABSENT", "ROUTE_CODE_FALLBACK_MALFORMED", "ROUTE_CODE_EXPLICIT_SECTION6",
                                  "ROUTE_CODE_EXPLICIT_LEGACY", "ROUTE_CODE_FALLBACK_UNKNOWN"})
        self.assertEqual([n for n in ast.walk(fn) if isinstance(n, ast.Attribute)], [])         # no attribute access on the declaration

    def test_no_toolrequest_is_constructed_or_capability_resolved(self):
        src = read(ROUTE_REL)
        code = ast.parse(src)
        strings_and_names = {n.id for n in ast.walk(code) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(code) if isinstance(n, ast.Attribute)}
        self.assertEqual({n for n in strings_and_names if "ToolRequest" in n or "create_tool_request" in n or "map_required_capabilities" in n}, set())
        for word in ("InProcessToolRegistry", "ToolSpec", "preflight", "validate_plan", "get_ready_plan_steps"):
            self.assertNotIn(word, src, word)

    def test_route_declaration_cannot_be_derived_from_a_plan_or_registry_shape(self):
        # a plan/step whose every field names the tool route is still just an opaque object to the resolver
        plan = Plan("p1", "g1", steps=[PlanStep("section6_tool", "section6_tool", required_capabilities=["section6_tool"])],
                    metadata={"route": "section6_tool", "execution_authorized": True})
        self.assertEqual(resolve_execution_route(plan).route, ROUTE_LEGACY_CAPABILITY)
        self.assertEqual(resolve_execution_route(plan.steps[0]).route, ROUTE_LEGACY_CAPABILITY)
        self.assertEqual(resolve_execution_route(plan.metadata).route, ROUTE_LEGACY_CAPABILITY)
        self.assertEqual(resolve_execution_route(plan.metadata["route"]).route, ROUTE_SECTION6_TOOL)   # only the caller's explicit value counts


class TestNothingIsWiredAndProtectedFilesAreUntouched(unittest.TestCase):
    def test_no_production_module_references_the_resolver(self):
        for path in production_files():
            rel = os.path.relpath(path, PY_ROOT).replace(os.sep, "/")
            if rel == ROUTE_REL or rel == "planning/tool_step_dispatch.py":    # Prompt 717: the one sanctioned consumer of the resolver (exact path, test-enforced)
                continue
            text = read(rel)
            for token in ("tool_step_route", "resolve_execution_route", "RouteResolutionResult", "ROUTE_SECTION6_TOOL", "ROUTE_LEGACY_CAPABILITY"):
                self.assertNotIn(token, text, (rel, token))

    def test_agent_loop_process_input_and_execution_are_untouched_and_unaware(self):
        self.assertEqual(sha("agent/agent_loop.py"), FROZEN_AGENT_LOOP_SHA256)
        self.assertEqual(sha("core/core.py"), FROZEN_CORE_SHA256)
        files = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/") for f in glob.glob(os.path.join(PY_ROOT, "execution", "*.py")))
        files.append("agent/agent_loop.py")
        self.assertEqual((digest(files), len(files)), (FROZEN_LEGACY_DIGEST, 27))
        for rel in ("agent/agent_loop.py", "core/core.py"):
            self.assertNotIn("tool_step", read(rel), rel)
        for path in glob.glob(os.path.join(PY_ROOT, "execution", "*.py")):
            text = read(os.path.relpath(path, PY_ROOT))
            for token in ("tool_step_route", "resolve_execution_route", "section6_tool"):
                self.assertNotIn(token, text, path)

    def test_plan_model_plan_manager_section4_and_section5_are_untouched(self):
        files = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/")
                       for f in glob.glob(os.path.join(PY_ROOT, "planning", "*.py")) + glob.glob(os.path.join(PY_ROOT, "tools", "*.py"))
                       if not any(k in f for k in ("tool_step_", "tool_capability_mapping")))
        self.assertEqual((digest(files), len(files)), (FROZEN_SECTION45_DIGEST, 31))     # includes plan.py, plan_builder.py, tools/*
        self.assertEqual(sha("planning/plan_manager.py"), FROZEN_PLAN_MANAGER_SHA256)
        self.assertEqual(PlanStep.__slots__, ("step_id", "description", "dependencies", "required_capabilities", "expected_output", "status",
                                              "input_data", "output_data"))

    def test_existing_section6_modules_and_adapter_are_untouched(self):
        self.assertEqual(digest(sorted(SECTION6)), FROZEN_SECTION6_DIGEST)
        self.assertEqual(sha("planning/tool_step_agent_adapter.py"), FROZEN_ADAPTER_SHA256)

    def test_adapter_still_has_no_route_parameter(self):
        from planning.tool_step_agent_adapter import execute_agent_tool_step
        self.assertEqual(list(inspect.signature(execute_agent_tool_step).parameters),
                         ["plan", "step_id", "request", "registry", "max_attempts", "required_capabilities", "capability_mapping", "attempt_log"])

    def test_route_module_is_the_only_planning_file_added_by_this_prompt(self):
        self.assertTrue(os.path.isfile(os.path.join(PY_ROOT, ROUTE_REL)))
        self.assertEqual(sorted(os.path.basename(f) for f in glob.glob(os.path.join(PY_ROOT, "**", "*route*.py"), recursive=True)
                                if os.sep + "tests" + os.sep not in f), ["tool_step_route.py"])

    def test_no_global_routing_registry_or_package_export(self):
        self.assertNotIn("route", read("planning/__init__.py").lower())
        self.assertFalse([n for n in dir(route_mod) if "registry" in n.lower() or "register" in n.lower()])

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
    def test_doc_exists_and_covers_required_topics(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for phrase in ("section6_tool", "legacy_capability", "resolve_execution_route", "RouteResolutionResult", "explicit", "fall back",
                       "no inference", "does not validate", "does not execute", "Prompt 717", "AgentLoop", "process_input"):
            self.assertIn(phrase, text, phrase)


if __name__ == "__main__":
    unittest.main()
