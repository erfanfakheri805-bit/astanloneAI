"""
Prompt 958 - a pack in its text form crosses the chat route intact.

The core folds ALL white space of every message into one space before the Persian brain reads it
(`InputSystem.normalize`; the core is a file this project keeps byte-identical). A pack in its text form is line based and
its Python code lives on indentation, so a pack pasted in the chat could never be recognised. The page therefore sends
such a message as one escaped line (`interface/static/i18n.js`, `protectPackage`) and the brain decodes it first thing
(`persian_brain/wire_text.py`).

  Python coder   exact round trip, the folding leaves the encoded text alone, the white-space class covers ALL of Unicode
  Node           the page's coder gives byte-for-byte the same text as the Python coder (every BMP character + 600 random
                 texts); the JSON form of a pack (code.v1 / lang.v1) survives the folding too - skipped without Node
  real route     HTTP -> Core -> skills -> brain -> pack manager: a code pack and a language pack are proposed, nothing is
                 installed before the user's yes, and the installed code behaves exactly as written
"""
import json
import os
import random
import shutil
import subprocess
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from input_system.input_system import InputSystem
from pack_system import boot, intake
from persian_brain import wire_text
from tests import pack_support_prompt958 as S
from tests.persian_app_case_prompt957 import AppCase

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "interface", "static")
I18N = os.path.join(STATIC, "i18n.js")
needs_node = unittest.skipUnless(shutil.which("node"), "node is not installed")
fold = InputSystem().normalize                      # exactly what the core does to every message

PACK_IDS = ("wire_demo", "wire_json", "wire_lang")

# Deep indentation, a blank line inside a function, trailing spaces, a tab inside a line, Persian text, and escape-looking
# text of the pack's own - everything the folding or a careless escape would damage. The source below is a RAW string:
# every backslash in it is a backslash of the PACK's code (its `\n` is for the pack's Python to read as a newline, not for
# this file), so nothing is interpreted twice. "__U__" stands for one backslash + "u" (the pack's own unicode escape).
NOTE_VALUE = r"back\\slash __U__0041 \s \t \n \\n end".replace("__U__", "\\u")      # the pack keeps it as a raw string: these characters, as written
WIRE_SOURCE = r"""VERSION = 1
MESSAGE = "پاسخ از بستهٔ سیم\nخط دوم می__U__200cشود"
NOTE = r"__NOTE__"


def register(api):
    def match(ctx):
        if "قیمت دلار" in ctx.norm:
            if len(ctx.norm) > 3:
                return True

        return False

    def handle(ctx):
        rows = ["الف", "ب"]__TRAIL__
        count = 2__TAB__# a tab inside a line
        return "|".join(rows) + "::" + MESSAGE.replace("\n", "/") + "::" + NOTE

    api.register_chat("wire_demo", match, handle, stage="fallback")
""".replace("__NOTE__", NOTE_VALUE).replace("__U__", "\\u").replace("__TRAIL__", "   ").replace("__TAB__", "\t")
WIRE_ANSWER = "الف|ب::پاسخ از بستهٔ سیم/خط دوم می" + chr(0x200C) + "شود::" + NOTE_VALUE


def wire_pack(pid="wire_demo"):
    return S.text_pack(pid=pid, source=WIRE_SOURCE)


def samples():
    """Texts that stress the coder: edges, runs, every kind of white space, backslashes that look like escapes, emoji."""
    fixed = ["", " ", "  ", "a", " a", "a ", "  a  ", "a  b", "a   b    c", "a\tb", "a\nb", "a\r\nb", "\n\n", "\\", "\\n", "\\\\",
             "\\u0041", "\\s", "\\x", "a \\ b", "    indented", "trail   ", "x\u00a0y", "x\u2028y\u2029z", "\u3000wide\u3000",
             "\x1c\x1d\x1e\x1f", "\x85", "\x0b\x0c", "emoji 😀  two", "می\u200cخواهم  ", "= = =", wire_text.MARK,
             wire_text.MARK + " x", wire_pack(), S.lang_pack(), "```\n" + wire_pack() + "```\n"]
    pool = [" ", " ", " ", "\n", "\t", "\r", "\\", "n", "s", "u", "0", "a", "ب", "\u200c", "\u00a0", "\u2028", "x", "=", "😀", "\x1f", "\u2003"]
    rng = random.Random(958)
    fuzz = ["".join(rng.choice(pool) for _ in range(rng.randint(0, 40))) for _ in range(600)]
    return fixed + fuzz


