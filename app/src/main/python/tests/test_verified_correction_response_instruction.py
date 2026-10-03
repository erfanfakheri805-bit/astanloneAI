"""
Tests for Prompt 490 - Create Verified Correction Response Instruction.

`VerifiedCorrectionResponseInstruction`
(language_intelligence/verified_correction_response_instruction.py) is
a small, deterministic, read-only structure representing one
instruction that a verified correction is available and its corrected
form should be used. It is not yet wired into response generation, the
correction-learning system, or correction application - this module
covers only the structure itself and its validation:

    1. valid construction succeeds and preserves every field
    2. missing/blank source_text raises ValueError
    3. missing/blank corrected_text raises ValueError
    4. missing/blank matched_text raises ValueError
    5. missing/blank replacement_text raises ValueError
    6. zero/negative match_count raises ValueError
    7. an unsupported instruction_type raises ValueError
    8. instruction_type defaults to USE_CORRECTED_TEXT
    9. to_dict() round-trips via from_dict()
    10. copy() returns an independent, equal instance
    11. equality is value-based
    12. the builder function matches direct construction
    13. exact strings are never normalized

Run directly:
    python -m unittest tests.test_verified_correction_response_instruction -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
    build_verified_correction_response_instruction,
    INSTRUCTION_TYPE_USE_CORRECTED_TEXT,
)


def _instruction(**overrides):
    fields = dict(
        source_text="a dgo here",
        corrected_text="a dog here",
        matched_text="dgo",
        replacement_text="dog",
        match_count=1,
    )
    fields.update(overrides)
    return build_verified_correction_response_instruction(**fields)


class TestValidConstructionPreservesFields(unittest.TestCase):
    def test_fields_are_preserved_exactly(self):
        instruction = _instruction()
        self.assertEqual(instruction.source_text, "a dgo here")
        self.assertEqual(instruction.corrected_text, "a dog here")
        self.assertEqual(instruction.matched_text, "dgo")
        self.assertEqual(instruction.replacement_text, "dog")
        self.assertEqual(instruction.match_count, 1)
        self.assertEqual(
            instruction.instruction_type, INSTRUCTION_TYPE_USE_CORRECTED_TEXT)

    def test_instruction_type_defaults_to_use_corrected_text(self):
        instruction = build_verified_correction_response_instruction(
            source_text="x", corrected_text="y",
            matched_text="x", replacement_text="y", match_count=1)
        self.assertEqual(
            instruction.instruction_type, INSTRUCTION_TYPE_USE_CORRECTED_TEXT)

    def test_direct_construction_matches_builder(self):
        via_class = VerifiedCorrectionResponseInstruction(
            source_text="a dgo here", corrected_text="a dog here",
            matched_text="dgo", replacement_text="dog", match_count=1)
        via_builder = _instruction()
        self.assertEqual(via_class, via_builder)


class TestRequiredTextFieldsMustBePresent(unittest.TestCase):
    def test_missing_source_text_raises(self):
        with self.assertRaises(ValueError):
            _instruction(source_text=None)

    def test_blank_source_text_raises(self):
        with self.assertRaises(ValueError):
            _instruction(source_text="   ")

    def test_missing_corrected_text_raises(self):
        with self.assertRaises(ValueError):
            _instruction(corrected_text="")

    def test_missing_matched_text_raises(self):
        with self.assertRaises(ValueError):
            _instruction(matched_text=None)

    def test_missing_replacement_text_raises(self):
        with self.assertRaises(ValueError):
            _instruction(replacement_text="")


class TestMatchCountMustBeGreaterThanZero(unittest.TestCase):
    def test_zero_match_count_raises(self):
        with self.assertRaises(ValueError):
            _instruction(match_count=0)

    def test_negative_match_count_raises(self):
        with self.assertRaises(ValueError):
            _instruction(match_count=-1)

    def test_non_int_match_count_raises(self):
        with self.assertRaises(ValueError):
            _instruction(match_count="1")


class TestInstructionTypeMustBeUseCorrectedText(unittest.TestCase):
    def test_unsupported_instruction_type_raises(self):
        with self.assertRaises(ValueError):
            _instruction(instruction_type="SOMETHING_ELSE")

    def test_none_instruction_type_raises(self):
        with self.assertRaises(ValueError):
            _instruction(instruction_type=None)

    def test_explicit_supported_instruction_type_is_accepted(self):
        instruction = _instruction(
            instruction_type=INSTRUCTION_TYPE_USE_CORRECTED_TEXT)
        self.assertEqual(
            instruction.instruction_type, INSTRUCTION_TYPE_USE_CORRECTED_TEXT)


class TestToDictAndFromDictRoundTrip(unittest.TestCase):
    def test_to_dict_shape(self):
        instruction = _instruction()
        self.assertEqual(instruction.to_dict(), {
            "source_text": "a dgo here",
            "corrected_text": "a dog here",
            "matched_text": "dgo",
            "replacement_text": "dog",
            "match_count": 1,
            "instruction_type": "USE_CORRECTED_TEXT",
        })

    def test_from_dict_reconstructs_an_equal_instance(self):
        instruction = _instruction()
        rebuilt = VerifiedCorrectionResponseInstruction.from_dict(
            instruction.to_dict())
        self.assertEqual(rebuilt, instruction)

    def test_from_dict_requires_a_dict(self):
        with self.assertRaises(TypeError):
            VerifiedCorrectionResponseInstruction.from_dict("not a dict")

    def test_from_dict_with_invalid_value_raises_value_error(self):
        data = _instruction().to_dict()
        data["match_count"] = 0
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInstruction.from_dict(data)


class TestCopyReturnsAnIndependentEqualInstance(unittest.TestCase):
    def test_copy_is_equal_but_not_the_same_object(self):
        instruction = _instruction()
        copied = instruction.copy()
        self.assertEqual(copied, instruction)
        self.assertIsNot(copied, instruction)

    def test_copy_preserves_every_field(self):
        instruction = _instruction(match_count=4)
        copied = instruction.copy()
        self.assertEqual(copied.source_text, instruction.source_text)
        self.assertEqual(copied.corrected_text, instruction.corrected_text)
        self.assertEqual(copied.matched_text, instruction.matched_text)
        self.assertEqual(copied.replacement_text, instruction.replacement_text)
        self.assertEqual(copied.match_count, 4)
        self.assertEqual(copied.instruction_type, instruction.instruction_type)


class TestEqualityIsValueBased(unittest.TestCase):
    def test_equal_fields_produce_equal_instances(self):
        self.assertEqual(_instruction(), _instruction())

    def test_different_fields_produce_unequal_instances(self):
        self.assertNotEqual(_instruction(), _instruction(match_count=2))

    def test_not_equal_to_a_non_instruction(self):
        self.assertNotEqual(_instruction(), {"source_text": "a dgo here"})


class TestExactStringsAreNeverNormalized(unittest.TestCase):
    def test_strings_are_stored_verbatim(self):
        instruction = _instruction(
            source_text="  A DGO  ", corrected_text="  A DOG  ",
            matched_text="DGO", replacement_text="DOG")
        self.assertEqual(instruction.source_text, "  A DGO  ")
        self.assertEqual(instruction.corrected_text, "  A DOG  ")
        self.assertEqual(instruction.matched_text, "DGO")
        self.assertEqual(instruction.replacement_text, "DOG")


if __name__ == "__main__":
    unittest.main()
