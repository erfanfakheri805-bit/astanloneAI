"""
Prompt 957 - the hub's open question (`hub_state`), the hub command classifier (`hub_intents`) and the honesty of the
hub messages (`hub_messages`, `hub_messages_tools`).

* the open question is validated on load, expires, never raises and is never written when there is nothing to write;
* the classifier takes over ONLY sentences that carry a hub noun next to an action word; a table of 200+ ordinary
  sentences of the existing brain (greetings, capability commands, facts, ...) is never taken over;
* a message may say "installed / active / usable" only when the result it was given says so.
"""
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from persian_brain import hub_intents as HI
from persian_brain import hub_messages as HM
from persian_brain import hub_messages_tools as HT
from persian_brain import hub_state
from persian_brain import normalization as nz
from self_builder import fa_text
from tests.test_persian_brain_final_exit001 import INTENT_TABLE


class KV:
    """The key-value part of MemorySystem."""

    def __init__(self):
        self.d, self.writes, self.fail_read, self.fail_write = {}, 0, False, False

    def get_state(self, key, default=None):
        if self.fail_read:
            raise RuntimeError("read")
        return self.d.get(key, default)

    def set_state(self, key, value):
        if self.fail_write:
            raise RuntimeError("write")
        self.writes += 1
        self.d[key] = value


class Clock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


INSTALL = {"proposal_id": "pabc1234ef", "capability_id": "bmi_calc", "title": "BMI", "action": "create", "planned_version": 1}


