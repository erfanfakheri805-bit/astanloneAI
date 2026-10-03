"""
Tests for Prompt 494 - Expose Corrected Response Target in Response
Context.

`with_corrected_response_target()` (language_intelligence/
corrected_response_target_context.py) attaches Prompt 493's prepared
corrected response target onto a NEW `ResponseGenerationContext`
(response_generation_context.py), via its new, additive,
`corrected_response_target` field (default `None`). No correction
lookup, matching, learning, or response-text modification happens
here. Covers:

    1. request without correction instruction -> context target is None
    2. valid correction instruction -> corrected target appears in context
    3. exact corrected text is preserved
    4. existing context fields remain unchanged
    5. the original context is never mutated
    6. ResponseGenerationContext.corrected_response_target defaults to
       None for existing callers (backward compatibility)
    7. to_dict() round-trips the new field
    8. wrong-typed arguments raise TypeError

Run directly:
    python -m unittest tests.test_corrected_response_target_context -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_generation import ResponseGenerationRequest
from language_intelligence.response_generation_context import ResponseGenerationContext
from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
)
from language_intelligence.corrected_response_target_context import (
    with_corrected_response_target,
)


def _instruction(**overrides):
    fields = dict(
        source_text="I has a dgo",
        corrected_text="I has a dog",
        matched_text="dgo",
        replacement_text="dog",
        match_count=1,
    )
    fields.update(overrides)
    return VerifiedCorrectionResponseInstruction(**fields)


class _NoPlanUnderstanding:
    """Minimal stand-in with no `response_plan` attribute."""
    pass


def _plain_context(**overrides):
    fields = dict(
        original_message="hello",
        status="RESOLVED",
        response_action="GREET",
        meaning="greeting",
        meaning_candidates=[],
        matched_pattern=None,
        variables={},
        active_topic=None,
        references=[],
        context=None,
        language="en",
        locale=None,
        unresolved_requirements=[],
    )
    fields.update(overrides)
    return ResponseGenerationContext(**fields)


class TestWithCorrectedResponseTarget(unittest.TestCase):

    def test_request_without_instruction_yields_none_target(self):
        context = _plain_context()
        request = ResponseGenerationRequest(_NoPlanUnderstanding())
        result = with_corrected_response_target(context, request)
        self.assertIsNone(result.corrected_response_target)

    def test_valid_instruction_appears_in_context(self):
        context = _plain_context()
        instruction = _instruction(corrected_text="I has a dog")
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=instruction
        )
        result = with_corrected_response_target(context, request)
        self.assertEqual(result.corrected_response_target, "I has a dog")

    def test_exact_corrected_text_preserved(self):
        context = _plain_context()
        instruction = _instruction(corrected_text="  Exact Corrected Text!  ")
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=instruction
        )
        result = with_corrected_response_target(context, request)
        self.assertEqual(result.corrected_response_target, "  Exact Corrected Text!  ")

    def test_existing_context_fields_remain_unchanged(self):
        context = _plain_context(
            original_message="original text",
            status="RESOLVED",
            response_action="PROVIDE_INFORMATION",
            meaning="some meaning",
            language="fa",
            locale="fa_IR",
        )
        instruction = _instruction()
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=instruction
        )
        result = with_corrected_response_target(context, request)
        self.assertEqual(result.original_message, "original text")
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual(result.response_action, "PROVIDE_INFORMATION")
        self.assertEqual(result.meaning, "some meaning")
        self.assertEqual(result.language, "fa")
        self.assertEqual(result.locale, "fa_IR")

    def test_original_context_never_mutated(self):
        context = _plain_context()
        before = context.to_dict()
        instruction = _instruction()
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=instruction
        )
        with_corrected_response_target(context, request)
        after = context.to_dict()
        self.assertEqual(before, after)
        self.assertIsNone(context.corrected_response_target)

    def test_returns_new_instance_not_same_object(self):
        context = _plain_context()
        request = ResponseGenerationRequest(_NoPlanUnderstanding())
        result = with_corrected_response_target(context, request)
        self.assertIsNot(result, context)

    def test_default_field_is_none_for_existing_callers(self):
        # Backward compatibility: existing ResponseGenerationContext
        # construction with no corrected_response_target argument.
        context = _plain_context()
        self.assertIsNone(context.corrected_response_target)
        self.assertIn("corrected_response_target", context.to_dict())
        self.assertIsNone(context.to_dict()["corrected_response_target"])

    def test_to_dict_round_trips_new_field(self):
        context = _plain_context()
        instruction = _instruction(corrected_text="round trip target")
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=instruction
        )
        result = with_corrected_response_target(context, request)
        self.assertEqual(result.to_dict()["corrected_response_target"], "round trip target")

    def test_wrong_typed_arguments_raise_type_error(self):
        context = _plain_context()
        request = ResponseGenerationRequest(_NoPlanUnderstanding())
        with self.assertRaises(TypeError):
            with_corrected_response_target("not a context", request)
        with self.assertRaises(TypeError):
            with_corrected_response_target(context, "not a request")


if __name__ == "__main__":
    unittest.main()
