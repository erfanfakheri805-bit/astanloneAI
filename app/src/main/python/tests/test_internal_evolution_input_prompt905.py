"""
Prompt 905 - Section 18: internal evolution input contract.

Deterministic tests of autonomy/internal_evolution_input.py. The result only DESCRIBES what the
controlled_internal_evolution stage would receive; it is not implementation, execution or approval.

Run (from app/src/main/python/):
    python -m unittest tests.test_internal_evolution_input_prompt905 -v
"""

import ast
import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autonomy.internal_evolution_input import (
    CONSTRAINTS, GOAL, INPUTS, OUTPUTS, RESULT_KEYS, STAGE, STATUSES,
    build_internal_evolution_input as build, validate_internal_evolution_input as validate)
from autonomy.internal_next_stage import build_internal_next_stage as build903
from autonomy.internal_stage_decision import build_internal_stage_decision as build904
from tests.test_claude_exit_readiness_prompt902 import run as run902

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "internal_evolution_input.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "internal_evolution_input_prompt905.md")
IDENTITY = ("request_id", "implementation_request_id", "capability_name", "operation")
FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started", "executed")

_CACHE = {}


def ready(op="create"):
    if op not in _CACHE:
        _CACHE[op] = build904(build903(run902(op)))
    return copy.deepcopy(_CACHE[op])


def edited(op="create", **fields):
    return dict(ready(op), **fields)


def assert_rejected(test, result, status):
    test.assertEqual(result["status"], status)
    test.assertIs(result["valid"], False)
    test.assertIsNone(result["stage"])
    test.assertIsNone(result["goal"])
    for key in IDENTITY:
        test.assertIsNone(result[key])
    for key in ("inputs", "outputs", "constraints"):
        test.assertEqual(result[key], [])
    for flag in FLAGS:
        test.assertIs(result[flag], False)
    test.assertTrue(validate(result)["valid"])


class ValidPathTests(unittest.TestCase):
    def test_valid_create_input(self):
        r = build(ready("create"))
        self.assertEqual(r["status"], "ready")
        self.assertIs(r["valid"], True)
        self.assertEqual(r["operation"], "create")

    def test_valid_improve_input(self):
        r = build(ready("improve"))
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["operation"], "improve")

    def test_stage_and_goal(self):
        r = build(ready())
        self.assertEqual(r["stage"], "controlled_internal_evolution")
        self.assertEqual(r["goal"], GOAL)
        self.assertIn("evolution", GOAL)

    def test_exact_sixteen_keys_in_order(self):
        self.assertEqual(len(RESULT_KEYS), 16)
        for op in ("create", "improve"):
            self.assertEqual(list(build(ready(op))), list(RESULT_KEYS))

    def test_inputs_outputs_constraints_described(self):
        r = build(ready())
        self.assertEqual(r["inputs"], list(INPUTS))
        self.assertEqual(r["outputs"], list(OUTPUTS))
        self.assertEqual(r["constraints"], list(CONSTRAINTS))
        self.assertIn("validated_capability_context", r["inputs"])
        self.assertIn("future_evolution_result_description", r["outputs"])

    def test_constraints_preserve_required_rules(self):
        c = build(ready())["constraints"]
        for rule in ("no_automatic_execution", "no_automatic_self_modification",
                     "no_external_ai_dependency", "controlled_validation_required"):
            self.assertIn(rule, c)

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
        self.assertEqual(STATUSES, ("ready", "not_ready", "invalid_stage_decision",
                                    "context_mismatch", "forbidden_execution_state",
                                    "validation_error"))

    def test_matching_expected_identity_ok(self):
        src = ready()
        self.assertEqual(build(src, {k: src[k] for k in IDENTITY})["status"], "ready")
        self.assertEqual(build(src, {"operation": "create"})["status"], "ready")
        self.assertEqual(build(src, {})["status"], "ready")

    def test_input_not_mutated_and_fresh_result(self):
        src = ready()
        before = copy.deepcopy(src)
        a, b = build(src), build(src)
        self.assertEqual(src, before)
        self.assertIsNot(a["inputs"], b["inputs"])
        a["inputs"].append("x")
        a["status"] = "x"
        self.assertEqual(build(src)["inputs"], list(INPUTS))
        self.assertEqual(build(src)["status"], "ready")


class ValidResultValidationTests(unittest.TestCase):
    def test_valid_results_validate(self):
        for op in ("create", "improve"):
            v = validate(build(ready(op)))
            self.assertTrue(v["valid"])
            self.assertEqual(v["errors"], [])
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)