def node_map(expression, values):
    """`expression` (JS using the page's i18n.js as `T`, and `x`) for every value; one node process, the data goes through stdin."""
    script = ("const T=require(process.argv[1]);const v=JSON.parse(require('fs').readFileSync(0,'utf8'));"
              "process.stdout.write(JSON.stringify(v.map(function(x){return " + expression + ";})));")
    out = subprocess.run(["node", "-e", script, I18N], input=json.dumps(values), capture_output=True, encoding="utf-8", timeout=180)
    if out.returncode != 0:
        raise AssertionError("node failed: " + out.stderr)
    return json.loads(out.stdout)


# ======================================================================================= the Python coder
class PythonCoderTests(unittest.TestCase):
    def test_every_text_comes_back_exactly(self):
        for text in samples():
            with self.subTest(text=text[:30]):
                self.assertEqual(wire_text.decode(wire_text.encode(text)), text)

    def test_the_cores_folding_leaves_the_encoded_text_alone(self):
        for text in samples():
            with self.subTest(text=text[:30]):
                encoded = wire_text.encode(text)
                self.assertEqual(fold(encoded), encoded)                           # nothing to fold, nothing to strip
                self.assertEqual(wire_text.decode(fold(encoded)), text)           # so the brain gets the original back
                self.assertNotIn("\n", encoded)
                self.assertNotIn("\t", encoded)

    def test_a_whole_pack_survives_the_real_folding_and_is_still_a_pack(self):
        text = wire_pack()
        self.assertNotEqual(fold(text), text)                                      # without the coder the pack is destroyed
        self.assertIsNone(intake.declared_schema(fold(text)))
        restored = wire_text.decode(fold(wire_text.encode(text)))
        self.assertEqual(restored, text)
        schema, package = intake.find_pack_in_text(restored)
        self.assertEqual(schema, "code.v1")
        self.assertEqual(package["files"]["wire_demo/main.py"], WIRE_SOURCE.rstrip("\n").strip("\n") + "\n")

    def test_the_white_space_class_is_exactly_what_the_core_folds(self):
        # `str.split()` is what folds; the coder must escape every character it would take for a separator (and no other).
        folded = {chr(cp) for cp in range(0x110000) if ("a" + chr(cp) + "b").split() != ["a" + chr(cp) + "b"]}
        escaped = {chr(cp) for cp in range(0x110000) if wire_text._WHITE.match(chr(cp))}
        self.assertEqual(folded - {" "}, escaped)
        self.assertIn(" ", folded)                                                 # the plain space has its own rule

    def test_the_escapes_in_detail(self):
        self.assertEqual(wire_text.encode("a\nb"), wire_text.MARK + " a\\nb")
        self.assertEqual(wire_text.encode("a\\nb"), wire_text.MARK + " a\\\\nb")      # a literal backslash + n is NOT a newline
        self.assertEqual(wire_text.encode("a  b"), wire_text.MARK + " a\\s\\sb")
        self.assertEqual(wire_text.encode("a b"), wire_text.MARK + " a b")            # a lone inner space stays readable
        self.assertEqual(wire_text.encode(" a "), wire_text.MARK + " \\sa\\s")
        self.assertEqual(wire_text.encode("a\u00a0b"), wire_text.MARK + " a\\u00a0b")
        self.assertEqual(wire_text.encode("a\x0bb"), wire_text.MARK + " a\\u000bb")
        self.assertEqual(wire_text.encode("a\n    b"), wire_text.MARK + " a\\n\\s\\s\\s\\sb")

    def test_other_text_is_never_touched(self):
        for text in ("", "سلام", "=== PACK code.v1 ===\nid: x\n", "x " + wire_text.MARK, wire_text.MARK + "x"):
            with self.subTest(text=text[:30]):
                self.assertIs(wire_text.decode(text), text)
                self.assertFalse(wire_text.is_encoded(text))
        self.assertIsNone(wire_text.decode(None))
        self.assertEqual(wire_text.decode(5), 5)

    def test_the_mark_alone_is_an_empty_text_and_a_damaged_escape_stays_as_written(self):
        self.assertEqual(wire_text.decode(wire_text.MARK), "")
        self.assertEqual(wire_text.decode(wire_text.MARK + " "), "")
        self.assertEqual(wire_text.decode(wire_text.MARK + " a\\qb\\u12"), "a\\qb\\u12")   # not an escape: written as it came
        self.assertEqual(wire_text.decode("  " + wire_text.MARK + " a\\nb  "), "a\nb")     # unfolded input is understood too

    def test_a_big_pack_round_trips(self):
        text = "\n".join("    " * (i % 6) + "value_%d = [1,  2,\t3]  # kommentar" % i for i in range(30_000))
        encoded = wire_text.encode(text)
        self.assertEqual(wire_text.decode(fold(encoded)), text)


