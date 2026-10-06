"""
Prompt 888 - capability implementation contract focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_implementation_contract_prompt888 -v
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_implementation_contract as cmod
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
    build_capability_implementation_contract as build,
    validate_capability_implementation_contract as validate)
from capabilities.capability_implementation_design import (
    build_capability_implementation_design as build_design,
    validate_capability_implementation_design as validate_design)
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


def swap(base, other, *indexes):
    out = list(base)
    for i in indexes:
        out[i] = other[i]
    return out


def run(chain, contract_id="ct_001"):
    return build(*chain, contract_id)


def ok(op="create"):
    return run(eleven(op))


def codes(result):
    return [e["code"] for e in result["errors"]]


class IntegerVersionTests(unittest.TestCase):
    def test_prompt884_design_version_still_integer(self):
        for op in ("create", "improve"):
            d = eleven(op)[7]
            self.assertIs(type(d["version"]), int)
            self.assertEqual(d["version"], 1)
            self.assertTrue(validate_design(d)["valid"])
            for bad in ("1", 2, True, 1.0, None):
                self.assertFalse(validate_design(dict(d, version=bad))["valid"], bad)

    def test_contract_version_is_integer_one(self):
        for op in ("create", "improve"):
            c = ok(op)["contract"]
            self.assertEqual(c["version"], 1)
            self.assertIs(type(c["version"]), int)
        self.assertIs(type(cmod.CONTRACT_VERSION), int)

    def test_wrong_version_types_rejected(self):
        for bad in ("1", "2", 2, 0, True, False, 1.0, None, [1], {"v": 1}):
            c = ok()["contract"]
            c["version"] = bad
            r = validate(c)
            self.assertFalse(r["valid"], repr(bad))
            self.assertIn("invalid_version", codes(r))


class ValidContractTests(unittest.TestCase):
    def test_valid_create(self):
        r = ok("create")
        self.assertEqual(r["status"], "ready")
        c = r["contract"]
        self.assertEqual((c["operation"], c["analysis_status"]), ("create", "create_required"))
        self.assertIsNone(c["existing_capability"])
        self.assertEqual(c["requirements"], CREATE_REQ)
        self.assertTrue(validate(c)["valid"])

    def test_valid_improve(self):
        r = ok("improve")
        self.assertEqual(r["status"], "ready")
        c = r["contract"]
        self.assertEqual((c["operation"], c["analysis_status"]), ("improve", "improve_required"))
        self.assertEqual(c["existing_capability"], desc())
        self.assertEqual(c["requirements"], IMPROVE_REQ)
        self.assertTrue(validate(c)["valid"])

    def test_exactly_seventeen_keys(self):
        for op in ("create", "improve"):
            self.assertEqual(sorted(ok(op)["contract"]), sorted(KEYS))
        self.assertEqual(len(KEYS), 17)
        self.assertEqual(list(cmod.FIELDS), KEYS)

    def test_builder_result_shape(self):
        for chain in (eleven(), [None] * 11):
            r = run(chain)
            self.assertEqual(sorted(r), ["contract", "executed", "execution_allowed", "status"])
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)
        self.assertIsNone(run([None] * 11)["contract"])

    def test_values_preserved_exactly(self):
        c = ok()["contract"]
        self.assertEqual(c["purpose"], "Summarize short documents.")
        self.assertEqual(c["inputs"], ["z_input", "a_input"])
        self.assertEqual(c["outputs"], ["z_out", "a_out"])
        self.assertEqual(c["constraints"], ["Second.", "First.", "Second."])
        self.assertEqual((c["request_id"], c["capability_name"]), ("evo_001", "text_summarizer"))

    def test_all_trusted_ids_preserved(self):
        chain = eleven(plan_id="my_plan", proposal_id="my_prop", candidate_id="my_cand",
                       design_id="my_design", blueprint_id="my_bp")
        c = run(chain, "my_ct")["contract"]
        self.assertEqual([c[k] for k in ("contract_id", "plan_id", "proposal_id", "candidate_id",
                                         "design_id", "blueprint_id")],
                         ["my_ct", "my_plan", "my_prop", "my_cand", "my_design", "my_bp"])

    def test_no_execution_or_implementation_claims(self):
        c = ok()["contract"]
        for flag in ("execution_allowed", "executed", "implementation_ready", "implemented"):
            self.assertNotIn(flag, c)


class ContractIdTests(unittest.TestCase):
    def test_caller_supplied_contract_id_kept(self):
        for cid in ("ct_1", "x", "Contract-42", "a" * 64):
            r = run(eleven(), cid)
            self.assertEqual(r["status"], "ready", cid)
            self.assertEqual(r["contract"]["contract_id"], cid)

    def test_missing_or_invalid_contract_id(self):
        for bad in (None, "", " ", "bad\nid", "x" * 65, 5, True, [], {}, b"x"):
            r = run(eleven(), bad)
            self.assertEqual(r["status"], "invalid_contract_id", repr(bad))
            self.assertIsNone(r["contract"])

    def test_no_generated_id(self):
        self.assertEqual(build(*eleven())["status"], "invalid_contract_id")

    def test_validator_rejects_bad_contract_id(self):
        for bad in (None, "", "bad\nid", "x" * 65, 5):
            c = ok()["contract"]
            c["contract_id"] = bad
            r = validate(c)
            self.assertFalse(r["valid"], repr(bad))
            self.assertIn("invalid_contract_id", codes(r))


class InvalidObjectTests(unittest.TestCase):
    def status(self, index, bad):
        chain = eleven()
        chain[index] = bad
        return run(chain)

    def test_invalid_request(self):
        for bad in (None, {}, dict(req(), goal=5)):
            self.assertEqual(self.status(0, bad)["status"], "invalid_request")

    def test_invalid_analysis(self):
        self.assertEqual(self.status(1, {"status": "create_required"})["status"],
                         "invalid_analysis")

    def test_invalid_specification(self):
        self.assertEqual(self.status(2, dict(eleven()[2], specification_id=""))["status"],
                         "invalid_specification")

    def test_invalid_validation_context(self):
        with mock.patch.object(cmod, "validate_capability_evolution", return_value={"x": 1}):
            r = run(eleven())
        self.assertEqual(r["status"], "invalid_validation")
        self.assertIsNone(r["contract"])

    def test_invalid_plan(self):
        for bad in (None, dict(eleven()[3], plan_id="bad\nid")):
            self.assertEqual(self.status(3, bad)["status"], "invalid_plan")

    def test_invalid_proposal(self):
        self.assertEqual(self.status(4, dict(eleven()[4], proposal_type="x"))["status"],
                         "invalid_proposal")

    def test_invalid_candidate(self):
        chain = eleven()
        for bad in (None, {"version": "1"}, dict(chain[5], extra=1),
                    dict(chain[5], execution_allowed=True)):
            self.assertEqual(self.status(5, bad)["status"], "invalid_candidate")

    def test_invalid_readiness(self):
        chain = eleven()
        for bad in (None, {}, dict(chain[6], extra=1), dict(chain[6], ready=False),
                    dict(chain[6], execution_allowed=True)):
            self.assertEqual(self.status(6, bad)["status"], "invalid_readiness")

    def test_invalid_design(self):
        chain = eleven()
        for bad in (None, {}, dict(chain[7], extra=1), dict(chain[7], version="1"),
                    dict(chain[7], implementation_ready=True),
                    dict(chain[7], execution_allowed=True)):
            self.assertEqual(self.status(7, bad)["status"], "invalid_design")

    def test_invalid_prompt885_validation_result(self):
        good = eleven()[8]
        for bad in (None, {}, "valid", dict(good, extra=1), dict(good, version="1"),
                    dict(good, valid=False), dict(good, reason="other")):
            self.assertEqual(self.status(8, bad)["status"], "invalid_design_validation",
                             repr(bad))
        failing = check885(*swap(eleven(), eleven(request_id="other"), 7)[:8])
        self.assertEqual(failing["status"], "context_mismatch")
        self.assertEqual(self.status(8, failing)["status"], "invalid_design_validation")

    def test_invalid_blueprint(self):
        good = eleven()[9]
        for bad in (None, {}, "x", dict(good, extra=1), dict(good, version="1"),
                    dict(good, blueprint_id=""), dict(good, implementation_steps=["x"])):
            self.assertEqual(self.status(9, bad)["status"], "invalid_blueprint", repr(bad))

    def test_invalid_prompt887_validation_result(self):
        good = eleven()[10]
        for bad in (None, {}, "valid", dict(good, extra=1), dict(good, version="1"),
                    dict(good, valid=False), dict(good, reason="other"),
                    dict(good, execution_allowed=False)):
            self.assertEqual(self.status(10, bad)["status"], "invalid_blueprint_validation",
                             repr(bad))

    def test_well_formed_but_not_valid_prompt887_result(self):
        failing = check887(*swap(eleven(), eleven(request_id="other"), 9)[:10])
        self.assertEqual(failing["status"], "context_mismatch")
        r = self.status(10, failing)
        self.assertEqual(r["status"], "invalid_blueprint_validation")
        self.assertIsNone(r["contract"])

    def test_order_first_failure_wins(self):
        chain = eleven()
        chain[1], chain[4], chain[10] = None, None, None
        self.assertEqual(run(chain)["status"], "invalid_analysis")
        chain = eleven()
        chain[7], chain[8], chain[9], chain[10] = None, None, None, None
        self.assertEqual(run(chain)["status"], "invalid_design")
        chain = eleven()
        chain[8], chain[9], chain[10] = None, None, None
        self.assertEqual(run(chain)["status"], "invalid_design_validation")
        chain = eleven()
        chain[9], chain[10] = None, None
        self.assertEqual(run(chain)["status"], "invalid_blueprint")
        chain = eleven()
        chain[10] = None
        self.assertEqual(run(chain, None)["status"], "invalid_blueprint_validation")

    def test_no_arguments(self):
        self.assertEqual(build()["status"], "invalid_request")


class ContextMismatchTests(unittest.TestCase):
    """Every object individually valid; the chain disagrees."""

    def mismatch(self, chain):
        r = run(chain)
        self.assertEqual(r["status"], "context_mismatch")
        self.assertIsNone(r["contract"])
        return r

    def test_request_mismatch(self):
        other = eleven(request_id="evo_002")
        for i in (0, 2, 3, 4, 5, 6, 7, 8, 9, 10):
            self.mismatch(swap(eleven(), other, i))

    def test_capability_name_mismatch(self):
        other = eleven(capability_name="other_cap")
        for i in (0, 3, 4, 5, 6, 7, 8, 9, 10):
            self.mismatch(swap(eleven(), other, i))

    def test_operation_mismatch(self):
        for i in (0, 4, 5, 6, 7, 8, 9, 10):
            self.mismatch(swap(eleven("create"), eleven("improve"), i))

    def test_candidate_mismatch(self):
        self.mismatch(swap(eleven(), eleven(candidate_id="cand_002"), 5))
        chain = eleven()
        chain[5] = dict(chain[5], inputs=["a_input", "z_input"])
        self.mismatch(chain)

    def test_readiness_mismatch(self):
        for other in (eleven(plan_id="plan_9"), eleven(proposal_id="prop_9"),
                      eleven(request_id="e9"), eleven("improve")):
            self.mismatch(swap(eleven(), other, 6))

    def test_design_mismatch(self):
        for other in (eleven(design_id="design_9"), eleven(goal="x"), eleven("improve"),
                      eleven(candidate_id="cand_9")):
            self.mismatch(swap(eleven(), other, 7))

    def test_prompt885_result_mismatch(self):
        for other in (eleven(design_id="design_9"), eleven(plan_id="plan_9"),
                      eleven(proposal_id="prop_9"), eleven(candidate_id="cand_9"),
                      eleven(request_id="evo_9"), eleven("improve")):
            self.assertEqual(other[8]["status"], "valid")
            self.mismatch(swap(eleven(), other, 8))

    def test_blueprint_mismatch(self):
        for other in (eleven(design_id="design_9"), eleven(plan_id="plan_9"),
                      eleven(goal="x"), eleven(inputs=["q"]), eleven(outputs=["q"]),
                      eleven(constraints=["q"]), eleven(blueprint_id="bp_9"),
                      eleven("improve")):
            self.mismatch(swap(eleven(), other, 9))

    def test_prompt887_result_mismatch(self):
        for other in (eleven(blueprint_id="bp_9"), eleven(design_id="design_9"),
                      eleven(plan_id="plan_9"), eleven(proposal_id="prop_9"),
                      eleven(candidate_id="cand_9"), eleven(request_id="evo_9"),
                      eleven(capability_name="other_cap"), eleven("improve")):
            self.assertEqual(other[10]["status"], "valid")
            self.mismatch(swap(eleven(), other, 10))

    def test_forged_prompt887_result_fields(self):
        for key, value in (("blueprint_id", "bp_forged"), ("design_id", "design_forged"),
                           ("plan_id", "plan_forged"), ("proposal_id", "prop_forged"),
                           ("candidate_id", "cand_forged"), ("request_id", "evo_forged"),
                           ("capability_name", "forged_cap")):
            chain = eleven()
            chain[10] = dict(chain[10], **{key: value})
            self.mismatch(chain)

    def test_forged_blueprint_fields(self):
        forgeries = {"purpose": "Forged purpose.", "inputs": ["a_input", "z_input"],
                     "outputs": ["only"], "constraints": ["Second.", "First."],
                     "plan_id": "plan_f", "proposal_id": "prop_f", "candidate_id": "cand_f",
                     "design_id": "design_f", "request_id": "evo_f",
                     "capability_name": "forged_cap", "blueprint_id": "bp_f"}
        for key, value in forgeries.items():
            chain = eleven()
            chain[9] = dict(chain[9], **{key: value})
            self.mismatch(chain)

    def test_forged_individually_valid_everywhere(self):
        base = eleven()
        for i, other in ((2, eleven(goal="Another goal.")), (3, eleven(plan_id="plan_2")),
                         (4, eleven(outputs=["x_out"])), (5, eleven(request_id="evo_2")),
                         (6, eleven(plan_id="plan_3")), (7, eleven(proposal_id="prop_2")),
                         (8, eleven(design_id="design_2")), (9, eleven(design_id="design_2")),
                         (10, eleven(blueprint_id="bp_2"))):
            self.mismatch(swap(base, other, i))

    def test_existing_capability_mismatch(self):
        base = eleven("improve")
        other = eleven("improve", caps=[desc(purpose="A different purpose.")])
        for i in (2, 3, 4, 5, 7, 9):
            self.mismatch(swap(base, other, i))
        chain = eleven("improve")
        chain[9] = dict(chain[9], existing_capability=desc(version=2))
        self.mismatch(chain)

    def test_analysis_status_mismatch(self):
        self.mismatch(swap(eleven("improve"), eleven("create"), 9))
        self.mismatch(swap(eleven("create"), eleven("improve"), 1))


class UnsupportedAndInternalTests(unittest.TestCase):
    def test_improve_or_conflict_rejected(self):
        request = req(operation="create")
        analysis = analyze(request, [desc()])
        self.assertEqual(analysis["status"], "improve_or_conflict")
        for tail in (eleven(), eleven("improve")):
            r = run([request, analysis] + tail[2:])
            self.assertNotEqual(r["status"], "ready")
            self.assertIsNone(r["contract"])

    def test_unsupported_combination_guard(self):
        with mock.patch.object(cmod, "SUPPORTED", (("improve", "improve_required",
                                                    "improve_implementation"),)):
            r = run(eleven("create"))
        self.assertEqual(r["status"], "unsupported_status")
        self.assertIsNone(r["contract"])

    def test_unsupported_operations_rejected(self):
        for op in ("delete", "replace", "", None, 1):
            chain = eleven()
            chain[0] = dict(chain[0], operation=op)
            self.assertNotEqual(run(chain)["status"], "ready", repr(op))
            c = ok()["contract"]
            c["operation"] = op
            self.assertFalse(validate(c)["valid"], repr(op))

    def test_internal_failure(self):
        with mock.patch.object(cmod, "_blueprint_validation_mismatch",
                               side_effect=RuntimeError("x")):
            r = run(eleven())
        self.assertEqual(r["status"], "validation_error")
        self.assertIsNone(r["contract"])
        self.assertIs(r["execution_allowed"], False)

    def test_contract_error_guard(self):
        with mock.patch.object(cmod, "_contract_errors", return_value=[{"code": "x"}]):
            self.assertEqual(run(eleven())["status"], "contract_error")


class RequirementSequenceTests(unittest.TestCase):
    def test_create_requirements(self):
        self.assertEqual(ok("create")["contract"]["requirements"], CREATE_REQ)
        self.assertEqual(list(cmod.CREATE_REQUIREMENTS), CREATE_REQ)

    def test_improve_requirements(self):
        self.assertEqual(ok("improve")["contract"]["requirements"], IMPROVE_REQ)
        self.assertEqual(list(cmod.IMPROVE_REQUIREMENTS), IMPROVE_REQ)

    def test_requirements_are_short_identifiers_only(self):
        for op in ("create", "improve"):
            for item in ok(op)["contract"]["requirements"]:
                self.assertRegex(item, r"^[a-z_]+$")

    def test_wrong_requirements_rejected(self):
        for bad in (None, "interface_must_be_defined", [], CREATE_REQ[:-1], CREATE_REQ[::-1],
                    CREATE_REQ + ["extra"], IMPROVE_REQ, [1, 2, 3, 4, 5, 6],
                    tuple(CREATE_REQ), ["rm -rf /"] * 6):
            c = ok("create")["contract"]
            c["requirements"] = bad
            r = validate(c)
            self.assertFalse(r["valid"], repr(bad))
            self.assertIn("invalid_requirements", codes(r))
        c = ok("improve")["contract"]
        c["requirements"] = list(CREATE_REQ)
        self.assertFalse(validate(c)["valid"])


class ContractValidatorTests(unittest.TestCase):
    def test_malformed_contract(self):
        for bad in (None, [], "x", 5, (), set()):
            r = validate(bad)
            self.assertFalse(r["valid"])
            self.assertEqual(codes(r), ["contract_not_dict"])
        self.assertFalse(validate()["valid"])

    def test_extra_keys(self):
        for extra in ("code", "execution_allowed", "executed", "implementation_ready", "path"):
            c = ok()["contract"]
            c[extra] = False
            r = validate(c)
            self.assertFalse(r["valid"], extra)
            self.assertIn("unexpected_key", codes(r))

    def test_missing_keys(self):
        for key in KEYS:
            c = ok()["contract"]
            del c[key]
            r = validate(c)
            self.assertFalse(r["valid"], key)
            self.assertIn("missing_key", codes(r))

    def test_field_corruption_rejected(self):
        corruptions = {"request_id": "bad\nid", "operation": "delete", "capability_name": "",
                       "purpose": "", "inputs": "x", "outputs": [], "constraints": [1],
                       "analysis_status": "improve_required", "plan_id": None,
                       "proposal_id": "", "candidate_id": 5, "design_id": "bad\nid",
                       "blueprint_id": "bad\nid", "existing_capability": desc()}
        for key, bad in corruptions.items():
            c = ok("create")["contract"]
            c[key] = bad
            self.assertFalse(validate(c)["valid"], key)

    def test_improve_requires_existing_capability(self):
        c = ok("improve")["contract"]
        c["existing_capability"] = None
        self.assertFalse(validate(c)["valid"])

    def test_validator_result_shape_and_never_raises(self):
        for c in (ok()["contract"], None, {}):
            r = validate(c)
            self.assertEqual(sorted(r), ["errors", "executed", "execution_allowed", "valid"])
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)
            self.assertLessEqual(len(r["errors"]), 20)
        c = ok()["contract"]
        c["inputs"] = object()
        self.assertFalse(validate(c)["valid"])
        with mock.patch.object(cmod, "_contract_errors", side_effect=RuntimeError("x")):
            r = validate(ok()["contract"])
        self.assertEqual(codes(r), ["validation_error"])


class SafetyTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for op in ("create", "improve"):
            chain = eleven(op)
            snap = copy.deepcopy(chain)
            run(chain)
            self.assertEqual(chain, snap)
        bad = swap(eleven(), eleven(request_id="b"), 9)
        snap = copy.deepcopy(bad)
        run(bad)
        self.assertEqual(bad, snap)

    def test_contract_detached_from_inputs(self):
        chain = eleven("improve")
        c = run(chain)["contract"]
        c["inputs"].append("mutated")
        c["outputs"].clear()
        c["constraints"].append("mutated")
        c["existing_capability"]["name"] = "mutated"
        c["requirements"].append("mutated")
        self.assertEqual(chain[0]["inputs"], ["z_input", "a_input"])
        self.assertEqual(chain[0]["outputs"], ["z_out", "a_out"])
        self.assertEqual(chain[1]["existing"]["name"], "text_summarizer")
        self.assertEqual(ok("improve")["contract"]["requirements"], IMPROVE_REQ)
        self.assertEqual(cmod.IMPROVE_REQUIREMENTS, tuple(IMPROVE_REQ))

    def test_fresh_results_and_determinism(self):
        for op in ("create", "improve"):
            chain = eleven(op)
            results = [run(chain) for _ in range(5)]
            self.assertTrue(all(r == results[0] for r in results))
            self.assertIsNot(results[0], results[1])
            self.assertIsNot(results[0]["contract"], results[1]["contract"])
            self.assertIsNot(results[0]["contract"]["requirements"],
                             results[1]["contract"]["requirements"])
        bad = swap(eleven(), eleven(goal="Other."), 3)
        results = [run(bad) for _ in range(3)]
        self.assertTrue(all(r == results[0] for r in results))

    def test_execution_flags_stay_false(self):
        for chain in (eleven(), eleven("improve"), [None] * 11,
                      swap(eleven(), eleven(goal="x"), 7)):
            r = run(chain)
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_type_strict_comparison(self):
        self.assertFalse(cmod._same(True, 1))
        self.assertFalse(cmod._same([1], (1,)))
        self.assertTrue(cmod._same({"a": [1, "b"]}, {"a": [1, "b"]}))

    def test_module_has_no_forbidden_imports_or_calls(self):
        path = os.path.join(ROOT, "capabilities", "capability_implementation_contract.py")
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
        self.assertEqual(len(cmod.STATUSES), 18)
        self.assertIn("invalid_blueprint_validation", cmod.STATUSES)


if __name__ == "__main__":
    unittest.main()
