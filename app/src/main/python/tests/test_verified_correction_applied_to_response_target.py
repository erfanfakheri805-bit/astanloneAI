"""
Tests for Prompt 500 - Apply Verified Correction to Response Target.

The first behavioral step: when a caller supplies a
`VerifiedCorrectionResponseInstruction` to
`LanguageIntelligenceCore.generate_response(...)`, a backend that
responds to text (`LocalLanguageModelBackend`) responds to the verified
corrected target - exactly as the instruction carries it - instead of the
original text, and the result / outcome report `used_verified_correction`
True. Nothing is looked up, matched or corrected again; the generated
text is whatever the model produced; without a usable correction every
path is exactly what it was.

Covers:
    1. normal path without a correction
    2. valid verified correction path (the model receives the corrected
       target; flags True)
    3. corrected target used exactly
    4. flag True only when the correction was actually used
    5. invalid / missing correction -> existing behavior
    6. no mutation of the understanding / context / instruction
    7. compatibility: default values, legacy call patterns, other backends

Run directly:
    python -m unittest tests.test_verified_correction_applied_to_response_target -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine

from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.local_model_mapping import build_inference_request
from language_intelligence.response_generation import (
    ResponseGenerationResult, STATUS_DEFERRED, STATUS_GENERATED,
)
from language_intelligence.response_generation_outcome import STATUS_SUCCESS
from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
)

from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT
from tests.test_local_inference_response_generation import TextRuntime

CORRECTED = "I has a dog"


def _instruction(**overrides):
    fields = dict(
        source_text="I has a dgo", corrected_text=CORRECTED,
        matched_text="dgo", replacement_text="dog", match_count=1)
    fields.update(overrides)
    return VerifiedCorrectionResponseInstruction(**fields)


def _understanding(text=MESSAGE):
    """A real understanding with a response plan attached (the plan is
    attached by LanguageIntelligenceCore.understand())."""
    core = LanguageIntelligenceCore(DeterministicFallbackBackend(UnderstandingEngine()))
    understanding = core.understand(text)
    assert understanding.response_plan is not None
    return understanding


class _Case(GuardCase):

    def core_and_runtime(self, text=MODEL_TEXT, **runtime_overrides):
        runtime = TextRuntime(self.config(**runtime_overrides), text)
        return LanguageIntelligenceCore(LocalLanguageModelBackend(runtime=runtime)), runtime

    def generate(self, instruction=None, understanding=None, context=None, **runtime_overrides):
        core, runtime = self.core_and_runtime(**runtime_overrides)
        understanding = understanding or _understanding()
        kwargs = {} if instruction is None else {"verified_correction_instruction": instruction}
        result = core.generate_response(understanding, context=context, **kwargs)
        return core, runtime, understanding, result


class TestNormalPathWithoutCorrection(_Case):

    def test_model_responds_to_the_original_text(self):
        _, runtime, understanding, result = self.generate()
        self.assertEqual(runtime.requests[0].user_input, understanding.original_input)
        self.assertEqual(runtime.requests[0].user_input, MESSAGE)

    def test_result_and_outcome_report_false(self):
        core, _, _, result = self.generate()
        self.assertEqual(result.status, STATUS_GENERATED)
        self.assertEqual(result.response_text, MODEL_TEXT)
        self.assertIs(result.used_verified_correction, False)
        self.assertIs(core.get_last_response_generation_result().used_verified_correction, False)

    def test_inference_generation_request_is_the_uncorrected_one(self):
        _, runtime, understanding, _ = self.generate()
        request = runtime.requests[0]
        self.assertEqual(request.generation_request.original_message, MESSAGE)
        self.assertIs(request.generation_request.used_verified_correction, False)


class TestValidVerifiedCorrectionPath(_Case):

    def test_model_responds_to_the_corrected_target(self):
        _, runtime, understanding, result = self.generate(_instruction())
        self.assertEqual(runtime.requests[0].user_input, CORRECTED)
        self.assertNotEqual(runtime.requests[0].user_input, understanding.original_input)

    def test_result_and_outcome_report_true(self):
        core, _, _, result = self.generate(_instruction())
        self.assertIs(result.used_verified_correction, True)
        self.assertIs(result.to_dict()["used_verified_correction"], True)
        outcome = core.get_last_response_generation_result()
        self.assertEqual(outcome.status, STATUS_SUCCESS)
        self.assertIs(outcome.used_verified_correction, True)

    def test_generated_text_is_whatever_the_model_produced(self):
        _, _, _, plain = self.generate()
        _, _, _, corrected = self.generate(_instruction())
        self.assertEqual(corrected.response_text, MODEL_TEXT)
        self.assertEqual(corrected.response_text, plain.response_text)
        self.assertEqual(corrected.status, plain.status)
        self.assertEqual(corrected.backend_kind, BACKEND_KIND_LOCAL_MODEL)

    def test_inference_generation_request_carries_the_corrected_target(self):
        _, runtime, _, _ = self.generate(_instruction())
        request = runtime.requests[0]
        self.assertEqual(request.generation_request.original_message, CORRECTED)
        self.assertIs(request.generation_request.used_verified_correction, True)

    def test_every_other_result_field_matches_the_uncorrected_run(self):
        _, _, _, plain = self.generate()
        _, _, _, corrected = self.generate(_instruction())
        a, b = plain.to_dict(), corrected.to_dict()
        for key in ("metadata",):
            a[key] = {k: v for k, v in (a[key] or {}).items() if k != "request_id"}
            b[key] = {k: v for k, v in (b[key] or {}).items() if k != "request_id"}
        self.assertIs(a.pop("used_verified_correction"), False)
        self.assertIs(b.pop("used_verified_correction"), True)
        self.assertEqual(a, b)

    def test_only_the_response_target_differs_in_the_inference_request(self):
        _, plain_rt, _, _ = self.generate()
        _, corrected_rt, _, _ = self.generate(_instruction())
        plain, corrected = plain_rt.requests[0], corrected_rt.requests[0]
        self.assertEqual(plain.system_prompt, corrected.system_prompt)
        self.assertEqual(plain.conversation, corrected.conversation)
        self.assertEqual(plain.language_context.to_dict(), corrected.language_context.to_dict())
        self.assertEqual(plain.generation_context.to_dict(), corrected.generation_context.to_dict())


class TestCorrectedTargetUsedExactly(_Case):

    def test_text_is_passed_exactly(self):
        texts = ("  padded corrected text  ", "MiXeD CaSe Text", "line one\nline two",
                 "متن اصلاح\u200cشده", "Trailing punctuation!?")
        for text in texts:
            with self.subTest(text=text):
                _, runtime, _, result = self.generate(_instruction(corrected_text=text))
                self.assertEqual(runtime.requests[0].user_input, text)
                self.assertEqual(runtime.requests[0].generation_request.original_message, text)
                self.assertIs(result.used_verified_correction, True)

    def test_source_matched_and_replacement_text_are_not_used(self):
        _, runtime, _, _ = self.generate(_instruction(
            source_text="SRC", corrected_text="CORRECTED", matched_text="MATCH",
            replacement_text="REPL"))
        self.assertEqual(runtime.requests[0].user_input, "CORRECTED")


class TestFlagOnlyWhenActuallyUsed(_Case):

    def test_model_not_ready_means_not_used(self):
        core, runtime = self.core_and_runtime()
        runtime.dependency_ok = False
        result = core.generate_response(
            _understanding(), verified_correction_instruction=_instruction())
        self.assertEqual(runtime.generate_calls, 0)
        self.assertIs(result.used_verified_correction, False)
        self.assertIs(core.get_last_response_generation_result().used_verified_correction, False)

    def test_model_not_ready_with_a_fallback_backend_means_not_used(self):
        runtime = TextRuntime(self.config(), MODEL_TEXT)
        runtime.dependency_ok = False
        core = LanguageIntelligenceCore(
            LocalLanguageModelBackend(runtime=runtime),
            fallback_backend=DeterministicFallbackBackend(UnderstandingEngine()))
        result = core.generate_response(
            _understanding(), verified_correction_instruction=_instruction())
        self.assertEqual(runtime.generate_calls, 0)
        self.assertIs(result.used_verified_correction, False)
        self.assertIs(core.get_last_response_generation_result().used_verified_correction, False)

    def test_deterministic_backend_generates_no_text_so_nothing_is_used(self):
        core = LanguageIntelligenceCore(DeterministicFallbackBackend(UnderstandingEngine()))
        result = core.generate_response(
            _understanding(), verified_correction_instruction=_instruction())
        self.assertEqual(result.status, STATUS_DEFERRED)
        self.assertIsNone(result.response_text)
        self.assertIs(result.used_verified_correction, False)
        self.assertIs(core.get_last_response_generation_result().used_verified_correction, False)

    def test_true_is_reported_only_by_the_backend_that_used_it(self):
        class Recording:
            backend_kind = "recording"

            def __init__(self):
                self.kwargs = None

            def generate_response(self, understanding, context=None, cancellation_token=None,
                                  verified_correction_instruction=None):
                self.kwargs = {"instruction": verified_correction_instruction}
                return ResponseGenerationResult(
                    status=STATUS_GENERATED, response_text="text", backend_kind="recording")
        backend = Recording()
        core = LanguageIntelligenceCore(backend)
        result = core.generate_response(
            _understanding(), verified_correction_instruction=_instruction())
        # the instruction reached the backend, but it did not claim to use it
        self.assertIsNotNone(backend.kwargs["instruction"])
        self.assertIs(result.used_verified_correction, False)
        self.assertIs(core.get_last_response_generation_result().used_verified_correction, False)


class TestInvalidOrMissingCorrection(_Case):

    def _assert_existing_behavior(self, instruction):
        core, runtime, understanding, result = self.generate(instruction)
        self.assertEqual(runtime.requests[0].user_input, understanding.original_input)
        self.assertEqual(runtime.requests[0].generation_request.original_message, MESSAGE)
        self.assertIs(runtime.requests[0].generation_request.used_verified_correction, False)
        self.assertIs(result.used_verified_correction, False)
        self.assertIs(core.get_last_response_generation_result().used_verified_correction, False)
        self.assertEqual(result.response_text, MODEL_TEXT)

    def test_missing_instruction(self):
        self._assert_existing_behavior(None)

    def test_non_instruction_values(self):
        for bogus in ({"corrected_text": CORRECTED}, CORRECTED, 123, object()):
            with self.subTest(bogus=bogus):
                self._assert_existing_behavior(bogus)

    def test_instruction_whose_target_became_blank(self):
        for blank in ("", "   ", "\n\t "):
            with self.subTest(blank=blank):
                instruction = _instruction()
                instruction.corrected_text = blank  # bypasses __init__ validation
                self._assert_existing_behavior(instruction)

    def test_understanding_without_a_plan_uses_no_correction(self):
        class NoPlan:
            original_input = "plain text"
            response_plan = None
        core, runtime = self.core_and_runtime()
        result = core.generate_response(
            NoPlan(), verified_correction_instruction=_instruction())
        self.assertEqual(runtime.requests[0].user_input, "plain text")
        self.assertIs(result.used_verified_correction, False)


class TestNoMutation(_Case):

    def test_understanding_context_and_instruction_unchanged(self):
        understanding = _understanding()
        understanding_before = copy.deepcopy(understanding.to_dict())
        instruction = _instruction()
        instruction_before = instruction.to_dict()
        context = ["ctx"]
        self.generate(instruction, understanding=understanding, context=context)
        self.assertEqual(understanding.to_dict(), understanding_before)
        self.assertEqual(understanding.original_input, MESSAGE)
        self.assertEqual(instruction.to_dict(), instruction_before)
        self.assertEqual(context, ["ctx"])

    def test_repeated_calls_are_deterministic(self):
        understanding = _understanding()
        first = self.generate(_instruction(), understanding=understanding)
        second = self.generate(_instruction(), understanding=understanding)
        self.assertEqual(first[1].requests[0].user_input, second[1].requests[0].user_input)
        self.assertEqual(first[3].to_dict()["used_verified_correction"],
                         second[3].to_dict()["used_verified_correction"])


class TestBackwardCompatibility(_Case):

    def test_result_default_and_serialization(self):
        result = ResponseGenerationResult(status=STATUS_GENERATED, response_text="x")
        self.assertIs(result.used_verified_correction, False)
        self.assertIs(result.to_dict()["used_verified_correction"], False)
        self.assertIs(ResponseGenerationResult(
            status=STATUS_GENERATED, used_verified_correction=True).used_verified_correction, True)
        self.assertEqual(
            repr(result), "ResponseGenerationResult(status='generated', backend_kind=None)")

    def test_build_inference_request_default_is_unchanged(self):
        understanding = _understanding()
        default = build_inference_request(understanding)
        explicit_none = build_inference_request(understanding, response_target=None)
        self.assertEqual(default.user_input, MESSAGE)
        self.assertEqual(explicit_none.user_input, MESSAGE)

    def test_build_inference_request_uses_the_target_exactly(self):
        request = build_inference_request(_understanding(), response_target="  Exact Target  ")
        self.assertEqual(request.user_input, "  Exact Target  ")

    def test_legacy_backend_signature_still_works_when_no_instruction_is_given(self):
        class Legacy:
            backend_kind = "legacy"

            def generate_response(self, understanding, context=None):
                return ResponseGenerationResult(
                    status=STATUS_GENERATED, response_text="legacy", backend_kind="legacy")
        core = LanguageIntelligenceCore(Legacy())
        result = core.generate_response(_understanding())
        self.assertEqual(result.response_text, "legacy")
        self.assertIs(result.used_verified_correction, False)

    def test_existing_call_patterns_without_the_new_argument(self):
        core, runtime = self.core_and_runtime()
        understanding = _understanding()
        first = core.generate_response(understanding)
        second = core.generate_response(understanding, context=None)
        self.assertEqual(first.response_text, second.response_text)
        self.assertEqual(runtime.requests[0].user_input, MESSAGE)


if __name__ == "__main__":
    unittest.main()
