"""
Prompt 958 - language packs (Persian question -> answer data) and the retrieval that serves them, plus the guard that
keeps a pack's chat handler from hanging the conversation.
"""

import os
import sys
import time
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pack_system import limits
from pack_system.lang import LangIndex, LangService, MAX_PHRASINGS, featurize, normalize_fa
from pack_system.registry import REGISTRY, call_guarded
from tests import pack_support_prompt958 as S
from tests.test_pack_system_prompt958 import PackCase

QA = [("پایتخت ایران کجاست | پایتخت ایران چیست | مرکز ایران کجاست", "تهران"),
      ("پایتخت فرانسه کجاست | پایتخت فرانسه چیست", "پاریس"),
      ("بلندترین قله ایران کدام است | بلندترین کوه ایران چیست", "دماوند"),
      ("سلام | درود | سلام علیکم | سلام حالت چطوره", "سلام! خوش آمدی.")]


class NormalizeTests(unittest.TestCase):
    def test_letters_digits_and_punctuation(self):
        self.assertEqual(normalize_fa("كتاب‌هاي  من؟!"), "کتاب های من")
        self.assertEqual(normalize_fa("سال ۱۴۰۵ و ٢٠٢٦"), "سال 1405 و 2026")
        self.assertEqual(normalize_fa("Hello,  WORLD!"), "hello world")
        self.assertEqual(normalize_fa("سَلام"), "سلام")

    def test_colloquial_question_words_meet_the_formal_ones(self):
        self.assertEqual(featurize("پایتخت ایران چیه")[1], featurize("پایتخت ایران چیست؟")[1])
        self.assertEqual(featurize("اسمت چیه")[1], featurize("اسمت چیست")[1])
        self.assertEqual(featurize("کجاست")[1], featurize("کجا")[1])

    def test_plural_and_comparative_forms_share_a_stem(self):
        self.assertEqual(featurize("کتاب")[1], featurize("کتاب‌ها")[1][:1])

    def test_short_words_are_not_stemmed_into_collisions(self):
        self.assertEqual(featurize("سلام")[1], ["u:سلام"])
        self.assertEqual(featurize("ایران")[1], ["u:ایران"])
        self.assertEqual(featurize("پایتخت")[1], ["u:پایتخت"])


class IndexTests(unittest.TestCase):
    def index(self, qa=QA):
        entries = []
        for number, (questions, answer) in enumerate(qa):
            entries.append(("p", number, [q.strip() for q in questions.split("|")], answer))
        return LangIndex().build(entries)

    def test_exact_and_near_questions_are_answered(self):
        idx = self.index()
        self.assertEqual(idx.query("پایتخت فرانسه کجاست؟").answer, "پاریس")
        self.assertEqual(idx.query("پایتخت فرانسه چیه").answer, "پاریس")
        self.assertEqual(idx.query("بلندترین قله‌ی ایران چیه").answer, "دماوند")
        self.assertEqual(idx.query("سلام").answer, "سلام! خوش آمدی.")

    def test_unknown_or_partial_questions_stay_unanswered(self):
        idx = self.index()
        for text in ("پایتخت آلمان کجاست", "هوا چطوره", "پایتخت", "ایران", "", "؟؟؟", "چطوری می‌تونم برنامه بنویسم"):
            self.assertIsNone(idx.query(text), text)

    def test_an_equally_close_pair_of_different_answers_is_not_answered(self):
        idx = self.index([("پایتخت ایران چیست", "تهران"), ("پایتخت ایران کجاست", "اصفهان")])
        self.assertIsNone(idx.query("پایتخت ایران"))                           # both are equally near: say nothing
        self.assertEqual(idx.query("پایتخت ایران چیه").answer, "تهران")        # the colloquial form is the same sentence
        self.assertEqual(idx.query("پایتخت ایران کجاست").answer, "اصفهان")

    def test_the_same_sentence_twice_the_later_entry_wins(self):
        idx = self.index([("پایتخت ایران چیست", "قدیمی"), ("پایتخت ایران چیست", "جدید")])
        self.assertEqual(idx.query("پایتخت ایران چیه").answer, "جدید")

    def test_two_phrasings_of_one_answer_are_not_ambiguous(self):
        idx = self.index([("پایتخت ایران چیست | مرکز ایران کجاست", "تهران")])
        self.assertEqual(idx.query("پایتخت ایران چیه").answer, "تهران")

    def test_score_and_phrasing_are_reported(self):
        match = self.index().query("پایتخت فرانسه کجاست")
        self.assertEqual(match.pack_id, "p")
        self.assertEqual(match.to_dict()["score"], 1.0)
        self.assertEqual(match.question, "پایتخت فرانسه کجاست")

    def test_a_large_index_builds_fast_and_is_bounded(self):
        entries = [("p", n, ["سؤال شمارهٔ %d دربارهٔ موضوع %d" % (n, n % 97), "پرسش %d موضوع %d" % (n, n % 89)], "پاسخ %d" % n)
                   for n in range(12000)]
        start = time.time()
        idx = LangIndex().build(entries)
        self.assertLess(time.time() - start, 8.0)
        self.assertLessEqual(idx.phrasings, MAX_PHRASINGS)
        self.assertEqual(idx.query("سؤال شمارهٔ 777 دربارهٔ موضوع %d" % (777 % 97)).answer, "پاسخ 777")
        entries = [("p", n, ["جمله %d" % n] * 1, "a") for n in range(MAX_PHRASINGS + 50)]
        self.assertTrue(LangIndex().build(entries).truncated)


