"""
Prompt 958 - the assistant knows itself, through the real Persian chat.

The Persian brain (FULL scope) on a real MemorySystem and a real hub; the phone is a set of hand-written doubles (the fake Android `FakeJava`, the
fake MediaPipe engine, the hub's Android bridge). What is proven:

* a sentence ABOUT the assistant («چه کارهایی بلدی؟», «مغز فارسی داری؟», «خودت را ارتقا بده», «صدایم را می‌شنوی؟», «می‌تونی از ChatGPT کمک بگیری؟»)
  is recognised by a closed word-list cascade; an ordinary sentence, a command that already had an owner and a wish are left alone;
* every «دارم / بلدم» in the answer is written from what THIS phone's app really has right now - no language model: it says so; a model that was
  imported but cannot run: it says why; a usable model: it says so (and that it is small); the voice button, the assistant apps found on the
  phone, the installed packs and the internet switch the same way. A thing that is absent is never claimed;
* the answers only EXPLAIN: nothing is started, installed, imported, downloaded, sent or opened by them, and no wish is remembered;
* «چه کارهایی بلدی؟» and «توانایی‌هات چیه؟» give one and the same answer, which also lists what the assistant built for itself;
* a question that nothing in the app can answer gets an honest «نمی‌دانم + راه‌ها» reply instead of silence - the long text once, a short one
  when asked again soon; the question is remembered so that a plain «از ChatGPT بخواه» takes it on. A greeting, a statement or a yes/no is
  not claimed, and a usable language model still gets the free questions.
NOT proven: that a real phone behaves like these doubles, or how good a real model's Persian is.
"""

import json
import os
import re
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import gaps, pack_prompt
from brain_hub.service import HubService
from model_runtime import MediaPipeLlmRuntime, NgramRuntime
from native_bridge import facade as native_facade
from persian_brain import activation, hub_hooks, hub_messages_self as HS, hub_messages_tools as HT, hub_self, hub_state
from persian_brain import messages as M
from persian_brain import normalization as nz
from teacher import assistants as teacher_assistants
from teacher import service as teacher_service
from tests import brain_hub_fixtures_prompt957 as F
from tests.llm_support_prompt958 import LLM_CLASS, with_llm_engine
from tests.test_pack_chat_prompt958 import PackChatCase
from tests.test_persian_llm_chat_prompt958 import QUESTION, LlmChatCase

CHATGPT, CLAUDE, OWN = "com.openai.chatgpt", "com.anthropic.claude", teacher_service.OWN_PACKAGE
ZWNJ = chr(0x200C)
HEAR_MARKS = {c: None for c in range(0x2066, 0x206A)}


def kind_of(sentence):
    return hub_self.classify(nz.normalize(sentence), nz.tokens(sentence))


# ======================================================================================= which sentence is about the assistant
SENTENCES = {
    hub_self.ABOUT: (
        "چه کارهایی می‌توانی انجام بدهی؟", "چه کارهایی بلدی؟", "چی بلدی؟", "چه کاری از دستت برمیاد؟", "توانایی‌هات چیه؟", "قابلیت‌هات چیه؟",
        "امکاناتت چیه؟", "تو کی هستی؟", "تو چی هستی؟", "خودت را معرفی کن", "چه کمکی می‌تونی بکنی؟", "می‌تونی بهم کمک کنی؟",
        "چه کارایی میتونی انجام بدی", "تو ChatGPT هستی؟", "تو چت جی پی تی هستی؟"),
    hub_self.BRAIN: (
        "مغز فارسی داری؟", "فارسی می‌فهمی؟", "هر چیزی بگویم می‌فهمی؟", "هوش مصنوعی داری؟", "چقدر باهوشی؟", "چطور هوشمندت کنم؟",
        "چطور باهوش‌ترت کنم؟", "فارسی بلدی؟", "همه چی رو میفهمی؟", "مدل زبانی داری؟", "LLM داری؟", "تو از چه مدلی استفاده می‌کنی؟",
        "تو هوش مصنوعی هستی؟"),
    hub_self.UPGRADE: (
        "کد خودت را تغییر بده", "خودت را ارتقا بده", "خودت را قوی‌تر کن", "می‌تونی خودت رو آپگرید کنی؟", "می‌تونی کد خودت رو عوض کنی؟",
        "خودت را آپدیت کن", "خودتو بهتر کن", "قوی‌تر شو", "پیشرفت کن", "هوشمندتر شو", "می‌تونی خودت اپدیت شی؟"),
    hub_self.VOICE: (
        "می‌تونی صدامو بشنوی؟", "با صدا باهات حرف بزنم؟", "می‌تونی حرف بزنی؟", "صدای من رو می‌شنوی؟", "می‌تونی حرفامو بشنوی؟", "حرفامو بشنو"),
    hub_self.OUTSIDE: (
        "می‌تونی بری توی گوگل جستجو کنی؟", "می‌تونی بری توی اینترنت؟", "می‌تونی با چت جی پی تی حرف بزنی؟", "می‌تونی با کلود صحبت کنی؟",
        "می‌تونی از کلود کمک بگیری؟", "می‌تونی از برنامه‌های دیگه استفاده کنی؟", "میتونی از ChatGPT کمک بگیری؟", "می‌تونی از Claude بپرسی؟",
        "می‌تونی از گوگل جواب بگیری؟"),
}
# Everything here has another owner (a greeting, a taught fact, a build request, a wish, a plain question) or is not about the assistant.
OTHER_SENTENCES = (
    "امروز هوا چطوره؟", "پایتخت فرانسه کجاست؟", "یه شعر بگو", "ایران چند استان داره؟", "تفاوت پایتون و جاوا چیه؟", "سلام", "اسم من عرفان است",
    "یاد بگیر که پایتخت ایران تهران است", "یک مبدل کیلومتر به مایل بساز", "از ChatGPT بخواه یه عکس بسازه", "ChatGPT چیه؟",
    "خودت یک کد برای این کار بنویس", "برنامه بنویس که", "یه عکس از گربه برام بساز", "چه ساعتیه؟", "می‌تونی ۲ و ۲ رو جمع کنی؟",
    "چه کاری باید بکنم؟", "کمکم کن", "ساعت چنده", "این برنامه چطور کار می‌کنه؟", "چی کار کنم؟", "خودت چی فکر می‌کنی؟", "به حرفم گوش بده",
    "امکانات هتل چیه؟", "چی بلدی درباره ایران بگی؟", "تو هستی؟", "یک ماشین‌حساب بهتر بساز", "این متن را کامل کن", "قیمت را تغییر بده",
    "اسم من چیست؟", "اسمم چیه؟", "اسم کتاب چیه؟", "اسم تو چیه؟ اسم من عرفان است")      # (the last one carries a personal fact: another owner)


