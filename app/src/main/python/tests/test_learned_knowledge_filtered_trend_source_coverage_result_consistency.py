"""
Tests for Prompt 543 - Validate Coverage Result Consistency.

`validate_learned_knowledge_filtered_trend_source_coverage_result_
consistency()` (learning/learned_knowledge_statistics.py) is a small,
deterministic, read-only consistency check between a Prompt 541
filtered trend source coverage result and a Prompt 542 validation
result claimed to describe it. It never calls Prompt 541, 540, or
anything upstream of them, never re-derives coverage from raw
comparisons or a trend summary, and never repairs or mutates either
dict it is given - it recomputes Prompt 542 on the coverage result and
compares that recomputation against the validation result it was
given.

Covers:
    1.  valid coverage + valid validation result
    2.  incomplete coverage + matching validation result
    3.  missing-source state + matching validation
    4.  duplicate-source state + matching validation
    5.  unexpected-source state + matching validation
    6.  ordering-mismatch state + matching validation
    7.  invalid-source state + matching validation
    8.  mismatched state
    9.  invalid "valid" status
    10. invalid "well_formed" status
    11. fabricated validation error
    12. missing required validation error
    13. malformed coverage result
    14. malformed validation result
    15. empty coverage
    16. zero-data coverage
    17. deterministic output

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_coverage_result_consistency -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_statistics import (
    validate_learned_knowledge_filtered_trend_source_coverage_result as check_result,
    validate_learned_knowledge_filtered_trend_source_coverage_result_consistency as check_consistency,
)


# A minimal, fully valid "complete" Prompt 541 result shape, used as a
# base to copy-and-tamper for the cases below (matches the base used by
# the Prompt 542 test suite).
_COMPLETE_RESULT = {
    "valid": True, "well_formed": True, "state": "complete",
    "errors": [], "warnings": [], "coverage": {0: "valid", 1: "valid"},
}


def _tamper(**overrides):
    result = dict(_COMPLETE_RESULT)
    result.update(overrides)
    return result


class ValidCoverageValidValidationTests(unittest.TestCase):
    def test_01_valid_coverage_valid_validation_result(self):
        validation = check_result(_COMPLETE_RESULT)
        outcome = check_consistency(_COMPLETE_RESULT, validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class IncompleteCoverageMatchingValidationTests(unittest.TestCase):
    def test_02_incomplete_coverage_matching_validation(self):
        coverage = _tamper(state="incomplete", valid=False,
                            errors=["inconsistent_comparison_count:1!=2"])
        validation = check_result(coverage)
        self.assertTrue(validation["valid"])
        outcome = check_consistency(coverage, validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class MissingSourceStateMatchingValidationTests(unittest.TestCase):
    def test_03_missing_source_state_matching_validation(self):
        coverage = _tamper(state="missing_source", valid=False,
                            coverage={0: "valid", 1: "missing"})
        validation = check_result(coverage)
        self.assertTrue(validation["valid"])
        outcome = check_consistency(coverage, validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class DuplicateSourceStateMatchingValidationTests(unittest.TestCase):
    def test_04_duplicate_source_state_matching_validation(self):
        coverage = _tamper(state="duplicate_source", valid=False,
                            coverage={0: "valid", 1: "duplicated"})
        validation = check_result(coverage)
        self.assertTrue(validation["valid"])
        outcome = check_consistency(coverage, validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class UnexpectedSourceStateMatchingValidationTests(unittest.TestCase):
    def test_05_unexpected_source_state_matching_validation(self):
        coverage = _tamper(state="unexpected_source", valid=False,
                            coverage={0: "valid", 1: "ordering_mismatch"})
        validation = check_result(coverage)
        self.assertTrue(validation["valid"])
        outcome = check_consistency(coverage, validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class OrderingMismatchStateMatchingValidationTests(unittest.TestCase):
    def test_06_ordering_mismatch_state_matching_validation(self):
        coverage = _tamper(state="ordering_mismatch", valid=False,
                            coverage={0: "valid", 1: "mismatched"})
        validation = check_result(coverage)
        self.assertTrue(validation["valid"])
        outcome = check_consistency(coverage, validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class InvalidSourceStateMatchingValidationTests(unittest.TestCase):
    def test_07_invalid_source_state_matching_validation(self):
        coverage = _tamper(state="invalid_source", valid=False,
                            coverage={0: "valid", 1: "invalid_source"})
        validation = check_result(coverage)
        self.assertTrue(validation["valid"])
        outcome = check_consistency(coverage, validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class MismatchedStateTests(unittest.TestCase):
    def test_08_validation_result_disagrees_with_actual_state(self):
        # The coverage result itself is internally contradictory
        # (state "complete" but a "missing" position present), so
        # Prompt 542 would report it invalid - but the caller's
        # validation result claims it is fully valid.
        coverage = _tamper(coverage={0: "valid", 1: "missing"})
        false_validation = {"valid": True, "errors": [], "warnings": []}
        outcome = check_consistency(coverage, false_validation)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("valid_mismatch:expected=False,actual=True", outcome["errors"])
        self.assertIn("missing_error:state_inconsistent_with_coverage:complete", outcome["errors"])


class InvalidValidStatusTests(unittest.TestCase):
    def test_09_validation_result_valid_wrong_type(self):
        validation = {"valid": "yes", "errors": [], "warnings": []}
        outcome = check_consistency(_COMPLETE_RESULT, validation)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("validation_result_invalid_type:valid", outcome["errors"])

    def test_09b_validation_result_valid_wrong_value(self):
        validation = {"valid": False, "errors": [], "warnings": []}
        outcome = check_consistency(_COMPLETE_RESULT, validation)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("valid_mismatch:expected=True,actual=False", outcome["errors"])


class InvalidWellFormedStatusTests(unittest.TestCase):
    def test_10_coverage_well_formed_wrong_type_reflected(self):
        coverage = _tamper(well_formed="yes")
        expected = check_result(coverage)
        self.assertFalse(expected["valid"])
        # A validation result claiming this is fully valid mismatches.
        false_validation = {"valid": True, "errors": [], "warnings": []}
        outcome = check_consistency(coverage, false_validation)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("valid_mismatch:expected=False,actual=True", outcome["errors"])
        self.assertIn("missing_error:invalid_type:well_formed", outcome["errors"])

    def test_10b_coverage_well_formed_wrong_type_matching_validation_consistent(self):
        coverage = _tamper(well_formed="yes")
        validation = check_result(coverage)
        outcome = check_consistency(coverage, validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class FabricatedValidationErrorTests(unittest.TestCase):
    def test_11_fabricated_error_detected(self):
        validation = check_result(_COMPLETE_RESULT)
        tampered_validation = dict(validation)
        tampered_validation["errors"] = list(validation["errors"]) + ["made_up_problem"]
        tampered_validation["valid"] = False
        outcome = check_consistency(_COMPLETE_RESULT, tampered_validation)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("fabricated_error:made_up_problem", outcome["errors"])
        self.assertIn("valid_mismatch:expected=True,actual=False", outcome["errors"])


class MissingRequiredValidationErrorTests(unittest.TestCase):
    def test_12_missing_required_error_detected(self):
        coverage = _tamper(coverage={0: "valid", 1: "missing"})
        real_errors = check_result(coverage)["errors"]
        self.assertTrue(real_errors)
        stripped_validation = {"valid": False, "errors": [], "warnings": []}
        outcome = check_consistency(coverage, stripped_validation)
        self.assertEqual(outcome["status"], "inconsistent")
        for code in real_errors:
            self.assertIn("missing_error:%s" % code, outcome["errors"])


class MalformedCoverageResultTests(unittest.TestCase):
    def test_13_coverage_result_not_a_dict(self):
        for bad in (None, [], "complete", 5):
            outcome = check_consistency(bad, {"valid": True, "errors": [], "warnings": []})
            self.assertEqual(outcome,
                              {"status": "invalid_input",
                               "errors": ["coverage_result_not_a_dict"], "warnings": []})


class MalformedValidationResultTests(unittest.TestCase):
    def test_14_validation_result_not_a_dict(self):
        for bad in (None, [], "valid", 5):
            outcome = check_consistency(_COMPLETE_RESULT, bad)
            self.assertEqual(outcome,
                              {"status": "invalid_input",
                               "errors": ["validation_result_not_a_dict"], "warnings": []})

    def test_14b_both_sides_malformed(self):
        outcome = check_consistency(None, None)
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("coverage_result_not_a_dict", outcome["errors"])
        self.assertIn("validation_result_not_a_dict", outcome["errors"])


class EmptyCoverageTests(unittest.TestCase):
    def test_15_empty_coverage_consistent(self):
        coverage = {
            "valid": True, "well_formed": True, "state": "complete",
            "errors": [], "warnings": [], "coverage": {},
        }
        validation = check_result(coverage)
        outcome = check_consistency(coverage, validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class ZeroDataCoverageTests(unittest.TestCase):
    def test_16_zero_data_invalid_input_coverage_consistent(self):
        coverage = {
            "valid": False, "well_formed": False, "state": "invalid_input",
            "errors": ["comparisons_not_a_list"], "warnings": [], "coverage": {},
        }
        validation = check_result(coverage)
        outcome = check_consistency(coverage, validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class DeterministicOutputTests(unittest.TestCase):
    def test_17_deterministic_on_consistent_pair(self):
        validation = check_result(_COMPLETE_RESULT)
        self.assertEqual(check_consistency(_COMPLETE_RESULT, validation),
                          check_consistency(_COMPLETE_RESULT, validation))

    def test_17b_deterministic_on_inconsistent_pair(self):
        false_validation = {"valid": False, "errors": [], "warnings": []}
        self.assertEqual(check_consistency(_COMPLETE_RESULT, false_validation),
                          check_consistency(_COMPLETE_RESULT, false_validation))

    def test_17c_does_not_mutate_inputs(self):
        coverage = _tamper(coverage={0: "valid", 1: "missing"})
        validation = check_result(coverage)
        coverage_copy = copy.deepcopy(coverage)
        validation_copy = copy.deepcopy(validation)
        check_consistency(coverage, validation)
        self.assertEqual(coverage, coverage_copy)
        self.assertEqual(validation, validation_copy)

    def test_17d_result_shape_has_exactly_the_expected_keys(self):
        validation = check_result(_COMPLETE_RESULT)
        outcome = check_consistency(_COMPLETE_RESULT, validation)
        self.assertEqual(set(outcome.keys()), {"status", "errors", "warnings"})


if __name__ == "__main__":
    unittest.main()
