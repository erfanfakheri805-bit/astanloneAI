"""
Tests for Prompt 499 - Expose Verified Correction Usage in Response
Result.

`ResponseGenerationOutcome` (language_intelligence/
response_generation_outcome.py) - the final structured result built from
a `ResponseGenerationResult` and the `ResponseGenerationRequest` it was
produced for - now carries `used_verified_correction` (bool, default
False). Its value is read from the request's existing preparation state
(`request.generation_request["used_verified_correction"]`, Prompt 498,
set where Prompt 497 substitutes the corrected target); it is never
inferred from the mere presence of correction data. Observability only:
`generated_text` and every other field are unchanged.

Covers:
    1. normal response generation -> False
    2. verified correction actually used -> True (every outcome status)
    3. correction data exists but is unusable / not used -> False
    4. value comes from the preparation state, not from object presence
    5. serialization (`to_dict()`); no deserializer exists on the outcome
    6. safe copy behavior (fresh dicts, deepcopy)
    7. every existing outcome field and behavior unchanged
    8. the real generation flow (core) reports False

Run directly:
    python -m unittest tests.test_response_generation_outcome_verified_correction_usage -v
"""

import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult,
    STATUS_GENERATED, STATUS_DEFERRED, STATUS_MODEL_FAILED,
)
from language_intelligence.response_generation_outcome import (
    ResponseGenerationOutcome, build_response_generation_outcome,
    STATUS_SUCCESS, STATUS_FALLBACK, STATUS_FAILED, STATUS_UNRESOLVED,
)
from language_intelligence.response_planning import ResponsePlan, STATUS_RESOLVED
from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
)
from understanding.engine import UnderstandingEngine

from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT
from tests.test_local_inference_response_generation import TextRuntime


def _instruction(**overrides):
    fields = dict(
        source_text="I has a dgo", corrected_text="I has a dog",
        matched_text="dgo", replacement_text="dog", match_count=1)
    fields.update(overrides)
    return VerifiedCorrectionResponseInstruction(**fields)


def _plan():
    return ResponsePlan(
        original_message="hello there", detected_language="english", locale=None,
        status=STATUS_RESOLVED, reason=None, needs_clarification=False,
        response_action=None, response_action_source=None,
        meaning=None, meaning_candidates=[], matched_pattern=None,
        pattern_candidates=[], variables={"topic": "dogs"}, expression_meanings=[],
        active_topic=None, references=[], context=None, required_items=[],
        unresolved_requirements=[], understanding_state={}, warnings=[])


class _PlanUnderstanding:
    def __init__(self):
        self.response_plan = _plan()


class _NoPlanUnderstanding:
    pass


def _request(instruction=None, understanding=None):
    return ResponseGenerationRequest(
        understanding or _PlanUnderstanding(), verified_correction_instruction=instruction)


def _generated():
    return ResponseGenerationResult(
        status=STATUS_GENERATED, response_text="hello there!",
        backend_kind=BACKEND_KIND_LOCAL_MODEL, metadata={"model_id": "m"})


def _fallback():
    return ResponseGenerationResult(
        status=STATUS_MODEL_FAILED, backend_kind=BACKEND_KIND_LOCAL_MODEL,
        reason="failed", error_code="e", inference_status="failed",
        fallback_backend_kind="deterministic_fallback")


def _failed():
    return ResponseGenerationResult(
        status=STATUS_MODEL_FAILED, backend_kind=BACKEND_KIND_LOCAL_MODEL,
        reason="failed", error_code="e", inference_status="failed")


def _deferred():
    return ResponseGenerationResult(status=STATUS_DEFERRED, backend_kind="deterministic_fallback")


RESULTS = (
    (STATUS_SUCCESS, _generated), (STATUS_FALLBACK, _fallback),
    (STATUS_FAILED, _failed), (STATUS_UNRESOLVED, _deferred),
)


class TestNormalGenerationIsFalse(unittest.TestCase):

    def test_request_without_a_correction(self):
        for status, make in RESULTS:
            with self.subTest(status=status):
                outcome = build_response_generation_outcome(make(), request=_request())
                self.assertEqual(outcome.status, status)
                self.assertIs(outcome.used_verified_correction, False)
                self.assertIs(outcome.to_dict()["used_verified_correction"], False)

    def test_no_request_at_all(self):
        for status, make in RESULTS:
            with self.subTest(status=status):
                outcome = build_response_generation_outcome(make())
                self.assertIs(outcome.used_verified_correction, False)

    def test_direct_construction_default_and_coercion(self):
        self.assertIs(ResponseGenerationOutcome(STATUS_UNRESOLVED).used_verified_correction, False)
        self.assertIs(ResponseGenerationOutcome(
            STATUS_UNRESOLVED, used_verified_correction=True).used_verified_correction, True)


