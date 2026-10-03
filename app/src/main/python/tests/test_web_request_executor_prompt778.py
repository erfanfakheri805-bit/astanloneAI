"""Prompt 778 - Section 9 web request executor (`web.web_request_executor`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from web import web_request_executor as we
from web.web_request import create_web_request
from web.web_request_executor import WebRequestExecutionResult, execute_web_request_plan
from web.web_request_plan import WebRequestPlan, create_web_request_plan
from web.web_request_validator import validate_web_request
from web.web_resource import create_web_resource
from web.web_resource_registry import create_web_resource_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_request_executor_prompt778.md")
MODULE = os.path.join(PY_ROOT, "web", "web_request_executor.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "WEB_REQUEST_EXECUTOR_"
INVALID, NOT_IMPL = P + "INVALID_PLAN", P + "NOT_IMPLEMENTED"
FIELDS = ("request_id", "url", "method", "resource_type", "timeout_ms")
DEFAULT = {"request_id": "req_1", "url": "https://example.org/x", "method": "GET", "resource_type": "page", "timeout_ms": 5000}


def make_plan(**over):
    data = dict(DEFAULT)
    data.update(over)
    req = create_web_request(data)
    assert req.ok, req.failures
    res = create_web_resource({"resource_id": data["resource_type"], "url": "https://example.org/r", "title": "T", "resource_type": "page"})
    assert res.ok, res.failures
    reg = create_web_resource_registry([res.resource])
    assert reg.ok, reg.failures
    plan = create_web_request_plan(validate_web_request(req.request, reg.registry))
    assert plan.ok, plan.codes()
    return plan.plan


class TestValidPlan(unittest.TestCase):
    def test_1_valid_plan_gives_not_implemented(self):
        res = execute_web_request_plan(make_plan())
        self.assertIs(type(res), WebRequestExecutionResult)
        self.assertEqual(res.status, "NOT_IMPLEMENTED")
        self.assertEqual(res.code, NOT_IMPL)
        self.assertFalse(res.ok)
        self.assertFalse(res.executed)

    def test_2_exact_five_values_preserved(self):
        values = {"request_id": "R-9", "url": "https://a.example/p?q=1#f", "method": "POST", "resource_type": "api", "timeout_ms": 1}
        res = execute_web_request_plan(make_plan(**values))
        self.assertEqual(res.metadata, values)
        self.assertEqual(list(res.metadata), list(FIELDS))
        for k, v in values.items():
            self.assertIs(type(res.metadata[k]), type(v))

    def test_3_no_normalization_and_identity_preserved(self):
        rid, url, method, rtype = ("".join(["re", "q_", "id"]), " HTTP://Example.ORG/A b ", " get ", " Page ")
        plan = make_plan(request_id=rid, url=url, method=method, resource_type=rtype)
        md = execute_web_request_plan(plan).metadata
        self.assertIs(md["request_id"], plan.request_id)
        self.assertIs(md["url"], plan.url)
        self.assertIs(md["method"], plan.method)
        self.assertIs(md["resource_type"], plan.resource_type)
        self.assertIs(md["timeout_ms"], plan.timeout_ms)
        self.assertEqual((md["url"], md["method"], md["resource_type"]), (url, method, rtype))

    def test_4_to_dict_shape(self):
        d = execute_web_request_plan(make_plan()).to_dict()
        self.assertEqual(d, {"ok": False, "status": "NOT_IMPLEMENTED", "code": NOT_IMPL, "executed": False, "metadata": DEFAULT})
        self.assertEqual(list(d), ["ok", "status", "code", "executed", "metadata"])

    def test_5_url_method_are_free_text_and_not_interpreted(self):
        for over in ({"url": "not a url"}, {"url": "file:///x"}, {"method": "BREW"}, {"timeout_ms": 1}):
            with self.subTest(over=over):
                res = execute_web_request_plan(make_plan(**over))
                self.assertEqual(res.code, NOT_IMPL)
                for k, v in over.items():
                    self.assertEqual(res.metadata[k], v)

    def test_6_plan_is_not_retained(self):
        plan = make_plan()
        res = execute_web_request_plan(plan)
        for slot in type(res).__slots__:
            self.assertIsNot(getattr(res, slot), plan, slot)
        self.assertEqual(sorted(type(res).__slots__), sorted(["_status", "_code"] + ["_" + f for f in FIELDS]))
        for name in ("plan", "request", "registry", "validation_result"):
            self.assertFalse(hasattr(res, name), name)
        self.assertFalse(hasattr(res, "__dict__"))
        for v in res.metadata.values():
            self.assertIn(type(v), (str, int))

    def test_7_plan_is_unchanged(self):
        plan = make_plan()
        before = (plan.to_dict(), hash(plan), repr(plan))
        execute_web_request_plan(plan)
        execute_web_request_plan(plan)
        self.assertEqual(before, (plan.to_dict(), hash(plan), repr(plan)))


class TestInvalidInput(unittest.TestCase):
    def test_8_invalid_inputs_are_rejected(self):
        plan = make_plan()
        for bad in (None, {}, [], "plan", 5, True, object(), plan.to_dict(), WebRequestPlan, create_web_request_plan(None),
                    create_web_request(DEFAULT).request, (plan,)):
            with self.subTest(bad=type(bad).__name__):
                res = execute_web_request_plan(bad)
                self.assertEqual(res.status, "REJECTED")
                self.assertEqual(res.code, INVALID)
                self.assertFalse(res.ok)
                self.assertFalse(res.executed)
                self.assertIsNone(res.metadata)
                self.assertEqual(res.to_dict(), {"ok": False, "status": "REJECTED", "code": INVALID, "executed": False, "metadata": None})

    def test_9_look_alike_is_rejected_and_never_read(self):
        class Fake:
            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        self.assertEqual(execute_web_request_plan(Fake()).code, INVALID)
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestPlan,), {})

    def test_10_never_raises_for_odd_inputs(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")

            def __getattr__(self, name):
                raise RuntimeError("boom")

        for bad in (Boom(), float("nan"), b"x", {1: 2}, lambda: 1, type, 10 ** 100):
            self.assertEqual(execute_web_request_plan(bad).code, INVALID)

    def test_11_constants_are_stable(self):
        self.assertEqual(we.CODES, (INVALID, NOT_IMPL))
        self.assertEqual(we.STATUSES, ("REJECTED", "NOT_IMPLEMENTED"))
        self.assertEqual(we.FIELDS, FIELDS)
        self.assertEqual(INVALID, "WEB_REQUEST_EXECUTOR_INVALID_PLAN")
        self.assertEqual(NOT_IMPL, "WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED")


class TestResultContract(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan()
        self.res = execute_web_request_plan(self.plan)
        self.bad = execute_web_request_plan(None)

    def test_12_immutable(self):
        for obj in (self.res, self.bad):
            for name in ("ok", "status", "code", "metadata", "executed", "_status", "_url", "extra", "plan"):
                with self.assertRaises(AttributeError):
                    setattr(obj, name, "x")
                with self.assertRaises(AttributeError):
                    delattr(obj, name)
        self.assertEqual(self.res.to_dict()["metadata"], DEFAULT)

    def test_13_direct_construction_refused(self):
        with self.assertRaises(TypeError):
            WebRequestExecutionResult(None, "NOT_IMPLEMENTED", NOT_IMPL, "a", "b", "c", "d", 1)
        with self.assertRaises(TypeError):
            WebRequestExecutionResult(object(), "REJECTED", INVALID, None, None, None, None, None)

    def test_14_subclassing_refused(self):
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestExecutionResult,), {})

    def test_15_fresh_to_dict_and_metadata(self):
        a, b = self.res.to_dict(), self.res.to_dict()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["metadata"], b["metadata"])
        a["metadata"]["url"] = "mutated"
        a["status"] = "X"
        a["extra"] = 1
        m1, m2 = self.res.metadata, self.res.metadata
        self.assertIsNot(m1, m2)
        m1["method"] = "X"
        self.assertEqual(self.res.to_dict(), {"ok": False, "status": "NOT_IMPLEMENTED", "code": NOT_IMPL, "executed": False, "metadata": DEFAULT})
        self.assertEqual(self.res.metadata, DEFAULT)
        r1, r2 = self.bad.to_dict(), self.bad.to_dict()
        self.assertEqual(r1, r2)
        self.assertIsNot(r1, r2)

    def test_16_equality_and_hash(self):
        again = execute_web_request_plan(make_plan())       # equal value, different objects
        self.assertEqual(self.res, again)
        self.assertFalse(self.res != again)
        self.assertEqual(hash(self.res), hash(again))
        self.assertEqual(len({self.res, again}), 1)
        self.assertEqual(self.bad, execute_web_request_plan(5))
        self.assertEqual(hash(self.bad), hash(execute_web_request_plan(5)))
        self.assertNotEqual(self.res, self.bad)
        for field, value in (("request_id", "req_2"), ("url", "https://other/"), ("method", "POST"), ("resource_type", "other"), ("timeout_ms", 6000)):
            with self.subTest(field=field):
                self.assertNotEqual(self.res, execute_web_request_plan(make_plan(**{field: value})))
        for other in (self.res.to_dict(), None, 1, "x", self.plan):
            self.assertNotEqual(self.res, other)
        self.assertEqual(self.res.__eq__(self.res.to_dict()), NotImplemented)
        self.assertEqual(len({self.res, self.bad, again}), 2)

    def test_17_copy_and_deepcopy_preserve_equality(self):
        for obj in (self.res, self.bad):
            for c in (copy.copy(obj), copy.deepcopy(obj), copy.deepcopy({"k": [obj]})["k"][0]):
                self.assertEqual(c, obj)
                self.assertEqual(hash(c), hash(obj))
                self.assertIs(c, obj)
                self.assertEqual(c.to_dict(), obj.to_dict())

    def test_18_pickle_refused(self):
        for obj in (self.res, self.bad):
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(obj=obj.status, proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(obj, protocol=proto)

    def test_19_repr_is_stable(self):
        self.assertEqual(repr(self.res), "WebRequestExecutionResult(status='NOT_IMPLEMENTED', code='%s')" % NOT_IMPL)
        self.assertEqual(repr(self.bad), "WebRequestExecutionResult(status='REJECTED', code='%s')" % INVALID)

    def test_20_public_surface_is_exact(self):
        for obj in (self.res, self.bad):
            self.assertEqual({n for n in dir(obj) if not n.startswith("_")}, {"ok", "status", "code", "executed", "metadata", "to_dict"})


class TestDeterminismAndSideEffects(unittest.TestCase):
    def test_21_repeated_execution_is_deterministic(self):
        plan = make_plan()
        results = [execute_web_request_plan(plan) for _ in range(5)]
        for r in results[1:]:
            self.assertEqual(r, results[0])
            self.assertEqual(hash(r), hash(results[0]))
            self.assertEqual(r.to_dict(), results[0].to_dict())
        self.assertEqual(len({execute_web_request_plan(None) for _ in range(3)}), 1)
        self.assertEqual(execute_web_request_plan(make_plan()), execute_web_request_plan(make_plan()))

    def test_22_no_side_effects_filesystem_environment_or_modules(self):
        plan = make_plan()
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            execute_web_request_plan(plan)
            execute_web_request_plan(None)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_23_no_network_filesystem_subprocess_or_persistence_calls(self):
        import builtins
        import io
        import os as _os
        import shutil
        import socket
        import sqlite3
        import subprocess
        import urllib.request
        plan = make_plan()
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom), mock.patch.object(urllib.request, "urlopen", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(_os, "system", boom), mock.patch.object(_os, "popen", boom), \
                mock.patch.object(builtins, "open", boom), mock.patch.object(io, "open", boom), \
                mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(_os, "remove", boom), mock.patch.object(_os, "mkdir", boom), \
                mock.patch.object(shutil, "copy", boom), mock.patch.object(sqlite3, "connect", boom):
            self.assertEqual(execute_web_request_plan(plan).code, NOT_IMPL)
            self.assertEqual(execute_web_request_plan(None).code, INVALID)

    def test_24_no_real_network_module_is_loaded_by_the_executor(self):
        for name in ("socket", "http.client", "urllib.request", "requests", "ssl"):
            self.assertNotIn(name, vars(we))


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_25_module_imports_only_the_plan_type(self):
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [("web_request_plan", 1, ["WebRequestPlan"])])

    def test_26_module_is_pure_and_has_no_module_state(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "ssl", "sqlite3", "shutil", "random", "time",
                     "datetime", "anthropic", "openai", "multimedia", "game_creation", "core", "agent", "planning", "WebRequest", "WebResource",
                     "WebResourceRegistry", "WebRequestValidationResult", "lookup", "registry"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(we).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_27_earlier_web_modules_are_unaware_of_the_executor(self):
        for name in ("web_resource.py", "web_resource_registry.py", "web_request.py", "web_request_validator.py", "web_request_plan.py"):
            with open(os.path.join(PY_ROOT, "web", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("web_request_executor", "WebRequestExecutionResult", "execute_web_request_plan"):
                self.assertNotIn(token, text, (name, token))

    def test_28_no_production_module_outside_web_references_it(self):
        tokens = ("web_request_executor", "WebRequestExecutionResult", "execute_web_request_plan")
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

    def test_29_web_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "web")) if f != "__pycache__"),
                         ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py", "web_request_executor.py", "web_request_metadata_executor.py", "web_request_output.py", "web_request_output_validator.py", "web_request_pipeline.py", "web_request_plan.py", "web_request_validator.py",
                          "web_resource.py", "web_resource_registry.py"])
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_30_end_to_end_through_public_apis_only(self):
        plan = make_plan(request_id="e2e", url="https://svc.example/v1", method="POST", resource_type="api", timeout_ms=250)
        res = execute_web_request_plan(plan)
        self.assertEqual(res.metadata, plan.to_dict())
        self.assertEqual(res.code, NOT_IMPL)

    def test_31_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("WebRequestExecutionResult", "execute_web_request_plan", "WEB_REQUEST_EXECUTOR_", "INVALID_PLAN", "NOT_IMPLEMENTED",
                       "REJECTED", "does NOT", "Prompt 779"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
