"""
Tests for Prompt 599 - Full Exception-Boundary Regression Coverage for
the Public Response State.

Prompt 598 confirmed the SINGLE reset point in `generate_response()`
(language_intelligence_core.py) runs strictly before `_learned_response()`
/ `_route_response()`, so an uncaught backend exception can never leave a
previous generation's response objects in place - it added one pair of
tests for that specific scenario (ordinary success -> exception ->
recovery). This prompt is the fuller regression sweep of that same
exception boundary Prompt 598's requirements pointed at but did not
exhaust: a correction-aware predecessor, repeated-read stability after
the exception, and an explicit check that the SUBSEQUENT successful
generation does not partially reuse anything from either the pre-
exception success or the exception itself.

No new behavior is introduced or tested here - `generate_response()`
does not catch a backend exception when `fallback_backend` is None (see
`_route_response()`); it propagates, exactly as before. This file only
observes and locks in the EXISTING semantics at that boundary.

Covers:
    1. ordinary success -> uncaught backend exception -> reads: neither
       getter exposes the previous ConversationResponse/
       ResponseGenerationResult, and correction-aware usability does not
       leak (it was False either way here, checked directly)
    2. repeated getter reads after the exception are stable (both still
       None, consistently, across many reads)
    3. a subsequent successful generation is a genuinely NEW object -
       not the pre-exception success, not any placeholder created during
       the exception - and does not partially reuse either
    4. the same sequence with a CORRECTION-AWARE predecessor: the
       exception clears the usable-correction success completely, and
       usability does not leak into the None state or into the later
       successful recovery generation (which is itself an ordinary,
       non-correction-aware message)
    5. reading the (cleared) public getters after the exception does not
       alter the unrelated same-lifecycle fields
       (`last_learned_response_decision`, `last_backend_selection`,
       `last_response_generation_validation`) - they keep whatever the
       reset boundary already established, per Prompt 598

Reuses the Prompt 576 test helper (`_make_core`), the Prompt 592 helpers
(`_generate_correction_aware`, `_generate_ordinary`), and the raising-
backend pattern introduced in Prompt 598's own reset-boundary tests
(`test_correction_aware_response_state_reset_boundary_prompt598.py`)
rather than duplicating that infrastructure. Real object references are
kept and compared with `assertIs`/`assertIsNot` throughout - no raw
`id()` comparisons - per this prompt's requirement 13.

Run directly:
    python -m unittest tests.test_correction_aware_response_exception_recovery_prompt599 -v
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
    _generate_correction_aware, _generate_ordinary,
)


def _raise_on_next_generate(lic, message="deliberate uncaught backend failure"):
    """Make the core's CURRENT backend raise, uncaught, on its very next
    `generate_response()` call, and return a callable that restores the
    original method. `fallback_backend` is asserted None first, so the
    raise is guaranteed to propagate out of
    `LanguageIntelligenceCore.generate_response()` rather than being
    caught by the fallback-handling branch of `_route_response()` - the
    same precondition Prompt 598's own exception test relies on."""
    assert lic.fallback_backend is None
    real_backend = lic.backend
    original_generate = real_backend.generate_response

    def _raising_generate(*args, **kwargs):
        raise RuntimeError(message)

    real_backend.generate_response = _raising_generate

    def _restore():
        real_backend.generate_response = original_generate

    return _restore


def _generate_and_expect_exception(test, core, text="tell me something requiring the backend"):
    lic = core.language_intelligence
    understanding = core.understand_language(text)
    with test.assertRaises(RuntimeError):
        lic.generate_response(understanding, context=core.context)


class TestExceptionClearsOrdinarySuccessCompletely(unittest.TestCase):
    """1 & 2 & 3: ordinary success -> exception -> reads -> new success,
    all on the same core instance."""

    def test_full_sequence(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_ordinary(core, text="tell me about xyzzy")
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            self.assertIsNotNone(prev_conv)
            self.assertIsNotNone(prev_outcome)
            self.assertFalse(prev_conv.correction_application_result_usable)

            restore = _raise_on_next_generate(lic)
            try:
                _generate_and_expect_exception(self, core)
            finally:
                restore()

            # 1: neither getter exposes the previous success
            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
            self.assertIsNot(lic.get_last_conversation_response(), prev_conv)
            self.assertIsNot(lic.get_last_response_generation_result(), prev_outcome)

            # 2: repeated reads after the exception are stable
            for _ in range(10):
                self.assertIsNone(lic.get_last_conversation_response())
                self.assertIsNone(lic.get_last_response_generation_result())

            # 3: the next successful generation is genuinely new, and
            # does not partially reuse the pre-exception success
            _generate_ordinary(core, text="tell me about plugh")
            new_conv = lic.get_last_conversation_response()
            new_outcome = lic.get_last_response_generation_result()
            self.assertIsNotNone(new_conv)
            self.assertIsNotNone(new_outcome)
            self.assertIsNot(new_conv, prev_conv)
            self.assertIsNot(new_outcome, prev_outcome)
            self.assertNotEqual(new_outcome.status, STATUS_FAILED)
        finally:
            tmpdir.cleanup()


class TestExceptionClearsCorrectionAwareSuccessCompletely(unittest.TestCase):
    """4: the same sequence with a correction-aware predecessor - the
    exception must clear the usable-correction success entirely, with no
    usability leak into the cleared state or the later ordinary
    recovery generation."""

    def test_full_sequence_with_correction_aware_predecessor(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_correction_aware(core)
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            self.assertTrue(prev_conv.correction_application_result_usable)
            self.assertTrue(prev_outcome.correction_application_result_usable)

            restore = _raise_on_next_generate(lic)
            try:
                _generate_and_expect_exception(self, core)
            finally:
                restore()

            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
            self.assertIsNot(lic.get_last_conversation_response(), prev_conv)
            self.assertIsNot(lic.get_last_response_generation_result(), prev_outcome)

            for _ in range(10):
                self.assertIsNone(lic.get_last_conversation_response())
                self.assertIsNone(lic.get_last_response_generation_result())

            _generate_ordinary(core, text="tell me about xyzzy")
            new_conv = lic.get_last_conversation_response()
            new_outcome = lic.get_last_response_generation_result()
            self.assertIsNot(new_conv, prev_conv)
            self.assertIsNot(new_outcome, prev_outcome)
            self.assertNotEqual(new_outcome.status, STATUS_FAILED)
            # the ordinary recovery message does not inherit the
            # predecessor's correction-aware usability
            self.assertFalse(new_conv.correction_application_result_usable)
            self.assertFalse(new_outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestReadsAfterExceptionDoNotDisturbUnrelatedState(unittest.TestCase):
    """5: reading the (cleared) public getters after the exception does
    not alter the unrelated same-lifecycle fields that Prompt 598
    established are left untouched by the reset boundary itself."""

    def test_related_state_unaffected_by_reads_after_exception(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_ordinary(core, text="tell me about xyzzy")
            restore = _raise_on_next_generate(lic)
            try:
                _generate_and_expect_exception(self, core)
            finally:
                restore()

            decision_before = lic.last_learned_response_decision
            selection_before = lic.last_backend_selection
            validation_before = lic.last_response_generation_validation

            for _ in range(10):
                lic.get_last_conversation_response()
                lic.get_last_response_generation_result()

            self.assertIs(lic.last_learned_response_decision, decision_before)
            self.assertIs(lic.last_backend_selection, selection_before)
            self.assertIs(lic.last_response_generation_validation, validation_before)
            self.assertIsNone(lic.last_response_generation_validation)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
