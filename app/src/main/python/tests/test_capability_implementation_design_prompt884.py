"""
Prompt 884 - capability implementation design focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_implementation_design_prompt884 -v
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_implementation_design as design_module
from capabilities.capability_definition_candidate import (
    build_capability_definition_candidate as build_candidate)
from capabilities.capability_definition_readiness import (
    evaluate_capability_definition_readiness as evaluate_readiness)
from capabilities.capability_evolution_analysis import analyze_capability_evolution as analyze
from capabilities.capability_evolution_plan import build_capability_evolution_plan as build_plan
from capabilities.capability_evolution_proposal import (
    build_capability_evolution_proposal as build_proposal)
from capabilities.capability_evolution_specification import (
    build_capability_evolution_specification as build_spec)
from capabilities.capability_implementation_design import (
    build_capability_implementation_design as build,
    validate_capability_implementation_design as validate)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["version", "design_id", "request_id", "operation", "capability_name", "purpose",
        "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
        "plan_id", "proposal_id", "candidate_id", "design_type", "implementation_ready",
        "execution_allowed"]
BUILD_KEYS = ["status", "design", "execution_allowed", "executed"]


def req(**over):
    d = {"version": "1", "request_id": "evo_001", "operation": "create",
         "capability_name": "text_summarizer", "goal": "Summarize short documents.",
         "inputs": ["z_input", "a_input"], "outputs": ["z_out", "a_out"],
         "constraints": ["Second.", "First.", "Second."], "requested_by": "developer",
         "execution_allowed": False}
    d.update(over)
    return d


def desc(name="text_summarizer", **over):
    d = {"name": name, "version": 1, "purpose": "Summarize text.", "inputs": ["document_text"],
         "outputs": ["summary_text"], "constraints": ["Pure Python only."], "enabled": True}
    d.update(over)
    return d


def seven(op="create", caps=None, plan_id="plan_001", proposal_id="prop_001",
          candidate_id="cand_001", **req_over):
    """[request, analysis, spec, plan, proposal, candidate, readiness] - consistent chain."""
    if caps is None:
        caps = [desc()] if op == "improve" else []
    request = req(operation=op, **req_over)
    analysis = analyze(request, caps)
    spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
    plan = build_plan(request, analysis, spec, plan_id)["plan"]
    proposal = build_proposal(request, analysis, spec, plan, proposal_id)["proposal"]
    candidate = build_candidate(request, analysis, spec, plan, proposal, candidate_id)["candidate"]
    readiness = evaluate_readiness(request, analysis, spec, plan, proposal, candidate)
    return [request, analysis, spec, plan, proposal, candidate, readiness]


def swap(base, other, *indexes):
    out = list(base)
    for i in indexes:
        out[i] = other[i]
    return out


def bd(chain, design_id="design_001"):
    return build(*chain, design_id=design_id)


def make(op="create"):
    return bd(seven(op))["design"]


def codes(result):
    return [e["code"] for e in result["errors"]]


class BuildValidTests(unittest.TestCase):
    def test_create_design(self):
        r = bd(seven("create"))
        self.assertEqual(r["status"], "ready")
        d = r["design"]
        self.assertEqual(sorted(d), sorted(KEYS))
        self.assertEqual((d["operation"], d["analysis_status"], d["design_type"]),
                         ("create", "create_required", "create_implementation"))
        self.assertIsNone(d["existing_capability"])
        self.assertTrue(validate(d)["valid"])

    def test_improve_design(self):
        d = make("improve")
        self.assertEqual((d["operation"], d["analysis_status"], d["design_type"]),
                         ("improve", "improve_required", "improve_implementation"))
        self.assertEqual(d["existing_capability"], desc())
        self.assertTrue(validate(d)["valid"])

    def test_caller_supplied_design_id(self):
        for did in ("design_001", "D-9", "a" * 64):
            self.assertEqual(bd(seven(), did)["design"]["design_id"], did)

    def test_exact_preservation(self):
        d = make("create")
        self.assertEqual(d["version"], 1)
        self.assertIs(type(d["version"]), int)
        self.assertEqual(d["request_id"], "evo_001")
        self.assertEqual(d["capability_name"], "text_summarizer")
        self.assertEqual(d["purpose"], "Summarize short documents.")
        self.assertEqual(d["inputs"], ["z_input", "a_input"])
        self.assertEqual(d["outputs"], ["z_out", "a_out"])
        self.assertEqual(d["constraints"], ["Second.", "First.", "Second."])

    def test_ids_preserved(self):
        d = bd(seven(plan_id="my_plan", proposal_id="my_prop", candidate_id="my_cand"))["design"]
        self.assertEqual((d["plan_id"], d["proposal_id"], d["candidate_id"]),
                         ("my_plan", "my_prop", "my_cand"))

    def test_flags_always_false(self):
        for op in ("create", "improve"):
            d = make(op)
            self.assertIs(d["implementation_ready"], False)
            self.assertIs(d["execution_allowed"], False)

    def test_result_shape_and_flags(self):
        for r in (bd(seven()), build(None, None, None, None, None, None, None)):
            self.assertEqual(sorted(r), sorted(BUILD_KEYS))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)
        self.assertIsNone(build()["design"])

    def test_design_is_detached_from_inputs(self):
        chain = seven("improve")
        d = bd(chain)["design"]
        d["inputs"].append("x")
        d["existing_capability"]["name"] = "changed"
        self.assertEqual(chain[0]["inputs"], ["z_input", "a_input"])
        self.assertEqual(chain[1]["existing"]["name"], "text_summarizer")


class InvalidObjectTests(unittest.TestCase):
    def status(self, index, bad):
        chain = seven()
        chain[index] = bad
        r = bd(chain)
        self.assertIsNone(r["design"])
        return r["status"]

    def test_invalid_request(self):
        for bad in (None, {}, dict(req(), goal=5)):
            self.assertEqual(self.status(0, bad), "invalid_request")

    def test_invalid_analysis(self):
        self.assertEqual(self.status(1, {"status": "create_required"}), "invalid_analysis")

    def test_invalid_specification(self):
        chain = seven()
        self.assertEqual(self.status(2, dict(chain[2], specification_id="")),
                         "invalid_specification")

    def test_invalid_validation_context(self):
        with mock.patch.object(design_module, "validate_capability_evolution",
                               return_value={"bogus": 1}):
            r = bd(seven())
        self.assertEqual(r["status"], "invalid_validation")
        self.assertIsNone(r["design"])

    def test_invalid_plan(self):
        chain = seven()
        self.assertEqual(self.status(3, dict(chain[3], plan_id="bad\nid")), "invalid_plan")
        self.assertEqual(self.status(3, None), "invalid_plan")

    def test_invalid_proposal(self):
        chain = seven()
        self.assertEqual(self.status(4, dict(chain[4], proposal_type="x")), "invalid_proposal")

    def test_invalid_candidate(self):
        chain = seven()
        self.assertEqual(self.status(5, {"version": "1"}), "invalid_candidate")
        self.assertEqual(self.status(5, None), "invalid_candidate")
        self.assertEqual(self.status(5, dict(chain[5], extra=1)), "invalid_candidate")
        self.assertEqual(self.status(5, dict(chain[5], candidate_id="x" * 99)),
                         "invalid_candidate")

    def test_candidate_implementation_ready_or_execution_true(self):
        chain = seven()
        self.assertEqual(self.status(5, dict(chain[5], implementation_ready=True)),
                         "invalid_candidate")
        self.assertEqual(self.status(5, dict(chain[5], execution_allowed=True)),
                         "invalid_candidate")

    def test_invalid_readiness(self):
        chain = seven()
        for bad in (None, {}, "x", dict(chain[6], extra=1), dict(chain[6], version="2"),
                    dict(chain[6], execution_allowed=True), dict(chain[6], ready=False),
                    dict(chain[6], reason="because")):
            self.assertEqual(self.status(6, bad), "invalid_readiness")

    def test_valid_but_not_ready_readiness(self):
        chain = seven()
        not_ready = evaluate_readiness(*swap(chain, seven(request_id="other"), 5)[:6])
        self.assertEqual(not_ready["status"], "context_mismatch")
        self.assertEqual(self.status(6, not_ready), "invalid_readiness")
        invalid = evaluate_readiness(None, None, None, None, None, None)
        self.assertEqual(self.status(6, invalid), "invalid_readiness")

    def test_order_first_failure_wins(self):
        self.assertEqual(build(None, None, None, None, None, None, None,
                               design_id="d")["status"], "invalid_request")
        chain = seven()
        chain[1], chain[4], chain[6] = None, None, None
        self.assertEqual(bd(chain)["status"], "invalid_analysis")
        chain = seven()
        chain[4], chain[5], chain[6] = None, None, None
        self.assertEqual(bd(chain)["status"], "invalid_proposal")
        chain = seven()
        chain[5], chain[6] = None, None
        self.assertEqual(bd(chain)["status"], "invalid_candidate")
        chain = seven()
        chain[6] = None
        self.assertEqual(bd(chain, design_id=None)["status"], "invalid_readiness")


class ContextMismatchTests(unittest.TestCase):
    def assert_mismatch(self, chain):
        r = bd(chain)
        self.assertEqual(r["status"], "context_mismatch")
        self.assertIsNone(r["design"])
        return r

    def test_request_id_mismatch(self):
        other = seven(request_id="evo_002")
        for i in (0, 2, 3, 4, 5, 6):
            self.assert_mismatch(swap(seven(), other, i))

    def test_capability_name_mismatch(self):
        other = seven(capability_name="other_cap")
        for i in (0, 3, 4, 5, 6):
            self.assert_mismatch(swap(seven(), other, i))

    def test_operation_mismatch(self):
        for i in (0, 4, 5, 6):
            self.assert_mismatch(swap(seven("create"), seven("improve"), i))
        self.assert_mismatch(swap(seven("improve"), seven("create"), 6))

    def test_goal_mismatch(self):
        other = seven(goal="A completely different goal.")
        for i in (2, 3, 4, 5):
            self.assert_mismatch(swap(seven(), other, i))

    def test_candidate_purpose_forged(self):
        chain = seven()
        chain[5] = dict(chain[5], purpose="Forged purpose.")
        self.assert_mismatch(chain)

    def test_inputs_mismatch(self):
        other = seven(inputs=["different_input"])
        for i in (2, 3, 4, 5):
            self.assert_mismatch(swap(seven(), other, i))

    def test_outputs_mismatch(self):
        other = seven(outputs=["different_out"])
        for i in (2, 3, 4, 5):
            self.assert_mismatch(swap(seven(), other, i))

    def test_constraints_mismatch(self):
        other = seven(constraints=["Only one."])
        for i in (2, 3, 4, 5):
            self.assert_mismatch(swap(seven(), other, i))
        self.assert_mismatch(swap(seven(), seven(constraints=["First.", "Second.", "Second."]), 5))

    def test_existing_capability_mismatch(self):
        base = seven("improve")
        other = seven("improve", caps=[desc(purpose="A different purpose.")])
        for i in (2, 3, 4, 5):
            self.assert_mismatch(swap(base, other, i))
        chain = seven("improve")
        chain[5] = dict(chain[5], existing_capability=desc(version=2))
        self.assert_mismatch(chain)

    def test_analysis_status_mismatch(self):
        self.assert_mismatch(swap(seven("create"), seven("improve"), 1))
        self.assert_mismatch(swap(seven("improve"), seven("create"), 5))
        self.assert_mismatch(swap(seven("improve"), seven("create"), 2))

    def test_plan_id_mismatch(self):
        base, other = seven(plan_id="plan_001"), seven(plan_id="plan_002")
        for i in (3, 5, 6):
            self.assert_mismatch(swap(base, other, i))

    def test_proposal_id_mismatch(self):
        base, other = seven(proposal_id="prop_001"), seven(proposal_id="prop_002")
        for i in (4, 5, 6):
            self.assert_mismatch(swap(base, other, i))

    def test_candidate_id_is_the_candidates_own_and_forgery_is_caught(self):
        d = bd(seven(candidate_id="cand_777"))["design"]
        self.assertEqual(d["candidate_id"], "cand_777")
        chain = seven()
        chain[5] = dict(chain[5], candidate_id="cand_002", purpose="Forged purpose.")
        self.assert_mismatch(chain)

    def test_candidate_not_derivable_from_chain(self):
        # internally consistent candidate whose list order differs from the request
        chain = seven()
        chain[5] = dict(chain[5], inputs=["a_input", "z_input"])
        self.assert_mismatch(chain)

    def test_forged_but_individually_valid_readiness(self):
        # valid + ready readiness results of OTHER chains
        for other in (seven(request_id="evo_9"), seven(plan_id="plan_9"),
                      seven(proposal_id="prop_9"), seven(capability_name="other_cap"),
                      seven("improve")):
            self.assertEqual(other[6]["status"], "ready")
            self.assert_mismatch(swap(seven(), other, 6))

    def test_forged_readiness_field_edits(self):
        for key, bad in (("request_id", "evo_9"), ("plan_id", "plan_9"),
                         ("proposal_id", "prop_9"), ("capability_name", "other_cap")):
            chain = seven()
            chain[6] = dict(chain[6], **{key: bad})
            self.assertTrue(evaluate_readiness is not None)
            self.assert_mismatch(chain)

    def test_forged_readiness_operation_and_status(self):
        chain = seven("create")
        chain[6] = dict(chain[6], operation="improve", analysis_status="improve_required")
        self.assert_mismatch(chain)

    def test_mismatch_never_copies_untrusted_fields(self):
        r = self.assert_mismatch(swap(seven(), seven(request_id="evo_002"), 5))
        self.assertEqual(sorted(r), sorted(BUILD_KEYS))


class UnsupportedAndDesignIdTests(unittest.TestCase):
    def test_missing_or_invalid_design_id(self):
        for bad in (None, "", " ", "a\nb", "x" * 65, 5, [], {}, True):
            r = bd(seven(), design_id=bad)
            self.assertEqual(r["status"], "invalid_design_id")
            self.assertIsNone(r["design"])
        self.assertEqual(build(*seven())["status"], "invalid_design_id")

    def test_design_id_never_generated(self):
        self.assertIsNone(build(*seven(), design_id=None)["design"])

    def test_improve_or_conflict_never_produces_design(self):
        request = req(operation="create")
        analysis = analyze(request, [desc()])
        self.assertEqual(analysis["status"], "improve_or_conflict")
        base = seven()
        for tail in (base, seven("improve")):
            chain = [request, analysis] + tail[2:]
            r = bd(chain)
            self.assertNotEqual(r["status"], "ready")
            self.assertIsNone(r["design"])

    def test_unsupported_combination_guard(self):
        with mock.patch.object(design_module, "SUPPORTED",
                               (("improve", "improve_required", "improve_capability",
                                 "improve_implementation"),)):
            r = bd(seven("create"))
        self.assertEqual(r["status"], "unsupported_status")
        self.assertIsNone(r["design"])

    def test_design_error_when_built_design_invalid(self):
        with mock.patch.object(design_module, "_design_errors",
                               return_value=[{"code": "x", "where": "y"}]):
            r = bd(seven())
        self.assertEqual(r["status"], "design_error")
        self.assertIsNone(r["design"])

    def test_internal_failure(self):
        with mock.patch.object(design_module, "_chain_mismatch", side_effect=RuntimeError("x")):
            r = bd(seven())
        self.assertEqual(r["status"], "validation_error")
        self.assertIsNone(r["design"])
        self.assertIs(r["execution_allowed"], False)

    def test_ready_only_with_valid_design(self):
        for op in ("create", "improve"):
            r = bd(seven(op))
            self.assertEqual(r["status"], "ready")
            self.assertTrue(validate(r["design"])["valid"])


class DesignValidatorTests(unittest.TestCase):
    def test_valid_designs(self):
        for op in ("create", "improve"):
            self.assertTrue(validate(make(op))["valid"])

    def test_result_shape(self):
        for r in (validate(make()), validate(None)):
            self.assertEqual(sorted(r), sorted(["valid", "errors", "execution_allowed",
                                                "executed"]))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_not_dict(self):
        for bad in (None, [], "x", 3):
            self.assertEqual(codes(validate(bad)), ["design_not_dict"])

    def test_missing_keys(self):
        for key in KEYS:
            d = make()
            del d[key]
            self.assertIn("missing_key", codes(validate(d)))

    def test_extra_keys(self):
        for extra in ("executed", "source_code", "patch"):
            d = make()
            d[extra] = False
            self.assertIn("unexpected_key", codes(validate(d)))

    def test_implementation_ready_must_be_false(self):
        for bad in (True, 1, None, "False", 0):
            d = make()
            d["implementation_ready"] = bad
            self.assertIn("invalid_implementation_ready", codes(validate(d)))

    def test_execution_allowed_must_be_false(self):
        for bad in (True, 1, None, "False", 0):
            d = make()
            d["execution_allowed"] = bad
            self.assertIn("invalid_execution_allowed", codes(validate(d)))

    def test_equivalent_executable_flags_rejected(self):
        for flag in ("executed", "executable", "ready", "install_allowed", "implemented"):
            d = make()
            d[flag] = True
            self.assertFalse(validate(d)["valid"])

    def test_invalid_design_type(self):
        for bad in ("create", "implementation", None, 1, "", "create_implementation "):
            d = make()
            d["design_type"] = bad
            self.assertFalse(validate(d)["valid"])
            self.assertIn("invalid_design_type" if bad in ("create", "implementation", None,
                                                            1, "", "create_implementation ")
                          else "x", codes(validate(d)))

    def test_inconsistent_operation_status_design_type(self):
        d = make("create")
        d["design_type"] = "improve_implementation"
        self.assertIn("inconsistent_design", codes(validate(d)))
        d = make("improve")
        d["design_type"] = "create_implementation"
        self.assertIn("inconsistent_design", codes(validate(d)))
        d = make("create")
        d["operation"] = "improve"
        self.assertFalse(validate(d)["valid"])
        d = make("create")
        d["analysis_status"] = "improve_required"
        self.assertFalse(validate(d)["valid"])

    def test_improve_or_conflict_rejected(self):
        d = make("create")
        d["analysis_status"] = "improve_or_conflict"
        self.assertFalse(validate(d)["valid"])

    def test_invalid_analysis_status(self):
        for bad in ("other", None, 1, ""):
            d = make()
            d["analysis_status"] = bad
            self.assertFalse(validate(d)["valid"])

    def test_invalid_operation(self):
        for bad in ("delete", None, 1, ""):
            d = make()
            d["operation"] = bad
            self.assertFalse(validate(d)["valid"])

    def test_invalid_ids(self):
        for key in ("design_id", "request_id", "plan_id", "proposal_id", "candidate_id"):
            for bad in ("", "a\nb", "x" * 65, None, 5):
                d = make()
                d[key] = bad
                self.assertFalse(validate(d)["valid"], (key, bad))
        d = make()
        d["design_id"] = "x" * 65
        self.assertIn("invalid_design_id", codes(validate(d)))

    def test_invalid_capability_name(self):
        for bad in ("", "Bad\nName", None, 5):
            d = make()
            d["capability_name"] = bad
            self.assertFalse(validate(d)["valid"])

    def test_create_with_existing_capability_rejected(self):
        d = make("create")
        d["existing_capability"] = desc()
        self.assertFalse(validate(d)["valid"])

    def test_improve_existing_capability_rules(self):
        d = make("improve")
        d["existing_capability"] = None
        self.assertFalse(validate(d)["valid"])
        d = make("improve")
        d["existing_capability"] = desc(name="other_cap")
        self.assertFalse(validate(d)["valid"])
        d = make("improve")
        d["existing_capability"] = {"name": "text_summarizer"}
        self.assertFalse(validate(d)["valid"])
        d = make("improve")
        d["existing_capability"] = "x"
        self.assertFalse(validate(d)["valid"])

    def test_invalid_purpose(self):
        for bad in ("", None, 5, ["x"]):
            d = make()
            d["purpose"] = bad
            self.assertFalse(validate(d)["valid"])

    def test_invalid_lists(self):
        for key in ("inputs", "outputs", "constraints"):
            for bad in ("x", None, [1], [""], ("a",), {"a": 1}):
                d = make()
                d[key] = bad
                self.assertFalse(validate(d)["valid"], (key, bad))
        d = make()
        d["outputs"] = []
        self.assertFalse(validate(d)["valid"])

    def test_invalid_version(self):
        for bad in ("2", "1", 2, 0, True, 1.0, None, ""):
            d = make()
            d["version"] = bad
            self.assertFalse(validate(d)["valid"], bad)
            self.assertIn("invalid_version", codes(validate(d)))

    def test_integer_version_one_is_the_only_valid_version(self):
        self.assertTrue(validate(make())["valid"])
        self.assertIs(type(make("improve")["version"]), int)

    def test_validator_read_only_and_never_raises(self):
        d = make("improve")
        snap = copy.deepcopy(d)
        validate(d)
        self.assertEqual(d, snap)
        for weird in ({1: 2}, {k: object() for k in KEYS}, {"version": object()}):
            self.assertFalse(validate(weird)["valid"])
        self.assertLessEqual(len(validate({k: object() for k in KEYS})["errors"]),
                             design_module.MAX_ERRORS)


class SafetyTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for op in ("create", "improve"):
            chain = seven(op)
            snap = copy.deepcopy(chain)
            bd(chain)
            self.assertEqual(chain, snap)
        bad = swap(seven(), seven(request_id="b"), 6)
        snap = copy.deepcopy(bad)
        bd(bad)
        self.assertEqual(bad, snap)

    def test_fresh_results(self):
        chain = seven()
        a, b = bd(chain), bd(chain)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["design"], b["design"])
        a["design"]["inputs"].append("x")
        self.assertEqual(bd(chain)["design"]["inputs"], ["z_input", "a_input"])

    def test_deterministic_repeated_construction(self):
        for chain in (seven(), seven("improve"), swap(seven(), seven(goal="Other."), 3),
                      [None] * 7):
            results = [bd(chain) for _ in range(5)]
            self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(bd(seven("improve")), bd(seven("improve")))

    def test_type_strict_comparison(self):
        self.assertFalse(design_module._same(True, 1))
        self.assertFalse(design_module._same([1], (1,)))
        self.assertTrue(design_module._same({"a": [1, "b"]}, {"a": [1, "b"]}))

    def test_module_has_no_forbidden_imports_or_calls(self):
        path = os.path.join(ROOT, "capabilities", "capability_implementation_design.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        banned = {"os", "sys", "socket", "http", "urllib", "requests", "subprocess", "shutil",
                  "pathlib", "importlib", "sqlite3", "pickle", "json", "random", "time",
                  "datetime", "threading", "ctypes", "builtins", "ael", "memory", "research"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], banned)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 1:
                    self.assertTrue(node.module.startswith("capability_"))
                else:
                    self.assertNotIn((node.module or "").split(".")[0], banned)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__"})

    def test_constants(self):
        self.assertEqual(list(design_module.FIELDS), KEYS)
        self.assertEqual(len(design_module.STATUSES), 14)
        self.assertEqual(design_module.DESIGN_TYPES,
                         ("create_implementation", "improve_implementation"))


if __name__ == "__main__":
    unittest.main()