# ======================================================================================= the page's coder
@needs_node
class PageCoderTests(unittest.TestCase):
    def test_the_pages_coder_gives_exactly_the_python_text(self):
        texts = samples()
        got = node_map("T.encodeWire(x)", texts)
        self.assertEqual(len(got), len(texts))
        for text, encoded in zip(texts, got):
            with self.subTest(text=text[:30]):
                self.assertEqual(encoded, wire_text.encode(text))

    def test_every_character_of_the_basic_plane_is_coded_alike(self):
        probes = ["a" + chr(cp) + "b" for cp in range(0x10000) if not 0xD800 <= cp <= 0xDFFF]
        got = node_map("T.encodeWire(x)", probes)
        wrong = [hex(ord(p[1])) for p, g in zip(probes, got) if g != wire_text.encode(p)]
        self.assertEqual(wrong, [])

    def test_a_text_pack_is_encoded_and_comes_back_through_the_real_folding(self):
        for text in (wire_pack(), S.lang_pack(), "این بسته را نصب کن:\n```\n" + wire_pack() + "```\n", wire_pack().replace("\n", "\r\n")):
            with self.subTest(text=text[:30]):
                [sent] = node_map("T.protectPackage(x)", [text])
                self.assertTrue(sent.startswith(wire_text.MARK + " "))
                self.assertEqual(fold(sent), sent)
                self.assertEqual(wire_text.decode(fold(sent)), text)

    def test_the_encoding_is_applied_once(self):
        [once] = node_map("T.protectPackage(x)", [wire_pack()])
        [twice] = node_map("T.protectPackage(x)", [once])
        self.assertEqual(twice, once)

    def test_text_that_is_not_a_text_pack_is_left_exactly_as_it_was(self):
        for text in ("سلام  دنیا\nخط دوم", "def f():\n    return 1\n", "=== PACK something ===\nx", "=== PACK code.v1 === و بقیهٔ جمله",
                     "نمونه: === PACK code.v1 ===", "== PACK code.v1 ==\nid: x", "", "   "):
            with self.subTest(text=text[:30]):
                [sent] = node_map("T.protectPackage(x)", [text])
                self.assertEqual(sent, text)

    def test_a_json_pack_keeps_the_spaces_of_its_code(self):
        _schema, package = intake.find_pack_in_text(wire_pack("wire_json"))
        text = "این بسته را بررسی کن:\n```json\n" + json.dumps(package, ensure_ascii=False, indent=4) + "\n```"
        self.assertNotEqual(intake.find_pack_in_text(fold(text))[1]["files"], package["files"])   # unprotected, the folding changes the code
        [sent] = node_map("T.protectPackage(x)", [text])
        self.assertNotEqual(sent, text)
        found = intake.find_pack_in_text(fold(sent))
        self.assertIsNotNone(found)
        self.assertEqual(found[1]["files"], package["files"])                       # byte for byte, indentation included
        lang = {"schema": "lang.v1", "id": "wire_lang", "version": 1, "title": "t",
                "qa": [{"q": ["پایتخت  ایران کجاست"], "a": "تهران،  شهر   بزرگ"}]}
        [sent] = node_map("T.protectPackage(x)", [json.dumps(lang, ensure_ascii=False, indent=2)])
        self.assertEqual(intake.find_pack_in_text(fold(sent))[1]["qa"], lang["qa"])

    def test_a_json_looking_piece_inside_a_text_pack_is_source_and_stays_exactly_as_written(self):
        code = 'DEMO = \'{"schema": "code.v1",   "id": "x"}\'\n\ndef register(api):\n    pass\n'
        text = S.text_pack(pid="wire_demo", source=code)
        [sent] = node_map("T.protectPackage(x)", [text])
        self.assertEqual(wire_text.decode(fold(sent)), text)


# ======================================================================================= the real route
class WireAppCase(AppCase):
    def setUp(self):
        S.reset_process_state(*PACK_IDS)
        boot.reset_for_tests()
        self.addCleanup(self._clean_process)
        super().setUp()

    def _clean_process(self):
        S.reset_process_state(*PACK_IDS)
        boot.reset_for_tests()

    def pm(self):
        return boot.manager_for(self.memory)

    def send(self, text):
        """How a message reaches the app: encoded by the page's rule (the Python twin of it, tested equal above)."""
        return self.ask(wire_text.encode(text))

    def install_through_chat(self, text):
        proposal = self.send(text)
        self.assertIn("هنوز چیزی نصب یا فعال نشده", proposal)
        self.assertEqual(self.pm().list(), [])                                  # nothing happened before the user's yes
        self.assertEqual(len(self.pm().pending()), 1)
        return self.ask("بله")


