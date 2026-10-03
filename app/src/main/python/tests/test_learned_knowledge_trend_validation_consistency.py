"""
Tests for Prompt 531 - Validate Trend Validation Consistency.

The Unified Diagnostic Report (`build_learned_knowledge_diagnostic_report()`,
Prompt 513) carries a trend summary (Prompt 511) alongside its own embedded
validation result (Prompt 512), and, when the caller opts into the filtered
diagnostic trend (Prompt 522), a second such pair for the filtered trend
(Prompt 520/521). `validate_learned_knowledge_diagnostic_report()`
(Prompt 514) already holds every trend validation section to the trend data
it claims to judge: for each of `"trend_validation"` / `"filtered_trend_
validation"` it recomputes the existing standalone trend validator
(`validate_learned_knowledge_diagnostic_snapshot_comparison_trend()` /
`validate_learned_knowledge_filtered_summary_snapshot_comparison_trend()`)
over the embedded summary and reports any disagreement
(`_check_validation_section()` / `_trend_validation_problem()` /
`_filtered_trend_validation_problem()`), and separately holds a trend
report validation still passes as valid holds every numeric/categorical
entry to the trend's own `eligible_count` / `total_comparisons`
(`_check_trend_states_against_eligibility()`), so a trend with nothing
eligible cannot claim anything but `"insufficient_data"`.

This module adds no production code: the consistency checks this prompt
asks for already exist (see `validate_learned_knowledge_diagnostic_report()`
in learning/learned_knowledge_statistics.py, together with
`_check_validation_section()`, `_trend_validation_problem()`,
`_filtered_trend_validation_problem()`, and
`_check_trend_states_against_eligibility()`). What follows are focused,
self-contained tests that exercise exactly the Prompt 531 checklist:

    1.  valid trend
    2.  malformed trend
    3.  invalid trend marked valid
    4.  valid trend marked invalid
    5.  unavailable trend
    6.  filtered diagnostic trend
    7.  empty / insufficient-data trend

Run directly:
    python -m unittest tests.test_learned_knowledge_trend_validation_consistency -v
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
)

OK = {"valid": True, "well_formed": True, "errors": [], "warnings": []}
_ALL = ["evaluation_counts", "rates", "dominant_rejection_reason",
        "comparison_changes", "trend", "validation_statuses"]


def _gtrace():
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(STATUS_PASSED, REASON_OK))


def _stats(**counts):
    stats = LearnedKnowledgeDecisionStatistics()
    for _ in range(counts.get("accepted", 0)):
        stats.record(_gtrace())
    return stats


def _history(steps):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for step in steps:
        history.record_statistics(_stats(**step))
    return history


def _base_pipeline(steps=({"accepted": 1}, {"accepted": 2}, {"accepted": 4})):
    """Real snapshots plus their ordered comparisons."""
    history = _history(steps)
    comparisons = [history.compare_sequences(i, i + 1) for i in range(1, len(steps))]
    return history, comparisons


def _insufficient_pipeline():
    """A single comparison whose earlier snapshot is itself invalid, so
    the comparison is well-formed but Prompt-510-ineligible: a real
    `eligible_count == 0` / `total_comparisons == 1` trend."""
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record({}, {"valid": False, "errors": ["boom"]})  # sequence 1
    history.record_statistics(_stats(accepted=2))              # sequence 2
    comparisons = [history.compare_sequences(1, 2)]
    return history, comparisons


def _filtered_summary(counts):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for step in ({"accepted": 1}, counts):
        history.record_statistics(_stats(**step))
    comparisons = [history.compare_sequences(1, 2)]
    built = report(snapshots=history, comparisons=comparisons)
    return fmt(built, validate(built, snapshots=history, comparisons=comparisons))


def _filtered_snapshots(specs):
    """Real filtered snapshots (sequences 1..n) from one history;
    `specs` is `[(sections, counts), ...]`."""
    history = LearnedKnowledgeFilteredSummarySnapshotHistory()
    return [history.record_filtered_summary(filt(_filtered_summary(counts), sections))
            for sections, counts in specs]


def _filtered_comparisons(totals=(1, 2, 5), sections=_ALL):
    snaps = _filtered_snapshots([(sections, {"accepted": n}) for n in totals])
    return [compare(snaps[i], snaps[i + 1]) for i in range(len(snaps) - 1)]


class Prompt531TestCase(unittest.TestCase):
    def assert_report_valid(self, built, **sources):
        result = validate(built, **sources)
        self.assertEqual(result, OK, result)

    def assert_report_invalid(self, built, *expected_error_prefixes, **sources):
        result = validate(built, **sources)
        self.assertFalse(result["valid"], result)
        for prefix in expected_error_prefixes:
            self.assertTrue(
                any(error.startswith(prefix) for error in result["errors"]),
                "expected an error starting with %r in %r" % (prefix, result["errors"]))


# ----------------------------------------------------------------------
# 1. valid trend
# ----------------------------------------------------------------------
class ValidTrendTests(Prompt531TestCase):

    def test_valid_trend_contains_valid_trend_data(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons)
        self.assertTrue(built["trend"]["available"])
        self.assertTrue(built["trend_validation"]["result"]["valid"])
        self.assert_report_valid(built)
        self.assert_report_valid(built, snapshots=history, comparisons=comparisons)

    def test_valid_provided_trend_summary_is_accepted(self):
        history, comparisons = _base_pipeline()
        derived = report(snapshots=history, comparisons=comparisons)["trend"]["summary"]
        built = report(snapshots=history, comparisons=comparisons,
                       trend_summary=copy.deepcopy(derived))
        self.assertEqual(built["trend"]["source"], "provided")
        self.assert_report_valid(built)


# ----------------------------------------------------------------------
# 2. malformed trend
# ----------------------------------------------------------------------
class MalformedTrendTests(Prompt531TestCase):

    def test_missing_required_field_marked_valid_is_detected(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        del built["trend"]["summary"]["eligible_count"]
        self.assert_report_invalid(built, "claims_valid_but_source_invalid:trend")

    def test_wrong_typed_field_marked_valid_is_detected(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["trend"]["summary"]["total_comparisons"] = "not_a_number"
        self.assert_report_invalid(built, "claims_valid_but_source_invalid:trend")


# ----------------------------------------------------------------------
# 3. invalid trend marked valid
# ----------------------------------------------------------------------
class InvalidTrendMarkedValidTests(Prompt531TestCase):

    def test_inconsistent_comparison_counts_marked_valid_is_detected(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["trend"]["summary"]["ineligible_count"] += 1
        self.assert_report_invalid(built, "claims_valid_but_source_invalid:trend")

    def test_bad_direction_marked_valid_is_detected(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["trend"]["summary"]["direction"] = "backwards"
        self.assert_report_invalid(built, "claims_valid_but_source_invalid:trend")


# ----------------------------------------------------------------------
# 4. valid trend marked invalid
# ----------------------------------------------------------------------
class ValidTrendMarkedInvalidTests(Prompt531TestCase):

    def test_falsely_claimed_invalid_trend_is_detected(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["trend_validation"]["result"] = {
            "valid": False, "well_formed": False, "errors": ["fabricated"], "warnings": []}
        self.assert_report_invalid(built, "mismatched_validation_result:trend")

    def test_falsely_claimed_invalid_trend_flips_structural_status(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["trend_validation"]["result"] = {
            "valid": False, "well_formed": False, "errors": ["fabricated"], "warnings": []}
        # structural_status was left as the original "valid", so it now
        # disagrees with the (falsely) invalid trend_validation too.
        self.assertEqual(built["structural_status"], "valid")
        result = validate(built)
        self.assertIn("inconsistent_structural_status", result["errors"])


# ----------------------------------------------------------------------
# 5. unavailable trend
# ----------------------------------------------------------------------
class UnavailableTrendTests(Prompt531TestCase):

    def test_no_comparisons_leaves_trend_unavailable_and_valid(self):
        history, _ = _base_pipeline()
        built = report(snapshots=history)
        self.assertFalse(built["trend"]["available"])
        self.assertIsNone(built["trend"]["summary"])
        self.assertIsNone(built["trend"]["source"])
        self.assertFalse(built["trend_validation"]["available"])
        self.assertIsNone(built["trend_validation"]["result"])
        self.assert_report_valid(built)

    def test_fabricated_result_for_unavailable_trend_is_detected(self):
        history, _ = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history))
        built["trend_validation"]["result"] = OK
        self.assertFalse(validate(built)["valid"])


# ----------------------------------------------------------------------
# 6. filtered diagnostic trend
# ----------------------------------------------------------------------
class FilteredDiagnosticTrendTests(Prompt531TestCase):

    def test_valid_filtered_trend_is_accepted(self):
        filtered = _filtered_comparisons()
        built = report(filtered_comparisons=filtered)
        self.assertTrue(built["filtered_trend"]["available"])
        self.assertTrue(built["filtered_trend_validation"]["result"]["valid"])
        self.assert_report_valid(built)
        self.assert_report_valid(built, filtered_comparisons=filtered)

    def test_malformed_filtered_trend_marked_valid_is_detected(self):
        filtered = _filtered_comparisons()
        built = copy.deepcopy(report(filtered_comparisons=filtered))
        built["filtered_trend"]["summary"]["eligible_count"] += 1
        self.assert_report_invalid(built, "claims_valid_but_source_invalid:filtered_trend")

    def test_valid_filtered_trend_marked_invalid_is_detected(self):
        filtered = _filtered_comparisons()
        built = copy.deepcopy(report(filtered_comparisons=filtered))
        built["filtered_trend_validation"]["result"] = {
            "valid": False, "well_formed": False, "errors": ["fabricated"], "warnings": []}
        self.assert_report_invalid(built, "mismatched_validation_result:filtered_trend")

    def test_unavailable_filtered_trend_is_valid(self):
        built = report(filtered_comparisons=None, filtered_trend_summary=None)
        self.assertFalse(built["filtered_trend"]["available"])
        self.assert_report_valid(built)


# ----------------------------------------------------------------------
# 7. empty / insufficient-data trend
# ----------------------------------------------------------------------
class EmptyInsufficientDataTrendTests(Prompt531TestCase):

    def test_trend_with_no_eligible_comparisons_reports_insufficient_data(self):
        history, comparisons = _insufficient_pipeline()
        built = report(snapshots=history, comparisons=comparisons)
        summary = built["trend"]["summary"]
        self.assertEqual(summary["eligible_count"], 0)
        for field in summary["numeric"]:
            self.assertEqual(summary["numeric"][field]["state"], "insufficient_data")
        self.assert_report_valid(built, snapshots=history, comparisons=comparisons)

    def test_claiming_a_real_state_over_insufficient_data_is_detected(self):
        history, comparisons = _insufficient_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["trend"]["summary"]["numeric"]["accepted_count"] = {
            "state": "increased", "start": 1, "end": 2, "delta": 1}
        self.assert_report_invalid(built, "inconsistent_numeric_trend_state:accepted_count")

    def test_zero_comparisons_filtered_trend_is_available_and_valid(self):
        snaps = _filtered_snapshots(
            [(["evaluation_counts", "rates"], {"accepted": 0}),
             (["evaluation_counts", "rates"], {"accepted": 0})])
        comparisons = [compare(snaps[0], snaps[1])]
        built = report(filtered_comparisons=comparisons)
        self.assertTrue(built["filtered_trend"]["available"])
        self.assertEqual(built["filtered_trend"]["summary"]["numeric"]["total_evaluations"]["end"], 0)
        self.assert_report_valid(built, filtered_comparisons=comparisons)

    def test_no_data_report_never_fabricates_a_trend(self):
        built = report()
        self.assertEqual(built["structural_status"], "no_data")
        self.assertFalse(built["trend"]["available"])
        self.assertIsNone(built["trend"]["summary"])
        self.assert_report_valid(built)


if __name__ == "__main__":
    unittest.main()
