"""
Tests for Prompt 440 - Expose Correction Understanding.

Covers the small, additive integration that exposes Prompt 439's
`CorrectionUnderstanding` through the existing understanding flow:

    UnderstandingEngine.understand()   (understanding/engine.py)
        -> correction_detection.detect_explicit_correction()   (Prompt 440,
           a fixed, explicit textual marker - understanding/
           correction_detection.py)
        -> UnderstandingResult.correction_candidate   (raw candidate or None)
        -> DeterministicFallbackBackend.understand()   (language_intelligence/
           deterministic_fallback_backend.py)
        -> build_correction_understanding()   (Prompt 439,
           language_intelligence/correction_understanding.py)
        -> LanguageUnderstandingResult.correction_understanding   (dict or
           None)

Run directly:
    python -m unittest tests.test_correction_understanding_exposure -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.correction_understanding import (
    STATUS_RESOLVED, STATUS_NOT_CORRECTION,
)


def _make_backend():
    return DeterministicFallbackBackend(UnderstandingEngine())


class TestExplicitCorrectionIsExposed(unittest.TestCase):
    """1. Explicit correction is exposed."""

    def test_explicit_correction_marker_produces_correction_understanding(self):
        backend = _make_backend()
        result = backend.understand("not dgo, I mean dog.")
        self.assertIsNotNone(result.correction_understanding)
        self.assertIsInstance(result.correction_understanding, dict)

    def test_meant_variant_also_exposed(self):
        backend = _make_backend()
        result = backend.understand("not dgo, I meant dog.")
        self.assertIsNotNone(result.correction_understanding)
        self.assertEqual(result.correction_understanding["status"], STATUS_RESOLVED)


class TestNonCorrectionRemainsUnchanged(unittest.TestCase):
    """2. Non-correction remains unchanged."""

    def test_ordinary_statement_has_no_correction_understanding(self):
        backend = _make_backend()
        result = backend.understand("Python is a programming language.")
        self.assertIsNone(result.correction_understanding)

    def test_ordinary_question_has_no_correction_understanding(self):
        backend = _make_backend()
        result = backend.understand("What is Python?")
        self.assertIsNone(result.correction_understanding)

    def test_ordinary_message_does_not_create_a_not_correction_result_either(self):
        # Requirement: do not create correction data unnecessarily - not
        # even a NOT_CORRECTION structure, just None.
        backend = _make_backend()
        result = backend.understand("hello there")
        self.assertIsNone(result.correction_understanding)


class TestCorrectionStatusPreserved(unittest.TestCase):
    """3. Correction status is preserved."""

    def test_resolved_status_is_carried_through(self):
        backend = _make_backend()
        result = backend.understand("not dgo, I mean dog.")
        self.assertEqual(result.correction_understanding["status"], STATUS_RESOLVED)


class TestOriginalExpressionPreserved(unittest.TestCase):
    """4. Original expression is preserved."""

    def test_original_expression_matches_the_marker(self):
        backend = _make_backend()
        result = backend.understand("not dgo, I mean dog.")
        self.assertEqual(result.correction_understanding["original_expression"], "dgo")

    def test_multi_word_original_expression_preserved(self):
        backend = _make_backend()
        result = backend.understand("not gud morning, I mean good morning.")
        self.assertEqual(
            result.correction_understanding["original_expression"], "gud morning")


class TestCorrectedExpressionOrMeaningPreserved(unittest.TestCase):
    """5. Corrected expression/meaning is preserved."""

    def test_corrected_expression_matches_the_marker(self):
        backend = _make_backend()
        result = backend.understand("not dgo, I mean dog.")
        self.assertEqual(result.correction_understanding["corrected_expression"], "dog")
        self.assertIsNone(result.correction_understanding["corrected_meaning"])


class TestLanguageLocalePreserved(unittest.TestCase):
    """6. Language/locale are preserved."""

    def test_detected_language_is_carried_into_the_correction(self):
        backend = _make_backend()
        result = backend.understand("not dgo, I mean dog.")
        self.assertEqual(result.correction_understanding["language"], result.detected_language)

    def test_locale_is_none_since_nothing_supplies_one_yet(self):
        backend = _make_backend()
        result = backend.understand("not dgo, I mean dog.")
        self.assertIsNone(result.correction_understanding["locale"])


class TestSourceTextPreserved(unittest.TestCase):
    """7. Source text is preserved."""

    def test_source_text_is_the_original_message_verbatim(self):
        backend = _make_backend()
        raw = "  not dgo,   I mean dog.  "
        result = backend.understand(raw)
        self.assertEqual(result.correction_understanding["source_text"], result.original_input)
        self.assertEqual(result.original_input, raw)


class TestConfidencePreserved(unittest.TestCase):
    """8. Confidence is preserved."""

    def test_confidence_is_a_float_in_unit_range(self):
        backend = _make_backend()
        result = backend.understand("not dgo, I mean dog.")
        confidence = result.correction_understanding["confidence"]
        self.assertIsInstance(confidence, float)
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)


class TestExistingUnderstandingBehaviorRemainsCompatible(unittest.TestCase):
    """9. Existing understanding behavior remains compatible."""

    def test_ordinary_message_understanding_is_unaffected(self):
        backend = _make_backend()
        result = backend.understand("Python is a programming language.")
        self.assertTrue(any(e["text"].lower() == "python" for e in result.entities))
        self.assertEqual(result.original_input, "Python is a programming language.")
        self.assertFalse(result.ambiguity)

    def test_correction_marker_message_still_understood_normally_otherwise(self):
        # The correction exposure is strictly additive: a message that
        # happens to match the marker is still understood exactly like
        # any other statement for every other field.
        backend = _make_backend()
        result = backend.understand("not dgo, I mean dog.")
        self.assertEqual(result.original_input, "not dgo, I mean dog.")
        self.assertIsInstance(result.entities, list)
        self.assertIsInstance(result.confidence, float)

    def test_to_dict_still_round_trips_with_the_new_field_included(self):
        backend = _make_backend()
        result = backend.understand("not dgo, I mean dog.")
        as_dict = result.to_dict()
        self.assertIn("correction_understanding", as_dict)
        self.assertEqual(as_dict["correction_understanding"]["status"], STATUS_RESOLVED)

    def test_underlying_understanding_result_carries_raw_candidate(self):
        engine = UnderstandingEngine()
        raw = engine.understand("not dgo, I mean dog.")
        self.assertEqual(
            raw.correction_candidate,
            {"original_expression": "dgo", "corrected_expression": "dog"})
        as_dict = raw.to_dict()
        self.assertIn("correction_candidate", as_dict)

    def test_underlying_understanding_result_candidate_none_for_ordinary_text(self):
        engine = UnderstandingEngine()
        raw = engine.understand("Python is a programming language.")
        self.assertIsNone(raw.correction_candidate)


if __name__ == "__main__":
    unittest.main()
