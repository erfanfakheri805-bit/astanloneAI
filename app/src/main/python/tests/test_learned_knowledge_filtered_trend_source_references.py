"""
Tests for Prompt 539 - Validate Filtered Trend Source References.

`validate_learned_knowledge_filtered_trend_source_references()`
(learning/learned_knowledge_statistics.py) is a deterministic, read-only
check of whether the source comparisons a filtered diagnostic trend
summary (Prompt 520
`summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend()`)
relies on (its eligible positions) form one connected, internally
consistent chain of source comparison references within `comparisons`.

It reuses the existing filtered trend and comparison validation systems
throughout - the Prompt 538 source-integrity check
(`validate_learned_knowledge_filtered_trend_source_integrity`, itself
built on the Prompt 536/537 consistency check and the Prompt 519
comparison validator) for the base envelope and every already-known
reference problem (missing, malformed, invalid, mismatched count,
mismatched ordering), plus four new, additive checks over the *clean*
eligible positions (no Prompt 538 problem) for the remaining reference
problems: duplicated references, references to unrelated comparisons,
inconsistent earlier/later relationships, and inconsistent source ids.
It creates no second trend or comparison system, never repairs or
mutates either argument, and assigns no score, rank, or prediction.

Covers:
    1.  empty trend
    2.  one valid comparison
    3.  multiple valid comparisons
    4.  missing source comparison (inherited from Prompt 538)
    5.  duplicated source comparison
    6.  unrelated comparison
    7.  invalid comparison (inherited from Prompt 538)
    8.  mismatched source ids
    9.  reversed comparison ordering (inherited from Prompt 536/537)
    10. incorrect comparison count (inherited from Prompt 536)
    11. mixed valid and invalid sources
    12. deterministic validation output / non-mutation

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_references -v
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
    validate_learned_knowledge_filtered_trend_source_references as check,
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
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_01b_none_comparisons_treated_as_empty(self):
        result = check(None, trend([]))
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class OneValidComparisonTests(unittest.TestCase):
    def test_02_one_valid_comparison(self):
        # A single eligible comparison has nothing to be compared
        # against - none of the new reference checks can ever fire.
        _, comps = _chain(_numeric_specs([1, 2]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class MultipleValidComparisonsTests(unittest.TestCase):
    def test_03_multiple_valid_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class MissingSourceComparisonTests(unittest.TestCase):
    def test_04_missing_source_comparison_is_inherited(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check([comps[0], None], summary)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertIn("missing_source_comparison:filtered_trend.1", result["errors"])


class DuplicatedSourceReferenceTests(unittest.TestCase):
    def test_05_duplicated_source_comparison(self):
        # Both eligible positions are checked against the SAME
        # underlying source comparison - the second one duplicates the
        # first's (earlier, later) snapshot pair.
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check([comps[0], comps[0]], summary)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertIn("duplicated_source_reference:filtered_trend.1", result["errors"])

    def test_05b_no_duplicate_among_distinct_chained_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertTrue(all(not e.startswith("duplicated_source_reference:") for e in result["errors"]))


class UnrelatedSourceReferenceTests(unittest.TestCase):
    def test_06_unrelated_comparison(self):
        # comps[0] is snapshot 1 -> 2; comps[2] is snapshot 3 -> 4. Using
        # them as consecutive eligible positions skips comps[1]'s
        # snapshot entirely - comps[2] does not continue where comps[0]
        # left off, so it is unrelated to it.
        _, comps = _chain(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps[:2])
        result = check([comps[0], comps[2]], summary)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertIn("unrelated_source_reference:filtered_trend.1", result["errors"])

    def test_06b_no_unrelated_flag_among_distinct_chained_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertTrue(all(not e.startswith("unrelated_source_reference:") for e in result["errors"]))


class InvalidSourceComparisonTests(unittest.TestCase):
    def test_07_invalid_comparison_is_inherited(self):
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


class MismatchedSourceIdTests(unittest.TestCase):
    def test_08_inconsistent_source_id(self):
        # comps chain 1->2->3->4 across three comparisons. comps[2]'s
        # "later" identity is altered to reuse comps[0]'s "earlier"
        # snapshot id but keep its own (different) sequence number - the
        # chain boundaries themselves stay connected, but that snapshot
        # id now claims two different sequence positions.
        _, comps = _chain(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        tampered = copy.deepcopy(comps)
        tampered[2]["later"]["snapshot_id"] = comps[0]["earlier"]["snapshot_id"]
        # Sanity: still a structurally well-formed, independently valid
        # comparison on its own (identity strings carry no uniqueness
        # constraint by themselves).
        sanity = validate_comparison(tampered[2])
        self.assertTrue(sanity["well_formed"])
        self.assertTrue(sanity["valid"])

        result = check(tampered, summary)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertIn("inconsistent_source_id:filtered_trend.2", result["errors"])
        # The chain boundaries around it are untouched, so this is not
        # also reported as an unrelated or earlier/later mismatch.
        self.assertTrue(all(not e.startswith("unrelated_source_reference:") for e in result["errors"]))
        self.assertTrue(all(
            not e.startswith("inconsistent_earlier_later_relationship:") for e in result["errors"]))

    def test_08b_inconsistent_earlier_later_relationship_at_the_boundary(self):
        # comps[1]'s own "earlier" identity keeps the right snapshot id
        # (so the chain still "connects" to comps[0]'s "later") but
        # disagrees about its sequence number.
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        tampered = copy.deepcopy(comps)
        tampered[1]["earlier"]["sequence"] = 1
        # Sanity: still well-formed and independently valid on its own -
        # `earlier.sequence` (1) is still below `later.sequence` (3), so
        # nothing about the comparison's own internal ordering breaks.
        sanity = validate_comparison(tampered[1])
        self.assertTrue(sanity["well_formed"])
        self.assertTrue(sanity["valid"])
        result = check(tampered, summary)
        self.assertFalse(result["valid"])
        self.assertIn(
            "inconsistent_earlier_later_relationship:filtered_trend.1", result["errors"])
        self.assertTrue(all(not e.startswith("unrelated_source_reference:") for e in result["errors"]))


class ReversedComparisonOrderingTests(unittest.TestCase):
    def test_09_reversed_comparison_ordering_is_inherited(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(list(reversed(comps)), summary)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any(e.startswith("inconsistent_trend_chronology:") for e in result["errors"]))


class IncorrectComparisonCountTests(unittest.TestCase):
    def test_10_incorrect_comparison_count_is_inherited(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps[:1], summary)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any(e.startswith("inconsistent_comparison_count:") for e in result["errors"]))


class MixedValidAndInvalidSourcesTests(unittest.TestCase):
    def test_11_mixed_valid_and_invalid_sources(self):
        # comps[1] (the middle, chaining snapshot 2 -> 3) is replaced
        # with an independently invalid comparison. The two remaining
        # clean positions (0 and 2) are then compared directly against
        # each other, and no longer connect - a mixed valid/invalid
        # source list produces a deterministic invalid result covering
        # both problems.
        _, comps = _chain(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        mixed = [comps[0], _INVALID_COMPARISON, comps[2]]
        result = check(mixed, summary)
        self.assertFalse(result["valid"])
        self.assertIn("invalid_source_comparison:filtered_trend.1", result["errors"])
        self.assertIn("unrelated_source_reference:filtered_trend.2", result["errors"])
        self.assertEqual(result, check(mixed, summary))


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

    def test_12d_invalid_comparisons_type_reported_and_no_reference_checks_attempted(self):
        result = check("not-a-list", trend([]))
        self.assertFalse(result["valid"])
        self.assertIn("invalid_source:comparisons", result["errors"])

    def test_12e_not_well_formed_trend_not_cross_checked(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        result = check(comps, {"valid": True})
        self.assertFalse(result["valid"])
        self.assertFalse(result["well_formed"])
        self.assertTrue(all(
            not e.startswith("duplicated_source_reference:")
            and not e.startswith("unrelated_source_reference:")
            and not e.startswith("inconsistent_source_id:")
            and not e.startswith("inconsistent_earlier_later_relationship:") for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
