"""
Tests for Prompt 596 - Read-Only Contract Hardening for the Public
Response-State Getters (`get_last_conversation_response()` /
`get_last_response_generation_result()`).

Inspection performed by this prompt: re-traced both getters in
language_intelligence_core.py (unchanged since Prompt 595):

    def get_last_conversation_response(self):
        return self.last_conversation_response

    def get_last_response_generation_result(self):
        return self.last_response_generation_result

and every other `self.last_*` attribute `generate_response()` sets
(`last_response_generation_validation`, `last_learned_response_decision`,
`last_backend_selection`, `last_understanding_fallback`,
`last_response_plan`). Both getters are plain attribute reads with no
branching, no rebuilding, no call into `self.backend`,
`decide_learned_response()`, `_route_response()`, `_build_outcome()`,
`_validate()`, or `_conversation_response()`, and no assignment of any
kind. Prompts 590-595 already proved same-lifecycle consistency,
no-leakage-across-generations, and object-identity stability under
repeated reads. What none of those files isolated as its own explicit
contract is that reading ONE getter cannot indirectly disturb: the
OTHER cached response object, the correction-aware usability state
carried on either object, the learning-decision state
(`last_learned_response_decision`), or any of the other same-lifecycle
`last_*` state exposed by `generate_response()` - and that reads never
invoke response generation, correction application, or the learned-
response decision themselves.

Covers:
    1. reading one getter repeatedly leaves the OTHER cached object's
       identity and field values completely unchanged, for an ordinary
       success, a correction-aware success, and a failed/no-usable
       response
    2. reading either getter repeatedly leaves correction-aware
       usability state, `last_learned_response_decision`,
       `last_backend_selection`, `last_response_generation_validation`,
       and `last_response_plan` all unchanged (identity and value)
    3. reading either getter does not invoke `decide_learned_response`,
       the backend's `generate_response`, or the correction-application
       pipeline (`build_response_generation_outcome`), and does not
       change the stored response text
    4. the read-only contract (points 1-3) holds after each of:
       ordinary success, correction-aware success, and failure
    5. across a SUCCESS -> FAILURE -> SUCCESS sequence, interleaved
       reads at every step disturb neither the current step's state nor
       any earlier step's already-returned objects

No production code was changed (Prompt 596 requirements 6/7/8): both
getters already satisfy the read-only contract; this file adds the
smallest additional regression coverage that isolates it explicitly and
checks the state the earlier prompts' files did not directly assert on
(the learning/decision/validation/plan side-state, and that reads never
call into generation or correction application).

Reuses the Prompt 576 test helper (`_make_core`), the Prompt 592 helpers
(`_generate_correction_aware`, `_generate_ordinary`, `_generate_failure`),
and the Prompt 594 helper (`_restore_working_backend`) rather than
duplicating that infrastructure.

Run directly:
    python -m unittest tests.test_correction_aware_response_state_read_only_prompt596 -v
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


def _snapshot_side_state(lic):
    """Every same-lifecycle `last_*` attribute `generate_response()` sets,
    besides the two public getters themselves - captured by identity AND
    by a value tuple, so both an object swap and an in-place mutation
    would be caught."""
    decision = lic.last_learned_response_decision
    selection = lic.last_backend_selection
    validation = lic.last_response_generation_validation
    plan = lic.last_response_plan
    values = (
        getattr(decision, "used", None),
        getattr(decision, "reason", None),
        getattr(decision, "correction_application_result_usable", None),
        selection.not_ready_response if selection is not None else None,
        getattr(validation, "status", None),
        plan.to_dict() if plan is not None else None,
        lic.last_understanding_fallback,
    )
    return (decision, selection, validation, plan), values


def _assert_side_state_unchanged(test, lic, before):
    identities_before, values_before = before
    identities_after, values_after = _snapshot_side_state(lic)
    test.assertEqual(
        [id(x) for x in identities_before], [id(x) for x in identities_after])
    test.assertEqual(values_before, values_after)


def _snapshot_response_object(obj):
    """A plain field snapshot usable for both ConversationResponse and
    ResponseGenerationOutcome (only fields present on the object are
    read, via getattr with a sentinel)."""
    fields = (
        "response_text", "generated_text", "status", "backend_kind",
        "correction_application_result_usable", "used_verified_correction",
    )
    return tuple(getattr(obj, f, "<absent>") for f in fields)


class TestReadingOneGetterLeavesOtherCachedObjectUnchanged(unittest.TestCase):
    """1: reading one getter repeatedly never disturbs the other cached
    object's identity or fields, across all three outcomes."""

    def _check(self, core):
        lic = core.language_intelligence
        conv = lic.get_last_conversation_response()
        outcome = lic.get_last_response_generation_result()
        conv_snapshot = _snapshot_response_object(conv)
        outcome_snapshot = _snapshot_response_object(outcome)

        for _ in range(10):
            lic.get_last_conversation_response()
        self.assertIs(lic.get_last_response_generation_result(), outcome)
        self.assertEqual(_snapshot_response_object(outcome), outcome_snapshot)
        self.assertIs(lic.get_last_conversation_response(), conv)
        self.assertEqual(_snapshot_response_object(conv), conv_snapshot)

        for _ in range(10):
            lic.get_last_response_generation_result()
        self.assertIs(lic.get_last_conversation_response(), conv)
        self.assertEqual(_snapshot_response_object(conv), conv_snapshot)
        self.assertIs(lic.get_last_response_generation_result(), outcome)
        self.assertEqual(_snapshot_response_object(outcome), outcome_snapshot)

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
            self.assertEqual(
                core.language_intelligence.last_response_generation_result.status,
                STATUS_FAILED)
            self._check(core)
        finally:
            tmpdir.cleanup()


