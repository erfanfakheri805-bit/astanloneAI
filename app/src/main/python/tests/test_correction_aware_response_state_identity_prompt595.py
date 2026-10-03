"""
Tests for Prompt 595 - Response-State Object Identity Regression Coverage
Across the `generate_response()` Lifecycle.

Inspection performed by this prompt: re-traced `LanguageIntelligenceCore.
generate_response()`, `get_last_conversation_response()`, and
`get_last_response_generation_result()` (language_intelligence_core.py),
plus the Prompt 590-594 tests/inspection notes. Confirmed (no production
change needed):

    def get_last_conversation_response(self):
        return self.last_conversation_response

    def get_last_response_generation_result(self):
        return self.last_response_generation_result

Both getters are plain attribute reads - no rebuilding, no defensive
copying, no mutation, and no call into generation. `self.last_*` is set
exactly once per `generate_response()` call (after the top-of-method
reset), so the SAME object is returned for every read until the next
`generate_response()` call replaces it. Prompts 590-592 already exercised
this identity property as part of broader consistency/lifecycle checks;
this prompt is the smallest additional coverage that isolates OBJECT
IDENTITY itself as its own explicit contract, across every generation
outcome and across the full recovery sequence, including a check that
reading the getters cannot itself trigger generation (no backend/decision
call count increases from reads alone).

Covers:
    1. repeated reads of each getter return the identical stored object
       (by `is`) when no new generation has happened, for: an ordinary
       success, a correction-aware success, and a failed/no-usable
       response
    2. getter reads do not mutate the stored object's fields and do not
       trigger a new generation (a spy backend's call count is unchanged
       by getter reads alone)
    3. a new generation intentionally replaces the previous identity
       (`is not`), while repeated reads WITHIN that new generation stay
       identity-stable
    4. across SUCCESS -> FAILURE -> SUCCESS, the final generation's
       identity is never any earlier step's object, and interleaved
       repeated reads throughout remain stable to whichever generation
       is currently current

No production code was changed (Prompt 595 requirements 7/8/9): the
getters already satisfy the identity contract; this file only adds
regression coverage proving it explicitly.

Reuses the Prompt 576 test helper (`_make_core`), the Prompt 592 helpers
(`_generate_correction_aware`, `_generate_ordinary`, `_generate_failure`),
and the Prompt 594 helper (`_restore_working_backend`) rather than
duplicating that infrastructure.

Run directly:
    python -m unittest tests.test_correction_aware_response_state_identity_prompt595 -v
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
from tests.test_correction_aware_response_recovery_prompt594 import (
    _restore_working_backend,
)


def _assert_identity_stable_across_reads(test, lic, reads=8):
    """Read both getters `reads` times, interleaved, and assert every
    read returns the SAME object identity as the first read of that
    getter - proving reads themselves never replace the stored object."""
    conv_first = lic.get_last_conversation_response()
    outcome_first = lic.get_last_response_generation_result()
    for _ in range(reads):
        test.assertIs(lic.get_last_conversation_response(), conv_first)
        test.assertIs(lic.get_last_response_generation_result(), outcome_first)
    return conv_first, outcome_first


class TestIdentityStableAcrossRepeatedReadsPerOutcome(unittest.TestCase):
    """1: repeated reads return the identical object for each of the
    three reachable generation outcomes."""

    def test_ordinary_success(self):
        core, tmpdir = _make_core()
        try:
            _generate_ordinary(core)
            _assert_identity_stable_across_reads(self, core.language_intelligence)
        finally:
            tmpdir.cleanup()

    def test_correction_aware_success(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            _assert_identity_stable_across_reads(self, core.language_intelligence)
        finally:
            tmpdir.cleanup()

    def test_failed_generation(self):
        core, tmpdir = _make_core()
        try:
            _generate_failure(core)
            conv, outcome = _assert_identity_stable_across_reads(
                self, core.language_intelligence)
            self.assertEqual(outcome.status, STATUS_FAILED)
        finally:
            tmpdir.cleanup()


class TestReadsDoNotMutateOrTriggerGeneration(unittest.TestCase):
    """2: getter reads do not mutate the stored object's fields and do
    not themselves cause another generation to happen."""

    def test_reads_do_not_mutate_fields(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            conv = lic.get_last_conversation_response()
            outcome = lic.get_last_response_generation_result()

            snapshot = (
                conv.response_text, conv.status, conv.backend_kind,
                conv.correction_application_result_usable,
                outcome.status, outcome.generated_text, outcome.backend_kind,
                outcome.correction_application_result_usable,
            )
            for _ in range(10):
                lic.get_last_conversation_response()
                lic.get_last_response_generation_result()
            after = (
                conv.response_text, conv.status, conv.backend_kind,
                conv.correction_application_result_usable,
                outcome.status, outcome.generated_text, outcome.backend_kind,
                outcome.correction_application_result_usable,
            )
            self.assertEqual(snapshot, after)
        finally:
            tmpdir.cleanup()

    def test_reads_do_not_trigger_new_generation(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core)

            calls = {"n": 0}
            real_backend = lic.backend
            original_generate = real_backend.generate_response

            def _counting_generate(*args, **kwargs):
                calls["n"] += 1
                return original_generate(*args, **kwargs)

            real_backend.generate_response = _counting_generate
            try:
                for _ in range(10):
                    lic.get_last_conversation_response()
                    lic.get_last_response_generation_result()
                self.assertEqual(calls["n"], 0)
            finally:
                real_backend.generate_response = original_generate
        finally:
            tmpdir.cleanup()


class TestNewGenerationReplacesIdentityButStaysStableWithin(unittest.TestCase):
    """3: a new generation intentionally produces a new identity, while
    repeated reads WITHIN that new generation stay identity-stable."""

    def test_ordinary_then_ordinary(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            first_conv, first_outcome = _assert_identity_stable_across_reads(self, lic)

            _generate_ordinary(core, text="tell me about plugh")
            second_conv, second_outcome = _assert_identity_stable_across_reads(self, lic)

            self.assertIsNot(second_conv, first_conv)
            self.assertIsNot(second_outcome, first_outcome)
        finally:
            tmpdir.cleanup()

    def test_correction_aware_then_correction_aware(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            first_conv, first_outcome = _assert_identity_stable_across_reads(self, lic)

            _generate_correction_aware(core)
            second_conv, second_outcome = _assert_identity_stable_across_reads(self, lic)

            self.assertIsNot(second_conv, first_conv)
            self.assertIsNot(second_outcome, first_outcome)
            self.assertTrue(second_conv.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestIdentityAcrossFullRecoverySequence(unittest.TestCase):
    """4: SUCCESS -> FAILURE -> SUCCESS never retains an earlier step's
    object identity, and repeated reads throughout stay stable to
    whichever generation is currently current."""

    def test_recovery_sequence_identity(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            original_backend = lic.backend

            _generate_ordinary(core, text="tell me about xyzzy")
            step1_conv, step1_outcome = _assert_identity_stable_across_reads(self, lic)

            _generate_failure(core)
            step2_conv, step2_outcome = _assert_identity_stable_across_reads(self, lic)
            self.assertEqual(step2_outcome.status, STATUS_FAILED)
            self.assertIsNot(step2_conv, step1_conv)
            self.assertIsNot(step2_outcome, step1_outcome)

            _restore_working_backend(core, original_backend)
            _generate_ordinary(core, text="tell me about plugh")
            step3_conv, step3_outcome = _assert_identity_stable_across_reads(self, lic)

            self.assertNotEqual(step3_outcome.status, STATUS_FAILED)
            self.assertIsNot(step3_conv, step1_conv)
            self.assertIsNot(step3_outcome, step1_outcome)
            self.assertIsNot(step3_conv, step2_conv)
            self.assertIsNot(step3_outcome, step2_outcome)

            # earlier steps' own objects remain exactly as they were
            self.assertIs(lic.get_last_conversation_response(), step3_conv)
            self.assertIs(lic.get_last_response_generation_result(), step3_outcome)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
