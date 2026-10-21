"""
Prompt 957 - what happens to an installed extension AFTER it was installed, all through the Persian chat: switching it
off and on, taking permissions away and giving them back, the app's internet switch that a network extension also
needs, the way the hub's open question and the dialogue's open question never mix, and a damaged extension store that is
reported and repaired only after an explicit yes. Real MemorySystem + HubService; scripted network.
"""
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from persian_brain.dialogue import Dialogue
from tests import brain_hub_fixtures_prompt957 as F
from tests.persian_hub_case_prompt957 import HubChatCase

JALALI_QUESTION = "تاریخ شمسی ۲۰۲۴ ۳ ۲۰"
JALALI_V1 = "۲۰۲۴/۳/۲۰ میلادی = ۱۴۰۳/۱/۱ شمسی"
TEACH = "پایتون یک زبان برنامه‌نویسی است"


class Switches(HubChatCase):
    def state(self, cid="jalali_date"):
        return self.hub.extension(cid)["state"]

    def test_disable_is_asked_first_then_the_extension_stops_and_says_why(self):
        self.install(F.jalali_pkg())
        ask = self.say("افزونه را غیرفعال کن")
        self.assertIn("غیرفعال شود؟", ask)
        self.assertEqual(self.state(), "active")                           # not before the yes
        done = self.say("بله")
        self.assertIn("غیرفعال شد", done)
        self.assertIn("نسخه‌ها و تاریخچه‌اش حفظ شده", done)
        self.assertEqual(self.state(), "disabled")
        reply = self.say(JALALI_QUESTION)
        self.assertIn("غیرفعال است", reply)
        self.assertNotIn("میلادی =", reply)
        self.assertEqual(self.trace_kind(), ("HUB", "extension"))
        self.assertIn("غیرفعال", self.say("افزونه‌ها را لیست کن"))

    def test_a_question_that_is_not_answered_changes_nothing(self):
        self.install(F.jalali_pkg())
        self.say("افزونه را غیرفعال کن")
        self.assertIn(JALALI_V1, self.say(JALALI_QUESTION))                 # another message withdraws the question
        self.assertNotIn("غیرفعال شد", self.say("بله") or "")
        self.assertEqual(self.state(), "active")

    def test_declining_keeps_the_extension_active(self):
        self.install(F.jalali_pkg())
        self.say("افزونه را غیرفعال کن")
        self.assertIn("چیزی تغییر نکرد", self.say("نه"))
        self.assertEqual(self.state(), "active")

    def test_enable_is_asked_first_and_the_extension_is_rechecked(self):
        self.install(F.jalali_pkg())
        self.say("افزونه را غیرفعال کن")
        self.say("بله")
        ask = self.say("افزونه را فعال کن")
        self.assertIn("دوباره فعال شود؟", ask)
        self.assertIn("یکپارچگی و آزمون‌هایش دوباره بررسی", ask)
        self.assertEqual(self.state(), "disabled")                         # not before the yes
        self.assertIn("دوباره فعال شد", self.say("بله"))
        self.assertEqual(self.state(), "active")
        self.assertIn(JALALI_V1, self.say(JALALI_QUESTION))

    def test_a_disabled_extension_stays_disabled_after_a_restart(self):
        self.install(F.jalali_pkg())
        self.say("افزونه را غیرفعال کن")
        self.say("بله")
        self.open_app()
        self.assertEqual(self.state(), "disabled")
        self.assertIn("غیرفعال است", self.say(JALALI_QUESTION))

    def test_switching_to_the_state_it_already_has_asks_nothing(self):
        self.install(F.jalali_pkg())
        self.assertIn("همین حالا هم فعال است", self.say("افزونه را فعال کن"))
        self.assertIsNone(self.pending())

    def test_a_trigger_sentence_that_is_part_of_a_longer_sentence_does_not_fire_the_extension(self):
        self.install(F.jalali_pkg())
        self.say("لطفاً درباره تاریخ شمسی ۲۰۲۴ ۳ ۲۰ و تاریخچهٔ تقویم‌ها برایم توضیح بده")
        self.assertNotEqual(self.trace_kind(), ("HUB", "extension"))

    def test_an_english_trigger_works_although_the_brain_itself_is_persian(self):
        self.install(F.jalali_pkg(triggers=["convert date {gy} {gm} {gd}"]))
        self.assertIn("۱۴۰۳/۱/۱ شمسی", self.say("convert date 2024 3 20"))


