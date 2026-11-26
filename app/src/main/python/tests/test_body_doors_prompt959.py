"""
Prompt 959 (stage B, the body): the one-time-code finder and the three doors only the app itself has - the foreground service
(`BodyDoor`), the phone facts (`PhoneDoor`) and the SMS-code reader (`SmsDoor`).

Everything runs against `FakeBodyJava` (tests/body_support_prompt959.py), a hand-written fake of the Android classes. These tests prove
the doors' LOGIC - what they call, what they refuse, what they report and what they never return - not that Android behaves like the fake.
"""

import json
import random
import time
import unittest

from native_bridge import body, facade, otp
from native_bridge.body import BodyDoor, PhoneDoor, SmsDoor
from native_bridge.jvm import NullJava
from native_bridge.result import DoorPermissionError
from pack_system import intake, limits, manifest
from pack_system.errors import PackError
from tests import pack_support_prompt958 as S
from tests.body_support_prompt959 import NOW, FakeBodyJava, SecurityException
from tests.test_native_bridge_prompt958 import FakeHub


def ms(seconds_ago, now=NOW):
    return int((now - seconds_ago) * 1000)


# ============================================================================ the one-time code finder
class OtpFinderTests(unittest.TestCase):
    CODES = (
        ("کد تایید شما: 48291", "48291"),
        ("کد تأیید ورود به حساب: ۴۸۲۹۱۳", "482913"),
        ("کد ورود شما ٣٨٤٩٢١ است. آن را به کسی نگویید.", "384921"),
        ("Your verification code is 482913", "482913"),
        ("G-482913 is your Google verification code", "482913"),
        ("Use 628419 as your login code", "628419"),
        ("Your OTP is 4921. Do not share it.", "4921"),
        ("<#> Your code: 3849 abc", "3849"),
        ("رمز پویا: 12345678", "12345678"),
        ("رمز یکبار مصرف شما 5678 است. مبلغ 2500000 ریال", "5678"),
        ("بانک: رمز دوم پویا 7340218 مبلغ 150000 ریال", "7340218"),
        ("123 456 is your code", "123456"),
        ("کد فعال‌سازی: 99317", "99317"),
        ("‎کد:‏ ‎۸۸۱۲۳۴", "881234"),
        ("PIN: 0042", "0042"),
        ("کد 1111 2222", "1111"),                      # two numbers: the one nearest to the word wins
        ("رمز یکبار مصرف خرید با کارت شما: 123456", "123456"),   # «کارت» in the middle does not make it a card number
        ("کد تایید بانک ملی ایران: 654321", "654321"),         # «ملی» is a bank here, not the national code
        ("کد تحویل سفارش شما: 4417", "4417"),
    )
    NOT_CODES = (
        "مبلغ 2500000 ریال از حساب شما برداشت شد",
        "کد پیگیری شما 123456789012 است",
        "کد ملی 0012345678",
        "کد پیگیری: 483921",
        "کد رهگیری مرسوله 4839211",
        "کد ملی 12345678 شما ثبت شد",
        "شماره حساب 1234567 کد",
        "کد پستی 1234567 را وارد کنید",
        "تاریخ 1403/09/20 کد",
        "ساعت 14:35 کد",
        "موجودی 5000 USD. Code: none",
        "کد تخفیف شما: SALE2024",
        "شماره تماس 09121234567 کد",
        "your balance is 4500 rial. code of conduct",
        "سلام، فردا ساعت ۸ می‌بینمت",
        "یک پیام ساده بدون عدد و بدون کلمهٔ کلیدی",
        "123456 بدونِ هیچ کلمه‌ای کنارش",
        "",
    )

    def test_real_looking_messages_give_their_code(self):
        for text, want in self.CODES:
            self.assertEqual(otp.extract_code(text), want, text)

    def test_things_that_are_not_codes_give_nothing(self):
        for text in self.NOT_CODES:
            self.assertEqual(otp.extract_code(text), "", text)

    def test_the_code_is_always_four_to_eight_ascii_digits(self):
        for text, _ in self.CODES:
            code = otp.extract_code(text)
            self.assertTrue(code.isascii() and code.isdigit())
            self.assertTrue(otp.MIN_DIGITS <= len(code) <= otp.MAX_DIGITS)
        self.assertEqual((otp.MIN_DIGITS, otp.MAX_DIGITS), (4, 8))

    def test_normalize_turns_every_digit_system_into_latin_digits_and_drops_direction_marks(self):
        self.assertEqual(otp.normalize("۰۱۲۳۴۵۶۷۸۹ ٠١٢٣٤٥٦٧٨٩"), "0123456789 0123456789")
        self.assertEqual(otp.normalize("a‎b‏c‮d⁦e﻿"), "abcde")
        self.assertEqual(otp.normalize(None), "")
        self.assertEqual(otp.normalize(12345), "12345")

    def test_find_code_says_where_it_is(self):
        text = "کد تایید شما: ۴۸۲۹۱۳ است"
        code, start, end = otp.find_code(text)
        self.assertEqual(code, "482913")
        self.assertEqual(otp.normalize(text)[start:end], "482913")
        self.assertEqual(otp.find_code("hello"), ("", -1, -1))

    def test_redact_hides_the_code_and_only_the_code(self):
        out = otp.redact("کد تایید شما: ۴۸۲۹۱۳ است. مبلغ 2500000 ریال")
        self.assertNotIn("482913", out)
        self.assertIn("••••••", out)
        self.assertIn("2500000", out)
        self.assertEqual(len(out), len(otp.normalize("کد تایید شما: ۴۸۲۹۱۳ است. مبلغ 2500000 ریال")))
        self.assertEqual(otp.redact("بدون کد"), "بدون کد")
        self.assertEqual(otp.redact("سلام ۱۲۳"), "سلام 123")

    def test_the_gap_limits_are_enforced(self):
        self.assertEqual((otp.MAX_AFTER, otp.MAX_BEFORE), (45, 25))            # the numbers themselves are part of the contract
        self.assertEqual(otp.extract_code("کد " + "x" * 40 + " 482913"), "482913")
        self.assertEqual(otp.extract_code("کد " + "x" * 50 + " 482913"), "")
        far = "کد " + "x" * (otp.MAX_AFTER + 5) + " 482913"
        self.assertEqual(otp.extract_code(far), "")
        near = "کد " + "x" * 10 + " 482913"
        self.assertEqual(otp.extract_code(near), "482913")
        far_before = "482913 " + "x" * (otp.MAX_BEFORE + 5) + " code"
        self.assertEqual(otp.extract_code(far_before), "")

    def test_it_never_raises_and_never_returns_a_bad_code_on_noise(self):
        rng = random.Random(959)
        pieces = ["کد", "رمز", "code", "otp", "۱۲۳۴", "56789", "1403/09/20", "12:30", "ریال", "مبلغ", " ", ":", "-", "‎", "x", "9",
                  "پیگیری", "123 456", "0912", "1.5", ".", "،"]
        for _ in range(3000):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 14)))
            code, start, end = otp.find_code(text)
            self.assertEqual(code, otp.extract_code(text))
            if code:
                self.assertTrue(code.isascii() and code.isdigit() and 4 <= len(code) <= 8, text)
                self.assertEqual(otp.redact(text)[start:end], "•" * (end - start), text)
            else:
                self.assertEqual((start, end, otp.redact(text)), (-1, -1, otp.normalize(text)), text)


