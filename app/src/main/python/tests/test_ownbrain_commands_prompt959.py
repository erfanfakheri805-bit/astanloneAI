"""Prompt 959 (stage B, «مغز خودکار») - which sentences are about the assistant's OWN brain.

The classifier (`persian_brain.hub_ownbrain_commands`) is a pure token cascade, so these tests are table tests: what the user may say, and
what must NOT be taken for it. In the user's terms:

* his own words for the wish («مغز خودت را بگیر», «خودت کارای لازم رو برای چیزی که نداره فراهم کنه») start the conversation - and only start
  a QUESTION (the consent card), never a download;
* the human brain, the CLOUD brain, a request TO a brain («از مغزت بخواه …») and ordinary talk are never taken over;
* every sentence the app itself tells the user to say («مغز خودت را بگیر», «وضعیت مغز», …) is understood - no dead advice - and every
  quoted phrase in the own-brain texts is one the app understands;
* the answers to the open question: «بله / نه», the choice «سبک» / «قوی», and the long forms («بله شروع کن», «آره بگیرش»).
"""
import os
import re
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import ownbrain_catalog as catalog
from persian_brain import hub_intents as HI
from persian_brain import hub_messages_ownbrain as BM
from persian_brain import hub_ownbrain_commands as OC
from persian_brain import normalization as nz
from self_builder import fa_text


def classify(text):
    norm = nz.normalize(text)
    return OC.classify(text, norm, fa_text.words(norm))


def kind_of(text):
    command = classify(text)
    return None if command is None else command.kind


def toks(text):
    return fa_text.words(nz.normalize(text))


# ====================================================================== what the user says -> which command
POSITIVE = {
    OC.GET: ("مغز خودت را بگیر", "مغز خودتو بگیر", "برای خودت مغز بگیر", "خودت یک مغز برای خودت فراهم کن", "می‌خوام مغز داشته باشی",
             "میخوام خودت مغز بگیری", "یه مغز زبانی برای خودت دانلود کن", "مغز آفلاین بگیر", "مغز خودکار را فعال کن", "مغز خودت رو راه بنداز",
             "یک مدل زبانی خودت را نصب کن", "خودت هر چیزی که نداری رو برای خودت فراهم کن", "خودت کارای لازم رو برای چیزی که نداره فراهم کنه",
             "مغز خودکار بگیر", "مغزت را بگیر", "مغزت رو از اینترنت دانلود کن", "چجوری مغز خودت رو بگیری؟", "هوش مصنوعی خودت را بگیر",
             "بدون کلید مغز بگیر", "مغز بدون هزینه برای خودت بگیر", "مغز رایگان بگیر", "یک مغز برای خودت تهیه کن"),
    OC.STATUS: ("وضعیت مغز", "وضعیت مغز خودکار", "مغزت چه شد؟", "دانلود مغز چقدر مونده؟", "مغز آماده شد؟", "پیشرفت دانلود مغز",
                "درصد مغز چند شد", "مغزت تموم شد؟"),
    OC.PAUSE: ("دانلود مغز را متوقف کن", "دانلود مغز رو نگه دار", "مغز را متوقف کن", "دانلود مغزت را لغو کن", "مغز رو بیخیال شو",
               "دانلود مغز رو کنسل کن"),
    OC.RESUME: ("ادامه دانلود مغز", "دانلود مغز را ادامه بده", "مغز رو ادامه بده", "دانلود مغز رو از سر بگیر", "ادامه مغز"),
    OC.DELETE: ("مغز را پاک کن", "مغزت رو پاک کن", "مغز خودکار را حذف کن", "مغز رو دور بریز", "جای مغز رو آزاد کن", "مغز را حذف کن"),
    OC.TEST: ("آزمایش مغز", "مغز را آزمایش کن", "مغزت را تست کن", "مغز را چک کن", "مغزت کار می‌کنه؟", "مغزت سالمه؟", "مغز رو امتحان کن"),
    OC.RETRY: ("مغز را دوباره امتحان کن", "دوباره مغز رو امتحان کن", "مغز را مجدد تست کن", "دوباره مغز رو راه‌اندازی کن",
               "مغز رو دوباره راه بنداز", "مغز رو از نو لود کن"),
    OC.HELP: ("مغز خودکار چیست؟", "مغز خودکار چیه", "مغز بگیرم هزینه دارد؟", "مغز خودت چقدر فضا می‌خواد", "مغز آفلاین امنه؟", "مغز خودکار",
              "مغز خودت چطور کار می‌کنه؟", "مغز خودت چقدر جا می‌گیرد؟", "مغز خودکار چقدر رم می‌خواهد؟"),
}

