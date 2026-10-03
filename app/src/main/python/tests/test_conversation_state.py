"""
Tests for Prompt 405 - Lightweight Conversation State.

Covers context/conversation_state.py (the compact, bounded state kept
next to ConversationContext / ActiveTopicTracker), its wiring in
core/core.py, and how the relevant part of it reaches the existing
inference-request path (language_intelligence/local_model_mapping.py:
build_inference_request, reusing Prompt 403's selection and Prompt 404's
size control). Deterministic; no model of any kind is involved.

Run directly:
    python -m unittest tests.test_conversation_state -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context.conversation_state import (
    ConversationState, select_relevant_state, format_state_text,
    DEFAULT_MAX_BACKGROUND_TOPICS, DEFAULT_MAX_PREFERENCES, DEFAULT_MAX_UNRESOLVED,
    MAX_KEY_TERMS, MAX_REFERENCE_TERMS, MAX_PREFERENCE_CHARS,
)
from context.active_topic import ActiveTopicResult
from context.message_reference_resolution import ResolvedReference
from context.relevance import RelevantContextResult
from core.core import Core
from understanding.engine import UnderstandingEngine
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_understanding_result import LanguageUnderstandingResult
from language_intelligence.inference import ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT
from language_intelligence.local_model_mapping import build_inference_request

OLD_FALLBACK = (
    "I don't have enough information to answer that yet. "
    "You can teach me using AEL, for example:\n"
    "TEACH sun IS a star at the center of the solar system\n"
    "or ask what I already know with: ASK sun"
)
ROBOT = "I am building a mobile game about a robot."
PYTHON = "also, how do I sort a Python list?"
GARDEN = "by the way, how often should I water tomatoes in the garden?"
PIANO = "by the way, which piano scales should beginners practice?"


def _topic(text):
    return ActiveTopicResult(text, "current_input", 0.7, True, None, "test")


def _core():
    tmpdir = tempfile.TemporaryDirectory()
    core = Core(
        memory_db_path=os.path.join(tmpdir.name, "test_memory.sqlite3"),
        skill_definitions_dir=os.path.join(tmpdir.name, "skills"),
    )
    return core, tmpdir


def _understanding(text, state=None, relevant_context=None):
    result = DeterministicFallbackBackend(UnderstandingEngine()).understand(
        text, relevant_context=relevant_context)
    result.conversation_state = state
    return result


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def say(self, *messages):
        for message in messages:
            self.core.process_input(message)
        return self.core.conversation_state.to_dict()

    def all_topics(self, state):
        topics = [state["topic"]["topic"]] if state["topic"] else []
        return topics + [r["topic"] for r in state["background_topics"]]


class TestTopicStateSurvivesLaterTurns(CoreTestCase):
    """1. important topic state survives later turns"""

    def test_topic_is_kept_while_the_conversation_continues(self):
        state = self.say(ROBOT, "What about the boss?", "How should the boss attack?")
        self.assertEqual(state["topic"]["topic"], "robot game mobile")
        self.assertIn("boss", state["topic"]["terms"])

    def test_earlier_topic_survives_after_unrelated_topics_replace_it_in_the_tracker(self):
        state = self.say(ROBOT, PYTHON, GARDEN)
        # The tracker only knows the latest topic ...
        self.assertNotEqual(self.core.topic_tracker.topic, "robot game mobile")
        # ... the compact state still holds the earlier one.
        self.assertIn("robot game mobile", self.all_topics(state))

    def test_earlier_topic_returns_to_active_with_its_words_when_the_conversation_returns(self):
        state = ConversationState()
        state.update("a", _topic("robot game"), type("T", (), {"terms": ["robot", "game", "boss"]})())
        state.update("b", _topic("python list"))
        state.update("c", _topic("robot game"), type("T", (), {"terms": ["robot", "game"]})())
        snapshot = state.to_dict()
        self.assertEqual(snapshot["topic"]["topic"], "robot game")
        self.assertIn("boss", snapshot["topic"]["terms"])  # words of the earlier stretch kept
        self.assertEqual([r["topic"] for r in snapshot["background_topics"]], ["python list"])


class TestRelevantReferencesRemainAvailable(unittest.TestCase):
    """2. relevant references remain available"""

    def test_resolved_reference_target_is_kept_as_words_not_as_the_message(self):
        state = ConversationState()
        state.update("I am building a robot game.", _topic("robot game"))
        ref = ResolvedReference(True, "it", "I am building a robot game.", 0.9, False, "x")
        state.update("How big should it be?", _topic("robot game"), None, ref)
        self.assertEqual(state.to_dict()["topic"]["reference_terms"], ["robot", "game"])

    def test_unresolved_reference_is_kept_and_reaches_a_message_that_uses_a_reference(self):
        state = ConversationState()
        state.update("I am building a robot game.", _topic("robot game"))
        ambiguous = ResolvedReference(True, "it", None, 0.0, True, "insufficient_margin")
        state.update("Make it bigger.", _topic("robot game"), None, ambiguous)
        snapshot = state.to_dict()
        self.assertEqual(snapshot["unresolved_references"],
                         [{"reference": "it", "topic": "robot game"}])
        self.assertEqual(
            select_relevant_state(snapshot, "Is that ready?")["unresolved_references"],
            snapshot["unresolved_references"])

    def test_unresolved_reference_is_not_selected_for_a_message_without_a_reference(self):
        state = ConversationState()
        state.update("x", _topic("robot game"), None,
                     ResolvedReference(True, "it", None, 0.0, False, "no_relevant_context"))
        selected = select_relevant_state(state.to_dict(), "Tell me about tomatoes.")
        self.assertEqual(selected["unresolved_references"], [])


class TestUnrelatedMessagesDoNotReplaceUsefulState(CoreTestCase):
    """3. unrelated messages do not unnecessarily replace useful state"""

    def test_message_without_meaningful_words_changes_nothing(self):
        before = self.say(ROBOT, "I prefer short answers.")
        after = self.say("Okay.")
        before.pop("turn"), after.pop("turn")
        self.assertEqual(before, after)

    def test_unrelated_topic_demotes_the_old_topic_instead_of_deleting_it(self):
        state = self.say(ROBOT, PYTHON)
        self.assertEqual([r["topic"] for r in state["background_topics"]], ["robot game mobile"])

    def test_preferences_survive_unrelated_topic_changes(self):
        state = self.say("I prefer short answers.", ROBOT, PYTHON, GARDEN, PIANO)
        self.assertEqual([p["text"] for p in state["preferences"]], ["prefers short answers"])

    def test_preference_statement_does_not_displace_the_topic_or_open_a_reference(self):
        state = self.say(ROBOT, "Keep it brief please.")
        self.assertEqual(state["topic"]["topic"], "robot game mobile")
        self.assertEqual(state["unresolved_references"], [])

    def test_a_question_is_not_taken_as_a_preference(self):
        self.assertEqual(self.say("What do I prefer?")["preferences"], [])


class TestObsoleteStateIsRemovedOrUpdated(unittest.TestCase):
    """4. obsolete state can be removed or updated"""

    def test_newer_preference_of_the_same_kind_replaces_the_older_one(self):
        state = ConversationState()
        state.update("Keep it short.")
        state.update("Please explain in detail.")
        self.assertEqual(state.to_dict()["preferences"],
                         [{"key": "response_length", "text": "prefers detailed answers"}])

    def test_no_longer_prefer_removes_the_preference(self):
        state = ConversationState()
        state.update("I prefer dark mode.")
        self.assertEqual(len(state.to_dict()["preferences"]), 1)
        state.update("I no longer prefer dark mode.")
        self.assertEqual(state.to_dict()["preferences"], [])

    def test_untouched_background_topic_ages_out(self):
        state = ConversationState(max_age=3)
        state.update("a", _topic("robot game"))
        state.update("b", _topic("python list"))
        self.assertEqual([r["topic"] for r in state.to_dict()["background_topics"]], ["robot game"])
        for _ in range(3):
            state.update("c", _topic("python list"))
        self.assertEqual(state.to_dict()["background_topics"], [])
        self.assertEqual(state.to_dict()["topic"]["topic"], "python list")

    def test_unresolved_reference_is_closed_when_it_later_resolves(self):
        state = ConversationState()
        state.update("a", _topic("robot game"), None,
                     ResolvedReference(True, "it", None, 0.0, True, "insufficient_margin"))
        self.assertEqual(len(state.to_dict()["unresolved_references"]), 1)
        state.update("b", _topic("robot game"), None,
                     ResolvedReference(True, "it", "robot game", 0.9, False, "x"))
        self.assertEqual(state.to_dict()["unresolved_references"], [])

    def test_unresolved_reference_ages_out(self):
        state = ConversationState(max_age=2)
        state.update("a", _topic("robot game"), None,
                     ResolvedReference(True, "it", None, 0.0, False, "no_relevant_context"))
        for _ in range(2):
            state.update("b", _topic("robot game"))
        self.assertEqual(state.to_dict()["unresolved_references"], [])

    def test_reset_clears_everything(self):
        state = ConversationState()
        state.update("I prefer tea.", _topic("robot game"))
        state.reset()
        self.assertEqual(state.to_dict(), ConversationState().to_dict())


class TestStateRemainsBounded(unittest.TestCase):
    """5. state remains bounded"""

    def test_every_collection_and_field_stays_within_its_limit(self):
        state = ConversationState()
        for i in range(300):
            terms = [f"word{i}a", f"word{i}b", f"word{i}c"]
            state.update(f"I prefer thing{i} " + "very long " * 30)
            state.update(
                "x", _topic(" ".join(terms)),
                type("T", (), {"terms": [f"extra{i}{j}" for j in range(30)]})(),
                ResolvedReference(True, f"ref{i}" * 30, None, 0.0, False, "no_relevant_context"))
            state.update(f"message {i}", _topic(" ".join(terms)),
                         type("T", (), {"terms": [f"extra{i}{j}" for j in range(30)]})(),
                         ResolvedReference(True, f"ref{i}", None, 0.0, False, "no_relevant_context"))
        snapshot = state.to_dict()
        self.assertLessEqual(len(snapshot["background_topics"]), DEFAULT_MAX_BACKGROUND_TOPICS)
        self.assertLessEqual(len(snapshot["preferences"]), DEFAULT_MAX_PREFERENCES)
        self.assertLessEqual(len(snapshot["unresolved_references"]), DEFAULT_MAX_UNRESOLVED)
        for record in [snapshot["topic"]] + snapshot["background_topics"]:
            self.assertLessEqual(len(record["terms"]), MAX_KEY_TERMS)
            self.assertLessEqual(len(record["reference_terms"]), MAX_REFERENCE_TERMS)
        for pref in snapshot["preferences"]:
            self.assertLessEqual(len(pref["text"]), MAX_PREFERENCE_CHARS)
        self.assertLess(len(json.dumps(snapshot)), 2500)  # independent of the 600 messages seen

    def test_size_does_not_grow_with_conversation_length(self):
        core, tmpdir = _core()
        try:
            sizes = []
            for i in range(60):
                core.process_input(f"I am studying subject{i} and unique{i} material today")
                sizes.append(len(json.dumps(core.conversation_state.to_dict())))
            self.assertLess(max(sizes[30:]), max(sizes[:30]) * 1.5)
            self.assertLess(max(sizes), 2500)
        finally:
            tmpdir.cleanup()

    def test_invalid_limits_are_rejected(self):
        for bad in (0, -1, None, True):
            with self.assertRaises(ValueError):
                ConversationState(max_age=bad)


class TestStateDoesNotDuplicateMessageHistory(CoreTestCase):
    """6. conversation state does not duplicate full message history"""

    def test_no_message_text_is_stored(self):
        messages = [
            "I am building a mobile game about a robot that collects crystals in caves.",
            "What about the boss guarding the crystals and the cave entrance?",
            "I prefer short answers over long ones.",
            "How do I make it jump higher than the enemies?",
        ]
        state = self.say(*messages)
        dumped = json.dumps(state)
        for message in messages:
            self.assertNotIn(message, dumped)
            self.assertNotIn(message.rstrip(".?"), dumped)
        stored = []

        def leaves(value):
            if isinstance(value, str):
                stored.append(value)
            elif isinstance(value, dict):
                for v in value.values():
                    leaves(v)
            elif isinstance(value, list):
                for v in value:
                    leaves(v)
        leaves(state)
        self.assertLess(sum(len(t) for t in stored), sum(len(m) for m in messages))

    def test_state_holds_no_assistant_replies(self):
        state = self.say(ROBOT, "Unknown question about robots?")
        self.assertNotIn("I don't have enough information", json.dumps(state))

    def test_history_lives_only_in_the_existing_context(self):
        self.say(ROBOT, PYTHON)
        self.assertEqual(len(self.core.get_recent_turns()), 2)  # turns still where they were
        self.assertFalse(hasattr(self.core.conversation_state, "_turns"))
        self.assertFalse(hasattr(self.core.conversation_state, "get_recent_turns"))


class TestRelevantStateReachesContextSelection(CoreTestCase):
    """7. relevant state can reach context selection"""

    def test_core_attaches_the_state_to_the_language_understanding(self):
        self.say(ROBOT)
        attached = self.core.get_last_language_understanding().conversation_state
        self.assertEqual(attached["topic"]["topic"], "robot game mobile")
        self.assertEqual(attached, self.core.conversation_state.to_dict())

    def test_understand_language_attaches_a_read_only_snapshot(self):
        self.say(ROBOT)
        before = self.core.conversation_state.to_dict()
        understanding = self.core.understand_language("Something completely new here?")
        self.assertEqual(understanding.conversation_state, before)
        self.assertEqual(self.core.conversation_state.to_dict(), before)  # nothing written back

    def test_earlier_topic_reaches_the_model_request_only_when_relevant(self):
        state = self.say(ROBOT, PYTHON, GARDEN)
        relevant = self.core.understand_language("Which weapons suit the robot?")
        request = build_inference_request(relevant, self.core.context, max_context_turns=4)
        system = [m.content for m in request.conversation if m.role == ROLE_SYSTEM]
        self.assertEqual(len(system), 1)
        self.assertIn("earlier topic: robot game mobile", system[0])
        self.assertNotIn("sort python list", system[0])  # not relevant: not sent

        unrelated = self.core.understand_language("Which weapons suit the knight?")
        request = build_inference_request(unrelated, self.core.context, max_context_turns=4)
        system = [m.content for m in request.conversation if m.role == ROLE_SYSTEM]
        self.assertNotIn("robot game mobile", system[0] if system else "")
        self.assertNotIn("sort python list", system[0] if system else "")

    def test_user_input_is_never_altered_by_the_state(self):
        self.say(ROBOT)
        understanding = self.core.understand_language("What about the boss?")
        request = build_inference_request(understanding, self.core.context, max_context_turns=4)
        self.assertEqual(request.user_input, "What about the boss?")

    def test_state_is_a_system_message_placed_before_the_turns(self):
        self.say(ROBOT, "What about the boss?")
        understanding = self.core.understand_language("How should the boss attack?")
        request = build_inference_request(understanding, self.core.context, max_context_turns=4)
        roles = [m.role for m in request.conversation]
        self.assertEqual(roles[0], ROLE_SYSTEM)
        self.assertNotIn(ROLE_SYSTEM, roles[1:])

    def test_selection_and_format_rules(self):
        snapshot = {
            "turn": 5,
            "topic": {"topic": "robot game", "terms": ["robot", "game", "boss"], "reference_terms": []},
            "background_topics": [{"topic": "python list", "terms": ["python", "list"], "reference_terms": []},
                                  {"topic": "tomato garden", "terms": ["tomato", "garden"], "reference_terms": []}],
            "preferences": [{"key": "response_length", "text": "prefers short answers"}],
            "unresolved_references": [{"reference": "it", "topic": "robot game"}],
        }
        selected = select_relevant_state(snapshot, "How do I sort a Python list?")
        self.assertEqual([r["topic"] for r in selected["background_topics"]], ["python list"])
        self.assertEqual(selected["unresolved_references"], [])
        text = format_state_text(selected)
        self.assertIn("topic: robot game", text)
        self.assertIn("preference: prefers short answers", text)
        self.assertIn("earlier topic: python list", text)
        self.assertNotIn("tomato", text)
        self.assertIsNone(select_relevant_state(None, "x"))
        self.assertIsNone(select_relevant_state({"topic": None}, "x"))
        self.assertEqual(format_state_text(None), "")


class TestStateUsesTheExistingSizeControl(unittest.TestCase):
    """7 (cont.). the state is charged against Prompt 404's budget"""

    STATE = {
        "turn": 3,
        "topic": {"topic": "robot game", "terms": ["robot", "game"], "reference_terms": []},
        "background_topics": [], "unresolved_references": [],
        "preferences": [{"key": "response_length", "text": "prefers short answers"}],
    }

    @staticmethod
    def _items(count, size):
        return [{
            "turn": {"user": f"robot game turn {i} " + "x" * size, "assistant": "y" * size},
            "index": i, "rank": count - i, "score": float(count - i),
            "matched_terms": [], "reasons": [], "covers_message_terms": False,
        } for i in range(count)]

    def _request(self, state, **kwargs):
        relevant = RelevantContextResult("m", [], self._items(4, 300))
        return build_inference_request(
            _understanding("What about the robot game?", state, relevant), None,
            max_context_turns=4, **kwargs)

    @staticmethod
    def _chars(request):
        return sum(len(m.content) for m in request.conversation)

    def test_state_and_turns_together_stay_inside_the_ceiling(self):
        request = self._request(self.STATE, max_context_chars=1000)
        self.assertEqual(request.conversation[0].role, ROLE_SYSTEM)
        self.assertLessEqual(self._chars(request), 1000)
        self.assertTrue(any(m.role == ROLE_USER for m in request.conversation))

    def test_state_is_deducted_from_the_turn_budget(self):
        without = self._request(None, max_context_chars=1000)
        with_state = self._request(self.STATE, max_context_chars=1000)
        self.assertLessEqual(self._chars(with_state), 1000)
        self.assertLessEqual(len(with_state.conversation) - 1, len(without.conversation))

    def test_small_model_context_gets_a_smaller_state_slice(self):
        relevant = RelevantContextResult("m", [], self._items(4, 10))
        make = lambda **kw: build_inference_request(
            _understanding("What about the robot game?", self.STATE, relevant), None,
            max_context_turns=4, **kw)
        big = make(context_length=4096, max_output_tokens=256)
        tiny = make(context_length=160, max_output_tokens=64)
        self.assertLess(self._chars(tiny), self._chars(big))
        est = lambda req: sum(len(m.content) for m in req.conversation)
        self.assertLessEqual(est(tiny), (160 - 64) * 3)

    def test_no_room_means_no_state_and_no_turns_but_user_input_is_intact(self):
        request = self._request(self.STATE, context_length=40, max_output_tokens=30)
        self.assertEqual(request.conversation, [])
        self.assertEqual(request.user_input, "What about the robot game?")

    def test_state_is_never_cut_mid_line(self):
        long_state = dict(self.STATE, preferences=[
            {"key": f"k{i}", "text": "prefers " + "word " * 12} for i in range(3)])
        for cap in range(20, 400, 7):
            text = format_state_text(select_relevant_state(long_state, "robot game"), cap)
            self.assertLessEqual(len(text), cap)
            for line in text.splitlines()[1:]:
                self.assertTrue(line.startswith(("topic:", "preference:", "related:")), line)


