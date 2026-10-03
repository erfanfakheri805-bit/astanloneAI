"""
Tests for Prompt 421 - Learned Sentence Pattern Recognition.

`LearnedPatternMatcher` (language_intelligence/learned_pattern_matching.py)
recognizes a message as an instance of a previously learned sentence
pattern (`LanguageLearningStore` items of `item_type=ITEM_TYPE_PATTERN`,
Prompt 416) - deterministically, never guessing a pattern that was not
explicitly taught.

Run directly:
    python -m unittest tests.test_learned_pattern_matching -v
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from language_intelligence.language_learning_store import LanguageLearningStore, ITEM_TYPE_PATTERN
from language_intelligence.learned_pattern_matching import (
    LearnedPatternMatcher, LearnedPatternMatchResult,
    STATUS_MATCHED, STATUS_NOT_FOUND, STATUS_AMBIGUOUS, STATUS_NOT_RESOLVED, ALL_STATUSES,
    REASON_EMPTY_MESSAGE, REASON_NO_PATTERN_MATCHED, REASON_SINGLE_PATTERN_MATCHED,
    REASON_MULTIPLE_PATTERNS_MATCHED, REASON_INDETERMINATE_STRUCTURE,
)


class _MatcherTestCase(unittest.TestCase):
    """A fresh on-disk MemorySystem + LanguageLearningStore (Prompt 416)
    and a LearnedPatternMatcher over it - mirrors _ResolverTestCase in
    test_meaning_resolution.py."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "memory.db")
        self.memory = MemorySystem(db_path)
        self.items = LanguageLearningStore(self.memory)
        self.matcher = LearnedPatternMatcher(self.items)

    def tearDown(self):
        self._tmpdir.cleanup()


class TestExactLearnedPatternMatch(_MatcherTestCase):
    """1. Exact learned pattern match (no variables)."""

    def test_exact_pattern_with_no_variables_matches(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "hello there",
                               meaning={"intent": "greeting"})
        result = self.matcher.match("hello there", language="english")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertTrue(result.matched)
        self.assertEqual(result.reason, REASON_SINGLE_PATTERN_MATCHED)
        self.assertEqual(result.matched_pattern_text, "hello there")
        self.assertEqual(result.meaning, {"intent": "greeting"})
        self.assertIsInstance(result, LearnedPatternMatchResult)

    def test_exact_pattern_is_case_insensitive_for_latin_script(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "Good Morning")
        result = self.matcher.match("good morning", language="english")
        self.assertEqual(result.status, STATUS_MATCHED)

    def test_extra_whitespace_in_message_does_not_prevent_a_match(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "hello there")
        result = self.matcher.match("  hello   there  ", language="english")
        self.assertEqual(result.status, STATUS_MATCHED)


class TestPatternWithOneVariable(_MatcherTestCase):
    """2. Learned pattern with one variable."""

    def test_persian_pattern_with_one_variable_is_recognized(self):
        self.items.learn_item(
            "persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم",
            meaning={"intent": "likes_thing"},
        )
        result = self.matcher.match("من کتاب را دوست دارم", language="persian")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.variables, {"X": "کتاب"})
        self.assertEqual(result.meaning, {"intent": "likes_thing"})

    def test_a_different_known_value_for_the_same_pattern_is_also_recognized(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        result = self.matcher.match("من فیلم را دوست دارم", language="persian")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.variables, {"X": "فیلم"})

    def test_anonymous_placeholder_is_supported(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "___ is a language")
        result = self.matcher.match("Python is a language", language="english")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.variables, {"var_1": "Python"})

    def test_a_multi_word_value_can_fill_one_variable(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        result = self.matcher.match("I love old science fiction movies", language="english")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.variables, {"thing": "old science fiction movies"})


class TestPatternWithMultipleVariables(_MatcherTestCase):
    """3. Learned pattern with multiple variables."""

    def test_two_variables_separated_by_a_literal_are_both_extracted(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{name}} likes {{thing}}")
        result = self.matcher.match("Alice likes tea", language="english")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.variables, {"name": "Alice", "thing": "tea"})

    def test_three_variables_are_all_extracted(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{a}} plus {{b}} equals {{c}}")
        result = self.matcher.match("two plus two equals four", language="english")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.variables, {"a": "two", "b": "two", "c": "four"})


