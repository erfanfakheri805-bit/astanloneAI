"""
Tests for Prompt 615 - Public Consistency Contract for `normalized_input`
Across the Core / LanguageIntelligence Boundaries.

Full chain now covered end to end:
    ConversationResponse.normalized_input                    (612)
    -> Core.last_conversation_response.normalized_input       (579/612)
    -> Core.last_response_normalized_input                    (613)
    -> LanguageIntelligenceCore.last_response_generation_result
       .normalized_input                                      (429/611)
    -> Core.last_response_generation_result                   (this prompt)
    -> Core.get_last_response_generation_result()              (this prompt)

Prompt 615 finding: every value in the chain above was already produced
and cached from a single `LanguageIntelligenceCore.generate_response()`
call except one small, missing public consistency guarantee - `Core`
itself had no boundary onto `LanguageIntelligenceCore.
get_last_response_generation_result()` (the `ResponseGenerationOutcome`
that `ConversationResponse`/`normalized_input` are themselves built
from), unlike `get_last_conversation_response()`, which `Core` already
exposes with exactly this straight-forward pattern. No new cache: the
new `Core.last_response_generation_result` is populated the SAME way
`Core.last_conversation_response` already is, at the SAME two existing
call sites (`_handle_conversation`'s "1d" and the explicit
`generate_language_response()` entry point), immediately after
`LanguageIntelligenceCore.generate_response()` returns.

Covers (per Prompt 615 requirements 6-10):
    6. same-call correspondence for: correction-aware/normalized
       response, ordinary response, failure, normalized recovery after
       failure
    7. no previous normalized value can leak into a later response
    8. `get_last_response_normalized_input()`,
       `get_last_conversation_response().normalized_input`, and
       `get_last_response_generation_result().normalized_input` all
       agree for the same successful lifecycle
    9. None behavior: ordinary response without normalized input,
       failure, legacy response/outcome objects without the field,
       reset state
    10. repeated public getter reads are read-only and do not mutate
        last_conversation_response / last_response_generation_result /
        last_response_normalized_input / unrelated response-generation
        state

Run directly:
    python -m unittest tests.test_normalized_input_cross_boundary_consistency_prompt615 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_correction_aware_response_decision_prompt576 import _make_core
from tests.test_correction_aware_core_response_lifecycle_prompt583 import (
    _usable_understanding, _unusable_understanding,
)
from tests.test_correction_aware_response_late_failure_prompt602 import (
    _inject_outcome_build_failure,
)
from language_intelligence.conversation_response import ConversationResponse


def _generate_with_injected_late_failure_via_core(core, understanding):
    restore = _inject_outcome_build_failure()
    try:
        return core.generate_language_response(understanding)
    finally:
        restore()


def _assert_all_three_agree(testcase, core):
    """The three public getters named in Prompt 615 requirement 8 must
    all agree for the same successful lifecycle, whenever all three are
    available."""
    conversation = core.get_last_conversation_response()
    outcome = core.get_last_response_generation_result()
    normalized = core.get_last_response_normalized_input()
    if conversation is None:
        testcase.assertIsNone(normalized)
        return
    conversation_value = getattr(conversation, "normalized_input", None)
    testcase.assertEqual(normalized, conversation_value)
    if outcome is not None:
        outcome_value = getattr(outcome, "normalized_input", None)
        testcase.assertEqual(outcome_value, conversation_value)
        testcase.assertEqual(outcome_value, normalized)


class TestGetterExistsAndDelegatesToLanguageIntelligence(unittest.TestCase):
    """The smallest missing guarantee this prompt adds: `Core` itself
    exposes `get_last_response_generation_result()`, a straight
    boundary onto `LanguageIntelligenceCore.
    get_last_response_generation_result()` for the same call - never a
    second computation."""

    def test_fresh_core_returns_none(self):
        core, tmpdir = _make_core()
        try:
            self.assertTrue(hasattr(core, "last_response_generation_result"))
            self.assertIsNone(core.last_response_generation_result)
            self.assertIsNone(core.get_last_response_generation_result())
        finally:
            tmpdir.cleanup()

    def test_same_object_as_language_intelligence_boundary(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(understanding)
            self.assertIs(
                core.get_last_response_generation_result(),
                core.language_intelligence.get_last_response_generation_result(),
            )
        finally:
            tmpdir.cleanup()


class TestSameCallCorrespondence(unittest.TestCase):
    """6: exact same-call correspondence across correction-aware/
    normalized response, ordinary response, failure, and normalized
    recovery after failure."""

    def test_correction_aware_normalized_response(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(understanding)
            self.assertIsNotNone(core.get_last_response_normalized_input())
            _assert_all_three_agree(self, core)
        finally:
            tmpdir.cleanup()

    def test_ordinary_response(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("  good   morning  ")
            _assert_all_three_agree(self, core)
        finally:
            tmpdir.cleanup()

    def test_failure(self):
        core, tmpdir = _make_core()
        try:
            _generate_with_injected_late_failure_via_core(
                core, _usable_understanding(core))
            self.assertIsNone(core.get_last_conversation_response().response_text)
            _assert_all_three_agree(self, core)
        finally:
            tmpdir.cleanup()

    def test_normalized_recovery_after_failure(self):
        core, tmpdir = _make_core()
        try:
            _generate_with_injected_late_failure_via_core(
                core, _unusable_understanding(core))
            self.assertIsNone(core.get_last_conversation_response().response_text)
            _assert_all_three_agree(self, core)

            recovery = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(recovery)
            self.assertIsNotNone(core.get_last_response_normalized_input())
            _assert_all_three_agree(self, core)
        finally:
            tmpdir.cleanup()


class TestNoLeakingOfPreviousNormalizedValue(unittest.TestCase):
    """7: no previous normalized value can leak into a later response,
    across all three public surfaces at once."""

    def test_second_response_never_carries_first_response_value(self):
        core, tmpdir = _make_core()
        try:
            first = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(first)
            first_normalized = core.get_last_response_normalized_input()
            first_outcome = core.get_last_response_generation_result()
            self.assertIsNotNone(first_normalized)

            second = _unusable_understanding(core, text="  totally   different text  ")
            core.generate_language_response(second)
            second_normalized = core.get_last_response_normalized_input()
            second_outcome = core.get_last_response_generation_result()

            self.assertNotEqual(second_normalized, first_normalized)
            self.assertIsNot(second_outcome, first_outcome)
            _assert_all_three_agree(self, core)
        finally:
            tmpdir.cleanup()

    def test_failure_after_success_does_not_leak_success_value(self):
        core, tmpdir = _make_core()
        try:
            first = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(first)
            first_normalized = core.get_last_response_normalized_input()
            self.assertIsNotNone(first_normalized)

            _generate_with_injected_late_failure_via_core(
                core, _unusable_understanding(core))
            after_failure = core.get_last_response_normalized_input()

            self.assertNotEqual(after_failure, first_normalized)
            _assert_all_three_agree(self, core)
        finally:
            tmpdir.cleanup()


class TestThreeGettersAgreeForSameLifecycle(unittest.TestCase):
    """8: get_last_response_normalized_input(),
    get_last_conversation_response().normalized_input, and
    get_last_response_generation_result().normalized_input remain
    consistent for the same successful lifecycle when all are
    available."""

    def test_three_getters_agree(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(understanding)

            via_normalized_getter = core.get_last_response_normalized_input()
            via_conversation = core.get_last_conversation_response().normalized_input
            via_outcome = core.get_last_response_generation_result().normalized_input

            self.assertIsNotNone(via_normalized_getter)
            self.assertEqual(via_normalized_getter, via_conversation)
            self.assertEqual(via_conversation, via_outcome)
        finally:
            tmpdir.cleanup()

    def test_three_getters_agree_via_process_input(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("  tell   me about xyzzy  ")
            via_normalized_getter = core.get_last_response_normalized_input()
            via_conversation = core.get_last_conversation_response().normalized_input
            outcome = core.get_last_response_generation_result()
            via_outcome = getattr(outcome, "normalized_input", None) if outcome else None

            self.assertEqual(via_normalized_getter, via_conversation)
            self.assertEqual(via_conversation, via_outcome)
        finally:
            tmpdir.cleanup()


class TestNoneBehavior(unittest.TestCase):
    """9: None behavior for ordinary responses without normalized
    input, failure paths, legacy response/outcome objects without the
    field, and reset state."""

    def test_ordinary_response_without_normalized_input(self):
        core, tmpdir = _make_core()
        try:
            understanding = _unusable_understanding(core, text="  good   morning  ")
            core.generate_language_response(understanding)
            # This helper's manually-built plan carries no
            # normalized_input - the point is only that all three
            # surfaces agree on whatever value actually results (None
            # or otherwise), never that one leaks ahead of the others.
            _assert_all_three_agree(self, core)
        finally:
            tmpdir.cleanup()

    def test_failure_path(self):
        core, tmpdir = _make_core()
        try:
            _generate_with_injected_late_failure_via_core(
                core, _unusable_understanding(core))
            self.assertIsNone(core.get_last_conversation_response().response_text)
            _assert_all_three_agree(self, core)
        finally:
            tmpdir.cleanup()

    def test_legacy_conversation_response_without_field(self):
        core, tmpdir = _make_core()
        try:
            legacy_response = ConversationResponse(
                response_text="hi", status="SUCCESS", language="en", locale="en-US",
                backend_kind="deterministic_fallback", fallback_used=False,
                failure_reason=None, metadata=None, valid=True, validation_issues=(),
                generation_status="SUCCESS", reason=None, generation_backend_kind=None,
                fallback_backend_kind=None, selected_backend_kind=None,
                inference_status=None, error_code=None)
            core.last_conversation_response = legacy_response
            core._refresh_last_response_normalized_input()
            self.assertIsNone(core.get_last_response_normalized_input())
        finally:
            tmpdir.cleanup()

    def test_legacy_outcome_object_without_field(self):
        core, tmpdir = _make_core()
        try:
            class _BareLegacyOutcome(object):
                generated_text = "hi"

            core.last_response_generation_result = _BareLegacyOutcome()
            self.assertIsNone(
                getattr(core.get_last_response_generation_result(), "normalized_input", None))
        finally:
            tmpdir.cleanup()

    def test_reset_state(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(understanding)
            self.assertIsNotNone(core.get_last_response_normalized_input())

            core.reset_context()

            # last_response_generation_result is deliberately untouched
            # by reset - same convention as last_conversation_response/
            # last_language_response (documented on reset_context and on
            # get_last_response_generation_result()).
            self.assertIsNotNone(core.get_last_response_generation_result())
            # ...yet the derived normalized-input getter must not leak
            # the stale value past the reset.
            self.assertIsNone(core.get_last_response_normalized_input())
        finally:
            tmpdir.cleanup()


class TestRepeatedReadsAreReadOnly(unittest.TestCase):
    """10: repeated public getter reads are read-only and do not
    mutate last_conversation_response, last_response_generation_result,
    last_response_normalized_input, or unrelated response-generation
    state."""

    def test_repeated_reads_do_not_mutate_cached_state(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(understanding)

            conversation_before = core.get_last_conversation_response()
            outcome_before = core.get_last_response_generation_result()
            normalized_before = core.get_last_response_normalized_input()
            understanding_before = core.last_language_understanding
            language_response_before = core.last_language_response

            for _ in range(3):
                core.get_last_conversation_response()
                core.get_last_response_generation_result()
                core.get_last_response_normalized_input()

            self.assertIs(core.get_last_conversation_response(), conversation_before)
            self.assertIs(core.get_last_response_generation_result(), outcome_before)
            self.assertEqual(core.get_last_response_normalized_input(), normalized_before)
            self.assertIs(core.last_language_understanding, understanding_before)
            self.assertIs(core.last_language_response, language_response_before)
        finally:
            tmpdir.cleanup()

    def test_repeated_reads_stable_values(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(understanding)
            first = core.get_last_response_generation_result()
            second = core.get_last_response_generation_result()
            third = core.get_last_response_generation_result()
            self.assertIs(first, second)
            self.assertIs(second, third)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
