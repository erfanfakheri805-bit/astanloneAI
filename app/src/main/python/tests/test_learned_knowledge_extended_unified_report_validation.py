"""
Tests for Prompt 523 - Validate Extended Unified Diagnostic Report.

Prompt 522 extended the Unified Diagnostic Report
(`build_learned_knowledge_diagnostic_report()`) to optionally carry the
Prompt 520/521 filtered diagnostic trend (`"filtered_trend"`,
`"filtered_trend_validation"`, `"section_origins"`), and extended its
existing validator (`validate_learned_knowledge_diagnostic_report()`,
Prompt 514) to check those sections too - reusing the Prompt 521 filtered
trend validator, the Prompt 512/514 patterns, and the Prompt 513 report
builder itself (to recompute an expected report from any given filtered
sources), rather than building a second, parallel validation system.

This module does not add or change any production code: the extended
validation layer this prompt asks for already exists (see
`validate_learned_knowledge_diagnostic_report()` in
learning/learned_knowledge_statistics.py, together with
`_check_filtered_trend_section()`, `_check_section_origins()`,
`_filtered_trend_validation_problem()`, `_check_report_against_sources()`
and `_check_status_consistency()`). What follows are focused,
self-contained tests that exercise exactly the Prompt 523 checklist
end-to-end, as an explicit, independently readable record that every
required case is actually covered:

    1.  valid extended unified reports
    2.  invalid existing sections
    3.  valid filtered trend section
    4.  invalid filtered trend section
    5.  missing filtered trend section
    6.  inconsistent filtered trend validation
    7.  invalid selected-section metadata (section_origins)
    8.  invalid chronology
    9.  contradictory validity states
    10. zero-evaluation data
    11. sparse / partial reports
    12. malformed input
    13. deterministic validation results
    14. no mutation of the original report

Run directly:
    python -m unittest tests.test_learned_knowledge_extended_unified_report_validation -v
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
    REPORT_STATUS_NO_DATA, REPORT_STATUS_PARTIAL, REPORT_STATUS_VALID, REPORT_STATUS_INVALID,
    TREND_SOURCE_DERIVED,
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
    """Real snapshots plus their ordered comparisons."""
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
    """Real filtered snapshots (sequences 1..n) from one history;
    `specs` is `[(sections, counts), ...]`."""
    history = LearnedKnowledgeFilteredSummarySnapshotHistory()
    return [history.record_filtered_summary(filt(_filtered_summary(counts), sections))
            for sections, counts in specs]


def _filtered_comparisons(totals=(1, 2, 5), sections=_ALL):
    snaps = _filtered_snapshots([(sections, {"accepted": n}) for n in totals])
    return [compare(snaps[i], snaps[i + 1]) for i in range(len(snaps) - 1)]


class Prompt523TestCase(unittest.TestCase):
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
# 1. valid extended unified reports
# ----------------------------------------------------------------------
class ValidExtendedReportTests(Prompt523TestCase):

    def test_fully_populated_extended_report_is_valid(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assertEqual(built["structural_status"], REPORT_STATUS_VALID)
        self.assert_report_valid(built)
        self.assert_report_valid(
            built, snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)

    def test_valid_extended_report_with_provided_filtered_trend(self):
        filtered = _filtered_comparisons()
        summary = ftrend(filtered)
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons, filtered_trend_summary=summary)
        self.assert_report_valid(built)
        self.assert_report_valid(built, filtered_trend_summary=summary)


# ----------------------------------------------------------------------
# 2. invalid existing sections (pre-522 territory, still covered here in
#    an extended report so the filtered addition cannot mask it)
# ----------------------------------------------------------------------
class InvalidExistingSectionTests(Prompt523TestCase):

    def test_tampered_snapshot_metric_is_caught_alongside_a_filtered_trend(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = copy.deepcopy(
            report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered))
        built["snapshots"]["latest"]["total_evaluations"] += 5
        self.assert_report_invalid(built, "snapshots.latest:")

    def test_comparison_validation_claiming_valid_for_invalid_comparison_is_caught(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = copy.deepcopy(
            report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered))
        built["comparison"]["latest"]["valid"] = False
        built["comparison_validation"]["result"] = dict(OK)
        self.assert_report_invalid(built, "claims_valid_but_source_invalid:comparison")

    def test_missing_pre_522_field_is_still_flagged_in_an_extended_report(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = copy.deepcopy(
            report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered))
        del built["trend"]
        self.assert_report_invalid(built, "missing_field:trend")


# ----------------------------------------------------------------------
# 3. valid filtered trend section
# ----------------------------------------------------------------------
class ValidFilteredTrendSectionTests(Prompt523TestCase):

    def test_derived_filtered_trend_section_has_expected_structure(self):
        filtered = _filtered_comparisons()
        built = report(filtered_comparisons=filtered)
        section = built["filtered_trend"]
        self.assertEqual(list(section.keys()), ["available", "source", "summary"])
        self.assertTrue(section["available"])
        self.assertEqual(section["source"], TREND_SOURCE_DERIVED)
        validation = built["filtered_trend_validation"]
        self.assertEqual(list(validation.keys()), ["available", "result"])
        self.assertEqual(validation["result"], OK)
        self.assert_report_valid(built, filtered_comparisons=filtered)

    def test_valid_filtered_trend_validation_result_has_expected_structure(self):
        built = report(filtered_comparisons=_filtered_comparisons())
        result = built["filtered_trend_validation"]["result"]
        self.assertEqual(sorted(result.keys()), sorted(["valid", "well_formed", "errors", "warnings"]))
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])


# ----------------------------------------------------------------------
# 4. invalid filtered trend section
# ----------------------------------------------------------------------
class InvalidFilteredTrendSectionTests(Prompt523TestCase):

    def test_invalid_filtered_trend_data_cannot_be_reported_as_fully_valid(self):
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["eligible_count"] += 1
        built = report(filtered_trend_summary=summary)
        self.assertFalse(built["filtered_trend_validation"]["result"]["valid"])
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        # a faithful report of an invalid filtered trend is itself valid
        self.assert_report_valid(built, filtered_trend_summary=summary)

    def test_filtered_trend_validation_status_matches_actual_filtered_trend_data(self):
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["eligible_count"] += 1
        built = report(filtered_trend_summary=summary)
        built["filtered_trend_validation"]["result"] = dict(OK)
        self.assert_report_invalid(built, "claims_valid_but_source_invalid:filtered_trend")

    def test_report_never_raises_on_malformed_filtered_trend_data(self):
        for value in (None, 5, "x", [], {}, "junk"):
            with self.subTest(value=value):
                built = report(filtered_trend_summary=value if value != "junk" else "junk")
                self.assertIn(built["structural_status"], (REPORT_STATUS_INVALID, REPORT_STATUS_NO_DATA))
                self.assert_report_valid(built)


# ----------------------------------------------------------------------
# 5. missing filtered trend section
# ----------------------------------------------------------------------
class MissingFilteredTrendSectionTests(Prompt523TestCase):

    def test_missing_filtered_trend_is_unavailable_not_fabricated(self):
        built = report(filtered_trend_summary=None)
        self.assertEqual(built["filtered_trend"], {"available": False, "source": None, "summary": None})
        self.assertEqual(built["filtered_trend_validation"], {"available": False, "result": None})
        self.assert_report_valid(built)

    def test_fabricated_value_for_unavailable_filtered_trend_is_rejected(self):
        built = copy.deepcopy(report(filtered_trend_summary=None))
        built["filtered_trend"]["available"] = True
        self.assertIn(
            "missing_data_marked_available:filtered_trend.summary",
            validate(built)["errors"])

    def test_a_plain_pre_522_report_needs_no_filtered_sections_at_all(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons)
        self.assertNotIn("filtered_trend", built)
        self.assert_report_valid(built)


# ----------------------------------------------------------------------
# 6. inconsistent filtered trend validation
# ----------------------------------------------------------------------
class InconsistentFilteredTrendValidationTests(Prompt523TestCase):

    def test_validation_result_internally_contradicting_itself_is_caught(self):
        built = copy.deepcopy(report(filtered_comparisons=_filtered_comparisons()))
        built["filtered_trend_validation"]["result"]["valid"] = False
        self.assert_report_invalid(built, "contradictory_validation_state:filtered_trend_validation.result")

    def test_availability_mismatch_between_section_and_its_validation_is_caught(self):
        built = copy.deepcopy(report(filtered_comparisons=_filtered_comparisons()))
        built["filtered_trend_validation"]["available"] = False
        self.assert_report_invalid(built, "inconsistent_availability:filtered_trend_validation")

    def test_validation_disagreeing_with_recomputed_result_is_caught(self):
        filtered = _filtered_comparisons((1, 2, 5))
        other = _filtered_comparisons((1, 2, 3))
        stale_summary = ftrend(other)
        built = report(filtered_comparisons=filtered, filtered_trend_summary=stale_summary)
        result = built["filtered_trend_validation"]["result"]
        self.assertFalse(result["valid"])
        self.assertTrue(any(error.startswith("mismatched_") for error in result["errors"]))
        self.assert_report_valid(built)


# ----------------------------------------------------------------------
# 7. invalid selected-section metadata (section_origins)
# ----------------------------------------------------------------------
class InvalidSelectedSectionMetadataTests(Prompt523TestCase):

    def setUp(self):
        self.built = report(filtered_comparisons=_filtered_comparisons())

    def test_section_origins_must_be_present_with_the_other_filtered_fields(self):
        built = copy.deepcopy(self.built)
        del built["section_origins"]
        self.assert_report_invalid(built, "missing_field:section_origins")

    def test_misstated_origin_is_caught(self):
        built = copy.deepcopy(self.built)
        built["section_origins"]["filtered_trend"] = "source"
        self.assert_report_invalid(built, "misstated_origin:filtered_trend")

    def test_missing_origin_entry_is_caught(self):
        built = copy.deepcopy(self.built)
        del built["section_origins"]["snapshots"]
        self.assert_report_invalid(built, "missing_field:section_origins.snapshots")

    def test_unexpected_origin_entry_is_caught(self):
        built = copy.deepcopy(self.built)
        built["section_origins"]["bogus"] = "source"
        self.assert_report_invalid(built, "unexpected_field:section_origins.bogus")

    def test_non_dict_section_origins_is_caught_without_raising(self):
        built = copy.deepcopy(self.built)
        built["section_origins"] = ["not", "a", "dict"]
        self.assert_report_invalid(built, "invalid_type:section_origins")


# ----------------------------------------------------------------------
# 8. invalid chronology
# ----------------------------------------------------------------------
class InvalidChronologyTests(Prompt523TestCase):

    def test_reversed_filtered_chronological_range_is_caught(self):
        built = copy.deepcopy(report(filtered_comparisons=_filtered_comparisons()))
        built["filtered_trend"]["summary"]["chronological_range"].update(
            {"earlier": {"snapshot_id": "learned_knowledge_snapshot_000009", "sequence": 9}})
        self.assert_report_invalid(
            built, "invalid_chronological_ordering:filtered_trend.chronological_range")

    def test_reversed_trend_chronological_range_is_still_caught_in_an_extended_report(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(
            report(snapshots=history, comparisons=comparisons,
                   filtered_comparisons=_filtered_comparisons()))
        built["trend"]["summary"]["chronological_range"]["earlier"] = \
            built["trend"]["summary"]["chronological_range"]["later"]
        self.assert_report_invalid(built, "invalid_chronological_ordering:trend.chronological_range")

    def test_out_of_order_source_snapshots_are_caught_with_sources_given(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons)
        reversed_snapshots = list(reversed(history.get_all()))
        result = validate(built, snapshots=reversed_snapshots)
        self.assertIn("invalid_chronological_ordering:snapshots", result["errors"])

    def test_unordered_filtered_chronology_is_a_reported_state_not_an_error(self):
        # Prompt 520 itself reports a reversed filtered chronology via
        # chronology.ordered=False; that is not, by itself, a report error.
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["chronology"]["ordered"] = False
        built = report(filtered_trend_summary=summary)
        errors = validate(built)["errors"]
        self.assertFalse(
            any(error.startswith("invalid_chronological_ordering:filtered_trend")
                for error in errors))


# ----------------------------------------------------------------------
# 9. contradictory validity states
# ----------------------------------------------------------------------
class ContradictoryValidityStateTests(Prompt523TestCase):

    def test_structural_status_contradicting_filtered_trend_validity_is_caught(self):
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["eligible_count"] += 1
        built = report(filtered_trend_summary=summary)
        built["structural_status"] = REPORT_STATUS_PARTIAL
        self.assert_report_invalid(built, "inconsistent_structural_status")

    def test_top_level_valid_true_with_errors_present_is_rejected(self):
        built = copy.deepcopy(report(filtered_comparisons=_filtered_comparisons()))
        built["errors"] = ["something"]
        self.assert_report_invalid(built, "invalid_report_errors_value")

    def test_validation_result_valid_true_but_well_formed_false_is_rejected(self):
        built = copy.deepcopy(report(filtered_comparisons=_filtered_comparisons()))
        built["filtered_trend_validation"]["result"]["well_formed"] = False
        self.assert_report_invalid(
            built, "contradictory_validation_state:filtered_trend_validation.result.well_formed")

    def test_unavailable_component_may_not_carry_a_fabricated_value(self):
        built = copy.deepcopy(report(filtered_comparisons=_filtered_comparisons()))
        built["filtered_trend"]["available"] = False
        errors = validate(built)["errors"]
        self.assertIn("fabricated_value_for_unavailable_component:filtered_trend.summary", errors)
        self.assertIn("fabricated_value_for_unavailable_component:filtered_trend.source", errors)


# ----------------------------------------------------------------------
# 10. zero-evaluation data
# ----------------------------------------------------------------------
class ZeroEvaluationTests(Prompt523TestCase):

    def test_zero_evaluation_filtered_comparisons_validate_cleanly(self):
        snaps = _filtered_snapshots(
            [(["evaluation_counts", "rates"], {"accepted": 0}),
             (["evaluation_counts", "rates"], {"accepted": 0})])
        comparisons = [compare(snaps[0], snaps[1])]
        built = report(filtered_comparisons=comparisons)
        summary = built["filtered_trend"]["summary"]
        self.assertEqual(summary["numeric"]["total_evaluations"]["end"], 0)
        self.assertEqual(built["filtered_trend_validation"]["result"], OK)
        self.assert_report_valid(built, filtered_comparisons=comparisons)

    def test_zero_evaluation_report_is_not_confused_with_missing_data(self):
        snaps = _filtered_snapshots(
            [(["evaluation_counts", "rates"], {"accepted": 0}),
             (["evaluation_counts", "rates"], {"accepted": 0})])
        comparisons = [compare(snaps[0], snaps[1])]
        built = report(filtered_comparisons=comparisons)
        self.assertTrue(built["filtered_trend"]["available"])
        self.assertIsNotNone(built["filtered_trend"]["summary"])


# ----------------------------------------------------------------------
# 11. sparse / partial reports
# ----------------------------------------------------------------------
class SparsePartialReportTests(Prompt523TestCase):

    def test_filtered_only_report_is_partial_and_still_valid(self):
        built = report(filtered_comparisons=_filtered_comparisons())
        self.assertEqual(built["structural_status"], REPORT_STATUS_PARTIAL)
        self.assertFalse(built["snapshots"]["available"])
        self.assertFalse(built["comparison"]["available"])
        self.assertTrue(built["filtered_trend"]["available"])
        self.assert_report_valid(built)

    def test_snapshots_only_with_no_filtered_data_is_partial(self):
        history, _ = _base_pipeline()
        built = report(snapshots=history, filtered_comparisons=None)
        self.assertEqual(built["structural_status"], REPORT_STATUS_PARTIAL)
        self.assert_report_valid(built)

    def test_completely_empty_report_is_no_data_and_still_valid(self):
        built = report()
        self.assertEqual(built["structural_status"], REPORT_STATUS_NO_DATA)
        self.assertNotIn("filtered_trend", built)
        self.assert_report_valid(built)

    def test_empty_report_with_only_filtered_arguments_absent_is_no_data(self):
        built = report(filtered_comparisons=None, filtered_trend_summary=None)
        self.assertEqual(built["structural_status"], REPORT_STATUS_NO_DATA)
        self.assertFalse(built["filtered_trend"]["available"])
        self.assert_report_valid(built)


# ----------------------------------------------------------------------
# 12. malformed input
# ----------------------------------------------------------------------
class MalformedInputTests(Prompt523TestCase):

    def test_non_dict_report_yields_structured_result_not_an_exception(self):
        for bad in (None, 5, "junk", [], ()):
            with self.subTest(bad=bad):
                result = validate(bad)
                self.assertEqual(result, {
                    "valid": False, "well_formed": False,
                    "errors": ["report_not_a_dict"], "warnings": [],
                })

    def test_odd_filtered_trend_section_values_never_raise(self):
        built = report(filtered_comparisons=_filtered_comparisons())
        for value in (None, 5, "x", [], {}):
            with self.subTest(value=value):
                tampered = copy.deepcopy(built)
                tampered["filtered_trend"] = value
                self.assertFalse(validate(tampered)["valid"])
                tampered2 = copy.deepcopy(built)
                tampered2["filtered_trend_validation"] = value
                self.assertFalse(validate(tampered2)["valid"])

    def test_non_sequence_filtered_comparisons_source_is_rejected_not_raised(self):
        built = report(filtered_comparisons="abc")
        self.assertEqual(built["filtered_trend"]["summary"]["errors"], ["comparisons_not_a_sequence"])
        self.assert_report_valid(built)
        result = validate(built, filtered_comparisons="abc")
        self.assertIn("invalid_source:filtered_comparisons", result["errors"])

    def test_empty_dict_report_is_reported_with_every_missing_field(self):
        result = validate({})
        self.assertFalse(result["valid"])
        self.assertTrue(any(error.startswith("missing_field:") for error in result["errors"]))


# ----------------------------------------------------------------------
# 13. deterministic validation results
# ----------------------------------------------------------------------
class DeterminismTests(Prompt523TestCase):

    def test_repeated_validation_of_the_same_report_is_identical(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        results = [validate(built, snapshots=history, comparisons=comparisons,
                            filtered_comparisons=filtered) for _ in range(5)]
        self.assertTrue(all(result == results[0] for result in results))

    def test_repeated_validation_of_an_invalid_report_is_identical(self):
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["eligible_count"] += 1
        built = report(filtered_trend_summary=summary)
        results = [validate(built) for _ in range(5)]
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(results[0]["errors"], sorted(results[0]["errors"], key=results[0]["errors"].index))

    def test_error_order_is_fixed_across_calls(self):
        built = copy.deepcopy(report(filtered_comparisons=_filtered_comparisons()))
        del built["trend"]
        del built["section_origins"]
        first = validate(built)["errors"]
        second = validate(built)["errors"]
        self.assertEqual(first, second)


# ----------------------------------------------------------------------
# 14. no mutation of the original report
# ----------------------------------------------------------------------
class NoMutationTests(Prompt523TestCase):

    def test_validating_a_valid_report_does_not_change_it(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        before = copy.deepcopy(built)
        validate(built, snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assertEqual(built, before)

    def test_validating_an_invalid_report_does_not_repair_it(self):
        filtered = _filtered_comparisons()
        summary = copy.deepcopy(ftrend(filtered))
        summary["eligible_count"] += 1
        built = report(filtered_trend_summary=summary)
        before = copy.deepcopy(built)
        validate(built)
        self.assertEqual(built, before)
        self.assertEqual(built["filtered_trend"]["summary"]["eligible_count"], summary["eligible_count"])

    def test_source_snapshots_and_comparisons_are_not_mutated_by_validation(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        history_before = copy.deepcopy(history.get_all())
        comparisons_before = copy.deepcopy(comparisons)
        filtered_before = copy.deepcopy(filtered)
        validate(built, snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assertEqual(history.get_all(), history_before)
        self.assertEqual(comparisons, comparisons_before)
        self.assertEqual(filtered, filtered_before)

    def test_validation_result_is_independent_of_the_report_dict(self):
        built = report(filtered_comparisons=_filtered_comparisons())
        result = validate(built)
        built["structural_status"] = "tampered_after_the_fact"
        self.assertNotEqual(result.get("structural_status"), "tampered_after_the_fact")
        self.assertNotIn("structural_status", result)


if __name__ == "__main__":
    unittest.main()
