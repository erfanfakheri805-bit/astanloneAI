"""
Tests for Prompt 616 - The Exact Publication Order of Core-Level
`last_response_generation_result`, `last_conversation_response`, and
`last_response_normalized_input`.

Inspection performed by this prompt (core.py): both existing Core
response-generation cache sites already assign, in this order, as
consecutive statements:

    _handle_conversation()'s "1d" (the real conversation path, reached
    through process_input()) and generate_language_response() (the
    explicit entry point):
        self.last_conversation_response = self.language_intelligence.get_last_conversation_response()
        self.last_response_generation_result = self.language_intelligence.get_last_response_generation_result()
        self._refresh_last_response_correction_usable()
        self._refresh_last_response_normalized_input()

Both `self.last_conversation_response` and `self.last_response_
generation_result` are straight, independent forwards of state that
`LanguageIntelligenceCore.generate_response()` (called just above, and
already returned by the time either line runs) built and cached
together for the SAME call - see that method's own docstring
(response_generation.py / language_intelligence_core.py). Neither read
depends on, blocks on, or can observe the other mid-update: there is no
statement between them that reads either value, and nothing else in
this single-threaded call re-enters `generate_response()` in between.
By the time `_refresh_last_response_normalized_input()` runs (last in
the sequence), both `last_conversation_response` and `last_response_
generation_result` are therefore ALREADY the CURRENT call's own
objects - there is no transient or stale-state window at this
boundary, so the existing assignment order already satisfies the
Prompt 616 contract (requirement 5): no production change is made
here.

This file locks that ordering in as regression coverage, using the
same class-level monkeypatch spy-and-restore idiom Prompts 598/600/
602/608 already use, applied here to `Core._refresh_last_response_
normalized_input` (an existing hook - Prompt 613 - not a new
production one).

Covers (per Prompt 616 requirements 8-13):
    1. normalized response -> ordinary response
    2. ordinary response -> normalized response
    3. normalized response -> failure
    4. ordinary response -> failure
    5. failure -> normalized recovery
    6. at the exact refresh boundary: last_response_generation_result
       and last_conversation_response already belong to the current
       call; last_response_normalized_input is derived from the
       current state only; no previous-call value is ever read
    7. failure behavior: no stale generation result, normalized input,
       or conversation response survives
    8. reset_context() preserves its existing semantics for all three
       states
    9. repeated public getter reads are read-only and stable
    10. legacy response-generation/conversation objects without
        normalized_input remain safe

Reuses the Prompt 576 helper (`_make_core`), the Prompt 583 helpers
(`_usable_understanding`, `_unusable_understanding`, `_assert_synced`),
and the Prompt 607 Core-level late-failure helper
(`_generate_with_injected_late_failure_via_core`, itself built on the
Prompt 602 injection) rather than duplicating any of that
infrastructure. Real object references are compared with `assertIs`/
`assertIsNot` throughout; no raw `id()` comparisons (requirement 15).

Run directly:
    python -m unittest tests.test_response_generation_result_publication_order_prompt616 -v
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
from language_intelligence.conversation_response import ConversationResponse


def _install_normalized_refresh_order_spy():
    """Monkeypatch `Core._refresh_last_response_normalized_input`
    (class-level, same patch-and-restore idiom Prompts 598/600/602/608
    already use) to snapshot, at the exact instant it is invoked -
    i.e. strictly AFTER both existing call sites' `self.last_
    conversation_response` / `self.last_response_generation_result`
    reassignment and strictly BEFORE this refresh's own body runs -
    the instance's current `last_conversation_response` and
    `last_response_generation_result`, plus the pre-refresh
    `last_response_normalized_input`, then delegates to the real
    (unchanged) implementation and records the post-refresh value too.
    Returns `(records, restore)`; `records` is a plain list appended to
    once per call, across every Core instance while installed."""
    original = core_module.Core._refresh_last_response_normalized_input
    records = []

    def _spy(self):
        conversation_at_call_time = self.last_conversation_response
        generation_result_at_call_time = self.last_response_generation_result
        normalized_before = self.last_response_normalized_input
        original(self)
        records.append({
            "conversation": conversation_at_call_time,
            "generation_result": generation_result_at_call_time,
            "normalized_before": normalized_before,
            "normalized_after": self.last_response_normalized_input,
        })

    core_module.Core._refresh_last_response_normalized_input = _spy

    def _restore():
        core_module.Core._refresh_last_response_normalized_input = original

    return records, _restore


def _expected_normalized(conversation):
    """Same fallback `_refresh_last_response_normalized_input()` itself
    already uses - None for a missing/legacy conversation response -
    so tests assert against this, not a second computation."""
    return getattr(conversation, "normalized_input", None)


class TestNormalizedThenOrdinary(unittest.TestCase):
    """1: at the exact instant the refresh runs for the SECOND call,
    all three states already belong to that current call, never the
    normalized predecessor's."""

    def test_via_generate_language_response(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            prev_conversation = core.get_last_conversation_response()
            prev_outcome = core.get_last_response_generation_result()

            records, restore = _install_normalized_refresh_order_spy()
            try:
                core.generate_language_response(_unusable_understanding(core))
            finally:
                restore()

            self.assertEqual(len(records), 1)
            snap = records[0]
            self.assertIsNot(snap["conversation"], prev_conversation)
            self.assertIsNot(snap["generation_result"], prev_outcome)
            self.assertIs(snap["conversation"], core.get_last_conversation_response())
            self.assertIs(snap["generation_result"], core.get_last_response_generation_result())
            self.assertEqual(snap["normalized_after"], _expected_normalized(snap["conversation"]))
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_via_process_input(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("  not dgo,   I mean dog.  ")
            prev_conversation = core.get_last_conversation_response()

            records, restore = _install_normalized_refresh_order_spy()
            try:
                core.process_input("  good   morning  ")
            finally:
                restore()

            self.assertEqual(len(records), 1)
            snap = records[0]
            self.assertIsNot(snap["conversation"], prev_conversation)
            self.assertIs(snap["conversation"], core.get_last_conversation_response())
            self.assertIs(snap["generation_result"], core.get_last_response_generation_result())
            self.assertEqual(snap["normalized_after"], _expected_normalized(snap["conversation"]))
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestOrdinaryThenNormalized(unittest.TestCase):
    """2: the transition reversed."""

    def test_via_generate_language_response(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_unusable_understanding(core))
            prev_conversation = core.get_last_conversation_response()
            prev_outcome = core.get_last_response_generation_result()

            records, restore = _install_normalized_refresh_order_spy()
            try:
                core.generate_language_response(
                    _usable_understanding(core, text="  not dgo,   I mean dog.  "))
            finally:
                restore()

            self.assertEqual(len(records), 1)
            snap = records[0]
            self.assertIsNot(snap["conversation"], prev_conversation)
            self.assertIsNot(snap["generation_result"], prev_outcome)
            self.assertIs(snap["conversation"], core.get_last_conversation_response())
            self.assertIs(snap["generation_result"], core.get_last_response_generation_result())
            self.assertIsNotNone(snap["normalized_after"])
            self.assertEqual(snap["normalized_after"], _expected_normalized(snap["conversation"]))
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestNormalizedThenFailure(unittest.TestCase):
    """3: a failing call's own refresh reads its OWN (outcome-less)
    conversation response and generation result, never the normalized
    predecessor's."""

    def test_failure_after_normalized_success(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(
                _usable_understanding(core, text="  not dgo,   I mean dog.  "))
            prev_conversation = core.get_last_conversation_response()
            prev_outcome = core.get_last_response_generation_result()
            self.assertIsNotNone(core.get_last_response_normalized_input())

            records, restore = _install_normalized_refresh_order_spy()
            try:
                _generate_with_injected_late_failure_via_core(
                    core, _unusable_understanding(core))
            finally:
                restore()

            self.assertEqual(len(records), 1)
            snap = records[0]
            self.assertIsNot(snap["conversation"], prev_conversation)
            self.assertIsNot(snap["generation_result"], prev_outcome)
            self.assertIs(snap["conversation"], core.get_last_conversation_response())
            self.assertIsNone(snap["conversation"].response_text)
            # the stale value was still there just before this refresh...
            self.assertIsNotNone(snap["normalized_before"])
            # ...but never leaks into the published, post-refresh value.
            self.assertNotEqual(snap["normalized_after"], snap["normalized_before"])
            self.assertEqual(snap["normalized_after"], _expected_normalized(snap["conversation"]))
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestOrdinaryThenFailure(unittest.TestCase):
    """4: same check with an already-None-or-plain predecessor."""

    def test_failure_after_ordinary_success(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_unusable_understanding(core))
            prev_conversation = core.get_last_conversation_response()

            records, restore = _install_normalized_refresh_order_spy()
            try:
                _generate_with_injected_late_failure_via_core(
                    core, _unusable_understanding(core))
            finally:
                restore()

            self.assertEqual(len(records), 1)
            snap = records[0]
            self.assertIsNot(snap["conversation"], prev_conversation)
            self.assertIs(snap["conversation"], core.get_last_conversation_response())
            self.assertIsNone(snap["conversation"].response_text)
            self.assertEqual(snap["normalized_after"], _expected_normalized(snap["conversation"]))
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestFailureThenNormalizedRecovery(unittest.TestCase):
    """5: the recovery call's own refresh reads its OWN, freshly-
    successful state, never the failed call's outcome-less one."""

    def test_recovery_after_failure(self):
        core, tmpdir = _make_core()
        try:
            _generate_with_injected_late_failure_via_core(
                core, _unusable_understanding(core))
            failed_conversation = core.get_last_conversation_response()
            failed_outcome = core.get_last_response_generation_result()
            self.assertIsNone(core.get_last_response_normalized_input())

            records, restore = _install_normalized_refresh_order_spy()
            try:
                core.generate_language_response(
                    _usable_understanding(core, text="  not dgo,   I mean dog.  "))
            finally:
                restore()

            self.assertEqual(len(records), 1)
            snap = records[0]
            self.assertIsNot(snap["conversation"], failed_conversation)
            self.assertIsNot(snap["generation_result"], failed_outcome)
            self.assertIs(snap["conversation"], core.get_last_conversation_response())
            self.assertIs(snap["generation_result"], core.get_last_response_generation_result())
            self.assertIsNotNone(snap["normalized_after"])
            self.assertEqual(snap["normalized_after"], _expected_normalized(snap["conversation"]))
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestFullFiveTransitionSequence(unittest.TestCase):
    """6: a single continuous session running all five required
    transitions back to back, with the spy installed for the whole
    session, checking the same before/after/current-not-previous
    ordering for every recorded refresh in one place."""

    def test_full_sequence(self):
        core, tmpdir = _make_core()
        try:
            records, restore = _install_normalized_refresh_order_spy()
            try:
                # 1: normalized success
                core.generate_language_response(
                    _usable_understanding(core, text="  not dgo,   I mean dog.  "))
                # 2: -> ordinary success
                core.generate_language_response(_unusable_understanding(core))
                # 3: -> failure
                _generate_with_injected_late_failure_via_core(
                    core, _unusable_understanding(core))
                # 4: -> normalized recovery
                core.generate_language_response(
                    _usable_understanding(core, text="  not dgo,   I mean dog.  "))
                # 5: -> ordinary success again
                core.generate_language_response(_unusable_understanding(core))
            finally:
                restore()

            self.assertEqual(len(records), 5)
            for i, snap in enumerate(records):
                self.assertIs(snap["conversation"], core.get_last_conversation_response()) \
                    if i == len(records) - 1 else None
                self.assertEqual(
                    snap["normalized_after"], _expected_normalized(snap["conversation"]),
                    msg="mismatch at step %d" % (i + 1))
            # no two consecutive steps share the same objects
            for i in range(1, len(records)):
                self.assertIsNot(records[i]["conversation"], records[i - 1]["conversation"])
                self.assertIsNot(records[i]["generation_result"], records[i - 1]["generation_result"])
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestResetContextSemanticsPreserved(unittest.TestCase):
    """8: reset_context() still clears last_response_normalized_input
    to None (and last_response_correction_usable to False) even though
    it does not itself go through `_refresh_last_response_normalized_
    input()` (it assigns the attribute directly) - and leaves last_
    conversation_response / last_response_generation_result untouched,
    exactly as before this prompt."""

    def test_reset_then_recovery_observed_with_spy_installed(self):
        core, tmpdir = _make_core()
        try:
            records, restore = _install_normalized_refresh_order_spy()
            try:
                core.generate_language_response(
                    _usable_understanding(core, text="  not dgo,   I mean dog.  "))
                self.assertIsNotNone(core.get_last_response_normalized_input())
                cached_conversation = core.get_last_conversation_response()
                cached_outcome = core.get_last_response_generation_result()

                core.reset_context()
                self.assertEqual(len(records), 1)  # reset does not call the refresh
                self.assertIsNone(core.get_last_response_normalized_input())
                # last_conversation_response / last_response_generation_result
                # are deliberately untouched by reset.
                self.assertIs(core.get_last_conversation_response(), cached_conversation)
                self.assertIs(core.get_last_response_generation_result(), cached_outcome)
                self.assertIsNotNone(cached_conversation.normalized_input)

                core.generate_language_response(_unusable_understanding(core))
            finally:
                restore()

            self.assertEqual(len(records), 2)
            snap = records[-1]
            self.assertIsNot(snap["conversation"], cached_conversation)
            self.assertIsNot(snap["generation_result"], cached_outcome)
            self.assertIs(snap["conversation"], core.get_last_conversation_response())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestRepeatedGetterReadsAreReadOnly(unittest.TestCase):
    """9: repeated public getter reads after each transition never
    mutate any of the three states, and never trigger another
    recorded refresh call."""

    def test_repeated_reads_after_success_and_after_failure(self):
        core, tmpdir = _make_core()
        try:
            records, restore = _install_normalized_refresh_order_spy()
            try:
                core.generate_language_response(
                    _usable_understanding(core, text="  not dgo,   I mean dog.  "))
                self.assertEqual(len(records), 1)
                conversation_first = core.get_last_conversation_response()
                outcome_first = core.get_last_response_generation_result()
                normalized_first = core.get_last_response_normalized_input()

                for _ in range(5):
                    self.assertIs(core.get_last_conversation_response(), conversation_first)
                    self.assertIs(core.get_last_response_generation_result(), outcome_first)
                    self.assertEqual(core.get_last_response_normalized_input(), normalized_first)
                self.assertEqual(len(records), 1)  # no extra refresh triggered by reads

                _generate_with_injected_late_failure_via_core(
                    core, _unusable_understanding(core))
                self.assertEqual(len(records), 2)
            finally:
                restore()
        finally:
            tmpdir.cleanup()


class TestLegacyObjectsWithoutNormalizedInputRemainSafe(unittest.TestCase):
    """10: legacy conversation-response / outcome objects without
    normalized_input remain safe at this publication boundary - the
    getattr fallback path, exercised alongside the spy."""

    def test_legacy_conversation_response(self):
        core, tmpdir = _make_core()
        try:
            legacy_response = ConversationResponse(
                response_text="hi", status="SUCCESS", language="en", locale="en-US",
                backend_kind="deterministic_fallback", fallback_used=False,
                failure_reason=None, metadata=None, valid=True, validation_issues=(),
                generation_status="SUCCESS", reason=None, generation_backend_kind=None,
                fallback_backend_kind=None, selected_backend_kind=None,
                inference_status=None, error_code=None)
            core.last_conversation_response = legacy_response

            records, restore = _install_normalized_refresh_order_spy()
            try:
                core._refresh_last_response_normalized_input()
            finally:
                restore()

            self.assertEqual(len(records), 1)
            self.assertIsNone(records[0]["normalized_after"])
            self.assertIsNone(core.get_last_response_normalized_input())
        finally:
            tmpdir.cleanup()

    def test_legacy_outcome_object(self):
        core, tmpdir = _make_core()
        try:
            class _BareLegacyOutcome(object):
                generated_text = "hi"

            core.last_response_generation_result = _BareLegacyOutcome()
            self.assertIsNone(
                getattr(core.get_last_response_generation_result(), "normalized_input", None))
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
