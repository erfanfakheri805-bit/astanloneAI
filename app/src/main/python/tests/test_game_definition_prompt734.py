"""Prompt 734 - Section 7 game definition (`game_creation.game_definition`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from game_creation import game_definition as gd
from game_creation.game_asset import create_game_asset
from game_creation.game_asset_registry import create_game_asset_registry
from game_creation.game_character import create_game_character
from game_creation.game_character_registry import create_game_character_registry
from game_creation.game_definition import GameDefinition, GameDefinitionResult, create_game_definition
from game_creation.game_project import create_game_project
from game_creation.game_project_structure import create_game_project_structure
from game_creation.game_scene import create_game_scene
from game_creation.game_scene_bundle import create_game_scene_bundle
from game_creation.game_scene_bundle_registry import create_game_scene_bundle_registry
from game_creation.game_scene_composition import create_game_scene_composition
from game_creation.game_scene_composition_registry import create_game_scene_composition_registry
from game_creation.game_scene_registry import create_game_scene_registry
from game_creation.gameplay_system_registry import create_gameplay_system_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_definition_prompt734.md")
SOURCE = os.path.join(PY_ROOT, "game_creation", "game_definition.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

ARG_NAMES = ("project", "structure", "scene_registry", "character_registry", "gameplay_system_registry", "asset_registry",
             "composition_registry", "bundle_registry")
INVALID_CODES = tuple("GAME_DEFINITION_INVALID_" + n for n in ("PROJECT", "STRUCTURE", "SCENE_REGISTRY", "CHARACTER_REGISTRY",
                                                               "GAMEPLAY_SYSTEM_REGISTRY", "ASSET_REGISTRY", "COMPOSITION_REGISTRY",
                                                               "BUNDLE_REGISTRY"))
PS = "GAME_DEFINITION_INVALID_PROJECT_STRUCTURE"
SC = "GAME_DEFINITION_INVALID_SCENE_COMPOSITION"
SB = "GAME_DEFINITION_INVALID_SCENE_BUNDLE"


def ok_of(result):
    assert result.ok, result.failures
    return result


def make_project():
    return ok_of(create_game_project({"project_id": "p1", "name": "P", "description": "", "genre": "", "target_platform": "", "version": "1"})).project


def make_structure(scenes=("s1", "s2"), characters=("c1",), systems=("combat",), assets=("a1", "a2")):
    return ok_of(create_game_project_structure({"scenes": list(scenes), "characters": list(characters), "gameplay_systems": list(systems),
                                                "assets": list(assets)})).structure


def make_scene(scene_id, name=None):
    return ok_of(create_game_scene({"scene_id": scene_id, "name": name or scene_id, "description": "", "scene_type": "level"})).scene


def make_scene_registry(ids=("s1", "s2")):
    return ok_of(create_game_scene_registry([make_scene(i) for i in ids])).registry


def make_character_registry(ids=("c1",)):
    return ok_of(create_game_character_registry([ok_of(create_game_character(
        {"character_id": i, "name": i, "description": "", "role": "npc"})).character for i in ids])).registry


def make_system_registry(ids=("combat",)):
    return ok_of(create_gameplay_system_registry(list(ids))).registry


def make_asset_registry(ids=("a1", "a2")):
    return ok_of(create_game_asset_registry([ok_of(create_game_asset(
        {"asset_id": i, "name": i, "description": "", "asset_type": "image"})).asset for i in ids])).registry


def make_composition(scene_id="s1", characters=("c1",), assets=("a1",), systems=("combat",)):
    return ok_of(create_game_scene_composition({"scene_id": scene_id, "character_ids": list(characters), "asset_ids": list(assets),
                                                "gameplay_system_ids": list(systems)})).composition


def make_composition_registry(*compositions):
    return ok_of(create_game_scene_composition_registry(list(compositions))).registry


def make_bundle(scene_id="s1", scene=None, composition=None):
    return ok_of(create_game_scene_bundle(scene or make_scene(scene_id), composition or make_composition(scene_id))).bundle


def make_bundle_registry(*bundles):
    return ok_of(create_game_scene_bundle_registry(list(bundles))).registry


def good_args(**over):
    args = {"project": make_project(), "structure": make_structure(), "scene_registry": make_scene_registry(),
            "character_registry": make_character_registry(), "gameplay_system_registry": make_system_registry(),
            "asset_registry": make_asset_registry(),
            "composition_registry": make_composition_registry(make_composition("s1"), make_composition("s2", (), ("a2",), ())),
            "bundle_registry": make_bundle_registry(make_bundle("s1"))}
    args.update(over)
    return args


def run(**over):
    return create_game_definition(**good_args(**over))


class Impostor:
    """Looks like anything but is not."""
    scenes = characters = assets = gameplay_systems = compositions = bundles = ()
    scene_ids = ()

    def to_dict(self):
        return {}

    def lookup(self, _):
        raise AssertionError("impostor consulted")


class TestValid(unittest.TestCase):
    def test_01_valid_complete_definition(self):
        args = good_args()
        result = create_game_definition(**args)
        self.assertIsInstance(result, GameDefinitionResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.codes(), [])
        self.assertIsInstance(result.definition, GameDefinition)
        self.assertEqual(result.to_dict()["failures"], [])
        self.assertTrue(result.to_dict()["ok"])

    def test_02_positional_call(self):
        a = good_args()
        self.assertTrue(create_game_definition(*[a[n] for n in ARG_NAMES]).ok)

    def test_03_identity_preserved_for_all_eight_objects(self):
        args = good_args()
        definition = create_game_definition(**args).definition
        for name in ARG_NAMES:
            self.assertIs(getattr(definition, name), args[name], name)

    def test_04_exactly_eight_public_attributes(self):
        definition = run().definition
        public = sorted(n for n in dir(definition) if not n.startswith("_"))
        self.assertEqual(public, sorted(ARG_NAMES + ("to_dict",)))

    def test_05_empty_registries_where_structurally_valid(self):
        result = run(structure=make_structure((), (), (), ()), scene_registry=make_scene_registry(()), character_registry=make_character_registry(()),
                     gameplay_system_registry=make_system_registry(()), asset_registry=make_asset_registry(()),
                     composition_registry=make_composition_registry(), bundle_registry=make_bundle_registry())
        self.assertTrue(result.ok, result.failures)

    def test_06_unused_registry_entries_are_allowed(self):
        result = run(scene_registry=make_scene_registry(("s1", "s2", "spare")), character_registry=make_character_registry(("c1", "spare")),
                     gameplay_system_registry=make_system_registry(("combat", "unused")), asset_registry=make_asset_registry(("a1", "a2", "a3")),
                     structure=make_structure((), (), (), ()))
        self.assertTrue(result.ok, result.failures)

    def test_07_bundle_registry_may_be_a_subset_of_compositions(self):
        self.assertTrue(run(bundle_registry=make_bundle_registry()).ok)
        self.assertTrue(run(composition_registry=make_composition_registry(), bundle_registry=make_bundle_registry()).ok)

    def test_08_empty_composition_fields_are_valid(self):
        self.assertTrue(run(composition_registry=make_composition_registry(make_composition("s1", (), (), ())), bundle_registry=make_bundle_registry()).ok)


class TestTopLevelArguments(unittest.TestCase):
    def bad_values(self, name):
        good = good_args()
        others = [good[n] for n in ARG_NAMES if n != name]
        return [None, "x", 5, {}, [], object(), Impostor(), others[0], others[-1]]

    def test_09_each_of_the_eight_arguments_is_checked(self):
        for index, name in enumerate(ARG_NAMES):
            for bad in self.bad_values(name):
                result = run(**{name: bad})
                self.assertFalse(result.ok, (name, bad))
                self.assertIsNone(result.definition)
                self.assertEqual(result.codes(), [INVALID_CODES[index]], name)
                failure = result.failures[0]
                self.assertEqual(failure["field"], name)
                self.assertIsNone(failure["source"])

    def test_10_failures_follow_argument_order(self):
        result = create_game_definition(*[None] * 8)
        self.assertEqual(result.codes(), list(INVALID_CODES))
        self.assertEqual([f["field"] for f in result.failures], list(ARG_NAMES))
        swapped = create_game_definition(*reversed([good_args()[n] for n in ARG_NAMES]))
        self.assertEqual(swapped.codes(), list(INVALID_CODES))

    def test_11_subset_of_bad_arguments_keeps_argument_order(self):
        result = run(bundle_registry=None, structure=None, asset_registry=None, project=None)
        self.assertEqual(result.codes(), [INVALID_CODES[0], INVALID_CODES[1], INVALID_CODES[5], INVALID_CODES[7]])

    def test_12_subclasses_are_rejected(self):
        # exact-type rule: a proxy that merely delegates is not the right type
        class Proxy:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, item):
                return getattr(self.inner, item)
        for name in ARG_NAMES:
            self.assertEqual(len(run(**{name: Proxy(good_args()[name])}).codes()), 1, name)

    def test_13_no_cross_validation_when_any_argument_is_invalid(self):
        with mock.patch.object(gd, "validate_game_project", side_effect=AssertionError("called")) as v1, \
             mock.patch.object(gd, "validate_game_scene_composition", side_effect=AssertionError("called")) as v2:
            broken = dict(structure=make_structure(("nope",), ("nope",), ("nope",), ("nope",)))
            for name in ARG_NAMES:
                result = run(**dict(broken, **{name: None}) if name != "structure" else {name: None})
                self.assertEqual(len(result.codes()), 1, name)
                self.assertFalse(set(result.codes()) & {PS, SC, SB})
            v1.assert_not_called()
            v2.assert_not_called()

    def test_14_invalid_input_never_raises(self):
        weird = [None, 0, "", (), [], {}, set(), object(), Ellipsis, Impostor, make_project, float("nan"), Impostor()]
        for bad in weird:
            for n in range(8):
                args = good_args()
                args[ARG_NAMES[n]] = bad
                try:
                    result = create_game_definition(**args)
                except Exception as exc:      # pragma: no cover
                    self.fail("raised %r" % (exc,))
                self.assertFalse(result.ok)
        with self.assertRaises(TypeError):      # a wrong NUMBER of arguments is a Python call error, not bad data
            create_game_definition()


class TestProjectStructureChecks(unittest.TestCase):
    def test_15_structure_mismatch_for_each_reference_kind(self):
        cases = (("scenes", make_structure(scenes=("s1", "ghost"))), ("characters", make_structure(characters=("c1", "ghost"))),
                 ("gameplay_systems", make_structure(systems=("combat", "ghost"))), ("assets", make_structure(assets=("a1", "ghost"))))
        for field, structure in cases:
            result = run(structure=structure)
            self.assertEqual(result.codes(), [PS], field)
            failure = result.failures[0]
            self.assertEqual(failure["field"], "structure")
            self.assertEqual(failure["source"]["field"], "structure." + field)
            self.assertIn("'ghost'", failure["source"]["message"])
            self.assertIn(failure["source"]["message"], failure["message"])
            self.assertTrue(failure["source"]["code"].startswith("GAME_PROJECT_VALIDATION_MISSING_"))

    def test_16_missing_scene_character_gameplay_asset_together_in_validator_order(self):
        result = run(structure=make_structure(("s1", "g1"), ("c1", "g2"), ("combat", "g3"), ("a1", "g4", "g5")))
        self.assertEqual(result.codes(), [PS] * 5)
        self.assertEqual([f["source"]["code"][len("GAME_PROJECT_VALIDATION_"):] for f in result.failures],
                         ["MISSING_SCENE_REFERENCE", "MISSING_CHARACTER_REFERENCE", "MISSING_GAMEPLAY_SYSTEM_REFERENCE",
                          "MISSING_ASSET_REFERENCE", "MISSING_ASSET_REFERENCE"])

    def test_17_delegated_failures_are_preserved_verbatim(self):
        args = good_args(structure=make_structure(("s1", "ghost")))
        expected = gd.validate_game_project(*[args[n] for n in ARG_NAMES[:6]]).failures
        got = create_game_definition(**args).failures
        self.assertEqual([f["source"] for f in got], expected)

    def test_18_ids_are_compared_exactly(self):
        for variant in ("S1", "s1 ", " s1"):
            self.assertEqual(run(structure=make_structure((variant,))).codes(), [PS], repr(variant))


class TestCompositionChecks(unittest.TestCase):
    def test_19_valid_compositions(self):
        self.assertTrue(run().ok)

    def test_20_missing_references_in_compositions(self):
        for kwargs, marker in (({"characters": ("ghost",)}, "CHARACTER_NOT_FOUND"), ({"assets": ("ghost",)}, "ASSET_NOT_FOUND"),
                               ({"systems": ("ghost",)}, "GAMEPLAY_SYSTEM_NOT_FOUND")):
            result = run(composition_registry=make_composition_registry(make_composition("s1", **kwargs)), bundle_registry=make_bundle_registry())
            self.assertEqual(result.codes(), [SC], marker)
            f = result.failures[0]
            self.assertEqual(f["field"], "composition_registry.compositions[0]")
            self.assertTrue(f["source"]["code"].endswith(marker))
            self.assertIn("'ghost'", f["message"])

    def test_21_composition_with_unregistered_scene(self):
        result = run(composition_registry=make_composition_registry(make_composition("s1"), make_composition("nowhere")),
                     bundle_registry=make_bundle_registry())
        self.assertEqual(result.codes(), [SC])
        f = result.failures[0]
        self.assertEqual(f["field"], "composition_registry.compositions[1].scene_id")
        self.assertIsNone(f["source"])
        self.assertIn("'nowhere'", f["message"])

    def test_22_composition_failures_follow_registry_order_and_nested_order(self):
        comps = make_composition_registry(make_composition("s2", ("g1",), ("g2",), ("g3",)), make_composition("s1", ("g4",), (), ()),
                                          make_composition("zz", ("g5",), (), ()))
        result = run(composition_registry=comps, bundle_registry=make_bundle_registry())
        self.assertEqual(result.codes(), [SC] * 5)
        self.assertEqual([f["field"] for f in result.failures], ["composition_registry.compositions[0]"] * 3 +
                         ["composition_registry.compositions[1]", "composition_registry.compositions[2].scene_id"])
        self.assertEqual([f["source"]["code"].rsplit("_NOT_FOUND")[0].rsplit("_", 1)[-1] for f in result.failures[:3]],
                         ["CHARACTER", "ASSET", "SYSTEM"])
        self.assertIsNone(result.failures[4]["source"])

    def test_23_composition_validator_receives_the_registered_scene_and_registries(self):
        args = good_args()
        calls = []
        real = gd.validate_game_scene_composition

        def spy(*a):
            calls.append(a)
            return real(*a)
        with mock.patch.object(gd, "validate_game_scene_composition", side_effect=spy):
            create_game_definition(**args)
        comps = args["composition_registry"].compositions
        self.assertEqual(len(calls), len(comps))
        for (c, scene, cr, ar, gr), expected in zip(calls, comps):
            self.assertIs(c, expected)
            self.assertIs(scene, args["scene_registry"].lookup(expected.scene_id).scene)
            self.assertIs(cr, args["character_registry"])
            self.assertIs(ar, args["asset_registry"])
            self.assertIs(gr, args["gameplay_system_registry"])

    def test_24_missing_composition_scene_is_not_passed_to_the_validator(self):
        with mock.patch.object(gd, "validate_game_scene_composition", wraps=gd.validate_game_scene_composition) as spy:
            run(composition_registry=make_composition_registry(make_composition("nowhere")), bundle_registry=make_bundle_registry())
        spy.assert_not_called()


class TestBundleChecks(unittest.TestCase):
    def test_25_valid_bundles(self):
        r = run(bundle_registry=make_bundle_registry(make_bundle("s1"), make_bundle("s2", composition=make_composition("s2", (), ("a2",), ()))))
        self.assertTrue(r.ok, r.failures)

    def test_26_bundle_with_missing_scene_reference(self):
        composition = make_composition("s3", (), (), ())
        bundle = make_bundle("s3", composition=composition)
        result = run(bundle_registry=make_bundle_registry(bundle), composition_registry=make_composition_registry(composition),
                     structure=make_structure((), (), (), ()))
        self.assertEqual(result.codes(), [SC, SB])
        self.assertEqual(result.failures[1]["field"], "bundle_registry.bundles[0].scene_id")
        self.assertIsNone(result.failures[1]["source"])

    def test_27_bundle_with_missing_composition_reference(self):
        result = run(bundle_registry=make_bundle_registry(make_bundle("s1")), composition_registry=make_composition_registry(make_composition("s2", (), ("a2",), ())))
        self.assertEqual(result.codes(), [SB])
        self.assertEqual(result.failures[0]["field"], "bundle_registry.bundles[0].composition.scene_id")

    def test_28_bundle_missing_both_references(self):
        result = run(bundle_registry=make_bundle_registry(make_bundle("zz")))
        self.assertEqual(result.codes(), [SB, SB])
        self.assertEqual([f["field"] for f in result.failures], ["bundle_registry.bundles[0].scene_id", "bundle_registry.bundles[0].composition.scene_id"])

    def test_29_bundle_scene_differs_from_registered_scene(self):
        result = run(bundle_registry=make_bundle_registry(make_bundle("s1", scene=make_scene("s1", name="Different"))))
        self.assertEqual(result.codes(), [SB])
        self.assertEqual(result.failures[0]["field"], "bundle_registry.bundles[0].scene")

    def test_30_bundle_composition_differs_from_registered_composition(self):
        result = run(bundle_registry=make_bundle_registry(make_bundle("s1", composition=make_composition("s1", ("c1",), ("a1", "a2"), ("combat",)))))
        self.assertEqual(result.codes(), [SB])
        self.assertEqual(result.failures[0]["field"], "bundle_registry.bundles[0].composition")

    def test_31_bundle_failures_follow_registry_order(self):
        bundles = make_bundle_registry(make_bundle("s1", scene=make_scene("s1", name="X")), make_bundle("q1"),
                                       make_bundle("s2", composition=make_composition("s2", (), (), ())))
        result = run(bundle_registry=bundles)
        self.assertEqual(result.codes(), [SB] * 4)
        self.assertEqual([f["field"] for f in result.failures],
                         ["bundle_registry.bundles[0].scene", "bundle_registry.bundles[1].scene_id",
                          "bundle_registry.bundles[1].composition.scene_id", "bundle_registry.bundles[2].composition"])

    def test_32_bundle_ids_are_compared_exactly(self):
        r = run(bundle_registry=make_bundle_registry(make_bundle("S1")))
        self.assertEqual(r.codes(), [SB, SB])


class TestOrderingAndDeterminism(unittest.TestCase):
    def broken(self):
        return dict(structure=make_structure(("s1", "gs"), ("gc",)),
                    composition_registry=make_composition_registry(make_composition("s1", ("g1",)), make_composition("s2", (), ("g2",), ())),
                    bundle_registry=make_bundle_registry(make_bundle("q9")))

    def test_33_stage_order_structure_then_compositions_then_bundles(self):
        result = run(**self.broken())
        self.assertEqual(result.codes(), [PS, PS, SC, SC, SB, SB])
        self.assertEqual([f["field"] for f in result.failures],
                         ["structure", "structure", "composition_registry.compositions[0]", "composition_registry.compositions[1]",
                          "bundle_registry.bundles[0].scene_id", "bundle_registry.bundles[0].composition.scene_id"])

    def test_34_failures_are_deterministic(self):
        first, second = run(**self.broken()), run(**self.broken())
        self.assertEqual(first, second)
        self.assertEqual(hash(first), hash(second))
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_35_delegated_validators_are_reused_exactly_once_per_item(self):
        args = good_args()
        with mock.patch.object(gd, "validate_game_project", wraps=gd.validate_game_project) as v1, \
             mock.patch.object(gd, "validate_game_scene_composition", wraps=gd.validate_game_scene_composition) as v2:
            create_game_definition(**args)
        self.assertEqual(v1.call_count, 1)
        a = v1.call_args[0]
        self.assertEqual(len(a), 6)
        for arg, name in zip(a, ARG_NAMES):
            self.assertIs(arg, args[name])
        self.assertEqual(v2.call_count, len(args["composition_registry"].compositions))

    def test_36_substituted_validator_output_is_carried_through_unchanged(self):
        fake = gd.validate_game_project(make_project(), make_structure(("x",)), make_scene_registry(), make_character_registry(),
                                        make_system_registry(), make_asset_registry())
        with mock.patch.object(gd, "validate_game_project", return_value=fake):
            result = run()
        self.assertEqual(result.codes(), [PS])
        self.assertEqual(result.failures[0]["source"], fake.failures[0])


class TestImmutabilityAndEquality(unittest.TestCase):
    def test_37_deterministic_equality_and_hash(self):
        a, b = run().definition, run().definition
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, run(project=ok_of(create_game_project({"project_id": "other", "name": "P", "description": "", "genre": "",
                                                                    "target_platform": "", "version": "1"})).project).definition)
        self.assertNotEqual(a, run(scene_registry=make_scene_registry(("s1", "s2", "x"))).definition)
        self.assertNotEqual(a, a.to_dict())
        r1, r2 = run(), run()
        self.assertEqual(r1, r2)
        self.assertEqual(hash(r1), hash(r2))
        self.assertEqual(run(project=None), run(project=None))
        self.assertNotEqual(run(project=None), r1)
        self.assertNotEqual(run(project=None), run(structure=None))

    def test_38_fresh_to_dict_and_nested_independence(self):
        definition = run().definition
        d1, d2 = definition.to_dict(), definition.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertEqual(list(d1), list(ARG_NAMES))
        for name in ARG_NAMES:
            self.assertEqual(d1[name], getattr(definition, name).to_dict(), name)
            self.assertIsNot(d1[name], d2[name], name)
        snapshot = definition.to_dict()
        d1["bundle_registry"]["bundles"].append("junk")
        d1["bundle_registry"]["bundles"][0]["composition"]["asset_ids"].append("junk")
        d1["composition_registry"]["compositions"][0]["character_ids"].append("junk")
        d1["scene_registry"]["scenes"][0]["name"] = "mutated"
        d1["structure"]["scenes"].append("junk")
        d1["project"]["name"] = "mutated"
        self.assertEqual(definition.to_dict(), snapshot)
        self.assertEqual(d1["bundle_registry"]["bundles"][0]["scene"], definition.bundle_registry.bundles[0].scene.to_dict())

    def test_39_result_to_dict_and_failures_are_fresh(self):
        ok = run()
        self.assertIsNot(ok.to_dict(), ok.to_dict())
        self.assertIsNot(ok.to_dict()["definition"], ok.to_dict()["definition"])
        self.assertEqual(ok.to_dict()["definition"], ok.definition.to_dict())
        bad = run(structure=make_structure(("s1", "ghost")))
        self.assertIsNone(bad.to_dict()["definition"])
        self.assertIsNot(bad.failures, bad.failures)
        self.assertIsNot(bad.failures[0], bad.failures[0])
        self.assertIsNot(bad.failures[0]["source"], bad.failures[0]["source"])
        self.assertIsNot(bad.codes(), bad.codes())
        snapshot = bad.to_dict()
        bad.failures.append("junk")
        bad.failures[0]["code"] = "x"
        bad.failures[0]["source"]["code"] = "x"
        bad.codes().append("x")
        d = bad.to_dict()
        d["failures"][0]["source"]["message"] = "x"
        self.assertEqual(bad.to_dict(), snapshot)

    def test_40_to_dict_is_plain_data(self):
        def check(value):
            self.assertIn(type(value), (dict, list, str, bool, type(None), int))
            if type(value) is dict:
                for k, v in value.items():
                    self.assertIs(type(k), str)
                    check(v)
            elif type(value) is list:
                for v in value:
                    check(v)
        check(run().to_dict())
        check(run(structure=make_structure(("ghost",))).to_dict())
        check(run(project=None).to_dict())

    def test_41_attributes_are_read_only(self):
        definition, result = run().definition, run()
        for obj, names in ((definition, ARG_NAMES + ("_project", "extra", "to_dict")), (result, ("ok", "definition", "failures", "_failures", "extra"))):
            for name in names:
                with self.assertRaises(AttributeError, msg=(type(obj).__name__, name)):
                    setattr(obj, name, 1)
                with self.assertRaises(AttributeError, msg=(type(obj).__name__, name)):
                    delattr(obj, name)
            self.assertFalse(hasattr(obj, "__dict__"))

    def test_42_direct_construction_is_refused(self):
        a = good_args()
        vals = [a[n] for n in ARG_NAMES]
        for token in (object(), None, True):
            with self.assertRaises(TypeError):
                GameDefinition(token, *vals)
            with self.assertRaises(TypeError):
                GameDefinitionResult(token, None, [])
        with self.assertRaises(TypeError):
            GameDefinition(*vals)
        with self.assertRaises(TypeError):
            GameDefinition()

    def test_43_subclassing_is_refused(self):
        for base in (GameDefinition, GameDefinitionResult):
            with self.assertRaises(TypeError):
                type("Sub", (base,), {})

    def test_44_copy_and_deepcopy_return_the_same_object(self):
        result = run()
        for obj in (result, result.definition, run(project=None)):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)

    def test_45_pickle_is_refused(self):
        result = run()
        for obj in (result, result.definition, run(project=None)):
            for protocol in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(obj, protocol)

    def test_46_repr_is_deterministic(self):
        self.assertEqual(repr(run()), repr(run()))
        self.assertEqual(repr(run(project=None)), "GameDefinitionResult(ok=False, failures=1)")
        self.assertEqual(repr(run().definition), repr(run().definition))


class TestNoMutation(unittest.TestCase):
    def test_47_supplied_objects_are_not_mutated(self):
        for over in ({}, {"structure": make_structure(("ghost",))},
                     {"bundle_registry": make_bundle_registry(make_bundle("q9"))},
                     {"composition_registry": make_composition_registry(make_composition("s1", ("ghost",)))}):
            args = good_args(**over)
            before = {n: args[n].to_dict() for n in ARG_NAMES}
            hashes = {n: hash(args[n]) for n in ARG_NAMES}
            create_game_definition(**args)
            self.assertEqual({n: args[n].to_dict() for n in ARG_NAMES}, before)
            self.assertEqual({n: hash(args[n]) for n in ARG_NAMES}, hashes)

    def test_48_inputs_are_not_consulted_when_invalid(self):
        args = good_args(composition_registry=Impostor(), bundle_registry=Impostor())
        result = create_game_definition(**args)
        self.assertEqual(result.codes(), [INVALID_CODES[6], INVALID_CODES[7]])


class TestSourceBoundaries(unittest.TestCase):
    def tree(self):
        with open(SOURCE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_49_imports_are_only_public_section7_models_registries_and_the_two_validators(self):
        imports = sorted((n.module, tuple(a.name for a in n.names)) for n in ast.walk(self.tree()) if isinstance(n, (ast.Import, ast.ImportFrom)))
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in ast.walk(self.tree()) if isinstance(n, (ast.Import, ast.ImportFrom))))
        self.assertEqual(imports, sorted([
            ("game_asset_registry", ("GameAssetRegistry",)), ("game_character_registry", ("GameCharacterRegistry",)),
            ("game_project", ("GameProject",)), ("game_project_structure", ("GameProjectStructure",)),
            ("game_project_validator", ("validate_game_project",)), ("game_scene_bundle_registry", ("GameSceneBundleRegistry",)),
            ("game_scene_composition_registry", ("GameSceneCompositionRegistry",)),
            ("game_scene_composition_validator", ("validate_game_scene_composition",)), ("game_scene_registry", ("GameSceneRegistry",)),
            ("gameplay_system_registry", ("GameplaySystemRegistry",))]))

    def test_50_no_registry_internal_access(self):
        tree = self.tree()
        allowed_private = {"_project", "_structure", "_scene_registry", "_character_registry", "_gameplay_system_registry", "_asset_registry",
                           "_composition_registry", "_bundle_registry", "_definition", "_failures", "_key"}
        foreign = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr.startswith("_") and not n.attr.startswith("__")
                   and n.attr not in allowed_private]
        self.assertEqual([ast.unparse(n) for n in foreign], [])
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr in allowed_private and n.attr not in ("_key", "_failures", "_definition"):
                self.assertIsInstance(n.value, ast.Name)
                self.assertEqual(n.value.id, "self")
        public_reads = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                        and n.value.id not in ("self", "other", "object") and not n.attr.startswith("_")}
        self.assertLessEqual(public_reads, {"compositions", "bundles", "scene_id", "composition", "scene", "found", "lookup", "failures", "append"})

    def test_51_no_validator_logic_is_duplicated(self):
        tree = self.tree()
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("character_ids", "asset_ids", "gameplay_system_ids", "character_id", "asset_id", "gameplay_system_ids", "scenes",
                          "characters", "assets", "gameplay_systems", "GameSceneCompositionValidator", "GameProjectValidator",
                          "create_game_scene_bundle", "process_input", "Core", "Planner", "AgentLoop"):
            self.assertNotIn(forbidden, names, forbidden)

    def test_52_no_io_normalization_or_module_state(self):
        tree = self.tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "sorted", "copy.copy", "copy.deepcopy"):
            self.assertNotIn(forbidden, calls)
        for method in ("strip", "lstrip", "rstrip", "lower", "upper", "casefold", "normalize", "title", "encode", "decode", "replace"):
            self.assertFalse([c for c in calls if c.endswith("." + method)], method)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(gd).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_53_stable_codes(self):
        self.assertEqual(gd.FAILURE_CODES[:8], INVALID_CODES)
        self.assertEqual(gd.FAILURE_CODES[8:], (PS, SC, SB))
        self.assertTrue(all(c.startswith("GAME_DEFINITION_") for c in gd.FAILURE_CODES))
        self.assertEqual(len(set(gd.FAILURE_CODES)), 11)


class TestScopeAndDocumentation(unittest.TestCase):
    def test_54_earlier_modules_are_untouched_and_unaware_of_the_definition(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py",
            "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py",
            "game_project.py", "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py",
            "game_scene_bundle_registry.py", "game_scene_composition.py", "game_scene_composition_registry.py",
            "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))):
            if rel in ("game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "__init__.py"):      # Prompt 735/736/737 consumers of GameDefinition
                continue
            with open(os.path.join(PY_ROOT, "game_creation", rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_definition", "create_game_definition", "GameDefinition"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "game_definition", "create_game_definition"):
                self.assertNotIn(token, text, (rel, token))

    def test_55_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_game_definition", "GameDefinitionResult", "GameDefinition", "GAME_DEFINITION_", "INVALID_PROJECT_STRUCTURE",
                       "INVALID_SCENE_COMPOSITION", "INVALID_SCENE_BUNDLE", "INVALID_BUNDLE_REGISTRY", "validate_game_project",
                       "validate_game_scene_composition", "does NOT", "Prompt 728", "Prompt 730", "Prompt 733", "Prompt 735"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
