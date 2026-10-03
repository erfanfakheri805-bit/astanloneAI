"""
Tests for Prompt 391: connecting relevant conversation context
(context/relevance.py, Prompt 390) to Response Construction.

Prompt 390 built the selector (context/relevance.py) and exposed it as
Core.get_relevant_context(). Prompt 391's only job is to make sure the
result of that selection is actually *handed to* the part of Core that
builds the reply, as a value distinct from the current user input,
instead of being (re)computed inside the reply-builder itself. See
core/core.py: Core._handle_conversation (step 5),
Core._construct_fallback_reply, and Core._recall_from_relevant_context.

Run directly:
    python -m unittest tests.test_response_construction_context -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context.relevance import select_relevant_turns
from core.core import Core

OLD_FALLBACK = (
    "I don't have enough information to answer that yet. "
    "You can teach me using AEL, for example:\n"
    "TEACH sun IS a star at the center of the solar system\n"
    "or ask what I already know with: ASK sun"
)


def turn(user, assistant="Okay."):
    return {"user": user, "assistant": assistant}


def _make_core(**kwargs):
    tmpdir = tempfile.TemporaryDirectory()
    core = Core(
        memory_db_path=os.path.join(tmpdir.name, "test_memory.sqlite3"),
        skill_definitions_dir=os.path.join(tmpdir.name, "skills"),
        **kwargs,
    )
    return core, tmpdir


class TestRelevantContextReachesResponseConstruction(unittest.TestCase):
    """1. Relevant context is passed into response construction, and
    2. response construction can access (and use) the selected context -
    without Core needing a second, independent lookup to do it."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_fallback_reply_is_built_from_the_passed_in_context(self):
        # Build a RelevantContextResult entirely by hand - never stored
        # in self.core.context at all - and hand it straight to the
        # response-construction method. If the reply reflects it, the
        # method is genuinely consuming the object it was given, not
        # re-deriving its own answer from Core's real conversation state.
        relevant = select_relevant_turns(
            "What am I building it for?",
            [turn("I am building it for Android.")],
        )
        reply = self.core._construct_fallback_reply(
            "What am I building it for?", relevant
        )
        self.assertIn('you said: "I am building it for Android."', reply)

    def test_handle_conversation_passes_its_own_selection_through(self):
        # End-to-end: process_input() drives _handle_conversation(),
        # which must select relevant context and feed that exact
        # selection to response construction for the reply to come out
        # this way at all (nothing else in Core would produce this text).
        self.core.process_input("I am building it for Android.")
        reply = self.core.process_input("What am I building it for?")
        self.assertIn('you said: "I am building it for Android."', reply)

    def test_construct_fallback_reply_uses_the_object_not_the_text_alone(self):
        # Same current_input string, two different pre-selected
        # RelevantContextResult objects -> two different replies. This
        # is only possible if the method actually reads the object it
        # was passed instead of recomputing something from the string.
        question = "What am I building it for?"
        android_context = select_relevant_turns(
            question, [turn("I am building it for Android.")]
        )
        windows_context = select_relevant_turns(
            question, [turn("I am building it for Windows.")]
        )
        android_reply = self.core._construct_fallback_reply(question, android_context)
        windows_reply = self.core._construct_fallback_reply(question, windows_context)
        self.assertIn("Android", android_reply)
        self.assertIn("Windows", windows_reply)
        self.assertNotIn("Windows", android_reply)
        self.assertNotIn("Android", windows_reply)


class TestIrrelevantContextIsNotInjected(unittest.TestCase):
    """3. Irrelevant context is not injected into the reply."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_unrelated_selected_turn_is_not_quoted(self):
        # A RelevantContextResult that selected something, but not
        # something that covers this question, must not be quoted.
        relevant = select_relevant_turns(
            "What is my dog called?",
            [turn("I am building it for Android.")],
        )
        reply = self.core._construct_fallback_reply("What is my dog called?", relevant)
        self.assertEqual(reply, OLD_FALLBACK)

    def test_end_to_end_unrelated_history_is_not_injected(self):
        self.core.process_input("I am building it for Android.")
        reply = self.core.process_input("What is glorp?")
        self.assertEqual(reply, OLD_FALLBACK)
        self.assertNotIn("Android", reply)


class TestEmptyContextPreservesExistingBehaviour(unittest.TestCase):
    """4. Empty context preserves existing (pre-390/391) behavior."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_empty_relevant_context_gives_the_unmodified_fallback(self):
        empty = select_relevant_turns("What is glorp?", [])
        self.assertEqual(empty.selected, [])
        reply = self.core._construct_fallback_reply("What is glorp?", empty)
        self.assertEqual(reply, OLD_FALLBACK)

    def test_no_conversation_history_gives_the_unmodified_fallback(self):
        self.assertEqual(self.core.process_input("What is glorp?"), OLD_FALLBACK)

    def test_relevant_context_none_falls_back_to_computing_it(self):
        # Optional-parameter backward compatibility: an older/other
        # caller that does not yet pass relevant_context still works,
        # by falling back to the same get_relevant_context() lookup
        # Prompt 390 already exposed.
        self.core.process_input("I am building it for Android.")
        recalled = self.core._recall_from_relevant_context(
            "What am I building it for?", relevant_context=None
        )
        self.assertEqual(recalled, "I am building it for Android.")


class TestExistingConversationTestsRemainCompatible(unittest.TestCase):
    """5. The pre-existing conversation/AEL/goal/skill behavior in Core
    is unaffected by wiring relevant context into response construction."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_every_reply_kind_is_as_before(self):
        self.assertEqual(self.core.process_input("What is glorp?"), OLD_FALLBACK)
        self.assertIn("Hello!", self.core.process_input("hello"))
        self.assertIn("[AEL OK]", self.core.process_input("TEACH moon IS a rock in orbit"))
        self.assertIn("[GOAL CREATED]", self.core.process_input("I want to learn Python"))
        self.assertEqual(
            self.core.process_input("Rust is a programming language."),
            "Got it, I'll remember that: Rust is a programming language.",
        )
        self.assertEqual(self.core.process_input("What is Rust?"), "Rust is a programming language.")

    def test_persistent_knowledge_still_outranks_conversation_recall(self):
        self.core.process_input("Python is a programming language.")
        self.core.process_input("I like Python.")
        self.assertEqual(
            self.core.process_input("What is Python?"), "Python is a programming language."
        )

    def test_get_relevant_context_itself_is_unchanged_and_read_only(self):
        self.core.process_input("Python is a programming language.")
        before = self.core.get_recent_turns()
        result = self.core.get_relevant_context("What is Python?")
        self.assertEqual([item["turn"]["user"] for item in result.selected],
                          ["Python is a programming language."])
        self.assertEqual(self.core.get_recent_turns(), before)


if __name__ == "__main__":
    unittest.main()
