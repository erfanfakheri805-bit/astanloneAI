"""
Tests for Prompt 552 - Validate Complete Chain Consistency Validation
Result.

`validate_learned_knowledge_filtered_trend_source_coverage_complete_
chain_consistency_validation_result()` (learning/learned_knowledge_
statistics.py) is a small, deterministic, read-only STRUCTURAL check
over the dict `validate_learned_knowledge_filtered_trend_source_
coverage_complete_chain_consistency_validation()` (Prompt 551) returns.
It never recomputes anything from Prompt 549, 550, or Prompt 551's own
raw inputs - only `result`'s own fields are read.

Covers:
    1.  valid consistent result
    2.  valid inconsistent result
    3.  valid invalid_input result
    4.  missing status
    5.  missing errors
    6.  missing warnings
    7.  wrong status type
    8.  invalid status value
    9.  wrong errors type
    10. malformed error entries
    11. wrong warnings type
    12. malformed warning entries
    13. malformed evidence/details (no such field exists - extras ignored)
    14. inconsistent status/error combinations
    15. inconsistent status/evidence combinations
    16. unexpected structure requiring rejection
    17. empty/zero-data-safe result
    18. repeated validation is deterministic
    19. validation does not mutate the input

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency_validation_result -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_statistics import (
    validate_learned_knowledge_filtered_trend_source_coverage as check_coverage,
    validate_learned_knowledge_filtered_trend_source_coverage_result as check_coverage_result,
    validate_learned_knowledge_filtered_trend_source_coverage_result_consistency as check_coverage_consistency,
    validate_learned_knowledge_filtered_trend_source_coverage_chain as check_chain,
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order as check_order,
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_result as check_order_result,
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_consistency as check_order_consistency,
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_consistency_result as check_order_consistency_result,
    validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency as check_complete,
    validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency_result as check_complete_result,
    validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency_validation as check_validation,
    validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency_validation_result as check_result,
    summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend as trend,
    _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_SEQUENCE as CANONICAL,
)


def _entries(names):
    return [{"stage": name} for name in names]


def _real_consistent_complete_result():
    """A genuinely valid, `"consistent"` Prompt 549 result, built the
    same way a well-behaved caller would - empty/zero-data on both
    sides of the chain."""
    trend_summary = trend([])
    coverage_result = check_coverage([], trend_summary)
    coverage_validation_result = check_coverage_result(coverage_result)
    consistency_result = check_coverage_consistency(coverage_result, coverage_validation_result)
    chain_result = check_chain(
        [], trend_summary, coverage_result, coverage_validation_result, consistency_result)

    stages = _entries(list(CANONICAL))
    order_result = check_order(stages)
    order_result_validation = check_order_result(order_result)
    order_result_consistency = check_order_consistency(
        stages, None, order_result, order_result_validation)
    order_result_consistency_validation = check_order_consistency_result(order_result_consistency)

    complete_result = check_complete(
        [], trend_summary, coverage_result, coverage_validation_result, consistency_result,
        chain_result, stages, None, order_result, order_result_validation,
        order_result_consistency, order_result_consistency_validation)
    return complete_result


def _real_consistent_validation_result():
    """A genuinely `"consistent"` Prompt 551 result, built by calling
    the real Prompt 550/551 helpers on a genuine Prompt 549 result."""
    complete_result = _real_consistent_complete_result()
    validation_result = check_complete_result(complete_result)
    return check_validation(complete_result, validation_result)


class ValidConsistentResultTests(unittest.TestCase):

    def test_01_real_consistent_result_is_consistent(self):
        prompt551_result = _real_consistent_validation_result()
        self.assertEqual(prompt551_result["status"], "consistent")
        result = check_result(prompt551_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_01b_handcrafted_consistent_result_is_consistent(self):
        result = check_result({"status": "consistent", "errors": [], "warnings": []})
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class ValidInconsistentResultTests(unittest.TestCase):

    def test_02_real_inconsistent_result_is_consistent(self):
        complete_result = _real_consistent_complete_result()
        genuine_validation = check_complete_result(complete_result)
        tampered_validation = dict(genuine_validation)
        tampered_validation["status"] = "inconsistent"
        tampered_validation["errors"] = ["invented"]
        prompt551_result = check_validation(complete_result, tampered_validation)
        self.assertEqual(prompt551_result["status"], "inconsistent")
        result = check_result(prompt551_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_02b_handcrafted_inconsistent_result_is_consistent(self):
        result = check_result({
            "status": "inconsistent",
            "errors": ["stage:validation_result:mismatched_field:status"],
            "warnings": [],
        })
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class ValidInvalidInputResultTests(unittest.TestCase):

    def test_03_real_invalid_input_result_is_consistent(self):
        prompt551_result = check_validation("not-a-dict", 42)
        self.assertEqual(prompt551_result["status"], "invalid_input")
        result = check_result(prompt551_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_03b_handcrafted_invalid_input_result_is_consistent(self):
        result = check_result({
            "status": "invalid_input", "errors": ["validation_result_not_a_dict"], "warnings": []})
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class MissingStatusTests(unittest.TestCase):

    def test_04_missing_status(self):
        result = check_result({"errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("missing_field:status", result["errors"])


class MissingErrorsTests(unittest.TestCase):

    def test_05_missing_errors(self):
        result = check_result({"status": "consistent", "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("missing_field:errors", result["errors"])


class MissingWarningsTests(unittest.TestCase):

    def test_06_missing_warnings(self):
        result = check_result({"status": "consistent", "errors": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("missing_field:warnings", result["errors"])

    def test_06b_missing_all_fields(self):
        result = check_result({})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("missing_field:status", result["errors"])
        self.assertIn("missing_field:errors", result["errors"])
        self.assertIn("missing_field:warnings", result["errors"])


class WrongStatusTypeTests(unittest.TestCase):

    def test_07_status_given_as_int(self):
        result = check_result({"status": 1, "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_status", result["errors"])

    def test_07b_status_given_as_bool(self):
        result = check_result({"status": True, "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_status", result["errors"])

    def test_07c_status_given_as_none(self):
        result = check_result({"status": None, "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_status", result["errors"])


class InvalidStatusValueTests(unittest.TestCase):

    def test_08_unrecognized_status_string(self):
        result = check_result({"status": "sort_of_consistent", "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_status", result["errors"])


class WrongErrorsTypeTests(unittest.TestCase):

    def test_09_errors_given_as_dict(self):
        result = check_result({"status": "consistent", "errors": {}, "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:errors", result["errors"])

    def test_09b_errors_given_as_string(self):
        result = check_result({"status": "consistent", "errors": "oops", "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:errors", result["errors"])


class MalformedErrorEntriesTests(unittest.TestCase):

    def test_10_error_entry_not_a_string(self):
        result = check_result({"status": "inconsistent", "errors": [123], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:errors", result["errors"])

    def test_10b_unrecognized_error_code(self):
        result = check_result({
            "status": "inconsistent", "errors": ["totally_invented_code"], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("unrecognized_error_code:totally_invented_code", result["errors"])

    def test_10c_malformed_stage_information_empty_field_suffix(self):
        result = check_result({
            "status": "inconsistent",
            "errors": ["stage:validation_result:mismatched_field:"],
            "warnings": [],
        })
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn(
            "malformed_stage_information:stage:validation_result:mismatched_field:",
            result["errors"])

    def test_10d_wrong_link_name_is_unrecognized(self):
        result = check_result({
            "status": "inconsistent",
            "errors": ["stage:bogus_link:mismatched_field:status"],
            "warnings": [],
        })
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn(
            "unrecognized_error_code:stage:bogus_link:mismatched_field:status",
            result["errors"])

    def test_10e_genuine_input_error_code_recognized(self):
        result = check_result({
            "status": "invalid_input",
            "errors": ["consistency_result_not_a_dict"],
            "warnings": [],
        })
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class WrongWarningsTypeTests(unittest.TestCase):

    def test_11_warnings_given_as_dict(self):
        result = check_result({"status": "consistent", "errors": [], "warnings": {}})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:warnings", result["errors"])

    def test_11b_warnings_given_as_string(self):
        result = check_result({"status": "consistent", "errors": [], "warnings": "oops"})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:warnings", result["errors"])


class MalformedWarningEntriesTests(unittest.TestCase):

    def test_12_warning_entry_not_a_string(self):
        result = check_result({"status": "consistent", "errors": [], "warnings": [123]})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:warnings", result["errors"])

    def test_12b_any_warning_is_fabricated(self):
        result = check_result({
            "status": "consistent", "errors": [], "warnings": ["some_warning"]})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("fabricated_warning:some_warning", result["errors"])


class MalformedEvidenceDetailsTests(unittest.TestCase):
    """Prompt 551's result carries no separate evidence/details field -
    its entire evidence is `"errors"`/`"warnings"` themselves. An extra
    top-level field is therefore not itself flagged by this vocabulary."""

    def test_13_extra_evidence_field_not_itself_flagged(self):
        result = check_result({
            "status": "consistent", "errors": [], "warnings": [], "evidence": {"bad": True}})
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_13b_extra_details_field_not_itself_flagged(self):
        result = check_result({
            "status": "consistent", "errors": [], "warnings": [], "details": ["x", "y"]})
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class InconsistentStatusErrorCombinationTests(unittest.TestCase):

    def test_14_consistent_status_with_real_errors(self):
        result = check_result({
            "status": "consistent",
            "errors": ["stage:validation_result:mismatched_field:status"],
            "warnings": [],
        })
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("status_inconsistent_with_errors:consistent", result["errors"])

    def test_14b_inconsistent_status_with_no_errors(self):
        result = check_result({"status": "inconsistent", "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("status_inconsistent_with_errors:inconsistent", result["errors"])

    def test_14c_invalid_input_status_with_no_input_error(self):
        result = check_result({
            "status": "invalid_input",
            "errors": ["stage:validation_result:mismatched_field:status"],
            "warnings": [],
        })
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("status_inconsistent_with_errors:invalid_input", result["errors"])

    def test_14d_consistent_status_with_input_error(self):
        result = check_result({
            "status": "consistent", "errors": ["validation_result_not_a_dict"], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("status_inconsistent_with_errors:consistent", result["errors"])


class InconsistentStatusEvidenceCombinationTests(unittest.TestCase):
    """Prompt 551's evidence for a given status is entirely captured in
    `"errors"` (there is no separate evidence field) - so a status that
    disagrees with its own `"errors"` IS the evidence-level
    contradiction this checks."""

    def test_15_invalid_input_status_with_genuine_input_error(self):
        result = check_result({
            "status": "invalid_input",
            "errors": ["consistency_result_not_a_dict", "validation_result_not_a_dict"],
            "warnings": [],
        })
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_15b_inconsistent_status_with_genuine_link_error(self):
        result = check_result({
            "status": "inconsistent",
            "errors": ["stage:validation_result:unexpected_field:extra"],
            "warnings": [],
        })
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class UnexpectedStructureTests(unittest.TestCase):

    def test_16_bad_field_skipped_in_cross_checks(self):
        result = check_result({"status": 42, "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_status", result["errors"])
        self.assertFalse(
            any(e.startswith("status_inconsistent_with_errors:") for e in result["errors"]))

    def test_16b_extra_unrecognized_top_level_field_is_not_itself_flagged(self):
        result = check_result({
            "status": "consistent", "errors": [], "warnings": [], "extra_thing": True})
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class EmptyZeroDataSafeResultTests(unittest.TestCase):

    def test_17_completely_empty_dict(self):
        result = check_result({})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("missing_field:status", result["errors"])
        self.assertIn("missing_field:errors", result["errors"])
        self.assertIn("missing_field:warnings", result["errors"])

    def test_17b_none_result(self):
        result = check_result(None)
        self.assertEqual(result, {"status": "invalid_input", "errors": ["result_not_a_dict"],
                                   "warnings": []})

    def test_17c_result_not_a_dict_string(self):
        result = check_result("not-a-dict")
        self.assertEqual(result, {"status": "invalid_input", "errors": ["result_not_a_dict"],
                                   "warnings": []})

    def test_17d_result_not_a_dict_list(self):
        result = check_result([])
        self.assertEqual(result, {"status": "invalid_input", "errors": ["result_not_a_dict"],
                                   "warnings": []})

    def test_17e_zero_data_consistent_shape(self):
        result = check_result({"status": "consistent", "errors": [], "warnings": []})
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class DeterministicValidationTests(unittest.TestCase):

    def test_18_repeated_calls_equal_on_valid_input(self):
        payload = {"status": "consistent", "errors": [], "warnings": []}
        first = check_result(payload)
        second = check_result(payload)
        self.assertEqual(first, second)

    def test_18b_repeated_calls_equal_on_broken_input(self):
        payload = {
            "status": "consistent",
            "errors": ["stage:validation_result:mismatched_field:status", "invented_code"],
            "warnings": ["invented_warning"],
        }
        first = check_result(payload)
        second = check_result(payload)
        self.assertEqual(first, second)

    def test_18c_repeated_calls_equal_on_real_validation_result(self):
        prompt551_result = _real_consistent_validation_result()
        first = check_result(prompt551_result)
        second = check_result(prompt551_result)
        self.assertEqual(first, second)


class DoesNotMutateInputTests(unittest.TestCase):

    def test_19_does_not_mutate_valid_input(self):
        payload = {"status": "consistent", "errors": [], "warnings": []}
        snapshot = copy.deepcopy(payload)
        check_result(payload)
        self.assertEqual(payload, snapshot)

    def test_19b_does_not_mutate_broken_input(self):
        payload = {
            "status": "inconsistent",
            "errors": ["stage:validation_result:mismatched_field:status", "made_up_code"],
            "warnings": ["fabricated"],
        }
        snapshot = copy.deepcopy(payload)
        check_result(payload)
        self.assertEqual(payload, snapshot)

    def test_19c_does_not_mutate_real_validation_result(self):
        prompt551_result = _real_consistent_validation_result()
        snapshot = copy.deepcopy(prompt551_result)
        check_result(prompt551_result)
        self.assertEqual(prompt551_result, snapshot)


if __name__ == "__main__":
    unittest.main()
