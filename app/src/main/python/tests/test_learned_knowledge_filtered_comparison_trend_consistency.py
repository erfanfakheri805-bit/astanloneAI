"""
Tests for Prompt 536 - Validate Filtered Comparison and Trend Consistency.

`validate_learned_knowledge_filtered_comparison_trend_consistency()`
(learning/learned_knowledge_statistics.py) is a deterministic, read-only
check of whether a filtered diagnostic trend summary (Prompt 520
`summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend()`)
is consistent with the ordered filtered comparisons (Prompt 519
`compare_learned_knowledge_filtered_summary_snapshots()` results) it
claims to summarize.

It reuses the existing filtered comparison and filtered trend systems -
the Prompt 520 summarizer (to recompute what the comparisons actually
produce) and the Prompt 521 validator (for the trend summary's own
internal well-formedness) - together with the existing Prompt 528
per-entry comparator, rather than any new metric, score, or
recomputation logic of its own. It never repairs or mutates either
argument, and it assigns no score, rank, or prediction.

Covers:
    1.  valid comparison/trend data
    2.  missing comparison (a real comparison the trend does not account for)
    3.  extra trend entry (a trend entry with no corresponding comparison)
    4.  inconsistent comparison count
    5.  inconsistent numeric trend state
    6.  inconsistent categorical trend state
    7.  empty / zero-evaluation data
    8.  malformed / invalid source
    9.  determinism and non-mutation

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_comparison_trend_consistency -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_gate import (
    STATUS_PASSED, REASON_OK, REASON_NOT_RELEVANT,
    LearnedKnowledgeGateResult, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    LearnedKnowledgeFilteredSummarySnapshotHistory,
    TREND_DECREASED,
    CHANGE_CHANGED,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
    compare_learned_knowledge_filtered_summary_snapshots as compare,
    summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend as trend,
    validate_learned_knowledge_filtered_comparison_trend_consistency as check,
)

_SMALL = ["evaluation_counts", "rates", "dominant_rejection_reason"]


def _gtrace(status, reason):
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(status, reason))


_TRACES = {"accepted": _gtrace(STATUS_PASSED, REASON_OK),
           "irrelevant": _gtrace("REJECTED", REASON_NOT_RELEVANT)}


def _stats(**counts):
    stats = LearnedKnowledgeDecisionStatistics()
    for name, count in counts.items():
        for _ in range(count):
            stats.record(_TRACES[name])
    return stats


def _summary(counts):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for step in ({"accepted": 1}, counts):
        history.record_statistics(_stats(**step))
    comparisons = [history.compare_sequences(1, 2)]
    built = report(snapshots=history, comparisons=comparisons)
    return fmt(built, validate(built, snapshots=history, comparisons=comparisons))


def _snapshots(specs):
    """Real Prompt 517 snapshots (sequences 1..n) from ONE history;
    `specs` is `[(sections, counts), ...]`."""
    history = LearnedKnowledgeFilteredSummarySnapshotHistory()
    return [history.record_filtered_summary(filt(_summary(counts), sections))
            for sections, counts in specs]


def _chain(specs):
    snaps = _snapshots(specs)
    return snaps, [compare(snaps[i], snaps[i + 1]) for i in range(len(snaps) - 1)]


def _numeric_specs(totals, sections=_SMALL):
    return [(sections, {"accepted": n}) for n in totals]


class ValidDataTests(unittest.TestCase):
    def test_01_valid_comparison_and_trend_data(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class MissingComparisonTests(unittest.TestCase):
    def test_02_missing_comparison(self):
        # The trend was built from only the first comparison; a second,
        # real comparison exists but nothing in the trend accounts for it.
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps[:1])
        result = check(comps, summary)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertIn("inconsistent_comparison_count:filtered_trend.total_comparisons", result["errors"])
        self.assertTrue(any(e.startswith("missing_trend_entry:") for e in result["errors"]))


class ExtraTrendEntryTests(unittest.TestCase):
    def test_03_extra_trend_entry(self):
        # The trend claims a comparison at index 1 is eligible, but that
        # comparison is actually invalid - it has no corresponding
        # eligible comparison to back it.
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        swapped = list(comps)
        swapped[1] = {"valid": False, "errors": ["forced_invalid"]}
        result = check(swapped, summary)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertTrue(any(e.startswith("extra_trend_entry:") for e in result["errors"]))

    def test_03b_trend_entry_without_comparison(self):
        # The trend was built from two comparisons but only one real
        # comparison is actually given - index 1 names a comparison that
        # does not exist at all.
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps[:1], summary)
        self.assertFalse(result["valid"])
        self.assertTrue(any(e.startswith("trend_entry_without_comparison:") for e in result["errors"]))


class InconsistentCountTests(unittest.TestCase):
    def test_04_inconsistent_comparison_count(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = copy.deepcopy(trend(comps))
        summary["total_comparisons"] = 99
        summary["ineligible_comparisons"] = []
        result = check(comps, summary)
        self.assertFalse(result["valid"])
        # A total that disagrees with its own eligible/ineligible counts
        # is caught by the trend's own well-formedness check first.
        self.assertFalse(result["well_formed"])


class InconsistentNumericTrendStateTests(unittest.TestCase):
    def test_05_inconsistent_numeric_trend_state(self):
        _, increasing = _chain(_numeric_specs([1, 2, 3]))
        _, decreasing = _chain(_numeric_specs([3, 2, 1]))
        reported = trend(increasing)
        result = check(decreasing, reported)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertIn("inconsistent_numeric_trend_state:filtered_trend.total_evaluations", result["errors"])

    def test_05b_self_inconsistent_numeric_state_still_reported(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = copy.deepcopy(trend(comps))
        summary["numeric"]["total_evaluations"]["state"] = TREND_DECREASED
        result = check(comps, summary)
        self.assertFalse(result["valid"])
        self.assertIn("inconsistent_numeric_trend_state:total_evaluations", result["errors"])


class InconsistentCategoricalTrendStateTests(unittest.TestCase):
    def test_06_inconsistent_categorical_trend_state(self):
        _, comps = _chain([(_SMALL, {"irrelevant": 2}), (_SMALL, {"irrelevant": 3})])
        summary = copy.deepcopy(trend(comps))
        summary["categorical"]["dominant_rejection_reason"]["state"] = CHANGE_CHANGED
        result = check(comps, summary)
        self.assertFalse(result["valid"])
        self.assertTrue(any(
            e.startswith("inconsistent_") and "dominant_rejection_reason" in e for e in result["errors"]))


class EmptyAndZeroEvaluationTests(unittest.TestCase):
    def test_07_empty_comparisons_and_empty_trend(self):
        result = check([], trend([]))
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_07b_none_comparisons_treated_as_empty(self):
        result = check(None, trend([]))
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_07c_zero_evaluation_comparisons(self):
        _, comps = _chain([(_SMALL, {}), (_SMALL, {})])
        summary = trend(comps)
        result = check(comps, summary)
        self.assertTrue(result["valid"])

    def test_07d_all_comparisons_invalid(self):
        comps = [compare({"snapshot_id": "x"}, {"snapshot_id": "y"}), {}, None, "junk"]
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class InvalidSourceTests(unittest.TestCase):
    def test_08_non_list_comparisons_is_reported(self):
        result = check("not-a-list", trend([]))
        self.assertFalse(result["valid"])
        self.assertIn("invalid_source:comparisons", result["errors"])

    def test_08b_malformed_trend_summary_short_circuits(self):
        result = check([], "not-a-dict")
        self.assertFalse(result["valid"])
        self.assertFalse(result["well_formed"])
        self.assertIn("trend_summary_not_a_dict", result["errors"])

    def test_08c_malformed_trend_summary_not_cross_checked(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        result = check(comps, {"valid": True})
        self.assertFalse(result["valid"])
        self.assertFalse(result["well_formed"])
        self.assertTrue(all(not e.startswith("inconsistent_comparison_count:") for e in result["errors"]))


class DeterminismAndMutationTests(unittest.TestCase):
    def test_09_deterministic_repeated_validation(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        self.assertEqual(check(comps, summary), check(comps, summary))

    def test_09b_does_not_mutate_trend_summary_or_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        comps_copy, summary_copy = copy.deepcopy(comps), copy.deepcopy(summary)
        check(comps, summary)
        self.assertEqual(comps, comps_copy)
        self.assertEqual(summary, summary_copy)


if __name__ == "__main__":
    unittest.main()
