"""
Tests for Prompt 511 - Diagnostic Comparison Trend Summary.

`summarize_learned_knowledge_diagnostic_snapshot_comparison_trend()`
(learning/learned_knowledge_statistics.py) is a deterministic, read-only
function over an ORDERED collection of Prompt 509 comparison results.
Every comparison is checked with the existing Prompt 510
`validate_learned_knowledge_diagnostic_snapshot_comparison()` (not
reimplemented); only comparisons that pass are eligible for the numeric
and dominant-rejection-reason trends. It never repairs a comparison,
never mutates anything it is given, assigns no score/rank/quality
judgement to any state, and predicts nothing.

Covers:
    1.  empty comparison history
    2.  one valid comparison
    3.  multiple valid comparisons
    4.  increased numeric metric
    5.  decreased numeric metric
    6.  unchanged numeric metric
    7.  insufficient numeric data
    8.  changed dominant rejection reason
    9.  dominant rejection reason appearing (became_available)
    10. dominant rejection reason disappearing (became_empty)
    11. unchanged dominant rejection reason
    12. changed validation status
    13. unchanged validation status
    14. invalid comparison is handled safely
    15. mixed valid and invalid comparisons
    16. zero-evaluation comparisons
    17. identical comparisons
    18. chronological ordering
    19. deterministic output
    20. input objects are not mutated
    21. regression coverage for Prompts 500-510

Run directly:
    python -m unittest tests.test_learned_knowledge_diagnostic_snapshot_comparison_trend -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_gate import (
    STATUS_PASSED, REASON_OK, REASON_NOT_SELECTED, REASON_NOT_RELEVANT,
    REASON_INSUFFICIENT_RELIABILITY,
    DECISION_REJECTED_IRRELEVANT,
    LearnedKnowledgeGateResult,
    evaluate_learned_knowledge_gate, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    SNAPSHOT_VALIDATION_VALID, SNAPSHOT_VALIDATION_INVALID,
    COMPARISON_DIRECTION,
    CHANGE_UNCHANGED, CHANGE_CHANGED, CHANGE_BECAME_EMPTY, CHANGE_BECAME_AVAILABLE,
    TREND_INCREASED, TREND_DECREASED, TREND_INSUFFICIENT_DATA,
    summarize_learned_knowledge_decisions,
    analyze_learned_knowledge_statistics,
    validate_learned_knowledge_statistics_analysis,
    build_learned_knowledge_analysis_summary,
    compare_learned_knowledge_diagnostic_snapshots as compare,
    validate_learned_knowledge_diagnostic_snapshot_comparison as validate,
    summarize_learned_knowledge_diagnostic_snapshot_comparison_trend as trend,
)

NUMERIC_FIELDS = ["total_evaluations", "accepted_count", "rejected_count",
                  "no_candidate_count", "acceptance_rate", "rejection_rate"]

TOP_LEVEL_KEYS = [
    "valid", "errors", "direction", "total_comparisons", "eligible_count",
    "ineligible_count", "ineligible_comparisons", "chronological_range",
    "numeric", "dominant_rejection_reason", "validation_status",
]


def _trace(status, reason, **numbers):
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(status, reason, **numbers))


ACCEPTED = _trace(STATUS_PASSED, REASON_OK)
IRRELEVANT = _trace("REJECTED", REASON_NOT_RELEVANT)
LOW_RELIABILITY = _trace("REJECTED", REASON_INSUFFICIENT_RELIABILITY)
NO_CANDIDATE = _trace("REJECTED", REASON_NOT_SELECTED)


def _stats(accepted=0, irrelevant=0, low_reliability=0, no_candidate=0):
    stats = LearnedKnowledgeDecisionStatistics()
    for gate_trace, count in ((ACCEPTED, accepted), (IRRELEVANT, irrelevant),
                              (LOW_RELIABILITY, low_reliability), (NO_CANDIDATE, no_candidate)):
        for _ in range(count):
            stats.record(gate_trace)
    return stats


def _history(counts_list):
    """A single real Prompt 508 history with one snapshot per dict in
    `counts_list`, sequences 1..len(counts_list) in order."""
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for counts in counts_list:
        history.record_statistics(_stats(**counts))
    return history


def _chain(counts_list):
    """The Prompt 509 comparisons for every consecutive pair of
    snapshots built from `counts_list`: (1,2), (2,3), ..."""
    history = _history(counts_list)
    return [history.compare_sequences(i, i + 1) for i in range(1, len(counts_list))]


def _pair(earlier_counts, later_counts):
    """A single real, fully valid two-snapshot comparison."""
    return _chain([earlier_counts, later_counts])[0]


def _invalid_status_comparison():
    """A well-formed-shape but Prompt-510-INELIGIBLE comparison: a
    snapshot whose own `validation_status` is `"invalid"` makes the
    comparison touching it fail Prompt 510 validation, even though the
    comparison's own Prompt 509 `valid` is True (comparable=False)."""
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record({}, {"valid": False, "errors": ["boom"]})  # sequence 1, invalid snapshot
    history.record_statistics(_stats(accepted=2))  # sequence 2, valid snapshot
    comparison = history.compare_sequences(1, 2)
    assert validate(comparison)["valid"] is False
    return comparison


