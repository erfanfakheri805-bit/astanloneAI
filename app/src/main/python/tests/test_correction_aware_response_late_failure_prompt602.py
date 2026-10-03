"""
Tests for Prompt 602 - The Cleared-State Contract Holds for a Failure
That Occurs AFTER the Backend Call, Before Final Response-State
Publication.

Prompts 598-601 covered the reset boundary and an uncaught EXCEPTION
from the backend itself (before or at the model call). This prompt
covers a different failure point in the same `generate_response()`
lifecycle: the backend already returned a genuine
`ResponseGenerationResult` successfully, but building the PUBLIC
representation of it afterwards fails - specifically,
`build_response_generation_outcome()` (response_generation_outcome.py,
imported into language_intelligence_core.py and called from
`_build_outcome()`). `_build_outcome()` never lets that propagate (both
its attempts are wrapped in `try/except Exception: pass`), so a failure
there does not raise - it simply makes `_build_outcome()` return None,
which `generate_response()` then assigns directly to
`last_response_generation_result`. This is an EXISTING, already-
reachable failure point; no production hook was added to create it -
this file only exercises it.

The same module-level monkeypatch pattern already used by Prompt 596
(`test_correction_aware_response_state_read_only_prompt596.py`, which
already patches `lic_module.build_response_generation_outcome` to COUNT
calls) is reused here, but to RAISE instead - a strictly smaller change
to that existing pattern, not a new hook.

Because `_build_outcome()`'s two attempts are the ONLY place this
prompt injects a failure, `_conversation_response()` still receives a
genuine `response` object and runs normally; it is passed `outcome=None`
and produces a legitimate (though outcome-less) `ConversationResponse`
for THIS call - never the predecessor's. This is the documented,
already-existing behavior of `_conversation_response()` (it only
returns None when `response` itself is not a `ResponseGenerationResult`,
never merely because the outcome is None), so this file locks that
distinction in explicitly instead of assuming it.

No production code is changed here, per this prompt's requirements 9/10.

Covers:
    1. ordinary successful predecessor -> injected late-stage failure:
       `last_response_generation_result` becomes None (the outcome
       failed to build), `last_conversation_response` is replaced by a
       genuinely new object for the failing call - never the
       predecessor's - and correction-aware usability does not leak
    2. correction-aware successful predecessor -> injected late-stage
       failure: the same clearing, with explicit confirmation the
       predecessor's usable-correction identity does not survive onto
       the new (outcome-less) conversation response
    3. repeated getter reads after the injected failure are stable and
       do not mutate the unrelated lifecycle fields
       (`last_learned_response_decision`, `last_backend_selection`,
       `last_response_plan`)
    4. injected late-stage failure -> successful recovery: the next
       successful `generate_response()` call produces fresh response-
       state objects that are neither the original predecessor's nor
       the degraded, outcome-less objects from the failed call

Reuses the Prompt 576 helper (`_make_core`), the Prompt 592 helpers
(`_generate_correction_aware`, `_generate_ordinary`), and the Prompt 596
monkeypatch target (`lic_module.build_response_generation_outcome`).
Real object references are compared with `assertIs` / `assertIsNot`
throughout; no raw `id()` comparisons, per this prompt's requirement 12.

Run directly:
    python -m unittest tests.test_correction_aware_response_late_failure_prompt602 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language_intelligence.language_intelligence_core as lic_module

from tests.test_correction_aware_response_decision_prompt576 import _make_core
from tests.test_correction_aware_response_state_consistency_prompt592 import (
    _generate_correction_aware, _generate_ordinary,
)


def _inject_outcome_build_failure(message="deliberate late-stage outcome-build failure"):
    """Monkeypatch the module-level `build_response_generation_outcome`
    (the same target Prompt 596 already patches, there to count calls)
    so it raises on every call. `_build_outcome()`'s own existing
    try/except swallows this - it never propagates - so the ONLY
    observable effect is that `_build_outcome()` returns None for
    every call made while this is installed, exactly as it already does
    for any other outcome-building failure. Returns a restore
    callable."""
    original = lic_module.build_response_generation_outcome

    def _raising(*args, **kwargs):
        raise RuntimeError(message)

    lic_module.build_response_generation_outcome = _raising

    def _restore():
        lic_module.build_response_generation_outcome = original

    return _restore


def _generate_with_injected_late_failure(core, text="tell me something requiring the backend"):
    """Run one `generate_response()` call for `text` with the late-stage
    outcome-build failure installed for the duration of that single
    call only."""
    lic = core.language_intelligence
    understanding = core.understand_language(text)
    restore = _inject_outcome_build_failure()
    try:
        return lic.generate_response(understanding, context=core.context)
    finally:
        restore()


class TestLateStageFailureAfterOrdinarySuccess(unittest.TestCase):
    """1: an ordinary successful predecessor, then an injected late-
    stage failure - the outcome is cleared, the conversation response is
    a fresh object for the failing call, and no usability leaks."""

    def test_outcome_cleared_and_conversation_response_is_fresh(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_ordinary(core, text="tell me about xyzzy")
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            self.assertIsNotNone(prev_conv)
            self.assertIsNotNone(prev_outcome)

            result = _generate_with_injected_late_failure(core)
            self.assertIsNotNone(result)  # the backend itself succeeded

            new_outcome = lic.get_last_response_generation_result()
            new_conv = lic.get_last_conversation_response()

            # the outcome failed to build: cleared, not stale
            self.assertIsNone(new_outcome)
            self.assertIsNot(new_outcome, prev_outcome)

            # the conversation response is a genuinely new object for
            # this call - never the predecessor's stale one
            self.assertIsNotNone(new_conv)
            self.assertIsNot(new_conv, prev_conv)
            self.assertFalse(new_conv.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestLateStageFailureAfterCorrectionAwareSuccess(unittest.TestCase):
    """2: the same injected failure starting from a correction-aware
    successful predecessor - its usable-correction identity must not
    survive onto the new, outcome-less conversation response."""

    def test_correction_aware_usability_does_not_leak_into_failure(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_correction_aware(core)
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            self.assertTrue(prev_conv.correction_application_result_usable)
            self.assertTrue(prev_outcome.correction_application_result_usable)

            _generate_with_injected_late_failure(core)

            new_outcome = lic.get_last_response_generation_result()
            new_conv = lic.get_last_conversation_response()

            self.assertIsNone(new_outcome)
            self.assertIsNot(new_outcome, prev_outcome)
            self.assertIsNotNone(new_conv)
            self.assertIsNot(new_conv, prev_conv)
            self.assertFalse(new_conv.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestRepeatedReadsStableAfterLateStageFailure(unittest.TestCase):
    """3: repeated public getter reads after the injected failure are
    stable and never mutate the unrelated lifecycle fields."""

    def _assert_reads_are_inert_and_stable(self, lic):
        outcome_before = lic.get_last_response_generation_result()
        conv_before = lic.get_last_conversation_response()
        decision_before = lic.last_learned_response_decision
        selection_before = lic.last_backend_selection
        plan_before = lic.last_response_plan

        for _ in range(10):
            self.assertIs(lic.get_last_response_generation_result(), outcome_before)
            self.assertIs(lic.get_last_conversation_response(), conv_before)

        self.assertIs(lic.last_learned_response_decision, decision_before)
        self.assertIs(lic.last_backend_selection, selection_before)
        self.assertIs(lic.last_response_plan, plan_before)

    def test_repeated_reads_stable_after_ordinary_predecessor(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            _generate_with_injected_late_failure(core)
            self._assert_reads_are_inert_and_stable(lic)
        finally:
            tmpdir.cleanup()

    def test_repeated_reads_stable_after_correction_aware_predecessor(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            _generate_with_injected_late_failure(core)
            self._assert_reads_are_inert_and_stable(lic)
        finally:
            tmpdir.cleanup()


class TestSuccessfulRecoveryAfterLateStageFailure(unittest.TestCase):
    """4: after the injected late-stage failure, a subsequent successful
    call rebuilds fresh state - never the original predecessor's, and
    never the degraded outcome-less objects from the failed call."""

    def test_recovery_creates_fresh_state_only(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_correction_aware(core)
            original_prev_conv = lic.get_last_conversation_response()
            original_prev_outcome = lic.get_last_response_generation_result()

            _generate_with_injected_late_failure(core)
            failed_conv = lic.get_last_conversation_response()
            failed_outcome = lic.get_last_response_generation_result()
            self.assertIsNone(failed_outcome)
            self.assertIsNotNone(failed_conv)

            _generate_ordinary(core, text="tell me about plugh")
            new_conv = lic.get_last_conversation_response()
            new_outcome = lic.get_last_response_generation_result()

            self.assertIsNotNone(new_conv)
            self.assertIsNotNone(new_outcome)
            self.assertIsNot(new_conv, original_prev_conv)
            self.assertIsNot(new_conv, failed_conv)
            self.assertIsNot(new_outcome, original_prev_outcome)
            self.assertIsNot(new_outcome, failed_outcome)
            self.assertFalse(new_conv.correction_application_result_usable)
            self.assertFalse(new_outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
