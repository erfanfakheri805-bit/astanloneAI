"""
Prompt 882 - capability definition candidate focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_definition_candidate_prompt882 -v
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_definition_candidate as cand_module
from capabilities.capability_definition_candidate import (
    build_capability_definition_candidate as build,
    validate_capability_definition_candidate as validate)
from capabilities.capability_evolution_analysis import analyze_capability_evolution as analyze
from capabilities.capability_evolution_plan import build_capability_evolution_plan as build_plan
from capabilities.capability_evolution_proposal import (
    build_capability_evolution_proposal as build_proposal)
from capabilities.capability_evolution_specification import (
    build_capability_evolution_specification as build_spec)
from capabilities.capability_evolution_validation import (
    validate_capability_evolution as real_context)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["version", "candidate_id", "request_id", "operation", "capability_name", "purpose",
        "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
        "plan_id", "proposal_id", "execution_allowed", "implementation_ready"]
BUILD_KEYS = ["status", "candidate", "execution_allowed", "executed"]


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


def five(op="create", caps=None, plan_id="plan_001", proposal_id="prop_001", **req_over):
    """(request, analysis, specification, plan, proposal) - a consistent context."""
    if caps is None:
        caps = [desc()] if op == "improve" else []
    request = req(operation=op, **req_over)
    analysis = analyze(request, caps)
    spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
    plan = build_plan(request, analysis, spec, plan_id)["plan"]
    proposal = build_proposal(request, analysis, spec, plan, proposal_id)["proposal"]
    return request, analysis, spec, plan, proposal


def make(op="create"):
    return build(*five(op), candidate_id="cand_001")["candidate"]


class BuildValidTests(unittest.TestCase):
    def test_create_candidate(self):
        r = build(*five("create"), candidate_id="cand_001")
        self.assertEqual(r["status"], "ready")
        c = r["candidate"]
        self.assertEqual(sorted(c), sorted(KEYS))
        self.assertEqual(c["operation"], "create")
        self.assertEqual(c["analysis_status"], "create_required")
        self.assertIsNone(c["existing_capability"])
        self.assertTrue(validate(c)["valid"])

    def test_improve_candidate(self):
        c = build(*five("improve"), candidate_id="cand_001")["candidate"]
        self.assertEqual(c["operation"], "improve")
        self.assertEqual(c["analysis_status"], "improve_required")
        self.assertEqual(c["existing_capability"], desc())
        self.assertTrue(validate(c)["valid"])

    def test_caller_supplied_candidate_id(self):
        for cid in ("cand_001", "C-9", "a" * 64):
            self.assertEqual(build(*five(), candidate_id=cid)["candidate"]["candidate_id"], cid)

    def test_exact_preservation(self):
        c = build(*five("create"), candidate_id="c1")["candidate"]
        self.assertEqual(c["version"], "1")
        self.assertEqual(c["request_id"], "evo_001")
        self.assertEqual(c["capability_name"], "text_summarizer")
        self.assertEqual(c["purpose"], "Summarize short documents.")
        self.assertEqual(c["inputs"], ["z_input", "a_input"])
        self.assertEqual(c["outputs"], ["z_out", "a_out"])
        self.assertEqual(c["constraints"], ["Second.", "First.", "Second."])

    def test_plan_and_proposal_ids_preserved(self):
        c = build(*five(plan_id="my_plan", proposal_id="my_prop"), candidate_id="c1")["candidate"]
        self.assertEqual((c["plan_id"], c["proposal_id"]), ("my_plan", "my_prop"))

    def test_flags_always_false(self):
        for op in ("create", "improve"):
            c = make(op)
            self.assertIs(c["execution_allowed"], False)
            self.assertIs(c["implementation_ready"], False)

    def test_result_shape_and_flags(self):
        for r in (build(*five(), candidate_id="c1"), build(None, None, None, None, None)):
            self.assertEqual(sorted(r), sorted(BUILD_KEYS))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_deterministic_repeated_construction(self):
        q = five("improve")
        a, b = build(*q, candidate_id="c1"), build(*q, candidate_id="c1")
        self.assertEqual(a, b)
        self.assertIsNot(a["candidate"], b["candidate"])
        self.assertIsNot(a["candidate"]["inputs"], b["candidate"]["inputs"])

    def test_ready_only_with_valid_candidate(self):
        for op in ("create", "improve"):
            r = build(*five(op), candidate_id="c1")
            self.assertEqual(r["status"] == "ready", validate(r["candidate"])["valid"])


class InvalidObjectTests(unittest.TestCase):
    def test_invalid_request(self):
        q = five()
        for bad in (None, {}, req(operation="delete"), req(execution_allowed=True)):
            r = build(bad, *q[1:], candidate_id="c1")
            self.assertEqual((r["status"], r["candidate"]), ("invalid_request", None))

    def test_invalid_analysis(self):
        q = five()
        for bad in (None, {}, dict(q[1], executed=True)):
            self.assertEqual(build(q[0], bad, *q[2:], candidate_id="c1")["status"],
                             "invalid_analysis")

    def test_invalid_specification(self):
        q = five()
        for bad in (None, {}, dict(q[2], execution_allowed=True)):
            self.assertEqual(build(q[0], q[1], bad, q[3], q[4], "c1")["status"],
                             "invalid_specification")

    def test_invalid_validation_context(self):
        q = five()
        forged = real_context(*q[:3])
        forged["ready"] = False
        with mock.patch.object(cand_module, "validate_capability_evolution",
                               return_value=forged):
            r = build(*q, candidate_id="c1")
        self.assertEqual((r["status"], r["candidate"]), ("invalid_validation", None))

    def test_invalid_plan(self):
        q = five()
        for bad in (None, {}, "x", dict(q[3], execution_allowed=True), dict(q[3], extra=1)):
            r = build(q[0], q[1], q[2], bad, q[4], "c1")
            self.assertEqual((r["status"], r["candidate"]), ("invalid_plan", None))

    def test_invalid_proposal(self):
        q = five()
        for bad in (None, {}, "x", dict(q[4], execution_allowed=True), dict(q[4], extra=1),
                    dict(q[4], proposal_type="improve_capability")):
            r = build(*q[:4], bad, "c1")
            self.assertEqual((r["status"], r["candidate"]), ("invalid_proposal", None))

    def test_validation_order(self):
        self.assertEqual(build()["status"], "invalid_request")
        self.assertEqual(build(req())["status"], "invalid_analysis")
        a = analyze(req(), [])
        self.assertEqual(build(req(), a)["status"], "invalid_specification")
        s = build_spec(req(), a, specification_id="s1")["specification"]
        self.assertEqual(build(req(), a, s)["status"], "invalid_plan")
        p = build_plan(req(), a, s, "p1")["plan"]
        self.assertEqual(build(req(), a, s, p)["status"], "invalid_proposal")


class MismatchTests(unittest.TestCase):
    def assertMismatch(self, r):
        self.assertEqual((r["status"], r["candidate"]), ("context_mismatch", None))

    def test_request_analysis(self):
        q = list(five("create"))
        q[1] = analyze(req(operation="improve"), [desc()])
        self.assertMismatch(build(*q, candidate_id="c1"))
        q[1] = analyze(req(capability_name="other_cap"), [])
        self.assertMismatch(build(*q, candidate_id="c1"))

    def test_request_specification(self):
        q = list(five("create"))
        for over in ({"request_id": "evo_999"}, {"capability_name": "other_cap"},
                     {"goal": "Different."}, {"inputs": ["x"]}, {"outputs": ["x"]},
                     {"constraints": ["x"]}):
            q[2] = five("create", **over)[2]
            self.assertMismatch(build(*q, candidate_id="c1"))

    def test_request_plan(self):
        q = list(five("create"))
        for over in ({"request_id": "evo_999"}, {"goal": "Different."}, {"inputs": ["x"]},
                     {"outputs": ["x"]}, {"constraints": ["x"]}):
            q[3] = five("create", **over)[3]
            self.assertMismatch(build(*q, candidate_id="c1"))

    def test_request_proposal(self):
        q = list(five("create"))
        for over in ({"request_id": "evo_999"}, {"goal": "Different."}, {"inputs": ["x"]},
                     {"outputs": ["x"]}, {"constraints": ["x"]}):
            q[4] = five("create", **over)[4]
            self.assertMismatch(build(*q, candidate_id="c1"))

    def test_analysis_specification(self):
        q = list(five("create"))
        q[2] = five("create", [desc()])[2]
        self.assertEqual(q[2]["analysis_status"], "improve_or_conflict")
        self.assertMismatch(build(*q, candidate_id="c1"))
        q = list(five("improve"))
        q[2] = five("improve", [desc(version=2)])[2]
        self.assertMismatch(build(*q, candidate_id="c1"))

    def test_analysis_plan(self):
        q = list(five("improve"))
        q[3] = five("improve", [desc(version=2)])[3]
        self.assertMismatch(build(*q, candidate_id="c1"))
        q = list(five("create"))
        q[3] = five("improve")[3]
        self.assertMismatch(build(*q, candidate_id="c1"))

    def test_analysis_proposal(self):
        q = list(five("improve"))
        q[4] = five("improve", [desc(version=2)])[4]
        self.assertMismatch(build(*q, candidate_id="c1"))

    def test_specification_plan(self):
        q = list(five("improve"))
        spec = copy.deepcopy(q[2])
        spec["existing_capability"]["version"] = 2
        q[2] = spec
        self.assertMismatch(build(*q, candidate_id="c1"))

    def test_specification_proposal(self):
        q = list(five("create"))
        q[2] = five("create", goal="Different.")[2]
        self.assertMismatch(build(*q, candidate_id="c1"))

    def test_plan_proposal(self):
        q = list(five("create"))
        q[4] = five("create", plan_id="plan_999")[4]
        self.assertEqual(q[4]["plan_id"], "plan_999")
        self.assertMismatch(build(*q, candidate_id="c1"))

    def test_proposal_for_other_operation(self):
        q = list(five("create"))
        q[4] = five("improve")[4]
        self.assertMismatch(build(*q, candidate_id="c1"))

    def test_validation_context_identity_mismatch(self):
        q = five("create")
        forged = real_context(*q[:3])
        forged["request_id"] = "evo_999"
        with mock.patch.object(cand_module, "validate_capability_evolution",
                               return_value=forged):
            r = build(*q, candidate_id="c1")
        self.assertEqual((r["status"], r["candidate"]), ("context_mismatch", None))


class IdAndStatusTests(unittest.TestCase):
    def test_missing_candidate_id(self):
        r = build(*five())
        self.assertEqual((r["status"], r["candidate"]), ("invalid_candidate_id", None))
        self.assertEqual(build(*five(), candidate_id=None)["status"], "invalid_candidate_id")

    def test_candidate_id_never_generated(self):
        for op in ("create", "improve"):
            self.assertIsNone(build(*five(op))["candidate"])

    def test_invalid_candidate_ids(self):
        for bad in ("", " x", "x ", 5, True, ["a"], "a" * 65, "a\nb"):
            r = build(*five(), candidate_id=bad)
            self.assertEqual((r["status"], r["candidate"]), ("invalid_candidate_id", None), bad)

    def test_mismatch_checked_before_candidate_id(self):
        q = list(five("create"))
        q[4] = five("create", goal="Different.")[4]
        self.assertEqual(build(*q)["status"], "context_mismatch")

    def test_improve_or_conflict_never_produces_candidate(self):
        request = req()
        analysis = analyze(request, [desc()])
        self.assertEqual(analysis["status"], "improve_or_conflict")
        spec = build_spec(request, analysis, specification_id="s1")["specification"]
        base = five("create")
        r = build(request, analysis, spec, base[3], base[4], "c1")
        self.assertIsNone(r["candidate"])
        self.assertNotEqual(r["status"], "ready")
        forged_plan = dict(base[3], analysis_status="improve_or_conflict")
        r = build(request, analysis, spec, forged_plan, base[4], "c1")
        self.assertEqual((r["status"], r["candidate"]), ("invalid_plan", None))

    def test_unsupported_status_guard(self):
        q = five("create")
        forged = real_context(*q[:3])
        forged.update(status="not_ready", ready=False, reason="analysis_status_not_supported",
                      analysis_status="missing_target")
        with mock.patch.object(cand_module, "validate_capability_evolution",
                               return_value=forged):
            r = build(*q, candidate_id="c1")
        self.assertEqual((r["status"], r["candidate"]), ("unsupported_status", None))

    def test_unsupported_proposal_builder_status(self):
        with mock.patch.object(cand_module, "build_capability_evolution_proposal",
                               return_value={"status": "unsupported_status", "proposal": None,
                                             "execution_allowed": False, "executed": False}):
            r = build(*five("create"), candidate_id="c1")
        self.assertEqual((r["status"], r["candidate"]), ("unsupported_status", None))

    def test_candidate_error_when_candidate_invalid(self):
        with mock.patch.object(cand_module, "_candidate_errors",
                               return_value=[{"code": "x", "where": "y"}]):
            r = build(*five("create"), candidate_id="c1")
        self.assertEqual((r["status"], r["candidate"]), ("candidate_error", None))

    def test_never_raises(self):
        class Boom(dict):
            def __getitem__(self, k):
                raise RuntimeError("boom")
        self.assertIsNone(build(Boom(), Boom(), Boom(), Boom(), Boom(), Boom())["candidate"])
        validate(Boom())
        with mock.patch.object(cand_module, "validate_capability_evolution",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(build(*five(), candidate_id="c1")["status"], "validation_error")


class ImmutabilityTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for op in ("create", "improve"):
            q = five(op)
            before = copy.deepcopy(q)
            build(*q, candidate_id="c1")
            self.assertEqual(q, before)

    def test_candidate_does_not_alias_inputs(self):
        q = five("improve")
        c = build(*q, candidate_id="c1")["candidate"]
        c["inputs"].append("mutated")
        c["existing_capability"]["inputs"].append("mutated")
        self.assertEqual(q[0]["inputs"], ["z_input", "a_input"])
        self.assertEqual(q[1]["existing"], desc())
        self.assertEqual(q[3]["existing_capability"], desc())
        self.assertEqual(q[4]["existing_capability"], desc())

    def test_validate_does_not_mutate(self):
        c = make("improve")
        before = copy.deepcopy(c)
        validate(c)
        self.assertEqual(c, before)


class ValidateCandidateTests(unittest.TestCase):
    def codes(self, c):
        return [e["code"] for e in validate(c)["errors"]]

    def test_not_dict(self):
        for bad in (None, [], "x", 1, ()):
            self.assertEqual(self.codes(bad), ["candidate_not_dict"])

    def test_missing_keys(self):
        for key in KEYS:
            c = make()
            del c[key]
            self.assertIn("missing_key", self.codes(c), key)
        self.assertFalse(validate({})["valid"])

    def test_extra_keys_and_equivalent_flags(self):
        for extra in ("extra", "executed", "execute", "run", "install", "load", "replace",
                      "source_code", "patch", "registry_mutation"):
            c = make()
            c[extra] = True
            self.assertIn("unexpected_key", self.codes(c), extra)

    def test_wrong_types(self):
        for key in KEYS:
            if key == "existing_capability":
                continue
            for bad in (None, 5, True, {}):
                c = make()
                c[key] = bad
                self.assertFalse(validate(c)["valid"], (key, bad))

    def test_invalid_version(self):
        for bad in ("2", 1, None):
            c = make()
            c["version"] = bad
            self.assertIn("invalid_version", self.codes(c))

    def test_invalid_ids(self):
        for key, code in (("candidate_id", "invalid_candidate_id"),
                          ("plan_id", "invalid_plan_id"),
                          ("proposal_id", "invalid_proposal_id"),
                          ("request_id", "invalid_request_id")):
            for bad in ("", " x", None, 3, "a" * 65):
                c = make()
                c[key] = bad
                self.assertIn(code, self.codes(c), (key, bad))

    def test_invalid_operation(self):
        for bad in ("delete", "Create", None, 1, ["create"]):
            c = make()
            c["operation"] = bad
            self.assertIn("invalid_operation", self.codes(c))

    def test_invalid_analysis_status(self):
        for bad in ("improve_or_conflict", "missing_target", "nope", None, 3):
            c = make()
            c["analysis_status"] = bad
            self.assertIn("invalid_analysis_status", self.codes(c), bad)

    def test_inconsistent_operation_status(self):
        c = make("create")
        c["analysis_status"] = "improve_required"
        self.assertIn("inconsistent_candidate", self.codes(c))
        c = make("improve")
        c["analysis_status"] = "create_required"
        self.assertIn("inconsistent_candidate", self.codes(c))
        c = make("create")
        c["operation"] = "improve"
        self.assertFalse(validate(c)["valid"])

    def test_invalid_purpose(self):
        for bad in ("", " x", None, 3, "a" * 201):
            c = make()
            c["purpose"] = bad
            self.assertIn("invalid_purpose", self.codes(c), bad)

    def test_invalid_lists(self):
        c = make()
        c["inputs"] = ["a", "a"]
        self.assertIn("duplicate_item", self.codes(c))
        c = make()
        c["outputs"] = []
        self.assertIn("empty_outputs", self.codes(c))
        c = make()
        c["constraints"] = [""]
        self.assertIn("invalid_item", self.codes(c))

    def test_invalid_existing_capability(self):
        for bad in ({}, "x", desc(enabled=1), desc(version=0), [desc()]):
            c = make("improve")
            c["existing_capability"] = bad
            self.assertIn("invalid_existing_capability", self.codes(c))

    def test_create_with_existing_capability(self):
        c = make("create")
        c["existing_capability"] = desc()
        self.assertIn("inconsistent_candidate", self.codes(c))

    def test_improve_without_existing_capability(self):
        c = make("improve")
        c["existing_capability"] = None
        self.assertIn("inconsistent_candidate", self.codes(c))

    def test_improve_with_wrong_existing_capability(self):
        c = make("improve")
        c["existing_capability"] = desc("other_cap")
        self.assertIn("inconsistent_candidate", self.codes(c))

    def test_execution_allowed(self):
        for bad in (True, 0, 1, None, "False"):
            c = make()
            c["execution_allowed"] = bad
            self.assertIn("invalid_execution_allowed", self.codes(c), bad)
            v = validate(c)
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)

    def test_implementation_ready_rejected(self):
        for bad in (True, 0, 1, None, "False"):
            c = make()
            c["implementation_ready"] = bad
            self.assertIn("invalid_implementation_ready", self.codes(c), bad)

    def test_validation_result_shape(self):
        v = validate(make())
        self.assertEqual(sorted(v), ["errors", "executed", "execution_allowed", "valid"])
        self.assertTrue(v["valid"])


class SafetyTests(unittest.TestCase):
    def test_imports_and_calls_are_safe(self):
        path = os.path.join(ROOT, "capabilities", "capability_definition_candidate.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported, calls = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add("." + (node.module or "") if node.level else node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                calls.add(node.func.id)
        self.assertEqual(imported, {"copy", ".capability_evolution_analysis",
                                    ".capability_evolution_plan",
                                    ".capability_evolution_proposal",
                                    ".capability_evolution_request",
                                    ".capability_evolution_specification",
                                    ".capability_evolution_validation",
                                    ".capability_registry"})
        for banned in ("open", "exec", "eval", "compile", "__import__"):
            self.assertNotIn(banned, calls)


if __name__ == "__main__":
    unittest.main()
