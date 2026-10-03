"""
Tests for Prompt 423 - Learned Sentence Pattern Teaching.

`LearnedPatternTeacher` (language_intelligence/learned_pattern_teaching.py)
is the one explicit operation for teaching a reusable sentence pattern to
the existing language-learning system. A taught pattern is an ordinary
`LanguageLearningStore` item (item_type=pattern, Prompt 416), so the
Prompt 421 matcher and the Prompt 422 structure extractor find it with no
change. Nothing is inferred, and an invalid pattern stores nothing.

Run directly:
    python -m unittest tests.test_learned_pattern_teaching -v
"""

import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from language_intelligence.language_learning_store import (
    LanguageLearningStore, ITEM_TYPE_PATTERN, ITEM_TYPE_WORD,
)
from language_intelligence.language_relationships import LanguageRelationshipStore, item_ref
from language_intelligence.learned_pattern_matching import (
    LearnedPatternMatcher, _split_template, _compile_pattern,
    STATUS_MATCHED, STATUS_NOT_FOUND, STATUS_AMBIGUOUS, STATUS_NOT_RESOLVED,
)
from language_intelligence.learned_sentence_structure import (
    LearnedSentenceStructureExtractor, COMPONENT_FIXED, COMPONENT_VARIABLE, COMPONENT_UNRESOLVED,
)
from language_intelligence.learned_pattern_teaching import (
    LearnedPatternTeacher, LearnedPatternTeachingResult,
    STATUS_CREATED, STATUS_ALREADY_EXISTS, STATUS_INVALID, STATUS_CONFLICT,
    REASON_PATTERN_TAUGHT, REASON_IDENTICAL_PATTERN_EXISTS, REASON_LOCALE_DIFFERS,
    REASON_VARIABLE_NAMES_DIFFER,
    ERROR_EMPTY_PATTERN, ERROR_PATTERN_NOT_TEXT, ERROR_MALFORMED_VARIABLE,
    ERROR_UNNAMED_VARIABLE, ERROR_DUPLICATE_VARIABLE, ERROR_NO_FIXED_COMPONENT,
    ERROR_INVALID_LANGUAGE, ERROR_INVALID_LOCALE, ERROR_LOCALE_LANGUAGE_MISMATCH,
    ERROR_LOCALE_CONFLICTS_WITH_MEANING, ERROR_INVALID_MEANING, ERROR_INVALID_CONFIDENCE,
    ERROR_INVALID_SOURCE, ERROR_INVALID_EXAMPLES,
    WARNING_ADJACENT_VARIABLES, WARNING_NOT_NFKC, WARNING_EXAMPLE_MISMATCH,
)

from core.core import Core

GIVE = "من {{X}} را به {{Y}} می‌دهم"
LIKE = "من {{X}} را دوست دارم"


