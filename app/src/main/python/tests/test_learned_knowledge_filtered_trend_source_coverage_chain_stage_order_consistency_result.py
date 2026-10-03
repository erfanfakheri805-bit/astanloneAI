"""
Tests for Prompt 548 - Validate Stage Order Consistency Result.

`validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_
order_consistency_result()` (learning/learned_knowledge_statistics.py)
is a small, deterministic, read-only STRUCTURAL check over the dict
`validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_
order_consistency()` (Prompt 547) returns. It never recomputes anything
from Prompt 545, 546, or 547's own `chain_stages`/`stage_order`/
`order_result`/`order_result_validation` input - only `result`'s own
fields are read.

Covers:
    1.  valid consistent result
    2.  valid inconsistent result
    3.  valid invalid-input result
    4.  missing required field
    5.  wrong boolean type
    6.  unknown state
    7.  malformed errors
    8.  malformed warnings
    9.  malformed error codes
    10. fabricated inconsistency error
    11. missing required inconsistency error
    12. contradictory "consistent" and state
    13. contradictory "inconsistent" and state
    14. contradictory state and evidence
    15. malformed stage information
    16. malformed source-reference information
    17. empty/zero-data result
    18. deterministic validation output

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_consistency_result -v
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
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_consistency_result as check_result,
    _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_SEQUENCE as CANONICAL,
)


def _entries(names):
    return [{"stage": name} for name in names]


class ValidConsistentResultTests(unittest.TestCase):

    def test_01_real_consistent_result_is_consistent(self):
        stages = _entries(list(CANONICAL))
        order_result = check_order(stages)
        order_validation = check_order_result(order_result)
        chain_result = check_chain(stages, None, order_result, order_validation)
        self.assertEqual(chain_result["status"], "consistent")
        result = check_result(chain_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_01b_handcrafted_consistent_result_is_consistent(self):
        result = check_result({"status": "consistent", "errors": [], "warnings": []})
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class ValidInconsistentResultTests(unittest.TestCase):

    def test_02_real_inconsistent_result_is_consistent(self):
        names = [n for n in CANONICAL if n != "coverage"]
        stages = _entries(names)
        order_result = check_order(stages)
        order_validation = check_order_result(order_result)
        tampered = copy.deepcopy(order_result)
        tampered["state"] = "valid"
        tampered["valid"] = True
        tampered["errors"] = []
        chain_result = check_chain(stages, None, tampered, order_validation)
        self.assertEqual(chain_result["status"], "inconsistent")
        result = check_result(chain_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})


class ValidInvalidInputResultTests(unittest.TestCase):

    def test_03_real_invalid_input_result_is_consistent(self):
        chain_result = check_chain("not-a-list", None, {}, {})
        self.assertEqual(chain_result["status"], "invalid_input")
        result = check_result(chain_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_03b_handcrafted_invalid_input_result_is_consistent(self):
        result = check_result(
            {"status": "invalid_input", "errors": ["order_result_not_a_dict"], "warnings": []})
        self.assertEqual(result["status"], "consistent")


class MissingRequiredFieldTests(unittest.TestCase):

    def test_04_missing_single_field(self):
        result = check_result({"status": "consistent", "errors": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("missing_field:warnings", result["errors"])

    def test_04b_missing_multiple_fields(self):
        result = check_result({"warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("missing_field:status", result["errors"])
        self.assertIn("missing_field:errors", result["errors"])


class WrongBooleanTypeTests(unittest.TestCase):
    """Prompt 547's result has no boolean field of its own; a bool
    given where "status" (a str) is required is the wrong-type probe
    for that field."""

    def test_05_status_given_as_bool_true(self):
        result = check_result({"status": True, "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_status", result["errors"])

    def test_05b_status_given_as_bool_false(self):
        result = check_result({"status": False, "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_status", result["errors"])


class UnknownStateTests(unittest.TestCase):

    def test_06_status_not_in_allowed_set(self):
        result = check_result({"status": "totally_unknown", "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_status", result["errors"])

    def test_06b_status_not_a_string(self):
        result = check_result({"status": 5, "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_status", result["errors"])


class MalformedErrorsTests(unittest.TestCase):

    def test_07_errors_not_a_list(self):
        result = check_result({"status": "consistent", "errors": "oops", "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:errors", result["errors"])

    def test_07b_errors_contains_non_string(self):
        result = check_result({"status": "inconsistent", "errors": [5], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:errors", result["errors"])
        self.assertNotIn("status_inconsistent_with_errors:inconsistent", result["errors"])


class MalformedWarningsTests(unittest.TestCase):

    def test_08_warnings_not_a_list(self):
        result = check_result({"status": "consistent", "errors": [], "warnings": "oops"})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:warnings", result["errors"])

    def test_08b_warnings_contains_non_string(self):
        result = check_result({"status": "consistent", "errors": [], "warnings": [None]})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("invalid_type:warnings", result["errors"])

    def test_08c_any_warning_present_is_fabricated(self):
        result = check_result({"status": "consistent", "errors": [], "warnings": ["something"]})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("fabricated_warning:something", result["errors"])


class MalformedErrorCodesTests(unittest.TestCase):

    def test_09_unrecognized_error_code(self):
        result = check_result(
            {"status": "inconsistent", "errors": ["totally_made_up_code"], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("unrecognized_error_code:totally_made_up_code", result["errors"])


class FabricatedInconsistencyErrorTests(unittest.TestCase):

    def test_10_consistent_status_with_fabricated_error_present(self):
        result = check_result(
            {"status": "consistent",
             "errors": ["stage:order_result:mismatched_field:state"],
             "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("status_inconsistent_with_errors:consistent", result["errors"])


class MissingRequiredInconsistencyErrorTests(unittest.TestCase):

    def test_11_inconsistent_status_with_no_supporting_errors(self):
        result = check_result({"status": "inconsistent", "errors": [], "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("status_inconsistent_with_errors:inconsistent", result["errors"])


class ContradictoryConsistentAndStateTests(unittest.TestCase):

    def test_12_consistent_with_real_mismatch_evidence(self):
        result = check_result(
            {"status": "consistent",
             "errors": ["order_result_not_a_dict"],
             "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("status_inconsistent_with_errors:consistent", result["errors"])


class ContradictoryInconsistentAndStateTests(unittest.TestCase):

    def test_13_inconsistent_with_no_evidence_at_all(self):
        result = check_result({"status": "inconsistent", "errors": [], "warnings": []})
        self.assertIn("status_inconsistent_with_errors:inconsistent", result["errors"])


class ContradictoryStateAndEvidenceTests(unittest.TestCase):

    def test_14_invalid_input_evidence_reported_as_inconsistent(self):
        result = check_result(
            {"status": "inconsistent",
             "errors": ["chain_stages_invalid_type"],
             "warnings": []})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("status_inconsistent_with_errors:inconsistent", result["errors"])

    def test_14b_invalid_input_status_with_no_input_error_present(self):
        result = check_result(
            {"status": "invalid_input",
             "errors": ["stage:order_result:mismatched_field:state"],
             "warnings": []})
        self.assertIn("status_inconsistent_with_errors:invalid_input", result["errors"])


class MalformedStageInformationTests(unittest.TestCase):

    def test_15_empty_field_suffix(self):
        result = check_result(
            {"status": "inconsistent",
             "errors": ["stage:order_result:missing_field:"],
             "warnings": []})
        self.assertIn("malformed_stage_information:stage:order_result:missing_field:",
                       result["errors"])

    def test_15b_empty_field_suffix_other_link(self):
        result = check_result(
            {"status": "inconsistent",
             "errors": ["stage:order_result_validation:unexpected_field:"],
             "warnings": []})
        self.assertIn(
            "malformed_stage_information:stage:order_result_validation:unexpected_field:",
            result["errors"])


class MalformedSourceReferenceInformationTests(unittest.TestCase):

    def test_16_fabricated_source_reference_style_code(self):
        # Mimics a genuine stage-scoped code but with a kind Prompt 547
        # never produces - not part of the fixed vocabulary, so it must
        # be flagged as unrecognized rather than silently accepted.
        result = check_result(
            {"status": "inconsistent",
             "errors": ["stage:order_result:source_reference:coverage"],
             "warnings": []})
        self.assertIn(
            "unrecognized_error_code:stage:order_result:source_reference:coverage",
            result["errors"])

    def test_16b_fabricated_unknown_stage_name(self):
        result = check_result(
            {"status": "inconsistent",
             "errors": ["stage:coverage:mismatched_field:state"],
             "warnings": []})
        self.assertIn(
            "unrecognized_error_code:stage:coverage:mismatched_field:state",
            result["errors"])


class EmptyZeroDataResultTests(unittest.TestCase):

    def test_17_real_empty_chain_consistency_result_is_consistent(self):
        chain_result = check_chain([], None,
                                    check_order([]),
                                    check_order_result(check_order([])))
        result = check_result(chain_result)
        self.assertEqual(result, {"status": "consistent", "errors": [], "warnings": []})

    def test_17b_result_not_a_dict(self):
        for bad in (None, "oops", 5, [], True):
            result = check_result(bad)
            self.assertEqual(result, {"status": "invalid_input",
                                       "errors": ["result_not_a_dict"], "warnings": []})

    def test_17c_empty_dict(self):
        result = check_result({})
        self.assertEqual(result["status"], "inconsistent")
        self.assertIn("missing_field:status", result["errors"])
        self.assertIn("missing_field:errors", result["errors"])
        self.assertIn("missing_field:warnings", result["errors"])


class DeterministicOutputTests(unittest.TestCase):

    def test_18_same_input_produces_equal_result_every_call(self):
        stages = _entries(list(CANONICAL))
        order_result = check_order(stages)
        order_validation = check_order_result(order_result)
        chain_result = check_chain(stages, None, order_result, order_validation)
        first = check_result(chain_result)
        second = check_result(chain_result)
        self.assertEqual(first, second)

    def test_18b_deterministic_across_many_shapes(self):
        shapes = [
            {"status": "consistent", "errors": [], "warnings": []},
            {"status": "inconsistent", "errors": ["totally_made_up"], "warnings": []},
            {"status": "invalid_input", "errors": ["order_result_not_a_dict"], "warnings": []},
            {"status": True, "errors": [], "warnings": []},
            None,
            "not-a-dict",
        ]
        for shape in shapes:
            first = check_result(shape)
            second = check_result(shape)
            self.assertEqual(first, second)


class NeverMutatesInputTests(unittest.TestCase):

    def test_19_result_left_unchanged(self):
        original = {"status": "inconsistent", "errors": ["totally_made_up"], "warnings": ["x"]}
        before = copy.deepcopy(original)
        check_result(original)
        self.assertEqual(original, before)


if __name__ == "__main__":
    unittest.main()
