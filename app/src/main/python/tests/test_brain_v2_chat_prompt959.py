"""Prompt 959 (stage A) - the cloud brain in the CHAT: the real Persian brain (FULL scope) on a real memory and a real hub, with a scripted
provider instead of the network.

What these tests protect, in the user's terms: nothing is saved or sent before his explicit words; the key never stays in the chat
history; every command does what it says; a failure says why; and the rest of the app (greetings, personal facts, self-knowledge,
the hub's own questions) keeps answering as it did, without ever reaching the cloud.
"""
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub.service import HubService
from brain_v2 import get_brain
from persian_brain import hub_brain
from tests import brain_hub_fixtures_prompt957 as F
from tests.persian_hub_case_prompt957 import HubChatCase
from tests.test_brain_v2_core_prompt959 import JSON, KEY, Fake, openai_answer

QUESTION = "پایتخت فرانسه کجاست؟"


class CloudChatCase(HubChatCase):
    def setUp(self):
        self.cloud = Fake((200, openai_answer("پایتخت فرانسه پاریس است."), JSON))
        super().setUp()

    def new_hub(self, memory):
        return HubService(self.hub_root, memory=memory, clock=self.clock, transport=self.cloud, download_transport=self.stream,
                          free_space_fn=F.PLENTY, bridge=F.HubFakeBridge())

    # ------------------------------------------------------------------ helpers
    @property
    def svc(self):
        return get_brain(self.hub)

    def brain_dir(self):
        return os.path.join(self.hub_root, "brain_v2")

    def logged(self):
        return json.dumps(self.memory.recent_messages(200), ensure_ascii=False)

    def connect(self, answer="پایتخت فرانسه پاریس است.", private="نه", memory=False):
        """The whole setup conversation; returns the replies. The answer memory is switched OFF unless `memory` (the tests of the cloud
        brain itself ask the same question twice and must see two requests; the memory has its own tests)."""
        self.cloud.script = [(200, openai_answer(answer), JSON)]
        replies = [self.say("مغز ابری را فعال کن"), self.say("۱"), self.say("بله"), self.say(KEY)]
        if private:
            replies.append(self.say(private))
        if not memory:
            self.svc.set_memory(False)
        return replies


