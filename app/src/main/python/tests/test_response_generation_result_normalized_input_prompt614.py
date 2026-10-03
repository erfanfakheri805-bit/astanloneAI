"""
Tests for Prompt 614 - `normalized_input` at the LanguageIntelligenceCore
Public Response-Generation-Result Boundary.

Inspection performed by this prompt (language_intelligence_core.py):

    - `last_response_generation_result` (Prompt 429,
      `get_last_response_generation_result()`) is not a copy or a
      parallel cache: `generate_response()` assigns it the SAME local
      `outcome` object (`ResponseGenerationOutcome`, response_generation_
      outcome.py) that is also passed into `_conversation_response()`
      to build `last_conversation_response` (Prompt 431) - see
      `generate_response()`'s own body:

          outcome = self._build_outcome(...)
          self.last_response_generation_result = outcome
          self.last_response_generation_validation = self._validate(response, outcome)
          self.last_conversation_response = self._conversation_response(
              response, outcome, self.last_response_generation_validation)

    - `ResponseGenerationOutcome.normalized_input` already exists
      (Prompt 611) and is already populated by `_build_outcome()` via
      `build_response_generation_outcome()`, forwarded verbatim from
      `ResponseGenerationContext.normalized_input` (Prompt 610), itself
      forwarded from `LanguageUnderstandingResult.normalized_input`
      (Prompt 609). `ConversationResponse.normalized_input` (Prompt 612)
      is read from that SAME outcome object.

Consequently `get_last_response_generation_result().normalized_input`
already reports the exact same value as
`get_last_conversation_response().normalized_input`, for every
successful and failed generation, with no new state, cache, or
accessor required - per this prompt's requirements 4/5/6 (expose
through the established object rather than duplicating it). No
production code is changed here (requirements 10/11/14): this file
observes and locks in the existing publication path, the same
convention Prompt 604 (`last_response_generation_result` publication
boundary) and Prompt 607 (`last_response_correction_usable` cross-field
lifecycle) already established for sibling fields on this exact same
outcome object.

Covers (per Prompt 614 requirement 9):
    1. normalized response -> ordinary response (fresh value each time,
       never a predecessor's)
    2. ordinary response -> normalized response
    3. normalized response -> injected late failure (no stale leak;
       `last_response_generation_result` becomes None, exactly as
       Prompt 604 already proved for the object as a whole)
    4. failure -> normalized successful recovery
    5. repeated `get_last_response_generation_result()` reads are
       read-only and stable (same object, same `.normalized_input`)
    6. `reset_context()` (Core) leaves this LanguageIntelligenceCore-
       level state untouched - same existing, unreset convention as
       `last_conversation_response` itself (Prompts 581/584)
    7. exact value/object correspondence between
       `get_last_response_generation_result().normalized_input` and
       `get_last_conversation_response().normalized_input` - the same
       outcome object, never a second computation
    8. legacy/no-outcome (None) safety

Run directly:
    python -m unittest tests.test_response_generation_result_normalized_input_prompt614 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_generation_outcome import ResponseGenerationOutcome
from language_intelligence.conversation_response import ConversationResponse

from tests.test_correction_aware_response_decision_prompt576 import _make_core
from tests.test_correction_aware_core_response_lifecycle_prompt583 import (
    _usable_understanding, _unusable_understanding,
)
from tests.test_correction_aware_response_late_failure_prompt602 import (
    _inject_outcome_build_failure,
)


def _assert_normalized_input_synced(testcase, lic):
    """The outcome-level getter and the conversation-response-level
    getter always agree, because both are read from the SAME `outcome`
    object built by this call's `_build_outcome()` - never a second
    computation."""
    outcome = lic.get_last_response_generation_result()
    conversation = lic.get_last_conversation_response()
    if outcome is None:
        testcase.assertIsNone(conversation if conversation is None else
                               getattr(conversation, "normalized_input", None))
    else:
        testcase.assertEqual(
            outcome.normalized_input,
            getattr(conversation, "normalized_input", None))


def _generate_with_injected_late_failure(core, understanding):
    restore = _inject_outcome_build_failure()
    try:
        return core.generate_language_response(understanding)
    finally:
        restore()


class TestNormalizedResponsePublishesExpectedValue(unittest.TestCase):
    """1: a real, correction-aware/normalized response's outcome
    already carries the correct normalized_input at this boundary."""

    def test_value_matches_understanding_normalized_input(self):
        core, tmpdir = _make_core()
        try:
            understanding = _usable_understanding(core, text="  not dgo,   I mean dog.  ")
            core.generate_language_response(understanding)
            lic = core.language_intelligence
            outcome = lic.get_last_response_generation_result()
            self.assertIsInstance(outcome, ResponseGenerationOutcome)
            self.assertEqual(outcome.normalized_input, understanding.normalized_input)
            _assert_normalized_input_synced(self, lic)
        finally:
            tmpdir.cleanup()


class TestNormalizedThenOrdinaryTransition(unittest.TestCase):
    """1/2: consecutive calls each publish only their OWN outcome's
    normalized_input - never a predecessor's, in either direction."""

    def test_normalized_then_ordinary(self):
        core, tmpdir = _make_core()
        try:
            core.generate_language_response(
                _usable_understanding(core, text="  not dgo,   I mean dog.  "))
            lic = core.language_intelligence
            first_outcome = lic.get_last_response_generation_result()
            first_value = first_outcome.normalized_input
            self.assertIsNotNone(first_value)

            core.generate_language_response(
                _unusable_understanding(core, text="  totally   different text  "))
            second_outcome = lic.get_last_response_generation_result()

            self.assertIsNot(second_outcome, first_outcome)
            _assert_normalized_input_synced(self, lic)
        finally:
            tmpdir.cleanup()

    def test_ordinary_then_normalized(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            core.generate_language_response(
                _unusable_understanding(core, text="  good   morning  "))
            first_outcome = lic.get_last_response_generation_result()

            core.generate_language_response(
                _usable_understanding(core, text="  not dgo,   I mean dog.  "))
            second_outcome = lic.get_last_response_generation_result()

            self.assertIsNot(second_outcome, first_outcome)
            self.assertIsNotNone(second_outcome.normalized_input)
            _assert_normalized_input_synced(self, lic)
        finally:
            tmpdir.cleanup()


class TestNormalizedThenFailureDoesNotLeak(unittest.TestCase):
    """3: a normalized successful response followed by an injected
    late-stage failure never retains the earlier outcome/value - the
    same structural guarantee Prompt 604 already proved for the object
    as a whole (`last_response_generation_result` is unconditionally
    reset to None before the new outcome is built)."""

    def test_success_then_failure(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            core.generate_language_response(
                _usable_understanding(core, text="  not dgo,   I mean dog.  "))
            first_outcome = lic.get_last_response_generation_result()
            self.assertIsNotNone(first_outcome.normalized_input)

            _generate_with_injected_late_failure(
                core, _unusable_understanding(core))
            after_failure = lic.get_last_response_generation_result()

            self.assertIsNone(after_failure)
            self.assertIsNone(lic.get_last_conversation_response().response_text)
            _assert_normalized_input_synced(self, lic)
        finally:
            tmpdir.cleanup()


class TestFailureThenNormalizedRecovery(unittest.TestCase):
    """4: an injected late-stage failure followed by a real, normalized
    successful response publishes the new outcome's value."""

    def test_failure_then_recovery(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_with_injected_late_failure(
                core, _unusable_understanding(core))
            self.assertIsNone(lic.get_last_response_generation_result())

            core.generate_language_response(
                _usable_understanding(core, text="  not dgo,   I mean dog.  "))
            recovered = lic.get_last_response_generation_result()

            self.assertIsNotNone(recovered)
            self.assertIsNotNone(recovered.normalized_input)
            _assert_normalized_input_synced(self, lic)
        finally:
            tmpdir.cleanup()


class TestRepeatedReadsAreReadOnlyAndStable(unittest.TestCase):
    """5: repeated getter reads never mutate anything and always agree."""

    def test_repeated_reads_return_the_same_object_and_value(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            core.generate_language_response(
                _usable_understanding(core, text="  not dgo,   I mean dog.  "))
            first = lic.get_last_response_generation_result()
            second = lic.get_last_response_generation_result()
            third = lic.get_last_response_generation_result()

            self.assertIs(first, second)
            self.assertIs(second, third)
            self.assertEqual(first.normalized_input, second.normalized_input)
            self.assertEqual(second.normalized_input, third.normalized_input)
        finally:
            tmpdir.cleanup()


class TestResetContextLeavesThisStateUntouched(unittest.TestCase):
    """6: Core.reset_context() does not clear this LanguageIntelligenceCore-
    level state - same existing, unreset convention as
    `last_conversation_response` itself (Prompts 581/584)."""

    def test_reset_context_does_not_clear_it(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            core.generate_language_response(
                _usable_understanding(core, text="  not dgo,   I mean dog.  "))
            outcome_before = lic.get_last_response_generation_result()
            self.assertIsNotNone(outcome_before.normalized_input)

            core.reset_context()

            outcome_after = lic.get_last_response_generation_result()
            self.assertIs(outcome_after, outcome_before)
            self.assertEqual(outcome_after.normalized_input, outcome_before.normalized_input)
        finally:
            tmpdir.cleanup()


class TestExactCorrespondenceWithConversationResponse(unittest.TestCase):
    """7: get_last_response_generation_result().normalized_input and
    get_last_conversation_response().normalized_input always agree -
    the SAME outcome object, never a second computation, real object
    references (never raw id() comparisons)."""

    def test_same_outcome_object_feeds_both_getters(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            core.generate_language_response(
                _usable_understanding(core, text="  not dgo,   I mean dog.  "))
            outcome = lic.get_last_response_generation_result()
            conversation = lic.get_last_conversation_response()

            self.assertIsInstance(conversation, ConversationResponse)
            self.assertEqual(outcome.normalized_input, conversation.normalized_input)

            # Decoys on unrelated cached state never affect this
            # correspondence - nothing here is recomputed from them.
            core.last_response_generation_result = None
            core.last_language_response = None

            self.assertIs(lic.get_last_response_generation_result(), outcome)
            self.assertEqual(
                lic.get_last_response_generation_result().normalized_input,
                lic.get_last_conversation_response().normalized_input)
        finally:
            tmpdir.cleanup()

    def test_correspondence_holds_on_failure_too(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            _generate_with_injected_late_failure(
                core, _usable_understanding(core, text="  not dgo,   I mean dog.  "))
            self.assertIsNone(lic.get_last_response_generation_result())
            self.assertIsNone(lic.get_last_conversation_response().response_text)
            _assert_normalized_input_synced(self, lic)
        finally:
            tmpdir.cleanup()


class TestNoOutcomeYetIsSafe(unittest.TestCase):
    """8: before any generation, both getters safely report None -
    no fabricated value, no exception."""

    def test_fresh_core_returns_none(self):
        core, tmpdir = _make_core()
        try:
            lic = core.language_intelligence
            self.assertIsNone(lic.get_last_response_generation_result())
            self.assertIsNone(lic.get_last_conversation_response())
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