# ============================================================================ BodyDoor (the foreground service)
class BodyDoorTests(unittest.TestCase):
    def setUp(self):
        self.jvm = FakeBodyJava()
        self.door = BodyDoor(self.jvm)

    def test_hold_starts_the_service_with_clean_texts(self):
        r = self.door.hold("  دانلودِ مغز  ", "۴۰٪\n   از ۱ گیگابایت", 40)
        self.assertEqual((r.ok, r.code, r.data), (True, "ok", {"running": True}))
        self.assertEqual(self.jvm.service_calls, [("hold", "دانلودِ مغز", "۴۰٪ از ۱ گیگابایت", 40)])

    def test_texts_are_cut_to_their_limits(self):
        self.door.hold("ع" * 500, "م" * 500, -1)
        _, title, text, percent = self.jvm.service_calls[0]
        self.assertEqual((len(title), len(text), percent), (body.MAX_TITLE, body.MAX_TEXT, -1))

    def test_bad_arguments_never_reach_android(self):
        for args in (("", "x", 5), ("   ", "x", 5), (None, "x", 5), ("t", "x", -2), ("t", "x", 101), ("t", "x", "5"), ("t", "x", 5.5),
                     ("t", "x", True), ("t", "x", None)):
            r = self.door.hold(*args)
            self.assertEqual((r.ok, r.code), (False, "bad_arguments"), args)
        self.assertEqual(self.jvm.service_calls, [])

    def test_the_percent_edges_are_accepted(self):
        for percent in (-1, 0, 100):
            self.assertTrue(self.door.hold("t", "x", percent).ok, percent)

    def test_android_refusing_the_service_is_reported_not_hidden(self):
        jvm = FakeBodyJava(service_allowed=False)
        r = BodyDoor(jvm).hold("t", "x", 1)
        self.assertEqual((r.ok, r.code), (False, "not_allowed"))
        self.assertFalse(BodyDoor(jvm).running().data["running"])

    def test_release_and_running(self):
        self.assertFalse(self.door.running().data["running"])
        self.door.hold("t")
        self.assertTrue(self.door.running().data["running"])
        r = self.door.release()
        self.assertEqual((r.ok, r.data), (True, {"running": False}))
        self.assertFalse(self.door.running().data["running"])
        self.assertEqual(self.jvm.service_calls[-1], ("release",))

    def test_an_apk_without_the_service_says_so(self):
        jvm = FakeBodyJava(features=("file_chooser",))
        for call in (lambda d: d.hold("t"), lambda d: d.release(), lambda d: d.running()):
            r = call(BodyDoor(jvm))
            self.assertEqual((r.ok, r.code, r.needs), (False, "native_feature_missing", body.FEATURE_SERVICE))
        self.assertEqual(jvm.service_calls, [])

    def test_a_missing_java_class_is_a_missing_feature(self):
        jvm = FakeBodyJava()
        del jvm.classes[body.SERVICE_CLASS]
        r = BodyDoor(jvm).hold("t")
        self.assertEqual((r.ok, r.code), (False, "native_feature_missing"))

    def test_off_android_it_is_unavailable(self):
        for call in (lambda d: d.hold("t"), lambda d: d.release(), lambda d: d.running()):
            self.assertEqual(call(BodyDoor(NullJava())).code, "unavailable_platform")

    def test_a_java_exception_becomes_a_result(self):
        class IllegalStateException(Exception):
            pass

        def boom(ctx, title, text, percent):
            raise IllegalStateException("x")
        self.jvm.classes[body.SERVICE_CLASS].hold = staticmethod(boom)
        r = self.door.hold("t")
        self.assertEqual((r.ok, r.code), (False, "java_error"))
        self.assertIn("IllegalStateException", r.detail_fa)


