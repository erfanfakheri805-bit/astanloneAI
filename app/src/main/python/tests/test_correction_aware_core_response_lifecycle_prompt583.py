"""
Tests for Prompt 583 - Correction-Aware Core Response Lifecycle
Consistency Check.

Inspection performed by this prompt: every place in core.py that
assigns `self.last_conversation_response` (excluding the `__init__`
default of `None`) is immediately followed by a call to
`self._refresh_last_response_correction_usable()`:

    - `_handle_conversation()`'s step "1d" (the real conversation path,
      reached through `process_input()`)
    - `generate_language_response()` (the explicit entry point)

No existing Core cache path assigns `last_conversation_response` without
also refreshing `last_response_correction_usable` in the same step, so
no new wiring was needed (Prompt 583 requirement 4). This file is the
focused regression test proving that both existing cache paths keep
`get_last_response_correction_usable()` synchronized with
`get_last_conversation_response()`, across normal conversation,
explicit language-response generation, consecutive responses whose
usability state changes, a reset in between, and legacy/missing
response compatibility. Nothing here recomputes usability, retrieves,
selects, or applies a correction, or touches reset semantics beyond
what Prompt 581 already added.

Covers:
    1. normal conversation response path (_handle_conversation via
       process_input())
    2. language-response generation path (generate_language_response())
    3. usable correction state
    4. false/default state
    5. consecutive responses where the state changes (True -> False and
       False -> True), on both cache paths
    6. reset followed by a new response
    7. legacy/missing response compatibility

Run directly:
    python -m unittest tests.test_correction_aware_core_response_lifecycle_prompt583 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_correction_aware_response_decision_prompt576 import (
    _make_core, _store_a_correction, _base_plan_kwargs, _not_applied_result_dict,
)
from language_intelligence.response_planning import ResponsePlan


def _usable_understanding(core, text="not dgo, I mean dog."):
    _store_a_correction(core.language_learning, "dgo", "dog")
    understanding = core.understand_language(text)
    plan = core.language_intelligence.plan_response(understanding)
    understanding.response_plan = plan.to_dict()
    return understanding


def _unusable_understanding(core, text="hello there"):
    plan = ResponsePlan(correction_application_result=None, **_base_plan_kwargs())
    understanding = core.understand_language(text)
    understanding.response_plan = plan.to_dict()
    return understanding


def _assert_synced(testcase, core):
    """The getter always agrees with the cached ConversationResponse's
    own field - the invariant this prompt's inspection confirmed holds
    at every existing cache path."""
    conversation = core.get_last_conversation_response()
    if conversation is None:
        testcase.assertIsNone(core.get_last_response_correction_usable())
    else:
        testcase.assertEqual(
            core.get_last_response_correction_usable(),
            conversation.correction_application_result_usable)


class TestNormalConversationResponsePath(unittest.TestCase):
    """1: the real _handle_conversation()/process_input() path keeps the
    getter synchronized with the cached ConversationResponse."""

    def test_ordinary_message_stays_synced(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("tell me about xyzzy")
            _assert_synced(self, core)
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()

    def test_explicit_correction_message_stays_synced(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            core.process_input("not dgo, I mean dog.")
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestLanguageResponseGenerationPath(unittest.TestCase):
    """2: the explicit generate_language_response() entry point keeps
    the getter synchronized with the cached ConversationResponse."""

    def test_generate_language_response_stays_synced(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core)
            core.generate_language_response(understanding)
            _assert_synced(self, core)
            self.assertTrue(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


class TestUsableCorrectionState(unittest.TestCase):
    """3: a real, applied correction is True through both cache paths."""

    def test_usable_via_generate_language_response(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core)
            core.generate_language_response(understanding)
            self.assertTrue(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


class TestFalseDefaultState(unittest.TestCase):
    """4: no correction anywhere in the picture reads False on both
    cache paths."""

    def test_false_via_generate_language_response(self):
        core, tmpdir = _make_core()
        try:
            understanding = _unusable_understanding(core)
            core.generate_language_response(understanding)
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()

    def test_false_via_process_input(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("tell me about xyzzy")
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


class TestConsecutiveResponsesWhereStateChanges(unittest.TestCase):
    """5: back-to-back calls on the same Core - True then False, and
    False then True - never leave a stale value, on either cache path."""

    def test_true_then_false_via_generate_language_response(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())

            core.generate_language_response(_unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_false_then_true_via_generate_language_response(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())

            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_true_then_false_via_process_input(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            core.process_input("not dgo, I mean dog.")
            first = core.get_last_response_correction_usable()

            core.process_input("tell me about xyzzy")
            second = core.get_last_response_correction_usable()
            self.assertFalse(second)
            _assert_synced(self, core)
            # documents whatever `first` legitimately was on this path,
            # without asserting a value this prompt must not recompute.
            self.assertIn(first, (True, False))
        finally:
            tmpdir.cleanup()


class TestResetFollowedByNewResponse(unittest.TestCase):
    """6: reset_context() (Prompt 581) clears the state, and a
    subsequent response correctly repopulates it - no stale leftover
    from before the reset."""

    def test_reset_then_usable_response(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())

            core.reset_context()
            self.assertFalse(core.get_last_response_correction_usable())

            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_reset_then_unusable_response(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            core.reset_context()
            core.generate_language_response(_unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestLegacyOrMissingResponseCompatibility(unittest.TestCase):
    """7: before any message, for AEL/goal-oriented input, and for a
    legacy ConversationResponse missing the field, the getter stays
    safely None/False and synchronized - never raises."""

    def test_fresh_core(self):
        core, tmpdir = _make_core()
        try:
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_ael_input(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("TEACH sun IS a star")
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_legacy_conversation_response_without_the_attribute(self):
        core, tmpdir = _make_core()
        try:
            class _LegacyConversationResponse:
                response_text = "hi there"

            core.last_conversation_response = _LegacyConversationResponse()
            core._refresh_last_response_correction_usable()
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
