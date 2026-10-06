"""
Prompt 824 - Persian NLU v1 focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_persian_nlu_prompt824 -v
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from understanding.persian_nlu import (
    PersianNLU, analyze_persian, normalize_persian,
    INTENT_INTRODUCE_NAME, INTENT_LIKE, INTENT_DISLIKE, INTENT_ASK_USER_NAME,
    INTENT_QUESTION, INTENT_REQUEST, INTENT_UNKNOWN,
)

FALLBACK_MARKER = "I don't have enough information"


def _make_core():
    tmp = tempfile.TemporaryDirectory()
    core = Core(memory_db_path=os.path.join(tmp.name, "m.sqlite3"),
                skill_definitions_dir=os.path.join(tmp.name, "skills"))
    return core, tmp


class TestNormalization(unittest.TestCase):
    def test_arabic_variants_become_persian(self):
        self.assertEqual(normalize_persian("كيك"), "کیک")
        self.assertEqual(normalize_persian("علي"), "علی")

    def test_whitespace_and_zwnj_collapsed(self):
        self.assertEqual(normalize_persian("  من   عرفان\tهستم \n"), "من عرفان هستم")
        self.assertEqual(normalize_persian("می\u200cخوام"), "می خوام")

    def test_digits_diacritics_tatweel_and_question_mark(self):
        self.assertEqual(normalize_persian("۱۲٣"), "123")
        self.assertEqual(normalize_persian("عرفــان"), "عرفان")
        self.assertEqual(normalize_persian("عِرفان"), "عرفان")
        self.assertEqual(normalize_persian("چیه؟"), "چیه?")

    def test_none_and_empty(self):
        self.assertEqual(normalize_persian(None), "")
        self.assertEqual(normalize_persian("   "), "")


class TestPatterns(unittest.TestCase):
    def test_name_hastam(self):
        r = analyze_persian("من عرفان هستم")
        self.assertEqual(r.intent, INTENT_INTRODUCE_NAME)
        self.assertEqual(r.entities, {"name": "عرفان"})
        self.assertEqual(r.facts, [{"subject": "user", "predicate": "name", "value": "عرفان"}])
        self.assertGreater(r.confidence, 0.9)

    def test_name_esm_man(self):
        r = analyze_persian("اسم من عرفانه")
        self.assertEqual(r.intent, INTENT_INTRODUCE_NAME)
        self.assertEqual(r.entities["name"], "عرفان")
        self.assertEqual(analyze_persian("اسمم عرفان است").entities["name"], "عرفان")
        self.assertEqual(analyze_persian("نام من عرفان هست").entities["name"], "عرفان")

    def test_name_with_arabic_letters_and_spacing(self):
        r = analyze_persian("  من   علي   هستم ")
        self.assertEqual(r.entities["name"], "علی")

    def test_state_is_not_a_name(self):
        self.assertEqual(analyze_persian("من خسته هستم").intent, INTENT_UNKNOWN)

    def test_like(self):
        r = analyze_persian("من پیتزا رو دوست دارم")
        self.assertEqual(r.intent, INTENT_LIKE)
        self.assertEqual(r.entities, {"item": "پیتزا"})
        self.assertEqual(r.facts[0]["predicate"], "likes")
        self.assertEqual(analyze_persian("من قهوه را دوست دارم").entities["item"], "قهوه")
        self.assertEqual(analyze_persian("من خیلی شکلات رو دوست دارم").entities["item"], "شکلات")

    def test_dislike(self):
        r = analyze_persian("من پیتزا رو دوست ندارم")
        self.assertEqual(r.intent, INTENT_DISLIKE)
        self.assertEqual(r.facts, [{"subject": "user", "predicate": "dislikes", "value": "پیتزا"}])

    def test_ask_user_name(self):
        self.assertEqual(analyze_persian("اسم من چیه؟").intent, INTENT_ASK_USER_NAME)

    def test_questions(self):
        for s in ("پایتون چیه؟", "چرا آسمون آبیه", "این کار میشه؟", "کجا میری"):
            self.assertEqual(analyze_persian(s).intent, INTENT_QUESTION, s)

    def test_requests(self):
        for s in ("یه جوک بگو", "لطفا کمک کن", "میشه یه داستان بنویسی؟", "فایل رو باز کن"):
            self.assertEqual(analyze_persian(s).intent, INTENT_REQUEST, s)

    def test_unknown_inputs(self):
        for s in ("امروز هوا خوبه", "سلام", "", "   ", "what is Python?", "My name is Erfan", "123"):
            r = analyze_persian(s)
            self.assertEqual(r.intent, INTENT_UNKNOWN, s)
            self.assertEqual(r.facts, [])
            self.assertEqual(r.entities, {})
            self.assertEqual(r.confidence, 0.0)

    def test_result_structure(self):
        d = analyze_persian("من عرفان هستم").to_dict()
        for key in ("intent", "entities", "facts", "confidence"):
            self.assertIn(key, d)

    def test_never_raises_on_odd_input(self):
        for s in (None, 5, "\u200c", "؟", "من هستم", "من دوست دارم", "اسم من"):
            self.assertIsNotNone(analyze_persian(s))

    def test_deterministic_repeated_results(self):
        nlu = PersianNLU()
        for s in ("من عرفان هستم", "اسم من عرفانه", "من پیتزا رو دوست دارم", "پایتون چیه؟", "؟؟؟"):
            first = nlu.analyze(s)
            for _ in range(5):
                self.assertEqual(nlu.analyze(s), first)


class TestCoreIntegration(unittest.TestCase):
    def setUp(self):
        self.core, self._tmp = _make_core()

    def tearDown(self):
        self._tmp.cleanup()

    def test_process_input_recognizes_name(self):
        reply = self.core.process_input("من عرفان هستم")
        self.assertIsInstance(reply, str)
        self.assertNotIn(FALLBACK_MARKER, reply)
        self.assertIn("عرفان", reply)
        self.assertEqual(self.core.last_persian_nlu.intent, INTENT_INTRODUCE_NAME)

    def test_name_persisted_and_recalled(self):
        self.core.process_input("اسم من عرفانه")
        rec = self.core.knowledge.get("کاربر.نام")
        self.assertEqual(rec["description"], "عرفان")
        self.assertEqual(rec["source"], "persian_nlu_v1")
        self.assertEqual(rec["source_text"], "اسم من عرفانه")
        self.assertIn("عرفان", self.core.process_input("اسم من چیه؟"))

    def test_learning_event_recorded(self):
        self.core.process_input("من عرفان هستم")
        events = self.core.recent_learning_events()
        self.assertTrue(any(e["target"] == "کاربر.نام" and e["event_type"] == "teach" for e in events))

    def test_name_unknown_before_stated(self):
        reply = self.core.process_input("اسم من چیه؟")
        self.assertNotIn("عرفان", reply)
        self.assertNotIn(FALLBACK_MARKER, reply)

    def test_name_update(self):
        self.core.process_input("من عرفان هستم")
        self.core.process_input("من علی هستم")
        self.assertEqual(self.core.knowledge.get("کاربر.نام")["description"], "علی")

    def test_like_and_dislike_persisted(self):
        self.core.process_input("من پیتزا رو دوست دارم")
        self.assertEqual(self.core.knowledge.get("کاربر.دوست_دارد.پیتزا")["status"], "active")
        self.core.process_input("من پیتزا رو دوست ندارم")
        self.assertEqual(self.core.knowledge.get("کاربر.دوست_ندارد.پیتزا")["status"], "active")
        self.assertEqual(self.core.knowledge.get("کاربر.دوست_دارد.پیتزا")["status"], "inactive")
        self.core.process_input("من پیتزا رو دوست دارم")
        self.assertEqual(self.core.knowledge.get("کاربر.دوست_دارد.پیتزا")["status"], "active")
        self.assertEqual(self.core.knowledge.get("کاربر.دوست_ندارد.پیتزا")["status"], "inactive")

    def test_memory_survives_new_core_on_same_db(self):
        db = os.path.join(self._tmp.name, "m.sqlite3")
        self.core.process_input("من عرفان هستم")
        core2 = Core(memory_db_path=db, skill_definitions_dir=os.path.join(self._tmp.name, "skills"))
        self.assertIn("عرفان", core2.process_input("اسم من چیه؟"))

    def test_question_and_request_routed_separately(self):
        q = self.core.process_input("پایتون چیه؟")
        self.assertEqual(self.core.last_persian_nlu.intent, INTENT_QUESTION)
        self.assertNotIn(FALLBACK_MARKER, q)
        r = self.core.process_input("یه جوک بگو")
        self.assertEqual(self.core.last_persian_nlu.intent, INTENT_REQUEST)
        self.assertNotIn(FALLBACK_MARKER, r)
        self.assertNotEqual(q, r)

    def test_question_and_request_store_nothing(self):
        before = self.core.memory.counts()
        self.core.process_input("پایتون چیه؟")
        self.core.process_input("یه جوک بگو")
        self.assertEqual(self.core.memory.counts()["knowledge_count"], before["knowledge_count"])

    def test_unknown_persian_uses_existing_fallback(self):
        reply = self.core.process_input("امروز هوا خوبه")
        self.assertEqual(self.core.last_persian_nlu.intent, INTENT_UNKNOWN)
        self.assertIn(FALLBACK_MARKER, reply)

    def test_english_unchanged_and_not_claimed(self):
        reply = self.core.process_input("What is the weather")
        self.assertEqual(self.core.last_persian_nlu.intent, INTENT_UNKNOWN)
        self.assertIn(FALLBACK_MARKER, reply)

    def test_deterministic_across_cores(self):
        replies = []
        for _ in range(2):
            core, tmp = _make_core()
            try:
                replies.append([core.process_input(s) for s in (
                    "من عرفان هستم", "اسم من چیه؟", "من چای رو دوست دارم", "یه جوک بگو", "سلام خوبی")])
            finally:
                tmp.cleanup()
        self.assertEqual(replies[0], replies[1])


class TestAELCompatibility(unittest.TestCase):
    def setUp(self):
        self.core, self._tmp = _make_core()

    def tearDown(self):
        self._tmp.cleanup()

    def test_ael_teach_and_query_unchanged(self):
        reply = self.core.process_input("TEACH sun IS a star at the center of the solar system")
        self.assertIn("[AEL OK]", reply)
        self.assertIn("star", self.core.knowledge.get("sun")["description"])

    def test_ael_does_not_trigger_nlu_facts(self):
        self.core.process_input("TEACH sun IS a star")
        self.assertIsNone(self.core.knowledge.get("کاربر.نام"))

    def test_taught_english_concept_still_answered_after_nlu_facts(self):
        self.core.process_input("TEACH sun IS a star")
        self.core.process_input("من عرفان هستم")
        self.assertIn("star", self.core.process_input("What is sun?"))

    def test_taught_persian_concept_still_answered_by_existing_lookup(self):
        # (AEL's tokenizer only accepts Latin identifiers, so teach it
        # through the same LearningSystem AEL itself uses.)
        self.core.learning.teach("پایتون", "یک زبان برنامه نویسی")
        # Bare-name lookup answered before Prompt 824 and still is.
        self.assertEqual(self.core.process_input("پایتون"), "یک زبان برنامه نویسی")
        self.assertEqual(self.core.last_persian_nlu.intent, INTENT_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
