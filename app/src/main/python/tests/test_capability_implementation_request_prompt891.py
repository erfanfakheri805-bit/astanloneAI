"""
Prompt 891 - capability implementation request focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_implementation_request_prompt891 -v
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_implementation_boundary as m890
from capabilities import capability_implementation_request as rmod
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
from capabilities.capability_implementation_boundary import (
    evaluate_capability_implementation_boundary as evaluate890)
from capabilities.capability_implementation_contract import (
    build_capability_implementation_contract as build_contract,
    validate_capability_implementation_contract as validate_contract)
from capabilities.capability_implementation_contract_readiness import (
    evaluate_capability_implementation_contract_readiness as evaluate889)
from capabilities.capability_implementation_design import (
    build_capability_implementation_design as build_design)
from capabilities.capability_implementation_design_validation import (
    validate_capability_implementation_design_context as check885)
from capabilities.capability_implementation_request import (
    build_capability_implementation_request as build,
    validate_capability_implementation_request as validate)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["version", "implementation_request_id", "request_id", "capability_name", "operation",
        "analysis_status", "plan_id", "contract_id", "boundary_status", "purpose", "inputs",
        "outputs", "constraints", "existing_capability", "implementation_allowed",
        "execution_allowed"]
NAMES = ["request", "analysis", "spec", "plan", "proposal", "candidate", "readiness", "design",
         "v885", "blueprint", "b887", "contract", "creport", "r889", "boundary"]
EXPECTED_NONE = ["invalid_request", "invalid_analysis", "invalid_specification", "invalid_plan",
                 "invalid_proposal", "invalid_candidate", "invalid_readiness", "invalid_design",
                 "invalid_design_validation", "invalid_blueprint",
                 "invalid_blueprint_validation", "invalid_contract",
                 "invalid_contract_validation", "invalid_contract_readiness",
                 "invalid_boundary"]


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


def full(op="create", caps=None, plan_id="plan_001", proposal_id="prop_001",
         candidate_id="cand_001", design_id="design_001", blueprint_id="bp_001",
         contract_id="ct_001", **req_over):
    """[request .. contract readiness result (889), boundary result (890)] - 15 objects."""
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
    contract = build_contract(*chain, vresult, blueprint, bresult, contract_id)["contract"]
    creport = validate_contract(contract)
    r889 = evaluate889(*chain, vresult, blueprint, bresult, contract, creport)
    base = chain + [vresult, blueprint, bresult, contract, creport, r889]
    return base + [evaluate890(*base)]


def swap(base, other, *indexes):
    out = list(base)
    for i in indexes:
        out[i] = other[i]
    return out


def run(chain, iid="ir_001"):
    return build(*chain, iid)


def ok(op="create"):
    return run(full(op))


def codes(result):
    return [e["code"] for e in result["errors"]]


def good(op="create"):
    return ok(op)["request"]


class IntegerVersionTests(unittest.TestCase):
    def test_prompt884_design_version_still_integer(self):
        for op in ("create", "improve"):
            self.assertIs(type(full(op)[7]["version"]), int)
            self.assertEqual(full(op)[7]["version"], 1)

    def test_request_version_is_integer_one(self):
        for op in ("create", "improve"):
            r = good(op)
            self.assertIs(type(r["version"]), int)
            self.assertEqual(r["version"], 1)

    def test_wrong_version_types_rejected(self):
        for bad in ("1", 1.0, True, None, 2, 0, [1], b"1"):
            r = good()
            r["version"] = bad
            v = validate(r)
            self.assertFalse(v["valid"], repr(bad))
            self.assertIn("invalid_version", codes(v))


class ValidRequestTests(unittest.TestCase):
    def test_valid_create_request(self):
        r = ok("create")
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["request"]["operation"], "create")
        self.assertEqual(r["request"]["analysis_status"], "create_required")
        self.assertTrue(validate(r["request"])["valid"])

    def test_valid_improve_request(self):
        r = ok("improve")
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["request"]["operation"], "improve")
        self.assertEqual(r["request"]["analysis_status"], "improve_required")
        self.assertTrue(validate(r["request"])["valid"])

    def test_exactly_sixteen_keys(self):
        for op in ("create", "improve"):
            r = good(op)
            self.assertEqual(len(r), 16)
            self.assertEqual(sorted(r), sorted(KEYS))
            self.assertEqual(list(r), KEYS)
            self.assertNotIn("status", r)

    def test_builder_return_shape(self):
        for r in (ok(), run(full(), None), run([None] * 15)):
            self.assertEqual(sorted(r), ["executed", "execution_allowed", "request", "status"])
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)
        self.assertIsNone(run(full(), None)["request"])

    def test_implementation_request_id_is_caller_supplied(self):
        for iid in ("ir_001", "my-request.42", "A"):
            self.assertEqual(run(full(), iid)["request"]["implementation_request_id"], iid)
        self.assertEqual(run(full(), None)["status"], "invalid_implementation_request_id")

    def test_identity_comes_from_trusted_objects(self):
        for op in ("create", "improve"):
            caps = [desc("other_cap")] if op == "improve" else []
            chain = full(op, caps=caps, plan_id="plan_x", contract_id="ct_x",
                         request_id="evo_x", capability_name="other_cap")
            r = run(chain, "ir_9")["request"]
            self.assertEqual(r["request_id"], "evo_x")
            self.assertEqual(r["capability_name"], "other_cap")
            self.assertEqual(r["operation"], op)
            self.assertEqual(r["plan_id"], "plan_x")
            self.assertEqual(r["contract_id"], "ct_x")
            self.assertEqual(r["analysis_status"], chain[1]["status"])
            self.assertEqual(r["implementation_request_id"], "ir_9")

    def test_content_preserved_exactly_in_order(self):
        for op in ("create", "improve"):
            chain = full(op)
            r = run(chain)["request"]
            self.assertEqual(r["inputs"], ["z_input", "a_input"])
            self.assertEqual(r["outputs"], ["z_out", "a_out"])
            self.assertEqual(r["constraints"], ["Second.", "First.", "Second."])
            self.assertEqual(r["purpose"], chain[5]["purpose"])
            self.assertEqual(r["purpose"], "Summarize short documents.")

    def test_existing_capability_preserved(self):
        self.assertIsNone(good("create")["existing_capability"])
        r = good("improve")
        self.assertEqual(r["existing_capability"], desc())
        self.assertIsNot(r["existing_capability"], full("improve")[1]["existing"])

    def test_boundary_status_ready(self):
        for op in ("create", "improve"):
            self.assertEqual(good(op)["boundary_status"], "ready")

    def test_flags_always_false_for_valid_request(self):
        for op in ("create", "improve"):
            r = good(op)
            self.assertIs(r["implementation_allowed"], False)
            self.assertIs(r["execution_allowed"], False)
            self.assertTrue(validate(r)["valid"])

    def test_no_automatic_execution_fields(self):
        r = good()
        for key in ("executed", "status", "implementation_started", "command", "code", "patch"):
            self.assertNotIn(key, r)


class InvalidChainTests(unittest.TestCase):
    def test_each_invalid_object_has_its_status(self):
        base = full()
        for i, expected in enumerate(EXPECTED_NONE):
            for bad in (None, {}, [], "x"):
                broken = list(base)
                broken[i] = bad
                r = run(broken)
                self.assertEqual(r["status"], expected, (NAMES[i], bad))
                self.assertIsNone(r["request"])

    def test_invalid_validation_context(self):
        with mock.patch.object(m890, "validate_capability_evolution_result",
                               return_value={"valid": False}):
            self.assertEqual(run(full())["status"], "invalid_validation")

    def test_invalid_readiness_not_ready(self):
        base = full()
        bad = copy.deepcopy(base[6])
        bad["ready"] = False
        self.assertEqual(run(swap(base, [None] * 6 + [bad], 6))["status"], "invalid_readiness")

    def test_invalid_design_validation_not_valid(self):
        base = full()
        bad = copy.deepcopy(base[8])
        bad["valid"] = False
        self.assertEqual(run(swap(base, [None] * 8 + [bad], 8))["status"],
                         "invalid_design_validation")

    def test_invalid_contract_validation_shape(self):
        base = full()
        for bad in ({"valid": True, "errors": [], "execution_allowed": False},
                    {"valid": False, "errors": [{"code": "x", "where": "y"}],
                     "execution_allowed": False, "executed": False},
                    {"valid": True, "errors": [], "execution_allowed": True, "executed": False}):
            self.assertEqual(run(swap(base, [None] * 12 + [bad], 12))["status"],
                             "invalid_contract_validation")

    def test_invalid_contract_readiness_not_ready(self):
        from capabilities import capability_implementation_contract_readiness as m889
        base = full()
        bad = m889._result("not_ready", base[0], "create_required")
        self.assertEqual(run(swap(base, [None] * 13 + [bad], 13))["status"],
                         "invalid_contract_readiness")

    def test_invalid_chain_never_produces_request(self):
        base = full()
        for i in range(15):
            broken = list(base)
            broken[i] = None
            self.assertIsNone(run(broken)["request"], NAMES[i])

    def test_ready_only_when_whole_chain_valid(self):
        self.assertEqual(run(full())["status"], "ready")


class ContextMismatchTests(unittest.TestCase):
    def _statuses(self, **kw):
        base, other = full(), full(**kw)
        out = {}
        for i, name in enumerate(NAMES):
            result = run(swap(base, other, i))["status"]
            if result != "ready":
                out[name] = result
        return out

    def test_every_swapped_object_from_other_request_is_context_mismatch(self):
        for kw in (dict(request_id="evo_002"), dict(capability_name="other_cap"),
                   dict(goal="Other goal."), dict(inputs=["q"]), dict(outputs=["q"]),
                   dict(constraints=["Other."])):
            found = self._statuses(**kw)
            self.assertTrue(found, kw)
            self.assertEqual(set(found.values()), {"context_mismatch"}, kw)

    def test_each_trusted_id_mismatch(self):
        expected = {"plan_id": {"plan", "proposal", "candidate", "readiness", "design", "v885",
                                "blueprint", "b887", "contract", "r889", "boundary"},
                    "proposal_id": {"proposal", "candidate", "readiness", "design", "v885",
                                    "blueprint", "b887", "contract", "r889"},
                    "candidate_id": {"candidate", "design", "v885", "blueprint", "b887",
                                     "contract"},
                    "design_id": {"design", "v885", "blueprint", "b887", "contract"},
                    "blueprint_id": {"blueprint", "b887", "contract"},
                    "contract_id": {"contract", "r889", "boundary"}}
        for key, names in expected.items():
            found = self._statuses(**{key: key[:-3] + "_002"})
            self.assertEqual(set(found), names, key)
            self.assertEqual(set(found.values()), {"context_mismatch"}, key)

    def test_operation_mismatch(self):
        base, other = full("create"), full("improve")
        for i, name in enumerate(NAMES):
            if name == "creport":
                continue  # the valid 4-key report is identical for both operations
            self.assertEqual(run(swap(base, other, i))["status"], "context_mismatch", name)

    def test_mismatch_never_produces_request(self):
        base, other = full(), full(request_id="evo_002")
        for i in range(15):
            r = run(swap(base, other, i))
            self.assertEqual(r["request"] is None, r["status"] != "ready", NAMES[i])


class BoundaryTests(unittest.TestCase):
    def test_invalid_boundary_results(self):
        base = full()
        good_boundary = base[14]
        bads = [None, {}, [], "ready", dict(good_boundary, version="1"),
                dict(good_boundary, extra=1)]
        for bad in bads:
            self.assertEqual(run(swap(base, [None] * 14 + [bad], 14))["status"],
                             "invalid_boundary", repr(bad)[:40])

    def test_boundary_not_ready_rejected(self):
        base = full()
        for status in ("context_mismatch", "unsupported_status", "invalid_contract"):
            bad = m890._result(status, base[0], "create_required")
            self.assertEqual(run(swap(base, [None] * 14 + [bad], 14))["status"],
                             "invalid_boundary", status)

    def test_boundary_flags_true_rejected(self):
        base = full()
        for key in ("implementation_allowed", "implementation_started", "execution_allowed",
                    "executed"):
            bad = dict(base[14], **{key: True})
            self.assertEqual(run(swap(base, [None] * 14 + [bad], 14))["status"],
                             "invalid_boundary", key)

    def test_forged_individually_valid_boundary_rejected(self):
        base = full()
        for kw in (dict(request_id="evo_002"), dict(plan_id="plan_002"),
                   dict(contract_id="ct_002"), dict(capability_name="other_cap")):
            forged = full(**kw)[14]
            self.assertTrue(m890.validate_capability_implementation_boundary_result(
                forged)["valid"])
            r = run(swap(base, [None] * 14 + [forged], 14))
            self.assertEqual(r["status"], "context_mismatch", kw)
            self.assertIsNone(r["request"])

    def test_forged_boundary_with_edited_ids_rejected(self):
        base = full()
        for key, value in (("plan_id", "plan_zzz"), ("contract_id", "ct_zzz"),
                           ("request_id", "evo_zzz"), ("capability_name", "zzz")):
            forged = dict(base[14], **{key: value})
            self.assertTrue(m890.validate_capability_implementation_boundary_result(
                forged)["valid"], key)
            self.assertEqual(run(swap(base, [None] * 14 + [forged], 14))["status"],
                             "context_mismatch", key)

    def test_boundary_from_other_operation_rejected(self):
        self.assertEqual(run(swap(full("create"), full("improve"), 14))["status"],
                         "context_mismatch")

    def test_improve_or_conflict_unsupported(self):
        request = req(operation="create")
        analysis = analyze(request, [desc()])
        self.assertEqual(analysis["status"], "improve_or_conflict")
        spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
        for tail in (full()[3:], full("improve")[3:]):
            r = run([request, analysis, spec] + tail)
            self.assertEqual(r["status"], "unsupported_status")
            self.assertIsNone(r["request"])

    def test_unsupported_combination_guard(self):
        with mock.patch.object(rmod, "SUPPORTED", (("improve", "improve_required"),)):
            r = run(full("create"))
        self.assertEqual(r["status"], "unsupported_status")
        self.assertIsNone(r["request"])


class RequestIdTests(unittest.TestCase):
    def test_invalid_implementation_request_ids(self):
        for bad in (None, "", " ", 5, True, ["a"], {"a": 1}, "x" * 65, "\n", "\t"):
            r = run(full(), bad)
            self.assertEqual(r["status"], "invalid_implementation_request_id", repr(bad))
            self.assertIsNone(r["request"])

    def test_valid_id_boundaries(self):
        self.assertEqual(run(full(), "x" * 64)["status"], "ready")

    def test_validator_rejects_invalid_ids(self):
        for key in ("implementation_request_id", "contract_id"):
            for bad in (None, "", 7, "x" * 65, "\n"):
                r = good()
                r[key] = bad
                self.assertFalse(validate(r)["valid"], (key, bad))

    def test_id_check_comes_after_chain_checks(self):
        broken = full()
        broken[3] = None
        self.assertEqual(run(broken, None)["status"], "invalid_plan")


class ValidatorTests(unittest.TestCase):
    def test_malformed_request(self):
        for bad in (None, [], "x", 1, (), set()):
            v = validate(bad)
            self.assertFalse(v["valid"])
            self.assertEqual(codes(v), ["request_not_dict"])

    def test_missing_keys(self):
        for key in KEYS:
            r = good()
            del r[key]
            v = validate(r)
            self.assertFalse(v["valid"], key)
            self.assertEqual(codes(v), ["missing_key"])

    def test_extra_keys(self):
        for extra in ("status", "executed", "implementation_started", "code", 5):
            r = good()
            r[extra] = True
            v = validate(r)
            self.assertFalse(v["valid"], extra)
            self.assertIn("unexpected_key", codes(v))

    def test_invalid_operation(self):
        for bad in ("delete", "", None, 1, "Create", "improve_or_conflict"):
            r = good()
            r["operation"] = bad
            self.assertFalse(validate(r)["valid"], repr(bad))

    def test_operation_status_inconsistency(self):
        r = good("create")
        r["analysis_status"] = "improve_required"
        self.assertFalse(validate(r)["valid"])
        r = good("improve")
        r["analysis_status"] = "create_required"
        self.assertFalse(validate(r)["valid"])
        r = good("create")
        r["analysis_status"] = "improve_or_conflict"
        self.assertFalse(validate(r)["valid"])

    def test_existing_capability_consistency(self):
        r = good("create")
        r["existing_capability"] = desc()
        self.assertFalse(validate(r)["valid"])
        r = good("improve")
        r["existing_capability"] = None
        self.assertFalse(validate(r)["valid"])

    def test_boundary_status_other_than_ready(self):
        for bad in ("not_ready", "context_mismatch", "", None, True, 1, "Ready"):
            r = good()
            r["boundary_status"] = bad
            v = validate(r)
            self.assertFalse(v["valid"], repr(bad))
            self.assertIn("invalid_boundary_status", codes(v))

    def test_implementation_allowed_true_rejected(self):
        for bad in (True, 1, None, "False", 0):
            for op in ("create", "improve"):
                r = good(op)
                r["implementation_allowed"] = bad
                v = validate(r)
                self.assertFalse(v["valid"], (bad, op))
                self.assertIn("invalid_flag", codes(v))

    def test_execution_allowed_true_rejected(self):
        for bad in (True, 1, None, "False", 0):
            for op in ("create", "improve"):
                r = good(op)
                r["execution_allowed"] = bad
                v = validate(r)
                self.assertFalse(v["valid"], (bad, op))
                self.assertIn("invalid_flag", codes(v))

    def test_inconsistent_trusted_fields(self):
        for key, bad in (("request_id", ""), ("capability_name", ""),
                         ("plan_id", None), ("purpose", ""), ("inputs", "x"),
                         ("outputs", []), ("constraints", None)):
            r = good()
            r[key] = bad
            self.assertFalse(validate(r)["valid"], key)

    def test_mutated_request_rejected(self):
        r = good()
        self.assertTrue(validate(r)["valid"])
        r["implementation_allowed"] = True
        self.assertFalse(validate(r)["valid"])
        r = good()
        r["inputs"] = ("a",)
        self.assertFalse(validate(r)["valid"])

    def test_validator_result_shape_and_never_raises(self):
        for r in (good(), None, {}):
            v = validate(r)
            self.assertEqual(sorted(v), ["errors", "executed", "execution_allowed", "valid"])
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)
            self.assertLessEqual(len(v["errors"]), 20)
        r = good()
        r["operation"] = object()
        self.assertFalse(validate(r)["valid"])
        with mock.patch.object(rmod, "_request_errors", side_effect=RuntimeError("x")):
            self.assertEqual(codes(validate(good())), ["validation_error"])

    def test_request_error_status_when_built_request_invalid(self):
        with mock.patch.object(rmod, "_request_errors",
                               return_value=[{"code": "x", "where": "y"}]):
            r = run(full())
        self.assertEqual(r["status"], "request_error")
        self.assertIsNone(r["request"])

    def test_internal_failure_is_validation_error(self):
        with mock.patch.object(rmod, "evaluate_capability_implementation_boundary",
                               side_effect=RuntimeError("x")):
            r = run(full())
        self.assertEqual(r["status"], "validation_error")
        self.assertIsNone(r["request"])


class SafetyTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for op in ("create", "improve"):
            chain = full(op)
            snap = copy.deepcopy(chain)
            run(chain)
            self.assertEqual(chain, snap)
        bad = swap(full(), full(request_id="evo_002"), 11, 12, 13)
        snap = copy.deepcopy(bad)
        run(bad)
        self.assertEqual(bad, snap)

    def test_request_is_independent_of_inputs(self):
        chain = full("improve")
        r = run(chain)["request"]
        snap = copy.deepcopy(r)
        chain[0]["inputs"].append("zzz")
        chain[1]["existing"]["name"] = "changed"
        self.assertEqual(r, snap)
        r["inputs"].append("q")
        self.assertNotIn("q", chain[0]["inputs"])

    def test_deterministic_repeated_construction(self):
        for op in ("create", "improve"):
            chain = full(op)
            results = [run(chain) for _ in range(5)]
            self.assertTrue(all(r == results[0] for r in results))
            self.assertIsNot(results[0], results[1])
            self.assertIsNot(results[0]["request"], results[1]["request"])
        bad = swap(full(), full(goal="Other."), 3)
        results = [run(bad) for _ in range(3)]
        self.assertTrue(all(r == results[0] for r in results))

    def test_validator_does_not_mutate(self):
        r = good()
        snap = copy.deepcopy(r)
        validate(r)
        self.assertEqual(r, snap)

    def test_constants(self):
        self.assertEqual(rmod.REQUEST_VERSION, 1)
        self.assertEqual(rmod.BOUNDARY_STATUS, "ready")
        self.assertEqual(len(rmod.FIELDS), 16)
        for status in ("ready", "invalid_boundary", "context_mismatch", "unsupported_status",
                       "validation_error", "invalid_contract_readiness"):
            self.assertIn(status, rmod.STATUSES)
        self.assertEqual(rmod.SUPPORTED, (("create", "create_required"),
                                          ("improve", "improve_required")))

    def test_module_has_no_forbidden_imports_or_calls(self):
        path = os.path.join(ROOT, "capabilities", "capability_implementation_request.py")
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
