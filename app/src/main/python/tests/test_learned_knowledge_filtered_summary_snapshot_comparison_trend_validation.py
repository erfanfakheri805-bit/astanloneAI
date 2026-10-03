"""
Tests for Prompt 521 - Validate Filtered Diagnostic Trend Summaries.

`validate_learned_knowledge_filtered_summary_snapshot_comparison_trend()`
(learning/learned_knowledge_statistics.py) is a deterministic, read-only
validator over the dict `summarize_learned_knowledge_filtered_summary_
snapshot_comparison_trend()` (Prompt 520) returns. It follows the same
`{"valid", "well_formed", "errors", "warnings"}` shape as the Prompt 506/
510/512/519 validators: `well_formed` means internally consistent on its
own; `valid` also means it matches its declared source comparisons, when
those are given. It never repairs a trend summary, never mutates
anything it is given, and assigns no score/rank/quality judgement.

Covers:
    1.  fully valid trend summary
    2.  missing required field
    3.  negative source count
    4.  inconsistent valid/invalid counts
    5.  invalid source comparison
    6.  all comparisons invalid
    7.  mixed valid/invalid comparisons
    8.  valid increased trend
    9.  valid decreased trend
    10. valid unchanged trend
    11. valid insufficient-data trend
    12. invalid numeric trend state
    13. inconsistent numeric trend state
    14. valid categorical unchanged
    15. valid categorical changed
    16. valid categorical appeared
    17. valid categorical disappeared
    18. valid categorical insufficient-data
    19. invalid categorical state
    20. inconsistent categorical state
    21. contradictory section availability
    22. missing section data
    23. valid sparse section data
    24. reversed chronology
    25. unavailable chronology
    26. contradictory chronology
    27. zero source comparisons
    28. one source comparison
    29. empty trend summary
    30. deterministic repeated validation
    31. validation does not mutate trend summary
    32. validation does not mutate source comparisons
    33. validation does not mutate snapshots
    34. regression coverage for Prompt 520
    35. regression coverage for existing Prompt 512 behavior

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_summary_snapshot_comparison_trend_validation -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_gate import (
    STATUS_PASSED, REASON_OK, REASON_NOT_RELEVANT, REASON_INSUFFICIENT_RELIABILITY,
    LearnedKnowledgeGateResult, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    LearnedKnowledgeFilteredSummarySnapshotHistory,
    TREND_INCREASED, TREND_DECREASED, TREND_INSUFFICIENT_DATA,
    CHANGE_UNCHANGED, CHANGE_CHANGED, CHANGE_BECAME_EMPTY, CHANGE_BECAME_AVAILABLE,
    AVAILABILITY_CONSISTENT, AVAILABILITY_UNAVAILABLE, AVAILABILITY_INVALID,
    COMPARISON_DIRECTION,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
    compare_learned_knowledge_filtered_summary_snapshots as compare,
    summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend as trend,
    validate_learned_knowledge_filtered_summary_snapshot_comparison_trend as validate_trend,
    summarize_learned_knowledge_diagnostic_snapshot_comparison_trend as trend511,
    validate_learned_knowledge_diagnostic_snapshot_comparison_trend as validate_trend511,
)

_ALL = ["evaluation_counts", "rates", "dominant_rejection_reason",
        "comparison_changes", "trend", "validation_statuses"]
_SMALL = ["evaluation_counts", "rates", "dominant_rejection_reason"]
_NUMERIC = ["total_evaluations", "accepted_count", "rejected_count", "no_candidate_count",
            "acceptance_rate", "rejection_rate"]
_CATEGORICAL = ["dominant_rejection_reason", "comparison_changes", "trend", "validation_statuses"]


def _gtrace(status, reason):
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(status, reason))


_TRACES = {"accepted": _gtrace(STATUS_PASSED, REASON_OK),
           "irrelevant": _gtrace("REJECTED", REASON_NOT_RELEVANT),
           "low_reliability": _gtrace("REJECTED", REASON_INSUFFICIENT_RELIABILITY)}


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


def _invalid_summary():
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record_statistics(_stats(accepted=1))
    built = copy.deepcopy(report(snapshots=history))
    built["structural_status"] = "unknown"
    return fmt(built, validate(built))


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


class EnvelopeTests(unittest.TestCase):
    def test_01_fully_valid_trend_summary(self):
        _, comps = _chain(_numeric_specs([1, 2, 5], _ALL))
        summary = trend(comps)
        result = validate_trend(summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})
        # and with the real comparisons cross-checked too
        result_with_sources = validate_trend(summary, comparisons=comps)
        self.assertEqual(result_with_sources,
                          {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_02_missing_required_field(self):
        _, comps = _chain(_numeric_specs([1, 2]))
        summary = dict(trend(comps))
        del summary["chronology"]
        result = validate_trend(summary)
        self.assertFalse(result["valid"])
        self.assertFalse(result["well_formed"])
        self.assertIn("missing_field:chronology", result["errors"])

    def test_03_negative_source_count(self):
        _, comps = _chain(_numeric_specs([1, 2]))
        summary = dict(trend(comps))
        summary["total_comparisons"] = -1
        result = validate_trend(summary)
        self.assertFalse(result["valid"])
        self.assertIn("invalid_type:total_comparisons", result["errors"])

    def test_04_inconsistent_valid_invalid_counts(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = dict(trend(comps))
        summary["eligible_count"] = summary["eligible_count"] + 1
        result = validate_trend(summary)
        self.assertFalse(result["valid"])
        self.assertIn("inconsistent_comparison_counts", result["errors"])

    def test_05_invalid_source_comparison(self):
        comps = [compare({"snapshot_id": "x"}, {"snapshot_id": "y"})]
        summary = trend(comps)
        result = validate_trend(summary)
        self.assertTrue(result["valid"])
        self.assertEqual(summary["eligible_count"], 0)
        self.assertEqual(summary["ineligible_count"], 1)

    def test_06_all_comparisons_invalid(self):
        comps = [compare({"snapshot_id": "x"}, {"snapshot_id": "y"}), {}, None, "junk"]
        summary = trend(comps)
        result = validate_trend(summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})
        for entry in summary["section_availability"].values():
            self.assertEqual(entry["availability"], AVAILABILITY_INVALID)

    def test_07_mixed_valid_invalid_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 4]))
        mixed = [comps[0], {"valid": True}, comps[1]]
        summary = trend(mixed)
        result = validate_trend(summary, comparisons=mixed)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class NumericTrendTests(unittest.TestCase):
    def test_08_valid_increased_trend(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        self.assertEqual(summary["numeric"]["total_evaluations"]["state"], TREND_INCREASED)
        result = validate_trend(summary)
        self.assertTrue(result["valid"])

    def test_09_valid_decreased_trend(self):
        _, comps = _chain(_numeric_specs([5, 4, 2]))
        summary = trend(comps)
        self.assertEqual(summary["numeric"]["total_evaluations"]["state"], TREND_DECREASED)
        result = validate_trend(summary)
        self.assertTrue(result["valid"])

    def test_10_valid_unchanged_trend(self):
        _, comps = _chain(_numeric_specs([3, 3, 3]))
        summary = trend(comps)
        self.assertEqual(summary["numeric"]["total_evaluations"]["state"], CHANGE_UNCHANGED)
        result = validate_trend(summary)
        self.assertTrue(result["valid"])

    def test_11_valid_insufficient_data_trend(self):
        _, comps = _chain([(["trend"], {"accepted": 1}), (["trend"], {"accepted": 2})])
        summary = trend(comps)
        for field in _NUMERIC:
            self.assertEqual(summary["numeric"][field]["state"], TREND_INSUFFICIENT_DATA)
        result = validate_trend(summary)
        self.assertTrue(result["valid"])

    def test_12_invalid_numeric_trend_state(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = copy.deepcopy(trend(comps))
        summary["numeric"]["total_evaluations"]["state"] = "skyrocketed"
        result = validate_trend(summary)
        self.assertFalse(result["valid"])
        self.assertIn("unknown_numeric_trend_state:total_evaluations", result["errors"])

    def test_13_inconsistent_numeric_trend_state(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = copy.deepcopy(trend(comps))
        summary["numeric"]["total_evaluations"]["state"] = TREND_DECREASED
        result = validate_trend(summary)
        self.assertFalse(result["valid"])
        self.assertIn("inconsistent_numeric_trend_state:total_evaluations", result["errors"])


class CategoricalTrendTests(unittest.TestCase):
    def _reason_summary(self, first, second):
        _, comps = _chain([(_SMALL, first), (_SMALL, second)])
        return trend(comps)

    def test_14_valid_categorical_unchanged(self):
        summary = self._reason_summary({"irrelevant": 2}, {"irrelevant": 3})
        self.assertEqual(summary["categorical"]["dominant_rejection_reason"]["state"], CHANGE_UNCHANGED)
        result = validate_trend(summary)
        self.assertTrue(result["valid"])

    def test_15_valid_categorical_changed(self):
        summary = self._reason_summary({"irrelevant": 2}, {"low_reliability": 2})
        self.assertEqual(summary["categorical"]["dominant_rejection_reason"]["state"], CHANGE_CHANGED)
        result = validate_trend(summary)
        self.assertTrue(result["valid"])

    def test_16_valid_categorical_appeared(self):
        summary = self._reason_summary({"accepted": 2}, {"irrelevant": 2})
        self.assertEqual(summary["categorical"]["dominant_rejection_reason"]["state"], CHANGE_BECAME_AVAILABLE)
        result = validate_trend(summary)
        self.assertTrue(result["valid"])

    def test_17_valid_categorical_disappeared(self):
        summary = self._reason_summary({"irrelevant": 2}, {"accepted": 2})
        self.assertEqual(summary["categorical"]["dominant_rejection_reason"]["state"], CHANGE_BECAME_EMPTY)
        result = validate_trend(summary)
        self.assertTrue(result["valid"])

    def test_18_valid_categorical_insufficient_data(self):
        _, comps = _chain([(["rates"], {"accepted": 1}), (["rates"], {"accepted": 2})])
        summary = trend(comps)
        for section in _CATEGORICAL:
            self.assertEqual(summary["categorical"][section]["state"], TREND_INSUFFICIENT_DATA)
        result = validate_trend(summary)
        self.assertTrue(result["valid"])

    def test_19_invalid_categorical_state(self):
        summary = copy.deepcopy(self._reason_summary({"irrelevant": 2}, {"irrelevant": 3}))
        summary["categorical"]["dominant_rejection_reason"]["state"] = "transformed"
        result = validate_trend(summary)
        self.assertFalse(result["valid"])
        self.assertIn("unknown_categorical_trend_state:dominant_rejection_reason", result["errors"])

    def test_20_inconsistent_categorical_state(self):
        summary = copy.deepcopy(self._reason_summary({"irrelevant": 2}, {"low_reliability": 2}))
        summary["categorical"]["dominant_rejection_reason"]["state"] = CHANGE_UNCHANGED
        result = validate_trend(summary)
        self.assertFalse(result["valid"])
        self.assertIn("inconsistent_dominant_rejection_reason_trend_state", result["errors"])


class SectionAvailabilityTests(unittest.TestCase):
    def test_21_contradictory_section_availability(self):
        _, comps = _chain(_numeric_specs([1, 2, 3], _ALL))
        summary = copy.deepcopy(trend(comps))
        summary["section_availability"]["trend"]["availability"] = AVAILABILITY_UNAVAILABLE
        result = validate_trend(summary)
        self.assertFalse(result["valid"])
        self.assertIn("inconsistent_trend_availability:section_availability.trend", result["errors"])

    def test_22_missing_section_data(self):
        _, comps = _chain(_numeric_specs([1, 2]))
        summary = dict(trend(comps))
        del summary["section_availability"]["trend"]
        result = validate_trend(summary)
        self.assertFalse(result["valid"])
        self.assertIn("missing_section_availability_field:trend", result["errors"])

    def test_23_valid_sparse_section_data(self):
        specs = [(["rates"], {"accepted": 1}), (["rates"], {"accepted": 2}),
                 (["rates", "evaluation_counts"], {"accepted": 3})]
        _, comps = _chain(specs)
        summary = trend(comps)
        result = validate_trend(summary)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


class ChronologyTests(unittest.TestCase):
    def test_24_reversed_chronology(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(list(reversed(comps)))
        self.assertFalse(summary["chronology"]["ordered"])
        result = validate_trend(summary)
        self.assertTrue(result["valid"])

    def test_25_unavailable_chronology(self):
        result = validate_trend(trend(None))
        self.assertTrue(result["valid"])
        self.assertEqual(trend(None)["chronological_range"], {"earlier": None, "later": None})

    def test_26_contradictory_chronology(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = copy.deepcopy(trend(comps))
        summary["chronology"]["ordered"] = False
        result = validate_trend(summary)
        self.assertFalse(result["valid"])
        self.assertIn("inconsistent_chronology", result["errors"])


class SparseAndEmptyTests(unittest.TestCase):
    def test_27_zero_source_comparisons(self):
        for empty in (None, [], ()):
            summary = trend(empty)
            result = validate_trend(summary)
            self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_28_one_source_comparison(self):
        _, comps = _chain(_numeric_specs([1, 3]))
        summary = trend(comps)
        result = validate_trend(summary, comparisons=comps)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_29_empty_trend_summary(self):
        result = validate_trend({})
        self.assertFalse(result["valid"])
        self.assertFalse(result["well_formed"])
        for field in ("valid", "errors", "direction", "total_comparisons", "numeric",
                      "categorical", "section_availability", "chronology"):
            self.assertIn("missing_field:%s" % field, result["errors"])
        # never raises / repairs
        self.assertEqual(validate_trend(None),
                          {"valid": False, "well_formed": False,
                           "errors": ["trend_summary_not_a_dict"], "warnings": []})


class DeterminismAndMutationTests(unittest.TestCase):
    def test_30_deterministic_repeated_validation(self):
        _, comps = _chain(_numeric_specs([1, 2, 3, 3]))
        mixed = [comps[0], {}, comps[1], comps[2]]
        summary = trend(mixed)
        results = [validate_trend(summary, comparisons=mixed) for _ in range(5)]
        self.assertTrue(all(r == results[0] for r in results))

    def test_31_validation_does_not_mutate_trend_summary(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        before = copy.deepcopy(summary)
        validate_trend(summary, comparisons=comps)
        self.assertEqual(summary, before)

    def test_32_validation_does_not_mutate_source_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        before = copy.deepcopy(comps)
        validate_trend(summary, comparisons=comps)
        self.assertEqual(comps, before)

    def test_33_validation_does_not_mutate_snapshots(self):
        snaps, comps = _chain(_numeric_specs([1, 2, 3]))
        before = copy.deepcopy(snaps)
        summary = trend(comps)
        validate_trend(summary, comparisons=comps)
        self.assertEqual(snaps, before)


class RegressionTests(unittest.TestCase):
    def test_34_prompt_520_behavior_unchanged(self):
        _, comps = _chain(_numeric_specs([1, 2, 5], _ALL))
        summary = trend(comps)
        self.assertEqual(summary["direction"], COMPARISON_DIRECTION)
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["errors"], [])
        # calling the validator afterwards changes nothing about the summary
        validate_trend(summary)
        self.assertEqual(trend(comps), summary)

    def test_35_prompt_512_behavior_unchanged(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        for counts in ({"accepted": 1}, {"accepted": 2}, {"accepted": 3}):
            history.record_statistics(_stats(**counts))
        comparisons = [history.compare_sequences(i, i + 1) for i in (1, 2)]
        summary511 = trend511(comparisons)
        result511 = validate_trend511(summary511, comparisons=comparisons)
        self.assertEqual(result511, {"valid": True, "well_formed": True, "errors": [], "warnings": []})


if __name__ == "__main__":
    unittest.main()
