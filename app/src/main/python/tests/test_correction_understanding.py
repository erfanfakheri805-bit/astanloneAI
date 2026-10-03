"""
Tests for Prompt 439 - Explicit Correction Structure.

`build_correction_understanding()` / `CorrectionUnderstandingResult`
(language_intelligence/correction_understanding.py) turn already-identified
correction pieces (an original expression and a corrected expression/
meaning) into one small, deterministic, JSON-shaped result. This module is
pure: no memory, no language-learning store, no other language-intelligence
system is touched or imported.

Run directly:
    python -m unittest tests.test_correction_understanding -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_understanding import (
    build_correction_understanding, CorrectionUnderstandingResult,
    STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED, STATUS_NOT_CORRECTION,
    ALL_STATUSES,
)


class TestValidResolvedCorrection(unittest.TestCase):
    """1. Valid resolved correction."""

    def test_original_and_corrected_expression_resolves(self):
        result = build_correction_understanding(
            "no I mean dog not dgo", original_expression="dgo",
            corrected_expression="dog", language="en", locale="en-US", confidence=0.9)
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.original_expression, "dgo")
        self.assertEqual(result.corrected_expression, "dog")
        self.assertIsNone(result.corrected_meaning)
        self.assertEqual(result.confidence, 0.9)

    def test_original_and_corrected_meaning_resolves(self):
        result = build_correction_understanding(
            "actually I meant something else", original_expression="hello",
            corrected_meaning={"gloss": "goodbye"}, language="en")
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.corrected_meaning, {"gloss": "goodbye"})
        self.assertIsNone(result.corrected_expression)

    def test_to_dict_carries_exactly_the_minimum_fields(self):
        result = build_correction_understanding(
            "no I mean dog not dgo", original_expression="dgo",
            corrected_expression="dog", language="en", locale="en-US", confidence=0.9)
        self.assertEqual(
            set(result.to_dict().keys()),
            {"status", "original_expression", "corrected_expression", "corrected_meaning",
             "language", "locale", "source_text", "confidence"})


class TestNonCorrection(unittest.TestCase):
    """2. Non-correction."""

    def test_nothing_supplied_is_not_correction(self):
        result = build_correction_understanding("what time is it")
        self.assertEqual(result.status, STATUS_NOT_CORRECTION)
        self.assertIsNone(result.original_expression)
        self.assertIsNone(result.corrected_expression)
        self.assertIsNone(result.corrected_meaning)

    def test_blank_pieces_are_treated_as_not_supplied(self):
        result = build_correction_understanding(
            "hello there", original_expression="   ", corrected_expression="")
        self.assertEqual(result.status, STATUS_NOT_CORRECTION)


class TestAmbiguousCorrection(unittest.TestCase):
    """3. Ambiguous correction."""

    def test_multiple_candidates_is_ambiguous(self):
        result = build_correction_understanding(
            "no not that", original_expression="that",
            corrected_candidates=["this", "it", "the other one"], language="en")
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertEqual(result.original_expression, "that")
        self.assertIsNone(result.corrected_expression)
        self.assertIsNone(result.corrected_meaning)

    def test_duplicate_candidates_do_not_count_twice(self):
        result = build_correction_understanding(
            "no not that", corrected_candidates=["this", "this", "  this  "])
        # only one distinct candidate after de-duplication -> not ambiguous
        self.assertNotEqual(result.status, STATUS_AMBIGUOUS)


class TestUnresolvedCorrection(unittest.TestCase):
    """4. Unresolved correction."""

    def test_only_original_expression_is_unresolved(self):
        result = build_correction_understanding(
            "dgo", original_expression="dgo", language="en")
        self.assertEqual(result.status, STATUS_UNRESOLVED)
        self.assertEqual(result.original_expression, "dgo")
        self.assertIsNone(result.corrected_expression)

    def test_only_corrected_expression_is_unresolved(self):
        result = build_correction_understanding(
            "I mean dog", corrected_expression="dog")
        self.assertEqual(result.status, STATUS_UNRESOLVED)
        self.assertIsNone(result.original_expression)
        self.assertEqual(result.corrected_expression, "dog")

    def test_single_candidate_with_nothing_else_is_unresolved(self):
        result = build_correction_understanding(
            "no not that", corrected_candidates=["this"])
        self.assertEqual(result.status, STATUS_UNRESOLVED)


class TestOriginalTextPreservation(unittest.TestCase):
    """5. Original text preservation."""

    def test_source_text_preserved_exactly(self):
        raw = "  no I mean   dog not dgo!!  "
        result = build_correction_understanding(
            raw, original_expression="dgo", corrected_expression="dog")
        self.assertEqual(result.source_text, raw)

    def test_original_expression_preserved_exactly_not_normalized(self):
        result = build_correction_understanding(
            "no I mean Dog not  DGO ", original_expression="  DGO ",
            corrected_expression="Dog")
        self.assertEqual(result.original_expression, "  DGO ")
        self.assertEqual(result.corrected_expression, "Dog")


class TestLanguagePreservation(unittest.TestCase):
    """6. Language preservation."""

    def test_language_preserved_exactly(self):
        result = build_correction_understanding(
            "no I mean dog", original_expression="dgo", corrected_expression="dog",
            language="persian")
        self.assertEqual(result.language, "persian")

    def test_language_none_when_not_supplied(self):
        result = build_correction_understanding(
            "no I mean dog", original_expression="dgo", corrected_expression="dog")
        self.assertIsNone(result.language)


class TestLocalePreservation(unittest.TestCase):
    """7. Locale preservation."""

    def test_locale_preserved_exactly(self):
        result = build_correction_understanding(
            "no I mean dog", original_expression="dgo", corrected_expression="dog",
            language="en", locale="en-GB")
        self.assertEqual(result.locale, "en-GB")

    def test_locale_none_when_not_supplied(self):
        result = build_correction_understanding(
            "no I mean dog", original_expression="dgo", corrected_expression="dog")
        self.assertIsNone(result.locale)


class TestDeterministicRepeatedResult(unittest.TestCase):
    """8. Deterministic repeated result."""

    def test_same_arguments_produce_equal_results_every_time(self):
        kwargs = dict(
            original_expression="dgo", corrected_expression="dog",
            language="en", locale="en-US", confidence=0.75)
        first = build_correction_understanding("no I mean dog not dgo", **kwargs)
        second = build_correction_understanding("no I mean dog not dgo", **kwargs)
        third = build_correction_understanding("no I mean dog not dgo", **kwargs)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(second.to_dict(), third.to_dict())

    def test_repeated_ambiguous_call_stays_ambiguous(self):
        kwargs = dict(
            original_expression="that", corrected_candidates=["this", "it"], language="en")
        first = build_correction_understanding("no not that", **kwargs)
        second = build_correction_understanding("no not that", **kwargs)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.status, STATUS_AMBIGUOUS)


class TestConfidenceAndValidation(unittest.TestCase):
    """Small supporting checks: required source_text, confidence clamping,
    status validity - kept in this file since they are directly related to
    the focused behavior above, not a broader audit."""

    def test_missing_source_text_raises(self):
        with self.assertRaises(ValueError):
            build_correction_understanding("")

    def test_confidence_defaults_to_zero(self):
        result = build_correction_understanding("hi")
        self.assertEqual(result.confidence, 0.0)

    def test_confidence_is_clamped_into_unit_range(self):
        result = build_correction_understanding(
            "no I mean dog", original_expression="dgo", corrected_expression="dog",
            confidence=5.0)
        self.assertEqual(result.confidence, 1.0)

    def test_all_statuses_constructible_and_listed(self):
        self.assertEqual(
            set(ALL_STATUSES),
            {STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED, STATUS_NOT_CORRECTION})
        for status in ALL_STATUSES:
            result = CorrectionUnderstandingResult(status, "hi")
            self.assertEqual(result.status, status)


if __name__ == "__main__":
    unittest.main()
