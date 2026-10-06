"""
Prompt 908 - Section 18: final controlled internal evolution gate.

Deterministic tests of autonomy/final_internal_evolution_gate.py. The gate is descriptive only; it
grants no approval or permission and executes nothing.

Run (from app/src/main/python/):
    python -m unittest tests.test_final_internal_evolution_gate_prompt908 -v
"""

import ast
import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autonomy.final_internal_evolution_gate import (
    GATE, OUTPUT_KEYS, REQUIREMENTS_MET, REQUIREMENTS_MISSING, STATUSES, SUMMARY,
    build_final_internal_evolution_gate as gate)
from autonomy.internal_evolution_input import build_internal_evolution_input as build905
from autonomy.internal_evolution_result import build_internal_evolution_result as build906
from autonomy.internal_evolution_result_validation import (
    validate_internal_evolution_result_context as build907)
from autonomy.internal_next_stage import build_internal_next_stage as build903
from autonomy.internal_stage_decision import build_internal_stage_decision as build904
from tests.test_claude_exit_readiness_prompt902 import run as run902

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "final_internal_evolution_gate.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "final_internal_evolution_gate_prompt908.md")
IDENTITY = ("request_id", "implementation_request_id", "capability_name", "operation")
FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started", "executed")

_CACHE = {}


def good(op="create"):
    if op not in _CACHE:
        _CACHE[op] = build907(build906(build905(build904(build903(run902(op))))))
    return copy.deepcopy(_CACHE[op])


def edited(op="create", **fields):
    return dict(good(op), **fields)


def assert_rejected(test, out, status):
    test.assertEqual(out["status"], status)
    test.assertIs(out["valid"], False)
    for key in IDENTITY + ("stage", "gate", "summary"):
        test.assertIsNone(out[key])
    test.assertEqual(out["requirements_met"], [])
    test.assertEqual(out["requirements_missing"], [])
    for key in FLAGS:
        test.assertIs(out[key], False)


class ValidGateTests(unittest.TestCase):
    def test_valid_create_result(self):
        out = gate(good("create"))
        self.assertEqual(out["status"], "ready_for_final_autonomy_validation")
        self.assertIs(out["valid"], True)

    def test_valid_improve_result(self):
        out = gate(good("improve"))
        self.assertIs(out["valid"], True)
        self.assertEqual(out["operation"], "improve")

    def test_output_fields_exactly(self):
        out = gate(good())
        self.assertEqual(tuple(out), OUTPUT_KEYS)
        self.assertEqual(len(out), 16)
        self.assertEqual(out["version"], 1)

    def test_fixed_valid_values(self):
        out = gate(good())
        self.assertEqual(out["stage"], "controlled_internal_evolution")
        self.assertEqual(out["gate"], "final_internal_evolution_gate")
        self.assertEqual(out["gate"], GATE)
        self.assertEqual(out["summary"], SUMMARY)

    def test_identity_copied(self):
        source = good()
        out = gate(source)
        for key in IDENTITY:
            self.assertEqual(out[key], source[key])

    def test_requirements_met_labels(self):
        out = gate(good())
        self.assertEqual(out["requirements_met"], list(REQUIREMENTS_MET))
        self.assertEqual(len(REQUIREMENTS_MET), 5)

    def test_requirements_missing_labels(self):
        out = gate(good())
        self.assertEqual(out["requirements_missing"],
                         ["implementation_permission", "execution_permission",
                          "final_autonomy_validation"])
        self.assertEqual(out["requirements_missing"], list(REQUIREMENTS_MISSING))

    def test_flags_false_and_not_permission(self):
        out = gate(good())
        for key in FLAGS:
            self.assertIs(out[key], False)
        self.assertNotIn("approved", out)
        self.assertNotIn("authorized", out)

    def test_status_vocabulary(self):
        self.assertEqual(STATUSES, ("ready_for_final_autonomy_validation",
                                    "invalid_validation_result", "context_mismatch",
                                    "forbidden_execution_state", "gate_error"))

    def test_matching_expected_identity(self):
        source = good()
        out = gate(source, {key: source[key] for key in IDENTITY})
        self.assertIs(out["valid"], True)
        self.assertIs(gate(source, {})["valid"], True)
        self.assertIs(gate(source, {"operation": source["operation"]})["valid"], True)

    def test_input_not_mutated_and_fresh_output(self):
        source = good()
        before = copy.deepcopy(source)
        first = gate(source)
        self.assertEqual(source, before)
        first["requirements_met"].append("x")
        first["executed"] = True
        second = gate(source)
        self.assertEqual(second["requirements_met"], list(REQUIREMENTS_MET))
        self.assertIs(second["executed"], False)

    def test_repeated_output_identical(self):
        source = good()
        self.assertEqual(gate(source), gate(copy.deepcopy(source)))


