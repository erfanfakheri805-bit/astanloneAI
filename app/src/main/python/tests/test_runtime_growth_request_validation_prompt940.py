"""
Tests for Prompt 940 - Runtime Growth Request Validation.

`validate_runtime_growth_request(request)` is a pure, deterministic check that a
value is exactly what `create_runtime_growth_request()` (Prompt 939) produces,
including its deterministic request_id.

Run directly:
    python -m unittest tests.test_runtime_growth_request_validation_prompt940 -v
"""

import ast
import copy
import hashlib
import json
import os
import sys
import tempfile
import random
import socket
import sqlite3
import subprocess
import time
import unittest
import uuid
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

validate = val.validate_runtime_growth_request
create = rgr.create_runtime_growth_request
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_request_validation.py")
RESULT_KEYS = ["available", "status", "valid", "error_count", "errors"]
UNAVAILABLE = {"available": False, "status": "unavailable", "valid": False,
               "error_count": 0, "errors": []}


def data(**over):
    base = {"kind": "IMPROVE_CAPABILITY", "goal": "Answer questions faster",
            "target": "code_analysis", "reason": "Users wait too long", "source": "runtime"}
    base.update(over)
    return base


def request(**over):
    return create(data(**over))


def tree_state(root):
    out = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            path = os.path.join(folder, name)
            with open(path, "rb") as handle:
                out[os.path.relpath(path, root)] = hashlib.sha256(handle.read()).hexdigest()
    return out


def errors_of(req):
    result = validate(req)
    assert result["status"] == "invalid", result
    return result["errors"]


class TestValidRequests(unittest.TestCase):
    def check(self, kind):
        result = validate(request(kind=kind))
        self.assertEqual(result, {"available": True, "status": "valid", "valid": True,
                                  "error_count": 0, "errors": []})
        self.assertEqual(list(result), RESULT_KEYS)

    def test_create_capability(self):
        self.check("CREATE_CAPABILITY")

    def test_improve_capability(self):
        self.check("IMPROVE_CAPABILITY")

    def test_improve_runtime(self):
        self.check("IMPROVE_RUNTIME")

    def test_optional_fields_defaulted_by_the_constructor_are_valid(self):
        self.assertTrue(validate(create({"kind": "IMPROVE_RUNTIME", "goal": "g",
                                         "target": "t"}))["valid"])

    def test_persian_and_normalized_text_is_valid(self):
        self.assertTrue(validate(request(goal="  پاسخ   سریع‌تر ", target="تحلیل_کد"))["valid"])


class TestInvalidRequests(unittest.TestCase):
    def test_forged_request_id(self):
        for forged in ("growth_req_0000000000000000", "x", "growth_req_",
                       request()["request_id"].upper(), request()["request_id"] + "0"):
            req = request()
            req["request_id"] = forged
            self.assertEqual(errors_of(req), ["request_id_mismatch"], forged)
        # an id copied from a different request is forged too
        req = request()
        req["request_id"] = request(goal="something else")["request_id"]
        self.assertEqual(errors_of(req), ["request_id_mismatch"])

    def test_invalid_request_id_type_or_empty(self):
        for bad in ("", None, 5, [], {}):
            req = request()
            req["request_id"] = bad
            self.assertEqual(errors_of(req), ["invalid_request_id"], repr(bad))

    def test_content_edit_without_new_id_is_detected(self):
        for field, value in (("goal", "different goal"), ("target", "memory"),
                             ("reason", "new reason"), ("source", "elsewhere"),
                             ("kind", "IMPROVE_RUNTIME")):
            req = request()
            req[field] = value
            self.assertEqual(errors_of(req), ["request_id_mismatch"], field)

    def test_wrong_version(self):
        for bad in ("2", "", 1, None, "1 "):
            req = request()
            req["version"] = bad
            self.assertEqual(errors_of(req), ["invalid_version"], repr(bad))

    def test_unsupported_kind(self):
        for bad in ("DELETE_EVERYTHING", "create_capability", "", None, 1, []):
            req = request()
            req["kind"] = bad
            self.assertEqual(errors_of(req), ["unsupported_kind"], repr(bad))

    def test_missing_goal(self):
        req = request()
        del req["goal"]
        self.assertEqual(errors_of(req), ["missing_goal"])
        for bad in ("", "  ", None, 5, " padded "):
            req = request()
            req["goal"] = bad
            self.assertEqual(errors_of(req), ["invalid_goal"], repr(bad))

    def test_missing_target(self):
        req = request()
        del req["target"]
        self.assertEqual(errors_of(req), ["missing_target"])
        for bad in ("", "  ", None, 5, "two  spaces"):
            req = request()
            req["target"] = bad
            self.assertEqual(errors_of(req), ["invalid_target"], repr(bad))

    def test_invalid_status(self):
        for bad in ("invalid", "approved", "executed", "", None, 1):
            req = request()
            req["status"] = bad
            self.assertEqual(errors_of(req), ["invalid_status"], repr(bad))

    def test_invalid_reason_and_source(self):
        for bad in (None, 5, [], " lead", "x" * 501):
            req = request()
            req["reason"] = bad
            self.assertEqual(errors_of(req), ["invalid_reason"], repr(bad))
        for bad in ("", None, 5, [], "trail ", "x" * 501):
            req = request()
            req["source"] = bad
            self.assertEqual(errors_of(req), ["invalid_source"], repr(bad))
        req = request(reason="")
        self.assertTrue(validate(req)["valid"])  # empty reason is valid

    def test_extra_keys(self):
        for extra in ("execute", "approved", "code", "execution_allowed", 5):
            req = request()
            req[extra] = "x"
            self.assertEqual(errors_of(req), ["unexpected_field"], repr(extra))
        req = request()
        req["a"], req["b"] = 1, 2
        self.assertEqual(errors_of(req), ["unexpected_field"])

    def test_missing_fields_are_reported_in_fixed_order(self):
        self.assertEqual(errors_of({}), [
            "missing_version", "missing_request_id", "missing_kind", "missing_goal",
            "missing_target", "missing_reason", "missing_source", "missing_status"])

    def test_the_constructors_invalid_result_is_invalid(self):
        result = validate(create(None))
        self.assertEqual(result["status"], "invalid")
        self.assertIn("invalid_request_id", result["errors"])
        self.assertIn("invalid_status", result["errors"])
        self.assertIs(result["valid"], False)

    def test_multiple_errors_are_stable_and_counted(self):
        req = request()
        req.update(version="9", kind="NOPE", status="x", extra=1)
        result = validate(req)
        self.assertEqual(result["errors"], ["unexpected_field", "invalid_version",
                                            "unsupported_kind", "invalid_status"])
        self.assertEqual(result["error_count"], 4)
        self.assertEqual(list(result), RESULT_KEYS)
        self.assertIs(result["available"], True)


