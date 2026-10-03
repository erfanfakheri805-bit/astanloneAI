"""
Tests for Prompt 594 - Full Recovery Sequence Regression Coverage:
SUCCESS -> FAILURE -> SUCCESS for `generate_response()`.

Inspection performed by this prompt: re-traced `LanguageIntelligenceCore.
generate_response()` (language_intelligence_core.py) and the Prompt 593
tests/inspection notes. Confirmed (no production change needed): every
call unconditionally resets `self.last_response_generation_result`,
`self.last_response_generation_validation`, and
`self.last_conversation_response` to `None` at the top, then rebuilds all
three from that SAME call's own local `response`/`outcome` - never from a
stale `self.last_*` re-read. Prompt 593 proved this holds at the
success -> failure boundary specifically (both plain and correction-aware
predecessors) and at failure -> success repopulation. This prompt is the
smallest additional regression coverage proving the full three-step
recovery sequence end-to-end on a single core instance, since neither
Prompt 592's 4-step sequence nor Prompt 593's two-step boundary tests
exercised "the SAME core recovers cleanly and the ORIGINAL first success
is never restored or reused" as one continuous scenario.

Covers:
    1. SUCCESS -> FAILURE -> SUCCESS with a plain ordinary first success:
       - after the failure, both getters expose cleared/current failure
         state, with no trace of the first success's object or content,
         and correction-aware usability does not leak
       - after the final success, both getters expose only the final
         generation's state; the first success is not restored/reused;
         repeated getter reads stay stable
    2. the same sequence with a correction-aware first success and a
       different (ordinary) final success: the True usability from step 1
       must not survive the failure, and must not reappear in the final
       ordinary success either
    3. the same sequence with a correction-aware first success and a
       correction-aware final success: the final success's own usability
       is real (independently re-derived), not a reappearance of the
       first success's cached True

No production code was changed (Prompt 594 requirements 6/7/8): the
lifecycle already satisfies the contract; this file only adds regression
coverage for the full recovery sequence.

Reuses the Prompt 576 test helper (`_make_core`) and the Prompt 592/593
helpers (`_generate_correction_aware`, `_generate_ordinary`,
`_generate_failure`, `_generate_failure_then_restore_backend`) rather than
duplicating that infrastructure.

Run directly:
    python -m unittest tests.test_correction_aware_response_recovery_prompt594 -v
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
    _generate_correction_aware, _generate_failure, _generate_ordinary,
)


def _restore_working_backend(core, original_backend):
    """Put the core's ORIGINAL (pre-failure) backend back in place, so a
    later `_generate_ordinary()` / `_generate_correction_aware()` on the
    SAME core can succeed again - used only to test the
    success -> failure -> success recovery boundary."""
    core.language_intelligence.backend = original_backend


def _assert_failure_state_clean(test, lic, prior_conv, prior_outcome):
    """After a failure: both getters must show cleared/current failure
    state, with no trace - by identity or content - of the prior
    generation, and usability must not leak."""
    failed_conv = lic.get_last_conversation_response()
    failed_outcome = lic.get_last_response_generation_result()

    test.assertIsNot(failed_conv, prior_conv)
    test.assertIsNot(failed_outcome, prior_outcome)
    test.assertEqual(failed_outcome.status, STATUS_FAILED)
    test.assertIsNone(failed_conv.response_text)
    test.assertIsNone(failed_outcome.generated_text)
    test.assertFalse(failed_conv.correction_application_result_usable)
    test.assertFalse(failed_outcome.correction_application_result_usable)
    # the prior generation's own objects remain untouched, not overwritten
    test.assertNotEqual(prior_outcome.status, STATUS_FAILED)
    return failed_conv, failed_outcome


class TestOrdinarySuccessFailureSuccessRecovery(unittest.TestCase):
    """1: plain ordinary first success, then failure, then a new
    ordinary success."""

    def test_full_recovery_sequence(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            original_backend = lic.backend
            _generate_ordinary(core, text="tell me about xyzzy")
            first_conv = lic.get_last_conversation_response()
            first_outcome = lic.get_last_response_generation_result()
            self.assertNotEqual(first_outcome.status, STATUS_FAILED)

            _generate_failure(core)
            failed_conv, failed_outcome = _assert_failure_state_clean(
                self, lic, first_conv, first_outcome)

            # final success, on the restored working backend
            _restore_working_backend(core, original_backend)
            _generate_ordinary(core, text="tell me about plugh")
            final_conv = lic.get_last_conversation_response()
            final_outcome = lic.get_last_response_generation_result()

            self.assertNotEqual(final_outcome.status, STATUS_FAILED)
            # neither the first success nor the intervening failure's
            # objects are restored or reused
            self.assertIsNot(final_conv, first_conv)
            self.assertIsNot(final_outcome, first_outcome)
            self.assertIsNot(final_conv, failed_conv)
            self.assertIsNot(final_outcome, failed_outcome)

            # repeated reads stay stable
            for _ in range(5):
                self.assertIs(lic.get_last_conversation_response(), final_conv)
                self.assertIs(lic.get_last_response_generation_result(), final_outcome)
        finally:
            tmpdir.cleanup()


class TestCorrectionAwareSuccessFailureOrdinarySuccessRecovery(unittest.TestCase):
    """2: correction-aware first success, then failure, then a
    DIFFERENT (ordinary) final success - the first success's True
    usability must not leak into either the failure or the final
    ordinary success."""

    def test_full_recovery_sequence(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            original_backend = lic.backend
            _generate_correction_aware(core)
            first_conv = lic.get_last_conversation_response()
            first_outcome = lic.get_last_response_generation_result()
            self.assertTrue(first_conv.correction_application_result_usable)
            self.assertTrue(first_outcome.correction_application_result_usable)

            _generate_failure(core)
            failed_conv, failed_outcome = _assert_failure_state_clean(
                self, lic, first_conv, first_outcome)

            _restore_working_backend(core, original_backend)
            _generate_ordinary(core, text="tell me about plugh")
            final_conv = lic.get_last_conversation_response()
            final_outcome = lic.get_last_response_generation_result()

            self.assertNotEqual(final_outcome.status, STATUS_FAILED)
            self.assertFalse(final_conv.correction_application_result_usable)
            self.assertFalse(final_outcome.correction_application_result_usable)
            self.assertIsNot(final_conv, first_conv)
            self.assertIsNot(final_outcome, first_outcome)
            self.assertIsNot(final_conv, failed_conv)
            self.assertIsNot(final_outcome, failed_outcome)

            # the first success's own objects remain untouched
            self.assertTrue(first_conv.correction_application_result_usable)
            self.assertTrue(first_outcome.correction_application_result_usable)

            for _ in range(5):
                self.assertIs(lic.get_last_conversation_response(), final_conv)
                self.assertIs(lic.get_last_response_generation_result(), final_outcome)
        finally:
            tmpdir.cleanup()


class TestCorrectionAwareSuccessFailureCorrectionAwareSuccessRecovery(unittest.TestCase):
    """3: correction-aware first success, then failure, then a NEW
    correction-aware final success - the final success's True usability
    must be independently re-derived, not a reappearance of the first
    success's cached object/value."""

    def test_full_recovery_sequence(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            original_backend = lic.backend
            _generate_correction_aware(core)
            first_conv = lic.get_last_conversation_response()
            first_outcome = lic.get_last_response_generation_result()
            self.assertTrue(first_conv.correction_application_result_usable)

            _generate_failure(core)
            failed_conv, failed_outcome = _assert_failure_state_clean(
                self, lic, first_conv, first_outcome)

            _restore_working_backend(core, original_backend)
            _generate_correction_aware(core)
            final_conv = lic.get_last_conversation_response()
            final_outcome = lic.get_last_response_generation_result()

            self.assertNotEqual(final_outcome.status, STATUS_FAILED)
            self.assertTrue(final_conv.correction_application_result_usable)
            self.assertTrue(final_outcome.correction_application_result_usable)
            self.assertIsNot(final_conv, first_conv)
            self.assertIsNot(final_outcome, first_outcome)
            self.assertIsNot(final_conv, failed_conv)
            self.assertIsNot(final_outcome, failed_outcome)

            for _ in range(5):
                self.assertIs(lic.get_last_conversation_response(), final_conv)
                self.assertIs(lic.get_last_response_generation_result(), final_outcome)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
