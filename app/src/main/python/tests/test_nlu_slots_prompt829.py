"""
Prompt 829 - semantic entity/slot foundation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_nlu_slots_prompt829 -v
"""

import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from understanding.persian_nlu import analyze_persian
from understanding.nlu_pipeline import NLUConversationContext, NLUAnalysis, default_pipeline
from understanding.nlu_structured_output import normalize_nlu_analysis
from understanding.nlu_slots import (
    extract_slots, extract_slots_from_analysis, empty_slots, SLOTS_VERSION,
    MAX_SLOTS, MAX_TEXT_CHARS, MAX_VALUE_LEN,
)

P = default_pipeline()
SLOT_KEYS = ["kind", "key", "value", "start", "end", "source"]


def slots_of(text):
    return extract_slots_from_analysis(P.analyze(text))["items"]


def triples(text):
    return [(s["kind"], s["key"], s["value"]) for s in slots_of(text)]


class TestExtraction(unittest.TestCase):
    def test_name_slot_copies_existing_entity(self):
        a = P.analyze("من عرفان هستم")
        items = extract_slots_from_analysis(a)["items"]
        self.assertEqual(items, [{"kind": "name", "key": None, "value": "عرفان",
                                  "start": None, "end": None, "source": "entity"}])
        self.assertEqual(a.result.entities["name"], "عرفان")

    def test_quoted_values_all_quote_styles(self):
        self.assertEqual(triples('او گفت «سلام دنیا» و "خداحافظ" و “سپاس”'),
                         [("quoted", None, "سلام دنیا"), ("quoted", None, "خداحافظ"),
                          ("quoted", None, "سپاس")])

    def test_key_value_forms(self):
        self.assertEqual(triples("سن: ۲۵ و age=30"),
                         [("key_value", "سن", "25"), ("key_value", "age", "30")])
        self.assertEqual(triples("نام: علی؟"), [("key_value", "نام", "علی")])
        self.assertEqual(triples('city: "Tehran"'), [("key_value", "city", "Tehran")])

    def test_numbers_integers_and_decimals(self):
        self.assertEqual(triples("۱۲۳ و 4.5 و ۳٫۱۴"),
                         [("number", None, "123"), ("number", None, "4.5"),
                          ("number", None, "3٫14")])
        self.assertEqual(triples("I have 3 cats"), [("number", None, "3")])

    def test_numbers_are_strings_not_converted(self):
        self.assertEqual(triples("کد 007"), [("number", None, "007")])

    def test_offsets_point_into_normalized_text(self):
        text = 'نام: علی و "سلام" و 42'
        a = P.analyze(text)
        t = a.result.normalized_text
        for s in extract_slots_from_analysis(a)["items"]:
            if s["kind"] == "quoted":
                self.assertEqual(t[s["start"]:s["end"]], s["value"])
            elif s["kind"] == "number":
                self.assertEqual(t[s["start"]:s["end"]], s["value"])
            elif s["kind"] == "key_value":
                self.assertEqual(t[s["start"]:s["end"]], "نام: علی")

    def test_order_is_names_first_then_by_position(self):
        a = P.analyze('من عرفان هستم و age=30 و "x" و 5')
        kinds = [s["kind"] for s in extract_slots_from_analysis(a)["items"]]
        starts = [s["start"] for s in extract_slots_from_analysis(a)["items"] if s["start"] is not None]
        self.assertEqual(starts, sorted(starts))
        if "name" in kinds:
            self.assertEqual(kinds[0], "name")

    def test_every_slot_has_the_same_keys(self):
        for t in ("من عرفان هستم", "سن: 25 و 'x'", 'او گفت «سلام» و 5'):
            for s in slots_of(t):
                self.assertEqual(list(s), SLOT_KEYS)


class TestNoDuplicatesAndOverlap(unittest.TestCase):
    def test_number_inside_key_value_not_repeated(self):
        self.assertEqual(triples("age=30"), [("key_value", "age", "30")])

    def test_quoted_value_of_key_value_not_repeated(self):
        self.assertEqual(triples('city: "Tehran"'), [("key_value", "city", "Tehran")])

    def test_number_inside_quotes_not_repeated(self):
        self.assertEqual(triples('گفت "عدد 7"'), [("quoted", None, "عدد 7")])


