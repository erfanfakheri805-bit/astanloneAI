"""
Tests for Prompt 522 - Integrate Filtered Diagnostic Trends into the
Unified Diagnostic Report.

`build_learned_knowledge_diagnostic_report()` (Prompt 513) and
`validate_learned_knowledge_diagnostic_report()` (Prompt 514) in
learning/learned_knowledge_statistics.py can now carry the filtered
diagnostic trend of Prompts 520-521 as an opt-in extension: a
`"filtered_trend"` section (the Prompt 520 summary, provided or derived by
the unmodified summarizer), a `"filtered_trend_validation"` section (the
unmodified Prompt 521 validator's result), and a fixed `"section_origins"`
map that says which sections hold source, derived, or validation
information. Nothing is recomputed, repaired, scored, ranked, predicted or
recommended, nothing is mutated, and a report built without the filtered
arguments is exactly the Prompt 513 report.

Covers:
    1.  valid filtered trend integrated into the unified report
    2.  invalid filtered trend integrated, validation status preserved
    3.  missing filtered trend
    4.  empty filtered trend
    5.  zero evaluations
    6.  one comparison
    7.  multiple comparisons
    8.  all comparisons invalid
    9.  mixed valid/invalid comparisons
    10. numeric trends preserved
    11. categorical trends preserved
    12. section availability preserved
    13. chronology information preserved
    14. unavailable / insufficient-data states preserved
    15. selected-section metadata preserved
    16. validation errors preserved
    17. source vs derived distinction preserved
    18. existing snapshot section remains intact
    19. existing comparison section remains intact
    20. existing trend section remains intact
    21. no duplicate diagnostic history created
    22. report generation does not mutate source data
    23. deterministic repeated report generation
    24. regression coverage for Prompt 513
    25. regression coverage for Prompt 514
    26. regression coverage for Prompts 520-521
    (plus report-validator coverage of the new sections, Prompt 515
    compatibility, and diagnostic-only isolation)

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_unified_report -v
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
from learning import learned_knowledge_statistics as lks
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    LearnedKnowledgeFilteredSummarySnapshotHistory,
    TREND_INCREASED, TREND_DECREASED, TREND_INSUFFICIENT_DATA, CHANGE_UNCHANGED,
    AVAILABILITY_CONSISTENT, AVAILABILITY_INTERMITTENT, AVAILABILITY_UNAVAILABLE,
    AVAILABILITY_INVALID,
    REPORT_STATUS_NO_DATA, REPORT_STATUS_PARTIAL, REPORT_STATUS_VALID, REPORT_STATUS_INVALID,
    TREND_SOURCE_PROVIDED, TREND_SOURCE_DERIVED,
    REPORT_ORIGIN_SOURCE, REPORT_ORIGIN_DERIVED_FROM_SNAPSHOTS,
    REPORT_ORIGIN_DERIVED_FROM_COMPARISONS, REPORT_ORIGIN_DERIVED_FROM_FILTERED_COMPARISONS,
    REPORT_ORIGIN_VALIDATION,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
    compare_learned_knowledge_filtered_summary_snapshots as compare,
    summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend as ftrend,
    validate_learned_knowledge_filtered_summary_snapshot_comparison_trend as validate_ftrend,
    summarize_learned_knowledge_diagnostic_snapshot_comparison_trend as trend,
    validate_learned_knowledge_diagnostic_snapshot_comparison_trend as validate_trend,
    validate_learned_knowledge_diagnostic_snapshot_comparison as validate_comparison,
)

_ALL = ["evaluation_counts", "rates", "dominant_rejection_reason",
        "comparison_changes", "trend", "validation_statuses"]
_SMALL = ["evaluation_counts", "rates", "dominant_rejection_reason"]
_NUMERIC = ["total_evaluations", "accepted_count", "rejected_count", "no_candidate_count",
            "acceptance_rate", "rejection_rate"]
_CATEGORICAL = ["dominant_rejection_reason", "comparison_changes", "trend", "validation_statuses"]

BASE_KEYS = ["valid", "errors", "structural_status", "snapshots", "comparison",
             "comparison_validation", "trend", "trend_validation"]
FILTERED_KEYS = ["filtered_trend", "filtered_trend_validation", "section_origins"]
BASE_SECTIONS = ["snapshots", "comparison", "comparison_validation", "trend", "trend_validation"]


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


def _history(steps):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for step in steps:
        history.record_statistics(_stats(**step))
    return history


def _base_pipeline(steps=({"accepted": 1}, {"accepted": 2}, {"accepted": 4})):
    """Real Prompt 508 snapshots plus their ordered Prompt 509 comparisons."""
    history = _history(steps)
    comparisons = [history.compare_sequences(i, i + 1) for i in range(1, len(steps))]
    return history, comparisons


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


def _filtered_comparisons(totals=(1, 2, 5), sections=_ALL):
    return _chain([(sections, {"accepted": n}) for n in totals])[1]


def _bad_comparisons():
    return [compare({"snapshot_id": "x"}, {"snapshot_id": "y"}), {}, None, "junk"]


OK = {"valid": True, "well_formed": True, "errors": [], "warnings": []}


class Prompt522TestCase(unittest.TestCase):
    def assert_report_valid(self, built, **sources):
        result = validate(built, **sources)
        self.assertEqual(result, OK, result)


# ----------------------------------------------------------------------
# 1. valid filtered trend integrated into the unified report
# ----------------------------------------------------------------------
class ValidIntegrationTests(Prompt522TestCase):

    def test_01_valid_filtered_trend_derived_from_comparisons(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assertEqual(list(built.keys()), BASE_KEYS + FILTERED_KEYS)
        self.assertEqual(built["structural_status"], REPORT_STATUS_VALID)
        section = built["filtered_trend"]
        self.assertEqual(list(section.keys()), ["available", "source", "summary"])
        self.assertTrue(section["available"])
        self.assertEqual(section["source"], TREND_SOURCE_DERIVED)
        self.assertEqual(section["summary"], ftrend(filtered))
        validation = built["filtered_trend_validation"]
        self.assertEqual(list(validation.keys()), ["available", "result"])
        self.assertTrue(validation["available"])
        self.assertEqual(validation["result"], validate_ftrend(section["summary"], comparisons=filtered))
        self.assertEqual(validation["result"], OK)
        self.assert_report_valid(built, snapshots=history, comparisons=comparisons,
                                 filtered_comparisons=filtered)

    def test_01b_valid_filtered_trend_provided(self):
        filtered = _filtered_comparisons()
        summary = ftrend(filtered)
        built = report(filtered_trend_summary=summary)
        self.assertEqual(built["filtered_trend"]["source"], TREND_SOURCE_PROVIDED)
        self.assertEqual(built["filtered_trend"]["summary"], summary)
        self.assertEqual(built["filtered_trend_validation"]["result"], validate_ftrend(summary))
        self.assert_report_valid(built, filtered_trend_summary=summary)

    def test_01c_provided_summary_with_its_comparisons_is_cross_checked(self):
        filtered = _filtered_comparisons()
        summary = ftrend(filtered)
        built = report(filtered_comparisons=filtered, filtered_trend_summary=summary)
        self.assertEqual(built["filtered_trend"]["source"], TREND_SOURCE_PROVIDED)
        self.assertEqual(built["filtered_trend_validation"]["result"],
                         validate_ftrend(summary, comparisons=filtered))
        self.assert_report_valid(built, filtered_comparisons=filtered, filtered_trend_summary=summary)

    def test_01d_filtered_only_report_is_partial(self):
        built = report(filtered_comparisons=_filtered_comparisons())
        self.assertEqual(built["structural_status"], REPORT_STATUS_PARTIAL)
        self.assertFalse(built["snapshots"]["available"])
        self.assertTrue(built["filtered_trend"]["available"])

    def test_embedded_summary_is_an_independent_copy(self):
        summary = ftrend(_filtered_comparisons())
        built = report(filtered_trend_summary=summary)
        built["filtered_trend"]["summary"]["numeric"]["total_evaluations"]["state"] = "tampered"
        self.assertNotEqual(summary["numeric"]["total_evaluations"]["state"], "tampered")


# ----------------------------------------------------------------------
# 2. invalid filtered trend, validation status preserved
# ----------------------------------------------------------------------
class InvalidIntegrationTests(Prompt522TestCase):

    def _tampered(self):
        summary = copy.deepcopy(ftrend(_filtered_comparisons()))
        summary["eligible_count"] += 1
        return summary

    def test_02_invalid_trend_keeps_its_validation_status(self):
        summary = self._tampered()
        built = report(filtered_trend_summary=summary)
        result = built["filtered_trend_validation"]["result"]
        self.assertFalse(result["valid"])
        self.assertIn("inconsistent_comparison_counts", result["errors"])
        self.assertEqual(result, validate_ftrend(summary))
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)

    def test_02b_invalid_trend_is_not_repaired(self):
        summary = self._tampered()
        built = report(filtered_trend_summary=summary)
        self.assertEqual(built["filtered_trend"]["summary"], summary)
        self.assertEqual(built["filtered_trend"]["summary"]["eligible_count"], 3)

    def test_02c_a_faithful_report_of_an_invalid_trend_is_itself_valid(self):
        summary = self._tampered()
        built = report(filtered_trend_summary=summary)
        self.assert_report_valid(built, filtered_trend_summary=summary)

    def test_02d_invalid_filtered_trend_makes_status_invalid_next_to_valid_sections(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons,
                       filtered_trend_summary=self._tampered())
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        self.assertTrue(built["comparison_validation"]["result"]["valid"])
        self.assertTrue(built["trend_validation"]["result"]["valid"])

    def test_02e_mismatch_with_source_comparisons_stays_visible(self):
        filtered = _filtered_comparisons((1, 2, 5))
        other = _filtered_comparisons((1, 2, 3))
        stale = ftrend(other)
        built = report(filtered_comparisons=filtered, filtered_trend_summary=stale)
        result = built["filtered_trend_validation"]["result"]
        self.assertFalse(result["valid"])
        self.assertTrue(any(error.startswith("mismatched_") for error in result["errors"]))
        self.assertEqual(built["filtered_trend"]["summary"], stale)
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)

    def test_02f_not_a_sequence_and_not_a_dict_are_carried_not_raised(self):
        not_sequence = report(filtered_comparisons=5)
        self.assertEqual(not_sequence["filtered_trend"]["summary"]["errors"],
                         ["comparisons_not_a_sequence"])
        self.assertFalse(not_sequence["filtered_trend_validation"]["result"]["valid"])
        self.assertEqual(not_sequence["structural_status"], REPORT_STATUS_INVALID)
        self.assert_report_valid(not_sequence)
        self.assertIn("invalid_source:filtered_comparisons",
                      validate(not_sequence, filtered_comparisons=5)["errors"])

        junk = report(filtered_trend_summary="junk")
        self.assertEqual(junk["filtered_trend"]["summary"], "junk")
        self.assertEqual(junk["filtered_trend_validation"]["result"]["errors"],
                         ["trend_summary_not_a_dict"])
        self.assertEqual(junk["structural_status"], REPORT_STATUS_INVALID)
        self.assert_report_valid(junk)


# ----------------------------------------------------------------------
# 3-4. missing / empty filtered trend
# ----------------------------------------------------------------------
class MissingAndEmptyTests(Prompt522TestCase):

    def test_03_missing_filtered_trend_is_explicitly_unavailable(self):
        for kwargs in ({"filtered_trend_summary": None}, {"filtered_comparisons": None},
                       {"filtered_comparisons": None, "filtered_trend_summary": None}):
            with self.subTest(kwargs=kwargs):
                built = report(**kwargs)
                self.assertEqual(built["filtered_trend"],
                                 {"available": False, "source": None, "summary": None})
                self.assertEqual(built["filtered_trend_validation"],
                                 {"available": False, "result": None})
                self.assertEqual(built["structural_status"], REPORT_STATUS_NO_DATA)
                self.assert_report_valid(built)

    def test_03b_missing_filtered_trend_does_not_change_a_complete_base_report(self):
        history, comparisons = _base_pipeline()
        base = report(snapshots=history, comparisons=comparisons)
        built = report(snapshots=history, comparisons=comparisons, filtered_trend_summary=None)
        self.assertEqual(built["structural_status"], REPORT_STATUS_VALID)
        for key in BASE_KEYS:
            self.assertEqual(built[key], base[key])

    def test_04_empty_filtered_trend_summary(self):
        summary = ftrend([])
        built = report(filtered_trend_summary=summary)
        section = built["filtered_trend"]
        self.assertTrue(section["available"])
        self.assertEqual(section["summary"]["total_comparisons"], 0)
        self.assertEqual(section["summary"]["eligible_count"], 0)
        self.assertEqual(section["summary"]["ineligible_count"], 0)
        self.assertIn("no_comparisons", section["summary"]["unavailable"])
        self.assertEqual(built["filtered_trend_validation"]["result"], OK)
        self.assert_report_valid(built, filtered_trend_summary=summary)

    def test_04b_empty_comparison_list_derives_nothing(self):
        # same rule as Prompt 513 for `comparisons=[]`: nothing to derive from
        built = report(filtered_comparisons=[])
        self.assertFalse(built["filtered_trend"]["available"])
        self.assertIsNone(built["filtered_trend"]["source"])
        self.assertIsNone(built["filtered_trend"]["summary"])
        self.assertFalse(built["filtered_trend_validation"]["available"])
        self.assert_report_valid(built, filtered_comparisons=[])

    def test_04c_unavailable_never_carries_a_stand_in_value(self):
        built = report(filtered_trend_summary=None)
        self.assertIsNone(built["filtered_trend"]["summary"])
        self.assertIsNone(built["filtered_trend_validation"]["result"])


# ----------------------------------------------------------------------
# 5-9. evaluation counts / number of comparisons / validity mixes
# ----------------------------------------------------------------------
class ComparisonShapeTests(Prompt522TestCase):

    def test_05_zero_evaluations(self):
        comparisons = _chain([(_SMALL, {"accepted": 0}), (_SMALL, {"accepted": 0})])[1]
        built = report(filtered_comparisons=comparisons)
        summary = built["filtered_trend"]["summary"]
        self.assertEqual(summary, ftrend(comparisons))
        self.assertEqual(summary["numeric"]["total_evaluations"]["end"], 0)
        self.assertEqual(built["filtered_trend_validation"]["result"], OK)
        self.assert_report_valid(built, filtered_comparisons=comparisons)

    def test_06_one_comparison(self):
        comparisons = _filtered_comparisons((1, 3))
        self.assertEqual(len(comparisons), 1)
        built = report(filtered_comparisons=comparisons)
        summary = built["filtered_trend"]["summary"]
        self.assertEqual((summary["total_comparisons"], summary["eligible_count"],
                          summary["ineligible_count"]), (1, 1, 0))
        self.assertEqual(built["filtered_trend_validation"]["result"], OK)

    def test_07_multiple_comparisons(self):
        comparisons = _filtered_comparisons((1, 2, 5, 9))
        built = report(filtered_comparisons=comparisons)
        summary = built["filtered_trend"]["summary"]
        self.assertEqual((summary["total_comparisons"], summary["eligible_count"],
                          summary["ineligible_count"]), (3, 3, 0))
        self.assertEqual(summary["numeric"]["total_evaluations"]["state"], TREND_INCREASED)
        self.assertEqual(built["filtered_trend_validation"]["result"], OK)

    def test_08_all_comparisons_invalid(self):
        comparisons = _bad_comparisons()
        built = report(filtered_comparisons=comparisons)
        summary = built["filtered_trend"]["summary"]
        self.assertEqual((summary["total_comparisons"], summary["eligible_count"],
                          summary["ineligible_count"]), (4, 0, 4))
        self.assertEqual([entry["index"] for entry in summary["ineligible_comparisons"]], [0, 1, 2, 3])
        for entry in summary["ineligible_comparisons"]:
            self.assertTrue(entry["errors"])
        self.assertIn("no_eligible_comparisons", summary["unavailable"])
        for entry in summary["section_availability"].values():
            self.assertEqual(entry["availability"], AVAILABILITY_INVALID)
        # the summary itself is well-formed, so the report is not called invalid for it
        self.assertEqual(built["filtered_trend_validation"]["result"], OK)
        self.assert_report_valid(built, filtered_comparisons=comparisons)

    def test_09_mixed_valid_and_invalid_comparisons(self):
        good = _filtered_comparisons((1, 2, 5))
        mixed = [good[0], {"valid": True}, good[1]]
        built = report(filtered_comparisons=mixed)
        summary = built["filtered_trend"]["summary"]
        self.assertEqual((summary["total_comparisons"], summary["eligible_count"],
                          summary["ineligible_count"]), (3, 2, 1))
        self.assertEqual(summary["ineligible_comparisons"][0]["index"], 1)
        self.assertEqual(summary["ineligible_comparisons"], ftrend(mixed)["ineligible_comparisons"])
        self.assertEqual(built["filtered_trend_validation"]["result"], OK)
        self.assert_report_valid(built, filtered_comparisons=mixed)

    def test_09b_invalid_comparisons_stay_invalid_not_repaired(self):
        good = _filtered_comparisons((1, 2, 5))
        broken = copy.deepcopy(good[1])
        broken["valid"] = "yes"
        mixed = [good[0], broken]
        before = copy.deepcopy(mixed)
        built = report(filtered_comparisons=mixed)
        self.assertEqual(mixed, before)
        self.assertEqual(built["filtered_trend"]["summary"]["ineligible_count"], 1)
        self.assertEqual(built["filtered_trend"]["summary"]["eligible_count"], 1)

    def test_09c_invalid_source_snapshot_stays_invalid(self):
        # a filtered snapshot whose own validation_status is invalid still
        # compares (Prompt 518) and is reported as it is: it is not made valid
        snaps = _snapshots([(_ALL, {"accepted": 1}), (_ALL, {"accepted": 2})])
        invalid = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary("not a summary")
        self.assertEqual(invalid["validation_status"], "invalid")
        comparison = compare(snaps[0], invalid)
        built = report(filtered_comparisons=[comparison])
        summary = built["filtered_trend"]["summary"]
        self.assertEqual(summary["validation_status"], ftrend([comparison])["validation_status"])
        self.assertEqual(built["filtered_trend"]["summary"], ftrend([comparison]))


# ----------------------------------------------------------------------
# 10-16. what the section carries, unchanged
# ----------------------------------------------------------------------
class PreservationTests(Prompt522TestCase):

    def test_10_numeric_trends_preserved(self):
        comparisons = _filtered_comparisons((1, 2, 5))
        summary = report(filtered_comparisons=comparisons)["filtered_trend"]["summary"]
        expected = ftrend(comparisons)["numeric"]
        self.assertEqual(list(summary["numeric"].keys()), _NUMERIC)
        self.assertEqual(summary["numeric"], expected)
        entry = summary["numeric"]["total_evaluations"]
        self.assertEqual(entry["state"], TREND_INCREASED)
        self.assertEqual(entry["delta"], entry["end"] - entry["start"])
        self.assertEqual(entry["availability"], AVAILABILITY_CONSISTENT)
        self.assertEqual(summary["numeric"]["rejected_count"]["state"], CHANGE_UNCHANGED)

    def test_10b_decreasing_numeric_trend_preserved(self):
        comparisons = _filtered_comparisons((6, 3, 1))
        summary = report(filtered_comparisons=comparisons)["filtered_trend"]["summary"]
        self.assertEqual(summary["numeric"]["total_evaluations"]["state"], TREND_DECREASED)
        self.assertEqual(summary["numeric"], ftrend(comparisons)["numeric"])

    def test_11_categorical_trends_preserved(self):
        comparisons = _filtered_comparisons((1, 2, 5))
        summary = report(filtered_comparisons=comparisons)["filtered_trend"]["summary"]
        self.assertEqual(list(summary["categorical"].keys()), _CATEGORICAL)
        self.assertEqual(summary["categorical"], ftrend(comparisons)["categorical"])
        for entry in summary["categorical"].values():
            self.assertIn("observed_states", entry)
            self.assertEqual(entry["availability"], AVAILABILITY_CONSISTENT)

    def test_12_section_availability_preserved(self):
        specs = [(_ALL, {"accepted": 1}), (_ALL, {"accepted": 2}), (_SMALL, {"accepted": 3}),
                 (_ALL, {"accepted": 4}), (_ALL, {"accepted": 5})]
        comparisons = _chain(specs)[1]
        summary = report(filtered_comparisons=comparisons)["filtered_trend"]["summary"]
        expected = ftrend(comparisons)["section_availability"]
        self.assertEqual(summary["section_availability"], expected)
        self.assertEqual(list(summary["section_availability"].keys()), _ALL)
        self.assertEqual(summary["section_availability"]["evaluation_counts"]["availability"],
                         AVAILABILITY_CONSISTENT)
        self.assertEqual(summary["section_availability"]["comparison_changes"]["availability"],
                         AVAILABILITY_INTERMITTENT)

    def test_13_chronology_information_preserved_when_ordered(self):
        comparisons = _filtered_comparisons((1, 2, 5))
        summary = report(filtered_comparisons=comparisons)["filtered_trend"]["summary"]
        self.assertEqual(summary["chronology"], {"ordered": True, "reversed": []})
        self.assertEqual(summary["chronological_range"], ftrend(comparisons)["chronological_range"])
        self.assertEqual(summary["chronological_range"]["earlier"]["sequence"], 1)
        self.assertEqual(summary["chronological_range"]["later"]["sequence"], 3)

    def test_13b_reversed_chronology_is_reported_not_corrected(self):
        comparisons = _filtered_comparisons((1, 2, 5))
        reversed_input = list(reversed(comparisons))
        built = report(filtered_comparisons=reversed_input)
        summary = built["filtered_trend"]["summary"]
        self.assertFalse(summary["chronology"]["ordered"])
        self.assertEqual(summary["chronology"]["reversed"], [{"index": 1, "previous_index": 0}])
        self.assertEqual(summary, ftrend(reversed_input))
        for entry in summary["numeric"].values():
            self.assertEqual(entry["state"], TREND_INSUFFICIENT_DATA)
        self.assertIn("chronology_not_ordered", summary["unavailable"])
        # a reversed chronology is a state the summary reports, not an error in the report
        self.assertEqual(built["filtered_trend_validation"]["result"], OK)
        self.assertEqual(built["structural_status"], REPORT_STATUS_PARTIAL)
        self.assert_report_valid(built, filtered_comparisons=reversed_input)

    def test_14_unavailable_and_insufficient_states_preserved(self):
        comparisons = _chain([(_SMALL, {"accepted": 1}), (_SMALL, {"accepted": 2})])[1]
        summary = report(filtered_comparisons=comparisons)["filtered_trend"]["summary"]
        self.assertEqual(summary["unavailable"], ftrend(comparisons)["unavailable"])
        for section in ("comparison_changes", "trend", "validation_statuses"):
            self.assertEqual(summary["categorical"][section]["state"], TREND_INSUFFICIENT_DATA)
            self.assertEqual(summary["section_availability"][section]["availability"],
                             AVAILABILITY_UNAVAILABLE)
            self.assertIn("insufficient_data:%s" % section, summary["unavailable"])
        self.assertIsNone(summary["categorical"]["trend"].get("start"))

    def test_14b_no_value_is_fabricated_for_unavailable_metrics(self):
        summary = report(filtered_comparisons=_bad_comparisons())["filtered_trend"]["summary"]
        for entry in summary["numeric"].values():
            self.assertEqual((entry["start"], entry["end"], entry["delta"]), (None, None, None))
            self.assertEqual(entry["available_in"], [])

    def test_15_selected_section_metadata_preserved(self):
        specs = [(_ALL, {"accepted": 1}), (_SMALL, {"accepted": 2}), (_ALL, {"accepted": 3})]
        comparisons = _chain(specs)[1]
        built = report(filtered_comparisons=comparisons)
        availability = built["filtered_trend"]["summary"]["section_availability"]
        self.assertEqual(availability, ftrend(comparisons)["section_availability"])
        counts = availability["trend"]["presence_counts"]
        self.assertEqual(counts["present_only_earlier"], 1)
        self.assertEqual(counts["present_only_later"], 1)
        self.assertEqual(counts["present_in_both"], 0)
        self.assertEqual(availability["evaluation_counts"]["presence_counts"]["present_in_both"], 2)
        self.assertEqual(availability["evaluation_counts"]["available_in"], [0, 1])

    def test_15b_sections_never_selected_stay_unavailable_and_nothing_is_invented(self):
        comparisons = _chain([(["evaluation_counts"], {"accepted": 1}),
                              (["evaluation_counts"], {"accepted": 2})])[1]
        built = report(filtered_comparisons=comparisons)
        availability = built["filtered_trend"]["summary"]["section_availability"]
        for section in ("rates", "dominant_rejection_reason", "comparison_changes", "trend",
                        "validation_statuses"):
            self.assertEqual(availability[section]["availability"], AVAILABILITY_UNAVAILABLE)
            self.assertEqual(availability[section]["presence_counts"]["unavailable_in_both"], 1)
        # requested / unknown names are not carried by Prompts 520-521, so the
        # report does not make them up
        for key in ("requested_sections", "included_sections", "unknown_sections"):
            self.assertNotIn(key, built["filtered_trend"])
            self.assertNotIn(key, built["filtered_trend"]["summary"])
            self.assertNotIn(key, built)

    def test_16_validation_errors_preserved(self):
        summary = copy.deepcopy(ftrend(_filtered_comparisons((1, 2, 5))))
        summary["eligible_count"] += 1
        del summary["chronology"]
        built = report(filtered_trend_summary=summary)
        result = built["filtered_trend_validation"]["result"]
        expected = validate_ftrend(summary)
        self.assertEqual(result["errors"], expected["errors"])
        self.assertIn("missing_field:chronology", result["errors"])
        self.assertIn("inconsistent_comparison_counts", result["errors"])
        self.assertFalse(result["well_formed"])
        self.assertEqual(result, expected)

    def test_16b_ineligible_comparison_errors_preserved(self):
        built = report(filtered_comparisons=_bad_comparisons())
        summary = built["filtered_trend"]["summary"]
        self.assertEqual(summary["ineligible_comparisons"][0]["errors"], ftrend(_bad_comparisons())[
            "ineligible_comparisons"][0]["errors"])
        self.assertTrue(summary["ineligible_comparisons"][0]["errors"])


# ----------------------------------------------------------------------
# 17. source vs derived distinction
# ----------------------------------------------------------------------
class SourceDerivedTests(Prompt522TestCase):

    def test_17_section_origins_state_what_each_section_holds(self):
        built = report(filtered_comparisons=_filtered_comparisons())
        self.assertEqual(built["section_origins"], {
            "snapshots": REPORT_ORIGIN_SOURCE,
            "comparison": REPORT_ORIGIN_DERIVED_FROM_SNAPSHOTS,
            "comparison_validation": REPORT_ORIGIN_VALIDATION,
            "trend": REPORT_ORIGIN_DERIVED_FROM_COMPARISONS,
            "trend_validation": REPORT_ORIGIN_VALIDATION,
            "filtered_trend": REPORT_ORIGIN_DERIVED_FROM_FILTERED_COMPARISONS,
            "filtered_trend_validation": REPORT_ORIGIN_VALIDATION,
        })
        # every report section other than the three bookkeeping fields is labelled
        labelled = set(built["section_origins"])
        sections = set(built) - {"valid", "errors", "structural_status", "section_origins"}
        self.assertEqual(labelled, sections)

    def test_17b_snapshot_section_is_the_recorded_snapshot_not_a_derivation(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons,
                       filtered_comparisons=_filtered_comparisons())
        self.assertEqual(built["snapshots"]["latest"], history.get_latest())

    def test_17c_derived_filtered_trend_is_never_labelled_source(self):
        built = report(filtered_comparisons=_filtered_comparisons())
        self.assertNotEqual(built["section_origins"]["filtered_trend"], REPORT_ORIGIN_SOURCE)
        self.assertEqual(built["filtered_trend"]["source"], TREND_SOURCE_DERIVED)

    def test_17d_misstated_origin_is_caught_by_the_validator(self):
        for name in ("filtered_trend", "comparison", "trend", "filtered_trend_validation"):
            with self.subTest(section=name):
                built = copy.deepcopy(report(filtered_comparisons=_filtered_comparisons()))
                built["section_origins"][name] = REPORT_ORIGIN_SOURCE
                result = validate(built)
                self.assertFalse(result["valid"])
                self.assertIn("misstated_origin:%s" % name, result["errors"])

    def test_17e_unavailable_is_distinct_from_available(self):
        built = report(filtered_trend_summary=None)
        self.assertFalse(built["filtered_trend"]["available"])
        self.assertFalse(built["filtered_trend_validation"]["available"])
        self.assertEqual(built["section_origins"]["filtered_trend"],
                         REPORT_ORIGIN_DERIVED_FROM_FILTERED_COMPARISONS)

    def test_17f_validation_section_holds_the_validator_result_not_a_corrected_value(self):
        summary = copy.deepcopy(ftrend(_filtered_comparisons()))
        summary["direction"] = "sideways"
        built = report(filtered_trend_summary=summary)
        self.assertEqual(built["filtered_trend"]["summary"]["direction"], "sideways")
        self.assertIn("invalid_direction", built["filtered_trend_validation"]["result"]["errors"])


# ----------------------------------------------------------------------
# 18-20. existing sections remain intact
# ----------------------------------------------------------------------
class ExistingSectionsIntactTests(Prompt522TestCase):

    def setUp(self):
        self.history, self.comparisons = _base_pipeline(
            ({"accepted": 1}, {"irrelevant": 2}, {"accepted": 4}))
        self.base = report(snapshots=self.history, comparisons=self.comparisons)
        self.extended = report(snapshots=self.history, comparisons=self.comparisons,
                               filtered_comparisons=_filtered_comparisons())

    def test_18_snapshot_section_intact(self):
        self.assertEqual(self.extended["snapshots"], self.base["snapshots"])
        self.assertEqual(self.extended["snapshots"]["count"], 3)
        self.assertEqual(self.extended["snapshots"]["latest"], self.history.get_latest())

    def test_19_comparison_sections_intact(self):
        self.assertEqual(self.extended["comparison"], self.base["comparison"])
        self.assertEqual(self.extended["comparison_validation"], self.base["comparison_validation"])
        self.assertEqual(self.extended["comparison_validation"]["result"],
                         validate_comparison(self.comparisons[-1]))

    def test_20_trend_sections_intact(self):
        self.assertEqual(self.extended["trend"], self.base["trend"])
        self.assertEqual(self.extended["trend_validation"], self.base["trend_validation"])
        self.assertEqual(self.extended["trend"]["summary"], trend(self.comparisons))

    def test_18_to_20_all_prompt_513_fields_equal_when_filtered_trend_is_valid(self):
        for key in BASE_KEYS:
            self.assertEqual(self.extended[key], self.base[key], key)

    def test_18_to_20_base_sections_unchanged_when_filtered_trend_is_invalid(self):
        summary = copy.deepcopy(ftrend(_filtered_comparisons()))
        summary["eligible_count"] += 1
        built = report(snapshots=self.history, comparisons=self.comparisons,
                       filtered_trend_summary=summary)
        for key in BASE_SECTIONS:
            self.assertEqual(built[key], self.base[key], key)
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        self.assertEqual(self.base["structural_status"], REPORT_STATUS_VALID)

    def test_base_invalidity_still_propagates_with_a_valid_filtered_trend(self):
        history = _history([{"accepted": 1}, {"accepted": 2}])
        comparison = copy.deepcopy(history.compare_sequences(1, 2))
        comparison["valid"] = "yes"
        built = report(snapshots=history, comparisons=[comparison],
                       filtered_comparisons=_filtered_comparisons())
        self.assertFalse(built["comparison_validation"]["result"]["valid"])
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        self.assertTrue(built["filtered_trend_validation"]["result"]["valid"])

    def test_invalid_source_snapshot_stays_invalid_in_the_report(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record({}, {"valid": False, "errors": ["boom"]})
        self.assertEqual(history.get_latest()["validation_status"], "invalid")
        built = report(snapshots=history, filtered_comparisons=_filtered_comparisons())
        self.assertEqual(built["snapshots"]["latest"]["validation_status"], "invalid")
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)

    def test_prompt_515_summary_is_unchanged_by_a_valid_filtered_trend(self):
        base_summary = fmt(self.base, validate(self.base))
        built = self.extended
        summary = fmt(built, validate(built))
        self.assertEqual(summary["report_validity"], "valid")
        self.assertEqual(summary, base_summary)


# ----------------------------------------------------------------------
# 21-23. no history, no mutation, determinism
# ----------------------------------------------------------------------
class SafetyTests(Prompt522TestCase):

    def test_21_no_duplicate_diagnostic_history_is_created(self):
        store = lks._BoundedDiagnosticSnapshotStore
        subclasses_before = sorted(cls.__name__ for cls in store.__subclasses__())
        history, comparisons = _base_pipeline()
        snaps, filtered = _chain([(_ALL, {"accepted": n}) for n in (1, 2, 5)])
        filtered_history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        filtered_history.record_filtered_summary(filt(_summary({"accepted": 1}), _ALL))
        before = (history.get_all(), filtered_history.get_all())
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        validate(built, snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assertEqual((history.get_all(), filtered_history.get_all()), before)
        self.assertEqual(len(history.get_all()), 3)
        self.assertEqual(len(filtered_history.get_all()), 1)
        self.assertEqual(sorted(cls.__name__ for cls in store.__subclasses__()), subclasses_before)
        self.assertEqual(subclasses_before, sorted([
            "LearnedKnowledgeDiagnosticSnapshotHistory",
            "LearnedKnowledgeFilteredSummarySnapshotHistory"]))
        self.assertEqual(len(snaps), 3)
        # nothing history-like was added to the report
        self.assertEqual(set(built), set(BASE_KEYS + FILTERED_KEYS))

    def test_22_report_generation_does_not_mutate_source_data(self):
        history, comparisons = _base_pipeline()
        filtered = _bad_comparisons()[:1] + _filtered_comparisons((1, 2, 5))
        summary = ftrend(filtered)
        base_summary = trend(comparisons)
        snapshot = (history.get_all(), copy.deepcopy(comparisons), copy.deepcopy(filtered),
                    copy.deepcopy(summary), copy.deepcopy(base_summary))
        built = report(snapshots=history, comparisons=comparisons, trend_summary=base_summary,
                       filtered_comparisons=filtered, filtered_trend_summary=summary)
        built_copy = copy.deepcopy(built)
        validate(built, snapshots=history, comparisons=comparisons, trend_summary=base_summary,
                 filtered_comparisons=filtered, filtered_trend_summary=summary)
        self.assertEqual((history.get_all(), comparisons, filtered, summary, base_summary), snapshot)
        self.assertEqual(built, built_copy)

    def test_22b_derived_report_does_not_mutate_filtered_comparisons(self):
        filtered = _filtered_comparisons((1, 2, 5))
        before = copy.deepcopy(filtered)
        report(filtered_comparisons=filtered)
        self.assertEqual(filtered, before)

    def test_22c_tuple_of_comparisons_is_accepted(self):
        filtered = _filtered_comparisons((1, 2, 5))
        self.assertEqual(report(filtered_comparisons=tuple(filtered)),
                         report(filtered_comparisons=filtered))

    def test_23_deterministic_repeated_generation(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        first = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        second = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assertEqual(first, second)
        self.assertEqual(list(first.keys()), list(second.keys()))
        self.assertEqual(validate(first, filtered_comparisons=filtered),
                         validate(second, filtered_comparisons=filtered))
        rebuilt = report(snapshots=history, comparisons=comparisons,
                         filtered_comparisons=_filtered_comparisons())
        self.assertEqual(first, rebuilt)


# ----------------------------------------------------------------------
# report validator (Prompt 514) coverage of the new sections
# ----------------------------------------------------------------------
class ReportValidatorTests(Prompt522TestCase):

    def setUp(self):
        self.filtered = _filtered_comparisons((1, 2, 5))
        self.built = report(filtered_comparisons=self.filtered)

    def _tamper(self, edit):
        built = copy.deepcopy(self.built)
        edit(built)
        return built

    def test_valid_report_with_and_without_sources(self):
        self.assert_report_valid(self.built)
        self.assert_report_valid(self.built, filtered_comparisons=self.filtered)

    def test_filtered_fields_must_come_together(self):
        for missing in FILTERED_KEYS:
            with self.subTest(missing=missing):
                built = self._tamper(lambda r: r.pop(missing))
                result = validate(built)
                self.assertFalse(result["valid"])
                self.assertIn("missing_field:%s" % missing, result["errors"])

    def test_unexpected_top_level_field_still_rejected(self):
        built = self._tamper(lambda r: r.update({"requested_sections": []}))
        self.assertIn("unexpected_field:requested_sections", validate(built)["errors"])

    def test_section_shape_is_checked(self):
        built = self._tamper(lambda r: r["filtered_trend"].update({"extra": 1}))
        self.assertIn("unexpected_field:filtered_trend.extra", validate(built)["errors"])
        built = self._tamper(lambda r: r["filtered_trend_validation"].pop("result"))
        self.assertIn("missing_field:filtered_trend_validation.result", validate(built)["errors"])
        built = self._tamper(lambda r: r["filtered_trend"].update({"available": "yes"}))
        self.assertIn("invalid_type:filtered_trend.available", validate(built)["errors"])

    def test_unavailable_section_may_not_carry_a_value(self):
        built = self._tamper(lambda r: r["filtered_trend"].update({"available": False}))
        errors = validate(built)["errors"]
        self.assertIn("fabricated_value_for_unavailable_component:filtered_trend.summary", errors)
        self.assertIn("fabricated_value_for_unavailable_component:filtered_trend.source", errors)
        self.assertIn("inconsistent_availability:filtered_trend_validation", errors)

    def test_available_section_may_not_be_empty(self):
        built = self._tamper(lambda r: r["filtered_trend"].update({"summary": None}))
        self.assertIn("missing_data_marked_available:filtered_trend.summary", validate(built)["errors"])

    def test_unsupported_source_value(self):
        built = self._tamper(lambda r: r["filtered_trend"].update({"source": "guessed"}))
        self.assertIn("unsupported_value:filtered_trend.source", validate(built)["errors"])

    def test_derived_trend_needs_comparisons_behind_it(self):
        built = report(filtered_trend_summary=ftrend([]))
        built["filtered_trend"]["source"] = TREND_SOURCE_DERIVED
        self.assertIn("derived_filtered_trend_without_comparisons", validate(built)["errors"])

    def test_report_claiming_valid_for_an_invalid_summary_is_rejected(self):
        summary = copy.deepcopy(ftrend(self.filtered))
        summary["eligible_count"] += 1
        built = report(filtered_trend_summary=summary)
        built["filtered_trend_validation"]["result"] = dict(OK)
        built["structural_status"] = REPORT_STATUS_PARTIAL
        result = validate(built)
        self.assertIn("claims_valid_but_source_invalid:filtered_trend", result["errors"])

    def test_status_must_match_the_filtered_trend_validity(self):
        summary = copy.deepcopy(ftrend(self.filtered))
        summary["eligible_count"] += 1
        built = report(filtered_trend_summary=summary)
        built["structural_status"] = REPORT_STATUS_PARTIAL
        self.assertIn("inconsistent_structural_status", validate(built)["errors"])
        also_wrong = report(filtered_comparisons=self.filtered)
        also_wrong["structural_status"] = REPORT_STATUS_NO_DATA
        self.assertIn("inconsistent_structural_status", validate(also_wrong)["errors"])

    def test_ordered_chronology_range_must_run_forward(self):
        built = self._tamper(lambda r: r["filtered_trend"]["summary"]["chronological_range"].update(
            {"earlier": {"snapshot_id": "learned_knowledge_snapshot_000009", "sequence": 9}}))
        self.assertIn("invalid_chronological_ordering:filtered_trend.chronological_range",
                      validate(built)["errors"])

    def test_source_mismatch_is_reported_with_sources(self):
        other = _filtered_comparisons((1, 2, 3))
        result = validate(self.built, filtered_comparisons=other)
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])
        self.assertTrue(any(error.startswith("source_mismatch:filtered_trend") for error in result["errors"]))

    def test_tampered_summary_is_caught_against_its_provided_source(self):
        summary = copy.deepcopy(ftrend(self.filtered))
        summary["numeric"]["total_evaluations"]["state"] = TREND_DECREASED
        built = report(filtered_trend_summary=summary)
        result = validate(built, filtered_trend_summary=ftrend(self.filtered))
        self.assertFalse(result["valid"])
        self.assertTrue(any(error.startswith("source_mismatch:filtered_trend") for error in result["errors"]))

    def test_report_without_filtered_sections_does_not_match_filtered_sources(self):
        plain = report()
        result = validate(plain, filtered_comparisons=self.filtered)
        self.assertFalse(result["valid"])
        self.assertIn("source_mismatch:filtered_trend", result["errors"])

    def test_invalid_filtered_source_type(self):
        result = validate(self.built, filtered_comparisons="abc")
        self.assertIn("invalid_source:filtered_comparisons", result["errors"])

    def test_filtered_sources_not_given_are_not_checked(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=self.filtered)
        self.assert_report_valid(built, snapshots=history, comparisons=comparisons)

    def test_section_origins_shape(self):
        built = self._tamper(lambda r: r.update({"section_origins": []}))
        self.assertIn("invalid_type:section_origins", validate(built)["errors"])
        built = self._tamper(lambda r: r["section_origins"].pop("trend"))
        self.assertIn("missing_field:section_origins.trend", validate(built)["errors"])
        built = self._tamper(lambda r: r["section_origins"].update({"extra": "source"}))
        self.assertIn("unexpected_field:section_origins.extra", validate(built)["errors"])

    def test_validator_never_raises_on_odd_filtered_sections(self):
        for value in (None, 5, "x", [], {}):
            with self.subTest(value=value):
                built = self._tamper(lambda r: r.update({"filtered_trend": value}))
                self.assertFalse(validate(built)["valid"])
                built = self._tamper(lambda r: r.update({"filtered_trend_validation": value}))
                self.assertFalse(validate(built)["valid"])


# ----------------------------------------------------------------------
# 24-26. regression coverage
# ----------------------------------------------------------------------
class RegressionPrompt513Tests(Prompt522TestCase):

    def test_24_default_report_is_exactly_the_prompt_513_report(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(list(built.keys()), BASE_KEYS)
        for key in FILTERED_KEYS:
            self.assertNotIn(key, built)
        self.assertEqual(built["structural_status"], REPORT_STATUS_VALID)
        self.assertEqual(report(), {
            "valid": True, "errors": [], "structural_status": REPORT_STATUS_NO_DATA,
            "snapshots": {"available": False, "count": 0, "latest": None},
            "comparison": {"available": False, "total_considered": 0, "latest": None},
            "comparison_validation": {"available": False, "result": None},
            "trend": {"available": False, "source": None, "summary": None},
            "trend_validation": {"available": False, "result": None},
        })

    def test_24b_prompt_513_arguments_behave_as_before(self):
        history, comparisons = _base_pipeline()
        derived = report(comparisons=comparisons)
        self.assertEqual(derived["trend"]["source"], TREND_SOURCE_DERIVED)
        provided = report(comparisons=comparisons, trend_summary=trend(comparisons))
        self.assertEqual(provided["trend"]["source"], TREND_SOURCE_PROVIDED)
        self.assertEqual(report(snapshots=history)["structural_status"], REPORT_STATUS_PARTIAL)
        # positional use of the first three arguments is unchanged
        self.assertEqual(report(history, comparisons, trend(comparisons)),
                         report(snapshots=history, comparisons=comparisons,
                                trend_summary=trend(comparisons)))

    def test_24c_status_derivation_without_filtered_arguments_is_unchanged(self):
        available = {"available": True}
        unavailable = {"available": False}
        valid_result = {"available": True, "result": {"valid": True}}
        status = lks._report_structural_status(
            {"available": True, "latest": {"validation_status": "valid"}}, valid_result,
            valid_result, available, available)
        self.assertEqual(status, REPORT_STATUS_VALID)
        self.assertEqual(lks._report_structural_status(
            unavailable, {"available": False}, {"available": False}, unavailable, unavailable),
            REPORT_STATUS_NO_DATA)


class RegressionPrompt514Tests(Prompt522TestCase):

    def test_25_plain_reports_validate_exactly_as_before(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(validate(built), OK)
        self.assertEqual(validate(built, snapshots=history, comparisons=comparisons), OK)
        self.assertEqual(validate(report()), OK)

    def test_25b_existing_error_codes_are_unchanged(self):
        history, comparisons = _base_pipeline()
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["structural_status"] = "unknown"
        self.assertIn("unsupported_status_value:structural_status", validate(built)["errors"])
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["extra"] = 1
        self.assertIn("unexpected_field:extra", validate(built)["errors"])
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        del built["trend"]
        self.assertIn("missing_field:trend", validate(built)["errors"])
        self.assertFalse(validate(None)["valid"])
        self.assertEqual(validate(None)["errors"], ["report_not_a_dict"])
        built = copy.deepcopy(report(snapshots=history, comparisons=comparisons))
        built["snapshots"]["latest"]["total_evaluations"] += 7
        result = validate(built, snapshots=history, comparisons=comparisons)
        self.assertTrue(any(error.startswith("source_mismatch:snapshots") for error in result["errors"]))

    def test_25c_result_shape_is_unchanged(self):
        self.assertEqual(list(validate(report()).keys()), ["valid", "well_formed", "errors", "warnings"])
        self.assertEqual(list(validate(report(filtered_trend_summary=None)).keys()),
                         ["valid", "well_formed", "errors", "warnings"])

    def test_25d_a_plain_report_is_not_required_to_have_filtered_sections(self):
        self.assertTrue(validate(report())["valid"])
        self.assertNotIn("missing_field:filtered_trend", validate(report())["errors"])


class RegressionPrompts520And521Tests(Prompt522TestCase):

    def test_26_prompt_520_summary_is_unchanged_by_the_report(self):
        filtered = _filtered_comparisons((1, 2, 5))
        before = ftrend(filtered)
        built = report(filtered_comparisons=filtered)
        self.assertEqual(ftrend(filtered), before)
        self.assertEqual(built["filtered_trend"]["summary"], before)
        self.assertEqual(list(before.keys()), [
            "valid", "errors", "direction", "total_comparisons", "eligible_count",
            "ineligible_count", "ineligible_comparisons", "chronological_range", "chronology",
            "numeric", "categorical", "section_availability", "validation_status", "unavailable"])

    def test_26b_prompt_521_validation_is_unchanged_by_the_report(self):
        filtered = _filtered_comparisons((1, 2, 5))
        summary = ftrend(filtered)
        before = (validate_ftrend(summary), validate_ftrend(summary, comparisons=filtered))
        report(filtered_comparisons=filtered, filtered_trend_summary=summary)
        self.assertEqual((validate_ftrend(summary), validate_ftrend(summary, comparisons=filtered)), before)
        self.assertEqual(before, (OK, OK))

    def test_26c_prompt_511_512_trend_is_independent_of_the_filtered_trend(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons,
                       filtered_comparisons=_filtered_comparisons())
        self.assertEqual(built["trend"]["summary"], trend(comparisons))
        self.assertEqual(built["trend_validation"]["result"],
                         validate_trend(trend(comparisons), comparisons=comparisons))

    def test_26d_the_filtered_snapshot_lineage_is_not_compared_with_the_snapshot_history(self):
        # the filtered snapshots' sequences (1..n) have nothing to do with the
        # Prompt 508 history; a mismatch between the two must not be flagged
        history, comparisons = _base_pipeline(({"accepted": 1}, {"accepted": 2}))
        filtered = _filtered_comparisons((1, 2, 5, 9, 14))
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        self.assert_report_valid(built, snapshots=history, comparisons=comparisons,
                                 filtered_comparisons=filtered)


# ----------------------------------------------------------------------
# diagnostic-only isolation
# ----------------------------------------------------------------------
class IsolationTests(unittest.TestCase):

    def test_gate_module_does_not_reference_the_report(self):
        import inspect
        from learning import learned_knowledge_gate
        source = inspect.getsource(learned_knowledge_gate)
        for name in ("build_learned_knowledge_diagnostic_report", "filtered_trend",
                     "filtered_comparisons"):
            self.assertNotIn(name, source)

    def test_no_production_module_calls_the_report_builder_or_validator(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                if path.endswith(os.path.join("learning", "learned_knowledge_statistics.py")):
                    continue
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                for symbol in ("build_learned_knowledge_diagnostic_report",
                               "validate_learned_knowledge_diagnostic_report"):
                    if symbol in text:
                        offenders.append((os.path.relpath(path, root), symbol))
        self.assertEqual(offenders, [])

    def test_gate_still_evaluates_normally(self):
        from learning.learned_knowledge_gate import evaluate_learned_knowledge_gate, REASON_NOT_SELECTED
        result = evaluate_learned_knowledge_gate(selection=None)
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.reason, REASON_NOT_SELECTED)

    def test_no_new_metric_names_are_added_to_the_filtered_section(self):
        summary = report(filtered_comparisons=_filtered_comparisons())["filtered_trend"]["summary"]
        self.assertEqual(set(summary), set(ftrend(_filtered_comparisons())))
        for forbidden in ("score", "rank", "ranking", "prediction", "recommendation", "health",
                          "quality", "improvement"):
            self.assertFalse(any(forbidden in key for key in summary), forbidden)


if __name__ == "__main__":
    unittest.main()
