"""
Tests for Prompt 392: conversation reference resolution.

context/message_reference_resolution.py resolves simple references
("it", "that", "the previous idea", "the game I mentioned", ...) in the
*current* user message against the already-selected relevant context
(context/relevance.py, Prompts 389-390), producing a structured
ResolvedReference that Response Construction (core/core.py's
_construct_fallback_reply, Prompt 391) can use - without replacing the
original user message, without rebuilding the NLU system, and without
fabricating a resolution when the signal isn't genuinely there.

Run directly:
    python -m unittest tests.test_message_reference_resolution -v
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
from context.message_reference_resolution import (
    resolve_conversational_reference,
    ResolvedReference,
)
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


class TestBarePronounResolution(unittest.TestCase):
    """1. "it" resolving to a relevant previous subject."""

    def test_it_resolves_to_the_relevant_previous_statement(self):
        relevant = select_relevant_turns(
            "Give me three ideas for it.",
            [turn("I am building a voice effects app.")],
        )
        result = resolve_conversational_reference("Give me three ideas for it.", relevant)
        self.assertIsInstance(result, ResolvedReference)
        self.assertTrue(result.has_reference)
        self.assertEqual(result.reference_text, "it")
        self.assertEqual(result.resolved_context, "I am building a voice effects app.")
        self.assertFalse(result.ambiguous)
        self.assertGreater(result.confidence, 0.0)

    def test_end_to_end_command_reply_uses_the_resolved_reference(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("I am building a voice effects app.")
            reply = core.process_input("Give me three ideas for it.")
            self.assertIn('"it" refers to what you said earlier', reply)
            self.assertIn("voice effects app", reply)
        finally:
            tmpdir.cleanup()


class TestDemonstrativeResolution(unittest.TestCase):
    """2. "that" resolving to a previous subject."""

    def test_that_one_resolves_to_the_relevant_previous_statement(self):
        relevant = select_relevant_turns(
            "Tell me more about that one.",
            [turn("My game has a spider boss.")],
        )
        result = resolve_conversational_reference("Tell me more about that one.", relevant)
        self.assertTrue(result.has_reference)
        self.assertEqual(result.reference_text, "that one")
        self.assertEqual(result.resolved_context, "My game has a spider boss.")
        self.assertFalse(result.ambiguous)


class ThePreviousIdeaResolution(unittest.TestCase):
    """3. "the previous idea" resolving correctly."""

    def test_the_previous_idea_resolves_when_context_is_relevant(self):
        # relevance.py (Prompt 390) selects a turn on shared content
        # terms or on its own (smaller) bare-pronoun vocabulary; "the
        # previous idea" carries its own content word ("idea"), which
        # is what makes the earlier turn relevant here in the first
        # place - same mechanism the "game I mentioned" tests below
        # rely on for "game"/"app".
        relevant = select_relevant_turns(
            "Expand on the previous idea please.",
            [turn("Here's an idea: add a robot voice preset.")],
        )
        result = resolve_conversational_reference(
            "Expand on the previous idea please.", relevant
        )
        self.assertTrue(result.has_reference)
        self.assertEqual(result.reference_text, "the previous idea")
        self.assertEqual(
            result.resolved_context, "Here's an idea: add a robot voice preset."
        )
        self.assertFalse(result.ambiguous)


class TestGameIMentionedResolution(unittest.TestCase):
    """4. "the game I mentioned" resolving correctly."""

    def test_the_game_i_mentioned_resolves_to_the_matching_statement(self):
        relevant = select_relevant_turns(
            "Tell me more about the game I mentioned.",
            [turn("My game has a spider boss.")],
        )
        result = resolve_conversational_reference(
            "Tell me more about the game I mentioned.", relevant
        )
        self.assertTrue(result.has_reference)
        self.assertEqual(result.reference_text, "the game i mentioned")
        self.assertEqual(result.resolved_context, "My game has a spider boss.")
        self.assertFalse(result.ambiguous)

    def test_the_app_i_mentioned_variant_also_resolves(self):
        relevant = select_relevant_turns(
            "Give me the app I mentioned's next feature.",
            [turn("I am building a voice effects app.")],
        )
        result = resolve_conversational_reference(
            "Give me the app I mentioned's next feature.", relevant
        )
        self.assertTrue(result.has_reference)
        self.assertEqual(result.resolved_context, "I am building a voice effects app.")


class TestNoReferenceLeavesMessageUnchanged(unittest.TestCase):
    """5. A message without references remaining unchanged."""

    def test_no_reference_phrase_gives_has_reference_false(self):
        relevant = select_relevant_turns(
            "Give me three ideas for a marketing plan.",
            [turn("I am building a voice effects app.")],
        )
        result = resolve_conversational_reference(
            "Give me three ideas for a marketing plan.", relevant
        )
        self.assertFalse(result.has_reference)
        self.assertIsNone(result.reference_text)
        self.assertIsNone(result.resolved_context)
        self.assertFalse(result.ambiguous)

    def test_original_user_input_is_never_replaced_when_no_reference(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("I am building a voice effects app.")
            reply = core.process_input("Give me three ideas for a marketing plan.")
            # No reference -> normal (unmodified) fallback flow.
            self.assertEqual(reply, OLD_FALLBACK)
        finally:
            tmpdir.cleanup()


class TestMissingContextProducesNoFabrication(unittest.TestCase):
    """6. Missing context producing no fabricated resolution."""

    def test_reference_with_no_selected_context_is_not_fabricated(self):
        relevant = select_relevant_turns("Give me three ideas for it.", [])
        result = resolve_conversational_reference("Give me three ideas for it.", relevant)
        self.assertTrue(result.has_reference)
        self.assertIsNone(result.resolved_context)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.confidence, 0.0)

    def test_none_relevant_context_is_handled_without_raising(self):
        result = resolve_conversational_reference("Give me three ideas for it.", None)
        self.assertTrue(result.has_reference)
        self.assertIsNone(result.resolved_context)


class TestAmbiguousContextIsMarkedAmbiguous(unittest.TestCase):
    """7. Ambiguous context being marked ambiguous."""

    def test_two_equally_relevant_candidates_stay_ambiguous(self):
        relevant = select_relevant_turns(
            "Tell me more about it.",
            [
                turn("I am building a voice app."),
                turn("I am building a drawing app."),
            ],
        )
        # Force a tie by hand: two selected items with identical scores.
        if len(relevant.selected) < 2:
            # Fall back to constructing the tie directly if the
            # selector itself only ever returns one candidate for a
            # bare pronoun (see relevance.py) - the resolver must still
            # treat an explicit tie as ambiguous.
            relevant.selected = [
                {
                    "turn": {"user": "I am building a voice app.", "assistant": "Okay."},
                    "index": 0, "rank": 1, "score": 1.0,
                    "matched_terms": [], "reasons": ["reference:it"],
                    "covers_message_terms": False,
                },
                {
                    "turn": {"user": "I am building a drawing app.", "assistant": "Okay."},
                    "index": 1, "rank": 1, "score": 1.0,
                    "matched_terms": [], "reasons": ["reference:it"],
                    "covers_message_terms": False,
                },
            ]
        result = resolve_conversational_reference("Tell me more about it.", relevant)
        self.assertTrue(result.has_reference)
        self.assertTrue(result.ambiguous)
        self.assertIsNone(result.resolved_context)


class TestResolvedReferencePassedIntoResponseConstruction(unittest.TestCase):
    """8. Resolved context being passed into response construction."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_construct_fallback_reply_consumes_the_passed_in_resolution(self):
        message = "Give me three ideas for it."
        relevant = select_relevant_turns(message, [turn("I am building a voice effects app.")])
        resolved = resolve_conversational_reference(message, relevant)
        reply = self.core._construct_fallback_reply(message, relevant, resolved)
        self.assertIn("voice effects app", reply)

    def test_original_input_and_resolved_context_are_both_available(self):
        # The response-construction call keeps current_input and
        # resolved_reference as two distinct arguments - the original
        # message is never overwritten by the resolution.
        message = "Give me three ideas for it."
        relevant = select_relevant_turns(message, [turn("I am building a voice effects app.")])
        resolved = resolve_conversational_reference(message, relevant)
        reply = self.core._construct_fallback_reply(message, relevant, resolved)
        self.assertEqual(resolved.resolved_context, "I am building a voice effects app.")
        self.assertIn("voice effects app", reply)
        # And Core.resolve_reference() (the public entry point) returns
        # the same structured result end to end.
        self.assertEqual(
            self.core.resolve_reference(message, relevant).to_dict(), resolved.to_dict()
        )

    def test_resolve_reference_falls_back_to_computing_relevant_context(self):
        self.core.process_input("I am building a voice effects app.")
        resolved = self.core.resolve_reference("Give me three ideas for it.")
        self.assertTrue(resolved.has_reference)
        self.assertEqual(resolved.resolved_context, "I am building a voice effects app.")


class TestExistingConversationTestsRemainCompatible(unittest.TestCase):
    """9. Existing conversation tests remaining compatible - the new
    resolution path never fires for questions or statements, which
    keep exactly their pre-392 behavior (see core/core.py's
    _construct_fallback_reply for why it's scoped to commands only)."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_question_with_a_reference_still_uses_only_the_strict_recall(self):
        self.core.process_input("I am building it for Android.")
        reply = self.core.process_input("What am I building it for?")
        self.assertIn('you said: "I am building it for Android."', reply)
        self.assertNotIn("refers to what you said earlier", reply)

    def test_repeated_statement_is_still_never_answered_from_context(self):
        self.core.process_input("I am building it for Android.")
        self.assertEqual(
            self.core.process_input("I am building it for Android."), OLD_FALLBACK
        )

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

    def test_command_with_no_relevant_history_is_unaffected(self):
        self.assertEqual(self.core.process_input("Give me three ideas for it."), OLD_FALLBACK)


if __name__ == "__main__":
    unittest.main()
