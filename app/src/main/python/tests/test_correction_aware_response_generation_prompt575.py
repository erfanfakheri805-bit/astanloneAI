"""
Tests for Prompt 575 - Correction-Aware Response Generation Decision.

Prompt 574 gave `ResponsePlan` a derived `correction_application_result_usable`
field. Nothing downstream of the plan - specifically
`ResponseGenerationContext` (response_generation_context.py, Prompt 426),
the smallest existing object through which `ResponsePlan` information is
already passed toward response generation - could see it yet.

This prompt adds ONE small, backward-compatible field to
`ResponseGenerationContext`: `correction_application_result_usable`,
forwarded DIRECTLY from `ResponsePlan.correction_application_result_usable`
(via `response_plan.to_dict()`, the same way every other plan field this
bridge already reads is read) - never independently recomputed. `True`
only when the plan itself says so; `False` for `None`/missing/legacy
plans that carry no such field.

Covers:
    1. usable=True is forwarded from a real ResponsePlan
    2. usable=False is forwarded from a real ResponsePlan
    3. missing/None correction information remains safely False
    4. a plan dict from before Prompt 574 (no such key at all) is safely False
    5. the field survives `ResponseGenerationContext.to_dict()`
    6. the field is visible through `ResponseGenerationRequest.generation_context`
       (response_generation.py) - the response-generation layer's own accessor
    7. existing ResponsePlan fields remain unchanged
    8. existing ResponseGenerationContext fields remain unchanged
    9. ordinary non-correction requests behave exactly as before
    10. no second correction application/retrieval/selection is introduced
    11. backward compatibility with existing constructors/callers
        (omitting the new keyword argument entirely)
    12. deterministic, repeated behavior
    13. end-to-end forwarding through a real Core-produced understanding

Run directly:
    python -m unittest tests.test_correction_aware_response_generation_prompt575 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult, STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED,
)
from language_intelligence.response_planning import (
    ResponsePlan, STATUS_RESOLVED,
)
from language_intelligence.response_generation_context import (
    ResponseGenerationContext, build_generation_context,
    generation_context_from_understanding,
)
from language_intelligence.response_generation import ResponseGenerationRequest
from language_intelligence.correction_understanding import build_correction_understanding
from language_intelligence.correction_understanding_result import (
    map_correction_understanding_to_result,
)
from language_intelligence.correction_feedback_record import (
    map_correction_understanding_result_to_feedback_record,
)
from language_intelligence.correction_feedback_learning_input_adapter import (
    convert_correction_feedback_to_learning_input,
)
from language_intelligence.correction_learning_handoff_result import (
    handoff_correction_learning_input_with_result,
)
from language_intelligence.correction_learning_input_storage import (
    store_accepted_correction_learning_input,
)


def _make_core():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
    skills_dir = os.path.join(tmpdir.name, "skills")
    core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)
    return core, tmpdir


def _store_a_correction(store, original_expression="dgo", corrected_expression="dog",
                         language="en", locale="en-US", confidence=0.9):
    """Same real-store seeding helper Prompt 572/573/574's own test modules use."""
    source = build_correction_understanding(
        "no I mean %s not %s" % (corrected_expression, original_expression),
        original_expression=original_expression,
        corrected_expression=corrected_expression, language=language,
        locale=locale, confidence=confidence)
    result = map_correction_understanding_to_result(source)
    record = map_correction_understanding_result_to_feedback_record(result)
    learning_input = convert_correction_feedback_to_learning_input(record)
    handoff_result = handoff_correction_learning_input_with_result(learning_input, store)
    store_accepted_correction_learning_input(handoff_result, learning_input, store)


def _base_plan_kwargs():
    return dict(
        original_message="hi", detected_language="english", locale=None,
        status=STATUS_RESOLVED, reason=None, needs_clarification=False,
        response_action="greet", response_action_source=None,
        meaning=None, meaning_candidates=[], matched_pattern=None,
        pattern_candidates=[], variables={}, expression_meanings=[],
        active_topic=None, references=[], context=None, required_items=[],
        unresolved_requirements=[], understanding_state={}, warnings=[])


