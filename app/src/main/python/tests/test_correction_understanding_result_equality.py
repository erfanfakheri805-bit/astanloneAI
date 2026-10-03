"""
Tests for Prompt 447 - Correction Result Equality.

`CorrectionUnderstandingResult.__eq__`
(language_intelligence/correction_understanding_result.py) is a small,
read-only, deterministic equality comparison over the seven fields
this class defines - status, original_expression,
corrected_expression_or_meaning, language, locale, source_text,
confidence. Same "isinstance check, then compare fields directly"
convention already used by `Token.__eq__` in
understanding/nl_tokenizer.py. Only:

    1. two identical results compare as equal
    2. different statuses compare as different
    3. different original expressions compare as different
    4. different corrected expressions/meanings compare as different
    5. different language or locale values compare as different
    6. different confidence values compare as different
    7. comparing a result with an invalid/non-result value compares as
       different (never raises)
    8. the comparison does not mutate either result

Run directly:
    python -m unittest tests.test_correction_understanding_result_equality -v
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


class TestIdenticalResultsAreEqual(unittest.TestCase):
    """1. Two identical results compare as equal."""

    def test_two_separately_built_results_with_the_same_fields_are_equal(self):
        a = _resolved()
        b = _resolved()
        self.assertEqual(a, b)
        self.assertTrue(a == b)
        self.assertFalse(a != b)

    def test_a_result_is_equal_to_itself(self):
        a = _resolved()
        self.assertEqual(a, a)


class TestDifferentStatusIsDifferent(unittest.TestCase):
    """2. Different statuses compare as different."""

    def test_resolved_vs_not_correction_are_not_equal(self):
        a = _resolved()
        b = CorrectionUnderstandingResult(
            STATUS_NOT_CORRECTION, source_text="no I mean dog not dgo")
        self.assertNotEqual(a, b)


class TestDifferentOriginalExpressionIsDifferent(unittest.TestCase):
    """3. Different original expressions compare as different."""

    def test_different_original_expression_is_not_equal(self):
        a = _resolved(original_expression="dgo")
        b = _resolved(original_expression="dog")
        self.assertNotEqual(a, b)


class TestDifferentCorrectedExpressionOrMeaningIsDifferent(unittest.TestCase):
    """4. Different corrected expressions/meanings compare as different."""

    def test_different_corrected_expression_or_meaning_is_not_equal(self):
        a = _resolved(corrected_expression_or_meaning="dog")
        b = _resolved(corrected_expression_or_meaning="cat")
        self.assertNotEqual(a, b)


class TestDifferentLanguageOrLocaleIsDifferent(unittest.TestCase):
    """5. Different language or locale values compare as different."""

    def test_different_language_is_not_equal(self):
        a = _resolved(language="en")
        b = _resolved(language="fa")
        self.assertNotEqual(a, b)

    def test_different_locale_is_not_equal(self):
        a = _resolved(locale="en-US")
        b = _resolved(locale="en-GB")
        self.assertNotEqual(a, b)

    def test_locale_none_vs_set_is_not_equal(self):
        a = _resolved(locale=None)
        b = _resolved(locale="en-US")
        self.assertNotEqual(a, b)


class TestDifferentConfidenceIsDifferent(unittest.TestCase):
    """6. Different confidence values compare as different."""

    def test_different_confidence_is_not_equal(self):
        a = _resolved(confidence=0.9)
        b = _resolved(confidence=0.4)
        self.assertNotEqual(a, b)

    def test_equal_confidence_values_of_different_numeric_type_are_equal(self):
        # follows the project's existing plain `==` convention (see
        # to_dict()/get_summary() and Token.__eq__): 0.5 == 0.5 as
        # Python already treats them, no special numeric handling
        # added here.
        a = _resolved(confidence=0.5)
        b = _resolved(confidence=0.5)
        self.assertEqual(a, b)


class TestComparingAgainstNonResultValue(unittest.TestCase):
    """7. Comparing a result with an invalid/non-result value behaves
    according to existing project conventions (Token.__eq__: not equal,
    never raises)."""

    def test_result_is_not_equal_to_none(self):
        a = _resolved()
        self.assertNotEqual(a, None)

    def test_result_is_not_equal_to_a_plain_dict_with_the_same_fields(self):
        a = _resolved()
        self.assertNotEqual(a, a.to_dict())

    def test_result_is_not_equal_to_an_unrelated_object(self):
        a = _resolved()
        self.assertNotEqual(a, "not a result")
        self.assertNotEqual(a, 42)
        self.assertNotEqual(a, object())


class TestComparisonDoesNotMutate(unittest.TestCase):
    """8. The comparison does not mutate either result."""

    def test_equality_check_leaves_both_results_unchanged(self):
        a = _resolved()
        b = _resolved(confidence=0.1)
        before_a = a.to_dict()
        before_b = b.to_dict()

        _ = (a == b)
        _ = (a == a)
        _ = (a != b)
        _ = (a == "not a result")

        self.assertEqual(a.to_dict(), before_a)
        self.assertEqual(b.to_dict(), before_b)


if __name__ == "__main__":
    unittest.main()
