"""
Tests for Prompt 579 - Expose Correction-Aware State in Final
Conversation Handling.

Prompt 578 gave `ConversationResponse` (language_intelligence/
conversation_response.py, Prompt 431) a `correction_application_result_
usable` field, forwarded straight from the Prompt 428 `ResponseGeneration
Outcome` that `LanguageIntelligenceCore.generate_response()` already
builds and caches as `get_last_conversation_response()`. Nothing beyond
that point - the actual `Core` (core/core.py) that returns the final
reply to its caller/UI through `process_input()` - had ever read
`ConversationResponse` at all: `Core` only ever consumed the raw
`ResponseGenerationResult` (`self.last_language_response`).

This prompt makes `Core` - the smallest existing handling layer
immediately before `process_input()` returns the final reply to the
caller/UI - aware of the SAME already-built `ConversationResponse`,
by caching it (exactly like the existing `self.last_language_response`
convention) and exposing it through a new `get_last_conversation_
response()` method, mirroring the existing `get_last_language_
response()`. The value is read straight off `LanguageIntelligenceCore.
get_last_conversation_response()` - never rebuilt, never recomputed.

Chain now covered end to end:
    CorrectionApplicationResult
    -> ResponsePlan.correction_application_result_usable              (574)
    -> ResponseGenerationContext.correction_application_result_usable (575)
    -> LearnedResponseDecision.correction_application_result_usable   (576)
    -> ResponseGenerationOutcome.correction_application_result_usable (577)
    -> ConversationResponse.correction_application_result_usable      (578)
    -> Core.get_last_conversation_response().correction_application_
       result_usable                                                  (579)

Covers:
    1. True reaches the final handling layer (Core)
    2. False preserves previous behavior
    3. missing/legacy values preserve previous behavior
    4. ordinary messages remain unchanged
    5. existing fields remain unchanged
    6. no second correction operation occurs
    7. backward-compatible construction
    8. deterministic behavior

Run directly:
    python -m unittest tests.test_correction_aware_conversation_output_prompt579 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence import correction_application_result_usability as _usability_module
from language_intelligence.conversation_response import ConversationResponse
from language_intelligence.response_planning import ResponsePlan

from tests.test_correction_aware_response_decision_prompt576 import (
    _make_core, _store_a_correction, _base_plan_kwargs, _not_applied_result_dict,
)


class TestTrueReachesTheFinalHandlingLayer(unittest.TestCase):
    """1: a real, applied correction reaches `Core.get_last_conversation_
    response()` - the layer immediately before `process_input()` returns
    the final reply to its caller/UI."""

    def test_true_reaches_core_via_explicit_entry_point(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            self.assertTrue(plan.correction_application_result_usable)
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            conversation = core.get_last_conversation_response()
            self.assertIsInstance(conversation, ConversationResponse)
            self.assertTrue(conversation.correction_application_result_usable)
            self.assertTrue(
                conversation.to_dict()["correction_application_result_usable"])
        finally:
            tmpdir.cleanup()

    def test_true_matches_the_underlying_lic_value_exactly(self):
        """The value Core exposes is identical to (not independently
        derived from) the one LanguageIntelligenceCore already built."""
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            lic_value = (
                core.language_intelligence.get_last_conversation_response()
                .correction_application_result_usable)
            core_value = core.get_last_conversation_response().correction_application_result_usable
            self.assertTrue(lic_value)
            self.assertEqual(lic_value, core_value)
        finally:
            tmpdir.cleanup()


class TestFalsePreservesPreviousBehavior(unittest.TestCase):
    """2: a not-applied/unusable correction result leaves the new field
    False at the Core layer, and changes nothing else about Core's
    existing behavior."""

    def test_not_applied_correction_result(self):
        core, tmpdir = _make_core()
        try:
            plan = ResponsePlan(
                correction_application_result=_not_applied_result_dict(),
                **_base_plan_kwargs())
            self.assertFalse(plan.correction_application_result_usable)
            understanding = core.understand_language("hello there")
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            conversation = core.get_last_conversation_response()
            self.assertFalse(conversation.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_no_correction_result_at_all(self):
        core, tmpdir = _make_core()
        try:
            plan = ResponsePlan(correction_application_result=None, **_base_plan_kwargs())
            self.assertFalse(plan.correction_application_result_usable)
            understanding = core.understand_language("hello there")
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            conversation = core.get_last_conversation_response()
            self.assertFalse(conversation.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestMissingOrLegacyPreservesBehavior(unittest.TestCase):
    """3: before any message has been processed (no ConversationResponse
    built yet at all - the legacy/pre-Prompt-579 state of a freshly
    constructed Core), the new getter safely returns None rather than
    raising or fabricating a value."""

    def test_fresh_core_returns_none(self):
        core, tmpdir = _make_core()
        try:
            self.assertIsNone(core.get_last_conversation_response())
        finally:
            tmpdir.cleanup()

    def test_ael_input_leaves_it_none(self):
        """AEL input never reaches Language Intelligence response
        generation at all - same scope as get_last_language_response()."""
        core, tmpdir = _make_core()
        try:
            core.process_input("TEACH sun IS a star")
            self.assertIsNone(core.get_last_conversation_response())
        finally:
            tmpdir.cleanup()


class TestOrdinaryMessagesUnchanged(unittest.TestCase):
    """4: an ordinary conversational message, processed through the real
    `process_input()` path with no correction anywhere in the picture,
    behaves exactly as before this prompt (same reply text), with the
    new field simply False once exposed."""

    def test_ordinary_message_reply_and_flag(self):
        core, tmpdir = _make_core()
        try:
            reply = core.process_input("tell me about xyzzy")
            self.assertIsInstance(reply, str)
            conversation = core.get_last_conversation_response()
            self.assertIsNotNone(conversation)
            self.assertFalse(conversation.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_skill_matched_message_leaves_conversation_response_none(self):
        """A keyword-matched skill reply returns before response
        generation is ever reached - last_conversation_response stays at
        its previous (None) value, exactly like last_language_response."""
        core, tmpdir = _make_core()
        try:
            core.process_input("hello")
            self.assertIsNone(core.get_last_language_response())
            self.assertIsNone(core.get_last_conversation_response())
        finally:
            tmpdir.cleanup()


class TestExistingFieldsUnchanged(unittest.TestCase):
    """5: adding `get_last_conversation_response()` to Core changes
    nothing about `get_last_language_response()`, `get_last_language_
    understanding()`, `get_last_response_plan()`, or the actual reply
    text `process_input()` returns."""

    def test_last_language_response_and_reply_unaffected(self):
        core, tmpdir = _make_core()
        try:
            reply = core.process_input("tell me about xyzzy")
            control, control_tmpdir = _make_core()
            try:
                control_reply = control.process_input("tell me about xyzzy")
            finally:
                control_tmpdir.cleanup()
            self.assertEqual(reply, control_reply)
            self.assertIsNotNone(core.get_last_language_response())
            self.assertIsNotNone(core.get_last_language_understanding())
            self.assertIsNotNone(core.get_last_response_plan())
        finally:
            tmpdir.cleanup()

    def test_conversation_response_other_fields_intact(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            conversation = core.get_last_conversation_response()
            lic_conversation = core.language_intelligence.get_last_conversation_response()
            for field in ("response_text", "status", "language", "locale", "backend_kind",
                          "fallback_used", "failure_reason", "metadata", "valid",
                          "validation_issues", "generation_status", "reason",
                          "generation_backend_kind", "fallback_backend_kind",
                          "selected_backend_kind", "inference_status", "error_code",
                          "classification"):
                self.assertEqual(
                    getattr(conversation, field), getattr(lic_conversation, field),
                    msg=f"field {field!r} differs")
        finally:
            tmpdir.cleanup()


class TestNoSecondCorrectionOperationOccurs(unittest.TestCase):
    """6: exposing the field at the Core layer never re-derives
    usability, re-retrieves, re-selects or re-applies a correction."""

    def test_usability_function_not_called_again(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()

            original = _usability_module.is_correction_application_result_usable
            calls = []

            def counting(*args, **kwargs):
                calls.append((args, kwargs))
                return original(*args, **kwargs)

            _usability_module.is_correction_application_result_usable = counting
            try:
                core.generate_language_response(understanding)
            finally:
                _usability_module.is_correction_application_result_usable = original
            self.assertEqual(len(calls), 0)
            conversation = core.get_last_conversation_response()
            self.assertTrue(conversation.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_core_reads_the_same_object_lic_already_built(self):
        """Core's getter returns the identical object LanguageIntelligence
        Core already cached - not a freshly-built copy."""
        core, tmpdir = _make_core()
        try:
            reply = core.process_input("tell me about xyzzy")
            self.assertIsInstance(reply, str)
            self.assertIs(
                core.get_last_conversation_response(),
                core.language_intelligence.get_last_conversation_response())
        finally:
            tmpdir.cleanup()


class TestBackwardCompatibleConstruction(unittest.TestCase):
    """7: existing `Core()` construction and existing callers of the
    other `get_last_*` methods are unaffected by this prompt's addition."""

    def test_core_constructs_normally(self):
        core, tmpdir = _make_core()
        try:
            self.assertTrue(hasattr(core, "last_conversation_response"))
            self.assertIsNone(core.last_conversation_response)
        finally:
            tmpdir.cleanup()

    def test_get_last_conversation_response_method_exists(self):
        core, tmpdir = _make_core()
        try:
            self.assertTrue(callable(getattr(core, "get_last_conversation_response", None)))
        finally:
            tmpdir.cleanup()

    def test_generate_language_response_still_returns_result_object(self):
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("hello there")
            response = core.generate_language_response(understanding)
            self.assertIsNotNone(response)
            self.assertTrue(hasattr(response, "status"))
        finally:
            tmpdir.cleanup()


class TestDeterministicRepeatedBehavior(unittest.TestCase):
    """8: the same input always produces the same value, repeatedly."""

    def test_repeated_calls_are_identical(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            values = []
            for _ in range(3):
                understanding = core.understand_language("not dgo, I mean dog.")
                plan = core.language_intelligence.plan_response(understanding)
                understanding.response_plan = plan.to_dict()
                core.generate_language_response(understanding)
                values.append(
                    core.get_last_conversation_response().correction_application_result_usable)
            self.assertTrue(all(v == values[0] for v in values))
            self.assertTrue(values[0])
        finally:
            tmpdir.cleanup()

    def test_repeated_ordinary_messages_stay_false(self):
        core, tmpdir = _make_core()
        try:
            values = []
            for _ in range(3):
                core.process_input("tell me about xyzzy")
                values.append(
                    core.get_last_conversation_response().correction_application_result_usable)
            self.assertTrue(all(v is False for v in values))
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
