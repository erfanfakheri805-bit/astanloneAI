"""
Tests for Prompt 501 - Integrate Learned Knowledge into Normal Response
Generation.

When the user has explicitly taught the system a piece of knowledge (the
existing KnowledgeSystem, reached through Core.learn_from_text() /
LearningSystem.teach()), and a later message directly names exactly one
such entry, that entry becomes available - exactly as stored - to the
existing response-generation path (`ResponseGenerationContext` /
`BackendGenerationRequest` / the local model's `InferenceRequest`).
Everything else leaves the path exactly as it was.

Covers:
    1. no learned knowledge -> existing behavior unchanged
    2. one directly relevant item -> available to response generation
    3. unrelated knowledge -> not selected
    4. ambiguous multiple items -> nothing selected
    5. failed retrieval -> normal response path intact
    6. exact learned content preserved
    7. Prompt 500 verified-correction behavior intact
    8. no mutation of stored knowledge or the request/context
    9. end to end through Core -> local-model backend

Run directly:
    python -m unittest tests.test_learned_knowledge_in_response_generation -v
"""

import copy
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.core as core_module
from language_intelligence.corrected_response_target_context import with_corrected_response_target
from language_intelligence.learned_knowledge_context import (
    STATUS_SELECTED, STATUS_NOT_FOUND, STATUS_AMBIGUOUS, STATUS_FAILED,
    LearnedKnowledgeSelection, select_learned_knowledge,
)
from language_intelligence.response_generation import (
    ResponseGenerationRequest, STATUS_GENERATED, STATUS_DEFERRED,
)
from language_intelligence.response_generation_context import (
    ResponseGenerationContext, build_generation_context, generation_context_from_understanding,
)
from language_intelligence.response_generation_request import generation_request_from_understanding
from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
)
from understanding.term_extraction import extract_candidate_terms

from tests.test_pre_inference_readiness_guard import GuardCase, MODEL_TEXT, _core
from tests.test_local_inference_response_generation import TextRuntime

PYTHON_FACT = "Python is a programming language."
PYTHON_QUESTION = "What is Python?"


def _instruction():
    return VerifiedCorrectionResponseInstruction(
        source_text="I has a dgo", corrected_text="I has a dog",
        matched_text="dgo", replacement_text="dog", match_count=1)


def _snapshot(core):
    """Everything the KnowledgeSystem holds, for before/after comparison."""
    knowledge = core.knowledge.all()
    return {
        "knowledge": copy.deepcopy(knowledge),
        "relationships": copy.deepcopy(
            [core.knowledge.relationships_for(row["name"]) for row in knowledge]),
    }


class Case(GuardCase):
    """A fresh real Core (real SQLite-backed KnowledgeSystem) per test."""

    def new_core(self):
        core, _tmp = _core(self)
        return core

    def taught_core(self, *sentences):
        core = self.new_core()
        for sentence in sentences or (PYTHON_FACT,):
            core.learn_from_text(sentence)
        return core

    def select(self, core, message):
        return core.select_learned_knowledge(message)