# sentences that must never be taken for an own-brain command
NOT_OURS = (
    "مغز انسان چطور کار می‌کند؟", "تست مغز چیست؟", "مغزم درد می‌کند", "مغز کوسه چقدر بزرگ است؟", "چطور مغزم را تقویت کنم؟", "مغز آدم چند گرم وزن دارد",
    "قهوه برای مغز خوب است؟", "مغز را بخور", "مغز و اعصاب", "با مغزت چی کار می‌کنی", "مغز چقدر جا می‌گیرد؟",
    # the CLOUD brain has its own commands
    "مغز ابری را فعال کن", "مغز ابری را خاموش کن", "وضعیت مغز ابری", "مغز آنلاین را بگیر", "کلید api بگیر برای مغز", "مغز با کلید api را فعال کن",
    # a request TO a brain (the teacher route), not «get a brain»
    "از مغزت بخواه یک ماشین‌حساب بسازد", "از مغز خودت بخواه برایم یک قابلیت جدید بسازه", "می‌تونی از مغزت کمک بگیری؟", "از مغزت بپرس HTTP چیست؟",
    # ordinary talk and the words of other commands
    "هوا ابری است و مغز من خسته است", "سلام", "ادامه بده", "ایست", "بله", "نه", "مدل را دانلود کن", "امروز هوا چطوره", "ساعت چنده؟",
)

# short phrases without the noun: «bare» - the conversation acts on them only while the own brain has a job or a failure they could mean
BARE = {
    "دانلود را متوقف کن": OC.PAUSE, "دانلود را نگه دار": OC.PAUSE, "ادامه دانلود": OC.RESUME, "دانلود را ادامه بده": OC.RESUME,
    "دوباره امتحان کن": OC.RETRY, "یه بار دیگه امتحان کن": OC.RETRY, "چقدر مونده؟": OC.STATUS, "دانلود چقدر مونده؟": OC.STATUS,
}


