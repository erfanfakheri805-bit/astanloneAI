"""Prompt 739 - Section 7 game creation request (`game_creation.game_creation_request`)."""
import ast
import collections
import copy
import hashlib
import os
import pickle
import subprocess
import sys
import types
import unittest
from unittest import mock

from game_creation import game_creation_request as cr
from game_creation import game_project as game_project_module
from game_creation.game_creation_request import GameCreationRequest, GameCreationRequestResult, create_game_creation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_creation_request_prompt739.md")
SOURCE = os.path.join(PY_ROOT, "game_creation", "game_creation_request.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

FIELDS = ("project_id", "name", "description", "genre", "target_platform", "version")
REQUIRED = ("project_id", "name", "version")
OPTIONAL = ("description", "genre", "target_platform")
P = "GAME_CREATION_REQUEST_"
INVALID_INPUT, UNEXPECTED, MISSING = P + "INVALID_INPUT", P + "UNEXPECTED_FIELD", P + "MISSING_FIELD"
INVALID = {f: P + "INVALID_" + f.upper() for f in FIELDS}


class StrSubclass(str):
    pass


class DictSubclass(dict):
    pass


def good(**over):
    d = {"project_id": "p1", "name": "My Game", "description": "A game", "genre": "puzzle", "target_platform": "android", "version": "1.0"}
    d.update(over)
    return d


class TestValid(unittest.TestCase):
    def test_01_valid_request(self):
        data = good()
        result = create_game_creation_request(data)
        self.assertIsInstance(result, GameCreationRequestResult)
        self.assertTrue(result.ok)
        self.assertIsInstance(result.request, GameCreationRequest)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.codes(), [])
        self.assertEqual(result.request.to_dict(), data)
        self.assertEqual(result.to_dict(), {"ok": True, "request": data, "failures": []})

    def test_02_every_required_field_is_exposed(self):
        r = create_game_creation_request(good()).request
        for f in FIELDS:
            self.assertEqual(getattr(r, f), good()[f], f)
        self.assertEqual(sorted(n for n in dir(r) if not n.startswith("_")), sorted(FIELDS + ("to_dict",)))
        self.assertEqual(list(r.to_dict()), list(FIELDS))

    def test_03_exact_string_preservation(self):
        odd = {"project_id": " p 1 ", "name": "\tMy\nGame ", "description": "  Ünïcödé 🎮  ", "genre": "CASE Sensitive", "target_platform": "\u00a0x\u00a0",
               "version": " v1.0-RC1 "}
        data = dict(odd)
        r = create_game_creation_request(data).request
        for f in FIELDS:
            self.assertIs(getattr(r, f), data[f], f)      # the very same string object, not a rewritten copy
            self.assertEqual(getattr(r, f), odd[f])
        self.assertEqual(r.to_dict(), odd)

    def test_04_empty_optional_strings_are_valid(self):
        for combo in ((), ("description",), ("genre",), ("target_platform",), OPTIONAL):
            data = good(**{f: "" for f in combo})
            r = create_game_creation_request(data)
            self.assertTrue(r.ok, combo)
            for f in combo:
                self.assertEqual(getattr(r.request, f), "")

    def test_05_whitespace_only_optional_strings_are_valid_and_unchanged(self):
        data = good(description="   ", genre="\t", target_platform="\n")
        r = create_game_creation_request(data)
        self.assertTrue(r.ok)
        self.assertEqual((r.request.description, r.request.genre, r.request.target_platform), ("   ", "\t", "\n"))

    def test_06_dict_key_order_does_not_matter(self):
        data = dict(reversed(list(good().items())))
        self.assertEqual(create_game_creation_request(data), create_game_creation_request(good()))


