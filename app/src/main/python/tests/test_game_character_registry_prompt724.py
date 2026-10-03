"""Prompt 724 - Section 7 game character registry (`game_creation.game_character_registry`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from game_creation import game_character_registry as reg
from game_creation.game_character import GameCharacter, create_game_character
from game_creation.game_character_registry import GameCharacterRegistry, create_game_character_registry
from game_creation.game_project_structure import create_game_project_structure

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_character_registry_prompt724.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def char(cid, name=None, role="npc", description=""):
    r = create_game_character({"character_id": cid, "name": name or cid.title(), "description": description, "role": role})
    assert r.ok
    return r.character


def structure(characters=(), **over):
    data = {"scenes": [], "characters": list(characters), "gameplay_systems": [], "assets": []}
    data.update(over)
    r = create_game_project_structure(data)
    assert r.ok
    return r.structure


def three():
    return [char("hero"), char("villain"), char("mentor")]


class TestValidCreation(unittest.TestCase):
    def test_1_valid_registry_from_a_list_and_a_tuple(self):
        for source in (three(), tuple(three())):
            r = create_game_character_registry(source)
            self.assertTrue(r.ok)
            self.assertEqual(r.failures, [])
            self.assertEqual(r.codes(), [])
            self.assertIs(type(r.registry), GameCharacterRegistry)
            self.assertEqual(r.registry.characters, tuple(three()))

    def test_2_empty_collection_is_valid(self):
        for empty in ([], ()):
            r = create_game_character_registry(empty)
            self.assertTrue(r.ok)
            self.assertEqual(r.registry.characters, ())
            self.assertEqual(r.registry.to_dict(), {"characters": []})

    def test_3_input_order_is_preserved_not_sorted(self):
        r = create_game_character_registry([char("zed"), char("amy"), char("mid")])
        self.assertEqual(r.registry.character_ids, ("zed", "amy", "mid"))
        self.assertEqual([c["character_id"] for c in r.registry.to_dict()["characters"]], ["zed", "amy", "mid"])

    def test_4_the_input_collection_is_not_changed_and_later_edits_do_not_reach_the_registry(self):
        source = three()
        snapshot = list(source)
        r = create_game_character_registry(source)
        source.append(char("late"))
        source.pop(0)
        self.assertEqual(r.registry.character_ids, ("hero", "villain", "mentor"))
        self.assertEqual(snapshot, three())


class TestLookup(unittest.TestCase):
    def test_5_exact_id_lookup_finds_the_character(self):
        registry = create_game_character_registry(three()).registry
        for cid in ("hero", "villain", "mentor"):
            res = registry.lookup(cid)
            self.assertTrue(res.found)
            self.assertIsNone(res.code)
            self.assertEqual(res.character.character_id, cid)
            self.assertIs(res.character, registry.characters[registry.character_ids.index(cid)])

    def test_6_missing_ids_return_a_stable_not_found_result_and_never_raise(self):
        registry = create_game_character_registry(three()).registry
        class S(str):
            pass
        for bad in ("ghost", "", "Hero", "hero ", " hero", None, 1, b"hero", ["hero"], S("hero")):
            with self.subTest(bad=repr(bad)):
                res = registry.lookup(bad)
                self.assertFalse(res.found)
                self.assertIsNone(res.character)
                self.assertEqual(res.code, reg.FAILURE_CHARACTER_NOT_FOUND)
                self.assertEqual(res.to_dict(), {"found": False, "character": None, "code": reg.FAILURE_CHARACTER_NOT_FOUND})

    def test_7_lookup_on_an_empty_registry_and_found_to_dict(self):
        self.assertFalse(create_game_character_registry([]).registry.lookup("hero").found)
        d = create_game_character_registry(three()).registry.lookup("hero").to_dict()
        self.assertEqual(d, {"found": True, "character": char("hero").to_dict(), "code": None})

    def test_8_lookup_does_not_change_the_registry(self):
        registry = create_game_character_registry(three()).registry
        before = registry.to_dict()
        registry.lookup("hero")
        registry.lookup("ghost")
        self.assertEqual(registry.to_dict(), before)


class TestInvalidCharacters(unittest.TestCase):
    def test_9_duplicate_character_ids_are_rejected(self):
        r = create_game_character_registry([char("hero"), char("villain"), char("hero", name="Other")])
        self.assertFalse(r.ok)
        self.assertIsNone(r.registry)
        self.assertEqual(r.codes(), [reg.FAILURE_DUPLICATE_CHARACTER_ID])
        self.assertEqual(r.failures[0]["field"], "characters")
        self.assertEqual(create_game_character_registry([char("a"), char("a"), char("a")]).codes(), [reg.FAILURE_DUPLICATE_CHARACTER_ID] * 2)

    def test_10_identical_objects_twice_are_also_duplicates_but_ids_are_exact(self):
        c = char("hero")
        self.assertEqual(create_game_character_registry([c, c]).codes(), [reg.FAILURE_DUPLICATE_CHARACTER_ID])
        self.assertTrue(create_game_character_registry([char("hero"), char("Hero"), char("hero ")]).ok)

    def test_11_invalid_collection_types_are_rejected_not_coerced(self):
        class L(list):
            pass
        bads = [None, "hero", b"x", 1, True, {"hero"}, frozenset([char("hero")]), {"hero": char("hero")}, iter(three()), (c for c in three()),
                char("hero"), L(three())]
        for bad in bads:
            with self.subTest(bad=type(bad).__name__):
                r = create_game_character_registry(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.registry)
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_COLLECTION])
                self.assertEqual(r.failures[0]["field"], "characters")

    def test_12_non_game_character_items_are_rejected(self):
        valid_data = char("hero").to_dict()
        for bad in (None, "hero", 1, valid_data, object(), [char("hero")], create_game_project_structure(
                {"scenes": [], "characters": [], "gameplay_systems": [], "assets": []}).structure):
            with self.subTest(bad=type(bad).__name__):
                r = create_game_character_registry([char("villain"), bad])
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_CHARACTER])
                self.assertIn("characters[1]", r.failures[0]["message"])

    def test_13_a_lookalike_class_is_not_accepted(self):
        class Fake:
            character_id = "hero"
            name = "Hero"
            description = ""
            role = "x"

            def to_dict(self):
                return {}
        self.assertEqual(create_game_character_registry([Fake()]).codes(), [reg.FAILURE_INVALID_CHARACTER])

    def test_14_every_collection_problem_is_reported_in_position_order(self):
        r = create_game_character_registry([1, char("a"), char("a"), None, char("b")])
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_CHARACTER, reg.FAILURE_DUPLICATE_CHARACTER_ID, reg.FAILURE_INVALID_CHARACTER])
        self.assertEqual([("[%d]" % i) in f["message"] for i, f in zip((0, 2, 3), r.failures)], [True, True, True])


class TestStructureValidation(unittest.TestCase):
    def test_15_structure_none_means_no_reference_check(self):
        self.assertTrue(create_game_character_registry(three(), None).ok)
        self.assertTrue(create_game_character_registry(three()).ok)

    def test_16_structure_whose_characters_are_all_registered_is_accepted(self):
        s = structure(["villain", "hero"])
        r = create_game_character_registry(three(), s)
        self.assertTrue(r.ok)
        self.assertEqual(r.registry.character_ids, ("hero", "villain", "mentor"))      # registry order, not structure order

    def test_17_missing_structure_references_are_reported_in_structure_order(self):
        s = structure(["zed", "hero", "amy"])
        r = create_game_character_registry(three(), s)
        self.assertFalse(r.ok)
        self.assertIsNone(r.registry)
        self.assertEqual(r.codes(), [reg.FAILURE_MISSING_CHARACTER_REFERENCE] * 2)
        self.assertEqual([f["field"] for f in r.failures], ["structure", "structure"])
        self.assertIn("'zed'", r.failures[0]["message"])
        self.assertIn("'amy'", r.failures[1]["message"])

    def test_18_unused_registered_characters_are_allowed(self):
        r = create_game_character_registry(three(), structure(["hero"]))
        self.assertTrue(r.ok)
        self.assertEqual(r.registry.character_ids, ("hero", "villain", "mentor"))
        self.assertTrue(create_game_character_registry(three(), structure([])).ok)

    def test_19_structure_with_characters_needs_a_registry_entry_even_when_empty(self):
        r = create_game_character_registry([], structure(["hero"]))
        self.assertEqual(r.codes(), [reg.FAILURE_MISSING_CHARACTER_REFERENCE])
        self.assertTrue(create_game_character_registry([], structure([])).ok)

    def test_20_reference_match_is_exact(self):
        self.assertEqual(create_game_character_registry(three(), structure(["Hero"])).codes(), [reg.FAILURE_MISSING_CHARACTER_REFERENCE])
        self.assertEqual(create_game_character_registry(three(), structure(["hero "])).codes(), [reg.FAILURE_MISSING_CHARACTER_REFERENCE])

    def test_21_invalid_structure_values_are_rejected(self):
        good = structure(["hero"]).to_dict()
        for bad in ("hero", 1, [], ["hero"], {}, good, object(), character_like(), True, 0, ""):
            with self.subTest(bad=type(bad).__name__):
                r = create_game_character_registry(three(), bad)
                self.assertFalse(r.ok)
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_STRUCTURE])
                self.assertEqual(r.failures[0]["field"], "structure")

    def test_22_collection_and_structure_problems_are_reported_together_in_fixed_order(self):
        r = create_game_character_registry("nope", 5)
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_COLLECTION, reg.FAILURE_INVALID_STRUCTURE])
        r = create_game_character_registry([char("hero"), char("hero"), 3], structure(["hero", "ghost"]))
        self.assertEqual(r.codes(), [reg.FAILURE_DUPLICATE_CHARACTER_ID, reg.FAILURE_INVALID_CHARACTER, reg.FAILURE_MISSING_CHARACTER_REFERENCE])
        self.assertIn("'ghost'", r.failures[2]["message"])

    def test_23_structure_and_characters_are_not_mutated(self):
        s = structure(["hero", "ghost"])
        cs = three()
        s_before, c_before = s.to_dict(), [c.to_dict() for c in cs]
        create_game_character_registry(cs, s)
        create_game_character_registry(cs, structure(["hero"]))
        self.assertEqual(s.to_dict(), s_before)
        self.assertEqual([c.to_dict() for c in cs], c_before)

    def test_24_the_structure_is_not_stored_in_the_registry(self):
        a = create_game_character_registry(three(), structure(["hero"])).registry
        b = create_game_character_registry(three()).registry
        self.assertEqual(a, b)
        self.assertEqual(a.to_dict(), b.to_dict())


def character_like():
    class Fake:
        characters = ("hero",)
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
                r = create_game_character_registry(chars, struct)
                self.assertFalse(r.ok)
                self.assertIsNone(r.registry)
                self.assertTrue(r.failures)
                for f in r.failures:
                    self.assertIn(f["code"], reg.FAILURE_CODES)
                    self.assertEqual(set(f), {"code", "field", "message"})

    def test_26_failures_are_deterministic_and_result_to_dict_is_fresh(self):
        args = ([1, char("a"), char("a")], structure(["zzz"]))
        a, b = create_game_character_registry(*args), create_game_character_registry(*args)
        self.assertEqual(a.to_dict(), b.to_dict())
        d = a.to_dict()
        self.assertEqual((d["ok"], d["registry"]), (False, None))
        d["failures"][0]["code"] = "hacked"
        d["failures"].clear()
        self.assertEqual(a.codes(), b.codes())
        self.assertTrue(a.failures)

    def test_27_ok_result_to_dict_shape(self):
        d = create_game_character_registry(three()).to_dict()
        self.assertEqual(set(d), {"ok", "registry", "failures"})
        self.assertEqual((d["ok"], d["failures"]), (True, []))
        self.assertEqual(d["registry"], {"characters": [c.to_dict() for c in three()]})

    def test_28_failure_codes_are_unique_and_stable(self):
        self.assertEqual(len(set(reg.FAILURE_CODES)), len(reg.FAILURE_CODES))
        self.assertEqual(reg.FAILURE_CODES, (
            "GAME_CHARACTER_REGISTRY_INVALID_COLLECTION", "GAME_CHARACTER_REGISTRY_INVALID_CHARACTER",
            "GAME_CHARACTER_REGISTRY_DUPLICATE_CHARACTER_ID", "GAME_CHARACTER_REGISTRY_INVALID_STRUCTURE",
            "GAME_CHARACTER_REGISTRY_MISSING_CHARACTER_REFERENCE", "GAME_CHARACTER_REGISTRY_CHARACTER_NOT_FOUND"))


class TestImmutabilityAndDeterminism(unittest.TestCase):
    def test_29_accessors_are_immutable_tuples(self):
        registry = create_game_character_registry(three()).registry
        for coll in (registry.characters, registry.character_ids):
            self.assertIs(type(coll), tuple)
            with self.assertRaises(TypeError):
                coll[0] = "x"
            self.assertFalse(hasattr(coll, "append"))
        self.assertIs(registry.characters, registry.characters)
        self.assertEqual(registry.character_ids, ("hero", "villain", "mentor"))

    def test_30_attributes_cannot_be_assigned_deleted_or_added(self):
        registry = create_game_character_registry(three()).registry
        for name in ("characters", "character_ids", "_characters", "extra"):
            with self.assertRaises(AttributeError):
                setattr(registry, name, ())
        for name in ("characters", "_characters"):
            with self.assertRaises(AttributeError):
                delattr(registry, name)
        self.assertFalse(hasattr(registry, "__dict__"))
        self.assertEqual(registry.character_ids, ("hero", "villain", "mentor"))

    def test_31_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            GameCharacterRegistry(object(), [])
        with self.assertRaises(TypeError):
            GameCharacterRegistry(None, three())
        with self.assertRaises(TypeError):
            class Sub(GameCharacterRegistry):
                pass

    def test_32_equal_content_gives_equal_objects_and_hashes_and_order_matters(self):
        a = create_game_character_registry(three()).registry
        b = create_game_character_registry(tuple(three())).registry
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, create_game_character_registry(list(reversed(three()))).registry)
        self.assertNotEqual(a, create_game_character_registry(three()[:2]).registry)
        self.assertNotEqual(a, create_game_character_registry([char("hero"), char("villain"), char("mentor", role="other")]).registry)
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, a.characters)

    def test_33_to_dict_is_fresh_ordered_and_round_trips_through_the_factory(self):
        registry = create_game_character_registry(three()).registry
        d = registry.to_dict()
        self.assertEqual(list(d), ["characters"])
        self.assertEqual([c["character_id"] for c in d["characters"]], ["hero", "villain", "mentor"])
        d["characters"].append({"x": 1})
        d["characters"][0]["name"] = "hacked"
        again = registry.to_dict()
        self.assertIsNot(d, again)
        self.assertIsNot(again["characters"], registry.to_dict()["characters"])
        self.assertEqual(registry.characters[0].name, "Hero")
        rebuilt = create_game_character_registry([create_game_character(c).character for c in again["characters"]]).registry
        self.assertEqual(rebuilt, registry)

    def test_34_copy_returns_the_same_object_and_pickling_is_refused(self):
        registry = create_game_character_registry(three()).registry
        self.assertIs(copy.copy(registry), registry)
        self.assertIs(copy.deepcopy(registry), registry)
        with self.assertRaises(TypeError):
            pickle.dumps(registry)

    def test_35_registered_characters_are_the_original_immutable_objects(self):
        cs = three()
        registry = create_game_character_registry(cs).registry
        for original, stored in zip(cs, registry.characters):
            self.assertIs(original, stored)
            with self.assertRaises(AttributeError):
                stored.name = "x"


class TestBoundaries(unittest.TestCase):
    def test_36_module_imports_only_the_two_record_modules_and_has_no_io_or_state(self):
        with open(os.path.join(PY_ROOT, "game_creation", "game_character_registry.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([(n.level, n.module, [a.name for a in n.names]) for n in imports],
                         [(1, "game_character", ["GameCharacter"]), (1, "game_project_structure", ["GameProjectStructure"])])
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
                         ["__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py", "game_project_structure.py", "game_project_validator.py",
                          "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in ("game_creation/game_project.py", "game_creation/game_project_structure.py", "game_creation/game_scene.py",
                    "game_creation/game_character.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("GameCharacterRegistry", "game_character_registry", "create_game_character_registry"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "GameCharacterRegistry", "game_character_registry"):
                self.assertNotIn(token, text, (rel, token))

    def test_38_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("GameCharacterRegistry", "create_game_character_registry", "GameProjectStructure", "lookup", "does NOT", "later",
                       "unused", "character_id"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
