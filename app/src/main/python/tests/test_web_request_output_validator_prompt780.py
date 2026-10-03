"""Prompt 780 - Section 9 web request output validator (`web.web_request_output_validator`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from web import web_request_output as wo
from web import web_request_output_validator as wv
from web.web_request import create_web_request
from web.web_request_executor import execute_web_request_plan
from web.web_request_output import WebRequestOutput, create_web_request_output
from web.web_request_output_validator import WebRequestOutputValidationResult, validate_web_request_output
from web.web_request_plan import create_web_request_plan
from web.web_request_validator import validate_web_request
from web.web_resource import create_web_resource
from web.web_resource_registry import create_web_resource_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_request_output_validator_prompt780.md")
MODULE = os.path.join(PY_ROOT, "web", "web_request_output_validator.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "WEB_REQUEST_OUTPUT_VALIDATOR_"
INVALID_OUTPUT, INVALID_STATUS, INVALID_CODE, INVALID_METADATA = P + "INVALID_OUTPUT", P + "INVALID_STATUS", P + "INVALID_CODE", P + "INVALID_METADATA"
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
        out = not_impl_output()
        res = validate_web_request_output(out)
        self.assertIs(type(res), WebRequestOutputValidationResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])
        self.assertEqual(out.status, "NOT_IMPLEMENTED")
        self.assertEqual(res.to_dict(), {"ok": True, "output": out.to_dict(), "failures": []})

    def test_2_valid_rejected_output(self):
        for out in (rejected_output(), invalid_input_output()):
            res = validate_web_request_output(out)
            self.assertTrue(res.ok)
            self.assertEqual(out.status, "REJECTED")
            self.assertIs(res.output, out)
            self.assertEqual(res.to_dict()["output"], out.to_dict())

    def test_3_valid_output_with_metadata_none(self):
        out = rejected_output()
        self.assertIsNone(out.metadata)
        res = validate_web_request_output(out)
        self.assertTrue(res.ok)
        self.assertIsNone(res.output.metadata)
        self.assertIsNone(res.to_dict()["output"]["metadata"])

    def test_4_valid_output_with_metadata(self):
        out = not_impl_output(request_id="R-9", method="POST", timeout_ms=1)
        res = validate_web_request_output(out)
        self.assertTrue(res.ok)
        self.assertEqual(res.output.metadata["request_id"], "R-9")
        self.assertEqual(res.to_dict()["output"]["metadata"], out.metadata)
        self.assertEqual(validate_web_request_output(raw_output("S", "C", ())).ok, True)
        self.assertEqual(validate_web_request_output(raw_output("S", "C", (("k", object()),))).ok, True)      # contents are not interpreted

    def test_5_identity_is_preserved_on_success(self):
        for out in (not_impl_output(), rejected_output(), invalid_input_output()):
            res = validate_web_request_output(out)
            self.assertIs(res.output, out)
            self.assertIs(res.output, validate_web_request_output(out).output)

    def test_6_output_is_unchanged(self):
        out = not_impl_output()
        before = (out.to_dict(), hash(out), repr(out))
        validate_web_request_output(out)
        validate_web_request_output(out)
        self.assertEqual(before, (out.to_dict(), hash(out), repr(out)))


class TestInvalidInputAndMalformedOutputs(unittest.TestCase):
    def test_7_invalid_input_types(self):
        out = not_impl_output()
        for bad in (None, {}, [], "output", 5, True, object(), out.to_dict(), WebRequestOutput, (out,), make_plan(),
                    execute_web_request_plan(make_plan()), validate_web_request_output(out)):
            with self.subTest(bad=type(bad).__name__):
                res = validate_web_request_output(bad)
                self.assertFalse(res.ok)
                self.assertIsNone(res.output)
                self.assertEqual(res.codes(), [INVALID_OUTPUT])
                self.assertEqual(res.to_dict(), {"ok": False, "output": None, "failures": [
                    {"code": INVALID_OUTPUT, "field": "output", "message": "output must be exactly a WebRequestOutput."}]})

    def test_8_look_alike_is_rejected_and_never_read(self):
        class Fake:
            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        res = validate_web_request_output(Fake())
        self.assertEqual(res.codes(), [INVALID_OUTPUT])
        self.assertIsNone(res.output)
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestOutput,), {})

    def test_9_never_raises_for_odd_inputs(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")

            def __hash__(self):
                raise RuntimeError("boom")

            def __getattr__(self, name):
                raise RuntimeError("boom")

        for bad in (Boom(), float("nan"), b"x", {1: 2}, lambda: 1, type, 10 ** 100):
            res = validate_web_request_output(bad)
            self.assertEqual(res.codes(), [INVALID_OUTPUT])
            self.assertIsNone(res.output)
            hash(res)

    def test_10_malformed_status(self):
        class S(str):
            pass

        for bad in (None, 5, b"X", ("a",), S("REJECTED"), True):
            with self.subTest(status=repr(bad)):
                out = raw_output(bad, "CODE", None)
                res = validate_web_request_output(out)
                self.assertFalse(res.ok)
                self.assertIsNone(res.output)
                self.assertEqual(res.codes(), [INVALID_STATUS])
                self.assertEqual(res.failures[0]["field"], "status")

    def test_11_malformed_code(self):
        class S(str):
            pass

        for bad in (None, 5, b"X", ["c"], S("CODE"), False):
            with self.subTest(code=repr(bad)):
                res = validate_web_request_output(raw_output("REJECTED", bad, None))
                self.assertFalse(res.ok)
                self.assertIsNone(res.output)
                self.assertEqual(res.codes(), [INVALID_CODE])
                self.assertEqual(res.failures[0]["field"], "code")

    def test_12_malformed_metadata(self):
        class D(dict):
            pass

        out = not_impl_output()
        for bad in ([], (), "m", 5, D(a=1), [("a", 1)], {1, 2}):
            with self.subTest(metadata=type(bad).__name__):
                with mock.patch.object(WebRequestOutput, "metadata", property(lambda self, _b=bad: _b)):
                    res = validate_web_request_output(out)
                self.assertFalse(res.ok)
                self.assertIsNone(res.output)
                self.assertEqual(res.codes(), [INVALID_METADATA])
                self.assertEqual(res.failures[0]["field"], "metadata")
        for bad_items in (5, "abc", (1, 2), object()):      # a metadata read that raises counts as invalid
            with self.subTest(items=repr(bad_items)):
                res = validate_web_request_output(raw_output("NOT_IMPLEMENTED", "CODE", bad_items))
                self.assertEqual(res.codes(), [INVALID_METADATA])
                self.assertIsNone(res.output)

    def test_13_all_problems_are_reported_together_in_order(self):
        res = validate_web_request_output(raw_output(1, 2, 3))
        self.assertEqual(res.codes(), [INVALID_STATUS, INVALID_CODE, INVALID_METADATA])
        self.assertEqual([f["field"] for f in res.failures], ["status", "code", "metadata"])
        self.assertIsNone(res.output)
        self.assertEqual(res.to_dict()["output"], None)
        res = validate_web_request_output(raw_output(1, "ok", None))
        self.assertEqual(res.codes(), [INVALID_STATUS])
        res = validate_web_request_output(raw_output("ok", 2, 3))
        self.assertEqual(res.codes(), [INVALID_CODE, INVALID_METADATA])

    def test_14_malformed_output_is_never_retained_and_result_is_hashable(self):
        out = raw_output(5, ["unhashable"], 3)
        res = validate_web_request_output(out)
        for slot in type(res).__slots__:
            self.assertIsNot(getattr(res, slot), out)
        self.assertIsNone(res.output)
        self.assertIsInstance(hash(res), int)
        self.assertEqual(res, validate_web_request_output(raw_output(5, ["unhashable"], 3)))

    def test_15_constants_are_stable(self):
        self.assertEqual(wv.FAILURE_CODES, (INVALID_OUTPUT, INVALID_STATUS, INVALID_CODE, INVALID_METADATA))
        self.assertEqual(INVALID_OUTPUT, "WEB_REQUEST_OUTPUT_VALIDATOR_INVALID_OUTPUT")


class TestResultContract(unittest.TestCase):
    def setUp(self):
        self.out = not_impl_output()
        self.ok = validate_web_request_output(self.out)
        self.bad = validate_web_request_output(None)
        self.mal = validate_web_request_output(raw_output(1, 2, 3))

    def test_16_immutable(self):
        for obj in (self.ok, self.bad, self.mal):
            for name in ("ok", "output", "failures", "_output", "_failures", "extra"):
                with self.assertRaises(AttributeError):
                    setattr(obj, name, "x")
                with self.assertRaises(AttributeError):
                    delattr(obj, name)
        self.assertIs(self.ok.output, self.out)

    def test_17_direct_construction_and_subclassing_refused(self):
        with self.assertRaises(TypeError):
            WebRequestOutputValidationResult(None, self.out, ())
        with self.assertRaises(TypeError):
            WebRequestOutputValidationResult(object(), None, [])
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestOutputValidationResult,), {})

    def test_18_fresh_dict_and_failures(self):
        for res in (self.ok, self.bad, self.mal):
            a, b = res.to_dict(), res.to_dict()
            self.assertEqual(a, b)
            self.assertIsNot(a, b)
            self.assertIsNot(a["failures"], b["failures"])
            for fa, fb in zip(a["failures"], b["failures"]):
                self.assertIsNot(fa, fb)
            a["ok"] = "X"
            a["extra"] = 1
            a["failures"].append({"code": "x"})
            for f in res.failures:
                f["code"] = "mutated"
            self.assertEqual(res.to_dict(), b)
        a, b = self.ok.to_dict(), self.ok.to_dict()
        self.assertIsNot(a["output"], b["output"])
        self.assertIsNot(a["output"]["metadata"], b["output"]["metadata"])
        a["output"]["metadata"]["url"] = "mutated"
        a["output"]["status"] = "X"
        self.assertEqual(self.ok.to_dict(), {"ok": True, "output": self.out.to_dict(), "failures": []})
        self.assertEqual(self.out.metadata, DEFAULT)
        self.assertIsNot(self.bad.failures, self.bad.failures)
        self.assertEqual(self.bad.failures, self.bad.failures)
        self.assertIsInstance(self.bad.failures, tuple)

    def test_19_equality_and_hash(self):
        again = validate_web_request_output(not_impl_output())      # equal output value, different objects
        self.assertEqual(self.ok, again)
        self.assertFalse(self.ok != again)
        self.assertEqual(hash(self.ok), hash(again))
        self.assertEqual(len({self.ok, again}), 1)
        self.assertEqual(self.bad, validate_web_request_output(5))
        self.assertEqual(hash(self.bad), hash(validate_web_request_output(5)))
        self.assertEqual(self.mal, validate_web_request_output(raw_output(9, 9, 9)))
        self.assertNotEqual(self.ok, self.bad)
        self.assertNotEqual(self.bad, self.mal)
        self.assertNotEqual(self.ok, validate_web_request_output(rejected_output()))
        self.assertNotEqual(self.ok, validate_web_request_output(not_impl_output(url="https://other/")))
        for other in (self.ok.to_dict(), None, 1, "x", self.out):
            self.assertNotEqual(self.ok, other)
        self.assertEqual(self.ok.__eq__(self.ok.to_dict()), NotImplemented)
        self.assertEqual(len({self.ok, self.bad, self.mal, again}), 3)

    def test_20_copy_and_deepcopy_preserve_equality(self):
        for obj in (self.ok, self.bad, self.mal):
            for c in (copy.copy(obj), copy.deepcopy(obj), copy.deepcopy({"k": [obj]})["k"][0]):
                self.assertEqual(c, obj)
                self.assertEqual(hash(c), hash(obj))
                self.assertEqual(c.to_dict(), obj.to_dict())
                self.assertEqual(c.codes(), obj.codes())
        self.assertIs(copy.deepcopy(self.ok).output, self.out)

    def test_21_pickle_refused(self):
        for obj in (self.ok, self.bad, self.mal):
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(codes=obj.codes(), proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(obj, protocol=proto)

    def test_22_repr_is_stable(self):
        self.assertEqual(repr(self.ok), "WebRequestOutputValidationResult(ok=True, codes=[])")
        self.assertEqual(repr(self.bad), "WebRequestOutputValidationResult(ok=False, codes=['%s'])" % INVALID_OUTPUT)

    def test_23_public_surface_is_exact(self):
        for obj in (self.ok, self.bad, self.mal):
            self.assertEqual({n for n in dir(obj) if not n.startswith("_")}, {"ok", "output", "failures", "codes", "to_dict"})
        self.assertIsNot(self.ok.codes(), self.ok.codes())


class TestDeterminismAndSideEffects(unittest.TestCase):
    def test_24_repeated_validation_is_deterministic(self):
        out = not_impl_output()
        results = [validate_web_request_output(out) for _ in range(5)]
        for r in results[1:]:
            self.assertEqual(r, results[0])
            self.assertEqual(hash(r), hash(results[0]))
            self.assertEqual(r.to_dict(), results[0].to_dict())
            self.assertIs(r.output, out)
        self.assertEqual(len({validate_web_request_output(None) for _ in range(3)}), 1)
        self.assertEqual(len({validate_web_request_output(raw_output(1, 2, 3)) for _ in range(3)}), 1)
        self.assertEqual(validate_web_request_output(not_impl_output()), validate_web_request_output(not_impl_output()))

    def test_25_no_side_effects_filesystem_environment_or_modules(self):
        out, rj, mal = not_impl_output(), rejected_output(), raw_output(1, 2, 3)
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            for item in (out, rj, mal, None):
                validate_web_request_output(item)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_26_no_network_filesystem_subprocess_or_persistence_calls(self):
        import builtins
        import io
        import os as _os
        import shutil
        import socket
        import sqlite3
        import subprocess
        import urllib.request
        out, rj, mal = not_impl_output(), rejected_output(), raw_output(1, 2, 3)
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom), mock.patch.object(urllib.request, "urlopen", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(_os, "system", boom), mock.patch.object(_os, "popen", boom), \
                mock.patch.object(builtins, "open", boom), mock.patch.object(io, "open", boom), \
                mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(_os, "remove", boom), mock.patch.object(_os, "mkdir", boom), \
                mock.patch.object(shutil, "copy", boom), mock.patch.object(sqlite3, "connect", boom):
            self.assertTrue(validate_web_request_output(out).ok)
            self.assertTrue(validate_web_request_output(rj).ok)
            self.assertEqual(validate_web_request_output(mal).codes(), [INVALID_STATUS, INVALID_CODE, INVALID_METADATA])
            self.assertEqual(validate_web_request_output(None).codes(), [INVALID_OUTPUT])

    def test_27_no_real_network_module_is_loaded_by_the_validator(self):
        for name in ("socket", "http.client", "urllib.request", "requests", "ssl"):
            self.assertNotIn(name, vars(wv))


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_28_module_imports_only_the_output_type(self):
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [("web_request_output", 1, ["WebRequestOutput"])])

    def test_29_module_is_pure_and_has_no_module_state(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "ssl", "sqlite3", "shutil", "random", "time",
                     "datetime", "anthropic", "openai", "multimedia", "game_creation", "core", "agent", "planning", "WebRequest", "WebResource",
                     "WebResourceRegistry", "WebRequestPlan", "WebRequestExecutionResult", "create_web_request_output", "_items", "_status", "_code"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(wv).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_30_earlier_web_modules_are_unaware_of_the_validator(self):
        for name in ("web_resource.py", "web_resource_registry.py", "web_request.py", "web_request_validator.py", "web_request_plan.py",
                     "web_request_executor.py", "web_request_output.py"):
            with open(os.path.join(PY_ROOT, "web", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("web_request_output_validator", "WebRequestOutputValidationResult", "validate_web_request_output"):
                self.assertNotIn(token, text, (name, token))

    def test_31_no_production_module_outside_web_references_it(self):
        tokens = ("web_request_output_validator", "WebRequestOutputValidationResult", "validate_web_request_output")
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

    def test_32_web_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "web")) if f != "__pycache__"),
                         ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py", "web_request_executor.py", "web_request_metadata_executor.py", "web_request_output.py", "web_request_output_validator.py",
                          "web_request_pipeline.py", "web_request_plan.py", "web_request_validator.py", "web_resource.py", "web_resource_registry.py"])
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_33_end_to_end_through_public_apis_only(self):
        plan = make_plan(request_id="e2e", url="https://svc.example/v1", method="POST", resource_type="api", timeout_ms=250)
        out = create_web_request_output(execute_web_request_plan(plan))
        res = validate_web_request_output(out)
        self.assertTrue(res.ok)
        self.assertIs(res.output, out)
        self.assertEqual(res.to_dict()["output"]["metadata"], plan.to_dict())
        self.assertTrue(validate_web_request_output(create_web_request_output(None)).ok)

    def test_34_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("WebRequestOutputValidationResult", "validate_web_request_output", "WEB_REQUEST_OUTPUT_VALIDATOR_", "INVALID_OUTPUT",
                       "INVALID_STATUS", "INVALID_CODE", "INVALID_METADATA", "WebRequestOutput", "does NOT", "Prompt 781"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
