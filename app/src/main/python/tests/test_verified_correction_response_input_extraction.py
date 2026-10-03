"""
Tests for Prompt 489 - Extract Usable Correction Response Input.

`extract_usable_verified_correction_response_input()`
(language_intelligence/verified_correction_response_input_extraction.py)
reads an already-built Prompt 426/467/471/483/487
`ResponseGenerationContext`'s `verified_correction_response_input`
field and returns a safe copy of it ONLY when Prompt 488's
`is_verified_correction_response_input_usable()` says it is usable -
`None` otherwise. It does not apply a correction, does not perform
text replacement or matching, does not modify
`ResponseGenerationContext`, and does not modify the stored
`VerifiedCorrectionResponseInput`. Covers:

    1. no correction input -> None
    2. valid usable correction input -> returned
    3. unusable correction input -> not returned (None)
    4. returned value preserves text_before
    5. returned value preserves text_after
    6. returned value preserves matched_text
    7. returned value preserves replacement_text
    8. returned value preserves match_count
    9. returned value preserves metadata
    10. safe copy behavior (independent from the stored instance)
    11. original context remains unchanged
    12. repeated extraction is deterministic

Run directly:
    python -m unittest tests.test_verified_correction_response_input_extraction -v
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
    VerifiedCorrectionResponseInput,
    build_verified_correction_response_input,
)
from language_intelligence.verified_correction_response_input_extraction import (
    extract_usable_verified_correction_response_input,
)


def _context(verified_correction_response_input=None):
    """A minimal, otherwise-ordinary `ResponseGenerationContext` -
    every field besides `verified_correction_response_input` is a
    plain, fixed stand-in value, the same way
    test_verified_correction_response_input_usability.py's own
    hand-built contexts do; nothing here is read by the extraction
    operation besides `verified_correction_response_input` itself."""
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
        metadata={"source": "user_correction", "note": "x"},
    )
    fields.update(overrides)
    return build_verified_correction_response_input(**fields)


class TestNoCorrectionInputYieldsNone(unittest.TestCase):
    def test_none_verified_correction_response_input_yields_none(self):
        context = _context(verified_correction_response_input=None)
        self.assertIsNone(
            extract_usable_verified_correction_response_input(context))

    def test_non_input_verified_correction_response_input_yields_none(self):
        # A plain dict - never accepted, even if shaped like to_dict()'s
        # output; only an actual VerifiedCorrectionResponseInput
        # instance is ever extracted.
        context = _context(
            verified_correction_response_input=_verified_input().to_dict())
        self.assertIsNone(
            extract_usable_verified_correction_response_input(context))


class TestValidUsableCorrectionInputIsReturned(unittest.TestCase):
    def test_valid_usable_input_is_returned(self):
        verified = _verified_input()
        context = _context(verified_correction_response_input=verified)
        extracted = extract_usable_verified_correction_response_input(context)
        self.assertIsNotNone(extracted)
        self.assertIsInstance(extracted, VerifiedCorrectionResponseInput)
        self.assertEqual(extracted, verified)


class TestUnusableCorrectionInputIsNotReturned(unittest.TestCase):
    def test_blank_text_before_is_not_returned(self):
        verified = _verified_input()
        verified.text_before = ""
        context = _context(verified_correction_response_input=verified)
        self.assertIsNone(
            extract_usable_verified_correction_response_input(context))

    def test_blank_text_after_is_not_returned(self):
        verified = _verified_input()
        verified.text_after = ""
        context = _context(verified_correction_response_input=verified)
        self.assertIsNone(
            extract_usable_verified_correction_response_input(context))

    def test_blank_matched_text_is_not_returned(self):
        verified = _verified_input()
        verified.matched_text = "   "
        context = _context(verified_correction_response_input=verified)
        self.assertIsNone(
            extract_usable_verified_correction_response_input(context))

    def test_blank_replacement_text_is_not_returned(self):
        verified = _verified_input()
        verified.replacement_text = None
        context = _context(verified_correction_response_input=verified)
        self.assertIsNone(
            extract_usable_verified_correction_response_input(context))

    def test_zero_match_count_is_not_returned(self):
        verified = _verified_input()
        verified.match_count = 0
        context = _context(verified_correction_response_input=verified)
        self.assertIsNone(
            extract_usable_verified_correction_response_input(context))

    def test_negative_match_count_is_not_returned(self):
        verified = _verified_input()
        verified.match_count = -1
        context = _context(verified_correction_response_input=verified)
        self.assertIsNone(
            extract_usable_verified_correction_response_input(context))


class TestReturnedValuePreservesEveryField(unittest.TestCase):
    def setUp(self):
        self.verified = _verified_input(
            text_before="a dgo here", text_after="a dog here",
            matched_text="dgo", replacement_text="dog", match_count=3,
            metadata={"source": "user_correction", "note": "x"},
        )
        self.context = _context(verified_correction_response_input=self.verified)
        self.extracted = extract_usable_verified_correction_response_input(
            self.context)

    def test_preserves_text_before(self):
        self.assertEqual(self.extracted.text_before, "a dgo here")

    def test_preserves_text_after(self):
        self.assertEqual(self.extracted.text_after, "a dog here")

    def test_preserves_matched_text(self):
        self.assertEqual(self.extracted.matched_text, "dgo")

    def test_preserves_replacement_text(self):
        self.assertEqual(self.extracted.replacement_text, "dog")

    def test_preserves_match_count(self):
        self.assertEqual(self.extracted.match_count, 3)

    def test_preserves_metadata(self):
        self.assertEqual(
            self.extracted.metadata, {"source": "user_correction", "note": "x"})


class TestSafeCopyBehavior(unittest.TestCase):
    """The extracted value is an independent copy, never the stored
    instance itself - the SAME "return an independent copy, never
    hand back shared mutable state" convention
    `VerifiedCorrectionResponseInput.copy()` already follows."""

    def test_extracted_value_is_not_the_same_object(self):
        verified = _verified_input()
        context = _context(verified_correction_response_input=verified)
        extracted = extract_usable_verified_correction_response_input(context)
        self.assertIsNot(extracted, verified)

    def test_mutating_extracted_value_does_not_reach_the_stored_input(self):
        verified = _verified_input()
        context = _context(verified_correction_response_input=verified)
        extracted = extract_usable_verified_correction_response_input(context)
        extracted.metadata["injected"] = "MUTATED"
        self.assertNotIn("injected", verified.metadata)
        self.assertNotIn(
            "injected", context.verified_correction_response_input.metadata)

    def test_mutating_extracted_value_does_not_reach_the_context(self):
        verified = _verified_input()
        context = _context(verified_correction_response_input=verified)
        extracted = extract_usable_verified_correction_response_input(context)
        extracted.metadata["injected"] = "MUTATED"
        self.assertNotIn(
            "injected", context.to_dict()["verified_correction_response_input"]["metadata"])


class TestOriginalContextRemainsUnchanged(unittest.TestCase):
    def test_context_not_mutated_by_extraction(self):
        verified = _verified_input()
        context = _context(verified_correction_response_input=verified)
        before = context.to_dict()
        extract_usable_verified_correction_response_input(context)
        self.assertEqual(context.to_dict(), before)

    def test_stored_input_not_mutated_by_extraction(self):
        verified = _verified_input()
        context = _context(verified_correction_response_input=verified)
        before = verified.to_dict()
        extract_usable_verified_correction_response_input(context)
        self.assertEqual(verified.to_dict(), before)

    def test_other_fields_unaffected_by_extraction(self):
        context = _context(verified_correction_response_input=_verified_input())
        extract_usable_verified_correction_response_input(context)
        self.assertEqual(context.status, STATUS_RESOLVED)
        self.assertEqual(context.original_message, "hello")
        self.assertIsNone(context.correction_application_result)

    def test_no_response_text_is_generated_or_modified(self):
        # This is a transport/extraction operation only - there is no
        # response text on the context to begin with, and extraction
        # must not add one.
        context = _context(verified_correction_response_input=_verified_input())
        extract_usable_verified_correction_response_input(context)
        as_dict = context.to_dict()
        self.assertNotIn("response_text", as_dict)
        self.assertIsNone(as_dict["response_action"])


class TestRepeatedExtractionIsDeterministic(unittest.TestCase):
    def test_same_context_always_produces_an_equal_result(self):
        verified = _verified_input()
        context = _context(verified_correction_response_input=verified)
        results = [
            extract_usable_verified_correction_response_input(context)
            for _ in range(5)
        ]
        for result in results:
            self.assertEqual(result, verified)

    def test_no_input_always_produces_none(self):
        context = _context(verified_correction_response_input=None)
        results = [
            extract_usable_verified_correction_response_input(context)
            for _ in range(5)
        ]
        self.assertEqual(results, [None] * 5)

    def test_equal_inputs_produce_equal_results(self):
        context_a = _context(verified_correction_response_input=_verified_input())
        context_b = _context(verified_correction_response_input=_verified_input())
        self.assertEqual(
            extract_usable_verified_correction_response_input(context_a),
            extract_usable_verified_correction_response_input(context_b),
        )


class TestExistingCallersRemainBackwardsCompatible(unittest.TestCase):
    def test_non_response_generation_context_raises_type_error(self):
        with self.assertRaises(TypeError):
            extract_usable_verified_correction_response_input({"not": "a context"})


if __name__ == "__main__":
    unittest.main()
