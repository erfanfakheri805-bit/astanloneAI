"""
Tests for Prompt 514 - Validate Unified Diagnostic Reports.

`validate_learned_knowledge_diagnostic_report()`
(learning/learned_knowledge_statistics.py) is a deterministic, read-only
validator over the dict `build_learned_knowledge_diagnostic_report()`
(Prompt 513) returns. It reuses the existing snapshot check (Prompt 508/
506), the Prompt 510 comparison validator, the Prompt 512 trend validator
and the Prompt 513 status derivation; it never repairs a report, never
regenerates one, and never mutates anything it is given.

Covers:
    1.  fully valid unified report
    2.  missing required report section
    3.  invalid overall status
    4.  invalid field type
    5.  missing metric
    6.  invalid numeric metric
    7.  metric inconsistent with source data
    8.  incorrect validation status
    9.  comparison information inconsistent with source comparison
    10. trend information inconsistent with source trend summary
    11. invalid chronological ordering
    12. no snapshots
    13. one snapshot
    14. multiple snapshots
    15. no comparisons
    16. invalid comparisons
    17. no trend summary
    18. invalid trend summary
    19. zero-evaluation data
    20. partially populated report
    21. deterministic validation output
    22. validator does not mutate the input
    23. invalid report is not automatically repaired
    24. Prompt 513 report generation remains unchanged
    25. regression coverage for Prompts 500-513
    +   fabricated / placeholder values, never raising on junk input

Run directly:
    python -m unittest tests.test_learned_knowledge_diagnostic_report_validation -v
"""

import copy
import hashlib
import inspect
import json
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
    REPORT_STATUS_NO_DATA, REPORT_STATUS_PARTIAL, REPORT_STATUS_VALID, REPORT_STATUS_INVALID,
    TREND_SOURCE_PROVIDED, TREND_SOURCE_DERIVED,
    summarize_learned_knowledge_diagnostic_snapshot_comparison_trend as trend,
    validate_learned_knowledge_diagnostic_snapshot_comparison_trend as validate_trend,
    validate_learned_knowledge_diagnostic_snapshot_comparison as validate_comparison,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
)

RESULT_KEYS = ["valid", "well_formed", "errors", "warnings"]


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
    """(history, comparisons, valid unified report) for a small history."""
    history = _history(counts_list or [{"accepted": 1}, {"accepted": 3}, {"irrelevant": 2}])
    comparisons = _chain(history)
    return history, comparisons, report(snapshots=history, comparisons=comparisons)


def _invalid_status_history_and_comparison():
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record({}, {"valid": False, "errors": ["boom"]})
    history.record_statistics(_stats(accepted=2))
    comparison = history.compare_sequences(1, 2)
    assert validate_comparison(comparison)["valid"] is False
    return history, comparison


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Prompt514TestCase(unittest.TestCase):

    def assertValid(self, result):
        self.assertEqual(list(result.keys()), RESULT_KEYS)
        self.assertEqual(result["errors"], [], result)
        self.assertIs(result["valid"], True)
        self.assertIs(result["well_formed"], True)
        self.assertEqual(result["warnings"], [])

    def assertInvalid(self, result, *codes):
        self.assertEqual(list(result.keys()), RESULT_KEYS)
        self.assertIs(result["valid"], False, result)
        self.assertTrue(result["errors"])
        self.assertEqual(result["warnings"], [])
        for code in codes:
            self.assertIn(code, result["errors"])


# ----------------------------------------------------------------------
# 1. fully valid unified report
# ----------------------------------------------------------------------
class TestFullyValid(Prompt514TestCase):

    def test_fully_populated_report_is_valid(self):
        _, _, built = _pipeline()
        self.assertEqual(built["structural_status"], REPORT_STATUS_VALID)
        self.assertValid(validate(built))

    def test_fully_populated_report_is_valid_against_its_sources(self):
        history, comparisons, built = _pipeline()
        self.assertValid(validate(built, snapshots=history, comparisons=comparisons))

    def test_provided_trend_summary_is_valid_against_sources(self):
        history = _history([{"accepted": 1}, {"accepted": 2}, {"accepted": 6}])
        comparisons = _chain(history)
        summary = trend(comparisons)
        built = report(snapshots=history, comparisons=comparisons, trend_summary=summary)
        self.assertEqual(built["trend"]["source"], TREND_SOURCE_PROVIDED)
        self.assertValid(validate(built))
        self.assertValid(validate(built, snapshots=history, comparisons=comparisons, trend_summary=summary))

    def test_valid_report_result_is_a_plain_new_dict(self):
        _, _, built = _pipeline()
        first, second = validate(built), validate(built)
        self.assertIsNot(first, second)
        self.assertIsNot(first["errors"], second["errors"])

    def test_snapshot_list_source_is_accepted(self):
        history, comparisons, built = _pipeline()
        self.assertValid(validate(built, snapshots=history.get_all(), comparisons=comparisons))


