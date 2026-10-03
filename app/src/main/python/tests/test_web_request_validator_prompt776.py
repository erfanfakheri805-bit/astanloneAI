"""Prompt 776 - Section 9 web request registry validation (`web.web_request_validator`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from web import web_request_validator as wv
from web.web_request import WebRequest, create_web_request
from web.web_request_validator import WebRequestValidationResult, validate_web_request
from web.web_resource import WebResource, create_web_resource
from web.web_resource_registry import WebResourceRegistry, create_web_resource_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_request_validator_prompt776.md")
MODULE = os.path.join(PY_ROOT, "web", "web_request_validator.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "WEB_REQUEST_VALIDATION_"
INVALID_REQUEST, INVALID_REGISTRY, NOT_FOUND = P + "INVALID_REQUEST", P + "INVALID_REGISTRY", P + "RESOURCE_NOT_FOUND"


def resource(rid, **over):
    data = {"resource_id": rid, "url": "https://example.org/" + rid, "title": "T " + rid, "resource_type": "page"}
    data.update(over)
    r = create_web_resource(data)
    assert r.ok, r.failures
    return r.resource


def registry(*ids):
    r = create_web_resource_registry([resource(i) for i in ids])
    assert r.ok, r.failures
    return r.registry


def request(resource_type="page", **over):
    data = {"request_id": "req_1", "url": "https://example.org/x", "method": "GET", "resource_type": resource_type, "timeout_ms": 5000}
    data.update(over)
    r = create_web_request(data)
    assert r.ok, r.failures
    return r.request


class TestValid(unittest.TestCase):
    def test_1_valid_request_with_registered_resource(self):
        res = validate_web_request(request("page"), registry("page", "other"))
        self.assertIs(type(res), WebRequestValidationResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.codes(), [])
        self.assertEqual(res.failures, ())
        self.assertEqual(res.to_dict()["failures"], [])

    def test_2_exact_object_identity_preserved(self):
        q, reg = request("a"), registry("a", "b")
        res = validate_web_request(q, reg)
        self.assertIs(res.request, q)
        self.assertIs(res.registry, reg)
        self.assertIs(res.to_dict() is not None, True)

    def test_3_any_position_in_registry_is_found(self):
        reg = registry("a", "b", "c")
        for rid in ("a", "b", "c"):
            self.assertTrue(validate_web_request(request(rid), reg).ok, rid)

    def test_4_other_request_fields_are_not_restricted_beyond_775(self):
        reg = registry("page")
        for over in ({"url": "not a url"}, {"method": "BREW"}, {"timeout_ms": 1}, {"url": "file:///x"}, {"request_id": " "}):
            with self.subTest(over=over):
                self.assertTrue(validate_web_request(request("page", **over), reg).ok)

    def test_5_registered_resource_url_is_not_compared_with_the_request(self):
        reg = create_web_resource_registry([resource("page", url="https://a.example/")]).registry
        self.assertTrue(validate_web_request(request("page", url="https://completely.different/"), reg).ok)

    def test_6_matching_is_exact_resource_type_against_resource_id(self):
        reg = create_web_resource_registry([resource("docs", resource_type="page")]).registry
        self.assertTrue(validate_web_request(request("docs"), reg).ok)
        self.assertEqual(validate_web_request(request("page"), reg).codes(), [NOT_FOUND])


class TestInvalidInputs(unittest.TestCase):
    def test_7_invalid_request(self):
        class Fake:
            resource_type = "page"
        reg = registry("page")
        for bad in (None, {}, valid_dict(), "x", 1, [], Fake(), object(), request("page").to_dict()):
            with self.subTest(bad=type(bad).__name__):
                res = validate_web_request(bad, reg)
                self.assertFalse(res.ok)
                self.assertEqual(res.codes(), [INVALID_REQUEST])
                self.assertIsNone(res.request)
                self.assertIs(res.registry, reg)
                self.assertEqual(res.failures[0]["field"], "request")

    def test_8_invalid_registry(self):
        class Fake:
            def lookup(self, rid):
                raise AssertionError("must not be called")
        q = request("page")
        for bad in (None, {}, [], (), "x", 1, Fake(), object(), registry("page").to_dict(), registry("page").resources):
            with self.subTest(bad=type(bad).__name__):
                res = validate_web_request(q, bad)
                self.assertFalse(res.ok)
                self.assertEqual(res.codes(), [INVALID_REGISTRY])
                self.assertIs(res.request, q)
                self.assertIsNone(res.registry)
                self.assertEqual(res.failures[0]["field"], "resource_registry")

    def test_9_both_invalid_reported_in_order(self):
        res = validate_web_request(None, None)
        self.assertEqual(res.codes(), [INVALID_REQUEST, INVALID_REGISTRY])
        self.assertEqual([f["field"] for f in res.failures], ["request", "resource_registry"])
        self.assertEqual((res.request, res.registry), (None, None))

    def test_10_arguments_are_not_swapped(self):
        res = validate_web_request(registry("page"), request("page"))
        self.assertEqual(res.codes(), [INVALID_REQUEST, INVALID_REGISTRY])

    def test_11_look_alikes_are_rejected(self):
        res = validate_web_request(resource("page"), registry("page"))
        self.assertEqual(res.codes(), [INVALID_REQUEST])
        res = validate_web_request(request("page"), create_web_resource_registry([]).registry.resources)
        self.assertEqual(res.codes(), [INVALID_REGISTRY])
        res = validate_web_request(create_web_request({}), registry("page"))     # a WebRequestResult is not a WebRequest
        self.assertEqual(res.codes(), [INVALID_REQUEST])

    def test_12_no_cross_validation_after_top_level_failure(self):
        with mock.patch.object(WebResourceRegistry, "lookup", autospec=True, side_effect=AssertionError("lookup must not run")) as spy:
            validate_web_request(None, registry("page"))
            validate_web_request(request("page"), None)
            validate_web_request(None, None)
            validate_web_request("x", object())
            self.assertEqual(spy.call_count, 0)

    def test_13_failure_shape_and_codes_are_stable(self):
        self.assertEqual(wv.FAILURE_CODES, (INVALID_REQUEST, INVALID_REGISTRY, NOT_FOUND))
        self.assertEqual(len(set(wv.FAILURE_CODES)), 3)
        for code in wv.FAILURE_CODES:
            self.assertTrue(code.startswith("WEB_REQUEST_VALIDATION_"))
        for res in (validate_web_request(None, None), validate_web_request(request("z"), registry("a"))):
            for f in res.failures:
                self.assertEqual(set(f), {"code", "field", "message"})
                self.assertIn(f["code"], wv.FAILURE_CODES)
                self.assertIs(type(f["message"]), str)


def valid_dict():
    return {"request_id": "r", "url": "u", "method": "GET", "resource_type": "page", "timeout_ms": 1}


class TestNotFound(unittest.TestCase):
    def test_14_missing_resource(self):
        q, reg = request("nope"), registry("a", "b")
        res = validate_web_request(q, reg)
        self.assertFalse(res.ok)
        self.assertEqual(res.codes(), [NOT_FOUND])
        self.assertEqual(res.failures[0]["field"], "resource_type")
        self.assertIs(res.request, q)
        self.assertIs(res.registry, reg)
        self.assertIn("'nope'", res.failures[0]["message"])

    def test_15_exact_matching_only(self):
        reg = registry("Page")
        for rt in ("page", "PAGE", " Page", "Page ", "Pag"):
            with self.subTest(rt=rt):
                self.assertEqual(validate_web_request(request(rt), reg).codes(), [NOT_FOUND])
        self.assertTrue(validate_web_request(request("Page"), reg).ok)

    def test_16_empty_registry(self):
        res = validate_web_request(request("page"), create_web_resource_registry([]).registry)
        self.assertEqual(res.codes(), [NOT_FOUND])

    def test_17_not_found_message_is_deterministic(self):
        a = validate_web_request(request("x"), registry("a"))
        b = validate_web_request(request("x"), registry("a"))
        self.assertEqual(a.failures, b.failures)
        self.assertEqual(a.failures[0]["message"], "No web resource is registered for resource_type 'x'.")

    def test_18_not_found_is_reported_with_exactly_one_failure(self):
        self.assertEqual(len(validate_web_request(request("x"), registry("a")).failures), 1)


class TestNoMutation(unittest.TestCase):
    def test_19_registry_state_unchanged(self):
        reg = registry("a", "b")
        before, ids = reg.to_dict(), reg.resource_ids
        validate_web_request(request("a"), reg)
        validate_web_request(request("zzz"), reg)
        self.assertEqual(reg.to_dict(), before)
        self.assertEqual(reg.resource_ids, ids)

    def test_20_request_state_unchanged(self):
        q = request("a")
        before = q.to_dict()
        validate_web_request(q, registry("a"))
        validate_web_request(q, registry("b"))
        self.assertEqual(q.to_dict(), before)

    def test_21_resources_unchanged_and_identity_kept(self):
        r1, r2 = resource("a"), resource("b")
        reg = create_web_resource_registry([r1, r2]).registry
        validate_web_request(request("b"), reg)
        self.assertIs(reg.resources[0], r1)
        self.assertIs(reg.resources[1], r2)

    def test_22_same_inputs_are_idempotent(self):
        q, reg = request("a"), registry("a")
        first = validate_web_request(q, reg)
        for _ in range(5):
            again = validate_web_request(q, reg)
            self.assertEqual(again, first)
            self.assertEqual(again.to_dict(), first.to_dict())
            self.assertIsNot(again, first)


class TestPublicLookupDelegation(unittest.TestCase):
    def test_23_lookup_called_once_with_the_request_resource_type_object(self):
        rt = "".join(["pa", "ge"])
        q, reg = request(rt), registry("page")
        with mock.patch.object(WebResourceRegistry, "lookup", autospec=True, side_effect=WebResourceRegistry.lookup) as spy:
            res = validate_web_request(q, reg)
        self.assertTrue(res.ok)
        self.assertEqual(spy.call_count, 1)
        args = spy.call_args[0]
        self.assertIs(args[0], reg)
        self.assertIs(args[1], q.resource_type)

    def test_24_result_follows_whatever_public_lookup_returns(self):
        from web.web_resource_registry import WebResourceLookupResult
        found_other = WebResourceLookupResult(True, resource("zzz"))
        missing = WebResourceLookupResult(False, None, [])
        with mock.patch.object(WebResourceRegistry, "lookup", autospec=True, return_value=found_other):
            self.assertTrue(validate_web_request(request("a"), registry("a")).ok)
        with mock.patch.object(WebResourceRegistry, "lookup", autospec=True, return_value=missing):
            self.assertEqual(validate_web_request(request("a"), registry("a")).codes(), [NOT_FOUND])

    def test_25_found_result_with_non_resource_is_not_trusted(self):
        class Fake:
            found = True
            resource = object()
        with mock.patch.object(WebResourceRegistry, "lookup", autospec=True, return_value=Fake()):
            self.assertEqual(validate_web_request(request("a"), registry("a")).codes(), [NOT_FOUND])

    def test_26_module_uses_only_public_registry_api(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertIn("lookup", attrs)
        for private in ("_resources", "_resource_id", "_resource_type", "_url", "_method", "_timeout_ms", "_request_id", "resource_ids"):
            self.assertNotIn(private, attrs)
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr == "_key":
                self.assertIsInstance(n.value, ast.Name)
                self.assertIn(n.value.id, ("self", "other"))


class TestResultContract(unittest.TestCase):
    def _ok(self):
        return validate_web_request(request("a"), registry("a"))

    def _bad(self):
        return validate_web_request(request("x"), registry("a"))

    def test_27_direct_construction_refused(self):
        for args in ((), (object(), None, None, ()), (None, None, None, ()), (None, None, ())):
            with self.assertRaises(TypeError):
                WebRequestValidationResult(*args)
        with self.assertRaises(TypeError):
            WebRequestValidationResult(request=None, registry=None, failures=())

    def test_28_subclassing_refused(self):
        with self.assertRaises(TypeError):
            class Child(WebRequestValidationResult):
                pass

    def test_29_immutable(self):
        res = self._ok()
        for name in ("ok", "request", "registry", "failures", "_request", "_registry", "_failures", "extra"):
            with self.assertRaises(AttributeError, msg=name):
                setattr(res, name, 1)
            with self.assertRaises(AttributeError, msg=name):
                delattr(res, name)
        with self.assertRaises(AttributeError):
            object.__setattr__(res, "extra", 1)
        self.assertFalse(hasattr(res, "__dict__"))
        self.assertEqual(WebRequestValidationResult.__slots__, ("_request", "_registry", "_failures"))

    def test_30_to_dict_shape_and_freshness(self):
        q, reg = request("a"), registry("a")
        res = validate_web_request(q, reg)
        d = res.to_dict()
        self.assertEqual(list(d), ["ok", "request", "registry", "failures"])
        self.assertEqual(d, {"ok": True, "request": q.to_dict(), "registry": reg.to_dict(), "failures": []})
        d["ok"] = False
        d["request"]["url"] = "hacked"
        d["registry"]["resources"].append(1)
        d["failures"].append("x")
        self.assertEqual(res.to_dict(), {"ok": True, "request": q.to_dict(), "registry": reg.to_dict(), "failures": []})
        self.assertEqual(q.url, "https://example.org/x")
        self.assertIsNot(res.to_dict(), res.to_dict())
        self.assertIsNot(res.to_dict()["request"], res.to_dict()["request"])

    def test_31_failed_to_dict_is_fresh_and_data_shaped(self):
        res = self._bad()
        d = res.to_dict()
        self.assertFalse(d["ok"])
        self.assertEqual([f["code"] for f in d["failures"]], [NOT_FOUND])
        d["failures"][0]["code"] = "hacked"
        d["failures"].clear()
        self.assertEqual(res.codes(), [NOT_FOUND])
        none_res = validate_web_request(None, None).to_dict()
        self.assertEqual((none_res["request"], none_res["registry"]), (None, None))
        import json
        json.dumps(res.to_dict())
        json.dumps(none_res)

    def test_32_failures_property_returns_fresh_copies(self):
        res = self._bad()
        self.assertIs(type(res.failures), tuple)
        f = res.failures[0]
        f["code"] = "hacked"
        self.assertEqual(res.failures[0]["code"], NOT_FOUND)
        self.assertIsNot(res.failures[0], res.failures[0])

    def test_33_equality_and_hash(self):
        q, reg = request("a"), registry("a")
        a, b = validate_web_request(q, reg), validate_web_request(q, reg)
        self.assertEqual(a, b)
        self.assertFalse(a != b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        c = validate_web_request(request("a"), registry("a"))            # equal value, different objects
        self.assertEqual((a, hash(a)), (c, hash(c)))
        self.assertNotEqual(a, validate_web_request(request("x"), reg))
        self.assertNotEqual(a, validate_web_request(q, registry("a", "b")))
        for other in (a.to_dict(), None, 1, "x", (q, reg, ())):
            self.assertNotEqual(a, other)
        self.assertEqual(a.__eq__(a.to_dict()), NotImplemented)

    def test_34_hashable_for_every_outcome(self):
        outcomes = [self._ok(), self._bad(), validate_web_request(None, registry("a")), validate_web_request(request("a"), None),
                    validate_web_request(None, None)]
        for res in outcomes:
            hash(res)
        self.assertEqual(len({*outcomes}), 5)

    def test_35_same_failure_codes_with_different_state_are_different(self):
        a = validate_web_request(None, registry("a"))
        b = validate_web_request(None, registry("b"))
        self.assertEqual(a.codes(), b.codes())
        self.assertNotEqual(a, b)

    def test_36_copy_and_deepcopy_return_same_object(self):
        res = self._ok()
        self.assertIs(copy.copy(res), res)
        self.assertIs(copy.deepcopy(res), res)
        self.assertIs(copy.deepcopy([res])[0], res)

    def test_37_pickle_refused(self):
        for res in (self._ok(), self._bad(), validate_web_request(None, None)):
            for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(res, protocol=proto)
            with self.assertRaises(TypeError):
                res.__reduce__()
            with self.assertRaises(TypeError):
                res.__reduce_ex__(2)

    def test_38_repr_is_stable(self):
        self.assertEqual(repr(self._ok()), "WebRequestValidationResult(ok=True, codes=[])")
        self.assertEqual(repr(self._bad()), "WebRequestValidationResult(ok=False, codes=['%s'])" % NOT_FOUND)

    def test_39_ok_is_derived_from_failures(self):
        self.assertTrue(self._ok().ok)
        for res in (self._bad(), validate_web_request(None, None)):
            self.assertFalse(res.ok)
            self.assertTrue(res.failures)


class TestDeterminism(unittest.TestCase):
    def test_40_never_raises_for_odd_inputs(self):
        class Boom:
            def __getattr__(self, name):
                raise RuntimeError("touched " + name)

            def __eq__(self, other):
                raise RuntimeError("compared")
            __hash__ = None
        for a in (None, Boom(), object(), 1, "x", [], {}, request("a")):
            for b in (None, Boom(), object(), 1, "x", [], {}, registry("a")):
                res = validate_web_request(a, b)
                self.assertIs(type(res), WebRequestValidationResult)

    def test_41_repeated_failures_are_deterministic(self):
        first = [validate_web_request(None, None).to_dict(), validate_web_request(request("x"), registry("a")).to_dict()]
        for _ in range(5):
            self.assertEqual([validate_web_request(None, None).to_dict(), validate_web_request(request("x"), registry("a")).to_dict()], first)

    def test_42_prior_prompt_modules_still_behave_the_same(self):
        self.assertEqual(request("a").to_dict(), {"request_id": "req_1", "url": "https://example.org/x", "method": "GET",
                                                  "resource_type": "a", "timeout_ms": 5000})
        self.assertEqual(registry("a", "b").resource_ids, ("a", "b"))
        self.assertTrue(registry("a").lookup("a").found)

    def test_43_no_side_effects_filesystem_environment_or_modules(self):
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        q, reg = request("a"), registry("a")
        for _ in range(3):
            validate_web_request(q, reg)
            validate_web_request(request("x"), reg)
            validate_web_request(None, None)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_44_no_network_or_file_access_is_attempted(self):
        import builtins
        import socket
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network")), \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")), \
                mock.patch.object(builtins, "open", side_effect=AssertionError("file")):
            self.assertTrue(validate_web_request(request("a"), registry("a")).ok)
            self.assertFalse(validate_web_request(request("x"), registry("a")).ok)
            self.assertFalse(validate_web_request(None, None).ok)


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_45_module_imports_only_prompts_773_to_775(self):
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(sorted(imports), [("web_request", 1, ["WebRequest"]), ("web_resource", 1, ["WebResource"]),
                                           ("web_resource_registry", 1, ["WebResourceRegistry"])])
        self.assertFalse([n for n in ast.walk(self._tree()) if isinstance(n, ast.Import)])

    def test_46_module_has_no_forbidden_calls_or_module_state(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(wv).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_47_module_names_no_forbidden_dependency(self):
        tree = self._tree()
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "ssl", "sqlite3", "random", "time",
                     "datetime", "anthropic", "openai", "game_creation", "multimedia", "ImageAsset", "AudioAsset", "core", "agent", "planning"):
            self.assertNotIn(word, names, word)

    def test_48_earlier_web_modules_are_unaware_of_the_validator(self):
        for name in ("web_resource.py", "web_resource_registry.py", "web_request.py"):
            with open(os.path.join(PY_ROOT, "web", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("web_request_validator", "WebRequestValidationResult", "validate_web_request"):
                self.assertNotIn(token, text, (name, token))

    def test_49_no_production_module_outside_web_references_it(self):
        tokens = ("web_request_validator", "WebRequestValidationResult", "validate_web_request", "web_request", "WebRequest")
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

    def test_50_web_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "web")) if f != "__pycache__"),
                         ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py", "web_request_executor.py", "web_request_metadata_executor.py", "web_request_output.py", "web_request_output_validator.py", "web_request_pipeline.py", "web_request_plan.py", "web_request_validator.py", "web_resource.py", "web_resource_registry.py"])
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_51_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("WebRequestValidationResult", "validate_web_request", "WEB_REQUEST_VALIDATION_", "INVALID_REQUEST", "INVALID_REGISTRY",
                       "RESOURCE_NOT_FOUND", "lookup()", "does NOT", "Prompt 777"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