class RealRouteTests(WireAppCase):
    def test_without_the_encoding_the_real_route_cannot_read_a_text_pack(self):
        # The reason the encoding exists: this is what the core does to the plain text (kept as a tripwire - if the core ever
        # keeps its line breaks, this test says so and the encoding can be reconsidered).
        reply = self.ask(wire_pack())
        self.assertNotIn("هنوز چیزی نصب یا فعال نشده", reply)
        self.assertEqual(self.pm().pending(), [])

    def test_an_encoded_code_pack_is_proposed_installed_after_the_yes_and_behaves_as_written(self):
        done = self.install_through_chat(wire_pack())
        self.assertIn("نصب و فعال شد", done)
        self.assertEqual(self.ask("قیمت دلار چنده"), WIRE_ANSWER)               # the nested code, the blank line, the escapes: intact

    def test_the_code_file_on_disk_is_byte_for_byte_what_was_pasted(self):
        self.install_through_chat(wire_pack())
        installed = os.path.join(self.files, "data", "packs", "store", "wire_demo", "1", "files", "wire_demo", "main.py")
        with open(installed, encoding="utf-8", newline="") as handle:
            self.assertEqual(handle.read(), intake.find_pack_in_text(wire_pack())[1]["files"]["wire_demo/main.py"])

    def test_a_language_pack_through_the_chat(self):
        self.assertIn("نصب و فعال شد", self.install_through_chat(S.lang_pack(pid="wire_lang")))
        self.assertEqual(self.ask("پایتخت ایران کجاست؟"), "تهران")

    def test_words_before_the_pack_and_a_code_fence_around_it_do_not_matter(self):
        proposal = self.send("لطفاً این بسته را بررسی کن:\n\n```\n" + wire_pack() + "```\nممنون")
        self.assertIn("هنوز چیزی نصب یا فعال نشده", proposal)
        self.assertIn("نصب و فعال شد", self.ask("بله"))

    def test_windows_line_endings_are_fine(self):
        self.assertIn("هنوز چیزی نصب یا فعال نشده", self.send(wire_pack().replace("\n", "\r\n")))

    def test_a_no_declines_and_nothing_is_installed(self):
        self.send(wire_pack())
        self.assertIn("کنار گذاشتم", self.ask("نه"))
        self.assertEqual(self.pm().list(), [])
        self.assertEqual(self.pm().pending(), [])

    def test_a_pack_with_a_forbidden_import_is_still_refused_through_the_encoding(self):
        reply = self.send(S.text_pack(pid="wire_demo", source="import subprocess\n\ndef register(api):\n    pass\n"))
        self.assertIn("نپذیرفتم", reply)
        self.assertIn("subprocess", reply)
        self.assertEqual(self.pm().list(), [])

    def test_ordinary_messages_are_not_affected(self):
        self.assertIsInstance(self.ask("سلام"), str)
        self.assertIsInstance(self.ask("امروز  هوا\nخوب است"), str)

    def test_a_damaged_or_empty_encoded_message_is_answered_and_never_breaks_the_app(self):
        for text in (wire_text.MARK, wire_text.MARK + " ", wire_text.MARK + " \\q\\u12 \\", wire_text.MARK + " \\n\\n\\n", wire_text.MARK + "x"):
            with self.subTest(text=text):
                self.assertIsInstance(self.ask(text), str)
        self.assertEqual(self.pm().list(), [])


@needs_node
class PageEncodingReachesTheRealApp(WireAppCase):
    def sent_by_the_page(self, text):
        [sent] = node_map("T.protectPackage(x)", [text])
        return sent

    def test_a_text_pack_sent_the_way_the_page_sends_it_installs(self):
        proposal = self.ask(self.sent_by_the_page(wire_pack()))
        self.assertIn("هنوز چیزی نصب یا فعال نشده", proposal)
        self.assertIn("نصب و فعال شد", self.ask("بله"))
        self.assertEqual(self.ask("قیمت دلار چنده"), WIRE_ANSWER)

    def test_a_json_pack_sent_the_way_the_page_sends_it_installs(self):
        _schema, package = intake.find_pack_in_text(wire_pack("wire_json"))
        package = dict(package, schema="code.v1", version=1)
        text = "این بسته را بررسی کن:\n```json\n" + json.dumps(package, ensure_ascii=False, indent=4) + "\n```"
        proposal = self.ask(self.sent_by_the_page(text))
        self.assertIn("هنوز چیزی نصب یا فعال نشده", proposal)
        self.assertIn("نصب و فعال شد", self.ask("بله"))
        self.assertEqual(self.ask("قیمت دلار چنده"), WIRE_ANSWER)


if __name__ == "__main__":
    unittest.main()
