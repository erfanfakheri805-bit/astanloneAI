"""
Tests for Prompt 524 - Validate Report Status Consistency.

The existing Unified Diagnostic Report validator
(`validate_learned_knowledge_diagnostic_report()`, Prompt 514) already
recomputes the report's `"structural_status"` from the availability and
validation state of its own sections - `_report_structural_status()`
(Prompt 513, extended by Prompt 522 for the optional filtered trend) run
over the report's own embedded sections via `_check_status_consistency()`
- and flags `"inconsistent_structural_status"` whenever the two disagree.
That is exactly what this prompt asks the validator to check: no
production code changes are needed. This module is a focused,
self-contained regression suite that exercises the Prompt 524 checklist
directly, so the guarantee is explicit and independently verifiable:

    1. fully valid report
    2. one invalid section (each of snapshot, comparison, trend and the
       Prompt 522 filtered trend, in turn)
    3. unavailable section
    4. invalid filtered diagnostic trend validation
    5. consistent valid/invalid overall status (a report cannot claim
       "valid" while a section it carries is invalid, and cannot claim
       "invalid" while every section it carries is genuinely valid)
    6. zero-data report

Run directly:
    python -m unittest tests.test_learned_knowledge_report_status_consistency -v
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
    SNAPSHOT_VALIDATION_VALID, SNAPSHOT_VALIDATION_INVALID,
    REPORT_STATUS_NO_DATA, REPORT_STATUS_PARTIAL, REPORT_STATUS_VALID, REPORT_STATUS_INVALID,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    validate_learned_knowledge_diagnostic_snapshot_comparison as validate_comparison,
    filter_learned_knowledge_diagnostic_summary as filt,
    format_learned_knowledge_diagnostic_summary as fmt,
    compare_learned_knowledge_filtered_summary_snapshots as compare,
    summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend as ftrend,
)

OK = {"valid": True, "well_formed": True, "errors": [], "warnings": []}
_ALL = ["evaluation_counts", "rates", "dominant_rejection_reason",
        "comparison_changes", "trend", "validation_statuses"]


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


def _history(steps):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for step in steps:
        history.record_statistics(_stats(**step))
    return history


def _base_pipeline(steps=({"accepted": 1}, {"accepted": 2}, {"accepted": 4})):
    history = _history(steps)
    comparisons = [history.compare_sequences(i, i + 1) for i in range(1, len(steps))]
    return history, comparisons


def _invalid_status_history_and_comparison():
    """A history whose first snapshot is directly recorded as invalid, so
    the comparison built from it is invalid too - the same real,
    end-to-end way an invalid section legitimately arises."""
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record({}, {"valid": False, "errors": ["boom"]})
    history.record_statistics(_stats(accepted=2))
    comparison = history.compare_sequences(1, 2)
    assert validate_comparison(comparison)["valid"] is False
    return history, comparison


def _filtered_summary(counts):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for step in ({"accepted": 1}, counts):
        history.record_statistics(_stats(**step))
    comparisons = [history.compare_sequences(1, 2)]
    built = report(snapshots=history, comparisons=comparisons)
    return fmt(built, validate(built, snapshots=history, comparisons=comparisons))


def _filtered_snapshots(specs):
    history = LearnedKnowledgeFilteredSummarySnapshotHistory()
    return [history.record_filtered_summary(filt(_filtered_summary(counts), sections))
            for sections, counts in specs]


def _filtered_comparisons(totals=(1, 2, 5), sections=_ALL):
    snaps = _filtered_snapshots([(sections, {"accepted": n}) for n in totals])
    return [compare(snaps[i], snaps[i + 1]) for i in range(len(snaps) - 1)]


class Prompt524TestCase(unittest.TestCase):
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
# 1. fully valid report
# ----------------------------------------------------------------------
class FullyValidReportTests(Prompt524TestCase):

    def test_fully_valid_base_report_status_is_consistent(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(built["structural_status"], REPORT_STATUS_VALID)
        self.assert_report_valid(built, snapshots=history, comparisons=comparisons)

    def test_fully_valid_extended_report_status_is_consistent(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assertEqual(built["structural_status"], REPORT_STATUS_VALID)
        self.assertTrue(built["comparison_validation"]["result"]["valid"])
        self.assertTrue(built["trend_validation"]["result"]["valid"])
        self.assertTrue(built["filtered_trend_validation"]["result"]["valid"])
        self.assert_report_valid(
            built, snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)


# ----------------------------------------------------------------------
# 2. one invalid section - a required included section being invalid
#    must make the overall status "invalid", and a report that claims
#    otherwise must be rejected.
# ----------------------------------------------------------------------
class OneInvalidSectionTests(Prompt524TestCase):

    def test_invalid_source_snapshot_forces_invalid_status(self):
        # the earlier (non-latest) snapshot is invalid, which makes the
        # comparison built from it invalid, which must in turn make the
        # overall status invalid - not just the snapshot's own status.
        history, comparison = _invalid_status_history_and_comparison()
        built = report(snapshots=history, comparisons=[comparison])
        self.assertFalse(built["comparison_validation"]["result"]["valid"])
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        self.assert_report_valid(built, snapshots=history, comparisons=[comparison])

    def test_invalid_latest_snapshot_forces_invalid_status(self):
        only_invalid = LearnedKnowledgeDiagnosticSnapshotHistory()
        only_invalid.record({}, {"valid": False, "errors": ["boom"]})
        built = report(snapshots=only_invalid)
        self.assertEqual(built["snapshots"]["latest"]["validation_status"], SNAPSHOT_VALIDATION_INVALID)
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        self.assert_report_valid(built, snapshots=only_invalid)

    def test_report_may_not_claim_valid_status_while_snapshot_is_invalid(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = copy.deepcopy(report(snapshots=history, comparisons=[comparison]))
        built["structural_status"] = REPORT_STATUS_VALID
        self.assert_report_invalid(built, "inconsistent_structural_status")

    def test_invalid_comparison_validation_forces_invalid_status(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = report(snapshots=history, comparisons=[comparison])
        self.assertFalse(built["comparison_validation"]["result"]["valid"])
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)

    def test_report_may_not_claim_valid_status_while_trend_validation_is_invalid(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["trend_validation"]["result"] = {
            "valid": False, "well_formed": False, "errors": ["made_up"], "warnings": []}
        built["structural_status"] = REPORT_STATUS_VALID
        self.assert_report_invalid(built, "inconsistent_structural_status")

    def test_invalid_filtered_trend_forces_invalid_status(self):
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["eligible_count"] += 1
        built = report(filtered_trend_summary=summary)
        self.assertFalse(built["filtered_trend_validation"]["result"]["valid"])
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)

    def test_report_may_not_claim_valid_status_while_filtered_trend_is_invalid(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = copy.deepcopy(
            report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered))
        built["filtered_trend_validation"]["result"] = {
            "valid": False, "well_formed": False, "errors": ["made_up"], "warnings": []}
        built["structural_status"] = REPORT_STATUS_VALID
        self.assert_report_invalid(built, "inconsistent_structural_status")

    def test_one_invalid_section_among_otherwise_valid_sections_still_yields_invalid(self):
        # snapshot and comparison are valid; only the filtered trend is invalid.
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["eligible_count"] += 1
        built = report(snapshots=history, comparisons=comparisons, filtered_trend_summary=summary)
        self.assertTrue(built["comparison_validation"]["result"]["valid"])
        self.assertTrue(built["trend_validation"]["result"]["valid"])
        self.assertFalse(built["filtered_trend_validation"]["result"]["valid"])
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        self.assert_report_valid(built)


# ----------------------------------------------------------------------
# 3. unavailable section - must not be treated as valid data
# ----------------------------------------------------------------------
class UnavailableSectionTests(Prompt524TestCase):

    def test_unavailable_sections_are_not_counted_as_available_valid_data(self):
        history, _ = _base_pipeline()
        built = report(snapshots=history)
        self.assertFalse(built["comparison"]["available"])
        self.assertFalse(built["trend"]["available"])
        self.assertEqual(built["structural_status"], REPORT_STATUS_PARTIAL)
        self.assert_report_valid(built, snapshots=history)

    def test_partial_report_may_not_be_reported_as_fully_valid(self):
        history, _ = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history))
        built["structural_status"] = REPORT_STATUS_VALID
        self.assert_report_invalid(built, "inconsistent_structural_status")

    def test_unavailable_filtered_trend_does_not_count_toward_status_validity(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=None)
        self.assertFalse(built["filtered_trend"]["available"])
        # the base pipeline alone is complete, so overall status is still valid -
        # a missing/unavailable filtered trend is simply not part of the picture
        self.assertEqual(built["structural_status"], REPORT_STATUS_VALID)
        self.assert_report_valid(built, snapshots=history, comparisons=comparisons)

    def test_fabricated_data_for_an_unavailable_section_is_rejected(self):
        built = copy.deepcopy(report())
        built["snapshots"]["available"] = True
        self.assertFalse(validate(built)["valid"])


# ----------------------------------------------------------------------
# 4. invalid filtered diagnostic trend validation (Prompt 522)
# ----------------------------------------------------------------------
class InvalidFilteredTrendValidationTests(Prompt524TestCase):

    def test_filtered_trend_validation_invalid_is_reflected_in_status(self):
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["eligible_count"] += 1
        built = report(filtered_comparisons=filtered, filtered_trend_summary=summary)
        result = built["filtered_trend_validation"]["result"]
        self.assertFalse(result["valid"])
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        self.assert_report_valid(built, filtered_comparisons=filtered, filtered_trend_summary=summary)

    def test_filtered_trend_validation_claiming_valid_for_invalid_data_is_rejected(self):
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["eligible_count"] += 1
        built = copy.deepcopy(report(filtered_trend_summary=summary))
        built["filtered_trend_validation"]["result"] = dict(OK)
        built["structural_status"] = REPORT_STATUS_PARTIAL
        self.assert_report_invalid(built, "claims_valid_but_source_invalid:filtered_trend")

    def test_filtered_trend_validation_invalid_alongside_valid_base_report_is_invalid_status(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["eligible_count"] += 1
        built = report(snapshots=history, comparisons=comparisons, filtered_trend_summary=summary)
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        broken = copy.deepcopy(built)
        broken["structural_status"] = REPORT_STATUS_VALID
        self.assert_report_invalid(broken, "inconsistent_structural_status")


# ----------------------------------------------------------------------
# 5. consistent valid/invalid overall status, both directions
# ----------------------------------------------------------------------
class ConsistentOverallStatusTests(Prompt524TestCase):

    def test_status_cannot_be_invalid_when_every_included_section_is_genuinely_valid(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = copy.deepcopy(
            report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered))
        built["structural_status"] = REPORT_STATUS_INVALID
        self.assert_report_invalid(built, "inconsistent_structural_status")

    def test_status_cannot_be_valid_when_an_included_section_is_invalid(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = copy.deepcopy(report(snapshots=history, comparisons=[comparison]))
        built["structural_status"] = REPORT_STATUS_VALID
        self.assert_report_invalid(built, "inconsistent_structural_status")

    def test_status_cannot_be_no_data_when_sections_are_available(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["structural_status"] = REPORT_STATUS_NO_DATA
        self.assert_report_invalid(built, "inconsistent_structural_status")

    def test_status_cannot_be_partial_when_every_section_is_available_and_valid(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["structural_status"] = REPORT_STATUS_PARTIAL
        self.assert_report_invalid(built, "inconsistent_structural_status")

    def test_genuinely_matching_status_is_never_flagged(self):
        for kwargs, expected in (
            ({}, REPORT_STATUS_NO_DATA),
            ({"snapshots": _base_pipeline()[0]}, REPORT_STATUS_PARTIAL),
        ):
            with self.subTest(expected=expected):
                built = report(**kwargs)
                self.assertEqual(built["structural_status"], expected)
                self.assert_report_valid(built)


# ----------------------------------------------------------------------
# 6. zero-data report
# ----------------------------------------------------------------------
class ZeroDataReportTests(Prompt524TestCase):

    def test_empty_report_is_no_data_and_consistent(self):
        built = report()
        self.assertEqual(built["structural_status"], REPORT_STATUS_NO_DATA)
        self.assertFalse(built["snapshots"]["available"])
        self.assertFalse(built["comparison"]["available"])
        self.assertFalse(built["trend"]["available"])
        self.assert_report_valid(built)

    def test_empty_extended_report_is_no_data_and_consistent(self):
        built = report(filtered_comparisons=None, filtered_trend_summary=None)
        self.assertEqual(built["structural_status"], REPORT_STATUS_NO_DATA)
        self.assertFalse(built["filtered_trend"]["available"])
        self.assert_report_valid(built)

    def test_zero_data_report_may_not_claim_a_validated_status(self):
        for status in (REPORT_STATUS_PARTIAL, REPORT_STATUS_VALID, REPORT_STATUS_INVALID):
            with self.subTest(status=status):
                built = copy.deepcopy(report())
                built["structural_status"] = status
                self.assert_report_invalid(built, "inconsistent_structural_status")

    def test_zero_evaluations_is_not_the_same_as_zero_data(self):
        # a report built from a real, zero-evaluation snapshot/comparison is
        # "valid" and available, not "no_data" - the two must stay distinct
        history = _history(({"accepted": 0}, {"accepted": 0}))
        comparisons = [history.compare_sequences(1, 2)]
        built = report(snapshots=history, comparisons=comparisons)
        self.assertNotEqual(built["structural_status"], REPORT_STATUS_NO_DATA)
        self.assertEqual(built["structural_status"], REPORT_STATUS_VALID)
        self.assert_report_valid(built, snapshots=history, comparisons=comparisons)


if __name__ == "__main__":
    unittest.main()
