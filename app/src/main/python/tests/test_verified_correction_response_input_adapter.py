"""
Tests for Prompt 486 - Build Verified Correction Response Input.

`build_verified_correction_response_input_from_result()`
(language_intelligence/verified_correction_response_input_adapter.py)
converts a valid, successfully-applied
`CorrectionApplicationResult` into a `VerifiedCorrectionResponseInput`
(Prompt 485), reusing the EXISTING Prompt 480
`validate_applied_correction_result()` unmodified. It performs no
correction application, no new text matching, and never modifies the
result it is given. Covers:

    1. valid APPLIED result -> verified response input created
    2. NOT_APPLIED -> no verified input
    3. FAILED -> no verified input
    4. applied=False -> no verified input
    5. zero match count -> no verified input
    6. missing required field -> no verified input
    7. invalid verification -> no verified input
    8. exact text preservation
    9. exact matched/replacement text preservation
    10. metadata preservation
    11. deterministic repeated conversion

Run directly:
    python -m unittest tests.test_verified_correction_response_input_adapter -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_application_result import (
    CorrectionApplicationResult,
    STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED,
)
from language_intelligence.verified_correction_response_input import (
    VerifiedCorrectionResponseInput,
)
from language_intelligence.verified_correction_response_input_adapter import (
    build_verified_correction_response_input_from_result,
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


class TestValidAppliedResultCreatesVerifiedInput(unittest.TestCase):
    def test_valid_applied_result_produces_verified_input(self):
        result = _applied_result()
        verified = build_verified_correction_response_input_from_result(result)
        self.assertIsInstance(verified, VerifiedCorrectionResponseInput)
        self.assertEqual(verified.text_before, "I has a dgo")
        self.assertEqual(verified.text_after, "I has a dog")
        self.assertEqual(verified.matched_text, "dgo")
        self.assertEqual(verified.replacement_text, "dog")
        self.assertEqual(verified.match_count, 1)


class TestNotAppliedProducesNoVerifiedInput(unittest.TestCase):
    def test_not_applied_returns_none(self):
        result = CorrectionApplicationResult(
            status=STATUS_NOT_APPLIED,
            original_text="hello",
            text_before="hello",
            text_after="hello",
            match_count=0,
        )
        self.assertIsNone(build_verified_correction_response_input_from_result(result))


class TestFailedProducesNoVerifiedInput(unittest.TestCase):
    def test_failed_returns_none(self):
        result = CorrectionApplicationResult(
            status=STATUS_FAILED,
            original_text="hello",
            reason="storage_unavailable",
            match_count=0,
        )
        self.assertIsNone(build_verified_correction_response_input_from_result(result))


class TestAppliedFalseProducesNoVerifiedInput(unittest.TestCase):
    def test_applied_flag_forced_false_returns_none(self):
        # CorrectionApplicationResult always derives `applied` from
        # `status`, so an APPLIED-status/applied=False combination is
        # not producible through the normal constructor path - assign
        # the attribute directly purely to exercise this defensive
        # branch of the adapter itself.
        result = _applied_result()
        result.applied = False
        self.assertIsNone(build_verified_correction_response_input_from_result(result))


class TestZeroMatchCountProducesNoVerifiedInput(unittest.TestCase):
    def test_zero_match_count_returns_none(self):
        result = _applied_result(match_count=0)
        self.assertIsNone(build_verified_correction_response_input_from_result(result))

    def test_negative_match_count_returns_none(self):
        result = _applied_result(match_count=-1)
        self.assertIsNone(build_verified_correction_response_input_from_result(result))


class TestMissingRequiredFieldProducesNoVerifiedInput(unittest.TestCase):
    def test_missing_text_before_returns_none(self):
        result = _applied_result(text_before=None, original_text=None)
        self.assertIsNone(build_verified_correction_response_input_from_result(result))

    def test_missing_text_after_returns_none(self):
        result = _applied_result(text_after=None, corrected_text=None)
        self.assertIsNone(build_verified_correction_response_input_from_result(result))

    def test_missing_matched_text_returns_none(self):
        result = _applied_result(matched_text=None)
        self.assertIsNone(build_verified_correction_response_input_from_result(result))

    def test_missing_replacement_text_returns_none(self):
        result = _applied_result(replacement_text=None)
        self.assertIsNone(build_verified_correction_response_input_from_result(result))


class TestInvalidVerificationProducesNoVerifiedInput(unittest.TestCase):
    def test_text_after_not_matching_exact_replacement_returns_none(self):
        # matched_text/replacement_text claim a correction that does
        # not actually correspond to text_before -> text_after; the
        # existing validate_applied_correction_result() must catch
        # this exactly as it already does for any other caller.
        result = _applied_result(
            text_before="I has a dgo",
            text_after="something completely different",
        )
        self.assertIsNone(build_verified_correction_response_input_from_result(result))

    def test_matched_text_not_present_in_text_before_returns_none(self):
        result = _applied_result(
            matched_text="not present anywhere",
            text_before="I has a dgo",
            text_after="I has a dog",
        )
        self.assertIsNone(build_verified_correction_response_input_from_result(result))


class TestExactTextPreservation(unittest.TestCase):
    def test_text_before_and_after_preserved_exactly(self):
        result = _applied_result(
            text_before="  She recieve the package  ",
            text_after="  She receive the package  ",
            matched_text="recieve",
            replacement_text="receive",
        )
        verified = build_verified_correction_response_input_from_result(result)
        self.assertEqual(verified.text_before, "  She recieve the package  ")
        self.assertEqual(verified.text_after, "  She receive the package  ")


class TestExactMatchedReplacementTextPreservation(unittest.TestCase):
    def test_matched_and_replacement_text_preserved_exactly(self):
        result = _applied_result(matched_text="DGO", replacement_text="Dog",
                                  text_before="DGO", text_after="Dog")
        verified = build_verified_correction_response_input_from_result(result)
        self.assertEqual(verified.matched_text, "DGO")
        self.assertEqual(verified.replacement_text, "Dog")


class TestMetadataPreservation(unittest.TestCase):
    def test_metadata_is_carried_through(self):
        result = _applied_result(metadata={"source": "user_correction"})
        verified = build_verified_correction_response_input_from_result(result)
        self.assertEqual(verified.metadata, {"source": "user_correction"})

    def test_metadata_mutation_on_result_after_conversion_does_not_change_verified(self):
        result = _applied_result(metadata={"nested": {"a": 1}})
        verified = build_verified_correction_response_input_from_result(result)
        result.metadata["nested"]["a"] = 999
        self.assertEqual(verified.metadata, {"nested": {"a": 1}})

    def test_no_metadata_defaults_to_empty_dict(self):
        result = _applied_result()
        verified = build_verified_correction_response_input_from_result(result)
        self.assertEqual(verified.metadata, {})


class TestDeterministicRepeatedConversion(unittest.TestCase):
    def test_same_result_always_produces_equal_verified_input(self):
        result = _applied_result()
        outcomes = [
            build_verified_correction_response_input_from_result(result)
            for _ in range(5)
        ]
        for outcome in outcomes[1:]:
            self.assertEqual(outcome, outcomes[0])

    def test_same_not_applied_result_always_produces_none(self):
        result = CorrectionApplicationResult(
            status=STATUS_NOT_APPLIED, original_text="hello",
            text_before="hello", text_after="hello", match_count=0,
        )
        outcomes = [
            build_verified_correction_response_input_from_result(result)
            for _ in range(5)
        ]
        self.assertEqual(outcomes, [None] * 5)


class TestAdapterDoesNotMutateTheResult(unittest.TestCase):
    def test_result_unchanged_after_conversion(self):
        result = _applied_result()
        before = result.to_dict()
        build_verified_correction_response_input_from_result(result)
        self.assertEqual(result.to_dict(), before)


class TestInvalidTypeRaises(unittest.TestCase):
    def test_invalid_type_raises_type_error(self):
        with self.assertRaises(TypeError):
            build_verified_correction_response_input_from_result({"status": "APPLIED"})
        with self.assertRaises(TypeError):
            build_verified_correction_response_input_from_result(None)


if __name__ == "__main__":
    unittest.main()
