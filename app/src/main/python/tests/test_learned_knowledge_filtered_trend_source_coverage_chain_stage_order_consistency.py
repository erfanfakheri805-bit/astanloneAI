"""
Tests for Prompt 547 - Validate Stage Order Result Against Source Chain.

`validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_
order_consistency()` (learning/learned_knowledge_statistics.py) is a
small, deterministic, read-only consistency check tying together:

    - `chain_stages`/`stage_order` (the raw stage-sequence description
      a caller supplies to Prompt 545)
    - the Prompt 545 stage-order result a caller claims for it
    - the Prompt 546 result a caller claims for validating that
      Prompt 545 result

It adds no detection of its own: it recomputes Prompt 545 on
`chain_stages`/`stage_order` and Prompt 546 on the caller's claimed
Prompt 545 result - each unchanged - and compares each recomputation
against what the caller claims for that link, field by field.

Covers:
    1.  completely consistent valid chain
    2.  valid empty/zero-data chain
    3.  missing stage mismatch
    4.  duplicate stage mismatch
    5.  unexpected stage mismatch
    6.  invalid-order mismatch
    7.  stage-name mismatch
    8.  source-reference mismatch
    9.  result claims valid while source chain is invalid
    10. validation result disagrees with the stage-order result
    11. missing stage-order result
    12. malformed stage-order result
    13. malformed validation result
    14. fabricated stage information
    15. deterministic output

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_consistency -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_statistics import (
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order as check_order,
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_result as check_order_result,
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_consistency as check_chain,
    _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_SEQUENCE as CANONICAL,
)


def _entries(names):
    return [{"stage": name} for name in names]


def _full_chain(chain_stages, stage_order=None):
    """The genuinely correct claimed result for both links, built by
    calling Prompt 545/546 exactly once each - the same way a
    well-behaved caller would."""
    order_result = check_order(chain_stages, stage_order)
    order_validation = check_order_result(order_result)
    return order_result, order_validation


class CompletelyConsistentValidChainTests(unittest.TestCase):

    def test_01_completely_consistent_valid_chain(self):
        stages = _entries(list(CANONICAL))
        order_result, order_validation = _full_chain(stages)
        outcome = check_chain(stages, None, order_result, order_validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_01b_with_matching_stage_order_metadata(self):
        stages = _entries(list(CANONICAL))
        order_result, order_validation = _full_chain(stages, list(CANONICAL))
        outcome = check_chain(stages, list(CANONICAL), order_result, order_validation)
        self.assertEqual(outcome["status"], "consistent")


class ValidEmptyZeroDataChainTests(unittest.TestCase):

    def test_02_empty_chain_stages(self):
        stages = []
        order_result, order_validation = _full_chain(stages)
        outcome = check_chain(stages, None, order_result, order_validation)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})
        self.assertEqual(order_result["state"], "missing_stage")


class MissingStageMismatchTests(unittest.TestCase):

    def test_03_claimed_result_hides_a_missing_stage(self):
        names = [n for n in CANONICAL if n != "coverage_validation"]
        stages = _entries(names)
        order_result, order_validation = _full_chain(stages)
        tampered = copy.deepcopy(order_result)
        tampered["errors"] = [e for e in tampered["errors"]
                               if not e.startswith("missing_stage:")]
        tampered["state"] = "valid"
        tampered["valid"] = True
        outcome = check_chain(stages, None, tampered, order_validation)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(any(e.startswith("stage:order_result:") for e in outcome["errors"]))


class DuplicateStageMismatchTests(unittest.TestCase):

    def test_04_claimed_result_hides_a_duplicate_stage(self):
        names = ["source_comparisons", "coverage", "coverage",
                 "coverage_validation", "coverage_consistency_validation",
                 "chain_integrity_validation"]
        stages = _entries(names)
        order_result, order_validation = _full_chain(stages)
        tampered = copy.deepcopy(order_result)
        tampered["errors"] = [e for e in tampered["errors"]
                               if not e.startswith("duplicate_stage:")]
        tampered["state"] = "valid"
        tampered["valid"] = True
        outcome = check_chain(stages, None, tampered, order_validation)
        self.assertEqual(outcome["status"], "inconsistent")


class UnexpectedStageMismatchTests(unittest.TestCase):

    def test_05_claimed_result_hides_an_unexpected_stage(self):
        names = list(CANONICAL) + ["bogus_stage"]
        stages = _entries(names)
        order_result, order_validation = _full_chain(stages)
        tampered = copy.deepcopy(order_result)
        tampered["errors"] = [e for e in tampered["errors"]
                               if not e.startswith("unexpected_stage:")]
        tampered["state"] = "valid"
        tampered["valid"] = True
        outcome = check_chain(stages, None, tampered, order_validation)
        self.assertEqual(outcome["status"], "inconsistent")


class InvalidOrderMismatchTests(unittest.TestCase):

    def test_06_claimed_result_hides_a_reversed_chain(self):
        stages = _entries(list(reversed(CANONICAL)))
        order_result, order_validation = _full_chain(stages)
        tampered = copy.deepcopy(order_result)
        tampered["errors"] = [e for e in tampered["errors"]
                               if not e.startswith("invalid_order")]
        tampered["state"] = "valid"
        tampered["valid"] = True
        outcome = check_chain(stages, None, tampered, order_validation)
        self.assertEqual(outcome["status"], "inconsistent")


class StageNameMismatchTests(unittest.TestCase):

    def test_07_claimed_result_renames_a_stage_error(self):
        names = [n for n in CANONICAL if n != "coverage"]
        stages = _entries(names)
        order_result, order_validation = _full_chain(stages)
        tampered = copy.deepcopy(order_result)
        tampered["errors"] = [
            "missing_stage:chain_integrity_validation" if e == "missing_stage:coverage" else e
            for e in tampered["errors"]
        ]
        outcome = check_chain(stages, None, tampered, order_validation)
        self.assertEqual(outcome["status"], "inconsistent")


class SourceReferenceMismatchTests(unittest.TestCase):

    def test_08_claimed_result_hides_a_bad_source_reference(self):
        stages = [
            {"stage": "source_comparisons"},
            {"stage": "coverage", "source": "coverage_validation"},
            {"stage": "coverage_validation"},
            {"stage": "coverage_consistency_validation"},
            {"stage": "chain_integrity_validation"},
        ]
        order_result, order_validation = _full_chain(stages)
        self.assertEqual(order_result["state"], "invalid_order")
        tampered = copy.deepcopy(order_result)
        tampered["errors"] = [e for e in tampered["errors"]
                               if not e.startswith("invalid_order:source_not_before_stage:")]
        tampered["state"] = "valid"
        tampered["valid"] = True
        outcome = check_chain(stages, None, tampered, order_validation)
        self.assertEqual(outcome["status"], "inconsistent")


class ClaimedValidWhileSourceInvalidTests(unittest.TestCase):

    def test_09_claimed_valid_while_source_chain_is_invalid(self):
        names = [n for n in CANONICAL if n != "chain_integrity_validation"]
        stages = _entries(names)
        _, order_validation = _full_chain(stages)
        fabricated_valid = {"valid": True, "state": "valid", "errors": [], "warnings": []}
        outcome = check_chain(stages, None, fabricated_valid,
                               check_order_result(fabricated_valid))
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(any(e.startswith("stage:order_result:") for e in outcome["errors"]))


class ValidationResultDisagreesTests(unittest.TestCase):

    def test_10_validation_result_disagrees_with_stage_order_result(self):
        stages = _entries(list(CANONICAL))
        order_result, order_validation = _full_chain(stages)
        tampered_validation = copy.deepcopy(order_validation)
        tampered_validation["status"] = "inconsistent"
        tampered_validation["errors"] = ["state_inconsistent_with_errors:valid"]
        outcome = check_chain(stages, None, order_result, tampered_validation)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(any(e.startswith("stage:order_result_validation:") for e in outcome["errors"]))


class MissingStageOrderResultTests(unittest.TestCase):

    def test_11_none_order_result_is_invalid_input(self):
        stages = _entries(list(CANONICAL))
        outcome = check_chain(stages, None, None, {"status": "consistent", "errors": [], "warnings": []})
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("order_result_not_a_dict", outcome["errors"])

    def test_11b_none_order_validation_is_invalid_input(self):
        stages = _entries(list(CANONICAL))
        order_result = check_order(stages)
        outcome = check_chain(stages, None, order_result, None)
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("order_result_validation_not_a_dict", outcome["errors"])


class MalformedStageOrderResultTests(unittest.TestCase):

    def test_12_order_result_wrong_type(self):
        stages = _entries(list(CANONICAL))
        outcome = check_chain(stages, None, "not-a-dict",
                               {"status": "consistent", "errors": [], "warnings": []})
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("order_result_not_a_dict", outcome["errors"])

    def test_12b_chain_stages_wrong_type(self):
        outcome = check_chain("not-a-list", None, {}, {})
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("chain_stages_invalid_type", outcome["errors"])

    def test_12c_stage_order_wrong_type(self):
        stages = _entries(list(CANONICAL))
        outcome = check_chain(stages, "not-a-list", {}, {})
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("stage_order_invalid_type", outcome["errors"])


class MalformedValidationResultTests(unittest.TestCase):

    def test_13_order_validation_wrong_type(self):
        stages = _entries(list(CANONICAL))
        order_result = check_order(stages)
        outcome = check_chain(stages, None, order_result, 42)
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("order_result_validation_not_a_dict", outcome["errors"])


class FabricatedStageInformationTests(unittest.TestCase):

    def test_14_fabricated_error_code_in_claimed_result(self):
        stages = _entries(list(CANONICAL))
        order_result, order_validation = _full_chain(stages)
        tampered = copy.deepcopy(order_result)
        tampered["errors"] = list(tampered["errors"]) + ["missing_stage:coverage"]
        tampered["state"] = "missing_stage"
        tampered["valid"] = False
        outcome = check_chain(stages, None, tampered, order_validation)
        self.assertEqual(outcome["status"], "inconsistent")


class DeterministicOutputTests(unittest.TestCase):

    def test_15_deterministic_across_calls(self):
        stages = _entries(list(CANONICAL))
        order_result, order_validation = _full_chain(stages)
        first = check_chain(stages, None, order_result, order_validation)
        second = check_chain(stages, None, order_result, order_validation)
        self.assertEqual(first, second)

    def test_15b_deterministic_on_inconsistent_case(self):
        names = [n for n in CANONICAL if n != "coverage"]
        stages = _entries(names)
        order_result, order_validation = _full_chain(stages)
        tampered = copy.deepcopy(order_result)
        tampered["state"] = "valid"
        tampered["valid"] = True
        tampered["errors"] = []
        first = check_chain(stages, None, tampered, order_validation)
        second = check_chain(stages, None, tampered, order_validation)
        self.assertEqual(first, second)


class NeverMutatesInputsTests(unittest.TestCase):

    def test_16_inputs_are_not_mutated(self):
        stages = _entries(list(CANONICAL))
        order_result, order_validation = _full_chain(stages)
        stages_before = copy.deepcopy(stages)
        order_result_before = copy.deepcopy(order_result)
        order_validation_before = copy.deepcopy(order_validation)
        check_chain(stages, None, order_result, order_validation)
        self.assertEqual(stages, stages_before)
        self.assertEqual(order_result, order_result_before)
        self.assertEqual(order_validation, order_validation_before)


if __name__ == "__main__":
    unittest.main()
