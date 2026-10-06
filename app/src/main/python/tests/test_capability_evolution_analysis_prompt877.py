"""
Prompt 877 - capability evolution analysis focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_evolution_analysis_prompt877 -v
"""

import ast
import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_evolution_analysis as m
from capabilities.capability_evolution_analysis import analyze_capability_evolution as analyze
from capabilities.capability_evolution_analysis import validate_capability_evolution_analysis as validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["status", "operation", "capability_name", "existing", "matching_count", "reason",
        "execution_allowed", "executed"]


def req(**over):
    d = {"version": "1", "request_id": "evo_001", "operation": "create",
         "capability_name": "text_summarizer", "goal": "Summarize short documents.",
         "inputs": ["document_text"], "outputs": ["summary_text"],
         "constraints": ["No network access."], "requested_by": "developer",
         "execution_allowed": False}
    d.update(over)
    return d


def desc(name="text_summarizer", **over):
    d = {"name": name, "version": 1, "purpose": "Summarize text.", "inputs": ["document_text"],
         "outputs": ["summary_text"], "constraints": ["Pure Python only."], "enabled": True}
    d.update(over)
    return d


def codes(result):
    return [e["code"] for e in validate(result)["errors"]]


class AnalyzeStatusTests(unittest.TestCase):
    def test_create_no_existing(self):
        r = analyze(req(), [desc("other_cap")])
        self.assertEqual(r["status"], "create_required")
        self.assertEqual(r["reason"], "no_existing_capability_for_create")
        self.assertIsNone(r["existing"])
        self.assertEqual(r["matching_count"], 0)

    def test_create_empty_list(self):
        self.assertEqual(analyze(req(), [])["status"], "create_required")

    def test_create_with_existing(self):
        r = analyze(req(), [desc()])
        self.assertEqual(r["status"], "improve_or_conflict")
        self.assertEqual(r["matching_count"], 1)
        self.assertEqual(r["existing"], desc())

    def test_improve_with_existing(self):
        r = analyze(req(operation="improve"), [desc("a"), desc()])
        self.assertEqual(r["status"], "improve_required")
        self.assertEqual(r["reason"], "existing_capability_found_for_improve")
        self.assertEqual(r["existing"]["name"], "text_summarizer")

    def test_improve_missing(self):
        r = analyze(req(operation="improve"), [desc("other_cap")])
        self.assertEqual(r["status"], "missing_target")
        self.assertEqual(r["reason"], "no_existing_capability_for_improve")
        self.assertIsNone(r["existing"])
        self.assertEqual(r["matching_count"], 0)

    def test_result_shape_and_flags(self):
        for r in (analyze(req(), []), analyze(req(), [desc()]), analyze(None, []),
                  analyze(req(), None)):
            self.assertEqual(sorted(r), sorted(KEYS))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_preserves_operation_and_name(self):
        r = analyze(req(operation="improve", capability_name="x_cap"), [desc("x_cap")])
        self.assertEqual((r["operation"], r["capability_name"]), ("improve", "x_cap"))

    def test_deterministic(self):
        caps = [desc(), desc("b_cap")]
        self.assertEqual(analyze(req(), caps), analyze(req(), caps))


class InvalidInputTests(unittest.TestCase):
    def test_duplicate_exact_matches(self):
        for op in ("create", "improve"):
            r = analyze(req(operation=op), [desc(), desc("z_cap"), desc(version=2)])
            self.assertEqual(r["status"], "invalid_capabilities")
            self.assertEqual(r["reason"], "duplicate_matching_capability_name")
            self.assertEqual(r["matching_count"], 2)
            self.assertIsNone(r["existing"])
            self.assertEqual(r["capability_name"], "text_summarizer")

    def test_unrelated_duplicates_do_not_matter(self):
        r = analyze(req(), [desc("dup_cap"), desc("dup_cap")])
        self.assertEqual(r["status"], "create_required")

    def test_invalid_request(self):
        for bad in (None, {}, "x", [], req(operation="delete"), req(execution_allowed=True),
                    {k: v for k, v in req().items() if k != "goal"}):
            r = analyze(bad, [desc()])
            self.assertEqual(r["status"], "invalid_request")
            self.assertEqual(r["reason"], "invalid_evolution_request")
            self.assertIsNone(r["operation"])
            self.assertIsNone(r["capability_name"])

    def test_invalid_request_checked_before_capabilities(self):
        self.assertEqual(analyze(None, None)["status"], "invalid_request")

    def test_invalid_capability_list(self):
        bad_lists = (None, "x", {}, (desc(),), [None], [{}], [desc(enabled="yes")],
                     [desc(), {"name": "x"}], [desc(name="Bad Name")])
        for bad in bad_lists:
            r = analyze(req(), bad)
            self.assertEqual(r["status"], "invalid_capabilities", bad)
            self.assertEqual(r["reason"], "invalid_capability_list")
            self.assertEqual(r["matching_count"], 0)
            self.assertEqual(r["operation"], "create")

    def test_too_many_capabilities(self):
        caps = [desc("cap_%d" % i) for i in range(257)]
        self.assertEqual(analyze(req(), caps)["status"], "invalid_capabilities")

    def test_invalid_descriptor_matching_name_not_selected(self):
        r = analyze(req(), [desc(version=0)])
        self.assertEqual(r["status"], "invalid_capabilities")
        self.assertIsNone(r["existing"])

    def test_never_raises_on_hostile_input(self):
        class Boom(dict):
            def __getitem__(self, k):
                raise RuntimeError("boom")
        for bad in (Boom(), object(), [Boom()]):
            analyze(bad, bad)
            validate(bad)