# ----------------------------------------------------------------------
# 1 + 3 + 4 + 5. The relevance decision
# ----------------------------------------------------------------------
class TestRelevanceDecision(Case):

    def test_no_learned_knowledge_is_not_found(self):
        selection = self.select(self.new_core(), PYTHON_QUESTION)
        self.assertEqual(selection.status, STATUS_NOT_FOUND)
        self.assertFalse(selection.selected)
        self.assertIsNone(selection.record)
        self.assertIsNone(selection.to_context())

    def test_one_directly_relevant_item_is_selected(self):
        core = self.taught_core()
        selection = self.select(core, PYTHON_QUESTION)
        self.assertEqual(selection.status, STATUS_SELECTED)
        self.assertTrue(selection.selected)
        self.assertEqual(selection.record["name"], "Python")
        self.assertEqual(selection.matched_term, "python")

    def test_description_only_knowledge_is_selected(self):
        core = self.new_core()
        core.learning.teach("Rust", "A systems programming language.", source="user")
        selection = self.select(core, "Tell me about rust")
        self.assertEqual(selection.status, STATUS_SELECTED)
        self.assertEqual(selection.record["description"], "A systems programming language.")

    def test_name_match_is_case_insensitive(self):
        core = self.taught_core()
        self.assertEqual(self.select(core, "PYTHON?").status, STATUS_SELECTED)

    def test_multi_word_name_is_selected(self):
        core = self.taught_core("Machine learning is a field of study.")
        selection = self.select(core, "What is machine learning?")
        self.assertEqual(selection.status, STATUS_SELECTED)
        self.assertEqual(selection.record["name"], "Machine learning")

    def test_unrelated_knowledge_is_not_selected(self):
        core = self.taught_core("Java is a programming language.")
        selection = self.select(core, PYTHON_QUESTION)
        self.assertEqual(selection.status, STATUS_NOT_FOUND)
        self.assertIsNone(selection.to_context())

    def test_partial_or_substring_names_are_not_matched(self):
        core = self.taught_core()
        for message in ("What is Pythonic code?", "What is Pyth?", "Tell me about snakes"):
            with self.subTest(message=message):
                self.assertEqual(self.select(core, message).status, STATUS_NOT_FOUND)

    def test_ambiguous_multiple_items_select_nothing(self):
        core = self.taught_core(PYTHON_FACT, "Java is a programming language.")
        selection = self.select(core, "Python or Java?")
        self.assertEqual(selection.status, STATUS_AMBIGUOUS)
        self.assertEqual(selection.candidates, ["Java", "Python"])
        self.assertIsNone(selection.record)
        self.assertIsNone(selection.to_context())

    def test_entry_with_no_learned_content_is_not_a_candidate(self):
        core = self.new_core()
        core.knowledge.learn("Ghost", None, status="stub")  # a bare stub: nothing to expose
        self.assertEqual(self.select(core, "Tell me about Ghost").status, STATUS_NOT_FOUND)

    def test_failed_retrieval_selects_nothing(self):
        core = self.taught_core()

        def boom(_name):
            raise RuntimeError("database unavailable")
        core.knowledge.find_by_name_case_insensitive = boom
        selection = self.select(core, PYTHON_QUESTION)
        self.assertEqual(selection.status, STATUS_FAILED)
        self.assertIn("database unavailable", selection.reason)
        self.assertIsNone(selection.to_context())

    def test_missing_knowledge_system_and_bad_messages_never_raise(self):
        self.assertEqual(select_learned_knowledge("Python", None).status, STATUS_FAILED)
        for bad in (None, "", "   ", 42, ["Python"]):
            with self.subTest(message=bad):
                self.assertEqual(select_learned_knowledge(bad, object()).status, STATUS_NOT_FOUND)

    def test_decision_is_deterministic(self):
        core = self.taught_core()
        first = self.select(core, PYTHON_QUESTION).to_dict()
        for _ in range(3):
            self.assertEqual(self.select(core, PYTHON_QUESTION).to_dict(), first)


# ----------------------------------------------------------------------
# 6 + 8. Exact content, no mutation
# ----------------------------------------------------------------------
class TestExactContentAndNoMutation(Case):

    def test_exact_learned_content_is_preserved(self):
        core = self.taught_core(PYTHON_FACT, "Python uses indentation.")
        stored = core.knowledge.get("Python")
        stored_relationships = core.knowledge.relationships_for("Python")
        context = self.select(core, PYTHON_QUESTION).to_context()
        self.assertEqual(context["status"], STATUS_SELECTED)
        self.assertEqual(context["record"], stored)
        self.assertEqual(context["relationships"], stored_relationships)
        self.assertEqual(context["record"]["source_text"], PYTHON_FACT)
        self.assertEqual(
            [(r["relation_type"], r["to_name"]) for r in context["relationships"]["outgoing"]],
            [("IS_A", "programming language"), ("USES", "indentation")])
        self.assertEqual(context["message"], PYTHON_QUESTION)

    def test_taught_description_is_preserved_verbatim(self):
        core = self.new_core()
        text = "  A language,  with   odd spacing & CASE.  "
        core.learning.teach("Rust", text, source="user")
        context = self.select(core, "rust").to_context()
        self.assertEqual(context["record"]["description"], text)

    def test_selection_does_not_mutate_stored_knowledge(self):
        core = self.taught_core(PYTHON_FACT, "Python uses indentation.")
        before = _snapshot(core)
        events_before = core.recent_learning_events()
        self.select(core, PYTHON_QUESTION)
        self.select(core, "Python or indentation?")
        self.assertEqual(_snapshot(core), before)
        self.assertEqual(core.recent_learning_events(), events_before)

    def test_mutating_a_selection_never_reaches_storage(self):
        core = self.taught_core()
        selection = self.select(core, PYTHON_QUESTION)
        selection.record["description"] = "tampered"
        selection.relationships["outgoing"].clear()
        selection.to_dict()["record"]["name"] = "tampered"
        selection.to_context()["relationships"]["incoming"].append("tampered")
        fresh = self.select(core, PYTHON_QUESTION)
        self.assertEqual(fresh.record, core.knowledge.get("Python"))
        self.assertEqual(fresh.relationships, core.knowledge.relationships_for("Python"))

    def test_message_and_terms_are_not_mutated(self):
        core = self.taught_core()
        message = PYTHON_QUESTION
        terms = extract_candidate_terms(message)
        terms_before = list(terms)
        select_learned_knowledge(message, core.knowledge, candidate_terms=terms)
        self.assertEqual(message, PYTHON_QUESTION)
        self.assertEqual(terms, terms_before)


