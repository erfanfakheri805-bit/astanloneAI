"""
Tests for Prompt 584 - Correction-Aware Core Consecutive Responses
Regression Strengthening.

Prompt 583 already proved, by inspection, that every existing site
that assigns `self.last_conversation_response` is immediately followed
by `self._refresh_last_response_correction_usable()`, and covered
True->False and False->True two-step transitions (on both cache
paths) plus a reset followed by one new response. This file adds only
the two smallest regression gaps left after that inspection - no
production code changes:

    1. A three-response chain in a single test - True, then an
       ordinary False, then a correction-aware True again - checking
       that `get_last_conversation_response()` and
       `get_last_response_correction_usable()` stay synchronized after
       *each* of the three transitions (not just the first and last),
       on both the real `process_input()` path and the explicit
       `generate_language_response()` path.
    2. `reset_context()` between two responses cannot leave stale True
       state behind even though it deliberately leaves
       `last_conversation_response` itself untouched (Prompt 581) -
       i.e. the getter must read False immediately after reset even
       while the cached ConversationResponse it would otherwise be
       derived from still reports True.

Nothing here recomputes usability, retrieves, selects, or applies a
correction, or adds any new state/abstraction.

Run directly:
    python -m unittest tests.test_correction_aware_core_consecutive_responses_prompt584 -v
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


class TestThreeResponseChain(unittest.TestCase):
    """1: True -> False -> True in a single continuous session, synced
    after every individual transition, on both cache paths."""

    def test_true_false_true_via_generate_language_response(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())
            _assert_synced(self, core)

            core.generate_language_response(_unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())
            _assert_synced(self, core)

            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_true_false_true_via_process_input(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            core.process_input("not dgo, I mean dog.")
            _assert_synced(self, core)

            core.process_input("tell me about xyzzy")
            self.assertFalse(core.get_last_response_correction_usable())
            _assert_synced(self, core)

            _store_a_correction(core.language_learning, "teh", "the")
            core.process_input("not teh, I mean the.")
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestResetLeavesNoStaleTrue(unittest.TestCase):
    """2: reset_context() must clear the getter to False immediately,
    even though `last_conversation_response` itself is left unchanged
    (and would still, on its own, report correction_application_
    result_usable=True) until the next response repopulates it."""

    def test_getter_false_immediately_after_reset_despite_unchanged_cached_response(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())
            cached_response = core.get_last_conversation_response()
            self.assertTrue(cached_response.correction_application_result_usable)

            core.reset_context()

            # last_conversation_response is deliberately untouched by
            # reset (Prompt 581) - still the same, still-True object...
            self.assertIs(core.get_last_conversation_response(), cached_response)
            self.assertTrue(cached_response.correction_application_result_usable)
            # ...yet the getter itself must not leak that stale True.
            self.assertFalse(core.get_last_response_correction_usable())
            self.assertFalse(core.last_response_correction_usable)
        finally:
            tmpdir.cleanup()

    def test_reset_between_two_usable_responses_leaves_no_stale_true(self):
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


if __name__ == "__main__":
    unittest.main()