class OpenQuestion(unittest.TestCase):
    def setUp(self):
        self.kv, self.clock = KV(), Clock()

    def test_round_trip_of_every_type(self):
        cases = {"install": INSTALL, "rollback": {"capability_id": "bmi_calc", "title": "x", "to_version": 1},
                 "disable": {"capability_id": "bmi_calc", "title": "x"}, "enable": {"capability_id": "bmi_calc", "title": "x"},
                 "perm_grant": {"capability_id": "bmi_calc", "title": "x", "permission": "network"}, "net_on": {},
                 "model_download": {"model_id": "fa-ngram"}, "model_license": {"model_id": "fa-ngram"},
                 "model_remove": {"model_id": "fa-ngram"}, "repair_store": {}}
        self.assertEqual(set(cases), set(hub_state.PENDING_TYPES))
        for type_, data in cases.items():
            with self.subTest(type_):
                self.assertTrue(hub_state.save(self.kv, type_, data, self.clock))
                self.assertEqual(hub_state.load(self.kv, self.clock), (type_, data))

    def test_only_one_question_is_open_and_a_new_one_replaces_it(self):
        hub_state.save(self.kv, "net_on", {}, self.clock)
        hub_state.save(self.kv, "repair_store", {}, self.clock)
        self.assertEqual(hub_state.load(self.kv, self.clock), ("repair_store", {}))

    def test_it_expires_after_thirty_minutes(self):
        hub_state.save(self.kv, "net_on", {}, self.clock)
        self.clock.t += hub_state.PENDING_TTL_SECONDS - 1
        self.assertIsNotNone(hub_state.load(self.kv, self.clock))
        self.clock.t += 2
        self.assertIsNone(hub_state.load(self.kv, self.clock))

    def test_lapsed_reports_only_an_intact_question_that_ran_out_of_time(self):
        hub_state.save(self.kv, "install", INSTALL, self.clock)
        self.assertIsNone(hub_state.lapsed(self.kv, self.clock))                    # still open: not lapsed
        self.clock.t += hub_state.PENDING_TTL_SECONDS - 1
        self.assertIsNone(hub_state.lapsed(self.kv, self.clock))
        self.clock.t += 2
        self.assertEqual(hub_state.lapsed(self.kv, self.clock), ("install", INSTALL))
        self.assertIsNone(hub_state.load(self.kv, self.clock))
        hub_state.clear(self.kv)
        self.assertIsNone(hub_state.lapsed(self.kv, self.clock))                    # cleared: nothing to report

    def test_lapsed_ignores_damaged_values_and_never_raises(self):
        key = hub_state.PENDING_KEY
        old = self.clock() - hub_state.PENDING_TTL_SECONDS - 10
        for value in (None, "x", [], {"type": "nope", "ts": old, "data": {}}, {"type": "install", "ts": "old", "data": INSTALL},
                      {"type": "install", "ts": True, "data": INSTALL}, {"type": "install", "ts": old, "data": dict(INSTALL, proposal_id="../x")}):
            with self.subTest(value=value):
                self.kv.d[key] = value
                self.assertIsNone(hub_state.lapsed(self.kv, self.clock))
        self.kv.fail_read = True
        self.assertIsNone(hub_state.lapsed(self.kv, self.clock))

    def test_a_value_from_the_future_is_ignored(self):
        hub_state.save(self.kv, "net_on", {}, self.clock)
        self.clock.t -= 3600
        self.assertIsNone(hub_state.load(self.kv, self.clock))

    def test_damaged_or_foreign_values_are_ignored(self):
        key = hub_state.PENDING_KEY
        bad = [None, "x", 5, [], {}, {"type": "install"}, {"type": "nope", "ts": self.clock(), "data": {}},
               {"type": "install", "ts": "now", "data": INSTALL}, {"type": "install", "ts": True, "data": INSTALL},
               {"type": "install", "ts": self.clock(), "data": dict(INSTALL, proposal_id="../../x")},
               {"type": "install", "ts": self.clock(), "data": dict(INSTALL, action="delete")},
               {"type": "install", "ts": self.clock(), "data": dict(INSTALL, capability_id="Bad-Id")},
               {"type": "install", "ts": self.clock(), "data": dict(INSTALL, planned_version=True)},
               {"type": "install", "ts": self.clock(), "data": "pabc"},
               {"type": "net_on", "ts": self.clock(), "data": {"url": "http://insecure.test/"}},
               {"type": "net_on", "ts": self.clock(), "data": {"other": 1}},
               {"type": "repair_store", "ts": self.clock(), "data": {"x": 1}},
               {"type": "model_download", "ts": self.clock(), "data": {"model_id": "../etc"}},
               {"type": "perm_grant", "ts": self.clock(), "data": {"capability_id": "bmi_calc", "title": "x", "permission": "Network!"}}]
        for value in bad:
            with self.subTest(value=value):
                self.kv.d[key] = value
                self.assertIsNone(hub_state.load(self.kv, self.clock))

    def test_save_refuses_invalid_data_and_writes_nothing(self):
        self.assertFalse(hub_state.save(self.kv, "install", dict(INSTALL, proposal_id="x"), self.clock))
        self.assertFalse(hub_state.save(self.kv, "unknown", {}, self.clock))
        self.assertFalse(hub_state.save(self.kv, "net_on", {"url": "http://x.test/"}, self.clock))
        self.assertEqual(self.kv.writes, 0)

    def test_net_on_may_remember_an_https_page(self):
        self.assertTrue(hub_state.save(self.kv, "net_on", {"url": "https://a.test/x"}, self.clock))
        self.assertEqual(hub_state.load(self.kv, self.clock), ("net_on", {"url": "https://a.test/x"}))

    def test_clear_writes_only_when_there_is_a_record(self):
        hub_state.clear(self.kv)
        self.assertEqual(self.kv.writes, 0)
        hub_state.save(self.kv, "net_on", {}, self.clock)
        writes = self.kv.writes
        hub_state.clear(self.kv)
        self.assertEqual(self.kv.writes, writes + 1)
        self.assertIsNone(hub_state.load(self.kv, self.clock))
        hub_state.clear(self.kv)
        self.assertEqual(self.kv.writes, writes + 1)

    def test_a_failing_store_never_raises(self):
        self.kv.fail_read = self.kv.fail_write = True
        self.assertIsNone(hub_state.load(self.kv, self.clock))
        self.assertFalse(hub_state.save(self.kv, "net_on", {}, self.clock))
        self.assertFalse(hub_state.clear(self.kv))
        self.assertFalse(hub_state.save_wish(self.kv, "x", self.clock))
        self.assertEqual(hub_state.load_wish(self.kv, self.clock), "")
        self.assertIsNone(hub_state.load(object(), self.clock))                  # not even a memory

    def test_the_wish_is_clipped_cleaned_and_expires(self):
        self.assertFalse(hub_state.save_wish(self.kv, "   ", self.clock))
        hub_state.save_wish(self.kv, "a\n\n  b " + "x" * 2000, self.clock)
        wish = hub_state.load_wish(self.kv, self.clock)
        self.assertTrue(wish.startswith("a b x") and len(wish) == hub_state.MAX_WISH_CHARS)
        self.clock.t += hub_state.WISH_TTL_SECONDS + 1
        self.assertEqual(hub_state.load_wish(self.kv, self.clock), "")
        self.kv.d[hub_state.WISH_KEY] = {"ts": self.clock(), "text": 5}
        self.assertEqual(hub_state.load_wish(self.kv, self.clock), "")


