"""Prompt 741 - Section 7 game structure from request (`game_creation.game_structure_from_request`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from game_creation import game_structure_from_request as bridge
from game_creation.game_creation_request import GameCreationRequest, create_game_creation_request
from game_creation.game_project import create_game_project
from game_creation.game_project_structure import GameProjectStructure, GameProjectStructureResult, create_game_project_structure
from game_creation.game_structure_from_request import GameStructureFromRequestResult, create_game_project_structure_from_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
PKG = os.path.join(PY_ROOT, "game_creation")
SOURCE = os.path.join(PKG, "game_structure_from_request.py")
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_structure_from_request_prompt741.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

FIELDS = ("project_id", "name", "description", "genre", "target_platform", "version")
STRUCTURE_FIELDS = ("scenes", "characters", "gameplay_systems", "assets")
INVALID_REQUEST = "GAME_STRUCTURE_FROM_REQUEST_INVALID_REQUEST"
EMPTY = {"scenes": [], "characters": [], "gameplay_systems": [], "assets": []}


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


class TestValidRequest(unittest.TestCase):
    def test_01_valid_request_creates_an_empty_structure(self):
        result = create_game_project_structure_from_request(make_request())
        self.assertIsInstance(result, GameStructureFromRequestResult)
        self.assertTrue(result.ok)
        self.assertIsInstance(result.structure, GameProjectStructure)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.codes(), [])
        self.assertEqual(result.structure, create_game_project_structure(EMPTY).structure)
        self.assertEqual(result.structure.to_dict(), EMPTY)
        self.assertEqual(result.to_dict(), {"ok": True, "structure": EMPTY, "failures": []})
        for field in STRUCTURE_FIELDS:
            self.assertEqual(getattr(result.structure, field), ())

    def test_02_the_result_does_not_depend_on_the_request_values(self):
        a = create_game_project_structure_from_request(make_request())
        for over in ({"name": "Other"}, {"genre": "rpg"}, {"project_id": "scenes"}, {"description": "assets"}, {"version": "  2  "}):
            b = create_game_project_structure_from_request(make_request(**over))
            self.assertEqual(a, b, over)
            self.assertEqual(hash(a), hash(b))

    def test_03_exact_passthrough_the_factory_gets_exactly_four_empty_lists_and_no_request_field(self):
        values = {f: "".join(["v-", f]) for f in FIELDS}
        request = make_request(**values)
        with mock.patch.object(bridge, "create_game_project_structure", wraps=create_game_project_structure) as factory:
            create_game_project_structure_from_request(request)
        self.assertEqual(factory.call_count, 1)
        (data,), kwargs = factory.call_args
        self.assertEqual(kwargs, {})
        self.assertIs(type(data), dict)
        self.assertEqual(list(data), list(STRUCTURE_FIELDS))
        for field in STRUCTURE_FIELDS:
            self.assertIs(type(data[field]), list)
            self.assertEqual(data[field], [])
        for field in FIELDS:
            self.assertNotIn(field, data)
            self.assertNotIn(values[field], str(data))

    def test_04_each_call_passes_fresh_lists(self):
        seen = []

        def spy(data):
            seen.append(data)
            return create_game_project_structure(data)
        with mock.patch.object(bridge, "create_game_project_structure", side_effect=spy):
            create_game_project_structure_from_request(make_request())
            create_game_project_structure_from_request(make_request())
        self.assertIsNot(seen[0], seen[1])
        for field in STRUCTURE_FIELDS:
            self.assertIsNot(seen[0][field], seen[1][field])

    def test_05_the_factory_is_called_exactly_once_per_valid_call_and_never_for_invalid(self):
        with mock.patch.object(bridge, "create_game_project_structure", wraps=create_game_project_structure) as factory:
            create_game_project_structure_from_request(make_request())
            self.assertEqual(factory.call_count, 1)
            create_game_project_structure_from_request(None)
            self.assertEqual(factory.call_count, 1)

    def test_06_deterministic_equal_results(self):
        a = create_game_project_structure_from_request(make_request())
        b = create_game_project_structure_from_request(make_request())
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)


class TestInvalidRequest(unittest.TestCase):
    def assert_invalid(self, value):
        with mock.patch.object(bridge, "create_game_project_structure") as factory:
            result = create_game_project_structure_from_request(value)
        factory.assert_not_called()
        self.assertIsInstance(result, GameStructureFromRequestResult)
        self.assertFalse(result.ok)
        self.assertIsNone(result.structure)
        self.assertEqual(result.codes(), [INVALID_REQUEST])
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(set(result.failures[0]), {"code", "field", "message"})
        self.assertEqual(result.failures[0]["field"], "request")
        self.assertEqual(result.to_dict(), {"ok": False, "structure": None, "failures": result.failures})
        return result

    def test_07_wrong_object_types_are_rejected(self):
        for value in (None, good(), EMPTY, [], (), "request", 1, 1.5, True, object(), GameCreationRequest, create_game_creation_request(good()),
                      create_game_project(good()), create_game_project(good()).project, create_game_project_structure(EMPTY).structure):
            self.assert_invalid(value)

    def test_08_look_alikes_and_subclasses_are_rejected(self):
        class LookAlike:
            project_id, name, description, genre, target_platform, version = "p1", "n", "", "", "", "1"

        class D(dict):
            pass
        self.assert_invalid(LookAlike())
        self.assert_invalid(mock.Mock(spec=GameCreationRequest))
        self.assert_invalid(D(good()))

    def test_09_the_invalid_failure_is_deterministic(self):
        a, b = self.assert_invalid(None), self.assert_invalid(None)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.failures, b.failures)
        self.assertTrue(a.failures[0]["code"].startswith(bridge.FAILURE_PREFIX))

    def test_10_never_raises_for_bad_input(self):
        for value in (None, 0, "", b"", [], {}, set(), object(), type, lambda: None, float("nan")):
            self.assertFalse(create_game_project_structure_from_request(value).ok)


class TestFactoryResultPropagation(unittest.TestCase):
    FAILURES = [{"code": "GAME_PROJECT_STRUCTURE_INVALID_COLLECTION", "field": "scenes", "message": "scenes must be a list."},
                {"code": "GAME_PROJECT_STRUCTURE_SOMETHING_NEW", "field": None, "message": "A failure the bridge has never heard of."}]

    def run_with(self, factory_result):
        with mock.patch.object(bridge, "create_game_project_structure", return_value=factory_result):
            return create_game_project_structure_from_request(make_request())

    def test_11_factory_failures_are_exposed_unchanged_and_in_order(self):
        result = self.run_with(GameProjectStructureResult(failures=[dict(f) for f in self.FAILURES]))
        self.assertFalse(result.ok)
        self.assertIsNone(result.structure)
        self.assertEqual(result.failures, self.FAILURES)
        self.assertEqual(result.codes(), [f["code"] for f in self.FAILURES])
        self.assertEqual(result.to_dict(), {"ok": False, "structure": None, "failures": self.FAILURES})

    def test_12_no_failure_is_invented_or_recoded(self):
        result = self.run_with(GameProjectStructureResult(failures=[dict(self.FAILURES[0])]))
        self.assertEqual(result.codes(), ["GAME_PROJECT_STRUCTURE_INVALID_COLLECTION"])
        self.assertNotIn(INVALID_REQUEST, result.codes())

    def test_13_the_real_factory_failure_shape_is_preserved(self):
        real = create_game_project_structure({"scenes": [""], "characters": [], "gameplay_systems": [], "assets": []})
        self.assertFalse(real.ok)
        result = self.run_with(real)
        self.assertEqual(result.failures, real.failures)
        self.assertEqual(result.codes(), real.codes())

    def test_14_the_structure_object_identity_is_preserved(self):
        sentinel = create_game_project_structure({"scenes": ["s1"], "characters": ["c1"], "gameplay_systems": [], "assets": ["a1"]}).structure
        result = self.run_with(GameProjectStructureResult(structure=sentinel))
        self.assertTrue(result.ok)
        self.assertIs(result.structure, sentinel)
        self.assertIs(result.structure, result.structure)
        self.assertEqual(result.to_dict()["structure"], sentinel.to_dict())

    def test_15_later_changes_to_the_factory_result_do_not_reach_the_bridge_result(self):
        failures = [dict(f) for f in self.FAILURES]
        factory_result = GameProjectStructureResult(failures=failures)
        result = self.run_with(factory_result)
        failures[0]["code"] = "CHANGED"
        failures.append({"code": "EXTRA", "field": None, "message": "x"})
        self.assertEqual(result.failures, self.FAILURES)

    def test_16_the_existing_factory_still_returns_its_own_mutable_result_type(self):
        self.assertIsInstance(create_game_project_structure(EMPTY), GameProjectStructureResult)
        self.assertNotIsInstance(create_game_project_structure_from_request(make_request()), GameProjectStructureResult)


class TestNoMutation(unittest.TestCase):
    def test_17_the_request_cannot_be_changed(self):
        request = make_request()
        for field in FIELDS:
            with self.assertRaises(AttributeError):
                setattr(request, field, "x")
            with self.assertRaises(AttributeError):
                delattr(request, field)
        with self.assertRaises(AttributeError):
            request.extra = 1

    def test_18_the_bridge_leaves_the_request_unchanged(self):
        request = make_request()
        before = (request.to_dict(), hash(request), [id(getattr(request, f)) for f in FIELDS])
        create_game_project_structure_from_request(request)
        with mock.patch.object(bridge, "create_game_project_structure", return_value=GameProjectStructureResult(failures=[{"code": "X", "field": None, "message": "m"}])):
            create_game_project_structure_from_request(request)
        self.assertEqual((request.to_dict(), hash(request), [id(getattr(request, f)) for f in FIELDS]), before)

    def test_19_the_request_is_never_read_beyond_its_type(self):
        request = make_request()
        accessed = []
        original = GameCreationRequest.__getattribute__

        def spy(self, name):
            accessed.append((name, sys._getframe(1).f_code.co_filename))
            return original(self, name)
        with mock.patch.object(GameCreationRequest, "__getattribute__", spy):
            result = create_game_project_structure_from_request(request)
        self.assertTrue(result.ok)
        self.assertEqual([n for n, where in accessed if os.path.abspath(where) == os.path.abspath(SOURCE)], [])

    def test_20_nothing_module_level_is_mutated_by_calls(self):
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

    def test_21_attributes_are_read_only(self):
        for result in (self.valid(), self.invalid()):
            for name in ("ok", "structure", "failures", "_structure", "_failures", "extra"):
                with self.assertRaises(AttributeError, msg=name):
                    setattr(result, name, 1)
            for name in ("ok", "structure", "failures", "_structure", "_failures"):
                with self.assertRaises(AttributeError, msg=name):
                    delattr(result, name)
            self.assertFalse(hasattr(result, "__dict__"))

    def test_22_deterministic_equality_and_hash(self):
        a, b = self.valid(), self.valid()
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, self.invalid())
        self.assertEqual(self.invalid(), self.invalid())
        self.assertEqual(hash(self.invalid()), hash(self.invalid()))
        self.assertNotEqual(a, a.to_dict())
        self.assertFalse(a == object())

    def test_23_to_dict_failures_and_codes_are_fresh_every_call(self):
        for result in (self.valid(), self.invalid()):
            first, second = result.to_dict(), result.to_dict()
            self.assertEqual(first, second)
            self.assertIsNot(first, second)
            self.assertIsNot(first["failures"], second["failures"])
            if first["structure"] is not None:
                self.assertIsNot(first["structure"], second["structure"])
                for field in STRUCTURE_FIELDS:
                    self.assertIsNot(first["structure"][field], second["structure"][field])
                first["structure"]["scenes"].append("tampered")
            first["ok"] = "tampered"
            first["failures"].append({"code": "X"})
            self.assertEqual(result.to_dict(), second)
            self.assertIsNot(result.failures, result.failures)
            for item in result.failures:
                item["code"] = "tampered"
            result.codes().append("X")
            self.assertEqual(result.to_dict(), second)

    def test_24_direct_construction_is_refused(self):
        structure = create_game_project_structure(EMPTY).structure
        for args in ((), (None, None, []), (object(), structure, []), (None, structure, [])):
            with self.assertRaises(TypeError):
                GameStructureFromRequestResult(*args)

    def test_25_subclassing_is_refused(self):
        with self.assertRaises(TypeError):
            class Sub(GameStructureFromRequestResult):
                pass

    def test_26_copy_and_deepcopy_return_the_same_object(self):
        for result in (self.valid(), self.invalid()):
            self.assertIs(copy.copy(result), result)
            self.assertIs(copy.deepcopy(result), result)
            self.assertIs(copy.deepcopy({"r": result})["r"], result)

    def test_27_pickle_is_refused(self):
        for result in (self.valid(), self.invalid()):
            for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(result, protocol)

    def test_28_codes_and_repr_follow_the_convention(self):
        self.assertEqual(self.valid().codes(), [])
        self.assertEqual(self.invalid().codes(), [INVALID_REQUEST])
        self.assertIsNot(self.invalid().codes(), self.invalid().codes())
        self.assertEqual(repr(self.valid()), "GameStructureFromRequestResult(ok=True, failures=0)")
        self.assertEqual(repr(self.invalid()), "GameStructureFromRequestResult(ok=False, failures=1)")

    def test_29_constants(self):
        self.assertEqual(bridge.FAILURE_PREFIX, "GAME_STRUCTURE_FROM_REQUEST_")
        self.assertEqual(bridge.FAILURE_INVALID_REQUEST, INVALID_REQUEST)
        self.assertEqual(bridge.FAILURE_CODES, (INVALID_REQUEST,))


class TestSourcePins(unittest.TestCase):
    def test_30_no_private_attribute_is_used_outside_the_result_class(self):
        tree = source_tree()
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_game_project_structure_from_request")
        attrs = {n.attr for n in ast.walk(func) if isinstance(n, ast.Attribute)}
        self.assertEqual(attrs, {"ok", "structure", "failures"})
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("_") and not node.attr.startswith("__"):
                self.assertIn(ast.unparse(node.value), ("self", "other"), ast.unparse(node))
        for field in FIELDS:
            self.assertNotIn(field, {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)})

    def test_31_imports_are_exactly_the_request_type_and_the_public_factory(self):
        tree = source_tree()
        imports = [ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, ["from .game_creation_request import GameCreationRequest",
                                   "from .game_project_structure import create_game_project_structure"])

    def test_32_only_the_public_factory_is_called_and_no_validation_is_duplicated(self):
        tree = source_tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertIn("create_game_project_structure", calls)
        for method in ("strip", "lstrip", "rstrip", "lower", "upper", "casefold", "normalize", "title", "replace", "join", "split", "str", "int",
                       "bool", "copy", "deepcopy", "dict", "list", "sorted", "set", "getattr", "setattr", "hasattr", "vars", "isinstance"):
            self.assertFalse([c for c in calls if c == method or c.endswith("." + method)], method)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("GameProjectStructure", "GameProjectStructureResult", "GameProject", "create_game_project", "FIELDS", "_check_collection",
                          "Core", "Planner", "AgentLoop", "process_input", "os", "sys", "socket", "sqlite3", "random", "time", "datetime", "pickle",
                          "subprocess", "threading", "requests", "urllib"):
            self.assertNotIn(forbidden, names)
        for name in names:
            self.assertNotIn("registry", name.lower(), name)

    def test_33_dependency_direction_request_to_bridge_to_factory(self):
        for rel in ("game_creation_request.py", "game_project_structure.py", "game_project.py", "game_creation_request_bridge.py"):
            with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
                other = fh.read()
            for token in ("game_structure_from_request", "create_game_project_structure_from_request", "GameStructureFromRequestResult"):
                self.assertNotIn(token, other, (rel, token))
        with open(os.path.join(PKG, "game_project_structure.py"), encoding="utf-8") as fh:
            text = fh.read()
        for token in ("GameCreationRequest", "game_creation_request"):
            self.assertNotIn(token, text)
        self.assertFalse([l for l in text.splitlines() if l.startswith(("import ", "from "))])

    def test_34_no_other_production_module_imports_the_bridge(self):
        needles = ("game_structure_from_request", "create_game_project_structure_from_request", "GameStructureFromRequestResult")
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "data")]
            for name in files:
                sanctioned = (SOURCE, os.path.join(PKG, "game_structure_request_bridge.py"))      # Prompt 744: same public function name, different module
                if name.endswith(".py") and os.path.join(folder, name) not in sanctioned:
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    for needle in needles:
                        self.assertNotIn(needle, text, os.path.join(folder, name))

    def test_35_one_public_function_one_class_no_module_state_no_io(self):
        tree = source_tree()
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")],
                         ["create_game_project_structure_from_request"])
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.ClassDef)], ["GameStructureFromRequestResult"])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))

    def test_36_earlier_section7_modules_are_not_wired_to_core_planner_or_agent_loop(self):
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_structure_from_request", "create_game_project_structure_from_request"):
                self.assertNotIn(token, text, (rel, token))

    def test_37_package_listing_has_exactly_the_one_new_module(self):
        self.assertEqual(sorted(os.listdir(PKG)), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py",
            "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py",
            "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py", "game_project_structure.py",
            "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py",
            "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py",
            "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])


class TestScopeAndDocumentation(unittest.TestCase):
    def test_38_pristine_database_no_bytecode(self):
        self.assertEqual(sha(PROJECT_DB), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)

    def test_39_documentation_names_the_contract(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_game_project_structure_from_request", "GameStructureFromRequestResult", "create_game_project_structure",
                       "GAME_STRUCTURE_FROM_REQUEST_", "GAME_STRUCTURE_FROM_REQUEST_INVALID_REQUEST", "GameCreationRequest -> bridge",
                       "empty", "never read", "unchanged", "identity", "does NOT", "Prompt 742"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