# ============================================================================ PhoneDoor
class PhoneDoorTests(unittest.TestCase):
    def test_battery_optimization(self):
        r = PhoneDoor(FakeBodyJava()).battery_optimization()
        self.assertEqual((r.ok, r.data), (True, {"ignoring": False, "power_save": False}))
        r = PhoneDoor(FakeBodyJava(ignoring=True, power_save=True)).battery_optimization()
        self.assertEqual(r.data, {"ignoring": True, "power_save": True})

    def test_a_missing_power_service_is_a_clear_error(self):
        jvm = FakeBodyJava()
        jvm.ctx.getSystemService = lambda name: None
        self.assertEqual(PhoneDoor(jvm).battery_optimization().code, "java_error")
        self.assertEqual(PhoneDoor(jvm).memory().code, "java_error")

    def test_app_info_on_a_modern_phone(self):
        r = PhoneDoor(FakeBodyJava(version=("0.2.0", 2), sdk=34)).app_info()
        self.assertTrue(r.ok)
        self.assertEqual(r.data, {"package": "com.erfan.standaloneai", "version_name": "0.2.0", "version_code": 2,
                                  "abis": ["arm64-v8a", "armeabi-v7a"], "sdk": 34})

    def test_app_info_on_an_old_phone_uses_the_old_version_field(self):
        jvm = FakeBodyJava(version=("0.1.9", 7), sdk=26)
        jvm.ctx.getPackageManager = lambda: type("PM", (), {"getPackageInfo": lambda self, p, f: type(
            "Info", (), {"versionName": "0.1.9", "versionCode": 7, "getLongVersionCode": lambda self: 9999})()})()
        r = PhoneDoor(jvm).app_info()
        self.assertEqual((r.data["version_code"], r.data["sdk"]), (7, 26))

    def test_memory(self):
        r = PhoneDoor(FakeBodyJava(memory=(8_000_000_000, 3_000_000_000, False))).memory()
        self.assertEqual((r.ok, r.data), (True, {"total": 8_000_000_000, "available": 3_000_000_000, "low": False}))
        self.assertTrue(PhoneDoor(FakeBodyJava(memory=(4_000_000_000, 100_000_000, True))).memory().data["low"])

    def test_off_android(self):
        for name in ("battery_optimization", "app_info", "memory"):
            self.assertEqual(getattr(PhoneDoor(NullJava()), name)().code, "unavailable_platform", name)


