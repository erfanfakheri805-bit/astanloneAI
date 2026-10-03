"""Prompt 740 - Section 7 game creation request bridge (`game_creation.game_creation_request_bridge`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from game_creation import game_creation_request_bridge as bridge
from game_creation.game_creation_request import GameCreationRequest, create_game_creation_request
from game_creation.game_creation_request_bridge import GameCreationRequestBridgeResult, create_game_project_from_request
from game_creation.game_project import GameProject, GameProjectResult, create_game_project

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
PKG = os.path.join(PY_ROOT, "game_creation")
SOURCE = os.path.join(PKG, "game_creation_request_bridge.py")
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_creation_request_bridge_prompt740.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
FROZEN_GAME_PROJECT_SHA256 = "765e8aae340452ffa33b32b7306d44c706913228a22018114749989d3b5cde8c"
FROZEN_GAME_CREATION_REQUEST_SHA256 = "23f4cb6d42d50871dddef428afc213af7c092edc38da550a8c008279c2f6f42e"

FIELDS = ("project_id", "name", "description", "genre", "target_platform", "version")
INVALID_REQUEST = "GAME_CREATION_REQUEST_BRIDGE_INVALID_REQUEST"


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
    def test_01_valid_request_creates_the_expected_project(self):
        request = make_request()
        result = create_game_project_from_request(request)
        self.assertIsInstance(result, GameCreationRequestBridgeResult)
        self.assertTrue(result.ok)
        self.assertIsInstance(result.project, GameProject)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.codes(), [])
        expected = create_game_project(good()).project
        self.assertEqual(result.project, expected)
        self.assertEqual(result.project.to_dict(), good())
        self.assertEqual(result.to_dict(), {"ok": True, "project": good(), "failures": []})

    def test_02_every_field_is_passed_unchanged(self):
        for field in FIELDS:
            request = make_request(**{field: "  Mixed Case %s  " % field})
            project = create_game_project_from_request(request).project
            self.assertEqual(getattr(project, field), "  Mixed Case %s  " % field, field)
        # optional fields may be empty, blank or odd text and stay exactly as given
        project = create_game_project_from_request(make_request(description="", genre="  ", target_platform="\tX\n")).project
        self.assertEqual((project.description, project.genre, project.target_platform), ("", "  ", "\tX\n"))

    def test_03_the_very_same_string_objects_reach_the_factory(self):
        values = {f: "".join(["v", "-", f, "-", "x"]) for f in FIELDS}      # fresh str objects, not interned literals
        request = make_request(**values)
        seen = []

        def spy(data):
            seen.append(data)
            return create_game_project(data)
        with mock.patch.object(bridge, "create_game_project", side_effect=spy) as factory:
            create_game_project_from_request(request)
        self.assertEqual(factory.call_count, 1)
        (data,), kwargs = factory.call_args
        self.assertEqual(kwargs, {})
        self.assertIs(type(data), dict)
        self.assertEqual(list(data), list(FIELDS))
        for field in FIELDS:
            self.assertIs(data[field], values[field], field)
            self.assertIs(data[field], getattr(request, field), field)

    def test_04_the_created_project_object_identity_is_preserved(self):
        sentinel = create_game_project(good()).project
        with mock.patch.object(bridge, "create_game_project", return_value=GameProjectResult(project=sentinel)):
            result = create_game_project_from_request(make_request())
        self.assertIs(result.project, sentinel)
        self.assertIs(result.project, result.project)
        self.assertTrue(result.ok)

    def test_05_the_factory_is_called_exactly_once_per_call(self):
        with mock.patch.object(bridge, "create_game_project", wraps=create_game_project) as factory:
            create_game_project_from_request(make_request())
            self.assertEqual(factory.call_count, 1)
            create_game_project_from_request(make_request())
            self.assertEqual(factory.call_count, 2)

    def test_06_each_call_builds_its_own_project_but_equal_input_gives_equal_results(self):
        a = create_game_project_from_request(make_request())
        b = create_game_project_from_request(make_request())
        self.assertIsNot(a.project, b.project)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))


class TestInvalidRequest(unittest.TestCase):
    def assert_invalid(self, value):
        with mock.patch.object(bridge, "create_game_project") as factory:
            result = create_game_project_from_request(value)
        factory.assert_not_called()
        self.assertIsInstance(result, GameCreationRequestBridgeResult)
        self.assertFalse(result.ok)
        self.assertIsNone(result.project)
        self.assertEqual(result.codes(), [INVALID_REQUEST])
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(set(result.failures[0]), {"code", "field", "message"})
        self.assertEqual(result.failures[0]["code"], INVALID_REQUEST)
        self.assertEqual(result.to_dict(), {"ok": False, "project": None, "failures": result.failures})
        return result

    def test_07_wrong_object_types_are_rejected(self):
        project = create_game_project(good()).project
        for value in (None, good(), [], (), "request", 1, 1.5, True, object(), project, GameCreationRequest, create_game_creation_request(good()),
                      create_game_project(good())):
            self.assert_invalid(value)

    def test_08_look_alike_objects_are_rejected(self):
        class LookAlike:
            project_id, name, description, genre, target_platform, version = "p1", "n", "", "", "", "1"
        self.assert_invalid(LookAlike())
        ns = mock.Mock(spec=GameCreationRequest)
        self.assert_invalid(ns)

    def test_09_a_dict_subclass_or_str_subclass_is_rejected(self):
        class D(dict):
            pass

        class S(str):
            pass
        self.assert_invalid(D(good()))
        self.assert_invalid(S("p1"))

    def test_10_the_invalid_failure_is_deterministic(self):
        a = self.assert_invalid(None)
        b = self.assert_invalid(None)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.failures, b.failures)
        self.assertEqual(a.failures[0]["field"], "request")
        self.assertTrue(a.failures[0]["code"].startswith(bridge.FAILURE_PREFIX))

    def test_11_request_subclassing_and_direct_construction_remain_impossible(self):
        with self.assertRaises(TypeError):
            class Sub(GameCreationRequest):
                pass
        with self.assertRaises(TypeError):
            GameCreationRequest(object(), "p", "n", "", "", "", "1")


class TestRequestIsNotMutated(unittest.TestCase):
    def test_12_request_attributes_cannot_be_changed(self):
        request = make_request()
        for field in FIELDS:
            with self.assertRaises(AttributeError):
                setattr(request, field, "x")
            with self.assertRaises(AttributeError):
                delattr(request, field)
        with self.assertRaises(AttributeError):
            request.extra = 1

    def test_13_the_bridge_leaves_the_request_unchanged(self):
        request = make_request()
        before_dict, before_hash = request.to_dict(), hash(request)
        before_ids = [id(getattr(request, f)) for f in FIELDS]
        create_game_project_from_request(request)
        with mock.patch.object(bridge, "create_game_project", return_value=GameProjectResult(failures=[{"code": "X", "field": None, "message": "m"}])):
            create_game_project_from_request(request)
        self.assertEqual(request.to_dict(), before_dict)
        self.assertEqual(hash(request), before_hash)
        self.assertEqual([id(getattr(request, f)) for f in FIELDS], before_ids)

    def test_14_mutating_the_dict_sent_to_the_factory_cannot_reach_the_request(self):
        request = make_request()

        def tamper(data):
            data["name"] = "tampered"
            return GameProjectResult(failures=[])
        with mock.patch.object(bridge, "create_game_project", side_effect=tamper):
            create_game_project_from_request(request)
        self.assertEqual(request.name, "My Game")
        self.assertEqual(request.to_dict(), good())


class TestFactoryFailurePropagation(unittest.TestCase):
    FAILURES = [{"code": "GAME_PROJECT_INVALID_NAME", "field": "name", "message": "name must not be empty or blank."},
                {"code": "GAME_PROJECT_SOMETHING_NEW", "field": None, "message": "A failure the bridge has never heard of."}]

    def run_with_failures(self, failures):
        with mock.patch.object(bridge, "create_game_project", return_value=GameProjectResult(failures=failures)):
            return create_game_project_from_request(make_request())

    def test_15_factory_failures_are_exposed_unchanged_and_in_order(self):
        result = self.run_with_failures([dict(f) for f in self.FAILURES])
        self.assertFalse(result.ok)
        self.assertIsNone(result.project)
        self.assertEqual(result.failures, self.FAILURES)
        self.assertEqual(result.codes(), ["GAME_PROJECT_INVALID_NAME", "GAME_PROJECT_SOMETHING_NEW"])
        self.assertEqual(result.to_dict(), {"ok": False, "project": None, "failures": self.FAILURES})

    def test_16_the_bridge_invents_no_failure_for_a_factory_failure(self):
        result = self.run_with_failures([dict(self.FAILURES[0])])
        self.assertEqual(result.codes(), ["GAME_PROJECT_INVALID_NAME"])
        self.assertNotIn(INVALID_REQUEST, result.codes())
        self.assertEqual(len(result.failures), 1)

    def test_17_the_real_factory_failure_shape_is_preserved(self):
        real = create_game_project({"project_id": "", "name": "n", "description": "", "genre": "", "target_platform": "", "version": "1"})
        self.assertFalse(real.ok)
        with mock.patch.object(bridge, "create_game_project", return_value=real):
            result = create_game_project_from_request(make_request())
        self.assertEqual(result.failures, real.failures)
        self.assertEqual(result.codes(), real.codes())

    def test_18_later_changes_to_the_factory_result_do_not_reach_the_bridge_result(self):
        failures = [dict(f) for f in self.FAILURES]
        result = self.run_with_failures(failures)
        failures[0]["code"] = "CHANGED"
        failures.append({"code": "EXTRA", "field": None, "message": "x"})
        self.assertEqual(result.failures, self.FAILURES)

    def test_19_a_factory_that_returns_an_ok_result_is_exposed_as_is(self):
        sentinel = create_game_project(good()).project
        with mock.patch.object(bridge, "create_game_project", return_value=GameProjectResult(project=sentinel)):
            result = create_game_project_from_request(make_request())
        self.assertTrue(result.ok)
        self.assertIs(result.project, sentinel)
        self.assertEqual(result.failures, [])


class TestResultProtections(unittest.TestCase):
    def valid(self):
        return create_game_project_from_request(make_request())

    def invalid(self):
        return create_game_project_from_request(None)

    def test_20_attributes_are_read_only(self):
        for result in (self.valid(), self.invalid()):
            for name in ("ok", "project", "failures", "_project", "_failures", "extra"):
                with self.assertRaises(AttributeError, msg=name):
                    setattr(result, name, 1)
            for name in ("ok", "project", "failures", "_project", "_failures"):
                with self.assertRaises(AttributeError, msg=name):
                    delattr(result, name)
            self.assertFalse(hasattr(result, "__dict__"))

    def test_21_deterministic_equality_and_hash(self):
        a, b = self.valid(), self.valid()
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, self.invalid())
        self.assertNotEqual(a, create_game_project_from_request(make_request(name="Other")))
        self.assertEqual(self.invalid(), self.invalid())
        self.assertEqual(hash(self.invalid()), hash(self.invalid()))
        self.assertNotEqual(a, a.to_dict())
        self.assertFalse(a == object())

    def test_22_to_dict_and_failures_are_fresh_every_call(self):
        for result in (self.valid(), self.invalid()):
            first, second = result.to_dict(), result.to_dict()
            self.assertEqual(first, second)
            self.assertIsNot(first, second)
            self.assertIsNot(first["failures"], second["failures"])
            if first["project"] is not None:
                self.assertIsNot(first["project"], second["project"])
            first["ok"] = "tampered"
            first["failures"].append({"code": "X"})
            if first["project"] is not None:
                first["project"]["name"] = "tampered"
            self.assertEqual(result.to_dict(), second)
            self.assertIsNot(result.failures, result.failures)
            fresh = result.failures
            for item in fresh:
                item["code"] = "tampered"
            self.assertEqual(result.to_dict(), second)
            codes = result.codes()
            codes.append("X")
            self.assertEqual(result.to_dict(), second)

    def test_23_direct_construction_is_refused(self):
        project = create_game_project(good()).project
        for args in ((), (None, None, []), (object(), project, []), (None, project, [])):
            with self.assertRaises(TypeError):
                GameCreationRequestBridgeResult(*args)

    def test_24_subclassing_is_refused(self):
        with self.assertRaises(TypeError):
            class Sub(GameCreationRequestBridgeResult):
                pass

    def test_25_copy_and_deepcopy_return_the_same_object(self):
        for result in (self.valid(), self.invalid()):
            self.assertIs(copy.copy(result), result)
            self.assertIs(copy.deepcopy(result), result)
            self.assertIs(copy.deepcopy({"r": result})["r"], result)

    def test_26_pickle_is_refused(self):
        for result in (self.valid(), self.invalid()):
            for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(result, protocol)

    def test_27_codes_follow_the_established_result_convention(self):
        self.assertEqual(self.valid().codes(), [])
        self.assertEqual(self.invalid().codes(), [INVALID_REQUEST])
        self.assertIs(type(self.valid().codes()), list)
        self.assertIsNot(self.invalid().codes(), self.invalid().codes())

    def test_28_repr_is_stable(self):
        self.assertEqual(repr(self.valid()), "GameCreationRequestBridgeResult(ok=True, failures=0)")
        self.assertEqual(repr(self.invalid()), "GameCreationRequestBridgeResult(ok=False, failures=1)")

    def test_29_constants(self):
        self.assertEqual(bridge.FAILURE_PREFIX, "GAME_CREATION_REQUEST_BRIDGE_")
        self.assertEqual(bridge.FAILURE_INVALID_REQUEST, INVALID_REQUEST)
        self.assertEqual(bridge.FAILURE_CODES, (INVALID_REQUEST,))
        for code in bridge.FAILURE_CODES:
            self.assertTrue(code.startswith(bridge.FAILURE_PREFIX))


class TestNoPrivateAccessNoRegistryNoMutation(unittest.TestCase):
    def test_30_no_private_attribute_is_read_from_the_request_or_the_project(self):
        tree = source_tree()
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_game_project_from_request")
        for node in ast.walk(func):
            if isinstance(node, ast.Attribute):
                self.assertFalse(node.attr.startswith("_"), ast.unparse(node))
            if isinstance(node, ast.Name):
                self.assertFalse(node.id.startswith("__"), node.id)
        attrs = sorted({n.attr for n in ast.walk(func) if isinstance(n, ast.Attribute)})
        self.assertEqual(attrs, ["description", "failures", "genre", "name", "ok", "project", "project_id", "target_platform", "version"])
        # the only underscore attributes in the whole module belong to the result class itself (self._x / other._x)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("_") and not node.attr.startswith("__"):
                self.assertIn(ast.unparse(node.value), ("self", "other"), ast.unparse(node))

    def test_31_no_private_attribute_access_at_runtime(self):
        request = make_request()
        accessed = []      # (attribute name, file of the code that asked for it)
        original = GameCreationRequest.__getattribute__

        def spy(self, name):
            accessed.append((name, sys._getframe(1).f_code.co_filename))
            return original(self, name)
        with mock.patch.object(GameCreationRequest, "__getattribute__", spy):
            result = create_game_project_from_request(request)
        self.assertTrue(result.ok)
        from_bridge = [n for n, where in accessed if os.path.abspath(where) == os.path.abspath(SOURCE)]
        self.assertEqual(sorted(from_bridge), sorted(FIELDS))      # exactly the six public fields, each read once, nothing private
        self.assertFalse([n for n in from_bridge if n.startswith("_")])

    def test_32_no_registry_is_imported_or_used(self):
        tree = source_tree()
        imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([ast.unparse(n) for n in imports],
                         ["from .game_creation_request import GameCreationRequest", "from .game_project import create_game_project"])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for name in names:
            self.assertNotIn("registry", name.lower(), name)
            self.assertNotIn("Registry", name, name)
        with open(SOURCE, encoding="utf-8") as fh:
            code = "\n".join(ast.unparse(n) for n in tree.body[1:])
        self.assertNotIn("registry", code.lower())

    def test_33_nothing_is_mutated_by_a_call(self):
        request = make_request()
        snapshot = (request.to_dict(), hash(request), dict(vars(bridge)).keys())
        for _ in range(3):
            create_game_project_from_request(request)
            create_game_project_from_request(None)
        self.assertEqual((request.to_dict(), hash(request), dict(vars(bridge)).keys()), snapshot)
        for name, value in vars(bridge).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set, bytearray), name)

    def test_34_the_call_never_raises_for_bad_input(self):
        for value in (None, 0, "", b"", [], {}, set(), object(), type, lambda: None, float("nan")):
            self.assertFalse(create_game_project_from_request(value).ok)


class TestSourcePins(unittest.TestCase):
    def test_35_dependency_direction_request_to_bridge_to_factory(self):
        with open(SOURCE, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("from .game_creation_request import GameCreationRequest", text)
        self.assertIn("from .game_project import create_game_project", text)
        for rel in ("game_project.py", "game_creation_request.py"):
            with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
                other = fh.read()
            for token in ("game_creation_request_bridge", "create_game_project_from_request", "GameCreationRequestBridgeResult"):
                self.assertNotIn(token, other, (rel, token))

    def test_36_game_project_does_not_depend_on_game_creation_request_and_is_unchanged(self):
        with open(os.path.join(PKG, "game_project.py"), encoding="utf-8") as fh:
            text = fh.read()
        for token in ("GameCreationRequest", "game_creation_request"):
            self.assertNotIn(token, text)
        self.assertFalse([l for l in text.splitlines() if l.startswith(("import ", "from "))])
        self.assertEqual(sha(os.path.join(PKG, "game_project.py")), FROZEN_GAME_PROJECT_SHA256)
        self.assertEqual(sha(os.path.join(PKG, "game_creation_request.py")), FROZEN_GAME_CREATION_REQUEST_SHA256)

    def test_37_no_other_production_module_imports_the_bridge(self):
        needles = ("game_creation_request_bridge", "create_game_project_from_request", "GameCreationRequestBridgeResult")
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "data")]
            for name in files:
                if not name.endswith(".py") or os.path.join(folder, name) == SOURCE:
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    text = fh.read()
                for needle in needles:
                    self.assertNotIn(needle, text, os.path.join(folder, name))

    def test_38_exactly_one_public_function_and_one_class(self):
        tree = source_tree()
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")], ["create_game_project_from_request"])
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.ClassDef)], ["GameCreationRequestBridgeResult"])

    def test_39_values_are_never_rewritten_or_checked(self):
        tree = source_tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for method in ("strip", "lstrip", "rstrip", "lower", "upper", "casefold", "normalize", "title", "capitalize", "encode", "decode", "replace",
                       "join", "split", "str", "int", "bool", "copy", "deepcopy", "dict", "list", "sorted", "repr", "format"):
            self.assertFalse([c for c in calls if c == method or c.endswith("." + method)], method)

    def test_40_no_io_no_runtime_execution_no_wiring(self):
        tree = source_tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "setattr", "getattr", "hasattr", "vars", "globals",
                          "locals", "subprocess.run", "os.system"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("Core", "Planner", "AgentLoop", "process_input", "os", "sys", "socket", "sqlite3", "random", "time", "datetime", "pickle",
                          "subprocess", "threading", "requests", "urllib"):
            self.assertNotIn(forbidden, names)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation_request_bridge", "create_game_project_from_request"):
                self.assertNotIn(token, text, (rel, token))

    def test_41_failure_prefix_is_the_stable_bridge_prefix(self):
        tree = source_tree()
        values = [n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)]
        self.assertIn("GAME_CREATION_REQUEST_BRIDGE_", values)
        self.assertIn("GAME_CREATION_REQUEST_BRIDGE_INVALID_REQUEST", values)
        # earlier request codes keep the shorter prefix and the bridge prefix extends it
        self.assertTrue(bridge.FAILURE_INVALID_REQUEST.startswith("GAME_CREATION_REQUEST_"))

    def test_42_package_listing_has_exactly_the_one_new_module(self):
        listing = sorted(os.listdir(PKG))
        self.assertEqual(listing, [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py",
            "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py",
            "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py", "game_project_structure.py",
            "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py",
            "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])


class TestScopeAndDocumentation(unittest.TestCase):
    def test_43_pristine_database_no_bytecode(self):
        self.assertEqual(sha(PROJECT_DB), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)

    def test_44_documentation_names_the_contract(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_game_project_from_request", "GameCreationRequestBridgeResult", "GameCreationRequest", "create_game_project",
                       "GAME_CREATION_REQUEST_BRIDGE_", "GAME_CREATION_REQUEST_BRIDGE_INVALID_REQUEST", "GameCreationRequest -> bridge -> GameProject",
                       "unchanged", "identity", "does NOT", "Prompt 741"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