class TestRequiredFields(unittest.TestCase):
    def test_07_empty_required_values_are_rejected(self):
        for f in REQUIRED:
            r = create_game_creation_request(good(**{f: ""}))
            self.assertFalse(r.ok)
            self.assertIsNone(r.request)
            self.assertEqual(r.codes(), [INVALID[f]])
            self.assertEqual(r.failures[0]["field"], f)

    def test_08_whitespace_only_required_values_are_rejected(self):
        for f in REQUIRED:
            for blank in (" ", "   ", "\t", "\n", "\r\n", " \t\n ", "\u00a0", "\u2003"):
                r = create_game_creation_request(good(**{f: blank}))
                self.assertEqual(r.codes(), [INVALID[f]], (f, blank))

    def test_09_required_values_with_inner_or_outer_whitespace_are_valid(self):
        for f in REQUIRED:
            self.assertTrue(create_game_creation_request(good(**{f: " x "})).ok)
            self.assertTrue(create_game_creation_request(good(**{f: "a b"})).ok)
            self.assertTrue(create_game_creation_request(good(**{f: "\u200b"})).ok)      # zero-width space is not whitespace to str.strip()

    def test_10_each_missing_field(self):
        for f in FIELDS:
            data = good()
            del data[f]
            r = create_game_creation_request(data)
            self.assertFalse(r.ok, f)
            self.assertEqual(r.codes(), [MISSING])
            self.assertEqual(r.failures[0]["field"], f)
            self.assertIn(f, r.failures[0]["message"])

    def test_11_all_fields_missing(self):
        r = create_game_creation_request({})
        self.assertEqual(r.codes(), [MISSING] * 6)
        self.assertEqual([x["field"] for x in r.failures], list(FIELDS))

    def test_12_unexpected_fields(self):
        r = create_game_creation_request(good(extra="x"))
        self.assertEqual(r.codes(), [UNEXPECTED])
        self.assertEqual(r.failures[0]["field"], "extra")
        r = create_game_creation_request(good(Name="x", PROJECT_ID="y", engine="z"))
        self.assertEqual(r.codes(), [UNEXPECTED] * 3)
        self.assertEqual([x["field"] for x in r.failures], ["Name", "PROJECT_ID", "engine"])      # sorted by name (plain str ordering)

    def test_13_unexpected_field_with_none_value_is_still_rejected(self):
        self.assertEqual(create_game_creation_request(good(extra=None)).codes(), [UNEXPECTED])

    def test_14_non_str_field_names(self):
        for key in (1, None, b"name", ("a",), 1.5):
            data = good()
            data[key] = "x"
            r = create_game_creation_request(data)
            self.assertEqual(r.codes(), [UNEXPECTED], repr(key))
            self.assertIsNone(r.failures[0]["field"])
        data = good()
        data[StrSubclass("name")] = "dup"      # equal and same hash as "name": replaces the value, key stays exact str
        self.assertEqual(create_game_creation_request(data).codes(), [])

    def test_15_wrong_value_types(self):
        wrong = (None, 1, 1.5, True, b"x", ["x"], ("x",), {"x": 1}, {"x"}, object(), StrSubclass("x"), bytearray(b"x"))
        for f in FIELDS:
            for bad in wrong:
                r = create_game_creation_request(good(**{f: bad}))
                self.assertFalse(r.ok, (f, bad))
                self.assertEqual(r.codes(), [INVALID[f]], (f, bad))
                self.assertEqual(r.failures[0]["field"], f)
                self.assertIn("must be a str", r.failures[0]["message"])

    def test_16_str_subclass_methods_are_never_run(self):
        class Evil(str):
            def strip(self, *a):
                raise AssertionError("subclass method run")

            def __eq__(self, other):
                raise AssertionError("subclass method run")
            __hash__ = str.__hash__
        for f in FIELDS:
            self.assertEqual(create_game_creation_request(good(**{f: Evil("x")})).codes(), [INVALID[f]])


class TestInvalidInput(unittest.TestCase):
    def test_17_non_dict_input(self):
        for bad in (None, "x", 5, 1.5, True, [], (), set(), object(), good, [("project_id", "p")], b"x", iter(good().items()),
                    types.MappingProxyType(good()), create_game_creation_request(good())):
            r = create_game_creation_request(bad)
            self.assertFalse(r.ok, repr(bad))
            self.assertIsNone(r.request)
            self.assertEqual(r.codes(), [INVALID_INPUT])
            self.assertIsNone(r.failures[0]["field"])

    def test_18_dict_subclasses_are_rejected(self):
        for bad in (DictSubclass(good()), collections.OrderedDict(good()), collections.defaultdict(str, good()), collections.Counter()):
            self.assertEqual(create_game_creation_request(bad).codes(), [INVALID_INPUT], type(bad).__name__)

    def test_19_invalid_input_never_raises(self):
        class Boom(dict):
            def __iter__(self):
                raise AssertionError("iterated")
        weird = [None, 0, "", (), [], {}, set(), object(), Ellipsis, create_game_creation_request, float("nan"), Boom(),
                 {1: 2}, {None: None}, {"project_id": object()}, {"a": {"b": [1]}}, good(version=float("nan"))]
        for bad in weird:
            try:
                result = create_game_creation_request(bad)
            except Exception as exc:      # pragma: no cover
                self.fail("raised %r for %r" % (exc, bad))
            self.assertIsInstance(result, GameCreationRequestResult)
        with self.assertRaises(TypeError):      # wrong argument COUNT is a Python call error, not bad data
            create_game_creation_request()


