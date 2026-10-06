"""
Prompt 903 - Section 18: internal next-stage readiness contract.

Deterministic tests of autonomy/internal_next_stage.py. "ready_for_internal_stage" only describes
the next controlled internal stage; it is not implementation or execution permission.

Run (from app/src/main/python/):
    python -m unittest tests.test_internal_next_stage_prompt903 -v
"""

import ast
import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autonomy import internal_next_stage as mod
from autonomy.internal_next_stage import (
    NEXT_STAGE, RESULT_KEYS, STATUSES,
    build_internal_next_stage as build, validate_internal_next_stage as validate)
from tests.test_claude_exit_readiness_prompt902 import run as run902

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "internal_next_stage.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "internal_next_stage_prompt903.md")
IDENTITY = ("request_id", "implementation_request_id", "capability_name", "operation")
FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started", "executed")


def ready(op="create"):
    return run902(op)


def edited(op="create", **fields):
    return dict(ready(op), **fields)


def assert_rejected(test, result, status):
    test.assertEqual(result["status"], status)
    test.assertIs(result["valid"], False)
    test.assertIsNone(result["next_stage"])
    for key in IDENTITY:
        test.assertIsNone(result[key])
    test.assertEqual(result["reason"], status)
    for flag in FLAGS:
        test.assertIs(result[flag], False)
    test.assertTrue(validate(result)["valid"])


class ValidPathTests(unittest.TestCase):
    def test_valid_create_readiness(self):
        r = build(ready("create"))
        self.assertEqual(r["status"], "ready_for_internal_stage")
        self.assertIs(r["valid"], True)
        self.assertEqual(r["operation"], "create")

    def test_valid_improve_readiness(self):
        r = build(ready("improve"))
        self.assertEqual(r["status"], "ready_for_internal_stage")
        self.assertEqual(r["operation"], "improve")

    def test_next_stage_value(self):
        for op in ("create", "improve"):
            self.assertEqual(build(ready(op))["next_stage"], "controlled_internal_evolution")
        self.assertEqual(NEXT_STAGE, "controlled_internal_evolution")

    def test_exact_thirteen_keys_in_order(self):
        self.assertEqual(len(RESULT_KEYS), 13)
        for op in ("create", "improve"):
            self.assertEqual(list(build(ready(op))), list(RESULT_KEYS))

    def test_version_is_integer_one(self):
        r = build(ready())
        self.assertIs(type(r["version"]), int)
        self.assertEqual(r["version"], 1)

    def test_identity_copied_from_readiness(self):
        src = ready()
        r = build(src)
        self.assertEqual({k: r[k] for k in IDENTITY}, {k: src[k] for k in IDENTITY})
        self.assertEqual(r["request_id"], "evo_001")
        self.assertEqual(r["implementation_request_id"], "ir_001")
        self.assertEqual(r["capability_name"], "text_summarizer")

    def test_ready_does_not_mean_implementation_allowed(self):
        r = build(ready())
        self.assertIs(r["implementation_allowed"], False)
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["implementation_started"], False)
        self.assertIs(r["executed"], False)

    def test_expected_identity_matching_is_accepted(self):
        src = ready()
        r = build(src, {k: src[k] for k in IDENTITY})
        self.assertEqual(r["status"], "ready_for_internal_stage")

    def test_exact_status_vocabulary(self):
        self.assertEqual(set(STATUSES), {
            "ready_for_internal_stage", "not_ready", "invalid_readiness", "context_mismatch",
            "forbidden_execution_state", "validation_error"})


