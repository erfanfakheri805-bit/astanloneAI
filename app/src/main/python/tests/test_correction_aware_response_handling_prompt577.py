"""
Tests for Prompt 577 - Correction-Aware Response Generation Handling.

Prompt 576 gave `LearnedResponseDecision` (learned_response_decision.py,
Prompt 437) a `correction_application_result_usable` field, read straight
off the same `ResponsePlan` the decision is already made from. Nothing
that actually HANDLES a `LearnedResponseDecision` could see it yet.

This prompt makes the smallest existing place `LearnedResponseDecision` is
already consumed - `LanguageIntelligenceCore.generate_response()` /
`_learned_response()` (language_intelligence_core.py, Prompt 437) - read
that field off the decision it already made, and forward it, unchanged,
onto the existing `ResponseGenerationOutcome`
(response_generation_outcome.py, Prompt 428) it already builds for every
call - so downstream code already reading that existing outcome structure
(`get_last_response_generation_result()`) can distinguish "a verified
correction application result is available" without a second lookup.

Covers:
    1. usable=True reaches the existing outcome-handling layer
    2. usable=False preserves the previous behavior
    3. missing/legacy plan preserves the previous behavior
    4. ordinary, non-correction messages remain unchanged
    5. existing outcome/decision fields remain intact
    6. no second correction retrieval/selection/application/usability
       computation occurs
    7. backward-compatible construction (new keyword arguments only)
    8. deterministic, repeated behavior

Run directly:
    python -m unittest tests.test_correction_aware_response_handling_prompt577 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence import correction_application_result_usability as _usability_module
from language_intelligence.learned_response_decision import LearnedResponseDecision
from language_intelligence.response_generation import ResponseGenerationResult, STATUS_GENERATED
from language_intelligence.response_generation_outcome import (
    ResponseGenerationOutcome, build_response_generation_outcome, STATUS_SUCCESS,
)
from language_intelligence import language_intelligence_core as _lic_module

from tests.test_correction_aware_response_decision_prompt576 import (
    _make_core, _store_a_correction, _base_plan_kwargs, _applied_result_dict,
    _not_applied_result_dict,
)
from language_intelligence.response_planning import ResponsePlan, STATUS_RESOLVED


def _generated_result(text="hi there"):
    return ResponseGenerationResult(
        status=STATUS_GENERATED, response_text=text, backend_kind="local_model")


class TestUsableTrueReachesOutcomeLayer(unittest.TestCase):
    """1: a real applied correction, produced by the actual correction
    pipeline, makes `correction_application_result_usable=True` visible on
    the existing `ResponseGenerationOutcome` built by
    `generate_response()`."""

    def test_true_reaches_the_outcome_via_real_pipeline(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            self.assertTrue(plan.correction_application_result_usable)
            understanding.response_plan = plan.to_dict()
            lic = core.language_intelligence
            response = lic.generate_response(understanding, context=core.context)
            self.assertTrue(lic.last_learned_response_decision.correction_application_result_usable)
            outcome = lic.get_last_response_generation_result()
            self.assertIsInstance(outcome, ResponseGenerationOutcome)
            self.assertTrue(outcome.correction_application_result_usable)
            self.assertTrue(outcome.to_dict()["correction_application_result_usable"])
            self.assertIsNotNone(response)
        finally:
            tmpdir.cleanup()

    def test_unit_level_build_function_passthrough(self):
        result = _generated_result()
        outcome = build_response_generation_outcome(
            result, correction_application_result_usable=True)
        self.assertTrue(outcome.correction_application_result_usable)
        self.assertEqual(outcome.status, STATUS_SUCCESS)


class TestUsableFalsePreservesPreviousBehavior(unittest.TestCase):
    """2: `False` / a not-applied result leaves the outcome's new field
    False, and leaves the rest of the outcome exactly as before this
    prompt."""

    def test_not_applied_correction_result(self):
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
            outcome = lic.get_last_response_generation_result()
            self.assertFalse(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_build_function_default_is_false(self):
        result = _generated_result()
        outcome = build_response_generation_outcome(result)
        self.assertFalse(outcome.correction_application_result_usable)


class TestMissingOrLegacyPlanPreservesBehavior(unittest.TestCase):
    """3: no plan at all, and a legacy plan dict built before Prompt 574
    (no `correction_application_result_usable` key), both safely default
    the outcome's new field to False - and leave `used`/`reason`/
    `response_text` exactly as before this prompt."""

    def test_no_plan_at_all(self):
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("hello there")
            understanding.response_plan = None
            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)
            outcome = lic.get_last_response_generation_result()
            self.assertFalse(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_legacy_plan_dict_missing_the_key(self):
        core, tmpdir = _make_core()
        try:
            plan = ResponsePlan(
                correction_application_result=_applied_result_dict(), **_base_plan_kwargs())
            legacy = plan.to_dict()
            del legacy["correction_application_result_usable"]
            self.assertNotIn("correction_application_result_usable", legacy)
            understanding = core.understand_language("hello there")
            understanding.response_plan = legacy
            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)
            outcome = lic.get_last_response_generation_result()
            self.assertFalse(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_decision_construction_failure_defaults_to_false(self):
        """A decision that could not be made at all (exception inside
        `decide_learned_response`) leaves `last_learned_response_decision`
        None (existing Prompt 437 behavior) and the new field simply
        defaults to False - it never breaks `generate_response()`."""
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("hello there")
            lic = core.language_intelligence
            with mock.patch.object(
                    _lic_module, "decide_learned_response",
                    side_effect=RuntimeError("boom")):
                response = lic.generate_response(understanding, context=core.context)
            self.assertIsNone(lic.last_learned_response_decision)
            outcome = lic.get_last_response_generation_result()
            self.assertIsNotNone(outcome)
            self.assertFalse(outcome.correction_application_result_usable)
            self.assertIsNotNone(response)
        finally:
            tmpdir.cleanup()


class TestOrdinaryMessagesUnchanged(unittest.TestCase):
    """4: an ordinary message with no correction anywhere in the picture
    behaves exactly as it did before this prompt, with the new field
    simply False."""

    def test_ordinary_message_no_correction(self):
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("hello there")
            lic = core.language_intelligence
            response = lic.generate_response(understanding, context=core.context)
            outcome = lic.get_last_response_generation_result()
            self.assertFalse(outcome.correction_application_result_usable)
            self.assertIsNotNone(response)
        finally:
            tmpdir.cleanup()


class TestExistingFieldsIntact(unittest.TestCase):
    """5: every other outcome field - and the decision's own existing
    fields - are unaffected by this prompt's change."""

    def test_outcome_fields_unaffected(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            lic = core.language_intelligence
            response = lic.generate_response(understanding, context=core.context)
            outcome = lic.get_last_response_generation_result()
            self.assertEqual(outcome.generated_text, response.response_text)
            self.assertEqual(outcome.backend_kind, response.backend_kind)
            self.assertFalse(outcome.fallback_used)
            self.assertIsInstance(outcome.used_verified_correction, bool)
        finally:
            tmpdir.cleanup()

    def test_decision_fields_present(self):
        decision = LearnedResponseDecision(True, "some_reason")
        self.assertTrue(hasattr(decision, "used"))
        self.assertTrue(hasattr(decision, "reason"))
        self.assertTrue(hasattr(decision, "pattern_id"))
        self.assertTrue(hasattr(decision, "correction_application_result_usable"))


class TestNoSecondCorrectionOperationOccurs(unittest.TestCase):
    """6: forwarding the field into the outcome never re-derives
    usability, re-retrieves, re-selects or re-applies a correction."""

    def test_usability_function_not_called_again_during_generate_response(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            lic = core.language_intelligence

            original = _usability_module.is_correction_application_result_usable
            calls = []

            def counting(*args, **kwargs):
                calls.append((args, kwargs))
                return original(*args, **kwargs)

            _usability_module.is_correction_application_result_usable = counting
            try:
                lic.generate_response(understanding, context=core.context)
            finally:
                _usability_module.is_correction_application_result_usable = original
            self.assertEqual(len(calls), 0)
            outcome = lic.get_last_response_generation_result()
            self.assertTrue(outcome.correction_application_result_usable)
        finally:
            tmpdir.cleanup()

    def test_build_outcome_value_equals_decision_value_not_independently_derived(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            plan = core.language_intelligence.plan_response(understanding)
            understanding.response_plan = plan.to_dict()
            lic = core.language_intelligence
            lic.generate_response(understanding, context=core.context)
            decision_value = lic.last_learned_response_decision.correction_application_result_usable
            outcome_value = lic.get_last_response_generation_result().correction_application_result_usable
            self.assertEqual(decision_value, outcome_value)
        finally:
            tmpdir.cleanup()


class TestBackwardCompatibleConstruction(unittest.TestCase):
    """7: existing call sites that construct `ResponseGenerationOutcome`
    or call `build_response_generation_outcome()` without the new keyword
    argument are unaffected."""

    def test_outcome_default_is_false(self):
        outcome = ResponseGenerationOutcome(STATUS_SUCCESS, generated_text="hi")
        self.assertFalse(outcome.correction_application_result_usable)

    def test_outcome_to_dict_has_key(self):
        outcome = ResponseGenerationOutcome(STATUS_SUCCESS, generated_text="hi")
        self.assertIn("correction_application_result_usable", outcome.to_dict())

    def test_build_function_without_new_kwarg(self):
        result = _generated_result()
        outcome = build_response_generation_outcome(result)
        self.assertFalse(outcome.correction_application_result_usable)

    def test_decision_backward_compatible(self):
        decision = LearnedResponseDecision(False, "some_reason", None, "pattern_x")
        self.assertFalse(decision.correction_application_result_usable)


class TestDeterministicRepeatedBehavior(unittest.TestCase):
    """8: the same input always produces the same outcome value,
    repeatedly."""

    def test_repeated_calls_are_identical(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            lic = core.language_intelligence
            values = []
            for _ in range(3):
                understanding = core.understand_language("not dgo, I mean dog.")
                plan = lic.plan_response(understanding)
                understanding.response_plan = plan.to_dict()
                lic.generate_response(understanding, context=core.context)
                values.append(
                    lic.get_last_response_generation_result().correction_application_result_usable)
            self.assertTrue(all(v == values[0] for v in values))
            self.assertTrue(values[0])
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
