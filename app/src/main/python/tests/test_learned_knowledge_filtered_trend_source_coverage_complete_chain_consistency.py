"""
Tests for Prompt 549 - Validate Complete Coverage Chain Consistency.

`validate_learned_knowledge_filtered_trend_source_coverage_complete_
chain_consistency()` (learning/learned_knowledge_statistics.py) is a
small, deterministic, read-only check that a caller's claimed results
for every link of the complete, eight-stage filtered trend source
coverage validation chain (Prompts 541-548) actually correspond to one
another and to their shared inputs, end to end. It adds no detection
of its own: it recomputes Prompt 544 on the coverage/coverage-
validation/consistency inputs, Prompt 547 on the stage-order inputs,
and Prompt 548 on the stage-order-consistency result - each unchanged
- and compares each recomputation against the caller's claimed result
for that link, field by field.

Covers:
    1.  completely valid full chain
    2.  valid empty/zero-data chain
    3.  missing source stage
    4.  invalid source comparison
    5.  inconsistent coverage
    6.  invalid coverage validation
    7.  inconsistent coverage consistency result
    8.  incorrect stage ordering
    9.  invalid stage-order validation
    10. inconsistent stage-order consistency result
    11. invalid stage-order consistency validation
    12. mismatched source IDs
    13. mismatched snapshot IDs
    14. mismatched comparison IDs
    15. missing intermediate stage
    16. malformed intermediate result
    17. contradictory validation states
    18. fabricated information in a later stage
    19. mixed valid/invalid chain
    20. deterministic output

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency -v
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
    validate_learned_knowledge_filtered_trend_source_coverage_result as check_coverage_result,
    validate_learned_knowledge_filtered_trend_source_coverage_result_consistency as check_coverage_consistency,
    validate_learned_knowledge_filtered_trend_source_coverage_chain as check_chain,
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order as check_order,
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_result as check_order_result,
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_consistency as check_order_consistency,
    validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_consistency_result as check_order_consistency_result,
    validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency as check_complete,
    _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_SEQUENCE as CANONICAL,
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


def _entries(names):
    return [{"stage": name} for name in names]


def _real_coverage_chain(comparisons, summary):
    """The genuinely correct claimed result for the coverage side of
    the chain (541/542/543/544), built the same way a well-behaved
    caller would."""
    coverage_result = check_coverage(comparisons, summary)
    coverage_validation_result = check_coverage_result(coverage_result)
    consistency_result = check_coverage_consistency(coverage_result, coverage_validation_result)
    chain_result = check_chain(
        comparisons, summary, coverage_result, coverage_validation_result, consistency_result)
    return coverage_result, coverage_validation_result, consistency_result, chain_result


def _real_order_chain(names=None):
    """The genuinely correct claimed result for the stage-order side
    of the chain (545/546/547/548), built the same way a well-behaved
    caller would."""
    stages = _entries(list(CANONICAL) if names is None else names)
    order_result = check_order(stages)
    order_result_validation = check_order_result(order_result)
    order_result_consistency = check_order_consistency(
        stages, None, order_result, order_result_validation)
    order_result_consistency_validation = check_order_consistency_result(order_result_consistency)
    return (stages, order_result, order_result_validation,
            order_result_consistency, order_result_consistency_validation)


def _full_valid_call(comparisons, summary, names=None):
    coverage_result, coverage_validation_result, consistency_result, chain_result = (
        _real_coverage_chain(comparisons, summary))
    (stages, order_result, order_result_validation,
     order_result_consistency, order_result_consistency_validation) = _real_order_chain(names)
    return dict(
        comparisons=comparisons, trend_summary=summary,
        coverage_result=coverage_result,
        coverage_validation_result=coverage_validation_result,
        consistency_result=consistency_result,
        chain_result=chain_result,
        chain_stages=stages, stage_order=None,
        order_result=order_result,
        order_result_validation=order_result_validation,
        order_result_consistency=order_result_consistency,
        order_result_consistency_validation=order_result_consistency_validation,
    )


class CompletelyValidFullChainTests(unittest.TestCase):

    def test_01_completely_valid_full_chain(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class ValidEmptyZeroDataChainTests(unittest.TestCase):

    def test_02_empty_trend_chain(self):
        comps = []
        summary = trend([])
        kwargs = _full_valid_call(comps, summary)
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_02b_none_comparisons_zero_data_chain(self):
        summary = trend([])
        kwargs = _full_valid_call(None, summary)
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class MissingSourceStageTests(unittest.TestCase):

    def test_03_missing_source_comparison_reflected_consistently(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        broken = [comps[0], None]
        kwargs = _full_valid_call(broken, summary)
        self.assertEqual(kwargs["coverage_result"]["state"], "missing_source")
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_03b_missing_stage_entry_in_chain_stages(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        names = [n for n in CANONICAL if n != "coverage"]
        kwargs = _full_valid_call(comps, summary, names)
        self.assertEqual(kwargs["order_result"]["state"], "missing_stage")
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class InvalidSourceComparisonTests(unittest.TestCase):

    def test_04_invalid_source_comparison_reflected_consistently(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        broken = [_INVALID_COMPARISON]
        summary = trend(broken)
        kwargs = _full_valid_call(broken, summary)
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})


class InconsistentCoverageTests(unittest.TestCase):

    def test_05_tampered_coverage_result_detected(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        tampered_coverage = dict(kwargs["coverage_result"])
        tampered_coverage["state"] = "invalid_source"
        tampered_coverage["valid"] = False
        kwargs["coverage_result"] = tampered_coverage
        # coverage_validation_result / consistency_result / chain_result
        # deliberately left stale - as originally computed for the
        # genuine (untampered) coverage_result.
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(any(e.startswith("stage:chain:") for e in outcome["errors"]))


class InvalidCoverageValidationTests(unittest.TestCase):

    def test_06_tampered_chain_result_field_detected(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        tampered_chain = dict(kwargs["chain_result"])
        tampered_chain["status"] = "consistent"
        tampered_chain["errors"] = []
        kwargs["chain_result"] = tampered_chain
        # Force an actual coverage_validation problem so recomputed
        # Prompt 544 disagrees with the (falsely clean) claimed chain.
        broken_coverage_validation = dict(kwargs["coverage_validation_result"])
        broken_coverage_validation["valid"] = not broken_coverage_validation["valid"]
        kwargs["coverage_validation_result"] = broken_coverage_validation
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(any(e.startswith("stage:chain:") for e in outcome["errors"]))


class InconsistentCoverageConsistencyResultTests(unittest.TestCase):

    def test_07_tampered_consistency_result_detected(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        tampered_consistency = dict(kwargs["consistency_result"])
        tampered_consistency["status"] = (
            "inconsistent" if tampered_consistency["status"] == "consistent" else "consistent")
        kwargs["consistency_result"] = tampered_consistency
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:chain:mismatched_field:status", outcome["errors"])


class IncorrectStageOrderingTests(unittest.TestCase):

    def test_08_reversed_stage_order_reflected_consistently(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        reversed_names = list(reversed(CANONICAL))
        kwargs = _full_valid_call(comps, summary, reversed_names)
        self.assertEqual(kwargs["order_result"]["state"], "invalid_order")
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_08b_reversed_stage_order_tampered_claim(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        reversed_names = list(reversed(CANONICAL))
        kwargs = _full_valid_call(comps, summary, reversed_names)
        fake_order = dict(kwargs["order_result"])
        fake_order["state"] = "valid"
        fake_order["valid"] = True
        fake_order["errors"] = []
        kwargs["order_result"] = fake_order
        # order_result_validation / order_result_consistency / its own
        # validation deliberately left stale - as originally computed
        # for the genuine (reversed, invalid_order) order_result.
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(
            any(e.startswith("stage:stage_order_consistency:") for e in outcome["errors"]))


class InvalidStageOrderValidationTests(unittest.TestCase):

    def test_09_tampered_order_result_validation_detected(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        tampered_validation = dict(kwargs["order_result_validation"])
        tampered_validation["status"] = "inconsistent"
        tampered_validation["errors"] = ["invented_problem"]
        kwargs["order_result_validation"] = tampered_validation
        kwargs["order_result_consistency"] = check_order_consistency(
            kwargs["chain_stages"], None, kwargs["order_result"], tampered_validation)
        kwargs["order_result_consistency_validation"] = check_order_consistency_result(
            kwargs["order_result_consistency"])
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome, {"status": "consistent", "errors": [], "warnings": []})

    def test_09b_tampered_order_result_validation_stale_downstream_claim(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        tampered_validation = dict(kwargs["order_result_validation"])
        tampered_validation["status"] = "inconsistent"
        tampered_validation["errors"] = ["invented_problem"]
        kwargs["order_result_validation"] = tampered_validation
        # order_result_consistency / its validation left stale (as if
        # recomputed against the honest, untampered validation) so the
        # complete-chain check must flag the mismatch itself.
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(
            any(e.startswith("stage:stage_order_consistency:") for e in outcome["errors"]))


class InconsistentStageOrderConsistencyResultTests(unittest.TestCase):

    def test_10_tampered_order_result_consistency_detected(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        tampered = dict(kwargs["order_result_consistency"])
        tampered["status"] = (
            "inconsistent" if tampered["status"] == "consistent" else "consistent")
        kwargs["order_result_consistency"] = tampered
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:stage_order_consistency:mismatched_field:status", outcome["errors"])


class InvalidStageOrderConsistencyValidationTests(unittest.TestCase):

    def test_11_tampered_final_validation_detected(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        tampered = dict(kwargs["order_result_consistency_validation"])
        tampered["status"] = (
            "inconsistent" if tampered["status"] == "consistent" else "consistent")
        kwargs["order_result_consistency_validation"] = tampered
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn(
            "stage:stage_order_consistency_validation:mismatched_field:status",
            outcome["errors"])


class MismatchedSourceIDsTests(unittest.TestCase):

    def test_12_mismatched_source_ids_in_coverage_detected(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        fake_coverage = copy.deepcopy(kwargs["coverage_result"])
        # Corrupt a per-position coverage category - stands in for a
        # source ID silently swapped for another one.
        if fake_coverage["coverage"]:
            key = next(iter(fake_coverage["coverage"]))
            fake_coverage["coverage"][key] = "invalid_source"
        else:
            fake_coverage["coverage"] = {0: "invalid_source"}
        kwargs["coverage_result"] = fake_coverage
        kwargs["coverage_validation_result"] = check_coverage_result(fake_coverage)
        kwargs["consistency_result"] = check_coverage_consistency(
            fake_coverage, kwargs["coverage_validation_result"])
        kwargs["chain_result"] = check_chain(
            comps, summary, fake_coverage, kwargs["coverage_validation_result"],
            kwargs["consistency_result"])
        # Tamper the claimed chain result so it disagrees with a fresh
        # recomputation over the corrupted coverage.
        fake_chain = dict(kwargs["chain_result"])
        fake_chain["status"] = "consistent"
        fake_chain["errors"] = []
        kwargs["chain_result"] = fake_chain
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(any(e.startswith("stage:chain:") for e in outcome["errors"]))


class MismatchedSnapshotIDsTests(unittest.TestCase):

    def test_13_mismatched_snapshot_identity_detected(self):
        snaps, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        # Splice in a comparison with an unrelated earlier snapshot,
        # simulating a snapshot ID silently replaced.
        other_snaps, other_comps = _chain_comparisons(_numeric_specs([5, 6]))
        spliced = [other_comps[0], comps[1] if len(comps) > 1 else comps[0]]
        kwargs["comparisons"] = spliced
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(any(e.startswith("stage:chain:") for e in outcome["errors"]))


class MismatchedComparisonIDsTests(unittest.TestCase):

    def test_14_reordered_comparisons_detected(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        if len(comps) > 1:
            kwargs["comparisons"] = list(reversed(comps))
            outcome = check_complete(**kwargs)
            self.assertEqual(outcome["status"], "inconsistent")
            self.assertTrue(any(e.startswith("stage:chain:") for e in outcome["errors"]))


class MissingIntermediateStageTests(unittest.TestCase):

    def test_15_chain_result_missing_field(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        stripped = dict(kwargs["chain_result"])
        del stripped["warnings"]
        kwargs["chain_result"] = stripped
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:chain:missing_field:warnings", outcome["errors"])

    def test_15b_order_result_consistency_missing_field(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        stripped = dict(kwargs["order_result_consistency"])
        del stripped["errors"]
        kwargs["order_result_consistency"] = stripped
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:stage_order_consistency:missing_field:errors", outcome["errors"])


class MalformedIntermediateResultTests(unittest.TestCase):

    def test_16_chain_result_not_a_dict(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        kwargs["chain_result"] = "not-a-dict"
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("chain_result_not_a_dict", outcome["errors"])

    def test_16b_order_result_consistency_validation_not_a_dict(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        kwargs["order_result_consistency_validation"] = None
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("order_result_consistency_validation_not_a_dict", outcome["errors"])

    def test_16c_chain_stages_invalid_type(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        kwargs["chain_stages"] = "not-a-list"
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("chain_stages_invalid_type", outcome["errors"])

    def test_16d_comparisons_invalid_type(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        kwargs["comparisons"] = "not-a-list"
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "invalid_input")
        self.assertIn("comparisons_invalid_type", outcome["errors"])

    def test_16e_multiple_malformed_arguments(self):
        outcome = check_complete(
            comparisons="x", trend_summary=None, coverage_result=None,
            coverage_validation_result=None, consistency_result=None, chain_result=None,
            chain_stages="y", stage_order="z", order_result=None,
            order_result_validation=None, order_result_consistency=None,
            order_result_consistency_validation=None)
        self.assertEqual(outcome["status"], "invalid_input")
        for code in (
                "comparisons_invalid_type", "trend_summary_not_a_dict",
                "coverage_result_not_a_dict", "coverage_validation_result_not_a_dict",
                "consistency_result_not_a_dict", "chain_result_not_a_dict",
                "chain_stages_invalid_type", "stage_order_invalid_type",
                "order_result_not_a_dict", "order_result_validation_not_a_dict",
                "order_result_consistency_not_a_dict",
                "order_result_consistency_validation_not_a_dict"):
            self.assertIn(code, outcome["errors"])


class ContradictoryValidationStatesTests(unittest.TestCase):

    def test_17_chain_status_contradicts_evidence(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        broken = dict(kwargs["coverage_validation_result"])
        broken["valid"] = not broken["valid"]
        kwargs["coverage_validation_result"] = broken
        fake_chain = dict(kwargs["chain_result"])
        fake_chain["status"] = "consistent"
        fake_chain["errors"] = []
        kwargs["chain_result"] = fake_chain
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")

    def test_17b_stage_order_consistency_status_contradicts_evidence(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        fake_consistency = dict(kwargs["order_result_consistency"])
        fake_consistency["status"] = "inconsistent"
        fake_consistency["errors"] = ["totally_invented"]
        kwargs["order_result_consistency"] = fake_consistency
        kwargs["order_result_consistency_validation"] = check_order_consistency_result(
            fake_consistency)
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(any(e.startswith("stage:stage_order_consistency:") for e in outcome["errors"]))


class FabricatedInformationInLaterStageTests(unittest.TestCase):

    def test_18_fabricated_error_code_in_final_validation(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        fabricated = dict(kwargs["order_result_consistency_validation"])
        fabricated["errors"] = list(fabricated["errors"]) + ["fabricated_problem"]
        fabricated["status"] = "inconsistent"
        kwargs["order_result_consistency_validation"] = fabricated
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn(
            "stage:stage_order_consistency_validation:mismatched_field:errors",
            outcome["errors"])

    def test_18b_fabricated_field_in_chain_result(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        fabricated = dict(kwargs["chain_result"])
        fabricated["extra_invented_field"] = True
        kwargs["chain_result"] = fabricated
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertIn("stage:chain:unexpected_field:extra_invented_field", outcome["errors"])


class MixedValidInvalidChainTests(unittest.TestCase):

    def test_19_chain_link_valid_order_link_broken(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        # Coverage side left entirely genuine; only the stage-order
        # consistency claim is broken.
        tampered = dict(kwargs["order_result_consistency"])
        tampered["status"] = "invalid_input"
        tampered["errors"] = ["order_result_not_a_dict"]
        kwargs["order_result_consistency"] = tampered
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(
            any(e.startswith("stage:stage_order_consistency:") for e in outcome["errors"]))
        self.assertFalse(any(e.startswith("stage:chain:") for e in outcome["errors"]))

    def test_19b_order_link_valid_chain_link_broken(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        tampered = dict(kwargs["chain_result"])
        tampered["status"] = "invalid_input"
        tampered["errors"] = ["comparisons_invalid_type"]
        kwargs["chain_result"] = tampered
        outcome = check_complete(**kwargs)
        self.assertEqual(outcome["status"], "inconsistent")
        self.assertTrue(any(e.startswith("stage:chain:") for e in outcome["errors"]))
        self.assertFalse(
            any(e.startswith("stage:stage_order_consistency:") for e in outcome["errors"]))


class DeterministicOutputTests(unittest.TestCase):

    def test_20_repeated_calls_equal_valid_chain(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3, 4]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        first = check_complete(**kwargs)
        second = check_complete(**kwargs)
        self.assertEqual(first, second)

    def test_20b_repeated_calls_equal_broken_chain(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        tampered = dict(kwargs["chain_result"])
        tampered["status"] = "consistent"
        tampered["errors"] = []
        kwargs["chain_result"] = tampered
        first = check_complete(**kwargs)
        second = check_complete(**kwargs)
        self.assertEqual(first, second)

    def test_20c_does_not_mutate_inputs(self):
        _, comps = _chain_comparisons(_numeric_specs([1, 2, 3]))
        summary = trend(comps)
        kwargs = _full_valid_call(comps, summary)
        snapshot = copy.deepcopy(kwargs)
        check_complete(**kwargs)
        self.assertEqual(kwargs["coverage_result"], snapshot["coverage_result"])
        self.assertEqual(kwargs["chain_result"], snapshot["chain_result"])
        self.assertEqual(kwargs["order_result_consistency"], snapshot["order_result_consistency"])
        self.assertEqual(
            kwargs["order_result_consistency_validation"],
            snapshot["order_result_consistency_validation"])


if __name__ == "__main__":
    unittest.main()
