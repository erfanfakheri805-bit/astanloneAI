"""
Prompt 879 - capability evolution validation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_evolution_validation_prompt879 -v
"""

import ast
import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.capability_evolution_analysis import analyze_capability_evolution as analyze
from capabilities.capability_evolution_specification import (
    build_capability_evolution_specification as build_spec)
from capabilities.capability_evolution_validation import (
    validate_capability_evolution as check,
    validate_capability_evolution_result as validate)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["status", "ready", "request_id", "capability_name", "operation", "analysis_status",
        "reason", "execution_allowed", "executed"]


def req(**over):
    d = {"version": "1", "request_id": "evo_001", "operation": "create",
         "capability_name": "text_summarizer", "goal": "Summarize short documents.",
         "inputs": ["z_input", "a_input"], "outputs": ["z_out"],
         "constraints": ["Rule."], "requested_by": "developer", "execution_allowed": False}
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


def reason(result):
    return result["status"], result["reason"]


class ReadyPathTests(unittest.TestCase):
    def test_create_path(self):
        r = check(*triple("create"))
        self.assertEqual(r["status"], "ready")
        self.assertIs(r["ready"], True)
        self.assertEqual(r["reason"], "ready")
        self.assertEqual((r["request_id"], r["capability_name"], r["operation"]),
                         ("evo_001", "text_summarizer", "create"))
        self.assertEqual(r["analysis_status"], "create_required")

    def test_improve_path(self):
        r = check(*triple("improve", [desc()]))
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["analysis_status"], "improve_required")
        self.assertEqual(r["operation"], "improve")

    def test_improve_or_conflict_path_not_upgraded(self):
        r = check(*triple("create", [desc()]))
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["analysis_status"], "improve_or_conflict")
        self.assertEqual(r["operation"], "create")

    def test_result_shape_flags_and_validates(self):
        results = [check(*triple("create")), check(*triple("improve", [desc()])),
                   check(None, None, None), check(*triple("create")[:2], None)]
        for r in results:
            self.assertEqual(sorted(r), sorted(KEYS))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)
            self.assertTrue(validate(r)["valid"], (r, validate(r)))

    def test_ready_only_for_ready_status(self):
        good = check(*triple("create"))
        bad = check(None, None, None)
        self.assertTrue(good["ready"])
        self.assertFalse(bad["ready"])

    def test_deterministic_and_fresh(self):
        t = triple("improve", [desc()])
        a, b = check(*t), check(*t)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)


class InvalidInputTests(unittest.TestCase):
    def test_invalid_request(self):
        _, analysis, spec = triple("create")
        for bad in (None, {}, req(operation="delete"), req(execution_allowed=True)):
            r = check(bad, analysis, spec)
            self.assertEqual(reason(r), ("invalid_request", "invalid_evolution_request"))
            for key in ("request_id", "capability_name", "operation", "analysis_status"):
                self.assertIsNone(r[key])

    def test_invalid_analysis(self):
        request, analysis, spec = triple("create")
        for bad in (None, {}, dict(analysis, executed=True), dict(analysis, extra=1)):
            r = check(request, bad, spec)
            self.assertEqual(reason(r), ("invalid_analysis", "invalid_analysis_result"))
            self.assertEqual(r["request_id"], "evo_001")
            self.assertEqual(r["operation"], "create")
            self.assertIsNone(r["analysis_status"])

    def test_invalid_specification(self):
        request, analysis, spec = triple("create")
        for bad in (None, {}, dict(spec, execution_allowed=True), dict(spec, version="2")):
            r = check(request, analysis, bad)
            self.assertEqual(reason(r), ("invalid_specification", "invalid_specification"))
            self.assertEqual(r["analysis_status"], "create_required")
            self.assertEqual(r["capability_name"], "text_summarizer")

    def test_order_request_before_analysis_before_specification(self):
        self.assertEqual(check(None, None, None)["status"], "invalid_request")
        self.assertEqual(check(req(), None, None)["status"], "invalid_analysis")
        self.assertEqual(check(req(), analyze(req(), []), None)["status"],
                         "invalid_specification")

    def test_missing_target_cannot_become_ready(self):
        request = req(operation="improve")
        analysis = analyze(request, [])
        self.assertEqual(analysis["status"], "missing_target")
        self.assertFalse(build_spec(request, analysis, specification_id="s1")["valid"])
        forged = triple("improve", [desc()])[2]
        forged["analysis_status"] = "missing_target"
        r = check(request, analysis, forged)
        self.assertEqual(r["status"], "invalid_specification")
        self.assertFalse(r["ready"])

    def test_never_raises(self):
        class Boom(dict):
            def __getitem__(self, k):
                raise RuntimeError("boom")
        r = check(Boom(), Boom(), Boom())
        self.assertFalse(r["ready"])
        validate(Boom())
        validate(object())


