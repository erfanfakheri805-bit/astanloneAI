"""Prompt 747 - Section 8 image asset registry (`multimedia.image_asset_registry`)."""
import ast
import copy
import hashlib
import json
import os
import pickle
import unittest

from multimedia import image_asset_registry as reg
from multimedia.image_asset import ImageAsset, create_image_asset
from multimedia.image_asset_registry import (ImageAssetLookupResult, ImageAssetRegistry, ImageAssetRegistryResult,
                                             create_image_asset_registry)

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_image_asset_registry_prompt747.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "image_asset_registry.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def img(image_id="img_1", **over):
    data = {"image_id": image_id, "name": "Name " + image_id, "description": "d", "format": "png", "width": 10, "height": 20}
    data.update(over)
    r = create_image_asset(data)
    assert r.ok, r.failures
    return r.asset


def three():
    return [img("a"), img("b"), img("c")]


class TestValidRegistry(unittest.TestCase):
    def test_1_valid_list_builds_a_registry(self):
        items = three()
        r = create_image_asset_registry(items)
        self.assertIs(type(r), ImageAssetRegistryResult)
        self.assertTrue(r.ok)
        self.assertEqual(r.failures, [])
        self.assertEqual(r.codes(), [])
        self.assertIs(type(r.registry), ImageAssetRegistry)
        self.assertEqual(r.registry.assets, tuple(items))
        self.assertEqual(r.registry.image_ids, ("a", "b", "c"))

    def test_2_valid_tuple_builds_the_same_registry(self):
        items = three()
        self.assertEqual(create_image_asset_registry(tuple(items)).registry, create_image_asset_registry(list(items)).registry)

    def test_3_the_registered_objects_are_the_very_same_assets(self):
        items = three()
        r = create_image_asset_registry(items).registry
        for given, stored in zip(items, r.assets):
            self.assertIs(given, stored)

    def test_4_single_asset_registry(self):
        r = create_image_asset_registry([img("only")])
        self.assertTrue(r.ok)
        self.assertEqual(r.registry.image_ids, ("only",))

    def test_5_equal_but_distinct_assets_with_different_ids_are_fine(self):
        self.assertTrue(create_image_asset_registry([img("a"), img("b", name="Name a")]).ok)

    def test_6_ids_differing_only_by_case_or_whitespace_are_distinct(self):
        r = create_image_asset_registry([img("a"), img("A"), img(" a"), img("a ")])
        self.assertTrue(r.ok)
        self.assertEqual(r.registry.image_ids, ("a", "A", " a", "a "))


class TestEmptyRegistry(unittest.TestCase):
    def test_7_empty_list_and_tuple_are_valid(self):
        for empty in ([], ()):
            with self.subTest(empty=empty):
                r = create_image_asset_registry(empty)
                self.assertTrue(r.ok)
                self.assertEqual(r.registry.assets, ())
                self.assertEqual(r.registry.image_ids, ())
                self.assertEqual(r.registry.to_dict(), {"assets": []})

    def test_8_empty_registries_are_equal_and_lookups_miss(self):
        a, b = create_image_asset_registry([]).registry, create_image_asset_registry(()).registry
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.lookup("x").codes(), [reg.FAILURE_IMAGE_NOT_FOUND])


