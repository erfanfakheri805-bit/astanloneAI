"""Prompt 731 - Section 7 game scene composition registry (`game_creation.game_scene_composition_registry`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from game_creation import game_asset_registry as asset_registry_module
from game_creation import game_character_registry as character_registry_module
from game_creation import game_project_validator as project_validator_module
from game_creation import game_scene_composition_registry as reg
from game_creation import game_scene_composition_validator as validator_module
from game_creation import gameplay_system_registry as system_registry_module
from game_creation.game_scene_composition import GameSceneComposition, create_game_scene_composition
from game_creation.game_scene_composition_registry import (
    GameSceneCompositionLookupResult, GameSceneCompositionRegistry, GameSceneCompositionRegistryResult,
    create_game_scene_composition_registry)

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_scene_composition_registry_prompt731.md")
SOURCE = os.path.join(PY_ROOT, "game_creation", "game_scene_composition_registry.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

INVALID_COLLECTION = "GAME_SCENE_COMPOSITION_REGISTRY_INVALID_COLLECTION"
INVALID_COMPOSITION = "GAME_SCENE_COMPOSITION_REGISTRY_INVALID_COMPOSITION"
DUPLICATE_SCENE_ID = "GAME_SCENE_COMPOSITION_REGISTRY_DUPLICATE_SCENE_ID"
SCENE_NOT_FOUND = "GAME_SCENE_COMPOSITION_REGISTRY_SCENE_NOT_FOUND"


def make_composition(scene_id="s1", characters=("c1",), assets=("a1", "a2"), systems=("combat",)):
    result = create_game_scene_composition({"scene_id": scene_id, "character_ids": list(characters), "asset_ids": list(assets),
                                            "gameplay_system_ids": list(systems)})
    assert result.ok, result.failures
    return result.composition


def make_registry(*compositions):
    result = create_game_scene_composition_registry(list(compositions))
    assert result.ok, result.failures
    return result.registry


class Impostor:
    """Looks like a composition but is not one."""
    scene_id = "s1"
    character_ids = ()
    asset_ids = ()
    gameplay_system_ids = ()

    def to_dict(self):
        return {}


class ListSubclass(list):
    pass


class TupleSubclass(tuple):
    pass


class TestValidRegistry(unittest.TestCase):
    def test_01_valid_registry(self):
        c1, c2 = make_composition("s1"), make_composition("s2")
        result = create_game_scene_composition_registry([c1, c2])
        self.assertIsInstance(result, GameSceneCompositionRegistryResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.codes(), [])
        self.assertIsInstance(result.registry, GameSceneCompositionRegistry)
        self.assertEqual(result.registry.compositions, (c1, c2))
        self.assertIs(result.registry.compositions[0], c1)

    def test_02_empty_registry_is_valid_for_list_and_tuple(self):
        for empty in ([], ()):
            result = create_game_scene_composition_registry(empty)
            self.assertTrue(result.ok)
            self.assertEqual(result.registry.compositions, ())
            self.assertEqual(result.registry.scene_ids, ())
            self.assertEqual(result.registry.to_dict(), {"compositions": []})
            self.assertFalse(result.registry.lookup("anything").found)

    def test_03_order_is_preserved(self):
        comps = [make_composition(i) for i in ("zeta", "alpha", "mid", "beta")]
        self.assertEqual(make_registry(*comps).scene_ids, ("zeta", "alpha", "mid", "beta"))
        self.assertEqual(create_game_scene_composition_registry(tuple(reversed(comps))).registry.scene_ids, ("beta", "mid", "alpha", "zeta"))
        self.assertEqual([c["scene_id"] for c in make_registry(*comps).to_dict()["compositions"]], ["zeta", "alpha", "mid", "beta"])

    def test_04_multiple_compositions_keep_their_own_contents(self):
        c1 = make_composition("s1", ("c1",), ("a1",), ("combat",))
        c2 = make_composition("s2", (), (), ())
        c3 = make_composition("s3", ("c2", "c3"), ("a2", "a3"), ("ai", "physics"))
        registry = make_registry(c1, c2, c3)
        self.assertEqual(len(registry.compositions), 3)
        self.assertEqual(registry.lookup("s3").composition.character_ids, ("c2", "c3"))
        self.assertEqual(registry.lookup("s2").composition.asset_ids, ())

    def test_05_arbitrary_ids_are_accepted_and_not_resolved_anywhere(self):
        odd = make_composition("no-such-scene", ("ghost-character",), ("ghost-asset",), ("ghost-system",))
        registry = make_registry(odd)
        self.assertEqual(registry.scene_ids, ("no-such-scene",))
        self.assertTrue(registry.lookup("no-such-scene").found)
        self.assertEqual(registry.lookup("no-such-scene").composition.character_ids, ("ghost-character",))


class TestInvalidInput(unittest.TestCase):
    def test_06_invalid_collection_types(self):
        c = make_composition()
        for bad in (None, "s1", b"s1", 7, 1.5, True, {c}, frozenset([c]), {"s1": c}, (x for x in [c]), iter([c]), c,
                    ListSubclass([c]), TupleSubclass([c]), range(0), object()):
            result = create_game_scene_composition_registry(bad)
            self.assertFalse(result.ok, bad)
            self.assertIsNone(result.registry, bad)
            self.assertEqual(result.codes(), [INVALID_COLLECTION], bad)
            self.assertEqual(result.failures[0]["field"], "compositions")

    def test_07_invalid_composition_items(self):
        c = make_composition()
        for bad in (None, "s1", 5, {}, {"scene_id": "s1"}, [c], (c,), Impostor(), c.to_dict(), object(), GameSceneComposition):
            result = create_game_scene_composition_registry([c, bad])
            self.assertFalse(result.ok, bad)
            self.assertIsNone(result.registry)
            self.assertEqual(result.codes(), [INVALID_COMPOSITION], bad)
            self.assertIn("compositions[1]", result.failures[0]["message"])

    def test_08_duplicate_scene_ids(self):
        result = create_game_scene_composition_registry([make_composition("s1"), make_composition("s2"), make_composition("s1", ("other",))])
        self.assertFalse(result.ok)
        self.assertIsNone(result.registry)
        self.assertEqual(result.codes(), [DUPLICATE_SCENE_ID])
        self.assertIn("compositions[2]", result.failures[0]["message"])
        self.assertIn("'s1'", result.failures[0]["message"])

    def test_09_identical_object_twice_is_a_duplicate(self):
        c = make_composition("s1")
        self.assertEqual(create_game_scene_composition_registry([c, c]).codes(), [DUPLICATE_SCENE_ID])
        self.assertEqual(create_game_scene_composition_registry((c, make_composition("s1"))).codes(), [DUPLICATE_SCENE_ID])

    def test_10_every_repeat_is_reported_in_input_order(self):
        comps = [make_composition("a"), make_composition("a"), make_composition("b"), make_composition("a"), make_composition("b")]
        result = create_game_scene_composition_registry(comps)
        self.assertEqual(result.codes(), [DUPLICATE_SCENE_ID] * 3)
        self.assertEqual([f["message"].split("]")[0] for f in result.failures], ["compositions[1", "compositions[3", "compositions[4"])

    def test_11_deterministic_failure_ordering_mixes_invalid_and_duplicate_by_position(self):
        a, b = make_composition("a"), make_composition("b")
        items = [a, "bad", b, make_composition("a"), None, make_composition("b"), 3, a]
        result = create_game_scene_composition_registry(items)
        self.assertEqual(result.codes(), [INVALID_COMPOSITION, DUPLICATE_SCENE_ID, INVALID_COMPOSITION, DUPLICATE_SCENE_ID,
                                          INVALID_COMPOSITION, DUPLICATE_SCENE_ID])
        self.assertEqual([int(f["message"].split("[")[1].split("]")[0]) for f in result.failures], [1, 3, 4, 5, 6, 7])
        self.assertEqual(create_game_scene_composition_registry(items), result)
        self.assertEqual(create_game_scene_composition_registry(list(items)).to_dict(), result.to_dict())

    def test_12_invalid_items_never_count_as_duplicates_or_seen_ids(self):
        result = create_game_scene_composition_registry([Impostor(), Impostor(), make_composition("s1")])
        self.assertEqual(result.codes(), [INVALID_COMPOSITION, INVALID_COMPOSITION])

    def test_13_factory_never_raises_for_invalid_top_level_input(self):
        class Hostile:
            def __iter__(self):
                raise RuntimeError("must not be iterated")

            def __len__(self):
                raise RuntimeError("must not be measured")

            def __eq__(self, other):
                raise RuntimeError("must not be compared")

            __hash__ = None

        for bad in (Hostile(), None, 1, "x", {1, 2}, (i for i in range(3))):
            result = create_game_scene_composition_registry(bad)
            self.assertFalse(result.ok)
            self.assertEqual(result.codes(), [INVALID_COLLECTION])
        self.assertEqual(create_game_scene_composition_registry([Hostile()]).codes(), [INVALID_COMPOSITION])

    def test_14_wrong_argument_count_is_a_plain_type_error(self):
        with self.assertRaises(TypeError):
            create_game_scene_composition_registry()
        with self.assertRaises(TypeError):
            create_game_scene_composition_registry([], [])

    def test_15_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(reg.FAILURE_CODES, (INVALID_COLLECTION, INVALID_COMPOSITION, DUPLICATE_SCENE_ID, SCENE_NOT_FOUND))
        self.assertEqual(len(set(reg.FAILURE_CODES)), 4)
        self.assertTrue(all(c.startswith("GAME_SCENE_COMPOSITION_REGISTRY_") for c in reg.FAILURE_CODES))
        result = create_game_scene_composition_registry(["x"])
        for f in result.failures:
            self.assertIn(f["code"], reg.FAILURE_CODES)
            self.assertEqual(set(f), {"code", "field", "message"})
        self.assertNotIn(SCENE_NOT_FOUND, [create_game_scene_composition_registry(v).codes()[0] for v in (None, ["x"])])


class TestLookup(unittest.TestCase):
    def test_16_exact_lookup_success(self):
        c1, c2 = make_composition("s1"), make_composition("s2", ("c9",))
        registry = make_registry(c1, c2)
        found = registry.lookup("s2")
        self.assertIsInstance(found, GameSceneCompositionLookupResult)
        self.assertTrue(found.found)
        self.assertIs(found.composition, c2)
        self.assertIsNone(found.code)
        self.assertIs(registry.lookup("s1").composition, c1)

    def test_17_exact_lookup_miss_is_deterministic(self):
        registry = make_registry(make_composition("s1"))
        miss = registry.lookup("nope")
        self.assertFalse(miss.found)
        self.assertIsNone(miss.composition)
        self.assertEqual(miss.code, SCENE_NOT_FOUND)
        self.assertEqual(registry.lookup("nope"), miss)
        self.assertEqual(registry.lookup("other"), miss)
        self.assertEqual(hash(registry.lookup("nope")), hash(miss))
        self.assertEqual(miss.to_dict(), {"found": False, "composition": None, "code": SCENE_NOT_FOUND})
        self.assertEqual(make_registry().lookup("s1"), miss)

    def test_18_ids_are_case_sensitive(self):
        registry = make_registry(make_composition("Arena"), make_composition("arena"))
        self.assertEqual(registry.scene_ids, ("Arena", "arena"))
        self.assertEqual(registry.lookup("Arena").composition.scene_id, "Arena")
        self.assertEqual(registry.lookup("arena").composition.scene_id, "arena")
        self.assertFalse(registry.lookup("ARENA").found)
        self.assertFalse(make_registry(make_composition("Arena")).lookup("arena").found)

    def test_19_ids_are_whitespace_sensitive(self):
        registry = make_registry(make_composition("arena"), make_composition("arena "), make_composition(" arena"), make_composition("are na"))
        self.assertEqual(len(registry.compositions), 4)
        for sid in ("arena", "arena ", " arena", "are na"):
            self.assertEqual(registry.lookup(sid).composition.scene_id, sid)
        for sid in ("arena\n", "\tarena", "  arena", "arena  ", "ar ena"):
            self.assertFalse(registry.lookup(sid).found, repr(sid))
        self.assertFalse(make_registry(make_composition("arena")).lookup(" arena").found)

    def test_20_lookup_uses_exact_ids_no_coercion_or_normalization(self):
        registry = make_registry(make_composition("1"), make_composition("Caf\u00e9"), make_composition("s1"))
        for bad in (1, 1.0, None, b"s1", ["s1"], ("s1",), {"s1"}, object(), True, ""):
            result = registry.lookup(bad)
            self.assertFalse(result.found, repr(bad))
            self.assertEqual(result.code, SCENE_NOT_FOUND)

        class StrSubclass(str):
            pass

        self.assertFalse(registry.lookup(StrSubclass("s1")).found)
        self.assertFalse(registry.lookup("Cafe\u0301").found)      # composed vs decomposed: no Unicode normalization
        self.assertTrue(registry.lookup("Caf\u00e9").found)
        self.assertTrue(registry.lookup("1").found)

    def test_21_lookup_never_raises_and_takes_exactly_one_argument(self):
        registry = make_registry(make_composition("s1"))

        class Hostile:
            def __eq__(self, other):
                raise RuntimeError("must not be compared")

            __hash__ = None

        self.assertFalse(registry.lookup(Hostile()).found)
        with self.assertRaises(TypeError):
            registry.lookup()

    def test_22_lookup_result_is_immutable_and_guarded(self):
        found = make_registry(make_composition("s1")).lookup("s1")
        for name in ("found", "composition", "code"):
            with self.assertRaises(AttributeError):
                setattr(found, name, None)
            with self.assertRaises(AttributeError):
                delattr(found, name)
        with self.assertRaises(AttributeError):
            found.extra = 1
        self.assertFalse(hasattr(found, "__dict__"))
        with self.assertRaises(TypeError):
            GameSceneCompositionLookupResult(True, make_composition(), None)
        with self.assertRaises(TypeError):
            GameSceneCompositionLookupResult(object(), True, make_composition(), None)
        with self.assertRaises(TypeError):
            class Sub(GameSceneCompositionLookupResult):
                pass

    def test_23_lookup_result_equality_hash_to_dict_copy_pickle(self):
        registry = make_registry(make_composition("s1"))
        a, b = registry.lookup("s1"), make_registry(make_composition("s1")).lookup("s1")
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, registry.lookup("x"))
        self.assertNotEqual(a, make_registry(make_composition("s1", ("z",))).lookup("s1"))
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, None)
        d1, d2 = a.to_dict(), a.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertIsNot(d1["composition"], d2["composition"])
        self.assertIsNot(d1["composition"]["character_ids"], d2["composition"]["character_ids"])
        d1["composition"]["character_ids"].append("junk")
        d1["found"] = False
        self.assertEqual(a.to_dict(), d2)
        self.assertEqual(a.composition.character_ids, ("c1",))
        self.assertIs(copy.copy(a), a)
        self.assertIs(copy.deepcopy(a), a)
        with self.assertRaises(TypeError):
            pickle.dumps(a)


class TestRegistryObject(unittest.TestCase):
    def test_24_immutable_tuple_properties(self):
        registry = make_registry(make_composition("s1"), make_composition("s2"))
        self.assertIs(type(registry.compositions), tuple)
        self.assertIs(type(registry.scene_ids), tuple)
        self.assertIs(registry.compositions, registry.compositions)
        with self.assertRaises(AttributeError):
            registry.compositions = ()
        with self.assertRaises(AttributeError):
            registry.scene_ids = ()
        with self.assertRaises(AttributeError):
            registry.compositions.append(make_composition("s3"))
        with self.assertRaises(TypeError):
            registry.compositions[0] = make_composition("s3")
        with self.assertRaises(TypeError):
            registry.scene_ids[0] = "x"

    def test_25_registry_is_read_only(self):
        registry = make_registry(make_composition("s1"))
        for name in ("compositions", "scene_ids", "_compositions", "lookup", "extra"):
            with self.assertRaises(AttributeError):
                setattr(registry, name, ())
            with self.assertRaises(AttributeError):
                delattr(registry, name)
        self.assertFalse(hasattr(registry, "__dict__"))
        self.assertEqual(registry.scene_ids, ("s1",))

    def test_26_direct_construction_is_refused(self):
        c = make_composition()
        for args in ((), (None,), (object(), [c]), (None, [c]), ([c],)):
            with self.assertRaises(TypeError):
                GameSceneCompositionRegistry(*args)
        with self.assertRaises(TypeError):
            GameSceneCompositionRegistryResult(None, [])
        with self.assertRaises(TypeError):
            GameSceneCompositionRegistryResult(object(), None, [])
        with self.assertRaises(TypeError):
            GameSceneCompositionRegistryResult()

    def test_27_subclassing_is_refused(self):
        for cls in (GameSceneCompositionRegistry, GameSceneCompositionRegistryResult, GameSceneCompositionLookupResult):
            with self.assertRaises(TypeError):
                type("Sub", (cls,), {})

    def test_28_deterministic_equality_and_hash(self):
        a = make_registry(make_composition("s1"), make_composition("s2"))
        b = make_registry(make_composition("s1"), make_composition("s2"))
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertEqual({a: 1}[b], 1)
        self.assertNotEqual(a, make_registry(make_composition("s2"), make_composition("s1")))      # order matters
        self.assertNotEqual(a, make_registry(make_composition("s1")))
        self.assertNotEqual(a, make_registry(make_composition("s1"), make_composition("s2", ("other",))))
        self.assertNotEqual(a, make_registry())
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, a.compositions)
        self.assertNotEqual(a, None)
        self.assertEqual(make_registry(), make_registry())
        self.assertEqual(hash(make_registry()), hash(make_registry()))

    def test_29_result_equality_and_hash(self):
        comps = [make_composition("s1"), make_composition("s2")]
        r1, r2 = create_game_scene_composition_registry(comps), create_game_scene_composition_registry(tuple(comps))
        self.assertIsNot(r1, r2)
        self.assertEqual(r1, r2)
        self.assertEqual(hash(r1), hash(r2))
        bad1, bad2 = create_game_scene_composition_registry(["x"]), create_game_scene_composition_registry(["y"])
        self.assertEqual(bad1, bad2)
        self.assertEqual(hash(bad1), hash(bad2))
        self.assertEqual(len({bad1, bad2}), 1)
        self.assertNotEqual(bad1, create_game_scene_composition_registry(None))
        self.assertNotEqual(bad1, create_game_scene_composition_registry([make_composition("a"), make_composition("a")]))
        self.assertNotEqual(r1, bad1)
        self.assertNotEqual(r1, r1.to_dict())
        self.assertNotEqual(r1, None)

    def test_30_registry_to_dict_is_fresh_plain_data(self):
        registry = make_registry(make_composition("s1"), make_composition("s2", ("c1", "c2")))
        d1, d2 = registry.to_dict(), registry.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertEqual(list(d1), ["compositions"])
        self.assertIs(type(d1["compositions"]), list)
        self.assertIsNot(d1["compositions"], d2["compositions"])
        self.assertIsNot(d1["compositions"][1], d2["compositions"][1])
        self.assertIsNot(d1["compositions"][1]["character_ids"], d2["compositions"][1]["character_ids"])
        d1["compositions"][1]["character_ids"].append("junk")
        d1["compositions"].pop()
        d1["extra"] = 1
        self.assertEqual(registry.to_dict(), d2)
        self.assertEqual(registry.compositions[1].character_ids, ("c1", "c2"))
        self.assertEqual(d2, {"compositions": [c.to_dict() for c in registry.compositions]})

    def test_31_to_dict_contains_plain_data_only_and_is_deterministic(self):
        def plain(value):
            if isinstance(value, dict):
                return all(type(k) is str and plain(v) for k, v in value.items())
            if isinstance(value, list):
                return all(plain(v) for v in value)
            return value is None or type(value) in (str, bool, int, float)

        registry = make_registry(make_composition("s1"), make_composition("s2"))
        results = [registry.to_dict(), create_game_scene_composition_registry(list(registry.compositions)).to_dict(),
                   create_game_scene_composition_registry(["x", "x"]).to_dict(), registry.lookup("s1").to_dict(), registry.lookup("q").to_dict()]
        for d in results:
            self.assertTrue(plain(d), d)
        self.assertEqual(results[0]["compositions"][0]["scene_id"], "s1")
        self.assertEqual(results[1], {"ok": True, "registry": registry.to_dict(), "failures": []})
        self.assertEqual(list(results[1]), ["ok", "registry", "failures"])
        self.assertEqual(list(results[3]), ["found", "composition", "code"])
        import json
        self.assertEqual(json.dumps(results[1], sort_keys=True), json.dumps(create_game_scene_composition_registry([
            make_composition("s1"), make_composition("s2")]).to_dict(), sort_keys=True))

    def test_32_result_to_dict_and_failures_are_fresh(self):
        result = create_game_scene_composition_registry([None, None])
        d1, d2 = result.to_dict(), result.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertIsNot(d1["failures"], d2["failures"])
        self.assertIsNot(d1["failures"][0], d2["failures"][0])
        d1["failures"][0]["code"] = "TAMPERED"
        d1["failures"].clear()
        self.assertEqual(result.codes(), [INVALID_COMPOSITION] * 2)
        f1, f2 = result.failures, result.failures
        self.assertEqual(f1, f2)
        self.assertIsNot(f1, f2)
        self.assertIsNot(f1[0], f2[0])
        f1[0]["message"] = "x"
        f1.append("x")
        self.assertEqual(len(result.failures), 2)
        self.assertNotEqual(result.failures[0]["message"], "x")
        c1, c2 = result.codes(), result.codes()
        self.assertIsNot(c1, c2)
        c1.append("x")
        self.assertEqual(result.codes(), [INVALID_COMPOSITION] * 2)
        self.assertEqual(result.to_dict(), {"ok": False, "registry": None, "failures": result.failures})

    def test_33_result_is_read_only(self):
        result = create_game_scene_composition_registry([make_composition("s1")])
        for name in ("ok", "registry", "failures", "_registry", "_failures", "extra"):
            with self.assertRaises(AttributeError):
                setattr(result, name, None)
            with self.assertRaises(AttributeError):
                delattr(result, name)
        self.assertFalse(hasattr(result, "__dict__"))
        self.assertTrue(result.ok)
        self.assertEqual(result.to_dict()["registry"], {"compositions": [make_composition("s1").to_dict()]})

    def test_34_copy_returns_same_object_and_pickle_is_refused(self):
        registry = make_registry(make_composition("s1"))
        result = create_game_scene_composition_registry([make_composition("s1")])
        for obj in (registry, result, create_game_scene_composition_registry(None), registry.lookup("s1"), registry.lookup("zz")):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)
            self.assertIs(copy.deepcopy([obj])[0], obj)
            for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(obj, protocol)
            with self.assertRaises(TypeError):
                obj.__reduce__()
            with self.assertRaises(TypeError):
                obj.__reduce_ex__(2)

    def test_35_repr_is_deterministic(self):
        registry = make_registry(make_composition("s1"), make_composition("s2"))
        self.assertEqual(repr(registry), repr(make_registry(make_composition("s1"), make_composition("s2"))))
        self.assertEqual(repr(registry), "GameSceneCompositionRegistry(scene_ids=('s1', 's2'))")


class TestNoMutationAndIsolation(unittest.TestCase):
    def test_36_supplied_compositions_and_collection_are_not_mutated(self):
        comps = [make_composition("s1", ("c1", "c2"), ("a1",), ("combat",)), make_composition("s2")]
        snapshot = [c.to_dict() for c in comps]
        hashes = [hash(c) for c in comps]
        sequence = list(comps)
        for collection in (comps, tuple(comps)):
            create_game_scene_composition_registry(collection)
        registry = make_registry(*comps)
        registry.lookup("s1")
        registry.to_dict()
        registry.scene_ids
        self.assertEqual([c.to_dict() for c in comps], snapshot)
        self.assertEqual([hash(c) for c in comps], hashes)
        self.assertEqual(comps, sequence)
        for original, stored in zip(comps, registry.compositions):
            self.assertIs(original, stored)      # stored as is: never copied, rebuilt or transformed

    def test_37_failed_creation_does_not_mutate_input(self):
        items = [make_composition("s1"), "bad", make_composition("s1")]
        before = list(items)
        create_game_scene_composition_registry(items)
        self.assertEqual(items, before)
        self.assertEqual(len(items), 3)
        for a, b in zip(items, before):
            self.assertIs(a, b)

    def test_38_later_edits_to_the_input_list_never_reach_the_registry(self):
        c1, c2 = make_composition("s1"), make_composition("s2")
        source = [c1, c2]
        registry = make_registry(*source)
        stored = create_game_scene_composition_registry(source).registry
        source.append(make_composition("s3"))
        source.reverse()
        source[0] = make_composition("s9")
        self.assertEqual(stored.scene_ids, ("s1", "s2"))
        self.assertEqual(registry.scene_ids, ("s1", "s2"))
        self.assertFalse(stored.lookup("s3").found)
        self.assertFalse(stored.lookup("s9").found)

    def test_39_ids_are_stored_untransformed(self):
        ids = ["Arena", " lead", "trail ", "Caf\u00e9", "x\ty", "UPPER"]
        registry = make_registry(*[make_composition(i) for i in ids])
        self.assertEqual(registry.scene_ids, tuple(ids))
        for i in ids:
            self.assertIs(registry.lookup(i).composition.scene_id, registry.lookup(i).composition.scene_id)
            self.assertEqual(registry.lookup(i).composition.scene_id, i)

    def test_40_registries_are_independent_objects(self):
        c = make_composition("s1")
        r1, r2 = make_registry(c), make_registry(c, make_composition("s2"))
        self.assertEqual(r1.scene_ids, ("s1",))
        self.assertEqual(r2.scene_ids, ("s1", "s2"))
        self.assertEqual(make_registry(c), make_registry(c))


class TestNoCrossValidation(unittest.TestCase):
    def test_41_no_scene_project_or_other_registry_validation_happens(self):
        boom = AssertionError("registry must not validate against another module")
        patches = [
            mock.patch.object(validator_module, "validate_game_scene_composition", side_effect=boom),
            mock.patch.object(project_validator_module, "validate_game_project", side_effect=boom, create=True),
            mock.patch.object(character_registry_module.GameCharacterRegistry, "lookup", side_effect=boom),
            mock.patch.object(asset_registry_module.GameAssetRegistry, "lookup", side_effect=boom),
            mock.patch.object(system_registry_module.GameplaySystemRegistry, "lookup", side_effect=boom),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        registry = make_registry(make_composition("any-id", ("x",), ("y",), ("z",)), make_composition("other-id", ("x",), (), ()))
        self.assertEqual(registry.scene_ids, ("any-id", "other-id"))
        self.assertTrue(registry.lookup("other-id").found)
        self.assertEqual(registry.to_dict()["compositions"][0]["gameplay_system_ids"], ["z"])
        self.assertFalse(create_game_scene_composition_registry([make_composition("a"), make_composition("a")]).ok)

    def test_42_compositions_with_ids_unknown_to_every_other_module_are_accepted(self):
        comps = [make_composition("unregistered-scene-%d" % i, ("missing-c",), ("missing-a",), ("missing-g",)) for i in range(5)]
        result = create_game_scene_composition_registry(comps)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.registry.compositions), 5)
        for c in comps:
            self.assertEqual(result.registry.lookup(c.scene_id).composition, c)

    def test_43_module_source_imports_only_the_composition_record_and_has_no_io_or_state(self):
        with open(SOURCE, encoding="utf-8") as fh:
            text = fh.read()
        tree = ast.parse(text)
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual([(n.module, tuple(a.name for a in n.names)) for n in imports],
                         [("game_scene_composition", ("GameSceneComposition",))])
        code_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("GameScene", "GameProject", "GameCharacterRegistry", "GameAssetRegistry", "GameplaySystemRegistry",
                          "GameProjectValidator", "GameSceneCompositionValidator", "validate_game_scene_composition", "validate_game_project",
                          "GameProjectStructure", "GameSceneRegistry"):
            self.assertNotIn(forbidden, code_names, forbidden)
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "sorted", "str.strip", "str.lower", "str.casefold"):
            self.assertNotIn(forbidden, calls)
        for method in ("strip", "lstrip", "rstrip", "lower", "upper", "casefold", "normalize", "title", "encode", "decode"):
            self.assertFalse([c for c in calls if c.endswith("." + method)], method)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(reg).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_44_lookup_source_compares_with_exact_equality_only(self):
        with open(SOURCE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        lookup = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "lookup"][0]
        compares = [n for n in ast.walk(lookup) if isinstance(n, ast.Compare)]
        self.assertTrue(any(isinstance(n.ops[0], ast.Eq) and ast.unparse(n.left) == "composition.scene_id" for n in compares))
        self.assertFalse([n for n in ast.walk(lookup) if isinstance(n, ast.Call) and ast.unparse(n.func) not in
                          ("type", "GameSceneCompositionLookupResult")])


class TestScopeAndDocumentation(unittest.TestCase):
    def test_45_earlier_modules_are_untouched_and_unaware_of_the_registry(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py",
            "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py",
            "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py",
            "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in ("game_project.py", "game_project_structure.py", "game_scene.py", "game_character.py", "game_asset.py",
                    "game_scene_registry.py", "game_character_registry.py", "gameplay_system_registry.py", "game_asset_registry.py",
                    "game_scene_composition.py", "game_project_validator.py", "game_scene_composition_validator.py"):
            with open(os.path.join(PY_ROOT, "game_creation", rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_scene_composition_registry", "create_game_scene_composition_registry", "GameSceneCompositionRegistry",
                          "GameSceneCompositionLookupResult"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "game_scene_composition_registry", "create_game_scene_composition_registry"):
                self.assertNotIn(token, text, (rel, token))

    def test_46_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_game_scene_composition_registry", "GameSceneCompositionRegistryResult", "GameSceneCompositionRegistry",
                       "GameSceneCompositionLookupResult", "GAME_SCENE_COMPOSITION_REGISTRY_", "INVALID_COLLECTION", "INVALID_COMPOSITION",
                       "DUPLICATE_SCENE_ID", "SCENE_NOT_FOUND", "exact", "does NOT", "Prompt 730", "Prompt 732"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