class SetupConversationTests(CloudChatCase):
    def test_a_fresh_app_never_reaches_the_cloud_and_writes_nothing(self):
        reply = self.say(QUESTION)
        self.assertIsNotNone(reply)
        self.assertNotIn("پاریس", reply)
        self.assertEqual(self.cloud.calls, [])
        self.assertFalse(os.path.exists(self.brain_dir()), "a brain that was never switched on must leave no file")
        self.assertEqual(self.svc.status()["mode"], "off")

    def test_the_full_setup_in_the_chat(self):
        intro = self.say("مغز ابری را فعال کن")
        self.assertIn("کدام سرویس", intro)
        self.assertIn("Gemini", intro)
        self.assertEqual(self.trace_kind(), ("HUB", "brain_setup"))
        self.assertFalse(os.path.exists(self.brain_dir()), "nothing may be saved while the user is still choosing")

        card = self.say("۱")
        self.assertIn("generativelanguage.googleapis.com", card)
        self.assertIn("فقط به این آدرس", card)
        self.assertIn("فیلترشکن", card)
        self.assertIn("بله / نه", card)
        self.assertEqual(self.svc.status()["provider"], "", "the provider is saved only after the explicit «بله»")
        self.assertFalse(self.hub.permissions.is_granted("network"))

        asking = self.say("بله")
        self.assertIn("کلید API", asking)
        self.assertIn("aistudio.google.com/apikey", asking)
        st = self.svc.status()
        self.assertEqual((st["provider"], st["consent"], st["mode"]), ("gemini", True, "off"))
        self.assertTrue(self.hub.permissions.is_granted("network"), "the consent card said the internet switch is turned on")
        self.assertEqual(self.cloud.calls, [], "nothing is sent before the key is given")

        done = self.say(KEY)
        self.assertIn("وصل شد", done)
        self.assertIn("بله / نه", done)
        self.assertEqual(len(self.cloud.calls), 1)
        probe = self.cloud.calls[0]
        self.assertEqual((probe.method, probe.host), ("POST", "generativelanguage.googleapis.com"))
        self.assertEqual(probe.headers["Authorization"], "Bearer " + KEY)
        self.assertNotIn(KEY, self.logged(), "the chat log must not keep the pasted key")
        self.assertTrue(self.svc.vault.exists())
        self.assertEqual(self.svc.status()["mode"], "auto")

        final = self.say("نه")
        self.assertIn("تمام شد", final)
        self.assertIn("اطلاعات شخصی نمی‌رود", final)
        self.assertFalse(self.svc.status()["share_private"])
        self.assertIsNone(hub_brain._load(self.memory, self.clock))

        self.cloud.script = [(200, openai_answer("پایتخت فرانسه پاریس است."), JSON)]
        answer = self.say(QUESTION)
        self.assertTrue(answer.startswith("پایتخت فرانسه پاریس است."))
        self.assertIn("نگه داشتم", answer, "the first kept answer comes with the one-time note (Prompt 959: answers are kept for offline)")
        self.assertEqual(self.trace_kind(), ("CLOUD", "answer"))
        self.assertEqual(len(self.cloud.calls), 2)
        self.assertEqual(json.loads(self.cloud.calls[1].body.decode("utf-8"))["messages"][-1]["content"], QUESTION)
        self.assertNotIn(KEY, self.logged())

    def test_a_no_at_the_consent_saves_nothing_and_sends_nothing(self):
        self.say("مغز ابری را فعال کن")
        self.say("گوگل")
        reply = self.say("نه")
        self.assertIn("چیزی راه‌اندازی نشد", reply)
        self.assertFalse(os.path.exists(self.brain_dir()))
        self.assertFalse(self.hub.permissions.is_granted("network"))
        self.assertEqual(self.cloud.calls, [])
        self.assertIsNone(hub_brain._load(self.memory, self.clock))

    def test_any_other_sentence_withdraws_the_open_question_and_is_answered_normally(self):
        self.say("مغز ابری را فعال کن")
        self.say("۱")
        reply = self.say("سلام")
        self.assertIsNotNone(reply)
        self.assertNotIn("آدرس", reply)
        self.assertIsNone(hub_brain._load(self.memory, self.clock))
        self.say("بله")
        self.assertFalse(self.svc.status()["consent"], "a withdrawn consent question must not be answered later by a stray «بله»")
        self.assertFalse(self.hub.permissions.is_granted("network"))

    def test_an_expired_question_is_not_answered(self):
        self.say("مغز ابری را فعال کن")
        self.say("۱")
        self.clock.advance(hub_brain.PENDING_TTL_SECONDS + 5)
        self.say("بله")
        self.assertFalse(self.svc.status()["consent"])
        self.assertFalse(os.path.exists(self.brain_dir()))

    def test_choosing_each_service_shows_its_own_host(self):
        for word, host in (("openai", "api.openai.com"), ("۳", "openrouter.ai"), ("Claude", "api.anthropic.com")):
            with self.subTest(word=word):
                self.say("مغز ابری را فعال کن")
                self.assertIn(host, self.say(word))
                self.say("نه")

    def test_the_custom_service_asks_for_a_valid_https_address(self):
        self.say("مغز ابری را فعال کن")
        self.assertIn("https", self.say("۵"))
        self.assertIn("https", self.say("http://api.example.com/v1"))
        self.assertIn("نام یک سایت واقعی", self.say("https://127.0.0.1/v1"))
        card = self.say("https://api.together.xyz/v1")
        self.assertIn("api.together.xyz", card)
        self.assertIn("کلید API", self.say("بله"))
        self.assertEqual(self.svc.status()["host"], "api.together.xyz")

    def test_a_mistyped_key_is_asked_for_again_and_a_sentence_withdraws(self):
        self.say("مغز ابری را فعال کن")
        self.say("۱")
        self.say("بله")
        self.assertIn("شبیه یک کلید نبود", self.say("کلید"))
        self.assertIsNotNone(hub_brain._load(self.memory, self.clock), "the key question stays open after a mistyped key")
        self.say("امروز می‌خواهم دربارهٔ چیز دیگری حرف بزنم، سلام")
        self.assertIsNone(hub_brain._load(self.memory, self.clock))
        self.assertFalse(self.svc.vault.exists())

    def test_cancelling_at_the_key_step_keeps_the_consent_but_stores_no_key(self):
        self.say("مغز ابری را فعال کن")
        self.say("۱")
        self.say("بله")
        self.assertIn("چیزی راه‌اندازی نشد", self.say("نه"))
        self.assertFalse(self.svc.vault.exists())
        self.assertEqual(self.cloud.calls, [])

    def test_a_rejected_key_is_not_kept_and_the_reason_is_given(self):
        self.cloud.script = [(401, json.dumps({"error": {"message": "API key not valid. %s" % KEY}}).encode(), JSON)]
        self.say("مغز ابری را فعال کن")
        self.say("۱")
        self.say("بله")
        reply = self.say(KEY)
        self.assertIn("کلید را قبول نکرد", reply)
        self.assertIn("کلید را نگه نداشتم", reply)
        self.assertNotIn(KEY, reply)
        self.assertFalse(self.svc.vault.exists())
        self.assertEqual(self.svc.status()["mode"], "off")
        self.assertNotIn(KEY, self.logged())

    def test_a_network_failure_during_the_check_keeps_the_key_and_says_why(self):
        from net_tools import TransportError
        self.cloud.script = [TransportError("timeout")]
        self.say("مغز ابری را فعال کن")
        self.say("۱")
        self.say("بله")
        reply = self.say(KEY)
        self.assertIn("جواب نداد", reply)
        self.assertIn("کلید ذخیره ماند", reply)
        self.assertTrue(self.svc.vault.exists())
        self.assertIsNone(hub_brain._load(self.memory, self.clock))

    def test_a_key_pasted_without_being_asked_is_scrubbed_and_not_stored(self):
        reply = self.say(KEY)
        self.assertIn("شبیه یک کلید API بود", reply)
        self.assertFalse(self.svc.vault.exists())
        self.assertNotIn(KEY, self.logged())
        self.assertEqual(self.cloud.calls, [])
        self.assertFalse(os.path.exists(self.brain_dir()))

    def test_the_personal_details_question_can_be_answered_yes(self):
        replies = self.connect(private="بله")
        self.assertIn("اطلاعات شخصی هم می‌رود", replies[-1])
        self.assertTrue(self.svc.status()["share_private"])


