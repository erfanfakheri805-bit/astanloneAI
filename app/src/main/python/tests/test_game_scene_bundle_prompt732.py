"""Prompt 732 - Section 7 game scene bundle (`game_creation.game_scene_bundle`)."""
import ast
import copy
import hashlib
import json
import os
import pickle
import unittest
from unittest import mock

from game_creation import game_asset_registry as asset_registry_module
from game_creation import game_character_registry as character_registry_module
from game_creation import game_scene_bundle as bun
from game_creation import game_scene_composition_registry as composition_registry_module
from game_creation import game_scene_composition_validator as validator_module
from game_creation import game_scene_registry as scene_registry_module
from game_creation import gameplay_system_registry as system_registry_module
from game_creation.game_scene import GameScene, create_game_scene
from game_creation.game_scene_bundle import GameSceneBundle, GameSceneBundleResult, create_game_scene_bundle
from game_creation.game_scene_composition import GameSceneComposition, create_game_scene_composition

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_scene_bundle_prompt732.md")
SOURCE = os.path.join(PY_ROOT, "game_creation", "game_scene_bundle.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

INVALID_SCENE = "GAME_SCENE_BUNDLE_INVALID_SCENE"
INVALID_COMPOSITION = "GAME_SCENE_BUNDLE_INVALID_COMPOSITION"
SCENE_ID_MISMATCH = "GAME_SCENE_BUNDLE_SCENE_ID_MISMATCH"


def make_scene(scene_id="s1", name="Scene", description="", scene_type="level"):
    result = create_game_scene({"scene_id": scene_id, "name": name, "description": description, "scene_type": scene_type})
    assert result.ok, result.failures
    return result.scene


def make_composition(scene_id="s1", characters=("c1",), assets=("a1", "a2"), systems=("combat",)):
    result = create_game_scene_composition({"scene_id": scene_id, "character_ids": list(characters), "asset_ids": list(assets),
                                            "gameplay_system_ids": list(systems)})
    assert result.ok, result.failures
    return result.composition


def make_bundle(scene=None, composition=None):
    result = create_game_scene_bundle(scene if scene is not None else make_scene(), composition if composition is not None else make_composition())
    assert result.ok, result.failures
    return result.bundle


class SceneLookalike:
    scene_id = "s1"
    name = "Scene"
    description = ""
    scene_type = "level"

    def to_dict(self):
        return {}


class CompositionLookalike:
    scene_id = "s1"
    character_ids = ()
    asset_ids = ()
    gameplay_system_ids = ()

    def to_dict(self):
        return {}


class TestValidBundle(unittest.TestCase):
    def test_01_valid_scene_and_matching_composition(self):
        scene, composition = make_scene("arena"), make_composition("arena")
        result = create_game_scene_bundle(scene, composition)
        self.assertIsInstance(result, GameSceneBundleResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.codes(), [])
        self.assertIsInstance(result.bundle, GameSceneBundle)
        self.assertEqual(result.bundle.scene_id, "arena")

    def test_02_object_identity_is_preserved(self):
        scene, composition = make_scene(), make_composition()
        bundle = create_game_scene_bundle(scene, composition).bundle
        self.assertIs(bundle.scene, scene)
        self.assertIs(bundle.composition, composition)
        self.assertIs(bundle.scene, bundle.scene)
        self.assertIs(bundle.composition, bundle.composition)
        self.assertIs(type(bundle.scene), GameScene)
        self.assertIs(type(bundle.composition), GameSceneComposition)

    def test_03_scene_id_is_derived_from_the_scene_and_is_a_read_only_str(self):
        scene, composition = make_scene("arena"), make_composition("arena")
        bundle = make_bundle(scene, composition)
        self.assertIs(type(bundle.scene_id), str)
        self.assertEqual(bundle.scene_id, scene.scene_id)
        self.assertIs(bundle.scene_id, scene.scene_id)
        self.assertEqual(bundle.scene_id, composition.scene_id)
        with self.assertRaises(AttributeError):
            bundle.scene_id = "other"
        with self.assertRaises(AttributeError):
            del bundle.scene_id

    def test_04_bundle_exposes_exactly_scene_composition_and_scene_id(self):
        bundle = make_bundle()
        public = sorted(n for n in dir(bundle) if not n.startswith("_"))
        self.assertEqual(public, ["composition", "scene", "scene_id", "to_dict"])
        self.assertEqual(GameSceneBundle.__slots__, ("_scene", "_composition"))
        self.assertFalse(hasattr(bundle, "__dict__"))

    def test_05_arbitrary_character_asset_and_system_ids_are_accepted_and_not_resolved(self):
        composition = make_composition("s1", ("ghost-character", "x"), ("ghost-asset",), ("ghost-system",))
        bundle = make_bundle(make_scene("s1"), composition)
        self.assertEqual(bundle.composition.character_ids, ("ghost-character", "x"))
        self.assertEqual(bundle.composition.asset_ids, ("ghost-asset",))
        self.assertEqual(bundle.composition.gameplay_system_ids, ("ghost-system",))
        empty = make_bundle(make_scene("s1"), make_composition("s1", (), (), ()))
        self.assertEqual(empty.composition.character_ids, ())

    def test_06_scene_fields_other_than_the_id_do_not_matter(self):
        a = make_bundle(make_scene("s1", "One", "d", "level"), make_composition("s1"))
        b = make_bundle(make_scene("s1", "Two", "", "level"), make_composition("s1"))
        self.assertEqual(a.scene_id, b.scene_id)
        self.assertNotEqual(a, b)


class TestInvalidInput(unittest.TestCase):
    def test_07_invalid_scene(self):
        composition = make_composition()
        for bad in (None, "s1", 5, {}, {"scene_id": "s1"}, [make_scene()], (make_scene(),), composition, SceneLookalike(), object(), GameScene,
                    make_scene().to_dict()):
            result = create_game_scene_bundle(bad, composition)
            self.assertFalse(result.ok, bad)
            self.assertIsNone(result.bundle)
            self.assertEqual(result.codes(), [INVALID_SCENE], bad)
            self.assertEqual(result.failures[0]["field"], "scene")

    def test_08_invalid_composition(self):
        scene = make_scene()
        for bad in (None, "s1", 5, {}, [make_composition()], (make_composition(),), scene, CompositionLookalike(), object(),
                    GameSceneComposition, make_composition().to_dict()):
            result = create_game_scene_bundle(scene, bad)
            self.assertFalse(result.ok, bad)
            self.assertIsNone(result.bundle)
            self.assertEqual(result.codes(), [INVALID_COMPOSITION], bad)
            self.assertEqual(result.failures[0]["field"], "composition")

    def test_09_scene_id_mismatch(self):
        result = create_game_scene_bundle(make_scene("s1"), make_composition("s2"))
        self.assertFalse(result.ok)
        self.assertIsNone(result.bundle)
        self.assertEqual(result.codes(), [SCENE_ID_MISMATCH])
        self.assertEqual(result.failures[0]["field"], "composition.scene_id")
        self.assertIn("'s2'", result.failures[0]["message"])
        self.assertIn("'s1'", result.failures[0]["message"])

    def test_10_matching_is_exact_and_case_sensitive(self):
        self.assertTrue(create_game_scene_bundle(make_scene("Arena"), make_composition("Arena")).ok)
        for a, b in (("Arena", "arena"), ("arena", "ARENA"), ("ARENA", "Arena")):
            result = create_game_scene_bundle(make_scene(a), make_composition(b))
            self.assertEqual(result.codes(), [SCENE_ID_MISMATCH], (a, b))
            self.assertIsNone(result.bundle)

    def test_11_matching_is_whitespace_sensitive(self):
        for a, b in (("arena", "arena "), ("arena", " arena"), ("arena ", "arena"), ("are na", "arena"), ("arena", "arena\n"),
                     ("arena", "\tarena"), ("a  b", "a b")):
            result = create_game_scene_bundle(make_scene(a), make_composition(b))
            self.assertEqual(result.codes(), [SCENE_ID_MISMATCH], (a, b))
        for same in ("arena ", " arena", "a b", "x\ty"):
            self.assertTrue(create_game_scene_bundle(make_scene(same), make_composition(same)).ok, same)

    def test_12_no_normalization_or_coercion(self):
        result = create_game_scene_bundle(make_scene("Caf\u00e9"), make_composition("Cafe\u0301"))      # composed vs decomposed
        self.assertEqual(result.codes(), [SCENE_ID_MISMATCH])
        self.assertTrue(create_game_scene_bundle(make_scene("Caf\u00e9"), make_composition("Caf\u00e9")).ok)
        self.assertEqual(create_game_scene_bundle(make_scene("1"), make_composition("01")).codes(), [SCENE_ID_MISMATCH])

    def test_13_failure_ordering(self):
        result = create_game_scene_bundle(None, None)
        self.assertEqual(result.codes(), [INVALID_SCENE, INVALID_COMPOSITION])
        self.assertEqual([f["field"] for f in result.failures], ["scene", "composition"])
        self.assertEqual(create_game_scene_bundle(object(), "x").codes(), [INVALID_SCENE, INVALID_COMPOSITION])
        self.assertEqual(create_game_scene_bundle(make_scene(), None).codes(), [INVALID_COMPOSITION])
        self.assertEqual(create_game_scene_bundle(None, make_composition()).codes(), [INVALID_SCENE])
        self.assertEqual(create_game_scene_bundle(make_scene("a"), make_composition("b")).codes(), [SCENE_ID_MISMATCH])

    def test_14_id_comparison_is_skipped_when_either_object_is_invalid(self):
        for scene, composition in ((SceneLookalike(), make_composition("other")), (make_scene("other"), CompositionLookalike()),
                                   (None, make_composition("other")), (make_scene("other"), None), (SceneLookalike(), CompositionLookalike())):
            codes = create_game_scene_bundle(scene, composition).codes()
            self.assertNotIn(SCENE_ID_MISMATCH, codes)
            self.assertTrue(codes)
        # look-alikes with a differing id: the comparison must not be reached, so no mismatch is invented
        self.assertEqual(create_game_scene_bundle(SceneLookalike(), make_composition("zzz")).codes(), [INVALID_SCENE])

    def test_15_invalid_inputs_never_raise(self):
        class Hostile:
            def __getattr__(self, name):
                raise RuntimeError("must not be read: " + name)

            def __eq__(self, other):
                raise RuntimeError("must not be compared")

            __hash__ = None

        for scene in (Hostile(), None, 1, "x", [], {}):
            for composition in (Hostile(), None, 1, "x", [], {}):
                result = create_game_scene_bundle(scene, composition)
                self.assertFalse(result.ok)
                self.assertEqual(result.codes(), [INVALID_SCENE, INVALID_COMPOSITION])
        self.assertEqual(create_game_scene_bundle(Hostile(), make_composition()).codes(), [INVALID_SCENE])
        self.assertEqual(create_game_scene_bundle(make_scene(), Hostile()).codes(), [INVALID_COMPOSITION])

    def test_16_wrong_argument_count_is_a_plain_type_error(self):
        with self.assertRaises(TypeError):
            create_game_scene_bundle()
        with self.assertRaises(TypeError):
            create_game_scene_bundle(make_scene())
        with self.assertRaises(TypeError):
            create_game_scene_bundle(make_scene(), make_composition(), None)

    def test_17_failures_are_deterministic(self):
        a = create_game_scene_bundle(None, make_composition("x"))
        b = create_game_scene_bundle(None, make_composition("x"))
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(a.failures, b.failures)
        m1 = create_game_scene_bundle(make_scene("a"), make_composition("b"))
        m2 = create_game_scene_bundle(make_scene("a"), make_composition("b"))
        self.assertEqual(m1, m2)
        self.assertNotEqual(m1, create_game_scene_bundle(make_scene("a"), make_composition("c")))      # message carries the ids

    def test_18_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(bun.FAILURE_CODES, (INVALID_SCENE, INVALID_COMPOSITION, SCENE_ID_MISMATCH))
        self.assertEqual(len(set(bun.FAILURE_CODES)), 3)
        self.assertTrue(all(c.startswith("GAME_SCENE_BUNDLE_") for c in bun.FAILURE_CODES))
        for result in (create_game_scene_bundle(None, None), create_game_scene_bundle(make_scene("a"), make_composition("b"))):
            for f in result.failures:
                self.assertIn(f["code"], bun.FAILURE_CODES)
                self.assertEqual(set(f), {"code", "field", "message"})


class TestBundleObject(unittest.TestCase):
    def test_19_bundle_is_read_only(self):
        bundle = make_bundle()
        for name in ("scene", "composition", "scene_id", "_scene", "_composition", "to_dict", "extra"):
            with self.assertRaises(AttributeError):
                setattr(bundle, name, None)
            with self.assertRaises(AttributeError):
                delattr(bundle, name)
        self.assertEqual(bundle.scene_id, "s1")

    def test_20_result_is_read_only(self):
        result = create_game_scene_bundle(make_scene(), make_composition())
        for name in ("ok", "bundle", "failures", "_bundle", "_failures", "extra"):
            with self.assertRaises(AttributeError):
                setattr(result, name, None)
            with self.assertRaises(AttributeError):
                delattr(result, name)
        self.assertFalse(hasattr(result, "__dict__"))
        self.assertTrue(result.ok)

    def test_21_direct_construction_is_refused(self):
        scene, composition = make_scene(), make_composition()
        for args in ((), (None,), (scene, composition), (object(), scene, composition), (None, scene, composition), (scene,)):
            with self.assertRaises(TypeError):
                GameSceneBundle(*args)
        for args in ((), (None, None), (None, None, []), (object(), None, []), (None, [])):
            with self.assertRaises(TypeError):
                GameSceneBundleResult(*args)

    def test_22_subclassing_is_refused(self):
        for cls in (GameSceneBundle, GameSceneBundleResult):
            with self.assertRaises(TypeError):
                type("Sub", (cls,), {})

            with self.assertRaises(TypeError):
                exec("class Sub(cls):\n    pass", {"cls": cls})

    def test_23_deterministic_equality_and_hash(self):
        a = make_bundle(make_scene("s1"), make_composition("s1"))
        b = make_bundle(make_scene("s1"), make_composition("s1"))
        self.assertIsNot(a, b)
        self.assertIsNot(a.scene, b.scene)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertEqual({a: 1}[b], 1)
        self.assertNotEqual(a, make_bundle(make_scene("s2"), make_composition("s2")))
        self.assertNotEqual(a, make_bundle(make_scene("s1", "Other"), make_composition("s1")))
        self.assertNotEqual(a, make_bundle(make_scene("s1"), make_composition("s1", ("z",))))
        self.assertNotEqual(a, make_bundle(make_scene("s1"), make_composition("s1", ("c1",), ("a2", "a1"))))      # order matters
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, (a.scene, a.composition))
        self.assertNotEqual(a, None)

    def test_24_result_equality_and_hash(self):
        r1 = create_game_scene_bundle(make_scene(), make_composition())
        r2 = create_game_scene_bundle(make_scene(), make_composition())
        self.assertIsNot(r1, r2)
        self.assertEqual(r1, r2)
        self.assertEqual(hash(r1), hash(r2))
        self.assertEqual(len({r1, r2}), 1)
        bad = create_game_scene_bundle(None, None)
        self.assertEqual(bad, create_game_scene_bundle("x", 3))
        self.assertEqual(hash(bad), hash(create_game_scene_bundle("x", 3)))
        self.assertNotEqual(r1, bad)
        self.assertNotEqual(bad, create_game_scene_bundle(None, make_composition()))
        self.assertNotEqual(r1, create_game_scene_bundle(make_scene("s2"), make_composition("s2")))
        self.assertNotEqual(r1, r1.to_dict())
        self.assertNotEqual(r1, None)

    def test_25_bundle_to_dict_is_fresh_plain_data(self):
        bundle = make_bundle(make_scene("s1", "Name", "Desc", "level"), make_composition("s1", ("c1", "c2")))
        d1, d2 = bundle.to_dict(), bundle.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertEqual(list(d1), ["scene_id", "scene", "composition"])
        self.assertEqual(d1["scene_id"], "s1")
        self.assertEqual(d1["scene"], bundle.scene.to_dict())
        self.assertEqual(d1["composition"], bundle.composition.to_dict())
        self.assertIs(type(d1["scene"]), dict)
        self.assertIs(type(d1["composition"]), dict)
        self.assertIs(type(d1["composition"]["character_ids"]), list)
        d1["scene_id"] = "tampered"
        d1["extra"] = 1
        self.assertEqual(bundle.to_dict(), d2)
        self.assertEqual(bundle.scene_id, "s1")

    def test_26_nested_to_dict_is_independent_of_the_bundle_and_of_every_other_call(self):
        scene, composition = make_scene("s1", "Name"), make_composition("s1", ("c1", "c2"), ("a1",), ("combat",))
        bundle = make_bundle(scene, composition)
        d1, d2 = bundle.to_dict(), bundle.to_dict()
        self.assertIsNot(d1["scene"], d2["scene"])
        self.assertIsNot(d1["composition"], d2["composition"])
        for field in ("character_ids", "asset_ids", "gameplay_system_ids"):
            self.assertIsNot(d1["composition"][field], d2["composition"][field])
        snap = (scene.to_dict(), composition.to_dict())
        d1["scene"]["name"] = "tampered"
        d1["scene"].clear()
        d1["composition"]["character_ids"].append("junk")
        d1["composition"]["asset_ids"].clear()
        d1["composition"]["gameplay_system_ids"][0] = "junk"
        d1["composition"].clear()
        self.assertEqual(bundle.to_dict(), d2)
        self.assertEqual((scene.to_dict(), composition.to_dict()), snap)
        self.assertEqual(bundle.scene.name, "Name")
        self.assertEqual(bundle.composition.character_ids, ("c1", "c2"))
        # the dicts do not alias the scene's or the composition's own to_dict() results either
        self.assertIsNot(bundle.to_dict()["scene"], scene.to_dict())
        self.assertIsNot(bundle.to_dict()["composition"]["character_ids"], composition.to_dict()["character_ids"])

    def test_27_to_dict_contains_plain_data_only_and_is_json_safe(self):
        def plain(value):
            if isinstance(value, dict):
                return all(type(k) is str and plain(v) for k, v in value.items())
            if isinstance(value, list):
                return all(plain(v) for v in value)
            return value is None or type(value) in (str, bool, int, float)

        ok = create_game_scene_bundle(make_scene(), make_composition())
        for d in (ok.bundle.to_dict(), ok.to_dict(), create_game_scene_bundle(None, None).to_dict(),
                  create_game_scene_bundle(make_scene("a"), make_composition("b")).to_dict()):
            self.assertTrue(plain(d), d)
            json.dumps(d)
        self.assertEqual(list(ok.to_dict()), ["ok", "bundle", "failures"])
        self.assertEqual(ok.to_dict(), {"ok": True, "bundle": ok.bundle.to_dict(), "failures": []})
        self.assertEqual(create_game_scene_bundle(None, None).to_dict()["bundle"], None)
        self.assertFalse(create_game_scene_bundle(None, None).to_dict()["ok"])

    def test_28_result_to_dict_failures_and_codes_are_fresh(self):
        result = create_game_scene_bundle(None, None)
        d1, d2 = result.to_dict(), result.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertIsNot(d1["failures"], d2["failures"])
        self.assertIsNot(d1["failures"][0], d2["failures"][0])
        d1["failures"][0]["code"] = "TAMPERED"
        d1["failures"].clear()
        self.assertEqual(result.codes(), [INVALID_SCENE, INVALID_COMPOSITION])
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
        self.assertEqual(result.codes(), [INVALID_SCENE, INVALID_COMPOSITION])
        self.assertEqual(result.to_dict(), {"ok": False, "bundle": None, "failures": result.failures})

    def test_29_result_bundle_to_dict_matches_the_bundle(self):
        result = create_game_scene_bundle(make_scene("s1"), make_composition("s1"))
        d = result.to_dict()
        self.assertEqual(d["bundle"], result.bundle.to_dict())
        d["bundle"]["composition"]["asset_ids"].append("junk")
        self.assertEqual(result.bundle.composition.asset_ids, ("a1", "a2"))
        self.assertEqual(result.to_dict()["bundle"]["composition"]["asset_ids"], ["a1", "a2"])

    def test_30_copy_returns_the_same_object_and_pickle_is_refused(self):
        bundle = make_bundle()
        ok = create_game_scene_bundle(make_scene(), make_composition())
        for obj in (bundle, ok, create_game_scene_bundle(None, None), create_game_scene_bundle(make_scene("a"), make_composition("b"))):
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
        self.assertIs(copy.copy(bundle).scene, bundle.scene)

    def test_31_repr_is_deterministic(self):
        self.assertEqual(repr(make_bundle()), "GameSceneBundle(scene_id='s1')")
        self.assertEqual(repr(make_bundle()), repr(make_bundle()))
        self.assertEqual(repr(create_game_scene_bundle(make_scene(), make_composition())), "GameSceneBundleResult(ok=True, failures=0)")
        self.assertEqual(repr(create_game_scene_bundle(None, None)), "GameSceneBundleResult(ok=False, failures=2)")