# ============================================================================ SmsDoor
class SmsDoorTests(unittest.TestCase):
    GOOGLE = "G-482913 is your Google verification code"
    BANK = "مبلغ 2500000 ریال از حساب شما برداشت شد. مانده 1250000 ریال"

    def jvm(self, sms, granted=True, **kw):
        permissions = ("android.permission.POST_NOTIFICATIONS", body.READ_SMS) if granted else ("android.permission.POST_NOTIFICATIONS",)
        return FakeBodyJava(sms=sms, granted=permissions, **kw)

    def door(self, jvm):
        return SmsDoor(jvm, clock=lambda: NOW)

    def test_the_newest_message_with_a_code_wins(self):
        jvm = self.jvm([("Bank", self.BANK, ms(60)), ("Google", self.GOOGLE, ms(120)), ("Mom", "ok", ms(300))])
        r = self.door(jvm).latest_code()
        self.assertEqual((r.ok, r.code), (True, "ok"))
        self.assertEqual(r.data, {"code": "482913", "sender": "Google", "age_seconds": 120, "looked_at": 2})

    def test_the_message_text_is_never_returned(self):
        jvm = self.jvm([("Bank", self.BANK, ms(60)), ("Google", self.GOOGLE, ms(120))])
        flat = json.dumps(self.door(jvm).latest_code().to_dict(), ensure_ascii=False)
        for secret in ("Google verification", "is your", self.BANK, "برداشت", "1250000", "2500000"):
            self.assertNotIn(secret, flat)
        self.assertEqual(sorted(json.loads(flat)["data"]), ["age_seconds", "code", "looked_at", "sender"])

    def test_only_the_documented_columns_are_read_newest_first(self):
        jvm = self.jvm([("Google", self.GOOGLE, ms(5))])
        self.door(jvm).latest_code()
        self.assertEqual(len(jvm.queries), 1)
        uri, columns, selection, args, order = jvm.queries[0]
        self.assertEqual((uri, columns, selection, args, order), (body.SMS_URI, ["address", "body", "date"], None, None, "date DESC"))

    def test_without_the_permission_nothing_is_read(self):
        jvm = self.jvm([("Google", self.GOOGLE, ms(5))], granted=False)
        r = self.door(jvm).latest_code()
        self.assertEqual((r.ok, r.code, r.needs), (False, "permission_denied", body.READ_SMS))
        self.assertEqual(jvm.queries, [])
        self.assertFalse(self.door(jvm).has_permission().data["granted"])
        self.assertTrue(self.door(self.jvm([])).has_permission().data["granted"])

    def test_the_permission_request_shows_androids_own_dialog_for_exactly_one_permission(self):
        jvm = self.jvm([], granted=False)
        r = self.door(jvm).request_permission()
        self.assertEqual((r.ok, r.code, r.data), (True, "ok", {"granted": False, "dispatched": True}))
        self.assertEqual(jvm.permission_requests, [[body.READ_SMS]])          # the one permission and nothing else
        self.assertEqual(jvm.queries, [])                                     # asking never reads anything

    def test_a_permission_that_is_given_already_is_not_asked_again(self):
        jvm = self.jvm([])
        r = self.door(jvm).request_permission()
        self.assertEqual((r.ok, r.data), (True, {"granted": True, "dispatched": False}))
        self.assertEqual(jvm.permission_requests, [])

    def test_a_dialog_that_could_not_be_shown_is_reported_not_pretended(self):
        jvm = self.jvm([], granted=False, dialog_allowed=False)
        r = self.door(jvm).request_permission()
        self.assertEqual((r.ok, r.code), (False, "not_allowed"))
        self.assertEqual(jvm.permission_requests, [[body.READ_SMS]])

    def test_the_permission_request_outside_the_app_says_so(self):
        r = SmsDoor(NullJava(), clock=lambda: NOW).request_permission()
        self.assertEqual((r.ok, r.code), (False, "unavailable_platform"))

    def test_android_refusing_a_granted_read_is_still_a_clean_result(self):
        jvm = self.jvm([("Google", self.GOOGLE, ms(5))])

        class Refusing:
            def query(self, *args):
                raise SecurityException("READ_SMS")
        jvm.ctx.getContentResolver = lambda: Refusing()
        r = self.door(jvm).latest_code()
        self.assertEqual((r.ok, r.code), (False, "permission_denied"))

    def test_a_message_older_than_the_limit_is_not_used(self):
        jvm = self.jvm([("Google", self.GOOGLE, ms(16 * 60))])
        r = self.door(jvm).latest_code(max_age_minutes=15)
        self.assertEqual((r.ok, r.code), (False, "empty"))
        self.assertTrue(self.door(jvm).latest_code(max_age_minutes=20).ok)
        self.assertEqual(self.door(self.jvm([("G", self.GOOGLE, ms(90))])).latest_code(max_age_minutes=1).code, "empty")
        self.assertTrue(self.door(self.jvm([("G", self.GOOGLE, ms(59))])).latest_code(max_age_minutes=1).ok)

    def test_it_stops_at_the_first_too_old_message(self):
        jvm = self.jvm([("A", "hello", ms(30 * 60)), ("B", self.GOOGLE, ms(31 * 60))])
        r = self.door(jvm).latest_code(max_age_minutes=15)
        self.assertEqual((r.code, r.data), ("empty", {"looked_at": 1}))

    def test_only_the_newest_few_are_looked_at(self):
        rows = [("S%d" % i, "no code here %d" % i, ms(10 + i)) for i in range(body.LOOK_AT + 4)]
        rows.insert(body.LOOK_AT + 1, ("Late", self.GOOGLE, ms(20)))
        jvm = self.jvm(rows)
        r = self.door(jvm).latest_code()
        self.assertEqual((r.code, r.data), ("empty", {"looked_at": body.LOOK_AT}))
        self.assertEqual(jvm.last_cursor.at, body.LOOK_AT - 1)
        self.assertEqual(body.LOOK_AT, 8)

    def test_the_cursor_is_always_closed(self):
        for rows in ([("G", self.GOOGLE, ms(5))], [("A", "no code", ms(5))], [], [("A", "x", "not-a-number")]):
            jvm = self.jvm(rows)
            self.door(jvm).latest_code()
            self.assertTrue(jvm.last_cursor.closed, rows)

    def test_a_broken_row_is_a_java_error_not_a_crash(self):
        r = self.door(self.jvm([("A", "x", "not-a-number")])).latest_code()
        self.assertEqual((r.ok, r.code), (False, "java_error"))

    def test_null_columns_and_future_dates(self):
        jvm = self.jvm([("A", None, ms(5)), (None, self.GOOGLE, ms(-500))])
        r = self.door(jvm).latest_code()
        self.assertEqual((r.ok, r.data["code"], r.data["sender"], r.data["age_seconds"]), (True, "482913", "", 0))

    def test_a_long_sender_is_cut(self):
        r = self.door(self.jvm([("x" * 100, self.GOOGLE, ms(5))])).latest_code()
        self.assertEqual(len(r.data["sender"]), 40)

    def test_the_age_limit_must_be_a_sane_whole_number(self):
        door = self.door(self.jvm([("G", self.GOOGLE, ms(5))]))
        for bad in (0, -1, body.MAX_AGE_MINUTES + 1, "15", 1.5, None, True):
            self.assertEqual(door.latest_code(max_age_minutes=bad).code, "bad_arguments", bad)
        self.assertTrue(door.latest_code(max_age_minutes=body.MAX_AGE_MINUTES).ok)

    def test_an_empty_inbox_and_an_unreadable_inbox(self):
        self.assertEqual(self.door(self.jvm([])).latest_code().code, "empty")
        jvm = self.jvm([])
        jvm.ctx.getContentResolver = lambda: type("R", (), {"query": lambda self, *a: None})()
        self.assertEqual(self.door(jvm).latest_code().code, "unavailable")

    def test_an_apk_or_platform_without_sms(self):
        self.assertEqual(self.door(NullJava()).latest_code().code, "unavailable_platform")

    def test_the_real_clock_is_the_default(self):
        jvm = self.jvm([("G", self.GOOGLE, int((time.time() - 45) * 1000))])
        r = SmsDoor(jvm).latest_code()
        self.assertTrue(r.ok)
        self.assertTrue(40 <= r.data["age_seconds"] <= 60)


