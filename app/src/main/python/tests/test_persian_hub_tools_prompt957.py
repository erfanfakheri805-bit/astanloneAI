"""
Prompt 957 - the web reader, the local-model manager, the capability map and the honest "I cannot do that yet" answers,
all reached through the Persian conversation. Network and downloads are scripted doubles (not a single real socket);
everything else (permission store, model registry, verification pipeline, audit) is the real code on a real MemorySystem.
"""
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import gaps
from brain_hub.service import reset_hub
from persian_brain import activation
from tests import brain_hub_fixtures_prompt957 as F
from tests.persian_hub_case_prompt957 import HubChatCase
from net_tools import TransportError
from net_tools.download import download_message
from net_tools.fetch import message_for

MID = F.MODEL_ID
FALSE_CLAIMS = ("ساختم", "ساخته شد", "نصب شد", "فعال شد", "انجام شد", "یاد گرفتم", "قابل استفاده است")


class Internet(HubChatCase):
    def turn_on(self):
        self.say("اینترنت را روشن کن")
        self.assertIn("اینترنت روشن شد", self.say("بله"))

    def test_the_status_is_truthful_and_sends_nothing(self):
        reply = self.say("وضعیت اینترنت چیست؟")
        self.assertIn("مجوز اینترنتِ برنامه: خاموش", reply)
        self.assertIn("طبق خود دستگاه", reply)
        self.assertIn("آنلاین", reply)
        self.assertIn("آفلاین کار می‌کنند", reply)
        self.assertEqual(self.fetch.requests, [])

    def test_switching_on_is_asked_first_and_declining_keeps_it_off(self):
        ask = self.say("اینترنت را روشن کن")
        self.assertIn("(بله / نه)", ask)
        self.assertFalse(self.hub.permissions.is_granted("network"))
        self.assertIn("چیزی تغییر نکرد", self.say("نه"))
        self.assertFalse(self.hub.permissions.is_granted("network"))

    def test_on_and_off_and_the_switch_survives_a_restart(self):
        self.turn_on()
        self.assertTrue(self.hub.permissions.is_granted("network"))
        self.assertIn("از قبل روشن بود", self.say("اینترنت را روشن کن"))
        self.open_app()
        self.assertIn("روشن (فقط خواندن متن صفحه‌ها با https)", self.say("وضعیت اینترنت"))
        self.assertIn("اینترنت خاموش شد", self.say("اینترنت را خاموش کن"))           # restricting needs no question
        self.assertFalse(self.hub.permissions.is_granted("network"))
        self.open_app()
        self.assertIn("خاموش", self.say("وضعیت اینترنت"))

    def test_reading_a_page_with_the_internet_off_asks_with_the_address_then_reads_after_yes(self):
        reply = self.say("https://example.com/a را ببین")
        self.assertIn("صفحه را نخواندم", reply)
        self.assertIn("بعد از روشن‌شدن همان صفحه را می‌خوانم", reply)
        self.assertEqual(self.fetch.requests, [])
        self.assertEqual(self.pending(), ("net_on", {"url": "https://example.com/a"}))
        done = self.say("بله")
        self.assertIn("اینترنت روشن شد", done)
        self.assertIn("متن صفحه را خواندم", done)
        self.assertIn("متن آزمایشی", done)
        self.assertIn("https://example.com/a", done)
        self.assertEqual([r.url for r in self.fetch.requests], ["https://example.com/a"])

    def test_only_the_visible_text_of_a_page_is_shown_never_scripts(self):
        self.turn_on()
        html = "<html><head><title>t</title><script>evil()</script></head><body><script>alert(1)</script>متن <b>مهم</b><style>.a{}</style></body></html>"
        self.fetch.items = [F.fetch_reply(html)]
        reply = self.say("صفحهٔ https://example.com/s را بخوان")
        self.assertIn("متن مهم", reply)
        for bad in ("evil()", "alert(1)", "<script", "<b>", ".a{}"):
            self.assertNotIn(bad, reply)

    def test_unsafe_addresses_are_refused_and_nothing_is_sent(self):
        self.turn_on()
        cases = (("صفحهٔ http://example.com/b را بخوان", "فقط آدرس‌های امن (https)"),
                 ("صفحهٔ https://localhost/b را بخوان", "برای امنیت بسته شد"),
                 ("صفحهٔ https://192.168.1.1/b را بخوان", "برای امنیت بسته شد"),
                 ("صفحهٔ https://10.0.0.5/b را بخوان", "برای امنیت بسته شد"))
        for sentence, expected in cases:
            with self.subTest(sentence=sentence):
                reply = self.say(sentence)
                self.assertIn(expected, reply)
                self.assertIn("چیزی ذخیره یا اجرا نشد", reply)
        self.assertEqual(self.fetch.requests, [])

    def test_network_failures_are_stated_clearly_and_chat_and_memory_go_on(self):
        self.turn_on()
        for code in ("offline", "timeout", "dns_failure", "tls_error"):
            with self.subTest(code=code):
                self.fetch.items = [TransportError(code, "")]
                reply = self.say("صفحهٔ https://example.com/x را بخوان")
                self.assertIn(message_for(code)[0], reply)
                self.assertIn("چیزی ذخیره یا اجرا نشد", reply)
                self.assertNotIn("متن صفحه را خواندم", reply)
        self.assertIn("سلام", self.say("سلام"))
        self.assertIn("یاد گرفتم", self.say("یاد بگیر که پایتون یک زبان برنامه‌نویسی است"))
        self.assertIn("زبان", self.say("پایتون چیست؟"))

    def test_with_the_internet_off_the_reader_sends_nothing_and_offline_chat_works(self):
        self.say("صفحهٔ https://example.com/a را بخوان")
        self.say("نه")
        self.assertEqual(self.fetch.requests, [])
        self.assertIn("سلام", self.say("سلام"))

    def test_an_oversized_page_is_cut_and_said_so(self):
        self.turn_on()
        self.fetch.items = [F.fetch_reply("x " * 400_000, ctype="text/plain")]
        reply = self.say("صفحهٔ https://example.com/big را بخوان")
        self.assertIn("متن صفحه را خواندم", reply)
        self.assertLess(len(reply), 4000)                               # a chat message, not the whole body


