"""
Tests for Prompt 422 - Learned Sentence Structure Extraction.

`LearnedSentenceStructureExtractor` (language_intelligence/
learned_sentence_structure.py) reports the ordered fixed / variable
components of a message that matches a learned sentence pattern
(Prompt 421, `LearnedPatternMatcher`) - deterministically, from the
learned pattern's own template only, never guessing a role, a split or
a meaning the pattern did not define.

Run directly:
    python -m unittest tests.test_learned_sentence_structure -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from language_intelligence.language_learning_store import LanguageLearningStore, ITEM_TYPE_PATTERN
from language_intelligence.learned_pattern_matching import (
    LearnedPatternMatcher, LearnedPatternMatchResult,
    STATUS_MATCHED, STATUS_NOT_FOUND, STATUS_AMBIGUOUS, STATUS_NOT_RESOLVED,
    REASON_EMPTY_MESSAGE, REASON_NO_PATTERN_MATCHED, REASON_MULTIPLE_PATTERNS_MATCHED,
    REASON_INDETERMINATE_STRUCTURE,
)
from language_intelligence.learned_sentence_structure import (
    LearnedSentenceStructureExtractor, LearnedSentenceStructureResult,
    COMPONENT_FIXED, COMPONENT_VARIABLE, COMPONENT_UNRESOLVED,
    REASON_STRUCTURE_EXTRACTED, REASON_STRUCTURE_MISMATCH,
)


class _ExtractorTestCase(unittest.TestCase):
    """A fresh on-disk MemorySystem + LanguageLearningStore (Prompt 416),
    the Prompt 421 matcher over it, and the Prompt 422 extractor over
    that - mirrors _MatcherTestCase in test_learned_pattern_matching.py."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "memory.db")
        self.memory = MemorySystem(db_path)
        self.items = LanguageLearningStore(self.memory)
        self.matcher = LearnedPatternMatcher(self.items)
        self.extractor = LearnedSentenceStructureExtractor(self.matcher)

    def tearDown(self):
        self._tmpdir.cleanup()

    def kinds(self, result):
        return [component["kind"] for component in result.components]

    def texts(self, result):
        return [component["text"] for component in result.components]