class Classification(unittest.TestCase):
    def test_each_sentence_gets_its_kind(self):
        for kind, sentences in SENTENCES.items():
            for sentence in sentences:
                with self.subTest(kind=kind, sentence=sentence):
                    self.assertEqual(kind_of(sentence), kind)

    def test_every_kind_has_sentences_and_the_kinds_are_exactly_these_five(self):
        self.assertEqual(set(SENTENCES), set(hub_self.KINDS))
        self.assertEqual(hub_self.KINDS, ("about", "brain", "upgrade", "voice", "outside"))
        self.assertTrue(all(len(v) >= 6 for v in SENTENCES.values()))

    def test_other_sentences_are_left_alone(self):
        for sentence in OTHER_SENTENCES:
            with self.subTest(sentence=sentence):
                self.assertIsNone(kind_of(sentence))

    def test_a_question_mark_spelling_variants_and_extra_spaces_do_not_matter(self):
        variants = (("چه کارهایی بلدی", "about"), ("چه   کارهایی\nبلدی؟؟؟", "about"), ("چه كارهايي بلدي؟", "about"), ("چه کارهایی بلدییییی؟", "about"),
                    ("مغز فارسی داری", "brain"), ("مغز  فارسی   داری؟", "brain"), ("مغز فارسي داري؟", "brain"),
                    ("می" + ZWNJ + "تونی صدامو بشنوی؟", "voice"), ("می تونی صدامو بشنوی", "voice"), ("میتونی صدامو بشنوی؟", "voice"),
                    ("خودت را ارتقا بده!", "upgrade"), ("خودتو ارتقاء بده", "upgrade"))
        for sentence, kind in variants:
            with self.subTest(sentence=sentence):
                self.assertEqual(kind_of(sentence), kind)

    def test_the_voice_of_the_other_assistant_is_not_the_voice_of_this_one(self):
        self.assertEqual(kind_of("می‌تونی با چت جی پی تی حرف بزنی؟"), "outside")       # «حرف بزنی» + a named assistant: that is about the assistant
        self.assertEqual(kind_of("می‌تونی حرف بزنی؟"), "voice")                       # the same words without a name: that is about speech

    def test_garbage_and_very_long_input_is_never_taken_for_a_question_about_the_assistant(self):
        for norm, toks in (("", []), (None, ["a"]), (5, ["a"]), ("چه کارهایی بلدی", []), ("x" * 300, ["چه", "کارهایی", "بلدی"]),
                           ("چه کارهایی بلدی " * 10, ("چه کارهایی بلدی " * 10).split())):
            with self.subTest(norm=str(norm)[:20]):
                self.assertIsNone(hub_self.classify(norm, toks))
        long_text = "چه کارهایی بلدی؟ " + "این یک متن بلند است " * 15
        self.assertIsNone(kind_of(long_text))

    def test_a_name_is_not_enough_it_needs_the_question(self):
        for sentence in ("گوگل", "ChatGPT", "کلود", "اینترنت", "صدا", "مغز", "هوش", "خودت"):
            with self.subTest(sentence=sentence):
                self.assertIsNone(kind_of(sentence))


# ======================================================================================= the phone
class SelfCase(LlmChatCase, PackChatCase):
    """The real brain and hub with a fake phone: its installed apps (`installed`), the native doors its APK declares (`native`) and a fake MediaPipe engine."""
    installed = ()
    native = ("file_chooser", "permission_request", "voice_input")

    def setUp(self):
        native_facade.reset_for_tests()
        teacher_service.reset_for_tests()
        self.addCleanup(native_facade.reset_for_tests)
        self.addCleanup(teacher_service.reset_for_tests)
        super().setUp()
        self.jvm.installed.update(self.installed)
        native_facade.set_jvm(self.jvm)

    def new_hub(self, memory):
        jvm = self.jvm
        return HubService(self.hub_root, memory=memory, clock=self.clock, transport=self.fetch, download_transport=self.stream, free_space_fn=F.PLENTY,
                          bridge=F.HubFakeBridge(native=self.native),
                          model_runtimes=[NgramRuntime(), MediaPipeLlmRuntime(jvm_provider=lambda: jvm)])

    # ------------------------------------------------------------------ helpers
    def snap(self):
        return hub_hooks._self_snapshot(self.brain)

    def import_without_engine(self, name="gemma-test.task"):
        """A model file whose engine this APK does not have: imported and verified, but it cannot run."""
        self.jvm.classes.pop(LLM_CLASS, None)
        self.put(name)
        self.say("مدل %s را وارد کن" % name)
        done = self.say("بله")
        self.assertIn("dependency_missing", done)
        return done

    def import_with_failing_engine(self, name="gemma-test.task"):
        with_llm_engine(self.jvm, load_error=RuntimeError("boom"))
        self.put(name)
        self.say("مدل %s را وارد کن" % name)
        done = self.say("بله")
        self.assertIn("engine_load_failed", done)
        return done

    def changes(self):
        """Everything an explanation must NOT change, as one comparable value."""
        service = teacher_service.get_service(self.hub)
        latest = service.store.latest(only_open=False) if service is not None else None
        return {"pending": self.pending(), "models": sorted(m.model_id for m in self.hub.list_models()), "packs": self.pm().list(),
                "extensions": self.installed_ids(), "mission": latest["id"] if latest else None, "started": list(self.jvm.started),
                "clipboard": self.jvm.clipboard, "downloads": len(self.stream.requests), "fetches": len(self.fetch.requests),
                "model_calls": self.prompts(), "wish": hub_state.load_wish(self.memory, self.clock)}

    def lines(self, reply):
        return [line.strip() for line in reply.split("\n") if line.strip()]

    def bullets(self, reply):
        return [line for line in self.lines(reply) if line.startswith("•")]


# ======================================================================================= what it says it has is what it has
def assert_honest_limits(case, reply):
    """What this build cannot do yet is named in every state - whatever else the phone has."""
    case.assertIn("ساخت عکس، ویدیو و آهنگ", reply)
    case.assertIn("جارویس", reply)
    case.assertIn("گوش‌دادنِ همیشگی", reply)


