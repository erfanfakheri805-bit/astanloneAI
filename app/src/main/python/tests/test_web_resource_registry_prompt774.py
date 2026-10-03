"""Prompt 774 - Section 9 web resource registry (`web.web_resource_registry`)."""
import ast
import copy
import hashlib
import json
import os
import pickle
import unittest

from web import web_resource_registry as reg
from web.web_resource import WebResource, create_web_resource
from web.web_resource_registry import (WebResourceLookupResult, WebResourceRegistry, WebResourceRegistryResult,
                                             create_web_resource_registry)

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_resource_registry_prompt774.md")
MODULE = os.path.join(PY_ROOT, "web", "web_resource_registry.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def res(resource_id="res_1", **over):
    data = {"resource_id": resource_id, "url": "https://example.org/" + resource_id, "title": "Title " + resource_id, "resource_type": "page"}
    data.update(over)
    r = create_web_resource(data)
    assert r.ok, r.failures
    return r.resource


def three():
    return [res("a"), res("b"), res("c")]


class TestValidRegistry(unittest.TestCase):
    def test_1_valid_list_builds_a_registry(self):
        items = three()
        r = create_web_resource_registry(items)
        self.assertIs(type(r), WebResourceRegistryResult)
        self.assertTrue(r.ok)
        self.assertEqual(r.failures, [])
        self.assertEqual(r.codes(), [])
        self.assertIs(type(r.registry), WebResourceRegistry)
        self.assertEqual(r.registry.resources, tuple(items))
        self.assertEqual(r.registry.resource_ids, ("a", "b", "c"))

    def test_2_valid_tuple_builds_the_same_registry(self):
        items = three()
        self.assertEqual(create_web_resource_registry(tuple(items)).registry, create_web_resource_registry(list(items)).registry)

    def test_3_the_registered_objects_are_the_very_same_resources(self):
        items = three()
        r = create_web_resource_registry(items).registry
        for given, stored in zip(items, r.resources):
            self.assertIs(given, stored)

    def test_4_single_resource_registry(self):
        r = create_web_resource_registry([res("only")])
        self.assertTrue(r.ok)
        self.assertEqual(r.registry.resource_ids, ("only",))

    def test_5_equal_but_distinct_resources_with_different_ids_are_fine(self):
        self.assertTrue(create_web_resource_registry([res("a"), res("b", url="https://example.org/a", title="Title a")]).ok)

    def test_6_ids_differing_only_by_case_or_whitespace_are_distinct(self):
        r = create_web_resource_registry([res("a"), res("A"), res(" a"), res("a ")])
        self.assertTrue(r.ok)
        self.assertEqual(r.registry.resource_ids, ("a", "A", " a", "a "))


class TestEmptyRegistry(unittest.TestCase):
    def test_7_empty_list_and_tuple_are_valid(self):
        for empty in ([], ()):
            with self.subTest(empty=empty):
                r = create_web_resource_registry(empty)
                self.assertTrue(r.ok)
                self.assertEqual(r.registry.resources, ())
                self.assertEqual(r.registry.resource_ids, ())
                self.assertEqual(r.registry.to_dict(), {"resources": []})

    def test_8_empty_registries_are_equal_and_lookups_miss(self):
        a, b = create_web_resource_registry([]).registry, create_web_resource_registry(()).registry
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.lookup("x").codes(), [reg.FAILURE_RESOURCE_NOT_FOUND])