class TestCollectionValidation(unittest.TestCase):
    def test_9_wrong_collection_types_are_rejected(self):
        class L(list):
            pass

        class T(tuple):
            pass
        items = three()
        bads = [None, "abc", b"abc", 1, True, 1.5, {}, {"a": items[0]}, set(items), frozenset(items), iter(items), (a for a in items),
                range(3), L(items), T(items), items[0], object(), {"assets": items}]
        for bad in bads:
            with self.subTest(bad=type(bad).__name__):
                r = create_image_asset_registry(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.registry)
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_COLLECTION])
                self.assertEqual(r.failures[0]["field"], "assets")

    def test_10_a_generator_is_not_consumed(self):
        gen = (a for a in three())
        create_image_asset_registry(gen)
        self.assertEqual(len(list(gen)), 3)

    def test_11_wrong_item_types_are_rejected_by_position(self):
        class Sub(dict):
            pass
        valid = img("a")
        for bad in (None, 1, "a", {"image_id": "x"}, valid.to_dict(), object(), [valid], (valid,), b"a", True):
            with self.subTest(bad=type(bad).__name__):
                r = create_image_asset_registry([valid, bad])
                self.assertFalse(r.ok)
                self.assertIsNone(r.registry)
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_ASSET])
                self.assertIn("assets[1]", r.failures[0]["message"])

    def test_12_look_alikes_and_other_asset_types_are_rejected(self):
        from game_creation.game_asset import create_game_asset
        game_asset = create_game_asset({"asset_id": "a", "name": "n", "description": "", "asset_type": "image"}).asset

        class Fake:
            image_id = "z"
            name = "n"
            description = ""
            format = "png"
            width = 1
            height = 1

            def to_dict(self):
                return {}
        self.assertEqual(create_image_asset_registry([game_asset]).codes(), [reg.FAILURE_INVALID_ASSET])
        self.assertEqual(create_image_asset_registry([Fake()]).codes(), [reg.FAILURE_INVALID_ASSET])
        self.assertEqual(create_image_asset_registry([img("a").to_dict()]).codes(), [reg.FAILURE_INVALID_ASSET])

    def test_13_every_bad_item_is_reported_in_input_order(self):
        r = create_image_asset_registry([None, img("a"), 5, img("b"), "x"])
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_ASSET] * 3)
        self.assertEqual([("assets[%d]" % i) in f["message"] for f, i in zip(r.failures, (0, 2, 4))], [True] * 3)

    def test_14_a_failed_build_returns_no_registry_for_any_bad_input(self):
        for bad in (None, [None], [img("a"), img("a")]):
            self.assertIsNone(create_image_asset_registry(bad).registry)


class TestDuplicateIds(unittest.TestCase):
    def test_15_duplicate_ids_are_rejected(self):
        r = create_image_asset_registry([img("a"), img("b"), img("a", name="other")])
        self.assertFalse(r.ok)
        self.assertIsNone(r.registry)
        self.assertEqual(r.codes(), [reg.FAILURE_DUPLICATE_IMAGE_ID])
        self.assertIn("assets[2]", r.failures[0]["message"])
        self.assertEqual(r.failures[0]["field"], "assets")

    def test_16_the_very_same_object_twice_is_a_duplicate(self):
        a = img("a")
        self.assertEqual(create_image_asset_registry([a, a]).codes(), [reg.FAILURE_DUPLICATE_IMAGE_ID])
        self.assertEqual(create_image_asset_registry((a, a)).codes(), [reg.FAILURE_DUPLICATE_IMAGE_ID])

    def test_17_equal_distinct_objects_are_duplicates_too(self):
        self.assertEqual(create_image_asset_registry([img("a"), img("a")]).codes(), [reg.FAILURE_DUPLICATE_IMAGE_ID])

    def test_18_each_extra_repeat_is_reported(self):
        r = create_image_asset_registry([img("a"), img("a", name="2"), img("a", name="3"), img("b"), img("b", name="2")])
        self.assertEqual(r.codes(), [reg.FAILURE_DUPLICATE_IMAGE_ID] * 3)

    def test_19_duplicate_ids_are_exact_comparisons_only(self):
        self.assertTrue(create_image_asset_registry([img("a"), img("A")]).ok)
        self.assertTrue(create_image_asset_registry([img("a"), img("a ")]).ok)
        self.assertTrue(create_image_asset_registry([img("a"), img("\u00e1")]).ok)

    def test_20_a_bad_item_is_not_also_counted_as_a_duplicate(self):
        r = create_image_asset_registry([img("a"), None, img("a")])
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_ASSET, reg.FAILURE_DUPLICATE_IMAGE_ID])

    def test_21_mixed_problems_are_reported_together_in_input_order(self):
        r = create_image_asset_registry([img("a"), 3, img("a"), None])
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_ASSET, reg.FAILURE_DUPLICATE_IMAGE_ID, reg.FAILURE_INVALID_ASSET])


