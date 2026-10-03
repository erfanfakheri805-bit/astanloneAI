"""Prompt 723 - Section 7 game character foundation (`game_creation.game_character`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from game_creation import game_character as gsc
from game_creation.game_character import GameCharacter, create_game_character

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_character_foundation_prompt723.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def valid(**over):
    data = {"character_id": "hero_1", "name": "Mira Vale", "description": "The main playable character.", "role": "protagonist"}
    data.update(over)
    return data


class TestValidCreation(unittest.TestCase):
    def test_1_valid_character_keeps_every_value_exactly(self):
        data = valid(name="  Mira Vale ")
        r = create_game_character(data)
        self.assertTrue(r.ok)
        self.assertEqual(r.failures, [])
        s = r.character
        self.assertIs(type(s), GameCharacter)
        self.assertEqual((s.character_id, s.name, s.description, s.role), ("hero_1", "  Mira Vale ", "The main playable character.", "protagonist"))

    def test_2_empty_description_is_valid_and_blank_description_too(self):
        self.assertEqual(create_game_character(valid(description="")).character.description, "")
        self.assertEqual(create_game_character(valid(description="   ")).character.description, "   ")      # only required fields are checked for blankness

    def test_3_any_role_text_is_accepted(self):
        self.assertTrue(create_game_character(valid(role="anything goes")).ok)

    def test_4_the_factory_never_changes_the_callers_dict(self):
        data = valid()
        snapshot = dict(data)
        create_game_character(data)
        create_game_character(valid(name=""))
        self.assertEqual(data, snapshot)


class TestRequiredFields(unittest.TestCase):
    def test_5_empty_or_blank_required_fields_are_rejected(self):
        for field, code in (("character_id", gsc.FAILURE_INVALID_CHARACTER_ID), ("name", gsc.FAILURE_INVALID_NAME),
                            ("role", gsc.FAILURE_INVALID_ROLE)):
            for bad in ("", "   ", "\n\t"):
                with self.subTest(field=field, bad=bad):
                    r = create_game_character(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertIsNone(r.character)
                    self.assertEqual(r.codes(), [code])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_6_missing_fields_are_rejected_and_nothing_is_defaulted(self):
        for field in gsc.FIELDS:
            with self.subTest(field=field):
                data = valid()
                del data[field]
                r = create_game_character(data)
                self.assertEqual(r.codes(), [gsc.FAILURE_MISSING_FIELD])
                self.assertEqual(r.failures[0]["field"], field)
        self.assertEqual(create_game_character({}).codes(), [gsc.FAILURE_MISSING_FIELD] * 4)

    def test_7_every_problem_is_reported_at_once_in_field_order(self):
        r = create_game_character(valid(character_id="", name=3, description=None, role=" "))
        self.assertEqual(r.codes(), [gsc.FAILURE_INVALID_CHARACTER_ID, gsc.FAILURE_INVALID_NAME, gsc.FAILURE_INVALID_DESCRIPTION,
                                     gsc.FAILURE_INVALID_ROLE])
        self.assertEqual([f["field"] for f in r.failures], list(gsc.FIELDS))


class TestTypes(unittest.TestCase):
    def test_8_invalid_field_types_are_rejected_for_every_field(self):
        class Sub(str):
            pass
        bads = [None, 0, 1, True, 1.5, b"x", ["a"], ("a",), {"a": 1}, {"a"}, object(), Sub("x")]
        for field in gsc.FIELDS:
            for bad in bads:
                with self.subTest(field=field, bad=type(bad).__name__):
                    r = create_game_character(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [gsc._INVALID_CODES[gsc.FIELDS.index(field)]])

    def test_9_non_dict_input_is_rejected_including_dict_subclasses(self):
        class D(dict):
            pass
        for bad in (None, [], (), "x", 1, valid().items(), D(valid())):
            with self.subTest(bad=type(bad).__name__):
                r = create_game_character(bad)
                self.assertEqual(r.codes(), [gsc.FAILURE_INVALID_INPUT])
                self.assertIsNone(r.character)
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
        create_game_character(valid(name=Evil("x")))
        self.assertEqual(calls, [])


class TestUnexpectedFields(unittest.TestCase):
    def test_11_unexpected_fields_are_rejected_not_ignored(self):
        r = create_game_character(valid(zeta=1, health=100, Alpha="x"))
        self.assertFalse(r.ok)
        self.assertEqual(r.codes(), [gsc.FAILURE_UNEXPECTED_FIELD] * 3)
        self.assertEqual([f["field"] for f in r.failures], ["Alpha", "health", "zeta"])

    def test_12_non_string_keys_are_rejected(self):
        data = valid()
        data[1] = "x"
        data[None] = "y"
        self.assertEqual(create_game_character(data).codes(), [gsc.FAILURE_UNEXPECTED_FIELD])

    def test_13_near_miss_field_names_are_unexpected_and_the_real_field_is_missing(self):
        data = valid()
        data["Name"] = data.pop("name")
        self.assertEqual(create_game_character(data).codes(), [gsc.FAILURE_UNEXPECTED_FIELD, gsc.FAILURE_MISSING_FIELD])


class TestFactoryFailureBehavior(unittest.TestCase):
    def test_14_the_factory_never_raises_for_bad_data(self):
        for bad in (None, 1, [], {}, {"x": object()}, valid(name=object()), {None: 1}, valid(character_id=[1])):
            with self.subTest(bad=repr(bad)[:30]):
                r = create_game_character(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.character)
                self.assertTrue(r.failures)
                for f in r.failures:
                    self.assertIn(f["code"], gsc.FAILURE_CODES)
                    self.assertEqual(set(f), {"code", "field", "message"})

    def test_15_failures_are_deterministic_across_calls(self):
        bad = {"zzz": 1, "character_id": "", "name": 5, "aaa": 2}
        self.assertEqual(create_game_character(bad).to_dict(), create_game_character(dict(bad)).to_dict())
        self.assertEqual(create_game_character(bad).codes(), [gsc.FAILURE_UNEXPECTED_FIELD, gsc.FAILURE_UNEXPECTED_FIELD,
                                                          gsc.FAILURE_INVALID_CHARACTER_ID, gsc.FAILURE_INVALID_NAME,
                                                          gsc.FAILURE_MISSING_FIELD, gsc.FAILURE_MISSING_FIELD])

    def test_16_result_to_dict_shapes_and_fresh_failures(self):
        ok = create_game_character(valid()).to_dict()
        self.assertEqual(set(ok), {"ok", "character", "failures"})
        self.assertEqual((ok["ok"], ok["character"], ok["failures"]), (True, valid(), []))
        r = create_game_character(valid(name=""))
        bad = r.to_dict()
        self.assertEqual((bad["ok"], bad["character"]), (False, None))
        bad["failures"][0]["code"] = "hacked"
        self.assertEqual(r.codes(), [gsc.FAILURE_INVALID_NAME])

    def test_17_failure_codes_are_unique_and_stable(self):
        self.assertEqual(len(set(gsc.FAILURE_CODES)), len(gsc.FAILURE_CODES))
        self.assertEqual(gsc.FAILURE_CODES, ("GAME_CHARACTER_INVALID_INPUT", "GAME_CHARACTER_UNEXPECTED_FIELD", "GAME_CHARACTER_MISSING_FIELD",
                                             "GAME_CHARACTER_INVALID_CHARACTER_ID", "GAME_CHARACTER_INVALID_NAME", "GAME_CHARACTER_INVALID_DESCRIPTION",
                                             "GAME_CHARACTER_INVALID_ROLE"))


class TestDeterminismAndImmutability(unittest.TestCase):
    def test_18_equal_data_gives_equal_objects_hashes_and_serialization(self):
        a, b = create_game_character(valid()).character, create_game_character(valid()).character
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(list(a.to_dict()), list(gsc.FIELDS))
        self.assertEqual(len({a, b}), 1)
        for f in gsc.FIELDS:
            self.assertNotEqual(a, create_game_character(valid(**{f: "other"})).character, f)
        self.assertNotEqual(a, valid())

    def test_19_to_dict_round_trips_and_is_a_fresh_dict_each_time(self):
        s = create_game_character(valid()).character
        d = s.to_dict()
        self.assertEqual(d, valid())
        d["name"] = "hacked"
        self.assertEqual(s.name, "Mira Vale")
        self.assertIsNot(s.to_dict(), s.to_dict())
        self.assertEqual(create_game_character(s.to_dict()).character, s)

    def test_20_later_edits_to_the_input_do_not_reach_the_character(self):
        data = valid()
        s = create_game_character(data).character
        data["name"] = "changed"
        self.assertEqual(s.name, "Mira Vale")

    def test_21_attributes_cannot_be_assigned_deleted_or_added(self):
        s = create_game_character(valid()).character
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
            GameCharacter(object(), "a", "b", "", "c")
        with self.assertRaises(TypeError):
            GameCharacter(None, "a", "b", "", "c")
        with self.assertRaises(TypeError):
            class Sub(GameCharacter):
                pass

    def test_23_copy_returns_the_same_object_and_pickling_is_refused(self):
        s = create_game_character(valid()).character
        self.assertIs(copy.copy(s), s)
        self.assertIs(copy.deepcopy(s), s)
        with self.assertRaises(TypeError):
            pickle.dumps(s)


class TestBoundaries(unittest.TestCase):
    def test_24_module_has_no_imports_calls_or_module_state(self):
        with open(os.path.join(PY_ROOT, "game_creation", "game_character.py"), encoding="utf-8") as fh:
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

    def test_25_character_is_standalone_and_production_code_is_untouched(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))),
                         ["__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py", "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in ("game_creation/game_project.py", "game_creation/game_project_structure.py", "game_creation/game_scene.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_character", "GameCharacter"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "GameCharacter", "game_character"):
                self.assertNotIn(token, text, (rel, token))

    def test_26_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("GameCharacter", "create_game_character", "character_id", "role", "does NOT", "later", "unexpected"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