# ----------------------------------------------------------------------
# 2 + 6 + 8. The existing response-generation structures
# ----------------------------------------------------------------------
class TestResponseGenerationStructures(Case):

    def understanding(self, core, message=PYTHON_QUESTION):
        return core.understand_language(message)

    def test_understanding_without_knowledge_is_unchanged(self):
        core = self.new_core()
        understanding = self.understanding(core)
        self.assertIsNone(understanding.learned_knowledge_context)
        request = ResponseGenerationRequest(understanding)
        self.assertIsNone(request.generation_context["learned_knowledge_context"])
        self.assertIsNone(request.generation_request["learned_knowledge_context"])
        self.assertIsNone(generation_context_from_understanding(understanding)
                          .learned_knowledge_context)

    def test_context_is_identical_to_before_when_nothing_is_attached(self):
        core = self.new_core()
        understanding = self.understanding(core)
        baseline = build_generation_context(understanding.response_plan).to_dict()
        actual = ResponseGenerationRequest(understanding).generation_context
        self.assertEqual(actual, baseline)  # includes the additive None key

    def test_learned_knowledge_becomes_generation_context(self):
        core = self.taught_core()
        understanding = self.understanding(core)
        expected = core.select_learned_knowledge(PYTHON_QUESTION).to_context()
        self.assertEqual(understanding.learned_knowledge_context, expected)
        request = ResponseGenerationRequest(understanding)
        self.assertEqual(request.generation_context["learned_knowledge_context"], expected)
        self.assertEqual(request.generation_request["learned_knowledge_context"], expected)
        self.assertEqual(
            generation_context_from_understanding(understanding).learned_knowledge_context, expected)
        self.assertEqual(
            generation_request_from_understanding(understanding).learned_knowledge_context, expected)

    def test_only_the_new_key_differs_from_the_no_knowledge_context(self):
        taught = self.understanding(self.taught_core())
        plain = self.understanding(self.new_core())
        a = ResponseGenerationRequest(taught).generation_context
        b = ResponseGenerationRequest(plain).generation_context
        a.pop("learned_knowledge_context")
        b.pop("learned_knowledge_context")
        # (the message and plan are the same text, so nothing else moves)
        self.assertEqual(a, b)

    def test_context_carries_a_private_copy(self):
        core = self.taught_core()
        understanding = self.understanding(core)
        context = generation_context_from_understanding(understanding)
        context.learned_knowledge_context["record"]["description"] = "tampered"
        context.to_dict()["learned_knowledge_context"]["record"]["name"] = "tampered"
        self.assertEqual(understanding.learned_knowledge_context["record"],
                         core.knowledge.get("Python"))

    def test_building_the_context_does_not_mutate_the_understanding(self):
        core = self.taught_core()
        understanding = self.understanding(core)
        before = (understanding.to_dict(), copy.deepcopy(understanding.learned_knowledge_context),
                  copy.deepcopy(understanding.response_plan))
        request = ResponseGenerationRequest(understanding)
        request.generation_context
        request.generation_request
        after = (understanding.to_dict(), understanding.learned_knowledge_context,
                 understanding.response_plan)
        self.assertEqual(after, before)

    def test_explicit_argument_is_carried_straight_through(self):
        core = self.new_core()
        plan = self.understanding(core).response_plan
        supplied = {"status": STATUS_SELECTED, "record": {"name": "X"}}
        context = build_generation_context(plan, learned_knowledge_context=supplied)
        self.assertEqual(context.learned_knowledge_context, supplied)
        supplied["record"]["name"] = "changed later"
        self.assertEqual(context.learned_knowledge_context["record"]["name"], "X")
        self.assertIsNone(build_generation_context(plan).learned_knowledge_context)

    def test_prompt_494_attachment_keeps_the_learned_knowledge(self):
        core = self.taught_core()
        understanding = self.understanding(core)
        request = ResponseGenerationRequest(
            understanding, verified_correction_instruction=_instruction())
        context = build_generation_context(
            understanding.response_plan,
            learned_knowledge_context=understanding.learned_knowledge_context)
        attached = with_corrected_response_target(context, request)
        self.assertEqual(attached.corrected_response_target, "I has a dog")
        self.assertEqual(attached.learned_knowledge_context, understanding.learned_knowledge_context)


