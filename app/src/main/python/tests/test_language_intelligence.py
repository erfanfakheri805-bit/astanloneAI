"""
Tests for the Language Intelligence Core (Prompt 397,
language_intelligence/).

Run directly:
    python -m unittest tests.test_language_intelligence -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine
from context.relevance import RelevantContextResult
from context.message_reference_resolution import ResolvedReference
from context.active_topic import ActiveTopicResult, SOURCE_CURRENT_INPUT

from language_intelligence.backend import (
    LanguageIntelligenceBackend, BACKEND_KIND_DETERMINISTIC_FALLBACK, BACKEND_KIND_LOCAL_MODEL,
)
from language_intelligence.language_understanding_result import (
    LanguageUnderstandingResult, INTENT_ASK_QUESTION, INTENT_PROVIDE_INFORMATION,
    INTENT_REQUEST_ACTION, INTENT_GOAL_REQUEST, INTENT_UNKNOWN,
)
from language_intelligence.response_generation import ResponseGenerationResult, STATUS_DEFERRED
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from core.core import Core


def _make_backend():
    return DeterministicFallbackBackend(UnderstandingEngine())


def _make_lic():
    return LanguageIntelligenceCore(backend=_make_backend())


class TestBasicNaturalLanguageInput(unittest.TestCase):
    """1. basic natural-language input"""

    def test_statement_is_understood(self):
        lic = _make_lic()
        result = lic.understand("Python is a programming language.")
        self.assertEqual(result.intent, INTENT_PROVIDE_INFORMATION)
        self.assertEqual(result.normalized_input, "Python is a programming language.")
        self.assertTrue(any(e["text"].lower() == "python" for e in result.entities))

    def test_question_is_understood(self):
        lic = _make_lic()
        result = lic.understand("What is Python?")
        self.assertEqual(result.intent, INTENT_ASK_QUESTION)

    def test_command_is_understood(self):
        lic = _make_lic()
        result = lic.understand("Explain indentation.")
        self.assertEqual(result.intent, INTENT_REQUEST_ACTION)

    def test_goal_oriented_prefix_is_labeled_goal_request(self):
        lic = _make_lic()
        result = lic.understand("I want to build a small script.")
        self.assertEqual(result.intent, INTENT_GOAL_REQUEST)


class TestStructuredUnderstandingResult(unittest.TestCase):
    """2. structured understanding result"""

    def test_to_dict_has_every_required_field(self):
        lic = _make_lic()
        result = lic.understand("Python uses indentation.")
        as_dict = result.to_dict()
        for field in (
            "original_input", "detected_language", "normalized_input", "intent",
            "entities", "referenced_items", "active_topic", "conversation_context",
            "confidence", "ambiguity", "needs_clarification", "warnings", "source_backend",
        ):
            self.assertIn(field, as_dict)

    def test_confidence_is_a_float_between_zero_and_one(self):
        lic = _make_lic()
        result = lic.understand("Python uses indentation.")
        self.assertIsInstance(result.confidence, float)
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_source_backend_is_labeled(self):
        lic = _make_lic()
        result = lic.understand("Hello there.")
        self.assertEqual(result.source_backend, BACKEND_KIND_DETERMINISTIC_FALLBACK)


class TestPreservationOfOriginalInput(unittest.TestCase):
    """3. preservation of original input"""

    def test_original_input_kept_verbatim(self):
        lic = _make_lic()
        raw = "  Python   is    great!!  "
        result = lic.understand(raw)
        self.assertEqual(result.original_input, raw)
        self.assertNotEqual(result.original_input, result.normalized_input)
        self.assertEqual(result.normalized_input, "Python is great!!")


class TestContextPassing(unittest.TestCase):
    """4. context passing"""

    def test_relevant_context_is_carried_through_unchanged(self):
        lic = _make_lic()
        relevant_context = RelevantContextResult(
            message="What does it use?",
            message_terms=["use"],
            selected=[{
                "turn": {"user": "Python is a language.", "assistant": "Got it."},
                "index": 0, "rank": 1, "score": 2.0,
                "matched_terms": ["use"], "reasons": ["shared_terms:use"],
                "covers_message_terms": True,
            }],
        )
        result = lic.understand("What does it use?", relevant_context=relevant_context)
        self.assertEqual(result.conversation_context, relevant_context.to_dict())

    def test_none_relevant_context_yields_none(self):
        lic = _make_lic()
        result = lic.understand("Hello.")
        self.assertIsNone(result.conversation_context)


class TestActiveTopicPassing(unittest.TestCase):
    """5. active topic passing"""

    def test_active_topic_is_carried_through_unchanged(self):
        lic = _make_lic()
        active_topic = ActiveTopicResult(
            topic="Python", topic_source=SOURCE_CURRENT_INPUT, confidence=0.8,
            changed=True, previous_topic=None, reason="new_from_input",
        )
        result = lic.understand("Tell me more.", active_topic=active_topic)
        self.assertEqual(result.active_topic, active_topic.to_dict())

    def test_none_active_topic_yields_none(self):
        lic = _make_lic()
        result = lic.understand("Hello.")
        self.assertIsNone(result.active_topic)


class TestReferencePassing(unittest.TestCase):
    """6. reference passing"""

    def test_resolved_reference_becomes_a_referenced_item(self):
        lic = _make_lic()
        resolved_reference = ResolvedReference(
            has_reference=True, reference_text="it", resolved_context="Python is a language.",
            confidence=0.9, ambiguous=False, reason="top_ranked_context",
        )
        result = lic.understand("What does it use?", resolved_reference=resolved_reference)
        self.assertEqual(len(result.referenced_items), 1)
        item = result.referenced_items[0]
        self.assertEqual(item["reference_text"], "it")
        self.assertEqual(item["resolved_context"], "Python is a language.")
        self.assertFalse(item["ambiguous"])

    def test_no_reference_yields_empty_list(self):
        lic = _make_lic()
        resolved_reference = ResolvedReference(
            has_reference=False, reference_text=None, resolved_context=None,
            confidence=0.0, ambiguous=False, reason="no_reference",
        )
        result = lic.understand("Python is great.", resolved_reference=resolved_reference)
        self.assertEqual(result.referenced_items, [])


class TestUncertaintyHandling(unittest.TestCase):
    """7. uncertainty handling"""

    def test_ambiguous_reference_lowers_confidence_and_flags_clarification(self):
        lic = _make_lic()
        ambiguous_reference = ResolvedReference(
            has_reference=True, reference_text="it", resolved_context=None,
            confidence=0.0, ambiguous=True, reason="insufficient_margin",
        )
        plain_result = lic.understand("What does it do?")
        ambiguous_result = lic.understand(
            "What does it do?", resolved_reference=ambiguous_reference
        )
        self.assertTrue(ambiguous_result.ambiguity)
        self.assertTrue(ambiguous_result.needs_clarification)
        self.assertLess(ambiguous_result.confidence, plain_result.confidence)
        self.assertIn("confidence_reduced_ambiguous_reference", ambiguous_result.warnings)

    def test_unresolvable_low_confidence_input_needs_clarification(self):
        lic = _make_lic()
        result = lic.understand("???")
        self.assertTrue(result.needs_clarification)


class TestUnknownInputWithoutHallucination(unittest.TestCase):
    """8. unknown input without hallucination"""

    def test_empty_input_produces_no_fabricated_information(self):
        lic = _make_lic()
        result = lic.understand("")
        self.assertEqual(result.intent, INTENT_UNKNOWN)
        self.assertEqual(result.entities, [])
        self.assertEqual(result.referenced_items, [])
        self.assertIsNone(result.active_topic)
        self.assertIsNone(result.conversation_context)
        self.assertTrue(result.needs_clarification)
        self.assertEqual(result.confidence, 0.0)

    def test_symbols_only_input_is_unknown_not_guessed(self):
        lic = _make_lic()
        result = lic.understand("!!! ??? ...")
        self.assertEqual(result.intent, INTENT_UNKNOWN)
        self.assertTrue(result.needs_clarification)


class TestBackendInterfaceBehavior(unittest.TestCase):
    """9. backend interface behavior"""

    def test_base_interface_is_not_implemented(self):
        base = LanguageIntelligenceBackend()
        with self.assertRaises(NotImplementedError):
            _ = base.backend_kind
        with self.assertRaises(NotImplementedError):
            base.understand("hello")
        with self.assertRaises(NotImplementedError):
            base.generate_response(None)

    def test_local_model_backend_is_honest_about_having_no_model(self):
        # Prompt 397 asserted NotImplementedError here (an inert stub).
        # Prompt 398 replaced the stub with a real runtime boundary, so
        # the same honesty is now an EXPLICIT, structured status
        # (see tests/test_local_model_runtime.py for full coverage).
        from language_intelligence.local_model_backend import LocalModelBackendError
        from language_intelligence.response_generation import STATUS_MODEL_NOT_CONFIGURED
        backend = LocalLanguageModelBackend()
        self.assertEqual(backend.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        with self.assertRaises(LocalModelBackendError) as ctx:
            backend.understand("hello")
        self.assertEqual(ctx.exception.status, STATUS_MODEL_NOT_CONFIGURED)
        response = backend.generate_response(_make_backend().understand("hello"))
        self.assertEqual(response.status, STATUS_MODEL_NOT_CONFIGURED)
        self.assertIsNone(response.response_text)

    def test_deterministic_backend_declares_its_kind(self):
        backend = _make_backend()
        self.assertEqual(backend.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)


class TestDeterministicFallbackBehavior(unittest.TestCase):
    """10. deterministic fallback behavior"""

    def test_generate_response_defers_to_existing_pipeline(self):
        lic = _make_lic()
        understanding = lic.understand("Hello.")
        response = lic.generate_response(understanding)
        self.assertIsInstance(response, ResponseGenerationResult)
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(response.response_text)
        self.assertEqual(response.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertTrue(response.reason)

    def test_fallback_never_invents_entities_beyond_understanding_engine(self):
        backend = _make_backend()
        engine_result = UnderstandingEngine().understand("Python uses indentation.")
        lic_result = backend.understand("Python uses indentation.")
        self.assertEqual(lic_result.entities, engine_result.entities)


class TestCoreIntegration(unittest.TestCase):
    """11. Core integration"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_core_has_a_language_intelligence_core(self):
        self.assertIsInstance(self.core.language_intelligence, LanguageIntelligenceCore)
        self.assertEqual(
            self.core.language_intelligence.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK
        )

    def test_last_language_understanding_starts_none(self):
        self.assertIsNone(self.core.get_last_language_understanding())

    def test_ordinary_conversation_populates_last_language_understanding(self):
        self.core.process_input("Python is a programming language.")
        result = self.core.get_last_language_understanding()
        self.assertIsInstance(result, LanguageUnderstandingResult)
        self.assertEqual(result.original_input, "Python is a programming language.")

    def test_ael_input_does_not_populate_last_language_understanding(self):
        self.core.process_input("TEACH Python IS Programming Language")
        self.assertIsNone(self.core.get_last_language_understanding())

    def test_goal_oriented_input_does_not_populate_last_language_understanding(self):
        self.core.process_input("I want to build a small script.")
        self.assertIsNone(self.core.get_last_language_understanding())

    def test_understand_language_entry_point_is_side_effect_free(self):
        before = self.core.memory.counts()
        result = self.core.understand_language("Python is a programming language.")
        after = self.core.memory.counts()
        self.assertIsInstance(result, LanguageUnderstandingResult)
        self.assertEqual(before, after)
        # It also never populates last_language_understanding - only the
        # real conversation path (process_input) does that.
        self.assertIsNone(self.core.get_last_language_understanding())

    def test_understand_language_without_context_yields_no_context_pieces(self):
        result = self.core.understand_language("Hello.", use_context=False)
        self.assertIsNone(result.active_topic)
        self.assertIsNone(result.conversation_context)
        self.assertEqual(result.referenced_items, [])

    def test_generate_language_response_defers(self):
        understanding = self.core.understand_language("Hello.")
        response = self.core.generate_language_response(understanding)
        self.assertEqual(response.status, STATUS_DEFERRED)


