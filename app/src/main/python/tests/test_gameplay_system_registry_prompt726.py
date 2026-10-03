"""Prompt 726 - Section 7 gameplay system registry (`game_creation.gameplay_system_registry`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from game_creation import gameplay_system_registry as reg
from game_creation.game_project_structure import create_game_project_structure
from game_creation.gameplay_system_registry import GameplaySystemRegistry, create_gameplay_system_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_gameplay_system_registry_prompt726.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def structure(systems=(), **over):
    data = {"scenes": [], "characters": [], "gameplay_systems": list(systems), "assets": []}
    data.update(over)
    r = create_game_project_structure(data)
    assert r.ok
    return r.structure


def three():
    return ["combat", "dialogue", "crafting"]


class TestValidCreation(unittest.TestCase):
    def test_1_valid_registry_from_a_list_and_a_tuple(self):
        for source in (three(), tuple(three())):
            r = create_gameplay_system_registry(source)
            self.assertTrue(r.ok)
            self.assertEqual((r.failures, r.codes()), ([], []))
            self.assertIs(type(r.registry), GameplaySystemRegistry)
            self.assertEqual(r.registry.gameplay_system_ids, tuple(three()))

    def test_2_empty_collection_is_valid(self):
        for empty in ([], ()):
            r = create_gameplay_system_registry(empty)
            self.assertTrue(r.ok)
            self.assertEqual(r.registry.gameplay_system_ids, ())
            self.assertEqual(r.registry.to_dict(), {"gameplay_systems": []})

    def test_3_input_order_is_preserved_not_sorted(self):
        r = create_gameplay_system_registry(["zed", "amy", "mid"])
        self.assertEqual(r.registry.gameplay_system_ids, ("zed", "amy", "mid"))
        self.assertEqual(r.registry.to_dict()["gameplay_systems"], ["zed", "amy", "mid"])

    def test_4_caller_list_mutation_does_not_reach_the_registry(self):
        source = three()
        r = create_gameplay_system_registry(source)
        source.append("late")
        source.pop(0)
        self.assertEqual(r.registry.gameplay_system_ids, tuple(three()))
        self.assertEqual(create_gameplay_system_registry(source).registry.gameplay_system_ids, ("dialogue", "crafting", "late"))

    def test_5_ids_are_not_trimmed_or_case_folded(self):
        r = create_gameplay_system_registry(["Combat", "combat", " combat", "combat "])
        self.assertTrue(r.ok)
        self.assertEqual(r.registry.gameplay_system_ids, ("Combat", "combat", " combat", "combat "))


class TestLookup(unittest.TestCase):
    def test_6_exact_id_lookup_finds_the_id(self):
        registry = create_gameplay_system_registry(three()).registry
        for sid in three():
            res = registry.lookup(sid)
            self.assertTrue(res.found)
            self.assertIsNone(res.code)
            self.assertEqual(res.system_id, sid)
            self.assertEqual(res.to_dict(), {"found": True, "system_id": sid, "code": None})

    def test_7_missing_and_non_string_ids_return_stable_not_found_and_never_raise(self):
        registry = create_gameplay_system_registry(three()).registry

        class S(str):
            pass
        for bad in ("ghost", "", "Combat", "combat ", " combat", None, 1, b"combat", ["combat"], S("combat"), object()):
            with self.subTest(bad=repr(bad)):
                res = registry.lookup(bad)
                self.assertFalse(res.found)
                self.assertIsNone(res.system_id)
                self.assertEqual(res.code, reg.FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND)
                self.assertEqual(res.to_dict(), {"found": False, "system_id": None, "code": reg.FAILURE_GAMEPLAY_SYSTEM_NOT_FOUND})

    def test_8_lookup_on_an_empty_registry_and_lookup_does_not_change_the_registry(self):
        self.assertFalse(create_gameplay_system_registry([]).registry.lookup("combat").found)
        registry = create_gameplay_system_registry(three()).registry
        before = registry.to_dict()
        registry.lookup("combat")
        registry.lookup("ghost")
        self.assertEqual(registry.to_dict(), before)


class TestInvalidInput(unittest.TestCase):
    def test_9_duplicate_ids_are_rejected(self):
        r = create_gameplay_system_registry(["combat", "dialogue", "combat"])
        self.assertFalse(r.ok)
        self.assertIsNone(r.registry)
        self.assertEqual(r.codes(), [reg.FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID])
        self.assertEqual(r.failures[0]["field"], "gameplay_systems")
        self.assertIn("gameplay_systems[2]", r.failures[0]["message"])
        self.assertEqual(create_gameplay_system_registry(["a", "a", "a"]).codes(), [reg.FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID] * 2)

    def test_10_invalid_collection_types_are_rejected_not_coerced(self):
        class L(list):
            pass
        bads = [None, "combat", b"x", 1, True, {"combat"}, frozenset(["combat"]), {"combat": 1}, iter(three()), (c for c in three()), L(three())]
        for bad in bads:
            with self.subTest(bad=type(bad).__name__):
                r = create_gameplay_system_registry(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.registry)
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_COLLECTION])
                self.assertEqual(r.failures[0]["field"], "gameplay_systems")

    def test_11_invalid_item_types_are_rejected(self):
        class S(str):
            pass
        for bad in (None, 1, True, b"combat", ["combat"], ("combat",), {"id": "combat"}, object(), S("combat")):
            with self.subTest(bad=type(bad).__name__):
                r = create_gameplay_system_registry(["dialogue", bad])
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_GAMEPLAY_SYSTEM])
                self.assertIn("gameplay_systems[1]", r.failures[0]["message"])

    def test_12_blank_string_ids_are_rejected(self):
        for bad in ("", " ", "   ", "\t", "\n", " \t\n "):
            with self.subTest(bad=repr(bad)):
                r = create_gameplay_system_registry(["combat", bad])
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_GAMEPLAY_SYSTEM])
                self.assertIn("blank", r.failures[0]["message"])

    def test_13_every_collection_problem_is_reported_in_position_order(self):
        r = create_gameplay_system_registry([1, "a", "a", "", None, "b"])
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_GAMEPLAY_SYSTEM, reg.FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID,
                                     reg.FAILURE_INVALID_GAMEPLAY_SYSTEM, reg.FAILURE_INVALID_GAMEPLAY_SYSTEM])
        self.assertEqual([("[%d]" % i) in f["message"] for i, f in zip((0, 2, 3, 4), r.failures)], [True] * 4)

    def test_14_a_rejected_item_does_not_count_as_registered_for_the_structure_check(self):
        r = create_gameplay_system_registry(["combat", "combat", ""], structure(["combat", "dialogue"]))
        self.assertEqual(r.codes(), [reg.FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID, reg.FAILURE_INVALID_GAMEPLAY_SYSTEM,
                                     reg.FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE])
        self.assertIn("'dialogue'", r.failures[2]["message"])


class TestStructureValidation(unittest.TestCase):
    def test_15_structure_none_means_no_reference_check(self):
        self.assertTrue(create_gameplay_system_registry(three(), None).ok)
        self.assertTrue(create_gameplay_system_registry(three()).ok)

    def test_16_structure_whose_systems_are_all_registered_is_accepted_in_registry_order(self):
        r = create_gameplay_system_registry(three(), structure(["crafting", "combat"]))
        self.assertTrue(r.ok)
        self.assertEqual(r.registry.gameplay_system_ids, tuple(three()))

    def test_17_missing_structure_references_are_reported_in_structure_order(self):
        r = create_gameplay_system_registry(three(), structure(["zed", "combat", "amy"]))
        self.assertFalse(r.ok)
        self.assertIsNone(r.registry)
        self.assertEqual(r.codes(), [reg.FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE] * 2)
        self.assertEqual([f["field"] for f in r.failures], ["structure", "structure"])
        self.assertIn("'zed'", r.failures[0]["message"])
        self.assertIn("'amy'", r.failures[1]["message"])

    def test_18_unused_registered_ids_are_allowed(self):
        self.assertTrue(create_gameplay_system_registry(three(), structure(["combat"])).ok)
        self.assertTrue(create_gameplay_system_registry(three(), structure([])).ok)

    def test_19_structure_with_systems_needs_registry_entries_even_when_empty(self):
        self.assertEqual(create_gameplay_system_registry([], structure(["combat"])).codes(), [reg.FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE])
        self.assertTrue(create_gameplay_system_registry([], structure([])).ok)

    def test_20_reference_match_is_exact(self):
        for near in ("Combat", "combat ", " combat"):
            self.assertEqual(create_gameplay_system_registry(three(), structure([near])).codes(),
                             [reg.FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE])

    def test_21_only_the_gameplay_systems_collection_of_the_structure_is_checked(self):
        s = structure(["combat"], scenes=["s1"], characters=["c1"], assets=["a1"])
        self.assertTrue(create_gameplay_system_registry(three(), s).ok)

    def test_22_invalid_structure_values_are_rejected(self):
        good = structure(["combat"]).to_dict()

        class Fake:
            gameplay_systems = ("combat",)
        for bad in ("combat", 1, [], ["combat"], {}, good, object(), Fake(), True, 0, ""):
            with self.subTest(bad=type(bad).__name__):
                r = create_gameplay_system_registry(three(), bad)
                self.assertFalse(r.ok)
                self.assertEqual(r.codes(), [reg.FAILURE_INVALID_STRUCTURE])
                self.assertEqual(r.failures[0]["field"], "structure")

    def test_23_collection_and_structure_problems_are_reported_together_in_fixed_order(self):
        self.assertEqual(create_gameplay_system_registry("nope", 5).codes(), [reg.FAILURE_INVALID_COLLECTION, reg.FAILURE_INVALID_STRUCTURE])
        r = create_gameplay_system_registry(["a", "a", 3], structure(["a", "ghost"]))
        self.assertEqual(r.codes(), [reg.FAILURE_DUPLICATE_GAMEPLAY_SYSTEM_ID, reg.FAILURE_INVALID_GAMEPLAY_SYSTEM,
                                     reg.FAILURE_MISSING_GAMEPLAY_SYSTEM_REFERENCE])
        self.assertIn("'ghost'", r.failures[2]["message"])

    def test_24_structure_and_input_are_not_mutated(self):
        s = structure(["combat", "ghost"])
        source = three()
        s_before = s.to_dict()
        create_gameplay_system_registry(source, s)
        create_gameplay_system_registry(source, structure(["combat"]))
        self.assertEqual(s.to_dict(), s_before)
        self.assertEqual(source, three())

    def test_25_the_structure_is_not_stored_so_registries_stay_equal(self):
        a = create_gameplay_system_registry(three(), structure(["combat"])).registry
        b = create_gameplay_system_registry(three()).registry
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.to_dict(), b.to_dict())


class TestFactoryFailureBehavior(unittest.TestCase):
    def test_26_the_factory_never_raises_for_bad_input(self):
        class Boom:
            def __iter__(self):
                raise RuntimeError("must not iterate")

            def __eq__(self, other):
                raise RuntimeError("must not compare")
            __hash__ = None
        for systems, struct in ((None, None), (Boom(), None), ([Boom()], None), ([], Boom()), ({}, {}), (1, 1), ([None, None], "x"), ([[]], None),
                                ([{}], None)):
            with self.subTest(systems=type(systems).__name__, struct=type(struct).__name__):
                r = create_gameplay_system_registry(systems, struct)
                self.assertFalse(r.ok)
                self.assertIsNone(r.registry)
                self.assertTrue(r.failures)
                for f in r.failures:
                    self.assertIn(f["code"], reg.FAILURE_CODES)
                    self.assertEqual(set(f), {"code", "field", "message"})

    def test_27_failures_are_deterministic_and_result_to_dict_is_fresh(self):
        args = ([1, "a", "a"], structure(["zzz"]))
        a, b = create_gameplay_system_registry(*args), create_gameplay_system_registry(*args)
        self.assertEqual(a.to_dict(), b.to_dict())
        d = a.to_dict()
        self.assertEqual((d["ok"], d["registry"]), (False, None))
        d["failures"][0]["code"] = "hacked"
        d["failures"].clear()
        self.assertEqual(a.codes(), b.codes())
        self.assertTrue(a.failures)

    def test_28_ok_result_to_dict_shape(self):
        d = create_gameplay_system_registry(three()).to_dict()
        self.assertEqual(set(d), {"ok", "registry", "failures"})
        self.assertEqual((d["ok"], d["failures"]), (True, []))
        self.assertEqual(d["registry"], {"gameplay_systems": three()})

    def test_29_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(len(set(reg.FAILURE_CODES)), len(reg.FAILURE_CODES))
        self.assertTrue(all(c.startswith("GAMEPLAY_SYSTEM_REGISTRY_") for c in reg.FAILURE_CODES))
        self.assertEqual(reg.FAILURE_CODES, (
            "GAMEPLAY_SYSTEM_REGISTRY_INVALID_COLLECTION", "GAMEPLAY_SYSTEM_REGISTRY_INVALID_GAMEPLAY_SYSTEM",
            "GAMEPLAY_SYSTEM_REGISTRY_DUPLICATE_GAMEPLAY_SYSTEM_ID", "GAMEPLAY_SYSTEM_REGISTRY_INVALID_STRUCTURE",
            "GAMEPLAY_SYSTEM_REGISTRY_MISSING_GAMEPLAY_SYSTEM_REFERENCE", "GAMEPLAY_SYSTEM_REGISTRY_GAMEPLAY_SYSTEM_NOT_FOUND"))


class TestImmutabilityAndDeterminism(unittest.TestCase):
    def test_30_accessor_is_an_immutable_tuple(self):
        registry = create_gameplay_system_registry(three()).registry
        ids = registry.gameplay_system_ids
        self.assertIs(type(ids), tuple)
        with self.assertRaises(TypeError):
            ids[0] = "x"
        self.assertFalse(hasattr(ids, "append"))
        self.assertIs(registry.gameplay_system_ids, ids)

    def test_31_attributes_cannot_be_assigned_deleted_or_added(self):
        registry = create_gameplay_system_registry(three()).registry
        for name in ("gameplay_system_ids", "_ids", "extra"):
            with self.assertRaises(AttributeError):
                setattr(registry, name, ())
        for name in ("gameplay_system_ids", "_ids"):
            with self.assertRaises(AttributeError):
                delattr(registry, name)
        self.assertFalse(hasattr(registry, "__dict__"))
        self.assertEqual(registry.gameplay_system_ids, tuple(three()))

    def test_32_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            GameplaySystemRegistry(object(), [])
        with self.assertRaises(TypeError):
            GameplaySystemRegistry(None, three())
        with self.assertRaises(TypeError):
            class Sub(GameplaySystemRegistry):
                pass

    def test_33_equal_content_gives_equal_objects_and_hashes_and_order_matters(self):
        a = create_gameplay_system_registry(three()).registry
        b = create_gameplay_system_registry(tuple(three())).registry
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, create_gameplay_system_registry(list(reversed(three()))).registry)
        self.assertNotEqual(a, create_gameplay_system_registry(three()[:2]).registry)
        self.assertNotEqual(a, create_gameplay_system_registry(["combat", "dialogue", "Crafting"]).registry)
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, a.gameplay_system_ids)

    def test_34_to_dict_is_fresh_ordered_and_round_trips_through_the_factory(self):
        registry = create_gameplay_system_registry(three()).registry
        d = registry.to_dict()
        self.assertEqual(list(d), ["gameplay_systems"])
        self.assertEqual(d["gameplay_systems"], three())
        d["gameplay_systems"].append("x")
        d["gameplay_systems"][0] = "hacked"
        again = registry.to_dict()
        self.assertIsNot(d, again)
        self.assertIsNot(again["gameplay_systems"], registry.to_dict()["gameplay_systems"])
        self.assertEqual(registry.gameplay_system_ids, tuple(three()))
        self.assertEqual(create_gameplay_system_registry(again["gameplay_systems"]).registry, registry)

    def test_35_copy_returns_the_same_object_and_pickling_is_refused(self):
        registry = create_gameplay_system_registry(three()).registry
        self.assertIs(copy.copy(registry), registry)
        self.assertIs(copy.deepcopy(registry), registry)
        with self.assertRaises(TypeError):
            pickle.dumps(registry)

    def test_36_repr_lists_the_ids(self):
        self.assertEqual(repr(create_gameplay_system_registry(["a", "b"]).registry), "GameplaySystemRegistry(gameplay_system_ids=('a', 'b'))")


class TestBoundaries(unittest.TestCase):
    def test_37_module_imports_only_the_structure_record_and_has_no_io_or_state(self):
        with open(os.path.join(PY_ROOT, "game_creation", "gameplay_system_registry.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([(n.level, n.module, [a.name for a in n.names]) for n in imports],
                         [(1, "game_project_structure", ["GameProjectStructure"])])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(reg).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_38_earlier_section7_modules_are_untouched_and_unaware_of_the_registry(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))),
                         ["__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py", "game_project_structure.py", "game_project_validator.py",
                          "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in ("game_creation/game_project.py", "game_creation/game_project_structure.py", "game_creation/game_scene.py",
                    "game_creation/game_character.py", "game_creation/game_character_registry.py", "game_creation/game_scene_registry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("GameplaySystemRegistry", "gameplay_system_registry", "create_gameplay_system_registry"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "GameplaySystemRegistry", "gameplay_system_registry"):
                self.assertNotIn(token, text, (rel, token))

    def test_39_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("GameplaySystemRegistry", "create_gameplay_system_registry", "GameProjectStructure", "lookup", "does NOT", "later",
                       "unused", "GAMEPLAY_SYSTEM_REGISTRY_"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
