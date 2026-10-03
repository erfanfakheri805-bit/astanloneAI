"""
Tests for Prompt 581 - Reset Correction-Aware Response State Consistently.

Prompt 580 added `Core.last_response_correction_usable`, refreshed by
`Core._refresh_last_response_correction_usable()` at the same sites that
already cache `self.last_conversation_response`, and exposed through
`Core.get_last_response_correction_usable()`. Nothing reset it back to
its safe default (False) when the rest of Core's short-term context is
reset via the existing `reset_context()`.

This prompt makes `reset_context()` - the one existing reset lifecycle
Core already has for `self.context`/`self.topic_tracker`/`self.
conversation_state` - also reset `last_response_correction_usable` to
False, through that same existing mechanism (no parallel reset path
added).

Covers:
    1. state becomes True after a correction-aware response
    2. reset_context() clears it to False
    3. get_last_response_correction_usable() reflects the reset state
    4. ordinary/legacy state remains safely False
    5. repeated reset is safe/idempotent

Run directly:
    python -m unittest tests.test_correction_aware_core_response_reset_prompt581 -v
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


def _make_usable_core():
    """A Core whose last_response_correction_usable is True, via the
    same explicit-entry-point pattern the Prompt 576-580 tests use."""
    core, tmpdir = _make_core()
    _store_a_correction(core.language_learning, "dgo", "dog")
    understanding = core.understand_language("not dgo, I mean dog.")
    plan = core.language_intelligence.plan_response(understanding)
    understanding.response_plan = plan.to_dict()
    core.generate_language_response(understanding)
    return core, tmpdir


class TestStateBecomesTrueAfterCorrectionAwareResponse(unittest.TestCase):
    """1: sanity check - the state this prompt resets is actually True
    beforehand, using the same real correction pipeline Prompt 580 used."""

    def test_true_before_reset(self):
        core, tmpdir = _make_usable_core()
        try:
            self.assertTrue(core.get_last_response_correction_usable())
            self.assertTrue(core.last_response_correction_usable)
        finally:
            tmpdir.cleanup()


class TestResetContextClearsItToFalse(unittest.TestCase):
    """2: reset_context() - the existing reset lifecycle - clears the
    new state to False."""

    def test_reset_clears_attribute(self):
        core, tmpdir = _make_usable_core()
        try:
            self.assertTrue(core.last_response_correction_usable)
            core.reset_context()
            self.assertFalse(core.last_response_correction_usable)
            self.assertIs(core.last_response_correction_usable, False)
        finally:
            tmpdir.cleanup()

    def test_reset_also_clears_existing_context_state(self):
        """The new line doesn't disturb what reset_context() already
        cleared before this prompt."""
        core, tmpdir = _make_usable_core()
        try:
            core.process_input("tell me about xyzzy")
            self.assertGreater(len(core.get_recent_turns()), 0)
            core.reset_context()
            self.assertEqual(len(core.get_recent_turns()), 0)
            self.assertFalse(core.last_response_correction_usable)
        finally:
            tmpdir.cleanup()


class TestGetterReflectsResetState(unittest.TestCase):
    """3: get_last_response_correction_usable() reflects the reset,
    not just the raw attribute."""

    def test_getter_reflects_reset(self):
        core, tmpdir = _make_usable_core()
        try:
            self.assertTrue(core.get_last_response_correction_usable())
            core.reset_context()
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()

    def test_last_conversation_response_untouched_by_reset(self):
        """reset_context() resets only the new field - the underlying
        ConversationResponse object it was derived from is left exactly
        as before this prompt (unreset), same as last_language_response."""
        core, tmpdir = _make_usable_core()
        try:
            conversation_before = core.get_last_conversation_response()
            self.assertIsNotNone(conversation_before)
            core.reset_context()
            self.assertIs(core.get_last_conversation_response(), conversation_before)
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


class TestOrdinaryOrLegacyStateStaysFalse(unittest.TestCase):
    """4: an ordinary/no-correction state (already False) stays False
    across a reset - reset never fabricates True, and a fresh Core's
    reset behaves the same way."""

    def test_false_before_reset_stays_false(self):
        core, tmpdir = _make_core()
        try:
            plan = ResponsePlan(
                correction_application_result=_not_applied_result_dict(),
                **_base_plan_kwargs())
            understanding = core.understand_language("hello there")
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            self.assertFalse(core.get_last_response_correction_usable())
            core.reset_context()
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()

    def test_fresh_core_reset_stays_none_or_false(self):
        """A Core that never processed a message has
        last_response_correction_usable=None (Prompt 580's own
        documented default); resetting it makes it the reset's explicit
        False - never raises either way."""
        core, tmpdir = _make_core()
        try:
            self.assertIsNone(core.last_response_correction_usable)
            core.reset_context()
            self.assertFalse(core.last_response_correction_usable)
        finally:
            tmpdir.cleanup()


class TestRepeatedResetIsSafeAndIdempotent(unittest.TestCase):
    """5: calling reset_context() repeatedly is safe and always leaves
    the same False result."""

    def test_repeated_reset_idempotent(self):
        core, tmpdir = _make_usable_core()
        try:
            core.reset_context()
            first = core.last_response_correction_usable
            core.reset_context()
            second = core.last_response_correction_usable
            core.reset_context()
            third = core.last_response_correction_usable
            self.assertEqual([first, second, third], [False, False, False])
        finally:
            tmpdir.cleanup()

    def test_reset_then_new_usable_response_then_reset_again(self):
        """Reset -> a fresh correction-aware response makes it True
        again -> reset clears it again, deterministically."""
        core, tmpdir = _make_core()
        try:
            core.reset_context()
            self.assertFalse(core.last_response_correction_usable)

            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            self.assertTrue(core.last_response_correction_usable)

            core.reset_context()
            self.assertFalse(core.last_response_correction_usable)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
