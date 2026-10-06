"""
Prompt 881 - capability evolution proposal focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_evolution_proposal_prompt881 -v
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_evolution_proposal as proposal_module
from capabilities.capability_evolution_analysis import analyze_capability_evolution as analyze
from capabilities.capability_evolution_plan import build_capability_evolution_plan as build_plan
from capabilities.capability_evolution_proposal import (
    build_capability_evolution_proposal as build,
    validate_capability_evolution_proposal as validate)
from capabilities.capability_evolution_specification import (
    build_capability_evolution_specification as build_spec)
from capabilities.capability_evolution_validation import (
    validate_capability_evolution as real_context)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["version", "proposal_id", "request_id", "operation", "capability_name", "goal",
        "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
        "plan_id", "execution_allowed", "proposal_type"]
BUILD_KEYS = ["status", "proposal", "execution_allowed", "executed"]


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


def quad(op="create", caps=None, plan_id="plan_001", **req_over):
    """(request, analysis, specification, plan) for a fully consistent context."""
    if caps is None:
        caps = [desc()] if op == "improve" else []
    request = req(operation=op, **req_over)
    analysis = analyze(request, caps)
    spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
    plan = build_plan(request, analysis, spec, plan_id)["plan"]
    return request, analysis, spec, plan


def make(op="create"):
    return build(*quad(op), proposal_id="prop_001")["proposal"]


class BuildValidTests(unittest.TestCase):
    def test_create_proposal(self):
        r = build(*quad("create"), proposal_id="prop_001")
        self.assertEqual(r["status"], "ready")
        p = r["proposal"]
        self.assertEqual(sorted(p), sorted(KEYS))
        self.assertEqual(p["operation"], "create")
        self.assertEqual(p["analysis_status"], "create_required")
        self.assertEqual(p["proposal_type"], "create_capability")
        self.assertIsNone(p["existing_capability"])
        self.assertTrue(validate(p)["valid"])

    def test_improve_proposal(self):
        p = build(*quad("improve"), proposal_id="prop_001")["proposal"]
        self.assertEqual(p["operation"], "improve")
        self.assertEqual(p["analysis_status"], "improve_required")
        self.assertEqual(p["proposal_type"], "improve_capability")
        self.assertEqual(p["existing_capability"], desc())
        self.assertTrue(validate(p)["valid"])

    def test_caller_supplied_proposal_id_preserved(self):
        for pid in ("prop_001", "P-9", "a" * 64):
            self.assertEqual(build(*quad("create"), proposal_id=pid)["proposal"]["proposal_id"],
                             pid)

    def test_plan_id_preserved(self):
        p = build(*quad("create", plan_id="my_plan_7"), proposal_id="p1")["proposal"]
        self.assertEqual(p["plan_id"], "my_plan_7")

    def test_exact_preservation(self):
        p = build(*quad("create"), proposal_id="p1")["proposal"]
        self.assertEqual(p["version"], "1")
        self.assertEqual(p["request_id"], "evo_001")
        self.assertEqual(p["capability_name"], "text_summarizer")
        self.assertEqual(p["goal"], "Summarize short documents.")
        self.assertEqual(p["inputs"], ["z_input", "a_input"])
        self.assertEqual(p["outputs"], ["z_out", "a_out"])
        self.assertEqual(p["constraints"], ["Second.", "First.", "Second."])

    def test_result_shape_and_flags(self):
        for r in (build(*quad("create"), proposal_id="p1"), build(None, None, None, None)):
            self.assertEqual(sorted(r), sorted(BUILD_KEYS))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)
        self.assertIs(make()["execution_allowed"], False)

    def test_deterministic_repeated_construction(self):
        q = quad("improve")
        a, b = build(*q, proposal_id="p1"), build(*q, proposal_id="p1")
        self.assertEqual(a, b)
        self.assertIsNot(a["proposal"], b["proposal"])
        self.assertIsNot(a["proposal"]["inputs"], b["proposal"]["inputs"])

    def test_ready_only_with_valid_proposal(self):
        for op in ("create", "improve"):
            r = build(*quad(op), proposal_id="p1")
            self.assertEqual(r["status"] == "ready", validate(r["proposal"])["valid"])


class BuildFailureTests(unittest.TestCase):
    def test_invalid_request(self):
        _, a, s, p = quad("create")
        for bad in (None, {}, req(operation="delete"), req(execution_allowed=True)):
            r = build(bad, a, s, p, "p1")
            self.assertEqual((r["status"], r["proposal"]), ("invalid_request", None))

    def test_invalid_analysis(self):
        r0, a, s, p = quad("create")
        for bad in (None, {}, dict(a, executed=True)):
            self.assertEqual(build(r0, bad, s, p, "p1")["status"], "invalid_analysis")

    def test_invalid_specification(self):
        r0, a, s, p = quad("create")
        for bad in (None, {}, dict(s, execution_allowed=True)):
            self.assertEqual(build(r0, a, bad, p, "p1")["status"], "invalid_specification")

    def test_invalid_validation_context(self):
        q = quad("create")
        forged = real_context(*q[:3])
        forged["ready"] = False
        with mock.patch.object(proposal_module, "validate_capability_evolution",
                               return_value=forged):
            r = build(*q, proposal_id="p1")
        self.assertEqual((r["status"], r["proposal"]), ("invalid_validation", None))

    def test_invalid_plan(self):
        r0, a, s, p = quad("create")
        for bad in (None, {}, "x", dict(p, execution_allowed=True), dict(p, extra=1),
                    dict(p, analysis_status="improve_or_conflict")):
            r = build(r0, a, s, bad, "p1")
            self.assertEqual((r["status"], r["proposal"]), ("invalid_plan", None))

    def test_validation_order(self):
        self.assertEqual(build(None, None, None, None, None)["status"], "invalid_request")
        self.assertEqual(build(req(), None, None, None, None)["status"], "invalid_analysis")
        a = analyze(req(), [])
        self.assertEqual(build(req(), a, None, None, None)["status"], "invalid_specification")
        s = build_spec(req(), a, specification_id="s1")["specification"]
        self.assertEqual(build(req(), a, s, None, None)["status"], "invalid_plan")

    def test_request_analysis_mismatch(self):
        r0, _, s, p = quad("create")
        a = analyze(req(operation="improve"), [desc()])
        r = build(r0, a, s, p, "p1")
        self.assertEqual((r["status"], r["proposal"]), ("context_mismatch", None))
        a = analyze(req(capability_name="other_cap"), [])
        self.assertEqual(build(r0, a, s, p, "p1")["status"], "context_mismatch")

    def test_request_specification_mismatch(self):
        r0, a, _, p = quad("create")
        for over in ({"request_id": "evo_999"}, {"capability_name": "other_cap"},
                     {"goal": "Different goal."}, {"inputs": ["other"]},
                     {"outputs": ["other"]}, {"constraints": ["Other."]}):
            s = quad("create", **over)[2]
            self.assertEqual(build(r0, a, s, p, "p1")["status"], "context_mismatch", over)

    def test_request_plan_mismatch(self):
        r0, a, s, _ = quad("create")
        for over in ({"request_id": "evo_999"}, {"goal": "Different goal."},
                     {"inputs": ["other"]}, {"outputs": ["other"]},
                     {"constraints": ["Other."]}):
            p = quad("create", **over)[3]
            self.assertEqual(build(r0, a, s, p, "p1")["status"], "context_mismatch", over)

    def test_analysis_specification_mismatch(self):
        r0, a, _, p = quad("create")
        s = quad("create", [desc()])[2]
        self.assertEqual(s["analysis_status"], "improve_or_conflict")
        self.assertEqual(build(r0, a, s, p, "p1")["status"], "context_mismatch")
        r1, a1, _, p1 = quad("improve")
        s1 = quad("improve", [desc(version=2)])[2]
        self.assertEqual(build(r1, a1, s1, p1, "p1")["status"], "context_mismatch")

    def test_analysis_plan_mismatch(self):
        r1, a1, s1, _ = quad("improve")
        p = quad("improve", [desc(version=2)])[3]
        self.assertEqual(build(r1, a1, s1, p, "p1")["status"], "context_mismatch")
        r0, a0, s0, _ = quad("create")
        self.assertEqual(build(r0, a0, s0, quad("improve")[3], "p1")["status"],
                         "context_mismatch")

    def test_specification_plan_mismatch(self):
        r0, a, _, p = quad("create")
        spec = quad("create", goal="Different goal.")[2]
        self.assertEqual(build(r0, a, spec, p, "p1")["status"], "context_mismatch")
        r1, a1, s1, p1 = quad("improve")
        s1 = copy.deepcopy(s1)
        s1["existing_capability"]["version"] = 2
        self.assertEqual(build(r1, a1, s1, p1, "p1")["status"], "context_mismatch")

    def test_validation_context_identity_mismatch(self):
        q = quad("create")
        for key, bad in (("request_id", "evo_999"), ("analysis_status", "improve_required")):
            forged = real_context(*q[:3])
            forged[key] = bad
            with mock.patch.object(proposal_module, "validate_capability_evolution",
                                   return_value=forged):
                r = build(*q, proposal_id="p1")
            self.assertIn(r["status"], ("context_mismatch", "invalid_validation"))
            self.assertIsNone(r["proposal"])

    def test_missing_proposal_id(self):
        r = build(*quad("create"))
        self.assertEqual((r["status"], r["proposal"]), ("invalid_proposal_id", None))
        self.assertEqual(build(*quad("create"), proposal_id=None)["status"],
                         "invalid_proposal_id")

    def test_proposal_id_never_generated(self):
        for op in ("create", "improve"):
            self.assertIsNone(build(*quad(op))["proposal"])

    def test_invalid_proposal_ids(self):
        for bad in ("", " x", "x ", 5, True, ["a"], "a" * 65, "a\nb"):
            r = build(*quad("create"), proposal_id=bad)
            self.assertEqual((r["status"], r["proposal"]), ("invalid_proposal_id", None), bad)

    def test_improve_or_conflict_unsupported(self):
        request = req()
        analysis = analyze(request, [desc()])
        self.assertEqual(analysis["status"], "improve_or_conflict")
        spec = build_spec(request, analysis, specification_id="s1")["specification"]
        # a valid plan cannot carry improve_or_conflict, so none can be built
        self.assertEqual(build_plan(request, analysis, spec, "p1")["status"],
                         "unsupported_status")
        plan = quad("create")[3]
        r = build(request, analysis, spec, plan, "prop_1")
        self.assertIsNone(r["proposal"])
        self.assertNotEqual(r["status"], "ready")
        forged = dict(plan, analysis_status="improve_or_conflict")
        r = build(request, analysis, spec, forged, "prop_1")
        self.assertEqual((r["status"], r["proposal"]), ("invalid_plan", None))

    def test_unsupported_status_guard(self):
        q = quad("create")
        forged = real_context(*q[:3])
        forged.update(status="not_ready", ready=False, reason="analysis_status_not_supported",
                      analysis_status="missing_target")
        with mock.patch.object(proposal_module, "validate_capability_evolution",
                               return_value=forged):
            r = build(*q, proposal_id="p1")
        self.assertEqual((r["status"], r["proposal"]), ("unsupported_status", None))

    def test_proposal_error_when_proposal_invalid(self):
        with mock.patch.object(proposal_module, "_proposal_errors",
                               return_value=[{"code": "x", "where": "y"}]):
            r = build(*quad("create"), proposal_id="p1")
        self.assertEqual((r["status"], r["proposal"]), ("proposal_error", None))

    def test_never_raises(self):
        class Boom(dict):
            def __getitem__(self, k):
                raise RuntimeError("boom")
        self.assertIsNone(build(Boom(), Boom(), Boom(), Boom(), Boom())["proposal"])
        validate(Boom())
        with mock.patch.object(proposal_module, "validate_capability_evolution",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(build(*quad("create"), proposal_id="p1")["status"],
                             "validation_error")


class ImmutabilityTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for op in ("create", "improve"):
            q = quad(op)
            before = copy.deepcopy(q)
            build(*q, proposal_id="p1")
            self.assertEqual(q, before)

    def test_proposal_does_not_alias_inputs(self):
        request, analysis, spec, plan = quad("improve")
        p = build(request, analysis, spec, plan, "p1")["proposal"]
        p["inputs"].append("mutated")
        p["existing_capability"]["inputs"].append("mutated")
        self.assertEqual(request["inputs"], ["z_input", "a_input"])
        self.assertEqual(analysis["existing"], desc())
        self.assertEqual(plan["existing_capability"], desc())

    def test_validate_does_not_mutate(self):
        p = make("improve")
        before = copy.deepcopy(p)
        validate(p)
        self.assertEqual(p, before)


class ValidateProposalTests(unittest.TestCase):
    def codes(self, p):
        return [e["code"] for e in validate(p)["errors"]]

    def test_not_dict(self):
        for bad in (None, [], "x", 1, ()):
            self.assertEqual(self.codes(bad), ["proposal_not_dict"])

    def test_missing_keys(self):
        for key in KEYS:
            p = make()
            del p[key]
            self.assertIn("missing_key", self.codes(p), key)
        self.assertFalse(validate({})["valid"])

    def test_extra_keys_and_equivalent_execution_flags(self):
        for extra in ("extra", "executed", "execute", "run", "apply", "code", "patch"):
            p = make()
            p[extra] = True
            self.assertIn("unexpected_key", self.codes(p), extra)

    def test_wrong_types(self):
        for key in KEYS:
            if key in ("existing_capability",):
                continue
            for bad in (None, 5, True, {}):
                p = make()
                p[key] = bad
                self.assertFalse(validate(p)["valid"], (key, bad))

    def test_invalid_version(self):
        for bad in ("2", 1, None):
            p = make()
            p["version"] = bad
            self.assertIn("invalid_version", self.codes(p))

    def test_invalid_ids(self):
        for key, code in (("proposal_id", "invalid_proposal_id"),
                          ("plan_id", "invalid_plan_id"),
                          ("request_id", "invalid_request_id")):
            for bad in ("", " x", None, 3, "a" * 65):
                p = make()
                p[key] = bad
                self.assertIn(code, self.codes(p), (key, bad))

    def test_invalid_operation(self):
        for bad in ("delete", "Create", None, 1):
            p = make()
            p["operation"] = bad
            self.assertIn("invalid_operation", self.codes(p))

    def test_invalid_analysis_status(self):
        for bad in ("improve_or_conflict", "missing_target", "nope", None, 3):
            p = make()
            p["analysis_status"] = bad
            self.assertIn("invalid_analysis_status", self.codes(p), bad)

    def test_invalid_proposal_type(self):
        for bad in ("delete_capability", "create", "", None, 3, "Create_Capability"):
            p = make()
            p["proposal_type"] = bad
            self.assertIn("invalid_proposal_type", self.codes(p), bad)

    def test_inconsistent_operation_status_type(self):
        p = make("create")
        p["proposal_type"] = "improve_capability"
        self.assertIn("inconsistent_proposal", self.codes(p))
        p = make("improve")
        p["proposal_type"] = "create_capability"
        self.assertIn("inconsistent_proposal", self.codes(p))
        p = make("create")
        p["analysis_status"] = "improve_required"
        self.assertIn("inconsistent_proposal", self.codes(p))
        p = make("improve")
        p["analysis_status"] = "create_required"
        self.assertIn("inconsistent_proposal", self.codes(p))
        p = make("create")
        p["operation"] = "improve"
        self.assertFalse(validate(p)["valid"])

    def test_inconsistent_request_fields(self):
        p = make()
        p["goal"] = ""
        self.assertIn("invalid_goal", self.codes(p))
        p = make()
        p["inputs"] = ["a", "a"]
        self.assertIn("duplicate_item", self.codes(p))
        p = make()
        p["outputs"] = []
        self.assertIn("empty_outputs", self.codes(p))
        p = make()
        p["constraints"] = [""]
        self.assertIn("invalid_item", self.codes(p))

    def test_invalid_existing_capability(self):
        for bad in ({}, "x", desc(enabled=1), desc(version=0), [desc()]):
            p = make("improve")
            p["existing_capability"] = bad
            self.assertIn("invalid_existing_capability", self.codes(p))

    def test_create_with_existing_capability(self):
        p = make("create")
        p["existing_capability"] = desc()
        self.assertIn("inconsistent_proposal", self.codes(p))

    def test_improve_without_existing_capability(self):
        p = make("improve")
        p["existing_capability"] = None
        self.assertIn("inconsistent_proposal", self.codes(p))

    def test_improve_with_wrong_existing_capability(self):
        p = make("improve")
        p["existing_capability"] = desc("other_cap")
        self.assertIn("inconsistent_proposal", self.codes(p))

    def test_execution_allowed(self):
        for bad in (True, 0, 1, None, "False"):
            p = make()
            p["execution_allowed"] = bad
            self.assertIn("invalid_execution_allowed", self.codes(p), bad)
            v = validate(p)
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)

    def test_validation_result_shape(self):
        v = validate(make())
        self.assertEqual(sorted(v), ["errors", "executed", "execution_allowed", "valid"])
        self.assertTrue(v["valid"])


class SafetyTests(unittest.TestCase):
    def test_imports_and_calls_are_safe(self):
        path = os.path.join(ROOT, "capabilities", "capability_evolution_proposal.py")
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
                                    ".capability_evolution_request",
                                    ".capability_evolution_specification",
                                    ".capability_evolution_validation",
                                    ".capability_registry"})
        for banned in ("open", "exec", "eval", "compile", "__import__"):
            self.assertNotIn(banned, calls)


if __name__ == "__main__":
    unittest.main()
