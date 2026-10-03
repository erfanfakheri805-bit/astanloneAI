"""
Tests for Prompt 483 - Expose Verified Correction Result in Response
Context.

Covers the small, additive integration that lets an existing
`CorrectionApplicationResult` (Prompt 474/478/479, typically one
already produced and verified by Prompt 482's
`apply_correction_request_with_validation()`) be carried through into
the existing `ResponseGenerationContext`:

    CorrectionApplicationResult                          (Prompt 474/478/479)
        -> generation_context_from_understanding()   (Prompt 483, THIS
           module's subject - response_generation_context.py)
        -> build_generation_context(...,
               correction_application_result=...)        (Prompt 483)
        -> ResponseGenerationContext.
               correction_application_result
           (dict / CorrectionApplicationResult / None)

This is transport only: nothing here applies a correction, modifies
the original message or target text, re-validates or re-verifies the
result, interprets or branches on its `status`, converts a
`NOT_APPLIED`/`FAILED` result into an `APPLIED` one, or changes what
`response_action` / guidance / selection / binding / rendering /
`correction_lookup_context` / `correction_application_candidate` are
computed to be.

Run directly:
    python -m unittest tests.test_correction_application_result_in_response_generation -v
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
from language_intelligence.correction_lookup_selection import (
    CorrectionSelectionResult, OUTCOME_SELECTED,
)
from language_intelligence.correction_application_candidate import (
    build_correction_application_candidate,
)
from language_intelligence.correction_application_request import (
    build_correction_application_request,
)
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult,
    STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED,
)
from language_intelligence.correction_application_guarded import (
    apply_correction_request_with_validation,
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


def _valid_record(key="dgo", meaning="dog", **overrides):
    record = {
        "id": 1, "language": "en", "item_type": "correction", "key": key,
        "meaning": meaning, "examples": [], "relationships": [],
        "confidence": 0.9, "source": "user_correction", "source_context": None,
        "learning_method": "explicit_correction", "version": 1,
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
    }
    record.update(overrides)
    return record


def _ready_request(**overrides):
    record = _valid_record(**overrides)
    selection_result = CorrectionSelectionResult(OUTCOME_SELECTED, correction=record)
    candidate = build_correction_application_candidate(selection_result)
    return build_correction_application_request(candidate)


def _applied_result():
    request = _ready_request(key="dgo", meaning="dog")
    # Goes through the full, verified Prompt 482 flow - a genuine,
    # verified APPLIED result, exactly what this field is meant to carry.
    return apply_correction_request_with_validation(request, "a dgo here")


def _not_applied_result():
    request = _ready_request(key="dgo", meaning="dog")
    return apply_correction_request_with_validation(request, "no match here")


def _failed_result():
    return CorrectionApplicationResult(STATUS_FAILED, reason="request_not_valid")


class _FakeUnderstanding:
    """A stand-in for LanguageUnderstandingResult carrying only what
    generation_context_from_understanding() reads (response_plan,
    learned_sentence_structure, correction_lookup_context,
    correction_application_candidate, correction_application_result) -
    keeps these tests focused on Prompt 483's own transport, not on
    driving a full real understanding pipeline (already covered
    elsewhere)."""

    def __init__(self, response_plan, correction_application_result=None):
        self.response_plan = response_plan
        self.learned_sentence_structure = None
        self.correction_lookup_context = None
        self.correction_application_candidate = None
        self.correction_application_result = correction_application_result


class TestContextWithoutCorrectionResultRemainsUnchanged(unittest.TestCase):
    """Existing ResponseGenerationContext works without a correction
    result - the field remains None and nothing else changes."""

    def test_build_generation_context_default_is_none(self):
        context = build_generation_context(_minimal_plan())
        self.assertIsNone(context.correction_application_result)

    def test_to_dict_includes_the_field_as_none_by_default(self):
        context = build_generation_context(_minimal_plan())
        as_dict = context.to_dict()
        self.assertIn("correction_application_result", as_dict)
        self.assertIsNone(as_dict["correction_application_result"])

    def test_generation_context_from_understanding_with_no_attribute_set(self):
        understanding = _FakeUnderstanding(_minimal_plan())
        # No existing code path sets correction_application_result on a
        # real LanguageUnderstandingResult yet - del it here to mimic
        # that exactly. getattr(..., None) covers both cases.
        del understanding.correction_application_result
        context = generation_context_from_understanding(understanding)
        self.assertIsNone(context.correction_application_result)

    def test_other_fields_unaffected_when_no_result_is_attached(self):
        plan = _minimal_plan(original_message="Python is a programming language.")
        context = build_generation_context(plan)
        self.assertEqual(context.status, STATUS_UNRESOLVED)
        self.assertIsNone(context.response_action)
        self.assertIsNone(context.correction_application_candidate)


class TestVerifiedAppliedResultCanBeStored(unittest.TestCase):
    """A verified APPLIED CorrectionApplicationResult can be stored in
    context, with all of its fields preserved."""

    def test_build_generation_context_carries_it_through(self):
        result = _applied_result()
        context = build_generation_context(
            _minimal_plan(), correction_application_result=result)
        self.assertIs(context.correction_application_result, result)

    def test_generation_context_from_understanding_carries_it_through(self):
        result = _applied_result()
        understanding = _FakeUnderstanding(_minimal_plan(), result)
        context = generation_context_from_understanding(understanding)
        self.assertIs(context.correction_application_result, result)

    def test_to_dict_exposes_the_transferred_result(self):
        result = _applied_result()
        understanding = _FakeUnderstanding(_minimal_plan(), result)
        context = generation_context_from_understanding(understanding)
        as_dict = context.to_dict()
        self.assertEqual(
            as_dict["correction_application_result"], result.to_dict())

    def test_stored_result_preserves_all_correction_fields(self):
        result = _applied_result()
        context = build_generation_context(
            _minimal_plan(), correction_application_result=result)
        carried = context.to_dict()["correction_application_result"]
        self.assertEqual(carried["status"], STATUS_APPLIED)
        self.assertTrue(carried["applied"])
        self.assertEqual(carried["text_before"], "a dgo here")
        self.assertEqual(carried["text_after"], "a dog here")
        self.assertEqual(carried["matched_text"], "dgo")
        self.assertEqual(carried["replacement_text"], "dog")
        self.assertEqual(carried["match_count"], 1)
        self.assertEqual(carried["original_text"], "a dgo here")
        self.assertEqual(carried["corrected_text"], "a dog here")


class TestNotAppliedResultIsNotTreatedAsSuccessful(unittest.TestCase):
    """A NOT_APPLIED result is carried through unchanged and never
    treated as, or converted into, a successful correction."""

    def test_not_applied_result_can_be_attached(self):
        result = _not_applied_result()
        context = build_generation_context(
            _minimal_plan(), correction_application_result=result)
        carried = context.to_dict()["correction_application_result"]
        self.assertEqual(carried["status"], STATUS_NOT_APPLIED)
        self.assertFalse(carried["applied"])
        self.assertEqual(carried["match_count"], 0)

    def test_not_applied_result_is_not_upgraded_to_applied(self):
        result = _not_applied_result()
        context = build_generation_context(
            _minimal_plan(), correction_application_result=result)
        carried = context.to_dict()["correction_application_result"]
        self.assertNotEqual(carried["status"], STATUS_APPLIED)


class TestFailedResultIsNotTreatedAsSuccessful(unittest.TestCase):
    """A FAILED result is carried through unchanged and never treated
    as, or converted into, a successful correction."""

    def test_failed_result_can_be_attached(self):
        result = _failed_result()
        context = build_generation_context(
            _minimal_plan(), correction_application_result=result)
        carried = context.to_dict()["correction_application_result"]
        self.assertEqual(carried["status"], STATUS_FAILED)
        self.assertFalse(carried["applied"])
        self.assertEqual(carried["match_count"], 0)

    def test_failed_result_is_not_upgraded_to_applied(self):
        result = _failed_result()
        context = build_generation_context(
            _minimal_plan(), correction_application_result=result)
        carried = context.to_dict()["correction_application_result"]
        self.assertNotEqual(carried["status"], STATUS_APPLIED)


class TestExistingFieldsRemainUnchangedWhenResultAttached(unittest.TestCase):
    """Existing response-generation fields remain unchanged when a
    correction result is attached."""

    def test_other_fields_unaffected_by_attaching_a_result(self):
        result = _applied_result()
        plan = _minimal_plan(original_message="Python is a programming language.")
        without = build_generation_context(plan)
        with_result = build_generation_context(
            plan, correction_application_result=result)

        without_dict = without.to_dict()
        with_dict = with_result.to_dict()
        del without_dict["correction_application_result"]
        del with_dict["correction_application_result"]
        self.assertEqual(without_dict, with_dict)

    def test_status_and_response_action_are_unaffected(self):
        result = _applied_result()
        context = build_generation_context(
            _minimal_plan(), correction_application_result=result)
        self.assertEqual(context.status, STATUS_UNRESOLVED)
        self.assertIsNone(context.response_action)
        self.assertTrue(context.unresolved)

    def test_correction_application_candidate_is_unaffected(self):
        result = _applied_result()
        context = build_generation_context(
            _minimal_plan(), correction_application_result=result)
        self.assertIsNone(context.correction_application_candidate)


class TestSafeCopyPreservesTheCorrectionResult(unittest.TestCase):
    """to_dict() (this project's safe-copy/serialization convention
    for context objects) preserves the correction result and never
    lets a caller mutate the stored one through it."""

    def test_to_dict_call_does_not_mutate_the_stored_result(self):
        result = _applied_result()
        context = build_generation_context(
            _minimal_plan(), correction_application_result=result)
        context.to_dict()
        context.to_dict()
        self.assertEqual(context.correction_application_result, result)

    def test_mutating_returned_dict_never_reaches_the_result(self):
        result = _applied_result()
        context = build_generation_context(
            _minimal_plan(), correction_application_result=result)
        as_dict = context.to_dict()
        as_dict["correction_application_result"]["matched_text"] = "MUTATED"
        self.assertEqual(result.matched_text, "dgo")

    def test_source_result_object_unchanged_after_being_carried(self):
        result = _applied_result()
        before = result.to_dict()
        understanding = _FakeUnderstanding(_minimal_plan(), result)
        generation_context_from_understanding(understanding)
        self.assertEqual(result.to_dict(), before)


class TestExistingCallersRemainBackwardsCompatible(unittest.TestCase):
    """Existing ResponseGenerationContext / build_generation_context /
    generation_context_from_understanding callers remain compatible."""

    def test_positional_construction_without_new_kwarg_still_works(self):
        context = ResponseGenerationContext(
            "hi", STATUS_UNRESOLVED, None, None, [], None, {}, None, [], None, "en", None, [],
        )
        self.assertIsNone(context.correction_application_result)
        self.assertIn("correction_application_result", context.to_dict())

    def test_build_generation_context_without_new_kwarg_still_works(self):
        context = build_generation_context(_minimal_plan(), sentence_structure=None)
        self.assertIsNone(context.correction_application_result)

    def test_construction_with_only_correction_application_candidate_kwarg_still_works(self):
        # Prompt 471's own kwarg still works unaffected by Prompt 483's
        # new one.
        context = ResponseGenerationContext(
            "hi", STATUS_UNRESOLVED, None, None, [], None, {}, None, [], None, "en", None, [],
            correction_application_candidate={"is_valid": False},
        )
        self.assertEqual(
            context.correction_application_candidate, {"is_valid": False})
        self.assertIsNone(context.correction_application_result)

    def test_generation_context_from_understanding_without_attribute_still_works(self):
        understanding = _FakeUnderstanding(_minimal_plan())
        del understanding.correction_application_result
        context = generation_context_from_understanding(understanding)
        self.assertIsNone(context.correction_application_result)
        self.assertIsNone(context.correction_application_candidate)


class TestRepeatedContextConstructionIsDeterministic(unittest.TestCase):

    def test_repeated_build_generation_context_produces_equal_dicts(self):
        result = _applied_result()
        plan = _minimal_plan()
        first = build_generation_context(
            plan, correction_application_result=result).to_dict()
        second = build_generation_context(
            plan, correction_application_result=result).to_dict()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
