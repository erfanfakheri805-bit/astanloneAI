"""
Tests for Prompt 541 - Validate Filtered Trend Source Coverage.

`validate_learned_knowledge_filtered_trend_source_coverage()`
(learning/learned_knowledge_statistics.py) is a deterministic, read-only
summarization layer over the existing Prompt 536/537/538/539/540
filtered trend source checks. It adds no new detection: it calls
`validate_learned_knowledge_filtered_trend_source_consistency()`
(Prompt 540) first, unchanged, for the full `{"valid", "well_formed",
"errors", "warnings"}` envelope and its per-position `"sources"`
breakdown, then collapses that into a single `"state"` - exactly one of
`"complete"`, `"incomplete"`, `"missing_source"`, `"duplicate_source"`,
`"unexpected_source"`, `"invalid_source"`, `"ordering_mismatch"`, or
`"invalid_input"` - chosen by a fixed priority order, plus a
`"coverage"` field that is the Prompt 540 result's own `"sources"`
mapping, unchanged.

It reuses the existing filtered trend, filtered comparison, and
validation structures throughout, creates no second trend or comparison
system, and never repairs, mutates, or silently drops either argument.

Covers:
    1.  empty trend
    2.  one complete source comparison
    3.  multiple complete source comparisons
    4.  missing required source
    5.  duplicated source
    6.  unexpected/unrelated source
    7.  invalid source
    8.  incorrect source count
    9.  ordering mismatch (reversed comparisons)
    10. inconsistent earlier/later snapshot relationship
    11. mixed valid and invalid sources
    12. deterministic validation result / non-mutation

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_coverage -v
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
    validate_learned_knowledge_filtered_trend_source_coverage as check,
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


class EmptyTrendTests(unittest.TestCase):
    def test_01_empty_trend(self):
        result = check([], trend([]))
        self.assertEqual(result, {
            "valid": True, "well_formed": True, "state": "complete",
            "errors": [], "warnings": [], "coverage": {},
        })

    def test_01b_none_comparisons_treated_as_empty(self):
        result = check(None, trend([]))
        self.assertEqual(result, {
            "valid": True, "well_formed": True, "state": "complete",
            "errors": [], "warnings": [], "coverage": {},
        })


class OneCompleteSourceComparisonTests(unittest.TestCase):
    def test_02_one_complete_source_comparison(self):
        _, comps = _chain(_numeric_specs([1, 2]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(result, {
            "valid": True, "well_formed": True, "state": "complete",
            "errors": [], "warnings": [], "coverage": {0: "valid"},
        })


class MultipleCompleteSourceComparisonsTests(unittest.TestCase):
    def test_03_multiple_complete_source_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(result, {
            "valid": True, "well_formed": True, "state": "complete",
            "errors": [], "warnings": [],
            "coverage": {0: "valid", 1: "valid", 2: "valid"},
        })


class MissingRequiredSourceTests(unittest.TestCase):
    def test_04_missing_required_source(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check([comps[0], None], summary)
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "missing_source")
        self.assertTrue(result["well_formed"])
        self.assertIn("missing_source_comparison:filtered_trend.1", result["errors"])
        self.assertEqual(result["coverage"], {0: "valid", 1: "missing"})


class DuplicatedSourceTests(unittest.TestCase):
    def test_05_duplicated_source(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check([comps[0], comps[0]], summary)
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "duplicate_source")
        self.assertEqual(result["coverage"], {0: "valid", 1: "duplicated"})

    def test_05b_no_duplicate_among_distinct_chained_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(result["state"], "complete")


class UnexpectedUnrelatedSourceTests(unittest.TestCase):
    def test_06_unexpected_unrelated_source(self):
        # comps[0] is snapshot 1 -> 2; comps[2] is snapshot 3 -> 4. Using
        # them as consecutive eligible positions skips comps[1]'s
        # snapshot entirely - comps[2] does not belong there.
        _, comps = _chain(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps[:2])
        result = check([comps[0], comps[2]], summary)
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "unexpected_source")
        self.assertEqual(result["coverage"], {0: "valid", 1: "ordering_mismatch"})

    def test_06b_no_unexpected_flag_among_distinct_chained_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(result["state"], "complete")


class InvalidSourceTests(unittest.TestCase):
    def test_07_invalid_source(self):
        sanity = validate_comparison(_INVALID_COMPARISON)
        self.assertTrue(sanity["well_formed"])
        self.assertFalse(sanity["valid"])

        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        forced_invalid = copy.deepcopy(comps)
        forced_invalid[0] = _INVALID_COMPARISON
        result = check(forced_invalid, summary)
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "invalid_source")
        self.assertEqual(result["coverage"][0], "invalid_source")


class IncorrectSourceCountTests(unittest.TestCase):
    def test_08_incorrect_source_count_too_few(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps[:1], summary)
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "missing_source")
        self.assertTrue(
            any(e.startswith("inconsistent_comparison_count:") for e in result["errors"]))

    def test_08b_incorrect_source_count_too_many(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps[:1])
        result = check(comps, summary)
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "incomplete")


class OrderingMismatchTests(unittest.TestCase):
    def test_09_ordering_mismatch_reversed_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(list(reversed(comps)), summary)
        self.assertFalse(result["valid"])
        self.assertIn(result["state"], ("unexpected_source", "ordering_mismatch"))
        self.assertTrue(
            any(e.startswith("inconsistent_trend_chronology:") for e in result["errors"]))


class InconsistentEarlierLaterRelationshipTests(unittest.TestCase):
    def test_10_inconsistent_earlier_later_snapshot_relationship(self):
        # comps[1]'s own "earlier" identity keeps the right snapshot id
        # (so the chain still "connects" to comps[0]'s "later") but
        # disagrees about its sequence number.
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        tampered = copy.deepcopy(comps)
        tampered[1]["earlier"]["sequence"] = 1
        sanity = validate_comparison(tampered[1])
        self.assertTrue(sanity["well_formed"])
        self.assertTrue(sanity["valid"])

        result = check(tampered, summary)
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "ordering_mismatch")
        self.assertEqual(result["coverage"], {0: "valid", 1: "mismatched"})

    def test_10b_inconsistent_source_id(self):
        _, comps = _chain(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        tampered = copy.deepcopy(comps)
        tampered[2]["later"]["snapshot_id"] = comps[0]["earlier"]["snapshot_id"]
        result = check(tampered, summary)
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "ordering_mismatch")
        self.assertEqual(result["coverage"][2], "mismatched")


class MixedValidAndInvalidSourcesTests(unittest.TestCase):
    def test_11_mixed_valid_and_invalid_sources(self):
        # comps[1] (the middle, chaining snapshot 2 -> 3) is replaced
        # with an independently invalid comparison. The two remaining
        # clean positions (0 and 2) no longer connect to each other -
        # the invalid source is the more specific, higher-priority
        # problem, so it wins over the resulting unexpected_source.
        _, comps = _chain(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        mixed = [comps[0], _INVALID_COMPARISON, comps[2]]
        result = check(mixed, summary)
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "invalid_source")
        self.assertEqual(
            result["coverage"],
            {0: "valid", 1: "invalid_source", 2: "ordering_mismatch"})
        self.assertEqual(result, check(mixed, summary))

    def test_11b_empty_and_zero_data_trends_stay_complete(self):
        result = check([], trend([]))
        self.assertTrue(result["valid"])
        self.assertEqual(result["state"], "complete")
        self.assertEqual(result["coverage"], {})


class DeterminismAndMutationTests(unittest.TestCase):
    def test_12_deterministic_repeated_validation(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        self.assertEqual(check(comps, summary), check(comps, summary))

    def test_12b_deterministic_on_invalid_input(self):
        _, comps = _chain(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        result = check([comps[0], comps[0]], summary)
        self.assertEqual(result, check([comps[0], comps[0]], summary))

    def test_12c_does_not_mutate_trend_summary_or_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        comps_copy, summary_copy = copy.deepcopy(comps), copy.deepcopy(summary)
        check(comps, summary)
        self.assertEqual(comps, comps_copy)
        self.assertEqual(summary, summary_copy)

    def test_12d_invalid_comparisons_type_reported_as_invalid_input(self):
        result = check("not-a-list", trend([]))
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "invalid_input")
        self.assertIn("invalid_source:comparisons", result["errors"])
        self.assertEqual(result["coverage"], {})

    def test_12e_not_well_formed_trend_reported_as_invalid_input(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        result = check(comps, {"valid": True})
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "invalid_input")
        self.assertFalse(result["well_formed"])
        self.assertEqual(result["coverage"], {})

    def test_12f_result_shape_has_exactly_the_expected_keys(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(
            set(result.keys()),
            {"valid", "well_formed", "state", "errors", "warnings", "coverage"})

    def test_12g_state_is_always_one_of_the_documented_values(self):
        from learning.learned_knowledge_statistics import (
            _FILTERED_TREND_SOURCE_COVERAGE_STATES,
        )
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        for candidate in (
                check([], trend([])),
                check(comps, summary),
                check([comps[0], None], summary),
                check("not-a-list", trend([]))):
            self.assertIn(candidate["state"], _FILTERED_TREND_SOURCE_COVERAGE_STATES)


if __name__ == "__main__":
    unittest.main()
