"""
Tests for Prompt 403 - Focused Conversation Context Selection.

Covers the small narrowing step that sits between the existing
relevance selection (context/relevance.py:select_relevant_turns) and
the conversation history actually sent to the Language Intelligence
backend/provider/runtime (language_intelligence/local_model_mapping.py:
focused_conversation_from_context), plus the reusable
context/relevance.py:select_bounded_context it is built on.

Run directly:
    python -m unittest tests.test_focused_context_selection -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context.relevance import (
    select_relevant_turns, select_bounded_context, RelevantContextResult,
    DEFAULT_FOCUSED_MAX_TURNS, DEFAULT_FOCUSED_MAX_CHARS,
)
from context.conversation_context import ConversationContext
from understanding.engine import UnderstandingEngine
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.local_model_mapping import (
    build_inference_request, focused_conversation_from_context, conversation_from_context,
)
from core.core import Core


def _item(index, rank, user, assistant):
    return {
        "turn": {"user": user, "assistant": assistant},
        "index": index, "rank": rank, "score": float(rank),
        "matched_terms": [], "reasons": [], "covers_message_terms": False,
    }


def _relevant(selected):
    return RelevantContextResult(message="msg", message_terms=[], selected=selected)


def _make_understanding(text, relevant_context=None):
    return DeterministicFallbackBackend(UnderstandingEngine()).understand(
        text, relevant_context=relevant_context
    )


class TestRelevantRecentContextIsSelected(unittest.TestCase):
    """1. relevant recent context is selected"""

    def test_shared_term_turn_is_selected(self):
        turns = [
            {"user": "Python is a programming language.", "assistant": "Got it."},
            {"user": "The weather is nice today.", "assistant": "Glad to hear it."},
        ]
        result = select_relevant_turns("What does Python use?", turns)
        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.selected[0]["turn"]["user"],
                         "Python is a programming language.")

    def test_bounded_context_keeps_the_relevant_turn(self):
        relevant = _relevant([_item(0, 1, "Python is great.", "Agreed.")])
        chosen = select_bounded_context(relevant)
        self.assertEqual(chosen, [{"user": "Python is great.", "assistant": "Agreed."}])


class TestIrrelevantOldContextIsExcluded(unittest.TestCase):
    """2. irrelevant old context is excluded when possible"""

    def test_unrelated_turn_scores_zero_and_is_not_selected(self):
        turns = [{"user": "The weather is nice today.", "assistant": "Glad to hear it."}]
        result = select_relevant_turns("What does Python use?", turns)
        self.assertEqual(result.selected_count, 0)

    def test_lower_ranked_turn_is_dropped_when_budget_is_tight(self):
        relevant = _relevant([
            _item(0, 1, "most relevant turn", "ok"),
            _item(1, 2, "less relevant turn", "sure"),
        ])
        chosen = select_bounded_context(relevant, max_turns=1)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0]["user"], "most relevant turn")


class TestActiveTopicIsPreservedWhenRelevant(unittest.TestCase):
    """3. active topic is preserved when relevant"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_topic_relevant_turn_survives_bounding(self):
        # Establish an active topic ("robot"), then continue it.
        self.core.process_input("I am building a game about a robot.")
        self.assertEqual(self.core.get_active_topic().topic, "robot game")
        self.core.process_input("Tell me more about the robot.")
        understanding = self.core.get_last_language_understanding()
        relevant = understanding.conversation_context
        self.assertIsNotNone(relevant)
        self.assertGreater(len(relevant["selected"]), 0)
        chosen = select_bounded_context(relevant)
        # The turn that established the active topic is not dropped.
        self.assertTrue(any("robot" in turn["user"].lower() for turn in chosen))


class TestResolvedReferenceContextIsPreservedWhenRelevant(unittest.TestCase):
    """4. resolved reference context is preserved when relevant"""

    def test_reference_target_turn_is_selected_and_kept(self):
        # "it" in a message points at the most recent turn - see
        # context/relevance.py's own "reference" scoring signal, which
        # context/message_reference_resolution.py's resolve_conversational_-
        # reference then treats as the resolved referent (always the
        # rank-#1 selected turn).
        turns = [
            {"user": "Unrelated earlier remark.", "assistant": "Ok."},
            {"user": "Python is a programming language.", "assistant": "Got it."},
        ]
        relevant_context = select_relevant_turns("What does it use?", turns)
        self.assertEqual(relevant_context.selected_count, 1)
        self.assertIn("reference:it", relevant_context.selected[0]["reasons"])
        chosen = select_bounded_context(relevant_context.to_dict())
        self.assertTrue(any("Python" in turn["user"] for turn in chosen))

    def test_reference_target_survives_even_under_a_tight_turn_budget(self):
        # The resolved-reference turn is always rank #1 (see module
        # docstring); a tight max_turns must still keep it.
        relevant = _relevant([
            _item(0, 1, "the resolved reference turn", "yes"),
            _item(1, 2, "some other, less relevant turn", "sure"),
        ])
        chosen = select_bounded_context(relevant, max_turns=1)
        self.assertEqual(chosen, [{"user": "the resolved reference turn", "assistant": "yes"}])


