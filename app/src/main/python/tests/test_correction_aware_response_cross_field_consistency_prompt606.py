"""
Tests for Prompt 606 - Cross-Field Consistency Among the Three Public
Response-Generation State Fields, Observed Together.

Prompts 603, 604, and 605 each verified ONE publication boundary in
isolation:
    603 - `last_conversation_response` corresponds to the current
          generation's own outcome, never a predecessor's object.
    604 - `last_response_generation_result` corresponds to the current
          generation's own outcome, never a predecessor's object.
    605 - `last_response_generation_validation` corresponds to the
          current generation's own validation, never a predecessor's
          object, and its `.outcome` is the SAME object as
          `last_response_generation_result` for that call (except on
          the Prompt 602 late-failure path, where validation
          independently rebuilds its own outcome while
          `last_response_generation_result` is None - existing,
          unchanged behavior).

This prompt does not re-derive any of that - it observes the THREE
fields TOGETHER, on the same calls, and locks in that they never mix
objects or state from different generations: after any single
`generate_response()` call, all three fields are mutually consistent
with EACH OTHER (not just individually consistent with the call that
produced them).

The traced path (language_intelligence_core.py, `generate_response()`)
is unchanged from Prompts 603-605:
    self.last_response_generation_result = None            # cleared FIRST
    self.last_response_generation_validation = None        # cleared FIRST
    self.last_conversation_response = None                 # cleared FIRST
    response = self._learned_response(...) or self._route_response(...)
    outcome = self._build_outcome(response, ...)            # fresh, local
    self.last_response_generation_result = outcome
    self.last_response_generation_validation = self._validate(response, outcome)
    self.last_conversation_response = self._conversation_response(
        response, outcome, self.last_response_generation_validation)
All three assignments happen in the same call, from the same local
`response`/`outcome` pair, so the three fields are structurally tied
together by construction; this file locks that triple correspondence in
with direct assertions rather than assuming it.

No production code is changed here, per this prompt's requirements
10/11.

Covers:
    1. ordinary success -> ordinary success: after each call, all three
       fields belong to that SAME call (cross-checked against each
       other), and none of the three is the predecessor's object
    2. correction-aware success -> ordinary success: same triple
       cross-check across the transition
    3. ordinary success -> correction-aware success: same triple
       cross-check across the transition
    4. successful response -> injected late failure (Prompt 602): the
       three fields follow their existing (Prompt 602/605) semantics
       TOGETHER - `last_response_generation_result` is None,
       `last_response_generation_validation` is a fresh non-None object
       (not the predecessor's), `last_conversation_response` is a fresh
       object (not the predecessor's) - with no predecessor response
       state (text, usability) leaking into any of the three
    5. late failure -> successful recovery: all three fields are fresh
       for the recovery call, cross-consistent with each other, and
       distinct from both the original predecessor's and the failed
       call's objects
    6. repeated getter reads across all three fields, interleaved, are
       read-only and never change any field or the relationships among
       them

Reuses the Prompt 576 helper (`_make_core`), the Prompt 592 helpers
(`_generate_correction_aware`, `_generate_ordinary`,
`_assert_same_lifecycle`), and the Prompt 602 late-failure injection
helper (`_generate_with_injected_late_failure`) rather than creating any
new production hook. Real object references are compared with
`assertIs` / `assertIsNot` throughout; no raw `id()` comparisons, per
this prompt's requirement 8.

Run directly:
    python -m unittest tests.test_correction_aware_response_cross_field_consistency_prompt606 -v
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


def _snapshot(lic):
    """Read all three public fields together, once, in the fixed order
    the production code assigns them - never re-read individually
    later, so a snapshot always reflects one single moment."""
    return (
        lic.get_last_response_generation_result(),
        lic.get_last_response_generation_validation(),
        lic.get_last_conversation_response(),
    )


def _assert_triple_cross_consistent(test, lic):
    """All three fields, read together, must correspond to the SAME
    current generation: the field-level correspondence already proven
    (Prompts 592/603/604/605) plus validation's `.outcome` being the
    exact same object as `last_response_generation_result`. Returns the
    snapshot for further predecessor-comparison by the caller."""
    outcome, validation, conversation = _snapshot(lic)
    conv2, outcome2 = _assert_same_lifecycle(test, lic)
    test.assertIs(conv2, conversation)
    test.assertIs(outcome2, outcome)
    test.assertIsNotNone(validation)
    test.assertIs(validation.outcome, outcome)
    return outcome, validation, conversation


class TestTripleConsistencyAcrossSuccessTransitions(unittest.TestCase):
    """1, 2, 3: for every successful generation, all three fields
    correspond to the SAME current call and none is the predecessor's
    object."""

    def test_ordinary_then_ordinary(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            step1 = _assert_triple_cross_consistent(self, lic)

            _generate_ordinary(core, text="tell me about plugh")
            step2 = _assert_triple_cross_consistent(self, lic)

            for a, b in zip(step1, step2):
                self.assertIsNot(a, b)
        finally:
            tmpdir.cleanup()

    def test_correction_aware_then_ordinary(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            step1 = _assert_triple_cross_consistent(self, lic)
            self.assertTrue(step1[0].correction_application_result_usable)

            _generate_ordinary(core, text="tell me about xyzzy")
            step2 = _assert_triple_cross_consistent(self, lic)
            self.assertFalse(step2[0].correction_application_result_usable)

            for a, b in zip(step1, step2):
                self.assertIsNot(a, b)
        finally:
            tmpdir.cleanup()

    def test_ordinary_then_correction_aware(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            step1 = _assert_triple_cross_consistent(self, lic)
            self.assertFalse(step1[0].correction_application_result_usable)

            _generate_correction_aware(core)
            step2 = _assert_triple_cross_consistent(self, lic)
            self.assertTrue(step2[0].correction_application_result_usable)

            for a, b in zip(step1, step2):
                self.assertIsNot(a, b)
        finally:
            tmpdir.cleanup()


class TestTripleSemanticsAcrossLateFailure(unittest.TestCase):
    """4: after a successful response, an injected late failure must
    make the three fields follow their existing, individually-proven
    semantics TOGETHER, with no predecessor state leaking into any of
    them - `last_response_generation_result` is None,
    `last_response_generation_validation` is a fresh non-None object
    (independently rebuilt, per Prompt 605), and
    `last_conversation_response` is a fresh object (per Prompt 602/603).
    This does not normalize the None outcome into anything else."""

    def test_successful_response_then_injected_late_failure(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            prev_outcome, prev_validation, prev_conv = _assert_triple_cross_consistent(self, lic)
            self.assertTrue(prev_conv.correction_application_result_usable)

            _generate_with_injected_late_failure(core)
            failed_outcome, failed_validation, failed_conv = _snapshot(lic)

            # existing semantics, held together, unchanged and unnormalized
            self.assertIsNone(failed_outcome)
            self.assertIsNotNone(failed_validation)
            self.assertIsNotNone(failed_conv)

            # none of the three retains the predecessor's object or state
            self.assertIsNot(failed_outcome, prev_outcome)  # vacuous but explicit
            self.assertIsNot(failed_validation, prev_validation)
            self.assertIsNot(failed_conv, prev_conv)
            self.assertIsNot(failed_validation.outcome, prev_validation.outcome)
            self.assertFalse(failed_conv.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestTripleConsistencyOnRecoveryAfterLateFailure(unittest.TestCase):
    """5: after an injected late failure, the recovery call's three
    fields are cross-consistent with each other and distinct from both
    the original predecessor's and the failed call's objects."""

    def test_late_failure_then_successful_recovery(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            original = _assert_triple_cross_consistent(self, lic)

            _generate_with_injected_late_failure(core)
            failed = _snapshot(lic)
            self.assertIsNone(failed[0])

            _generate_ordinary(core, text="tell me about plugh")
            recovered = _assert_triple_cross_consistent(self, lic)
            self.assertFalse(recovered[0].correction_application_result_usable)

            for a, b in zip(original, recovered):
                self.assertIsNot(a, b)
            # failed[0] was None, so only validation/conversation compare meaningfully
            self.assertIsNot(recovered[1], failed[1])
            self.assertIsNot(recovered[2], failed[2])
        finally:
            tmpdir.cleanup()


class TestRepeatedInterleavedReadsAreReadOnly(unittest.TestCase):
    """6: repeated getter reads across all three fields, interleaved in
    various orders, are read-only and never change any field or the
    relationships among them."""

    def test_interleaved_reads_stable_after_ordinary_success(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_ordinary(core, text="tell me about xyzzy")
            outcome_first, validation_first, conv_first = _snapshot(lic)

            for _ in range(5):
                self.assertIs(lic.get_last_conversation_response(), conv_first)
                self.assertIs(lic.get_last_response_generation_validation(), validation_first)
                self.assertIs(lic.get_last_response_generation_result(), outcome_first)

            outcome_again, validation_again, conv_again = _snapshot(lic)
            self.assertIs(outcome_again, outcome_first)
            self.assertIs(validation_again, validation_first)
            self.assertIs(conv_again, conv_first)
            self.assertIs(validation_again.outcome, outcome_again)
        finally:
            tmpdir.cleanup()

    def test_interleaved_reads_stable_after_injected_late_failure(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_correction_aware(core)
            _generate_with_injected_late_failure(core)
            outcome_first, validation_first, conv_first = _snapshot(lic)
            self.assertIsNone(outcome_first)

            for _ in range(5):
                self.assertIs(lic.get_last_response_generation_result(), outcome_first)
                self.assertIs(lic.get_last_conversation_response(), conv_first)
                self.assertIs(lic.get_last_response_generation_validation(), validation_first)

            outcome_again, validation_again, conv_again = _snapshot(lic)
            self.assertIsNone(outcome_again)
            self.assertIs(validation_again, validation_first)
            self.assertIs(conv_again, conv_first)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