class ModelStates(SelfCase):
    def test_without_a_model_it_says_so_and_names_the_button(self):
        self.assertEqual(self.snap()["model"]["state"], "none")
        brain = self.say("مغز فارسی داری؟")
        self.assertIn("هنوز هیچ مدل زبانی‌ای روی گوشی ندارم", brain)
        self.assertIn(HS.MODEL_BUTTON, brain)
        self.assertNotIn("بارگذاری و آزموده شده", brain)
        about = self.say("چه کارهایی بلدی؟")
        self.assertIn("جواب آزاد به هر پرسشی (مدل زبانی ندارم)", about)
        self.assertNotIn("پاسخ آزاد به پرسش‌ها با یک مدل زبانیِ کوچک", about)
        assert_honest_limits(self, about)

    def test_a_model_that_cannot_run_is_not_claimed_and_the_reason_is_said(self):
        self.import_without_engine()
        self.assertEqual(self.snap()["model"]["state"], "imported")
        brain = self.say("مغز فارسی داری؟")
        self.assertIn("وارد شده ولی هنوز قابل اجرا نیست", brain)
        self.assertIn("موتورِ اجرای آن قالب را ندارد", brain)
        self.assertNotIn("بارگذاری و آزموده شده", brain)
        about = self.say("چه کارهایی بلدی؟")
        self.assertIn("جواب آزاد به هر پرسشی (مدل زبانی ندارم)", about)            # still true: nothing usable
        self.assertNotIn("پاسخ آزاد به پرسش‌ها با", about)
        self.assertEqual(self.prompts(), 0)

    def test_a_model_whose_test_failed_says_the_test_failed(self):
        self.import_with_failing_engine()
        self.assertEqual(self.snap()["model"]["state"], "imported")
        brain = self.say("مغز فارسی داری؟")
        self.assertIn("آزمونش ناموفق بود", brain)
        self.assertNotIn("بارگذاری و آزموده شده", brain)

    def test_a_usable_model_is_claimed_together_with_its_honest_limit(self):
        self.import_model()
        snapshot = self.snap()
        self.assertEqual(snapshot["model"]["state"], "usable")
        self.assertEqual(snapshot["model"]["title"], "gemma-test")
        brain = self.say("مغز فارسی داری؟")
        self.assertIn("بارگذاری و آزموده شده", brain)
        self.assertIn("gemma-test", brain)
        self.assertIn("به‌اندازهٔ ChatGPT هوشمند نیست", brain)                      # the honest limit of a model that fits on a phone
        self.assertNotIn("هنوز هیچ مدل زبانی‌ای روی گوشی ندارم", brain)
        about = self.say("چه کارهایی بلدی؟")
        self.assertIn("پاسخ آزاد به پرسش‌ها با یک مدل زبانیِ کوچک", about)
        self.assertNotIn("(مدل زبانی ندارم)", about)
        assert_honest_limits(self, about)                                         # a model does not give it images or a wake word

    def test_the_same_question_is_answered_differently_after_the_model_arrives(self):
        before = self.say("مغز فارسی داری؟")
        self.import_model()
        after = self.say("مغز فارسی داری؟")
        self.assertNotEqual(before, after)
        self.assertIn("هنوز هیچ مدل زبانی‌ای روی گوشی ندارم", before)
        self.assertIn("بارگذاری و آزموده شده", after)

    def test_the_model_is_never_asked_who_the_assistant_is_but_still_gets_the_free_questions(self):
        self.import_model()
        asked = self.prompts()                                                    # the import's own self-test already used the engine once
        for sentence in ("تو کی هستی؟", "مغز فارسی داری؟", "تو ChatGPT هستی؟", "خودت را ارتقا بده", "می‌تونی صدامو بشنوی؟", "می‌تونی از کلود کمک بگیری؟"):
            with self.subTest(sentence=sentence):
                reply = self.say(sentence)
                self.assertEqual(self.prompts(), asked)                           # a small model would answer as itself («من مدل گوگل هستم»)
                self.assertNotIn(self.answers[0], reply)
                self.assertEqual(self.trace_kind()[0], "HUB")
        reply = self.say(QUESTION)
        self.assertIn(self.answers[0], reply)                                     # a real free question still reaches the model
        self.assertEqual(self.prompts(), asked + 1)

    def test_the_unknown_reply_names_a_model_that_cannot_run(self):
        self.import_without_engine()
        reply = self.say("امروز هوا چطوره؟")
        self.assertIn("این را نمی‌دانم", reply)
        self.assertIn("وارد شده ولی هنوز قابل اجرا نیست", reply)
        self.assertIn("وضعیت مدل‌ها", reply)                                       # the next step it names
        self.assertEqual(self.prompts(), 0)


class VoiceStates(SelfCase):
    def test_with_the_voice_button_it_is_claimed_as_speech_to_text_only(self):
        self.assertIn("voice_input", self.snap()["native"])
        voice = self.say("می‌تونی صدامو بشنوی؟")
        self.assertIn(HS.VOICE_BUTTON, voice)
        self.assertIn("پنجرهٔ گفتارِ خودِ اندروید", voice)
        self.assertIn("تا «ارسال» نزنی چیزی فرستاده نمی‌شود", voice)
        self.assertIn("من خودم میکروفون را باز نمی‌کنم", voice)
        for missing in ("گوش‌دادنِ همیشگی", "جارویس", "جواب‌دادن با صدای بلند"):
            self.assertIn(missing, voice)                                         # what it does NOT have is said in the same breath
        self.assertIn(HS.VOICE_BUTTON, self.say("چه کارهایی بلدی؟"))

    def test_without_the_voice_button_it_is_not_claimed(self):
        self.native = ("file_chooser", "permission_request")
        self.open_app()
        self.assertNotIn("voice_input", self.snap()["native"])
        voice = self.say("می‌تونی صدامو بشنوی؟")
        self.assertIn("این نسخهٔ برنامه دکمهٔ گفتار ندارد", voice)
        self.assertNotIn("گفتار به متن دارم", voice)
        self.assertNotIn(HS.VOICE_BUTTON, voice)
        self.assertIn("جارویس", voice)
        about = self.say("چه کارهایی بلدی؟")
        self.assertNotIn(HS.VOICE_BUTTON, about)
        self.assertNotIn("گفتار به متن:", about)
        assert_honest_limits(self, about)

    def test_the_graph_shows_the_same_state_as_the_answer(self):
        node = self.hub.graph().get("android.voice_input")
        self.assertEqual(node.state, "available")
        self.native = ("file_chooser",)
        self.open_app()
        self.assertEqual(self.hub.graph().get("android.voice_input").state, "dependency_blocked")


