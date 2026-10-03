"""
Tests for Prompt 534 - Validate Filtered Snapshot and Summary Consistency.

`validate_learned_knowledge_diagnostic_report()` (Prompt 514,
learning/learned_knowledge_statistics.py) can now also be handed a Prompt
517 filtered-summary snapshot (`filtered_snapshot=`) together with the
Prompt 516 filtered summary (`filtered_summary=`) it was recorded from,
and verifies the two still agree.

Nothing here is a second snapshot/summary system: the value the snapshot
should be is obtained from the existing, unmodified
`_build_filtered_summary_snapshot()` (the builder
`LearnedKnowledgeFilteredSummarySnapshotHistory.record_filtered_summary()`
uses), and compared with the same machinery every other source
cross-check in this validator uses. Neither input is modified or
repaired.

Covers:
    1.  a matching snapshot and summary
    2.  a missing section (either side)
    3.  an unavailable section (kept unavailable, never conflated with missing)
    4.  an unknown section
    5.  a mismatched section value
    6.  a filtered trend mismatch
    7.  an empty filtered snapshot / summary
    8.  scope, determinism and non-mutation

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_snapshot_summary_consistency -v
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
    LearnedKnowledgeFilteredSummarySnapshotHistory,
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
    """Real snapshots, comparisons, report, validation and Prompt 515
    summary - exactly what a real caller would produce end to end."""
    history = _history(counts)
    comparisons = [history.compare_sequences(i, i + 1) for i in range(1, len(counts))]
    built = report(snapshots=history, comparisons=comparisons)
    validation = validate(built, snapshots=history, comparisons=comparisons)
    return built, fmt(built, validation)


def _partial_pipeline():
    """A report with snapshots only: `comparison_changes` and `trend`
    are genuinely unavailable in its summary."""
    history = _history((1, 2, 3))
    built = report(snapshots=history)
    return built, fmt(built, validate(built, snapshots=history))


def _record(filtered):
    return LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)


class Prompt534TestCase(unittest.TestCase):
    def assert_consistent(self, built, snapshot, filtered):
        result = validate(built, filtered_snapshot=snapshot, filtered_summary=filtered)
        self.assertEqual(result, OK, result)

    def assert_inconsistent(self, built, snapshot, filtered, *expected_error_prefixes):
        result = validate(built, filtered_snapshot=snapshot, filtered_summary=filtered)
        self.assertFalse(result["valid"], result)
        for prefix in expected_error_prefixes:
            self.assertTrue(
                any(error.startswith(prefix) for error in result["errors"]),
                "expected an error starting with %r in %r" % (prefix, result["errors"]))
        return result


# ----------------------------------------------------------------------
# 1. a matching snapshot and summary
# ----------------------------------------------------------------------
class MatchingSnapshotAndSummaryTests(Prompt534TestCase):

    def test_snapshot_recorded_from_the_filtered_summary_is_consistent(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["evaluation_counts", "rates", "trend"])
        self.assert_consistent(built, _record(filtered), filtered)

    def test_every_available_section_matches(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, summary["available_sections"])
        snapshot = _record(filtered)
        self.assertEqual(snapshot["included_sections"], filtered["included_sections"])
        self.assert_consistent(built, snapshot, filtered)

    def test_deep_copies_of_both_still_match(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "comparison_changes"])
        self.assert_consistent(built, copy.deepcopy(_record(filtered)), copy.deepcopy(filtered))

    def test_snapshot_sequence_and_id_do_not_matter(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        history.record_filtered_summary(filt(summary, ["trend"]))
        later = history.record_filtered_summary(filtered)
        self.assertEqual(later["sequence"], 2)
        self.assert_consistent(built, later, filtered)

    def test_unknown_names_are_counted_not_stored_and_still_match(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "not_a_section", "also_unknown"])
        snapshot = _record(filtered)
        self.assertEqual(snapshot["unknown_section_count"], 2)
        self.assert_consistent(built, snapshot, filtered)


# ----------------------------------------------------------------------
# 2. a missing section
# ----------------------------------------------------------------------
class MissingSectionTests(Prompt534TestCase):

    def test_section_available_in_summary_but_missing_from_snapshot(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "trend"])
        snapshot = _record(filtered)
        snapshot["included_sections"].remove("rates")
        del snapshot["metrics"]["rates"]
        self.assert_inconsistent(
            built, snapshot, filtered,
            "filtered_summary_section_not_available_in_snapshot:rates")

    def test_section_in_snapshot_but_not_in_summary_at_all(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        snapshot = _record(filtered)
        snapshot["included_sections"].append("trend")
        snapshot["metrics"]["trend"] = {"source": "fabricated"}
        self.assert_inconsistent(
            built, snapshot, filtered,
            "filtered_snapshot_section_not_available_in_summary:trend")

    def test_snapshot_claiming_available_a_section_the_source_summary_lacks(self):
        built, summary = _partial_pipeline()
        filtered = filt(summary, ["evaluation_counts", "trend"])
        self.assertEqual(filtered["unavailable_sections"], ["trend"])
        snapshot = _record(filtered)
        snapshot["unavailable_sections"].remove("trend")
        snapshot["included_sections"].append("trend")
        snapshot["metrics"]["trend"] = {"source": "fabricated"}
        self.assert_inconsistent(
            built, snapshot, filtered,
            "filtered_snapshot_section_not_available_in_summary:trend")

    def test_missing_metrics_entry_for_an_included_section(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        snapshot = _record(filtered)
        del snapshot["metrics"]["rates"]
        self.assert_inconsistent(
            built, snapshot, filtered, "source_mismatch:filtered_snapshot_summary.metrics.rates")


# ----------------------------------------------------------------------
# 3. an unavailable section
# ----------------------------------------------------------------------
class UnavailableSectionTests(Prompt534TestCase):

    def test_genuinely_unavailable_section_is_consistent(self):
        built, summary = _partial_pipeline()
        filtered = filt(summary, ["evaluation_counts", "comparison_changes", "trend"])
        snapshot = _record(filtered)
        self.assertEqual(snapshot["unavailable_sections"], ["comparison_changes", "trend"])
        self.assertIsNone(snapshot["metrics"]["trend"])
        self.assert_consistent(built, snapshot, filtered)

    def test_unavailable_section_promoted_to_included_in_summary_only(self):
        built, summary = _partial_pipeline()
        filtered = filt(summary, ["trend"])
        snapshot = _record(filtered)
        promoted = copy.deepcopy(filtered)
        promoted["unavailable_sections"].remove("trend")
        promoted["included_sections"].append("trend")
        promoted["metrics"]["trend"] = {"source": "fabricated"}
        self.assert_inconsistent(
            built, snapshot, promoted,
            "filtered_summary_section_not_available_in_snapshot:trend")

    def test_unavailable_versus_missing_is_never_conflated(self):
        built, summary = _partial_pipeline()
        filtered = filt(summary, ["evaluation_counts", "trend"])
        snapshot = _record(filtered)
        snapshot["unavailable_sections"].remove("trend")
        del snapshot["metrics"]["trend"]
        self.assert_inconsistent(
            built, snapshot, filtered, "filtered_snapshot_section_state_mismatch:trend")

    def test_unavailable_section_with_a_value_is_detected(self):
        built, summary = _partial_pipeline()
        filtered = filt(summary, ["trend"])
        snapshot = _record(filtered)
        snapshot["metrics"]["trend"] = {"source": "fabricated"}
        self.assert_inconsistent(
            built, snapshot, filtered, "source_mismatch:filtered_snapshot_summary.metrics.trend")

    def test_invalid_filtered_summary_stays_invalid_in_its_snapshot(self):
        built, summary = _full_pipeline()
        invalid_summary = copy.deepcopy(summary)
        invalid_summary["report_validity"] = "invalid"
        invalid_summary["validation_errors"] = ["some_source_error"]
        filtered = filt(invalid_summary, ["rates"])
        self.assertEqual(filtered["report_validity"], "invalid")
        snapshot = _record(filtered)
        self.assertEqual(snapshot["unavailable_sections"], ["rates"])
        result = validate(built, filtered_snapshot=snapshot, filtered_summary=filtered)
        self.assertFalse(any(error.startswith(("filtered_snapshot", "filtered_summary_section",
                                               "source_mismatch:filtered_snapshot_summary"))
                             for error in result["errors"]), result["errors"])

    def test_snapshot_claiming_valid_over_an_invalid_filtered_summary(self):
        built, summary = _full_pipeline()
        invalid_summary = copy.deepcopy(summary)
        invalid_summary["report_validity"] = "invalid"
        invalid_summary["validation_errors"] = ["some_source_error"]
        filtered = filt(invalid_summary, ["rates"])
        snapshot = _record(filtered)
        snapshot["validation_status"] = "valid"
        snapshot["validation_errors"] = []
        self.assert_inconsistent(
            built, snapshot, filtered,
            "claims_valid_but_source_invalid:filtered_snapshot_summary",
            "source_mismatch:filtered_snapshot_summary.validation_errors")


# ----------------------------------------------------------------------
# 4. an unknown section
# ----------------------------------------------------------------------
class UnknownSectionTests(Prompt534TestCase):

    def test_unknown_name_marked_included_in_snapshot_is_detected(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "not_a_section"])
        snapshot = _record(filtered)
        snapshot["included_sections"].append("not_a_section")
        snapshot["metrics"]["not_a_section"] = {"x": 1}
        self.assert_inconsistent(
            built, snapshot, filtered, "filtered_snapshot_inconsistent:invalid_section_names")

    def test_unknown_name_marked_unavailable_in_snapshot_is_detected(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "not_a_section"])
        snapshot = _record(filtered)
        snapshot["unavailable_sections"].append("not_a_section")
        self.assert_inconsistent(
            built, snapshot, filtered, "filtered_snapshot_inconsistent:invalid_section_names")

    def test_unknown_section_count_mismatch_is_detected(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "not_a_section"])
        snapshot = _record(filtered)
        snapshot["unknown_section_count"] = 0
        self.assert_inconsistent(
            built, snapshot, filtered, "filtered_snapshot_unknown_section_count_mismatch")

    def test_unknown_name_promoted_to_a_real_section_in_summary_is_detected(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "not_a_section"])
        snapshot = _record(filtered)
        tampered = copy.deepcopy(filtered)
        tampered["unknown_sections"] = []
        tampered["unavailable_sections"].append("trend")
        tampered["metrics"]["trend"] = None
        self.assert_inconsistent(
            built, snapshot, tampered,
            "filtered_snapshot_section_state_mismatch:trend",
            "filtered_snapshot_unknown_section_count_mismatch")


# ----------------------------------------------------------------------
# 5. a mismatched section value
# ----------------------------------------------------------------------
class MismatchedValueTests(Prompt534TestCase):

    def test_changed_count_is_detected(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["evaluation_counts"])
        snapshot = _record(filtered)
        snapshot["metrics"]["evaluation_counts"]["accepted_count"] += 1
        self.assert_inconsistent(
            built, snapshot, filtered,
            "source_mismatch:filtered_snapshot_summary.metrics.evaluation_counts.accepted_count")

    def test_changed_rate_is_detected(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        snapshot = _record(filtered)
        snapshot["metrics"]["rates"]["acceptance_rate"] = 0.123
        self.assert_inconsistent(
            built, snapshot, filtered,
            "source_mismatch:filtered_snapshot_summary.metrics.rates.acceptance_rate")

    def test_changed_dominant_reason_is_detected(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["dominant_rejection_reason"])
        snapshot = _record(filtered)
        snapshot["metrics"]["dominant_rejection_reason"] = "made_up_reason"
        self.assert_inconsistent(
            built, snapshot, filtered,
            "source_mismatch:filtered_snapshot_summary.metrics.dominant_rejection_reason")

    def test_value_changed_in_the_summary_instead_is_detected(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["evaluation_counts"])
        snapshot = _record(filtered)
        drifted = copy.deepcopy(filtered)
        drifted["metrics"]["evaluation_counts"]["total_evaluations"] += 5
        self.assert_inconsistent(
            built, snapshot, drifted,
            "source_mismatch:filtered_snapshot_summary.metrics.evaluation_counts.total_evaluations")

    def test_only_the_mismatched_section_is_reported(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["evaluation_counts", "rates"])
        snapshot = _record(filtered)
        snapshot["metrics"]["rates"]["rejection_rate"] = 0.5
        result = self.assert_inconsistent(
            built, snapshot, filtered,
            "source_mismatch:filtered_snapshot_summary.metrics.rates")
        self.assertFalse(any("evaluation_counts" in error for error in result["errors"]),
                         result["errors"])


# ----------------------------------------------------------------------
# 6. a filtered trend mismatch
# ----------------------------------------------------------------------
class FilteredTrendMismatchTests(Prompt534TestCase):

    def test_matching_filtered_trend_is_consistent(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["trend"])
        self.assertEqual(filtered["included_sections"], ["trend"])
        self.assert_consistent(built, _record(filtered), filtered)

    def test_changed_trend_value_is_detected(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["trend"])
        snapshot = _record(filtered)
        snapshot["metrics"]["trend"]["source"] = "something_else"
        self.assert_inconsistent(
            built, snapshot, filtered,
            "source_mismatch:filtered_snapshot_summary.metrics.trend.source")

    def test_changed_trend_state_is_detected(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["trend"])
        snapshot = _record(filtered)
        self.assertIn("validation_status", snapshot["metrics"]["trend"])
        snapshot["metrics"]["trend"]["validation_status"] = "changed_state"
        self.assert_inconsistent(
            built, snapshot, filtered,
            "source_mismatch:filtered_snapshot_summary.metrics.trend.validation_status")

    def test_trend_dropped_from_the_snapshot_is_detected(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["trend", "rates"])
        snapshot = _record(filtered)
        snapshot["included_sections"].remove("trend")
        del snapshot["metrics"]["trend"]
        self.assert_inconsistent(
            built, snapshot, filtered,
            "filtered_summary_section_not_available_in_snapshot:trend")


# ----------------------------------------------------------------------
# 7. an empty filtered snapshot / summary
# ----------------------------------------------------------------------
class EmptyFilteredSnapshotAndSummaryTests(Prompt534TestCase):

    def test_empty_request_snapshot_and_summary_are_consistent(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, [])
        snapshot = _record(filtered)
        self.assertEqual(snapshot["included_sections"], [])
        self.assertEqual(snapshot["metrics"], {})
        self.assert_consistent(built, snapshot, filtered)

    def test_empty_snapshot_against_a_summary_with_sections_is_detected(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        empty_snapshot = _record(filt(summary, []))
        self.assert_inconsistent(
            built, empty_snapshot, filtered,
            "filtered_summary_section_not_available_in_snapshot:rates")

    def test_snapshot_with_sections_against_an_empty_summary_is_detected(self):
        built, summary = _full_pipeline()
        snapshot = _record(filt(summary, ["rates"]))
        empty = filt(summary, [])
        self.assert_inconsistent(
            built, snapshot, empty, "filtered_snapshot_section_not_available_in_summary:rates")

    def test_empty_dict_snapshot_is_structurally_reported(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, [])
        self.assert_inconsistent(
            built, {}, filtered, "filtered_snapshot_inconsistent:missing_field:snapshot_id")

    def test_snapshot_of_a_malformed_empty_summary_is_consistent_with_it(self):
        # A `{}` filtered summary is not a well-formed Prompt 516 result;
        # its snapshot is the existing invalid, section-less snapshot, and
        # the two agree with each other (the summary's own problems are
        # reported by the Prompt 532 checks, not duplicated here).
        built, _ = _full_pipeline()
        snapshot = _record({})
        self.assertEqual(snapshot["validation_status"], "invalid")
        result = validate(built, filtered_snapshot=snapshot, filtered_summary={})
        self.assertFalse(any("filtered_snapshot_summary" in error for error in result["errors"]),
                         result["errors"])


# ----------------------------------------------------------------------
# 8. scope, determinism and non-mutation
# ----------------------------------------------------------------------
class ScopeAndSafetyTests(Prompt534TestCase):

    def test_snapshot_alone_is_never_checked(self):
        built, summary = _full_pipeline()
        snapshot = _record(filt(summary, ["rates"]))
        snapshot["metrics"]["rates"]["acceptance_rate"] = 0.987
        self.assertEqual(validate(built, filtered_snapshot=snapshot), OK)

    def test_none_snapshot_is_a_missing_state_not_an_error(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        self.assertEqual(validate(built, filtered_snapshot=None, filtered_summary=filtered), OK)

    def test_non_dict_snapshot_is_an_invalid_source(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        self.assert_inconsistent(built, "not a snapshot", filtered, "invalid_source:filtered_snapshot")

    def test_existing_calls_without_a_snapshot_are_unchanged(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        self.assertEqual(validate(built), OK)
        self.assertEqual(validate(built, summary=summary, filtered_summary=filtered), OK)

    def test_results_are_deterministic(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "trend", "nope"])
        snapshot = _record(filtered)
        snapshot["metrics"]["trend"]["source"] = "x"
        first = validate(built, filtered_snapshot=snapshot, filtered_summary=filtered)
        second = validate(built, filtered_snapshot=snapshot, filtered_summary=filtered)
        self.assertEqual(first, second)

    def test_nothing_is_mutated_or_repaired(self):
        built, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "trend"])
        snapshot = _record(filtered)
        snapshot["metrics"]["rates"]["acceptance_rate"] = 0.42
        snapshot["included_sections"].append("comparison_changes")
        before = copy.deepcopy((built, summary, filtered, snapshot))
        result = validate(built, summary=summary, filtered_summary=filtered,
                          filtered_snapshot=snapshot)
        self.assertFalse(result["valid"])
        self.assertEqual((built, summary, filtered, snapshot), before)


if __name__ == "__main__":
    unittest.main()