def classify(text, named=False):
    norm = nz.normalize(text)
    return HI.classify(text, norm, fa_text.words(norm), named)


class Classifier(unittest.TestCase):
    POSITIVE = [
        ("اینترنت را روشن کن", HI.NET_ON), ("اینترنت رو روشن کن", HI.NET_ON), ("می‌خوام اینترنت وصل شه", HI.NET_ON),
        ("به برنامه اجازهٔ اینترنت بده", HI.NET_ON), ("اینترنت را خاموش کن", HI.NET_OFF), ("اینترنت رو قطع کن", HI.NET_OFF),
        ("وضعیت اینترنت چیست؟", HI.NET_STATUS), ("آیا اینترنت وصل است؟", HI.NET_STATUS), ("اینترنت وصله؟", HI.NET_STATUS),
        ("نقشهٔ قابلیت‌ها را نشان بده", HI.OVERVIEW), ("وضعیت کامل قابلیت‌هایت را بگو", HI.OVERVIEW),
        ("چه چیزهایی هنوز نداری؟", HI.OVERVIEW), ("تو چه کارهایی نمی‌تونی انجام بدی؟", HI.OVERVIEW),
        ("افزونه‌ها را لیست کن", HI.EXT_LIST), ("چه افزونه‌هایی داری؟", HI.EXT_LIST), ("افزونه‌های نصب شده", HI.EXT_LIST),
        ("افزونه‌ها", HI.EXT_LIST), ("تاریخچهٔ افزونه ساعت", HI.EXT_HISTORY), ("افزونه ساعت را برگردان", HI.EXT_ROLLBACK),
        ("افزونه ساعت را به نسخهٔ ۲ برگردان", HI.EXT_ROLLBACK), ("نسخهٔ قبلی افزونه ساعت را برگردان", HI.EXT_ROLLBACK),
        ("افزونه ساعت را غیرفعال کن", HI.EXT_DISABLE), ("افزونه ساعت را خاموش کن", HI.EXT_DISABLE),
        ("افزونه ساعت را فعال کن", HI.EXT_ENABLE), ("مجوز اینترنت افزونه ساعت را بگیر", HI.EXT_PERM_REVOKE),
        ("به افزونه ساعت اجازهٔ اینترنت بده", HI.EXT_PERM_GRANT), ("مدل‌ها را نشان بده", HI.MODELS_LIST),
        ("مدل‌های محلی چیست؟", HI.MODELS_LIST), ("مدل tiny-ngram را دانلود کن", HI.MODEL_DOWNLOAD),
        ("مدل tiny-ngram را آماده کن", HI.MODEL_PREPARE), ("مدل tiny-ngram را حذف کن", HI.MODEL_REMOVE),
        ("مجوز مدل tiny-ngram را می‌پذیرم", HI.MODEL_LICENSE), ("وضعیت اندروید", HI.ANDROID_STATUS),
        ("دسترسی‌های گوشی چیست؟", HI.ANDROID_STATUS), ("مجوزها را نشان بده", HI.PERMISSIONS),
        ("پرامپت افزونه برای تبدیل تاریخ", HI.EXT_PROMPT), ("یک پرامپت برای ChatGPT بده که ماشین‌حساب بسازد", HI.EXT_PROMPT),
        ("چطور افزونه اضافه کنم؟", HI.EXT_HELP), ("چطور یک قابلیت جدید اضافه کنم؟", HI.EXT_HELP),
        ("حافظهٔ افزونه‌ها را ترمیم کن", HI.REPAIR_STORE), ("صفحهٔ https://example.com/a?b=1 را بخوان", HI.FETCH),
        ("https://example.com/a را ببین", HI.FETCH),
    ]
    NEGATIVE = [
        "سلام", "ممنون", "لیست قابلیت‌ها", "تاریخچه", "برگردان", "غیرفعالش کن", "اسم من علی است", "من ساعت را دوست دارم",
        "اینترنت قطع شد", "اینترنت من خیلی کنده", "چطور از اینترنت پول دربیاورم؟", "در اینترنت جستجو کن پایتون",
        "افزونهٔ کروم را نصب کن", "افزونه‌ها را نصب کن", "مدل هوش مصنوعی بساز", "مدل موی من چیست؟", "مدل iphone را بخر",
        "با دوربین گوشی عکس بگیر", "قیمت گوشی چقدر است؟", "لینک https://example.com عالیه", "پاک کن", "یک مبدل کیلومتر به مایل بساز",
        "ده کیلومتر چند مایل است؟", "نقشهٔ ایران را نشان بده", "تو چه کاری می‌توانی بکنی؟", "حالت چطوره؟", "مجوز رانندگی من گم شده",
    ]

    def test_hub_sentences(self):
        for text, kind in self.POSITIVE:
            with self.subTest(text=text):
                found = classify(text, named="ساعت" in text)
                self.assertIsNotNone(found, text)
                self.assertEqual(found.kind, kind, text)

    def test_ordinary_sentences_are_not_taken_over(self):
        for text in self.NEGATIVE:
            with self.subTest(text=text):
                self.assertIsNone(classify(text), text)

    def test_none_of_the_existing_brain_sentences_is_a_hub_command(self):
        self.assertGreater(len(INTENT_TABLE), 150)
        taken = [row[0] for row in INTENT_TABLE if classify(row[0]) is not None]
        self.assertEqual(taken, [])

    def test_slots(self):
        self.assertEqual(classify("صفحهٔ https://example.com/a?b=1. را بخوان").slots["url"], "https://example.com/a?b=1")
        self.assertEqual(classify("مدل Fa-Ngram.v2 را دانلود کن").slots["model_id"], "fa-ngram.v2")
        self.assertIsNone(classify("مدل ها را دانلود کن").slots["model_id"])
        self.assertEqual(classify("افزونه ساعت را به نسخهٔ ۳ برگردان").slots["version"], 3)
        self.assertIsNone(classify("افزونه ساعت را برگردان").slots["version"])
        self.assertEqual(classify("مجوز اینترنت افزونه ساعت را بگیر").slots["permissions"], ["network", "clock"])
        self.assertEqual(classify("پرامپت افزونه برای تبدیل تاریخ").slots["wish"], "تبدیل تاریخ")
        self.assertEqual(classify("یک پرامپت برای ChatGPT بده که ماشین‌حساب بسازد").slots["wish"], "ماشین حساب بسازد")
        self.assertEqual(classify("پرامپت افزونه بده").slots["wish"], "")
        self.assertTrue(classify("چه چیزهایی هنوز نداری؟").slots["missing"])

    def test_a_named_extension_alone_is_enough_for_the_verbs_but_not_without_one(self):
        self.assertIsNone(classify("تبدیل تاریخ را غیرفعال کن"))
        self.assertEqual(classify("تبدیل تاریخ را غیرفعال کن", named=True).kind, HI.EXT_DISABLE)
        self.assertEqual(classify("تبدیل تاریخ را برگردان", named=True).kind, HI.EXT_ROLLBACK)
        self.assertIsNone(classify("سلام", named=True))

    def test_urls_need_a_reading_word_and_only_http_family(self):
        self.assertIsNone(classify("https://example.com"))
        self.assertIsNone(classify("ftp://example.com را بخوان"))
        self.assertEqual(classify("http://example.com را بخوان").slots["url"], "http://example.com")         # refused later by the fetcher

    def test_long_or_empty_text_is_never_a_command(self):
        self.assertIsNone(HI.classify("", "", []))
        long = "اینترنت را روشن کن " + "الف " * 400
        self.assertIsNone(classify(long))
        self.assertIsNone(HI.classify("x", "x", ["x"] * 121))

    def test_every_kind_has_a_constant_and_a_handler(self):
        from persian_brain import hub_commands
        self.assertEqual(set(hub_commands.HANDLERS), set(HI.KINDS))