class TestCollectionValidation(unittest.TestCase):
    def test_9_wrong_collection_types_are_rejected(self):
        class L(list):
            pass

        class T(tuple):
            pass
        items = three()
        bads = [None, "abc", b"abc", 1, True, 1.5, {}, {"a": items[0]}, set(items), frozenset(items), iter(items), (a for a in items),
                range(3), L(items), T(items), items[0], object(), {"resources": items}]
        for bad in bads:
            with self.subTest(bad=type(bad).__name__):
                r = create_web_resource_registry(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.registry)
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_COLLECTION])
                self.assertEqual(r.failures[0]["field"], "resources")

    def test_10_a_generator_is_not_consumed(self):
        gen = (a for a in three())
        create_web_resource_registry(gen)
        self.assertEqual(len(list(gen)), 3)

    def test_11_wrong_item_types_are_rejected_by_position(self):
        class Sub(dict):
            pass
        valid = res("a")
        for bad in (None, 1, "a", {"resource_id": "x"}, valid.to_dict(), object(), [valid], (valid,), b"a", True):
            with self.subTest(bad=type(bad).__name__):
                r = create_web_resource_registry([valid, bad])
                self.assertFalse(r.ok)
                self.assertIsNone(r.registry)
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_RESOURCE])
                self.assertIn("resources[1]", r.failures[0]["message"])

    def test_12_look_alikes_and_other_types_are_rejected(self):
        class Fake:
            resource_id = "z"
            url = "https://example.org/z"
            title = ""
            resource_type = "page"

            def to_dict(self):
                return {}
        self.assertEqual(create_web_resource_registry([Fake()]).codes(), [reg.FAILURE_INVALID_RESOURCE])
        self.assertEqual(create_web_resource_registry([res("a").to_dict()]).codes(), [reg.FAILURE_INVALID_RESOURCE])

    def test_13_every_bad_item_is_reported_in_input_order(self):
        r = create_web_resource_registry([None, res("a"), 5, res("b"), "x"])
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_RESOURCE] * 3)
        self.assertEqual([("resources[%d]" % i) in f["message"] for f, i in zip(r.failures, (0, 2, 4))], [True] * 3)

    def test_14_a_failed_build_returns_no_registry_for_any_bad_input(self):
        for bad in (None, [None], [res("a"), res("a")]):
            self.assertIsNone(create_web_resource_registry(bad).registry)


class TestDuplicateIds(unittest.TestCase):
    def test_15_duplicate_ids_are_rejected(self):
        r = create_web_resource_registry([res("a"), res("b"), res("a", title="other")])
        self.assertFalse(r.ok)
        self.assertIsNone(r.registry)
        self.assertEqual(r.codes(), [reg.FAILURE_DUPLICATE_RESOURCE_ID])
        self.assertIn("resources[2]", r.failures[0]["message"])
        self.assertEqual(r.failures[0]["field"], "resources")

    def test_16_the_very_same_object_twice_is_a_duplicate(self):
        a = res("a")
        self.assertEqual(create_web_resource_registry([a, a]).codes(), [reg.FAILURE_DUPLICATE_RESOURCE_ID])
        self.assertEqual(create_web_resource_registry((a, a)).codes(), [reg.FAILURE_DUPLICATE_RESOURCE_ID])

    def test_17_equal_distinct_objects_are_duplicates_too(self):
        self.assertEqual(create_web_resource_registry([res("a"), res("a")]).codes(), [reg.FAILURE_DUPLICATE_RESOURCE_ID])

    def test_18_each_extra_repeat_is_reported(self):
        r = create_web_resource_registry([res("a"), res("a", title="2"), res("a", title="3"), res("b"), res("b", title="2")])
        self.assertEqual(r.codes(), [reg.FAILURE_DUPLICATE_RESOURCE_ID] * 3)

    def test_19_duplicate_ids_are_exact_comparisons_only(self):
        self.assertTrue(create_web_resource_registry([res("a"), res("A")]).ok)
        self.assertTrue(create_web_resource_registry([res("a"), res("a ")]).ok)
        self.assertTrue(create_web_resource_registry([res("a"), res("\u00e1")]).ok)

    def test_20_a_bad_item_is_not_also_counted_as_a_duplicate(self):
        r = create_web_resource_registry([res("a"), None, res("a")])
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_RESOURCE, reg.FAILURE_DUPLICATE_RESOURCE_ID])

    def test_21_mixed_problems_are_reported_together_in_input_order(self):
        r = create_web_resource_registry([res("a"), 3, res("a"), None])
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_RESOURCE, reg.FAILURE_DUPLICATE_RESOURCE_ID, reg.FAILURE_INVALID_RESOURCE])


class TestOrdering(unittest.TestCase):
    def test_22_input_order_is_preserved_and_never_sorted(self):
        items = [res("z"), res("m"), res("a"), res("B")]
        r = create_web_resource_registry(items).registry
        self.assertEqual(r.resource_ids, ("z", "m", "a", "B"))
        self.assertEqual([a["resource_id"] for a in r.to_dict()["resources"]], ["z", "m", "a", "B"])

    def test_23_a_different_order_is_a_different_registry(self):
        a, b, c = three()
        r1 = create_web_resource_registry([a, b, c]).registry
        r2 = create_web_resource_registry([c, b, a]).registry
        self.assertNotEqual(r1, r2)
        self.assertEqual(len({r1, r2}), 2)

    def test_24_list_and_tuple_input_give_the_same_order(self):
        items = [res("q"), res("p")]
        self.assertEqual(create_web_resource_registry(items).registry.resource_ids, create_web_resource_registry(tuple(items)).registry.resource_ids)


