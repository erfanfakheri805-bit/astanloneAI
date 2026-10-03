"""
Tests for Prompt 502 - Safe Learned-Knowledge Relevance Gate.

Prompt 501 attaches the one directly relevant, already-taught knowledge
entry to the response-generation context. Prompt 502 adds a gate
(learning/learned_knowledge_gate.py) that the selected entry must pass
first: it must still be directly relevant to the message and reliable
according to the existing LearningAnalyzer (average stored confidence at
or above 0.7 over its stored evidence). A rejected entry is simply not
attached - nothing is injected or invented, the request is untouched and
the existing response behavior continues.

Covers:
    1. relevant + reliable item accepted (and still reaches the model request)
    2. irrelevant item rejected
    3. insufficiently reliable item rejected
    4. normal response generation intact when nothing passes
    5. Prompt 500 correction behavior unchanged
    6. reuse of the existing LearningAnalyzer; no mutation; never raises

Run directly:
    python -m unittest tests.test_learned_knowledge_gate -v
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.learned_knowledge_context import (
    LearnedKnowledgeSelection, select_learned_knowledge, STATUS_NOT_FOUND, STATUS_AMBIGUOUS,
)
from language_intelligence.response_generation import ResponseGenerationRequest, STATUS_GENERATED
from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
)
from learning.learned_knowledge_gate import (
    STATUS_PASSED, STATUS_REJECTED, REASON_OK, REASON_NOT_SELECTED, REASON_NOT_RELEVANT,
    REASON_NO_EVIDENCE, REASON_INSUFFICIENT_RELIABILITY, REASON_GATE_ERROR,
    MIN_RELIABLE_CONFIDENCE, evaluate_learned_knowledge_gate,
)
from learning.learning_analyzer import LearningAnalyzer

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


# ----------------------------------------------------------------------
# 1. relevant and reliable -> accepted
# ----------------------------------------------------------------------
class TestReliableRelevantItemIsAccepted(Case):

    def test_reliable_description_is_accepted(self):
        result = self.gate(self.teach(self.new_core(), confidence=0.9))
        self.assertEqual(result.status, STATUS_PASSED)
        self.assertTrue(result.passed)
        self.assertEqual(result.reason, REASON_OK)
        self.assertEqual(result.supporting_records, 1)
        self.assertAlmostEqual(result.average_confidence, 0.9)
        self.assertEqual(result.success_rate, 1.0)

    def test_confidence_not_stated_follows_the_existing_default(self):
        # KnowledgeSystem.learn() stores 1.0 when no confidence is given
        self.assertTrue(self.gate(self.teach(self.new_core())).passed)

    def test_natural_language_taught_facts_are_accepted(self):
        core = self.new_core()
        core.learn_from_text("Python is a programming language.")
        core.learn_from_text("Python uses indentation.")
        result = self.gate(core, "What is Python?")
        self.assertTrue(result.passed)
        self.assertEqual(result.supporting_records, 2)

    def test_relationship_without_a_stated_confidence_is_accepted(self):
        core = self.new_core()
        core.knowledge.relate("Rust", "memory safety", "HAS")   # as AEL RELATE stores it
        self.assertIsNone(core.knowledge.relationships_for("Rust")["outgoing"][0]["confidence"])
        self.assertTrue(self.gate(core).passed)

    def test_threshold_is_the_analyzers_default_and_inclusive(self):
        self.assertEqual(MIN_RELIABLE_CONFIDENCE, 0.7)
        self.assertTrue(self.gate(self.teach(self.new_core(), confidence=0.7)).passed)

    def test_accepted_item_still_reaches_the_response_context_exactly(self):
        core = self.teach(self.new_core(), confidence=0.9)
        understanding = core.understand_language(QUESTION)
        expected = core.select_learned_knowledge(QUESTION).to_context()
        self.assertEqual(understanding.learned_knowledge_context, expected)
        self.assertEqual(
            ResponseGenerationRequest(understanding).generation_context["learned_knowledge_context"],
            expected)
        self.assertTrue(core.last_learned_knowledge_gate.passed)

    def test_accepted_item_reaches_the_local_model_request(self):
        core = self.teach(self.new_core(), confidence=0.9)
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        self.assertEqual(core.process_input(QUESTION), MODEL_TEXT)
        learned = runtime.requests[0].generation_context.to_dict()["learned_knowledge_context"]
        self.assertEqual(learned["record"], core.knowledge.get("Rust"))


# ----------------------------------------------------------------------
# 2. irrelevant -> rejected
# ----------------------------------------------------------------------
class TestIrrelevantItemIsRejected(Case):

    def selected(self, core):
        return self.selection(core).to_dict()

    def test_term_not_in_the_message_is_rejected(self):
        core = self.teach(self.new_core())
        result = evaluate_learned_knowledge_gate(self.selection(core), message="What is the weather?")
        self.assertEqual((result.status, result.reason), (STATUS_REJECTED, REASON_NOT_RELEVANT))

    def test_term_only_inside_a_longer_word_is_rejected(self):
        core = self.teach(self.new_core())
        result = evaluate_learned_knowledge_gate(self.selection(core), message="Tell me about rusty nails")
        self.assertEqual(result.reason, REASON_NOT_RELEVANT)

    def test_matched_term_that_is_not_the_stored_name_is_rejected(self):
        data = self.selected(self.teach(self.new_core()))
        data["matched_term"] = "systems"
        result = evaluate_learned_knowledge_gate(data, message="systems")
        self.assertEqual(result.reason, REASON_NOT_RELEVANT)

    def test_a_forged_selection_for_another_entry_is_rejected(self):
        core = self.teach(self.teach(self.new_core()), "Java", "A managed language.")
        data = self.selected(core)
        data["record"] = core.knowledge.get("Java")          # not what the message names
        self.assertEqual(evaluate_learned_knowledge_gate(data).reason, REASON_NOT_RELEVANT)

    def test_multi_word_names_are_verified_as_consecutive_words(self):
        core = self.new_core()
        core.learn_from_text("Machine learning is a field of study.")
        ok = evaluate_learned_knowledge_gate(
            self.selection(core, "What is machine learning?"), message="What is machine learning?")
        bad = evaluate_learned_knowledge_gate(
            self.selection(core, "What is machine learning?"), message="learning about a machine")
        self.assertTrue(ok.passed)
        self.assertEqual(bad.reason, REASON_NOT_RELEVANT)

    def test_unselected_results_are_rejected(self):
        core = self.teach(self.new_core())
        not_found = core.select_learned_knowledge("What is the weather?")
        self.assertEqual(not_found.status, STATUS_NOT_FOUND)
        self.teach(core, "Java", "A managed language.")
        ambiguous = core.select_learned_knowledge("Rust or Java?")
        self.assertEqual(ambiguous.status, STATUS_AMBIGUOUS)
        for candidate in (not_found, ambiguous, {"status": "NOT_FOUND"}, None, "Rust", 42):
            with self.subTest(candidate=candidate):
                result = evaluate_learned_knowledge_gate(candidate)
                self.assertEqual((result.status, result.reason), (STATUS_REJECTED, REASON_NOT_SELECTED))

    def test_an_irrelevant_selection_is_not_attached_by_core(self):
        core = self.teach(self.new_core())
        forged = LearnedKnowledgeSelection(
            "SELECTED", message="What is the weather?", matched_term="rust",
            record=core.knowledge.get("Rust"),
            relationships=core.knowledge.relationships_for("Rust"))
        with mock.patch.object(core, "select_learned_knowledge", return_value=forged):
            understanding = core.understand_language("What is the weather?")
        self.assertIsNone(understanding.learned_knowledge_context)
        self.assertEqual(core.last_learned_knowledge_gate.reason, REASON_NOT_RELEVANT)


# ----------------------------------------------------------------------
# 3. insufficiently reliable -> rejected
# ----------------------------------------------------------------------
class TestUnreliableItemIsRejected(Case):

    def test_low_confidence_description_is_rejected(self):
        result = self.gate(self.teach(self.new_core(), confidence=0.4))
        self.assertEqual((result.status, result.reason), (STATUS_REJECTED, REASON_INSUFFICIENT_RELIABILITY))
        self.assertAlmostEqual(result.average_confidence, 0.4)

    def test_just_below_the_threshold_is_rejected(self):
        self.assertFalse(self.gate(self.teach(self.new_core(), confidence=0.69)).passed)

    def test_low_confidence_relationship_is_rejected(self):
        core = self.new_core()
        core.knowledge.relate("Rust", "memory safety", "HAS", confidence=0.3)
        self.assertEqual(self.gate(core).reason, REASON_INSUFFICIENT_RELIABILITY)

    def test_reliability_is_judged_over_all_the_evidence(self):
        core = self.teach(self.new_core(), confidence=1.0)
        core.knowledge.relate("Rust", "memory safety", "HAS", confidence=0.2)
        result = self.gate(core)                       # (1.0 + 0.2) / 2 = 0.6 < 0.7
        self.assertEqual(result.supporting_records, 2)
        self.assertAlmostEqual(result.average_confidence, 0.6)
        self.assertEqual(result.reason, REASON_INSUFFICIENT_RELIABILITY)

    def test_invalid_stored_confidence_gives_no_usable_evidence(self):
        for bad in (5.0, -0.1, "high"):
            with self.subTest(confidence=bad):
                core = self.teach(self.new_core())
                core.memory._run("UPDATE knowledge SET confidence = ? WHERE name = ?", (bad, "Rust"))
                self.assertEqual(self.gate(core).reason, REASON_NO_EVIDENCE)

    def test_reteaching_with_higher_confidence_makes_it_usable(self):
        core = self.teach(self.new_core(), confidence=0.3)
        self.assertFalse(self.gate(core).passed)
        self.teach(core, confidence=0.95)
        self.assertTrue(self.gate(core).passed)

    def test_an_unreliable_item_is_not_attached_by_core(self):
        core = self.teach(self.new_core(), confidence=0.4)
        understanding = core.understand_language(QUESTION)
        self.assertIsNone(understanding.learned_knowledge_context)
        self.assertEqual(core.last_learned_knowledge_gate.reason, REASON_INSUFFICIENT_RELIABILITY)
        request = ResponseGenerationRequest(understanding)
        self.assertIsNone(request.generation_context["learned_knowledge_context"])
        self.assertIsNone(request.generation_request["learned_knowledge_context"])

    def test_nothing_is_hard_coded_to_particular_names_or_answers(self):
        for name, text in (("Alpha", "first"), ("Zeta", "last"), ("Le chat", "un animal")):
            with self.subTest(name=name):
                low = self.teach(self.new_core(), name, text, confidence=0.1)
                high = self.teach(self.new_core(), name, text, confidence=0.9)
                message = f"Tell me about {name}"
                self.assertFalse(self.gate(low, message).passed)
                self.assertTrue(self.gate(high, message).passed)


# ----------------------------------------------------------------------
# 4. normal response generation intact when nothing passes
# ----------------------------------------------------------------------
class TestNormalResponseWhenNothingPasses(Case):

    def test_reply_is_exactly_the_normal_one(self):
        core = self.teach(self.new_core(), confidence=0.4)
        control = self.teach(self.new_core(), confidence=0.4)
        with mock.patch("core.core.evaluate_learned_knowledge_gate", None):
            # (patched to a non-callable: the gate would raise if called - it is
            # caught, nothing is attached, and the reply is still the normal one)
            reply = core.process_input(QUESTION)
        self.assertEqual(reply, control.process_input(QUESTION))
        self.assertEqual(reply, "Here's what I know about 'Rust': A systems programming language.")

    def test_local_model_still_generates_and_gets_the_unchanged_request(self):
        core = self.teach(self.new_core(), confidence=0.4)
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        self.assertEqual(core.process_input(QUESTION), MODEL_TEXT)
        request = runtime.requests[0]
        self.assertEqual(request.user_input, QUESTION)                 # request untouched
        self.assertIsNone(request.generation_context.to_dict()["learned_knowledge_context"])
        self.assertIsNone(request.generation_request.learned_knowledge_context)
        self.assertEqual(core.get_last_language_response().status, STATUS_GENERATED)

    def test_context_equals_the_one_built_without_any_learned_knowledge(self):
        with_item = self.teach(self.new_core(), confidence=0.4).understand_language(QUESTION)
        without = self.new_core().understand_language(QUESTION)
        a = ResponseGenerationRequest(with_item).generation_context
        b = ResponseGenerationRequest(without).generation_context
        self.assertEqual(a, b)
        self.assertEqual(with_item.original_input, without.original_input)

    def test_no_replacement_knowledge_is_fabricated(self):
        core = self.teach(self.new_core(), confidence=0.4)
        understanding = core.understand_language(QUESTION)
        self.assertIsNone(understanding.learned_knowledge_context)
        self.assertNotIn("A systems programming language.",
                         repr(ResponseGenerationRequest(understanding).generation_request))

    def test_gate_error_falls_back_to_the_normal_path(self):
        core = self.teach(self.new_core(), confidence=0.9)
        with mock.patch("core.core.evaluate_learned_knowledge_gate", side_effect=RuntimeError("x")):
            understanding = core.understand_language(QUESTION)
        self.assertIsNone(understanding.learned_knowledge_context)
        self.assertIsNotNone(understanding.response_plan)

    def test_nothing_selected_means_no_gate_verdict(self):
        core = self.new_core()
        core.understand_language("What is the weather?")
        self.assertIsNone(core.last_learned_knowledge_gate)


# ----------------------------------------------------------------------
# 5. Prompt 500 unchanged
# ----------------------------------------------------------------------
class TestPrompt500Unchanged(Case):

    def generate(self, core):
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        understanding = core.understand_language(QUESTION)
        result = core.language_intelligence.generate_response(
            understanding, context=core.context, verified_correction_instruction=_instruction())
        return runtime.requests[0], result

    def test_correction_with_a_rejected_item(self):
        request, result = self.generate(self.teach(self.new_core(), confidence=0.4))
        self.assertIs(result.used_verified_correction, True)
        self.assertEqual(request.user_input, "I has a dog")
        self.assertEqual(request.generation_request.original_message, "I has a dog")
        self.assertIsNone(request.generation_request.learned_knowledge_context)

    def test_correction_with_an_accepted_item(self):
        request, result = self.generate(self.teach(self.new_core(), confidence=0.9))
        self.assertIs(result.used_verified_correction, True)
        self.assertEqual(request.user_input, "I has a dog")
        self.assertEqual(request.generation_request.original_message, "I has a dog")
        self.assertEqual(request.generation_request.learned_knowledge_context["record"]["name"], "Rust")

    def test_correction_without_any_learned_item(self):
        request, result = self.generate(self.new_core())
        self.assertIs(result.used_verified_correction, True)
        self.assertEqual(request.user_input, "I has a dog")


# ----------------------------------------------------------------------
# 6. existing mechanisms, purity
# ----------------------------------------------------------------------
class TestReusesTheLearningAnalyzerAndIsPure(Case):

    def test_the_verdict_comes_from_the_learning_analyzer(self):
        core = self.teach(self.new_core(), confidence=0.9)
        selection = self.selection(core)
        with mock.patch.object(LearningAnalyzer, "is_pattern_reliable", return_value=False) as check:
            result = evaluate_learned_knowledge_gate(selection, message=QUESTION)
        self.assertEqual(result.reason, REASON_INSUFFICIENT_RELIABILITY)
        args, kwargs = check.call_args
        self.assertEqual(args[1], "Rust")                       # the entry's name is the pattern
        self.assertEqual(kwargs["min_confidence"], MIN_RELIABLE_CONFIDENCE)
        with mock.patch.object(LearningAnalyzer, "is_pattern_reliable", return_value=True):
            self.assertTrue(evaluate_learned_knowledge_gate(selection, message=QUESTION).passed)

    def test_evaluating_mutates_nothing(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.knowledge.relate("Rust", "memory safety", "HAS", confidence=0.95)
        selection = self.selection(core)
        before_selection = copy.deepcopy(selection.to_dict())
        before_store = (copy.deepcopy(core.knowledge.all()),
                        copy.deepcopy(core.knowledge.relationships_for("Rust")),
                        core.recent_learning_events())
        message = QUESTION
        evaluate_learned_knowledge_gate(selection, message=message)
        evaluate_learned_knowledge_gate(selection.to_dict())
        self.assertEqual(selection.to_dict(), before_selection)
        self.assertEqual(message, QUESTION)
        self.assertEqual((core.knowledge.all(), core.knowledge.relationships_for("Rust"),
                          core.recent_learning_events()), before_store)

    def test_the_gate_never_raises(self):
        weird = {"status": "SELECTED", "record": {"name": None}, "relationships": 5,
                 "matched_term": ["x"], "message": 3}
        for candidate in (weird, {"status": "SELECTED"}, {"status": "SELECTED", "record": "no"}, object()):
            with self.subTest(candidate=candidate):
                result = evaluate_learned_knowledge_gate(candidate)
                self.assertEqual(result.status, STATUS_REJECTED)
        bad = evaluate_learned_knowledge_gate(
            self.selection(self.teach(self.new_core())), min_confidence="x")
        self.assertEqual((bad.status, bad.reason), (STATUS_REJECTED, REASON_GATE_ERROR))

    def test_ael_style_teaching_is_still_usable(self):
        core = self.new_core()
        core.learning.teach("Rust", "A systems language.", source="ael")   # AEL TEACH's own path
        core.learning.relate("Rust", "memory safety", "HAS", source="ael")  # AEL RELATE's own path
        self.assertTrue(self.gate(core).passed)


if __name__ == "__main__":
    unittest.main()