def _missing_snapshot_comparison():
    """A Prompt-509 `"valid": False` comparison (a snapshot was simply
    missing) - also Prompt-510-ineligible, via a different code path
    than `_invalid_status_comparison()`."""
    snapshot = _history([{"accepted": 1}]).get_latest()
    comparison = compare(None, snapshot)
    assert comparison["valid"] is False
    assert validate(comparison)["valid"] is False
    return comparison


class Prompt511TestCase(unittest.TestCase):

    def assertResultShape(self, result):
        self.assertEqual(list(result.keys()), TOP_LEVEL_KEYS)
        self.assertIs(result["valid"], True)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["direction"], COMPARISON_DIRECTION)
        self.assertEqual(list(result["numeric"].keys()), NUMERIC_FIELDS)
        for field in NUMERIC_FIELDS:
            self.assertEqual(
                list(result["numeric"][field].keys()), ["state", "start", "end", "delta"])
        self.assertEqual(
            list(result["dominant_rejection_reason"].keys()), ["state", "start", "end"])
        self.assertEqual(
            list(result["validation_status"].keys()), ["state", "start", "end"])
        self.assertEqual(list(result["chronological_range"].keys()), ["earlier", "later"])


# ----------------------------------------------------------------------
# 1. empty comparison history
# ----------------------------------------------------------------------
class TestEmptyHistory(Prompt511TestCase):

    def test_empty_list(self):
        result = trend([])
        self.assertResultShape(result)
        self.assertEqual(result["total_comparisons"], 0)
        self.assertEqual(result["eligible_count"], 0)
        self.assertEqual(result["ineligible_count"], 0)
        self.assertEqual(result["ineligible_comparisons"], [])
        self.assertEqual(result["chronological_range"], {"earlier": None, "later": None})
        for field in NUMERIC_FIELDS:
            self.assertEqual(result["numeric"][field],
                              {"state": TREND_INSUFFICIENT_DATA, "start": None, "end": None, "delta": None})
        self.assertEqual(result["dominant_rejection_reason"],
                          {"state": TREND_INSUFFICIENT_DATA, "start": None, "end": None})
        self.assertEqual(result["validation_status"],
                          {"state": TREND_INSUFFICIENT_DATA, "start": None, "end": None})

    def test_none_is_treated_as_empty(self):
        self.assertEqual(trend(None), trend([]))


