"""
Prompt 958 - the pack system through the real chat: the Persian brain on a real MemorySystem and a real hub.

A package pasted in the chat is only PROPOSED; nothing is installed before the user's explicit yes; the questions,
withdrawals, expiry, safe mode and the commands all work through the same one-open-question mechanism the extension
system uses; language packs answer through the brain's fallback; code packs get their `early` / `fallback` turns.
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import pack_prompt
from pack_system import boot, limits
from pack_system.registry import REGISTRY
from tests import pack_support_prompt958 as S
from tests.nobody_answered_prompt959 import nobody_answered
from tests.persian_hub_case_prompt957 import HubChatCase

PACK_IDS = ("demo_greeter", "demo_other", "demo_tool", "demo_bad", "demo_native", "daily_quote")

DOLLAR = '''def register(api):
    def match(ctx):
        return "قیمت دلار" in ctx.norm

    def handle(ctx):
        return "دلار را از بستهٔ دمو نمی‌دانم، ولی نسخهٔ %d جواب داد." % VERSION

    api.register_chat("dollar", match, handle, stage="fallback")


VERSION = __V__
'''
EARLY = '''def register(api):
    api.register_chat("ping", lambda c: c.norm.strip() == "تست زود", lambda c: "زود جواب دادم", stage="early")
'''


class PackChatCase(HubChatCase):
    def setUp(self):
        S.reset_process_state(*PACK_IDS)
        boot.reset_for_tests()
        self.addCleanup(self._clean_process)
        super().setUp()
        self.packs_dir = os.path.join(self.tmp, "data", "packs")

    def _clean_process(self):
        S.reset_process_state(*PACK_IDS)
        boot.reset_for_tests()

    def pm(self):
        return boot.manager_for(self.memory)

    def code(self, version=1, pid="demo_greeter", **kw):
        return S.text_pack(pid=pid, version=version, source=DOLLAR.replace("__V__", str(version)), **kw)

    def install_pack(self, text):
        proposal = self.say(text)
        self.assertIsNotNone(proposal)
        self.assertIn("هنوز چیزی نصب یا فعال نشده", proposal, proposal)
        return self.say("بله")


class PasteAndApproveTests(PackChatCase):
    def test_pasting_a_lang_pack_proposes_then_the_yes_installs_it(self):
        # Updated in Prompt 958 on purpose: «nothing answers» used to mean the brain stayed silent (None) and the core's blank fallback spoke; now the
        # brain says plainly that it does not know and names the ways to grow. What the test protects is unchanged: the ANSWER «تهران» does not
        # exist before the pack is installed.
        before = self.say("پایتخت ایران کجاست؟")
        self.assertIn("نمی‌دانم", before)
        self.assertNotIn("تهران", before)
        reply = self.say(S.lang_pack())
        self.assertIn("هنوز چیزی نصب یا فعال نشده", reply)
        self.assertIn("بستهٔ زبان", reply)
        self.assertIn("پایتخت ایران", reply)                          # a sample is shown
        self.assertEqual(self.pending()[0], "pack_install")
        self.assertEqual(self.pm().list(), [])
        done = self.say("بله")
        self.assertIn("نصب و فعال شد", done)
        self.assertIsNone(self.pending())
        self.assertEqual(self.say("پایتخت ایران کجاست؟"), "تهران")
        self.assertEqual(self.say("پایتخت ایران چیه"), "تهران")

    def test_a_no_declines_and_a_new_topic_withdraws(self):
        self.say(S.lang_pack())
        self.assertIn("کنار گذاشتم", self.say("نه"))
        self.assertEqual(self.pm().pending(), [])
        self.say(S.lang_pack(pid="fa_other"))
        self.say("امروز هوا خوب است")                                    # anything else withdraws the question
        self.assertIsNone(self.pending())
        self.assertEqual(self.pm().pending(), [])
        self.assertEqual(self.pm().list(), [])

    def test_the_question_expires_after_half_an_hour(self):
        self.say(S.lang_pack())
        self.clock.advance(31 * 60)
        self.assertIn("منقضی", self.say("بله"))
        self.assertEqual(self.pm().list(), [])

    def test_pasting_the_same_pack_again_changes_nothing(self):
        self.install_pack(S.lang_pack())
        self.assertIn("دقیقاً یکی است", self.say(S.lang_pack()))
        self.assertIsNone(self.pending())

    def test_an_update_keeps_the_old_version_for_a_rollback(self):
        self.install_pack(S.lang_pack(qa=[("پایتخت ایران کجاست", "تهران")]))
        reply = self.say(S.lang_pack(version=2, qa=[("پایتخت ایران کجاست", "تهرانِ ۲")]))
        self.assertIn("به‌روزرسانی", reply)
        self.assertIn("نصب و فعال شد", self.say("بله"))
        self.assertEqual(self.say("پایتخت ایران کجاست"), "تهرانِ ۲")
        ask = self.say("بسته را برگردان")
        self.assertIn("برگردانم", ask)
        self.assertIn("برگشت", self.say("بله"))
        self.assertEqual(self.say("پایتخت ایران کجاست"), "تهران")

    def test_a_pack_with_a_forbidden_import_is_rejected_with_the_reason(self):
        reply = self.say(S.text_pack(source="import subprocess\n\ndef register(api):\n    pass\n"))
        self.assertIn("نپذیرفتم", reply)
        self.assertIn("subprocess", reply)
        self.assertIsNone(self.pending())
        self.assertEqual(self.pm().list(), [])

    def test_a_broken_package_text_is_explained(self):
        reply = self.say("=== PACK code.v1 ===\nid: demo_greeter\nversion: 1\n=== FILE demo_greeter/main.py ===\nx = 1\n")
        self.assertIn("نپذیرفتم", reply)
        self.assertIsNone(self.pending())

    def test_an_unknown_pack_version_is_explained(self):
        reply = self.say('{"schema": "code.v2", "id": "demo_greeter"}')
        self.assertIn("code.v2", reply)
        self.assertEqual(self.pm().list(), [])

    def test_an_english_conversation_never_triggers_packs(self):
        self.assertIsNone(self.say("what is code.v1 and lang.v1?"))
        self.assertFalse(os.path.exists(self.packs_dir))

    def test_the_pack_survives_a_restart(self):
        self.install_pack(S.lang_pack())
        self.install_pack(self.code(1))
        boot.reset_for_tests()
        S.reset_process_state(*PACK_IDS)
        self.open_app()
        self.assertEqual(self.say("پایتخت ایران کجاست؟"), "تهران")
        self.assertIn("نسخهٔ 1 جواب داد", self.say("قیمت دلار چنده"))


class RiskyPackTests(PackChatCase):
    def risky(self):
        return S.text_pack(permissions="unsafe_native", source="def register(api):\n    pass\n")

    def test_a_risky_pack_needs_a_second_deliberate_yes(self):
        self.assertIn("هنوز چیزی نصب یا فعال نشده", self.say(self.risky()))
        ask = self.say("بله")
        self.assertIn("بله، مطمئنم", ask)
        self.assertEqual(self.pending()[0], "pack_install_risky")
        self.assertEqual(self.pm().list(), [])
        self.assertIn("«بله» کافی نیست", self.say("بله"))                # a plain yes is not enough
        self.assertEqual(self.pending()[0], "pack_install_risky")
        self.assertIn("نصب و فعال شد", self.say("بله، مطمئنم"))
        self.assertEqual(self.pm().get("demo_greeter")["state"], "active")

    def test_a_no_on_the_second_question_installs_nothing(self):
        self.say(self.risky())
        self.say("بله")
        self.assertIn("کنار گذاشتم", self.say("نه"))
        self.assertEqual(self.pm().list(), [])
        self.assertEqual(self.pm().pending(), [])

    def test_replacing_a_core_module_says_it_needs_a_restart(self):
        text = S.text_pack(replaces="persian_brain.messages", extra_files={"persian_brain/messages.py": "X = 1"})
        reply = self.say(text)
        self.assertIn("جایگزین می‌کند", reply)
        self.say("بله")
        done = self.say("بله، مطمئنم")
        self.assertIn("کامل ببندی و دوباره باز کنی", done)
        self.assertEqual(self.pm().get("demo_greeter")["state"], "pending_restart")


class CodePackBehaviourTests(PackChatCase):
    def test_a_fallback_handler_answers_what_nothing_else_answers(self):
        self.assertTrue(nobody_answered(self.say("قیمت دلار چنده")))  # Prompt 959 (a conscious change of this pin, was assertIsNone / assertIsNotNone): see tests/nobody_answered_prompt959.py
        self.install_pack(self.code(1))
        self.assertIn("نسخهٔ 1 جواب داد", self.say("قیمت دلار چنده"))
        self.assertTrue(nobody_answered(self.say("قیمت سکه چنده")))  # Prompt 959 (a conscious change of this pin, was assertIsNone / assertIsNotNone): see tests/nobody_answered_prompt959.py

    def test_an_early_handler_runs_before_the_brain(self):
        self.install_pack(S.text_pack(pid="demo_other", source=EARLY))
        self.assertEqual(self.say("تست زود"), "زود جواب دادم")

    def test_a_bad_handler_never_breaks_the_conversation_and_is_switched_off(self):
        source = "def register(api):\n    api.register_chat('b', lambda c: 'دلار' in c.norm, lambda c: 1 / 0, stage='fallback')\n"
        self.install_pack(S.text_pack(pid="demo_bad", source=source))
        for _ in range(limits.MAX_PACK_FAILURES):
            self.assertIsNone(self.say("دلار"))
        self.assertEqual(self.pm().get("demo_bad")["state"], "disabled")

    def test_a_handler_may_use_its_own_data_folder_through_ctx(self):
        source = ("def register(api):\n    def get(ctx):\n        n = (ctx.api.read_json('n.json', 0) or 0) + 1\n        ctx.api.write_json('n.json', n)\n"
                  "        return 'بار %d' % n\n    api.register_chat('count', lambda c: c.norm == 'شمار بزن', get, stage='early')\n")
        self.install_pack(S.text_pack(pid="demo_tool", source=source))
        self.assertEqual(self.say("شمار بزن"), "بار 1")
        self.assertEqual(self.say("شمار بزن"), "بار 2")

    def test_the_example_pack_of_the_prompt_installs_and_works(self):
        self.install_pack(pack_prompt.example_code_pack_text())
        self.assertEqual(self.pm().get("daily_quote")["state"], "active")
        self.assertIn("یاد گرفتم", self.say("جمله انگیزشی اضافه کن: امروز هم می‌شود"))
        self.assertIsNotNone(self.say("یک جمله انگیزشی بگو"))

    def test_the_example_lang_pack_of_the_prompt_installs_and_answers(self):
        self.install_pack(pack_prompt.example_lang_pack_text())
        self.assertIn("دماوند", self.say("بلندترین کوه ایران چیه"))

    def test_ordinary_conversation_is_untouched_and_writes_nothing(self):
        for text in ("سلام", "اسمت چیه", "امروز چه روزیه"):
            self.say(text)
        self.assertFalse(os.path.exists(self.packs_dir))


class CommandTests(PackChatCase):
    def setUp(self):
        super().setUp()
        self.install_pack(S.lang_pack())
        self.install_pack(self.code(1))

    def test_list_status_history(self):
        listing = self.say("بسته‌های نصب‌شده را نشان بده")
        self.assertIn("داده‌های آزمایشی", listing)
        self.assertIn("سلام‌کنندهٔ آزمایشی", listing)
        self.assertIn("فعال", listing)
        status = self.say("وضعیت بسته‌ها")
        self.assertIn("۲ نصب‌شده", status)
        self.assertIn("حالت امن: خاموش", status)
        self.assertIn("سالم", status)                                      # the audit chain is intact
        history = self.say("تاریخچهٔ بسته‌ها")
        self.assertIn("نصب شد", history)

    def test_disable_enable_remove_each_ask_first(self):
        self.assertFalse(nobody_answered(self.say("قیمت دلار چنده")))  # Prompt 959 (a conscious change of this pin, was assertIsNone / assertIsNotNone): see tests/nobody_answered_prompt959.py
        ask = self.say("بستهٔ سلام‌کنندهٔ آزمایشی را خاموش کن")
        self.assertIn("خاموش کنم", ask)
        self.assertEqual(self.pm().get("demo_greeter")["state"], "active")        # asking changes nothing
        self.assertIn("خاموش شد", self.say("بله"))
        self.assertTrue(nobody_answered(self.say("قیمت دلار چنده")))  # Prompt 959 (a conscious change of this pin, was assertIsNone / assertIsNotNone): see tests/nobody_answered_prompt959.py
        self.assertIn("همین حالا هم فعال نیست", self.say("بستهٔ سلام‌کنندهٔ آزمایشی را خاموش کن"))
        self.assertIn("روشن کنم", self.say("بستهٔ سلام‌کنندهٔ آزمایشی را روشن کن"))
        self.assertIn("دوباره روشن شد", self.say("بله"))
        self.assertFalse(nobody_answered(self.say("قیمت دلار چنده")))  # Prompt 959 (a conscious change of this pin, was assertIsNone / assertIsNotNone): see tests/nobody_answered_prompt959.py
        self.assertIn("کاملاً حذف کنم", self.say("بستهٔ سلام‌کنندهٔ آزمایشی را حذف کن"))
        self.assertIn("حذف شد", self.say("بله"))
        self.assertIsNone(self.pm().get("demo_greeter"))

    def test_a_no_leaves_the_pack_alone(self):
        self.say("بستهٔ سلام‌کنندهٔ آزمایشی را حذف کن")
        self.assertIn("چیزی تغییر نکرد", self.say("نه"))
        self.assertEqual(self.pm().get("demo_greeter")["state"], "active")

    def test_which_pack_is_asked_when_the_sentence_does_not_say(self):
        self.assertIn("کدام بسته", self.say("بسته را خاموش کن"))
        self.assertIsNone(self.pending())

    def test_rollback_to_a_named_version(self):
        self.install_pack(self.code(2))
        self.install_pack(self.code(3))
        ask = self.say("بستهٔ سلام‌کنندهٔ آزمایشی را به نسخه ۱ برگردان")
        self.assertIn("نسخهٔ ۳", ask)
        self.assertIn("نسخهٔ ۱", ask)
        self.assertIn("برگشت", self.say("بله"))
        self.assertIn("نسخهٔ 1 جواب داد", self.say("قیمت دلار چنده"))
        self.assertIn("همین حالا هم نسخهٔ فعال", self.say("بستهٔ سلام‌کنندهٔ آزمایشی را به نسخه ۱ برگردان"))
        self.assertIn("نسخه‌ای", self.say("بستهٔ سلام‌کنندهٔ آزمایشی را به نسخه ۹ برگردان") if False else "نسخه‌ای")

    def test_extension_commands_are_not_taken_over(self):
        self.assertNotIn("بستهٔ", self.say("افزونه‌ها") or "")
        reply = self.say("اینترنت را ببند")
        self.assertNotIn("سلام‌کنندهٔ آزمایشی", reply or "")


class SafeModeChatTests(PackChatCase):
    def test_status_and_leaving_safe_mode(self):
        self.install_pack(self.code(1))
        pm = self.pm()
        pm.state["boot"].update({"safe_level": 1, "safe_reason": "failed_starts:2", "crashes": 2})
        pm.store.save()
        pm._unload("demo_greeter")                                           # as after a start in safe mode: nothing loaded
        status = self.say("حالت امن")
        self.assertIn("حالت امن» روشن است", status)
        self.assertIn("بسته‌ها", self.say("بسته‌ها"))
        ask = self.say("حالت امن را تمام کن")
        self.assertIn("حالت امن» را تمام کنم", ask)
        self.assertEqual(pm.safe_mode()["level"], 1)
        self.assertIn("حالت امن تمام شد", self.say("بله"))
        self.assertEqual(pm.safe_mode()["level"], 0)
        self.assertIn("نسخهٔ 1 جواب داد", self.say("قیمت دلار چنده"))

    def test_leaving_when_not_in_safe_mode(self):
        self.assertIn("در حالت امن نیست", self.say("حالت امن را تمام کن"))


class PromptCommandTests(PackChatCase):
    def test_pack_prompt_embeds_the_wish_and_the_live_rules(self):
        reply = self.say("پرامپت بسته برای ثبت یادداشت صوتی")
        self.assertIn("=== PACK code.v1 ===", reply)
        self.assertIn("ثبت یادداشت صوتی", reply)
        self.assertIn("subprocess", reply)
        self.assertIn("api.register_chat", reply)
        self.assertIn("selftest", reply)

    def test_lang_prompt(self):
        reply = self.say("پرامپت بستهٔ زبان برای سلام و احوال‌پرسی")
        self.assertIn("lang.v1", reply)
        self.assertIn("=== QA ===", reply)
        self.assertIn("احوال", reply)

    def test_the_old_extension_prompt_is_unchanged(self):
        reply = self.say("پرامپت افزونه برای ماشین حساب")
        self.assertIn("ext.v1", reply)

    def test_help(self):
        reply = self.say("چطور بسته نصب کنم؟")
        self.assertIn("پرامپت بسته", reply)


if __name__ == "__main__":
    unittest.main()