class TestSingleVariableStructure(_ExtractorTestCase):
    """1. Single-variable structural extraction."""

    def test_persian_single_variable_pattern_is_split_into_components(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم",
                               meaning={"intent": "likes_thing"})
        result = self.extractor.extract("من کتاب را دوست دارم", language="persian")
        self.assertIsInstance(result, LearnedSentenceStructureResult)
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertTrue(result.matched)
        self.assertEqual(result.reason, REASON_STRUCTURE_EXTRACTED)
        self.assertEqual(self.kinds(result), [COMPONENT_FIXED, COMPONENT_VARIABLE, COMPONENT_FIXED])
        self.assertEqual(self.texts(result), ["من", "کتاب", "را دوست دارم"])

    def test_variable_component_carries_name_and_value(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        result = self.extractor.extract("من کتاب را دوست دارم", language="persian")
        variable = result.components[1]
        self.assertEqual(variable["variable_name"], "X")
        self.assertEqual(variable["value"], "کتاب")
        self.assertEqual(variable["text"], "کتاب")
        self.assertEqual(variable["variable_names"], [])

    def test_english_single_variable_pattern(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        result = self.extractor.extract("I love green tea", language="english")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.variables, {"thing": "green tea"})
        self.assertEqual(self.kinds(result), [COMPONENT_FIXED, COMPONENT_VARIABLE])

    def test_anonymous_placeholder_uses_the_matchers_auto_name(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "___ is great")
        result = self.extractor.extract("Python is great", language="english")
        self.assertEqual(result.components[0]["variable_name"], "var_1")
        self.assertEqual(result.components[0]["value"], "Python")

    def test_matched_pattern_identity_is_reported(self):
        item = self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        result = self.extractor.extract("من کتاب را دوست دارم", language="persian")
        self.assertEqual(result.matched_pattern_id, item["id"])
        self.assertEqual(result.matched_pattern_text, "من {{X}} را دوست دارم")
        self.assertEqual(result.language, "persian")


class TestMultipleVariableStructure(_ExtractorTestCase):
    """2. Multiple-variable extraction, 3. correct variable/value association."""

    PATTERN = "من {{X}} را به {{Y}} می‌دهم"

    def setUp(self):
        super().setUp()
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, self.PATTERN,
                               meaning={"intent": "give"})

    def test_two_variables_are_both_extracted_in_order(self):
        result = self.extractor.extract("من کتاب را به علی می‌دهم", language="persian")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(
            self.kinds(result),
            [COMPONENT_FIXED, COMPONENT_VARIABLE, COMPONENT_FIXED, COMPONENT_VARIABLE,
             COMPONENT_FIXED],
        )
        self.assertEqual(self.texts(result), ["من", "کتاب", "را به", "علی", "می‌دهم"])

    def test_x_and_y_values_stay_separate(self):
        result = self.extractor.extract("من کتاب را به علی می‌دهم", language="persian")
        by_name = {c["variable_name"]: c["value"] for c in result.components
                   if c["kind"] == COMPONENT_VARIABLE}
        self.assertEqual(by_name, {"X": "کتاب", "Y": "علی"})
        self.assertEqual(result.variables, {"X": "کتاب", "Y": "علی"})

    def test_swapping_the_values_swaps_the_association(self):
        first = self.extractor.extract("من کتاب را به علی می‌دهم", language="persian")
        second = self.extractor.extract("من علی را به کتاب می‌دهم", language="persian")
        self.assertEqual(first.variables, {"X": "کتاب", "Y": "علی"})
        self.assertEqual(second.variables, {"X": "علی", "Y": "کتاب"})

    def test_multi_word_values_are_kept_whole_and_separate(self):
        result = self.extractor.extract("من یک کتاب قدیمی را به دوست خوبم می‌دهم",
                                        language="persian")
        self.assertEqual(result.variables, {"X": "یک کتاب قدیمی", "Y": "دوست خوبم"})

    def test_values_agree_with_the_prompt_421_match(self):
        message = "من کتاب را به علی می‌دهم"
        match = self.matcher.match(message, language="persian")
        result = self.extractor.from_match(match)
        self.assertEqual(result.variables, match.variables)

    def test_same_variable_name_twice_keeps_both_components(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{X}} and {{X}} differ")
        result = self.extractor.extract("cats and dogs differ", language="english")
        self.assertEqual(result.status, STATUS_MATCHED)
        values = [c["value"] for c in result.components if c["kind"] == COMPONENT_VARIABLE]
        self.assertEqual(values, ["cats", "dogs"])