# ----------------------------------------------------------------------
# 2/3. one valid comparison / multiple valid comparisons
# ----------------------------------------------------------------------
class TestValidComparisons(Prompt511TestCase):

    def test_one_valid_comparison(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 3}])
        result = trend(comparisons)
        self.assertResultShape(result)
        self.assertEqual(result["total_comparisons"], 1)
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["ineligible_count"], 0)
        self.assertEqual(result["numeric"]["accepted_count"],
                          {"state": TREND_INCREASED, "start": 1, "end": 3, "delta": 2})

    def test_multiple_valid_comparisons(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}, {"accepted": 4}, {"accepted": 7}])
        result = trend(comparisons)
        self.assertResultShape(result)
        self.assertEqual(result["total_comparisons"], 3)
        self.assertEqual(result["eligible_count"], 3)
        self.assertEqual(result["ineligible_count"], 0)
        # start = earliest eligible's "earlier" (1), end = latest eligible's "later" (7)
        self.assertEqual(result["numeric"]["accepted_count"],
                          {"state": TREND_INCREASED, "start": 1, "end": 7, "delta": 6})

    def test_chronological_range_identifies_the_endpoints(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}, {"accepted": 4}])
        result = trend(comparisons)
        self.assertEqual(result["chronological_range"]["earlier"],
                          {"snapshot_id": "learned_knowledge_snapshot_000001", "sequence": 1})
        self.assertEqual(result["chronological_range"]["later"],
                          {"snapshot_id": "learned_knowledge_snapshot_000003", "sequence": 3})


# ----------------------------------------------------------------------
# 4/5/6/7. numeric metric states
# ----------------------------------------------------------------------
class TestNumericStates(Prompt511TestCase):

    def test_increased(self):
        result = trend([_pair({"accepted": 1}, {"accepted": 5})])
        self.assertEqual(result["numeric"]["accepted_count"]["state"], TREND_INCREASED)

    def test_decreased(self):
        result = trend([_pair({"accepted": 5}, {"accepted": 1})])
        self.assertEqual(result["numeric"]["accepted_count"]["state"], TREND_DECREASED)

    def test_unchanged(self):
        result = trend([_pair({"accepted": 3}, {"accepted": 3})])
        self.assertEqual(result["numeric"]["accepted_count"],
                          {"state": CHANGE_UNCHANGED, "start": 3, "end": 3, "delta": 0})

    def test_insufficient_data_with_no_eligible_comparisons(self):
        result = trend([_invalid_status_comparison()])
        for field in NUMERIC_FIELDS:
            self.assertEqual(result["numeric"][field]["state"], TREND_INSUFFICIENT_DATA)
            self.assertIsNone(result["numeric"][field]["start"])
            self.assertIsNone(result["numeric"][field]["end"])
            self.assertIsNone(result["numeric"][field]["delta"])

    def test_rate_fields_use_the_same_states(self):
        result = trend([_pair({"accepted": 1, "irrelevant": 1}, {"accepted": 3})])
        # acceptance_rate: 0.5 -> 1.0 (increased); rejection_rate: 0.5 -> 0.0 (decreased)
        self.assertEqual(result["numeric"]["acceptance_rate"]["state"], TREND_INCREASED)
        self.assertEqual(result["numeric"]["rejection_rate"]["state"], TREND_DECREASED)


# ----------------------------------------------------------------------
# 8/9/10/11. dominant rejection reason states
# ----------------------------------------------------------------------
class TestDominantRejectionReasonStates(Prompt511TestCase):

    def test_changed(self):
        result = trend([_pair({"irrelevant": 2}, {"low_reliability": 2})])
        entry = result["dominant_rejection_reason"]
        self.assertEqual(entry["state"], CHANGE_CHANGED)
        self.assertEqual(entry["start"], DECISION_REJECTED_IRRELEVANT)

    def test_became_available(self):
        result = trend([_pair({"accepted": 1}, {"irrelevant": 2})])
        self.assertEqual(result["dominant_rejection_reason"],
                          {"state": CHANGE_BECAME_AVAILABLE, "start": None,
                           "end": DECISION_REJECTED_IRRELEVANT})

    def test_became_empty(self):
        result = trend([_pair({"irrelevant": 2}, {"accepted": 1})])
        self.assertEqual(result["dominant_rejection_reason"],
                          {"state": CHANGE_BECAME_EMPTY, "start": DECISION_REJECTED_IRRELEVANT,
                           "end": None})

    def test_unchanged(self):
        result = trend([_pair({"irrelevant": 2}, {"irrelevant": 6})])
        entry = result["dominant_rejection_reason"]
        self.assertEqual(entry["state"], CHANGE_UNCHANGED)
        self.assertEqual(entry["start"], entry["end"])

    def test_missing_optional_categorical_value_both_sides_none(self):
        result = trend([_pair({"accepted": 1}, {"accepted": 4})])
        self.assertEqual(result["dominant_rejection_reason"],
                          {"state": CHANGE_UNCHANGED, "start": None, "end": None})

    def test_endpoint_anchoring_ignores_a_middle_fluctuation(self):
        # started with no dominant reason, ended with no dominant reason,
        # even though the middle snapshot had one - the trend is a
        # start-vs-end reading, not a fluctuation count.
        comparisons = _chain([{"accepted": 1}, {"irrelevant": 3}, {"accepted": 1}])
        result = trend(comparisons)
        self.assertEqual(result["dominant_rejection_reason"]["state"], CHANGE_UNCHANGED)