# ----------------------------------------------------------------------
# 1 + 3 + 4 + 5. Core: normal behavior unchanged unless exactly one item
# ----------------------------------------------------------------------
class TestCoreLeavesNormalBehaviorAlone(Case):

    def assert_nothing_attached_and_reply_unchanged(self, core, control, message):
        reply = core.process_input(message)
        self.assertEqual(reply, control.process_input(message))
        understanding = core.get_last_language_understanding()
        self.assertIsNone(understanding.learned_knowledge_context)
        self.assertIsNone(ResponseGenerationRequest(understanding)
                          .generation_context["learned_knowledge_context"])
        return reply

    def test_no_learned_knowledge(self):
        core, control = self.new_core(), self.new_core()
        self.assert_nothing_attached_and_reply_unchanged(core, control, PYTHON_QUESTION)

    def test_unrelated_learned_knowledge(self):
        core = self.taught_core("Java is a programming language.")
        control = self.taught_core("Java is a programming language.")
        self.assert_nothing_attached_and_reply_unchanged(core, control, "What is the weather?")

    def test_ambiguous_learned_knowledge(self):
        sentences = (PYTHON_FACT, "Java is a programming language.")
        core, control = self.taught_core(*sentences), self.taught_core(*sentences)
        self.assert_nothing_attached_and_reply_unchanged(core, control, "Python or Java?")

    def test_failed_retrieval_keeps_the_normal_reply(self):
        core, control = self.taught_core(), self.taught_core()

        class BrokenKnowledge:
            def find_by_name_case_insensitive(self, _name):
                raise RuntimeError("database unavailable")

            def relationships_for(self, _name):
                raise RuntimeError("database unavailable")

        def broken_selection(message, _knowledge, candidate_terms=None):
            # the same operation Core calls, but over a knowledge system whose retrieval fails
            return select_learned_knowledge(message, BrokenKnowledge(), candidate_terms)

        with mock.patch.object(core_module, "select_learned_knowledge", broken_selection):
            self.assertEqual(core.select_learned_knowledge(PYTHON_QUESTION).status, STATUS_FAILED)
            reply = core.process_input(PYTHON_QUESTION)
        self.assertEqual(reply, control.process_input(PYTHON_QUESTION))
        self.assertIsNone(core.get_last_language_understanding().learned_knowledge_context)

    def test_failed_selection_never_breaks_understand_language(self):
        core = self.taught_core()
        core.select_learned_knowledge = lambda message: (_ for _ in ()).throw(RuntimeError("x"))
        understanding = core.understand_language(PYTHON_QUESTION)
        self.assertIsNone(understanding.learned_knowledge_context)
        self.assertIsNotNone(understanding.response_plan)

    def test_deterministic_backend_reply_is_unchanged_when_relevant(self):
        # With today's deterministic backend nothing is generated from the
        # knowledge; the existing pipeline answers exactly as it always did.
        core = self.new_core()
        core.learning.teach("Rust", "A systems programming language.", source="user")
        reply = core.process_input("Tell me about Rust")
        self.assertEqual(
            reply, "Here's what I know about 'Rust': A systems programming language.")
        self.assertEqual(core.get_last_language_response().status, STATUS_DEFERRED)
        self.assertIsNotNone(core.get_last_language_understanding().learned_knowledge_context)

    def test_conversation_never_mutates_stored_knowledge(self):
        core = self.taught_core(PYTHON_FACT, "Python uses indentation.")
        before = _snapshot(core)
        core.process_input(PYTHON_QUESTION)
        core.understand_language("Tell me about Python")
        self.assertEqual(_snapshot(core), before)


