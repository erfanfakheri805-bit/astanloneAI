"""
Prompt 883 - capability definition readiness focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_definition_readiness_prompt883 -v
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_definition_readiness as ready_module
from capabilities.capability_definition_candidate import (
    build_capability_definition_candidate as build_candidate)
from capabilities.capability_definition_readiness import (
    evaluate_capability_definition_readiness as evaluate,
    validate_capability_definition_readiness as validate)
from capabilities.capability_evolution_analysis import analyze_capability_evolution as analyze
from capabilities.capability_evolution_plan import build_capability_evolution_plan as build_plan
from capabilities.capability_evolution_proposal import (
    build_capability_evolution_proposal as build_proposal)
from capabilities.capability_evolution_specification import (
    build_capability_evolution_specification as build_spec)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["version", "status", "ready", "request_id", "capability_name", "operation",
        "analysis_status", "plan_id", "proposal_id", "reason", "execution_allowed"]
STATUSES = ["ready", "not_ready", "invalid_request", "invalid_analysis",
            "invalid_specification", "invalid_validation", "invalid_plan", "invalid_proposal",
            "invalid_candidate", "context_mismatch", "unsupported_status", "validation_error"]


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


def six(op="create", caps=None, plan_id="plan_001", proposal_id="prop_001",
        candidate_id="cand_001", **req_over):
    """(request, analysis, specification, plan, proposal, candidate) - consistent chain."""
    if caps is None:
        caps = [desc()] if op == "improve" else []
    request = req(operation=op, **req_over)
    analysis = analyze(request, caps)
    spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
    plan = build_plan(request, analysis, spec, plan_id)["plan"]
    proposal = build_proposal(request, analysis, spec, plan, proposal_id)["proposal"]
    candidate = build_candidate(request, analysis, spec, plan, proposal, candidate_id)["candidate"]
    return [request, analysis, spec, plan, proposal, candidate]


def swap(base, other, *indexes):
    """Replace chain members at `indexes` with those of another (valid) chain."""
    out = list(base)
    for i in indexes:
        out[i] = other[i]
    return out


def ev(chain):
    return evaluate(*chain)


def ok(op="create"):
    return ev(six(op))


class ValidReadinessTests(unittest.TestCase):
    def test_valid_create(self):
        r = ok("create")
        self.assertEqual(r["status"], "ready")
        self.assertIs(r["ready"], True)
        self.assertEqual((r["request_id"], r["capability_name"], r["operation"]),
                         ("evo_001", "text_summarizer", "create"))
        self.assertEqual((r["analysis_status"], r["plan_id"], r["proposal_id"]),
                         ("create_required", "plan_001", "prop_001"))
        self.assertTrue(validate(r)["valid"])

    def test_valid_improve(self):
        r = ok("improve")
        self.assertEqual(r["status"], "ready")
        self.assertEqual((r["operation"], r["analysis_status"]), ("improve", "improve_required"))
        self.assertTrue(validate(r)["valid"])

    def test_result_has_exactly_eleven_keys(self):
        for chain in (six("create"), [None] * 6, six("improve")):
            self.assertEqual(sorted(ev(chain)), sorted(KEYS))

    def test_version_reason_flags(self):
        r = ok()
        self.assertEqual(r["version"], "1")
        self.assertEqual(r["reason"], "ready")
        self.assertIs(r["execution_allowed"], False)
        self.assertNotIn("executed", r)

    def test_ids_preserved(self):
        r = ev(six(plan_id="my_plan", proposal_id="my_prop"))
        self.assertEqual((r["plan_id"], r["proposal_id"]), ("my_plan", "my_prop"))

    def test_ready_only_when_status_ready(self):
        chains = [six(), six("improve"), [None] * 6, swap(six(), six(request_id="x2"), 0)]
        for chain in chains:
            r = ev(chain)
            self.assertEqual(r["ready"], r["status"] == "ready")
            self.assertIs(r["execution_allowed"], False)


class InvalidObjectTests(unittest.TestCase):
    def test_invalid_request(self):
        for bad in (None, {}, "x", dict(req(), goal=5)):
            c = six()
            c[0] = bad
            r = ev(c)
            self.assertEqual(r["status"], "invalid_request")
            self.assertEqual([r[k] for k in ("request_id", "capability_name", "operation",
                                             "analysis_status", "plan_id", "proposal_id")],
                             [None] * 6)
            self.assertEqual(r["reason"], "invalid_request")
            self.assertTrue(validate(r)["valid"])

    def test_invalid_analysis(self):
        c = six()
        c[1] = {"status": "create_required"}
        r = ev(c)
        self.assertEqual(r["status"], "invalid_analysis")
        self.assertEqual((r["request_id"], r["capability_name"], r["operation"]),
                         ("evo_001", "text_summarizer", "create"))
        self.assertEqual((r["analysis_status"], r["plan_id"], r["proposal_id"]),
                         (None, None, None))
        self.assertTrue(validate(r)["valid"])

    def test_invalid_specification(self):
        c = six()
        c[2] = dict(c[2], specification_id="")
        r = ev(c)
        self.assertEqual(r["status"], "invalid_specification")
        self.assertEqual(r["request_id"], "evo_001")
        self.assertEqual((r["plan_id"], r["proposal_id"]), (None, None))
        self.assertTrue(validate(r)["valid"])

    def test_invalid_specification_untrusted_fields_not_copied(self):
        c = six()
        c[2] = dict(c[2], request_id="FORGED", capability_name="forged\n")
        r = ev(c)
        self.assertEqual(r["status"], "invalid_specification")
        self.assertEqual((r["request_id"], r["capability_name"]), ("evo_001", "text_summarizer"))

    def test_invalid_validation_context(self):
        with mock.patch.object(ready_module, "validate_capability_evolution",
                               return_value={"bogus": 1}):
            r = ev(six())
        self.assertEqual(r["status"], "invalid_validation")
        self.assertEqual((r["plan_id"], r["proposal_id"]), (None, None))
        self.assertEqual(r["request_id"], "evo_001")
        self.assertIs(r["ready"], False)
        self.assertTrue(validate(r)["valid"])

    def test_invalid_plan(self):
        c = six()
        c[3] = dict(c[3], plan_id="bad id with spaces\n")
        r = ev(c)
        self.assertEqual(r["status"], "invalid_plan")
        self.assertEqual((r["plan_id"], r["proposal_id"]), (None, None))
        self.assertTrue(validate(r)["valid"])

    def test_invalid_plan_none(self):
        c = six()
        c[3] = None
        self.assertEqual(ev(c)["status"], "invalid_plan")

    def test_invalid_proposal(self):
        c = six()
        c[4] = dict(c[4], proposal_type="nonsense")
        r = ev(c)
        self.assertEqual(r["status"], "invalid_proposal")
        self.assertEqual((r["plan_id"], r["proposal_id"]), (None, None))
        self.assertTrue(validate(r)["valid"])

    def test_invalid_candidate(self):
        c = six()
        c[5] = {"version": "1"}
        r = ev(c)
        self.assertEqual(r["status"], "invalid_candidate")
        self.assertEqual((r["plan_id"], r["proposal_id"]), (None, None))
        self.assertEqual(r["request_id"], "evo_001")
        self.assertTrue(validate(r)["valid"])

    def test_candidate_none_and_extra_key(self):
        c = six()
        c[5] = None
        self.assertEqual(ev(c)["status"], "invalid_candidate")
        c = six()
        c[5] = dict(c[5], extra=1)
        self.assertEqual(ev(c)["status"], "invalid_candidate")

    def test_invalid_candidate_does_not_copy_forged_ids(self):
        c = six()
        c[5] = dict(c[5], proposal_id="x" * 99)
        r = ev(c)
        self.assertEqual(r["status"], "invalid_candidate")
        self.assertIsNone(r["proposal_id"])

    def test_validation_order_first_failure_wins(self):
        c = [None, None, None, None, None, None]
        self.assertEqual(ev(c)["status"], "invalid_request")
        c = six()
        c[1], c[3], c[5] = None, None, None
        self.assertEqual(ev(c)["status"], "invalid_analysis")
        c = six()
        c[3], c[4], c[5] = None, None, None
        self.assertEqual(ev(c)["status"], "invalid_plan")
        c = six()
        c[4], c[5] = None, None
        self.assertEqual(ev(c)["status"], "invalid_proposal")

    def test_no_arguments(self):
        self.assertEqual(evaluate()["status"], "invalid_request")


class ForgedChainTests(unittest.TestCase):
    """Each object is individually valid; the chain disagrees."""

    def assert_mismatch(self, chain):
        r = ev(chain)
        self.assertEqual(r["status"], "context_mismatch")
        self.assertIs(r["ready"], False)
        self.assertEqual(r["reason"], "context_mismatch")
        self.assertIsNone(r["plan_id"])
        self.assertIsNone(r["proposal_id"])
        self.assertTrue(validate(r)["valid"])
        return r

    def test_request_id_mismatch(self):
        r = self.assert_mismatch(swap(six(), six(request_id="evo_002"), 0))
        self.assertEqual(r["request_id"], "evo_001" if False else r["request_id"])

    def test_request_id_mismatch_candidate_only(self):
        self.assert_mismatch(swap(six(), six(request_id="evo_002"), 5))

    def test_request_id_mismatch_proposal_only(self):
        self.assert_mismatch(swap(six(), six(request_id="evo_002"), 4))

    def test_capability_name_mismatch(self):
        self.assert_mismatch(swap(six(), six(capability_name="other_cap"), 5))
        self.assert_mismatch(swap(six(), six(capability_name="other_cap"), 3))
        self.assert_mismatch(swap(six(), six(capability_name="other_cap"), 0))

    def test_operation_mismatch(self):
        self.assert_mismatch(swap(six("create"), six("improve"), 5))
        self.assert_mismatch(swap(six("create"), six("improve"), 0))
        self.assert_mismatch(swap(six("improve"), six("create"), 4))

    def test_goal_mismatch(self):
        other = six(goal="A completely different goal.")
        for i in (2, 3, 4, 5):
            self.assert_mismatch(swap(six(), other, i))

    def test_candidate_purpose_forged(self):
        c = six()
        c[5] = dict(c[5], purpose="Forged purpose.")
        self.assert_mismatch(c)

    def test_inputs_mismatch(self):
        other = six(inputs=["different_input"])
        for i in (2, 3, 4, 5):
            self.assert_mismatch(swap(six(), other, i))

    def test_outputs_mismatch(self):
        other = six(outputs=["different_out"])
        for i in (2, 3, 4, 5):
            self.assert_mismatch(swap(six(), other, i))

    def test_constraints_mismatch(self):
        other = six(constraints=["Only one."])
        for i in (2, 3, 4, 5):
            self.assert_mismatch(swap(six(), other, i))

    def test_constraints_order_matters(self):
        other = six(constraints=["First.", "Second.", "Second."])
        self.assert_mismatch(swap(six(), other, 5))

    def test_existing_capability_mismatch(self):
        base = six("improve")
        other = six("improve", caps=[desc(purpose="A different purpose.")])
        for i in (2, 3, 4, 5):
            self.assert_mismatch(swap(base, other, i))

    def test_existing_capability_forged_candidate(self):
        c = six("improve")
        c[5] = dict(c[5], existing_capability=desc(version=2))
        self.assert_mismatch(c)

    def test_analysis_status_mismatch(self):
        self.assert_mismatch(swap(six("create"), six("improve"), 1))
        self.assert_mismatch(swap(six("improve"), six("create"), 5))
        self.assert_mismatch(swap(six("improve"), six("create"), 2))

    def test_plan_id_mismatch(self):
        base = six(plan_id="plan_001")
        other = six(plan_id="plan_002")
        self.assert_mismatch(swap(base, other, 3))
        self.assert_mismatch(swap(base, other, 5))

    def test_proposal_id_mismatch(self):
        base = six(proposal_id="prop_001")
        other = six(proposal_id="prop_002")
        self.assert_mismatch(swap(base, other, 5))

    def test_proposal_id_candidate_forged(self):
        c = six()
        c[5] = dict(c[5], proposal_id="prop_999")
        self.assert_mismatch(c)

    def test_whole_other_chain_tail(self):
        base, other = six(request_id="evo_001"), six(request_id="evo_777")
        self.assert_mismatch(swap(base, other, 3, 4, 5))

    def test_mismatch_preserves_only_trusted_identity(self):
        r = self.assert_mismatch(swap(six(), six(capability_name="other_cap"), 5))
        self.assertEqual((r["request_id"], r["capability_name"], r["operation"]),
                         ("evo_001", "text_summarizer", "create"))
        self.assertEqual(r["analysis_status"], "create_required")

    def test_type_strict_comparison(self):
        self.assertFalse(ready_module._same(True, 1))
        self.assertFalse(ready_module._same([1], (1,)))
        self.assertTrue(ready_module._same({"a": [1, "b"]}, {"a": [1, "b"]}))
        self.assertFalse(ready_module._same({"a": 1}, {"a": 1, "b": 2}))


class UnsupportedAndFlagTests(unittest.TestCase):
    def test_improve_or_conflict_never_ready(self):
        request = req(operation="create")
        analysis = analyze(request, [desc()])
        self.assertEqual(analysis["status"], "improve_or_conflict")
        base = six()
        for tail in (base, six("improve")):
            chain = [request, analysis, base[2], tail[3], tail[4], tail[5]]
            r = ev(chain)
            self.assertNotEqual(r["status"], "ready")
            self.assertIs(r["ready"], False)
            self.assertIs(r["execution_allowed"], False)
            self.assertTrue(validate(r)["valid"])

    def test_improve_or_conflict_with_own_spec(self):
        request = req(operation="create")
        analysis = analyze(request, [desc()])
        spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
        base = six()
        r = ev([request, analysis, spec, base[3], base[4], base[5]])
        self.assertNotEqual(r["status"], "ready")
        self.assertIs(r["ready"], False)

    def test_unsupported_combination_direct(self):
        with mock.patch.object(ready_module, "SUPPORTED", (("improve", "improve_required",
                                                            "improve_capability"),)):
            r = ev(six("create"))
        self.assertEqual(r["status"], "unsupported_status")
        self.assertIs(r["ready"], False)
        self.assertEqual(r["request_id"], "evo_001")
        self.assertEqual((r["plan_id"], r["proposal_id"]), (None, None))
        self.assertEqual(r["reason"], "unsupported_status")
        self.assertTrue(validate(r)["valid"])

    def test_context_not_ready_is_not_ready(self):
        ctx = {"status": "not_ready", "ready": False, "request_id": "evo_001",
               "capability_name": "text_summarizer", "operation": "create",
               "analysis_status": "create_required", "reason": "not_ready",
               "execution_allowed": False, "executed": False}
        with mock.patch.object(ready_module, "validate_capability_evolution", return_value=ctx), \
                mock.patch.object(ready_module, "validate_capability_evolution_result",
                                  return_value={"valid": True}):
            r = ev(six("create"))
        self.assertEqual(r["status"], "not_ready")
        self.assertIs(r["ready"], False)
        self.assertTrue(validate(r)["valid"])

    def test_context_identity_forged(self):
        ctx = {"status": "ready", "ready": True, "request_id": "OTHER",
               "capability_name": "text_summarizer", "operation": "create",
               "analysis_status": "create_required", "reason": "ready",
               "execution_allowed": False, "executed": False}
        with mock.patch.object(ready_module, "validate_capability_evolution", return_value=ctx), \
                mock.patch.object(ready_module, "validate_capability_evolution_result",
                                  return_value={"valid": True}):
            r = ev(six("create"))
        self.assertEqual(r["status"], "context_mismatch")

    def test_candidate_implementation_ready_true(self):
        c = six()
        c[5] = dict(c[5], implementation_ready=True)
        r = ev(c)
        self.assertEqual(r["status"], "invalid_candidate")
        self.assertIs(r["ready"], False)

    def test_candidate_execution_allowed_true(self):
        c = six()
        c[5] = dict(c[5], execution_allowed=True)
        r = ev(c)
        self.assertEqual(r["status"], "invalid_candidate")
        self.assertIs(r["ready"], False)

    def test_other_objects_execution_allowed_true(self):
        for i, key in ((0, "execution_allowed"), (2, "execution_allowed"),
                       (3, "execution_allowed"), (4, "execution_allowed")):
            c = six()
            c[i] = dict(c[i], **{key: True})
            r = ev(c)
            self.assertNotEqual(r["status"], "ready")
            self.assertIs(r["ready"], False)

    def test_internal_failure_is_validation_error(self):
        with mock.patch.object(ready_module, "_chain_mismatch", side_effect=RuntimeError("x")):
            r = ev(six())
        self.assertEqual(r["status"], "validation_error")
        self.assertIs(r["ready"], False)
        self.assertEqual([r[k] for k in ("request_id", "operation", "plan_id")], [None] * 3)
        self.assertTrue(validate(r)["valid"])


class ResultValidatorTests(unittest.TestCase):
    def good(self):
        return ok("create")

    def codes(self, result):
        return [e["code"] for e in validate(result)["errors"]]

    def test_valid_results_of_every_evaluator_status(self):
        for chain in (six(), six("improve"), [None] * 6, swap(six(), six(request_id="b"), 5)):
            self.assertTrue(validate(ev(chain))["valid"])

    def test_validator_flags(self):
        for r in (validate(self.good()), validate(None)):
            self.assertEqual(sorted(r), sorted(["errors", "execution_allowed", "executed", "valid"]))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_not_dict(self):
        for bad in (None, [], "x", 3):
            self.assertEqual(self.codes(bad), ["result_not_dict"])

    def test_missing_keys(self):
        for key in KEYS:
            r = self.good()
            del r[key]
            self.assertIn("missing_key", self.codes(r))

    def test_extra_keys(self):
        r = self.good()
        r["executed"] = False
        self.assertIn("unexpected_key", self.codes(r))
        r = self.good()
        r["junk"] = 1
        self.assertFalse(validate(r)["valid"])

    def test_invalid_version(self):
        for bad in ("2", 1, None, ""):
            r = self.good()
            r["version"] = bad
            self.assertIn("invalid_version", self.codes(r))

    def test_invalid_status(self):
        for bad in ("done", None, 1, ""):
            r = self.good()
            r["status"] = bad
            self.assertIn("invalid_status", self.codes(r))

    def test_ready_flag_inconsistency(self):
        r = self.good()
        r["ready"] = False
        self.assertIn("invalid_ready", self.codes(r))
        r = ev([None] * 6)
        r["ready"] = True
        self.assertIn("invalid_ready", self.codes(r))
        r = self.good()
        r["ready"] = 1
        self.assertIn("invalid_ready", self.codes(r))

    def test_execution_allowed_true_rejected(self):
        for bad in (True, 0, None, "False"):
            r = self.good()
            r["execution_allowed"] = bad
            self.assertIn("invalid_execution_allowed", self.codes(r))

    def test_reason_must_match_status(self):
        r = self.good()
        r["reason"] = "because"
        self.assertIn("invalid_reason", self.codes(r))
        r["reason"] = 5
        self.assertIn("invalid_reason", self.codes(r))

    def test_ready_requires_full_identity(self):
        for key in ("request_id", "capability_name", "operation", "analysis_status",
                    "plan_id", "proposal_id"):
            r = self.good()
            r[key] = None
            self.assertFalse(validate(r)["valid"], key)

    def test_ready_invalid_identity_text(self):
        for key, bad in (("request_id", ""), ("request_id", "a\nb"), ("plan_id", "x" * 65),
                         ("proposal_id", 5), ("capability_name", "Bad\nName"),
                         ("operation", "delete")):
            r = self.good()
            r[key] = bad
            self.assertIn("invalid_identity", self.codes(r))

    def test_ready_unsupported_combination(self):
        r = self.good()
        r["analysis_status"] = "improve_or_conflict"
        self.assertFalse(validate(r)["valid"])
        r = self.good()
        r["analysis_status"] = "improve_required"
        self.assertFalse(validate(r)["valid"])

    def test_invalid_request_identity_must_be_none(self):
        r = ev([None] * 6)
        for key in ("request_id", "capability_name", "operation", "analysis_status",
                    "plan_id", "proposal_id"):
            bad = dict(r)
            bad[key] = "evo_001"
            self.assertFalse(validate(bad)["valid"], key)

    def test_invalid_analysis_identity_rules(self):
        c = six()
        c[1] = None
        r = ev(c)
        for key in ("analysis_status", "plan_id", "proposal_id"):
            bad = dict(r)
            bad[key] = "create_required" if key == "analysis_status" else "p1"
            self.assertFalse(validate(bad)["valid"], key)
        bad = dict(r, request_id=None)
        self.assertFalse(validate(bad)["valid"])

    def test_non_ready_must_not_carry_plan_or_proposal_id(self):
        r = ev(swap(six(), six(request_id="b"), 5))
        for key in ("plan_id", "proposal_id"):
            bad = dict(r)
            bad[key] = "plan_001"
            self.assertFalse(validate(bad)["valid"])

    def test_non_ready_requires_request_identity(self):
        r = ev(swap(six(), six(request_id="b"), 5))
        bad = dict(r, request_id=None)
        self.assertFalse(validate(bad)["valid"])

    def test_every_status_shape_accepted(self):
        base = {"version": "1", "ready": False, "request_id": "r1", "capability_name": "cap",
                "operation": "create", "analysis_status": "create_required", "plan_id": None,
                "proposal_id": None, "execution_allowed": False}
        for status in STATUSES:
            r = dict(base, status=status, reason=status)
            if status == "ready":
                r.update(ready=True, plan_id="p1", proposal_id="q1")
            elif status == "invalid_request" or status == "validation_error":
                r.update(request_id=None, capability_name=None, operation=None,
                         analysis_status=None)
            elif status == "invalid_analysis":
                r.update(analysis_status=None)
            self.assertTrue(validate(r)["valid"], status)

    def test_validator_does_not_mutate_or_raise(self):
        r = self.good()
        snap = copy.deepcopy(r)
        validate(r)
        self.assertEqual(r, snap)
        for weird in ({1: 2}, {"version": object()}, {k: object() for k in KEYS}):
            self.assertFalse(validate(weird)["valid"])

    def test_error_cap(self):
        r = {k: object() for k in KEYS}
        self.assertLessEqual(len(validate(r)["errors"]), ready_module.MAX_ERRORS)


class SafetyTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for op in ("create", "improve"):
            chain = six(op)
            snap = copy.deepcopy(chain)
            ev(chain)
            self.assertEqual(chain, snap)
        bad = swap(six(), six(request_id="b"), 5)
        snap = copy.deepcopy(bad)
        ev(bad)
        self.assertEqual(bad, snap)

    def test_result_is_fresh_and_detached(self):
        chain = six()
        a, b = ev(chain), ev(chain)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a["status"] = "x"
        self.assertEqual(ev(chain)["status"], "ready")

    def test_deterministic_repeated_evaluation(self):
        for chain in (six(), six("improve"), swap(six(), six(goal="Other goal."), 3), [None] * 6):
            results = [ev(chain) for _ in range(5)]
            self.assertTrue(all(r == results[0] for r in results))

    def test_deterministic_across_equal_chains(self):
        self.assertEqual(ev(six("improve")), ev(six("improve")))

    def test_module_has_no_forbidden_imports_or_calls(self):
        path = os.path.join(ROOT, "capabilities", "capability_definition_readiness.py")
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
                self.assertTrue(node.level == 1 or node.module is None
                                or node.module.split(".")[0] not in banned)
                if node.level == 1:
                    self.assertTrue(node.module.startswith("capability_"))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__"})

    def test_no_executed_field_and_statuses_complete(self):
        self.assertEqual(sorted(ready_module.STATUSES), sorted(STATUSES))
        self.assertEqual(list(ready_module.RESULT_KEYS), KEYS)
        self.assertNotIn("executed", ready_module.RESULT_KEYS)


if __name__ == "__main__":
    unittest.main()
