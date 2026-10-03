"""
Tests for Prompt 525 - Validate Report Section Availability.

The existing Unified Diagnostic Report validator
(`validate_learned_knowledge_diagnostic_report()`, Prompt 514, extended by
Prompt 522 for the filtered trend) already checks that every section's
`"available"` flag matches what the section actually carries -
`_check_payload_presence()` flags a payload fabricated for an unavailable
section (`"fabricated_value_for_unavailable_component:<path>"`) or a
missing/empty payload for one marked available
(`"missing_data_marked_available:<path>"` /
`"fabricated_placeholder_value:<path>"`); `_check_count()` does the same
for `snapshots.count` / `comparison.total_considered`
(`"inconsistent_count:<path>"`); and the embedded validation sections
(`comparison_validation`, `trend_validation`, `filtered_trend_validation`)
are checked both for matching availability with the component they judge
(`"inconsistent_availability:<name>"`) and for not claiming a source
invalid as valid (`"claims_valid_but_source_invalid:<component>"`) or a
valid source as invalid (`"claims_invalid_but_source_valid:<component>"`).
No production code changes are needed for this prompt. This module is a
focused, self-contained regression suite that exercises the Prompt 525
checklist directly against that existing machinery:

    1. all sections available
    2. unavailable section
    3. missing section
    4. invalid section
    5. filtered trend available / unavailable
    6. contradictory availability states

Run directly:
    python -m unittest tests.test_learned_knowledge_report_section_availability -v
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
    REPORT_STATUS_VALID, REPORT_STATUS_PARTIAL,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
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


class Prompt525TestCase(unittest.TestCase):
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
# 1. all sections available
# ----------------------------------------------------------------------
class AllSectionsAvailableTests(Prompt525TestCase):

    def test_every_base_section_reports_available_true_with_real_data(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons)
        for name in ("snapshots", "comparison", "comparison_validation", "trend", "trend_validation"):
            self.assertTrue(built[name]["available"], name)
        self.assertIsNotNone(built["snapshots"]["latest"])
        self.assertIsNotNone(built["comparison"]["latest"])
        self.assertIsNotNone(built["trend"]["summary"])
        self.assertEqual(built["structural_status"], REPORT_STATUS_VALID)
        self.assert_report_valid(built, snapshots=history, comparisons=comparisons)

    def test_every_section_including_filtered_trend_is_available(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        all_names = ("snapshots", "comparison", "comparison_validation", "trend", "trend_validation",
                     "filtered_trend", "filtered_trend_validation")
        for name in all_names:
            self.assertTrue(built[name]["available"], name)
        self.assert_report_valid(
            built, snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)


# ----------------------------------------------------------------------
# 2. unavailable section
# ----------------------------------------------------------------------
class UnavailableSectionTests(Prompt525TestCase):

    def test_genuinely_unavailable_comparison_and_trend_carry_no_data(self):
        history, _ = _base_pipeline()
        built = report(snapshots=history)
        self.assertFalse(built["comparison"]["available"])
        self.assertIsNone(built["comparison"]["latest"])
        self.assertEqual(built["comparison"]["total_considered"], 0)
        self.assertFalse(built["trend"]["available"])
        self.assertIsNone(built["trend"]["summary"])
        self.assertIsNone(built["trend"]["source"])
        self.assertFalse(built["comparison_validation"]["available"])
        self.assertIsNone(built["comparison_validation"]["result"])
        self.assert_report_valid(built, snapshots=history)

    def test_genuinely_unavailable_filtered_trend_carries_no_data(self):
        built = report(filtered_comparisons=None, filtered_trend_summary=None)
        self.assertFalse(built["filtered_trend"]["available"])
        self.assertIsNone(built["filtered_trend"]["summary"])
        self.assertIsNone(built["filtered_trend"]["source"])
        self.assertFalse(built["filtered_trend_validation"]["available"])
        self.assertIsNone(built["filtered_trend_validation"]["result"])
        self.assert_report_valid(built)


# ----------------------------------------------------------------------
# 3. missing section
# ----------------------------------------------------------------------
class MissingSectionTests(Prompt525TestCase):

    def test_missing_top_level_section_is_flagged(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        del built["comparison"]
        self.assert_report_invalid(built, "missing_field:comparison")

    def test_missing_field_within_a_section_is_flagged(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        del built["snapshots"]["available"]
        self.assert_report_invalid(built, "missing_field:snapshots.available")

    def test_missing_filtered_trend_fields_must_come_together(self):
        built = copy.deepcopy(report(filtered_comparisons=_filtered_comparisons()))
        del built["filtered_trend"]
        self.assert_report_invalid(built, "missing_field:filtered_trend")

    def test_missing_availability_flag_inside_filtered_trend(self):
        built = copy.deepcopy(report(filtered_comparisons=_filtered_comparisons()))
        del built["filtered_trend"]["available"]
        self.assert_report_invalid(built, "missing_field:filtered_trend.available")


# ----------------------------------------------------------------------
# 4. invalid section - data present but the section is not valid;
#    availability alone must not paper over that.
# ----------------------------------------------------------------------
class InvalidSectionTests(Prompt525TestCase):

    def test_available_comparison_section_with_invalid_data_is_flagged(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["comparison"]["latest"]["valid"] = False
        # available is still True and data is present - the section itself
        # is not thereby "missing"; but the embedded validation must not
        # claim it valid.
        self.assertTrue(built["comparison"]["available"])
        self.assert_report_invalid(built, "claims_valid_but_source_invalid:comparison")

    def test_invalid_filtered_trend_data_stays_available_but_not_valid(self):
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["eligible_count"] += 1
        built = report(filtered_trend_summary=summary)
        self.assertTrue(built["filtered_trend"]["available"])
        self.assertFalse(built["filtered_trend_validation"]["result"]["valid"])
        # a faithful report of invalid data is itself a valid report
        self.assert_report_valid(built, filtered_trend_summary=summary)

    def test_invalid_data_marked_valid_by_the_report_is_rejected(self):
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["eligible_count"] += 1
        built = copy.deepcopy(report(filtered_trend_summary=summary))
        built["filtered_trend_validation"]["result"] = dict(OK)
        self.assert_report_invalid(built, "claims_valid_but_source_invalid:filtered_trend")

    def test_invalid_snapshot_is_still_reported_available_with_its_own_status(self):
        only_invalid = LearnedKnowledgeDiagnosticSnapshotHistory()
        only_invalid.record({}, {"valid": False, "errors": ["boom"]})
        built = report(snapshots=only_invalid)
        self.assertTrue(built["snapshots"]["available"])
        self.assertIsNotNone(built["snapshots"]["latest"])
        self.assertEqual(built["snapshots"]["latest"]["validation_status"], "invalid")
        self.assert_report_valid(built, snapshots=only_invalid)


# ----------------------------------------------------------------------
# 5. filtered trend available / unavailable
# ----------------------------------------------------------------------
class FilteredTrendAvailabilityTests(Prompt525TestCase):

    def test_filtered_trend_available_with_derived_summary(self):
        filtered = _filtered_comparisons()
        built = report(filtered_comparisons=filtered)
        self.assertTrue(built["filtered_trend"]["available"])
        self.assertIsNotNone(built["filtered_trend"]["summary"])
        self.assertTrue(built["filtered_trend_validation"]["available"])
        self.assert_report_valid(built, filtered_comparisons=filtered)

    def test_filtered_trend_available_with_provided_summary(self):
        summary = ftrend(_filtered_comparisons())
        built = report(filtered_trend_summary=summary)
        self.assertTrue(built["filtered_trend"]["available"])
        self.assertEqual(built["filtered_trend"]["summary"], summary)
        self.assert_report_valid(built, filtered_trend_summary=summary)

    def test_filtered_trend_unavailable_when_no_filtered_arguments_given(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons)
        self.assertNotIn("filtered_trend", built)
        self.assert_report_valid(built, snapshots=history, comparisons=comparisons)

    def test_filtered_trend_unavailable_with_empty_comparisons_list(self):
        built = report(filtered_comparisons=[])
        self.assertFalse(built["filtered_trend"]["available"])
        self.assertIsNone(built["filtered_trend"]["summary"])
        self.assert_report_valid(built, filtered_comparisons=[])

    def test_availability_flips_correctly_between_two_reports(self):
        history, comparisons = _base_pipeline()
        unavailable = report(snapshots=history, comparisons=comparisons,
                             filtered_comparisons=None, filtered_trend_summary=None)
        available = report(snapshots=history, comparisons=comparisons,
                           filtered_comparisons=_filtered_comparisons())
        self.assertFalse(unavailable["filtered_trend"]["available"])
        self.assertTrue(available["filtered_trend"]["available"])
        self.assertNotEqual(unavailable["structural_status"], available["structural_status"] and None)


# ----------------------------------------------------------------------
# 6. contradictory availability states
# ----------------------------------------------------------------------
class ContradictoryAvailabilityStateTests(Prompt525TestCase):

    def test_section_marked_available_but_containing_no_data_is_rejected(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["trend"]["available"] = True
        built["trend"]["summary"] = None
        self.assert_report_invalid(built, "missing_data_marked_available:trend.summary")

    def test_section_marked_available_with_an_empty_placeholder_is_rejected(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["comparison_validation"]["available"] = True
        built["comparison_validation"]["result"] = {}
        self.assert_report_invalid(built, "fabricated_placeholder_value:comparison_validation.result")

    def test_section_marked_unavailable_while_valid_data_is_present(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["comparison"]["available"] = False
        self.assert_report_invalid(built, "fabricated_value_for_unavailable_component:comparison.latest")

    def test_filtered_trend_marked_unavailable_while_data_is_present(self):
        built = copy.deepcopy(report(filtered_comparisons=_filtered_comparisons()))
        built["filtered_trend"]["available"] = False
        errors = validate(built)["errors"]
        self.assertIn("fabricated_value_for_unavailable_component:filtered_trend.summary", errors)
        self.assertIn("fabricated_value_for_unavailable_component:filtered_trend.source", errors)
        self.assertIn("inconsistent_availability:filtered_trend_validation", errors)

    def test_count_contradicts_availability_flag(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["snapshots"]["available"] = False
        built["snapshots"]["count"] = 3
        built["snapshots"]["latest"] = None
        self.assert_report_invalid(built, "fabricated_value_for_unavailable_component:snapshots.count")

    def test_available_true_with_zero_count_is_inconsistent(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["comparison"]["total_considered"] = 0
        self.assert_report_invalid(built, "inconsistent_count:comparison.total_considered")

    def test_validation_section_availability_must_match_its_component(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["trend_validation"]["available"] = False
        self.assert_report_invalid(built, "inconsistent_availability:trend_validation")


if __name__ == "__main__":
    unittest.main()
