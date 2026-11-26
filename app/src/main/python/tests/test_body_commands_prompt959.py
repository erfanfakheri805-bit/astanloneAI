"""
Prompt 959 (stage B, the body) - the Persian commands of the BODY, as a pure classifier (no app, no phone).

A sentence is a body command only when it carries one of the body's own nouns next to an action word. The tests pin three things: what IS a body
command (and its slots), what is NOT (a question, a general sentence, the commands of the other parts), and that every sentence the app's own
replies tell the user to say is understood by the classifier (so a reply can never promise a command that does not work).
"""
import os
import re
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from persian_brain import hub_body_commands as BC
from persian_brain import hub_messages_body as HB
from persian_brain import hub_ownbrain_commands as OC
from persian_brain import normalization as nz
from self_builder import fa_text


def classify(sentence):
    norm = nz.normalize(sentence)
    return BC.classify(sentence, norm, fa_text.words(norm))


def own(sentence):
    norm = nz.normalize(sentence)
    return OC.classify(sentence, norm, fa_text.words(norm))


class PositiveTests(unittest.TestCase):
    CASES = (
        ("گزارش آزمایشی", BC.SELFTEST, {"copy": False}),
        ("گزارش آزمایشی را کپی کن", BC.SELFTEST, {"copy": True}),
        ("یه گزارش فنی بده", BC.SELFTEST, {"copy": False}),
        ("خودآزمایی", BC.SELFTEST, {"copy": False}),
        ("تست سلامت برنامه", BC.SELFTEST, {"copy": False}),
        ("چک‌لیست دسترسی‌ها", BC.ACCESS, {}),
        ("چک لیست تنظیمات گوشی", BC.ACCESS, {}),
        ("تنظیمات گوشی برای کار در پس‌زمینه", BC.ACCESS, {}),
        ("چرا دانلود قطع می‌شود؟", BC.ACCESS, {}),
        ("چرا دانلود قطع میشه", BC.ACCESS, {}),
        ("چرا برنامه خودش بسته می‌شود؟", BC.ACCESS, {}),
        ("صفحهٔ باتری را باز کن", BC.OPEN, {"target": "battery"}),
        ("تنظیمات باتری رو باز کن", BC.OPEN, {"target": "battery"}),
        ("تنظیمات برنامه را باز کن", BC.OPEN, {"target": "app"}),
        ("تنظیمات اعلان را باز کن", BC.OPEN, {"target": "notifications"}),
        ("صفحهٔ نوتیفیکیشن را نشان بده", BC.OPEN, {"target": "notifications"}),
        ("کد پیامک را بخوان", BC.SMS, {"minutes": 15}),
        ("کد اس ام اس رو بخون", BC.SMS, {"minutes": 15}),
        ("کد تایید پیامک را بگو", BC.SMS, {"minutes": 15}),
        ("کدی که برام اومد چیه؟", BC.SMS, {"minutes": 15}),
        ("کد پیامک ۲۰ دقیقه اخیر را بخوان", BC.SMS, {"minutes": 20}),
        ("کد پیامک یک ساعت اخیر را بخوان", BC.SMS, {"minutes": 60}),
        ("کد پیامک ۵۰۰ دقیقه اخیر را بخوان", BC.SMS, {"minutes": BC.MAX_MINUTES}),
        ("مجوز پیامک را بده", BC.SMS_PERMISSION, {}),
        ("اجازهٔ پیامک را فعال کن", BC.SMS_PERMISSION, {}),
    )

    def test_each_sentence_is_the_expected_command(self):
        for sentence, kind, slots in self.CASES:
            with self.subTest(sentence):
                command = classify(sentence)
                self.assertIsNotNone(command, sentence)
                self.assertEqual(command.kind, kind)
                self.assertEqual(command.slots, slots)

    def test_the_kinds_are_the_five_the_chat_handles(self):
        self.assertEqual(BC.KINDS, ("selftest", "access", "open", "sms", "sms_permission"))
        self.assertEqual({kind for _s, kind, _slots in self.CASES}, set(BC.KINDS), "every kind has a positive sentence")


class NegativeTests(unittest.TestCase):
    NOT_BODY = (
        "کد تایید چیه؟",                              # a question about what such a code is
        "رمز وای‌فای را بگو",
        "رمز عبورم را فراموش کردم",
        "کدی که برام نوشتی رو بخون",                    # a code the assistant wrote, not an SMS
        "کدی که اومده کار نمیکنه",
        "پیامک را بخوان",                              # an SMS, but no code: the body never reads messages
        "پیام های من را بخوان",
        "پیامک بفرست",
        "یک برنامه بساز",
        "دانلود مغز را متوقف کن",                       # the own brain's command
        "وضعیت مغز",
        "تنظیمات دسترسی‌پذیری را باز کن",               # the hub's accessibility command
        "باتری چقدر مونده؟",
        "سلام",
        "",
        "گزارش بده",                                   # no kind of report
        "گزارش مالی بده",
        "یه کد پایتون بنویس",
        "چرا آسمان آبی است؟",
        "این برنامه چه کار می‌کند؟",
    )

    def test_these_are_never_body_commands(self):
        for sentence in self.NOT_BODY:
            with self.subTest(sentence):
                self.assertIsNone(classify(sentence), sentence)

    def test_a_long_sentence_is_never_a_body_command(self):
        padded = "کد پیامک را بخوان " + "بله " * 20
        self.assertIsNone(classify(padded))
        self.assertIsNone(classify("گزارش آزمایشی " + "ا" * (BC.MAX_CHARS + 1)))

    def test_a_non_string_or_empty_input_is_none(self):
        self.assertIsNone(BC.classify(None, "", []))
        self.assertIsNone(BC.classify("", "", []))


