"""
Prompt 885 - capability implementation design validation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_implementation_design_validation_prompt885 -v
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_implementation_design_validation as vmod
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
    build_capability_implementation_design as build_design,
    validate_capability_implementation_design as validate_design)
from capabilities.capability_implementation_design_validation import (
    validate_capability_implementation_design_context as check,
    validate_capability_implementation_design_validation_result as validate)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["version", "status", "valid", "request_id", "capability_name", "operation",
        "analysis_status", "plan_id", "proposal_id", "candidate_id", "design_id", "reason"]
KEYS12 = KEYS
STATUSES = ["valid", "invalid_request", "invalid_analysis", "invalid_specification",
            "invalid_validation", "invalid_plan", "invalid_proposal", "invalid_candidate",
            "invalid_readiness", "invalid_design", "context_mismatch", "unsupported_status",
            "validation_error"]
ID_FIELDS = ["request_id", "capability_name", "operation", "analysis_status", "plan_id",
             "proposal_id", "candidate_id", "design_id"]


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


def eight(op="create", caps=None, plan_id="plan_001", proposal_id="prop_001",
          candidate_id="cand_001", design_id="design_001", **req_over):
    """[request, analysis, spec, plan, proposal, candidate, readiness, design]."""
    if caps is None:
        caps = [desc()] if op == "improve" else []
    request = req(operation=op, **req_over)
    analysis = analyze(request, caps)
    spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
    plan = build_plan(request, analysis, spec, plan_id)["plan"]
    proposal = build_proposal(request, analysis, spec, plan, proposal_id)["proposal"]
    candidate = build_candidate(request, analysis, spec, plan, proposal, candidate_id)["candidate"]
    readiness = evaluate_readiness(request, analysis, spec, plan, proposal, candidate)
    design = build_design(request, analysis, spec, plan, proposal, candidate, readiness,
                          design_id)["design"]
    return [request, analysis, spec, plan, proposal, candidate, readiness, design]


def swap(base, other, *indexes):
    out = list(base)
    for i in indexes:
        out[i] = other[i]
    return out


def run(chain):
    return check(*chain)


def ok(op="create"):
    return run(eight(op))


def codes(result):
    return [e["code"] for e in result["errors"]]


class IntegerVersionCorrectionTests(unittest.TestCase):
    def test_design_version_is_integer_one(self):
        for op in ("create", "improve"):
            d = eight(op)[7]
            self.assertEqual(d["version"], 1)
            self.assertIs(type(d["version"]), int)
            self.assertTrue(validate_design(d)["valid"])

    def test_string_and_other_versions_rejected_by_design_validator(self):
        for bad in ("1", "2", 2, True, 1.0, None):
            d = eight()[7]
            d["version"] = bad
            self.assertFalse(validate_design(d)["valid"], bad)

    def test_validation_result_version_is_integer_one(self):
        r = ok()
        self.assertEqual(r["version"], 1)
        self.assertIs(type(r["version"]), int)

    def test_other_prompt884_semantics_unchanged(self):
        d = eight()[7]
        self.assertEqual(sorted(d), sorted(["version", "design_id", "request_id", "operation",
                                            "capability_name", "purpose", "inputs", "outputs",
                                            "constraints", "existing_capability",
                                            "analysis_status", "plan_id", "proposal_id",
                                            "candidate_id", "design_type",
                                            "implementation_ready", "execution_allowed"]))
        self.assertIs(d["implementation_ready"], False)
        self.assertIs(d["execution_allowed"], False)


class ValidChainTests(unittest.TestCase):
    def test_valid_create(self):
        r = ok("create")
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["valid"], True)
        self.assertEqual([r[k] for k in ID_FIELDS],
                         ["evo_001", "text_summarizer", "create", "create_required",
                          "plan_001", "prop_001", "cand_001", "design_001"])
        self.assertEqual(r["reason"], "valid")
        self.assertTrue(validate(r)["valid"])

    def test_valid_improve(self):
        r = ok("improve")
        self.assertEqual(r["status"], "valid")
        self.assertEqual((r["operation"], r["analysis_status"]), ("improve", "improve_required"))
        self.assertTrue(validate(r)["valid"])

    def test_exactly_the_twelve_listed_keys(self):
        for chain in (eight(), [None] * 8, eight("improve")):
            self.assertEqual(sorted(run(chain)), sorted(KEYS12))
        self.assertEqual(len(KEYS12), 12)

    def test_ids_populated_from_chain(self):
        r = run(eight(plan_id="my_plan", proposal_id="my_prop", candidate_id="my_cand",
                      design_id="my_design"))
        self.assertEqual((r["plan_id"], r["proposal_id"], r["candidate_id"], r["design_id"]),
                         ("my_plan", "my_prop", "my_cand", "my_design"))

    def test_valid_flag_matches_status(self):
        chains = [eight(), eight("improve"), [None] * 8, swap(eight(), eight(goal="x"), 7)]
        for chain in chains:
            r = run(chain)
            self.assertEqual(r["valid"], r["status"] == "valid")
            self.assertEqual(r["reason"], r["status"])
            self.assertNotIn("execution_allowed", r)
            self.assertNotIn("executed", r)

    def test_no_arguments(self):
        self.assertEqual(check()["status"], "invalid_request")


class InvalidObjectTests(unittest.TestCase):
    def status(self, index, bad):
        chain = eight()
        chain[index] = bad
        return run(chain)

    def test_invalid_request(self):
        for bad in (None, {}, dict(req(), goal=5)):
            r = self.status(0, bad)
            self.assertEqual(r["status"], "invalid_request")
            self.assertEqual([r[k] for k in ID_FIELDS], [None] * 8)
            self.assertTrue(validate(r)["valid"])

    def test_invalid_analysis(self):
        r = self.status(1, {"status": "create_required"})
        self.assertEqual(r["status"], "invalid_analysis")
        self.assertEqual((r["request_id"], r["capability_name"], r["operation"]),
                         ("evo_001", "text_summarizer", "create"))
        self.assertEqual([r[k] for k in ID_FIELDS[3:]], [None] * 5)
        self.assertTrue(validate(r)["valid"])

    def test_invalid_specification(self):
        r = self.status(2, dict(eight()[2], specification_id=""))
        self.assertEqual(r["status"], "invalid_specification")
        self.assertEqual(r["analysis_status"], "create_required")
        self.assertEqual([r[k] for k in ID_FIELDS[4:]], [None] * 4)
        self.assertTrue(validate(r)["valid"])

    def test_invalid_specification_untrusted_fields_not_copied(self):
        r = self.status(2, dict(eight()[2], request_id="FORGED", specification_id=""))
        self.assertEqual(r["request_id"], "evo_001")

    def test_invalid_validation_context(self):
        with mock.patch.object(vmod, "validate_capability_evolution", return_value={"x": 1}):
            r = run(eight())
        self.assertEqual(r["status"], "invalid_validation")
        self.assertIs(r["valid"], False)
        self.assertEqual(r["request_id"], "evo_001")
        self.assertIsNone(r["plan_id"])
        self.assertTrue(validate(r)["valid"])

    def test_invalid_plan(self):
        for bad in (None, dict(eight()[3], plan_id="bad\nid")):
            r = self.status(3, bad)
            self.assertEqual(r["status"], "invalid_plan")
            self.assertEqual([r[k] for k in ID_FIELDS[4:]], [None] * 4)
            self.assertTrue(validate(r)["valid"])

    def test_invalid_proposal(self):
        r = self.status(4, dict(eight()[4], proposal_type="x"))
        self.assertEqual(r["status"], "invalid_proposal")
        self.assertEqual([r[k] for k in ID_FIELDS[4:]], [None] * 4)
        self.assertTrue(validate(r)["valid"])

    def test_invalid_candidate(self):
        chain = eight()
        for bad in (None, {"version": "1"}, dict(chain[5], extra=1),
                    dict(chain[5], candidate_id="x" * 99),
                    dict(chain[5], implementation_ready=True),
                    dict(chain[5], execution_allowed=True)):
            r = self.status(5, bad)
            self.assertEqual(r["status"], "invalid_candidate")
            self.assertEqual([r[k] for k in ID_FIELDS[4:]], [None] * 4)
            self.assertTrue(validate(r)["valid"])

    def test_invalid_readiness(self):
        chain = eight()
        for bad in (None, {}, "x", dict(chain[6], extra=1), dict(chain[6], version="2"),
                    dict(chain[6], ready=False), dict(chain[6], reason="because"),
                    dict(chain[6], execution_allowed=True)):
            r = self.status(6, bad)
            self.assertEqual(r["status"], "invalid_readiness")
            self.assertEqual([r[k] for k in ID_FIELDS[4:]], [None] * 4)
            self.assertTrue(validate(r)["valid"])

    def test_valid_but_not_ready_readiness(self):
        chain = eight()
        mismatched = evaluate_readiness(*swap(chain, eight(request_id="other"), 5)[:6])
        self.assertEqual(mismatched["status"], "context_mismatch")
        self.assertEqual(self.status(6, mismatched)["status"], "invalid_readiness")
        invalid = evaluate_readiness(None, None, None, None, None, None)
        self.assertEqual(self.status(6, invalid)["status"], "invalid_readiness")

    def test_invalid_design(self):
        chain = eight()
        for bad in (None, {}, dict(chain[7], extra=1), dict(chain[7], version="1"),
                    dict(chain[7], design_type="nonsense"), dict(chain[7], design_id=""),
                    dict(chain[7], implementation_ready=True),
                    dict(chain[7], execution_allowed=True)):
            r = self.status(7, bad)
            self.assertEqual(r["status"], "invalid_design")
            self.assertEqual([r[k] for k in ID_FIELDS[4:]], [None] * 4)
            self.assertTrue(validate(r)["valid"])

    def test_order_first_failure_wins(self):
        chain = eight()
        chain[1], chain[4], chain[7] = None, None, None
        self.assertEqual(run(chain)["status"], "invalid_analysis")
        chain = eight()
        chain[4], chain[5], chain[6], chain[7] = None, None, None, None
        self.assertEqual(run(chain)["status"], "invalid_proposal")
        chain = eight()
        chain[5], chain[6], chain[7] = None, None, None
        self.assertEqual(run(chain)["status"], "invalid_candidate")
        chain = eight()
        chain[6], chain[7] = None, None
        self.assertEqual(run(chain)["status"], "invalid_readiness")


class ForgedChainTests(unittest.TestCase):
    """Every object individually valid; the chain disagrees."""

    def mismatch(self, chain):
        r = run(chain)
        self.assertEqual(r["status"], "context_mismatch")
        self.assertIs(r["valid"], False)
        self.assertEqual(r["reason"], "context_mismatch")
        self.assertEqual([r[k] for k in ID_FIELDS[4:]], [None] * 4)
        self.assertTrue(validate(r)["valid"])
        return r

    def test_forged_valid_request(self):
        other = eight(request_id="evo_002")
        self.mismatch(swap(eight(), other, 0))

    def test_forged_valid_analysis(self):
        self.mismatch(swap(eight("create"), eight("improve"), 1))

    def test_forged_valid_specification(self):
        self.mismatch(swap(eight(), eight(goal="Another goal."), 2))

    def test_forged_valid_plan(self):
        self.mismatch(swap(eight(), eight(plan_id="plan_002"), 3))
        self.mismatch(swap(eight(), eight(capability_name="other_cap"), 3))

    def test_forged_valid_proposal(self):
        self.mismatch(swap(eight(), eight(proposal_id="prop_002"), 4))
        self.mismatch(swap(eight(), eight(outputs=["other_out"]), 4))

    def test_forged_valid_candidate(self):
        self.mismatch(swap(eight(), eight(request_id="evo_002"), 5))
        chain = eight()
        chain[5] = dict(chain[5], inputs=["a_input", "z_input"])
        self.mismatch(chain)

    def test_forged_valid_readiness(self):
        for other in (eight(request_id="evo_9"), eight(plan_id="plan_9"),
                      eight(proposal_id="prop_9"), eight(capability_name="other_cap"),
                      eight("improve")):
            self.assertEqual(other[6]["status"], "ready")
            self.mismatch(swap(eight(), other, 6))

    def test_forged_valid_design(self):
        for other in (eight(request_id="evo_9"), eight(plan_id="plan_9"),
                      eight(proposal_id="prop_9"), eight(candidate_id="cand_9"),
                      eight(goal="x"), eight("improve")):
            self.assertTrue(validate_design(other[7])["valid"])
            self.mismatch(swap(eight(), other, 7))

    def test_request_id_mismatch(self):
        other = eight(request_id="evo_002")
        for i in (0, 2, 3, 4, 5, 6, 7):
            self.mismatch(swap(eight(), other, i))

    def test_capability_name_mismatch(self):
        other = eight(capability_name="other_cap")
        for i in (0, 3, 4, 5, 6, 7):
            self.mismatch(swap(eight(), other, i))

    def test_operation_mismatch(self):
        for i in (0, 4, 5, 6, 7):
            self.mismatch(swap(eight("create"), eight("improve"), i))
        self.mismatch(swap(eight("improve"), eight("create"), 7))

    def test_goal_purpose_mismatch(self):
        other = eight(goal="A completely different goal.")
        for i in (2, 3, 4, 5, 7):
            self.mismatch(swap(eight(), other, i))
        chain = eight()
        chain[7] = dict(chain[7], purpose="Forged purpose.")
        self.mismatch(chain)

    def test_inputs_mismatch(self):
        other = eight(inputs=["different_input"])
        for i in (2, 3, 4, 5, 7):
            self.mismatch(swap(eight(), other, i))

    def test_outputs_mismatch(self):
        other = eight(outputs=["different_out"])
        for i in (2, 3, 4, 5, 7):
            self.mismatch(swap(eight(), other, i))

    def test_constraints_mismatch(self):
        other = eight(constraints=["Only one."])
        for i in (2, 3, 4, 5, 7):
            self.mismatch(swap(eight(), other, i))
        self.mismatch(swap(eight(), eight(constraints=["First.", "Second.", "Second."]), 7))

    def test_existing_capability_mismatch(self):
        base = eight("improve")
        other = eight("improve", caps=[desc(purpose="A different purpose.")])
        for i in (2, 3, 4, 5, 7):
            self.mismatch(swap(base, other, i))
        chain = eight("improve")
        chain[7] = dict(chain[7], existing_capability=desc(version=2))
        self.mismatch(chain)

    def test_analysis_status_mismatch(self):
        self.mismatch(swap(eight("improve"), eight("create"), 7))
        self.mismatch(swap(eight("improve"), eight("create"), 2))
        self.mismatch(swap(eight("create"), eight("improve"), 1))

    def test_plan_id_mismatch(self):
        base, other = eight(plan_id="plan_001"), eight(plan_id="plan_002")
        for i in (3, 5, 6, 7):
            self.mismatch(swap(base, other, i))

    def test_proposal_id_mismatch(self):
        base, other = eight(proposal_id="prop_001"), eight(proposal_id="prop_002")
        for i in (4, 5, 6, 7):
            self.mismatch(swap(base, other, i))

    def test_candidate_id_mismatch(self):
        base, other = eight(candidate_id="cand_001"), eight(candidate_id="cand_002")
        self.mismatch(swap(base, other, 7))
        chain = eight()
        chain[7] = dict(chain[7], candidate_id="cand_002")
        self.mismatch(chain)

    def test_design_id_forged_and_design_type_mismatch(self):
        # a design is valid for any caller-supplied design_id, so it must equal the builder's
        chain = eight()
        chain[7] = dict(chain[7], design_id="design_other")
        self.assertEqual(run(chain)["design_id"], None if run(chain)["status"] != "valid"
                         else "design_other")
        chain = eight("create")
        chain[7] = dict(chain[7], design_type="improve_implementation")
        self.assertIn(run(chain)["status"], ("invalid_design", "context_mismatch"))
        self.assertIsNone(run(chain)["design_id"])

    def test_design_id_is_the_designs_own(self):
        r = run(eight(design_id="d_special"))
        self.assertEqual((r["status"], r["design_id"]), ("valid", "d_special"))

    def test_mismatch_preserves_only_trusted_identity(self):
        r = self.mismatch(swap(eight(), eight(capability_name="other_cap"), 7))
        self.assertEqual((r["request_id"], r["capability_name"], r["operation"],
                          r["analysis_status"]),
                         ("evo_001", "text_summarizer", "create", "create_required"))


class UnsupportedAndInternalTests(unittest.TestCase):
    def test_improve_or_conflict_never_valid(self):
        request = req(operation="create")
        analysis = analyze(request, [desc()])
        self.assertEqual(analysis["status"], "improve_or_conflict")
        base = eight()
        for tail in (base, eight("improve")):
            chain = [request, analysis] + tail[2:]
            r = run(chain)
            self.assertNotEqual(r["status"], "valid")
            self.assertIs(r["valid"], False)
            self.assertTrue(validate(r)["valid"])

    def test_unsupported_combination_guard(self):
        with mock.patch.object(vmod, "SUPPORTED", (("improve", "improve_required",
                                                    "improve_capability",
                                                    "improve_implementation"),)):
            r = run(eight("create"))
        self.assertEqual(r["status"], "unsupported_status")
        self.assertIs(r["valid"], False)
        self.assertEqual(r["request_id"], "evo_001")
        self.assertEqual([r[k] for k in ID_FIELDS[4:]], [None] * 4)
        self.assertTrue(validate(r)["valid"])

    def test_implementation_ready_true_and_execution_allowed_true(self):
        for key in ("implementation_ready", "execution_allowed"):
            chain = eight()
            chain[7] = dict(chain[7], **{key: True})
            r = run(chain)
            self.assertEqual(r["status"], "invalid_design")
            self.assertIs(r["valid"], False)

    def test_validity_never_converts_implementation_ready(self):
        chain = eight()
        run(chain)
        self.assertIs(chain[7]["implementation_ready"], False)
        self.assertIs(chain[7]["execution_allowed"], False)

    def test_other_objects_execution_allowed_true(self):
        for i in (0, 2, 3, 4):
            chain = eight()
            chain[i] = dict(chain[i], execution_allowed=True)
            r = run(chain)
            self.assertNotEqual(r["status"], "valid")

    def test_internal_failure(self):
        with mock.patch.object(vmod, "_chain_mismatch", side_effect=RuntimeError("x")):
            r = run(eight())
        self.assertEqual(r["status"], "validation_error")
        self.assertEqual([r[k] for k in ID_FIELDS], [None] * 8)
        self.assertTrue(validate(r)["valid"])


class ResultValidatorTests(unittest.TestCase):
    def good(self):
        return ok("create")

    def test_valid_results_of_every_status(self):
        base = eight()
        for chain in (base, eight("improve"), [None] * 8, swap(base, eight(goal="x"), 7)):
            self.assertTrue(validate(run(chain))["valid"])

    def test_every_status_shape_accepted(self):
        base = {"version": 1, "valid": False, "request_id": "r1", "capability_name": "cap",
                "operation": "create", "analysis_status": "create_required", "plan_id": None,
                "proposal_id": None, "candidate_id": None, "design_id": None}
        for status in STATUSES:
            r = dict(base, status=status, reason=status)
            if status == "valid":
                r.update(valid=True, plan_id="p1", proposal_id="q1", candidate_id="c1",
                         design_id="d1")
            elif status in ("invalid_request", "validation_error"):
                r.update(request_id=None, capability_name=None, operation=None,
                         analysis_status=None)
            elif status == "invalid_analysis":
                r.update(analysis_status=None)
            self.assertTrue(validate(r)["valid"], status)

    def test_report_shape(self):
        for r in (validate(self.good()), validate(None)):
            self.assertEqual(sorted(r), sorted(["valid", "errors", "execution_allowed",
                                                "executed"]))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_not_dict(self):
        for bad in (None, [], "x", 3):
            self.assertEqual(codes(validate(bad)), ["result_not_dict"])

    def test_missing_keys(self):
        for key in KEYS:
            r = self.good()
            del r[key]
            self.assertIn("missing_key", codes(validate(r)))

    def test_extra_keys_and_execution_flags(self):
        for extra in ("executed", "execution_allowed", "implementation_ready", "ready", "junk"):
            r = self.good()
            r[extra] = False
            self.assertIn("unexpected_key", codes(validate(r)))
            self.assertFalse(validate(r)["valid"])

    def test_wrong_version_type(self):
        for bad in ("1", "2", 2, 0, True, 1.0, None):
            r = self.good()
            r["version"] = bad
            self.assertIn("invalid_version", codes(validate(r)), bad)

    def test_invalid_status(self):
        for bad in ("done", "ready", None, 1, ""):
            r = self.good()
            r["status"] = bad
            self.assertIn("invalid_status", codes(validate(r)))

    def test_inconsistent_valid_flag(self):
        r = self.good()
        r["valid"] = False
        self.assertIn("invalid_valid", codes(validate(r)))
        r = run([None] * 8)
        r["valid"] = True
        self.assertIn("invalid_valid", codes(validate(r)))
        r = self.good()
        r["valid"] = 1
        self.assertIn("invalid_valid", codes(validate(r)))

    def test_inconsistent_reason(self):
        for bad in ("because", "invalid_request", 5, None):
            r = self.good()
            r["reason"] = bad
            self.assertIn("invalid_reason", codes(validate(r)))

    def test_valid_requires_full_identity(self):
        for key in ID_FIELDS:
            r = self.good()
            r[key] = None
            self.assertFalse(validate(r)["valid"], key)

    def test_invalid_ids(self):
        for key in ("request_id", "plan_id", "proposal_id", "candidate_id", "design_id",
                    "capability_name", "operation"):
            for bad in ("", "a\nb", "x" * 65, 5):
                r = self.good()
                r[key] = bad
                self.assertFalse(validate(r)["valid"], (key, bad))

    def test_unsupported_combination_in_valid_result(self):
        for op, st in (("create", "improve_required"), ("improve", "create_required"),
                       ("create", "improve_or_conflict")):
            r = self.good()
            r.update(operation=op, analysis_status=st)
            self.assertFalse(validate(r)["valid"])

    def test_untrusted_identity_per_status(self):
        r = run([None] * 8)
        for key in ID_FIELDS:
            bad = dict(r)
            bad[key] = "evo_001"
            self.assertFalse(validate(bad)["valid"], key)
        chain = eight()
        chain[1] = None
        r = run(chain)
        for key, val in (("analysis_status", "create_required"), ("plan_id", "p"),
                         ("proposal_id", "p"), ("candidate_id", "c"), ("design_id", "d")):
            self.assertFalse(validate(dict(r, **{key: val}))["valid"], key)
        self.assertFalse(validate(dict(r, request_id=None))["valid"])
        r = run(swap(eight(), eight(goal="x"), 7))
        for key in ("plan_id", "proposal_id", "candidate_id", "design_id"):
            self.assertFalse(validate(dict(r, **{key: "plan_001"}))["valid"], key)
        self.assertFalse(validate(dict(r, request_id=None))["valid"])

    def test_read_only_and_never_raises(self):
        r = self.good()
        snap = copy.deepcopy(r)
        validate(r)
        self.assertEqual(r, snap)
        for weird in ({1: 2}, {k: object() for k in KEYS}, {"version": object()}):
            self.assertFalse(validate(weird)["valid"])
        self.assertLessEqual(len(validate({k: object() for k in KEYS})["errors"]),
                             vmod.MAX_ERRORS)


class SafetyTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for op in ("create", "improve"):
            chain = eight(op)
            snap = copy.deepcopy(chain)
            run(chain)
            self.assertEqual(chain, snap)
        bad = swap(eight(), eight(request_id="b"), 7)
        snap = copy.deepcopy(bad)
        run(bad)
        self.assertEqual(bad, snap)

    def test_fresh_detached_results(self):
        chain = eight()
        a, b = run(chain), run(chain)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a["status"] = "x"
        self.assertEqual(run(chain)["status"], "valid")

    def test_deterministic_repeated_validation(self):
        for chain in (eight(), eight("improve"), swap(eight(), eight(goal="Other."), 3),
                      [None] * 8):
            results = [run(chain) for _ in range(5)]
            self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(run(eight("improve")), run(eight("improve")))

    def test_type_strict_comparison(self):
        self.assertFalse(vmod._same(True, 1))
        self.assertFalse(vmod._same([1], (1,)))
        self.assertTrue(vmod._same({"a": [1, "b"]}, {"a": [1, "b"]}))

    def test_module_has_no_forbidden_imports_or_calls(self):
        path = os.path.join(ROOT, "capabilities", "capability_implementation_design_validation.py")
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
        self.assertEqual(list(vmod.RESULT_KEYS), KEYS)
        self.assertEqual(sorted(vmod.STATUSES), sorted(STATUSES))
        self.assertEqual(vmod.VALIDATION_VERSION, 1)
        self.assertIs(type(vmod.VALIDATION_VERSION), int)


if __name__ == "__main__":
    unittest.main()
