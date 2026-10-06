"""
Prompt 880 - capability evolution plan focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_evolution_plan_prompt880 -v
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_evolution_plan as plan_module
from capabilities.capability_evolution_analysis import analyze_capability_evolution as analyze
from capabilities.capability_evolution_plan import (
    build_capability_evolution_plan as build,
    validate_capability_evolution_plan as validate)
from capabilities.capability_evolution_specification import (
    build_capability_evolution_specification as build_spec)
from capabilities.capability_evolution_validation import (
    validate_capability_evolution as real_context)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLAN_KEYS = ["version", "plan_id", "request_id", "operation", "capability_name", "goal",
             "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
             "execution_allowed"]
BUILD_KEYS = ["status", "plan", "execution_allowed", "executed"]


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


def triple(op="create", caps=None, **req_over):
    request = req(operation=op, **req_over)
    analysis = analyze(request, [] if caps is None else caps)
    spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
    return request, analysis, spec


def make(op="create"):
    t = triple(op, [desc()] if op == "improve" else None)
    return build(*t, plan_id="plan_001")["plan"]


class BuildValidTests(unittest.TestCase):
    def test_create_plan(self):
        r = build(*triple("create"), plan_id="plan_001")
        self.assertEqual(r["status"], "ready")
        p = r["plan"]
        self.assertEqual(sorted(p), sorted(PLAN_KEYS))
        self.assertEqual(p["operation"], "create")
        self.assertEqual(p["analysis_status"], "create_required")
        self.assertIsNone(p["existing_capability"])
        self.assertTrue(validate(p)["valid"])

    def test_improve_plan(self):
        p = build(*triple("improve", [desc()]), plan_id="plan_001")["plan"]
        self.assertEqual(p["operation"], "improve")
        self.assertEqual(p["analysis_status"], "improve_required")
        self.assertEqual(p["existing_capability"], desc())
        self.assertTrue(validate(p)["valid"])

    def test_caller_supplied_plan_id_preserved(self):
        for pid in ("plan_001", "P-9", "a" * 64):
            p = build(*triple("create"), plan_id=pid)["plan"]
            self.assertEqual(p["plan_id"], pid)

    def test_exact_preservation(self):
        request = triple("create")[0]
        p = build(*triple("create"), plan_id="p1")["plan"]
        self.assertEqual(p["version"], "1")
        self.assertEqual(p["request_id"], "evo_001")
        self.assertEqual(p["capability_name"], "text_summarizer")
        self.assertEqual(p["goal"], request["goal"])
        self.assertEqual(p["inputs"], ["z_input", "a_input"])
        self.assertEqual(p["outputs"], ["z_out", "a_out"])
        self.assertEqual(p["constraints"], ["Second.", "First.", "Second."])

    def test_result_shape_and_flags(self):
        for r in (build(*triple("create"), plan_id="p1"), build(None, None, None)):
            self.assertEqual(sorted(r), sorted(BUILD_KEYS))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)
        self.assertIs(build(*triple("create"), plan_id="p1")["plan"]["execution_allowed"], False)

    def test_deterministic_repeated_construction(self):
        t = triple("improve", [desc()])
        a, b = build(*t, plan_id="p1"), build(*t, plan_id="p1")
        self.assertEqual(a, b)
        self.assertIsNot(a["plan"], b["plan"])
        self.assertIsNot(a["plan"]["inputs"], b["plan"]["inputs"])

    def test_ready_only_with_valid_plan(self):
        for t, pid in ((triple("create"), "p1"), (triple("improve", [desc()]), "p2")):
            r = build(*t, plan_id=pid)
            self.assertEqual(r["status"] == "ready", validate(r["plan"])["valid"])


class BuildFailureTests(unittest.TestCase):
    def test_invalid_request(self):
        _, analysis, spec = triple("create")
        for bad in (None, {}, req(operation="delete"), req(execution_allowed=True)):
            r = build(bad, analysis, spec, "p1")
            self.assertEqual((r["status"], r["plan"]), ("invalid_request", None))

    def test_invalid_analysis(self):
        request, analysis, spec = triple("create")
        for bad in (None, {}, dict(analysis, executed=True)):
            self.assertEqual(build(request, bad, spec, "p1")["status"], "invalid_analysis")

    def test_invalid_specification(self):
        request, analysis, spec = triple("create")
        for bad in (None, {}, dict(spec, execution_allowed=True)):
            self.assertEqual(build(request, analysis, bad, "p1")["status"],
                             "invalid_specification")

    def test_validation_order(self):
        self.assertEqual(build(None, None, None, None)["status"], "invalid_request")
        self.assertEqual(build(req(), None, None, None)["status"], "invalid_analysis")
        self.assertEqual(build(req(), analyze(req(), []), None, None)["status"],
                         "invalid_specification")

    def test_invalid_validation_result(self):
        forged = real_context(*triple("create"))
        forged["ready"] = False
        with mock.patch.object(plan_module, "validate_capability_evolution",
                               return_value=forged):
            r = build(*triple("create"), plan_id="p1")
        self.assertEqual((r["status"], r["plan"]), ("invalid_validation", None))

    def test_request_analysis_mismatch(self):
        request, _, spec = triple("create")
        analysis = analyze(req(operation="improve"), [desc()])
        r = build(request, analysis, spec, "p1")
        self.assertEqual((r["status"], r["plan"]), ("context_mismatch", None))

    def test_request_specification_mismatch(self):
        request, analysis, _ = triple("create")
        spec = triple("create", request_id="evo_999")[2]
        self.assertEqual(build(request, analysis, spec, "p1")["status"], "context_mismatch")
        spec = triple("create", capability_name="other_cap")[2]
        self.assertEqual(build(request, analysis, spec, "p1")["status"], "context_mismatch")

    def test_analysis_specification_mismatch(self):
        request = req()
        analysis = analyze(request, [])
        spec = triple("create", [desc()])[2]
        self.assertEqual(build(request, analysis, spec, "p1")["status"], "context_mismatch")
        request = req(operation="improve")
        analysis = analyze(request, [desc()])
        spec = triple("improve", [desc(version=2)])[2]
        self.assertEqual(build(request, analysis, spec, "p1")["status"], "context_mismatch")

    def test_validation_result_context_mismatch(self):
        t = triple("create")
        for key, bad in (("request_id", "evo_999"), ("capability_name", "other_cap"),
                         ("operation", "improve"), ("analysis_status", "improve_required")):
            forged = real_context(*t)
            forged[key] = bad
            with mock.patch.object(plan_module, "validate_capability_evolution",
                                   return_value=forged):
                # an inconsistent forged result may also be an invalid result
                r = build(*t, plan_id="p1")
            self.assertIn(r["status"], ("context_mismatch", "invalid_validation"), key)
            self.assertIsNone(r["plan"])

    def test_missing_plan_id(self):
        r = build(*triple("create"))
        self.assertEqual((r["status"], r["plan"]), ("invalid_plan_id", None))
        self.assertEqual(build(*triple("create"), plan_id=None)["status"], "invalid_plan_id")

    def test_plan_id_never_generated(self):
        for t in (triple("create"), triple("improve", [desc()])):
            self.assertIsNone(build(*t)["plan"])

    def test_invalid_plan_ids(self):
        for bad in ("", " x", "x ", 5, True, ["a"], "a" * 65, "a\nb"):
            r = build(*triple("create"), plan_id=bad)
            self.assertEqual((r["status"], r["plan"]), ("invalid_plan_id", None), bad)

    def test_plan_id_checked_before_unsupported_status(self):
        t = triple("create", [desc()])
        self.assertEqual(build(*t)["status"], "invalid_plan_id")

    def test_improve_or_conflict_unsupported(self):
        t = triple("create", [desc()])
        self.assertEqual(t[1]["status"], "improve_or_conflict")
        r = build(*t, plan_id="p1")
        self.assertEqual((r["status"], r["plan"]), ("unsupported_status", None))

    def test_not_ready_context_unsupported(self):
        t = triple("create")
        forged = real_context(*t)
        forged.update(status="not_ready", ready=False, reason="analysis_status_not_supported",
                      analysis_status="missing_target")
        with mock.patch.object(plan_module, "validate_capability_evolution",
                               return_value=forged):
            r = build(*t, plan_id="p1")
        self.assertEqual(r["status"], "unsupported_status")

    def test_missing_target_never_planned(self):
        request = req(operation="improve")
        analysis = analyze(request, [])
        r = build(request, analysis, triple("improve", [desc()])[2], "p1")
        self.assertIsNone(r["plan"])
        self.assertNotEqual(r["status"], "ready")

    def test_plan_error_when_plan_invalid(self):
        with mock.patch.object(plan_module, "_plan_errors",
                               return_value=[{"code": "x", "where": "y"}]):
            r = build(*triple("create"), plan_id="p1")
        self.assertEqual((r["status"], r["plan"]), ("plan_error", None))

    def test_never_raises(self):
        class Boom(dict):
            def __getitem__(self, k):
                raise RuntimeError("boom")
        r = build(Boom(), Boom(), Boom(), Boom())
        self.assertEqual(r["plan"], None)
        validate(Boom())
        with mock.patch.object(plan_module, "validate_capability_evolution",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(build(*triple("create"), plan_id="p1")["status"],
                             "validation_error")


class ImmutabilityTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for t in (triple("create"), triple("improve", [desc()])):
            before = copy.deepcopy(t)
            build(*t, plan_id="p1")
            self.assertEqual(t, before)

    def test_plan_does_not_alias_inputs(self):
        request, analysis, spec = triple("improve", [desc()])
        p = build(request, analysis, spec, "p1")["plan"]
        p["inputs"].append("mutated")
        p["existing_capability"]["inputs"].append("mutated")
        self.assertEqual(request["inputs"], ["z_input", "a_input"])
        self.assertEqual(analysis["existing"], desc())
        self.assertEqual(spec["existing_capability"], desc())

    def test_validate_does_not_mutate(self):
        p = make("improve")
        before = copy.deepcopy(p)
        validate(p)
        self.assertEqual(p, before)


class ValidatePlanTests(unittest.TestCase):
    def codes(self, p):
        return [e["code"] for e in validate(p)["errors"]]

    def test_not_dict(self):
        for bad in (None, [], "x", 1, ()):
            self.assertEqual(self.codes(bad), ["plan_not_dict"])

    def test_missing_keys(self):
        for key in PLAN_KEYS:
            p = make()
            del p[key]
            self.assertIn("missing_key", self.codes(p), key)
        self.assertFalse(validate({})["valid"])

    def test_extra_keys_and_equivalent_execution_flags(self):
        for extra in ("extra", "executed", "execute", "execution", "run", "apply"):
            p = make()
            p[extra] = True
            self.assertIn("unexpected_key", self.codes(p), extra)

    def test_wrong_types(self):
        for key in ("version", "plan_id", "request_id", "operation", "capability_name",
                    "goal", "inputs", "outputs", "constraints", "analysis_status"):
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
        for key, code in (("plan_id", "invalid_plan_id"), ("request_id", "invalid_request_id")):
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

    def test_invalid_lists(self):
        p = make()
        p["outputs"] = []
        self.assertIn("empty_outputs", self.codes(p))
        p = make()
        p["inputs"] = ["a", "a"]
        self.assertIn("duplicate_item", self.codes(p))
        p = make()
        p["constraints"] = [""]
        self.assertIn("invalid_item", self.codes(p))

    def test_create_with_improve_status(self):
        p = make("create")
        p["analysis_status"] = "improve_required"
        self.assertIn("inconsistent_plan", self.codes(p))

    def test_improve_with_create_status(self):
        p = make("improve")
        p["analysis_status"] = "create_required"
        self.assertIn("inconsistent_plan", self.codes(p))

    def test_create_with_existing_capability(self):
        p = make("create")
        p["existing_capability"] = desc()
        self.assertIn("inconsistent_plan", self.codes(p))

    def test_improve_without_existing_capability(self):
        p = make("improve")
        p["existing_capability"] = None
        self.assertIn("inconsistent_plan", self.codes(p))

    def test_improve_with_wrong_existing_capability(self):
        p = make("improve")
        p["existing_capability"] = desc("other_cap")
        self.assertIn("inconsistent_plan", self.codes(p))

    def test_invalid_existing_capability(self):
        for bad in ({}, "x", desc(enabled=1), desc(version=0), [desc()]):
            p = make("improve")
            p["existing_capability"] = bad
            self.assertIn("invalid_existing_capability", self.codes(p))

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
        path = os.path.join(ROOT, "capabilities", "capability_evolution_plan.py")
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
                                    ".capability_evolution_request",
                                    ".capability_evolution_specification",
                                    ".capability_evolution_validation",
                                    ".capability_registry"})
        for banned in ("open", "exec", "eval", "compile", "__import__"):
            self.assertNotIn(banned, calls)


if __name__ == "__main__":
    unittest.main()
