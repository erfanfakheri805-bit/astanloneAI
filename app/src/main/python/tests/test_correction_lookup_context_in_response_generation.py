"""
Tests for Prompt 467 - Carry Correction Context into Response
Generation Context.

Covers the small, additive integration that lets Prompt 466's
`LanguageUnderstandingResult.correction_lookup_context` (Prompt 465's
`CorrectionLookupContext`) be carried through into the existing
`ResponseGenerationContext`:

    LanguageUnderstandingResult.correction_lookup_context   (Prompt 466)
        -> generation_context_from_understanding()   (Prompt 467, THIS
           module's subject - response_generation_context.py)
        -> build_generation_context(..., correction_lookup_context=...)
           (Prompt 467)
        -> ResponseGenerationContext.correction_lookup_context
           (dict / CorrectionLookupContext / None)

This is transport only: nothing here performs a correction lookup,
applies a stored correction, modifies the original message, or changes
what `response_action` / guidance / selection / binding / rendering
are computed to be.

Run directly:
    python -m unittest tests.test_correction_lookup_context_in_response_generation -v
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
from language_intelligence.correction_lookup_context import (
    build_correction_lookup_context,
)
from language_intelligence.correction_learning_exact_lookup_result import (
    CorrectionLearningExactLookupResult,
    STATUS_FOUND, STATUS_NOT_FOUND, STATUS_FAILED,
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


def _found_lookup_result(records=None):
    return CorrectionLearningExactLookupResult(
        status=STATUS_FOUND,
        original_expression="dgo",
        records=records if records is not None else [
            {"corrected_expression": "dog", "language": "en", "source": "user_correction"},
        ],
    )


def _not_found_lookup_result():
    return CorrectionLearningExactLookupResult(
        status=STATUS_NOT_FOUND, original_expression="dgo", records=[],
    )


def _failed_lookup_result():
    return CorrectionLearningExactLookupResult(
        status=STATUS_FAILED, original_expression="dgo", records=[],
        reason="storage_unavailable",
    )


class _FakeUnderstanding:
    """A stand-in for LanguageUnderstandingResult carrying only what
    generation_context_from_understanding() reads (response_plan,
    learned_sentence_structure, correction_lookup_context) - keeps
    these tests focused on Prompt 467's own transport, not on driving
    a full real understanding pipeline (already covered elsewhere)."""

    def __init__(self, response_plan, correction_lookup_context=None):
        self.response_plan = response_plan
        self.learned_sentence_structure = None
        self.correction_lookup_context = correction_lookup_context


class TestExistingContextStillWorksWithoutCorrectionContext(unittest.TestCase):
    """Existing response-generation context still works without
    correction context."""

    def test_build_generation_context_default_is_none(self):
        context = build_generation_context(_minimal_plan())
        self.assertIsNone(context.correction_lookup_context)

    def test_to_dict_includes_the_field_as_none_by_default(self):
        context = build_generation_context(_minimal_plan())
        as_dict = context.to_dict()
        self.assertIn("correction_lookup_context", as_dict)
        self.assertIsNone(as_dict["correction_lookup_context"])

    def test_generation_context_from_understanding_with_no_field_set(self):
        understanding = _FakeUnderstanding(_minimal_plan())
        # correction_lookup_context defaults to None on the fake, just
        # like a pre-Prompt-466 LanguageUnderstandingResult would have
        # no such attribute at all - getattr(..., None) covers both.
        del understanding.correction_lookup_context
        context = generation_context_from_understanding(understanding)
        self.assertIsNone(context.correction_lookup_context)

    def test_generation_context_from_understanding_returns_none_without_plan(self):
        understanding = _FakeUnderstanding(None)
        self.assertIsNone(generation_context_from_understanding(understanding))


class TestCorrectionContextIsTransferredWhenPresent(unittest.TestCase):
    """Correction context is transferred when present."""

    def test_build_generation_context_carries_it_through(self):
        context_obj = build_correction_lookup_context(_found_lookup_result())
        context = build_generation_context(
            _minimal_plan(), correction_lookup_context=context_obj)
        self.assertIs(context.correction_lookup_context, context_obj)

    def test_generation_context_from_understanding_carries_it_through(self):
        context_obj = build_correction_lookup_context(_found_lookup_result())
        understanding = _FakeUnderstanding(_minimal_plan(), context_obj)
        context = generation_context_from_understanding(understanding)
        self.assertIs(context.correction_lookup_context, context_obj)

    def test_to_dict_exposes_the_transferred_context(self):
        context_obj = build_correction_lookup_context(_found_lookup_result())
        understanding = _FakeUnderstanding(_minimal_plan(), context_obj)
        context = generation_context_from_understanding(understanding)
        as_dict = context.to_dict()
        self.assertEqual(as_dict["correction_lookup_context"], context_obj.to_dict())


class TestFoundContextIsPreserved(unittest.TestCase):
    """FOUND context is preserved."""

    def test_found_status_and_fields_preserved(self):
        context_obj = build_correction_lookup_context(_found_lookup_result())
        understanding = _FakeUnderstanding(_minimal_plan(), context_obj)
        result = generation_context_from_understanding(understanding).to_dict()
        carried = result["correction_lookup_context"]
        self.assertEqual(carried["status"], STATUS_FOUND)
        self.assertEqual(carried["original_expression"], "dgo")
        self.assertEqual(len(carried["records"]), 1)
        self.assertEqual(carried["language"], "en")
        self.assertEqual(carried["source"], "user_correction")
        self.assertIsNone(carried["reason"])


class TestNotFoundContextIsPreserved(unittest.TestCase):
    """NOT_FOUND context is preserved."""

    def test_not_found_status_and_empty_fields_preserved(self):
        context_obj = build_correction_lookup_context(_not_found_lookup_result())
        understanding = _FakeUnderstanding(_minimal_plan(), context_obj)
        result = generation_context_from_understanding(understanding).to_dict()
        carried = result["correction_lookup_context"]
        self.assertEqual(carried["status"], STATUS_NOT_FOUND)
        self.assertEqual(carried["records"], [])
        self.assertIsNone(carried["language"])
        self.assertIsNone(carried["source"])
        self.assertIsNone(carried["reason"])


class TestFailedContextIsPreserved(unittest.TestCase):
    """FAILED context is preserved."""

    def test_failed_status_and_reason_preserved(self):
        context_obj = build_correction_lookup_context(_failed_lookup_result())
        understanding = _FakeUnderstanding(_minimal_plan(), context_obj)
        result = generation_context_from_understanding(understanding).to_dict()
        carried = result["correction_lookup_context"]
        self.assertEqual(carried["status"], STATUS_FAILED)
        self.assertEqual(carried["records"], [])
        self.assertEqual(carried["reason"], "storage_unavailable")


class TestExistingFieldsRemainUnchanged(unittest.TestCase):
    """Existing response-generation context fields remain unchanged."""

    def test_other_fields_unaffected_by_carrying_a_context(self):
        context_obj = build_correction_lookup_context(_found_lookup_result())
        plan = _minimal_plan(original_message="Python is a programming language.")
        without = build_generation_context(plan)
        withctx = build_generation_context(plan, correction_lookup_context=context_obj)

        without_dict = without.to_dict()
        with_dict = withctx.to_dict()
        del without_dict["correction_lookup_context"]
        del with_dict["correction_lookup_context"]
        self.assertEqual(without_dict, with_dict)

    def test_status_and_response_action_are_unaffected(self):
        context_obj = build_correction_lookup_context(_found_lookup_result())
        context = build_generation_context(
            _minimal_plan(), correction_lookup_context=context_obj)
        self.assertEqual(context.status, STATUS_UNRESOLVED)
        self.assertIsNone(context.response_action)
        self.assertTrue(context.unresolved)


class TestOriginalCorrectionContextIsNotMutatedDuringTransfer(unittest.TestCase):
    """The original correction context is not mutated during transfer."""

    def test_context_object_unchanged_after_being_carried(self):
        context_obj = build_correction_lookup_context(_found_lookup_result())
        before = context_obj.copy()
        understanding = _FakeUnderstanding(_minimal_plan(), context_obj)
        generation_context_from_understanding(understanding)
        self.assertEqual(context_obj, before)

    def test_records_list_unchanged_after_being_carried(self):
        records = [{"corrected_expression": "dog", "language": "en", "source": "user_correction"}]
        context_obj = build_correction_lookup_context(_found_lookup_result(records=records))
        original_records_copy = [dict(r) for r in context_obj.records]
        build_generation_context(_minimal_plan(), correction_lookup_context=context_obj)
        self.assertEqual(context_obj.records, original_records_copy)

    def test_to_dict_call_does_not_mutate_the_stored_context(self):
        context_obj = build_correction_lookup_context(_found_lookup_result())
        context = build_generation_context(
            _minimal_plan(), correction_lookup_context=context_obj)
        context.to_dict()
        context.to_dict()
        self.assertEqual(context.correction_lookup_context, context_obj)


class TestExistingCallersRemainBackwardsCompatible(unittest.TestCase):
    """Existing callers remain backwards compatible."""

    def test_positional_construction_without_new_kwarg_still_works(self):
        context = ResponseGenerationContext(
            "hi", STATUS_UNRESOLVED, None, None, [], None, {}, None, [], None, "en", None, [],
        )
        self.assertIsNone(context.correction_lookup_context)
        self.assertIn("correction_lookup_context", context.to_dict())

    def test_build_generation_context_without_new_kwarg_still_works(self):
        context = build_generation_context(_minimal_plan(), sentence_structure=None)
        self.assertIsNone(context.correction_lookup_context)

    def test_existing_optional_fields_still_work_together(self):
        context = ResponseGenerationContext(
            "hi", STATUS_UNRESOLVED, None, None, [], None, {}, None, [], None, "en", None, [],
            language_guidance={"status": "NOT_FOUND"},
        )
        self.assertEqual(context.language_guidance, {"status": "NOT_FOUND"})
        self.assertIsNone(context.correction_lookup_context)


if __name__ == "__main__":
    unittest.main()
