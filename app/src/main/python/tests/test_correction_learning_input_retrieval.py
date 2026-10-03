"""
Tests for Prompt 462 - Retrieve Stored Correction Learning Input.

`retrieve_stored_correction_learning_input()`
(language_intelligence/correction_learning_input_retrieval.py) is a
small, read-only, deterministic pass-through to the EXISTING
`LanguageLearningStore.get_item()` (Prompt 416), looking up a record
previously stored by Prompt 461
(`store_accepted_correction_learning_input()`) by its exact
`(language, original_expression)` identity under `ITEM_TYPE_CORRECTION`
(Prompt 455's existing constant).

    - store a correction, then retrieve it
    - retrieved original expression matches the stored value
    - retrieved corrected expression/meaning matches the stored value
    - language and locale are preserved
    - correction source is preserved
    - retrieving a missing record returns NOT_FOUND/empty according to
      existing conventions
    - retrieval does not modify the stored record
    - retrieval is deterministic

Run directly:
    python -m unittest tests.test_correction_learning_input_retrieval -v
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
    retrieve_stored_correction_learning_input,
)


def _store():
    db_path = tempfile.mktemp(suffix=".db")
    memory = MemorySystem(db_path)
    return LanguageLearningStore(memory), memory


def _valid_learning_input(**overrides):
    source = build_correction_understanding(
        "no I mean dog not dgo", original_expression="dgo",
        corrected_expression="dog", language="en", locale="en-US", confidence=0.9)
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


class TestStoreThenRetrieve(unittest.TestCase):
    """store a correction, then retrieve it."""

    def test_retrieve_returns_a_dict(self):
        store, _memory = _store()
        learning_input, stored = _store_a_correction(store)
        self.assertIsNotNone(stored)

        retrieved = retrieve_stored_correction_learning_input(store, "en", "dgo")
        self.assertIsInstance(retrieved, dict)

    def test_retrieved_record_matches_the_stored_record(self):
        store, _memory = _store()
        learning_input, stored = _store_a_correction(store)

        retrieved = retrieve_stored_correction_learning_input(store, "en", "dgo")
        self.assertEqual(retrieved, stored)


class TestRetrievedOriginalExpressionMatches(unittest.TestCase):
    """retrieved original expression matches the stored value."""

    def test_key_matches(self):
        store, _memory = _store()
        _store_a_correction(store)
        retrieved = retrieve_stored_correction_learning_input(store, "en", "dgo")
        self.assertEqual(retrieved["key"], "dgo")


class TestRetrievedCorrectedExpressionOrMeaningMatches(unittest.TestCase):
    """retrieved corrected expression/meaning matches the stored value."""

    def test_meaning_matches(self):
        store, _memory = _store()
        _store_a_correction(store)
        retrieved = retrieve_stored_correction_learning_input(store, "en", "dgo")
        self.assertEqual(retrieved["meaning"], "dog")


class TestLanguageAndLocaleArePreserved(unittest.TestCase):
    """language and locale are preserved."""

    def test_language_matches(self):
        store, _memory = _store()
        learning_input, _stored = _store_a_correction(store)
        retrieved = retrieve_stored_correction_learning_input(store, "en", "dgo")
        self.assertEqual(retrieved["language"], canonical_language(learning_input["language"]))

    def test_no_locale_field_is_invented(self):
        # locale was never part of this stored shape - nothing is
        # added on retrieval either.
        store, _memory = _store()
        _store_a_correction(store)
        retrieved = retrieve_stored_correction_learning_input(store, "en", "dgo")
        self.assertNotIn("locale", retrieved)


class TestCorrectionSourceIsPreserved(unittest.TestCase):
    """correction source is preserved."""

    def test_source_matches(self):
        store, _memory = _store()
        _store_a_correction(store)
        retrieved = retrieve_stored_correction_learning_input(store, "en", "dgo")
        self.assertEqual(retrieved["source"], SOURCE_USER_CORRECTION)


class TestMissingRecordReturnsNotFound(unittest.TestCase):
    """retrieving a missing record returns NOT_FOUND/empty according
    to existing conventions."""

    def test_nothing_stored_returns_none(self):
        store, _memory = _store()
        retrieved = retrieve_stored_correction_learning_input(store, "en", "never-stored")
        self.assertIsNone(retrieved)

    def test_wrong_language_returns_none(self):
        store, _memory = _store()
        _store_a_correction(store)
        retrieved = retrieve_stored_correction_learning_input(store, "fr", "dgo")
        self.assertIsNone(retrieved)

    def test_rejected_input_was_never_stored_so_retrieval_returns_none(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        del learning_input["key"]
        handoff_result = handoff_correction_learning_input_with_result(learning_input, store)
        store_accepted_correction_learning_input(handoff_result, learning_input, store)

        retrieved = retrieve_stored_correction_learning_input(store, "en", "dgo")
        self.assertIsNone(retrieved)

    def test_wrong_store_type_raises(self):
        with self.assertRaises(TypeError):
            retrieve_stored_correction_learning_input(object(), "en", "dgo")


class TestRetrievalDoesNotModifyTheStoredRecord(unittest.TestCase):
    """retrieval does not modify the stored record."""

    def test_second_retrieval_still_matches_the_original(self):
        store, _memory = _store()
        _store_a_correction(store)

        first = retrieve_stored_correction_learning_input(store, "en", "dgo")
        retrieve_stored_correction_learning_input(store, "en", "dgo")
        second = retrieve_stored_correction_learning_input(store, "en", "dgo")
        self.assertEqual(first, second)

    def test_retrieval_never_changes_the_version(self):
        store, _memory = _store()
        _learning_input, stored = _store_a_correction(store)
        retrieve_stored_correction_learning_input(store, "en", "dgo")
        retrieve_stored_correction_learning_input(store, "en", "dgo")

        retrieved = retrieve_stored_correction_learning_input(store, "en", "dgo")
        self.assertEqual(retrieved["version"], stored["version"])


class TestRetrievalIsDeterministic(unittest.TestCase):
    """retrieval is deterministic."""

    def test_repeated_calls_return_equal_results(self):
        store, _memory = _store()
        _store_a_correction(store)

        results = [retrieve_stored_correction_learning_input(store, "en", "dgo")
                   for _ in range(5)]
        self.assertTrue(all(result == results[0] for result in results))


if __name__ == "__main__":
    unittest.main()