class InvalidStageDecisionTests(unittest.TestCase):
    def test_non_dict_inputs(self):
        for bad in (None, "x", 5, [], (), object(), b"x"):
            assert_rejected(self, build(bad), "invalid_stage_decision")

    def test_wrong_stage(self):
        for value in ("other_stage", "", None, 5):
            assert_rejected(self, build(edited(next_stage=value)), "invalid_stage_decision")

    def test_forged_decision_fields(self):
        for field, value in (("decision", "proceed"), ("decision", None), ("status", "approved"),
                             ("valid", False), ("reason", "x"), ("version", 2)):
            assert_rejected(self, build(edited(**{field: value})), "invalid_stage_decision")

    def test_forged_identity(self):
        for field, value in (("operation", "delete"), ("capability_name", ""),
                             ("request_id", 5)):
            assert_rejected(self, build(edited(**{field: value})), "invalid_stage_decision")

    def test_forged_valid_on_rejected_decision(self):
        assert_rejected(self, build(dict(build904(None), valid=True)), "invalid_stage_decision")

    def test_missing_or_extra_keys(self):
        src = ready()
        for key in list(src):
            d = dict(src)
            del d[key]
            assert_rejected(self, build(d), "invalid_stage_decision")
        assert_rejected(self, build(dict(src, extra=1)), "invalid_stage_decision")

    def test_prompt_903_result_is_not_a_904_result(self):
        assert_rejected(self, build(build903(run902("create"))), "invalid_stage_decision")

    def test_not_ready_for_valid_rejected_decision(self):
        assert_rejected(self, build(build904(None)), "not_ready")
        assert_rejected(self, build(build904(ready(), {"operation": "improve"})), "not_ready")


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

    def test_invalid_source_beats_context(self):
        assert_rejected(self, build(None, {"request_id": "zzz"}), "invalid_stage_decision")


class ForbiddenStateTests(unittest.TestCase):
    def test_each_flag_true(self):
        for flag in FLAGS:
            assert_rejected(self, build(edited(**{flag: True})), "forbidden_execution_state")

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


class ResultValidationTests(unittest.TestCase):
    def test_non_dict(self):
        for bad in (None, "x", 1, [], object()):
            self.assertFalse(validate(bad)["valid"])

    def test_missing_and_unexpected_keys(self):
        base = build(ready())
        d = dict(base)
        del d["goal"]
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
        for field, value in (("stage", "other"), ("stage", None), ("goal", "x"), ("goal", None),
                             ("inputs", []), ("inputs", list(INPUTS) + ["x"]),
                             ("outputs", ["def f(): pass"]), ("constraints", []),
                             ("constraints", list(CONSTRAINTS)[:-1]),
                             ("constraints", tuple(CONSTRAINTS)), ("status", "approved"),
                             ("version", True), ("version", 2)):
            self.assertFalse(validate(dict(base, **{field: value}))["valid"], field)

    def test_rejected_result_forgeries(self):
        base = build(None)
        for field, value in (("stage", STAGE), ("goal", GOAL), ("inputs", list(INPUTS)),
                             ("request_id", "evo_001"), ("valid", True)):
            self.assertFalse(validate(dict(base, **{field: value}))["valid"], field)

    def test_valid_field_not_trusted(self):
        self.assertFalse(validate(dict(build(ready()), valid=False))["valid"])
        self.assertFalse(validate(dict(build(ready()), status="not_ready"))["valid"])

    def test_identity_rules(self):
        base = build(ready())
        for field, value in (("operation", "delete"), ("capability_name", ""),
                             ("request_id", 5)):
            self.assertFalse(validate(dict(base, **{field: value}))["valid"], field)

    def test_never_raises_or_executes(self):
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
        self.assertEqual(json.dumps(build(ready("improve"))), json.dumps(build(ready("improve"))))


class NoExecutableContentTests(unittest.TestCase):
    MARKERS = ("http", "://", "www.", "api_key", "apikey", "secret", "token=", "def ", "class ",
               "import ", "```", "sudo", "rm -", "curl ", "pip install", "diff --git", "@@",
               "#!/", "exec(", "eval(", "subprocess")

    def test_result_has_no_code_patch_command_key_or_url(self):
        text = json.dumps([build(ready("create")), build(ready("improve"))]).lower()
        for marker in self.MARKERS:
            self.assertNotIn(marker, text, marker)

    def test_descriptive_lists_are_plain_labels(self):
        for label in INPUTS + OUTPUTS + CONSTRAINTS + (GOAL,):
            self.assertRegex(label, r"^[a-z_]+$")


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
                                   "autonomy.internal_stage_decision",
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
        self.assertEqual(public, ["build_internal_evolution_input",
                                  "validate_internal_evolution_input"])

    def test_doc_exists_and_states_descriptive_only(self):
        with open(DOC, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("controlled_internal_evolution", text)
        self.assertIn("NOT", text)


if __name__ == "__main__":
    unittest.main()
