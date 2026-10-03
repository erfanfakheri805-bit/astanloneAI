"""
Tests for Prompt 516 - Diagnostic Summary Section Filtering.

`filter_learned_knowledge_diagnostic_summary()`
(learning/learned_knowledge_statistics.py) is a thin, deterministic,
read-only selection layer over the dict
`format_learned_knowledge_diagnostic_summary()` (Prompt 515) returns. It
only chooses which already-existing sections of a summary to expose; it
never computes, repairs, reinterprets, or invents anything.

Covers:
    1.  one valid section
    2.  multiple valid sections
    3.  all available sections
    4.  an unknown section
    5.  an unavailable section
    6.  valid + unknown sections
    7.  valid + unavailable sections
    8.  empty section request
    9.  duplicate requested section names
    10. invalid underlying diagnostic summary
    11. summary with validation errors
    12. missing optional sections
    13. numeric values unchanged
    14. trend states unchanged
    15. categorical states unchanged
    16. chronological ordering unchanged
    17. deterministic output
    18. original summary not mutated
    19. source diagnostic objects not mutated
    20. Prompt 515 behavior unchanged
    21. regression coverage for Prompts 500-515

Run directly:
    python -m unittest tests.test_learned_knowledge_diagnostic_summary_filtering -v
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
    REPORT_VALIDITY_VALID, REPORT_VALIDITY_INVALID,
    summarize_learned_knowledge_diagnostic_snapshot_comparison_trend as trend,
    validate_learned_knowledge_diagnostic_snapshot_comparison as validate_comparison,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
)

_FILTER_KEYS = [
    "requested_sections", "included_sections", "unavailable_sections", "unknown_sections",
    "summary_text", "report_validity", "validation_errors", "metrics",
]
_SUMMARY_KEYS = [
    "summary_text", "report_validity", "validation_errors",
    "available_sections", "unavailable_sections", "metrics",
]
_ALL_SECTIONS = [
    "evaluation_counts", "rates", "dominant_rejection_reason",
    "comparison_changes", "trend", "validation_statuses",
]
_FORBIDDEN_WORDS = ("good", "bad", "healthy", "unhealthy", "successful", "unsuccessful",
                    "best", "worst", "important", "recommend", "predict")


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


def _chain(history):
    return [history.compare_sequences(i, i + 1) for i in range(1, len(history))]


def _pipeline(counts_list=None):
    """(history, comparisons, valid unified report, its 514 validation)."""
    history = _history(counts_list or [{"accepted": 1}, {"accepted": 3}, {"irrelevant": 2}])
    comparisons = _chain(history)
    built = report(snapshots=history, comparisons=comparisons)
    return history, comparisons, built, validate(built, snapshots=history, comparisons=comparisons)


def _summary(counts_list=None):
    _, _, built, validation = _pipeline(counts_list)
    return fmt(built, validation)


def _invalid_status_history_and_comparison():
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record({}, {"valid": False, "errors": ["boom"]})
    history.record_statistics(_stats(accepted=2))
    comparison = history.compare_sequences(1, 2)
    assert validate_comparison(comparison)["valid"] is False
    return history, comparison


def _partial_summary():
    """One snapshot: evaluation sections + validation_statuses only."""
    history = _history([{"accepted": 2, "irrelevant": 1}])
    built = report(snapshots=history)
    return fmt(built, validate(built, snapshots=history))


def _invalid_summary(errors=None):
    _, _, built, _ = _pipeline()
    broken = copy.deepcopy(built)
    broken["structural_status"] = "unknown"
    validation = validate(broken)
    assert not validation["valid"]
    if errors is not None:
        validation = {"valid": False, "well_formed": False, "errors": errors, "warnings": []}
    return fmt(broken, validation)


class Prompt516TestCase(unittest.TestCase):

    def assertFilterShape(self, result):
        self.assertEqual(list(result.keys()), _FILTER_KEYS)
        self.assertIn(result["report_validity"], (REPORT_VALIDITY_VALID, REPORT_VALIDITY_INVALID))
        for key in ("requested_sections", "included_sections", "unavailable_sections",
                    "unknown_sections", "validation_errors"):
            self.assertIsInstance(result[key], list)
        self.assertIsInstance(result["summary_text"], str)
        self.assertIsInstance(result["metrics"], dict)


# ----------------------------------------------------------------------
# 1. one valid section
# ----------------------------------------------------------------------
class TestOneValidSection(Prompt516TestCase):

    def test_single_section_is_returned_with_its_exact_value(self):
        summary = _summary()
        result = filt(summary, ["rates"])
        self.assertFilterShape(result)
        self.assertEqual(result["requested_sections"], ["rates"])
        self.assertEqual(result["included_sections"], ["rates"])
        self.assertEqual(result["unavailable_sections"], [])
        self.assertEqual(result["unknown_sections"], [])
        self.assertEqual(result["report_validity"], REPORT_VALIDITY_VALID)
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(result["metrics"], {"rates": summary["metrics"]["rates"]})

    def test_other_sections_are_not_exposed(self):
        summary = _summary()
        result = filt(summary, ["trend"])
        self.assertEqual(list(result["metrics"]), ["trend"])
        self.assertNotIn("Evaluation counts", result["summary_text"])
        self.assertNotIn("Comparison", result["summary_text"])
        self.assertNotIn("Validation statuses", result["summary_text"])

    def test_every_section_name_can_be_requested_on_its_own(self):
        summary = _summary()
        for section in _ALL_SECTIONS:
            with self.subTest(section=section):
                result = filt(summary, [section])
                self.assertEqual(result["included_sections"], [section])
                self.assertEqual(result["metrics"][section], summary["metrics"][section])

    def test_bare_string_request_is_one_section(self):
        self.assertEqual(filt(_summary(), "trend"), filt(_summary(), ["trend"]))


# ----------------------------------------------------------------------
# 2. multiple valid sections
# ----------------------------------------------------------------------
class TestMultipleValidSections(Prompt516TestCase):

    def test_several_sections_are_returned(self):
        summary = _summary()
        result = filt(summary, ["trend", "evaluation_counts", "comparison_changes"])
        self.assertEqual(result["requested_sections"], ["trend", "evaluation_counts", "comparison_changes"])
        # included sections follow the fixed Prompt 515 section order
        self.assertEqual(result["included_sections"], ["evaluation_counts", "comparison_changes", "trend"])
        for section in result["included_sections"]:
            self.assertEqual(result["metrics"][section], summary["metrics"][section])
        self.assertEqual(list(result["metrics"]), result["included_sections"])

    def test_request_order_does_not_change_included_result(self):
        summary = _summary()
        first = filt(summary, ["validation_statuses", "rates"])
        second = filt(summary, ["rates", "validation_statuses"])
        for key in ("included_sections", "metrics", "summary_text", "unavailable_sections"):
            self.assertEqual(first[key], second[key])
        self.assertEqual(first["requested_sections"], ["validation_statuses", "rates"])
        self.assertEqual(second["requested_sections"], ["rates", "validation_statuses"])


# ----------------------------------------------------------------------
# 3. all available sections
# ----------------------------------------------------------------------
class TestAllAvailableSections(Prompt516TestCase):

    def test_requesting_every_available_section_includes_them_all(self):
        summary = _summary()
        result = filt(summary, summary["available_sections"])
        self.assertEqual(result["included_sections"], summary["available_sections"])
        self.assertEqual(result["unavailable_sections"], [])
        self.assertEqual(result["unknown_sections"], [])
        self.assertEqual(result["metrics"], summary["metrics"])

    def test_requesting_all_names_on_a_partial_summary_splits_included_and_unavailable(self):
        summary = _partial_summary()
        result = filt(summary, _ALL_SECTIONS)
        self.assertEqual(result["included_sections"], summary["available_sections"])
        self.assertEqual(result["unavailable_sections"], summary["unavailable_sections"])
        self.assertEqual(result["unknown_sections"], [])

    def test_included_text_lines_agree_with_the_515_summary_text(self):
        summary = _summary()
        result = filt(summary, ["evaluation_counts"])
        self.assertIn("2 total", result["summary_text"])
        # trend and validation lines are word-for-word the 515 lines
        trend_line = filt(summary, ["trend"])["summary_text"]
        validation_line = filt(summary, ["validation_statuses"])["summary_text"]
        self.assertIn(trend_line, summary["summary_text"])
        self.assertIn(validation_line, summary["summary_text"])
        self.assertIn(filt(summary, ["dominant_rejection_reason"])["summary_text"], summary["summary_text"])


# ----------------------------------------------------------------------
# 4. unknown section
# ----------------------------------------------------------------------
class TestUnknownSection(Prompt516TestCase):

    def test_unknown_name_is_reported_and_nothing_is_invented(self):
        result = filt(_summary(), ["forecast"])
        self.assertFilterShape(result)
        self.assertEqual(result["requested_sections"], ["forecast"])
        self.assertEqual(result["unknown_sections"], ["forecast"])
        self.assertEqual(result["included_sections"], [])
        self.assertEqual(result["unavailable_sections"], [])
        self.assertEqual(result["metrics"], {})
        self.assertIn("Unknown sections: forecast.", result["summary_text"])

    def test_matching_is_exact_and_case_sensitive(self):
        result = filt(_summary(), ["Trend", " trend", "trend ", "TREND"])
        self.assertEqual(result["unknown_sections"], ["Trend", " trend", "trend ", "TREND"])
        self.assertEqual(result["included_sections"], [])

    def test_non_string_names_are_unknown_not_errors(self):
        result = filt(_summary(), [None, 3, ("trend",), "rates"])
        self.assertEqual(result["included_sections"], ["rates"])
        self.assertEqual(result["unknown_sections"], [None, 3, ("trend",)])
        self.assertIn("Unknown sections: None, 3, ('trend',).", result["summary_text"])

    def test_unknown_names_appear_only_in_unknown_and_requested(self):
        result = filt(_summary(), ["nope"])
        self.assertNotIn("nope", result["included_sections"])
        self.assertNotIn("nope", result["unavailable_sections"])
        self.assertNotIn("nope", result["metrics"])


# ----------------------------------------------------------------------
# 5. unavailable section
# ----------------------------------------------------------------------
class TestUnavailableSection(Prompt516TestCase):

    def test_unavailable_section_is_explicit_and_not_fabricated(self):
        summary = _partial_summary()
        self.assertIn("trend", summary["unavailable_sections"])
        result = filt(summary, ["trend"])
        self.assertEqual(result["included_sections"], [])
        self.assertEqual(result["unavailable_sections"], ["trend"])
        self.assertEqual(result["unknown_sections"], [])
        self.assertIsNone(result["metrics"]["trend"])
        self.assertIn("Unavailable sections: trend.", result["summary_text"])
        self.assertEqual(result["report_validity"], REPORT_VALIDITY_VALID)

    def test_no_data_report_only_offers_validation_statuses(self):
        built = report()
        summary = fmt(built, validate(built))
        result = filt(summary, _ALL_SECTIONS)
        self.assertEqual(result["included_sections"], ["validation_statuses"])
        self.assertEqual(result["unavailable_sections"], [s for s in _ALL_SECTIONS if s != "validation_statuses"])


# ----------------------------------------------------------------------
# 6. valid + unknown
# ----------------------------------------------------------------------
class TestValidAndUnknown(Prompt516TestCase):

    def test_valid_sections_still_returned_alongside_unknown(self):
        summary = _summary()
        result = filt(summary, ["bogus", "rates", "other", "trend"])
        self.assertEqual(result["requested_sections"], ["bogus", "rates", "other", "trend"])
        self.assertEqual(result["included_sections"], ["rates", "trend"])
        self.assertEqual(result["unknown_sections"], ["bogus", "other"])
        self.assertEqual(result["unavailable_sections"], [])
        self.assertEqual(result["metrics"]["rates"], summary["metrics"]["rates"])
        self.assertEqual(result["report_validity"], REPORT_VALIDITY_VALID)


# ----------------------------------------------------------------------
# 7. valid + unavailable
# ----------------------------------------------------------------------
class TestValidAndUnavailable(Prompt516TestCase):

    def test_valid_sections_returned_alongside_unavailable(self):
        summary = _partial_summary()
        result = filt(summary, ["trend", "rates", "comparison_changes", "evaluation_counts"])
        self.assertEqual(result["included_sections"], ["evaluation_counts", "rates"])
        self.assertEqual(result["unavailable_sections"], ["comparison_changes", "trend"])
        self.assertIsNone(result["metrics"]["comparison_changes"])
        self.assertIsNone(result["metrics"]["trend"])
        self.assertEqual(result["metrics"]["rates"], summary["metrics"]["rates"])

    def test_valid_unavailable_and_unknown_together(self):
        result = filt(_partial_summary(), ["rates", "trend", "zzz"])
        self.assertEqual(result["included_sections"], ["rates"])
        self.assertEqual(result["unavailable_sections"], ["trend"])
        self.assertEqual(result["unknown_sections"], ["zzz"])
        self.assertIn("Unavailable sections: trend.", result["summary_text"])
        self.assertIn("Unknown sections: zzz.", result["summary_text"])


# ----------------------------------------------------------------------
# 8. empty section request
# ----------------------------------------------------------------------
class TestEmptyRequest(Prompt516TestCase):

    def test_empty_request_selects_nothing_and_never_means_everything(self):
        for request in ([], (), None, set(), ""):
            with self.subTest(request=request):
                result = filt(_summary(), request)
                self.assertFilterShape(result)
                if request == "":
                    # an empty string is one (unknown) name, not an empty request
                    self.assertEqual(result["unknown_sections"], [""])
                    continue
                self.assertEqual(result["requested_sections"], [])
                self.assertEqual(result["included_sections"], [])
                self.assertEqual(result["unavailable_sections"], [])
                self.assertEqual(result["unknown_sections"], [])
                self.assertEqual(result["metrics"], {})
                self.assertEqual(result["report_validity"], REPORT_VALIDITY_VALID)
                self.assertEqual(result["summary_text"], "No diagnostic summary sections were requested.")

    def test_default_request_is_empty(self):
        self.assertEqual(filt(_summary()), filt(_summary(), []))


# ----------------------------------------------------------------------
# 9. duplicate requested section names
# ----------------------------------------------------------------------
class TestDuplicateRequests(Prompt516TestCase):

    def test_duplicates_are_collapsed_first_occurrence_kept(self):
        summary = _summary()
        result = filt(summary, ["rates", "trend", "rates", "rates", "trend"])
        self.assertEqual(result["requested_sections"], ["rates", "trend"])
        self.assertEqual(result["included_sections"], ["rates", "trend"])
        self.assertEqual(result["summary_text"], filt(summary, ["rates", "trend"])["summary_text"])

    def test_duplicate_unknown_and_unavailable_names_are_collapsed(self):
        result = filt(_partial_summary(), ["x", "trend", "x", "trend"])
        self.assertEqual(result["unknown_sections"], ["x"])
        self.assertEqual(result["unavailable_sections"], ["trend"])

    def test_equal_but_differently_typed_names_are_not_merged(self):
        result = filt(_summary(), [1, 1.0, True])
        self.assertEqual(len(result["unknown_sections"]), 3)

    def test_duplicates_of_unhashable_names_do_not_crash(self):
        result = filt(_summary(), [["a"], ["a"], {"b": 1}])
        self.assertEqual(result["unknown_sections"], [["a"], {"b": 1}])


# ----------------------------------------------------------------------
# 10. invalid underlying diagnostic summary
# ----------------------------------------------------------------------
class TestInvalidSummary(Prompt516TestCase):

    def test_invalid_summary_stays_invalid_and_includes_nothing(self):
        summary = _invalid_summary()
        self.assertEqual(summary["report_validity"], REPORT_VALIDITY_INVALID)
        result = filt(summary, ["rates", "trend", "nope"])
        self.assertFilterShape(result)
        self.assertEqual(result["report_validity"], REPORT_VALIDITY_INVALID)
        self.assertEqual(result["included_sections"], [])
        self.assertEqual(result["unavailable_sections"], ["rates", "trend"])
        self.assertEqual(result["unknown_sections"], ["nope"])
        self.assertEqual(result["metrics"], {"rates": None, "trend": None})
        self.assertIn("INVALID", result["summary_text"])

    def test_invalid_summary_is_not_repaired_or_reinterpreted(self):
        summary = _invalid_summary()
        # tamper: an invalid summary that still carries "available" sections
        tampered = copy.deepcopy(summary)
        tampered["available_sections"] = list(_ALL_SECTIONS)
        tampered["metrics"]["rates"] = {"acceptance_rate": 1.0, "rejection_rate": 0.0}
        result = filt(tampered, _ALL_SECTIONS)
        self.assertEqual(result["report_validity"], REPORT_VALIDITY_INVALID)
        self.assertEqual(result["included_sections"], [])
        self.assertEqual(result["unavailable_sections"], _ALL_SECTIONS)
        self.assertTrue(all(value is None for value in result["metrics"].values()))
        self.assertNotIn("100.0%", result["summary_text"])

    def test_non_summary_inputs_are_invalid(self):
        for bad in (None, [], "summary", 7, {}, {"report_validity": "maybe"}):
            with self.subTest(bad=bad):
                result = filt(bad, ["rates", "zzz"])
                self.assertFilterShape(result)
                self.assertEqual(result["report_validity"], REPORT_VALIDITY_INVALID)
                self.assertEqual(result["included_sections"], [])
                self.assertEqual(result["unavailable_sections"], ["rates"])
                self.assertEqual(result["unknown_sections"], ["zzz"])
                self.assertTrue(result["validation_errors"])

    def test_non_dict_summary_error_is_named(self):
        self.assertEqual(filt(None, [])["validation_errors"], ["summary_not_a_dict"])

    def test_invalid_summary_with_empty_request(self):
        result = filt(_invalid_summary(), [])
        self.assertEqual(result["report_validity"], REPORT_VALIDITY_INVALID)
        self.assertEqual(result["requested_sections"], [])
        self.assertIn("INVALID", result["summary_text"])

    def test_valid_summary_with_malformed_fields_is_invalid(self):
        for field in ("metrics", "available_sections", "unavailable_sections", "validation_errors"):
            with self.subTest(field=field):
                broken = _summary()
                del broken[field]
                result = filt(broken, ["rates"])
                self.assertEqual(result["report_validity"], REPORT_VALIDITY_INVALID)
                self.assertEqual(result["included_sections"], [])
                self.assertIn("summary_field_missing_or_malformed:" + field, result["validation_errors"])


# ----------------------------------------------------------------------
# 11. summary with validation errors
# ----------------------------------------------------------------------
class TestSummaryWithValidationErrors(Prompt516TestCase):

    def test_errors_are_preserved_unchanged_and_in_order(self):
        errors = ["mismatched_field:trend", "count_negative:comparison", "zzz"]
        summary = _invalid_summary(errors)
        self.assertEqual(summary["validation_errors"], errors)
        result = filt(summary, ["trend"])
        self.assertEqual(result["validation_errors"], errors)
        for error in errors:
            self.assertIn(error, result["summary_text"])

    def test_error_list_is_an_independent_copy(self):
        summary = _invalid_summary(["e1"])
        result = filt(summary, ["trend"])
        result["validation_errors"].append("added")
        self.assertEqual(summary["validation_errors"], ["e1"])

    def test_real_514_errors_survive_the_whole_chain(self):
        _, _, built, _ = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison"]["total_considered"] = -1
        validation = validate(broken)
        self.assertFalse(validation["valid"])
        result = filt(fmt(broken, validation), ["comparison_changes"])
        self.assertEqual(result["validation_errors"], validation["errors"])
        self.assertEqual(result["report_validity"], REPORT_VALIDITY_INVALID)

    def test_summary_claiming_valid_while_carrying_errors_is_not_trusted(self):
        summary = _summary()
        summary["validation_errors"] = ["something_is_wrong"]
        result = filt(summary, ["rates"])
        self.assertEqual(result["report_validity"], REPORT_VALIDITY_INVALID)
        self.assertEqual(result["included_sections"], [])
        self.assertEqual(result["validation_errors"][0], "something_is_wrong")
        self.assertIn("summary_valid_with_validation_errors", result["validation_errors"])

    def test_non_string_errors_do_not_crash_the_text(self):
        # (built by hand: Prompt 515 itself only ever carries the string
        # errors Prompt 514 produces)
        summary = _invalid_summary()
        summary["validation_errors"] = [1, None]
        result = filt(summary, ["rates"])
        self.assertEqual(result["validation_errors"], [1, None])
        self.assertIn("INVALID", result["summary_text"])


# ----------------------------------------------------------------------
# 12. missing optional sections
# ----------------------------------------------------------------------
class TestMissingOptionalSections(Prompt516TestCase):

    def test_section_listed_available_but_absent_from_metrics_is_unavailable(self):
        summary = _summary()
        del summary["metrics"]["trend"]
        result = filt(summary, ["trend", "rates"])
        self.assertEqual(result["included_sections"], ["rates"])
        self.assertEqual(result["unavailable_sections"], ["trend"])
        self.assertIsNone(result["metrics"]["trend"])

    def test_section_not_listed_available_is_unavailable_even_if_metrics_has_a_value(self):
        summary = _summary()
        summary["available_sections"].remove("trend")
        result = filt(summary, ["trend"])
        self.assertEqual(result["unavailable_sections"], ["trend"])
        self.assertIsNone(result["metrics"]["trend"])

    def test_no_dominant_reason_is_still_an_included_value_of_none(self):
        summary = _summary([{"accepted": 3}])
        self.assertIn("dominant_rejection_reason", summary["available_sections"])
        self.assertIsNone(summary["metrics"]["dominant_rejection_reason"])
        result = filt(summary, ["dominant_rejection_reason"])
        self.assertEqual(result["included_sections"], ["dominant_rejection_reason"])
        self.assertIsNone(result["metrics"]["dominant_rejection_reason"])
        self.assertIn("No dominant rejection reason", result["summary_text"])

    def test_missing_sections_are_never_replaced_with_data(self):
        summary = _partial_summary()
        result = filt(summary, ["comparison_changes", "trend"])
        self.assertEqual(result["metrics"], {"comparison_changes": None, "trend": None})
        self.assertNotIn("->", result["summary_text"])

    def test_missing_optional_nested_values_do_not_crash_the_text(self):
        summary = _summary()
        summary["metrics"]["comparison_changes"] = {}
        summary["metrics"]["trend"] = {}
        summary["metrics"]["rates"] = {}
        result = filt(summary, ["rates", "comparison_changes", "trend"])
        self.assertEqual(result["included_sections"], ["rates", "comparison_changes", "trend"])
        self.assertIn("n/a", result["summary_text"])

    def test_malformed_section_value_falls_back_to_plain_readout(self):
        summary = _summary()
        summary["metrics"]["rates"] = "not-a-dict"
        result = filt(summary, ["rates"])
        self.assertEqual(result["metrics"]["rates"], "not-a-dict")
        self.assertEqual(result["summary_text"], "rates: not-a-dict")


# ----------------------------------------------------------------------
# 13. numeric values unchanged
# ----------------------------------------------------------------------
class TestNumericValuesUnchanged(Prompt516TestCase):

    def test_counts_and_rates_keep_value_type_and_precision(self):
        summary = _summary([{"accepted": 1, "irrelevant": 2}])
        result = filt(summary, ["evaluation_counts", "rates"])
        for section in ("evaluation_counts", "rates"):
            source, copied = summary["metrics"][section], result["metrics"][section]
            self.assertEqual(copied, source)
            for key in source:
                self.assertIs(type(copied[key]), type(source[key]))
                self.assertEqual(repr(copied[key]), repr(source[key]))
        self.assertEqual(result["metrics"]["rates"]["acceptance_rate"], 1 / 3)
        self.assertNotEqual(result["metrics"]["rates"]["acceptance_rate"], round(1 / 3, 1))

    def test_comparison_numeric_deltas_are_unchanged(self):
        summary = _summary([{"accepted": 4}, {"accepted": 1, "irrelevant": 2}])
        result = filt(summary, ["comparison_changes"])
        self.assertEqual(result["metrics"]["comparison_changes"]["numeric"],
                         summary["metrics"]["comparison_changes"]["numeric"])
        self.assertEqual(repr(result["metrics"]["comparison_changes"]["numeric"]),
                         repr(summary["metrics"]["comparison_changes"]["numeric"]))

    def test_trend_start_end_delta_are_unchanged(self):
        summary = _summary([{"accepted": 1}, {"accepted": 2, "irrelevant": 1}, {"accepted": 2, "irrelevant": 3}])
        result = filt(summary, ["trend"])
        for field in ("total_evaluations", "acceptance_rate", "rejection_rate"):
            self.assertEqual(result["metrics"]["trend"][field], summary["metrics"]["trend"][field])

    def test_percentage_text_is_display_only(self):
        result = filt(_summary([{"accepted": 1, "irrelevant": 2}]), ["rates"])
        self.assertIn("33.3%", result["summary_text"])
        self.assertNotEqual(result["metrics"]["rates"]["acceptance_rate"], 0.333)

    def test_zero_evaluation_values_stay_zero(self):
        summary = _summary([{}])
        result = filt(summary, ["evaluation_counts", "rates"])
        self.assertEqual(result["metrics"]["evaluation_counts"], summary["metrics"]["evaluation_counts"])
        self.assertEqual(result["metrics"]["evaluation_counts"]["total_evaluations"], 0)


# ----------------------------------------------------------------------
# 14. trend states unchanged
# ----------------------------------------------------------------------
class TestTrendStatesUnchanged(Prompt516TestCase):

    def _states(self, counts_list):
        summary = _summary(counts_list)
        result = filt(summary, ["trend"])
        return summary, result

    def test_increased(self):
        summary, result = self._states([{"accepted": 1}, {"accepted": 2}, {"accepted": 3}])
        self.assertEqual(result["metrics"]["trend"]["total_evaluations"]["state"], "increased")
        self.assertIn("total_evaluations: increased", result["summary_text"])

    def test_decreased(self):
        summary, result = self._states([{"accepted": 5}, {"accepted": 3}, {"accepted": 1}])
        self.assertEqual(result["metrics"]["trend"]["accepted_count"]["state"], "decreased")
        self.assertIn("accepted_count: decreased", result["summary_text"])

    def test_unchanged(self):
        summary, result = self._states([{"accepted": 2}, {"accepted": 4}, {"accepted": 6}])
        self.assertEqual(result["metrics"]["trend"]["no_candidate_count"]["state"], "unchanged")
        self.assertIn("no_candidate_count: unchanged", result["summary_text"])

    def test_insufficient_data(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = report(snapshots=history, comparisons=[comparison])
        summary = fmt(built, validate(built, snapshots=history, comparisons=[comparison]))
        result = filt(summary, ["trend"])
        self.assertEqual(result["metrics"]["trend"]["total_evaluations"]["state"], "insufficient data")
        self.assertIn("total_evaluations: insufficient data", result["summary_text"])

    def test_every_numeric_state_is_carried_through_verbatim(self):
        summary = _summary([{"accepted": 1}, {"accepted": 2, "irrelevant": 2}, {"accepted": 2, "irrelevant": 5}])
        result = filt(summary, ["trend"])
        for field, entry in summary["metrics"]["trend"].items():
            if isinstance(entry, dict) and "state" in entry:
                self.assertEqual(result["metrics"]["trend"][field]["state"], entry["state"])
        states = {e["state"] for e in result["metrics"]["trend"].values() if isinstance(e, dict) and "state" in e}
        self.assertTrue(states <= {"increased", "decreased", "unchanged", "insufficient data",
                                   "changed", "appeared", "disappeared"})


# ----------------------------------------------------------------------
# 15. categorical states unchanged
# ----------------------------------------------------------------------
class TestCategoricalStatesUnchanged(Prompt516TestCase):

    def _comparison(self, counts_list):
        return filt(_summary(counts_list), ["comparison_changes"])

    def test_changed(self):
        result = self._comparison([{"irrelevant": 3}, {"low_reliability": 3}])
        self.assertEqual(result["metrics"]["comparison_changes"]["dominant_rejection_reason_change"], "changed")
        self.assertIn("dominant_rejection_reason: changed", result["summary_text"])

    def test_appeared(self):
        result = self._comparison([{"accepted": 3}, {"irrelevant": 3}])
        self.assertEqual(result["metrics"]["comparison_changes"]["dominant_rejection_reason_change"], "appeared")
        self.assertIn("dominant_rejection_reason: appeared", result["summary_text"])

    def test_disappeared(self):
        result = self._comparison([{"irrelevant": 3}, {"accepted": 3}])
        self.assertEqual(result["metrics"]["comparison_changes"]["dominant_rejection_reason_change"], "disappeared")
        self.assertIn("dominant_rejection_reason: disappeared", result["summary_text"])

    def test_unchanged(self):
        summary = _summary([{"irrelevant": 3}, {"irrelevant": 5}])
        result = filt(summary, ["comparison_changes", "trend"])
        self.assertEqual(result["metrics"]["comparison_changes"]["dominant_rejection_reason_change"], "unchanged")
        self.assertEqual(result["metrics"]["comparison_changes"]["validation_status_change"], "unchanged")
        self.assertEqual(result["metrics"]["trend"]["dominant_rejection_reason"]["state"], "unchanged")

    def test_insufficient_data(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = report(snapshots=history, comparisons=[comparison])
        summary = fmt(built, validate(built, snapshots=history, comparisons=[comparison]))
        result = filt(summary, ["trend"])
        self.assertEqual(result["metrics"]["trend"]["dominant_rejection_reason"]["state"], "insufficient data")
        self.assertEqual(result["metrics"]["trend"]["validation_status"]["state"],
                         summary["metrics"]["trend"]["validation_status"]["state"])

    def test_not_comparable_comparison_is_described_only_as_such(self):
        summary = _summary()
        summary["metrics"]["comparison_changes"] = dict(
            summary["metrics"]["comparison_changes"], comparable=False,
            dominant_rejection_reason_change="insufficient data")
        result = filt(summary, ["comparison_changes"])
        self.assertIn("not comparable", result["summary_text"])
        self.assertEqual(result["metrics"]["comparison_changes"]["dominant_rejection_reason_change"],
                         "insufficient data")

    def test_identical_comparison_reports_no_change(self):
        result = filt(_summary([{"accepted": 1}, {"accepted": 1}]), ["comparison_changes"])
        self.assertIn("no change since the previous comparable snapshot", result["summary_text"])


# ----------------------------------------------------------------------
# 16. chronological ordering unchanged
# ----------------------------------------------------------------------
class TestChronologicalOrderingUnchanged(Prompt516TestCase):

    def test_comparison_earlier_and_later_keep_their_positions(self):
        summary = _summary([{"accepted": 1}, {"accepted": 3}, {"irrelevant": 2}, {"irrelevant": 4}])
        result = filt(summary, ["comparison_changes"])
        source, copied = summary["metrics"]["comparison_changes"], result["metrics"]["comparison_changes"]
        self.assertEqual(copied["earlier"], source["earlier"])
        self.assertEqual(copied["later"], source["later"])
        self.assertEqual(copied["changed_fields"], source["changed_fields"])
        self.assertEqual(list(copied), list(source))
        self.assertEqual(list(copied["numeric"]), list(source["numeric"]))

    def test_trend_chronological_range_is_unchanged(self):
        summary = _summary([{"accepted": 1}, {"accepted": 2}, {"accepted": 3}, {"accepted": 4}])
        result = filt(summary, ["trend"])
        source, copied = summary["metrics"]["trend"], result["metrics"]["trend"]
        self.assertEqual(copied["chronological_range"], source["chronological_range"])
        self.assertEqual(copied["eligible_count"], source["eligible_count"])
        self.assertEqual(copied["total_comparisons"], source["total_comparisons"])
        self.assertEqual(list(copied), list(source))

    def test_trend_text_lists_fields_in_the_source_order(self):
        summary = _summary()
        result = filt(summary, ["trend"])
        source_fields = [f for f, e in summary["metrics"]["trend"].items()
                         if isinstance(e, dict) and "state" in e]
        positions = [result["summary_text"].index(field + ":") for field in source_fields]
        self.assertEqual(positions, sorted(positions))

    def test_included_metrics_follow_the_fixed_section_order_not_request_order(self):
        result = filt(_summary(), list(reversed(_ALL_SECTIONS)))
        self.assertEqual(list(result["metrics"]), _ALL_SECTIONS)
        self.assertEqual(result["included_sections"], _ALL_SECTIONS)
        self.assertEqual(result["requested_sections"], list(reversed(_ALL_SECTIONS)))


# ----------------------------------------------------------------------
# 17. deterministic output
# ----------------------------------------------------------------------
class TestDeterministicOutput(Prompt516TestCase):

    def test_repeated_calls_are_equal(self):
        summary = _summary()
        request = ["trend", "nope", "rates", "rates"]
        first = filt(summary, request)
        for _ in range(5):
            self.assertEqual(filt(summary, request), first)

    def test_equal_summaries_built_independently_give_equal_results(self):
        self.assertEqual(filt(_summary(), ["trend", "rates"]), filt(_summary(), ["trend", "rates"]))

    def test_set_requests_are_ordered_deterministically(self):
        summary = _summary()
        first = filt(summary, {"trend", "rates", "zzz", "aaa"})
        second = filt(summary, frozenset(["aaa", "zzz", "rates", "trend"]))
        self.assertEqual(first, second)
        self.assertEqual(first["unknown_sections"], ["aaa", "zzz"])

    def test_generator_and_tuple_requests_match_list_requests(self):
        summary = _summary()
        expected = filt(summary, ["rates", "trend"])
        self.assertEqual(filt(summary, iter(["rates", "trend"])), expected)
        self.assertEqual(filt(summary, ("rates", "trend")), expected)

    def test_invalid_path_is_deterministic(self):
        summary = _invalid_summary(["a", "b"])
        self.assertEqual(filt(summary, ["trend", "x"]), filt(summary, ["trend", "x"]))

    def test_text_avoids_judgement_words(self):
        for summary in (_summary(), _partial_summary(), _invalid_summary()):
            text = filt(summary, _ALL_SECTIONS + ["zzz"])["summary_text"].lower()
            for word in _FORBIDDEN_WORDS:
                self.assertNotIn(word, text)


# ----------------------------------------------------------------------
# 18. original summary not mutated
# ----------------------------------------------------------------------
class TestSummaryNotMutated(Prompt516TestCase):

    def test_summary_is_unchanged_by_filtering(self):
        for summary in (_summary(), _partial_summary(), _invalid_summary(["e"])):
            before = copy.deepcopy(summary)
            filt(summary, _ALL_SECTIONS + ["zzz", "rates"])
            self.assertEqual(summary, before)

    def test_request_list_is_not_mutated(self):
        request = ["rates", "rates", "zzz", "trend"]
        before = list(request)
        filt(_summary(), request)
        self.assertEqual(request, before)

    def test_returned_values_are_independent_copies(self):
        summary = _summary()
        before = copy.deepcopy(summary)
        result = filt(summary, ["comparison_changes", "trend", "rates"])
        result["metrics"]["comparison_changes"]["changed_fields"].append("zzz")
        result["metrics"]["trend"]["chronological_range"]["earlier"] = "tampered"
        result["metrics"]["rates"]["acceptance_rate"] = -1
        result["requested_sections"].append("zzz")
        result["included_sections"].clear()
        self.assertEqual(summary, before)

    def test_returned_unknown_names_are_independent_copies(self):
        name = ["mutable"]
        result = filt(_summary(), [name])
        result["unknown_sections"][0].append("changed")
        result["requested_sections"][0].append("changed")
        self.assertEqual(name, ["mutable"])


# ----------------------------------------------------------------------
# 19. source diagnostic objects not mutated
# ----------------------------------------------------------------------
class TestSourceObjectsNotMutated(Prompt516TestCase):

    def test_snapshots_comparisons_trend_report_and_validation_are_untouched(self):
        history, comparisons, built, validation = _pipeline(
            [{"accepted": 1}, {"accepted": 3}, {"irrelevant": 2}, {"low_reliability": 2}])
        trend_summary = trend(comparisons)
        before = {
            "snapshots": copy.deepcopy(history.get_all()),
            "comparisons": copy.deepcopy(comparisons),
            "trend": copy.deepcopy(trend_summary),
            "report": copy.deepcopy(built),
            "validation": copy.deepcopy(validation),
        }
        summary = fmt(built, validation)
        filt(summary, _ALL_SECTIONS + ["zzz"])
        filt(summary, [])
        self.assertEqual(history.get_all(), before["snapshots"])
        self.assertEqual(comparisons, before["comparisons"])
        self.assertEqual(trend_summary, before["trend"])
        self.assertEqual(built, before["report"])
        self.assertEqual(validation, before["validation"])

    def test_statistics_object_is_untouched(self):
        stats = _stats(accepted=2, irrelevant=1)
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(stats)
        before = stats.summary()
        built = report(snapshots=history)
        filt(fmt(built, validate(built, snapshots=history)), _ALL_SECTIONS)
        self.assertEqual(stats.summary(), before)

    def test_filtering_does_not_change_what_514_reports(self):
        history, comparisons, built, validation = _pipeline()
        filt(fmt(built, validation), _ALL_SECTIONS)
        self.assertEqual(validate(built, snapshots=history, comparisons=comparisons), validation)


# ----------------------------------------------------------------------
# 20. Prompt 515 behavior unchanged
# ----------------------------------------------------------------------
class TestPrompt515Unchanged(Prompt516TestCase):

    def test_515_summary_shape_is_unchanged(self):
        self.assertEqual(list(_summary().keys()), _SUMMARY_KEYS)
        self.assertEqual(list(_invalid_summary().keys()), _SUMMARY_KEYS)

    def test_515_output_is_identical_before_and_after_filtering(self):
        _, _, built, validation = _pipeline()
        before = fmt(built, validation)
        filt(before, _ALL_SECTIONS)
        self.assertEqual(fmt(built, validation), before)

    def test_515_invalid_summary_is_unchanged(self):
        summary = _invalid_summary(["e1"])
        self.assertEqual(summary["report_validity"], REPORT_VALIDITY_INVALID)
        self.assertEqual(summary["available_sections"], [])
        self.assertEqual(summary["unavailable_sections"], _ALL_SECTIONS)
        self.assertEqual(summary["metrics"], {s: None for s in _ALL_SECTIONS})
        self.assertEqual(summary["validation_errors"], ["e1"])

    def test_515_section_vocabulary_is_the_filter_vocabulary(self):
        summary = _summary()
        self.assertEqual(sorted(summary["available_sections"] + summary["unavailable_sections"]),
                         sorted(_ALL_SECTIONS))
        result = filt(summary, _ALL_SECTIONS)
        self.assertEqual(result["unknown_sections"], [])

    def test_filter_is_not_wired_into_any_non_diagnostic_module(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for name in files:
                if not name.endswith(".py") or name == "learned_knowledge_statistics.py":
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    self.assertNotIn("filter_learned_knowledge_diagnostic_summary", handle.read(),
                                     os.path.join(folder, name))


# ----------------------------------------------------------------------
# 21. regression coverage for Prompts 500-515
# ----------------------------------------------------------------------
class TestRegression500To515(Prompt516TestCase):

    def test_gate_trace_statistics_unaffected(self):
        stats = _stats(accepted=2, irrelevant=1)
        before = stats.summary()
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(stats)
        built = report(snapshots=history)
        filt(fmt(built, validate(built, snapshots=history)), _ALL_SECTIONS)
        self.assertEqual(stats.summary(), before)

    def test_snapshot_history_unaffected(self):
        history = _history([{"accepted": 1}, {"accepted": 2}])
        before_all = history.get_all()
        comparisons = _chain(history)
        built = report(snapshots=history, comparisons=comparisons)
        filt(fmt(built, validate(built, snapshots=history, comparisons=comparisons)), ["trend"])
        self.assertEqual(history.get_all(), before_all)

    def test_comparison_and_trend_functions_unaffected(self):
        history = _history([{"accepted": 1}, {"accepted": 3}])
        comparisons = _chain(history)
        comparison_before = copy.deepcopy(comparisons[0])
        trend_before = trend(comparisons)
        built = report(snapshots=history, comparisons=comparisons)
        filt(fmt(built, validate(built, snapshots=history, comparisons=comparisons)), _ALL_SECTIONS)
        self.assertEqual(comparisons[0], comparison_before)
        self.assertEqual(trend(comparisons), trend_before)

    def test_unified_report_and_validation_still_agree(self):
        history, comparisons, built, validation = _pipeline()
        self.assertTrue(validation["valid"])
        self.assertEqual(validate(built, snapshots=history, comparisons=comparisons), validation)
        self.assertTrue(fmt(built, validation)["report_validity"] == REPORT_VALIDITY_VALID)

    def test_broken_report_is_still_rejected_by_514_and_stays_invalid_through_516(self):
        _, _, built, _ = _pipeline()
        broken = copy.deepcopy(built)
        del broken["trend"]
        validation = validate(broken)
        self.assertFalse(validation["valid"])
        result = filt(fmt(broken, validation), ["trend", "rates"])
        self.assertEqual(result["report_validity"], REPORT_VALIDITY_INVALID)
        self.assertEqual(result["validation_errors"], validation["errors"])


if __name__ == "__main__":
    unittest.main()