class TestReadingEitherGetterLeavesSideStateUnchanged(unittest.TestCase):
    """2: reading either getter repeatedly leaves the learning/decision/
    validation/plan side-state, and correction-aware usability on both
    objects, exactly as it was."""

    def _check(self, core):
        lic = core.language_intelligence
        before = _snapshot_side_state(lic)
        conv_usable = lic.get_last_conversation_response().correction_application_result_usable
        outcome_usable = (
            lic.get_last_response_generation_result().correction_application_result_usable)

        for _ in range(10):
            lic.get_last_conversation_response()
            lic.get_last_response_generation_result()

        _assert_side_state_unchanged(self, lic, before)
        self.assertEqual(
            lic.get_last_conversation_response().correction_application_result_usable,
            conv_usable)
        self.assertEqual(
            lic.get_last_response_generation_result().correction_application_result_usable,
            outcome_usable)

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
            self._check(core)
        finally:
            tmpdir.cleanup()


class TestReadsNeverInvokeGenerationOrCorrectionApplication(unittest.TestCase):
    """3: reading either getter never calls `decide_learned_response`,
    the backend's `generate_response`, or
    `build_response_generation_outcome` - and never changes the stored
    response text."""

    def test_no_learned_response_decision_call_from_reads(self):
        core, tmpdir = _make_core()
        try:
            _generate_ordinary(core)
            lic = core.language_intelligence

            calls = {"n": 0}
            original = lic_module.decide_learned_response

            def _counting(*args, **kwargs):
                calls["n"] += 1
                return original(*args, **kwargs)

            lic_module.decide_learned_response = _counting
            try:
                for _ in range(10):
                    lic.get_last_conversation_response()
                    lic.get_last_response_generation_result()
                self.assertEqual(calls["n"], 0)
            finally:
                lic_module.decide_learned_response = original
        finally:
            tmpdir.cleanup()

    def test_no_backend_generate_call_from_reads_correction_aware(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence

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

    def test_no_outcome_rebuild_call_from_reads(self):
        core, tmpdir = _make_core()
        try:
            _generate_ordinary(core)
            lic = core.language_intelligence

            calls = {"n": 0}
            original = lic_module.build_response_generation_outcome

            def _counting(*args, **kwargs):
                calls["n"] += 1
                return original(*args, **kwargs)

            lic_module.build_response_generation_outcome = _counting
            try:
                for _ in range(10):
                    lic.get_last_conversation_response()
                    lic.get_last_response_generation_result()
                self.assertEqual(calls["n"], 0)
            finally:
                lic_module.build_response_generation_outcome = original
        finally:
            tmpdir.cleanup()

    def test_response_text_unchanged_by_reads(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            text_before = lic.get_last_conversation_response().response_text
            generated_before = lic.get_last_response_generation_result().generated_text

            for _ in range(10):
                lic.get_last_conversation_response()
                lic.get_last_response_generation_result()

            self.assertEqual(lic.get_last_conversation_response().response_text, text_before)
            self.assertEqual(
                lic.get_last_response_generation_result().generated_text, generated_before)
        finally:
            tmpdir.cleanup()


class TestReadOnlyContractAcrossFullRecoverySequence(unittest.TestCase):
    """5: SUCCESS -> FAILURE -> SUCCESS - interleaved reads at every step
    disturb neither the current step's objects/side-state nor any
    earlier step's already-returned objects."""

    def test_recovery_sequence_read_only(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            original_backend = lic.backend

            _generate_ordinary(core, text="tell me about xyzzy")
            step1_conv = lic.get_last_conversation_response()
            step1_outcome = lic.get_last_response_generation_result()
            step1_conv_snap = _snapshot_response_object(step1_conv)
            step1_outcome_snap = _snapshot_response_object(step1_outcome)
            for _ in range(5):
                lic.get_last_conversation_response()
                lic.get_last_response_generation_result()

            _generate_failure(core)
            step2_side_before = _snapshot_side_state(lic)
            for _ in range(5):
                lic.get_last_conversation_response()
                lic.get_last_response_generation_result()
            _assert_side_state_unchanged(self, lic, step2_side_before)
            # earlier step's objects, read again, are still exactly as
            # they were - a later generation never rewrites them
            self.assertEqual(_snapshot_response_object(step1_conv), step1_conv_snap)
            self.assertEqual(_snapshot_response_object(step1_outcome), step1_outcome_snap)

            _restore_working_backend(core, original_backend)
            _generate_ordinary(core, text="tell me about plugh")
            step3_conv = lic.get_last_conversation_response()
            step3_outcome = lic.get_last_response_generation_result()
            step3_side_before = _snapshot_side_state(lic)
            for _ in range(5):
                lic.get_last_conversation_response()
                lic.get_last_response_generation_result()
            _assert_side_state_unchanged(self, lic, step3_side_before)

            self.assertIs(lic.get_last_conversation_response(), step3_conv)
            self.assertIs(lic.get_last_response_generation_result(), step3_outcome)
            self.assertEqual(_snapshot_response_object(step1_conv), step1_conv_snap)
            self.assertEqual(_snapshot_response_object(step1_outcome), step1_outcome_snap)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
