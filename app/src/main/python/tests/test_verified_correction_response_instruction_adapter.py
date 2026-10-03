"""
Tests for Prompt 491 - Build Verified Correction Response Instruction.

`build_verified_correction_response_instruction_from_input()`
(language_intelligence/verified_correction_response_instruction_adapter.py)
converts an already-validated and usable `VerifiedCorrectionResponseInput`
(Prompt 485) into a `VerifiedCorrectionResponseInstruction` (Prompt 490),
reusing the EXISTING Prompt 488 usability rules unmodified. It performs
no response text modification, no new text matching, and never modifies
the input it is given. Covers:

    1. valid usable input -> instruction created
    2. None input -> None
    3. non-VerifiedCorrectionResponseInput input -> None
    4. values preserved exactly (source_text/corrected_text/matched_text/
       replacement_text/match_count)
    5. instruction_type is always USE_CORRECTED_TEXT
    6. deterministic repeated conversion
    7. the returned instruction is a fresh instance
    8. original input is never mutated

Run directly:
    python -m unittest tests.test_verified_correction_response_instruction_adapter -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.verified_correction_response_input import (
    VerifiedCorrectionResponseInput,
)
from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
    INSTRUCTION_TYPE_USE_CORRECTED_TEXT,
)
from language_intelligence.verified_correction_response_instruction_adapter import (
    build_verified_correction_response_instruction_from_input,
)


def _valid_input(**overrides):
    fields = dict(
        text_before="I has a dgo",
        text_after="I has a dog",
        matched_text="dgo",
        replacement_text="dog",
        match_count=1,
        metadata={"note": "test"},
    )
    fields.update(overrides)
    return VerifiedCorrectionResponseInput(**fields)


class TestBuildVerifiedCorrectionResponseInstruction(unittest.TestCase):

    def test_valid_input_produces_expected_instruction(self):
        verified_input = _valid_input()
        instruction = build_verified_correction_response_instruction_from_input(
            verified_input
        )
        self.assertIsInstance(instruction, VerifiedCorrectionResponseInstruction)

    def test_none_input_returns_none(self):
        self.assertIsNone(
            build_verified_correction_response_instruction_from_input(None)
        )

    def test_wrong_type_input_returns_none(self):
        self.assertIsNone(
            build_verified_correction_response_instruction_from_input(
                {"text_before": "a", "text_after": "b"}
            )
        )
        self.assertIsNone(
            build_verified_correction_response_instruction_from_input("not an input")
        )

    def test_values_preserved_exactly(self):
        verified_input = _valid_input(
            text_before="Source Text Exactly",
            text_after="Corrected Text Exactly",
            matched_text="Matched Exactly",
            replacement_text="Replacement Exactly",
            match_count=3,
        )
        instruction = build_verified_correction_response_instruction_from_input(
            verified_input
        )
        self.assertEqual(instruction.source_text, "Source Text Exactly")
        self.assertEqual(instruction.corrected_text, "Corrected Text Exactly")
        self.assertEqual(instruction.matched_text, "Matched Exactly")
        self.assertEqual(instruction.replacement_text, "Replacement Exactly")
        self.assertEqual(instruction.match_count, 3)

    def test_instruction_type_is_use_corrected_text(self):
        instruction = build_verified_correction_response_instruction_from_input(
            _valid_input()
        )
        self.assertEqual(instruction.instruction_type, INSTRUCTION_TYPE_USE_CORRECTED_TEXT)
        self.assertEqual(instruction.instruction_type, "USE_CORRECTED_TEXT")

    def test_deterministic_repeated_conversion(self):
        verified_input = _valid_input()
        first = build_verified_correction_response_instruction_from_input(verified_input)
        second = build_verified_correction_response_instruction_from_input(verified_input)
        self.assertEqual(first, second)

    def test_returns_fresh_instance_not_shared(self):
        verified_input = _valid_input()
        first = build_verified_correction_response_instruction_from_input(verified_input)
        second = build_verified_correction_response_instruction_from_input(verified_input)
        self.assertIsNot(first, second)

    def test_original_input_never_mutated(self):
        verified_input = _valid_input()
        before = verified_input.to_dict()
        build_verified_correction_response_instruction_from_input(verified_input)
        after = verified_input.to_dict()
        self.assertEqual(before, after)

    def test_does_not_modify_response_text_or_apply_correction(self):
        # The operation only builds an instruction object - it never
        # touches any external text or performs any replacement itself.
        verified_input = _valid_input()
        instruction = build_verified_correction_response_instruction_from_input(
            verified_input
        )
        # source_text/corrected_text on the instruction are exactly the
        # values already carried by the verified input - nothing new
        # was computed, matched, or replaced.
        self.assertEqual(instruction.source_text, verified_input.text_before)
        self.assertEqual(instruction.corrected_text, verified_input.text_after)


if __name__ == "__main__":
    unittest.main()
