"""
Tests for Prompt 393: active conversation topic tracking.

context/active_topic.py keeps one small, deterministic "what is being
discussed right now" value, built from the current message, the
already-selected relevant context (Prompt 390) and the already-resolved
reference (Prompt 392), and hands it to Response Construction
(core/core.py's _construct_fallback_reply, Prompt 391) as a separate
input - without replacing the original message, without inventing a
topic when there is nothing to build one from.

Run directly:
    python -m unittest tests.test_active_topic -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context.active_topic import (
    ActiveTopicTracker,
    ActiveTopicResult,
    determine_active_topic,
    SOURCE_CURRENT_INPUT,
    SOURCE_PREVIOUS_TOPIC,
    SOURCE_RESOLVED_REFERENCE,
    SOURCE_SHIFT_MARKER,
)
from context.relevance import select_relevant_turns
from context.message_reference_resolution import resolve_conversational_reference
from core.core import Core

OLD_FALLBACK = (
    "I don't have enough information to answer that yet. "
    "You can teach me using AEL, for example:\n"
    "TEACH sun IS a star at the center of the solar system\n"
    "or ask what I already know with: ASK sun"
)

ROBOT = "I am building a game about a robot."


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


def _track(tracker, message, turns=()):
    relevant = select_relevant_turns(message, list(turns))
    resolved = resolve_conversational_reference(message, relevant)
    return tracker.update(message, relevant, resolved)


class TestNewTopicIsDetected(unittest.TestCase):
    """1. A new topic is detected from a conversation."""

    def test_first_message_creates_a_topic(self):
        result = determine_active_topic(ROBOT)
        self.assertEqual(result.topic, "robot game")
        self.assertEqual(result.topic_source, SOURCE_CURRENT_INPUT)
        self.assertTrue(result.changed)
        self.assertIsNone(result.previous_topic)
        self.assertGreater(result.confidence, 0.0)

    def test_result_is_structured_and_serializable(self):
        result = determine_active_topic(ROBOT)
        self.assertIsInstance(result, ActiveTopicResult)
        self.assertEqual(
            set(result.to_dict()),
            {"topic", "topic_source", "confidence", "changed", "previous_topic", "reason"},
        )

    def test_tracker_remembers_the_topic(self):
        tracker = ActiveTopicTracker()
        _track(tracker, ROBOT)
        self.assertEqual(tracker.topic, "robot game")
        self.assertEqual(tracker.current.topic, "robot game")


class TestFollowUpKeepsTopic(unittest.TestCase):
    """2. A follow-up message keeps the active topic."""

    def setUp(self):
        self.tracker = ActiveTopicTracker()
        _track(self.tracker, ROBOT)

    def test_follow_up_sharing_a_word_keeps_the_topic(self):
        result = _track(self.tracker, "Add a boss level to the game.", [turn(ROBOT)])
        self.assertEqual(result.topic, "robot game")
        self.assertFalse(result.changed)
        self.assertEqual(result.previous_topic, "robot game")
        self.assertEqual(result.topic_source, SOURCE_PREVIOUS_TOPIC)

    def test_message_with_no_new_subject_keeps_the_topic(self):
        result = _track(self.tracker, "Tell me more.", [turn(ROBOT)])
        self.assertEqual(result.topic, "robot game")
        self.assertFalse(result.changed)

    def test_topic_kept_via_relevant_context_that_is_on_topic(self):
        # "levels" shares nothing with "robot game" itself, but the
        # selected earlier turn does, so the subject is continuing.
        turns = [turn("The robot game needs harder levels.")]
        result = _track(self.tracker, "What about the levels?", turns)
        self.assertEqual(result.topic, "robot game")
        self.assertFalse(result.changed)


class TestResolvedReferenceKeepsTopic(unittest.TestCase):
    """3. A resolved reference keeps the correct topic."""

    def test_it_resolving_to_the_game_keeps_the_robot_game_topic(self):
        tracker = ActiveTopicTracker()
        _track(tracker, ROBOT)
        message = "I want three weapons for it."
        turns = [turn(ROBOT)]
        relevant = select_relevant_turns(message, turns)
        resolved = resolve_conversational_reference(message, relevant)
        self.assertEqual(resolved.resolved_context, ROBOT)
        result = tracker.update(message, relevant, resolved)
        self.assertEqual(result.topic, "robot game")
        self.assertFalse(result.changed)
        self.assertEqual(result.topic_source, SOURCE_RESOLVED_REFERENCE)

    def test_reference_with_no_prior_topic_takes_topic_from_referent(self):
        tracker = ActiveTopicTracker()
        result = _track(tracker, "Give me three ideas for it.", [turn(ROBOT)])
        self.assertEqual(result.topic, "robot game")
        self.assertEqual(result.topic_source, SOURCE_RESOLVED_REFERENCE)

    def test_ambiguous_reference_does_not_move_the_topic(self):
        tracker = ActiveTopicTracker()
        _track(tracker, ROBOT)
        message = "Tell me more about it."
        relevant = select_relevant_turns(message, [turn("I like the song."), turn("I like the movie.")])
        # Force a tie by hand (same technique as Prompt 392's tests).
        relevant.selected = [
            {"turn": turn("I like the song."), "index": 0, "rank": 1, "score": 1.0,
             "matched_terms": [], "reasons": ["reference:it"], "covers_message_terms": False},
            {"turn": turn("I like the movie."), "index": 1, "rank": 1, "score": 1.0,
             "matched_terms": [], "reasons": ["reference:it"], "covers_message_terms": False},
        ]
        resolved = resolve_conversational_reference(message, relevant)
        self.assertTrue(resolved.ambiguous)
        result = tracker.update(message, relevant, resolved)
        self.assertEqual(result.topic, "robot game")
        self.assertNotEqual(result.topic_source, SOURCE_RESOLVED_REFERENCE)


class TestClearSubjectChangeUpdatesTopic(unittest.TestCase):
    """4. A clear subject change updates the topic."""

    def test_by_the_way_switches_to_the_new_subject(self):
        tracker = ActiveTopicTracker()
        _track(tracker, ROBOT)
        result = _track(tracker, "By the way, how do I make a Python list?", [turn(ROBOT)])
        self.assertEqual(result.topic, "python list")
        self.assertTrue(result.changed)
        self.assertEqual(result.previous_topic, "robot game")
        self.assertEqual(result.topic_source, SOURCE_SHIFT_MARKER)
        self.assertEqual(tracker.topic, "python list")

    def test_unrelated_message_without_a_marker_also_changes_topic(self):
        tracker = ActiveTopicTracker()
        _track(tracker, ROBOT)
        result = _track(tracker, "What is Python?", [turn(ROBOT)])
        self.assertEqual(result.topic, "python")
        self.assertTrue(result.changed)
        self.assertEqual(result.previous_topic, "robot game")

    def test_marker_with_nothing_after_it_changes_nothing(self):
        tracker = ActiveTopicTracker()
        _track(tracker, ROBOT)
        result = _track(tracker, "By the way.", [turn(ROBOT)])
        self.assertEqual(result.topic, "robot game")
        self.assertFalse(result.changed)


class TestMissingContextDoesNotFabricateTopic(unittest.TestCase):
    """5. Missing context does not create a fabricated topic."""

    def test_reference_with_no_context_and_no_topic(self):
        result = _track(ActiveTopicTracker(), "Give me three ideas for it.")
        self.assertIsNone(result.topic)
        self.assertIsNone(result.topic_source)
        self.assertEqual(result.confidence, 0.0)
        self.assertFalse(result.changed)

    def test_filler_only_messages_create_no_topic(self):
        for message in ("Okay.", "Yes please", "Tell me more.", "", "   ", None):
            with self.subTest(message=message):
                result = _track(ActiveTopicTracker(), message)
                self.assertIsNone(result.topic)

    def test_non_latin_message_creates_no_topic_and_keeps_existing(self):
        tracker = ActiveTopicTracker()
        self.assertIsNone(_track(tracker, "سلام دنیا").topic)
        _track(tracker, ROBOT)
        self.assertEqual(_track(tracker, "سلام دنیا").topic, "robot game")

    def test_none_context_arguments_do_not_raise(self):
        result = determine_active_topic("I am building a game about a robot.", None, None, None)
        self.assertEqual(result.topic, "robot game")

    def test_reset_clears_the_topic(self):
        tracker = ActiveTopicTracker()
        _track(tracker, ROBOT)
        tracker.reset()
        self.assertIsNone(tracker.topic)
        self.assertIsNone(tracker.current.topic)


class TestTopicReachesResponseConstruction(unittest.TestCase):
    """6. Topic information reaches response construction."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _capture_calls(self):
        calls = []
        original = self.core._construct_fallback_reply

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        patcher = mock.patch.object(self.core, "_construct_fallback_reply", side_effect=spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def test_active_topic_is_passed_to_construct_fallback_reply(self):
        calls = self._capture_calls()
        self.core.process_input("Robots are fun to build for a game.")
        self.assertEqual(len(calls), 1)
        args, _ = calls[0]
        self.assertEqual(len(args), 4)
        active_topic = args[3]
        self.assertIsInstance(active_topic, ActiveTopicResult)
        self.assertIsNotNone(active_topic.topic)
        self.assertEqual(active_topic.topic, self.core.get_active_topic().topic)

    def test_all_four_inputs_stay_separately_accessible(self):
        self.core.process_input("Robots are fun to build for a game.")
        message = "Give me three ideas for it."
        self.core.process_input(message)
        ctx = self.core.last_response_context
        self.assertEqual(ctx["current_input"], message)
        self.assertGreaterEqual(ctx["relevant_context"].selected_count, 1)
        self.assertTrue(ctx["resolved_reference"].has_reference)
        self.assertEqual(ctx["active_topic"].topic, self.core.get_active_topic().topic)
        self.assertIsNotNone(ctx["active_topic"].topic)

    def test_direct_call_without_topic_defaults_to_the_tracker(self):
        message = "Give me three ideas for it."
        relevant = select_relevant_turns(message, [turn(ROBOT)])
        self.core._construct_fallback_reply(message, relevant)
        self.assertIs(self.core.last_response_context["active_topic"], self.core.topic_tracker.current)

    def test_topic_moves_across_a_real_conversation(self):
        self.core.process_input("Robots are fun to build for a game.")
        first = self.core.get_active_topic().topic
        self.core.process_input("By the way, how do I make a Python list?")
        self.assertEqual(self.core.get_active_topic().topic, "python list")
        self.assertNotEqual(first, "python list")

    def test_reset_context_clears_topic(self):
        self.core.process_input("Robots are fun to build for a game.")
        self.core.reset_context()
        self.assertIsNone(self.core.get_active_topic().topic)


class TestOriginalInputRemainsUnchanged(unittest.TestCase):
    """7. Original user input remains unchanged."""

    def test_tracker_does_not_alter_message_or_inputs(self):
        message = "By the way, how do I make a Python list?"
        turns = [turn(ROBOT)]
        relevant = select_relevant_turns(message, turns)
        resolved = resolve_conversational_reference(message, relevant)
        relevant_before = copy.deepcopy(relevant.to_dict())
        resolved_before = resolved.to_dict()
        tracker = ActiveTopicTracker()
        tracker.update(message, relevant, resolved)
        self.assertEqual(message, "By the way, how do I make a Python list?")
        self.assertEqual(relevant.to_dict(), relevant_before)
        self.assertEqual(resolved.to_dict(), resolved_before)

    def test_core_passes_the_verbatim_input_to_response_construction(self):
        core, tmpdir = _make_core()
        self.addCleanup(tmpdir.cleanup)
        message = "Give me three ideas for it."
        core.process_input(message)
        self.assertEqual(core.last_response_context["current_input"], message)
        self.assertEqual(core.get_recent_turns()[-1]["user"], message)


class TestExistingConversationBehaviorRemainsCompatible(unittest.TestCase):
    """8. Existing conversation/context behavior is unchanged."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_unrelated_message_still_gets_the_plain_fallback(self):
        self.assertEqual(self.core.process_input("Xyzzy plugh?"), OLD_FALLBACK)

    def test_command_with_reference_reply_is_unchanged(self):
        self.core.process_input("I am building a voice effects app.")
        reply = self.core.process_input("Give me three ideas for it.")
        self.assertIn('I think "it" refers to what you said earlier: "I am building a voice effects app."', reply)

    def test_topic_tracking_does_not_change_reply_text(self):
        first = self.core.process_input("Xyzzy plugh?")
        self.assertEqual(first, OLD_FALLBACK)
        self.assertEqual(self.core.process_input("Xyzzy plugh?"), OLD_FALLBACK)

    def test_skill_matched_replies_do_not_move_the_topic(self):
        self.core.process_input("Robots are fun to build for a game.")
        before = self.core.get_active_topic().topic
        self.core.skills.find_matching_skill = lambda text: {"response": "canned"}
        self.assertEqual(self.core.process_input("hello there"), "canned")
        self.assertEqual(self.core.get_active_topic().topic, before)


if __name__ == "__main__":
    unittest.main()
