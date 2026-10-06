"""
Prompt 850 - upgrade project state focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_project_state_prompt850 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade import project_state as ps
from upgrade.project_state import build_project_state as build
from upgrade.project_state import validate_project_state as validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "project_state", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
NORMAL_KEYS = ["version", "project_id", "revision", "files", "capabilities", "tests",
               "constraints", "execution_allowed"]


def src(**over):
    d = {"project_id": "proj_001", "revision": "r849",
         "files": [{"path": "upgrade/upgrade_request.py", "kind": "module", "status": "present"},
                   {"path": "tests/test_upgrade_request_prompt849.py", "kind": "test",
                    "status": "present"}],
         "capabilities": ["upgrade_request"],
         "tests": ["tests.test_upgrade_request_prompt849"],
         "constraints": ["No automatic self-modification."]}
    d.update(over)
    return d


def normal(**over):
    d = dict(src(), version="1", execution_allowed=False)
    d.update(over)
    return d


def codes(result):
    return [(e["code"], e["where"]) for e in result["errors"]]


def check_shape(test, result, keys=BUILD_KEYS):
    test.assertEqual(list(result), keys)
    test.assertIs(result["execution_allowed"], False)
    test.assertIs(result["executed"], False)
    json.dumps(result)


class ValidStateTests(unittest.TestCase):
    def _valid_build(self):
        r = build(src())
        check_shape(self, r)
        self.assertIs(r["valid"], True)
        self.assertEqual(r["errors"], [])
        self.assertEqual(list(r["project_state"]), NORMAL_KEYS)
        self.assertEqual(r["project_state"], normal())

    def _normalized_has_no_executed_key(self):
        state = build(src())["project_state"]
        self.assertNotIn("executed", state)
        self.assertIs(state["execution_allowed"], False)

    def _build_result_validates(self):
        state = build(src())["project_state"]
        v = validate(state)
        check_shape(self, v, VALIDATE_KEYS)
        self.assertIs(v["valid"], True)

    def _empty_collections_are_valid(self):
        r = build(src(files=[], capabilities=[], tests=[], constraints=[]))
        self.assertIs(r["valid"], True)
        self.assertEqual(r["project_state"]["files"], [])

    def test_build_returns_fresh_copies(self):
        s = src()
        a = build(s)["project_state"]
        a["files"][0]["path"] = "changed"
        a["capabilities"].append("x")
        self.assertEqual(s, src())
        b = build(s)["project_state"]
        self.assertIsNot(a, b)
        self.assertEqual(b, normal())
        self.assertIsNot(b["files"][0], s["files"][0])

    def _explicit_legal_optionals_accepted(self):
        r = build(src(version="1", execution_allowed=False))
        self.assertIs(r["valid"], True)

    def _order_preserved_no_dedupe(self):
        r = build(src(capabilities=["b", "a", "b"], tests=["t2", "t1"]))
        self.assertEqual(r["project_state"]["capabilities"], ["b", "a", "b"])
        self.assertEqual(r["project_state"]["tests"], ["t2", "t1"])

    def test_valid_build_and_validate(self):
        self._valid_build()
        self._normalized_has_no_executed_key()
        self._build_result_validates()

    def test_empty_and_explicit_optionals(self):
        self._empty_collections_are_valid()
        self._explicit_legal_optionals_accepted()
        self._order_preserved_no_dedupe()


class MissingFieldTests(unittest.TestCase):
    def _none_source(self):
        r = build(None)
        check_shape(self, r)
        self.assertEqual(codes(r), [("missing_source", "source")])
        self.assertIsNone(r["project_state"])
        self.assertEqual(codes(build()), [("missing_source", "source")])

    def _each_required_field_missing(self):
        for field in ("project_id", "revision", "files", "capabilities", "tests",
                      "constraints"):
            s = src()
            del s[field]
            r = build(s)
            self.assertIs(r["valid"], False, field)
            self.assertEqual(codes(r), [("missing_field", field)])
            self.assertIsNone(r["project_state"])

    def test_validate_requires_all_eight_keys(self):
        for field in NORMAL_KEYS:
            n = normal()
            del n[field]
            r = validate(n)
            self.assertIs(r["valid"], False, field)
            self.assertEqual(codes(r), [("missing_field", field)])

    def _validate_none_and_empty(self):
        self.assertEqual(codes(validate(None)), [("missing_state", "state")])
        self.assertEqual(codes(validate()), [("missing_state", "state")])
        self.assertEqual(len(validate({})["errors"]), 8)

    def _no_defaulting_or_inference(self):
        r = build({})
        self.assertEqual([c for c, _ in codes(r)], ["missing_field"] * 6)
        self.assertIsNone(r["project_state"])

    def test_none_and_each_required_missing(self):
        self._none_source()
        self._each_required_field_missing()

    def test_validate_none_empty_and_no_defaulting(self):
        self._validate_none_and_empty()
        self._no_defaulting_or_inference()


class FileDescriptorTests(unittest.TestCase):
    def _descriptor_not_dict(self):
        for bad in (None, "a.py", ["path"], ("p", "k", "s"), 1):
            r = build(src(files=[bad]))
            self.assertEqual(codes(r), [("invalid_file", "files[0]")])

    def _descriptor_missing_keys(self):
        for key in ("path", "kind", "status"):
            d = {"path": "a.py", "kind": "module", "status": "present"}
            del d[key]
            r = build(src(files=[d]))
            self.assertEqual(codes(r), [("missing_file_field", "files[0].%s" % key)])

    def _descriptor_extra_key(self):
        d = {"path": "a.py", "kind": "module", "status": "present", "size": "1"}
        self.assertEqual(codes(build(src(files=[d]))), [("unexpected_file_field", "files[0].size")])
        d = {"path": "a.py", "kind": "module", "status": "present", 5: "x"}
        self.assertEqual(codes(build(src(files=[d]))), [("unexpected_file_field", "files[0].<field>")])

    def _descriptor_invalid_values(self):
        for key in ("path", "kind", "status"):
            for bad in ("", " x", "x ", "a\nb", None, 5, b"x", ["x"], "x" * 201):
                d = {"path": "a.py", "kind": "module", "status": "present"}
                d[key] = bad
                r = build(src(files=[d]))
                self.assertEqual(codes(r), [("invalid_file_" + key, "files[0].%s" % key)], (key, bad))

    def _descriptor_bounds_differ_by_field(self):
        ok = {"path": "p" * 200, "kind": "k" * 64, "status": "s" * 64}
        self.assertIs(build(src(files=[ok]))["valid"], True)
        self.assertEqual(codes(build(src(files=[dict(ok, kind="k" * 65)]))),
                         [("invalid_file_kind", "files[0].kind")])

    def _descriptor_subclass_rejected(self):
        class D(dict):
            pass
        d = D(path="a.py", kind="module", status="present")
        self.assertEqual(codes(build(src(files=[d]))), [("invalid_file", "files[0]")])

    def _second_descriptor_position_reported(self):
        good = {"path": "a.py", "kind": "module", "status": "present"}
        r = build(src(files=[good, {"path": "b.py"}]))
        self.assertEqual(codes(r), [("missing_file_field", "files[1].kind"),
                                    ("missing_file_field", "files[1].status")])

    def _oversized_descriptor_rejected_without_scan(self):
        d = {("k%d" % i): "v" for i in range(ps.MAX_FIELDS + 1)}
        self.assertEqual(codes(build(src(files=[d]))), [("too_many_file_fields", "files[0]")])

    def test_descriptor_shape_errors(self):
        self._descriptor_not_dict()
        self._descriptor_subclass_rejected()
        self._descriptor_missing_keys()
        self._descriptor_extra_key()
        self._oversized_descriptor_rejected_without_scan()

    def test_descriptor_value_errors(self):
        self._descriptor_invalid_values()
        self._descriptor_bounds_differ_by_field()
        self._second_descriptor_position_reported()


class TextListTests(unittest.TestCase):
    def test_invalid_capabilities(self):
        self.assertEqual(codes(build(src(capabilities="cap"))), [("invalid_capabilities", "capabilities")])
        self.assertEqual(codes(build(src(capabilities=("cap",)))), [("invalid_capabilities", "capabilities")])
        for bad in ("", " cap", "cap ", None, 3, ["cap"], "c" * 65, "a\x00b"):
            r = build(src(capabilities=["ok", bad]))
            self.assertEqual(codes(r), [("invalid_item", "capabilities[1]")], bad)

    def _invalid_tests(self):
        self.assertEqual(codes(build(src(tests=None))), [("invalid_tests", "tests")])
        self.assertEqual(codes(build(src(tests={"t": 1}))), [("invalid_tests", "tests")])
        for bad in ("", "t ", None, 1, "t" * 201, "x\ty"):
            r = build(src(tests=[bad]))
            self.assertEqual(codes(r), [("invalid_item", "tests[0]")], bad)

    def _invalid_constraints(self):
        self.assertEqual(codes(build(src(constraints="c"))), [("invalid_constraints", "constraints")])
        for bad in ("", "\nc", None, 1.5, "c" * 201):
            r = build(src(constraints=["a", "b", bad]))
            self.assertEqual(codes(r), [("invalid_item", "constraints[2]")], bad)

    def _validate_checks_same_rules(self):
        self.assertEqual(codes(validate(normal(tests=[""]))), [("invalid_item", "tests[0]")])
        self.assertEqual(codes(validate(normal(files=[{"path": "p"}]))),
                         [("missing_file_field", "files[0].kind"),
                          ("missing_file_field", "files[0].status")])

    def test_invalid_tests_and_constraints(self):
        self._invalid_tests()
        self._invalid_constraints()
        self._validate_checks_same_rules()


class OversizedTests(unittest.TestCase):
    def _bounds_accepted_at_limit(self):
        f = [{"path": "p%d" % i, "kind": "k", "status": "s"} for i in range(ps.MAX_FILES)]
        r = build(src(files=f, capabilities=["c"] * ps.MAX_CAPABILITIES,
                      tests=["t"] * ps.MAX_TESTS, constraints=["x"] * ps.MAX_CONSTRAINTS))
        self.assertIs(r["valid"], True)

    def _files_over_limit(self):
        f = [{"path": "p", "kind": "k", "status": "s"}] * (ps.MAX_FILES + 1)
        self.assertEqual(codes(build(src(files=f))), [("too_many_items", "files")])

    def _each_list_over_limit(self):
        for field, limit in (("capabilities", ps.MAX_CAPABILITIES), ("tests", ps.MAX_TESTS),
                             ("constraints", ps.MAX_CONSTRAINTS)):
            r = build(src(**{field: ["x"] * (limit + 1)}))
            self.assertEqual(codes(r), [("too_many_items", field)], field)

    def _oversized_not_scanned(self):
        # invalid items beyond the bound produce only the size error
        r = build(src(tests=[None] * (ps.MAX_TESTS + 1)))
        self.assertEqual(codes(r), [("too_many_items", "tests")])

    def _errors_are_capped(self):
        r = build(src(tests=[None] * ps.MAX_TESTS))
        self.assertLessEqual(len(r["errors"]), 16)
        self.assertIs(r["valid"], False)

    def _oversized_source_dict(self):
        big = {("k%d" % i): 1 for i in range(ps.MAX_FIELDS + 1)}
        r = build(big)
        self.assertEqual(codes(r), [("too_many_fields", "state")])
        self.assertEqual(codes(validate(big)), [("too_many_fields", "state")])

    def _oversized_text(self):
        self.assertEqual(codes(build(src(project_id="p" * 65))), [("invalid_project_id", "project_id")])
        self.assertEqual(codes(build(src(revision="r" * 65))), [("invalid_revision", "revision")])
        self.assertIs(build(src(project_id="p" * 64, revision="r" * 64))["valid"], True)

    def test_limits_accepted_and_exceeded(self):
        self._bounds_accepted_at_limit()
        self._files_over_limit()
        self._each_list_over_limit()

    def test_oversized_not_scanned_and_errors_capped(self):
        self._oversized_not_scanned()
        self._errors_are_capped()

    def test_oversized_dict_and_text(self):
        self._oversized_source_dict()
        self._oversized_text()


class WrongTypeTests(unittest.TestCase):
    def _non_dict_inputs(self):
        for bad in ("s", 1, 1.5, True, [], (), set(), b"x", object()):
            r = build(bad)
            self.assertEqual(codes(r), [("source_not_dict", "source")], repr(bad))
            self.assertEqual(codes(validate(bad)), [("state_not_dict", "state")], repr(bad))

    def _dict_subclass_rejected(self):
        class D(dict):
            pass
        self.assertEqual(codes(build(D(src()))), [("source_not_dict", "source")])
        self.assertEqual(codes(validate(D(normal()))), [("state_not_dict", "state")])

    def _list_subclass_rejected(self):
        class L(list):
            pass
        self.assertEqual(codes(build(src(files=L()))), [("invalid_files", "files")])
        self.assertEqual(codes(build(src(tests=L(["t"])))), [("invalid_tests", "tests")])

    def _str_subclass_rejected(self):
        class S(str):
            pass
        self.assertEqual(codes(build(src(project_id=S("p")))), [("invalid_project_id", "project_id")])
        self.assertEqual(codes(build(src(capabilities=[S("c")]))), [("invalid_item", "capabilities[0]")])
        d = {"path": S("a.py"), "kind": "module", "status": "present"}
        self.assertEqual(codes(build(src(files=[d]))), [("invalid_file_path", "files[0].path")])

    def _wrong_scalar_types(self):
        for field in ("project_id", "revision"):
            for bad in (None, 1, b"x", ["x"], True):
                r = build(src(**{field: bad}))
                self.assertEqual(codes(r), [("invalid_" + field, field)])
        for bad in (None, "x", 1, {}, ()):
            self.assertEqual(codes(build(src(files=bad))), [("invalid_files", "files")])

    def _invalid_version(self):
        for bad in ("2", "", 1, None, True, "1 "):
            self.assertEqual(codes(build(src(version=bad))), [("invalid_version", "version")], repr(bad))
            self.assertEqual(codes(validate(normal(version=bad))), [("invalid_version", "version")])

    def _no_trim_or_coercion(self):
        self.assertIs(build(src(project_id=" p"))["valid"], False)
        self.assertIs(build(src(revision=1))["valid"], False)
        self.assertIs(build(src(files=({"path": "a", "kind": "k", "status": "s"},)))["valid"], False)

    def test_non_dict_and_dict_subclass(self):
        self._non_dict_inputs()
        self._dict_subclass_rejected()

    def test_list_and_str_subclass_rejected(self):
        self._list_subclass_rejected()
        self._str_subclass_rejected()

    def test_wrong_scalars_version_no_coercion(self):
        self._wrong_scalar_types()
        self._invalid_version()
        self._no_trim_or_coercion()


class ExecutionTests(unittest.TestCase):
    def _execution_true_rejected_in_build(self):
        r = build(src(execution_allowed=True))
        self.assertEqual(codes(r), [("invalid_execution_allowed", "execution_allowed")])
        self.assertIsNone(r["project_state"])
        self.assertIs(r["execution_allowed"], False)

    def _execution_non_false_values_rejected(self):
        for bad in (True, 1, 0, "False", "", None, [], 0.0):
            self.assertEqual(codes(build(src(execution_allowed=bad))),
                             [("invalid_execution_allowed", "execution_allowed")], repr(bad))
            self.assertEqual(codes(validate(normal(execution_allowed=bad))),
                             [("invalid_execution_allowed", "execution_allowed")], repr(bad))

    def test_results_never_allow_or_report_execution(self):
        for r in (build(src()), build(None), build(src(execution_allowed=True)),
                  validate(normal()), validate(None), validate(normal(execution_allowed=True))):
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_extra_executed_key_rejected(self):
        self.assertEqual(codes(validate(normal(executed=False))), [("unexpected_field", "executed")])
        self.assertEqual(codes(build(src(executed=False))), [("unexpected_field", "executed")])

    def test_execution_true_and_non_false_rejected(self):
        self._execution_true_rejected_in_build()
        self._execution_non_false_values_rejected()


class MalformedInputTests(unittest.TestCase):
    def _unexpected_fields(self):
        r = build(src(extra=1))
        self.assertEqual(codes(r), [("unexpected_field", "extra")])
        r = build(dict(src(), **{"x": 1}))
        self.assertIsNone(r["project_state"])
        n = normal()
        n[7] = "x"
        self.assertEqual(codes(validate(n)), [("unexpected_field", "<field>")])

    def _hostile_objects_never_raise(self):
        class Evil:
            def __eq__(self, o):
                raise RuntimeError("boom")

            def __len__(self):
                raise RuntimeError("boom")

            def __iter__(self):
                raise RuntimeError("boom")

        for bad in (Evil(), src(files=[Evil()]), src(tests=[Evil()]), src(project_id=Evil())):
            r = build(bad)
            self.assertIs(r["valid"], False)
            check_shape(self, r)
            check_shape(self, validate(bad), VALIDATE_KEYS)

    def _inputs_not_modified(self):
        s = src()
        before = copy.deepcopy(s)
        build(s)
        self.assertEqual(s, before)
        n = normal()
        before = copy.deepcopy(n)
        validate(n)
        self.assertEqual(n, before)
        bad = src(tests=[None], files=[{"path": 1}])
        before = copy.deepcopy(bad)
        build(bad)
        self.assertEqual(bad, before)

    def _deterministic_and_fresh(self):
        bad = src(tests=[None], capabilities="x", files=[5])
        a, b = build(bad), build(bad)
        self.assertEqual(a, b)
        self.assertIsNot(a["errors"], b["errors"])
        a["errors"].append("x")
        self.assertEqual(build(bad), b)

    def test_error_order_follows_field_order(self):
        r = build({"revision": 1, "project_id": 1, "files": 1, "capabilities": 1,
                   "tests": 1, "constraints": 1})
        self.assertEqual([w for _, w in codes(r)],
                         ["project_id", "revision", "files", "capabilities", "tests",
                          "constraints"])

    def test_unexpected_fields_and_hostile_objects(self):
        self._unexpected_fields()
        self._hostile_objects_never_raise()

    def test_inputs_not_modified_deterministic_fresh(self):
        self._inputs_not_modified()
        self._deterministic_and_fresh()


class SafetyBoundaryTests(unittest.TestCase):
    def _module_imports_only_prompt849_helpers(self):
        tree = ast.parse(inspect.getsource(ps))
        mods = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods.append(node.module)
        self.assertEqual(mods, ["upgrade.upgrade_request"])

    def _no_io_or_execution_calls(self):
        names = {n.id for n in ast.walk(ast.parse(inspect.getsource(ps)))
                 if isinstance(n, ast.Name)}
        for forbidden in ("open", "exec", "eval", "compile", "__import__", "input", "print"):
            self.assertNotIn(forbidden, names)

    def _no_other_package_imports_upgrade(self):
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ("upgrade", "tests", "__pycache__")]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    self.assertNotIn("import project_state", text)
                    self.assertNotIn("upgrade.project_state", text, os.path.join(folder, name))

    def _prompt849_module_unchanged_api(self):
        from upgrade import upgrade_request as ur
        self.assertEqual(ur.FIELDS, ("version", "request_id", "goal", "scope", "constraints",
                                     "requested_by", "execution_allowed"))
        self.assertIs(ur.build_upgrade_request(None)["valid"], False)
    def test_module_imports_and_no_io(self):
        self._module_imports_only_prompt849_helpers()
        self._no_io_or_execution_calls()

    def test_no_other_package_imports_upgrade(self):
        self._no_other_package_imports_upgrade()
        self._prompt849_module_unchanged_api()


if __name__ == "__main__":
    unittest.main()