class PositiveTests(unittest.TestCase):
    def test_every_phrase_is_the_command_it_says(self):
        wrong = []
        for kind, sentences in POSITIVE.items():
            for sentence in sentences:
                got = kind_of(sentence)
                if got != kind:
                    wrong.append((sentence, kind, got))
        self.assertEqual(wrong, [])

    def test_there_are_enough_phrases_per_command(self):
        self.assertEqual(set(POSITIVE), set(OC.KINDS))
        for kind, sentences in POSITIVE.items():
            self.assertGreaterEqual(len(sentences), 5, kind)

    def test_the_users_own_words_for_the_wish_are_a_get(self):
        # what he wrote in his own message after the corrective release
        for sentence in ("می‌خوام خودش کارای لازم رو برای چیزی که نداره فراهم کنه", "خودت کارای لازم رو برای چیزی که نداری فراهم کن",
                         "برای هر چیزی که نداری خودت فراهم کن", "خودت مستقل شو"):
            command = classify(sentence)
            self.assertIsNotNone(command, sentence)
            self.assertEqual(command.kind, OC.GET, sentence)

    def test_the_same_wish_with_a_pronoun_on_the_word_needed_is_a_get_too(self):
        # Prompt 959 (found by the documents' pin test: the Persian guide offered «خودت کارهای لازمت را فراهم کن» as a spoken variant and the app did
        # not understand it - a dead hint): «لازم» also comes as «لازمت», «لازمه», «لازمشو».
        for sentence in ("خودت کارهای لازمت را فراهم کن", "خودت چیزهای لازمت را فراهم کن", "خودش کارای لازمشو فراهم کنه",
                         "می‌خوام خودت هر چی لازمه رو فراهم کنی", "خودت لازمه‌هایت را فراهم کن"):
            command = classify(sentence)
            self.assertIsNotNone(command, sentence)
            self.assertEqual(command.kind, OC.GET, sentence)
        # still needs the thing itself («خودت») and the verb «فراهم»: without them nothing is a command
        for sentence in ("کارهای لازمت را فراهم کن", "لازمت را بیاور", "خودت لازمه‌ات را بگو"):
            self.assertIsNone(classify(sentence), sentence)

    def test_a_question_about_the_cost_is_an_explanation_and_an_order_without_cost_is_an_order(self):
        self.assertEqual(kind_of("مغز بگیرم هزینه دارد؟"), OC.HELP)
        self.assertEqual(kind_of("مغز خودت پول می‌خواد؟"), OC.HELP)
        self.assertEqual(kind_of("مغز بدون هزینه برای خودت بگیر"), OC.GET)
        self.assertEqual(kind_of("مغز رایگان بگیر"), OC.GET)

    def test_how_it_works_is_an_explanation_and_does_it_work_is_a_test(self):
        self.assertEqual(kind_of("مغز خودت چطور کار می‌کنه؟"), OC.HELP)
        command = classify("مغزت کار می‌کنه؟")
        self.assertEqual((command.kind, command.slots.get("soft")), (OC.TEST, True))

    def test_a_retry_needs_an_again_word_and_a_test_does_not(self):
        self.assertEqual(kind_of("مغز را امتحان کن"), OC.TEST)
        self.assertEqual(kind_of("مغز را دوباره امتحان کن"), OC.RETRY)
        self.assertEqual(kind_of("آزمایش مغز"), OC.TEST)

    def test_stop_continue_and_delete_do_not_get_mixed_up(self):
        self.assertEqual(kind_of("دانلود مغز را متوقف کن"), OC.PAUSE)
        self.assertEqual(kind_of("ادامه دانلود مغز"), OC.RESUME)
        self.assertEqual(kind_of("مغز را ادامه بده"), OC.RESUME)
        self.assertEqual(kind_of("مغز را پاک کن"), OC.DELETE)
        self.assertEqual(kind_of("پاک کردن مغز"), OC.DELETE)

    def test_a_pronoun_suffix_on_the_noun_still_names_the_brain(self):
        for word in ("مغز", "مغزت", "مغزش", "مغزتون", "مغزم"):
            self.assertEqual(kind_of("وضعیت %s" % word), OC.STATUS, word)


class NotOursTests(unittest.TestCase):
    def test_nothing_in_the_list_is_taken_over(self):
        taken = [(sentence, kind_of(sentence)) for sentence in NOT_OURS if classify(sentence) is not None]
        self.assertEqual(taken, [])

    def test_a_long_or_empty_text_is_never_a_command(self):
        self.assertIsNone(OC.classify("", "", []))
        long_text = "مغز خودت را بگیر " * 40
        norm = nz.normalize(long_text)
        self.assertIsNone(OC.classify(long_text, norm, fa_text.words(norm)))
        many = "مغز خودت را بگیر " + "و " * 30
        norm = nz.normalize(many)
        self.assertIsNone(OC.classify(many, norm, fa_text.words(norm)))

    def test_the_cloud_brain_wins_unless_the_user_says_without_a_key(self):
        self.assertIsNone(classify("مغز ابری خودت را بگیر"))
        self.assertIsNone(classify("برای مغز کلید بگیر"))
        self.assertEqual(kind_of("مغز بدون کلید بگیر"), OC.GET)

    def test_a_request_to_the_brain_is_never_get_a_brain(self):
        for sentence in ("از مغزت بخواه یک بستهٔ زبان بنویسد", "از مغز خودت کمک بگیر", "از مغزت یک سؤال بپرس"):
            self.assertIsNone(classify(sentence), sentence)


