"""
Tests for Prompt 488 - Validate Verified Correction Response Input
Usability.

`is_verified_correction_response_input_usable()`
(language_intelligence/verified_correction_response_input_usability.py)
is a small, deterministic check over an already-built Prompt
426/467/471/483/487 `ResponseGenerationContext`'s
`verified_correction_response_input` field (a Prompt 485
`VerifiedCorrectionResponseInput`, when a caller explicitly supplied
one). It does not apply a correction, does not modify
`ResponseGenerationContext`, and does not modify the stored
`VerifiedCorrectionResponseInput`. Covers:

    1. no verified correction input -> not usable
    2. valid verified correction input -> usable
    3. missing text_before -> not usable
    4. missing text_after -> not usable
    5. missing matched_text -> not usable
    6. missing replacement_text -> not usable
    7. zero match_count -> not usable
    8. negative match_count -> not usable
    9. exact strings remain unchanged
    10. repeated checks are deterministic
    11. existing ResponseGenerationContext behavior remains unchanged

Run directly:
    python -m unittest tests.test_verified_correction_response_input_usability -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_generation_context import (
    ResponseGenerationContext,
)
from language_intelligence.response_planning import STATUS_RESOLVED
from language_intelligence.verified_correction_response_input import (
    build_verified_correction_response_input,
)
from language_intelligence.verified_correction_response_input_usability import (
    is_verified_correction_response_input_usable,
)


def _context(verified_correction_response_input=None):
    """A minimal, otherwise-ordinary `ResponseGenerationContext` -
    every field besides `verified_correction_response_input` is a
    plain, fixed stand-in value, the same way
    test_correction_application_result_usability.py's own hand-built
    contexts do; nothing here is read by the usability check besides
    `verified_correction_response_input` itself."""
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
        verified_correction_response_input=verified_correction_response_input,
    )


def _verified_input(**overrides):
    fields = dict(
        text_before="a dgo here",
        text_after="a dog here",
        matched_text="dgo",
        replacement_text="dog",
        match_count=1,
        metadata={"source": "user_correction"},
    )
    fields.update(overrides)
    return build_verified_correction_response_input(**fields)


class TestNoVerifiedCorrectionInputIsNotUsable(unittest.TestCase):
    def test_none_verified_correction_response_input_is_not_usable(self):
        context = _context(verified_correction_response_input=None)
        self.assertFalse(is_verified_correction_response_input_usable(context))

    def test_non_input_verified_correction_response_input_is_not_usable(self):
        # A plain dict - never accepted, even if shaped like to_dict()'s
        # output; only an actual VerifiedCorrectionResponseInput
        # instance counts.
        context = _context(
            verified_correction_response_input=_verified_input().to_dict())
        self.assertFalse(is_verified_correction_response_input_usable(context))


class TestValidVerifiedCorrectionInputIsUsable(unittest.TestCase):
    def test_valid_verified_correction_input_is_usable(self):
        context = _context(verified_correction_response_input=_verified_input())
        self.assertTrue(is_verified_correction_response_input_usable(context))


class TestMissingTextBeforeIsNotUsable(unittest.TestCase):
    def test_missing_text_before_is_not_usable(self):
        # Construction itself enforces non-blank text_before, so the
        # only way to reach this defensive branch is to assign the
        # attribute directly after a valid construction - the SAME
        # technique test_correction_application_result_usability.py
        # already uses for its own equivalent defensive branch.
        verified = _verified_input()
        verified.text_before = ""
        context = _context(verified_correction_response_input=verified)
        self.assertFalse(is_verified_correction_response_input_usable(context))

    def test_none_text_before_is_not_usable(self):
        verified = _verified_input()
        verified.text_before = None
        context = _context(verified_correction_response_input=verified)
        self.assertFalse(is_verified_correction_response_input_usable(context))


class TestMissingTextAfterIsNotUsable(unittest.TestCase):
    def test_missing_text_after_is_not_usable(self):
        verified = _verified_input()
        verified.text_after = ""
        context = _context(verified_correction_response_input=verified)
        self.assertFalse(is_verified_correction_response_input_usable(context))


class TestMissingMatchedTextIsNotUsable(unittest.TestCase):
    def test_missing_matched_text_is_not_usable(self):
        verified = _verified_input()
        verified.matched_text = "   "
        context = _context(verified_correction_response_input=verified)
        self.assertFalse(is_verified_correction_response_input_usable(context))


class TestMissingReplacementTextIsNotUsable(unittest.TestCase):
    def test_missing_replacement_text_is_not_usable(self):
        verified = _verified_input()
        verified.replacement_text = ""
        context = _context(verified_correction_response_input=verified)
        self.assertFalse(is_verified_correction_response_input_usable(context))


class TestZeroMatchCountIsNotUsable(unittest.TestCase):
    def test_zero_match_count_is_not_usable(self):
        verified = _verified_input()
        verified.match_count = 0
        context = _context(verified_correction_response_input=verified)
        self.assertFalse(is_verified_correction_response_input_usable(context))

    def test_negative_match_count_is_not_usable(self):
        verified = _verified_input()
        verified.match_count = -1
        context = _context(verified_correction_response_input=verified)
        self.assertFalse(is_verified_correction_response_input_usable(context))


class TestExactStringsRemainUnchanged(unittest.TestCase):
    def test_check_does_not_modify_the_verified_input_fields(self):
        verified = _verified_input(
            text_before="a dgo here", text_after="a dog here",
            matched_text="dgo", replacement_text="dog")
        context = _context(verified_correction_response_input=verified)
        is_verified_correction_response_input_usable(context)
        self.assertEqual(verified.text_before, "a dgo here")
        self.assertEqual(verified.text_after, "a dog here")
        self.assertEqual(verified.matched_text, "dgo")
        self.assertEqual(verified.replacement_text, "dog")

    def test_check_never_normalizes_case_or_whitespace(self):
        # A usable input's exact strings are read verbatim - the check
        # itself never cases, trims, or otherwise transforms them.
        verified = _verified_input(
            text_before="  A DGO  ", text_after="  A DOG  ")
        context = _context(verified_correction_response_input=verified)
        self.assertTrue(is_verified_correction_response_input_usable(context))
        self.assertEqual(verified.text_before, "  A DGO  ")
        self.assertEqual(verified.text_after, "  A DOG  ")


class TestUsabilityCheckIsDeterministic(unittest.TestCase):
    def test_same_context_always_produces_the_same_result(self):
        context = _context(verified_correction_response_input=_verified_input())
        results = [
            is_verified_correction_response_input_usable(context) for _ in range(5)
        ]
        self.assertEqual(results, [True] * 5)

    def test_no_input_always_produces_the_same_result(self):
        context = _context(verified_correction_response_input=None)
        results = [
            is_verified_correction_response_input_usable(context) for _ in range(5)
        ]
        self.assertEqual(results, [False] * 5)

    def test_equal_inputs_produce_equal_results(self):
        context_a = _context(verified_correction_response_input=_verified_input())
        context_b = _context(verified_correction_response_input=_verified_input())
        self.assertEqual(
            is_verified_correction_response_input_usable(context_a),
            is_verified_correction_response_input_usable(context_b),
        )


class TestExistingResponseGenerationContextBehaviorUnchanged(unittest.TestCase):
    def test_context_not_mutated_by_the_check(self):
        verified = _verified_input()
        context = _context(verified_correction_response_input=verified)
        before = context.to_dict()
        is_verified_correction_response_input_usable(context)
        self.assertEqual(context.to_dict(), before)

    def test_verified_correction_response_input_not_mutated_by_the_check(self):
        verified = _verified_input()
        before = verified.to_dict()
        context = _context(verified_correction_response_input=verified)
        is_verified_correction_response_input_usable(context)
        self.assertEqual(verified.to_dict(), before)

    def test_other_fields_unaffected_by_running_the_check(self):
        context = _context(verified_correction_response_input=_verified_input())
        is_verified_correction_response_input_usable(context)
        self.assertEqual(context.status, STATUS_RESOLVED)
        self.assertEqual(context.original_message, "hello")
        self.assertIsNone(context.correction_application_result)

    def test_non_response_generation_context_raises_type_error(self):
        with self.assertRaises(TypeError):
            is_verified_correction_response_input_usable({"not": "a context"})


if __name__ == "__main__":
    unittest.main()
