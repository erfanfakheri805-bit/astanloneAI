"""
Tests for Prompt 448 - Correction Result Safe Copy.

`CorrectionUnderstandingResult.copy()`
(language_intelligence/correction_understanding_result.py) is a small,
read-only, deterministic safe-copy operation: it returns a new,
independent `CorrectionUnderstandingResult` with the same seven fields
- status, original_expression, corrected_expression_or_meaning,
language, locale, source_text, confidence. The one field that can
carry a mutable, caller-shaped JSON value
(corrected_expression_or_meaning) is deep-copied, so the copy shares
no mutable state with the original. Only:

    1. the copied result preserves all fields
    2. the copied result compares equal to the original (Prompt 447's
       `__eq__`)
    3. the copy is independent when mutable values exist
    4. creating a copy does not modify the original
    5. optional/None values are preserved correctly

Run directly:
    python -m unittest tests.test_correction_understanding_result_safe_copy -v
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


def _resolved(**overrides):
    fields = dict(
        status=STATUS_RESOLVED, source_text="no I mean dog not dgo",
        original_expression="dgo", corrected_expression_or_meaning="dog",
        language="en", locale="en-US", confidence=0.9)
    fields.update(overrides)
    return CorrectionUnderstandingResult(**fields)


class TestCopyPreservesAllFields(unittest.TestCase):
    """1. The copied result preserves all fields."""

    def test_copy_preserves_every_field_exactly(self):
        original = _resolved()
        copy_ = original.copy()
        self.assertEqual(copy_.status, original.status)
        self.assertEqual(copy_.original_expression, original.original_expression)
        self.assertEqual(copy_.corrected_expression_or_meaning,
                          original.corrected_expression_or_meaning)
        self.assertEqual(copy_.language, original.language)
        self.assertEqual(copy_.locale, original.locale)
        self.assertEqual(copy_.source_text, original.source_text)
        self.assertEqual(copy_.confidence, original.confidence)

    def test_copy_to_dict_matches_original_to_dict(self):
        original = _resolved()
        self.assertEqual(original.copy().to_dict(), original.to_dict())


class TestCopyComparesEqualToOriginal(unittest.TestCase):
    """2. The copied result compares equal to the original according
    to the existing comparison behavior (Prompt 447's `__eq__`)."""

    def test_copy_equals_original(self):
        original = _resolved()
        copy_ = original.copy()
        self.assertEqual(copy_, original)
        self.assertTrue(copy_ == original)
        self.assertFalse(copy_ != original)

    def test_copy_is_a_distinct_object_from_the_original(self):
        original = _resolved()
        copy_ = original.copy()
        self.assertIsNot(copy_, original)


class TestCopyIsIndependentForMutableValues(unittest.TestCase):
    """3. The copy is independent when mutable values exist."""

    def test_mutating_a_dict_shaped_corrected_meaning_on_the_copy_does_not_affect_original(self):
        original = _resolved(
            corrected_expression_or_meaning={"meaning_name": "greet", "slots": ["hello"]})
        copy_ = original.copy()

        copy_.corrected_expression_or_meaning["meaning_name"] = "CHANGED"
        copy_.corrected_expression_or_meaning["slots"].append("CHANGED")

        self.assertEqual(original.corrected_expression_or_meaning,
                          {"meaning_name": "greet", "slots": ["hello"]})
        self.assertEqual(copy_.corrected_expression_or_meaning["meaning_name"], "CHANGED")

    def test_mutating_a_list_shaped_corrected_meaning_on_the_original_does_not_affect_the_copy(self):
        mutable_meaning = {"candidates": ["dog", "dig"]}
        original = _resolved(corrected_expression_or_meaning=mutable_meaning)
        copy_ = original.copy()

        mutable_meaning["candidates"].append("CHANGED")
        original.corrected_expression_or_meaning["candidates"].append("ALSO CHANGED")

        self.assertEqual(copy_.corrected_expression_or_meaning, {"candidates": ["dog", "dig"]})


class TestCopyDoesNotModifyOriginal(unittest.TestCase):
    """4. Creating a copy does not modify the original."""

    def test_calling_copy_leaves_the_original_unchanged(self):
        original = _resolved(
            corrected_expression_or_meaning={"meaning_name": "greet"})
        before = original.to_dict()

        _ = original.copy()
        _ = original.copy()

        after = original.to_dict()
        self.assertEqual(before, after)


class TestOptionalNoneValuesArePreserved(unittest.TestCase):
    """5. Optional/"None" values are preserved correctly."""

    def test_none_fields_stay_none_on_the_copy(self):
        original = CorrectionUnderstandingResult(
            STATUS_NOT_CORRECTION, source_text="hello there")
        copy_ = original.copy()

        self.assertIsNone(copy_.original_expression)
        self.assertIsNone(copy_.corrected_expression_or_meaning)
        self.assertIsNone(copy_.language)
        self.assertIsNone(copy_.locale)
        self.assertEqual(copy_.confidence, 0.0)
        self.assertEqual(copy_, original)

    def test_some_none_some_set_fields_are_preserved_individually(self):
        original = CorrectionUnderstandingResult(
            STATUS_UNRESOLVED, source_text="not dgo",
            original_expression="dgo", language="en", locale=None,
            confidence=0.2)
        copy_ = original.copy()

        self.assertEqual(copy_.original_expression, "dgo")
        self.assertIsNone(copy_.corrected_expression_or_meaning)
        self.assertEqual(copy_.language, "en")
        self.assertIsNone(copy_.locale)
        self.assertEqual(copy_.confidence, 0.2)


if __name__ == "__main__":
    unittest.main()