# ----------------------------------------------------------------------
# 12/13. validation status states
# ----------------------------------------------------------------------
class TestValidationStatusStates(Prompt511TestCase):

    def test_unchanged_when_every_comparison_is_eligible(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}, {"accepted": 3}])
        result = trend(comparisons)
        self.assertEqual(result["validation_status"],
                          {"state": CHANGE_UNCHANGED,
                           "start": SNAPSHOT_VALIDATION_VALID, "end": SNAPSHOT_VALIDATION_VALID})

    def test_unchanged_when_every_comparison_is_ineligible(self):
        result = trend([_invalid_status_comparison(), _invalid_status_comparison()])
        self.assertEqual(result["validation_status"],
                          {"state": CHANGE_UNCHANGED,
                           "start": SNAPSHOT_VALIDATION_INVALID, "end": SNAPSHOT_VALIDATION_INVALID})

    def test_changed_from_invalid_to_valid(self):
        comparisons = [_invalid_status_comparison()] + _chain([{"accepted": 1}, {"accepted": 2}])
        result = trend(comparisons)
        self.assertEqual(result["validation_status"],
                          {"state": CHANGE_CHANGED,
                           "start": SNAPSHOT_VALIDATION_INVALID, "end": SNAPSHOT_VALIDATION_VALID})

    def test_changed_from_valid_to_invalid(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}]) + [_invalid_status_comparison()]
        result = trend(comparisons)
        self.assertEqual(result["validation_status"],
                          {"state": CHANGE_CHANGED,
                           "start": SNAPSHOT_VALIDATION_VALID, "end": SNAPSHOT_VALIDATION_INVALID})


# ----------------------------------------------------------------------
# 14/15. invalid comparisons handled safely / mixed valid+invalid
# ----------------------------------------------------------------------
class TestInvalidComparisons(Prompt511TestCase):

    def test_single_invalid_comparison_is_reported_not_repaired(self):
        bad = _invalid_status_comparison()
        result = trend([bad])
        self.assertResultShape(result)
        self.assertEqual(result["total_comparisons"], 1)
        self.assertEqual(result["eligible_count"], 0)
        self.assertEqual(result["ineligible_count"], 1)
        self.assertEqual(result["ineligible_comparisons"],
                          [{"index": 0, "errors": validate(bad)["errors"]}])

    def test_missing_snapshot_comparison_is_also_reported(self):
        bad = _missing_snapshot_comparison()
        result = trend([bad])
        self.assertEqual(result["eligible_count"], 0)
        self.assertEqual(result["ineligible_count"], 1)
        self.assertEqual(result["ineligible_comparisons"][0]["index"], 0)
        self.assertTrue(result["ineligible_comparisons"][0]["errors"])

    def test_non_dict_comparisons_are_safely_ineligible(self):
        for bad in (None, "not a comparison", 42, [], object()):
            result = trend([bad])
            self.assertEqual(result["eligible_count"], 0)
            self.assertEqual(result["ineligible_count"], 1)
            self.assertIn("comparison_not_a_dict", result["ineligible_comparisons"][0]["errors"])

    def test_mixed_valid_and_invalid_preserves_positions(self):
        good = _chain([{"accepted": 1}, {"accepted": 5}])[0]
        bad = _invalid_status_comparison()
        result = trend([bad, good, bad])
        self.assertEqual(result["total_comparisons"], 3)
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["ineligible_count"], 2)
        self.assertEqual([entry["index"] for entry in result["ineligible_comparisons"]], [0, 2])
        # the lone eligible comparison still drives the numeric trend
        self.assertEqual(result["numeric"]["accepted_count"],
                          {"state": TREND_INCREASED, "start": 1, "end": 5, "delta": 4})

    def test_mixed_ineligible_at_the_edges_does_not_shift_the_numeric_anchor(self):
        good_chain = _chain([{"accepted": 1}, {"accepted": 2}, {"accepted": 9}])
        bad = _invalid_status_comparison()
        result = trend([bad] + good_chain + [bad])
        self.assertEqual(result["eligible_count"], 2)
        self.assertEqual(result["ineligible_count"], 2)
        self.assertEqual(result["numeric"]["accepted_count"]["start"], 1)
        self.assertEqual(result["numeric"]["accepted_count"]["end"], 9)


