"""
Tests for Prompt 454 - Correction Feedback Deserialization.

`CorrectionFeedbackRecord.from_dict()` (Prompt 454,
correction_feedback_record.py) reconstructs a record from the dict
`to_dict()` (Prompt 449/453) produces. It is a thin classmethod
wrapper around `__init__`: required fields are taken as given (a
missing one raises `TypeError` from `__init__`'s own required-argument
check), optional fields (`source`, `created_at`) fall back to
`__init__`'s own existing defaults when absent, an unrecognized
`source` still raises `ValueError` exactly as direct construction
already does, and `corrected_expression_or_meaning` - the one field
that can carry mutable, caller-shaped JSON - is deep-copied out of the
input dict so the new record shares no mutable state with it. Only:

    1. a record serialized with to_dict() can be reconstructed with
       from_dict()
    2. all fields are preserved
    3. None values are preserved
    4. mutable nested values, if supported, do not unexpectedly share
       mutable state
    5. invalid/missing required fields are handled according to
       existing project conventions
    6. invalid status/source values are handled according to existing
       conventions
    7. the original dictionary is not mutated
    8. the reconstructed record compares correctly with the original
       using existing equality behavior (this class has no custom
       __eq__, so - same as elsewhere in this package, e.g.
       test_correction_feedback_record_timestamp.py's round-trip
       checks - "compares correctly" means an equal to_dict())

Run directly:
    python -m unittest tests.test_correction_feedback_record_deserialization -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_feedback_record import (
    ALL_SOURCES,
    SOURCE_USER_CORRECTION,
    CorrectionFeedbackRecord,
)

FIXED_CREATED_AT = "2024-01-15T10:30:00+00:00"


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


class TestToDictFromDictRoundTrip(unittest.TestCase):
    """1. A record serialized with to_dict() can be reconstructed with
    from_dict()."""

    def test_from_dict_of_to_dict_returns_a_record(self):
        record = _record()
        rebuilt = CorrectionFeedbackRecord.from_dict(record.to_dict())
        self.assertIsInstance(rebuilt, CorrectionFeedbackRecord)

    def test_round_trip_is_stable_across_multiple_conversions(self):
        record = _record()
        once = CorrectionFeedbackRecord.from_dict(record.to_dict())
        twice = CorrectionFeedbackRecord.from_dict(once.to_dict())
        self.assertEqual(once.to_dict(), twice.to_dict())


class TestAllFieldsArePreserved(unittest.TestCase):
    """2. All fields are preserved."""

    def test_every_field_matches_after_round_trip(self):
        record = _record()
        rebuilt = CorrectionFeedbackRecord.from_dict(record.to_dict())
        self.assertEqual(rebuilt.original_expression, record.original_expression)
        self.assertEqual(rebuilt.corrected_expression_or_meaning,
                          record.corrected_expression_or_meaning)
        self.assertEqual(rebuilt.language, record.language)
        self.assertEqual(rebuilt.locale, record.locale)
        self.assertEqual(rebuilt.source_text, record.source_text)
        self.assertEqual(rebuilt.confidence, record.confidence)
        self.assertEqual(rebuilt.is_valid_feedback, record.is_valid_feedback)
        self.assertEqual(rebuilt.source, record.source)
        self.assertEqual(rebuilt.created_at, record.created_at)

    def test_nested_mutable_correction_value_preserved(self):
        nested = {"candidates": ["dog", "dig"]}
        record = _record(corrected_expression_or_meaning=nested)
        rebuilt = CorrectionFeedbackRecord.from_dict(record.to_dict())
        self.assertEqual(rebuilt.corrected_expression_or_meaning, nested)


class TestNoneValuesArePreserved(unittest.TestCase):
    """3. None values are preserved."""

    def test_none_optional_correction_fields_stay_none(self):
        record = _record(
            original_expression=None, corrected_expression_or_meaning=None,
            language=None, locale=None)
        rebuilt = CorrectionFeedbackRecord.from_dict(record.to_dict())
        self.assertIsNone(rebuilt.original_expression)
        self.assertIsNone(rebuilt.corrected_expression_or_meaning)
        self.assertIsNone(rebuilt.language)
        self.assertIsNone(rebuilt.locale)

    def test_missing_created_at_key_defaults_same_as_direct_construction(self):
        data = _record().to_dict()
        del data["created_at"]
        rebuilt = CorrectionFeedbackRecord.from_dict(data)
        self.assertIsNotNone(rebuilt.created_at)

    def test_missing_source_key_defaults_to_user_correction(self):
        data = _record().to_dict()
        del data["source"]
        rebuilt = CorrectionFeedbackRecord.from_dict(data)
        self.assertEqual(rebuilt.source, SOURCE_USER_CORRECTION)


class TestMutableNestedValuesDoNotUnexpectedlyShareState(unittest.TestCase):
    """4. Mutable nested values, if supported, do not unexpectedly
    share mutable state."""

    def test_mutating_source_dict_after_from_dict_does_not_affect_record(self):
        nested = {"candidates": ["dog", "dig"]}
        record = _record(corrected_expression_or_meaning=nested)
        data = record.to_dict()
        rebuilt = CorrectionFeedbackRecord.from_dict(data)
        data["corrected_expression_or_meaning"]["candidates"].append("dug")
        self.assertEqual(rebuilt.corrected_expression_or_meaning,
                          {"candidates": ["dog", "dig"]})

    def test_mutating_rebuilt_record_does_not_affect_source_dict(self):
        nested = {"candidates": ["dog", "dig"]}
        record = _record(corrected_expression_or_meaning=nested)
        data = record.to_dict()
        rebuilt = CorrectionFeedbackRecord.from_dict(data)
        rebuilt.corrected_expression_or_meaning["candidates"].append("dug")
        self.assertEqual(data["corrected_expression_or_meaning"],
                          {"candidates": ["dog", "dig"]})

    def test_two_from_dict_calls_on_same_data_return_independent_objects(self):
        nested = {"candidates": ["dog", "dig"]}
        data = _record(corrected_expression_or_meaning=nested).to_dict()
        first = CorrectionFeedbackRecord.from_dict(data)
        second = CorrectionFeedbackRecord.from_dict(data)
        self.assertIsNot(
            first.corrected_expression_or_meaning,
            second.corrected_expression_or_meaning)


class TestInvalidOrMissingRequiredFieldsHandledPerConvention(unittest.TestCase):
    """5. Invalid/missing required fields are handled according to
    existing project conventions (a required __init__ argument with no
    default raises TypeError when omitted - the same failure any other
    caller omitting it would already get)."""

    def test_missing_required_field_raises_type_error(self):
        data = _record().to_dict()
        del data["source_text"]
        with self.assertRaises(TypeError):
            CorrectionFeedbackRecord.from_dict(data)

    def test_missing_confidence_raises_type_error(self):
        data = _record().to_dict()
        del data["confidence"]
        with self.assertRaises(TypeError):
            CorrectionFeedbackRecord.from_dict(data)

    def test_non_dict_input_raises_type_error(self):
        with self.assertRaises(TypeError):
            CorrectionFeedbackRecord.from_dict(None)
        with self.assertRaises(TypeError):
            CorrectionFeedbackRecord.from_dict(["not", "a", "dict"])

    def test_no_default_is_invented_for_a_missing_required_field(self):
        data = _record().to_dict()
        del data["language"]
        # language has no constructor default of its own, so it must
        # raise rather than silently becoming None/invented.
        with self.assertRaises(TypeError):
            CorrectionFeedbackRecord.from_dict(data)


class TestInvalidSourceHandledPerConvention(unittest.TestCase):
    """6. Invalid status/source values are handled according to
    existing conventions (an unrecognized source raises ValueError
    from __init__, same as direct construction, Prompt 451)."""

    def test_unknown_source_raises_value_error(self):
        data = _record().to_dict()
        data["source"] = "NOT_A_REAL_SOURCE"
        with self.assertRaises(ValueError):
            CorrectionFeedbackRecord.from_dict(data)

    def test_known_source_is_accepted(self):
        data = _record().to_dict()
        data["source"] = SOURCE_USER_CORRECTION
        rebuilt = CorrectionFeedbackRecord.from_dict(data)
        self.assertIn(rebuilt.source, ALL_SOURCES)


class TestOriginalDictionaryIsNotMutated(unittest.TestCase):
    """7. The original dictionary is not mutated."""

    def test_input_dict_unchanged_after_from_dict(self):
        nested = {"candidates": ["dog", "dig"]}
        record = _record(corrected_expression_or_meaning=nested)
        data = record.to_dict()
        before = dict(data)
        CorrectionFeedbackRecord.from_dict(data)
        self.assertEqual(data, before)

    def test_input_dict_keys_unchanged_after_missing_optional_field(self):
        data = _record().to_dict()
        del data["source"]
        before_keys = set(data.keys())
        CorrectionFeedbackRecord.from_dict(data)
        self.assertEqual(set(data.keys()), before_keys)


class TestReconstructedRecordComparesCorrectly(unittest.TestCase):
    """8. The reconstructed record compares correctly with the
    original using existing equality behavior. CorrectionFeedbackRecord
    defines no custom __eq__, so - same convention already used for
    this record elsewhere in this package (e.g.
    test_correction_feedback_record_timestamp.py's round-trip checks) -
    "compares correctly" is checked via to_dict() equality."""

    def test_rebuilt_record_to_dict_equals_original_to_dict(self):
        record = _record()
        rebuilt = CorrectionFeedbackRecord.from_dict(record.to_dict())
        self.assertEqual(rebuilt.to_dict(), record.to_dict())

    def test_records_without_custom_eq_are_not_equal_by_identity(self):
        # Documents the actual existing behavior: no __eq__ is defined
        # on this class, so distinct instances are never `==` to each
        # other even with identical fields - only their to_dict()s are
        # compared, as in every test above.
        record = _record()
        rebuilt = CorrectionFeedbackRecord.from_dict(record.to_dict())
        self.assertFalse(record == rebuilt)
        self.assertIsNot(record, rebuilt)


if __name__ == "__main__":
    unittest.main()
