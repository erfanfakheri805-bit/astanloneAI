"""Prompt 775 - Section 9 web request contract (`web.web_request`)."""
import ast
import copy
import hashlib
import json
import os
import pickle
import unittest

from web import web_request as wq
from web.web_request import WebRequest, WebRequestResult, create_web_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_request_prompt775.md")
MODULE = os.path.join(PY_ROOT, "web", "web_request.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
FIELDS = ("request_id", "url", "method", "resource_type", "timeout_ms")
TEXT = ("request_id", "url", "method", "resource_type")


def valid(**over):
    data = {"request_id": "req_1", "url": "https://example.org/docs", "method": "GET", "resource_type": "page", "timeout_ms": 5000}
    data.update(over)
    return data


def code_for(field):
    return wq._INVALID_CODES[wq.FIELDS.index(field)]


class TestValidCreation(unittest.TestCase):
    def test_1_valid_input_builds_a_request_with_every_value_kept(self):
        r = create_web_request(valid())
        self.assertIs(type(r), WebRequestResult)
        self.assertTrue(r.ok)
        self.assertEqual((r.failures, r.codes()), ([], []))
        w = r.request
        self.assertIs(type(w), WebRequest)
        self.assertEqual((w.request_id, w.url, w.method, w.resource_type, w.timeout_ms),
                         ("req_1", "https://example.org/docs", "GET", "page", 5000))

    def test_2_exactly_five_fields_in_fixed_order(self):
        self.assertEqual(wq.FIELDS, FIELDS)
        self.assertEqual(list(create_web_request(valid()).request.to_dict()), list(FIELDS))
        self.assertEqual(WebRequest.__slots__, ("_request_id", "_url", "_method", "_resource_type", "_timeout_ms"))

    def test_3_no_trim_no_normalization_values_are_stored_as_given(self):
        w = create_web_request(valid(request_id=" ID-1 ", url=" HTTP://Example.ORG/A b ", method=" get ", resource_type=" Page ")).request
        self.assertEqual((w.request_id, w.url, w.method, w.resource_type), (" ID-1 ", " HTTP://Example.ORG/A b ", " get ", " Page "))

    def test_4_non_empty_means_only_not_the_empty_string(self):
        for field in TEXT:
            for ok in (" ", "\t", "  \n", "x"):
                with self.subTest(field=field, value=ok):
                    r = create_web_request(valid(**{field: ok}))
                    self.assertTrue(r.ok)
                    self.assertEqual(getattr(r.request, field), ok)

    def test_5_url_method_and_type_are_free_text(self):
        for url in ("not a url", "ftp://x", "file:///etc/passwd", "javascript:alert(1)", "//x", "a"):
            self.assertEqual(create_web_request(valid(url=url)).request.url, url)
        for method in ("get", "Get", "FETCH", "BREW", "x"):
            self.assertEqual(create_web_request(valid(method=method)).request.method, method)
        self.assertTrue(create_web_request(valid(resource_type="anything-at-all")).ok)

    def test_6_timeout_accepts_any_positive_int(self):
        for t in (1, 2, 5000, 10 ** 12, 2 ** 70):
            r = create_web_request(valid(timeout_ms=t))
            self.assertTrue(r.ok)
            self.assertEqual(r.request.timeout_ms, t)
            self.assertIs(type(r.request.timeout_ms), int)

    def test_7_string_identity_is_preserved(self):
        values = {"request_id": "".join(["re", "q_", "1"]), "url": "".join(["http://", "x"]),
                  "method": "".join(["GE", "T"]), "resource_type": "".join(["pa", "ge"])}
        w = create_web_request(valid(**values)).request
        for field in TEXT:
            self.assertIs(getattr(w, field), values[field], field)
            self.assertIs(w.to_dict()[field], values[field], field)

    def test_8_the_factory_never_changes_the_callers_dict(self):
        data = valid(url="  x ")
        snapshot, keys = copy.deepcopy(data), list(data)
        create_web_request(data)
        self.assertEqual(data, snapshot)
        self.assertEqual(list(data), keys)
        bad = {"request_id": "", "zzz": 1}
        snap = dict(bad)
        create_web_request(bad)
        self.assertEqual(bad, snap)

    def test_9_later_edits_to_the_input_do_not_reach_the_request(self):
        data = valid()
        w = create_web_request(data).request
        data["url"] = "changed"
        data["timeout_ms"] = 1
        data["extra"] = 1
        self.assertEqual(w.to_dict(), valid())


class TestFieldValidation(unittest.TestCase):
    def test_10_empty_text_fields_are_rejected(self):
        for field in TEXT:
            with self.subTest(field=field):
                r = create_web_request(valid(**{field: ""}))
                self.assertFalse(r.ok)
                self.assertIsNone(r.request)
                self.assertEqual(r.codes(), [code_for(field)])
                self.assertEqual(r.failures[0]["field"], field)

    def test_11_every_text_field_rejects_wrong_types(self):
        class Sub(str):
            pass
        bads = [None, 0, 1, True, False, 1.5, b"x", bytearray(b"x"), ["a"], ("a",), {"a": 1}, {"a"}, object(), Sub("x"), Sub("")]
        for field in TEXT:
            for bad in bads:
                with self.subTest(field=field, bad=type(bad).__name__):
                    r = create_web_request(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [code_for(field)])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_12_timeout_rejects_non_positive_and_non_int(self):
        class I(int):
            pass
        bads = [0, -1, -5000, -(10 ** 12), True, False, 1.0, 5000.0, 0.5, float("nan"), float("inf"), "5000", "", None, b"1", [1], (1,),
                {"a": 1}, object(), I(5), I(0), 1 + 0j]
        for bad in bads:
            with self.subTest(bad=repr(bad)[:30]):
                r = create_web_request(valid(timeout_ms=bad))
                self.assertFalse(r.ok)
                self.assertIsNone(r.request)
                self.assertEqual(r.codes(), [wq.FAILURE_INVALID_TIMEOUT_MS])
                self.assertEqual(r.failures[0]["field"], "timeout_ms")

    def test_13_bool_is_rejected_for_timeout_even_though_true_is_one(self):
        self.assertEqual(create_web_request(valid(timeout_ms=True)).codes(), [wq.FAILURE_INVALID_TIMEOUT_MS])
        self.assertTrue(create_web_request(valid(timeout_ms=1)).ok)

    def test_14_no_coercion_of_text_to_timeout_or_timeout_to_text(self):
        self.assertFalse(create_web_request(valid(timeout_ms="1000")).ok)
        self.assertFalse(create_web_request(valid(method=200)).ok)

    def test_15_a_str_subclass_method_is_never_called(self):
        calls = []

        class Evil(str):
            def strip(self, *a):
                calls.append("strip")
                return "x"

            def __len__(self):
                calls.append("len")
                return 1

            def __eq__(self, other):
                calls.append("eq")
                return True

            def __ne__(self, other):
                calls.append("ne")
                return False
            __hash__ = str.__hash__
        for field in TEXT:
            create_web_request(valid(**{field: Evil("x")}))
        self.assertEqual(calls, [])

    def test_16_an_int_subclass_method_is_never_called(self):
        calls = []

        class EvilInt(int):
            def __le__(self, other):
                calls.append("le")
                return False

            def __gt__(self, other):
                calls.append("gt")
                return True

            def __eq__(self, other):
                calls.append("eq")
                return True
            __hash__ = int.__hash__
        create_web_request(valid(timeout_ms=EvilInt(5)))
        self.assertEqual(calls, [])

    def test_17_fields_are_validated_independently(self):
        self.assertEqual([f["field"] for f in create_web_request(valid(url="")).failures], ["url"])
        self.assertEqual([f["field"] for f in create_web_request(valid(timeout_ms=0)).failures], ["timeout_ms"])
        self.assertEqual([f["field"] for f in create_web_request(valid(method=3)).failures], ["method"])


class TestInputShape(unittest.TestCase):
    def test_18_non_dict_input_is_rejected_including_dict_subclasses(self):
        from collections import OrderedDict

        class D(dict):
            pass
        for bad in (None, [], (), "x", 1, True, valid().items(), valid().keys(), D(valid()), OrderedDict(valid()), object()):
            with self.subTest(bad=type(bad).__name__):
                r = create_web_request(bad)
                self.assertEqual(r.codes(), [wq.FAILURE_INVALID_INPUT])
                self.assertIsNone(r.request)
                self.assertFalse(r.ok)
                self.assertIsNone(r.failures[0]["field"])

    def test_19_missing_fields_are_rejected_and_nothing_is_defaulted(self):
        for field in FIELDS:
            with self.subTest(field=field):
                data = valid()
                del data[field]
                r = create_web_request(data)
                self.assertFalse(r.ok)
                self.assertEqual(r.codes(), [wq.FAILURE_MISSING_FIELD])
                self.assertEqual(r.failures[0]["field"], field)
        self.assertEqual(create_web_request({}).codes(), [wq.FAILURE_MISSING_FIELD] * 5)

    def test_20_unexpected_fields_are_rejected_not_ignored_and_sorted(self):
        r = create_web_request(valid(zeta=1, headers={}, Alpha="x"))
        self.assertEqual(r.codes(), [wq.FAILURE_UNEXPECTED_FIELD] * 3)
        self.assertEqual([f["field"] for f in r.failures], ["Alpha", "headers", "zeta"])

    def test_21_every_plausible_extra_field_is_rejected(self):
        for extra in ("body", "headers", "retries", "params", "timeout", "title", "resource_id"):
            with self.subTest(extra=extra):
                self.assertEqual(create_web_request(valid(**{extra: "x"})).codes(), [wq.FAILURE_UNEXPECTED_FIELD])

    def test_22_non_string_and_str_subclass_keys_are_rejected(self):
        data = valid()
        data[1] = "x"
        data[None] = "y"
        r = create_web_request(data)
        self.assertEqual(r.codes(), [wq.FAILURE_UNEXPECTED_FIELD])
        self.assertIsNone(r.failures[0]["field"])

        class K(str):
            pass
        data = valid()
        data[K("extra")] = 1
        self.assertEqual(create_web_request(data).codes(), [wq.FAILURE_UNEXPECTED_FIELD])

    def test_23_near_miss_field_names_are_unexpected_and_the_real_field_is_missing(self):
        data = valid()
        data["Method"] = data.pop("method")
        self.assertEqual(create_web_request(data).codes(), [wq.FAILURE_UNEXPECTED_FIELD, wq.FAILURE_MISSING_FIELD])
        data = valid()
        data["timeout"] = data.pop("timeout_ms")
        self.assertEqual(create_web_request(data).codes(), [wq.FAILURE_UNEXPECTED_FIELD, wq.FAILURE_MISSING_FIELD])

    def test_24_key_order_of_the_input_does_not_matter(self):
        data = dict(reversed(list(valid().items())))
        w = create_web_request(data).request
        self.assertEqual(list(w.to_dict()), list(FIELDS))
        self.assertEqual(w, create_web_request(valid()).request)


class TestFailureReporting(unittest.TestCase):
    def test_25_every_problem_is_reported_at_once_in_field_order(self):
        r = create_web_request(valid(request_id="", url=None, method=3, resource_type="", timeout_ms=0))
        self.assertEqual(r.codes(), list(wq._INVALID_CODES))
        self.assertEqual([f["field"] for f in r.failures], list(FIELDS))

    def test_26_input_then_unexpected_then_fields_ordering(self):
        bad = {"zzz": 1, "request_id": "", "url": 5, "aaa": 2}
        self.assertEqual(create_web_request(bad).codes(),
                         [wq.FAILURE_UNEXPECTED_FIELD, wq.FAILURE_UNEXPECTED_FIELD, wq.FAILURE_INVALID_REQUEST_ID,
                          wq.FAILURE_INVALID_URL, wq.FAILURE_MISSING_FIELD, wq.FAILURE_MISSING_FIELD, wq.FAILURE_MISSING_FIELD])

    def test_27_the_factory_never_raises_for_bad_data(self):
        for bad in (None, 1, [], {}, {"x": object()}, valid(url=object()), {None: 1}, valid(url=[1]), valid(request_id=float("nan")),
                    valid(timeout_ms=float("nan")), valid(timeout_ms=object())):
            with self.subTest(bad=repr(bad)[:30]):
                r = create_web_request(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.request)
                for f in r.failures:
                    self.assertIn(f["code"], wq.FAILURE_CODES)
                    self.assertEqual(set(f), {"code", "field", "message"})
                    self.assertIs(type(f["message"]), str)

    def test_28_failures_are_deterministic_across_repeated_calls(self):
        bad = {"zzz": 1, "request_id": "", "url": 5, "aaa": 2, "timeout_ms": -1}
        first = create_web_request(bad).to_dict()
        for _ in range(5):
            self.assertEqual(create_web_request(dict(bad)).to_dict(), first)
        good = create_web_request(valid()).to_dict()
        for _ in range(5):
            self.assertEqual(create_web_request(valid()).to_dict(), good)

    def test_29_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(len(set(wq.FAILURE_CODES)), len(wq.FAILURE_CODES))
        for code in wq.FAILURE_CODES:
            self.assertTrue(code.startswith("WEB_REQUEST_"), code)
        self.assertEqual(wq.FAILURE_CODES, (
            "WEB_REQUEST_INVALID_INPUT", "WEB_REQUEST_UNEXPECTED_FIELD", "WEB_REQUEST_MISSING_FIELD",
            "WEB_REQUEST_INVALID_REQUEST_ID", "WEB_REQUEST_INVALID_URL", "WEB_REQUEST_INVALID_METHOD",
            "WEB_REQUEST_INVALID_RESOURCE_TYPE", "WEB_REQUEST_INVALID_TIMEOUT_MS"))

    def test_30_result_shape_to_dict_and_fresh_failures(self):
        ok = create_web_request(valid()).to_dict()
        self.assertEqual(set(ok), {"ok", "request", "failures"})
        self.assertEqual((ok["ok"], ok["request"], ok["failures"]), (True, valid(), []))
        r = create_web_request(valid(url=""))
        bad = r.to_dict()
        self.assertEqual((bad["ok"], bad["request"]), (False, None))
        bad["failures"][0]["code"] = "hacked"
        bad["failures"].append("x")
        self.assertEqual(r.codes(), [wq.FAILURE_INVALID_URL])
        self.assertIsNot(r.to_dict()["failures"][0], r.to_dict()["failures"][0])

    def test_31_result_ok_and_codes_are_consistent(self):
        self.assertFalse(WebRequestResult().ok)
        self.assertEqual(WebRequestResult().codes(), [])
        self.assertEqual(sorted(WebRequestResult.__slots__), ["failures", "request"])


class TestImmutability(unittest.TestCase):
    def test_32_equal_data_gives_equal_objects_and_hashes(self):
        a, b = create_web_request(valid()).request, create_web_request(valid()).request
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertFalse(a != b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertEqual({a: 1}[b], 1)
        c = create_web_request(valid(url="".join(["https://example", ".org/docs"]))).request
        self.assertEqual((a, hash(a)), (c, hash(c)))

    def test_33_any_differing_field_breaks_equality(self):
        a = create_web_request(valid()).request
        for f, v in {"request_id": "o", "url": "o", "method": "o", "resource_type": "o", "timeout_ms": 1}.items():
            with self.subTest(field=f):
                b = create_web_request(valid(**{f: v})).request
                self.assertNotEqual(a, b)
                self.assertEqual(len({a, b}), 2)

    def test_34_equality_is_exact_type_only(self):
        a = create_web_request(valid()).request
        for other in (valid(), a.to_dict(), None, 1, tuple(valid().values())):
            self.assertNotEqual(a, other)
        self.assertEqual(a.__eq__(valid()), NotImplemented)

    def test_35_to_dict_is_fresh_and_round_trips(self):
        w = create_web_request(valid()).request
        d = w.to_dict()
        self.assertEqual(d, valid())
        d["url"] = "hacked"
        d["timeout_ms"] = 1
        d["extra"] = 1
        self.assertEqual((w.url, w.timeout_ms), ("https://example.org/docs", 5000))
        self.assertIsNot(w.to_dict(), w.to_dict())
        self.assertEqual(w.to_dict(), valid())
        self.assertEqual(create_web_request(w.to_dict()).request, w)
        self.assertEqual(json.loads(json.dumps(w.to_dict())), valid())

    def test_36_attributes_cannot_be_assigned_deleted_or_added(self):
        w = create_web_request(valid()).request
        for field in FIELDS:
            for target in (field, "_" + field):
                with self.assertRaises(AttributeError, msg=target):
                    setattr(w, target, "x")
                with self.assertRaises(AttributeError, msg=target):
                    delattr(w, target)
        with self.assertRaises(AttributeError):
            w.extra = 1
        with self.assertRaises(AttributeError):
            object.__setattr__(w, "extra", 1)
        self.assertFalse(hasattr(w, "__dict__"))
        self.assertEqual(w.to_dict(), valid())

    def test_37_direct_construction_and_subclassing_are_refused(self):
        for args in ((object(), "a", "b", "GET", "page", 1), (None, "a", "b", "GET", "page", 1), ("a", "b", "GET", "page", 1)):
            with self.assertRaises(TypeError):
                WebRequest(*args)
        with self.assertRaises(TypeError):
            WebRequest(**valid())
        with self.assertRaises(TypeError):
            class Sub(WebRequest):
                pass

    def test_38_copy_and_deepcopy_return_the_same_object(self):
        w = create_web_request(valid()).request
        self.assertIs(copy.copy(w), w)
        self.assertIs(copy.deepcopy(w), w)
        self.assertIs(copy.deepcopy({"k": [w]})["k"][0], w)

    def test_39_pickle_is_refused_for_every_protocol(self):
        w = create_web_request(valid()).request
        for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=proto):
                with self.assertRaises(TypeError):
                    pickle.dumps(w, protocol=proto)
        with self.assertRaises(TypeError):
            w.__reduce__()
        with self.assertRaises(TypeError):
            w.__reduce_ex__(2)

    def test_40_repr_is_stable(self):
        self.assertEqual(repr(create_web_request(valid()).request),
                         "WebRequest(request_id='req_1', url='https://example.org/docs', method='GET', resource_type='page', timeout_ms=5000)")


class TestScopeAndHygiene(unittest.TestCase):
    def test_41_module_imports_nothing_and_does_no_io_or_networking(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(names & {"open", "eval", "exec", "compile", "__import__", "input", "print", "getattr", "setattr", "globals", "vars"})
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "ssl", "sqlite3", "random", "time",
                     "datetime", "anthropic", "openai", "core", "agent", "planning", "game_creation", "multimedia"):
            self.assertNotIn(word, names, word)

    def test_42_module_has_no_mutable_module_level_state(self):
        for name, value in vars(wq).items():
            if name.startswith("__"):
                continue
            self.assertNotIsInstance(value, (list, dict, set, bytearray), name)

    def test_43_calling_the_factory_has_no_side_effects(self):
        before_env, before_cwd = dict(os.environ), os.getcwd()
        before_modules = set(__import__("sys").modules)
        for _ in range(3):
            create_web_request(valid())
            create_web_request({"x": 1})
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(__import__("sys").modules), before_modules)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_44_web_package_contains_only_the_expected_files(self):
        entries = sorted(e for e in os.listdir(os.path.join(PY_ROOT, "web")) if e != "__pycache__")
        self.assertEqual(entries, ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py", "web_request_executor.py", "web_request_metadata_executor.py", "web_request_output.py", "web_request_output_validator.py", "web_request_pipeline.py", "web_request_plan.py", "web_request_validator.py", "web_resource.py", "web_resource_registry.py"])
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read(), b"")

    def test_45_neighbouring_web_modules_and_other_code_are_unaware_of_the_request(self):
        for rel in ("web/web_resource.py", "web/web_resource_registry.py", "core/core.py", "input_system/input_system.py",
                    "agent/agent_loop.py", "planning/planner.py", "multimedia/image_asset.py", "game_creation/game_asset.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("WebRequest", "web_request", "from web", "import web"):
                self.assertNotIn(token, text, (rel, token))

    def test_46_no_existing_module_imports_the_web_package(self):
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("web", "tests", "__pycache__")]
            for name in files:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
                for n in ast.walk(tree):
                    mods = []
                    if isinstance(n, ast.Import):
                        mods = [a.name for a in n.names]
                    elif isinstance(n, ast.ImportFrom):
                        mods = [n.module or ""]
                    for m in mods:
                        self.assertNotEqual(m.split(".")[0], "web", os.path.join(folder, name))

    def test_47_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("Prompt 775", "WebRequest", "create_web_request", "WEB_REQUEST_", "timeout_ms", "does NOT", "Prompt 776"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
