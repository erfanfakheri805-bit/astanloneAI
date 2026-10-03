"""
Tests for Prompt 513 - Unified Diagnostic Report.

`build_learned_knowledge_diagnostic_report()`
(learning/learned_knowledge_statistics.py) is a deterministic, read-only
aggregation over whatever subset of the existing pipeline the caller
has: a snapshot collection (Prompt 508), an ordered comparison
collection (judged by the existing Prompt 510 validator), and a trend
summary (Prompt 511, judged by the existing Prompt 512 validator, or
derived here by calling the unmodified Prompt 511 summarizer when the
caller has comparisons but no trend summary yet). It computes no new
metric, never repairs an invalid comparison or trend summary, never
fabricates a value for a missing component, and never mutates anything
it is given.

Covers:
    1.  fully populated valid diagnostic pipeline
    2.  no snapshots
    3.  one snapshot
    4.  multiple snapshots
    5.  no comparisons
    6.  valid comparisons
    7.  invalid comparisons
    8.  valid trend summary
    9.  invalid trend summary
    10. zero-evaluation data
    11. partially available diagnostic data
    12. correct metric preservation
    13. correct chronological ordering
    14. correct validation-status preservation
    15. no fabricated values when data is missing
    16. deterministic report output
    17. report generation does not mutate source objects
    18. report generation does not change normal AI behavior
    19. Prompt 512 validation remains unchanged
    20. regression coverage for Prompts 500-512

Run directly:
    python -m unittest tests.test_learned_knowledge_diagnostic_report -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_gate import (
    STATUS_PASSED, REASON_OK, REASON_NOT_RELEVANT, REASON_INSUFFICIENT_RELIABILITY,
    DECISION_REJECTED_IRRELEVANT,
    LearnedKnowledgeGateResult, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    SNAPSHOT_VALIDATION_VALID, SNAPSHOT_VALIDATION_INVALID,
    TREND_INCREASED,
    REPORT_STATUS_NO_DATA, REPORT_STATUS_PARTIAL, REPORT_STATUS_VALID, REPORT_STATUS_INVALID,
    TREND_SOURCE_PROVIDED, TREND_SOURCE_DERIVED,
    summarize_learned_knowledge_diagnostic_snapshot_comparison_trend as trend,
    validate_learned_knowledge_diagnostic_snapshot_comparison_trend as validate_trend,
    validate_learned_knowledge_diagnostic_snapshot_comparison as validate_comparison,
    build_learned_knowledge_diagnostic_report as report,
)

REPORT_TOP_LEVEL_KEYS = [
    "valid", "errors", "structural_status", "snapshots", "comparison",
    "comparison_validation", "trend", "trend_validation",
]


def _gtrace(status, reason, **numbers):
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(status, reason, **numbers))


ACCEPTED = _gtrace(STATUS_PASSED, REASON_OK)
IRRELEVANT = _gtrace("REJECTED", REASON_NOT_RELEVANT)
LOW_RELIABILITY = _gtrace("REJECTED", REASON_INSUFFICIENT_RELIABILITY)


def _stats(accepted=0, irrelevant=0, low_reliability=0):
    stats = LearnedKnowledgeDecisionStatistics()
    for gate_trace, count in ((ACCEPTED, accepted), (IRRELEVANT, irrelevant), (LOW_RELIABILITY, low_reliability)):
        for _ in range(count):
            stats.record(gate_trace)
    return stats


def _history(counts_list):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for counts in counts_list:
        history.record_statistics(_stats(**counts))
    return history


def _chain(counts_list):
    history = _history(counts_list)
    return [history.compare_sequences(i, i + 1) for i in range(1, len(counts_list))]


def _invalid_status_history_and_comparison():
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record({}, {"valid": False, "errors": ["boom"]})
    history.record_statistics(_stats(accepted=2))
    comparison = history.compare_sequences(1, 2)
    assert validate_comparison(comparison)["valid"] is False
    return history, comparison


class Prompt513TestCase(unittest.TestCase):

    def assertReportShape(self, result):
        self.assertEqual(list(result.keys()), REPORT_TOP_LEVEL_KEYS)
        self.assertIs(result["valid"], True)
        self.assertEqual(result["errors"], [])
        self.assertEqual(list(result["snapshots"].keys()), ["available", "count", "latest"])
        self.assertEqual(list(result["comparison"].keys()), ["available", "total_considered", "latest"])
        self.assertEqual(list(result["comparison_validation"].keys()), ["available", "result"])
        self.assertEqual(list(result["trend"].keys()), ["available", "source", "summary"])
        self.assertEqual(list(result["trend_validation"].keys()), ["available", "result"])


# ----------------------------------------------------------------------
# 1. fully populated valid diagnostic pipeline
# ----------------------------------------------------------------------
class TestFullyPopulated(Prompt513TestCase):

    def test_everything_present_and_valid(self):
        history = _history([{"accepted": 1}, {"accepted": 3}, {"accepted": 9}])
        comparisons = [history.compare_sequences(i, i + 1) for i in range(1, 3)]
        result = report(snapshots=history, comparisons=comparisons)
        self.assertReportShape(result)
        self.assertEqual(result["structural_status"], REPORT_STATUS_VALID)
        self.assertTrue(result["snapshots"]["available"])
        self.assertTrue(result["comparison"]["available"])
        self.assertTrue(result["trend"]["available"])
        self.assertTrue(result["comparison_validation"]["result"]["valid"])
        self.assertTrue(result["trend_validation"]["result"]["valid"])

    def test_explicit_trend_summary_is_marked_provided(self):
        history = _history([{"accepted": 1}, {"accepted": 3}])
        comparisons = [history.compare_sequences(1, 2)]
        precomputed = trend(comparisons)
        result = report(snapshots=history, comparisons=comparisons, trend_summary=precomputed)
        self.assertEqual(result["trend"]["source"], TREND_SOURCE_PROVIDED)
        self.assertEqual(result["trend"]["summary"], precomputed)
        self.assertEqual(result["structural_status"], REPORT_STATUS_VALID)


# ----------------------------------------------------------------------
# 2/3/4. no / one / multiple snapshots
# ----------------------------------------------------------------------
class TestSnapshotCounts(Prompt513TestCase):

    def test_no_snapshots(self):
        result = report()
        self.assertReportShape(result)
        self.assertEqual(result["structural_status"], REPORT_STATUS_NO_DATA)
        self.assertFalse(result["snapshots"]["available"])
        self.assertEqual(result["snapshots"]["count"], 0)
        self.assertIsNone(result["snapshots"]["latest"])

    def test_no_snapshots_argument_none_and_empty_list_agree(self):
        self.assertEqual(report(snapshots=None), report(snapshots=[]))

    def test_one_snapshot(self):
        history = _history([{"accepted": 1}])
        result = report(snapshots=history)
        self.assertTrue(result["snapshots"]["available"])
        self.assertEqual(result["snapshots"]["count"], 1)
        self.assertEqual(result["snapshots"]["latest"]["sequence"], 1)
        self.assertEqual(result["structural_status"], REPORT_STATUS_PARTIAL)

    def test_multiple_snapshots_reports_the_latest_one(self):
        history = _history([{"accepted": 1}, {"accepted": 2}, {"accepted": 9}])
        result = report(snapshots=history)
        self.assertEqual(result["snapshots"]["count"], 3)
        self.assertEqual(result["snapshots"]["latest"]["sequence"], 3)
        self.assertEqual(result["snapshots"]["latest"]["accepted_count"], 9)

    def test_plain_list_of_snapshots_accepted_directly(self):
        history = _history([{"accepted": 1}, {"accepted": 4}])
        result = report(snapshots=history.get_all())
        self.assertEqual(result["snapshots"]["count"], 2)
        self.assertEqual(result["snapshots"]["latest"]["accepted_count"], 4)


# ----------------------------------------------------------------------
# 5/6/7. no / valid / invalid comparisons
# ----------------------------------------------------------------------
class TestComparisons(Prompt513TestCase):

    def test_no_comparisons(self):
        history = _history([{"accepted": 1}])
        result = report(snapshots=history)
        self.assertFalse(result["comparison"]["available"])
        self.assertEqual(result["comparison"]["total_considered"], 0)
        self.assertIsNone(result["comparison"]["latest"])
        self.assertFalse(result["comparison_validation"]["available"])
        self.assertIsNone(result["comparison_validation"]["result"])

    def test_valid_comparison(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 5}])
        result = report(comparisons=comparisons)
        self.assertTrue(result["comparison"]["available"])
        self.assertEqual(result["comparison"]["total_considered"], 1)
        self.assertTrue(result["comparison_validation"]["result"]["valid"])

    def test_invalid_comparison_marks_report_invalid(self):
        _, bad = _invalid_status_history_and_comparison()
        result = report(comparisons=[bad])
        self.assertFalse(result["comparison_validation"]["result"]["valid"])
        self.assertEqual(result["structural_status"], REPORT_STATUS_INVALID)

    def test_latest_comparison_is_the_last_in_the_list(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}, {"accepted": 9}])
        result = report(comparisons=comparisons)
        self.assertEqual(result["comparison"]["latest"], comparisons[-1])
        self.assertEqual(result["comparison"]["total_considered"], 2)


# ----------------------------------------------------------------------
# 8/9. valid / invalid trend summary
# ----------------------------------------------------------------------
class TestTrendSummary(Prompt513TestCase):

    def test_valid_trend_summary_provided(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}, {"accepted": 5}])
        precomputed = trend(comparisons)
        result = report(comparisons=comparisons, trend_summary=precomputed)
        self.assertTrue(result["trend_validation"]["result"]["valid"])
        # snapshots were not given here, so the pipeline is not fully populated
        self.assertEqual(result["structural_status"], REPORT_STATUS_PARTIAL)

    def test_invalid_trend_summary_provided_marks_report_invalid(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 5}])
        tampered = trend(comparisons)
        tampered["numeric"]["accepted_count"]["state"] = "decreased"
        result = report(comparisons=comparisons, trend_summary=tampered)
        self.assertFalse(result["trend_validation"]["result"]["valid"])
        self.assertEqual(result["structural_status"], REPORT_STATUS_INVALID)
        self.assertEqual(result["trend"]["source"], TREND_SOURCE_PROVIDED)

    def test_trend_summary_without_comparisons_is_validated_without_cross_check(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 3}])
        precomputed = trend(comparisons)
        result = report(trend_summary=precomputed)
        self.assertTrue(result["trend_validation"]["available"])
        self.assertTrue(result["trend_validation"]["result"]["well_formed"])
        self.assertTrue(result["trend_validation"]["result"]["valid"])

    def test_no_trend_summary_and_no_comparisons_means_unavailable(self):
        history = _history([{"accepted": 1}])
        result = report(snapshots=history)
        self.assertFalse(result["trend"]["available"])
        self.assertIsNone(result["trend"]["source"])
        self.assertIsNone(result["trend"]["summary"])
        self.assertFalse(result["trend_validation"]["available"])


# ----------------------------------------------------------------------
# 10. zero-evaluation data
# ----------------------------------------------------------------------
class TestZeroEvaluationData(Prompt513TestCase):

    def test_zero_evaluation_snapshot(self):
        history = _history([{}])
        result = report(snapshots=history)
        self.assertEqual(result["snapshots"]["latest"]["total_evaluations"], 0)
        self.assertEqual(result["snapshots"]["latest"]["acceptance_rate"], 0.0)
        self.assertEqual(result["structural_status"], REPORT_STATUS_PARTIAL)

    def test_zero_to_zero_comparison_and_trend(self):
        history = _history([{}, {}])
        comparisons = [history.compare_sequences(1, 2)]
        result = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(result["structural_status"], REPORT_STATUS_VALID)
        self.assertTrue(result["comparison_validation"]["result"]["valid"])
        self.assertTrue(result["trend_validation"]["result"]["valid"])


# ----------------------------------------------------------------------
# 11. partially available diagnostic data
# ----------------------------------------------------------------------
class TestPartialData(Prompt513TestCase):

    def test_snapshots_only(self):
        history = _history([{"accepted": 1}, {"accepted": 2}])
        result = report(snapshots=history)
        self.assertEqual(result["structural_status"], REPORT_STATUS_PARTIAL)

    def test_comparisons_only_no_snapshots_argument(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}])
        result = report(comparisons=comparisons)
        self.assertFalse(result["snapshots"]["available"])
        self.assertTrue(result["comparison"]["available"])
        self.assertTrue(result["trend"]["available"])
        self.assertEqual(result["structural_status"], REPORT_STATUS_PARTIAL)

    def test_trend_summary_only(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 4}])
        precomputed = trend(comparisons)
        result = report(trend_summary=precomputed)
        self.assertFalse(result["snapshots"]["available"])
        self.assertFalse(result["comparison"]["available"])
        self.assertTrue(result["trend"]["available"])
        self.assertEqual(result["structural_status"], REPORT_STATUS_PARTIAL)


# ----------------------------------------------------------------------
# 12. correct metric preservation
# ----------------------------------------------------------------------
class TestMetricPreservation(Prompt513TestCase):

    def test_snapshot_metrics_carried_through_unchanged(self):
        history = _history([{"accepted": 3, "irrelevant": 2, "low_reliability": 1}])
        snapshot = history.get_latest()
        result = report(snapshots=history)
        for field in ("total_evaluations", "accepted_count", "rejected_count",
                      "no_candidate_count", "acceptance_rate", "rejection_rate",
                      "dominant_rejection_reason"):
            self.assertEqual(result["snapshots"]["latest"][field], snapshot[field])

    def test_trend_numeric_metrics_carried_through_unchanged(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 5}])
        expected = trend(comparisons)
        result = report(comparisons=comparisons)
        self.assertEqual(result["trend"]["summary"]["numeric"], expected["numeric"])
        self.assertEqual(result["trend"]["summary"]["dominant_rejection_reason"],
                          expected["dominant_rejection_reason"])


# ----------------------------------------------------------------------
# 13. correct chronological ordering
# ----------------------------------------------------------------------
class TestChronologicalOrdering(Prompt513TestCase):

    def test_latest_snapshot_is_the_last_recorded_not_the_first(self):
        history = _history([{"accepted": 1}, {"accepted": 2}, {"accepted": 3}])
        result = report(snapshots=history)
        self.assertEqual(result["snapshots"]["latest"]["sequence"], 3)

    def test_latest_comparison_is_the_last_given_not_the_first(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}, {"accepted": 9}])
        result = report(comparisons=comparisons)
        self.assertEqual(result["comparison"]["latest"]["later"]["sequence"], 3)

    def test_derived_trend_reflects_full_ordered_history(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 4}, {"accepted": 9}])
        result = report(comparisons=comparisons)
        self.assertEqual(result["trend"]["summary"]["numeric"]["accepted_count"],
                          {"state": TREND_INCREASED, "start": 1, "end": 9, "delta": 8})


# ----------------------------------------------------------------------
# 14. correct validation-status preservation
# ----------------------------------------------------------------------
class TestValidationStatusPreservation(Prompt513TestCase):

    def test_comparison_validation_result_matches_direct_call(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 5}])
        expected = validate_comparison(comparisons[-1])
        result = report(comparisons=comparisons)
        self.assertEqual(result["comparison_validation"]["result"], expected)

    def test_trend_validation_result_matches_direct_call(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 5}])
        precomputed = trend(comparisons)
        expected = validate_trend(precomputed, comparisons=comparisons)
        result = report(comparisons=comparisons, trend_summary=precomputed)
        self.assertEqual(result["trend_validation"]["result"], expected)

    def test_invalid_snapshot_status_preserved_and_drives_invalid_status(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record({}, {"valid": False, "errors": ["boom"]})  # the latest (only) snapshot
        result = report(snapshots=history)
        self.assertEqual(result["snapshots"]["latest"]["validation_status"], SNAPSHOT_VALIDATION_INVALID)
        self.assertEqual(result["structural_status"], REPORT_STATUS_INVALID)


# ----------------------------------------------------------------------
# 15. no fabricated values when data is missing
# ----------------------------------------------------------------------
class TestNoFabrication(Prompt513TestCase):

    def test_missing_components_are_none_not_guessed(self):
        result = report()
        self.assertIsNone(result["snapshots"]["latest"])
        self.assertIsNone(result["comparison"]["latest"])
        self.assertIsNone(result["comparison_validation"]["result"])
        self.assertIsNone(result["trend"]["summary"])
        self.assertIsNone(result["trend_validation"]["result"])

    def test_snapshots_without_comparisons_does_not_invent_a_comparison(self):
        history = _history([{"accepted": 1}, {"accepted": 5}])
        result = report(snapshots=history)
        self.assertFalse(result["comparison"]["available"])
        self.assertIsNone(result["comparison"]["latest"])


# ----------------------------------------------------------------------
# 16. deterministic report output
# ----------------------------------------------------------------------
class TestDeterministic(Prompt513TestCase):

    def test_same_input_same_output(self):
        history = _history([{"accepted": 1}, {"accepted": 4}])
        comparisons = [history.compare_sequences(1, 2)]
        first = report(snapshots=history, comparisons=comparisons)
        second = report(snapshots=history.get_all(), comparisons=copy.deepcopy(comparisons))
        self.assertEqual(first, second)

    def test_repeated_calls_are_stable(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}])
        outcomes = [report(comparisons=comparisons) for _ in range(5)]
        for outcome in outcomes[1:]:
            self.assertEqual(outcome, outcomes[0])


# ----------------------------------------------------------------------
# 17. report generation does not mutate source objects
# ----------------------------------------------------------------------
class TestNoMutation(Prompt513TestCase):

    def test_history_untouched(self):
        history = _history([{"accepted": 1}, {"accepted": 4}])
        before = history.get_all()
        report(snapshots=history)
        self.assertEqual(history.get_all(), before)

    def test_comparisons_list_untouched(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 4}])
        before = copy.deepcopy(comparisons)
        report(comparisons=comparisons)
        self.assertEqual(comparisons, before)

    def test_trend_summary_untouched(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 4}])
        precomputed = trend(comparisons)
        before = copy.deepcopy(precomputed)
        report(comparisons=comparisons, trend_summary=precomputed)
        self.assertEqual(precomputed, before)

    def test_returned_report_is_independent(self):
        history = _history([{"accepted": 1}, {"accepted": 4}])
        result = report(snapshots=history)
        result["snapshots"]["latest"]["accepted_count"] = 999
        self.assertEqual(report(snapshots=history)["snapshots"]["latest"]["accepted_count"], 4)


# ----------------------------------------------------------------------
# 18. report generation does not change normal AI behavior
# ----------------------------------------------------------------------
class TestNoBehaviorChange(Prompt513TestCase):

    def test_not_referenced_from_the_gate_module(self):
        import inspect
        from learning import learned_knowledge_gate
        source = inspect.getsource(learned_knowledge_gate)
        self.assertNotIn("build_learned_knowledge_diagnostic_report", source)

    def test_gate_still_evaluates_normally(self):
        from learning.learned_knowledge_gate import evaluate_learned_knowledge_gate, REASON_NOT_SELECTED
        result = evaluate_learned_knowledge_gate(selection=None)
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.reason, REASON_NOT_SELECTED)


# ----------------------------------------------------------------------
# 19. Prompt 512 validation remains unchanged
# ----------------------------------------------------------------------
class TestPrompt512Unaffected(Prompt513TestCase):

    def test_validator_output_shape_is_unchanged(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}])
        result = validate_trend(trend(comparisons), comparisons=comparisons)
        self.assertEqual(set(result.keys()), {"valid", "well_formed", "errors", "warnings"})
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_validator_never_calls_the_new_report_function(self):
        import inspect
        from learning import learned_knowledge_statistics
        source = inspect.getsource(
            learned_knowledge_statistics.validate_learned_knowledge_diagnostic_snapshot_comparison_trend)
        self.assertNotIn("build_learned_knowledge_diagnostic_report", source)


# ----------------------------------------------------------------------
# 20. regression coverage for Prompts 500-512
# ----------------------------------------------------------------------
class TestRegressionPrompts500Through512(unittest.TestCase):

    def test_full_chain_still_works_end_to_end(self):
        history = _history([{"accepted": 1}, {"irrelevant": 2}, {"accepted": 4}])
        comparisons = [history.compare_sequences(i, i + 1) for i in range(1, 3)]
        for comparison in comparisons:
            self.assertTrue(validate_comparison(comparison)["valid"])
        trend_summary = trend(comparisons)
        self.assertTrue(validate_trend(trend_summary, comparisons=comparisons)["valid"])
        result = report(snapshots=history, comparisons=comparisons, trend_summary=trend_summary)
        self.assertEqual(result["structural_status"], REPORT_STATUS_VALID)

    def test_dominant_rejection_reason_constant_unaffected(self):
        comparisons = _chain([{"accepted": 1}, {"irrelevant": 2}])
        result = report(comparisons=comparisons)
        self.assertEqual(result["trend"]["summary"]["dominant_rejection_reason"]["end"],
                          DECISION_REJECTED_IRRELEVANT)


if __name__ == "__main__":
    unittest.main()