# ----------------------------------------------------------------------
# 2. missing required report section
# ----------------------------------------------------------------------
class TestMissingSection(Prompt514TestCase):

    def test_each_missing_top_level_section_is_reported(self):
        _, _, built = _pipeline()
        for name in ("snapshots", "comparison", "comparison_validation", "trend", "trend_validation"):
            broken = copy.deepcopy(built)
            del broken[name]
            self.assertInvalid(validate(broken), "missing_field:%s" % name)
            self.assertIs(validate(broken)["well_formed"], False)

    def test_each_missing_top_level_scalar_is_reported(self):
        _, _, built = _pipeline()
        for name in ("valid", "errors", "structural_status"):
            broken = copy.deepcopy(built)
            del broken[name]
            self.assertInvalid(validate(broken), "missing_field:%s" % name)

    def test_missing_section_field_is_reported(self):
        _, _, built = _pipeline()
        for section, field in (("snapshots", "latest"), ("snapshots", "count"),
                                ("comparison", "total_considered"), ("comparison", "latest"),
                                ("comparison_validation", "result"), ("trend", "source"),
                                ("trend", "summary"), ("trend_validation", "available")):
            broken = copy.deepcopy(built)
            del broken[section][field]
            self.assertInvalid(validate(broken), "missing_field:%s.%s" % (section, field))

    def test_missing_validation_result_field_is_reported(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        del broken["comparison_validation"]["result"]["errors"]
        self.assertInvalid(validate(broken), "missing_field:comparison_validation.result.errors")

    def test_unexpected_fields_are_reported(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["score"] = 0.9
        broken["snapshots"]["rank"] = 1
        self.assertInvalid(validate(broken), "unexpected_field:score", "unexpected_field:snapshots.rank")


# ----------------------------------------------------------------------
# 3. invalid overall status
# ----------------------------------------------------------------------
class TestOverallStatus(Prompt514TestCase):

    def test_unsupported_status_values(self):
        _, _, built = _pipeline()
        for bad in ("good", "healthy", "VALID", "", "unknown"):
            broken = copy.deepcopy(built)
            broken["structural_status"] = bad
            self.assertInvalid(validate(broken), "unsupported_status_value:structural_status")

    def test_status_of_wrong_type(self):
        _, _, built = _pipeline()
        for bad in (None, 3, True, ["valid"]):
            broken = copy.deepcopy(built)
            broken["structural_status"] = bad
            self.assertInvalid(validate(broken), "invalid_type:structural_status")

    def test_status_that_disagrees_with_the_sections(self):
        history, comparisons, built = _pipeline()
        for wrong in (REPORT_STATUS_NO_DATA, REPORT_STATUS_PARTIAL, REPORT_STATUS_INVALID):
            broken = copy.deepcopy(built)
            broken["structural_status"] = wrong
            self.assertInvalid(validate(broken), "inconsistent_structural_status")

    def test_every_supported_status_validates_when_consistent(self):
        history, comparison = _invalid_status_history_and_comparison()
        cases = {
            REPORT_STATUS_NO_DATA: report(),
            REPORT_STATUS_PARTIAL: report(snapshots=_history([{"accepted": 1}])),
            REPORT_STATUS_VALID: _pipeline()[2],
            REPORT_STATUS_INVALID: report(snapshots=history, comparisons=[comparison]),
        }
        for status, built in cases.items():
            self.assertEqual(built["structural_status"], status)
            self.assertValid(validate(built))

    def test_report_valid_and_errors_fields(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["valid"] = False
        broken["errors"] = ["something"]
        self.assertInvalid(validate(broken), "invalid_report_valid_value", "invalid_report_errors_value")
        broken["valid"], broken["errors"] = "yes", "none"
        self.assertInvalid(validate(broken), "invalid_type:valid", "invalid_type:errors")


# ----------------------------------------------------------------------
# 4. invalid field type
# ----------------------------------------------------------------------
class TestInvalidFieldType(Prompt514TestCase):

    def test_section_of_wrong_type(self):
        _, _, built = _pipeline()
        for name in ("snapshots", "comparison", "comparison_validation", "trend", "trend_validation"):
            for bad in (None, [], "text", 5):
                broken = copy.deepcopy(built)
                broken[name] = bad
                self.assertInvalid(validate(broken), "invalid_type:%s" % name)

    def test_available_flag_of_wrong_type(self):
        _, _, built = _pipeline()
        for name in ("snapshots", "comparison", "comparison_validation", "trend", "trend_validation"):
            broken = copy.deepcopy(built)
            broken[name]["available"] = "yes"
            self.assertInvalid(validate(broken), "invalid_type:%s.available" % name)

    def test_count_fields_of_wrong_type(self):
        _, _, built = _pipeline()
        for section, field in (("snapshots", "count"), ("comparison", "total_considered")):
            for bad in ("3", 2.0, True, None):
                broken = copy.deepcopy(built)
                broken[section][field] = bad
                self.assertInvalid(validate(broken), "invalid_type:%s.%s" % (section, field))

    def test_payload_of_wrong_type(self):
        _, _, built = _pipeline()
        for section, field in (("snapshots", "latest"),
                                ("comparison_validation", "result"), ("trend_validation", "result")):
            broken = copy.deepcopy(built)
            broken[section][field] = ["not", "a", "dict"]
            self.assertInvalid(validate(broken), "invalid_type:%s.%s" % (section, field))

    def test_comparison_and_trend_payloads_of_wrong_type_are_judged_by_their_validators(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison"]["latest"] = ["not", "a", "dict"]
        broken["trend"]["summary"] = "not a summary"
        # the report still says both validated fine, which the existing
        # Prompt 510 / 512 validators contradict
        self.assertInvalid(validate(broken), "claims_valid_but_source_invalid:comparison",
                           "claims_valid_but_source_invalid:trend")

    def test_validation_result_fields_of_wrong_type(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison_validation"]["result"]["valid"] = "true"
        broken["trend_validation"]["result"]["errors"] = "none"
        self.assertInvalid(validate(broken), "invalid_type:comparison_validation.result.valid",
                           "invalid_type:trend_validation.result.errors")

    def test_report_of_wrong_type(self):
        for bad in (None, [], "report", 3, True):
            self.assertInvalid(validate(bad), "report_not_a_dict")
            self.assertIs(validate(bad)["well_formed"], False)

    def test_snapshot_field_of_wrong_type(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["snapshot_id"] = 7
        broken["snapshots"]["latest"]["validation_errors"] = "none"
        self.assertInvalid(validate(broken), "snapshots.latest:invalid_snapshot_id",
                           "snapshots.latest:invalid_validation_errors")


# ----------------------------------------------------------------------
# 5. missing metric
# ----------------------------------------------------------------------
class TestMissingMetric(Prompt514TestCase):

    METRICS = ("total_evaluations", "accepted_count", "rejected_count", "no_candidate_count",
               "acceptance_rate", "rejection_rate", "dominant_rejection_reason")

    def test_each_missing_snapshot_metric_is_reported(self):
        _, _, built = _pipeline()
        for metric in self.METRICS:
            broken = copy.deepcopy(built)
            del broken["snapshots"]["latest"][metric]
            self.assertInvalid(validate(broken), "snapshots.latest:missing_field:%s" % metric)
            self.assertIs(validate(broken)["well_formed"], False)

    def test_missing_metric_in_trend_summary_is_reported(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        del broken["trend"]["summary"]["numeric"]["accepted_count"]
        self.assertInvalid(validate(broken), "claims_valid_but_source_invalid:trend")

    def test_missing_metric_in_comparison_is_reported(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        del broken["comparison"]["latest"]["numeric"]["rejected_count"]
        self.assertInvalid(validate(broken), "claims_valid_but_source_invalid:comparison")


# ----------------------------------------------------------------------
# 6. invalid numeric metric
# ----------------------------------------------------------------------
class TestInvalidNumericMetric(Prompt514TestCase):

    def _with(self, field, value):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"][field] = value
        return validate(broken)

    def test_negative_counts(self):
        for field in ("total_evaluations", "accepted_count", "rejected_count", "no_candidate_count"):
            self.assertInvalid(self._with(field, -1), "snapshots.latest:analysis:negative_count:%s" % field)

    def test_count_of_wrong_type(self):
        for value in ("2", 2.5, True, None):
            self.assertInvalid(self._with("accepted_count", value),
                               "snapshots.latest:analysis:invalid_count_type:accepted_count")

    def test_rate_out_of_range(self):
        self.assertInvalid(self._with("acceptance_rate", 1.5),
                           "snapshots.latest:analysis:rate_above_valid_range:acceptance_rate")
        self.assertInvalid(self._with("rejection_rate", -0.1),
                           "snapshots.latest:analysis:rate_below_valid_range:rejection_rate")

    def test_rate_of_wrong_type_or_not_finite(self):
        self.assertInvalid(self._with("acceptance_rate", "0.5"),
                           "snapshots.latest:analysis:invalid_rate_type:acceptance_rate")
        self.assertInvalid(self._with("acceptance_rate", float("inf")))
        self.assertInvalid(self._with("acceptance_rate", float("nan")))

    def test_unsupported_dominant_reason(self):
        self.assertInvalid(self._with("dominant_rejection_reason", "N/A"),
                           "snapshots.latest:analysis:invalid_dominant_rejection_reason")

    def test_impossible_section_counts(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["snapshots"]["count"] = -4
        broken["comparison"]["total_considered"] = -1
        self.assertInvalid(validate(broken), "negative_value:snapshots.count",
                           "negative_value:comparison.total_considered")
        broken = copy.deepcopy(built)
        broken["snapshots"]["count"] = 0
        self.assertInvalid(validate(broken), "inconsistent_count:snapshots.count")


# ----------------------------------------------------------------------
# 7. metric inconsistent with source data
# ----------------------------------------------------------------------
class TestMetricInconsistency(Prompt514TestCase):

    def test_rate_inconsistent_with_counts(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["acceptance_rate"] = 0.99
        self.assertInvalid(validate(broken), "snapshots.latest:analysis:inconsistent_acceptance_rate")

    def test_counts_exceeding_total(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["total_evaluations"] = 0
        self.assertInvalid(validate(broken), "snapshots.latest:analysis:counts_exceed_total_evaluations")

    def test_snapshot_metric_differs_from_source_snapshot(self):
        history, comparisons, built = _pipeline()
        broken = copy.deepcopy(built)
        latest = broken["snapshots"]["latest"]
        latest["total_evaluations"], latest["rejected_count"] = 4, 1
        latest["rejection_rate"] = 0.25
        result = validate(broken, snapshots=history, comparisons=comparisons)
        self.assertInvalid(result, "source_mismatch:snapshots.latest.total_evaluations")
        # each preserved metric is named individually
        self.assertIn("source_mismatch:snapshots.latest.rejected_count", result["errors"])
        self.assertIn("source_mismatch:snapshots.latest.rejection_rate", result["errors"])

    def test_dominant_reason_differs_from_source(self):
        history, comparisons, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["dominant_rejection_reason"] = None
        self.assertInvalid(validate(broken, snapshots=history),
                           "source_mismatch:snapshots.latest.dominant_rejection_reason")

    def test_comparison_metric_disagrees_with_latest_snapshot(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["accepted_count"] = 1
        broken["snapshots"]["latest"]["total_evaluations"] = 2
        broken["snapshots"]["latest"]["acceptance_rate"] = 0.5
        result = validate(broken)
        self.assertInvalid(result, "metric_mismatch:comparison_vs_snapshots:accepted_count")

    def test_trend_end_disagrees_with_latest_snapshot(self):
        history, comparisons, built = _pipeline()
        broken = copy.deepcopy(built)
        latest = broken["snapshots"]["latest"]
        latest["rejected_count"], latest["total_evaluations"] = 1, 3
        latest["rejection_rate"] = 1 / 3
        self.assertInvalid(validate(broken), "metric_mismatch:trend_vs_snapshots:rejected_count")

    def test_snapshot_count_differs_from_source(self):
        history, comparisons, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["snapshots"]["count"] = 2
        self.assertInvalid(validate(broken, snapshots=history), "source_mismatch:snapshots.count")


# ----------------------------------------------------------------------
# 8. incorrect validation status
# ----------------------------------------------------------------------
class TestValidationStatus(Prompt514TestCase):

    def test_report_claims_comparison_valid_when_source_invalid(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = report(snapshots=history, comparisons=[comparison])
        broken = copy.deepcopy(built)
        broken["comparison_validation"]["result"] = {
            "valid": True, "well_formed": True, "errors": [], "warnings": []}
        broken["structural_status"] = REPORT_STATUS_PARTIAL
        result = validate(broken)
        self.assertInvalid(result, "claims_valid_but_source_invalid:comparison")
        self.assertIs(result["well_formed"], False)

    def test_overall_status_valid_while_a_component_is_invalid(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = report(snapshots=history, comparisons=[comparison])
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        broken = copy.deepcopy(built)
        broken["structural_status"] = REPORT_STATUS_VALID
        self.assertInvalid(validate(broken), "inconsistent_structural_status")

    def test_report_claims_trend_valid_when_source_invalid(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["trend"]["summary"]["numeric"]["accepted_count"]["delta"] = 999
        self.assertInvalid(validate(broken), "claims_valid_but_source_invalid:trend")

    def test_report_claims_comparison_invalid_when_source_valid(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison_validation"]["result"] = {
            "valid": False, "well_formed": False, "errors": ["made_up"], "warnings": []}
        self.assertInvalid(validate(broken), "claims_invalid_but_source_valid:comparison")

    def test_snapshot_claims_valid_while_carrying_errors(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["validation_errors"] = ["boom"]
        self.assertInvalid(validate(broken), "snapshots.latest:valid_snapshot_has_validation_errors")

    def test_snapshot_claims_valid_when_source_snapshot_is_invalid(self):
        history, comparison = _invalid_status_history_and_comparison()
        # the report says the (invalid) first snapshot is valid
        only_invalid = LearnedKnowledgeDiagnosticSnapshotHistory()
        only_invalid.record({}, {"valid": False, "errors": ["boom"]})
        built = report(snapshots=only_invalid)
        self.assertEqual(built["snapshots"]["latest"]["validation_status"], SNAPSHOT_VALIDATION_INVALID)
        self.assertValid(validate(built, snapshots=only_invalid))
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["validation_status"] = SNAPSHOT_VALIDATION_VALID
        result = validate(broken, snapshots=only_invalid)
        self.assertInvalid(result, "claims_valid_but_source_invalid:snapshot",
                           "source_mismatch:snapshots.latest.validation_status")

    def test_unsupported_validation_status_values(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["validation_status"] = "mostly_ok"
        self.assertInvalid(validate(broken), "snapshots.latest:invalid_validation_status")

    def test_contradictory_validation_state(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison_validation"]["result"]["errors"] = ["boom"]        # valid True + errors
        broken["trend_validation"]["result"]["valid"] = False                  # valid False + no errors
        result = validate(broken)
        self.assertInvalid(result,
                           "contradictory_validation_state:comparison_validation.result",
                           "contradictory_validation_state:trend_validation.result")

    def test_well_formed_false_but_valid_true(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["trend_validation"]["result"]["well_formed"] = False
        self.assertInvalid(validate(broken),
                           "contradictory_validation_state:trend_validation.result.well_formed")

    def test_faithfully_reported_invalid_components_are_not_themselves_invalid(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = report(snapshots=history, comparisons=[comparison])
        self.assertFalse(built["comparison_validation"]["result"]["valid"])
        self.assertValid(validate(built))
        self.assertValid(validate(built, snapshots=history, comparisons=[comparison]))


# ----------------------------------------------------------------------
# 9. comparison information inconsistent with source comparison
# ----------------------------------------------------------------------
class TestComparisonConsistency(Prompt514TestCase):

    def test_latest_comparison_differs_from_last_source_comparison(self):
        history, comparisons, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison"]["latest"] = copy.deepcopy(comparisons[0])
        result = validate(broken, snapshots=history, comparisons=comparisons)
        self.assertInvalid(result)
        self.assertTrue(any(e.startswith("source_mismatch:comparison.latest") for e in result["errors"]))

    def test_comparison_field_altered_after_the_fact(self):
        history, comparisons, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison"]["latest"]["numeric"]["accepted_count"]["later"] = 42
        result = validate(broken, comparisons=comparisons)
        self.assertInvalid(result, "source_mismatch:comparison.latest.numeric")
        # the report alone also notices: the embedded validation says valid
        self.assertInvalid(validate(broken), "claims_valid_but_source_invalid:comparison")

    def test_total_considered_differs_from_source(self):
        history, comparisons, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison"]["total_considered"] = 7
        self.assertInvalid(validate(broken, comparisons=comparisons),
                           "source_mismatch:comparison.total_considered")

    def test_comparison_validation_differs_from_source(self):
        history, comparisons, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison_validation"]["result"]["warnings"] = ["invented"]
        result = validate(broken, comparisons=comparisons)
        self.assertInvalid(result, "source_mismatch:comparison_validation.result.warnings")
        self.assertInvalid(validate(broken), "mismatched_validation_result:comparison")

    def test_comparison_availability_disagrees_with_validation_availability(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison_validation"]["available"] = False
        broken["comparison_validation"]["result"] = None
        self.assertInvalid(validate(broken), "inconsistent_availability:comparison_validation")


# ----------------------------------------------------------------------
# 10. trend information inconsistent with source trend summary
# ----------------------------------------------------------------------
class TestTrendConsistency(Prompt514TestCase):

    def test_trend_summary_differs_from_provided_source(self):
        history, comparisons, _ = _pipeline()
        summary = trend(comparisons)
        built = report(snapshots=history, comparisons=comparisons, trend_summary=summary)
        broken = copy.deepcopy(built)
        self.assertEqual(broken["trend"]["summary"]["numeric"]["accepted_count"]["state"], "decreased")
        broken["trend"]["summary"]["numeric"]["accepted_count"]["state"] = "unchanged"
        result = validate(broken, comparisons=comparisons, trend_summary=summary)
        self.assertInvalid(result, "source_mismatch:trend.summary.numeric")

    def test_trend_summary_differs_from_derivation_of_the_comparisons(self):
        history, comparisons, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["trend"]["summary"]["eligible_count"] = 0
        broken["trend"]["summary"]["ineligible_count"] = 2
        result = validate(broken, comparisons=comparisons)
        self.assertInvalid(result, "source_mismatch:trend.summary.eligible_count")

    def test_trend_summary_internally_inconsistent(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["trend"]["summary"]["total_comparisons"] = 50
        self.assertInvalid(validate(broken), "claims_valid_but_source_invalid:trend")

    def test_derived_trend_total_disagrees_with_comparison_count(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison"]["total_considered"] = 5
        self.assertInvalid(validate(broken), "inconsistent_trend_source:total_comparisons")

    def test_trend_validation_result_differs_from_source(self):
        history, comparisons, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["trend_validation"]["result"]["warnings"] = ["invented"]
        self.assertInvalid(validate(broken, comparisons=comparisons),
                           "source_mismatch:trend_validation.result.warnings")
        self.assertInvalid(validate(broken), "mismatched_validation_result:trend")

    def test_trend_source_label_must_be_supported(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["trend"]["source"] = "guessed"
        self.assertInvalid(validate(broken), "unsupported_value:trend.source")
        broken["trend"]["source"] = None
        self.assertInvalid(validate(broken), "unsupported_value:trend.source")

    def test_trend_metrics_disagree_with_latest_comparison(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison"]["latest"]["numeric"]["accepted_count"]["later"] = 42
        result = validate(broken)
        self.assertInvalid(result, "metric_mismatch:trend_vs_comparison:accepted_count")

    def test_provided_trend_that_mismatches_its_comparisons_is_faithfully_reported(self):
        history, comparisons, _ = _pipeline()
        other = trend(_chain(_history([{"accepted": 1}, {"accepted": 50}])))
        built = report(snapshots=history, comparisons=comparisons, trend_summary=other)
        self.assertFalse(built["trend_validation"]["result"]["valid"])
        self.assertTrue(built["trend_validation"]["result"]["well_formed"])
        self.assertValid(validate(built))
        self.assertValid(validate(built, snapshots=history, comparisons=comparisons, trend_summary=other))


# ----------------------------------------------------------------------
# 11. invalid chronological ordering
# ----------------------------------------------------------------------
class TestChronology(Prompt514TestCase):

    def test_comparison_earlier_after_later(self):
        history = _history([{"accepted": 1}, {"accepted": 2}])
        reversed_comparison = history.compare_sequences(2, 1)
        built = report(snapshots=history, comparisons=[reversed_comparison])
        self.assertFalse(reversed_comparison["chronological"])
        self.assertInvalid(validate(built), "invalid_chronological_ordering:comparison.latest")

    def test_trend_range_running_backwards(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        rng = broken["trend"]["summary"]["chronological_range"]
        rng["earlier"], rng["later"] = rng["later"], rng["earlier"]
        self.assertInvalid(validate(broken), "invalid_chronological_ordering:trend.chronological_range")

    def test_comparison_refers_to_a_snapshot_after_the_latest_snapshot(self):
        history, comparisons, _ = _pipeline([{"accepted": 1}, {"accepted": 2}, {"accepted": 3}])
        truncated = history.get_all()[:2]
        built = report(snapshots=truncated, comparisons=comparisons)
        self.assertInvalid(validate(built),
                           "invalid_chronological_ordering:comparison_after_latest_snapshot",
                           "invalid_chronological_ordering:trend_after_latest_snapshot")

    def test_source_snapshots_out_of_order(self):
        history = _history([{"accepted": 1}, {"accepted": 2}, {"accepted": 3}])
        shuffled = history.get_all()
        shuffled[0], shuffled[2] = shuffled[2], shuffled[0]
        built = report(snapshots=shuffled)
        self.assertInvalid(validate(built, snapshots=shuffled),
                           "invalid_chronological_ordering:snapshots")

    def test_source_comparisons_out_of_order(self):
        history = _history([{"accepted": 1}, {"accepted": 2}, {"accepted": 3}, {"accepted": 4}])
        comparisons = _chain(history)
        comparisons.reverse()
        built = report(snapshots=history, comparisons=comparisons)
        self.assertInvalid(validate(built, comparisons=comparisons),
                           "invalid_chronological_ordering:comparisons")

    def test_properly_ordered_history_has_no_chronology_errors(self):
        history, comparisons, built = _pipeline([{"accepted": i} for i in range(1, 6)])
        self.assertValid(validate(built, snapshots=history, comparisons=comparisons))

    def test_latest_snapshot_is_the_last_recorded(self):
        history, comparisons, built = _pipeline()
        self.assertEqual(built["snapshots"]["latest"]["sequence"], len(history))
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"] = history.get_all()[0]
        self.assertInvalid(validate(broken, snapshots=history),
                           "source_mismatch:snapshots.latest.snapshot_id")


# ----------------------------------------------------------------------
# 12-14. snapshot counts
# ----------------------------------------------------------------------
class TestSnapshotCounts(Prompt514TestCase):

    def test_no_snapshots(self):
        built = report()
        self.assertFalse(built["snapshots"]["available"])
        self.assertValid(validate(built))
        self.assertValid(validate(built, snapshots=None))
        self.assertValid(validate(built, snapshots=LearnedKnowledgeDiagnosticSnapshotHistory()))
        self.assertValid(validate(built, snapshots=[]))

    def test_one_snapshot(self):
        history = _history([{"accepted": 2}])
        built = report(snapshots=history)
        self.assertEqual(built["snapshots"]["count"], 1)
        self.assertValid(validate(built))
        self.assertValid(validate(built, snapshots=history))

    def test_multiple_snapshots(self):
        history = _history([{"accepted": 1}, {"irrelevant": 1}, {"low_reliability": 2}, {"accepted": 4}])
        built = report(snapshots=history)
        self.assertEqual(built["snapshots"]["count"], 4)
        self.assertValid(validate(built))
        self.assertValid(validate(built, snapshots=history))

    def test_reporting_a_snapshot_that_does_not_exist(self):
        broken = report()
        broken["snapshots"] = {"available": True, "count": 1, "latest": None}
        self.assertInvalid(validate(broken), "missing_data_marked_available:snapshots.latest")

    def test_source_has_snapshots_but_report_says_none(self):
        history = _history([{"accepted": 1}])
        result = validate(report(), snapshots=history)
        self.assertInvalid(result, "source_mismatch:snapshots.available", "source_mismatch:snapshots.count",
                           "source_mismatch:snapshots.latest")


# ----------------------------------------------------------------------
# 15-16. comparisons
# ----------------------------------------------------------------------
class TestComparisons(Prompt514TestCase):

    def test_no_comparisons(self):
        history = _history([{"accepted": 1}, {"accepted": 2}])
        built = report(snapshots=history)
        self.assertFalse(built["comparison"]["available"])
        self.assertValid(validate(built))
        self.assertValid(validate(built, snapshots=history, comparisons=[]))
        self.assertValid(validate(built, comparisons=None))

    def test_invalid_comparisons_are_faithfully_reported(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = report(snapshots=history, comparisons=[comparison])
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        self.assertValid(validate(built))
        self.assertValid(validate(built, snapshots=history, comparisons=[comparison]))

    def test_malformed_comparison_object_is_faithfully_reported(self):
        history = _history([{"accepted": 1}])
        for bad in ({}, {"valid": True}, "garbage", 7):
            built = report(snapshots=history, comparisons=[bad])
            self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
            self.assertValid(validate(built))

    def test_invalid_comparison_marked_valid_by_a_tampered_report(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = report(snapshots=history, comparisons=[comparison])
        broken = copy.deepcopy(built)
        broken["comparison_validation"]["result"] = {
            "valid": True, "well_formed": True, "errors": [], "warnings": []}
        self.assertInvalid(validate(broken), "claims_valid_but_source_invalid:comparison")
        self.assertInvalid(validate(broken, comparisons=[comparison]),
                           "claims_valid_but_source_invalid:comparison",
                           "source_mismatch:comparison_validation.result.valid")

    def test_source_has_comparisons_but_report_says_none(self):
        history, comparisons, _ = _pipeline()
        result = validate(report(snapshots=history), comparisons=comparisons)
        self.assertInvalid(result, "source_mismatch:comparison.available",
                           "source_mismatch:comparison.total_considered")

    def test_missing_trend_for_available_comparison(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["trend"] = {"available": False, "source": None, "summary": None}
        broken["trend_validation"] = {"available": False, "result": None}
        self.assertInvalid(validate(broken), "missing_trend_for_available_comparison")


# ----------------------------------------------------------------------
# 17-18. trend summary
# ----------------------------------------------------------------------
class TestTrendSummary(Prompt514TestCase):

    def test_no_trend_summary(self):
        history = _history([{"accepted": 1}])
        built = report(snapshots=history)
        self.assertFalse(built["trend"]["available"])
        self.assertIsNone(built["trend"]["source"])
        self.assertValid(validate(built))
        self.assertValid(validate(built, snapshots=history, comparisons=[], trend_summary=None))

    def test_invalid_trend_summary_is_faithfully_reported(self):
        bad_summary = {"valid": True, "errors": []}
        built = report(trend_summary=bad_summary)
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        self.assertValid(validate(built))
        self.assertValid(validate(built, trend_summary=bad_summary))

    def test_non_dict_trend_summary_is_faithfully_reported(self):
        built = report(trend_summary="not a summary")
        self.assertEqual(built["structural_status"], REPORT_STATUS_INVALID)
        self.assertValid(validate(built))

    def test_invalid_trend_marked_valid_by_a_tampered_report(self):
        bad_summary = {"valid": True, "errors": []}
        built = report(trend_summary=bad_summary)
        broken = copy.deepcopy(built)
        broken["trend_validation"]["result"] = {
            "valid": True, "well_formed": True, "errors": [], "warnings": []}
        self.assertInvalid(validate(broken), "claims_valid_but_source_invalid:trend")

    def test_trend_summary_only_report(self):
        comparisons = _chain(_history([{"accepted": 1}, {"accepted": 3}]))
        summary = trend(comparisons)
        built = report(trend_summary=summary)
        self.assertEqual(built["structural_status"], REPORT_STATUS_PARTIAL)
        self.assertValid(validate(built))
        self.assertValid(validate(built, trend_summary=summary))

    def test_derived_trend_without_comparisons_is_contradictory(self):
        comparisons = _chain(_history([{"accepted": 1}, {"accepted": 3}]))
        built = report(comparisons=comparisons)
        self.assertEqual(built["trend"]["source"], TREND_SOURCE_DERIVED)
        broken = copy.deepcopy(built)
        broken["comparison"] = {"available": False, "total_considered": 0, "latest": None}
        broken["comparison_validation"] = {"available": False, "result": None}
        self.assertInvalid(validate(broken), "derived_trend_without_comparisons")

    def test_trend_source_label_is_checked_against_the_given_sources(self):
        history, comparisons, built = _pipeline()          # built with no trend_summary -> "derived"
        summary = trend(comparisons)
        self.assertEqual(built["trend"]["source"], TREND_SOURCE_DERIVED)
        self.assertInvalid(validate(built, comparisons=comparisons, trend_summary=summary),
                           "source_mismatch:trend.source")

    def test_provided_summary_validates_against_comparisons_alone(self):
        history, comparisons, _ = _pipeline()
        built = report(snapshots=history, comparisons=comparisons, trend_summary=trend(comparisons))
        self.assertEqual(built["trend"]["source"], TREND_SOURCE_PROVIDED)
        self.assertValid(validate(built, comparisons=comparisons))


# ----------------------------------------------------------------------
# 19. zero-evaluation data
# ----------------------------------------------------------------------
class TestZeroEvaluationData(Prompt514TestCase):

    def test_zero_evaluation_snapshot(self):
        history = _history([{}])
        built = report(snapshots=history)
        self.assertEqual(built["snapshots"]["latest"]["total_evaluations"], 0)
        self.assertValid(validate(built))
        self.assertValid(validate(built, snapshots=history))

    def test_zero_to_zero_comparison_and_trend(self):
        history = _history([{}, {}])
        comparisons = _chain(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(built["structural_status"], REPORT_STATUS_VALID)
        self.assertValid(validate(built))
        self.assertValid(validate(built, snapshots=history, comparisons=comparisons))

    def test_zero_evaluations_with_impossible_counts(self):
        built = report(snapshots=_history([{}]))
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["accepted_count"] = 1
        self.assertInvalid(validate(broken), "snapshots.latest:analysis:counts_exceed_total_evaluations")

    def test_zero_evaluations_with_a_nonzero_rate(self):
        built = report(snapshots=_history([{}]))
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["acceptance_rate"] = 0.5
        self.assertInvalid(validate(broken), "snapshots.latest:analysis:inconsistent_acceptance_rate")

    def test_zero_evaluations_with_a_fabricated_dominant_reason(self):
        built = report(snapshots=_history([{}]))
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["dominant_rejection_reason"] = "unknown"
        self.assertInvalid(validate(broken), "snapshots.latest:analysis:invalid_dominant_rejection_reason")


# ----------------------------------------------------------------------
# 20. partially populated reports
# ----------------------------------------------------------------------
class TestPartialReports(Prompt514TestCase):

    def test_snapshots_only(self):
        history = _history([{"accepted": 1}, {"accepted": 2}])
        built = report(snapshots=history)
        self.assertEqual(built["structural_status"], REPORT_STATUS_PARTIAL)
        self.assertValid(validate(built))

    def test_comparisons_only(self):
        comparisons = _chain(_history([{"accepted": 1}, {"accepted": 2}, {"accepted": 3}]))
        built = report(comparisons=comparisons)
        self.assertEqual(built["structural_status"], REPORT_STATUS_PARTIAL)
        self.assertValid(validate(built))
        self.assertValid(validate(built, comparisons=comparisons))

    def test_empty_report_from_the_builder(self):
        built = report()
        self.assertEqual(built["structural_status"], REPORT_STATUS_NO_DATA)
        self.assertValid(validate(built))

    def test_empty_dict_is_an_invalid_report(self):
        result = validate({})
        self.assertInvalid(result, "missing_field:valid", "missing_field:snapshots", "missing_field:trend_validation")
        self.assertIs(result["well_formed"], False)

    def test_partially_populated_report_that_is_missing_fields(self):
        result = validate({"valid": True, "errors": [], "structural_status": "no_data",
                           "snapshots": {"available": False}})
        self.assertInvalid(result, "missing_field:snapshots.count", "missing_field:snapshots.latest",
                           "missing_field:comparison", "missing_field:trend_validation")


# ----------------------------------------------------------------------
# fabricated / placeholder replacement values
# ----------------------------------------------------------------------
class TestFabricatedValues(Prompt514TestCase):

    def test_unavailable_components_hold_none_not_placeholders(self):
        built = report()
        for section, field, placeholder in (
                ("snapshots", "latest", {}), ("snapshots", "latest", {"accepted_count": 0}),
                ("comparison", "latest", {}), ("trend", "summary", {}),
                ("comparison_validation", "result", {"valid": True}),
                ("trend_validation", "result", {"valid": True})):
            broken = copy.deepcopy(built)
            broken[section][field] = placeholder
            self.assertInvalid(validate(broken),
                               "fabricated_value_for_unavailable_component:%s.%s" % (section, field))

    def test_unavailable_counts_and_source_are_not_filled_in(self):
        built = report()
        broken = copy.deepcopy(built)
        broken["snapshots"]["count"] = 3
        broken["comparison"]["total_considered"] = 2
        broken["trend"]["source"] = "derived"
        self.assertInvalid(validate(broken),
                           "fabricated_value_for_unavailable_component:snapshots.count",
                           "fabricated_value_for_unavailable_component:comparison.total_considered",
                           "fabricated_value_for_unavailable_component:trend.source")

    def test_available_snapshot_is_not_an_empty_placeholder(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"] = {}
        self.assertInvalid(validate(broken), "fabricated_placeholder_value:snapshots.latest",
                           "snapshots.latest:missing_field:accepted_count")

    def test_available_comparison_and_trend_placeholders_contradict_their_validators(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["comparison"]["latest"] = {}
        broken["trend"]["summary"] = {}
        self.assertInvalid(validate(broken), "claims_valid_but_source_invalid:comparison",
                           "claims_valid_but_source_invalid:trend")

    def test_invalid_snapshot_carries_no_invented_analysis_values(self):
        only_invalid = LearnedKnowledgeDiagnosticSnapshotHistory()
        only_invalid.record({}, {"valid": False, "errors": ["boom"]})
        built = report(snapshots=only_invalid)
        self.assertValid(validate(built))
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["total_evaluations"] = 0
        broken["snapshots"]["latest"]["acceptance_rate"] = 0.0
        self.assertInvalid(validate(broken),
                           "snapshots.latest:invalid_snapshot_has_analysis_field:total_evaluations",
                           "snapshots.latest:invalid_snapshot_has_analysis_field:acceptance_rate")

    def test_unavailable_marked_available_without_data(self):
        built = report()
        broken = copy.deepcopy(built)
        broken["comparison"]["available"] = True
        broken["trend"]["available"] = True
        result = validate(broken)
        self.assertInvalid(result, "missing_data_marked_available:comparison.latest",
                           "missing_data_marked_available:trend.summary", "unsupported_value:trend.source")


# ----------------------------------------------------------------------
# 21. deterministic validation output
# ----------------------------------------------------------------------
class TestDeterministic(Prompt514TestCase):

    def test_same_input_same_output(self):
        history, comparisons, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["structural_status"] = "bogus"
        broken["snapshots"]["latest"]["accepted_count"] = -1
        del broken["comparison_validation"]
        first = validate(broken, snapshots=history, comparisons=comparisons)
        for _ in range(5):
            self.assertEqual(validate(broken, snapshots=history, comparisons=comparisons), first)
        self.assertEqual(_digest(first), _digest(validate(copy.deepcopy(broken), snapshots=history,
                                                           comparisons=comparisons)))

    def test_error_order_is_fixed_and_has_no_duplicates(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["structural_status"] = "bogus"
        del broken["trend"]
        del broken["snapshots"]["latest"]["accepted_count"]
        result = validate(broken)
        self.assertEqual(len(result["errors"]), len(set(result["errors"])))
        self.assertEqual(result["errors"], validate(broken)["errors"])
        # structural codes come in the fixed check order: top-level fields
        # and sections first, then the per-component checks
        self.assertEqual(result["errors"][0], "unsupported_status_value:structural_status")
        self.assertLess(result["errors"].index("missing_field:trend"),
                        result["errors"].index("snapshots.latest:missing_field:accepted_count"))

    def test_valid_reports_validate_the_same_every_time(self):
        _, _, built = _pipeline()
        self.assertEqual([validate(built) for _ in range(3)], [validate(built)] * 3)


# ----------------------------------------------------------------------
# 22. validator does not mutate the input
# ----------------------------------------------------------------------
class TestNoMutation(Prompt514TestCase):

    def test_valid_report_and_sources_untouched(self):
        history, comparisons, built = _pipeline()
        summary = trend(comparisons)
        before = (copy.deepcopy(built), history.get_all(), copy.deepcopy(comparisons), copy.deepcopy(summary))
        validate(built, snapshots=history, comparisons=comparisons, trend_summary=summary)
        after = (built, history.get_all(), comparisons, summary)
        self.assertEqual(before, after)

    def test_invalid_report_and_sources_untouched(self):
        history, comparisons, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["snapshots"]["latest"]["accepted_count"] = -5
        broken["trend"]["summary"]["numeric"]["total_evaluations"]["delta"] = 1000
        broken["comparison_validation"]["result"]["errors"] = ["x"]
        snapshot_copy = copy.deepcopy(broken)
        history_before, comparisons_before = history.get_all(), copy.deepcopy(comparisons)
        validate(broken, snapshots=history, comparisons=comparisons)
        self.assertEqual(broken, snapshot_copy)
        self.assertEqual(history.get_all(), history_before)
        self.assertEqual(comparisons, comparisons_before)

    def test_history_length_and_sequence_numbers_unchanged(self):
        history, comparisons, built = _pipeline()
        validate(built, snapshots=history, comparisons=comparisons)
        self.assertEqual(len(history), 3)
        self.assertEqual(history.record_statistics(_stats(accepted=1))["sequence"], 4)

    def test_result_does_not_alias_the_report(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = report(snapshots=history, comparisons=[comparison])
        result = validate(built)
        result["errors"].append("tamper")
        self.assertEqual(validate(built)["errors"], [])
        self.assertEqual(built["errors"], [])

    def test_report_with_shared_sections_is_not_modified(self):
        history, comparisons, built = _pipeline()
        broken = dict(built)               # shallow copy shares every section with `built`
        broken["structural_status"] = "bogus"
        before = copy.deepcopy(built)
        validate(broken)
        self.assertEqual(built, before)


# ----------------------------------------------------------------------
# 23. invalid report is not automatically repaired
# ----------------------------------------------------------------------
class TestNoRepair(Prompt514TestCase):

    def test_invalid_report_is_left_exactly_as_given(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        broken["structural_status"] = "bogus"
        broken["snapshots"]["latest"]["acceptance_rate"] = 7
        del broken["trend_validation"]
        expected = copy.deepcopy(broken)
        first = validate(broken)
        self.assertFalse(first["valid"])
        self.assertEqual(broken, expected)
        self.assertNotIn("trend_validation", broken)
        self.assertEqual(broken["structural_status"], "bogus")
        self.assertEqual(validate(broken), first)         # still invalid the second time

    def test_result_carries_no_repaired_report(self):
        _, _, built = _pipeline()
        broken = copy.deepcopy(built)
        del broken["comparison"]
        result = validate(broken)
        self.assertEqual(set(result), set(RESULT_KEYS))

    def test_validator_never_calls_the_builder_without_sources(self):
        calls = []
        from learning import learned_knowledge_statistics as module
        original = module.build_learned_knowledge_diagnostic_report

        def spy(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        module.build_learned_knowledge_diagnostic_report = spy
        try:
            _, _, built = _pipeline()
            calls.clear()
            validate(built)
            self.assertEqual(calls, [])
        finally:
            module.build_learned_knowledge_diagnostic_report = original


# ----------------------------------------------------------------------
# never raises on junk input
# ----------------------------------------------------------------------
class TestJunkInput(Prompt514TestCase):

    JUNK = (None, 0, -1, 1.5, float("nan"), "", "x", True, [], [1], {}, {"a": 1}, object)

    def test_replacing_any_field_with_junk_never_raises(self):
        _, _, built = _pipeline()
        paths = []

        def walk(node, path):
            if isinstance(node, dict):
                for key, value in node.items():
                    paths.append(path + (key,))
                    walk(value, path + (key,))

        walk(built, ())
        for path in paths:
            for junk in self.JUNK:
                broken = copy.deepcopy(built)
                target = broken
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = junk
                result = validate(broken)
                self.assertEqual(list(result.keys()), RESULT_KEYS)
                self.assertIsInstance(result["valid"], bool)
                self.assertEqual(result["valid"], not result["errors"])

    def test_junk_sources_never_raise(self):
        _, _, built = _pipeline()
        for junk in (7, "text", {"a": 1}, object()):
            for kwargs in ({"snapshots": junk}, {"comparisons": junk}, {"trend_summary": junk}):
                result = validate(built, **kwargs)
                self.assertEqual(list(result.keys()), RESULT_KEYS)

    def test_junk_source_is_reported(self):
        _, _, built = _pipeline()
        self.assertInvalid(validate(built, comparisons=7), "invalid_source:comparisons")
        self.assertInvalid(validate(built, snapshots="text"), "invalid_source:snapshots")


# ----------------------------------------------------------------------
# 24. Prompt 513 report generation remains unchanged
# ----------------------------------------------------------------------
class TestPrompt513Unchanged(Prompt514TestCase):
    # Digests of the Prompt 513 output for fixed inputs, computed from the
    # unmodified Prompt 513 code before Prompt 514 was written.

    def _cases(self):
        one = _history([{"accepted": 1}])
        three = _history([{"accepted": 1}, {"accepted": 3}, {"irrelevant": 2}])
        comparisons = _chain(three)
        invalid_history, invalid_comparison = _invalid_status_history_and_comparison()
        return {
            "no_data": report(),
            "one_snapshot": report(snapshots=one),
            "full": report(snapshots=three, comparisons=comparisons),
            "invalid_comparison": report(snapshots=invalid_history, comparisons=[invalid_comparison]),
            "provided_trend": report(comparisons=comparisons, trend_summary=trend(comparisons)),
        }

    GOLDEN = {
        "no_data": "763c02bc53c98f23371efcf03dcf5b2325d7932042f2332a0e24b54a15c30b09",
        "one_snapshot": "d6d24db2427e3ce826cf6c343f6fa15e4ab9cf669f3be19bbfe51b0693168894",
        "full": "9d69146551ff814cc779e1c889960e20e74e5fe54d4bf2fe58d42e6f1f8e378f",
        "invalid_comparison": "e94144303dd9bc6bc7e52a00ba6e7d1a28817001bee067e4fc3381a9ceb7c186",
        "provided_trend": "1d184bb7fa447e045e4865e0f23e5bdd508f1d1c50098c07bba710b8aea13891",
    }

    def test_report_output_is_byte_for_byte_what_prompt_513_produced(self):
        for name, built in self._cases().items():
            self.assertEqual(_digest(built), self.GOLDEN[name], name)

    def test_report_keys_and_shape_unchanged(self):
        built = report()
        self.assertEqual(list(built.keys()), [
            "valid", "errors", "structural_status", "snapshots", "comparison",
            "comparison_validation", "trend", "trend_validation"])
        self.assertIs(built["valid"], True)
        self.assertEqual(built["errors"], [])

    def test_report_generation_does_not_call_the_new_validator(self):
        from learning import learned_knowledge_statistics as module
        source = inspect.getsource(module.build_learned_knowledge_diagnostic_report)
        for helper in (module._report_snapshots_section, module._report_comparison_sections,
                       module._report_trend_sections, module._report_structural_status):
            source += inspect.getsource(helper)
        self.assertNotIn("validate_learned_knowledge_diagnostic_report", source)

    def test_every_report_the_builder_makes_validates(self):
        history, comparison = _invalid_status_history_and_comparison()
        for built in list(self._cases().values()) + [report(snapshots=history, comparisons=[comparison])]:
            self.assertValid(validate(built))


# ----------------------------------------------------------------------
# validator does not influence normal AI behavior
# ----------------------------------------------------------------------
class TestNoBehaviorChange(Prompt514TestCase):

    def test_not_referenced_from_the_gate_module(self):
        from learning import learned_knowledge_gate
        source = inspect.getsource(learned_knowledge_gate)
        self.assertNotIn("validate_learned_knowledge_diagnostic_report", source)

    def test_not_referenced_from_earlier_validators_or_summarizers(self):
        from learning import learned_knowledge_statistics as module
        for function in (
                module.validate_learned_knowledge_statistics_analysis,
                module.validate_learned_knowledge_diagnostic_snapshot_comparison,
                module.validate_learned_knowledge_diagnostic_snapshot_comparison_trend,
                module.summarize_learned_knowledge_diagnostic_snapshot_comparison_trend,
                module.compare_learned_knowledge_diagnostic_snapshots):
            self.assertNotIn("validate_learned_knowledge_diagnostic_report", inspect.getsource(function))

    def test_gate_still_evaluates_normally(self):
        from learning.learned_knowledge_gate import evaluate_learned_knowledge_gate, REASON_NOT_SELECTED
        result = evaluate_learned_knowledge_gate(selection=None)
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.reason, REASON_NOT_SELECTED)

    def test_validation_result_has_no_score_rank_or_recommendation(self):
        _, _, built = _pipeline()
        result = validate(built)
        self.assertEqual(set(result), set(RESULT_KEYS))
        blob = json.dumps(result).lower()
        for word in ("score", "rank", "recommend", "grade"):
            self.assertNotIn(word, blob)


# ----------------------------------------------------------------------
# 25. regression coverage for Prompts 500-513
# ----------------------------------------------------------------------
class TestRegressionPrompts500Through513(Prompt514TestCase):

    def test_full_chain_still_works_end_to_end(self):
        history = _history([{"accepted": 1}, {"irrelevant": 2}, {"accepted": 4}])
        comparisons = _chain(history)
        for comparison in comparisons:
            self.assertTrue(validate_comparison(comparison)["valid"])
        summary = trend(comparisons)
        self.assertTrue(validate_trend(summary, comparisons=comparisons)["valid"])
        built = report(snapshots=history, comparisons=comparisons, trend_summary=summary)
        self.assertEqual(built["structural_status"], REPORT_STATUS_VALID)
        self.assertValid(validate(built, snapshots=history, comparisons=comparisons, trend_summary=summary))

    def test_prompt_510_and_512_validator_outputs_unchanged(self):
        history = _history([{"accepted": 1}, {"accepted": 2}])
        comparisons = _chain(history)
        self.assertEqual(validate_comparison(comparisons[0]),
                         {"valid": True, "well_formed": True, "errors": [], "warnings": []})
        self.assertEqual(validate_trend(trend(comparisons), comparisons=comparisons),
                         {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_dominant_rejection_reason_flows_through_every_layer(self):
        history = _history([{"accepted": 1}, {"irrelevant": 2}])
        comparisons = _chain(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(built["snapshots"]["latest"]["dominant_rejection_reason"],
                         DECISION_REJECTED_IRRELEVANT)
        self.assertEqual(built["trend"]["summary"]["dominant_rejection_reason"]["end"],
                         DECISION_REJECTED_IRRELEVANT)
        self.assertValid(validate(built, snapshots=history, comparisons=comparisons))

    def test_snapshot_history_still_bounded_and_unmodified_by_validation(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory(max_snapshots=2)
        for count in (1, 2, 3):
            history.record_statistics(_stats(accepted=count))
        built = report(snapshots=history, comparisons=_chain(history))
        self.assertEqual([s["sequence"] for s in history.get_all()], [2, 3])
        self.assertValid(validate(built, snapshots=history, comparisons=_chain(history)))
        self.assertEqual([s["sequence"] for s in history.get_all()], [2, 3])


if __name__ == "__main__":
    unittest.main()
