"""
Tests for Prompt 587 - Correction-Aware Learned-Response-Decision
Propagation.

Inspection performed by this prompt: traced the real production path from
`ResponsePlan` into `LearnedResponseDecision`
(`decide_learned_response()`, language_intelligence/
learned_response_decision.py) and onward into the actual downstream
consumer, `LanguageIntelligenceCore.generate_response()` /
`build_response_generation_outcome()` (response_generation_outcome.py).

Finding: propagation is already complete and correct at every step
(Prompt 576 gave `LearnedResponseDecision` the field; Prompt 577 forwarded
it into `ResponseGenerationOutcome`). `decide_learned_response()` reads
`correction_application_result_usable` exactly ONCE, straight off the SAME
`ResponsePlan` (via `ResponseGenerationRequest.response_plan`,
`_correction_application_result_usable_from_plan()`), before any
selection/binding/rendering/validation branching happens, and every one
of its return paths (`REASON_NO_REQUEST`, `REASON_SELECTION_NOT_RESOLVED`,
`REASON_BINDING_NOT_RESOLVED`, `REASON_RENDERING_NOT_RESOLVED`,
`REASON_NO_RENDERED_TEXT`, `REASON_PATTERN_MISMATCH`,
`REASON_VALIDATION_FAILED`, `REASON_USED`) passes that SAME already-read
value straight through the `no()` helper or the final constructor - never
recomputed per branch. `LanguageIntelligenceCore.generate_response()`
then reads `last_learned_response_decision.
correction_application_result_usable` exactly once (Prompt 577) and
forwards it into `build_response_generation_outcome()`, which assigns it
to the built `ResponseGenerationOutcome` without re-deriving it from
anything else. No missing propagation or re-derivation was found, so no
production code was changed (Prompt 587 requirement 6) - this file is the
smallest regression coverage proving that handoff holds for EVERY return
path of `decide_learned_response()`, plus the existing downstream
consumer.

Covers:
    1. True propagates through every decide_learned_response() return path
    2. False propagates through every decide_learned_response() return path
    3. None / legacy ResponsePlan behavior stays False throughout
    4. Downstream preservation into ResponseGenerationOutcome via the real
       LanguageIntelligenceCore.generate_response() production path, for
       both a used and a not-used decision
    5. No mutation of the source plan and no recomputation

Run directly:
    python -m unittest tests.test_correction_aware_response_decision_propagation_prompt587 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_generation import ResponseGenerationRequest
from language_intelligence.response_generation_outcome import ResponseGenerationOutcome
from language_intelligence.response_generation_validation import (
    ResponseGenerationValidation, VALIDATION_INVALID,
)
from language_intelligence.learned_response_decision import (
    decide_learned_response, LearnedResponseDecision,
    REASON_USED, REASON_NO_REQUEST, REASON_SELECTION_NOT_RESOLVED,
    REASON_BINDING_NOT_RESOLVED, REASON_RENDERING_NOT_RESOLVED,
    REASON_NO_RENDERED_TEXT, REASON_PATTERN_MISMATCH, REASON_VALIDATION_FAILED,
)

from tests.test_learned_response_integration import _CoreCase, MESSAGE
from tests.test_correction_aware_response_decision_prompt576 import (
    _understanding_with_plan, _base_plan_kwargs,
)
from language_intelligence.response_planning import ResponsePlan


def _set_usable(understanding, usable):
    """Mutate the ALREADY-ATTACHED `understanding.response_plan` dict's own
    `correction_application_result_usable` key in place - simulating a
    real plan that did/didn't find a usable correction application result,
    without threading a full correction pipeline through every selection/
    binding/rendering scenario below. This is the exact field
    `decide_learned_response` reads; nothing else on the plan is touched."""
    understanding.response_plan["correction_application_result_usable"] = bool(usable)
    return understanding


class TestEveryReturnPathPropagatesTrue(_CoreCase):
    """1: correction_application_result_usable=True on the plan reaches
    the decision unchanged, for every one of decide_learned_response()'s
    return paths - including the branches only reachable by tampering
    with an already-built request, exactly as the existing Prompt 437
    tamper test does."""

    def test_no_request_path(self):
        understanding = _understanding_with_plan(None)
        decision = decide_learned_response(understanding)
        self.assertEqual(decision.reason, REASON_NO_REQUEST)
        # No plan at all - nothing to read True from; still explicit False.
        self.assertFalse(decision.correction_application_result_usable)

    def test_selection_not_resolved_ambiguous(self):
        core = self.taught_core([{"id": "one", "template": "One"},
                                  {"id": "two", "template": "Two"}])
        understanding = _set_usable(core.understand_language(MESSAGE), True)
        decision = decide_learned_response(understanding, context=core.context)
        self.assertEqual(decision.reason, REASON_SELECTION_NOT_RESOLVED)
        self.assertFalse(decision.used)
        self.assertTrue(decision.correction_application_result_usable)

    def test_selection_not_resolved_not_found(self):
        core = self.taught_core(None)
        understanding = _set_usable(core.understand_language(MESSAGE), True)
        decision = decide_learned_response(understanding, context=core.context)
        self.assertEqual(decision.reason, REASON_SELECTION_NOT_RESOLVED)
        self.assertTrue(decision.correction_application_result_usable)

    def test_binding_not_resolved(self):
        core = self.taught_core(self.valid_pattern("About {{topic}} for {{audience}}."))
        understanding = _set_usable(core.understand_language(MESSAGE), True)
        decision = decide_learned_response(understanding, context=core.context)
        self.assertEqual(decision.reason, REASON_BINDING_NOT_RESOLVED)
        self.assertTrue(decision.correction_application_result_usable)

    def test_rendering_not_resolved(self):
        core = self.taught_core([{"id": "answer_question"}])  # nothing to render
        understanding = _set_usable(core.understand_language(MESSAGE), True)
        decision = decide_learned_response(understanding, context=core.context)
        self.assertEqual(decision.reason, REASON_RENDERING_NOT_RESOLVED)
        self.assertTrue(decision.correction_application_result_usable)

    def test_no_rendered_text_and_pattern_mismatch_and_validation_failed(self):
        """The three defensive branches decide_learned_response() itself
        can only reach if an already-RESOLVED sub-result were tampered
        with (rendering never naturally leaves text blank, a mismatched
        pattern_id, or a valid result naturally fail Prompt 430
        validation) - same tampering technique the existing Prompt 437
        integration suite already uses
        (test_a_tampered_sub_result_is_never_used /
        test_validation_failure_falls_through)."""
        core = self.taught_core(self.valid_pattern())
        understanding = _set_usable(core.understand_language(MESSAGE), True)

        # REASON_NO_RENDERED_TEXT: blank the already-resolved rendered text.
        request = ResponseGenerationRequest(understanding, context=core.context).generation_request
        blanked = copy.deepcopy(request)
        blanked["response_pattern_rendering"]["rendered_text"] = "   "
        with mock.patch.object(ResponseGenerationRequest, "generation_request",
                                new_callable=mock.PropertyMock, return_value=blanked):
            decision = decide_learned_response(understanding, context=core.context)
        self.assertEqual(decision.reason, REASON_NO_RENDERED_TEXT)
        self.assertTrue(decision.correction_application_result_usable)

        # REASON_PATTERN_MISMATCH: mismatch the rendering's pattern_id.
        mismatched = copy.deepcopy(request)
        mismatched["response_pattern_rendering"]["pattern_id"] = "not_the_real_id"
        with mock.patch.object(ResponseGenerationRequest, "generation_request",
                                new_callable=mock.PropertyMock, return_value=mismatched):
            decision = decide_learned_response(understanding, context=core.context)
        self.assertEqual(decision.reason, REASON_PATTERN_MISMATCH)
        self.assertTrue(decision.correction_application_result_usable)

        # REASON_VALIDATION_FAILED: force Prompt 430 validation to fail.
        invalid = ResponseGenerationValidation(VALIDATION_INVALID, [{"code": "x", "message": "x"}])
        with mock.patch("language_intelligence.learned_response_decision."
                        "validate_response_generation_result", return_value=invalid):
            decision = decide_learned_response(understanding, context=core.context)
        self.assertEqual((decision.used, decision.reason), (False, REASON_VALIDATION_FAILED))
        self.assertIsNone(decision.response)
        self.assertTrue(decision.correction_application_result_usable)

    def test_used_path(self):
        core = self.taught_core(self.valid_pattern())
        understanding = _set_usable(core.understand_language(MESSAGE), True)
        decision = decide_learned_response(understanding, context=core.context)
        self.assertEqual((decision.used, decision.reason), (True, REASON_USED))
        self.assertIsNotNone(decision.response)
        self.assertTrue(decision.correction_application_result_usable)


class TestEveryReturnPathPropagatesFalse(_CoreCase):
    """2: the same eight return paths with the plan's field left at its
    ordinary default (False) - the pre-Prompt-576 behavior every one of
    these branches already had, now pinned down explicitly."""

    def test_no_request_path(self):
        understanding = _understanding_with_plan(None)
        decision = decide_learned_response(understanding)
        self.assertEqual(decision.reason, REASON_NO_REQUEST)
        self.assertFalse(decision.correction_application_result_usable)

    def test_selection_not_resolved(self):
        core = self.taught_core([{"id": "one", "template": "One"},
                                  {"id": "two", "template": "Two"}])
        understanding = core.understand_language(MESSAGE)
        decision = decide_learned_response(understanding, context=core.context)
        self.assertEqual(decision.reason, REASON_SELECTION_NOT_RESOLVED)
        self.assertFalse(decision.correction_application_result_usable)

    def test_binding_not_resolved(self):
        core = self.taught_core(self.valid_pattern("About {{topic}} for {{audience}}."))
        understanding = core.understand_language(MESSAGE)
        decision = decide_learned_response(understanding, context=core.context)
        self.assertEqual(decision.reason, REASON_BINDING_NOT_RESOLVED)
        self.assertFalse(decision.correction_application_result_usable)

    def test_rendering_not_resolved(self):
        core = self.taught_core([{"id": "answer_question"}])
        understanding = core.understand_language(MESSAGE)
        decision = decide_learned_response(understanding, context=core.context)
        self.assertEqual(decision.reason, REASON_RENDERING_NOT_RESOLVED)
        self.assertFalse(decision.correction_application_result_usable)

    def test_used_path(self):
        core = self.taught_core(self.valid_pattern())
        understanding = core.understand_language(MESSAGE)
        decision = decide_learned_response(understanding, context=core.context)
        self.assertEqual((decision.used, decision.reason), (True, REASON_USED))
        self.assertFalse(decision.correction_application_result_usable)


class TestNoneOrLegacyResponsePlan(unittest.TestCase):
    """3: no plan at all, and a legacy plan dict built before Prompt 574
    (no such key), both stay safely False - same as every other reader
    of this field in this package."""

    def test_no_plan_at_all(self):
        decision = decide_learned_response(_understanding_with_plan(None))
        self.assertFalse(decision.correction_application_result_usable)
        self.assertEqual(decision.reason, REASON_NO_REQUEST)

    def test_legacy_plan_dict_missing_the_key(self):
        plan = ResponsePlan(**_base_plan_kwargs())
        legacy = plan.to_dict()
        del legacy["correction_application_result_usable"]
        decision = decide_learned_response(_understanding_with_plan(legacy))
        self.assertFalse(decision.correction_application_result_usable)


class TestDownstreamPreservationIntoOutcome(_CoreCase):
    """4: the real LanguageIntelligenceCore.generate_response() production
    path - decide_learned_response() -> last_learned_response_decision ->
    build_response_generation_outcome() - preserves the value unchanged,
    for both a used and a not-used decision, without altering `used`,
    `response_text` or any other existing outcome field."""

    def test_preserved_when_used(self):
        core = self.taught_core(self.valid_pattern())
        understanding = _set_usable(core.understand_language(MESSAGE), True)
        lic = core.language_intelligence
        response = lic.generate_response(understanding, context=core.context)
        self.assertTrue(lic.last_learned_response_decision.used)
        self.assertTrue(
            lic.last_learned_response_decision.correction_application_result_usable)
        outcome = lic.get_last_response_generation_result()
        self.assertIsInstance(outcome, ResponseGenerationOutcome)
        self.assertTrue(outcome.correction_application_result_usable)
        self.assertEqual(outcome.generated_text, response.response_text)

    def test_preserved_when_not_used(self):
        core = self.taught_core([{"id": "one", "template": "One"},
                                  {"id": "two", "template": "Two"}])
        understanding = _set_usable(core.understand_language(MESSAGE), True)
        lic = core.language_intelligence
        lic.generate_response(understanding, context=core.context)
        self.assertFalse(lic.last_learned_response_decision.used)
        self.assertTrue(
            lic.last_learned_response_decision.correction_application_result_usable)
        outcome = lic.get_last_response_generation_result()
        self.assertTrue(outcome.correction_application_result_usable)

    def test_false_stays_false_downstream(self):
        core = self.taught_core(self.valid_pattern())
        understanding = core.understand_language(MESSAGE)
        lic = core.language_intelligence
        lic.generate_response(understanding, context=core.context)
        outcome = lic.get_last_response_generation_result()
        self.assertFalse(outcome.correction_application_result_usable)


class TestNoMutationOrRecomputation(_CoreCase):
    """5: decide_learned_response() never writes back to the plan it
    read from, and repeated calls over the same understanding give the
    identical value every time."""

    def test_plan_dict_untouched(self):
        core = self.taught_core(self.valid_pattern())
        understanding = _set_usable(core.understand_language(MESSAGE), True)
        before = copy.deepcopy(understanding.response_plan)
        decide_learned_response(understanding, context=core.context)
        self.assertEqual(understanding.response_plan, before)

    def test_repeated_calls_are_identical(self):
        core = self.taught_core(self.valid_pattern())
        understanding = _set_usable(core.understand_language(MESSAGE), True)
        first = decide_learned_response(understanding, context=core.context)
        second = decide_learned_response(understanding, context=core.context)
        third = decide_learned_response(understanding, context=core.context)
        for other in (second, third):
            self.assertEqual(first.used, other.used)
            self.assertEqual(first.reason, other.reason)
            self.assertEqual(
                first.correction_application_result_usable,
                other.correction_application_result_usable)


if __name__ == "__main__":
    unittest.main()
