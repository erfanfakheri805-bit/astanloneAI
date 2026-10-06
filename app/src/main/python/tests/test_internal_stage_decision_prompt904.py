"""
Prompt 904 - Section 18: controlled internal stage decision.

Deterministic tests of autonomy/internal_stage_decision.py. "stage_ready" is a descriptive
planning/readiness decision only; it is not implementation, execution or approval.

Run (from app/src/main/python/):
    python -m unittest tests.test_internal_stage_decision_prompt904 -v
"""

import ast
import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autonomy import internal_stage_decision as mod
from autonomy.internal_next_stage import build_internal_next_stage as build903
from autonomy.internal_stage_decision import (
    DECISION, RESULT_KEYS, STATUSES,
    build_internal_stage_decision as build, validate_internal_stage_decision as validate)
from tests.test_claude_exit_readiness_prompt902 import run as run902

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "internal_stage_decision.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "internal_stage_decision_prompt904.md")
IDENTITY = ("request_id", "implementation_request_id", "capability_name", "operation")
FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started", "executed")


def ready(op="create"):
    return build903(run902(op))


def edited(op="create", **fields):
    return dict(ready(op), **fields)


def assert_rejected(test, result, status):
    test.assertEqual(result["status"], status)
    test.assertIs(result["valid"], False)
    test.assertIsNone(result["decision"])
    test.assertIsNone(result["next_stage"])
    for key in IDENTITY:
        test.assertIsNone(result[key])
    test.assertEqual(result["reason"], status)
    for flag in FLAGS:
        test.assertIs(result[flag], False)
    test.assertTrue(validate(result)["valid"])


class ValidPathTests(unittest.TestCase):
    def test_valid_create_decision(self):
        r = build(ready("create"))
        self.assertEqual(r["status"], "stage_ready")
        self.assertIs(r["valid"], True)
        self.assertEqual(r["operation"], "create")

    def test_valid_improve_decision(self):
        r = build(ready("improve"))
        self.assertEqual(r["status"], "stage_ready")
        self.assertEqual(r["operation"], "improve")

    def test_decision_value(self):
        for op in ("create", "improve"):
            self.assertEqual(build(ready(op))["decision"], "proceed_to_controlled_internal_stage")
        self.assertEqual(DECISION, "proceed_to_controlled_internal_stage")

    def test_next_stage_carried(self):
        self.assertEqual(build(ready())["next_stage"], "controlled_internal_evolution")

    def test_exact_fourteen_keys_in_order(self):
        self.assertEqual(len(RESULT_KEYS), 14)
        for op in ("create", "improve"):
            self.assertEqual(list(build(ready(op))), list(RESULT_KEYS))

    def test_identity_copied(self):
        src = ready()
        r = build(src)
        self.assertEqual({k: r[k] for k in IDENTITY}, {k: src[k] for k in IDENTITY})

    def test_ready_is_not_permission(self):
        r = build(ready())
        for flag in FLAGS:
            self.assertIs(r[flag], False)

    def test_status_vocabulary(self):
        self.assertEqual(STATUSES, ("stage_ready", "not_ready", "invalid_next_stage",
                                    "context_mismatch", "forbidden_execution_state",
                                    "validation_error"))

    def test_matching_expected_identity_ok(self):
        src = ready()
        exp = {k: src[k] for k in IDENTITY}
        self.assertEqual(build(src, exp)["status"], "stage_ready")
        self.assertEqual(build(src, {"operation": "create"})["status"], "stage_ready")
        self.assertEqual(build(src, {})["status"], "stage_ready")

    def test_input_not_mutated_and_fresh_result(self):
        src = ready()
        before = copy.deepcopy(src)
        a, b = build(src), build(src)
        self.assertEqual(src, before)
        self.assertIsNot(a, b)
        a["status"] = "x"
        self.assertEqual(build(src)["status"], "stage_ready")


class ValidationOfValidResultTests(unittest.TestCase):
    def test_valid_results_validate(self):
        for op in ("create", "improve"):
            v = validate(build(ready(op)))
            self.assertTrue(v["valid"])
            self.assertEqual(v["errors"], [])
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)