class TestExistingBehaviourRemainsCompatible(CoreTestCase):
    """8. existing conversation behaviour remains compatible"""

    def test_request_without_a_state_is_exactly_the_previous_request(self):
        items = TestStateUsesTheExistingSizeControl._items(3, 50)
        relevant = RelevantContextResult("m", [], items)
        plain = build_inference_request(_understanding("hello robot", None, relevant), None,
                                        max_context_turns=4)
        self.assertEqual([m.role for m in plain.conversation],
                         [ROLE_USER, ROLE_ASSISTANT] * 3)

    def test_state_with_nothing_relevant_adds_no_message(self):
        empty = ConversationState().to_dict()
        request = build_inference_request(_understanding("hello", empty), None, max_context_turns=4)
        self.assertEqual(request.conversation, [])

    def test_understanding_result_defaults_and_serializes_the_new_field(self):
        result = LanguageUnderstandingResult(
            "x", "english", "x", "unknown", [], [], None, None, 0.5, False, False)
        self.assertIsNone(result.conversation_state)
        self.assertIn("conversation_state", result.to_dict())

    def test_replies_and_topic_tracking_are_unchanged(self):
        reply = self.core.process_input("Tell me about quasars and pulsars.")
        self.assertEqual(reply, OLD_FALLBACK)
        self.assertEqual(self.core.get_active_topic().topic, self.core.topic_tracker.topic)
        self.assertEqual(len(self.core.get_recent_turns()), 1)

    def test_greeting_skill_replies_do_not_touch_the_state(self):
        self.say(ROBOT)
        before = self.core.conversation_state.to_dict()
        self.core.process_input("hello")
        self.assertEqual(self.core.conversation_state.to_dict(), before)

    def test_reset_context_clears_the_state_and_only_short_term_data(self):
        self.say(ROBOT, "I prefer short answers.")
        self.core.reset_context()
        self.assertEqual(self.core.conversation_state.to_dict(),
                         ConversationState().to_dict())

    def test_state_age_limit_follows_the_existing_context_size(self):
        self.assertEqual(self.core.conversation_state.max_age, self.core.context.max_size)


if __name__ == "__main__":
    unittest.main()
