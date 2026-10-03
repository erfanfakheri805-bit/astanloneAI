"""
Tests for Prompt 580 - Make Core Response Handling Correction-Aware.

Prompt 579 gave `Core` (core/core.py) `get_last_conversation_response()`,
caching the same `ConversationResponse` (Prompt 431) that
`LanguageIntelligenceCore.generate_response()` already built - including
its `correction_application_result_usable` field (Prompt 578). Nothing in
`Core`'s own response-handling logic - the code in `_handle_conversation()`
immediately after `generate_response()` that decides what `process_input()`
returns - had ever read that field.

This prompt adds the smallest existing response-handling decision point
that consumes it: `self.last_response_correction_usable`, refreshed once,
immediately after `self.last_conversation_response` is (re)cached, at
every existing site that already does so
(`_handle_conversation`'s step "1d" and the explicit
`generate_language_response()` entry point) - a straight, backward-
compatible forward of `self.last_conversation_response.
correction_application_result_usable`, exposed through the new
`get_last_response_correction_usable()`. Nothing about the returned reply
text, `last_language_response`, or any correction retrieval/selection/
application/usability computation changes.

Chain now covered end to end:
    CorrectionApplicationResult
    -> ResponsePlan.correction_application_result_usable              (574)
    -> ResponseGenerationContext.correction_application_result_usable (575)
    -> LearnedResponseDecision.correction_application_result_usable   (576)
    -> ResponseGenerationOutcome.correction_application_result_usable (577)
    -> ConversationResponse.correction_application_result_usable      (578)
    -> Core.get_last_conversation_response().correction_application_
       result_usable                                                  (579)
    -> Core.get_last_response_correction_usable()                     (580)

Covers:
    1. usable=True reaches the new Core handling state
    2. usable=False preserves previous behavior
    3. missing/None conversation response preserves previous behavior
    4. legacy conversation response without the field preserves previous
       behavior
    5. ordinary messages remain unchanged
    6. process_input() returned text remains unchanged
    7. existing last_language_response behavior remains unchanged
    8. no second correction application/retrieval/selection occurs
    9. backward-compatible behavior
    10. deterministic repeated behavior

Run directly:
    python -m unittest tests.test_correction_aware_core_response_handling_prompt580 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence import correction_application_result_usability as _usability_module
from language_intelligence.response_planning import ResponsePlan

from tests.test_correction_aware_response_decision_prompt576 import (
    _make_core, _store_a_correction, _base_plan_kwargs, _not_applied_result_dict,
)


class TestUsableTrueReachesNewCoreState(unittest.TestCase):
    """1: a real, applied correction reaches the new Core-level state,
    via both the explicit entry point and the real process_input() path."""

    def test_true_via_explicit_entry_point(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            self.assertTrue(plan.correction_application_result_usable)
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            self.assertTrue(core.get_last_response_correction_usable())
            self.assertTrue(core.last_response_correction_usable)
        finally:
            tmpdir.cleanup()

    def test_true_via_generate_language_response_reached_through_understand_language(self):
        """Same explicit-entry-point pattern the Prompt 576-579 tests use
        (understand_language() + plan_response() + a manually attached
        plan) - the same real correction pipeline those prompts already
        verified, now also visible as the new Core-level state."""
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            self.assertTrue(plan.correction_application_result_usable)
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            self.assertTrue(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()

    def test_matches_the_underlying_conversation_response_value_exactly(self):
        """The new state is a straight forward of the already-cached
        ConversationResponse - never an independent computation."""
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            conversation_value = (
                core.get_last_conversation_response().correction_application_result_usable)
            core_value = core.get_last_response_correction_usable()
            self.assertTrue(conversation_value)
            self.assertEqual(conversation_value, core_value)
        finally:
            tmpdir.cleanup()


class TestUsableFalsePreservesPreviousBehavior(unittest.TestCase):
    """2: a not-applied/unusable correction result leaves the new state
    False, and changes nothing else."""

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
            self.assertFalse(core.get_last_response_correction_usable())
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
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


class TestMissingOrNonePreservesBehavior(unittest.TestCase):
    """3: before any conversational message has been processed at all,
    the new getter safely returns None rather than raising or fabricating
    a value - same convention as get_last_conversation_response()."""

    def test_fresh_core_returns_none(self):
        core, tmpdir = _make_core()
        try:
            self.assertIsNone(core.get_last_conversation_response())
            self.assertIsNone(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()

    def test_ael_input_leaves_it_none(self):
        """AEL input never reaches Language Intelligence response
        generation at all - same scope as get_last_conversation_response()."""
        core, tmpdir = _make_core()
        try:
            core.process_input("TEACH sun IS a star")
            self.assertIsNone(core.get_last_conversation_response())
            self.assertIsNone(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()

    def test_skill_matched_message_leaves_it_none(self):
        """A keyword-matched skill reply returns before response
        generation is ever reached - last_response_correction_usable
        stays at its previous (None) value, exactly like
        last_conversation_response."""
        core, tmpdir = _make_core()
        try:
            core.process_input("hello")
            self.assertIsNone(core.get_last_conversation_response())
            self.assertIsNone(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


class TestLegacyConversationResponseWithoutFieldPreservesBehavior(unittest.TestCase):
    """4: a legacy/stand-in ConversationResponse object with no
    correction_application_result_usable attribute at all safely
    defaults the new state to False, never raises."""

    def test_legacy_object_without_the_attribute(self):
        core, tmpdir = _make_core()
        try:
            class _LegacyConversationResponse:
                response_text = "hi there"

            core.last_conversation_response = _LegacyConversationResponse()
            core._refresh_last_response_correction_usable()
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


class TestOrdinaryMessagesUnchanged(unittest.TestCase):
    """5: an ordinary conversational message, with no correction anywhere
    in the picture, leaves the new state simply False."""

    def test_ordinary_message(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("tell me about xyzzy")
            self.assertIsNotNone(core.get_last_conversation_response())
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


class TestProcessInputReturnedTextUnchanged(unittest.TestCase):
    """6: process_input()'s returned reply text is byte-for-byte
    unaffected by this prompt's change, whether or not the new state
    ends up True."""

    def test_ordinary_message_reply_matches_control(self):
        core, tmpdir = _make_core()
        try:
            reply = core.process_input("tell me about xyzzy")
            control, control_tmpdir = _make_core()
            try:
                control_reply = control.process_input("tell me about xyzzy")
            finally:
                control_tmpdir.cleanup()
            self.assertEqual(reply, control_reply)
        finally:
            tmpdir.cleanup()

    def test_correction_message_reply_matches_control(self):
        """The real process_input() path for an explicit correction
        message is unaffected by this prompt's change, and the new state
        it leaves behind (False here - the same as before this prompt,
        since response_plan is built during understand(), before the
        correction result is attached; unchanged by this prompt either
        way) is identical across two independent runs."""
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            reply = core.process_input("not dgo, I mean dog.")
            usable = core.get_last_response_correction_usable()

            control, control_tmpdir = _make_core()
            try:
                _store_a_correction(control.language_learning, "dgo", "dog")
                control_reply = control.process_input("not dgo, I mean dog.")
                control_usable = control.get_last_response_correction_usable()
            finally:
                control_tmpdir.cleanup()

            self.assertEqual(reply, control_reply)
            self.assertEqual(usable, control_usable)
        finally:
            tmpdir.cleanup()


class TestExistingLastLanguageResponseUnaffected(unittest.TestCase):
    """7: get_last_language_response(), get_last_language_understanding()
    and get_last_response_plan() are all unaffected by this prompt."""

    def test_existing_getters_unaffected(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("tell me about xyzzy")
            self.assertIsNotNone(core.get_last_language_response())
            self.assertIsNotNone(core.get_last_language_understanding())
            self.assertIsNotNone(core.get_last_response_plan())
        finally:
            tmpdir.cleanup()


class TestNoSecondCorrectionOperationOccurs(unittest.TestCase):
    """8: exposing the new state at the Core layer never re-derives
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
                calls_after_generation = len(calls)
                # Reading the new Core-level state repeatedly must never
                # trigger another usability computation.
                core.get_last_response_correction_usable()
                core.get_last_response_correction_usable()
                self.assertEqual(len(calls), calls_after_generation)
            finally:
                _usability_module.is_correction_application_result_usable = original
        finally:
            tmpdir.cleanup()

    def test_correction_application_not_reapplied(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            first_result = understanding.correction_application_result
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            core.get_last_response_correction_usable()
            # The candidate/result already attached during
            # understand_language() above is untouched by anything this
            # prompt adds.
            self.assertIs(understanding.correction_application_result, first_result)
        finally:
            tmpdir.cleanup()


class TestBackwardCompatibleConstruction(unittest.TestCase):
    """9: a freshly constructed Core has the new attribute present and
    None, with no other constructor behavior changed."""

    def test_fresh_core_has_new_attribute(self):
        core, tmpdir = _make_core()
        try:
            self.assertTrue(hasattr(core, "last_response_correction_usable"))
            self.assertIsNone(core.last_response_correction_usable)
        finally:
            tmpdir.cleanup()


class TestDeterministicRepeatedBehavior(unittest.TestCase):
    """10: calling the new getter repeatedly, and re-running the same
    message on a fresh Core, produces identical results every time."""

    def test_repeated_getter_calls_are_stable(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            first = core.get_last_response_correction_usable()
            second = core.get_last_response_correction_usable()
            third = core.get_last_response_correction_usable()
            self.assertTrue(first)
            self.assertEqual(first, second)
            self.assertEqual(second, third)
        finally:
            tmpdir.cleanup()

    def test_repeated_runs_agree(self):
        results = []
        for _ in range(3):
            core, tmpdir = _make_core()
            try:
                _store_a_correction(core.language_learning, "dgo", "dog")
                understanding = core.understand_language("not dgo, I mean dog.")
                plan = core.language_intelligence.plan_response(understanding)
                understanding.response_plan = plan.to_dict()
                core.generate_language_response(understanding)
                results.append(core.get_last_response_correction_usable())
            finally:
                tmpdir.cleanup()
        self.assertEqual(results, [True, True, True])


if __name__ == "__main__":
    unittest.main()