class BareTests(unittest.TestCase):
    def test_the_noun_less_phrases_are_flagged_bare(self):
        for sentence, kind in BARE.items():
            command = classify(sentence)
            self.assertIsNotNone(command, sentence)
            self.assertEqual((command.kind, command.slots.get("bare")), (kind, True), sentence)

    def test_a_phrase_with_the_noun_is_not_bare(self):
        for sentence in ("دانلود مغز را متوقف کن", "ادامه دانلود مغز", "مغز را دوباره امتحان کن", "وضعیت مغز"):
            self.assertFalse(classify(sentence).slots.get("bare"), sentence)

    def test_a_bare_retry_accepts_only_short_polite_forms(self):
        self.assertIsNone(classify("دوباره امتحان کن که ببینم هوا چطوره و برنامه ام چیست"))
        self.assertIsNone(classify("دوباره همه چیز را امتحان کن و بعد خاموش شو"))


# ====================================================================== the answers to the open question
class AnswerWordTests(unittest.TestCase):
    def test_choose_word(self):
        for text, key in (("سبک", "light"), ("نسخه سبک را بگیر", "light"), ("همون سبکه", None), ("قوی", "strong"), ("قوی‌تر را می‌خوام", "strong"),
                          ("بله نسخه قوی", "strong"), ("gemma", "strong"), ("qwen", "light"), ("کوچک", "light"), ("بزرگتر", "strong")):
            self.assertEqual(OC.choose_word(toks(text)), key, text)

    def test_choose_word_needs_exactly_one_side_and_no_other_words(self):
        for text in ("سبک یا قوی", "هر کدام", "سبک و قوی را با هم", "سبک را بگیر و بعد یک بستهٔ لغت هم بنویس", "", "سلام", "بله"):
            self.assertIsNone(OC.choose_word(toks(text)), text)

    def test_confirm_word_short_and_long_yes(self):
        for text in ("بله", "آره", "باشه", "بله شروع کن", "آره بگیرش", "اوکی شروع کن", "بله بگیر", "آره دانلود کن"):
            self.assertEqual(OC.confirm_word(toks(text)), "confirm", text)

    def test_confirm_word_no_and_cancel(self):
        for text in ("نه", "نه ممنون", "نخیر", "ولش کن", "بیخیال", "نمی‌خوام"):
            self.assertIn(OC.confirm_word(toks(text)), ("deny", "cancel"), text)

    def test_a_sentence_that_only_contains_a_yes_is_not_an_answer(self):
        for text in ("بله ولی اول بگو چقدر جا می‌گیرد", "آره می‌دونم که هوا خوبه ولی نه", "شروع کن برو بگیر و بعد هم یک چیز دیگر", "امروز بله",
                     "ساعت چنده", "چرا؟"):
            self.assertNotIn(OC.confirm_word(toks(text)), ("confirm",), text)

    def test_a_no_inside_a_long_yes_is_never_a_yes(self):
        self.assertNotEqual(OC.confirm_word(toks("بله نه")), "confirm")
        self.assertNotEqual(OC.confirm_word(toks("نه بگیرش")), "confirm")


# ====================================================================== no dead advice
KNOWN_COMMANDS = {BM.START: OC.GET, BM.STATUS: OC.STATUS, BM.PAUSE: OC.PAUSE, BM.RESUME: OC.RESUME, BM.DELETE: OC.DELETE, BM.TEST: OC.TEST,
                  BM.RETRY: OC.RETRY}
