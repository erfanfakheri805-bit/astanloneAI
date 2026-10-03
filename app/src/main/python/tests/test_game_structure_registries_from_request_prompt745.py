"""Prompt 745 - Section 7 game structure registries-from-request bridge (`game_creation.game_structure_registries_from_request`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import types
import unittest
from unittest import mock

from game_creation import game_structure_registries_from_request as bridge
from game_creation.game_asset_registry import GameAssetRegistry, GameAssetRegistryResult, create_game_asset_registry
from game_creation.game_character_registry import GameCharacterRegistry, GameCharacterRegistryResult, create_game_character_registry
from game_creation.game_creation_request import create_game_creation_request
from game_creation.game_project_structure import create_game_project_structure
from game_creation.game_scene_registry import GameSceneRegistry, GameSceneRegistryResult, create_game_scene_registry
from game_creation.game_structure_registries_from_request import (GameStructureRegistriesFromRequestResult,
                                                                   create_game_structure_registries_from_request)
from game_creation.game_structure_request import GameStructureRequest, create_game_structure_request
from game_creation.gameplay_system_registry import GameplaySystemRegistry, GameplaySystemRegistryResult, create_gameplay_system_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
PKG = os.path.join(PY_ROOT, "game_creation")
SOURCE = os.path.join(PKG, "game_structure_registries_from_request.py")
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_structure_registries_from_request_prompt745.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

FIELDS = ("scenes", "characters", "gameplay_systems", "assets")
KEYS = ("scene_registry", "character_registry", "gameplay_system_registry", "asset_registry")
INVALID_REQUEST = "GAME_STRUCTURE_REGISTRIES_FROM_REQUEST_INVALID_REQUEST"
EMPTY = {f: [] for f in FIELDS}
FACTORIES = (("create_game_scene_registry", GameSceneRegistryResult, "scenes"),
             ("create_game_character_registry", GameCharacterRegistryResult, "characters"),
             ("create_gameplay_system_registry", GameplaySystemRegistryResult, "gameplay_systems"),
             ("create_game_asset_registry", GameAssetRegistryResult, "assets"))
REAL = {"create_game_scene_registry": create_game_scene_registry, "create_game_character_registry": create_game_character_registry,
        "create_gameplay_system_registry": create_gameplay_system_registry, "create_game_asset_registry": create_game_asset_registry}


def good(**over):
    d = {"scenes": [], "characters": [], "gameplay_systems": ["combat", "inventory"], "assets": []}
    d.update(over)
    return d


def make_request(data=None):
    result = create_game_structure_request(good() if data is None else data)
    assert result.ok, result.failures
    return result.request


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def source_tree():
    with open(SOURCE, encoding="utf-8") as fh:
        return ast.parse(fh.read())


def spy_all(order, returned=None):
    """Patch the four factory names in the bridge with recording wrappers around the REAL factories."""
    patches = []
    mocks = {}
    for name, _cls, _field in FACTORIES:
        def make(n):
            def side(*args, **kwargs):
                order.append(n)
                r = REAL[n](*args, **kwargs)
                if returned is not None:
                    returned[n] = r
                return r
            return side
        p = mock.patch.object(bridge, name, side_effect=make(name))
        mocks[name] = p.start()
        patches.append(p)
    return patches, mocks


def stop_all(patches):
    for p in patches:
        p.stop()


def failure(code, field="x", message="m"):
    return {"code": code, "field": field, "message": message}


class TestValidRequest(unittest.TestCase):
    def test_01_valid_request_creates_all_four_registries(self):
        result = create_game_structure_registries_from_request(make_request())
        self.assertIsInstance(result, GameStructureRegistriesFromRequestResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.codes(), [])
        regs = result.registries
        self.assertEqual(list(regs), list(KEYS))
        self.assertIsInstance(regs["scene_registry"], GameSceneRegistry)
        self.assertIsInstance(regs["character_registry"], GameCharacterRegistry)
        self.assertIsInstance(regs["gameplay_system_registry"], GameplaySystemRegistry)
        self.assertIsInstance(regs["asset_registry"], GameAssetRegistry)
        self.assertEqual(regs["gameplay_system_registry"].gameplay_system_ids, ("combat", "inventory"))
        self.assertEqual(result.to_dict(), {"ok": True, "registries": {
            "scene_registry": {"scenes": []}, "character_registry": {"characters": []},
            "gameplay_system_registry": {"gameplay_systems": ["combat", "inventory"]}, "asset_registry": {"assets": []}}, "failures": []})

    def test_02_registries_equal_what_the_factories_build_directly(self):
        request = make_request()
        regs = create_game_structure_registries_from_request(request).registries
        self.assertEqual(regs["scene_registry"], create_game_scene_registry(list(request.scenes)).registry)
        self.assertEqual(regs["character_registry"], create_game_character_registry(list(request.characters)).registry)
        self.assertEqual(regs["gameplay_system_registry"], create_gameplay_system_registry(list(request.gameplay_systems)).registry)
        self.assertEqual(regs["asset_registry"], create_game_asset_registry(list(request.assets)).registry)

    def test_03_empty_collections(self):
        result = create_game_structure_registries_from_request(make_request(EMPTY))
        self.assertTrue(result.ok)
        regs = result.registries
        self.assertEqual(regs["scene_registry"].scenes, ())
        self.assertEqual(regs["character_registry"].characters, ())
        self.assertEqual(regs["gameplay_system_registry"].gameplay_system_ids, ())
        self.assertEqual(regs["asset_registry"].assets, ())
        self.assertEqual(result.to_dict()["registries"], {"scene_registry": {"scenes": []}, "character_registry": {"characters": []},
                                                          "gameplay_system_registry": {"gameplay_systems": []}, "asset_registry": {"assets": []}})

    def test_04_tuple_and_list_requests_give_equal_results(self):
        a = create_game_structure_registries_from_request(make_request({"scenes": (), "characters": (), "gameplay_systems": ("p", "q"), "assets": ()}))
        b = create_game_structure_registries_from_request(make_request({"scenes": [], "characters": [], "gameplay_systems": ["p", "q"], "assets": []}))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_05_exact_ordering_is_preserved(self):
        ids = ["z", "a", "m", "B", "A", "10", "9", " a ", "\tTab"]
        result = create_game_structure_registries_from_request(make_request(good(gameplay_systems=ids)))
        self.assertTrue(result.ok)
        self.assertEqual(result.registries["gameplay_system_registry"].gameplay_system_ids, tuple(ids))
        self.assertEqual(result.to_dict()["registries"]["gameplay_system_registry"]["gameplay_systems"], ids)

    def test_06_items_are_never_normalized_trimmed_casefolded_or_deduplicated(self):
        ids = [" a ", "a", "A", "\u00a0x\u00a0", "Ünïcödé 🎮", "a b", "a  b"]
        request = make_request(good(gameplay_systems=ids))
        kept = create_game_structure_registries_from_request(request).registries["gameplay_system_registry"].gameplay_system_ids
        self.assertEqual(kept, tuple(ids))
        for given, got in zip(request.gameplay_systems, kept):
            self.assertIs(given, got)      # string identity preserved

    def test_07_string_identity_reaches_the_factory_that_receives_it(self):
        request = make_request(good(scenes=["s1", "s2"], gameplay_systems=["g1", "g2"]))
        order, _returned = [], {}
        patches, mocks = spy_all(order)
        try:
            result = create_game_structure_registries_from_request(request)
        finally:
            stop_all(patches)
        self.assertFalse(result.ok)      # the real scene factory rejects identifier strings; the bridge does not turn them into records
        (arg,), _kwargs = mocks["create_game_scene_registry"].call_args
        self.assertIs(arg, request.scenes)
        for given, kept in zip(arg, request.scenes):
            self.assertIs(given, kept)

    def test_08_each_factory_receives_the_request_tuples_unchanged(self):
        data = good(gameplay_systems=["g1", "g2"])
        request = make_request(data)
        order, returned = [], {}
        patches, mocks = spy_all(order, returned)
        try:
            result = create_game_structure_registries_from_request(request)
        finally:
            stop_all(patches)
        self.assertTrue(result.ok)
        for name, _cls, field in FACTORIES:
            (arg,), kwargs = mocks[name].call_args
            self.assertEqual(kwargs, {}, name)
            self.assertIs(arg, getattr(request, field), name)      # the request's own immutable tuple: nothing adapted, nothing copied
            self.assertIs(type(arg), tuple, name)
            for given, kept in zip(arg, getattr(request, field)):
                self.assertIs(given, kept)

    def test_09_deterministic_equal_results(self):
        a = create_game_structure_registries_from_request(make_request())
        b = create_game_structure_registries_from_request(make_request())
        self.assertIsNot(a.registries["gameplay_system_registry"], b.registries["gameplay_system_registry"])      # new registries per call
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, create_game_structure_registries_from_request(make_request(good(gameplay_systems=["other"]))))

    def test_10_a_non_empty_scene_character_or_asset_is_reported_by_that_factory_unchanged(self):
        # the request holds identifier strings; scene/character/asset registries take record objects, and the bridge invents none
        for field, code in (("scenes", "GAME_SCENE_REGISTRY_INVALID_SCENE"), ("characters", "GAME_CHARACTER_REGISTRY_INVALID_CHARACTER"),
                            ("assets", "GAME_ASSET_REGISTRY_INVALID_ASSET")):
            result = create_game_structure_registries_from_request(make_request(good(**{field: ["x"]})))
            self.assertFalse(result.ok, field)
            self.assertIsNone(result.registries)
            self.assertEqual(result.codes(), [code])
            self.assertEqual(result.failures[0]["field"], field)


class TestInvalidRequest(unittest.TestCase):
    def assert_invalid(self, value):
        patches, mocks = [], {}
        for name, _cls, _field in FACTORIES:
            p = mock.patch.object(bridge, name)
            mocks[name] = p.start()
            patches.append(p)
        try:
            result = create_game_structure_registries_from_request(value)
        finally:
            stop_all(patches)
        for name, m in mocks.items():
            m.assert_not_called()
        self.assertIsInstance(result, GameStructureRegistriesFromRequestResult)
        self.assertFalse(result.ok)
        self.assertIsNone(result.registries)
        self.assertEqual(result.codes(), [INVALID_REQUEST])
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(set(result.failures[0]), {"code", "field", "message"})
        self.assertEqual(result.failures[0]["field"], "request")
        self.assertEqual(result.to_dict(), {"ok": False, "registries": None, "failures": result.failures})
        return result

    def test_11_wrong_object_types_are_rejected(self):
        creation = create_game_creation_request({"project_id": "p", "name": "n", "description": "", "genre": "", "target_platform": "", "version": "1"})
        structure = create_game_project_structure(good()).structure
        for value in (None, good(), EMPTY, [], (), "request", 1, 1.5, True, object(), GameStructureRequest, create_game_structure_request(good()),
                      creation, creation.request, structure, create_game_scene_registry([]).registry, create_game_scene_registry([])):
            self.assert_invalid(value)

    def test_12_look_alikes_and_mocks_are_rejected(self):
        class LookAlike:
            scenes, characters, gameplay_systems, assets = ("a",), (), (), ()

        class D(dict):
            pass
        self.assert_invalid(LookAlike())
        self.assert_invalid(mock.Mock(spec=GameStructureRequest))
        self.assert_invalid(D(good()))
        self.assert_invalid(types.SimpleNamespace(scenes=(), characters=(), gameplay_systems=(), assets=()))

    def test_13_the_invalid_failure_is_deterministic_and_uses_the_bridge_prefix(self):
        a, b = self.assert_invalid(None), self.assert_invalid(None)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.failures, b.failures)
        self.assertTrue(a.failures[0]["code"].startswith(bridge.FAILURE_PREFIX))

    def test_14_never_raises_for_bad_input(self):
        for value in (None, 0, "", b"", [], {}, set(), object(), type, lambda: None, float("nan")):
            self.assertFalse(create_game_structure_registries_from_request(value).ok)
        with self.assertRaises(TypeError):      # wrong argument COUNT is a Python call error, not bad data
            create_game_structure_registries_from_request()

    def test_15_a_subclass_cannot_exist_so_exact_type_is_the_only_acceptable_type(self):
        with self.assertRaises(TypeError):
            type("Sub", (GameStructureRequest,), {})


class TestFactoryOrderAndShortCircuit(unittest.TestCase):
    def test_16_the_four_factories_are_called_exactly_once_in_order(self):
        order = []
        patches, mocks = spy_all(order)
        try:
            result = create_game_structure_registries_from_request(make_request())
        finally:
            stop_all(patches)
        self.assertTrue(result.ok)
        self.assertEqual(order, ["create_game_scene_registry", "create_game_character_registry", "create_gameplay_system_registry",
                                 "create_game_asset_registry"])
        for m in mocks.values():
            self.assertEqual(m.call_count, 1)

    def test_17_first_failure_short_circuits_every_later_factory(self):
        for index in range(4):
            calls = []
            patches = []
            for i, (name, cls, _field) in enumerate(FACTORIES):
                def make(n, i=i, cls=cls):
                    def side(arg):
                        calls.append(n)
                        if i == index:
                            return cls(failures=[failure("FIRST_%d" % i)])
                        return REAL[n](arg)
                    return side
                p = mock.patch.object(bridge, name, side_effect=make(name))
                p.start()
                patches.append(p)
            try:
                result = create_game_structure_registries_from_request(make_request())
            finally:
                stop_all(patches)
            self.assertEqual(calls, [n for n, _c, _f in FACTORIES[:index + 1]], index)      # earlier ones ran once; later ones never
            self.assertFalse(result.ok)
            self.assertIsNone(result.registries)
            self.assertEqual(result.codes(), ["FIRST_%d" % index])

    def test_18_when_several_factories_would_fail_only_the_first_one_is_reported(self):
        calls = []
        patches = []
        for i, (name, cls, _field) in enumerate(FACTORIES):
            def make(n, i=i, cls=cls):
                def side(arg):
                    calls.append(n)
                    return cls(failures=[failure("FAIL_%d" % i)])
                return side
            p = mock.patch.object(bridge, name, side_effect=make(name))
            p.start()
            patches.append(p)
        try:
            result = create_game_structure_registries_from_request(make_request())
        finally:
            stop_all(patches)
        self.assertEqual(calls, ["create_game_scene_registry"])
        self.assertEqual(result.codes(), ["FAIL_0"])

    def test_19_real_scene_failure_stops_before_character_gameplay_and_asset(self):
        order = []
        patches, mocks = spy_all(order)
        try:
            result = create_game_structure_registries_from_request(make_request(good(scenes=["menu"], characters=["hero"], assets=["a"])))
        finally:
            stop_all(patches)
        self.assertEqual(order, ["create_game_scene_registry"])
        self.assertEqual(result.codes(), ["GAME_SCENE_REGISTRY_INVALID_SCENE"])

    def test_20_real_character_failure_runs_scene_only_before_it(self):
        order = []
        patches, _mocks = spy_all(order)
        try:
            result = create_game_structure_registries_from_request(make_request(good(characters=["hero"], assets=["a"])))
        finally:
            stop_all(patches)
        self.assertEqual(order, ["create_game_scene_registry", "create_game_character_registry"])
        self.assertEqual(result.codes(), ["GAME_CHARACTER_REGISTRY_INVALID_CHARACTER"])

    def test_21_real_asset_failure_runs_all_four_and_reports_only_the_asset_failure(self):
        order = []
        patches, _mocks = spy_all(order)
        try:
            result = create_game_structure_registries_from_request(make_request(good(assets=["a"])))
        finally:
            stop_all(patches)
        self.assertEqual(len(order), 4)
        self.assertEqual(result.codes(), ["GAME_ASSET_REGISTRY_INVALID_ASSET"])
        self.assertIsNone(result.registries)

    def test_22_only_the_failing_factorys_properties_were_read(self):
        request = make_request(good(scenes=["menu"]))
        accessed = []
        original = GameStructureRequest.__getattribute__

        def spy(self, name):
            if os.path.abspath(sys._getframe(1).f_code.co_filename) == os.path.abspath(SOURCE):
                accessed.append(name)
            return original(self, name)
        with mock.patch.object(GameStructureRequest, "__getattribute__", spy):
            create_game_structure_registries_from_request(request)
        self.assertEqual(accessed, ["scenes"])      # the later properties are never touched after the first failure


class TestFailurePropagationAndIdentity(unittest.TestCase):
    FAILURES = [failure("GAME_SCENE_REGISTRY_INVALID_COLLECTION", "scenes", "scenes must be a list."),
                failure("SOMETHING_NEW_THE_BRIDGE_HAS_NEVER_HEARD_OF", None, "A failure the bridge does not know."),
                failure("GAME_SCENE_REGISTRY_DUPLICATE_SCENE_ID", "scenes", "dup")]

    def run_with_failing(self, index, failures):
        cls = FACTORIES[index][1]
        patches = []
        for i, (name, c, _field) in enumerate(FACTORIES):
            if i == index:
                p = mock.patch.object(bridge, name, return_value=cls(failures=failures))
            else:
                p = mock.patch.object(bridge, name, side_effect=REAL[name])
            p.start()
            patches.append(p)
        try:
            return create_game_structure_registries_from_request(make_request())
        finally:
            stop_all(patches)

    def test_23_failures_of_every_factory_are_exposed_unchanged_and_in_order(self):
        for index in range(4):
            fails = [dict(f) for f in self.FAILURES]
            result = self.run_with_failing(index, fails)
            self.assertFalse(result.ok, index)
            self.assertIsNone(result.registries)
            self.assertEqual(result.failures, self.FAILURES)
            self.assertEqual(result.codes(), [f["code"] for f in self.FAILURES])
            self.assertEqual(result.to_dict(), {"ok": False, "registries": None, "failures": self.FAILURES})

    def test_24_no_failure_is_invented_or_recoded(self):
        result = self.run_with_failing(2, [dict(self.FAILURES[0])])
        self.assertEqual(result.codes(), [self.FAILURES[0]["code"]])
        self.assertNotIn(INVALID_REQUEST, result.codes())
        self.assertFalse(result.codes()[0].startswith(bridge.FAILURE_PREFIX))

    def test_25_the_real_factory_failure_shape_is_preserved(self):
        real = create_game_scene_registry(("x",))
        self.assertFalse(real.ok)
        result = create_game_structure_registries_from_request(make_request(good(scenes=["x"])))
        self.assertEqual(result.failures, real.failures)
        self.assertEqual(result.codes(), real.codes())

    def test_26_later_changes_to_the_factory_failures_do_not_reach_the_result(self):
        fails = [dict(f) for f in self.FAILURES]
        result = self.run_with_failing(0, fails)
        fails[0]["code"] = "CHANGED"
        fails.append(failure("EXTRA"))
        self.assertEqual(result.failures, self.FAILURES)

    def test_27_registry_objects_returned_by_the_factories_are_preserved(self):
        order, returned = [], {}
        patches, _mocks = spy_all(order, returned)
        try:
            result = create_game_structure_registries_from_request(make_request())
        finally:
            stop_all(patches)
        regs = result.registries
        for key, (name, _cls, _field) in zip(KEYS, FACTORIES):
            self.assertIs(regs[key], returned[name].registry, key)

    def test_28_sentinel_registries_from_replaced_factories_are_exposed_as_is(self):
        sentinels = [create_game_scene_registry([]).registry, create_game_character_registry([]).registry, create_gameplay_system_registry(["only"]).registry,
                     create_game_asset_registry([]).registry]
        patches = []
        for (name, cls, _field), registry in zip(FACTORIES, sentinels):
            p = mock.patch.object(bridge, name, return_value=cls(registry=registry))
            p.start()
            patches.append(p)
        try:
            result = create_game_structure_registries_from_request(make_request(good(scenes=["ignored"])))      # the bridge adds no rule of its own
        finally:
            stop_all(patches)
        self.assertTrue(result.ok)
        for key, sentinel in zip(KEYS, sentinels):
            self.assertIs(result.registries[key], sentinel)
            self.assertIs(result.registries[key], result.registries[key])

    def test_29_the_factories_still_return_their_own_mutable_result_types(self):
        self.assertIsInstance(create_game_scene_registry([]), GameSceneRegistryResult)
        self.assertIsInstance(create_gameplay_system_registry([]), GameplaySystemRegistryResult)
        self.assertNotIsInstance(create_game_structure_registries_from_request(make_request()), GameplaySystemRegistryResult)


class TestNoMutationAndPublicApiOnly(unittest.TestCase):
    def snapshot(self, request):
        return (request.to_dict(), hash(request), [id(getattr(request, f)) for f in FIELDS], [getattr(request, f) for f in FIELDS])

    def test_30_the_bridge_leaves_the_request_unchanged(self):
        request = make_request(good(scenes=["s"], gameplay_systems=["g1", "g2"]))
        before = self.snapshot(request)
        create_game_structure_registries_from_request(request)
        create_game_structure_registries_from_request(make_request(good(gameplay_systems=["g1"])))
        self.assertEqual(self.snapshot(request), before)
        for f in FIELDS:
            self.assertIs(type(getattr(request, f)), tuple)

    def test_31_results_are_independent_of_the_original_input(self):
        data = good()
        request = make_request(data)
        result = create_game_structure_registries_from_request(request)
        data["gameplay_systems"].append("added")
        data["scenes"].append("added")
        self.assertEqual(result.registries["gameplay_system_registry"].gameplay_system_ids, ("combat", "inventory"))
        self.assertEqual(request.to_dict(), good())

    def test_32_the_existing_factories_and_their_failure_codes_are_unchanged(self):
        from game_creation import game_asset_registry, game_character_registry, game_scene_registry, gameplay_system_registry
        self.assertIs(bridge.create_game_scene_registry, game_scene_registry.create_game_scene_registry)
        self.assertIs(bridge.create_game_character_registry, game_character_registry.create_game_character_registry)
        self.assertIs(bridge.create_gameplay_system_registry, gameplay_system_registry.create_gameplay_system_registry)
        self.assertIs(bridge.create_game_asset_registry, game_asset_registry.create_game_asset_registry)
        self.assertEqual(len(game_scene_registry.FAILURE_CODES), 6)
        self.assertEqual(game_scene_registry.FAILURE_INVALID_SCENE, "GAME_SCENE_REGISTRY_INVALID_SCENE")
        self.assertEqual(game_character_registry.FAILURE_INVALID_CHARACTER, "GAME_CHARACTER_REGISTRY_INVALID_CHARACTER")
        self.assertEqual(gameplay_system_registry.FAILURE_INVALID_GAMEPLAY_SYSTEM, "GAMEPLAY_SYSTEM_REGISTRY_INVALID_GAMEPLAY_SYSTEM")
        self.assertEqual(game_asset_registry.FAILURE_INVALID_ASSET, "GAME_ASSET_REGISTRY_INVALID_ASSET")

    def test_33_only_the_four_public_properties_are_read_in_order(self):
        request = make_request()
        accessed = []
        original = GameStructureRequest.__getattribute__

        def spy(self, name):
            if os.path.abspath(sys._getframe(1).f_code.co_filename) == os.path.abspath(SOURCE):
                accessed.append(name)
            return original(self, name)
        with mock.patch.object(GameStructureRequest, "__getattribute__", spy):
            result = create_game_structure_registries_from_request(request)
        self.assertTrue(result.ok)
        self.assertEqual(accessed, list(FIELDS))

    def test_34_no_private_attribute_of_any_other_object_is_used(self):
        tree = source_tree()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("_") and not node.attr.startswith("__"):
                self.assertIn(ast.unparse(node.value), ("self", "other"), ast.unparse(node))      # only the result class touches its own slots
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_game_structure_registries_from_request")
        attrs = {n.attr for n in ast.walk(func) if isinstance(n, ast.Attribute)}
        self.assertEqual(attrs, {"scenes", "characters", "gameplay_systems", "assets", "ok", "registry"})

    def test_35_nothing_module_level_is_mutated_by_calls(self):
        keys = list(vars(bridge))
        for _ in range(3):
            create_game_structure_registries_from_request(make_request())
            create_game_structure_registries_from_request(make_request(good(scenes=["x"])))
            create_game_structure_registries_from_request(None)
        self.assertEqual(list(vars(bridge)), keys)
        for name, value in vars(bridge).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set, bytearray), name)
        self.assertEqual(bridge.REGISTRY_KEYS, KEYS)


class TestResultProtections(unittest.TestCase):
    def valid(self):
        return create_game_structure_registries_from_request(make_request())

    def invalid(self):
        return create_game_structure_registries_from_request(None)

    def failed(self):
        return create_game_structure_registries_from_request(make_request(good(scenes=["x"])))

    def test_36_attributes_are_read_only(self):
        for result in (self.valid(), self.invalid(), self.failed()):
            for name in ("ok", "registries", "failures", "_registries", "_failures", "extra", "codes", "to_dict"):
                with self.assertRaises(AttributeError, msg=name):
                    setattr(result, name, 1)
            for name in ("ok", "registries", "failures", "_registries", "_failures"):
                with self.assertRaises(AttributeError, msg=name):
                    delattr(result, name)
            self.assertFalse(hasattr(result, "__dict__"))
        self.assertEqual(sorted(n for n in dir(self.valid()) if not n.startswith("_")), ["codes", "failures", "ok", "registries", "to_dict"])

    def test_37_deterministic_equality_and_hash(self):
        a, b = self.valid(), self.valid()
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, self.invalid())
        self.assertNotEqual(self.invalid(), self.failed())
        self.assertEqual(self.invalid(), self.invalid())
        self.assertEqual(hash(self.failed()), hash(self.failed()))
        self.assertNotEqual(a, a.to_dict())
        self.assertFalse(a == object())

    def test_38_registries_to_dict_failures_and_codes_are_fresh_every_call(self):
        for result in (self.valid(), self.invalid(), self.failed()):
            first, second = result.to_dict(), result.to_dict()
            self.assertEqual(first, second)
            self.assertIsNot(first, second)
            self.assertIsNot(first["failures"], second["failures"])
            if first["registries"] is not None:
                self.assertIsNot(first["registries"], second["registries"])
                first["registries"]["scene_registry"]["scenes"].append("tampered")
                first["registries"]["extra"] = 1
            first["ok"] = "tampered"
            first["failures"].append({"code": "X"})
            self.assertEqual(result.to_dict(), second)
            self.assertIsNot(result.failures, result.failures)
            for item in result.failures:
                item["code"] = "tampered"
            result.codes().append("X")
            self.assertEqual(result.to_dict(), second)
        ok = self.valid()
        d1, d2 = ok.registries, ok.registries
        self.assertIsNot(d1, d2)
        self.assertEqual(d1, d2)
        d1["extra"] = 1
        d1["scene_registry"] = None
        self.assertEqual(list(ok.registries), list(KEYS))
        self.assertIsNotNone(ok.registries["scene_registry"])
        for key in KEYS:
            self.assertIs(d2[key], ok.registries[key])      # fresh container, the very same immutable registry objects
        bad = self.invalid()
        self.assertIsNot(bad.failures[0], bad.failures[0])
        self.assertIsNot(bad.codes(), bad.codes())
        self.assertIsNone(bad.registries)

    def test_39_direct_construction_is_refused(self):
        regs = (create_game_scene_registry([]).registry, create_game_character_registry([]).registry,
                create_gameplay_system_registry([]).registry, create_game_asset_registry([]).registry)
        for args in ((), (None, None, []), (object(), regs, []), (None, regs, []), (True, regs, [])):
            with self.assertRaises(TypeError):
                GameStructureRegistriesFromRequestResult(*args)

    def test_40_subclassing_is_refused(self):
        with self.assertRaises(TypeError):
            class Sub(GameStructureRegistriesFromRequestResult):
                pass

    def test_41_copy_and_deepcopy_return_the_same_object(self):
        for result in (self.valid(), self.invalid(), self.failed()):
            self.assertIs(copy.copy(result), result)
            self.assertIs(copy.deepcopy(result), result)
            self.assertIs(copy.deepcopy({"r": result})["r"], result)

    def test_42_pickle_is_refused(self):
        for result in (self.valid(), self.invalid(), self.failed()):
            for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(result, protocol)

    def test_43_codes_repr_and_constants(self):
        self.assertEqual(self.valid().codes(), [])
        self.assertEqual(self.invalid().codes(), [INVALID_REQUEST])
        self.assertEqual(repr(self.valid()), "GameStructureRegistriesFromRequestResult(ok=True, failures=0)")
        self.assertEqual(repr(self.invalid()), "GameStructureRegistriesFromRequestResult(ok=False, failures=1)")
        self.assertEqual(bridge.FAILURE_PREFIX, "GAME_STRUCTURE_REGISTRIES_FROM_REQUEST_")
        self.assertEqual(bridge.FAILURE_INVALID_REQUEST, INVALID_REQUEST)
        self.assertEqual(bridge.FAILURE_CODES, (INVALID_REQUEST,))


class TestSourcePins(unittest.TestCase):
    def test_44_imports_are_exactly_the_request_type_and_the_four_public_factories(self):
        imports = [ast.unparse(n) for n in source_tree().body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, ["from .game_asset_registry import create_game_asset_registry",
                                   "from .game_character_registry import create_game_character_registry",
                                   "from .game_scene_registry import create_game_scene_registry",
                                   "from .game_structure_request import GameStructureRequest",
                                   "from .gameplay_system_registry import create_gameplay_system_registry"])

    def test_45_each_factory_is_called_once_in_order_and_no_validation_is_duplicated(self):
        tree = source_tree()
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_game_structure_registries_from_request")
        factory_calls = [ast.unparse(n.func) for n in ast.walk(func)
                         if isinstance(n, ast.Call) and ast.unparse(n.func).startswith(("create_game_", "create_gameplay_"))]
        self.assertEqual(factory_calls, ["create_game_scene_registry", "create_game_character_registry", "create_gameplay_system_registry",
                                         "create_game_asset_registry"])
        calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        for forbidden in ("list", "set", "sorted", "reversed", "tuple_of", "str", "int", "bool", "copy", "deepcopy", "getattr", "setattr", "hasattr", "vars",
                          "isinstance", "any", "all", "filter", "map", "enumerate"):
            self.assertNotIn(forbidden, calls, forbidden)      # no container adaptation and no validation helper anywhere
        for method in ("strip", "lstrip", "rstrip", "lower", "upper", "casefold", "normalize", "title", "replace", "join", "split", "copy", "sort",
                       "append", "extend", "update", "pop"):
            self.assertFalse([c for c in calls if c.endswith("." + method)], method)
        for call in factory_calls:
            node = next(n for n in ast.walk(func) if isinstance(n, ast.Call) and ast.unparse(n.func) == call)
            self.assertEqual(len(node.args), 1, call)
            self.assertEqual(node.keywords, [], call)      # the optional `structure` argument is never passed
        compares = [ast.unparse(n) for n in ast.walk(func) if isinstance(n, ast.Compare)]
        self.assertEqual(compares, ["type(request) is not GameStructureRequest"])      # the exact-type gate is the only check
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("GameProjectStructure", "create_game_project_structure", "create_game_structure_request", "GameCreationRequest", "FIELDS",
                          "_check_collection", "GameScene", "GameCharacter", "GameAsset", "create_game_scene", "create_game_character", "create_game_asset",
                          "GameSceneComposition", "GameSceneBundle", "Core", "Planner", "AgentLoop", "process_input", "os", "sys", "socket", "sqlite3",
                          "random", "time", "datetime", "pickle", "subprocess", "threading", "requests", "urllib"):
            self.assertNotIn(forbidden, names)

    def test_46_dependency_direction_request_to_bridge_to_factories(self):
        for rel in ("game_structure_request.py", "game_project_structure.py", "game_scene_registry.py", "game_character_registry.py",
                    "gameplay_system_registry.py", "game_asset_registry.py", "game_structure_request_bridge.py", "game_structure_from_request.py"):
            with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
                other = fh.read()
            for token in ("game_structure_registries_from_request", "GameStructureRegistriesFromRequestResult"):
                self.assertNotIn(token, other, (rel, token))
        with open(os.path.join(PKG, "game_structure_request.py"), encoding="utf-8") as fh:
            self.assertFalse([l for l in fh.read().splitlines() if l.startswith(("import ", "from "))])      # the request model still imports nothing
        for rel in ("game_scene_registry.py", "game_character_registry.py", "gameplay_system_registry.py", "game_asset_registry.py"):
            with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
                self.assertNotIn("GameStructureRequest", fh.read(), rel)

    def test_47_no_other_production_module_imports_the_bridge(self):
        needles = ("game_structure_registries_from_request", "GameStructureRegistriesFromRequestResult")
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "data")]
            for name in files:
                if name.endswith(".py") and os.path.join(folder, name) != SOURCE:
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    for needle in needles:
                        self.assertNotIn(needle, text, os.path.join(folder, name))

    def test_48_one_public_function_one_class_no_module_state_no_io(self):
        tree = source_tree()
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")],
                         ["create_game_structure_registries_from_request"])
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.ClassDef)], ["GameStructureRegistriesFromRequestResult"])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))

    def test_49_core_input_planner_and_agent_loop_do_not_know_the_bridge(self):
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_structure_registries_from_request", "GameStructureRegistriesFromRequestResult", "game_creation"):
                self.assertNotIn(token, text, (rel, token))

    def test_50_package_listing_has_exactly_the_one_new_module(self):
        self.assertEqual(sorted(os.listdir(PKG)), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py",
            "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py",
            "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py",
            "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py",
            "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py",
            "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py",
            "game_structure_request_bridge.py", "gameplay_system_registry.py"])

    def test_51_package_init_is_empty_of_exports(self):
        with open(os.path.join(PKG, "__init__.py"), encoding="utf-8") as fh:
            self.assertNotIn("registries_from_request", fh.read())


class TestScopeAndDocumentation(unittest.TestCase):
    def test_52_pristine_database_no_bytecode(self):
        self.assertEqual(sha(PROJECT_DB), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)

    def test_53_documentation_names_the_contract(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_game_structure_registries_from_request", "GameStructureRegistriesFromRequestResult", "GameStructureRequest",
                       "create_game_scene_registry", "create_game_character_registry", "create_gameplay_system_registry", "create_game_asset_registry",
                       "GAME_STRUCTURE_REGISTRIES_FROM_REQUEST_", "GAME_STRUCTURE_REGISTRIES_FROM_REQUEST_INVALID_REQUEST", "scene_registry",
                       "character_registry", "gameplay_system_registry", "asset_registry", "identity", "unchanged", "fresh", "tuple", "short-circuit",
                       "does NOT", "Prompt 744", "Prompt 746", "GameScene", "limitation"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
