"""
Tests for Prompt 604 - The Publication Boundary for
`last_response_generation_result`, Mirroring Prompt 603's
`ConversationResponse` Boundary.

Prompt 603 proved that for every successful `generate_response()` call,
`last_conversation_response` (`get_last_conversation_response()`)
corresponds to THAT SAME call's own outcome and is never a
predecessor's object, and that a late failure never retains the
previous public `ConversationResponse`. This prompt traces the same
contract for the other half of the pair -
`last_response_generation_result` (`get_last_response_generation_result()`)
itself - across the same set of transitions.

The traced path (language_intelligence_core.py, `generate_response()`):
    self.last_response_generation_result = None          # cleared FIRST
    self.last_response_generation_validation = None
    self.last_conversation_response = None
    response = self._learned_response(understanding, context) or \
        self._route_response(...)
    outcome = self._build_outcome(response, ...)          # fresh, local
    self.last_response_generation_result = outcome        # published
    self.last_response_generation_validation = self._validate(response, outcome)
    self.last_conversation_response = self._conversation_response(
        response, outcome, self.last_response_generation_validation)
Because `self.last_response_generation_result` is unconditionally reset
to None at the top of every call, BEFORE the new `outcome` is built, and
is only ever assigned that call's own freshly-built local `outcome`
afterward, it is structurally incapable of retaining a predecessor's
object - on success OR on a late (post-backend) failure, where
`_build_outcome()`'s own existing try/except (Prompt 602) makes it
return None instead of the previous outcome.

No production code is changed - this file only observes and locks in
the existing publication path, per this prompt's requirements 10/11.

Covers:
    1. ordinary success -> ordinary success: the second call's
       `last_response_generation_result` is a fresh object, not the
       first call's
    2. correction-aware success -> ordinary success: same, with the
       second call's `correction_application_result_usable` explicitly
       False despite the predecessor's True
    3. ordinary success -> correction-aware success: same, with the
       second call's `correction_application_result_usable` explicitly
       True
    4. successful response -> injected late failure (Prompt 602's
       injection): the previous `last_response_generation_result` is
       not retained - it becomes None, never the predecessor's object
    5. late failure -> successful recovery: the recovery call's
       `last_response_generation_result` is a fresh object, neither the
       original predecessor's nor (vacuously, since it was None) the
       failed call's
    6. for every successful generation, the current outcome and the
       current `ConversationResponse` remain field-consistent
       (`_assert_same_lifecycle`, Prompt 592) - the existing
       relationship is unchanged by this prompt
    7. repeated `get_last_response_generation_result()` reads after a
       successful publication return the exact same object every time
       (read-only - no rebuild, no mutation)

Reuses the Prompt 576 helper (`_make_core`), the Prompt 592 helpers
(`_generate_correction_aware`, `_generate_ordinary`,
`_assert_same_lifecycle`), and the Prompt 602 late-failure injection
helper (`_generate_with_injected_late_failure`) rather than creating any
new production hook. Real object references are compared with
`assertIs` / `assertIsNot` throughout; no raw `id()` comparisons, per
this prompt's requirement 8.

Run directly:
    python -m unittest tests.test_correction_aware_response_generation_result_publication_prompt604 -v
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


class TestGenerationResultIsFreshAcrossSuccessTransitions(unittest.TestCase):
    """1, 2, 3: for every successful generation, `last_response_generation_result`
    is the current call's own fresh outcome, never the predecessor's object."""

    def test_ordinary_then_ordinary(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            step1_outcome = lic.get_last_response_generation_result()
            self.assertIsNotNone(step1_outcome)

            _generate_ordinary(core, text="tell me about plugh")
            step2_outcome = lic.get_last_response_generation_result()
            self.assertIsNotNone(step2_outcome)
            self.assertIsNot(step2_outcome, step1_outcome)
            self.assertFalse(step2_outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_correction_aware_then_ordinary(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            step1_outcome = lic.get_last_response_generation_result()
            self.assertTrue(step1_outcome.correction_application_result_usable)

            _generate_ordinary(core, text="tell me about xyzzy")
            step2_outcome = lic.get_last_response_generation_result()
            self.assertIsNot(step2_outcome, step1_outcome)
            self.assertFalse(step2_outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_ordinary_then_correction_aware(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            step1_outcome = lic.get_last_response_generation_result()
            self.assertFalse(step1_outcome.correction_application_result_usable)

            _generate_correction_aware(core)
            step2_outcome = lic.get_last_response_generation_result()
            self.assertIsNot(step2_outcome, step1_outcome)
            self.assertTrue(step2_outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestPreviousGenerationResultNotRetainedAcrossLateFailure(unittest.TestCase):
    """4: after a successful response, an injected late failure must not
    retain the previous `last_response_generation_result` - it clears to
    None rather than keeping the predecessor's object."""

    def test_successful_response_then_injected_late_failure(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            prev_outcome = lic.get_last_response_generation_result()
            self.assertIsNotNone(prev_outcome)

            _generate_with_injected_late_failure(core)

            failed_outcome = lic.get_last_response_generation_result()
            self.assertIsNone(failed_outcome)
            self.assertIsNot(failed_outcome, prev_outcome)  # vacuous but explicit
        finally:
            tmpdir.cleanup()


class TestRecoveryGenerationResultAfterLateFailure(unittest.TestCase):
    """5: after an injected late failure, the recovery call's
    `last_response_generation_result` is a fresh object for that
    recovery call, not the original predecessor's."""

    def test_late_failure_then_successful_recovery(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            original_outcome = lic.get_last_response_generation_result()

            _generate_with_injected_late_failure(core)
            self.assertIsNone(lic.get_last_response_generation_result())

            _generate_ordinary(core, text="tell me about plugh")
            new_outcome = lic.get_last_response_generation_result()
            self.assertIsNotNone(new_outcome)
            self.assertIsNot(new_outcome, original_outcome)
            self.assertFalse(new_outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestGenerationResultConsistentWithConversationResponse(unittest.TestCase):
    """6: the current `last_response_generation_result` and the current
    `last_conversation_response` remain field-consistent for every
    successful transition - the existing relationship (Prompt 592) is
    unchanged by this prompt's added coverage."""

    def test_consistency_holds_across_all_transitions(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_ordinary(core, text="tell me about xyzzy")
            _assert_same_lifecycle(self, lic)

            _generate_correction_aware(core)
            _assert_same_lifecycle(self, lic)

            _generate_ordinary(core, text="tell me about plugh")
            _assert_same_lifecycle(self, lic)

            _generate_with_injected_late_failure(core)
            self.assertIsNone(lic.get_last_response_generation_result())
            self.assertIsNotNone(lic.get_last_conversation_response())

            _generate_correction_aware(core)
            _assert_same_lifecycle(self, lic)
        finally:
            tmpdir.cleanup()


class TestRepeatedReadsAreReadOnly(unittest.TestCase):
    """7: repeated `get_last_response_generation_result()` reads after a
    successful publication return the exact same object every time -
    reading never rebuilds, replaces, or mutates the stored result."""

    def test_reads_stable_after_ordinary_success(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            outcome_first = lic.get_last_response_generation_result()
            for _ in range(10):
                self.assertIs(lic.get_last_response_generation_result(), outcome_first)
        finally:
            tmpdir.cleanup()

    def test_reads_stable_after_correction_aware_success(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            outcome_first = lic.get_last_response_generation_result()
            for _ in range(10):
                self.assertIs(lic.get_last_response_generation_result(), outcome_first)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
