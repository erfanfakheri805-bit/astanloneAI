"""Prompt 777 - Section 9 web request plan (`web.web_request_plan`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from web import web_request_plan as wp
from web.web_request import WebRequest, create_web_request
from web.web_request_plan import WebRequestPlan, WebRequestPlanResult, create_web_request_plan
from web.web_request_validator import WebRequestValidationResult, validate_web_request
from web.web_resource import WebResource, create_web_resource
from web.web_resource_registry import WebResourceRegistry, create_web_resource_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_request_plan_prompt777.md")
MODULE = os.path.join(PY_ROOT, "web", "web_request_plan.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "WEB_REQUEST_PLAN_"
FIELDS = ("request_id", "url", "method", "resource_type", "timeout_ms")
DEFAULT = {"request_id": "req_1", "url": "https://example.org/x", "method": "GET", "resource_type": "page", "timeout_ms": 5000}


def make_resource(rid="page"):
    r = create_web_resource({"resource_id": rid, "url": "https://example.org/" + rid, "title": "T " + rid, "resource_type": "page"})
    assert r.ok, r.failures
    return r.resource


def make_registry(*ids):
    r = create_web_resource_registry([make_resource(i) for i in ids])
    assert r.ok, r.failures
    return r.registry


def make_request(**over):
    data = dict(DEFAULT)
    data.update(over)
    r = create_web_request(data)
    assert r.ok, r.failures
    return r.request


def validated(**over):
    """(validation_result, request, registry) for a registered resource type."""
    req = make_request(**over)
    reg = make_registry(*dict.fromkeys((req.resource_type, "other")))
    res = validate_web_request(req, reg)
    assert res.ok, res.codes()
    return res, req, reg


class TestSuccess(unittest.TestCase):
    def test_1_valid_validation_result_produces_the_exact_expected_plan(self):
        vr, _req, _reg = validated()
        res = create_web_request_plan(vr)
        self.assertIs(type(res), WebRequestPlanResult)
        self.assertTrue(res.ok)
        self.assertIs(type(res.plan), WebRequestPlan)
        self.assertEqual(res.codes(), [])
        self.assertEqual(res.failures, ())
        self.assertEqual(res.plan.to_dict(), DEFAULT)
        self.assertEqual(res.to_dict(), {"ok": True, "plan": DEFAULT, "failures": []})

    def test_2_all_five_values_preserved_exactly(self):
        values = {"request_id": "R-9", "url": "https://a.example/p?q=1#f", "method": "POST", "resource_type": "api", "timeout_ms": 1}
        vr, _req, _reg = validated(**values)
        p = create_web_request_plan(vr).plan
        for name, value in values.items():
            self.assertEqual(getattr(p, name), value)
            self.assertIs(type(getattr(p, name)), type(value))

    def test_3_fields_are_exactly_the_five_in_fixed_order(self):
        p = create_web_request_plan(validated()[0]).plan
        self.assertEqual(wp.FIELDS, FIELDS)
        self.assertEqual(list(p.to_dict()), list(FIELDS))
        self.assertEqual(sorted(type(p).__slots__), sorted("_" + f for f in FIELDS))

    def test_4_no_normalization_trimming_casefolding_or_coercion(self):
        vr, _req, _reg = validated(request_id=" ID-1 ", url=" HTTP://Example.ORG/A b ", method=" get ", resource_type=" Page ")
        p = create_web_request_plan(vr).plan
        self.assertEqual((p.request_id, p.url, p.method, p.resource_type), (" ID-1 ", " HTTP://Example.ORG/A b ", " get ", " Page "))

    def test_5_exact_value_identity_preserved(self):
        rid, url, method, rtype = ("".join(["re", "q_", "id"]), "".join(["https://", "x.example/"]), "".join(["GE", "T"]), "".join(["pa", "ge"]))
        vr, req, _reg = validated(request_id=rid, url=url, method=method, resource_type=rtype)
        p = create_web_request_plan(vr).plan
        self.assertIs(p.request_id, rid)
        self.assertIs(p.url, url)
        self.assertIs(p.method, method)
        self.assertIs(p.resource_type, rtype)
        self.assertIs(p.timeout_ms, req.timeout_ms)
        self.assertIs(type(p.timeout_ms), int)
        self.assertIs(p.to_dict()["url"], url)

    def test_6_url_method_and_resource_type_stay_free_text(self):
        for over in ({"url": "not a url"}, {"url": "file:///x"}, {"method": "BREW"}, {"method": "get"}, {"resource_type": "Weird Type"}):
            with self.subTest(over=over):
                res = create_web_request_plan(validated(**over)[0])
                self.assertTrue(res.ok)
                for k, v in over.items():
                    self.assertEqual(getattr(res.plan, k), v)

    def test_7_values_are_not_compared_with_the_registered_resource(self):
        req = make_request(url="https://completely.different/")
        reg = create_web_resource_registry([create_web_resource(
            {"resource_id": "page", "url": "https://a.example/", "title": "Other", "resource_type": "image"}).resource]).registry
        res = create_web_request_plan(validate_web_request(req, reg))
        self.assertTrue(res.ok)
        self.assertEqual(res.plan.url, "https://completely.different/")
        self.assertEqual(res.plan.resource_type, "page")


class TestFailure(unittest.TestCase):
    def test_8_invalid_validation_result_type(self):
        vr, req, reg = validated()
        for bad in (None, {}, [], "ok", 5, True, object(), vr.to_dict(), req, reg, make_resource(), req.to_dict()):
            with self.subTest(bad=type(bad).__name__):
                res = create_web_request_plan(bad)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertEqual(res.codes(), [P + "INVALID_VALIDATION_RESULT"])
                self.assertEqual(res.failures[0]["field"], "validation_result")

    def test_9_look_alike_validation_result_is_rejected_and_never_read(self):
        class Fake:
            ok = True

            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        res = create_web_request_plan(Fake())
        self.assertEqual(res.codes(), [P + "INVALID_VALIDATION_RESULT"])
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestValidationResult,), {})

    def test_10_validation_result_with_ok_false(self):
        reg = make_registry("page")
        failed = (validate_web_request(make_request(resource_type="ghost"), reg), validate_web_request(None, reg),
                  validate_web_request(make_request(), None), validate_web_request(None, None))
        for vr in failed:
            with self.subTest(codes=vr.codes()):
                self.assertFalse(vr.ok)
                res = create_web_request_plan(vr)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertEqual(res.codes(), [P + "VALIDATION_FAILED"])
                self.assertEqual(res.failures[0]["field"], "validation_result")

    def test_11_no_plan_returned_on_failure(self):
        for vr in (validate_web_request(make_request(), make_registry()), None):
            res = create_web_request_plan(vr)
            self.assertIsNone(res.plan)
            self.assertFalse(res.ok)
            self.assertIsNone(res.to_dict()["plan"])
            self.assertFalse(res.to_dict()["ok"])

    def test_12_failed_validation_with_found_request_still_gives_no_plan(self):
        vr = validate_web_request(make_request(resource_type="ghost"), make_registry())
        self.assertIsNotNone(vr.request)
        self.assertIsNone(create_web_request_plan(vr).plan)

    def test_13_failure_messages_and_codes_are_stable(self):
        self.assertEqual(wp.FAILURE_CODES, (P + "INVALID_VALIDATION_RESULT", P + "VALIDATION_FAILED"))
        self.assertEqual(wp.FAILURE_INVALID_VALIDATION_RESULT, P + "INVALID_VALIDATION_RESULT")
        self.assertEqual(wp.FAILURE_VALIDATION_FAILED, P + "VALIDATION_FAILED")
        a = create_web_request_plan(validate_web_request(make_request(resource_type="ghost"), make_registry()))
        b = create_web_request_plan(validate_web_request(make_request(resource_type="ghost"), make_registry()))
        self.assertEqual(a, b)
        self.assertEqual(a.failures, b.failures)
        self.assertEqual(set(a.failures[0]), {"code", "field", "message"})
        self.assertIn("WEB_REQUEST_VALIDATION_RESOURCE_NOT_FOUND", a.failures[0]["message"])
        self.assertEqual(a.to_dict()["failures"], [dict(a.failures[0])])
        c = create_web_request_plan(None)
        self.assertEqual(c.failures[0]["message"], "validation_result must be exactly a WebRequestValidationResult.")


class TestNoRetentionAndNoMutation(unittest.TestCase):
    def test_14_request_registry_and_validation_result_are_not_retained(self):
        vr, req, reg = validated()
        res = create_web_request_plan(vr)
        forbidden = (req, reg, vr)
        for obj in (res, res.plan):
            for slot in type(obj).__slots__:
                value = getattr(obj, slot)
                for f in forbidden:
                    self.assertIsNot(value, f, slot)
        for value in res.plan.to_dict().values():
            self.assertIn(type(value), (str, int))
        for name in ("request", "registry", "resource", "validation_result"):
            self.assertFalse(hasattr(res.plan, name), name)
            self.assertFalse(hasattr(res, name), name)
        self.assertFalse(hasattr(res.plan, "__dict__"))
        self.assertFalse(hasattr(res, "__dict__"))

    def test_15_source_validation_result_remains_unchanged(self):
        vr, req, reg = validated()
        before = (vr.to_dict(), hash(vr), vr.request, vr.registry, vr.codes(), vr.failures, vr.ok)
        create_web_request_plan(vr)
        create_web_request_plan(vr)
        self.assertEqual(before, (vr.to_dict(), hash(vr), vr.request, vr.registry, vr.codes(), vr.failures, vr.ok))
        self.assertIs(vr.request, req)
        self.assertIs(vr.registry, reg)

    def test_16_request_and_registry_remain_unchanged(self):
        vr, req, reg = validated()
        snap = (req.to_dict(), hash(req), reg.to_dict(), hash(reg))
        create_web_request_plan(vr)
        self.assertEqual(snap, (req.to_dict(), hash(req), reg.to_dict(), hash(reg)))
        self.assertIs(type(req), WebRequest)
        self.assertIs(type(reg), WebResourceRegistry)

    def test_17_failed_source_validation_result_remains_unchanged(self):
        vr = validate_web_request(make_request(resource_type="ghost"), make_registry())
        before = (vr.to_dict(), hash(vr))
        create_web_request_plan(vr)
        self.assertEqual(before, (vr.to_dict(), hash(vr)))

    def test_18_registry_is_never_queried_by_the_planner(self):
        vr, _req, reg = validated()
        with mock.patch.object(WebResourceRegistry, "lookup", side_effect=AssertionError("lookup")):
            self.assertTrue(create_web_request_plan(vr).ok)
        self.assertIs(type(make_resource()), WebResource)


class TestPlanContract(unittest.TestCase):
    def setUp(self):
        self.vr = validated()[0]
        self.res = create_web_request_plan(self.vr)
        self.plan = self.res.plan
        self.bad = create_web_request_plan(None)

    def test_19_read_only_properties(self):
        for name in FIELDS:
            with self.assertRaises(AttributeError):
                setattr(self.plan, name, "x")
            with self.assertRaises(AttributeError):
                delattr(self.plan, name)
        for name in ("_url", "extra", "request"):
            with self.assertRaises(AttributeError):
                setattr(self.plan, name, "x")
            with self.assertRaises(AttributeError):
                delattr(self.plan, name)
        self.assertEqual(self.plan.to_dict(), DEFAULT)

    def test_20_direct_construction_refused(self):
        with self.assertRaises(TypeError):
            WebRequestPlan(None, "a", "b", "c", "d", 1)
        with self.assertRaises(TypeError):
            WebRequestPlan(object(), "a", "b", "c", "d", 1)
        with self.assertRaises(TypeError):
            WebRequestPlanResult(None, None, [])
        with self.assertRaises(TypeError):
            WebRequestPlanResult(object(), self.plan, [])

    def test_21_subclassing_refused(self):
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestPlan,), {})
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestPlanResult,), {})

    def test_22_result_is_immutable(self):
        for name in ("ok", "plan", "failures", "_plan", "extra"):
            with self.assertRaises(AttributeError):
                setattr(self.res, name, 1)
            with self.assertRaises(AttributeError):
                delattr(self.res, name)
        self.assertTrue(self.res.ok)
        self.assertIs(self.res.plan, self.plan)

    def test_23_fresh_to_dict(self):
        a, b = self.plan.to_dict(), self.plan.to_dict()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a["url"] = "mutated"
        a["extra"] = 1
        self.assertEqual(self.plan.to_dict(), DEFAULT)
        self.assertEqual(self.plan.url, DEFAULT["url"])
        r1, r2 = self.res.to_dict(), self.res.to_dict()
        self.assertEqual(r1, r2)
        self.assertIsNot(r1, r2)
        self.assertIsNot(r1["plan"], r2["plan"])
        self.assertIsNot(r1["failures"], r2["failures"])
        r1["plan"]["method"] = "X"
        r1["failures"].append(1)
        self.assertEqual(self.res.to_dict(), {"ok": True, "plan": DEFAULT, "failures": []})

    def test_24_failure_to_dict_and_failures_are_fresh(self):
        a, b = self.bad.to_dict(), self.bad.to_dict()
        self.assertEqual(a, b)
        self.assertIsNot(a["failures"], b["failures"])
        self.assertIsNot(a["failures"][0], b["failures"][0])
        a["failures"][0]["code"] = "X"
        f1, f2 = self.bad.failures, self.bad.failures
        self.assertEqual(f1, f2)
        self.assertIsNot(f1[0], f2[0])
        self.assertIsInstance(f1, tuple)
        f1[0]["message"] = "mutated"
        self.assertEqual(self.bad.codes(), [P + "INVALID_VALIDATION_RESULT"])
        self.assertEqual(self.bad.failures[0]["code"], P + "INVALID_VALIDATION_RESULT")
        self.assertIsNone(self.bad.to_dict()["plan"])

    def test_25_equality_and_hash(self):
        again = create_web_request_plan(validated()[0])        # equal value, different objects
        self.assertIsNot(again.plan, self.plan)
        self.assertEqual(self.plan, again.plan)
        self.assertFalse(self.plan != again.plan)
        self.assertEqual(hash(self.plan), hash(again.plan))
        self.assertEqual(self.res, again)
        self.assertEqual(hash(self.res), hash(again))
        self.assertEqual(len({self.plan, again.plan}), 1)
        self.assertEqual(len({self.res, again}), 1)
        for field, value in (("request_id", "req_2"), ("url", "https://other/"), ("method", "POST"), ("resource_type", "other"), ("timeout_ms", 6000)):
            with self.subTest(field=field):
                other = create_web_request_plan(validated(**{field: value})[0]).plan
                self.assertNotEqual(self.plan, other)
        for other in (self.plan.to_dict(), None, 1, "x", make_request(), self.res):
            self.assertNotEqual(self.plan, other)
        self.assertEqual(self.plan.__eq__(self.plan.to_dict()), NotImplemented)
        self.assertEqual(self.res.__eq__(self.res.to_dict()), NotImplemented)
        self.assertNotEqual(self.res, self.bad)
        self.assertEqual(self.bad, create_web_request_plan(5))
        self.assertEqual(hash(self.bad), hash(create_web_request_plan(5)))
        self.assertNotEqual(self.bad, create_web_request_plan(validate_web_request(None, None)))

    def test_26_copy_and_deepcopy_return_same_object(self):
        for obj in (self.res, self.plan, self.bad):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)
            self.assertIs(copy.deepcopy({"k": [obj]})["k"][0], obj)

    def test_27_pickle_refused(self):
        for obj in (self.res, self.plan, self.bad):
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(obj=type(obj).__name__, proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(obj, protocol=proto)

    def test_28_repr_is_stable(self):
        self.assertEqual(repr(self.plan), "WebRequestPlan(request_id='req_1', url='https://example.org/x', method='GET', resource_type='page', timeout_ms=5000)")
        self.assertEqual(repr(self.res), "WebRequestPlanResult(ok=True, codes=[])")
        self.assertEqual(repr(self.bad), "WebRequestPlanResult(ok=False, codes=['%sINVALID_VALIDATION_RESULT'])" % P)

    def test_29_plan_has_no_execution_surface(self):
        self.assertEqual({n for n in dir(self.plan) if not n.startswith("_")}, set(FIELDS) | {"to_dict"})
        self.assertEqual({n for n in dir(self.res) if not n.startswith("_")}, {"ok", "plan", "failures", "codes", "to_dict"})

    def test_30_hashable_for_every_outcome(self):
        outcomes = [self.res, self.bad, create_web_request_plan(validate_web_request(None, None)),
                    create_web_request_plan(validate_web_request(make_request(resource_type="ghost"), make_registry()))]
        self.assertEqual(len({hash(o) for o in outcomes}), len(outcomes))
        self.assertEqual(len(set(outcomes)), len(outcomes))


class TestDeterminismAndSideEffects(unittest.TestCase):
    def test_31_repeated_calls_are_deterministic(self):
        vr = validated()[0]
        results = [create_web_request_plan(vr) for _ in range(5)]
        for r in results[1:]:
            self.assertEqual(r, results[0])
            self.assertEqual(hash(r), hash(results[0]))
            self.assertEqual(r.to_dict(), results[0].to_dict())
        fails = [create_web_request_plan(validate_web_request(None, None)) for _ in range(3)]
        self.assertEqual(len(set(fails)), 1)
        self.assertEqual(fails[0].codes(), [P + "VALIDATION_FAILED"])

    def test_32_never_raises_for_odd_inputs(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")

            def __getattr__(self, name):
                raise RuntimeError("boom")

        for bad in (None, Boom(), float("nan"), b"x", (), {1: 2}, lambda: 1, type, WebRequestValidationResult, 10 ** 100):
            self.assertEqual(create_web_request_plan(bad).codes(), [P + "INVALID_VALIDATION_RESULT"])

    def test_33_no_side_effects_filesystem_environment_or_modules(self):
        vr = validated()[0]
        bad_vr = validate_web_request(None, None)
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            create_web_request_plan(vr)
            create_web_request_plan(bad_vr)
            create_web_request_plan(None)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_34_no_network_file_or_subprocess_access_is_attempted(self):
        import builtins
        import socket
        import subprocess
        vr = validated()[0]
        bad_vr = validate_web_request(None, None)
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network")), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess")), \
                mock.patch.object(builtins, "open", side_effect=AssertionError("file")):
            self.assertTrue(create_web_request_plan(vr).ok)
            self.assertFalse(create_web_request_plan(bad_vr).ok)
            self.assertFalse(create_web_request_plan(None).ok)


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_35_module_imports_only_the_validator_result_type(self):
        tree = self._tree()
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [("web_request_validator", 1, ["WebRequestValidationResult"])])

    def test_36_module_is_pure_and_has_no_module_state(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "ssl", "sqlite3", "random", "time",
                     "datetime", "anthropic", "openai", "game_creation", "multimedia", "core", "agent", "planning",
                     "WebRequest", "WebResource", "WebResourceRegistry", "lookup", "registry", "resource", "resources"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(wp).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_37_earlier_web_modules_are_unaware_of_the_plan(self):
        for name in ("web_resource.py", "web_resource_registry.py", "web_request.py", "web_request_validator.py"):
            with open(os.path.join(PY_ROOT, "web", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("web_request_plan", "WebRequestPlan", "create_web_request_plan"):
                self.assertNotIn(token, text, (name, token))

    def test_38_no_production_module_outside_web_references_it(self):
        tokens = ("web_request_plan", "WebRequestPlan", "create_web_request_plan")
        skip = {"web", "tests", "__pycache__", "data"}
        checked = 0
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in skip) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    for token in tokens:
                        self.assertNotIn(token, text, os.path.join(folder, name))
                    checked += 1
        self.assertGreater(checked, 100)

    def test_39_web_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "web")) if f != "__pycache__"),
                         ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py", "web_request_executor.py", "web_request_metadata_executor.py", "web_request_output.py", "web_request_output_validator.py", "web_request_pipeline.py", "web_request_plan.py", "web_request_validator.py", "web_resource.py", "web_resource_registry.py"])
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_40_end_to_end_through_public_apis_only(self):
        reg = make_registry("page", "api")
        req = make_request(request_id="e2e", url="https://svc.example/v1", method="POST", resource_type="api", timeout_ms=250)
        plan = create_web_request_plan(validate_web_request(req, reg)).plan
        self.assertEqual(plan.to_dict(), req.to_dict())
        self.assertIs(type(plan), WebRequestPlan)
        self.assertNotEqual(plan, req)

    def test_41_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("WebRequestPlan", "WebRequestPlanResult", "create_web_request_plan", "WEB_REQUEST_PLAN_", "INVALID_VALIDATION_RESULT",
                       "VALIDATION_FAILED", "does NOT", "Prompt 778", "execution description"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
