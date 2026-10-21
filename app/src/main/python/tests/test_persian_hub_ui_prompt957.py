"""
Prompt 957 - the chat page as the user meets it: attaching a text / JSON file, long messages shown shortened, extension code
that keeps its indentation on the way to the app, and the two new starter chips.

  Node        the DOM-free helpers of i18n.js (fillTemplate, shortenForDisplay, protectPackage) - skipped without Node
  real route  the page's own encoding of a package, sent to the real app (HTTP -> Core -> brain -> hub)  - skipped without Node
  Chromium    the real page against the real app with Playwright (file chooser, send, confirm, use, phone sizes) - skipped
              when Playwright / Chromium are not installed

The frozen Prompt-956 page tests (tests/test_persian_mobile_ui_prompt956.py) keep running unchanged next to these.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ext_runtime import intake
from self_builder import fa_text
from tests.persian_app_case_prompt957 import AppCase, LOAN_ASK, loan_answer, loan_pkg

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "interface", "static")
I18N = os.path.join(STATIC, "i18n.js")
needs_node = unittest.skipUnless(shutil.which("node"), "node is not installed")
BIDI = ("⁦", "⁩")


def clean(text):
    for mark in BIDI:
        text = text.replace(mark, "")
    return text


def node_json(expression, *values):
    """Evaluates a JS expression with the page's i18n.js loaded as `T` and the arguments as `v` (parsed JSON); returns parsed JSON."""
    script = ("const T=require(process.argv[1]);const v=JSON.parse(process.argv[2]);const r=" + expression + ";"
              "process.stdout.write(JSON.stringify(r === undefined ? null : r));")
    out = subprocess.run(["node", "-e", script, I18N, json.dumps(list(values))], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError("node failed: " + out.stderr)
    return json.loads(out.stdout)


def fold(text):
    """What Core's InputSystem.normalize does to every message before anything reads it."""
    return " ".join(text.strip().split())


def fenced(pkg, indent=1):
    return "این بسته را بررسی کن:\n```json\n" + json.dumps(pkg, ensure_ascii=False, indent=indent) + "\n```"


# ======================================================================================= Node
@needs_node
class DomFreeHelpers(unittest.TestCase):
    def test_templates_use_persian_digits_and_isolate_file_names(self):
        out = node_json("T.fillTemplate(T.STR.attachReady,{name:v[0],n:v[1]})", "pkg.json", 1234)
        self.assertIn("(۱۲۳۴ نویسه)", out)
        self.assertIn("⁦pkg.json⁩", out)
        self.assertEqual(node_json("T.fillTemplate('a {x} b',{})"), "a {x} b")                  # an unknown key stays visible

    def test_long_messages_are_shortened_for_display_only(self):
        short = node_json("T.shortenForDisplay(v[0],600)", "کوتاه")
        self.assertEqual(short, "کوتاه")
        long = node_json("T.shortenForDisplay(v[0],600)", "ب" * 5000)
        self.assertTrue(long.startswith("ب" * 600 + "\n"))
        self.assertIn("پیام بلند است: ۵۰۰۰ نویسه", long)
        self.assertLess(len(long), 800)
        emoji = node_json("T.shortenForDisplay(v[0],10)", "😀" * 50)
        self.assertTrue(emoji.startswith("😀" * 10 + "\n"))                                      # no character is cut in half
        self.assertEqual(node_json("T.shortenForDisplay(undefined)"), "")

    def test_the_display_limit_is_exact_and_a_bad_limit_falls_back_to_the_default(self):
        self.assertEqual(node_json("T.shortenForDisplay(v[0],600)", "ب" * 600), "ب" * 600)             # at the limit: untouched
        self.assertTrue(node_json("T.shortenForDisplay(v[0],600)", "ب" * 601).startswith("ب" * 600 + "\n"))
        for bad in ("0", "-5", "NaN", "'abc'", "undefined"):
            with self.subTest(limit=bad):
                out = node_json("T.shortenForDisplay(v[0]," + bad + ")", "ب" * 700)
                self.assertTrue(out.startswith("ب" * 600 + "\n"))                                       # the default of 600

    def test_a_package_survives_the_cores_whitespace_folding_exactly(self):
        spaced = loan_pkg(indent="    ", title="قسط  ماهانه   وام", answer="قسط ماهانه:  {payment}  تومان؛ جمع پرداختی: {total}")
        spaced["description"] = "توضیح  با فاصله‌های ویژه"
        texts = [fenced(spaced), fenced(spaced, indent=4), json.dumps(spaced, ensure_ascii=False),
                 "{x} پیش از بسته " + fenced(spaced) + "\nممنون {y}"]
        for text in texts:
            with self.subTest(text=text[:40]):
                protected = node_json("T.protectPackage(v[0])", text)
                self.assertNotEqual(protected, text)
                found = intake.find_package_in_text(fold(protected))
                self.assertIsNotNone(found)
                self.assertEqual(json.loads(found), spaced)                                      # byte-for-byte the same package
                self.assertEqual(json.loads(found)["source"], spaced["source"])

    def test_text_that_is_not_a_package_is_left_exactly_as_it_was(self):
        for text in ("سلام  دنیا", "TEACH sky IS the atmosphere", "{ \"a\":  1 }", '{"schema": "ext.v1", broken',
                     '{"schema": "ext.v2", "x":  "a  b"}', '["ext.v1",  "a  b"]', "ext.v1 فقط یک اشاره است  {}", ""):
            with self.subTest(text=text):
                self.assertEqual(node_json("T.protectPackage(v[0])", text), text)
        self.assertEqual(node_json("T.protectPackage(undefined)"), None)

    def test_only_an_object_whose_own_schema_is_ext_v1_counts_as_a_package(self):
        # Every text below MENTIONS "ext.v1" (so the cheap early exit does not apply) and holds spaced strings that an
        # over-eager rewrite would visibly change; none of them is a package, so none may be touched.
        other = {"schema": "ext.v2", "note": "works like ext.v1", "source": "a  b"}
        texts = ["ext.v1 " + json.dumps(other, ensure_ascii=False),
                 '{"schema": "ext.v10", "source": "a  b"} ext.v1',
                 '{"schema": "EXT.V1", "source": "a  b"} ext.v1',
                 '{"schema": 1, "source": "a  b"} ext.v1',
                 '{"id": "ext.v1", "source": "a  b"}',                       # the mark is a VALUE of another key
                 '{"schema": ["ext.v1"], "source": "a  b"}']
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(node_json("T.protectPackage(v[0])", text), text)

    def test_text_without_the_literal_mark_is_never_rewritten_even_if_json_would_decode_to_it(self):
        # The assistant itself looks for the literal mark ("ext.v1") before it reads a package, so a JSON escape of it
        # is not a package for the assistant; the page must not rewrite what the assistant would not read either.
        text = '{"schema": "ext\\u002ev1", "source": "a  b"}'
        self.assertEqual(node_json("T.protectPackage(v[0])", text), text)

    def test_braces_and_escaped_quotes_inside_strings_do_not_confuse_the_matcher(self):
        pkg = loan_pkg(indent="    ")
        pkg["description"] = 'نشانهٔ "}" و "{" و \\ و \\" پایان'               # JSON text holds: \"}\"  \"{\"  \\  \\\"
        pkg["answer"] = "قسط {payment} «{total}»  تومان"
        protected = node_json("T.protectPackage(v[0])", fenced(pkg))
        self.assertNotEqual(protected, fenced(pkg))
        found = intake.find_package_in_text(fold(protected))
        self.assertIsNotNone(found)
        self.assertEqual(json.loads(found), pkg)

    def test_protecting_twice_changes_nothing_more(self):
        once = node_json("T.protectPackage(v[0])", fenced(loan_pkg(indent="    ")))
        self.assertEqual(node_json("T.protectPackage(v[0])", once), once)

    def test_a_hostile_message_full_of_braces_returns_quickly_and_untouched(self):
        text = "{" * 100_000 + " ext.v1 " + "}" * 10
        started = time.time()
        out = node_json("T.protectPackage(v[0])", text)
        self.assertLess(time.time() - started, 10)
        self.assertEqual(out, text)


# ======================================================================================= real route
@needs_node
class PageEncodingReachesTheRealApp(AppCase):
    def test_space_indented_code_installs_when_sent_the_way_the_page_sends_it(self):
        pkg = loan_pkg(indent="    ")
        text = node_json("T.protectPackage(v[0])", fenced(pkg))
        proposal = self.ask(text)
        self.assertIn("آزمون‌ها: ۴ از ۴ موفق", proposal)
        self.assertIn(hashlib.sha256(pkg["source"].encode("utf-8")).hexdigest()[:12], proposal)   # the code arrived unchanged
        self.assertIn("نصب و فعال شد", self.ask("بله"))
        self.assertIn(loan_answer(11_001_599, 132_019_190), self.ask(LOAN_ASK))


# ======================================================================================= Chromium
try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
    _PW = True
except Exception:  # noqa: BLE001
    _PW = False


@unittest.skipUnless(_PW, "Playwright is not installed")
class PageInChromium(AppCase):
    PHONES = {"small": (320, 568), "normal": (360, 740), "large": (412, 915)}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = None
        try:
            cls._pw = sync_playwright().start()
            cls._browser = cls._pw.chromium.launch()
        except Exception as e:  # noqa: BLE001
            if cls._pw is not None:
                try:
                    cls._pw.stop()
                except Exception:  # noqa: BLE001
                    pass
            raise unittest.SkipTest("Chromium is not available: %s" % e)

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()
        super().tearDownClass()

    def page(self, w=360, h=740):
        ctx = self._browser.new_context(viewport={"width": w, "height": h}, is_mobile=True, has_touch=True, locale="fa-IR")
        self.addCleanup(ctx.close)
        pg = ctx.new_page()
        self.errors, self.sent = [], []
        pg.on("pageerror", lambda e: self.errors.append(str(e)))
        pg.on("request", lambda r: self.sent.append(r.post_data) if r.url.endswith("/api/message") and r.method == "POST" else None)
        pg.goto(self.url + "/")
        pg.wait_for_selector("#status-dot.dot-live", timeout=10000)
        return pg

    def send(self, pg, text=None):
        before = pg.evaluate("document.querySelectorAll('.message.assistant:not(.typing)').length")
        if text is not None:
            pg.fill("#input-box", text)
        pg.click("#send-btn")
        pg.wait_for_function("n => document.querySelectorAll('.message.assistant:not(.typing)').length > n"
                             " && !document.getElementById('send-btn').disabled", arg=before, timeout=60000)
        return pg.inner_text(".message.assistant:not(.typing) >> nth=-1")

    def attach(self, pg, name, data, mime="application/json"):
        pg.set_input_files("#attach-input", {"name": name, "mimeType": mime, "buffer": data})
        pg.wait_for_selector("#attach-note", state="visible", timeout=10000)
        return clean(pg.inner_text("#attach-note"))

    # ------------------------------------------------------------------ the button and the file chooser
    def test_the_attach_button_opens_the_chooser_for_text_and_json_files_only(self):
        pg = self.page()
        self.assertEqual(pg.inner_text("#attach-btn"), "پیوست")
        self.assertEqual(pg.get_attribute("#attach-btn", "aria-label"), "پیوست فایل متنی")
        accept = pg.get_attribute("#attach-input", "accept")
        for kind in (".json", ".txt", "text/plain", "application/json"):
            self.assertIn(kind, accept)
        with pg.expect_file_chooser() as chooser:
            pg.click("#attach-btn")
        self.assertFalse(chooser.value.is_multiple())                               # one file at a time
        chooser.value.set_files({"name": "note.txt", "mimeType": "text/plain", "buffer": "سلام دنیا".encode("utf-8")})
        pg.wait_for_selector("#attach-note", state="visible")
        self.assertEqual(pg.input_value("#input-box"), "سلام دنیا")
        self.assertEqual(self.errors, [])

    def test_an_attached_file_is_only_read_into_the_box_nothing_is_sent_until_send(self):
        pg = self.page()
        text = "پایتون یک زبان برنامه‌نویسی است"
        note = self.attach(pg, "note.txt", text.encode("utf-8"), "text/plain")
        self.assertIn("فایل «note.txt» خوانده شد (%s نویسه)" % fa_text.fa_number(len(text)), note)
        self.assertIn("هنوز چیزی فرستاده نشده", note)
        self.assertEqual(pg.input_value("#input-box"), "پایتون یک زبان برنامه‌نویسی است")
        pg.wait_for_timeout(300)
        self.assertEqual(self.sent, [])
        self.assertEqual(pg.query_selector(".message.user"), None)

    def test_the_size_ceiling_is_exactly_200000_bytes_and_a_nul_byte_means_not_text(self):
        pg = self.page()
        note = self.attach(pg, "edge.txt", b"a" * 200_000, "text/plain")
        self.assertIn("خوانده شد (۲۰۰۰۰۰ نویسه)", note)
        self.assertEqual(len(pg.input_value("#input-box")), 200_000)
        pg.fill("#input-box", "")
        self.assertIn("بزرگ‌تر از ۲۰۰ کیلوبایت", self.attach(pg, "over.txt", b"a" * 200_001, "text/plain"))
        self.assertEqual(pg.input_value("#input-box"), "")
        self.assertIn("این فایل متن UTF-8 نیست", self.attach(pg, "nul.txt", b"abc\x00def", "text/plain"))
        self.assertEqual(pg.input_value("#input-box"), "")

    def test_an_empty_file_is_refused_without_reading_it(self):
        pg = self.page()
        pg.evaluate("() => { window.__reads = 0; const orig = FileReader.prototype.readAsText;"
                    " FileReader.prototype.readAsText = function () { window.__reads++; return orig.apply(this, arguments); }; }")
        self.assertIn("این فایل خالی است", self.attach(pg, "empty.txt", b"", "text/plain"))
        self.assertEqual(pg.evaluate("window.__reads"), 0)
        self.attach(pg, "one.txt", b"x", "text/plain")
        self.assertEqual(pg.evaluate("window.__reads"), 1)                          # the counter really counts: a non-empty file is read

    def test_the_chooser_starts_empty_so_the_same_file_can_be_chosen_twice(self):
        pg = self.page()
        data = {"name": "same.txt", "mimeType": "text/plain", "buffer": "سلام".encode("utf-8")}
        for attempt in range(2):
            with pg.expect_file_chooser() as chooser:
                pg.click("#attach-btn")
            self.assertEqual(chooser.value.element.evaluate("e => e.files.length"), 0, attempt)     # nothing is left from last time
            chooser.value.set_files(data)
            pg.wait_for_function("document.getElementById('input-box').value !== ''")
            pg.fill("#input-box", "")

    def test_the_note_counts_characters_not_utf16_units_and_is_replaced_by_the_next_file(self):
        pg = self.page()
        self.assertIn("(۳ نویسه)", self.attach(pg, "emoji.txt", "😀😀😀".encode("utf-8"), "text/plain"))
        note = self.attach(pg, "empty.txt", b"", "text/plain")
        self.assertIn("این فایل خالی است", note)
        self.assertNotIn("خوانده شد", note)                                              # one honest line, never a stale one

    def test_the_attach_button_is_disabled_while_a_message_is_in_flight(self):
        pg = self.page()
        pg.route("**/api/message", lambda route: (pg.wait_for_timeout(500), route.continue_()))
        pg.fill("#input-box", "سلام")
        pg.click("#send-btn")
        pg.wait_for_selector(".message.typing", timeout=5000)
        self.assertTrue(pg.is_disabled("#attach-btn"))
        pg.wait_for_function("!document.getElementById('send-btn').disabled", timeout=15000)
        self.assertFalse(pg.is_disabled("#attach-btn"))

    def test_a_utf16_file_with_a_byte_order_mark_is_read_correctly_not_garbled(self):
        pg = self.page()
        note = self.attach(pg, "utf16.txt", "سلام دنیا".encode("utf-16"), "text/plain")
        self.assertIn("خوانده شد (۹ نویسه)", note)
        self.assertEqual(pg.input_value("#input-box"), "سلام دنیا")

    def test_attaching_keeps_what_the_user_has_already_typed(self):
        pg = self.page()
        pg.fill("#input-box", "این بسته را نصب کن")
        self.attach(pg, "note.txt", "سلام دنیا".encode("utf-8"), "text/plain")
        self.assertEqual(pg.input_value("#input-box"), "این بسته را نصب کن\n\nسلام دنیا")

    def test_a_file_that_cannot_be_read_says_why_and_changes_nothing(self):
        cases = (("empty.txt", b"", "این فایل خالی است"), ("blank.txt", b"  \n \t ", "این فایل خالی است"),
                 ("big.json", b"a" * 200_001, "بزرگ‌تر از ۲۰۰ کیلوبایت است"),
                 ("image.png", b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x01\x80", "این فایل متن UTF-8 نیست"),
                 ("windows1256.txt", "سلام".encode("cp1256"), "این فایل متن UTF-8 نیست"))
        pg = self.page()
        pg.fill("#input-box", "پیش‌نویس من")
        for name, data, reason in cases:
            with self.subTest(file=name):
                note = self.attach(pg, name, data, "application/octet-stream")
                self.assertIn(reason, note)
                self.assertEqual(pg.input_value("#input-box"), "پیش‌نویس من")
        self.assertEqual(self.sent, [])

    # ------------------------------------------------------------------ the whole way: attach -> send -> yes -> use
    def test_an_attached_extension_package_is_sent_whole_shown_short_and_installs_after_yes(self):
        pkg = loan_pkg(indent="    ")                                               # spaces: the case the chat would break
        data = json.dumps(pkg, ensure_ascii=False, indent=2).encode("utf-8")
        pg = self.page()
        note = self.attach(pg, "loan.json", data)
        self.assertIn("فایل «loan.json» خوانده شد", note)
        self.assertEqual(self.sent, [])
        proposal = self.send(pg)
        self.assertEqual(len(self.sent), 1)
        wire = json.loads(self.sent[0])["text"]                                       # what the app received from the page ...
        self.assertIn("\\u0020", wire)                                                # ... with the code's spaces protected
        self.assertNotIn("\n", wire)
        self.assertEqual(json.loads(wire), pkg)                                       # ... and still exactly the package
        bubble = pg.inner_text(".message.user .bubble")
        self.assertIn("پیام بلند است", bubble)                                          # long: shown shortened ...
        self.assertLess(len(bubble), 800)
        self.assertIn("متن کامل فرستاده شد", bubble)                                    # ... and says the whole text was sent
        self.assertEqual(pg.input_value("#input-box"), "")
        self.assertTrue(pg.is_hidden("#attach-note"))
        self.assertIn("هنوز چیزی نصب یا فعال نشده", proposal)
        self.assertIn("آزمون‌ها: ۴ از ۴ موفق", proposal)
        self.assertIsNone(self.hub.extension("loan_installment"))
        self.assertIn("نصب و فعال شد", self.send(pg, "بله"))
        self.assertEqual(self.hub.extension("loan_installment")["state"], "active")
        self.assertIn(loan_answer(11_001_599, 132_019_190), self.send(pg, LOAN_ASK))
        self.assertEqual(self.errors, [])

    def test_a_failed_send_keeps_the_whole_attached_text_as_the_draft(self):
        pg = self.page()
        pg.route("**/api/message", lambda route: route.abort())
        text = "ب" * 3000
        self.attach(pg, "long.txt", text.encode("utf-8"), "text/plain")
        pg.click("#send-btn")
        pg.wait_for_selector(".message.error", timeout=10000)
        self.assertEqual(pg.input_value("#input-box"), text)                          # restored in full, never the shortened display

    def test_an_error_answer_from_the_app_also_keeps_the_whole_attached_text_as_the_draft(self):
        pg = self.page()
        pg.route("**/api/message", lambda route: route.fulfill(status=500, content_type="application/json",
                                                               body='{"error": "internal error"}'))
        text = "ب" * 3000
        self.attach(pg, "long.txt", text.encode("utf-8"), "text/plain")
        pg.click("#send-btn")
        pg.wait_for_selector(".message.error", timeout=10000)
        self.assertEqual(pg.input_value("#input-box"), text)                          # not shortened on this path either

    # ------------------------------------------------------------------ the starter chips and the info sheet
    def test_the_new_starter_chips_reach_the_real_brain(self):
        pg = self.page()
        pg.click("text=افزودن قابلیت جدید")
        self.assertEqual(pg.input_value("#input-box"), "چطور افزونه اضافه کنم؟")
        self.assertIn("ext.v1", self.send(pg))
        pg = self.page()
        self.assertIsNotNone(pg.query_selector("#hints"))
        pg.click("text=نقشهٔ قابلیت‌ها")
        self.assertIn("نقشهٔ قابلیت‌ها (از وضعیت واقعی همین لحظه)", self.send(pg))

    def test_the_info_sheet_footer_is_truthful_about_the_internet(self):
        pg = self.page()
        pg.click("#info-open")
        pg.wait_for_selector("#info-sheet", state="visible")
        footer = pg.inner_text(".sheet-footer")
        self.assertIn("اینترنت فقط با اجازهٔ خودت", footer)
        self.assertNotIn("فقط محلی", footer)

    # ------------------------------------------------------------------ phone sizes
    def test_the_composer_fits_every_phone_size_with_the_attach_button_and_its_note(self):
        for name, (w, h) in self.PHONES.items():
            with self.subTest(size=name):
                pg = self.page(w, h)
                self.attach(pg, "note.txt", ("خط " * 40).encode("utf-8"), "text/plain")        # the note is on screen too
                m = pg.evaluate("""() => {
                    const box = id => { const r = document.getElementById(id).getBoundingClientRect();
                                        return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height}; };
                    const doc = document.documentElement;
                    return {attach: box('attach-btn'), input: box('input-box'), send: box('send-btn'), form: box('input-form'),
                            messages: box('messages'), note: box('attach-note'), sw: doc.scrollWidth, cw: doc.clientWidth, vh: innerHeight};
                }""")
                self.assertLessEqual(m["sw"], m["cw"])
                self.assertLessEqual(m["form"]["b"], m["vh"] + 0.5)
                for control in ("attach", "send"):
                    self.assertGreaterEqual(m[control]["h"], 44 - 0.5, control)
                    self.assertGreaterEqual(m[control]["w"], 44 - 0.5, control)
                self.assertGreaterEqual(m["input"]["h"], 44 - 0.5)
                self.assertGreaterEqual(m["input"]["w"], 100, "the text box must stay usable")
                first, second, third = sorted((m["attach"], m["input"], m["send"]), key=lambda r: r["l"])
                self.assertLessEqual(first["r"], second["l"] + 0.5)                               # the three controls never overlap
                self.assertLessEqual(second["r"], third["l"] + 0.5)
                self.assertGreaterEqual(first["l"], -0.5)
                self.assertLessEqual(third["r"], m["cw"] + 0.5)
                self.assertGreater(m["messages"]["h"], 80)                                         # the conversation keeps room
                self.assertLessEqual(m["note"]["b"], m["form"]["t"] + 0.5)                         # the note sits above the composer
                self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
