"""
Tests for Prompt 504 - Learned Knowledge Decision Statistics.

`LearnedKnowledgeDecisionStatistics` / `summarize_learned_knowledge_decisions()`
aggregate Prompt 503 `LearnedKnowledgeGateTrace`s into plain counts and
rates. Purely diagnostic: it only reads each trace's own `decision`
field (already fixed by Prompt 502/503), never re-evaluates relevance
or reliability, never mutates a trace or a learned record, and has no
effect on the actual gate/response decision.

Covers:
    1. empty statistics
    2. one accepted / one of each rejection kind / one no-candidate
    3. multiple mixed decisions, with correct totals, counts and rates
    4. zero-evaluation safety
    5. no mutation of traces or learned records
    6. collecting statistics never changes the gate decision
    7. Prompt 500, 502, 503 behavior unchanged

Run directly:
    python -m unittest tests.test_learned_knowledge_statistics -v
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
)
from learning.learned_knowledge_gate import (
    STATUS_PASSED, REASON_OK, REASON_NOT_SELECTED, REASON_NOT_RELEVANT,
    REASON_NO_EVIDENCE, REASON_INSUFFICIENT_RELIABILITY,
    DECISION_ACCEPTED, DECISION_REJECTED_IRRELEVANT, DECISION_REJECTED_LOW_RELIABILITY,
    DECISION_REJECTED_INSUFFICIENT_EVIDENCE, DECISION_NO_CANDIDATE, DECISION_GATE_ERROR,
    LearnedKnowledgeGateResult,
    evaluate_learned_knowledge_gate, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics, summarize_learned_knowledge_decisions,
)

from tests.test_pre_inference_readiness_guard import GuardCase, _core
from tests.test_local_inference_response_generation import TextRuntime

QUESTION = "Tell me about Rust"


def _instruction():
    return VerifiedCorrectionResponseInstruction(
        source_text="I has a dgo", corrected_text="I has a dog",
        matched_text="dgo", replacement_text="dog", match_count=1)


def _trace(status, reason, **numbers):
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(status, reason, **numbers))


ACCEPTED_TRACE = _trace(STATUS_PASSED, REASON_OK)
IRRELEVANT_TRACE = _trace("REJECTED", REASON_NOT_RELEVANT)
LOW_RELIABILITY_TRACE = _trace("REJECTED", REASON_INSUFFICIENT_RELIABILITY)
INSUFFICIENT_EVIDENCE_TRACE = _trace("REJECTED", REASON_NO_EVIDENCE)
NO_CANDIDATE_TRACE = _trace("REJECTED", REASON_NOT_SELECTED)


class Case(GuardCase):

    def new_core(self):
        core, _tmp = _core(self)
        return core

    def teach(self, core, name="Rust", description="A systems programming language.",
              confidence=None):
        core.learning.teach(name, description, source="user", confidence=confidence)
        return core

    def selection(self, core, message=QUESTION):
        selection = core.select_learned_knowledge(message)
        self.assertTrue(selection.selected)
        return selection

    def gate(self, core, message=QUESTION):
        return evaluate_learned_knowledge_gate(self.selection(core, message), message=message)


# ----------------------------------------------------------------------
# 1. empty statistics
# ----------------------------------------------------------------------
class TestEmptyStatistics(unittest.TestCase):

    def test_fresh_statistics_object_is_all_zero(self):
        summary = LearnedKnowledgeDecisionStatistics().summary()
        self.assertEqual(summary["total_evaluations"], 0)
        self.assertEqual(summary["total_accepted"], 0)
        self.assertEqual(summary["total_rejected"], 0)
        self.assertEqual(summary["total_no_candidate"], 0)
        self.assertEqual(summary["total_gate_errors"], 0)
        self.assertEqual(summary["rejection_reasons"], {
            DECISION_REJECTED_IRRELEVANT: 0,
            DECISION_REJECTED_LOW_RELIABILITY: 0,
            DECISION_REJECTED_INSUFFICIENT_EVIDENCE: 0,
        })
        self.assertEqual(summary["acceptance_rate"], 0.0)
        self.assertEqual(summary["rejection_rate"], 0.0)

    def test_summarize_empty_and_none_iterables(self):
        self.assertEqual(summarize_learned_knowledge_decisions([]),
                          LearnedKnowledgeDecisionStatistics().summary())
        self.assertEqual(summarize_learned_knowledge_decisions(None),
                          LearnedKnowledgeDecisionStatistics().summary())

    def test_zero_evaluation_rates_never_divide_by_zero(self):
        stats = LearnedKnowledgeDecisionStatistics()
        try:
            summary = stats.summary()
        except ZeroDivisionError:
            self.fail("summary() must not raise ZeroDivisionError")
        self.assertEqual(summary["acceptance_rate"], 0.0)
        self.assertEqual(summary["rejection_rate"], 0.0)


# ----------------------------------------------------------------------
# 2. one decision of each kind
# ----------------------------------------------------------------------
class TestSingleDecisions(unittest.TestCase):

    def test_one_accepted(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        summary = stats.summary()
        self.assertEqual(summary["total_evaluations"], 1)
        self.assertEqual(summary["total_accepted"], 1)
        self.assertEqual(summary["total_rejected"], 0)
        self.assertEqual(summary["acceptance_rate"], 1.0)
        self.assertEqual(summary["rejection_rate"], 0.0)

    def test_one_irrelevant_rejection(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(IRRELEVANT_TRACE)
        summary = stats.summary()
        self.assertEqual(summary["total_evaluations"], 1)
        self.assertEqual(summary["total_rejected"], 1)
        self.assertEqual(summary["rejection_reasons"][DECISION_REJECTED_IRRELEVANT], 1)
        self.assertEqual(summary["rejection_rate"], 1.0)
        self.assertEqual(summary["acceptance_rate"], 0.0)

    def test_one_low_reliability_rejection(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(LOW_RELIABILITY_TRACE)
        summary = stats.summary()
        self.assertEqual(summary["total_rejected"], 1)
        self.assertEqual(summary["rejection_reasons"][DECISION_REJECTED_LOW_RELIABILITY], 1)

    def test_one_insufficient_evidence_rejection(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(INSUFFICIENT_EVIDENCE_TRACE)
        summary = stats.summary()
        self.assertEqual(summary["total_rejected"], 1)
        self.assertEqual(summary["rejection_reasons"][DECISION_REJECTED_INSUFFICIENT_EVIDENCE], 1)

    def test_one_no_candidate(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(NO_CANDIDATE_TRACE)
        summary = stats.summary()
        self.assertEqual(summary["total_evaluations"], 1)
        self.assertEqual(summary["total_no_candidate"], 1)
        self.assertEqual(summary["total_rejected"], 0)   # no_candidate is not a "rejection"
        self.assertEqual(summary["acceptance_rate"], 0.0)
        self.assertEqual(summary["rejection_rate"], 0.0)


# ----------------------------------------------------------------------
# 3. multiple mixed decisions
# ----------------------------------------------------------------------
class TestMixedDecisions(unittest.TestCase):

    def test_mixed_batch_counts_and_rates(self):
        traces = [
            ACCEPTED_TRACE, ACCEPTED_TRACE, ACCEPTED_TRACE,
            IRRELEVANT_TRACE,
            LOW_RELIABILITY_TRACE, LOW_RELIABILITY_TRACE,
            INSUFFICIENT_EVIDENCE_TRACE,
            NO_CANDIDATE_TRACE, NO_CANDIDATE_TRACE,
        ]
        summary = summarize_learned_knowledge_decisions(traces)
        self.assertEqual(summary["total_evaluations"], 9)
        self.assertEqual(summary["total_accepted"], 3)
        self.assertEqual(summary["total_rejected"], 4)
        self.assertEqual(summary["total_no_candidate"], 2)
        self.assertEqual(summary["rejection_reasons"], {
            DECISION_REJECTED_IRRELEVANT: 1,
            DECISION_REJECTED_LOW_RELIABILITY: 2,
            DECISION_REJECTED_INSUFFICIENT_EVIDENCE: 1,
        })
        self.assertAlmostEqual(summary["acceptance_rate"], 3 / 9)
        self.assertAlmostEqual(summary["rejection_rate"], 4 / 9)

    def test_recording_one_at_a_time_matches_summarizing_a_batch(self):
        traces = [ACCEPTED_TRACE, IRRELEVANT_TRACE, NO_CANDIDATE_TRACE, ACCEPTED_TRACE]
        stats = LearnedKnowledgeDecisionStatistics()
        for trace in traces:
            stats.record(trace)
        self.assertEqual(stats.summary(), summarize_learned_knowledge_decisions(traces))

    def test_gate_errors_counted_separately_from_rejections_and_no_candidate(self):
        error_trace = build_learned_knowledge_gate_trace("not a real result")
        self.assertEqual(error_trace.decision, DECISION_GATE_ERROR)
        summary = summarize_learned_knowledge_decisions([error_trace, ACCEPTED_TRACE])
        self.assertEqual(summary["total_evaluations"], 2)
        self.assertEqual(summary["total_gate_errors"], 1)
        self.assertEqual(summary["total_rejected"], 0)
        self.assertEqual(summary["total_no_candidate"], 0)

    def test_unrecognized_or_none_decisions_are_not_counted(self):
        stats = LearnedKnowledgeDecisionStatistics()
        for junk in (None, "not a trace", 42, {"decision": "something_new"}, object()):
            stats.record(junk)
        self.assertEqual(stats.summary()["total_evaluations"], 0)

    def test_accepts_plain_dicts_as_well_as_trace_objects(self):
        as_dict = ACCEPTED_TRACE.to_dict()
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(as_dict)
        self.assertEqual(stats.summary()["total_accepted"], 1)

    def test_reset_zeroes_all_counters(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        stats.record(IRRELEVANT_TRACE)
        stats.reset()
        self.assertEqual(stats.summary(), LearnedKnowledgeDecisionStatistics().summary())


# ----------------------------------------------------------------------
# 4/5. no mutation of traces or learned records; decision is unaffected
# ----------------------------------------------------------------------
class TestPurity(Case):

    def test_recording_does_not_mutate_the_trace(self):
        before = copy.deepcopy(ACCEPTED_TRACE.to_dict())
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        self.assertEqual(ACCEPTED_TRACE.to_dict(), before)

    def test_summarizing_does_not_mutate_input_traces(self):
        traces = [ACCEPTED_TRACE, IRRELEVANT_TRACE, NO_CANDIDATE_TRACE]
        before = [copy.deepcopy(t.to_dict()) for t in traces]
        summarize_learned_knowledge_decisions(traces)
        after = [t.to_dict() for t in traces]
        self.assertEqual(before, after)

    def test_statistics_do_not_mutate_learned_records(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.knowledge.relate("Rust", "memory safety", "HAS", confidence=0.95)
        before_knowledge = copy.deepcopy(core.knowledge.all())
        before_relationships = copy.deepcopy(core.knowledge.relationships_for("Rust"))
        gate = self.gate(core)
        trace = build_learned_knowledge_gate_trace(gate)
        core.learned_knowledge_decision_statistics.record(trace)
        self.assertEqual(core.knowledge.all(), before_knowledge)
        self.assertEqual(core.knowledge.relationships_for("Rust"), before_relationships)

    def test_recording_statistics_does_not_change_the_gate_decision(self):
        core_a = self.teach(self.new_core(), confidence=0.9)
        core_b = self.teach(self.new_core(), confidence=0.9)
        gate_a = self.gate(core_a)
        gate_b = self.gate(core_b)
        trace_b = build_learned_knowledge_gate_trace(gate_b)
        LearnedKnowledgeDecisionStatistics().record(trace_b)   # recorded, then discarded
        self.assertEqual((gate_a.status, gate_a.reason), (gate_b.status, gate_b.reason))

    def test_core_accumulates_statistics_without_changing_the_reply(self):
        core = self.teach(self.new_core(), confidence=0.4)
        control = self.teach(self.new_core(), confidence=0.4)
        reply = core.process_input(QUESTION)
        self.assertEqual(reply, control.process_input(QUESTION))
        self.assertEqual(core.learned_knowledge_decision_statistics.summary()["total_evaluations"], 1)
        self.assertEqual(
            core.learned_knowledge_decision_statistics.summary()["rejection_reasons"]
            [DECISION_REJECTED_LOW_RELIABILITY], 1)

    def test_core_accepted_evaluation_is_counted(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        summary = core.learned_knowledge_decision_statistics.summary()
        self.assertEqual(summary["total_accepted"], 1)
        self.assertEqual(summary["total_evaluations"], 1)

    def test_statistics_not_in_the_generation_request(self):
        core = self.teach(self.new_core(), confidence=0.9)
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        core.process_input(QUESTION)
        request = runtime.requests[0]
        self.assertNotIn("acceptance_rate", repr(request.generation_context))
        self.assertNotIn("total_evaluations", repr(request.generation_request))


# ----------------------------------------------------------------------
# 6. Prompt 500, 502, 503 unchanged
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

    def test_nothing_selected_still_means_no_gate_verdict_or_trace(self):
        core = self.new_core()
        core.understand_language("What is the weather?")
        self.assertIsNone(core.last_learned_knowledge_gate)
        self.assertIsNone(core.last_learned_knowledge_gate_trace)
        # the early-return-before-gate path is unchanged by Prompt 504, so
        # this particular (unselected) evaluation is not tallied either
        self.assertEqual(
            core.learned_knowledge_decision_statistics.summary()["total_evaluations"], 0)


if __name__ == "__main__":
    unittest.main()