class TestOrdering(unittest.TestCase):
    def test_22_input_order_is_preserved_and_never_sorted(self):
        items = [img("z"), img("m"), img("a"), img("B")]
        r = create_image_asset_registry(items).registry
        self.assertEqual(r.image_ids, ("z", "m", "a", "B"))
        self.assertEqual([a["image_id"] for a in r.to_dict()["assets"]], ["z", "m", "a", "B"])

    def test_23_a_different_order_is_a_different_registry(self):
        a, b, c = three()
        r1 = create_image_asset_registry([a, b, c]).registry
        r2 = create_image_asset_registry([c, b, a]).registry
        self.assertNotEqual(r1, r2)
        self.assertEqual(len({r1, r2}), 2)

    def test_24_list_and_tuple_input_give_the_same_order(self):
        items = [img("q"), img("p")]
        self.assertEqual(create_image_asset_registry(items).registry.image_ids, create_image_asset_registry(tuple(items)).registry.image_ids)


class TestInternalImmutability(unittest.TestCase):
    def test_25_assets_and_image_ids_are_tuples(self):
        r = create_image_asset_registry(three()).registry
        self.assertIs(type(r.assets), tuple)
        self.assertIs(type(r.image_ids), tuple)
        self.assertIs(r.assets, r.assets)

    def test_26_later_edits_to_the_input_list_do_not_reach_the_registry(self):
        items = three()
        r = create_image_asset_registry(items).registry
        items.append(img("d"))
        items[0] = img("zzz")
        items.clear()
        self.assertEqual(r.image_ids, ("a", "b", "c"))
        self.assertEqual(r.lookup("a").asset.image_id, "a")

    def test_27_the_factory_does_not_change_the_input(self):
        items = three()
        snapshot = list(items)
        create_image_asset_registry(items)
        self.assertEqual(items, snapshot)
        for x, y in zip(items, snapshot):
            self.assertIs(x, y)
        bad = [img("a"), None, img("a")]
        snap_bad = list(bad)
        create_image_asset_registry(bad)
        self.assertEqual(bad, snap_bad)
        tup = tuple(items)
        create_image_asset_registry(tup)
        self.assertEqual(tup, tuple(snapshot))

    def test_28_registry_attributes_cannot_be_assigned_deleted_or_added(self):
        r = create_image_asset_registry(three()).registry
        for name in ("assets", "image_ids", "_assets", "lookup", "extra"):
            with self.assertRaises(AttributeError, msg=name):
                setattr(r, name, ())
        for name in ("assets", "image_ids", "_assets"):
            with self.assertRaises(AttributeError, msg=name):
                delattr(r, name)
        with self.assertRaises(AttributeError):
            object.__setattr__(r, "extra", 1)
        self.assertFalse(hasattr(r, "__dict__"))
        self.assertEqual(r.image_ids, ("a", "b", "c"))

    def test_29_the_registry_has_no_mutating_methods(self):
        public = sorted(n for n in dir(ImageAssetRegistry) if not n.startswith("_"))
        self.assertEqual(public, ["assets", "image_ids", "lookup", "to_dict"])
        self.assertEqual(ImageAssetRegistry.__slots__, ("_assets",))

    def test_30_stored_assets_stay_immutable(self):
        r = create_image_asset_registry(three()).registry
        with self.assertRaises(AttributeError):
            r.assets[0].name = "x"
        with self.assertRaises(TypeError):
            r.assets[0] = None


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.items = three()
        self.r = create_image_asset_registry(self.items).registry

    def test_31_found_returns_the_registered_object(self):
        for item in self.items:
            res = self.r.lookup(item.image_id)
            self.assertIs(type(res), ImageAssetLookupResult)
            self.assertTrue(res.found)
            self.assertIs(res.asset, item)
            self.assertEqual(res.failures, [])
            self.assertEqual(res.codes(), [])

    def test_32_a_missing_id_gives_a_deterministic_not_found_result(self):
        res = self.r.lookup("missing")
        self.assertFalse(res.found)
        self.assertIsNone(res.asset)
        self.assertEqual(res.codes(), [reg.FAILURE_IMAGE_NOT_FOUND])
        self.assertEqual(set(res.failures[0]), {"code", "field", "message"})
        self.assertEqual(res.failures[0]["field"], "image_id")
        self.assertEqual(res.to_dict(), self.r.lookup("missing").to_dict())
        self.assertEqual(res.to_dict(), create_image_asset_registry(self.items).registry.lookup("missing").to_dict())

    def test_33_exact_string_matching_no_trim_casefold_or_normalization(self):
        for near in ("A", " a", "a ", "\ta", "a\n", "\u00e1", "a\u0301", "ａ"):
            with self.subTest(near=near):
                res = self.r.lookup(near)
                self.assertFalse(res.found)
                self.assertIsNone(res.asset)
                self.assertEqual(res.codes(), [reg.FAILURE_IMAGE_NOT_FOUND])

    def test_34_unicode_ids_match_only_by_exact_code_points(self):
        composed, decomposed = "caf\u00e9", "cafe\u0301"
        r = create_image_asset_registry([img(composed)]).registry
        self.assertTrue(r.lookup(composed).found)
        self.assertFalse(r.lookup(decomposed).found)

    def test_35_empty_string_lookup_is_not_found_not_invalid(self):
        self.assertEqual(self.r.lookup("").codes(), [reg.FAILURE_IMAGE_NOT_FOUND])

    def test_36_non_str_ids_are_invalid_image_id_and_never_coerced(self):
        class Sub(str):
            pass
        bads = [None, 1, 0, True, 1.5, b"a", bytearray(b"a"), ["a"], ("a",), {"a"}, {"a": 1}, object(), Sub("a"), self.items[0]]
        for bad in bads:
            with self.subTest(bad=type(bad).__name__):
                res = self.r.lookup(bad)
                self.assertFalse(res.found)
                self.assertIsNone(res.asset)
                self.assertEqual(res.codes(), [reg.FAILURE_INVALID_IMAGE_ID])
                self.assertEqual(res.failures[0]["field"], "image_id")

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
        self.assertEqual(self.r.image_ids, ("a", "b", "c"))

    def test_39_lookup_result_to_dict_shapes_and_fresh_output(self):
        ok = self.r.lookup("b")
        d = ok.to_dict()
        self.assertEqual(set(d), {"found", "asset", "failures"})
        self.assertEqual((d["found"], d["asset"], d["failures"]), (True, self.items[1].to_dict(), []))
        d["asset"]["name"] = "hacked"
        self.assertEqual(self.r.lookup("b").asset.name, "Name b")
        self.assertEqual(ok.asset.name, "Name b")
        bad = self.r.lookup("nope")
        bd = bad.to_dict()
        self.assertEqual((bd["found"], bd["asset"]), (False, None))
        bd["failures"][0]["code"] = "hacked"
        bd["failures"].append("x")
        self.assertEqual(bad.codes(), [reg.FAILURE_IMAGE_NOT_FOUND])
        self.assertIsNot(bad.to_dict()["failures"], bad.to_dict()["failures"])
        self.assertIsNot(bad.to_dict()["failures"][0], bad.to_dict()["failures"][0])

    def test_40_lookup_result_object_shape(self):
        self.assertEqual(ImageAssetLookupResult.__slots__, ("found", "asset", "failures"))
        empty = ImageAssetLookupResult()
        self.assertFalse(empty.found)
        self.assertEqual(empty.codes(), [])

    def test_41_lookup_works_for_registries_built_from_tuples_and_for_ids_equal_to_other_fields(self):
        r = create_image_asset_registry(tuple(self.items)).registry
        self.assertTrue(r.lookup("c").found)
        r2 = create_image_asset_registry([img("png")]).registry      # the id equals a format value; only image_id is searched
        self.assertTrue(r2.lookup("png").found)
        self.assertFalse(r2.lookup("Name png").found)      # name is not an id