class TestFailureOrdering(unittest.TestCase):
    def test_20_deterministic_failure_ordering(self):
        data = {"version": 5, "zeta": 1, "name": "", "Alpha": 2, "genre": None, "project_id": "p", 7: "x"}
        r = create_game_creation_request(data)
        self.assertEqual(r.codes(), [UNEXPECTED] * 3 + [INVALID["name"], MISSING, INVALID["genre"], MISSING, INVALID["version"]])
        self.assertEqual([x["field"] for x in r.failures], [None, "Alpha", "zeta", "name", "description", "genre", "target_platform", "version"])
        self.assertEqual(r, create_game_creation_request(dict(data)))
        self.assertEqual(r.to_dict(), create_game_creation_request(dict(reversed(list(data.items())))).to_dict())

    def test_21_field_failures_follow_model_order(self):
        r = create_game_creation_request({"version": "", "target_platform": 1, "genre": 1, "description": 1, "name": "", "project_id": ""})
        self.assertEqual(r.codes(), [INVALID[f] for f in FIELDS])
        self.assertEqual([x["field"] for x in r.failures], list(FIELDS))

    def test_22_codes_are_stable_and_prefixed(self):
        self.assertEqual(cr.FAILURE_CODES, (INVALID_INPUT, UNEXPECTED, MISSING) + tuple(INVALID[f] for f in FIELDS))
        self.assertEqual(len(set(cr.FAILURE_CODES)), 9)
        self.assertTrue(all(c.startswith("GAME_CREATION_REQUEST_") for c in cr.FAILURE_CODES))