class AssistantApps(SelfCase):
    installed = (CHATGPT, CLAUDE, OWN)

    def test_the_apps_found_on_the_phone_are_named(self):
        rows = {row["id"]: row for row in self.snap()["assistants"]}
        self.assertTrue(rows["chatgpt"]["installed"])
        self.assertTrue(rows["claude"]["installed"])
        about = self.say("چه کارهایی بلدی؟")
        self.assertIn("پرسیدن از «ChatGPT» و «Claude» با اجازهٔ تو (برنامه‌اش روی گوشی هست)", about)
        outside = self.say("می‌تونی از ChatGPT کمک بگیری؟")
        self.assertIn("برنامهٔ «ChatGPT» و «Claude» روی گوشی دیده شد", outside)
        self.assertNotIn("روی گوشی دیده نشد", outside)

    def test_only_the_app_that_is_really_there_is_named(self):
        self.jvm.installed.discard(CHATGPT)
        self.assertEqual([r["id"] for r in self.snap()["assistants"] if r["installed"]], ["claude"])
        about = self.say("چه کارهایی بلدی؟")
        self.assertIn("پرسیدن از «Claude» با اجازهٔ تو", about)
        self.assertNotIn("«ChatGPT»", about)


class NoAssistantApps(SelfCase):
    installed = ()

    def test_without_the_apps_it_says_the_sites_will_open_instead(self):
        self.assertEqual([r for r in self.snap()["assistants"] if r["installed"]], [])
        about = self.say("چه کارهایی بلدی؟")
        self.assertIn("برنامه‌شان روی گوشی دیده نشد؛ سایتشان باز می‌شود", about)
        outside = self.say("می‌تونی از ChatGPT کمک بگیری؟")
        self.assertIn("برنامهٔ ChatGPT یا Claude روی گوشی دیده نشد؛ سایتشان باز می‌شود", outside)
        brain = self.say("چطور باهوش‌ترت کنم؟")
        self.assertIn("پرسیدن از ChatGPT یا Claude", brain)


class PacksAndInternet(SelfCase):
    def test_the_packs_line_counts_what_is_really_installed(self):
        self.assertEqual(self.snap()["packs"], {"active": 0, "installed": 0, "safe": False})
        self.assertIn("هنوز بسته‌ای نصب نشده", self.say("چه کارهایی بلدی؟"))
        self.install_pack(self.code())
        self.assertEqual(self.snap()["packs"]["active"], 1)
        about = self.say("چه کارهایی بلدی؟")
        self.assertIn("۱ بستهٔ نصب‌شده و فعال", about)
        self.assertNotIn("هنوز بسته‌ای نصب نشده", about)

    def test_the_internet_line_follows_the_users_own_switch(self):
        self.assertFalse(self.snap()["internet"])
        self.assertIn("بعد از اینکه خودت اینترنتِ برنامه را روشن کنی", self.say("چه کارهایی بلدی؟"))
        self.hub.grant_permission("network", user_approved=True)
        self.assertTrue(self.snap()["internet"])
        about = self.say("چه کارهایی بلدی؟")
        self.assertIn("اینترنتِ برنامه الان روشن است", about)
        self.assertNotIn("بعد از اینکه خودت اینترنتِ برنامه را روشن کنی", about)


class HonestAnswers(SelfCase):
    def test_outside_names_the_real_doors_and_their_conditions(self):
        reply = self.say("می‌تونی بری توی گوگل جستجو کنی؟")
        self.assertIn("فقط با اجازهٔ تو", reply)
        self.assertIn("جستجوی گوگل ندارم", reply)                                     # no invented search engine
        self.assertIn("«از ChatGPT بخواه …»", reply)
        self.assertIn("سرویس دسترسی‌پذیری", reply)
        self.assertIn("اندروید اجازه نمی‌دهد برنامه خودش این سرویس را روشن کند", reply)
        self.assertIn("فقط به‌عنوان متن می‌خوانم و اجرا نمی‌کنم", reply)
        self.assertIn("هیچ‌کدام بی‌صدا یا بدون اجازه انجام نمی‌شود", reply)

    def test_upgrade_names_the_three_safe_ways_and_claims_nothing_done(self):
        reply = self.say("خودت را ارتقا بده")
        for word in ("«بسته»", "«بله»ی تو", "برمی‌گردد", HS.MODEL_BUTTON, "نسخهٔ تازه در GitHub", "بی‌صدا و خودسرانه"):
            self.assertIn(word, reply)
        for claimed in ("ارتقا دادم", "تغییر دادم", "نصب شد", "نصب کردم"):
            self.assertNotIn(claimed, reply)

    def test_brain_has_two_layers_and_says_the_rule_layer_does_not_understand_everything(self):
        reply = self.say("مغز فارسی داری؟")
        self.assertIn("لایهٔ همیشه‌حاضر", reply)
        self.assertIn("هر جملهٔ آزادی را نمی‌فهمد", reply)
        self.assertIn("برای کارهای سنگین، پرسیدن از ChatGPT یا Claude بهتر است", reply)
        for way in ("۱) مدل زبانی", "۲) بسته", "۳) پرسیدن از"):
            self.assertIn(way, reply)

    def test_about_says_who_it_is_and_what_it_cannot_do_yet(self):
        reply = self.say("تو کی هستی؟")
        self.assertIn("دستیار شخصی و فارسی‌زبانِ تو", reply)
        self.assertIn("نه ChatGPT و نه Claude", reply)
        self.assertIn("بدون اجازهٔ تو چیزی از گفتگوهایمان جایی فرستاده نمی‌شود", reply)
        assert_honest_limits(self, reply)
        self.assertIn("«نقشهٔ قابلیت‌ها»", reply)
        self.assertEqual(self.say("تو ChatGPT هستی؟"), reply)                     # «are you ChatGPT?» is answered by the same honest self-description


