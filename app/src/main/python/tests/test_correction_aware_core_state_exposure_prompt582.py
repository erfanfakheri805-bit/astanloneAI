"""
Tests for Prompt 582 - Confirm the Stable Read Path for Correction-Aware
Core State.

Prompt 580 added `Core.get_last_response_correction_usable()`, and Prompt
581 made `reset_context()` clear the state it reads back to False. This
prompt inspected every existing caller/accessor around
`Core.get_last_conversation_response()` and
`Core.get_last_response_correction_usable()` (core.py, language_
intelligence/__init__.py, language_intelligence/language_intelligence_
core.py, and the tests/ package) and found no higher-level module reads
`last_response_correction_usable` directly, and no forwarding accessor is
missing - `get_last_response_correction_usable()` already IS the correct,
stable, single public read path for this state, following the exact same
getter pattern as `get_last_language_response()` and
`get_last_conversation_response()`.

No new accessor, subsystem, or parallel state model was added. This is a
documentation clarification (the getter's docstring now distinguishes
"never populated" (None) from "explicitly reset" (False)) plus this
focused test file, verifying that single read path end to end.

Covers:
    1. usable correction state (True) via the stable read path
    2. false/default state via the stable read path
    3. reset state via the stable read path (Prompt 581)
    4. legacy/missing response state via the stable read path
    5. repeated reads never mutate anything

Run directly:
    python -m unittest tests.test_correction_aware_core_state_exposure_prompt582 -v
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
    core, tmpdir = _make_core()
    _store_a_correction(core.language_learning, "dgo", "dog")
    understanding = core.understand_language("not dgo, I mean dog.")
    plan = core.language_intelligence.plan_response(understanding)
    understanding.response_plan = plan.to_dict()
    core.generate_language_response(understanding)
    return core, tmpdir


class TestUsableStateViaStableReadPath(unittest.TestCase):
    """1: a real, applied correction is visible through
    get_last_response_correction_usable(), and matches the raw attribute
    and the ConversationResponse it was derived from."""

    def test_true_via_getter(self):
        core, tmpdir = _make_usable_core()
        try:
            self.assertTrue(core.get_last_response_correction_usable())
            self.assertEqual(
                core.get_last_response_correction_usable(),
                core.last_response_correction_usable)
            self.assertEqual(
                core.get_last_response_correction_usable(),
                core.get_last_conversation_response().correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestFalseDefaultStateViaStableReadPath(unittest.TestCase):
    """2: a not-applied/unusable correction, and an ordinary message,
    both read as False through the same getter."""

    def test_not_applied_correction_result(self):
        core, tmpdir = _make_core()
        try:
            plan = ResponsePlan(
                correction_application_result=_not_applied_result_dict(),
                **_base_plan_kwargs())
            understanding = core.understand_language("hello there")
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()

    def test_ordinary_message_via_process_input(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("tell me about xyzzy")
            self.assertIsNotNone(core.get_last_conversation_response())
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


class TestResetStateViaStableReadPath(unittest.TestCase):
    """3: after reset_context() (Prompt 581), the getter reads back the
    explicit False reset leaves behind - not the stale True."""

    def test_getter_reflects_reset(self):
        core, tmpdir = _make_usable_core()
        try:
            self.assertTrue(core.get_last_response_correction_usable())
            core.reset_context()
            self.assertFalse(core.get_last_response_correction_usable())
            self.assertIs(core.get_last_response_correction_usable(), False)
        finally:
            tmpdir.cleanup()


class TestLegacyOrMissingResponseStateViaStableReadPath(unittest.TestCase):
    """4: before any conversational message, for AEL input, and for a
    legacy ConversationResponse missing the field entirely, the getter
    safely returns None/False rather than raising."""

    def test_fresh_core_returns_none(self):
        core, tmpdir = _make_core()
        try:
            self.assertIsNone(core.get_last_conversation_response())
            self.assertIsNone(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()

    def test_ael_input_leaves_it_none(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("TEACH sun IS a star")
            self.assertIsNone(core.get_last_response_correction_usable())
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


class TestRepeatedReadsNeverMutate(unittest.TestCase):
    """5: reading the stable path repeatedly returns the exact same
    value every time and never re-triggers correction retrieval/
    selection/application/usability computation."""

    def test_repeated_reads_are_stable(self):
        core, tmpdir = _make_usable_core()
        try:
            first = core.get_last_response_correction_usable()
            second = core.get_last_response_correction_usable()
            third = core.get_last_response_correction_usable()
            self.assertEqual([first, second, third], [True, True, True])
        finally:
            tmpdir.cleanup()

    def test_repeated_reads_do_not_change_cached_conversation_response(self):
        core, tmpdir = _make_usable_core()
        try:
            conversation_before = core.get_last_conversation_response()
            core.get_last_response_correction_usable()
            core.get_last_response_correction_usable()
            self.assertIs(core.get_last_conversation_response(), conversation_before)
            self.assertTrue(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