class MatchingTests(unittest.TestCase):
    def test_case_sensitive(self):
        # descriptors must be lowercase identifiers, so test the request side
        r = analyze(req(capability_name="Text_Summarizer"), [desc()])
        self.assertEqual(r["status"], "create_required")
        r = analyze(req(operation="improve", capability_name="TEXT_SUMMARIZER"), [desc()])
        self.assertEqual(r["status"], "missing_target")

    def test_no_substring_matching(self):
        caps = [desc("text_summarizer_v2"), desc("text")]
        self.assertEqual(analyze(req(), caps)["status"], "create_required")
        r = analyze(req(operation="improve", capability_name="text_summarizer_v2x"), caps)
        self.assertEqual(r["status"], "missing_target")

    def test_no_normalization_or_aliases(self):
        r = analyze(req(capability_name="text-summarizer"), [desc()])
        self.assertEqual(r["status"], "create_required")
        r = analyze(req(capability_name="text summarizer"), [desc()])
        self.assertEqual(r["status"], "create_required")

    def test_first_and_last_position_matches(self):
        for caps in ([desc(), desc("a")], [desc("a"), desc()]):
            self.assertEqual(analyze(req(), caps)["status"], "improve_or_conflict")


class CopyAndImmutabilityTests(unittest.TestCase):
    def test_existing_is_deep_copy(self):
        caps = [desc()]
        r = analyze(req(), caps)
        self.assertIsNot(r["existing"], caps[0])
        self.assertIsNot(r["existing"]["inputs"], caps[0]["inputs"])
        r["existing"]["inputs"].append("mutated")
        r["existing"]["name"] = "mutated"
        self.assertEqual(caps[0], desc())

    def test_inputs_not_mutated(self):
        for op in ("create", "improve"):
            request, caps = req(operation=op), [desc(), desc("b_cap")]
            r0, c0 = copy.deepcopy(request), copy.deepcopy(caps)
            analyze(request, caps)
            self.assertEqual(request, r0)
            self.assertEqual(caps, c0)

    def test_results_are_fresh(self):
        caps = [desc()]
        a, b = analyze(req(), caps), analyze(req(), caps)
        self.assertIsNot(a, b)
        self.assertIsNot(a["existing"], b["existing"])

    def test_analysis_results_validate(self):
        cases = [analyze(req(), []), analyze(req(), [desc()]),
                 analyze(req(operation="improve"), [desc()]),
                 analyze(req(operation="improve"), []), analyze(None, []),
                 analyze(req(), None), analyze(req(), [desc(), desc()])]
        for r in cases:
            v = validate(r)
            self.assertTrue(v["valid"], (r, v))
            self.assertEqual(sorted(v), ["errors", "executed", "execution_allowed", "valid"])
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)


