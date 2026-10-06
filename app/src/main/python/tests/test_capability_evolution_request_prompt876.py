"""
Prompt 876 - capability evolution request contract focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_evolution_request_prompt876 -v
"""

import ast
import builtins
import copy
import json
import os
import socket
import subprocess
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_evolution_request as m
from capabilities.capability_evolution_request import build_capability_evolution_request as build
from capabilities.capability_evolution_request import validate_capability_evolution_request as validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "evolution_request", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
NORMAL_KEYS = ["version", "request_id", "operation", "capability_name", "goal", "inputs",
               "outputs", "constraints", "requested_by", "execution_allowed"]
REQUIRED = ["request_id", "operation", "capability_name", "goal", "inputs", "outputs",
            "constraints", "requested_by"]


def req(**over):
    d = {"request_id": "evo_001", "operation": "create", "capability_name": "text_summarizer",
         "goal": "Summarize short documents deterministically.",
         "inputs": ["document_text", "max_sentences"], "outputs": ["summary_text"],
         "constraints": ["No network access.", "Pure Python only."], "requested_by": "developer"}
    d.update(over)
    return d


def normal(**over):
    d = dict(req(), version="1", execution_allowed=False)
    d.update(over)
    return d


def codes(result):
    return [e["code"] for e in result["errors"]]


def check_build_shape(test, r):
    test.assertEqual(list(r), BUILD_KEYS)
    test.assertIs(r["execution_allowed"], False)
    test.assertIs(r["executed"], False)
    json.dumps(r)
    if r["valid"]:
        test.assertEqual(validate(r["evolution_request"])["errors"], [])
    else:
        test.assertIsNone(r["evolution_request"])


class ValidBuildTests(unittest.TestCase):
    def test_valid_create_request(self):
        r = build(req())
        check_build_shape(self, r)
        self.assertEqual((r["valid"], r["errors"]), (True, []))
        self.assertEqual(list(r["evolution_request"]), NORMAL_KEYS)
        self.assertEqual(r["evolution_request"], normal())

    def test_valid_improve_request(self):
        r = build(req(operation="improve", capability_name="existing_cap"))
        check_build_shape(self, r)
        self.assertTrue(r["valid"])
        self.assertEqual(r["evolution_request"]["operation"], "improve")

    def test_values_preserved_exactly_and_in_order(self):
        d = req(inputs=["z", "a", "M"], outputs=["out_b", "Out_A"],
                constraints=["c2", "C1", "c2"])
        e = build(d)["evolution_request"]
        self.assertEqual((e["inputs"], e["outputs"], e["constraints"]),
                         (["z", "a", "M"], ["out_b", "Out_A"], ["c2", "C1", "c2"]))

    def test_empty_inputs_and_constraints_allowed_duplicate_constraints_kept(self):
        e = build(req(inputs=[], constraints=[]))["evolution_request"]
        self.assertEqual((e["inputs"], e["constraints"]), ([], []))
        self.assertEqual(build(req(constraints=["x", "x"]))["evolution_request"]["constraints"],
                         ["x", "x"])

    def test_optional_version_and_flag_accepted_when_exact(self):
        self.assertTrue(build(req(version="1"))["valid"])
        self.assertTrue(build(req(execution_allowed=False))["valid"])
        self.assertTrue(build(normal())["valid"])

    def test_boundary_sizes_accepted(self):
        d = req(request_id="r" * 64, capability_name="n" * 64, goal="g" * 200,
                requested_by="u" * 64, inputs=["i%d" % i for i in range(16)],
                outputs=["o" * 64], constraints=["c" * 120] * 16)
        self.assertTrue(build(d)["valid"])

    def test_fresh_structures_and_deterministic(self):
        d = req()
        a, b = build(d), build(d)
        self.assertEqual(a, b)
        self.assertIsNot(a["evolution_request"]["inputs"], d["inputs"])
        self.assertIsNot(a["evolution_request"]["outputs"], b["evolution_request"]["outputs"])
        a["evolution_request"]["outputs"].append("x")
        self.assertEqual(d["outputs"], ["summary_text"])


