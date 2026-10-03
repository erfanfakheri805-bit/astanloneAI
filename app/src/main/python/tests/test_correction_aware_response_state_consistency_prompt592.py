"""
Tests for Prompt 592 - Cross-Getter Consistency Contract Between
`get_last_conversation_response()` and `get_last_response_generation_result()`.

Inspection performed by this prompt: re-traced `LanguageIntelligenceCore.
generate_response()` (language_intelligence_core.py). Within a single call:

    response = self._learned_response(...) or self._route_response(...)
    outcome = self._build_outcome(response, ...)                # from `response`
    self.last_response_generation_result = outcome
    self.last_response_generation_validation = self._validate(response, outcome)
    self.last_conversation_response = self._conversation_response(
        response, outcome, self.last_response_generation_validation)  # from the SAME outcome

`get_last_response_generation_result()`'s outcome and
`get_last_conversation_response()`'s ConversationResponse are built from the
exact same local `response`/`outcome` variables of the SAME call - never
from `self.last_*` re-reads - so the two are structurally incapable of
disagreeing about which generation they belong to. And, as Prompt 591 found,
all three `self.last_*` caches are reset to `None` at the very top of the
method before either object is (re)built, so no previous call's state can
survive into a new one regardless of how that new call turns out (success,
ordinary, correction-aware, or failure).

No production code was changed (Prompt 592 requirements 6/7/8): both
getters already satisfy the consistency contract; this file is the
smallest regression coverage proving it across all four generation
outcomes, plus that reading one getter repeatedly never disturbs the
other's cached object.

Covers:
    1. same-lifecycle consistency: response_text/status/backend_kind/
       correction_application_result_usable agree between the two
       getters, for a successful, ordinary, correction-aware, and a
       genuinely FAILED generation
    2. no previous-generation leakage across a
       correction-aware -> ordinary -> correction-aware -> failure
       sequence: each step's getters report only that step's own values
    3. repeated reads of one getter never mutate or replace the other's
       cached object, including in the failure case
    4. pre-generation / reset behavior stays consistent with the
       Prompt 590-591 contract (both None before the first call; the
       pre-reset object still current immediately after
       Core.reset_context(), before the next generate_response())

Reuses the existing Prompt 576 test helpers (`_make_core`,
`_store_a_correction`), the Prompt 589-591 `_plan_with_correction`/
`_generate_correction_aware`/`_generate_ordinary` helper pattern, and the
`tests.test_local_model_failure_fallback`-style standalone backend
construction for the genuine-failure case, rather than duplicating that
infrastructure.

Run directly:
    python -m unittest tests.test_correction_aware_response_state_consistency_prompt592 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.backend import LanguageIntelligenceBackend
from language_intelligence.conversation_response import ConversationResponse
from language_intelligence.response_generation import (
    ResponseGenerationResult, STATUS_MODEL_FAILED,
)
from language_intelligence.response_generation_outcome import (
    ResponseGenerationOutcome, STATUS_FAILED,
)

from tests.test_correction_aware_response_decision_prompt576 import (
    _make_core, _store_a_correction,
)


def _plan_with_correction(understanding, core):
    plan = core.language_intelligence.plan_response(understanding)
    understanding.response_plan = plan.to_dict()
    return plan


def _generate_correction_aware(core):
    _store_a_correction(core.language_learning, "dgo", "dog")
    understanding = core.understand_language("not dgo, I mean dog.")
    _plan_with_correction(understanding, core)
    core.language_intelligence.generate_response(understanding, context=core.context)


def _generate_ordinary(core, text="tell me about xyzzy"):
    understanding = core.understand_language(text)
    core.language_intelligence.generate_response(understanding, context=core.context)


class _AlwaysFailingBackend(LanguageIntelligenceBackend):
    """A backend that never raises or returns junk - it plays fair and
    returns a genuine STATUS_MODEL_FAILED ResponseGenerationResult, the
    ordinary way a model backend reports it cannot answer."""

    backend_kind = "local_model"

    def __init__(self, inner_understand_backend):
        self._inner = inner_understand_backend

    def understand(self, raw_text, context=None, relevant_context=None,
                    resolved_reference=None, active_topic=None, requested_language=None):
        return self._inner.understand(
            raw_text, context=context, relevant_context=relevant_context,
            resolved_reference=resolved_reference, active_topic=active_topic,
            requested_language=requested_language,
        )

    def generate_response(self, understanding, context=None, **kwargs):
        return ResponseGenerationResult(
            status=STATUS_MODEL_FAILED, response_text=None,
            reason="deliberate test failure", backend_kind=self.backend_kind,
        )


def _generate_failure(core):
    """Swap the core's backend for one that always fails, and generate a
    response for an ordinary (non-correction) message."""
    lic = core.language_intelligence
    lic.backend = _AlwaysFailingBackend(lic.backend)
    understanding = core.understand_language("tell me about xyzzy")
    lic.generate_response(understanding, context=core.context)


def _assert_same_lifecycle(test, lic):
    conversation = lic.get_last_conversation_response()
    outcome = lic.get_last_response_generation_result()
    test.assertIsInstance(conversation, ConversationResponse)
    test.assertIsInstance(outcome, ResponseGenerationOutcome)
    test.assertEqual(conversation.response_text, outcome.generated_text)
    test.assertEqual(conversation.status, outcome.status)
    test.assertEqual(conversation.backend_kind, outcome.backend_kind)
    test.assertEqual(
        conversation.correction_application_result_usable,
        outcome.correction_application_result_usable)
    return conversation, outcome


class TestSameLifecycleConsistencyAcrossOutcomes(unittest.TestCase):
    """1: the two getters agree on every shared field, for each of the
    four generation outcomes."""

    def test_successful_correction_aware_response(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            conversation, outcome = _assert_same_lifecycle(self, core.language_intelligence)
            self.assertTrue(conversation.correction_application_result_usable)
            self.assertTrue(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_successful_ordinary_response(self):
        core, tmpdir = _make_core()
        try:
            _generate_ordinary(core)
            conversation, outcome = _assert_same_lifecycle(self, core.language_intelligence)
            self.assertFalse(conversation.correction_application_result_usable)
            self.assertFalse(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_failed_generation(self):
        core, tmpdir = _make_core()
        try:
            _generate_failure(core)
            conversation, outcome = _assert_same_lifecycle(self, core.language_intelligence)
            self.assertEqual(outcome.status, STATUS_FAILED)
            self.assertIsNone(conversation.response_text)
            self.assertFalse(conversation.correction_application_result_usable)
            self.assertFalse(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestNoPreviousGenerationLeakageAcrossSequence(unittest.TestCase):
    """2: correction-aware -> ordinary -> correction-aware -> failure;
    each step's getters report only that step's own values, never a
    prior step's."""

    def test_four_step_sequence(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_correction_aware(core)
            step1_conv = lic.get_last_conversation_response()
            self.assertTrue(step1_conv.correction_application_result_usable)

            _generate_ordinary(core)
            step2_conv, step2_outcome = _assert_same_lifecycle(self, lic)
            self.assertFalse(step2_conv.correction_application_result_usable)
            self.assertIsNot(step2_conv, step1_conv)

            _generate_correction_aware(core)
            step3_conv, step3_outcome = _assert_same_lifecycle(self, lic)
            self.assertTrue(step3_conv.correction_application_result_usable)
            self.assertIsNot(step3_conv, step1_conv)
            self.assertIsNot(step3_conv, step2_conv)

            _generate_failure(core)
            step4_conv, step4_outcome = _assert_same_lifecycle(self, lic)
            self.assertFalse(step4_conv.correction_application_result_usable)
            self.assertEqual(step4_outcome.status, STATUS_FAILED)
            self.assertIsNot(step4_conv, step3_conv)
            self.assertIsNone(step4_conv.response_text)
        finally:
            tmpdir.cleanup()


class TestRepeatedReadsOfOneGetterNeverDisturbTheOther(unittest.TestCase):
    """3: repeated reads of one getter never mutate or replace the
    other's cached object - including in the failure case."""

    def test_stable_through_repeated_reads_after_success(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            outcome_before = lic.get_last_response_generation_result()
            for _ in range(5):
                lic.get_last_conversation_response()
            outcome_after = lic.get_last_response_generation_result()
            self.assertIs(outcome_before, outcome_after)

            conversation_before = lic.get_last_conversation_response()
            for _ in range(5):
                lic.get_last_response_generation_result()
            conversation_after = lic.get_last_conversation_response()
            self.assertIs(conversation_before, conversation_after)
        finally:
            tmpdir.cleanup()

    def test_stable_through_repeated_reads_after_failure(self):
        core, tmpdir = _make_core()
        try:
            _generate_failure(core)
            lic = core.language_intelligence
            conversation_before = lic.get_last_conversation_response()
            outcome_before = lic.get_last_response_generation_result()
            for _ in range(5):
                lic.get_last_conversation_response()
                lic.get_last_response_generation_result()
            self.assertIs(lic.get_last_conversation_response(), conversation_before)
            self.assertIs(lic.get_last_response_generation_result(), outcome_before)
        finally:
            tmpdir.cleanup()


class TestPreGenerationAndResetConsistency(unittest.TestCase):
    """4: pre-generation and reset behavior stays consistent with the
    Prompt 590-591 contract."""

    def test_both_none_before_first_call(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
        finally:
            tmpdir.cleanup()

    def test_pre_reset_object_still_current_immediately_after_reset(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            pre_reset_conv = lic.get_last_conversation_response()
            pre_reset_outcome = lic.get_last_response_generation_result()

            core.reset_context()

            self.assertIs(lic.get_last_conversation_response(), pre_reset_conv)
            self.assertIs(lic.get_last_response_generation_result(), pre_reset_outcome)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