class TestInternalImmutability(unittest.TestCase):
    def test_25_resources_and_resource_ids_are_tuples(self):
        r = create_web_resource_registry(three()).registry
        self.assertIs(type(r.resources), tuple)
        self.assertIs(type(r.resource_ids), tuple)
        self.assertIs(r.resources, r.resources)

    def test_26_later_edits_to_the_input_list_do_not_reach_the_registry(self):
        items = three()
        r = create_web_resource_registry(items).registry
        items.append(res("d"))
        items[0] = res("zzz")
        items.clear()
        self.assertEqual(r.resource_ids, ("a", "b", "c"))
        self.assertEqual(r.lookup("a").resource.resource_id, "a")

    def test_27_the_factory_does_not_change_the_input(self):
        items = three()
        snapshot = list(items)
        create_web_resource_registry(items)
        self.assertEqual(items, snapshot)
        for x, y in zip(items, snapshot):
            self.assertIs(x, y)
        bad = [res("a"), None, res("a")]
        snap_bad = list(bad)
        create_web_resource_registry(bad)
        self.assertEqual(bad, snap_bad)
        tup = tuple(items)
        create_web_resource_registry(tup)
        self.assertEqual(tup, tuple(snapshot))

    def test_28_registry_attributes_cannot_be_assigned_deleted_or_added(self):
        r = create_web_resource_registry(three()).registry
        for name in ("resources", "resource_ids", "_resources", "lookup", "extra"):
            with self.assertRaises(AttributeError, msg=name):
                setattr(r, name, ())
        for name in ("resources", "resource_ids", "_resources"):
            with self.assertRaises(AttributeError, msg=name):
                delattr(r, name)
        with self.assertRaises(AttributeError):
            object.__setattr__(r, "extra", 1)
        self.assertFalse(hasattr(r, "__dict__"))
        self.assertEqual(r.resource_ids, ("a", "b", "c"))

    def test_29_the_registry_has_no_mutating_methods(self):
        public = sorted(n for n in dir(WebResourceRegistry) if not n.startswith("_"))
        self.assertEqual(public, ["lookup", "resource_ids", "resources", "to_dict"])
        self.assertEqual(WebResourceRegistry.__slots__, ("_resources",))

    def test_30_stored_resources_stay_immutable(self):
        r = create_web_resource_registry(three()).registry
        with self.assertRaises(AttributeError):
            r.resources[0].name = "x"
        with self.assertRaises(TypeError):
            r.resources[0] = None


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.items = three()
        self.r = create_web_resource_registry(self.items).registry

    def test_31_found_returns_the_registered_object(self):
        for item in self.items:
            res = self.r.lookup(item.resource_id)
            self.assertIs(type(res), WebResourceLookupResult)
            self.assertTrue(res.found)
            self.assertIs(res.resource, item)
            self.assertEqual(res.failures, [])
            self.assertEqual(res.codes(), [])

    def test_32_a_missing_id_gives_a_deterministic_not_found_result(self):
        res = self.r.lookup("missing")
        self.assertFalse(res.found)
        self.assertIsNone(res.resource)
        self.assertEqual(res.codes(), [reg.FAILURE_RESOURCE_NOT_FOUND])
        self.assertEqual(set(res.failures[0]), {"code", "field", "message"})
        self.assertEqual(res.failures[0]["field"], "resource_id")
        self.assertEqual(res.to_dict(), self.r.lookup("missing").to_dict())
        self.assertEqual(res.to_dict(), create_web_resource_registry(self.items).registry.lookup("missing").to_dict())

    def test_33_exact_string_matching_no_trim_casefold_or_normalization(self):
        for near in ("A", " a", "a ", "\ta", "a\n", "\u00e1", "a\u0301", "ａ"):
            with self.subTest(near=near):
                res = self.r.lookup(near)
                self.assertFalse(res.found)
                self.assertIsNone(res.resource)
                self.assertEqual(res.codes(), [reg.FAILURE_RESOURCE_NOT_FOUND])

    def test_34_unicode_ids_match_only_by_exact_code_points(self):
        composed, decomposed = "caf\u00e9", "cafe\u0301"
        r = create_web_resource_registry([res(composed)]).registry
        self.assertTrue(r.lookup(composed).found)
        self.assertFalse(r.lookup(decomposed).found)

    def test_35_empty_string_lookup_is_not_found_not_invalid(self):
        self.assertEqual(self.r.lookup("").codes(), [reg.FAILURE_RESOURCE_NOT_FOUND])

    def test_36_non_str_ids_are_invalid_resource_id_and_never_coerced(self):
        class Sub(str):
            pass
        bads = [None, 1, 0, True, 1.5, b"a", bytearray(b"a"), ["a"], ("a",), {"a"}, {"a": 1}, object(), Sub("a"), self.items[0]]
        for bad in bads:
            with self.subTest(bad=type(bad).__name__):
                res = self.r.lookup(bad)
                self.assertFalse(res.found)
                self.assertIsNone(res.resource)
                self.assertEqual(res.codes(), [reg.FAILURE_INVALID_RESOURCE_ID])
                self.assertEqual(res.failures[0]["field"], "resource_id")

    def test_37_a_str_subclass_method_is_never_called(self):
        calls = []

        class Evil(str):
            def __eq__(self, other):
                calls.append("eq")
                return True

            def __hash__(self):
                calls.append("hash")
                return 0

            def strip(self, *a):
                calls.append("strip")
                return "a"

            def lower(self):
                calls.append("lower")
                return "a"
        res = self.r.lookup(Evil("a"))
        self.assertFalse(res.found)
        self.assertEqual(calls, [])

    def test_38_lookup_never_raises_and_never_changes_the_registry(self):
        before = self.r.to_dict()
        for probe in (None, "a", "zzz", 3, object(), ""):
            self.r.lookup(probe)
        self.assertEqual(self.r.to_dict(), before)
        self.assertEqual(self.r.resource_ids, ("a", "b", "c"))

    def test_39_lookup_result_to_dict_shapes_and_fresh_output(self):
        ok = self.r.lookup("b")
        d = ok.to_dict()
        self.assertEqual(set(d), {"found", "resource", "failures"})
        self.assertEqual((d["found"], d["resource"], d["failures"]), (True, self.items[1].to_dict(), []))
        d["resource"]["title"] = "hacked"
        self.assertEqual(self.r.lookup("b").resource.title, "Title b")
        self.assertEqual(ok.resource.title, "Title b")
        bad = self.r.lookup("nope")
        bd = bad.to_dict()
        self.assertEqual((bd["found"], bd["resource"]), (False, None))
        bd["failures"][0]["code"] = "hacked"
        bd["failures"].append("x")
        self.assertEqual(bad.codes(), [reg.FAILURE_RESOURCE_NOT_FOUND])
        self.assertIsNot(bad.to_dict()["failures"], bad.to_dict()["failures"])
        self.assertIsNot(bad.to_dict()["failures"][0], bad.to_dict()["failures"][0])

    def test_40_lookup_result_object_shape(self):
        self.assertEqual(WebResourceLookupResult.__slots__, ("found", "resource", "failures"))
        empty = WebResourceLookupResult()
        self.assertFalse(empty.found)
        self.assertEqual(empty.codes(), [])

    def test_41_lookup_works_for_registries_built_from_tuples_and_for_ids_equal_to_other_fields(self):
        r = create_web_resource_registry(tuple(self.items)).registry
        self.assertTrue(r.lookup("c").found)
        r2 = create_web_resource_registry([res("png")]).registry      # the id equals a format value; only resource_id is searched
        self.assertTrue(r2.lookup("png").found)
        self.assertFalse(r2.lookup("Name png").found)      # name is not an id


