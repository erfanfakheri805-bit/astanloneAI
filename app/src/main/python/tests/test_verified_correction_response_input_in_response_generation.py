"""
Tests for Prompt 487 - Expose Verified Correction Input in Response
Context.

Covers the small, additive integration that lets an existing
`VerifiedCorrectionResponseInput` (Prompt 485,
verified_correction_response_input.py) be carried through into the
existing `ResponseGenerationContext`:

    VerifiedCorrectionResponseInput                     (Prompt 485)
        -> generation_context_from_understanding()   (Prompt 487, THIS
           module's subject - response_generation_context.py)
        -> build_generation_context(...,
               verified_correction_response_input=...)   (Prompt 487)
        -> ResponseGenerationContext.
               verified_correction_response_input
           (dict / VerifiedCorrectionResponseInput / None)

This is transport only: nothing here applies a correction, performs
matching (fuzzy, semantic, embeddings, spelling-correction,
normalization, guessing, ranking, or confidence-based), modifies the
original message or target text, or changes what `response_action` /
guidance / selection / binding / rendering / `correction_lookup_context`
/ `correction_application_candidate` / `correction_application_result`
are computed to be.

Run directly:
    python -m unittest tests.test_verified_correction_response_input_in_response_generation -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_generation_context import (
    ResponseGenerationContext, build_generation_context,
    generation_context_from_understanding,
)
from language_intelligence.response_planning import STATUS_UNRESOLVED
from language_intelligence.verified_correction_response_input import (
    VerifiedCorrectionResponseInput,
    build_verified_correction_response_input,
)


def _minimal_plan(**overrides):
    """A minimal, directly-built plan dict - exactly the fields
    `build_generation_context()` reads (see that module's `_PLAN_FIELDS`).
    UNRESOLVED so guidance/selection/binding/rendering all take their
    simplest, no-op path."""
    plan = {
        "original_message": "hello there",
        "status": STATUS_UNRESOLVED,
        "response_action": None,
        "meaning": None,
        "meaning_candidates": [],
        "matched_pattern": None,
        "variables": {},
        "active_topic": None,
        "references": [],
        "context": None,
        "detected_language": "en",
        "locale": None,
        "unresolved_requirements": [],
    }
    plan.update(overrides)
    return plan


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


class _FakeUnderstanding:
    """A stand-in for LanguageUnderstandingResult carrying only what
    generation_context_from_understanding() reads (response_plan,
    learned_sentence_structure, correction_lookup_context,
    correction_application_candidate, correction_application_result,
    verified_correction_response_input) - keeps these tests focused on
    Prompt 487's own transport, not on driving a full real
    understanding pipeline (already covered elsewhere)."""

    def __init__(self, response_plan, verified_correction_response_input=None):
        self.response_plan = response_plan
        self.learned_sentence_structure = None
        self.correction_lookup_context = None
        self.correction_application_candidate = None
        self.correction_application_result = None
        self.verified_correction_response_input = verified_correction_response_input


class TestContextWithoutVerifiedCorrectionInputRemainsUnchanged(unittest.TestCase):
    """Existing ResponseGenerationContext works without a verified
    correction input - the field remains None and nothing else
    changes."""

    def test_build_generation_context_default_is_none(self):
        context = build_generation_context(_minimal_plan())
        self.assertIsNone(context.verified_correction_response_input)

    def test_to_dict_includes_the_field_as_none_by_default(self):
        context = build_generation_context(_minimal_plan())
        as_dict = context.to_dict()
        self.assertIn("verified_correction_response_input", as_dict)
        self.assertIsNone(as_dict["verified_correction_response_input"])

    def test_generation_context_from_understanding_with_no_attribute_set(self):
        understanding = _FakeUnderstanding(_minimal_plan())
        # No existing code path sets verified_correction_response_input
        # on a real LanguageUnderstandingResult yet - del it here to
        # mimic that exactly. getattr(..., None) covers both cases.
        del understanding.verified_correction_response_input
        context = generation_context_from_understanding(understanding)
        self.assertIsNone(context.verified_correction_response_input)

    def test_other_fields_unaffected_when_no_input_is_attached(self):
        plan = _minimal_plan(original_message="Python is a programming language.")
        context = build_generation_context(plan)
        self.assertEqual(context.status, STATUS_UNRESOLVED)
        self.assertIsNone(context.response_action)
        self.assertIsNone(context.correction_application_result)


class TestValidVerifiedCorrectionInputCanBeStored(unittest.TestCase):
    """A valid VerifiedCorrectionResponseInput can be stored in
    context, with all of its fields and metadata preserved."""

    def test_build_generation_context_carries_it_through(self):
        verified = _verified_input()
        context = build_generation_context(
            _minimal_plan(), verified_correction_response_input=verified)
        self.assertIs(context.verified_correction_response_input, verified)

    def test_generation_context_from_understanding_carries_it_through(self):
        verified = _verified_input()
        understanding = _FakeUnderstanding(_minimal_plan(), verified)
        context = generation_context_from_understanding(understanding)
        self.assertIs(context.verified_correction_response_input, verified)

    def test_to_dict_exposes_the_transferred_input(self):
        verified = _verified_input()
        understanding = _FakeUnderstanding(_minimal_plan(), verified)
        context = generation_context_from_understanding(understanding)
        as_dict = context.to_dict()
        self.assertEqual(
            as_dict["verified_correction_response_input"], verified.to_dict())

    def test_stored_input_preserves_all_fields(self):
        verified = _verified_input()
        context = build_generation_context(
            _minimal_plan(), verified_correction_response_input=verified)
        carried = context.to_dict()["verified_correction_response_input"]
        self.assertEqual(carried["text_before"], "a dgo here")
        self.assertEqual(carried["text_after"], "a dog here")
        self.assertEqual(carried["matched_text"], "dgo")
        self.assertEqual(carried["replacement_text"], "dog")
        self.assertEqual(carried["match_count"], 1)

    def test_stored_input_preserves_metadata(self):
        verified = _verified_input(metadata={"source": "user_correction", "note": "x"})
        context = build_generation_context(
            _minimal_plan(), verified_correction_response_input=verified)
        carried = context.to_dict()["verified_correction_response_input"]
        self.assertEqual(
            carried["metadata"], {"source": "user_correction", "note": "x"})

    def test_text_is_not_modified_merely_by_storing_it(self):
        verified = _verified_input(
            text_before="a dgo here", text_after="a dog here")
        context = build_generation_context(
            _minimal_plan(), verified_correction_response_input=verified)
        carried = context.to_dict()["verified_correction_response_input"]
        self.assertEqual(carried["text_before"], "a dgo here")
        self.assertEqual(carried["text_after"], "a dog here")


class TestExistingFieldsRemainUnchangedWhenInputAttached(unittest.TestCase):
    """Existing response-generation fields, including no response text
    being changed, remain unchanged when a verified correction input is
    attached."""

    def test_other_fields_unaffected_by_attaching_an_input(self):
        verified = _verified_input()
        plan = _minimal_plan(original_message="Python is a programming language.")
        without = build_generation_context(plan)
        with_input = build_generation_context(
            plan, verified_correction_response_input=verified)

        without_dict = without.to_dict()
        with_dict = with_input.to_dict()
        del without_dict["verified_correction_response_input"]
        del with_dict["verified_correction_response_input"]
        self.assertEqual(without_dict, with_dict)

    def test_status_and_response_action_are_unaffected(self):
        verified = _verified_input()
        context = build_generation_context(
            _minimal_plan(), verified_correction_response_input=verified)
        self.assertEqual(context.status, STATUS_UNRESOLVED)
        self.assertIsNone(context.response_action)
        self.assertTrue(context.unresolved)

    def test_original_message_is_unaffected(self):
        verified = _verified_input()
        plan = _minimal_plan(original_message="unchanged message")
        context = build_generation_context(
            plan, verified_correction_response_input=verified)
        self.assertEqual(context.original_message, "unchanged message")

    def test_correction_application_result_is_unaffected(self):
        verified = _verified_input()
        context = build_generation_context(
            _minimal_plan(), verified_correction_response_input=verified)
        self.assertIsNone(context.correction_application_result)
        self.assertIsNone(context.correction_application_candidate)
        self.assertIsNone(context.correction_lookup_context)


class TestSafeCopyPreservesTheVerifiedCorrectionInput(unittest.TestCase):
    """to_dict() (this project's safe-copy/serialization convention for
    context objects) preserves the verified correction input and never
    lets a caller mutate the stored one through it."""

    def test_to_dict_call_does_not_mutate_the_stored_input(self):
        verified = _verified_input()
        context = build_generation_context(
            _minimal_plan(), verified_correction_response_input=verified)
        context.to_dict()
        context.to_dict()
        self.assertEqual(context.verified_correction_response_input, verified)

    def test_mutating_returned_dict_never_reaches_the_input(self):
        verified = _verified_input()
        context = build_generation_context(
            _minimal_plan(), verified_correction_response_input=verified)
        as_dict = context.to_dict()
        as_dict["verified_correction_response_input"]["matched_text"] = "MUTATED"
        as_dict["verified_correction_response_input"]["metadata"]["note"] = "MUTATED"
        self.assertEqual(verified.matched_text, "dgo")
        self.assertNotIn("note", verified.metadata)

    def test_source_input_object_unchanged_after_being_carried(self):
        verified = _verified_input()
        before = verified.to_dict()
        understanding = _FakeUnderstanding(_minimal_plan(), verified)
        generation_context_from_understanding(understanding)
        self.assertEqual(verified.to_dict(), before)

    def test_equality_is_preserved_across_a_carried_round_trip(self):
        verified = _verified_input()
        context = build_generation_context(
            _minimal_plan(), verified_correction_response_input=verified)
        # Reconstructing from the carried dict yields an equal input -
        # equality/comparison is preserved through storage.
        rebuilt = VerifiedCorrectionResponseInput.from_dict(
            context.to_dict()["verified_correction_response_input"])
        self.assertEqual(rebuilt, verified)


class TestExistingCallersRemainBackwardsCompatible(unittest.TestCase):
    """Existing ResponseGenerationContext / build_generation_context /
    generation_context_from_understanding callers remain compatible."""

    def test_positional_construction_without_new_kwarg_still_works(self):
        context = ResponseGenerationContext(
            "hi", STATUS_UNRESOLVED, None, None, [], None, {}, None, [], None, "en", None, [],
        )
        self.assertIsNone(context.verified_correction_response_input)
        self.assertIn("verified_correction_response_input", context.to_dict())

    def test_build_generation_context_without_new_kwarg_still_works(self):
        context = build_generation_context(_minimal_plan(), sentence_structure=None)
        self.assertIsNone(context.verified_correction_response_input)

    def test_construction_with_only_correction_application_result_kwarg_still_works(self):
        # Prompt 483's own kwarg still works unaffected by Prompt 487's
        # new one.
        context = ResponseGenerationContext(
            "hi", STATUS_UNRESOLVED, None, None, [], None, {}, None, [], None, "en", None, [],
            correction_application_result={"status": "FAILED"},
        )
        self.assertEqual(
            context.correction_application_result, {"status": "FAILED"})
        self.assertIsNone(context.verified_correction_response_input)

    def test_generation_context_from_understanding_without_attribute_still_works(self):
        understanding = _FakeUnderstanding(_minimal_plan())
        del understanding.verified_correction_response_input
        context = generation_context_from_understanding(understanding)
        self.assertIsNone(context.verified_correction_response_input)
        self.assertIsNone(context.correction_application_result)


class TestRepeatedContextConstructionIsDeterministic(unittest.TestCase):

    def test_repeated_build_generation_context_produces_equal_dicts(self):
        verified = _verified_input()
        plan = _minimal_plan()
        first = build_generation_context(
            plan, verified_correction_response_input=verified).to_dict()
        second = build_generation_context(
            plan, verified_correction_response_input=verified).to_dict()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