def _applied_result():
    return CorrectionApplicationResult(
        status=STATUS_APPLIED, match_count=1,
        text_before="dgo is here", text_after="dog is here",
        matched_text="dgo", replacement_text="dog")


def _applied_result_dict():
    """The dict form, exactly what `ResponsePlanner.plan()` itself always
    passes into `ResponsePlan.correction_application_result`
    (`_READ_FIELDS` reads it from `understanding.to_dict()`, already a
    dict - response_planning.py). Direct `ResponsePlan(...)` construction
    in these tests uses this same shape so `correction_application_result_
    usable` is computed exactly as it is on the real pipeline."""
    return _applied_result().to_dict()


class TestUsableTrueIsForwarded(unittest.TestCase):
    """1: a plan whose own `correction_application_result_usable` is True
    produces a context whose field is also True - not recomputed."""

    def test_true_forwarded_to_context(self):
        plan = ResponsePlan(correction_application_result=_applied_result_dict(), **_base_plan_kwargs())
        self.assertTrue(plan.correction_application_result_usable)
        context = build_generation_context(plan)
        self.assertTrue(context.correction_application_result_usable)


class TestUsableFalseIsForwarded(unittest.TestCase):
    """2: a FAILED result keeps the plan's own field False, and the
    context reports that same False - never independently True."""

    def test_false_forwarded_to_context(self):
        failed = CorrectionApplicationResult(status=STATUS_FAILED)
        plan = ResponsePlan(correction_application_result=failed, **_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)
        context = build_generation_context(plan)
        self.assertFalse(context.correction_application_result_usable)

    def test_not_applied_forwarded_as_false(self):
        not_applied = CorrectionApplicationResult(status=STATUS_NOT_APPLIED)
        plan = ResponsePlan(correction_application_result=not_applied, **_base_plan_kwargs())
        context = build_generation_context(plan)
        self.assertFalse(context.correction_application_result_usable)


class TestMissingCorrectionInformationStaysFalse(unittest.TestCase):
    """3: None / no correction information at all stays safely False."""

    def test_none_result_context_is_false(self):
        plan = ResponsePlan(correction_application_result=None, **_base_plan_kwargs())
        context = build_generation_context(plan)
        self.assertFalse(context.correction_application_result_usable)

    def test_default_constructed_plan_has_no_correction_is_false(self):
        plan = ResponsePlan(**_base_plan_kwargs())
        self.assertFalse(plan.correction_application_result_usable)
        context = build_generation_context(plan)
        self.assertFalse(context.correction_application_result_usable)


class TestLegacyPlanDictWithoutTheKeyStaysFalse(unittest.TestCase):
    """4: a plan dict predating Prompt 574 (no such key present at all)
    is a safe default of False - never a KeyError, never guessed True."""

    def test_plan_dict_missing_key_is_false(self):
        plan = ResponsePlan(**_base_plan_kwargs())
        data = plan.to_dict()
        self.assertIn("correction_application_result_usable", data)
        del data["correction_application_result_usable"]
        context = build_generation_context(data)
        self.assertFalse(context.correction_application_result_usable)

    def test_plan_dict_with_none_value_is_false(self):
        plan = ResponsePlan(**_base_plan_kwargs())
        data = plan.to_dict()
        data["correction_application_result_usable"] = None
        context = build_generation_context(data)
        self.assertFalse(context.correction_application_result_usable)


class TestFieldSurvivesToDict(unittest.TestCase):
    """5: the field round-trips through ResponseGenerationContext.to_dict()."""

    def test_true_survives_to_dict(self):
        plan = ResponsePlan(correction_application_result=_applied_result_dict(), **_base_plan_kwargs())
        context = build_generation_context(plan)
        self.assertTrue(context.to_dict()["correction_application_result_usable"])

    def test_false_survives_to_dict(self):
        plan = ResponsePlan(**_base_plan_kwargs())
        context = build_generation_context(plan)
        self.assertFalse(context.to_dict()["correction_application_result_usable"])

    def test_to_dict_returns_independent_copy(self):
        """Mutating the returned dict never changes the context's own state
        (same "no mutable-state leakage" discipline every other field
        here already follows)."""
        plan = ResponsePlan(correction_application_result=_applied_result_dict(), **_base_plan_kwargs())
        context = build_generation_context(plan)
        data = context.to_dict()
        data["correction_application_result_usable"] = False
        self.assertTrue(context.correction_application_result_usable)