class TestFixedComponentPreservation(_ExtractorTestCase):
    """4. Fixed component preservation."""

    def test_fixed_components_keep_the_pattern_literals(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را به {{Y}} می‌دهم")
        result = self.extractor.extract("من کتاب را به علی می‌دهم", language="persian")
        fixed = [c for c in result.components if c["kind"] == COMPONENT_FIXED]
        self.assertEqual([c["pattern_segment"] for c in fixed], ["من", "را به", "می‌دهم"])
        self.assertEqual([c["text"] for c in fixed], ["من", "را به", "می‌دهم"])
        for component in fixed:
            self.assertIsNone(component["variable_name"])
            self.assertIsNone(component["value"])

    def test_persian_zwnj_is_preserved_in_a_fixed_component(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} می‌خواهم")
        result = self.extractor.extract("من آب می‌خواهم", language="persian")
        self.assertEqual(result.components[-1]["text"], "می‌خواهم")
        self.assertIn("\u200c", result.components[-1]["text"])

    def test_fixed_text_reports_message_case_and_segment_reports_taught_case(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "Good Morning {{name}}")
        result = self.extractor.extract("good morning Sara", language="english")
        fixed = result.components[0]
        self.assertEqual(fixed["text"], "good morning")
        self.assertEqual(fixed["pattern_segment"], "Good Morning")
        self.assertEqual(result.components[1]["value"], "Sara")

    def test_a_pattern_without_variables_is_one_fixed_component(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "hello there")
        result = self.extractor.extract("hello there", language="english")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(self.kinds(result), [COMPONENT_FIXED])
        self.assertEqual(result.variables, {})


class TestComponentOrdering(_ExtractorTestCase):
    """5. Component ordering."""

    def setUp(self):
        super().setUp()
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را به {{Y}} می‌دهم")

    def test_positions_are_consecutive_from_zero_in_pattern_order(self):
        result = self.extractor.extract("من کتاب را به علی می‌دهم", language="persian")
        self.assertEqual([c["position"] for c in result.components], [0, 1, 2, 3, 4])

    def test_offsets_are_increasing_and_non_overlapping(self):
        result = self.extractor.extract("من کتاب را به علی می‌دهم", language="persian")
        previous_end = 0
        for component in result.components:
            self.assertGreaterEqual(component["start"], previous_end)
            self.assertLess(component["start"], component["end"])
            previous_end = component["end"]

    def test_offsets_index_the_normalized_message(self):
        result = self.extractor.extract("من کتاب را به علی می‌دهم", language="persian")
        for component in result.components:
            self.assertEqual(
                result.normalized_message[component["start"]:component["end"]],
                component["text"],
            )

    def test_components_reassemble_the_normalized_message(self):
        result = self.extractor.extract("من کتاب را به علی می‌دهم", language="persian")
        self.assertEqual(" ".join(self.texts(result)), result.normalized_message)

    def test_irregular_whitespace_does_not_disturb_order_or_offsets(self):
        result = self.extractor.extract("  من   کتاب  را به   علی می‌دهم ", language="persian")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(self.texts(result), ["من", "کتاب", "را به", "علی", "می‌دهم"])
        for component in result.components:
            self.assertEqual(
                result.normalized_message[component["start"]:component["end"]],
                component["text"],
            )


class TestUnresolvedComponent(_ExtractorTestCase):
    """6. Unknown / unresolved component - preserved, never guessed."""

    def setUp(self):
        super().setUp()
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "{{A}} {{B}} خوب است",
                               meaning={"intent": "praise"})

    def test_adjacent_variables_are_reported_as_one_unresolved_component(self):
        result = self.extractor.extract("سیب سرخ خوب است", language="persian")
        self.assertEqual(result.status, STATUS_NOT_RESOLVED)
        self.assertEqual(result.reason, REASON_INDETERMINATE_STRUCTURE)
        self.assertEqual(self.kinds(result), [COMPONENT_UNRESOLVED, COMPONENT_FIXED])
        unresolved = result.components[0]
        self.assertEqual(unresolved["text"], "سیب سرخ")
        self.assertEqual(unresolved["variable_names"], ["A", "B"])

    def test_no_split_is_invented_for_the_unresolved_run(self):
        result = self.extractor.extract("سیب سرخ خوب است", language="persian")
        unresolved = result.components[0]
        self.assertIsNone(unresolved["variable_name"])
        self.assertIsNone(unresolved["value"])
        self.assertEqual(result.variables, {})

    def test_determined_parts_of_an_unresolved_pattern_are_still_reported(self):
        result = self.extractor.extract("سیب سرخ خوب است", language="persian")
        fixed = result.components[1]
        self.assertEqual(fixed["kind"], COMPONENT_FIXED)
        self.assertEqual(fixed["text"], "خوب است")

    def test_unresolved_result_claims_no_pattern_and_no_meaning(self):
        result = self.extractor.extract("سیب سرخ خوب است", language="persian")
        self.assertFalse(result.matched)
        self.assertIsNone(result.matched_pattern_id)
        self.assertIsNone(result.matched_pattern_text)
        self.assertIsNone(result.meaning)
        self.assertIsNone(result.confidence)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0]["pattern_text"], "{{A}} {{B}} خوب است")

    def test_three_adjacent_variables_form_one_run_with_all_names(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{A}} {{B}} {{C}} done")
        result = self.extractor.extract("one two three done", language="english")
        self.assertEqual(result.status, STATUS_NOT_RESOLVED)
        self.assertEqual(result.components[0]["variable_names"], ["A", "B", "C"])
        self.assertEqual(result.components[0]["text"], "one two three")

    def test_isolated_variable_next_to_an_unresolved_run_stays_resolved(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{A}} {{B}} then {{C}}")
        result = self.extractor.extract("red big then car", language="english")
        self.assertEqual(result.status, STATUS_NOT_RESOLVED)
        self.assertEqual(
            self.kinds(result), [COMPONENT_UNRESOLVED, COMPONENT_FIXED, COMPONENT_VARIABLE])
        self.assertEqual(result.components[0]["text"], "red big")
        self.assertEqual(result.components[2]["variable_name"], "C")
        self.assertEqual(result.components[2]["value"], "car")

    def test_several_unresolved_candidates_report_no_components(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "{{P}} {{Q}} است")
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "{{R}} {{S}} خوب است")
        result = self.extractor.extract("سیب سرخ خوب است", language="persian")
        self.assertEqual(result.status, STATUS_NOT_RESOLVED)
        self.assertGreater(len(result.candidates), 1)
        self.assertEqual(result.components, [])
        self.assertIsNone(result.meaning)

    def test_message_matching_nothing_is_not_found_with_no_components(self):
        result = self.extractor.extract("سلام دوست من", language="persian")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_NO_PATTERN_MATCHED)
        self.assertEqual(result.components, [])
        self.assertIsNone(result.meaning)

    def test_empty_message_is_not_found(self):
        result = self.extractor.extract("   ", language="persian")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.reason, REASON_EMPTY_MESSAGE)
        self.assertEqual(result.components, [])

    def test_a_structure_that_disagrees_with_the_match_is_never_reported(self):
        # A hand-built match whose variables disagree with what the
        # template actually captures - the defensive cross-check.
        bad = LearnedPatternMatchResult(
            "I love tea", STATUS_MATCHED, 7, "I love {{thing}}", {"thing": "coffee"},
            {"intent": "likes"}, "english", None, 0.9, "taught", [],
            "single_learned_pattern_matched", False, {"max_patterns": 50},
        )
        result = self.extractor.from_match(bad)
        self.assertEqual(result.status, STATUS_NOT_RESOLVED)
        self.assertEqual(result.reason, REASON_STRUCTURE_MISMATCH)
        self.assertEqual(result.components, [])
        self.assertIsNone(result.matched_pattern_id)
        self.assertIsNone(result.meaning)


