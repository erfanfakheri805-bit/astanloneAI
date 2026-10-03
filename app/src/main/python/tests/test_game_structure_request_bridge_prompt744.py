"""Prompt 744 - Section 7 game structure request bridge (`game_creation.game_structure_request_bridge`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from game_creation import game_structure_request_bridge as bridge
from game_creation.game_creation_request import create_game_creation_request
from game_creation.game_project_structure import GameProjectStructure, GameProjectStructureResult, create_game_project_structure
from game_creation.game_structure_request import GameStructureRequest, create_game_structure_request
from game_creation.game_structure_request_bridge import GameStructureRequestBridgeResult, create_game_project_structure_from_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
PKG = os.path.join(PY_ROOT, "game_creation")
SOURCE = os.path.join(PKG, "game_structure_request_bridge.py")
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_structure_request_bridge_prompt744.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

FIELDS = ("scenes", "characters", "gameplay_systems", "assets")
INVALID_REQUEST = "GAME_STRUCTURE_REQUEST_BRIDGE_INVALID_REQUEST"
EMPTY = {f: [] for f in FIELDS}


def good(**over):
    d = {"scenes": ["menu", "level1"], "characters": ["hero", "villain"], "gameplay_systems": ["combat", "inventory"], "assets": ["hero.png", "theme.ogg"]}
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


class TestValidRequest(unittest.TestCase):
    def test_01_valid_request_creates_the_structure(self):
        result = create_game_project_structure_from_request(make_request())
        self.assertIsInstance(result, GameStructureRequestBridgeResult)
        self.assertTrue(result.ok)
        self.assertIsInstance(result.structure, GameProjectStructure)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.codes(), [])
        self.assertEqual(result.structure, create_game_project_structure(good()).structure)
        self.assertEqual(result.structure.to_dict(), good())
        self.assertEqual(result.to_dict(), {"ok": True, "structure": good(), "failures": []})

    def test_02_the_structure_holds_exactly_the_four_request_collections(self):
        s = create_game_project_structure_from_request(make_request()).structure
        for f in FIELDS:
            self.assertEqual(getattr(s, f), tuple(good()[f]), f)

    def test_03_exact_four_field_passthrough_to_the_factory(self):
        request = make_request()
        with mock.patch.object(bridge, "create_game_project_structure", wraps=create_game_project_structure) as factory:
            create_game_project_structure_from_request(request)
        self.assertEqual(factory.call_count, 1)
        (data,), kwargs = factory.call_args
        self.assertEqual(kwargs, {})
        self.assertIs(type(data), dict)
        self.assertEqual(list(data), list(FIELDS))
        for f in FIELDS:
            self.assertEqual(data[f], list(getattr(request, f)), f)
            for given, kept in zip(data[f], getattr(request, f)):
                self.assertIs(given, kept)      # the very same string objects

    def test_04_the_factory_gets_fresh_lists_because_it_accepts_only_lists(self):
        request = make_request()
        seen = []

        def spy(data):
            seen.append(data)
            return create_game_project_structure(data)
        with mock.patch.object(bridge, "create_game_project_structure", side_effect=spy):
            create_game_project_structure_from_request(request)
            create_game_project_structure_from_request(request)
        self.assertIsNot(seen[0], seen[1])
        for f in FIELDS:
            self.assertIs(type(seen[0][f]), list)
            self.assertIsNot(seen[0][f], seen[1][f])
            self.assertEqual(seen[0][f], list(getattr(request, f)))

    def test_05_ordering_is_preserved(self):
        data = {"scenes": ["z", "a", "m", "B", "A", "10", "9"], "characters": ["c3", "c1", "c2"], "gameplay_systems": ["s2", "s1"], "assets": ["t3", "t1", "t2"]}
        result = create_game_project_structure_from_request(make_request(data))
        self.assertTrue(result.ok)
        for f in FIELDS:
            self.assertEqual(getattr(result.structure, f), tuple(data[f]), f)
        self.assertEqual(result.to_dict()["structure"], data)

    def test_06_items_are_never_normalized_trimmed_casefolded_or_deduplicated(self):
        data = {"scenes": [" a ", "a", "A", "\tTab", "Ünïcödé 🎮", "\u00a0x\u00a0", "a b", "a  b"], "characters": ["x"], "gameplay_systems": [], "assets": ["x"]}
        request = make_request(data)
        s = create_game_project_structure_from_request(request).structure
        self.assertEqual(s.scenes, tuple(data["scenes"]))
        for given, kept in zip(request.scenes, s.scenes):
            self.assertIs(given, kept)
        self.assertEqual(s.characters, s.assets)      # the same item in different collections stays in both

    def test_07_empty_collections(self):
        result = create_game_project_structure_from_request(make_request(EMPTY))
        self.assertTrue(result.ok)
        for f in FIELDS:
            self.assertEqual(getattr(result.structure, f), ())
        self.assertEqual(result.to_dict(), {"ok": True, "structure": EMPTY, "failures": []})
        for f in FIELDS:
            only = {k: [] for k in FIELDS}
            only[f] = ["x"]
            self.assertEqual(create_game_project_structure_from_request(make_request(only)).structure.to_dict(), only, f)

    def test_08_tuple_and_list_requests_give_equal_results(self):
        a = create_game_project_structure_from_request(make_request({f: ("p", "q") for f in FIELDS}))
        b = create_game_project_structure_from_request(make_request({f: ["p", "q"] for f in FIELDS}))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_09_deterministic_equal_results(self):
        a = create_game_project_structure_from_request(make_request())
        b = create_game_project_structure_from_request(make_request())
        self.assertIsNot(a.structure, b.structure)      # a new structure per call, equal by content
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, create_game_project_structure_from_request(make_request(good(scenes=["other"]))))

    def test_10_the_factory_is_called_exactly_once_per_valid_call_and_never_for_invalid(self):
        with mock.patch.object(bridge, "create_game_project_structure", wraps=create_game_project_structure) as factory:
            create_game_project_structure_from_request(make_request())
            self.assertEqual(factory.call_count, 1)
            create_game_project_structure_from_request(None)
            self.assertEqual(factory.call_count, 1)


class TestInvalidRequest(unittest.TestCase):
    def assert_invalid(self, value):
        with mock.patch.object(bridge, "create_game_project_structure") as factory:
            result = create_game_project_structure_from_request(value)
        factory.assert_not_called()
        self.assertIsInstance(result, GameStructureRequestBridgeResult)
        self.assertFalse(result.ok)
        self.assertIsNone(result.structure)
        self.assertEqual(result.codes(), [INVALID_REQUEST])
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(set(result.failures[0]), {"code", "field", "message"})
        self.assertEqual(result.failures[0]["field"], "request")
        self.assertEqual(result.to_dict(), {"ok": False, "structure": None, "failures": result.failures})
        return result

    def test_11_wrong_object_types_are_rejected(self):
        creation = create_game_creation_request({"project_id": "p", "name": "n", "description": "", "genre": "", "target_platform": "", "version": "1"})
        for value in (None, good(), EMPTY, [], (), "request", 1, 1.5, True, object(), GameStructureRequest, create_game_structure_request(good()),
                      creation, creation.request, create_game_project_structure(good()).structure, create_game_project_structure(good())):
            self.assert_invalid(value)

    def test_12_look_alikes_and_mocks_are_rejected(self):
        class LookAlike:
            scenes, characters, gameplay_systems, assets = ("a",), (), (), ()

        class D(dict):
            pass
        self.assert_invalid(LookAlike())
        self.assert_invalid(mock.Mock(spec=GameStructureRequest))
        self.assert_invalid(D(good()))
        self.assert_invalid(types_namespace())

    def test_13_the_invalid_failure_is_deterministic(self):
        a, b = self.assert_invalid(None), self.assert_invalid(None)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.failures, b.failures)
        self.assertTrue(a.failures[0]["code"].startswith(bridge.FAILURE_PREFIX))

    def test_14_never_raises_for_bad_input(self):
        for value in (None, 0, "", b"", [], {}, set(), object(), type, lambda: None, float("nan")):
            self.assertFalse(create_game_project_structure_from_request(value).ok)
        with self.assertRaises(TypeError):      # wrong argument COUNT is a Python call error, not bad data
            create_game_project_structure_from_request()

    def test_15_a_subclass_cannot_exist_so_exact_type_is_the_only_acceptable_type(self):
        with self.assertRaises(TypeError):
            type("Sub", (GameStructureRequest,), {})


def types_namespace():
    import types
    return types.SimpleNamespace(scenes=(), characters=(), gameplay_systems=(), assets=())


class TestFactoryResultPropagation(unittest.TestCase):
    FAILURES = [{"code": "GAME_PROJECT_STRUCTURE_INVALID_COLLECTION", "field": "scenes", "message": "scenes must be a list."},
                {"code": "GAME_PROJECT_STRUCTURE_SOMETHING_NEW", "field": None, "message": "A failure the bridge has never heard of."}]

    def run_with(self, factory_result):
        with mock.patch.object(bridge, "create_game_project_structure", return_value=factory_result):
            return create_game_project_structure_from_request(make_request())

    def test_16_factory_failures_are_exposed_unchanged_and_in_order(self):
        result = self.run_with(GameProjectStructureResult(failures=[dict(f) for f in self.FAILURES]))
        self.assertFalse(result.ok)
        self.assertIsNone(result.structure)
        self.assertEqual(result.failures, self.FAILURES)
        self.assertEqual(result.codes(), [f["code"] for f in self.FAILURES])
        self.assertEqual(result.to_dict(), {"ok": False, "structure": None, "failures": self.FAILURES})

    def test_17_no_failure_is_invented_or_recoded(self):
        result = self.run_with(GameProjectStructureResult(failures=[dict(self.FAILURES[0])]))
        self.assertEqual(result.codes(), ["GAME_PROJECT_STRUCTURE_INVALID_COLLECTION"])
        self.assertNotIn(INVALID_REQUEST, result.codes())
        self.assertFalse(result.codes()[0].startswith(bridge.FAILURE_PREFIX))

    def test_18_the_real_factory_failure_shape_is_preserved(self):
        real = create_game_project_structure({"scenes": [""], "characters": [], "gameplay_systems": [], "assets": []})
        self.assertFalse(real.ok)
        result = self.run_with(real)
        self.assertEqual(result.failures, real.failures)
        self.assertEqual(result.codes(), real.codes())

    def test_19_the_bridge_does_not_validate_by_itself(self):
        # a factory that accepts anything proves the bridge adds no rule of its own: it just wraps what the factory returns
        sentinel = create_game_project_structure(good()).structure
        result = self.run_with(GameProjectStructureResult(structure=sentinel))
        self.assertTrue(result.ok)
        self.assertIs(result.structure, sentinel)

    def test_20_the_structure_object_identity_is_preserved(self):
        sentinel = create_game_project_structure({"scenes": ["s1"], "characters": ["c1"], "gameplay_systems": [], "assets": ["a1"]}).structure
        result = self.run_with(GameProjectStructureResult(structure=sentinel))
        self.assertIs(result.structure, sentinel)
        self.assertIs(result.structure, result.structure)
        self.assertEqual(result.to_dict()["structure"], sentinel.to_dict())

    def test_21_the_real_factory_structure_is_exposed_as_returned(self):
        produced = []

        def spy(data):
            r = create_game_project_structure(data)
            produced.append(r)
            return r
        with mock.patch.object(bridge, "create_game_project_structure", side_effect=spy):
            result = create_game_project_structure_from_request(make_request())
        self.assertIs(result.structure, produced[0].structure)

    def test_22_later_changes_to_the_factory_result_do_not_reach_the_bridge_result(self):
        failures = [dict(f) for f in self.FAILURES]
        result = self.run_with(GameProjectStructureResult(failures=failures))
        failures[0]["code"] = "CHANGED"
        failures.append({"code": "EXTRA", "field": None, "message": "x"})
        self.assertEqual(result.failures, self.FAILURES)

    def test_23_the_existing_factory_still_returns_its_own_mutable_result_type(self):
        self.assertIsInstance(create_game_project_structure(EMPTY), GameProjectStructureResult)
        self.assertNotIsInstance(create_game_project_structure_from_request(make_request()), GameProjectStructureResult)


class TestNoMutationAndPublicApiOnly(unittest.TestCase):
    def test_24_the_bridge_leaves_the_request_unchanged(self):
        request = make_request()
        before = (request.to_dict(), hash(request), [id(getattr(request, f)) for f in FIELDS], [getattr(request, f) for f in FIELDS])
        create_game_project_structure_from_request(request)
        with mock.patch.object(bridge, "create_game_project_structure", return_value=GameProjectStructureResult(failures=[{"code": "X", "field": None, "message": "m"}])):
            create_game_project_structure_from_request(request)
        self.assertEqual((request.to_dict(), hash(request), [id(getattr(request, f)) for f in FIELDS], [getattr(request, f) for f in FIELDS]), before)
        for f in FIELDS:
            self.assertIs(type(getattr(request, f)), tuple)

    def test_25_the_structure_is_independent_of_the_request_and_the_original_input(self):
        data = good()
        request = make_request(data)
        s = create_game_project_structure_from_request(request).structure
        data["scenes"].append("added")
        data["assets"].clear()
        self.assertEqual(s.to_dict(), good())
        self.assertEqual(request.to_dict(), good())

    def test_26_only_the_four_public_properties_are_read(self):
        request = make_request()
        accessed = []
        original = GameStructureRequest.__getattribute__

        def spy(self, name):
            if os.path.abspath(sys._getframe(1).f_code.co_filename) == os.path.abspath(SOURCE):
                accessed.append(name)
            return original(self, name)
        with mock.patch.object(GameStructureRequest, "__getattribute__", spy):
            result = create_game_project_structure_from_request(request)
        self.assertTrue(result.ok)
        self.assertEqual(accessed, list(FIELDS))      # exactly the four public properties, once each, in order

    def test_27_no_private_attribute_of_the_request_or_structure_is_used(self):
        tree = source_tree()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("_") and not node.attr.startswith("__"):
                self.assertIn(ast.unparse(node.value), ("self", "other"), ast.unparse(node))      # only the result class touches its own slots
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_game_project_structure_from_request")
        attrs = {n.attr for n in ast.walk(func) if isinstance(n, ast.Attribute)}
        self.assertEqual(attrs, {"scenes", "characters", "gameplay_systems", "assets", "ok", "structure", "failures"})

    def test_28_nothing_module_level_is_mutated_by_calls(self):
        keys = list(vars(bridge))
        for _ in range(3):
            create_game_project_structure_from_request(make_request())
            create_game_project_structure_from_request(None)
        self.assertEqual(list(vars(bridge)), keys)
        for name, value in vars(bridge).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set, bytearray), name)


class TestResultProtections(unittest.TestCase):
    def valid(self):
        return create_game_project_structure_from_request(make_request())

    def invalid(self):
        return create_game_project_structure_from_request(None)

    def test_29_attributes_are_read_only(self):
        for result in (self.valid(), self.invalid()):
            for name in ("ok", "structure", "failures", "_structure", "_failures", "extra", "codes", "to_dict"):
                with self.assertRaises(AttributeError, msg=name):
                    setattr(result, name, 1)
            for name in ("ok", "structure", "failures", "_structure", "_failures"):
                with self.assertRaises(AttributeError, msg=name):
                    delattr(result, name)
            self.assertFalse(hasattr(result, "__dict__"))
        self.assertEqual(sorted(n for n in dir(self.valid()) if not n.startswith("_")), ["codes", "failures", "ok", "structure", "to_dict"])

    def test_30_deterministic_equality_and_hash(self):
        a, b = self.valid(), self.valid()
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, self.invalid())
        self.assertEqual(self.invalid(), self.invalid())
        self.assertEqual(hash(self.invalid()), hash(self.invalid()))
        self.assertNotEqual(a, a.to_dict())
        self.assertFalse(a == object())

    def test_31_to_dict_failures_and_codes_are_fresh_every_call(self):
        for result in (self.valid(), self.invalid()):
            first, second = result.to_dict(), result.to_dict()
            self.assertEqual(first, second)
            self.assertIsNot(first, second)
            self.assertIsNot(first["failures"], second["failures"])
            if first["structure"] is not None:
                self.assertIsNot(first["structure"], second["structure"])
                for f in FIELDS:
                    self.assertIsNot(first["structure"][f], second["structure"][f])
                first["structure"]["scenes"].append("tampered")
            first["ok"] = "tampered"
            first["failures"].append({"code": "X"})
            self.assertEqual(result.to_dict(), second)
            self.assertIsNot(result.failures, result.failures)
            for item in result.failures:
                item["code"] = "tampered"
            result.codes().append("X")
            self.assertEqual(result.to_dict(), second)
        bad = self.invalid()
        self.assertIsNot(bad.failures[0], bad.failures[0])
        self.assertIsNot(bad.codes(), bad.codes())

    def test_32_direct_construction_is_refused(self):
        structure = create_game_project_structure(good()).structure
        for args in ((), (None, None, []), (object(), structure, []), (None, structure, []), (True, structure, [])):
            with self.assertRaises(TypeError):
                GameStructureRequestBridgeResult(*args)

    def test_33_subclassing_is_refused(self):
        with self.assertRaises(TypeError):
            class Sub(GameStructureRequestBridgeResult):
                pass

    def test_34_copy_and_deepcopy_return_the_same_object(self):
        for result in (self.valid(), self.invalid()):
            self.assertIs(copy.copy(result), result)
            self.assertIs(copy.deepcopy(result), result)
            self.assertIs(copy.deepcopy({"r": result})["r"], result)

    def test_35_pickle_is_refused(self):
        for result in (self.valid(), self.invalid()):
            for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(result, protocol)

    def test_36_codes_repr_and_constants(self):
        self.assertEqual(self.valid().codes(), [])
        self.assertEqual(self.invalid().codes(), [INVALID_REQUEST])
        self.assertEqual(repr(self.valid()), "GameStructureRequestBridgeResult(ok=True, failures=0)")
        self.assertEqual(repr(self.invalid()), "GameStructureRequestBridgeResult(ok=False, failures=1)")
        self.assertEqual(bridge.FAILURE_PREFIX, "GAME_STRUCTURE_REQUEST_BRIDGE_")
        self.assertEqual(bridge.FAILURE_INVALID_REQUEST, INVALID_REQUEST)
        self.assertEqual(bridge.FAILURE_CODES, (INVALID_REQUEST,))


class TestSourcePins(unittest.TestCase):
    def test_37_imports_are_exactly_the_request_type_and_the_public_factory(self):
        imports = [ast.unparse(n) for n in source_tree().body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, ["from .game_project_structure import create_game_project_structure",
                                   "from .game_structure_request import GameStructureRequest"])

    def test_38_only_the_public_factory_is_called_and_no_validation_is_duplicated(self):
        tree = source_tree()
        calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        self.assertEqual(calls.count("create_game_project_structure"), 1)
        for method in ("strip", "lstrip", "rstrip", "lower", "upper", "casefold", "normalize", "title", "replace", "join", "split", "str", "int", "bool",
                       "copy", "deepcopy", "dict", "sorted", "set", "getattr", "setattr", "hasattr", "vars", "isinstance", "type_of"):
            self.assertFalse([c for c in calls if c == method or c.endswith("." + method)], method)
        self.assertEqual(calls.count("tuple"), 1)      # only the result class freezing its own failures
        self.assertEqual(sorted(c for c in calls if c == "list"), ["list"] * 4)      # the four container adaptations, nothing else
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_game_project_structure_from_request")
        compares = [ast.unparse(n) for n in ast.walk(func) if isinstance(n, ast.Compare)]
        self.assertEqual(compares, ["type(request) is not GameStructureRequest"])      # the exact-type gate is the only check; no validation rule lives here
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("GameProjectStructure", "GameProjectStructureResult", "GameProject", "create_game_project", "create_game_structure_request",
                          "GameCreationRequest", "FIELDS", "_check_collection", "Core", "Planner", "AgentLoop", "process_input", "os", "sys", "socket",
                          "sqlite3", "random", "time", "datetime", "pickle", "subprocess", "threading", "requests", "urllib"):
            self.assertNotIn(forbidden, names)
        for name in names:
            self.assertNotIn("registry", name.lower(), name)

    def test_39_dependency_direction_request_to_bridge_to_factory(self):
        for rel in ("game_structure_request.py", "game_project_structure.py", "game_project.py", "game_structure_from_request.py"):
            with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
                other = fh.read()
            for token in ("game_structure_request_bridge", "GameStructureRequestBridgeResult"):
                self.assertNotIn(token, other, (rel, token))
        with open(os.path.join(PKG, "game_structure_request.py"), encoding="utf-8") as fh:
            self.assertFalse([l for l in fh.read().splitlines() if l.startswith(("import ", "from "))])      # the request model still imports nothing
        with open(os.path.join(PKG, "game_project_structure.py"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("GameStructureRequest", text)
        self.assertFalse([l for l in text.splitlines() if l.startswith(("import ", "from "))])

    def test_40_no_other_production_module_imports_the_bridge(self):
        needles = ("game_structure_request_bridge", "GameStructureRequestBridgeResult")
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "data")]
            for name in files:
                if name.endswith(".py") and os.path.join(folder, name) != SOURCE:
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    for needle in needles:
                        self.assertNotIn(needle, text, os.path.join(folder, name))

    def test_41_the_older_741_bridge_is_unaware_and_unchanged_in_behavior(self):
        with open(os.path.join(PKG, "game_structure_from_request.py"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("GameStructureRequest", text)
        self.assertNotIn("game_structure_request", text)
        from game_creation import game_structure_from_request as old
        self.assertIsNot(old.create_game_project_structure_from_request, create_game_project_structure_from_request)

    def test_42_one_public_function_one_class_no_module_state_no_io(self):
        tree = source_tree()
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")], ["create_game_project_structure_from_request"])
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.ClassDef)], ["GameStructureRequestBridgeResult"])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))

    def test_43_core_input_planner_and_agent_loop_do_not_know_the_bridge(self):
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_structure_request_bridge", "GameStructureRequestBridgeResult", "game_creation"):
                self.assertNotIn(token, text, (rel, token))

    def test_44_package_listing_has_exactly_the_one_new_module(self):
        self.assertEqual(sorted(os.listdir(PKG)), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py",
            "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py",
            "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py",
            "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py",
            "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py",
            "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])


class TestScopeAndDocumentation(unittest.TestCase):
    def test_45_pristine_database_no_bytecode(self):
        self.assertEqual(sha(PROJECT_DB), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)

    def test_46_documentation_names_the_contract(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_game_project_structure_from_request", "GameStructureRequestBridgeResult", "GameStructureRequest", "create_game_project_structure",
                       "GAME_STRUCTURE_REQUEST_BRIDGE_", "GAME_STRUCTURE_REQUEST_BRIDGE_INVALID_REQUEST", "GameStructureRequest -> bridge", "identity",
                       "unchanged", "fresh", "list", "does NOT", "Prompt 741", "Prompt 745"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
