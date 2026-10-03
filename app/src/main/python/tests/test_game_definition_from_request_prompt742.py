"""Prompt 742 - Section 7 game definition from request (`game_creation.game_definition_from_request`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from game_creation import game_definition_from_request as bridge
from game_creation.game_asset_registry import GameAssetRegistry, create_game_asset_registry
from game_creation.game_character_registry import GameCharacterRegistry, create_game_character_registry
from game_creation.game_creation_request import GameCreationRequest, create_game_creation_request
from game_creation.game_definition import GameDefinition, GameDefinitionResult, create_game_definition
from game_creation.game_definition_from_request import GameDefinitionFromRequestResult, create_game_definition_from_request
from game_creation.game_project import GameProject, create_game_project
from game_creation.game_project_structure import GameProjectStructure, create_game_project_structure
from game_creation.game_scene_bundle_registry import GameSceneBundleRegistry, create_game_scene_bundle_registry
from game_creation.game_scene_composition_registry import GameSceneCompositionRegistry, create_game_scene_composition_registry
from game_creation.game_scene_registry import GameSceneRegistry, create_game_scene_registry
from game_creation.gameplay_system_registry import GameplaySystemRegistry, create_gameplay_system_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
PKG = os.path.join(PY_ROOT, "game_creation")
SOURCE = os.path.join(PKG, "game_definition_from_request.py")
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_definition_from_request_prompt742.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

FIELDS = ("project_id", "name", "description", "genre", "target_platform", "version")
INVALID_REQUEST = "GAME_DEFINITION_FROM_REQUEST_INVALID_REQUEST"
EMPTY_STRUCTURE = {"scenes": [], "characters": [], "gameplay_systems": [], "assets": []}
REGISTRY_FACTORIES = (("create_game_scene_registry", GameSceneRegistry), ("create_game_character_registry", GameCharacterRegistry),
                      ("create_gameplay_system_registry", GameplaySystemRegistry), ("create_game_asset_registry", GameAssetRegistry),
                      ("create_game_scene_bundle_registry", GameSceneBundleRegistry),
                      ("create_game_scene_composition_registry", GameSceneCompositionRegistry))
ORDER = ("create_game_project", "create_game_project_structure", "create_game_scene_registry", "create_game_character_registry",
         "create_gameplay_system_registry", "create_game_asset_registry", "create_game_scene_composition_registry",
         "create_game_scene_bundle_registry", "create_game_definition")


def good(**over):
    d = {"project_id": "p1", "name": "My Game", "description": "A game", "genre": "puzzle", "target_platform": "android", "version": "1.0"}
    d.update(over)
    return d


def make_request(**over):
    result = create_game_creation_request(good(**over))
    assert result.ok, result.failures
    return result.request


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def source_tree():
    with open(SOURCE, encoding="utf-8") as fh:
        return ast.parse(fh.read())


def real_failure_for(name):
    """A genuine failing result produced by the real factory named `name` (so shapes are never hand-made)."""
    if name == "create_game_project":
        return create_game_project({})
    if name == "create_game_project_structure":
        return create_game_project_structure({})
    if name == "create_game_definition":
        structure = create_game_project_structure({"scenes": ["s1"], "characters": [], "gameplay_systems": [], "assets": []}).structure
        return create_game_definition(create_game_project(good()).project, structure, create_game_scene_registry([]).registry,
                                      create_game_character_registry([]).registry, create_gameplay_system_registry([]).registry,
                                      create_game_asset_registry([]).registry, create_game_scene_composition_registry([]).registry,
                                      create_game_scene_bundle_registry([]).registry)
    return getattr(bridge, name)("not a collection")


class TestValidRequest(unittest.TestCase):
    def test_01_valid_request_creates_a_valid_empty_game_definition(self):
        result = create_game_definition_from_request(make_request())
        self.assertIsInstance(result, GameDefinitionFromRequestResult)
        self.assertTrue(result.ok)
        self.assertIsInstance(result.definition, GameDefinition)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.codes(), [])
        d = result.definition
        self.assertIsInstance(d.project, GameProject)
        self.assertIsInstance(d.structure, GameProjectStructure)
        self.assertIsInstance(d.scene_registry, GameSceneRegistry)
        self.assertIsInstance(d.character_registry, GameCharacterRegistry)
        self.assertIsInstance(d.gameplay_system_registry, GameplaySystemRegistry)
        self.assertIsInstance(d.asset_registry, GameAssetRegistry)
        self.assertIsInstance(d.composition_registry, GameSceneCompositionRegistry)
        self.assertIsInstance(d.bundle_registry, GameSceneBundleRegistry)

    def test_02_the_definition_is_what_the_existing_factory_builds_from_the_same_empty_graph(self):
        result = create_game_definition_from_request(make_request())
        expected = create_game_definition(
            create_game_project(good()).project, create_game_project_structure(EMPTY_STRUCTURE).structure, create_game_scene_registry([]).registry,
            create_game_character_registry([]).registry, create_gameplay_system_registry([]).registry, create_game_asset_registry([]).registry,
            create_game_scene_composition_registry([]).registry, create_game_scene_bundle_registry([]).registry)
        self.assertTrue(expected.ok)
        self.assertEqual(result.definition, expected.definition)
        self.assertEqual(result.to_dict(), {"ok": True, "definition": expected.definition.to_dict(), "failures": []})

    def test_03_everything_except_the_project_is_empty(self):
        d = create_game_definition_from_request(make_request()).definition
        self.assertEqual(d.structure.to_dict(), EMPTY_STRUCTURE)
        self.assertEqual(d.scene_registry.scene_ids, ())
        self.assertEqual(d.character_registry.character_ids, ())
        self.assertEqual(d.gameplay_system_registry.gameplay_system_ids, ())
        self.assertEqual(d.asset_registry.asset_ids, ())
        self.assertEqual(d.composition_registry.compositions, ())
        self.assertEqual(d.bundle_registry.bundles, ())
        self.assertEqual(d.to_dict(), {"project": good(), "structure": EMPTY_STRUCTURE, "scene_registry": {"scenes": []},
                                       "character_registry": {"characters": []}, "gameplay_system_registry": {"gameplay_systems": []},
                                       "asset_registry": {"assets": []}, "composition_registry": {"compositions": []},
                                       "bundle_registry": {"bundles": []}})

    def test_04_the_result_is_deterministic(self):
        a, b = create_game_definition_from_request(make_request()), create_game_definition_from_request(make_request())
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_05_only_the_project_depends_on_the_request_values(self):
        base = create_game_definition_from_request(make_request()).to_dict()
        for over in ({"name": "Other"}, {"genre": "rpg"}, {"project_id": "scenes"}, {"description": "assets"}, {"version": "  2  "}):
            other = create_game_definition_from_request(make_request(**over)).to_dict()
            self.assertNotEqual(base["definition"]["project"], other["definition"]["project"], over)
            for key in base["definition"]:
                if key != "project":
                    self.assertEqual(base["definition"][key], other["definition"][key], (over, key))

    def test_06_all_nine_factories_are_called_once_in_order_and_never_for_invalid_requests(self):
        manager = mock.Mock()
        patches = [mock.patch.object(bridge, name, wraps=getattr(bridge, name)) for name in ORDER]
        mocks = [p.start() for p in patches]
        try:
            for name, m in zip(ORDER, mocks):
                manager.attach_mock(m, name)
            create_game_definition_from_request(make_request())
            self.assertEqual([c[0] for c in manager.mock_calls if c[0] in ORDER], list(ORDER))
            for m in mocks:
                self.assertEqual(m.call_count, 1)
            create_game_definition_from_request(None)
            for m in mocks:
                self.assertEqual(m.call_count, 1)
        finally:
            for p in patches:
                p.stop()


class TestProjectFields(unittest.TestCase):
    def test_07_the_six_fields_are_passed_unchanged_as_the_same_objects(self):
        values = {f: "".join(["  v-", f, "  "]) for f in FIELDS}
        request = make_request(**values)
        with mock.patch.object(bridge, "create_game_project", wraps=create_game_project) as factory:
            result = create_game_definition_from_request(request)
        self.assertTrue(result.ok)
        (data,), kwargs = factory.call_args
        self.assertEqual(kwargs, {})
        self.assertIs(type(data), dict)
        self.assertEqual(list(data), list(FIELDS))
        for field in FIELDS:
            self.assertIs(data[field], getattr(request, field), field)
            self.assertEqual(data[field], values[field])
            self.assertEqual(getattr(result.definition.project, field), values[field])
            self.assertIs(getattr(result.definition.project, field), getattr(request, field), field)

    def test_08_optional_fields_may_be_empty_and_nothing_is_trimmed_or_normalized(self):
        request = make_request(description="", genre="", target_platform="", name=" Name ", version=" 1 ")
        project = create_game_definition_from_request(request).definition.project
        self.assertEqual(project.to_dict(), {"project_id": "p1", "name": " Name ", "description": "", "genre": "", "target_platform": "",
                                             "version": " 1 "})

    def test_09_the_project_in_the_definition_is_the_one_the_project_factory_returned(self):
        produced = []

        def spy(data):
            produced.append(create_game_project(data))
            return produced[-1]
        with mock.patch.object(bridge, "create_game_project", side_effect=spy):
            result = create_game_definition_from_request(make_request())
        self.assertEqual(len(produced), 1)
        self.assertIs(result.definition.project, produced[0].project)


class TestEmptyGraph(unittest.TestCase):
    def test_10_the_structure_factory_gets_exactly_four_empty_lists_and_no_request_field(self):
        values = {f: "".join(["v-", f]) for f in FIELDS}
        with mock.patch.object(bridge, "create_game_project_structure", wraps=create_game_project_structure) as factory:
            create_game_definition_from_request(make_request(**values))
        self.assertEqual(factory.call_count, 1)
        (data,), kwargs = factory.call_args
        self.assertEqual(kwargs, {})
        self.assertEqual(list(data), ["scenes", "characters", "gameplay_systems", "assets"])
        for field, value in data.items():
            self.assertIs(type(value), list)
            self.assertEqual(value, [])
        for field in FIELDS:
            self.assertNotIn(field, data)
            self.assertNotIn(values[field], str(data))

    def test_11_each_registry_factory_gets_exactly_one_empty_list_and_no_other_argument(self):
        for name, _cls in REGISTRY_FACTORIES:
            with mock.patch.object(bridge, name, wraps=getattr(bridge, name)) as factory:
                create_game_definition_from_request(make_request())
            self.assertEqual(factory.call_count, 1, name)
            args, kwargs = factory.call_args
            self.assertEqual(kwargs, {}, name)
            self.assertEqual(len(args), 1, name)
            self.assertIs(type(args[0]), list, name)
            self.assertEqual(args[0], [], name)

    def test_12_every_call_passes_fresh_lists(self):
        for name in ("create_game_project_structure",) + tuple(n for n, _c in REGISTRY_FACTORIES):
            seen = []
            real = getattr(bridge, name)

            def spy(data, _real=real, _seen=seen):
                _seen.append(data)
                return _real(data)
            with mock.patch.object(bridge, name, side_effect=spy):
                create_game_definition_from_request(make_request())
                create_game_definition_from_request(make_request())
            self.assertEqual(len(seen), 2, name)
            self.assertIsNot(seen[0], seen[1], name)
            if isinstance(seen[0], dict):
                for key in seen[0]:
                    self.assertIsNot(seen[0][key], seen[1][key], (name, key))

    def test_13_no_empty_object_is_shared_between_calls(self):
        a = create_game_definition_from_request(make_request()).definition
        b = create_game_definition_from_request(make_request()).definition
        self.assertEqual(a, b)
        for attr in ("project", "structure", "scene_registry", "character_registry", "gameplay_system_registry", "asset_registry",
                     "composition_registry", "bundle_registry"):
            self.assertIsNot(getattr(a, attr), getattr(b, attr), attr)


class TestIdentityAndDefinitionCall(unittest.TestCase):
    def test_14_the_definition_factory_gets_the_eight_produced_objects_positionally_and_identity_is_preserved(self):
        products = {}
        real = {}
        patches = []
        for name, attr in (("create_game_project", "project"), ("create_game_project_structure", "structure"),
                           ("create_game_scene_registry", "registry"), ("create_game_character_registry", "registry"),
                           ("create_gameplay_system_registry", "registry"), ("create_game_asset_registry", "registry"),
                           ("create_game_scene_composition_registry", "registry"), ("create_game_scene_bundle_registry", "registry")):
            real[name] = getattr(bridge, name)

            def spy(data, _name=name, _attr=attr):
                outcome = real[_name](data)
                products[_name] = getattr(outcome, _attr)
                return outcome
            patches.append(mock.patch.object(bridge, name, side_effect=spy))
        patches.append(mock.patch.object(bridge, "create_game_definition", wraps=create_game_definition))
        started = [p.start() for p in patches]
        try:
            result = create_game_definition_from_request(make_request())
        finally:
            for p in patches:
                p.stop()
        definition_factory = started[-1]
        self.assertEqual(definition_factory.call_count, 1)
        args, kwargs = definition_factory.call_args
        self.assertEqual(kwargs, {})
        self.assertEqual(len(args), 8)
        for arg, name in zip(args, ORDER[:-1]):
            self.assertIs(arg, products[name], name)
        d = result.definition
        for attr, name in zip(("project", "structure", "scene_registry", "character_registry", "gameplay_system_registry", "asset_registry",
                               "composition_registry", "bundle_registry"), ORDER[:-1]):
            self.assertIs(getattr(d, attr), products[name], attr)

    def test_15_the_returned_definition_is_the_factory_definition_object(self):
        sentinel = create_game_definition_from_request(make_request(project_id="other")).definition
        outcome = mock.Mock(ok=True, definition=sentinel, failures=[])
        with mock.patch.object(bridge, "create_game_definition", return_value=outcome):
            result = create_game_definition_from_request(make_request())
        self.assertTrue(result.ok)
        self.assertIs(result.definition, sentinel)
        self.assertEqual(result.to_dict()["definition"], sentinel.to_dict())


class TestInvalidRequest(unittest.TestCase):
    def assert_invalid(self, value):
        patches = [mock.patch.object(bridge, name) for name in ORDER]
        mocks = [p.start() for p in patches]
        try:
            result = create_game_definition_from_request(value)
        finally:
            for p in patches:
                p.stop()
        for m in mocks:
            m.assert_not_called()
        self.assertIsInstance(result, GameDefinitionFromRequestResult)
        self.assertFalse(result.ok)
        self.assertIsNone(result.definition)
        self.assertEqual(result.codes(), [INVALID_REQUEST])
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0], {"code": INVALID_REQUEST, "field": "request", "message": "request must be exactly a GameCreationRequest.",
                                              "source": None})
        self.assertEqual(result.to_dict(), {"ok": False, "definition": None, "failures": result.failures})
        return result

    def test_16_wrong_object_types_are_rejected(self):
        for value in (None, good(), EMPTY_STRUCTURE, [], (), "request", 1, 1.5, True, object(), GameCreationRequest, create_game_creation_request(good()),
                      create_game_project(good()), create_game_project(good()).project, create_game_project_structure(EMPTY_STRUCTURE).structure,
                      create_game_definition_from_request(make_request()), create_game_definition_from_request(make_request()).definition):
            self.assert_invalid(value)

    def test_17_look_alikes_and_subclasses_are_rejected(self):
        class LookAlike:
            project_id, name, description, genre, target_platform, version = "p1", "n", "", "", "", "1"

        class D(dict):
            pass
        self.assert_invalid(LookAlike())
        self.assert_invalid(mock.Mock(spec=GameCreationRequest))
        self.assert_invalid(D(good()))

    def test_18_the_invalid_failure_is_deterministic_and_uses_the_bridge_prefix(self):
        a, b = self.assert_invalid(None), self.assert_invalid(None)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.failures, b.failures)
        self.assertTrue(a.failures[0]["code"].startswith(bridge.FAILURE_PREFIX))

    def test_19_never_raises_for_bad_input(self):
        for value in (None, 0, "", b"", [], {}, set(), object(), type, lambda: None, float("nan")):
            self.assertFalse(create_game_definition_from_request(value).ok)


class TestFactoryFailurePropagation(unittest.TestCase):
    def run_failing(self, name, outcome):
        patches = {n: mock.patch.object(bridge, n, wraps=getattr(bridge, n)) for n in ORDER}
        started = {n: p.start() for n, p in patches.items()}
        started[name].side_effect = None
        started[name].return_value = outcome
        try:
            result = create_game_definition_from_request(make_request())
        finally:
            for p in patches.values():
                p.stop()
        return result, started

    def test_20_a_failure_at_any_stage_is_exposed_unchanged_and_stops_the_chain(self):
        for index, name in enumerate(ORDER):
            real = real_failure_for(name)
            self.assertFalse(real.ok, name)
            expected = [{"code": f["code"], "field": f["field"], "message": f["message"], "source": f.get("source")} for f in real.failures]
            result, started = self.run_failing(name, real)
            self.assertFalse(result.ok, name)
            self.assertIsNone(result.definition, name)
            self.assertEqual(result.failures, expected, name)
            self.assertEqual(result.codes(), real.codes(), name)
            self.assertEqual(result.to_dict(), {"ok": False, "definition": None, "failures": expected}, name)
            for later in ORDER[index + 1:]:
                started[later].assert_not_called()
            for earlier in ORDER[:index + 1]:
                self.assertEqual(started[earlier].call_count, 1, (name, earlier))

    def test_21_no_failure_is_invented_or_recoded(self):
        for name in ORDER:
            result, _ = self.run_failing(name, real_failure_for(name))
            self.assertNotIn(INVALID_REQUEST, result.codes(), name)
            for code in result.codes():
                self.assertFalse(code.startswith(bridge.FAILURE_PREFIX), (name, code))

    def test_22_an_unknown_future_failure_is_passed_through_as_is(self):
        outcome = mock.Mock(ok=False, failures=[{"code": "GAME_PROJECT_SOMETHING_NEW", "field": None, "message": "Unknown to the bridge."},
                                                {"code": "GAME_PROJECT_ANOTHER", "field": "x", "message": "Second."}])
        result, _ = self.run_failing("create_game_project", outcome)
        self.assertEqual(result.failures, [{"code": "GAME_PROJECT_SOMETHING_NEW", "field": None, "message": "Unknown to the bridge.", "source": None},
                                           {"code": "GAME_PROJECT_ANOTHER", "field": "x", "message": "Second.", "source": None}])
        self.assertEqual(result.codes(), ["GAME_PROJECT_SOMETHING_NEW", "GAME_PROJECT_ANOTHER"])

    def test_23_a_definition_failure_keeps_its_source(self):
        real = real_failure_for("create_game_definition")
        self.assertIsInstance(real, GameDefinitionResult)
        sourced = [f for f in real.failures if f["source"] is not None]
        self.assertTrue(sourced)
        result, _ = self.run_failing("create_game_definition", real)
        self.assertEqual(result.failures, real.failures)
        for mine, theirs in zip(result.failures, real.failures):
            self.assertEqual(mine["source"], theirs["source"])
            if mine["source"] is not None:
                self.assertIsNot(mine["source"], theirs["source"])

    def test_24_later_changes_to_the_factory_failures_do_not_reach_the_result(self):
        failures = [{"code": "GAME_PROJECT_A", "field": "f", "message": "m"}]
        outcome = mock.Mock(ok=False, failures=failures)
        result, _ = self.run_failing("create_game_project", outcome)
        failures[0]["code"] = "CHANGED"
        failures.append({"code": "EXTRA", "field": None, "message": "x"})
        self.assertEqual(result.codes(), ["GAME_PROJECT_A"])

    def test_25_a_failed_result_is_never_ok_even_with_a_definition_left_in_the_factory_result(self):
        definition = create_game_definition_from_request(make_request()).definition
        outcome = mock.Mock(ok=False, definition=definition, failures=[{"code": "GAME_DEFINITION_X", "field": None, "message": "m", "source": None}])
        result, _ = self.run_failing("create_game_definition", outcome)
        self.assertFalse(result.ok)
        self.assertIsNone(result.definition)

    def test_26_the_existing_factory_results_keep_their_own_types(self):
        self.assertIsInstance(create_game_definition_from_request(make_request()), GameDefinitionFromRequestResult)
        self.assertNotIsInstance(create_game_definition_from_request(make_request()), GameDefinitionResult)


class TestNoMutation(unittest.TestCase):
    def test_27_the_request_cannot_be_changed(self):
        request = make_request()
        for field in FIELDS:
            with self.assertRaises(AttributeError):
                setattr(request, field, "x")
            with self.assertRaises(AttributeError):
                delattr(request, field)
        with self.assertRaises(AttributeError):
            request.extra = 1

    def test_28_the_bridge_leaves_the_request_unchanged(self):
        request = make_request()
        before = (request.to_dict(), hash(request), [id(getattr(request, f)) for f in FIELDS])
        create_game_definition_from_request(request)
        outcome = mock.Mock(ok=False, failures=[{"code": "X", "field": None, "message": "m"}])
        with mock.patch.object(bridge, "create_game_project_structure", return_value=outcome):
            create_game_definition_from_request(request)
        self.assertEqual((request.to_dict(), hash(request), [id(getattr(request, f)) for f in FIELDS]), before)

    def test_29_only_the_six_public_properties_are_read_from_the_request(self):
        request = make_request()
        accessed = []
        original = GameCreationRequest.__getattribute__

        def spy(self, name):
            accessed.append((name, sys._getframe(1).f_code.co_filename))
            return original(self, name)
        with mock.patch.object(GameCreationRequest, "__getattribute__", spy):
            result = create_game_definition_from_request(request)
        self.assertTrue(result.ok)
        mine = [n for n, where in accessed if os.path.abspath(where) == os.path.abspath(SOURCE)]
        self.assertEqual(sorted(mine), sorted(FIELDS))
        for name in mine:
            self.assertFalse(name.startswith("_"), name)

    def test_30_nothing_module_level_is_mutated_by_calls(self):
        keys = list(vars(bridge))
        for _ in range(3):
            create_game_definition_from_request(make_request())
            create_game_definition_from_request(None)
        self.assertEqual(list(vars(bridge)), keys)
        for name, value in vars(bridge).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set, bytearray), name)

    def test_31_the_definition_it_returns_is_immutable_and_protected(self):
        d = create_game_definition_from_request(make_request()).definition
        for name in ("project", "structure", "scene_registry", "extra"):
            with self.assertRaises(AttributeError):
                setattr(d, name, 1)
        first, second = d.to_dict(), d.to_dict()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        first["structure"]["scenes"].append("tampered")
        self.assertEqual(d.to_dict(), second)


class TestResultProtections(unittest.TestCase):
    def valid(self):
        return create_game_definition_from_request(make_request())

    def invalid(self):
        return create_game_definition_from_request(None)

    def test_32_attributes_are_read_only(self):
        for result in (self.valid(), self.invalid()):
            for name in ("ok", "definition", "failures", "_definition", "_failures", "extra"):
                with self.assertRaises(AttributeError, msg=name):
                    setattr(result, name, 1)
            for name in ("ok", "definition", "failures", "_definition", "_failures"):
                with self.assertRaises(AttributeError, msg=name):
                    delattr(result, name)
            self.assertFalse(hasattr(result, "__dict__"))

    def test_33_deterministic_equality_and_hash(self):
        a, b = self.valid(), self.valid()
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, self.invalid())
        self.assertEqual(self.invalid(), self.invalid())
        self.assertEqual(hash(self.invalid()), hash(self.invalid()))
        self.assertNotEqual(a, a.to_dict())
        self.assertFalse(a == object())

    def test_34_to_dict_failures_and_codes_are_fresh_every_call(self):
        for result in (self.valid(), self.invalid()):
            first, second = result.to_dict(), result.to_dict()
            self.assertEqual(first, second)
            self.assertIsNot(first, second)
            self.assertIsNot(first["failures"], second["failures"])
            if first["definition"] is not None:
                self.assertIsNot(first["definition"], second["definition"])
                self.assertIsNot(first["definition"]["structure"]["scenes"], second["definition"]["structure"]["scenes"])
                first["definition"]["structure"]["scenes"].append("tampered")
                first["definition"]["project"]["name"] = "tampered"
            first["ok"] = "tampered"
            first["failures"].append({"code": "X"})
            self.assertEqual(result.to_dict(), second)
            self.assertIsNot(result.failures, result.failures)
            for item in result.failures:
                item["code"] = "tampered"
            result.codes().append("X")
            self.assertEqual(result.to_dict(), second)

    def test_35_failure_sources_are_fresh_every_call(self):
        real = real_failure_for("create_game_definition")
        outcome = real
        with mock.patch.object(bridge, "create_game_definition", return_value=outcome):
            result = create_game_definition_from_request(make_request())
        a, b = result.failures, result.failures
        sourced = [i for i, f in enumerate(a) if f["source"] is not None]
        self.assertTrue(sourced)
        for i in sourced:
            self.assertIsNot(a[i]["source"], b[i]["source"])
            a[i]["source"]["code"] = "tampered"
        self.assertEqual(result.failures, b)

    def test_36_direct_construction_is_refused(self):
        definition = self.valid().definition
        for args in ((), (None, None, []), (object(), definition, []), (None, definition, [])):
            with self.assertRaises(TypeError):
                GameDefinitionFromRequestResult(*args)

    def test_37_subclassing_is_refused(self):
        with self.assertRaises(TypeError):
            class Sub(GameDefinitionFromRequestResult):
                pass

    def test_38_copy_and_deepcopy_return_the_same_object(self):
        for result in (self.valid(), self.invalid()):
            self.assertIs(copy.copy(result), result)
            self.assertIs(copy.deepcopy(result), result)
            self.assertIs(copy.deepcopy({"r": result})["r"], result)

    def test_39_pickle_is_refused(self):
        for result in (self.valid(), self.invalid()):
            for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(result, protocol)

    def test_40_codes_repr_and_constants_follow_the_convention(self):
        self.assertEqual(self.valid().codes(), [])
        self.assertEqual(self.invalid().codes(), [INVALID_REQUEST])
        self.assertIsNot(self.invalid().codes(), self.invalid().codes())
        self.assertEqual(repr(self.valid()), "GameDefinitionFromRequestResult(ok=True, failures=0)")
        self.assertEqual(repr(self.invalid()), "GameDefinitionFromRequestResult(ok=False, failures=1)")
        self.assertEqual(bridge.FAILURE_PREFIX, "GAME_DEFINITION_FROM_REQUEST_")
        self.assertEqual(bridge.FAILURE_INVALID_REQUEST, INVALID_REQUEST)
        self.assertEqual(bridge.FAILURE_CODES, (INVALID_REQUEST,))


class TestSourcePins(unittest.TestCase):
    def test_41_no_private_attribute_is_used_outside_the_result_class_and_only_public_results_are_read(self):
        tree = source_tree()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("_") and not node.attr.startswith("__"):
                self.assertIn(ast.unparse(node.value), ("self", "other"), ast.unparse(node))
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_game_definition_from_request")
        attrs = {n.attr for n in ast.walk(func) if isinstance(n, ast.Attribute)}
        self.assertEqual(attrs, set(FIELDS) | {"ok", "failures", "project", "structure", "registry", "definition"})

    def test_42_imports_are_exactly_the_request_type_and_the_public_factories(self):
        tree = source_tree()
        imports = [ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [
            "from .game_asset_registry import create_game_asset_registry",
            "from .game_character_registry import create_game_character_registry",
            "from .game_creation_request import GameCreationRequest",
            "from .game_definition import create_game_definition",
            "from .game_project import create_game_project",
            "from .game_project_structure import create_game_project_structure",
            "from .game_scene_bundle_registry import create_game_scene_bundle_registry",
            "from .game_scene_composition_registry import create_game_scene_composition_registry",
            "from .game_scene_registry import create_game_scene_registry",
            "from .gameplay_system_registry import create_gameplay_system_registry"])

    def test_43_only_the_public_factories_are_called_and_no_validation_is_duplicated(self):
        tree = source_tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for name in ORDER:
            self.assertIn(name, calls)
        for method in ("strip", "lstrip", "rstrip", "lower", "upper", "casefold", "normalize", "title", "replace", "join", "split", "str", "int", "bool",
                       "copy", "deepcopy", "list", "sorted", "set", "getattr", "setattr", "hasattr", "vars", "isinstance"):
            self.assertFalse([c for c in calls if c == method or c.endswith("." + method)], method)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("GameProject", "GameProjectStructure", "GameDefinition", "GameDefinitionResult", "GameSceneRegistry", "GameCharacterRegistry",
                          "GameplaySystemRegistry", "GameAssetRegistry", "GameSceneCompositionRegistry", "GameSceneBundleRegistry",
                          "validate_game_project", "validate_game_scene_composition", "create_game_creation_request", "FIELDS", "_check_collection",
                          "create_game_project_from_request", "create_game_project_structure_from_request", "lookup",
                          "Core", "Planner", "AgentLoop", "process_input", "os", "sys", "socket", "sqlite3", "random", "time", "datetime", "pickle",
                          "subprocess", "threading", "requests", "urllib"):
            self.assertNotIn(forbidden, names)

    def test_44_dependency_direction_no_existing_module_knows_the_bridge(self):
        needles = ("game_definition_from_request", "create_game_definition_from_request", "GameDefinitionFromRequestResult")
        for rel in sorted(os.listdir(PKG)):
            if rel.endswith(".py") and rel != "game_definition_from_request.py":
                with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
                    text = fh.read()
                for token in needles:
                    self.assertNotIn(token, text, (rel, token))

    def test_45_no_other_production_module_imports_the_bridge_and_nothing_is_wired(self):
        needles = ("game_definition_from_request", "create_game_definition_from_request", "GameDefinitionFromRequestResult")
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "data")]
            for name in files:
                if name.endswith(".py") and os.path.join(folder, name) != SOURCE:
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    for needle in needles:
                        self.assertNotIn(needle, text, os.path.join(folder, name))

    def test_46_one_public_function_one_class_no_module_state_no_io(self):
        tree = source_tree()
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")],
                         ["create_game_definition_from_request"])
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.ClassDef)], ["GameDefinitionFromRequestResult"])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))

    def test_47_core_input_planner_and_agent_loop_do_not_know_the_bridge(self):
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_definition_from_request", "create_game_definition_from_request"):
                self.assertNotIn(token, text, (rel, token))

    def test_48_package_listing_has_exactly_the_one_new_module(self):
        self.assertEqual(sorted(os.listdir(PKG)), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py",
            "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py",
            "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py",
            "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py",
            "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py",
            "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])


class TestScopeAndDocumentation(unittest.TestCase):
    def test_49_pristine_database_no_bytecode(self):
        self.assertEqual(sha(PROJECT_DB), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)

    def test_50_documentation_names_the_contract(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_game_definition_from_request", "GameDefinitionFromRequestResult", "create_game_definition", "create_game_project",
                       "create_game_project_structure", "GAME_DEFINITION_FROM_REQUEST_", "GAME_DEFINITION_FROM_REQUEST_INVALID_REQUEST",
                       "GameCreationRequest -> bridge", "empty", "invent", "unchanged", "identity", "does NOT", "Prompt 742", "Prompt 743"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
