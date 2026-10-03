"""
Tests for Prompt 544 - Validate Coverage Validation Chain Integrity.

`validate_learned_knowledge_filtered_trend_source_coverage_chain()`
(learning/learned_knowledge_statistics.py) is a small, deterministic,
read-only integrity check over the full four-stage filtered trend
source coverage validation chain:

    source comparisons -> coverage -> coverage validation
                        -> coverage consistency validation

It adds no detection of its own: it recomputes Prompt 541 on
`comparisons`/`trend_summary`, Prompt 542 on the caller's claimed
coverage result, and Prompt 543 on the caller's claimed coverage result
and coverage validation result - each unchanged - and compares each
recomputation against what the caller claims for that stage, field by
field.

Covers:
    1.  completely valid validation chain
    2.  valid empty/zero-data chain
    3.  missing source comparison
    4.  invalid source comparison
    5.  inconsistent coverage
    6.  inconsistent coverage validation
    7.  inconsistent consistency validation
    8.  mismatched source IDs
    9.  mismatched snapshot IDs
    10. ordering mismatch
    11. missing stage
    12. malformed stage
    13. contradictory validation states
    14. fabricated source information
    15. deterministic output

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_coverage_chain -v
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
    validate_learned_knowledge_filtered_trend_source_coverage as check_coverage,
    validate_learned_knowledge_filtered_trend_source_coverage_result as check_result,
    validate_learned_knowledge_filtered_trend_source_coverage_result_consistency as check_consistency,
    validate_learned_knowledge_filtered_trend_source_coverage_chain as check_chain,
    COMPARISON_DIRECTION,
)

_SMALL = ["evaluation_counts", "rates", "dominant_rejection_reason"]

_INVALID_COMPARISON = {
    "valid": False,
    "direction": COMPARISON_DIRECTION,
    "errors": ["earlier_snapshot_invalid", "later_snapshot_invalid"],
    "invalid_inputs": ["earlier", "later"],
    "earlier_errors": ["snapshot_missing"],
    "later_errors": ["snapshot_missing"],
    "earlier_validation_information": None,
    "later_validation_information": None,
}


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


def _chain_comparisons(specs):
    snaps = _snapshots(specs)
    return snaps, [compare(snaps[i], snaps[i + 1]) for i in range(len(snaps) - 1)]


def _numeric_specs(totals, sections=_SMALL):
    return [(sections, {"accepted": n}) for n in totals]


def _full_chain(comparisons, summary):
    """The genuinely correct claimed result for every stage, built by
    calling Prompt 541/542/543 exactly once each - the same way a
    well-behaved caller would."""
    coverage_result = check_coverage(comparisons, summary)
    coverage_validation_result = check_result(coverage_result)
    consistency_result = check_consistency(coverage_result, coverage_validation_result)
    return coverage_result, coverage_validation_result, consistency_result


class CompletelyValidChainTests(unittest.TestCase):
    def test_01_completely_valid_chain(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        coverage_result, validation_result, consistency_result = _full_chain(comps, summary)
        outcome = check_chain(comps, summary, coverage_result, validation_result, consistency_result)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class ValidEmptyZeroDataChainTests(unittest.TestCase):
    def test_02_empty_trend_chain(self):
        comps = []
        summary = trend([])
        coverage_result, validation_result, consistency_result = _full_chain(comps, summary)
        outcome = check_chain(comps, summary, coverage_result, validation_result, consistency_result)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_02b_none_comparisons_zero_data_chain(self):
        summary = trend([])
        coverage_result, validation_result, consistency_result = _full_chain(None, summary)
        outcome = check_chain(None, summary, coverage_result, validation_result, consistency_result)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class MissingSourceComparisonTests(unittest.TestCase):
    def test_03_missing_source_comparison_reflected_consistently(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        broken = [comps[0], None]
        coverage_result, validation_result, consistency_result = _full_chain(broken, summary)
        self.assertEqual(coverage_result["state"], "missing_source")
        outcome = check_chain(broken, summary, coverage_result, validation_result, consistency_result)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_03b_missing_source_comparison_mismatched_claim(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        broken = [comps[0], None]
        real_coverage = check_coverage(broken, summary)
        fake_coverage = dict(real_coverage)
        fake_coverage["state"] = "complete"
        fake_coverage["valid"] = True
        validation_result = check_result(fake_coverage)
        consistency_result = check_consistency(fake_coverage, validation_result)
        outcome = check_chain(broken, summary, fake_coverage, validation_result, consistency_result)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:coverage:mismatched_field:state", outcome["errors"])
        self.assertIn("stage:coverage:mismatched_field:valid", outcome["errors"])


class InvalidSourceComparisonTests(unittest.TestCase):
    def test_04_invalid_source_comparison_reflected_consistently(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        forced_invalid = copy.deepcopy(comps)
        forced_invalid[0] = _INVALID_COMPARISON
        coverage_result, validation_result, consistency_result = _full_chain(forced_invalid, summary)
        self.assertEqual(coverage_result["state"], "invalid_source")
        outcome = check_chain(
            forced_invalid, summary, coverage_result, validation_result, consistency_result)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_04b_invalid_source_comparison_mismatched_claim(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        forced_invalid = copy.deepcopy(comps)
        forced_invalid[0] = _INVALID_COMPARISON
        real_coverage = check_coverage(forced_invalid, summary)
        fake_coverage = dict(real_coverage)
        fake_coverage["coverage"] = dict(real_coverage["coverage"])
        fake_coverage["coverage"][0] = "valid"
        validation_result = check_result(fake_coverage)
        consistency_result = check_consistency(fake_coverage, validation_result)
        outcome = check_chain(
            forced_invalid, summary, fake_coverage, validation_result, consistency_result)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:coverage:mismatched_field:coverage", outcome["errors"])


class InconsistentCoverageTests(unittest.TestCase):
    def test_05_inconsistent_coverage_extra_position(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        real_coverage = check_coverage(comps, summary)
        fake_coverage = dict(real_coverage)
        fake_coverage["coverage"] = dict(real_coverage["coverage"])
        fake_coverage["coverage"][99] = "valid"
        validation_result = check_result(fake_coverage)
        consistency_result = check_consistency(fake_coverage, validation_result)
        outcome = check_chain(comps, summary, fake_coverage, validation_result, consistency_result)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:coverage:mismatched_field:coverage", outcome["errors"])


class InconsistentCoverageValidationTests(unittest.TestCase):
    def test_06_inconsistent_coverage_validation_fabricated_error(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        coverage_result = check_coverage(comps, summary)
        real_validation = check_result(coverage_result)
        fake_validation = dict(real_validation)
        fake_validation["errors"] = list(real_validation["errors"]) + ["made_up_problem"]
        fake_validation["valid"] = False
        consistency_result = check_consistency(coverage_result, fake_validation)
        outcome = check_chain(
            comps, summary, coverage_result, fake_validation, consistency_result)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:coverage_validation:mismatched_field:errors", outcome["errors"])
        self.assertIn("stage:coverage_validation:mismatched_field:valid", outcome["errors"])


class InconsistentConsistencyValidationTests(unittest.TestCase):
    def test_07_inconsistent_consistency_validation(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        coverage_result, validation_result, _real_consistency = _full_chain(comps, summary)
        fake_consistency = {"status": "consistent", "errors": ["not_real"], "warnings": []}
        outcome = check_chain(
            comps, summary, coverage_result, validation_result, fake_consistency)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:consistency:mismatched_field:errors", outcome["errors"])


class MismatchedSourceIdsTests(unittest.TestCase):
    def test_08_mismatched_source_ids_detected_via_recomputation(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        tampered = copy.deepcopy(comps)
        tampered[2]["later"]["snapshot_id"] = comps[0]["earlier"]["snapshot_id"]
        real_coverage = check_coverage(tampered, summary)
        self.assertEqual(real_coverage["coverage"][2], "mismatched")
        # A caller claiming this tampered chain reads "complete" is
        # caught at the coverage stage, regardless of the id mismatch's
        # exact position.
        fake_coverage = dict(real_coverage)
        fake_coverage["state"] = "complete"
        fake_coverage["valid"] = True
        fake_coverage["errors"] = []
        validation_result = check_result(fake_coverage)
        consistency_result = check_consistency(fake_coverage, validation_result)
        outcome = check_chain(
            tampered, summary, fake_coverage, validation_result, consistency_result)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(any(e.startswith("stage:coverage:mismatched_field:") for e in outcome["errors"]))

    def test_08b_mismatched_source_ids_honestly_reported_stays_consistent(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        tampered = copy.deepcopy(comps)
        tampered[2]["later"]["snapshot_id"] = comps[0]["earlier"]["snapshot_id"]
        coverage_result, validation_result, consistency_result = _full_chain(tampered, summary)
        outcome = check_chain(
            tampered, summary, coverage_result, validation_result, consistency_result)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class MismatchedSnapshotIdsTests(unittest.TestCase):
    def test_09_mismatched_earlier_later_snapshot_relationship(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        tampered = copy.deepcopy(comps)
        tampered[1]["earlier"]["sequence"] = 1
        coverage_result, validation_result, consistency_result = _full_chain(tampered, summary)
        self.assertEqual(coverage_result["coverage"], {0: "valid", 1: "mismatched"})
        outcome = check_chain(
            tampered, summary, coverage_result, validation_result, consistency_result)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_09b_mismatched_snapshot_relationship_dishonestly_claimed(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        tampered = copy.deepcopy(comps)
        tampered[1]["earlier"]["sequence"] = 1
        real_coverage = check_coverage(tampered, summary)
        fake_coverage = dict(real_coverage)
        fake_coverage["coverage"] = dict(real_coverage["coverage"])
        fake_coverage["coverage"][1] = "valid"
        fake_coverage["state"] = "complete"
        fake_coverage["valid"] = True
        fake_coverage["errors"] = []
        validation_result = check_result(fake_coverage)
        consistency_result = check_consistency(fake_coverage, validation_result)
        outcome = check_chain(
            tampered, summary, fake_coverage, validation_result, consistency_result)
        self.assertEqual(outcome["status"], "inconsistent")


class OrderingMismatchTests(unittest.TestCase):
    def test_10_reversed_comparisons_ordering_mismatch(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        reversed_comps = list(reversed(comps))
        coverage_result, validation_result, consistency_result = _full_chain(reversed_comps, summary)
        self.assertFalse(coverage_result["valid"])
        outcome = check_chain(
            reversed_comps, summary, coverage_result, validation_result, consistency_result)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_10b_reversed_comparisons_falsely_claimed_valid(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        reversed_comps = list(reversed(comps))
        real_coverage = check_coverage(reversed_comps, summary)
        fake_coverage = dict(real_coverage)
        fake_coverage["state"] = "complete"
        fake_coverage["valid"] = True
        fake_coverage["errors"] = []
        validation_result = check_result(fake_coverage)
        consistency_result = check_consistency(fake_coverage, validation_result)
        outcome = check_chain(
            reversed_comps, summary, fake_coverage, validation_result, consistency_result)
        self.assertEqual(outcome["status"], "inconsistent")


class MissingStageTests(unittest.TestCase):
    def test_11_missing_trend_summary(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        outcome = check_chain(comps, None, {}, {}, {})
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("trend_summary_not_a_dict", outcome["errors"])

    def test_11b_missing_coverage_result(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        outcome = check_chain(comps, summary, None, {}, {})
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("coverage_result_not_a_dict", outcome["errors"])

    def test_11c_missing_coverage_validation_result(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        coverage_result = check_coverage(comps, summary)
        outcome = check_chain(comps, summary, coverage_result, None, {})
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("coverage_validation_result_not_a_dict", outcome["errors"])

    def test_11d_missing_consistency_result(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        coverage_result = check_coverage(comps, summary)
        validation_result = check_result(coverage_result)
        outcome = check_chain(comps, summary, coverage_result, validation_result, None)
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("consistency_result_not_a_dict", outcome["errors"])

    def test_11e_all_stages_missing(self):
        outcome = check_chain("not-a-list", None, None, None, None)
        self.assertEqual(outcome["status"], "invalid_input")
        for code in ("comparisons_invalid_type", "trend_summary_not_a_dict",
                     "coverage_result_not_a_dict", "coverage_validation_result_not_a_dict",
                     "consistency_result_not_a_dict"):
            self.assertIn(code, outcome["errors"])


class MalformedStageTests(unittest.TestCase):
    def test_12_malformed_coverage_result_missing_fields(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        malformed_coverage = {"valid": True}
        validation_result = check_result(malformed_coverage)
        consistency_result = check_consistency(malformed_coverage, validation_result)
        outcome = check_chain(
            comps, summary, malformed_coverage, validation_result, consistency_result)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(any(e.startswith("stage:coverage:missing_field:") for e in outcome["errors"]))

    def test_12b_malformed_validation_result_wrong_type(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        coverage_result = check_coverage(comps, summary)
        malformed_validation = {"valid": "yes", "errors": [], "warnings": []}
        consistency_result = check_consistency(coverage_result, malformed_validation)
        outcome = check_chain(
            comps, summary, coverage_result, malformed_validation, consistency_result)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:coverage_validation:mismatched_field:valid", outcome["errors"])


class ContradictoryValidationStatesTests(unittest.TestCase):
    def test_13_contradictory_valid_and_state(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        real_coverage = check_coverage([comps[0], None], summary)
        self.assertEqual(real_coverage["state"], "missing_source")
        # The claimed coverage result contradicts itself: state names a
        # real problem but "valid" claims everything is fine.
        contradictory = dict(real_coverage)
        contradictory["valid"] = True
        validation_result = check_result(contradictory)
        self.assertFalse(validation_result["valid"])
        consistency_result = check_consistency(contradictory, validation_result)
        outcome = check_chain(
            [comps[0], None], summary, contradictory, validation_result, consistency_result)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:coverage:mismatched_field:valid", outcome["errors"])


class FabricatedSourceInformationTests(unittest.TestCase):
    def test_14_fabricated_coverage_position(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        real_coverage = check_coverage(comps, summary)
        fabricated = dict(real_coverage)
        fabricated["coverage"] = dict(real_coverage["coverage"])
        fabricated["coverage"][7] = "valid"
        validation_result = check_result(fabricated)
        consistency_result = check_consistency(fabricated, validation_result)
        outcome = check_chain(
            comps, summary, fabricated, validation_result, consistency_result)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:coverage:mismatched_field:coverage", outcome["errors"])

    def test_14b_fabricated_top_level_field(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        coverage_result, validation_result, consistency_result = _full_chain(comps, summary)
        fabricated_validation = dict(validation_result)
        fabricated_validation["made_up_field"] = True
        outcome = check_chain(
            comps, summary, coverage_result, fabricated_validation, consistency_result)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn(
            "stage:coverage_validation:unexpected_field:made_up_field", outcome["errors"])


class DeterministicOutputTests(unittest.TestCase):
    def test_15_deterministic_on_consistent_chain(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        coverage_result, validation_result, consistency_result = _full_chain(comps, summary)
        first = check_chain(comps, summary, coverage_result, validation_result, consistency_result)
        second = check_chain(comps, summary, coverage_result, validation_result, consistency_result)
        self.assertEqual(first, second)

    def test_15b_deterministic_on_inconsistent_chain(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        coverage_result = check_coverage(comps, summary)
        fake_validation = {"valid": False, "errors": ["bogus"], "warnings": []}
        consistency_result = check_consistency(coverage_result, fake_validation)
        first = check_chain(comps, summary, coverage_result, fake_validation, consistency_result)
        second = check_chain(comps, summary, coverage_result, fake_validation, consistency_result)
        self.assertEqual(first, second)

    def test_15c_does_not_mutate_inputs(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        coverage_result, validation_result, consistency_result = _full_chain(comps, summary)
        comps_copy = copy.deepcopy(comps)
        summary_copy = copy.deepcopy(summary)
        coverage_copy = copy.deepcopy(coverage_result)
        validation_copy = copy.deepcopy(validation_result)
        consistency_copy = copy.deepcopy(consistency_result)
        check_chain(comps, summary, coverage_result, validation_result, consistency_result)
        self.assertEqual(comps, comps_copy)
        self.assertEqual(summary, summary_copy)
        self.assertEqual(coverage_result, coverage_copy)
        self.assertEqual(validation_result, validation_copy)
        self.assertEqual(consistency_result, consistency_copy)

    def test_15d_result_shape_has_exactly_the_expected_keys(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        coverage_result, validation_result, consistency_result = _full_chain(comps, summary)
        outcome = check_chain(comps, summary, coverage_result, validation_result, consistency_result)
        self.assertEqual(set(outcome.keys()), {"status", "errors", "warnings"})


if __name__ == "__main__":
    unittest.main()
