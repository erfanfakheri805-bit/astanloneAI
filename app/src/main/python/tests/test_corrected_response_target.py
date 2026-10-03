"""
Tests for Prompt 493 - Prepare Corrected Response Target.

`prepare_corrected_response_target()` (language_intelligence/
corrected_response_target.py) reads the EXISTING
`ResponseGenerationRequest.verified_correction_instruction` (Prompt
492) and returns ONLY the corrected target text
(`VerifiedCorrectionResponseInstruction.corrected_text`, Prompt 490)
it already carries - no correction application, no text replacement,
no matching, no response generation. Covers:

    1. request without an instruction (None) -> None
    2. invalid/unusable instruction (wrong type stored) -> None
    3. valid instruction -> expected corrected target
    4. corrected target is preserved exactly
    5. calling the operation does not mutate the request
    6. calling the operation does not mutate the instruction
    7. wrong-typed `request` argument raises TypeError
    8. deterministic repeated calls

Run directly:
    python -m unittest tests.test_corrected_response_target -v
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
)
from language_intelligence.corrected_response_target import (
    prepare_corrected_response_target,
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
    fixture shape used in tests/test_response_generation_request_
    verified_correction_instruction.py."""
    pass


class TestPrepareCorrectedResponseTarget(unittest.TestCase):

    def test_request_without_instruction_returns_none(self):
        request = ResponseGenerationRequest(_NoPlanUnderstanding())
        self.assertIsNone(prepare_corrected_response_target(request))

    def test_invalid_unusable_instruction_returns_none(self):
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(),
            verified_correction_instruction={"corrected_text": "not a real instruction"},
        )
        self.assertIsNone(prepare_corrected_response_target(request))

    def test_valid_instruction_returns_expected_corrected_target(self):
        instruction = _instruction(corrected_text="I has a dog")
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=instruction
        )
        self.assertEqual(prepare_corrected_response_target(request), "I has a dog")

    def test_corrected_target_preserved_exactly(self):
        instruction = _instruction(corrected_text="  Exact Corrected Text!  ")
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=instruction
        )
        self.assertEqual(
            prepare_corrected_response_target(request), "  Exact Corrected Text!  "
        )

    def test_does_not_mutate_request(self):
        instruction = _instruction()
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), context="ctx", verified_correction_instruction=instruction
        )
        prepare_corrected_response_target(request)
        self.assertIs(request.verified_correction_instruction, instruction)
        self.assertEqual(request.context, "ctx")

    def test_does_not_mutate_instruction(self):
        instruction = _instruction()
        before = instruction.to_dict()
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=instruction
        )
        prepare_corrected_response_target(request)
        self.assertEqual(instruction.to_dict(), before)

    def test_wrong_typed_request_raises_type_error(self):
        with self.assertRaises(TypeError):
            prepare_corrected_response_target(None)
        with self.assertRaises(TypeError):
            prepare_corrected_response_target("not a request")

    def test_deterministic_repeated_calls(self):
        instruction = _instruction()
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=instruction
        )
        first = prepare_corrected_response_target(request)
        second = prepare_corrected_response_target(request)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