class TestImmutabilityAndEquality(unittest.TestCase):
    def test_23_deterministic_equality_and_hash(self):
        a, b = create_game_creation_request(good()), create_game_creation_request(good())
        self.assertIsNot(a.request, b.request)
        self.assertEqual(a.request, b.request)
        self.assertEqual(hash(a.request), hash(b.request))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a.request, b.request}), 1)
        for f in FIELDS:
            self.assertNotEqual(a.request, create_game_creation_request(good(**{f: "other"})).request, f)
        self.assertNotEqual(a.request, a.request.to_dict())
        self.assertNotEqual(a, a.to_dict())
        bad1, bad2 = create_game_creation_request(None), create_game_creation_request("x")
        self.assertEqual(bad1, bad2)
        self.assertEqual(hash(bad1), hash(bad2))
        self.assertNotEqual(bad1, a)
        self.assertNotEqual(create_game_creation_request({}), bad1)

    def test_24_fresh_to_dict(self):
        r = create_game_creation_request(good())
        d1, d2 = r.request.to_dict(), r.request.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        snapshot = r.request.to_dict()
        d1["name"] = "mutated"
        d1["extra"] = 1
        del d1["version"]
        self.assertEqual(r.request.to_dict(), snapshot)
        t1, t2 = r.to_dict(), r.to_dict()
        self.assertIsNot(t1, t2)
        self.assertIsNot(t1["request"], t2["request"])
        self.assertIsNot(t1["failures"], t2["failures"])
        t1["request"]["name"] = "mutated"
        self.assertEqual(r.to_dict()["request"]["name"], "My Game")

    def test_25_fresh_failures_and_codes(self):
        bad = create_game_creation_request({"name": ""})
        self.assertIsNot(bad.failures, bad.failures)
        self.assertIsNot(bad.failures[0], bad.failures[0])
        self.assertIsNot(bad.codes(), bad.codes())
        snapshot = bad.to_dict()
        bad.failures.append("junk")
        bad.failures[0]["code"] = "x"
        bad.codes().append("x")
        bad.to_dict()["failures"][0]["message"] = "x"
        self.assertEqual(bad.to_dict(), snapshot)
        self.assertIsNone(bad.to_dict()["request"])

    def test_26_to_dict_is_plain_data(self):
        def check(value):
            self.assertIn(type(value), (dict, list, str, bool, type(None)))
            if type(value) is dict:
                for k, v in value.items():
                    self.assertIs(type(k), str)
                    check(v)
            elif type(value) is list:
                for v in value:
                    check(v)
        check(create_game_creation_request(good()).to_dict())
        check(create_game_creation_request({"a": 1, 5: 2}).to_dict())
        check(create_game_creation_request(None).to_dict())

    def test_27_attributes_are_read_only(self):
        result = create_game_creation_request(good())
        for obj, names in ((result.request, FIELDS + tuple("_" + f for f in FIELDS) + ("extra", "to_dict")),
                           (result, ("ok", "request", "failures", "_request", "_failures", "extra", "codes"))):
            for name in names:
                with self.assertRaises(AttributeError, msg=(type(obj).__name__, name)):
                    setattr(obj, name, "x")
                with self.assertRaises(AttributeError, msg=(type(obj).__name__, name)):
                    delattr(obj, name)
            self.assertFalse(hasattr(obj, "__dict__"))
        self.assertEqual(result.request.to_dict(), good())

    def test_28_direct_construction_is_refused(self):
        values = [good()[f] for f in FIELDS]
        for token in (object(), None, True):
            with self.assertRaises(TypeError):
                GameCreationRequest(token, *values)
            with self.assertRaises(TypeError):
                GameCreationRequestResult(token, None, [])
        with self.assertRaises(TypeError):
            GameCreationRequest(*values)
        with self.assertRaises(TypeError):
            GameCreationRequest()
        with self.assertRaises(TypeError):
            GameCreationRequestResult()

    def test_29_subclassing_is_refused(self):
        for base in (GameCreationRequest, GameCreationRequestResult):
            with self.assertRaises(TypeError):
                type("Sub", (base,), {})

    def test_30_copy_and_deepcopy_return_the_same_object(self):
        result = create_game_creation_request(good())
        for obj in (result, result.request, create_game_creation_request(None)):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)

    def test_31_pickle_is_refused(self):
        result = create_game_creation_request(good())
        for obj in (result, result.request, create_game_creation_request(None)):
            for protocol in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(obj, protocol)

    def test_32_repr_is_deterministic(self):
        r = create_game_creation_request(good())
        self.assertEqual(repr(r.request), "GameCreationRequest(project_id='p1', name='My Game', version='1.0')")
        self.assertEqual(repr(r), "GameCreationRequestResult(ok=True, failures=0)")
        self.assertEqual(repr(create_game_creation_request(None)), "GameCreationRequestResult(ok=False, failures=1)")


