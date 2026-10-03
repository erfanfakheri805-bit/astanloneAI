"""
Tests for Prompt 571 - Add Correction Application Result Field.

Covers exactly the small, additive change this prompt makes:

    1. `LanguageUnderstandingResult.correction_application_result`
       defaults to `None`, following the exact `correction_application_
       candidate` (Prompt 564) pattern.
    2. An explicitly supplied value is preserved unchanged.
    3. `to_dict()` exposes it, using the SAME "call `.to_dict()` when
       present, else pass the value through" convention already used
       for `correction_application_candidate`.
    4. Existing (pre-571) construction without this keyword argument
       remains valid - backward compatible.
    5. `ResponseGenerationRequest._generation_context_object()` now
       forwards `understanding.correction_application_result` into
       `build_generation_context()`, closing the one missing
       connection this prompt targets (mirrors the Prompt 568 audit
       for `correction_application_candidate`).

Nothing here applies a correction, changes response text, changes
correction acknowledgement behavior, adds storage/retrieval, or
touches Core.

Run directly:
    python -m unittest tests.test_correction_application_result_field_prompt571 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.language_understanding_result import (
    LanguageUnderstandingResult,
)
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult, STATUS_APPLIED,
)
from language_intelligence.response_generation import ResponseGenerationRequest
from language_intelligence.response_planning import STATUS_UNRESOLVED


def _minimal_result(**overrides):
    """The smallest valid positional call to `LanguageUnderstandingResult`
    - exactly the fields required before any optional keyword args."""
    kwargs = dict(
        original_input="hello",
        detected_language="en",
        normalized_input="hello",
        intent="unknown",
        entities=[],
        referenced_items=[],
        active_topic=None,
        conversation_context=None,
        confidence=0.5,
        ambiguity=False,
        needs_clarification=False,
    )
    kwargs.update(overrides)
    return LanguageUnderstandingResult(**kwargs)


def _applied_result():
    return CorrectionApplicationResult(
        STATUS_APPLIED, original_text="a dgo here", corrected_text="a dog here",
        matched_text="dgo", replacement_text="dog", match_count=1,
    )


def _minimal_plan(**overrides):
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


class TestDefaultValueIsNone(unittest.TestCase):

    def test_default_is_none(self):
        result = _minimal_result()
        self.assertIsNone(result.correction_application_result)

    def test_default_appears_as_none_in_to_dict(self):
        result = _minimal_result()
        self.assertIn("correction_application_result", result.to_dict())
        self.assertIsNone(result.to_dict()["correction_application_result"])


class TestExplicitValueIsPreserved(unittest.TestCase):

    def test_explicit_object_is_preserved(self):
        applied = _applied_result()
        result = _minimal_result(correction_application_result=applied)
        self.assertIs(result.correction_application_result, applied)

    def test_explicit_plain_dict_is_preserved(self):
        payload = {"status": "NOT_APPLIED"}
        result = _minimal_result(correction_application_result=payload)
        self.assertEqual(result.correction_application_result, payload)


class TestToDictExposesIt(unittest.TestCase):

    def test_to_dict_calls_to_dict_on_an_object_value(self):
        applied = _applied_result()
        result = _minimal_result(correction_application_result=applied)
        self.assertEqual(
            result.to_dict()["correction_application_result"], applied.to_dict())

    def test_to_dict_passes_through_a_plain_dict_value_unchanged(self):
        payload = {"status": "FAILED", "reason": "request_not_valid"}
        result = _minimal_result(correction_application_result=payload)
        self.assertEqual(
            result.to_dict()["correction_application_result"], payload)

    def test_other_fields_unaffected(self):
        applied = _applied_result()
        without = _minimal_result().to_dict()
        with_result = _minimal_result(
            correction_application_result=applied).to_dict()
        del without["correction_application_result"]
        del with_result["correction_application_result"]
        self.assertEqual(without, with_result)


class TestOldConstructionRemainsBackwardCompatible(unittest.TestCase):

    def test_positional_style_call_without_new_kwarg_still_works(self):
        result = LanguageUnderstandingResult(
            "hi", "en", "hi", "unknown", [], [], None, None, 0.5, False, False,
        )
        self.assertIsNone(result.correction_application_result)
        self.assertIn("correction_application_result", result.to_dict())

    def test_prior_keyword_correction_application_candidate_still_works(self):
        # Prompt 564's own kwarg still works, unaffected by this one.
        result = _minimal_result(
            correction_application_candidate={"is_valid": False})
        self.assertEqual(
            result.correction_application_candidate, {"is_valid": False})
        self.assertIsNone(result.correction_application_result)


class _FakeUnderstandingNoAttribute:
    """Stands in for a `LanguageUnderstandingResult` produced before this
    field existed - reproduces the exact gap `_generation_context_object()`
    is fixed to handle via `getattr(..., None)`."""

    def __init__(self, response_plan):
        self.response_plan = response_plan
        self.learned_sentence_structure = None
        self.correction_lookup_context = None
        self.correction_application_candidate = None
        self.learned_knowledge_context = None
        # deliberately no correction_application_result attribute at all


class TestDownstreamForwardingWorks(unittest.TestCase):
    """`ResponseGenerationRequest._generation_context_object()` now
    forwards `understanding.correction_application_result` - the one
    missing connection this prompt adds."""

    def test_real_result_reaches_the_generation_context(self):
        applied = _applied_result()
        understanding = _minimal_result(
            response_plan=_minimal_plan(),
            correction_application_result=applied)
        request = ResponseGenerationRequest(understanding)
        context = request.generation_context
        self.assertEqual(
            context["correction_application_result"], applied.to_dict())

    def test_none_remains_none_without_a_result(self):
        understanding = _minimal_result(response_plan=_minimal_plan())
        request = ResponseGenerationRequest(understanding)
        context = request.generation_context
        self.assertIsNone(context["correction_application_result"])

    def test_missing_attribute_on_an_older_understanding_is_handled_safely(self):
        understanding = _FakeUnderstandingNoAttribute(_minimal_plan())
        request = ResponseGenerationRequest(understanding)
        context = request.generation_context
        self.assertIsNone(context["correction_application_result"])

    def test_forwarding_does_not_change_status_or_response_action(self):
        applied = _applied_result()
        understanding = _minimal_result(
            correction_application_result=applied)
        understanding.response_plan = _minimal_plan()
        request = ResponseGenerationRequest(understanding)
        context = request.generation_context
        self.assertEqual(context["status"], STATUS_UNRESOLVED)
        self.assertIsNone(context["response_action"])


if __name__ == "__main__":
    unittest.main()
