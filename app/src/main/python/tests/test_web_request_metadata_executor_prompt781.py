"""Prompt 781 - Section 9 web request metadata executor (`web.web_request_metadata_executor`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from web import web_request_metadata_executor as wm
from web import web_request_output as wo
from web.web_request import create_web_request
from web.web_request_executor import execute_web_request_plan
from web.web_request_metadata_executor import WebRequestMetadataExecutionResult, execute_web_request_metadata
from web.web_request_output import WebRequestOutput, create_web_request_output
from web.web_request_plan import create_web_request_plan
from web.web_request_validator import validate_web_request
from web.web_resource import create_web_resource
from web.web_resource_registry import create_web_resource_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_request_metadata_executor_prompt781.md")
MODULE = os.path.join(PY_ROOT, "web", "web_request_metadata_executor.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
INVALID = "WEB_REQUEST_METADATA_EXECUTOR_INVALID_OUTPUT"
NOT_IMPL = "WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED"
EXEC_INVALID = "WEB_REQUEST_EXECUTOR_INVALID_PLAN"
OUT_INVALID = "WEB_REQUEST_OUTPUT_INVALID_EXECUTION_RESULT"
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


def not_impl_output(**over):
    return create_web_request_output(execute_web_request_plan(make_plan(**over)))


def rejected_output():
    return create_web_request_output(execute_web_request_plan(None))


def invalid_input_output():
    return create_web_request_output(None)


def raw_output(status, code, items):
    """A WebRequestOutput with arbitrary internals (only possible inside tests, via the module's private token)."""
    return WebRequestOutput(wo._CREATE_TOKEN, status, code, items)


class TestValidOutputs(unittest.TestCase):
    def test_1_valid_not_implemented_output(self):
        res = execute_web_request_metadata(not_impl_output())
        self.assertIs(type(res), WebRequestMetadataExecutionResult)
        self.assertEqual(res.status, "NOT_IMPLEMENTED")
        self.assertEqual(res.code, NOT_IMPL)
        self.assertEqual(res.metadata, DEFAULT)
        self.assertEqual(res.to_dict(), {"status": "NOT_IMPLEMENTED", "code": NOT_IMPL, "metadata": DEFAULT})
        self.assertEqual(list(res.to_dict()), ["status", "code", "metadata"])

    def test_2_valid_rejected_output(self):
        res = execute_web_request_metadata(rejected_output())
        self.assertEqual((res.status, res.code), ("REJECTED", EXEC_INVALID))
        self.assertIsNone(res.metadata)
        self.assertEqual(res.to_dict(), {"status": "REJECTED", "code": EXEC_INVALID, "metadata": None})
        res = execute_web_request_metadata(invalid_input_output())
        self.assertEqual((res.status, res.code), ("REJECTED", OUT_INVALID))      # a valid output that itself reports a rejection is copied, not re-coded
        self.assertNotEqual(res.code, INVALID)
        self.assertIsNone(res.metadata)

    def test_3_metadata_present(self):
        res = execute_web_request_metadata(not_impl_output(request_id="R-9", method="POST", timeout_ms=1))
        self.assertEqual(list(res.metadata), list(FIELDS))
        self.assertEqual(res.metadata["request_id"], "R-9")
        self.assertEqual(res.metadata["timeout_ms"], 1)

    def test_4_metadata_none_is_preserved_exactly(self):
        res = execute_web_request_metadata(rejected_output())
        self.assertIsNone(res.metadata)
        self.assertIsNone(res.to_dict()["metadata"])
        self.assertIsNot(res.metadata, {})
        self.assertNotEqual(res, execute_web_request_metadata(raw_output("REJECTED", EXEC_INVALID, ())))      # None and an empty dict are different
        self.assertEqual(execute_web_request_metadata(raw_output("S", "C", ())).metadata, {})

    def test_5_exact_value_preservation_and_identity(self):
        values = {"request_id": "R-9", "url": "https://a.example/p?q=1#f", "method": "POST", "resource_type": "api", "timeout_ms": 1}
        out = not_impl_output(**values)
        res = execute_web_request_metadata(out)
        self.assertEqual((res.status, res.code, res.metadata), (out.status, out.code, out.metadata))
        self.assertEqual(res.metadata, values)
        for k, v in values.items():
            self.assertIs(type(res.metadata[k]), type(v))
        self.assertIs(res.status, out.status)
        self.assertIs(res.code, out.code)
        plan = make_plan(url=" HTTP://Example.ORG/A b ", method=" get ", resource_type=" Page ")
        res = execute_web_request_metadata(create_web_request_output(execute_web_request_plan(plan)))
        for k in FIELDS:
            self.assertIs(res.metadata[k], getattr(plan, k), k)
        self.assertEqual((res.metadata["url"], res.metadata["method"]), (" HTTP://Example.ORG/A b ", " get "))

    def test_6_metadata_is_not_interpreted_or_transformed(self):
        marker = object()
        out = raw_output("anything", "whatever", (("z", marker), ("a", None), (1, "x"), ("", "")))
        res = execute_web_request_metadata(out)
        self.assertEqual(list(res.metadata), ["z", "a", 1, ""])
        self.assertIs(res.metadata["z"], marker)
        self.assertEqual((res.status, res.code), ("anything", "whatever"))

    def test_7_metadata_is_a_copy_not_the_output_dict(self):
        out = not_impl_output()
        res = execute_web_request_metadata(out)
        m = out.metadata
        m["url"] = "mutated"
        self.assertEqual(res.metadata, DEFAULT)
        self.assertIsNot(res.metadata, out.metadata)

    def test_8_output_is_unchanged(self):
        out = not_impl_output()
        before = (out.to_dict(), hash(out), repr(out))
        execute_web_request_metadata(out)
        execute_web_request_metadata(out)
        self.assertEqual(before, (out.to_dict(), hash(out), repr(out)))

    def test_9_output_is_not_retained(self):
        for out in (not_impl_output(), rejected_output()):
            res = execute_web_request_metadata(out)
            self.assertEqual(sorted(type(res).__slots__), ["_code", "_items", "_status"])
            for slot in type(res).__slots__:
                self.assertIsNot(getattr(res, slot), out, slot)
            for name in ("output", "execution_result", "plan", "request"):
                self.assertFalse(hasattr(res, name), name)
            self.assertFalse(hasattr(res, "__dict__"))
            if res.metadata is not None:
                for v in res.metadata.values():
                    self.assertIn(type(v), (str, int))
                    self.assertIsNot(v, out)


class TestInvalidInput(unittest.TestCase):
    def test_10_invalid_inputs_are_rejected(self):
        out = not_impl_output()
        for bad in (None, {}, [], "output", 5, True, object(), out.to_dict(), WebRequestOutput, (out,), make_plan(),
                    execute_web_request_plan(make_plan()), execute_web_request_metadata(out)):
            with self.subTest(bad=type(bad).__name__):
                res = execute_web_request_metadata(bad)
                self.assertIs(type(res), WebRequestMetadataExecutionResult)
                self.assertEqual((res.status, res.code), ("REJECTED", INVALID))
                self.assertIsNone(res.metadata)
                self.assertEqual(res.to_dict(), {"status": "REJECTED", "code": INVALID, "metadata": None})

    def test_11_look_alike_is_rejected_and_never_read(self):
        class Fake:
            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        self.assertEqual(execute_web_request_metadata(Fake()).code, INVALID)
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestOutput,), {})

    def test_12_never_raises_for_odd_inputs(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")

            def __getattr__(self, name):
                raise RuntimeError("boom")

        for bad in (Boom(), float("nan"), b"x", {1: 2}, lambda: 1, type, 10 ** 100):
            self.assertEqual(execute_web_request_metadata(bad).code, INVALID)

    def test_13_malformed_outputs_are_rejected(self):
        for bad in (raw_output(1, "c", None), raw_output("s", 2, None), raw_output("s", "c", 3), raw_output(None, None, "abc"), raw_output("s", "c", (1, 2))):
            with self.subTest(bad=repr(bad)):
                res = execute_web_request_metadata(bad)
                self.assertEqual((res.status, res.code, res.metadata), ("REJECTED", INVALID, None))

    def test_14_constants_are_stable(self):
        self.assertEqual(wm.CODES, (INVALID,))
        self.assertEqual(wm.CODE_INVALID_OUTPUT, "WEB_REQUEST_METADATA_EXECUTOR_INVALID_OUTPUT")
        self.assertEqual(wm.STATUS_REJECTED, "REJECTED")


class TestResultContract(unittest.TestCase):
    def setUp(self):
        self.out = not_impl_output()
        self.res = execute_web_request_metadata(self.out)
        self.rej = execute_web_request_metadata(rejected_output())
        self.bad = execute_web_request_metadata(None)

    def test_15_immutable(self):
        for obj in (self.res, self.rej, self.bad):
            for name in ("status", "code", "metadata", "_status", "_code", "_items", "extra", "output"):
                with self.assertRaises(AttributeError):
                    setattr(obj, name, "x")
                with self.assertRaises(AttributeError):
                    delattr(obj, name)
        self.assertEqual(self.res.to_dict()["metadata"], DEFAULT)

    def test_16_direct_construction_and_subclassing_refused(self):
        with self.assertRaises(TypeError):
            WebRequestMetadataExecutionResult(None, "REJECTED", INVALID, None)
        with self.assertRaises(TypeError):
            WebRequestMetadataExecutionResult(object(), "S", "C", ())
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestMetadataExecutionResult,), {})

    def test_17_fresh_to_dict_and_metadata(self):
        a, b = self.res.to_dict(), self.res.to_dict()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["metadata"], b["metadata"])
        a["metadata"]["url"] = "mutated"
        a["status"] = "X"
        a["extra"] = 1
        m1, m2 = self.res.metadata, self.res.metadata
        self.assertEqual(m1, m2)
        self.assertIsNot(m1, m2)
        m1["method"] = "X"
        m1["new"] = 1
        self.assertEqual(self.res.to_dict(), {"status": "NOT_IMPLEMENTED", "code": NOT_IMPL, "metadata": DEFAULT})
        self.assertEqual(self.res.metadata, DEFAULT)
        for obj in (self.rej, self.bad):
            r1, r2 = obj.to_dict(), obj.to_dict()
            self.assertEqual(r1, r2)
            self.assertIsNot(r1, r2)

    def test_18_equality_and_hash(self):
        again = execute_web_request_metadata(not_impl_output())      # equal value, different objects
        self.assertIsNot(self.res, again)
        self.assertEqual(self.res, again)
        self.assertFalse(self.res != again)
        self.assertEqual(hash(self.res), hash(again))
        self.assertEqual(len({self.res, again}), 1)
        self.assertEqual(self.bad, execute_web_request_metadata(5))
        self.assertEqual(hash(self.bad), hash(execute_web_request_metadata(5)))
        self.assertNotEqual(self.res, self.rej)
        self.assertNotEqual(self.rej, self.bad)
        for field, value in (("request_id", "req_2"), ("url", "https://other/"), ("method", "POST"), ("resource_type", "other"), ("timeout_ms", 6000)):
            with self.subTest(field=field):
                self.assertNotEqual(self.res, execute_web_request_metadata(not_impl_output(**{field: value})))
        for other in (self.res.to_dict(), None, 1, "x", self.out):
            self.assertNotEqual(self.res, other)
        self.assertEqual(self.res.__eq__(self.res.to_dict()), NotImplemented)
        self.assertEqual(len({self.res, self.rej, self.bad, again}), 3)

    def test_19_copy_and_deepcopy_preserve_equality(self):
        for obj in (self.res, self.rej, self.bad):
            for c in (copy.copy(obj), copy.deepcopy(obj), copy.deepcopy({"k": [obj]})["k"][0]):
                self.assertEqual(c, obj)
                self.assertEqual(hash(c), hash(obj))
                self.assertEqual(c.to_dict(), obj.to_dict())
                self.assertEqual(c.metadata, obj.metadata)

    def test_20_pickle_refused(self):
        for obj in (self.res, self.rej, self.bad):
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(code=obj.code, proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(obj, protocol=proto)

    def test_21_repr_is_stable(self):
        self.assertEqual(repr(self.res), "WebRequestMetadataExecutionResult(status='NOT_IMPLEMENTED', code='%s')" % NOT_IMPL)
        self.assertEqual(repr(self.bad), "WebRequestMetadataExecutionResult(status='REJECTED', code='%s')" % INVALID)

    def test_22_public_surface_is_exact(self):
        for obj in (self.res, self.rej, self.bad):
            self.assertEqual({n for n in dir(obj) if not n.startswith("_")}, {"status", "code", "metadata", "to_dict"})


class TestDeterminismAndSideEffects(unittest.TestCase):
    def test_23_repeated_execution_is_deterministic(self):
        out = not_impl_output()
        results = [execute_web_request_metadata(out) for _ in range(5)]
        for r in results[1:]:
            self.assertEqual(r, results[0])
            self.assertEqual(hash(r), hash(results[0]))
            self.assertEqual(r.to_dict(), results[0].to_dict())
        self.assertEqual(len({execute_web_request_metadata(None) for _ in range(3)}), 1)
        self.assertEqual(len({execute_web_request_metadata(rejected_output()) for _ in range(3)}), 1)
        self.assertEqual(execute_web_request_metadata(not_impl_output()), execute_web_request_metadata(not_impl_output()))

    def test_24_no_side_effects_filesystem_environment_or_modules(self):
        out, rj = not_impl_output(), rejected_output()
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            for item in (out, rj, raw_output(1, 2, 3), None):
                execute_web_request_metadata(item)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_25_no_network_filesystem_subprocess_or_database_access(self):
        import builtins
        import io
        import os as _os
        import shutil
        import socket
        import sqlite3
        import subprocess
        import urllib.request
        out, rj = not_impl_output(), rejected_output()
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom), mock.patch.object(urllib.request, "urlopen", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(_os, "system", boom), mock.patch.object(_os, "popen", boom), \
                mock.patch.object(builtins, "open", boom), mock.patch.object(io, "open", boom), \
                mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(_os, "remove", boom), mock.patch.object(_os, "mkdir", boom), \
                mock.patch.object(shutil, "copy", boom), mock.patch.object(sqlite3, "connect", boom):
            self.assertEqual(execute_web_request_metadata(out).code, NOT_IMPL)
            self.assertEqual(execute_web_request_metadata(rj).code, EXEC_INVALID)
            self.assertEqual(execute_web_request_metadata(None).code, INVALID)

    def test_26_no_real_network_module_is_loaded_by_the_executor(self):
        for name in ("socket", "http.client", "urllib.request", "requests", "ssl", "sqlite3", "subprocess"):
            self.assertNotIn(name, vars(wm))


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_27_module_imports_only_the_output_validator(self):
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [("web_request_output_validator", 1, ["validate_web_request_output"])])

    def test_28_module_is_pure_and_has_no_module_state(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "ssl", "sqlite3", "shutil", "random", "time",
                     "datetime", "anthropic", "openai", "multimedia", "game_creation", "core", "agent", "planning", "WebRequest", "WebResource",
                     "WebResourceRegistry", "WebRequestPlan", "WebRequestExecutionResult", "WebRequestOutput", "create_web_request_output",
                     "execute_web_request_plan", "_items_of_output"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(wm).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_29_earlier_web_modules_are_unaware_of_the_metadata_executor(self):
        for name in ("web_resource.py", "web_resource_registry.py", "web_request.py", "web_request_validator.py", "web_request_plan.py",
                     "web_request_executor.py", "web_request_output.py", "web_request_output_validator.py"):
            with open(os.path.join(PY_ROOT, "web", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("web_request_metadata_executor", "WebRequestMetadataExecutionResult", "execute_web_request_metadata"):
                self.assertNotIn(token, text, (name, token))

    def test_30_no_production_module_outside_web_references_it(self):
        tokens = ("web_request_metadata_executor", "WebRequestMetadataExecutionResult", "execute_web_request_metadata")
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

    def test_31_web_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "web")) if f != "__pycache__"),
                         ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py", "web_request_executor.py", "web_request_metadata_executor.py", "web_request_output.py",
                          "web_request_output_validator.py", "web_request_pipeline.py", "web_request_plan.py", "web_request_validator.py", "web_resource.py",
                          "web_resource_registry.py"])
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_32_end_to_end_through_public_apis_only(self):
        plan = make_plan(request_id="e2e", url="https://svc.example/v1", method="POST", resource_type="api", timeout_ms=250)
        res = execute_web_request_metadata(create_web_request_output(execute_web_request_plan(plan)))
        self.assertEqual(res.metadata, plan.to_dict())
        self.assertEqual((res.status, res.code), ("NOT_IMPLEMENTED", NOT_IMPL))

    def test_33_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("WebRequestMetadataExecutionResult", "execute_web_request_metadata", "WEB_REQUEST_METADATA_EXECUTOR_", "INVALID_OUTPUT",
                       "WebRequestOutput", "REJECTED", "does NOT", "Prompt 782"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