# words the texts quote that other parts of the app (not this classifier) understand: the answer to the open question, the choice,
# and the emergency words
OTHER_UNDERSTOOD = {"بله", "نه", "سبک", "قوی", "ایست", "ادامه", "بله / نه"}
# the app-wide internet switch is the HUB's own command (not the own brain's): the texts tell the user to use it, so the hub must really understand it
HUB_COMMANDS = {"اینترنت را خاموش کن": HI.NET_OFF, "اینترنت را روشن کن": HI.NET_ON}
# quoted words that DESCRIBE (the word the app only says when it is true, a fallback word) - nothing is asked of the user with them
DESCRIPTIVE = {"آماده", "آماده است", "مغزِ زبانی", "نامشخص", "اینترنتِ برنامه"}


def _facts():
    return {"ram": 8_000_000_000, "free": 20_000_000_000, "engine_ok": True, "engine_code": "ok", "online": "online"}


def _states():
    base = {"phase": "idle", "sub": "", "choice": "strong", "title_fa": catalog.STRONG_CHOICE.short_fa, "model_id": "m", "bytes": 0, "total": 0,
            "percent": 0, "speed": 0, "eta": None, "code": "", "detail": "", "consent": True, "resumable": False}
    out = []
    for phase in ("idle", "downloading", "installing", "ready", "failed", "paused"):
        for sub in ("", "download", "verify"):
            for code in ("", "user_paused", "halted", "app_closed", "net_off", "permission_denied", "offline", "hash_mismatch", "crashed_before", "engine_load_failed", "smoke_test_failed",
                         "unavailable_platform", "interrupted", "zzz_unknown"):
                for resumable in (False, True):
                    out.append(dict(base, phase=phase, sub=sub, code=code, resumable=resumable, bytes=1_000_000, total=2_000_000, percent=50,
                                    speed=500_000, eta=120))
    return out


def all_texts():
    """Every text the own brain's chat can say, over every state and code it knows."""
    strong, light = catalog.STRONG_CHOICE, catalog.LIGHT_CHOICE
    facts = _facts()
    texts = [BM.what_it_is(), BM.cancelled(), BM.setup_failed(), BM.none_fits(facts), BM.started(strong), BM.started(light, resumed=True),
             BM.paused({"percent": 40}), BM.halted_note(), BM.resumed_note(), BM.ask_delete({"held": 5_000_000}), BM.ask_delete({"held": 0}),
             BM.deleted(1_000_000_000), BM.deleted(0), BM.delete_cancelled(), BM.nothing_to_delete(), BM.test_failed("x", 3.0),
             BM.test_failed("timeout", 170.0), BM.retry_started(), BM.first_answer_note(strong.short_fa), BM.llm_timeout(170, True),
             BM.llm_timeout(170), BM.busy_installing(), BM.started(strong, net_turned_on=True), BM.net_off_note({"percent": 40}),
             BM.net_off_note({})]
    for choice, alt in ((strong, light), (light, strong), (strong, None)):
        for partial in (0, 500_000_000):
            texts.append(BM.offer_card(choice, alt, facts, partial))
            texts.append(BM.offer_card(choice, alt, facts, partial, ask=False))
        texts.append(BM.clarify_consent(choice))
        for code in ("engine_missing", "ram_unknown", "ram_too_small", "not_enough_space", "offline", "already_running", "have_other",
                     "nothing_to_resume", "network_off", "network_failed", "zzz_other"):
            texts.append(BM.blocked(code, "100/200", choice, facts))
    for code in ("unavailable_platform", "dependency_missing", "crashed_before", "engine_load_failed", "model_file_invalid", "smoke_test_failed",
                 "hash_mismatch", "size_mismatch", "remote_changed", "host_not_allowed", "offline", "dns_failure", "timeout", "tls_error", "interrupted",
                 "insufficient_space", "unexpected_error", "zzz_unknown", "empty", "model_not_usable", "engine_generate_failed", "permission_denied"):
        texts.append(BM.failure_text(code, "detail"))
        texts.append(BM.llm_failed(code))
    for state in _states():
        texts.append(BM.status(state))
        texts.append(BM.nothing_running(state))
        texts.append(BM.not_ready_for_test(state))
    for phase in ("none", "downloading", "installing", "paused", "failed", "ready"):
        texts.extend((BM.lead_line(phase, 40), BM.about_line(phase, 40), BM.lead_short(phase, 40)))
    return texts


