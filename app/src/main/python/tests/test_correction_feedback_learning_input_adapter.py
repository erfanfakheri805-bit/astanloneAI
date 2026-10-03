"""
Tests for Prompt 455 - Correction Feedback Learning Input Adapter.

`convert_correction_feedback_to_learning_input()`
(language_intelligence/correction_feedback_learning_input_adapter.py)
is the one small, deterministic conversion from an existing
`CorrectionFeedbackRecord` (Prompt 449) into a plain dict shaped like
`LanguageLearningStore.learn_item()`'s own keyword arguments (Prompt
416) - the project's existing language-learning input shape. It does
not call `learn_item()`, does not store anything, and does not touch
`LearningAnalyzer`, `CorrectionUnderstanding`, or
`CorrectionUnderstandingResult`. Only:

    1. a valid CorrectionFeedbackRecord converts successfully
    2. the original and corrected expressions are mapped correctly
       (key / meaning)
    3. language is preserved; locale has no counterpart in the
       existing learning-input shape and is correctly left out
    4. confidence is preserved
    5. source information is preserved (source -> source,
       source_text -> source_context)
    6. invalid feedback does not produce a valid learning input
       (returns None, the project's existing empty-result convention)
    7. the original CorrectionFeedbackRecord is not modified
    8. no information is invented during conversion (item_type is the
       only added value, and it is a fixed, documented constant - not
       a guess; unmapped fields such as locale/created_at/examples/
       relationships/learning_method never appear in the output)

Run directly:
    python -m unittest tests.test_correction_feedback_learning_input_adapter -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_understanding import (
    build_correction_understanding,
)
from language_intelligence.correction_understanding_result import (
    map_correction_understanding_to_result,
)
from language_intelligence.correction_feedback_record import (
    CorrectionFeedbackRecord,
    SOURCE_USER_CORRECTION,
    map_correction_understanding_result_to_feedback_record,
)
from language_intelligence.correction_feedback_learning_input_adapter import (
    ITEM_TYPE_CORRECTION,
    convert_correction_feedback_to_learning_input,
)


def _valid_record(**overrides):
    source = build_correction_understanding(
        "no I mean dog not dgo", original_expression="dgo",
        corrected_expression="dog", language="en", locale="en-US", confidence=0.9)
    result = map_correction_understanding_to_result(source)
    record = map_correction_understanding_result_to_feedback_record(
        result, created_at="2026-01-01T00:00:00+00:00")
    if overrides:
        data = record.to_dict()
        data.update(overrides)
        record = CorrectionFeedbackRecord(**data)
    return record


def _invalid_record():
    source = build_correction_understanding("dgo", original_expression="dgo")
    result = map_correction_understanding_to_result(source)
    return map_correction_understanding_result_to_feedback_record(result)


class TestValidRecordConvertsSuccessfully(unittest.TestCase):
    """1. A valid CorrectionFeedbackRecord converts successfully."""

    def test_returns_a_dict(self):
        record = _valid_record()
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertIsInstance(learning_input, dict)

    def test_item_type_is_the_documented_correction_constant(self):
        record = _valid_record()
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertEqual(learning_input["item_type"], ITEM_TYPE_CORRECTION)
        self.assertEqual(ITEM_TYPE_CORRECTION, "correction")

    def test_rejects_a_non_record_argument(self):
        with self.assertRaises(TypeError):
            convert_correction_feedback_to_learning_input({"is_valid_feedback": True})


class TestExpressionsAreMappedCorrectly(unittest.TestCase):
    """2. The original and corrected expressions are mapped correctly."""

    def test_original_expression_becomes_key(self):
        record = _valid_record()
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertEqual(learning_input["key"], record.original_expression)
        self.assertEqual(learning_input["key"], "dgo")

    def test_corrected_expression_or_meaning_becomes_meaning(self):
        record = _valid_record()
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertEqual(
            learning_input["meaning"], record.corrected_expression_or_meaning)
        self.assertEqual(learning_input["meaning"], "dog")

    def test_meaning_is_deep_copied_not_shared(self):
        record = _valid_record(corrected_expression_or_meaning={"text": "dog"})
        learning_input = convert_correction_feedback_to_learning_input(record)
        learning_input["meaning"]["text"] = "mutated"
        self.assertEqual(
            record.corrected_expression_or_meaning, {"text": "dog"})


class TestLanguageIsPreservedLocaleIsNot(unittest.TestCase):
    """3. Language and locale are preserved when supported by the
    existing learning-input shape - language is, locale is not."""

    def test_language_is_preserved(self):
        record = _valid_record()
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertEqual(learning_input["language"], record.language)
        self.assertEqual(learning_input["language"], "en")

    def test_locale_has_no_counterpart_and_is_left_out(self):
        record = _valid_record()
        self.assertEqual(record.locale, "en-US")
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertNotIn("locale", learning_input)
        # Not silently folded into another field either.
        self.assertNotIn("en-US", str(learning_input.get("source_context")))
        self.assertNotIn("en-US", str(learning_input.get("meaning")))


class TestConfidenceIsPreserved(unittest.TestCase):
    """4. Confidence is preserved when supported."""

    def test_confidence_is_copied_through(self):
        record = _valid_record()
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertEqual(learning_input["confidence"], record.confidence)
        self.assertEqual(learning_input["confidence"], 0.9)

    def test_none_confidence_is_preserved_as_none(self):
        record = _valid_record(confidence=None)
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertIsNone(learning_input["confidence"])


class TestSourceInformationIsPreserved(unittest.TestCase):
    """5. Source information is preserved when supported."""

    def test_source_is_copied_through(self):
        record = _valid_record()
        self.assertEqual(record.source, SOURCE_USER_CORRECTION)
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertEqual(learning_input["source"], SOURCE_USER_CORRECTION)

    def test_source_text_becomes_source_context(self):
        record = _valid_record()
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertEqual(learning_input["source_context"], record.source_text)
        self.assertEqual(
            learning_input["source_context"], "no I mean dog not dgo")


class TestInvalidFeedbackDoesNotProduceALearningInput(unittest.TestCase):
    """6. Invalid feedback does not produce a valid learning input."""

    def test_invalid_record_returns_none(self):
        record = _invalid_record()
        self.assertFalse(record.is_valid_feedback)
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertIsNone(learning_input)

    def test_explicitly_invalid_record_returns_none(self):
        record = _valid_record(is_valid_feedback=False)
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertIsNone(learning_input)


class TestOriginalRecordIsNotModified(unittest.TestCase):
    """7. The original CorrectionFeedbackRecord is not modified."""

    def test_record_unchanged_after_conversion(self):
        record = _valid_record()
        before = record.to_dict()
        convert_correction_feedback_to_learning_input(record)
        after = record.to_dict()
        self.assertEqual(before, after)

    def test_record_unchanged_after_conversion_with_mutable_meaning(self):
        record = _valid_record(corrected_expression_or_meaning={"text": "dog"})
        before = copy.deepcopy(record.corrected_expression_or_meaning)
        convert_correction_feedback_to_learning_input(record)
        self.assertEqual(record.corrected_expression_or_meaning, before)


class TestNoInformationIsInvented(unittest.TestCase):
    """8. No information is invented during conversion."""

    def test_only_documented_keys_are_present(self):
        record = _valid_record()
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertEqual(
            set(learning_input.keys()),
            {"language", "item_type", "key", "meaning", "confidence",
             "source", "source_context"},
        )

    def test_no_examples_relationships_or_learning_method_are_invented(self):
        record = _valid_record()
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertNotIn("examples", learning_input)
        self.assertNotIn("relationships", learning_input)
        self.assertNotIn("learning_method", learning_input)

    def test_created_at_is_not_carried_into_the_learning_input(self):
        record = _valid_record()
        self.assertEqual(record.created_at, "2026-01-01T00:00:00+00:00")
        learning_input = convert_correction_feedback_to_learning_input(record)
        self.assertNotIn("created_at", learning_input)


if __name__ == "__main__":
    unittest.main()