class RejectionTests(unittest.TestCase):
    def test_non_ready_902_state_is_not_ready(self):
        r902 = run902("create", decision=None)
        self.assertNotEqual(r902["status"], "ready_without_claude")
        assert_rejected(self, build(r902), "not_ready")

    def test_claude_independent_false_rejected(self):
        assert_rejected(self, build(edited(claude_independent=False)), "invalid_readiness")

    def test_valid_false_on_ready_status_rejected(self):
        assert_rejected(self, build(edited(valid=False)), "invalid_readiness")

    def test_forged_ready_with_wrong_reason(self):
        assert_rejected(self, build(edited(reason="not_ready")), "invalid_readiness")

    def test_forged_ready_with_missing_requirements(self):
        r = edited(missing_requirements=["policy_valid"])
        assert_rejected(self, build(r), "invalid_readiness")

    def test_forged_non_ready_claiming_independence(self):
        r = dict(run902("create", decision=None), claude_independent=True)
        assert_rejected(self, build(r), "invalid_readiness")

    def test_forged_non_ready_carrying_identity(self):
        r = dict(run902("create", decision=None), request_id="evo_001")
        assert_rejected(self, build(r), "invalid_readiness")

    def test_forged_unsupported_operation(self):
        assert_rejected(self, build(edited(operation="delete")), "invalid_readiness")

    def test_forged_blank_identity(self):
        assert_rejected(self, build(edited(capability_name="")), "invalid_readiness")
        assert_rejected(self, build(edited(implementation_request_id=None)),
                        "invalid_readiness")

    def test_identity_mismatch_with_expected(self):
        src = ready()
        for key in IDENTITY:
            expected = {k: src[k] for k in IDENTITY}
            expected[key] = "other"
            assert_rejected(self, build(src, expected), "context_mismatch")

    def test_expected_identity_malformed_is_mismatch(self):
        for bad in ([], "x", 5, {"unknown": "x"}):
            assert_rejected(self, build(ready(), bad), "context_mismatch")


class FlagTests(unittest.TestCase):
    def test_each_permission_flag_true_is_forbidden(self):
        for flag in ("implementation_allowed", "implementation_started"):
            assert_rejected(self, build(edited(**{flag: True})), "forbidden_execution_state")

    def test_each_execution_flag_true_is_forbidden(self):
        for flag in ("execution_allowed", "executed"):
            assert_rejected(self, build(edited(**{flag: True})), "forbidden_execution_state")

    def test_truthy_non_bool_flags_forbidden(self):
        for value in (1, "yes", [1]):
            assert_rejected(self, build(edited(executed=value)), "forbidden_execution_state")

    def test_falsy_non_bool_flag_is_invalid_not_forbidden(self):
        assert_rejected(self, build(edited(executed=0)), "invalid_readiness")

    def test_nested_flag_is_forbidden(self):
        r = edited()
        r["missing_requirements"] = [{"execution_allowed": True}]
        assert_rejected(self, build(r), "forbidden_execution_state")

    def test_flag_takes_priority_over_non_ready(self):
        r = dict(run902("create", decision=None), executed=True)
        assert_rejected(self, build(r), "forbidden_execution_state")


class MalformedInputTests(unittest.TestCase):
    def test_malformed_inputs(self):
        for bad in (None, [], (), "ready", 5, 1.5, True, object(), set(), {}):
            assert_rejected(self, build(bad), "invalid_readiness")

    def test_raising_flag_value_is_forbidden(self):
        class Bad:
            def __bool__(self):
                raise RuntimeError("no")
        assert_rejected(self, build(edited(executed=Bad())), "forbidden_execution_state")

    def test_internal_failure_is_validation_error(self):
        original = mod.validate_claude_exit_readiness
        mod.validate_claude_exit_readiness = lambda *_a, **_k: 1 / 0
        try:
            assert_rejected(self, build(ready()), "validation_error")
        finally:
            mod.validate_claude_exit_readiness = original


class DeterminismTests(unittest.TestCase):
    def test_repeated_results_equal(self):
        src = ready()
        self.assertEqual(build(src), build(src))
        self.assertEqual([build(ready("improve")) for _ in range(3)],
                         [build(ready("improve"))] * 3)

    def test_fresh_dict_each_call(self):
        src = ready()
        a, b = build(src), build(src)
        self.assertIsNot(a, b)
        a["status"] = "changed"
        self.assertEqual(build(src)["status"], "ready_for_internal_stage")

    def test_input_never_modified(self):
        src = ready()
        snapshot = copy.deepcopy(src)
        build(src)
        build(src, {k: src[k] for k in IDENTITY})
        self.assertEqual(src, snapshot)


