"""
Tests for Prompt 471 - Expose Correction Application Candidate to
Response Context.

Covers the small, additive integration that lets Prompt 470's
`CorrectionApplicationCandidate`
(correction_application_candidate.py) be carried through into the
existing `ResponseGenerationContext`:

    CorrectionApplicationCandidate                       (Prompt 470)
        -> generation_context_from_understanding()   (Prompt 471, THIS
           module's subject - response_generation_context.py)
        -> build_generation_context(...,
               correction_application_candidate=...)     (Prompt 471)
        -> ResponseGenerationContext.
               correction_application_candidate
           (dict / CorrectionApplicationCandidate / None)

This is transport only: nothing here builds a candidate, applies a
stored correction, modifies the original message, modifies stored
learning records, or changes what `response_action` / guidance /
selection / binding / rendering / `correction_lookup_context` are
computed to be.

Run directly:
    python -m unittest tests.test_correction_application_candidate_in_response_generation -v
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
from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate, build_correction_application_candidate,
)
from language_intelligence.correction_lookup_selection import (
    CorrectionSelectionResult, OUTCOME_SELECTED, OUTCOME_NOT_FOUND,
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


def _valid_candidate(**overrides):
    record = _valid_record(**overrides)
    selection_result = CorrectionSelectionResult(OUTCOME_SELECTED, correction=record)
    return build_correction_application_candidate(selection_result)


def _invalid_candidate():
    return build_correction_application_candidate(
        CorrectionSelectionResult(OUTCOME_NOT_FOUND))


class _FakeUnderstanding:
    """A stand-in for LanguageUnderstandingResult carrying only what
    generation_context_from_understanding() reads (response_plan,
    learned_sentence_structure, correction_lookup_context,
    correction_application_candidate) - keeps these tests focused on
    Prompt 471's own transport, not on driving a full real
    understanding pipeline (already covered elsewhere)."""

    def __init__(self, response_plan, correction_application_candidate=None):
        self.response_plan = response_plan
        self.learned_sentence_structure = None
        self.correction_lookup_context = None
        self.correction_application_candidate = correction_application_candidate


class TestExistingContextStillWorksWithoutCandidate(unittest.TestCase):
    """Existing ResponseGenerationContext works without a candidate."""

    def test_build_generation_context_default_is_none(self):
        context = build_generation_context(_minimal_plan())
        self.assertIsNone(context.correction_application_candidate)

    def test_to_dict_includes_the_field_as_none_by_default(self):
        context = build_generation_context(_minimal_plan())
        as_dict = context.to_dict()
        self.assertIn("correction_application_candidate", as_dict)
        self.assertIsNone(as_dict["correction_application_candidate"])

    def test_generation_context_from_understanding_with_no_attribute_set(self):
        understanding = _FakeUnderstanding(_minimal_plan())
        # No existing code path sets correction_application_candidate on
        # a real LanguageUnderstandingResult yet - del it here to mimic
        # that exactly. getattr(..., None) covers both cases.
        del understanding.correction_application_candidate
        context = generation_context_from_understanding(understanding)
        self.assertIsNone(context.correction_application_candidate)

    def test_generation_context_from_understanding_returns_none_without_plan(self):
        understanding = _FakeUnderstanding(None)
        self.assertIsNone(generation_context_from_understanding(understanding))


class TestValidCandidateCanBeAttached(unittest.TestCase):
    """A valid candidate can be attached and its fields preserved."""

    def test_build_generation_context_carries_it_through(self):
        candidate = _valid_candidate()
        context = build_generation_context(
            _minimal_plan(), correction_application_candidate=candidate)
        self.assertIs(context.correction_application_candidate, candidate)

    def test_generation_context_from_understanding_carries_it_through(self):
        candidate = _valid_candidate()
        understanding = _FakeUnderstanding(_minimal_plan(), candidate)
        context = generation_context_from_understanding(understanding)
        self.assertIs(context.correction_application_candidate, candidate)

    def test_to_dict_exposes_the_transferred_candidate(self):
        candidate = _valid_candidate()
        understanding = _FakeUnderstanding(_minimal_plan(), candidate)
        context = generation_context_from_understanding(understanding)
        as_dict = context.to_dict()
        self.assertEqual(
            as_dict["correction_application_candidate"], candidate.to_dict())

    def test_candidate_fields_preserved_in_context(self):
        candidate = _valid_candidate(
            key="dgo", meaning="dog", language="en",
            source="user_correction", confidence=0.75)
        context = build_generation_context(
            _minimal_plan(), correction_application_candidate=candidate)
        carried = context.to_dict()["correction_application_candidate"]
        self.assertTrue(carried["is_valid"])
        self.assertEqual(carried["original_expression"], "dgo")
        self.assertEqual(carried["corrected_expression_or_meaning"], "dog")
        self.assertEqual(carried["language"], "en")
        self.assertIsNone(carried["locale"])
        self.assertEqual(carried["source"], "user_correction")
        self.assertEqual(carried["confidence"], 0.75)


class TestInvalidOrNoCandidateRemainsAbsent(unittest.TestCase):
    """An invalid/no candidate remains absent (None) - never guessed
    or partially filled."""

    def test_no_candidate_argument_remains_none(self):
        context = build_generation_context(_minimal_plan())
        self.assertIsNone(context.correction_application_candidate)

    def test_invalid_candidate_carried_through_as_is_not_upgraded(self):
        # An invalid candidate object, if a caller ever explicitly
        # passes one, is still carried through unchanged - this
        # integration never decides validity or discards it itself.
        candidate = _invalid_candidate()
        context = build_generation_context(
            _minimal_plan(), correction_application_candidate=candidate)
        carried = context.to_dict()["correction_application_candidate"]
        self.assertFalse(carried["is_valid"])
        self.assertIsNone(carried["original_expression"])

    def test_understanding_without_attribute_produces_none(self):
        understanding = _FakeUnderstanding(_minimal_plan())
        del understanding.correction_application_candidate
        context = generation_context_from_understanding(understanding)
        self.assertIsNone(context.correction_application_candidate)


class TestExistingFieldsRemainUnchanged(unittest.TestCase):
    """Existing response-generation fields remain unchanged when a
    candidate is attached."""

    def test_other_fields_unaffected_by_attaching_a_candidate(self):
        candidate = _valid_candidate()
        plan = _minimal_plan(original_message="Python is a programming language.")
        without = build_generation_context(plan)
        with_candidate = build_generation_context(
            plan, correction_application_candidate=candidate)

        without_dict = without.to_dict()
        with_dict = with_candidate.to_dict()
        del without_dict["correction_application_candidate"]
        del with_dict["correction_application_candidate"]
        self.assertEqual(without_dict, with_dict)

    def test_status_and_response_action_are_unaffected(self):
        candidate = _valid_candidate()
        context = build_generation_context(
            _minimal_plan(), correction_application_candidate=candidate)
        self.assertEqual(context.status, STATUS_UNRESOLVED)
        self.assertIsNone(context.response_action)
        self.assertTrue(context.unresolved)

    def test_correction_lookup_context_is_unaffected(self):
        candidate = _valid_candidate()
        context = build_generation_context(
            _minimal_plan(), correction_application_candidate=candidate)
        self.assertIsNone(context.correction_lookup_context)


class TestCandidateDataIsNotMutatedDuringConstruction(unittest.TestCase):
    """Candidate data is not mutated during context construction."""

    def test_candidate_object_unchanged_after_being_carried(self):
        candidate = _valid_candidate()
        before = candidate.copy()
        understanding = _FakeUnderstanding(_minimal_plan(), candidate)
        generation_context_from_understanding(understanding)
        self.assertEqual(candidate, before)

    def test_to_dict_call_does_not_mutate_the_stored_candidate(self):
        candidate = _valid_candidate()
        context = build_generation_context(
            _minimal_plan(), correction_application_candidate=candidate)
        context.to_dict()
        context.to_dict()
        self.assertEqual(context.correction_application_candidate, candidate)

    def test_mutating_returned_dict_never_reaches_the_candidate(self):
        candidate = _valid_candidate()
        context = build_generation_context(
            _minimal_plan(), correction_application_candidate=candidate)
        as_dict = context.to_dict()
        as_dict["correction_application_candidate"]["original_expression"] = "MUTATED"
        self.assertEqual(candidate.original_expression, "dgo")


class TestExistingCallersRemainBackwardsCompatible(unittest.TestCase):
    """Existing callers remain backwards compatible."""

    def test_positional_construction_without_new_kwarg_still_works(self):
        context = ResponseGenerationContext(
            "hi", STATUS_UNRESOLVED, None, None, [], None, {}, None, [], None, "en", None, [],
        )
        self.assertIsNone(context.correction_application_candidate)
        self.assertIn("correction_application_candidate", context.to_dict())

    def test_build_generation_context_without_new_kwarg_still_works(self):
        context = build_generation_context(_minimal_plan(), sentence_structure=None)
        self.assertIsNone(context.correction_application_candidate)

    def test_construction_with_only_correction_lookup_context_kwarg_still_works(self):
        # Prompt 467's own kwarg still works unaffected by Prompt 471's
        # new one.
        context = ResponseGenerationContext(
            "hi", STATUS_UNRESOLVED, None, None, [], None, {}, None, [], None, "en", None, [],
            correction_lookup_context={"status": "NOT_FOUND"},
        )
        self.assertEqual(context.correction_lookup_context, {"status": "NOT_FOUND"})
        self.assertIsNone(context.correction_application_candidate)

    def test_existing_optional_fields_still_work_together(self):
        context = ResponseGenerationContext(
            "hi", STATUS_UNRESOLVED, None, None, [], None, {}, None, [], None, "en", None, [],
            language_guidance={"status": "NOT_FOUND"},
        )
        self.assertEqual(context.language_guidance, {"status": "NOT_FOUND"})
        self.assertIsNone(context.correction_application_candidate)


if __name__ == "__main__":
    unittest.main()