class _TeacherTestCase(unittest.TestCase):
    """A fresh on-disk MemorySystem + LanguageLearningStore (Prompt 416),
    the Prompt 421 matcher, the Prompt 422 extractor and the Prompt 423
    teacher over that ONE store - the composition Core itself builds."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = MemorySystem(os.path.join(self._tmpdir.name, "memory.db"))
        self.items = LanguageLearningStore(self.memory)
        self.matcher = LearnedPatternMatcher(self.items)
        self.extractor = LearnedSentenceStructureExtractor(self.matcher)
        self.teacher = LearnedPatternTeacher(self.items)

    def tearDown(self):
        self._tmpdir.cleanup()

    def stored_patterns(self, language=None):
        if language is not None:
            return self.items.items_for_language(language, item_type=ITEM_TYPE_PATTERN)
        rows = []
        for one in self.items.languages():
            rows.extend(self.items.items_for_language(one, item_type=ITEM_TYPE_PATTERN))
        return rows

    def event_count(self):
        return len(self.memory.recent_learning_events(10000))

    def codes(self, result):
        return [error["code"] for error in result.errors]


class TestTeachingAValidPattern(_TeacherTestCase):
    """1. Teaching a valid pattern."""

    def test_valid_pattern_is_created(self):
        result = self.teacher.teach("fa", LIKE)
        self.assertIsInstance(result, LearnedPatternTeachingResult)
        self.assertEqual(result.status, STATUS_CREATED)
        self.assertEqual(result.reason, REASON_PATTERN_TAUGHT)
        self.assertTrue(result.success)
        self.assertTrue(result.created)
        self.assertFalse(result.already_existed)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.updated_fields, [])

    def test_result_reports_id_text_language_and_variables(self):
        result = self.teacher.teach("fa", LIKE)
        self.assertIsInstance(result.pattern_id, int)
        self.assertEqual(result.pattern_text, LIKE)
        self.assertEqual(result.language, "persian")
        self.assertEqual(result.variables, ["X"])
        self.assertIsNone(result.locale)

    def test_to_dict_is_json_serializable_and_complete(self):
        as_dict = self.teacher.teach("fa", LIKE, locale="fa-IR", meaning={"intent": "likes"},
                                     confidence=0.5, source="user",
                                     examples=["من چای را دوست دارم"]).to_dict()
        json.dumps(as_dict, ensure_ascii=False)
        for key in ("status", "success", "created", "already_existed", "updated_fields",
                    "pattern_id", "pattern_text", "language", "locale", "variables",
                    "components", "meaning", "confidence", "source", "examples", "warnings",
                    "errors", "reason"):
            self.assertIn(key, as_dict)

    def test_teaching_is_recorded_as_a_normal_learning_event(self):
        before = self.event_count()
        self.teacher.teach("fa", LIKE)
        self.assertEqual(self.event_count(), before + 1)

    def test_teach_is_deterministic(self):
        first = self.teacher.teach("fa", LIKE, meaning={"intent": "likes"}).to_dict()
        second_store = LanguageLearningStore(
            MemorySystem(os.path.join(self._tmpdir.name, "second.db")))
        second = LearnedPatternTeacher(second_store).teach(
            "fa", LIKE, meaning={"intent": "likes"}).to_dict()
        self.assertEqual(first, second)


class TestRetrievingTheTaughtPattern(_TeacherTestCase):
    """2. Retrieving the newly taught pattern (Prompt 416 store)."""

    def test_pattern_is_retrievable_through_get_item(self):
        result = self.teacher.teach("fa", LIKE, meaning={"intent": "likes"})
        item = self.items.get_item("fa", ITEM_TYPE_PATTERN, LIKE)
        self.assertIsNotNone(item)
        self.assertEqual(item["id"], result.pattern_id)
        self.assertEqual(item["key"], LIKE)
        self.assertEqual(item["item_type"], ITEM_TYPE_PATTERN)
        self.assertEqual(item["language"], "persian")

    def test_pattern_is_listed_for_its_language_only(self):
        self.teacher.teach("fa", LIKE)
        self.assertEqual([p["key"] for p in self.stored_patterns("persian")], [LIKE])
        self.assertEqual(self.stored_patterns("english"), [])

    def test_pattern_is_retrievable_through_core(self):
        core = Core(memory_db_path=os.path.join(self._tmpdir.name, "core.db"))
        result = core.teach_sentence_pattern("fa", LIKE, meaning={"intent": "likes"})
        item = core.get_language_item("fa", ITEM_TYPE_PATTERN, LIKE)
        self.assertEqual(item["id"], result.pattern_id)

    def test_stored_pattern_text_is_verbatim(self):
        odd = "  من   {{X}}  را دوست دارم "
        result = self.teacher.teach("fa", odd)
        self.assertEqual(result.pattern_text, odd)
        self.assertEqual(self.stored_patterns()[0]["key"], odd)

    def test_teaching_marks_how_the_item_was_learned(self):
        self.teacher.teach("fa", LIKE)
        self.assertEqual(self.stored_patterns()[0]["learning_method"], "explicit_pattern_teaching")


class TestRecognitionAfterTeaching(_TeacherTestCase):
    """3. Prompt 421 recognizes matching sentences after teaching."""

    def test_taught_pattern_is_recognized_by_the_matcher(self):
        taught = self.teacher.teach("fa", LIKE, meaning={"intent": "likes_thing"})
        match = self.matcher.match("من کتاب را دوست دارم", language="fa")
        self.assertEqual(match.status, STATUS_MATCHED)
        self.assertEqual(match.matched_pattern_id, taught.pattern_id)
        self.assertEqual(match.matched_pattern_text, LIKE)
        self.assertEqual(match.variables, {"X": "کتاب"})
        self.assertEqual(match.meaning, {"intent": "likes_thing"})

    def test_matcher_finds_it_without_a_language_hint(self):
        self.teacher.teach("fa", LIKE)
        self.assertEqual(self.matcher.match("من کتاب را دوست دارم").status, STATUS_MATCHED)

    def test_message_outside_the_pattern_is_not_found(self):
        self.teacher.teach("fa", LIKE)
        self.assertEqual(self.matcher.match("من کتاب را نمی‌خواهم", language="fa").status,
                         STATUS_NOT_FOUND)

    def test_nothing_is_recognized_before_teaching(self):
        self.assertEqual(self.matcher.match("من کتاب را دوست دارم", language="fa").status,
                         STATUS_NOT_FOUND)
        self.teacher.teach("fa", LIKE)
        self.assertEqual(self.matcher.match("من کتاب را دوست دارم", language="fa").status,
                         STATUS_MATCHED)

    def test_extra_whitespace_in_the_message_still_matches(self):
        self.teacher.teach("fa", LIKE)
        match = self.matcher.match("  من   کتاب  را دوست   دارم ", language="fa")
        self.assertEqual(match.status, STATUS_MATCHED)


class TestStructureExtractionAfterTeaching(_TeacherTestCase):
    """4. Prompt 422 extracts the structure after teaching."""

    def test_structure_is_extracted_from_a_taught_pattern(self):
        taught = self.teacher.teach("fa", GIVE, meaning={"intent": "give"})
        structure = self.extractor.extract("من کتاب را به علی می‌دهم", language="fa")
        self.assertEqual(structure.status, STATUS_MATCHED)
        self.assertEqual(structure.matched_pattern_id, taught.pattern_id)
        self.assertEqual(
            [c["kind"] for c in structure.components],
            [COMPONENT_FIXED, COMPONENT_VARIABLE, COMPONENT_FIXED, COMPONENT_VARIABLE,
             COMPONENT_FIXED],
        )
        self.assertEqual(structure.variables, {"X": "کتاب", "Y": "علی"})
        self.assertEqual(structure.meaning, {"intent": "give"})

    def test_taught_components_agree_with_the_extracted_structure(self):
        taught = self.teacher.teach("fa", GIVE)
        structure = self.extractor.extract("من کتاب را به علی می‌دهم", language="fa")
        taught_fixed = [c["text"] for c in taught.components if c["kind"] == COMPONENT_FIXED]
        extracted_fixed = [c["pattern_segment"] for c in structure.components
                           if c["kind"] == COMPONENT_FIXED]
        self.assertEqual(taught_fixed, extracted_fixed)
        taught_vars = [c["variable_name"] for c in taught.components
                       if c["kind"] == COMPONENT_VARIABLE]
        extracted_vars = [c["variable_name"] for c in structure.components
                          if c["kind"] == COMPONENT_VARIABLE]
        self.assertEqual(taught_vars, extracted_vars)

    def test_adjacent_taught_variables_are_reported_unresolved_not_guessed(self):
        self.teacher.teach("fa", "{{A}} {{B}} خوب است")
        structure = self.extractor.extract("سیب سرخ خوب است", language="fa")
        self.assertEqual(structure.status, STATUS_NOT_RESOLVED)
        self.assertEqual(structure.components[0]["kind"], COMPONENT_UNRESOLVED)
        self.assertEqual(structure.components[0]["variable_names"], ["A", "B"])


class TestVariablePreservation(_TeacherTestCase):
    """5. Variable preservation - names, order, literals."""

    def test_variable_names_are_kept_exactly_including_case_and_underscores(self):
        result = self.teacher.teach("en", "send {{Item_1}} to {{recipient}} now")
        self.assertEqual(result.variables, ["Item_1", "recipient"])

    def test_names_are_case_sensitive(self):
        result = self.teacher.teach("en", "{{x}} likes {{X}}")
        self.assertEqual(result.status, STATUS_CREATED)
        self.assertEqual(result.variables, ["x", "X"])
        match = self.matcher.match("tea likes milk", language="en")
        self.assertEqual(match.variables, {"x": "tea", "X": "milk"})

    def test_components_keep_order_and_fixed_literals(self):
        result = self.teacher.teach("fa", GIVE)
        self.assertEqual(
            [(c["kind"], c["text"], c["variable_name"]) for c in result.components],
            [(COMPONENT_FIXED, "من", None), (COMPONENT_VARIABLE, None, "X"),
             (COMPONENT_FIXED, "را به", None), (COMPONENT_VARIABLE, None, "Y"),
             (COMPONENT_FIXED, "می‌دهم", None)],
        )
        self.assertEqual([c["position"] for c in result.components], [0, 1, 2, 3, 4])

    def test_spaces_inside_braces_do_not_change_the_name(self):
        result = self.teacher.teach("en", "I love {{ thing }}")
        self.assertEqual(result.variables, ["thing"])
        self.assertEqual(self.matcher.match("I love tea", language="en").variables,
                         {"thing": "tea"})

    def test_pattern_without_variables_is_allowed(self):
        result = self.teacher.teach("en", "good morning")
        self.assertEqual(result.status, STATUS_CREATED)
        self.assertEqual(result.variables, [])
        self.assertEqual(self.matcher.match("good morning", language="en").status,
                         STATUS_MATCHED)

    def test_zwnj_in_literals_is_preserved(self):
        result = self.teacher.teach("fa", "من {{X}} می‌خواهم")
        self.assertEqual(result.pattern_text, "من {{X}} می‌خواهم")
        self.assertIn("\u200c", result.components[-1]["text"])
        match = self.matcher.match("من آب می‌خواهم", language="fa")
        self.assertEqual(match.status, STATUS_MATCHED)


class TestMultipleVariables(_TeacherTestCase):
    """6. Multiple variables."""

    def test_two_variables_are_taught_and_kept_separate_in_matching(self):
        result = self.teacher.teach("fa", GIVE)
        self.assertEqual(result.variables, ["X", "Y"])
        match = self.matcher.match("من کتاب را به علی می‌دهم", language="fa")
        self.assertEqual(match.variables, {"X": "کتاب", "Y": "علی"})
        swapped = self.matcher.match("من علی را به کتاب می‌دهم", language="fa")
        self.assertEqual(swapped.variables, {"X": "علی", "Y": "کتاب"})

    def test_three_variables_keep_their_order(self):
        result = self.teacher.teach("en", "{{who}} gave {{what}} to {{whom}} on time")
        self.assertEqual(result.variables, ["who", "what", "whom"])
        match = self.matcher.match("Sara gave a book to Ali on time", language="en")
        self.assertEqual(match.variables, {"who": "Sara", "what": "a book", "whom": "Ali"})

    def test_adjacent_variables_are_accepted_with_a_warning(self):
        result = self.teacher.teach("fa", "{{A}} {{B}} خوب است")
        self.assertEqual(result.status, STATUS_CREATED)
        self.assertEqual([w["code"] for w in result.warnings], [WARNING_ADJACENT_VARIABLES])
        self.assertEqual(result.variables, ["A", "B"])


class TestLanguagePreservation(_TeacherTestCase):
    """7. Language preservation."""

    def test_language_code_is_canonicalized_like_the_rest_of_the_package(self):
        self.assertEqual(self.teacher.teach("fa", LIKE).language, "persian")
        self.assertEqual(self.teacher.teach("en", "I love {{thing}}").language, "english")

    def test_language_aliases_reach_the_same_pattern(self):
        self.teacher.teach("fa", LIKE)
        self.assertIsNotNone(self.items.get_item("persian", ITEM_TYPE_PATTERN, LIKE))
        self.assertIsNotNone(self.items.get_item("FA", ITEM_TYPE_PATTERN, LIKE))
        self.assertEqual(self.teacher.teach("persian", LIKE).status, STATUS_ALREADY_EXISTS)

    def test_a_language_the_project_does_not_know_is_kept_as_is(self):
        result = self.teacher.teach("fi", "minä rakastan {{asia}}")
        self.assertEqual(result.status, STATUS_CREATED)
        self.assertEqual(result.language, "fi")
        self.assertEqual(self.matcher.match("minä rakastan kahvia", language="fi").variables,
                         {"asia": "kahvia"})

    def test_pattern_is_only_used_for_its_own_language(self):
        self.teacher.teach("fa", LIKE)
        self.assertEqual(self.matcher.match("من کتاب را دوست دارم", language="en").status,
                         STATUS_NOT_FOUND)


class TestLocalePreservation(_TeacherTestCase):
    """8. Locale preservation (stored in `meaning["locale"]`, Prompt 421)."""

    def test_locale_is_stored_and_reported(self):
        result = self.teacher.teach("fa", LIKE, locale="fa-IR", meaning={"intent": "likes"})
        self.assertEqual(result.locale, "fa-IR")
        stored = self.stored_patterns()[0]
        self.assertEqual(stored["meaning"], {"intent": "likes", "locale": "fa-IR"})

    def test_locale_without_meaning_is_still_stored(self):
        result = self.teacher.teach("fa", LIKE, locale="fa-IR")
        self.assertEqual(self.stored_patterns()[0]["meaning"], {"locale": "fa-IR"})
        self.assertEqual(result.locale, "fa-IR")

    def test_locale_written_in_meaning_is_the_same_as_the_argument(self):
        result = self.teacher.teach("fa", LIKE, meaning={"intent": "likes", "locale": "fa-IR"})
        self.assertEqual(result.locale, "fa-IR")

    def test_matcher_honours_the_taught_locale(self):
        self.teacher.teach("fa", LIKE, locale="fa-IR")
        message = "من کتاب را دوست دارم"
        self.assertEqual(self.matcher.match(message, language="fa", locale="fa-IR").status,
                         STATUS_MATCHED)
        self.assertEqual(self.matcher.match(message, language="fa", locale="fa-AF").status,
                         STATUS_NOT_FOUND)
        self.assertEqual(self.matcher.match(message, language="fa").status, STATUS_MATCHED)

    def test_extractor_reports_the_taught_locale(self):
        self.teacher.teach("fa", LIKE, locale="fa-IR")
        structure = self.extractor.extract("من کتاب را دوست دارم", language="fa")
        self.assertEqual(structure.locale, "fa-IR")

    def test_no_locale_means_a_locale_agnostic_pattern(self):
        result = self.teacher.teach("fa", LIKE)
        self.assertIsNone(result.locale)
        self.assertEqual(self.matcher.match("من کتاب را دوست دارم", language="fa",
                                            locale="fa-AF").status, STATUS_MATCHED)

    def test_locale_tag_is_stored_verbatim(self):
        self.assertEqual(self.teacher.teach("fa", LIKE, locale=" fa_IR ").locale, "fa_IR")

    def test_locale_of_another_language_is_refused(self):
        result = self.teacher.teach("fa", LIKE, locale="en-US")
        self.assertEqual(result.status, STATUS_INVALID)
        self.assertEqual(self.codes(result), [ERROR_LOCALE_LANGUAGE_MISMATCH])

    def test_locale_that_contradicts_the_meaning_locale_is_refused(self):
        result = self.teacher.teach("fa", LIKE, locale="fa-IR", meaning={"locale": "fa-AF"})
        self.assertEqual(result.status, STATUS_INVALID)
        self.assertEqual(self.codes(result), [ERROR_LOCALE_CONFLICTS_WITH_MEANING])

    def test_malformed_locale_is_refused(self):
        for bad in ("", "  ", "fa IR", "fa-", 5, ["fa"]):
            result = self.teacher.teach("fa", LIKE, locale=bad)
            self.assertEqual(result.status, STATUS_INVALID, repr(bad))
            self.assertIn(ERROR_INVALID_LOCALE, self.codes(result))


class TestMeaningPreservation(_TeacherTestCase):
    """9. Meaning (intention), confidence and source preservation."""

    def test_meaning_is_stored_exactly_as_taught(self):
        meaning = {"intent": "likes_thing", "slots": {"X": "thing"}, "note": "قابل استفاده"}
        result = self.teacher.teach("fa", LIKE, meaning=meaning, confidence=0.8, source="user")
        self.assertEqual(result.meaning, meaning)
        self.assertEqual(self.stored_patterns()[0]["meaning"], meaning)
        self.assertEqual(result.confidence, 0.8)
        self.assertEqual(result.source, "user")

    def test_callers_meaning_dict_is_not_mutated(self):
        meaning = {"intent": "likes_thing"}
        original = copy.deepcopy(meaning)
        self.teacher.teach("fa", LIKE, meaning=meaning, locale="fa-IR")
        self.assertEqual(meaning, original)

    def test_matcher_and_extractor_report_the_taught_meaning(self):
        self.teacher.teach("fa", LIKE, meaning={"intent": "likes_thing"}, confidence=0.6,
                           source="taught")
        match = self.matcher.match("من کتاب را دوست دارم", language="fa")
        self.assertEqual(match.meaning, {"intent": "likes_thing"})
        self.assertEqual(match.confidence, 0.6)
        self.assertEqual(match.source, "taught")
        structure = self.extractor.extract("من کتاب را دوست دارم", language="fa")
        self.assertEqual(structure.meaning, {"intent": "likes_thing"})
        self.assertEqual(structure.confidence, 0.6)

    def test_no_meaning_taught_means_no_meaning_invented(self):
        result = self.teacher.teach("fa", LIKE)
        self.assertEqual(result.meaning, {})
        self.assertIsNone(result.source)

    def test_confidence_defaults_and_clamps_like_the_store(self):
        self.assertEqual(self.teacher.teach("fa", LIKE).confidence, 1.0)
        self.assertEqual(self.teacher.teach("fa", "الف {{X}} ب", confidence=7).confidence, 1.0)
        self.assertEqual(self.teacher.teach("fa", "ج {{X}} د", confidence=-2).confidence, 0.0)

    def test_meaning_must_be_a_json_safe_object(self):
        for bad in ("likes", ["a"], 5, {"f": lambda: 1}, {"s": {1, 2}}):
            result = self.teacher.teach("fa", LIKE, meaning=bad)
            self.assertEqual(result.status, STATUS_INVALID, repr(bad))
            self.assertEqual(self.codes(result), [ERROR_INVALID_MEANING])

    def test_confidence_and_source_must_be_well_formed(self):
        for bad in ("high", True, float("nan"), float("inf"), [1]):
            result = self.teacher.teach("fa", LIKE, confidence=bad)
            self.assertEqual(self.codes(result), [ERROR_INVALID_CONFIDENCE], repr(bad))
        for bad in ("", "  ", 5):
            result = self.teacher.teach("fa", LIKE, source=bad)
            self.assertEqual(self.codes(result), [ERROR_INVALID_SOURCE], repr(bad))


class TestExamplePreservation(_TeacherTestCase):
    """10. Original example text is preserved exactly."""

    def test_examples_are_stored_exactly_as_given(self):
        examples = ["  من   کتاب را دوست دارم  ", "من می‌خوانم کتاب را دوست دارم", "من چای را دوست دارم"]
        result = self.teacher.teach("fa", LIKE, examples=examples)
        self.assertEqual(result.examples, examples)
        self.assertEqual(self.stored_patterns()[0]["examples"], examples)

    def test_zwnj_and_irregular_whitespace_survive_the_round_trip(self):
        example = "من  می‌نویسم\tکتاب را دوست دارم"
        self.teacher.teach("fa", LIKE, examples=[example])
        stored = self.items.get_item("fa", ITEM_TYPE_PATTERN, LIKE)["examples"][0]
        self.assertEqual(stored, example)
        self.assertIn("\u200c", stored)
        self.assertNotEqual(stored, " ".join(example.split()))

    def test_examples_are_not_normalized_to_nfkc(self):
        example = "من ﻛﺘﺎب را دوست دارم"  # presentation forms, changed by NFKC
        self.teacher.teach("fa", LIKE, examples=[example])
        self.assertEqual(self.stored_patterns()[0]["examples"], [example])

    def test_examples_keep_their_order(self):
        examples = ["من ج را دوست دارم", "من الف را دوست دارم", "من ب را دوست دارم"]
        self.teacher.teach("fa", LIKE, examples=examples)
        self.assertEqual(self.stored_patterns()[0]["examples"], examples)

    def test_exact_duplicate_examples_are_stored_once(self):
        self.teacher.teach("fa", LIKE, examples=["من چای را دوست دارم", "من چای را دوست دارم"])
        self.assertEqual(self.stored_patterns()[0]["examples"], ["من چای را دوست دارم"])

    def test_example_that_does_not_fit_the_pattern_is_kept_with_a_warning(self):
        result = self.teacher.teach("fa", LIKE, examples=["من چای را دوست دارم", "hello"])
        self.assertEqual(result.status, STATUS_CREATED)
        self.assertEqual(result.examples, ["من چای را دوست دارم", "hello"])
        self.assertEqual([(w["code"], w["index"]) for w in result.warnings],
                         [(WARNING_EXAMPLE_MISMATCH, 1)])

    def test_examples_must_be_a_list_of_non_empty_strings(self):
        for bad in ("من چای را دوست دارم", ["ok", 5], ["ok", "  "], 7, {"a": 1}):
            result = self.teacher.teach("fa", LIKE, examples=bad)
            self.assertEqual(result.status, STATUS_INVALID, repr(bad))
            self.assertEqual(self.codes(result), [ERROR_INVALID_EXAMPLES])

    def test_a_pattern_that_nfkc_would_change_is_taught_with_a_warning(self):
        result = self.teacher.teach("fa", "من {{X}} ﻣﯽ‌دهم")
        self.assertEqual(result.status, STATUS_CREATED)
        self.assertIn(WARNING_NOT_NFKC, [w["code"] for w in result.warnings])


class TestDuplicateTeaching(_TeacherTestCase):
    """11. Duplicate teaching."""

    def test_identical_pattern_is_not_duplicated(self):
        first = self.teacher.teach("fa", LIKE)
        second = self.teacher.teach("fa", LIKE)
        self.assertEqual(second.status, STATUS_ALREADY_EXISTS)
        self.assertEqual(second.reason, REASON_IDENTICAL_PATTERN_EXISTS)
        self.assertTrue(second.success)
        self.assertFalse(second.created)
        self.assertTrue(second.already_existed)
        self.assertEqual(second.pattern_id, first.pattern_id)
        self.assertEqual(len(self.stored_patterns()), 1)

    def test_same_pattern_through_a_language_alias_is_a_duplicate(self):
        self.teacher.teach("fa", LIKE)
        self.assertEqual(self.teacher.teach("Persian", LIKE).status, STATUS_ALREADY_EXISTS)
        self.assertEqual(len(self.stored_patterns()), 1)

    def test_whitespace_and_case_variants_are_the_same_pattern(self):
        first = self.teacher.teach("en", "I love {{thing}}")
        second = self.teacher.teach("en", "  i  LOVE   {{thing}} ")
        self.assertEqual(second.status, STATUS_ALREADY_EXISTS)
        self.assertEqual(second.pattern_id, first.pattern_id)
        # The stored text is the one first taught - never rewritten.
        self.assertEqual(second.pattern_text, "I love {{thing}}")
        self.assertEqual(len(self.stored_patterns()), 1)

    def test_reteaching_with_nothing_new_writes_nothing(self):
        self.teacher.teach("fa", LIKE, meaning={"intent": "likes"}, confidence=0.5,
                           source="user", examples=["من چای را دوست دارم"])
        version = self.stored_patterns()[0]["version"]
        events = self.event_count()
        result = self.teacher.teach("fa", LIKE, meaning={"intent": "likes"}, confidence=0.5,
                                    source="user", examples=["من چای را دوست دارم"])
        self.assertEqual(result.status, STATUS_ALREADY_EXISTS)
        self.assertEqual(result.updated_fields, [])
        self.assertEqual(self.stored_patterns()[0]["version"], version)
        self.assertEqual(self.event_count(), events)

    def test_metadata_is_updated_only_when_explicitly_supplied(self):
        self.teacher.teach("fa", LIKE, meaning={"intent": "likes"}, confidence=0.5, source="user")
        result = self.teacher.teach("fa", LIKE, confidence=0.9)
        self.assertEqual(result.status, STATUS_ALREADY_EXISTS)
        self.assertEqual(result.updated_fields, ["confidence"])
        stored = self.stored_patterns()[0]
        self.assertEqual(stored["confidence"], 0.9)
        self.assertEqual(stored["meaning"], {"intent": "likes"})
        self.assertEqual(stored["source"], "user")

    def test_supplied_meaning_and_source_replace_the_stored_ones(self):
        self.teacher.teach("fa", LIKE, meaning={"intent": "likes"}, source="user")
        result = self.teacher.teach("fa", LIKE, meaning={"intent": "enjoys"}, source="app")
        self.assertEqual(result.updated_fields, ["meaning", "source"])
        stored = self.stored_patterns()[0]
        self.assertEqual(stored["meaning"], {"intent": "enjoys"})
        self.assertEqual(stored["source"], "app")

    def test_existing_examples_are_preserved_and_new_ones_added(self):
        self.teacher.teach("fa", LIKE, examples=["من چای را دوست دارم"])
        result = self.teacher.teach("fa", LIKE, examples=["من چای را دوست دارم",
                                                          "من کتاب را دوست دارم"])
        self.assertEqual(result.updated_fields, ["examples"])
        self.assertEqual(self.stored_patterns()[0]["examples"],
                         ["من چای را دوست دارم", "من کتاب را دوست دارم"])

    def test_reteaching_without_examples_keeps_existing_examples(self):
        self.teacher.teach("fa", LIKE, examples=["من چای را دوست دارم"])
        self.teacher.teach("fa", LIKE, confidence=0.4)
        self.assertEqual(self.stored_patterns()[0]["examples"], ["من چای را دوست دارم"])

    def test_existing_relationships_are_preserved(self):
        taught = self.teacher.teach("fa", LIKE)
        # The item's own `relationships` column (Prompt 416)...
        self.items.learn_item("fa", ITEM_TYPE_PATTERN, LIKE,
                              relationships=[{"type": "variant_of", "target": "x"}])
        # ...and a Prompt 417 relationship row pointing at the item.
        rels = LanguageRelationshipStore(self.memory, self.items)
        self.items.learn_item("fa", ITEM_TYPE_WORD, "کتاب")
        rels.relate(item_ref("fa", ITEM_TYPE_PATTERN, LIKE), item_ref("fa", ITEM_TYPE_WORD, "کتاب"),
                    "example_word")
        before = rels.relationships_for(item_ref("fa", ITEM_TYPE_PATTERN, LIKE))
        self.assertEqual(len(before), 1)

        result = self.teacher.teach("fa", LIKE, examples=["من کتاب را دوست دارم"],
                                    meaning={"intent": "likes"})
        self.assertEqual(result.status, STATUS_ALREADY_EXISTS)
        self.assertEqual(result.pattern_id, taught.pattern_id)
        stored = self.stored_patterns()[0]
        self.assertEqual(stored["relationships"], [{"type": "variant_of", "target": "x"}])
        self.assertEqual(rels.relationships_for(item_ref("fa", ITEM_TYPE_PATTERN, LIKE)), before)

    def test_same_language_and_locale_is_a_duplicate(self):
        self.teacher.teach("fa", LIKE, locale="fa-IR")
        result = self.teacher.teach("fa", LIKE, locale="fa-IR", confidence=0.3)
        self.assertEqual(result.status, STATUS_ALREADY_EXISTS)
        self.assertEqual(result.locale, "fa-IR")
        self.assertEqual(len(self.stored_patterns()), 1)

    def test_omitting_locale_on_reteach_leaves_the_stored_locale_alone(self):
        self.teacher.teach("fa", LIKE, locale="fa-IR", meaning={"intent": "likes"})
        result = self.teacher.teach("fa", LIKE, examples=["من چای را دوست دارم"])
        self.assertEqual(result.status, STATUS_ALREADY_EXISTS)
        self.assertEqual(result.locale, "fa-IR")
        self.assertEqual(self.stored_patterns()[0]["meaning"],
                         {"intent": "likes", "locale": "fa-IR"})

    def test_replacing_meaning_keeps_the_stored_locale(self):
        self.teacher.teach("fa", LIKE, locale="fa-IR", meaning={"intent": "likes"})
        result = self.teacher.teach("fa", LIKE, meaning={"intent": "enjoys"})
        self.assertEqual(result.updated_fields, ["meaning"])
        self.assertEqual(self.stored_patterns()[0]["meaning"],
                         {"intent": "enjoys", "locale": "fa-IR"})
        self.assertEqual(self.matcher.match("من کتاب را دوست دارم", language="fa",
                                            locale="fa-AF").status, STATUS_NOT_FOUND)

    def test_a_different_explicit_locale_is_a_conflict_and_changes_nothing(self):
        self.teacher.teach("fa", LIKE, locale="fa-IR", meaning={"intent": "likes"})
        before = copy.deepcopy(self.stored_patterns())
        events = self.event_count()
        result = self.teacher.teach("fa", LIKE, locale="fa-AF", meaning={"intent": "other"},
                                    confidence=0.1, examples=["من چای را دوست دارم"])
        self.assertEqual(result.status, STATUS_CONFLICT)
        self.assertEqual(result.reason, REASON_LOCALE_DIFFERS)
        self.assertFalse(result.success)
        self.assertFalse(result.created)
        self.assertTrue(result.already_existed)
        self.assertEqual(result.locale, "fa-IR")
        self.assertEqual(self.codes(result), [REASON_LOCALE_DIFFERS])
        self.assertEqual(self.stored_patterns(), before)
        self.assertEqual(self.event_count(), events)

    def test_teaching_a_locale_for_a_locale_agnostic_pattern_is_a_conflict(self):
        self.teacher.teach("fa", LIKE)
        result = self.teacher.teach("fa", LIKE, locale="fa-IR")
        self.assertEqual(result.status, STATUS_CONFLICT)
        self.assertIsNone(self.stored_patterns()[0]["meaning"].get("locale"))

    def test_variable_names_differing_only_in_case_are_a_conflict(self):
        self.teacher.teach("en", "I love {{Thing}}")
        result = self.teacher.teach("en", "I love {{thing}}")
        self.assertEqual(result.status, STATUS_CONFLICT)
        self.assertEqual(result.reason, REASON_VARIABLE_NAMES_DIFFER)
        self.assertEqual(result.variables, ["Thing"])
        self.assertEqual(len(self.stored_patterns()), 1)
        self.assertEqual(self.stored_patterns()[0]["key"], "I love {{Thing}}")

    def test_duplicate_with_invalid_arguments_is_invalid_not_a_duplicate(self):
        self.teacher.teach("fa", LIKE)
        version = self.stored_patterns()[0]["version"]
        result = self.teacher.teach("fa", LIKE, confidence="high")
        self.assertEqual(result.status, STATUS_INVALID)
        self.assertEqual(self.stored_patterns()[0]["version"], version)


class TestSamePatternInDifferentLanguages(_TeacherTestCase):
    """12. Same pattern in different languages stays separate."""

    def test_same_text_in_two_languages_makes_two_patterns(self):
        fa = self.teacher.teach("fa", "{{X}} is here", meaning={"intent": "presence_fa"})
        en = self.teacher.teach("en", "{{X}} is here", meaning={"intent": "presence_en"})
        self.assertEqual(fa.status, STATUS_CREATED)
        self.assertEqual(en.status, STATUS_CREATED)
        self.assertNotEqual(fa.pattern_id, en.pattern_id)
        self.assertEqual(len(self.stored_patterns()), 2)

    def test_each_language_keeps_its_own_meaning_and_matches_separately(self):
        self.teacher.teach("fa", "{{X}} is here", meaning={"intent": "presence_fa"})
        self.teacher.teach("en", "{{X}} is here", meaning={"intent": "presence_en"})
        fa = self.matcher.match("tea is here", language="fa")
        en = self.matcher.match("tea is here", language="en")
        self.assertEqual(fa.meaning, {"intent": "presence_fa"})
        self.assertEqual(en.meaning, {"intent": "presence_en"})
        self.assertEqual(fa.language, "persian")
        self.assertEqual(en.language, "english")

    def test_teaching_one_language_again_does_not_touch_the_other(self):
        self.teacher.teach("fa", "{{X}} is here", meaning={"intent": "presence_fa"})
        self.teacher.teach("en", "{{X}} is here", meaning={"intent": "presence_en"})
        self.teacher.teach("fa", "{{X}} is here", confidence=0.2)
        self.assertEqual(self.items.get_item("en", ITEM_TYPE_PATTERN, "{{X}} is here")["confidence"],
                         1.0)

    def test_without_a_language_hint_the_shared_pattern_is_ambiguous_not_guessed(self):
        self.teacher.teach("fa", "{{X}} is here")
        self.teacher.teach("en", "{{X}} is here")
        self.assertEqual(self.matcher.match("tea is here").status, STATUS_AMBIGUOUS)


class TestInvalidEmptyPattern(_TeacherTestCase):
    """13. Invalid empty pattern."""

    def test_empty_and_blank_patterns_are_invalid(self):
        for bad in ("", " ", "\n\t  "):
            result = self.teacher.teach("fa", bad)
            self.assertEqual(result.status, STATUS_INVALID, repr(bad))
            self.assertFalse(result.success)
            self.assertEqual(self.codes(result), [ERROR_EMPTY_PATTERN])
            self.assertIsNone(result.pattern_id)
            self.assertEqual(result.variables, [])

    def test_non_string_pattern_is_invalid(self):
        for bad in (None, 5, ["من {{X}}"], {"p": 1}):
            result = self.teacher.teach("fa", bad)
            self.assertEqual(result.status, STATUS_INVALID, repr(bad))
            self.assertEqual(self.codes(result), [ERROR_PATTERN_NOT_TEXT])

    def test_a_pattern_of_only_variables_is_refused(self):
        for bad in ("{{X}}", "{{A}} {{B}}"):
            result = self.teacher.teach("fa", bad)
            self.assertEqual(self.codes(result), [ERROR_NO_FIXED_COMPONENT], bad)

    def test_invalid_language_is_refused(self):
        for bad in ("", "  ", "unknown", None, 5):
            result = self.teacher.teach(bad, LIKE)
            self.assertEqual(result.status, STATUS_INVALID, repr(bad))
            self.assertEqual(self.codes(result), [ERROR_INVALID_LANGUAGE])
            self.assertIsNone(result.language)


class TestInvalidVariableSyntax(_TeacherTestCase):
    """14. Invalid variable syntax."""

    def assertRefused(self, pattern, code):
        result = self.teacher.teach("fa", pattern)
        self.assertEqual(result.status, STATUS_INVALID, repr(pattern))
        self.assertIn(code, self.codes(result), repr(pattern))
        self.assertFalse(result.success)
        self.assertIsNone(result.pattern_id)
        return result

    def test_unbalanced_and_single_braces_are_malformed(self):
        for bad in ("من {{X را دوست دارم", "من X}} را دوست دارم", "من {X} را دوست دارم",
                    "من {{X}}} را دوست دارم", "من {{{X}} را دوست دارم", "من { را دوست دارم"):
            self.assertRefused(bad, ERROR_MALFORMED_VARIABLE)

    def test_names_the_matcher_cannot_read_are_malformed(self):
        for bad in ("من {{1st}} را", "من {{a b}} را", "من {{نام}} را", "من {{a-b}} را",
                    "من {{a.b}} را"):
            self.assertRefused(bad, ERROR_MALFORMED_VARIABLE)

    def test_unnamed_variables_are_refused(self):
        for bad in ("من ___ را دوست دارم", "من {{}} را دوست دارم", "من {{ }} را دوست دارم",
                    "من {{___}} را دوست دارم", "___ is a ___"):
            self.assertRefused(bad, ERROR_UNNAMED_VARIABLE)

    def test_unnamed_variables_are_never_auto_named(self):
        result = self.teacher.teach("en", "___ is a ___")
        self.assertEqual(result.variables, [])
        self.assertEqual(self.stored_patterns(), [])

    def test_duplicate_variable_names_are_refused(self):
        result = self.assertRefused("{{X}} و {{X}} یکسان‌اند", ERROR_DUPLICATE_VARIABLE)
        self.assertEqual(result.errors[0]["variable_name"], "X")

    def test_a_repeated_name_is_reported_once(self):
        result = self.teacher.teach("en", "{{X}} a {{X}} b {{X}}")
        self.assertEqual(self.codes(result), [ERROR_DUPLICATE_VARIABLE])

    def test_all_problems_are_reported_together_and_deterministically(self):
        first = self.teacher.teach("fa", "{{X}} ___ {{X}} {Y}")
        second = self.teacher.teach("fa", "{{X}} ___ {{X}} {Y}")
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(sorted(set(self.codes(first))),
                         sorted([ERROR_UNNAMED_VARIABLE, ERROR_MALFORMED_VARIABLE,
                                 ERROR_DUPLICATE_VARIABLE]))

    def test_names_that_differ_only_in_case_are_not_duplicates(self):
        self.assertEqual(self.teacher.teach("en", "{{x}} then {{X}}").status, STATUS_CREATED)

    def test_the_stricter_gate_does_not_change_raw_pattern_learning(self):
        # Prompt 416 / 421 still accept an anonymous placeholder taught the raw way.
        self.items.learn_item("english", ITEM_TYPE_PATTERN, "___ is a ___")
        match = self.matcher.match("Python is a language", language="english")
        self.assertEqual(match.status, STATUS_MATCHED)
        self.assertEqual(match.variables, {"var_1": "Python", "var_2": "language"})


class TestFailedValidationStoresNothing(_TeacherTestCase):
    """15. Failed validation does not partially store data."""

    def snapshot(self):
        return (copy.deepcopy(self.stored_patterns()), self.event_count(),
                self.items.languages())

    def test_invalid_pattern_leaves_the_store_untouched(self):
        self.teacher.teach("fa", LIKE)
        before = self.snapshot()
        for bad in ("", "من {{X را", "من ___ را", "{{X}} {{X}} است", "{{X}}"):
            self.teacher.teach("fa", bad, meaning={"intent": "x"}, examples=["e"], source="s")
            self.assertEqual(self.snapshot(), before, repr(bad))

    def test_valid_pattern_with_bad_metadata_is_refused_whole(self):
        before = self.snapshot()
        cases = [
            {"confidence": "high"}, {"meaning": "text"}, {"locale": "en-US"},
            {"locale": "not a locale"}, {"examples": ["ok", 3]}, {"source": ""},
            {"meaning": {"locale": "fa-IR"}, "locale": "fa-AF"},
        ]
        for kwargs in cases:
            result = self.teacher.teach("fa", LIKE, **kwargs)
            self.assertEqual(result.status, STATUS_INVALID, kwargs)
            self.assertEqual(self.snapshot(), before, kwargs)
        self.assertEqual(self.matcher.match("من کتاب را دوست دارم", language="fa").status,
                         STATUS_NOT_FOUND)

    def test_invalid_language_stores_nothing_in_any_language(self):
        before = self.snapshot()
        self.teacher.teach("unknown", LIKE, meaning={"intent": "x"})
        self.teacher.teach("", LIKE)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.items.languages(), [])

    def test_invalid_result_carries_errors_and_no_pattern_data(self):
        result = self.teacher.teach("fa", "من {{X را")
        as_dict = result.to_dict()
        self.assertEqual(as_dict["status"], STATUS_INVALID)
        self.assertFalse(as_dict["success"])
        self.assertTrue(as_dict["errors"])
        self.assertIsNone(as_dict["pattern_id"])
        self.assertEqual(as_dict["variables"], [])
        self.assertEqual(as_dict["components"], [])
        self.assertEqual(as_dict["reason"], as_dict["errors"][0]["code"])
        self.assertEqual(as_dict["pattern_text"], "من {{X را")

    def test_invalid_input_never_raises(self):
        for args in ((None, None), (5, {}), ("fa", object())):
            self.teacher.teach(*args)
        for kwargs in ({"meaning": object()}, {"examples": object()}, {"locale": object()},
                       {"confidence": object()}, {"source": object()}):
            self.teacher.teach("fa", LIKE, **kwargs)
        self.assertEqual(self.stored_patterns(), [])


class TestPrompt421And422Regression(_TeacherTestCase):
    """16. Prompts 421 and 422 are unchanged and treat a taught pattern like any other."""

    def _raw_store(self):
        memory = MemorySystem(os.path.join(self._tmpdir.name, "raw.db"))
        items = LanguageLearningStore(memory)
        return items, LearnedPatternMatcher(items), LearnedSentenceStructureExtractor(
            LearnedPatternMatcher(items))

    def test_taught_pattern_behaves_exactly_like_a_raw_learn_item_pattern(self):
        raw_items, raw_matcher, raw_extractor = self._raw_store()
        raw_items.learn_item("persian", ITEM_TYPE_PATTERN, GIVE, meaning={"intent": "give"},
                             confidence=0.7, source="user")
        self.teacher.teach("fa", GIVE, meaning={"intent": "give"}, confidence=0.7, source="user")
        message = "من کتاب را به علی می‌دهم"

        def scrub(payload):
            payload = dict(payload)
            payload.pop("matched_pattern_id", None)
            return payload

        self.assertEqual(scrub(self.matcher.match(message, language="fa").to_dict()),
                         scrub(raw_matcher.match(message, language="fa").to_dict()))
        self.assertEqual(scrub(self.extractor.extract(message, language="fa").to_dict()),
                         scrub(raw_extractor.extract(message, language="fa").to_dict()))

    def test_stored_row_has_the_same_shape_as_a_raw_pattern_row(self):
        raw_items, _, _ = self._raw_store()
        raw = raw_items.learn_item("persian", ITEM_TYPE_PATTERN, LIKE)
        self.teacher.teach("fa", LIKE)
        taught = self.stored_patterns()[0]
        self.assertEqual(set(taught), set(raw))
        self.assertEqual(taught["item_type"], raw["item_type"])
        self.assertEqual(taught["key"], raw["key"])
        self.assertEqual(taught["meaning"], raw["meaning"])

    def test_the_421_regex_for_a_taught_pattern_is_unchanged(self):
        regex, names, indeterminate = _compile_pattern(_split_template(GIVE))
        self.assertEqual(
            regex.pattern, r"^\s*من\s+(\S.*?|\S)\s+را\s+به\s+(\S.*?|\S)\s+می‌دهم\s*$")
        self.assertEqual(names, ["X", "Y"])
        self.assertFalse(indeterminate)

    def test_two_taught_patterns_that_match_equally_are_ambiguous(self):
        self.teacher.teach("en", "{{A}} is a {{B}}", meaning={"intent": "classify"})
        self.teacher.teach("en", "{{P}} is a {{Q}}", meaning={"intent": "define"})
        match = self.matcher.match("Python is a language", language="en")
        self.assertEqual(match.status, STATUS_AMBIGUOUS)
        self.assertEqual(len(match.candidates), 2)
        structure = self.extractor.extract("Python is a language", language="en")
        self.assertEqual(structure.status, STATUS_AMBIGUOUS)
        self.assertEqual(structure.components, [])

    def test_taught_and_raw_patterns_coexist(self):
        self.items.learn_item("persian", ITEM_TYPE_PATTERN, "سلام {{who}}")
        self.teacher.teach("fa", LIKE)
        self.assertEqual(self.matcher.match("سلام علی", language="fa").variables, {"who": "علی"})
        self.assertEqual(self.matcher.match("من چای را دوست دارم", language="fa").variables,
                         {"X": "چای"})

    def test_teaching_does_not_alter_other_learned_items(self):
        self.items.learn_item("persian", ITEM_TYPE_WORD, "کتاب", meaning={"gloss": "book"})
        before = self.items.get_item("fa", ITEM_TYPE_WORD, "کتاب")
        self.teacher.teach("fa", LIKE, examples=["من کتاب را دوست دارم"])
        self.assertEqual(self.items.get_item("fa", ITEM_TYPE_WORD, "کتاب"), before)


class TestCoreIntegration(unittest.TestCase):
    """Core wires its own teacher over its own store, matcher and extractor.
    Each test gets a private on-disk database, so nothing depends on (or
    leaks into) the default one."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def new_core(self):
        return Core(memory_db_path=os.path.join(self._tmpdir.name, "core.db"))

    def test_core_has_a_teacher_over_its_own_language_learning_store(self):
        core = self.new_core()
        self.assertIsInstance(core.pattern_teacher, LearnedPatternTeacher)
        self.assertIs(core.pattern_teacher.language_learning, core.language_learning)

    def test_teach_then_match_then_extract_through_core(self):
        core = self.new_core()
        taught = core.teach_sentence_pattern("fa", GIVE, meaning={"intent": "give"},
                                             locale="fa-IR", examples=["من کتاب را به علی می‌دهم"])
        self.assertEqual(taught.status, STATUS_CREATED)
        match = core.match_learned_pattern("من کتاب را به علی می‌دهم", language="fa")
        self.assertEqual(match.status, STATUS_MATCHED)
        self.assertEqual(match.matched_pattern_id, taught.pattern_id)
        structure = core.extract_sentence_structure("من کتاب را به علی می‌دهم", language="fa")
        self.assertEqual(structure.variables, {"X": "کتاب", "Y": "علی"})
        self.assertEqual(structure.locale, "fa-IR")

    def test_core_duplicate_and_invalid_results(self):
        core = self.new_core()
        core.teach_sentence_pattern("fa", LIKE)
        self.assertEqual(core.teach_sentence_pattern("fa", LIKE).status, STATUS_ALREADY_EXISTS)
        self.assertEqual(core.teach_sentence_pattern("fa", "من {{X را").status, STATUS_INVALID)

    def test_taught_pattern_reaches_the_understanding_result(self):
        core = self.new_core()
        core.teach_sentence_pattern("fa", LIKE, meaning={"intent": "likes_thing"})
        core.process_input("من کتاب را دوست دارم")
        understanding = core.last_language_understanding
        self.assertEqual(understanding.learned_pattern_match["status"], STATUS_MATCHED)
        structure = understanding.learned_sentence_structure
        self.assertEqual(structure["status"], STATUS_MATCHED)
        self.assertEqual(structure["components"][1]["value"], "کتاب")
        self.assertEqual(structure["meaning"], {"intent": "likes_thing"})


if __name__ == "__main__":
    unittest.main()