class TestVisibleThroughResponseGenerationLayer(unittest.TestCase):
    """6: the response-generation layer's own existing accessor
    (`ResponseGenerationRequest.generation_context`) exposes the new
    field, exactly as it already exposes every other plan-derived field."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_generation_context_property_carries_the_flag(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        self.assertEqual(understanding.correction_application_result.status, STATUS_APPLIED)
        # The plan auto-attached during understand() was built BEFORE the
        # correction application step ran (see `_attach_response_plan`,
        # language_intelligence_core.py); re-planning now (the same
        # `plan_response()` Prompt 574's own tests use) reflects the
        # correction that has since been attached to `understanding`.
        plan = self.core.language_intelligence.plan_response(understanding)
        self.assertTrue(plan.correction_application_result_usable)
        understanding.response_plan = plan.to_dict()
        request = ResponseGenerationRequest(understanding)
        generation_context = request.generation_context
        self.assertIsNotNone(generation_context)
        self.assertTrue(generation_context["correction_application_result_usable"])

    def test_generation_context_from_understanding_carries_the_flag(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        plan = self.core.language_intelligence.plan_response(understanding)
        understanding.response_plan = plan.to_dict()
        context = generation_context_from_understanding(understanding)
        self.assertTrue(context.correction_application_result_usable)


class TestExistingResponsePlanFieldsUnchanged(unittest.TestCase):
    """7: adding the new context field never touches the plan itself."""

    def test_plan_fields_unaffected(self):
        kwargs = _base_plan_kwargs()
        plan_before = ResponsePlan(correction_application_result=_applied_result_dict(), **kwargs)
        before = plan_before.to_dict()
        build_generation_context(plan_before)
        after = plan_before.to_dict()
        self.assertEqual(before, after)


class TestExistingResponseGenerationContextFieldsUnchanged(unittest.TestCase):
    """8: every pre-existing ResponseGenerationContext field is untouched
    by the addition - same values as before Prompt 575."""

    def test_other_fields_unchanged(self):
        # `correction_application_result` on the CONTEXT is supplied by a
        # caller directly (Prompt 483) - separate from the plan's own
        # Prompt 573 copy the new field reads. Passing both here (the
        # same way `generation_context_from_understanding` does) checks
        # that adding the new field disturbs neither.
        result_dict = _applied_result_dict()
        plan = ResponsePlan(correction_application_result=result_dict, **_base_plan_kwargs())
        context = build_generation_context(plan, correction_application_result=result_dict)
        data = context.to_dict()
        self.assertEqual(data["original_message"], "hi")
        self.assertEqual(data["status"], STATUS_RESOLVED)
        self.assertEqual(data["response_action"], "greet")
        self.assertEqual(data["meaning"], None)
        self.assertEqual(data["meaning_candidates"], [])
        self.assertEqual(data["matched_pattern"], None)
        self.assertEqual(data["variables"], {})
        self.assertEqual(data["active_topic"], None)
        self.assertEqual(data["references"], [])
        self.assertEqual(data["context"], None)
        self.assertEqual(data["language"], "english")
        self.assertEqual(data["locale"], None)
        self.assertEqual(data["unresolved_requirements"], [])
        # correction_application_result itself must still be the raw
        # forwarded dict, untouched by the new derived field.
        self.assertEqual(data["correction_application_result"]["status"], STATUS_APPLIED)
        self.assertTrue(data["correction_application_result_usable"])


class TestOrdinaryRequestsUnchanged(unittest.TestCase):
    """9: ordinary, non-correction conversation behaves exactly as before -
    no correction result anywhere, so the new field is simply False and
    nothing else about the flow is affected."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ordinary_message_context_is_false_and_unaffected(self):
        understanding = self.core.understand_language("hello there")
        self.assertIsNone(getattr(understanding, "correction_application_result", None))
        context = generation_context_from_understanding(understanding)
        if context is not None:
            self.assertFalse(context.correction_application_result_usable)


