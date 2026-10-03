"""Prompt 773 - Section 9 web resource contract (`web.web_resource`)."""
import ast
import copy
import hashlib
import json
import os
import pickle
import unittest

from web import web_resource as wr
from web.web_resource import WebResource, WebResourceResult, create_web_resource

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_resource_prompt773.md")
MODULE = os.path.join(PY_ROOT, "web", "web_resource.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
FIELDS = ("resource_id", "url", "title", "resource_type")
REQUIRED = ("resource_id", "url", "resource_type")


def valid(**over):
    data = {"resource_id": "docs_home", "url": "https://example.org/docs", "title": "Docs Home", "resource_type": "page"}
    data.update(over)
    return data


def code_for(field):
    return wr._INVALID_CODES[wr.FIELDS.index(field)]


class TestValidCreation(unittest.TestCase):
    def test_1_valid_input_builds_a_resource_with_every_value_kept(self):
        r = create_web_resource(valid())
        self.assertIs(type(r), WebResourceResult)
        self.assertTrue(r.ok)
        self.assertEqual((r.failures, r.codes()), ([], []))
        w = r.resource
        self.assertIs(type(w), WebResource)
        self.assertEqual((w.resource_id, w.url, w.title, w.resource_type),
                         ("docs_home", "https://example.org/docs", "Docs Home", "page"))

    def test_2_exactly_four_fields_in_fixed_order(self):
        self.assertEqual(wr.FIELDS, FIELDS)
        self.assertEqual(list(create_web_resource(valid()).resource.to_dict()), list(FIELDS))
        self.assertEqual(WebResource.__slots__, ("_resource_id", "_url", "_title", "_resource_type"))

    def test_3_empty_title_is_valid_and_so_is_a_blank_one(self):
        self.assertEqual(create_web_resource(valid(title="")).resource.title, "")
        self.assertEqual(create_web_resource(valid(title=" \n")).resource.title, " \n")

    def test_4_no_trim_no_normalization_values_are_stored_as_given(self):
        w = create_web_resource(valid(resource_id=" ID-1 ", url=" HTTP://Example.ORG/A b ", title=" T ",
                                      resource_type=" Page ")).resource
        self.assertEqual((w.resource_id, w.url, w.title, w.resource_type), (" ID-1 ", " HTTP://Example.ORG/A b ", " T ", " Page "))

    def test_5_non_empty_means_only_not_the_empty_string(self):
        for field in REQUIRED:
            for ok in (" ", "\t", "  \n", "x"):
                with self.subTest(field=field, value=ok):
                    r = create_web_resource(valid(**{field: ok}))
                    self.assertTrue(r.ok)
                    self.assertEqual(getattr(r.resource, field), ok)

    def test_6_url_and_type_are_free_text(self):
        for url in ("not a url", "ftp://x", "file:///etc/passwd", "javascript:alert(1)", "//x", "a"):
            self.assertEqual(create_web_resource(valid(url=url)).resource.url, url)
        self.assertTrue(create_web_resource(valid(resource_type="anything-at-all")).ok)

    def test_7_string_identity_is_preserved(self):
        values = {"resource_id": "".join(["res", "_", "1"]), "url": "".join(["http://", "x"]),
                  "title": "".join(["Ti", "tle"]), "resource_type": "".join(["pa", "ge"])}
        w = create_web_resource(valid(**values)).resource
        for field in FIELDS:
            self.assertIs(getattr(w, field), values[field], field)
            self.assertIs(w.to_dict()[field], values[field], field)

    def test_8_the_factory_never_changes_the_callers_dict(self):
        data = valid(title="  x ")
        snapshot, keys = copy.deepcopy(data), list(data)
        create_web_resource(data)
        self.assertEqual(data, snapshot)
        self.assertEqual(list(data), keys)
        bad = {"resource_id": "", "zzz": 1}
        snap = dict(bad)
        create_web_resource(bad)
        self.assertEqual(bad, snap)

    def test_9_later_edits_to_the_input_do_not_reach_the_resource(self):
        data = valid()
        w = create_web_resource(data).resource
        data["title"] = "changed"
        data["extra"] = 1
        self.assertEqual(w.to_dict(), valid())


class TestFieldValidation(unittest.TestCase):
    def test_10_empty_required_fields_are_rejected(self):
        for field in REQUIRED:
            with self.subTest(field=field):
                r = create_web_resource(valid(**{field: ""}))
                self.assertFalse(r.ok)
                self.assertIsNone(r.resource)
                self.assertEqual(r.codes(), [code_for(field)])
                self.assertEqual(r.failures[0]["field"], field)

    def test_11_every_field_rejects_wrong_types(self):
        class Sub(str):
            pass
        bads = [None, 0, 1, True, False, 1.5, b"x", bytearray(b"x"), ["a"], ("a",), {"a": 1}, {"a"}, object(), Sub("x"), Sub("")]
        for field in FIELDS:
            for bad in bads:
                with self.subTest(field=field, bad=type(bad).__name__):
                    r = create_web_resource(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [code_for(field)])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_12_a_str_subclass_method_is_never_called(self):
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
            __hash__ = str.__hash__
        for field in FIELDS:
            create_web_resource(valid(**{field: Evil("x")}))
        self.assertEqual(calls, [])

    def test_13_fields_are_validated_independently(self):
        self.assertEqual([f["field"] for f in create_web_resource(valid(url="")).failures], ["url"])
        self.assertEqual([f["field"] for f in create_web_resource(valid(title=3)).failures], ["title"])


class TestInputShape(unittest.TestCase):
    def test_14_non_dict_input_is_rejected_including_dict_subclasses(self):
        from collections import OrderedDict

        class D(dict):
            pass
        for bad in (None, [], (), "x", 1, True, valid().items(), valid().keys(), D(valid()), OrderedDict(valid()), object()):
            with self.subTest(bad=type(bad).__name__):
                r = create_web_resource(bad)
                self.assertEqual(r.codes(), [wr.FAILURE_INVALID_INPUT])
                self.assertIsNone(r.resource)
                self.assertFalse(r.ok)
                self.assertIsNone(r.failures[0]["field"])

    def test_15_missing_fields_are_rejected_and_nothing_is_defaulted(self):
        for field in FIELDS:
            with self.subTest(field=field):
                data = valid()
                del data[field]
                r = create_web_resource(data)
                self.assertFalse(r.ok)
                self.assertEqual(r.codes(), [wr.FAILURE_MISSING_FIELD])
                self.assertEqual(r.failures[0]["field"], field)
        self.assertEqual(create_web_resource({}).codes(), [wr.FAILURE_MISSING_FIELD] * 4)

    def test_16_unexpected_fields_are_rejected_not_ignored_and_sorted(self):
        r = create_web_resource(valid(zeta=1, objects=[], Alpha="x"))
        self.assertEqual(r.codes(), [wr.FAILURE_UNEXPECTED_FIELD] * 3)
        self.assertEqual([f["field"] for f in r.failures], ["Alpha", "objects", "zeta"])

    def test_17_non_string_and_str_subclass_keys_are_rejected(self):
        data = valid()
        data[1] = "x"
        data[None] = "y"
        r = create_web_resource(data)
        self.assertEqual(r.codes(), [wr.FAILURE_UNEXPECTED_FIELD])
        self.assertIsNone(r.failures[0]["field"])

        class K(str):
            pass
        data = valid()
        data[K("extra")] = 1
        self.assertEqual(create_web_resource(data).codes(), [wr.FAILURE_UNEXPECTED_FIELD])

    def test_18_near_miss_field_names_are_unexpected_and_the_real_field_is_missing(self):
        data = valid()
        data["Title"] = data.pop("title")
        self.assertEqual(create_web_resource(data).codes(), [wr.FAILURE_UNEXPECTED_FIELD, wr.FAILURE_MISSING_FIELD])
        data = valid()
        data["id"] = data.pop("resource_id")
        self.assertEqual(create_web_resource(data).codes(), [wr.FAILURE_UNEXPECTED_FIELD, wr.FAILURE_MISSING_FIELD])


class TestFailureReporting(unittest.TestCase):
    def test_19_every_problem_is_reported_at_once_in_field_order(self):
        r = create_web_resource(valid(resource_id="", url=None, title=3, resource_type=""))
        self.assertEqual(r.codes(), list(wr._INVALID_CODES))
        self.assertEqual([f["field"] for f in r.failures], list(FIELDS))

    def test_20_input_then_unexpected_then_fields_ordering(self):
        bad = {"zzz": 1, "resource_id": "", "url": 5, "aaa": 2}
        self.assertEqual(create_web_resource(bad).codes(),
                         [wr.FAILURE_UNEXPECTED_FIELD, wr.FAILURE_UNEXPECTED_FIELD, wr.FAILURE_INVALID_RESOURCE_ID,
                          wr.FAILURE_INVALID_URL, wr.FAILURE_MISSING_FIELD, wr.FAILURE_MISSING_FIELD])

    def test_21_the_factory_never_raises_for_bad_data(self):
        for bad in (None, 1, [], {}, {"x": object()}, valid(title=object()), {None: 1}, valid(url=[1]), valid(resource_id=float("nan"))):
            with self.subTest(bad=repr(bad)[:30]):
                r = create_web_resource(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.resource)
                for f in r.failures:
                    self.assertIn(f["code"], wr.FAILURE_CODES)
                    self.assertEqual(set(f), {"code", "field", "message"})
                    self.assertIs(type(f["message"]), str)

    def test_22_failures_are_deterministic_across_calls(self):
        bad = {"zzz": 1, "resource_id": "", "url": 5, "aaa": 2}
        self.assertEqual(create_web_resource(bad).to_dict(), create_web_resource(dict(bad)).to_dict())

    def test_23_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(len(set(wr.FAILURE_CODES)), len(wr.FAILURE_CODES))
        for code in wr.FAILURE_CODES:
            self.assertTrue(code.startswith("WEB_RESOURCE_"), code)
        self.assertEqual(wr.FAILURE_CODES, (
            "WEB_RESOURCE_INVALID_INPUT", "WEB_RESOURCE_UNEXPECTED_FIELD", "WEB_RESOURCE_MISSING_FIELD",
            "WEB_RESOURCE_INVALID_RESOURCE_ID", "WEB_RESOURCE_INVALID_URL", "WEB_RESOURCE_INVALID_TITLE",
            "WEB_RESOURCE_INVALID_RESOURCE_TYPE"))

    def test_24_result_shape_to_dict_and_fresh_failures(self):
        ok = create_web_resource(valid()).to_dict()
        self.assertEqual(set(ok), {"ok", "resource", "failures"})
        self.assertEqual((ok["ok"], ok["resource"], ok["failures"]), (True, valid(), []))
        r = create_web_resource(valid(url=""))
        bad = r.to_dict()
        self.assertEqual((bad["ok"], bad["resource"]), (False, None))
        bad["failures"][0]["code"] = "hacked"
        bad["failures"].append("x")
        self.assertEqual(r.codes(), [wr.FAILURE_INVALID_URL])
        self.assertIsNot(r.to_dict()["failures"][0], r.to_dict()["failures"][0])

    def test_25_result_ok_and_codes_are_consistent(self):
        self.assertFalse(WebResourceResult().ok)
        self.assertEqual(WebResourceResult().codes(), [])
        self.assertEqual(sorted(WebResourceResult.__slots__), ["failures", "resource"])


class TestImmutability(unittest.TestCase):
    def test_26_equal_data_gives_equal_objects_and_hashes(self):
        a, b = create_web_resource(valid()).resource, create_web_resource(valid()).resource
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertFalse(a != b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertEqual({a: 1}[b], 1)
        c = create_web_resource(valid(title="".join(["Docs", " Home"]))).resource
        self.assertEqual((a, hash(a)), (c, hash(c)))

    def test_27_any_differing_field_breaks_equality(self):
        a = create_web_resource(valid()).resource
        for f, v in {"resource_id": "o", "url": "o", "title": "o", "resource_type": "o"}.items():
            with self.subTest(field=f):
                b = create_web_resource(valid(**{f: v})).resource
                self.assertNotEqual(a, b)
                self.assertEqual(len({a, b}), 2)

    def test_28_equality_is_exact_type_only(self):
        a = create_web_resource(valid()).resource
        for other in (valid(), a.to_dict(), None, 1, tuple(valid().values())):
            self.assertNotEqual(a, other)
        self.assertEqual(a.__eq__(valid()), NotImplemented)

    def test_29_to_dict_is_fresh_and_round_trips(self):
        w = create_web_resource(valid()).resource
        d = w.to_dict()
        self.assertEqual(d, valid())
        d["title"] = "hacked"
        d["extra"] = 1
        self.assertEqual(w.title, "Docs Home")
        self.assertIsNot(w.to_dict(), w.to_dict())
        self.assertEqual(w.to_dict(), valid())
        self.assertEqual(create_web_resource(w.to_dict()).resource, w)
        self.assertEqual(json.loads(json.dumps(w.to_dict())), valid())

    def test_30_attributes_cannot_be_assigned_deleted_or_added(self):
        w = create_web_resource(valid()).resource
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

    def test_31_direct_construction_and_subclassing_are_refused(self):
        for args in ((object(), "a", "b", "", "page"), (None, "a", "b", "", "page"), ("a", "b", "", "page")):
            with self.assertRaises(TypeError):
                WebResource(*args)
        with self.assertRaises(TypeError):
            WebResource(**valid())
        with self.assertRaises(TypeError):
            class Sub(WebResource):
                pass

    def test_32_copy_and_deepcopy_return_the_same_object(self):
        w = create_web_resource(valid()).resource
        self.assertIs(copy.copy(w), w)
        self.assertIs(copy.deepcopy(w), w)
        self.assertIs(copy.deepcopy({"k": [w]})["k"][0], w)

    def test_33_pickle_is_refused_for_every_protocol(self):
        w = create_web_resource(valid()).resource
        for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=proto):
                with self.assertRaises(TypeError):
                    pickle.dumps(w, protocol=proto)
        with self.assertRaises(TypeError):
            w.__reduce__()
        with self.assertRaises(TypeError):
            w.__reduce_ex__(2)

    def test_34_repr_is_stable(self):
        self.assertEqual(repr(create_web_resource(valid()).resource),
                         "WebResource(resource_id='docs_home', url='https://example.org/docs', title='Docs Home', resource_type='page')")


class TestScopeAndHygiene(unittest.TestCase):
    def test_35_module_imports_nothing_and_does_no_io_or_networking(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "eval", "exec", "compile", "__import__", "input", "print"})

    def test_36_module_has_no_mutable_module_level_state(self):
        for name, value in vars(wr).items():
            if name.startswith("__"):
                continue
            self.assertNotIsInstance(value, (list, dict, set, bytearray), name)

    def test_37_web_package_contains_only_the_expected_files(self):
        entries = sorted(e for e in os.listdir(os.path.join(PY_ROOT, "web")) if e != "__pycache__")
        self.assertEqual(entries, ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py", "web_request_executor.py", "web_request_metadata_executor.py", "web_request_output.py", "web_request_output_validator.py", "web_request_pipeline.py", "web_request_plan.py", "web_request_validator.py", "web_resource.py", "web_resource_registry.py"])      # Prompt 774 adds the registry module; Prompt 775 adds web_request
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read(), b"")

    def test_38_no_existing_module_imports_the_web_package(self):
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

    def test_39_doc_exists_and_mentions_the_contract(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for needle in ("Prompt 773", "WebResource", "create_web_resource", "WEB_RESOURCE_", "Prompt 774", "NOT"):
            self.assertIn(needle, text)

    def test_40_pristine_database_is_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
