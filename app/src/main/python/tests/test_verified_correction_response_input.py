"""
Tests for Prompt 485 - Verified Correction Response Input.

`VerifiedCorrectionResponseInput`
(language_intelligence/verified_correction_response_input.py) is a
small, deterministic, read-only structure representing one already-
applied, already-verified correction. It performs no correction
application, no matching, no text modification, and is not connected
to response generation. Covers:

    1. valid verified correction input
    2. missing text_before
    3. missing text_after
    4. missing matched_text
    5. missing replacement_text
    6. zero match_count
    7. negative match_count
    8. exact string preservation
    9. metadata preservation
    10. safe copy
    11. serialization/deserialization
    12. equality/comparison
    13. deterministic construction

Run directly:
    python -m unittest tests.test_verified_correction_response_input -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.verified_correction_response_input import (
    VerifiedCorrectionResponseInput,
    build_verified_correction_response_input,
)


def _valid_kwargs(**overrides):
    fields = dict(
        text_before="I has a dgo",
        text_after="I has a dog",
        matched_text="dgo",
        replacement_text="dog",
        match_count=1,
    )
    fields.update(overrides)
    return fields


class TestValidVerifiedCorrectionInput(unittest.TestCase):
    def test_valid_instance_constructs(self):
        instance = VerifiedCorrectionResponseInput(**_valid_kwargs())
        self.assertEqual(instance.text_before, "I has a dgo")
        self.assertEqual(instance.text_after, "I has a dog")
        self.assertEqual(instance.matched_text, "dgo")
        self.assertEqual(instance.replacement_text, "dog")
        self.assertEqual(instance.match_count, 1)
        self.assertEqual(instance.metadata, {})

    def test_builder_function_produces_equivalent_instance(self):
        instance = build_verified_correction_response_input(**_valid_kwargs())
        self.assertEqual(instance, VerifiedCorrectionResponseInput(**_valid_kwargs()))


class TestMissingTextBefore(unittest.TestCase):
    def test_none_text_before_raises(self):
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput(**_valid_kwargs(text_before=None))

    def test_empty_text_before_raises(self):
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput(**_valid_kwargs(text_before=""))

    def test_blank_text_before_raises(self):
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput(**_valid_kwargs(text_before="   "))


class TestMissingTextAfter(unittest.TestCase):
    def test_none_text_after_raises(self):
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput(**_valid_kwargs(text_after=None))

    def test_empty_text_after_raises(self):
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput(**_valid_kwargs(text_after=""))


class TestMissingMatchedText(unittest.TestCase):
    def test_none_matched_text_raises(self):
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput(**_valid_kwargs(matched_text=None))

    def test_empty_matched_text_raises(self):
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput(**_valid_kwargs(matched_text=""))


class TestMissingReplacementText(unittest.TestCase):
    def test_none_replacement_text_raises(self):
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput(**_valid_kwargs(replacement_text=None))

    def test_empty_replacement_text_raises(self):
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput(**_valid_kwargs(replacement_text=""))


class TestZeroMatchCount(unittest.TestCase):
    def test_zero_match_count_raises(self):
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput(**_valid_kwargs(match_count=0))


class TestNegativeMatchCount(unittest.TestCase):
    def test_negative_match_count_raises(self):
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput(**_valid_kwargs(match_count=-1))

    def test_non_int_match_count_raises(self):
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput(**_valid_kwargs(match_count="1"))


class TestExactStringPreservation(unittest.TestCase):
    def test_strings_are_never_normalized(self):
        instance = VerifiedCorrectionResponseInput(
            text_before="  I has a dgo  extra spaces",
            text_after="  I has a dog  extra spaces",
            matched_text="dgo",
            replacement_text="dog",
            match_count=1,
        )
        self.assertEqual(instance.text_before, "  I has a dgo  extra spaces")
        self.assertEqual(instance.text_after, "  I has a dog  extra spaces")

    def test_case_is_never_altered(self):
        instance = VerifiedCorrectionResponseInput(
            **_valid_kwargs(matched_text="DGO", replacement_text="Dog")
        )
        self.assertEqual(instance.matched_text, "DGO")
        self.assertEqual(instance.replacement_text, "Dog")


class TestMetadataPreservation(unittest.TestCase):
    def test_metadata_defaults_to_empty_dict(self):
        instance = VerifiedCorrectionResponseInput(**_valid_kwargs())
        self.assertEqual(instance.metadata, {})

    def test_metadata_is_preserved(self):
        instance = VerifiedCorrectionResponseInput(
            **_valid_kwargs(metadata={"source": "user_correction"})
        )
        self.assertEqual(instance.metadata, {"source": "user_correction"})

    def test_metadata_is_deep_copied_at_construction(self):
        original_metadata = {"nested": {"a": 1}}
        instance = VerifiedCorrectionResponseInput(
            **_valid_kwargs(metadata=original_metadata)
        )
        original_metadata["nested"]["a"] = 999
        self.assertEqual(instance.metadata, {"nested": {"a": 1}})

    def test_returned_to_dict_metadata_does_not_leak(self):
        instance = VerifiedCorrectionResponseInput(
            **_valid_kwargs(metadata={"nested": {"a": 1}})
        )
        as_dict = instance.to_dict()
        as_dict["metadata"]["nested"]["a"] = 999
        self.assertEqual(instance.metadata, {"nested": {"a": 1}})


class TestSafeCopy(unittest.TestCase):
    def test_copy_equals_original(self):
        instance = VerifiedCorrectionResponseInput(**_valid_kwargs())
        self.assertEqual(instance.copy(), instance)

    def test_copy_is_independent(self):
        instance = VerifiedCorrectionResponseInput(
            **_valid_kwargs(metadata={"nested": {"a": 1}})
        )
        duplicate = instance.copy()
        duplicate.metadata["nested"]["a"] = 999
        self.assertEqual(instance.metadata, {"nested": {"a": 1}})


class TestSerializationDeserialization(unittest.TestCase):
    def test_to_dict_shape(self):
        instance = VerifiedCorrectionResponseInput(
            **_valid_kwargs(metadata={"source": "user_correction"})
        )
        self.assertEqual(instance.to_dict(), {
            "text_before": "I has a dgo",
            "text_after": "I has a dog",
            "matched_text": "dgo",
            "replacement_text": "dog",
            "match_count": 1,
            "metadata": {"source": "user_correction"},
        })

    def test_from_dict_round_trip(self):
        instance = VerifiedCorrectionResponseInput(
            **_valid_kwargs(metadata={"source": "user_correction"})
        )
        rebuilt = VerifiedCorrectionResponseInput.from_dict(instance.to_dict())
        self.assertEqual(rebuilt, instance)

    def test_from_dict_requires_a_dict(self):
        with self.assertRaises(TypeError):
            VerifiedCorrectionResponseInput.from_dict("not a dict")
        with self.assertRaises(TypeError):
            VerifiedCorrectionResponseInput.from_dict(None)

    def test_from_dict_missing_required_field_raises(self):
        data = _valid_kwargs()
        del data["matched_text"]
        with self.assertRaises(TypeError):
            VerifiedCorrectionResponseInput.from_dict(data)

    def test_from_dict_invalid_value_raises_value_error(self):
        data = _valid_kwargs(match_count=0)
        with self.assertRaises(ValueError):
            VerifiedCorrectionResponseInput.from_dict(data)


class TestEqualityComparison(unittest.TestCase):
    def test_equal_instances_compare_equal(self):
        a = VerifiedCorrectionResponseInput(**_valid_kwargs())
        b = VerifiedCorrectionResponseInput(**_valid_kwargs())
        self.assertEqual(a, b)

    def test_different_field_makes_instances_unequal(self):
        a = VerifiedCorrectionResponseInput(**_valid_kwargs())
        b = VerifiedCorrectionResponseInput(**_valid_kwargs(match_count=2))
        self.assertNotEqual(a, b)

    def test_not_equal_to_other_types(self):
        a = VerifiedCorrectionResponseInput(**_valid_kwargs())
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, None)


class TestDeterministicConstruction(unittest.TestCase):
    def test_same_inputs_always_produce_equal_instances(self):
        instances = [
            VerifiedCorrectionResponseInput(**_valid_kwargs()) for _ in range(5)
        ]
        for instance in instances[1:]:
            self.assertEqual(instance, instances[0])

    def test_to_dict_is_stable_across_calls(self):
        instance = VerifiedCorrectionResponseInput(**_valid_kwargs())
        first = instance.to_dict()
        second = instance.to_dict()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)


if __name__ == "__main__":
    unittest.main()