class Models(HubChatCase):
    def card_message(self, **over):
        return json.dumps(F.model_card(**over), ensure_ascii=False)

    def turn_on(self):
        self.say("اینترنت را روشن کن")
        self.say("بله")

    def usable_model(self):
        self.turn_on()
        self.say(self.card_message())
        self.say("مدل %s را دانلود کن" % MID)
        return self.say("بله")

    def test_a_card_registers_but_downloads_nothing_and_is_not_usable(self):
        reply = self.say(self.card_message())
        self.assertIn("ثبت شد", reply)
        self.assertIn("هنوز هیچ فایلی دریافت نشده و مدل قابل استفاده نیست", reply)
        self.assertEqual(self.stream.requests, [])
        self.assertFalse(self.hub.model_status(MID).usable)
        self.assertIn("هنوز قابل استفاده نیست", self.say("مدل‌ها را نشان بده"))
        self.assertFalse(self.hub.ask_model(MID, "سلام").ok)             # a model that is not usable generates nothing

    def test_an_invalid_card_is_refused_and_registers_nothing(self):
        reply = self.say('{"model_id": "x", "sha256": "zz"}')
        self.assertIn("معتبر نیست و ثبت نشد", reply)
        self.assertEqual(self.hub.list_models(), [])

    def test_download_is_asked_first_and_also_needs_the_internet_switch(self):
        self.say(self.card_message())
        ask = self.say("مدل %s را دانلود کن" % MID)
        self.assertIn("دانلود شود؟ (بله / نه)", ask)
        self.assertIn("مجوز اینترنت برنامه خاموش است", ask)
        self.assertEqual(self.stream.requests, [])
        reply = self.say("بله")
        self.assertIn("دانلود انجام نشد", reply)
        self.assertIn("اجازهٔ دسترسی به اینترنت داده نشده", reply)
        self.assertIn("چیزی قابل استفاده نشد", reply)
        self.assertEqual(self.stream.requests, [])
        self.assertFalse(self.hub.model_status(MID).usable)

    def test_a_verified_download_becomes_usable_only_after_the_whole_pipeline(self):
        reply = self.usable_model()
        for stage in ("صحت فایل (اندازه و SHA-256): گذشت", "سازگاری با موتورهای موجود: گذشت", "بارگذاری در موتور: گذشت",
                      "آزمون استنتاج واقعی: گذشت", "همهٔ مراحل را گذراند و قابل استفاده است"):
            self.assertIn(stage, reply)
        self.assertEqual(len(self.stream.requests), 1)
        status = self.hub.model_status(MID)
        self.assertEqual((status.state, status.usable), ("usable", True))
        result = self.hub.ask_model(MID, "سلام")
        self.assertTrue(result.ok)
        self.assertTrue(result.text)

    def test_a_file_with_the_wrong_hash_is_rejected_and_never_usable(self):
        self.turn_on()
        self.stream.data = F.MODEL_BYTES[:-5] + b"abcde"                 # same size, different content
        self.say(self.card_message())
        self.say("مدل %s را دانلود کن" % MID)
        reply = self.say("بله")
        self.assertIn("هش فایل دانلودشده با مقدار مورد انتظار نمی‌خواند", reply)
        self.assertIn(download_message("hash_mismatch")[0], reply)
        self.assertIn("چیزی قابل استفاده نشد", reply)
        self.assertNotIn("قابل استفاده است", reply)
        status = self.hub.model_status(MID)
        self.assertFalse(status.usable)
        self.assertFalse(self.hub.ask_model(MID, "سلام").ok)
        self.assertFalse(os.path.isfile(self.hub._model_manager().model_path(MID)))      # nothing unverified stays on disk
        self.stream.data = F.MODEL_BYTES                                  # a retry with the real file works from scratch
        self.say("مدل %s را دانلود کن" % MID)
        self.assertIn("همهٔ مراحل را گذراند", self.say("بله"))

    def test_a_licence_that_needs_review_is_acknowledged_separately_and_downloads_nothing(self):
        self.say(self.card_message(model_id="gpl-ngram", license="gpl-3.0"))
        ask = self.say("مدل gpl-ngram را دانلود کن")
        self.assertIn("نیاز به بازبینی دارد", ask)
        self.assertEqual(self.stream.requests, [])
        done = self.say("بله")
        self.assertIn("تأیید مجوز ثبت شد", done)
        self.assertIn("دانلود باز هم تأیید جدا می‌خواهد", done)
        self.assertEqual(self.stream.requests, [])                        # acknowledging a licence is not a download
        self.assertTrue(self.hub.model_status("gpl-ngram").license_ack)
        self.assertIn("الان سؤال بازی ندارم", self.say("بله"))           # and a second yes is not a hidden download request
        self.assertEqual(self.stream.requests, [])
        self.turn_on()
        self.say("مدل gpl-ngram را دانلود کن")
        self.assertIn("همهٔ مراحل را گذراند", self.say("بله"))

    def test_a_restricted_licence_is_never_downloaded(self):
        reply = self.say(self.card_message(model_id="nc-ngram", license="cc-by-nc-4.0"))
        self.assertIn("با این مجوز دانلود انجام نمی‌شود", reply)
        again = self.say("مدل nc-ngram را دانلود کن")
        self.assertIn("دانلود انجام نمی‌شود", again)
        self.assertIsNone(self.pending())
        self.assertEqual(self.stream.requests, [])

    def test_removal_is_asked_first(self):
        self.usable_model()
        ask = self.say("مدل %s را حذف کن" % MID)
        self.assertIn("حذف شود؟ (فایل و ثبتش پاک می‌شود.) (بله / نه)", ask)
        self.assertTrue(self.hub.model_status(MID).usable)
        self.assertIn("از ثبت و از حافظه حذف شد", self.say("بله"))
        self.assertEqual(self.hub.model_status(MID).state, "unregistered")
        self.assertFalse(self.hub.ask_model(MID, "سلام").ok)

    def test_usable_survives_a_restart_only_while_the_file_is_unchanged(self):
        self.usable_model()
        self.open_app()
        self.assertIn("قابل استفاده", self.say("مدل‌ها را نشان بده"))
        self.assertTrue(self.hub.model_status(MID).usable)
        path = self.hub._model_manager().model_path(MID)
        self.close_app()
        with open(path, "ab") as handle:
            handle.write(b" ")                                           # the file changed behind the app's back
        self.open_app()
        self.assertFalse(self.hub.model_status(MID).usable)
        self.assertFalse(self.hub.ask_model(MID, "سلام").ok)


