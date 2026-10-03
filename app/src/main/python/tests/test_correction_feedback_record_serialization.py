"""
Tests for Prompt 453 - Correction Feedback Serialization.

`CorrectionFeedbackRecord.to_dict()` (Prompt 449,
correction_feedback_record.py) already returned all nine current
fields; Prompt 453 only hardens it to apply this project's existing
"mutable fields get a safe copy" convention
(`CorrectionUnderstandingResult.copy()`, Prompt 448) to
`corrected_expression_or_meaning` - the one field that can carry a
mutable, caller-shaped JSON value. Only:

    1. to_dict() contains all current fields
    2. all field values are preserved correctly
    3. None values are preserved correctly
    4. mutable nested values, if supported, do not cause unintended
       mutation of the original record
    5. calling to_dict() does not modify the original record
    6. source and created_at are serialized correctly
    7. is_valid_feedback is serialized as the correct boolean value

Run directly:
    python -m unittest tests.test_correction_feedback_record_serialization -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_feedback_record import (
    SOURCE_USER_CORRECTION,
    CorrectionFeedbackRecord,
)

FIXED_CREATED_AT = "2024-01-15T10:30:00+00:00"

ALL_FIELD_NAMES = {
    "original_expression", "corrected_expression_or_meaning", "language",
    "locale", "source_text", "confidence", "is_valid_feedback", "source",
    "created_at",
}


def _record(**overrides):
    kwargs = dict(
        original_expression="dgo",
        corrected_expression_or_meaning="dog",
        language="en",
        locale="en-US",
        source_text="not dgo, I mean dog",
        confidence=0.9,
        is_valid_feedback=True,
        source=SOURCE_USER_CORRECTION,
        created_at=FIXED_CREATED_AT,
    )
    kwargs.update(overrides)
    return CorrectionFeedbackRecord(**kwargs)


class TestToDictContainsAllCurrentFields(unittest.TestCase):
    """1. to_dict() contains all current fields."""

    def test_to_dict_keys_match_exactly_the_nine_current_fields(self):
        record = _record()
        self.assertEqual(set(record.to_dict().keys()), ALL_FIELD_NAMES)

    def test_to_dict_returns_a_plain_dict(self):
        record = _record()
        self.assertIsInstance(record.to_dict(), dict)


class TestAllFieldValuesArePreservedCorrectly(unittest.TestCase):
    """2. All field values are preserved correctly."""

    def test_scalar_fields_round_trip_unchanged(self):
        record = _record()
        data = record.to_dict()
        self.assertEqual(data["original_expression"], "dgo")
        self.assertEqual(data["corrected_expression_or_meaning"], "dog")
        self.assertEqual(data["language"], "en")
        self.assertEqual(data["locale"], "en-US")
        self.assertEqual(data["source_text"], "not dgo, I mean dog")
        self.assertEqual(data["confidence"], 0.9)

    def test_dict_can_reconstruct_an_equal_record(self):
        record = _record()
        rebuilt = CorrectionFeedbackRecord(**record.to_dict())
        self.assertEqual(rebuilt.to_dict(), record.to_dict())


class TestNoneValuesArePreservedCorrectly(unittest.TestCase):
    """3. None values are preserved correctly."""

    def test_none_optional_fields_stay_none_in_to_dict(self):
        record = _record(
            original_expression=None, corrected_expression_or_meaning=None,
            language=None, locale=None)
        data = record.to_dict()
        self.assertIsNone(data["original_expression"])
        self.assertIsNone(data["corrected_expression_or_meaning"])
        self.assertIsNone(data["language"])
        self.assertIsNone(data["locale"])

    def test_none_is_not_replaced_with_a_default_or_placeholder(self):
        record = _record(language=None)
        self.assertNotIn(record.to_dict()["language"], ("", "unknown"))
        self.assertIsNone(record.to_dict()["language"])


class TestMutableNestedValuesDoNotCauseUnintendedMutation(unittest.TestCase):
    """4. Mutable nested values, if supported, do not cause unintended
    mutation of the original record."""

    def test_mutating_returned_dict_value_does_not_affect_record(self):
        nested = {"candidates": ["dog", "dig"]}
        record = _record(corrected_expression_or_meaning=nested)
        data = record.to_dict()
        data["corrected_expression_or_meaning"]["candidates"].append("dug")
        self.assertEqual(
            record.corrected_expression_or_meaning, {"candidates": ["dog", "dig"]})

    def test_two_calls_to_to_dict_return_independent_copies(self):
        nested = {"candidates": ["dog", "dig"]}
        record = _record(corrected_expression_or_meaning=nested)
        first = record.to_dict()
        second = record.to_dict()
        first["corrected_expression_or_meaning"]["candidates"].append("dug")
        self.assertEqual(second["corrected_expression_or_meaning"],
                          {"candidates": ["dog", "dig"]})
        self.assertIsNot(
            first["corrected_expression_or_meaning"],
            second["corrected_expression_or_meaning"])

    def test_to_dict_value_is_independent_of_the_stored_attribute(self):
        nested = {"candidates": ["dog", "dig"]}
        record = _record(corrected_expression_or_meaning=nested)
        data = record.to_dict()
        self.assertIsNot(
            data["corrected_expression_or_meaning"],
            record.corrected_expression_or_meaning)
        data["corrected_expression_or_meaning"]["candidates"].append("dug")
        self.assertEqual(
            record.corrected_expression_or_meaning, {"candidates": ["dog", "dig"]})


class TestToDictDoesNotModifyTheOriginalRecord(unittest.TestCase):
    """5. Calling to_dict() does not modify the original record."""

    def test_record_fields_unchanged_after_to_dict(self):
        record = _record()
        before = (
            record.original_expression, record.corrected_expression_or_meaning,
            record.language, record.locale, record.source_text,
            record.confidence, record.is_valid_feedback, record.source,
            record.created_at,
        )
        record.to_dict()
        after = (
            record.original_expression, record.corrected_expression_or_meaning,
            record.language, record.locale, record.source_text,
            record.confidence, record.is_valid_feedback, record.source,
            record.created_at,
        )
        self.assertEqual(before, after)

    def test_repeated_calls_are_stable(self):
        record = _record()
        self.assertEqual(record.to_dict(), record.to_dict())


class TestSourceAndCreatedAtSerializedCorrectly(unittest.TestCase):
    """6. source and created_at are serialized correctly."""

    def test_source_is_serialized_as_is(self):
        record = _record(source=SOURCE_USER_CORRECTION)
        self.assertEqual(record.to_dict()["source"], SOURCE_USER_CORRECTION)

    def test_created_at_is_serialized_as_is(self):
        record = _record(created_at=FIXED_CREATED_AT)
        self.assertEqual(record.to_dict()["created_at"], FIXED_CREATED_AT)


class TestIsValidFeedbackSerializedAsCorrectBoolean(unittest.TestCase):
    """7. is_valid_feedback is serialized as the correct boolean value."""

    def test_true_is_valid_feedback_serializes_as_true(self):
        record = _record(is_valid_feedback=True)
        data = record.to_dict()
        self.assertIs(data["is_valid_feedback"], True)

    def test_false_is_valid_feedback_serializes_as_false(self):
        record = _record(is_valid_feedback=False)
        data = record.to_dict()
        self.assertIs(data["is_valid_feedback"], False)

    def test_truthy_non_bool_input_is_coerced_to_bool_in_to_dict(self):
        # CorrectionFeedbackRecord.__init__ already coerces
        # is_valid_feedback with bool(); to_dict() must reflect that
        # coerced value, not the original truthy input.
        record = _record(is_valid_feedback=1)
        self.assertIs(record.to_dict()["is_valid_feedback"], True)


if __name__ == "__main__":
    unittest.main()