class OtherPartsKeepTheirOwnTests(unittest.TestCase):
    """The body goes before the own brain in the chat; these sentences must still reach the own brain's classifier."""

    def test_the_own_brain_still_gets_its_commands(self):
        self.assertEqual(own("دانلود مغز را متوقف کن").kind, OC.PAUSE)
        self.assertEqual(own("وضعیت مغز").kind, OC.STATUS)

    def test_a_why_question_about_a_download_never_stops_or_continues_it(self):
        for sentence in ("چرا دانلود قطع میشه؟", "چرا دانلود مغز متوقف شد؟", "چرا دانلود نمیشه", "چرا دانلود تموم نمیشه"):
            with self.subTest(sentence):
                command = own(sentence)
                self.assertTrue(command is None or command.kind == OC.STATUS, "%s -> %r" % (sentence, command))

    def test_the_order_to_stop_a_download_is_still_the_order(self):
        for sentence in ("دانلود را متوقف کن", "دانلود را قطع کن", "دانلود مغز را متوقف کن"):
            with self.subTest(sentence):
                self.assertEqual(own(sentence).kind, OC.PAUSE)


class WhatTheRepliesSayTests(unittest.TestCase):
    """Every sentence in «…» that an app reply tells the user to say is either a body command that the classifier understands, or is listed
    here as something that is NOT a command (a label on a button or a setting). A new quote forces a decision."""

    NOT_COMMANDS = frozenset((
        "بدون محدودیت", "صرفه‌جوییِ باتری", "شروع خودکار", "قفل", "اخیر", "اجازه", "پیامک", "اجازهٔ تنظیماتِ محدودشده", "Allow restricted settings",
        "در حال گرفتنِ مغز", "ایست", "کپی", "مجوز", "سبک", "قوی", "چسباندن",
    ))

    def quotes(self, text):
        return re.findall(r"«([^»]+)»", text)

    def replies(self):
        for battery in ({"known": False}, {"known": True, "ignoring": False, "power_save": False}, {"known": True, "ignoring": True, "power_save": True}):
            for notifications in ("", "granted", "denied", "not_declared"):
                for sms in ("granted", "denied", "unknown"):
                    yield HB.access_checklist({"battery": battery, "notifications": notifications, "sms": sms})
        yield HB.sms_need_permission()
        yield HB.sms_permission_have()
        yield HB.sms_permission_shown()
        yield HB.sms_empty(15)
        yield HB.sms_empty(120)
        yield HB.sms_code({"code": "123456", "sender": "x", "age_seconds": 5})
        yield HB.sms_code({"code": "123456", "sender": "x", "age_seconds": 5}, scrubbed=False)
        for code in ("permission_denied", "rate_limited", "not_allowed", "unavailable_platform", "native_feature_missing", "error", "weird"):
            yield HB.sms_failed(code)
        for kind in ("battery", "app", "notifications"):
            yield HB.opened(kind)
            for code in ("unavailable_platform", "rate_limited", "error"):
                yield HB.open_failed(code, kind)
        yield HB.copied(True, "")
        yield HB.copied(False, "unavailable_platform")
        yield HB.emergency_extra(["engine"], True)
        yield HB.selftest_hint()
        yield HB.selftest({})

    def test_every_quoted_sentence_is_understood_or_is_a_known_label(self):
        seen = set()
        for reply in self.replies():
            for quote in self.quotes(reply):
                seen.add(quote)
                if classify(quote) is None:
                    self.assertIn(quote, self.NOT_COMMANDS, "«%s» is quoted in a reply but is neither a body command nor a listed label" % quote)
        for sentence in (HB.SELFTEST_ASK, HB.SELFTEST_COPY, HB.ACCESS_ASK, HB.OPEN_BATTERY, HB.OPEN_APP, HB.OPEN_NOTIFICATIONS, HB.SMS_ASK, HB.SMS_PERMISSION):
            self.assertIn(sentence, seen, "«%s» is a command of the body but no reply tells the user about it" % sentence)

    def test_the_constants_are_the_kinds_they_name(self):
        expected = {HB.SELFTEST_ASK: BC.SELFTEST, HB.SELFTEST_COPY: BC.SELFTEST, HB.ACCESS_ASK: BC.ACCESS, HB.SMS_ASK: BC.SMS,
                    HB.SMS_PERMISSION: BC.SMS_PERMISSION}
        for sentence, kind in expected.items():
            self.assertEqual(classify(sentence).kind, kind, sentence)
        self.assertEqual(classify(HB.SELFTEST_COPY).slots, {"copy": True})
        self.assertEqual([classify(s).slots["target"] for s in (HB.OPEN_BATTERY, HB.OPEN_APP, HB.OPEN_NOTIFICATIONS)],
                         ["battery", "app", "notifications"])


if __name__ == "__main__":
    unittest.main()