class InvalidNextStageTests(unittest.TestCase):
    def test_non_dict_inputs(self):
        for bad in (None, "x", 5, [], (), set(), object(), b"x"):
            assert_rejected(self, build(bad), "invalid_next_stage")

    def test_wrong_next_stage(self):
        for value in ("other_stage", "", None, 5, "Controlled_Internal_Evolution"):
            assert_rejected(self, build(edited(next_stage=value)), "invalid_next_stage")

    def test_forged_ready_with_invalid_identity(self):
        for field, value in (("operation", "delete"), ("capability_name", ""),
                             ("request_id", 5), ("implementation_request_id", None)):
            assert_rejected(self, build(edited(**{field: value})), "invalid_next_stage")

    def test_forged_status_valid_reason(self):
        for field, value in (("status", "approved"), ("valid", False), ("reason", "x"),
                             ("version", 2), ("valid", 1)):
            assert_rejected(self, build(edited(**{field: value})), "invalid_next_stage")

    def test_missing_or_extra_keys(self):
        src = ready()
        for key in list(src):
            d = dict(src)
            del d[key]
            assert_rejected(self, build(d), "invalid_next_stage")
        assert_rejected(self, build(dict(src, extra=1)), "invalid_next_stage")

    def test_forged_valid_true_on_not_ready(self):
        forged = dict(build903(None), valid=True)
        assert_rejected(self, build(forged), "invalid_next_stage")

    def test_not_ready_for_valid_non_ready_903(self):
        for src in (build903(None), build903(dict(run902("create"), status="x"))):
            assert_rejected(self, build(src), "not_ready")


class ContextMismatchTests(unittest.TestCase):
    def test_identity_mismatch_each_field(self):
        src = ready()
        for key in IDENTITY:
            other = "improve" if key == "operation" and src[key] == "create" else "zzz"
            assert_rejected(self, build(src, {key: other}), "context_mismatch")

    def test_type_mismatch(self):
        assert_rejected(self, build(ready(), {"request_id": 1}), "context_mismatch")

    def test_malformed_expected_identity(self):
        for bad in ("x", 5, [], ("a",), {"unknown": 1}, {1: "a"}):
            assert_rejected(self, build(ready(), bad), "context_mismatch")

    def test_mismatch_not_masked_by_invalid_source(self):
        assert_rejected(self, build(None, {"request_id": "zzz"}), "invalid_next_stage")


class ForbiddenStateTests(unittest.TestCase):
    def test_each_permission_flag_true(self):
        for flag in ("implementation_allowed", "execution_allowed"):
            assert_rejected(self, build(edited(**{flag: True})), "forbidden_execution_state")

    def test_implementation_started_true(self):
        assert_rejected(self, build(edited(implementation_started=True)),
                        "forbidden_execution_state")

    def test_executed_true(self):
        assert_rejected(self, build(edited(executed=True)), "forbidden_execution_state")

    def test_truthy_non_bool_flag(self):
        assert_rejected(self, build(edited(executed=1)), "forbidden_execution_state")

    def test_nested_flag(self):
        assert_rejected(self, build(edited(extra={"deep": [{"execution_allowed": True}]})),
                        "forbidden_execution_state")

    def test_approval_authorization_states(self):
        for key in ("approved", "approval_granted", "authorized", "permission_granted"):
            assert_rejected(self, build(edited(**{key: True})), "forbidden_execution_state")

    def test_forbidden_beats_context_mismatch(self):
        assert_rejected(self, build(edited(executed=True), {"request_id": "zzz"}),
                        "forbidden_execution_state")

    def test_flag_false_on_extra_key_is_just_invalid(self):
        assert_rejected(self, build(edited(approved=False)), "invalid_next_stage")


