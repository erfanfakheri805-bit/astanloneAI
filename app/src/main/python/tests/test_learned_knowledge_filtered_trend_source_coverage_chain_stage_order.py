"""
Tests for Prompt 545 - Validate Coverage Chain Stage Ordering.

`validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_
order()` (learning/learned_knowledge_statistics.py) is a small,
deterministic, read-only STRUCTURAL check that a caller-supplied
description of the filtered trend source coverage validation chain's
stages - not their values - follows the chain's required logical
order:

    source comparisons -> coverage -> coverage validation
                        -> coverage consistency validation
                        -> chain integrity validation

It never recomputes or compares any Prompt 541/542/543/544 VALUE; it
only checks the "stage"/"source" names a caller attaches to each link
of the chain.

Covers:
    1.  completely valid stage order
    2.  empty/zero-data chain
    3.  missing stage
    4.  unexpected stage
    5.  duplicated stage
    6.  reversed stage order
    7.  skipped middle stage
    8.  stage referencing a later stage
    9.  inconsistent stage identifiers
    10. malformed stage metadata
    11. deterministic validation output

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_coverage_chain_stage_order -v
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_statistics import (
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order as check_order,
    _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_SEQUENCE as CANONICAL,
    _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_STATES as STATES,
)


def _entries(names):
    """Plain `{"stage": <name>}` entries, in the given order, with no
    explicit `"source"`."""
    return [{"stage": name} for name in names]


class TestValidStageOrder(unittest.TestCase):

    def test_completely_valid_stage_order(self):
        result = check_order(_entries(list(CANONICAL)))
        self.assertEqual(result, {
            "valid": True, "state": "valid", "errors": [], "warnings": [],
        })

    def test_valid_with_correct_explicit_sources(self):
        entries = [
            {"stage": "source_comparisons", "source": None},
            {"stage": "coverage", "source": "source_comparisons"},
            {"stage": "coverage_validation", "source": "coverage"},
            {"stage": "coverage_consistency_validation", "source": "coverage_validation"},
            {"stage": "chain_integrity_validation", "source": "coverage_consistency_validation"},
        ]
        result = check_order(entries)
        self.assertTrue(result["valid"])
        self.assertEqual(result["state"], "valid")
        self.assertEqual(result["errors"], [])

    def test_valid_with_matching_stage_order_metadata(self):
        names = list(CANONICAL)
        result = check_order(_entries(names), stage_order=names)
        self.assertTrue(result["valid"])
        self.assertEqual(result["state"], "valid")


class TestEmptyChain(unittest.TestCase):

    def test_empty_chain_is_missing_every_stage(self):
        result = check_order([])
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "missing_stage")
        for name in CANONICAL:
            self.assertIn("missing_stage:%s" % name, result["errors"])

    def test_empty_chain_never_silently_valid(self):
        # Explicit regression: nothing present must never be reported
        # as "nothing required" the way an empty trend is elsewhere -
        # every canonical stage is always required here.
        result = check_order(())
        self.assertNotEqual(result["state"], "valid")


class TestMissingStage(unittest.TestCase):

    def test_missing_single_stage(self):
        names = [n for n in CANONICAL if n != "coverage_validation"]
        result = check_order(_entries(names))
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "missing_stage")
        self.assertIn("missing_stage:coverage_validation", result["errors"])

    def test_missing_last_stage(self):
        names = list(CANONICAL[:-1])
        result = check_order(_entries(names))
        self.assertEqual(result["state"], "missing_stage")
        self.assertIn("missing_stage:chain_integrity_validation", result["errors"])


class TestUnexpectedStage(unittest.TestCase):

    def test_unexpected_stage_present(self):
        names = list(CANONICAL) + ["bogus_stage"]
        result = check_order(_entries(names))
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "unexpected_stage")
        self.assertIn("unexpected_stage:bogus_stage", result["errors"])

    def test_unexpected_stage_replacing_canonical_one(self):
        names = [n if n != "coverage" else "coverage_summary" for n in CANONICAL]
        result = check_order(_entries(names))
        # Both the vanished canonical stage and the unrecognized
        # replacement are reported, even though "missing_stage" wins
        # priority for "state".
        self.assertIn("missing_stage:coverage", result["errors"])
        self.assertIn("unexpected_stage:coverage_summary", result["errors"])


class TestDuplicateStage(unittest.TestCase):

    def test_duplicated_stage(self):
        names = ["source_comparisons", "coverage", "coverage",
                 "coverage_validation", "coverage_consistency_validation",
                 "chain_integrity_validation"]
        result = check_order(_entries(names))
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "duplicate_stage")
        self.assertIn("duplicate_stage:coverage", result["errors"])


class TestReversedStageOrder(unittest.TestCase):

    def test_fully_reversed_order(self):
        names = list(reversed(CANONICAL))
        result = check_order(_entries(names))
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "invalid_order")
        self.assertIn("invalid_order:sequence", result["errors"])

    def test_two_adjacent_stages_swapped(self):
        names = list(CANONICAL)
        names[1], names[2] = names[2], names[1]
        result = check_order(_entries(names))
        self.assertEqual(result["state"], "invalid_order")
        self.assertIn("invalid_order:sequence", result["errors"])


class TestSkippedMiddleStage(unittest.TestCase):

    def test_skipped_middle_stage(self):
        names = ["source_comparisons", "coverage",
                 "coverage_consistency_validation", "chain_integrity_validation"]
        result = check_order(_entries(names))
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "missing_stage")
        self.assertIn("missing_stage:coverage_validation", result["errors"])
        # The stages that are present remain in valid relative order.
        self.assertNotIn("invalid_order:sequence", result["errors"])


class TestStageReferencingLaterStage(unittest.TestCase):

    def test_source_points_to_a_later_stage(self):
        entries = _entries(list(CANONICAL))
        entries[1] = {"stage": "coverage", "source": "chain_integrity_validation"}
        result = check_order(entries)
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "invalid_order")
        self.assertIn("invalid_order:source_not_before_stage:coverage", result["errors"])

    def test_source_points_to_itself(self):
        entries = _entries(list(CANONICAL))
        entries[2] = {"stage": "coverage_validation", "source": "coverage_validation"}
        result = check_order(entries)
        self.assertEqual(result["state"], "invalid_order")
        self.assertIn(
            "invalid_order:source_not_before_stage:coverage_validation", result["errors"])


class TestInconsistentStageIdentifiers(unittest.TestCase):

    def test_identifier_variant_not_recognized(self):
        names = [n if n != "coverage" else "Coverage" for n in CANONICAL]
        result = check_order(_entries(names))
        self.assertFalse(result["valid"])
        self.assertIn("unexpected_stage:Coverage", result["errors"])
        self.assertIn("missing_stage:coverage", result["errors"])

    def test_identifier_with_stray_whitespace_not_recognized(self):
        names = [n if n != "chain_integrity_validation" else "chain_integrity_validation "
                 for n in CANONICAL]
        result = check_order(_entries(names))
        self.assertIn("unexpected_stage:chain_integrity_validation ", result["errors"])
        self.assertIn("missing_stage:chain_integrity_validation", result["errors"])


class TestMalformedStageMetadata(unittest.TestCase):

    def test_chain_stages_not_a_list(self):
        result = check_order("not a list")
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "invalid_input")
        self.assertIn("chain_stages_invalid_type", result["errors"])

    def test_chain_stages_none(self):
        result = check_order(None)
        self.assertEqual(result["state"], "invalid_input")

    def test_entry_not_a_dict(self):
        result = check_order(["coverage"])
        self.assertEqual(result["state"], "invalid_input")
        self.assertIn("invalid_stage_entry:0", result["errors"])

    def test_entry_missing_stage_field(self):
        result = check_order([{"source": None}])
        self.assertEqual(result["state"], "invalid_input")
        self.assertIn("invalid_stage_entry:0", result["errors"])

    def test_entry_stage_not_a_string(self):
        result = check_order([{"stage": 5}])
        self.assertEqual(result["state"], "invalid_input")
        self.assertIn("invalid_stage_entry:0", result["errors"])

    def test_entry_source_wrong_type(self):
        result = check_order([{"stage": "coverage", "source": 5}])
        self.assertEqual(result["state"], "invalid_input")
        self.assertIn("invalid_stage_entry:0", result["errors"])

    def test_stage_order_wrong_type(self):
        result = check_order(_entries(list(CANONICAL)), stage_order="bad")
        self.assertEqual(result["state"], "invalid_input")
        self.assertIn("stage_order_invalid_type", result["errors"])

    def test_stage_order_entry_wrong_type(self):
        result = check_order(_entries(list(CANONICAL)), stage_order=["coverage", 5])
        self.assertEqual(result["state"], "invalid_input")
        self.assertIn("invalid_stage_order_entry:1", result["errors"])

    def test_malformed_input_never_raises_and_reports_all_problems(self):
        result = check_order([{"stage": ""}, "bad_entry"], stage_order=[1, 2])
        self.assertEqual(result["state"], "invalid_input")
        self.assertIn("invalid_stage_entry:0", result["errors"])
        self.assertIn("invalid_stage_entry:1", result["errors"])
        self.assertIn("invalid_stage_order_entry:0", result["errors"])
        self.assertIn("invalid_stage_order_entry:1", result["errors"])


class TestStageOrderMetadataMismatch(unittest.TestCase):

    def test_declared_order_disagrees_with_actual_order(self):
        names = list(CANONICAL)
        result = check_order(_entries(names), stage_order=list(reversed(names)))
        self.assertFalse(result["valid"])
        self.assertEqual(result["state"], "invalid_order")
        self.assertIn("invalid_order:stage_order_metadata_mismatch", result["errors"])


class TestNeverMutatesInputs(unittest.TestCase):

    def test_chain_stages_and_stage_order_left_unchanged(self):
        entries = _entries(list(CANONICAL))
        entries_copy = [dict(entry) for entry in entries]
        order = list(CANONICAL)
        order_copy = list(order)

        check_order(entries, stage_order=order)

        self.assertEqual(entries, entries_copy)
        self.assertEqual(order, order_copy)


class TestDeterministicOutput(unittest.TestCase):

    def test_same_input_produces_equal_result_every_call(self):
        names = list(CANONICAL)
        names[3], names[4] = names[4], names[3]
        entries = _entries(names)

        first = check_order(entries)
        second = check_order(entries)
        third = check_order(entries, stage_order=None)

        self.assertEqual(first, second)
        self.assertEqual(first, third)

    def test_deterministic_across_many_shapes(self):
        cases = [
            [],
            _entries(list(CANONICAL)),
            _entries(list(reversed(CANONICAL))),
            "invalid",
            [{"stage": "coverage"}, {"stage": "coverage"}],
        ]
        for case in cases:
            first = check_order(case)
            second = check_order(case)
            self.assertEqual(first, second)


class TestStatesTuple(unittest.TestCase):

    def test_states_tuple_matches_documented_states(self):
        self.assertEqual(
            set(STATES),
            {"valid", "invalid_order", "missing_stage", "unexpected_stage",
             "duplicate_stage", "invalid_input"},
        )

    def test_result_state_is_always_one_of_the_documented_states(self):
        cases = [
            [],
            _entries(list(CANONICAL)),
            _entries(list(reversed(CANONICAL))),
            "invalid",
            None,
            [{"stage": "coverage"}, {"stage": "coverage"}],
            list(CANONICAL) + ["bogus"],
        ]
        for case in cases:
            result = check_order(case)
            self.assertIn(result["state"], STATES)


if __name__ == "__main__":
    unittest.main()
