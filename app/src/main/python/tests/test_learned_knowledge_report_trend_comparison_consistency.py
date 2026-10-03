"""
Tests for Prompt 528 - Validate Trend and Comparison Consistency.

The existing Unified Diagnostic Report validator
(`validate_learned_knowledge_diagnostic_report()`) already judged the
trend against the comparison in a few ways (a derived trend's total, the
trend's end metrics, chronology). Prompt 528 completes that, using only
what the pipeline already computes, so that a report which presents a
trend summary as valid while it contradicts its comparisons is reported:

  * `inconsistent_comparison_count:<trend>.<field>`
  * `trend_entry_without_comparison:<path>`   (a trend entry, no comparison)
  * `extra_trend_entry:<path>`                (an entry nothing justifies)
  * `missing_trend_entry:<path>`              (a comparison not accounted for)
  * `inconsistent_numeric_trend_state:<field>`
  * `inconsistent_categorical_trend_state:<name>`
  * `metric_mismatch:trend_start_vs_comparison:<field>`

`<trend>` is `trend` or `filtered_trend`. A trend the report's own
embedded validation result already declares invalid is not judged again,
and absent / empty / zero-evaluation data is judged exactly as before.

Run directly:
    python -m unittest tests.test_learned_knowledge_report_trend_comparison_consistency -v
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
    summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend as summarize_filtered,
    validate_learned_knowledge_diagnostic_snapshot_comparison as validate_comparison,
    validate_learned_knowledge_filtered_summary_snapshot_comparison as validate_filtered_comparison,
)

OK = {"valid": True, "well_formed": True, "errors": [], "warnings": []}
_SUMMARY_ALL = ["evaluation_counts", "rates", "dominant_rejection_reason",
                "comparison_changes", "trend", "validation_statuses"]
_ACCEPTED = build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(STATUS_PASSED, REASON_OK))
_NUMERIC_FIELDS = ("total_evaluations", "accepted_count", "rejected_count",
                   "no_candidate_count", "acceptance_rate", "rejection_rate")


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


def _ineligible(comparison):
    """A copy of `comparison` that fails Prompt 510 validation."""
    broken = copy.deepcopy(comparison)
    broken["numeric"]["total_evaluations"]["delta"] += 99
    return broken


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


def _ineligible_filtered(comparison):
    broken = copy.deepcopy(comparison)
    broken["numeric"]["total_evaluations"]["delta"] += 99
    return broken


class Prompt528TestCase(unittest.TestCase):
    def assert_valid(self, built, **sources):
        result = validate(built, **sources)
        self.assertEqual(result, OK, result)

    def errors_of(self, built, **sources):
        result = validate(built, **sources)
        self.assertFalse(result["valid"], result)
        return result["errors"]

    def assert_codes(self, errors, *codes):
        for code in codes:
            self.assertIn(code, errors)

    @staticmethod
    def tampered(built, section, mutate):
        """A copy of `built` with `built[section]["summary"]` changed by
        `mutate`. The embedded validation result is left as it was, so
        the report still presents the trend as valid."""
        changed = copy.deepcopy(built)
        mutate(changed[section]["summary"])
        return changed


def _set_numeric(field, **values):
    def mutate(summary):
        summary["numeric"][field].update(values)
    return mutate


# ----------------------------------------------------------------------
# 1. valid comparison / trend data
# ----------------------------------------------------------------------
class ValidComparisonTrendTests(Prompt528TestCase):

    def test_derived_trend_over_several_comparisons_is_valid(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assert_valid(built)
        self.assert_valid(built, snapshots=history, comparisons=comparisons)

    def test_provided_trend_matching_its_comparisons_is_valid(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons, trend_summary=summarize(comparisons))
        self.assertEqual(built["trend"]["source"], "provided")
        self.assert_valid(built)
        self.assert_valid(built, comparisons=comparisons, trend_summary=summarize(comparisons))

    def test_single_comparison_trend_is_valid(self):
        history = _history((1, 2))
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assert_valid(built)
        self.assert_valid(built, snapshots=history, comparisons=comparisons)

    def test_overlapping_comparisons_are_valid(self):
        history = _history()
        comparisons = [history.compare_sequences(1, 3), history.compare_sequences(2, 4)]
        built = report(snapshots=history, comparisons=comparisons)
        self.assert_valid(built, snapshots=history, comparisons=comparisons)

    def test_ineligible_comparison_listed_by_the_trend_is_valid(self):
        history = _history()
        comparisons = _consecutive(history)
        for position in (0, 1, 2):
            with self.subTest(ineligible_position=position):
                mixed = list(comparisons)
                mixed[position] = _ineligible(mixed[position])
                built = report(snapshots=history, comparisons=mixed)
                indices = [e["index"] for e in built["trend"]["summary"]["ineligible_comparisons"]]
                self.assertEqual(indices, [position])
                self.assert_valid(built)
                self.assert_valid(built, snapshots=history, comparisons=mixed)

    def test_every_comparison_ineligible_is_valid(self):
        history = _history()
        broken = [_ineligible(c) for c in _consecutive(history)]
        built = report(snapshots=history, comparisons=broken)
        self.assertEqual(built["trend"]["summary"]["eligible_count"], 0)
        self.assert_valid(built)
        self.assert_valid(built, comparisons=broken)

    def test_filtered_trend_matching_its_comparisons_is_valid(self):
        history = _history()
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = report(snapshots=history, comparisons=_consecutive(history), filtered_comparisons=filtered)
        self.assert_valid(built)
        self.assert_valid(built, filtered_comparisons=filtered)

    def test_provided_trend_without_a_comparison_section_is_judged_as_before(self):
        comparisons = _consecutive(_history())
        built = report(trend_summary=summarize(comparisons))
        self.assertFalse(built["comparison"]["available"])
        self.assert_valid(built)


# ----------------------------------------------------------------------
# 2. missing comparison
# ----------------------------------------------------------------------
class MissingComparisonTests(Prompt528TestCase):

    def _with_ineligible_last(self):
        history = _history()
        comparisons = _consecutive(history)
        comparisons[-1] = _ineligible(comparisons[-1])
        return history, comparisons, report(snapshots=history, comparisons=comparisons)

    def test_trend_entry_naming_a_comparison_that_does_not_exist(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons, trend_summary=summarize(comparisons))

        def add_phantom(summary):
            summary["total_comparisons"] = 4
            summary["ineligible_count"] = 1
            summary["ineligible_comparisons"] = [{"index": 3, "errors": ["incorrect_delta:total_evaluations"]}]
        changed = self.tampered(built, "trend", add_phantom)
        errors = self.errors_of(changed)
        self.assert_codes(
            errors, "inconsistent_comparison_count:trend.total_comparisons",
            "trend_entry_without_comparison:trend.ineligible_comparisons.3")
        errors = self.errors_of(changed, comparisons=comparisons)
        self.assert_codes(
            errors, "trend_entry_without_comparison:trend.ineligible_comparisons.3")

    def test_ineligible_latest_comparison_the_trend_does_not_account_for(self):
        history, comparisons, built = self._with_ineligible_last()

        def forget_it(summary):
            summary["eligible_count"] = 3
            summary["ineligible_count"] = 0
            summary["ineligible_comparisons"] = []
        changed = self.tampered(built, "trend", forget_it)
        self.assert_codes(self.errors_of(changed), "missing_trend_entry:trend.ineligible_comparisons.2")
        self.assert_codes(
            self.errors_of(changed, comparisons=comparisons),
            "missing_trend_entry:trend.ineligible_comparisons.2",
            "inconsistent_comparison_count:trend.eligible_count",
            "inconsistent_comparison_count:trend.ineligible_count")

    def test_comparison_missing_from_the_source_list(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        errors = self.errors_of(built, comparisons=comparisons[:2])
        self.assertIn("inconsistent_comparison_count:trend.total_comparisons", errors)

    def test_missing_comparison_for_a_valid_trend_is_reported_as_before(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        built["comparison"] = {"available": False, "total_considered": 0, "latest": None}
        built["comparison_validation"] = {"available": False, "result": None}
        errors = self.errors_of(built)
        self.assertIn("derived_trend_without_comparisons", errors)
        self.assertNotIn("inconsistent_comparison_count:trend.total_comparisons", errors)


# ----------------------------------------------------------------------
# 3. extra trend entry
# ----------------------------------------------------------------------
class ExtraTrendEntryTests(Prompt528TestCase):

    def setUp(self):
        self.history = _history()
        self.comparisons = _consecutive(self.history)
        self.built = report(snapshots=self.history, comparisons=self.comparisons)

    def test_eligible_comparison_listed_as_ineligible(self):
        def list_it(summary):
            summary["eligible_count"] = 2
            summary["ineligible_count"] = 1
            summary["ineligible_comparisons"] = [{"index": 2, "errors": ["incorrect_delta:total_evaluations"]}]
        changed = self.tampered(self.built, "trend", list_it)
        self.assert_codes(self.errors_of(changed), "extra_trend_entry:trend.ineligible_comparisons.2")
        self.assert_codes(
            self.errors_of(changed, comparisons=self.comparisons),
            "extra_trend_entry:trend.ineligible_comparisons.2")

    def test_earlier_eligible_comparison_listed_as_ineligible_with_sources(self):
        def list_it(summary):
            summary["eligible_count"] = 2
            summary["ineligible_count"] = 1
            summary["ineligible_comparisons"] = [{"index": 0, "errors": ["incorrect_delta:total_evaluations"]}]
        changed = self.tampered(self.built, "trend", list_it)
        self.assert_codes(
            self.errors_of(changed, comparisons=self.comparisons),
            "extra_trend_entry:trend.ineligible_comparisons.0")

    def test_numeric_entry_for_an_unknown_field(self):
        def add_field(summary):
            summary["numeric"]["mystery_metric"] = {"state": "unchanged", "start": 1, "end": 1, "delta": 0}
        changed = self.tampered(self.built, "trend", add_field)
        self.assert_codes(self.errors_of(changed), "extra_trend_entry:trend.numeric.mystery_metric")
        self.assert_codes(
            self.errors_of(changed, comparisons=self.comparisons),
            "extra_trend_entry:trend.numeric.mystery_metric")

    def test_filtered_trend_index_the_trend_counts_as_ineligible(self):
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = report(filtered_comparisons=filtered)

        def mark(summary):
            summary["eligible_count"] = 2
            summary["ineligible_count"] = 1
            summary["ineligible_comparisons"] = [{"index": 1, "errors": ["incorrect_delta:total_evaluations"]}]
        changed = self.tampered(built, "filtered_trend", mark)
        self.assert_codes(
            self.errors_of(changed),
            "extra_trend_entry:filtered_trend.numeric.total_evaluations.available_in.1")
        self.assert_codes(
            self.errors_of(changed, filtered_comparisons=filtered),
            "extra_trend_entry:filtered_trend.ineligible_comparisons.1")

    def test_filtered_trend_categorical_entry_for_an_unknown_section(self):
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = report(filtered_comparisons=filtered)

        def add_section(summary):
            summary["categorical"]["mystery_section"] = {"state": "unchanged"}
        changed = self.tampered(built, "filtered_trend", add_section)
        self.assert_codes(self.errors_of(changed), "extra_trend_entry:filtered_trend.categorical.mystery_section")


# ----------------------------------------------------------------------
# 4. inconsistent comparison count
# ----------------------------------------------------------------------
class InconsistentComparisonCountTests(Prompt528TestCase):

    def setUp(self):
        self.history = _history()
        self.comparisons = _consecutive(self.history)

    def _count_change(self, total):
        def mutate(summary):
            summary["total_comparisons"] = total
            summary["eligible_count"] = total
        return mutate

    def test_provided_trend_counts_more_comparisons_than_the_report_holds(self):
        built = report(snapshots=self.history, comparisons=self.comparisons,
                       trend_summary=summarize(self.comparisons))
        changed = self.tampered(built, "trend", self._count_change(5))
        self.assertEqual(self.errors_of(changed), ["inconsistent_comparison_count:trend.total_comparisons"])
        self.assert_codes(
            self.errors_of(changed, comparisons=self.comparisons),
            "inconsistent_comparison_count:trend.total_comparisons",
            "inconsistent_comparison_count:trend.eligible_count")

    def test_provided_trend_counts_fewer_comparisons_than_the_report_holds(self):
        built = report(snapshots=self.history, comparisons=self.comparisons,
                       trend_summary=summarize(self.comparisons))
        changed = self.tampered(built, "trend", self._count_change(2))
        self.assertEqual(self.errors_of(changed), ["inconsistent_comparison_count:trend.total_comparisons"])

    def test_derived_trend_count_keeps_its_existing_error_alone(self):
        built = report(snapshots=self.history, comparisons=self.comparisons)
        self.assertEqual(built["trend"]["source"], "derived")
        changed = self.tampered(built, "trend", self._count_change(5))
        self.assertEqual(self.errors_of(changed), ["inconsistent_trend_source:total_comparisons"])

    def test_latest_comparison_eligible_but_trend_counts_none_eligible(self):
        built = report(snapshots=self.history, comparisons=self.comparisons,
                       trend_summary=summarize(self.comparisons))

        def none_eligible(summary):
            summary["eligible_count"] = 0
            summary["ineligible_count"] = 3
            summary["ineligible_comparisons"] = [
                {"index": i, "errors": ["incorrect_delta:total_evaluations"]} for i in range(3)]
            summary["chronological_range"] = {"earlier": None, "later": None}
            for entry in summary["numeric"].values():
                entry.update({"state": "insufficient_data", "start": None, "end": None, "delta": None})
            summary["dominant_rejection_reason"] = {"state": "insufficient_data", "start": None, "end": None}
        changed = self.tampered(built, "trend", none_eligible)
        self.assert_codes(
            self.errors_of(changed),
            "inconsistent_comparison_count:trend.eligible_count",
            "extra_trend_entry:trend.ineligible_comparisons.2")

    def test_counts_that_only_the_source_comparisons_contradict(self):
        built = report(snapshots=self.history, comparisons=self.comparisons)

        def swap_counts(summary):
            summary["eligible_count"] = 2
            summary["ineligible_count"] = 1
            summary["ineligible_comparisons"] = [{"index": 0, "errors": ["incorrect_delta:total_evaluations"]}]
        changed = self.tampered(built, "trend", swap_counts)
        errors = self.errors_of(changed, comparisons=self.comparisons)
        self.assert_codes(
            errors, "inconsistent_comparison_count:trend.eligible_count",
            "inconsistent_comparison_count:trend.ineligible_count")

    def test_filtered_trend_count_against_its_source_comparisons(self):
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = report(filtered_comparisons=filtered)

        def more(summary):
            summary["total_comparisons"] = 4
            summary["eligible_count"] = 4
        changed = self.tampered(built, "filtered_trend", more)
        self.assert_codes(
            self.errors_of(changed, filtered_comparisons=filtered),
            "inconsistent_comparison_count:filtered_trend.total_comparisons",
            "inconsistent_comparison_count:filtered_trend.eligible_count")


# ----------------------------------------------------------------------
# 5. inconsistent numeric trend state
# ----------------------------------------------------------------------
class InconsistentNumericTrendStateTests(Prompt528TestCase):

    def setUp(self):
        self.history = _history((1, 2))
        self.comparisons = _consecutive(self.history)
        self.built = report(snapshots=self.history, comparisons=self.comparisons)

    def test_trend_state_contradicting_the_comparison(self):
        # Start/end swapped and the state and delta made to agree with
        # them: only the comparison shows it is wrong.
        changed = self.tampered(
            self.built, "trend",
            _set_numeric("total_evaluations", state="decreased", start=2, end=1, delta=-1))
        errors = self.errors_of(changed)
        self.assert_codes(
            errors, "inconsistent_numeric_trend_state:total_evaluations",
            "metric_mismatch:trend_start_vs_comparison:total_evaluations",
            "metric_mismatch:trend_vs_comparison:total_evaluations")
        self.assert_codes(
            self.errors_of(changed, comparisons=self.comparisons),
            "inconsistent_numeric_trend_state:total_evaluations")

    def test_state_alone_wrong(self):
        changed = self.tampered(self.built, "trend", _set_numeric("accepted_count", state="unchanged"))
        self.assert_codes(self.errors_of(changed), "inconsistent_numeric_trend_state:accepted_count")

    def test_rate_state_is_judged_too(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_stats(3))
        history.record_statistics(_stats(3))
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assert_valid(built)
        changed = self.tampered(built, "trend", _set_numeric("acceptance_rate", state="increased"))
        self.assert_codes(self.errors_of(changed), "inconsistent_numeric_trend_state:acceptance_rate")

    def test_state_that_only_the_source_comparisons_contradict(self):
        changed = self.tampered(
            self.built, "trend",
            _set_numeric("total_evaluations", state="decreased", start=2, end=1, delta=-1))
        errors = self.errors_of(changed, comparisons=self.comparisons)
        self.assertIn("inconsistent_numeric_trend_state:total_evaluations", errors)

    def test_insufficient_data_state_although_comparisons_are_eligible(self):
        changed = self.tampered(
            self.built, "trend",
            _set_numeric("rejected_count", state="insufficient_data", start=None, end=None, delta=None))
        self.assertEqual(self.errors_of(changed), ["inconsistent_numeric_trend_state:rejected_count"])

    def test_value_at_the_comparisons_earlier_snapshot_must_agree(self):
        changed = self.tampered(self.built, "trend", _set_numeric(
            "total_evaluations", state="increased", start=0, end=2, delta=2))
        errors = self.errors_of(changed)
        self.assertIn("metric_mismatch:trend_start_vs_comparison:total_evaluations", errors)

    def test_trend_over_a_longer_span_is_not_held_to_the_latest_comparisons_state(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(built["trend"]["summary"]["numeric"]["total_evaluations"]["start"], 1)
        self.assert_valid(built, snapshots=history, comparisons=comparisons)

    def test_filtered_numeric_state_against_source_comparisons(self):
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = report(filtered_comparisons=filtered)
        changed = self.tampered(
            built, "filtered_trend",
            _set_numeric("total_evaluations", state="decreased", start=9, end=1, delta=-8))
        self.assert_codes(
            self.errors_of(changed, filtered_comparisons=filtered),
            "inconsistent_numeric_trend_state:filtered_trend.total_evaluations")


# ----------------------------------------------------------------------
# 6. inconsistent categorical trend state
# ----------------------------------------------------------------------
class InconsistentCategoricalTrendStateTests(Prompt528TestCase):

    def setUp(self):
        self.history = _history((1, 2))
        self.comparisons = _consecutive(self.history)
        self.built = report(snapshots=self.history, comparisons=self.comparisons)

    def test_dominant_rejection_reason_state_contradicting_the_comparison(self):
        def mutate(summary):
            summary["dominant_rejection_reason"] = {
                "state": "changed", "start": "rejected_irrelevant", "end": "rejected_low_reliability"}
        changed = self.tampered(self.built, "trend", mutate)
        errors = self.errors_of(changed)
        self.assert_codes(
            errors, "inconsistent_categorical_trend_state:dominant_rejection_reason",
            "metric_mismatch:trend_start_vs_comparison:dominant_rejection_reason")
        self.assert_codes(
            self.errors_of(changed, comparisons=self.comparisons),
            "inconsistent_categorical_trend_state:dominant_rejection_reason")

    def test_dominant_rejection_reason_state_alone_wrong(self):
        def mutate(summary):
            summary["dominant_rejection_reason"] = {"state": "became_available", "start": None, "end": None}
        changed = self.tampered(self.built, "trend", mutate)
        self.assert_codes(
            self.errors_of(changed), "inconsistent_categorical_trend_state:dominant_rejection_reason")

    def test_validation_status_end_contradicting_the_latest_comparison(self):
        def mutate(summary):
            summary["validation_status"] = {"state": "changed", "start": "valid", "end": "invalid"}
        changed = self.tampered(self.built, "trend", mutate)
        self.assertEqual(
            self.errors_of(changed), ["inconsistent_categorical_trend_state:validation_status"])
        self.assert_codes(
            self.errors_of(changed, comparisons=self.comparisons),
            "inconsistent_categorical_trend_state:validation_status")

    def test_validation_status_of_an_ineligible_latest_comparison(self):
        history = _history()
        comparisons = _consecutive(history)
        comparisons[-1] = _ineligible(comparisons[-1])
        built = report(snapshots=history, comparisons=comparisons)
        self.assert_valid(built, comparisons=comparisons)
        self.assertEqual(built["trend"]["summary"]["validation_status"]["end"], "invalid")

        def mutate(summary):
            summary["validation_status"] = {"state": "unchanged", "start": "valid", "end": "valid"}
        changed = self.tampered(built, "trend", mutate)
        self.assert_codes(
            self.errors_of(changed), "inconsistent_categorical_trend_state:validation_status")

    def test_insufficient_validation_status_although_comparisons_exist(self):
        def mutate(summary):
            summary["validation_status"] = {"state": "insufficient_data", "start": None, "end": None}
        changed = self.tampered(self.built, "trend", mutate)
        self.assertEqual(
            self.errors_of(changed), ["inconsistent_categorical_trend_state:validation_status"])

    def test_filtered_categorical_state_against_source_comparisons(self):
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = report(filtered_comparisons=filtered)

        def mutate(summary):
            summary["categorical"]["comparison_changes"]["state"] = "unchanged"
        changed = self.tampered(built, "filtered_trend", mutate)
        self.assert_codes(
            self.errors_of(changed, filtered_comparisons=filtered),
            "inconsistent_categorical_trend_state:filtered_trend.comparison_changes")

    def test_filtered_validation_status_against_source_comparisons(self):
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = report(filtered_comparisons=filtered)

        def mutate(summary):
            summary["validation_status"] = {"state": "changed", "start": "valid", "end": "invalid"}
        changed = self.tampered(built, "filtered_trend", mutate)
        self.assert_codes(
            self.errors_of(changed, filtered_comparisons=filtered),
            "inconsistent_categorical_trend_state:filtered_trend.validation_status")


# ----------------------------------------------------------------------
# 7. empty / sparse / zero-evaluation data
# ----------------------------------------------------------------------
class EmptyAndZeroEvaluationTests(Prompt528TestCase):

    def test_empty_report_is_valid(self):
        built = report()
        self.assert_valid(built)
        self.assert_valid(built, snapshots=None, comparisons=None, trend_summary=None)

    def test_empty_comparisons_and_provided_empty_trend_are_valid(self):
        built = report(comparisons=[], trend_summary=summarize([]))
        self.assert_valid(built)
        self.assert_valid(built, comparisons=[], trend_summary=summarize([]))

    def test_empty_trend_over_no_comparisons_is_consistent(self):
        empty = summarize([])
        self.assertEqual((empty["total_comparisons"], empty["eligible_count"]), (0, 0))
        built = report(trend_summary=empty)
        self.assert_valid(built)

    def test_states_claimed_with_nothing_eligible(self):
        built = report(trend_summary=summarize([]))
        changed = self.tampered(built, "trend", _set_numeric(
            "total_evaluations", state="increased", start=1, end=2, delta=1))
        self.assertEqual(self.errors_of(changed), ["inconsistent_numeric_trend_state:total_evaluations"])

        def reason(summary):
            summary["dominant_rejection_reason"] = {"state": "unchanged", "start": None, "end": None}
        self.assertEqual(
            self.errors_of(self.tampered(built, "trend", reason)),
            ["inconsistent_categorical_trend_state:dominant_rejection_reason"])

        def status(summary):
            summary["validation_status"] = {"state": "unchanged", "start": "valid", "end": "valid"}
        self.assertEqual(
            self.errors_of(self.tampered(built, "trend", status)),
            ["inconsistent_categorical_trend_state:validation_status"])

    def test_sparse_report_with_only_snapshots_is_valid(self):
        history = _history((1, 2))
        built = report(snapshots=history)
        self.assert_valid(built, snapshots=history)

    def test_sparse_report_with_only_a_comparison_is_valid(self):
        comparisons = _consecutive(_history((1, 2)))
        built = report(comparisons=comparisons)
        self.assert_valid(built, comparisons=comparisons)

    def test_zero_evaluation_snapshots_are_consistent(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_stats(0))
        history.record_statistics(_stats(0))
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(built["trend"]["summary"]["numeric"]["total_evaluations"]["end"], 0)
        self.assert_valid(built)
        self.assert_valid(built, snapshots=history, comparisons=comparisons)

    def test_zero_evaluation_trend_claiming_growth(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_stats(0))
        history.record_statistics(_stats(0))
        built = report(snapshots=history, comparisons=_consecutive(history))
        changed = self.tampered(built, "trend", _set_numeric(
            "total_evaluations", state="increased", start=0, end=3, delta=3))
        self.assert_codes(
            self.errors_of(changed), "inconsistent_numeric_trend_state:total_evaluations")

    def test_zero_evaluation_growing_into_evaluations_is_consistent(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_stats(0))
        history.record_statistics(_stats(4))
        built = report(snapshots=history, comparisons=_consecutive(history))
        self.assertEqual(built["trend"]["summary"]["numeric"]["total_evaluations"]["state"], "increased")
        self.assert_valid(built)

    def test_empty_and_zero_data_is_not_an_error_for_the_filtered_trend(self):
        built = report(filtered_comparisons=[])
        self.assert_valid(built)
        self.assert_valid(built, filtered_comparisons=[])
        built = report(filtered_comparisons=None, filtered_trend_summary=None)
        self.assert_valid(built)

    def test_malformed_trend_pieces_are_skipped_not_raised(self):
        history = _history()
        built = report(snapshots=history, comparisons=_consecutive(history))
        for mutate in (
                lambda s: s.update({"numeric": None}),
                lambda s: s.update({"ineligible_comparisons": "nope"}),
                lambda s: s.update({"total_comparisons": "3"}),
                lambda s: s.update({"chronological_range": None}),
                lambda s: s.update({"validation_status": 7}),
                lambda s: s["numeric"].update({"total_evaluations": None}),
        ):
            changed = self.tampered(built, "trend", mutate)
            result = validate(changed)
            self.assertIn("valid", result)
            result = validate(changed, comparisons=_consecutive(history))
            self.assertIn("valid", result)


# ----------------------------------------------------------------------
# 8. filtered trend consistency
# ----------------------------------------------------------------------
class FilteredTrendConsistencyTests(Prompt528TestCase):

    def setUp(self):
        self.filtered = _filtered_consecutive(_filtered_snapshots())
        self.built = report(filtered_comparisons=self.filtered)

    def test_filtered_trend_is_valid_with_and_without_sources(self):
        self.assert_valid(self.built)
        self.assert_valid(self.built, filtered_comparisons=self.filtered)

    def test_filtered_trend_with_an_ineligible_comparison_is_valid(self):
        for position in (0, 2):
            with self.subTest(ineligible_position=position):
                mixed = list(self.filtered)
                mixed[position] = _ineligible_filtered(mixed[position])
                self.assertFalse(validate_filtered_comparison(mixed[position])["valid"])
                built = report(filtered_comparisons=mixed)
                indices = [e["index"] for e in built["filtered_trend"]["summary"]["ineligible_comparisons"]]
                self.assertEqual(indices, [position])
                self.assert_valid(built)
                self.assert_valid(built, filtered_comparisons=mixed)

    def test_filtered_available_in_index_without_a_comparison(self):
        def phantom(summary):
            summary["numeric"]["total_evaluations"]["available_in"] = [0, 1, 2, 3]
        changed = self.tampered(self.built, "filtered_trend", phantom)
        self.assert_codes(
            self.errors_of(changed),
            "trend_entry_without_comparison:filtered_trend.numeric.total_evaluations.available_in.3")
        self.assert_codes(
            self.errors_of(changed, filtered_comparisons=self.filtered),
            "trend_entry_without_comparison:filtered_trend.numeric.total_evaluations.available_in.3")

    def test_filtered_available_in_index_missing_for_a_comparison(self):
        def drop(summary):
            summary["numeric"]["accepted_count"]["available_in"] = [0, 1]
        changed = self.tampered(self.built, "filtered_trend", drop)
        self.assert_codes(
            self.errors_of(changed, filtered_comparisons=self.filtered),
            "missing_trend_entry:filtered_trend.numeric.accepted_count.available_in.2")

    def test_filtered_categorical_available_in_against_sources(self):
        def add(summary):
            summary["categorical"]["trend"]["available_in"] = [0, 1, 2, 7]
        changed = self.tampered(self.built, "filtered_trend", add)
        self.assert_codes(
            self.errors_of(changed, filtered_comparisons=self.filtered),
            "trend_entry_without_comparison:filtered_trend.categorical.trend.available_in.7")

    def test_filtered_ineligible_comparison_missing_from_the_trend(self):
        mixed = list(self.filtered)
        mixed[1] = _ineligible_filtered(mixed[1])
        built = report(filtered_comparisons=mixed)

        def forget(summary):
            summary["eligible_count"] = 3
            summary["ineligible_count"] = 0
            summary["ineligible_comparisons"] = []
        changed = self.tampered(built, "filtered_trend", forget)
        self.assert_codes(
            self.errors_of(changed, filtered_comparisons=mixed),
            "missing_trend_entry:filtered_trend.ineligible_comparisons.1")

    def test_filtered_states_with_nothing_eligible(self):
        broken = [_ineligible_filtered(c) for c in self.filtered]
        built = report(filtered_comparisons=broken)
        self.assertEqual(built["filtered_trend"]["summary"]["eligible_count"], 0)
        self.assert_valid(built)

        def claim(summary):
            summary["numeric"]["total_evaluations"].update(
                {"state": "increased", "start": 1, "end": 9, "delta": 8})
            summary["categorical"]["trend"]["state"] = "changed"
        changed = self.tampered(built, "filtered_trend", claim)
        self.assert_codes(
            self.errors_of(changed),
            "inconsistent_numeric_trend_state:filtered_trend.total_evaluations",
            "inconsistent_categorical_trend_state:filtered_trend.trend")

    def test_filtered_trend_not_judged_against_the_regular_comparison(self):
        # Different lineages: two filtered comparisons, three regular ones.
        history = _history()
        comparisons = _consecutive(history)
        filtered = _filtered_consecutive(_filtered_snapshots((1, 2, 5)))
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assertEqual(built["filtered_trend"]["summary"]["total_comparisons"], 2)
        self.assertEqual(built["comparison"]["total_considered"], 3)
        self.assert_valid(built)
        self.assert_valid(built, snapshots=history, comparisons=comparisons,
                          filtered_comparisons=filtered)

    def test_filtered_trend_already_declared_invalid_is_not_reported_twice(self):
        filtered = self.filtered
        bad_trend = copy.deepcopy(summarize_filtered(filtered))
        bad_trend["total_comparisons"] = 9
        bad_trend["eligible_count"] = 9
        built = report(filtered_comparisons=filtered, filtered_trend_summary=bad_trend)
        self.assertFalse(built["filtered_trend_validation"]["result"]["valid"])
        self.assert_valid(built, filtered_comparisons=filtered, filtered_trend_summary=bad_trend)


# ----------------------------------------------------------------------
# 9. behaviour that must not change
# ----------------------------------------------------------------------
class UnchangedBehaviourTests(Prompt528TestCase):

    def test_trend_already_declared_invalid_is_not_reported_twice(self):
        history = _history()
        comparisons = _consecutive(history)
        bad_trend = summarize(comparisons)
        bad_trend["total_comparisons"] = 9
        bad_trend["eligible_count"] = 9
        built = report(snapshots=history, comparisons=comparisons, trend_summary=bad_trend)
        self.assertFalse(built["trend_validation"]["result"]["valid"])
        self.assert_valid(built)
        self.assert_valid(built, snapshots=history, comparisons=comparisons, trend_summary=bad_trend)

    def test_validation_never_mutates_or_repairs(self):
        history = _history()
        comparisons = _consecutive(history)
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        changed = self.tampered(built, "trend", _set_numeric(
            "total_evaluations", state="decreased", start=8, end=1, delta=-7))
        report_before = copy.deepcopy(changed)
        comparisons_before = copy.deepcopy(comparisons)
        filtered_before = copy.deepcopy(filtered)
        validate(changed, snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assertEqual(changed, report_before)
        self.assertEqual(comparisons, comparisons_before)
        self.assertEqual(filtered, filtered_before)

    def test_validation_is_deterministic(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons, trend_summary=summarize(comparisons))
        changed = self.tampered(built, "trend", lambda s: s.update(
            {"total_comparisons": 5, "eligible_count": 5}))
        first = validate(changed, comparisons=comparisons)
        second = validate(copy.deepcopy(changed), comparisons=copy.deepcopy(comparisons))
        self.assertEqual(first, second)
        self.assertFalse(first["valid"])

    def test_consistency_errors_do_not_make_the_report_malformed(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons, trend_summary=summarize(comparisons))
        changed = self.tampered(built, "trend", lambda s: s.update(
            {"total_comparisons": 5, "eligible_count": 5}))
        result = validate(changed)
        self.assertFalse(result["valid"])
        self.assertEqual(result["warnings"], [])

    def test_selected_sections_validation_is_unaffected(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        selected = {"requested_sections": ["trend", "comparison"], "included_sections": ["trend", "comparison"],
                    "unavailable_sections": [], "unknown_sections": []}
        self.assert_valid(built, selected_sections=selected)


if __name__ == "__main__":
    unittest.main()
