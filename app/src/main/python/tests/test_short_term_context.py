"""
Tests for Prompt 389: short-term conversation context.

ConversationContext (context/conversation_context.py) keeps a bounded
window of recent {"user", "assistant"} turns, and Core.process_input()
records one turn per handled message. These tests check what is really
stored and retrieved - not just that calls succeed.

Run directly:
    python -m unittest tests.test_short_term_context -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context.conversation_context import ConversationContext, DEFAULT_CONTEXT_SIZE
from core.core import Core


def _make_core(**kwargs):
    tmpdir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
    skills_dir = os.path.join(tmpdir.name, "skills")
    core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir, **kwargs)
    return core, tmpdir, db_path, skills_dir


def _spy_on_reasoning(core):
    """Wrap core.reasoning.reason so each call records the context it was
    handed *at call time* - i.e. what the reasoning path can actually see
    while a message is being processed."""
    original = core.reasoning.reason
    seen = []

    def spy(query, context=None, **kwargs):
        seen.append({
            "query": query,
            "context": context,
            "turns": context.get_recent_turns() if context is not None else None,
        })
        return original(query, context=context, **kwargs)

    core.reasoning.reason = spy
    return seen


# ----------------------------------------------------------------------
# ConversationContext turn window, on its own
# ----------------------------------------------------------------------
class TestTurnWindow(unittest.TestCase):
    def test_empty_context_has_no_turns(self):
        context = ConversationContext()
        self.assertEqual(context.get_recent_turns(), [])
        self.assertEqual(context.get_recent_turns(limit=5), [])

    def test_recent_user_message_is_retained(self):
        context = ConversationContext()
        context.add_turn("My project is called Echo Shift.", "Got it.")
        turns = context.get_recent_turns()
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["user"], "My project is called Echo Shift.")

    def test_recent_assistant_response_is_retained(self):
        context = ConversationContext()
        context.add_turn("My project is called Echo Shift.", "Got it.")
        self.assertEqual(context.get_recent_turns()[0]["assistant"], "Got it.")

    def test_multiple_turns_remain_ordered_oldest_first(self):
        context = ConversationContext()
        context.add_turn("one", "reply one")
        context.add_turn("two", "reply two")
        context.add_turn("three", "reply three")
        self.assertEqual(
            context.get_recent_turns(),
            [
                {"user": "one", "assistant": "reply one"},
                {"user": "two", "assistant": "reply two"},
                {"user": "three", "assistant": "reply three"},
            ],
        )

    def test_context_is_bounded_by_configured_limit(self):
        context = ConversationContext(max_size=4)
        for i in range(20):
            context.add_turn(f"u{i}", f"a{i}")
        self.assertEqual(len(context.get_recent_turns()), 4)

    def test_old_turns_are_removed_when_limit_is_exceeded(self):
        context = ConversationContext(max_size=3)
        for i in range(1, 6):
            context.add_turn(f"u{i}", f"a{i}")
        turns = context.get_recent_turns()
        self.assertEqual([t["user"] for t in turns], ["u3", "u4", "u5"])
        self.assertEqual([t["assistant"] for t in turns], ["a3", "a4", "a5"])
        all_text = " ".join(t["user"] + " " + t["assistant"] for t in turns)
        self.assertNotIn("u1", all_text.split())
        self.assertNotIn("a2", all_text.split())

    def test_turns_up_to_the_limit_are_all_kept(self):
        context = ConversationContext(max_size=3)
        for i in range(1, 4):
            context.add_turn(f"u{i}", f"a{i}")
        self.assertEqual([t["user"] for t in context.get_recent_turns()], ["u1", "u2", "u3"])

    def test_limit_of_one_keeps_only_the_latest_turn(self):
        context = ConversationContext(max_size=1)
        context.add_turn("first", "a")
        context.add_turn("second", "b")
        self.assertEqual(context.get_recent_turns(), [{"user": "second", "assistant": "b"}])

    def test_limit_argument_returns_most_recent_only(self):
        context = ConversationContext()
        for i in range(1, 6):
            context.add_turn(f"u{i}", f"a{i}")
        self.assertEqual([t["user"] for t in context.get_recent_turns(limit=2)], ["u4", "u5"])
        self.assertEqual(context.get_recent_turns(limit=0), [])

    def test_returned_turns_are_copies(self):
        context = ConversationContext()
        context.add_turn("hello", "hi")
        context.get_recent_turns()[0]["user"] = "tampered"
        self.assertEqual(context.get_recent_turns()[0]["user"], "hello")

    def test_reset_clears_turns(self):
        context = ConversationContext()
        context.add_turn("hello", "hi")
        context.reset()
        self.assertEqual(context.get_recent_turns(), [])
        context.reset()  # resetting an empty context is fine
        context.add_turn("again", "yes")
        self.assertEqual(len(context.get_recent_turns()), 1)


# ----------------------------------------------------------------------
# Through Core.process_input() - the real conversation pipeline
# ----------------------------------------------------------------------
class TestCoreRecordsTurns(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir, self.db_path, self.skills_dir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_fresh_core_has_empty_context(self):
        self.assertEqual(self.core.get_recent_turns(), [])

    def test_process_input_stores_user_message_and_actual_reply(self):
        reply = self.core.process_input("What is glorp?")
        self.assertEqual(
            self.core.get_recent_turns(),
            [{"user": "What is glorp?", "assistant": reply}],
        )

    def test_turns_stay_ordered_across_messages(self):
        replies = [self.core.process_input(f"What is thing{i}?") for i in range(4)]
        turns = self.core.get_recent_turns()
        self.assertEqual([t["user"] for t in turns], [f"What is thing{i}?" for i in range(4)])
        self.assertEqual([t["assistant"] for t in turns], replies)

    def test_empty_input_records_nothing(self):
        self.core.process_input("   ")
        self.core.process_input("")
        self.assertEqual(self.core.get_recent_turns(), [])

    def test_every_handling_path_records_its_turn(self):
        """AEL command, goal request, skill-matched greeting and an
        ordinary question are all part of the conversation."""
        ael = self.core.process_input("TEACH sun IS a star at the center of the solar system")
        goal = self.core.process_input("I want to learn Python")
        greeting = self.core.process_input("hello")
        question = self.core.process_input("What is glorp?")

        self.assertIn("[AEL OK]", ael)
        self.assertIn("[GOAL CREATED]", goal)
        turns = self.core.get_recent_turns()
        self.assertEqual([t["assistant"] for t in turns], [ael, goal, greeting, question])
        self.assertEqual(turns[2]["user"], "hello")

    def test_default_limit_is_applied(self):
        self.assertEqual(self.core.context.max_size, DEFAULT_CONTEXT_SIZE)
        for i in range(DEFAULT_CONTEXT_SIZE + 3):
            self.core.process_input(f"What is thing{i}?")
        turns = self.core.get_recent_turns()
        self.assertEqual(len(turns), DEFAULT_CONTEXT_SIZE)
        self.assertEqual(turns[0]["user"], "What is thing3?")
        self.assertEqual(turns[-1]["user"], f"What is thing{DEFAULT_CONTEXT_SIZE + 2}?")

    def test_limit_is_configurable_and_old_turns_are_dropped(self):
        core, tmpdir, _, _ = _make_core(context_max_turns=3)
        try:
            for i in range(1, 6):
                core.process_input(f"What is thing{i}?")
            turns = core.get_recent_turns()
            self.assertEqual([t["user"] for t in turns],
                             ["What is thing3?", "What is thing4?", "What is thing5?"])
            self.assertNotIn("What is thing1?", [t["user"] for t in turns])
        finally:
            tmpdir.cleanup()

    def test_invalid_configured_limit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                Core(memory_db_path=os.path.join(tmp, "m.sqlite3"),
                     skill_definitions_dir=os.path.join(tmp, "skills"),
                     context_max_turns=0)


class TestReasoningPathSeesRecentContext(unittest.TestCase):
    """The prompt's two required conversations: when the second message
    is processed, the reasoning path is handed a context that already
    holds the first turn (user message + the assistant's real reply)."""

    def setUp(self):
        self.core, self._tmpdir, _, _ = _make_core()
        self.seen = _spy_on_reasoning(self.core)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_project_name_conversation(self):
        first = "My project is called Echo Shift."
        question = "What is my project called?"

        first_reply = self.core.process_input(first)
        self.assertTrue(first_reply.startswith("Got it"))
        answer = self.core.process_input(question)

        self.assertEqual(len(self.seen), 1)
        self.assertEqual(self.seen[0]["query"], question)
        self.assertIs(self.seen[0]["context"], self.core.context)
        self.assertEqual(self.seen[0]["turns"], [{"user": first, "assistant": first_reply}])
        self.assertIn("Echo Shift", answer)

        self.assertEqual(
            self.core.get_recent_turns(),
            [{"user": first, "assistant": first_reply}, {"user": question, "assistant": answer}],
        )

    def test_python_conversation(self):
        statement = "Python is a programming language."
        question = "What is Python?"

        statement_reply = self.core.process_input(statement)
        answer = self.core.process_input(question)

        self.assertEqual(len(self.seen), 1)
        self.assertEqual(self.seen[0]["turns"], [{"user": statement, "assistant": statement_reply}])
        self.assertIn("programming language", answer)
        self.assertEqual(
            [t["user"] for t in self.core.get_recent_turns()], [statement, question]
        )

    def test_current_message_is_not_yet_a_turn_while_it_is_processed(self):
        self.core.process_input("What is glorp?")
        self.core.process_input("What is flibber?")
        # The 2nd call saw only the 1st turn; the 1st call saw none.
        self.assertEqual(self.seen[0]["turns"], [])
        self.assertEqual([t["user"] for t in self.seen[1]["turns"]], ["What is glorp?"])


class TestContextIsShortTermOnly(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir, self.db_path, self.skills_dir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_chatting_creates_no_permanent_memory_per_message(self):
        before = self.core.memory.counts()
        for text in ["hello", "What is glorp?", "Tell me about flibber", "What is zonk?"]:
            self.core.process_input(text)
        self.assertEqual(self.core.memory.counts(), before)
        self.assertEqual(len(self.core.get_recent_turns()), 4)

    def test_learned_statement_is_stored_once_not_once_per_turn(self):
        self.core.process_input("Python is a programming language.")
        knowledge_after_statement = self.core.memory.counts()["knowledge_count"]
        for i in range(5):
            self.core.process_input(f"What is thing{i}?")
        self.assertEqual(self.core.memory.counts()["knowledge_count"], knowledge_after_statement)

    def test_context_is_not_persisted_across_restarts(self):
        self.core.process_input("My project is called Echo Shift.")
        self.assertEqual(len(self.core.get_recent_turns()), 1)

        restarted = Core(memory_db_path=self.db_path, skill_definitions_dir=self.skills_dir)
        self.assertEqual(restarted.get_recent_turns(), [])

    def test_reset_context_clears_turns_but_keeps_knowledge(self):
        self.core.process_input("Python is a programming language.")
        self.core.reset_context()
        self.assertEqual(self.core.get_recent_turns(), [])
        self.assertEqual(self.core.get_recent_context(), [])
        self.assertIn("programming language", self.core.process_input("What is Python?"))


class TestExistingConversationBehaviourUnchanged(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir, _, _ = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_replies_are_the_same_kinds_as_before(self):
        self.assertIn("I don't have enough information", self.core.process_input("What is glorp?"))
        self.assertIn("Hello!", self.core.process_input("hello"))
        self.assertIn("[AEL OK]", self.core.process_input("TEACH moon IS a rock in orbit"))
        self.assertIn("[GOAL CREATED]", self.core.process_input("I want to learn Python"))
        self.assertEqual(
            self.core.process_input("Rust is a programming language."),
            "Got it, I'll remember that: Rust is a programming language.",
        )
        self.assertEqual(self.core.process_input("What is Rust?"), "Rust is a programming language.")

    def test_understanding_entries_still_recorded_alongside_turns(self):
        self.core.process_input("Python is a programming language.")
        entries = self.core.get_recent_context()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["input_text"], "Python is a programming language.")
        self.assertEqual(len(self.core.get_recent_turns()), 1)

    def test_follow_up_reference_resolution_still_works(self):
        self.core.process_input("Python is a programming language.")
        self.core.process_input("It uses indentation.")
        self.assertIn("indentation", self.core.process_input("What does Python use?"))

    def test_process_input_still_returns_text(self):
        for text in ["hello", "What is glorp?", "TEACH a IS b", "I need to fix the bug"]:
            self.assertIsInstance(self.core.process_input(text), str)


if __name__ == "__main__":
    unittest.main()