class TestNoProjectAndNoMutation(unittest.TestCase):
    def test_33_no_project_is_created(self):
        with mock.patch.object(game_project_module, "create_game_project", side_effect=AssertionError("project created")), \
             mock.patch.object(game_project_module, "GameProject", side_effect=AssertionError("project built")):
            self.assertTrue(create_game_creation_request(good()).ok)
            self.assertFalse(create_game_creation_request({"name": ""}).ok)
            self.assertFalse(create_game_creation_request(None).ok)
        self.assertFalse(hasattr(cr, "create_game_project"))
        self.assertFalse(hasattr(cr, "GameProject"))

    def test_34_module_imports_nothing_at_runtime(self):
        code = ("import sys; before=set(sys.modules); import game_creation.game_creation_request as m; "
                "new=sorted(n for n in set(sys.modules)-before if n.startswith('game_creation')); print(new)")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=PY_ROOT)
        out = subprocess.run([sys.executable, "-c", code], cwd=PY_ROOT, env=env, capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(out, "['game_creation', 'game_creation.game_creation_request']")

    def test_35_supplied_dict_is_not_mutated(self):
        data = good()
        values = {k: v for k, v in data.items()}
        order = list(data)
        for payload in (data, dict(data, extra=1), {k: v for k, v in data.items() if k != "name"}, dict(data, name="")):
            snapshot = dict(payload)
            keys = list(payload)
            create_game_creation_request(payload)
            self.assertEqual(payload, snapshot)
            self.assertEqual(list(payload), keys)
            for k in snapshot:
                self.assertIs(payload[k], snapshot[k])
        self.assertEqual((list(data), data), (order, values))

    def test_36_request_is_independent_of_the_supplied_dict(self):
        data = good()
        r = create_game_creation_request(data).request
        data["name"] = "changed"
        data["extra"] = 1
        del data["version"]
        self.assertEqual(r.to_dict(), good())

    def test_37_same_input_gives_same_result_every_time(self):
        data = good(extra=1)
        self.assertEqual([create_game_creation_request(data).to_dict() for _ in range(3)], [create_game_creation_request(data).to_dict()] * 3)


class TestSourceBoundaries(unittest.TestCase):
    def tree(self):
        with open(SOURCE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_38_module_imports_nothing(self):
        self.assertEqual([ast.unparse(n) for n in ast.walk(self.tree()) if isinstance(n, (ast.Import, ast.ImportFrom))], [])

    def test_39_module_does_not_reference_project_definition_registry_or_query_layers(self):
        tree = self.tree()
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("GameProject", "create_game_project", "GameProjectStructure", "GameDefinition", "create_game_definition",
                          "GameSceneRegistry", "GameCharacterRegistry", "GameAssetRegistry", "GameplaySystemRegistry",
                          "GameSceneCompositionRegistry", "GameSceneBundleRegistry", "GameProjectValidator", "GameSceneCompositionValidator",
                          "validate_game_project", "validate_game_scene_composition", "lookup_game_scene", "lookup_game_scene_bundle",
                          "has_game_scene", "build_game_definition_summary", "get_game_definition_counts", "Core", "Planner", "AgentLoop",
                          "process_input", "copy", "pickle", "os", "sys", "open"):
            self.assertNotIn(forbidden, names, forbidden)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node is not tree.body[0].value:
                for token in ("game_project", "game_definition", "GameDefinition"):
                    self.assertNotIn(token, node.value)

    def test_40_values_are_never_rewritten(self):
        tree = self.tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for method in ("lstrip", "rstrip", "lower", "upper", "casefold", "normalize", "title", "capitalize", "encode", "decode", "replace", "join",
                       "split", "str", "int", "bool", "repr_value"):
            self.assertFalse([c for c in calls if c == method or c.endswith("." + method)], method)
        strips = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func).endswith(".strip")]
        self.assertEqual(strips, ["value.strip()"])      # the only use: a blank check whose result is compared, never stored
        compared = [n for n in ast.walk(tree) if isinstance(n, ast.Compare) and "value.strip()" in ast.unparse(n)]
        self.assertEqual([ast.unparse(n) for n in compared], ["value.strip() == ''"])

    def test_41_no_io_and_no_module_level_mutable_state(self):
        tree = self.tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "copy.copy", "copy.deepcopy"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(cr).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set, bytearray), name)
        self.assertIs(type(cr.FIELDS), tuple)
        self.assertIs(type(cr.REQUIRED_NON_BLANK), tuple)
        self.assertIs(type(cr.FAILURE_CODES), tuple)

    def test_42_exactly_one_public_function_and_two_classes(self):
        tree = self.tree()
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")], ["create_game_creation_request"])
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.ClassDef)], ["GameCreationRequest", "GameCreationRequestResult"])


class TestScopeAndDocumentation(unittest.TestCase):
    def test_43_earlier_modules_are_untouched_and_unaware_of_the_request(self):
        listing = sorted(os.listdir(os.path.join(PY_ROOT, "game_creation")))
        self.assertEqual(listing, [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py",
            "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py",
            "game_definition_summary.py", "game_project.py", "game_project_structure.py", "game_project_validator.py", "game_scene.py",
            "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py", "game_scene_composition_registry.py",
            "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in listing:
            if rel in ("game_creation_request.py", "game_creation_request_bridge.py", "game_definition_from_request.py", "game_structure_from_request.py", "__init__.py"):
                continue
            with open(os.path.join(PY_ROOT, "game_creation", rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation_request", "create_game_creation_request", "GameCreationRequest"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "game_creation_request", "create_game_creation_request"):
                self.assertNotIn(token, text, (rel, token))

    def test_44_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_game_creation_request", "GameCreationRequestResult", "GameCreationRequest", "GAME_CREATION_REQUEST_", "INVALID_INPUT",
                       "UNEXPECTED_FIELD", "MISSING_FIELD", "INVALID_PROJECT_ID", "INVALID_NAME", "INVALID_DESCRIPTION", "INVALID_GENRE",
                       "INVALID_TARGET_PLATFORM", "INVALID_VERSION", "exact", "does NOT", "imports nothing", "Prompt 740"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
