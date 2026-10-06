"""
Prompt 907 - Section 18: controlled internal evolution result validation.

Deterministic tests of autonomy/internal_evolution_result_validation.py. Validation is
descriptive only; it grants no approval or permission and executes nothing.

Run (from app/src/main/python/):
    python -m unittest tests.test_internal_evolution_result_validation_prompt907 -v
"""

import ast
import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autonomy.internal_evolution_input import build_internal_evolution_input as build905
from autonomy.internal_evolution_result import (
    REQUIREMENTS_MET, REQUIREMENTS_MISSING, SUMMARY,
    build_internal_evolution_result as build906)
from autonomy.internal_evolution_result_validation import (
    OUTPUT_KEYS, STATUSES, validate_internal_evolution_result_context as check)
from autonomy.internal_next_stage import build_internal_next_stage as build903
from autonomy.internal_stage_decision import build_internal_stage_decision as build904
from tests.test_claude_exit_readiness_prompt902 import run as run902

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "internal_evolution_result_validation.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "internal_evolution_result_validation_prompt907.md")
IDENTITY = ("request_id", "implementation_request_id", "capability_name", "operation")
FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started", "executed")

_CACHE = {}


def good(op="create"):
    if op not in _CACHE:
        _CACHE[op] = build906(build905(build904(build903(run902(op)))))
    return copy.deepcopy(_CACHE[op])


def edited(op="create", **fields):
    return dict(good(op), **fields)


def codes(out):
    return [e["code"] for e in out["errors"]]


def assert_rejected(test, out, status, code=None):
    test.assertEqual(out["status"], status)
    test.assertIs(out["valid"], False)
    for key in IDENTITY + ("stage", "result_type"):
        test.assertIsNone(out[key])
    test.assertTrue(out["errors"])
    test.assertEqual(out["warnings"], [])
    for flag in FLAGS:
        test.assertIs(out[flag], False)
    if code:
        test.assertIn(code, codes(out))


class ValidPathTests(unittest.TestCase):
    def test_valid_create_result(self):
        out = check(good("create"))
        self.assertEqual(out["status"], "valid")
        self.assertIs(out["valid"], True)
        self.assertEqual(out["operation"], "create")

    def test_valid_improve_result(self):
        out = check(good("improve"))
        self.assertEqual(out["status"], "valid")
        self.assertEqual(out["operation"], "improve")

    def test_output_fields(self):
        out = check(good())
        self.assertEqual(list(out), list(OUTPUT_KEYS))
        self.assertEqual(len(OUTPUT_KEYS), 15)
        self.assertEqual(out["stage"], "controlled_internal_evolution")
        self.assertEqual(out["result_type"], "descriptive_evaluation")
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["warnings"], [])
        self.assertIs(type(out["version"]), int)

    def test_identity_copied(self):
        src = good()
        out = check(src)
        self.assertEqual({k: out[k] for k in IDENTITY}, {k: src[k] for k in IDENTITY})

    def test_flags_false_and_not_permission(self):
        for op in ("create", "improve"):
            out = check(good(op))
            for flag in FLAGS:
                self.assertIs(out[flag], False)

    def test_status_vocabulary(self):
        self.assertEqual(STATUSES, ("valid", "invalid_result", "context_mismatch",
                                    "forbidden_execution_state", "validation_error"))

    def test_matching_expected_identity(self):
        src = good()
        self.assertEqual(check(src, {k: src[k] for k in IDENTITY})["status"], "valid")
        self.assertEqual(check(src, {"operation": "create"})["status"], "valid")
        self.assertEqual(check(src, {})["status"], "valid")

    def test_input_not_mutated_and_fresh_output(self):
        src = good()
        before = copy.deepcopy(src)
        a = check(src)
        self.assertEqual(src, before)
        a["errors"].append("x")
        self.assertEqual(check(src)["errors"], [])


