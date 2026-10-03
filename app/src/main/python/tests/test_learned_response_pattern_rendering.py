"""
Tests for Prompt 436 - Learned Response Pattern Rendering.

`LearnedResponsePatternRenderer` (language_intelligence/
learned_response_pattern_rendering.py) turns the ONE selected learned
response pattern's `template` plus the variables Prompt 435 bound into a
response text - RESOLVED with `rendered_text`, UNRESOLVED (missing
variables named, no text at all) when a placeholder has no usable value,
and it preserves an AMBIGUOUS / NOT_FOUND binding without rendering.
Its result is carried by `ResponseGenerationContext.
response_pattern_rendering` and, from there, `BackendGenerationRequest.
response_pattern_rendering`.

Unit-level tests hand-build the plan dict (the exact shape
`ResponsePlan.to_dict()` produces) and run the REAL Prompt 434 selector
and Prompt 435 binder to obtain the binding, so each rule is exercised on
its own. Integration-level tests drive a real Understanding Engine and
real Prompt 416-424 stores and read the rendering off the real context /
request; the local-model / fallback tests use the existing runtime-
boundary test double only.

Run directly:
    python -m unittest tests.test_learned_response_pattern_rendering -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_planning import STATUS_RESOLVED as PLAN_RESOLVED
from language_intelligence.response_generation_context import (
    ResponseGenerationContext, build_generation_context, generation_context_from_understanding,
)
from language_intelligence.response_generation_request import (
    BackendGenerationRequest, build_generation_request, generation_request_from_understanding,
)
from language_intelligence.response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult, STATUS_DEFERRED,
)
from language_intelligence.learned_response_pattern_selection import (
    select_learned_response_pattern, RESPONSE_PATTERNS_KEY,
    STATUS_RESOLVED as SEL_RESOLVED, STATUS_NOT_FOUND as SEL_NOT_FOUND,
)
from language_intelligence.learned_response_pattern_binding import (
    LearnedResponsePatternBinder, bind_learned_response_pattern,
    STATUS_RESOLVED as BIND_RESOLVED,
)
from language_intelligence.learned_response_pattern_rendering import (
    LearnedResponsePatternRenderer, LearnedResponsePatternRendering,
    render_learned_response_pattern, response_pattern_rendering_from_understanding,
    STATUS_RESOLVED, STATUS_UNRESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND, ALL_STATUSES,
    REASON_VARIABLES_MISSING, REASON_VARIABLE_NOT_RENDERABLE, REASON_NO_BINDING,
    REASON_PATTERN_UNAVAILABLE, REASON_NO_TEMPLATE, OUTPUT_KIND,
)

# Existing test modules are reused (as modules, so none of their test
# classes are collected a second time here).
from tests import test_learned_response_pattern_binding as _b
from tests import test_response_generation_request as _r

QUESTION_PATTERN = _b.QUESTION_PATTERN
GREETING_PATTERN = _b.GREETING_PATTERN
PREFERENCE_PATTERN = _b.PREFERENCE_PATTERN


def _binding(plan, guidance=None):
    """The REAL Prompt 434 selection and Prompt 435 binding for `plan`."""
    selection = select_learned_response_pattern(plan, guidance)
    return LearnedResponsePatternBinder().bind(plan, selection, guidance)


def _render(plan, guidance=None):
    return LearnedResponsePatternRenderer().render(_binding(plan, guidance)).to_dict()


def _render_template(template, variables=None, **plan_kwargs):
    plan = _b._plan_with([{"id": "p", "template": template}], variables=variables or {},
                         **plan_kwargs)
    return _render(plan)


# ----------------------------------------------------------------------
class TestPatternWithNoVariables(unittest.TestCase):
    """1. A template with no placeholder needs nothing and renders as is."""

    def test_renders_the_template_verbatim(self):
        result = _render_template("Good morning.")
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["rendered_text"], "Good morning.")
        self.assertIsNone(result["failure_reason"])
        self.assertEqual(result["bound_variables"], {})
        self.assertEqual(result["missing_variables"], [])
        self.assertEqual(result["pattern_id"], "p")

    def test_unrelated_extracted_variables_are_not_inserted(self):
        result = _render_template("Good morning.", {"topic": "python"})
        self.assertEqual(result["rendered_text"], "Good morning.")

    def test_whitespace_and_punctuation_are_untouched(self):
        result = _render_template("  Hello,\n  world !  ")
        self.assertEqual(result["rendered_text"], "  Hello,\n  world !  ")


class TestPatternWithOneVariable(unittest.TestCase):
    """2. One placeholder, one bound value."""

    def test_the_placeholder_is_replaced(self):
        result = _render_template("About {{topic}}.", {"topic": "python"})
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["rendered_text"], "About python.")
        self.assertEqual(result["bound_variables"], {"topic": "python"})
        self.assertEqual(result["metadata"]["template_variables"], ["topic"])
        self.assertEqual(result["metadata"]["output_kind"], OUTPUT_KIND)

    def test_a_repeated_placeholder_is_replaced_everywhere(self):
        result = _render_template("{{x}} and {{x}} again", {"x": "tea"})
        self.assertEqual(result["rendered_text"], "tea and tea again")

    def test_a_padded_placeholder_is_replaced(self):
        result = _render_template("About {{ topic }}.", {"topic": "python"})
        self.assertEqual(result["rendered_text"], "About python.")


class TestPatternWithMultipleVariables(unittest.TestCase):
    """3. Several placeholders, each with its own bound value."""

    def test_every_placeholder_gets_its_own_value(self):
        result = _render_template("{{who}} likes {{what}} in {{where}}.",
                                  {"who": "Sara", "what": "tea", "where": "Tehran"})
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["rendered_text"], "Sara likes tea in Tehran.")
        self.assertEqual(result["bound_variables"],
                         {"who": "Sara", "what": "tea", "where": "Tehran"})
        self.assertEqual(result["metadata"]["template_variables"], ["who", "what", "where"])

    def test_values_are_not_swapped_by_name_order(self):
        result = _render_template("{{b}}-{{a}}", {"a": "1", "b": "2"})
        self.assertEqual(result["rendered_text"], "2-1")

    def test_a_routed_context_variable_is_rendered(self):
        plan = _b._plan_with(
            [{"id": "p", "template": "Re: {{subject}}", "variable_sources": {"subject": "active_topic"}}],
            active_topic={"topic": "python"})
        result = _render(plan)
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["rendered_text"], "Re: python")
        self.assertEqual(result["metadata"]["variable_sources"], {"subject": "active_topic"})


class TestExactVariableReplacement(unittest.TestCase):
    """4. Only the defined placeholders change; values go in exactly."""

    def test_the_value_is_inserted_exactly_as_bound(self):
        for value in ("  padded  ", "MiXeD Case", "a\tb\nc", "چای", "😀 x", "a{b}c", "$1 \\1 %s"):
            with self.subTest(value=value):
                result = _render_template("<{{v}}>", {"v": value})
                self.assertEqual(result["rendered_text"], "<" + value + ">")

    def test_a_placeholder_shaped_value_is_never_expanded(self):
        result = _render_template("{{a}} / {{b}}", {"a": "{{b}}", "b": "B"})
        self.assertEqual(result["rendered_text"], "{{b}} / B")

    def test_text_that_is_not_a_placeholder_is_left_alone(self):
        for template in ("{single} braces", "{{}} empty", "lonely {{ open", "close }} only"):
            with self.subTest(template=template):
                result = _render_template(template + " {{v}}", {"v": "X"})
                self.assertTrue(result["rendered_text"].endswith(" X"), result)
                self.assertNotIn("{{v}}", result["rendered_text"])

    def test_placeholder_names_are_case_sensitive(self):
        result = _render_template("{{Topic}}", {"topic": "python"})
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["missing_variables"], ["Topic"])

    def test_numbers_are_rendered_as_their_own_text(self):
        result = _render_template("{{n}} items, {{f}} kg", {"n": 3, "f": 2.5})
        self.assertEqual(result["rendered_text"], "3 items, 2.5 kg")
        self.assertEqual(result["bound_variables"], {"n": 3, "f": 2.5})


class TestMissingVariable(unittest.TestCase):
    """5. One required variable is missing: UNRESOLVED, no text at all."""

    def test_a_missing_variable_is_reported_and_no_text_is_produced(self):
        result = _render_template("About {{topic}} for {{audience}}.", {"topic": "python"})
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertIsNone(result["rendered_text"])
        self.assertEqual(result["missing_variables"], ["audience"])
        self.assertEqual(result["failure_reason"], REASON_VARIABLES_MISSING)
        self.assertEqual(result["bound_variables"], {"topic": "python"})
        self.assertEqual(result["pattern_id"], "p")

    def test_a_blank_extracted_value_counts_as_missing(self):
        result = _render_template("About {{topic}}.", {"topic": "   "})
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertIsNone(result["rendered_text"])
        self.assertEqual(result["missing_variables"], ["topic"])

    def test_conflicting_values_are_missing_not_guessed(self):
        plan = _b._plan_with([{"id": "p", "template": "About {{topic}}."}],
                             variables={"topic": "python"})
        guidance = _b._guidance(plan, structure=_b._structure(topic="java"))
        result = _render(plan, guidance)
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertIsNone(result["rendered_text"])
        self.assertEqual(result["missing_variables"], ["topic"])

    def test_a_bound_value_that_is_not_text_or_a_number_is_not_rendered(self):
        for value in (True, {"a": 1}, ["x"]):
            with self.subTest(value=value):
                result = _render_template("About {{topic}}.", {"topic": value})
                self.assertEqual(result["status"], STATUS_UNRESOLVED)
                self.assertIsNone(result["rendered_text"])
                self.assertEqual(result["missing_variables"], ["topic"])
                self.assertEqual(result["failure_reason"], REASON_VARIABLE_NOT_RENDERABLE)
                self.assertEqual(result["bound_variables"], {"topic": value})

    def test_a_resolved_binding_whose_bound_variables_lack_a_placeholder_is_unresolved(self):
        binding = _binding(_b._plan_with([{"id": "p", "template": "{{a}} {{b}}"}],
                                         variables={"a": "1", "b": "2"})).to_dict()
        del binding["bound_variables"]["b"]
        result = render_learned_response_pattern(binding).to_dict()
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertIsNone(result["rendered_text"])
        self.assertEqual(result["missing_variables"], ["b"])


class TestMultipleMissingVariables(unittest.TestCase):
    """6. Every missing variable is named, in template order."""

    def test_all_missing_variables_are_named(self):
        result = _render_template("{{a}} {{b}} {{c}}", {"b": "2"})
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertIsNone(result["rendered_text"])
        self.assertEqual(result["missing_variables"], ["a", "c"])
        self.assertEqual(result["bound_variables"], {"b": "2"})

    def test_nothing_bound_at_all(self):
        result = _render_template("{{a}} {{b}}", {})
        self.assertEqual(result["missing_variables"], ["a", "b"])
        self.assertEqual(result["bound_variables"], {})
        self.assertIsNone(result["rendered_text"])

    def test_no_partial_text_leaks_into_any_field(self):
        result = _render_template("Dear {{name}}, about {{topic}}.", {"topic": "python"})
        self.assertIsNone(result["rendered_text"])
        self.assertNotIn("Dear", repr({k: v for k, v in result.items()
                                        if k not in ("metadata",)}))

    def test_variables_beyond_the_binders_bound_are_reported_missing(self):
        names = ["v%d" % i for i in range(_b.MAX_REQUIRED_VARIABLES + 2)]
        plan = _b._plan_with([{"id": "p", "template": " ".join("{{%s}}" % n for n in names)}],
                             variables={n: "x" for n in names})
        result = _render(plan)
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertEqual(result["missing_variables"], names[-2:])
        self.assertIsNone(result["rendered_text"])
        self.assertTrue(result["metadata"]["truncated"])


class TestAmbiguousPattern(unittest.TestCase):
    """7. An ambiguous selection is preserved and nothing is rendered."""

    def test_equally_valid_patterns_stay_ambiguous(self):
        plan = _b._plan_with([{"id": "one", "template": "One {{a}}"},
                              {"id": "two", "template": "Two {{a}}"}], variables={"a": "x"})
        binding = _binding(plan)
        result = LearnedResponsePatternRenderer().render(binding).to_dict()
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertIsNone(result["rendered_text"])
        self.assertIsNone(result["pattern_id"])
        self.assertEqual(result["failure_reason"], binding.reason)
        self.assertEqual([c["pattern_id"] for c in result["candidates"]], ["one", "two"])
        self.assertEqual(result["candidates"], binding.to_dict()["candidates"])
        self.assertEqual(result["bound_variables"], {})

    def test_an_undecided_understanding_stays_ambiguous(self):
        plan = _b._plan(
            meaning_candidates=[_b._meaning("gratitude", [{"id": "thank_back", "template": "Thanks"}]),
                                _b._meaning("farewell", [{"id": "wave_back", "template": "Bye"}],
                                            meaning_id=2)],
            variables={"a": "x"})
        result = _render(plan)
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertIsNone(result["rendered_text"])


class TestUnavailablePattern(unittest.TestCase):
    """8. No pattern / no binding: NOT_FOUND, nothing invented."""

    def test_nothing_taught_is_not_found(self):
        plan = _b._plan(meaning=_b._meaning(), variables={"a": "x"})
        binding = _binding(plan)
        result = LearnedResponsePatternRenderer().render(binding).to_dict()
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertIsNone(result["rendered_text"])
        self.assertIsNone(result["pattern_id"])
        self.assertEqual(result["failure_reason"], binding.reason)

    def test_no_binding_at_all_is_not_found(self):
        for missing in (None, {}):
            with self.subTest(binding=missing):
                result = render_learned_response_pattern(missing).to_dict()
                self.assertEqual(result["status"], STATUS_NOT_FOUND)
                self.assertIsNone(result["rendered_text"])
                self.assertEqual(result["failure_reason"], REASON_NO_BINDING)

    def test_a_binding_of_an_unknown_status_is_not_found(self):
        result = render_learned_response_pattern({"status": "WHATEVER"}).to_dict()
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertIsNone(result["rendered_text"])

    def test_a_value_of_the_wrong_type_raises_type_error(self):
        for bad in ("RESOLVED", 5, [], object()):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    LearnedResponsePatternRenderer().render(bad)

    def test_a_not_found_binding_dict_is_preserved(self):
        binding = {"status": "NOT_FOUND", "reason": "some_reason", "language": "english",
                   "locale": "en-GB"}
        result = render_learned_response_pattern(binding).to_dict()
        self.assertEqual((result["status"], result["failure_reason"]), (STATUS_NOT_FOUND, "some_reason"))
        self.assertEqual((result["language"], result["locale"]), ("english", "en-GB"))


class TestEmptyOrInvalidPattern(unittest.TestCase):
    """9. A selected pattern with nothing usable to render is NOT_FOUND."""

    def test_a_pattern_without_a_template_is_not_rendered(self):
        result = _render(_b._plan_with([{"id": "p"}], variables={"a": "x"}))
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertEqual(result["failure_reason"], REASON_NO_TEMPLATE)
        self.assertIsNone(result["rendered_text"])
        self.assertEqual(result["pattern_id"], "p")

    def test_a_blank_or_non_text_template_is_not_rendered(self):
        for template in ("", "   \n", None, 5, ["x"], {"t": "x"}):
            with self.subTest(template=template):
                result = _render(_b._plan_with([{"id": "p", "template": template}]))
                self.assertEqual(result["status"], STATUS_NOT_FOUND)
                self.assertEqual(result["failure_reason"], REASON_NO_TEMPLATE)
                self.assertIsNone(result["rendered_text"])

    def test_an_entry_without_an_id_is_never_selected_so_nothing_renders(self):
        result = _render(_b._plan_with([{"template": "no id"}, "not a dict", 7, None]))
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertIsNone(result["rendered_text"])

    def test_a_resolved_binding_with_a_broken_selected_pattern_is_not_found(self):
        base = _binding(_b._plan_with([{"id": "p", "template": "Hi"}])).to_dict()
        for name, mutate, reason in (
                ("no selected pattern", lambda d: d.update(selected_pattern=None),
                 REASON_PATTERN_UNAVAILABLE),
                ("no pattern body", lambda d: d["selected_pattern"].update(pattern=None),
                 REASON_PATTERN_UNAVAILABLE),
                ("pattern without id", lambda d: d["selected_pattern"]["pattern"].pop("id"),
                 REASON_PATTERN_UNAVAILABLE),
                ("pattern without template", lambda d: d["selected_pattern"]["pattern"].pop("template"),
                 REASON_NO_TEMPLATE)):
            with self.subTest(case=name):
                data = copy.deepcopy(base)
                mutate(data)
                result = render_learned_response_pattern(data).to_dict()
                self.assertEqual(result["status"], STATUS_NOT_FOUND)
                self.assertEqual(result["failure_reason"], reason)
                self.assertIsNone(result["rendered_text"])


class TestPreservation(unittest.TestCase):
    """10-12. Bound values, language, locale, identity, source, confidence
    and metadata are preserved exactly."""

    def _pair(self, patterns, **kwargs):
        plan = _b._plan_with(patterns, **kwargs)
        binding = _binding(plan)
        return binding.to_dict(), LearnedResponsePatternRenderer().render(binding).to_dict()

    def test_bound_variable_values_are_preserved_exactly(self):
        bound, rendered = self._pair([{"id": "p", "template": "{{a}} {{b}} {{c}}"}],
                                     variables={"a": "  spaced ", "b": 4, "c": "چای"})
        self.assertEqual(rendered["bound_variables"], bound["bound_variables"])
        self.assertEqual(rendered["bound_variables"], {"a": "  spaced ", "b": 4, "c": "چای"})
        self.assertIsInstance(rendered["bound_variables"]["b"], int)
        self.assertEqual(rendered["rendered_text"], "  spaced  4 چای")

    def test_language_is_preserved(self):
        for language in ("english", "persian"):
            with self.subTest(language=language):
                bound, rendered = self._pair([{"id": "p", "template": "Hi"}], language=language)
                self.assertEqual(rendered["language"], language)
                self.assertEqual(rendered["language"], bound["language"])

    def test_locale_is_preserved(self):
        bound, rendered = self._pair([{"id": "p", "locale": "en-GB", "template": "Hi"}],
                                     locale="en-GB")
        self.assertEqual(rendered["status"], STATUS_RESOLVED)
        self.assertEqual(rendered["locale"], "en-GB")
        self.assertEqual(rendered["locale"], bound["locale"])

    def test_language_and_locale_survive_a_failure_too(self):
        bound, rendered = self._pair([{"id": "p", "template": "{{x}}"}], language="persian",
                                     locale="fa-IR")
        self.assertEqual(rendered["status"], STATUS_UNRESOLVED)
        self.assertEqual((rendered["language"], rendered["locale"]), ("persian", "fa-IR"))

    def test_pattern_identity_source_confidence_and_origin_are_preserved(self):
        bound, rendered = self._pair([{"id": "greet_back", "template": "Hi"}])
        self.assertEqual(rendered["pattern_id"], "greet_back")
        self.assertEqual(rendered["source"], bound["source"])
        self.assertEqual(rendered["confidence"], bound["confidence"])
        self.assertEqual(rendered["confidence"], 0.9)
        self.assertEqual(rendered["source"], "unit-test")
        self.assertEqual(rendered["original_message"], bound["original_message"])
        self.assertEqual(rendered["metadata"]["origin"], bound["selected_pattern"]["origin"])
        self.assertEqual(rendered["metadata"]["matched_on"], bound["selected_pattern"]["matched_on"])
        self.assertEqual(rendered["metadata"]["binding_status"], BIND_RESOLVED)
        self.assertEqual(rendered["metadata"]["binding_reason"], bound["reason"])

    def test_the_patterns_own_metadata_is_carried(self):
        _, rendered = self._pair([{"id": "p", "template": "Hi", "metadata": {"tone": "formal"}}])
        self.assertEqual(rendered["metadata"]["pattern_metadata"], {"tone": "formal"})

    def test_metadata_marks_only_rendered_text_as_learned_response_output(self):
        _, ok = self._pair([{"id": "p", "template": "Hi"}])
        _, bad = self._pair([{"id": "p", "template": "{{x}}"}])
        self.assertEqual(ok["metadata"]["output_kind"], "deterministic_learned_response")
        self.assertIsNone(bad["metadata"]["output_kind"])

    def test_every_status_is_a_known_status(self):
        self.assertEqual(set(ALL_STATUSES),
                         {STATUS_RESOLVED, STATUS_UNRESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND})


class TestDeterministic(unittest.TestCase):
    """13. The same binding always renders the same result."""

    def test_repeated_rendering_is_identical(self):
        binding = _binding(_b._plan_with([{"id": "p", "template": "{{a}}, {{b}}!"}],
                                         variables={"a": "x", "b": "y"}))
        renderer = LearnedResponsePatternRenderer()
        first = renderer.render(binding).to_dict()
        for _ in range(5):
            self.assertEqual(renderer.render(binding).to_dict(), first)
            self.assertEqual(LearnedResponsePatternRenderer().render(binding.to_dict()).to_dict(),
                             first)
        self.assertEqual(first["rendered_text"], "x, y!")

    def test_a_rendering_and_its_dict_are_independent_copies(self):
        binding = _binding(_b._plan_with([{"id": "p", "template": "{{a}}"}], variables={"a": "x"}))
        rendering = render_learned_response_pattern(binding)
        rendering.to_dict()["bound_variables"]["a"] = "TAMPERED"
        rendering.to_dict()["metadata"]["template_variables"].append("z")
        self.assertEqual(rendering.to_dict()["bound_variables"], {"a": "x"})
        self.assertEqual(rendering.to_dict()["metadata"]["template_variables"], ["a"])

    def test_rendering_never_mutates_the_binding(self):
        binding = _binding(_b._plan_with([{"id": "p", "template": "{{a}} {{b}}"}],
                                         variables={"a": "x"})).to_dict()
        before = copy.deepcopy(binding)
        render_learned_response_pattern(binding)
        self.assertEqual(binding, before)

    def test_input_order_of_taught_patterns_does_not_change_the_text(self):
        for template in ("A {{x}}", "B {{x}}"):
            self.assertEqual(_render_template(template, {"x": "1"})["rendered_text"],
                             template.replace("{{x}}", "1"))

    def test_a_rendering_object_reports_its_status_flags(self):
        ok = render_learned_response_pattern(
            _binding(_b._plan_with([{"id": "p", "template": "Hi"}])))
        self.assertIsInstance(ok, LearnedResponsePatternRendering)
        self.assertTrue(ok.resolved)
        self.assertFalse(ok.unresolved or ok.ambiguous or ok.not_found)


class TestNoInventedText(unittest.TestCase):
    """14. The output holds only the template's text and the bound values."""

    def test_removing_the_bound_values_leaves_exactly_the_templates_own_text(self):
        template = "Hi {{who}}, welcome to {{where}}. Enjoy!"
        variables = {"who": "Sara", "where": "Tehran"}
        result = _render_template(template, variables)
        expected = template.replace("{{who}}", "Sara").replace("{{where}}", "Tehran")
        self.assertEqual(result["rendered_text"], expected)
        literal = result["rendered_text"].replace("Sara", "").replace("Tehran", "")
        self.assertEqual(literal, "Hi , welcome to . Enjoy!")

    def test_the_message_and_extra_context_never_appear_in_the_text(self):
        plan = _b._plan_with([{"id": "p", "template": "Hello."}],
                             variables={"topic": "python"}, original_message="what is python",
                             active_topic={"topic": "java"})
        result = _render(plan)
        self.assertEqual(result["rendered_text"], "Hello.")
        self.assertEqual(result["original_message"], "what is python")

    def test_a_pattern_never_becomes_text_when_it_is_not_rendered(self):
        for plan in (
                _b._plan_with([{"id": "p", "template": "Secret {{x}}"}]),
                _b._plan_with([{"id": "a", "template": "A"}, {"id": "b", "template": "B"}]),
                _b._plan_with([{"id": "p"}]),
                _b._plan(meaning=_b._meaning())):
            self.assertIsNone(_render(plan)["rendered_text"])

    def test_no_model_or_network_module_is_imported_by_the_renderer(self):
        import language_intelligence.learned_response_pattern_rendering as module
        with open(module.__file__, encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in ("import socket", "import urllib", "import requests", "import random",
                          "import time", "import datetime", "local_model_runtime",
                          "local_model_provider", "local_model_backend", "backend_selection"):
            self.assertNotIn(forbidden, source)


# ----------------------------------------------------------------------
class TestRealPipelineRendering(_b._PipelineCase):
    """Real Understanding Engine + real stores; response patterns taught
    through the existing operations."""

    def _rendering(self, text, **context):
        return response_pattern_rendering_from_understanding(
            self.understand(text, **context)).to_dict()

    def test_a_sentence_pattern_variable_is_rendered(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "variables": ["topic"], "template": "About {{topic}}."}]})
        result = self._rendering("what is python")
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["rendered_text"], "About python.")
        self.assertEqual(result["pattern_id"], "answer_question")
        self.assertEqual(result["bound_variables"], {"topic": "python"})
        self.assertEqual(result["original_message"], "what is python")
        self.assertEqual(result["language"], "english")

    def test_a_placeholder_the_message_never_supplied_is_unresolved(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "template": "About {{topic}} for {{audience}}."}]})
        result = self._rendering("what is python")
        self.assertEqual(result["status"], STATUS_UNRESOLVED)
        self.assertIsNone(result["rendered_text"])
        self.assertEqual(result["missing_variables"], ["audience"])

    def test_persian_pattern_keeps_language_locale_and_value(self):
        self.teach(PREFERENCE_PATTERN, language="fa", locale="fa-IR", meaning={
            RESPONSE_PATTERNS_KEY: [
                {"id": "ask_why", "language": "fa", "locale": "fa-IR",
                 "template": "چرا {{X}} را دوست داری؟"}]})
        self.bind_meaning(PREFERENCE_PATTERN, "express_preference", language="fa")
        result = self._rendering("من چای را دوست دارم", requested_language="fa")
        self.assertEqual(result["status"], STATUS_RESOLVED)
        self.assertEqual(result["rendered_text"], "چرا چای را دوست داری؟")
        self.assertEqual(result["bound_variables"], {"X": "چای"})
        self.assertEqual((result["language"], result["locale"]), ("persian", "fa-IR"))

    def test_two_equally_valid_patterns_stay_ambiguous(self):
        self.teach_meaning("ask_question", [{"id": "one", "template": "One"},
                                            {"id": "two", "template": "Two"}])
        self.teach(QUESTION_PATTERN)
        self.bind_meaning(QUESTION_PATTERN, "ask_question")
        result = self._rendering("what is python")
        self.assertEqual(result["status"], STATUS_AMBIGUOUS)
        self.assertIsNone(result["rendered_text"])
        self.assertEqual([c["pattern_id"] for c in result["candidates"]], ["one", "two"])

    def test_nothing_taught_is_not_found(self):
        result = self._rendering("what is python")
        self.assertEqual(result["status"], STATUS_NOT_FOUND)
        self.assertIsNone(result["rendered_text"])

    def test_no_plan_means_no_rendering(self):
        class _NoPlan:
            response_plan = None
            learned_sentence_structure = None
        self.assertIsNone(response_pattern_rendering_from_understanding(_NoPlan()))


