"""Prompt 720 - Section 7 game project foundation (`game_creation.game_project`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from game_creation import game_project as gp
from game_creation.game_project import GameProject, create_game_project

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_project_foundation_prompt720.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def valid(**over):
    data = {"project_id": "p-1", "name": "Sky Forge", "description": "A small test game.", "genre": "platformer",
            "target_platform": "android", "version": "0.1.0"}
    data.update(over)
    return data


class TestValidCreation(unittest.TestCase):
    def test_1_valid_project_keeps_every_value_exactly(self):
        data = valid(name="  Sky Forge ")
        result = create_game_project(data)
        self.assertTrue(result.ok)
        self.assertEqual(result.failures, [])
        p = result.project
        self.assertIs(type(p), GameProject)
        self.assertEqual((p.project_id, p.name, p.description, p.genre, p.target_platform, p.version),
                         ("p-1", "  Sky Forge ", "A small test game.", "platformer", "android", "0.1.0"))   # never trimmed

    def test_2_description_genre_and_platform_may_be_empty(self):
        result = create_game_project(valid(description="", genre="", target_platform=""))
        self.assertTrue(result.ok)
        self.assertEqual((result.project.description, result.project.genre, result.project.target_platform), ("", "", ""))

    def test_3_any_genre_platform_and_version_text_is_accepted(self):
        self.assertTrue(create_game_project(valid(genre="anything goes", target_platform="Toaster", version="v?")).ok)

    def test_4_the_factory_never_changes_the_callers_dict(self):
        data = valid()
        snapshot = dict(data)
        create_game_project(data)
        create_game_project(valid(name=""))
        self.assertEqual(data, snapshot)


class TestRequiredFields(unittest.TestCase):
    def test_5_empty_or_blank_required_fields_are_rejected(self):
        for field, code in (("project_id", gp.FAILURE_INVALID_PROJECT_ID), ("name", gp.FAILURE_INVALID_NAME), ("version", gp.FAILURE_INVALID_VERSION)):
            for bad in ("", "   ", "\n\t"):
                with self.subTest(field=field, bad=bad):
                    r = create_game_project(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertIsNone(r.project)
                    self.assertEqual(r.codes(), [code])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_6_missing_fields_are_rejected_and_nothing_is_defaulted(self):
        for field in gp.FIELDS:
            with self.subTest(field=field):
                data = valid()
                del data[field]
                r = create_game_project(data)
                self.assertEqual(r.codes(), [gp.FAILURE_MISSING_FIELD])
                self.assertEqual(r.failures[0]["field"], field)
        self.assertEqual(create_game_project({}).codes(), [gp.FAILURE_MISSING_FIELD] * 6)

    def test_7_every_problem_is_reported_at_once_in_field_order(self):
        r = create_game_project(valid(project_id="", name=3, description=None, genre=1.5, target_platform=[], version=" "))
        self.assertEqual(r.codes(), [gp.FAILURE_INVALID_PROJECT_ID, gp.FAILURE_INVALID_NAME, gp.FAILURE_INVALID_DESCRIPTION,
                                     gp.FAILURE_INVALID_GENRE, gp.FAILURE_INVALID_TARGET_PLATFORM, gp.FAILURE_INVALID_VERSION])


class TestTypes(unittest.TestCase):
    def test_8_invalid_field_types_are_rejected_for_every_field(self):
        class Sub(str):
            pass
        bads = [None, 0, 1, True, 1.5, b"x", ["a"], ("a",), {"a": 1}, {"a"}, object(), Sub("x")]
        for field in gp.FIELDS:
            for bad in bads:
                with self.subTest(field=field, bad=type(bad).__name__):
                    r = create_game_project(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [gp._INVALID_CODES[gp.FIELDS.index(field)]])

    def test_9_non_dict_input_is_rejected_including_dict_subclasses(self):
        class D(dict):
            pass
        for bad in (None, [], (), "x", 1, valid().items(), D(valid())):
            with self.subTest(bad=type(bad).__name__):
                r = create_game_project(bad)
                self.assertEqual(r.codes(), [gp.FAILURE_INVALID_INPUT])
                self.assertIsNone(r.project)

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
        create_game_project(valid(name=Evil("x")))
        self.assertEqual(calls, [])


class TestUnexpectedFields(unittest.TestCase):
    def test_11_unexpected_fields_are_rejected_not_ignored(self):
        r = create_game_project(valid(zeta=1, engine="unity", Alpha="x"))
        self.assertFalse(r.ok)
        self.assertEqual(r.codes(), [gp.FAILURE_UNEXPECTED_FIELD] * 3)
        self.assertEqual([f["field"] for f in r.failures], ["Alpha", "engine", "zeta"])        # sorted, deterministic

    def test_12_non_string_keys_are_rejected(self):
        data = valid()
        data[1] = "x"
        data[None] = "y"
        r = create_game_project(data)
        self.assertEqual(r.codes(), [gp.FAILURE_UNEXPECTED_FIELD])

    def test_13_near_miss_field_names_are_unexpected_and_the_real_field_is_missing(self):
        data = valid()
        data["Name"] = data.pop("name")
        self.assertEqual(create_game_project(data).codes(), [gp.FAILURE_UNEXPECTED_FIELD, gp.FAILURE_MISSING_FIELD])


class TestDeterminismAndImmutability(unittest.TestCase):
    def test_14_equal_data_gives_equal_objects_hashes_and_serialization(self):
        a, b = create_game_project(valid()).project, create_game_project(valid()).project
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(list(a.to_dict()), list(gp.FIELDS))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, create_game_project(valid(version="0.2.0")).project)
        self.assertNotEqual(a, valid())                                   # not equal to a bare dict

    def test_15_to_dict_round_trips_and_is_a_fresh_dict_each_time(self):
        p = create_game_project(valid()).project
        d = p.to_dict()
        self.assertEqual(d, valid())
        d["name"] = "hacked"
        self.assertEqual(p.name, "Sky Forge")
        self.assertIsNot(p.to_dict(), p.to_dict())
        self.assertEqual(create_game_project(p.to_dict()).project, p)

    def test_16_later_edits_to_the_input_do_not_reach_the_project(self):
        data = valid()
        p = create_game_project(data).project
        data["name"] = "changed"
        self.assertEqual(p.name, "Sky Forge")

    def test_17_attributes_cannot_be_assigned_deleted_or_added(self):
        p = create_game_project(valid()).project
        for field in gp.FIELDS:
            with self.assertRaises(AttributeError):
                setattr(p, field, "x")
            with self.assertRaises(AttributeError):
                delattr(p, field)
        with self.assertRaises(AttributeError):
            p.extra = 1
        with self.assertRaises(AttributeError):
            p._name = "x"
        self.assertFalse(hasattr(p, "__dict__"))
        self.assertEqual(p.name, "Sky Forge")

    def test_18_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            GameProject(object(), "a", "b", "", "", "", "1")
        with self.assertRaises(TypeError):
            GameProject(None, "a", "b", "", "", "", "1")
        with self.assertRaises(TypeError):
            class Sub(GameProject):
                pass

    def test_19_copy_returns_the_same_object_and_pickling_is_refused(self):
        p = create_game_project(valid()).project
        self.assertIs(copy.copy(p), p)
        self.assertIs(copy.deepcopy(p), p)
        with self.assertRaises(TypeError):
            pickle.dumps(p)

    def test_20_result_to_dict_shapes(self):
        ok = create_game_project(valid()).to_dict()
        self.assertEqual(set(ok), {"ok", "project", "failures"})
        self.assertEqual((ok["ok"], ok["project"], ok["failures"]), (True, valid(), []))
        bad = create_game_project(valid(name="")).to_dict()
        self.assertEqual((bad["ok"], bad["project"]), (False, None))
        self.assertEqual(set(bad["failures"][0]), {"code", "field", "message"})


class TestBoundaries(unittest.TestCase):
    def test_21_module_has_no_imports_calls_or_module_state(self):
        with open(os.path.join(PY_ROOT, "game_creation", "game_project.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:                                              # module level: constants, functions, classes only
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(gp).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_22_only_the_new_package_is_added_to_production_code(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))),
                         ["__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py", "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])      # Prompt 721 added the structure module, 722 the scene module, 723 the character module
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "GameProject", "game_project"):
                self.assertNotIn(token, text, (rel, token))

    def test_23_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("GameProject", "create_game_project", "does NOT", "future", "project_id", "unexpected"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