class BuildFailureTests(unittest.TestCase):
    def test_missing_and_non_dict_request(self):
        self.assertEqual(build()["errors"], [{"code": "missing_request", "where": "request"}])
        for bad in ([], "x", 3, True, (), [req()]):
            r = build(bad)
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "request_not_dict", "where": "request"}])

    def test_missing_required_fields_are_errors_not_defaults(self):
        for key in REQUIRED:
            d = req(); del d[key]
            r = build(d)
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "missing_field", "where": key}])

    def test_unexpected_fields_rejected(self):
        for extra in ("extra", "code", "patch", "executed", "descriptor"):
            r = build(req(**{extra: 1}))
            self.assertEqual(r["errors"], [{"code": "unexpected_field", "where": extra}])

    def test_invalid_operation(self):
        for bad in ("Create", "IMPROVE", "update", "delete", "", " create", None, 1, True, ["create"]):
            r = build(req(operation=bad))
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "invalid_operation", "where": "operation"}],
                             repr(bad))

    def test_missing_or_invalid_request_id(self):
        for bad in ("", " a", "a ", "a\nb", None, 5, True, [], "x" * 65):
            r = build(req(request_id=bad))
            self.assertEqual(r["errors"], [{"code": "invalid_request_id", "where": "request_id"}],
                             repr(bad))

    def test_request_id_never_auto_generated(self):
        d = req(); del d["request_id"]
        r = build(d)
        self.assertIsNone(r["evolution_request"])
        self.assertEqual(codes(r), ["missing_field"])
        self.assertNotIn("request_id", d)

    def test_invalid_capability_name_goal_requested_by(self):
        for field, limit in (("capability_name", 64), ("goal", 200), ("requested_by", 64)):
            for bad in ("", " a", "a ", "a\tb", None, 5, True, [], "x" * (limit + 1)):
                r = build(req(**{field: bad}))
                self.assertEqual(r["errors"], [{"code": "invalid_" + field, "where": field}],
                                 (field, bad))

    def test_str_subclass_rejected(self):
        class S(str):
            pass
        for field in ("request_id", "capability_name", "goal", "requested_by", "operation"):
            self.assertFalse(build(req(**{field: S("create" if field == "operation" else "abc")}))["valid"])
        self.assertFalse(build(req(inputs=[S("a")]))["valid"])

    def test_invalid_inputs(self):
        for bad in (None, "x", {}, (), 5, True):
            self.assertEqual(build(req(inputs=bad))["errors"],
                             [{"code": "invalid_inputs", "where": "inputs"}], repr(bad))
        for bad in ("", " a", "a\n", None, 5, True, ["a"], "x" * 65):
            self.assertEqual(build(req(inputs=["ok", bad]))["errors"],
                             [{"code": "invalid_item", "where": "inputs[1]"}], repr(bad))

    def test_invalid_outputs(self):
        for bad in (None, "x", {}, (), 5, True):
            self.assertEqual(build(req(outputs=bad))["errors"],
                             [{"code": "invalid_outputs", "where": "outputs"}], repr(bad))
        self.assertEqual(build(req(outputs=[]))["errors"],
                         [{"code": "empty_outputs", "where": "outputs"}])
        for bad in ("", " a", None, 5, False, "x" * 65):
            self.assertEqual(build(req(outputs=["ok", bad]))["errors"],
                             [{"code": "invalid_item", "where": "outputs[1]"}], repr(bad))

    def test_duplicate_inputs_and_outputs_rejected_exactly(self):
        self.assertEqual(build(req(inputs=["a", "b", "a"]))["errors"],
                         [{"code": "duplicate_item", "where": "inputs[2]"}])
        self.assertEqual(build(req(outputs=["x", "x"]))["errors"],
                         [{"code": "duplicate_item", "where": "outputs[1]"}])
        self.assertTrue(build(req(inputs=["a", "A"], outputs=["x", "X"]))["valid"])  # case-sensitive

    def test_invalid_constraints(self):
        for bad in (None, "x", {}, (), 5, True):
            self.assertEqual(build(req(constraints=bad))["errors"],
                             [{"code": "invalid_constraints", "where": "constraints"}], repr(bad))
        for bad in ("", " a", None, 5, True, ["a"], "x" * 121):
            self.assertEqual(build(req(constraints=["ok", bad]))["errors"],
                             [{"code": "invalid_item", "where": "constraints[1]"}], repr(bad))

    def test_too_many_items_rejected(self):
        many = ["i%d" % i for i in range(17)]
        for field in ("inputs", "outputs", "constraints"):
            self.assertEqual(build(req(**{field: many}))["errors"],
                             [{"code": "too_many_items", "where": field}])

    def test_incorrect_version(self):
        for bad in ("2", "", 1, True, None, ["1"]):
            self.assertEqual(build(req(version=bad))["errors"],
                             [{"code": "invalid_version", "where": "version"}], repr(bad))

    def test_incorrect_execution_flag(self):
        for bad in (True, 1, 0, None, "False", []):
            r = build(req(execution_allowed=bad))
            self.assertEqual(r["errors"],
                             [{"code": "invalid_execution_allowed", "where": "execution_allowed"}],
                             repr(bad))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_too_many_fields_and_errors_bounded(self):
        big = {str(i): i for i in range(17)}
        self.assertEqual(build(big)["errors"], [{"code": "too_many_fields", "where": "request"}])
        r = build({str(i): i for i in range(16)})
        self.assertLessEqual(len(r["errors"]), 16)
        self.assertFalse(r["valid"])

    def test_never_raises_on_hostile_input(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")
        for bad in (Boom(), {1: 2}, {None: 1}, {"request_id": object()},
                    req(inputs=[object()]), req(goal=b"bytes")):
            r = build(bad)
            check_build_shape(self, r)
            self.assertFalse(r["valid"])
        with mock.patch.object(m, "_errors", side_effect=RuntimeError):
            r = build(req())
        self.assertEqual(r["errors"], [{"code": "validation_error", "where": "request"}])


class ValidatorTests(unittest.TestCase):
    def test_validate_good_shape_and_flags(self):
        for op in ("create", "improve"):
            v = validate(normal(operation=op))
            self.assertEqual(list(v), VALIDATE_KEYS)
            self.assertEqual((v["valid"], v["errors"]), (True, []))
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)

    def test_all_ten_fields_required_and_no_extras(self):
        for key in NORMAL_KEYS:
            d = normal(); del d[key]
            self.assertEqual(validate(d)["errors"], [{"code": "missing_field", "where": key}])
        self.assertEqual(validate(req())["errors"][0], {"code": "missing_field", "where": "version"})
        for extra in ("extra", "executed", "evolution_request"):
            d = normal(**{extra: 1})
            self.assertEqual(validate(d)["errors"], [{"code": "unexpected_field", "where": extra}])

    def test_missing_and_non_dict(self):
        self.assertEqual(validate()["errors"], [{"code": "missing_request", "where": "request"}])
        for bad in ([], "x", 3, True, (), [normal()]):
            self.assertEqual(validate(bad)["errors"],
                             [{"code": "request_not_dict", "where": "request"}])

    def test_rejects_each_malformed_field(self):
        cases = (("version", "2", "invalid_version"), ("request_id", "", "invalid_request_id"),
                 ("operation", "update", "invalid_operation"),
                 ("capability_name", None, "invalid_capability_name"),
                 ("goal", " x", "invalid_goal"), ("inputs", None, "invalid_inputs"),
                 ("outputs", [], "empty_outputs"), ("outputs", "x", "invalid_outputs"),
                 ("constraints", "x", "invalid_constraints"),
                 ("requested_by", 5, "invalid_requested_by"),
                 ("execution_allowed", True, "invalid_execution_allowed"))
        for key, bad, code in cases:
            self.assertEqual(codes(validate(normal(**{key: bad}))), [code], (key, bad))

    def test_rejects_duplicates_and_bad_items(self):
        self.assertEqual(codes(validate(normal(inputs=["a", "a"]))), ["duplicate_item"])
        self.assertEqual(codes(validate(normal(outputs=["a", "a"]))), ["duplicate_item"])
        self.assertEqual(codes(validate(normal(constraints=[""]))), ["invalid_item"])
        self.assertEqual(codes(validate(normal(inputs=[1]))), ["invalid_item"])

    def test_validation_never_repairs_or_mutates(self):
        d = normal(); before = copy.deepcopy(d)
        validate(d)
        self.assertEqual(d, before)
        bad = normal(operation="CREATE", goal=" padded ")
        self.assertEqual(codes(validate(bad)), ["invalid_operation", "invalid_goal"])
        self.assertEqual(validate(bad), validate(bad))
        self.assertIsNot(validate(bad), validate(bad))
        with mock.patch.object(m, "_errors", side_effect=RuntimeError):
            self.assertEqual(validate(normal())["errors"],
                             [{"code": "validation_error", "where": "request"}])