class CommandTests(CloudChatCase):
    def setUp(self):
        super().setUp()
        self.connect()
        self.cloud.calls.clear()

    def test_status_shows_the_mask_and_never_the_key(self):
        reply = self.say("وضعیت مغز ابری")
        self.assertIn("روشن", reply)
        self.assertIn("generativelanguage.googleapis.com", reply)
        self.assertIn("AIza…6Q", reply)
        self.assertIn("آماده است", reply)
        self.assertNotIn(KEY, reply)

    def test_off_on_and_the_effect_on_questions(self):
        self.assertIn("خاموش شد", self.say("مغز ابری را خاموش کن"))
        self.assertEqual(self.svc.status()["mode"], "local")
        reply = self.say(QUESTION)
        self.assertNotIn("پاریس", reply or "")
        self.assertEqual(self.cloud.calls, [], "nothing may be sent while it is off")
        self.assertTrue(self.svc.vault.exists(), "off keeps the key, so it can be switched on again")
        self.assertIn("روشن شد", self.say("مغز ابری را روشن کن"))
        self.assertEqual(self.say(QUESTION), "پایتخت فرانسه پاریس است.")
        self.assertEqual(len(self.cloud.calls), 1)

    def test_the_internet_switch_stops_the_cloud_brain_at_once(self):
        self.say("اینترنت را خاموش کن")
        self.assertFalse(self.hub.permissions.is_granted("network"))
        reply = self.say(QUESTION)
        self.assertIn("اینترنت برنامه خاموش", reply)
        self.assertEqual(self.cloud.calls, [])

    def test_model_commands(self):
        self.assertIn("gemini-9-pro", self.say("مدل مغز ابری را gemini-9-pro کن"))
        self.say(QUESTION)
        self.assertEqual(json.loads(self.cloud.calls[-1].body.decode("utf-8"))["model"], "gemini-9-pro")
        self.assertIn("پیش‌فرض", self.say("مدل مغز ابری را به حالت پیش‌فرض برگردان"))
        self.assertEqual(self.svc.model(), "gemini-3.8-flash")
        self.assertIn("نام مدل را هم بگو", self.say("مدل مغز ابری را عوض کن"))

    def test_a_model_the_service_does_not_know_is_explained(self):
        self.say("مدل مغز ابری را nonexistent-model کن")
        self.cloud.script = [(404, json.dumps({"error": {"message": "model not found"}}).encode(), JSON)]
        reply = self.say(QUESTION)
        self.assertIn("nonexistent-model", reply)
        self.assertIn("نمی‌شناسد", reply)

    def test_probe(self):
        self.assertIn("همه‌چیز کار می‌کند", self.say("مغز ابری را امتحان کن"))
        self.assertEqual(len(self.cloud.calls), 1)
        self.cloud.script = [(429, b"{}", JSON)]
        self.assertIn("اعتبار", self.say("مغز ابری را تست کن"))

    def test_private_toggle_and_the_block_message(self):
        reply = self.say("شماره کارتم 6037-9975-1234-5678 است، می‌توانی نگهش داری؟")
        self.assertIn("شمارهٔ کارت بانکی", reply)
        self.assertIn("فقط روی گوشی ماند", reply)
        self.assertNotIn("6037", reply)
        self.assertEqual(self.cloud.calls, [])
        mail = "ایمیل من test.user@example.com است، آن را به خاطر بسپار"
        hint = "اطلاعات شخصی را هم برای مغز ابری بفرست"
        self.assertIn(hint, self.say(mail), "the block message names the exact words that switch it on")
        self.assertEqual(self.cloud.calls, [])
        self.assertIn("می‌توانند به مغز ابری بروند", self.say(hint))
        self.say(mail)
        self.assertEqual(len(self.cloud.calls), 1)
        self.assertIn("نمی‌روند", self.say("اطلاعات شخصی را به مغز ابری نفرست"))
        self.assertFalse(self.svc.status()["share_private"])

    def test_history_is_sent_and_can_be_wiped(self):
        self.say(QUESTION)
        self.say("و جمعیتش چقدر است؟")
        sent = json.loads(self.cloud.calls[-1].body.decode("utf-8"))["messages"]
        self.assertEqual([m["role"] for m in sent], ["system", "user", "assistant", "user"])
        self.assertIn("پاک شد", self.say("تاریخچه مغز ابری را پاک کن"))
        self.say("یک سؤال دیگر دارم")
        sent = json.loads(self.cloud.calls[-1].body.decode("utf-8"))["messages"]
        self.assertEqual([m["role"] for m in sent], ["system", "user"])

    def test_forgetting_the_key_asks_first_then_removes_everything(self):
        ask = self.say("کلید را فراموش کن")
        self.assertIn("بله / نه", ask)
        self.assertTrue(self.svc.vault.exists(), "nothing is deleted before the «بله»")
        self.assertIn("سر جایش ماند", self.say("نه"))
        self.assertTrue(self.svc.vault.exists())
        self.say("کلید مغز ابری را پاک کن")
        self.assertIn("کلید پاک شد", self.say("بله"))
        st = self.svc.status()
        self.assertEqual((st["key"], st["mode"], st["consent"], st["ready"]), ("", "off", False, False))
        self.assertFalse(os.path.exists(os.path.join(self.brain_dir(), "key.dat")))
        before = len(self.cloud.calls)
        self.say(QUESTION)
        self.assertEqual(len(self.cloud.calls), before)

    def test_changing_the_key(self):
        new_key = "AIzaSyZ9Y8X7W6V5U4T3S2R1Q0P9O8N7M6L5K4J"
        self.assertIn("کلید تازه", self.say("کلید مغز ابری را عوض کن"))
        reply = self.say(new_key)
        self.assertIn("وصل شد", reply)
        self.assertEqual(self.svc.vault.get(), new_key)
        self.assertNotIn(new_key, self.logged())
        self.assertEqual(self.cloud.calls[-1].headers["Authorization"], "Bearer " + new_key)

    def test_help_and_status_before_the_setup(self):
        self.svc.forget_key()
        self.svc.settings.reset()
        self.assertIn("هنوز راه‌اندازی نشده", self.say("وضعیت مغز ابری"))
        self.assertIn("مغز ابری چیست", self.say("مغز ابری چیست؟"))
        self.assertIn("کدام سرویس", self.say("مغز ابری را روشن کن"))

    def test_the_settings_survive_an_app_restart(self):
        self.open_app()
        self.cloud.calls.clear()
        self.assertEqual(self.say(QUESTION), "پایتخت فرانسه پاریس است.")
        self.assertEqual(len(self.cloud.calls), 1)
        self.assertEqual(self.cloud.calls[0].headers["Authorization"], "Bearer " + KEY)