class TestEmptyContextWorksCorrectly(unittest.TestCase):
    """5. empty context works correctly"""

    def test_none_relevant_context_yields_empty_list(self):
        self.assertEqual(select_bounded_context(None), [])

    def test_empty_selected_yields_empty_list(self):
        self.assertEqual(select_bounded_context(_relevant([])), [])

    def test_focused_conversation_with_no_understanding_context_and_no_live_context(self):
        understanding = _make_understanding("Hello.")  # no relevant_context given
        self.assertIsNone(understanding.conversation_context)
        messages = focused_conversation_from_context(understanding, None, max_turns=4)
        self.assertEqual(messages, [])


class TestContextSizeRemainsBounded(unittest.TestCase):
    """6. context size remains bounded"""

    def test_max_turns_is_respected(self):
        items = [_item(i, i + 1, f"turn {i}", f"reply {i}") for i in range(10)]
        chosen = select_bounded_context(_relevant(items), max_turns=3)
        self.assertLessEqual(len(chosen), 3)

    def test_max_chars_is_respected(self):
        # Each turn fits the budget on its own, but not all of them
        # together - the least relevant (highest rank) one must be
        # dropped rather than the total silently exceeding max_chars.
        medium_text = "x" * 1500
        items = [
            _item(0, 1, medium_text, medium_text),
            _item(1, 2, medium_text, medium_text),
            _item(2, 3, medium_text, medium_text),
        ]
        chosen = select_bounded_context(_relevant(items), max_turns=5, max_chars=4000)
        total_chars = sum(len(t["user"]) + len(t["assistant"]) for t in chosen)
        self.assertLessEqual(total_chars, 4000)
        self.assertEqual(len(chosen), 1)  # only one 3000-char turn fits under 4000

    def test_top_turn_is_kept_even_if_it_alone_exceeds_the_budget(self):
        huge_text = "x" * 10000
        items = [_item(0, 1, huge_text, huge_text)]
        chosen = select_bounded_context(_relevant(items), max_turns=4, max_chars=100)
        self.assertEqual(len(chosen), 1)  # never reduced to nothing

    def test_default_limits_are_small_fixed_numbers(self):
        self.assertIsInstance(DEFAULT_FOCUSED_MAX_TURNS, int)
        self.assertGreater(DEFAULT_FOCUSED_MAX_TURNS, 0)
        self.assertIsInstance(DEFAULT_FOCUSED_MAX_CHARS, int)
        self.assertGreater(DEFAULT_FOCUSED_MAX_CHARS, 0)

    def test_a_long_old_conversation_does_not_blow_up_the_request(self):
        items = [_item(i, i + 1, f"turn number {i} " * 20, f"reply {i} " * 20)
                 for i in range(50)]
        chosen = select_bounded_context(_relevant(items))
        self.assertLessEqual(len(chosen), DEFAULT_FOCUSED_MAX_TURNS)
        total_chars = sum(len(t["user"]) + len(t["assistant"]) for t in chosen)
        self.assertLessEqual(total_chars, DEFAULT_FOCUSED_MAX_CHARS)


class TestOriginalUserMessageIsUnchanged(unittest.TestCase):
    """7. original user message is unchanged"""

    def test_original_input_never_touched_by_context_selection(self):
        raw = "  Python   is    great!!  "
        understanding = _make_understanding(
            raw, relevant_context=_relevant([_item(0, 1, "earlier turn", "earlier reply")])
        )
        request = build_inference_request(understanding, context=None, max_context_turns=4)
        self.assertEqual(request.user_input, raw)

    def test_context_selection_does_not_mutate_the_relevant_context_input(self):
        relevant = _relevant([_item(0, 1, "hello", "hi")])
        before = relevant.to_dict()
        select_bounded_context(relevant)
        self.assertEqual(relevant.to_dict(), before)

    def test_persian_and_mixed_script_text_is_kept_verbatim(self):
        persian_turn = _item(0, 1, "برنامه نویسی پایتون Python 3.12", "بله")
        chosen = select_bounded_context(_relevant([persian_turn]))
        self.assertEqual(chosen[0]["user"], "برنامه نویسی پایتون Python 3.12")
        self.assertEqual(chosen[0]["assistant"], "بله")


class TestExistingConversationBehaviorRemainsCompatible(unittest.TestCase):
    """8. existing conversation behavior remains compatible"""

    def test_blind_fallback_still_works_without_a_relevance_selected_understanding(self):
        context = ConversationContext()
        context.add_turn("first q", "first a")
        context.add_turn("second q", "second a")
        understanding = _make_understanding("third q")  # no relevant_context given
        messages = focused_conversation_from_context(understanding, context, max_turns=1)
        self.assertEqual([(m.role, m.content) for m in messages],
                         [("user", "second q"), ("assistant", "second a")])

    def test_conversation_from_context_is_unchanged(self):
        context = ConversationContext()
        context.add_turn("q", "a")
        self.assertEqual(len(conversation_from_context(context, 4)), 2)
        self.assertEqual(conversation_from_context(context, 0), [])
        self.assertEqual(conversation_from_context(None, 4), [])

    def test_ordinary_process_input_conversation_is_unaffected(self):
        tmpdir = tempfile.TemporaryDirectory()
        try:
            db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
            skills_dir = os.path.join(tmpdir.name, "skills")
            core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)
            reply = core.process_input("qwerty zzznoxyzzz unmapped concept")
            self.assertIn("I don't have enough information", reply)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
