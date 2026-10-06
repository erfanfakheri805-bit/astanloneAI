"""
Prompt 890 - capability implementation boundary gate focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_implementation_boundary_prompt890 -v
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_implementation_boundary as rmod
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
    build_capability_implementation_blueprint as build_blueprint)
from capabilities.capability_implementation_blueprint_validation import (
    validate_capability_implementation_blueprint_context as check887)
from capabilities.capability_implementation_contract import (
    build_capability_implementation_contract as build_contract,
    validate_capability_implementation_contract as validate_contract)
from capabilities.capability_implementation_boundary import (
    evaluate_capability_implementation_boundary as evaluate,
    validate_capability_implementation_boundary_result as validate)
from capabilities.capability_implementation_contract_readiness import (
    evaluate_capability_implementation_contract_readiness as evaluate889,
    validate_capability_implementation_contract_readiness as validate889)
from capabilities.capability_implementation_design import (
    build_capability_implementation_design as build_design)
from capabilities.capability_implementation_design_validation import (
    validate_capability_implementation_design_context as check885)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["version", "contract_id", "request_id", "operation", "capability_name", "purpose",
        "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
        "plan_id", "proposal_id", "candidate_id", "design_id", "blueprint_id", "requirements"]
CREATE_REQ = ["interface_must_be_defined", "inputs_must_be_validated",
              "outputs_must_be_defined", "constraints_must_be_respected",
              "behavior_boundary_must_be_defined", "tests_must_cover_required_behavior"]
IMPROVE_REQ = ["existing_behavior_must_be_preserved", "interface_delta_must_be_defined",
               "inputs_must_be_validated", "outputs_must_remain_valid",
               "constraints_must_be_respected", "regression_tests_must_cover_existing_behavior"]


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


def eleven(op="create", caps=None, plan_id="plan_001", proposal_id="prop_001",
           candidate_id="cand_001", design_id="design_001", blueprint_id="bp_001", **req_over):
    """[request, analysis, spec, plan, proposal, candidate, readiness, design, vresult885,
    blueprint, bresult887]."""
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
    bresult = check887(*chain, vresult, blueprint)
    return chain + [vresult, blueprint, bresult]


KEYS = ["version", "status", "ready", "request_id", "capability_name", "operation",
        "analysis_status", "plan_id", "contract_id", "reason", "execution_allowed",
        "executed", "implementation_started", "implementation_allowed"]
IDENT = ["request_id", "capability_name", "operation"]


def fourteen(op="create", caps=None, contract_id="ct_001", **kw):
    """[request .. bresult887, contract, contract validation result, 889 readiness result]."""
    chain = eleven(op, caps, **kw)
    contract = build_contract(*chain, contract_id)["contract"]
    creport = validate_contract(contract)
    r889 = evaluate889(*chain, contract, creport)
    return chain + [contract, creport, r889]


def rmod_889_not_ready():
    from capabilities import capability_implementation_contract_readiness as m889
    return m889._result("not_ready", req(), "create_required")


def swap(base, other, *indexes):
    out = list(base)
    for i in indexes:
        out[i] = other[i]
    return out


def run(chain):
    return evaluate(*chain)


def ok(op="create"):
    return run(fourteen(op))


def codes(result):
    return [e["code"] for e in result["errors"]]


class IntegerVersionTests(unittest.TestCase):
    def test_prompt884_design_version_still_integer(self):
        for op in ("create", "improve"):
            self.assertIs(type(eleven(op)[7]["version"]), int)
            self.assertEqual(eleven(op)[7]["version"], 1)

    def test_readiness_version_is_integer_one(self):
        for op in ("create", "improve"):
            r = ok(op)
            self.assertIs(type(r["version"]), int)
            self.assertEqual(r["version"], 1)

    def test_wrong_version_types_rejected(self):
        for bad in ("1", 1.0, True, None, 2, 0, [1], b"1"):
            r = ok()
            r["version"] = bad
            self.assertFalse(validate(r)["valid"], repr(bad))
            self.assertIn("invalid_version", codes(validate(r)))


class ValidReadinessTests(unittest.TestCase):
    def test_valid_create(self):
        chain = fourteen("create")
        r = run(chain)
        self.assertEqual(r["status"], "ready")
        self.assertIs(r["ready"], True)
        self.assertEqual(r["operation"], "create")
        self.assertEqual(r["analysis_status"], "create_required")
        self.assertEqual(r["contract_id"], chain[11]["contract_id"])
        self.assertEqual(r["plan_id"], "plan_001")
        self.assertIs(r["implementation_allowed"], False)
        self.assertEqual(r["reason"], "ready")
        self.assertTrue(validate(r)["valid"])

    def test_valid_improve(self):
        r = ok("improve")
        self.assertEqual(r["status"], "ready")
        self.assertIs(r["ready"], True)
        self.assertEqual(r["operation"], "improve")
        self.assertEqual(r["analysis_status"], "improve_required")
        self.assertEqual(r["contract_id"], "ct_001")
        self.assertTrue(validate(r)["valid"])

    def test_exactly_fourteen_keys(self):
        for chain in (fourteen(), fourteen("improve"), [None] * 14):
            self.assertEqual(sorted(run(chain)), sorted(KEYS))
        self.assertEqual(list(rmod.RESULT_KEYS), KEYS)

    def test_identity_taken_from_trusted_chain(self):
        r = ok()
        self.assertEqual((r["request_id"], r["capability_name"]), ("evo_001", "text_summarizer"))

    def test_other_contract_ids_accepted(self):
        r = run(fourteen(contract_id="another_contract"))
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["contract_id"], "another_contract")

    def test_execution_flags_always_false(self):
        for chain in (fourteen(), fourteen("improve"), [None] * 14,
                      swap(fourteen(), fourteen(goal="x"), 7)):
            r = run(chain)
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)


class InvalidObjectTests(unittest.TestCase):
    def check(self, chain, status):
        r = run(chain)
        self.assertEqual(r["status"], status)
        self.assertIs(r["ready"], False)
        self.assertEqual(r["reason"], status)
        self.assertIsNone(r["plan_id"])
        self.assertIsNone(r["contract_id"])
        self.assertTrue(validate(r)["valid"], validate(r))
        return r

    def with_(self, index, value, op="create"):
        chain = fourteen(op)
        chain[index] = value
        return chain

    def test_invalid_request(self):
        for bad in (None, {}, "x", dict(fourteen()[0], request_id="")):
            r = self.check(self.with_(0, bad), "invalid_request")
            for key in IDENT + ["analysis_status"]:
                self.assertIsNone(r[key])

    def test_invalid_analysis(self):
        r = self.check(self.with_(1, {"status": "create_required"}), "invalid_analysis")
        self.assertEqual(r["request_id"], "evo_001")
        self.assertIsNone(r["analysis_status"])

    def test_invalid_specification(self):
        r = self.check(self.with_(2, None), "invalid_specification")
        self.assertEqual(r["analysis_status"], "create_required")

    def test_invalid_validation_context(self):
        with mock.patch.object(rmod, "validate_capability_evolution_result",
                               return_value={"valid": False}):
            self.check(fourteen(), "invalid_validation")

    def test_invalid_plan(self):
        self.check(self.with_(3, {}), "invalid_plan")

    def test_invalid_proposal(self):
        self.check(self.with_(4, None), "invalid_proposal")

    def test_invalid_candidate(self):
        chain = fourteen()
        chain[5] = dict(chain[5], candidate_id="")
        self.check(chain, "invalid_candidate")

    def test_invalid_readiness(self):
        self.check(self.with_(6, {"status": "ready"}), "invalid_readiness")

    def test_readiness_not_ready(self):
        chain = fourteen()
        chain[6] = dict(chain[6], status="not_ready", ready=False, reason="not_ready")
        self.assertNotEqual(run(chain)["status"], "ready")

    def test_invalid_design(self):
        chain = fourteen()
        chain[7] = dict(chain[7], design_id="bad\nid")
        self.check(chain, "invalid_design")

    def test_invalid_prompt885_validation_result(self):
        self.check(self.with_(8, {}), "invalid_design_validation")

    def test_invalid_blueprint(self):
        chain = fourteen()
        chain[9] = dict(chain[9], blueprint_id="")
        self.check(chain, "invalid_blueprint")

    def test_invalid_prompt887_validation_result(self):
        self.check(self.with_(10, None), "invalid_blueprint_validation")
        chain = fourteen()
        chain[10] = dict(chain[10], status="context_mismatch", valid=False,
                         reason="context_mismatch")
        self.check(chain, "invalid_blueprint_validation")

    def test_invalid_contract(self):
        r = self.check(self.with_(11, None), "invalid_contract")
        self.assertEqual(r["analysis_status"], "create_required")
        chain = fourteen()
        chain[11] = dict(chain[11], requirements=[])
        self.check(chain, "invalid_contract")

    def test_invalid_contract_validation_result(self):
        bad_values = (None, {}, [], {"valid": True}, {"valid": False, "errors": [],
                      "execution_allowed": False, "executed": False},
                      {"valid": True, "errors": [{"code": "x", "where": "y"}],
                       "execution_allowed": False, "executed": False},
                      {"valid": 1, "errors": [], "execution_allowed": False, "executed": False},
                      {"valid": True, "errors": (), "execution_allowed": False,
                       "executed": False})
        for bad in bad_values:
            self.check(self.with_(12, bad), "invalid_contract_validation")

    def test_order_first_failure_wins(self):
        chain = fourteen()
        chain[12] = None
        chain[11] = None
        self.assertEqual(run(chain)["status"], "invalid_contract")
        chain[9] = None
        self.assertEqual(run(chain)["status"], "invalid_blueprint")
        chain[4] = None
        self.assertEqual(run(chain)["status"], "invalid_proposal")
        chain[0] = None
        self.assertEqual(run(chain)["status"], "invalid_request")

    def test_no_arguments(self):
        r = evaluate()
        self.assertEqual(r["status"], "invalid_request")
        self.assertTrue(validate(r)["valid"])


class ContextMismatchTests(unittest.TestCase):
    def mismatch(self, chain):
        r = run(chain)
        self.assertEqual(r["status"], "context_mismatch", r)
        self.assertIs(r["ready"], False)
        self.assertIsNone(r["plan_id"])
        self.assertIsNone(r["contract_id"])
        self.assertTrue(validate(r)["valid"])

    def test_request_mismatch(self):
        base = fourteen()
        self.mismatch(swap(base, fourteen(request_id="evo_2"), 0))

    def test_capability_name_mismatch(self):
        self.mismatch(swap(fourteen(), fourteen(capability_name="other_cap"), 0))

    def test_candidate_mismatch(self):
        self.mismatch(swap(fourteen(), fourteen(candidate_id="cand_2"), 5))

    def test_readiness_mismatch(self):
        self.mismatch(swap(fourteen(), fourteen(plan_id="plan_9"), 6))

    def test_design_mismatch(self):
        self.mismatch(swap(fourteen(), fourteen(design_id="design_2"), 7))

    def test_prompt885_result_mismatch(self):
        self.mismatch(swap(fourteen(), fourteen(design_id="design_2"), 8))

    def test_blueprint_mismatch(self):
        self.mismatch(swap(fourteen(), fourteen(blueprint_id="bp_2"), 9))

    def test_prompt887_result_mismatch(self):
        self.mismatch(swap(fourteen(), fourteen(blueprint_id="bp_2"), 10))

    def test_contract_mismatch(self):
        other = fourteen(blueprint_id="bp_2")
        self.mismatch(swap(fourteen(), other, 11, 12, 13))
        self.mismatch(swap(fourteen(), fourteen(plan_id="plan_2"), 11, 12, 13))
        self.mismatch(swap(fourteen(), fourteen(request_id="evo_3"), 11, 12, 13))

    def test_contract_from_other_operation(self):
        self.mismatch(swap(fourteen("create"), fourteen("improve"), 11, 12, 13))

    def test_forged_individually_valid_everywhere(self):
        base = fourteen()
        for i, other in ((2, fourteen(goal="Another goal.")), (3, fourteen(plan_id="plan_2")),
                         (4, fourteen(outputs=["x_out"])), (5, fourteen(request_id="evo_2")),
                         (6, fourteen(plan_id="plan_3")), (7, fourteen(proposal_id="prop_2")),
                         (9, fourteen(design_id="design_2"))):
            self.mismatch(swap(base, other, i))

    def test_forged_contract_fields(self):
        for key, value in (("purpose", "Another purpose."), ("inputs", ["x"]),
                           ("outputs", ["z_out"]), ("constraints", ["Only."]),
                           ("plan_id", "plan_999"), ("proposal_id", "prop_999"),
                           ("candidate_id", "cand_999"), ("design_id", "design_999"),
                           ("blueprint_id", "bp_999"), ("capability_name", "forged_cap"),
                           ("request_id", "evo_999"), ("contract_id", "ct_999")):
            chain = fourteen()
            chain[11] = dict(chain[11], **{key: value})
            chain[12] = validate_contract(chain[11])
            self.assertTrue(chain[12]["valid"], key)  # individually valid forgery
            if key == "contract_id":
                chain[13] = evaluate889(*chain[:11], chain[11], chain[12])
            r = run(chain)
            if key == "contract_id":
                self.assertEqual(r["status"], "ready")  # caller-supplied id is free
                self.assertEqual(r["contract_id"], "ct_999")
            else:
                self.assertEqual(r["status"], "context_mismatch", key)

    def test_forged_contract_existing_capability(self):
        chain = fourteen("improve")
        chain[11] = dict(chain[11], existing_capability=desc(version=2))
        chain[12] = validate_contract(chain[11])
        self.assertEqual(run(chain)["status"], "context_mismatch")

    def test_forged_contract_requirements_reordered(self):
        chain = fourteen()
        chain[11] = dict(chain[11], requirements=list(reversed(chain[11]["requirements"])))
        self.assertEqual(run(chain)["status"], "invalid_contract")

    def test_forged_contract_validation_result(self):
        chain = fourteen()
        forged = dict(chain[12], extra=1)
        chain[12] = forged
        self.assertEqual(run(chain)["status"], "invalid_contract_validation")
        chain = fourteen()
        chain[12] = {"valid": True, "errors": [], "execution_allowed": False, "executed": True}
        self.assertEqual(run(chain)["status"], "invalid_contract_validation")

    def test_readiness_result_not_matching_derived(self):
        chain = fourteen()
        other = fourteen(contract_id="ct_other")[13]
        chain[13] = other
        self.mismatch(chain)
        with mock.patch.object(rmod, "evaluate_capability_implementation_contract_readiness",
                               return_value=dict(chain[13], plan_id="plan_x")):
            self.assertEqual(run(fourteen())["status"], "context_mismatch")

    def test_forged_readiness_result_fields(self):
        for key, value in (("request_id", "evo_999"), ("capability_name", "forged"),
                           ("plan_id", "plan_999"), ("proposal_id", "prop_999"),
                           ("contract_id", "ct_999"), ("analysis_status", "improve_required"),
                           ("operation", "improve")):
            chain = fourteen()
            chain[13] = dict(chain[13], **{key: value})
            r = run(chain)
            self.assertNotEqual(r["status"], "ready", key)
            self.assertIs(r["implementation_allowed"], False)

    def test_readiness_result_not_ready_rejected(self):
        chain = fourteen()
        chain[13] = rmod_889_not_ready()
        self.assertEqual(run(chain)["status"], "invalid_contract_readiness")

    def test_type_sensitive_comparison(self):
        chain = fourteen()
        chain[11] = dict(chain[11], version=True)
        self.assertEqual(run(chain)["status"], "invalid_contract")
        self.assertFalse(rmod._same(True, 1))
        self.assertFalse(rmod._same([1], (1,)))
        self.assertTrue(rmod._same({"a": [1, "b"]}, {"a": [1, "b"]}))

    def test_analysis_status_mismatch(self):
        self.mismatch(swap(fourteen("improve"), fourteen("create"), 9, 10))


class UnsupportedAndInternalTests(unittest.TestCase):
    def test_improve_or_conflict_never_ready(self):
        request = req(operation="create")
        analysis = analyze(request, [desc()])
        self.assertEqual(analysis["status"], "improve_or_conflict")
        spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
        for tail in (fourteen()[3:], fourteen("improve")[3:]):
            r = run([request, analysis, spec] + tail)
            self.assertEqual(r["status"], "unsupported_status")
            self.assertIs(r["ready"], False)
            self.assertEqual(r["analysis_status"], "improve_or_conflict")
            self.assertIsNone(r["plan_id"])
            self.assertIsNone(r["contract_id"])
            self.assertTrue(validate(r)["valid"])

    def test_unsupported_combination_guard(self):
        with mock.patch.object(rmod, "SUPPORTED", (("improve", "improve_required",
                                                    "improve_capability",
                                                    "improve_implementation"),)):
            r = run(fourteen("create"))
        self.assertEqual(r["status"], "unsupported_status")
        self.assertIs(r["ready"], False)
        self.assertIsNone(r["contract_id"])

    def test_unsupported_operations_rejected(self):
        for op in ("delete", "replace", "", None, 1):
            chain = fourteen()
            chain[0] = dict(chain[0], operation=op)
            self.assertNotEqual(run(chain)["status"], "ready", repr(op))

    def test_internal_failure(self):
        with mock.patch.object(rmod, "_readiness_mismatch", side_effect=RuntimeError("x")):
            r = run(fourteen())
        self.assertEqual(r["status"], "validation_error")
        self.assertIs(r["ready"], False)
        for key in IDENT + ["plan_id", "contract_id", "analysis_status"]:
            self.assertIsNone(r[key])
        self.assertTrue(validate(r)["valid"])

    def test_not_ready_status_is_valid_but_never_produced(self):
        r = rmod._result("not_ready", req(), "create_required")
        self.assertTrue(validate(r)["valid"], validate(r))
        self.assertIs(r["ready"], False)
        self.assertEqual(r["reason"], "not_ready")


class ResultValidatorTests(unittest.TestCase):
    def test_malformed_result(self):
        for bad in (None, [], "x", 5, (), set()):
            r = validate(bad)
            self.assertFalse(r["valid"])
            self.assertEqual(codes(r), ["result_not_dict"])
        self.assertFalse(validate()["valid"])

    def test_missing_keys(self):
        for key in KEYS:
            r = ok()
            del r[key]
            self.assertIn("missing_key", codes(validate(r)), key)

    def test_extra_keys(self):
        for extra in ("code", "path", "contract", "implementation_ready", "errors"):
            r = ok()
            r[extra] = False
            v = validate(r)
            self.assertFalse(v["valid"], extra)
            self.assertIn("unexpected_key", codes(v))

    def test_wrong_types(self):
        for key, bad in (("status", 5), ("status", "bogus"), ("ready", 1), ("ready", "True"),
                         ("reason", None), ("reason", "other"), ("request_id", 5),
                         ("capability_name", ""), ("operation", "delete"),
                         ("analysis_status", "bogus"), ("plan_id", ""), ("proposal_id", 3),
                         ("contract_id", None), ("contract_id", "bad\nid")):
            r = ok()
            r[key] = bad
            self.assertFalse(validate(r)["valid"], (key, bad))

    def test_invalid_identity_fields(self):
        for key in ("request_id", "capability_name", "operation"):
            r = ok()
            r[key] = None
            self.assertIn("invalid_identity", codes(validate(r)), key)

    def test_inconsistent_ready_status_reason(self):
        r = ok()
        r["ready"] = False
        self.assertFalse(validate(r)["valid"])
        r = ok()
        r["status"] = "not_ready"
        self.assertFalse(validate(r)["valid"])
        r = ok()
        r["reason"] = "not_ready"
        self.assertFalse(validate(r)["valid"])
        r = run(swap(fourteen(), fourteen(goal="x"), 7))
        r["ready"] = True
        self.assertFalse(validate(r)["valid"])
        r = rmod._result("unsupported_status")
        r["ready"] = True
        r["reason"] = "ready"
        self.assertFalse(validate(r)["valid"])

    def test_ready_requires_ids_and_supported_pair(self):
        r = ok()
        r["analysis_status"] = "improve_required"
        self.assertFalse(validate(r)["valid"])
        r = ok()
        r["analysis_status"] = "improve_or_conflict"
        self.assertFalse(validate(r)["valid"])
        for key in ("plan_id", "contract_id"):
            r = ok()
            r[key] = None
            self.assertFalse(validate(r)["valid"], key)

    def test_untrusted_stages_cannot_leak_identity(self):
        for status in rmod.STATUSES:
            if status == "ready":
                continue
            for key in ("plan_id", "contract_id"):
                r = rmod._result(status, req(), "create_required")
                r[key] = "leaked"
                self.assertFalse(validate(r)["valid"], (status, key))
        for status in ("invalid_request", "validation_error"):
            r = rmod._result(status)
            r["request_id"] = "leaked"
            self.assertFalse(validate(r)["valid"], status)
        r = rmod._result("invalid_analysis", req(), "create_required")
        self.assertFalse(validate(r)["valid"])

    def test_execution_flags_forced_true(self):
        for key in ("execution_allowed", "executed", "implementation_started",
                    "implementation_allowed"):
            for bad in (True, 1, None, "False", 0):
                for op in ("create", "improve"):
                    r = ok(op)
                    r[key] = bad
                    v = validate(r)
                    self.assertFalse(v["valid"], (key, bad))
                    self.assertIn("invalid_flag", codes(v))

    def test_ready_result_implementation_allowed_true_fails(self):
        r = ok()
        self.assertEqual(r["status"], "ready")
        r["implementation_allowed"] = True
        self.assertFalse(validate(r)["valid"])

    def test_ready_result_implementation_started_true_fails(self):
        r = ok()
        r["implementation_started"] = True
        self.assertFalse(validate(r)["valid"])

    def test_ready_never_allows_implementation(self):
        for op in ("create", "improve"):
            r = ok(op)
            self.assertIs(r["ready"], True)
            self.assertIs(r["implementation_allowed"], False)
            self.assertIs(r["implementation_started"], False)

    def test_validator_result_shape_and_never_raises(self):
        for r in (ok(), None, {}):
            v = validate(r)
            self.assertEqual(sorted(v), ["errors", "executed", "execution_allowed", "valid"])
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)
            self.assertLessEqual(len(v["errors"]), 20)
        r = ok()
        r["status"] = object()
        self.assertFalse(validate(r)["valid"])
        with mock.patch.object(rmod, "_result_errors", side_effect=RuntimeError("x")):
            self.assertEqual(codes(validate(ok())), ["validation_error"])

    def test_every_status_result_validates(self):
        for status in rmod.STATUSES:
            if status == "ready":
                continue
            for r in (rmod._result(status), rmod._result(status, req(), "create_required"),
                      rmod._result(status, req(operation="improve"), "improve_required")):
                v = validate(r)
                if status in ("invalid_request", "validation_error"):
                    if r["request_id"] is None:
                        self.assertTrue(v["valid"], (status, v))
                elif status == "invalid_analysis":
                    pass
                elif r["request_id"] is not None:
                    self.assertTrue(v["valid"], (status, v))


class SafetyTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for op in ("create", "improve"):
            chain = fourteen(op)
            snap = copy.deepcopy(chain)
            run(chain)
            self.assertEqual(chain, snap)
        bad = swap(fourteen(), fourteen(request_id="b"), 11, 12, 13)
        snap = copy.deepcopy(bad)
        run(bad)
        self.assertEqual(bad, snap)

    def test_fresh_results_and_determinism(self):
        for op in ("create", "improve"):
            chain = fourteen(op)
            results = [run(chain) for _ in range(5)]
            self.assertTrue(all(r == results[0] for r in results))
            self.assertIsNot(results[0], results[1])
        bad = swap(fourteen(), fourteen(goal="Other."), 3)
        results = [run(bad) for _ in range(3)]
        self.assertTrue(all(r == results[0] for r in results))

    def test_result_validator_does_not_mutate(self):
        r = ok()
        snap = copy.deepcopy(r)
        validate(r)
        self.assertEqual(r, snap)

    def test_ready_only_when_whole_chain_valid(self):
        chain = fourteen()
        self.assertEqual(run(chain)["status"], "ready")
        for i in range(14):
            broken = list(chain)
            broken[i] = None
            self.assertNotEqual(run(broken)["status"], "ready", i)

    def test_constants(self):
        self.assertEqual(len(rmod.STATUSES), 20)
        for status in ("ready", "not_ready", "invalid_contract", "invalid_contract_validation",
                       "invalid_contract_readiness", "context_mismatch", "unsupported_status", "validation_error"):
            self.assertIn(status, rmod.STATUSES)
        self.assertEqual(rmod.BOUNDARY_VERSION, 1)

    def test_module_has_no_forbidden_imports_or_calls(self):
        path = os.path.join(ROOT, "capabilities", "capability_implementation_contract_readiness.py")
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


if __name__ == "__main__":
    unittest.main()
