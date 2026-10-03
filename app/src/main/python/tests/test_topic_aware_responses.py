"""
Tests for Prompt 394: topic-aware conversation responses.

Prompt 393 tracked the active topic; here it takes part in Response
Construction. context/topic_awareness.py decides, from the four
separate inputs (original input, relevant context, resolved reference,
active topic), whether a message is clearly a continuation of the
topic; core/core.py's _construct_fallback_reply then shapes the reply
from that decision and records it in
`Core.last_response_context["topic_awareness"]`. The topic is context,
never knowledge: nothing about the topic beyond what the user said is
ever stated.

Run directly:
    python -m unittest tests.test_topic_aware_responses -v
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

from context.active_topic import ActiveTopicResult, ActiveTopicTracker
from context.message_reference_resolution import resolve_conversational_reference
from context.relevance import select_relevant_turns
from context.topic_awareness import assess_topic_awareness, TopicAwareness
from core.core import Core

OLD_FALLBACK = (
    "I don't have enough information to answer that yet. "
    "You can teach me using AEL, for example:\n"
    "TEACH sun IS a star at the center of the solar system\n"
    "or ask what I already know with: ASK sun"
)
ROBOT = "I am building a game about a robot."
VOICE = "I am making a voice effects app."
AWARE_MARKER = "I'm treating this as a follow-up about"
NO_INVENTION = "I don't know more about it than what you've told me"


def turn(user, assistant="Okay."):
    return {"user": user, "assistant": assistant}


def _make_core():
    tmpdir = tempfile.TemporaryDirectory()
    core = Core(
        memory_db_path=os.path.join(tmpdir.name, "test_memory.sqlite3"),
        skill_definitions_dir=os.path.join(tmpdir.name, "skills"),
    )
    return core, tmpdir


def _assess(message, turns, previous_messages=()):
    """Run the real tracker + assessment over `turns` (no Core)."""
    tracker = ActiveTopicTracker()
    for m in previous_messages:
        tracker.update(m)
    relevant = select_relevant_turns(message, turns)
    resolved = resolve_conversational_reference(message, relevant)
    topic = tracker.update(message, relevant, resolved)
    return assess_topic_awareness(message, relevant, resolved, topic)


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def awareness(self):
        return self.core.last_response_context["topic_awareness"]


class TestFollowUpUsesActiveTopic(CoreTestCase):
    """1. A follow-up message uses the active topic."""

    def test_request_for_ideas_without_own_subject_is_topic_aware(self):
        self.core.process_input(ROBOT)
        reply = self.core.process_input("What weapon ideas fit?")
        self.assertTrue(self.awareness().topic_aware)
        self.assertEqual(self.awareness().topic, "robot game")
        self.assertIn(f'{AWARE_MARKER} "robot game"', reply)

    def test_features_question_is_aware_of_the_voice_effects_app(self):
        self.core.process_input(VOICE)
        reply = self.core.process_input("What features should I add?")
        self.assertTrue(self.awareness().topic_aware)
        self.assertIn('"voice effects app"', reply)

    def test_follow_up_sharing_a_word_quotes_the_users_own_statement(self):
        self.core.process_input(ROBOT)
        reply = self.core.process_input("Tell me about the game.")
        self.assertEqual(self.awareness().basis, "shared_terms")
        self.assertEqual(self.awareness().supporting_context, ROBOT)
        self.assertIn(f'What you told me about it: "{ROBOT}"', reply)

    def test_mechanism_is_generic_not_hard_coded(self):
        turns = [turn("I am planning a garden for my balcony.")]
        result = _assess("Tell me about the garden.", turns, ["I am planning a garden for my balcony."])
        self.assertTrue(result.topic_aware)
        self.assertEqual(result.topic, "planning garden balcony")


class TestResolvedReferenceUsesActiveTopic(CoreTestCase):
    """2. A follow-up with a resolved reference uses the active topic."""

    def test_it_resolving_to_the_topic_statement(self):
        self.core.process_input(ROBOT)
        reply = self.core.process_input("Suggest weapon ideas for it.")
        ctx = self.core.last_response_context
        self.assertTrue(ctx["resolved_reference"].has_reference)
        self.assertEqual(ctx["resolved_reference"].resolved_context, ROBOT)
        self.assertTrue(ctx["topic_awareness"].topic_aware)
        self.assertEqual(ctx["topic_awareness"].basis, "resolved_reference")
        self.assertIn('"robot game"', reply)
        self.assertIn(f'"{ROBOT}"', reply)

    def test_quote_is_not_repeated_when_the_reply_already_has_it(self):
        self.core.process_input(VOICE)
        reply = self.core.process_input("Give me three ideas for it.")
        self.assertEqual(reply.count(f'"{VOICE}"'), 1)
        self.assertIn(AWARE_MARKER, reply)


class TestUnrelatedMessageDoesNotUseTopic(CoreTestCase):
    """3. An unrelated message does not incorrectly use the previous topic."""

    def test_new_subject_gets_the_plain_reply(self):
        self.core.process_input(ROBOT)
        reply = self.core.process_input("By the way, how do I make a Python list?")
        self.assertFalse(self.awareness().topic_aware)
        self.assertNotIn("robot", reply)
        self.assertEqual(reply, OLD_FALLBACK)

    def test_ideas_for_a_named_other_subject_is_not_a_follow_up(self):
        self.core.process_input(ROBOT)
        reply = self.core.process_input("Give me ideas for Python.")
        self.assertFalse(self.awareness().topic_aware)
        self.assertEqual(reply, OLD_FALLBACK)

    def test_message_that_introduces_the_topic_is_not_a_follow_up(self):
        reply = self.core.process_input(ROBOT)
        self.assertFalse(self.awareness().topic_aware)
        self.assertEqual(reply, OLD_FALLBACK)

    def test_contentless_message_does_not_force_the_topic(self):
        self.core.process_input(ROBOT)
        reply = self.core.process_input("Okay.")
        self.assertFalse(self.awareness().topic_aware)
        self.assertEqual(reply, OLD_FALLBACK)


class TestMissingActiveTopicPreservesNormalBehavior(CoreTestCase):
    """4. Missing active topic preserves normal behavior."""

    def test_no_topic_no_context(self):
        reply = self.core.process_input("What features should I add?")
        # The message itself creates a topic ("features"), but it is
        # the introducing message, so nothing topic-aware is added.
        self.assertFalse(self.awareness().topic_aware)
        self.assertEqual(reply, OLD_FALLBACK)

    def test_reference_with_nothing_to_refer_to(self):
        reply = self.core.process_input("Give me three ideas for it.")
        self.assertIsNone(self.core.get_active_topic().topic)
        self.assertEqual(self.awareness().reason, "no_active_topic")
        self.assertEqual(reply, OLD_FALLBACK)

    def test_assess_handles_missing_topic_and_inputs(self):
        for topic in (None, ActiveTopicResult(None, None, 0.0, False, None, "no_topic_yet")):
            result = assess_topic_awareness("anything", None, None, topic)
            self.assertIsInstance(result, TopicAwareness)
            self.assertFalse(result.topic_aware)

    def test_direct_call_without_topic_argument_still_works(self):
        message = "Give me three ideas for it."
        relevant = select_relevant_turns(message, [turn(VOICE)])
        reply = self.core._construct_fallback_reply(message, relevant)
        self.assertIn(VOICE, reply)
        self.assertNotIn(AWARE_MARKER, reply)


class TestAmbiguousTopicOrReferenceInventsNothing(CoreTestCase):
    """5. Ambiguous topic/reference does not cause fabricated context."""

    def _tied_relevant(self, message):
        relevant = select_relevant_turns(message, [turn("I like the song."), turn("I like the movie.")])
        relevant.selected = [
            {"turn": turn("I like the song."), "index": 0, "rank": 1, "score": 1.0,
             "matched_terms": [], "reasons": ["reference:it"], "covers_message_terms": False},
            {"turn": turn("I like the movie."), "index": 1, "rank": 1, "score": 1.0,
             "matched_terms": [], "reasons": ["reference:it"], "covers_message_terms": False},
        ]
        return relevant

    def test_ambiguous_reference_is_never_topic_aware(self):
        message = "What features does it need?"
        relevant = self._tied_relevant(message)
        resolved = resolve_conversational_reference(message, relevant)
        self.assertTrue(resolved.ambiguous)
        tracker = ActiveTopicTracker()
        tracker.update(ROBOT)
        topic = tracker.update(message, relevant, resolved)
        result = assess_topic_awareness(message, relevant, resolved, topic)
        self.assertFalse(result.topic_aware)
        self.assertEqual(result.reason, "ambiguous_reference")

    def test_ambiguous_reference_reply_has_no_topic_text(self):
        message = "What features does it need?"
        relevant = self._tied_relevant(message)
        resolved = resolve_conversational_reference(message, relevant)
        self.core.topic_tracker.update(ROBOT)
        reply = self.core._construct_fallback_reply(
            message, relevant, resolved, self.core.get_active_topic()
        )
        self.assertNotIn(AWARE_MARKER, reply)
        self.assertNotIn("robot", reply)
        self.assertEqual(reply, OLD_FALLBACK)

    def test_topic_is_never_treated_as_knowledge(self):
        self.core.process_input(ROBOT)
        reply = self.core.process_input("What weapon ideas fit?")
        self.assertIn(NO_INVENTION, reply)
        for invented in ("sword", "laser", "gun", "mechanic", "story", "graphics"):
            self.assertNotIn(invented, reply.lower())


class TestResponseConstructionPathUsesTopic(CoreTestCase):
    """6. The actual response-construction path receives and uses topic
    information."""

    def test_construct_fallback_reply_receives_the_topic(self):
        self.core.process_input(ROBOT)
        original = self.core._construct_fallback_reply
        calls = []

        def spy(*args, **kwargs):
            calls.append(args)
            return original(*args, **kwargs)

        with mock.patch.object(self.core, "_construct_fallback_reply", side_effect=spy):
            reply = self.core.process_input("What weapon ideas fit?")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "What weapon ideas fit?")
        self.assertEqual(calls[0][3].topic, "robot game")
        self.assertIn(AWARE_MARKER, reply)

    def test_the_topic_changes_the_reply_and_only_the_topic_does(self):
        message = "What weapon ideas fit?"
        relevant = select_relevant_turns(message, [turn(ROBOT)])
        resolved = resolve_conversational_reference(message, relevant)
        with_topic = ActiveTopicResult("robot game", "previous_topic", 0.7, False, "robot game",
                                       "dependent_request_on_topic")
        without_topic = ActiveTopicResult(None, None, 0.0, False, None, "no_topic_yet")
        aware_reply = self.core._construct_fallback_reply(message, relevant, resolved, with_topic)
        plain_reply = self.core._construct_fallback_reply(message, relevant, resolved, without_topic)
        self.assertIn(AWARE_MARKER, aware_reply)
        self.assertEqual(plain_reply, OLD_FALLBACK)
        self.assertTrue(aware_reply.endswith(OLD_FALLBACK.split("yet. ", 1)[1]))

    def test_response_context_keeps_the_four_inputs_separate(self):
        self.core.process_input(ROBOT)
        message = "Suggest weapon ideas for it."
        self.core.process_input(message)
        ctx = self.core.last_response_context
        self.assertEqual(ctx["current_input"], message)
        self.assertGreaterEqual(ctx["relevant_context"].selected_count, 1)
        self.assertEqual(ctx["resolved_reference"].resolved_context, ROBOT)
        self.assertEqual(ctx["active_topic"].topic, "robot game")
        self.assertTrue(ctx["topic_awareness"].topic_aware)
        self.assertEqual(set(ctx["topic_awareness"].to_dict()),
                         {"topic_aware", "topic", "basis", "supporting_context", "reason"})


class TestAssessmentRules(unittest.TestCase):
    """Unit checks of the awareness decision itself."""

    def test_verbatim_repeat_is_not_a_follow_up(self):
        result = _assess(ROBOT, [turn(ROBOT)], [ROBOT])
        self.assertFalse(result.topic_aware)
        self.assertEqual(result.reason, "repeat_of_earlier_message")

    def test_explicit_topic_change_is_not_a_follow_up(self):
        result = _assess("By the way, how do I make a Python list?", [turn(ROBOT)], [ROBOT])
        self.assertFalse(result.topic_aware)

    def test_supporting_context_is_never_a_question(self):
        turns = [turn("Is the game about a robot fun?"), turn(ROBOT)]
        result = _assess("Tell me about the game.", turns, [ROBOT])
        self.assertEqual(result.supporting_context, ROBOT)

    def test_inputs_are_not_mutated(self):
        message = "What weapon ideas fit?"
        relevant = select_relevant_turns(message, [turn(ROBOT)])
        resolved = resolve_conversational_reference(message, relevant)
        before = (relevant.to_dict(), resolved.to_dict())
        tracker = ActiveTopicTracker()
        tracker.update(ROBOT)
        topic = tracker.update(message, relevant, resolved)
        assess_topic_awareness(message, relevant, resolved, topic)
        self.assertEqual((relevant.to_dict(), resolved.to_dict()), before)
        self.assertEqual(message, "What weapon ideas fit?")


class TestExistingConversationBehaviorRemainsCompatible(CoreTestCase):
    """7. Existing conversation behavior remains compatible."""

    def test_repeated_statement_still_gets_plain_fallback(self):
        self.core.process_input("I am building it for Android.")
        self.assertEqual(self.core.process_input("I am building it for Android."), OLD_FALLBACK)

    def test_question_covered_by_earlier_statement_still_only_quotes(self):
        self.core.process_input("I am building it for Android.")
        reply = self.core.process_input("What am I building it for?")
        self.assertNotIn(AWARE_MARKER, reply)

    def test_goal_requests_still_use_the_goal_path(self):
        self.core.process_input(ROBOT)
        reply = self.core.process_input("I want three weapon ideas.")
        self.assertTrue(reply.startswith("[GOAL CREATED]"))

    def test_original_input_is_kept_verbatim(self):
        self.core.process_input(ROBOT)
        message = "What  weapon ideas fit?"
        self.core.process_input(message)
        self.assertEqual(self.core.get_recent_turns()[-1]["user"], self.core.input_system.normalize(message))


if __name__ == "__main__":
    unittest.main()
