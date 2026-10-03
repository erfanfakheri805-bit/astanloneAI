"""
Tests for Prompt 446 - Correction Result Summary.

`CorrectionUnderstandingResult.get_summary()`
(language_intelligence/correction_understanding_result.py) is a small,
read-only, deterministic structured summary of an existing
`CorrectionUnderstandingResult` (Prompt 441) - status,
original_expression, corrected_expression_or_meaning, language,
locale and confidence, each copied straight through from the existing
attribute. Only:

    1. a resolved correction result produces the expected summary
    2. an ambiguous result produces the expected summary
    3. an unresolved result produces the expected summary
    4. a not-correction result produces the expected summary
    5. no information is invented or lost during summarization
    6. the original result remains unchanged

Run directly:
    python -m unittest tests.test_correction_understanding_result_summary -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_understanding import (
    STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED, STATUS_NOT_CORRECTION,
)
from language_intelligence.correction_understanding_result import (
    CorrectionUnderstandingResult,
)


class TestResolvedSummary(unittest.TestCase):
    """1. A resolved correction result produces the expected summary."""

    def test_resolved_summary_matches_expected_fields(self):
        result = CorrectionUnderstandingResult(
            STATUS_RESOLVED, source_text="no I mean dog not dgo",
            original_expression="dgo",
            corrected_expression_or_meaning="dog",
            language="en", locale="en-US", confidence=0.9)
        self.assertEqual(result.get_summary(), {
            "status": STATUS_RESOLVED,
            "original_expression": "dgo",
            "corrected_expression_or_meaning": "dog",
            "language": "en",
            "locale": "en-US",
            "confidence": 0.9,
        })


class TestAmbiguousSummary(unittest.TestCase):
    """2. An ambiguous result produces the expected summary."""

    def test_ambiguous_summary_matches_expected_fields(self):
        result = CorrectionUnderstandingResult(
            STATUS_AMBIGUOUS, source_text="not dgo",
            original_expression="dgo",
            language="en", locale="en-US", confidence=0.4)
        self.assertEqual(result.get_summary(), {
            "status": STATUS_AMBIGUOUS,
            "original_expression": "dgo",
            "corrected_expression_or_meaning": None,
            "language": "en",
            "locale": "en-US",
            "confidence": 0.4,
        })


class TestUnresolvedSummary(unittest.TestCase):
    """3. An unresolved result produces the expected summary."""

    def test_unresolved_summary_matches_expected_fields(self):
        result = CorrectionUnderstandingResult(
            STATUS_UNRESOLVED, source_text="not dgo",
            original_expression="dgo",
            language="en", locale=None, confidence=0.2)
        self.assertEqual(result.get_summary(), {
            "status": STATUS_UNRESOLVED,
            "original_expression": "dgo",
            "corrected_expression_or_meaning": None,
            "language": "en",
            "locale": None,
            "confidence": 0.2,
        })


class TestNotCorrectionSummary(unittest.TestCase):
    """4. A not-correction result produces the expected summary."""

    def test_not_correction_summary_matches_expected_fields(self):
        result = CorrectionUnderstandingResult(
            STATUS_NOT_CORRECTION, source_text="hello there")
        self.assertEqual(result.get_summary(), {
            "status": STATUS_NOT_CORRECTION,
            "original_expression": None,
            "corrected_expression_or_meaning": None,
            "language": None,
            "locale": None,
            "confidence": 0.0,
        })


class TestNoInformationInventedOrLost(unittest.TestCase):
    """5. No information is invented or lost during summarization."""

    def test_summary_has_exactly_the_documented_keys_no_more_no_less(self):
        result = CorrectionUnderstandingResult(
            STATUS_RESOLVED, source_text="no I mean dog not dgo",
            original_expression="dgo",
            corrected_expression_or_meaning="dog",
            language="en", locale="en-US", confidence=0.9)
        summary = result.get_summary()
        self.assertEqual(
            set(summary.keys()),
            {"status", "original_expression", "corrected_expression_or_meaning",
             "language", "locale", "confidence"})

    def test_every_summary_value_matches_the_source_attribute_exactly(self):
        result = CorrectionUnderstandingResult(
            STATUS_RESOLVED, source_text="no I mean dog not dgo",
            original_expression="dgo",
            corrected_expression_or_meaning="dog",
            language="en", locale="en-US", confidence=0.9)
        summary = result.get_summary()
        self.assertEqual(summary["status"], result.status)
        self.assertEqual(summary["original_expression"], result.original_expression)
        self.assertEqual(summary["corrected_expression_or_meaning"],
                          result.corrected_expression_or_meaning)
        self.assertEqual(summary["language"], result.language)
        self.assertEqual(summary["locale"], result.locale)
        self.assertEqual(summary["confidence"], result.confidence)

    def test_summary_omits_source_text_but_does_not_lose_it_from_the_result(self):
        result = CorrectionUnderstandingResult(
            STATUS_RESOLVED, source_text="no I mean dog not dgo",
            original_expression="dgo",
            corrected_expression_or_meaning="dog")
        summary = result.get_summary()
        self.assertNotIn("source_text", summary)
        # the original result still carries it - summarizing did not
        # drop it from the result itself, only from this shorter view.
        self.assertEqual(result.source_text, "no I mean dog not dgo")


class TestOriginalResultUnchanged(unittest.TestCase):
    """6. The original result remains unchanged."""

    def test_calling_get_summary_repeatedly_leaves_the_result_unchanged(self):
        result = CorrectionUnderstandingResult(
            STATUS_RESOLVED, source_text="no I mean dog not dgo",
            original_expression="dgo",
            corrected_expression_or_meaning="dog",
            language="en", locale="en-US", confidence=0.9)
        before = result.to_dict()

        _ = result.get_summary()
        _ = result.get_summary()

        after = result.to_dict()
        self.assertEqual(before, after)

    def test_mutating_the_returned_summary_dict_does_not_affect_the_result(self):
        result = CorrectionUnderstandingResult(
            STATUS_RESOLVED, source_text="no I mean dog not dgo",
            original_expression="dgo",
            corrected_expression_or_meaning="dog",
            language="en", locale="en-US", confidence=0.9)
        summary = result.get_summary()
        summary["status"] = "TAMPERED"
        summary["confidence"] = -99

        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.confidence, 0.9)
        self.assertEqual(result.get_summary()["status"], STATUS_RESOLVED)


if __name__ == "__main__":
    unittest.main()
