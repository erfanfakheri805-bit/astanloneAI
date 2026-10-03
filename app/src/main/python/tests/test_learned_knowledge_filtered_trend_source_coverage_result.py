"""
Tests for Prompt 542 - Validate Filtered Trend Source Coverage Result.

`validate_learned_knowledge_filtered_trend_source_coverage_result()`
(learning/learned_knowledge_statistics.py) is a deterministic,
read-only structural check over the dict
`validate_learned_knowledge_filtered_trend_source_coverage()`
(Prompt 541) returns. It never re-runs or re-derives coverage from any
underlying comparisons or trend summary - the Prompt 541 `result` dict
is the only thing it reads - and never repairs, normalizes, or mutates
what it is given.

Covers:
    1.  fully valid complete result
    2.  valid incomplete result
    3.  missing required field
    4.  invalid "valid" type
    5.  invalid "well_formed" type
    6.  unknown coverage state
    7.  malformed errors
    8.  malformed warnings
    9.  malformed coverage entries
    10. contradictory complete state
    11. contradictory missing-source state
    12. contradictory duplicate-source state
    13. contradictory unexpected-source state
    14. contradictory ordering-mismatch state
    15. contradictory invalid-source state
    16. invalid-input result
    17. empty coverage
    18. zero-data result
    19. deterministic validation output

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_coverage_result -v
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
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
    compare_learned_knowledge_filtered_summary_snapshots as compare,
    summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend as trend,
    validate_learned_knowledge_filtered_trend_source_coverage as check,
    validate_learned_knowledge_filtered_trend_source_coverage_result as check_result,
    COMPARISON_DIRECTION,
)

_SMALL = ["evaluation_counts", "rates", "dominant_rejection_reason"]


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


def _summary(counts):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for step in ({"accepted": 1}, counts):
        history.record_statistics(_stats(**step))
    comparisons = [history.compare_sequences(1, 2)]
    built = report(snapshots=history, comparisons=comparisons)
    return fmt(built, validate(built, snapshots=history, comparisons=comparisons))


def _snapshots(specs):
    history = LearnedKnowledgeFilteredSummarySnapshotHistory()
    return [history.record_filtered_summary(filt(_summary(counts), sections))
            for sections, counts in specs]


def _chain(specs):
    snaps = _snapshots(specs)
    return snaps, [compare(snaps[i], snaps[i + 1]) for i in range(len(snaps) - 1)]


def _numeric_specs(totals, sections=_SMALL):
    return [(sections, {"accepted": n}) for n in totals]


# A minimal, fully valid "complete" Prompt 541 result shape, used as a
# base to copy-and-tamper for the malformed/contradictory cases below.
_COMPLETE_RESULT = {
    "valid": True, "well_formed": True, "state": "complete",
    "errors": [], "warnings": [], "coverage": {0: "valid", 1: "valid"},
}

# A minimal, fully valid "invalid_input" Prompt 541 result shape.
_INVALID_INPUT_RESULT = {
    "valid": False, "well_formed": False, "state": "invalid_input",
    "errors": ["comparisons_not_a_list"], "warnings": [], "coverage": {},
}


class FullyValidCompleteResultTests(unittest.TestCase):
    def test_01_fully_valid_complete_result_from_real_check(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(result["state"], "complete")
        self.assertEqual(check_result(result), {"valid": True, "errors": [], "warnings": []})

    def test_01b_fully_valid_complete_result_literal(self):
        self.assertEqual(check_result(_COMPLETE_RESULT),
                          {"valid": True, "errors": [], "warnings": []})


class ValidIncompleteResultTests(unittest.TestCase):
    def test_02_valid_incomplete_result_missing_source(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check([comps[0], None], summary)
        self.assertEqual(result["state"], "missing_source")
        self.assertEqual(check_result(result), {"valid": True, "errors": [], "warnings": []})

    def test_02b_valid_incomplete_result_too_many_sources(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps[:1])
        result = check(comps, summary)
        self.assertEqual(result["state"], "incomplete")
        self.assertEqual(check_result(result), {"valid": True, "errors": [], "warnings": []})


class MissingRequiredFieldTests(unittest.TestCase):
    def test_03_missing_state_field(self):
        tampered = dict(_COMPLETE_RESULT)
        del tampered["state"]
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("missing_field:state", outcome["errors"])

    def test_03b_missing_coverage_field(self):
        tampered = dict(_COMPLETE_RESULT)
        del tampered["coverage"]
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("missing_field:coverage", outcome["errors"])

    def test_03c_missing_all_fields(self):
        outcome = check_result({})
        self.assertFalse(outcome["valid"])
        for field in ("valid", "well_formed", "state", "errors", "warnings", "coverage"):
            self.assertIn("missing_field:%s" % field, outcome["errors"])

    def test_03d_result_not_a_dict(self):
        for bad in (None, [], "complete", 5):
            outcome = check_result(bad)
            self.assertEqual(outcome, {"valid": False, "errors": ["result_not_a_dict"], "warnings": []})


class InvalidValidTypeTests(unittest.TestCase):
    def test_04_invalid_valid_type_string(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["valid"] = "true"
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("invalid_type:valid", outcome["errors"])

    def test_04b_invalid_valid_type_int(self):
        # bool is a subclass of int in Python - a plain 1 is not a bool.
        tampered = dict(_COMPLETE_RESULT)
        tampered["valid"] = 1
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("invalid_type:valid", outcome["errors"])


class InvalidWellFormedTypeTests(unittest.TestCase):
    def test_05_invalid_well_formed_type_string(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["well_formed"] = "yes"
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("invalid_type:well_formed", outcome["errors"])

    def test_05b_invalid_well_formed_type_none(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["well_formed"] = None
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("invalid_type:well_formed", outcome["errors"])


class UnknownCoverageStateTests(unittest.TestCase):
    def test_06_unknown_state(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["state"] = "totally_fine"
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("invalid_state", outcome["errors"])

    def test_06b_unknown_state_wrong_type(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["state"] = 42
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("invalid_state", outcome["errors"])


class MalformedErrorsTests(unittest.TestCase):
    def test_07_errors_not_a_list(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["errors"] = "none"
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("invalid_type:errors", outcome["errors"])

    def test_07b_errors_list_with_non_string_item(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["errors"] = [123]
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("invalid_type:errors", outcome["errors"])


class MalformedWarningsTests(unittest.TestCase):
    def test_08_warnings_not_a_list(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["warnings"] = {}
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("invalid_type:warnings", outcome["errors"])

    def test_08b_warnings_list_with_non_string_item(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["warnings"] = [None]
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("invalid_type:warnings", outcome["errors"])


class MalformedCoverageEntriesTests(unittest.TestCase):
    def test_09_coverage_not_a_dict(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["coverage"] = ["valid", "valid"]
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("invalid_type:coverage", outcome["errors"])

    def test_09b_coverage_non_int_key(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["coverage"] = {"0": "valid"}
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertTrue(any(e.startswith("invalid_coverage_key:") for e in outcome["errors"]))

    def test_09c_coverage_negative_key(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["coverage"] = {-1: "valid"}
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertTrue(any(e.startswith("invalid_coverage_key:") for e in outcome["errors"]))

    def test_09d_coverage_unknown_category(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["coverage"] = {0: "sort_of_okay"}
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("invalid_coverage_category:0", outcome["errors"])


class ContradictoryCompleteStateTests(unittest.TestCase):
    def test_10_complete_state_with_missing_source(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["state"] = "complete"
        tampered["valid"] = True
        tampered["coverage"] = {0: "valid", 1: "missing"}
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("state_inconsistent_with_coverage:complete", outcome["errors"])


class ContradictoryMissingSourceStateTests(unittest.TestCase):
    def test_11_missing_source_state_with_no_missing_category(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["state"] = "missing_source"
        tampered["valid"] = False
        # coverage has no "missing" category anywhere.
        tampered["coverage"] = {0: "valid", 1: "valid"}
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("state_inconsistent_with_coverage:missing_source", outcome["errors"])


class ContradictoryDuplicateSourceStateTests(unittest.TestCase):
    def test_12_duplicate_source_state_with_no_duplicated_category(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["state"] = "duplicate_source"
        tampered["valid"] = False
        tampered["coverage"] = {0: "valid", 1: "valid"}
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("state_inconsistent_with_coverage:duplicate_source", outcome["errors"])


class ContradictoryUnexpectedSourceStateTests(unittest.TestCase):
    def test_13_unexpected_source_state_with_no_ordering_mismatch_category(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["state"] = "unexpected_source"
        tampered["valid"] = False
        tampered["coverage"] = {0: "valid", 1: "valid"}
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("state_inconsistent_with_coverage:unexpected_source", outcome["errors"])


class ContradictoryOrderingMismatchStateTests(unittest.TestCase):
    def test_14_ordering_mismatch_state_with_no_mismatched_category_or_error(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["state"] = "ordering_mismatch"
        tampered["valid"] = False
        tampered["coverage"] = {0: "valid", 1: "valid"}
        tampered["errors"] = []
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("state_inconsistent_with_coverage:ordering_mismatch", outcome["errors"])


class ContradictoryInvalidSourceStateTests(unittest.TestCase):
    def test_15_invalid_source_state_with_no_invalid_source_category(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["state"] = "invalid_source"
        tampered["valid"] = False
        tampered["coverage"] = {0: "valid", 1: "valid"}
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("state_inconsistent_with_coverage:invalid_source", outcome["errors"])


class InvalidInputResultTests(unittest.TestCase):
    def test_16_valid_invalid_input_result(self):
        self.assertEqual(check_result(_INVALID_INPUT_RESULT),
                          {"valid": True, "errors": [], "warnings": []})

    def test_16b_invalid_input_state_misused_when_well_formed(self):
        # well_formed True and no "invalid_source:comparisons" error -
        # the coverage result was NOT itself structurally invalid, so
        # "invalid_input" is not justified here.
        tampered = dict(_COMPLETE_RESULT)
        tampered["state"] = "invalid_input"
        tampered["valid"] = False
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("state_inconsistent_with_coverage:invalid_input", outcome["errors"])

    def test_16c_real_invalid_input_from_check(self):
        result = check("not-a-list", trend([]))
        self.assertEqual(result["state"], "invalid_input")
        self.assertEqual(check_result(result), {"valid": True, "errors": [], "warnings": []})

    def test_16d_real_invalid_input_not_well_formed(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        result = check(comps, {"valid": True})
        self.assertEqual(result["state"], "invalid_input")
        self.assertFalse(result["well_formed"])
        self.assertEqual(check_result(result), {"valid": True, "errors": [], "warnings": []})


class EmptyCoverageTests(unittest.TestCase):
    def test_17_empty_coverage_complete(self):
        result = check([], trend([]))
        self.assertEqual(result["coverage"], {})
        self.assertEqual(check_result(result), {"valid": True, "errors": [], "warnings": []})

    def test_17b_empty_coverage_with_leftover_errors_still_checked(self):
        # Empty coverage but a non-empty errors list with no recognized
        # prefix still yields "incomplete" under the fixed priority
        # order - a state claiming "complete" here is contradictory.
        tampered = {
            "valid": True, "well_formed": True, "state": "complete",
            "errors": ["something_unexpected"], "warnings": [], "coverage": {},
        }
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("state_inconsistent_with_coverage:complete", outcome["errors"])


class ZeroDataResultTests(unittest.TestCase):
    def test_18_zero_data_none_comparisons(self):
        result = check(None, trend([]))
        self.assertEqual(check_result(result), {"valid": True, "errors": [], "warnings": []})

    def test_18b_zero_data_literal_result(self):
        zero_data = {
            "valid": True, "well_formed": True, "state": "complete",
            "errors": [], "warnings": [], "coverage": {},
        }
        self.assertEqual(check_result(zero_data), {"valid": True, "errors": [], "warnings": []})


class DeterministicValidationOutputTests(unittest.TestCase):
    def test_19_deterministic_on_valid_result(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps, summary)
        self.assertEqual(check_result(result), check_result(result))

    def test_19b_deterministic_on_malformed_result(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["coverage"] = {0: "bogus"}
        self.assertEqual(check_result(tampered), check_result(tampered))

    def test_19c_does_not_mutate_input(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        result = check(comps, summary)
        result_copy = copy.deepcopy(result)
        check_result(result)
        self.assertEqual(result, result_copy)

    def test_19d_result_shape_has_exactly_the_expected_keys(self):
        outcome = check_result(_COMPLETE_RESULT)
        self.assertEqual(set(outcome.keys()), {"valid", "errors", "warnings"})

    def test_19e_valid_inconsistent_with_state_detected(self):
        tampered = dict(_COMPLETE_RESULT)
        tampered["valid"] = False  # state is still "complete"
        outcome = check_result(tampered)
        self.assertFalse(outcome["valid"])
        self.assertIn("valid_inconsistent_with_state", outcome["errors"])


if __name__ == "__main__":
    unittest.main()
