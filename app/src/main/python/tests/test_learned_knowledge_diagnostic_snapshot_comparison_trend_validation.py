"""
Tests for Prompt 512 - Validate Diagnostic Trend Summaries.

`validate_learned_knowledge_diagnostic_snapshot_comparison_trend()`
(learning/learned_knowledge_statistics.py) is a deterministic, read-only
validator over the dict `summarize_learned_knowledge_diagnostic_
snapshot_comparison_trend()` (Prompt 511) returns. It follows the same
`{"valid", "well_formed", "errors", "warnings"}` shape as the Prompt 506
and Prompt 510 validators: `well_formed` means internally consistent on
its own; `valid` also means it matches its declared source comparisons,
when those are given. It never repairs a trend summary, never mutates
anything it is given, and assigns no score/rank/quality judgement.

Covers:
    1.  fully valid trend summary
    2.  missing required field
    3.  invalid numeric trend state
    4.  invalid categorical trend state
    5.  unknown trend state
    6.  invalid chronological ordering
    7.  inconsistent comparison count
    8.  inconsistent valid/invalid comparison count
    9.  inconsistent derived numeric information
    10. empty trend summary
    11. one-comparison trend summary
    12. multi-comparison trend summary
    13. zero-evaluation data
    14. missing optional categorical value
    15. mixed valid and invalid source comparisons
    16. deterministic validation output
    17. validator does not mutate the input
    18. invalid trend summary is not automatically repaired
    19. Prompt 511 behavior remains unchanged
    20. regression coverage for Prompts 500-511

Run directly:
    python -m unittest tests.test_learned_knowledge_diagnostic_snapshot_comparison_trend_validation -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_gate import (
    STATUS_PASSED, REASON_OK, REASON_NOT_SELECTED, REASON_NOT_RELEVANT,
    REASON_INSUFFICIENT_RELIABILITY,
    DECISION_REJECTED_IRRELEVANT,
    LearnedKnowledgeGateResult, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    SNAPSHOT_VALIDATION_VALID, SNAPSHOT_VALIDATION_INVALID,
    COMPARISON_DIRECTION,
    CHANGE_UNCHANGED, CHANGE_CHANGED, CHANGE_BECAME_AVAILABLE,
    TREND_INCREASED, TREND_DECREASED, TREND_INSUFFICIENT_DATA,
    summarize_learned_knowledge_diagnostic_snapshot_comparison_trend as trend,
    validate_learned_knowledge_diagnostic_snapshot_comparison_trend as validate_trend,
    validate_learned_knowledge_diagnostic_snapshot_comparison as validate_comparison,
)

NUMERIC_FIELDS = ["total_evaluations", "accepted_count", "rejected_count",
                  "no_candidate_count", "acceptance_rate", "rejection_rate"]


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


def _chain(counts_list):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for counts in counts_list:
        history.record_statistics(_stats(**counts))
    return [history.compare_sequences(i, i + 1) for i in range(1, len(counts_list))]


def _pair(earlier_counts, later_counts):
    return _chain([earlier_counts, later_counts])[0]


def _invalid_status_comparison():
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record({}, {"valid": False, "errors": ["boom"]})
    history.record_statistics(_stats(accepted=2))
    comparison = history.compare_sequences(1, 2)
    assert validate_comparison(comparison)["valid"] is False
    return comparison


class Prompt512TestCase(unittest.TestCase):

    def assertFullyValid(self, result):
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def assertInvalid(self, result, expected_error=None):
        self.assertFalse(result["valid"])
        self.assertIsInstance(result["errors"], list)
        self.assertTrue(result["errors"])
        if expected_error is not None:
            self.assertIn(expected_error, result["errors"])


# ----------------------------------------------------------------------
# 1. fully valid trend summary
# ----------------------------------------------------------------------
class TestFullyValid(Prompt512TestCase):

    def test_multi_comparison_summary_is_fully_valid(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 3}, {"accepted": 9}])
        self.assertFullyValid(validate_trend(trend(comparisons)))

    def test_fully_valid_with_source_cross_check(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 3}])
        result = trend(comparisons)
        self.assertFullyValid(validate_trend(result, comparisons=comparisons))


# ----------------------------------------------------------------------
# 2. missing required field
# ----------------------------------------------------------------------
class TestMissingField(Prompt512TestCase):

    def test_missing_top_level_field(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 2}]))
        del result["eligible_count"]
        self.assertInvalid(validate_trend(result), "missing_field:eligible_count")

    def test_missing_numeric_entry_field(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 2}]))
        del result["numeric"]["accepted_count"]["delta"]
        self.assertInvalid(validate_trend(result), "invalid_numeric_trend_entry:accepted_count")

    def test_missing_numeric_field_entirely(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 2}]))
        del result["numeric"]["accepted_count"]
        self.assertInvalid(validate_trend(result), "missing_numeric_trend_field:accepted_count")

    def test_non_dict_trend_summary(self):
        for bad in (None, "not a trend", 42, []):
            self.assertInvalid(validate_trend(bad), "trend_summary_not_a_dict")


# ----------------------------------------------------------------------
# 3. invalid numeric trend state
# ----------------------------------------------------------------------
class TestInvalidNumericState(Prompt512TestCase):

    def test_state_does_not_match_start_end(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 5}]))
        result["numeric"]["accepted_count"]["state"] = TREND_DECREASED
        self.assertInvalid(validate_trend(result), "inconsistent_numeric_trend_state:accepted_count")

    def test_incorrect_delta(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 5}]))
        result["numeric"]["accepted_count"]["delta"] = 999
        self.assertInvalid(validate_trend(result), "incorrect_trend_delta:numeric.accepted_count")

    def test_wrong_value_type(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 5}]))
        result["numeric"]["accepted_count"]["start"] = "one"
        self.assertInvalid(validate_trend(result), "invalid_value_type:numeric.accepted_count.start")

    def test_insufficient_data_state_with_non_none_values(self):
        result = trend([_invalid_status_comparison()])
        result["numeric"]["accepted_count"]["start"] = 0
        self.assertInvalid(validate_trend(result), "invalid_insufficient_data_values:numeric.accepted_count")


# ----------------------------------------------------------------------
# 4. invalid categorical trend state
# ----------------------------------------------------------------------
class TestInvalidCategoricalState(Prompt512TestCase):

    def test_dominant_rejection_reason_state_does_not_match(self):
        result = trend([_pair({"irrelevant": 2}, {"low_reliability": 2})])
        result["dominant_rejection_reason"]["state"] = CHANGE_UNCHANGED
        self.assertInvalid(validate_trend(result), "inconsistent_dominant_rejection_reason_trend_state")

    def test_validation_status_state_does_not_match(self):
        comparisons = [_invalid_status_comparison()] + _chain([{"accepted": 1}, {"accepted": 2}])
        result = trend(comparisons)
        result["validation_status"]["state"] = CHANGE_UNCHANGED
        self.assertInvalid(validate_trend(result), "inconsistent_validation_status_trend_state")

    def test_invalid_value_for_field(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 2}]))
        result["validation_status"]["start"] = "sideways"
        self.assertInvalid(validate_trend(result), "invalid_trend_value:validation_status.start")


# ----------------------------------------------------------------------
# 5. unknown trend state
# ----------------------------------------------------------------------
class TestUnknownTrendState(Prompt512TestCase):

    def test_unknown_numeric_state(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 2}]))
        result["numeric"]["accepted_count"]["state"] = "skyrocketed"
        self.assertInvalid(validate_trend(result), "unknown_numeric_trend_state:accepted_count")

    def test_numeric_state_used_on_categorical_field(self):
        result = trend([_pair({"accepted": 1}, {"irrelevant": 2})])
        result["dominant_rejection_reason"]["state"] = TREND_INCREASED
        self.assertInvalid(validate_trend(result), "unknown_categorical_trend_state:dominant_rejection_reason")

    def test_appear_disappear_state_not_allowed_on_validation_status(self):
        # "became_available" is a legitimate categorical state in general,
        # but not one validation_status can ever legitimately report.
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}])
        result = trend(comparisons)
        result["validation_status"]["state"] = CHANGE_BECAME_AVAILABLE
        self.assertInvalid(validate_trend(result), "unknown_categorical_trend_state:validation_status")


# ----------------------------------------------------------------------
# 6. invalid chronological ordering
# ----------------------------------------------------------------------
class TestInvalidChronologicalOrdering(Prompt512TestCase):

    def test_ineligible_indices_out_of_order(self):
        good = _chain([{"accepted": 1}, {"accepted": 2}])[0]
        bad = _invalid_status_comparison()
        result = trend([bad, good, bad])
        result["ineligible_comparisons"] = list(reversed(result["ineligible_comparisons"]))
        self.assertInvalid(validate_trend(result), "invalid_ineligible_comparison_ordering")

    def test_duplicate_ineligible_index(self):
        bad = _invalid_status_comparison()
        result = trend([bad, bad])
        result["ineligible_comparisons"][1]["index"] = 0
        self.assertInvalid(validate_trend(result), "duplicate_ineligible_comparison_index")

    def test_chronological_range_missing_when_eligible(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 2}]))
        result["chronological_range"]["earlier"] = None
        self.assertInvalid(validate_trend(result), "invalid_chronological_range_identity:earlier")

    def test_chronological_range_present_when_nothing_eligible(self):
        result = trend([_invalid_status_comparison()])
        result["chronological_range"]["earlier"] = {"snapshot_id": "x", "sequence": 1}
        self.assertInvalid(validate_trend(result), "inconsistent_chronological_range")


# ----------------------------------------------------------------------
# 7/8. inconsistent comparison / valid-invalid counts
# ----------------------------------------------------------------------
class TestInconsistentCounts(Prompt512TestCase):

    def test_counts_do_not_add_up(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 2}, {"accepted": 3}]))
        result["eligible_count"] = 99
        self.assertInvalid(validate_trend(result), "inconsistent_comparison_counts")

    def test_ineligible_count_does_not_match_list_length(self):
        good = _chain([{"accepted": 1}, {"accepted": 2}])[0]
        bad = _invalid_status_comparison()
        result = trend([bad, good])
        result["ineligible_count"] = 0
        self.assertInvalid(validate_trend(result), "inconsistent_ineligible_count")

    def test_index_out_of_range(self):
        bad = _invalid_status_comparison()
        result = trend([bad])
        result["ineligible_comparisons"][0]["index"] = 5
        self.assertInvalid(validate_trend(result), "invalid_ineligible_comparison_index")


# ----------------------------------------------------------------------
# 9. inconsistent derived numeric information (source cross-check)
# ----------------------------------------------------------------------
class TestInconsistentWithSource(Prompt512TestCase):

    def test_numeric_end_does_not_match_source(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 5}])
        result = trend(comparisons)
        result["numeric"]["accepted_count"]["end"] = 999
        result["numeric"]["accepted_count"]["delta"] = 998
        outcome = validate_trend(result, comparisons=comparisons)
        self.assertFalse(outcome["valid"])
        self.assertTrue(outcome["well_formed"])  # internally consistent, just wrong vs. source
        self.assertIn("mismatched_numeric:accepted_count", outcome["errors"])

    def test_eligible_count_does_not_match_source(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}, {"accepted": 3}])
        result = trend(comparisons)
        tampered = copy.deepcopy(result)
        tampered["eligible_count"] = 1
        tampered["ineligible_count"] = 2
        outcome = validate_trend(tampered, comparisons=comparisons)
        self.assertFalse(outcome["valid"])
        self.assertIn("mismatched_field:eligible_count", outcome["errors"])

    def test_without_comparisons_no_cross_check_is_attempted(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 5}])
        result = trend(comparisons)
        result["numeric"]["accepted_count"]["end"] = 999
        result["numeric"]["accepted_count"]["delta"] = 998
        # internally self-consistent (end - start == delta, state matches),
        # so without the source it is reported as fully valid
        self.assertFullyValid(validate_trend(result))


# ----------------------------------------------------------------------
# 10/11/12. empty / one-comparison / multi-comparison summaries
# ----------------------------------------------------------------------
class TestSizeVariants(Prompt512TestCase):

    def test_empty_trend_summary(self):
        self.assertFullyValid(validate_trend(trend([])))
        self.assertFullyValid(validate_trend(trend(None)))

    def test_one_comparison_trend_summary(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 4}])
        self.assertFullyValid(validate_trend(trend(comparisons), comparisons=comparisons))

    def test_multi_comparison_trend_summary(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}, {"accepted": 5}, {"accepted": 9}])
        self.assertFullyValid(validate_trend(trend(comparisons), comparisons=comparisons))


# ----------------------------------------------------------------------
# 13. zero-evaluation data
# ----------------------------------------------------------------------
class TestZeroEvaluationData(Prompt512TestCase):

    def test_zero_to_zero_is_valid(self):
        comparisons = [_pair({}, {})]
        self.assertFullyValid(validate_trend(trend(comparisons), comparisons=comparisons))

    def test_zero_evaluation_rates_are_not_flagged_as_wrong_type(self):
        comparisons = [_pair({}, {"accepted": 3})]
        result = trend(comparisons)
        self.assertEqual(result["numeric"]["acceptance_rate"]["start"], 0.0)
        self.assertFullyValid(validate_trend(result, comparisons=comparisons))


# ----------------------------------------------------------------------
# 14. missing optional categorical value
# ----------------------------------------------------------------------
class TestMissingOptionalCategoricalValue(Prompt512TestCase):

    def test_both_sides_none_dominant_reason_is_valid(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 4}])
        result = trend(comparisons)
        self.assertEqual(result["dominant_rejection_reason"], {"state": CHANGE_UNCHANGED, "start": None, "end": None})
        self.assertFullyValid(validate_trend(result, comparisons=comparisons))

    def test_one_side_none_became_available_is_valid(self):
        comparisons = [_pair({"accepted": 1}, {"irrelevant": 2})]
        result = trend(comparisons)
        self.assertFullyValid(validate_trend(result, comparisons=comparisons))


# ----------------------------------------------------------------------
# 15. mixed valid and invalid source comparisons
# ----------------------------------------------------------------------
class TestMixedSourceComparisons(Prompt512TestCase):

    def test_mixed_sequence_validates_cleanly(self):
        good = _chain([{"accepted": 1}, {"accepted": 5}])[0]
        bad = _invalid_status_comparison()
        comparisons = [bad, good, bad]
        result = trend(comparisons)
        self.assertFullyValid(validate_trend(result, comparisons=comparisons))
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["ineligible_count"], 2)


# ----------------------------------------------------------------------
# 16. deterministic validation output
# ----------------------------------------------------------------------
class TestDeterministic(Prompt512TestCase):

    def test_same_input_same_output(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 4}, {"low_reliability": 2}])
        result = trend(comparisons)
        first = validate_trend(result, comparisons=comparisons)
        second = validate_trend(copy.deepcopy(result), comparisons=copy.deepcopy(comparisons))
        self.assertEqual(first, second)

    def test_repeated_calls_are_stable(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 2}]))
        outcomes = [validate_trend(result) for _ in range(5)]
        for outcome in outcomes[1:]:
            self.assertEqual(outcome, outcomes[0])


# ----------------------------------------------------------------------
# 17. validator does not mutate the input
# ----------------------------------------------------------------------
class TestNoMutation(Prompt512TestCase):

    def test_trend_summary_untouched(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 4}])
        result = trend(comparisons)
        before = copy.deepcopy(result)
        validate_trend(result, comparisons=comparisons)
        self.assertEqual(result, before)

    def test_comparisons_untouched(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 4}])
        before = copy.deepcopy(comparisons)
        validate_trend(trend(comparisons), comparisons=comparisons)
        self.assertEqual(comparisons, before)

    def test_returned_result_is_independent(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 2}]))
        outcome = validate_trend(result)
        outcome["errors"].append("tampered")
        self.assertEqual(validate_trend(result)["errors"], [])


# ----------------------------------------------------------------------
# 18. invalid trend summary is not automatically repaired
# ----------------------------------------------------------------------
class TestNoAutoRepair(Prompt512TestCase):

    def test_invalid_summary_is_reported_not_fixed(self):
        result = trend(_chain([{"accepted": 1}, {"accepted": 5}]))
        result["numeric"]["accepted_count"]["state"] = TREND_DECREASED
        before = copy.deepcopy(result)
        outcome = validate_trend(result)
        self.assertFalse(outcome["valid"])
        # the summary itself is untouched - no repair was attempted
        self.assertEqual(result, before)
        self.assertEqual(result["numeric"]["accepted_count"]["state"], TREND_DECREASED)


# ----------------------------------------------------------------------
# 19. Prompt 511 behavior remains unchanged
# ----------------------------------------------------------------------
class TestPrompt511Unaffected(Prompt512TestCase):

    def test_trend_function_output_shape_is_unchanged(self):
        comparisons = _chain([{"accepted": 1}, {"irrelevant": 2}, {"accepted": 4}])
        result = trend(comparisons)
        self.assertEqual(
            list(result.keys()),
            ["valid", "errors", "direction", "total_comparisons", "eligible_count",
             "ineligible_count", "ineligible_comparisons", "chronological_range",
             "numeric", "dominant_rejection_reason", "validation_status"])
        self.assertEqual(result["direction"], COMPARISON_DIRECTION)

    def test_trend_function_never_calls_the_new_validator_itself(self):
        import inspect
        from learning import learned_knowledge_statistics
        source = inspect.getsource(learned_knowledge_statistics.summarize_learned_knowledge_diagnostic_snapshot_comparison_trend)
        self.assertNotIn("validate_learned_knowledge_diagnostic_snapshot_comparison_trend", source)


# ----------------------------------------------------------------------
# 20. regression coverage for Prompts 500-511
# ----------------------------------------------------------------------
class TestRegressionPrompts500Through511(unittest.TestCase):

    def test_snapshot_comparison_and_trend_chain_unaffected(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 3}])
        self.assertTrue(comparisons[0]["valid"])
        self.assertTrue(validate_comparison(comparisons[0])["valid"])
        result = trend(comparisons)
        self.assertEqual(result["numeric"]["accepted_count"]["state"], TREND_INCREASED)

    def test_validator_not_referenced_from_the_gate_module(self):
        import inspect
        from learning import learned_knowledge_gate
        source = inspect.getsource(learned_knowledge_gate)
        self.assertNotIn("validate_learned_knowledge_diagnostic_snapshot_comparison_trend", source)

    def test_dominant_rejection_reason_constant_unaffected(self):
        result = trend([_pair({"accepted": 1}, {"irrelevant": 2})])
        self.assertEqual(result["dominant_rejection_reason"]["end"], DECISION_REJECTED_IRRELEVANT)


if __name__ == "__main__":
    unittest.main()