class TestAmbiguousAndEmpty(unittest.TestCase):
    def test_empty_blank_and_non_string_inputs(self):
        for t in ("", "   ", "؟", "سلام"):
            self.assertEqual(slots_of(t), [], repr(t))
        for bad in (None, 5, [], {}, b"x"):
            self.assertEqual(extract_slots(bad), empty_slots())
        self.assertEqual(extract_slots("x", entities="oops"), empty_slots())

    def test_times_dates_fractions_versions_skipped(self):
        for t in ("ساعت 10:30", "تاریخ 2024-05-06", "نصف 1/2", "نسخه 1.2.3"):
            self.assertEqual(slots_of(t), [], t)

    def test_numbers_glued_to_letters_or_with_commas_skipped(self):
        for t in ("abc123", "v2", "کد a1b", "1,000", "1,5"):
            self.assertEqual(slots_of(t), [], t)

    def test_odd_ascii_quotes_are_ambiguous(self):
        self.assertEqual([s for s in slots_of('اسم "علی" و "رضا') if s["kind"] == "quoted"], [])
        self.assertEqual(len([s for s in slots_of('اسم "علی" و "رضا"') if s["kind"] == "quoted"]), 2)

    def test_empty_blank_or_overlong_quotes_skipped(self):
        self.assertEqual(slots_of('او گفت "" و «   »'), [])
        long = "ا" * (MAX_VALUE_LEN + 1)
        self.assertEqual(slots_of(f'او گفت «{long}»'), [])
        ok = "ا" * MAX_VALUE_LEN
        self.assertEqual(len(slots_of(f'او گفت «{ok}»')), 1)

    def test_url_and_malformed_key_value_skipped(self):
        for t in ("http://x.com", "a=/b", "x =", "10: ten", ": مقدار", "a == b"):
            self.assertEqual([s for s in slots_of(t) if s["kind"] == "key_value"], [], t)

    def test_trailing_punctuation_not_part_of_value(self):
        self.assertEqual(triples("نام: علی."), [("key_value", "نام", "علی")])

    def test_unrecognized_intent_still_yields_explicit_values(self):
        a = P.analyze("امروز 3 نفر آمدند")
        self.assertEqual(a.intent, "unknown")
        self.assertEqual(extract_slots_from_analysis(a)["items"][0]["value"], "3")

    def test_nothing_is_inferred(self):
        # No slot for words that merely look like values.
        self.assertEqual(slots_of("من پیتزا رو دوست دارم"), [])
        self.assertEqual(slots_of("سه نفر آمدند"), [])