class Gaps(HubChatCase):
    def test_every_known_wish_gets_an_honest_explanation(self):
        for gap in gaps.GAPS:
            for example in gap.examples_fa:
                with self.subTest(gap=gap.gap_id, example=example):
                    reply = self.say(example)
                    self.assertTrue(reply)
                    for claim in FALSE_CLAIMS:
                        self.assertNotIn(claim, reply)
                    if "جارویس" not in example or "ساعت" in example:
                        self.assertIn("هنوز نمی‌توانم", reply)

    def test_the_explanation_says_what_exists_what_is_missing_and_the_next_step(self):
        reply = self.say("برام یک ویدیو بساز")
        for part in ("این را هنوز نمی‌توانم انجام بدهم", "آنچه واقعاً هست", "آنچه کم است", "قدم بعدی"):
            self.assertIn(part, reply)
        self.assertIn("پرامپت افزونه", reply)

    def test_the_last_wish_is_remembered_for_the_extension_prompt(self):
        self.say("یک اپلیکیشن بساز که قیمت دلار را نشان بدهد")
        prompt = self.say("پرامپت افزونه بده")
        self.assertIn("درخواست من: یک اپلیکیشن بساز که قیمت دلار را نشان بدهد", prompt)
        self.assertIn("درخواستی که قبلاً گفتی", prompt)
        self.assertIn("ext.v1", prompt)
        self.assertIn("بدون «بله»ی تو چیزی فعال نمی‌شود", prompt)
        explicit = self.say("پرامپت افزونه برای تبدیل تاریخ")
        self.assertIn("درخواست من: تبدیل تاریخ", explicit)
        self.assertNotIn("درخواستی که قبلاً گفتی", explicit)

    def test_a_wish_the_app_explains_is_remembered_as_well(self):
        self.say("برام یک ویدیو بساز")
        prompt = self.say("پرامپت افزونه بده")
        self.assertIn("درخواست من: برام یک ویدیو بساز", prompt)
        self.assertIn("درخواستی که قبلاً گفتی", prompt)

    def test_the_prompt_without_any_wish_still_works(self):
        prompt = self.say("پرامپت افزونه بده")
        self.assertIn("ext.v1", prompt)
        self.assertNotIn("درخواستی که قبلاً گفتی", prompt)

    def test_an_unsupported_build_keeps_the_old_answer_and_adds_the_way_forward(self):
        reply = self.say("یک اپلیکیشن بساز که قیمت دلار را نشان بدهد")
        self.assertIn("نمی‌توانم", reply)
        self.assertIn("برنامه‌نویس", reply)
        self.assertIn("پرامپت افزونه", reply)
        for claim in FALSE_CLAIMS:
            self.assertNotIn(claim, reply)

    def test_the_capability_map_separates_usable_from_missing_and_lists_new_extensions(self):
        before = self.say("نقشهٔ قابلیت‌ها را نشان بده")
        self.assertIn("از وضعیت واقعی همین لحظه", before)
        self.assertIn("نیازمند چیزی که اینجا نیست", before)
        self.assertIn("ساخت تصویر و نقاشی — نیازمند چیزی که اینجا نیست", before)
        usable_before = [line for line in before.splitlines() if line.startswith("قابل استفاده الان")][0]
        self.assertNotIn("تبدیل تاریخ میلادی به شمسی", usable_before)
        self.install(F.jalali_pkg())
        after = self.say("نقشهٔ قابلیت‌ها را نشان بده")
        usable_after = [line for line in after.splitlines() if line.startswith("قابل استفاده الان")][0]
        self.assertIn("تبدیل تاریخ میلادی به شمسی", usable_after)
        self.assertNotIn("ساخت تصویر", usable_after)                       # a wish never becomes «usable» by being listed

    def test_a_disabled_extension_leaves_the_usable_list(self):
        self.install(F.jalali_pkg())
        self.say("افزونه را غیرفعال کن")
        self.say("بله")
        text = self.say("نقشهٔ قابلیت‌ها را نشان بده")
        usable = [line for line in text.splitlines() if line.startswith("قابل استفاده الان")][0]
        self.assertNotIn("تبدیل تاریخ میلادی به شمسی", usable)

    def test_the_android_status_says_nothing_was_tested_on_a_real_device(self):
        text = self.say("وضعیت اندروید")
        self.assertIn("هیچ‌کدام روی دستگاه واقعی آزموده نشده", text)
        self.assertIn("برنامه هیچ مجوز حساسی را خودش نمی‌گیرد", text)
        self.assertEqual(self.hub._bridge.request_calls, [])               # asking for the status asks for nothing

    def test_the_help_explains_the_honest_limits(self):
        text = self.say("چطور افزونه اضافه کنم؟")
        self.assertIn("پرامپت افزونه", text)
        self.assertIn("بله", text)
        self.assertIn("محدودیت صادقانه", text)
        self.assertIn("APK جدید", text)


