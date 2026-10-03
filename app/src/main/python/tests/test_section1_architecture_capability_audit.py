"""
Tests for Prompt 557 - Section 1 Architecture Capability Audit.

build_section1_architecture_capability_audit() returns a fixed, factual
snapshot of what this audit found in the project's source structure. It
performs no I/O and mutates no project state.

This test only checks that the audit's own output is well-formed,
deterministic, and free of the things the audit was explicitly told not
to produce (scores, rankings, "best"/"worst" labels). It does not
re-derive the audit's findings from the source tree - that inspection was
done manually for Prompt 557, per the prompt's instruction that the audit
itself must remain read-only.

Run directly:
    python -m unittest tests.test_section1_architecture_capability_audit -v
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diagnostics.section1_architecture_capability_audit import (
    build_section1_architecture_capability_audit,
    IMPLEMENTED_CORE_CAPABILITIES,
    PARTIALLY_IMPLEMENTED_CAPABILITIES,
    DIAGNOSTIC_ONLY_CAPABILITIES,
    INTEGRATION_GAPS,
    IMPORTANT_MISSING_FOUNDATION_CAPABILITIES,
    REDUNDANT_OR_EXCESSIVELY_NESTED_DIAGNOSTIC_LAYERS,
    SECTION_1_COMPLETION_CANDIDATES,
    BEHAVIOR_CHANGING,
    RECORDS_OR_VALIDATES_ONLY,
    STRUCTURAL_NOT_INTEGRATED,
)

REQUIRED_TOP_LEVEL_KEYS = {
    "implemented_core_capabilities",
    "partially_implemented_capabilities",
    "diagnostic_only_capabilities",
    "integration_gaps",
    "important_missing_foundation_capabilities",
    "redundant_or_excessively_nested_diagnostic_layers",
    "section_1_completion_candidates",
    "section_1_ready_for_section_2",
    "section_1_readiness_notes",
}

ENTRY_LIST_KEYS = (
    "implemented_core_capabilities",
    "partially_implemented_capabilities",
    "diagnostic_only_capabilities",
    "integration_gaps",
    "important_missing_foundation_capabilities",
    "redundant_or_excessively_nested_diagnostic_layers",
)

FORBIDDEN_WORDS = ("best", "worst", "score", "rank", "recommend", "should")


class Section1ArchitectureAuditStructureTests(unittest.TestCase):

    def setUp(self):
        self.audit = build_section1_architecture_capability_audit()

    def test_returns_all_required_top_level_keys(self):
        self.assertEqual(set(self.audit.keys()), REQUIRED_TOP_LEVEL_KEYS)

    def test_deterministic_across_calls(self):
        second = build_section1_architecture_capability_audit()
        self.assertEqual(self.audit, second)

    def test_returned_structure_is_not_the_module_level_constant(self):
        # Mutating the returned dict/lists must never affect the module's
        # own record of the audit.
        self.audit["implemented_core_capabilities"].append({"name": "x"})
        self.audit["implemented_core_capabilities"][0]["kind"] = "mutated"
        fresh = build_section1_architecture_capability_audit()
        self.assertNotEqual(fresh["implemented_core_capabilities"],
                             self.audit["implemented_core_capabilities"])
        self.assertEqual(len(fresh["implemented_core_capabilities"]),
                          len(IMPLEMENTED_CORE_CAPABILITIES))

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

    def test_no_scores_ranks_or_best_worst_language_in_entry_names_or_evidence(self):
        for key in ENTRY_LIST_KEYS:
            for entry in self.audit[key]:
                haystack = (entry["name"] + " " + entry["evidence"]).lower()
                for word in FORBIDDEN_WORDS:
                    self.assertNotIn(word, haystack,
                                      "%s entry %r contains forbidden word %r"
                                      % (key, entry["name"], word))

    def test_completion_candidates_are_nonempty_strings_not_a_ranked_list(self):
        candidates = self.audit["section_1_completion_candidates"]
        self.assertTrue(candidates)
        for item in candidates:
            self.assertIsInstance(item, str)
            self.assertTrue(item.strip())

    def test_readiness_flag_is_boolean(self):
        self.assertIsInstance(self.audit["section_1_ready_for_section_2"], bool)

    def test_diagnostic_only_capabilities_are_never_listed_as_behavior_changing(self):
        for entry in self.audit["diagnostic_only_capabilities"]:
            self.assertNotEqual(entry["kind"], BEHAVIOR_CHANGING, entry["name"])

    def test_capability_names_are_unique_within_each_category(self):
        for key in ENTRY_LIST_KEYS:
            names = [e["name"] for e in self.audit[key]]
            self.assertEqual(len(names), len(set(names)), key)

    def test_building_the_audit_does_not_touch_other_subsystems(self):
        # The audit module must not import Core or any behavior-affecting
        # subsystem; it is a static data snapshot only.
        import diagnostics.section1_architecture_capability_audit as mod
        source_path = mod.__file__
        with open(source_path, "r") as fh:
            source = fh.read()
        for forbidden_import in ("import core.core", "from core.core", "from core import core"):
            self.assertNotIn(forbidden_import, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
