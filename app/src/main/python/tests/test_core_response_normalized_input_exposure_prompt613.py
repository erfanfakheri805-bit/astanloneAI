"""
Tests for Prompt 613 - Expose `normalized_input` Through Core's Public
Last-Response State.

Chain now covered end to end:
    LanguageUnderstandingResult.normalized_input        (609)
    -> ResponsePlan.normalized_input                    (609)
    -> ResponseGenerationContext.normalized_input        (610)
    -> ResponseGenerationOutcome.normalized_input         (611)
    -> ConversationResponse.normalized_input               (612)
    -> Core.get_last_conversation_response().normalized_input
    -> Core.get_last_response_normalized_input()          (this prompt)

Mirrors the existing `last_response_correction_usable` pattern (Prompts
579-584/607/608) exactly: `self.last_response_normalized_input` is
refreshed once, immediately after `self.last_conversation_response` is
(re)cached, at every existing site that already does so
(`_handle_conversation`'s step "1d" and the explicit
`generate_language_response()` entry point) - a straight, backward-
compatible forward of `self.last_conversation_response.normalized_input`
via `_refresh_last_response_normalized_input()`, exposed through the new
`get_last_response_normalized_input()`. Nothing about the returned reply
text, correction handling, routing, or generation behavior changes; no
text is re-normalized here.

Covers (per Prompt 613 requirement 11):
    1. correction-aware/normalized response publishes the expected
       normalized input
    2. an ordinary response does not retain a previous normalized value
    3. success -> failure clears/does not leak stale normalized input
    4. failure -> normalized recovery publishes the new value
    5. both Core response-generation cache paths refresh consistently
    6. reset_context() clears the Core-level value
    7. repeated getter reads are read-only and stable
    8. legacy response objects without the field safely produce None
    9. exact object/value correspondence with
       last_conversation_response.normalized_input

Run directly:
    python -m unittest tests.test_core_response_normalized_input_exposure_prompt613 -v
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


def _assert_normalized_synced(testcase, core):
    """The getter always agrees with the currently cached
    ConversationResponse's own `normalized_input` field - the same
    invariant Prompt 583's `_assert_synced` establishes for
    `last_response_correction_usable`."""
    conversation = core.get_last_conversation_response()
    if conversation is None:
        testcase.assertIsNone(core.get_last_response_normalized_input())
    else:
        testcase.assertEqual(
            core.get_last_response_normalized_input(),
            getattr(conversation, "normalized_input", None))


def _generate_with_injected_late_failure_via_core(core, understanding):
    restore = _inject_outcome_build_failure()
    try:
        return core.generate_language_response(understanding)
    finally:
        restore()


class TestCorrectionAwareResponsePublishesNormalizedInput(unittest.TestCase):
    """1: a real, correction-aware response publishes the expected
    normalized input at the Core boundary, through both cache paths."""

    def test_via_generate_language_response(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(understanding)
            expected = core.get_last_conversation_response().normalized_input
            self.assertIsNotNone(expected)
            self.assertEqual(core.get_last_response_normalized_input(), expected)
            self.assertEqual(core.last_response_normalized_input, expected)
        finally:
            tmpdir.cleanup()

    def test_via_process_input_real_conversation_path(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("  tell   me about xyzzy  ")
            expected = core.get_last_conversation_response().normalized_input
            self.assertEqual(core.get_last_response_normalized_input(), expected)
        finally:
            tmpdir.cleanup()

    def test_matches_understanding_normalized_input(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            expected_from_understanding = understanding.normalized_input
            core.generate_language_response(understanding)
            self.assertEqual(
                core.get_last_response_normalized_input(), expected_from_understanding)
        finally:
            tmpdir.cleanup()


class TestOrdinaryResponseDoesNotRetainPreviousValue(unittest.TestCase):
    """2: an ordinary response after a normalized one reflects only the
    CURRENT response - never a leftover from the previous turn."""

    def test_new_response_overwrites_previous_normalized_value(self):
        core, tmpdir = _make_core()
        try:
            first = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(first)
            first_value = core.get_last_response_normalized_input()
            self.assertIsNotNone(first_value)

            second = _unusable_understanding(core, text="  totally   different text  ")
            core.generate_language_response(second)
            second_value = core.get_last_response_normalized_input()

            self.assertNotEqual(second_value, first_value)
            _assert_normalized_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestSuccessThenFailureDoesNotLeakStaleValue(unittest.TestCase):
    """3: a successful normalized response followed by an injected
    late-stage failure never leaks the earlier value."""

    def test_success_then_failure(self):
        core, tmpdir = _make_core()
        try:
            first = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(first)
            first_value = core.get_last_response_normalized_input()
            self.assertIsNotNone(first_value)

            _generate_with_injected_late_failure_via_core(
                core, _unusable_understanding(core))
            self.assertIsNone(core.get_last_conversation_response().response_text)
            after_failure = core.get_last_response_normalized_input()

            self.assertNotEqual(after_failure, first_value)
            _assert_normalized_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestFailureThenNormalizedRecovery(unittest.TestCase):
    """4: an injected late-stage failure followed by a real, normalized
    successful response publishes the new value."""

    def test_failure_then_recovery(self):
        core, tmpdir = _make_core()
        try:
            _generate_with_injected_late_failure_via_core(
                core, _unusable_understanding(core))
            self.assertIsNone(core.get_last_conversation_response().response_text)
            _assert_normalized_synced(self, core)

            recovery = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(recovery)
            recovered_value = core.get_last_response_normalized_input()

            self.assertIsNotNone(recovered_value)
            self.assertEqual(
                recovered_value, core.get_last_conversation_response().normalized_input)
        finally:
            tmpdir.cleanup()


class TestBothCachePathsRefreshConsistently(unittest.TestCase):
    """5: both existing Core response-generation cache paths
    (_handle_conversation's "1d" via process_input(), and the explicit
    generate_language_response() entry point) refresh the new state
    consistently."""

    def test_process_input_path(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("  good   morning  ")
            _assert_normalized_synced(self, core)
            self.assertIsNotNone(core.get_last_response_normalized_input())
        finally:
            tmpdir.cleanup()

    def test_generate_language_response_path(self):
        # _unusable_understanding's manually-built ResponsePlan (Prompt
        # 576 helper) does not pass normalized_input, so this path's
        # response legitimately carries None here - the point of this
        # test is only that the Core-level getter stays in sync with
        # whatever last_conversation_response.normalized_input actually
        # is, on this cache path, not that it is non-None.
        core, tmpdir = _make_core()
        try:
            understanding = _unusable_understanding(core, text="  good   morning  ")
            core.generate_language_response(understanding)
            _assert_normalized_synced(self, core)

            # The same cache path with a plan that DOES carry
            # normalized_input (the usable helper) does publish it.
            usable = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(usable)
            _assert_normalized_synced(self, core)
            self.assertIsNotNone(core.get_last_response_normalized_input())
        finally:
            tmpdir.cleanup()


class TestResetContextClearsTheValue(unittest.TestCase):
    """6: reset_context() clears the new Core-level value to its safe
    default (None), the same convention Prompt 581 established for
    last_response_correction_usable."""

    def test_reset_clears_value_but_leaves_conversation_response_untouched(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(understanding)
            cached_conversation = core.get_last_conversation_response()
            self.assertIsNotNone(core.get_last_response_normalized_input())

            core.reset_context()

            # last_conversation_response is deliberately untouched by
            # reset (same convention as last_response_correction_usable).
            self.assertIs(core.get_last_conversation_response(), cached_conversation)
            self.assertIsNotNone(cached_conversation.normalized_input)
            # ...yet the getter itself must not leak that stale value.
            self.assertIsNone(core.get_last_response_normalized_input())
            self.assertIsNone(core.last_response_normalized_input)
        finally:
            tmpdir.cleanup()

    def test_reset_then_new_response_publishes_fresh_value(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("  good   morning  ")
            core.reset_context()
            self.assertIsNone(core.get_last_response_normalized_input())

            core.process_input("  tell   me about xyzzy  ")
            self.assertIsNotNone(core.get_last_response_normalized_input())
            _assert_normalized_synced(self, core)
        finally:
            tmpdir.cleanup()


class TestRepeatedReadsAreReadOnlyAndStable(unittest.TestCase):
    """7: repeated getter reads never mutate state and always agree."""

    def test_repeated_getter_calls_are_stable(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(understanding)
            first = core.get_last_response_normalized_input()
            second = core.get_last_response_normalized_input()
            third = core.get_last_response_normalized_input()
            self.assertIsNotNone(first)
            self.assertEqual(first, second)
            self.assertEqual(second, third)
            # Reading repeatedly never changes the cached conversation
            # response identity either.
            conv_first = core.get_last_conversation_response()
            core.get_last_response_normalized_input()
            self.assertIs(core.get_last_conversation_response(), conv_first)
        finally:
            tmpdir.cleanup()

    def test_fresh_core_returns_none_before_any_message(self):
        core, tmpdir = _make_core()
        try:
            self.assertIsNone(core.get_last_conversation_response())
            self.assertIsNone(core.get_last_response_normalized_input())
            self.assertTrue(hasattr(core, "last_response_normalized_input"))
            self.assertIsNone(core.last_response_normalized_input)
        finally:
            tmpdir.cleanup()


class TestLegacyResponseWithoutFieldSafelyReturnsNone(unittest.TestCase):
    """8: a legacy ConversationResponse built before Prompt 612 (no
    normalized_input attribute passed - defaults to None on the class
    itself, so this also covers the getattr fallback for an object that
    truly lacks the attribute) safely produces None rather than raising
    or fabricating a value."""

    def test_directly_constructed_legacy_response_yields_none(self):
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

    def test_object_truly_missing_the_attribute_yields_none(self):
        """A bare object with no `normalized_input` attribute at all -
        the getattr(..., None) fallback path, not merely a defaulted
        constructor argument."""
        core, tmpdir = _make_core()
        try:
            class _BareLegacyResponse(object):
                response_text = "hi"

            core.last_conversation_response = _BareLegacyResponse()
            core._refresh_last_response_normalized_input()
            self.assertIsNone(core.get_last_response_normalized_input())
        finally:
            tmpdir.cleanup()


class TestExactCorrespondenceWithConversationResponse(unittest.TestCase):
    """9: the public Core-level value is exactly
    `last_conversation_response.normalized_input` - no second
    computation, no re-normalization, real object references (never raw
    id() comparisons)."""

    def test_exact_value_correspondence_success(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(understanding)
            conversation = core.get_last_conversation_response()
            self.assertIs(
                conversation, core.language_intelligence.get_last_conversation_response())
            self.assertEqual(
                core.get_last_response_normalized_input(), conversation.normalized_input)
        finally:
            tmpdir.cleanup()

    def test_exact_value_correspondence_failure(self):
        core, tmpdir = _make_core()
        try:
            _generate_with_injected_late_failure_via_core(
                core, _usable_understanding(core))
            conversation = core.get_last_conversation_response()
            self.assertEqual(
                core.get_last_response_normalized_input(),
                getattr(conversation, "normalized_input", None))
        finally:
            tmpdir.cleanup()

    def test_decoys_on_other_fields_do_not_affect_the_getter(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(understanding)
            expected = core.get_last_response_normalized_input()
            real_conversation = core.get_last_conversation_response()

            # Contradictory decoys on unrelated cached state - none of
            # these is what _refresh_last_response_normalized_input()
            # reads.
            core.last_response_generation_result = None
            core.last_language_response = None
            understanding.response_plan = None

            core._refresh_last_response_normalized_input()

            self.assertEqual(core.get_last_response_normalized_input(), expected)
            self.assertIs(core.get_last_conversation_response(), real_conversation)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
