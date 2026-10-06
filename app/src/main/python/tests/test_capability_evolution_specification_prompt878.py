"""
Prompt 878 - capability evolution specification focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_evolution_specification_prompt878 -v
"""

import ast
import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.capability_evolution_analysis import analyze_capability_evolution as analyze
from capabilities.capability_evolution_specification import (
    build_capability_evolution_specification as build,
    validate_capability_evolution_specification as validate)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SPEC_KEYS = ["version", "specification_id", "request_id", "operation", "capability_name", "goal",
             "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
             "execution_allowed"]
BUILD_KEYS = ["valid", "errors", "specification", "execution_allowed", "executed"]


def req(**over):
    d = {"version": "1", "request_id": "evo_001", "operation": "create",
         "capability_name": "text_summarizer", "goal": "Summarize short documents.",
         "inputs": ["z_input", "a_input"], "outputs": ["z_out", "a_out"],
         "constraints": ["Second rule.", "First rule.", "Second rule."],
         "requested_by": "developer", "execution_allowed": False}
    d.update(over)
    return d


def desc(name="text_summarizer", **over):
    d = {"name": name, "version": 1, "purpose": "Summarize text.", "inputs": ["document_text"],
         "outputs": ["summary_text"], "constraints": ["Pure Python only."], "enabled": True}
    d.update(over)
    return d


def make(op="create", caps=None, **kw):
    request = req(operation=op)
    analysis = analyze(request, [] if caps is None else caps)
    return request, analysis, build(request, analysis, specification_id="spec_001", **kw)


def build_codes(result):
    return [e["code"] for e in result["errors"]]


def val_codes(spec):
    return [e["code"] for e in validate(spec)["errors"]]


class BuildValidTests(unittest.TestCase):
    def test_create_specification(self):
        request, analysis, r = make("create")
        self.assertTrue(r["valid"], r)
        s = r["specification"]
        self.assertEqual(sorted(s), sorted(SPEC_KEYS))
        self.assertEqual(s["analysis_status"], "create_required")
        self.assertIsNone(s["existing_capability"])
        self.assertEqual(s["operation"], "create")
        self.assertTrue(validate(s)["valid"])

    def test_improve_specification(self):
        request, analysis, r = make("improve", [desc()])
        self.assertTrue(r["valid"], r)
        s = r["specification"]
        self.assertEqual(s["analysis_status"], "improve_required")
        self.assertEqual(s["existing_capability"], desc())
        self.assertTrue(validate(s)["valid"])

    def test_improve_or_conflict_specification_preserves_status(self):
        request, analysis, r = make("create", [desc()])
        self.assertTrue(r["valid"], r)
        s = r["specification"]
        self.assertEqual(s["analysis_status"], "improve_or_conflict")
        self.assertEqual(s["operation"], "create")
        self.assertEqual(s["existing_capability"], desc())
        self.assertTrue(validate(s)["valid"])

    def test_build_result_shape_and_flags(self):
        ok = make("create")[2]
        bad = build(None, None)
        for r in (ok, bad):
            self.assertEqual(sorted(r), sorted(BUILD_KEYS))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)
        self.assertIs(ok["specification"]["execution_allowed"], False)
        self.assertIsNone(bad["specification"])

    def test_exact_preservation(self):
        request, analysis, r = make("create")
        s = r["specification"]
        self.assertEqual(s["version"], "1")
        self.assertEqual(s["request_id"], request["request_id"])
        self.assertEqual(s["capability_name"], request["capability_name"])
        self.assertEqual(s["goal"], request["goal"])
        self.assertEqual(s["inputs"], ["z_input", "a_input"])
        self.assertEqual(s["outputs"], ["z_out", "a_out"])
        self.assertEqual(s["constraints"], ["Second rule.", "First rule.", "Second rule."])

    def test_deterministic(self):
        a = make("improve", [desc()])[2]
        b = make("improve", [desc()])[2]
        self.assertEqual(a, b)

    def test_explicit_existing_capability_accepted(self):
        request = req(operation="improve")
        analysis = analyze(request, [desc()])
        r = build(request, analysis, desc(), "spec_001")
        self.assertTrue(r["valid"], r)
        self.assertEqual(r["specification"]["existing_capability"], desc())


class SpecificationIdTests(unittest.TestCase):
    def test_missing_id_fails(self):
        request = req()
        r = build(request, analyze(request, []))
        self.assertFalse(r["valid"])
        self.assertEqual(build_codes(r), ["missing_specification_id"])
        self.assertIsNone(r["specification"])

    def test_id_never_generated(self):
        request = req()
        r = build(request, analyze(request, []), None, None)
        self.assertIsNone(r["specification"])
        ok = build(request, analyze(request, []), specification_id="my_exact_id")
        self.assertEqual(ok["specification"]["specification_id"], "my_exact_id")

    def test_invalid_ids(self):
        request = req()
        analysis = analyze(request, [])
        for bad in ("", " x", "x ", 5, True, ["a"], "a" * 65, "a\nb"):
            r = build(request, analysis, specification_id=bad)
            self.assertFalse(r["valid"], bad)
            self.assertEqual(build_codes(r), ["invalid_specification_id"], bad)