class TestFailureReporting(unittest.TestCase):
    def test_42_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(len(set(reg.FAILURE_CODES)), len(reg.FAILURE_CODES))
        for code in reg.FAILURE_CODES:
            self.assertTrue(code.startswith("WEB_RESOURCE_REGISTRY_"), code)
        self.assertEqual(reg.FAILURE_CODES, (
            "WEB_RESOURCE_REGISTRY_INVALID_COLLECTION", "WEB_RESOURCE_REGISTRY_INVALID_RESOURCE",
            "WEB_RESOURCE_REGISTRY_DUPLICATE_RESOURCE_ID", "WEB_RESOURCE_REGISTRY_RESOURCE_NOT_FOUND",
            "WEB_RESOURCE_REGISTRY_INVALID_RESOURCE_ID"))

    def test_43_the_factory_only_emits_factory_codes_and_lookup_only_lookup_codes(self):
        for bad in (None, [None], [res("a"), res("a")], [res("a"), 1, res("a")]):
            for code in create_web_resource_registry(bad).codes():
                self.assertIn(code, reg.FACTORY_FAILURE_CODES)
        r = create_web_resource_registry(three()).registry
        for probe in ("x", None, 1):
            for code in r.lookup(probe).codes():
                self.assertIn(code, reg.LOOKUP_FAILURE_CODES)

    def test_44_the_factory_never_raises_for_bad_input(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")
            __hash__ = None
        for bad in (None, 1, "x", {}, [Boom()], (Boom(),), [[]], [{}], [res("a"), Boom()], object()):
            with self.subTest(bad=repr(bad)[:30]):
                r = create_web_resource_registry(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.registry)
                self.assertTrue(r.failures)
                for f in r.failures:
                    self.assertIn(f["code"], reg.FACTORY_FAILURE_CODES)
                    self.assertEqual(set(f), {"code", "field", "message"})
                    self.assertIs(type(f["message"]), str)

    def test_45_failures_are_deterministic_across_calls(self):
        a = res("a")
        bad = [a, None, a, 7]
        self.assertEqual(create_web_resource_registry(bad).to_dict(), create_web_resource_registry(list(bad)).to_dict())
        self.assertEqual(create_web_resource_registry(bad).codes(), create_web_resource_registry(tuple(bad)).codes())

    def test_46_result_to_dict_shapes_and_fresh_failures(self):
        items = three()
        ok = create_web_resource_registry(items).to_dict()
        self.assertEqual(set(ok), {"ok", "registry", "failures"})
        self.assertEqual((ok["ok"], ok["registry"], ok["failures"]), (True, {"resources": [i.to_dict() for i in items]}, []))
        r = create_web_resource_registry(None)
        bad = r.to_dict()
        self.assertEqual((bad["ok"], bad["registry"]), (False, None))
        bad["failures"][0]["code"] = "hacked"
        bad["failures"].append(1)
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_COLLECTION])
        self.assertEqual(len(r.failures), 1)
        self.assertIsNot(r.to_dict()["failures"][0], r.to_dict()["failures"][0])

    def test_47_result_ok_codes_and_slots(self):
        self.assertFalse(WebResourceRegistryResult().ok)
        self.assertEqual(WebResourceRegistryResult().codes(), [])
        self.assertEqual(sorted(WebResourceRegistryResult.__slots__), ["failures", "registry"])
        self.assertTrue(create_web_resource_registry([]).ok)


