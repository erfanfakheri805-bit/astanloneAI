"""
Tests for Prompt 451 - Correction Feedback Source.

Adds one small, deterministic field, `source`, to the existing
`CorrectionFeedbackRecord` (Prompt 449, correction_feedback_record.py).
For this stage there is exactly one valid value, `SOURCE_USER_CORRECTION`
("USER_CORRECTION"), and a record built from a `CorrectionUnderstandingResult`
via `map_correction_understanding_result_to_feedback_record()` always
gets that source. Only:

    1. a feedback record created from a correction result has
       source SOURCE_USER_CORRECTION
    2. the source is preserved when copying the record (via the
       existing to_dict() copy convention this project already uses)
    3. existing is_valid_feedback behavior remains unchanged
    4. existing fields remain unchanged
    5. invalid/unexpected source values are handled per the project's
       existing convention (reject at construction time; validation
       reports ISSUE_UNKNOWN_SOURCE for a record that already carries
       one, mirroring ISSUE_UNKNOWN_STATUS in
       correction_understanding_result_validation.py)
    6. the original CorrectionUnderstandingResult is not modified

Run directly:
    python -m unittest tests.test_correction_feedback_record_source -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_understanding import (
    build_correction_understanding,
    STATUS_RESOLVED, STATUS_AMBIGUOUS,
)
from language_intelligence.correction_understanding_result import (
    map_correction_understanding_to_result,
)
from language_intelligence.correction_feedback_record import (
    ALL_SOURCES,
    SOURCE_USER_CORRECTION,
    CorrectionFeedbackRecord,
    map_correction_understanding_result_to_feedback_record,
)
from language_intelligence.correction_feedback_record_validation import (
    VALIDATION_VALID, VALIDATION_INVALID,
    ISSUE_UNKNOWN_SOURCE,
    validate_correction_feedback_record,
)


def _resolved_result():
    source = build_correction_understanding(
        "no I mean dog not dgo", original_expression="dgo",
        corrected_expression="dog", language="en", locale="en-US", confidence=0.9)
    return map_correction_understanding_to_result(source)


def _ambiguous_result():
    source = build_correction_understanding(
        "not dgo", original_expression="dgo",
        corrected_candidates=["dog", "dig"])
    return map_correction_understanding_to_result(source)


class TestRecordFromCorrectionResultHasUserCorrectionSource(unittest.TestCase):
    """1. A feedback record created from a correction result has
    source SOURCE_USER_CORRECTION."""

    def test_resolved_result_maps_to_user_correction_source(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertEqual(record.source, SOURCE_USER_CORRECTION)

    def test_non_resolved_result_still_maps_to_user_correction_source(self):
        # source identifies where the feedback came from, not whether it
        # is valid feedback - an AMBIGUOUS result still came from the
        # user's own correction attempt.
        result = _ambiguous_result()
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertEqual(record.source, SOURCE_USER_CORRECTION)

    def test_all_sources_holds_exactly_one_value_for_this_stage(self):
        self.assertEqual(ALL_SOURCES, (SOURCE_USER_CORRECTION,))


class TestSourcePreservedWhenCopyingRecord(unittest.TestCase):
    """2. The source is preserved when copying the record - via this
    project's existing to_dict() copy convention (CorrectionFeedbackRecord
    has no separate copy() method, so to_dict()/reconstruction is the
    supported way to make an independent copy, same as
    CorrectionFeedbackRecordValidation.record already does)."""

    def test_source_survives_to_dict_round_trip(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        copied = CorrectionFeedbackRecord(**record.to_dict())
        self.assertEqual(copied.source, record.source)

    def test_source_present_in_validation_record_copy(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.record["source"], SOURCE_USER_CORRECTION)


class TestExistingIsValidFeedbackBehaviorUnchanged(unittest.TestCase):
    """3. Existing is_valid_feedback behavior remains unchanged."""

    def test_resolved_is_still_valid_feedback(self):
        result = _resolved_result()
        self.assertEqual(result.status, STATUS_RESOLVED)
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertTrue(record.is_valid_feedback)

    def test_ambiguous_is_still_not_valid_feedback(self):
        result = _ambiguous_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertFalse(record.is_valid_feedback)

    def test_is_valid_feedback_still_coerced_to_bool(self):
        record = CorrectionFeedbackRecord(
            original_expression="dgo", corrected_expression_or_meaning="dog",
            language="en", locale="en-US", source_text="src", confidence=0.5,
            is_valid_feedback=1)
        self.assertIsInstance(record.is_valid_feedback, bool)
        self.assertTrue(record.is_valid_feedback)


class TestExistingFieldsUnchanged(unittest.TestCase):
    """4. Existing fields remain unchanged."""

    def test_seven_original_fields_still_preserved(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertEqual(record.original_expression, result.original_expression)
        self.assertEqual(record.corrected_expression_or_meaning,
                          result.corrected_expression_or_meaning)
        self.assertEqual(record.language, result.language)
        self.assertEqual(record.locale, result.locale)
        self.assertEqual(record.source_text, result.source_text)
        self.assertEqual(record.confidence, result.confidence)

    def test_to_dict_contains_exactly_the_nine_fields(self):
        # Prompt 452 adds `created_at`, so this count grew from eight to
        # nine; see tests/test_correction_feedback_record_timestamp.py
        # for the focused created_at coverage.
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertEqual(
            set(record.to_dict().keys()),
            {"original_expression", "corrected_expression_or_meaning", "language",
             "locale", "source_text", "confidence", "is_valid_feedback", "source",
             "created_at"})

    def test_existing_construction_without_source_still_works(self):
        # Backward compatibility: callers that only pass the original
        # seven arguments still get a valid record, defaulted to
        # SOURCE_USER_CORRECTION.
        record = CorrectionFeedbackRecord(
            original_expression="dgo", corrected_expression_or_meaning="dog",
            language="en", locale="en-US", source_text="src", confidence=0.5,
            is_valid_feedback=True)
        self.assertEqual(record.source, SOURCE_USER_CORRECTION)


class TestInvalidSourceValuesHandledPerConvention(unittest.TestCase):
    """5. Invalid or unexpected source values are handled according to
    the project's existing conventions: rejected with ValueError at
    construction time (same posture as CorrectionUnderstandingResult's
    own status check), and reported as ISSUE_UNKNOWN_SOURCE by
    validation for a record that already carries one."""

    def test_constructing_with_unknown_source_raises_value_error(self):
        with self.assertRaises(ValueError):
            CorrectionFeedbackRecord(
                original_expression="dgo", corrected_expression_or_meaning="dog",
                language="en", locale="en-US", source_text="src", confidence=0.5,
                is_valid_feedback=True, source="SOMETHING_ELSE")

    def test_validation_reports_unknown_source_for_tampered_record(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        record.source = "TOTALLY_MADE_UP"
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.status, VALIDATION_INVALID)
        self.assertIn(ISSUE_UNKNOWN_SOURCE, validation.issue_codes)

    def test_valid_source_still_passes_validation(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        validation = validate_correction_feedback_record(record)
        self.assertEqual(validation.status, VALIDATION_VALID)


class TestOriginalCorrectionResultNotModified(unittest.TestCase):
    """6. The original CorrectionUnderstandingResult is not modified."""

    def test_result_snapshot_unchanged_after_conversion(self):
        result = _resolved_result()
        before = result.to_dict()
        map_correction_understanding_result_to_feedback_record(result)
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_result_has_no_source_attribute_added(self):
        # `source` belongs to CorrectionFeedbackRecord only - the
        # CorrectionUnderstandingResult it was built from is untouched
        # and never gains a source attribute of its own.
        result = _resolved_result()
        map_correction_understanding_result_to_feedback_record(result)
        self.assertFalse(hasattr(result, "source"))


if __name__ == "__main__":
    unittest.main()
