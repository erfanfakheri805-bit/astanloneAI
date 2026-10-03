"""
Tests for Prompt 441 - Correction Understanding Result.

`build_correction_understanding_result()` / `CorrectionUnderstandingResult`
(language_intelligence/correction_understanding_result.py) build a small,
compact result from an already-built `CorrectionUnderstanding` (Prompt 439,
language_intelligence/correction_understanding.py). Only:

    1. all valid status values can be represented
    2. all model fields are stored correctly
    3. copying/serialization works (to_dict() round trip)
    4. existing CorrectionUnderstanding (Prompt 439) behavior is unbroken

Run directly:
    python -m unittest tests.test_correction_understanding_result -v
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
    ALL_STATUSES,
)
from language_intelligence.correction_understanding_result import (
    CorrectionUnderstandingResult,
    build_correction_understanding_result,
)


class TestAllValidStatusesCanBeRepresented(unittest.TestCase):
    """1. All valid status values can be represented."""

    def test_all_all_statuses_constructible_directly(self):
        for status in ALL_STATUSES:
            result = CorrectionUnderstandingResult(status, source_text="hello")
            self.assertEqual(result.status, status)

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(ValueError):
            CorrectionUnderstandingResult("NOT_A_REAL_STATUS", source_text="hello")

    def test_all_statuses_reachable_through_the_real_pipeline(self):
        # RESOLVED
        resolved = build_correction_understanding(
            "no I mean dog not dgo", original_expression="dgo",
            corrected_expression="dog", language="en", locale="en-US", confidence=0.9)
        self.assertEqual(
            build_correction_understanding_result(resolved).status, STATUS_RESOLVED)

        # AMBIGUOUS
        ambiguous = build_correction_understanding(
            "not dgo", original_expression="dgo",
            corrected_candidates=["dog", "dig"])
        self.assertEqual(
            build_correction_understanding_result(ambiguous).status, STATUS_AMBIGUOUS)

        # UNRESOLVED
        unresolved = build_correction_understanding(
            "dgo", original_expression="dgo")
        self.assertEqual(
            build_correction_understanding_result(unresolved).status, STATUS_UNRESOLVED)

        # NOT_CORRECTION
        not_correction = build_correction_understanding("hello there")
        self.assertEqual(
            build_correction_understanding_result(not_correction).status,
            STATUS_NOT_CORRECTION)


class TestAllModelFieldsAreStoredCorrectly(unittest.TestCase):
    """2. All model fields are stored correctly."""

    def test_direct_construction_stores_every_field(self):
        result = CorrectionUnderstandingResult(
            status=STATUS_RESOLVED, source_text="not dgo, I mean dog.",
            original_expression="dgo", corrected_expression_or_meaning="dog",
            language="en", locale="en-US", confidence=0.87)
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.source_text, "not dgo, I mean dog.")
        self.assertEqual(result.original_expression, "dgo")
        self.assertEqual(result.corrected_expression_or_meaning, "dog")
        self.assertEqual(result.language, "en")
        self.assertEqual(result.locale, "en-US")
        self.assertEqual(result.confidence, 0.87)

    def test_defaults_are_none_or_zero_when_not_supplied(self):
        result = CorrectionUnderstandingResult(STATUS_NOT_CORRECTION, source_text="hi")
        self.assertIsNone(result.original_expression)
        self.assertIsNone(result.corrected_expression_or_meaning)
        self.assertIsNone(result.language)
        self.assertIsNone(result.locale)
        self.assertEqual(result.confidence, 0.0)

    def test_builder_prefers_corrected_expression_over_meaning(self):
        underlying = build_correction_understanding(
            "src", original_expression="dgo",
            corrected_expression="dog", corrected_meaning="a domestic animal",
            language="en", locale="en-US", confidence=0.5)
        result = build_correction_understanding_result(underlying)
        self.assertEqual(result.corrected_expression_or_meaning, "dog")

    def test_builder_falls_back_to_corrected_meaning_when_no_expression(self):
        underlying = build_correction_understanding(
            "src", original_expression="dgo",
            corrected_meaning="a domestic animal", language="en", confidence=0.5)
        result = build_correction_understanding_result(underlying)
        self.assertEqual(result.corrected_expression_or_meaning, "a domestic animal")

    def test_builder_copies_original_expression_language_locale_source_confidence(self):
        underlying = build_correction_understanding(
            "not dgo, I mean dog.", original_expression="dgo",
            corrected_expression="dog", language="en", locale="en-US", confidence=0.73)
        result = build_correction_understanding_result(underlying)
        self.assertEqual(result.original_expression, "dgo")
        self.assertEqual(result.language, "en")
        self.assertEqual(result.locale, "en-US")
        self.assertEqual(result.source_text, "not dgo, I mean dog.")
        self.assertEqual(result.confidence, 0.73)

    def test_builder_rejects_wrong_type(self):
        with self.assertRaises(TypeError):
            build_correction_understanding_result({"status": STATUS_RESOLVED})


class TestCopyingSerializationWorks(unittest.TestCase):
    """3. Copying/serialization works according to project conventions."""

    def test_to_dict_contains_exactly_the_seven_fields(self):
        result = CorrectionUnderstandingResult(
            status=STATUS_RESOLVED, source_text="src", original_expression="dgo",
            corrected_expression_or_meaning="dog", language="en", locale="en-US",
            confidence=0.6)
        as_dict = result.to_dict()
        self.assertEqual(
            set(as_dict.keys()),
            {"status", "original_expression", "corrected_expression_or_meaning",
             "language", "locale", "source_text", "confidence"})
        self.assertEqual(as_dict["status"], STATUS_RESOLVED)
        self.assertEqual(as_dict["original_expression"], "dgo")
        self.assertEqual(as_dict["corrected_expression_or_meaning"], "dog")
        self.assertEqual(as_dict["language"], "en")
        self.assertEqual(as_dict["locale"], "en-US")
        self.assertEqual(as_dict["source_text"], "src")
        self.assertEqual(as_dict["confidence"], 0.6)

    def test_to_dict_round_trip_reconstructs_an_equal_copy(self):
        original = CorrectionUnderstandingResult(
            status=STATUS_RESOLVED, source_text="src", original_expression="dgo",
            corrected_expression_or_meaning="dog", language="en", locale="en-US",
            confidence=0.6)
        rebuilt = CorrectionUnderstandingResult(**original.to_dict())
        self.assertEqual(rebuilt.to_dict(), original.to_dict())
        # a safe copy - mutating the copy's dict must not affect the original
        copied_dict = original.to_dict()
        copied_dict["status"] = STATUS_NOT_CORRECTION
        self.assertEqual(original.status, STATUS_RESOLVED)

    def test_repr_does_not_raise_and_mentions_status(self):
        result = CorrectionUnderstandingResult(STATUS_NOT_CORRECTION, source_text="hi")
        self.assertIn(STATUS_NOT_CORRECTION, repr(result))


class TestExistingCorrectionUnderstandingBehaviorUnbroken(unittest.TestCase):
    """4. Existing CorrectionUnderstanding (Prompt 439) behavior is not
    broken by this addition."""

    def test_resolved_case_unchanged(self):
        result = build_correction_understanding(
            "no I mean dog not dgo", original_expression="dgo",
            corrected_expression="dog", language="en", locale="en-US", confidence=0.9)
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.original_expression, "dgo")
        self.assertEqual(result.corrected_expression, "dog")
        self.assertIsNone(result.corrected_meaning)

    def test_not_correction_case_unchanged(self):
        result = build_correction_understanding("hello there")
        self.assertEqual(result.status, STATUS_NOT_CORRECTION)
        self.assertIsNone(result.original_expression)

    def test_underlying_to_dict_still_has_its_own_two_fields(self):
        result = build_correction_understanding(
            "src", original_expression="dgo", corrected_expression="dog")
        as_dict = result.to_dict()
        self.assertIn("corrected_expression", as_dict)
        self.assertIn("corrected_meaning", as_dict)
        self.assertNotIn("corrected_expression_or_meaning", as_dict)


if __name__ == "__main__":
    unittest.main()
