"""
Tests for Prompt 607 - `last_response_correction_usable` Stays
Synchronized With the Current `ConversationResponse` Lifecycle, Never
Inferred From the Other Response-Generation State Fields.

Inspection performed by this prompt (core.py):

    - `_refresh_last_response_correction_usable()` (Prompt 580) reads
      ONLY `self.last_conversation_response.correction_application_
      result_usable` (via `getattr(..., False)`); it does not read
      `last_response_generation_result`, `last_response_generation_
      validation`, `last_response_plan`, or any response text.
    - It is called exactly twice in the whole file: immediately after
      `_handle_conversation()`'s "1d" assigns `last_conversation_
      response`, and immediately after `generate_language_response()`
      does the same (Prompt 583 already found and proved this).
    - `reset_context()` (Prompt 581) sets `last_response_correction_
      usable = False` directly and leaves `last_conversation_response`
      itself untouched (Prompt 584 already proved the getter cannot
      read a stale True out of that untouched object afterwards).

Prompts 603/604/605/606 locked in the cross-field relationship among
`last_conversation_response`, `last_response_generation_result`, and
`last_response_generation_validation` at the LanguageIntelligenceCore
level. This prompt adds the fourth field - the public, Core-level
`last_response_correction_usable` - to that same picture, at the Core
boundary, across the six required transitions, including two failure
paths this field's existing regression suite (Prompts 580-584) never
exercised: a successful response followed by a failure, and a failure
followed by successful recovery. The late-stage failure is the existing
Prompt 602 injection (`_inject_outcome_build_failure`), reused unchanged
but driven through `Core.generate_language_response()` instead of
`LanguageIntelligenceCore.generate_response()` directly, so the Core-
level refresh path is the one actually exercised.

No production code is changed here (requirement 12): the existing
implementation already satisfies the contract; this file is regression
coverage for it. No new production state, accessor, cache, abstraction,
fallback behavior, or exception handling is added (requirement 13).

Covers:
    1. correction-aware success -> ordinary success (True -> False)
    2. ordinary success -> correction-aware success (False -> True)
    3. correction-aware success -> failure (True -> False, not stale)
    4. ordinary success -> failure (False -> False)
    5. failure -> correction-aware successful recovery (-> True)
    6. failure -> ordinary successful recovery (-> False)
    7. not independently recomputed from `last_response_generation_
       result`, `last_response_generation_validation`, or
       `last_response_plan` - decoy/contradictory values on those three
       do not change what the getter reports for the current, real
       `last_conversation_response`
    8. repeated `get_last_response_correction_usable()` reads are
       stable and read-only, interleaved with the other getters
    9. `reset_context()` preserves its existing semantics for this
       field (no stale True survives a reset even though `last_
       conversation_response` itself is left unchanged by it)
    10. the public Core-level value and the LanguageIntelligenceCore-
        level ConversationResponse it is refreshed from stay
        consistent, with no second synchronization mechanism - the
        Core's cached `last_conversation_response` is the exact same
        object `language_intelligence.get_last_conversation_response()`
        returns, by `assertIs`, not merely equal

Reuses the Prompt 576 helper (`_make_core`), the Prompt 583 helpers
(`_usable_understanding`, `_unusable_understanding`, `_assert_synced`),
and the Prompt 602 late-failure injection helper
(`_inject_outcome_build_failure`) rather than creating any new
production hook. Real object references are compared with `assertIs` /
`assertIsNot` throughout; no raw `id()` comparisons, per this prompt's
requirement 10.

Run directly:
    python -m unittest tests.test_correction_aware_response_usable_cross_field_lifecycle_prompt607 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_correction_aware_response_decision_prompt576 import _make_core
from tests.test_correction_aware_core_response_lifecycle_prompt583 import (
    _usable_understanding, _unusable_understanding, _assert_synced,
)
from tests.test_correction_aware_response_late_failure_prompt602 import (
    _inject_outcome_build_failure,
)


def _generate_with_injected_late_failure_via_core(core, understanding):
    """Same Prompt 602 late-stage outcome-build failure, installed for
    the duration of a single call, but driven through `Core.
    generate_language_response()` (which itself calls `language_
    intelligence.generate_response()` and then refreshes
    `last_response_correction_usable` from the result) rather than
    calling the LanguageIntelligenceCore directly - so the Core-level
    refresh path this prompt is about is the one actually exercised."""
    restore = _inject_outcome_build_failure()
    try:
        return core.generate_language_response(understanding)
    finally:
        restore()


class TestSixRequiredLifecycleTransitions(unittest.TestCase):
    """1-6: every required transition on the same Core instance, each
    checked for synchronization against the current ConversationResponse
    immediately after it happens."""

    def test_correction_aware_then_ordinary(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())
            _assert_synced(self, core)

            core.generate_language_response(_unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_ordinary_then_correction_aware(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())
            _assert_synced(self, core)

            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_correction_aware_success_then_failure(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())

            _generate_with_injected_late_failure_via_core(
                core, _unusable_understanding(core))
            self.assertIsNone(core.get_last_conversation_response().response_text)
            self.assertFalse(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_ordinary_success_then_failure(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())

            _generate_with_injected_late_failure_via_core(
                core, _unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_failure_then_correction_aware_successful_recovery(self):
        core, tmpdir = _make_core()
        try:
            _generate_with_injected_late_failure_via_core(
                core, _unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())

            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()

    def test_failure_then_ordinary_successful_recovery(self):
        core, tmpdir = _make_core()
        try:
            _generate_with_injected_late_failure_via_core(
                core, _usable_understanding(core))
            # even a would-be-usable call's late failure reports False -
            # no stale True from the outcome-less ConversationResponse.
            self.assertFalse(core.get_last_response_correction_usable())

            core.generate_language_response(_unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestNoStaleTrueSurvivesAFailureThatIsNotUsable(unittest.TestCase):
    """3 (requirement 6, explicit): a correction-aware success's True
    can never leak forward into a subsequent failing call's reported
    usability, even when that failing call's own understanding would
    itself have been correction-aware."""

    def test_previously_true_does_not_leak_into_a_usable_calls_own_failure(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            prev_conversation = core.get_last_conversation_response()
            self.assertTrue(core.get_last_response_correction_usable())
            self.assertTrue(prev_conversation.correction_application_result_usable)

            # This call's own understanding is ALSO correction-aware, so
            # if usability were (incorrectly) inferred from anything
            # other than the fresh ConversationResponse's own outcome-
            # dependent field, a stale/leaked True could appear here.
            _generate_with_injected_late_failure_via_core(
                core, _usable_understanding(core))

            new_conversation = core.get_last_conversation_response()
            self.assertIsNot(new_conversation, prev_conversation)
            self.assertFalse(core.get_last_response_correction_usable())
            self.assertFalse(new_conversation.correction_application_result_usable)
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestNotIndependentlyRecomputedFromUnrelatedFields(unittest.TestCase):
    """7: decoy/contradictory values planted on `last_response_
    generation_result`, `last_response_generation_validation`, and
    `last_response_plan` never change what
    `get_last_response_correction_usable()` reports for the current,
    real `last_conversation_response` - it is refreshed from that one
    field alone, per `_refresh_last_response_correction_usable()`'s
    existing, unchanged implementation."""

    def test_decoys_on_the_other_three_fields_do_not_affect_the_getter(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core)
            core.generate_language_response(understanding)
            self.assertTrue(core.get_last_response_correction_usable())
            real_conversation = core.get_last_conversation_response()

            # Contradictory decoys on the three fields this prompt must
            # verify independence from - none of these three is what
            # `_refresh_last_response_correction_usable()` reads.
            core.last_response_generation_result = None
            lic = core.language_intelligence
            lic.last_response_generation_validation = None
            understanding.response_plan = None
            core.last_language_understanding = understanding

            core._refresh_last_response_correction_usable()

            self.assertTrue(core.get_last_response_correction_usable())
            self.assertIs(core.get_last_conversation_response(), real_conversation)
        finally:
            tmpdir.cleanup()

    def test_decoy_response_text_does_not_affect_the_getter(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())
            real_conversation = core.get_last_conversation_response()

            core.last_language_response = None

            core._refresh_last_response_correction_usable()

            self.assertFalse(core.get_last_response_correction_usable())
            self.assertIs(core.get_last_conversation_response(), real_conversation)
        finally:
            tmpdir.cleanup()


class TestRepeatedInterleavedReadsAreReadOnly(unittest.TestCase):
    """8: repeated reads of `get_last_response_correction_usable()`,
    interleaved with the other public getters, are stable and never
    mutate any field or the relationship between them."""

    def test_interleaved_reads_stable_after_correction_aware_success(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            conversation_first = core.get_last_conversation_response()
            usable_first = core.get_last_response_correction_usable()
            self.assertTrue(usable_first)

            for _ in range(5):
                self.assertIs(core.get_last_conversation_response(), conversation_first)
                self.assertEqual(core.get_last_response_correction_usable(), usable_first)
                self.assertIs(
                    core.language_intelligence.get_last_conversation_response(),
                    conversation_first)

            self.assertIs(core.get_last_conversation_response(), conversation_first)
            self.assertEqual(core.get_last_response_correction_usable(), usable_first)
        finally:
            tmpdir.cleanup()

    def test_interleaved_reads_stable_after_injected_late_failure(self):
        core, tmpdir = _make_core()
        try:
            _generate_with_injected_late_failure_via_core(
                core, _usable_understanding(core))
            conversation_first = core.get_last_conversation_response()
            usable_first = core.get_last_response_correction_usable()
            self.assertFalse(usable_first)

            for _ in range(5):
                self.assertIs(core.get_last_conversation_response(), conversation_first)
                self.assertFalse(core.get_last_response_correction_usable())

            self.assertIs(core.get_last_conversation_response(), conversation_first)
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


class TestResetContextPreservesExistingSemantics(unittest.TestCase):
    """9: reset_context() (Prompt 581/584) keeps its existing behavior
    for this field across the fuller lifecycle this prompt exercises,
    including immediately after a late-stage failure."""

    def test_reset_after_correction_aware_success_leaves_no_stale_true(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            cached_conversation = core.get_last_conversation_response()
            self.assertTrue(core.get_last_response_correction_usable())

            core.reset_context()

            # last_conversation_response is deliberately untouched by
            # reset (Prompt 581) - still the same, still-True object...
            self.assertIs(core.get_last_conversation_response(), cached_conversation)
            self.assertTrue(cached_conversation.correction_application_result_usable)
            # ...yet the getter itself must not leak that stale True.
            self.assertFalse(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()

    def test_reset_after_injected_late_failure_stays_false(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            _generate_with_injected_late_failure_via_core(
                core, _unusable_understanding(core))
            self.assertFalse(core.get_last_response_correction_usable())

            core.reset_context()
            self.assertFalse(core.get_last_response_correction_usable())

            core.generate_language_response(_usable_understanding(core))
            self.assertTrue(core.get_last_response_correction_usable())
            _assert_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestCoreAndLanguageIntelligenceCoreStayConsistent(unittest.TestCase):
    """10: the public Core-level value and the LanguageIntelligenceCore-
    level ConversationResponse it is refreshed from stay consistent
    with no new synchronization mechanism - Core's cached object is the
    exact same object the LanguageIntelligenceCore itself reports."""

    def test_same_object_identity_across_the_boundary_success(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(_usable_understanding(core))
            self.assertIs(
                core.get_last_conversation_response(),
                core.language_intelligence.get_last_conversation_response())
            self.assertEqual(
                core.get_last_response_correction_usable(),
                core.language_intelligence.get_last_conversation_response()
                    .correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_same_object_identity_across_the_boundary_failure(self):
        core, tmpdir = _make_core()
        try:
            _generate_with_injected_late_failure_via_core(
                core, _usable_understanding(core))
            self.assertIs(
                core.get_last_conversation_response(),
                core.language_intelligence.get_last_conversation_response())
            self.assertFalse(core.get_last_response_correction_usable())
            self.assertFalse(
                core.language_intelligence.get_last_conversation_response()
                    .correction_application_result_usable)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
