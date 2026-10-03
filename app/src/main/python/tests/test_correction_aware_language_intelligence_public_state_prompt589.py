"""
Tests for Prompt 589 - Correction-Aware State at the Public Language
Intelligence Boundary.

Inspection performed by this prompt: examined every public method/getter
on `LanguageIntelligenceCore` (language_intelligence_core.py) related to
the final response - `get_last_conversation_response()` (Prompt 431) and
`get_last_response_generation_result()` (Prompt 429) - to determine
whether a caller outside the internal response-generation path
(generate_response()/_route_response()/_learned_response()/_build_outcome())
can reliably reach the correction-aware final-response state without
touching a private field.

Finding: both existing getters already provide a complete, stable public
path.
    `get_last_conversation_response()` returns the same
    `ConversationResponse` `generate_response()` just cached, and that
    object already carries `correction_application_result_usable`
    (Prompt 578, forwarded from the Prompt 428 outcome).
    `get_last_response_generation_result()` returns the same
    `ResponseGenerationOutcome` `generate_response()` just built (Prompt
    429's naming keeps returning the outcome, not the raw
    `ResponseGenerationResult` - see its own docstring), and that outcome
    already carries `correction_application_result_usable` directly
    (Prompt 577).
No production code was changed (Prompt 589 requirements 3/6/11): this
file is the smallest regression coverage proving the public path is
already complete, stable, and reachable without private-field access.

Covers:
    1. public access to the final correction-aware state via both
       existing getters
    2. True/False behavior
    3. an ordinary response after a correction-aware one clears the state
       back to False on both getters (no stale True leaks across calls)
    4. reset behavior (Core.reset_context() followed by a fresh ordinary
       message still reports False through both getters; a new
       generate_response() call always rebuilds the state from scratch)
    5. legacy/missing state: both getters are None before the first
       generate_response() call on a fresh LanguageIntelligenceCore
    6. the entire test path uses only public getters - no `_`-prefixed
       attribute is ever read

Reuses the existing Prompt 576 test helpers (`_make_core`,
`_store_a_correction`, `_base_plan_kwargs`, `_not_applied_result_dict`)
rather than duplicating that infrastructure.

Run directly:
    python -m unittest tests.test_correction_aware_language_intelligence_public_state_prompt589 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.conversation_response import ConversationResponse
from language_intelligence.response_generation_outcome import ResponseGenerationOutcome
from language_intelligence.response_planning import ResponsePlan

from tests.test_correction_aware_response_decision_prompt576 import (
    _make_core, _store_a_correction, _base_plan_kwargs, _not_applied_result_dict,
)


def _plan_with_correction(understanding, core):
    plan = core.language_intelligence.plan_response(understanding)
    understanding.response_plan = plan.to_dict()
    return plan


class TestPublicAccessToFinalCorrectionAwareState(unittest.TestCase):
    """1: both public getters reach the correction-aware value with no
    private-field access."""

    def test_conversation_response_getter_exposes_it(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = _plan_with_correction(understanding, core)
            self.assertTrue(plan.correction_application_result_usable)

            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)

            conversation = lic.get_last_conversation_response()
            self.assertIsInstance(conversation, ConversationResponse)
            self.assertTrue(conversation.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_response_generation_result_getter_exposes_it(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            _plan_with_correction(understanding, core)

            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)

            outcome = lic.get_last_response_generation_result()
            self.assertIsInstance(outcome, ResponseGenerationOutcome)
            self.assertTrue(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestTrueFalseBehavior(unittest.TestCase):
    """2: both getters report False for an ordinary message / a
    not-applied correction, and the two getters always agree."""

    def test_false_for_ordinary_message(self):
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("tell me about xyzzy")
            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)

            conversation = lic.get_last_conversation_response()
            outcome = lic.get_last_response_generation_result()
            self.assertFalse(conversation.correction_application_result_usable)
            self.assertFalse(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_false_for_not_applied_correction(self):
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
            outcome = lic.get_last_response_generation_result()
            self.assertFalse(conversation.correction_application_result_usable)
            self.assertFalse(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_true_case_both_getters_agree(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            _plan_with_correction(understanding, core)

            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)

            conversation_value = (
                lic.get_last_conversation_response().correction_application_result_usable)
            outcome_value = (
                lic.get_last_response_generation_result().correction_application_result_usable)
            self.assertTrue(conversation_value)
            self.assertEqual(conversation_value, outcome_value)
        finally:
            tmpdir.cleanup()


class TestOrdinaryResponseAfterCorrectionAwareResponse(unittest.TestCase):
    """3: a correction-aware True does not leak into the next, ordinary
    call - each generate_response() call reports only its own state."""

    def test_state_clears_on_next_ordinary_call(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            correction_understanding = core.understand_language("not dgo, I mean dog.")
            _plan_with_correction(correction_understanding, core)

            lic = core.language_intelligence
            lic.generate_response(correction_understanding, context=core.context)
            self.assertTrue(
                lic.get_last_conversation_response().correction_application_result_usable)
            self.assertTrue(
                lic.get_last_response_generation_result().correction_application_result_usable)

            ordinary_understanding = core.understand_language("tell me about xyzzy")
            lic.generate_response(ordinary_understanding, context=core.context)

            self.assertFalse(
                lic.get_last_conversation_response().correction_application_result_usable)
            self.assertFalse(
                lic.get_last_response_generation_result().correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestResetBehavior(unittest.TestCase):
    """4: Core.reset_context() followed by a fresh ordinary message still
    reports False through both LanguageIntelligenceCore getters, and each
    fresh generate_response() call rebuilds the state rather than
    reusing a stale object."""

    def test_reset_context_then_ordinary_message_is_false(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            correction_understanding = core.understand_language("not dgo, I mean dog.")
            _plan_with_correction(correction_understanding, core)

            lic = core.language_intelligence
            lic.generate_response(correction_understanding, context=core.context)
            self.assertTrue(
                lic.get_last_conversation_response().correction_application_result_usable)

            core.reset_context()

            ordinary_understanding = core.understand_language("tell me about xyzzy")
            lic.generate_response(ordinary_understanding, context=core.context)
            self.assertFalse(
                lic.get_last_conversation_response().correction_application_result_usable)
            self.assertFalse(
                lic.get_last_response_generation_result().correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_repeated_calls_rebuild_rather_than_reuse(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            _plan_with_correction(understanding, core)

            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)
            first = lic.get_last_conversation_response()

            lic.generate_response(understanding, context=core.context)
            second = lic.get_last_conversation_response()

            self.assertTrue(first.correction_application_result_usable)
            self.assertTrue(second.correction_application_result_usable)
            self.assertIsNot(first, second)
        finally:
            tmpdir.cleanup()


class TestLegacyOrMissingStateBehavior(unittest.TestCase):
    """5: before the first generate_response() call, both getters are
    None on a fresh LanguageIntelligenceCore - never an AttributeError,
    never a default True."""

    def test_both_getters_none_before_first_call(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
        finally:
            tmpdir.cleanup()


class TestNoPrivateFieldAccessRequired(unittest.TestCase):
    """6: the correction-aware value is reachable through the public
    getters alone; this test never reads a `_`-prefixed attribute, and
    a caller instructed to avoid private state could produce the exact
    same assertions."""

    def test_public_only_path_matches_private_state(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            _plan_with_correction(understanding, core)

            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)

            public_conversation = lic.get_last_conversation_response()
            public_outcome = lic.get_last_response_generation_result()

            # Cross-check only, still through public attributes of the
            # returned public objects - not through any `_`-prefixed
            # name on `lic` itself.
            self.assertIs(public_conversation, lic.last_conversation_response)
            self.assertIs(public_outcome, lic.last_response_generation_result)
            self.assertTrue(public_conversation.correction_application_result_usable)
            self.assertTrue(public_outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