class LangPackLifecycleTests(PackCase):
    def lang(self, version=1, qa=None):
        return S.lang_pack(version=version, qa=qa)

    def test_a_lang_pack_answers_only_after_approval(self):
        service = LangService(self.mgr)
        proposal = self.propose(self.lang())
        self.assertEqual(proposal["status"], "pending_approval")
        self.assertEqual(proposal["kind"], "lang.v1")
        self.assertEqual(proposal["qa_count"], 2)
        self.assertFalse(proposal["restart_needed"])
        self.assertIsNone(service.answer("پایتخت ایران چیه"))
        out = self.mgr.approve(proposal["proposal_id"], user_approved=True)
        self.assertEqual((out["status"], out["hot"], out["restart_needed"]), ("applied", True, False))
        self.assertEqual(service.answer("پایتخت ایران چیه").answer, "تهران")
        self.assertEqual(service.stats()["phrasings"], 5)

    def test_update_rollback_disable_remove(self):
        service = LangService(self.mgr)
        self.install(self.lang())
        self.install(self.lang(2, qa=[("پایتخت ایران کجاست", "تهران عزیز")]))
        self.assertEqual(service.answer("پایتخت ایران کجاست").answer, "تهران عزیز")
        self.assertIsNone(service.answer("سلام"))
        self.mgr.rollback("fa_demo")
        self.assertEqual(service.answer("پایتخت ایران کجاست").answer, "تهران")
        self.assertEqual(service.answer("سلام").answer, "سلام! خوش آمدی.")
        self.mgr.disable("fa_demo")
        self.assertIsNone(service.answer("سلام"))
        self.mgr.enable("fa_demo", user_approved=True)
        self.assertIsNotNone(service.answer("سلام"))
        self.mgr.remove("fa_demo", user_approved=True)
        self.assertIsNone(service.answer("سلام"))

    def test_lang_packs_survive_a_restart_without_any_code_loading(self):
        self.install(self.lang())
        mgr = self.restart()
        mgr.activate_all()
        self.assertEqual(LangService(mgr).answer("سلام علیکم").answer, "سلام! خوش آمدی.")
        self.assertEqual(REGISTRY.pack_ids(), [])

    def test_tampered_lang_data_is_not_served(self):
        self.install(self.lang())
        path = os.path.join(self.root, "store", "fa_demo", "1", "data.json")
        os.chmod(path, 0o644)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('[{"q": ["سلام"], "a": ["x"]}]')
        self.assertEqual(self.mgr.store.verify("fa_demo", 1), (False, "data_changed"))
        self.assertEqual(self.mgr.enable("fa_demo", user_approved=True)["code"], "E_PACK_VERIFY")

    def test_two_packs_serve_one_index(self):
        service = LangService(self.mgr)
        self.install(self.lang())
        self.install(S.lang_pack(pid="fa_more", qa=[("اسم تو چیست", "من دستیار فارسی هستم")]))
        self.assertEqual(service.answer("اسم تو چیه").answer, "من دستیار فارسی هستم")
        self.assertEqual(service.answer("سلام").answer, "سلام! خوش آمدی.")
        self.assertEqual({r["pack_id"] for r in self.mgr.list()}, {"fa_demo", "fa_more"})

    def test_a_newer_pack_overrides_an_older_answer_to_the_same_question(self):
        service = LangService(self.mgr)
        self.install(self.lang())
        self.clock.advance(60)
        self.install(S.lang_pack(pid="fa_more", qa=[("پایتخت ایران کجاست", "تهران، شهر من")]))
        self.assertEqual(service.answer("پایتخت ایران کجاست").answer, "تهران، شهر من")
        self.mgr.disable("fa_more")
        self.assertEqual(service.answer("پایتخت ایران کجاست").answer, "تهران")

    def test_a_pack_cannot_change_kind(self):
        self.install(self.lang())
        out = self.propose(S.text_pack(pid="fa_demo", version=2))
        self.assertEqual(out["code"], "E_PACK_KIND_CHANGE")