class OutsideTheFullScope(HubChatCase):
    scope = activation.SCOPE_CAPABILITIES

    def test_no_hub_behaviour_exists_outside_the_application_scope(self):
        self.paste(F.jalali_pkg())
        self.assertNotEqual(self.trace_kind()[0], "HUB")
        self.assertEqual(self.installed_ids(), [])
        self.assertIsNone(self.pending())
        self.say("افزونه‌ها را لیست کن")
        self.assertNotEqual(self.trace_kind()[0], "HUB")
        self.assertNotIn("آنچه واقعاً هست", self.say("برام یک ویدیو بساز") or "")


class HubUnavailable(HubChatCase):
    def setUp(self):
        super().setUp()
        reset_hub(self.memory)
        self.memory.db_path = ""                                        # a memory without any storage path

    def test_replies_say_so_and_the_conversation_goes_on(self):
        for text in (self.say("افزونه‌ها را لیست کن"), self.paste(F.jalali_pkg()), self.say("اینترنت را روشن کن"),
                     self.say("مدل‌ها را نشان بده")):
            self.assertIn("مسیر ذخیره‌سازی برنامه مشخص نیست", text)
            self.assertNotIn("نصب و فعال شد", text)
        self.assertIn("سلام", self.say("سلام"))
        self.assertIn("هنوز نمی‌توانم", self.say("برام یک ویدیو بساز"))


if __name__ == "__main__":
    unittest.main()