# ----------------------------------------------------------------------
# 7. Prompt 500 intact
# ----------------------------------------------------------------------
class TestPrompt500StillWorks(Case):

    def test_verified_correction_and_learned_knowledge_coexist(self):
        core = self.taught_core()
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        understanding = core.understand_language(PYTHON_QUESTION)
        expected = understanding.learned_knowledge_context
        self.assertIsNotNone(expected)

        result = core.language_intelligence.generate_response(
            understanding, context=core.context, verified_correction_instruction=_instruction())

        self.assertEqual(result.status, STATUS_GENERATED)
        self.assertIs(result.used_verified_correction, True)
        request = runtime.requests[0]
        self.assertEqual(request.user_input, "I has a dog")          # Prompt 500 unchanged
        self.assertEqual(request.generation_request.original_message, "I has a dog")
        self.assertIs(request.generation_request.used_verified_correction, True)
        self.assertEqual(request.generation_context.to_dict()["learned_knowledge_context"], expected)
        self.assertEqual(request.generation_request.learned_knowledge_context, expected)

    def test_correction_without_knowledge_is_as_before(self):
        core = self.new_core()
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        understanding = core.understand_language(PYTHON_QUESTION)
        result = core.language_intelligence.generate_response(
            understanding, context=core.context, verified_correction_instruction=_instruction())
        self.assertIs(result.used_verified_correction, True)
        request = runtime.requests[0]
        self.assertEqual(request.user_input, "I has a dog")
        self.assertIsNone(request.generation_request.learned_knowledge_context)


# ----------------------------------------------------------------------
# 9. End to end, through the production path
# ----------------------------------------------------------------------
class TestEndToEnd(Case):
    """user teaches -> existing learning/storage -> later user message ->
    relevant learned knowledge retrieved -> becomes response context ->
    the existing response-generation path (local-model backend) receives it."""

    def wired_core(self):
        runtime = TextRuntime(self.config())
        core = self.new_core()
        core.use_local_language_model(runtime=runtime)
        return core, runtime

    def test_taught_relations_reach_the_model_request(self):
        core, runtime = self.wired_core()
        core.learn_from_text(PYTHON_FACT)                      # 1. user teaches
        core.learn_from_text("Python uses indentation.")
        stored = core.knowledge.get("Python")                  # 2. existing storage
        stored_relationships = core.knowledge.relationships_for("Python")

        reply = core.process_input(PYTHON_QUESTION)            # 3. later message

        self.assertEqual(reply, MODEL_TEXT)                    # the normal path answered
        self.assertEqual(len(runtime.requests), 1)
        request = runtime.requests[0]
        for learned in (request.generation_context.to_dict()["learned_knowledge_context"],
                        request.generation_request.learned_knowledge_context):   # 4 + 5
            self.assertEqual(learned["status"], STATUS_SELECTED)
            self.assertEqual(learned["record"], stored)        # exact content
            self.assertEqual(learned["relationships"], stored_relationships)
            self.assertEqual(learned["message"], PYTHON_QUESTION)
        self.assertEqual(request.user_input, PYTHON_QUESTION)  # message itself untouched

    def test_taught_description_reaches_the_model_request(self):
        core, runtime = self.wired_core()
        core.learning.teach("Rust", "A systems programming language.", source="user")
        core.process_input("Tell me about Rust")
        learned = runtime.requests[0].generation_context.to_dict()["learned_knowledge_context"]
        self.assertEqual(learned["record"]["description"], "A systems programming language.")

    def test_unrelated_message_receives_no_learned_knowledge(self):
        core, runtime = self.wired_core()
        core.learn_from_text(PYTHON_FACT)
        core.process_input("What is the weather like?")
        request = runtime.requests[0]
        self.assertIsNone(request.generation_context.to_dict()["learned_knowledge_context"])
        self.assertIsNone(request.generation_request.learned_knowledge_context)

    def test_ambiguous_message_receives_no_learned_knowledge(self):
        core, runtime = self.wired_core()
        core.learn_from_text(PYTHON_FACT)
        core.learn_from_text("Java is a programming language.")
        core.process_input("Python or Java?")
        self.assertIsNone(runtime.requests[0].generation_context.to_dict()["learned_knowledge_context"])

    def test_teaching_turn_itself_is_not_its_own_context(self):
        # Selection runs before anything is learned from the message, so
        # the very first statement cannot be "found" by itself.
        core = self.new_core()
        core.process_input(PYTHON_FACT)
        self.assertIsNone(core.get_last_language_understanding().learned_knowledge_context)
        core.process_input(PYTHON_QUESTION)
        self.assertIsNotNone(core.get_last_language_understanding().learned_knowledge_context)


if __name__ == "__main__":
    unittest.main()
