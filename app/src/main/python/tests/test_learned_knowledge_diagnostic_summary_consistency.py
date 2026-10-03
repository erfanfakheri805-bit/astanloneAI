"""
Tests for Prompt 532 - Validate Diagnostic Summary Consistency.

`validate_learned_knowledge_diagnostic_report()` (Prompt 514,
learning/learned_knowledge_statistics.py) already verifies the Unified
Diagnostic Report (Prompt 513) against every source in the existing
pipeline - snapshots, comparisons, trend summaries, the filtered trend,
selected-section metadata, and per-snapshot validation states. This
prompt adds two more, fully optional, independent sources: the
human-readable diagnostic summary (`format_learned_knowledge_diagnostic_
summary()`, Prompt 515) and the section-filtered summary built from it
(`filter_learned_knowledge_diagnostic_summary()`, Prompt 516).

Nothing here is a second summary system. The validator recomputes the
"expected" summary/filtered summary by calling the existing, unmodified
Prompt 515/516 functions themselves - on the same report and this same
validator's own structural/source verdict of it - purely to compare
against what the caller handed in. Neither `report` nor the given
summary/filtered summary is ever mutated, repaired or regenerated in
place; no new metric or analysis is computed.

Covers:
    1.  valid report and matching summary
    2.  invalid report with invalid summary state
    3.  summary incorrectly marked valid
    4.  missing sections
    5.  unavailable sections
    6.  filtered diagnostic sections
    7.  empty/zero-data report

Run directly:
    python -m unittest tests.test_learned_knowledge_diagnostic_summary_consistency -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_gate import (
    STATUS_PASSED, REASON_OK,
    LearnedKnowledgeGateResult, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
)

OK = {"valid": True, "well_formed": True, "errors": [], "warnings": []}


def _gtrace():
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(STATUS_PASSED, REASON_OK))


def _stats(accepted=0):
    stats = LearnedKnowledgeDecisionStatistics()
    for _ in range(accepted):
        stats.record(_gtrace())
    return stats


def _history(counts):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for n in counts:
        history.record_statistics(_stats(n))
    return history


def _full_pipeline(counts=(1, 2, 4)):
    """Real snapshots, their ordered comparisons, the report built from
    them, its own real Prompt 514 validation, and the real Prompt 515
    summary built from that - i.e. exactly what a real caller would
    produce end to end."""
    history = _history(counts)
    comparisons = [history.compare_sequences(i, i + 1) for i in range(1, len(counts))]
    built = report(snapshots=history, comparisons=comparisons)
    validation = validate(built, snapshots=history, comparisons=comparisons)
    summary = fmt(built, validation)
    return history, comparisons, built, validation, summary


class Prompt532TestCase(unittest.TestCase):
    def assert_consistent(self, built, **kwargs):
        result = validate(built, **kwargs)
        self.assertEqual(result, OK, result)

    def assert_summary_adds_no_errors(self, built, baseline, **kwargs):
        """The summary/filtered_summary check itself contributes nothing
        beyond whatever `baseline` (the same call without them) already
        reported - i.e. the given summary faithfully, consistently
        reflects an already-broken report."""
        result = validate(built, **kwargs)
        self.assertEqual(result["errors"], baseline["errors"], result)
        self.assertEqual(result["well_formed"], baseline["well_formed"], result)

    def assert_inconsistent(self, built, *expected_error_prefixes, **kwargs):
        result = validate(built, **kwargs)
        self.assertFalse(result["valid"], result)
        for prefix in expected_error_prefixes:
            self.assertTrue(
                any(error.startswith(prefix) for error in result["errors"]),
                "expected an error starting with %r in %r" % (prefix, result["errors"]))


# ----------------------------------------------------------------------
# 1. valid report and matching summary
# ----------------------------------------------------------------------
class ValidReportMatchingSummaryTests(Prompt532TestCase):

    def test_real_summary_of_a_valid_report_is_consistent(self):
        _, _, built, _, summary = _full_pipeline()
        self.assertEqual(summary["report_validity"], "valid")
        self.assert_consistent(built, summary=summary)

    def test_matching_summary_alongside_the_original_sources_is_consistent(self):
        history, comparisons, built, _, summary = _full_pipeline()
        self.assert_consistent(built, snapshots=history, comparisons=comparisons, summary=summary)

    def test_deep_copied_summary_still_matches(self):
        _, _, built, _, summary = _full_pipeline()
        self.assert_consistent(built, summary=copy.deepcopy(summary))

    def test_neither_summary_nor_filtered_summary_given_is_unaffected(self):
        _, _, built, _, _ = _full_pipeline()
        self.assert_consistent(built)


# ----------------------------------------------------------------------
# 2. invalid report with invalid summary state
# ----------------------------------------------------------------------
class InvalidReportInvalidSummaryTests(Prompt532TestCase):

    def _broken_report(self):
        _, _, built, _, _ = _full_pipeline()
        broken = copy.deepcopy(built)
        broken["trend"]["available"] = "not_a_bool"
        return broken

    def test_faithful_invalid_summary_over_an_invalid_report_is_consistent(self):
        broken = self._broken_report()
        validation = validate(broken)
        self.assertFalse(validation["valid"])
        summary = fmt(broken, validation)
        self.assertEqual(summary["report_validity"], "invalid")
        self.assert_summary_adds_no_errors(broken, validation, summary=summary)

    def test_invalid_summarys_errors_are_carried_through_unchanged(self):
        broken = self._broken_report()
        validation = validate(broken)
        summary = fmt(broken, validation)
        self.assertEqual(summary["validation_errors"], validation["errors"])
        self.assert_summary_adds_no_errors(broken, validation, summary=summary)

    def test_invalid_summary_over_a_report_that_is_otherwise_untouched(self):
        # A report that is well-formed but not fully valid against a given
        # source (a "source_mismatch") also produces an invalid summary
        # that must stay invalid to be consistent.
        history, comparisons, built, _, _ = _full_pipeline()
        tampered = copy.deepcopy(built)
        tampered["comparison"]["total_considered"] += 1
        validation = validate(tampered, comparisons=comparisons)
        self.assertFalse(validation["valid"])
        summary = fmt(tampered, validation)
        self.assertEqual(summary["report_validity"], "invalid")
        self.assert_summary_adds_no_errors(
            tampered, validation, comparisons=comparisons, summary=summary)


# ----------------------------------------------------------------------
# 3. summary incorrectly marked valid
# ----------------------------------------------------------------------
class SummaryIncorrectlyMarkedValidTests(Prompt532TestCase):

    def test_summary_claiming_valid_over_an_invalid_report_is_detected(self):
        _, _, built, _, _ = _full_pipeline()
        broken = copy.deepcopy(built)
        broken["trend"]["available"] = "not_a_bool"
        validation = validate(broken)
        fake = fmt(broken, validation)
        fake["report_validity"] = "valid"
        fake["validation_errors"] = []
        self.assert_inconsistent(broken, "claims_valid_but_source_invalid:summary", summary=fake)

    def test_summary_claiming_invalid_over_a_genuinely_valid_report_is_detected(self):
        _, _, built, _, summary = _full_pipeline()
        fake = copy.deepcopy(summary)
        fake["report_validity"] = "invalid"
        fake["validation_errors"] = ["fabricated"]
        self.assert_inconsistent(built, "claims_invalid_but_source_valid:summary", summary=fake)

    def test_unrecognized_report_validity_value_is_detected(self):
        _, _, built, _, summary = _full_pipeline()
        fake = copy.deepcopy(summary)
        fake["report_validity"] = "sort_of_valid"
        self.assert_inconsistent(built, "mismatched_validation_result:summary", summary=fake)

    def test_summary_not_a_dict_is_detected(self):
        _, _, built, _, _ = _full_pipeline()
        self.assert_inconsistent(built, "invalid_source:summary", summary=["not", "a", "dict"])

    def test_summary_is_never_mutated_by_the_check(self):
        _, _, built, _, summary = _full_pipeline()
        before = copy.deepcopy(summary)
        validate(built, summary=summary)
        self.assertEqual(summary, before)

    def test_report_is_never_mutated_by_the_check(self):
        _, _, built, _, summary = _full_pipeline()
        before = copy.deepcopy(built)
        validate(built, summary=summary)
        self.assertEqual(built, before)


# ----------------------------------------------------------------------
# 4. missing sections
# ----------------------------------------------------------------------
class MissingSectionsTests(Prompt532TestCase):

    def test_report_with_only_snapshots_has_a_consistent_summary(self):
        history = _history((1, 2, 3))
        built = report(snapshots=history)
        validation = validate(built, snapshots=history)
        summary = fmt(built, validation)
        self.assertIn("comparison_changes", summary["unavailable_sections"])
        self.assertIn("trend", summary["unavailable_sections"])
        self.assert_consistent(built, snapshots=history, summary=summary)

    def test_summary_fabricating_a_missing_section_is_detected(self):
        history = _history((1, 2, 3))
        built = report(snapshots=history)
        validation = validate(built, snapshots=history)
        summary = fmt(built, validation)
        tampered = copy.deepcopy(summary)
        tampered["available_sections"].append("trend")
        tampered["unavailable_sections"].remove("trend")
        tampered["metrics"]["trend"] = {"source": "provided"}
        self.assert_inconsistent(
            built, "source_mismatch:summary.available_sections", snapshots=history, summary=tampered)

    def test_summary_claiming_a_present_section_is_missing_is_detected(self):
        _, _, built, _, summary = _full_pipeline()
        tampered = copy.deepcopy(summary)
        tampered["available_sections"].remove("trend")
        tampered["unavailable_sections"].append("trend")
        tampered["metrics"]["trend"] = None
        self.assert_inconsistent(built, "source_mismatch:summary.unavailable_sections", summary=tampered)


# ----------------------------------------------------------------------
# 5. unavailable sections
# ----------------------------------------------------------------------
class UnavailableSectionsTests(Prompt532TestCase):

    def test_no_data_reports_unavailable_sections_stay_unavailable(self):
        built = report()
        validation = validate(built)
        summary = fmt(built, validation)
        self.assertEqual(summary["available_sections"], ["validation_statuses"])
        self.assert_consistent(built, summary=summary)

    def test_wrong_metrics_for_an_unavailable_section_is_detected(self):
        built = report()
        validation = validate(built)
        summary = fmt(built, validation)
        tampered = copy.deepcopy(summary)
        # Still correctly marked unavailable, but a value has been
        # fabricated for it anyway.
        tampered["metrics"]["rates"] = {"acceptance_rate": 1.0, "rejection_rate": 0.0}
        self.assert_inconsistent(built, "source_mismatch:summary.metrics", summary=tampered)

    def test_unavailable_state_is_not_flagged_as_an_error_by_itself(self):
        built = report()
        validation = validate(built)
        summary = fmt(built, validation)
        result = validate(built, summary=summary)
        self.assertEqual(result, OK, result)


# ----------------------------------------------------------------------
# 6. filtered diagnostic sections
# ----------------------------------------------------------------------
class FilteredDiagnosticSectionsTests(Prompt532TestCase):

    def test_matching_filtered_summary_is_consistent(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "trend"])
        self.assert_consistent(built, filtered_summary=filtered)

    def test_matching_summary_and_filtered_summary_together_are_consistent(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["evaluation_counts"])
        self.assert_consistent(built, summary=summary, filtered_summary=filtered)

    def test_filtered_summary_over_an_unrequested_section_stays_unavailable(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        self.assertEqual(filtered["included_sections"], ["rates"])
        self.assert_consistent(built, filtered_summary=filtered)

    def test_filtered_summary_over_no_data_report_is_consistent(self):
        built = report()
        validation = validate(built)
        summary = fmt(built, validation)
        filtered = filt(summary, ["validation_statuses", "trend"])
        self.assertEqual(filtered["included_sections"], ["validation_statuses"])
        self.assertEqual(filtered["unavailable_sections"], ["trend"])
        self.assert_consistent(built, filtered_summary=filtered)

    def test_tampered_included_section_is_detected(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        tampered = copy.deepcopy(filtered)
        tampered["metrics"]["rates"]["acceptance_rate"] = 0.0
        self.assert_inconsistent(built, "source_mismatch:filtered_summary.metrics", filtered_summary=tampered)

    def test_filtered_summary_validity_flip_is_detected(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        tampered = copy.deepcopy(filtered)
        tampered["report_validity"] = "invalid"
        tampered["included_sections"] = []
        tampered["validation_errors"] = ["fabricated"]
        self.assert_inconsistent(
            built, "claims_invalid_but_source_valid:filtered_summary", filtered_summary=tampered)

    def test_filtered_summary_not_a_dict_is_detected(self):
        _, _, built, _, _ = _full_pipeline()
        self.assert_inconsistent(built, "invalid_source:filtered_summary", filtered_summary=42)

    def test_filtered_summary_uses_its_own_requested_sections(self):
        # No separate "requested_sections" argument exists: the filtered
        # summary's own field is what is recomputed against.
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["trend", "validation_statuses"])
        self.assertEqual(filtered["requested_sections"], ["trend", "validation_statuses"])
        self.assert_consistent(built, filtered_summary=filtered)


# ----------------------------------------------------------------------
# 7. empty/zero-data report
# ----------------------------------------------------------------------
class EmptyZeroDataReportTests(Prompt532TestCase):

    def test_empty_report_summary_is_consistent(self):
        built = report()
        self.assertEqual(built["structural_status"], "no_data")
        validation = validate(built)
        summary = fmt(built, validation)
        self.assertEqual(summary["report_validity"], "valid")
        self.assert_consistent(built, summary=summary)

    def test_zero_evaluation_snapshot_summary_is_consistent(self):
        history = _history((0,))
        built = report(snapshots=history)
        validation = validate(built, snapshots=history)
        summary = fmt(built, validation)
        self.assertEqual(summary["metrics"]["evaluation_counts"]["total_evaluations"], 0)
        self.assert_consistent(built, snapshots=history, summary=summary)

    def test_empty_report_filtered_summary_is_consistent(self):
        built = report()
        validation = validate(built)
        summary = fmt(built, validation)
        filtered = filt(summary, [])
        self.assertEqual(filtered["included_sections"], [])
        self.assert_consistent(built, filtered_summary=filtered)

    def test_empty_report_wrong_validation_statuses_metric_is_detected(self):
        built = report()
        validation = validate(built)
        summary = fmt(built, validation)
        tampered = copy.deepcopy(summary)
        tampered["metrics"]["validation_statuses"]["structural_status"] = "valid"
        self.assert_inconsistent(built, "source_mismatch:summary.metrics", summary=tampered)


if __name__ == "__main__":
    unittest.main()
