"""
Tests for Prompt 590 - Public LanguageIntelligenceCore Response-State
Contract Stability.

Inspection performed by this prompt: re-examined the Prompt 589 tests and
the current `LanguageIntelligenceCore.get_last_conversation_response()` /
`get_last_response_generation_result()` implementations
(language_intelligence_core.py). Both getters are plain attribute reads
(`return self.last_conversation_response` /
`return self.last_response_generation_result`) with no computation, no
mutation, and no side effect - repeated calls between two
`generate_response()` calls always return the SAME cached object, and
reading one getter never touches the other's stored state. This already
satisfies every requirement below, so no production code was changed
(Prompt 590 requirements 7/8/9) - this file is the smallest regression
coverage proving that stability end to end.

Covers:
    1. repeated calls to each public getter return the identical object
       (`is`, not just `==`) across multiple reads with no
       `generate_response()` call in between - proving no recomputation
    2. neither getter's returned object is mutated by reading it, and the
       correction-aware field's value stays fixed across repeated reads
    3. the state transition across three consecutive
       generate_response() calls - correction-aware, ordinary,
       correction-aware again - reports the correct value at each step,
       and no earlier step's object survives past its own call
    4. calling one getter repeatedly never changes what the OTHER getter
       reports
    5. both getters are None before the first generate_response() call,
       and after Core.reset_context() a subsequent ordinary
       generate_response() call still reports False through both
    6. response text is identical across repeated reads of either getter
       and is unaffected by how many times either getter is called

Reuses the existing Prompt 576 test helpers (`_make_core`,
`_store_a_correction`) and the Prompt 589 `_plan_with_correction` helper
pattern rather than duplicating that infrastructure.

Run directly:
    python -m unittest tests.test_correction_aware_public_response_state_stability_prompt590 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.conversation_response import ConversationResponse
from language_intelligence.response_generation_outcome import ResponseGenerationOutcome

from tests.test_correction_aware_response_decision_prompt576 import (
    _make_core, _store_a_correction,
)


def _plan_with_correction(understanding, core):
    plan = core.language_intelligence.plan_response(understanding)
    understanding.response_plan = plan.to_dict()
    return plan


def _generate_correction_aware(core):
    """Store a correction, understand a correcting message, plan it, and
    generate the response through LanguageIntelligenceCore directly."""
    _store_a_correction(core.language_learning, "dgo", "dog")
    understanding = core.understand_language("not dgo, I mean dog.")
    _plan_with_correction(understanding, core)
    core.language_intelligence.generate_response(understanding, context=core.context)


def _generate_ordinary(core, text="tell me about xyzzy"):
    understanding = core.understand_language(text)
    core.language_intelligence.generate_response(understanding, context=core.context)


class TestRepeatedCallsReturnSameObjectNoRecomputation(unittest.TestCase):
    """1: repeated getter calls with no intervening generate_response()
    return the identical cached object every time."""

    def test_conversation_response_getter_stable_identity(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            first = lic.get_last_conversation_response()
            second = lic.get_last_conversation_response()
            third = lic.get_last_conversation_response()
            self.assertIs(first, second)
            self.assertIs(second, third)
        finally:
            tmpdir.cleanup()

    def test_response_generation_result_getter_stable_identity(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            first = lic.get_last_response_generation_result()
            second = lic.get_last_response_generation_result()
            third = lic.get_last_response_generation_result()
            self.assertIs(first, second)
            self.assertIs(second, third)
        finally:
            tmpdir.cleanup()


class TestNoMutationAndFixedCorrectionValueAcrossReads(unittest.TestCase):
    """2: reading either getter repeatedly never changes the correction-
    aware field's value, and the object's own state is unaffected."""

    def test_conversation_response_value_fixed_across_reads(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            values = [
                lic.get_last_conversation_response().correction_application_result_usable
                for _ in range(5)
            ]
            self.assertEqual(values, [True] * 5)
        finally:
            tmpdir.cleanup()

    def test_outcome_value_fixed_across_reads(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            values = [
                lic.get_last_response_generation_result().correction_application_result_usable
                for _ in range(5)
            ]
            self.assertEqual(values, [True] * 5)
        finally:
            tmpdir.cleanup()

    def test_reading_getters_does_not_mutate_underlying_to_dict(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            conversation = lic.get_last_conversation_response()
            before = conversation.to_dict()
            # Read both getters several times, interleaved.
            for _ in range(3):
                lic.get_last_conversation_response()
                lic.get_last_response_generation_result()
            after = conversation.to_dict()
            self.assertEqual(before, after)
        finally:
            tmpdir.cleanup()


class TestStateTransitionAcrossThreeGeneratedResponses(unittest.TestCase):
    """3: correction-aware -> ordinary -> correction-aware again, each
    call's getters report only that call's own value."""

    def test_true_false_true_sequence(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence

            _generate_correction_aware(core)
            first_conversation = lic.get_last_conversation_response()
            first_outcome = lic.get_last_response_generation_result()
            self.assertTrue(first_conversation.correction_application_result_usable)
            self.assertTrue(first_outcome.correction_application_result_usable)

            _generate_ordinary(core)
            second_conversation = lic.get_last_conversation_response()
            second_outcome = lic.get_last_response_generation_result()
            self.assertFalse(second_conversation.correction_application_result_usable)
            self.assertFalse(second_outcome.correction_application_result_usable)
            self.assertIsNot(second_conversation, first_conversation)
            self.assertIsNot(second_outcome, first_outcome)

            _generate_correction_aware(core)
            third_conversation = lic.get_last_conversation_response()
            third_outcome = lic.get_last_response_generation_result()
            self.assertTrue(third_conversation.correction_application_result_usable)
            self.assertTrue(third_outcome.correction_application_result_usable)
            self.assertIsNot(third_conversation, first_conversation)
            self.assertIsNot(third_conversation, second_conversation)
        finally:
            tmpdir.cleanup()


class TestOneGetterReadDoesNotAlterTheOther(unittest.TestCase):
    """4: repeatedly calling one getter never changes what the other
    getter reports."""

    def test_repeated_conversation_reads_leave_outcome_getter_untouched(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            outcome_before = lic.get_last_response_generation_result()
            for _ in range(10):
                lic.get_last_conversation_response()
            outcome_after = lic.get_last_response_generation_result()
            self.assertIs(outcome_before, outcome_after)
            self.assertTrue(outcome_after.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_repeated_outcome_reads_leave_conversation_getter_untouched(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            conversation_before = lic.get_last_conversation_response()
            for _ in range(10):
                lic.get_last_response_generation_result()
            conversation_after = lic.get_last_conversation_response()
            self.assertIs(conversation_before, conversation_after)
            self.assertTrue(conversation_after.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestBeforeFirstResponseAndAfterResetLifecycle(unittest.TestCase):
    """5: both getters are None before the first generate_response()
    call, and after Core.reset_context() a subsequent ordinary call
    still reports False through both."""

    def test_both_none_before_first_call(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            self.assertIsNone(lic.get_last_conversation_response())
            self.assertIsNone(lic.get_last_response_generation_result())
        finally:
            tmpdir.cleanup()

    def test_false_after_reset_then_ordinary_call(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            self.assertTrue(
                lic.get_last_conversation_response().correction_application_result_usable)

            core.reset_context()
            _generate_ordinary(core)

            self.assertFalse(
                lic.get_last_conversation_response().correction_application_result_usable)
            self.assertFalse(
                lic.get_last_response_generation_result().correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestResponseTextUnaffectedByRepeatedGetterReads(unittest.TestCase):
    """6: response text is identical across repeated reads of either
    getter, unaffected by read count or order."""

    def test_text_stable_across_repeated_reads(self):
        core, tmpdir = _make_core()
        try:
            _generate_correction_aware(core)
            lic = core.language_intelligence
            texts_from_conversation = {
                lic.get_last_conversation_response().response_text for _ in range(4)
            }
            texts_from_outcome = {
                lic.get_last_response_generation_result().generated_text for _ in range(4)
            }
            self.assertEqual(len(texts_from_conversation), 1)
            self.assertEqual(len(texts_from_outcome), 1)
            self.assertEqual(
                texts_from_conversation.pop(), texts_from_outcome.pop())
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