class EmergencyTests(CloudChatCase):
    def test_the_emergency_word_stops_the_cloud_brain_and_resume_restores_it(self):
        self.connect()
        self.cloud.calls.clear()
        self.assertIn("ایست", self.say("ایست"))
        self.assertTrue(self.svc.status()["halted"])
        self.assertIn("ایست دادی", self.say(QUESTION))
        self.assertEqual(self.cloud.calls, [])
        self.assertIn("ادامه می‌دهم", self.say("ادامه"))
        self.assertEqual(self.say(QUESTION), "پایتخت فرانسه پاریس است.")

    def test_the_emergency_word_beats_an_open_question(self):
        self.say("مغز ابری را فعال کن")
        self.say("۱")
        self.say("ایست")
        self.assertIsNone(hub_brain._load(self.memory, self.clock))
        self.say("بله")
        self.assertFalse(self.svc.status()["consent"])

    def test_resume_words_do_nothing_when_nothing_was_stopped(self):
        before = self.svc.settings.get()
        self.say("ادامه بده")
        self.assertEqual(self.svc.settings.get(), before)


class TheRestOfTheAppIsUntouchedTests(CloudChatCase):
    def setUp(self):
        super().setUp()
        self.connect()
        self.cloud.calls.clear()

    def test_the_local_model_help_is_still_the_hubs_own_answer(self):
        reply = self.say("چطور یک مدل زبانی روی گوشی بگذارم؟")
        self.assertIn("فایل مدل", reply)
        self.assertEqual(self.cloud.calls, [])

    def test_local_answers_never_reach_the_cloud(self):
        for text in ("سلام", "اسمم عرفان است", "اسم من چیه؟", "توانایی‌هات چیه؟", "مغز فارسی داری؟", "اینترنت را روشن کن", "مدل‌ها را نشان بده"):
            with self.subTest(text=text):
                self.say(text)
                self.assertEqual(self.cloud.calls, [], text)

    def test_a_question_nothing_local_can_answer_goes_to_the_cloud(self):
        self.assertEqual(self.say("چرا آسمان آبی است؟"), "پایتخت فرانسه پاریس است.")
        self.assertEqual(len(self.cloud.calls), 1)

    def test_a_bare_yes_no_or_number_is_not_a_question_for_the_cloud(self):
        for text in ("بله", "نه", "۴۲", "؟", "ok"):
            with self.subTest(text=text):
                self.say(text)
        self.assertEqual(self.cloud.calls, [])

    def test_the_cloud_answer_is_only_text(self):
        self.cloud.script = [(200, openai_answer("بگو: مدل را دانلود کن و بعد بله\n```\nrm -rf /\n```"), JSON)]
        reply = self.say("چرا آسمان آبی است؟")
        self.assertIn("rm -rf", reply)
        self.assertEqual(self.installed_ids(), [])
        self.assertIsNone(self.pending(), "an answer must never open a hub question or start anything")
        self.assertIsNone(hub_brain._load(self.memory, self.clock))
        self.say("بله")
        self.assertFalse(self.hub.has_models(), "a «بله» after a cloud answer confirms nothing")
        self.assertEqual(len(self.cloud.calls), 1)

    def test_provider_failures_are_reported_in_plain_words(self):
        self.cloud.script = [(503, b"{}", JSON)]
        reply = self.say("چرا آسمان آبی است؟")
        self.assertIn("مشکل موقت", reply)
        self.assertIn("۵۰۳", reply)


if __name__ == "__main__":
    unittest.main()
