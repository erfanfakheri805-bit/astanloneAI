"""
Tests for Prompt 505 - Learned Knowledge Decision Statistics Analysis.

`analyze_learned_knowledge_statistics()` (and
`LearnedKnowledgeDecisionStatistics.analyze()`) is a small, deterministic,
read-only diagnostic layer over the Prompt 504 statistics structure
(`learning/learned_knowledge_statistics.py`). It reuses that structure
directly - no second statistics system, no re-evaluation of relevance
or reliability, no mutation of the statistics object, its counters, or
any trace/learned record it was built from.

Covers:
    1. zero evaluations -> safe deterministic empty-state result
    2. only accepted decisions
    3. only rejected decisions (each rejection kind)
    4. only no-candidate decisions
    5. mixed decisions -> correct counts/rates and dominant reason
    6. ties between rejection reasons handled deterministically
    7. no rejected decisions -> dominant_rejection_reason is None
    8. analysis does not mutate the statistics object or its summary
    9. analysis does not affect decision traces or response generation
    10. Prompt 504/503/502/500 behavior unchanged

Run directly:
    python -m unittest tests.test_learned_knowledge_statistics_analysis -v
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
    REASON_NO_EVIDENCE, REASON_INSUFFICIENT_RELIABILITY,
    DECISION_ACCEPTED, DECISION_REJECTED_IRRELEVANT, DECISION_REJECTED_LOW_RELIABILITY,
    DECISION_REJECTED_INSUFFICIENT_EVIDENCE, DECISION_NO_CANDIDATE,
    LearnedKnowledgeGateResult,
    evaluate_learned_knowledge_gate, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    summarize_learned_knowledge_decisions,
    analyze_learned_knowledge_statistics,
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


# ----------------------------------------------------------------------
# 1. zero evaluations
# ----------------------------------------------------------------------
class TestZeroEvaluations(unittest.TestCase):

    def test_fresh_statistics_object_analysis_is_empty_state(self):
        analysis = LearnedKnowledgeDecisionStatistics().analyze()
        self.assertEqual(analysis["total_evaluations"], 0)
        self.assertEqual(analysis["accepted_count"], 0)
        self.assertEqual(analysis["rejected_count"], 0)
        self.assertEqual(analysis["no_candidate_count"], 0)
        self.assertEqual(analysis["acceptance_rate"], 0.0)
        self.assertEqual(analysis["rejection_rate"], 0.0)
        self.assertIsNone(analysis["dominant_rejection_reason"])

    def test_empty_summary_dict_is_empty_state(self):
        summary = summarize_learned_knowledge_decisions([])
        analysis = analyze_learned_knowledge_statistics(summary)
        self.assertEqual(analysis["total_evaluations"], 0)
        self.assertIsNone(analysis["dominant_rejection_reason"])

    def test_none_and_unrecognized_input_are_safe(self):
        self.assertEqual(analyze_learned_knowledge_statistics(None)["total_evaluations"], 0)
        self.assertEqual(analyze_learned_knowledge_statistics({})["total_evaluations"], 0)
        self.assertEqual(analyze_learned_knowledge_statistics("nonsense")["total_evaluations"], 0)


# ----------------------------------------------------------------------
# 2. only accepted decisions
# ----------------------------------------------------------------------
class TestOnlyAccepted(unittest.TestCase):

    def test_only_accepted(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        stats.record(ACCEPTED_TRACE)
        analysis = stats.analyze()
        self.assertEqual(analysis["total_evaluations"], 2)
        self.assertEqual(analysis["accepted_count"], 2)
        self.assertEqual(analysis["rejected_count"], 0)
        self.assertEqual(analysis["no_candidate_count"], 0)
        self.assertEqual(analysis["acceptance_rate"], 1.0)
        self.assertEqual(analysis["rejection_rate"], 0.0)
        self.assertIsNone(analysis["dominant_rejection_reason"])


# ----------------------------------------------------------------------
# 3. only rejected decisions
# ----------------------------------------------------------------------
class TestOnlyRejected(unittest.TestCase):

    def test_only_one_rejection_kind(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(LOW_RELIABILITY_TRACE)
        stats.record(LOW_RELIABILITY_TRACE)
        analysis = stats.analyze()
        self.assertEqual(analysis["rejected_count"], 2)
        self.assertEqual(analysis["rejection_rate"], 1.0)
        self.assertEqual(analysis["dominant_rejection_reason"], DECISION_REJECTED_LOW_RELIABILITY)

    def test_dominant_reason_is_the_highest_count(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(IRRELEVANT_TRACE)
        stats.record(LOW_RELIABILITY_TRACE)
        stats.record(LOW_RELIABILITY_TRACE)
        stats.record(LOW_RELIABILITY_TRACE)
        stats.record(INSUFFICIENT_EVIDENCE_TRACE)
        analysis = stats.analyze()
        self.assertEqual(analysis["dominant_rejection_reason"], DECISION_REJECTED_LOW_RELIABILITY)


# ----------------------------------------------------------------------
# 4. only no-candidate decisions
# ----------------------------------------------------------------------
class TestOnlyNoCandidate(unittest.TestCase):

    def test_only_no_candidate(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(NO_CANDIDATE_TRACE)
        stats.record(NO_CANDIDATE_TRACE)
        analysis = stats.analyze()
        self.assertEqual(analysis["total_evaluations"], 2)
        self.assertEqual(analysis["no_candidate_count"], 2)
        self.assertEqual(analysis["rejected_count"], 0)
        self.assertEqual(analysis["acceptance_rate"], 0.0)
        self.assertEqual(analysis["rejection_rate"], 0.0)
        self.assertIsNone(analysis["dominant_rejection_reason"])


# ----------------------------------------------------------------------
# 5. mixed decisions
# ----------------------------------------------------------------------
class TestMixedDecisions(unittest.TestCase):

    def test_mixed_batch(self):
        traces = [
            ACCEPTED_TRACE, ACCEPTED_TRACE, ACCEPTED_TRACE,
            IRRELEVANT_TRACE,
            LOW_RELIABILITY_TRACE, LOW_RELIABILITY_TRACE,
            INSUFFICIENT_EVIDENCE_TRACE,
            NO_CANDIDATE_TRACE, NO_CANDIDATE_TRACE,
        ]
        summary = summarize_learned_knowledge_decisions(traces)
        analysis = analyze_learned_knowledge_statistics(summary)
        self.assertEqual(analysis["total_evaluations"], 9)
        self.assertEqual(analysis["accepted_count"], 3)
        self.assertEqual(analysis["rejected_count"], 4)
        self.assertEqual(analysis["no_candidate_count"], 2)
        self.assertAlmostEqual(analysis["acceptance_rate"], 3 / 9)
        self.assertAlmostEqual(analysis["rejection_rate"], 4 / 9)
        self.assertEqual(analysis["dominant_rejection_reason"], DECISION_REJECTED_LOW_RELIABILITY)

    def test_analyze_method_matches_module_function(self):
        stats = LearnedKnowledgeDecisionStatistics()
        for trace in (ACCEPTED_TRACE, LOW_RELIABILITY_TRACE, NO_CANDIDATE_TRACE):
            stats.record(trace)
        self.assertEqual(stats.analyze(), analyze_learned_knowledge_statistics(stats))
        self.assertEqual(stats.analyze(), analyze_learned_knowledge_statistics(stats.summary()))


# ----------------------------------------------------------------------
# 6. ties between rejection reasons
# ----------------------------------------------------------------------
class TestTieBreaking(unittest.TestCase):

    def test_two_way_tie_prefers_irrelevant_over_low_reliability(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(IRRELEVANT_TRACE)
        stats.record(LOW_RELIABILITY_TRACE)
        analysis = stats.analyze()
        self.assertEqual(analysis["dominant_rejection_reason"], DECISION_REJECTED_IRRELEVANT)

    def test_three_way_tie_prefers_irrelevant_first(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(INSUFFICIENT_EVIDENCE_TRACE)
        stats.record(LOW_RELIABILITY_TRACE)
        stats.record(IRRELEVANT_TRACE)
        analysis = stats.analyze()
        self.assertEqual(analysis["dominant_rejection_reason"], DECISION_REJECTED_IRRELEVANT)

    def test_tie_between_low_reliability_and_insufficient_evidence(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(LOW_RELIABILITY_TRACE)
        stats.record(INSUFFICIENT_EVIDENCE_TRACE)
        analysis = stats.analyze()
        self.assertEqual(analysis["dominant_rejection_reason"], DECISION_REJECTED_LOW_RELIABILITY)

    def test_tie_result_is_deterministic_across_repeated_calls(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(IRRELEVANT_TRACE)
        stats.record(LOW_RELIABILITY_TRACE)
        stats.record(INSUFFICIENT_EVIDENCE_TRACE)
        first = stats.analyze()
        second = stats.analyze()
        third = analyze_learned_knowledge_statistics(stats.summary())
        self.assertEqual(first, second)
        self.assertEqual(first, third)


# ----------------------------------------------------------------------
# 7. no rejections -> safe None
# ----------------------------------------------------------------------
class TestNoRejections(unittest.TestCase):

    def test_no_rejected_decisions_gives_none_dominant_reason(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        stats.record(NO_CANDIDATE_TRACE)
        analysis = stats.analyze()
        self.assertEqual(analysis["rejected_count"], 0)
        self.assertIsNone(analysis["dominant_rejection_reason"])


# ----------------------------------------------------------------------
# 8. no mutation
# ----------------------------------------------------------------------
class TestNoMutation(unittest.TestCase):

    def test_analysis_does_not_mutate_statistics_object(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        stats.record(LOW_RELIABILITY_TRACE)
        before = copy.deepcopy(stats.summary())
        stats.analyze()
        analyze_learned_knowledge_statistics(stats)
        after = stats.summary()
        self.assertEqual(before, after)

    def test_analysis_does_not_mutate_summary_dict_argument(self):
        summary = summarize_learned_knowledge_decisions(
            [ACCEPTED_TRACE, LOW_RELIABILITY_TRACE, NO_CANDIDATE_TRACE])
        before = copy.deepcopy(summary)
        analyze_learned_knowledge_statistics(summary)
        self.assertEqual(summary, before)

    def test_analysis_result_is_independent_of_later_recording(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        analysis = stats.analyze()
        stats.record(LOW_RELIABILITY_TRACE)
        stats.record(LOW_RELIABILITY_TRACE)
        # the already-returned analysis dict is a snapshot, unaffected
        # by further recording on the (still separately-tracked) stats
        self.assertEqual(analysis["total_evaluations"], 1)
        self.assertEqual(analysis["rejected_count"], 0)

    def test_analysis_does_not_mutate_trace_objects(self):
        traces = [ACCEPTED_TRACE, LOW_RELIABILITY_TRACE, NO_CANDIDATE_TRACE]
        before = [copy.deepcopy(trace.to_dict()) for trace in traces]
        summary = summarize_learned_knowledge_decisions(traces)
        analyze_learned_knowledge_statistics(summary)
        after = [trace.to_dict() for trace in traces]
        self.assertEqual(before, after)


# ----------------------------------------------------------------------
# 9. no effect on gate decisions or response generation
# ----------------------------------------------------------------------
class TestNoEffectOnBehavior(Case):

    def test_analysis_does_not_change_core_gate_decision(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        stats = core.learned_knowledge_decision_statistics
        stats.analyze()
        analyze_learned_knowledge_statistics(stats)
        self.assertEqual(core.last_learned_knowledge_gate_trace.decision, DECISION_ACCEPTED)

    def test_statistics_analysis_not_in_the_generation_request(self):
        core = self.teach(self.new_core(), confidence=0.9)
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        core.process_input(QUESTION)
        request = runtime.requests[0]
        self.assertNotIn("dominant_rejection_reason", repr(request.generation_context))
        self.assertNotIn("accepted_count", repr(request.generation_request))


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


if __name__ == "__main__":
    unittest.main()