class HandlerGuardTests(PackCase):
    def test_call_guarded_returns_raises_and_times_out(self):
        self.assertEqual(call_guarded(lambda: 7, 2), 7)
        with self.assertRaises(ValueError):
            call_guarded(lambda: (_ for _ in ()).throw(ValueError("x")), 2)
        spin = lambda: [None for _ in iter(int, 1)]
        started = time.time()
        with self.assertRaises(TimeoutError):
            call_guarded(spin, 0.3)
        self.assertLess(time.time() - started, 3.0)

    def test_a_hanging_handler_cannot_hang_the_conversation_and_gets_switched_off(self):
        old = limits.HANDLER_SECONDS
        limits.HANDLER_SECONDS = 0.3
        self.addCleanup(setattr, limits, "HANDLER_SECONDS", old)
        source = ("def register(api):\n    def handle(ctx):\n        while True:\n            pass\n"
                  "    api.register_chat('hang', lambda c: True, handle, stage='fallback')\n")
        self.install(S.text_pack(pid="demo_bad", source=source))
        started = time.time()
        for _ in range(limits.MAX_PACK_FAILURES):
            self.assertIsNone(self.chat("هر چیزی"))
        self.assertLess(time.time() - started, 10.0)
        self.assertEqual(self.mgr.get("demo_bad")["state"], "disabled")

    def test_a_matcher_that_raises_counts_as_a_failure_but_not_as_an_answer(self):
        source = ("def register(api):\n    api.register_chat('m', lambda c: 1 / 0, lambda c: 'x', stage='fallback')\n"
                  "    api.register_chat('ok', lambda c: True, lambda c: 'پاسخ سالم', stage='fallback', priority=90)\n")
        self.install(S.text_pack(pid="demo_bad", source=source))
        self.assertEqual(self.chat("هر چیزی"), "پاسخ سالم")
        self.assertEqual(REGISTRY.errors("demo_bad"), 1)

    def test_empty_or_non_text_replies_are_ignored(self):
        source = ("def register(api):\n    api.register_chat('a', lambda c: True, lambda c: None, stage='fallback')\n"
                  "    api.register_chat('b', lambda c: True, lambda c: 5, stage='fallback')\n"
                  "    api.register_chat('c', lambda c: True, lambda c: '   ', stage='fallback')\n")
        self.install(S.text_pack(pid="demo_bad", source=source))
        self.assertIsNone(self.chat("هر چیزی"))
        self.assertEqual(REGISTRY.errors("demo_bad"), 0)


if __name__ == "__main__":
    unittest.main()