class TestCompatibleWithResponseGenerationContext(_b._PipelineCase):
    """15. The rendering rides on the existing ResponseGenerationContext,
    after binding, without changing anything already there."""

    def _taught(self):
        self.teach(QUESTION_PATTERN, meaning={
            "response_action": "answer", RESPONSE_PATTERNS_KEY: [
                {"id": "answer_question", "variables": ["topic"], "template": "About {{topic}}."}]})
        return self.understand("what is python")

    def test_the_context_carries_the_rendering(self):
        context = generation_context_from_understanding(self._taught())
        self.assertIsInstance(context, ResponseGenerationContext)
        self.assertEqual(context.response_pattern_rendering["status"], STATUS_RESOLVED)
        self.assertEqual(context.response_pattern_rendering["rendered_text"], "About python.")
        self.assertEqual(context.to_dict()["response_pattern_rendering"],
                         context.response_pattern_rendering)

    def test_the_contexts_rendering_equals_the_renderers_own(self):
        understanding = self._taught()
        context = generation_context_from_understanding(understanding)
        self.assertEqual(context.response_pattern_rendering,
                         response_pattern_rendering_from_understanding(understanding).to_dict())

    def test_the_rendering_is_made_from_the_contexts_own_binding(self):
        context = generation_context_from_understanding(self._taught())
        self.assertEqual(context.response_pattern_rendering,
                         render_learned_response_pattern(context.response_pattern_binding).to_dict())
        self.assertEqual(context.response_pattern_rendering["bound_variables"],
                         context.response_pattern_binding["bound_variables"])

    def test_the_context_still_carries_guidance_selection_and_binding(self):
        context = generation_context_from_understanding(self._taught())
        self.assertEqual(context.response_pattern_selection["status"], SEL_RESOLVED)
        self.assertEqual(context.response_pattern_binding["status"], BIND_RESOLVED)
        self.assertIsNotNone(context.language_guidance)
        self.assertEqual(context.original_message, "what is python")
        self.assertEqual(context.variables, {"topic": "python"})

    def test_a_context_built_from_a_plan_dict_has_a_rendering_and_stays_independent(self):
        plan = _b._plan_with([{"id": "p", "template": "Hi {{a}}"}], variables={"a": "x"})
        context = build_generation_context(plan)
        self.assertEqual(context.response_pattern_rendering["rendered_text"], "Hi x")
        context.response_pattern_rendering["rendered_text"] = "TAMPERED"
        context.to_dict()["response_pattern_rendering"]["bound_variables"]["a"] = "y"
        self.assertEqual(build_generation_context(plan).response_pattern_rendering["rendered_text"],
                         "Hi x")
        self.assertEqual(context.to_dict()["response_pattern_rendering"]["bound_variables"],
                         {"a": "x"})

    def test_a_context_with_no_learned_response_pattern_carries_not_found(self):
        context = build_generation_context(_b._plan(meaning=_b._meaning()))
        self.assertEqual(context.response_pattern_selection["status"], SEL_NOT_FOUND)
        self.assertEqual(context.response_pattern_rendering["status"], STATUS_NOT_FOUND)
        self.assertIsNone(context.response_pattern_rendering["rendered_text"])

    def test_a_context_built_by_hand_without_a_rendering_still_works(self):
        context = ResponseGenerationContext(
            original_message="hi", status=PLAN_RESOLVED, response_action=None, meaning=None,
            meaning_candidates=[], matched_pattern=None, variables={}, active_topic=None,
            references=[], context=None, language="english", locale=None,
            unresolved_requirements=[])
        self.assertIsNone(context.response_pattern_rendering)
        self.assertIsNone(context.to_dict()["response_pattern_rendering"])