class TestAmbiguousPattern(_ExtractorTestCase):
    """7. Ambiguous pattern."""

    def setUp(self):
        super().setUp()
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{A}} is a {{B}}",
                               meaning={"intent": "classify"})
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "___ is a ___",
                               meaning={"intent": "define"})

    def test_two_equally_matching_patterns_report_ambiguous(self):
        result = self.extractor.extract("Python is a language", language="english")
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertEqual(result.reason, REASON_MULTIPLE_PATTERNS_MATCHED)
        self.assertFalse(result.matched)

    def test_ambiguous_result_picks_no_structure_and_no_meaning(self):
        result = self.extractor.extract("Python is a language", language="english")
        self.assertEqual(result.components, [])
        self.assertIsNone(result.matched_pattern_id)
        self.assertIsNone(result.matched_pattern_text)
        self.assertIsNone(result.meaning)
        self.assertEqual(result.variables, {})

    def test_every_candidate_is_preserved_with_its_own_variables(self):
        result = self.extractor.extract("Python is a language", language="english")
        self.assertEqual(len(result.candidates), 2)
        by_text = {c["pattern_text"]: c for c in result.candidates}
        self.assertEqual(by_text["{{A}} is a {{B}}"]["variables"],
                         {"A": "Python", "B": "language"})
        self.assertEqual(by_text["___ is a ___"]["variables"],
                         {"var_1": "Python", "var_2": "language"})


