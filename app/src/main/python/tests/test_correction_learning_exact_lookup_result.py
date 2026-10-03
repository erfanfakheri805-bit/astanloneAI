"""
Tests for Prompt 464 - Structured Exact Correction Lookup Result.

`lookup_correction_learning_input_by_original_expression_with_result()`
(language_intelligence/correction_learning_exact_lookup_result.py) is
a small, read-only, deterministic wrapper over the EXISTING Prompt 463
exact lookup
(`lookup_stored_correction_learning_input_by_original_expression()`),
reporting the outcome as a `CorrectionLearningExactLookupResult`
(FOUND / NOT_FOUND / FAILED) instead of a list-or-raise.

    - exact lookup with one stored correction -> "FOUND"
    - exact lookup with multiple stored corrections -> "FOUND" with
      all matching records
    - exact lookup with no matching record -> "NOT_FOUND"
    - simulated storage failure -> "FAILED"
    - stored correction data is preserved
    - multiple corrections are not automatically ranked or selected
    - result is deterministic

Run directly:
    python -m unittest tests.test_correction_learning_exact_lookup_result -v
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
from language_intelligence.correction_learning_exact_lookup_result import (
    CorrectionLearningExactLookupResult,
    STATUS_FOUND,
    STATUS_NOT_FOUND,
    STATUS_FAILED,
    ALL_STATUSES,
    lookup_correction_learning_input_by_original_expression_with_result,
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


class TestAllStatusesDistinct(unittest.TestCase):
    """the result clearly distinguishes FOUND / NOT_FOUND / FAILED."""

    def test_all_three_statuses_are_distinct_and_listed(self):
        self.assertEqual(set(ALL_STATUSES), {"FOUND", "NOT_FOUND", "FAILED"})
        self.assertEqual(STATUS_FOUND, "FOUND")
        self.assertEqual(STATUS_NOT_FOUND, "NOT_FOUND")
        self.assertEqual(STATUS_FAILED, "FAILED")

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            CorrectionLearningExactLookupResult("BOGUS", "dgo")


class TestExactLookupWithOneStoredCorrectionIsFound(unittest.TestCase):
    """exact lookup with one stored correction -> FOUND."""

    def test_status_is_found(self):
        store, _memory = _store()
        _store_a_correction(store)

        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")
        self.assertEqual(result.status, STATUS_FOUND)

    def test_one_record_returned(self):
        store, _memory = _store()
        _store_a_correction(store)

        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")
        self.assertEqual(len(result.records), 1)

    def test_reason_is_none(self):
        store, _memory = _store()
        _store_a_correction(store)

        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")
        self.assertIsNone(result.reason)


class TestExactLookupWithMultipleStoredCorrectionsIsFound(unittest.TestCase):
    """exact lookup with multiple stored corrections -> FOUND with all
    matching records."""

    def test_both_records_returned(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="ciao",
                             corrected_expression="hello (informal)",
                             language="it", locale="it-IT")
        _store_a_correction(store, original_expression="ciao",
                             corrected_expression="bye (informal)",
                             language="en", locale="en-US")

        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "ciao")
        self.assertEqual(result.status, STATUS_FOUND)
        self.assertEqual(len(result.records), 2)


class TestExactLookupWithNoMatchingRecordIsNotFound(unittest.TestCase):
    """exact lookup with no matching record -> NOT_FOUND."""

    def test_nothing_stored_is_not_found(self):
        store, _memory = _store()
        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "never-stored")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.records, [])
        self.assertIsNone(result.reason)

    def test_similar_but_non_identical_is_not_found(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo")

        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dog")
        self.assertEqual(result.status, STATUS_NOT_FOUND)

    def test_original_expression_echoed_back(self):
        store, _memory = _store()
        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "never-stored")
        self.assertEqual(result.original_expression, "never-stored")


class TestSimulatedStorageFailureIsFailed(unittest.TestCase):
    """simulated storage failure -> FAILED."""

    def test_wrong_store_type_is_failed(self):
        result = lookup_correction_learning_input_by_original_expression_with_result(
            object(), "dgo")
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(result.records, [])
        self.assertIsNotNone(result.reason)

    def test_failure_reason_is_the_existing_exception_text(self):
        store, _memory = _store()
        try:
            from language_intelligence.correction_learning_input_retrieval import (
                lookup_stored_correction_learning_input_by_original_expression,
            )
            lookup_stored_correction_learning_input_by_original_expression(
                object(), "dgo")
            self.fail("expected TypeError")
        except TypeError as exc:
            expected_reason = str(exc)

        result = lookup_correction_learning_input_by_original_expression_with_result(
            object(), "dgo")
        self.assertEqual(result.reason, expected_reason)

    def test_original_expression_still_echoed_back_on_failure(self):
        result = lookup_correction_learning_input_by_original_expression_with_result(
            object(), "dgo")
        self.assertEqual(result.original_expression, "dgo")

    def test_unrelated_exception_types_still_propagate(self):
        # only TypeError/ValueError (the existing lookup's own
        # documented exceptions) are turned into FAILED - anything
        # else is not one of this pipeline's documented outcomes.
        class _ExplodingStore(LanguageLearningStore):
            def find_items(self, *args, **kwargs):
                raise RuntimeError("boom")

        store, memory = _store()
        exploding = _ExplodingStore(memory)
        with self.assertRaises(RuntimeError):
            lookup_correction_learning_input_by_original_expression_with_result(
                exploding, "dgo")


class TestStoredCorrectionDataIsPreserved(unittest.TestCase):
    """stored correction data is preserved."""

    def test_key_matches(self):
        store, _memory = _store()
        _store_a_correction(store)
        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")
        self.assertEqual(result.records[0]["key"], "dgo")

    def test_meaning_matches(self):
        store, _memory = _store()
        _store_a_correction(store)
        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")
        self.assertEqual(result.records[0]["meaning"], "dog")

    def test_language_matches(self):
        store, _memory = _store()
        learning_input, _stored = _store_a_correction(store)
        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")
        self.assertEqual(
            result.records[0]["language"], canonical_language(learning_input["language"]))

    def test_no_locale_field_is_invented(self):
        # locale was never part of this stored shape (Prompt 455's own
        # documented decision, carried through unchanged) - nothing is
        # added here either.
        store, _memory = _store()
        _store_a_correction(store)
        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")
        self.assertNotIn("locale", result.records[0])

    def test_source_matches(self):
        store, _memory = _store()
        _store_a_correction(store)
        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")
        self.assertEqual(result.records[0]["source"], SOURCE_USER_CORRECTION)

    def test_record_matches_the_raw_stored_record(self):
        store, _memory = _store()
        _learning_input, stored = _store_a_correction(store)
        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")
        self.assertEqual(result.records[0], stored)


class TestMultipleCorrectionsAreNotAutomaticallyRankedOrSelected(unittest.TestCase):
    """multiple corrections are not automatically ranked or selected."""

    def test_both_records_present_in_existing_store_order(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="ciao",
                             corrected_expression="hello (informal)",
                             language="it", locale="it-IT")
        _store_a_correction(store, original_expression="ciao",
                             corrected_expression="bye (informal)",
                             language="en", locale="en-US")

        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "ciao")
        # find_items() orders by (language, item_type, id); the
        # canonicalized "en" ("english") sorts before "it" - no
        # ranking/scoring is applied here, this is simply the
        # existing storage order, preserved unchanged.
        self.assertEqual(
            [record["language"] for record in result.records],
            [canonical_language("en"), canonical_language("it")],
        )

    def test_no_single_record_or_best_match_field_exists(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="ciao", language="it")
        _store_a_correction(store, original_expression="ciao", language="en")

        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "ciao")
        self.assertNotIn("record", result.to_dict())
        self.assertNotIn("best_match", result.to_dict())
        self.assertIsInstance(result.records, list)


class TestResultIsDeterministic(unittest.TestCase):
    """result is deterministic."""

    def test_repeated_calls_return_equal_results(self):
        store, _memory = _store()
        _store_a_correction(store)

        results = [
            lookup_correction_learning_input_by_original_expression_with_result(
                store, "dgo")
            for _ in range(5)
        ]
        self.assertTrue(all(result == results[0] for result in results))

    def test_repeated_not_found_calls_return_equal_results(self):
        store, _memory = _store()
        first = lookup_correction_learning_input_by_original_expression_with_result(
            store, "never-stored")
        second = lookup_correction_learning_input_by_original_expression_with_result(
            store, "never-stored")
        self.assertEqual(first, second)

    def test_lookup_never_mutates_the_stored_record(self):
        store, _memory = _store()
        _learning_input, stored = _store_a_correction(store)

        lookup_correction_learning_input_by_original_expression_with_result(store, "dgo")
        lookup_correction_learning_input_by_original_expression_with_result(store, "dgo")

        result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")
        self.assertEqual(result.records[0]["version"], stored["version"])


if __name__ == "__main__":
    unittest.main()
