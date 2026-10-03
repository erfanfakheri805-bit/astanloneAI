"""Prompt 733 - Section 7 game scene bundle registry (`game_creation.game_scene_bundle_registry`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from game_creation import game_asset_registry as asset_registry_module
from game_creation import game_character_registry as character_registry_module
from game_creation import game_scene_bundle_registry as reg
from game_creation import game_scene_composition_registry as composition_registry_module
from game_creation import game_scene_composition_validator as validator_module
from game_creation import game_scene_registry as scene_registry_module
from game_creation import gameplay_system_registry as system_registry_module
from game_creation.game_scene import create_game_scene
from game_creation.game_scene_bundle import GameSceneBundle, create_game_scene_bundle
from game_creation.game_scene_bundle_registry import (
    GameSceneBundleLookupResult, GameSceneBundleRegistry, GameSceneBundleRegistryResult, create_game_scene_bundle_registry)
from game_creation.game_scene_composition import create_game_scene_composition

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_scene_bundle_registry_prompt733.md")
SOURCE = os.path.join(PY_ROOT, "game_creation", "game_scene_bundle_registry.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

INVALID_COLLECTION = "GAME_SCENE_BUNDLE_REGISTRY_INVALID_COLLECTION"
INVALID_BUNDLE = "GAME_SCENE_BUNDLE_REGISTRY_INVALID_BUNDLE"
DUPLICATE_SCENE_ID = "GAME_SCENE_BUNDLE_REGISTRY_DUPLICATE_SCENE_ID"
SCENE_NOT_FOUND = "GAME_SCENE_BUNDLE_REGISTRY_SCENE_NOT_FOUND"


def make_bundle(scene_id="s1", characters=("c1",), assets=("a1", "a2"), systems=("combat",)):
    scene = create_game_scene({"scene_id": scene_id, "name": "Scene", "description": "", "scene_type": "level"})
    assert scene.ok, scene.failures
    composition = create_game_scene_composition({"scene_id": scene_id, "character_ids": list(characters), "asset_ids": list(assets),
                                                 "gameplay_system_ids": list(systems)})
    assert composition.ok, composition.failures
    result = create_game_scene_bundle(scene.scene, composition.composition)
    assert result.ok, result.failures
    return result.bundle


def make_registry(*bundles):
    result = create_game_scene_bundle_registry(list(bundles))
    assert result.ok, result.failures
    return result.registry


class BundleImpostor:
    """Looks like a bundle but is not one."""
    scene_id = "s1"
    scene = None
    composition = None

    def to_dict(self):
        return {}


class ListSubclass(list):
    pass


class TupleSubclass(tuple):
    pass


class StrSubclass(str):
    pass


class TestValidRegistry(unittest.TestCase):
    def test_01_valid_registry(self):
        b = make_bundle("arena")
        result = create_game_scene_bundle_registry([b])
        self.assertIsInstance(result, GameSceneBundleRegistryResult)
        self.assertTrue(result.ok)
        self.assertIsInstance(result.registry, GameSceneBundleRegistry)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.codes(), [])
        self.assertEqual(result.to_dict(), {"ok": True, "registry": {"bundles": [b.to_dict()]}, "failures": []})

    def test_02_empty_registry_from_list_and_tuple(self):
        for empty in ([], ()):
            result = create_game_scene_bundle_registry(empty)
            self.assertTrue(result.ok)
            self.assertEqual(result.registry.bundles, ())
            self.assertEqual(result.registry.scene_ids, ())
            self.assertEqual(result.registry.to_dict(), {"bundles": []})
            self.assertFalse(result.registry.lookup("s1").found)

    def test_03_one_bundle(self):
        b = make_bundle("only")
        r = make_registry(b)
        self.assertEqual(r.bundles, (b,))
        self.assertIs(r.bundles[0], b)
        self.assertEqual(r.scene_ids, ("only",))

    def test_04_multiple_bundles_and_tuple_input(self):
        bs = [make_bundle("a"), make_bundle("b"), make_bundle("c")]
        for source in (list(bs), tuple(bs)):
            result = create_game_scene_bundle_registry(source)
            self.assertTrue(result.ok)
            self.assertEqual(result.registry.bundles, tuple(bs))
            for original, stored in zip(bs, result.registry.bundles):
                self.assertIs(original, stored)

    def test_05_input_order_is_preserved_not_sorted(self):
        ids = ["zeta", "alpha", "Mid", "beta", "10", "9"]
        r = make_registry(*[make_bundle(i) for i in ids])
        self.assertEqual(r.scene_ids, tuple(ids))
        self.assertEqual([b["scene_id"] for b in r.to_dict()["bundles"]], ids)

    def test_06_different_order_is_a_different_registry(self):
        a, b = make_bundle("a"), make_bundle("b")
        self.assertNotEqual(make_registry(a, b), make_registry(b, a))


class TestInvalidInput(unittest.TestCase):
    def test_07_invalid_collection(self):
        b = make_bundle()
        for bad in (None, "s1", b"s1", 5, 1.5, True, {"s1": b}, {b}, frozenset([b]), (x for x in [b]), iter([b]), b,
                    ListSubclass([b]), TupleSubclass([b]), range(3), object()):
            result = create_game_scene_bundle_registry(bad)
            self.assertFalse(result.ok, repr(bad))
            self.assertIsNone(result.registry)
            self.assertEqual(result.codes(), [INVALID_COLLECTION])
            self.assertEqual(result.failures[0]["field"], "bundles")

    def test_08_invalid_collection_reports_nothing_else(self):
        result = create_game_scene_bundle_registry({"a": 1, "b": 2})
        self.assertEqual(result.codes(), [INVALID_COLLECTION])

    def test_09_invalid_bundle_items(self):
        for bad in (None, "s1", 5, {}, [], (), object(), BundleImpostor(), make_bundle().to_dict()):
            result = create_game_scene_bundle_registry([make_bundle("ok"), bad])
            self.assertFalse(result.ok, repr(bad))
            self.assertIsNone(result.registry)
            self.assertEqual(result.codes(), [INVALID_BUNDLE])
            self.assertIn("bundles[1]", result.failures[0]["message"])

    def test_10_invalid_bundle_includes_scene_composition_and_results(self):
        b = make_bundle("s1")
        result = create_game_scene_bundle_registry([b.scene, b.composition, create_game_scene_bundle(b.scene, b.composition)])
        self.assertEqual(result.codes(), [INVALID_BUNDLE] * 3)

    def test_11_invalid_items_are_never_duplicates(self):
        result = create_game_scene_bundle_registry([BundleImpostor(), BundleImpostor(), make_bundle("s1")])
        self.assertEqual(result.codes(), [INVALID_BUNDLE, INVALID_BUNDLE])

    def test_12_invalid_input_never_raises(self):
        weird = [None, 0, "", (), [], {}, set(), object(), Ellipsis, BundleImpostor, make_bundle, float("nan"), [[]], [None, None], ([1],), [BundleImpostor()]]
        for bad in weird:
            try:
                result = create_game_scene_bundle_registry(bad)
            except Exception as exc:      # pragma: no cover
                self.fail("raised %r for %r" % (exc, bad))
            self.assertIsInstance(result, GameSceneBundleRegistryResult)


class TestDuplicates(unittest.TestCase):
    def test_13_duplicate_scene_id(self):
        first, second = make_bundle("dup", ("c1",)), make_bundle("dup", ("c2",))
        result = create_game_scene_bundle_registry([first, second])
        self.assertFalse(result.ok)
        self.assertIsNone(result.registry)
        self.assertEqual(result.codes(), [DUPLICATE_SCENE_ID])
        self.assertIn("bundles[1]", result.failures[0]["message"])
        self.assertIn("'dup'", result.failures[0]["message"])

    def test_14_the_same_bundle_object_twice_is_a_duplicate(self):
        b = make_bundle("x")
        self.assertEqual(create_game_scene_bundle_registry([b, b]).codes(), [DUPLICATE_SCENE_ID])

    def test_15_equal_but_distinct_bundles_are_duplicates(self):
        self.assertEqual(create_game_scene_bundle_registry([make_bundle("x"), make_bundle("x")]).codes(), [DUPLICATE_SCENE_ID])

    def test_16_each_later_repeat_reports_once_in_order(self):
        bs = [make_bundle("a"), make_bundle("b"), make_bundle("a"), make_bundle("b"), make_bundle("a")]
        result = create_game_scene_bundle_registry(bs)
        self.assertEqual(result.codes(), [DUPLICATE_SCENE_ID] * 3)
        messages = [f["message"] for f in result.failures]
        self.assertEqual([("bundles[%d]" % i) in m for i, m in zip((2, 3, 4), messages)], [True] * 3)

    def test_17_case_and_whitespace_variants_are_not_duplicates(self):
        ids = ["Arena", "arena", "ARENA", "arena ", " arena", "arena\t", "arena\n", "are na"]
        result = create_game_scene_bundle_registry([make_bundle(i) for i in ids])
        self.assertTrue(result.ok, result.failures)
        self.assertEqual(result.registry.scene_ids, tuple(ids))

    def test_18_failure_ordering_follows_input_order(self):
        items = [make_bundle("a"), None, make_bundle("a"), BundleImpostor(), make_bundle("b"), make_bundle("b"), 7, make_bundle("a")]
        result = create_game_scene_bundle_registry(items)
        self.assertEqual(result.codes(), [INVALID_BUNDLE, DUPLICATE_SCENE_ID, INVALID_BUNDLE, DUPLICATE_SCENE_ID, INVALID_BUNDLE,
                                          DUPLICATE_SCENE_ID])
        indices = [int(f["message"].split("[")[1].split("]")[0]) for f in result.failures]
        self.assertEqual(indices, [1, 2, 3, 5, 6, 7])
        self.assertEqual(result, create_game_scene_bundle_registry(list(items)))
        self.assertEqual(result.codes(), create_game_scene_bundle_registry(tuple(items)).codes())


class TestLookup(unittest.TestCase):
    def test_19_exact_lookup_success(self):
        a, b = make_bundle("a"), make_bundle("b")
        r = make_registry(a, b)
        hit = r.lookup("b")
        self.assertIsInstance(hit, GameSceneBundleLookupResult)
        self.assertTrue(hit.found)
        self.assertIs(hit.bundle, b)
        self.assertIsNone(hit.code)
        self.assertEqual(hit.to_dict(), {"found": True, "bundle": b.to_dict(), "code": None})

    def test_20_exact_lookup_miss(self):
        r = make_registry(make_bundle("a"))
        miss = r.lookup("zzz")
        self.assertFalse(miss.found)
        self.assertIsNone(miss.bundle)
        self.assertEqual(miss.code, SCENE_NOT_FOUND)
        self.assertEqual(miss.to_dict(), {"found": False, "bundle": None, "code": SCENE_NOT_FOUND})

    def test_21_non_string_lookup_is_not_found_and_never_raises(self):
        r = make_registry(make_bundle("1"), make_bundle("None"), make_bundle("True"))
        for bad in (None, 1, 1.0, True, b"1", [], ["1"], ("1",), {}, {"1"}, object(), StrSubclass("1"), make_bundle("1")):
            result = r.lookup(bad)
            self.assertFalse(result.found, repr(bad))
            self.assertIsNone(result.bundle)
            self.assertEqual(result.code, SCENE_NOT_FOUND)

    def test_22_case_sensitive_ids(self):
        r = make_registry(make_bundle("Arena"), make_bundle("arena"))
        self.assertEqual(r.lookup("Arena").bundle.scene_id, "Arena")
        self.assertEqual(r.lookup("arena").bundle.scene_id, "arena")
        self.assertFalse(r.lookup("ARENA").found)
        self.assertFalse(make_registry(make_bundle("Arena")).lookup("arena").found)

    def test_23_whitespace_sensitive_ids(self):
        r = make_registry(make_bundle("arena"))
        for bad in ("arena ", " arena", "arena\n", "\tarena", "are na", ""):
            self.assertFalse(r.lookup(bad).found, repr(bad))
        r2 = make_registry(make_bundle(" arena "))
        self.assertTrue(r2.lookup(" arena ").found)
        self.assertFalse(r2.lookup("arena").found)

    def test_24_lookup_is_deterministic_and_equal_results_hash_equal(self):
        r = make_registry(make_bundle("a"))
        self.assertEqual(r.lookup("a"), r.lookup("a"))
        self.assertEqual(hash(r.lookup("a")), hash(r.lookup("a")))
        self.assertEqual(r.lookup("q"), r.lookup(None))
        self.assertNotEqual(r.lookup("a"), r.lookup("q"))
        self.assertEqual(len({r.lookup("q"), r.lookup(5)}), 1)


class TestImmutabilityAndEquality(unittest.TestCase):
    def test_25_deterministic_equality_and_hash(self):
        r1 = make_registry(make_bundle("a"), make_bundle("b"))
        r2 = make_registry(make_bundle("a"), make_bundle("b"))
        self.assertIsNot(r1, r2)
        self.assertEqual(r1, r2)
        self.assertEqual(hash(r1), hash(r2))
        self.assertNotEqual(r1, make_registry(make_bundle("a")))
        self.assertNotEqual(r1, make_registry(make_bundle("a"), make_bundle("b", ("other",))))
        self.assertNotEqual(r1, (r1.bundles,))
        self.assertFalse(r1 == r1.to_dict())
        self.assertEqual(len({r1, r2}), 1)
        res1 = create_game_scene_bundle_registry([make_bundle("a")])
        res2 = create_game_scene_bundle_registry((make_bundle("a"),))
        self.assertEqual(res1, res2)
        self.assertEqual(hash(res1), hash(res2))
        bad1, bad2 = create_game_scene_bundle_registry(None), create_game_scene_bundle_registry("x")
        self.assertEqual(bad1, bad2)
        self.assertEqual(hash(bad1), hash(bad2))
        self.assertNotEqual(bad1, res1)

    def test_26_fresh_to_dict(self):
        r = make_registry(make_bundle("a"), make_bundle("b"))
        d1, d2 = r.to_dict(), r.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertIsNot(d1["bundles"], d2["bundles"])
        self.assertIsNot(d1["bundles"][0], d2["bundles"][0])
        self.assertIsNot(d1["bundles"][0]["composition"]["asset_ids"], d2["bundles"][0]["composition"]["asset_ids"])
        snapshot = r.to_dict()
        d1["bundles"].append("junk")
        d1["bundles"][0]["scene_id"] = "mutated"
        d1["bundles"][0]["composition"]["asset_ids"].append("junk")
        self.assertEqual(r.to_dict(), snapshot)
        self.assertEqual(r.scene_ids, ("a", "b"))
        result = create_game_scene_bundle_registry([make_bundle("a")])
        self.assertIsNot(result.to_dict(), result.to_dict())
        self.assertIsNot(result.to_dict()["registry"], result.to_dict()["registry"])
        bad = create_game_scene_bundle_registry(None)
        self.assertIsNot(bad.failures, bad.failures)
        self.assertIsNot(bad.failures[0], bad.failures[0])
        self.assertIsNot(bad.codes(), bad.codes())
        bad.failures.append("junk")
        bad.failures[0]["code"] = "x"
        bad.codes().append("x")
        self.assertEqual(bad.codes(), [INVALID_COLLECTION])
        hit = r.lookup("a").to_dict()
        hit["bundle"]["scene_id"] = "mutated"
        self.assertEqual(r.lookup("a").to_dict()["bundle"]["scene_id"], "a")

    def test_27_to_dict_is_plain_data_only(self):
        def check(value):
            self.assertIn(type(value), (dict, list, str, bool, type(None), int))
            if type(value) is dict:
                for k, v in value.items():
                    self.assertIs(type(k), str)
                    check(v)
            elif type(value) is list:
                for v in value:
                    check(v)
        r = make_registry(make_bundle("a"), make_bundle("b"))
        check(r.to_dict())
        check(create_game_scene_bundle_registry([make_bundle("a")]).to_dict())
        check(create_game_scene_bundle_registry([make_bundle("a"), make_bundle("a"), None]).to_dict())
        check(r.lookup("a").to_dict())
        check(r.lookup("zzz").to_dict())

    def test_28_immutable_tuple_properties(self):
        r = make_registry(make_bundle("a"), make_bundle("b"))
        self.assertIs(type(r.bundles), tuple)
        self.assertIs(type(r.scene_ids), tuple)
        self.assertIs(r.bundles, r.bundles)
        for attr in ("append", "extend", "insert", "pop", "remove", "sort", "clear"):
            self.assertFalse(hasattr(r.bundles, attr))
            self.assertFalse(hasattr(r.scene_ids, attr))
        with self.assertRaises(TypeError):
            r.bundles[0] = None
        with self.assertRaises(TypeError):
            r.scene_ids[0] = "x"

    def test_29_stored_collection_is_independent_of_the_input_list(self):
        source = [make_bundle("a"), make_bundle("b")]
        r = create_game_scene_bundle_registry(source).registry
        source.append(make_bundle("c"))
        source[0] = None
        self.assertEqual(r.scene_ids, ("a", "b"))
        self.assertEqual(r.bundles[0].scene_id, "a")

    def test_30_attributes_are_read_only(self):
        r = make_registry(make_bundle("a"))
        result = create_game_scene_bundle_registry([make_bundle("a")])
        lookup = r.lookup("a")
        for obj, names in ((r, ("bundles", "scene_ids", "_bundles", "extra", "lookup")),
                           (result, ("ok", "registry", "failures", "_registry", "_failures", "extra")),
                           (lookup, ("found", "bundle", "code", "_found", "_bundle", "_code", "extra"))):
            for name in names:
                with self.assertRaises(AttributeError, msg=(type(obj).__name__, name)):
                    setattr(obj, name, 1)
                with self.assertRaises(AttributeError, msg=(type(obj).__name__, name)):
                    delattr(obj, name)
            self.assertFalse(hasattr(obj, "__dict__"))
        self.assertEqual(r.scene_ids, ("a",))

    def test_31_direct_construction_is_refused(self):
        b = make_bundle("a")
        with self.assertRaises(TypeError):
            GameSceneBundleRegistry(object(), [b])
        with self.assertRaises(TypeError):
            GameSceneBundleRegistry([b])
        with self.assertRaises(TypeError):
            GameSceneBundleRegistry(None, [b])
        with self.assertRaises(TypeError):
            GameSceneBundleRegistryResult(object(), None, [])
        with self.assertRaises(TypeError):
            GameSceneBundleRegistryResult(None, None, [])
        with self.assertRaises(TypeError):
            GameSceneBundleLookupResult(object(), True, b, None)
        with self.assertRaises(TypeError):
            GameSceneBundleLookupResult(True, b, None)
        with self.assertRaises(TypeError):
            GameSceneBundleRegistry(reg._CREATE_TOKEN.__class__(), [b])

    def test_32_subclassing_is_refused(self):
        for base in (GameSceneBundleRegistry, GameSceneBundleRegistryResult, GameSceneBundleLookupResult):
            with self.assertRaises(TypeError):
                type("Sub", (base,), {})

    def test_33_copy_returns_the_same_object(self):
        r = make_registry(make_bundle("a"))
        result = create_game_scene_bundle_registry([make_bundle("a")])
        lookup = r.lookup("a")
        for obj in (r, result, lookup, result.registry, r.lookup("nope")):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)

    def test_34_pickle_is_refused(self):
        r = make_registry(make_bundle("a"))
        result = create_game_scene_bundle_registry([make_bundle("a")])
        for obj in (r, result, r.lookup("a"), r.lookup("nope")):
            for protocol in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(obj, protocol)

    def test_35_repr_is_deterministic(self):
        r = make_registry(make_bundle("a"), make_bundle("b"))
        self.assertEqual(repr(r), repr(make_registry(make_bundle("a"), make_bundle("b"))))
        self.assertIn("'a'", repr(r))
        self.assertEqual(repr(r.lookup("q")), repr(r.lookup(3)))
        self.assertEqual(repr(create_game_scene_bundle_registry(None)), "GameSceneBundleRegistryResult(ok=False, failures=1)")


class TestNoSideEffects(unittest.TestCase):
    def test_36_supplied_bundles_and_collection_are_not_mutated(self):
        bundles = [make_bundle("a"), make_bundle("b")]
        before_dicts = [b.to_dict() for b in bundles]
        before_keys = [(b.scene, b.composition) for b in bundles]
        source = list(bundles)
        r = create_game_scene_bundle_registry(source).registry
        create_game_scene_bundle_registry(source + [bundles[0]])
        r.lookup("a")
        r.to_dict()
        self.assertEqual(source, bundles)
        self.assertEqual([b.to_dict() for b in bundles], before_dicts)
        for b, (scene, composition) in zip(bundles, before_keys):
            self.assertIs(b.scene, scene)
            self.assertIs(b.composition, composition)
        self.assertTrue(all(stored is original for stored, original in zip(r.bundles, bundles)))
        tup = tuple(bundles)
        create_game_scene_bundle_registry(tup)
        self.assertEqual(tup, tuple(bundles))

    def test_37_no_composition_registry_or_validator_lookup(self):
        b = make_bundle("a")
        targets = [mock.patch.object(composition_registry_module, "create_game_scene_composition_registry", side_effect=AssertionError("called")),
                   mock.patch.object(composition_registry_module.GameSceneCompositionRegistry, "lookup", side_effect=AssertionError("called"))]
        for name in dir(validator_module):
            if name.startswith("validate") or name.startswith("create"):
                targets.append(mock.patch.object(validator_module, name, side_effect=AssertionError("called")))
        entered = [t.start() for t in targets]
        try:
            r = create_game_scene_bundle_registry([b]).registry
            self.assertTrue(r.lookup("a").found)
            self.assertFalse(r.lookup("b").found)
            r.to_dict()
            create_game_scene_bundle_registry([b, b, None])
        finally:
            for t in targets:
                t.stop()
        self.assertTrue(entered)

    def test_38_no_other_section7_registry_is_consulted(self):
        b = make_bundle("a")
        patches = [mock.patch.object(scene_registry_module.GameSceneRegistry, "lookup", side_effect=AssertionError("called")),
                   mock.patch.object(character_registry_module.GameCharacterRegistry, "lookup", side_effect=AssertionError("called")),
                   mock.patch.object(asset_registry_module.GameAssetRegistry, "lookup", side_effect=AssertionError("called")),
                   mock.patch.object(system_registry_module.GameplaySystemRegistry, "lookup", side_effect=AssertionError("called"))]
        for p in patches:
            p.start()
        try:
            r = create_game_scene_bundle_registry([b]).registry
            r.lookup("a")
            r.lookup(None)
        finally:
            for p in patches:
                p.stop()

    def test_39_arbitrary_composition_contents_remain_untouched(self):
        odd = make_bundle("odd", ("ghost-character", "Ghost Character"), ("missing asset", "A", "a"), ("no-such-system",))
        empty = make_bundle("empty", (), (), ())
        before = (odd.to_dict(), empty.to_dict())
        r = make_registry(odd, empty)
        self.assertIs(r.lookup("odd").bundle, odd)
        self.assertEqual(r.lookup("odd").bundle.composition.character_ids, odd.composition.character_ids)
        self.assertEqual(r.lookup("odd").bundle.composition.character_ids, ("ghost-character", "Ghost Character"))
        self.assertEqual(r.lookup("odd").bundle.composition.asset_ids, ("missing asset", "A", "a"))
        self.assertEqual((odd.to_dict(), empty.to_dict()), before)
        self.assertEqual(r.to_dict()["bundles"], list(before))

    def test_40_many_bundles_round_trip_in_order(self):
        bs = [make_bundle("scene-%d" % i, ("unregistered-c-%d" % i,), ("unregistered-a-%d" % i,), ("unregistered-g-%d" % i,)) for i in range(25)]
        result = create_game_scene_bundle_registry(bs)
        self.assertTrue(result.ok)
        self.assertEqual(result.registry.bundles, tuple(bs))
        for b in bs:
            self.assertIs(result.registry.lookup(b.scene_id).bundle, b)


class TestSourceBoundaries(unittest.TestCase):
    def test_41_module_imports_only_game_scene_bundle(self):
        with open(SOURCE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual([(n.module, tuple(a.name for a in n.names)) for n in imports], [("game_scene_bundle", ("GameSceneBundle",))])

    def test_42_module_uses_no_unrelated_registry_validator_or_runtime_names(self):
        with open(SOURCE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("GameScene", "GameSceneComposition", "GameSceneCompositionRegistry", "GameSceneCompositionValidator", "GameSceneRegistry",
                          "GameCharacterRegistry", "GameAssetRegistry", "GameplaySystemRegistry", "GameProject", "GameProjectStructure",
                          "GameProjectValidator", "validate_game_scene_composition", "validate_game_project", "create_game_scene",
                          "create_game_scene_bundle", "create_game_scene_composition", "create_game_scene_composition_registry",
                          "Core", "Planner", "AgentLoop", "process_input", "composition", "scene"):
            self.assertNotIn(forbidden, names, forbidden)
        class_names = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
        self.assertEqual(class_names, {"GameSceneBundleLookupResult", "GameSceneBundleRegistry", "GameSceneBundleRegistryResult"})

    def test_43_module_has_no_io_normalization_or_module_state(self):
        with open(SOURCE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "sorted", "str", "copy.copy", "copy.deepcopy"):
            self.assertNotIn(forbidden, calls)
        for method in ("strip", "lstrip", "rstrip", "lower", "upper", "casefold", "normalize", "title", "encode", "decode", "replace", "format"):
            self.assertFalse([c for c in calls if c.endswith("." + method)], method)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(reg).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_44_lookup_compares_with_exact_equality_only(self):
        with open(SOURCE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        lookup = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "lookup"][0]
        compares = [n for n in ast.walk(lookup) if isinstance(n, ast.Compare)]
        self.assertTrue(any(isinstance(n.ops[0], ast.Eq) and ast.unparse(n.left) == "bundle.scene_id" for n in compares))
        self.assertFalse([n for n in ast.walk(lookup) if isinstance(n, ast.Call) and ast.unparse(n.func) not in ("type", "GameSceneBundleLookupResult")])

    def test_45_stable_failure_codes(self):
        self.assertEqual(reg.FAILURE_CODES, (INVALID_COLLECTION, INVALID_BUNDLE, DUPLICATE_SCENE_ID, SCENE_NOT_FOUND))
        for code in reg.FAILURE_CODES:
            self.assertTrue(code.startswith("GAME_SCENE_BUNDLE_REGISTRY_"))
        self.assertEqual(len(set(reg.FAILURE_CODES)), 4)


class TestScopeAndDocumentation(unittest.TestCase):
    def test_46_earlier_modules_are_untouched_and_unaware_of_the_registry(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py",
            "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py",
            "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py",
            "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in ("game_project.py", "game_project_structure.py", "game_scene.py", "game_character.py", "game_asset.py",
                    "game_scene_registry.py", "game_character_registry.py", "gameplay_system_registry.py", "game_asset_registry.py",
                    "game_scene_composition.py", "game_project_validator.py", "game_scene_composition_validator.py",
                    "game_scene_composition_registry.py", "game_scene_bundle.py"):
            with open(os.path.join(PY_ROOT, "game_creation", rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_scene_bundle_registry", "create_game_scene_bundle_registry", "GameSceneBundleRegistry", "GameSceneBundleLookupResult"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "game_scene_bundle_registry", "create_game_scene_bundle_registry"):
                self.assertNotIn(token, text, (rel, token))

    def test_47_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_game_scene_bundle_registry", "GameSceneBundleRegistryResult", "GameSceneBundleRegistry", "GameSceneBundleLookupResult",
                       "GAME_SCENE_BUNDLE_REGISTRY_", "INVALID_COLLECTION", "INVALID_BUNDLE", "DUPLICATE_SCENE_ID", "SCENE_NOT_FOUND", "exact",
                       "does NOT", "Prompt 732", "Prompt 730", "Prompt 731", "Prompt 734"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
