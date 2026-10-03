"""
Tests for Prompt 598 - The Exact Reset Boundary of the Public Response
State (`last_conversation_response` / `last_response_generation_result`).

Inspection performed by this prompt: every assignment site of
`last_conversation_response` and `last_response_generation_result` in
language_intelligence_core.py, in file order:

    __init__()             both set to None (construction, never
                            "reset" in the lifecycle sense)
    generate_response()     top of the method (lines ~325-327), BEFORE
                            `_learned_response()` or `_route_response()`
                            (and therefore before any backend/model call)
                            runs:
                                self.last_response_generation_result = None
                                self.last_response_generation_validation = None
                                self.last_conversation_response = None
                            ... then, after `response`/`outcome` are
                            produced, both (plus validation) are rebuilt
                            from that SAME call's local variables.

So there is exactly ONE intentional reset point in the whole lifecycle
(besides construction), and it is the very first thing
`generate_response()` does - strictly before `_learned_response()`
(which may set `last_learned_response_decision`) and strictly before
`_route_response()` (which may call the backend and set
`last_backend_selection`). This means: (a) a backend/model failure -
whether a structured STATUS_MODEL_FAILED result or an uncaught
exception - can never leave a PREVIOUS generation's response objects
in place, because they are already cleared before the backend is ever
called; and (b) the reset lines touch only THREE attributes -
`last_response_generation_result`, `last_response_generation_validation`,
`last_conversation_response` - never `last_learned_response_decision`,
`last_backend_selection`, or `last_response_plan`, which keep whatever
value they held from the previous call for the brief remainder of the
current call until their OWN dedicated update point (inside
`_learned_response()` / `_route_response()`) runs.

Covers:
    1. the reset lines run strictly before `_learned_response()` (and
       therefore before any possible backend call), observed directly
       by capturing state at the moment `decide_learned_response()` is
       invoked
    2. the reset lines clear only the three intended attributes - at
       that same moment, `last_learned_response_decision` and
       `last_backend_selection` still hold the PREVIOUS generation's
       values, proving the reset does not touch unrelated state early
    3. the four required boundary sequences (success -> new generation,
       correction-aware success -> new generation, success -> failure,
       failure -> success): immediately after each transition, both
       getters report only the new generation's state, no previous
       object remains exposed, and correction-aware usability does not
       leak across the boundary
    4. an uncaught exception from the backend (no fallback configured)
       still leaves the reset already applied - the getters report
       cleared state, not the prior successful generation's objects,
       proving the reset happens before a backend failure of any kind
       (structured OR an outright exception) could leave stale state
       behind

No production code was changed (Prompt 598 requirements 7/8/9): the
single reset point already has the intended lifecycle semantics; this
file adds the smallest additional regression coverage that isolates the
reset boundary itself, using real object references (never raw `id()`
comparisons, per this prompt's requirement 12) wherever cross-generation
identity must be checked.

Reuses the Prompt 576 test helper (`_make_core`), the Prompt 592 helpers
(`_generate_correction_aware`, `_generate_ordinary`, `_generate_failure`),
and the Prompt 594 helper (`_restore_working_backend`) rather than
duplicating that infrastructure.

Run directly:
    python -m unittest tests.test_correction_aware_response_state_reset_boundary_prompt598 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language_intelligence.language_intelligence_core as lic_module
from language_intelligence.response_generation_outcome import STATUS_FAILED

from tests.test_correction_aware_response_decision_prompt576 import _make_core
from tests.test_correction_aware_response_state_consistency_prompt592 import (
    _generate_correction_aware, _generate_failure, _generate_ordinary,
)
from tests.test_correction_aware_response_recovery_prompt594 import (
    _restore_working_backend,
)


def _capture_state_at_decision_time(lic):
    """Monkeypatch `decide_learned_response` (module-level, used by
    `_learned_response()`) to snapshot the core's response-state
    attributes at the exact moment it is invoked - i.e. right after the
    reset lines run and before either `_learned_response()` or
    `_route_response()` can produce anything new. Returns a list the
    caller can inspect after `generate_response()` returns; also
    restores the original function."""
    captured = []
    original = lic_module.decide_learned_response

    def _capturing(*args, **kwargs):
        captured.append((
            lic.last_conversation_response,
            lic.last_response_generation_result,
            lic.last_response_generation_validation,
            lic.last_learned_response_decision,
            lic.last_backend_selection,
        ))
        return original(*args, **kwargs)

    lic_module.decide_learned_response = _capturing
    return captured, original


class TestResetPrecedesLearnedResponseDecision(unittest.TestCase):
    """1 & 2: at the moment `decide_learned_response()` runs (the first
    thing after the reset lines), the three reset attributes are already
    None, while the unrelated ones still hold the PREVIOUS generation's
    values."""

    def test_second_call_sees_reset_state_but_stale_unrelated_state(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            prev_decision = lic.last_learned_response_decision
            prev_backend_selection = lic.last_backend_selection
            self.assertIsNotNone(prev_decision)

            captured, original = _capture_state_at_decision_time(lic)
            try:
                _generate_correction_aware(core)
            finally:
                lic_module.decide_learned_response = original

            self.assertEqual(len(captured), 1)
            conv, outcome, validation, decision, selection = captured[0]
            # the three reset attributes are already cleared
            self.assertIsNone(conv)
            self.assertIsNone(outcome)
            self.assertIsNone(validation)
            # the unrelated attributes are untouched by the reset lines -
            # still the PREVIOUS generation's own values at this instant
            self.assertIs(decision, prev_decision)
            self.assertIs(selection, prev_backend_selection)
        finally:
            tmpdir.cleanup()

    def test_first_call_ever_sees_construction_defaults(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            self.assertIsNone(lic.last_conversation_response)
            self.assertIsNone(lic.last_response_generation_result)
            self.assertIsNone(lic.last_learned_response_decision)

            captured, original = _capture_state_at_decision_time(lic)
            try:
                _generate_ordinary(core)
            finally:
                lic_module.decide_learned_response = original

            conv, outcome, validation, decision, selection = captured[0]
            self.assertIsNone(conv)
            self.assertIsNone(outcome)
            self.assertIsNone(validation)
            self.assertIsNone(decision)
            self.assertIsNone(selection)
        finally:
            tmpdir.cleanup()


class TestBoundarySequences(unittest.TestCase):
    """3: the four required boundary sequences - immediately after the
    transition, both getters report only the new generation's state, no
    previous object leaks through, and correction-aware usability does
    not leak either direction."""

    def _assert_clean_boundary(self, lic, prev_conv, prev_outcome):
        new_conv = lic.get_last_conversation_response()
        new_outcome = lic.get_last_response_generation_result()
        self.assertIsNot(new_conv, prev_conv)
        self.assertIsNot(new_outcome, prev_outcome)
        return new_conv, new_outcome

    def test_success_then_new_success(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()

            _generate_ordinary(core, text="tell me about plugh")
            self._assert_clean_boundary(lic, prev_conv, prev_outcome)
        finally:
            tmpdir.cleanup()

    def test_correction_aware_then_new_generation(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            self.assertTrue(prev_conv.correction_application_result_usable)

            _generate_ordinary(core, text="tell me about xyzzy")
            new_conv, new_outcome = self._assert_clean_boundary(lic, prev_conv, prev_outcome)
            # the new, ordinary generation does not inherit the previous
            # correction-aware usability
            self.assertFalse(new_conv.correction_application_result_usable)
            self.assertFalse(new_outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_success_then_failure(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            self.assertTrue(prev_conv.correction_application_result_usable)

            _generate_failure(core)
            new_conv, new_outcome = self._assert_clean_boundary(lic, prev_conv, prev_outcome)
            self.assertEqual(new_outcome.status, STATUS_FAILED)
            self.assertIsNone(new_conv.response_text)
            # no leaked usability from the prior successful, correction-
            # aware generation
            self.assertFalse(new_conv.correction_application_result_usable)
            self.assertFalse(new_outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_failure_then_success(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            original_backend = lic.backend

            _generate_failure(core)
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            self.assertEqual(prev_outcome.status, STATUS_FAILED)

            _restore_working_backend(core, original_backend)
            _generate_ordinary(core, text="tell me about plugh")
            new_conv, new_outcome = self._assert_clean_boundary(lic, prev_conv, prev_outcome)
            self.assertNotEqual(new_outcome.status, STATUS_FAILED)
        finally:
            tmpdir.cleanup()


class TestResetPrecedesUncaughtBackendException(unittest.TestCase):
    """4: even an outright exception from the backend (no fallback
    configured, so it propagates uncaught) cannot leave a previous
    successful generation's response objects in place, because the
    reset already ran before the backend was ever called."""

    def test_uncaught_backend_exception_leaves_cleared_state(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            self.assertIsNone(lic.fallback_backend)

            _generate_ordinary(core, text="tell me about xyzzy")
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            self.assertIsNotNone(prev_conv)
            self.assertIsNotNone(prev_outcome)

            real_backend = lic.backend
            original_generate = real_backend.generate_response

            def _raising_generate(*args, **kwargs):
                raise RuntimeError("deliberate uncaught backend failure")

            real_backend.generate_response = _raising_generate
            try:
                understanding = core.understand_language(
                    "tell me something requiring the backend")
                with self.assertRaises(RuntimeError):
                    lic.generate_response(understanding, context=core.context)
            finally:
                real_backend.generate_response = original_generate

            # the reset already ran before the raise: the previous
            # generation's objects are gone, not merely stale-but-present
            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
            self.assertIsNone(lic.last_response_generation_validation)
            self.assertIsNot(lic.get_last_conversation_response(), prev_conv)
        finally:
            tmpdir.cleanup()

    def test_recovery_after_uncaught_exception(self):
        """A subsequent, successful call cleanly rebuilds state after an
        uncaught-exception generation - the reset boundary does not
        leave the core permanently broken."""
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            real_backend = lic.backend
            original_generate = real_backend.generate_response

            def _raising_generate(*args, **kwargs):
                raise RuntimeError("deliberate uncaught backend failure")

            real_backend.generate_response = _raising_generate
            understanding = core.understand_language("tell me about xyzzy")
            with self.assertRaises(RuntimeError):
                lic.generate_response(understanding, context=core.context)
            real_backend.generate_response = original_generate

            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())

            _generate_ordinary(core, text="tell me about xyzzy")
            self.assertIsNotNone(lic.get_last_conversation_response())
            self.assertIsNotNone(lic.get_last_response_generation_result())
            self.assertNotEqual(
                lic.get_last_response_generation_result().status, STATUS_FAILED)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