class MalformedAndForgedTests(unittest.TestCase):
    def test_non_dict_inputs(self):
        for bad in (None, [], (), "valid", 7, True, object(), [good()]):
            assert_rejected(self, gate(bad), "invalid_validation_result")

    def test_missing_each_key(self):
        for key in OUTPUT_KEYS_907:
            source = good()
            del source[key]
            assert_rejected(self, gate(source), "invalid_validation_result")

    def test_unexpected_key(self):
        assert_rejected(self, gate(edited(extra="x")), "invalid_validation_result")

    def test_non_string_key(self):
        source = good()
        source[1] = "x"
        assert_rejected(self, gate(source), "invalid_validation_result")

    def test_never_raises(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

        for bad in (Boom(), {"a": object()}, {1: 2}, float("nan")):
            self.assertIn(gate(bad)["status"], ("invalid_validation_result", "gate_error"))

    def test_valid_field_false_on_good_result(self):
        assert_rejected(self, gate(edited(valid=False)), "invalid_validation_result")

    def test_valid_field_forged_true_on_rejected_907_result(self):
        rejected = build907({"nope": 1})
        forged = dict(rejected, valid=True)
        assert_rejected(self, gate(forged), "invalid_validation_result")
        assert_rejected(self, gate(rejected), "invalid_validation_result")

    def test_valid_true_with_invalid_907_status_is_rejected(self):
        for status in ("invalid_result", "context_mismatch", "forbidden_execution_state",
                       "validation_error", "ready", "", None):
            assert_rejected(self, gate(edited(status=status, valid=True)),
                            "invalid_validation_result")

    def test_non_bool_valid_and_version(self):
        for value in (1, "True", None):
            assert_rejected(self, gate(edited(valid=value)), "invalid_validation_result")
        for value in (True, 2, "1", None):
            assert_rejected(self, gate(edited(version=value)), "invalid_validation_result")

    def test_forged_identity_that_907_would_reject(self):
        for key in IDENTITY:
            for value in ("", None, 5, " ", "x" * 500):
                assert_rejected(self, gate(edited(**{key: value})), "invalid_validation_result")

    def test_errors_or_warnings_present(self):
        assert_rejected(self, gate(edited(errors=[{"code": "x", "where": "y"}])),
                        "invalid_validation_result")
        assert_rejected(self, gate(edited(warnings=["w"])), "invalid_validation_result")
        assert_rejected(self, gate(edited(errors=None)), "invalid_validation_result")
        assert_rejected(self, gate(edited(warnings=())), "invalid_validation_result")

    def test_validity_independent_of_valid_field(self):
        source = good()
        source["valid"] = True
        self.assertIs(gate(source)["valid"], True)
        source["request_id"] = "bad;id"
        assert_rejected(self, gate(source), "invalid_validation_result")


class WrongFieldTests(unittest.TestCase):
    def test_wrong_stage(self):
        for stage in ("capability_evolution", "claude_exit", "", None, 3):
            assert_rejected(self, gate(edited(stage=stage)), "invalid_validation_result")

    def test_wrong_status(self):
        for status in ("evaluated", "ready_for_final_autonomy_validation", "VALID", " valid"):
            assert_rejected(self, gate(edited(status=status)), "invalid_validation_result")

    def test_wrong_result_type(self):
        for kind in ("executable_result", "implementation", "", None, ["descriptive_evaluation"]):
            assert_rejected(self, gate(edited(result_type=kind)), "invalid_validation_result")

    def test_gate_style_fields_from_output_are_not_accepted(self):
        forged = dict(good(), gate="final_internal_evolution_gate")
        assert_rejected(self, gate(forged), "invalid_validation_result")
        assert_rejected(self, gate(gate(good())), "invalid_validation_result")

    def test_requirement_tampering(self):
        source = good()
        source["requirements_met"] = list(REQUIREMENTS_MET)
        assert_rejected(self, gate(source), "invalid_validation_result")
        source = good()
        source["requirements_missing"] = []
        assert_rejected(self, gate(source), "invalid_validation_result")


class IdentityContextTests(unittest.TestCase):
    def test_each_identity_field_mismatch(self):
        source = good()
        for key in IDENTITY:
            out = gate(source, {key: source[key] + "_other"})
            assert_rejected(self, out, "context_mismatch")

    def test_type_mismatch_and_malformed_expected(self):
        source = good()
        for expected in ("x", [], 5, {"request_id": 5}, {"unknown": "x"}, {1: "x"}):
            assert_rejected(self, gate(source, expected), "context_mismatch")

    def test_invalid_beats_context(self):
        source = edited(stage="wrong")
        assert_rejected(self, gate(source, {"operation": "other"}), "invalid_validation_result")

    def test_forbidden_beats_context(self):
        source = edited(executed=True)
        assert_rejected(self, gate(source, {"operation": "other"}), "forbidden_execution_state")


class ForbiddenStateTests(unittest.TestCase):
    def test_each_flag_true(self):
        for key in FLAGS:
            assert_rejected(self, gate(edited(**{key: True})), "forbidden_execution_state")

    def test_truthy_non_bool_and_nested(self):
        assert_rejected(self, gate(edited(executed=1)), "forbidden_execution_state")
        assert_rejected(self, gate(edited(errors=[{"execution_allowed": True}])),
                        "forbidden_execution_state")
        assert_rejected(self, gate(edited(warnings=[[{"implementation_started": "yes"}]])),
                        "forbidden_execution_state")

    def test_approval_permission_states(self):
        for key in ("approved", "approval_granted", "authorized", "authorization_granted",
                    "permission_granted", "implementation_approved", "execution_approved"):
            assert_rejected(self, gate(dict(good(), **{key: True})), "forbidden_execution_state")

    def test_forbidden_beats_everything(self):
        source = dict(good(), executed=True, status="invalid_result", valid=False,
                      stage="wrong", extra=1)
        assert_rejected(self, gate(source), "forbidden_execution_state")


class UnsafeContentTests(unittest.TestCase):
    def test_code_like_identity(self):
        for text in ("def run():", "import os", "rm -rf x", "a;b", "a|b", "a&&b", "$(x)",
                     "<x>", "{x}", "a\nb", "`x`", "sudo x", "http_thing", "x://y", "diff --git"):
            for key in IDENTITY:
                assert_rejected(self, gate(edited(**{key: text})), "invalid_validation_result")

    def test_external_service_references(self):
        for text in ("openai", "claude", "anthropic", "gpt", "llm", "api", "network", "cloud",
                     "server", "service", "endpoint", "webhook", "remote", "url", "internet",
                     "socket", "use the API"):
            for key in IDENTITY:
                assert_rejected(self, gate(edited(**{key: text})), "invalid_validation_result")

    def test_external_word_must_be_whole_word(self):
        source = edited(capability_name="rapid_capability")
        out = gate(source)
        # whole-word rule: "rapid" is not "api"; the gate agrees with the 907 identity rules
        self.assertEqual(out["status"] == "ready_for_final_autonomy_validation",
                         build907(_as906(source))["valid"])

    def test_output_has_no_executable_content(self):
        out = gate(good())
        text = " ".join([out["summary"], *out["requirements_met"], *out["requirements_missing"]])
        for marker in ("def ", "import ", "```", "http", "://", "&&", "$(", "{", "}", "api_key"):
            self.assertNotIn(marker, text)


def _as906(result):
    view = {"version": 1, "status": "evaluated", "valid": True}
    view.update({key: result[key] for key in IDENTITY})
    from autonomy.internal_evolution_result import (
        REQUIREMENTS_MET as MET, REQUIREMENTS_MISSING as MISSING, RESULT_TYPE, STAGE,
        SUMMARY as RESULT_SUMMARY)
    view.update(stage=STAGE, result_type=RESULT_TYPE, summary=RESULT_SUMMARY,
                requirements_met=list(MET), requirements_missing=list(MISSING),
                **dict.fromkeys(FLAGS, False))
    return view


OUTPUT_KEYS_907 = ("version", "status", "valid", "request_id", "implementation_request_id",
                   "capability_name", "operation", "stage", "result_type", "errors", "warnings",
                   "implementation_allowed", "execution_allowed", "implementation_started",
                   "executed")


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
                                   "autonomy.internal_evolution_result",
                                   "autonomy.internal_evolution_result_validation"])

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
        self.assertEqual(public, ["build_final_internal_evolution_gate"])

    def test_doc_exists_and_states_descriptive_only(self):
        with open(DOC, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("build_final_internal_evolution_gate", text)
        self.assertIn("NOT", text)
        self.assertIn("ready_for_final_autonomy_validation", text)


if __name__ == "__main__":
    unittest.main()
