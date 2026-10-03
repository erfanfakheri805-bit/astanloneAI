"""
Tests for Prompt 537 - Validate Filtered Trend Source Ordering.

`validate_learned_knowledge_filtered_comparison_trend_consistency()`
(learning/learned_knowledge_statistics.py, Prompt 536) already recomputes
what the Prompt 520 summarizer produces from the real filtered
comparisons and compares individual numeric/categorical trend entries
against it. Prompt 537 adds one more targeted comparison on top of that
existing architecture: the declared `"chronology"` block (`"ordered"` /
`"reversed"`) against what recomputing from the real comparisons
actually shows, via `_check_filtered_trend_chronology_against_comparisons()`.
This closes a gap the broader per-entry comparator does not itself
cover - a chronology disagreement that does not happen to surface as a
numeric/categorical state mismatch (every field reading
`"insufficient_data"` either way, or a `"reversed"` entry naming the
wrong pair of positions while the `"ordered"` flag still happens to
agree).

No new metric, ordering rule, or recomputation logic is introduced -
this reuses the existing Prompt 520 summarizer (which already computes
chronology via `_filtered_trend_chronology`) and the existing Prompt 521
validator, exactly as Prompt 536 does. Neither `trend_summary` nor
`comparisons` is ever reordered, repaired, or otherwise changed.

Covers:
    1.  valid chronological trend (in-order comparisons, nothing flagged)
    2.  reversed comparisons (a trend that hides an actual reversal)
    3.  duplicated / conflicting chronological positions in "reversed"
    4.  empty trend (no comparisons at all)
    5.  single-comparison trend (nothing to be out of order)
    6.  missing source comparison (an eligible comparison the trend omits)
    7.  invalid source comparison (a comparison entry that is not valid)

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_chronology -v
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
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
    compare_learned_knowledge_filtered_summary_snapshots as compare,
    summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend as trend,
    validate_learned_knowledge_filtered_comparison_trend_consistency as check,
)

_SECTIONS = ["evaluation_counts", "rates", "dominant_rejection_reason"]

# No sections at all: every numeric/categorical trend field then has an
# empty "available_in" regardless of chronology, so a chronology-only
# tamper never cascades into an unrelated numeric/categorical state
# mismatch - isolating exactly what this prompt adds.
_NO_SECTIONS = []


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


def _snapshots(totals, sections=_SECTIONS):
    """Real Prompt 517 snapshots (sequences 1..n) from ONE history."""
    history = LearnedKnowledgeFilteredSummarySnapshotHistory()
    return [history.record_filtered_summary(filt(_summary({"accepted": n}), sections))
            for n in totals]


def _in_order_comparisons(totals=(1, 2, 3, 4)):
    """`comparisons` in true chronological order: `[c(0,1), c(1,2), ...]`."""
    snaps = _snapshots(totals)
    return [compare(snaps[i], snaps[i + 1]) for i in range(len(snaps) - 1)]


class ValidChronologicalTrendTests(unittest.TestCase):
    def test_01_valid_chronological_trend_is_fully_consistent(self):
        comps = _in_order_comparisons()
        summary = trend(comps)
        self.assertEqual(summary["chronology"], {"ordered": True, "reversed": []})
        result = check(comps, summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class ReversedComparisonsTests(unittest.TestCase):
    def _reordered_comparisons(self):
        """The same real comparisons, fed out of chronological order, so
        the second position actually goes backwards relative to the
        first - a genuine reversal, not a fabricated one. No sections,
        so every numeric/categorical field stays "insufficient_data"
        with no data either way, isolating the chronology check itself."""
        snaps = _snapshots((1, 2, 3, 4), sections=_NO_SECTIONS)
        c01, c12, c23 = (compare(snaps[0], snaps[1]), compare(snaps[1], snaps[2]),
                          compare(snaps[2], snaps[3]))
        return [c12, c01, c23]

    def test_02_reversal_is_reported_by_the_summarizer_itself(self):
        reordered = self._reordered_comparisons()
        summary = trend(reordered)
        self.assertFalse(summary["chronology"]["ordered"])
        self.assertEqual(summary["chronology"]["reversed"], [{"index": 1, "previous_index": 0}])
        # A trend faithfully reporting its own reversal is still consistent.
        result = check(reordered, summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_02b_hidden_reversal_is_detected_against_the_real_comparisons(self):
        # The trend claims the comparisons are in order when the real,
        # given comparisons actually go backwards - the case this prompt
        # exists to catch.
        reordered = self._reordered_comparisons()
        honest = trend(reordered)
        hidden = copy.deepcopy(honest)
        hidden["chronology"] = {"ordered": True, "reversed": []}
        hidden["unavailable"] = [u for u in hidden["unavailable"] if u != "chronology_not_ordered"]
        result = check(reordered, hidden)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertIn("inconsistent_trend_chronology:filtered_trend.chronology.ordered", result["errors"])


class DuplicatedOrConflictingPositionTests(unittest.TestCase):
    def _reversed_trend_and_source(self):
        snaps = _snapshots((1, 2, 3, 4), sections=_NO_SECTIONS)
        c01, c12, c23 = (compare(snaps[0], snaps[1]), compare(snaps[1], snaps[2]),
                          compare(snaps[2], snaps[3]))
        reordered = [c12, c01, c23]
        return reordered, trend(reordered)

    def test_03_duplicated_reversed_entry_is_detected(self):
        reordered, honest = self._reversed_trend_and_source()
        duplicated = copy.deepcopy(honest)
        duplicated["chronology"]["reversed"] = honest["chronology"]["reversed"] * 2
        result = check(reordered, duplicated)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertIn("inconsistent_trend_chronology:filtered_trend.chronology.reversed", result["errors"])

    def test_03b_conflicting_reversed_position_is_detected(self):
        # Still exactly one (non-empty) reversed entry, so the
        # "ordered" flag stays self-consistent, but it names the wrong
        # pair of positions.
        reordered, honest = self._reversed_trend_and_source()
        conflicting = copy.deepcopy(honest)
        conflicting["chronology"]["reversed"] = [{"index": 1, "previous_index": 2}]
        result = check(reordered, conflicting)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertIn("inconsistent_trend_chronology:filtered_trend.chronology.reversed", result["errors"])


class EmptyTrendTests(unittest.TestCase):
    def test_04_empty_comparisons_and_empty_trend(self):
        summary = trend([])
        self.assertEqual(summary["chronology"], {"ordered": True, "reversed": []})
        result = check([], summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_04b_none_comparisons_treated_as_empty(self):
        result = check(None, trend([]))
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class SingleComparisonTrendTests(unittest.TestCase):
    def test_05_single_comparison_trend_is_trivially_ordered(self):
        comps = _in_order_comparisons()[:1]
        summary = trend(comps)
        self.assertEqual(summary["chronology"], {"ordered": True, "reversed": []})
        result = check(comps, summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class MissingSourceComparisonTests(unittest.TestCase):
    def test_06_missing_source_comparison_is_reported(self):
        # The real, given comparisons include a third eligible one that
        # the trend (built from only the first two) does not account for.
        comps = _in_order_comparisons()
        summary = trend(comps[:2])
        result = check(comps, summary)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertIn(
            "inconsistent_comparison_count:filtered_trend.total_comparisons", result["errors"])
        self.assertTrue(any(e.startswith("missing_trend_entry:") for e in result["errors"]))


class InvalidSourceComparisonTests(unittest.TestCase):
    def test_07_invalid_source_comparison_entry_is_reported(self):
        # The trend was built assuming every comparison is eligible, but
        # one of the real, given comparisons is actually invalid.
        comps = _in_order_comparisons()
        summary = trend(comps)
        tampered_source = list(comps)
        tampered_source[1] = {"valid": False, "errors": ["forced_invalid"]}
        result = check(tampered_source, summary)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertTrue(any(e.startswith("extra_trend_entry:") for e in result["errors"]))

    def test_07b_non_list_comparisons_source_is_reported(self):
        result = check("not-a-list", trend([]))
        self.assertFalse(result["valid"])
        self.assertIn("invalid_source:comparisons", result["errors"])


class DeterminismAndMutationTests(unittest.TestCase):
    def test_08_deterministic_repeated_validation(self):
        snaps = _snapshots((1, 2, 3, 4))
        c01, c12, c23 = (compare(snaps[0], snaps[1]), compare(snaps[1], snaps[2]),
                          compare(snaps[2], snaps[3]))
        reordered = [c12, c01, c23]
        summary = trend(reordered)
        self.assertEqual(check(reordered, summary), check(reordered, summary))

    def test_08b_does_not_mutate_trend_summary_or_comparisons(self):
        comps = _in_order_comparisons()
        summary = trend(comps)
        comps_copy, summary_copy = copy.deepcopy(comps), copy.deepcopy(summary)
        check(comps, summary)
        self.assertEqual(comps, comps_copy)
        self.assertEqual(summary, summary_copy)


if __name__ == "__main__":
    unittest.main()
