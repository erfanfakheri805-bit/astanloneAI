"""Prompt 722 - Section 7 game scene foundation (`game_creation.game_scene`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from game_creation import game_scene as gsc
from game_creation.game_scene import GameScene, create_game_scene

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_scene_foundation_prompt722.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def valid(**over):
    data = {"scene_id": "level_1", "name": "Forest Edge", "description": "The first playable area.", "scene_type": "level"}
    data.update(over)
    return data


class TestValidCreation(unittest.TestCase):
    def test_1_valid_scene_keeps_every_value_exactly(self):
        data = valid(name="  Forest Edge ")
        r = create_game_scene(data)
        self.assertTrue(r.ok)
        self.assertEqual(r.failures, [])
        s = r.scene
        self.assertIs(type(s), GameScene)
        self.assertEqual((s.scene_id, s.name, s.description, s.scene_type), ("level_1", "  Forest Edge ", "The first playable area.", "level"))

    def test_2_empty_description_is_valid_and_blank_description_too(self):
        self.assertEqual(create_game_scene(valid(description="")).scene.description, "")
        self.assertEqual(create_game_scene(valid(description="   ")).scene.description, "   ")      # only required fields are checked for blankness

    def test_3_any_scene_type_text_is_accepted(self):
        self.assertTrue(create_game_scene(valid(scene_type="anything goes")).ok)

    def test_4_the_factory_never_changes_the_callers_dict(self):
        data = valid()
        snapshot = dict(data)
        create_game_scene(data)
        create_game_scene(valid(name=""))
        self.assertEqual(data, snapshot)


class TestRequiredFields(unittest.TestCase):
    def test_5_empty_or_blank_required_fields_are_rejected(self):
        for field, code in (("scene_id", gsc.FAILURE_INVALID_SCENE_ID), ("name", gsc.FAILURE_INVALID_NAME),
                            ("scene_type", gsc.FAILURE_INVALID_SCENE_TYPE)):
            for bad in ("", "   ", "\n\t"):
                with self.subTest(field=field, bad=bad):
                    r = create_game_scene(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertIsNone(r.scene)
                    self.assertEqual(r.codes(), [code])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_6_missing_fields_are_rejected_and_nothing_is_defaulted(self):
        for field in gsc.FIELDS:
            with self.subTest(field=field):
                data = valid()
                del data[field]
                r = create_game_scene(data)
                self.assertEqual(r.codes(), [gsc.FAILURE_MISSING_FIELD])
                self.assertEqual(r.failures[0]["field"], field)
        self.assertEqual(create_game_scene({}).codes(), [gsc.FAILURE_MISSING_FIELD] * 4)

    def test_7_every_problem_is_reported_at_once_in_field_order(self):
        r = create_game_scene(valid(scene_id="", name=3, description=None, scene_type=" "))
        self.assertEqual(r.codes(), [gsc.FAILURE_INVALID_SCENE_ID, gsc.FAILURE_INVALID_NAME, gsc.FAILURE_INVALID_DESCRIPTION,
                                     gsc.FAILURE_INVALID_SCENE_TYPE])
        self.assertEqual([f["field"] for f in r.failures], list(gsc.FIELDS))


class TestTypes(unittest.TestCase):
    def test_8_invalid_field_types_are_rejected_for_every_field(self):
        class Sub(str):
            pass
        bads = [None, 0, 1, True, 1.5, b"x", ["a"], ("a",), {"a": 1}, {"a"}, object(), Sub("x")]
        for field in gsc.FIELDS:
            for bad in bads:
                with self.subTest(field=field, bad=type(bad).__name__):
                    r = create_game_scene(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [gsc._INVALID_CODES[gsc.FIELDS.index(field)]])

    def test_9_non_dict_input_is_rejected_including_dict_subclasses(self):
        class D(dict):
            pass
        for bad in (None, [], (), "x", 1, valid().items(), D(valid())):
            with self.subTest(bad=type(bad).__name__):
                r = create_game_scene(bad)
                self.assertEqual(r.codes(), [gsc.FAILURE_INVALID_INPUT])
                self.assertIsNone(r.scene)
                self.assertFalse(r.ok)

    def test_10_a_str_subclass_method_is_never_called(self):
        calls = []

        class Evil(str):
            def strip(self, *a):
                calls.append("strip")
                return "x"

            def __eq__(self, other):
                calls.append("eq")
                return True
            __hash__ = str.__hash__
        create_game_scene(valid(name=Evil("x")))
        self.assertEqual(calls, [])


class TestUnexpectedFields(unittest.TestCase):
    def test_11_unexpected_fields_are_rejected_not_ignored(self):
        r = create_game_scene(valid(zeta=1, objects=[], Alpha="x"))
        self.assertFalse(r.ok)
        self.assertEqual(r.codes(), [gsc.FAILURE_UNEXPECTED_FIELD] * 3)
        self.assertEqual([f["field"] for f in r.failures], ["Alpha", "objects", "zeta"])

    def test_12_non_string_keys_are_rejected(self):
        data = valid()
        data[1] = "x"
        data[None] = "y"
        self.assertEqual(create_game_scene(data).codes(), [gsc.FAILURE_UNEXPECTED_FIELD])

    def test_13_near_miss_field_names_are_unexpected_and_the_real_field_is_missing(self):
        data = valid()
        data["Name"] = data.pop("name")
        self.assertEqual(create_game_scene(data).codes(), [gsc.FAILURE_UNEXPECTED_FIELD, gsc.FAILURE_MISSING_FIELD])


class TestFactoryFailureBehavior(unittest.TestCase):
    def test_14_the_factory_never_raises_for_bad_data(self):
        for bad in (None, 1, [], {}, {"x": object()}, valid(name=object()), {None: 1}, valid(scene_id=[1])):
            with self.subTest(bad=repr(bad)[:30]):
                r = create_game_scene(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.scene)
                self.assertTrue(r.failures)
                for f in r.failures:
                    self.assertIn(f["code"], gsc.FAILURE_CODES)
                    self.assertEqual(set(f), {"code", "field", "message"})

    def test_15_failures_are_deterministic_across_calls(self):
        bad = {"zzz": 1, "scene_id": "", "name": 5, "aaa": 2}
        self.assertEqual(create_game_scene(bad).to_dict(), create_game_scene(dict(bad)).to_dict())
        self.assertEqual(create_game_scene(bad).codes(), [gsc.FAILURE_UNEXPECTED_FIELD, gsc.FAILURE_UNEXPECTED_FIELD,
                                                          gsc.FAILURE_INVALID_SCENE_ID, gsc.FAILURE_INVALID_NAME,
                                                          gsc.FAILURE_MISSING_FIELD, gsc.FAILURE_MISSING_FIELD])

    def test_16_result_to_dict_shapes_and_fresh_failures(self):
        ok = create_game_scene(valid()).to_dict()
        self.assertEqual(set(ok), {"ok", "scene", "failures"})
        self.assertEqual((ok["ok"], ok["scene"], ok["failures"]), (True, valid(), []))
        r = create_game_scene(valid(name=""))
        bad = r.to_dict()
        self.assertEqual((bad["ok"], bad["scene"]), (False, None))
        bad["failures"][0]["code"] = "hacked"
        self.assertEqual(r.codes(), [gsc.FAILURE_INVALID_NAME])

    def test_17_failure_codes_are_unique_and_stable(self):
        self.assertEqual(len(set(gsc.FAILURE_CODES)), len(gsc.FAILURE_CODES))
        self.assertEqual(gsc.FAILURE_CODES, ("GAME_SCENE_INVALID_INPUT", "GAME_SCENE_UNEXPECTED_FIELD", "GAME_SCENE_MISSING_FIELD",
                                             "GAME_SCENE_INVALID_SCENE_ID", "GAME_SCENE_INVALID_NAME", "GAME_SCENE_INVALID_DESCRIPTION",
                                             "GAME_SCENE_INVALID_SCENE_TYPE"))


class TestDeterminismAndImmutability(unittest.TestCase):
    def test_18_equal_data_gives_equal_objects_hashes_and_serialization(self):
        a, b = create_game_scene(valid()).scene, create_game_scene(valid()).scene
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(list(a.to_dict()), list(gsc.FIELDS))
        self.assertEqual(len({a, b}), 1)
        for f in gsc.FIELDS:
            self.assertNotEqual(a, create_game_scene(valid(**{f: "other"})).scene, f)
        self.assertNotEqual(a, valid())

    def test_19_to_dict_round_trips_and_is_a_fresh_dict_each_time(self):
        s = create_game_scene(valid()).scene
        d = s.to_dict()
        self.assertEqual(d, valid())
        d["name"] = "hacked"
        self.assertEqual(s.name, "Forest Edge")
        self.assertIsNot(s.to_dict(), s.to_dict())
        self.assertEqual(create_game_scene(s.to_dict()).scene, s)

    def test_20_later_edits_to_the_input_do_not_reach_the_scene(self):
        data = valid()
        s = create_game_scene(data).scene
        data["name"] = "changed"
        self.assertEqual(s.name, "Forest Edge")

    def test_21_attributes_cannot_be_assigned_deleted_or_added(self):
        s = create_game_scene(valid()).scene
        for field in gsc.FIELDS:
            with self.assertRaises(AttributeError):
                setattr(s, field, "x")
            with self.assertRaises(AttributeError):
                delattr(s, field)
            with self.assertRaises(AttributeError):
                setattr(s, "_" + field, "x")
        with self.assertRaises(AttributeError):
            s.extra = 1
        self.assertFalse(hasattr(s, "__dict__"))
        self.assertEqual(s.to_dict(), valid())

    def test_22_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            GameScene(object(), "a", "b", "", "c")
        with self.assertRaises(TypeError):
            GameScene(None, "a", "b", "", "c")
        with self.assertRaises(TypeError):
            class Sub(GameScene):
                pass

    def test_23_copy_returns_the_same_object_and_pickling_is_refused(self):
        s = create_game_scene(valid()).scene
        self.assertIs(copy.copy(s), s)
        self.assertIs(copy.deepcopy(s), s)
        with self.assertRaises(TypeError):
            pickle.dumps(s)


class TestBoundaries(unittest.TestCase):
    def test_24_module_has_no_imports_calls_or_module_state(self):
        with open(os.path.join(PY_ROOT, "game_creation", "game_scene.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(gsc).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_25_scene_is_standalone_and_production_code_is_untouched(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))),
                         ["__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py", "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])      # Prompt 723 added the character module
        for rel in ("game_creation/game_project.py", "game_creation/game_project_structure.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_scene", "GameScene"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "GameScene", "game_scene"):
                self.assertNotIn(token, text, (rel, token))

    def test_26_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("GameScene", "create_game_scene", "scene_id", "scene_type", "does NOT", "later", "unexpected"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