class ContextMismatchTests(unittest.TestCase):
    def test_request_analysis_operation(self):
        request, _, spec = triple("create")
        analysis = analyze(req(operation="improve"), [desc()])
        r = check(request, analysis, spec)
        self.assertEqual(reason(r), ("context_mismatch", "request_analysis_operation_mismatch"))
        self.assertFalse(r["ready"])
        self.assertEqual(r["analysis_status"], "improve_required")

    def test_request_analysis_capability_name(self):
        request, _, spec = triple("create")
        analysis = analyze(req(capability_name="other_cap"), [])
        r = check(request, analysis, spec)
        self.assertEqual(reason(r),
                         ("context_mismatch", "request_analysis_capability_name_mismatch"))

    def test_request_specification_request_id(self):
        request, analysis, _ = triple("create")
        spec = triple("create", request_id="evo_999")[2]
        r = check(request, analysis, spec)
        self.assertEqual(reason(r),
                         ("context_mismatch", "request_specification_request_id_mismatch"))
        self.assertEqual(r["request_id"], "evo_001")

    def test_request_specification_operation(self):
        request = req(operation="improve")
        analysis = analyze(request, [desc()])
        spec = triple("create", [desc()])[2]
        r = check(request, analysis, spec)
        self.assertEqual(reason(r),
                         ("context_mismatch", "request_specification_operation_mismatch"))

    def test_request_specification_capability_name(self):
        request, analysis, _ = triple("create")
        spec = triple("create", capability_name="other_cap")[2]
        r = check(request, analysis, spec)
        self.assertEqual(reason(r),
                         ("context_mismatch", "request_specification_capability_name_mismatch"))

    def test_analysis_specification_status(self):
        request = req()
        analysis = analyze(request, [])
        spec = triple("create", [desc()])[2]
        self.assertEqual(spec["analysis_status"], "improve_or_conflict")
        r = check(request, analysis, spec)
        self.assertEqual(reason(r),
                         ("context_mismatch", "analysis_specification_status_mismatch"))
        self.assertEqual(r["analysis_status"], "create_required")

    def test_analysis_specification_existing(self):
        request = req(operation="improve")
        analysis = analyze(request, [desc()])
        spec = triple("improve", [desc(version=2)])[2]
        r = check(request, analysis, spec)
        self.assertEqual(reason(r),
                         ("context_mismatch", "analysis_specification_existing_mismatch"))

    def test_existing_difference_in_nested_value(self):
        request = req(operation="improve")
        analysis = analyze(request, [desc()])
        spec = triple("improve", [desc(inputs=["other_input"])])[2]
        self.assertEqual(check(request, analysis, spec)["reason"],
                         "analysis_specification_existing_mismatch")

    def test_mismatch_order_operation_before_name(self):
        request, _, spec = triple("create")
        analysis = analyze(req(operation="improve", capability_name="other_cap"), [])
        self.assertEqual(check(request, analysis, spec)["reason"],
                         "request_analysis_operation_mismatch")


class ImmutabilityTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for t in (triple("create"), triple("improve", [desc()]), triple("create", [desc()])):
            before = copy.deepcopy(t)
            check(*t)
            self.assertEqual(t, before)

    def test_result_does_not_alias_inputs(self):
        request, analysis, spec = triple("create")
        r = check(request, analysis, spec)
        r["request_id"] = "changed"
        self.assertEqual(request["request_id"], "evo_001")


