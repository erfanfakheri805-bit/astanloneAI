"""Prompt 727 - Section 7 game asset registry (`game_creation.game_asset_registry`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from game_creation import game_asset_registry as reg
from game_creation.game_asset import GameAsset, create_game_asset
from game_creation.game_asset_registry import GameAssetRegistry, create_game_asset_registry
from game_creation.game_project_structure import create_game_project_structure

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_asset_prompt727.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def ast_(cid, name=None, asset_type="image", description=""):
    r = create_game_asset({"asset_id": cid, "name": name or cid.title(), "description": description, "asset_type": asset_type})
    assert r.ok
    return r.asset


def structure(assets=(), **over):
    data = {"scenes": [], "characters": [], "gameplay_systems": [], "assets": list(assets)}
    data.update(over)
    r = create_game_project_structure(data)
    assert r.ok
    return r.structure


def three():
    return [ast_("intro"), ast_("battle"), ast_("finale")]


class TestValidCreation(unittest.TestCase):
    def test_1_valid_registry_from_a_list_and_a_tuple(self):
        for source in (three(), tuple(three())):
            r = create_game_asset_registry(source)
            self.assertTrue(r.ok)
            self.assertEqual(r.failures, [])
            self.assertEqual(r.codes(), [])
            self.assertIs(type(r.registry), GameAssetRegistry)
            self.assertEqual(r.registry.assets, tuple(three()))

    def test_2_empty_collection_is_valid(self):
        for empty in ([], ()):
            r = create_game_asset_registry(empty)
            self.assertTrue(r.ok)
            self.assertEqual(r.registry.assets, ())
            self.assertEqual(r.registry.to_dict(), {"assets": []})

    def test_3_input_order_is_preserved_not_sorted(self):
        r = create_game_asset_registry([ast_("zed"), ast_("amy"), ast_("mid")])
        self.assertEqual(r.registry.asset_ids, ("zed", "amy", "mid"))
        self.assertEqual([c["asset_id"] for c in r.registry.to_dict()["assets"]], ["zed", "amy", "mid"])

    def test_4_the_input_collection_is_not_changed_and_later_edits_do_not_reach_the_registry(self):
        source = three()
        snapshot = list(source)
        r = create_game_asset_registry(source)
        source.append(ast_("late"))
        source.pop(0)
        self.assertEqual(r.registry.asset_ids, ("intro", "battle", "finale"))
        self.assertEqual(snapshot, three())


class TestLookup(unittest.TestCase):
    def test_5_exact_id_lookup_finds_the_asset(self):
        registry = create_game_asset_registry(three()).registry
        for cid in ("intro", "battle", "finale"):
            res = registry.lookup(cid)
            self.assertTrue(res.found)
            self.assertIsNone(res.code)
            self.assertEqual(res.asset.asset_id, cid)
            self.assertIs(res.asset, registry.assets[registry.asset_ids.index(cid)])

    def test_6_missing_ids_return_a_stable_not_found_result_and_never_raise(self):
        registry = create_game_asset_registry(three()).registry
        class S(str):
            pass
        for bad in ("ghost", "", "Intro", "intro ", " intro", None, 1, b"intro", ["intro"], S("intro")):
            with self.subTest(bad=repr(bad)):
                res = registry.lookup(bad)
                self.assertFalse(res.found)
                self.assertIsNone(res.asset)
                self.assertEqual(res.code, reg.FAILURE_ASSET_NOT_FOUND)
                self.assertEqual(res.to_dict(), {"found": False, "asset": None, "code": reg.FAILURE_ASSET_NOT_FOUND})

    def test_7_lookup_on_an_empty_registry_and_found_to_dict(self):
        self.assertFalse(create_game_asset_registry([]).registry.lookup("intro").found)
        d = create_game_asset_registry(three()).registry.lookup("intro").to_dict()
        self.assertEqual(d, {"found": True, "asset": ast_("intro").to_dict(), "code": None})

    def test_8_lookup_does_not_change_the_registry(self):
        registry = create_game_asset_registry(three()).registry
        before = registry.to_dict()
        registry.lookup("intro")
        registry.lookup("ghost")
        self.assertEqual(registry.to_dict(), before)


class TestInvalidAssets(unittest.TestCase):
    def test_9_duplicate_asset_ids_are_rejected(self):
        r = create_game_asset_registry([ast_("intro"), ast_("battle"), ast_("intro", name="Other")])
        self.assertFalse(r.ok)
        self.assertIsNone(r.registry)
        self.assertEqual(r.codes(), [reg.FAILURE_DUPLICATE_ASSET_ID])
        self.assertEqual(r.failures[0]["field"], "assets")
        self.assertEqual(create_game_asset_registry([ast_("a"), ast_("a"), ast_("a")]).codes(), [reg.FAILURE_DUPLICATE_ASSET_ID] * 2)

    def test_10_identical_objects_twice_are_also_duplicates_but_ids_are_exact(self):
        c = ast_("intro")
        self.assertEqual(create_game_asset_registry([c, c]).codes(), [reg.FAILURE_DUPLICATE_ASSET_ID])
        self.assertTrue(create_game_asset_registry([ast_("intro"), ast_("Intro"), ast_("intro ")]).ok)

    def test_11_invalid_collection_types_are_rejected_not_coerced(self):
        class L(list):
            pass
        bads = [None, "intro", b"x", 1, True, {"intro"}, frozenset([ast_("intro")]), {"intro": ast_("intro")}, iter(three()), (c for c in three()),
                ast_("intro"), L(three())]
        for bad in bads:
            with self.subTest(bad=type(bad).__name__):
                r = create_game_asset_registry(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.registry)
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_COLLECTION])
                self.assertEqual(r.failures[0]["field"], "assets")

    def test_12_non_game_asset_items_are_rejected(self):
        valid_data = ast_("intro").to_dict()
        for bad in (None, "intro", 1, valid_data, object(), [ast_("intro")], create_game_project_structure(
                {"assets": [], "assets": [], "gameplay_systems": [], "assets": []}).structure):
            with self.subTest(bad=type(bad).__name__):
                r = create_game_asset_registry([ast_("battle"), bad])
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_ASSET])
                self.assertIn("assets[1]", r.failures[0]["message"])

    def test_13_a_lookalike_class_is_not_accepted(self):
        class Fake:
            asset_id = "intro"
            name = "Intro"
            description = ""
            asset_type = "x"

            def to_dict(self):
                return {}
        self.assertEqual(create_game_asset_registry([Fake()]).codes(), [reg.FAILURE_INVALID_ASSET])

    def test_14_every_collection_problem_is_reported_in_position_order(self):
        r = create_game_asset_registry([1, ast_("a"), ast_("a"), None, ast_("b")])
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_ASSET, reg.FAILURE_DUPLICATE_ASSET_ID, reg.FAILURE_INVALID_ASSET])
        self.assertEqual([("[%d]" % i) in f["message"] for i, f in zip((0, 2, 3), r.failures)], [True, True, True])


class TestStructureValidation(unittest.TestCase):
    def test_15_structure_none_means_no_reference_check(self):
        self.assertTrue(create_game_asset_registry(three(), None).ok)
        self.assertTrue(create_game_asset_registry(three()).ok)

    def test_16_structure_whose_assets_are_all_registered_is_accepted(self):
        s = structure(["battle", "intro"])
        r = create_game_asset_registry(three(), s)
        self.assertTrue(r.ok)
        self.assertEqual(r.registry.asset_ids, ("intro", "battle", "finale"))      # registry order, not structure order

    def test_17_missing_structure_references_are_reported_in_structure_order(self):
        s = structure(["zed", "intro", "amy"])
        r = create_game_asset_registry(three(), s)
        self.assertFalse(r.ok)
        self.assertIsNone(r.registry)
        self.assertEqual(r.codes(), [reg.FAILURE_MISSING_ASSET_REFERENCE] * 2)
        self.assertEqual([f["field"] for f in r.failures], ["structure", "structure"])
        self.assertIn("'zed'", r.failures[0]["message"])
        self.assertIn("'amy'", r.failures[1]["message"])

    def test_18_unused_registered_assets_are_allowed(self):
        r = create_game_asset_registry(three(), structure(["intro"]))
        self.assertTrue(r.ok)
        self.assertEqual(r.registry.asset_ids, ("intro", "battle", "finale"))
        self.assertTrue(create_game_asset_registry(three(), structure([])).ok)

    def test_19_structure_with_assets_needs_a_registry_entry_even_when_empty(self):
        r = create_game_asset_registry([], structure(["intro"]))
        self.assertEqual(r.codes(), [reg.FAILURE_MISSING_ASSET_REFERENCE])
        self.assertTrue(create_game_asset_registry([], structure([])).ok)

    def test_20_reference_match_is_exact(self):
        self.assertEqual(create_game_asset_registry(three(), structure(["Intro"])).codes(), [reg.FAILURE_MISSING_ASSET_REFERENCE])
        self.assertEqual(create_game_asset_registry(three(), structure(["intro "])).codes(), [reg.FAILURE_MISSING_ASSET_REFERENCE])

    def test_21_invalid_structure_values_are_rejected(self):
        good = structure(["intro"]).to_dict()
        for bad in ("intro", 1, [], ["intro"], {}, good, object(), asset_like(), True, 0, ""):
            with self.subTest(bad=type(bad).__name__):
                r = create_game_asset_registry(three(), bad)
                self.assertFalse(r.ok)
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_STRUCTURE])
                self.assertEqual(r.failures[0]["field"], "structure")

    def test_22_collection_and_structure_problems_are_reported_together_in_fixed_order(self):
        r = create_game_asset_registry("nope", 5)
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_COLLECTION, reg.FAILURE_INVALID_STRUCTURE])
        r = create_game_asset_registry([ast_("intro"), ast_("intro"), 3], structure(["intro", "ghost"]))
        self.assertEqual(r.codes(), [reg.FAILURE_DUPLICATE_ASSET_ID, reg.FAILURE_INVALID_ASSET, reg.FAILURE_MISSING_ASSET_REFERENCE])
        self.assertIn("'ghost'", r.failures[2]["message"])

    def test_23_structure_and_assets_are_not_mutated(self):
        s = structure(["intro", "ghost"])
        cs = three()
        s_before, c_before = s.to_dict(), [c.to_dict() for c in cs]
        create_game_asset_registry(cs, s)
        create_game_asset_registry(cs, structure(["intro"]))
        self.assertEqual(s.to_dict(), s_before)
        self.assertEqual([c.to_dict() for c in cs], c_before)

    def test_24_the_structure_is_not_stored_in_the_registry(self):
        a = create_game_asset_registry(three(), structure(["intro"])).registry
        b = create_game_asset_registry(three()).registry
        self.assertEqual(a, b)
        self.assertEqual(a.to_dict(), b.to_dict())


def asset_like():
    class Fake:
        assets = ("intro",)
    return Fake()


class TestFactoryFailureBehavior(unittest.TestCase):
    def test_25_the_factory_never_raises_for_bad_input(self):
        class Boom:
            def __iter__(self):
                raise RuntimeError("must not iterate")

            def __eq__(self, other):
                raise RuntimeError("must not compare")
            __hash__ = None
        for chars, struct in ((None, None), (Boom(), None), ([Boom()], None), ([], Boom()), ({}, {}), (1, 1), ([None, None], "x"), ([[]], None)):
            with self.subTest(chars=type(chars).__name__, struct=type(struct).__name__):
                r = create_game_asset_registry(chars, struct)
                self.assertFalse(r.ok)
                self.assertIsNone(r.registry)
                self.assertTrue(r.failures)
                for f in r.failures:
                    self.assertIn(f["code"], reg.FAILURE_CODES)
                    self.assertEqual(set(f), {"code", "field", "message"})

    def test_26_failures_are_deterministic_and_result_to_dict_is_fresh(self):
        args = ([1, ast_("a"), ast_("a")], structure(["zzz"]))
        a, b = create_game_asset_registry(*args), create_game_asset_registry(*args)
        self.assertEqual(a.to_dict(), b.to_dict())
        d = a.to_dict()
        self.assertEqual((d["ok"], d["registry"]), (False, None))
        d["failures"][0]["code"] = "hacked"
        d["failures"].clear()
        self.assertEqual(a.codes(), b.codes())
        self.assertTrue(a.failures)

    def test_27_ok_result_to_dict_shape(self):
        d = create_game_asset_registry(three()).to_dict()
        self.assertEqual(set(d), {"ok", "registry", "failures"})
        self.assertEqual((d["ok"], d["failures"]), (True, []))
        self.assertEqual(d["registry"], {"assets": [c.to_dict() for c in three()]})

    def test_28_failure_codes_are_unique_and_stable(self):
        self.assertEqual(len(set(reg.FAILURE_CODES)), len(reg.FAILURE_CODES))
        self.assertEqual(reg.FAILURE_CODES, (
            "GAME_ASSET_REGISTRY_INVALID_COLLECTION", "GAME_ASSET_REGISTRY_INVALID_ASSET",
            "GAME_ASSET_REGISTRY_DUPLICATE_ASSET_ID", "GAME_ASSET_REGISTRY_INVALID_STRUCTURE",
            "GAME_ASSET_REGISTRY_MISSING_ASSET_REFERENCE", "GAME_ASSET_REGISTRY_ASSET_NOT_FOUND"))


class TestImmutabilityAndDeterminism(unittest.TestCase):
    def test_29_accessors_are_immutable_tuples(self):
        registry = create_game_asset_registry(three()).registry
        for coll in (registry.assets, registry.asset_ids):
            self.assertIs(type(coll), tuple)
            with self.assertRaises(TypeError):
                coll[0] = "x"
            self.assertFalse(hasattr(coll, "append"))
        self.assertIs(registry.assets, registry.assets)
        self.assertEqual(registry.asset_ids, ("intro", "battle", "finale"))

    def test_30_attributes_cannot_be_assigned_deleted_or_added(self):
        registry = create_game_asset_registry(three()).registry
        for name in ("assets", "asset_ids", "_assets", "extra"):
            with self.assertRaises(AttributeError):
                setattr(registry, name, ())
        for name in ("assets", "_assets"):
            with self.assertRaises(AttributeError):
                delattr(registry, name)
        self.assertFalse(hasattr(registry, "__dict__"))
        self.assertEqual(registry.asset_ids, ("intro", "battle", "finale"))

    def test_31_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            GameAssetRegistry(object(), [])
        with self.assertRaises(TypeError):
            GameAssetRegistry(None, three())
        with self.assertRaises(TypeError):
            class Sub(GameAssetRegistry):
                pass

    def test_32_equal_content_gives_equal_objects_and_hashes_and_order_matters(self):
        a = create_game_asset_registry(three()).registry
        b = create_game_asset_registry(tuple(three())).registry
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, create_game_asset_registry(list(reversed(three()))).registry)
        self.assertNotEqual(a, create_game_asset_registry(three()[:2]).registry)
        self.assertNotEqual(a, create_game_asset_registry([ast_("intro"), ast_("battle"), ast_("finale", asset_type="other")]).registry)
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, a.assets)

    def test_33_to_dict_is_fresh_ordered_and_round_trips_through_the_factory(self):
        registry = create_game_asset_registry(three()).registry
        d = registry.to_dict()
        self.assertEqual(list(d), ["assets"])
        self.assertEqual([c["asset_id"] for c in d["assets"]], ["intro", "battle", "finale"])
        d["assets"].append({"x": 1})
        d["assets"][0]["name"] = "hacked"
        again = registry.to_dict()
        self.assertIsNot(d, again)
        self.assertIsNot(again["assets"], registry.to_dict()["assets"])
        self.assertEqual(registry.assets[0].name, "Intro")
        rebuilt = create_game_asset_registry([create_game_asset(c).asset for c in again["assets"]]).registry
        self.assertEqual(rebuilt, registry)

    def test_34_copy_returns_the_same_object_and_pickling_is_refused(self):
        registry = create_game_asset_registry(three()).registry
        self.assertIs(copy.copy(registry), registry)
        self.assertIs(copy.deepcopy(registry), registry)
        with self.assertRaises(TypeError):
            pickle.dumps(registry)

    def test_35_registered_assets_are_the_original_immutable_objects(self):
        cs = three()
        registry = create_game_asset_registry(cs).registry
        for original, stored in zip(cs, registry.assets):
            self.assertIs(original, stored)
            with self.assertRaises(AttributeError):
                stored.name = "x"


class TestBoundaries(unittest.TestCase):
    def test_36_module_imports_only_the_two_record_modules_and_has_no_io_or_state(self):
        with open(os.path.join(PY_ROOT, "game_creation", "game_asset_registry.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([(n.level, n.module, [a.name for a in n.names]) for n in imports],
                         [(1, "game_asset", ["GameAsset"]), (1, "game_project_structure", ["GameProjectStructure"])])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(reg).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_37_earlier_section7_modules_are_untouched_and_unaware_of_the_registry(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))),
                         ["__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py", "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in ("game_creation/game_project.py", "game_creation/game_project_structure.py", "game_creation/game_scene.py", "game_creation/game_character.py", "game_creation/game_character_registry.py", "game_creation/game_scene_registry.py", "game_creation/gameplay_system_registry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("GameAssetRegistry", "game_asset_registry", "create_game_asset_registry"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "GameAssetRegistry", "game_asset_registry"):
                self.assertNotIn(token, text, (rel, token))

    def test_38_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("GameAssetRegistry", "create_game_asset_registry", "GameProjectStructure", "lookup", "does NOT", "later",
                       "unused", "asset_id"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
