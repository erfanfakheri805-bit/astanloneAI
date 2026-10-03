"""
Tests for Prompt 601 - The Response-State Reset Happens Strictly Before
the Backend/Model Operation Itself.

Prompt 598 proved the reset lines run before `_learned_response()` (by
capturing state at the moment `decide_learned_response()` is invoked).
Prompt 599/600 proved the resulting cleared-vs-unrelated state holds
after the fact, including across an uncaught backend exception. None of
them captured state at the exact moment the BACKEND's own
`generate_response()` is entered - the actual "response-generation
work" this prompt's requirement 4 asks to instrument directly, rather
than merely observing the final state afterwards.

This file wraps the real backend's `generate_response()` itself (not
`decide_learned_response()`) so the reset can be observed as already
applied at the last possible moment before any response-generation
work - model call included - runs. This is a strictly later, more
specific ordering proof than Prompt 598's: `_learned_response()` may
run in between (deciding not to use a learned response for these
plain-text messages) without ever exposing anything, because the reset
already happened before it started.

No production code is changed - the single reset point already has the
intended lifecycle semantics; this file only adds coverage that pins
the ordering down at the backend-call boundary specifically, per this
prompt's requirements 7/8.

Covers:
    1. ordinary successful predecessor -> failing generation: the
       backend's `generate_response()` is entered with the three
       reset attributes already None, and the subsequent exception
       leaves the previous success's public objects unreachable
    2. correction-aware successful predecessor -> failing generation:
       same ordering proof, with the predecessor's usable-correction
       success cleared before the backend call, and not resurrected by
       the exception
    3. successful predecessor -> successful generation: the backend is
       entered with the three attributes already None (not merely
       cleared afterwards), and the resulting new response-state
       objects are fresh, never the predecessor's

Reuses the Prompt 576 helper (`_make_core`), the Prompt 592 helpers
(`_generate_correction_aware`, `_generate_ordinary`), and the Prompt
598/599 raising-backend precondition (`fallback_backend is None`, so a
backend exception always propagates uncaught rather than being handled
by the fallback branch). Real object references are compared with
`assertIs` / `assertIsNot` throughout; no raw `id()` comparisons, per
this prompt's requirement 11.

Run directly:
    python -m unittest tests.test_correction_aware_response_reset_order_prompt601 -v
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


def _wrap_backend_call_capturing_state(lic):
    """Wrap the core's CURRENT backend's `generate_response()` so every
    call snapshots the three reset attributes at the exact moment the
    backend is entered - the last possible point before any
    response-generation work (including the model call itself) runs.
    Returns (captured, restore): `captured` accumulates one tuple per
    call, in call order; `restore` puts the original method back. The
    wrapped method still delegates to the original afterwards, so
    normal (non-raising) generation is unaffected."""
    assert lic.fallback_backend is None
    real_backend = lic.backend
    original_generate = real_backend.generate_response
    captured = []

    def _capturing(*args, **kwargs):
        captured.append((
            lic.last_conversation_response,
            lic.last_response_generation_result,
            lic.last_response_generation_validation,
        ))
        return original_generate(*args, **kwargs)

    real_backend.generate_response = _capturing

    def _restore():
        real_backend.generate_response = original_generate

    return captured, _restore


def _wrap_backend_call_capturing_then_raising(lic, message="deliberate uncaught backend failure"):
    """Like `_wrap_backend_call_capturing_state()`, but the wrapped call
    raises instead of delegating to the original - the same
    uncaught-exception precondition Prompt 598/599/600 rely on
    (`fallback_backend is None`, so the raise propagates out of
    `generate_response()` untouched)."""
    assert lic.fallback_backend is None
    real_backend = lic.backend
    original_generate = real_backend.generate_response
    captured = []

    def _capturing_then_raising(*args, **kwargs):
        captured.append((
            lic.last_conversation_response,
            lic.last_response_generation_result,
            lic.last_response_generation_validation,
        ))
        raise RuntimeError(message)

    real_backend.generate_response = _capturing_then_raising

    def _restore():
        real_backend.generate_response = original_generate

    return captured, _restore


class TestResetPrecedesBackendCallOrdinaryPredecessorThenFailure(unittest.TestCase):
    """1: an ordinary successful predecessor, then a failing generation -
    the reset is already applied at the instant the backend is entered,
    and the exception cannot resurrect the predecessor's public
    objects."""

    def test_reset_precedes_backend_call_and_exception_clears_state(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_ordinary(core, text="tell me about xyzzy")
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            self.assertIsNotNone(prev_conv)
            self.assertIsNotNone(prev_outcome)

            captured, restore = _wrap_backend_call_capturing_then_raising(lic)
            try:
                understanding = core.understand_language(
                    "tell me something requiring the backend")
                with self.assertRaises(RuntimeError):
                    lic.generate_response(understanding, context=core.context)
            finally:
                restore()

            # the backend was entered exactly once, and at that instant
            # all three reset attributes were already None - the reset
            # ran before any response-generation work, model call
            # included
            self.assertEqual(len(captured), 1)
            conv_at_call, outcome_at_call, validation_at_call = captured[0]
            self.assertIsNone(conv_at_call)
            self.assertIsNone(outcome_at_call)
            self.assertIsNone(validation_at_call)

            # the exception cannot resurrect the predecessor's objects
            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
            self.assertIsNot(lic.get_last_conversation_response(), prev_conv)
            self.assertIsNot(lic.get_last_response_generation_result(), prev_outcome)
        finally:
            tmpdir.cleanup()


class TestResetPrecedesBackendCallCorrectionAwarePredecessorThenFailure(unittest.TestCase):
    """2: the same ordering proof starting from a correction-aware
    successful predecessor - the usable-correction success must be
    cleared before the backend is ever entered for the next call, and
    the exception must not resurrect it."""

    def test_reset_precedes_backend_call_with_correction_aware_predecessor(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_correction_aware(core)
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            self.assertTrue(prev_conv.correction_application_result_usable)
            self.assertTrue(prev_outcome.correction_application_result_usable)

            captured, restore = _wrap_backend_call_capturing_then_raising(lic)
            try:
                understanding = core.understand_language(
                    "tell me something requiring the backend")
                with self.assertRaises(RuntimeError):
                    lic.generate_response(understanding, context=core.context)
            finally:
                restore()

            self.assertEqual(len(captured), 1)
            conv_at_call, outcome_at_call, validation_at_call = captured[0]
            self.assertIsNone(conv_at_call)
            self.assertIsNone(outcome_at_call)
            self.assertIsNone(validation_at_call)

            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
            self.assertIsNot(lic.get_last_conversation_response(), prev_conv)
            self.assertIsNot(lic.get_last_response_generation_result(), prev_outcome)
        finally:
            tmpdir.cleanup()


class TestResetPrecedesBackendCallSuccessfulPredecessorThenSuccess(unittest.TestCase):
    """3: a successful predecessor, then a successful generation - the
    backend is still entered with the three reset attributes already
    None (the reset is unconditional, not just an artifact of the
    failure path), and the resulting response-state objects are fresh,
    never the predecessor's."""

    def test_reset_precedes_backend_call_on_the_success_path_too(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_ordinary(core, text="tell me about xyzzy")
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            prev_validation = lic.last_response_generation_validation

            captured, restore = _wrap_backend_call_capturing_state(lic)
            try:
                _generate_ordinary(core, text="tell me about plugh")
            finally:
                restore()

            self.assertEqual(len(captured), 1)
            conv_at_call, outcome_at_call, validation_at_call = captured[0]
            self.assertIsNone(conv_at_call)
            self.assertIsNone(outcome_at_call)
            self.assertIsNone(validation_at_call)

            new_conv = lic.get_last_conversation_response()
            new_outcome = lic.get_last_response_generation_result()
            new_validation = lic.last_response_generation_validation
            self.assertIsNotNone(new_conv)
            self.assertIsNotNone(new_outcome)
            self.assertIsNotNone(new_validation)
            self.assertIsNot(new_conv, prev_conv)
            self.assertIsNot(new_outcome, prev_outcome)
            self.assertIsNot(new_validation, prev_validation)
            self.assertNotEqual(new_outcome.status, STATUS_FAILED)
        finally:
            tmpdir.cleanup()

    def test_reset_precedes_backend_call_from_correction_aware_predecessor(self):
        """The same successful-to-successful ordering proof, starting
        from a correction-aware predecessor, confirming the recovery
        generation neither inherits the predecessor's usability nor
        skips the reset before its own backend call."""
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_correction_aware(core)
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            self.assertTrue(prev_conv.correction_application_result_usable)

            captured, restore = _wrap_backend_call_capturing_state(lic)
            try:
                _generate_ordinary(core, text="tell me about xyzzy")
            finally:
                restore()

            self.assertEqual(len(captured), 1)
            conv_at_call, outcome_at_call, validation_at_call = captured[0]
            self.assertIsNone(conv_at_call)
            self.assertIsNone(outcome_at_call)
            self.assertIsNone(validation_at_call)

            new_conv = lic.get_last_conversation_response()
            new_outcome = lic.get_last_response_generation_result()
            self.assertIsNot(new_conv, prev_conv)
            self.assertIsNot(new_outcome, prev_outcome)
            self.assertFalse(new_conv.correction_application_result_usable)
            self.assertFalse(new_outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