class ResultValidationTests(unittest.TestCase):
    def test_valid_ready_result(self):
        for op in ("create", "improve"):
            v = validate(build(ready(op)))
            self.assertEqual(v, {"valid": True, "errors": [], "execution_allowed": False,
                                 "executed": False})

    def test_non_dict(self):
        for bad in (None, [], "x", 1):
            v = validate(bad)
            self.assertFalse(v["valid"])
            self.assertEqual(v["errors"][0]["code"], "result_not_dict")

    def test_missing_and_unexpected_keys(self):
        r = build(ready())
        del r["next_stage"]
        self.assertEqual(validate(r)["errors"][0]["code"], "missing_key")
        r = dict(build(ready()), extra=1)
        self.assertEqual(validate(r)["errors"][0]["code"], "unexpected_key")

    def test_flag_true_rejected(self):
        for flag in FLAGS:
            r = dict(build(ready()), **{flag: True})
            v = validate(r)
            self.assertFalse(v["valid"])
            self.assertIn("invalid_flag", [e["code"] for e in v["errors"]])

    def test_forged_ready_result_rejected(self):
        r = dict(build(None), status="ready_for_internal_stage")
        self.assertFalse(validate(r)["valid"])
        r = dict(build(ready()), next_stage=None)
        self.assertFalse(validate(r)["valid"])
        r = dict(build(None), next_stage=NEXT_STAGE)
        self.assertFalse(validate(r)["valid"])

    def test_bad_status_valid_reason_version(self):
        base = build(ready())
        for field, value in (("status", "approved"), ("valid", 1), ("reason", "x"),
                             ("version", 2), ("version", True)):
            self.assertFalse(validate(dict(base, **{field: value}))["valid"], field)

    def test_identity_rules(self):
        base = build(ready())
        for field, value in (("operation", "delete"), ("capability_name", ""),
                             ("request_id", 5), ("implementation_request_id", None)):
            v = validate(dict(base, **{field: value}))
            self.assertFalse(v["valid"], field)
        rejected = dict(build(None), request_id="evo_001")
        self.assertFalse(validate(rejected)["valid"])

    def test_validation_never_raises_or_executes(self):
        class Boom:
            def __getitem__(self, _):
                raise RuntimeError

        v = validate(Boom())
        self.assertFalse(v["valid"])
        self.assertIs(v["execution_allowed"], False)
        self.assertIs(v["executed"], False)


class StaticSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MODULE_PATH, encoding="utf-8") as handle:
            cls.source = handle.read()
        cls.tree = ast.parse(cls.source)

    def test_only_the_902_module_is_imported(self):
        imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imports += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
        self.assertEqual(imports, ["autonomy.claude_exit_readiness"])

    def test_no_forbidden_calls_or_names(self):
        forbidden = {"open", "exec", "eval", "compile", "__import__", "input", "print",
                     "setattr", "delattr", "globals", "system", "popen", "Popen", "socket",
                     "urlopen", "request", "write", "remove", "rename", "mkdir"}
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        self.assertEqual((names | attrs) & forbidden, set())

    def test_no_global_mutable_state_or_io_keywords(self):
        for node in ast.walk(self.tree):
            self.assertNotIsInstance(node, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef,
                                            ast.Await, ast.Yield))
        for word in ("subprocess", "socket", "urllib", "requests", "anthropic", "openai",
                     "pathlib", "os.", "sys.", "threading"):
            self.assertNotIn("import " + word.strip("."), self.source)

    def test_public_functions_exactly(self):
        public = [n.name for n in self.tree.body
                  if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual(public, ["build_internal_next_stage", "validate_internal_next_stage"])

    def test_doc_exists_and_states_non_permission(self):
        with open(DOC, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("ready_for_internal_stage", text)
        self.assertIn("NOT", text)


if __name__ == "__main__":
    unittest.main()
