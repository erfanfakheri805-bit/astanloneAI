"""
Tests for Prompt 456 - Correction Learning Input Eligibility.

`is_correction_learning_input_eligible()`
(language_intelligence/correction_learning_input_eligibility.py) is a
small, deterministic check over the learning input dict Prompt 455's
adapter (`correction_feedback_learning_input_adapter.py`) produces. It
inspects only information already in that dict; it does not learn,
store, or touch `LearningAnalyzer`, `CorrectionUnderstanding`,
`CorrectionUnderstandingResult`, or `CorrectionFeedbackRecord`. Only:

    1. a complete valid correction learning input is eligible
    2. missing original expression (`key`) is not eligible
    3. missing corrected expression/meaning (`meaning`) is not eligible
    4. missing required language information is handled per existing
       conventions (non-blank text that names a real language/locale,
       the same rule language_learning_store.py's learn_item() itself
       enforces)
    5. an invalid correction-derived input (None - what Prompt 455's
       adapter itself returns for invalid feedback) is not eligible
    6. the eligibility check does not modify the input

Run directly:
    python -m unittest tests.test_correction_learning_input_eligibility -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_understanding import (
    build_correction_understanding,
)
from language_intelligence.correction_understanding_result import (
    map_correction_understanding_to_result,
)
from language_intelligence.correction_feedback_record import (
    map_correction_understanding_result_to_feedback_record,
)
from language_intelligence.correction_feedback_learning_input_adapter import (
    convert_correction_feedback_to_learning_input,
)
from language_intelligence.correction_learning_input_eligibility import (
    is_correction_learning_input_eligible,
)


def _valid_learning_input(**overrides):
    source = build_correction_understanding(
        "no I mean dog not dgo", original_expression="dgo",
        corrected_expression="dog", language="en", locale="en-US", confidence=0.9)
    result = map_correction_understanding_to_result(source)
    record = map_correction_understanding_result_to_feedback_record(result)
    learning_input = convert_correction_feedback_to_learning_input(record)
    learning_input.update(overrides)
    return learning_input


def _invalid_feedback_learning_input():
    """What Prompt 455's own adapter returns for feedback that was
    never valid correction feedback - None."""
    source = build_correction_understanding("dgo", original_expression="dgo")
    result = map_correction_understanding_to_result(source)
    record = map_correction_understanding_result_to_feedback_record(result)
    return convert_correction_feedback_to_learning_input(record)


class TestCompleteValidInputIsEligible(unittest.TestCase):
    """1. A complete valid correction learning input is eligible."""

    def test_complete_input_is_eligible(self):
        learning_input = _valid_learning_input()
        self.assertTrue(is_correction_learning_input_eligible(learning_input))

    def test_extra_unrelated_fields_do_not_affect_eligibility(self):
        learning_input = _valid_learning_input(source="USER_CORRECTION",
                                                source_context="no I mean dog not dgo")
        self.assertTrue(is_correction_learning_input_eligible(learning_input))


class TestMissingOriginalExpressionIsNotEligible(unittest.TestCase):
    """2. Missing original expression is not eligible."""

    def test_missing_key_is_not_eligible(self):
        learning_input = _valid_learning_input()
        del learning_input["key"]
        self.assertFalse(is_correction_learning_input_eligible(learning_input))

    def test_blank_key_is_not_eligible(self):
        learning_input = _valid_learning_input(key="   ")
        self.assertFalse(is_correction_learning_input_eligible(learning_input))

    def test_none_key_is_not_eligible(self):
        learning_input = _valid_learning_input(key=None)
        self.assertFalse(is_correction_learning_input_eligible(learning_input))


class TestMissingCorrectedExpressionOrMeaningIsNotEligible(unittest.TestCase):
    """3. Missing corrected expression/meaning is not eligible."""

    def test_missing_meaning_is_not_eligible(self):
        learning_input = _valid_learning_input()
        del learning_input["meaning"]
        self.assertFalse(is_correction_learning_input_eligible(learning_input))

    def test_blank_meaning_is_not_eligible(self):
        learning_input = _valid_learning_input(meaning="")
        self.assertFalse(is_correction_learning_input_eligible(learning_input))

    def test_empty_dict_meaning_is_not_eligible(self):
        learning_input = _valid_learning_input(meaning={})
        self.assertFalse(is_correction_learning_input_eligible(learning_input))

    def test_none_meaning_is_not_eligible(self):
        learning_input = _valid_learning_input(meaning=None)
        self.assertFalse(is_correction_learning_input_eligible(learning_input))


class TestMissingLanguageIsHandledPerExistingConvention(unittest.TestCase):
    """4. Missing required language information is handled according
    to existing conventions (same rule learn_item()/_resolve_language()
    already enforce, via canonical_language())."""

    def test_missing_language_is_not_eligible(self):
        learning_input = _valid_learning_input()
        del learning_input["language"]
        self.assertFalse(is_correction_learning_input_eligible(learning_input))

    def test_blank_language_is_not_eligible(self):
        learning_input = _valid_learning_input(language="")
        self.assertFalse(is_correction_learning_input_eligible(learning_input))

    def test_none_language_is_not_eligible(self):
        learning_input = _valid_learning_input(language=None)
        self.assertFalse(is_correction_learning_input_eligible(learning_input))

    def test_unknown_language_label_is_not_eligible(self):
        # canonical_language() treats "unknown" as naming no language.
        learning_input = _valid_learning_input(language="unknown")
        self.assertFalse(is_correction_learning_input_eligible(learning_input))

    def test_recognized_language_code_is_eligible(self):
        learning_input = _valid_learning_input(language="fa")
        self.assertTrue(is_correction_learning_input_eligible(learning_input))

    def test_unrecognized_but_real_language_code_is_eligible(self):
        # canonical_language() passes an unknown-but-real code through
        # lowercased rather than rejecting it.
        learning_input = _valid_learning_input(language="fi")
        self.assertTrue(is_correction_learning_input_eligible(learning_input))


class TestInvalidCorrectionDerivedInputIsNotEligible(unittest.TestCase):
    """5. An invalid correction-derived input is not eligible."""

    def test_none_is_not_eligible(self):
        learning_input = _invalid_feedback_learning_input()
        self.assertIsNone(learning_input)
        self.assertFalse(is_correction_learning_input_eligible(learning_input))

    def test_non_dict_values_are_not_eligible(self):
        self.assertFalse(is_correction_learning_input_eligible("not a dict"))
        self.assertFalse(is_correction_learning_input_eligible(123))
        self.assertFalse(is_correction_learning_input_eligible([]))


class TestEligibilityCheckDoesNotModifyTheInput(unittest.TestCase):
    """6. The eligibility check does not modify the input."""

    def test_valid_input_unchanged_after_check(self):
        learning_input = _valid_learning_input()
        before = copy.deepcopy(learning_input)
        is_correction_learning_input_eligible(learning_input)
        self.assertEqual(learning_input, before)

    def test_ineligible_input_unchanged_after_check(self):
        learning_input = _valid_learning_input(key="")
        before = copy.deepcopy(learning_input)
        is_correction_learning_input_eligible(learning_input)
        self.assertEqual(learning_input, before)

    def test_mutable_meaning_unchanged_after_check(self):
        learning_input = _valid_learning_input(meaning={"text": "dog"})
        before = copy.deepcopy(learning_input)
        is_correction_learning_input_eligible(learning_input)
        self.assertEqual(learning_input, before)


if __name__ == "__main__":
    unittest.main()
