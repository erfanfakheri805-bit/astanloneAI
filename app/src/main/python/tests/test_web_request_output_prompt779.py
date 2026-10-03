"""Prompt 779 - Section 9 web request output (`web.web_request_output`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from web import web_request_output as wo
from web.web_request import create_web_request
from web.web_request_executor import WebRequestExecutionResult, execute_web_request_plan
from web.web_request_output import WebRequestOutput, create_web_request_output
from web.web_request_plan import create_web_request_plan
from web.web_request_validator import validate_web_request
from web.web_resource import create_web_resource
from web.web_resource_registry import create_web_resource_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_request_output_prompt779.md")
MODULE = os.path.join(PY_ROOT, "web", "web_request_output.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
INVALID = "WEB_REQUEST_OUTPUT_INVALID_EXECUTION_RESULT"
NOT_IMPL = "WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED"
EXEC_INVALID = "WEB_REQUEST_EXECUTOR_INVALID_PLAN"
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


def make_exec(**over):
    return execute_web_request_plan(make_plan(**over))


def rejected_exec():
    return execute_web_request_plan(None)


class TestValidExecutionResults(unittest.TestCase):
    def test_1_not_implemented_result(self):
        out = create_web_request_output(make_exec())
        self.assertIs(type(out), WebRequestOutput)
        self.assertEqual(out.status, "NOT_IMPLEMENTED")
        self.assertEqual(out.code, NOT_IMPL)
        self.assertEqual(out.metadata, DEFAULT)
        self.assertEqual(out.to_dict(), {"status": "NOT_IMPLEMENTED", "code": NOT_IMPL, "metadata": DEFAULT})
        self.assertEqual(list(out.to_dict()), ["status", "code", "metadata"])

    def test_2_rejected_result(self):
        out = create_web_request_output(rejected_exec())
        self.assertIs(type(out), WebRequestOutput)
        self.assertEqual(out.status, "REJECTED")
        self.assertEqual(out.code, EXEC_INVALID)
        self.assertIsNone(out.metadata)
        self.assertEqual(out.to_dict(), {"status": "REJECTED", "code": EXEC_INVALID, "metadata": None})

    def test_3_exact_status_code_metadata_preservation(self):
        values = {"request_id": "R-9", "url": "https://a.example/p?q=1#f", "method": "POST", "resource_type": "api", "timeout_ms": 1}
        ex = make_exec(**values)
        out = create_web_request_output(ex)
        self.assertEqual(out.status, ex.status)
        self.assertEqual(out.code, ex.code)
        self.assertEqual(out.metadata, ex.metadata)
        self.assertEqual(out.metadata, values)
        self.assertEqual(list(out.metadata), list(FIELDS))
        for k, v in values.items():
            self.assertIs(type(out.metadata[k]), type(v))
        for k in FIELDS:
            self.assertEqual(out.metadata[k], ex.metadata[k])

    def test_4_values_are_not_normalized_and_identity_is_preserved(self):
        plan = make_plan(url=" HTTP://Example.ORG/A b ", method=" get ", resource_type=" Page ")
        ex = execute_web_request_plan(plan)
        out = create_web_request_output(ex)
        for k in FIELDS:
            self.assertIs(out.metadata[k], getattr(plan, k), k)
        self.assertIs(out.status, ex.status)
        self.assertIs(out.code, ex.code)
        self.assertEqual((out.metadata["url"], out.metadata["method"], out.metadata["resource_type"]), (" HTTP://Example.ORG/A b ", " get ", " Page "))

    def test_5_metadata_none_is_preserved(self):
        ex = rejected_exec()
        self.assertIsNone(ex.metadata)
        out = create_web_request_output(ex)
        self.assertIsNone(out.metadata)
        self.assertIsNone(out.to_dict()["metadata"])
        self.assertIsNot(out.metadata, {})

    def test_6_execution_result_is_not_retained(self):
        for ex in (make_exec(), rejected_exec()):
            out = create_web_request_output(ex)
            self.assertEqual(sorted(type(out).__slots__), ["_code", "_items", "_status"])
            for slot in type(out).__slots__:
                self.assertIsNot(getattr(out, slot), ex, slot)
            for name in ("execution_result", "result", "plan", "request"):
                self.assertFalse(hasattr(out, name), name)
            self.assertFalse(hasattr(out, "__dict__"))
            if out.metadata is not None:
                for v in out.metadata.values():
                    self.assertIn(type(v), (str, int))

    def test_7_execution_result_is_unchanged(self):
        ex = make_exec()
        before = (ex.to_dict(), hash(ex), repr(ex))
        create_web_request_output(ex)
        create_web_request_output(ex)
        self.assertEqual(before, (ex.to_dict(), hash(ex), repr(ex)))


class TestInvalidInput(unittest.TestCase):
    def test_8_invalid_inputs_are_rejected(self):
        plan, ex = make_plan(), make_exec()
        for bad in (None, {}, [], "result", 5, True, object(), ex.to_dict(), WebRequestExecutionResult, plan, (ex,), create_web_request_output(ex)):
            with self.subTest(bad=type(bad).__name__):
                out = create_web_request_output(bad)
                self.assertIs(type(out), WebRequestOutput)
                self.assertEqual(out.status, "REJECTED")
                self.assertEqual(out.code, INVALID)
                self.assertIsNone(out.metadata)
                self.assertEqual(out.to_dict(), {"status": "REJECTED", "code": INVALID, "metadata": None})

    def test_9_look_alike_is_rejected_and_never_read(self):
        class Fake:
            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        self.assertEqual(create_web_request_output(Fake()).code, INVALID)
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestExecutionResult,), {})

    def test_10_never_raises_for_odd_inputs(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")

            def __getattr__(self, name):
                raise RuntimeError("boom")

        for bad in (Boom(), float("nan"), b"x", {1: 2}, lambda: 1, type, 10 ** 100):
            self.assertEqual(create_web_request_output(bad).code, INVALID)

    def test_11_invalid_input_output_differs_from_a_valid_rejected_result_output(self):
        self.assertNotEqual(create_web_request_output(None), create_web_request_output(rejected_exec()))
        self.assertEqual(create_web_request_output(None).code, INVALID)
        self.assertEqual(create_web_request_output(rejected_exec()).code, EXEC_INVALID)

    def test_12_constants_are_stable(self):
        self.assertEqual(wo.CODES, (INVALID,))
        self.assertEqual(wo.CODE_INVALID_EXECUTION_RESULT, "WEB_REQUEST_OUTPUT_INVALID_EXECUTION_RESULT")
        self.assertEqual(wo.STATUS_REJECTED, "REJECTED")


class TestOutputContract(unittest.TestCase):
    def setUp(self):
        self.ex = make_exec()
        self.out = create_web_request_output(self.ex)
        self.rej = create_web_request_output(rejected_exec())
        self.bad = create_web_request_output(None)

    def test_13_immutable(self):
        for obj in (self.out, self.rej, self.bad):
            for name in ("status", "code", "metadata", "_status", "_code", "_items", "extra", "execution_result"):
                with self.assertRaises(AttributeError):
                    setattr(obj, name, "x")
                with self.assertRaises(AttributeError):
                    delattr(obj, name)
        self.assertEqual(self.out.to_dict()["metadata"], DEFAULT)

    def test_14_direct_construction_refused(self):
        with self.assertRaises(TypeError):
            WebRequestOutput(None, "NOT_IMPLEMENTED", NOT_IMPL, None)
        with self.assertRaises(TypeError):
            WebRequestOutput(object(), "REJECTED", INVALID, None)

    def test_15_subclassing_refused(self):
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestOutput,), {})

    def test_16_fresh_to_dict_and_metadata(self):
        a, b = self.out.to_dict(), self.out.to_dict()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["metadata"], b["metadata"])
        a["metadata"]["url"] = "mutated"
        a["status"] = "X"
        a["extra"] = 1
        m1, m2 = self.out.metadata, self.out.metadata
        self.assertEqual(m1, m2)
        self.assertIsNot(m1, m2)
        m1["method"] = "X"
        m1["new"] = 1
        self.assertEqual(self.out.to_dict(), {"status": "NOT_IMPLEMENTED", "code": NOT_IMPL, "metadata": DEFAULT})
        self.assertEqual(self.out.metadata, DEFAULT)
        for obj in (self.rej, self.bad):
            r1, r2 = obj.to_dict(), obj.to_dict()
            self.assertEqual(r1, r2)
            self.assertIsNot(r1, r2)

    def test_17_equality_and_hash(self):
        again = create_web_request_output(make_exec())      # equal value, different objects
        self.assertIsNot(self.out, again)
        self.assertEqual(self.out, again)
        self.assertFalse(self.out != again)
        self.assertEqual(hash(self.out), hash(again))
        self.assertEqual(len({self.out, again}), 1)
        self.assertEqual(self.bad, create_web_request_output(5))
        self.assertEqual(hash(self.bad), hash(create_web_request_output(5)))
        self.assertNotEqual(self.out, self.rej)
        self.assertNotEqual(self.rej, self.bad)
        for field, value in (("request_id", "req_2"), ("url", "https://other/"), ("method", "POST"), ("resource_type", "other"), ("timeout_ms", 6000)):
            with self.subTest(field=field):
                self.assertNotEqual(self.out, create_web_request_output(make_exec(**{field: value})))
        for other in (self.out.to_dict(), None, 1, "x", self.ex):
            self.assertNotEqual(self.out, other)
        self.assertEqual(self.out.__eq__(self.out.to_dict()), NotImplemented)
        self.assertEqual(len({self.out, self.rej, self.bad, again}), 3)

    def test_18_copy_and_deepcopy_preserve_equality(self):
        for obj in (self.out, self.rej, self.bad):
            for c in (copy.copy(obj), copy.deepcopy(obj), copy.deepcopy({"k": [obj]})["k"][0]):
                self.assertEqual(c, obj)
                self.assertEqual(hash(c), hash(obj))
                self.assertEqual(c.to_dict(), obj.to_dict())
                self.assertEqual(c.metadata, obj.metadata)

    def test_19_pickle_refused(self):
        for obj in (self.out, self.rej, self.bad):
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(obj=obj.code, proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(obj, protocol=proto)

    def test_20_repr_is_stable(self):
        self.assertEqual(repr(self.out), "WebRequestOutput(status='NOT_IMPLEMENTED', code='%s')" % NOT_IMPL)
        self.assertEqual(repr(self.bad), "WebRequestOutput(status='REJECTED', code='%s')" % INVALID)

    def test_21_public_surface_is_exact(self):
        for obj in (self.out, self.rej, self.bad):
            self.assertEqual({n for n in dir(obj) if not n.startswith("_")}, {"status", "code", "metadata", "to_dict"})


class TestDeterminismAndSideEffects(unittest.TestCase):
    def test_22_repeated_creation_is_deterministic(self):
        ex = make_exec()
        outs = [create_web_request_output(ex) for _ in range(5)]
        for o in outs[1:]:
            self.assertEqual(o, outs[0])
            self.assertEqual(hash(o), hash(outs[0]))
            self.assertEqual(o.to_dict(), outs[0].to_dict())
        self.assertEqual(len({create_web_request_output(None) for _ in range(3)}), 1)
        self.assertEqual(len({create_web_request_output(rejected_exec()) for _ in range(3)}), 1)
        self.assertEqual(create_web_request_output(make_exec()), create_web_request_output(make_exec()))

    def test_23_no_side_effects_filesystem_environment_or_modules(self):
        ex, rj = make_exec(), rejected_exec()
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            create_web_request_output(ex)
            create_web_request_output(rj)
            create_web_request_output(None)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_24_no_network_filesystem_subprocess_or_persistence_calls(self):
        import builtins
        import io
        import os as _os
        import shutil
        import socket
        import sqlite3
        import subprocess
        import urllib.request
        ex, rj = make_exec(), rejected_exec()
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom), mock.patch.object(urllib.request, "urlopen", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(_os, "system", boom), mock.patch.object(_os, "popen", boom), \
                mock.patch.object(builtins, "open", boom), mock.patch.object(io, "open", boom), \
                mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(_os, "remove", boom), mock.patch.object(_os, "mkdir", boom), \
                mock.patch.object(shutil, "copy", boom), mock.patch.object(sqlite3, "connect", boom):
            self.assertEqual(create_web_request_output(ex).code, NOT_IMPL)
            self.assertEqual(create_web_request_output(rj).code, EXEC_INVALID)
            self.assertEqual(create_web_request_output(None).code, INVALID)

    def test_25_no_real_network_module_is_loaded_by_the_output_module(self):
        for name in ("socket", "http.client", "urllib.request", "requests", "ssl"):
            self.assertNotIn(name, vars(wo))


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_26_module_imports_only_the_execution_result_type(self):
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [("web_request_executor", 1, ["WebRequestExecutionResult"])])

    def test_27_module_is_pure_and_has_no_module_state(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "ssl", "sqlite3", "shutil", "random", "time",
                     "datetime", "anthropic", "openai", "multimedia", "game_creation", "core", "agent", "planning", "WebRequest", "WebResource",
                     "WebResourceRegistry", "WebRequestPlan", "execute_web_request_plan", "registry"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(wo).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_28_earlier_web_modules_are_unaware_of_the_output(self):
        for name in ("web_resource.py", "web_resource_registry.py", "web_request.py", "web_request_validator.py", "web_request_plan.py", "web_request_executor.py"):
            with open(os.path.join(PY_ROOT, "web", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("web_request_output", "WebRequestOutput", "create_web_request_output"):
                self.assertNotIn(token, text, (name, token))

    def test_29_no_production_module_outside_web_references_it(self):
        tokens = ("web_request_output", "WebRequestOutput", "create_web_request_output")
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

    def test_30_web_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "web")) if f != "__pycache__"),
                         ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py", "web_request_executor.py", "web_request_metadata_executor.py", "web_request_output.py", "web_request_output_validator.py", "web_request_pipeline.py", "web_request_plan.py",
                          "web_request_validator.py", "web_resource.py", "web_resource_registry.py"])
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_31_end_to_end_through_public_apis_only(self):
        plan = make_plan(request_id="e2e", url="https://svc.example/v1", method="POST", resource_type="api", timeout_ms=250)
        out = create_web_request_output(execute_web_request_plan(plan))
        self.assertEqual(out.metadata, plan.to_dict())
        self.assertEqual((out.status, out.code), ("NOT_IMPLEMENTED", NOT_IMPL))

    def test_32_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("WebRequestOutput", "create_web_request_output", "WEB_REQUEST_OUTPUT_", "INVALID_EXECUTION_RESULT", "WebRequestExecutionResult",
                       "REJECTED", "does NOT", "Prompt 780"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
