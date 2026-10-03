"""Prompt 730 - Section 7 game scene composition validator (`game_creation.game_scene_composition_validator`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from game_creation import game_scene_composition_validator as val
from game_creation.game_asset import create_game_asset
from game_creation.game_asset_registry import GameAssetRegistry, create_game_asset_registry
from game_creation.game_character import create_game_character
from game_creation.game_character_registry import GameCharacterRegistry, create_game_character_registry
from game_creation.game_scene import create_game_scene
from game_creation.game_scene_composition import create_game_scene_composition
from game_creation.game_scene_composition_validator import GameSceneCompositionValidationResult, validate_game_scene_composition
from game_creation.gameplay_system_registry import GameplaySystemRegistry, create_gameplay_system_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_scene_composition_validator_prompt730.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

ARG_NAMES = ("composition", "scene", "character_registry", "asset_registry", "gameplay_system_registry")
INVALID_CODES = (val.FAILURE_INVALID_COMPOSITION, val.FAILURE_INVALID_SCENE, val.FAILURE_INVALID_CHARACTER_REGISTRY,
                 val.FAILURE_INVALID_ASSET_REGISTRY, val.FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY)


def ok_of(result):
    assert result.ok, result.failures
    return result


def make_composition(scene_id="s1", characters=("c1",), assets=("a1", "a2"), systems=("combat",)):
    return ok_of(create_game_scene_composition({"scene_id": scene_id, "character_ids": list(characters), "asset_ids": list(assets),
                                                "gameplay_system_ids": list(systems)})).composition


def make_scene(scene_id="s1"):
    return ok_of(create_game_scene({"scene_id": scene_id, "name": "Scene", "description": "", "scene_type": "level"})).scene


def make_character_registry(ids=("c1",)):
    return ok_of(create_game_character_registry([ok_of(create_game_character(
        {"character_id": i, "name": i, "description": "", "role": "npc"})).character for i in ids])).registry


def make_asset_registry(ids=("a1", "a2")):
    return ok_of(create_game_asset_registry([ok_of(create_game_asset(
        {"asset_id": i, "name": i, "description": "", "asset_type": "image"})).asset for i in ids])).registry


def make_system_registry(ids=("combat",)):
    return ok_of(create_gameplay_system_registry(list(ids))).registry


def good_args(**over):
    args = {"composition": make_composition(), "scene": make_scene(), "character_registry": make_character_registry(),
            "asset_registry": make_asset_registry(), "gameplay_system_registry": make_system_registry()}
    args.update(over)
    return args


def run(**over):
    return validate_game_scene_composition(**good_args(**over))


class TestValid(unittest.TestCase):
    def test_1_fully_valid_composition(self):
        r = run()
        self.assertTrue(r.ok)
        self.assertEqual(r.failures, [])
        self.assertEqual(r.codes(), [])
        self.assertIs(type(r), GameSceneCompositionValidationResult)
        self.assertEqual(r.to_dict(), {"ok": True, "failures": []})

    def test_2_positional_call_and_empty_composition_are_valid(self):
        self.assertTrue(validate_game_scene_composition(make_composition(), make_scene(), make_character_registry(), make_asset_registry(),
                                                        make_system_registry()).ok)
        r = run(composition=make_composition(characters=(), assets=(), systems=()), character_registry=make_character_registry(()),
                asset_registry=make_asset_registry(()), gameplay_system_registry=make_system_registry(()))
        self.assertTrue(r.ok)

    def test_3_matching_scene_id(self):
        self.assertTrue(run(composition=make_composition(scene_id="level-7"), scene=make_scene("level-7")).ok)

    def test_4_valid_character_asset_and_gameplay_references(self):
        r = run(composition=make_composition(characters=("c1", "c2"), assets=("a2", "a1"), systems=("combat", "dialogue")),
                character_registry=make_character_registry(("c2", "c1")), asset_registry=make_asset_registry(("a1", "a2")),
                gameplay_system_registry=make_system_registry(("dialogue", "combat")))
        self.assertTrue(r.ok)

    def test_5_unused_registry_entries_are_accepted(self):
        r = run(character_registry=make_character_registry(("c1", "spare")), asset_registry=make_asset_registry(("a1", "a2", "a3")),
                gameplay_system_registry=make_system_registry(("combat", "unused")))
        self.assertTrue(r.ok)
        self.assertTrue(run(composition=make_composition(characters=(), assets=(), systems=())).ok)


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
        self.assertEqual(run(composition=g["scene"]).codes(), [val.FAILURE_INVALID_COMPOSITION])
        self.assertEqual(run(scene=g["composition"]).codes(), [val.FAILURE_INVALID_SCENE])
        self.assertEqual(run(composition=g["composition"].to_dict()).codes(), [val.FAILURE_INVALID_COMPOSITION])
        self.assertEqual(run(scene=g["scene"].to_dict()).codes(), [val.FAILURE_INVALID_SCENE])
        swapped = dict(g, character_registry=g["asset_registry"], asset_registry=g["character_registry"])
        self.assertEqual(validate_game_scene_composition(**swapped).codes(),
                         [val.FAILURE_INVALID_CHARACTER_REGISTRY, val.FAILURE_INVALID_ASSET_REGISTRY])
        self.assertEqual(run(gameplay_system_registry=g["asset_registry"]).codes(), [val.FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY])

    def test_8_look_alike_classes_are_rejected(self):
        class FakeComposition:
            scene_id = "s1"
            character_ids = asset_ids = gameplay_system_ids = ()

        class FakeScene:
            scene_id = "s1"

        class FakeRegistry:
            def lookup(self, _id):
                raise RuntimeError("must not be called")
        r = validate_game_scene_composition(FakeComposition(), FakeScene(), FakeRegistry(), FakeRegistry(), FakeRegistry())
        self.assertEqual(r.codes(), list(INVALID_CODES))

    def test_9_several_invalid_inputs_are_reported_in_argument_order_without_reference_noise(self):
        r = validate_game_scene_composition(make_composition("other", ("ghost",), ("ghost",), ("ghost",)), None, 3, make_asset_registry(()), "x")
        self.assertEqual(r.codes(), [val.FAILURE_INVALID_SCENE, val.FAILURE_INVALID_CHARACTER_REGISTRY,
                                     val.FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY, val.FAILURE_ASSET_NOT_FOUND])
        r = validate_game_scene_composition(1, 2, 3, 4, 5)
        self.assertEqual(r.codes(), list(INVALID_CODES))
        self.assertEqual([f["field"] for f in r.failures], list(ARG_NAMES))

    def test_10_invalid_composition_skips_scene_and_reference_checks(self):
        r = run(composition=None, scene=make_scene("anything"), character_registry=make_character_registry(()))
        self.assertEqual(r.codes(), [val.FAILURE_INVALID_COMPOSITION])

    def test_11_invalid_scene_skips_only_the_scene_id_check(self):
        r = run(composition=make_composition(characters=("ghost",)), scene=None)
        self.assertEqual(r.codes(), [val.FAILURE_INVALID_SCENE, val.FAILURE_CHARACTER_NOT_FOUND])

    def test_12_invalid_registry_skips_only_its_own_group(self):
        r = run(composition=make_composition(characters=("ghost",), assets=("ghost",), systems=("ghost",)), asset_registry=None)
        self.assertEqual(r.codes(), [val.FAILURE_INVALID_ASSET_REGISTRY, val.FAILURE_CHARACTER_NOT_FOUND,
                                     val.FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND])

    def test_13_str_and_dict_subclass_inputs_are_rejected(self):
        class S(str):
            pass

        class D(dict):
            pass
        for bad in (S("s1"), D(), D(make_composition().to_dict())):
            self.assertEqual(run(composition=bad).codes(), [val.FAILURE_INVALID_COMPOSITION])
            self.assertEqual(run(scene=bad).codes(), [val.FAILURE_INVALID_SCENE])

    def test_14_the_real_classes_cannot_be_subclassed_so_exact_type_is_the_only_type(self):
        for name in ARG_NAMES:
            cls = type(good_args()[name])
            with self.subTest(cls=cls.__name__):
                with self.assertRaises(TypeError):
                    type("Sub", (cls,), {})


class TestSceneId(unittest.TestCase):
    def test_15_scene_id_mismatch(self):
        r = run(scene=make_scene("s2"))
        self.assertEqual(r.codes(), [val.FAILURE_SCENE_ID_MISMATCH])
        self.assertEqual(r.failures[0]["field"], "composition.scene_id")
        self.assertIn("'s1'", r.failures[0]["message"])
        self.assertIn("'s2'", r.failures[0]["message"])

    def test_16_scene_id_match_is_exact(self):
        for near in ("S1", "s1 ", " s1", "s 1"):
            self.assertEqual(run(scene=make_scene(near)).codes(), [val.FAILURE_SCENE_ID_MISMATCH], near)


class TestReferences(unittest.TestCase):
    def test_17_missing_character_reference(self):
        r = run(composition=make_composition(characters=("c1", "ghost")))
        self.assertEqual(r.codes(), [val.FAILURE_CHARACTER_NOT_FOUND])
        self.assertEqual(r.failures[0]["field"], "composition.character_ids")
        self.assertIn("'ghost'", r.failures[0]["message"])
        self.assertIn("character_registry", r.failures[0]["message"])

    def test_18_missing_asset_reference(self):
        r = run(composition=make_composition(assets=("a1", "ghost")))
        self.assertEqual(r.codes(), [val.FAILURE_ASSET_NOT_FOUND])
        self.assertEqual(r.failures[0]["field"], "composition.asset_ids")
        self.assertIn("'ghost'", r.failures[0]["message"])

    def test_19_missing_gameplay_system_reference(self):
        r = run(composition=make_composition(systems=("combat", "ghost")))
        self.assertEqual(r.codes(), [val.FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND])
        self.assertEqual(r.failures[0]["field"], "composition.gameplay_system_ids")
        self.assertIn("'ghost'", r.failures[0]["message"])

    def test_20_multiple_missing_references_keep_composition_order_within_each_group(self):
        r = run(composition=make_composition(characters=("z", "c1", "a"), assets=("q", "a1", "b"), systems=("y", "combat", "x")))
        self.assertEqual(r.codes(), [val.FAILURE_CHARACTER_NOT_FOUND] * 2 + [val.FAILURE_ASSET_NOT_FOUND] * 2 +
                         [val.FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND] * 2)
        order = ["'z'", "'a'", "'q'", "'b'", "'y'", "'x'"]
        self.assertEqual([order[i] in r.failures[i]["message"] for i in range(6)], [True] * 6)

    def test_21_exact_full_ordering_of_every_failure_kind(self):
        r = validate_game_scene_composition(make_composition("s1", ("gc",), ("ga",), ("gy",)), None, make_character_registry(()), None,
                                            make_system_registry(()))
        self.assertEqual(r.codes(), [val.FAILURE_INVALID_SCENE, val.FAILURE_INVALID_ASSET_REGISTRY, val.FAILURE_CHARACTER_NOT_FOUND,
                                     val.FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND])
        r = validate_game_scene_composition(make_composition("s1", ("gc",), ("ga",), ("gy",)), make_scene("s2"), make_character_registry(()),
                                            make_asset_registry(()), make_system_registry(()))
        self.assertEqual(r.codes(), [val.FAILURE_SCENE_ID_MISMATCH, val.FAILURE_CHARACTER_NOT_FOUND, val.FAILURE_ASSET_NOT_FOUND,
                                     val.FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND])
        self.assertEqual([f["field"] for f in r.failures], ["composition.scene_id", "composition.character_ids", "composition.asset_ids",
                                                            "composition.gameplay_system_ids"])
        r = validate_game_scene_composition(None, "x", None, 2, [])
        self.assertEqual(r.codes(), list(INVALID_CODES))

    def test_22_invalid_inputs_come_before_scene_and_reference_failures(self):
        r = validate_game_scene_composition(make_composition("s1", ("gc",), ("ga",), ("gy",)), make_scene("s2"), None, make_asset_registry(()), None)
        self.assertEqual(r.codes(), [val.FAILURE_INVALID_CHARACTER_REGISTRY, val.FAILURE_INVALID_GAMEPLAY_SYSTEM_REGISTRY,
                                     val.FAILURE_SCENE_ID_MISMATCH, val.FAILURE_ASSET_NOT_FOUND])

    def test_23_reference_match_is_exact(self):
        for near in ("C1", "c1 ", " c1"):
            self.assertEqual(run(composition=make_composition(characters=(near,))).codes(), [val.FAILURE_CHARACTER_NOT_FOUND], near)
        self.assertEqual(run(composition=make_composition(systems=("Combat",))).codes(), [val.FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND])
        self.assertEqual(run(composition=make_composition(assets=("A1",))).codes(), [val.FAILURE_ASSET_NOT_FOUND])

    def test_24_ids_are_checked_only_against_their_own_registry(self):
        self.assertEqual(run(composition=make_composition(characters=("a1",))).codes(), [val.FAILURE_CHARACTER_NOT_FOUND])
        self.assertEqual(run(composition=make_composition(assets=("c1",))).codes(), [val.FAILURE_ASSET_NOT_FOUND])
        self.assertEqual(run(composition=make_composition(systems=("c1",))).codes(), [val.FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND])

    def test_25_same_id_in_two_collections_is_checked_in_each_registry(self):
        r = run(composition=make_composition(characters=("x",), assets=("x",), systems=("x",)), character_registry=make_character_registry(("x",)),
                asset_registry=make_asset_registry(("x",)), gameplay_system_registry=make_system_registry(("x",)))
        self.assertTrue(r.ok)
        r = run(composition=make_composition(characters=("x",), assets=("x",), systems=("x",)), character_registry=make_character_registry(("x",)),
                asset_registry=make_asset_registry(()), gameplay_system_registry=make_system_registry(()))
        self.assertEqual(r.codes(), [val.FAILURE_ASSET_NOT_FOUND, val.FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND])


class TestRegistryLookupApis(unittest.TestCase):
    def test_26_validator_asks_each_registry_lookup_in_composition_order(self):
        comp = make_composition(characters=("c1", "c9"), assets=("a2", "a1"), systems=("combat", "zz"))
        seen = {"c": [], "a": [], "g": []}
        real = {"c": GameCharacterRegistry.lookup, "a": GameAssetRegistry.lookup, "g": GameplaySystemRegistry.lookup}

        def spy(key):
            def inner(self, item):
                seen[key].append(item)
                return real[key](self, item)
            return inner
        with mock.patch.object(GameCharacterRegistry, "lookup", spy("c")), mock.patch.object(GameAssetRegistry, "lookup", spy("a")), \
                mock.patch.object(GameplaySystemRegistry, "lookup", spy("g")):
            r = run(composition=comp)
        self.assertEqual(seen, {"c": ["c1", "c9"], "a": ["a2", "a1"], "g": ["combat", "zz"]})
        self.assertEqual(r.codes(), [val.FAILURE_CHARACTER_NOT_FOUND, val.FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND])

    def test_27_the_lookup_verdict_alone_decides_found_or_missing(self):
        class Found:
            found = True

        class Missing:
            found = False
        comp = make_composition()
        with mock.patch.object(GameCharacterRegistry, "lookup", lambda self, i: Missing()), \
                mock.patch.object(GameAssetRegistry, "lookup", lambda self, i: Missing()), \
                mock.patch.object(GameplaySystemRegistry, "lookup", lambda self, i: Missing()):
            r = run(composition=comp)
        self.assertEqual(r.codes(), [val.FAILURE_CHARACTER_NOT_FOUND] + [val.FAILURE_ASSET_NOT_FOUND] * 2 + [val.FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND])
        with mock.patch.object(GameCharacterRegistry, "lookup", lambda self, i: Found()), \
                mock.patch.object(GameAssetRegistry, "lookup", lambda self, i: Found()), \
                mock.patch.object(GameplaySystemRegistry, "lookup", lambda self, i: Found()):
            r = run(composition=make_composition(characters=("ghost",), assets=("ghost",), systems=("ghost",)))
        self.assertTrue(r.ok)

    def test_28_source_uses_lookup_and_never_reads_registry_internals(self):
        with open(os.path.join(PY_ROOT, "game_creation", "game_scene_composition_validator.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertIn("lookup", attrs)
        self.assertIn("found", attrs)
        for internal in ("_characters", "_assets", "_ids", "characters", "assets", "scene_ids", "asset_ids_registry"):
            self.assertNotIn(internal, attrs, internal)
        lookup_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "lookup"]
        self.assertEqual(len(lookup_calls), 1)
        # the composition's own id tuples are read, but never membership-tested against a registry id list
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
                # the only membership tests allowed are on the validator's own dict of already-validated arguments
                self.assertTrue(all(isinstance(c, ast.Name) and c.id == "valid" for c in node.comparators), ast.unparse(node))


class TestPurityAndResult(unittest.TestCase):
    def test_29_no_input_is_mutated(self):
        g = good_args(composition=make_composition(characters=("c1", "ghost")), scene=make_scene("other"))
        before = {k: v.to_dict() for k, v in g.items()}
        ids = [g["composition"].character_ids, g["composition"].asset_ids, g["composition"].gameplay_system_ids,
               g["character_registry"].character_ids, g["asset_registry"].asset_ids, g["gameplay_system_registry"].gameplay_system_ids]
        validate_game_scene_composition(**g)
        validate_game_scene_composition(**g)
        self.assertEqual({k: v.to_dict() for k, v in g.items()}, before)
        self.assertEqual([g["composition"].character_ids, g["composition"].asset_ids, g["composition"].gameplay_system_ids,
                          g["character_registry"].character_ids, g["asset_registry"].asset_ids,
                          g["gameplay_system_registry"].gameplay_system_ids], ids)

    def test_30_the_result_stores_no_caller_object(self):
        r = validate_game_scene_composition(**good_args())
        self.assertEqual(r._failures, ())
        r2 = run(composition=make_composition(characters=("ghost",)), scene=make_scene("x"))
        for entry in r2._failures:
            self.assertTrue(all(type(x) is str for x in entry))

    def test_31_equal_results_have_equal_hashes_and_different_results_differ(self):
        a = run(composition=make_composition(characters=("ghost",)))
        b = run(composition=make_composition(characters=("ghost",)))
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, run(composition=make_composition(characters=("other",))))
        self.assertNotEqual(a, run())
        self.assertEqual(run(), run())
        self.assertEqual(hash(run()), hash(run()))
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, a.failures)

    def test_32_to_dict_and_failures_are_fresh(self):
        r = run(composition=make_composition(characters=("ghost",), assets=("ghost",)))
        d = r.to_dict()
        self.assertEqual(list(d), ["ok", "failures"])
        self.assertEqual(set(d["failures"][0]), {"code", "field", "message"})
        d["failures"][0]["code"] = "hacked"
        d["failures"].clear()
        f = r.failures
        f.append({"x": 1})
        f[0]["message"] = "hacked"
        self.assertEqual(r.codes(), [val.FAILURE_CHARACTER_NOT_FOUND, val.FAILURE_ASSET_NOT_FOUND])
        self.assertIsNot(r.to_dict(), r.to_dict())
        self.assertIsNot(r.failures[0], r.failures[0])
        self.assertEqual(r.to_dict(), r.to_dict())
        self.assertFalse(r.ok)

    def test_33_result_is_immutable(self):
        r = run()
        for name in ("ok", "failures", "_failures", "extra"):
            with self.assertRaises(AttributeError):
                setattr(r, name, ())
        for name in ("failures", "_failures"):
            with self.assertRaises(AttributeError):
                delattr(r, name)
        self.assertFalse(hasattr(r, "__dict__"))
        self.assertIs(type(r._failures), tuple)

    def test_34_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            GameSceneCompositionValidationResult(object(), [])
        with self.assertRaises(TypeError):
            GameSceneCompositionValidationResult(None, [])
        with self.assertRaises(TypeError):
            class Sub(GameSceneCompositionValidationResult):
                pass

    def test_35_copy_returns_the_same_object_and_pickling_is_refused(self):
        r = run(composition=make_composition(characters=("ghost",)))
        self.assertIs(copy.copy(r), r)
        self.assertIs(copy.deepcopy(r), r)
        for proto in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(r, proto)

    def test_36_function_never_raises_for_invalid_top_level_inputs_and_is_deterministic(self):
        class Boom:
            def __getattr__(self, name):
                raise RuntimeError("must not touch")

            def __eq__(self, other):
                raise RuntimeError("must not compare")
            __hash__ = None
        junk = (None, Boom(), 0, "", [], {}, (1,), object())
        for args in ((junk[0],) * 5, (junk[1],) * 5, junk[:5], junk[3:], (junk[1], junk[2], junk[3], junk[4], junk[5])):
            r1, r2 = validate_game_scene_composition(*args), validate_game_scene_composition(*args)
            self.assertFalse(r1.ok)
            self.assertEqual(r1, r2)
            self.assertEqual(r1.to_dict(), r2.to_dict())
            self.assertEqual(r1.codes(), list(INVALID_CODES))
            for f in r1.failures:
                self.assertIn(f["code"], val.FAILURE_CODES)
                self.assertEqual(set(f), {"code", "field", "message"})

    def test_37_wrong_argument_count_is_a_plain_type_error_not_a_validation_result(self):
        with self.assertRaises(TypeError):
            validate_game_scene_composition(make_composition())

    def test_38_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(len(set(val.FAILURE_CODES)), len(val.FAILURE_CODES))
        self.assertTrue(all(c.startswith("GAME_SCENE_COMPOSITION_VALIDATION_") for c in val.FAILURE_CODES))
        self.assertEqual(val.FAILURE_CODES, tuple("GAME_SCENE_COMPOSITION_VALIDATION_" + s for s in (
            "INVALID_COMPOSITION", "INVALID_SCENE", "INVALID_CHARACTER_REGISTRY", "INVALID_ASSET_REGISTRY",
            "INVALID_GAMEPLAY_SYSTEM_REGISTRY", "SCENE_ID_MISMATCH", "CHARACTER_NOT_FOUND", "ASSET_NOT_FOUND", "GAMEPLAY_SYSTEM_NOT_FOUND")))


class TestBoundaries(unittest.TestCase):
    def test_39_module_imports_only_section7_modules_with_relative_imports_and_has_no_io_or_state(self):
        with open(os.path.join(PY_ROOT, "game_creation", "game_scene_composition_validator.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual(sorted((n.module, tuple(a.name for a in n.names)) for n in imports), [
            ("game_asset_registry", ("GameAssetRegistry",)), ("game_character_registry", ("GameCharacterRegistry",)),
            ("game_scene", ("GameScene",)), ("game_scene_composition", ("GameSceneComposition",)),
            ("gameplay_system_registry", ("GameplaySystemRegistry",))])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(val).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_40_earlier_section7_modules_are_untouched_and_unaware_of_the_validator(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py",
            "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py",
            "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in ("game_project.py", "game_project_structure.py", "game_scene.py", "game_character.py", "game_asset.py",
                    "game_scene_registry.py", "game_character_registry.py", "gameplay_system_registry.py", "game_asset_registry.py",
                    "game_scene_composition.py", "game_project_validator.py"):
            with open(os.path.join(PY_ROOT, "game_creation", rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_scene_composition_validator", "validate_game_scene_composition", "GameSceneCompositionValidationResult"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "game_scene_composition_validator", "validate_game_scene_composition"):
                self.assertNotIn(token, text, (rel, token))

    def test_41_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("validate_game_scene_composition", "GameSceneCompositionValidationResult", "GAME_SCENE_COMPOSITION_VALIDATION_",
                       "lookup", "does NOT", "unused", "Prompt 731"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
