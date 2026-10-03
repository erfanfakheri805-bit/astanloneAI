"""
Tests for Prompt 395: multi-turn follow-up understanding.

The Active Topic tracker (context/active_topic.py, Prompt 393) now also
keeps a small conversation-thread record, so a later message is judged
against the *current thread* - not only the previous message or the
topic phrase - and Response Construction (core/core.py's
_construct_fallback_reply, Prompts 391/394) receives that thread state
in `Core.last_response_context["thread"]`. Every message is one of:
new_topic, follow_up, isolated, or ambiguous (no relationship invented).
The thread's word memory is bounded by the ConversationContext limit.

Run directly:
    python -m unittest tests.test_multi_turn_followup -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context.active_topic import (
    ActiveTopicTracker,
    ConversationThreadState,
    determine_active_topic,
    STATUS_NEW_TOPIC,
    STATUS_FOLLOW_UP,
    STATUS_ISOLATED,
    STATUS_AMBIGUOUS,
)
from context.message_reference_resolution import resolve_conversational_reference
from context.relevance import select_relevant_turns
from context.topic_awareness import assess_topic_awareness
from core.core import Core

OLD_FALLBACK = (
    "I don't have enough information to answer that yet. "
    "You can teach me using AEL, for example:\n"
    "TEACH sun IS a star at the center of the solar system\n"
    "or ask what I already know with: ASK sun"
)
ROBOT = "I am building a mobile game about a robot."
WEAPONS = "What weapons should it have?"
BOSS = "What about the boss?"
BOSS_ATTACK = "How should the boss attack?"
PYTHON = "also, how do I sort a Python list?"
AWARE_MARKER = "I'm treating this as a follow-up about"


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


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def say(self, message):
        reply = self.core.process_input(message)
        return reply, self.core.last_response_context["thread"]


class TestFirstMessageCreatesThread(CoreTestCase):
    """1. First message creates a conversation thread."""

    def test_first_message_starts_thread_one(self):
        _, thread = self.say(ROBOT)
        self.assertIsInstance(thread, ConversationThreadState)
        self.assertEqual(thread.thread_id, 1)
        self.assertEqual(thread.topic, "robot game mobile")
        self.assertEqual(thread.continuation, STATUS_NEW_TOPIC)
        self.assertEqual(thread.turn_count, 1)
        self.assertIsNone(thread.last_resolved_reference)
        self.assertIn("robot", thread.terms)

    def test_thread_state_is_structured(self):
        _, thread = self.say(ROBOT)
        self.assertEqual(
            set(thread.to_dict()),
            {"thread_id", "topic", "continuation", "turn_count", "last_resolved_reference", "terms"},
        )

    def test_no_thread_exists_before_any_message(self):
        thread = ActiveTopicTracker().thread
        self.assertEqual(thread.thread_id, 0)
        self.assertIsNone(thread.topic)
        self.assertEqual(thread.continuation, STATUS_ISOLATED)


class TestSecondRelatedMessageContinues(CoreTestCase):
    """2. Second related message continues the thread."""

    def test_reference_follow_up_continues_the_thread(self):
        self.say(ROBOT)
        reply, thread = self.say(WEAPONS)
        self.assertEqual(thread.thread_id, 1)
        self.assertEqual(thread.continuation, STATUS_FOLLOW_UP)
        self.assertEqual(thread.turn_count, 2)
        self.assertEqual(thread.topic, "robot game mobile")
        self.assertEqual(thread.last_resolved_reference, ROBOT)
        self.assertIn(AWARE_MARKER, reply)
        self.assertIn("weapons", thread.terms)


class TestThirdRelatedMessageContinuesSameThread(CoreTestCase):
    """3. Third related message continues the same thread."""

    def test_the_whole_chain_stays_in_one_thread(self):
        self.say(ROBOT)
        self.say(WEAPONS)
        _, third = self.say(BOSS)
        reply, fourth = self.say(BOSS_ATTACK)
        self.assertEqual((third.thread_id, third.continuation, third.turn_count), (1, STATUS_FOLLOW_UP, 3))
        # "boss" appeared only in the previous message: the fourth is
        # matched against the thread, not just the topic phrase.
        self.assertEqual((fourth.thread_id, fourth.continuation, fourth.turn_count), (1, STATUS_FOLLOW_UP, 4))
        self.assertEqual(fourth.topic, "robot game mobile")
        self.assertIn('"robot game mobile"', reply)
        self.assertEqual(self.core.get_active_topic().topic, "robot game mobile")

    def test_thread_words_grow_with_the_conversation(self):
        for message in (ROBOT, WEAPONS, BOSS, BOSS_ATTACK):
            _, thread = self.say(message)
        for word in ("robot", "weapons", "boss", "attack"):
            self.assertIn(word, thread.terms)


class TestReferenceSeveralTurnsLater(CoreTestCase):
    """4. A reference several turns later resolves against relevant context."""

    def test_the_game_i_mentioned_resolves_to_the_first_turn(self):
        for message in (ROBOT, WEAPONS, BOSS, BOSS_ATTACK):
            self.say(message)
        reply, thread = self.say("Give me ideas for the game I mentioned.")
        ctx = self.core.last_response_context
        self.assertTrue(ctx["resolved_reference"].has_reference)
        self.assertEqual(ctx["resolved_reference"].resolved_context, ROBOT)
        self.assertEqual(thread.thread_id, 1)
        self.assertEqual(thread.continuation, STATUS_FOLLOW_UP)
        self.assertEqual(thread.last_resolved_reference, ROBOT)
        self.assertEqual(ctx["current_input"], "Give me ideas for the game I mentioned.")

    def test_it_after_a_chain_resolves_to_the_latest_relevant_turn(self):
        for message in (ROBOT, WEAPONS, BOSS):
            self.say(message)
        _, thread = self.say("How should it attack?")
        ctx = self.core.last_response_context
        self.assertEqual(ctx["resolved_reference"].resolved_context, BOSS)
        self.assertEqual((thread.thread_id, thread.continuation), (1, STATUS_FOLLOW_UP))
        self.assertEqual(thread.topic, "robot game mobile")


class TestClearSubjectChangeStartsNewThread(CoreTestCase):
    """5. A clear subject change starts a new thread."""

    def setUp(self):
        super().setUp()
        for message in (ROBOT, WEAPONS, BOSS, BOSS_ATTACK):
            self.say(message)

    def test_also_new_subject_starts_thread_two(self):
        reply, thread = self.say(PYTHON)
        self.assertEqual(thread.thread_id, 2)
        self.assertEqual(thread.continuation, STATUS_NEW_TOPIC)
        self.assertEqual(thread.turn_count, 1)
        self.assertEqual(thread.topic, "sort python list")
        self.assertNotIn("boss", thread.terms)
        self.assertNotIn("robot", reply)
        self.assertEqual(reply, OLD_FALLBACK)

    def test_follow_ups_after_the_change_belong_to_the_new_thread_only(self):
        self.say(PYTHON)
        reply, thread = self.say("How should it work?")
        self.assertEqual((thread.thread_id, thread.continuation), (2, STATUS_FOLLOW_UP))
        self.assertEqual(thread.topic, "sort python list")
        self.assertNotIn("robot", reply)
        self.assertNotIn("boss", reply)

    def test_old_thread_words_no_longer_continue_anything(self):
        self.say(PYTHON)
        _, thread = self.say("How should the boss attack?")
        self.assertNotEqual(thread.thread_id, 1)
        self.assertEqual(thread.continuation, STATUS_NEW_TOPIC)


class TestAmbiguousMessageDoesNotFabricateContinuity(CoreTestCase):
    """6. An ambiguous message does not fabricate continuity."""

    def _tied(self, message):
        relevant = select_relevant_turns(message, [turn("I like the song."), turn("I like the movie.")])
        relevant.selected = [
            {"turn": turn("I like the song."), "index": 0, "rank": 1, "score": 1.0,
             "matched_terms": [], "reasons": ["reference:it"], "covers_message_terms": False},
            {"turn": turn("I like the movie."), "index": 1, "rank": 1, "score": 1.0,
             "matched_terms": [], "reasons": ["reference:it"], "covers_message_terms": False},
        ]
        return relevant

    def test_ambiguous_reference_leaves_the_thread_untouched(self):
        tracker = ActiveTopicTracker()
        for message in (ROBOT, BOSS):
            tracker.update(message)
        before = tracker.thread.to_dict()
        message = "What features does it need?"
        relevant = self._tied(message)
        resolved = resolve_conversational_reference(message, relevant)
        self.assertTrue(resolved.ambiguous)
        result = tracker.update(message, relevant, resolved)
        thread = tracker.thread
        self.assertEqual(thread.continuation, STATUS_AMBIGUOUS)
        self.assertEqual(result.topic, before["topic"])
        self.assertEqual(thread.turn_count, before["turn_count"])
        self.assertEqual(thread.terms, before["terms"])
        self.assertEqual(thread.thread_id, before["thread_id"])
        self.assertFalse(assess_topic_awareness(message, relevant, resolved, result).topic_aware)

    def test_ambiguous_reply_contains_no_topic_context(self):
        self.core.topic_tracker.update(ROBOT)
        message = "What features does it need?"
        relevant = self._tied(message)
        resolved = resolve_conversational_reference(message, relevant)
        self.core.topic_tracker.update(message, relevant, resolved)
        reply = self.core._construct_fallback_reply(
            message, relevant, resolved, self.core.get_active_topic(), thread=self.core.topic_tracker.thread
        )
        self.assertEqual(self.core.last_response_context["thread"].continuation, STATUS_AMBIGUOUS)
        self.assertNotIn(AWARE_MARKER, reply)
        self.assertNotIn("robot", reply)

    def test_contentless_message_is_isolated_not_a_follow_up(self):
        self.say(ROBOT)
        reply, thread = self.say("Okay.")
        self.assertEqual(thread.continuation, STATUS_ISOLATED)
        self.assertEqual(thread.turn_count, 1)
        self.assertEqual(reply, OLD_FALLBACK)

    def test_isolated_when_no_thread_exists(self):
        _, thread = self.say("Okay.")
        self.assertEqual((thread.thread_id, thread.continuation), (0, STATUS_ISOLATED))
        self.assertIsNone(thread.topic)


class TestBoundedContextLimitsAreRespected(unittest.TestCase):
    """7. Bounded context limits are still respected."""

    SEQUENCE = (ROBOT, BOSS, "What about the levels?", "What about the music?")

    def _run(self, window):
        tracker = ActiveTopicTracker(window=window)
        for message in self.SEQUENCE:
            tracker.update(message)
        tracker.update(BOSS_ATTACK)
        return tracker.thread

    def test_within_the_window_the_old_word_still_continues_the_thread(self):
        thread = self._run(window=10)
        self.assertEqual(thread.continuation, STATUS_FOLLOW_UP)
        self.assertEqual(thread.thread_id, 1)

    def test_outside_the_window_the_old_word_is_forgotten(self):
        thread = self._run(window=2)
        self.assertEqual(thread.continuation, STATUS_NEW_TOPIC)
        self.assertEqual(thread.thread_id, 2)

    def test_thread_words_are_bounded_by_the_window(self):
        tracker = ActiveTopicTracker(window=2)
        for message in self.SEQUENCE:
            tracker.update(message)
        self.assertEqual(sorted(tracker.thread.terms), ["levels", "music"])
        self.assertEqual(tracker.thread.turn_count, 4)

    def test_invalid_window_is_rejected(self):
        with self.assertRaises(ValueError):
            ActiveTopicTracker(window=0)

    def test_core_ties_the_thread_window_to_the_context_limit(self):
        for limit in (None, 3, 6):
            with self.subTest(limit=limit):
                kwargs = {} if limit is None else {"context_max_turns": limit}
                core, tmpdir = _make_core(**kwargs)
                self.addCleanup(tmpdir.cleanup)
                self.assertEqual(core.topic_tracker.window, core.context.max_size)

    def test_core_context_size_is_not_increased(self):
        core, tmpdir = _make_core(context_max_turns=3)
        self.addCleanup(tmpdir.cleanup)
        for message in (ROBOT, WEAPONS, BOSS, BOSS_ATTACK, "What about the levels?"):
            core.process_input(message)
        self.assertEqual(len(core.get_recent_turns()), 3)
        self.assertLessEqual(len(core.last_response_context["thread"].terms), 3 * 3)

    def test_reset_context_ends_the_thread(self):
        core, tmpdir = _make_core()
        self.addCleanup(tmpdir.cleanup)
        core.process_input(ROBOT)
        core.reset_context()
        thread = core.topic_tracker.thread
        self.assertEqual((thread.thread_id, thread.topic, thread.turn_count), (0, None, 0))


class TestResponseConstructionReceivesThreadState(CoreTestCase):
    """8. Response construction receives the correct thread state."""

    def test_thread_is_passed_to_construct_fallback_reply(self):
        original = self.core._construct_fallback_reply
        calls = []

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        with mock.patch.object(self.core, "_construct_fallback_reply", side_effect=spy):
            self.core.process_input(ROBOT)
            self.core.process_input(WEAPONS)
        self.assertEqual(len(calls), 2)
        first, second = calls[0][1]["thread"], calls[1][1]["thread"]
        self.assertEqual(first.continuation, STATUS_NEW_TOPIC)
        self.assertEqual(second.continuation, STATUS_FOLLOW_UP)
        self.assertEqual(second.thread_id, first.thread_id)

    def test_response_context_distinguishes_new_topic_follow_up_and_isolated(self):
        seen = []
        for message in (ROBOT, BOSS, "Okay.", PYTHON):
            self.core.process_input(message)
            seen.append(self.core.last_response_context["thread"].continuation)
        self.assertEqual(seen, [STATUS_NEW_TOPIC, STATUS_FOLLOW_UP, STATUS_ISOLATED, STATUS_NEW_TOPIC])

    def test_all_inputs_stay_separate_in_the_response_context(self):
        self.core.process_input(ROBOT)
        self.core.process_input(WEAPONS)
        ctx = self.core.last_response_context
        self.assertEqual(ctx["current_input"], WEAPONS)
        self.assertIsNotNone(ctx["relevant_context"])
        self.assertEqual(ctx["resolved_reference"].resolved_context, ROBOT)
        self.assertEqual(ctx["active_topic"].topic, ctx["thread"].topic)
        self.assertTrue(ctx["topic_awareness"].topic_aware)

    def test_thread_defaults_to_the_trackers_current_thread(self):
        self.core.process_input(ROBOT)
        message = WEAPONS
        relevant = select_relevant_turns(message, [turn(ROBOT)])
        self.core._construct_fallback_reply(message, relevant)
        self.assertIs(self.core.last_response_context["thread"], self.core.topic_tracker.thread)


class TestExistingBehaviorRemainsCompatible(CoreTestCase):
    """9. Existing conversation behavior remains compatible."""

    def test_determine_active_topic_keeps_its_original_signature(self):
        self.assertEqual(determine_active_topic(ROBOT).topic, "robot game mobile")
        self.assertEqual(determine_active_topic("What is Python?", "robot game").topic, "python")

    def test_unrelated_and_single_messages_get_the_plain_reply(self):
        self.assertEqual(self.core.process_input("Xyzzy plugh?"), OLD_FALLBACK)
        self.assertEqual(self.core.process_input("What is Python?"), OLD_FALLBACK)

    def test_repeated_statement_still_gets_the_plain_fallback(self):
        self.core.process_input("I am building it for Android.")
        self.assertEqual(self.core.process_input("I am building it for Android."), OLD_FALLBACK)

    def test_goal_requests_still_use_the_goal_path(self):
        self.core.process_input(ROBOT)
        self.assertTrue(self.core.process_input("I want three weapon ideas.").startswith("[GOAL CREATED]"))

    def test_elliptical_message_without_any_topic_starts_one_and_adds_nothing(self):
        reply, thread = self.say(BOSS)
        self.assertEqual(thread.continuation, STATUS_NEW_TOPIC)
        self.assertEqual(reply, OLD_FALLBACK)

    def test_original_input_is_kept_verbatim(self):
        self.core.process_input(ROBOT)
        self.core.process_input(BOSS)
        self.assertEqual(self.core.last_response_context["current_input"], BOSS)
        self.assertEqual(self.core.get_recent_turns()[-1]["user"], BOSS)


if __name__ == "__main__":
    unittest.main()
