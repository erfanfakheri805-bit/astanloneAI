"""
Tests for Prompt 559 - Section 2 Language Intelligence Architecture Audit.

Minimal, focused structural test only - mirrors the same checks used for
the Prompt 557 Section 1 audit (tests/test_section1_architecture_
capability_audit.py). Does not re-derive the audit's findings from the
source tree (that inspection was done manually for Prompt 559, per this
prompt's audit-only, read-only scope); only checks that the audit's own
output is well-formed, deterministic, and free of forbidden
score/rank/"best"/"worst" language.

Run directly:
    python -m unittest tests.test_section2_language_intelligence_audit -v
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diagnostics.section2_language_intelligence_audit import (
    build_section2_language_intelligence_audit,
    IMPLEMENTED_AND_CORE_INTEGRATED,
    BEHAVIOR_CHANGING,
    RECORDS_OR_VALIDATES_ONLY,
    STRUCTURAL_NOT_INTEGRATED,
)

REQUIRED_TOP_LEVEL_KEYS = {
    "total_language_intelligence_files_inspected",
    "implemented_and_core_integrated",
    "implemented_but_not_core_integrated",
    "partially_implemented",
    "diagnostic_or_test_only",
    "integration_gaps",
    "important_missing_capabilities",
    "redundant_or_overlapping_components",
    "section_2_completion_candidates",
    "request_processing_path",
    "smallest_safe_integration_point",
    "recommended_next_implementation_target_prompt_560",
}

ENTRY_LIST_KEYS = (
    "implemented_and_core_integrated",
    "implemented_but_not_core_integrated",
    "partially_implemented",
    "diagnostic_or_test_only",
    "integration_gaps",
    "important_missing_capabilities",
    "redundant_or_overlapping_components",
)

FORBIDDEN_WORDS = ("best", "worst", "score", "rank")


class Section2LanguageIntelligenceAuditStructureTests(unittest.TestCase):

    def setUp(self):
        self.audit = build_section2_language_intelligence_audit()

    def test_returns_all_required_top_level_keys(self):
        self.assertEqual(set(self.audit.keys()), REQUIRED_TOP_LEVEL_KEYS)

    def test_deterministic_across_calls(self):
        second = build_section2_language_intelligence_audit()
        self.assertEqual(self.audit, second)

    def test_returned_structure_is_not_the_module_level_constant(self):
        self.audit["implemented_and_core_integrated"].append({"name": "x"})
        fresh = build_section2_language_intelligence_audit()
        self.assertEqual(len(fresh["implemented_and_core_integrated"]),
                          len(IMPLEMENTED_AND_CORE_INTEGRATED))

    def test_every_entry_has_name_kind_and_evidence(self):
        for key in ENTRY_LIST_KEYS:
            for entry in self.audit[key]:
                self.assertIn("name", entry, key)
                self.assertIn("kind", entry, key)
                self.assertIn("evidence", entry, key)
                self.assertTrue(entry["name"])
                self.assertTrue(entry["evidence"])

    def test_every_entry_kind_is_one_of_the_three_defined_categories(self):
        valid = {BEHAVIOR_CHANGING, RECORDS_OR_VALIDATES_ONLY, STRUCTURAL_NOT_INTEGRATED}
        for key in ENTRY_LIST_KEYS:
            for entry in self.audit[key]:
                self.assertIn(entry["kind"], valid, (key, entry["name"]))

    def test_no_scores_ranks_or_best_worst_language(self):
        for key in ENTRY_LIST_KEYS:
            for entry in self.audit[key]:
                haystack = (entry["name"] + " " + entry["evidence"]).lower()
                for word in FORBIDDEN_WORDS:
                    self.assertNotIn(word, haystack,
                                      "%s entry %r contains forbidden word %r"
                                      % (key, entry["name"], word))

    def test_capability_names_are_unique_within_each_category(self):
        for key in ENTRY_LIST_KEYS:
            names = [e["name"] for e in self.audit[key]]
            self.assertEqual(len(names), len(set(names)), key)

    def test_request_processing_path_is_a_nonempty_ordered_list_of_strings(self):
        path = self.audit["request_processing_path"]
        self.assertTrue(path)
        for step in path:
            self.assertIsInstance(step, str)
            self.assertTrue(step.strip())

    def test_total_files_inspected_is_a_positive_int(self):
        total = self.audit["total_language_intelligence_files_inspected"]
        self.assertIsInstance(total, int)
        self.assertGreater(total, 0)

    def test_building_the_audit_does_not_import_core(self):
        import diagnostics.section2_language_intelligence_audit as mod
        with open(mod.__file__, "r") as fh:
            source = fh.read()
        for forbidden_import in ("import core.core", "from core.core", "from core import core"):
            self.assertNotIn(forbidden_import, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