class TestCompatibleWithResponseGenerationRequest(_b._PipelineCase):
    """16. The rendering reaches `ResponseGenerationRequest` and
    `BackendGenerationRequest` unchanged; nothing downstream changes."""

    def _taught(self):
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "variables": ["topic"], "template": "About {{topic}}."}]})
        return self.understand("what is python")

    def test_the_backend_generation_request_carries_the_rendering_unchanged(self):
        understanding = self._taught()
        request = generation_request_from_understanding(understanding)
        self.assertIsInstance(request, BackendGenerationRequest)
        context = generation_context_from_understanding(understanding)
        self.assertEqual(request.response_pattern_rendering, context.response_pattern_rendering)
        self.assertEqual(request.to_dict()["response_pattern_rendering"]["rendered_text"],
                         "About python.")

    def test_build_generation_request_carries_it_from_a_context_or_its_dict(self):
        context = generation_context_from_understanding(self._taught())
        for source in (context, context.to_dict()):
            request = build_generation_request(source)
            self.assertEqual(request.response_pattern_rendering, context.response_pattern_rendering)

    def test_the_request_accessors_expose_the_rendering(self):
        request = ResponseGenerationRequest(self._taught())
        self.assertEqual(request.generation_context["response_pattern_rendering"]["status"],
                         STATUS_RESOLVED)
        self.assertEqual(request.generation_request["response_pattern_rendering"],
                         request.generation_context["response_pattern_rendering"])

    def test_the_request_still_carries_the_earlier_fields(self):
        data = generation_request_from_understanding(self._taught()).to_dict()
        self.assertEqual(data["response_pattern_selection"]["status"], SEL_RESOLVED)
        self.assertEqual(data["response_pattern_binding"]["status"], BIND_RESOLVED)
        self.assertEqual(data["original_message"], "what is python")
        self.assertEqual(data["variables"], {"topic": "python"})

    def test_a_request_built_by_hand_without_a_rendering_still_works(self):
        request = BackendGenerationRequest(
            original_message="hi", status=PLAN_RESOLVED, response_action=None, meaning=None,
            meaning_candidates=[], matched_pattern=None, sentence_structure=None, variables={},
            active_topic=None, references=[], context=None, language="english", locale=None,
            unresolved_requirements=[])
        self.assertIsNone(request.response_pattern_rendering)
        self.assertIsNone(request.to_dict()["response_pattern_rendering"])

    def test_the_request_rendering_is_an_independent_copy(self):
        understanding = self._taught()
        request = generation_request_from_understanding(understanding)
        request.response_pattern_rendering["rendered_text"] = "TAMPERED"
        request.to_dict()["response_pattern_rendering"]["bound_variables"]["topic"] = "x"
        again = generation_request_from_understanding(understanding)
        self.assertEqual(again.response_pattern_rendering["rendered_text"], "About python.")
        self.assertEqual(again.response_pattern_rendering["bound_variables"], {"topic": "python"})

    def test_the_deterministic_backend_result_is_a_deferred_generation_result(self):
        """17. ResponseGenerationResult is unchanged: rendering does not turn
        the deterministic backend into a text generator."""
        result = self.backend.generate_response(ResponseGenerationRequest(self._taught()))
        self.assertIsInstance(result, ResponseGenerationResult)
        self.assertEqual(result.status, STATUS_DEFERRED)
        self.assertIsNone(result.response_text)
        self.assertEqual(sorted(result.to_dict()), sorted([
            "status", "response_text", "reason", "backend_kind", "inference_status", "error_code",
            "metadata", "fallback_backend_kind", "selected_backend_kind",
            "used_verified_correction"]))  # Prompt 500: additive key
        self.assertNotIn("response_pattern_rendering", result.to_dict())
        self.assertIs(result.to_dict()["used_verified_correction"], False)

    def test_generation_result_is_identical_with_and_without_a_learned_pattern(self):
        control = self.understand("what is python")
        control_result = self.backend.generate_response(ResponseGenerationRequest(control)).to_dict()
        self.teach(QUESTION_PATTERN, meaning={RESPONSE_PATTERNS_KEY: [
            {"id": "answer_question", "template": "About {{topic}}."}]})
        taught_result = self.backend.generate_response(
            ResponseGenerationRequest(self.understand("what is python"))).to_dict()
        self.assertEqual(taught_result, control_result)