class TestNoSecondCorrectionOperationIntroduced(unittest.TestCase):
    """10: forwarding the flag never applies, retrieves, or re-selects
    a correction - it is read exactly once, from the plan's own already-
    computed field."""

    def test_build_generation_context_does_not_touch_correction_result_object(self):
        result = _applied_result()
        original_dict = result.to_dict()
        plan = ResponsePlan(correction_application_result=result, **_base_plan_kwargs())
        build_generation_context(plan)
        self.assertEqual(result.to_dict(), original_dict)

    def test_no_recomputation_when_plan_dict_is_hand_forged_inconsistent(self):
        """The context must forward EXACTLY what the plan dict already
        says - even a hand-forged (inconsistent) dict - never
        re-deriving usability from `correction_application_result` on
        its own. This proves there is no second, competing usability
        algorithm in response_generation_context.py."""
        plan = ResponsePlan(**_base_plan_kwargs())
        data = plan.to_dict()
        # Plan says a result exists but explicitly marks it NOT usable;
        # a re-derivation would need to consult `correction_application_result`
        # itself, which this module must never do.
        data["correction_application_result"] = {
            "status": STATUS_APPLIED, "applied": True, "match_count": 1,
            "text_before": "a", "text_after": "b",
            "matched_text": "a", "replacement_text": "b",
        }
        data["correction_application_result_usable"] = False
        context = build_generation_context(data)
        self.assertFalse(context.correction_application_result_usable)


class TestBackwardCompatibleConstructors(unittest.TestCase):
    """11: existing callers that omit the new keyword argument entirely
    keep working, with the safe default of False."""

    def test_direct_construction_without_new_kwarg(self):
        context = ResponseGenerationContext(
            original_message="hi", status=STATUS_RESOLVED, response_action="greet",
            meaning=None, meaning_candidates=[], matched_pattern=None, variables={},
            active_topic=None, references=[], context=None, language="english",
            locale=None, unresolved_requirements=[])
        self.assertFalse(context.correction_application_result_usable)
        self.assertIn("correction_application_result_usable", context.to_dict())

    def test_build_generation_context_without_any_correction_kwargs(self):
        plan = ResponsePlan(**_base_plan_kwargs())
        context = build_generation_context(plan)
        self.assertFalse(context.correction_application_result_usable)


class TestDeterministicBehavior(unittest.TestCase):
    """12: repeated builds from the same plan always agree."""

    def test_repeated_builds_agree(self):
        plan = ResponsePlan(correction_application_result=_applied_result_dict(), **_base_plan_kwargs())
        results = [build_generation_context(plan).correction_application_result_usable
                   for _ in range(5)]
        self.assertEqual(results, [True] * 5)

    def test_repeated_builds_from_dict_agree(self):
        plan = ResponsePlan(**_base_plan_kwargs())
        data = plan.to_dict()
        results = [build_generation_context(copy.deepcopy(data)).correction_application_result_usable
                   for _ in range(5)]
        self.assertEqual(results, [False] * 5)


class TestEndToEndForwardingThroughRealCore(unittest.TestCase):
    """13: the full, real pipeline (Core -> understanding -> plan ->
    context) forwards the flag correctly for both a usable and an
    ordinary (non-correction) message."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_real_applied_correction_is_usable_end_to_end(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        plan = self.core.language_intelligence.plan_response(understanding)
        self.assertTrue(plan.correction_application_result_usable)
        understanding.response_plan = plan.to_dict()
        context = generation_context_from_understanding(understanding)
        self.assertTrue(context.correction_application_result_usable)
        request = ResponseGenerationRequest(understanding)
        self.assertTrue(request.generation_context["correction_application_result_usable"])

    def test_ordinary_message_end_to_end_is_false(self):
        understanding = self.core.understand_language("hello there")
        context = generation_context_from_understanding(understanding)
        self.assertIsNotNone(context)
        self.assertFalse(context.correction_application_result_usable)


if __name__ == "__main__":
    unittest.main()
