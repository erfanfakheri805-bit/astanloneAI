"""
Tests for Prompt 553 - Validate Complete Coverage Chain Validation
Consistency.

`validate_learned_knowledge_filtered_trend_source_coverage_complete_
chain_validation_consistency()` (learning/learned_knowledge_
statistics.py) is a small, deterministic, read-only consistency check
tying together:

    - a caller's claimed Prompt 551 result, `validation_result`
    - a caller's claimed Prompt 552 validation of that same result,
      `validation_result_validation`

It adds no detection of its own: it recomputes Prompt 552
(`validate_learned_knowledge_filtered_trend_source_coverage_complete_
chain_consistency_validation_result()`) on the caller's `validation_
result` - unchanged - and compares that recomputation against the
caller's `validation_result_validation`, field by field.

Covers:
    1.  valid consistent case (real chain, agreement)
    2.  valid inconsistent case (real chain, tampered validation)
    3.  invalid_input case (both arguments malformed)
    4.  agreement between result and validation
    5.  disagreement (mismatching validation result)
    6.  malformed first result (validation_result)
    7.  malformed second result (validation_result_validation)
    8.  missing inputs
    9.  wrong input types
    10. invalid nested structures
    11. contradictory status values
    12. contradictory error information
    13. contradictory evidence (errors/warnings)
    14. zero-data-safe behavior
    15. deterministic repeated execution
    16. no mutation of either input

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_coverage_complete_chain_validation_consistency -v
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
    validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency_validation_result as check_validation_result,
    validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_validation_consistency as check_validation_consistency,
    summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend as trend,
    _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_SEQUENCE as CANONICAL,
)


def _entries(names):
    return [{"stage": name} for name in names]


def _real_consistent_validation_result():
    """A genuinely valid, `"consistent"` Prompt 551 result, built the
    same way a well-behaved caller would - empty/zero-data on both
    sides of the chain. Mirrors the Prompt 552 test helper exactly."""
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
    validation_result = check_validation(complete_result, check_complete_result(complete_result))
    return validation_result


class ValidConsistentCaseTests(unittest.TestCase):

    def test_01_real_consistent_result_with_genuine_validation_agrees(self):
        validation_result = _real_consistent_validation_result()
        self.assertEqual(validation_result["status"], "consistent")
        validation_result_validation = check_validation_result(validation_result)
        outcome = check_validation_consistency(validation_result, validation_result_validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_01b_handcrafted_agreement_is_consistent(self):
        validation_result = {"status": "consistent", "errors": [], "warnings": []}
        validation_result_validation = check_validation_result(validation_result)
        outcome = check_validation_consistency(validation_result, validation_result_validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class ValidInconsistentCaseTests(unittest.TestCase):

    def test_02_tampered_validation_status_is_inconsistent(self):
        validation_result = _real_consistent_validation_result()
        genuine = check_validation_result(validation_result)
        tampered = copy.deepcopy(genuine)
        tampered["status"] = "inconsistent"
        tampered["errors"] = ["status_inconsistent_with_errors:consistent"]
        outcome = check_validation_consistency(validation_result, tampered)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(
            any(e.startswith("stage:validation_result_validation:") for e in outcome["errors"]))

    def test_02b_handcrafted_inconsistent_result_with_mismatched_validation(self):
        validation_result = {
            "status": "inconsistent",
            "errors": ["stage:validation_result:mismatched_field:status"],
            "warnings": [],
        }
        genuine = check_validation_result(validation_result)
        self.assertEqual(genuine["status"], "consistent")
        tampered = {"status": "inconsistent", "errors": ["made_up"], "warnings": []}
        outcome = check_validation_consistency(validation_result, tampered)
        self.assertEqual(outcome["status"], "inconsistent")


class InvalidInputCaseTests(unittest.TestCase):

    def test_03_both_arguments_malformed(self):
        outcome = check_validation_consistency("not-a-dict", 42)
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("validation_result_not_a_dict", outcome["errors"])
        self.assertIn("validation_result_validation_not_a_dict", outcome["errors"])


class AgreementBetweenResultAndValidationTests(unittest.TestCase):

    def test_04_genuine_validation_of_a_real_invalid_input_case(self):
        validation_result = check_validation("not-a-dict", 42)
        self.assertEqual(validation_result["status"], "invalid_input")
        validation_result_validation = check_validation_result(validation_result)
        outcome = check_validation_consistency(validation_result, validation_result_validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class DisagreementBetweenResultAndValidationTests(unittest.TestCase):

    def test_05_validation_claims_wrong_errors_list(self):
        validation_result = {"status": "consistent", "errors": [], "warnings": []}
        bad_validation = {"status": "consistent", "errors": ["invented"], "warnings": []}
        outcome = check_validation_consistency(validation_result, bad_validation)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn(
            "stage:validation_result_validation:mismatched_field:errors", outcome["errors"])


class MalformedFirstResultTests(unittest.TestCase):

    def test_06_validation_result_missing_fields(self):
        validation_result = {}
        genuine = check_validation_result(validation_result)
        outcome = check_validation_consistency(validation_result, genuine)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_06b_validation_result_not_a_dict(self):
        outcome = check_validation_consistency(
            None, {"status": "consistent", "errors": [], "warnings": []})
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("validation_result_not_a_dict", outcome["errors"])


class MalformedSecondResultTests(unittest.TestCase):

    def test_07_validation_result_validation_not_a_dict(self):
        validation_result = {"status": "consistent", "errors": [], "warnings": []}
        outcome = check_validation_consistency(validation_result, "not-a-dict")
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("validation_result_validation_not_a_dict", outcome["errors"])

    def test_07b_validation_result_validation_none(self):
        validation_result = {"status": "consistent", "errors": [], "warnings": []}
        outcome = check_validation_consistency(validation_result, None)
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("validation_result_validation_not_a_dict", outcome["errors"])


class MissingInputsTests(unittest.TestCase):

    def test_08_both_none(self):
        outcome = check_validation_consistency(None, None)
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("validation_result_not_a_dict", outcome["errors"])
        self.assertIn("validation_result_validation_not_a_dict", outcome["errors"])


class WrongInputTypesTests(unittest.TestCase):

    def test_09_validation_result_wrong_type_list(self):
        outcome = check_validation_consistency(
            [], {"status": "consistent", "errors": [], "warnings": []})
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("validation_result_not_a_dict", outcome["errors"])

    def test_09b_validation_result_validation_wrong_type_int(self):
        validation_result = {"status": "consistent", "errors": [], "warnings": []}
        outcome = check_validation_consistency(validation_result, 7)
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("validation_result_validation_not_a_dict", outcome["errors"])

    def test_09c_validation_result_wrong_type_string(self):
        outcome = check_validation_consistency(
            "nope", {"status": "consistent", "errors": [], "warnings": []})
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("validation_result_not_a_dict", outcome["errors"])


class InvalidNestedStructuresTests(unittest.TestCase):

    def test_10_validation_result_errors_not_a_list(self):
        validation_result = {"status": "consistent", "errors": "oops", "warnings": []}
        genuine = check_validation_result(validation_result)
        outcome = check_validation_consistency(validation_result, genuine)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_10b_validation_result_validation_errors_not_a_list(self):
        validation_result = {"status": "consistent", "errors": [], "warnings": []}
        bad_validation = {"status": "consistent", "errors": "oops", "warnings": []}
        outcome = check_validation_consistency(validation_result, bad_validation)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn(
            "stage:validation_result_validation:mismatched_field:errors", outcome["errors"])


class ContradictoryStatusValuesTests(unittest.TestCase):

    def test_11_validation_claims_invalid_input_when_actually_consistent(self):
        validation_result = {"status": "consistent", "errors": [], "warnings": []}
        bad_validation = {"status": "invalid_input", "errors": [], "warnings": []}
        outcome = check_validation_consistency(validation_result, bad_validation)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn(
            "stage:validation_result_validation:mismatched_field:status", outcome["errors"])

    def test_11b_validation_claims_consistent_when_actually_inconsistent(self):
        validation_result = {"status": 42, "errors": [], "warnings": []}
        genuine = check_validation_result(validation_result)
        self.assertEqual(genuine["status"], "inconsistent")
        bad_validation = {"status": "consistent", "errors": [], "warnings": []}
        outcome = check_validation_consistency(validation_result, bad_validation)
        self.assertEqual(outcome["status"], "inconsistent")


class ContradictoryErrorInformationTests(unittest.TestCase):

    def test_12_validation_evidence_missing_a_real_finding(self):
        validation_result = {"status": 42, "errors": [], "warnings": []}
        genuine = check_validation_result(validation_result)
        self.assertIn("invalid_status", genuine["errors"])
        bad_validation = {"status": genuine["status"], "errors": [], "warnings": []}
        outcome = check_validation_consistency(validation_result, bad_validation)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn(
            "stage:validation_result_validation:mismatched_field:errors", outcome["errors"])


class ContradictoryEvidenceTests(unittest.TestCase):

    def test_13_validation_fabricates_a_warning(self):
        validation_result = {"status": "consistent", "errors": [], "warnings": []}
        genuine = check_validation_result(validation_result)
        bad_validation = copy.deepcopy(genuine)
        bad_validation["warnings"] = ["a_fabricated_warning"]
        outcome = check_validation_consistency(validation_result, bad_validation)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn(
            "stage:validation_result_validation:mismatched_field:warnings", outcome["errors"])

    def test_13b_validation_drops_a_genuine_error(self):
        validation_result = {"status": "consistent", "errors": ["invented"], "warnings": []}
        genuine = check_validation_result(validation_result)
        self.assertTrue(len(genuine["errors"]) > 0)
        bad_validation = {"status": genuine["status"], "errors": [], "warnings": []}
        outcome = check_validation_consistency(validation_result, bad_validation)
        self.assertEqual(outcome["status"], "inconsistent")


class ZeroDataSafeBehaviorTests(unittest.TestCase):

    def test_14_empty_dicts_on_both_sides(self):
        genuine = check_validation_result({})
        outcome = check_validation_consistency({}, genuine)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_14b_empty_lists_are_rejected_as_wrong_type(self):
        outcome = check_validation_consistency([], [])
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("validation_result_not_a_dict", outcome["errors"])
        self.assertIn("validation_result_validation_not_a_dict", outcome["errors"])


class DeterministicOutputTests(unittest.TestCase):

    def test_15_deterministic_on_consistent_case(self):
        validation_result = _real_consistent_validation_result()
        validation_result_validation = check_validation_result(validation_result)
        first = check_validation_consistency(validation_result, validation_result_validation)
        second = check_validation_consistency(validation_result, validation_result_validation)
        self.assertEqual(first, second)

    def test_15b_deterministic_on_inconsistent_case(self):
        validation_result = {"status": "consistent", "errors": [], "warnings": []}
        bad_validation = {"status": "inconsistent", "errors": ["x"], "warnings": []}
        first = check_validation_consistency(validation_result, bad_validation)
        second = check_validation_consistency(validation_result, bad_validation)
        self.assertEqual(first, second)

    def test_15c_deterministic_on_invalid_input_case(self):
        first = check_validation_consistency(None, None)
        second = check_validation_consistency(None, None)
        self.assertEqual(first, second)


class NeverMutatesInputsTests(unittest.TestCase):

    def test_16_inputs_are_not_mutated_on_consistent_case(self):
        validation_result = _real_consistent_validation_result()
        validation_result_validation = check_validation_result(validation_result)
        result_before = copy.deepcopy(validation_result)
        validation_before = copy.deepcopy(validation_result_validation)
        check_validation_consistency(validation_result, validation_result_validation)
        self.assertEqual(validation_result, result_before)
        self.assertEqual(validation_result_validation, validation_before)

    def test_16b_inputs_are_not_mutated_on_inconsistent_case(self):
        validation_result = {"status": "consistent", "errors": [], "warnings": []}
        bad_validation = {"status": "inconsistent", "errors": ["x"], "warnings": []}
        result_before = copy.deepcopy(validation_result)
        validation_before = copy.deepcopy(bad_validation)
        check_validation_consistency(validation_result, bad_validation)
        self.assertEqual(validation_result, result_before)
        self.assertEqual(bad_validation, validation_before)

    def test_16c_inputs_are_not_mutated_on_invalid_input_case(self):
        validation_result = "not-a-dict"
        validation_result_validation = {"status": "consistent", "errors": [], "warnings": []}
        validation_before = copy.deepcopy(validation_result_validation)
        check_validation_consistency(validation_result, validation_result_validation)
        self.assertEqual(validation_result_validation, validation_before)


if __name__ == "__main__":
    unittest.main()
