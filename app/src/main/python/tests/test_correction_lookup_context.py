"""
Tests for Prompt 465 - Correction Lookup Decision Context.

`build_correction_lookup_context()`
(language_intelligence/correction_lookup_context.py) is a small,
read-only, deterministic wrapper over the EXISTING Prompt 464
structured exact lookup result
(`CorrectionLearningExactLookupResult`), producing a
`CorrectionLookupContext` - NOT yet wired into the language-
understanding flow or any conversation pipeline.

    - "FOUND" lookup creates a context containing the correction records
    - "NOT_FOUND" creates an empty/no-match context
    - "FAILED" preserves the failure state
    - multiple corrections are preserved without ranking
    - original expression is preserved
    - language and locale are preserved
    - correction source is preserved
    - context cannot accidentally mutate the original lookup data
    - conversion is deterministic

Run directly:
    python -m unittest tests.test_correction_lookup_context -v
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
    STATUS_FOUND, STATUS_NOT_FOUND, STATUS_FAILED,
    lookup_correction_learning_input_by_original_expression_with_result,
)
from language_intelligence.correction_lookup_context import (
    CorrectionLookupContext,
    build_correction_lookup_context,
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


class TestFoundLookupCreatesContextWithRecords(unittest.TestCase):
    """"FOUND" lookup creates a context containing the correction
    records."""

    def test_status_is_found(self):
        store, _memory = _store()
        _store_a_correction(store)
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")

        context = build_correction_lookup_context(lookup_result)
        self.assertEqual(context.status, STATUS_FOUND)

    def test_records_are_present(self):
        store, _memory = _store()
        _learning_input, stored = _store_a_correction(store)
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")

        context = build_correction_lookup_context(lookup_result)
        self.assertEqual(context.records, [stored])

    def test_has_match_is_true(self):
        store, _memory = _store()
        _store_a_correction(store)
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")

        context = build_correction_lookup_context(lookup_result)
        self.assertTrue(context.has_match)


class TestNotFoundCreatesEmptyContext(unittest.TestCase):
    """"NOT_FOUND" creates an empty/no-match context."""

    def test_status_is_not_found(self):
        store, _memory = _store()
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "never-stored")

        context = build_correction_lookup_context(lookup_result)
        self.assertEqual(context.status, STATUS_NOT_FOUND)

    def test_records_empty(self):
        store, _memory = _store()
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "never-stored")

        context = build_correction_lookup_context(lookup_result)
        self.assertEqual(context.records, [])

    def test_has_match_is_false(self):
        store, _memory = _store()
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "never-stored")

        context = build_correction_lookup_context(lookup_result)
        self.assertFalse(context.has_match)

    def test_no_language_locale_source_invented(self):
        store, _memory = _store()
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "never-stored")

        context = build_correction_lookup_context(lookup_result)
        self.assertIsNone(context.language)
        self.assertIsNone(context.locale)
        self.assertIsNone(context.source)


class TestFailedPreservesFailureState(unittest.TestCase):
    """"FAILED" preserves the failure state."""

    def test_status_is_failed(self):
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            object(), "dgo")

        context = build_correction_lookup_context(lookup_result)
        self.assertEqual(context.status, STATUS_FAILED)

    def test_reason_is_preserved(self):
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            object(), "dgo")

        context = build_correction_lookup_context(lookup_result)
        self.assertEqual(context.reason, lookup_result.reason)
        self.assertIsNotNone(context.reason)

    def test_records_empty_no_correction_invented(self):
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            object(), "dgo")

        context = build_correction_lookup_context(lookup_result)
        self.assertEqual(context.records, [])
        self.assertFalse(context.has_match)

    def test_original_expression_still_preserved_on_failure(self):
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            object(), "dgo")

        context = build_correction_lookup_context(lookup_result)
        self.assertEqual(context.original_expression, "dgo")


class TestMultipleCorrectionsPreservedWithoutRanking(unittest.TestCase):
    """multiple corrections are preserved without ranking."""

    def test_both_records_present_in_existing_order(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="ciao",
                             corrected_expression="hello (informal)",
                             language="it", locale="it-IT")
        _store_a_correction(store, original_expression="ciao",
                             corrected_expression="bye (informal)",
                             language="en", locale="en-US")
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "ciao")

        context = build_correction_lookup_context(lookup_result)
        self.assertEqual(context.status, STATUS_FOUND)
        self.assertEqual(len(context.records), 2)
        self.assertEqual(
            [record["language"] for record in context.records],
            [canonical_language("en"), canonical_language("it")],
        )

    def test_language_and_source_not_guessed_when_ambiguous(self):
        # more than one record exists, spanning different languages -
        # this module does not pick one, so both stay None.
        store, _memory = _store()
        _store_a_correction(store, original_expression="ciao", language="it")
        _store_a_correction(store, original_expression="ciao", language="en")
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "ciao")

        context = build_correction_lookup_context(lookup_result)
        self.assertIsNone(context.language)
        self.assertIsNone(context.source)


class TestOriginalExpressionIsPreserved(unittest.TestCase):
    """original expression is preserved."""

    def test_matches_the_looked_up_expression(self):
        store, _memory = _store()
        _store_a_correction(store)
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")

        context = build_correction_lookup_context(lookup_result)
        self.assertEqual(context.original_expression, "dgo")


class TestLanguageAndLocaleArePreserved(unittest.TestCase):
    """language and locale are preserved."""

    def test_language_from_the_single_matching_record(self):
        store, _memory = _store()
        learning_input, _stored = _store_a_correction(store)
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")

        context = build_correction_lookup_context(lookup_result)
        self.assertEqual(
            context.language, canonical_language(learning_input["language"]))

    def test_locale_is_never_invented(self):
        # locale was never part of the stored shape (Prompt 455's own
        # documented decision) - the context does not add one.
        store, _memory = _store()
        _store_a_correction(store)
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")

        context = build_correction_lookup_context(lookup_result)
        self.assertIsNone(context.locale)


class TestCorrectionSourceIsPreserved(unittest.TestCase):
    """correction source is preserved."""

    def test_source_from_the_single_matching_record(self):
        store, _memory = _store()
        _store_a_correction(store)
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")

        context = build_correction_lookup_context(lookup_result)
        self.assertEqual(context.source, SOURCE_USER_CORRECTION)


class TestContextCannotAccidentallyMutateOriginalLookupData(unittest.TestCase):
    """context cannot accidentally mutate the original lookup data."""

    def test_mutating_context_records_does_not_affect_lookup_result(self):
        store, _memory = _store()
        _store_a_correction(store)
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")

        context = build_correction_lookup_context(lookup_result)
        context.records[0]["meaning"] = "TAMPERED"
        context.records.append({"key": "injected"})

        self.assertNotEqual(lookup_result.records[0]["meaning"], "TAMPERED")
        self.assertEqual(len(lookup_result.records), 1)

    def test_mutating_lookup_result_after_context_built_does_not_affect_context(self):
        store, _memory = _store()
        _store_a_correction(store)
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")

        context = build_correction_lookup_context(lookup_result)
        lookup_result.records[0]["meaning"] = "TAMPERED"
        lookup_result.records.append({"key": "injected"})

        self.assertNotEqual(context.records[0]["meaning"], "TAMPERED")
        self.assertEqual(len(context.records), 1)

    def test_to_dict_returns_independent_copy(self):
        store, _memory = _store()
        _store_a_correction(store)
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")
        context = build_correction_lookup_context(lookup_result)

        snapshot = context.to_dict()
        snapshot["records"][0]["meaning"] = "TAMPERED"

        self.assertNotEqual(context.records[0]["meaning"], "TAMPERED")

    def test_wrong_lookup_result_type_raises(self):
        with self.assertRaises(TypeError):
            build_correction_lookup_context({"status": "FOUND"})


class TestConversionIsDeterministic(unittest.TestCase):
    """conversion is deterministic."""

    def test_repeated_conversions_are_equal(self):
        store, _memory = _store()
        _store_a_correction(store)
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")

        contexts = [build_correction_lookup_context(lookup_result) for _ in range(5)]
        self.assertTrue(all(context == contexts[0] for context in contexts))

    def test_copy_equals_original(self):
        store, _memory = _store()
        _store_a_correction(store)
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            store, "dgo")
        context = build_correction_lookup_context(lookup_result)

        self.assertEqual(context.copy(), context)
        self.assertIsNot(context.copy().records, context.records)


if __name__ == "__main__":
    unittest.main()
