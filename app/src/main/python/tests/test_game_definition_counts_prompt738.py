"""Prompt 738 - Section 7 game definition counts query (`game_creation.game_definition_counts`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from game_creation import game_definition_counts as sm
from game_creation.game_asset_registry import GameAssetRegistry
from game_creation.game_character_registry import GameCharacterRegistry
from game_creation.game_definition import GameDefinition
from game_creation.game_definition_counts import GameDefinitionCountsResult, get_game_definition_counts
from game_creation.game_scene_bundle_registry import GameSceneBundleRegistry
from game_creation.game_scene_composition_registry import GameSceneCompositionRegistry
from game_creation.game_scene_registry import GameSceneRegistry
from game_creation.gameplay_system_registry import GameplaySystemRegistry

from tests.test_game_definition_queries_prompt735 import FakeDefinition, make_definition

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_definition_counts_prompt738.md")
SOURCE = os.path.join(PY_ROOT, "game_creation", "game_definition_counts.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
INVALID = "GAME_DEFINITION_COUNTS_INVALID_GAME_DEFINITION"
KEYS = ["scene_count", "character_count", "gameplay_system_count", "asset_count", "composition_count", "bundle_count"]
PUBLIC_PROPS = {GameSceneRegistry: "scenes", GameCharacterRegistry: "characters", GameplaySystemRegistry: "gameplay_system_ids",
                GameAssetRegistry: "assets", GameSceneCompositionRegistry: "compositions", GameSceneBundleRegistry: "bundles"}


class TestSummary(unittest.TestCase):
    def test_01_valid_game_definition(self):
        r = get_game_definition_counts(make_definition())
        self.assertIsInstance(r, GameDefinitionCountsResult)
        self.assertTrue(r.ok)
        self.assertEqual(r.failures, [])
        self.assertIsNotNone(r.counts)

    def test_02_exact_count_keys(self):
        s = get_game_definition_counts(make_definition()).counts
        self.assertEqual(list(s), KEYS)
        self.assertEqual(sorted(n for n in dir(get_game_definition_counts(make_definition())) if not n.startswith("_")),
                         ["counts", "failures", "ok", "to_dict"])

    def test_03_exact_counts(self):
        d = make_definition()      # 5 scenes, 1 character, 1 system, 1 asset, 5 compositions, 2 bundles
        s = get_game_definition_counts(d).counts
        self.assertEqual([s[k] for k in KEYS], [5, 1, 1, 1, 5, 2])
        self.assertEqual(s["scene_count"], len(d.scene_registry.scenes))
        self.assertEqual(s["character_count"], len(d.character_registry.characters))
        self.assertEqual(s["gameplay_system_count"], len(d.gameplay_system_registry.gameplay_system_ids))
        self.assertEqual(s["asset_count"], len(d.asset_registry.assets))
        self.assertEqual(s["composition_count"], len(d.composition_registry.compositions))
        self.assertEqual(s["bundle_count"], len(d.bundle_registry.bundles))
        d2 = make_definition(("a", "b", "c"), ("a", "b", "c"))
        self.assertEqual([get_game_definition_counts(d2).counts[k] for k in KEYS], [3, 1, 1, 1, 3, 3])
        self.assertTrue(all(type(get_game_definition_counts(d2).counts[k]) is int for k in KEYS))

    def test_05_empty_registries_produce_zero_counts(self):
        d = make_definition((), ())
        # character/system/asset registries in the fixture are non-empty; the scene-related ones are empty
        s = get_game_definition_counts(d).counts
        self.assertEqual((s["scene_count"], s["composition_count"], s["bundle_count"]), (0, 0, 0))
        self.assertEqual((s["character_count"], s["gameplay_system_count"], s["asset_count"]), (1, 1, 1))

    def test_06_all_registries_zero_when_every_registry_is_empty(self):
        d = make_definition((), ())
        stub = {cls: mock.patch.object(cls, prop, new=property(lambda self: ())) for cls, prop in PUBLIC_PROPS.items()}
        for p in stub.values():
            p.start()
        try:
            s = get_game_definition_counts(d).counts
        finally:
            for p in stub.values():
                p.stop()
        self.assertEqual([s[k] for k in KEYS], [0] * 6)

    def test_07_counts_come_only_from_the_public_properties(self):
        d = make_definition()
        for cls, prop in PUBLIC_PROPS.items():
            with mock.patch.object(cls, prop, new=property(lambda self: (None,) * 7)):
                s = get_game_definition_counts(d).counts
            self.assertEqual([k for k in KEYS if s[k] == 7], [KEYS[list(PUBLIC_PROPS).index(cls)]], cls.__name__)

    def test_08_registry_order_and_contents_are_irrelevant_to_counts(self):
        self.assertEqual(get_game_definition_counts(make_definition(("a", "b"), ("b",))).counts["bundle_count"], 1)
        self.assertEqual(get_game_definition_counts(make_definition(("b", "a"), ("a", "b"))).counts["scene_count"], 2)


class TestInvalidInput(unittest.TestCase):
    def test_09_invalid_game_definition(self):
        d = make_definition()
        for bad in (None, "d", 5, {}, [], object(), FakeDefinition(), d.project, d.scene_registry, d.to_dict(), GameDefinition,
                    get_game_definition_counts(d)):
            r = get_game_definition_counts(bad)
            self.assertFalse(r.ok, repr(bad))
            self.assertIsNone(r.counts)
            self.assertEqual(r.failures, [{"code": INVALID, "field": "game_definition", "message": "game_definition must be exactly a GameDefinition."}])
            self.assertEqual(r.to_dict(), {"ok": False, "counts": None, "failures": r.failures})

    def test_10_invalid_input_never_raises(self):
        for bad in (None, 0, "", (), [], {}, set(), object(), Ellipsis, GameDefinition, make_definition, float("nan"), FakeDefinition()):
            try:
                self.assertFalse(get_game_definition_counts(bad).ok)
            except Exception as exc:      # pragma: no cover
                self.fail("raised %r" % (exc,))
        with self.assertRaises(TypeError):      # wrong argument COUNT is a Python call error, not bad data
            get_game_definition_counts()

    def test_11_subclass_like_or_proxy_objects_are_rejected_without_being_read(self):
        class Boom:
            def __getattr__(self, name):
                raise AssertionError("read " + name)
        self.assertEqual(get_game_definition_counts(Boom()).failures[0]["code"], INVALID)

    def test_12_registries_are_not_read_for_invalid_input(self):
        with mock.patch.object(GameSceneRegistry, "scenes", new=property(lambda s: (_ for _ in ()).throw(AssertionError("read")))):
            self.assertFalse(get_game_definition_counts(None).ok)


class TestNoAccessAndNoMutation(unittest.TestCase):
    def test_13_no_registry_internal_or_other_member_access(self):
        d = make_definition()
        touched = []

        def tripwire(name):
            return property(lambda self: touched.append(name))
        with mock.patch.object(GameSceneRegistry, "scene_ids", new=tripwire("scene_ids")), \
             mock.patch.object(GameCharacterRegistry, "character_ids", new=tripwire("character_ids")), \
             mock.patch.object(GameAssetRegistry, "asset_ids", new=tripwire("asset_ids")), \
             mock.patch.object(GameSceneCompositionRegistry, "scene_ids", new=tripwire("composition.scene_ids")), \
             mock.patch.object(GameSceneBundleRegistry, "scene_ids", new=tripwire("bundle.scene_ids")), \
             mock.patch.object(GameSceneRegistry, "lookup", side_effect=lambda *a: touched.append("lookup")), \
             mock.patch.object(GameSceneBundleRegistry, "lookup", side_effect=lambda *a: touched.append("lookup")), \
             mock.patch.object(GameSceneRegistry, "to_dict", side_effect=lambda: touched.append("to_dict")), \
             mock.patch.object(GameSceneBundleRegistry, "to_dict", side_effect=lambda: touched.append("to_dict")), \
             mock.patch.object(GameDefinition, "to_dict", side_effect=lambda: touched.append("definition.to_dict")):
            self.assertTrue(get_game_definition_counts(d).ok)
        self.assertEqual(touched, [])

    def test_14_only_the_six_public_properties_are_read(self):
        d = make_definition()
        reads = []
        patches = []
        for cls, prop in PUBLIC_PROPS.items():
            original = getattr(cls, prop)
            patches.append(mock.patch.object(cls, prop, new=property(lambda self, o=original, n=prop: (reads.append(n), o.fget(self))[1])))
        for p in patches:
            p.start()
        try:
            get_game_definition_counts(d)
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(reads, ["scenes", "characters", "gameplay_system_ids", "assets", "compositions", "bundles"])

    def test_15_no_mutation(self):
        d = make_definition()
        names = ("project", "structure", "scene_registry", "character_registry", "gameplay_system_registry", "asset_registry",
                 "composition_registry", "bundle_registry")
        before, hashes, whole = {n: getattr(d, n).to_dict() for n in names}, {n: hash(getattr(d, n)) for n in names}, d.to_dict()
        r = get_game_definition_counts(d)
        r.counts["scene_count"] = 99
        r.to_dict()["counts"]["scene_count"] = 99
        get_game_definition_counts(None)
        self.assertEqual({n: getattr(d, n).to_dict() for n in names}, before)
        self.assertEqual({n: hash(getattr(d, n)) for n in names}, hashes)
        self.assertEqual(d.to_dict(), whole)
        self.assertEqual(d, make_definition())


class TestResultConventions(unittest.TestCase):
    def test_16_deterministic_equality_and_hash(self):
        a, b = get_game_definition_counts(make_definition()), get_game_definition_counts(make_definition())
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, get_game_definition_counts(make_definition(("a",), ("a",))))
        self.assertNotEqual(a, get_game_definition_counts(None))
        self.assertEqual(get_game_definition_counts(None), get_game_definition_counts("x"))
        self.assertEqual(hash(get_game_definition_counts(None)), hash(get_game_definition_counts(5)))
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, a.counts)

    def test_17_fresh_to_dict(self):
        r = get_game_definition_counts(make_definition())
        d1, d2 = r.to_dict(), r.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertIsNot(d1["counts"], d2["counts"])
        self.assertIsNot(d1["failures"], d2["failures"])
        self.assertEqual(d1["counts"], r.counts)
        self.assertEqual(list(d1["counts"]), KEYS)
        snapshot = r.to_dict()
        d1["counts"]["scene_count"] = 99
        d1["counts"].clear()
        d1["failures"].append("junk")
        d1["ok"] = False
        self.assertEqual(r.to_dict(), snapshot)

    def test_18_counts_and_failures_are_fresh(self):
        r = get_game_definition_counts(make_definition())
        self.assertIsNot(r.counts, r.counts)
        r.counts["scene_count"] = 99
        r.counts.clear()
        self.assertEqual(r.counts["scene_count"], 5)
        bad = get_game_definition_counts(None)
        self.assertIsNot(bad.failures, bad.failures)
        self.assertIsNot(bad.failures[0], bad.failures[0])
        bad.failures.append("junk")
        bad.failures[0]["code"] = "x"
        self.assertEqual(bad.failures[0]["code"], INVALID)

    def test_19_to_dict_is_plain_data(self):
        def check(value):
            self.assertIn(type(value), (dict, list, str, bool, type(None), int))
            if type(value) is dict:
                for k, v in value.items():
                    self.assertIs(type(k), str)
                    check(v)
            elif type(value) is list:
                for v in value:
                    check(v)
        check(get_game_definition_counts(make_definition()).to_dict())
        check(get_game_definition_counts(None).to_dict())

    def test_20_attributes_are_read_only(self):
        for r in (get_game_definition_counts(make_definition()), get_game_definition_counts(None)):
            for name in ("ok", "counts", "failures", "_data", "_failures", "extra", "to_dict"):
                with self.assertRaises(AttributeError, msg=name):
                    setattr(r, name, 1)
                with self.assertRaises(AttributeError, msg=name):
                    delattr(r, name)
            self.assertFalse(hasattr(r, "__dict__"))

    def test_21_direct_construction_is_refused(self):
        for token in (object(), None, True):
            with self.assertRaises(TypeError):
                GameDefinitionCountsResult(token, None, [])
        with self.assertRaises(TypeError):
            GameDefinitionCountsResult(None, [])
        with self.assertRaises(TypeError):
            GameDefinitionCountsResult()

    def test_22_subclassing_is_refused(self):
        with self.assertRaises(TypeError):
            type("Sub", (GameDefinitionCountsResult,), {})

    def test_23_copy_and_deepcopy_return_the_same_object(self):
        for r in (get_game_definition_counts(make_definition()), get_game_definition_counts(None)):
            self.assertIs(copy.copy(r), r)
            self.assertIs(copy.deepcopy(r), r)

    def test_24_pickle_is_refused(self):
        for r in (get_game_definition_counts(make_definition()), get_game_definition_counts(None)):
            for protocol in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(r, protocol)

    def test_25_repr_is_deterministic(self):
        self.assertEqual(repr(get_game_definition_counts(None)), "GameDefinitionCountsResult(ok=False, failures=1)")
        self.assertEqual(repr(get_game_definition_counts(make_definition())), "GameDefinitionCountsResult(ok=True, failures=0)")


class TestSourceBoundaries(unittest.TestCase):
    def tree(self):
        with open(SOURCE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_26_module_imports_only_game_definition_relatively(self):
        imports = [n for n in ast.walk(self.tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual([(n.module, tuple(a.name for a in n.names)) for n in imports], [("game_definition", ("GameDefinition",))])

    def test_27_exactly_one_public_function(self):
        tree = self.tree()
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef)], ["get_game_definition_counts"])
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.ClassDef)], ["GameDefinitionCountsResult"])
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))

    def test_28_function_reads_only_the_six_public_properties(self):
        func = [n for n in self.tree().body if isinstance(n, ast.FunctionDef)][0]
        paths = sorted(ast.unparse(n) for n in ast.walk(func) if isinstance(n, ast.Attribute))
        self.assertEqual(paths, sorted([
            "game_definition.scene_registry", "game_definition.scene_registry.scenes",
            "game_definition.character_registry", "game_definition.character_registry.characters",
            "game_definition.gameplay_system_registry", "game_definition.gameplay_system_registry.gameplay_system_ids",
            "game_definition.asset_registry", "game_definition.asset_registry.assets",
            "game_definition.composition_registry", "game_definition.composition_registry.compositions",
            "game_definition.bundle_registry", "game_definition.bundle_registry.bundles"]))
        for n in ast.walk(func):
            if isinstance(n, ast.Attribute):
                self.assertFalse(n.attr.startswith("_"), n.attr)

    def test_29_no_scanning_validation_sorting_or_lookup(self):
        tree = self.tree()
        func = [n for n in tree.body if isinstance(n, ast.FunctionDef)][0]
        nodes = list(ast.walk(func))
        self.assertFalse([n for n in nodes if isinstance(n, (ast.For, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.Try))])
        calls = sorted(ast.unparse(n.func) for n in nodes if isinstance(n, ast.Call))
        self.assertEqual(calls, ["GameDefinitionCountsResult"] * 2 + ["len"] * 6 + ["type"])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("build_game_definition_summary", "game_definition_summary", "GameDefinitionSummaryResult", "lookup_game_scene", "lookup_game_scene_bundle",
                          "has_game_scene", "has_game_scene_bundle", "project", "GameProjectValidator", "GameSceneCompositionValidator", "validate_game_project", "validate_game_scene_composition",
                          "create_game_definition", "lookup", "scene_ids", "character_ids", "asset_ids", "to_dict_registry", "sorted", "sort", "scene_id",
                          "GameSceneRegistry", "GameSceneBundleRegistry", "GameSceneCompositionRegistry", "GameCharacterRegistry",
                          "GameAssetRegistry", "GameplaySystemRegistry", "Core", "Planner", "AgentLoop", "process_input"):
            self.assertNotIn(forbidden, names, forbidden)

    def test_30_no_private_access_on_foreign_objects(self):
        for n in ast.walk(self.tree()):
            if isinstance(n, ast.Attribute) and n.attr.startswith("_") and not n.attr.startswith("__"):
                self.assertIsInstance(n.value, ast.Name)
                self.assertIn(n.value.id, ("self", "other"), ast.unparse(n))

    def test_31_no_io_or_module_state(self):
        tree = self.tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "sorted", "copy.copy", "copy.deepcopy"):
            self.assertNotIn(forbidden, calls)
        for name, value in vars(sm).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_32a_independent_of_the_summary_and_query_layers(self):
        from game_creation import game_definition_queries as queries
        from game_creation import game_definition_query_helpers as helpers
        from game_creation import game_definition_summary as summary
        d = make_definition()
        with mock.patch.object(summary, "build_game_definition_summary", side_effect=AssertionError("summary used")), \
             mock.patch.object(queries, "lookup_game_scene", side_effect=AssertionError("query used")), \
             mock.patch.object(queries, "lookup_game_scene_bundle", side_effect=AssertionError("query used")), \
             mock.patch.object(helpers, "has_game_scene", side_effect=AssertionError("helper used")):
            self.assertTrue(get_game_definition_counts(d).ok)
        self.assertFalse(hasattr(sm, "build_game_definition_summary"))

    def test_32_stable_code(self):
        self.assertEqual(sm.FAILURE_INVALID_GAME_DEFINITION, INVALID)


class TestScopeAndDocumentation(unittest.TestCase):
    def test_33_earlier_modules_are_untouched_and_unaware_of_the_counts(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py", "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py",
            "game_definition_from_request.py", "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py",
            "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py",
            "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py",
            "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])
        for rel in sorted(os.listdir(os.path.join(PY_ROOT, "game_creation"))):
            if rel in ("game_definition_counts.py", "__init__.py"):
                continue
            with open(os.path.join(PY_ROOT, "game_creation", rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_definition_counts", "get_game_definition_counts", "GameDefinitionCountsResult"):
                self.assertNotIn(token, text, (rel, token))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "game_definition_counts", "get_game_definition_counts"):
                self.assertNotIn(token, text, (rel, token))

    def test_34_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("get_game_definition_counts", "GameDefinitionCountsResult", "GAME_DEFINITION_COUNTS_INVALID_GAME_DEFINITION",
                       "scene_count", "character_count", "gameplay_system_count", "asset_count", "composition_count", "bundle_count", "independent",
                       "does NOT", "Prompt 734", "Prompt 739"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