class ValidateResultTests(unittest.TestCase):
    def good(self, kind="ready"):
        return {
            "ready": check(*triple("create")),
            "invalid_request": check(None, None, None),
            "invalid_analysis": check(req(), None, None),
            "invalid_specification": check(req(), analyze(req(), []), None),
            "context_mismatch": check(req(), analyze(req(), []),
                                      triple("create", [desc()])[2]),
        }[kind]

    def codes(self, r):
        return [e["code"] for e in validate(r)["errors"]]

    def test_not_dict(self):
        for bad in (None, [], "x", 1):
            self.assertEqual(self.codes(bad), ["result_not_dict"])

    def test_missing_and_extra_keys(self):
        for key in KEYS:
            r = self.good()
            del r[key]
            self.assertIn("missing_key", self.codes(r), key)
        r = self.good()
        r["extra"] = 1
        self.assertIn("unexpected_key", self.codes(r))
        self.assertFalse(validate({})["valid"])

    def test_all_generated_kinds_valid(self):
        for kind in ("ready", "invalid_request", "invalid_analysis", "invalid_specification",
                     "context_mismatch"):
            self.assertTrue(validate(self.good(kind))["valid"], kind)

    def test_invalid_status(self):
        for bad in ("nope", None, 3, "Ready"):
            r = self.good()
            r["status"] = bad
            self.assertIn("invalid_status", self.codes(r))

    def test_ready_true_with_other_status(self):
        r = self.good("invalid_request")
        r["ready"] = True
        self.assertIn("inconsistent_result", self.codes(r))
        r = self.good("context_mismatch")
        r["ready"] = True
        self.assertFalse(validate(r)["valid"])

    def test_ready_false_with_ready_status(self):
        r = self.good()
        r["ready"] = False
        self.assertIn("inconsistent_result", self.codes(r))

    def test_ready_flag_must_be_bool(self):
        for bad in (1, 0, None, "True"):
            r = self.good()
            r["ready"] = bad
            self.assertIn("invalid_ready", self.codes(r))

    def test_ready_with_missing_identity(self):
        for key in ("request_id", "capability_name", "operation"):
            r = self.good()
            r[key] = None
            self.assertFalse(validate(r)["valid"], key)

    def test_ready_without_analysis_status(self):
        r = self.good()
        r["analysis_status"] = None
        self.assertIn("inconsistent_result", self.codes(r))

    def test_invalid_statuses_must_not_carry_fabricated_identity(self):
        r = self.good("invalid_request")
        r["request_id"] = "evo_001"
        self.assertFalse(validate(r)["valid"])
        r = self.good("invalid_request")
        r["analysis_status"] = "create_required"
        self.assertFalse(validate(r)["valid"])
        r = self.good("invalid_analysis")
        r["analysis_status"] = "create_required"
        self.assertFalse(validate(r)["valid"])
        r = self.good("invalid_specification")
        r["capability_name"] = None
        r["request_id"] = None
        r["operation"] = None
        self.assertFalse(validate(r)["valid"])

    def test_invalid_identity_values(self):
        for key, code in (("request_id", "invalid_request_id"),
                          ("capability_name", "invalid_capability_name"),
                          ("operation", "invalid_operation")):
            for bad in ("", " x", 5, "delete" if key == "operation" else "a" * 65):
                r = self.good()
                r[key] = bad
                self.assertIn(code, self.codes(r), (key, bad))

    def test_invalid_analysis_status(self):
        for bad in ("nope", 3, "Create_Required"):
            r = self.good()
            r["analysis_status"] = bad
            self.assertIn("invalid_analysis_status", self.codes(r))

    def test_ready_with_unsupported_analysis_status(self):
        for status in ("missing_target", "invalid_capabilities", "analysis_error"):
            r = self.good()
            r["analysis_status"] = status
            self.assertIn("inconsistent_result", self.codes(r), status)

    def test_ready_operation_must_match_analysis_status(self):
        r = self.good()
        r["operation"] = "improve"
        self.assertIn("inconsistent_result", self.codes(r))
        r = self.good()
        r["analysis_status"] = "improve_required"
        self.assertFalse(validate(r)["valid"])

    def test_not_ready_shape(self):
        r = self.good()
        r.update(status="not_ready", ready=False, reason="analysis_status_not_supported",
                 analysis_status="missing_target")
        self.assertTrue(validate(r)["valid"], validate(r))
        r["analysis_status"] = "create_required"
        self.assertFalse(validate(r)["valid"])

    def test_reason_must_belong_to_status(self):
        r = self.good()
        r["reason"] = "invalid_evolution_request"
        self.assertIn("inconsistent_result", self.codes(r))
        for bad in ("", None, 4):
            r = self.good()
            r["reason"] = bad
            self.assertIn("invalid_reason", self.codes(r))

    def test_execution_flags(self):
        for key, code in (("execution_allowed", "invalid_execution_allowed"),
                          ("executed", "invalid_executed")):
            for bad in (True, 0, 1, None, "False"):
                r = self.good()
                r[key] = bad
                self.assertIn(code, self.codes(r), (key, bad))
                v = validate(r)
                self.assertIs(v["execution_allowed"], False)
                self.assertIs(v["executed"], False)

    def test_validation_error_status(self):
        r = {"status": "validation_error", "ready": False, "request_id": None,
             "capability_name": None, "operation": None, "analysis_status": None,
             "reason": "validation_error", "execution_allowed": False, "executed": False}
        self.assertTrue(validate(r)["valid"])
        r["operation"] = "create"
        self.assertFalse(validate(r)["valid"])

    def test_validate_does_not_mutate_and_shape(self):
        r = self.good()
        before = copy.deepcopy(r)
        v = validate(r)
        self.assertEqual(r, before)
        self.assertEqual(sorted(v), ["errors", "executed", "execution_allowed", "valid"])


class SafetyTests(unittest.TestCase):
    def test_imports_and_calls_are_safe(self):
        path = os.path.join(ROOT, "capabilities", "capability_evolution_validation.py")
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
        self.assertEqual(imported, {".capability_evolution_analysis",
                                    ".capability_evolution_request",
                                    ".capability_evolution_specification",
                                    ".capability_registry"})
        for banned in ("open", "exec", "eval", "compile", "__import__"):
            self.assertNotIn(banned, calls)


if __name__ == "__main__":
    unittest.main()
