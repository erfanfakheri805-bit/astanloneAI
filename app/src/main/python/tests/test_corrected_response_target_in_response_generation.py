"""
Tests for Prompt 496 - Integrate Corrected Response Target into
Response Generation (extended in Prompt 497 - Use Corrected Target as
Response Generation Input, and Prompt 498 - Track Corrected Response
Target Usage: see the last classes in this file).

`ResponseGenerationRequest` (language_intelligence/response_generation.py)
now feeds the existing corrected-response-target pieces into its
existing context-preparation path:

    ResponseGenerationRequest(..., verified_correction_instruction=...)   (Prompt 492)
    with_corrected_response_target(...)                                  (Prompt 494)
    select_corrected_response_target(...)                                (Prompt 495)
        -> `ResponseGenerationRequest.generation_context["corrected_response_target"]`
        -> `ResponseGenerationRequest.selected_response_target`

This stage only makes the already-verified corrected target available
to the response-generation layer. It generates no response text,
rewrites no text, adds no matching, and looks up / applies / learns /
stores no correction. Covers:

    1. normal request without correction -> existing behavior unchanged
       (no selected target; generation_context identical to what
       build_generation_context() alone produces)
    2. request with a valid corrected target -> the target is available
       as the selected target and in generation_context, and every
       other generation_context field is unchanged
    3. invalid / missing corrected target -> existing behavior preserved
    4. no mutation of the request, understanding, plan, or instruction
    5. exact corrected text is preserved
    6. backward compatibility of existing call patterns / properties

Run directly:
    python -m unittest tests.test_corrected_response_target_in_response_generation -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_generation import ResponseGenerationRequest
from language_intelligence.response_generation_context import build_generation_context
from language_intelligence.response_generation_request import (
    BackendGenerationRequest, build_generation_request,
)
from language_intelligence.response_planning import ResponsePlan, STATUS_RESOLVED
from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
)
from language_intelligence.corrected_response_target_context import (
    with_corrected_response_target,
)
from language_intelligence.corrected_response_target_selection import (
    select_corrected_response_target,
)


def _instruction(**overrides):
    fields = dict(
        source_text="I has a dgo",
        corrected_text="I has a dog",
        matched_text="dgo",
        replacement_text="dog",
        match_count=1,
    )
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
    """Minimal stand-in understanding that carries a real ResponsePlan."""

    def __init__(self):
        self.response_plan = _plan()


class _NoPlanUnderstanding:
    """Minimal stand-in with no `response_plan` attribute."""
    pass


def _baseline_context_dict():
    """What the request's generation_context was before this stage."""
    return build_generation_context(_plan()).to_dict()


class TestRequestWithoutCorrection(unittest.TestCase):

    def test_no_selected_target(self):
        request = ResponseGenerationRequest(_PlanUnderstanding())
        self.assertIsNone(request.selected_response_target)

    def test_generation_context_identical_to_existing_behavior(self):
        request = ResponseGenerationRequest(_PlanUnderstanding())
        self.assertEqual(request.generation_context, _baseline_context_dict())
        self.assertIsNone(request.generation_context["corrected_response_target"])

    def test_generation_request_unchanged_for_explicit_none_instruction(self):
        # (Prompt 497 supersedes the Prompt 496 assertion that a usable
        # instruction leaves generation_request unchanged - see
        # TestCorrectedTargetIsResponseGenerationInput below.)
        with_none = ResponseGenerationRequest(_PlanUnderstanding())
        explicit_none = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=None)
        self.assertEqual(with_none.generation_request, explicit_none.generation_request)

    def test_no_plan_request_behaves_as_before(self):
        request = ResponseGenerationRequest(_NoPlanUnderstanding())
        self.assertIsNone(request.response_plan)
        self.assertIsNone(request.generation_context)
        self.assertIsNone(request.generation_request)
        self.assertIsNone(request.selected_response_target)