class TestBounds(unittest.TestCase):
    def test_slot_count_is_capped_and_flagged(self):
        r = extract_slots(" ".join(str(i) for i in range(MAX_SLOTS + 10)))
        self.assertEqual(r["count"], MAX_SLOTS)
        self.assertEqual(len(r["items"]), MAX_SLOTS)
        self.assertTrue(r["truncated"])
        self.assertEqual(r["items"][0]["value"], "0")

    def test_below_cap_is_not_truncated(self):
        r = extract_slots("1 2 3")
        self.assertEqual((r["count"], r["truncated"]), (3, False))

    def test_text_scan_is_bounded_and_cut_at_word_boundary(self):
        text = ("ا " * (MAX_TEXT_CHARS // 2 - 2)) + "12345 99"
        r = extract_slots(text)
        self.assertTrue(r["truncated"])
        for s in r["items"]:
            self.assertLessEqual(s["end"], MAX_TEXT_CHARS)
        for s in r["items"]:
            self.assertIn(s["value"], ("12345", "99"))

    def test_entity_name_counts_toward_cap(self):
        r = extract_slots(" ".join(str(i) for i in range(30)), {"name": "علی"})
        self.assertEqual(r["count"], MAX_SLOTS)
        self.assertEqual(r["items"][0]["kind"], "name")


class TestDeterminismAndPurity(unittest.TestCase):
    TEXTS = ['من عرفان هستم', 'سن: ۲۵ و "سلام" و 4.5', "", "ساعت 10:30"]

    def test_same_input_same_output(self):
        for t in self.TEXTS:
            self.assertEqual(slots_of(t), slots_of(t))
            self.assertEqual(json.dumps(slots_of(t), ensure_ascii=False),
                             json.dumps(slots_of(t), ensure_ascii=False))

    def test_json_safe(self):
        for t in self.TEXTS:
            json.dumps(extract_slots_from_analysis(P.analyze(t)))

    def test_extraction_does_not_modify_analysis_or_entities(self):
        a = P.analyze("من عرفان هستم و age=30")
        before = copy.deepcopy(a.to_dict())
        extract_slots_from_analysis(a)
        self.assertEqual(a.to_dict(), before)
        ents = {"name": "علی"}
        extract_slots("x", ents)
        self.assertEqual(ents, {"name": "علی"})

    def test_result_is_detached(self):
        a = P.analyze("age=30")
        r = extract_slots_from_analysis(a)
        r["items"].append("x")
        r["items"][0]["value"] = "changed"
        self.assertEqual(extract_slots_from_analysis(a)["items"][0]["value"], "30")

    def test_garbage_analysis_never_raises(self):
        for junk in (None, object(), 5, "x"):
            self.assertEqual(extract_slots_from_analysis(junk), empty_slots())


class TestNormalizedOutputExposure(unittest.TestCase):
    def test_slots_exposed_in_normalized_output_last(self):
        n = P.analyze("من عرفان هستم و age=30").normalized()
        self.assertEqual(list(n)[16], "slots")  # Prompt 830 appends "relations" after it
        self.assertEqual(n["slots"], extract_slots_from_analysis(P.analyze("من عرفان هستم و age=30")))
        self.assertEqual(set(n["slots"]), {"version", "items", "count", "truncated"})
        self.assertEqual(n["slots"]["version"], SLOTS_VERSION)

    def test_slots_always_present_with_stable_shape(self):
        for t in ("", "سلام", "من عرفان هستم", "Hello 5"):
            n = P.analyze(t).normalized()
            self.assertEqual(set(n["slots"]), {"version", "items", "count", "truncated"})
            self.assertEqual(n["slots"]["count"], len(n["slots"]["items"]))
        self.assertEqual(normalize_nlu_analysis(None)["slots"], empty_slots())

    def test_schema_version_and_828_keys_unchanged(self):
        n = P.analyze("پایتون چیه؟").normalized()
        self.assertEqual(n["schema_version"], 1)
        self.assertEqual(list(n)[:16], [
            "schema_version", "intent", "recognized", "confidence", "matched_rule",
            "normalized_text", "entities", "facts", "decided_by", "question", "request",
            "negation", "correction", "context", "extras", "errors"])

    def test_normalized_is_deterministic_and_json_safe(self):
        a = P.analyze("نام: علی و 5")
        self.assertEqual(a.normalized(), a.normalized())
        json.dumps(a.normalized(), ensure_ascii=False)


class TestBackwardCompatibility(unittest.TestCase):
    CORPUS = ["من عرفان هستم", "اسم من چیه؟", "لطفا یه جوک بگو", "پایتون چیه؟", "و جاوا چی؟",
              "دوباره", "نه منظورم علی بود", "من پیتزا رو دوست ندارم", "What is the weather",
              "", "سن: ۲۵", 'او گفت "سلام" 5 بار']

    def test_primary_result_entities_facts_unchanged_by_slots(self):
        ctx = NLUConversationContext()
        for t in self.CORPUS:
            a = P.analyze(t, ctx)
            ctx.record(a)
            n = a.normalized()
            self.assertEqual(a.result.to_dict(), analyze_persian(t).to_dict(), t)
            self.assertEqual(n["intent"], a.result.intent)
            self.assertEqual(n["entities"], a.result.entities)
            self.assertEqual(n["facts"], [dict(f) for f in a.result.facts])

    def test_raw_analysis_and_structure_have_no_slots(self):
        a = P.analyze("age=30")
        self.assertNotIn("slots", a.structure)
        self.assertEqual(set(a.to_dict()), {"result", "structure", "component", "errors"})
        self.assertIsInstance(a, NLUAnalysis)

    def test_name_entity_is_copied_not_reinterpreted(self):
        # A stray quote inside the existing entity is preserved as-is.
        a = P.analyze('اسم من "علی')
        name = a.result.entities.get("name")
        if name is not None:
            self.assertEqual(extract_slots_from_analysis(a)["items"][0]["value"], name)


class TestCoreUnchanged(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(os.path.join(self.tmp.name, "memory.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_core_replies_memory_unchanged_and_slots_available(self):
        self.core.process_input("من عرفان هستم")
        counts = self.core.memory.counts()
        self.core.process_input("نام: علی و سن: 25")
        n = self.core.last_nlu_analysis.normalized()
        self.assertEqual([(s["kind"], s["key"], s["value"]) for s in n["slots"]["items"]],
                         [("key_value", "نام", "علی"), ("key_value", "سن", "25")])
        self.assertEqual(self.core.memory.counts()["knowledge_count"], counts["knowledge_count"])


if __name__ == "__main__":
    unittest.main()