# ----------------------------------------------------------------------
# 16. zero-evaluation comparisons
# ----------------------------------------------------------------------
class TestZeroEvaluationComparisons(Prompt511TestCase):

    def test_zero_to_zero(self):
        result = trend([_pair({}, {})])
        self.assertEqual(result["numeric"]["total_evaluations"],
                          {"state": CHANGE_UNCHANGED, "start": 0, "end": 0, "delta": 0})
        for field in ("acceptance_rate", "rejection_rate"):
            self.assertEqual(result["numeric"][field]["start"], 0.0)
            self.assertEqual(result["numeric"][field]["end"], 0.0)
        self.assertEqual(result["dominant_rejection_reason"],
                          {"state": CHANGE_UNCHANGED, "start": None, "end": None})

    def test_zero_to_nonzero(self):
        result = trend([_pair({}, {"accepted": 2})])
        self.assertEqual(result["numeric"]["total_evaluations"]["state"], TREND_INCREASED)
        self.assertEqual(result["numeric"]["acceptance_rate"]["state"], TREND_INCREASED)


# ----------------------------------------------------------------------
# 17. identical comparisons
# ----------------------------------------------------------------------
class TestIdenticalComparisons(Prompt511TestCase):

    def test_repeated_identical_snapshots(self):
        comparisons = _chain([{"accepted": 2, "irrelevant": 1}] * 4)
        self.assertTrue(all(c["identical"] for c in comparisons))
        result = trend(comparisons)
        self.assertEqual(result["eligible_count"], 3)
        for field in NUMERIC_FIELDS:
            self.assertEqual(result["numeric"][field]["state"], CHANGE_UNCHANGED)
        self.assertEqual(result["dominant_rejection_reason"]["state"], CHANGE_UNCHANGED)
        self.assertEqual(result["validation_status"]["state"], CHANGE_UNCHANGED)


# ----------------------------------------------------------------------
# 18. chronological ordering
# ----------------------------------------------------------------------
class TestChronologicalOrdering(Prompt511TestCase):

    def test_order_is_preserved_not_resorted(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 4}, {"accepted": 9}])
        forward = trend(comparisons)
        reversed_result = trend(list(reversed(comparisons)))
        # reversing the caller's order changes which comparison is
        # "first eligible" / "last eligible" - this function trusts the
        # given order rather than re-deriving it from sequence numbers,
        # so the reversed list reads the anchors from different
        # comparisons (first eligible's earlier=4, last eligible's
        # later=4) rather than mechanically flipping the forward result.
        self.assertEqual(forward["numeric"]["accepted_count"],
                          {"state": TREND_INCREASED, "start": 1, "end": 9, "delta": 8})
        self.assertEqual(reversed_result["numeric"]["accepted_count"],
                          {"state": CHANGE_UNCHANGED, "start": 4, "end": 4, "delta": 0})

    def test_ineligible_index_matches_original_position(self):
        good = _chain([{"accepted": 1}, {"accepted": 2}])[0]
        bad = _invalid_status_comparison()
        result = trend([good, good, bad, good])
        self.assertEqual([e["index"] for e in result["ineligible_comparisons"]], [2])


