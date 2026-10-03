"""
Tests for Prompt 591 - Lifecycle Contract of the Public Response-State
Getters (no-response / first-response / subsequent-response / reset).

Inspection performed by this prompt: re-examined the Prompt 590 tests and
`LanguageIntelligenceCore.generate_response()` (language_intelligence_core.py).
Findings:

  * Pre-generation (fresh core, no `generate_response()` call yet) and the
    True -> ordinary -> True state transition across successive calls were
    already covered by Prompt 590
    (`TestBeforeFirstResponseAndAfterResetLifecycle`,
    `TestStateTransitionAcrossThreeGeneratedResponses`). No gap there.

  * A genuine, previously-untested gap: `generate_response()` resets
    `self.last_response_generation_result` / `self.last_conversation_
    response` (and `self.last_response_generation_validation`) to `None`
    at the very TOP of the method, before routing/outcome-building even
    starts (see the three `self.last_* = None` lines immediately inside
    `generate_response()`). This means a malfunctioning backend that
    returns something that is not a `ResponseGenerationResult` can never
    leave a PREVIOUS call's cached True/response object visible as if it
    were current - the cache is unconditionally cleared before the new
    attempt is even made. This was implied but never directly exercised;
    this file adds that regression.

  * `Core.reset_context()` (Prompt 581) is documented to leave `Language
    IntelligenceCore`'s own `last_conversation_response`/`last_response_
    generation_result` untouched - there is no reset/clear API on
    `LanguageIntelligenceCore` itself, so the only "reset" that ever
    clears its cached response state is a fresh `generate_response()`
    call. Prompt 590 tested the state AFTER a post-reset ordinary call,
    but never the gap in between: immediately after `reset_context()`
    and BEFORE the next `generate_response()` call, the previous
    (pre-reset) `ConversationResponse`/outcome are still exactly what the
    getters return. This file locks in that existing, intentional
    behavior explicitly, and confirms it stays perfectly stable (repeated
    reads, no mutation) across that window.

No production code was changed (Prompt 591 requirements 7/8/9): every
behavior above is exactly what the current implementation already does;
this file is the smallest regression coverage proving it.

Covers:
    1. no generated response yet: both getters None, stably, on a fresh
       LanguageIntelligenceCore (both via Core and standalone)
    2. first generated response correctly populates both getters (True
       and False cases)
    3. a malfunctioning backend response (not a ResponseGenerationResult)
       never leaves a previous call's stale True/object visible - the
       cache is unconditionally cleared to None first
    4. immediately after Core.reset_context() and before any new
       generate_response() call, LanguageIntelligenceCore's getters still
       return the pre-reset object, unchanged and stable across repeated
       reads (documents the existing, intentional Core/LIC reset
       boundary)
    5. generating a new response after reset correctly repopulates the
       public state end to end, in both directions (True after a prior
       False, and False after a prior True)
    6. response text is preserved and correct at every transition above

Reuses the existing Prompt 576 test helpers (`_make_core`,
`_store_a_correction`) and the Prompt 589/590 `_plan_with_correction`
helper pattern, plus the Prompt 421-424-style stub-backend construction
used by `tests.test_response_planning_integration` for the malfunctioning-
backend case, rather than duplicating that infrastructure.

Run directly:
    python -m unittest tests.test_correction_aware_public_response_lifecycle_prompt591 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.backend import LanguageIntelligenceBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.conversation_response import ConversationResponse
from language_intelligence.response_generation_outcome import ResponseGenerationOutcome

from tests.test_correction_aware_response_decision_prompt576 import (
    _make_core, _store_a_correction,
)


def _plan_with_correction(understanding, core):
    plan = core.language_intelligence.plan_response(understanding)
    understanding.response_plan = plan.to_dict()
    return plan


def _generate_correction_aware(core):
    """Store a correction, understand a correcting message, plan it, and
    generate the response through LanguageIntelligenceCore directly."""
    _store_a_correction(core.language_learning, "dgo", "dog")
    understanding = core.understand_language("not dgo, I mean dog.")
    _plan_with_correction(understanding, core)
    core.language_intelligence.generate_response(understanding, context=core.context)


def _generate_ordinary(core, text="tell me about xyzzy"):
    understanding = core.understand_language(text)
    core.language_intelligence.generate_response(understanding, context=core.context)


class _OddGenerationBackend(LanguageIntelligenceBackend):
    """Test double, same style as tests.test_response_planning_integration's
    `Odd`/`Failing` backends: a real understand() (delegated to a fresh
    DeterministicFallbackBackend) but a generate_response() that returns a
    plain sentinel instead of a ResponseGenerationResult - standing in for
    a backend that broke its own contract, without needing a real broken
    backend/provider/runtime installed."""

    backend_kind = "deterministic_fallback"

    def __init__(self, inner_understand_backend):
        self._inner = inner_understand_backend

    def understand(self, raw_text, context=None, relevant_context=None,
                    resolved_reference=None, active_topic=None, requested_language=None):
        return self._inner.understand(
            raw_text, context=context, relevant_context=relevant_context,
            resolved_reference=resolved_reference, active_topic=active_topic,
            requested_language=requested_language,
        )

    def generate_response(self, understanding, context=None, **kwargs):
        return object()  # deliberately not a ResponseGenerationResult


class TestNoGeneratedResponseYet(unittest.TestCase):
    """1: both getters are None, stably, before the first
    generate_response() call."""

    def test_fresh_core_both_none_and_stable(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
            # repeated reads before any generation stay None
            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
        finally:
            tmpdir.cleanup()

    def test_standalone_language_intelligence_core_both_none(self):
        real_core, tmpdir = _make_core()
        try:
            lic = LanguageIntelligenceCore(backend=real_core.language_intelligence.backend)
            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
        finally:
            tmpdir.cleanup()


class TestFirstGeneratedResponsePopulatesState(unittest.TestCase):
    """2: the first generate_response() call correctly populates both
    getters, for a correction-aware and an ordinary message."""

    def test_first_call_correction_aware_true(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            conversation = lic.get_last_conversation_response()
            outcome = lic.get_last_response_generation_result()
            self.assertIsInstance(conversation, ConversationResponse)
            self.assertIsInstance(outcome, ResponseGenerationOutcome)
            self.assertTrue(conversation.correction_application_result_usable)
            self.assertTrue(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_first_call_ordinary_false(self):
        core, tmpdir = _make_core()
        try:
            _generate_ordinary(core)
            lic = core.language_intelligence
            conversation = lic.get_last_conversation_response()
            outcome = lic.get_last_response_generation_result()
            self.assertIsInstance(conversation, ConversationResponse)
            self.assertIsInstance(outcome, ResponseGenerationOutcome)
            self.assertFalse(conversation.correction_application_result_usable)
            self.assertFalse(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestMalfunctioningBackendNeverLeavesStaleState(unittest.TestCase):
    """3: a backend that violates its own contract (returns something
    that is not a ResponseGenerationResult) never leaves a previous
    call's True/object visible as current - the cache is unconditionally
    cleared to None before the broken attempt is even evaluated."""

    def test_stale_true_does_not_survive_a_broken_backend_call(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            self.assertTrue(
                lic.get_last_conversation_response().correction_application_result_usable)
            stale_conversation = lic.get_last_conversation_response()
            stale_outcome = lic.get_last_response_generation_result()

            lic.backend = _OddGenerationBackend(lic.backend)
            understanding = core.understand_language("tell me about xyzzy")
            lic.generate_response(understanding, context=core.context)

            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
            # explicitly not the previous objects
            self.assertIsNot(lic.get_last_conversation_response(), stale_conversation)
            self.assertIsNot(lic.get_last_response_generation_result(), stale_outcome)
        finally:
            tmpdir.cleanup()


class TestStateImmediatelyAfterResetBeforeNextGeneration(unittest.TestCase):
    """4: immediately after Core.reset_context() and before the next
    generate_response() call, LanguageIntelligenceCore's getters still
    return the pre-reset object - documenting the existing, intentional
    Core/LIC reset boundary (Prompt 581) - and that value is perfectly
    stable across repeated reads during this window."""

    def test_pre_reset_object_still_current_immediately_after_reset(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            pre_reset_conversation = lic.get_last_conversation_response()
            pre_reset_outcome = lic.get_last_response_generation_result()
            self.assertTrue(pre_reset_conversation.correction_application_result_usable)

            core.reset_context()

            self.assertIs(lic.get_last_conversation_response(), pre_reset_conversation)
            self.assertIs(lic.get_last_response_generation_result(), pre_reset_outcome)
            # repeated reads across the reset window are stable, not
            # re-derived
            for _ in range(3):
                self.assertIs(lic.get_last_conversation_response(), pre_reset_conversation)
                self.assertIs(lic.get_last_response_generation_result(), pre_reset_outcome)
            self.assertTrue(
                lic.get_last_conversation_response().correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestNewResponseAfterResetRepopulatesState(unittest.TestCase):
    """5: generating a new response after reset correctly repopulates the
    public state end to end, in both directions."""

    def test_true_then_reset_then_ordinary_is_false(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            core.reset_context()
            _generate_ordinary(core)

            conversation = lic.get_last_conversation_response()
            outcome = lic.get_last_response_generation_result()
            self.assertFalse(conversation.correction_application_result_usable)
            self.assertFalse(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_false_then_reset_then_correction_aware_is_true(self):
        core, tmpdir = _make_core()
        try:
            _generate_ordinary(core)
            lic = core.language_intelligence
            self.assertFalse(
                lic.get_last_conversation_response().correction_application_result_usable)

            core.reset_context()
            _generate_correction_aware(core)

            conversation = lic.get_last_conversation_response()
            outcome = lic.get_last_response_generation_result()
            self.assertTrue(conversation.correction_application_result_usable)
            self.assertTrue(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestResponseTextPreservedAcrossTransitions(unittest.TestCase):
    """6: response text is correct and consistent between the two
    getters at every lifecycle stage above."""

    def test_text_matches_between_getters_first_and_after_reset(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_correction_aware(core)
            first_conversation = lic.get_last_conversation_response()
            first_outcome = lic.get_last_response_generation_result()
            self.assertEqual(first_conversation.response_text, first_outcome.generated_text)

            core.reset_context()
            _generate_ordinary(core)
            second_conversation = lic.get_last_conversation_response()
            second_outcome = lic.get_last_response_generation_result()
            self.assertEqual(second_conversation.response_text, second_outcome.generated_text)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
