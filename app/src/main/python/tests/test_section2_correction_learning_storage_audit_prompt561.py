"""
Tests for Prompt 561 - Section 2 Correction-Learning Storage/Retrieval
Architecture Audit.

Minimal, focused structural test only - mirrors the same checks used
for the Prompt 559 Section 2 audit
(tests/test_section2_language_intelligence_audit.py). Does not
re-derive the audit's findings from the source tree (that inspection
was done manually for Prompt 561, per this prompt's audit-only,
read-only scope); only checks that the audit's own output is
well-formed, deterministic, and free of forbidden score/rank/
"best"/"worst" language.

Run directly:
    python -m unittest tests.test_section2_correction_learning_storage_audit_prompt561 -v
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diagnostics.section2_correction_learning_storage_audit_prompt561 import (
    build_correction_learning_storage_audit,
    IMPLEMENTED_AND_WORKING,
    IMPLEMENTED_BUT_NOT_INTEGRATED,
    PARTIALLY_IMPLEMENTED,
    MISSING,
    DUPLICATE_OR_OVERLAPPING,
    INTEGRATION_GAP,
)

REQUIRED_TOP_LEVEL_KEYS = {
    "total_files_inspected",
    "files_inspected",
    "implemented_and_working",
    "implemented_but_not_integrated",
    "partially_implemented",
    "missing",
    "duplicate_or_overlapping",
    "integration_gaps",
    "request_lifecycle_trace",
    "can_existing_storage_safely_support_this_without_duplication",
    "smallest_implementation_target_prompt_562",
}

ENTRY_LIST_KEYS = (
    "implemented_and_working",
    "implemented_but_not_integrated",
    "partially_implemented",
    "missing",
    "duplicate_or_overlapping",
    "integration_gaps",
)

FORBIDDEN_WORDS = ("best", "worst", "score", "rank")


class Section2CorrectionLearningStorageAuditStructureTests(unittest.TestCase):

    def setUp(self):
        self.audit = build_correction_learning_storage_audit()

    def test_returns_all_required_top_level_keys(self):
        self.assertEqual(set(self.audit.keys()), REQUIRED_TOP_LEVEL_KEYS)

    def test_deterministic_across_calls(self):
        second = build_correction_learning_storage_audit()
        self.assertEqual(self.audit, second)

    def test_returned_structure_is_not_the_module_level_constant(self):
        self.audit["implemented_and_working"].append({"name": "x"})
        fresh = build_correction_learning_storage_audit()
        import diagnostics.section2_correction_learning_storage_audit_prompt561 as mod
        self.assertEqual(len(fresh["implemented_and_working"]),
                          len(mod.IMPLEMENTED_AND_WORKING_FINDINGS))

    def test_every_entry_has_name_kind_and_evidence(self):
        for key in ENTRY_LIST_KEYS:
            for entry in self.audit[key]:
                self.assertIn("name", entry, key)
                self.assertIn("kind", entry, key)
                self.assertIn("evidence", entry, key)
                self.assertTrue(entry["name"])
                self.assertTrue(entry["evidence"])

    def test_every_entry_kind_is_one_of_the_six_defined_categories(self):
        valid = {
            IMPLEMENTED_AND_WORKING,
            IMPLEMENTED_BUT_NOT_INTEGRATED,
            PARTIALLY_IMPLEMENTED,
            MISSING,
            DUPLICATE_OR_OVERLAPPING,
            INTEGRATION_GAP,
        }
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

    def test_entry_names_are_unique_within_each_category(self):
        for key in ENTRY_LIST_KEYS:
            names = [e["name"] for e in self.audit[key]]
            self.assertEqual(len(names), len(set(names)), key)

    def test_files_inspected_is_nonempty_and_matches_total(self):
        files = self.audit["files_inspected"]
        self.assertTrue(files)
        self.assertEqual(len(files), self.audit["total_files_inspected"])
        for f in files:
            self.assertIsInstance(f, str)
            self.assertTrue(f.strip())

    def test_request_lifecycle_trace_is_a_nonempty_ordered_list_of_strings(self):
        trace = self.audit["request_lifecycle_trace"]
        self.assertTrue(trace)
        for step in trace:
            self.assertIsInstance(step, str)
            self.assertTrue(step.strip())

    def test_lifecycle_trace_starts_with_the_user_correction_trigger(self):
        self.assertEqual(
            self.audit["request_lifecycle_trace"][0], "USER CORRECTS SOMETHING"
        )

    def test_narrative_fields_are_nonblank_strings(self):
        for key in (
            "can_existing_storage_safely_support_this_without_duplication",
            "smallest_implementation_target_prompt_562",
        ):
            self.assertIsInstance(self.audit[key], str)
            self.assertTrue(self.audit[key].strip())

    def test_at_least_one_finding_in_each_of_the_six_categories(self):
        # Prompt 561 asks the audit to categorize into all six buckets;
        # an empty category is a valid real finding (e.g. "missing" may
        # turn out to be small), but every category must at least be
        # considered/populated by this specific audit.
        for key in ENTRY_LIST_KEYS:
            self.assertTrue(len(self.audit[key]) >= 1, key)

    def test_building_the_audit_does_not_import_core(self):
        import diagnostics.section2_correction_learning_storage_audit_prompt561 as mod
        with open(mod.__file__, "r") as fh:
            source = fh.read()
        for forbidden_import in ("import core.core", "from core.core", "from core import core"):
            self.assertNotIn(forbidden_import, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