class TestNoMutationAndNoLookups(unittest.TestCase):
    def test_32_supplied_objects_are_not_mutated_on_success(self):
        scene, composition = make_scene("s1", "N", "D", "level"), make_composition("s1", ("c1", "c2"), ("a1",), ("combat",))
        before = (scene.to_dict(), composition.to_dict(), hash(scene), hash(composition), repr(scene), repr(composition))
        result = create_game_scene_bundle(scene, composition)
        result.bundle.to_dict()
        result.to_dict()
        result.bundle.scene_id
        hash(result.bundle)
        self.assertEqual((scene.to_dict(), composition.to_dict(), hash(scene), hash(composition), repr(scene), repr(composition)), before)
        self.assertIs(result.bundle.scene, scene)
        self.assertIs(result.bundle.composition, composition)

    def test_33_supplied_objects_are_not_mutated_on_failure(self):
        scene, composition = make_scene("s1"), make_composition("s2")
        before = (scene.to_dict(), composition.to_dict(), hash(scene), hash(composition))
        for _ in range(3):
            self.assertEqual(create_game_scene_bundle(scene, composition).codes(), [SCENE_ID_MISMATCH])
        create_game_scene_bundle(None, composition)
        create_game_scene_bundle(scene, None)
        self.assertEqual((scene.to_dict(), composition.to_dict(), hash(scene), hash(composition)), before)

    def test_34_no_copy_or_rebuild_of_supplied_objects(self):
        scene, composition = make_scene(), make_composition()
        with mock.patch("game_creation.game_scene.create_game_scene", side_effect=AssertionError("must not rebuild")), \
                mock.patch("game_creation.game_scene_composition.create_game_scene_composition", side_effect=AssertionError("must not rebuild")), \
                mock.patch.object(GameScene, "__copy__", side_effect=AssertionError("must not copy")), \
                mock.patch.object(GameScene, "__deepcopy__", side_effect=AssertionError("must not copy")), \
                mock.patch.object(GameSceneComposition, "__copy__", side_effect=AssertionError("must not copy")), \
                mock.patch.object(GameSceneComposition, "__deepcopy__", side_effect=AssertionError("must not copy")):
            bundle = create_game_scene_bundle(scene, composition).bundle
            self.assertIs(bundle.scene, scene)
            self.assertIs(bundle.composition, composition)

    def test_35_no_registry_lookup_or_validator_is_used(self):
        boom = AssertionError("bundle must not consult another module")
        patches = [
            mock.patch.object(character_registry_module.GameCharacterRegistry, "lookup", side_effect=boom),
            mock.patch.object(asset_registry_module.GameAssetRegistry, "lookup", side_effect=boom),
            mock.patch.object(system_registry_module.GameplaySystemRegistry, "lookup", side_effect=boom),
            mock.patch.object(scene_registry_module.GameSceneRegistry, "lookup", side_effect=boom),
            mock.patch.object(composition_registry_module.GameSceneCompositionRegistry, "lookup", side_effect=boom),
            mock.patch.object(validator_module, "validate_game_scene_composition", side_effect=boom),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        bundle = make_bundle(make_scene("s1"), make_composition("s1", ("nobody",), ("nothing",), ("nowhere",)))
        self.assertEqual(bundle.scene_id, "s1")
        self.assertEqual(bundle.to_dict()["composition"]["character_ids"], ["nobody"])
        self.assertFalse(create_game_scene_bundle(make_scene("a"), make_composition("b")).ok)
        self.assertFalse(create_game_scene_bundle(None, None).ok)

    def test_36_compositions_referencing_unknown_ids_are_accepted(self):
        for i in range(5):
            composition = make_composition("scene-%d" % i, ("unregistered-c-%d" % i,), ("unregistered-a-%d" % i,), ("unregistered-g-%d" % i,))
            result = create_game_scene_bundle(make_scene("scene-%d" % i), composition)
            self.assertTrue(result.ok)
            self.assertIs(result.bundle.composition, composition)


class TestSourceBoundaries(unittest.TestCase):
    def test_37_module_imports_only_game_scene_and_game_scene_composition(self):
        with open(SOURCE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual(sorted((n.module, tuple(a.name for a in n.names)) for n in imports),
                         [("game_scene", ("GameScene",)), ("game_scene_composition", ("GameSceneComposition",))])

    def test_38_module_does_not_use_registries_validators_project_or_runtime_names(self):
        with open(SOURCE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("GameSceneRegistry", "GameCharacterRegistry", "GameAssetRegistry", "GameplaySystemRegistry",
                          "GameSceneCompositionRegistry", "GameProject", "GameProjectStructure", "GameProjectValidator",
                          "GameSceneCompositionValidator", "validate_game_scene_composition", "validate_game_project", "lookup",
                          "create_game_scene", "create_game_scene_composition", "Core", "Planner", "AgentLoop", "process_input"):
            self.assertNotIn(forbidden, names, forbidden)
        with open(SOURCE, encoding="utf-8") as fh:
            code_only = "\n".join(ast.unparse(n) for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)))
        for token in ("registry.", "lookup(", "import core", "agent_loop", "planner", "execution"):
            self.assertNotIn(token, code_only.replace("GameSceneRegistry", ""), token)

    def test_39_module_has_no_io_normalization_or_module_state(self):
        with open(SOURCE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "sorted", "copy.copy", "copy.deepcopy", "str", "repr_"):
            self.assertNotIn(forbidden, calls)
        for method in ("strip", "lstrip", "rstrip", "lower", "upper", "casefold", "normalize", "title", "encode", "decode", "replace"):
            self.assertFalse([c for c in calls if c.endswith("." + method)], method)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(bun).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_40_scene_id_comparison_uses_exact_equality_only(self):
        with open(SOURCE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        factory = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_game_scene_bundle"][0]
        compares = [ast.unparse(n) for n in ast.walk(factory) if isinstance(n, ast.Compare)]
        self.assertIn("scene.scene_id != composition.scene_id", compares)
        self.assertFalse([c for c in compares if " is " not in c and "!=" not in c])


class TestScopeAndDocumentation(unittest.TestCase):
    def test_41_earlier_modules_are_untouched_and_unaware_of_the_bundle(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py",
            "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py",
            "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py",
            "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in ("game_project.py", "game_project_structure.py", "game_scene.py", "game_character.py", "game_asset.py",
                    "game_scene_registry.py", "game_character_registry.py", "gameplay_system_registry.py", "game_asset_registry.py",
                    "game_scene_composition.py", "game_project_validator.py", "game_scene_composition_validator.py",
                    "game_scene_composition_registry.py"):
            with open(os.path.join(PY_ROOT, "game_creation", rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_scene_bundle", "create_game_scene_bundle", "GameSceneBundle"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "game_scene_bundle", "create_game_scene_bundle"):
                self.assertNotIn(token, text, (rel, token))

    def test_42_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_game_scene_bundle", "GameSceneBundleResult", "GameSceneBundle", "GAME_SCENE_BUNDLE_", "INVALID_SCENE",
                       "INVALID_COMPOSITION", "SCENE_ID_MISMATCH", "exact", "does NOT", "Prompt 730", "Prompt 731", "Prompt 733"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
