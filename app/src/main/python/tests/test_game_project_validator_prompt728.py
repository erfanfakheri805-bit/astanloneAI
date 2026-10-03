"""Prompt 728 - Section 7 game project validator (`game_creation.game_project_validator`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from game_creation import game_project_validator as val
from game_creation.game_asset import create_game_asset
from game_creation.game_asset_registry import create_game_asset_registry
from game_creation.game_character import create_game_character
from game_creation.game_character_registry import create_game_character_registry
from game_creation.game_project import create_game_project
from game_creation.game_project_structure import create_game_project_structure
from game_creation.game_project_validator import GameProjectValidationResult, validate_game_project
from game_creation.game_scene import create_game_scene
from game_creation.game_scene_registry import create_game_scene_registry
from game_creation.gameplay_system_registry import create_gameplay_system_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_project_validator_prompt728.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

ARG_NAMES = ("project", "structure", "scene_registry", "character_registry", "gameplay_system_registry", "asset_registry")
INVALID_CODES = (val.FAILURE_INVALID_PROJECT, val.FAILURE_INVALID_STRUCTURE, val.FAILURE_INVALID_SCENE_REGISTRY,
                 val.FAILURE_INVALID_CHARACTER_REGISTRY, val.FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY, val.FAILURE_INVALID_ASSET_REGISTRY)


def ok_of(result):
    assert result.ok, result.failures
    return result


def make_project():
    return ok_of(create_game_project({"project_id": "p1", "name": "P", "description": "", "genre": "", "target_platform": "", "version": "1"})).project


def make_structure(scenes=("s1", "s2"), characters=("c1",), systems=("combat",), assets=("a1", "a2")):
    return ok_of(create_game_project_structure({"scenes": list(scenes), "characters": list(characters), "gameplay_systems": list(systems),
                                                "assets": list(assets)})).structure


def make_scene_registry(ids=("s1", "s2")):
    return ok_of(create_game_scene_registry([ok_of(create_game_scene(
        {"scene_id": i, "name": i, "description": "", "scene_type": "level"})).scene for i in ids])).registry


def make_character_registry(ids=("c1",)):
    return ok_of(create_game_character_registry([ok_of(create_game_character(
        {"character_id": i, "name": i, "description": "", "role": "npc"})).character for i in ids])).registry


def make_system_registry(ids=("combat",)):
    return ok_of(create_gameplay_system_registry(list(ids))).registry


def make_asset_registry(ids=("a1", "a2")):
    return ok_of(create_game_asset_registry([ok_of(create_game_asset(
        {"asset_id": i, "name": i, "description": "", "asset_type": "image"})).asset for i in ids])).registry


def good_args(**over):
    args = {"project": make_project(), "structure": make_structure(), "scene_registry": make_scene_registry(),
            "character_registry": make_character_registry(), "gameplay_system_registry": make_system_registry(),
            "asset_registry": make_asset_registry()}
    args.update(over)
    return args


def run(**over):
    return validate_game_project(**good_args(**over))


class TestValid(unittest.TestCase):
    def test_1_fully_valid_project(self):
        r = run()
        self.assertTrue(r.ok)
        self.assertEqual(r.failures, [])
        self.assertEqual(r.codes(), [])
        self.assertIs(type(r), GameProjectValidationResult)
        self.assertEqual(r.to_dict(), {"ok": True, "failures": []})

    def test_2_positional_call_and_empty_everything_are_valid(self):
        self.assertTrue(validate_game_project(make_project(), make_structure(), make_scene_registry(), make_character_registry(),
                                              make_system_registry(), make_asset_registry()).ok)
        r = run(structure=make_structure((), (), (), ()), scene_registry=make_scene_registry(()), character_registry=make_character_registry(()),
                gameplay_system_registry=make_system_registry(()), asset_registry=make_asset_registry(()))
        self.assertTrue(r.ok)

    def test_3_unused_registry_entries_are_allowed(self):
        r = run(scene_registry=make_scene_registry(("s1", "s2", "extra")), character_registry=make_character_registry(("c1", "spare")),
                gameplay_system_registry=make_system_registry(("combat", "unused")), asset_registry=make_asset_registry(("a1", "a2", "a3")))
        self.assertTrue(r.ok)
        self.assertTrue(run(structure=make_structure((), (), (), ())).ok)

    def test_4_registry_and_structure_order_do_not_matter(self):
        self.assertTrue(run(structure=make_structure(("s2", "s1"), assets=("a2", "a1")),
                            scene_registry=make_scene_registry(("s1", "s2"))).ok)

    def test_5_project_identity_is_deferred_because_the_structure_has_no_project_id(self):
        self.assertFalse(hasattr(make_structure(), "project_id"))
        self.assertNotIn("project_id", make_structure().to_dict())
        other = ok_of(create_game_project({"project_id": "totally-different", "name": "X", "description": "", "genre": "",
                                           "target_platform": "", "version": "9"})).project
        self.assertTrue(run(project=other).ok)


class TestInvalidTopLevelInputs(unittest.TestCase):
    def test_6_each_invalid_input_independently(self):
        for index, name in enumerate(ARG_NAMES):
            for bad in (None, "x", 1, {}, [], object()):
                with self.subTest(arg=name, bad=type(bad).__name__):
                    r = run(**{name: bad})
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [INVALID_CODES[index]])
                    self.assertEqual(r.failures[0]["field"], name)
                    self.assertIn(name, r.failures[0]["message"])

    def test_7_wrong_but_valid_looking_objects_are_rejected(self):
        g = good_args()
        swapped = dict(g, scene_registry=g["character_registry"], character_registry=g["scene_registry"])
        self.assertEqual(validate_game_project(**swapped).codes(), [val.FAILURE_INVALID_SCENE_REGISTRY, val.FAILURE_INVALID_CHARACTER_REGISTRY])
        self.assertEqual(run(project=g["structure"]).codes(), [val.FAILURE_INVALID_PROJECT])
        self.assertEqual(run(structure=g["project"]).codes(), [val.FAILURE_INVALID_STRUCTURE])
        self.assertEqual(run(asset_registry=g["gameplay_system_registry"]).codes(), [val.FAILURE_INVALID_ASSET_REGISTRY])
        self.assertEqual(run(structure=g["structure"].to_dict()).codes(), [val.FAILURE_INVALID_STRUCTURE])

    def test_8_look_alike_classes_are_rejected(self):
        class FakeStructure:
            scenes = characters = gameplay_systems = assets = ()

        class FakeRegistry:
            scene_ids = character_ids = gameplay_system_ids = asset_ids = ()
        r = validate_game_project(make_project(), FakeStructure(), FakeRegistry(), FakeRegistry(), FakeRegistry(), FakeRegistry())
        self.assertEqual(r.codes(), list(INVALID_CODES[1:]))

    def test_9_several_invalid_inputs_are_reported_in_argument_order_without_reference_noise(self):
        r = validate_game_project(None, make_structure(("ghost",), ("ghost",), ("ghost",), ("ghost",)), None, 3, make_system_registry(()), "x")
        self.assertEqual(r.codes(), [val.FAILURE_INVALID_PROJECT, val.FAILURE_INVALID_SCENE_REGISTRY, val.FAILURE_INVALID_CHARACTER_REGISTRY,
                                     val.FAILURE_INVALID_ASSET_REGISTRY, val.FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE])
        r = validate_game_project(1, 2, 3, 4, 5, 6)
        self.assertEqual(r.codes(), list(INVALID_CODES))
        self.assertEqual([f["field"] for f in r.failures], list(ARG_NAMES))

    def test_10_invalid_structure_skips_all_reference_checks(self):
        r = run(structure=None, scene_registry=make_scene_registry(()))
        self.assertEqual(r.codes(), [val.FAILURE_INVALID_STRUCTURE])


class TestExactTypes(unittest.TestCase):
    def test_11_subclasses_of_the_real_types_are_rejected(self):
        # the real classes refuse subclassing, so a "subclass" can only be simulated with a wrapper that fakes __class__
        for name in ARG_NAMES:
            real = good_args()[name]

            class Impostor:
                __class__ = type(real)
            with self.subTest(arg=name):
                self.assertFalse(run(**{name: Impostor()}).ok)

    def test_12_the_real_classes_cannot_be_subclassed_so_exact_type_is_the_only_type(self):
        for name in ARG_NAMES:
            cls = type(good_args()[name])
            with self.subTest(cls=cls.__name__):
                with self.assertRaises(TypeError):
                    type("Sub", (cls,), {})

    def test_13_str_and_dict_subclass_inputs_are_rejected(self):
        class S(str):
            pass

        class D(dict):
            pass
        for bad in (S("p1"), D(), D(make_structure().to_dict())):
            self.assertEqual(run(project=bad).codes(), [val.FAILURE_INVALID_PROJECT])
            self.assertEqual(run(structure=bad).codes(), [val.FAILURE_INVALID_STRUCTURE])


class TestReferences(unittest.TestCase):
    def test_14_missing_scene_references(self):
        r = run(structure=make_structure(scenes=("s1", "ghost")))
        self.assertEqual(r.codes(), [val.FAILURE_MISSING_SCENE_REFERENCE])
        self.assertEqual(r.failures[0]["field"], "structure.scenes")
        self.assertIn("'ghost'", r.failures[0]["message"])
        self.assertIn("scene_registry", r.failures[0]["message"])

    def test_15_missing_character_references(self):
        r = run(structure=make_structure(characters=("c1", "ghost")))
        self.assertEqual(r.codes(), [val.FAILURE_MISSING_CHARACTER_REFERENCE])
        self.assertEqual(r.failures[0]["field"], "structure.characters")
        self.assertIn("'ghost'", r.failures[0]["message"])

    def test_16_missing_gameplay_system_references(self):
        r = run(structure=make_structure(systems=("combat", "ghost")))
        self.assertEqual(r.codes(), [val.FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE])
        self.assertEqual(r.failures[0]["field"], "structure.gameplay_systems")
        self.assertIn("'ghost'", r.failures[0]["message"])

    def test_17_missing_asset_references(self):
        r = run(structure=make_structure(assets=("a1", "ghost")))
        self.assertEqual(r.codes(), [val.FAILURE_MISSING_ASSET_REFERENCE])
        self.assertEqual(r.failures[0]["field"], "structure.assets")
        self.assertIn("'ghost'", r.failures[0]["message"])

    def test_18_multiple_missing_references_keep_structure_order_within_each_group(self):
        r = run(structure=make_structure(scenes=("z", "s1", "a"), assets=("q", "a1", "b")))
        self.assertEqual(r.codes(), [val.FAILURE_MISSING_SCENE_REFERENCE] * 2 + [val.FAILURE_MISSING_ASSET_REFERENCE] * 2)
        self.assertEqual([("'z'" in r.failures[0]["message"]), ("'a'" in r.failures[1]["message"]),
                          ("'q'" in r.failures[2]["message"]), ("'b'" in r.failures[3]["message"])], [True] * 4)

    def test_19_groups_are_ordered_scenes_characters_systems_assets(self):
        s = make_structure(("gs",), ("gc",), ("gy",), ("ga",))
        r = validate_game_project(make_project(), s, make_scene_registry(()), make_character_registry(()), make_system_registry(()),
                                  make_asset_registry(()))
        self.assertEqual(r.codes(), [val.FAILURE_MISSING_SCENE_REFERENCE, val.FAILURE_MISSING_CHARACTER_REFERENCE,
                                     val.FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE, val.FAILURE_MISSING_ASSET_REFERENCE])
        self.assertEqual([f["field"] for f in r.failures],
                         ["structure.scenes", "structure.characters", "structure.gameplay_systems", "structure.assets"])

    def test_20_invalid_inputs_come_before_reference_failures(self):
        r = validate_game_project(None, make_structure(("ghost",), ("ghost",), ("ghost",), ("ghost",)), make_scene_registry(()), None,
                                  make_system_registry(()), make_asset_registry(()))
        self.assertEqual(r.codes(), [val.FAILURE_INVALID_PROJECT, val.FAILURE_INVALID_CHARACTER_REGISTRY, val.FAILURE_MISSING_SCENE_REFERENCE,
                                     val.FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE, val.FAILURE_MISSING_ASSET_REFERENCE])

    def test_21_reference_match_is_exact(self):
        for near in ("S1", "s1 ", " s1"):
            self.assertEqual(run(structure=make_structure(scenes=(near,))).codes(), [val.FAILURE_MISSING_SCENE_REFERENCE])
        self.assertEqual(run(structure=make_structure(systems=("Combat",))).codes(), [val.FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE])

    def test_22_ids_are_checked_only_against_their_own_registry(self):
        self.assertEqual(run(structure=make_structure(scenes=("c1",))).codes(), [val.FAILURE_MISSING_SCENE_REFERENCE])
        self.assertEqual(run(structure=make_structure(assets=("s1",))).codes(), [val.FAILURE_MISSING_ASSET_REFERENCE])
        self.assertEqual(run(structure=make_structure(characters=("a1",))).codes(), [val.FAILURE_MISSING_CHARACTER_REFERENCE])


class TestPurityAndResult(unittest.TestCase):
    def test_23_no_input_is_mutated(self):
        g = good_args(structure=make_structure(scenes=("s1", "ghost")))
        before = {k: (v.to_dict() if hasattr(v, "to_dict") else v) for k, v in g.items()}
        ids = [g["scene_registry"].scene_ids, g["character_registry"].character_ids, g["gameplay_system_registry"].gameplay_system_ids,
               g["asset_registry"].asset_ids]
        validate_game_project(**g)
        validate_game_project(**g)
        self.assertEqual({k: v.to_dict() for k, v in g.items()}, before)
        self.assertEqual([g["scene_registry"].scene_ids, g["character_registry"].character_ids,
                          g["gameplay_system_registry"].gameplay_system_ids, g["asset_registry"].asset_ids], ids)

    def test_24_the_result_stores_no_caller_object(self):
        g = good_args()
        r = validate_game_project(**g)
        self.assertEqual(r._failures, ())
        r2 = validate_game_project(**dict(g, structure=make_structure(scenes=("ghost",))))
        for entry in r2._failures:
            self.assertTrue(all(type(x) is str or x is None for x in entry))

    def test_25_equal_results_have_equal_hashes_and_different_results_differ(self):
        a = run(structure=make_structure(scenes=("ghost",)))
        b = run(structure=make_structure(scenes=("ghost",)))
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, run(structure=make_structure(scenes=("other",))))
        self.assertNotEqual(a, run())
        self.assertEqual(run(), run())
        self.assertEqual(hash(run()), hash(run()))
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, a.failures)

    def test_26_to_dict_and_failures_are_fresh(self):
        r = run(structure=make_structure(scenes=("ghost",), assets=("ghost",)))
        d = r.to_dict()
        self.assertEqual(list(d), ["ok", "failures"])
        self.assertEqual(set(d["failures"][0]), {"code", "field", "message"})
        d["failures"][0]["code"] = "hacked"
        d["failures"].clear()
        f = r.failures
        f.append({"x": 1})
        f[0]["message"] = "hacked"
        self.assertEqual(r.codes(), [val.FAILURE_MISSING_SCENE_REFERENCE, val.FAILURE_MISSING_ASSET_REFERENCE])
        self.assertIsNot(r.to_dict(), r.to_dict())
        self.assertIsNot(r.failures[0], r.failures[0])
        self.assertEqual(r.to_dict(), r.to_dict())
        self.assertFalse(r.ok)

    def test_27_result_is_immutable(self):
        r = run()
        for name in ("ok", "failures", "_failures", "extra"):
            with self.assertRaises(AttributeError):
                setattr(r, name, ())
        for name in ("failures", "_failures"):
            with self.assertRaises(AttributeError):
                delattr(r, name)
        self.assertFalse(hasattr(r, "__dict__"))
        self.assertIs(type(r._failures), tuple)

    def test_28_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            GameProjectValidationResult(object(), [])
        with self.assertRaises(TypeError):
            GameProjectValidationResult(None, [])
        with self.assertRaises(TypeError):
            class Sub(GameProjectValidationResult):
                pass

    def test_29_copy_returns_the_same_object_and_pickling_is_refused(self):
        r = run(structure=make_structure(scenes=("ghost",)))
        self.assertIs(copy.copy(r), r)
        self.assertIs(copy.deepcopy(r), r)
        with self.assertRaises(TypeError):
            pickle.dumps(r)

    def test_30_function_never_raises_and_is_deterministic(self):
        class Boom:
            def __getattr__(self, name):
                raise RuntimeError("must not touch")

            def __eq__(self, other):
                raise RuntimeError("must not compare")
            __hash__ = None
        junk = (None, Boom(), 0, "", [], {}, (1,), object())
        for args in ((junk[0],) * 6, (junk[1],) * 6, junk[:6], junk[2:], (junk[1], junk[2], junk[3], junk[4], junk[5], junk[6])):
            r1, r2 = validate_game_project(*args), validate_game_project(*args)
            self.assertFalse(r1.ok)
            self.assertEqual(r1, r2)
            self.assertEqual(r1.to_dict(), r2.to_dict())
            for f in r1.failures:
                self.assertIn(f["code"], val.FAILURE_CODES)
                self.assertEqual(set(f), {"code", "field", "message"})

    def test_31_wrong_argument_count_is_a_plain_type_error_not_a_validation_result(self):
        with self.assertRaises(TypeError):
            validate_game_project(make_project())

    def test_32_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(len(set(val.FAILURE_CODES)), len(val.FAILURE_CODES))
        self.assertTrue(all(c.startswith("GAME_PROJECT_VALIDATION_") for c in val.FAILURE_CODES))
        self.assertEqual(val.FAILURE_CODES, tuple("GAME_PROJECT_VALIDATION_" + s for s in (
            "INVALID_PROJECT", "INVALID_STRUCTURE", "INVALID_SCENE_REGISTRY", "INVALID_CHARACTER_REGISTRY", "INVALID_GAMEPLAY_SYSTEM_REGISTRY",
            "INVALID_ASSET_REGISTRY", "MISSING_SCENE_REFERENCE", "MISSING_CHARACTER_REFERENCE", "MISSING_GAMEPLAY_SYSTEM_REFERENCE",
            "MISSING_ASSET_REFERENCE")))


class TestBoundaries(unittest.TestCase):
    def test_33_module_imports_only_section7_modules_with_relative_imports_and_has_no_io_or_state(self):
        with open(os.path.join(PY_ROOT, "game_creation", "game_project_validator.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual(sorted((n.module, tuple(a.name for a in n.names)) for n in imports), [
            ("game_asset_registry", ("GameAssetRegistry",)), ("game_character_registry", ("GameCharacterRegistry",)),
            ("game_project", ("GameProject",)), ("game_project_structure", ("GameProjectStructure",)),
            ("game_scene_registry", ("GameSceneRegistry",)), ("gameplay_system_registry", ("GameplaySystemRegistry",))])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(val).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_34_earlier_section7_modules_are_untouched_and_unaware_of_the_validator(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py",
            "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in ("game_project.py", "game_project_structure.py", "game_scene.py", "game_character.py", "game_asset.py",
                    "game_scene_registry.py", "game_character_registry.py", "gameplay_system_registry.py", "game_asset_registry.py"):
            with open(os.path.join(PY_ROOT, "game_creation", rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_project_validator", "validate_game_project", "GameProjectValidationResult"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "game_project_validator", "validate_game_project"):
                self.assertNotIn(token, text, (rel, token))

    def test_35_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("validate_game_project", "GameProjectValidationResult", "GAME_PROJECT_VALIDATION_", "deferred", "project_id", "does NOT",
                       "unused", "later"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