class TestNoMatchingPattern(_MatcherTestCase):
    """4. No matching pattern -> NOT_FOUND."""

    def test_unrelated_message_is_not_found(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        result = self.matcher.match("The weather is nice today", language="english")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_NO_PATTERN_MATCHED)
        self.assertFalse(result.matched)
        self.assertIsNone(result.matched_pattern_id)

    def test_no_learned_patterns_at_all_is_not_found(self):
        result = self.matcher.match("anything at all", language="english")
        self.assertEqual(result.status, STATUS_NOT_FOUND)

    def test_never_invents_a_pattern_that_was_not_taught(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        result = self.matcher.match("I hate broccoli", language="english")
        self.assertEqual(result.status, STATUS_NOT_FOUND)


class TestAmbiguousMultipleMatches(_MatcherTestCase):
    """5. Ambiguous multiple matches -> AMBIGUOUS, nothing collapsed."""

    def test_two_different_learned_patterns_matching_equally_is_ambiguous(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{A}} is a {{B}}")
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "___ is a ___")
        result = self.matcher.match("Python is a language", language="english")
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertEqual(result.reason, REASON_MULTIPLE_PATTERNS_MATCHED)
        self.assertEqual(len(result.candidates), 2)
        self.assertFalse(result.matched)
        self.assertIsNone(result.matched_pattern_id)


class TestLanguageMismatch(_MatcherTestCase):
    """6. Language mismatch - a Persian pattern is never matched against
    an unrelated language."""

    def test_persian_pattern_is_not_matched_when_asking_in_english(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        result = self.matcher.match("I love books", language="english")
        self.assertEqual(result.status, STATUS_NOT_FOUND)

    def test_language_none_searches_every_learned_language(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        result = self.matcher.match("من چای را دوست دارم")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.language, "persian")


class TestLocaleAwareBehavior(_MatcherTestCase):
    """7. Locale-aware behavior when applicable."""

    def test_locale_specific_pattern_is_excluded_for_a_different_locale(self):
        self.items.learn_item(
            "english", ITEM_TYPE_PATTERN, "cheers mate",
            meaning={"locale": "en-GB", "intent": "greeting"},
        )
        result = self.matcher.match("cheers mate", language="english", locale="en-US")
        self.assertEqual(result.status, STATUS_NOT_FOUND)

    def test_locale_specific_pattern_matches_its_own_locale(self):
        self.items.learn_item(
            "english", ITEM_TYPE_PATTERN, "cheers mate",
            meaning={"locale": "en-GB", "intent": "greeting"},
        )
        result = self.matcher.match("cheers mate", language="english", locale="en-GB")
        self.assertEqual(result.status, STATUS_MATCHED)

    def test_locale_agnostic_pattern_matches_any_requested_locale(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "hello there")
        result = self.matcher.match("hello there", language="english", locale="en-US")
        self.assertEqual(result.status, STATUS_MATCHED)

    def test_no_locale_requested_still_matches_a_locale_agnostic_pattern(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "hello there")
        result = self.matcher.match("hello there", language="english")
        self.assertEqual(result.status, STATUS_MATCHED)


class TestExtractedVariablePreservation(_MatcherTestCase):
    """8. Extracted variable values are preserved verbatim."""

    def test_variable_value_is_preserved_exactly_as_typed(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        result = self.matcher.match("I love Old-School Science Fiction", language="english")
        self.assertEqual(result.variables["thing"], "Old-School Science Fiction")

    def test_no_variables_yields_an_empty_dict_not_none(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "hello there")
        result = self.matcher.match("hello there", language="english")
        self.assertEqual(result.variables, {})
        self.assertIsInstance(result.to_dict()["variables"], dict)


class TestAssociatedMeaningPreservation(_MatcherTestCase):
    """9. Associated meaning/intention is preserved, never invented."""

    def test_meaning_is_returned_unchanged(self):
        meaning = {"intent": "likes_thing", "polarity": "positive"}
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}", meaning=meaning)
        result = self.matcher.match("I love tea", language="english")
        self.assertEqual(result.meaning, meaning)

    def test_pattern_with_no_stored_meaning_reports_the_stored_default(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        result = self.matcher.match("I love tea", language="english")
        # learn_item's own default for an unspecified meaning is {} - see
        # language_learning_store.py; never fabricated here.
        self.assertEqual(result.meaning, {})

    def test_unresolved_and_ambiguous_results_never_pick_a_meaning(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{A}} is a {{B}}")
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "___ is a ___")
        result = self.matcher.match("Python is a language", language="english")
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertIsNone(result.meaning)


class TestOriginalMessagePreservation(_MatcherTestCase):
    """10. The original message is preserved verbatim in every result."""

    def test_original_message_is_kept_verbatim_on_a_match(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "hello there")
        raw = "  hello   there  "
        result = self.matcher.match(raw, language="english")
        self.assertEqual(result.original_message, raw)

    def test_original_message_is_kept_verbatim_when_not_found(self):
        raw = "something entirely unrelated"
        result = self.matcher.match(raw, language="english")
        self.assertEqual(result.original_message, raw)


class TestIndeterminateStructure(_MatcherTestCase):
    """The structure is insufficient to determine a match ->
    NOT_RESOLVED: two adjacent variables with no literal boundary
    between them are never split by guessing."""

    def test_adjacent_variables_are_reported_as_not_resolved(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{first}} {{second}} loves cats")
        result = self.matcher.match("Tom Smith loves cats", language="english")
        self.assertEqual(result.status, STATUS_NOT_RESOLVED)
        self.assertEqual(result.reason, REASON_INDETERMINATE_STRUCTURE)
        self.assertEqual(len(result.candidates), 1)
        self.assertFalse(result.matched)


class TestEmptyMessage(_MatcherTestCase):
    """A blank message is never fabricated a match."""

    def test_blank_message_is_not_found(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "hello there")
        result = self.matcher.match("   ", language="english")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_EMPTY_MESSAGE)

    def test_none_message_is_not_found(self):
        result = self.matcher.match(None, language="english")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_EMPTY_MESSAGE)


