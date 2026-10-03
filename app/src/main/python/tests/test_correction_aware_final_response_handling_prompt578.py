"""
Tests for Prompt 578 - Propagate Correction-Aware Outcome Into Final
Response Handling.

Prompt 577 gave `ResponseGenerationOutcome` (response_generation_outcome.py,
Prompt 428) a `correction_application_result_usable` field, forwarded
straight from the `LearnedResponseDecision` (Prompt 576) that
`LanguageIntelligenceCore.generate_response()` already makes. Nothing
downstream of the outcome could see it yet.

This prompt makes the next existing layer that already receives the
outcome - `ConversationResponse` / `build_conversation_response()`
(conversation_response.py, Prompt 431), the final, immutable response
object every higher-level caller already consumes - carry the SAME field
through unchanged, never recomputed.

Chain now covered end to end:
    CorrectionApplicationResult
    -> ResponsePlan.correction_application_result_usable            (574)
    -> ResponseGenerationContext.correction_application_result_usable (575)
    -> LearnedResponseDecision.correction_application_result_usable   (576)
    -> ResponseGenerationOutcome.correction_application_result_usable (577)
    -> ConversationResponse.correction_application_result_usable      (578)

Covers:
    1. True reaches the next handling layer (ConversationResponse)
    2. False preserves previous behavior
    3. missing/legacy outcome preserves previous behavior
    4. ordinary, non-correction messages remain unchanged
    5. existing ConversationResponse fields remain unchanged
    6. no second correction retrieval/selection/application/usability
       computation occurs
    7. backward-compatible construction
    8. deterministic, repeated behavior

Run directly:
    python -m unittest tests.test_correction_aware_final_response_handling_prompt578 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence import correction_application_result_usability as _usability_module
from language_intelligence.conversation_response import (
    ConversationResponse, build_conversation_response,
)
from language_intelligence.response_generation import ResponseGenerationResult, STATUS_GENERATED
from language_intelligence.response_generation_outcome import (
    ResponseGenerationOutcome, STATUS_SUCCESS,
)

from tests.test_correction_aware_response_decision_prompt576 import (
    _make_core, _store_a_correction, _base_plan_kwargs, _not_applied_result_dict,
)
from language_intelligence.response_planning import ResponsePlan


def _generated_result(text="hi there"):
    return ResponseGenerationResult(
        status=STATUS_GENERATED, response_text=text, backend_kind="local_model")


def _outcome(usable=False):
    return ResponseGenerationOutcome(
        STATUS_SUCCESS, generated_text="hi there", backend_kind="local_model",
        correction_application_result_usable=usable)


class TestUsableTrueReachesConversationResponse(unittest.TestCase):
    """1: a real applied correction reaches `ConversationResponse` via the
    real `generate_response()` / `get_last_conversation_response()` path,
    and via the direct `build_conversation_response()` builder."""

    def test_true_reaches_conversation_response_via_real_pipeline(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            self.assertTrue(plan.correction_application_result_usable)
            understanding.response_plan = plan.to_dict()
            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)
            outcome = lic.get_last_response_generation_result()
            self.assertTrue(outcome.correction_application_result_usable)
            conversation = lic.get_last_conversation_response()
            self.assertIsInstance(conversation, ConversationResponse)
            self.assertTrue(conversation.correction_application_result_usable)
            self.assertTrue(conversation.to_dict()["correction_application_result_usable"])
        finally:
            tmpdir.cleanup()

    def test_unit_level_builder_passthrough(self):
        result = _generated_result()
        outcome = _outcome(usable=True)
        conversation = build_conversation_response(result, outcome=outcome)
        self.assertTrue(conversation.correction_application_result_usable)


class TestUsableFalsePreservesPreviousBehavior(unittest.TestCase):
    """2: `False` leaves `ConversationResponse`'s new field False, and the
    rest of the object exactly as before this prompt."""

    def test_not_applied_correction_result(self):
        core, tmpdir = _make_core()
        try:
            plan = ResponsePlan(
                correction_application_result=_not_applied_result_dict(),
                **_base_plan_kwargs())
            self.assertFalse(plan.correction_application_result_usable)
            understanding = core.understand_language("hello there")
            understanding.response_plan = plan.to_dict()
            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)
            conversation = lic.get_last_conversation_response()
            self.assertFalse(conversation.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_builder_default_is_false(self):
        result = _generated_result()
        outcome = _outcome(usable=False)
        conversation = build_conversation_response(result, outcome=outcome)
        self.assertFalse(conversation.correction_application_result_usable)


class TestMissingOrLegacyOutcomePreservesBehavior(unittest.TestCase):
    """3: no outcome given (built internally), and a legacy outcome object
    built before Prompt 577 (no such attribute), both safely default the
    new field to False - and leave every other field exactly as before."""

    def test_no_outcome_given_builds_default_false(self):
        result = _generated_result()
        conversation = build_conversation_response(result)
        self.assertFalse(conversation.correction_application_result_usable)
        self.assertEqual(conversation.response_text, "hi there")

    def test_legacy_outcome_object_without_the_attribute(self):
        class _LegacyOutcome:
            status = STATUS_SUCCESS
            generated_text = "hi there"
            backend_kind = "local_model"
            language = None
            locale = None
            failure_reason = None
            fallback_used = False
            metadata = None

        result = _generated_result()
        conversation = build_conversation_response(result, outcome=_LegacyOutcome())
        self.assertFalse(conversation.correction_application_result_usable)
        self.assertEqual(conversation.response_text, "hi there")


class TestOrdinaryMessagesUnchanged(unittest.TestCase):
    """4: an ordinary message with no correction anywhere in the picture
    behaves exactly as before this prompt, with the new field simply
    False."""

    def test_ordinary_message_no_correction(self):
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("hello there")
            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)
            conversation = lic.get_last_conversation_response()
            self.assertFalse(conversation.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestExistingFieldsUnchanged(unittest.TestCase):
    """5: every other `ConversationResponse` field is unaffected by this
    prompt's change, whether the new flag is True or False."""

    def test_fields_identical_with_and_without_correction(self):
        result = _generated_result()
        with_correction = build_conversation_response(result, outcome=_outcome(usable=True))
        without_correction = build_conversation_response(result, outcome=_outcome(usable=False))
        for field in ("response_text", "status", "language", "locale", "backend_kind",
                      "fallback_used", "failure_reason", "metadata", "valid",
                      "validation_issues", "generation_status", "reason",
                      "generation_backend_kind", "fallback_backend_kind",
                      "selected_backend_kind", "inference_status", "error_code",
                      "classification"):
            self.assertEqual(
                getattr(with_correction, field), getattr(without_correction, field),
                msg=f"field {field!r} differs")
        self.assertNotEqual(
            with_correction.correction_application_result_usable,
            without_correction.correction_application_result_usable)


