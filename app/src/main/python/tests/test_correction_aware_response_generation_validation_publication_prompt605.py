"""
Tests for Prompt 605 - The Publication Boundary for
`last_response_generation_validation`, Mirroring Prompts 603/604's
`ConversationResponse` / `last_response_generation_result` Boundaries.

Prompts 603 and 604 proved that for every successful `generate_response()`
call, `last_conversation_response` and `last_response_generation_result`
each correspond to THAT SAME call's own fresh state and are never a
predecessor's object, and that a late (post-backend) failure never
retains the previous publication. This prompt traces the same contract
for the third piece of the same triple - `last_response_generation_validation`
(`get_last_response_generation_validation()`).

The traced path (language_intelligence_core.py, `generate_response()`):
    self.last_response_generation_result = None            # cleared FIRST
    self.last_response_generation_validation = None        # cleared FIRST
    self.last_conversation_response = None
    response = self._learned_response(...) or self._route_response(...)
    outcome = self._build_outcome(response, ...)            # fresh, local
    self.last_response_generation_result = outcome
    self.last_response_generation_validation = self._validate(response, outcome)
    self.last_conversation_response = self._conversation_response(
        response, outcome, self.last_response_generation_validation)
`self.last_response_generation_validation` is unconditionally reset to
None at the top of every call, BEFORE `_validate()` runs, and is only
ever assigned that call's own freshly-computed `_validate(response,
outcome)` result afterward - so it is structurally incapable of
retaining a predecessor's object, on success or on failure.

Prompt 602's late-stage injection (`build_response_generation_outcome`
raising, patched only on `language_intelligence_core`'s own imported
name) makes `_build_outcome()` return None for `outcome`, but
`_validate()` -> `validate_response_generation_result(response,
outcome=None)` (response_generation_validation.py) imports its OWN
`build_response_generation_outcome` reference and is unaffected by that
patch: given `outcome=None` it independently rebuilds a fresh outcome
from `response` and returns a genuine (non-None)
`ResponseGenerationValidation` for that call. Per this prompt's
requirement 8, this file OBSERVES and locks in that exact existing
behavior (a fresh, non-None validation object even while
`last_response_generation_result` is None) rather than asserting it
should be None or inventing any fallback.

No production code is changed here, per this prompt's requirements
11/12.

Covers:
    1. ordinary success -> ordinary success: the second call's
       `last_response_generation_validation` is a fresh object, not the
       first call's, and its status/outcome agree with that call's own
       `last_response_generation_result`
    2. correction-aware success -> ordinary success: same freshness
       check across the transition
    3. ordinary success -> correction-aware success: same freshness
       check across the transition
    4. successful response -> injected late failure (Prompt 602): the
       previous `last_response_generation_validation` is not retained -
       a fresh object is produced for the failing call (never the
       predecessor's), independent of `_build_outcome()`'s own failure
    5. late failure -> successful recovery: the recovery call's
       `last_response_generation_validation` is a fresh object, neither
       the original predecessor's nor the failed call's
    6. the existing relationship between the current validation's
       `.outcome` and the current `last_response_generation_result` /
       `last_conversation_response` remains as documented - unchanged
       by this prompt's added coverage
    7. repeated `get_last_response_generation_validation()` reads after
       a successful publication return the exact same object every time
       (read-only - no rebuild, no mutation)

Reuses the Prompt 576 helper (`_make_core`), the Prompt 592 helpers
(`_generate_correction_aware`, `_generate_ordinary`,
`_assert_same_lifecycle`), and the Prompt 602 late-failure injection
helper (`_generate_with_injected_late_failure`) rather than creating any
new production hook. Real object references are compared with
`assertIs` / `assertIsNot` throughout; no raw `id()` comparisons, per
this prompt's requirement 9.

Run directly:
    python -m unittest tests.test_correction_aware_response_generation_validation_publication_prompt605 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_generation_validation import (
    ResponseGenerationValidation, VALIDATION_VALID,
)

from tests.test_correction_aware_response_decision_prompt576 import _make_core
from tests.test_correction_aware_response_state_consistency_prompt592 import (
    _assert_same_lifecycle, _generate_correction_aware, _generate_ordinary,
)
from tests.test_correction_aware_response_late_failure_prompt602 import (
    _generate_with_injected_late_failure,
)


class TestValidationIsFreshAcrossSuccessTransitions(unittest.TestCase):
    """1, 2, 3: for every successful generation,
    `last_response_generation_validation` is the current call's own
    fresh validation, never the predecessor's object, and its `.outcome`
    is the SAME object as `last_response_generation_result` for that
    call."""

    def test_ordinary_then_ordinary(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            step1_validation = lic.get_last_response_generation_validation()
            self.assertIsNotNone(step1_validation)
            self.assertIsInstance(step1_validation, ResponseGenerationValidation)
            self.assertIs(step1_validation.outcome, lic.get_last_response_generation_result())

            _generate_ordinary(core, text="tell me about plugh")
            step2_validation = lic.get_last_response_generation_validation()
            self.assertIsNotNone(step2_validation)
            self.assertIsNot(step2_validation, step1_validation)
            self.assertIs(step2_validation.outcome, lic.get_last_response_generation_result())
        finally:
            tmpdir.cleanup()

    def test_correction_aware_then_ordinary(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            step1_validation = lic.get_last_response_generation_validation()
            self.assertTrue(step1_validation.outcome.correction_application_result_usable)

            _generate_ordinary(core, text="tell me about xyzzy")
            step2_validation = lic.get_last_response_generation_validation()
            self.assertIsNot(step2_validation, step1_validation)
            self.assertIs(step2_validation.outcome, lic.get_last_response_generation_result())
            self.assertFalse(step2_validation.outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_ordinary_then_correction_aware(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            step1_validation = lic.get_last_response_generation_validation()
            self.assertFalse(step1_validation.outcome.correction_application_result_usable)

            _generate_correction_aware(core)
            step2_validation = lic.get_last_response_generation_validation()
            self.assertIsNot(step2_validation, step1_validation)
            self.assertIs(step2_validation.outcome, lic.get_last_response_generation_result())
            self.assertTrue(step2_validation.outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestPreviousValidationNotRetainedAcrossLateFailure(unittest.TestCase):
    """4: after a successful response, an injected late failure must not
    retain the previous `last_response_generation_validation` - a fresh
    validation object is produced for the failing call, even though
    `_build_outcome()` itself fails for that same call (existing,
    unchanged behavior per this prompt's requirement 8: validation is
    independently rebuilt, not left stale or invented as a fallback)."""

    def test_successful_response_then_injected_late_failure(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            prev_validation = lic.get_last_response_generation_validation()
            self.assertIsNotNone(prev_validation)

            _generate_with_injected_late_failure(core)

            self.assertIsNone(lic.get_last_response_generation_result())
            failed_validation = lic.get_last_response_generation_validation()
            self.assertIsNotNone(failed_validation)
            self.assertIsNot(failed_validation, prev_validation)
            # the failing call's outcome (last_response_generation_result)
            # is None, but validation independently rebuilt its own -
            # that rebuilt outcome is not the predecessor's outcome either
            self.assertIsNot(failed_validation.outcome, prev_validation.outcome)
        finally:
            tmpdir.cleanup()


class TestRecoveryValidationAfterLateFailure(unittest.TestCase):
    """5: after an injected late failure, the recovery call's
    `last_response_generation_validation` is a fresh object for that
    recovery call, not the original predecessor's nor the failed call's."""

    def test_late_failure_then_successful_recovery(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            original_validation = lic.get_last_response_generation_validation()

            _generate_with_injected_late_failure(core)
            failed_validation = lic.get_last_response_generation_validation()
            self.assertIsNotNone(failed_validation)

            _generate_ordinary(core, text="tell me about plugh")
            new_validation = lic.get_last_response_generation_validation()
            self.assertIsNotNone(new_validation)
            self.assertIsNot(new_validation, original_validation)
            self.assertIsNot(new_validation, failed_validation)
            self.assertIs(new_validation.outcome, lic.get_last_response_generation_result())
            self.assertFalse(new_validation.outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestValidationConsistentWithExistingLifecycle(unittest.TestCase):
    """6: the existing relationship between the current validation, the
    current `last_response_generation_result`, and the current
    `last_conversation_response` (Prompt 592's `_assert_same_lifecycle`)
    remains unchanged across every required transition."""

    def test_relationship_holds_across_all_transitions(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_ordinary(core, text="tell me about xyzzy")
            _assert_same_lifecycle(self, lic)
            self.assertIs(
                lic.get_last_response_generation_validation().outcome,
                lic.get_last_response_generation_result())

            _generate_correction_aware(core)
            _assert_same_lifecycle(self, lic)
            self.assertIs(
                lic.get_last_response_generation_validation().outcome,
                lic.get_last_response_generation_result())

            _generate_with_injected_late_failure(core)
            self.assertIsNone(lic.get_last_response_generation_result())
            self.assertIsNotNone(lic.get_last_response_generation_validation())
            self.assertIsNotNone(lic.get_last_conversation_response())

            _generate_ordinary(core, text="tell me about plugh")
            _assert_same_lifecycle(self, lic)
            self.assertIs(
                lic.get_last_response_generation_validation().outcome,
                lic.get_last_response_generation_result())
        finally:
            tmpdir.cleanup()


class TestRepeatedReadsAreReadOnly(unittest.TestCase):
    """7: repeated `get_last_response_generation_validation()` reads
    after a successful publication return the exact same object every
    time - reading never rebuilds, replaces, or mutates the stored
    validation."""

    def test_reads_stable_after_ordinary_success(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            validation_first = lic.get_last_response_generation_validation()
            for _ in range(10):
                self.assertIs(lic.get_last_response_generation_validation(), validation_first)
            self.assertEqual(validation_first.status, VALIDATION_VALID)
        finally:
            tmpdir.cleanup()

    def test_reads_stable_after_correction_aware_success(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            validation_first = lic.get_last_response_generation_validation()
            for _ in range(10):
                self.assertIs(lic.get_last_response_generation_validation(), validation_first)
            self.assertEqual(validation_first.status, VALIDATION_VALID)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