class TestFailureReporting(unittest.TestCase):
    def test_42_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(len(set(reg.FAILURE_CODES)), len(reg.FAILURE_CODES))
        for code in reg.FAILURE_CODES:
            self.assertTrue(code.startswith("IMAGE_ASSET_REGISTRY_"), code)
        self.assertEqual(reg.FAILURE_CODES, (
            "IMAGE_ASSET_REGISTRY_INVALID_COLLECTION", "IMAGE_ASSET_REGISTRY_INVALID_ASSET",
            "IMAGE_ASSET_REGISTRY_DUPLICATE_IMAGE_ID", "IMAGE_ASSET_REGISTRY_IMAGE_NOT_FOUND",
            "IMAGE_ASSET_REGISTRY_INVALID_IMAGE_ID"))

    def test_43_the_factory_only_emits_factory_codes_and_lookup_only_lookup_codes(self):
        for bad in (None, [None], [img("a"), img("a")], [img("a"), 1, img("a")]):
            for code in create_image_asset_registry(bad).codes():
                self.assertIn(code, reg.FACTORY_FAILURE_CODES)
        r = create_image_asset_registry(three()).registry
        for probe in ("x", None, 1):
            for code in r.lookup(probe).codes():
                self.assertIn(code, reg.LOOKUP_FAILURE_CODES)

    def test_44_the_factory_never_raises_for_bad_input(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")
            __hash__ = None
        for bad in (None, 1, "x", {}, [Boom()], (Boom(),), [[]], [{}], [img("a"), Boom()], object()):
            with self.subTest(bad=repr(bad)[:30]):
                r = create_image_asset_registry(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.registry)
                self.assertTrue(r.failures)
                for f in r.failures:
                    self.assertIn(f["code"], reg.FACTORY_FAILURE_CODES)
                    self.assertEqual(set(f), {"code", "field", "message"})
                    self.assertIs(type(f["message"]), str)

    def test_45_failures_are_deterministic_across_calls(self):
        a = img("a")
        bad = [a, None, a, 7]
        self.assertEqual(create_image_asset_registry(bad).to_dict(), create_image_asset_registry(list(bad)).to_dict())
        self.assertEqual(create_image_asset_registry(bad).codes(), create_image_asset_registry(tuple(bad)).codes())

    def test_46_result_to_dict_shapes_and_fresh_failures(self):
        items = three()
        ok = create_image_asset_registry(items).to_dict()
        self.assertEqual(set(ok), {"ok", "registry", "failures"})
        self.assertEqual((ok["ok"], ok["registry"], ok["failures"]), (True, {"assets": [i.to_dict() for i in items]}, []))
        r = create_image_asset_registry(None)
        bad = r.to_dict()
        self.assertEqual((bad["ok"], bad["registry"]), (False, None))
        bad["failures"][0]["code"] = "hacked"
        bad["failures"].append(1)
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_COLLECTION])
        self.assertEqual(len(r.failures), 1)
        self.assertIsNot(r.to_dict()["failures"][0], r.to_dict()["failures"][0])

    def test_47_result_ok_codes_and_slots(self):
        self.assertFalse(ImageAssetRegistryResult().ok)
        self.assertEqual(ImageAssetRegistryResult().codes(), [])
        self.assertEqual(sorted(ImageAssetRegistryResult.__slots__), ["failures", "registry"])
        self.assertTrue(create_image_asset_registry([]).ok)