class TestEqualityHashAndSerialization(unittest.TestCase):
    def test_48_equal_resources_in_the_same_order_give_equal_registries_and_hashes(self):
        a = create_web_resource_registry([res("a"), res("b")]).registry
        b = create_web_resource_registry([res("a"), res("b")]).registry
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertFalse(a != b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertEqual({a: 1}[b], 1)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_49_differences_break_equality(self):
        base = create_web_resource_registry([res("a"), res("b")]).registry
        for other in ([res("a")], [res("a"), res("b"), res("c")], [res("a"), res("x")], [res("a"), res("b", title="changed")], []):
            with self.subTest(other=len(other)):
                self.assertNotEqual(base, create_web_resource_registry(other).registry)

    def test_50_equality_is_exact_type_only(self):
        r = create_web_resource_registry([res("a")]).registry
        self.assertNotEqual(r, r.to_dict())
        self.assertNotEqual(r, (res("a"),))
        self.assertNotEqual(r, [res("a")])
        self.assertNotEqual(r, None)
        self.assertEqual(r.__eq__(1), NotImplemented)

    def test_51_to_dict_is_fresh_every_time_and_in_registration_order(self):
        items = [res("z"), res("a")]
        r = create_web_resource_registry(items).registry
        d = r.to_dict()
        self.assertEqual(d, {"resources": [items[0].to_dict(), items[1].to_dict()]})
        self.assertIsNot(r.to_dict(), r.to_dict())
        self.assertIsNot(r.to_dict()["resources"], r.to_dict()["resources"])
        self.assertIsNot(r.to_dict()["resources"][0], r.to_dict()["resources"][0])
        d["resources"].append({"x": 1})
        d["resources"][0]["title"] = "hacked"
        d["resources"][1].clear()
        self.assertEqual(r.to_dict(), {"resources": [items[0].to_dict(), items[1].to_dict()]})
        self.assertEqual(r.resources[0].title, "Title z")
        self.assertEqual(json.loads(json.dumps(r.to_dict())), r.to_dict())

    def test_52_to_dict_round_trips_through_the_factories(self):
        r = create_web_resource_registry(three()).registry
        rebuilt = create_web_resource_registry([create_web_resource(d).resource for d in r.to_dict()["resources"]]).registry
        self.assertEqual(rebuilt, r)

    def test_53_repr_is_deterministic(self):
        r = create_web_resource_registry(three()).registry
        self.assertEqual(repr(r), "WebResourceRegistry(resource_ids=('a', 'b', 'c'))")


class TestConstructionCopyPickle(unittest.TestCase):
    def test_54_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            WebResourceRegistry(object(), [])
        with self.assertRaises(TypeError):
            WebResourceRegistry(None, three())
        with self.assertRaises(TypeError):
            WebResourceRegistry(three())
        with self.assertRaises(TypeError):
            WebResourceRegistry(resources=three())
        with self.assertRaises(TypeError):
            class Sub(WebResourceRegistry):
                pass

    def test_55_copy_and_deepcopy_return_the_same_object(self):
        r = create_web_resource_registry(three()).registry
        self.assertIs(copy.copy(r), r)
        self.assertIs(copy.deepcopy(r), r)
        self.assertIs(copy.deepcopy({"k": [r]})["k"][0], r)
        self.assertIs(copy.deepcopy(r).resources[0], r.resources[0])

    def test_56_pickle_is_refused_for_every_protocol(self):
        r = create_web_resource_registry(three()).registry
        for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=proto):
                with self.assertRaises(TypeError):
                    pickle.dumps(r, protocol=proto)
        with self.assertRaises(TypeError):
            r.__reduce__()
        with self.assertRaises(TypeError):
            r.__reduce_ex__(2)
        with self.assertRaises(TypeError):
            pickle.dumps(create_web_resource_registry([]).registry)