class TestVerifiedCorrectionActuallyUsedIsTrue(unittest.TestCase):

    def test_true_for_every_outcome_status(self):
        for status, make in RESULTS:
            with self.subTest(status=status):
                outcome = build_response_generation_outcome(
                    make(), request=_request(_instruction()))
                self.assertEqual(outcome.status, status)
                self.assertIs(outcome.used_verified_correction, True)
                self.assertIs(outcome.to_dict()["used_verified_correction"], True)

    def test_true_matches_the_prepared_input(self):
        request = _request(_instruction())
        self.assertEqual(request.generation_request["original_message"], "I has a dog")
        outcome = build_response_generation_outcome(_generated(), request=request)
        self.assertIs(outcome.used_verified_correction, True)


class TestUnusableOrUnusedCorrectionIsFalse(unittest.TestCase):

    def test_unusable_instruction_values(self):
        blank = _instruction()
        blank.corrected_text = "   "  # bypasses __init__ validation
        for bogus in ({"corrected_text": "I has a dog"}, "I has a dog", 123, object(), blank):
            with self.subTest(bogus=bogus):
                outcome = build_response_generation_outcome(
                    _generated(), request=_request(bogus))
                self.assertIs(outcome.used_verified_correction, False)

    def test_valid_instruction_but_no_plan_means_nothing_was_used(self):
        request = _request(_instruction(), understanding=_NoPlanUnderstanding())
        self.assertIsNone(request.generation_request)
        outcome = build_response_generation_outcome(_generated(), request=request)
        self.assertIs(outcome.used_verified_correction, False)


class TestValueComesFromPreparationState(unittest.TestCase):

    def test_instruction_present_but_preparation_reports_not_used(self):
        class NotUsed(ResponseGenerationRequest):
            @property
            def generation_request(self):
                data = super().generation_request
                data["used_verified_correction"] = False
                return data
        request = NotUsed(_PlanUnderstanding(), verified_correction_instruction=_instruction())
        self.assertIsNotNone(request.verified_correction_instruction)
        outcome = build_response_generation_outcome(_generated(), request=request)
        self.assertIs(outcome.used_verified_correction, False)

    def test_no_instruction_but_preparation_reports_used(self):
        class Used(ResponseGenerationRequest):
            @property
            def generation_request(self):
                data = super().generation_request
                data["used_verified_correction"] = True
                return data
        request = Used(_PlanUnderstanding())
        self.assertIsNone(request.verified_correction_instruction)
        outcome = build_response_generation_outcome(_generated(), request=request)
        self.assertIs(outcome.used_verified_correction, True)

    def test_only_a_real_true_counts(self):
        for value in (None, 1, "True", [True]):
            with self.subTest(value=value):
                class Odd(ResponseGenerationRequest):
                    @property
                    def generation_request(self):
                        data = super().generation_request
                        data["used_verified_correction"] = value
                        return data
                outcome = build_response_generation_outcome(
                    _generated(), request=Odd(_PlanUnderstanding()))
                self.assertIs(outcome.used_verified_correction, False)


class TestSerializationAndCopy(unittest.TestCase):

    def test_to_dict_preserves_the_value(self):
        for used, instruction in ((True, _instruction()), (False, None)):
            with self.subTest(used=used):
                outcome = build_response_generation_outcome(
                    _generated(), request=_request(instruction))
                self.assertIs(outcome.to_dict()["used_verified_correction"], used)

    def test_json_round_trip_of_to_dict_preserves_the_value(self):
        outcome = build_response_generation_outcome(
            _generated(), request=_request(_instruction()))
        restored = json.loads(json.dumps(outcome.to_dict()))
        self.assertEqual(restored, outcome.to_dict())
        self.assertIs(restored["used_verified_correction"], True)

    def test_outcome_has_no_deserializer_or_copy_method(self):
        # documents the existing convention this stage follows: to_dict()
        # is the only serialization, plus copy.deepcopy for copies
        self.assertFalse(hasattr(ResponseGenerationOutcome, "from_dict"))
        self.assertFalse(hasattr(ResponseGenerationOutcome, "copy"))

    def test_deepcopy_preserves_the_value(self):
        outcome = build_response_generation_outcome(
            _generated(), request=_request(_instruction()))
        clone = copy.deepcopy(outcome)
        self.assertIsNot(clone, outcome)
        self.assertIs(clone.used_verified_correction, True)
        self.assertEqual(clone.to_dict(), outcome.to_dict())

    def test_to_dict_is_a_fresh_dict_each_call(self):
        outcome = build_response_generation_outcome(
            _generated(), request=_request(_instruction()))
        first = outcome.to_dict()
        first["used_verified_correction"] = False
        first["metadata"]["model_id"] = "tampered"
        self.assertIs(outcome.to_dict()["used_verified_correction"], True)
        self.assertEqual(outcome.to_dict()["metadata"], {"model_id": "m"})