class TestNoSecondCorrectionOperationOccurs(unittest.TestCase):
    """6: propagating the field into `ConversationResponse` never
    re-derives usability, re-retrieves, re-selects or re-applies a
    correction."""

    def test_usability_function_not_called_again(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            lic = core.language_intelligence

            original = _usability_module.is_correction_application_result_usable
            calls = []

            def counting(*args, **kwargs):
                calls.append((args, kwargs))
                return original(*args, **kwargs)

            _usability_module.is_correction_application_result_usable = counting
            try:
                lic.generate_response(understanding, context=core.context)
            finally:
                _usability_module.is_correction_application_result_usable = original
            self.assertEqual(len(calls), 0)
            conversation = lic.get_last_conversation_response()
            self.assertTrue(conversation.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_conversation_value_equals_outcome_value_not_independently_derived(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)
            outcome_value = lic.get_last_response_generation_result().correction_application_result_usable
            conversation_value = lic.get_last_conversation_response().correction_application_result_usable
            self.assertEqual(outcome_value, conversation_value)
        finally:
            tmpdir.cleanup()


class TestBackwardCompatibleConstruction(unittest.TestCase):
    """7: existing call sites that construct `ConversationResponse` or
    call `build_conversation_response()` without the new keyword argument
    are unaffected."""

    def test_conversation_response_default_is_false(self):
        conversation = ConversationResponse(status=STATUS_SUCCESS, response_text="hi")
        self.assertFalse(conversation.correction_application_result_usable)

    def test_conversation_response_to_dict_has_key(self):
        conversation = ConversationResponse(status=STATUS_SUCCESS, response_text="hi")
        self.assertIn("correction_application_result_usable", conversation.to_dict())

    def test_conversation_response_is_still_immutable(self):
        conversation = ConversationResponse(status=STATUS_SUCCESS, response_text="hi")
        with self.assertRaises(AttributeError):
            conversation.correction_application_result_usable = True

    def test_builder_without_new_kwarg_still_works(self):
        result = _generated_result()
        conversation = build_conversation_response(result)
        self.assertFalse(conversation.correction_application_result_usable)


class TestDeterministicRepeatedBehavior(unittest.TestCase):
    """8: the same input always produces the same value, repeatedly."""

    def test_repeated_calls_are_identical(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            lic = core.language_intelligence
            values = []
            for _ in range(3):
                understanding = core.understand_language("not dgo, I mean dog.")
                plan = lic.plan_response(understanding)
                understanding.response_plan = plan.to_dict()
                lic.generate_response(understanding, context=core.context)
                values.append(
                    lic.get_last_conversation_response().correction_application_result_usable)
            self.assertTrue(all(v == values[0] for v in values))
            self.assertTrue(values[0])
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
