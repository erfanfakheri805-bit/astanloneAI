"""
Tests for Prompt 507 - Learned Knowledge Analysis Summary.

`build_learned_knowledge_analysis_summary()` (and
`LearnedKnowledgeDecisionStatistics.summarize_analysis()`) turns an
already-computed Prompt 505 analysis dict, together with its
already-computed Prompt 506 validation dict, into one more plain dict
with a short human-readable `"text"` line. It performs no counting or
structural checking of its own, never mutates its inputs, never
touches the underlying statistics/traces/learned records, and is not
wired into the gate/decision/response path.

Covers:
    1. valid analysis result produces a correct summary
    2. invalid analysis result produces an invalid summary state
    3. validation errors are preserved
    4. zero evaluations handled safely
    5. accepted/rejected/no-candidate counts represented correctly
    6. rates represented correctly
    7. dominant rejection reason represented correctly
    8. no dominant rejection reason handled safely
    9. determinism
    10. no mutation of analysis / statistics / traces / learned records
    11. Prompt 506/505/504/503/502/500 behavior unchanged

Run directly:
    python -m unittest tests.test_learned_knowledge_analysis_summary -v
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
    DECISION_ACCEPTED, DECISION_REJECTED_LOW_RELIABILITY,
    LearnedKnowledgeGateResult,
    evaluate_learned_knowledge_gate, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    summarize_learned_knowledge_decisions,
    analyze_learned_knowledge_statistics,
    validate_learned_knowledge_statistics_analysis,
    build_learned_knowledge_analysis_summary,
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


def _mixed_analysis():
    traces = [
        ACCEPTED_TRACE, ACCEPTED_TRACE, ACCEPTED_TRACE,
        IRRELEVANT_TRACE,
        LOW_RELIABILITY_TRACE, LOW_RELIABILITY_TRACE,
        NO_CANDIDATE_TRACE, NO_CANDIDATE_TRACE,
    ]
    return analyze_learned_knowledge_statistics(summarize_learned_knowledge_decisions(traces))


class Case(GuardCase):

    def new_core(self):
        core, _tmp = _core(self)
        return core

    def teach(self, core, name="Rust", description="A systems programming language.",
              confidence=None):
        core.learning.teach(name, description, source="user", confidence=confidence)
        return core


# ----------------------------------------------------------------------
# 1. valid analysis result produces a correct summary
# ----------------------------------------------------------------------
class TestValidSummary(unittest.TestCase):

    def test_valid_mixed_analysis_summary(self):
        analysis = _mixed_analysis()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertTrue(validation["valid"])
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["errors"], [])
        self.assertIsInstance(summary["text"], str)
        self.assertGreater(len(summary["text"]), 0)


# ----------------------------------------------------------------------
# 2. invalid analysis result produces an invalid summary state
# ----------------------------------------------------------------------
class TestInvalidSummary(unittest.TestCase):

    def test_invalid_analysis_produces_invalid_summary(self):
        analysis = _mixed_analysis()
        analysis["accepted_count"] = -1
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(validation["valid"])
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertFalse(summary["valid"])
        # invalid path never fabricates the normally-present structured fields
        self.assertNotIn("total_evaluations", summary)
        self.assertNotIn("acceptance_rate", summary)
        self.assertNotIn("dominant_rejection_reason", summary)

    def test_invalid_summary_does_not_pretend_to_be_valid(self):
        analysis = _mixed_analysis()
        del analysis["total_evaluations"]
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertFalse(summary["valid"])
        self.assertIn("invalid", summary["text"].lower())

    def test_unrecognized_validation_input_is_safely_invalid(self):
        analysis = _mixed_analysis()
        for bad_validation in (None, "nonsense", {}, {"errors": ["x"]}):
            summary = build_learned_knowledge_analysis_summary(analysis, bad_validation)
            self.assertFalse(summary["valid"])
            self.assertIsInstance(summary["errors"], list)


# ----------------------------------------------------------------------
# 3. validation errors are preserved
# ----------------------------------------------------------------------
class TestErrorsPreserved(unittest.TestCase):

    def test_errors_list_matches_validation_exactly(self):
        analysis = _mixed_analysis()
        analysis["accepted_count"] = -1
        analysis["acceptance_rate"] = 5.0
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertEqual(summary["errors"], validation["errors"])
        for error in validation["errors"]:
            self.assertIn(error, summary["text"])


# ----------------------------------------------------------------------
# 4. zero evaluations handled safely
# ----------------------------------------------------------------------
class TestZeroEvaluations(unittest.TestCase):

    def test_zero_evaluations(self):
        analysis = LearnedKnowledgeDecisionStatistics().analyze()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["total_evaluations"], 0)
        self.assertEqual(summary["accepted_count"], 0)
        self.assertEqual(summary["rejected_count"], 0)
        self.assertEqual(summary["no_candidate_count"], 0)
        self.assertIsNone(summary["dominant_rejection_reason"])
        self.assertIn("no evaluations", summary["text"].lower())

    def test_stats_object_convenience_method_matches(self):
        stats = LearnedKnowledgeDecisionStatistics()
        summary = stats.summarize_analysis()
        analysis = stats.analyze()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertEqual(summary, build_learned_knowledge_analysis_summary(analysis, validation))


# ----------------------------------------------------------------------
# 5. counts represented correctly
# ----------------------------------------------------------------------
class TestCountsRepresented(unittest.TestCase):

    def test_counts_match_analysis(self):
        analysis = _mixed_analysis()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertEqual(summary["total_evaluations"], analysis["total_evaluations"])
        self.assertEqual(summary["accepted_count"], analysis["accepted_count"])
        self.assertEqual(summary["rejected_count"], analysis["rejected_count"])
        self.assertEqual(summary["no_candidate_count"], analysis["no_candidate_count"])
        self.assertIn(str(analysis["accepted_count"]), summary["text"])
        self.assertIn(str(analysis["rejected_count"]), summary["text"])
        self.assertIn(str(analysis["no_candidate_count"]), summary["text"])


# ----------------------------------------------------------------------
# 6. rates represented correctly
# ----------------------------------------------------------------------
class TestRatesRepresented(unittest.TestCase):

    def test_rates_match_analysis_exactly_in_structured_fields(self):
        analysis = _mixed_analysis()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertEqual(summary["acceptance_rate"], analysis["acceptance_rate"])
        self.assertEqual(summary["rejection_rate"], analysis["rejection_rate"])

    def test_rates_appear_as_percentages_in_text(self):
        analysis = _mixed_analysis()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        expected_acceptance_pct = "{0:.0%}".format(analysis["acceptance_rate"])
        expected_rejection_pct = "{0:.0%}".format(analysis["rejection_rate"])
        self.assertIn(expected_acceptance_pct, summary["text"])
        self.assertIn(expected_rejection_pct, summary["text"])


# ----------------------------------------------------------------------
# 7. dominant rejection reason represented correctly
# ----------------------------------------------------------------------
class TestDominantReasonRepresented(unittest.TestCase):

    def test_dominant_reason_appears_in_text_and_field(self):
        analysis = _mixed_analysis()
        self.assertEqual(analysis["dominant_rejection_reason"], DECISION_REJECTED_LOW_RELIABILITY)
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertEqual(summary["dominant_rejection_reason"], DECISION_REJECTED_LOW_RELIABILITY)
        self.assertIn(DECISION_REJECTED_LOW_RELIABILITY, summary["text"])


# ----------------------------------------------------------------------
# 8. no dominant rejection reason handled safely
# ----------------------------------------------------------------------
class TestNoDominantReason(unittest.TestCase):

    def test_only_accepted_has_no_dominant_reason(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        analysis = stats.analyze()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertTrue(summary["valid"])
        self.assertIsNone(summary["dominant_rejection_reason"])
        self.assertIn("no dominant rejection reason", summary["text"].lower())


# ----------------------------------------------------------------------
# 9. determinism
# ----------------------------------------------------------------------
class TestDeterminism(unittest.TestCase):

    def test_repeated_calls_are_identical(self):
        analysis = _mixed_analysis()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        first = build_learned_knowledge_analysis_summary(analysis, validation)
        second = build_learned_knowledge_analysis_summary(copy.deepcopy(analysis), copy.deepcopy(validation))
        self.assertEqual(first, second)


# ----------------------------------------------------------------------
# 10. no mutation
# ----------------------------------------------------------------------
class TestNoMutation(unittest.TestCase):

    def test_does_not_mutate_analysis_or_validation(self):
        analysis = _mixed_analysis()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        analysis_before = copy.deepcopy(analysis)
        validation_before = copy.deepcopy(validation)
        build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertEqual(analysis, analysis_before)
        self.assertEqual(validation, validation_before)

    def test_does_not_mutate_invalid_analysis_or_validation(self):
        analysis = _mixed_analysis()
        analysis["accepted_count"] = -1
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        analysis_before = copy.deepcopy(analysis)
        validation_before = copy.deepcopy(validation)
        build_learned_knowledge_analysis_summary(analysis, validation)
        self.assertEqual(analysis, analysis_before)
        self.assertEqual(validation, validation_before)

    def test_does_not_mutate_underlying_statistics(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        stats.record(LOW_RELIABILITY_TRACE)
        before = copy.deepcopy(stats.summary())
        stats.summarize_analysis()
        after = stats.summary()
        self.assertEqual(before, after)

    def test_does_not_mutate_trace_objects(self):
        traces = [ACCEPTED_TRACE, LOW_RELIABILITY_TRACE, NO_CANDIDATE_TRACE]
        before = [copy.deepcopy(trace.to_dict()) for trace in traces]
        analysis = analyze_learned_knowledge_statistics(
            summarize_learned_knowledge_decisions(traces))
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        build_learned_knowledge_analysis_summary(analysis, validation)
        after = [trace.to_dict() for trace in traces]
        self.assertEqual(before, after)


# ----------------------------------------------------------------------
# 11. earlier prompts unchanged
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

    def test_prompt_505_analysis_shape_unchanged(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        analysis = core.learned_knowledge_decision_statistics.analyze()
        self.assertEqual(analysis["accepted_count"], 1)
        self.assertIsNone(analysis["dominant_rejection_reason"])

    def test_prompt_506_validation_shape_unchanged(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        analysis = core.learned_knowledge_decision_statistics.analyze()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["errors"], [])

    def test_summary_not_in_the_generation_request(self):
        core = self.teach(self.new_core(), confidence=0.9)
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        core.process_input(QUESTION)
        request = runtime.requests[0]
        self.assertNotIn("dominant_rejection_reason", repr(request.generation_context))
        self.assertNotIn("Learned knowledge analysis", repr(request.generation_request))


if __name__ == "__main__":
    unittest.main()
