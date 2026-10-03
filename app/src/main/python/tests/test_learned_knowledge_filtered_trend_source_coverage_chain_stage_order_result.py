"""
Tests for Prompt 546 - Validate Filtered Trend Coverage Chain Stage
Order Result.

`validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_
order_result()` (learning/learned_knowledge_statistics.py) is a small,
deterministic, read-only STRUCTURAL check over the dict
`validate_learned_knowledge_filtered_trend_source_coverage_chain_
stage_order()` (Prompt 545) returns. It never recomputes stage
ordering from any `chain_stages`/`stage_order` input - only `result`'s
own fields are read.

Covers:
    1.  valid "valid" result
    2.  valid "missing_stage" result
    3.  valid "duplicate_stage" result
    4.  valid "unexpected_stage" result
    5.  valid "invalid_order" result
    6.  valid "invalid_input" result
    7.  missing required field
    8.  wrong boolean type
    9.  unknown state
    10. malformed errors
    11. malformed warnings
    12. malformed stage information
    13. contradictory "valid" and "state"
    14. contradictory state and stage data
    15. fabricated error
    16. missing required error
    17. empty stage data
    18. zero-data case
    19. deterministic output

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_result -v
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_statistics import (
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order as check_order,
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_result as check_result,
    _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_SEQUENCE as CANONICAL,
)


def _entries(names):
    return [{"stage": name} for name in names]


class TestValidValidResult(unittest.TestCase):

    def test_real_valid_result_is_consistent(self):
        order_result = check_order(_entries(list(CANONICAL)))
        result = check_result(order_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_handcrafted_valid_result_is_consistent(self):
        result = check_result({"valid": True, "state": "valid", "errors": [], "warnings": []})
        self.assertEqual(result["status"], "consistent")


class TestValidMissingStageResult(unittest.TestCase):

    def test_real_missing_stage_result_is_consistent(self):
        names = [n for n in CANONICAL if n != "coverage_validation"]
        order_result = check_order(_entries(names))
        self.assertEqual(order_result["state"], "missing_stage")
        result = check_result(order_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class TestValidDuplicateStageResult(unittest.TestCase):

    def test_real_duplicate_stage_result_is_consistent(self):
        names = ["source_comparisons", "coverage", "coverage",
                 "coverage_validation", "coverage_consistency_validation",
                 "chain_integrity_validation"]
        order_result = check_order(_entries(names))
        self.assertEqual(order_result["state"], "duplicate_stage")
        result = check_result(order_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class TestValidUnexpectedStageResult(unittest.TestCase):

    def test_real_unexpected_stage_result_is_consistent(self):
        order_result = check_order(_entries(list(CANONICAL) + ["bogus_stage"]))
        self.assertEqual(order_result["state"], "unexpected_stage")
        result = check_result(order_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class TestValidInvalidOrderResult(unittest.TestCase):

    def test_real_reversed_order_result_is_consistent(self):
        order_result = check_order(_entries(list(reversed(CANONICAL))))
        self.assertEqual(order_result["state"], "invalid_order")
        result = check_result(order_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_real_source_references_later_stage_result_is_consistent(self):
        entries = _entries(list(CANONICAL))
        entries[1] = {"stage": "coverage", "source": "chain_integrity_validation"}
        order_result = check_order(entries)
        self.assertEqual(order_result["state"], "invalid_order")
        result = check_result(order_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_real_stage_order_metadata_mismatch_result_is_consistent(self):
        names = list(CANONICAL)
        order_result = check_order(_entries(names), stage_order=list(reversed(names)))
        self.assertEqual(order_result["state"], "invalid_order")
        result = check_result(order_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class TestValidInvalidInputResult(unittest.TestCase):

    def test_real_chain_stages_not_a_list_result_is_consistent(self):
        order_result = check_order("not a list")
        self.assertEqual(order_result["state"], "invalid_input")
        result = check_result(order_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_real_malformed_entry_result_is_consistent(self):
        order_result = check_order([{"stage": 5}])
        self.assertEqual(order_result["state"], "invalid_input")
        result = check_result(order_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_real_malformed_stage_order_metadata_result_is_consistent(self):
        order_result = check_order(_entries(list(CANONICAL)), stage_order="bad")
        self.assertEqual(order_result["state"], "invalid_input")
        result = check_result(order_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class TestMissingRequiredField(unittest.TestCase):

    def test_missing_single_field(self):
        result = check_result({"valid": True, "state": "valid", "errors": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("missing_field:warnings", result["errors"])

    def test_missing_multiple_fields(self):
        result = check_result({})
        self.assertEqual(result["status"], "inconsistent")
        for field in ("valid", "state", "errors", "warnings"):
            self.assertIn("missing_field:%s" % field, result["errors"])


class TestWrongBooleanType(unittest.TestCase):

    def test_valid_field_not_a_bool(self):
        result = check_result({"valid": "true", "state": "valid", "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:valid", result["errors"])

    def test_valid_field_is_int_not_bool(self):
        # 1/0 are ints in Python, not real bools, and must be rejected.
        result = check_result({"valid": 1, "state": "valid", "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:valid", result["errors"])


class TestUnknownState(unittest.TestCase):

    def test_state_not_in_allowed_set(self):
        result = check_result(
            {"valid": False, "state": "totally_unknown", "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_state", result["errors"])

    def test_state_not_a_string(self):
        result = check_result({"valid": False, "state": 5, "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_state", result["errors"])


class TestMalformedErrors(unittest.TestCase):

    def test_errors_not_a_list(self):
        result = check_result(
            {"valid": True, "state": "valid", "errors": "oops", "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:errors", result["errors"])

    def test_errors_contains_non_string(self):
        result = check_result(
            {"valid": False, "state": "missing_stage", "errors": [5], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:errors", result["errors"])
        # Type failure suppresses the deeper per-code / state checks.
        self.assertNotIn("state_inconsistent_with_errors:missing_stage", result["errors"])


class TestMalformedWarnings(unittest.TestCase):

    def test_warnings_not_a_list(self):
        result = check_result(
            {"valid": True, "state": "valid", "errors": [], "warnings": "oops"})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:warnings", result["errors"])

    def test_warnings_contains_non_string(self):
        result = check_result(
            {"valid": True, "state": "valid", "errors": [], "warnings": [None]})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:warnings", result["errors"])

    def test_any_warning_present_is_fabricated(self):
        # Prompt 545 never raises a warning of its own.
        result = check_result(
            {"valid": True, "state": "valid", "errors": [], "warnings": ["something"]})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("fabricated_warning:something", result["errors"])


class TestMalformedStageInformation(unittest.TestCase):

    def test_missing_stage_code_with_empty_suffix(self):
        result = check_result(
            {"valid": False, "state": "missing_stage", "errors": ["missing_stage:"], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("malformed_stage_information:missing_stage:", result["errors"])

    def test_unexpected_stage_code_with_empty_suffix(self):
        result = check_result(
            {"valid": False, "state": "unexpected_stage",
             "errors": ["unexpected_stage:"], "warnings": []})
        self.assertIn("malformed_stage_information:unexpected_stage:", result["errors"])

    def test_duplicate_stage_code_with_empty_suffix(self):
        result = check_result(
            {"valid": False, "state": "duplicate_stage",
             "errors": ["duplicate_stage:"], "warnings": []})
        self.assertIn("malformed_stage_information:duplicate_stage:", result["errors"])

    def test_invalid_order_source_code_with_empty_suffix(self):
        result = check_result(
            {"valid": False, "state": "invalid_order",
             "errors": ["invalid_order:source_not_before_stage:"], "warnings": []})
        self.assertIn(
            "malformed_stage_information:invalid_order:source_not_before_stage:", result["errors"])


class TestContradictoryValidAndState(unittest.TestCase):

    def test_valid_true_with_missing_stage_state(self):
        result = check_result(
            {"valid": True, "state": "missing_stage",
             "errors": ["missing_stage:coverage"], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("valid_inconsistent_with_state", result["errors"])

    def test_valid_false_with_valid_state(self):
        result = check_result({"valid": False, "state": "valid", "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("valid_inconsistent_with_state", result["errors"])


class TestContradictoryStateAndStageData(unittest.TestCase):

    def test_missing_stage_state_with_no_supporting_errors(self):
        result = check_result(
            {"valid": False, "state": "missing_stage", "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("state_inconsistent_with_errors:missing_stage", result["errors"])

    def test_valid_state_with_missing_stage_evidence(self):
        result = check_result(
            {"valid": True, "state": "valid",
             "errors": ["missing_stage:coverage"], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("state_inconsistent_with_errors:valid", result["errors"])

    def test_duplicate_stage_state_with_only_unexpected_evidence(self):
        result = check_result(
            {"valid": False, "state": "duplicate_stage",
             "errors": ["unexpected_stage:bogus"], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("state_inconsistent_with_errors:duplicate_stage", result["errors"])


class TestFabricatedError(unittest.TestCase):

    def test_unrecognized_error_code(self):
        result = check_result(
            {"valid": False, "state": "invalid_order",
             "errors": ["not_a_real_code"], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("unrecognized_error_code:not_a_real_code", result["errors"])

    def test_fabricated_warning_reported(self):
        result = check_result(
            {"valid": True, "state": "valid", "errors": [], "warnings": ["invented"]})
        self.assertIn("fabricated_warning:invented", result["errors"])


class TestMissingRequiredError(unittest.TestCase):

    def test_invalid_input_state_with_no_input_error_present(self):
        result = check_result(
            {"valid": False, "state": "invalid_input", "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("state_inconsistent_with_errors:invalid_input", result["errors"])

    def test_unexpected_stage_state_with_no_unexpected_evidence(self):
        result = check_result(
            {"valid": False, "state": "unexpected_stage", "errors": [], "warnings": []})
        self.assertIn("state_inconsistent_with_errors:unexpected_stage", result["errors"])


class TestEmptyStageData(unittest.TestCase):

    def test_real_empty_chain_result_is_consistent(self):
        order_result = check_order([])
        self.assertEqual(order_result["state"], "missing_stage")
        result = check_result(order_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_handcrafted_empty_errors_with_valid_state(self):
        result = check_result({"valid": True, "state": "valid", "errors": [], "warnings": []})
        self.assertEqual(result["status"], "consistent")


class TestZeroDataCase(unittest.TestCase):

    def test_result_not_a_dict_is_invalid_input(self):
        result = check_result(None)
        self.assertEqual(result, {"status": "invalid_input", "errors": ["result_not_a_dict"], "warnings": []})

    def test_result_is_empty_dict(self):
        result = check_result({})
        self.assertEqual(result["status"], "inconsistent")
        self.assertEqual(len(result["errors"]), 4)

    def test_result_is_not_a_dict_various_types(self):
        for bad in ([], "string", 5, 5.0, True):
            result = check_result(bad)
            self.assertEqual(result["status"], "invalid_input")


class TestNeverMutatesInput(unittest.TestCase):

    def test_result_left_unchanged(self):
        original = {"valid": True, "state": "valid", "errors": [], "warnings": []}
        snapshot = dict(original)
        check_result(original)
        self.assertEqual(original, snapshot)

    def test_result_with_lists_left_unchanged(self):
        original = {"valid": False, "state": "missing_stage",
                    "errors": ["missing_stage:coverage"], "warnings": []}
        errors_snapshot = list(original["errors"])
        check_result(original)
        self.assertEqual(original["errors"], errors_snapshot)


class TestDeterministicOutput(unittest.TestCase):

    def test_same_input_produces_equal_result_every_call(self):
        result = {"valid": False, "state": "invalid_order",
                  "errors": ["invalid_order:sequence", "bogus_code"], "warnings": ["oops"]}
        first = check_result(result)
        second = check_result(result)
        self.assertEqual(first, second)

    def test_deterministic_across_many_shapes(self):
        cases = [
            {"valid": True, "state": "valid", "errors": [], "warnings": []},
            {},
            None,
            "invalid",
            {"valid": True, "state": "missing_stage", "errors": [], "warnings": []},
            check_order([]),
            check_order(_entries(list(CANONICAL))),
        ]
        for case in cases:
            first = check_result(case)
            second = check_result(case)
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
