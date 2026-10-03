"""
Tests for Prompt 515 - Human-Readable Diagnostic Summary.

`format_learned_knowledge_diagnostic_summary()`
(learning/learned_knowledge_statistics.py) is a deterministic, read-only
presentation layer over the dict `build_learned_knowledge_diagnostic_report()`
(Prompt 513) returns, judged by its own already-computed
`validate_learned_knowledge_diagnostic_report()` (Prompt 514) result. It
never recomputes, repairs, or reinterprets anything; it only reads what
the existing pipeline already produced.

Covers:
    1.  valid complete diagnostic report
    2.  invalid diagnostic report
    3.  missing sections
    4.  no snapshots
    5.  one snapshot
    6.  multiple snapshots
    7.  no comparisons
    8.  valid comparison information
    9.  invalid comparison information
    10. valid trend information
    11. invalid trend information
    12. zero-evaluation data
    13. missing optional values
    14. increased trend
    15. decreased trend
    16. unchanged trend
    17. insufficient-data trend
    18. changed categorical state
    19. appeared categorical state
    20. disappeared categorical state
    21. deterministic output
    22. accurate numeric formatting
    23. no fabricated values
    24. formatter does not mutate input objects
    25. existing Prompt 514 validation behavior remains unchanged
    26. regression coverage for Prompts 500-514

Run directly:
    python -m unittest tests.test_learned_knowledge_diagnostic_summary -v
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
    SNAPSHOT_VALIDATION_VALID, SNAPSHOT_VALIDATION_INVALID,
    REPORT_STATUS_NO_DATA, REPORT_STATUS_PARTIAL, REPORT_STATUS_VALID, REPORT_STATUS_INVALID,
    REPORT_VALIDITY_VALID, REPORT_VALIDITY_INVALID,
    summarize_learned_knowledge_diagnostic_snapshot_comparison_trend as trend,
    validate_learned_knowledge_diagnostic_snapshot_comparison_trend as validate_trend,
    validate_learned_knowledge_diagnostic_snapshot_comparison as validate_comparison,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
)

_SUMMARY_KEYS = [
    "summary_text", "report_validity", "validation_errors",
    "available_sections", "unavailable_sections", "metrics",
]
_ALL_SECTIONS = [
    "evaluation_counts", "rates", "dominant_rejection_reason",
    "comparison_changes", "trend", "validation_statuses",
]
_FORBIDDEN_WORDS = (
    "good", "bad", "healthy", "unhealthy", "successful", "unsuccessful",
)


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


def _invalid_status_history_and_comparison():
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record({}, {"valid": False, "errors": ["boom"]})
    history.record_statistics(_stats(accepted=2))
    comparison = history.compare_sequences(1, 2)
    assert validate_comparison(comparison)["valid"] is False
    return history, comparison


class Prompt515TestCase(unittest.TestCase):

    def assertSummaryShape(self, summary):
        self.assertEqual(list(summary.keys()), _SUMMARY_KEYS)
        self.assertIn(summary["report_validity"], (REPORT_VALIDITY_VALID, REPORT_VALIDITY_INVALID))
        self.assertIsInstance(summary["summary_text"], str)
        self.assertIsInstance(summary["validation_errors"], list)
        self.assertIsInstance(summary["available_sections"], list)
        self.assertIsInstance(summary["unavailable_sections"], list)
        self.assertIsInstance(summary["metrics"], dict)
        self.assertEqual(
            sorted(summary["available_sections"] + summary["unavailable_sections"]),
            sorted(_ALL_SECTIONS),
        )
        self.assertEqual(
            set(summary["available_sections"]) & set(summary["unavailable_sections"]), set())
        self.assertEqual(set(summary["metrics"].keys()), set(_ALL_SECTIONS))
        for word in _FORBIDDEN_WORDS:
            self.assertNotIn(word, summary["summary_text"].lower())

    def assertInvalidSummary(self, summary, validation):
        self.assertSummaryShape(summary)
        self.assertEqual(summary["report_validity"], REPORT_VALIDITY_INVALID)
        self.assertEqual(summary["available_sections"], [])
        self.assertEqual(sorted(summary["unavailable_sections"]), sorted(_ALL_SECTIONS))
        for section in _ALL_SECTIONS:
            self.assertIsNone(summary["metrics"][section])
        self.assertEqual(summary["validation_errors"], list(validation.get("errors", [])))
        self.assertIn("INVALID", summary["summary_text"])


# ----------------------------------------------------------------------
# 1. valid complete diagnostic report
# ----------------------------------------------------------------------
class TestValidCompleteReport(Prompt515TestCase):

    def test_fully_populated_report_is_summarized(self):
        _, _, built, validation = _pipeline()
        self.assertTrue(validation["valid"])
        summary = fmt(built, validation)
        self.assertSummaryShape(summary)
        self.assertEqual(summary["report_validity"], REPORT_VALIDITY_VALID)
        self.assertEqual(summary["validation_errors"], [])
        self.assertEqual(sorted(summary["available_sections"]), sorted(_ALL_SECTIONS))
        self.assertEqual(summary["unavailable_sections"], [])

    def test_metrics_match_report_exactly(self):
        _, _, built, validation = _pipeline()
        summary = fmt(built, validation)
        latest = built["snapshots"]["latest"]
        self.assertEqual(summary["metrics"]["evaluation_counts"]["total_evaluations"],
                          latest["total_evaluations"])
        self.assertEqual(summary["metrics"]["rates"]["acceptance_rate"], latest["acceptance_rate"])
        self.assertEqual(summary["metrics"]["dominant_rejection_reason"],
                          latest["dominant_rejection_reason"])


# ----------------------------------------------------------------------
# 2. invalid diagnostic report
# ----------------------------------------------------------------------
class TestInvalidReport(Prompt515TestCase):

    def test_report_that_fails_514_validation_is_reported_invalid(self):
        _, _, built, _ = _pipeline()
        broken = copy.deepcopy(built)
        broken["structural_status"] = "unknown"
        validation = validate(broken)
        self.assertFalse(validation["valid"])
        summary = fmt(broken, validation)
        self.assertInvalidSummary(summary, validation)

    def test_non_dict_validation_is_treated_as_invalid(self):
        _, _, built, _ = _pipeline()
        summary = fmt(built, None)
        self.assertInvalidSummary(summary, {"errors": ["validation_not_a_dict"]})

    def test_non_dict_report_with_valid_looking_validation_is_still_invalid(self):
        summary = fmt(None, {"valid": True, "well_formed": True, "errors": [], "warnings": []})
        self.assertInvalidSummary(summary, {"errors": ["report_not_a_dict"]})

    def test_validation_without_valid_key_is_treated_as_invalid(self):
        summary = fmt({}, {"well_formed": True, "errors": [], "warnings": []})
        self.assertEqual(summary["report_validity"], REPORT_VALIDITY_INVALID)

    def test_invalid_report_does_not_leak_section_data(self):
        # Even though `broken` still carries real snapshot/comparison/trend
        # data, an invalid verdict means none of it is described.
        _, _, built, _ = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison"]["total_considered"] = -1
        validation = validate(broken)
        self.assertFalse(validation["valid"])
        summary = fmt(broken, validation)
        self.assertNotIn(str(broken["snapshots"]["latest"]["total_evaluations"]), summary["summary_text"])
        self.assertInvalidSummary(summary, validation)


# ----------------------------------------------------------------------
# 3. missing sections
# ----------------------------------------------------------------------
class TestMissingSections(Prompt515TestCase):

    def test_missing_top_level_section_fails_514_and_is_reported_invalid(self):
        _, _, built, _ = _pipeline()
        broken = copy.deepcopy(built)
        del broken["trend"]
        validation = validate(broken)
        self.assertFalse(validation["valid"])
        summary = fmt(broken, validation)
        self.assertInvalidSummary(summary, validation)


# ----------------------------------------------------------------------
# 4. no snapshots
# ----------------------------------------------------------------------
class TestNoSnapshots(Prompt515TestCase):

    def test_empty_report_has_no_available_sections_except_validation_statuses(self):
        built = report()
        validation = validate(built)
        self.assertTrue(validation["valid"])
        self.assertEqual(built["structural_status"], REPORT_STATUS_NO_DATA)
        summary = fmt(built, validation)
        self.assertEqual(summary["available_sections"], ["validation_statuses"])
        self.assertEqual(
            sorted(summary["unavailable_sections"]),
            sorted(s for s in _ALL_SECTIONS if s != "validation_statuses"))
        for section in ("evaluation_counts", "rates", "dominant_rejection_reason",
                         "comparison_changes", "trend"):
            self.assertIsNone(summary["metrics"][section])
        self.assertIn("unavailable", summary["summary_text"])


# ----------------------------------------------------------------------
# 5. one snapshot
# ----------------------------------------------------------------------
class TestOneSnapshot(Prompt515TestCase):

    def test_single_snapshot_has_evaluation_data_but_no_comparison_or_trend(self):
        history = _history([{"accepted": 4, "irrelevant": 1}])
        built = report(snapshots=history)
        validation = validate(built, snapshots=history)
        self.assertTrue(validation["valid"])
        self.assertEqual(built["structural_status"], REPORT_STATUS_PARTIAL)
        summary = fmt(built, validation)
        self.assertIn("evaluation_counts", summary["available_sections"])
        self.assertIn("comparison_changes", summary["unavailable_sections"])
        self.assertIn("trend", summary["unavailable_sections"])
        self.assertEqual(summary["metrics"]["evaluation_counts"]["total_evaluations"], 5)


# ----------------------------------------------------------------------
# 6. multiple snapshots
# ----------------------------------------------------------------------
class TestMultipleSnapshots(Prompt515TestCase):

    def test_three_snapshots_full_pipeline_available(self):
        _, _, built, validation = _pipeline(
            [{"accepted": 1}, {"accepted": 2}, {"accepted": 3}, {"irrelevant": 4}])
        summary = fmt(built, validation)
        self.assertEqual(sorted(summary["available_sections"]), sorted(_ALL_SECTIONS))


# ----------------------------------------------------------------------
# 7. no comparisons
# ----------------------------------------------------------------------
class TestNoComparisons(Prompt515TestCase):

    def test_snapshots_without_comparisons_has_no_comparison_or_trend(self):
        history = _history([{"accepted": 1}, {"accepted": 2}])
        built = report(snapshots=history)
        validation = validate(built, snapshots=history)
        summary = fmt(built, validation)
        self.assertIn("comparison_changes", summary["unavailable_sections"])
        self.assertIn("trend", summary["unavailable_sections"])


# ----------------------------------------------------------------------
# 8. valid comparison information
# ----------------------------------------------------------------------
class TestValidComparison(Prompt515TestCase):

    def test_comparison_changes_are_described(self):
        _, _, built, validation = _pipeline([{"accepted": 1}, {"accepted": 5}])
        summary = fmt(built, validation)
        self.assertIn("comparison_changes", summary["available_sections"])
        comp = summary["metrics"]["comparison_changes"]
        self.assertIn("accepted_count", comp["changed_fields"])
        self.assertEqual(comp["numeric"]["accepted_count"]["delta"], 4)
        self.assertIn("Comparison changes:", summary["summary_text"])

    def test_identical_comparison_reports_no_change(self):
        _, _, built, validation = _pipeline([{"accepted": 3}, {"accepted": 3}])
        summary = fmt(built, validation)
        comp = summary["metrics"]["comparison_changes"]
        self.assertTrue(comp["identical"])
        self.assertIn("no change", summary["summary_text"])


# ----------------------------------------------------------------------
# 9. invalid comparison information
# ----------------------------------------------------------------------
class TestInvalidComparison(Prompt515TestCase):

    def test_non_comparable_snapshots_are_not_described_as_comparison_changes(self):
        history, comparison = _invalid_status_history_and_comparison()
        # This comparison's own "valid" is True (structurally fine) but
        # "comparable" is False, since one snapshot's own analysis was
        # invalid - the existing Prompt 510 validator itself then marks
        # the comparison "valid": False (`source_snapshot_validation_
        # status_invalid:earlier`), even though it is well-formed. The
        # report built from it is still a fully valid (514) report -
        # faithfully reporting an untrustworthy comparison - so this
        # formatter correctly treats comparison_changes as unavailable
        # rather than fabricating numbers from an untrusted comparison.
        built = report(snapshots=history, comparisons=[comparison])
        validation = validate(built, snapshots=history, comparisons=[comparison])
        self.assertTrue(validation["valid"])
        self.assertFalse(built["comparison_validation"]["result"]["valid"])
        summary = fmt(built, validation)
        self.assertIn("comparison_changes", summary["unavailable_sections"])
        self.assertIsNone(summary["metrics"]["comparison_changes"])
        self.assertFalse(summary["metrics"]["validation_statuses"]["comparison_validation"])


# ----------------------------------------------------------------------
# 10. valid trend information
# ----------------------------------------------------------------------
class TestValidTrend(Prompt515TestCase):

    def test_trend_is_described_with_provided_summary(self):
        history = _history([{"accepted": 1}, {"accepted": 2}, {"accepted": 6}])
        comparisons = _chain(history)
        summary_dict = trend(comparisons)
        built = report(snapshots=history, comparisons=comparisons, trend_summary=summary_dict)
        validation = validate(built, snapshots=history, comparisons=comparisons, trend_summary=summary_dict)
        self.assertTrue(validation["valid"])
        summary = fmt(built, validation)
        self.assertIn("trend", summary["available_sections"])
        self.assertEqual(summary["metrics"]["trend"]["source"], "provided")


# ----------------------------------------------------------------------
# 11. invalid trend information
# ----------------------------------------------------------------------
class TestInvalidTrend(Prompt515TestCase):

    def test_trend_summary_that_fails_512_makes_the_whole_report_invalid(self):
        history, comparisons, built, _ = _pipeline()
        broken_trend = copy.deepcopy(built["trend"]["summary"])
        broken_trend["numeric"]["total_evaluations"]["state"] = "not_a_real_state"
        self.assertFalse(validate_trend(broken_trend)["valid"])
        broken_built = report(snapshots=history, comparisons=comparisons, trend_summary=broken_trend)
        self.assertEqual(broken_built["structural_status"], REPORT_STATUS_INVALID)
        validation = validate(broken_built)
        summary = fmt(broken_built, validation)
        # A report that FAITHFULLY reports an invalid trend is itself a
        # valid (514) report - so it is still described, but the trend
        # section is correctly marked unavailable since the embedded
        # trend_validation says it cannot be trusted.
        self.assertTrue(validation["valid"])
        self.assertEqual(summary["report_validity"], REPORT_VALIDITY_VALID)
        self.assertIn("trend", summary["unavailable_sections"])
        self.assertIsNone(summary["metrics"]["trend"])


# ----------------------------------------------------------------------
# 12. zero-evaluation data
# ----------------------------------------------------------------------
class TestZeroEvaluationData(Prompt515TestCase):

    def test_zero_evaluations_snapshot_is_described_without_dominant_reason(self):
        history = _history([{}])
        built = report(snapshots=history)
        validation = validate(built, snapshots=history)
        summary = fmt(built, validation)
        self.assertIn("evaluation_counts", summary["available_sections"])
        self.assertEqual(summary["metrics"]["evaluation_counts"]["total_evaluations"], 0)
        self.assertIsNone(summary["metrics"]["dominant_rejection_reason"])
        self.assertIn("No dominant rejection reason", summary["summary_text"])


# ----------------------------------------------------------------------
# 13. missing optional values
# ----------------------------------------------------------------------
class TestMissingOptionalValues(Prompt515TestCase):

    def test_no_dominant_rejection_reason_when_no_rejections(self):
        history = _history([{"accepted": 5}])
        built = report(snapshots=history)
        validation = validate(built, snapshots=history)
        summary = fmt(built, validation)
        self.assertIsNone(summary["metrics"]["dominant_rejection_reason"])
        self.assertIn("evaluation_counts", summary["available_sections"])


# ----------------------------------------------------------------------
# 14. increased trend
# ----------------------------------------------------------------------
class TestIncreasedTrend(Prompt515TestCase):

    def test_increased_field_reported_as_increased(self):
        _, _, built, validation = _pipeline(
            [{"accepted": 1}, {"accepted": 2}, {"accepted": 3}])
        summary = fmt(built, validation)
        self.assertEqual(summary["metrics"]["trend"]["total_evaluations"]["state"], "increased")
        self.assertIn("total_evaluations: increased", summary["summary_text"])


# ----------------------------------------------------------------------
# 15. decreased trend
# ----------------------------------------------------------------------
class TestDecreasedTrend(Prompt515TestCase):

    def test_decreased_field_reported_as_decreased(self):
        _, _, built, validation = _pipeline(
            [{"accepted": 5}, {"accepted": 3}, {"accepted": 1}])
        summary = fmt(built, validation)
        self.assertEqual(summary["metrics"]["trend"]["accepted_count"]["state"], "decreased")
        self.assertIn("accepted_count: decreased", summary["summary_text"])


# ----------------------------------------------------------------------
# 16. unchanged trend
# ----------------------------------------------------------------------
class TestUnchangedTrend(Prompt515TestCase):

    def test_unchanged_field_reported_as_unchanged(self):
        _, _, built, validation = _pipeline(
            [{"accepted": 2}, {"accepted": 4}, {"accepted": 6}])
        summary = fmt(built, validation)
        self.assertEqual(summary["metrics"]["trend"]["no_candidate_count"]["state"], "unchanged")
        self.assertIn("no_candidate_count: unchanged", summary["summary_text"])


# ----------------------------------------------------------------------
# 17. insufficient-data trend
# ----------------------------------------------------------------------
class TestInsufficientDataTrend(Prompt515TestCase):

    def test_no_eligible_comparisons_is_insufficient_data(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = report(snapshots=history, comparisons=[comparison])
        validation = validate(built, snapshots=history, comparisons=[comparison])
        summary = fmt(built, validation)
        self.assertIn("trend", summary["available_sections"])
        self.assertEqual(summary["metrics"]["trend"]["total_evaluations"]["state"], "insufficient data")
        self.assertIn("insufficient data", summary["summary_text"])


# ----------------------------------------------------------------------
# 18. changed categorical state
# ----------------------------------------------------------------------
class TestChangedCategoricalState(Prompt515TestCase):

    def test_dominant_rejection_reason_changed_between_two_reasons(self):
        _, _, built, validation = _pipeline(
            [{"irrelevant": 3}, {"low_reliability": 3}])
        summary = fmt(built, validation)
        comp = summary["metrics"]["comparison_changes"]
        self.assertEqual(comp["dominant_rejection_reason_change"], "changed")
        self.assertIn("(changed)", summary["summary_text"])


# ----------------------------------------------------------------------
# 19. appeared categorical state
# ----------------------------------------------------------------------
class TestAppearedCategoricalState(Prompt515TestCase):

    def test_dominant_rejection_reason_appears(self):
        _, _, built, validation = _pipeline([{"accepted": 3}, {"irrelevant": 3}])
        summary = fmt(built, validation)
        comp = summary["metrics"]["comparison_changes"]
        self.assertEqual(comp["dominant_rejection_reason_change"], "appeared")
        self.assertIn("(appeared)", summary["summary_text"])


# ----------------------------------------------------------------------
# 20. disappeared categorical state
# ----------------------------------------------------------------------
class TestDisappearedCategoricalState(Prompt515TestCase):

    def test_dominant_rejection_reason_disappears(self):
        _, _, built, validation = _pipeline([{"irrelevant": 3}, {"accepted": 3}])
        summary = fmt(built, validation)
        comp = summary["metrics"]["comparison_changes"]
        self.assertEqual(comp["dominant_rejection_reason_change"], "disappeared")
        self.assertIn("(disappeared)", summary["summary_text"])


# ----------------------------------------------------------------------
# 21. deterministic output
# ----------------------------------------------------------------------
class TestDeterministicOutput(Prompt515TestCase):

    def test_repeated_calls_produce_equal_results(self):
        _, _, built, validation = _pipeline()
        first = fmt(built, validation)
        second = fmt(built, validation)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)

    def test_invalid_path_is_also_deterministic(self):
        _, _, built, _ = _pipeline()
        broken = copy.deepcopy(built)
        broken["structural_status"] = "bogus"
        validation = validate(broken)
        first = fmt(broken, validation)
        second = fmt(broken, validation)
        self.assertEqual(first, second)


# ----------------------------------------------------------------------
# 22. accurate numeric formatting
# ----------------------------------------------------------------------
class TestAccurateNumericFormatting(Prompt515TestCase):

    def test_rates_are_exact_and_unrounded_in_metrics(self):
        history = _history([{"accepted": 1, "irrelevant": 2}])  # 1/3, 2/3
        built = report(snapshots=history)
        validation = validate(built, snapshots=history)
        summary = fmt(built, validation)
        self.assertEqual(summary["metrics"]["rates"]["acceptance_rate"], 1 / 3)
        self.assertEqual(summary["metrics"]["rates"]["rejection_rate"], 2 / 3)

    def test_percentage_text_reflects_the_same_rate(self):
        history = _history([{"accepted": 1, "irrelevant": 1}])  # 50%/50%
        built = report(snapshots=history)
        validation = validate(built, snapshots=history)
        summary = fmt(built, validation)
        self.assertIn("50.0%", summary["summary_text"])


# ----------------------------------------------------------------------
# 23. no fabricated values
# ----------------------------------------------------------------------
class TestNoFabricatedValues(Prompt515TestCase):

    def test_unavailable_sections_are_none_not_empty_dict(self):
        built = report()
        validation = validate(built)
        summary = fmt(built, validation)
        for section in ("evaluation_counts", "rates", "dominant_rejection_reason",
                         "comparison_changes", "trend"):
            self.assertIsNone(summary["metrics"][section])

    def test_invalid_report_metrics_are_all_none(self):
        _, _, built, _ = _pipeline()
        broken = copy.deepcopy(built)
        broken["structural_status"] = "bogus"
        validation = validate(broken)
        summary = fmt(broken, validation)
        for value in summary["metrics"].values():
            self.assertIsNone(value)


# ----------------------------------------------------------------------
# 24. formatter does not mutate input objects
# ----------------------------------------------------------------------
class TestNoMutation(Prompt515TestCase):

    def test_report_is_not_mutated(self):
        _, _, built, validation = _pipeline()
        before = copy.deepcopy(built)
        fmt(built, validation)
        self.assertEqual(built, before)

    def test_validation_is_not_mutated(self):
        _, _, built, validation = _pipeline()
        before = copy.deepcopy(validation)
        fmt(built, validation)
        self.assertEqual(validation, before)

    def test_nested_structures_in_result_are_independent_copies(self):
        _, _, built, validation = _pipeline()
        summary = fmt(built, validation)
        summary["metrics"]["comparison_changes"]["numeric"]["accepted_count"]["delta"] = 999999
        self.assertNotEqual(
            built["comparison"]["latest"]["numeric"]["accepted_count"]["delta"], 999999)


# ----------------------------------------------------------------------
# 25. existing Prompt 514 validation behavior remains unchanged
# ----------------------------------------------------------------------
class TestPrompt514Unchanged(Prompt515TestCase):

    def test_514_validator_still_behaves_as_before(self):
        _, _, built, validation = _pipeline()
        self.assertEqual(
            list(validation.keys()), ["valid", "well_formed", "errors", "warnings"])
        self.assertTrue(validation["valid"])
        self.assertTrue(validation["well_formed"])

    def test_calling_the_formatter_does_not_change_what_514_reports(self):
        _, _, built, _ = _pipeline()
        before = validate(built)
        fmt(built, validate(built))
        after = validate(built)
        self.assertEqual(before, after)


# ----------------------------------------------------------------------
# 26. regression coverage for Prompts 500-514
# ----------------------------------------------------------------------
class TestRegression500To514(Prompt515TestCase):

    def test_gate_trace_statistics_unaffected(self):
        stats = _stats(accepted=2, irrelevant=1)
        before = stats.summary()
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(stats)
        built = report(snapshots=history)
        fmt(built, validate(built, snapshots=history))
        self.assertEqual(stats.summary(), before)

    def test_snapshot_history_unaffected_by_formatting(self):
        history = _history([{"accepted": 1}, {"accepted": 2}])
        before_all = history.get_all()
        comparisons = _chain(history)
        built = report(snapshots=history, comparisons=comparisons)
        fmt(built, validate(built, snapshots=history, comparisons=comparisons))
        self.assertEqual(history.get_all(), before_all)

    def test_comparison_and_trend_functions_unaffected(self):
        history = _history([{"accepted": 1}, {"accepted": 3}])
        comparisons = _chain(history)
        comparison_before = copy.deepcopy(comparisons[0])
        trend_before = trend(comparisons)
        built = report(snapshots=history, comparisons=comparisons)
        fmt(built, validate(built, snapshots=history, comparisons=comparisons))
        self.assertEqual(comparisons[0], comparison_before)
        self.assertEqual(trend(comparisons), trend_before)


if __name__ == "__main__":
    unittest.main()
