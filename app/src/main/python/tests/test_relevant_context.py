"""
Tests for Prompt 390: relevant conversation context.

context/relevance.py picks, from the bounded recent turns kept by
ConversationContext, those that bear on the current message; Core exposes
that as get_relevant_context() and uses it on the conversation path's
final fallback, where Response Construction (Core._construct_fallback_reply,
Prompt 391) receives it and Core._recall_from_relevant_context consumes it.
These tests check the actual turns selected, their order and their scores -
not merely that the functions run.

Run directly:
    python -m unittest tests.test_relevant_context -v
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

from context.relevance import select_relevant_turns, RelevantContextResult
from core.core import Core

# Exactly what Core replied before Prompt 390 when nothing could answer.
OLD_FALLBACK = (
    "I don't have enough information to answer that yet. "
    "You can teach me using AEL, for example:\n"
    "TEACH sun IS a star at the center of the solar system\n"
    "or ask what I already know with: ASK sun"
)


def turn(user, assistant="Okay."):
    return {"user": user, "assistant": assistant}


def users(result):
    return [item["turn"]["user"] for item in result.selected]


def _make_core(**kwargs):
    tmpdir = tempfile.TemporaryDirectory()
    core = Core(
        memory_db_path=os.path.join(tmpdir.name, "test_memory.sqlite3"),
        skill_definitions_dir=os.path.join(tmpdir.name, "skills"),
        **kwargs,
    )
    return core, tmpdir


# ----------------------------------------------------------------------
# The selector on its own
# ----------------------------------------------------------------------
class TestSelectsRelevantTurns(unittest.TestCase):
    def test_relevant_turn_is_selected(self):
        game = turn("My game is called Echo Shift.", "Got it.")
        android = turn("I am building it for Android.", "Sounds good.")
        result = select_relevant_turns("What is my game called?", [game, android])

        self.assertIsInstance(result, RelevantContextResult)
        self.assertEqual(result.selected_count, 1)
        item = result.selected[0]
        self.assertEqual(item["turn"], game)  # both sides of the turn come back
        self.assertEqual(item["index"], 0)
        self.assertEqual(item["matched_terms"], ["game", "called"])
        self.assertEqual(item["score"], 2.0)
        self.assertEqual(item["reasons"], ["shared_terms:game,called"])
        self.assertEqual(item["rank"], 1)

    def test_unrelated_turn_is_excluded(self):
        result = select_relevant_turns(
            "What is my game called?",
            [turn("My game is called Echo Shift."), turn("I am building it for Android.")],
        )
        self.assertNotIn("I am building it for Android.", users(result))

    def test_python_turn_beats_java_turn(self):
        python = turn("Python is a programming language.", "Yes.")
        java = turn("I also use Java.", "Okay.")
        result = select_relevant_turns("What is Python?", [python, java])
        self.assertEqual(users(result), ["Python is a programming language."])
        self.assertEqual(result.selected_count, 1)

    def test_rank_reflects_relevance_while_selection_stays_chronological(self):
        java = turn("Java is verbose.")
        python = turn("Python is a great programming language.")
        result = select_relevant_turns(
            "Python or Java: which is a programming language?", [java, python]
        )
        # Chronological order: Java came first...
        self.assertEqual(users(result), ["Java is verbose.", "Python is a great programming language."])
        # ...but Python is the more relevant of the two.
        by_user = {item["turn"]["user"]: item for item in result.selected}
        self.assertEqual(by_user["Python is a great programming language."]["rank"], 1)
        self.assertEqual(by_user["Java is verbose."]["rank"], 2)
        self.assertGreater(
            by_user["Python is a great programming language."]["score"],
            by_user["Java is verbose."]["score"],
        )

    def test_multiple_relevant_turns_keep_chronological_order(self):
        turns = [
            turn("I like Python for scripts."),
            turn("The weather is nice."),
            turn("Python has a simple syntax and a big library."),
            turn("Lunch was good."),
            turn("Python again."),
        ]
        result = select_relevant_turns("Tell me about Python syntax", turns)
        self.assertEqual(
            users(result),
            ["I like Python for scripts.",
             "Python has a simple syntax and a big library.",
             "Python again."],
        )
        self.assertEqual([item["index"] for item in result.selected], [0, 2, 4])
        # The best-scoring turn (index 2, shares "syntax" too) is not first
        # in the list - order follows the conversation, not the score.
        self.assertEqual(result.selected[1]["rank"], 1)

    def test_equal_scores_rank_the_more_recent_turn_first(self):
        result = select_relevant_turns(
            "What is Python?", [turn("Python is old."), turn("Python is popular.")]
        )
        ranks = {item["turn"]["user"]: item["rank"] for item in result.selected}
        self.assertEqual(ranks, {"Python is popular.": 1, "Python is old.": 2})


class TestEmptyAndUnrelated(unittest.TestCase):
    def test_empty_context_gives_empty_selection(self):
        for empty in ([], None):
            result = select_relevant_turns("What is Python?", empty)
            self.assertEqual(result.selected, [])
            self.assertEqual(result.selected_count, 0)
        self.assertEqual(result.message_terms, ["python"])

    def test_empty_user_input_gives_empty_selection(self):
        turns = [turn("Python is a programming language.")]
        for blank in ("", "   ", "\n\t", None):
            result = select_relevant_turns(blank, turns)
            self.assertEqual(result.selected, [])
            self.assertEqual(result.selected_count, 0)
            self.assertEqual(result.message_terms, [])

    def test_nothing_relevant_returns_empty_not_unrelated_context(self):
        turns = [turn("I am building it for Android."), turn("Lunch was good.")]
        result = select_relevant_turns("What is Python?", turns)
        self.assertEqual(result.selected, [])
        self.assertEqual(result.selected_count, 0)

    def test_only_stopwords_selects_nothing(self):
        result = select_relevant_turns("What is the?", [turn("What is the plan?")])
        self.assertEqual(result.selected_count, 0)

    def test_assistant_text_does_not_make_a_turn_relevant(self):
        # Core's fallback reply itself mentions "sun" - that must not make
        # an unrelated turn look relevant to a question about the sun.
        boilerplate = turn("I am building it for Android.", OLD_FALLBACK)
        result = select_relevant_turns("What is the sun?", [boilerplate])
        self.assertEqual(result.selected_count, 0)

    def test_malformed_turns_are_tolerated(self):
        result = select_relevant_turns(
            "What is Python?", [None, {}, {"user": None}, turn("Python is fun.")]
        )
        self.assertEqual(users(result), ["Python is fun."])
        self.assertEqual(result.selected[0]["index"], 3)


class TestNamesAndReferences(unittest.TestCase):
    def test_explicit_name_improves_relevance(self):
        turns = [turn("Rust is popular."), turn("I like fast cars.")]
        named = select_relevant_turns("Is Rust fast?", turns)
        plain = select_relevant_turns("is rust fast?", turns)

        def score_of(result, text):
            return next(i["score"] for i in result.selected if i["turn"]["user"] == text)

        # Same words matched either way; only the capitalized "Rust" is a name.
        self.assertGreater(score_of(named, "Rust is popular."), score_of(plain, "Rust is popular."))
        self.assertIn("shared_name:rust", named.selected[0]["reasons"])
        self.assertNotIn("shared_name:rust", plain.selected[0]["reasons"])
        # ...and it lifts the name-matching turn above the plain-word one.
        ranks = {i["turn"]["user"]: i["rank"] for i in named.selected}
        self.assertEqual(ranks["Rust is popular."], 1)
        self.assertEqual(ranks["I like fast cars."], 2)

    def test_question_opener_is_not_mistaken_for_a_name(self):
        result = select_relevant_turns("What is Python?", [turn("What time is it?")])
        self.assertEqual(result.selected_count, 0)

    def test_reference_word_selects_the_most_recent_turn_only(self):
        turns = [turn("Python is a programming language."), turn("Lunch was good."), turn("It rained.")]
        result = select_relevant_turns("What does it use?", turns)
        self.assertEqual(users(result), ["It rained."])
        self.assertEqual(result.selected[0]["reasons"], ["reference:it"])

    def test_no_reference_word_means_last_turn_is_not_selected_for_free(self):
        turns = [turn("Python is a programming language."), turn("Lunch was good.")]
        result = select_relevant_turns("What is Python?", turns)
        self.assertEqual(users(result), ["Python is a programming language."])

    def test_reference_alone_never_counts_as_covering_the_message(self):
        result = select_relevant_turns("What is it?", [turn("Lunch was good.")])
        self.assertEqual(result.selected_count, 1)
        self.assertFalse(result.selected[0]["covers_message_terms"])

    def test_covers_message_terms_needs_every_word(self):
        turns = [turn("My game is called Echo Shift.")]
        self.assertTrue(select_relevant_turns("What is my game called?", turns)
                        .selected[0]["covers_message_terms"])
        partial = select_relevant_turns("What is my dog called?", turns)
        self.assertEqual(partial.selected[0]["matched_terms"], ["called"])
        self.assertFalse(partial.selected[0]["covers_message_terms"])


class TestResultShape(unittest.TestCase):
    def test_to_dict_is_json_shaped(self):
        result = select_relevant_turns("What is Python?", [turn("Python is fun.", "Yes.")])
        data = result.to_dict()
        json.dumps(data)  # must be serializable as-is
        self.assertEqual(data["message"], "What is Python?")
        self.assertEqual(data["message_terms"], ["python"])
        self.assertEqual(data["selected_count"], 1)
        self.assertEqual(data["selected"][0]["turn"], {"user": "Python is fun.", "assistant": "Yes."})

    def test_input_turns_are_not_mutated_and_results_are_copies(self):
        original = [turn("Python is fun.")]
        result = select_relevant_turns("What is Python?", original)
        result.selected[0]["turn"]["user"] = "tampered"
        self.assertEqual(original, [{"user": "Python is fun.", "assistant": "Okay."}])


# ----------------------------------------------------------------------
# Through Core, with the real recent-turn window
# ----------------------------------------------------------------------
class TestCoreSelectsFromRealConversation(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_empty_conversation(self):
        result = self.core.get_relevant_context("What is my game called?")
        self.assertEqual(result.selected, [])
        self.assertEqual(result.selected_count, 0)

    def test_echo_shift_conversation(self):
        first_reply = self.core.process_input("My game is called Echo Shift.")
        self.core.process_input("I am building it for Android.")

        result = self.core.get_relevant_context("What is my game called?")
        self.assertEqual(users(result), ["My game is called Echo Shift."])
        self.assertEqual(result.selected[0]["turn"]["assistant"], first_reply)
        self.assertEqual(result.selected_count, 1)

        # The existing conversation path still answers it as before.
        self.assertIn("Echo Shift", self.core.process_input("What is my game called?"))

    def test_python_java_conversation(self):
        self.core.process_input("Python is a programming language.")
        self.core.process_input("I also use Java.")
        result = self.core.get_relevant_context("What is Python?")
        self.assertEqual(users(result), ["Python is a programming language."])
        self.assertEqual(
            self.core.process_input("What is Python?"), "Python is a programming language."
        )

    def test_selection_is_read_only(self):
        self.core.process_input("Python is a programming language.")
        before = self.core.get_recent_turns()
        self.core.get_relevant_context("What is Python?")
        self.assertEqual(self.core.get_recent_turns(), before)

    def test_only_the_bounded_window_is_searched(self):
        core, tmpdir = _make_core(context_max_turns=2)
        try:
            core.process_input("I am building it for Android.")
            core.process_input("hello")
            core.process_input("hello there")
            # The Android turn has been evicted from the 2-turn window.
            self.assertEqual(core.get_relevant_context("What am I building?").selected, [])
        finally:
            tmpdir.cleanup()


class TestConversationPathUsesRelevantContext(unittest.TestCase):
    """Core._handle_conversation's final fallback quotes back the user's
    own relevant statement - and only when it really is relevant."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_question_covered_by_an_earlier_statement_quotes_it(self):
        self.core.process_input("I am building it for Android.")
        reply = self.core.process_input("What am I building it for?")
        self.assertEqual(
            reply,
            "I don't have enough information to answer that yet. "
            'Earlier in this conversation you said: "I am building it for Android." '
            "You can teach me using AEL, for example:\n"
            "TEACH sun IS a star at the center of the solar system\n"
            "or ask what I already know with: ASK sun",
        )

    def test_most_recent_of_equally_relevant_statements_wins(self):
        self.core.process_input("I am building it for Android.")
        self.core.process_input("I am building it for Windows.")
        reply = self.core.process_input("What am I building it for?")
        self.assertIn('you said: "I am building it for Windows."', reply)
        self.assertNotIn("Android", reply)

    def test_partially_matching_statement_is_not_quoted(self):
        self.core.process_input("I am building it for Android.")
        self.assertEqual(self.core.process_input("What is my dog called?"), OLD_FALLBACK)

    def test_unrelated_history_leaves_the_fallback_unchanged(self):
        self.core.process_input("I am building it for Android.")
        self.assertEqual(self.core.process_input("What is glorp?"), OLD_FALLBACK)

    def test_an_earlier_question_is_never_quoted_back(self):
        first = self.core.process_input("What am I building it for?")
        self.assertEqual(first, OLD_FALLBACK)
        self.assertEqual(self.core.process_input("What am I building it for?"), OLD_FALLBACK)

    def test_a_statement_is_never_answered_from_recent_context(self):
        self.core.process_input("I am building it for Android.")
        self.assertEqual(self.core.process_input("I am building it for Android."), OLD_FALLBACK)

    def test_persistent_knowledge_still_takes_priority(self):
        self.core.process_input("Python is a programming language.")
        self.core.process_input("I like Python.")
        self.assertEqual(
            self.core.process_input("What is Python?"), "Python is a programming language."
        )

    def test_recall_writes_nothing_permanent(self):
        self.core.process_input("I am building it for Android.")
        before = self.core.memory.counts()
        reply = self.core.process_input("What am I building it for?")
        self.assertIn("Earlier in this conversation", reply)
        self.assertEqual(self.core.memory.counts(), before)

    def test_reset_context_removes_what_can_be_quoted(self):
        self.core.process_input("I am building it for Android.")
        self.core.reset_context()
        self.assertEqual(self.core.process_input("What am I building it for?"), OLD_FALLBACK)

    def test_evicted_turns_cannot_be_quoted(self):
        core, tmpdir = _make_core(context_max_turns=2)
        try:
            core.process_input("I am building it for Android.")
            core.process_input("hello")
            core.process_input("hello there")
            self.assertEqual(core.process_input("What am I building it for?"), OLD_FALLBACK)
        finally:
            tmpdir.cleanup()


class TestExistingConversationBehaviourUnchanged(unittest.TestCase):
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

    def test_recent_turns_still_recorded(self):
        reply = self.core.process_input("What is glorp?")
        self.assertEqual(
            self.core.get_recent_turns(), [{"user": "What is glorp?", "assistant": reply}]
        )

    def test_follow_up_reference_resolution_still_works(self):
        self.core.process_input("Python is a programming language.")
        self.core.process_input("It uses indentation.")
        self.assertIn("indentation", self.core.process_input("What does Python use?"))


if __name__ == "__main__":
    unittest.main()