class TestLanguageAndLocaleSafety(_ExtractorTestCase):
    """8. Language mismatch (and locale)."""

    def setUp(self):
        super().setUp()
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم",
                               meaning={"intent": "likes_thing", "locale": "fa-IR"})

    def test_persian_pattern_is_not_used_for_an_english_request(self):
        result = self.extractor.extract("من کتاب را دوست دارم", language="english")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.components, [])
        self.assertIsNone(result.matched_pattern_id)

    def test_english_message_does_not_match_a_persian_pattern(self):
        result = self.extractor.extract("I love books", language="persian")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.components, [])

    def test_language_aliases_still_find_the_pattern(self):
        result = self.extractor.extract("من کتاب را دوست دارم", language="fa")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.language, "persian")

    def test_mismatching_locale_is_not_found(self):
        result = self.extractor.extract("من کتاب را دوست دارم", language="persian",
                                        locale="fa-AF")
        self.assertEqual(result.status, STATUS_NOT_FOUND)
        self.assertEqual(result.components, [])

    def test_matching_locale_is_reported(self):
        result = self.extractor.extract("من کتاب را دوست دارم", language="persian",
                                        locale="fa-IR")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.locale, "fa-IR")

    def test_patterns_own_locale_is_reported_when_the_call_gave_none(self):
        result = self.extractor.extract("من کتاب را دوست دارم", language="persian")
        self.assertEqual(result.locale, "fa-IR")

    def test_a_locale_agnostic_pattern_reports_the_requested_locale(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "I love {{thing}}")
        result = self.extractor.extract("I love tea", language="english", locale="en-GB")
        self.assertEqual(result.status, STATUS_MATCHED)
        self.assertEqual(result.locale, "en-GB")

    def test_same_structure_taught_in_two_languages_stays_language_scoped(self):
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "{{X}} is here")
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "{{X}} اینجاست")
        english = self.extractor.extract("tea is here", language="english")
        persian = self.extractor.extract("چای اینجاست", language="persian")
        self.assertEqual(english.variables, {"X": "tea"})
        self.assertEqual(persian.variables, {"X": "چای"})
        self.assertEqual(english.language, "english")
        self.assertEqual(persian.language, "persian")


class TestOriginalMessagePreservation(_ExtractorTestCase):
    """9. Original message preservation."""

    def setUp(self):
        super().setUp()
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")

    def test_original_message_is_verbatim_including_whitespace(self):
        raw = "  من   کتاب را   دوست دارم  "
        result = self.extractor.extract(raw, language="persian")
        self.assertEqual(result.original_message, raw)
        self.assertEqual(result.normalized_message, "من کتاب را دوست دارم")
        self.assertNotEqual(result.original_message, result.normalized_message)

    def test_original_message_is_kept_for_a_non_match_too(self):
        raw = "  یک جمله دیگر  "
        result = self.extractor.extract(raw, language="persian")
        self.assertEqual(result.original_message, raw)

    def test_from_match_can_override_the_original_message(self):
        match = self.matcher.match("من کتاب را دوست دارم", language="persian")
        result = self.extractor.from_match(match, original_message="  من  کتاب را دوست دارم ")
        self.assertEqual(result.original_message, "  من  کتاب را دوست دارم ")
        self.assertEqual(result.normalized_message, "من کتاب را دوست دارم")
        self.assertEqual(result.status, STATUS_MATCHED)