class MalformedAndForgedResultValidationTests(unittest.TestCase):
    def test_non_dict(self):
        for bad in (None, "x", 1, [], object()):
            self.assertFalse(validate(bad)["valid"])

    def test_missing_and_unexpected_keys(self):
        base = build(ready())
        d = dict(base)
        del d["decision"]
        self.assertFalse(validate(d)["valid"])
        self.assertFalse(validate(dict(base, extra=1))["valid"])

    def test_flag_true_in_result(self):
        base = build(ready())
        for flag in FLAGS:
            v = validate(dict(base, **{flag: True}))
            self.assertFalse(v["valid"], flag)
            self.assertIs(v["execution_allowed"], False)

    def test_forged_decision_on_rejected(self):
        self.assertFalse(validate(dict(build(None), decision=DECISION))["valid"])
        self.assertFalse(validate(dict(build(ready()), decision=None))["valid"])
        self.assertFalse(validate(dict(build(ready()), decision="proceed"))["valid"])

    def test_forged_next_stage(self):
        self.assertFalse(validate(dict(build(ready()), next_stage="x"))["valid"])
        self.assertFalse(validate(dict(build(None), next_stage="controlled_internal_evolution"))["valid"])

    def test_valid_field_not_trusted(self):
        # status says rejected but valid claims True, and vice versa
        self.assertFalse(validate(dict(build(None), valid=True))["valid"])
        self.assertFalse(validate(dict(build(ready()), valid=False))["valid"])
        self.assertFalse(validate(dict(build(ready()), status="not_ready"))["valid"])

    def test_bad_version_status_reason(self):
        base = build(ready())
        for field, value in (("status", "approved"), ("reason", "x"), ("version", True),
                             ("version", 2)):
            self.assertFalse(validate(dict(base, **{field: value}))["valid"], field)

    def test_identity_rules(self):
        base = build(ready())
        for field, value in (("operation", "delete"), ("capability_name", ""),
                             ("request_id", 5)):
            self.assertFalse(validate(dict(base, **{field: value}))["valid"], field)
        self.assertFalse(validate(dict(build(None), request_id="evo_001"))["valid"])

    def test_validation_never_raises_or_executes(self):
        class Boom:
            def __getitem__(self, _):
                raise RuntimeError

        v = validate(Boom())
        self.assertFalse(v["valid"])
        self.assertIs(v["execution_allowed"], False)
        self.assertIs(v["executed"], False)


class DeterminismTests(unittest.TestCase):
    def test_repeated_output_identical(self):
        outs = [build(ready()) for _ in range(5)]
        self.assertTrue(all(o == outs[0] for o in outs))
        outs = [build(None) for _ in range(3)]
        self.assertTrue(all(o == outs[0] for o in outs))


class StaticSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MODULE_PATH, encoding="utf-8") as handle:
            cls.source = handle.read()
        cls.tree = ast.parse(cls.source)

    def test_only_autonomy_modules_imported(self):
        imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imports += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
        self.assertEqual(imports, ["autonomy.claude_exit_readiness",
                                   "autonomy.internal_next_stage"])

    def test_no_forbidden_calls_or_names(self):
        forbidden = {"open", "exec", "eval", "compile", "__import__", "input", "print",
                     "setattr", "delattr", "globals", "system", "popen", "Popen", "socket",
                     "urlopen", "request", "write", "remove", "rename", "mkdir"}
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        self.assertEqual((names | attrs) & forbidden, set())

    def test_no_global_state_or_io_imports(self):
        for node in ast.walk(self.tree):
            self.assertNotIsInstance(node, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef,
                                            ast.Await, ast.Yield))
        for word in ("subprocess", "socket", "urllib", "requests", "anthropic", "openai",
                     "pathlib", "os", "sys", "threading"):
            self.assertNotIn("import " + word, self.source)

    def test_public_functions_exactly(self):
        public = [n.name for n in self.tree.body
                  if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual(public, ["build_internal_stage_decision",
                                  "validate_internal_stage_decision"])

    def test_doc_exists_and_states_non_permission(self):
        with open(DOC, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("stage_ready", text)
        self.assertIn("NOT", text)


if __name__ == "__main__":
    unittest.main()
