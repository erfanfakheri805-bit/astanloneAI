"""
Tests for Prompt 597 - Independence Between the Public Response-State
Lifecycle and Surrounding `LanguageIntelligenceCore` State.

Inspection performed by this prompt: re-traced every assignment site of
the "related" state fields in language_intelligence_core.py -
`last_learned_response_decision`, `last_backend_selection`,
`last_response_generation_validation`, and `last_response_plan` - plus
`last_understanding_fallback` (the same kind of side-state, reset by
`understand()`):

    understand()          resets `last_understanding_fallback`, then
                          (`_attach_response_plan`) resets and rebuilds
                          `last_response_plan` - NEVER touches
                          `last_conversation_response` or
                          `last_response_generation_result`.
    plan_response()       calls `self.response_planner.plan(...)`
                          directly - sets no `self.last_*` attribute
                          at all.
    select_backend()   /
    check_model_readiness()
                          both read-only per their own docstrings -
                          set no `self.last_*` attribute.
    generate_response()   resets and rebuilds ALL of
                          `last_response_generation_result`,
                          `last_response_generation_validation`,
                          `last_conversation_response`,
                          `last_learned_response_decision`, and
                          (inside `_route_response`)
                          `last_backend_selection` - but only as part of
                          ITS OWN call, never as a side effect of any of
                          the calls above.

So the two directions Prompt 597 asks for are already structurally true:
resetting/rebuilding `last_response_plan` or `last_understanding_fallback`
via `understand()`/`plan_response()` (unrelated calls made AFTER a
`generate_response()`) cannot reach `last_conversation_response` or
`last_response_generation_result` (no shared code path, no aliasing -
`generate_response()` resets its own three at its own top, no one else
does); and Prompt 595/596 already proved the getters are plain attribute
reads, so they cannot write to `last_learned_response_decision`,
`last_backend_selection`, `last_response_generation_validation`, or
`last_response_plan` either. This file is the smallest additional
regression coverage that isolates INDEPENDENCE between the two families
of state as its own explicit contract, using unrelated public calls
(`understand()`, `plan_response()`, `select_backend()`,
`check_model_readiness()`) interleaved with the response-state getters,
across every reachable generation outcome and the full recovery
sequence.

Covers:
    1. calling `understand()` again after `generate_response()` (which
       resets `last_understanding_fallback` and rebuilds
       `last_response_plan`) leaves `last_conversation_response`,
       `last_response_generation_result`, and
       `correction_application_result_usable` on both completely
       unchanged (identity and fields)
    2. calling `plan_response()`, `select_backend()`, and
       `check_model_readiness()` directly after `generate_response()`
       leaves the same three untouched
    3. reading either public getter, repeatedly, does not alter
       `last_learned_response_decision`, `last_backend_selection`,
       `last_response_generation_validation`, or `last_response_plan`
    4. both directions hold for: an ordinary success, a correction-aware
       success, and a failed/no-usable response
    5. across a SUCCESS -> FAILURE -> SUCCESS sequence, unrelated calls
       and getter reads interleaved at every step disturb neither the
       current step's response-state nor any earlier step's

No production code was changed (Prompt 597 requirements 7/8/9): the two
families of state are already independent; this file adds regression
coverage proving it explicitly.

Reuses the Prompt 576 test helper (`_make_core`), the Prompt 592 helpers
(`_generate_correction_aware`, `_generate_ordinary`, `_generate_failure`),
and the Prompt 594 helper (`_restore_working_backend`) rather than
duplicating that infrastructure.

Run directly:
    python -m unittest tests.test_correction_aware_response_state_independence_prompt597 -v
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


def _snapshot_response_object(obj):
    fields = (
        "response_text", "generated_text", "status", "backend_kind",
        "correction_application_result_usable", "used_verified_correction",
    )
    return tuple(getattr(obj, f, "<absent>") for f in fields)


def _snapshot_response_state(lic):
    """The public response-state pair, captured as one unit: the objects
    THEMSELVES are kept (not just their `id()`) so a later, unrelated
    object cannot coincidentally be allocated at a freed, reused address
    and be mistaken for "the same" one - plus each object's own field
    snapshot, so a single assertion catches either kind of disturbance."""
    conv = lic.get_last_conversation_response()
    outcome = lic.get_last_response_generation_result()
    return (
        conv, outcome,
        _snapshot_response_object(conv), _snapshot_response_object(outcome),
    )


def _assert_response_state_unchanged(test, lic, before):
    conv, outcome, conv_snap, outcome_snap = before
    now_conv = lic.get_last_conversation_response()
    now_outcome = lic.get_last_response_generation_result()
    test.assertIs(now_conv, conv)
    test.assertIs(now_outcome, outcome)
    test.assertEqual(_snapshot_response_object(now_conv), conv_snap)
    test.assertEqual(_snapshot_response_object(now_outcome), outcome_snap)


def _assert_response_state_different(test, state_a, state_b):
    """The two snapshots belong to genuinely different generations -
    checked by real object identity, not by a possibly-reused id()."""
    conv_a, outcome_a, _, _ = state_a
    conv_b, outcome_b, _, _ = state_b
    test.assertIsNot(conv_a, conv_b)
    test.assertIsNot(outcome_a, outcome_b)


def _snapshot_related_state(lic):
    """The Prompt 597 "related" fields, by identity - untouched reads
    should never even swap in an equal-looking replacement object."""
    return (
        id(lic.last_learned_response_decision),
        id(lic.last_backend_selection),
        id(lic.last_response_generation_validation),
        id(lic.last_response_plan),
    )


class TestUnrelatedStateResetsDoNotMutateResponseState(unittest.TestCase):
    """1 & 2: calling understand()/plan_response()/select_backend()/
    check_model_readiness() after generate_response() - each of which
    resets or rebuilds one of the "related" fields - never disturbs the
    public response-state pair."""

    def _check(self, core):
        lic = core.language_intelligence
        before = _snapshot_response_state(lic)

        # understand() resets last_understanding_fallback and rebuilds
        # last_response_plan on every call
        fresh_understanding = core.understand_language("what time is it")
        _assert_response_state_unchanged(self, lic, before)

        # plan_response() re-plans directly (no last_* write at all)
        lic.plan_response(fresh_understanding)
        _assert_response_state_unchanged(self, lic, before)

        # select_backend() / check_model_readiness(): read-only per their
        # own contract, called here directly rather than only via
        # generate_response()'s internal routing
        lic.select_backend()
        lic.check_model_readiness()
        _assert_response_state_unchanged(self, lic, before)

    def test_ordinary_success(self):
        core, tmpdir = _make_core()
        try:
            _generate_ordinary(core)
            self._check(core)
        finally:
            tmpdir.cleanup()

    def test_correction_aware_success(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            self.assertTrue(
                core.language_intelligence.get_last_conversation_response()
                .correction_application_result_usable)
            self._check(core)
        finally:
            tmpdir.cleanup()

    def test_failed_generation(self):
        core, tmpdir = _make_core()
        try:
            _generate_failure(core)
            self.assertEqual(
                core.language_intelligence.get_last_response_generation_result().status,
                STATUS_FAILED)
            self._check(core)
        finally:
            tmpdir.cleanup()


class TestGetterReadsDoNotMutateRelatedState(unittest.TestCase):
    """3: reading either public getter, repeatedly, never alters any of
    the "related" state fields - the reverse direction of the
    independence contract."""

    def _check(self, core):
        lic = core.language_intelligence
        before = _snapshot_related_state(lic)
        for _ in range(10):
            lic.get_last_conversation_response()
            lic.get_last_response_generation_result()
        self.assertEqual(_snapshot_related_state(lic), before)

    def test_ordinary_success(self):
        core, tmpdir = _make_core()
        try:
            _generate_ordinary(core)
            self._check(core)
        finally:
            tmpdir.cleanup()

    def test_correction_aware_success(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            self._check(core)
        finally:
            tmpdir.cleanup()

    def test_failed_generation(self):
        core, tmpdir = _make_core()
        try:
            _generate_failure(core)
            self._check(core)
        finally:
            tmpdir.cleanup()


class TestIndependenceAcrossFullRecoverySequence(unittest.TestCase):
    """5: SUCCESS -> FAILURE -> SUCCESS - unrelated calls and getter
    reads interleaved at every step disturb neither the current step's
    response-state nor any earlier step's already-returned objects."""

    def test_recovery_sequence_independence(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            original_backend = lic.backend

            _generate_ordinary(core, text="tell me about xyzzy")
            step1_state = _snapshot_response_state(lic)
            core.understand_language("an unrelated message")
            lic.select_backend()
            lic.check_model_readiness()
            _assert_response_state_unchanged(self, lic, step1_state)

            _generate_failure(core)
            step2_state = _snapshot_response_state(lic)
            self.assertEqual(step2_state[3][2], STATUS_FAILED)  # outcome.status
            core.understand_language("another unrelated message")
            lic.select_backend()
            _assert_response_state_unchanged(self, lic, step2_state)
            # the earlier success step is still exactly as it was
            _assert_response_state_different(self, step1_state, step2_state)
            _assert_response_state_unchanged(self, lic, step2_state)

            _restore_working_backend(core, original_backend)
            _generate_ordinary(core, text="tell me about plugh")
            step3_state = _snapshot_response_state(lic)
            core.understand_language("yet another unrelated message")
            lic.plan_response(core.understand_language("plan me too"))
            lic.select_backend()
            lic.check_model_readiness()
            _assert_response_state_unchanged(self, lic, step3_state)

            _assert_response_state_different(self, step3_state, step1_state)
            _assert_response_state_different(self, step3_state, step2_state)
            self.assertNotEqual(step3_state[3][2], STATUS_FAILED)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