class TestExistingLocalModelAndFallbackBehaviourUnchanged(_r._LocalPath):
    """18. The local-model path and the deterministic fallback behave as
    before: the model's own text is still the reply, a model failure still
    falls back to the deterministic pipeline, and the rendering is only
    carried, never substituted for either."""

    # Prompt 437 lets a VALID learned response answer directly, so these
    # Prompt 436 checks use a pattern whose variable can never be bound:
    # the rendering is carried (UNRESOLVED) and the existing pipeline runs.
    UNBOUND = "About {{topic}} for {{audience}}."

    def _teach(self, core, template=None):
        assert core.teach_sentence_pattern("en", QUESTION_PATTERN).status == _r.STATUS_CREATED
        bound = core.bind_pattern_meaning("en", QUESTION_PATTERN, "ask_question")
        assert bound.success, bound.errors
        core.learn_language_item("en", "meaning", "ask_question", meaning={
            "response_action": "provide_information",
            RESPONSE_PATTERNS_KEY: [{"id": "answer_question",
                                     "template": template or self.UNBOUND}]})

    def test_the_model_text_is_still_the_reply_and_the_rendering_is_only_carried(self):
        core = self.core()
        self._teach(core)
        runtime = _r.TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        reply = core.process_input("what is python")
        self.assertEqual(reply, _r.MODEL_TEXT)
        generation_request = runtime.requests[0].generation_request
        self.assertIsNone(generation_request.response_pattern_rendering["rendered_text"])
        self.assertEqual(generation_request.response_pattern_rendering["status"], STATUS_UNRESOLVED)
        self.assertEqual(generation_request.response_pattern_rendering["missing_variables"],
                         ["audience"])

    def test_model_not_configured_falls_back_exactly_as_before(self):
        control, _ = _r._core(self)
        expected = control.process_input(_r.MESSAGE)
        core = self.core()
        self._teach(core)
        core.use_local_language_model(runtime=_r.TextRuntime(None))
        self.assertEqual(core.process_input(_r.MESSAGE), expected)
        response = core.get_last_language_response()
        self.assertTrue(response.needs_fallback)
        self.assertIsNone(response.response_text)

    def test_deterministic_core_generation_is_still_deferred_with_no_text(self):
        core = self.core()
        self._teach(core)
        response = core.generate_language_response(core.understand_language("what is python"))
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertIsNone(response.response_text)

    def test_core_behaviour_with_no_learned_response_pattern_is_preserved(self):
        core = self.core()
        assert core.teach_sentence_pattern("en", GREETING_PATTERN).status == _r.STATUS_CREATED
        assert core.bind_pattern_meaning("en", GREETING_PATTERN, "greeting").success
        ctx = ResponseGenerationRequest(core.understand_language("good morning"),
                                        context=core.context).generation_context
        self.assertEqual(ctx["response_pattern_rendering"]["status"], STATUS_NOT_FOUND)
        self.assertIsNone(ctx["response_pattern_rendering"]["rendered_text"])
        self.assertEqual(ctx["response_action"], "greet")
        self.assertEqual(ctx["status"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()
