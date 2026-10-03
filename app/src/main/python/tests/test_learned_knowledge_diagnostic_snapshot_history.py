"""
Tests for Prompt 508 - Learned Knowledge Diagnostic Snapshot History.

`LearnedKnowledgeDiagnosticSnapshotHistory`
(learning/learned_knowledge_statistics.py) keeps a bounded, in-memory,
diagnostic-only history of snapshots of the Prompt 505 analysis / Prompt
506 validation / Prompt 507 summary information. It stores deep copies,
returns deep copies, never reads or writes a trace, learned record, the
statistics counters, a threshold, the gate, or a response path, and is
never used to make a decision.

Covers:
    1. storing one snapshot / multiple snapshots
    2. latest / recent / all retrieval
    3. empty history
    4. deterministic identifiers and order
    5. snapshot data preserved correctly (valid and invalid)
    6. isolation from the original analysis/validation/statistics
    7. retrieval does not mutate stored snapshots
    8. history does not touch learned records / traces / statistics /
       analysis / validation / response generation / learning behavior
    9. maximum history behavior
    10. Prompt 507/506/505/504/503/502/500 behavior unchanged

Run directly:
    python -m unittest tests.test_learned_knowledge_diagnostic_snapshot_history -v
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
    DECISION_ACCEPTED, DECISION_REJECTED_LOW_RELIABILITY,
    LearnedKnowledgeGateResult,
    evaluate_learned_knowledge_gate, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    DEFAULT_MAX_SNAPSHOT_HISTORY,
    SNAPSHOT_VALIDATION_VALID, SNAPSHOT_VALIDATION_INVALID,
    summarize_learned_knowledge_decisions,
    analyze_learned_knowledge_statistics,
    validate_learned_knowledge_statistics_analysis,
    build_learned_knowledge_analysis_summary,
)

from tests.test_pre_inference_readiness_guard import GuardCase, _core
from tests.test_local_inference_response_generation import TextRuntime

QUESTION = "Tell me about Rust"

SNAPSHOT_KEYS = [
    "snapshot_id", "sequence", "validation_status", "validation_errors",
    "total_evaluations", "accepted_count", "rejected_count", "no_candidate_count",
    "acceptance_rate", "rejection_rate", "dominant_rejection_reason",
]


def _instruction():
    return VerifiedCorrectionResponseInstruction(
        source_text="I has a dgo", corrected_text="I has a dog",
        matched_text="dgo", replacement_text="dog", match_count=1)


def _trace(status, reason, **numbers):
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(status, reason, **numbers))


ACCEPTED_TRACE = _trace(STATUS_PASSED, REASON_OK)
IRRELEVANT_TRACE = _trace("REJECTED", REASON_NOT_RELEVANT)
LOW_RELIABILITY_TRACE = _trace("REJECTED", REASON_INSUFFICIENT_RELIABILITY)
NO_CANDIDATE_TRACE = _trace("REJECTED", REASON_NOT_SELECTED)


def _mixed_traces():
    return [
        ACCEPTED_TRACE, ACCEPTED_TRACE, ACCEPTED_TRACE,
        IRRELEVANT_TRACE,
        LOW_RELIABILITY_TRACE, LOW_RELIABILITY_TRACE,
        NO_CANDIDATE_TRACE, NO_CANDIDATE_TRACE,
    ]


def _mixed_statistics():
    stats = LearnedKnowledgeDecisionStatistics()
    for trace in _mixed_traces():
        stats.record(trace)
    return stats


def _analysis_and_validation(stats=None):
    analysis = (stats or _mixed_statistics()).analyze()
    return analysis, validate_learned_knowledge_statistics_analysis(analysis)


_VOLATILE_KEYS = ("id", "created_at", "updated_at", "timestamp")


def _stable(value):
    """`value` with per-instance ids/timestamps removed, so the knowledge
    of two independently built cores can be compared field-for-field."""
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in _VOLATILE_KEYS}
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    return value


class Case(GuardCase):

    def new_core(self):
        core, _tmp = _core(self)
        return core

    def teach(self, core, name="Rust", description="A systems programming language.",
              confidence=None):
        core.learning.teach(name, description, source="user", confidence=confidence)
        return core


# ----------------------------------------------------------------------
# 1. storing snapshots
# ----------------------------------------------------------------------
class TestStoring(unittest.TestCase):

    def test_store_one_snapshot(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        analysis, validation = _analysis_and_validation()
        stored = history.record(analysis, validation)
        self.assertEqual(len(history), 1)
        self.assertEqual(history.get_all(), [stored])
        self.assertEqual(list(stored.keys()), SNAPSHOT_KEYS)

    def test_store_multiple_snapshots(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        stats = LearnedKnowledgeDecisionStatistics()
        for trace in (ACCEPTED_TRACE, LOW_RELIABILITY_TRACE, NO_CANDIDATE_TRACE):
            stats.record(trace)
            history.record_statistics(stats)
        self.assertEqual(len(history), 3)
        self.assertEqual([s["total_evaluations"] for s in history.get_all()], [1, 2, 3])

    def test_record_statistics_matches_record_of_analysis_and_validation(self):
        stats = _mixed_statistics()
        via_stats = LearnedKnowledgeDiagnosticSnapshotHistory().record_statistics(stats)
        analysis, validation = _analysis_and_validation(stats)
        via_pair = LearnedKnowledgeDiagnosticSnapshotHistory().record(analysis, validation)
        self.assertEqual(via_stats, via_pair)

    def test_record_statistics_accepts_a_summary_dict(self):
        summary = _mixed_statistics().summary()
        snapshot = LearnedKnowledgeDiagnosticSnapshotHistory().record_statistics(summary)
        self.assertEqual(snapshot["total_evaluations"], 8)


# ----------------------------------------------------------------------
# 2/3. retrieval and empty history
# ----------------------------------------------------------------------
class TestRetrieval(unittest.TestCase):

    def _filled(self, count):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        stats = LearnedKnowledgeDecisionStatistics()
        for _ in range(count):
            stats.record(ACCEPTED_TRACE)
            history.record_statistics(stats)
        return history

    def test_latest_snapshot(self):
        history = self._filled(4)
        latest = history.get_latest()
        self.assertEqual(latest["sequence"], 4)
        self.assertEqual(latest["total_evaluations"], 4)
        self.assertEqual(latest, history.get_all()[-1])

    def test_recent_snapshots_are_the_newest_n_oldest_first(self):
        history = self._filled(5)
        recent = history.get_recent(3)
        self.assertEqual([s["sequence"] for s in recent], [3, 4, 5])

    def test_recent_limit_larger_than_history_returns_everything(self):
        history = self._filled(2)
        self.assertEqual([s["sequence"] for s in history.get_recent(50)], [1, 2])

    def test_recent_without_limit_returns_everything(self):
        history = self._filled(3)
        self.assertEqual(history.get_recent(), history.get_all())
        self.assertEqual(history.get_recent(None), history.get_all())

    def test_recent_with_zero_negative_or_bad_limit_returns_empty(self):
        history = self._filled(3)
        for bad in (0, -1, -100, "2", 1.5, True, [], {}):
            self.assertEqual(history.get_recent(bad), [], msg=repr(bad))

    def test_empty_history_uses_the_safe_empty_representations(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        self.assertEqual(len(history), 0)
        self.assertEqual(history.get_all(), [])
        self.assertIsNone(history.get_latest())
        self.assertEqual(history.get_recent(5), [])
        self.assertEqual(history.get_recent(), [])
        self.assertEqual(history.get_recent(0), [])


# ----------------------------------------------------------------------
# 4. deterministic identifiers / order
# ----------------------------------------------------------------------
class TestDeterminism(unittest.TestCase):

    def test_identifiers_and_sequence_are_deterministic(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        analysis, validation = _analysis_and_validation()
        for _ in range(3):
            history.record(analysis, validation)
        snapshots = history.get_all()
        self.assertEqual([s["sequence"] for s in snapshots], [1, 2, 3])
        self.assertEqual(
            [s["snapshot_id"] for s in snapshots],
            ["learned_knowledge_snapshot_000001",
             "learned_knowledge_snapshot_000002",
             "learned_knowledge_snapshot_000003"])

    def test_two_histories_fed_the_same_inputs_are_identical(self):
        first = LearnedKnowledgeDiagnosticSnapshotHistory()
        second = LearnedKnowledgeDiagnosticSnapshotHistory()
        for history in (first, second):
            stats = LearnedKnowledgeDecisionStatistics()
            for trace in _mixed_traces():
                stats.record(trace)
                history.record_statistics(stats)
        self.assertEqual(first.get_all(), second.get_all())

    def test_repeated_retrieval_is_identical(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_mixed_statistics())
        history.record_statistics(LearnedKnowledgeDecisionStatistics())
        self.assertEqual(history.get_all(), history.get_all())
        self.assertEqual(history.get_latest(), history.get_latest())
        self.assertEqual(history.get_recent(1), history.get_recent(1))

    def test_snapshots_carry_no_timestamp(self):
        snapshot = LearnedKnowledgeDiagnosticSnapshotHistory().record_statistics(_mixed_statistics())
        self.assertEqual(list(snapshot.keys()), SNAPSHOT_KEYS)


# ----------------------------------------------------------------------
# 5. snapshot data preserved correctly
# ----------------------------------------------------------------------
class TestSnapshotData(unittest.TestCase):

    def test_valid_snapshot_preserves_every_diagnostic_field(self):
        analysis, validation = _analysis_and_validation()
        snapshot = LearnedKnowledgeDiagnosticSnapshotHistory().record(analysis, validation)
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_VALID)
        self.assertEqual(snapshot["validation_errors"], [])
        self.assertEqual(snapshot["total_evaluations"], 8)
        self.assertEqual(snapshot["accepted_count"], 3)
        self.assertEqual(snapshot["rejected_count"], 3)
        self.assertEqual(snapshot["no_candidate_count"], 2)
        self.assertEqual(snapshot["acceptance_rate"], analysis["acceptance_rate"])
        self.assertEqual(snapshot["rejection_rate"], analysis["rejection_rate"])
        self.assertEqual(snapshot["dominant_rejection_reason"], DECISION_REJECTED_LOW_RELIABILITY)

    def test_snapshot_agrees_with_the_prompt_507_summary(self):
        analysis, validation = _analysis_and_validation()
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        snapshot = LearnedKnowledgeDiagnosticSnapshotHistory().record(analysis, validation)
        for field in ("total_evaluations", "accepted_count", "rejected_count",
                      "no_candidate_count", "acceptance_rate", "rejection_rate",
                      "dominant_rejection_reason"):
            self.assertEqual(snapshot[field], summary[field], msg=field)

    def test_no_dominant_reason_is_preserved_as_none(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        snapshot = LearnedKnowledgeDiagnosticSnapshotHistory().record_statistics(stats)
        self.assertIsNone(snapshot["dominant_rejection_reason"])
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_VALID)

    def test_zero_evaluation_snapshot(self):
        snapshot = LearnedKnowledgeDiagnosticSnapshotHistory().record_statistics(
            LearnedKnowledgeDecisionStatistics())
        self.assertEqual(snapshot["total_evaluations"], 0)
        self.assertEqual(snapshot["acceptance_rate"], 0.0)
        self.assertEqual(snapshot["rejection_rate"], 0.0)
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_VALID)

    def test_invalid_analysis_snapshot_keeps_errors_and_no_guessed_values(self):
        analysis, _ = _analysis_and_validation()
        analysis["accepted_count"] = -1
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(validation["valid"])
        snapshot = LearnedKnowledgeDiagnosticSnapshotHistory().record(analysis, validation)
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_INVALID)
        self.assertEqual(snapshot["validation_errors"], validation["errors"])
        self.assertEqual(list(snapshot.keys()), SNAPSHOT_KEYS)
        for field in ("total_evaluations", "accepted_count", "rejected_count",
                      "no_candidate_count", "acceptance_rate", "rejection_rate",
                      "dominant_rejection_reason"):
            self.assertIsNone(snapshot[field], msg=field)

    def test_unrecognized_inputs_become_invalid_snapshots_without_raising(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        for analysis, validation in ((None, None), ({}, "x"), ("a", {"errors": ["e"]}),
                                     ({"total_evaluations": 1}, {"valid": False, "errors": ["e"]})):
            snapshot = history.record(analysis, validation)
            self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_INVALID)
            self.assertEqual(list(snapshot.keys()), SNAPSHOT_KEYS)
        self.assertEqual(len(history), 4)

    def test_valid_validation_but_non_dict_analysis_is_invalid(self):
        snapshot = LearnedKnowledgeDiagnosticSnapshotHistory().record(
            None, {"valid": True, "errors": [], "warnings": []})
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_INVALID)
        self.assertEqual(snapshot["validation_errors"], ["analysis_not_a_dict"])

    def test_snapshot_stores_no_raw_content_or_extra_fields(self):
        snapshot = LearnedKnowledgeDiagnosticSnapshotHistory().record_statistics(_mixed_statistics())
        self.assertEqual(set(snapshot.keys()), set(SNAPSHOT_KEYS))
        self.assertNotIn("text", snapshot)


# ----------------------------------------------------------------------
# 6. independence from the source objects
# ----------------------------------------------------------------------
class TestIndependenceFromSources(unittest.TestCase):

    def test_modifying_analysis_and_validation_afterwards_does_not_change_history(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        analysis, validation = _analysis_and_validation()
        history.record(analysis, validation)
        before = history.get_all()
        analysis["total_evaluations"] = 999
        analysis["dominant_rejection_reason"] = "changed"
        validation["valid"] = False
        validation["errors"].append("added_later")
        self.assertEqual(history.get_all(), before)

    def test_modifying_invalid_validation_errors_afterwards_does_not_change_history(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        validation = {"valid": False, "errors": ["a", "b"]}
        history.record({}, validation)
        before = history.get_all()
        validation["errors"].append("c")
        validation["errors"][0] = "changed"
        self.assertEqual(history.get_all(), before)

    def test_modifying_statistics_afterwards_does_not_change_history(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        stats = _mixed_statistics()
        history.record_statistics(stats)
        before = history.get_all()
        for _ in range(5):
            stats.record(ACCEPTED_TRACE)
        stats.reset()
        self.assertEqual(history.get_all(), before)

    def test_modifying_a_summary_dict_afterwards_does_not_change_history(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        summary = _mixed_statistics().summary()
        history.record_statistics(summary)
        before = history.get_all()
        summary["total_accepted"] = 1000
        summary["rejection_reasons"]["rejected_irrelevant"] = 1000
        self.assertEqual(history.get_all(), before)

    def test_recording_does_not_mutate_the_sources(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        stats = _mixed_statistics()
        analysis, validation = _analysis_and_validation(stats)
        stats_before = copy.deepcopy(stats.summary())
        analysis_before = copy.deepcopy(analysis)
        validation_before = copy.deepcopy(validation)
        history.record(analysis, validation)
        history.record_statistics(stats)
        self.assertEqual(stats.summary(), stats_before)
        self.assertEqual(analysis, analysis_before)
        self.assertEqual(validation, validation_before)

    def test_recording_does_not_mutate_invalid_sources(self):
        analysis, _ = _analysis_and_validation()
        analysis["accepted_count"] = -1
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        analysis_before = copy.deepcopy(analysis)
        validation_before = copy.deepcopy(validation)
        LearnedKnowledgeDiagnosticSnapshotHistory().record(analysis, validation)
        self.assertEqual(analysis, analysis_before)
        self.assertEqual(validation, validation_before)


# ----------------------------------------------------------------------
# 7. retrieval does not mutate stored snapshots
# ----------------------------------------------------------------------
class TestRetrievalIsolation(unittest.TestCase):

    def _history(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_mixed_statistics())
        history.record({}, {"valid": False, "errors": ["boom"]})
        return history

    def test_mutating_the_returned_record_result_does_not_change_history(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        returned = history.record_statistics(_mixed_statistics())
        expected = history.get_all()
        returned["total_evaluations"] = -1
        returned["validation_errors"].append("x")
        self.assertEqual(history.get_all(), expected)

    def test_mutating_get_all_results_does_not_change_history(self):
        history = self._history()
        expected = history.get_all()
        for snapshot in history.get_all():
            snapshot["accepted_count"] = 12345
            snapshot["validation_errors"].append("x")
            snapshot["sequence"] = 0
        history.get_all().clear()
        self.assertEqual(history.get_all(), expected)

    def test_mutating_get_latest_result_does_not_change_history(self):
        history = self._history()
        expected = history.get_all()
        latest = history.get_latest()
        latest["validation_status"] = "tampered"
        latest["validation_errors"].append("x")
        self.assertEqual(history.get_all(), expected)

    def test_mutating_get_recent_results_does_not_change_history(self):
        history = self._history()
        expected = history.get_all()
        recent = history.get_recent(2)
        for snapshot in recent:
            snapshot["snapshot_id"] = "tampered"
            snapshot["validation_errors"].append("x")
        recent.clear()
        self.assertEqual(history.get_all(), expected)

    def test_retrieval_calls_do_not_change_length_or_order(self):
        history = self._history()
        history.get_all()
        history.get_latest()
        history.get_recent(1)
        history.get_recent(0)
        history.get_recent("bad")
        self.assertEqual(len(history), 2)
        self.assertEqual([s["sequence"] for s in history.get_all()], [1, 2])


# ----------------------------------------------------------------------
# 9. maximum history behavior
# ----------------------------------------------------------------------
class TestMaximumHistory(unittest.TestCase):

    def test_default_limit_is_documented_and_used(self):
        self.assertEqual(DEFAULT_MAX_SNAPSHOT_HISTORY, 100)
        self.assertEqual(LearnedKnowledgeDiagnosticSnapshotHistory().max_snapshots, 100)

    def test_history_never_exceeds_the_limit_and_drops_only_the_oldest(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory(max_snapshots=3)
        stats = LearnedKnowledgeDecisionStatistics()
        for _ in range(5):
            stats.record(ACCEPTED_TRACE)
            history.record_statistics(stats)
        self.assertEqual(len(history), 3)
        self.assertEqual([s["sequence"] for s in history.get_all()], [3, 4, 5])
        self.assertEqual([s["total_evaluations"] for s in history.get_all()], [3, 4, 5])
        self.assertEqual(history.get_latest()["sequence"], 5)

    def test_kept_snapshots_are_unchanged_by_eviction(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory(max_snapshots=2)
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        history.record_statistics(stats)
        stats.record(LOW_RELIABILITY_TRACE)
        second = history.record_statistics(stats)
        stats.record(NO_CANDIDATE_TRACE)
        third = history.record_statistics(stats)
        self.assertEqual(history.get_all(), [second, third])

    def test_sequence_numbers_are_never_reused_after_eviction(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory(max_snapshots=1)
        ids = [history.record_statistics(LearnedKnowledgeDecisionStatistics())["snapshot_id"]
               for _ in range(3)]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(history.get_latest()["snapshot_id"], "learned_knowledge_snapshot_000003")

    def test_history_at_exactly_the_limit_keeps_everything(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory(max_snapshots=4)
        for _ in range(4):
            history.record_statistics(LearnedKnowledgeDecisionStatistics())
        self.assertEqual([s["sequence"] for s in history.get_all()], [1, 2, 3, 4])

    def test_default_limit_bounds_the_history(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        for _ in range(DEFAULT_MAX_SNAPSHOT_HISTORY + 5):
            history.record_statistics(LearnedKnowledgeDecisionStatistics())
        self.assertEqual(len(history), DEFAULT_MAX_SNAPSHOT_HISTORY)
        self.assertEqual(history.get_all()[0]["sequence"], 6)

    def test_invalid_limit_falls_back_to_the_default(self):
        for bad in (0, -3, None, "5", 2.5, True):
            self.assertEqual(
                LearnedKnowledgeDiagnosticSnapshotHistory(max_snapshots=bad).max_snapshots,
                DEFAULT_MAX_SNAPSHOT_HISTORY, msg=repr(bad))


# ----------------------------------------------------------------------
# 8. history does not touch anything else
# ----------------------------------------------------------------------
class TestHistoryDoesNotAffectOtherSystems(Case):

    def test_history_does_not_modify_learned_records(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.knowledge.relate("Rust", "memory safety", "HAS", confidence=0.95)
        core.understand_language(QUESTION)
        before_knowledge = copy.deepcopy(core.knowledge.all())
        before_relationships = copy.deepcopy(core.knowledge.relationships_for("Rust"))
        history = core.learned_knowledge_diagnostic_snapshot_history
        history.record_statistics(core.learned_knowledge_decision_statistics)
        history.get_all()
        history.get_latest()
        history.get_recent(1)
        self.assertEqual(core.knowledge.all(), before_knowledge)
        self.assertEqual(core.knowledge.relationships_for("Rust"), before_relationships)

    def test_history_does_not_modify_decision_traces(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        trace_before = copy.deepcopy(core.last_learned_knowledge_gate_trace.to_dict())
        gate_before = (core.last_learned_knowledge_gate.status, core.last_learned_knowledge_gate.reason)
        core.learned_knowledge_diagnostic_snapshot_history.record_statistics(
            core.learned_knowledge_decision_statistics)
        self.assertEqual(core.last_learned_knowledge_gate_trace.to_dict(), trace_before)
        self.assertEqual(
            (core.last_learned_knowledge_gate.status, core.last_learned_knowledge_gate.reason),
            gate_before)

    def test_history_does_not_affect_statistics_analysis_or_validation(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        stats = core.learned_knowledge_decision_statistics
        summary_before = copy.deepcopy(stats.summary())
        analysis_before = copy.deepcopy(stats.analyze())
        validation_before = copy.deepcopy(stats.validate_analysis())
        text_summary_before = copy.deepcopy(stats.summarize_analysis())
        history = core.learned_knowledge_diagnostic_snapshot_history
        history.record_statistics(stats)
        history.record(analysis_before, validation_before)
        history.get_recent(2)
        self.assertEqual(stats.summary(), summary_before)
        self.assertEqual(stats.analyze(), analysis_before)
        self.assertEqual(stats.validate_analysis(), validation_before)
        self.assertEqual(stats.summarize_analysis(), text_summary_before)

    def test_new_core_starts_with_an_empty_history_and_nothing_records_automatically(self):
        core = self.teach(self.new_core(), confidence=0.9)
        history = core.learned_knowledge_diagnostic_snapshot_history
        self.assertEqual(history.get_all(), [])
        self.assertIsNone(history.get_latest())
        core.understand_language(QUESTION)
        core.process_input(QUESTION)
        self.assertEqual(history.get_all(), [])
        self.assertEqual(core.learned_knowledge_decision_statistics.summary()["total_evaluations"], 2)

    def test_each_core_has_its_own_history(self):
        first = self.new_core()
        second = self.new_core()
        first.learned_knowledge_diagnostic_snapshot_history.record_statistics(
            first.learned_knowledge_decision_statistics)
        self.assertEqual(len(first.learned_knowledge_diagnostic_snapshot_history), 1)
        self.assertEqual(len(second.learned_knowledge_diagnostic_snapshot_history), 0)

    def _request_with_history_activity(self, record_history):
        core = self.teach(self.new_core(), confidence=0.9)
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        if record_history:
            history = core.learned_knowledge_diagnostic_snapshot_history
            for _ in range(3):
                history.record_statistics(core.learned_knowledge_decision_statistics)
            history.get_all()
        reply = core.process_input(QUESTION)
        if record_history:
            core.learned_knowledge_diagnostic_snapshot_history.record_statistics(
                core.learned_knowledge_decision_statistics)
        request = runtime.requests[0]
        return core, reply, request

    def test_history_does_not_affect_response_generation(self):
        control, control_reply, control_request = self._request_with_history_activity(False)
        core, reply, request = self._request_with_history_activity(True)
        self.assertEqual(reply, control_reply)
        self.assertEqual(repr(request.generation_context), repr(control_request.generation_context))
        self.assertEqual(repr(request.generation_request), repr(control_request.generation_request))
        self.assertEqual(core.last_learned_knowledge_gate_trace.to_dict(),
                         control.last_learned_knowledge_gate_trace.to_dict())

    def test_snapshot_history_not_in_the_generation_request(self):
        _core_, _reply, request = self._request_with_history_activity(True)
        for forbidden in ("snapshot", "validation_status", "learned_knowledge_snapshot"):
            self.assertNotIn(forbidden, repr(request.generation_context))
            self.assertNotIn(forbidden, repr(request.generation_request))

    def test_history_does_not_affect_learning_behavior(self):
        control = self.teach(self.new_core(), confidence=0.9)
        core = self.teach(self.new_core(), confidence=0.9)
        history = core.learned_knowledge_diagnostic_snapshot_history
        for _ in range(3):
            history.record_statistics(core.learned_knowledge_decision_statistics)
        for target in (control, core):
            target.learning.teach("Go", "A compiled language.", source="user", confidence=0.8)
        self.assertEqual(_stable(core.knowledge.all()), _stable(control.knowledge.all()))
        self.assertEqual(_stable(core.knowledge.relationships_for("Go")),
                         _stable(control.knowledge.relationships_for("Go")))
        self.assertEqual(core.process_input("Tell me about Go"),
                         control.process_input("Tell me about Go"))
        self.assertEqual(core.learned_knowledge_decision_statistics.summary(),
                         control.learned_knowledge_decision_statistics.summary())

    def test_history_does_not_change_the_gate_decision_for_a_rejected_candidate(self):
        control = self.teach(self.new_core(), confidence=0.4)
        core = self.teach(self.new_core(), confidence=0.4)
        core.learned_knowledge_diagnostic_snapshot_history.record_statistics(
            core.learned_knowledge_decision_statistics)
        self.assertEqual(core.process_input(QUESTION), control.process_input(QUESTION))
        self.assertEqual(core.last_learned_knowledge_gate_trace.decision,
                         control.last_learned_knowledge_gate_trace.decision)
        self.assertEqual(core.last_learned_knowledge_gate_trace.decision,
                         DECISION_REJECTED_LOW_RELIABILITY)


# ----------------------------------------------------------------------
# 10. earlier prompts unchanged
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
        result = evaluate_learned_knowledge_gate(weird)
        self.assertEqual(result.status, "REJECTED")

    def test_prompt_503_trace_field_still_populated_as_before(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        self.assertEqual(core.last_learned_knowledge_gate_trace.decision, DECISION_ACCEPTED)

    def test_prompt_504_statistics_summary_shape_unchanged(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        summary = core.learned_knowledge_decision_statistics.summary()
        self.assertEqual(summary["total_accepted"], 1)
        self.assertEqual(summary["total_evaluations"], 1)
        self.assertEqual(
            sorted(summary.keys()),
            sorted(["total_evaluations", "total_accepted", "total_rejected", "total_no_candidate",
                    "total_gate_errors", "rejection_reasons", "acceptance_rate", "rejection_rate"]))

    def test_prompt_505_analysis_shape_unchanged(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        analysis = core.learned_knowledge_decision_statistics.analyze()
        self.assertEqual(analysis["accepted_count"], 1)
        self.assertIsNone(analysis["dominant_rejection_reason"])
        self.assertEqual(
            sorted(analysis.keys()),
            sorted(["total_evaluations", "accepted_count", "rejected_count", "no_candidate_count",
                    "acceptance_rate", "rejection_rate", "dominant_rejection_reason"]))

    def test_prompt_506_validation_shape_unchanged(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        analysis = core.learned_knowledge_decision_statistics.analyze()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertEqual(validation, {"valid": True, "errors": [], "warnings": []})

    def test_prompt_507_summary_unchanged(self):
        analysis = analyze_learned_knowledge_statistics(
            summarize_learned_knowledge_decisions(_mixed_traces()))
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["errors"], [])
        self.assertEqual(
            sorted(summary.keys()),
            sorted(["valid", "errors", "total_evaluations", "accepted_count", "rejected_count",
                    "no_candidate_count", "acceptance_rate", "rejection_rate",
                    "dominant_rejection_reason", "text"]))
        self.assertIn("8 evaluation(s)", summary["text"])
        invalid = build_learned_knowledge_analysis_summary(analysis, {"valid": False, "errors": ["e"]})
        self.assertEqual(sorted(invalid.keys()), ["errors", "text", "valid"])

    def test_prompt_507_summary_is_the_same_before_and_after_recording_a_snapshot(self):
        stats = _mixed_statistics()
        before = stats.summarize_analysis()
        LearnedKnowledgeDiagnosticSnapshotHistory().record_statistics(stats)
        self.assertEqual(stats.summarize_analysis(), before)


if __name__ == "__main__":
    unittest.main()