class BuildFailureOrderTests(unittest.TestCase):
    def test_invalid_request(self):
        for bad in (None, {}, req(operation="delete"), req(execution_allowed=True)):
            r = build(bad, analyze(req(), []), specification_id="s1")
            self.assertEqual(build_codes(r), ["invalid_evolution_request"])

    def test_invalid_analysis(self):
        good = analyze(req(), [])
        broken = dict(good, executed=True)
        extra = dict(good, extra=1)
        for bad in (None, {}, broken, extra):
            r = build(req(), bad, specification_id="s1")
            self.assertEqual(build_codes(r), ["invalid_analysis_result"])

    def test_request_checked_before_analysis(self):
        self.assertEqual(build_codes(build(None, None, specification_id="s1")),
                         ["invalid_evolution_request"])

    def test_operation_mismatch(self):
        analysis = analyze(req(operation="improve"), [desc()])
        r = build(req(operation="create"), analysis, specification_id="s1")
        self.assertEqual(build_codes(r), ["operation_mismatch"])

    def test_capability_name_mismatch(self):
        analysis = analyze(req(capability_name="other_cap"), [])
        r = build(req(), analysis, specification_id="s1")
        self.assertEqual(build_codes(r), ["capability_name_mismatch"])

    def test_operation_checked_before_name(self):
        analysis = analyze(req(operation="improve", capability_name="other_cap"), [])
        r = build(req(), analysis, specification_id="s1")
        self.assertEqual(build_codes(r), ["operation_mismatch"])

    def test_invalid_existing_capability(self):
        request = req(operation="improve")
        analysis = analyze(request, [desc()])
        for bad in ({}, "x", desc(enabled="yes"), [desc()], 5):
            r = build(request, analysis, bad, "s1")
            self.assertEqual(build_codes(r), ["invalid_existing_capability"], bad)

    def test_existing_identity_mismatch(self):
        request = req(operation="improve")
        analysis = analyze(request, [desc()])
        for other in (desc(version=2), desc("other_cap"), desc(purpose="Different.")):
            r = build(request, analysis, other, "s1")
            self.assertEqual(build_codes(r), ["existing_identity_mismatch"])

    def test_existing_supplied_for_create_required(self):
        request = req()
        r = build(request, analyze(request, []), desc(), "s1")
        self.assertEqual(build_codes(r), ["existing_identity_mismatch"])

    def test_missing_target_unsupported(self):
        request = req(operation="improve")
        analysis = analyze(request, [])
        self.assertEqual(analysis["status"], "missing_target")
        r = build(request, analysis, specification_id="s1")
        self.assertEqual(build_codes(r), ["unsupported_analysis_status"])
        self.assertIsNone(r["specification"])

    def test_other_statuses_unsupported(self):
        request = req()
        analysis = analyze(request, [desc(), desc()])
        self.assertEqual(analysis["status"], "invalid_capabilities")
        r = build(request, analysis, specification_id="s1")
        self.assertEqual(build_codes(r), ["unsupported_analysis_status"])

    def test_status_checked_before_id(self):
        request = req(operation="improve")
        r = build(request, analyze(request, []))
        self.assertEqual(build_codes(r), ["unsupported_analysis_status"])

    def test_never_raises(self):
        class Boom(dict):
            def __getitem__(self, k):
                raise RuntimeError("boom")
        for bad in (Boom(), object(), [Boom()]):
            r = build(bad, bad, bad, bad)
            self.assertFalse(r["valid"])
            validate(bad)


class CopyAndImmutabilityTests(unittest.TestCase):
    def test_specification_is_deep_copy(self):
        request, analysis, r = make("improve", [desc()])
        s = r["specification"]
        for key in ("inputs", "outputs", "constraints"):
            self.assertIsNot(s[key], request[key])
        self.assertIsNot(s["existing_capability"], analysis["existing"])
        self.assertIsNot(s["existing_capability"]["inputs"], analysis["existing"]["inputs"])
        s["inputs"].append("mutated")
        s["existing_capability"]["inputs"].append("mutated")
        self.assertEqual(request["inputs"], ["z_input", "a_input"])
        self.assertEqual(analysis["existing"], desc())

    def test_explicit_existing_not_aliased(self):
        request = req(operation="improve")
        analysis = analyze(request, [desc()])
        supplied = desc()
        s = build(request, analysis, supplied, "s1")["specification"]
        s["existing_capability"]["outputs"].append("mutated")
        self.assertEqual(supplied, desc())

    def test_inputs_not_mutated(self):
        request = req(operation="improve")
        analysis = analyze(request, [desc()])
        existing = desc()
        before = copy.deepcopy((request, analysis, existing))
        build(request, analysis, existing, "s1")
        self.assertEqual((request, analysis, existing), before)

    def test_results_are_fresh(self):
        request = req()
        analysis = analyze(request, [])
        a = build(request, analysis, specification_id="s1")
        b = build(request, analysis, specification_id="s1")
        self.assertIsNot(a["specification"], b["specification"])
        self.assertIsNot(a["specification"]["inputs"], b["specification"]["inputs"])