class Permissions(HubChatCase):
    def test_a_clock_extension_runs_with_the_granted_permission(self):
        reply = self.install(F.clock_pkg())
        self.assertIn("مجوزهای داده‌شده به این افزونه: ساعت دستگاه", reply)
        answer = self.say("ساعت دستگاه")
        self.assertIn("ساعت ۲۲:۱۳ (UTC)", answer)                              # the injected clock: 1_700_000_000 s
        self.assertIn("افزونهٔ «ساعت دستگاه»", answer)

    def test_taking_a_permission_away_is_immediate_and_blocks_the_extension(self):
        self.install(F.clock_pkg())
        done = self.say("مجوز ساعت را از افزونه ساعت دستگاه بگیر")
        self.assertIn("گرفته شد", done)
        self.assertIn("تا وقتی دوباره ندهی، این افزونه اجرا نمی‌شود", done)
        blocked = self.say("ساعت دستگاه")
        self.assertIn("اجرا نشد", blocked)
        self.assertIn("مجوز ساعت دستگاه ندارد", blocked)
        self.assertNotIn("UTC", blocked)
        listing = self.say("افزونه‌ها را لیست کن")
        self.assertIn("منتظر مجوز", listing)

    def test_giving_a_permission_back_is_asked_first(self):
        self.install(F.clock_pkg())
        self.say("مجوز ساعت را از افزونه ساعت دستگاه بگیر")
        ask = self.say("به افزونه ساعت دستگاه اجازهٔ ساعت بده")
        self.assertIn("داده شود؟", ask)
        self.assertEqual(self.hub.invoke_extension("clock_reader", {})["status"], "blocked_permission")   # not before the yes
        self.assertIn("داده شد", self.say("بله"))
        self.assertIn("UTC", self.say("ساعت دستگاه"))

    def test_the_permission_overview_is_persian_and_truthful(self):
        self.install(F.clock_pkg())
        text = self.say("مجوزها را نشان بده")
        self.assertIn("دسترسی به اینترنت — خاموش", text)
        self.assertIn("«ساعت دستگاه»: ساعت دستگاه (داده‌شده)", text)
        self.assertNotIn("clock", text)
        self.assertIn("وضعیت اندروید", text)

    def test_a_network_extension_also_needs_the_apps_own_internet_switch(self):
        review = self.paste(F.words_pkg())
        self.assertIn("مجوز اینترنت خود برنامه هم باید روشن باشد (الان خاموش است)", review)
        self.say("بله")
        asked = self.say("کلمات صفحه https://a.test/")
        self.assertIn("اینترنت برنامه الان خاموش است", asked)
        self.assertNotIn("نتیجه", asked)
        self.assertEqual(self.pending()[0], "net_on")                       # the one honest next step is offered
        self.assertEqual(self.fetch.requests, [])                           # and not a single request left the app
        self.assertIn("اینترنت روشن شد", self.say("بله"))
        answer = self.say("کلمات صفحه https://a.test/")
        self.assertIn("نتیجه: ۲", answer)
        self.assertEqual([r.url for r in self.fetch.requests], ["https://a.test/"])
        self.assertIn("اینترنت خاموش شد", self.say("اینترنت را خاموش کن"))
        again = self.say("کلمات صفحه https://a.test/")
        self.assertIn("جوابی ندارم", again)
        self.assertEqual(len(self.fetch.requests), 1)                       # switched off: nothing was sent


    def test_an_address_typed_with_trailing_punctuation_is_read_without_it(self):
        self.say("اینترنت را روشن کن")
        self.say("بله")
        self.paste(F.words_pkg())
        self.say("بله")
        for tail in (".", "؟", "،", ")"):
            self.fetch.requests.clear()
            reply = self.say("کلمات صفحه https://a.test/page%s" % tail)
            self.assertIn("نتیجه: ۲", reply)
            self.assertEqual([r.url for r in self.fetch.requests], ["https://a.test/page"])


