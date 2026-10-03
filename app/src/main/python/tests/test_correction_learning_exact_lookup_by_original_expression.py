"""
Tests for Prompt 463 - Exact Correction Lookup by Original Expression.

`lookup_stored_correction_learning_input_by_original_expression()`
(language_intelligence/correction_learning_input_retrieval.py) is a
small, read-only, deterministic, EXACT-match-only pass-through to the
EXISTING `LanguageLearningStore.find_items()` (Prompt 416/418), fixed
to `ITEM_TYPE_CORRECTION` (Prompt 455's existing constant) - looking up
correction-learning records previously stored by Prompt 461
(`store_accepted_correction_learning_input()`) by original expression
alone, without requiring `language`.

    - stored correction found by exact original expression
    - exact case-sensitive/case-insensitive behavior follows the
      existing storage convention
    - missing expression returns NOT_FOUND/empty according to
      existing conventions
    - similar but non-identical expression does not incorrectly match
    - returned correction data is preserved
    - language and locale remain intact
    - correction source remains intact
    - lookup does not modify stored data

Run directly:
    python -m unittest tests.test_correction_learning_exact_lookup_by_original_expression -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from language_intelligence.correction_understanding import (
    build_correction_understanding,
)
from language_intelligence.correction_understanding_result import (
    map_correction_understanding_to_result,
)
from language_intelligence.correction_feedback_record import (
    map_correction_understanding_result_to_feedback_record,
    SOURCE_USER_CORRECTION,
)
from language_intelligence.correction_feedback_learning_input_adapter import (
    convert_correction_feedback_to_learning_input,
)
from language_intelligence.language_learning_store import LanguageLearningStore
from language_intelligence.language_context import canonical_language
from language_intelligence.correction_learning_handoff_result import (
    handoff_correction_learning_input_with_result,
)
from language_intelligence.correction_learning_input_storage import (
    store_accepted_correction_learning_input,
)
from language_intelligence.correction_learning_input_retrieval import (
    lookup_stored_correction_learning_input_by_original_expression,
)


def _store():
    db_path = tempfile.mktemp(suffix=".db")
    memory = MemorySystem(db_path)
    return LanguageLearningStore(memory), memory


def _valid_learning_input(original_expression="dgo", corrected_expression="dog",
                           language="en", locale="en-US", confidence=0.9, **overrides):
    source = build_correction_understanding(
        f"no I mean {corrected_expression} not {original_expression}",
        original_expression=original_expression,
        corrected_expression=corrected_expression,
        language=language, locale=locale, confidence=confidence)
    result = map_correction_understanding_to_result(source)
    record = map_correction_understanding_result_to_feedback_record(result)
    learning_input = convert_correction_feedback_to_learning_input(record)
    learning_input.update(overrides)
    return learning_input


def _store_a_correction(store, **overrides):
    learning_input = _valid_learning_input(**overrides)
    handoff_result = handoff_correction_learning_input_with_result(learning_input, store)
    stored = store_accepted_correction_learning_input(handoff_result, learning_input, store)
    return learning_input, stored


class TestStoredCorrectionFoundByExactOriginalExpression(unittest.TestCase):
    """stored correction found by exact original expression."""

    def test_lookup_returns_a_list(self):
        store, _memory = _store()
        _store_a_correction(store)

        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo")
        self.assertIsInstance(matches, list)

    def test_lookup_finds_the_stored_record(self):
        store, _memory = _store()
        _learning_input, stored = _store_a_correction(store)

        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0], stored)

    def test_lookup_works_without_language(self):
        # the whole point of Prompt 463: only the original expression
        # is required, unlike Prompt 462's language-scoped retrieval.
        store, _memory = _store()
        _store_a_correction(store, language="en")

        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo")
        self.assertEqual(len(matches), 1)

    def test_language_argument_narrows_the_match(self):
        store, _memory = _store()
        _store_a_correction(store, language="en")

        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo", language="en")
        self.assertEqual(len(matches), 1)

        no_matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo", language="fr")
        self.assertEqual(no_matches, [])


class TestExactCaseConventionFollowsExistingStorageConvention(unittest.TestCase):
    """exact case-sensitive/case-insensitive behavior follows the
    existing storage convention (case-folded identity, same as
    `get_item()`/`find_items()`)."""

    def test_different_case_still_matches(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo")

        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "DGO")
        self.assertEqual(len(matches), 1)

    def test_extra_surrounding_whitespace_still_matches(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo")

        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "  dgo  ")
        self.assertEqual(len(matches), 1)


class TestMissingExpressionReturnsNotFound(unittest.TestCase):
    """missing expression returns NOT_FOUND/empty according to
    existing conventions (find_items()'s own empty list)."""

    def test_nothing_stored_returns_empty_list(self):
        store, _memory = _store()
        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "never-stored")
        self.assertEqual(matches, [])

    def test_rejected_input_was_never_stored_so_lookup_returns_empty(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        del learning_input["key"]
        handoff_result = handoff_correction_learning_input_with_result(learning_input, store)
        store_accepted_correction_learning_input(handoff_result, learning_input, store)

        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo")
        self.assertEqual(matches, [])

    def test_wrong_store_type_raises(self):
        with self.assertRaises(TypeError):
            lookup_stored_correction_learning_input_by_original_expression(
                object(), "dgo")


class TestSimilarButNonIdenticalExpressionDoesNotMatch(unittest.TestCase):
    """similar but non-identical expression does not incorrectly
    match - exact matching only, no fuzzy matching."""

    def test_prefix_does_not_match(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo")

        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dg")
        self.assertEqual(matches, [])

    def test_superstring_does_not_match(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo")

        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgoo")
        self.assertEqual(matches, [])

    def test_similar_spelling_does_not_match(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo")

        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dog")
        self.assertEqual(matches, [])


class TestReturnedCorrectionDataIsPreserved(unittest.TestCase):
    """returned correction data is preserved."""

    def test_key_matches(self):
        store, _memory = _store()
        _store_a_correction(store)
        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo")
        self.assertEqual(matches[0]["key"], "dgo")

    def test_meaning_matches(self):
        store, _memory = _store()
        _store_a_correction(store)
        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo")
        self.assertEqual(matches[0]["meaning"], "dog")


class TestLanguageAndLocaleRemainIntact(unittest.TestCase):
    """language and locale remain intact."""

    def test_language_matches(self):
        store, _memory = _store()
        learning_input, _stored = _store_a_correction(store)
        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo")
        self.assertEqual(
            matches[0]["language"], canonical_language(learning_input["language"]))

    def test_no_locale_field_is_invented(self):
        # locale was never part of this stored shape (Prompt 455's own
        # documented decision) - nothing is added here either.
        store, _memory = _store()
        _store_a_correction(store)
        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo")
        self.assertNotIn("locale", matches[0])


class TestCorrectionSourceRemainsIntact(unittest.TestCase):
    """correction source remains intact."""

    def test_source_matches(self):
        store, _memory = _store()
        _store_a_correction(store)
        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo")
        self.assertEqual(matches[0]["source"], SOURCE_USER_CORRECTION)


class TestLookupDoesNotModifyStoredData(unittest.TestCase):
    """lookup does not modify stored data."""

    def test_repeated_lookups_return_equal_results(self):
        store, _memory = _store()
        _store_a_correction(store)

        first = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo")
        lookup_stored_correction_learning_input_by_original_expression(store, "dgo")
        second = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo")
        self.assertEqual(first, second)

    def test_lookup_never_changes_the_version(self):
        store, _memory = _store()
        _learning_input, stored = _store_a_correction(store)

        lookup_stored_correction_learning_input_by_original_expression(store, "dgo")
        lookup_stored_correction_learning_input_by_original_expression(store, "dgo")

        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "dgo")
        self.assertEqual(matches[0]["version"], stored["version"])


class TestMultipleExactRecordsPreserveExistingOrdering(unittest.TestCase):
    """if multiple exact records are possible (the same original
    expression learned under more than one language), the existing
    storage ordering/convention (find_items()'s own `language,
    item_type, id` order) is preserved - no invented ranking."""

    def test_same_expression_in_two_languages_both_returned_in_store_order(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="ciao",
                             corrected_expression="hello (informal)",
                             language="it", locale="it-IT")
        _store_a_correction(store, original_expression="ciao",
                             corrected_expression="bye (informal)",
                             language="en", locale="en-US")

        matches = lookup_stored_correction_learning_input_by_original_expression(
            store, "ciao")
        self.assertEqual(len(matches), 2)
        # find_items() orders by (language, item_type, id); the
        # canonicalized "en" ("english") sorts before "it".
        self.assertEqual(
            [m["language"] for m in matches],
            [canonical_language("en"), canonical_language("it")],
        )


if __name__ == "__main__":
    unittest.main()
