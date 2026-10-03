"""
Tests for Prompt 506 - Learned Knowledge Analysis Result Validation.

`validate_learned_knowledge_statistics_analysis()` (and
`LearnedKnowledgeDecisionStatistics.validate_analysis()`) is a small,
deterministic, read-only structural check over the Prompt 505 analysis
result shape. It never repairs or reinterprets an invalid result,
never mutates the analysis dict, the Prompt 504 statistics, any trace,
or any learned record, and plays no part in the actual learned-
knowledge gate decision.

Covers:
    1. a valid analysis result
    2. a missing required field
    3. an invalid count type
    4. a negative count
    5. an invalid rate type
    6. a rate below the valid range
    7. a rate above the valid range
    8. an invalid dominant rejection reason
    9. a valid empty/null dominant rejection reason
    10. an inconsistent total count
    11. an inconsistent acceptance rate
    12. an inconsistent rejection rate
    13. multiple validation errors at once
    14. determinism
    15. no mutation of the analysis result / statistics / traces / learned records
    16. Prompt 505/504/503/502/500 behavior unchanged

Run directly:
    python -m unittest tests.test_learned_knowledge_statistics_analysis_validation -v
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
    LearnedKnowledgeGateResult,
    evaluate_learned_knowledge_gate, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    summarize_learned_knowledge_decisions,
    analyze_learned_knowledge_statistics,
    validate_learned_knowledge_statistics_analysis,
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


def _valid_mixed_analysis():
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
# 1. a valid analysis result
# ----------------------------------------------------------------------
class TestValidAnalysis(unittest.TestCase):

    def test_valid_mixed_analysis_passes(self):
        result = validate_learned_knowledge_statistics_analysis(_valid_mixed_analysis())
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])

    def test_valid_empty_state_analysis_passes(self):
        empty = LearnedKnowledgeDecisionStatistics().analyze()
        result = validate_learned_knowledge_statistics_analysis(empty)
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_non_dict_input_is_safely_invalid(self):
        for bad in (None, "nonsense", 42, ["a", "list"]):
            result = validate_learned_knowledge_statistics_analysis(bad)
            self.assertFalse(result["valid"])
            self.assertEqual(result["errors"], ["analysis_not_a_dict"])


# ----------------------------------------------------------------------
# 2. missing required field
# ----------------------------------------------------------------------
class TestMissingField(unittest.TestCase):

    def test_missing_single_field(self):
        analysis = _valid_mixed_analysis()
        del analysis["dominant_rejection_reason"]
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(result["valid"])
        self.assertIn("missing_field:dominant_rejection_reason", result["errors"])

    def test_missing_field_does_not_cascade_into_consistency_errors(self):
        analysis = _valid_mixed_analysis()
        del analysis["total_evaluations"]
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertIn("missing_field:total_evaluations", result["errors"])
        self.assertNotIn("counts_exceed_total_evaluations", result["errors"])
        self.assertNotIn("inconsistent_acceptance_rate", result["errors"])
        self.assertNotIn("inconsistent_rejection_rate", result["errors"])


# ----------------------------------------------------------------------
# 3. invalid count type
# ----------------------------------------------------------------------
class TestInvalidCountType(unittest.TestCase):

    def test_string_count(self):
        analysis = _valid_mixed_analysis()
        analysis["accepted_count"] = "3"
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(result["valid"])
        self.assertIn("invalid_count_type:accepted_count", result["errors"])

    def test_float_count_is_invalid(self):
        analysis = _valid_mixed_analysis()
        analysis["rejected_count"] = 3.0
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertIn("invalid_count_type:rejected_count", result["errors"])

    def test_bool_count_is_invalid(self):
        analysis = _valid_mixed_analysis()
        analysis["no_candidate_count"] = True
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertIn("invalid_count_type:no_candidate_count", result["errors"])


# ----------------------------------------------------------------------
# 4. negative count
# ----------------------------------------------------------------------
class TestNegativeCount(unittest.TestCase):

    def test_negative_count(self):
        analysis = _valid_mixed_analysis()
        analysis["accepted_count"] = -1
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(result["valid"])
        self.assertIn("negative_count:accepted_count", result["errors"])


# ----------------------------------------------------------------------
# 5. invalid rate type
# ----------------------------------------------------------------------
class TestInvalidRateType(unittest.TestCase):

    def test_string_rate(self):
        analysis = _valid_mixed_analysis()
        analysis["acceptance_rate"] = "0.5"
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(result["valid"])
        self.assertIn("invalid_rate_type:acceptance_rate", result["errors"])

    def test_bool_rate_is_invalid(self):
        analysis = _valid_mixed_analysis()
        analysis["rejection_rate"] = False
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertIn("invalid_rate_type:rejection_rate", result["errors"])


# ----------------------------------------------------------------------
# 6. rate below valid range
# ----------------------------------------------------------------------
class TestRateBelowRange(unittest.TestCase):

    def test_negative_rate(self):
        analysis = _valid_mixed_analysis()
        analysis["acceptance_rate"] = -0.1
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(result["valid"])
        self.assertIn("rate_below_valid_range:acceptance_rate", result["errors"])


# ----------------------------------------------------------------------
# 7. rate above valid range
# ----------------------------------------------------------------------
class TestRateAboveRange(unittest.TestCase):

    def test_rate_over_one(self):
        analysis = _valid_mixed_analysis()
        analysis["rejection_rate"] = 1.1
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(result["valid"])
        self.assertIn("rate_above_valid_range:rejection_rate", result["errors"])


# ----------------------------------------------------------------------
# 8. invalid dominant rejection reason
# ----------------------------------------------------------------------
class TestInvalidDominantReason(unittest.TestCase):

    def test_unrecognized_string_reason(self):
        analysis = _valid_mixed_analysis()
        analysis["dominant_rejection_reason"] = "not_a_real_reason"
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(result["valid"])
        self.assertIn("invalid_dominant_rejection_reason", result["errors"])

    def test_accepted_decision_is_not_a_valid_rejection_reason(self):
        analysis = _valid_mixed_analysis()
        analysis["dominant_rejection_reason"] = DECISION_ACCEPTED
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertIn("invalid_dominant_rejection_reason", result["errors"])


# ----------------------------------------------------------------------
# 9. valid empty/null dominant rejection reason
# ----------------------------------------------------------------------
class TestValidNullDominantReason(unittest.TestCase):

    def test_none_is_valid_when_present(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        analysis = stats.analyze()
        self.assertIsNone(analysis["dominant_rejection_reason"])
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertTrue(result["valid"])

    def test_real_rejection_reason_is_valid(self):
        analysis = _valid_mixed_analysis()
        self.assertEqual(analysis["dominant_rejection_reason"], DECISION_REJECTED_LOW_RELIABILITY)
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertTrue(result["valid"])


# ----------------------------------------------------------------------
# 10. inconsistent total count
# ----------------------------------------------------------------------
class TestInconsistentTotal(unittest.TestCase):

    def test_component_counts_exceed_total(self):
        analysis = _valid_mixed_analysis()
        analysis["total_evaluations"] = (
            analysis["accepted_count"] + analysis["rejected_count"]
            + analysis["no_candidate_count"] - 1
        )
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(result["valid"])
        self.assertIn("counts_exceed_total_evaluations", result["errors"])

    def test_total_greater_than_components_is_allowed(self):
        # Prompt 504's own total_evaluations also counts DECISION_GATE_ERROR,
        # which Prompt 505's analysis does not expose - so a total strictly
        # larger than accepted+rejected+no_candidate is not itself an error.
        analysis = _valid_mixed_analysis()
        analysis["total_evaluations"] = (
            analysis["accepted_count"] + analysis["rejected_count"]
            + analysis["no_candidate_count"] + 2
        )
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertNotIn("counts_exceed_total_evaluations", result["errors"])


# ----------------------------------------------------------------------
# 11. inconsistent acceptance rate
# ----------------------------------------------------------------------
class TestInconsistentAcceptanceRate(unittest.TestCase):

    def test_wrong_acceptance_rate(self):
        analysis = _valid_mixed_analysis()
        analysis["acceptance_rate"] = 0.0
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(result["valid"])
        self.assertIn("inconsistent_acceptance_rate", result["errors"])


# ----------------------------------------------------------------------
# 12. inconsistent rejection rate
# ----------------------------------------------------------------------
class TestInconsistentRejectionRate(unittest.TestCase):

    def test_wrong_rejection_rate(self):
        analysis = _valid_mixed_analysis()
        analysis["rejection_rate"] = 1.0
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(result["valid"])
        self.assertIn("inconsistent_rejection_rate", result["errors"])


# ----------------------------------------------------------------------
# 13. multiple validation errors
# ----------------------------------------------------------------------
class TestMultipleErrors(unittest.TestCase):

    def test_several_problems_are_all_reported(self):
        analysis = _valid_mixed_analysis()
        analysis["accepted_count"] = -1
        analysis["acceptance_rate"] = 1.5
        analysis["dominant_rejection_reason"] = "bogus"
        del analysis["no_candidate_count"]
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertFalse(result["valid"])
        self.assertIn("negative_count:accepted_count", result["errors"])
        self.assertIn("rate_above_valid_range:acceptance_rate", result["errors"])
        self.assertIn("invalid_dominant_rejection_reason", result["errors"])
        self.assertIn("missing_field:no_candidate_count", result["errors"])
        self.assertGreaterEqual(len(result["errors"]), 4)


# ----------------------------------------------------------------------
# 14. determinism
# ----------------------------------------------------------------------
class TestDeterminism(unittest.TestCase):

    def test_repeated_calls_are_identical(self):
        analysis = _valid_mixed_analysis()
        first = validate_learned_knowledge_statistics_analysis(analysis)
        second = validate_learned_knowledge_statistics_analysis(analysis)
        third = validate_learned_knowledge_statistics_analysis(copy.deepcopy(analysis))
        self.assertEqual(first, second)
        self.assertEqual(first, third)

    def test_error_order_is_stable_across_calls(self):
        analysis = _valid_mixed_analysis()
        analysis["accepted_count"] = -1
        analysis["rejection_rate"] = 5.0
        first = validate_learned_knowledge_statistics_analysis(analysis)["errors"]
        second = validate_learned_knowledge_statistics_analysis(analysis)["errors"]
        self.assertEqual(first, second)


# ----------------------------------------------------------------------
# 15. no mutation
# ----------------------------------------------------------------------
class TestNoMutation(unittest.TestCase):

    def test_does_not_mutate_analysis_dict(self):
        analysis = _valid_mixed_analysis()
        before = copy.deepcopy(analysis)
        validate_learned_knowledge_statistics_analysis(analysis)
        self.assertEqual(analysis, before)

    def test_does_not_mutate_invalid_analysis_dict(self):
        analysis = _valid_mixed_analysis()
        analysis["accepted_count"] = -1
        before = copy.deepcopy(analysis)
        validate_learned_knowledge_statistics_analysis(analysis)
        self.assertEqual(analysis, before)

    def test_does_not_mutate_underlying_statistics(self):
        stats = LearnedKnowledgeDecisionStatistics()
        stats.record(ACCEPTED_TRACE)
        stats.record(LOW_RELIABILITY_TRACE)
        before = copy.deepcopy(stats.summary())
        stats.validate_analysis()
        validate_learned_knowledge_statistics_analysis(stats.analyze())
        self.assertEqual(stats.summary(), before)

    def test_does_not_mutate_trace_objects(self):
        traces = [ACCEPTED_TRACE, LOW_RELIABILITY_TRACE, NO_CANDIDATE_TRACE]
        before = [copy.deepcopy(trace.to_dict()) for trace in traces]
        analysis = analyze_learned_knowledge_statistics(
            summarize_learned_knowledge_decisions(traces))
        validate_learned_knowledge_statistics_analysis(analysis)
        after = [trace.to_dict() for trace in traces]
        self.assertEqual(before, after)


# ----------------------------------------------------------------------
# 16. earlier prompts unchanged
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
        self.assertEqual(analysis["total_evaluations"], 1)
        self.assertIsNone(analysis["dominant_rejection_reason"])
        result = validate_learned_knowledge_statistics_analysis(analysis)
        self.assertTrue(result["valid"])

    def test_validation_not_in_the_generation_request(self):
        core = self.teach(self.new_core(), confidence=0.9)
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        core.process_input(QUESTION)
        request = runtime.requests[0]
        self.assertNotIn("valid", repr(request.generation_context))
        self.assertNotIn("errors", repr(request.generation_request))


if __name__ == "__main__":
    unittest.main()