class SuggestedCommands(SelfCase):
    """Whatever the replies tell the user to say must really be understood by the app (no dead advice)."""
    installed = (CHATGPT, CLAUDE, OWN)
    ADVICE = (
        ("نقشهٔ قابلیت‌ها", "نقشهٔ قابلیت‌ها"), ("وضعیت مدل‌ها", "وضعیت مدل‌ها"), ("بسته چیست؟", "بسته چیست؟"),
        ("چطور مدل وارد کنم؟", "چطور مدل وارد کنم؟"), ("مدل‌ها", "مدل‌ها"), ("پرامپت بسته برای …", "پرامپت بسته برای ثبت خاطرات روزانه"),
        ("از ChatGPT بخواه …", "از ChatGPT بخواه یک ماشین‌حساب برایم بسازد"), ("اینترنت را روشن کن", "اینترنت را روشن کن"),
        ("چطور باهوش‌ترت کنم؟", "چطور باهوش‌ترت کنم؟"), ("تنظیمات دسترسی‌پذیری", "تنظیمات دسترسی‌پذیری"))

    def every_reply(self):
        texts = [self.say(s) for s in ("چه کارهایی بلدی؟", "مغز فارسی داری؟", "خودت را ارتقا بده", "می‌تونی صدامو بشنوی؟", "می‌تونی بری توی گوگل؟")]
        texts.append(self.say("امروز هوا چطوره؟"))
        return "\n".join(texts)

    def test_every_piece_of_advice_is_written_in_some_answer(self):
        everything = self.every_reply()
        self.import_without_engine()                                              # «وضعیت مدل‌ها» is advised for a model that cannot run
        self.clock.advance(16 * 60)                                               # (the long «nothing answers» text again)
        everything += "\n" + self.every_reply()
        for advice, _ in self.ADVICE:
            with self.subTest(advice=advice):
                self.assertTrue(advice in everything, advice)                     # (not assertIn: it would print every answer)

    def test_the_help_lists_the_ways_to_grow_and_the_older_list_stays_where_it_was(self):
        reply = self.say("راهنما")
        self.assertIn("«یک مبدل کیلومتر به مایل بساز»", reply)                       # the older list is still there, unchanged
        for advice in ("چه کارهایی بلدی؟", "مغز فارسی داری؟", "چطور باهوش‌ترت کنم؟", "بسته چیست؟", "پرامپت بسته برای …", "از ChatGPT بخواه …",
                       "چطور مدل وارد کنم؟", "مدل‌ها", "نقشهٔ قابلیت‌ها"):
            self.assertTrue(advice in reply, advice)
        self.assertEqual(self.trace_kind(), ("COMMAND", "help"))
        self.scope = activation.SCOPE_CAPABILITIES
        self.open_app()
        older = self.say("راهنما")
        self.assertEqual(older, M.help_text())                                     # outside the full app nothing is added
        self.assertNotIn("برای بزرگ‌ترکردنِ خودم", older)

    def test_every_piece_of_advice_is_understood_by_the_app(self):
        for _, sentence in self.ADVICE:
            with self.subTest(sentence=sentence):
                reply = self.say(sentence)
                self.assertTrue(reply)
                self.assertNotIn("این را نمی‌دانم", reply)
                self.assertEqual(self.trace_kind()[0], "HUB", reply)
                if self.pending() is not None:
                    self.say("نه")                                                  # withdraw a question the command opened


# ======================================================================================= the answers only explain
OWNED_ELSEWHERE = {                      # sentences of SENTENCES that an older, more specific owner in the app answers (the answer is as honest)
    "چه کارهایی بلدی؟": ("COMMAND", "list"), "چی بلدی؟": ("COMMAND", "list"), "چه کاری از دستت برمیاد؟": ("COMMAND", "list"),
    "چه کارایی میتونی انجام بدی": ("COMMAND", "list"), "مدل زبانی داری؟": ("HUB", "models_list")}


class ExplainOnly(SelfCase):
    installed = (CHATGPT, CLAUDE, OWN)

    def test_no_explanation_starts_installs_imports_downloads_sends_or_remembers_anything(self):
        before = self.changes()
        for kind, sentences in SENTENCES.items():
            for sentence in sentences:
                with self.subTest(sentence=sentence):
                    reply = self.say(sentence)
                    self.assertTrue(isinstance(reply, str) and reply.strip(), sentence)
                    self.assertEqual(self.trace_kind(), OWNED_ELSEWHERE.get(sentence, ("HUB", "self_" + kind)))
                    self.assertTrue(self.changes() == before, sentence)           # (not assertEqual: it would print every value)

    def test_a_plain_yes_after_an_explanation_has_nothing_to_confirm(self):
        for sentence in ("خودت را ارتقا بده", "می‌تونی از ChatGPT کمک بگیری؟", "چه کارهایی بلدی؟"):
            with self.subTest(sentence=sentence):
                self.say(sentence)
                before = self.changes()
                self.say("بله")
                self.assertTrue(self.changes() == before)                         # the explanation opened no question that a «بله» could confirm

    def test_an_explanation_does_not_leave_a_wish_behind_for_a_plain_ask(self):
        self.say("چه کارهایی می‌توانی انجام بدهی؟")
        self.say("خودت را ارتقا بده")
        self.assertEqual(hub_state.load_wish(self.memory, self.clock), "")
        reply = self.say("از Claude بخواه")
        self.assertIn("چه چیزی را از", reply)                                      # it asks what to request instead of sending an old sentence
        self.assertIsNone(self.pending())

    def test_a_wish_and_an_explicit_ask_still_work_as_before(self):
        reply = self.say("از ChatGPT بخواه یه قابلیت ساخت عکس برام بسازه")
        self.assertEqual(self.pending()[0], "teacher_send")
        self.assertIn("ساخت عکس", reply)
        self.assertEqual(self.jvm.started, [])                                    # still nothing leaves before the user's yes
        self.say("نه")
        reply = self.say("یه عکس از گربه برام بساز")                                # a wish the app cannot fulfil keeps its own honest reply
        self.assertIn("هنوز نمی‌توانم", reply)
        self.assertEqual(hub_state.load_wish(self.memory, self.clock), "یه عکس از گربه برام بساز")

    def test_older_commands_keep_their_owner(self):
        for sentence, sub in (("وضعیت مدل‌ها", "models_list"), ("بسته چیست؟", "pack_help"), ("نقشهٔ قابلیت‌ها", "overview"),
                              ("وضعیت اینترنت", "net_status"), ("وضعیت اندروید", "android_status"), ("بسته‌ها", "pack_list")):
            with self.subTest(sentence=sentence):
                self.say(sentence)
                self.assertEqual(self.trace_kind(), ("HUB", sub))