class NoDeadAdviceTests(unittest.TestCase):
    def test_every_sentence_the_app_tells_the_user_to_say_is_understood(self):
        for sentence, kind in KNOWN_COMMANDS.items():
            self.assertEqual(kind_of(sentence), kind, sentence)

    def test_every_quoted_phrase_in_the_texts_is_understood_somewhere(self):
        titles = {c.short_fa for c in catalog.CHOICES}
        quoted = set()
        for text in all_texts():
            quoted.update(re.findall("«([^»]+)»", text))
        unknown = sorted(q for q in quoted if q not in KNOWN_COMMANDS and q not in OTHER_UNDERSTOOD and q not in DESCRIPTIVE and q not in titles
                         and q not in HUB_COMMANDS
                         and not re.fullmatch("[A-Za-z0-9_]+", q))          # a plain-ASCII quote is a failure code, not a phrase
        self.assertEqual(unknown, [], "the texts tell the user to say phrases that nothing understands")

    def test_the_internet_words_the_texts_quote_are_the_hubs_real_commands(self):
        """The texts send the user to the app-wide internet switch; a word that the hub did not understand would be dead advice."""
        for sentence, kind in HUB_COMMANDS.items():
            norm = nz.normalize(sentence)
            command = HI.classify(sentence, norm, fa_text.words(norm))
            self.assertIsNotNone(command, sentence)
            self.assertEqual(command.kind, kind, sentence)
        quoted = set()
        for text in all_texts():
            quoted.update(re.findall("«([^»]+)»", text))
        self.assertTrue(set(HUB_COMMANDS) & quoted, "the texts really do quote the internet words (this test would otherwise prove nothing)")

    def test_the_texts_are_not_empty_and_never_raise(self):
        texts = all_texts()
        self.assertGreater(len(texts), 300)
        for text in texts:
            self.assertIsInstance(text, str)
            self.assertTrue(text.strip())

    def test_no_text_calls_the_brain_ready_unless_the_state_is_ready(self):
        for state in _states():
            if state["phase"] == "ready":
                continue
            for text in (BM.status(state), BM.nothing_running(state), BM.not_ready_for_test(state)):
                self.assertNotIn("آماده است ✅", text, state)
                self.assertNotIn("آزمایش گذشت", text)

    def test_the_offer_names_what_the_user_must_know_before_saying_yes(self):
        for choice, alt in ((catalog.STRONG_CHOICE, catalog.LIGHT_CHOICE), (catalog.LIGHT_CHOICE, catalog.STRONG_CHOICE)):
            card = BM.offer_card(choice, alt, _facts(), 0)
            for must in ("بدون کلید", "بدون هزینه", "huggingface.co", "SHA-256", "VPN", "گیگابایت" if choice.key == "strong" else "مگابایت",
                         "هنوز آزمایش نشده", "«بله»", "«نه»", BM.PAUSE, BM.DELETE):
                self.assertIn(must, card, (choice.key, must))
            self.assertIn(alt.short_fa, card)

    def test_the_costly_choice_is_not_started_by_the_asking_words(self):
        # the explanation form never asks «بله»: it says how to start instead
        card = BM.offer_card(catalog.STRONG_CHOICE, catalog.LIGHT_CHOICE, _facts(), 0, ask=False)
        self.assertNotIn("بگو «بله»", card)
        self.assertIn(BM.START, card)


if __name__ == "__main__":
    unittest.main()
