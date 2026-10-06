"""
Prompt 887 - capability implementation blueprint validation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_implementation_blueprint_validation_prompt887 -v
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_implementation_blueprint_validation as vmod
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
from capabilities.capability_implementation_blueprint import (
    build_capability_implementation_blueprint as build_blueprint,
    validate_capability_implementation_blueprint as validate_blueprint)
from capabilities.capability_implementation_blueprint_validation import (
    validate_capability_implementation_blueprint_context as check,
    validate_capability_implementation_blueprint_validation_result as validate)
from capabilities.capability_implementation_design import (
    build_capability_implementation_design as build_design,
    validate_capability_implementation_design as validate_design)
from capabilities.capability_implementation_design_validation import (
    validate_capability_implementation_design_context as check885)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["version", "status", "valid", "request_id", "capability_name", "operation",
        "analysis_status", "plan_id", "proposal_id", "candidate_id", "design_id",
        "blueprint_id", "reason"]
STATUSES = ["valid", "invalid_request", "invalid_analysis", "invalid_specification",
            "invalid_validation", "invalid_plan", "invalid_proposal", "invalid_candidate",
            "invalid_readiness", "invalid_design", "invalid_design_validation",
            "invalid_blueprint", "context_mismatch", "unsupported_status",
            "validation_error"]
ID_FIELDS = ["request_id", "capability_name", "operation", "analysis_status", "plan_id",
             "proposal_id", "candidate_id", "design_id", "blueprint_id"]
LATER = ID_FIELDS[4:]


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


def ten(op="create", caps=None, plan_id="plan_001", proposal_id="prop_001",
        candidate_id="cand_001", design_id="design_001", blueprint_id="bp_001", **req_over):
    """[request, analysis, spec, plan, proposal, candidate, readiness, design, vresult,
    blueprint]."""
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
    chain = [request, analysis, spec, plan, proposal, candidate, readiness, design]
    vresult = check885(*chain)
    blueprint = build_blueprint(*chain, vresult, blueprint_id)["blueprint"]
    return chain + [vresult, blueprint]


def swap(base, other, *indexes):
    out = list(base)
    for i in indexes:
        out[i] = other[i]
    return out


def run(chain):
    return check(*chain)


def ok(op="create"):
    return run(ten(op))


def codes(result):
    return [e["code"] for e in result["errors"]]


class IntegerVersionTests(unittest.TestCase):
    def test_prompt884_design_version_still_integer(self):
        for op in ("create", "improve"):
            d = ten(op)[7]
            self.assertIs(type(d["version"]), int)
            self.assertEqual(d["version"], 1)
            self.assertTrue(validate_design(d)["valid"])
            for bad in ("1", 2, True, 1.0, None):
                self.assertFalse(validate_design(dict(d, version=bad))["valid"], bad)

    def test_chain_versions_are_integer_one(self):
        chain = ten()
        for obj in (chain[7], chain[8], chain[9]):
            self.assertIs(type(obj["version"]), int)
            self.assertEqual(obj["version"], 1)

    def test_validation_result_version_is_integer_one(self):
        r = ok()
        self.assertEqual(r["version"], 1)
        self.assertIs(type(r["version"]), int)
        self.assertEqual(vmod.VALIDATION_VERSION, 1)
        self.assertIs(type(vmod.VALIDATION_VERSION), int)


class ValidChainTests(unittest.TestCase):
    def test_valid_create(self):
        r = ok("create")
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["valid"], True)
        self.assertEqual([r[k] for k in ID_FIELDS],
                         ["evo_001", "text_summarizer", "create", "create_required",
                          "plan_001", "prop_001", "cand_001", "design_001", "bp_001"])
        self.assertEqual(r["reason"], "valid")
        self.assertTrue(validate(r)["valid"])

    def test_valid_improve(self):
        r = ok("improve")
        self.assertEqual(r["status"], "valid")
        self.assertEqual((r["operation"], r["analysis_status"]), ("improve", "improve_required"))
        self.assertTrue(validate(r)["valid"])

    def test_exactly_thirteen_keys(self):
        for chain in (ten(), [None] * 10, ten("improve")):
            self.assertEqual(sorted(run(chain)), sorted(KEYS))
        self.assertEqual(len(KEYS), 13)
        self.assertEqual(list(vmod.RESULT_KEYS), KEYS)

    def test_ids_populated_from_trusted_chain(self):
        r = run(ten(plan_id="my_plan", proposal_id="my_prop", candidate_id="my_cand",
                    design_id="my_design", blueprint_id="my_bp"))
        self.assertEqual([r[k] for k in LATER],
                         ["my_plan", "my_prop", "my_cand", "my_design", "my_bp"])

    def test_valid_flag_matches_status_and_reason(self):
        chains = [ten(), ten("improve"), [None] * 10, swap(ten(), ten(goal="x"), 9)]
        for chain in chains:
            r = run(chain)
            self.assertEqual(r["valid"], r["status"] == "valid")
            self.assertEqual(r["reason"], r["status"])
            self.assertNotIn("execution_allowed", r)
            self.assertNotIn("executed", r)

    def test_no_arguments(self):
        self.assertEqual(check()["status"], "invalid_request")

    def test_blueprint_steps_in_valid_chain(self):
        self.assertEqual(ten("create")[9]["implementation_steps"][0], "define_interface")
        self.assertEqual(ten("improve")[9]["implementation_steps"][0], "inspect_existing_behavior")


class InvalidObjectTests(unittest.TestCase):
    def status(self, index, bad):
        chain = ten()
        chain[index] = bad
        return run(chain)

    def test_invalid_request(self):
        for bad in (None, {}, dict(req(), goal=5)):
            r = self.status(0, bad)
            self.assertEqual(r["status"], "invalid_request")
            self.assertEqual([r[k] for k in ID_FIELDS], [None] * 9)
            self.assertTrue(validate(r)["valid"])

    def test_invalid_analysis(self):
        r = self.status(1, {"status": "create_required"})
        self.assertEqual(r["status"], "invalid_analysis")
        self.assertEqual((r["request_id"], r["capability_name"], r["operation"]),
                         ("evo_001", "text_summarizer", "create"))
        self.assertEqual([r[k] for k in ID_FIELDS[3:]], [None] * 6)
        self.assertTrue(validate(r)["valid"])

    def test_invalid_specification(self):
        r = self.status(2, dict(ten()[2], specification_id=""))
        self.assertEqual(r["status"], "invalid_specification")
        self.assertEqual(r["analysis_status"], "create_required")
        self.assertEqual([r[k] for k in LATER], [None] * 5)
        self.assertTrue(validate(r)["valid"])

    def test_untrusted_fields_not_copied(self):
        r = self.status(2, dict(ten()[2], request_id="FORGED", specification_id=""))
        self.assertEqual(r["request_id"], "evo_001")

    def test_invalid_validation_context(self):
        with mock.patch.object(vmod, "validate_capability_evolution", return_value={"x": 1}):
            r = run(ten())
        self.assertEqual(r["status"], "invalid_validation")
        self.assertEqual(r["request_id"], "evo_001")
        self.assertEqual([r[k] for k in LATER], [None] * 5)
        self.assertTrue(validate(r)["valid"])

    def test_invalid_plan(self):
        for bad in (None, dict(ten()[3], plan_id="bad\nid")):
            r = self.status(3, bad)
            self.assertEqual(r["status"], "invalid_plan")
            self.assertEqual([r[k] for k in LATER], [None] * 5)

    def test_invalid_proposal(self):
        r = self.status(4, dict(ten()[4], proposal_type="x"))
        self.assertEqual(r["status"], "invalid_proposal")
        self.assertTrue(validate(r)["valid"])

    def test_invalid_candidate(self):
        chain = ten()
        for bad in (None, {"version": "1"}, dict(chain[5], extra=1),
                    dict(chain[5], implementation_ready=True),
                    dict(chain[5], execution_allowed=True)):
            r = self.status(5, bad)
            self.assertEqual(r["status"], "invalid_candidate")
            self.assertEqual([r[k] for k in LATER], [None] * 5)

    def test_invalid_readiness(self):
        chain = ten()
        for bad in (None, {}, dict(chain[6], extra=1), dict(chain[6], ready=False),
                    dict(chain[6], execution_allowed=True)):
            self.assertEqual(self.status(6, bad)["status"], "invalid_readiness")
        mismatched = evaluate_readiness(*swap(chain, ten(request_id="other"), 5)[:6])
        self.assertEqual(self.status(6, mismatched)["status"], "invalid_readiness")

    def test_invalid_design(self):
        chain = ten()
        for bad in (None, {}, dict(chain[7], extra=1), dict(chain[7], version="1"),
                    dict(chain[7], design_type="nonsense"),
                    dict(chain[7], implementation_ready=True),
                    dict(chain[7], execution_allowed=True)):
            r = self.status(7, bad)
            self.assertEqual(r["status"], "invalid_design")
            self.assertEqual([r[k] for k in LATER], [None] * 5)

    def test_invalid_design_validation_result(self):
        good = ten()[8]
        for bad in (None, {}, "valid", dict(good, extra=1), dict(good, version="1"),
                    dict(good, valid=False), dict(good, reason="other")):
            r = self.status(8, bad)
            self.assertEqual(r["status"], "invalid_design_validation", repr(bad))
            self.assertTrue(validate(r)["valid"])

    def test_well_formed_but_not_valid_design_validation_result(self):
        failing = check885(*swap(ten(), ten(request_id="other"), 7)[:8])
        self.assertEqual(failing["status"], "context_mismatch")
        self.assertEqual(self.status(8, failing)["status"], "invalid_design_validation")

    def test_invalid_blueprint(self):
        good = ten()[9]
        for bad in (None, {}, "x", dict(good, extra=1), dict(good, version="1"),
                    dict(good, blueprint_id=""), dict(good, implementation_steps=["x"]),
                    dict(good, implementation_steps=None)):
            r = self.status(9, bad)
            self.assertEqual(r["status"], "invalid_blueprint", repr(bad))
            self.assertEqual([r[k] for k in LATER], [None] * 5)
            self.assertTrue(validate(r)["valid"])
        missing = dict(good)
        del missing["purpose"]
        self.assertEqual(self.status(9, missing)["status"], "invalid_blueprint")

    def test_order_first_failure_wins(self):
        chain = ten()
        chain[1], chain[4], chain[9] = None, None, None
        self.assertEqual(run(chain)["status"], "invalid_analysis")
        chain = ten()
        chain[7], chain[8], chain[9] = None, None, None
        self.assertEqual(run(chain)["status"], "invalid_design")
        chain = ten()
        chain[8], chain[9] = None, None
        self.assertEqual(run(chain)["status"], "invalid_design_validation")
        chain = ten()
        chain[9] = None
        self.assertEqual(run(chain)["status"], "invalid_blueprint")


class ContextMismatchTests(unittest.TestCase):
    """Every object individually valid; the chain disagrees."""

    def mismatch(self, chain):
        r = run(chain)
        self.assertEqual(r["status"], "context_mismatch")
        self.assertIs(r["valid"], False)
        self.assertEqual(r["reason"], "context_mismatch")
        self.assertEqual([r[k] for k in LATER], [None] * 5)
        self.assertTrue(validate(r)["valid"])
        return r

    def test_request_mismatch(self):
        other = ten(request_id="evo_002")
        for i in (0, 2, 3, 4, 5, 6, 7, 8, 9):
            self.mismatch(swap(ten(), other, i))

    def test_capability_name_mismatch(self):
        other = ten(capability_name="other_cap")
        for i in (0, 3, 4, 5, 6, 7, 8, 9):
            self.mismatch(swap(ten(), other, i))

    def test_operation_mismatch(self):
        for i in (0, 4, 5, 6, 7, 8, 9):
            self.mismatch(swap(ten("create"), ten("improve"), i))
        self.mismatch(swap(ten("improve"), ten("create"), 9))

    def test_candidate_mismatch(self):
        self.mismatch(swap(ten(), ten(candidate_id="cand_002"), 5))
        chain = ten()
        chain[5] = dict(chain[5], inputs=["a_input", "z_input"])
        self.mismatch(chain)

    def test_readiness_mismatch(self):
        for other in (ten(plan_id="plan_9"), ten(proposal_id="prop_9"), ten(request_id="e9"),
                      ten(capability_name="other_cap"), ten("improve")):
            self.mismatch(swap(ten(), other, 6))

    def test_design_mismatch(self):
        for other in (ten(design_id="design_9"), ten(goal="x"), ten("improve"),
                      ten(candidate_id="cand_9"), ten(plan_id="plan_9")):
            self.mismatch(swap(ten(), other, 7))
        chain = ten()
        chain[7] = dict(chain[7], purpose="Forged purpose.")
        self.assertNotEqual(run(chain)["status"], "valid")

    def test_validation_result_mismatch(self):
        for other in (ten(design_id="design_9"), ten(plan_id="plan_9"),
                      ten(proposal_id="prop_9"), ten(candidate_id="cand_9"),
                      ten(request_id="evo_9"), ten(capability_name="other_cap"),
                      ten("improve")):
            self.assertEqual(other[8]["status"], "valid")
            self.mismatch(swap(ten(), other, 8))

    def test_forged_prompt885_result_fields(self):
        for key, value in (("design_id", "design_forged"), ("plan_id", "plan_forged"),
                           ("proposal_id", "prop_forged"), ("candidate_id", "cand_forged"),
                           ("request_id", "evo_forged"), ("capability_name", "forged_cap")):
            chain = ten()
            chain[8] = dict(chain[8], **{key: value})
            self.mismatch(chain)

    def test_blueprint_mismatch(self):
        for other in (ten(design_id="design_9"), ten(plan_id="plan_9"),
                      ten(proposal_id="prop_9"), ten(candidate_id="cand_9"),
                      ten(request_id="evo_9"), ten(goal="x"), ten(inputs=["q"]),
                      ten(outputs=["q"]), ten(constraints=["q"]), ten("improve")):
            self.mismatch(swap(ten(), other, 9))

    def test_forged_blueprint_fields(self):
        forgeries = {"purpose": "Forged purpose.", "inputs": ["a_input", "z_input"],
                     "outputs": ["only"], "constraints": ["Second.", "First."],
                     "plan_id": "plan_f", "proposal_id": "prop_f", "candidate_id": "cand_f",
                     "design_id": "design_f", "request_id": "evo_f",
                     "capability_name": "forged_cap"}
        for key, value in forgeries.items():
            chain = ten()
            chain[9] = dict(chain[9], **{key: value})
            self.assertTrue(validate_blueprint(chain[9])["valid"], key)
            self.mismatch(chain)

    def test_forged_blueprint_operation_and_steps(self):
        chain = ten("create")
        chain[9] = dict(chain[9], implementation_steps=list(ten("improve")[9]["implementation_steps"]))
        self.assertEqual(run(chain)["status"], "invalid_blueprint")
        chain = ten("create")
        chain[9] = dict(chain[9], operation="improve")
        self.assertNotEqual(run(chain)["status"], "valid")

    def test_blueprint_id_is_the_blueprints_own(self):
        r = run(ten(blueprint_id="bp_special"))
        self.assertEqual((r["status"], r["blueprint_id"]), ("valid", "bp_special"))

    def test_existing_capability_mismatch(self):
        base = ten("improve")
        other = ten("improve", caps=[desc(purpose="A different purpose.")])
        for i in (2, 3, 4, 5, 7, 9):
            self.mismatch(swap(base, other, i))
        chain = ten("improve")
        chain[9] = dict(chain[9], existing_capability=desc(version=2))
        self.mismatch(chain)

    def test_analysis_status_mismatch(self):
        self.mismatch(swap(ten("improve"), ten("create"), 9))
        self.mismatch(swap(ten("create"), ten("improve"), 1))

    def test_plan_proposal_id_mismatch(self):
        for field, a, b, idx in (("plan", "plan_001", "plan_002", (3, 5, 6, 7, 9)),
                                 ("proposal", "prop_001", "prop_002", (4, 5, 6, 7, 9))):
            base = ten(**{field + "_id": a})
            other = ten(**{field + "_id": b})
            for i in idx:
                self.mismatch(swap(base, other, i))

    def test_mismatch_preserves_only_trusted_identity(self):
        r = self.mismatch(swap(ten(), ten(capability_name="other_cap"), 9))
        self.assertEqual((r["request_id"], r["capability_name"], r["operation"],
                          r["analysis_status"]),
                         ("evo_001", "text_summarizer", "create", "create_required"))


class UnsupportedAndInternalTests(unittest.TestCase):
    def test_improve_or_conflict_never_valid(self):
        request = req(operation="create")
        analysis = analyze(request, [desc()])
        self.assertEqual(analysis["status"], "improve_or_conflict")
        for tail in (ten(), ten("improve")):
            chain = [request, analysis] + tail[2:]
            r = run(chain)
            self.assertNotEqual(r["status"], "valid")
            self.assertIs(r["valid"], False)
            self.assertTrue(validate(r)["valid"])

    def test_unsupported_combination_guard(self):
        with mock.patch.object(vmod, "SUPPORTED", (("improve", "improve_required",
                                                    "improve_capability",
                                                    "improve_implementation"),)):
            r = run(ten("create"))
        self.assertEqual(r["status"], "unsupported_status")
        self.assertIs(r["valid"], False)
        self.assertEqual(r["request_id"], "evo_001")
        self.assertEqual([r[k] for k in LATER], [None] * 5)
        self.assertTrue(validate(r)["valid"])

    def test_unsupported_operation_never_valid(self):
        for op in ("delete", "replace", "", None, 1):
            chain = ten()
            chain[0] = dict(chain[0], operation=op)
            self.assertNotEqual(run(chain)["status"], "valid", repr(op))
            chain = ten()
            chain[9] = dict(chain[9], operation=op)
            self.assertNotEqual(run(chain)["status"], "valid", repr(op))

    def test_execution_flags_true_elsewhere(self):
        for i in (0, 2, 3, 4):
            chain = ten()
            chain[i] = dict(chain[i], execution_allowed=True)
            self.assertNotEqual(run(chain)["status"], "valid")
        for key in ("implementation_ready", "execution_allowed"):
            chain = ten()
            chain[7] = dict(chain[7], **{key: True})
            self.assertEqual(run(chain)["status"], "invalid_design")

    def test_internal_failure(self):
        with mock.patch.object(vmod, "_chain_mismatch", side_effect=RuntimeError("x")):
            r = run(ten())
        self.assertEqual(r["status"], "validation_error")
        self.assertEqual([r[k] for k in ID_FIELDS], [None] * 9)
        self.assertTrue(validate(r)["valid"])


class ResultValidatorTests(unittest.TestCase):
    def good(self, op="create"):
        return ok(op)

    def test_valid_results_accepted(self):
        for chain in (ten(), ten("improve"), [None] * 10, swap(ten(), ten(goal="x"), 9)):
            self.assertTrue(validate(run(chain))["valid"])

    def test_all_status_shapes_accepted(self):
        for status in STATUSES:
            self.assertIn(status, vmod.STATUSES)
        self.assertEqual(sorted(vmod.STATUSES), sorted(STATUSES))

    def test_malformed_result(self):
        for bad in (None, [], "x", 5, (), set()):
            r = validate(bad)
            self.assertFalse(r["valid"])
            self.assertEqual(codes(r), ["result_not_dict"])
        self.assertFalse(validate()["valid"])

    def test_wrong_version_types(self):
        for bad in ("1", "2", 2, 0, True, False, 1.0, None, [1]):
            r = self.good()
            r["version"] = bad
            res = validate(r)
            self.assertFalse(res["valid"], repr(bad))
            self.assertIn("invalid_version", codes(res))

    def test_missing_keys(self):
        for key in KEYS:
            r = self.good()
            del r[key]
            res = validate(r)
            self.assertFalse(res["valid"], key)
            self.assertIn("missing_key", codes(res))

    def test_extra_keys(self):
        for extra in ("execution_allowed", "executed", "code", "ready", "blueprint"):
            r = self.good()
            r[extra] = False
            res = validate(r)
            self.assertFalse(res["valid"], extra)
            self.assertIn("unexpected_key", codes(res))
        r = self.good()
        r[5] = 1
        self.assertFalse(validate(r)["valid"])

    def test_invalid_status(self):
        for bad in ("done", "", None, 5, ["valid"], "VALID", True):
            r = self.good()
            r["status"] = bad
            self.assertFalse(validate(r)["valid"], repr(bad))

    def test_inconsistent_valid_status_reason(self):
        cases = [("valid", False), ("status", "context_mismatch")]
        r = self.good()
        r["valid"] = False
        self.assertIn("invalid_valid", codes(validate(r)))
        r = self.good()
        r["status"], r["reason"] = "context_mismatch", "context_mismatch"
        self.assertFalse(validate(r)["valid"])  # valid True with a failure status
        r = ok()
        r["reason"] = "other"
        self.assertIn("invalid_reason", codes(validate(r)))
        r = run(ten(request_id="a"))
        r2 = run(swap(ten(), ten(goal="x"), 9))
        r2["valid"] = True
        self.assertIn("invalid_valid", codes(validate(r2)))
        r2["valid"], r2["reason"] = False, "valid"
        self.assertIn("invalid_reason", codes(validate(r2)))
        for bad in (1, 0, None, "True"):
            r = self.good()
            r["valid"] = bad
            self.assertIn("invalid_valid", codes(validate(r)))
        self.assertTrue(cases)

    def test_invalid_identity_fields(self):
        bad_values = {"request_id": "bad\nid", "capability_name": "", "operation": "delete",
                      "analysis_status": "weird", "plan_id": "bad\nid", "proposal_id": None,
                      "candidate_id": "", "design_id": 5, "blueprint_id": "x" * 65}
        for key, bad in bad_values.items():
            r = self.good()
            r[key] = bad
            res = validate(r)
            self.assertFalse(res["valid"], key)
            self.assertIn("invalid_identity", codes(res))

    def test_valid_requires_all_trusted_identity_fields(self):
        for key in LATER:
            r = self.good()
            r[key] = None
            self.assertFalse(validate(r)["valid"], key)

    def test_valid_improve_or_conflict_rejected(self):
        r = self.good()
        r["analysis_status"] = "improve_or_conflict"
        self.assertFalse(validate(r)["valid"])
        r = self.good()
        r["operation"], r["analysis_status"] = "improve", "create_required"
        self.assertFalse(validate(r)["valid"])

    def test_untrusted_stage_identity_rules(self):
        r = run([None] * 10)
        r["request_id"] = "evo_001"
        self.assertFalse(validate(r)["valid"])
        r = run(ten())
        r["status"], r["valid"], r["reason"] = "invalid_analysis", False, "invalid_analysis"
        self.assertFalse(validate(r)["valid"])  # still carries later ids
        r = run(swap(ten(), ten(goal="x"), 9))
        r["plan_id"] = "plan_001"
        self.assertFalse(validate(r)["valid"])
        r = run(swap(ten(), ten(goal="x"), 9))
        r["blueprint_id"] = "bp_001"
        self.assertFalse(validate(r)["valid"])

    def test_validator_result_shape_and_never_raises(self):
        for r in (ok(), None, {}):
            res = validate(r)
            self.assertEqual(sorted(res), ["errors", "executed", "execution_allowed", "valid"])
            self.assertIs(res["execution_allowed"], False)
            self.assertIs(res["executed"], False)
            self.assertLessEqual(len(res["errors"]), 20)
        with mock.patch.object(vmod, "_result_errors", side_effect=RuntimeError("x")):
            res = validate(ok())
        self.assertEqual(codes(res), ["validation_error"])
        weird = ok()
        weird["plan_id"] = object()
        self.assertFalse(validate(weird)["valid"])


class SafetyTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for op in ("create", "improve"):
            chain = ten(op)
            snap = copy.deepcopy(chain)
            run(chain)
            self.assertEqual(chain, snap)
        bad = swap(ten(), ten(request_id="b"), 9)
        snap = copy.deepcopy(bad)
        run(bad)
        self.assertEqual(bad, snap)

    def test_trusted_chain_replacement_detected(self):
        chain = ten()
        before = run(chain)
        chain[9]["inputs"].append("tampered")
        self.assertNotEqual(run(chain)["status"], "valid")
        self.assertEqual(before["status"], "valid")
        chain = ten()
        chain[3]["inputs"] = ["tampered"]
        self.assertNotEqual(run(chain)["status"], "valid")

    def test_fresh_detached_results(self):
        chain = ten()
        a, b = run(chain), run(chain)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a["status"] = "x"
        self.assertEqual(run(chain)["status"], "valid")

    def test_deterministic_repeated_validation(self):
        for chain in (ten(), ten("improve"), swap(ten(), ten(goal="Other."), 3), [None] * 10):
            results = [run(chain) for _ in range(5)]
            self.assertTrue(all(r == results[0] for r in results))

    def test_type_strict_comparison(self):
        self.assertFalse(vmod._same(True, 1))
        self.assertFalse(vmod._same([1], (1,)))
        self.assertTrue(vmod._same({"a": [1, "b"]}, {"a": [1, "b"]}))

    def test_module_has_no_forbidden_imports_or_calls(self):
        path = os.path.join(ROOT, "capabilities",
                            "capability_implementation_blueprint_validation.py")
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
        self.assertEqual(len(vmod.STATUSES), 15)


if __name__ == "__main__":
    unittest.main()