class MessagesAreHonest(unittest.TestCase):
    CLAIMS = ("نصب و فعال شد", "نصب شد", "فعال شد", "قابل استفاده است", "برگشت", "یاد گرفتم")

    def assertNoClaim(self, text, claims=None):
        for claim in claims or self.CLAIMS:
            self.assertNotIn(claim, text, text)

    def test_a_proposal_says_nothing_is_installed_yet(self):
        result = {"status": "pending_approval", "capability_id": "bmi_calc", "title": "BMI", "action": "create", "planned_version": 1,
                  "permissions": ["network"], "tests": {"passed": 2, "total": 2},
                  "review": {"inputs": [{"name": "w", "label": "وزن"}], "outputs": [{"name": "b"}], "examples": ["bmi 70"],
                             "source_sha256": "a" * 64, "source_lines": 3, "provenance": {"source": "https://x.test"}}}
        for net in (True, False, None):
            text = HM.proposal(result, net)
            self.assertIn("هنوز چیزی نصب یا فعال نشده", text)
            self.assertIn("(بله / نه)", text)
            self.assertIn("مجوز اینترنت خود برنامه", text)
            self.assertNoClaim(text, ("نصب و فعال شد",))
        self.assertIn("روشن است", HM.proposal(result, True))
        self.assertIn("خاموش است", HM.proposal(result, False))
        self.assertIn("نامعلوم است", HM.proposal(result, None))
        update = HM.proposal(dict(result, action="update", planned_version=3, permissions=[]), True)
        self.assertIn("به‌روزرسانی", update)
        self.assertIn("مجوز اضافه‌ای نمی‌خواهد", update)

    def test_every_failed_status_says_that_nothing_was_activated(self):
        for status in ("not_pending", "expired", "busy", "approval_required", "failed", "error", "weird"):
            with self.subTest(status):
                text = HM.approve_failed({"status": status, "code": "E_X", "detail": "boom"})
                self.assertNoClaim(text, ("نصب و فعال شد", "فعال شد"))
        self.assertIn("نسخهٔ قبلی (۲) دوباره فعال", HM.approve_failed({"status": "failed", "detail": "x", "restored_version": 2}))

    def test_rejection_lists_the_reasons_bounded_and_isolated(self):
        issues = [{"code": "c%d" % i, "path": "source", "message": "bad thing %d " % i + "x" * 400} for i in range(9)]
        text = HM.proposal_rejected({"status": "rejected", "stage": "source", "issues": issues})
        self.assertIn("هیچ چیزی نصب یا فعال نشد", text)
        self.assertEqual(text.count("• "), HM.MAX_ISSUES)
        self.assertIn("و ۳ مشکل دیگر", text)
        self.assertLess(len(text), 2600)
        self.assertIn("⁦", text)
        self.assertNoClaim(text, ("نصب و فعال شد", "فعال شد"))

    def test_extension_failures_are_never_phrased_as_answers(self):
        for status in ("blocked_permission", "integrity_failed", "limit", "bad_output", "runtime_error", "disabled", "x"):
            with self.subTest(status):
                text = HM.ext_failed({"status": status, "title": "T", "capability_id": "t_x", "missing_permissions": ["network"],
                                      "reason": "hash", "error": {"message": "boom"}})
                self.assertIn("«T»", text)
                self.assertNotIn("·", text)                            # the footer that only a real answer carries
                self.assertNotIn("نسخهٔ ۱", text)
        self.assertIn("اینترنت", HM.ext_failed({"status": "blocked_permission", "title": "T", "missing_permissions": ["network"]}))
        self.assertIn("نسخهٔ سالم ۲", HM.ext_failed({"status": "integrity_failed", "title": "T", "reason": "h", "repaired_to": 2}))
        self.assertIn("نسخهٔ سالمی برای برگشتن نبود", HM.ext_failed({"status": "integrity_failed", "title": "T", "reason": "h"}))

    def test_an_answer_carries_the_extension_footer(self):
        text = HM.ext_answer({"answer": "BMI شما ۲۲٫۹ است.", "title": "BMI", "capability_id": "bmi_calc", "version": 2})
        self.assertEqual(text.splitlines()[0], "BMI شما ۲۲٫۹ است.")
        self.assertIn("افزونهٔ «BMI» · نسخهٔ ۲", text)

    def test_the_internet_messages_distinguish_the_app_switch_from_the_device(self):
        class Dev:
            state = "offline"
        off = HM.net_status(False, Dev())
        self.assertIn("خاموش", off)
        self.assertIn("آفلاین", off)
        self.assertIn("آفلاین کار می‌کنند", off)
        on = HM.net_status(True, type("D", (), {"state": "unknown"})())
        self.assertIn("روشن", on)
        self.assertIn("نامشخص", on)

    def test_a_model_is_usable_only_when_its_status_says_so(self):
        from model_runtime.manager import ModelStatus, PipelineReport, StageReport
        base = dict(model_id="fa-ngram", state="verified", ok=True, code="ok", stage="verify", reasons=(), usable=False,
                    message_fa="صحت تأیید شد.", message_en="ok", card={"title": "T"})
        report = PipelineReport("fa-ngram", False, (StageReport("verify", True, "ok"), StageReport("compatibility", False, "no_runtime")),
                                ModelStatus(**dict(base, ok=False, state="failed", code="no_runtime", message_fa="موتور ندارد.")))
        text = HT.model_pipeline("fa-ngram", None, report)
        self.assertIn("مدل قابل استفاده نیست", text)
        self.assertNotIn("همهٔ مراحل را گذراند", text)
        good = PipelineReport("fa-ngram", True, tuple(StageReport(s, True, "ok") for s in ("verify", "compatibility", "load", "smoke")),
                              ModelStatus(**dict(base, state="usable", usable=True, stage="smoke")))
        self.assertIn("همهٔ مراحل را گذراند و قابل استفاده است", HT.model_pipeline("fa-ngram", None, good))
        failed_download = ModelStatus(**dict(base, ok=False, state="failed", code="download_failed", message_fa="دانلود ناموفق بود."))
        text = HT.model_pipeline("fa-ngram", failed_download, None)
        self.assertIn("دانلود انجام نشد", text)
        self.assertIn("چیزی قابل استفاده نشد", text)
        listing = HT.models_list([ModelStatus(**base)], [])
        self.assertIn("هنوز قابل استفاده نیست", listing)

    def test_gap_replies_quote_the_exact_blockers_and_never_promise(self):
        from brain_hub import gaps
        for gap in gaps.GAPS:
            with self.subTest(gap.gap_id):
                text = HT.gap_reply(gap)
                self.assertIn("هنوز نمی‌توانم", text)
                self.assertIn(gap.title_fa, text)
                for blocker in gap.blockers[:4]:
                    self.assertIn(blocker.text_fa, text)
                self.assertNoClaim(text, ("ساختم", "نصب شد", "یاد گرفتم", "انجام شد"))
                self.assertIn("دقیق‌تر", HT.gap_reply(gap, lead=False))


if __name__ == "__main__":
    unittest.main()
