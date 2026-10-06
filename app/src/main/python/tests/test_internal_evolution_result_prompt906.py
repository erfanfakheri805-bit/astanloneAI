"""
Prompt 906 - Section 18: internal evolution result contract.

Deterministic tests of autonomy/internal_evolution_result.py. The result only DESCRIBES an
evaluation; "evaluated" does not mean anything was implemented, improved or executed.

Run (from app/src/main/python/):
    python -m unittest tests.test_internal_evolution_result_prompt906 -v
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
    REQUIREMENTS_MET, REQUIREMENTS_MISSING, RESULT_KEYS, RESULT_TYPE, STAGE, STATUSES, SUMMARY,
    build_internal_evolution_result as build, validate_internal_evolution_result as validate)
from autonomy.internal_next_stage import build_internal_next_stage as build903
from autonomy.internal_stage_decision import build_internal_stage_decision as build904
from tests.test_claude_exit_readiness_prompt902 import run as run902

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "internal_evolution_result.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "internal_evolution_result_prompt906.md")
IDENTITY = ("request_id", "implementation_request_id", "capability_name", "operation")
FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started", "executed")

_CACHE = {}


def ready(op="create"):
    if op not in _CACHE:
        _CACHE[op] = build905(build904(build903(run902(op))))
    return copy.deepcopy(_CACHE[op])


def edited(op="create", **fields):
    return dict(ready(op), **fields)


def assert_rejected(test, result, status):
    test.assertEqual(result["status"], status)
    test.assertIs(result["valid"], False)
    for key in IDENTITY + ("stage", "result_type", "summary"):
        test.assertIsNone(result[key])
    test.assertEqual(result["requirements_met"], [])
    test.assertEqual(result["requirements_missing"], [])
    for flag in FLAGS:
        test.assertIs(result[flag], False)
    test.assertTrue(validate(result)["valid"])


class ValidPathTests(unittest.TestCase):
    def test_valid_create_input(self):
        r = build(ready("create"))
        self.assertEqual(r["status"], "evaluated")
        self.assertIs(r["valid"], True)
        self.assertEqual(r["operation"], "create")

    def test_valid_improve_input(self):
        r = build(ready("improve"))
        self.assertEqual(r["status"], "evaluated")
        self.assertEqual(r["operation"], "improve")

    def test_stage_and_result_type(self):
        r = build(ready())
        self.assertEqual(r["stage"], "controlled_internal_evolution")
        self.assertEqual(r["result_type"], "descriptive_evaluation")
        self.assertEqual((STAGE, RESULT_TYPE), ("controlled_internal_evolution",
                                                "descriptive_evaluation"))

    def test_exact_sixteen_keys_in_order(self):
        self.assertEqual(len(RESULT_KEYS), 16)
        for op in ("create", "improve"):
            self.assertEqual(list(build(ready(op))), list(RESULT_KEYS))

    def test_summary_and_requirement_labels(self):
        r = build(ready())
        self.assertEqual(r["summary"], SUMMARY)
        self.assertEqual(r["requirements_met"], list(REQUIREMENTS_MET))
        self.assertEqual(r["requirements_missing"], list(REQUIREMENTS_MISSING))
        self.assertIn("implementation_permission", r["requirements_missing"])
        self.assertIn("execution_permission", r["requirements_missing"])

    def test_summary_says_nothing_was_done(self):
        self.assertIn("nothing was implemented", SUMMARY)

    def test_identity_copied(self):
        src = ready()
        r = build(src)
        self.assertEqual({k: r[k] for k in IDENTITY}, {k: src[k] for k in IDENTITY})

    def test_all_flags_false(self):
        for op in ("create", "improve"):
            r = build(ready(op))
            for flag in FLAGS:
                self.assertIs(r[flag], False)

    def test_status_vocabulary(self):
        self.assertEqual(STATUSES, ("evaluated", "not_ready", "invalid_evolution_input",
                                    "context_mismatch", "forbidden_execution_state",
                                    "validation_error"))

    def test_matching_expected_identity_ok(self):
        src = ready()
        self.assertEqual(build(src, {k: src[k] for k in IDENTITY})["status"], "evaluated")
        self.assertEqual(build(src, {"operation": "create"})["status"], "evaluated")
        self.assertEqual(build(src, {})["status"], "evaluated")

    def test_input_not_mutated_and_fresh_result(self):
        src = ready()
        before = copy.deepcopy(src)
        a = build(src)
        self.assertEqual(src, before)
        a["requirements_met"].append("x")
        a["status"] = "x"
        self.assertEqual(build(src)["requirements_met"], list(REQUIREMENTS_MET))
        self.assertEqual(build(src)["status"], "evaluated")


class ResultValidatorTests(unittest.TestCase):
    def test_valid_results_validate(self):
        for op in ("create", "improve"):
            v = validate(build(ready(op)))
            self.assertTrue(v["valid"])
            self.assertEqual(v["errors"], [])
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)

    def test_non_dict(self):
        for bad in (None, "x", 1, [], object()):
            self.assertFalse(validate(bad)["valid"])

    def test_missing_and_unexpected_keys(self):
        base = build(ready())
        d = dict(base)
        del d["summary"]
        self.assertFalse(validate(d)["valid"])
        self.assertFalse(validate(dict(base, extra=1))["valid"])

    def test_flag_true_in_result(self):
        base = build(ready())
        for flag in FLAGS:
            v = validate(dict(base, **{flag: True}))
            self.assertFalse(v["valid"], flag)
            self.assertIs(v["execution_allowed"], False)

    def test_forged_fields(self):
        base = build(ready())
        for field, value in (("stage", "other"), ("stage", None), ("result_type", "x"),
                             ("result_type", "implementation"), ("summary", "done"),
                             ("summary", SUMMARY + " http://x"), ("summary", None),
                             ("requirements_met", []), ("requirements_met", ["def f(): pass"]),
                             ("requirements_missing", []),
                             ("requirements_missing", list(REQUIREMENTS_MISSING)[:-1]),
                             ("requirements_missing", tuple(REQUIREMENTS_MISSING)),
                             ("status", "approved"), ("version", True), ("version", 2)):
            self.assertFalse(validate(dict(base, **{field: value}))["valid"], field)

    def test_rejected_result_forgeries(self):
        base = build(None)
        for field, value in (("stage", STAGE), ("result_type", RESULT_TYPE), ("summary", SUMMARY),
                             ("requirements_met", list(REQUIREMENTS_MET)),
                             ("request_id", "evo_001"), ("valid", True)):
            self.assertFalse(validate(dict(base, **{field: value}))["valid"], field)

    def test_valid_field_not_trusted(self):
        self.assertFalse(validate(dict(build(ready()), valid=False))["valid"])
        self.assertFalse(validate(dict(build(ready()), status="not_ready"))["valid"])

    def test_identity_rules_and_code_like_identity(self):
        base = build(ready())
        for field, value in (("operation", "delete"), ("capability_name", ""),
                             ("request_id", 5), ("capability_name", "http://x"),
                             ("capability_name", "a; rm -rf x"), ("request_id", "a\nb")):
            self.assertFalse(validate(dict(base, **{field: value}))["valid"], field)

    def test_never_raises_or_executes(self):
        class Boom:
            def __getitem__(self, _):
                raise RuntimeError

        v = validate(Boom())
        self.assertFalse(v["valid"])
        self.assertIs(v["execution_allowed"], False)
        self.assertIs(v["executed"], False)


class InvalidEvolutionInputTests(unittest.TestCase):
    def test_non_dict_inputs(self):
        for bad in (None, "x", 5, [], (), object(), b"x"):
            assert_rejected(self, build(bad), "invalid_evolution_input")

    def test_wrong_stage(self):
        for value in ("other_stage", "", None, 5):
            assert_rejected(self, build(edited(stage=value)), "invalid_evolution_input")

    def test_forged_input_fields(self):
        for field, value in (("status", "approved"), ("valid", False), ("goal", "x"),
                             ("inputs", []), ("outputs", ["x"]), ("constraints", []),
                             ("version", 2)):
            assert_rejected(self, build(edited(**{field: value})), "invalid_evolution_input")

    def test_forged_identity(self):
        for field, value in (("operation", "delete"), ("capability_name", ""),
                             ("request_id", 5)):
            assert_rejected(self, build(edited(**{field: value})), "invalid_evolution_input")

    def test_code_like_identity_rejected(self):
        for value in ("http://x", "a; ls", "x && y", "`id`", "def f"):
            assert_rejected(self, build(edited(capability_name=value)), "invalid_evolution_input")

    def test_missing_or_extra_keys(self):
        src = ready()
        for key in list(src):
            d = dict(src)
            del d[key]
            assert_rejected(self, build(d), "invalid_evolution_input")
        assert_rejected(self, build(dict(src, extra=1)), "invalid_evolution_input")

    def test_prompt_904_result_is_not_a_905_result(self):
        assert_rejected(self, build(build904(build903(run902("create")))),
                        "invalid_evolution_input")

    def test_not_ready_for_valid_rejected_input(self):
        assert_rejected(self, build(build905(None)), "not_ready")


class ContextMismatchTests(unittest.TestCase):
    def test_identity_mismatch_each_field(self):
        src = ready()
        for key in IDENTITY:
            other = "improve" if key == "operation" and src[key] == "create" else "zzz"
            assert_rejected(self, build(src, {key: other}), "context_mismatch")

    def test_type_and_malformed_expected(self):
        assert_rejected(self, build(ready(), {"request_id": 1}), "context_mismatch")
        for bad in ("x", 5, [], ("a",), {"unknown": 1}, {1: "a"}):
            assert_rejected(self, build(ready(), bad), "context_mismatch")

    def test_invalid_source_beats_context(self):
        assert_rejected(self, build(None, {"request_id": "zzz"}), "invalid_evolution_input")


class ForbiddenStateTests(unittest.TestCase):
    def test_each_flag_true(self):
        for flag in FLAGS:
            assert_rejected(self, build(edited(**{flag: True})), "forbidden_execution_state")

    def test_truthy_non_bool_and_nested_flag(self):
        assert_rejected(self, build(edited(executed=1)), "forbidden_execution_state")
        assert_rejected(self, build(edited(extra={"d": [{"execution_allowed": True}]})),
                        "forbidden_execution_state")

    def test_approval_authorization_states(self):
        for key in ("approved", "approval_granted", "authorized", "permission_granted"):
            assert_rejected(self, build(edited(**{key: True})), "forbidden_execution_state")

    def test_forbidden_beats_context_mismatch(self):
        assert_rejected(self, build(edited(executed=True), {"request_id": "zzz"}),
                        "forbidden_execution_state")


class DeterminismTests(unittest.TestCase):
    def test_repeated_output_identical(self):
        outs = [build(ready()) for _ in range(5)]
        self.assertTrue(all(o == outs[0] for o in outs))
        self.assertEqual(json.dumps(build(ready("improve"))), json.dumps(build(ready("improve"))))


class NoExecutableContentTests(unittest.TestCase):
    MARKERS = ("http", "://", "www.", "api_key", "apikey", "secret", "token=", "def ", "class ",
               "import ", "```", "sudo", "rm -", "curl ", "pip install", "diff --git", "@@",
               "#!/", "exec(", "eval(", "subprocess")

    def test_result_has_no_code_patch_command_key_or_url(self):
        text = json.dumps([build(ready("create")), build(ready("improve"))]).lower()
        for marker in self.MARKERS:
            self.assertNotIn(marker, text, marker)

    def test_labels_are_plain(self):
        for label in REQUIREMENTS_MET + REQUIREMENTS_MISSING:
            self.assertRegex(label, r"^[a-z_]+$")
        self.assertRegex(SUMMARY, r"^[A-Za-z ,.;]+$")


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
                                   "autonomy.internal_evolution_input"])

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
        self.assertEqual(public, ["build_internal_evolution_result",
                                  "validate_internal_evolution_result"])

    def test_doc_exists_and_states_descriptive_only(self):
        with open(DOC, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("descriptive_evaluation", text)
        self.assertIn("NOT", text)


if __name__ == "__main__":
    unittest.main()