class ValidateSpecificationTests(unittest.TestCase):
    def good(self, kind="create_required"):
        if kind == "create_required":
            return make("create")[2]["specification"]
        if kind == "improve_required":
            return make("improve", [desc()])[2]["specification"]
        return make("create", [desc()])[2]["specification"]

    def test_not_dict(self):
        for bad in (None, [], "x", 1):
            self.assertEqual(val_codes(bad), ["specification_not_dict"])

    def test_missing_and_extra_keys(self):
        for key in SPEC_KEYS:
            s = self.good()
            del s[key]
            self.assertIn("missing_key", val_codes(s), key)
        s = self.good()
        s["extra"] = 1
        self.assertIn("unexpected_key", val_codes(s))
        self.assertFalse(validate({})["valid"])

    def test_bad_version(self):
        for bad in ("2", 1, None):
            s = self.good()
            s["version"] = bad
            self.assertIn("invalid_version", val_codes(s))

    def test_bad_text_fields(self):
        for key, code in (("specification_id", "invalid_specification_id"),
                          ("request_id", "invalid_request_id"),
                          ("capability_name", "invalid_capability_name"),
                          ("goal", "invalid_goal")):
            for bad in ("", " x", None, 3):
                s = self.good()
                s[key] = bad
                self.assertIn(code, val_codes(s), (key, bad))

    def test_bad_lists(self):
        s = self.good()
        s["inputs"] = "x"
        self.assertIn("invalid_inputs", val_codes(s))
        s = self.good()
        s["outputs"] = []
        self.assertIn("empty_outputs", val_codes(s))
        s = self.good()
        s["inputs"] = ["a", "a"]
        self.assertIn("duplicate_item", val_codes(s))
        s = self.good()
        s["constraints"] = [""]
        self.assertIn("invalid_item", val_codes(s))

    def test_invalid_operation(self):
        s = self.good()
        s["operation"] = "delete"
        self.assertIn("invalid_operation", val_codes(s))

    def test_invalid_analysis_status(self):
        for bad in ("nope", None, 3, "Create_Required"):
            s = self.good()
            s["analysis_status"] = bad
            self.assertIn("invalid_analysis_status", val_codes(s))

    def test_missing_target_and_other_statuses_rejected(self):
        for status in ("missing_target", "invalid_request", "invalid_capabilities",
                       "analysis_error"):
            s = self.good("improve_required")
            s["analysis_status"] = status
            self.assertIn("unsupported_analysis_status", val_codes(s), status)

    def test_malformed_existing_descriptor(self):
        for bad in ({}, "x", desc(enabled=1), desc(version=0), [desc()]):
            s = self.good("improve_required")
            s["existing_capability"] = bad
            self.assertIn("invalid_existing_capability", val_codes(s))

    def test_create_required_with_existing(self):
        s = self.good("create_required")
        s["existing_capability"] = desc()
        self.assertIn("inconsistent_specification", val_codes(s))

    def test_improve_required_without_existing(self):
        s = self.good("improve_required")
        s["existing_capability"] = None
        self.assertIn("inconsistent_specification", val_codes(s))

    def test_improve_or_conflict_without_existing(self):
        s = self.good("improve_or_conflict")
        s["existing_capability"] = None
        self.assertIn("inconsistent_specification", val_codes(s))

    def test_improve_operation_without_existing(self):
        s = self.good("create_required")
        s["operation"] = "improve"
        self.assertIn("inconsistent_specification", val_codes(s))

    def test_operation_status_combinations(self):
        s = self.good("improve_required")
        s["operation"] = "create"
        self.assertIn("inconsistent_specification", val_codes(s))
        s = self.good("improve_or_conflict")
        s["operation"] = "improve"
        self.assertIn("inconsistent_specification", val_codes(s))
        s = self.good("create_required")
        s["analysis_status"] = "improve_required"
        self.assertFalse(validate(s)["valid"])

    def test_existing_name_must_match(self):
        s = self.good("improve_required")
        s["capability_name"] = "other_cap"
        self.assertIn("inconsistent_specification", val_codes(s))

    def test_execution_flag(self):
        for bad in (True, 0, 1, None, "False"):
            s = self.good()
            s["execution_allowed"] = bad
            self.assertIn("invalid_execution_allowed", val_codes(s), bad)
            v = validate(s)
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)

    def test_validation_result_shape_and_no_mutation(self):
        s = self.good("improve_required")
        before = copy.deepcopy(s)
        v = validate(s)
        self.assertEqual(sorted(v), ["errors", "executed", "execution_allowed", "valid"])
        self.assertEqual(s, before)


class SafetyTests(unittest.TestCase):
    def test_imports_and_calls_are_safe(self):
        path = os.path.join(ROOT, "capabilities", "capability_evolution_specification.py")
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
                                    ".capability_evolution_request", ".capability_registry"})
        for banned in ("open", "exec", "eval", "compile", "__import__"):
            self.assertNotIn(banned, calls)


if __name__ == "__main__":
    unittest.main()
