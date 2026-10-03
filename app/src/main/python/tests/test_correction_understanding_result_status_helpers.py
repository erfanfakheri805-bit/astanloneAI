"""
Tests for Prompt 445 - Correction Result Status Helpers.

`CorrectionUnderstandingResult.is_resolved` / `.is_ambiguous` /
`.is_unresolved` / `.is_not_correction`
(language_intelligence/correction_understanding_result.py) are small,
read-only, deterministic checks against the existing `status` field.
Only:

    1. a RESOLVED result reports the correct status
    2. an AMBIGUOUS result reports the correct status
    3. an UNRESOLVED result reports the correct status
    4. a NOT_CORRECTION result reports the correct status
    5. the helpers do not modify the result

Run directly:
    python -m unittest tests.test_correction_understanding_result_status_helpers -v
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


class TestResolvedStatusHelpers(unittest.TestCase):
    """1. A RESOLVED result reports the correct status."""

    def test_resolved_helpers(self):
        result = CorrectionUnderstandingResult(
            STATUS_RESOLVED, source_text="no I mean dog not dgo",
            original_expression="dgo",
            corrected_expression_or_meaning="dog")
        self.assertTrue(result.is_resolved)
        self.assertFalse(result.is_ambiguous)
        self.assertFalse(result.is_unresolved)
        self.assertFalse(result.is_not_correction)


class TestAmbiguousStatusHelpers(unittest.TestCase):
    """2. An AMBIGUOUS result reports the correct status."""

    def test_ambiguous_helpers(self):
        result = CorrectionUnderstandingResult(
            STATUS_AMBIGUOUS, source_text="not dgo",
            original_expression="dgo")
        self.assertFalse(result.is_resolved)
        self.assertTrue(result.is_ambiguous)
        self.assertFalse(result.is_unresolved)
        self.assertFalse(result.is_not_correction)


class TestUnresolvedStatusHelpers(unittest.TestCase):
    """3. An UNRESOLVED result reports the correct status."""

    def test_unresolved_helpers(self):
        result = CorrectionUnderstandingResult(
            STATUS_UNRESOLVED, source_text="not dgo",
            original_expression="dgo")
        self.assertFalse(result.is_resolved)
        self.assertFalse(result.is_ambiguous)
        self.assertTrue(result.is_unresolved)
        self.assertFalse(result.is_not_correction)


class TestNotCorrectionStatusHelpers(unittest.TestCase):
    """4. A NOT_CORRECTION result reports the correct status."""

    def test_not_correction_helpers(self):
        result = CorrectionUnderstandingResult(
            STATUS_NOT_CORRECTION, source_text="hello there")
        self.assertFalse(result.is_resolved)
        self.assertFalse(result.is_ambiguous)
        self.assertFalse(result.is_unresolved)
        self.assertTrue(result.is_not_correction)


class TestHelpersDoNotModifyResult(unittest.TestCase):
    """5. The helpers do not modify the result."""

    def test_accessing_helpers_leaves_result_unchanged(self):
        result = CorrectionUnderstandingResult(
            STATUS_RESOLVED, source_text="no I mean dog not dgo",
            original_expression="dgo",
            corrected_expression_or_meaning="dog",
            language="en", locale="en-US", confidence=0.9)
        before = result.to_dict()

        # Access every helper, in every order, multiple times.
        _ = result.is_resolved
        _ = result.is_ambiguous
        _ = result.is_unresolved
        _ = result.is_not_correction
        _ = result.is_not_correction
        _ = result.is_resolved

        after = result.to_dict()
        self.assertEqual(before, after)
        self.assertEqual(result.status, STATUS_RESOLVED)


if __name__ == "__main__":
    unittest.main()