class TestExistingResultFieldsUnchanged(unittest.TestCase):

    BASE_KEYS = {"status", "generated_text", "backend_kind", "language", "locale",
                 "failure_reason", "fallback_used", "metadata"}

    def test_key_set_is_the_old_keys_plus_the_one_new_key(self):
        outcome = build_response_generation_outcome(_generated())
        # Prompt 577 added one further additive key,
        # `correction_application_result_usable`, the same shape of
        # change this test already covers for Prompt 499's own
        # `used_verified_correction`. Prompt 611 adds one more,
        # `normalized_input`, the same additive shape again.
        self.assertEqual(
            set(outcome.to_dict()),
            self.BASE_KEYS | {"used_verified_correction",
                              "correction_application_result_usable",
                              "normalized_input"})

    def test_all_other_fields_identical_with_and_without_a_correction(self):
        for status, make in RESULTS:
            with self.subTest(status=status):
                plain = build_response_generation_outcome(make(), request=_request()).to_dict()
                corrected = build_response_generation_outcome(
                    make(), request=_request(_instruction())).to_dict()
                self.assertIs(plain.pop("used_verified_correction"), False)
                self.assertIs(corrected.pop("used_verified_correction"), True)
                self.assertEqual(plain, corrected)

    def test_generated_text_is_not_modified(self):
        outcome = build_response_generation_outcome(
            _generated(), request=_request(_instruction()))
        self.assertEqual(outcome.generated_text, "hello there!")
        self.assertNotIn("dog", outcome.generated_text)

    def test_existing_derived_fields_unchanged(self):
        outcome = build_response_generation_outcome(
            _generated(), request=_request(_instruction()))
        self.assertEqual(outcome.status, STATUS_SUCCESS)
        self.assertEqual(outcome.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertIs(outcome.fallback_used, False)
        self.assertEqual(outcome.metadata, {"model_id": "m"})
        self.assertEqual(outcome.language, "english")

    def test_repr_unchanged(self):
        outcome = build_response_generation_outcome(
            _generated(), request=_request(_instruction()))
        self.assertEqual(
            repr(outcome),
            "ResponseGenerationOutcome(status='SUCCESS', "
            "backend_kind='local_model', fallback_used=False)")

    def test_result_request_and_instruction_are_not_mutated(self):
        understanding = _PlanUnderstanding()
        plan_before = copy.deepcopy(understanding.response_plan.to_dict())
        instruction = _instruction()
        instruction_before = instruction.to_dict()
        request = _request(instruction, understanding=understanding)
        result = _generated()
        result_before = copy.deepcopy(result.to_dict())
        context_before = request.generation_context

        build_response_generation_outcome(result, request=request)

        self.assertEqual(result.to_dict(), result_before)
        self.assertEqual(understanding.response_plan.to_dict(), plan_before)
        self.assertEqual(instruction.to_dict(), instruction_before)
        self.assertIs(request.verified_correction_instruction, instruction)
        self.assertEqual(request.generation_context, context_before)


class TestRealGenerationFlowReportsFalse(GuardCase):
    """The core's own generation path never carries a verified
    correction instruction, so its outcome reports False (and is
    otherwise exactly what it was)."""

    def test_core_outcome_is_false(self):
        runtime = TextRuntime(self.config(), MODEL_TEXT)
        core = LanguageIntelligenceCore(LocalLanguageModelBackend(runtime=runtime))
        understanding = DeterministicFallbackBackend(UnderstandingEngine()).understand(MESSAGE)
        outcome = core.generate_response_outcome(understanding)
        self.assertEqual(outcome.status, STATUS_SUCCESS)
        self.assertEqual(outcome.generated_text, MODEL_TEXT)
        self.assertIs(outcome.used_verified_correction, False)
        self.assertIs(core.get_last_response_generation_result().used_verified_correction, False)


if __name__ == "__main__":
    unittest.main()