class TestMeaningPreservation(_ExtractorTestCase):
    """10. Meaning (and confidence/source) preservation."""

    def test_the_patterns_own_stored_meaning_is_carried_unchanged(self):
        meaning = {"intent": "likes_thing", "slots": {"X": "thing"}}
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم",
                               meaning=meaning, confidence=0.8, source="taught_by_user")
        result = self.extractor.extract("من کتاب را دوست دارم", language="persian")
        self.assertEqual(result.meaning, meaning)
        self.assertEqual(result.confidence, 0.8)
        self.assertEqual(result.source, "taught_by_user")

    def test_result_agrees_with_the_prompt_421_result(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم",
                               meaning={"intent": "likes_thing"}, confidence=0.6, source="s")
        message = "من کتاب را دوست دارم"
        match = self.matcher.match(message, language="persian")
        result = self.extractor.from_match(match)
        self.assertEqual(result.meaning, match.meaning)
        self.assertEqual(result.confidence, match.confidence)
        self.assertEqual(result.source, match.source)
        self.assertEqual(result.matched_pattern_id, match.matched_pattern_id)
        self.assertEqual(result.matched_pattern_text, match.matched_pattern_text)

    def test_a_pattern_taught_without_meaning_gets_no_invented_meaning(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        message = "من کتاب را دوست دارم"
        result = self.extractor.extract(message, language="persian")
        self.assertEqual(result.status, STATUS_MATCHED)
        # Exactly what the store holds (empty), never anything derived.
        self.assertEqual(result.meaning, self.matcher.match(message, language="persian").meaning)
        self.assertFalse(result.meaning)

    def test_extraction_does_not_alter_the_stored_pattern(self):
        item = self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم",
                                     meaning={"intent": "likes_thing"})
        self.extractor.extract("من کتاب را دوست دارم", language="persian")
        stored = self.items.get_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        self.assertEqual(stored["meaning"], {"intent": "likes_thing"})
        self.assertEqual(stored["version"], item["version"])


class TestResultShapeAndPurity(_ExtractorTestCase):
    def test_to_dict_is_json_serializable_and_complete(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم",
                               meaning={"intent": "likes_thing"})
        as_dict = self.extractor.extract("من کتاب را دوست دارم", language="persian").to_dict()
        json.dumps(as_dict, ensure_ascii=False)
        for key in ("original_message", "normalized_message", "status", "matched",
                    "matched_pattern_id", "matched_pattern_text", "components", "meaning",
                    "language", "locale", "confidence", "source", "candidates", "reason",
                    "truncated"):
            self.assertIn(key, as_dict)
        for key in ("position", "kind", "text", "start", "end", "pattern_segment",
                    "variable_name", "value", "variable_names"):
            self.assertIn(key, as_dict["components"][0])

    def test_extraction_writes_nothing_to_the_learning_store(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        before = self.items.items_for_language("persian")
        self.extractor.extract("من کتاب را دوست دارم", language="persian")
        self.extractor.extract("چیز دیگری", language="persian")
        self.assertEqual(self.items.items_for_language("persian"), before)

    def test_extraction_is_deterministic(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را به {{Y}} می‌دهم")
        first = self.extractor.extract("من کتاب را به علی می‌دهم", language="persian").to_dict()
        second = self.extractor.extract("من کتاب را به علی می‌دهم", language="persian").to_dict()
        self.assertEqual(first, second)

    def test_from_match_does_not_run_a_second_match(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم")
        calls = []

        class _CountingMatcher(LearnedPatternMatcher):
            def match(self, *args, **kwargs):
                calls.append(1)
                return super().match(*args, **kwargs)

        matcher = _CountingMatcher(self.items)
        extractor = LearnedSentenceStructureExtractor(matcher)
        match = matcher.match("من کتاب را دوست دارم", language="persian")
        extractor.from_match(match)
        extractor.from_match(match)
        self.assertEqual(len(calls), 1)
        extractor.extract("من کتاب را دوست دارم", language="persian")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