class TestEqualityHashAndSerialization(unittest.TestCase):
    def test_48_equal_assets_in_the_same_order_give_equal_registries_and_hashes(self):
        a = create_image_asset_registry([img("a"), img("b")]).registry
        b = create_image_asset_registry([img("a"), img("b")]).registry
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertFalse(a != b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertEqual({a: 1}[b], 1)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_49_differences_break_equality(self):
        base = create_image_asset_registry([img("a"), img("b")]).registry
        for other in ([img("a")], [img("a"), img("b"), img("c")], [img("a"), img("x")], [img("a"), img("b", width=99)], []):
            with self.subTest(other=len(other)):
                self.assertNotEqual(base, create_image_asset_registry(other).registry)

    def test_50_equality_is_exact_type_only(self):
        r = create_image_asset_registry([img("a")]).registry
        self.assertNotEqual(r, r.to_dict())
        self.assertNotEqual(r, (img("a"),))
        self.assertNotEqual(r, [img("a")])
        self.assertNotEqual(r, None)
        self.assertEqual(r.__eq__(1), NotImplemented)

    def test_51_to_dict_is_fresh_every_time_and_in_registration_order(self):
        items = [img("z"), img("a")]
        r = create_image_asset_registry(items).registry
        d = r.to_dict()
        self.assertEqual(d, {"assets": [items[0].to_dict(), items[1].to_dict()]})
        self.assertIsNot(r.to_dict(), r.to_dict())
        self.assertIsNot(r.to_dict()["assets"], r.to_dict()["assets"])
        self.assertIsNot(r.to_dict()["assets"][0], r.to_dict()["assets"][0])
        d["assets"].append({"x": 1})
        d["assets"][0]["name"] = "hacked"
        d["assets"][1].clear()
        self.assertEqual(r.to_dict(), {"assets": [items[0].to_dict(), items[1].to_dict()]})
        self.assertEqual(r.assets[0].name, "Name z")
        self.assertEqual(json.loads(json.dumps(r.to_dict())), r.to_dict())

    def test_52_to_dict_round_trips_through_the_factories(self):
        r = create_image_asset_registry(three()).registry
        rebuilt = create_image_asset_registry([create_image_asset(d).asset for d in r.to_dict()["assets"]]).registry
        self.assertEqual(rebuilt, r)

    def test_53_repr_is_deterministic(self):
        r = create_image_asset_registry(three()).registry
        self.assertEqual(repr(r), "ImageAssetRegistry(image_ids=('a', 'b', 'c'))")


class TestConstructionCopyPickle(unittest.TestCase):
    def test_54_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            ImageAssetRegistry(object(), [])
        with self.assertRaises(TypeError):
            ImageAssetRegistry(None, three())
        with self.assertRaises(TypeError):
            ImageAssetRegistry(three())
        with self.assertRaises(TypeError):
            ImageAssetRegistry(assets=three())
        with self.assertRaises(TypeError):
            class Sub(ImageAssetRegistry):
                pass

    def test_55_copy_and_deepcopy_return_the_same_object(self):
        r = create_image_asset_registry(three()).registry
        self.assertIs(copy.copy(r), r)
        self.assertIs(copy.deepcopy(r), r)
        self.assertIs(copy.deepcopy({"k": [r]})["k"][0], r)
        self.assertIs(copy.deepcopy(r).assets[0], r.assets[0])

    def test_56_pickle_is_refused_for_every_protocol(self):
        r = create_image_asset_registry(three()).registry
        for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=proto):
                with self.assertRaises(TypeError):
                    pickle.dumps(r, protocol=proto)
        with self.assertRaises(TypeError):
            r.__reduce__()
        with self.assertRaises(TypeError):
            r.__reduce_ex__(2)
        with self.assertRaises(TypeError):
            pickle.dumps(create_image_asset_registry([]).registry)


