"""
Tests for Prompt 608 - The Exact Publication Boundary of Core-Level
Correction Usability.

Inspection performed by this prompt (core.py): every existing site that
assigns `self.last_conversation_response` (excluding `__init__`'s
`None` default) is immediately followed, as the very next statement,
by a call to `self._refresh_last_response_correction_usable()`:

    _handle_conversation()'s "1d" (the real conversation path, reached
    through process_input()):
        self.last_conversation_response = self.language_intelligence.get_last_conversation_response()
        self._refresh_last_response_correction_usable()

    generate_language_response() (the explicit entry point):
        self.last_conversation_response = self.language_intelligence.get_last_conversation_response()
        self._refresh_last_response_correction_usable()

`_refresh_last_response_correction_usable()` itself (Prompt 580) reads
only `self.last_conversation_response.correction_application_result_
usable` (via `getattr(..., False)`) - never anything else - so by the
time it runs, `self.last_conversation_response` has ALREADY been
reassigned to the CURRENT call's object at both sites; there is no
statement between the two that could let `last_response_correction_
usable` be published from a value read before the cache update. This
is exactly the ordering Prompt 583 already found and Prompt 607 already
exercised indirectly through end-to-end assertions; this file is the
first to observe the ordering directly, at the instant it happens, via
monkeypatch instrumentation - the same class/module-level patch-and-
restore idiom Prompts 598/600/602 already use, applied here to the one
additional call this prompt needs to instrument
(`Core._refresh_last_response_correction_usable`) rather than to a new
production hook.

No production code is changed here (requirement 10): the existing
assignment order already satisfies the contract; this file locks it in
as regression coverage. No new production state, accessor, cache,
abstraction, fallback behavior, or exception handling is added
(requirement 11).

Covers:
    1. correction-aware success -> ordinary success: at the exact
       instant `_refresh_last_response_correction_usable()` runs for
       the second call, `last_conversation_response` is already the
       SECOND call's own object (never the first's), and the refreshed
       usability exactly matches that object's own field
    2. ordinary success -> correction-aware success: same check,
       transition reversed
    3. correction-aware success -> failure: the failing call's own
       refresh reads its OWN (outcome-less) conversation response, not
       the correction-aware predecessor's, so the published value is
       False, never a stale True
    4. ordinary success -> failure: same check with an already-False
       predecessor
    5. failure -> correction-aware recovery: the recovery call's own
       refresh reads its OWN, freshly-successful conversation response,
       not the failed call's outcome-less one
    6. explicit before/after values around the same `_refresh_last_
       response_correction_usable()` call, proving the read happens
       AFTER the cache reassignment, not before, for every one of the
       five transitions above
    7. `Core.reset_context()` continues to clear the Core-level
       usability value according to its existing (Prompt 581/584)
       semantics, observed alongside the same instrumentation
    8. repeated public getter reads after each boundary remain stable
       and read-only

Reuses the Prompt 576 helper (`_make_core`), the Prompt 583 helpers
(`_usable_understanding`, `_unusable_understanding`, `_assert_synced`),
and the Prompt 607 Core-level late-failure helper
(`_generate_with_injected_late_failure_via_core`, itself built on the
Prompt 602 injection) rather than duplicating any of that
infrastructure. Real object references are compared with `assertIs` /
`assertIsNot` throughout; no raw `id()` comparisons, per this prompt's
requirement 14.

Run directly:
    python -m unittest tests.test_correction_aware_response_usable_publication_order_prompt608 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.core as core_module

from tests.test_correction_aware_response_decision_prompt576 import _make_core
from tests.test_correction_aware_core_response_lifecycle_prompt583 import (
    _usable_understanding, _unusable_understanding, _assert_synced,
)
from tests.test_correction_aware_response_usable_cross_field_lifecycle_prompt607 import (
    _generate_with_injected_late_failure_via_core,
)


def _install_refresh_order_spy():
    """Monkeypatch `Core._refresh_last_response_correction_usable`
    (class-level, same patch-and-restore idiom Prompts 598/600/602
    already use for module-level functions) to snapshot, at the exact
    instant it is invoked - i.e. strictly AFTER both existing call
    sites' `self.last_conversation_response = ...` reassignment and
    strictly BEFORE this refresh's own body runs - the instance's
    current `last_conversation_response` and its pre-refresh
    `last_response_correction_usable`, then delegates to the real
    (unchanged) implementation and records the post-refresh value too.
    Returns `(records, restore)`; `records` is a plain list appended to
    once per call, across every Core instance while installed."""
    original = core_module.Core._refresh_last_response_correction_usable
    records = []

    def _spy(self):
        conversation_at_call_time = self.last_conversation_response
        usable_before = self.last_response_correction_usable
        original(self)
        records.append({
            "conversation": conversation_at_call_time,
            "usable_before": usable_before,
            "usable_after": self.last_response_correction_usable,
        })

    core_module.Core._refresh_last_response_correction_usable = _spy

    def _restore():
        core_module.Core._refresh_last_response_correction_usable = original

    return records, _restore


def _expected_usable(conversation):
    """Same fallback `_refresh_last_response_correction_usable()`
    itself already uses - `False` for `None` or a legacy object missing
    the attribute - so tests assert against this, not a second
    computation of usability."""
    return bool(getattr(conversation, "correction_application_result_usable", False))


class TestOrderingAcrossSuccessTransitions(unittest.TestCase):
    """1, 2: at the exact instant the refresh runs, it already reads the
    CURRENT call's own conversation response, never the predecessor's,
    on both success-to-success transitions."""

    def test_correction_aware_then_ordinary(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            prev_conversation = core.get_last_conversation_response()

            records, restore = _install_refresh_order_spy()
            try:
                core.generate_language_response(_unusable_understanding(core))
            finally:
                restore()

            self.assertEqual(len(records), 1)
            snapshot = records[0]
            self.assertIsNot(snapshot["conversation"], prev_conversation)
            self.assertIs(snapshot["conversation"], core.get_last_conversation_response())
            self.assertEqual(snapshot["usable_after"],
                              _expected_usable(snapshot["conversation"]))
            self.assertFalse(snapshot["usable_after"])
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_ordinary_then_correction_aware(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_unusable_understanding(core))
            prev_conversation = core.get_last_conversation_response()

            records, restore = _install_refresh_order_spy()
            try:
                core.generate_language_response(_usable_understanding(core))
            finally:
                restore()

            self.assertEqual(len(records), 1)
            snapshot = records[0]
            self.assertIsNot(snapshot["conversation"], prev_conversation)
            self.assertIs(snapshot["conversation"], core.get_last_conversation_response())
            self.assertEqual(snapshot["usable_after"],
                              _expected_usable(snapshot["conversation"]))
            self.assertTrue(snapshot["usable_after"])
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestOrderingIntoFailure(unittest.TestCase):
    """3, 4: a failing call's own refresh reads its OWN (outcome-less)
    conversation response, never a successful predecessor's - so the
    published value is False regardless of what the predecessor was."""

    def test_correction_aware_success_then_failure(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            prev_conversation = core.get_last_conversation_response()
            self.assertTrue(core.get_last_response_correction_usable())

            records, restore = _install_refresh_order_spy()
            try:
                _generate_with_injected_late_failure_via_core(
                    core, _unusable_understanding(core))
            finally:
                restore()

            self.assertEqual(len(records), 1)
            snapshot = records[0]
            self.assertIsNot(snapshot["conversation"], prev_conversation)
            self.assertIs(snapshot["conversation"], core.get_last_conversation_response())
            self.assertIsNone(snapshot["conversation"].response_text)
            # the failing call's refresh published False from its OWN
            # outcome-less response - never the predecessor's stale True.
            self.assertTrue(snapshot["usable_before"])  # stale value still there just before
            self.assertFalse(snapshot["usable_after"])
            self.assertEqual(snapshot["usable_after"],
                              _expected_usable(snapshot["conversation"]))
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_ordinary_success_then_failure(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_unusable_understanding(core))
            prev_conversation = core.get_last_conversation_response()
            self.assertFalse(core.get_last_response_correction_usable())

            records, restore = _install_refresh_order_spy()
            try:
                _generate_with_injected_late_failure_via_core(
                    core, _unusable_understanding(core))
            finally:
                restore()

            self.assertEqual(len(records), 1)
            snapshot = records[0]
            self.assertIsNot(snapshot["conversation"], prev_conversation)
            self.assertIs(snapshot["conversation"], core.get_last_conversation_response())
            self.assertFalse(snapshot["usable_before"])
            self.assertFalse(snapshot["usable_after"])
            self.assertEqual(snapshot["usable_after"],
                              _expected_usable(snapshot["conversation"]))
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestOrderingOutOfFailure(unittest.TestCase):
    """5: the recovery call's own refresh reads its OWN, freshly-
    successful conversation response, never the failed call's
    outcome-less one."""

    def test_failure_then_correction_aware_recovery(self):
        core, tmpdir = _make_core()
        try:
            _generate_with_injected_late_failure_via_core(
                core, _unusable_understanding(core))
            failed_conversation = core.get_last_conversation_response()
            self.assertFalse(core.get_last_response_correction_usable())

            records, restore = _install_refresh_order_spy()
            try:
                core.generate_language_response(_usable_understanding(core))
            finally:
                restore()

            self.assertEqual(len(records), 1)
            snapshot = records[0]
            self.assertIsNot(snapshot["conversation"], failed_conversation)
            self.assertIs(snapshot["conversation"], core.get_last_conversation_response())
            self.assertFalse(snapshot["usable_before"])
            self.assertTrue(snapshot["usable_after"])
            self.assertEqual(snapshot["usable_after"],
                              _expected_usable(snapshot["conversation"]))
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestBeforeAfterOrderingAcrossAllFiveTransitions(unittest.TestCase):
    """6: a single continuous session running all five required
    transitions back to back, with the spy installed for the whole
    session, so every one of the five refresh calls is captured and
    checked for the same before/after/current-not-previous ordering in
    one place."""

    def test_full_five_transition_sequence(self):
        core, tmpdir = _make_core()
        try:
            records, restore = _install_refresh_order_spy()
            try:
                # 1: correction-aware success
                core.generate_language_response(_usable_understanding(core))
                # 2: -> ordinary success
                core.generate_language_response(_unusable_understanding(core))
                # 3: -> failure
                _generate_with_injected_late_failure_via_core(
                    core, _unusable_understanding(core))
                # 4: -> correction-aware recovery (also exercises
                #    ordinary success -> failure -> correction-aware
                #    together with step 3's ordinary predecessor)
                core.generate_language_response(_usable_understanding(core))
                # 5: -> ordinary success again
                core.generate_language_response(_unusable_understanding(core))
            finally:
                restore()

            self.assertEqual(len(records), 5)
            expected_usable = [True, False, False, True, False]
            for i, snapshot in enumerate(records):
                self.assertEqual(snapshot["usable_after"], expected_usable[i],
                                  msg="mismatch at step %d" % (i + 1))
                self.assertEqual(snapshot["usable_after"],
                                  _expected_usable(snapshot["conversation"]))
            # no two consecutive steps share the same conversation object
            for i in range(1, len(records)):
                self.assertIsNot(records[i]["conversation"], records[i - 1]["conversation"])
            # the final recorded conversation is exactly the current one
            self.assertIs(records[-1]["conversation"], core.get_last_conversation_response())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestResetContextSemanticsPreservedAlongsideInstrumentation(unittest.TestCase):
    """7: reset_context() (Prompt 581/584) still clears the Core-level
    usability value to False even though it does not itself go through
    `_refresh_last_response_correction_usable()` (it assigns the
    attribute directly) - installing the spy must not change that, and
    the next real response after a reset produces a genuinely fresh,
    correctly-ordered refresh."""

    def test_reset_then_recovery_observed_with_spy_installed(self):
        core, tmpdir = _make_core()
        try:
            records, restore = _install_refresh_order_spy()
            try:
                core.generate_language_response(_usable_understanding(core))
                self.assertTrue(core.get_last_response_correction_usable())
                cached_conversation = core.get_last_conversation_response()

                core.reset_context()
                # reset_context() does not call the refresh - no new
                # record - yet the getter is already False.
                self.assertEqual(len(records), 1)
                self.assertFalse(core.get_last_response_correction_usable())
                # the untouched cached object would still say True on
                # its own (Prompt 581/584's documented distinction).
                self.assertIs(core.get_last_conversation_response(), cached_conversation)
                self.assertTrue(cached_conversation.correction_application_result_usable)

                core.generate_language_response(_unusable_understanding(core))
            finally:
                restore()

            self.assertEqual(len(records), 2)
            snapshot = records[-1]
            self.assertIsNot(snapshot["conversation"], cached_conversation)
            self.assertIs(snapshot["conversation"], core.get_last_conversation_response())
            self.assertFalse(snapshot["usable_after"])
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestRepeatedGetterReadsAfterEachBoundaryAreReadOnly(unittest.TestCase):
    """8: repeated public getter reads after each transition never
    mutate `last_conversation_response`, `last_response_correction_
    usable`, or the relationship between them - with the spy installed,
    repeated reads must never trigger another recorded refresh call."""

    def test_repeated_reads_after_success_and_after_failure(self):
        core, tmpdir = _make_core()
        try:
            records, restore = _install_refresh_order_spy()
            try:
                core.generate_language_response(_usable_understanding(core))
                self.assertEqual(len(records), 1)
                conversation_first = core.get_last_conversation_response()
                usable_first = core.get_last_response_correction_usable()

                for _ in range(5):
                    self.assertIs(core.get_last_conversation_response(), conversation_first)
                    self.assertEqual(core.get_last_response_correction_usable(), usable_first)
                self.assertEqual(len(records), 1)  # no extra refresh triggered by reads

                _generate_with_injected_late_failure_via_core(
                    core, _unusable_understanding(core))
                self.assertEqual(len(records), 2)
                conversation_second = core.get_last_conversation_response()
                usable_second = core.get_last_response_correction_usable()
                self.assertIsNot(conversation_second, conversation_first)
                self.assertFalse(usable_second)

                for _ in range(5):
                    self.assertIs(core.get_last_conversation_response(), conversation_second)
                    self.assertEqual(core.get_last_response_correction_usable(), usable_second)
                self.assertEqual(len(records), 2)
            finally:
                restore()
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
