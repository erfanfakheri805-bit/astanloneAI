"""
Tests for Prompt 461 - Store Accepted Correction Learning Input.

`store_accepted_correction_learning_input()`
(language_intelligence/correction_learning_input_storage.py) writes an
ACCEPTED correction-learning input - via Prompt 460's EXISTING adapter
- into the EXISTING language-learning storage
(`LanguageLearningStore.learn_item()`, Prompt 416). It adds no new
storage mechanism and is never triggered automatically.

    - valid accepted correction is stored
    - original expression is preserved
    - corrected expression/meaning is preserved
    - language/locale are preserved
    - correction source is preserved
    - rejected input is not stored
    - failed input is not stored
    - invalid/incomplete input is not stored
    - repeated explicit storage calls behave consistently with the
      existing storage conventions

Run directly:
    python -m unittest tests.test_correction_learning_input_storage -v
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
    STATUS_REJECTED,
    STATUS_FAILED,
    CorrectionLearningHandoffResult,
    handoff_correction_learning_input_with_result,
)
from language_intelligence.correction_learning_input_storage import (
    store_accepted_correction_learning_input,
)


class CountingLanguageLearningStore(LanguageLearningStore):
    """TEST DOUBLE at the store boundary - always delegates to the real
    LanguageLearningStore implementation; only adds a call counter -
    same convention test_correction_learning_input_handoff.py already
    uses."""

    def __init__(self, memory):
        super().__init__(memory)
        self.learn_item_calls = 0

    def learn_item(self, *args, **kwargs):
        self.learn_item_calls += 1
        return super().learn_item(*args, **kwargs)


def _store():
    db_path = tempfile.mktemp(suffix=".db")
    memory = MemorySystem(db_path)
    return CountingLanguageLearningStore(memory), memory


def _valid_learning_input(**overrides):
    source = build_correction_understanding(
        "no I mean dog not dgo", original_expression="dgo",
        corrected_expression="dog", language="en", locale="en-US", confidence=0.9)
    result = map_correction_understanding_to_result(source)
    record = map_correction_understanding_result_to_feedback_record(result)
    learning_input = convert_correction_feedback_to_learning_input(record)
    learning_input.update(overrides)
    return learning_input


class TestValidAcceptedCorrectionIsStored(unittest.TestCase):
    """valid accepted correction is stored."""

    def test_learn_item_is_called(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        store_accepted_correction_learning_input(handoff_result, learning_input, store)
        self.assertEqual(store.learn_item_calls, 2)  # once via handoff, once here

    def test_item_is_actually_stored(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        result = store_accepted_correction_learning_input(
            handoff_result, learning_input, store)
        self.assertIsInstance(result, dict)
        stored = store.get_item("en", "correction", "dgo")
        self.assertIsNotNone(stored)


class TestOriginalExpressionIsPreserved(unittest.TestCase):
    """original expression is preserved."""

    def test_key_matches_the_original_expression(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        result = store_accepted_correction_learning_input(
            handoff_result, learning_input, store)
        self.assertEqual(result["key"], "dgo")


class TestCorrectedExpressionOrMeaningIsPreserved(unittest.TestCase):
    """corrected expression/meaning is preserved."""

    def test_meaning_matches_the_correction(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        result = store_accepted_correction_learning_input(
            handoff_result, learning_input, store)
        self.assertEqual(result["meaning"], "dog")


class TestLanguageAndLocaleArePreserved(unittest.TestCase):
    """language/locale are preserved."""

    def test_language_matches(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        result = store_accepted_correction_learning_input(
            handoff_result, learning_input, store)
        # language is canonicalized by learn_item() itself (existing,
        # unchanged behavior), not by this storage operation.
        self.assertEqual(result["language"], canonical_language(learning_input["language"]))

    def test_no_locale_field_is_invented(self):
        # locale was never part of learn_item()'s existing keyword
        # shape - nothing is added here either.
        store, _memory = _store()
        learning_input = _valid_learning_input()
        self.assertNotIn("locale", learning_input)
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        result = store_accepted_correction_learning_input(
            handoff_result, learning_input, store)
        self.assertNotIn("locale", result)


class TestCorrectionSourceIsPreserved(unittest.TestCase):
    """correction source is preserved."""

    def test_source_matches_user_correction(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        result = store_accepted_correction_learning_input(
            handoff_result, learning_input, store)
        self.assertEqual(result["source"], SOURCE_USER_CORRECTION)


class TestRejectedInputIsNotStored(unittest.TestCase):
    """rejected input is not stored."""

    def test_returns_none(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        del learning_input["key"]
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)
        self.assertEqual(handoff_result.status, STATUS_REJECTED)

        result = store_accepted_correction_learning_input(
            handoff_result, learning_input, store)
        self.assertIsNone(result)
        self.assertEqual(store.learn_item_calls, 0)

    def test_nothing_is_stored(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(meaning=None)
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        store_accepted_correction_learning_input(handoff_result, learning_input, store)
        self.assertIsNone(store.get_item("en", "correction", "dgo"))


class TestFailedInputIsNotStored(unittest.TestCase):
    """failed input is not stored."""

    def test_returns_none(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(confidence="not a number")
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)
        self.assertEqual(handoff_result.status, STATUS_FAILED)

        result = store_accepted_correction_learning_input(
            handoff_result, learning_input, store)
        self.assertIsNone(result)
        self.assertEqual(store.learn_item_calls, 1)  # only the failed attempt inside handoff

    def test_directly_constructed_failed_result_is_not_stored(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = CorrectionLearningHandoffResult(
            STATUS_FAILED, reason="existing failure text")

        result = store_accepted_correction_learning_input(
            handoff_result, learning_input, store)
        self.assertIsNone(result)
        self.assertEqual(store.learn_item_calls, 0)


class TestInvalidOrIncompleteInputIsNotStored(unittest.TestCase):
    """invalid/incomplete input is not stored."""

    def test_none_handoff_result(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        result = store_accepted_correction_learning_input(None, learning_input, store)
        self.assertIsNone(result)
        self.assertEqual(store.learn_item_calls, 0)

    def test_structurally_invalid_accepted_result_is_not_stored(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        from language_intelligence.correction_learning_handoff_result import STATUS_ACCEPTED
        handoff_result = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        handoff_result.accepted = False  # structurally INVALID
        result = store_accepted_correction_learning_input(
            handoff_result, learning_input, store)
        self.assertIsNone(result)
        self.assertEqual(store.learn_item_calls, 0)

    def test_non_dict_learning_input_is_not_stored(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)
        result = store_accepted_correction_learning_input(
            handoff_result, "not a dict", store)
        self.assertIsNone(result)

    def test_wrong_store_type_raises_for_an_otherwise_accepted_input(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)
        with self.assertRaises(TypeError):
            store_accepted_correction_learning_input(handoff_result, learning_input, object())


class TestRepeatedExplicitStorageCallsBehaveConsistently(unittest.TestCase):
    """repeated explicit storage calls behave consistently with the
    existing storage conventions."""

    def test_calling_it_twice_updates_rather_than_duplicates(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        first = store_accepted_correction_learning_input(
            handoff_result, learning_input, store)
        second = store_accepted_correction_learning_input(
            handoff_result, learning_input, store)

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["version"], first["version"] + 1)

    def test_this_operation_is_never_called_automatically(self):
        # Building and even accepting a handoff result never stores
        # via THIS operation by itself - store_accepted_correction_
        # learning_input() must be called explicitly.
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_correction_learning_input_with_result(learning_input, store)
        calls_before_explicit_call = store.learn_item_calls
        self.assertEqual(calls_before_explicit_call, 1)  # only the handoff's own call


if __name__ == "__main__":
    unittest.main()
