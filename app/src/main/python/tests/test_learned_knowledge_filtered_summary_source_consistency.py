"""
Tests for Prompt 533 - Validate Filtered Diagnostic Summary (against its
source summary).

`validate_learned_knowledge_diagnostic_report()` (Prompt 514,
learning/learned_knowledge_statistics.py) already holds an optional
`filtered_summary` (Prompt 516) to a summary RECOMPUTED FROM THE REPORT
(Prompt 532). This prompt adds a further, independent check: whenever the
caller also hands in the actual `summary` (Prompt 515) the filtered one
claims to have been filtered from, `filtered_summary` is additionally held
directly to THAT summary - its real, immediate source - regardless of
whatever the report itself says.

Nothing here is a second summary/filter system: the "expected" filtered
summary is obtained by calling the existing, unmodified Prompt 516
`filter_learned_knowledge_diagnostic_summary()` on the given `summary`
itself, using the very `requested_sections` the given filtered summary
already claims to have used, and diffed with the same machinery every
other source cross-check in this validator already uses.

Covers:
    1.  a valid filtered summary matching its source
    2.  a section reported included that is missing from the source
    3.  a section that must remain unavailable
    4.  an unknown section incorrectly marked included
    5.  inconsistent selected-section metadata (requested/included/
        unavailable/unknown no longer agreeing)
    6.  a modified/mismatched filtered value
    7.  filtered trend information
    8.  an empty source summary

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_summary_source_consistency -v
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
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
)

OK = {"valid": True, "well_formed": True, "errors": [], "warnings": []}


def _gtrace():
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(STATUS_PASSED, REASON_OK))


def _stats(accepted=0):
    stats = LearnedKnowledgeDecisionStatistics()
    for _ in range(accepted):
        stats.record(_gtrace())
    return stats


def _history(counts):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for n in counts:
        history.record_statistics(_stats(n))
    return history


def _full_pipeline(counts=(1, 2, 4)):
    """Real snapshots, their ordered comparisons, the report built from
    them, its own real Prompt 514 validation, and the real Prompt 515
    summary built from that - i.e. exactly what a real caller would
    produce end to end."""
    history = _history(counts)
    comparisons = [history.compare_sequences(i, i + 1) for i in range(1, len(counts))]
    built = report(snapshots=history, comparisons=comparisons)
    validation = validate(built, snapshots=history, comparisons=comparisons)
    summary = fmt(built, validation)
    return history, comparisons, built, validation, summary


class Prompt533TestCase(unittest.TestCase):
    def assert_consistent(self, built, **kwargs):
        result = validate(built, **kwargs)
        self.assertEqual(result, OK, result)

    def assert_source_inconsistent(self, built, *expected_error_prefixes, **kwargs):
        result = validate(built, **kwargs)
        self.assertFalse(result["valid"], result)
        for prefix in expected_error_prefixes:
            self.assertTrue(
                any(error.startswith(prefix) for error in result["errors"]),
                "expected an error starting with %r in %r" % (prefix, result["errors"]))


# ----------------------------------------------------------------------
# 1. a valid filtered summary matching its source
# ----------------------------------------------------------------------
class ValidFilteredSummaryTests(Prompt533TestCase):

    def test_matching_filtered_summary_against_its_source_is_consistent(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "trend"])
        self.assert_consistent(built, summary=summary, filtered_summary=filtered)

    def test_deep_copied_filtered_summary_still_matches(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["evaluation_counts"])
        self.assert_consistent(
            built, summary=summary, filtered_summary=copy.deepcopy(filtered))

    def test_filtered_summary_alone_never_triggers_the_source_check(self):
        # With no `summary` given, there is no direct source to hold
        # `filtered_summary` to beyond the report-recomputed one - the
        # new check simply does not run.
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        self.assert_consistent(built, filtered_summary=filtered)

    def test_check_only_fires_against_the_actual_summary_not_the_report(self):
        # `summary` itself disagrees with the report (its own
        # "summary"/"filtered_summary" report-based check fails), but
        # `filtered_summary` is faithfully filtered from that very
        # `summary` - so the NEW source-based check contributes no
        # errors of its own, even though the report-based ones do fire.
        _, _, built, _, summary = _full_pipeline()
        tampered_summary = copy.deepcopy(summary)
        tampered_summary["available_sections"].remove("trend")
        tampered_summary["unavailable_sections"].append("trend")
        tampered_summary["metrics"]["trend"] = None
        filtered = filt(tampered_summary, ["trend", "rates"])
        result = validate(built, summary=tampered_summary, filtered_summary=filtered)
        self.assertFalse(result["valid"], result)
        self.assertFalse(
            any(error.startswith("filtered_summary_source") for error in result["errors"]),
            result["errors"])
        self.assertTrue(
            any(error.startswith("source_mismatch:summary") for error in result["errors"]),
            result["errors"])


# ----------------------------------------------------------------------
# 2. a section reported included that is missing from the source
# ----------------------------------------------------------------------
class MissingSourceSectionTests(Prompt533TestCase):

    def test_included_section_absent_from_source_is_detected(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        tampered = copy.deepcopy(filtered)
        # Claim a section is included that "rates"-only filtering never
        # actually included.
        tampered["included_sections"].append("comparison_changes")
        tampered["metrics"]["comparison_changes"] = {"identical": True}
        self.assert_source_inconsistent(
            built, "source_mismatch:filtered_summary_source",
            summary=summary, filtered_summary=tampered)

    def test_included_section_not_offered_by_a_partial_source_is_detected(self):
        history = _history((1, 2, 3))
        built = report(snapshots=history)
        validation = validate(built, snapshots=history)
        summary = fmt(built, validation)
        self.assertIn("trend", summary["unavailable_sections"])
        filtered = filt(summary, ["evaluation_counts"])
        tampered = copy.deepcopy(filtered)
        tampered["included_sections"].append("trend")
        tampered["metrics"]["trend"] = {"source": "fabricated"}
        self.assert_source_inconsistent(
            built, "source_mismatch:filtered_summary_source",
            snapshots=history, summary=summary, filtered_summary=tampered)


# ----------------------------------------------------------------------
# 3. a section that must remain unavailable
# ----------------------------------------------------------------------
class UnavailableSectionRemainsUnavailableTests(Prompt533TestCase):

    def test_genuinely_unavailable_section_stays_unavailable_and_is_consistent(self):
        history = _history((1, 2, 3))
        built = report(snapshots=history)
        validation = validate(built, snapshots=history)
        summary = fmt(built, validation)
        filtered = filt(summary, ["comparison_changes", "trend"])
        self.assertEqual(filtered["included_sections"], [])
        self.assertEqual(filtered["unavailable_sections"], ["comparison_changes", "trend"])
        self.assert_consistent(
            built, snapshots=history, summary=summary, filtered_summary=filtered)

    def test_promoting_an_unavailable_section_to_included_is_detected(self):
        history = _history((1, 2, 3))
        built = report(snapshots=history)
        validation = validate(built, snapshots=history)
        summary = fmt(built, validation)
        filtered = filt(summary, ["comparison_changes"])
        tampered = copy.deepcopy(filtered)
        tampered["unavailable_sections"].remove("comparison_changes")
        tampered["included_sections"].append("comparison_changes")
        tampered["metrics"]["comparison_changes"] = {"identical": True}
        self.assert_source_inconsistent(
            built, "source_mismatch:filtered_summary_source",
            snapshots=history, summary=summary, filtered_summary=tampered)


# ----------------------------------------------------------------------
# 4. an unknown section incorrectly marked included
# ----------------------------------------------------------------------
class UnknownSectionTests(Prompt533TestCase):

    def test_unknown_name_is_correctly_kept_out_of_included_and_is_consistent(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "not_a_real_section"])
        self.assertEqual(filtered["unknown_sections"], ["not_a_real_section"])
        self.assertNotIn("not_a_real_section", filtered["included_sections"])
        self.assert_consistent(built, summary=summary, filtered_summary=filtered)

    def test_unknown_section_incorrectly_included_is_detected(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "not_a_real_section"])
        tampered = copy.deepcopy(filtered)
        tampered["unknown_sections"] = []
        tampered["included_sections"].append("not_a_real_section")
        tampered["metrics"]["not_a_real_section"] = "fabricated"
        self.assert_source_inconsistent(
            built, "source_mismatch:filtered_summary_source",
            summary=summary, filtered_summary=tampered)


# ----------------------------------------------------------------------
# 5. inconsistent selected-section metadata
# ----------------------------------------------------------------------
class InconsistentSelectedSectionMetadataTests(Prompt533TestCase):

    def test_section_listed_as_both_included_and_unavailable_is_detected(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "trend"])
        self.assertEqual(filtered["included_sections"], ["rates", "trend"])
        tampered = copy.deepcopy(filtered)
        # "trend" now appears in both lists at once - self-inconsistent
        # metadata, regardless of whether it also disagrees with `summary`.
        tampered["unavailable_sections"].append("trend")
        self.assert_source_inconsistent(
            built, "source_mismatch:filtered_summary_source",
            summary=summary, filtered_summary=tampered)

    def test_requested_section_missing_from_every_list_is_detected(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "trend"])
        tampered = copy.deepcopy(filtered)
        # "trend" silently dropped out of included_sections and not moved
        # anywhere else - requested/included/unavailable/unknown no
        # longer account for it.
        tampered["included_sections"].remove("trend")
        self.assert_source_inconsistent(
            built, "source_mismatch:filtered_summary_source",
            summary=summary, filtered_summary=tampered)


# ----------------------------------------------------------------------
# 6. a modified/mismatched filtered value
# ----------------------------------------------------------------------
class ModifiedFilteredValueTests(Prompt533TestCase):

    def test_mismatched_filtered_value_is_detected(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        tampered = copy.deepcopy(filtered)
        tampered["metrics"]["rates"]["acceptance_rate"] = 0.0
        self.assert_source_inconsistent(
            built, "source_mismatch:filtered_summary_source.metrics",
            summary=summary, filtered_summary=tampered)

    def test_matching_filtered_value_is_not_flagged(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["evaluation_counts"])
        self.assert_consistent(built, summary=summary, filtered_summary=filtered)


# ----------------------------------------------------------------------
# 7. filtered trend information
# ----------------------------------------------------------------------
class FilteredTrendInformationTests(Prompt533TestCase):

    def test_matching_filtered_trend_is_consistent(self):
        _, _, built, _, summary = _full_pipeline()
        self.assertIn("trend", summary["available_sections"])
        filtered = filt(summary, ["trend"])
        self.assertIsNotNone(filtered["metrics"]["trend"])
        self.assert_consistent(built, summary=summary, filtered_summary=filtered)

    def test_mismatched_filtered_trend_field_is_detected(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["trend"])
        tampered = copy.deepcopy(filtered)
        tampered["metrics"]["trend"]["source"] = "fabricated_source"
        self.assert_source_inconsistent(
            built, "source_mismatch:filtered_summary_source.metrics",
            summary=summary, filtered_summary=tampered)


# ----------------------------------------------------------------------
# 8. an empty source summary
# ----------------------------------------------------------------------
class EmptySourceSummaryTests(Prompt533TestCase):

    def test_filtered_summary_of_an_empty_source_is_consistent(self):
        built = report()
        validation = validate(built)
        summary = fmt(built, validation)
        self.assertEqual(summary["available_sections"], ["validation_statuses"])
        filtered = filt(summary, ["validation_statuses", "trend"])
        self.assertEqual(filtered["included_sections"], ["validation_statuses"])
        self.assertEqual(filtered["unavailable_sections"], ["trend"])
        self.assert_consistent(built, summary=summary, filtered_summary=filtered)

    def test_empty_source_wrong_metric_is_detected(self):
        built = report()
        validation = validate(built)
        summary = fmt(built, validation)
        filtered = filt(summary, ["validation_statuses"])
        tampered = copy.deepcopy(filtered)
        tampered["metrics"]["validation_statuses"]["structural_status"] = "valid"
        self.assert_source_inconsistent(
            built, "source_mismatch:filtered_summary_source.metrics",
            summary=summary, filtered_summary=tampered)

    def test_empty_source_never_fabricates_an_included_section(self):
        built = report()
        validation = validate(built)
        summary = fmt(built, validation)
        filtered = filt(summary, ["validation_statuses"])
        tampered = copy.deepcopy(filtered)
        tampered["included_sections"].append("rates")
        tampered["unavailable_sections"] = [
            s for s in tampered["unavailable_sections"] if s != "rates"]
        tampered["metrics"]["rates"] = {"acceptance_rate": 1.0, "rejection_rate": 0.0}
        self.assert_source_inconsistent(
            built, "source_mismatch:filtered_summary_source",
            summary=summary, filtered_summary=tampered)


# ----------------------------------------------------------------------
# Never mutates, never repairs
# ----------------------------------------------------------------------
class NeverMutatesTests(Prompt533TestCase):

    def test_summary_is_never_mutated(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "trend"])
        before = copy.deepcopy(summary)
        validate(built, summary=summary, filtered_summary=filtered)
        self.assertEqual(summary, before)

    def test_filtered_summary_is_never_mutated(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "trend"])
        before = copy.deepcopy(filtered)
        validate(built, summary=summary, filtered_summary=filtered)
        self.assertEqual(filtered, before)

    def test_report_is_never_mutated(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates"])
        before = copy.deepcopy(built)
        validate(built, summary=summary, filtered_summary=filtered)
        self.assertEqual(built, before)

    def test_result_is_deterministic(self):
        _, _, built, _, summary = _full_pipeline()
        filtered = filt(summary, ["rates", "trend"])
        first = validate(built, summary=summary, filtered_summary=filtered)
        second = validate(built, summary=summary, filtered_summary=filtered)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
