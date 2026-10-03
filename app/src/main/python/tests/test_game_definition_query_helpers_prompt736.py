"""Prompt 736 - Section 7 game definition query helpers (`game_creation.game_definition_query_helpers`)."""
import ast
import hashlib
import os
import unittest
from unittest import mock

from game_creation import game_definition_queries as queries
from game_creation import game_definition_query_helpers as helpers
from game_creation.game_definition_query_helpers import has_game_scene, has_game_scene_bundle
from game_creation.game_scene_bundle_registry import GameSceneBundleRegistry
from game_creation.game_scene_registry import GameSceneRegistry

from tests.test_game_definition_queries_prompt735 import FakeDefinition, StrSubclass, make_definition

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_definition_query_helpers_prompt736.md")
SOURCE = os.path.join(PY_ROOT, "game_creation", "game_definition_query_helpers.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

PAIRS = ((has_game_scene, "lookup_game_scene"), (has_game_scene_bundle, "lookup_game_scene_bundle"))


class TestBehavior(unittest.TestCase):
    def test_01_valid_found_case(self):
        d = make_definition()
        self.assertIs(has_game_scene(d, "s1"), True)
        self.assertIs(has_game_scene(d, "s2"), True)
        self.assertIs(has_game_scene_bundle(d, "s1"), True)
        self.assertIs(has_game_scene_bundle(d, "Arena"), True)

    def test_02_valid_missing_case(self):
        d = make_definition()
        self.assertIs(has_game_scene(d, "nope"), False)
        self.assertIs(has_game_scene_bundle(d, "nope"), False)
        self.assertIs(has_game_scene_bundle(d, "s2"), False)      # a scene without a bundle
        self.assertIs(has_game_scene(d, ""), False)
        self.assertIs(has_game_scene_bundle(d, ""), False)

    def test_03_empty_registries(self):
        d = make_definition((), ())
        self.assertIs(has_game_scene(d, "s1"), False)
        self.assertIs(has_game_scene_bundle(d, "s1"), False)

    def test_04_invalid_game_definition(self):
        d = make_definition()
        for bad in (None, "d", 5, {}, [], object(), FakeDefinition(), d.scene_registry, d.bundle_registry, d.to_dict(), type(d)):
            for fn, _ in PAIRS:
                self.assertIs(fn(bad, "s1"), False, repr(bad))

    def test_05_invalid_scene_id(self):
        d = make_definition()
        for bad in (None, 1, 1.5, True, b"s1", ["s1"], ("s1",), {"s1"}, {}, object(), StrSubclass("s1"), d):
            for fn, _ in PAIRS:
                self.assertIs(fn(d, bad), False, repr(bad))

    def test_06_exact_case_sensitivity(self):
        d = make_definition(("Arena", "arena"), ("Arena",))
        self.assertTrue(has_game_scene(d, "Arena"))
        self.assertTrue(has_game_scene(d, "arena"))
        self.assertFalse(has_game_scene(d, "ARENA"))
        self.assertTrue(has_game_scene_bundle(d, "Arena"))
        self.assertFalse(has_game_scene_bundle(d, "arena"))
        self.assertFalse(has_game_scene_bundle(d, "ARENA"))

    def test_07_exact_whitespace_sensitivity(self):
        d = make_definition(("arena", "arena "), ("arena",))
        self.assertTrue(has_game_scene(d, "arena "))
        self.assertTrue(has_game_scene_bundle(d, "arena"))
        self.assertFalse(has_game_scene_bundle(d, "arena "))
        for bad in (" arena", "arena\t", "arena\n", " arena ", "are na"):
            self.assertFalse(has_game_scene(d, bad), repr(bad))
            self.assertFalse(has_game_scene_bundle(d, bad), repr(bad))

    def test_08_invalid_input_never_raises(self):
        d = make_definition()
        weird = [None, 0, "", (), [], {}, set(), object(), Ellipsis, type(d), make_definition, float("nan"), FakeDefinition(), d]
        for a in weird:
            for b in weird + ["s1"]:
                for fn, _ in PAIRS:
                    try:
                        result = fn(a, b)
                    except Exception as exc:      # pragma: no cover
                        self.fail("raised %r" % (exc,))
                    self.assertIs(type(result), bool)
        with self.assertRaises(TypeError):      # wrong argument COUNT is a Python call error, not bad data
            has_game_scene(d)

    def test_09_deterministic(self):
        a, b = make_definition(), make_definition()
        for fn, _ in PAIRS:
            self.assertEqual([fn(a, i) for i in ("s1", "s2", "x", None)], [fn(b, i) for i in ("s1", "s2", "x", None)])
            self.assertEqual(fn(a, "s1"), fn(a, "s1"))


class TestDelegation(unittest.TestCase):
    def test_10_each_helper_delegates_to_its_query_function(self):
        d = make_definition()
        for fn, name in PAIRS:
            other = [n for _, n in PAIRS if n != name][0]
            with mock.patch.object(helpers, name, wraps=getattr(queries, name)) as used, \
                 mock.patch.object(helpers, other, side_effect=AssertionError("wrong query used")):
                self.assertTrue(fn(d, "s1"))
                used.assert_called_once_with(d, "s1")

    def test_11_arguments_are_passed_through_unchanged_even_when_invalid(self):
        for fn, name in PAIRS:
            for a, b in ((None, None), ("x", 5), (object(), StrSubclass("s1"))):
                with mock.patch.object(helpers, name, wraps=getattr(queries, name)) as used:
                    fn(a, b)
                (got_a, got_b), kwargs = used.call_args
                self.assertIs(got_a, a)
                self.assertIs(got_b, b)
                self.assertEqual(kwargs, {})

    def test_12_helpers_return_exactly_result_found(self):
        d = make_definition()
        for fn, name in PAIRS:
            for found in (True, False):
                result = mock.Mock(found=found)
                with mock.patch.object(helpers, name, return_value=result):
                    self.assertIs(fn(d, "s1"), found)
            sentinel = object()
            with mock.patch.object(helpers, name, return_value=mock.Mock(found=sentinel)):
                self.assertIs(fn(d, "s1"), sentinel)      # no bool() conversion, no extra logic
            for sid in ("s1", "s2", "Arena", "nope", None):
                self.assertIs(fn(d, sid), getattr(queries, name)(d, sid).found)

    def test_13_registry_lookup_still_runs_through_the_query_layer(self):
        d = make_definition()
        with mock.patch.object(GameSceneRegistry, "lookup", autospec=True, side_effect=GameSceneRegistry.lookup) as sl, \
             mock.patch.object(GameSceneBundleRegistry, "lookup", autospec=True, side_effect=GameSceneBundleRegistry.lookup) as bl:
            has_game_scene(d, "s1")
            sl.assert_called_once_with(d.scene_registry, "s1")
            bl.assert_not_called()
            has_game_scene_bundle(d, "s1")
            bl.assert_called_once_with(d.bundle_registry, "s1")
            sl.assert_called_once()

    def test_14_no_registry_internal_access(self):
        d = make_definition()
        touched = []
        with mock.patch.object(GameSceneRegistry, "scenes", new=property(lambda s: touched.append("scenes"))), \
             mock.patch.object(GameSceneRegistry, "scene_ids", new=property(lambda s: touched.append("scene_ids"))), \
             mock.patch.object(GameSceneBundleRegistry, "bundles", new=property(lambda s: touched.append("bundles"))), \
             mock.patch.object(GameSceneBundleRegistry, "scene_ids", new=property(lambda s: touched.append("scene_ids"))), \
             mock.patch.object(GameSceneRegistry, "to_dict", side_effect=lambda: touched.append("to_dict")), \
             mock.patch.object(GameSceneBundleRegistry, "to_dict", side_effect=lambda: touched.append("to_dict")):
            self.assertTrue(has_game_scene(d, "s1") and has_game_scene_bundle(d, "s1"))
            self.assertFalse(has_game_scene(d, "x") or has_game_scene_bundle(d, "x"))
        self.assertEqual(touched, [])

    def test_15_no_mutation(self):
        d = make_definition()
        names = ("project", "structure", "scene_registry", "character_registry", "gameplay_system_registry", "asset_registry",
                 "composition_registry", "bundle_registry")
        before, hashes, whole = {n: getattr(d, n).to_dict() for n in names}, {n: hash(getattr(d, n)) for n in names}, d.to_dict()
        for sid in ("s1", "s2", "Arena", "nope", "", "arena ", None, 5):
            has_game_scene(d, sid)
            has_game_scene_bundle(d, sid)
        has_game_scene(None, "s1")
        has_game_scene_bundle(None, "s1")
        self.assertEqual({n: getattr(d, n).to_dict() for n in names}, before)
        self.assertEqual({n: hash(getattr(d, n)) for n in names}, hashes)
        self.assertEqual(d.to_dict(), whole)
        self.assertEqual(d, make_definition())


class TestSourceBoundaries(unittest.TestCase):
    def tree(self):
        with open(SOURCE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_16_module_imports_only_the_two_query_functions_relatively(self):
        imports = [n for n in ast.walk(self.tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual([(n.module, tuple(a.name for a in n.names)) for n in imports],
                         [("game_definition_queries", ("lookup_game_scene", "lookup_game_scene_bundle"))])

    def test_17_exactly_two_public_functions_and_nothing_else(self):
        tree = self.tree()
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef)], ["has_game_scene", "has_game_scene_bundle"])
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.ImportFrom, ast.FunctionDef))
        self.assertEqual(sorted(n for n, v in vars(helpers).items() if not n.startswith("_") and callable(v) and getattr(v, "__module__", "") == helpers.__name__),
                         ["has_game_scene", "has_game_scene_bundle"])

    def test_18_each_helper_is_a_single_delegating_return_of_found(self):
        for func, expected in zip([n for n in self.tree().body if isinstance(n, ast.FunctionDef)],
                                  ("lookup_game_scene(game_definition, scene_id).found", "lookup_game_scene_bundle(game_definition, scene_id).found")):
            self.assertEqual([ast.unparse(a) for a in func.args.args], ["game_definition", "scene_id"])
            statements = [s for s in func.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
            self.assertEqual(len(statements), 1)
            self.assertIsInstance(statements[0], ast.Return)
            self.assertEqual(ast.unparse(statements[0].value), expected)

    def test_19_no_scanning_internals_normalization_or_duplicated_lookup(self):
        tree = self.tree()
        code_nodes = [n for f in tree.body if isinstance(f, ast.FunctionDef) for n in ast.walk(f)]
        self.assertFalse([n for n in code_nodes if isinstance(n, (ast.For, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.Compare, ast.If, ast.BoolOp, ast.Try))])
        attrs = {n.attr for n in code_nodes if isinstance(n, ast.Attribute)}
        self.assertEqual(attrs, {"found"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("GameDefinition", "scene_registry", "bundle_registry", "scenes", "bundles", "scene_ids", "lookup", "to_dict", "GameSceneRegistry",
                          "GameSceneBundleRegistry", "GameSceneCompositionRegistry", "GameProjectValidator", "GameSceneCompositionValidator",
                          "create_game_definition", "Core", "Planner", "AgentLoop", "process_input"):
            self.assertNotIn(forbidden, names, forbidden)
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertEqual(calls, {"lookup_game_scene", "lookup_game_scene_bundle"})

    def test_20_module_is_stateless(self):
        for name, value in vars(helpers).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)


class TestScopeAndDocumentation(unittest.TestCase):
    def test_21_earlier_modules_are_untouched_and_unaware_of_the_helpers(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py",
            "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py", "game_project_structure.py",
            "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py", "game_scene_composition.py",
            "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py", "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))):
            if rel in ("game_definition_query_helpers.py", "__init__.py"):
                continue
            with open(os.path.join(PY_ROOT, "game_creation", rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_definition_query_helpers", "has_game_scene"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "game_definition_query_helpers", "has_game_scene"):
                self.assertNotIn(token, text, (rel, token))

    def test_22_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("has_game_scene", "has_game_scene_bundle", "lookup_game_scene", "lookup_game_scene_bundle", "found", "exact", "does NOT",
                       "Prompt 735", "Prompt 737"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
