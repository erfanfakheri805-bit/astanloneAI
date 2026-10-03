"""
Tests for Prompt 538 - Validate Filtered Trend Source Integrity.

`validate_learned_knowledge_filtered_trend_source_integrity()`
(learning/learned_knowledge_statistics.py) is a deterministic, read-only
check of whether every source comparison a filtered diagnostic trend
summary (Prompt 520
`summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend()`)
relies on (its eligible positions) actually exists and is independently
valid.

It reuses the existing filtered trend and comparison validation systems -
the Prompt 536/537 consistency check
(`validate_learned_knowledge_filtered_comparison_trend_consistency`) for
the base envelope, and the Prompt 519 comparison validator
(`validate_learned_knowledge_filtered_summary_snapshot_comparison`) to
judge each eligible source comparison on its own - rather than any new
metric, score, or recomputation logic of its own. It never repairs or
mutates either argument, and it assigns no score, rank, or prediction.

Covers:
    1.  valid trend with valid sources
    2.  missing source comparison
    3.  malformed source comparison
    4.  invalid source comparison
    5.  trend incorrectly marked valid despite an invalid source
    6.  empty trend
    7.  zero-evaluation trend
    8.  ineligible sources need no integrity error
    9.  invalid/malformed `comparisons` argument, non-well-formed trend
    10. determinism and non-mutation

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_integrity -v
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
    validate_learned_knowledge_filtered_summary_snapshot_comparison as validate_comparison,
    validate_learned_knowledge_filtered_trend_source_integrity as check,
    COMPARISON_DIRECTION,
)

# A structurally well-formed but independently INVALID filtered
# comparison: both sources are recorded as invalid, so the comparison
# itself is a well-formed "invalid" shape (Prompt 519's own invalid
# branch), not a malformed one.
_INVALID_COMPARISON = {
    "valid": False,
    "direction": COMPARISON_DIRECTION,
    "errors": ["earlier_snapshot_invalid", "later_snapshot_invalid"],
    "invalid_inputs": ["earlier", "later"],
    "earlier_errors": ["snapshot_missing"],
    "later_errors": ["snapshot_missing"],
    "earlier_validation_information": None,
    "later_validation_information": None,
}

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


class ValidSourcesTests(unittest.TestCase):
    def test_01_valid_trend_with_valid_sources(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class MissingSourceComparisonTests(unittest.TestCase):
    def test_02_missing_source_comparison(self):
        # The trend was built with two comparisons eligible, but the
        # second one is simply not there when re-checked.
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check([comps[0], None], summary)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertIn("missing_source_comparison:filtered_trend.1", result["errors"])
        self.assertIn("trend_marked_valid_with_invalid_source:filtered_trend.1", result["errors"])

    def test_02b_source_comparison_out_of_range(self):
        # Only one real comparison is given, but the trend was built
        # from two - the second eligible position does not exist at all.
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps[:1], summary)
        self.assertFalse(result["valid"])
        self.assertIn("missing_source_comparison:filtered_trend.1", result["errors"])


class MalformedSourceComparisonTests(unittest.TestCase):
    def test_03_malformed_source_comparison(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        malformed = ["not-a-comparison-dict", comps[1]]
        result = check(malformed, summary)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertIn("malformed_source_comparison:filtered_trend.0", result["errors"])
        self.assertIn("trend_marked_valid_with_invalid_source:filtered_trend.0", result["errors"])

    def test_03b_structurally_malformed_dict(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        broken = [{"valid": True}, comps[1]]
        result = check(broken, summary)
        self.assertFalse(result["valid"])
        self.assertIn("malformed_source_comparison:filtered_trend.0", result["errors"])


class InvalidSourceComparisonTests(unittest.TestCase):
    def test_04_invalid_source_comparison(self):
        # Sanity: the fixture is well-formed but not valid.
        sanity = validate_comparison(_INVALID_COMPARISON)
        self.assertTrue(sanity["well_formed"])
        self.assertFalse(sanity["valid"])

        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        forced_invalid = copy.deepcopy(comps)
        forced_invalid[0] = _INVALID_COMPARISON
        result = check(forced_invalid, summary)
        self.assertFalse(result["valid"])
        self.assertIn("invalid_source_comparison:filtered_trend.0", result["errors"])
        self.assertIn("trend_marked_valid_with_invalid_source:filtered_trend.0", result["errors"])


class TrendIncorrectlyMarkedValidTests(unittest.TestCase):
    def test_05_trend_marked_valid_despite_invalid_source(self):
        # The trend summary itself declares "valid": True (its own
        # Prompt 521 well-formedness), yet a comparison it relies on is
        # actually unusable - source integrity must flag that
        # combination explicitly, not just the underlying problem.
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = copy.deepcopy(trend(comps))
        self.assertTrue(summary["valid"])
        result = check([None, comps[1]], summary)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any(e.startswith("trend_marked_valid_with_invalid_source:") for e in result["errors"]))

    def test_05b_missing_source_still_reported_even_when_not_flagged_as_marked_valid(self):
        # The dedicated "marked valid" code is additive: the underlying
        # missing/malformed/invalid source code is always reported on
        # its own, whether or not the trend also happens to read valid.
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check([None, comps[1]], summary)
        self.assertIn("missing_source_comparison:filtered_trend.0", result["errors"])


class EmptyTrendTests(unittest.TestCase):
    def test_06_empty_trend(self):
        result = check([], trend([]))
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_06b_none_comparisons_treated_as_empty(self):
        result = check(None, trend([]))
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class ZeroEvaluationTrendTests(unittest.TestCase):
    def test_07_zero_evaluation_trend(self):
        _, comps = _chain([(_SMALL, {}), (_SMALL, {})])
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class IneligibleSourceNeedsNoErrorTests(unittest.TestCase):
    def test_08_ineligible_source_is_not_checked(self):
        # A comparison the trend already lists as ineligible is expected
        # to possibly be unusable - that alone is not a source-integrity
        # problem.
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        with_bad = list(comps)
        with_bad[1] = _INVALID_COMPARISON
        summary = trend(with_bad)
        self.assertEqual([entry["index"] for entry in summary["ineligible_comparisons"]], [1])
        result = check(with_bad, summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class InvalidSourceAndNonWellFormedTests(unittest.TestCase):
    def test_09_non_list_comparisons_is_reported(self):
        result = check("not-a-list", trend([]))
        self.assertFalse(result["valid"])
        self.assertIn("invalid_source:comparisons", result["errors"])

    def test_09b_malformed_trend_summary_short_circuits(self):
        result = check([], "not-a-dict")
        self.assertFalse(result["valid"])
        self.assertFalse(result["well_formed"])
        self.assertIn("trend_summary_not_a_dict", result["errors"])
        self.assertTrue(all(not e.startswith("missing_source_comparison:") for e in result["errors"]))

    def test_09c_not_well_formed_trend_not_cross_checked(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        result = check(comps, {"valid": True})
        self.assertFalse(result["valid"])
        self.assertFalse(result["well_formed"])
        self.assertTrue(all(
            not e.startswith("missing_source_comparison:")
            and not e.startswith("malformed_source_comparison:")
            and not e.startswith("invalid_source_comparison:") for e in result["errors"]))


class DeterminismAndMutationTests(unittest.TestCase):
    def test_10_deterministic_repeated_validation(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        self.assertEqual(check(comps, summary), check(comps, summary))

    def test_10b_does_not_mutate_trend_summary_or_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        comps_copy, summary_copy = copy.deepcopy(comps), copy.deepcopy(summary)
        check(comps, summary)
        self.assertEqual(comps, comps_copy)
        self.assertEqual(summary, summary_copy)


if __name__ == "__main__":
    unittest.main()