# ============================================================================ the doors behind the facade
class FacadeBodyTests(unittest.TestCase):
    def setUp(self):
        facade.reset_for_tests()
        self.addCleanup(facade.reset_for_tests)
        self.hub = FakeHub()
        self.jvm = FakeBodyJava(sms=[("Google", SmsDoorTests.GOOGLE, int((time.time() - 30) * 1000))],
                                granted=("android.permission.POST_NOTIFICATIONS", body.READ_SMS))

    def app(self, clock=None):
        kwargs = {"clock": clock} if clock else {}
        return facade.for_app(self.hub, jvm=self.jvm, **kwargs)

    def test_the_app_has_the_three_doors_and_still_not_the_raw_jvm(self):
        app = self.app()
        self.assertEqual(app.permissions, frozenset({"android", "clipboard", "screen", "body", "phone", "sms"}))
        self.assertTrue(app.sms.latest_code().ok)
        self.assertTrue(app.phone.memory().ok)
        self.assertTrue(app.body.hold("t", "x", 3).ok)
        with self.assertRaises(DoorPermissionError):
            app.jvm

    def test_a_pack_can_never_have_them(self):
        pack = facade.for_pack("demo_pack", limits.PERMISSIONS, self.hub)
        for name in ("body", "phone", "sms"):
            with self.assertRaises(DoorPermissionError, msg=name):
                getattr(pack, name)
        for name in ("body", "phone", "sms"):
            self.assertNotIn(name, limits.PERMISSIONS)
            with self.assertRaises(PackError, msg=name):
                schema, raw = intake.find_pack_in_text(S.text_pack(permissions="network, %s" % name))
                manifest.normalize(raw)

    def test_only_public_methods_are_reachable(self):
        sms = self.app().sms
        for attr in ("_clock", "_jvm", "_run", "_door"):
            with self.assertRaises(AttributeError, msg=attr):
                getattr(sms, attr)
        self.assertTrue(callable(sms.latest_code) and callable(sms.has_permission))

    def test_the_code_reader_is_audited_without_the_code_and_the_progress_pings_are_not(self):
        app = self.app()
        app.body.hold("t", "x", 3)
        app.body.running()
        app.phone.memory()
        app.phone.app_info()
        app.phone.battery_optimization()
        app.sms.has_permission()
        self.assertEqual(self.hub.entries, [])
        self.assertTrue(app.sms.latest_code().ok)
        app.body.release()
        self.assertEqual([e[0] for e in self.hub.entries], ["native.sms", "native.body"])
        self.assertEqual([e[2]["action"] for e in self.hub.entries], ["latest_code", "release"])
        flat = json.dumps(self.hub.entries, ensure_ascii=False)
        for secret in ("482913", "Google", "verification"):
            self.assertNotIn(secret, flat)

    def test_the_sms_door_is_rate_limited_so_it_cannot_be_used_as_a_spy(self):
        now = [5000.0]
        app = self.app(clock=lambda: now[0])
        calls, seconds = facade.RATE_LIMITS["sms"]
        self.assertEqual((calls, seconds), (6, 600))
        for _ in range(calls):
            self.assertTrue(app.sms.latest_code().ok)
        queried = len(self.jvm.queries)
        r = app.sms.latest_code()
        self.assertEqual((r.ok, r.code), (False, "rate_limited"))
        self.assertEqual(len(self.jvm.queries), queried)            # a refused call never touched the inbox
        now[0] += seconds + 1
        self.assertTrue(app.sms.latest_code().ok)

    def test_the_door_limits_match_what_the_code_expects(self):
        for name in ("body", "phone", "sms"):
            self.assertIn(name, facade.RATE_LIMITS)
        self.assertGreaterEqual(facade.RATE_LIMITS["body"][0], 900)       # a download reports progress for hours
        self.assertLessEqual(facade.RATE_LIMITS["sms"][0], 10)


if __name__ == "__main__":
    unittest.main()
