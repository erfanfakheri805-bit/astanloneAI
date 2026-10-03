"""Prompt 721 - Section 7 game project structure (`game_creation.game_project_structure`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from game_creation import game_project_structure as gs
from game_creation.game_project_structure import GameProjectStructure, create_game_project_structure

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_project_structure_prompt721.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def valid(**over):
    data = {"scenes": ["main_menu", "level_1"], "characters": ["hero", "villain"], "gameplay_systems": ["combat", "inventory"],
            "assets": ["hero_sprite", "theme_music"]}
    data.update(over)
    return data


class TestValidCreation(unittest.TestCase):
    def test_1_valid_structure_has_all_four_collections(self):
        r = create_game_project_structure(valid())
        self.assertTrue(r.ok)
        self.assertEqual(r.failures, [])
        s = r.structure
        self.assertIs(type(s), GameProjectStructure)
        self.assertEqual(s.scenes, ("main_menu", "level_1"))
        self.assertEqual(s.characters, ("hero", "villain"))
        self.assertEqual(s.gameplay_systems, ("combat", "inventory"))
        self.assertEqual(s.assets, ("hero_sprite", "theme_music"))

    def test_2_input_ordering_is_preserved_not_sorted(self):
        s = create_game_project_structure(valid(scenes=["z", "a", "m"], assets=["b", "B", "a"])).structure
        self.assertEqual(s.scenes, ("z", "a", "m"))
        self.assertEqual(s.assets, ("b", "B", "a"))

    def test_3_empty_collections_are_valid(self):
        r = create_game_project_structure({f: [] for f in gs.FIELDS})
        self.assertTrue(r.ok)
        for f in gs.FIELDS:
            self.assertEqual(getattr(r.structure, f), ())
        self.assertEqual(r.structure.to_dict(), {f: [] for f in gs.FIELDS})
        self.assertTrue(create_game_project_structure(valid(scenes=[])).ok)

    def test_4_identifiers_are_stored_exactly_never_trimmed_or_case_folded(self):
        s = create_game_project_structure(valid(scenes=[" Level 1 ", "level 1"])).structure
        self.assertEqual(s.scenes, (" Level 1 ", "level 1"))

    def test_5_same_identifier_may_appear_in_different_collections(self):
        self.assertTrue(create_game_project_structure(valid(scenes=["x"], characters=["x"], gameplay_systems=["x"], assets=["x"])).ok)

    def test_6_the_factory_never_changes_the_callers_data(self):
        data = valid()
        snapshot = {k: list(v) for k, v in data.items()}
        create_game_project_structure(data)
        create_game_project_structure(valid(scenes=["a", "a", ""]))
        self.assertEqual(data, snapshot)


class TestInvalidCollections(unittest.TestCase):
    def test_7_duplicate_identifiers_are_rejected_per_collection(self):
        for field in gs.FIELDS:
            with self.subTest(field=field):
                r = create_game_project_structure(valid(**{field: ["a", "b", "a"]}))
                self.assertFalse(r.ok)
                self.assertIsNone(r.structure)
                self.assertEqual(r.codes(), [gs.FAILURE_DUPLICATE_IDENTIFIER])
                self.assertEqual(r.failures[0]["field"], field)

    def test_8_duplicates_are_exact_only(self):
        self.assertTrue(create_game_project_structure(valid(scenes=["a", "A", "a "])).ok)
        self.assertEqual(create_game_project_structure(valid(scenes=["a", "a", "a"])).codes(), [gs.FAILURE_DUPLICATE_IDENTIFIER] * 2)

    def test_9_blank_identifiers_are_rejected(self):
        for field in gs.FIELDS:
            for bad in ("", " ", "   ", "\n\t"):
                with self.subTest(field=field, bad=bad):
                    r = create_game_project_structure(valid(**{field: ["ok", bad]}))
                    self.assertEqual(r.codes(), [gs.FAILURE_BLANK_IDENTIFIER])
                    self.assertEqual(r.failures[0]["field"], field)
        self.assertEqual(create_game_project_structure(valid(scenes=["", ""])).codes(), [gs.FAILURE_BLANK_IDENTIFIER] * 2)

    def test_10_wrong_item_types_are_rejected(self):
        class Sub(str):
            pass
        bads = [None, 0, 1, True, 1.5, b"x", ["a"], ("a",), {"a": 1}, {"a"}, object(), Sub("x")]
        for field in gs.FIELDS:
            for bad in bads:
                with self.subTest(field=field, bad=type(bad).__name__):
                    r = create_game_project_structure(valid(**{field: ["ok", bad]}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [gs.FAILURE_INVALID_IDENTIFIER_TYPE])

    def test_11_wrong_collection_types_are_rejected_not_coerced(self):
        class L(list):
            pass
        bads = [None, "abc", b"x", 1, True, ("a",), {"a"}, frozenset(["a"]), {"a": 1}, iter(["a"]), (x for x in "a"), L(["a"])]
        for field in gs.FIELDS:
            for bad in bads:
                with self.subTest(field=field, bad=type(bad).__name__):
                    r = create_game_project_structure(valid(**{field: bad}))
                    self.assertEqual(r.codes(), [gs.FAILURE_INVALID_COLLECTION])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_12_missing_fields_are_rejected_and_nothing_is_defaulted(self):
        for field in gs.FIELDS:
            with self.subTest(field=field):
                data = valid()
                del data[field]
                r = create_game_project_structure(data)
                self.assertEqual(r.codes(), [gs.FAILURE_MISSING_FIELD])
                self.assertEqual(r.failures[0]["field"], field)
        self.assertEqual(create_game_project_structure({}).codes(), [gs.FAILURE_MISSING_FIELD] * 4)

    def test_13_unexpected_fields_are_rejected_not_ignored(self):
        r = create_game_project_structure(valid(zeta=[], levels=[], Alpha=[]))
        self.assertEqual(r.codes(), [gs.FAILURE_UNEXPECTED_FIELD] * 3)
        self.assertEqual([f["field"] for f in r.failures], ["Alpha", "levels", "zeta"])
        data = valid()
        data[1] = []
        self.assertEqual(create_game_project_structure(data).codes(), [gs.FAILURE_UNEXPECTED_FIELD])
        data = valid()
        data["Scenes"] = data.pop("scenes")
        self.assertEqual(create_game_project_structure(data).codes(), [gs.FAILURE_UNEXPECTED_FIELD, gs.FAILURE_MISSING_FIELD])

    def test_14_non_dict_input_is_rejected_including_dict_subclasses(self):
        class D(dict):
            pass
        for bad in (None, [], (), "x", 1, valid().items(), D(valid())):
            with self.subTest(bad=type(bad).__name__):
                r = create_game_project_structure(bad)
                self.assertEqual(r.codes(), [gs.FAILURE_INVALID_INPUT])
                self.assertIsNone(r.structure)

    def test_15_every_problem_is_reported_at_once_in_a_fixed_order(self):
        r = create_game_project_structure({"zzz": 1, "scenes": ["a", "a", ""], "characters": "no", "gameplay_systems": [1], "extra": 0})
        self.assertEqual(r.codes(), [gs.FAILURE_UNEXPECTED_FIELD, gs.FAILURE_UNEXPECTED_FIELD,
                                     gs.FAILURE_DUPLICATE_IDENTIFIER, gs.FAILURE_BLANK_IDENTIFIER,
                                     gs.FAILURE_INVALID_COLLECTION, gs.FAILURE_INVALID_IDENTIFIER_TYPE, gs.FAILURE_MISSING_FIELD])
        self.assertEqual([f["field"] for f in r.failures], ["extra", "zzz", "scenes", "scenes", "characters", "gameplay_systems", "assets"])
        self.assertEqual(r.to_dict(), create_game_project_structure({"zzz": 1, "scenes": ["a", "a", ""], "characters": "no",
                                                                     "gameplay_systems": [1], "extra": 0}).to_dict())

    def test_16_a_str_subclass_method_is_never_called(self):
        calls = []

        class Evil(str):
            def strip(self, *a):
                calls.append("strip")
                return "x"

            def __eq__(self, other):
                calls.append("eq")
                return True

            def __hash__(self):
                calls.append("hash")
                return 1
        create_game_project_structure(valid(scenes=[Evil("x"), Evil("x")]))
        self.assertEqual(calls, [])


class TestImmutabilityAndDeterminism(unittest.TestCase):
    def test_17_later_edits_to_the_input_lists_do_not_reach_the_structure(self):
        data = valid()
        s = create_game_project_structure(data).structure
        data["scenes"].append("intruder")
        data["scenes"][0] = "changed"
        self.assertEqual(s.scenes, ("main_menu", "level_1"))

    def test_18_accessors_are_immutable_tuples(self):
        s = create_game_project_structure(valid()).structure
        for f in gs.FIELDS:
            coll = getattr(s, f)
            self.assertIs(type(coll), tuple)
            self.assertIs(getattr(s, f), coll)
            with self.assertRaises(TypeError):
                coll[0] = "x"
            self.assertFalse(hasattr(coll, "append"))
        self.assertEqual(s.scenes, ("main_menu", "level_1"))

    def test_19_attributes_cannot_be_assigned_deleted_or_added(self):
        s = create_game_project_structure(valid()).structure
        for field in gs.FIELDS:
            with self.assertRaises(AttributeError):
                setattr(s, field, ())
            with self.assertRaises(AttributeError):
                delattr(s, field)
            with self.assertRaises(AttributeError):
                setattr(s, "_" + field, [])
        with self.assertRaises(AttributeError):
            s.extra = 1
        self.assertFalse(hasattr(s, "__dict__"))
        self.assertEqual(s.scenes, ("main_menu", "level_1"))

    def test_20_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            GameProjectStructure(object(), [], [], [], [])
        with self.assertRaises(TypeError):
            GameProjectStructure(None, [], [], [], [])
        with self.assertRaises(TypeError):
            class Sub(GameProjectStructure):
                pass

    def test_21_equal_data_gives_equal_objects_and_hashes(self):
        a, b = create_game_project_structure(valid()).structure, create_game_project_structure(valid()).structure
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, create_game_project_structure(valid(scenes=["level_1", "main_menu"])).structure)   # order matters
        self.assertNotEqual(a, create_game_project_structure(valid(assets=[])).structure)
        self.assertNotEqual(a, valid())
        swapped = create_game_project_structure(valid(scenes=["hero", "villain"], characters=["main_menu", "level_1"])).structure
        self.assertNotEqual(a, swapped)

    def test_22_to_dict_is_fresh_fixed_order_and_round_trips(self):
        s = create_game_project_structure(valid()).structure
        d = s.to_dict()
        self.assertEqual(d, valid())
        self.assertEqual(list(d), list(gs.FIELDS))
        for v in d.values():
            self.assertIs(type(v), list)
        d["scenes"].append("hacked")
        d["assets"] = []
        self.assertEqual(s.scenes, ("main_menu", "level_1"))
        self.assertEqual(s.to_dict(), valid())
        a, b = s.to_dict(), s.to_dict()
        self.assertIsNot(a, b)
        for f in gs.FIELDS:
            self.assertIsNot(a[f], b[f])
        self.assertEqual(create_game_project_structure(s.to_dict()).structure, s)

    def test_23_copy_returns_the_same_object_and_pickling_is_refused(self):
        s = create_game_project_structure(valid()).structure
        self.assertIs(copy.copy(s), s)
        self.assertIs(copy.deepcopy(s), s)
        with self.assertRaises(TypeError):
            pickle.dumps(s)

    def test_24_result_to_dict_shapes(self):
        ok = create_game_project_structure(valid()).to_dict()
        self.assertEqual(set(ok), {"ok", "structure", "failures"})
        self.assertEqual((ok["ok"], ok["structure"], ok["failures"]), (True, valid(), []))
        bad = create_game_project_structure(valid(scenes=["a", "a"])).to_dict()
        self.assertEqual((bad["ok"], bad["structure"]), (False, None))
        self.assertEqual(set(bad["failures"][0]), {"code", "field", "message"})


class TestBoundaries(unittest.TestCase):
    def test_25_module_has_no_imports_calls_or_module_state(self):
        with open(os.path.join(PY_ROOT, "game_creation", "game_project_structure.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(gs).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_26_existing_game_project_api_and_production_code_are_untouched(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))),
                         ["__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py", "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])      # Prompts 722/723 added the scene and character modules
        with open(os.path.join(PY_ROOT, "game_creation", "game_project.py"), encoding="utf-8") as fh:
            self.assertNotIn("structure", fh.read().lower())
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "GameProjectStructure", "game_project_structure"):
                self.assertNotIn(token, text, (rel, token))

    def test_27_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("GameProjectStructure", "create_game_project_structure", "identifiers", "does NOT", "future", "scenes",
                       "characters", "gameplay_systems", "assets"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
