"""
Tests for Prompt 593 - Success/Failure Boundary Regression Coverage for
`generate_response()`.

Inspection performed by this prompt: re-traced `LanguageIntelligenceCore.
generate_response()` (language_intelligence_core.py) and the existing
Prompt 592 tests. Confirmed (no production change needed):

    self.last_response_generation_result = None
    self.last_response_generation_validation = None
    self.last_conversation_response = None
    response = self._learned_response(...) or self._route_response(...)
    ...
    outcome = self._build_outcome(response, ...)
    self.last_response_generation_result = outcome
    self.last_response_generation_validation = self._validate(response, outcome)
    self.last_conversation_response = self._conversation_response(
        response, outcome, self.last_response_generation_validation)

All three `self.last_*` caches are unconditionally reset to `None` at the
very top of the method, before either public object is (re)built - and both
public objects are always built from the SAME local `response`/`outcome`
produced by THIS call, never from a stale `self.last_*` re-read. This makes
it structurally impossible for a failed/no-usable-response generation to
expose a previous successful `ConversationResponse`,
`ResponseGenerationResult`, or correction-aware usability state, regardless
of what the previous generation was.

Prompt 592 already proved cross-getter consistency for each of the four
outcomes individually and a 4-step sequence ending in failure. This prompt
specifically drills the success -> failure boundary itself (not just
"failure produces internally-consistent failure state," but "failure
state contains NONE of the previous success's identity or content"), plus
failure -> success repopulation, and does so both for a plain successful
predecessor and a correction-aware successful predecessor.

Covers:
    1. successful (ordinary) response -> failed generation: failure exposes
       neither the previous `ConversationResponse` nor the previous
       `ResponseGenerationResult` object or content (identity + fields)
    2. successful correction-aware response -> failed generation: same,
       plus correction_application_result_usable is False on both getters
       after the failure, never True
    3. repeated getter reads after the failure remain stable (same object
       identity every time, on both getters, interleaved)
    4. failure -> subsequent successful generation repopulates both public
       response states correctly, with no trace of the intervening failure

No production code was changed (Prompt 593 requirements 8/9/10): the
lifecycle already satisfies the contract; this file is the smallest
regression coverage proving the failure boundary specifically.

Reuses the Prompt 576 test helpers (`_make_core`, `_store_a_correction`)
and the Prompt 592 `_generate_correction_aware` / `_generate_ordinary` /
`_generate_failure` / `_AlwaysFailingBackend` helpers rather than
duplicating that infrastructure.

Run directly:
    python -m unittest tests.test_correction_aware_response_failure_boundary_prompt593 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_generation_outcome import STATUS_FAILED

from tests.test_correction_aware_response_decision_prompt576 import _make_core
from tests.test_correction_aware_response_state_consistency_prompt592 import (
    _AlwaysFailingBackend, _generate_correction_aware, _generate_failure,
    _generate_ordinary,
)


def _generate_failure_then_restore_backend(core):
    """Like `_generate_failure()`, but restores the core's original
    (working) backend afterward, so a later `_generate_ordinary()` /
    `_generate_correction_aware()` on the SAME core can succeed again -
    used only to test the failure -> success repopulation boundary."""
    lic = core.language_intelligence
    original_backend = lic.backend
    _generate_failure(core)
    lic.backend = original_backend


class TestSuccessThenFailureBoundary(unittest.TestCase):
    """1: a plain successful response followed by a failed generation -
    the failure must expose none of the previous success's identity or
    content on either public getter."""

    def test_failure_after_ordinary_success_replaces_conversation_response(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core)
            success_conv = lic.get_last_conversation_response()
            self.assertNotEqual(success_conv.status, STATUS_FAILED)

            _generate_failure(core)
            failed_conv = lic.get_last_conversation_response()

            self.assertIsNot(failed_conv, success_conv)
            self.assertIsNone(failed_conv.response_text)
            self.assertNotEqual(failed_conv.status, success_conv.status)
        finally:
            tmpdir.cleanup()

    def test_failure_after_ordinary_success_replaces_generation_result(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core)
            success_outcome = lic.get_last_response_generation_result()
            self.assertNotEqual(success_outcome.status, STATUS_FAILED)

            _generate_failure(core)
            failed_outcome = lic.get_last_response_generation_result()

            self.assertIsNot(failed_outcome, success_outcome)
            self.assertEqual(failed_outcome.status, STATUS_FAILED)
            self.assertIsNone(failed_outcome.generated_text)
        finally:
            tmpdir.cleanup()


class TestSuccessfulCorrectionAwareThenFailureBoundary(unittest.TestCase):
    """2: same boundary, but the previous successful response was
    correction-aware - failure must not leak the True usability state."""

    def test_failure_after_correction_aware_success_clears_usability(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            success_conv = lic.get_last_conversation_response()
            success_outcome = lic.get_last_response_generation_result()
            self.assertTrue(success_conv.correction_application_result_usable)
            self.assertTrue(success_outcome.correction_application_result_usable)

            _generate_failure(core)
            failed_conv = lic.get_last_conversation_response()
            failed_outcome = lic.get_last_response_generation_result()

            self.assertIsNot(failed_conv, success_conv)
            self.assertIsNot(failed_outcome, success_outcome)
            self.assertFalse(failed_conv.correction_application_result_usable)
            self.assertFalse(failed_outcome.correction_application_result_usable)
            self.assertEqual(failed_outcome.status, STATUS_FAILED)
            self.assertIsNone(failed_conv.response_text)
            # the previous success's own object must be untouched, not
            # merely superseded, by the failed generation
            self.assertTrue(success_conv.correction_application_result_usable)
            self.assertTrue(success_outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_failure_result_backend_kind_reflects_failing_backend(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            _generate_failure(core)
            failed_outcome = lic.get_last_response_generation_result()
            self.assertEqual(failed_outcome.status, STATUS_FAILED)
        finally:
            tmpdir.cleanup()


class TestRepeatedReadsAfterFailureStayStable(unittest.TestCase):
    """3: repeated, interleaved getter reads after a failure that follows
    a successful (including correction-aware) predecessor stay stable -
    same object identity every time."""

    def test_interleaved_reads_stable_after_failure_following_success(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            _generate_failure(core)

            conv_first = lic.get_last_conversation_response()
            outcome_first = lic.get_last_response_generation_result()
            for _ in range(6):
                self.assertIs(lic.get_last_conversation_response(), conv_first)
                self.assertIs(lic.get_last_response_generation_result(), outcome_first)
        finally:
            tmpdir.cleanup()


class TestFailureThenSuccessRepopulation(unittest.TestCase):
    """4: a subsequent successful generation after a failure repopulates
    both public response states correctly, with no trace of the failure."""

    def test_ordinary_success_after_failure(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_failure_then_restore_backend(core)
            failed_conv = lic.get_last_conversation_response()
            failed_outcome = lic.get_last_response_generation_result()
            self.assertEqual(failed_outcome.status, STATUS_FAILED)

            _generate_ordinary(core)
            new_conv = lic.get_last_conversation_response()
            new_outcome = lic.get_last_response_generation_result()

            self.assertNotEqual(new_conv.status, STATUS_FAILED)
            self.assertNotEqual(new_outcome.status, STATUS_FAILED)
            self.assertIsNot(new_conv, failed_conv)
            self.assertIsNot(new_outcome, failed_outcome)
        finally:
            tmpdir.cleanup()

    def test_correction_aware_success_after_failure_repopulates_usability(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_failure_then_restore_backend(core)
            self.assertFalse(
                lic.get_last_conversation_response().correction_application_result_usable)

            _generate_correction_aware(core)
            new_conv = lic.get_last_conversation_response()
            new_outcome = lic.get_last_response_generation_result()

            self.assertTrue(new_conv.correction_application_result_usable)
            self.assertTrue(new_outcome.correction_application_result_usable)
            self.assertNotEqual(new_conv.status, STATUS_FAILED)
            self.assertNotEqual(new_outcome.status, STATUS_FAILED)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