class TestMalformedInput(unittest.TestCase):
    def test_unavailable_when_not_a_dict(self):
        for bad in (None, "x", 1, 1.5, True, [], (), set(), object(), [request()], ("a",)):
            self.assertEqual(validate(bad), UNAVAILABLE, repr(bad))

    def test_unavailable_when_reading_raises(self):
        class Boom(dict):
            def __contains__(self, key):
                raise RuntimeError("boom")

            def __iter__(self):
                raise RuntimeError("boom")

            def __getitem__(self, key):
                raise RuntimeError("boom")

        self.assertEqual(validate(Boom(request())), UNAVAILABLE)

    def test_dict_subclass_of_a_valid_request_is_still_validated(self):
        class D(dict):
            pass

        self.assertTrue(validate(D(request()))["valid"])


class TestPurity(unittest.TestCase):
    def test_deterministic_repeated_validation(self):
        for req in (request(), dict(request(), status="x"), None, {}):
            first = validate(req)
            for _ in range(4):
                self.assertEqual(validate(req), first)
            self.assertEqual(json.dumps(validate(req)), json.dumps(first))
        self.assertEqual(validate(copy.deepcopy(request())), validate(request()))

    def test_no_input_mutation(self):
        for req in (request(), dict(request(), status="x", extra=1), {"x": [1]}, {}):
            before = copy.deepcopy(req)
            validate(req)
            self.assertEqual(req, before)

    def test_returned_result_is_isolated(self):
        req = dict(request(), status="x")
        first = validate(req)
        first["errors"].append("tampered")
        first["valid"] = True
        first["status"] = "valid"
        second = validate(req)
        self.assertEqual(second["errors"], ["invalid_status"])
        self.assertIs(second["valid"], False)
        self.assertIsNot(second, validate(req))
        self.assertIsNot(second["errors"], validate(req)["errors"])
        ok = validate(request())
        ok["errors"].append("x")
        self.assertEqual(validate(request())["errors"], [])

    def test_no_filesystem_or_database_modification(self):
        db = os.path.join(PY_ROOT, "data", "memory.db")
        with open(db, "rb") as handle:
            db_before = hashlib.sha256(handle.read()).hexdigest()
        tree_before = tree_state(PY_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                for req in (request(), dict(request(), status="x"), None, {}):
                    validate(req)
                self.assertEqual(os.listdir(tmp), [])
            finally:
                os.chdir(old)
        with open(db, "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), db_before)
        self.assertEqual(tree_state(PY_ROOT), tree_before)

    def test_no_io_database_network_subprocess_or_execution_is_attempted(self):
        req = request()
        trap = AssertionError("must not be called")
        with mock.patch("sqlite3.connect", side_effect=trap), \
                mock.patch("socket.socket", side_effect=trap), \
                mock.patch("subprocess.Popen", side_effect=trap), \
                mock.patch("os.system", side_effect=trap), \
                mock.patch("os.remove", side_effect=trap), \
                mock.patch("builtins.exec", side_effect=trap), \
                mock.patch("builtins.eval", side_effect=trap), \
                mock.patch("time.time", side_effect=trap), \
                mock.patch("random.random", side_effect=trap), \
                mock.patch("uuid.uuid4", side_effect=trap), \
                mock.patch("builtins.open", side_effect=trap):
            self.assertTrue(validate(req)["valid"])
            self.assertEqual(validate("bad"), UNAVAILABLE)
            self.assertFalse(validate(dict(req, status="x"))["valid"])

    def test_callables_in_the_request_are_never_called(self):
        trap = mock.Mock(side_effect=AssertionError("must not be called"))
        for field in ("goal", "target", "reason", "source", "kind", "status", "version",
                      "request_id", "extra"):
            self.assertEqual(validate(dict(request(), **{field: trap}))["status"], "invalid")
        trap.assert_not_called()

    def test_module_source_is_pure(self):
        with open(MODULE_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {"runtime_growth"})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__",
                                                "input", "print", "setattr", "delattr", "getattr"})

    def test_not_wired_into_the_runtime(self):
        for rel in ("core/core.py",
                    "runtime_integration/bridge.py", "ael/interpreter.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as handle:
                self.assertNotIn("runtime_growth", handle.read(), rel)


if __name__ == "__main__":
    unittest.main()
