"""
Tests for Prompt 509 - Diagnostic Snapshot Comparison.

`compare_learned_knowledge_diagnostic_snapshots(earlier, later)`
(learning/learned_knowledge_statistics.py, also reachable through
`LearnedKnowledgeDiagnosticSnapshotHistory.compare_latest()` /
`.compare_sequences()`) compares two Prompt 508 diagnostic snapshots.
Every numeric delta is `later - earlier`. It is deterministic and
read-only: it mutates neither snapshot, nor the snapshot history, the
statistics, any trace, learned record, or response path, and nothing
reads its result to change behavior.

Run directly:
    python -m unittest tests.test_learned_knowledge_diagnostic_snapshot_comparison -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
)
from learning.learned_knowledge_gate import (
    STATUS_PASSED, REASON_OK, REASON_NOT_SELECTED, REASON_NOT_RELEVANT,
    REASON_INSUFFICIENT_RELIABILITY,
    DECISION_ACCEPTED, DECISION_REJECTED_IRRELEVANT, DECISION_REJECTED_LOW_RELIABILITY,
    LearnedKnowledgeGateResult,
    evaluate_learned_knowledge_gate, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    COMPARISON_DIRECTION,
    SNAPSHOT_VALIDATION_VALID, SNAPSHOT_VALIDATION_INVALID,
    summarize_learned_knowledge_decisions,
    analyze_learned_knowledge_statistics,
    validate_learned_knowledge_statistics_analysis,
    build_learned_knowledge_analysis_summary,
    compare_learned_knowledge_diagnostic_snapshots as compare,
)

from tests.test_pre_inference_readiness_guard import GuardCase, _core
from tests.test_local_inference_response_generation import TextRuntime

QUESTION = "Tell me about Rust"

NUMERIC_FIELDS = ["total_evaluations", "accepted_count", "rejected_count",
                  "no_candidate_count", "acceptance_rate", "rejection_rate"]


def _instruction():
    return VerifiedCorrectionResponseInstruction(
        source_text="I has a dgo", corrected_text="I has a dog",
        matched_text="dgo", replacement_text="dog", match_count=1)


def _trace(status, reason, **numbers):
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(status, reason, **numbers))


ACCEPTED = _trace(STATUS_PASSED, REASON_OK)
IRRELEVANT = _trace("REJECTED", REASON_NOT_RELEVANT)
LOW_RELIABILITY = _trace("REJECTED", REASON_INSUFFICIENT_RELIABILITY)
NO_CANDIDATE = _trace("REJECTED", REASON_NOT_SELECTED)


def _snapshot(accepted=0, irrelevant=0, low_reliability=0, no_candidate=0):
    """A real Prompt 508 snapshot, from real Prompt 504/505/506 output."""
    stats = LearnedKnowledgeDecisionStatistics()
    for trace, count in ((ACCEPTED, accepted), (IRRELEVANT, irrelevant),
                         (LOW_RELIABILITY, low_reliability), (NO_CANDIDATE, no_candidate)):
        for _ in range(count):
            stats.record(trace)
    return LearnedKnowledgeDiagnosticSnapshotHistory().record_statistics(stats)


def _invalid_status_snapshot():
    """A well-formed snapshot whose own validation_status is 'invalid'."""
    return LearnedKnowledgeDiagnosticSnapshotHistory().record({}, {"valid": False, "errors": ["boom"]})


class Case(GuardCase):

    def new_core(self):
        core, _tmp = _core(self)
        return core

    def teach(self, core, name="Rust", description="A systems programming language.",
              confidence=None):
        core.learning.teach(name, description, source="user", confidence=confidence)
        return core


# ----------------------------------------------------------------------
# result shape / direction
# ----------------------------------------------------------------------
class TestShapeAndDirection(unittest.TestCase):

    def test_valid_result_shape(self):
        result = compare(_snapshot(accepted=1), _snapshot(accepted=2))
        self.assertEqual(list(result.keys()), [
            "valid", "errors", "direction", "earlier", "later", "chronological",
            "comparable", "identical", "changed_fields", "numeric",
            "dominant_rejection_reason", "validation_status"])
        self.assertIs(result["valid"], True)
        self.assertEqual(result["errors"], [])
        self.assertEqual(list(result["numeric"].keys()), NUMERIC_FIELDS)
        for entry in result["numeric"].values():
            self.assertEqual(list(entry.keys()), ["earlier", "later", "delta", "changed"])

    def test_direction_is_later_minus_earlier_and_named_explicitly(self):
        first = _snapshot(accepted=1)
        second = _snapshot(accepted=4, low_reliability=2)
        result = compare(first, second)
        self.assertEqual(result["direction"], "later_minus_earlier")
        self.assertEqual(result["direction"], COMPARISON_DIRECTION)
        self.assertEqual(result["numeric"]["accepted_count"]["delta"], 3)
        self.assertEqual(result["numeric"]["accepted_count"]["earlier"], 1)
        self.assertEqual(result["numeric"]["accepted_count"]["later"], 4)
        self.assertEqual(result["numeric"]["total_evaluations"]["delta"], 5)

    def test_swapping_the_arguments_negates_every_delta(self):
        first = _snapshot(accepted=1, irrelevant=1)
        second = _snapshot(accepted=4, low_reliability=2, no_candidate=1)
        forward = compare(first, second)
        backward = compare(second, first)
        for field in NUMERIC_FIELDS:
            self.assertEqual(forward["numeric"][field]["delta"], -backward["numeric"][field]["delta"])

    def test_baseline_and_current_are_identified(self):
        first = _snapshot(accepted=1)
        second = _snapshot(accepted=2)
        second["snapshot_id"], second["sequence"] = "learned_knowledge_snapshot_000002", 2
        result = compare(first, second)
        self.assertEqual(result["earlier"], {"snapshot_id": first["snapshot_id"], "sequence": 1})
        self.assertEqual(result["later"], {"snapshot_id": "learned_knowledge_snapshot_000002",
                                           "sequence": 2})
        self.assertIs(result["chronological"], True)
        self.assertIs(compare(second, first)["chronological"], False)


# ----------------------------------------------------------------------
# numeric fields
# ----------------------------------------------------------------------
class TestNumericChanges(unittest.TestCase):

    def test_identical_snapshots(self):
        snap = _snapshot(accepted=3, irrelevant=1, low_reliability=2, no_candidate=2)
        result = compare(snap, copy.deepcopy(snap))
        self.assertIs(result["valid"], True)
        self.assertIs(result["identical"], True)
        self.assertEqual(result["changed_fields"], [])
        for field in NUMERIC_FIELDS:
            self.assertEqual(result["numeric"][field]["delta"], 0)
            self.assertIs(result["numeric"][field]["changed"], False)
        self.assertEqual(result["dominant_rejection_reason"]["change"], "unchanged")
        self.assertEqual(result["validation_status"]["change"], "unchanged")

    def test_comparing_a_snapshot_with_itself_is_identical(self):
        snap = _snapshot(accepted=2)
        self.assertIs(compare(snap, snap)["identical"], True)

    def test_increased_total_evaluations(self):
        result = compare(_snapshot(accepted=2), _snapshot(accepted=5))
        self.assertEqual(result["numeric"]["total_evaluations"]["delta"], 3)
        self.assertIs(result["numeric"]["total_evaluations"]["changed"], True)
        self.assertIn("total_evaluations", result["changed_fields"])

    def test_decreased_total_evaluations(self):
        result = compare(_snapshot(accepted=5), _snapshot(accepted=2))
        self.assertEqual(result["numeric"]["total_evaluations"]["delta"], -3)
        self.assertEqual(result["numeric"]["accepted_count"]["delta"], -3)

    def test_changed_accepted_count_only(self):
        result = compare(_snapshot(accepted=1, irrelevant=2), _snapshot(accepted=4, irrelevant=2))
        self.assertEqual(result["numeric"]["accepted_count"]["delta"], 3)
        self.assertEqual(result["numeric"]["rejected_count"]["delta"], 0)
        self.assertIs(result["numeric"]["rejected_count"]["changed"], False)
        self.assertEqual(result["numeric"]["no_candidate_count"]["delta"], 0)

    def test_changed_rejected_count(self):
        result = compare(_snapshot(accepted=2, low_reliability=1), _snapshot(accepted=2, low_reliability=4))
        self.assertEqual(result["numeric"]["rejected_count"]["delta"], 3)
        self.assertIs(result["numeric"]["rejected_count"]["changed"], True)
        self.assertEqual(result["numeric"]["accepted_count"]["delta"], 0)

    def test_changed_no_candidate_count(self):
        result = compare(_snapshot(accepted=2, no_candidate=1), _snapshot(accepted=2, no_candidate=6))
        self.assertEqual(result["numeric"]["no_candidate_count"]["delta"], 5)
        self.assertIs(result["numeric"]["no_candidate_count"]["changed"], True)

    def test_changed_acceptance_rate(self):
        first = _snapshot(accepted=1, irrelevant=1)      # 0.5
        second = _snapshot(accepted=3, irrelevant=1)     # 0.75
        result = compare(first, second)
        entry = result["numeric"]["acceptance_rate"]
        self.assertEqual((entry["earlier"], entry["later"]), (0.5, 0.75))
        self.assertEqual(entry["delta"], 0.75 - 0.5)
        self.assertIs(entry["changed"], True)

    def test_changed_rejection_rate(self):
        first = _snapshot(accepted=1, irrelevant=1)      # 0.5
        second = _snapshot(accepted=3, irrelevant=1)     # 0.25
        result = compare(first, second)
        entry = result["numeric"]["rejection_rate"]
        self.assertEqual((entry["earlier"], entry["later"]), (0.5, 0.25))
        self.assertEqual(entry["delta"], 0.25 - 0.5)
        self.assertLess(entry["delta"], 0)

    def test_rate_delta_uses_the_stored_values_unrounded(self):
        first = _snapshot(accepted=1, irrelevant=1, low_reliability=1)   # 1/3
        second = _snapshot(accepted=2, irrelevant=1, low_reliability=2)  # 2/5
        result = compare(first, second)
        for rate in ("acceptance_rate", "rejection_rate"):
            self.assertEqual(result["numeric"][rate]["delta"],
                             second[rate] - first[rate])

    def test_changed_fields_lists_only_what_changed_in_fixed_order(self):
        result = compare(_snapshot(accepted=1, irrelevant=1), _snapshot(accepted=1, low_reliability=1))
        self.assertEqual(result["changed_fields"], ["dominant_rejection_reason"])
        result = compare(_snapshot(accepted=1), _snapshot(accepted=2, no_candidate=2))
        self.assertEqual(result["changed_fields"],
                         ["total_evaluations", "accepted_count", "no_candidate_count",
                          "acceptance_rate"])


# ----------------------------------------------------------------------
# zero evaluations
# ----------------------------------------------------------------------
class TestZeroEvaluations(unittest.TestCase):

    def test_two_zero_evaluation_snapshots(self):
        result = compare(_snapshot(), _snapshot())
        self.assertIs(result["valid"], True)
        self.assertIs(result["identical"], True)
        for field in NUMERIC_FIELDS:
            self.assertEqual(result["numeric"][field]["delta"], 0)
        self.assertEqual(result["dominant_rejection_reason"]["change"], "unchanged")

    def test_zero_to_nonzero_and_back(self):
        grown = compare(_snapshot(), _snapshot(accepted=2, irrelevant=1))
        self.assertEqual(grown["numeric"]["total_evaluations"]["delta"], 3)
        shrunk = compare(_snapshot(accepted=2, irrelevant=1), _snapshot())
        self.assertEqual(shrunk["numeric"]["total_evaluations"]["delta"], -3)
        self.assertEqual(shrunk["numeric"]["acceptance_rate"]["later"], 0.0)


# ----------------------------------------------------------------------
# dominant rejection reason
# ----------------------------------------------------------------------
class TestDominantReason(unittest.TestCase):

    def test_unchanged_reason(self):
        result = compare(_snapshot(low_reliability=2), _snapshot(low_reliability=3, accepted=1))
        self.assertEqual(result["dominant_rejection_reason"], {
            "earlier": DECISION_REJECTED_LOW_RELIABILITY, "later": DECISION_REJECTED_LOW_RELIABILITY,
            "change": "unchanged", "changed": False})
        self.assertNotIn("dominant_rejection_reason", result["changed_fields"])

    def test_both_without_a_reason_is_unchanged(self):
        result = compare(_snapshot(accepted=1), _snapshot(accepted=3))
        self.assertEqual(result["dominant_rejection_reason"]["change"], "unchanged")
        self.assertIsNone(result["dominant_rejection_reason"]["earlier"])
        self.assertIsNone(result["dominant_rejection_reason"]["later"])

    def test_changed_reason(self):
        result = compare(_snapshot(irrelevant=2), _snapshot(low_reliability=2))
        self.assertEqual(result["dominant_rejection_reason"], {
            "earlier": DECISION_REJECTED_IRRELEVANT, "later": DECISION_REJECTED_LOW_RELIABILITY,
            "change": "changed", "changed": True})
        self.assertIn("dominant_rejection_reason", result["changed_fields"])

    def test_reason_appearing(self):
        result = compare(_snapshot(accepted=2), _snapshot(accepted=2, irrelevant=1))
        self.assertEqual(result["dominant_rejection_reason"], {
            "earlier": None, "later": DECISION_REJECTED_IRRELEVANT,
            "change": "became_available", "changed": True})

    def test_reason_disappearing(self):
        result = compare(_snapshot(accepted=2, irrelevant=1), _snapshot(accepted=2))
        self.assertEqual(result["dominant_rejection_reason"], {
            "earlier": DECISION_REJECTED_IRRELEVANT, "later": None,
            "change": "became_empty", "changed": True})


# ----------------------------------------------------------------------
# validation status
# ----------------------------------------------------------------------
class TestValidationStatus(unittest.TestCase):

    def test_unchanged_validation_status(self):
        result = compare(_snapshot(accepted=1), _snapshot(accepted=2))
        self.assertEqual(result["validation_status"], {
            "earlier": "valid", "later": "valid", "change": "unchanged", "changed": False})
        self.assertIs(result["comparable"], True)

    def test_changed_validation_status_valid_to_invalid(self):
        result = compare(_snapshot(accepted=1), _invalid_status_snapshot())
        self.assertIs(result["valid"], True)         # both are well-formed snapshots
        self.assertEqual(result["validation_status"], {
            "earlier": SNAPSHOT_VALIDATION_VALID, "later": SNAPSHOT_VALIDATION_INVALID,
            "change": "changed", "changed": True})
        self.assertIs(result["identical"], False)
        self.assertIn("validation_status", result["changed_fields"])

    def test_changed_validation_status_invalid_to_valid(self):
        result = compare(_invalid_status_snapshot(), _snapshot(accepted=1))
        self.assertEqual(result["validation_status"]["change"], "changed")
        self.assertEqual(result["validation_status"]["earlier"], SNAPSHOT_VALIDATION_INVALID)

    def test_snapshot_without_analysis_values_is_not_compared_numerically(self):
        result = compare(_snapshot(accepted=1), _invalid_status_snapshot())
        self.assertIs(result["comparable"], False)
        for field in NUMERIC_FIELDS:
            self.assertIsNone(result["numeric"][field]["delta"])
            self.assertIsNone(result["numeric"][field]["changed"])
            self.assertIsNone(result["numeric"][field]["later"])
        self.assertEqual(result["dominant_rejection_reason"]["change"], "not_comparable")
        self.assertIsNone(result["dominant_rejection_reason"]["changed"])
        # nothing invented, nothing counted as a change except the status itself
        self.assertEqual(result["changed_fields"], ["validation_status"])

    def test_two_status_invalid_snapshots(self):
        result = compare(_invalid_status_snapshot(), _invalid_status_snapshot())
        self.assertIs(result["valid"], True)
        self.assertIs(result["comparable"], False)
        self.assertEqual(result["validation_status"]["change"], "unchanged")
        self.assertIs(result["identical"], True)


# ----------------------------------------------------------------------
# invalid / missing input
# ----------------------------------------------------------------------
class TestInvalidInput(unittest.TestCase):

    def test_invalid_first_snapshot(self):
        bad = _snapshot(accepted=1)
        del bad["accepted_count"]
        result = compare(bad, _snapshot(accepted=2))
        self.assertIs(result["valid"], False)
        self.assertEqual(result["errors"], ["earlier_snapshot_invalid"])
        self.assertEqual(result["invalid_inputs"], ["earlier"])
        self.assertEqual(result["earlier_errors"], ["missing_field:accepted_count"])
        self.assertEqual(result["later_errors"], [])
        self.assertEqual(result["direction"], "later_minus_earlier")
        self.assertNotIn("numeric", result)

    def test_invalid_second_snapshot(self):
        bad = _snapshot(accepted=2)
        bad["acceptance_rate"] = 5.0
        result = compare(_snapshot(accepted=1), bad)
        self.assertIs(result["valid"], False)
        self.assertEqual(result["errors"], ["later_snapshot_invalid"])
        self.assertEqual(result["invalid_inputs"], ["later"])
        self.assertEqual(result["earlier_errors"], [])
        self.assertIn("analysis:rate_above_valid_range:acceptance_rate", result["later_errors"])

    def test_both_snapshots_invalid(self):
        result = compare(None, "nonsense")
        self.assertIs(result["valid"], False)
        self.assertEqual(result["errors"], ["earlier_snapshot_invalid", "later_snapshot_invalid"])
        self.assertEqual(result["invalid_inputs"], ["earlier", "later"])
        self.assertEqual(result["earlier_errors"], ["snapshot_missing"])
        self.assertEqual(result["later_errors"], ["snapshot_not_a_dict"])

    def test_missing_snapshot(self):
        for earlier, later in ((None, _snapshot(accepted=1)), (_snapshot(accepted=1), None)):
            result = compare(earlier, later)
            self.assertIs(result["valid"], False)
            side = "earlier" if earlier is None else "later"
            self.assertEqual(result["invalid_inputs"], [side])
            self.assertEqual(result[side + "_errors"], ["snapshot_missing"])
            self.assertIsNone(result[side + "_validation_information"])

    def test_validation_information_is_preserved_for_an_invalid_input(self):
        bad = _invalid_status_snapshot()
        bad["sequence"] = 0
        result = compare(bad, _snapshot(accepted=1))
        self.assertEqual(result["earlier_errors"], ["invalid_sequence"])
        self.assertEqual(result["earlier_validation_information"],
                         {"validation_status": "invalid", "validation_errors": ["boom"]})
        self.assertEqual(result["later_validation_information"],
                         {"validation_status": "valid", "validation_errors": []})

    def test_unusable_validation_information_is_none_not_invented(self):
        bad = {"snapshot_id": "x", "validation_status": "???", "validation_errors": "oops"}
        result = compare(bad, _snapshot())
        self.assertEqual(result["earlier_validation_information"],
                         {"validation_status": None, "validation_errors": None})

    def test_each_structural_problem_is_reported(self):
        base = _snapshot(accepted=2, irrelevant=1)
        cases = {
            "invalid_snapshot_id": ("snapshot_id", ""),
            "invalid_sequence": ("sequence", True),
            "invalid_validation_status": ("validation_status", "maybe"),
            "invalid_validation_errors": ("validation_errors", ["ok", 3]),
            "valid_snapshot_has_validation_errors": ("validation_errors", ["leftover"]),
            "analysis:negative_count:accepted_count": ("accepted_count", -1),
            "analysis:invalid_count_type:total_evaluations": ("total_evaluations", "3"),
            "analysis:invalid_dominant_rejection_reason": ("dominant_rejection_reason", "made_up"),
            "analysis:inconsistent_rejection_rate": ("rejection_rate", 0.99),
        }
        for expected, (field, value) in cases.items():
            bad = copy.deepcopy(base)
            bad[field] = value
            result = compare(bad, base)
            self.assertIs(result["valid"], False, msg=expected)
            self.assertIn(expected, result["earlier_errors"], msg=expected)

    def test_status_invalid_snapshot_must_not_carry_analysis_values(self):
        bad = _invalid_status_snapshot()
        bad["total_evaluations"] = 7
        result = compare(bad, _snapshot())
        self.assertEqual(result["earlier_errors"], ["invalid_snapshot_has_analysis_field:total_evaluations"])

    def test_non_dict_inputs_never_raise(self):
        for bad in (None, 0, "x", [], [1], (1,), 1.5, object(), {}):
            result = compare(bad, bad)
            self.assertIs(result["valid"], False)
            self.assertEqual(result["invalid_inputs"], ["earlier", "later"])

    def test_invalid_result_is_deterministic(self):
        bad = _snapshot(accepted=1)
        bad["rejected_count"] = -5
        self.assertEqual(compare(bad, None), compare(copy.deepcopy(bad), None))


# ----------------------------------------------------------------------
# history convenience methods + empty history
# ----------------------------------------------------------------------
class TestHistoryComparison(unittest.TestCase):

    def _history(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        stats = LearnedKnowledgeDecisionStatistics()
        for trace in (ACCEPTED, ACCEPTED, LOW_RELIABILITY, IRRELEVANT, LOW_RELIABILITY):
            stats.record(trace)
            history.record_statistics(stats)
        return history

    def test_empty_history(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        result = history.compare_latest()
        self.assertIs(result["valid"], False)
        self.assertEqual(result["invalid_inputs"], ["earlier", "later"])
        self.assertEqual(result["earlier_errors"], ["snapshot_missing"])
        self.assertEqual(result["later_errors"], ["snapshot_missing"])
        self.assertEqual(history.compare_sequences(1, 2)["invalid_inputs"], ["earlier", "later"])
        self.assertEqual(history.get_all(), [])

    def test_history_with_a_single_snapshot(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(LearnedKnowledgeDecisionStatistics())
        result = history.compare_latest()
        self.assertIs(result["valid"], False)
        self.assertEqual(result["invalid_inputs"], ["earlier"])
        self.assertEqual(result["later_errors"], [])

    def test_compare_latest_compares_previous_to_latest(self):
        history = self._history()
        result = history.compare_latest()
        self.assertEqual(result["earlier"]["sequence"], 4)
        self.assertEqual(result["later"]["sequence"], 5)
        self.assertEqual(result["numeric"]["total_evaluations"]["delta"], 1)
        self.assertEqual(result["numeric"]["rejected_count"]["delta"], 1)
        self.assertEqual(result, compare(history.get_all()[3], history.get_all()[4]))

    def test_compare_sequences_uses_the_order_given(self):
        history = self._history()
        forward = history.compare_sequences(1, 5)
        self.assertEqual(forward["numeric"]["total_evaluations"]["delta"], 4)
        self.assertIs(forward["chronological"], True)
        backward = history.compare_sequences(5, 1)
        self.assertEqual(backward["numeric"]["total_evaluations"]["delta"], -4)
        self.assertIs(backward["chronological"], False)
        self.assertEqual(backward["earlier"]["sequence"], 5)

    def test_compare_sequences_with_missing_or_bad_sequence(self):
        history = self._history()
        result = history.compare_sequences(1, 99)
        self.assertEqual(result["invalid_inputs"], ["later"])
        for bad in (0, -1, "1", 1.0, True, None):
            self.assertIs(history.compare_sequences(bad, 2)["valid"], False, msg=repr(bad))

    def test_evicted_snapshot_is_reported_missing(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory(max_snapshots=2)
        for _ in range(3):
            history.record_statistics(LearnedKnowledgeDecisionStatistics())
        self.assertEqual(history.compare_sequences(1, 3)["invalid_inputs"], ["earlier"])
        self.assertIs(history.compare_sequences(2, 3)["valid"], True)

    def test_history_is_not_mutated_by_comparison(self):
        history = self._history()
        before = history.get_all()
        history.compare_latest()
        history.compare_sequences(1, 3)
        history.compare_sequences(3, 1)
        history.compare_sequences(1, 99)
        self.assertEqual(history.get_all(), before)
        self.assertEqual(len(history), 5)
        # sequence numbering continues exactly as if nothing had been compared
        self.assertEqual(history.record_statistics(LearnedKnowledgeDecisionStatistics())["sequence"], 6)

    def test_mutating_the_returned_result_does_not_change_the_history(self):
        history = self._history()
        before = history.get_all()
        result = history.compare_latest()
        result["numeric"]["total_evaluations"]["delta"] = 1000
        result["changed_fields"].append("x")
        result["earlier"]["sequence"] = 0
        self.assertEqual(history.get_all(), before)
        self.assertEqual(history.compare_latest()["numeric"]["total_evaluations"]["delta"], 1)


# ----------------------------------------------------------------------
# purity / determinism
# ----------------------------------------------------------------------
class TestPurityAndDeterminism(unittest.TestCase):

    def test_neither_snapshot_is_mutated(self):
        first = _snapshot(accepted=1, irrelevant=1)
        second = _snapshot(accepted=3, low_reliability=1)
        first_before, second_before = copy.deepcopy(first), copy.deepcopy(second)
        compare(first, second)
        self.assertEqual(first, first_before)
        self.assertEqual(second, second_before)

    def test_invalid_snapshots_are_not_mutated_or_repaired(self):
        bad = _snapshot(accepted=1)
        bad["accepted_count"] = -1
        del bad["sequence"]
        good = _invalid_status_snapshot()
        bad_before, good_before = copy.deepcopy(bad), copy.deepcopy(good)
        compare(bad, good)
        compare(good, bad)
        self.assertEqual(bad, bad_before)
        self.assertEqual(good, good_before)

    def test_result_is_independent_of_the_inputs(self):
        first = _invalid_status_snapshot()
        first["sequence"] = 0
        result = compare(first, _snapshot())
        expected = copy.deepcopy(result)
        first["validation_errors"].append("added_later")
        self.assertEqual(result, expected)

    def test_repeated_calls_are_identical(self):
        first = _snapshot(accepted=1, irrelevant=1)
        second = _snapshot(accepted=3, low_reliability=1)
        self.assertEqual(compare(first, second), compare(first, second))
        self.assertEqual(compare(first, second), compare(copy.deepcopy(first), copy.deepcopy(second)))


# ----------------------------------------------------------------------
# comparison does not affect any other system
# ----------------------------------------------------------------------
class TestComparisonDoesNotAffectOtherSystems(Case):

    def test_does_not_modify_statistics_analysis_validation_or_traces(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        stats = core.learned_knowledge_decision_statistics
        history = core.learned_knowledge_diagnostic_snapshot_history
        history.record_statistics(stats)
        core.understand_language(QUESTION)
        history.record_statistics(stats)

        summary_before = copy.deepcopy(stats.summary())
        analysis_before = copy.deepcopy(stats.analyze())
        validation_before = copy.deepcopy(stats.validate_analysis())
        text_before = copy.deepcopy(stats.summarize_analysis())
        trace_before = copy.deepcopy(core.last_learned_knowledge_gate_trace.to_dict())
        snapshots_before = history.get_all()

        result = history.compare_latest()
        self.assertIs(result["valid"], True)
        self.assertEqual(result["numeric"]["total_evaluations"]["delta"], 1)
        history.compare_sequences(1, 2)

        self.assertEqual(stats.summary(), summary_before)
        self.assertEqual(stats.analyze(), analysis_before)
        self.assertEqual(stats.validate_analysis(), validation_before)
        self.assertEqual(stats.summarize_analysis(), text_before)
        self.assertEqual(core.last_learned_knowledge_gate_trace.to_dict(), trace_before)
        self.assertEqual(history.get_all(), snapshots_before)

    def test_does_not_modify_learned_records(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.knowledge.relate("Rust", "memory safety", "HAS", confidence=0.95)
        core.understand_language(QUESTION)
        history = core.learned_knowledge_diagnostic_snapshot_history
        history.record_statistics(core.learned_knowledge_decision_statistics)
        history.record_statistics(core.learned_knowledge_decision_statistics)
        knowledge_before = copy.deepcopy(core.knowledge.all())
        relationships_before = copy.deepcopy(core.knowledge.relationships_for("Rust"))
        history.compare_latest()
        history.compare_sequences(1, 2)
        self.assertEqual(core.knowledge.all(), knowledge_before)
        self.assertEqual(core.knowledge.relationships_for("Rust"), relationships_before)

    def test_new_core_never_compares_or_records_on_its_own(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        core.process_input(QUESTION)
        self.assertEqual(core.learned_knowledge_diagnostic_snapshot_history.get_all(), [])

    def _request(self, with_comparison):
        core = self.teach(self.new_core(), confidence=0.9)
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        if with_comparison:
            history = core.learned_knowledge_diagnostic_snapshot_history
            history.record_statistics(core.learned_knowledge_decision_statistics)
            history.record_statistics(core.learned_knowledge_decision_statistics)
            history.compare_latest()
            history.compare_sequences(1, 2)
        reply = core.process_input(QUESTION)
        if with_comparison:
            core.learned_knowledge_diagnostic_snapshot_history.compare_latest()
        return core, reply, runtime.requests[0]

    def test_does_not_affect_response_generation(self):
        control, control_reply, control_request = self._request(False)
        core, reply, request = self._request(True)
        self.assertEqual(reply, control_reply)
        self.assertEqual(repr(request.generation_context), repr(control_request.generation_context))
        self.assertEqual(repr(request.generation_request), repr(control_request.generation_request))
        self.assertEqual(core.last_learned_knowledge_gate_trace.to_dict(),
                         control.last_learned_knowledge_gate_trace.to_dict())
        self.assertEqual(core.learned_knowledge_decision_statistics.summary(),
                         control.learned_knowledge_decision_statistics.summary())

    def test_comparison_not_in_the_generation_request(self):
        _core_, _reply, request = self._request(True)
        for forbidden in ("later_minus_earlier", "changed_fields", "became_available", "comparable"):
            self.assertNotIn(forbidden, repr(request.generation_context))
            self.assertNotIn(forbidden, repr(request.generation_request))


# ----------------------------------------------------------------------
# earlier prompts unchanged
# ----------------------------------------------------------------------
class TestEarlierPromptsStillUnchanged(Case):

    def generate(self, core):
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        understanding = core.understand_language(QUESTION)
        result = core.language_intelligence.generate_response(
            understanding, context=core.context, verified_correction_instruction=_instruction())
        return runtime.requests[0], result

    def test_prompt_500_correction_behavior_unchanged(self):
        request, result = self.generate(self.teach(self.new_core(), confidence=0.9))
        self.assertIs(result.used_verified_correction, True)
        self.assertEqual(request.generation_request.original_message, "I has a dog")

    def test_prompt_502_gate_still_never_raises(self):
        weird = {"status": "SELECTED", "record": {"name": None}}
        self.assertEqual(evaluate_learned_knowledge_gate(weird).status, "REJECTED")

    def test_prompt_503_trace_field_still_populated_as_before(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        self.assertEqual(core.last_learned_knowledge_gate_trace.decision, DECISION_ACCEPTED)

    def test_prompt_504_statistics_summary_shape_unchanged(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        summary = core.learned_knowledge_decision_statistics.summary()
        self.assertEqual(
            sorted(summary.keys()),
            sorted(["total_evaluations", "total_accepted", "total_rejected", "total_no_candidate",
                    "total_gate_errors", "rejection_reasons", "acceptance_rate", "rejection_rate"]))
        self.assertEqual(summary["total_accepted"], 1)

    def test_prompt_505_analysis_shape_unchanged(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED)
        self.assertEqual(
            sorted(analyze_learned_knowledge_statistics(stats).keys()),
            sorted(["total_evaluations", "accepted_count", "rejected_count", "no_candidate_count",
                    "acceptance_rate", "rejection_rate", "dominant_rejection_reason"]))

    def test_prompt_506_validation_shape_unchanged(self):
        analysis = analyze_learned_knowledge_statistics(_snapshot_free_stats())
        self.assertEqual(validate_learned_knowledge_statistics_analysis(analysis),
                         {"valid": True, "errors": [], "warnings": []})

    def test_prompt_507_summary_unchanged(self):
        stats = _snapshot_free_stats()
        analysis = stats.analyze()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertTrue(summary["valid"])
        self.assertEqual(sorted(summary.keys()), sorted([
            "valid", "errors", "total_evaluations", "accepted_count", "rejected_count",
            "no_candidate_count", "acceptance_rate", "rejection_rate",
            "dominant_rejection_reason", "text"]))
        self.assertIn("4 evaluation(s)", summary["text"])

    def test_prompt_508_snapshot_behavior_unchanged(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory(max_snapshots=2)
        stats = _snapshot_free_stats()
        first = history.record_statistics(stats)
        self.assertEqual(list(first.keys()), [
            "snapshot_id", "sequence", "validation_status", "validation_errors",
            "total_evaluations", "accepted_count", "rejected_count", "no_candidate_count",
            "acceptance_rate", "rejection_rate", "dominant_rejection_reason"])
        self.assertEqual(first["snapshot_id"], "learned_knowledge_snapshot_000001")
        history.record_statistics(stats)
        history.record_statistics(stats)
        self.assertEqual([s["sequence"] for s in history.get_all()], [2, 3])
        self.assertEqual(history.get_latest()["sequence"], 3)
        self.assertEqual([s["sequence"] for s in history.get_recent(1)], [3])
        self.assertEqual(LearnedKnowledgeDiagnosticSnapshotHistory().get_all(), [])
        self.assertIsNone(LearnedKnowledgeDiagnosticSnapshotHistory().get_latest())

    def test_prompt_508_history_unchanged_by_prompt_509_calls(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_snapshot_free_stats())
        before = history.get_all()
        history.compare_latest()
        self.assertEqual(history.get_all(), before)


def _snapshot_free_stats():
    stats = LearnedKnowledgeDecisionStatistics()
    for trace in (ACCEPTED, ACCEPTED, LOW_RELIABILITY, NO_CANDIDATE):
        stats.record(trace)
    return stats


if __name__ == "__main__":
    unittest.main()
