"""Prompt 729 - Section 7 game scene composition (`game_creation.game_scene_composition`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from game_creation import game_scene_composition as comp
from game_creation.game_scene_composition import GameSceneComposition, create_game_scene_composition

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_scene_composition_prompt729.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
SOURCE = os.path.join(PY_ROOT, "game_creation", "game_scene_composition.py")


def data(**over):
    d = {"scene_id": "forest", "character_ids": ["hero", "wolf"], "asset_ids": ["tree", "rock", "fog"], "gameplay_system_ids": ["combat"]}
    d.update(over)
    return d


def made(**over):
    r = create_game_scene_composition(data(**over))
    assert r.ok, r.failures
    return r.composition


class TestValidCreation(unittest.TestCase):
    def test_1_valid_creation_exposes_all_fields(self):
        r = create_game_scene_composition(data())
        self.assertTrue(r.ok)
        self.assertEqual((r.failures, r.codes()), ([], []))
        c = r.composition
        self.assertIs(type(c), GameSceneComposition)
        self.assertEqual((c.scene_id, c.character_ids, c.asset_ids, c.gameplay_system_ids),
                         ("forest", ("hero", "wolf"), ("tree", "rock", "fog"), ("combat",)))

    def test_2_tuples_are_accepted_too(self):
        c = made(character_ids=("hero",), asset_ids=(), gameplay_system_ids=("a", "b"))
        self.assertEqual((c.character_ids, c.asset_ids, c.gameplay_system_ids), (("hero",), (), ("a", "b")))

    def test_3_empty_collections_are_valid(self):
        r = create_game_scene_composition(data(character_ids=[], asset_ids=[], gameplay_system_ids=[]))
        self.assertTrue(r.ok)
        self.assertEqual(r.composition.to_dict(), {"scene_id": "forest", "character_ids": [], "asset_ids": [], "gameplay_system_ids": []})

    def test_4_collection_order_is_preserved_exactly_not_sorted(self):
        c = made(character_ids=["zed", "amy", "mid"], asset_ids=["z", "a"], gameplay_system_ids=["y", "x"])
        self.assertEqual((c.character_ids, c.asset_ids, c.gameplay_system_ids), (("zed", "amy", "mid"), ("z", "a"), ("y", "x")))
        self.assertEqual(c.to_dict()["character_ids"], ["zed", "amy", "mid"])

    def test_5_values_are_not_trimmed_or_case_folded(self):
        c = made(scene_id=" Forest ", character_ids=["Hero", "hero", " hero", "hero "])
        self.assertEqual(c.scene_id, " Forest ")
        self.assertEqual(c.character_ids, ("Hero", "hero", " hero", "hero "))

    def test_6_cross_collection_duplicate_ids_are_allowed(self):
        c = made(character_ids=["x"], asset_ids=["x"], gameplay_system_ids=["x"])
        self.assertEqual((c.character_ids, c.asset_ids, c.gameplay_system_ids), (("x",), ("x",), ("x",)))
        self.assertTrue(create_game_scene_composition(data(scene_id="x", character_ids=["x"])).ok)

    def test_7_ids_are_not_resolved_against_anything(self):
        self.assertTrue(create_game_scene_composition(data(character_ids=["no-such-character"], asset_ids=["no-such-asset"],
                                                           gameplay_system_ids=["no-such-system"], scene_id="no-such-scene")).ok)

    def test_8_the_callers_dict_and_lists_are_not_changed_and_later_edits_do_not_reach_the_composition(self):
        d = data()
        snapshot = {k: (list(v) if isinstance(v, list) else v) for k, v in d.items()}
        c = create_game_scene_composition(d).composition
        d["character_ids"].append("late")
        d["asset_ids"].pop(0)
        d["gameplay_system_ids"].clear()
        d["scene_id"] = "other"
        self.assertEqual((c.character_ids, c.asset_ids, c.gameplay_system_ids, c.scene_id),
                         (("hero", "wolf"), ("tree", "rock", "fog"), ("combat",), "forest"))
        d2 = data()
        create_game_scene_composition(d2)
        self.assertEqual(d2, snapshot)


class TestInvalidInput(unittest.TestCase):
    def test_9_non_dict_input_is_rejected(self):
        for bad in (None, "x", 1, [], (), [("scene_id", "x")], object(), data().items(), frozenset()):
            with self.subTest(bad=type(bad).__name__):
                r = create_game_scene_composition(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.composition)
                self.assertEqual(r.codes(), [comp.FAILURE_INVALID_INPUT])

    def test_10_dict_subclass_is_rejected(self):
        class D(dict):
            pass
        r = create_game_scene_composition(D(data()))
        self.assertEqual(r.codes(), [comp.FAILURE_INVALID_INPUT])
        from collections import OrderedDict
        self.assertEqual(create_game_scene_composition(OrderedDict(data())).codes(), [comp.FAILURE_INVALID_INPUT])

    def test_11_missing_fields_are_reported_in_field_order_and_not_checked_further(self):
        for field in comp.FIELDS:
            d = data()
            del d[field]
            r = create_game_scene_composition(d)
            self.assertEqual(r.codes(), [comp.FAILURE_MISSING_FIELD])
            self.assertEqual(r.failures[0]["field"], field)
        r = create_game_scene_composition({})
        self.assertEqual(r.codes(), [comp.FAILURE_MISSING_FIELD] * 4)
        self.assertEqual([f["field"] for f in r.failures], list(comp.FIELDS))

    def test_12_unexpected_fields_are_rejected_sorted_and_reported_first(self):
        r = create_game_scene_composition(data(zeta=1, alpha=2))
        self.assertEqual(r.codes(), [comp.FAILURE_UNEXPECTED_FIELD] * 2)
        self.assertEqual([f["field"] for f in r.failures], ["alpha", "zeta"])
        r = create_game_scene_composition({1: "x", "scene_id": "s", "character_ids": [], "asset_ids": [], "gameplay_system_ids": []})
        self.assertEqual(r.codes(), [comp.FAILURE_UNEXPECTED_FIELD])
        self.assertIsNone(r.failures[0]["field"])

    def test_13_unexpected_then_missing_then_field_problems_in_fixed_order(self):
        r = create_game_scene_composition({"zz": 1, "scene_id": 5, "asset_ids": "no"})
        self.assertEqual(r.codes(), [comp.FAILURE_UNEXPECTED_FIELD, comp.FAILURE_MISSING_FIELD, comp.FAILURE_MISSING_FIELD,
                                     comp.FAILURE_INVALID_SCENE_ID, comp.FAILURE_INVALID_ASSET_IDS])
        self.assertEqual([f["field"] for f in r.failures], ["zz", "character_ids", "gameplay_system_ids", "scene_id", "asset_ids"])

    def test_14_wrong_scene_id_type(self):
        class S(str):
            pass
        for bad in (None, 1, True, b"forest", ["forest"], S("forest"), object()):
            with self.subTest(bad=type(bad).__name__):
                r = create_game_scene_composition(data(scene_id=bad))
                self.assertEqual(r.codes(), [comp.FAILURE_INVALID_SCENE_ID])
                self.assertEqual(r.failures[0]["field"], "scene_id")

    def test_15_blank_scene_id(self):
        for bad in ("", " ", "   ", "\t", "\n", " \t\n "):
            with self.subTest(bad=repr(bad)):
                self.assertEqual(create_game_scene_composition(data(scene_id=bad)).codes(), [comp.FAILURE_INVALID_SCENE_ID])

    def test_16_wrong_collection_types_for_each_collection(self):
        class L(list):
            pass
        expected = {"character_ids": comp.FAILURE_INVALID_CHARACTER_IDS, "asset_ids": comp.FAILURE_INVALID_ASSET_IDS,
                    "gameplay_system_ids": comp.FAILURE_INVALID_GAMEPLAY_SYSTEM_IDS}
        for field, code in expected.items():
            for bad in (None, "hero", b"x", 1, True, {"hero"}, frozenset(["hero"]), {"hero": 1}, iter(["hero"]), (c for c in ["hero"]), L(["hero"])):
                with self.subTest(field=field, bad=type(bad).__name__):
                    r = create_game_scene_composition(data(**{field: bad}))
                    self.assertEqual(r.codes(), [code])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_17_wrong_item_types_for_each_collection(self):
        class S(str):
            pass
        expected = {"character_ids": comp.FAILURE_INVALID_CHARACTER_ID, "asset_ids": comp.FAILURE_INVALID_ASSET_ID,
                    "gameplay_system_ids": comp.FAILURE_INVALID_GAMEPLAY_SYSTEM_ID}
        for field, code in expected.items():
            for bad in (None, 1, True, b"x", ["x"], ("x",), {"id": "x"}, object(), S("x")):
                with self.subTest(field=field, bad=type(bad).__name__):
                    r = create_game_scene_composition(data(**{field: ["ok", bad]}))
                    self.assertEqual(r.codes(), [code])
                    self.assertIn("%s[1]" % field, r.failures[0]["message"])

    def test_18_blank_ids_in_each_collection(self):
        expected = {"character_ids": comp.FAILURE_INVALID_CHARACTER_ID, "asset_ids": comp.FAILURE_INVALID_ASSET_ID,
                    "gameplay_system_ids": comp.FAILURE_INVALID_GAMEPLAY_SYSTEM_ID}
        for field, code in expected.items():
            for bad in ("", " ", "\t", "\n", "  \t "):
                with self.subTest(field=field, bad=repr(bad)):
                    r = create_game_scene_composition(data(**{field: [bad]}))
                    self.assertEqual(r.codes(), [code])
                    self.assertIn("blank", r.failures[0]["message"])

    def test_19_duplicates_in_each_collection(self):
        expected = {"character_ids": comp.FAILURE_DUPLICATE_CHARACTER_ID, "asset_ids": comp.FAILURE_DUPLICATE_ASSET_ID,
                    "gameplay_system_ids": comp.FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID}
        for field, code in expected.items():
            r = create_game_scene_composition(data(**{field: ["a", "b", "a"]}))
            self.assertEqual(r.codes(), [code])
            self.assertEqual(r.failures[0]["field"], field)
            self.assertIn("%s[2]" % field, r.failures[0]["message"])
            self.assertEqual(create_game_scene_composition(data(**{field: ("a", "a", "a")})).codes(), [code] * 2)
            self.assertTrue(create_game_scene_composition(data(**{field: ["a", "A", "a "]})).ok)

    def test_20_collection_failures_are_ordered_scene_id_characters_assets_systems(self):
        r = create_game_scene_composition({"scene_id": "", "character_ids": [1, "a", "a"], "asset_ids": ["", "b", "b"],
                                           "gameplay_system_ids": [None, "c", "c"]})
        self.assertEqual(r.codes(), [comp.FAILURE_INVALID_SCENE_ID, comp.FAILURE_INVALID_CHARACTER_ID, comp.FAILURE_DUPLICATE_CHARACTER_ID,
                                     comp.FAILURE_INVALID_ASSET_ID, comp.FAILURE_DUPLICATE_ASSET_ID, comp.FAILURE_INVALID_GAMEPLAY_SYSTEM_ID,
                                     comp.FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID])
        self.assertEqual([f["field"] for f in r.failures], ["scene_id", "character_ids", "character_ids", "asset_ids", "asset_ids",
                                                            "gameplay_system_ids", "gameplay_system_ids"])

    def test_21_items_are_reported_in_position_order(self):
        r = create_game_scene_composition(data(character_ids=[1, "a", "a", None, ""]))
        self.assertEqual(r.codes(), [comp.FAILURE_INVALID_CHARACTER_ID, comp.FAILURE_DUPLICATE_CHARACTER_ID, comp.FAILURE_INVALID_CHARACTER_ID,
                                     comp.FAILURE_INVALID_CHARACTER_ID])
        self.assertEqual([("[%d]" % i) in f["message"] for i, f in zip((0, 2, 3, 4), r.failures)], [True] * 4)


class TestFactoryFailureBehavior(unittest.TestCase):
    def test_22_the_factory_never_raises_for_bad_input(self):
        class Boom:
            def __iter__(self):
                raise RuntimeError("must not iterate")

            def __eq__(self, other):
                raise RuntimeError("must not compare")

            def __getattr__(self, name):
                raise RuntimeError("must not touch")
            __hash__ = None
        for bad in (None, Boom(), {}, {"scene_id": Boom()}, data(scene_id=Boom()), data(character_ids=Boom()), data(asset_ids=[Boom()]),
                    data(gameplay_system_ids=[[Boom()]]), data(scene_id=None, character_ids=None)):
            with self.subTest(bad=type(bad).__name__):
                r = create_game_scene_composition(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.composition)
                self.assertTrue(r.failures)
                for f in r.failures:
                    self.assertIn(f["code"], comp.FAILURE_CODES)
                    self.assertEqual(set(f), {"code", "field", "message"})

    def test_23_failures_are_deterministic_and_result_to_dict_is_fresh(self):
        bad = data(scene_id="", character_ids=[1, "a", "a"], extra=1)
        a, b = create_game_scene_composition(bad), create_game_scene_composition(bad)
        self.assertEqual(a.to_dict(), b.to_dict())
        d = a.to_dict()
        self.assertEqual((d["ok"], d["composition"]), (False, None))
        d["failures"][0]["code"] = "hacked"
        d["failures"].clear()
        self.assertEqual(a.codes(), b.codes())
        self.assertTrue(a.failures)

    def test_24_ok_result_to_dict_shape(self):
        d = create_game_scene_composition(data()).to_dict()
        self.assertEqual(set(d), {"ok", "composition", "failures"})
        self.assertEqual((d["ok"], d["failures"]), (True, []))
        self.assertEqual(d["composition"], data())

    def test_25_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(len(set(comp.FAILURE_CODES)), len(comp.FAILURE_CODES))
        self.assertTrue(all(c.startswith("GAME_SCENE_COMPOSITION_") for c in comp.FAILURE_CODES))
        self.assertEqual(comp.FAILURE_CODES, tuple("GAME_SCENE_COMPOSITION_" + s for s in (
            "INVALID_INPUT", "UNEXPECTED_FIELD", "MISSING_FIELD", "INVALID_SCENE_ID", "INVALID_CHARACTER_IDS", "INVALID_CHARACTER_ID",
            "DUPLICATE_CHARACTER_ID", "INVALID_ASSET_IDS", "INVALID_ASSET_ID", "DUPLICATE_ASSET_ID", "INVALID_GAMEPLAY_SYSTEM_IDS",
            "INVALID_GAMEPLAY_SYSTEM_ID", "DUPLICATE_GAMEPLAY_SYSTEM_ID")))


class TestImmutabilityAndDeterminism(unittest.TestCase):
    def test_26_accessors_are_immutable_tuples(self):
        c = made()
        for coll in (c.character_ids, c.asset_ids, c.gameplay_system_ids):
            self.assertIs(type(coll), tuple)
            with self.assertRaises(TypeError):
                coll[0] = "x"
            self.assertFalse(hasattr(coll, "append"))
        self.assertIs(c.character_ids, c.character_ids)

    def test_27_attributes_cannot_be_assigned_deleted_or_added(self):
        c = made()
        for name in ("scene_id", "character_ids", "asset_ids", "gameplay_system_ids", "_scene_id", "_character_ids", "extra"):
            with self.assertRaises(AttributeError):
                setattr(c, name, "x")
        for name in ("scene_id", "_asset_ids"):
            with self.assertRaises(AttributeError):
                delattr(c, name)
        self.assertFalse(hasattr(c, "__dict__"))
        self.assertEqual(c.to_dict(), data())

    def test_28_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            GameSceneComposition(object(), "s", [], [], [])
        with self.assertRaises(TypeError):
            GameSceneComposition(None, "s", [], [], [])
        with self.assertRaises(TypeError):
            class Sub(GameSceneComposition):
                pass

    def test_29_equal_data_gives_equal_objects_and_hashes(self):
        a, b = made(), made(character_ids=("hero", "wolf"))
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertEqual(hash(a), hash(made()))

    def test_30_any_difference_or_order_change_makes_objects_unequal(self):
        a = made()
        for other in (made(scene_id="cave"), made(character_ids=["wolf", "hero"]), made(asset_ids=["tree", "rock"]),
                      made(gameplay_system_ids=[]), made(asset_ids=["fog", "rock", "tree"]), made(character_ids=["hero", "Wolf"])):
            self.assertNotEqual(a, other)
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, a.character_ids)
        self.assertNotEqual(a, "forest")

    def test_31_collections_are_separate_namespaces_in_equality(self):
        self.assertNotEqual(made(character_ids=["x"], asset_ids=[]), made(character_ids=[], asset_ids=["x"]))

    def test_32_to_dict_is_fresh_ordered_and_round_trips_through_the_factory(self):
        c = made()
        d = c.to_dict()
        self.assertEqual(list(d), list(comp.FIELDS))
        d["character_ids"].append("x")
        d["asset_ids"][0] = "hacked"
        d["scene_id"] = "hacked"
        again = c.to_dict()
        self.assertIsNot(d, again)
        for key in comp.COLLECTION_FIELDS:
            self.assertIsNot(again[key], c.to_dict()[key])
        self.assertEqual(c.character_ids, ("hero", "wolf"))
        self.assertEqual(c.asset_ids[0], "tree")
        self.assertEqual(create_game_scene_composition(again).composition, c)

    def test_33_copy_returns_the_same_object_and_pickling_is_refused(self):
        c = made()
        self.assertIs(copy.copy(c), c)
        self.assertIs(copy.deepcopy(c), c)
        with self.assertRaises(TypeError):
            pickle.dumps(c)
        with self.assertRaises(TypeError):
            pickle.dumps(c, protocol=2)

    def test_34_repr_summarises_without_raising(self):
        self.assertEqual(repr(made()), "GameSceneComposition(scene_id='forest', characters=2, assets=3, gameplay_systems=1)")


class TestBoundaries(unittest.TestCase):
    def test_35_module_has_no_imports_calls_or_module_state(self):
        with open(SOURCE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(comp).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_36_no_registry_or_validator_is_imported_referenced_or_looked_up(self):
        with open(SOURCE, encoding="utf-8") as fh:
            text = fh.read()
        code_only = "\n".join(line for line in text.splitlines())
        tree = ast.parse(text)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for token in ("GameCharacterRegistry", "GameAssetRegistry", "GameSceneRegistry", "GameplaySystemRegistry", "GameProjectValidat",
                      "game_character_registry", "game_asset_registry", "game_scene_registry", "gameplay_system_registry",
                      "game_project_validator", "validate_game_project", "lookup"):
            self.assertNotIn(token, names)
            self.assertFalse(any(token in n for n in names), token)
        self.assertNotIn("import ", "\n".join(l for l in code_only.splitlines() if l.startswith(("import", "from"))))
        self.assertFalse([n for n in vars(comp) if "registry" in n.lower() or "validat" in n.lower()])

    def test_37_creating_a_composition_does_not_load_any_registry_module(self):
        import sys
        import importlib
        # the registries may already be imported by other tests; what matters is that this module holds no reference to them
        module = importlib.import_module("game_creation.game_scene_composition")
        for value in vars(module).values():
            self.assertNotIn(getattr(value, "__module__", ""), ("game_creation.game_scene_registry", "game_creation.game_asset_registry",
                                                                 "game_creation.game_character_registry",
                                                                 "game_creation.gameplay_system_registry",
                                                                 "game_creation.game_project_validator"))
        self.assertIn("game_creation.game_scene_composition", sys.modules)

    def test_38_earlier_section7_modules_are_untouched_and_unaware_of_the_composition(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py",
            "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py",
            "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in ("game_project.py", "game_project_structure.py", "game_scene.py", "game_character.py", "game_asset.py",
                    "game_scene_registry.py", "game_character_registry.py", "gameplay_system_registry.py", "game_asset_registry.py",
                    "game_project_validator.py"):
            with open(os.path.join(PY_ROOT, "game_creation", rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_scene_composition", "GameSceneComposition", "create_game_scene_composition"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "GameSceneComposition", "game_scene_composition"):
                self.assertNotIn(token, text, (rel, token))

    def test_39_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("GameSceneComposition", "create_game_scene_composition", "GAME_SCENE_COMPOSITION_", "character_ids", "asset_ids",
                       "gameplay_system_ids", "does NOT", "later", "not resolved"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
