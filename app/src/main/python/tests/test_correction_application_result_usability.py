"""
Tests for Prompt 484 - Correction Application Result Usability.

`is_correction_application_result_usable()`
(language_intelligence/correction_application_result_usability.py) is
a small, deterministic check over an already-built Prompt 426/467/471/
483 `ResponseGenerationContext`'s `correction_application_result`
field (a Prompt 474/478/479 `CorrectionApplicationResult`, when a
caller explicitly supplied one). It does not apply a correction, does
not modify `ResponseGenerationContext`, and does not modify the stored
`CorrectionApplicationResult`. Covers:

    1. no correction result -> not usable
    2. valid APPLIED result -> usable
    3. NOT_APPLIED -> not usable
    4. FAILED -> not usable
    5. applied=False -> not usable
    6. zero match count -> not usable
    7. missing text_before -> not usable
    8. missing text_after -> not usable
    9. missing matched_text -> not usable
    10. missing replacement_text -> not usable
    11. repeated checks are deterministic
    12. existing ResponseGenerationContext behavior remains unchanged

Run directly:
    python -m unittest tests.test_correction_application_result_usability -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_generation_context import (
    ResponseGenerationContext,
)
from language_intelligence.response_planning import STATUS_RESOLVED
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult,
    STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED,
)
from language_intelligence.correction_application_result_usability import (
    is_correction_application_result_usable,
)


def _context(correction_application_result=None):
    """A minimal, otherwise-ordinary `ResponseGenerationContext` -
    every field besides `correction_application_result` is a plain,
    fixed stand-in value, the same way test_response_generation_context.py's
    own hand-built contexts do; nothing here is read by the usability
    check besides `correction_application_result` itself."""
    return ResponseGenerationContext(
        original_message="hello",
        status=STATUS_RESOLVED,
        response_action=None,
        meaning=None,
        meaning_candidates=[],
        matched_pattern=None,
        variables={},
        active_topic=None,
        references=[],
        context=None,
        language="en",
        locale=None,
        unresolved_requirements=[],
        correction_application_result=correction_application_result,
    )


def _applied_result(**overrides):
    fields = dict(
        status=STATUS_APPLIED,
        original_text="I has a dgo",
        corrected_text="I has a dog",
        matched_text="dgo",
        replacement_text="dog",
        match_count=1,
        text_before="I has a dgo",
        text_after="I has a dog",
    )
    fields.update(overrides)
    return CorrectionApplicationResult(**fields)


class TestNoCorrectionResultIsNotUsable(unittest.TestCase):
    def test_none_correction_application_result_is_not_usable(self):
        context = _context(correction_application_result=None)
        self.assertFalse(is_correction_application_result_usable(context))

    def test_non_result_correction_application_result_is_not_usable(self):
        context = _context(correction_application_result={"status": "APPLIED"})
        self.assertFalse(is_correction_application_result_usable(context))


class TestValidAppliedResultIsUsable(unittest.TestCase):
    def test_valid_applied_result_is_usable(self):
        context = _context(correction_application_result=_applied_result())
        self.assertTrue(is_correction_application_result_usable(context))


class TestNotAppliedIsNotUsable(unittest.TestCase):
    def test_not_applied_is_not_usable(self):
        result = CorrectionApplicationResult(
            status=STATUS_NOT_APPLIED,
            original_text="hello",
            text_before="hello",
            text_after="hello",
            match_count=0,
        )
        context = _context(correction_application_result=result)
        self.assertFalse(is_correction_application_result_usable(context))


class TestFailedIsNotUsable(unittest.TestCase):
    def test_failed_is_not_usable(self):
        result = CorrectionApplicationResult(
            status=STATUS_FAILED,
            original_text="hello",
            reason="storage_unavailable",
            match_count=0,
        )
        context = _context(correction_application_result=result)
        self.assertFalse(is_correction_application_result_usable(context))


class TestAppliedFalseIsNotUsable(unittest.TestCase):
    def test_applied_flag_forced_false_is_not_usable(self):
        # CorrectionApplicationResult always derives `applied` from
        # `status`, so an APPLIED-status/applied=False combination is
        # not producible through the normal constructor path - assign
        # the attribute directly purely to exercise this defensive
        # branch of the usability check itself.
        result = _applied_result()
        result.applied = False
        context = _context(correction_application_result=result)
        self.assertFalse(is_correction_application_result_usable(context))


class TestZeroMatchCountIsNotUsable(unittest.TestCase):
    def test_zero_match_count_is_not_usable(self):
        result = _applied_result(match_count=0)
        context = _context(correction_application_result=result)
        self.assertFalse(is_correction_application_result_usable(context))

    def test_negative_match_count_is_not_usable(self):
        result = _applied_result(match_count=-1)
        context = _context(correction_application_result=result)
        self.assertFalse(is_correction_application_result_usable(context))


class TestMissingTextBeforeIsNotUsable(unittest.TestCase):
    def test_missing_text_before_is_not_usable(self):
        result = _applied_result(text_before=None, original_text=None)
        context = _context(correction_application_result=result)
        self.assertFalse(is_correction_application_result_usable(context))


class TestMissingTextAfterIsNotUsable(unittest.TestCase):
    def test_missing_text_after_is_not_usable(self):
        # With no explicit text_after and no corrected_text, the
        # constructor's own APPLIED default (text_after = corrected_text)
        # leaves text_after as None - reaching the missing branch
        # directly, without needing to patch the attribute.
        result = _applied_result(text_after=None, corrected_text=None)
        context = _context(correction_application_result=result)
        self.assertFalse(is_correction_application_result_usable(context))


class TestMissingMatchedTextIsNotUsable(unittest.TestCase):
    def test_missing_matched_text_is_not_usable(self):
        result = _applied_result(matched_text=None)
        context = _context(correction_application_result=result)
        self.assertFalse(is_correction_application_result_usable(context))


class TestMissingReplacementTextIsNotUsable(unittest.TestCase):
    def test_missing_replacement_text_is_not_usable(self):
        result = _applied_result(replacement_text=None)
        context = _context(correction_application_result=result)
        self.assertFalse(is_correction_application_result_usable(context))


class TestUsabilityCheckIsDeterministic(unittest.TestCase):
    def test_same_context_always_produces_the_same_result(self):
        context = _context(correction_application_result=_applied_result())
        results = [is_correction_application_result_usable(context) for _ in range(5)]
        self.assertEqual(results, [True] * 5)

    def test_no_result_always_produces_the_same_result(self):
        context = _context(correction_application_result=None)
        results = [is_correction_application_result_usable(context) for _ in range(5)]
        self.assertEqual(results, [False] * 5)

    def test_equal_inputs_produce_equal_results(self):
        context_a = _context(correction_application_result=_applied_result())
        context_b = _context(correction_application_result=_applied_result())
        self.assertEqual(
            is_correction_application_result_usable(context_a),
            is_correction_application_result_usable(context_b),
        )


class TestExistingResponseGenerationContextBehaviorUnchanged(unittest.TestCase):
    def test_context_not_mutated_by_the_check(self):
        result = _applied_result()
        context = _context(correction_application_result=result)
        before = context.to_dict()
        is_correction_application_result_usable(context)
        self.assertEqual(context.to_dict(), before)

    def test_correction_application_result_not_mutated_by_the_check(self):
        result = _applied_result()
        before = result.to_dict()
        context = _context(correction_application_result=result)
        is_correction_application_result_usable(context)
        self.assertEqual(result.to_dict(), before)

    def test_to_dict_still_carries_correction_application_result_unchanged(self):
        result = _applied_result()
        context = _context(correction_application_result=result)
        is_correction_application_result_usable(context)
        self.assertEqual(
            context.to_dict()["correction_application_result"], result.to_dict()
        )

    def test_none_correction_application_result_field_still_none(self):
        context = _context(correction_application_result=None)
        self.assertIsNone(context.correction_application_result)
        is_correction_application_result_usable(context)
        self.assertIsNone(context.correction_application_result)

    def test_invalid_type_raises_without_side_effects(self):
        with self.assertRaises(TypeError):
            is_correction_application_result_usable({"correction_application_result": None})
        with self.assertRaises(TypeError):
            is_correction_application_result_usable(None)


if __name__ == "__main__":
    unittest.main()
