"""
Tests for Prompt 503 - Learned Knowledge Decision Trace.

`build_learned_knowledge_gate_trace()` turns an already-computed
Prompt 502 `LearnedKnowledgeGateResult` into a small structured
`LearnedKnowledgeGateTrace`, for later internal analysis only. It never
re-runs relevance/reliability logic and never changes what the gate
decided; it is not attached to the response.

Covers:
    1. relevant + reliable candidate -> accepted
    2. irrelevant candidate -> rejected_irrelevant
    3. low-reliability candidate -> rejected_low_reliability
    4. insufficient evidence -> rejected_insufficient_evidence
    5. no candidate -> no_candidate
    6. trace information is structurally valid
    7. trace generation does not alter the final response behavior
    8. Prompt 500 correction behavior remains unchanged
    9. Prompt 501 learned-knowledge behavior remains unchanged
    10. Prompt 502 rejection behavior remains unchanged

Run directly:
    python -m unittest tests.test_learned_knowledge_gate_trace -v
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_generation import ResponseGenerationRequest, STATUS_GENERATED
from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
)
from learning.learned_knowledge_gate import (
    STATUS_PASSED, STATUS_REJECTED, REASON_OK, REASON_NOT_SELECTED, REASON_NOT_RELEVANT,
    REASON_NO_EVIDENCE, REASON_INSUFFICIENT_RELIABILITY, REASON_GATE_ERROR,
    DECISION_ACCEPTED, DECISION_REJECTED_IRRELEVANT, DECISION_REJECTED_LOW_RELIABILITY,
    DECISION_REJECTED_INSUFFICIENT_EVIDENCE, DECISION_NO_CANDIDATE, DECISION_GATE_ERROR,
    RELEVANCE_PASSED, RELEVANCE_FAILED, RELEVANCE_NOT_EVALUATED,
    RELIABILITY_RELIABLE, RELIABILITY_UNRELIABLE, RELIABILITY_INSUFFICIENT_EVIDENCE,
    RELIABILITY_NOT_EVALUATED,
    LearnedKnowledgeGateResult, LearnedKnowledgeGateTrace,
    evaluate_learned_knowledge_gate, build_learned_knowledge_gate_trace,
)

from tests.test_pre_inference_readiness_guard import GuardCase, MODEL_TEXT, _core
from tests.test_local_inference_response_generation import TextRuntime

QUESTION = "Tell me about Rust"


def _instruction():
    return VerifiedCorrectionResponseInstruction(
        source_text="I has a dgo", corrected_text="I has a dog",
        matched_text="dgo", replacement_text="dog", match_count=1)


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

    def trace(self, core, message=QUESTION):
        return build_learned_knowledge_gate_trace(self.gate(core, message))


# ----------------------------------------------------------------------
# 1. relevant + reliable -> accepted
# ----------------------------------------------------------------------
class TestAcceptedTrace(Case):

    def test_accepted_trace(self):
        trace = self.trace(self.teach(self.new_core(), confidence=0.9))
        self.assertEqual(trace.decision, DECISION_ACCEPTED)
        self.assertTrue(trace.had_candidate)
        self.assertEqual(trace.relevance_result, RELEVANCE_PASSED)
        self.assertEqual(trace.reliability_result, RELIABILITY_RELIABLE)
        self.assertEqual(trace.gate_status, STATUS_PASSED)
        self.assertIsNone(trace.rejection_reason)
        self.assertEqual(trace.supporting_records, 1)
        self.assertAlmostEqual(trace.average_confidence, 0.9)

    def test_core_records_the_trace_for_an_accepted_item(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        self.assertEqual(core.last_learned_knowledge_gate_trace.decision, DECISION_ACCEPTED)


# ----------------------------------------------------------------------
# 2. irrelevant -> rejected_irrelevant
# ----------------------------------------------------------------------
class TestIrrelevantTrace(Case):

    def test_irrelevant_trace(self):
        core = self.teach(self.new_core())
        gate = evaluate_learned_knowledge_gate(
            self.selection(core), message="What is the weather?")
        trace = build_learned_knowledge_gate_trace(gate)
        self.assertEqual(trace.decision, DECISION_REJECTED_IRRELEVANT)
        self.assertTrue(trace.had_candidate)
        self.assertEqual(trace.relevance_result, RELEVANCE_FAILED)
        self.assertEqual(trace.reliability_result, RELIABILITY_NOT_EVALUATED)
        self.assertEqual(trace.gate_status, STATUS_REJECTED)
        self.assertEqual(trace.rejection_reason, REASON_NOT_RELEVANT)

    def test_core_records_the_trace_for_an_irrelevant_item(self):
        core = self.teach(self.new_core())
        core.understand_language("What is the weather?")
        self.assertIsNone(core.last_learned_knowledge_gate_trace)  # not selected at all


# ----------------------------------------------------------------------
# 3. low reliability -> rejected_low_reliability
# ----------------------------------------------------------------------
class TestLowReliabilityTrace(Case):

    def test_low_reliability_trace(self):
        trace = self.trace(self.teach(self.new_core(), confidence=0.4))
        self.assertEqual(trace.decision, DECISION_REJECTED_LOW_RELIABILITY)
        self.assertTrue(trace.had_candidate)
        self.assertEqual(trace.relevance_result, RELEVANCE_PASSED)
        self.assertEqual(trace.reliability_result, RELIABILITY_UNRELIABLE)
        self.assertEqual(trace.rejection_reason, REASON_INSUFFICIENT_RELIABILITY)
        self.assertAlmostEqual(trace.average_confidence, 0.4)

    def test_core_records_the_trace_for_a_low_reliability_item(self):
        core = self.teach(self.new_core(), confidence=0.4)
        core.understand_language(QUESTION)
        self.assertEqual(
            core.last_learned_knowledge_gate_trace.decision, DECISION_REJECTED_LOW_RELIABILITY)


# ----------------------------------------------------------------------
# 4. insufficient evidence -> rejected_insufficient_evidence
# ----------------------------------------------------------------------
class TestInsufficientEvidenceTrace(Case):

    def test_insufficient_evidence_trace(self):
        core = self.teach(self.new_core())
        core.memory._run("UPDATE knowledge SET confidence = ? WHERE name = ?", (5.0, "Rust"))
        trace = self.trace(core)
        self.assertEqual(trace.decision, DECISION_REJECTED_INSUFFICIENT_EVIDENCE)
        self.assertTrue(trace.had_candidate)
        self.assertEqual(trace.relevance_result, RELEVANCE_PASSED)
        self.assertEqual(trace.reliability_result, RELIABILITY_INSUFFICIENT_EVIDENCE)
        self.assertEqual(trace.rejection_reason, REASON_NO_EVIDENCE)
        self.assertEqual(trace.supporting_records, 0)


# ----------------------------------------------------------------------
# 5. no candidate -> no_candidate
# ----------------------------------------------------------------------
class TestNoCandidateTrace(Case):

    def test_no_candidate_trace(self):
        core = self.new_core()
        not_found = core.select_learned_knowledge("What is the weather?")
        gate = evaluate_learned_knowledge_gate(not_found)
        trace = build_learned_knowledge_gate_trace(gate)
        self.assertEqual(trace.decision, DECISION_NO_CANDIDATE)
        self.assertFalse(trace.had_candidate)
        self.assertEqual(trace.relevance_result, RELEVANCE_NOT_EVALUATED)
        self.assertEqual(trace.reliability_result, RELIABILITY_NOT_EVALUATED)
        self.assertEqual(trace.rejection_reason, REASON_NOT_SELECTED)

    def test_gate_error_is_a_distinct_state_from_no_candidate(self):
        core = self.teach(self.new_core())
        gate = evaluate_learned_knowledge_gate(self.selection(core), min_confidence="x")
        self.assertEqual(gate.reason, REASON_GATE_ERROR)
        trace = build_learned_knowledge_gate_trace(gate)
        self.assertEqual(trace.decision, DECISION_GATE_ERROR)
        self.assertNotEqual(trace.decision, DECISION_NO_CANDIDATE)  # distinguished from no_candidate


# ----------------------------------------------------------------------
# 6. trace information is structurally valid
# ----------------------------------------------------------------------
class TestTraceStructure(Case):

    REQUIRED_KEYS = {
        "decision", "had_candidate", "relevance_result", "reliability_result",
        "gate_status", "supporting_records", "average_confidence", "success_rate",
        "min_confidence", "rejection_reason", "detail",
    }

    def test_to_dict_has_all_required_keys(self):
        trace = self.trace(self.teach(self.new_core(), confidence=0.9))
        self.assertEqual(set(trace.to_dict().keys()), self.REQUIRED_KEYS)

    def test_decision_is_always_one_of_the_known_states(self):
        known = {DECISION_ACCEPTED, DECISION_REJECTED_IRRELEVANT, DECISION_REJECTED_LOW_RELIABILITY,
                 DECISION_REJECTED_INSUFFICIENT_EVIDENCE, DECISION_NO_CANDIDATE, DECISION_GATE_ERROR}
        cases = [
            self.gate(self.teach(self.new_core(), confidence=0.9)),
            evaluate_learned_knowledge_gate(
                self.selection(self.teach(self.new_core())), message="unrelated text"),
            self.gate(self.teach(self.new_core(), confidence=0.1)),
            evaluate_learned_knowledge_gate(self.new_core().select_learned_knowledge("hi")),
            evaluate_learned_knowledge_gate(object()),
        ]
        for gate in cases:
            with self.subTest(reason=gate.reason):
                self.assertIn(build_learned_knowledge_gate_trace(gate).decision, known)

    def test_had_candidate_is_a_bool_and_only_false_for_not_selected(self):
        for gate in (self.gate(self.teach(self.new_core(), confidence=0.9)),
                     evaluate_learned_knowledge_gate(self.new_core().select_learned_knowledge("hi"))):
            trace = build_learned_knowledge_gate_trace(gate)
            self.assertIsInstance(trace.had_candidate, bool)
            self.assertEqual(trace.had_candidate, gate.reason != REASON_NOT_SELECTED)

    def test_rejection_reason_is_none_only_when_accepted(self):
        accepted = self.trace(self.teach(self.new_core(), confidence=0.9))
        rejected = self.trace(self.teach(self.new_core(), confidence=0.1))
        self.assertIsNone(accepted.rejection_reason)
        self.assertIsNotNone(rejected.rejection_reason)

    def test_trace_never_raises_on_an_unrecognized_result(self):
        for bad in (None, "not a result", 42, object()):
            with self.subTest(bad=bad):
                trace = build_learned_knowledge_gate_trace(bad)
                self.assertEqual(trace.decision, DECISION_GATE_ERROR)

    def test_directly_constructing_from_a_plain_result_matches_the_builder(self):
        result = LearnedKnowledgeGateResult(STATUS_PASSED, REASON_OK, supporting_records=2,
                                            average_confidence=0.95, success_rate=1.0)
        via_builder = build_learned_knowledge_gate_trace(result)
        via_class = LearnedKnowledgeGateTrace(result)
        self.assertEqual(via_builder.to_dict(), via_class.to_dict())


# ----------------------------------------------------------------------
# 7. trace generation does not alter the final response behavior
# ----------------------------------------------------------------------
class TestTraceDoesNotAlterBehavior(Case):

    def test_gate_verdict_is_identical_with_or_without_building_a_trace(self):
        core_a = self.teach(self.new_core(), confidence=0.4)
        core_b = self.teach(self.new_core(), confidence=0.4)
        gate_a = self.gate(core_a)
        gate_b = self.gate(core_b)
        build_learned_knowledge_gate_trace(gate_b)   # built, but discarded
        self.assertEqual((gate_a.status, gate_a.reason), (gate_b.status, gate_b.reason))

    def test_response_is_unaffected_by_trace_construction(self):
        # build_learned_knowledge_gate_trace() itself never raises (it catches
        # internally), so building it alongside the gate call never disturbs
        # the accept/attach decision that already happened.
        core = self.teach(self.new_core(), confidence=0.9)
        understanding = core.understand_language(QUESTION)
        expected = core.select_learned_knowledge(QUESTION).to_context()
        self.assertEqual(understanding.learned_knowledge_context, expected)
        self.assertEqual(core.last_learned_knowledge_gate_trace.decision, DECISION_ACCEPTED)

    def test_trace_is_never_attached_to_the_understanding_or_request(self):
        core = self.teach(self.new_core(), confidence=0.9)
        understanding = core.understand_language(QUESTION)
        request = ResponseGenerationRequest(understanding)
        self.assertNotIn("trace", repr(request.generation_context))
        self.assertNotIn("gate_status", repr(request.generation_request))

    def test_reply_text_unaffected_when_trace_available(self):
        core = self.teach(self.new_core(), confidence=0.4)
        control = self.teach(self.new_core(), confidence=0.4)
        reply = core.process_input(QUESTION)
        self.assertEqual(reply, control.process_input(QUESTION))
        self.assertIsNotNone(core.last_learned_knowledge_gate_trace)


# ----------------------------------------------------------------------
# 8. Prompt 500 unchanged
# ----------------------------------------------------------------------
class TestPrompt500StillUnchanged(Case):

    def generate(self, core):
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        understanding = core.understand_language(QUESTION)
        result = core.language_intelligence.generate_response(
            understanding, context=core.context, verified_correction_instruction=_instruction())
        return runtime.requests[0], result

    def test_correction_with_an_accepted_item_and_a_trace_present(self):
        request, result = self.generate(self.teach(self.new_core(), confidence=0.9))
        self.assertIs(result.used_verified_correction, True)
        self.assertEqual(request.generation_request.original_message, "I has a dog")
        self.assertEqual(request.generation_request.learned_knowledge_context["record"]["name"], "Rust")

    def test_correction_with_a_rejected_item_and_a_trace_present(self):
        request, result = self.generate(self.teach(self.new_core(), confidence=0.4))
        self.assertIs(result.used_verified_correction, True)
        self.assertIsNone(request.generation_request.learned_knowledge_context)


# ----------------------------------------------------------------------
# 9. Prompt 501 unchanged
# ----------------------------------------------------------------------
class TestPrompt501StillUnchanged(Case):

    def test_accepted_item_still_reaches_the_local_model_request(self):
        core = self.teach(self.new_core(), confidence=0.9)
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        self.assertEqual(core.process_input(QUESTION), MODEL_TEXT)
        learned = runtime.requests[0].generation_context.to_dict()["learned_knowledge_context"]
        self.assertEqual(learned["record"], core.knowledge.get("Rust"))


# ----------------------------------------------------------------------
# 10. Prompt 502 unchanged
# ----------------------------------------------------------------------
class TestPrompt502StillUnchanged(Case):

    def test_gate_still_never_raises_and_mutates_nothing(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.knowledge.relate("Rust", "memory safety", "HAS", confidence=0.95)
        selection = self.selection(core)
        before_selection = copy.deepcopy(selection.to_dict())
        gate = evaluate_learned_knowledge_gate(selection, message=QUESTION)
        build_learned_knowledge_gate_trace(gate)
        self.assertEqual(selection.to_dict(), before_selection)

    def test_gate_error_still_falls_back_to_the_normal_path(self):
        core = self.teach(self.new_core(), confidence=0.9)
        with mock.patch("core.core.evaluate_learned_knowledge_gate", side_effect=RuntimeError("x")):
            understanding = core.understand_language(QUESTION)
        self.assertIsNone(understanding.learned_knowledge_context)
        self.assertIsNone(core.last_learned_knowledge_gate_trace)

    def test_nothing_selected_still_means_no_gate_verdict_or_trace(self):
        core = self.new_core()
        core.understand_language("What is the weather?")
        self.assertIsNone(core.last_learned_knowledge_gate)
        self.assertIsNone(core.last_learned_knowledge_gate_trace)


if __name__ == "__main__":
    unittest.main()