class TestBoundaries(unittest.TestCase):
    def test_57_module_imports_only_web_resource_and_has_no_forbidden_calls_or_state(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(len(imports), 1)
        self.assertIsInstance(imports[0], ast.ImportFrom)
        self.assertEqual((imports[0].module, imports[0].level, [a.name for a in imports[0].names]), ("web_resource", 1, ["WebResource"]))
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars", "sorted"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(reg).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_58_module_source_names_no_forbidden_dependency(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "PIL", "numpy", "cv2", "sqlite3",
                     "random", "time", "datetime", "anthropic", "openai", "game_creation", "GameResource", "core", "agent", "planning"):
            self.assertNotIn(word, names, word)

    def test_59_web_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "web")) if f != "__pycache__"),
                         ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py", "web_request_executor.py", "web_request_metadata_executor.py", "web_request_output.py", "web_request_output_validator.py", "web_request_pipeline.py", "web_request_plan.py", "web_request_validator.py", "web_resource.py", "web_resource_registry.py"])
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_60_web_resource_module_is_unaware_of_the_registry(self):
        with open(os.path.join(PY_ROOT, "web", "web_resource.py"), encoding="utf-8") as fh:
            text = fh.read()
        for token in ("registry", "Registry"):
            self.assertNotIn(token, text)
        import web.web_resource as ia
        self.assertEqual(ia.FIELDS, ("resource_id", "url", "title", "resource_type"))

    def test_61_no_other_production_module_references_the_registry_or_web(self):
        tokens = ("web_resource", "WebResource", "create_web_resource", "from web", "import web")
        skip = {"web", "tests", "__pycache__", "data"}
        checked = 0
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in skip) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    for token in tokens:
                        self.assertNotIn(token, text, os.path.join(folder, name))
                    checked += 1
        self.assertGreater(checked, 100)

    def test_62_other_sections_and_core_are_unaware(self):
        for rel in ("game_creation/game_asset.py", "game_creation/game_asset_registry.py", "multimedia/image_asset_registry.py", "multimedia/audio_asset_registry.py", "core/core.py", "input_system/input_system.py",
                    "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("WebResource", "web_resource", "from web", "import web"):
                self.assertNotIn(token, text, (rel, token))

    def test_63_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("WebResourceRegistry", "create_web_resource_registry", "lookup", "WEB_RESOURCE_REGISTRY_", "DUPLICATE_RESOURCE_ID",
                       "RESOURCE_NOT_FOUND", "INVALID_RESOURCE_ID", "INVALID_COLLECTION", "INVALID_RESOURCE", "does NOT", "Prompt 775"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
