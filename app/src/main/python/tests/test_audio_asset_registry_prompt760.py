"""Prompt 760 - Section 8 audio asset registry (`multimedia.audio_asset_registry`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest
from collections import OrderedDict

from multimedia import audio_asset_registry as reg
from multimedia.audio_asset import AudioAsset, create_audio_asset
from multimedia.audio_asset_registry import (AudioAssetLookupResult, AudioAssetRegistry, AudioAssetRegistryResult,
                                             create_audio_asset_registry)
from multimedia.image_asset import create_image_asset

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_audio_asset_registry_prompt760.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "audio_asset_registry.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "AUDIO_ASSET_REGISTRY_"


def make(audio_id="theme", **over):
    data = {"audio_id": audio_id, "name": "Name " + audio_id, "description": "", "format": "mp3", "duration_ms": 1000, "sample_rate": 44100}
    data.update(over)
    created = create_audio_asset(data)
    assert created.ok, created.failures
    return created.asset


def three():
    return [make("theme"), make("click", format="wav", sample_rate=22050), make("boss", duration_ms=90000)]


class TestValidRegistry(unittest.TestCase):
    def test_01_valid_list_builds_a_registry(self):
        assets = three()
        r = create_audio_asset_registry(assets)
        self.assertIs(type(r), AudioAssetRegistryResult)
        self.assertIs(r.ok, True)
        self.assertEqual((r.failures, r.codes()), ((), []))
        self.assertIs(type(r.registry), AudioAssetRegistry)
        self.assertEqual(r.registry.assets, tuple(assets))

    def test_02_tuple_input_gives_the_same_registry(self):
        assets = three()
        self.assertEqual(create_audio_asset_registry(assets).registry, create_audio_asset_registry(tuple(assets)).registry)

    def test_03_the_registered_objects_are_the_very_same_assets(self):
        assets = three()
        registry = create_audio_asset_registry(assets).registry
        for given, stored in zip(assets, registry.assets):
            self.assertIs(given, stored)

    def test_04_single_asset(self):
        a = make()
        registry = create_audio_asset_registry([a]).registry
        self.assertEqual((registry.assets, registry.audio_ids), ((a,), ("theme",)))

    def test_05_equal_content_with_different_ids_is_fine(self):
        a, b = make("a"), make("b")
        self.assertTrue(create_audio_asset_registry([a, b]).ok)

    def test_06_ids_differing_only_by_case_or_whitespace_are_distinct(self):
        assets = [make("Theme"), make("theme"), make(" theme"), make("theme "), make("THEME")]
        registry = create_audio_asset_registry(assets).registry
        self.assertEqual(registry.audio_ids, ("Theme", "theme", " theme", "theme ", "THEME"))


class TestEmptyRegistry(unittest.TestCase):
    def test_10_empty_list_and_tuple_are_valid(self):
        for empty in ([], ()):
            with self.subTest(kind=type(empty).__name__):
                r = create_audio_asset_registry(empty)
                self.assertIs(r.ok, True)
                self.assertEqual((r.registry.assets, r.registry.audio_ids), ((), ()))
                self.assertEqual(r.registry.to_dict(), {"assets": []})
                self.assertEqual(r.to_dict(), {"ok": True, "registry": {"assets": []}, "failures": []})

    def test_11_empty_registries_are_equal_and_every_lookup_misses(self):
        a, b = create_audio_asset_registry([]).registry, create_audio_asset_registry(()).registry
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        res = a.lookup("anything")
        self.assertEqual((res.found, res.asset, res.codes()), (False, None, [P + "AUDIO_NOT_FOUND"]))
        self.assertEqual(a.lookup(None).codes(), [P + "INVALID_AUDIO_ID"])


class TestCollectionValidation(unittest.TestCase):
    def test_20_wrong_collection_types_are_rejected(self):
        class L(list):
            pass

        class T(tuple):
            pass
        a = make()
        bads = [None, 0, 1, True, "", "abc", b"x", {}, {"theme": a}, {a}, frozenset([a]), a, OrderedDict(), L([a]), T((a,)),
                iter([a]), (x for x in [a]), range(3), object(), a.to_dict()]
        for bad in bads:
            with self.subTest(bad=type(bad).__name__):
                r = create_audio_asset_registry(bad)
                self.assertIs(r.ok, False)
                self.assertIsNone(r.registry)
                self.assertEqual(r.codes(), [P + "INVALID_COLLECTION"])
                self.assertEqual(r.failures[0]["field"], "assets")

    def test_21_a_generator_is_not_consumed(self):
        gen = (x for x in [make()])
        create_audio_asset_registry(gen)
        self.assertEqual(len(list(gen)), 1)

    def test_22_wrong_item_types_are_rejected_by_position(self):
        a = make()
        for bad in (None, 0, "theme", b"x", {}, [], (), object(), a.to_dict(), a.audio_id, True):
            with self.subTest(bad=type(bad).__name__):
                r = create_audio_asset_registry([a, bad, make("other")])
                self.assertIs(r.ok, False)
                self.assertIsNone(r.registry)
                self.assertEqual(r.codes(), [P + "INVALID_ASSET"])
                self.assertIn("assets[1]", r.failures[0]["message"])
                self.assertEqual(r.failures[0]["field"], "assets")

    def test_23_look_alikes_and_other_asset_types_are_rejected(self):
        class Fake:
            audio_id = "x"

            def to_dict(self):
                return {}
        image = create_image_asset({"image_id": "i", "name": "N", "description": "", "format": "png", "width": 1, "height": 1}).asset
        from game_creation.game_asset import GameAsset
        self.assertEqual(create_audio_asset_registry([Fake()]).codes(), [P + "INVALID_ASSET"])
        self.assertEqual(create_audio_asset_registry([image]).codes(), [P + "INVALID_ASSET"])
        self.assertEqual(create_audio_asset_registry([GameAsset]).codes(), [P + "INVALID_ASSET"])
        self.assertEqual(create_audio_asset_registry([AudioAsset]).codes(), [P + "INVALID_ASSET"])

    def test_24_every_bad_item_is_reported_in_input_order(self):
        r = create_audio_asset_registry([None, make(), 3, make("b"), "x"])
        self.assertEqual(r.codes(), [P + "INVALID_ASSET"] * 3)
        for failure, index in zip(r.failures, (0, 2, 4)):
            self.assertIn("assets[%d]" % index, failure["message"])

    def test_25_a_failed_build_never_returns_a_registry(self):
        for bad in (None, [None], [make(), make()], "x"):
            self.assertIsNone(create_audio_asset_registry(bad).registry)
            self.assertIs(create_audio_asset_registry(bad).ok, False)


class TestDuplicateIds(unittest.TestCase):
    def test_30_duplicate_ids_are_rejected(self):
        r = create_audio_asset_registry([make("a"), make("b", name="other"), make("a", name="third")])
        self.assertIs(r.ok, False)
        self.assertIsNone(r.registry)
        self.assertEqual(r.codes(), [P + "DUPLICATE_AUDIO_ID"])
        self.assertIn("assets[2]", r.failures[0]["message"])
        self.assertIn("'a'", r.failures[0]["message"])
        self.assertEqual(r.failures[0]["field"], "assets")

    def test_31_the_same_object_twice_is_a_duplicate(self):
        a = make()
        self.assertEqual(create_audio_asset_registry([a, a]).codes(), [P + "DUPLICATE_AUDIO_ID"])

    def test_32_equal_distinct_objects_are_duplicates_too(self):
        self.assertEqual(create_audio_asset_registry([make(), make()]).codes(), [P + "DUPLICATE_AUDIO_ID"])

    def test_33_each_extra_repeat_is_reported(self):
        r = create_audio_asset_registry([make("a"), make("a"), make("a"), make("b"), make("b")])
        self.assertEqual(r.codes(), [P + "DUPLICATE_AUDIO_ID"] * 3)
        self.assertEqual([("assets[%d]" % i) in f["message"] for f, i in zip(r.failures, (1, 2, 4))], [True] * 3)

    def test_34_duplicates_are_exact_comparisons_only(self):
        self.assertTrue(create_audio_asset_registry([make("a"), make("A"), make("a "), make(" a"), make("\u00e9"), make("e\u0301")]).ok)

    def test_35_a_bad_item_is_not_also_counted_as_a_duplicate(self):
        a = make()
        r = create_audio_asset_registry([a, None, a])
        self.assertEqual(r.codes(), [P + "INVALID_ASSET", P + "DUPLICATE_AUDIO_ID"])
        self.assertEqual(create_audio_asset_registry([None, None]).codes(), [P + "INVALID_ASSET"] * 2)

    def test_36_mixed_problems_are_reported_together_in_input_order(self):
        r = create_audio_asset_registry([make("a"), 5, make("a"), None, make("b"), make("b")])
        self.assertEqual(r.codes(), [P + "INVALID_ASSET", P + "DUPLICATE_AUDIO_ID", P + "INVALID_ASSET", P + "DUPLICATE_AUDIO_ID"])


class TestOrderingAndImmutableStorage(unittest.TestCase):
    def test_40_input_order_is_preserved_and_never_sorted(self):
        registry = create_audio_asset_registry([make("m"), make("z"), make("a"), make("k")]).registry
        self.assertEqual(registry.audio_ids, ("m", "z", "a", "k"))
        self.assertEqual([a["audio_id"] for a in registry.to_dict()["assets"]], ["m", "z", "a", "k"])

    def test_41_a_different_order_is_a_different_registry(self):
        a, b = make("a"), make("b")
        r1, r2 = create_audio_asset_registry([a, b]).registry, create_audio_asset_registry([b, a]).registry
        self.assertNotEqual(r1, r2)
        self.assertEqual(len({r1, r2}), 2)

    def test_42_assets_and_audio_ids_are_tuples(self):
        registry = create_audio_asset_registry(three()).registry
        self.assertIs(type(registry.assets), tuple)
        self.assertIs(type(registry.audio_ids), tuple)
        self.assertEqual(registry.audio_ids, ("theme", "click", "boss"))
        with self.assertRaises(TypeError):
            registry.assets[0] = None
        with self.assertRaises(AttributeError):
            registry.assets.append(make("x"))
        self.assertIs(registry.assets, registry.assets)

    def test_43_later_edits_to_the_input_list_do_not_reach_the_registry(self):
        assets = three()
        registry = create_audio_asset_registry(assets).registry
        before = registry.assets
        assets.append(make("late"))
        assets[0] = make("swapped")
        assets.reverse()
        self.assertEqual(registry.audio_ids, ("theme", "click", "boss"))
        self.assertEqual(registry.assets, before)

    def test_44_the_factory_does_not_change_its_input_or_the_assets(self):
        assets = three()
        snapshot = (list(assets), [a.to_dict() for a in assets], [hash(a) for a in assets])
        create_audio_asset_registry(assets)
        create_audio_asset_registry(assets + [assets[0]])
        self.assertEqual((list(assets), [a.to_dict() for a in assets], [hash(a) for a in assets]), snapshot)
        bad = [None, make()]
        create_audio_asset_registry(bad)
        self.assertEqual(len(bad), 2)

    def test_45_registry_attributes_cannot_be_assigned_deleted_or_added(self):
        registry = create_audio_asset_registry(three()).registry
        for name in ("assets", "audio_ids", "_assets", "extra", "lookup"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(registry, name, ())
                with self.assertRaises(AttributeError):
                    delattr(registry, name)
        with self.assertRaises(AttributeError):
            object.__setattr__(registry, "extra", 1)
        self.assertFalse(hasattr(registry, "__dict__"))
        self.assertEqual(registry.audio_ids, ("theme", "click", "boss"))

    def test_46_the_registry_has_no_mutating_methods_and_a_fixed_public_surface(self):
        public = sorted(n for n in dir(AudioAssetRegistry) if not n.startswith("_"))
        self.assertEqual(public, ["assets", "audio_ids", "lookup", "to_dict"])
        self.assertEqual(AudioAssetRegistry.__slots__, ("_assets",))

    def test_47_stored_assets_stay_immutable(self):
        registry = create_audio_asset_registry(three()).registry
        with self.assertRaises(AttributeError):
            registry.assets[0].name = "x"
        self.assertEqual(registry.assets[0].name, "Name theme")


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.assets = three()
        self.registry = create_audio_asset_registry(self.assets).registry

    def test_50_found_returns_the_registered_object(self):
        for asset in self.assets:
            with self.subTest(audio_id=asset.audio_id):
                res = self.registry.lookup(asset.audio_id)
                self.assertIs(type(res), AudioAssetLookupResult)
                self.assertIs(res.found, True)
                self.assertIs(res.asset, asset)
                self.assertEqual((res.failures, res.codes()), ((), []))
                self.assertEqual(res.to_dict(), {"found": True, "asset": asset.to_dict(), "failures": []})

    def test_51_identity_is_preserved_for_the_returned_asset_and_its_strings(self):
        name = "".join(["Na", "me"])
        ident = "".join(["i", "d"])
        a = make(ident, name=name)
        registry = create_audio_asset_registry([a]).registry
        found = registry.lookup("id").asset
        self.assertIs(found, a)
        self.assertIs(found.name, name)
        self.assertIs(found.audio_id, ident)
        self.assertIs(registry.audio_ids[0], ident)

    def test_52_a_missing_id_gives_a_deterministic_not_found_result(self):
        r1, r2 = self.registry.lookup("missing"), self.registry.lookup("missing")
        self.assertEqual((r1.found, r1.asset, r1.codes()), (False, None, [P + "AUDIO_NOT_FOUND"]))
        self.assertEqual(r1, r2)
        self.assertEqual(hash(r1), hash(r2))
        self.assertEqual(r1.to_dict(), r2.to_dict())
        self.assertEqual(r1.failures[0]["field"], "audio_id")
        self.assertIn("'missing'", r1.failures[0]["message"])
        self.assertEqual(len(r1.failures), 1)

    def test_53_exact_string_matching_no_trim_casefold_or_normalization(self):
        for probe in ("Theme", "THEME", " theme", "theme ", "\ttheme", "theme\n", "the me", "", " "):
            with self.subTest(probe=probe):
                res = self.registry.lookup(probe)
                self.assertEqual((res.found, res.asset, res.codes()), (False, None, [P + "AUDIO_NOT_FOUND"]))

    def test_54_unicode_ids_match_only_by_exact_code_points(self):
        registry = create_audio_asset_registry([make("caf\u00e9")]).registry
        self.assertTrue(registry.lookup("caf\u00e9").found)
        self.assertEqual(registry.lookup("cafe\u0301").codes(), [P + "AUDIO_NOT_FOUND"])

    def test_55_empty_string_lookup_is_not_found_not_invalid(self):
        self.assertEqual(self.registry.lookup("").codes(), [P + "AUDIO_NOT_FOUND"])

    def test_56_non_str_ids_are_invalid_audio_id_and_never_coerced(self):
        class S(str):
            pass
        for bad in (None, 0, 1, True, False, 1.5, b"theme", bytearray(b"theme"), ["theme"], ("theme",), {"theme"}, {"theme": 1}, object(),
                    S("theme"), self.assets[0], self.assets[0].to_dict()):
            with self.subTest(bad=type(bad).__name__):
                res = self.registry.lookup(bad)
                self.assertEqual((res.found, res.asset, res.codes()), (False, None, [P + "INVALID_AUDIO_ID"]))
                self.assertEqual(res.failures[0]["field"], "audio_id")

    def test_57_a_str_subclass_method_is_never_called(self):
        calls = []

        class Evil(str):
            def __eq__(self, other):
                calls.append("eq")
                return True

            def __hash__(self):
                calls.append("hash")
                return 1

            def strip(self, *a):
                calls.append("strip")
                return "theme"

            def lower(self):
                calls.append("lower")
                return "theme"
        self.assertEqual(self.registry.lookup(Evil("theme")).codes(), [P + "INVALID_AUDIO_ID"])
        self.assertEqual(calls, [])

    def test_58_lookup_never_raises_and_never_changes_the_registry(self):
        before = (self.registry.assets, self.registry.audio_ids, self.registry.to_dict(), hash(self.registry))
        for probe in ("theme", "nope", None, 1, object(), "", b"x", float("nan")):
            self.registry.lookup(probe)
        self.assertEqual(before, (self.registry.assets, self.registry.audio_ids, self.registry.to_dict(), hash(self.registry)))

    def test_59_lookup_result_is_immutable_comparable_and_hashable(self):
        found, miss, invalid = self.registry.lookup("theme"), self.registry.lookup("zzz"), self.registry.lookup(None)
        for res in (found, miss, invalid):
            for name in ("found", "asset", "failures", "_found", "extra"):
                with self.assertRaises(AttributeError):
                    setattr(res, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(res, name)
            self.assertFalse(hasattr(res, "__dict__"))
        self.assertEqual(found, self.registry.lookup("theme"))
        self.assertNotEqual(found, miss)
        self.assertNotEqual(miss, invalid)
        self.assertNotEqual(found, found.to_dict())
        self.assertNotEqual(found, None)
        self.assertEqual(len({found, self.registry.lookup("theme"), miss, self.registry.lookup("zzz"), invalid}), 3)
        self.assertNotEqual(self.registry.lookup("theme"), self.registry.lookup("click"))
        self.assertEqual(self.registry.lookup("zzz"), create_audio_asset_registry([]).registry.lookup("zzz"))

    def test_60_lookup_result_to_dict_and_failures_are_fresh(self):
        miss = self.registry.lookup("zzz")
        d = miss.to_dict()
        self.assertEqual(set(d), {"found", "asset", "failures"})
        self.assertEqual((d["found"], d["asset"]), (False, None))
        self.assertEqual(set(d["failures"][0]), {"code", "field", "message"})
        d["failures"][0]["code"] = "hacked"
        d["failures"].append(1)
        d["found"] = True
        miss.failures[0]["message"] = "hacked"
        self.assertEqual(miss.codes(), [P + "AUDIO_NOT_FOUND"])
        self.assertEqual(miss.to_dict()["failures"][0]["code"], P + "AUDIO_NOT_FOUND")
        self.assertIsNot(miss.to_dict(), miss.to_dict())
        self.assertIsNot(miss.to_dict()["failures"], miss.to_dict()["failures"])
        self.assertIsNot(miss.to_dict()["failures"][0], miss.to_dict()["failures"][0])
        self.assertIsNot(miss.failures[0], miss.failures[0])
        self.assertIs(type(miss.failures), tuple)
        found = self.registry.lookup("theme").to_dict()
        found["asset"]["name"] = "hacked"
        self.assertEqual(self.registry.lookup("theme").asset.name, "Name theme")

    def test_61_lookup_works_for_tuple_built_registries_and_ids_equal_to_other_fields(self):
        registry = create_audio_asset_registry(tuple([make("x", name="y"), make("y", name="x")])).registry
        self.assertEqual(registry.lookup("x").asset.name, "y")
        self.assertEqual(registry.lookup("y").asset.name, "x")
        self.assertEqual(registry.lookup("mp3").codes(), [P + "AUDIO_NOT_FOUND"])

    def test_62_lookup_result_cannot_be_built_directly_or_subclassed(self):
        for args in ((), (object(), False, None, ()), (None, False, None, ()), (True, None, ())):
            with self.assertRaises(TypeError):
                AudioAssetLookupResult(*args)
        with self.assertRaises(TypeError):
            type("Sub", (AudioAssetLookupResult,), {})


class TestFailureReporting(unittest.TestCase):
    def test_70_failure_codes_are_exactly_the_five_and_prefixed(self):
        self.assertEqual(reg.FAILURE_CODES, (P + "INVALID_COLLECTION", P + "INVALID_ASSET", P + "DUPLICATE_AUDIO_ID", P + "AUDIO_NOT_FOUND",
                                             P + "INVALID_AUDIO_ID"))
        self.assertEqual(len(set(reg.FAILURE_CODES)), 5)
        defined = {v for k, v in vars(reg).items() if isinstance(v, str) and v.startswith("AUDIO_ASSET_REGISTRY_")}
        self.assertEqual(defined, set(reg.FAILURE_CODES))
        self.assertEqual(reg.FACTORY_FAILURE_CODES + reg.LOOKUP_FAILURE_CODES, reg.FAILURE_CODES)

    def test_71_the_factory_only_emits_factory_codes_and_lookup_only_lookup_codes(self):
        registry = create_audio_asset_registry(three()).registry
        for bad in (None, [None], [make(), make()], [None, make("a"), make("a")]):
            for code in create_audio_asset_registry(bad).codes():
                self.assertIn(code, reg.FACTORY_FAILURE_CODES)
        for probe in ("nope", None, 3):
            for code in registry.lookup(probe).codes():
                self.assertIn(code, reg.LOOKUP_FAILURE_CODES)

    def test_72_the_factory_never_raises_for_bad_input(self):
        class Hostile:
            def __getattr__(self, name):
                raise RuntimeError(name)
        for bad in (None, 1, "x", [], (), {}, [Hostile()], [object()], [None], (None,), [make(), None], 10 ** 100, float("nan"), type):
            with self.subTest(bad=repr(bad)[:30]):
                r = create_audio_asset_registry(bad)
                for f in r.failures:
                    self.assertEqual(set(f), {"code", "field", "message"})
                    self.assertIs(type(f["message"]), str)

    def test_73_failures_are_deterministic_across_calls(self):
        bad = [make("a"), None, make("a"), 5]
        self.assertEqual(create_audio_asset_registry(bad), create_audio_asset_registry(list(bad)))
        self.assertEqual(create_audio_asset_registry(bad).to_dict(), create_audio_asset_registry(bad).to_dict())

    def test_74_result_to_dict_shapes_and_fresh_failures(self):
        ok = create_audio_asset_registry(three())
        d = ok.to_dict()
        self.assertEqual(set(d), {"ok", "registry", "failures"})
        self.assertEqual((d["ok"], d["failures"]), (True, []))
        self.assertEqual(d["registry"], {"assets": [a.to_dict() for a in three()]})
        d["registry"]["assets"].clear()
        self.assertEqual(len(ok.registry.assets), 3)
        self.assertEqual(len(ok.to_dict()["registry"]["assets"]), 3)
        bad = create_audio_asset_registry([None])
        bd = bad.to_dict()
        self.assertEqual((bd["ok"], bd["registry"]), (False, None))
        bd["failures"][0]["code"] = "hacked"
        bd["failures"].append("x")
        bad.failures[0]["code"] = "hacked"
        self.assertEqual(bad.codes(), [P + "INVALID_ASSET"])
        self.assertEqual(len(bad.failures), 1)
        self.assertIsNot(bad.to_dict()["failures"], bad.to_dict()["failures"])
        self.assertIsNot(bad.failures[0], bad.failures[0])
        self.assertIs(type(bad.failures), tuple)

    def test_75_result_is_immutable_comparable_and_hashable(self):
        ok, ok2 = create_audio_asset_registry(three()), create_audio_asset_registry(three())
        bad, empty = create_audio_asset_registry([None]), create_audio_asset_registry([])
        for res in (ok, bad):
            for name in ("ok", "registry", "failures", "_registry", "extra"):
                with self.assertRaises(AttributeError):
                    setattr(res, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(res, name)
            self.assertFalse(hasattr(res, "__dict__"))
        self.assertEqual(ok, ok2)
        self.assertEqual(hash(ok), hash(ok2))
        self.assertNotEqual(ok, bad)
        self.assertNotEqual(ok, empty)
        self.assertNotEqual(bad, create_audio_asset_registry(None))
        self.assertNotEqual(ok, ok.to_dict())
        self.assertNotEqual(ok, None)
        self.assertEqual(len({ok, ok2, bad, empty}), 3)

    def test_76_result_cannot_be_built_directly_or_subclassed(self):
        for args in ((), (object(), None, ()), (None, None, ()), (True, None)):
            with self.assertRaises(TypeError):
                AudioAssetRegistryResult(*args)
        with self.assertRaises(TypeError):
            type("Sub", (AudioAssetRegistryResult,), {})
        self.assertEqual(sorted(AudioAssetRegistryResult.__slots__), ["_failures", "_registry"])
        self.assertEqual(sorted(AudioAssetLookupResult.__slots__), ["_asset", "_failures", "_found"])


class TestEqualityHashAndSerialization(unittest.TestCase):
    def test_80_equal_assets_in_the_same_order_give_equal_registries_and_hashes(self):
        a, b = create_audio_asset_registry(three()).registry, create_audio_asset_registry(three()).registry
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertFalse(a != b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertEqual({a: 1}[b], 1)

    def test_81_differences_break_equality(self):
        base = create_audio_asset_registry(three()).registry
        for other in (three()[:2], three() + [make("extra")], [make("theme", name="changed")] + three()[1:], list(reversed(three())), []):
            with self.subTest(n=len(other)):
                self.assertNotEqual(base, create_audio_asset_registry(other).registry)

    def test_82_equality_is_exact_type_only(self):
        r = create_audio_asset_registry(three()).registry
        self.assertNotEqual(r, r.to_dict())
        self.assertNotEqual(r, r.assets)
        self.assertNotEqual(r, list(r.assets))
        self.assertNotEqual(r, None)
        self.assertEqual(r.__eq__(r.assets), NotImplemented)

    def test_83_to_dict_is_fresh_every_time_and_in_registration_order(self):
        r = create_audio_asset_registry(three()).registry
        d = r.to_dict()
        self.assertEqual(list(d), ["assets"])
        self.assertEqual([a["audio_id"] for a in d["assets"]], ["theme", "click", "boss"])
        d["assets"].append("x")
        d["assets"][0]["name"] = "hacked"
        self.assertEqual(len(r.to_dict()["assets"]), 3)
        self.assertEqual(r.to_dict(), {"assets": [a.to_dict() for a in three()]})
        self.assertIsNot(r.to_dict(), r.to_dict())
        self.assertIsNot(r.to_dict()["assets"], r.to_dict()["assets"])
        self.assertIsNot(r.to_dict()["assets"][0], r.to_dict()["assets"][0])
        self.assertEqual(r.assets[0].name, "Name theme")

    def test_84_to_dict_round_trips_through_the_factories(self):
        r = create_audio_asset_registry(three()).registry
        rebuilt = create_audio_asset_registry([create_audio_asset(d).asset for d in r.to_dict()["assets"]]).registry
        self.assertEqual(rebuilt, r)

    def test_85_repr_is_deterministic(self):
        r = create_audio_asset_registry(three()).registry
        self.assertEqual(repr(r), "AudioAssetRegistry(audio_ids=('theme', 'click', 'boss'))")
        self.assertEqual(repr(create_audio_asset_registry([None])), "AudioAssetRegistryResult(ok=False, codes=['%sINVALID_ASSET'])" % P)
        self.assertEqual(repr(r.lookup("click")), "AudioAssetLookupResult(found=True, audio_id='click', codes=[])")
        self.assertEqual(repr(r.lookup("zz")), "AudioAssetLookupResult(found=False, audio_id=None, codes=['%sAUDIO_NOT_FOUND'])" % P)

    def test_86_deterministic_repeated_builds(self):
        built = [create_audio_asset_registry(three()) for _ in range(4)]
        self.assertEqual(len(set(built)), 1)
        self.assertEqual(len({repr(b) for b in built}), 1)
        self.assertEqual(len({str(b.to_dict()) for b in built}), 1)


class TestConstructionCopyPickle(unittest.TestCase):
    def setUp(self):
        self.registry = create_audio_asset_registry(three()).registry
        self.objects = (self.registry, create_audio_asset_registry(three()), create_audio_asset_registry([None]),
                        self.registry.lookup("theme"), self.registry.lookup("nope"), self.registry.lookup(None))

    def test_90_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            AudioAssetRegistry(object(), [])
        with self.assertRaises(TypeError):
            AudioAssetRegistry(None, [])
        with self.assertRaises(TypeError):
            AudioAssetRegistry([])
        with self.assertRaises(TypeError):
            AudioAssetRegistry()
        with self.assertRaises(TypeError):
            type("Sub", (AudioAssetRegistry,), {})

    def test_91_copy_and_deepcopy_return_the_same_object(self):
        for obj in self.objects:
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)
            self.assertIs(copy.deepcopy({"k": [obj]})["k"][0], obj)
        self.assertIs(copy.deepcopy(self.registry).assets[0], self.registry.assets[0])

    def test_92_pickle_is_refused_for_every_protocol(self):
        for obj in self.objects:
            for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(type=type(obj).__name__, protocol=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(obj, protocol=proto)
            with self.assertRaises(TypeError):
                obj.__reduce__()
            with self.assertRaises(TypeError):
                obj.__reduce_ex__(2)
        with self.assertRaises(TypeError):
            pickle.dumps(create_audio_asset_registry([]).registry)

    def test_93_pickle_behaviour_matches_the_image_registry(self):
        from multimedia.image_asset_registry import create_image_asset_registry
        with self.assertRaises(TypeError):
            pickle.dumps(create_image_asset_registry([]).registry)
        with self.assertRaises(TypeError):
            pickle.dumps(create_audio_asset_registry([]).registry)


class TestBoundaries(unittest.TestCase):
    def test_100_module_imports_only_audio_asset_and_has_no_forbidden_calls_or_state(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(len(imports), 1)
        self.assertIsInstance(imports[0], ast.ImportFrom)
        self.assertEqual((imports[0].module, imports[0].level, [a.name for a in imports[0].names]), ("audio_asset", 1, ["AudioAsset"]))
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars", "sorted"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(reg).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_101_module_source_names_no_forbidden_dependency(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "PIL", "wave", "pydub", "soundfile",
                     "pyaudio", "numpy", "cv2", "sqlite3", "random", "time", "datetime", "anthropic", "openai", "game_creation", "GameAsset",
                     "ImageAsset", "core", "agent", "planning", "threading", "asyncio"):
            self.assertNotIn(word, names, word)

    def test_102_multimedia_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py", "image_asset.py", "image_asset_registry.py",
                          "image_operation_batch.py", "image_operation_batch_summary.py", "image_operation_dispatcher.py",
                          "image_operation_executor.py", "image_operation_metadata_executor.py", "image_operation_output.py",
                          "image_operation_output_validator.py", "image_operation_pipeline.py", "image_operation_plan.py",
                          "image_operation_request.py", "image_operation_validator.py"])
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_103_audio_asset_contract_is_unchanged_and_unaware_of_the_registry(self):
        with open(os.path.join(PY_ROOT, "multimedia", "audio_asset.py"), "rb") as fh:
            data = fh.read()
        self.assertEqual(hashlib.sha256(data).hexdigest(), AUDIO_ASSET_SHA256)
        text = data.decode("utf-8")
        for token in ("audio_asset_registry", "AudioAssetRegistry", "create_audio_asset_registry"):
            self.assertNotIn(token, text)
        import multimedia.audio_asset as aa
        self.assertEqual(aa.FIELDS, ("audio_id", "name", "description", "format", "duration_ms", "sample_rate"))
        self.assertEqual(len(aa.FAILURE_CODES), 9)

    def test_104_image_modules_are_unaware_of_the_audio_registry(self):
        for name in sorted(os.listdir(os.path.join(PY_ROOT, "multimedia"))):
            if name.startswith("image_") and name.endswith(".py"):
                with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                    text = fh.read()
                for token in ("audio_asset_registry", "AudioAssetRegistry", "AudioAssetLookupResult"):
                    self.assertNotIn(token, text, name)

    def test_105_no_other_production_module_references_the_audio_registry(self):
        tokens = ("audio_asset", "AudioAsset", "create_audio_asset")
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

    def test_106_no_filesystem_access(self):
        import builtins
        from unittest import mock

        def refuse(*a, **k):
            raise AssertionError("filesystem access attempted")
        with mock.patch.object(builtins, "open", refuse), mock.patch("os.listdir", refuse), mock.patch("os.stat", refuse), \
                mock.patch("os.scandir", refuse), mock.patch("os.walk", refuse), mock.patch("os.path.exists", refuse), \
                mock.patch("io.open", refuse):
            r = create_audio_asset_registry(three())
            self.assertTrue(r.ok)
            self.assertTrue(r.registry.lookup("theme").found)
            r.registry.to_dict()
            self.assertFalse(create_audio_asset_registry(None).ok)

    def test_107_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("AudioAssetRegistry", "AudioAssetRegistryResult", "AudioAssetLookupResult", "create_audio_asset_registry", "lookup",
                       "AUDIO_ASSET_REGISTRY_", "INVALID_COLLECTION", "INVALID_ASSET", "DUPLICATE_AUDIO_ID", "AUDIO_NOT_FOUND",
                       "INVALID_AUDIO_ID", "does NOT", "Prompt 759", "Prompt 761", "has **not** been started"):
            self.assertIn(marker, text)


AUDIO_ASSET_SHA256 = "10e0c5770c880c6443b65489b4cf4e74f89f7bad37ea57d1ff986d8a433c6b6a"

if __name__ == "__main__":
    unittest.main()
