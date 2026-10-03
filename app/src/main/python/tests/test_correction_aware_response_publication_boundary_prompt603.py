"""
Tests for Prompt 603 - The Publication Boundary Between the Current
Generation's `ResponseGenerationOutcome` and the Public
`ConversationResponse`.

Prompt 602 proved a late (post-backend) failure cannot leak a stale
predecessor's response state. This prompt traces the other direction of
the same boundary: for every SUCCESSFUL `generate_response()` call, the
published `last_conversation_response`
(`get_last_conversation_response()`) must correspond to THAT SAME
call's own `last_response_generation_result`
(`get_last_response_generation_result()`) - never a predecessor's - and
for every failure boundary, the previous public `ConversationResponse`
must not be retained.

The traced path (language_intelligence_core.py, `generate_response()`):
    outcome = self._build_outcome(response, ...)
    self.last_response_generation_result = outcome
    self.last_response_generation_validation = self._validate(response, outcome)
    self.last_conversation_response = self._conversation_response(
        response, outcome, self.last_response_generation_validation)
`_conversation_response()` is built from THAT SAME LOCAL `outcome`
variable (never from `self.last_response_generation_result` re-read, and
never from any prior call's outcome), so the published
`ConversationResponse` is structurally tied to the current call's own
outcome by construction. This file locks that correspondence in with
direct field-level assertions (`response_text` == `generated_text`,
`status`, `backend_kind`, `correction_application_result_usable`) for
every required transition, on top of plain object-identity checks.

No production code is changed - this file only observes and locks in
the existing publication path, per this prompt's requirements 8/9.

Covers:
    1. ordinary success -> ordinary success: the second call's
       conversation response corresponds field-for-field to the SECOND
       call's own outcome, and is not the first call's object
    2. correction-aware success -> ordinary success: same correspondence
       check, with the second call's usability explicitly False despite
       the predecessor's True
    3. ordinary success -> correction-aware success: same correspondence
       check, with the second call's usability explicitly True
    4. successful response -> injected late failure (Prompt 602's
       injection): the previous public `ConversationResponse` is not
       retained (a fresh object is published for the failing call, per
       Prompt 602's own finding that `_conversation_response()` never
       returns None merely because the outcome is None)
    5. late failure -> successful recovery: the recovery call's
       conversation response corresponds to the recovery call's own
       outcome, and is neither the original predecessor's object nor
       the failed call's object
    6. repeated public getter reads after a successful publication
       return the exact same object every time (read-only)

Reuses the Prompt 576 helper (`_make_core`), the Prompt 592 helpers
(`_generate_correction_aware`, `_generate_ordinary`,
`_assert_same_lifecycle`), and the Prompt 602 late-failure injection
helper (`_generate_with_injected_late_failure`) rather than creating any
new production hook. Real object references are compared with
`assertIs` / `assertIsNot` throughout; no raw `id()` comparisons, per
this prompt's requirement 6.

Run directly:
    python -m unittest tests.test_correction_aware_response_publication_boundary_prompt603 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_correction_aware_response_decision_prompt576 import _make_core
from tests.test_correction_aware_response_state_consistency_prompt592 import (
    _assert_same_lifecycle, _generate_correction_aware, _generate_ordinary,
)
from tests.test_correction_aware_response_late_failure_prompt602 import (
    _generate_with_injected_late_failure,
)


class TestPublicationCorrespondsToCurrentOutcomeAcrossTransitions(unittest.TestCase):
    """1, 2, 3: for every successful generation, the published
    conversation response corresponds field-for-field to THAT SAME
    call's own outcome, and is never the predecessor's object."""

    def test_ordinary_then_ordinary(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            step1_conv, step1_outcome = _assert_same_lifecycle(self, lic)

            _generate_ordinary(core, text="tell me about plugh")
            step2_conv, step2_outcome = _assert_same_lifecycle(self, lic)
            self.assertFalse(step2_conv.correction_application_result_usable)
            self.assertIsNot(step2_conv, step1_conv)
            self.assertIsNot(step2_outcome, step1_outcome)
        finally:
            tmpdir.cleanup()

    def test_correction_aware_then_ordinary(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            step1_conv, step1_outcome = _assert_same_lifecycle(self, lic)
            self.assertTrue(step1_conv.correction_application_result_usable)

            _generate_ordinary(core, text="tell me about xyzzy")
            step2_conv, step2_outcome = _assert_same_lifecycle(self, lic)
            self.assertFalse(step2_conv.correction_application_result_usable)
            self.assertFalse(step2_outcome.correction_application_result_usable)
            self.assertIsNot(step2_conv, step1_conv)
            self.assertIsNot(step2_outcome, step1_outcome)
        finally:
            tmpdir.cleanup()

    def test_ordinary_then_correction_aware(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            step1_conv, step1_outcome = _assert_same_lifecycle(self, lic)
            self.assertFalse(step1_conv.correction_application_result_usable)

            _generate_correction_aware(core)
            step2_conv, step2_outcome = _assert_same_lifecycle(self, lic)
            self.assertTrue(step2_conv.correction_application_result_usable)
            self.assertTrue(step2_outcome.correction_application_result_usable)
            self.assertIsNot(step2_conv, step1_conv)
            self.assertIsNot(step2_outcome, step1_outcome)
        finally:
            tmpdir.cleanup()


class TestPreviousPublicationNotRetainedAcrossLateFailure(unittest.TestCase):
    """4: after a successful response, an injected late failure must not
    retain the previous public `ConversationResponse`."""

    def test_successful_response_then_injected_late_failure(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            prev_conv, prev_outcome = _assert_same_lifecycle(self, lic)
            self.assertTrue(prev_conv.correction_application_result_usable)

            _generate_with_injected_late_failure(core)

            self.assertIsNone(lic.get_last_response_generation_result())
            failed_conv = lic.get_last_conversation_response()
            self.assertIsNotNone(failed_conv)
            self.assertIsNot(failed_conv, prev_conv)
            self.assertFalse(failed_conv.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestRecoveryPublicationAfterLateFailure(unittest.TestCase):
    """5: after an injected late failure, the recovery call's published
    conversation response corresponds to its own outcome and is neither
    the original predecessor's nor the failed call's object."""

    def test_late_failure_then_successful_recovery(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            original_conv = lic.get_last_conversation_response()
            original_outcome = lic.get_last_response_generation_result()

            _generate_with_injected_late_failure(core)
            failed_conv = lic.get_last_conversation_response()
            self.assertIsNone(lic.get_last_response_generation_result())

            _generate_ordinary(core, text="tell me about plugh")
            new_conv, new_outcome = _assert_same_lifecycle(self, lic)
            self.assertFalse(new_conv.correction_application_result_usable)
            self.assertIsNot(new_conv, original_conv)
            self.assertIsNot(new_conv, failed_conv)
            self.assertIsNot(new_outcome, original_outcome)
        finally:
            tmpdir.cleanup()


class TestRepeatedReadsAreReadOnlyAfterPublication(unittest.TestCase):
    """6: repeated public getter reads after a successful publication
    return the exact same object every time - reading never republishes
    or mutates the boundary."""

    def test_reads_stable_after_ordinary_success(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            conv_first = lic.get_last_conversation_response()
            outcome_first = lic.get_last_response_generation_result()
            for _ in range(10):
                self.assertIs(lic.get_last_conversation_response(), conv_first)
                self.assertIs(lic.get_last_response_generation_result(), outcome_first)
        finally:
            tmpdir.cleanup()

    def test_reads_stable_after_correction_aware_success(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            conv_first = lic.get_last_conversation_response()
            outcome_first = lic.get_last_response_generation_result()
            for _ in range(10):
                self.assertIs(lic.get_last_conversation_response(), conv_first)
                self.assertIs(lic.get_last_response_generation_result(), outcome_first)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
