"""
Tests for Prompt 535 - Validate Filtered Comparison Sources.

`validate_learned_knowledge_filtered_summary_snapshot_comparison()` (Prompt
519, learning/learned_knowledge_statistics.py) already cross-checks a
Prompt 518 filtered comparison against the two Prompt 517 filtered
snapshots it names when they are handed in. Prompt 535 makes that check
hold the two SOURCE snapshots themselves to account:

  - the given `earlier` source must really be earlier than the `later`
    one (`reversed_source_snapshots` / `contradictory_source_ordering:..`);
  - a source whose own validation status is invalid can never back a
    comparison marked valid (`source_snapshot_validation_status_invalid`);
  - a comparison that names a snapshot which does not match the one the
    caller holds is a mismatch, not a missing snapshot, in the report-level
    check too (`filtered_comparison_source_inconsistent:...`);
  - missing / unavailable / invalid states are preserved, never guessed at.

Nothing here is a new comparison, snapshot, trend or validation system,
and no snapshot or comparison is ever modified or repaired.

Covers:
    1.  valid source snapshots
    2.  reversed source snapshots
    3.  invalid source snapshot
    4.  mismatched source snapshot
    5.  missing source snapshot
    6.  valid filtered comparison (filtered trend section included)
    7.  empty / zero-data comparison
    8.  scope, determinism and non-mutation

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_comparison_source_validation -v
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
    validate_learned_knowledge_diagnostic_report as validate_report,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
    compare_learned_knowledge_filtered_summary_snapshots as compare,
    validate_learned_knowledge_filtered_summary_snapshot_comparison as check,
)


def _gtrace():
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(STATUS_PASSED, REASON_OK))


def _stats(accepted=0):
    stats = LearnedKnowledgeDecisionStatistics()
    for _ in range(accepted):
        stats.record(_gtrace())
    return stats


def _summary(counts=(1, 2, 4)):
    """A real Prompt 515 summary (with a trend) built end to end."""
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for n in counts:
        history.record_statistics(_stats(n))
    comparisons = [history.compare_sequences(i, i + 1) for i in range(1, len(counts))]
    built = report(snapshots=history, comparisons=comparisons)
    return built, fmt(built, validate_report(built, snapshots=history, comparisons=comparisons))


def _snapshots(*requests, counts=(1, 2, 4)):
    """Real Prompt 517 snapshots, one per request list, recorded in order
    (sequence 1, 2, ...), from real Prompt 516 filtered summaries."""
    built, summary = _summary(counts)
    history = LearnedKnowledgeFilteredSummarySnapshotHistory()
    return built, summary, [history.record_filtered_summary(filt(summary, list(r))) for r in requests]


def _varied_snapshots(*requests, base=(1, 2, 4)):
    """Real Prompt 517 snapshots like `_snapshots()`, but each recorded from
    its own diagnostic history (the last count grows by one per snapshot),
    so every snapshot carries genuinely different values."""
    history = LearnedKnowledgeFilteredSummarySnapshotHistory()
    snapshots = []
    for index, request in enumerate(requests):
        _, summary = _summary(base[:-1] + (base[-1] + index,))
        snapshots.append(history.record_filtered_summary(filt(summary, list(request))))
    return snapshots


class Prompt535TestCase(unittest.TestCase):
    def assert_valid(self, result):
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["errors"], [])

    def assert_has(self, result, code, kind="errors"):
        self.assertIn(code, result[kind], result)
        self.assertFalse(result["valid"], result)


# ----------------------------------------------------------------------
# 1. valid source snapshots
# ----------------------------------------------------------------------
class ValidSourceSnapshotsTests(Prompt535TestCase):

    def test_comparison_of_its_two_real_sources_is_valid(self):
        _, _, (first, second) = _snapshots(["evaluation_counts", "rates"], ["evaluation_counts", "rates"])
        self.assert_valid(check(compare(first, second), first, second))

    def test_sources_are_strictly_ordered_earlier_before_later(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        self.assertLess(first["sequence"], second["sequence"])
        result = check(compare(first, second), first, second)
        self.assert_valid(result)
        self.assertEqual(result["ordering_errors"], [])

    def test_non_adjacent_sources_are_still_correctly_ordered(self):
        _, _, (first, _, third) = _snapshots(["rates"], ["trend"], ["rates", "trend"])
        self.assert_valid(check(compare(first, third), first, third))

    def test_deep_copied_sources_are_equally_valid(self):
        _, _, (first, second) = _snapshots(["rates", "trend"], ["rates", "trend"])
        self.assert_valid(check(compare(first, second), copy.deepcopy(first), copy.deepcopy(second)))

    def test_report_level_check_accepts_faithful_filtered_comparisons(self):
        built, _, (first, second) = _snapshots(["rates", "trend"], ["rates"])
        result = validate_report(built, filtered_snapshots=[first, second],
                                 filtered_comparisons=[compare(first, second)])
        self.assertFalse(any(code.startswith("filtered_comparison_source_inconsistent")
                             for code in result["errors"]), result["errors"])


# ----------------------------------------------------------------------
# 2. reversed source snapshots
# ----------------------------------------------------------------------
class ReversedSourceSnapshotsTests(Prompt535TestCase):

    def test_sources_handed_in_the_wrong_roles_are_reported_as_reversed(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        result = check(compare(first, second), second, first)
        self.assert_has(result, "reversed_source_snapshots", "ordering_errors")
        self.assertIn("source_mismatch:earlier:identity", result["errors"])

    def test_a_faithfully_reversed_comparison_is_reported_once_as_reversed_ordering(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        reversed_comparison = compare(second, first)
        result = check(reversed_comparison, second, first)
        self.assertEqual(result["ordering_errors"], ["reversed_ordering"])
        self.assertTrue(result["well_formed"])

    def test_reversed_sources_with_a_forward_comparison_do_not_repair_either(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        comparison = compare(first, second)
        before = copy.deepcopy((comparison, first, second))
        check(comparison, second, first)
        self.assertEqual((comparison, first, second), before)

    def test_same_sequence_different_snapshot_is_contradictory(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        clone = copy.deepcopy(first)
        clone["snapshot_id"] = "another_snapshot"
        comparison = compare(first, clone)
        result = check(comparison, first, clone)
        self.assert_has(
            result, "contradictory_source_ordering:same_sequence_different_snapshot_id",
            "ordering_errors")

    def test_same_snapshot_id_different_sequence_is_contradictory(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        clone = copy.deepcopy(second)
        clone["snapshot_id"] = first["snapshot_id"]
        result = check(compare(first, clone), first, clone)
        self.assert_has(
            result, "contradictory_source_ordering:same_snapshot_id_different_sequence",
            "ordering_errors")

    def test_comparing_a_snapshot_with_itself_is_only_a_warning(self):
        _, _, (first, _) = _snapshots(["rates"], ["rates"])
        result = check(compare(first, first), first, first)
        self.assert_valid(result)
        self.assertEqual(result["warnings"], ["same_snapshot_compared"])


# ----------------------------------------------------------------------
# 3. invalid source snapshot
# ----------------------------------------------------------------------
class InvalidSourceSnapshotTests(Prompt535TestCase):

    def test_structurally_malformed_source_cannot_back_a_valid_comparison(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        comparison = compare(first, second)
        broken = copy.deepcopy(second)
        del broken["metrics"]
        result = check(comparison, first, broken)
        self.assert_has(result, "comparison_valid_but_source_invalid:later", "source_snapshot_errors")

    def test_source_with_invalid_status_cannot_back_a_valid_comparison(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        comparison = compare(first, second)
        invalid = copy.deepcopy(second)
        invalid.update({"validation_status": "invalid", "validation_errors": ["bad"],
                        "included_sections": [], "unavailable_sections": ["rates"],
                        "metrics": {"rates": None}})
        result = check(comparison, first, invalid)
        self.assert_has(result, "source_snapshot_validation_status_invalid:later",
                        "source_snapshot_errors")
        self.assertIn("source_mismatch:later:validation_status", result["errors"])

    def test_honestly_invalid_source_is_preserved_but_never_a_valid_comparison(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        invalid = copy.deepcopy(second)
        invalid.update({"validation_status": "invalid", "validation_errors": ["bad"],
                        "included_sections": [], "unavailable_sections": ["rates"],
                        "metrics": {"rates": None}})
        comparison = compare(first, invalid)
        self.assertEqual(comparison["later_validation_status"], "invalid")
        self.assertEqual(comparison["sections"]["rates"]["presence"], "present_only_earlier")
        result = check(comparison, first, invalid)
        self.assertEqual(result["source_snapshot_errors"],
                         ["source_snapshot_validation_status_invalid:later"])
        self.assertTrue(result["well_formed"])

    def test_invalid_source_status_is_flagged_even_if_the_comparison_omits_it(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        invalid = copy.deepcopy(second)
        invalid.update({"validation_status": "invalid", "validation_errors": ["bad"],
                        "included_sections": [], "unavailable_sections": ["rates"],
                        "metrics": {"rates": None}})
        comparison = compare(first, invalid)
        comparison["later_validation_status"] = "valid"  # a lying comparison
        result = check(comparison, first, invalid)
        self.assert_has(result, "source_snapshot_validation_status_invalid:later",
                        "source_snapshot_errors")

    def test_both_sources_invalid_are_each_reported(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        bad_first, bad_second = copy.deepcopy(first), copy.deepcopy(second)
        for snap in (bad_first, bad_second):
            snap.update({"validation_status": "invalid", "validation_errors": ["bad"],
                         "included_sections": [], "unavailable_sections": ["rates"],
                         "metrics": {"rates": None}})
        result = check(compare(bad_first, bad_second), bad_first, bad_second)
        self.assertEqual(result["source_snapshot_errors"], [
            "source_snapshot_validation_status_invalid:earlier",
            "source_snapshot_validation_status_invalid:later"])

    def test_invalid_comparison_of_malformed_sources_stays_invalid_and_consistent(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        malformed = copy.deepcopy(second)
        del malformed["metrics"]
        comparison = compare(first, malformed)
        self.assertFalse(comparison["valid"])
        result = check(comparison, first, malformed)
        self.assertNotIn("comparison_valid_but_source_invalid:later", result["errors"])
        self.assertNotIn("source_errors_mismatch:later", result["errors"])


# ----------------------------------------------------------------------
# 4. mismatched source snapshot
# ----------------------------------------------------------------------
class MismatchedSourceSnapshotTests(Prompt535TestCase):

    def test_unrelated_later_snapshot_is_a_mismatch(self):
        _, _, (first, second, third) = _snapshots(["rates"], ["rates"], ["comparison_changes"])
        result = check(compare(first, second), first, third)
        self.assert_has(result, "source_mismatch:later:identity", "source_snapshot_errors")

    def test_unrelated_earlier_snapshot_is_a_mismatch(self):
        _, _, (first, second, third) = _snapshots(["rates"], ["rates"], ["trend"])
        result = check(compare(second, third), first, third)
        self.assert_has(result, "source_mismatch:earlier:identity", "source_snapshot_errors")

    def test_section_recorded_from_the_wrong_source_is_detected(self):
        first, second = _varied_snapshots(["evaluation_counts"], ["evaluation_counts"])
        comparison = compare(first, second)
        self.assertTrue(comparison["sections"]["evaluation_counts"]["fields"]["accepted_count"]["changed"])
        wrong = copy.deepcopy(comparison)
        detail = wrong["sections"]["evaluation_counts"]["fields"]["accepted_count"]
        detail["earlier"], detail["later"] = detail["later"], detail["earlier"]
        result = check(wrong, first, second)
        self.assertFalse(result["valid"], result)
        self.assertIn("source_mismatch:earlier:accepted_count", result["numeric_errors"])
        self.assertIn("source_mismatch:later:accepted_count", result["numeric_errors"])

    def test_filtered_trend_section_recorded_from_the_wrong_source_is_detected(self):
        _, _, (first, second) = _snapshots(["trend"], ["trend"])
        comparison = compare(first, second)
        wrong = copy.deepcopy(comparison)
        wrong["sections"]["trend"]["earlier"] = {"source": "not_the_earlier_source"}
        result = check(wrong, first, second)
        self.assert_has(result, "source_mismatch:earlier:trend", "categorical_errors")

    def test_section_the_source_does_not_hold_is_detected(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        comparison = compare(first, second)
        other = copy.deepcopy(second)
        other["included_sections"] = []
        other["unavailable_sections"] = ["rates"]
        other["metrics"] = {"rates": None}
        result = check(comparison, first, other)
        self.assert_has(result, "shared_section_not_in_source:rates:later", "section_errors")

    def test_snapshot_from_another_history_is_a_mismatch(self):
        first, second = _varied_snapshots(["evaluation_counts"], ["evaluation_counts"])
        alien_first, alien_second = _varied_snapshots(
            ["evaluation_counts"], ["evaluation_counts"], base=(3, 5, 8))
        self.assertEqual(first["snapshot_id"], alien_first["snapshot_id"])
        comparison = compare(first, second)
        result = check(comparison, alien_first, alien_second)
        self.assertFalse(result["valid"], result)
        self.assertTrue(any(code.startswith("source_mismatch:") for code in result["errors"]),
                        result["errors"])

    def test_report_level_same_id_different_sequence_is_a_mismatch_not_missing(self):
        built, _, (first, second) = _snapshots(["rates"], ["rates"])
        comparison = compare(first, second)
        retagged = copy.deepcopy(second)
        retagged["sequence"] = 9
        result = validate_report(built, filtered_snapshots=[first, retagged],
                                 filtered_comparisons=[comparison])
        self.assertTrue(any(code.startswith("filtered_comparison_source_inconsistent:0:")
                            for code in result["errors"]), result["errors"])

    def test_report_level_unrelated_snapshots_sharing_only_a_sequence_stay_missing(self):
        built, _, (first, second) = _snapshots(["rates"], ["rates"])
        comparison = compare(first, second)
        unrelated = copy.deepcopy([first, second])
        for snap in unrelated:
            snap["snapshot_id"] = "unrelated-%d" % snap["sequence"]
        result = validate_report(built, filtered_snapshots=unrelated,
                                 filtered_comparisons=[comparison])
        self.assertFalse(any(code.startswith("filtered_comparison_source_inconsistent")
                             for code in result["errors"]), result["errors"])


# ----------------------------------------------------------------------
# 5. missing source snapshot
# ----------------------------------------------------------------------
class MissingSourceSnapshotTests(Prompt535TestCase):

    def test_missing_earlier_source(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        result = check(compare(first, second), None, second)
        self.assertEqual(result["source_snapshot_errors"], ["source_snapshot_missing:earlier"])

    def test_missing_later_source(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        result = check(compare(first, second), first, None)
        self.assertEqual(result["source_snapshot_errors"], ["source_snapshot_missing:later"])

    def test_both_sources_missing(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        result = check(compare(first, second), None, None)
        self.assertEqual(result["source_snapshot_errors"],
                         ["source_snapshot_missing:earlier", "source_snapshot_missing:later"])

    def test_a_missing_source_is_never_guessed_at_or_ordered(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        result = check(compare(first, second), None, second)
        self.assertEqual(result["ordering_errors"], [])
        self.assertEqual(result["section_errors"], [])

    def test_sources_not_given_are_not_checked(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        self.assert_valid(check(compare(first, second)))
        self.assert_valid(check(compare(first, second), first))
        self.assert_valid(check(compare(first, second), later_snapshot=second))

    def test_report_level_snapshot_absent_from_the_given_list_is_not_judged(self):
        built, _, (first, second) = _snapshots(["rates"], ["rates"])
        result = validate_report(built, filtered_snapshots=[first],
                                 filtered_comparisons=[compare(first, second)])
        self.assertFalse(any(code.startswith("filtered_comparison_source_inconsistent")
                             for code in result["errors"]), result["errors"])


# ----------------------------------------------------------------------
# 6. valid filtered comparison
# ----------------------------------------------------------------------
class ValidFilteredComparisonTests(Prompt535TestCase):

    def test_sections_present_in_both_come_from_both_sources(self):
        _, _, (first, second) = _snapshots(["evaluation_counts", "rates", "trend"],
                                           ["evaluation_counts", "rates", "trend"])
        comparison = compare(first, second)
        self.assertEqual(comparison["common_sections"], ["evaluation_counts", "rates", "trend"])
        self.assert_valid(check(comparison, first, second))

    def test_one_sided_sections_come_only_from_their_own_source(self):
        _, _, (first, second) = _snapshots(["rates", "trend"], ["rates"])
        comparison = compare(first, second)
        self.assertEqual(comparison["sections"]["trend"]["presence"], "present_only_earlier")
        self.assert_valid(check(comparison, first, second))

    def test_earlier_only_section_found_in_the_later_source_is_detected(self):
        _, _, (first, second) = _snapshots(["rates", "trend"], ["rates"])
        comparison = compare(first, second)
        later_with_trend = copy.deepcopy(first)
        later_with_trend.update({"snapshot_id": second["snapshot_id"], "sequence": second["sequence"]})
        result = check(comparison, first, later_with_trend)
        self.assertFalse(result["valid"], result)
        self.assertIn("earlier_only_section_in_later_source:trend", result["section_errors"])

    def test_unavailable_section_stays_unavailable_in_both(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        comparison = compare(first, second)
        self.assertEqual(comparison["sections"]["trend"]["presence"], "unavailable_in_both")
        self.assert_valid(check(comparison, first, second))

    def test_unavailable_section_reported_available_by_a_source_is_detected(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        comparison = compare(first, second)
        richer = copy.deepcopy(second)
        richer["included_sections"] = ["rates", "trend"]
        richer["metrics"]["trend"] = {"source": "x"}
        result = check(comparison, first, richer)
        self.assertIn("unavailable_section_in_source:trend:later", result["section_errors"])

    def test_report_level_faithful_comparison_over_a_longer_history(self):
        built, _, snaps = _snapshots(["rates", "trend"], ["rates", "trend"], ["rates"])
        comparisons = [compare(snaps[0], snaps[1]), compare(snaps[1], snaps[2])]
        result = validate_report(built, filtered_snapshots=snaps, filtered_comparisons=comparisons)
        self.assertFalse(any(code.startswith("filtered_comparison_source_inconsistent")
                             for code in result["errors"]), result["errors"])


# ----------------------------------------------------------------------
# 7. empty / zero-data comparison
# ----------------------------------------------------------------------
class EmptyOrZeroDataComparisonTests(Prompt535TestCase):

    def test_empty_filtered_snapshots_compare_and_validate(self):
        _, _, (first, second) = _snapshots([], [])
        comparison = compare(first, second)
        self.assertEqual(comparison["common_sections"], [])
        self.assertEqual(comparison["numeric"], {})
        result = check(comparison, first, second)
        self.assert_valid(result)
        self.assertIn("no_shared_sections", result["unavailable"])

    def test_empty_sources_still_must_be_the_named_ones(self):
        _, _, (first, second, third) = _snapshots([], [], [])
        result = check(compare(first, second), first, third)
        self.assert_has(result, "source_mismatch:later:identity", "source_snapshot_errors")

    def test_empty_sources_reversed_are_still_reported(self):
        _, _, (first, second) = _snapshots([], [])
        result = check(compare(first, second), second, first)
        self.assert_has(result, "reversed_source_snapshots", "ordering_errors")

    def test_zero_evaluation_data_compares_and_validates(self):
        _, _, (first, second) = _snapshots(["evaluation_counts", "rates"],
                                           ["evaluation_counts", "rates"], counts=(0, 0, 0))
        comparison = compare(first, second)
        self.assertEqual(comparison["sections"]["evaluation_counts"]["fields"]["total_evaluations"]["later"], 0)
        self.assertEqual(comparison["sections"]["rates"]["fields"]["acceptance_rate"]["later"], 0.0)
        self.assertTrue(comparison["identical"])
        self.assert_valid(check(comparison, first, second))

    def test_zero_data_source_swapped_for_a_different_one_is_a_mismatch(self):
        zero_first, zero_second = _varied_snapshots(
            ["evaluation_counts"], ["evaluation_counts"], base=(0, 0, 0))
        busy_first, busy_second = _varied_snapshots(
            ["evaluation_counts"], ["evaluation_counts"], base=(1, 2, 4))
        comparison = compare(zero_first, zero_second)
        result = check(comparison, busy_first, busy_second)
        self.assertFalse(result["valid"], result)
        self.assertTrue(any(code.startswith("source_mismatch:") for code in result["errors"]),
                        result["errors"])

    def test_a_missing_numeric_value_stays_unavailable_not_zero(self):
        first, second = _varied_snapshots(["rates"], ["evaluation_counts"])
        comparison = compare(first, second)
        self.assertEqual(comparison["numeric"], {})
        result = check(comparison, first, second)
        self.assert_valid(result)
        self.assertIn("no_comparable_numeric_metrics", result["unavailable"])

    def test_snapshot_of_a_missing_filtered_summary_is_an_invalid_state_not_repaired(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        empty_invalid = history.record_filtered_summary(None)
        _, summary = _summary()
        later = history.record_filtered_summary(filt(summary, ["rates"]))
        self.assertEqual(empty_invalid["validation_status"], "invalid")
        comparison = compare(empty_invalid, later)
        result = check(comparison, empty_invalid, later)
        self.assertEqual(result["source_snapshot_errors"],
                         ["source_snapshot_validation_status_invalid:earlier"])
        self.assertEqual(comparison["sections"]["rates"]["presence"], "present_only_later")

    def test_empty_dict_comparison_is_structurally_reported(self):
        _, _, (first, second) = _snapshots([], [])
        result = check({}, first, second)
        self.assertFalse(result["valid"])
        self.assertIn("missing_field:valid", result["structural_errors"])


# ----------------------------------------------------------------------
# 8. scope, determinism and non-mutation
# ----------------------------------------------------------------------
class ScopeAndSafetyTests(Prompt535TestCase):

    def test_results_are_deterministic(self):
        _, _, (first, second) = _snapshots(["rates", "trend"], ["rates"])
        comparison = compare(first, second)
        first_run = check(comparison, second, first)
        self.assertEqual(first_run, check(comparison, second, first))

    def test_nothing_is_mutated_or_repaired(self):
        _, _, (first, second, third) = _snapshots(["rates", "trend"], ["rates"], ["trend"])
        comparison = compare(first, second)
        before = copy.deepcopy((comparison, first, second, third))
        check(comparison, second, first)
        check(comparison, first, third)
        check(comparison, None, None)
        self.assertEqual((comparison, first, second, third), before)

    def test_existing_result_shape_and_keys_are_unchanged(self):
        _, _, (first, second) = _snapshots(["rates"], ["rates"])
        result = check(compare(first, second), first, second)
        self.assertEqual(sorted(result), sorted([
            "valid", "well_formed", "errors", "warnings", "structural_errors", "section_errors",
            "numeric_errors", "categorical_errors", "ordering_errors", "source_snapshot_errors",
            "unavailable"]))

    def test_a_valid_comparison_without_sources_is_unaffected(self):
        _, _, (first, second) = _snapshots(["rates", "trend"], ["rates", "trend"])
        self.assert_valid(check(compare(first, second)))


if __name__ == "__main__":
    unittest.main()