class DialogueInterplay(HubChatCase):
    def dialogue_pending(self):
        return Dialogue(self.memory, self.clock).load().pending

    def test_a_package_withdraws_an_open_dialogue_question(self):
        self.assertIn("(بله / نه)", self.say(TEACH))
        self.assertIsNotNone(self.dialogue_pending())
        self.paste(F.jalali_pkg())
        self.assertIsNone(self.dialogue_pending())
        reply = self.say("بله")
        self.assertIn("نصب و فعال شد", reply)
        self.assertNotIn("یاد گرفتم", reply)                                 # the yes belonged to the hub's question only

    def test_a_dialogue_question_withdraws_the_hubs_question(self):
        self.install(F.jalali_pkg())
        self.say("افزونه را غیرفعال کن")
        self.assertEqual(self.pending()[0], "disable")
        self.assertIn("(بله / نه)", self.say(TEACH))
        self.assertIsNone(self.pending())
        self.assertIn("یاد گرفتم", self.say("بله"))
        self.assertEqual(self.hub.extension("jalali_date")["state"], "active")       # the yes did not disable it

    def test_a_hub_command_is_a_new_topic_for_the_dialogue(self):
        self.say(TEACH)
        self.assertIn("افزونه", self.say("افزونه‌ها را لیست کن"))
        self.assertIsNone(self.dialogue_pending())
        self.assertNotIn("یاد گرفتم", self.say("بله") or "")


class DamagedStore(HubChatCase):
    def ext_path(self, *parts):
        return os.path.join(self.hub_root, "extensions", *parts)

    def damage(self):
        self.close_app()
        with open(self.ext_path("hub.db"), "wb") as handle:
            handle.write(b"this is not a database" * 50)
        self.open_app()

    def test_a_damaged_store_is_reported_and_set_aside_only_after_a_yes(self):
        self.install(F.jalali_pkg())
        self.damage()
        reply = self.say("افزونه‌ها را لیست کن")
        self.assertIn("حافظهٔ افزونه‌ها خراب است", reply)
        self.assertIn("چیزی پاک نمی‌شود", reply)
        self.assertEqual(self.pending(), ("repair_store", {}))
        self.assertTrue(os.path.isfile(self.ext_path("hub.db")))            # untouched before the yes
        done = self.say("بله")
        self.assertIn("کنار گذاشته شد (چیزی پاک نشد)", done)
        names = os.listdir(self.ext_path())
        self.assertTrue(any(n.startswith("hub.db.corrupt.") for n in names), names)
        self.assertTrue(os.path.isfile(self.ext_path("modules.corrupt.1", "jalali_date_v1.py")))      # kept, not deleted
        self.assertIn("هنوز افزونه‌ای نصب نکرده‌ام", self.say("افزونه‌ها را لیست کن"))
        self.install(F.jalali_pkg())                                            # a fresh store works again
        self.assertIn(JALALI_V1, self.say(JALALI_QUESTION))

    def test_a_package_pasted_into_a_damaged_store_is_never_installed(self):
        self.install(F.jalali_pkg())
        self.damage()
        ask = self.paste(F.factors_pkg())
        self.assertIn("حافظهٔ افزونه‌ها خراب است", ask)
        self.assertNotIn("نصب و فعال شد", ask)
        self.assertEqual(self.pending()[0], "repair_store")
        self.assertIn("چیزی تغییر نکرد", self.say("نه"))
        self.assertEqual(self.hub.extension_store_state(), "damaged")
        self.assertEqual(self.hub.extensions(), [])

    def test_nothing_runs_from_a_damaged_store_and_the_chat_goes_on(self):
        self.install(F.jalali_pkg())
        self.damage()
        reply = self.say(JALALI_QUESTION)
        self.assertNotIn("میلادی =", reply or "")
        self.assertIn("سلام", self.say("سلام"))

    def test_repair_of_a_healthy_or_unused_store_changes_nothing(self):
        self.assertIn("هنوز ساخته نشده", self.say("حافظهٔ افزونه‌ها را ترمیم کن"))
        self.install(F.jalali_pkg())
        self.assertIn("سالم است", self.say("حافظهٔ افزونه‌ها را ترمیم کن"))
        self.assertIsNone(self.pending())
        self.assertFalse(any("corrupt" in n for n in os.listdir(self.ext_path())))
        self.assertIn(JALALI_V1, self.say(JALALI_QUESTION))


if __name__ == "__main__":
    unittest.main()