class ImmutabilityTests(unittest.TestCase):
    def test_build_never_mutates_input(self):
        cases = (req(), req(operation="improve"), req(inputs=["a", "a"]), req(goal=""),
                 normal(), {}, req(extra=1))
        for d in cases:
            before = copy.deepcopy(d)
            build(d)
            self.assertEqual(d, before)


class IsolationTests(unittest.TestCase):
    def test_no_io_subprocess_or_network(self):
        def forbidden(*a, **k):
            raise AssertionError("forbidden call")
        with mock.patch.object(builtins, "open", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(os, "stat", forbidden):
            r = build(req())
            validate(r["evolution_request"])
            build()
        self.assertTrue(r["valid"])

    def test_source_imports_and_public_api(self):
        with open(os.path.join(ROOT, "capabilities", "capability_evolution_request.py"),
                  encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([(type(n).__name__, n.module, n.level) for n in imports],
                         [("ImportFrom", "capability_registry", 1)])
        public = sorted(n.name for n in tree.body
                        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"))
        self.assertEqual(public, ["build_capability_evolution_request",
                                  "validate_capability_evolution_request"])

    def test_no_generation_or_side_effect_tokens(self):
        path = os.path.join(ROOT, "capabilities", "capability_evolution_request.py")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        tree = ast.parse(text)
        # Scan the executable source only: drop the module docstring and function docstrings.
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef)) and ast.get_docstring(node):
                node.body = node.body[1:] or [ast.Pass()]
        code = ast.unparse(tree)
        for token in ("uuid", "random", "time", "open(", "exec(", "eval(", "compile(", "print(",
                      "os.", "sys.", "sorted(", ".sort(", "lower(", "upper(", "write(",
                      "__import__"):
            self.assertNotIn(token, code, token)


if __name__ == "__main__":
    unittest.main()
