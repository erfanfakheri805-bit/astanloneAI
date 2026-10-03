"""Prompt 735 - Section 7 game definition queries (`game_creation.game_definition_queries`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from game_creation import game_definition_queries as q
from game_creation.game_asset import create_game_asset
from game_creation.game_asset_registry import create_game_asset_registry
from game_creation.game_character import create_game_character
from game_creation.game_character_registry import create_game_character_registry
from game_creation.game_definition import GameDefinition, create_game_definition
from game_creation.game_definition_queries import (
    GameSceneBundleQueryResult, GameSceneQueryResult, lookup_game_scene, lookup_game_scene_bundle)
from game_creation.game_project import create_game_project
from game_creation.game_project_structure import create_game_project_structure
from game_creation.game_scene import GameScene, create_game_scene
from game_creation.game_scene_bundle import create_game_scene_bundle
from game_creation.game_scene_bundle_registry import GameSceneBundleRegistry, create_game_scene_bundle_registry
from game_creation.game_scene_composition import create_game_scene_composition
from game_creation.game_scene_composition_registry import create_game_scene_composition_registry
from game_creation.game_scene_registry import GameSceneRegistry, create_game_scene_registry
from game_creation.gameplay_system_registry import create_gameplay_system_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_definition_queries_prompt735.md")
SOURCE = os.path.join(PY_ROOT, "game_creation", "game_definition_queries.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

INVALID_DEFINITION = "GAME_DEFINITION_QUERY_INVALID_GAME_DEFINITION"
INVALID_SCENE_ID = "GAME_DEFINITION_QUERY_INVALID_SCENE_ID"
SCENE_NOT_FOUND = "GAME_DEFINITION_QUERY_SCENE_NOT_FOUND"
BUNDLE_NOT_FOUND = "GAME_DEFINITION_QUERY_BUNDLE_NOT_FOUND"


def ok_of(result):
    assert result.ok, result.failures
    return result


def make_scene(scene_id):
    return ok_of(create_game_scene({"scene_id": scene_id, "name": scene_id, "description": "", "scene_type": "level"})).scene


def make_composition(scene_id):
    return ok_of(create_game_scene_composition({"scene_id": scene_id, "character_ids": ["c1"], "asset_ids": ["a1"],
                                                "gameplay_system_ids": ["combat"]})).composition


def make_definition(scene_ids=("s1", "s2", "Arena", "arena", "arena "), bundled=("s1", "Arena")):
    scenes = [make_scene(i) for i in scene_ids]
    compositions = [make_composition(i) for i in scene_ids]
    by_id = dict(zip(scene_ids, zip(scenes, compositions)))
    bundles = [ok_of(create_game_scene_bundle(*by_id[i])).bundle for i in bundled]
    args = dict(
        project=ok_of(create_game_project({"project_id": "p1", "name": "P", "description": "", "genre": "", "target_platform": "", "version": "1"})).project,
        structure=ok_of(create_game_project_structure({"scenes": list(scene_ids), "characters": ["c1"], "gameplay_systems": ["combat"],
                                                       "assets": ["a1"]})).structure,
        scene_registry=ok_of(create_game_scene_registry(scenes)).registry,
        character_registry=ok_of(create_game_character_registry([ok_of(create_game_character(
            {"character_id": "c1", "name": "c1", "description": "", "role": "npc"})).character])).registry,
        gameplay_system_registry=ok_of(create_gameplay_system_registry(["combat"])).registry,
        asset_registry=ok_of(create_game_asset_registry([ok_of(create_game_asset(
            {"asset_id": "a1", "name": "a1", "description": "", "asset_type": "image"})).asset])).registry,
        composition_registry=ok_of(create_game_scene_composition_registry(compositions)).registry,
        bundle_registry=ok_of(create_game_scene_bundle_registry(bundles)).registry)
    return ok_of(create_game_definition(**args)).definition


class StrSubclass(str):
    pass


class FakeDefinition:
    scene_registry = bundle_registry = None


class TestSceneLookup(unittest.TestCase):
    def test_01_valid_scene_lookup(self):
        d = make_definition()
        r = lookup_game_scene(d, "s2")
        self.assertIsInstance(r, GameSceneQueryResult)
        self.assertTrue(r.found)
        self.assertIsInstance(r.scene, GameScene)
        self.assertEqual(r.scene.scene_id, "s2")
        self.assertIsNone(r.code)
        self.assertEqual(r.to_dict(), {"found": True, "scene": r.scene.to_dict(), "code": None})

    def test_02_missing_scene(self):
        r = lookup_game_scene(make_definition(), "nope")
        self.assertFalse(r.found)
        self.assertIsNone(r.scene)
        self.assertEqual(r.code, SCENE_NOT_FOUND)
        self.assertEqual(r.to_dict(), {"found": False, "scene": None, "code": SCENE_NOT_FOUND})

    def test_03_scene_without_bundle_is_still_a_scene(self):
        d = make_definition()
        self.assertTrue(lookup_game_scene(d, "s2").found)
        self.assertFalse(lookup_game_scene_bundle(d, "s2").found)

    def test_04_empty_scene_registry(self):
        d = make_definition((), ())
        self.assertEqual(lookup_game_scene(d, "s1").code, SCENE_NOT_FOUND)
        self.assertEqual(lookup_game_scene_bundle(d, "s1").code, BUNDLE_NOT_FOUND)


class TestBundleLookup(unittest.TestCase):
    def test_05_valid_bundle_lookup(self):
        d = make_definition()
        r = lookup_game_scene_bundle(d, "s1")
        self.assertIsInstance(r, GameSceneBundleQueryResult)
        self.assertTrue(r.found)
        self.assertEqual(r.bundle.scene_id, "s1")
        self.assertIsNone(r.code)
        self.assertEqual(r.to_dict(), {"found": True, "bundle": r.bundle.to_dict(), "code": None})

    def test_06_missing_bundle(self):
        r = lookup_game_scene_bundle(make_definition(), "nope")
        self.assertFalse(r.found)
        self.assertIsNone(r.bundle)
        self.assertEqual(r.code, BUNDLE_NOT_FOUND)
        self.assertEqual(r.to_dict(), {"found": False, "bundle": None, "code": BUNDLE_NOT_FOUND})


class TestInvalidArguments(unittest.TestCase):
    def test_07_invalid_game_definition(self):
        d = make_definition()
        for bad in (None, "d", 5, {}, [], object(), FakeDefinition(), d.scene_registry, d.to_dict(), GameDefinition):
            for fn, field in ((lookup_game_scene, "scene"), (lookup_game_scene_bundle, "bundle")):
                r = fn(bad, "s1")
                self.assertFalse(r.found)
                self.assertIsNone(getattr(r, field))
                self.assertEqual(r.code, INVALID_DEFINITION)

    def test_08_invalid_scene_id_including_str_subclass(self):
        d = make_definition()
        for bad in (None, 1, 1.5, True, b"s1", ["s1"], ("s1",), {"s1"}, {}, object(), StrSubclass("s1"), d):
            for fn, field in ((lookup_game_scene, "scene"), (lookup_game_scene_bundle, "bundle")):
                r = fn(d, bad)
                self.assertFalse(r.found, repr(bad))
                self.assertIsNone(getattr(r, field))
                self.assertEqual(r.code, INVALID_SCENE_ID)

    def test_09_definition_is_checked_before_scene_id(self):
        self.assertEqual(lookup_game_scene(None, None).code, INVALID_DEFINITION)
        self.assertEqual(lookup_game_scene_bundle(None, None).code, INVALID_DEFINITION)

    def test_10_invalid_input_never_raises(self):
        d = make_definition()
        weird = [None, 0, "", (), [], {}, set(), object(), Ellipsis, GameDefinition, make_definition, float("nan"), FakeDefinition(), d]
        for a in weird:
            for b in weird + ["s1"]:
                for fn in (lookup_game_scene, lookup_game_scene_bundle):
                    try:
                        fn(a, b)
                    except Exception as exc:      # pragma: no cover
                        self.fail("raised %r" % (exc,))
        with self.assertRaises(TypeError):      # wrong argument COUNT is a Python call error, not bad data
            lookup_game_scene(d)

    def test_11_empty_string_is_a_valid_id_that_misses(self):
        d = make_definition()
        self.assertEqual(lookup_game_scene(d, "").code, SCENE_NOT_FOUND)
        self.assertEqual(lookup_game_scene_bundle(d, "").code, BUNDLE_NOT_FOUND)


class TestExactMatching(unittest.TestCase):
    def test_12_case_sensitive(self):
        d = make_definition(("Arena", "arena"), ("Arena",))
        self.assertEqual(lookup_game_scene(d, "Arena").scene.scene_id, "Arena")
        self.assertEqual(lookup_game_scene(d, "arena").scene.scene_id, "arena")
        self.assertFalse(lookup_game_scene(d, "ARENA").found)
        self.assertTrue(lookup_game_scene_bundle(d, "Arena").found)
        self.assertFalse(lookup_game_scene_bundle(d, "arena").found)
        self.assertFalse(lookup_game_scene_bundle(d, "ARENA").found)

    def test_13_whitespace_sensitive(self):
        d = make_definition(("arena", "arena "), ("arena",))
        self.assertEqual(lookup_game_scene(d, "arena ").scene.scene_id, "arena ")
        for bad in (" arena", "arena\t", "arena\n", " arena ", "are na"):
            self.assertFalse(lookup_game_scene(d, bad).found, repr(bad))
            self.assertFalse(lookup_game_scene_bundle(d, bad).found, repr(bad))
        self.assertTrue(lookup_game_scene_bundle(d, "arena").found)
        self.assertFalse(lookup_game_scene_bundle(d, "arena ").found)


class TestIdentityAndImmutability(unittest.TestCase):
    def test_14_object_identity_is_preserved(self):
        d = make_definition()
        self.assertIs(lookup_game_scene(d, "s1").scene, d.scene_registry.lookup("s1").scene)
        self.assertIs(lookup_game_scene(d, "s1").scene, d.scene_registry.scenes[0])
        self.assertIs(lookup_game_scene_bundle(d, "s1").bundle, d.bundle_registry.lookup("s1").bundle)
        self.assertIs(lookup_game_scene_bundle(d, "s1").bundle, d.bundle_registry.bundles[0])
        self.assertIs(lookup_game_scene(d, "s1").scene, lookup_game_scene(d, "s1").scene)

    def test_15_exact_object_from_registry_lookup_is_returned(self):
        d = make_definition()
        sentinel_scene, sentinel_bundle = make_scene("elsewhere"), lookup_game_scene_bundle(d, "s1").bundle
        with mock.patch.object(GameSceneRegistry, "lookup", return_value=mock.Mock(found=True, scene=sentinel_scene)):
            self.assertIs(lookup_game_scene(d, "anything").scene, sentinel_scene)
        other = make_definition().bundle_registry.bundles[1]
        with mock.patch.object(GameSceneBundleRegistry, "lookup", return_value=mock.Mock(found=True, bundle=other)):
            self.assertIs(lookup_game_scene_bundle(d, "anything").bundle, other)
        self.assertIsNot(sentinel_bundle, other)

    def test_16_deterministic_equality_and_hash(self):
        a, b = make_definition(), make_definition()
        for fn in (lookup_game_scene, lookup_game_scene_bundle):
            r1, r2 = fn(a, "s1"), fn(b, "s1")
            self.assertIsNot(r1, r2)
            self.assertEqual(r1, r2)
            self.assertEqual(hash(r1), hash(r2))
            self.assertEqual(len({r1, r2}), 1)
            self.assertNotEqual(r1, fn(a, "Arena"))
            self.assertNotEqual(r1, fn(a, "nope"))
            self.assertEqual(fn(a, "nope"), fn(b, "zzz"))
            self.assertEqual(hash(fn(a, "nope")), hash(fn(b, "zzz")))
            self.assertEqual(fn(a, None), fn(b, 5))
            self.assertNotEqual(fn(a, None), fn(a, "nope"))
            self.assertNotEqual(fn(None, "s1"), fn(a, None))
            self.assertNotEqual(r1, r1.to_dict())
        self.assertNotEqual(lookup_game_scene(a, "nope"), lookup_game_scene_bundle(a, "nope"))

    def test_17_fresh_to_dict(self):
        d = make_definition()
        for fn, field in ((lookup_game_scene, "scene"), (lookup_game_scene_bundle, "bundle")):
            r = fn(d, "s1")
            d1, d2 = r.to_dict(), r.to_dict()
            self.assertEqual(d1, d2)
            self.assertIsNot(d1, d2)
            self.assertIsNot(d1[field], d2[field])
            snapshot = r.to_dict()
            d1[field]["scene_id" if field == "bundle" else "name"] = "mutated"
            if field == "bundle":
                d1[field]["composition"]["asset_ids"].append("junk")
            d1["found"] = False
            self.assertEqual(r.to_dict(), snapshot)
            self.assertEqual(fn(d, "s1").to_dict(), snapshot)
            miss = fn(d, "nope")
            self.assertIsNot(miss.to_dict(), miss.to_dict())

    def test_18_attributes_are_read_only(self):
        d = make_definition()
        for r, names in ((lookup_game_scene(d, "s1"), ("found", "scene", "code", "_found", "_scene", "_code", "extra")),
                         (lookup_game_scene_bundle(d, "s1"), ("found", "bundle", "code", "_found", "_bundle", "_code", "extra"))):
            for name in names:
                with self.assertRaises(AttributeError, msg=(type(r).__name__, name)):
                    setattr(r, name, 1)
                with self.assertRaises(AttributeError, msg=(type(r).__name__, name)):
                    delattr(r, name)
            self.assertFalse(hasattr(r, "__dict__"))
        self.assertTrue(lookup_game_scene(d, "s1").found)

    def test_19_direct_construction_is_refused(self):
        s = make_scene("s1")
        for token in (object(), None, True):
            with self.assertRaises(TypeError):
                GameSceneQueryResult(token, True, s, None)
            with self.assertRaises(TypeError):
                GameSceneBundleQueryResult(token, False, None, "x")
        with self.assertRaises(TypeError):
            GameSceneQueryResult(True, s, None)
        with self.assertRaises(TypeError):
            GameSceneBundleQueryResult()

    def test_20_subclassing_is_refused(self):
        for base in (GameSceneQueryResult, GameSceneBundleQueryResult):
            with self.assertRaises(TypeError):
                type("Sub", (base,), {})

    def test_21_copy_and_deepcopy_return_the_same_object(self):
        d = make_definition()
        for r in (lookup_game_scene(d, "s1"), lookup_game_scene(d, "nope"), lookup_game_scene_bundle(d, "s1"), lookup_game_scene_bundle(d, None)):
            self.assertIs(copy.copy(r), r)
            self.assertIs(copy.deepcopy(r), r)

    def test_22_pickle_is_refused(self):
        d = make_definition()
        for r in (lookup_game_scene(d, "s1"), lookup_game_scene(d, "nope"), lookup_game_scene_bundle(d, "s1"), lookup_game_scene_bundle(d, None)):
            for protocol in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(r, protocol)

    def test_23_repr_is_deterministic(self):
        d = make_definition()
        self.assertEqual(repr(lookup_game_scene(d, "nope")), "GameSceneQueryResult(found=False, code='%s')" % SCENE_NOT_FOUND)
        self.assertEqual(repr(lookup_game_scene_bundle(d, "nope")), "GameSceneBundleQueryResult(found=False, code='%s')" % BUNDLE_NOT_FOUND)
        self.assertEqual(repr(lookup_game_scene(d, "s1")), repr(lookup_game_scene(make_definition(), "s1")))


class TestRegistryDelegation(unittest.TestCase):
    def test_24_registry_lookup_is_actually_used(self):
        d = make_definition()
        with mock.patch.object(GameSceneRegistry, "lookup", autospec=True, side_effect=GameSceneRegistry.lookup) as sl, \
             mock.patch.object(GameSceneBundleRegistry, "lookup", autospec=True, side_effect=GameSceneBundleRegistry.lookup) as bl:
            lookup_game_scene(d, "s1")
            sl.assert_called_once_with(d.scene_registry, "s1")
            bl.assert_not_called()
            lookup_game_scene_bundle(d, "s2")
            bl.assert_called_once_with(d.bundle_registry, "s2")
            sl.assert_called_once()

    def test_25_a_not_found_from_the_registry_is_what_decides(self):
        d = make_definition()
        with mock.patch.object(GameSceneRegistry, "lookup", return_value=mock.Mock(found=False, scene=None)):
            r = lookup_game_scene(d, "s1")
        self.assertEqual((r.found, r.scene, r.code), (False, None, SCENE_NOT_FOUND))
        with mock.patch.object(GameSceneBundleRegistry, "lookup", return_value=mock.Mock(found=False, bundle=None)):
            r = lookup_game_scene_bundle(d, "s1")
        self.assertEqual((r.found, r.bundle, r.code), (False, None, BUNDLE_NOT_FOUND))

    def test_26_registry_not_consulted_for_invalid_arguments(self):
        d = make_definition()
        with mock.patch.object(GameSceneRegistry, "lookup", side_effect=AssertionError("called")), \
             mock.patch.object(GameSceneBundleRegistry, "lookup", side_effect=AssertionError("called")):
            for bad in (None, 5, StrSubclass("s1"), b"s1"):
                self.assertEqual(lookup_game_scene(d, bad).code, INVALID_SCENE_ID)
                self.assertEqual(lookup_game_scene_bundle(d, bad).code, INVALID_SCENE_ID)
            self.assertEqual(lookup_game_scene(FakeDefinition(), "s1").code, INVALID_DEFINITION)

    def test_27_registry_internals_are_not_touched(self):
        d = make_definition()

        real_scene_lookup = GameSceneRegistry.lookup
        real_bundle_lookup = GameSceneBundleRegistry.lookup
        touched = []
        with mock.patch.object(GameSceneRegistry, "scenes", new=property(lambda s: touched.append("scenes"))), \
             mock.patch.object(GameSceneRegistry, "scene_ids", new=property(lambda s: touched.append("scene_ids"))), \
             mock.patch.object(GameSceneBundleRegistry, "bundles", new=property(lambda s: touched.append("bundles"))), \
             mock.patch.object(GameSceneBundleRegistry, "scene_ids", new=property(lambda s: touched.append("scene_ids"))), \
             mock.patch.object(GameSceneRegistry, "to_dict", side_effect=lambda: touched.append("to_dict")), \
             mock.patch.object(GameSceneBundleRegistry, "to_dict", side_effect=lambda: touched.append("to_dict")), \
             mock.patch.object(GameSceneRegistry, "lookup", real_scene_lookup), mock.patch.object(GameSceneBundleRegistry, "lookup", real_bundle_lookup):
            r1 = lookup_game_scene(d, "s1")
            r2 = lookup_game_scene_bundle(d, "s1")
            lookup_game_scene(d, "nope")
            lookup_game_scene_bundle(d, "nope")
        self.assertEqual(touched, [])
        self.assertTrue(r1.found and r2.found)

    def test_28_other_definition_members_are_not_touched(self):
        d = make_definition()
        patches = [mock.patch.object(type(getattr(d, n)), "lookup", side_effect=AssertionError(n))
                   for n in ("composition_registry", "character_registry", "asset_registry", "gameplay_system_registry")]
        for p in patches:
            p.start()
        try:
            self.assertTrue(lookup_game_scene(d, "s1").found)
            self.assertTrue(lookup_game_scene_bundle(d, "s1").found)
        finally:
            for p in patches:
                p.stop()

    def test_29_supplied_definition_and_registries_are_not_mutated(self):
        d = make_definition()
        names = ("project", "structure", "scene_registry", "character_registry", "gameplay_system_registry", "asset_registry",
                 "composition_registry", "bundle_registry")
        before, hashes, whole = {n: getattr(d, n).to_dict() for n in names}, {n: hash(getattr(d, n)) for n in names}, d.to_dict()
        for sid in ("s1", "s2", "Arena", "nope", "", "arena "):
            lookup_game_scene(d, sid)
            lookup_game_scene_bundle(d, sid)
        lookup_game_scene(d, None)
        lookup_game_scene_bundle(None, "s1")
        self.assertEqual({n: getattr(d, n).to_dict() for n in names}, before)
        self.assertEqual({n: hash(getattr(d, n)) for n in names}, hashes)
        self.assertEqual(d.to_dict(), whole)
        self.assertEqual(d, make_definition())


class TestSourceBoundaries(unittest.TestCase):
    def tree(self):
        with open(SOURCE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_30_module_imports_only_game_definition(self):
        imports = [n for n in ast.walk(self.tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual([(n.module, tuple(a.name for a in n.names)) for n in imports], [("game_definition", ("GameDefinition",))])

    def test_31_forbidden_names_are_not_used(self):
        tree = self.tree()
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("GameProjectValidator", "GameSceneCompositionValidator", "GameSceneCompositionRegistry", "GameSceneBundleRegistry",
                          "GameSceneRegistry", "validate_game_project", "validate_game_scene_composition", "create_game_definition",
                          "composition_registry", "character_registry", "asset_registry", "gameplay_system_registry", "project", "structure",
                          "create_game_scene_bundle", "create_game_scene_registry", "Core", "Planner", "AgentLoop", "process_input"):
            self.assertNotIn(forbidden, names, forbidden)

    def test_32_only_public_lookup_surface_is_read(self):
        tree = self.tree()
        reads = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, (ast.Name, ast.Attribute))
                 and not (isinstance(n.value, ast.Name) and n.value.id in ("self", "other", "object"))}
        self.assertEqual(sorted(a for a in reads if not a.startswith("_")), ["bundle", "bundle_registry", "found", "lookup", "scene", "scene_registry", "to_dict"])
        lookups = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "lookup"]
        self.assertEqual(sorted(lookups), ["game_definition.bundle_registry.lookup", "game_definition.scene_registry.lookup"])

    def test_33_no_private_access_on_foreign_objects(self):
        for n in ast.walk(self.tree()):
            if isinstance(n, ast.Attribute) and n.attr.startswith("_") and not n.attr.startswith("__"):
                self.assertIsInstance(n.value, ast.Name)
                self.assertIn(n.value.id, ("self", "other"), ast.unparse(n))

    def test_34_no_scanning_or_duplicated_lookup_logic(self):
        tree = self.tree()
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        self.assertEqual([f.name for f in functions], ["lookup_game_scene", "lookup_game_scene_bundle"])
        for f in functions:
            nodes = list(ast.walk(f))
            self.assertFalse([n for n in nodes if isinstance(n, (ast.For, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.AsyncFor))])
            for c in [n for n in nodes if isinstance(n, ast.Compare)]:
                self.assertTrue(all(isinstance(op, (ast.Is, ast.IsNot)) for op in c.ops), ast.unparse(c))
            calls = {ast.unparse(n.func) for n in nodes if isinstance(n, ast.Call)}
            self.assertTrue(calls <= {"type", "GameSceneQueryResult", "GameSceneBundleQueryResult", "game_definition.scene_registry.lookup",
                                      "game_definition.bundle_registry.lookup"}, calls)

    def test_35_no_io_normalization_or_module_state(self):
        tree = self.tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "sorted", "str", "copy.copy", "copy.deepcopy"):
            self.assertNotIn(forbidden, calls)
        for method in ("strip", "lstrip", "rstrip", "lower", "upper", "casefold", "normalize", "title", "encode", "decode", "replace", "format"):
            self.assertFalse([c for c in calls if c.endswith("." + method)], method)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(q).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_36_stable_codes(self):
        self.assertEqual(q.FAILURE_CODES, (INVALID_DEFINITION, INVALID_SCENE_ID, SCENE_NOT_FOUND, BUNDLE_NOT_FOUND))
        self.assertEqual(len(set(q.FAILURE_CODES)), 4)
        self.assertTrue(all(c.startswith("GAME_DEFINITION_QUERY_") for c in q.FAILURE_CODES))


class TestScopeAndDocumentation(unittest.TestCase):
    def test_37_earlier_modules_are_untouched_and_unaware_of_the_queries(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py",
            "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py", "game_project_structure.py", "game_project_validator.py", "game_scene.py",
            "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py", "game_scene_composition_registry.py",
            "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))):
            if rel in ("game_definition_queries.py", "game_definition_query_helpers.py", "__init__.py"):      # Prompt 736 consumer of the queries
                continue
            with open(os.path.join(PY_ROOT, "game_creation", rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_definition_queries", "lookup_game_scene", "GameSceneQueryResult", "GameSceneBundleQueryResult"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "game_definition_queries", "lookup_game_scene"):
                self.assertNotIn(token, text, (rel, token))

    def test_38_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("lookup_game_scene", "lookup_game_scene_bundle", "GameSceneQueryResult", "GameSceneBundleQueryResult", "GAME_DEFINITION_QUERY_",
                       "INVALID_GAME_DEFINITION", "INVALID_SCENE_ID", "SCENE_NOT_FOUND", "BUNDLE_NOT_FOUND", "exact", "does NOT", "Prompt 734",
                       "Prompt 736"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
