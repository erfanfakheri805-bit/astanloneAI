"""
Tests for Prompt 527 - Validate Report Chronology.

The existing Unified Diagnostic Report validator
(`validate_learned_knowledge_diagnostic_report()`) already required the
latest comparison and the trend's range to run forward, nothing to refer
to a snapshot later than the latest one, and (given the sources) the
snapshots and comparisons to be in order. Prompt 527 completes that, with
the same `"invalid_chronological_ordering:<where>"` error family:

  * `snapshots.count`             - more snapshots than the latest sequence
                                    allows (e.g. handed over newest-first)
  * `comparisons.<index>`         - ANY given comparison whose earlier
                                    snapshot is not before its later one
  * `trend_after_latest_comparison` /
    `inconsistent_trend_source:chronological_range`
                                  - a trend running past (or, when derived,
                                    stopping short of) the latest comparison
  * `filtered_trend.chronology`   - a filtered trend's reversed-entry list
                                    that itself runs backwards

A reversed filtered chronology - or a reversed filtered comparison Prompt
520 reports as ineligible - stays a reported state, not an error. Empty
and single-item data are judged exactly as before.

Run directly:
    python -m unittest tests.test_learned_knowledge_report_chronology -v
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
    filter_learned_knowledge_diagnostic_summary as filt,
    format_learned_knowledge_diagnostic_summary as fmt,
    compare_learned_knowledge_filtered_summary_snapshots as compare,
    summarize_learned_knowledge_diagnostic_snapshot_comparison_trend as summarize,
)

OK = {"valid": True, "well_formed": True, "errors": [], "warnings": []}
_SUMMARY_ALL = ["evaluation_counts", "rates", "dominant_rejection_reason",
                "comparison_changes", "trend", "validation_statuses"]
_ACCEPTED = build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(STATUS_PASSED, REASON_OK))


def _stats(accepted):
    stats = LearnedKnowledgeDecisionStatistics()
    for _ in range(accepted):
        stats.record(_ACCEPTED)
    return stats


def _history(steps=(1, 2, 4, 8)):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for accepted in steps:
        history.record_statistics(_stats(accepted))
    return history


def _consecutive(history):
    return [history.compare_sequences(i, i + 1) for i in range(1, len(history.get_all()))]


def _filtered_summary(accepted):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for count in (1, accepted):
        history.record_statistics(_stats(count))
    built = report(snapshots=history, comparisons=[history.compare_sequences(1, 2)])
    return fmt(built, validate(built, snapshots=history, comparisons=[history.compare_sequences(1, 2)]))


def _filtered_snapshots(totals=(1, 2, 5, 9)):
    history = LearnedKnowledgeFilteredSummarySnapshotHistory()
    return [history.record_filtered_summary(filt(_filtered_summary(n), _SUMMARY_ALL)) for n in totals]


def _filtered_consecutive(snaps):
    return [compare(snaps[i], snaps[i + 1]) for i in range(len(snaps) - 1)]


def _identity(snapshot):
    return {"snapshot_id": snapshot["snapshot_id"], "sequence": snapshot["sequence"]}


class Prompt527TestCase(unittest.TestCase):
    def assert_valid(self, built, **sources):
        result = validate(built, **sources)
        self.assertEqual(result, OK, result)

    def errors_of(self, built, **sources):
        result = validate(built, **sources)
        self.assertFalse(result["valid"], result)
        return result["errors"]


# ----------------------------------------------------------------------
# 1. valid chronological data
# ----------------------------------------------------------------------
class ValidChronologyTests(Prompt527TestCase):

    def test_ordered_snapshots_comparisons_trend_and_filtered_trend_are_valid(self):
        history = _history()
        comparisons = _consecutive(history)
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assert_valid(
            built, snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assert_valid(built)

    def test_plain_list_of_ordered_snapshots_is_valid(self):
        snapshots = _history().get_all()
        built = report(snapshots=snapshots)
        self.assert_valid(built, snapshots=snapshots)

    def test_overlapping_and_non_adjacent_comparisons_that_run_forward_are_valid(self):
        history = _history()
        comparisons = [history.compare_sequences(1, 3), history.compare_sequences(2, 4)]
        built = report(snapshots=history, comparisons=comparisons)
        self.assert_valid(built, snapshots=history, comparisons=comparisons)

    def test_trend_ends_at_the_latest_comparison(self):
        history = _history()
        built = report(snapshots=history, comparisons=_consecutive(history))
        self.assertEqual(
            built["trend"]["summary"]["chronological_range"]["later"],
            built["comparison"]["latest"]["later"])
        self.assert_valid(built)

    def test_provided_trend_covering_fewer_comparisons_is_not_a_derived_mismatch(self):
        history = _history()
        comparisons = _consecutive(history)
        trend = summarize(comparisons[:1])
        built = report(snapshots=history, comparisons=comparisons, trend_summary=trend)
        self.assertEqual(built["trend"]["source"], "provided")
        self.assert_valid(built, snapshots=history, comparisons=comparisons, trend_summary=trend)


# ----------------------------------------------------------------------
# 2. reversed snapshots
# ----------------------------------------------------------------------
class ReversedSnapshotTests(Prompt527TestCase):

    def test_newest_first_snapshots_are_flagged_from_the_report_alone(self):
        reversed_snapshots = list(reversed(_history().get_all()))
        built = report(snapshots=reversed_snapshots)
        self.assertEqual(built["snapshots"]["latest"]["sequence"], 1)
        self.assertEqual(built["snapshots"]["count"], 4)
        self.assertIn("invalid_chronological_ordering:snapshots.count", self.errors_of(built))

    def test_newest_first_snapshots_are_flagged_with_the_source_too(self):
        reversed_snapshots = list(reversed(_history().get_all()))
        built = report(snapshots=reversed_snapshots)
        errors = self.errors_of(built, snapshots=reversed_snapshots)
        self.assertIn("invalid_chronological_ordering:snapshots", errors)
        self.assertIn("invalid_chronological_ordering:snapshots.count", errors)

    def test_partly_out_of_order_snapshots_are_flagged_by_the_source_check(self):
        s = _history().get_all()
        shuffled = [s[0], s[2], s[1], s[3]]
        built = report(snapshots=shuffled)
        self.assertEqual(self.errors_of(built, snapshots=shuffled),
                         ["invalid_chronological_ordering:snapshots"])

    def test_repeated_sequence_is_flagged(self):
        s = _history().get_all()
        repeated = [s[0], copy.deepcopy(s[0])]
        built = report(snapshots=repeated)
        self.assertIn("invalid_chronological_ordering:snapshots.count", self.errors_of(built))
        self.assertIn("invalid_chronological_ordering:snapshots",
                      self.errors_of(built, snapshots=repeated))

    def test_count_larger_than_the_latest_sequence_is_flagged_in_a_tampered_report(self):
        built = copy.deepcopy(report(snapshots=_history()))
        built["snapshots"]["count"] = 5
        self.assertIn("invalid_chronological_ordering:snapshots.count", self.errors_of(built))

    def test_count_equal_to_the_latest_sequence_is_valid(self):
        built = report(snapshots=_history())
        self.assertEqual(
            built["snapshots"]["count"], built["snapshots"]["latest"]["sequence"])
        self.assert_valid(built)


# ----------------------------------------------------------------------
# 3. reversed comparison
# ----------------------------------------------------------------------
class ReversedComparisonTests(Prompt527TestCase):

    def test_latest_comparison_with_earlier_after_later_is_flagged(self):
        history = _history()
        built = report(snapshots=history, comparisons=[history.compare_sequences(3, 2)])
        self.assertFalse(built["comparison"]["latest"]["chronological"])
        self.assertIn("invalid_chronological_ordering:comparison.latest", self.errors_of(built))

    def test_latest_comparison_of_a_snapshot_with_itself_is_flagged(self):
        history = _history()
        built = report(snapshots=history, comparisons=[history.compare_sequences(2, 2)])
        self.assertIn("invalid_chronological_ordering:comparison.latest", self.errors_of(built))

    def test_reversed_comparison_in_the_middle_of_the_list_is_flagged_by_position(self):
        history = _history()
        comparisons = [history.compare_sequences(1, 2), history.compare_sequences(3, 2),
                       history.compare_sequences(3, 4)]
        built = report(snapshots=history, comparisons=comparisons)
        self.assertNotIn("comparison.latest", " ".join(validate(built)["errors"]))
        errors = self.errors_of(built, snapshots=history, comparisons=comparisons)
        self.assertIn("invalid_chronological_ordering:comparisons.1", errors)
        self.assertNotIn("invalid_chronological_ordering:comparisons.0", errors)
        self.assertNotIn("invalid_chronological_ordering:comparisons.2", errors)

    def test_every_reversed_comparison_is_reported_in_list_order(self):
        history = _history()
        comparisons = [history.compare_sequences(2, 1), history.compare_sequences(2, 3),
                       history.compare_sequences(4, 3)]
        errors = self.errors_of(
            report(snapshots=history, comparisons=comparisons),
            snapshots=history, comparisons=comparisons)
        flagged = [e for e in errors if e.startswith("invalid_chronological_ordering:comparisons.")]
        self.assertEqual(flagged, ["invalid_chronological_ordering:comparisons.0",
                                   "invalid_chronological_ordering:comparisons.2"])

    def test_comparisons_whose_later_snapshots_go_backwards_are_flagged(self):
        history = _history()
        comparisons = [history.compare_sequences(3, 4), history.compare_sequences(1, 2)]
        errors = self.errors_of(
            report(snapshots=history, comparisons=comparisons),
            snapshots=history, comparisons=comparisons)
        self.assertIn("invalid_chronological_ordering:comparisons", errors)

    def test_comparison_after_the_latest_snapshot_is_flagged(self):
        history = _history()
        built = copy.deepcopy(report(snapshots=history, comparisons=[history.compare_sequences(3, 4)]))
        built["snapshots"]["latest"] = history.get_all()[2]
        built["snapshots"]["count"] = 3
        self.assertIn("invalid_chronological_ordering:comparison_after_latest_snapshot",
                      self.errors_of(built))

    def test_invalid_comparison_in_the_list_is_not_judged_by_ordering(self):
        history = _history()
        broken = copy.deepcopy(history.compare_sequences(2, 3))
        broken["valid"] = False
        broken["errors"] = ["broken"]
        comparisons = [history.compare_sequences(1, 2), broken]
        errors = validate(report(snapshots=history, comparisons=comparisons),
                          snapshots=history, comparisons=comparisons)["errors"]
        self.assertFalse([e for e in errors if e.startswith("invalid_chronological_ordering")], errors)


# ----------------------------------------------------------------------
# 4. invalid trend ordering
# ----------------------------------------------------------------------
class InvalidTrendOrderingTests(Prompt527TestCase):

    def _built(self):
        history = _history()
        return history, copy.deepcopy(report(snapshots=history, comparisons=_consecutive(history)))

    def test_trend_range_running_backwards_is_flagged(self):
        _, built = self._built()
        range_ = built["trend"]["summary"]["chronological_range"]
        range_["earlier"], range_["later"] = range_["later"], range_["earlier"]
        self.assertIn("invalid_chronological_ordering:trend.chronological_range",
                      self.errors_of(built))

    def test_trend_ending_after_the_latest_comparison_is_flagged(self):
        history = _history()
        comparisons = _consecutive(history)[:2]          # 1->2, 2->3
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["trend"]["summary"]["chronological_range"]["later"] = _identity(history.get_all()[3])
        self.assertIn("invalid_chronological_ordering:trend_after_latest_comparison",
                      self.errors_of(built))

    def test_derived_trend_stopping_short_of_the_latest_comparison_is_flagged(self):
        history = _history()
        built = copy.deepcopy(report(snapshots=history, comparisons=_consecutive(history)))
        built["trend"]["summary"]["chronological_range"]["later"] = _identity(history.get_all()[1])
        errors = self.errors_of(built)
        self.assertIn("inconsistent_trend_source:chronological_range", errors)
        self.assertNotIn("invalid_chronological_ordering:trend_after_latest_comparison", errors)

    def test_trend_ending_after_the_latest_snapshot_is_flagged(self):
        history = _history()
        built = copy.deepcopy(report(snapshots=history, comparisons=_consecutive(history)))
        built["trend"]["summary"]["chronological_range"]["later"] = {
            "snapshot_id": "learned_knowledge_snapshot_000009", "sequence": 9}
        self.assertIn("invalid_chronological_ordering:trend_after_latest_snapshot",
                      self.errors_of(built))

    def test_trend_derived_from_out_of_order_comparisons_is_flagged_with_the_sources(self):
        history = _history()
        comparisons = [history.compare_sequences(3, 4), history.compare_sequences(1, 2)]
        built = report(snapshots=history, comparisons=comparisons)
        errors = self.errors_of(built, snapshots=history, comparisons=comparisons)
        self.assertIn("invalid_chronological_ordering:trend.chronological_range", errors)
        self.assertIn("invalid_chronological_ordering:comparisons", errors)

    def test_trend_that_disagrees_with_its_source_comparisons_is_still_flagged(self):
        history = _history()
        comparisons = _consecutive(history)
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["trend"]["summary"]["chronological_range"]["earlier"] = _identity(history.get_all()[1])
        self.assertTrue(any(e.startswith("source_mismatch:trend")
                            for e in self.errors_of(built, snapshots=history, comparisons=comparisons)))


# ----------------------------------------------------------------------
# 5. empty data
# ----------------------------------------------------------------------
class EmptyDataTests(Prompt527TestCase):

    def test_report_with_nothing_is_valid(self):
        self.assert_valid(report())

    def test_empty_history_and_empty_lists_are_valid(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        built = report(snapshots=history, comparisons=[])
        self.assertFalse(built["snapshots"]["available"])
        self.assertFalse(built["comparison"]["available"])
        self.assertFalse(built["trend"]["available"])
        self.assert_valid(built, snapshots=history, comparisons=[])

    def test_empty_plain_snapshot_list_is_valid(self):
        self.assert_valid(report(snapshots=[]), snapshots=[])

    def test_empty_filtered_data_is_valid(self):
        built = report(filtered_comparisons=[])
        self.assertFalse(built["filtered_trend"]["available"])
        self.assert_valid(built, filtered_comparisons=[])
        self.assert_valid(report(filtered_comparisons=None, filtered_trend_summary=None))

    def test_every_source_empty_at_once_is_valid(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        built = report(snapshots=history, comparisons=[], filtered_comparisons=[])
        self.assert_valid(built, snapshots=history, comparisons=[], filtered_comparisons=[])


# ----------------------------------------------------------------------
# 6. single-item data
# ----------------------------------------------------------------------
class SingleItemDataTests(Prompt527TestCase):

    def test_single_snapshot_is_valid(self):
        history = _history((3,))
        built = report(snapshots=history)
        self.assertEqual(built["snapshots"]["count"], 1)
        self.assert_valid(built, snapshots=history)

    def test_single_snapshot_with_a_large_sequence_is_valid(self):
        snapshot = copy.deepcopy(_history().get_all()[3])           # sequence 4, alone
        built = report(snapshots=[snapshot])
        self.assert_valid(built, snapshots=[snapshot])

    def test_single_comparison_and_its_trend_are_valid(self):
        history = _history((1, 2))
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(built["comparison"]["total_considered"], 1)
        self.assertEqual(built["trend"]["summary"]["total_comparisons"], 1)
        self.assert_valid(built, snapshots=history, comparisons=comparisons)

    def test_single_reversed_comparison_is_still_flagged(self):
        history = _history((1, 2))
        comparisons = [history.compare_sequences(2, 1)]
        errors = self.errors_of(
            report(snapshots=history, comparisons=comparisons),
            snapshots=history, comparisons=comparisons)
        self.assertIn("invalid_chronological_ordering:comparisons.0", errors)

    def test_single_filtered_comparison_and_trend_are_valid(self):
        filtered = _filtered_consecutive(_filtered_snapshots((1, 2)))
        built = report(filtered_comparisons=filtered)
        self.assertEqual(built["filtered_trend"]["summary"]["total_comparisons"], 1)
        self.assertEqual(built["filtered_trend"]["summary"]["chronology"],
                         {"ordered": True, "reversed": []})
        self.assert_valid(built, filtered_comparisons=filtered)


# ----------------------------------------------------------------------
# 7. filtered trend chronology
# ----------------------------------------------------------------------
class FilteredTrendChronologyTests(Prompt527TestCase):

    def test_ordered_filtered_trend_is_valid(self):
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = report(filtered_comparisons=filtered)
        self.assertTrue(built["filtered_trend"]["summary"]["chronology"]["ordered"])
        self.assert_valid(built, filtered_comparisons=filtered)

    def test_filtered_trend_with_base_data_is_valid(self):
        history = _history()
        comparisons = _consecutive(history)
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assert_valid(
            built, snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)

    def test_filtered_trend_lineage_is_independent_of_the_snapshots_section(self):
        # Four filtered snapshots, three base snapshots: the filtered
        # trend is never compared with the base "snapshots" section.
        history = _history((1, 2, 4))
        filtered = _filtered_consecutive(_filtered_snapshots((1, 2, 5, 9)))
        built = report(snapshots=history, comparisons=_consecutive(history),
                       filtered_comparisons=filtered)
        self.assertEqual(
            built["filtered_trend"]["summary"]["chronological_range"]["later"]["sequence"], 4)
        self.assertEqual(built["snapshots"]["latest"]["sequence"], 3)
        self.assert_valid(built)

    def test_reversed_filtered_chronology_remains_a_reported_state_not_an_error(self):
        filtered = _filtered_consecutive(_filtered_snapshots())
        backwards = list(reversed(filtered))
        built = report(filtered_comparisons=backwards)
        chronology = built["filtered_trend"]["summary"]["chronology"]
        self.assertFalse(chronology["ordered"])
        self.assertEqual([entry["index"] for entry in chronology["reversed"]], [1, 2])
        self.assert_valid(built)
        self.assert_valid(built, filtered_comparisons=backwards)

    def test_reversed_filtered_comparison_is_reported_ineligible_not_an_error(self):
        snaps = _filtered_snapshots()
        filtered = [compare(snaps[0], snaps[1]), compare(snaps[2], snaps[1])]
        built = report(filtered_comparisons=filtered)
        summary = built["filtered_trend"]["summary"]
        self.assertEqual(summary["eligible_count"], 1)
        self.assertEqual(summary["ineligible_comparisons"][0]["index"], 1)
        self.assert_valid(built, filtered_comparisons=filtered)

    def test_filtered_reversed_entry_whose_previous_index_is_not_earlier_is_flagged(self):
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = copy.deepcopy(report(filtered_comparisons=list(reversed(filtered))))
        built["filtered_trend"]["summary"]["chronology"]["reversed"] = [
            {"index": 0, "previous_index": 1}]
        self.assertIn("invalid_chronological_ordering:filtered_trend.chronology",
                      self.errors_of(built))

    def test_filtered_reversed_entries_out_of_order_are_flagged(self):
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = copy.deepcopy(report(filtered_comparisons=list(reversed(filtered))))
        built["filtered_trend"]["summary"]["chronology"]["reversed"] = [
            {"index": 2, "previous_index": 1}, {"index": 1, "previous_index": 0}]
        self.assertIn("invalid_chronological_ordering:filtered_trend.chronology",
                      self.errors_of(built))

    def test_filtered_reversed_entry_repeating_an_index_is_flagged(self):
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = copy.deepcopy(report(filtered_comparisons=list(reversed(filtered))))
        built["filtered_trend"]["summary"]["chronology"]["reversed"] = [
            {"index": 1, "previous_index": 0}, {"index": 1, "previous_index": 0}]
        self.assertIn("invalid_chronological_ordering:filtered_trend.chronology",
                      self.errors_of(built))

    def test_filtered_range_running_backwards_while_ordered_is_flagged(self):
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = copy.deepcopy(report(filtered_comparisons=filtered))
        range_ = built["filtered_trend"]["summary"]["chronological_range"]
        range_["earlier"], range_["later"] = range_["later"], range_["earlier"]
        self.assertIn("invalid_chronological_ordering:filtered_trend.chronological_range",
                      self.errors_of(built))


# ----------------------------------------------------------------------
# guarantees
# ----------------------------------------------------------------------
class ValidatorGuaranteeTests(Prompt527TestCase):

    def _tampered(self):
        history = _history()
        comparisons = [history.compare_sequences(1, 2), history.compare_sequences(3, 2)]
        built = report(snapshots=list(reversed(history.get_all())), comparisons=comparisons,
                       filtered_comparisons=_filtered_consecutive(_filtered_snapshots()))
        return history, comparisons, built

    def test_never_mutates_the_report_or_the_sources(self):
        history, comparisons, built = self._tampered()
        before = (copy.deepcopy(built), copy.deepcopy(comparisons), copy.deepcopy(history.get_all()))
        validate(built, snapshots=history, comparisons=comparisons)
        self.assertEqual(built, before[0])
        self.assertEqual(comparisons, before[1])
        self.assertEqual(history.get_all(), before[2])

    def test_deterministic_with_errors_in_a_fixed_order(self):
        history, comparisons, built = self._tampered()
        first = validate(built, snapshots=history, comparisons=comparisons)
        self.assertFalse(first["valid"])
        for _ in range(3):
            self.assertEqual(validate(built, snapshots=history, comparisons=comparisons), first)

    def test_source_comparison_ordering_error_leaves_well_formed_unchanged(self):
        history = _history()
        comparisons = [history.compare_sequences(1, 2), history.compare_sequences(3, 2),
                       history.compare_sequences(3, 4)]
        built = report(snapshots=history, comparisons=comparisons)
        result = validate(built, snapshots=history, comparisons=comparisons)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])   # a source-derived error, like a source mismatch


if __name__ == "__main__":
    unittest.main()