class TestRequestWithValidCorrectedTarget(unittest.TestCase):

    def test_corrected_target_becomes_selected_target(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        self.assertEqual(request.selected_response_target, "I has a dog")

    def test_corrected_target_available_in_generation_context(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        self.assertEqual(request.generation_context["corrected_response_target"], "I has a dog")

    def test_only_the_corrected_target_field_differs(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        actual = request.generation_context
        expected = _baseline_context_dict()
        self.assertEqual(actual.pop("corrected_response_target"), "I has a dog")
        expected.pop("corrected_response_target")
        self.assertEqual(actual, expected)

    def test_uses_the_existing_attach_and_select_operations(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        base = build_generation_context(_plan())
        via_existing = select_corrected_response_target(
            with_corrected_response_target(base, request))
        self.assertEqual(request.selected_response_target, via_existing)

    def test_no_plan_means_no_context_and_no_selected_target(self):
        # the target lives on ResponseGenerationContext, which needs a plan
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=_instruction())
        self.assertIsNone(request.generation_context)
        self.assertIsNone(request.selected_response_target)

    def test_repeated_calls_are_deterministic_and_independent(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        first = request.generation_context
        second = request.generation_context
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        first["corrected_response_target"] = "tampered"
        self.assertEqual(request.selected_response_target, "I has a dog")
        self.assertEqual(request.generation_context["corrected_response_target"], "I has a dog")


class TestInvalidOrMissingCorrectedTarget(unittest.TestCase):

    def _assert_existing_behavior(self, request):
        self.assertIsNone(request.selected_response_target)
        self.assertEqual(request.generation_context, _baseline_context_dict())
        self.assertIsNone(request.generation_context["corrected_response_target"])

    def test_explicit_none_instruction(self):
        self._assert_existing_behavior(ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=None))

    def test_non_instruction_value(self):
        for bogus in ({"corrected_text": "I has a dog"}, "I has a dog", 123, object()):
            with self.subTest(bogus=bogus):
                self._assert_existing_behavior(ResponseGenerationRequest(
                    _PlanUnderstanding(), verified_correction_instruction=bogus))

    def test_instruction_whose_target_became_blank(self):
        for blank in ("", "   ", "\n\t "):
            with self.subTest(blank=blank):
                instruction = _instruction()
                instruction.corrected_text = blank  # bypasses __init__ validation
                self._assert_existing_behavior(ResponseGenerationRequest(
                    _PlanUnderstanding(), verified_correction_instruction=instruction))


class TestNoMutation(unittest.TestCase):

    def test_request_understanding_plan_and_instruction_unchanged(self):
        understanding = _PlanUnderstanding()
        plan_before = copy.deepcopy(understanding.response_plan.to_dict())
        instruction = _instruction()
        instruction_before = instruction.to_dict()
        request = ResponseGenerationRequest(
            understanding, context="ctx", verified_correction_instruction=instruction)

        request.generation_context
        request.selected_response_target
        request.generation_request

        self.assertIs(request.understanding, understanding)
        self.assertEqual(request.context, "ctx")
        self.assertIs(request.verified_correction_instruction, instruction)
        self.assertEqual(instruction.to_dict(), instruction_before)
        self.assertEqual(understanding.response_plan.to_dict(), plan_before)

    def test_request_without_correction_unchanged(self):
        understanding = _PlanUnderstanding()
        plan_before = copy.deepcopy(understanding.response_plan.to_dict())
        request = ResponseGenerationRequest(understanding)
        request.generation_context
        request.selected_response_target
        self.assertIsNone(request.verified_correction_instruction)
        self.assertEqual(understanding.response_plan.to_dict(), plan_before)


class TestExactCorrectedTextPreserved(unittest.TestCase):

    def test_text_is_returned_exactly(self):
        texts = (
            "  padded corrected text  ",
            "MiXeD CaSe Text",
            "line one\nline two",
            "متن اصلاح\u200cشده",
            "Trailing punctuation!?",
        )
        for text in texts:
            with self.subTest(text=text):
                request = ResponseGenerationRequest(
                    _PlanUnderstanding(),
                    verified_correction_instruction=_instruction(corrected_text=text))
                self.assertEqual(request.selected_response_target, text)
                self.assertEqual(request.generation_context["corrected_response_target"], text)

    def test_source_matched_and_replacement_text_are_not_used_as_target(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(),
            verified_correction_instruction=_instruction(
                source_text="SRC", corrected_text="CORRECTED",
                matched_text="MATCH", replacement_text="REPL"))
        self.assertEqual(request.selected_response_target, "CORRECTED")


class TestBackwardCompatibility(unittest.TestCase):

    def test_existing_call_patterns_still_work(self):
        understanding = _PlanUnderstanding()
        one = ResponseGenerationRequest(understanding)
        two = ResponseGenerationRequest(understanding, "ctx")
        self.assertIs(one.understanding, understanding)
        self.assertEqual(two.context, "ctx")
        self.assertEqual(one.generation_context, two.generation_context)
        self.assertIsNone(one.selected_response_target)
        self.assertIsNone(two.selected_response_target)

    def test_existing_properties_still_return_expected_shapes(self):
        request = ResponseGenerationRequest(_PlanUnderstanding())
        self.assertIsInstance(request.generation_context, dict)
        self.assertIsInstance(request.generation_request, dict)
        self.assertIs(request.response_plan, request.understanding.response_plan)

    def test_repr_unchanged(self):
        understanding = _PlanUnderstanding()
        request = ResponseGenerationRequest(understanding)
        self.assertEqual(
            repr(request), f"ResponseGenerationRequest(understanding={understanding!r})")


# ---------------------------------------------------------------------
# Prompt 497 - Use Corrected Target as Response Generation Input
#
# `ResponseGenerationRequest.generation_request` (the structured input
# handed to response generation) carries the selected corrected target
# in its EXISTING `original_message` field when one is selected; with no
# selected target it is exactly what it was before.
# ---------------------------------------------------------------------

def _baseline_generation_request_dict():
    """What generation_request was before Prompt 497 (no correction)."""
    return ResponseGenerationRequest(_PlanUnderstanding()).generation_request


class TestCorrectedTargetIsResponseGenerationInput(unittest.TestCase):

    def test_normal_request_input_unchanged(self):
        request = ResponseGenerationRequest(_PlanUnderstanding())
        generated = request.generation_request
        self.assertEqual(generated["original_message"], "hello there")
        self.assertEqual(generated, _baseline_generation_request_dict())

    def test_valid_corrected_target_is_the_input(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        self.assertEqual(request.generation_request["original_message"], "I has a dog")

    def test_only_the_existing_input_field_differs(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        actual = request.generation_request
        expected = _baseline_generation_request_dict()
        self.assertEqual(actual.pop("original_message"), "I has a dog")
        expected.pop("original_message")
        # Prompt 498's observability flag is the only other difference.
        self.assertTrue(actual.pop("used_verified_correction"))
        self.assertFalse(expected.pop("used_verified_correction"))
        self.assertEqual(actual, expected)  # no new/parallel input key

    def test_same_target_as_selected_response_target(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        self.assertEqual(
            request.generation_request["original_message"], request.selected_response_target)

    def test_corrected_text_preserved_exactly(self):
        texts = (
            "  padded corrected text  ",
            "MiXeD CaSe Text",
            "line one\nline two",
            "متن اصلاح\u200cشده",
            "Trailing punctuation!?",
        )
        for text in texts:
            with self.subTest(text=text):
                request = ResponseGenerationRequest(
                    _PlanUnderstanding(),
                    verified_correction_instruction=_instruction(corrected_text=text))
                self.assertEqual(request.generation_request["original_message"], text)

    def test_source_matched_and_replacement_text_not_used(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(),
            verified_correction_instruction=_instruction(
                source_text="SRC", corrected_text="CORRECTED",
                matched_text="MATCH", replacement_text="REPL"))
        self.assertEqual(request.generation_request["original_message"], "CORRECTED")

    def test_invalid_or_missing_target_leaves_input_unchanged(self):
        blank_instruction = _instruction()
        blank_instruction.corrected_text = "   "  # bypasses __init__ validation
        candidates = (
            None, {"corrected_text": "I has a dog"}, "I has a dog", 123, object(),
            blank_instruction,
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                request = ResponseGenerationRequest(
                    _PlanUnderstanding(), verified_correction_instruction=candidate)
                self.assertEqual(request.generation_request, _baseline_generation_request_dict())
                self.assertEqual(request.generation_request["original_message"], "hello there")

    def test_no_plan_request_still_has_no_generation_request(self):
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=_instruction())
        self.assertIsNone(request.generation_request)

    def test_generation_context_still_keeps_the_uncorrected_message(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        self.assertEqual(request.generation_context["original_message"], "hello there")
        self.assertEqual(
            request.generation_context["corrected_response_target"], "I has a dog")

    def test_repeated_calls_deterministic_and_independent(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        first = request.generation_request
        second = request.generation_request
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        first["original_message"] = "tampered"
        self.assertEqual(request.generation_request["original_message"], "I has a dog")


class TestGenerationRequestNoMutation(unittest.TestCase):

    def test_request_understanding_plan_instruction_unchanged(self):
        understanding = _PlanUnderstanding()
        plan_before = copy.deepcopy(understanding.response_plan.to_dict())
        instruction = _instruction()
        instruction_before = instruction.to_dict()
        request = ResponseGenerationRequest(
            understanding, context="ctx", verified_correction_instruction=instruction)
        context_before = request.generation_context

        request.generation_request

        self.assertIs(request.understanding, understanding)
        self.assertEqual(request.context, "ctx")
        self.assertIs(request.verified_correction_instruction, instruction)
        self.assertEqual(instruction.to_dict(), instruction_before)
        self.assertEqual(understanding.response_plan.to_dict(), plan_before)
        self.assertEqual(request.generation_context, context_before)

    def test_generation_context_object_not_altered(self):
        base = build_generation_context(_plan())
        before = base.to_dict()
        ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction()
        ).generation_request
        self.assertEqual(base.to_dict(), before)
        self.assertEqual(base.original_message, "hello there")

    def test_no_correction_request_unchanged(self):
        understanding = _PlanUnderstanding()
        plan_before = copy.deepcopy(understanding.response_plan.to_dict())
        request = ResponseGenerationRequest(understanding)
        request.generation_request
        self.assertIsNone(request.verified_correction_instruction)
        self.assertEqual(understanding.response_plan.to_dict(), plan_before)


# ---------------------------------------------------------------------
# Prompt 498 - Track Corrected Response Target Usage
#
# `BackendGenerationRequest.used_verified_correction` (bool, default
# False) - the structure Prompt 497 already puts the corrected target
# into - is True only when a verified corrected target was actually used
# as the request's input. Observability only: no text is changed by it.
# ---------------------------------------------------------------------

def _without_flag(data):
    data = dict(data)
    data.pop("used_verified_correction")
    return data


class TestUsedVerifiedCorrectionFlag(unittest.TestCase):

    def test_normal_path_is_false(self):
        request = ResponseGenerationRequest(_PlanUnderstanding())
        self.assertIs(request.generation_request["used_verified_correction"], False)

    def test_default_on_the_structure_is_false(self):
        built = build_generation_request(build_generation_context(_plan()))
        self.assertIs(built.used_verified_correction, False)
        self.assertIs(built.to_dict()["used_verified_correction"], False)

    def test_valid_correction_actually_used_is_true(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        generated = request.generation_request
        self.assertIs(generated["used_verified_correction"], True)
        self.assertEqual(generated["original_message"], "I has a dog")

    def test_flag_agrees_with_selected_target(self):
        for instruction in (None, _instruction(), {"corrected_text": "x"}):
            with self.subTest(instruction=instruction):
                request = ResponseGenerationRequest(
                    _PlanUnderstanding(), verified_correction_instruction=instruction)
                self.assertEqual(
                    request.generation_request["used_verified_correction"],
                    request.selected_response_target is not None)

    def test_unusable_correction_data_is_false(self):
        blank_instruction = _instruction()
        blank_instruction.corrected_text = "  "  # bypasses __init__ validation
        for candidate in ({"corrected_text": "I has a dog"}, "I has a dog", 123,
                          object(), blank_instruction):
            with self.subTest(candidate=candidate):
                request = ResponseGenerationRequest(
                    _PlanUnderstanding(), verified_correction_instruction=candidate)
                generated = request.generation_request
                self.assertIs(generated["used_verified_correction"], False)
                self.assertEqual(generated["original_message"], "hello there")

    def test_target_on_context_but_not_used_as_input_is_false(self):
        # correction data exists on a context, but nothing used it as the
        # request's input -> not merely "data exists" -> False
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        context = with_corrected_response_target(build_generation_context(_plan()), request)
        self.assertEqual(context.corrected_response_target, "I has a dog")
        built = build_generation_request(context)
        self.assertIs(built.used_verified_correction, False)
        self.assertEqual(built.original_message, "hello there")

    def test_no_plan_request_has_no_generation_request(self):
        request = ResponseGenerationRequest(
            _NoPlanUnderstanding(), verified_correction_instruction=_instruction())
        self.assertIsNone(request.generation_request)

    def test_everything_else_unchanged_without_correction(self):
        with_flag = ResponseGenerationRequest(_PlanUnderstanding()).generation_request
        self.assertEqual(
            _without_flag(with_flag)["original_message"], "hello there")
        # same keys as before Prompt 498, plus the one new key
        expected_keys = set(build_generation_request(
            build_generation_context(_plan())).to_dict()) - {"used_verified_correction"}
        self.assertEqual(set(_without_flag(with_flag)), expected_keys)

    def test_generation_context_and_selected_target_unchanged(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        before_context = request.generation_context
        before_target = request.selected_response_target
        request.generation_request
        self.assertNotIn("used_verified_correction", request.generation_context)
        self.assertEqual(request.generation_context, before_context)
        self.assertEqual(request.selected_response_target, before_target)


class TestUsedVerifiedCorrectionSerialization(unittest.TestCase):

    def test_round_trip_through_to_dict_preserves_true(self):
        used = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction()
        ).generation_request
        rebuilt = build_generation_request(used)
        self.assertIs(rebuilt.used_verified_correction, True)
        self.assertEqual(rebuilt.to_dict(), used)

    def test_round_trip_through_to_dict_preserves_false(self):
        unused = ResponseGenerationRequest(_PlanUnderstanding()).generation_request
        rebuilt = build_generation_request(unused)
        self.assertIs(rebuilt.used_verified_correction, False)
        self.assertEqual(rebuilt.to_dict(), unused)

    def test_dict_without_the_key_defaults_to_false(self):
        legacy = ResponseGenerationRequest(_PlanUnderstanding()).generation_request
        del legacy["used_verified_correction"]
        rebuilt = build_generation_request(legacy)
        self.assertIs(rebuilt.used_verified_correction, False)

    def test_only_a_real_true_counts(self):
        data = ResponseGenerationRequest(_PlanUnderstanding()).generation_request
        for value in (None, 1, "yes", "True", [True]):
            with self.subTest(value=value):
                data["used_verified_correction"] = value
                self.assertIs(build_generation_request(data).used_verified_correction, False)

    def test_direct_construction_and_repr(self):
        built = BackendGenerationRequest(
            original_message="m", status=None, response_action=None, meaning=None,
            meaning_candidates=[], matched_pattern=None, sentence_structure=None,
            variables={}, active_topic=None, references=[], context=None,
            language=None, locale=None, unresolved_requirements=[],
            used_verified_correction=True)
        self.assertIs(built.to_dict()["used_verified_correction"], True)
        self.assertEqual(repr(built), "BackendGenerationRequest(status=None, response_action=None)")


class TestUsedVerifiedCorrectionSafeCopy(unittest.TestCase):

    def test_to_dict_is_a_fresh_copy_each_call(self):
        request = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction())
        first = request.generation_request
        first["used_verified_correction"] = False
        self.assertIs(request.generation_request["used_verified_correction"], True)

    def test_mutating_a_built_request_never_reaches_the_source(self):
        data = ResponseGenerationRequest(
            _PlanUnderstanding(), verified_correction_instruction=_instruction()
        ).generation_request
        built = build_generation_request(data)
        data["used_verified_correction"] = False
        self.assertIs(built.used_verified_correction, True)
        built.used_verified_correction = False
        self.assertIs(built.to_dict()["used_verified_correction"], False)

    def test_source_objects_not_mutated(self):
        understanding = _PlanUnderstanding()
        plan_before = copy.deepcopy(understanding.response_plan.to_dict())
        instruction = _instruction()
        instruction_before = instruction.to_dict()
        request = ResponseGenerationRequest(
            understanding, verified_correction_instruction=instruction)
        request.generation_request
        self.assertEqual(understanding.response_plan.to_dict(), plan_before)
        self.assertEqual(instruction.to_dict(), instruction_before)
        self.assertIs(request.verified_correction_instruction, instruction)


if __name__ == "__main__":
    unittest.main()