class TestBoundaries(unittest.TestCase):
    def test_57_module_imports_only_image_asset_and_has_no_forbidden_calls_or_state(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(len(imports), 1)
        self.assertIsInstance(imports[0], ast.ImportFrom)
        self.assertEqual((imports[0].module, imports[0].level, [a.name for a in imports[0].names]), ("image_asset", 1, ["ImageAsset"]))
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
                     "random", "time", "datetime", "anthropic", "openai", "game_creation", "GameAsset", "core", "agent", "planning"):
            self.assertNotIn(word, names, word)

    def test_59_multimedia_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py", "image_asset.py", "image_asset_registry.py", "image_operation_batch.py", "image_operation_batch_summary.py", "image_operation_dispatcher.py", "image_operation_executor.py", "image_operation_metadata_executor.py", "image_operation_output.py", "image_operation_output_validator.py", "image_operation_pipeline.py", "image_operation_plan.py", "image_operation_request.py", "image_operation_validator.py"])      # Prompts 748, 749, 750 and 751 add one further module each
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_60_image_asset_module_is_unaware_of_the_registry(self):
        with open(os.path.join(PY_ROOT, "multimedia", "image_asset.py"), encoding="utf-8") as fh:
            text = fh.read()
        for token in ("registry", "Registry"):
            self.assertNotIn(token, text)
        import multimedia.image_asset as ia
        self.assertEqual(ia.FIELDS, ("image_id", "name", "description", "format", "width", "height"))

    def test_61_no_other_production_module_references_the_registry_or_multimedia(self):
        tokens = ("multimedia", "image_asset", "ImageAsset", "create_image_asset")
        skip = {"multimedia", "tests", "__pycache__", "data"}
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

    def test_62_section7_game_asset_is_unchanged_and_unaware(self):
        for rel in ("game_creation/game_asset.py", "game_creation/game_asset_registry.py", "core/core.py", "input_system/input_system.py",
                    "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("multimedia", "ImageAsset", "image_asset"):
                self.assertNotIn(token, text, (rel, token))

    def test_63_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("ImageAssetRegistry", "create_image_asset_registry", "lookup", "IMAGE_ASSET_REGISTRY_", "DUPLICATE_IMAGE_ID",
                       "IMAGE_NOT_FOUND", "INVALID_IMAGE_ID", "INVALID_COLLECTION", "INVALID_ASSET", "does NOT", "Prompt 748"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
