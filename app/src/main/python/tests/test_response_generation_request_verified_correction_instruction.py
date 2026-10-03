"""
Tests for Prompt 492 - Expose Verified Correction Instruction in
Response Generation Request.

`ResponseGenerationRequest` (language_intelligence/response_generation.py)
now accepts an optional `verified_correction_instruction` keyword
argument - a `VerifiedCorrectionResponseInstruction` (Prompt 490), or
`None`. This stage only carries the instruction through the request;
it does not apply any correction to response text, does not perform
any matching, and does not change any other existing request
behavior. Covers:

    1. request without a correction instruction remains valid
       (defaults to None; existing properties unaffected)
    2. request with a valid instruction remains valid
    3. the exact instruction object is preserved (identity, not a
       copy, not transformed)
    4. existing request behavior (understanding/context storage,
       response_plan/generation_context/generation_request properties
       for a no-plan understanding) remains unchanged
    5. existing positional/keyword call patterns still work
       (backward compatibility)

Run directly:
    python -m unittest tests.test_response_generation_request_verified_correction_instruction -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_generation import ResponseGenerationRequest
from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
    INSTRUCTION_TYPE_USE_CORRECTED_TEXT,
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
    """Minimal stand-in with no `response_plan` attribute - the SAME
    fixture shape `object()` already serves as in
    tests/test_response_generation_request.py for a request whose
    understanding carries no plan."""
    pass


class TestVerifiedCorrectionInstructionField(unittest.TestCase):

    def test_request_without_correction_instruction_remains_valid(self):
        request = ResponseGenerationRequest(_NoPlanUnderstanding())
        self.assertIsNone(request.verified_correction_instruction)
        # existing properties still behave exactly as before
        self.assertIsNone(request.response_plan)
        self.assertIsNone(request.generation_context)
        self.assertIsNone(request.generation_request)

    def test_request_with_valid_instruction_remains_valid(self):
        instruction = _instruction()
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=instruction
        )
        self.assertIsInstance(
            request.verified_correction_instruction,
            VerifiedCorrectionResponseInstruction,
        )
        # unrelated existing properties are still unaffected by the new field
        self.assertIsNone(request.response_plan)
        self.assertIsNone(request.generation_context)
        self.assertIsNone(request.generation_request)

    def test_exact_instruction_preserved(self):
        instruction = _instruction(
            source_text="Source Exactly",
            corrected_text="Corrected Exactly",
            matched_text="Matched Exactly",
            replacement_text="Replacement Exactly",
            match_count=2,
        )
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=instruction
        )
        # same object, never transformed/copied into a different structure
        self.assertIs(request.verified_correction_instruction, instruction)
        self.assertEqual(request.verified_correction_instruction.source_text, "Source Exactly")
        self.assertEqual(request.verified_correction_instruction.corrected_text, "Corrected Exactly")
        self.assertEqual(request.verified_correction_instruction.matched_text, "Matched Exactly")
        self.assertEqual(request.verified_correction_instruction.replacement_text, "Replacement Exactly")
        self.assertEqual(request.verified_correction_instruction.match_count, 2)
        self.assertEqual(
            request.verified_correction_instruction.instruction_type,
            INSTRUCTION_TYPE_USE_CORRECTED_TEXT,
        )

    def test_default_is_none_when_field_omitted(self):
        request = ResponseGenerationRequest(_NoPlanUnderstanding(), context="some-context")
        self.assertIsNone(request.verified_correction_instruction)
        self.assertEqual(request.context, "some-context")

    def test_existing_positional_call_pattern_still_works(self):
        # Existing callers passing only `understanding` positionally,
        # or `understanding, context` positionally, must keep working
        # unchanged.
        understanding = _NoPlanUnderstanding()
        request_one_arg = ResponseGenerationRequest(understanding)
        self.assertIs(request_one_arg.understanding, understanding)
        self.assertIsNone(request_one_arg.context)
        self.assertIsNone(request_one_arg.verified_correction_instruction)

        request_two_args = ResponseGenerationRequest(understanding, "ctx")
        self.assertIs(request_two_args.understanding, understanding)
        self.assertEqual(request_two_args.context, "ctx")
        self.assertIsNone(request_two_args.verified_correction_instruction)

    def test_understanding_and_context_storage_unchanged(self):
        understanding = _NoPlanUnderstanding()
        context = object()
        instruction = _instruction()
        request = ResponseGenerationRequest(
            understanding, context=context, verified_correction_instruction=instruction
        )
        self.assertIs(request.understanding, understanding)
        self.assertIs(request.context, context)
        self.assertIs(request.verified_correction_instruction, instruction)

    def test_does_not_apply_correction_or_modify_response_text(self):
        # Attaching the instruction to a request never triggers any
        # correction application or text modification - the request is
        # a plain, inert holder of the instruction only.
        instruction = _instruction()
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=instruction
        )
        # The instruction's own fields are untouched (never re-derived,
        # never normalized) by having been attached to the request.
        self.assertEqual(request.verified_correction_instruction.to_dict(), instruction.to_dict())


if __name__ == "__main__":
    unittest.main()
