"""
Tests for Prompt 588 - Correction-Aware Final Response Object Propagation.

Inspection performed by this prompt: traced the real production path from
`ResponseGenerationOutcome` (response_generation_outcome.py, Prompt 428/577)
into `ConversationResponse` (`build_conversation_response()`,
conversation_response.py, Prompt 431/578), and onward into `Core`'s cached
response state (`core/core.py`: `last_conversation_response`,
`_refresh_last_response_correction_usable()`, Prompt 579/580).

Finding: propagation is already complete and correct at every step.
`build_conversation_response()` reads `correction_application_result_
usable` exactly once, straight off the SAME `outcome` it is already given
(via `getattr(outcome, "correction_application_result_usable", False)`),
and forwards it unchanged onto the returned `ConversationResponse` -
never recomputed from `result`/`request`/`validation`.
`LanguageIntelligenceCore.generate_response()` caches that SAME
`ConversationResponse` as `last_conversation_response`; `Core`
(`_handle_conversation`'s step "1d" and the explicit
`generate_language_response()` entry point) then reads it straight off
that cache via `get_last_conversation_response()`, caches it again as its
own `last_conversation_response`, and refreshes
`last_response_correction_usable` from that SAME object via
`_refresh_last_response_correction_usable()` - which
`get_last_response_correction_usable()` then simply returns. No missing
propagation or re-derivation was found, so no production code was changed
(Prompt 588 requirement 6) - this file is the smallest regression coverage
proving that the final handoff (outcome -> ConversationResponse -> Core
cache -> public getter) holds end to end.

Chain covered end to end by this file:
    ResponseGenerationOutcome.correction_application_result_usable  (577)
    -> ConversationResponse.correction_application_result_usable    (578)
    -> Core.last_conversation_response.correction_application_
       result_usable                                                (579)
    -> Core.get_last_response_correction_usable()                   (580)

Covers:
    1. True propagates from outcome into ConversationResponse
    2. False propagates the same way
    3. legacy/missing outcome field stays False
    4. Core's cached last_conversation_response carries the same value
    5. Core.get_last_response_correction_usable() stays synchronized with
       Core.get_last_conversation_response()
    6. response text is unchanged at every stage
    7. no mutation or recomputation of the source outcome

Reuses the existing Prompt 576-580 test helpers (`_make_core`,
`_store_a_correction`, `_base_plan_kwargs`, `_applied_result_dict`,
`_not_applied_result_dict`) rather than duplicating that infrastructure.

Run directly:
    python -m unittest tests.test_correction_aware_final_response_propagation_prompt588 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.conversation_response import (
    ConversationResponse, build_conversation_response,
)
from language_intelligence.response_generation import ResponseGenerationResult, STATUS_GENERATED
from language_intelligence.response_generation_outcome import (
    ResponseGenerationOutcome, build_response_generation_outcome, STATUS_SUCCESS,
)
from language_intelligence.response_planning import ResponsePlan

from tests.test_correction_aware_response_decision_prompt576 import (
    _make_core, _store_a_correction, _base_plan_kwargs,
    _applied_result_dict, _not_applied_result_dict,
)


def _generated_result(text="hi there"):
    return ResponseGenerationResult(
        status=STATUS_GENERATED, response_text=text, backend_kind="local_model")


class TestTruePropagatesFromOutcomeToConversationResponse(unittest.TestCase):
    """1: outcome -> ConversationResponse, unit level and via the real
    correction pipeline through Core."""

    def test_unit_level_passthrough(self):
        result = _generated_result("About python.")
        outcome = build_response_generation_outcome(
            result, correction_application_result_usable=True)
        self.assertTrue(outcome.correction_application_result_usable)

        conversation = build_conversation_response(result, outcome=outcome)
        self.assertIsInstance(conversation, ConversationResponse)
        self.assertTrue(conversation.correction_application_result_usable)
        self.assertEqual(conversation.response_text, "About python.")

    def test_real_correction_pipeline_reaches_conversation_response(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            self.assertTrue(plan.correction_application_result_usable)
            understanding.response_plan = plan.to_dict()
            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)
            conversation = lic.get_last_conversation_response()
            self.assertIsInstance(conversation, ConversationResponse)
            self.assertTrue(conversation.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestFalsePropagatesFromOutcomeToConversationResponse(unittest.TestCase):
    """2: an ordinary/not-applied outcome leaves the field False on the
    built ConversationResponse, and nothing else changes."""

    def test_unit_level_default_is_false(self):
        result = _generated_result()
        outcome = build_response_generation_outcome(result)
        conversation = build_conversation_response(result, outcome=outcome)
        self.assertFalse(conversation.correction_application_result_usable)
        self.assertEqual(conversation.response_text, "hi there")
        self.assertEqual(conversation.status, STATUS_SUCCESS)

    def test_not_applied_correction_result_through_core(self):
        core, tmpdir = _make_core()
        try:
            plan = ResponsePlan(
                correction_application_result=_not_applied_result_dict(),
                **_base_plan_kwargs())
            self.assertFalse(plan.correction_application_result_usable)
            understanding = core.understand_language("hello there")
            understanding.response_plan = plan.to_dict()
            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)
            conversation = lic.get_last_conversation_response()
            self.assertFalse(conversation.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestLegacyOrMissingOutcomeFieldStaysFalse(unittest.TestCase):
    """3: an outcome object with no such attribute at all (built before
    Prompt 577) is tolerated exactly like a fresh, unrelated object -
    False, never raised."""

    def test_bare_object_with_no_attribute(self):
        class _LegacyOutcome:
            generated_text = "legacy text"
            status = STATUS_SUCCESS
            language = None
            locale = None
            backend_kind = "local_model"
            fallback_used = False
            failure_reason = None
            metadata = None

        result = _generated_result("legacy text")
        conversation = build_conversation_response(result, outcome=_LegacyOutcome())
        self.assertFalse(conversation.correction_application_result_usable)
        self.assertEqual(conversation.response_text, "legacy text")

    def test_outcome_built_without_the_keyword_argument(self):
        result = _generated_result()
        outcome = build_response_generation_outcome(result)  # keyword omitted
        self.assertFalse(outcome.correction_application_result_usable)
        conversation = build_conversation_response(result, outcome=outcome)
        self.assertFalse(conversation.correction_application_result_usable)


class TestCoreCachedResponseStateCarriesTheValue(unittest.TestCase):
    """4: Core's own last_conversation_response cache (populated via both
    the explicit entry point and the real _handle_conversation path)
    carries the same value the underlying ConversationResponse has."""

    def test_via_explicit_entry_point(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            cached = core.get_last_conversation_response()
            self.assertIsInstance(cached, ConversationResponse)
            self.assertTrue(cached.correction_application_result_usable)
            self.assertIs(cached, core.last_conversation_response)
        finally:
            tmpdir.cleanup()

    def test_false_via_ordinary_process_input(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("tell me about xyzzy")
            cached = core.get_last_conversation_response()
            self.assertIsInstance(cached, ConversationResponse)
            self.assertFalse(cached.correction_application_result_usable)
        finally:
            tmpdir.cleanup()


class TestPublicGetterSynchronization(unittest.TestCase):
    """5: get_last_response_correction_usable() always agrees with
    get_last_conversation_response().correction_application_result_usable -
    a straight read of the same cached object, never an independent
    computation."""

    def test_true_case_synchronized(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            conversation_value = (
                core.get_last_conversation_response().correction_application_result_usable)
            self.assertTrue(conversation_value)
            self.assertEqual(conversation_value, core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()

    def test_false_case_synchronized(self):
        core, tmpdir = _make_core()
        try:
            core.process_input("tell me about xyzzy")
            conversation_value = (
                core.get_last_conversation_response().correction_application_result_usable)
            self.assertFalse(conversation_value)
            self.assertEqual(conversation_value, core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()

    def test_fresh_core_getter_is_none_before_any_message(self):
        core, tmpdir = _make_core()
        try:
            self.assertIsNone(core.get_last_conversation_response())
            self.assertIsNone(core.get_last_response_correction_usable())
        finally:
            tmpdir.cleanup()


class TestResponseTextUnchangedAtEveryStage(unittest.TestCase):
    """6: the rendered/generated response text is identical on the
    ResponseGenerationResult, the ResponseGenerationOutcome, the
    ConversationResponse and Core's cached copy - correction-usable
    exposure never alters it."""

    def test_text_identical_across_all_stages(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            lic = core.language_intelligence
            result = lic.generate_response(understanding, context=core.context)
            outcome = lic.get_last_response_generation_result()
            conversation = lic.get_last_conversation_response()
            core.generate_language_response(understanding)
            core_cached = core.get_last_conversation_response()

            self.assertEqual(outcome.generated_text, result.response_text)
            self.assertEqual(conversation.response_text, outcome.generated_text)
            self.assertEqual(core_cached.response_text, conversation.response_text)
        finally:
            tmpdir.cleanup()


class TestNoMutationOrRecomputationOfSourceOutcome(unittest.TestCase):
    """7: building a ConversationResponse from an outcome never writes
    back to that outcome, and repeated builds/reads are deterministic."""

    def test_outcome_untouched_by_build_conversation_response(self):
        result = _generated_result("About python.")
        outcome = build_response_generation_outcome(
            result, correction_application_result_usable=True)
        before = outcome.to_dict()

        build_conversation_response(result, outcome=outcome)

        after = outcome.to_dict()
        self.assertEqual(before, after)
        self.assertTrue(outcome.correction_application_result_usable)

    def test_repeated_builds_are_identical(self):
        result = _generated_result("About python.")
        outcome = build_response_generation_outcome(
            result, correction_application_result_usable=True)
        first = build_conversation_response(result, outcome=outcome)
        second = build_conversation_response(result, outcome=outcome)
        self.assertEqual(
            first.correction_application_result_usable,
            second.correction_application_result_usable)
        self.assertEqual(first.response_text, second.response_text)

    def test_core_state_deterministic_across_repeated_reads(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            core.generate_language_response(understanding)
            first = core.get_last_response_correction_usable()
            second = core.get_last_response_correction_usable()
            third = core.get_last_response_correction_usable()
            self.assertEqual((first, second, third), (True, True, True))
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