class MalformedInputTests(unittest.TestCase):
    def test_non_dict(self):
        for bad in (None, "x", 5, [], (), object(), b"x"):
            assert_rejected(self, check(bad), "invalid_result")

    def test_missing_keys(self):
        src = good()
        for key in list(src):
            d = dict(src)
            del d[key]
            assert_rejected(self, check(d), "invalid_result", "missing_key")

    def test_unexpected_key(self):
        assert_rejected(self, check(dict(good(), extra=1)), "invalid_result", "unexpected_key")

    def test_never_raises(self):
        class Boom:
            def __getitem__(self, _):
                raise RuntimeError

        out = check(Boom())
        self.assertFalse(out["valid"])
        out = check(good(), expected_identity=Boom())
        self.assertEqual(out["status"], "context_mismatch")


class ForgedResultTests(unittest.TestCase):
    def test_valid_field_false_on_good_result(self):
        assert_rejected(self, check(edited(valid=False)), "invalid_result")

    def test_valid_field_true_on_rejected_result(self):
        assert_rejected(self, check(dict(build906(None), valid=True)), "invalid_result")

    def test_valid_field_true_not_enough(self):
        forged = edited(status="not_ready")
        self.assertIs(forged["valid"], True)
        assert_rejected(self, check(forged), "invalid_result")

    def test_not_ready_906_result_is_not_a_valid_evaluation(self):
        assert_rejected(self, check(build906(None)), "invalid_result", "result_not_evaluated")

    def test_status_forged(self):
        for value in ("approved", "implemented", "", None):
            assert_rejected(self, check(edited(status=value)), "invalid_result")

    def test_summary_forged(self):
        for value in ("done", SUMMARY + " Implemented.", "", None, "The capability was executed."):
            assert_rejected(self, check(edited(summary=value)), "invalid_result")

    def test_identity_forged(self):
        for field, value in (("operation", "delete"), ("capability_name", ""),
                             ("request_id", 5), ("implementation_request_id", None)):
            assert_rejected(self, check(edited(**{field: value})), "invalid_result")


class StageAndTypeTests(unittest.TestCase):
    def test_wrong_stage(self):
        for value in ("other_stage", "", None, 5, "Controlled_Internal_Evolution"):
            assert_rejected(self, check(edited(stage=value)), "invalid_result", "invalid_stage")

    def test_wrong_result_type(self):
        for value in ("implementation", "execution_result", "", None, 5):
            assert_rejected(self, check(edited(result_type=value)), "invalid_result",
                            "invalid_result_type")


class RequirementsTests(unittest.TestCase):
    def test_missing_required_met(self):
        for label in REQUIREMENTS_MET:
            met = [m for m in REQUIREMENTS_MET if m != label]
            out = check(edited(requirements_met=met))
            assert_rejected(self, out, "invalid_result", "requirement_missing")

    def test_missing_required_missing_list(self):
        met = list(REQUIREMENTS_MISSING)[:-1]
        assert_rejected(self, check(edited(requirements_missing=met)), "invalid_result",
                        "requirement_missing")

    def test_unexpected_requirement(self):
        out = check(edited(requirements_met=list(REQUIREMENTS_MET) + ["extra_label"]))
        assert_rejected(self, out, "invalid_result", "unexpected_requirement")
        out = check(edited(requirements_missing=list(REQUIREMENTS_MISSING) + ["x"]))
        assert_rejected(self, out, "invalid_result", "unexpected_requirement")

    def test_swapped_and_wrong_types(self):
        out = check(edited(requirements_met=list(REQUIREMENTS_MISSING),
                           requirements_missing=list(REQUIREMENTS_MET)))
        assert_rejected(self, out, "invalid_result")
        for value in (tuple(REQUIREMENTS_MET), None, "x", [1, 2], []):
            assert_rejected(self, check(edited(requirements_met=value)), "invalid_result")


class ContextMismatchTests(unittest.TestCase):
    def test_each_identity_field(self):
        src = good()
        for key in IDENTITY:
            other = "improve" if key == "operation" and src[key] == "create" else "zzz"
            out = check(src, {key: other})
            self.assertEqual(out["status"], "context_mismatch")
            self.assertIs(out["valid"], False)
            self.assertEqual(out["errors"], [{"code": "identity_mismatch", "where": key}])
            for k in IDENTITY:
                self.assertIsNone(out[k])

    def test_type_mismatch_and_malformed_expected(self):
        self.assertEqual(check(good(), {"request_id": 1})["status"], "context_mismatch")
        for bad in ("x", 5, [], ("a",), {"unknown": 1}, {1: "a"}):
            self.assertEqual(check(good(), bad)["status"], "context_mismatch")

    def test_invalid_result_beats_context(self):
        out = check(edited(stage="x"), {"request_id": "zzz"})
        self.assertEqual(out["status"], "invalid_result")