# ======================================================================================= a question nothing can answer
class UnknownReply(SelfCase):
    ASK = "پایتخت فرانسه کجاست؟"

    def test_a_question_nothing_answers_gets_an_honest_reply_with_the_real_ways(self):
        reply = self.say(self.ASK)
        self.assertIn("این را نمی‌دانم و از خودم جوابی برایش ندارم", reply)
        for word in (HS.MODEL_BUTTON, "«پرامپت بسته برای …»", "«از ChatGPT بخواه …»", "پرسشت را به‌خاطر سپردم"):
            self.assertIn(word, reply)
        self.assertNotIn("پاریس", reply)                                           # it never invents an answer
        self.assertEqual(self.trace_kind(), ("QUESTION", "general"))
        self.assertEqual(hub_state.load_wish(self.memory, self.clock), self.ASK)
        self.assertIsNone(self.pending())
        self.assertEqual(self.jvm.started, [])

    def test_a_request_the_app_has_no_rule_for_is_answered_the_same_honest_way(self):
        reply = self.say("یه شعر کوتاه درباره بهار بگو")
        self.assertIn("این را نمی‌دانم", reply)
        self.assertEqual(hub_state.load_wish(self.memory, self.clock), "یه شعر کوتاه درباره بهار بگو")

    def test_asked_again_soon_only_a_short_line_is_shown_and_after_a_quarter_of_an_hour_the_long_text_returns(self):
        long_text = self.say(self.ASK)
        self.clock.advance(14 * 60)
        short = self.say("پایتخت ایتالیا کجاست؟")
        self.assertIn("این را هم نمی‌دانم", short)
        self.assertIn("از ChatGPT بخواه", short)
        self.assertLess(len(short), len(long_text) // 2)
        self.assertEqual(hub_state.load_wish(self.memory, self.clock), "پایتخت ایتالیا کجاست؟")   # the newest question is the one kept
        self.clock.advance(2 * 60)
        again = self.say("پایتخت اسپانیا کجاست؟")
        self.assertIn("این را نمی‌دانم و از خودم جوابی برایش ندارم", again)

    def test_the_remembered_question_is_taken_on_by_a_plain_ask_and_nothing_leaves_before_the_yes(self):
        self.say(self.ASK)
        reply = self.say("از ChatGPT بخواه")
        self.assertIn("درخواست قبلی‌ات را برمی‌دارم", reply)
        self.assertIn("پایتخت فرانسه", reply)
        self.assertEqual(self.pending()[0], "teacher_send")
        self.assertEqual(self.jvm.started, [])
        self.assertIsNone(self.jvm.clipboard)

    def test_a_question_older_than_a_day_is_forgotten(self):
        self.say(self.ASK)
        self.clock.advance(25 * 3600)
        self.assertEqual(hub_state.load_wish(self.memory, self.clock), "")
        self.assertIn("چه چیزی را از", self.say("از ChatGPT بخواه"))

    def test_a_greeting_a_statement_a_bare_answer_or_one_word_is_not_claimed(self):
        for text in ("سلام", "امروز هوا خوب است", "بله", "نه", "مرسی", "چرا؟", "عالی"):
            with self.subTest(text=text):
                reply = self.say(text)
                self.assertNotIn("نمی‌دانم", reply or "")
        self.assertEqual(hub_state.load_wish(self.memory, self.clock), "")

    def test_a_very_long_text_is_left_to_the_core(self):
        text = self.ASK + " " + "این یک متن بسیار بلند است " * (hub_hooks.MAX_LLM_CHARS // 20)
        self.assertGreater(len(text), hub_hooks.MAX_LLM_CHARS)
        self.assertNotIn("نمی‌دانم", self.say(text) or "")
        self.assertEqual(hub_state.load_wish(self.memory, self.clock), "")

    def test_what_the_user_taught_or_a_pack_knows_is_answered_before_the_unknown_reply(self):
        self.say("یاد بگیر که پایتخت ایران تهران است")
        self.assertIn("تهران", self.say("پایتخت ایران کجاست؟"))
        from tests import pack_support_prompt958 as S
        self.install_pack(S.lang_pack(qa=[("پایتخت آلمان کجاست", "برلین")]))
        self.assertEqual(self.say("پایتخت آلمان کجاست؟"), "برلین")

    def test_the_free_model_still_gets_the_free_questions_and_the_unknown_reply_never_replaces_it(self):
        self.import_model()
        asked = self.prompts()
        self.assertIn(self.answers[0], self.say(QUESTION))
        self.assertEqual(self.prompts(), asked + 1)
        self.assertNotIn("این را نمی‌دانم", self.say(self.ASK))
        self.assertEqual(hub_state.load_wish(self.memory, self.clock), "")


# ======================================================================================= one answer to «what can you do?»
class UnifiedAbilityAnswer(SelfCase):
    ORDER = ("نه ChatGPT و نه Claude", "من این کارها را بلدم:", "و این‌ها را هم واقعاً دارم", "چیزهایی که هنوز نمی‌توانم:", "فهرست دقیق: «نقشهٔ قابلیت‌ها»")

    def test_both_ways_of_asking_give_the_same_answer_in_the_same_order(self):
        first = self.say("چه کارهایی بلدی؟")
        for other in ("توانایی‌هات چیه؟", "قابلیت‌هات چیه؟", "چی بلدی؟", "تو کی هستی؟", "چه کارهایی می‌توانی انجام بدهی؟"):
            with self.subTest(other=other):
                self.assertEqual(self.say(other), first)
        positions = [first.index(part) for part in self.ORDER]
        self.assertEqual(positions, sorted(positions))

    def test_the_built_in_abilities_are_listed_from_the_one_source(self):
        reply = self.say("توانایی‌هات چیه؟")
        for ability in M.BUILTIN_ABILITIES:
            self.assertIn("• " + ability, reply)
        self.assertIn("هنوز قابلیتی برای خودم نساخته‌ام", reply)

    def test_what_the_assistant_built_for_itself_appears_in_the_same_answer(self):
        self.assertIn("ساختم", self.say("یک مبدل کیلومتر به مایل بساز"))
        after = self.say("چه کارهایی بلدی؟")
        self.assertNotIn("هنوز قابلیتی برای خودم نساخته‌ام", after)
        self.assertIn("قابلیت‌هایی که خودم ساخته‌ام (۱)", after)
        self.assertIn("«تبدیل کیلومتر به مایل»", after)
        self.assertEqual(self.say("توانایی‌هات چیه؟"), after)

    def test_the_answer_is_written_from_the_snapshot_and_nothing_else(self):
        for _ in range(2):                                                         # the same phone state gives the same words, twice
            snapshot = self.snap()
            self.assertEqual(self.say("چه کارهایی بلدی؟"), HS.about(snapshot, hub_hooks._registry_lines(_FakeTurn(self.brain))))
            self.import_model() if snapshot["model"]["state"] == "none" else None

    def test_outside_the_full_app_the_older_list_stays_and_nothing_new_is_claimed(self):
        self.scope = activation.SCOPE_CAPABILITIES
        self.open_app()
        reply = self.say("چه کارهایی بلدی؟")
        self.assertIn("من این کارها را بلدم:", reply)
        self.assertNotIn("و این‌ها را هم واقعاً دارم", reply)
        self.assertIsNone(self.say("مغز فارسی داری؟"))
        self.assertIsNone(self.say("پایتخت فرانسه کجاست؟"))
        self.assertEqual(hub_state.load_wish(self.memory, self.clock), "")


class _FakeTurn:
    """The one field `_registry_lines` reads from a turn: the Self-Builder service."""

    def __init__(self, brain):
        from self_builder import service as sb_service
        self.service = sb_service.get_service(brain.memory)


# ======================================================================================= the status texts say the same
FULL_NATIVE = ("file_chooser", "permission_request", "voice_input", "accessibility", "share_target", "file_pick")   # what MainActivity.NATIVE_FEATURES declares


class StatusTexts(SelfCase):
    installed = (CHATGPT, CLAUDE, OWN)
    native = FULL_NATIVE

    def test_the_empty_models_list_names_the_button_and_the_formats(self):
        text = HT.models_list([], [])
        for word in (HS.MODEL_BUTTON, ".task", ".gguf", "چطور مدل وارد کنم؟", "n-gram"):
            self.assertIn(word, text)
        self.assertEqual(self.say("مدل‌ها را نشان بده").split("\n")[0][:30], text.split("\n")[0][:30])

    def test_the_wake_word_gap_separates_what_exists_from_what_does_not(self):
        gap = gaps.match_gap("می‌خوام با صدای بلند باهات حرف بزنم جارویس")
        self.assertEqual(gap.gap_id, "wake_word_voice")
        text = HT.gap_reply(gap)
        self.assertIn("«گفتار به متن» هست", text)
        self.assertIn(HS.VOICE_BUTTON, text)
        self.assertIn("جارویسِ» همیشه‌گوش و جواب با صدا یک APK تازه", text)
        self.assertIn("برنامه خودش APK نمی‌سازد و بی‌صدا نصب نمی‌کند", text)

    def test_the_other_apps_gap_names_the_one_real_door_and_its_limits(self):
        gap = gaps.match_gap("بیا توی تلگرام و اینستاگرام برام کار کن")
        self.assertEqual(gap.gap_id, "other_apps")
        text = HT.gap_reply(gap)
        for word in ("ChatGPT، Claude", "سرویس دسترسی‌پذیری", "برنامه نمی‌تواند خودش را روشن کند", "تنظیمات محدودشده", "روی گوشی هنوز آزموده نشده",
                     "برای تلگرام، اینستاگرام و واتساپ هیچ دستور کاری ندارم"):
            self.assertIn(word, text)

    def test_the_code_writing_gap_points_to_packs_and_the_model_button_not_only_to_the_old_extension_path(self):
        gap = gaps.match_gap("خودت یک کد برای این کار بنویس")
        self.assertEqual(gap.gap_id, "local_code_model")
        text = HT.gap_reply(gap)
        for word in ("بستهٔ کد یا بستهٔ زبان", HS.MODEL_BUTTON, "«پرامپت بسته برای …»"):
            self.assertIn(word, text)
        self.assertNotIn("ext.v1", text)

    def test_the_graph_nodes_describe_the_phone_the_answers_describe(self):
        graph = self.hub.graph()
        self.assertEqual(graph.get("tool.packs").state, "available")
        self.assertEqual(graph.get("tool.teacher").state, "available")
        for door in ("android.voice_input", "android.file_pick", "android.share_target"):
            self.assertEqual(graph.get(door).state, "available", door)
        self.assertEqual(graph.get("android.accessibility").state, "available")               # the service is switched on (the fake phone says so)

    def test_the_accessibility_door_is_blocked_until_the_user_switches_the_service_on_himself(self):
        self.jvm.connected = False
        node = self.hub.graph().get("android.accessibility")
        self.assertEqual(node.state, "permission_blocked")
        self.assertIn("خودت در تنظیمات اندروید روشن کنی", " ".join(b.text_fa for b in node.blockers))
        self.assertIn("تنظیمات دسترسی‌پذیری", " ".join(b.text_fa for b in node.blockers))      # the advice the node gives is a command the app understands
        self.say("تنظیمات دسترسی‌پذیری")
        self.assertEqual(self.trace_kind(), ("HUB", "access_settings"))
        self.assertTrue(self.jvm.started)                                                        # the page was only OPENED
        self.assertEqual(self.hub.graph().get("android.accessibility").state, "permission_blocked")

    def test_an_apk_without_a_door_says_a_new_build_has_it(self):
        self.native = ("file_chooser", "permission_request", "voice_input")
        self.open_app()
        for door in ("android.file_pick", "android.share_target", "android.accessibility"):
            node = self.hub.graph().get(door)
            self.assertEqual(node.state, "dependency_blocked", door)
            self.assertEqual([b.kind for b in node.blockers], ["new_apk"])
        self.assertEqual(self.hub.graph().get("android.voice_input").state, "available")

    def test_a_phone_without_the_apps_shows_the_teacher_as_a_website_route(self):
        self.jvm.installed.clear()
        node = self.hub.graph().get("tool.teacher")
        self.assertEqual(node.state, "available")
        self.assertIn("سایت", node.summary_fa)

    def test_the_model_node_follows_the_model_state(self):
        self.assertEqual(self.hub.graph().get("tool.local_model").state, "dependency_blocked")
        self.import_model()
        self.assertEqual(self.hub.graph().get("tool.local_model").state, "active")


# ======================================================================================= the documents stay true
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.abspath(os.path.join(PY_ROOT, "..", "..", "..", ".."))
DOCS = os.path.join(REPO_ROOT, "docs")
BRIEFING = os.path.join(DOCS, "chatgpt_briefing_prompt958.md")
GUIDE = os.path.join(DOCS, "baby_ai_guide_fa_prompt958.md")
TECH = os.path.join(DOCS, "self_knowledge_prompt958.md")
MAIN_ACTIVITY = os.path.join(REPO_ROOT, "app", "src", "main", "java", "com", "erfan", "standaloneai", "MainActivity.java")
PINNED = ("android_entry.py", "core/core.py", "ael/interpreter.py", "runtime_integration/bridge.py", "interface/server.py",
          "runtime_integration/runtime_core.py", "runtime_growth/runtime_growth_cycle.py")
PACK_FILE_NAMES = frozenset({"main.py", "__init__.py"})          # files INSIDE a pack, not files of this tree


def read_doc(path):
    if not os.path.isfile(path):
        raise unittest.SkipTest("the documentation is not part of this checkout layout")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def section(text, start, end):
    """The part of a document between two headings (both must exist)."""
    first = text.index(start)
    return text[first:text.index(end, first + len(start))]


class DocsStayTrue(SelfCase):
    """The briefing for ChatGPT and the user guide quote numbers, examples and sentences of the app. If the code moves and a document does not, a test
    here fails instead of the document quietly telling the user (or an assistant) something false."""

    def has(self, doc, text):
        self.assertTrue(text in doc, text)

    def test_the_briefing_states_the_live_pack_limits(self):
        doc = read_doc(BRIEFING)
        facts = pack_prompt.prompt_facts()
        for text in ("حداکثر %d ورودی" % facts["max_qa"], "حداکثر %d شکلِ پرسیدن" % facts["max_questions_per_entry"],
                     "حداکثر %d نویسه" % facts["max_question_chars"], "حداکثر %d نویسه" % facts["max_answer_chars"],
                     "حداکثر %d فایل و %d بایت" % (facts["max_files"], facts["max_total_bytes"]),
                     "حداکثر %d فایل، هر فایل حداکثر %d بایت، مجموع حداکثر %d بایت" % (facts["max_files"], facts["max_file_bytes"], facts["max_total_bytes"]),
                     "هر handler حداکثر %d ثانیه" % int(facts["handler_seconds"]), "`selftest` حداکثر %d ثانیه" % int(facts["selftest_seconds"])):
            self.has(doc, text)
        for name in facts["permissions"] + facts["blocked_calls"] + facts["protected_prefixes"]:
            self.has(doc, "`%s`" % name)
        self.assertTrue(set(facts["risky_permissions"]) <= set(facts["permissions"]))
        self.has(doc, "`، `".join(facts["risky_permissions"]))

    def test_the_briefing_quotes_the_real_example_packs_and_the_whole_api_table(self):
        doc = read_doc(BRIEFING)
        self.has(doc, pack_prompt.example_lang_pack_text().rstrip())
        self.has(doc, pack_prompt.example_code_pack_text().rstrip())
        for call, permission, _text in pack_prompt.API_DOC:
            self.has(doc, "`%s`" % call.replace("|", "\\|"))
            if permission:
                self.has(doc, "`%s`" % permission)

    def test_the_briefing_names_the_real_assistants_doors_and_pinned_files(self):
        doc = read_doc(BRIEFING)
        for assistant in teacher_assistants.ASSISTANTS:
            self.has(doc, assistant.title)
        for rel in PINNED:
            self.has(doc, "`%s`" % rel)
            self.assertTrue(os.path.isfile(os.path.join(PY_ROOT, rel)), rel)
        if os.path.isfile(MAIN_ACTIVITY):
            with open(MAIN_ACTIVITY, encoding="utf-8") as handle:
                java = handle.read()
            match = re.search(r"NATIVE_FEATURES\s*=\s*\{([^}]*)\}", java)
            self.assertTrue(match is not None, "NATIVE_FEATURES")
            names = re.findall(r'"([a-z_]+)"', match.group(1))
            self.assertTrue(len(names) >= 6, names)
            for name in names:
                self.has(doc, "`%s`" % name)

    def test_every_file_and_folder_the_briefing_points_at_exists(self):
        doc = read_doc(BRIEFING)
        folders = re.findall(r"`([a-z_]+/)`", doc)
        self.assertTrue(len(folders) >= 10, folders)
        for folder in folders:
            self.assertTrue(os.path.isdir(os.path.join(PY_ROOT, folder)), folder)
        names = {os.path.basename(name) for _root, _dirs, files in os.walk(PY_ROOT) for name in files}
        for token in re.findall(r"`([A-Za-z0-9_./]+\.py)`", doc):
            if token in PACK_FILE_NAMES:
                continue
            if "/" in token:
                self.assertTrue(os.path.isfile(os.path.join(PY_ROOT, token)), token)
            else:
                self.assertTrue(token in names, token)

    def test_the_guide_names_the_buttons_the_app_really_has(self):
        guide = read_doc(GUIDE)
        self.has(guide, HS.MODEL_BUTTON)
        self.has(guide, HS.VOICE_BUTTON)

    def test_every_command_the_guide_tells_the_user_to_type_is_understood(self):
        table = section(read_doc(GUIDE), "## ۵.", "## ۶.")
        commands = []
        for row in table.split("\n"):
            cells = row.split("|")
            if row.startswith("|") and len(cells) >= 3:               # the FIRST column holds what the user types; the second one explains
                commands.extend(q for q in re.findall(r"«([^»]+)»", cells[1]) if not any(ch in q for ch in "…<>/"))
        self.assertTrue(len(commands) >= 25, commands)
        for q in commands:
            if q == "جواب آمد":                  # it answers an open request; with none open it is an ordinary sentence (see the teacher tests)
                continue
            reply = self.say(q)
            self.assertTrue(reply is not None, q)
            self.assertFalse(reply.startswith("این را نمی‌دانم"), q)      # the honest "I do not know" means the sentence was NOT understood
            self.say("نه")                                               # no question stays open for the next sentence

    def test_the_guides_example_goes_from_a_wish_to_a_prepared_request_and_sends_nothing(self):
        first = self.say("یک عکس از گربه برام بساز")
        self.assertTrue("نمی‌توانم" in first, first)
        ask = self.say("از ChatGPT بخواه")
        self.assertTrue("یک عکس از گربه برام بساز" in ask, ask)
        self.assertTrue("بفرستم؟" in ask, ask)
        self.assertEqual(self.jvm.started, [])
        self.say("نه")
        self.assertEqual(self.jvm.started, [])

    def test_the_technical_note_lists_every_test_that_was_changed_on_purpose(self):
        note = read_doc(TECH)
        tests_dir = os.path.join(PY_ROOT, "tests")
        found = 0
        for name in sorted(os.listdir(tests_dir)):
            if not name.endswith(".py") or name == os.path.basename(__file__):          # (this file quotes the phrase itself)
                continue
            with open(os.path.join(tests_dir, name), encoding="utf-8") as handle:
                found += len(re.findall(r"Updated in Prompt 958 on purpose", handle.read()))
        rows = re.findall(r"^\| `[^`]*test_[^`]*` \|", note, flags=re.MULTILINE)
        self.assertEqual(found, len(rows), "every «Updated in Prompt 958 on purpose» comment needs its row in docs/self_knowledge_prompt958.md")


if __name__ == "__main__":
    unittest.main()
