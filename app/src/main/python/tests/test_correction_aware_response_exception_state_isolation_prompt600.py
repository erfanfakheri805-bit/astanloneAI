"""
Tests for Prompt 600 - Cleared Response-State vs Unrelated Lifecycle
State Across the Exception Boundary.

Prompt 598 established the exact reset boundary in `generate_response()`
(language_intelligence_core.py): exactly three attributes -
`last_response_generation_result`, `last_response_generation_validation`,
`last_conversation_response` - are cleared at the top of the method,
strictly before `_learned_response()` / `_route_response()` run, so an
uncaught backend exception can never leave a previous generation's
response objects in place. Prompt 599 was the fuller regression sweep
of that same boundary (correction-aware predecessor, repeated-read
stability, subsequent-recovery isolation).

This prompt narrows in on one distinction those two did not fully
exercise together: cleared response-state (the three reset attributes)
versus attributes that are NOT part of the reset block at all -
`last_learned_response_decision`, `last_backend_selection`,
`last_response_plan` - which either keep their previous value briefly
or get overwritten by that SAME failing call's own normal update logic
(both `_learned_response()` and `_route_response()` unconditionally
update their own attribute before the backend is ever called, so a
call that raises still updates them "normally" - this is expected,
not a boundary leak). `last_response_plan` is set only inside
`_attach_response_plan()` (called from `understand()`), and
`generate_response()` never reads or writes it at all, so it is
untouched by this exception boundary in either direction.

No production code is changed here - this file only observes and
locks in the existing semantics, per this prompt's requirement 7.

Covers:
    1. ordinary predecessor: after the exception, the three reset
       attributes are cleared, while `last_learned_response_decision`
       and `last_backend_selection` reflect the FAILING call's own
       normal update (a genuinely new decision/selection object, not
       the predecessor's stale one, not None-by-boundary) and
       `last_response_plan` is completely untouched by
       `generate_response()` (still exactly the object `understand()`
       set for the failing message, before generate_response ran)
    2. the same distinction with a CORRECTION-AWARE predecessor
    3. repeated public getter reads after the exception do not mutate
       `last_learned_response_decision`, `last_backend_selection`,
       `last_response_generation_validation`, or `last_response_plan`,
       for both predecessor types
    4. a subsequent successful generation updates
       `last_learned_response_decision` / `last_backend_selection` /
       `last_response_generation_validation` / `last_response_plan` to
       genuinely NEW objects captured at the moment normal generation
       produces them - never the pre-exception predecessor's objects,
       never anything from the exception call itself

Reuses the Prompt 576 helper (`_make_core`), the Prompt 592 helpers
(`_generate_correction_aware`, `_generate_ordinary`), the Prompt 599
raising-backend helper pattern, and the Prompt 598
`_capture_state_at_decision_time`-style monkeypatching approach for
identity checks - extended here to also capture `select_backend()`'s
result and `_attach_response_plan()`'s plan. Real object references are
compared with `assertIs` / `assertIsNot` throughout; no raw `id()`
comparisons, per this prompt's requirement 11.

Run directly:
    python -m unittest tests.test_correction_aware_response_exception_state_isolation_prompt600 -v
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
from tests.test_correction_aware_response_exception_recovery_prompt599 import (
    _raise_on_next_generate, _generate_and_expect_exception,
)


def _capture_select_backend(lic):
    """Wrap the core's bound `select_backend()` so every call it makes
    is recorded, returning a list of the `BackendSelection` objects (in
    call order) and a restore callable. Used to get the exact object
    `_route_response()` assigns to `last_backend_selection` during a
    specific `generate_response()` call, independent of whatever the
    attribute holds afterwards."""
    calls = []
    original = lic.select_backend

    def _capturing():
        selection = original()
        calls.append(selection)
        return selection

    lic.select_backend = _capturing

    def _restore():
        lic.select_backend = original

    return calls, _restore


class TestClearedVsUnrelatedStateOrdinaryPredecessor(unittest.TestCase):
    """1: with an ordinary predecessor, the reset block clears the three
    response-state attributes, while the unrelated attributes either
    keep their pre-call value (`last_response_plan`, untouched by
    `generate_response()` entirely) or are overwritten by the failing
    call's OWN normal update logic (`last_learned_response_decision`,
    `last_backend_selection`) - never left stale, never resurrected
    from the predecessor."""

    def test_reset_vs_unrelated_after_exception(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_ordinary(core, text="tell me about xyzzy")
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            prev_decision = lic.last_learned_response_decision
            prev_selection = lic.last_backend_selection
            self.assertIsNotNone(prev_conv)
            self.assertIsNotNone(prev_outcome)

            restore_backend = _raise_on_next_generate(lic)
            selection_calls, restore_select = _capture_select_backend(lic)
            try:
                understanding = core.understand_language(
                    "tell me something requiring the backend")
                plan_after_understand = lic.last_response_plan
                self.assertIsNotNone(plan_after_understand)
                with self.assertRaises(RuntimeError):
                    lic.generate_response(understanding, context=core.context)
            finally:
                restore_backend()
                restore_select()

            # the three reset attributes are cleared
            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
            self.assertIsNone(lic.last_response_generation_validation)
            self.assertIsNot(lic.get_last_conversation_response(), prev_conv)
            self.assertIsNot(lic.get_last_response_generation_result(), prev_outcome)

            # last_response_plan is untouched by generate_response(): it
            # still holds exactly what understand() set for THIS message,
            # before generate_response ever ran
            self.assertIs(lic.last_response_plan, plan_after_understand)

            # the failing call still ran its own normal update logic for
            # the decision/selection - a genuinely new object, not the
            # predecessor's, not left stale
            self.assertEqual(len(selection_calls), 1)
            self.assertIs(lic.last_backend_selection, selection_calls[0])
            self.assertIsNot(lic.last_backend_selection, prev_selection)
            self.assertIsNotNone(lic.last_learned_response_decision)
            self.assertIsNot(lic.last_learned_response_decision, prev_decision)
        finally:
            tmpdir.cleanup()


class TestClearedVsUnrelatedStateCorrectionAwarePredecessor(unittest.TestCase):
    """2: the same distinction, starting from a correction-aware
    predecessor - the exception must clear the usable-correction
    success completely, and the unrelated attributes must not carry the
    predecessor's correction-aware identity forward."""

    def test_reset_vs_unrelated_after_exception_with_correction_aware_predecessor(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_correction_aware(core)
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            prev_decision = lic.last_learned_response_decision
            self.assertTrue(prev_conv.correction_application_result_usable)
            self.assertTrue(prev_decision.correction_application_result_usable)

            restore_backend = _raise_on_next_generate(lic)
            selection_calls, restore_select = _capture_select_backend(lic)
            try:
                understanding = core.understand_language(
                    "tell me something requiring the backend")
                plan_after_understand = lic.last_response_plan
                with self.assertRaises(RuntimeError):
                    lic.generate_response(understanding, context=core.context)
            finally:
                restore_backend()
                restore_select()

            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
            self.assertIsNone(lic.last_response_generation_validation)
            self.assertIsNot(lic.get_last_conversation_response(), prev_conv)
            self.assertIsNot(lic.get_last_response_generation_result(), prev_outcome)

            self.assertIs(lic.last_response_plan, plan_after_understand)

            # the failing call's own decision replaces the predecessor's -
            # for this ordinary-text message it is not correction-aware
            self.assertEqual(len(selection_calls), 1)
            self.assertIs(lic.last_backend_selection, selection_calls[0])
            self.assertIsNotNone(lic.last_learned_response_decision)
            self.assertIsNot(lic.last_learned_response_decision, prev_decision)
            self.assertFalse(
                bool(getattr(lic.last_learned_response_decision,
                             "correction_application_result_usable", False)))
        finally:
            tmpdir.cleanup()


class TestRepeatedReadsAcrossPredecessorTypes(unittest.TestCase):
    """3: repeated public getter reads after the exception never mutate
    the unrelated attributes, for either predecessor type."""

    def _assert_reads_are_inert(self, lic):
        decision_before = lic.last_learned_response_decision
        selection_before = lic.last_backend_selection
        validation_before = lic.last_response_generation_validation
        plan_before = lic.last_response_plan

        for _ in range(10):
            lic.get_last_conversation_response()
            lic.get_last_response_generation_result()
            lic.get_last_response_generation_validation()

        self.assertIs(lic.last_learned_response_decision, decision_before)
        self.assertIs(lic.last_backend_selection, selection_before)
        self.assertIs(lic.last_response_generation_validation, validation_before)
        self.assertIsNone(lic.last_response_generation_validation)
        self.assertIs(lic.last_response_plan, plan_before)

    def test_repeated_reads_inert_after_ordinary_predecessor(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            restore = _raise_on_next_generate(lic)
            try:
                _generate_and_expect_exception(self, core)
            finally:
                restore()
            self._assert_reads_are_inert(lic)
        finally:
            tmpdir.cleanup()

    def test_repeated_reads_inert_after_correction_aware_predecessor(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            restore = _raise_on_next_generate(lic)
            try:
                _generate_and_expect_exception(self, core)
            finally:
                restore()
            self._assert_reads_are_inert(lic)
        finally:
            tmpdir.cleanup()


class TestSubsequentGenerationOnlyUpdatesNormalFields(unittest.TestCase):
    """4: a subsequent successful generation updates the unrelated
    attributes to genuinely new objects produced by ITS OWN normal
    logic - never the pre-exception predecessor's objects, and never
    anything left behind by the exception call itself."""

    def test_recovery_updates_only_via_normal_logic(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_correction_aware(core)
            prev_conv = lic.get_last_conversation_response()
            prev_outcome = lic.get_last_response_generation_result()
            prev_decision = lic.last_learned_response_decision
            prev_selection = lic.last_backend_selection

            restore = _raise_on_next_generate(lic)
            try:
                _generate_and_expect_exception(self, core)
            finally:
                restore()

            exception_decision = lic.last_learned_response_decision
            exception_selection = lic.last_backend_selection
            exception_plan = lic.last_response_plan
            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())

            selection_calls, restore_select = _capture_select_backend(lic)
            try:
                _generate_ordinary(core, text="tell me about plugh")
            finally:
                restore_select()

            new_conv = lic.get_last_conversation_response()
            new_outcome = lic.get_last_response_generation_result()
            new_decision = lic.last_learned_response_decision
            new_selection = lic.last_backend_selection
            new_validation = lic.last_response_generation_validation

            # response-state: genuinely new, not the predecessor's, not
            # resurrected from the exception call
            self.assertIsNotNone(new_conv)
            self.assertIsNotNone(new_outcome)
            self.assertIsNot(new_conv, prev_conv)
            self.assertIsNot(new_outcome, prev_outcome)
            self.assertNotEqual(new_outcome.status, STATUS_FAILED)
            self.assertFalse(new_conv.correction_application_result_usable)

            # unrelated fields: updated by this recovery call's own
            # normal logic (a fresh selection was actually made), not
            # equal to either the pre-exception predecessor's objects or
            # whatever the exception call itself last set
            self.assertEqual(len(selection_calls), 1)
            self.assertIs(new_selection, selection_calls[0])
            self.assertIsNot(new_selection, prev_selection)
            self.assertIsNot(new_selection, exception_selection)
            self.assertIsNotNone(new_decision)
            self.assertIsNot(new_decision, prev_decision)
            self.assertIsNot(new_decision, exception_decision)
            self.assertIsNotNone(new_validation)

            # last_response_plan is still untouched by generate_response
            # itself - it reflects the recovery message's own understand()
            # call, not anything generate_response wrote
            self.assertIsNotNone(lic.last_response_plan)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