# ----------------------------------------------------------------------
# 19. deterministic output
# ----------------------------------------------------------------------
class TestDeterministicOutput(Prompt511TestCase):

    def test_same_input_same_output(self):
        comparisons = _chain([{"accepted": 1, "irrelevant": 1}, {"accepted": 3},
                               {"accepted": 3, "low_reliability": 2}])
        first = trend(comparisons)
        second = trend(copy.deepcopy(comparisons))
        self.assertEqual(first, second)

    def test_repeated_calls_are_stable(self):
        comparisons = [_invalid_status_comparison()] + _chain([{"accepted": 1}, {"accepted": 4}])
        results = [trend(comparisons) for _ in range(5)]
        for result in results[1:]:
            self.assertEqual(result, results[0])


# ----------------------------------------------------------------------
# 20. input objects are not mutated
# ----------------------------------------------------------------------
class TestNoMutation(Prompt511TestCase):

    def test_comparisons_are_untouched(self):
        comparisons = _chain([{"accepted": 1, "irrelevant": 1}, {"accepted": 4},
                               {"low_reliability": 2}])
        comparisons.append(_invalid_status_comparison())
        before = copy.deepcopy(comparisons)
        trend(comparisons)
        self.assertEqual(comparisons, before)

    def test_returned_chronological_range_is_independent(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}])
        result = trend(comparisons)
        result["chronological_range"]["earlier"]["sequence"] = 999
        result2 = trend(comparisons)
        self.assertNotEqual(result2["chronological_range"]["earlier"]["sequence"], 999)

    def test_original_list_object_is_not_the_returned_list(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 2}])
        result = trend(comparisons)
        result["ineligible_comparisons"].append({"index": 999, "errors": []})
        result2 = trend(comparisons)
        self.assertEqual(result2["ineligible_comparisons"], [])


# ----------------------------------------------------------------------
# 21. regression coverage for Prompts 500-510
# ----------------------------------------------------------------------
class TestRegressionPrompts500Through510(unittest.TestCase):

    def test_gate_and_statistics_unaffected(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED)
        stats.record(IRRELEVANT)
        summary = stats.summary()
        self.assertEqual(summary["total_evaluations"], 2)
        self.assertEqual(summary["total_accepted"], 1)

    def test_summarize_learned_knowledge_decisions_unaffected(self):
        summary = summarize_learned_knowledge_decisions([ACCEPTED, ACCEPTED, LOW_RELIABILITY])
        self.assertEqual(summary["total_accepted"], 2)
        self.assertEqual(summary["total_rejected"], 1)

    def test_analysis_validation_and_summary_chain_unaffected(self):
        stats = LearnedKnowledgeDecisionStatistics()
        for gate_trace in (ACCEPTED, ACCEPTED, IRRELEVANT):
            stats.record(gate_trace)
        analysis = analyze_learned_knowledge_statistics(stats)
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertTrue(validation["valid"])
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["accepted_count"], 2)

    def test_snapshot_history_record_and_retrieve_unaffected(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_stats(accepted=1))
        history.record_statistics(_stats(accepted=2))
        self.assertEqual(len(history), 2)
        self.assertEqual(history.get_latest()["accepted_count"], 2)

    def test_snapshot_comparison_and_its_validation_unaffected(self):
        comparisons = _chain([{"accepted": 1}, {"accepted": 3}])
        self.assertTrue(comparisons[0]["valid"])
        self.assertTrue(validate(comparisons[0])["valid"])

    def test_gate_evaluation_pipeline_still_runs(self):
        result = evaluate_learned_knowledge_gate(selection=None)
        self.assertEqual(result.status, "REJECTED")
        self.assertEqual(result.reason, REASON_NOT_SELECTED)

    def test_trend_function_never_appears_in_the_gate_decision_path(self):
        # Purely a sanity check that the new function is additive: the
        # gate's own evaluation does not reference it.
        import inspect
        from learning import learned_knowledge_gate
        source = inspect.getsource(learned_knowledge_gate)
        self.assertNotIn("summarize_learned_knowledge_diagnostic_snapshot_comparison_trend", source)


if __name__ == "__main__":
    unittest.main()