class _StubGeneratingBackend(LanguageIntelligenceBackend):
    """Test double for Prompt 402's connection tests only. Wraps the
    real DeterministicFallbackBackend for understand() (so context/
    reference/topic computation is untouched) but returns a fixed,
    non-fabricated STATUS_GENERATED response for generate_response() -
    standing in for a real local model backend/provider/runtime
    without needing one installed."""

    def __init__(self, response_text):
        self._inner = _make_backend()
        self._response_text = response_text

    @property
    def backend_kind(self):
        return BACKEND_KIND_LOCAL_MODEL

    def understand(self, raw_text, context=None, relevant_context=None,
                    resolved_reference=None, active_topic=None, requested_language=None):
        return self._inner.understand(
            raw_text, context=context, relevant_context=relevant_context,
            resolved_reference=resolved_reference, active_topic=active_topic,
            requested_language=requested_language,
        )

    def generate_response(self, understanding, context=None):
        from language_intelligence.response_generation import STATUS_GENERATED
        return ResponseGenerationResult(
            status=STATUS_GENERATED, response_text=self._response_text,
            reason="stub backend for connection test", backend_kind=self.backend_kind,
        )


class TestConversationConnectedToLanguageIntelligenceCore(unittest.TestCase):
    """Prompt 402: the normal conversation flow (Core.process_input ->
    Core._handle_conversation) is actually connected to
    LanguageIntelligenceCore -> the configured backend/provider/
    runtime -> the existing response path, instead of only computing
    an observational LanguageUnderstandingResult."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_normal_message_reaches_language_intelligence_core(self):
        # 1. Normal user message reaches LanguageIntelligenceCore.
        self.assertIsNone(self.core.get_last_language_understanding())
        self.core.process_input("Rivers usually flow toward the sea.")
        understanding = self.core.get_last_language_understanding()
        self.assertIsInstance(understanding, LanguageUnderstandingResult)
        self.assertEqual(understanding.original_input, "Rivers usually flow toward the sea.")
        # ... and its generate_response() step (1d) also ran.
        response = self.core.get_last_language_response()
        self.assertIsInstance(response, ResponseGenerationResult)

    def test_language_intelligence_result_reaches_existing_response_path(self):
        # 2. A generated language-intelligence result reaches the
        # existing response path: process_input() returns it directly,
        # through the one existing reply pipeline (no second one), and
        # message/context storage still happen exactly once.
        self.core.language_intelligence.backend = _StubGeneratingBackend(
            "This is the connected language-intelligence reply."
        )
        before_messages = len(self.core.recent_messages(100))
        reply = self.core.process_input("Tell me something about rivers.")
        self.assertEqual(reply, "This is the connected language-intelligence reply.")
        after_messages = len(self.core.recent_messages(100))
        # Exactly one user + one assistant message logged - no duplicate
        # message storage from this new step.
        self.assertEqual(after_messages - before_messages, 2)
        turns = self.core.get_recent_turns()
        self.assertEqual(turns[-1]["assistant"], "This is the connected language-intelligence reply.")
        # Not duplicated as a second turn either.
        self.assertEqual(
            len([t for t in turns if t["user"] == "Tell me something about rivers."]), 1
        )

    def test_no_model_configured_keeps_deterministic_fallback_behavior(self):
        # 3. No-model/fallback behavior still works: with today's
        # default (deterministic fallback) backend, generate_response()
        # always defers, so the connection changes nothing about the
        # reply for ordinary unmapped input.
        reply = self.core.process_input("qwerty zzznoxyzzz unmapped concept")
        self.assertIn("I don't have enough information", reply)
        response = self.core.get_last_language_response()
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(response.response_text)

    def test_existing_conversation_behavior_remains_compatible(self):
        # 4. Existing conversation behavior remains compatible: skill
        # matching (checked before the language-intelligence step) and
        # AEL/goal routing (which never reach _handle_conversation at
        # all) are both unaffected by this connection.
        self.assertIn("Hello!", self.core.process_input("hello"))
        self.assertIsNone(self.core.get_last_language_understanding())
        teach_reply = self.core.process_input("TEACH Python IS Programming Language")
        self.assertIn("[AEL OK]", teach_reply)
        goal_reply = self.core.process_input("I want to build a small script.")
        self.assertIn("[GOAL CREATED]", goal_reply)


class TestBackwardCompatibility(unittest.TestCase):
    """12. backward compatibility with existing conversation behavior"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ael_teach_and_ask_still_work(self):
        teach_reply = self.core.process_input('TEACH Python IS Programming Language')
        self.assertIn("[AEL OK]", teach_reply)
        ask_reply = self.core.process_input("ASK Python")
        self.assertIn("Programming Language", ask_reply)

    def test_conversation_fallback_still_works(self):
        reply = self.core.process_input("qwerty zzznoxyzzz unmapped concept")
        self.assertIn("I don't have enough information", reply)

    def test_reply_is_still_a_plain_string(self):
        reply = self.core.process_input("Hello there.")
        self.assertIsInstance(reply, str)

    def test_goal_creation_reply_unaffected(self):
        reply = self.core.process_input("I want to build a small script.")
        self.assertIn("[GOAL CREATED]", reply)


if __name__ == "__main__":
    unittest.main()
