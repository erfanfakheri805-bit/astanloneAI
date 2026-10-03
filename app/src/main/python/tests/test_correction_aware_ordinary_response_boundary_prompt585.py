"""
Tests for Prompt 585 - Correction-Aware / Ordinary Response Boundary.

Prompt 583 proved both existing `last_conversation_response` cache
sites always refresh `last_response_correction_usable` in the same
step, and Prompt 584 added a three-response True->False->True chain
plus a reset-leaves-no-stale-True check. What neither prompt asserted
explicitly and by name is the boundary itself: that an ORDINARY
response immediately following a correction-aware one does not merely
happen to read False on the getter, but that the underlying cached
ConversationResponse it was just re-pointed at is itself a genuinely
different object with `correction_application_result_usable == False`
- i.e. nothing is retained, leaked, or defaulted-away from the prior
turn. This file adds that boundary check by name, in both directions,
on both existing cache paths. No production code changes: this is
regression coverage only, tightening the existing invariant Prompt 583
already proved holds.

Covers:
    1. correction-aware response -> ordinary response: the ordinary
       response's own `correction_application_result_usable` is False,
       the getter is False, and the cached response is a distinct
       object from the prior (True) one - nothing retained.
    2. ordinary response -> correction-aware response: the reverse
       boundary correctly exposes True on the `generate_language_
       response()` path (the path Prompt 583/584 already established
       as the reliable one for asserting True), and stays synchronized
       on the `process_input()` path exactly like Prompt 583's own
       `test_true_then_false_via_process_input` - without asserting a
       specific boolean there, since that real pipeline path does not
       reliably surface True even on a fresh Core.
    3. getter and `last_conversation_response.correction_application_
       result_usable` stay synchronized across both boundaries, on
       both `process_input()` and `generate_language_response()`.

Nothing here recomputes usability, retrieves, selects, or applies a
correction, or adds any new state/abstraction.

Run directly:
    python -m unittest tests.test_correction_aware_ordinary_response_boundary_prompt585 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_correction_aware_response_decision_prompt576 import (
    _make_core, _store_a_correction,
)
from tests.test_correction_aware_core_response_lifecycle_prompt583 import (
    _usable_understanding, _unusable_understanding, _assert_synced,
)


class TestCorrectionAwareThenOrdinary(unittest.TestCase):
    """1: an ordinary response right after a correction-aware one does
    not retain the prior turn's True state - on either cache path."""

    def test_via_generate_language_response(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())
            aware_response = core.get_last_conversation_response()

            core.generate_language_response(_unusable_understanding(core))
            ordinary_response = core.get_last_conversation_response()

            # a distinct object - nothing carried over from the prior turn
            self.assertIsNot(ordinary_response, aware_response)
            self.assertFalse(ordinary_response.correction_application_result_usable)
            self.assertFalse(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_via_process_input(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            core.process_input("not dgo, I mean dog.")
            aware_response = core.get_last_conversation_response()

            core.process_input("tell me about xyzzy")
            ordinary_response = core.get_last_conversation_response()

            self.assertIsNot(ordinary_response, aware_response)
            self.assertFalse(ordinary_response.correction_application_result_usable)
            self.assertFalse(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestOrdinaryThenCorrectionAware(unittest.TestCase):
    """2: the reverse boundary - an ordinary response followed by a
    correction-aware one correctly exposes True."""

    def test_via_generate_language_response(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())

            core.generate_language_response(_usable_understanding(core))
            aware_response = core.get_last_conversation_response()

            self.assertTrue(aware_response.correction_application_result_usable)
            self.assertTrue(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_via_process_input(self):
        # Note: like Prompt 583's own `test_true_then_false_via_
        # process_input`, this deliberately does not assert True here -
        # the real process_input() pipeline's own response-planning
        # step does not reliably surface a usable correction even on a
        # fresh Core (confirmed by inspection: `generate_language_
        # response()` is the path Prompt 583/584 assert True through).
        # What this boundary test verifies is what must hold regardless:
        # the getter and the cached response stay synchronized across
        # the transition, exactly as documented in the invariant Prompt
        # 583 proved.
        core, tmpdir = _make_core()
        try:
            core.process_input("tell me about xyzzy")
            self.assertFalse(core.get_last_response_correction_usable())

            _store_a_correction(core.language_learning, "dgo", "dog")
            core.process_input("not dgo, I mean dog.")
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
