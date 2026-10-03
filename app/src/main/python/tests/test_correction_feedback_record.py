"""
Tests for Prompt 449 - Correction Feedback Record.

`map_correction_understanding_result_to_feedback_record()`
(language_intelligence/correction_feedback_record.py) is the one small,
deterministic conversion from an existing `CorrectionUnderstandingResult`
(Prompt 441) to the new `CorrectionFeedbackRecord` (Prompt 449). Only:

    1. a RESOLVED correction creates valid feedback
    2. an AMBIGUOUS correction creates invalid feedback
    3. an UNRESOLVED correction creates invalid feedback
    4. a NOT_CORRECTION result creates invalid feedback
    5. all existing fields are preserved correctly
    6. missing/None values are handled per existing project convention
    7. the original CorrectionUnderstandingResult is not modified

Run directly:
    python -m unittest tests.test_correction_feedback_record -v
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
    STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED, STATUS_NOT_CORRECTION,
)
from language_intelligence.correction_understanding_result import (
    map_correction_understanding_to_result,
)
from language_intelligence.correction_feedback_record import (
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


def _unresolved_result():
    source = build_correction_understanding("dgo", original_expression="dgo")
    return map_correction_understanding_to_result(source)


def _not_correction_result():
    source = build_correction_understanding("hello there")
    return map_correction_understanding_to_result(source)


class TestResolvedCreatesValidFeedback(unittest.TestCase):
    """1. A RESOLVED correction creates valid feedback."""

    def test_resolved_is_valid_feedback(self):
        result = _resolved_result()
        self.assertEqual(result.status, STATUS_RESOLVED)
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertIsInstance(record, CorrectionFeedbackRecord)
        self.assertTrue(record.is_valid_feedback)


class TestAmbiguousCreatesInvalidFeedback(unittest.TestCase):
    """2. An AMBIGUOUS correction creates invalid feedback."""

    def test_ambiguous_is_not_valid_feedback(self):
        result = _ambiguous_result()
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertFalse(record.is_valid_feedback)


class TestUnresolvedCreatesInvalidFeedback(unittest.TestCase):
    """3. An UNRESOLVED correction creates invalid feedback."""

    def test_unresolved_is_not_valid_feedback(self):
        result = _unresolved_result()
        self.assertEqual(result.status, STATUS_UNRESOLVED)
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertFalse(record.is_valid_feedback)


class TestNotCorrectionCreatesInvalidFeedback(unittest.TestCase):
    """4. A NOT_CORRECTION result creates invalid feedback."""

    def test_not_correction_is_not_valid_feedback(self):
        result = _not_correction_result()
        self.assertEqual(result.status, STATUS_NOT_CORRECTION)
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertFalse(record.is_valid_feedback)

    def test_every_non_resolved_status_is_covered_by_this_suite(self):
        # Guards against a new status being added without a matching test.
        from language_intelligence.correction_understanding import ALL_STATUSES
        covered = {STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED, STATUS_NOT_CORRECTION}
        self.assertEqual(covered, set(ALL_STATUSES))


class TestExistingFieldsArePreserved(unittest.TestCase):
    """5. All existing fields are preserved correctly."""

    def test_all_six_shared_fields_preserved_for_resolved(self):
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertEqual(record.original_expression, result.original_expression)
        self.assertEqual(record.corrected_expression_or_meaning,
                          result.corrected_expression_or_meaning)
        self.assertEqual(record.language, result.language)
        self.assertEqual(record.locale, result.locale)
        self.assertEqual(record.source_text, result.source_text)
        self.assertEqual(record.confidence, result.confidence)

    def test_source_text_preserved_verbatim(self):
        raw = "  not dgo,   I mean dog.  "
        source = build_correction_understanding(
            raw, original_expression="dgo", corrected_expression="dog")
        result = map_correction_understanding_to_result(source)
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertEqual(record.source_text, raw)

    def test_to_dict_contains_exactly_the_nine_fields(self):
        # Prompt 451 added `source` (seven -> eight fields) and Prompt 452
        # adds `created_at` (eight -> nine fields); this test reflects
        # the current shape. See tests/test_correction_feedback_record_timestamp.py
        # for the focused created_at coverage.
        result = _resolved_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertEqual(
            set(record.to_dict().keys()),
            {"original_expression", "corrected_expression_or_meaning", "language",
             "locale", "source_text", "confidence", "is_valid_feedback", "source",
             "created_at"})


class TestNoneOptionalValuesHandledPerConvention(unittest.TestCase):
    """6. Missing/None values are handled according to existing project
    convention (never defaulted or invented - copied through as None)."""

    def test_not_correction_record_has_none_fields_except_source_and_confidence(self):
        result = _not_correction_result()
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertIsNone(record.original_expression)
        self.assertIsNone(record.corrected_expression_or_meaning)
        self.assertIsNone(record.language)
        self.assertIsNone(record.locale)
        self.assertEqual(record.confidence, 0.0)

    def test_no_language_or_locale_supplied_maps_to_none_not_a_default_string(self):
        source = build_correction_understanding(
            "not dgo, I mean dog.", original_expression="dgo", corrected_expression="dog")
        result = map_correction_understanding_to_result(source)
        record = map_correction_understanding_result_to_feedback_record(result)
        self.assertIsNone(record.language)
        self.assertIsNone(record.locale)

    def test_rejects_non_correction_understanding_result_input(self):
        with self.assertRaises(TypeError):
            map_correction_understanding_result_to_feedback_record({"status": STATUS_RESOLVED})
        with self.assertRaises(TypeError):
            map_correction_understanding_result_to_feedback_record(None)


class TestOriginalResultIsNotModified(unittest.TestCase):
    """7. The original CorrectionUnderstandingResult is not modified."""

    def test_result_snapshot_unchanged_after_conversion(self):
        result = _resolved_result()
        before = result.to_dict()
        map_correction_understanding_result_to_feedback_record(result)
        after = result.to_dict()
        self.assertEqual(before, after)

    def test_result_equals_its_own_copy_after_conversion(self):
        # Prompt 447/448's __eq__ and copy() give an independent way to
        # confirm the original was never mutated in place.
        result = _resolved_result()
        snapshot = result.copy()
        map_correction_understanding_result_to_feedback_record(result)
        self.assertEqual(result, snapshot)


if __name__ == "__main__":
    unittest.main()
