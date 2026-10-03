"""
Tests for Prompt 452 - Correction Feedback Timestamp.

Adds one small, deterministic-apart-from-the-clock field, `created_at`,
to the existing `CorrectionFeedbackRecord` (Prompt 449,
correction_feedback_record.py), following the project's existing
timestamp convention already used in `planning/plan.py`,
`planning/goal.py`, `financial/revenue_task.py` and
`language_intelligence/language_learning_store.py`: an ISO 8601 string
in UTC via `_now_iso()` (`datetime.now(timezone.utc).isoformat()`),
defaulted at construction time when not supplied, and included in
`to_dict()`. Only:

    1. a newly created feedback record contains a valid created_at
    2. the timestamp follows the project's existing format/convention
    3. the timestamp is preserved when the record is copied (via the
       existing to_dict() copy convention this project already uses -
       CorrectionFeedbackRecord has no separate copy() method)
    4. existing source behavior remains unchanged
    5. existing is_valid_feedback behavior remains unchanged
    6. existing correction fields remain unchanged
    7. the original CorrectionUnderstandingResult is not modified

Fixed/explicit timestamps are used wherever possible instead of
real-time assertions, to keep the suite deterministic.

Run directly:
    python -m unittest tests.test_correction_feedback_record_timestamp -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_understanding import (
    build_correction_understanding,
    STATUS_RESOLVED, STATUS_AMBIGUOUS,
)
from language_intelligence.correction_understanding_result import (
    map_correction_understanding_to_result,
)
from language_intelligence.correction_feedback_record import (
    SOURCE_USER_CORRECTION,
    CorrectionFeedbackRecord,
    map_correction_understanding_result_to_feedback_record,
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


FIXED_CREATED_AT = "2024-01-15T10:30:00+00:00"


class TestNewRecordHasValidCreatedAt(unittest.TestCase):
    """1. A newly created feedback record contains a valid created_at."""

    def test_conversion_sets_a_created_at(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertIsNotNone(record.created_at)
        self.assertIsInstance(record.created_at, str)

    def test_direct_construction_defaults_created_at_when_omitted(self):
        record = CorrectionFeedbackRecord(
            original_expression="dgo", corrected_expression_or_meaning="dog",
            language="en", locale="en-US", source_text="not dgo, dog",
            confidence=0.9, is_valid_feedback=True)
        self.assertIsNotNone(record.created_at)

    def test_explicit_created_at_is_used_as_is(self):
        record = CorrectionFeedbackRecord(
            original_expression="dgo", corrected_expression_or_meaning="dog",
            language="en", locale="en-US", source_text="not dgo, dog",
            confidence=0.9, is_valid_feedback=True, created_at=FIXED_CREATED_AT)
        self.assertEqual(record.created_at, FIXED_CREATED_AT)

    def test_conversion_accepts_explicit_created_at_for_determinism(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(
            result, created_at=FIXED_CREATED_AT)
        self.assertEqual(record.created_at, FIXED_CREATED_AT)


class TestCreatedAtFollowsProjectConvention(unittest.TestCase):
    """2. The timestamp follows the project's existing format/convention
    (ISO 8601, UTC - same shape as planning/plan.py, planning/goal.py,
    financial/revenue_task.py and
    language_intelligence/language_learning_store.py)."""

    def test_default_created_at_parses_as_iso8601_utc(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        parsed = datetime.fromisoformat(record.created_at)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_default_created_at_is_close_to_now(self):
        before = datetime.now(timezone.utc)
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        after = datetime.now(timezone.utc)
        parsed = datetime.fromisoformat(record.created_at)
        self.assertLessEqual(before, parsed)
        self.assertLessEqual(parsed, after)

    def test_created_at_is_present_in_to_dict(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(
            result, created_at=FIXED_CREATED_AT)
        self.assertEqual(record.to_dict()["created_at"], FIXED_CREATED_AT)

    def test_to_dict_contains_exactly_the_nine_fields(self):
        # Prompt 452 adds `created_at` to the record; this count
        # intentionally grew from eight to nine.
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertEqual(
            set(record.to_dict().keys()),
            {"original_expression", "corrected_expression_or_meaning", "language",
             "locale", "source_text", "confidence", "is_valid_feedback", "source",
             "created_at"})


class TestCreatedAtPreservedWhenCopyingRecord(unittest.TestCase):
    """3. The timestamp is preserved when the record is copied - via the
    existing to_dict() copy convention this project already uses, and
    via Python's generic copy support (CorrectionFeedbackRecord has no
    separate copy() method of its own)."""

    def test_created_at_survives_to_dict_round_trip(self):
        record = CorrectionFeedbackRecord(
            original_expression="dgo", corrected_expression_or_meaning="dog",
            language="en", locale="en-US", source_text="not dgo, dog",
            confidence=0.9, is_valid_feedback=True, created_at=FIXED_CREATED_AT)
        copied = CorrectionFeedbackRecord(**record.to_dict())
        self.assertEqual(copied.created_at, record.created_at)

    def test_created_at_survives_deepcopy(self):
        record = CorrectionFeedbackRecord(
            original_expression="dgo", corrected_expression_or_meaning="dog",
            language="en", locale="en-US", source_text="not dgo, dog",
            confidence=0.9, is_valid_feedback=True, created_at=FIXED_CREATED_AT)
        cloned = copy.deepcopy(record)
        self.assertEqual(cloned.created_at, FIXED_CREATED_AT)


class TestExistingSourceBehaviorUnchanged(unittest.TestCase):
    """4. Existing source behavior remains unchanged."""

    def test_resolved_result_still_maps_to_user_correction_source(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertEqual(record.source, SOURCE_USER_CORRECTION)

    def test_source_still_defaults_when_constructed_directly(self):
        record = CorrectionFeedbackRecord(
            original_expression="dgo", corrected_expression_or_meaning="dog",
            language="en", locale="en-US", source_text="not dgo, dog",
            confidence=0.9, is_valid_feedback=True)
        self.assertEqual(record.source, SOURCE_USER_CORRECTION)


class TestExistingIsValidFeedbackBehaviorUnchanged(unittest.TestCase):
    """5. Existing is_valid_feedback behavior remains unchanged."""

    def test_resolved_is_still_valid_feedback(self):
        result = _resolved_result()
        self.assertEqual(result.status, STATUS_RESOLVED)
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertTrue(record.is_valid_feedback)

    def test_ambiguous_is_still_not_valid_feedback(self):
        result = _ambiguous_result()
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertFalse(record.is_valid_feedback)


class TestExistingCorrectionFieldsUnchanged(unittest.TestCase):
    """6. Existing correction fields remain unchanged."""

    def test_all_six_shared_fields_still_preserved(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertEqual(record.original_expression, result.original_expression)
        self.assertEqual(record.corrected_expression_or_meaning,
                          result.corrected_expression_or_meaning)
        self.assertEqual(record.language, result.language)
        self.assertEqual(record.locale, result.locale)
        self.assertEqual(record.source_text, result.source_text)
        self.assertEqual(record.confidence, result.confidence)


class TestOriginalResultIsNotModified(unittest.TestCase):
    """7. The original CorrectionUnderstandingResult is not modified."""

    def test_result_snapshot_unchanged_after_conversion(self):
        result = _resolved_result()
        before = result.to_dict()
        map_correction_understanding_result_to_feedback_record(result)
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_result_equals_its_own_copy_after_conversion(self):
        result = _resolved_result()
        snapshot = result.copy()
        map_correction_understanding_result_to_feedback_record(result)
        self.assertEqual(result, snapshot)

    def test_result_has_no_created_at_attribute(self):
        # created_at belongs only to CorrectionFeedbackRecord (Prompt
        # 452); CorrectionUnderstandingResult is untouched by this stage.
        result = _resolved_result()
        self.assertFalse(hasattr(result, "created_at"))


if __name__ == "__main__":
    unittest.main()