class TestBoundedMatching(_MatcherTestCase):
    """Matching stays bounded/deterministic even with many patterns."""

    def test_max_patterns_bounds_how_many_are_considered(self):
        for i in range(5):
            self.items.learn_item("english", ITEM_TYPE_PATTERN, f"pattern number {i}")
        result = self.matcher.match("pattern number 3", language="english", max_patterns=2)
        # Only the first 2 (by item_key order) are even read - "pattern
        # number 3" is alphabetically NOT among the first two, so it is
        # correctly not found, and truncation is reported honestly.
        self.assertTrue(result.truncated)

    def test_negative_max_patterns_is_rejected(self):
        with self.assertRaises(ValueError):
            self.matcher.match("hello", max_patterns=-1)

    def test_max_patterns_hard_cap_is_enforced(self):
        result = self.matcher.match("hello", language="english", max_patterns=10 ** 9)
        self.assertLessEqual(result.limits["max_patterns"], 200)


class TestToDictShape(_MatcherTestCase):
    def test_to_dict_has_every_required_field(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "hello there")
        result = self.matcher.match("hello there", language="english")
        as_dict = result.to_dict()
        for field in (
            "original_message", "status", "matched", "matched_pattern_id",
            "matched_pattern_text", "variables", "meaning", "language", "locale",
            "confidence", "source", "candidates", "reason", "truncated", "limits",
        ):
            self.assertIn(field, as_dict)

    def test_status_is_always_one_of_the_fixed_vocabulary(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "hello there")
        for message in ("hello there", "goodbye", ""):
            result = self.matcher.match(message, language="english")
            self.assertIn(result.status, ALL_STATUSES)


if __name__ == "__main__":
    unittest.main()