class ForbiddenStateTests(unittest.TestCase):
    def test_each_flag_true(self):
        for flag in FLAGS:
            out = check(edited(**{flag: True}))
            assert_rejected(self, out, "forbidden_execution_state", "forbidden_flag")
            self.assertEqual(out["errors"][0]["where"], flag)

    def test_truthy_non_bool_and_nested(self):
        assert_rejected(self, check(edited(executed=1)), "forbidden_execution_state")
        assert_rejected(self, check(edited(x={"d": [{"execution_allowed": True}]})),
                        "forbidden_execution_state")

    def test_approval_permission_states(self):
        for key in ("approved", "approval_granted", "authorized", "permission_granted",
                    "implementation_approved", "execution_approved"):
            assert_rejected(self, check(edited(**{key: True})), "forbidden_execution_state")

    def test_forbidden_beats_everything(self):
        out = check(edited(executed=True, stage="x"), {"request_id": "zzz"})
        self.assertEqual(out["status"], "forbidden_execution_state")


class UnsafeContentTests(unittest.TestCase):
    def test_code_like_identity(self):
        for value in ("http://x", "a; ls", "x && y", "`id`", "def f", "a\nb", "{x}"):
            assert_rejected(self, check(edited(capability_name=value)), "invalid_result")

    def test_code_like_requirements(self):
        for value in ("import os", "rm -rf x", "```code```", "curl x"):
            met = list(REQUIREMENTS_MET)[:-1] + [value]
            assert_rejected(self, check(edited(requirements_met=met)), "invalid_result",
                            "code_like_content")

    def test_external_service_references(self):
        for value in ("call_the_api", "use openai", "claude_helper", "remote-server",
                      "cloud_service"):
            out = check(edited(capability_name=value))
            assert_rejected(self, out, "invalid_result", "external_reference")

    def test_external_word_must_be_whole_word(self):
        out = check(edited(capability_name="rapid_capability"))
        self.assertEqual(out["status"], "valid")

    def test_external_reference_in_requirements(self):
        met = list(REQUIREMENTS_MET)[:-1] + ["external_ai_service"]
        assert_rejected(self, check(edited(requirements_met=met)), "invalid_result",
                        "external_reference")


class IndependenceAndDeterminismTests(unittest.TestCase):
    def test_validity_independent_of_valid_field(self):
        good_result = good()
        for value in (True, False, None, 1, "yes"):
            out = check(dict(good_result, valid=value))
            self.assertEqual(out["status"] == "valid", value is True, value)

    def test_repeated_output_identical(self):
        outs = [check(good()) for _ in range(5)]
        self.assertTrue(all(o == outs[0] for o in outs))
        self.assertEqual(json.dumps(check(edited(stage="x"))), json.dumps(check(edited(stage="x"))))

    def test_output_has_no_executable_content(self):
        text = json.dumps([check(good("create")), check(good("improve")), check(None)]).lower()
        for marker in ("http", "://", "api_key", "def ", "import ", "```", "sudo", "rm -",
                       "curl ", "diff --git", "exec(", "eval(", "subprocess"):
            self.assertNotIn(marker, text, marker)


class StaticSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MODULE_PATH, encoding="utf-8") as handle:
            cls.source = handle.read()
        cls.tree = ast.parse(cls.source)

    def test_only_expected_imports(self):
        imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imports += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
        self.assertEqual(imports, ["re", "autonomy.claude_exit_readiness",
                                   "autonomy.internal_evolution_result"])

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

    def test_public_function_exactly(self):
        public = [n.name for n in self.tree.body
                  if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual(public, ["validate_internal_evolution_result_context"])

    def test_doc_exists_and_states_descriptive_only(self):
        with open(DOC, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("validate_internal_evolution_result_context", text)
        self.assertIn("NOT", text)


if __name__ == "__main__":
    unittest.main()