class ValidateResultTests(unittest.TestCase):
    def good(self, status="create_required"):
        return {
            "create_required": analyze(req(), []),
            "improve_or_conflict": analyze(req(), [desc()]),
            "improve_required": analyze(req(operation="improve"), [desc()]),
            "missing_target": analyze(req(operation="improve"), []),
            "invalid_request": analyze(None, []),
            "invalid_capabilities": analyze(req(), [desc(), desc()]),
        }[status]

    def test_not_dict(self):
        for bad in (None, [], "x", 1, ()):
            self.assertEqual(codes(bad), ["result_not_dict"])

    def test_missing_and_extra_keys(self):
        r = self.good()
        del r["reason"]
        self.assertIn("missing_key", codes(r))
        r = self.good()
        r["extra"] = 1
        self.assertIn("unexpected_key", codes(r))
        self.assertFalse(validate({})["valid"])

    def test_invalid_status(self):
        for bad in ("nope", None, 1, "Create_Required"):
            r = self.good()
            r["status"] = bad
            self.assertIn("invalid_status", codes(r))

    def test_invalid_operation_and_name(self):
        r = self.good()
        r["operation"] = "delete"
        self.assertIn("invalid_operation", codes(r))
        r = self.good()
        r["capability_name"] = ""
        self.assertIn("invalid_capability_name", codes(r))
        r = self.good()
        r["capability_name"] = 5
        self.assertIn("invalid_capability_name", codes(r))
        r = self.good("invalid_request")
        r["operation"] = "create"
        self.assertIn("invalid_operation", codes(r))

    def test_mismatched_operation(self):
        r = self.good("improve_required")
        r["operation"] = "create"
        self.assertIn("inconsistent_result", codes(r))
        r = self.good("create_required")
        r["operation"] = "improve"
        self.assertIn("inconsistent_result", codes(r))

    def test_mismatched_existing_name(self):
        r = self.good("improve_required")
        r["capability_name"] = "other_cap"
        self.assertIn("inconsistent_result", codes(r))

    def test_invalid_existing(self):
        r = self.good("improve_required")
        r["existing"] = {"name": "text_summarizer"}
        self.assertIn("invalid_existing", codes(r))
        r["existing"] = "x"
        self.assertIn("invalid_existing", codes(r))

    def test_invalid_matching_count(self):
        for bad in (-1, True, False, 1.0, "1", None):
            r = self.good()
            r["matching_count"] = bad
            self.assertIn("invalid_matching_count", codes(r), bad)

    def test_invalid_reason(self):
        for bad in ("", None, 3):
            r = self.good()
            r["reason"] = bad
            self.assertIn("invalid_reason", codes(r))
        r = self.good()
        r["reason"] = "something_else"
        self.assertIn("inconsistent_result", codes(r))

    def test_reason_must_match_status(self):
        r = self.good("create_required")
        r["reason"] = "existing_capability_found_for_create"
        self.assertFalse(validate(r)["valid"])

    def test_create_required_with_existing(self):
        r = self.good("create_required")
        r["existing"] = desc()
        self.assertFalse(validate(r)["valid"])

    def test_create_required_with_count(self):
        r = self.good("create_required")
        r["matching_count"] = 1
        self.assertFalse(validate(r)["valid"])

    def test_improve_required_without_existing(self):
        r = self.good("improve_required")
        r["existing"] = None
        self.assertFalse(validate(r)["valid"])

    def test_improve_required_wrong_count(self):
        for bad in (0, 2):
            r = self.good("improve_required")
            r["matching_count"] = bad
            self.assertFalse(validate(r)["valid"])

    def test_improve_or_conflict_without_existing(self):
        r = self.good("improve_or_conflict")
        r["existing"] = None
        self.assertFalse(validate(r)["valid"])

    def test_missing_target_with_existing(self):
        r = self.good("missing_target")
        r["existing"] = desc()
        self.assertFalse(validate(r)["valid"])

    def test_invalid_capabilities_consistency(self):
        r = self.good("invalid_capabilities")
        r["matching_count"] = 1
        self.assertFalse(validate(r)["valid"])
        r = self.good("invalid_capabilities")
        r["existing"] = desc()
        self.assertFalse(validate(r)["valid"])
        r = analyze(req(), None)
        r["matching_count"] = 2
        self.assertFalse(validate(r)["valid"])

    def test_invalid_request_consistency(self):
        r = self.good("invalid_request")
        r["matching_count"] = 1
        self.assertFalse(validate(r)["valid"])
        r = self.good("invalid_request")
        r["capability_name"] = "x_cap"
        self.assertFalse(validate(r)["valid"])

    def test_execution_flags(self):
        for key, code in (("execution_allowed", "invalid_execution_allowed"),
                          ("executed", "invalid_executed")):
            for bad in (True, 0, 1, None, "False"):
                r = self.good()
                r[key] = bad
                self.assertIn(code, codes(r), (key, bad))
                self.assertIs(validate(r)["execution_allowed"], False)
                self.assertIs(validate(r)["executed"], False)

    def test_validate_does_not_mutate(self):
        r = self.good("improve_required")
        before = copy.deepcopy(r)
        validate(r)
        self.assertEqual(r, before)

    def test_validate_never_raises(self):
        class Boom(dict):
            def __getitem__(self, k):
                raise RuntimeError("boom")
        for bad in (Boom(), object(), None):
            self.assertFalse(validate(bad)["valid"])


class SafetyTests(unittest.TestCase):
    def test_module_imports_and_calls_are_safe(self):
        path = os.path.join(ROOT, "capabilities", "capability_evolution_analysis.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = set()
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0] if node.level == 0
                             else "." + (node.module or ""))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                calls.add(node.func.id)
        self.assertEqual(imported, {"copy", ".capability_evolution_request",
                                    ".capability_registry"})
        for banned in ("open", "exec", "eval", "compile", "__import__"):
            self.assertNotIn(banned, calls)

    def test_registry_not_touched(self):
        from capabilities.capability_registry import CapabilityRegistry
        registry = CapabilityRegistry()
        before = registry.__dict__.copy() if hasattr(registry, "__dict__") else None
        analyze(req(), [desc()])
        if before is not None:
            self.assertEqual(registry.__dict__, before)


if __name__ == "__main__":
    unittest.main()
