"""
Prompt 958 - the page's own buttons inside the Android app (speech, model file) and the text shared INTO the app.

  Contract    every name, feature, purpose, failure code, JSON key and limit the page uses is the one the Java side and the Python
              side really have (so a rename on one side cannot go unnoticed) - no browser and no Android needed
  Node        the DOM-free helpers of i18n.js (a size with Persian digits ...) - skipped without Node
  Real route  the two sentences the page sends BY ITSELF are understood by the real app (HTTP -> core -> brain -> hub / teacher), and
              they only open the assistant's own question: nothing is imported or installed before the user's «بله»
  Chromium    the real page with a hand-written stand-in for the Android bridge (`window.AndroidBridge`) and the four callbacks the
              activity calls: what appears, what is sent, what is NOT sent - skipped when Playwright / Chromium are not installed

NOT proven here: how the real WebView, Android's speech dialog, its document picker and its Share sheet behave on a phone. Those are
the Java side's job and can only be shown by installing the app (see docs/).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import platform_boot
from brain_hub import builtin_tools
from model_runtime import card as model_card
from native_bridge import facade as native_facade
from pack_system import boot, intake
from persian_brain import hub_messages_llm
from teacher import service as teacher_service
from tests import pack_support_prompt958 as S
from tests.native_support_prompt958 import FakeJava
from tests.persian_app_case_prompt957 import AppCase
from tests.test_android_files_prompt958 import code_only, java, _HAS_PROJECT

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(PY_ROOT, "interface", "static")
I18N = os.path.join(STATIC, "i18n.js")
needs_node = unittest.skipUnless(shutil.which("node"), "node is not installed")
BIDI = {c: None for c in range(0x2066, 0x206A)}
OWN = teacher_service.OWN_PACKAGE
CHATGPT, CLAUDE = "com.openai.chatgpt", "com.anthropic.claude"
TASK = b"PK\x03\x04 pretend this is a task bundle " * 50
PACK_IDS = ("page_demo", "fa_via_page")

# Indented, nested code: the case the chat's whitespace folding would destroy.
PAGE_SOURCE = '''VERSION = 1


def register(api):
    def match(ctx):
        if "قیمت دلار" in ctx.norm:
            if len(ctx.norm) > 3:
                return True
        return False

    def handle(ctx):
        return "پاسخ از بستهٔ صفحه"

    api.register_chat("page_demo", match, handle, stage="fallback")
'''
PAGE_ANSWER = "پاسخ از بستهٔ صفحه"


def read_static(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as handle:
        return handle.read()


def clean(text):
    return text.translate(BIDI)


def page_pack():
    return S.text_pack(pid="page_demo", source=PAGE_SOURCE)


def node_json(expression, *values):
    """Evaluates a JS expression with the page's i18n.js loaded as `T` and the arguments as `v` (parsed JSON); returns parsed JSON."""
    script = ("const T=require(process.argv[1]);const v=JSON.parse(process.argv[2]);const r=" + expression + ";"
              "process.stdout.write(JSON.stringify(r === undefined ? null : r));")
    out = subprocess.run(["node", "-e", script, I18N, json.dumps(list(values))], capture_output=True, encoding="utf-8", timeout=60)
    if out.returncode != 0:
        raise AssertionError("node failed: " + out.stderr)
    return json.loads(out.stdout)


def js_function_body(source, name):
    """The body of `window.<name> = function (json) { ... };` of app.js (the closing `};` is the one at two spaces of indentation)."""
    found = re.search(r"window\." + name + r" = function \(json\) \{(.*?)\n  \};", source, re.S)
    assert found, name
    return found.group(1)


def keys_read(body):
    return set(re.findall(r"\bdata\.(\w+)", body))


# ======================================================================================= the contract
@unittest.skipUnless(_HAS_PROJECT, "Gradle project files not present")
class ContractTests(unittest.TestCase):
    def setUp(self):
        self.js = read_static("app.js")
        self.i18n = read_static("i18n.js")
        self.html = read_static("index.html")
        self.main = code_only(java("MainActivity.java"))

    # ------------------------------------------------------------------------------------------ names
    def test_the_page_defines_exactly_the_callbacks_the_activity_calls(self):
        called = set(re.findall(r'tellPage\("(\w+)"', self.main))
        defined = set(re.findall(r"window\.(nativeOn\w+)\s*=\s*function", self.js))
        self.assertEqual(called, {"nativeOnFile", "nativeOnShared", "nativeOnVoice", "nativeOnProgress"})
        self.assertEqual(defined, called)

    def test_the_page_uses_the_bridge_and_the_methods_the_activity_exposes(self):
        self.assertIn('addJavascriptInterface(new NativeBridge(), "AndroidBridge")', self.main)
        self.assertIn("window.AndroidBridge", self.js)
        exposed = set(re.findall(r"@JavascriptInterface\s+public\s+\w+\s+(\w+)\(", self.main))
        used = set(re.findall(r'bridgeCall\("(\w+)"', self.js)) | {"features"}
        self.assertEqual(exposed, {"features", "pickFile", "startVoice"})
        self.assertLessEqual(used, exposed)
        self.assertIn("bridge.features", self.js)

    def test_the_features_the_page_waits_for_are_declared_by_the_activity(self):
        declared = set(re.findall(r'"([a-z_]+)"', re.search(r"NATIVE_FEATURES\s*=\s*\{([^}]*)\}", self.main).group(1)))
        waited = set(re.findall(r'features\.indexOf\("([a-z_]+)"\)', self.js))
        self.assertEqual(waited, {"voice_input", "file_pick"})
        self.assertLessEqual(waited, declared)

    def test_purposes_and_language_match(self):
        purposes = dict(re.findall(r'PURPOSE_(\w+)\s*=\s*"(\w+)"', self.main))
        self.assertEqual(purposes, {"MODEL": "model", "FILE": "file"})
        self.assertIn('bridgeCall("pickFile", "model")', self.js)
        self.assertIn('bridgeCall("startVoice", "fa-IR")', self.js)
        self.assertIn('return "fa-IR"', self.main)                                 # the activity's own default is the same language

    # ------------------------------------------------------------------------------------------ failure codes
    def test_every_failure_code_the_activity_reports_has_its_own_persian_message(self):
        codes = set(re.findall(r'fileResult\(false,\s*"(\w+)"', self.main))
        handled = set(re.findall(r"(\w+): \"pick\w+\"", re.search(r"var FILE_PROBLEMS = \{(.*?)\};", self.js, re.S).group(1))) | {"too_large"}
        self.assertEqual(codes - {"error"}, handled)                              # "error" is the generic message (pickFailed)
        strings = set(re.findall(r'(pick\w+):', self.i18n))
        for key in re.findall(r'"(pick(?!File)\w+)"', self.js):
            self.assertIn(key, strings, key)

    # ------------------------------------------------------------------------------------------ JSON keys
    def test_the_keys_the_page_reads_exist_on_the_senders_side(self):
        file_keys = set(re.findall(r'o\.put\("(\w+)"', re.search(r"private static String fileResult.*?\n    }\n", self.main, re.S).group(0)))
        progress_keys = set(re.findall(r'o\.put\("(\w+)"', re.search(r"private static String progressJson.*?\n    }\n", self.main, re.S).group(0)))
        voice_keys = set(re.findall(r'o\.put\("(\w+)"', re.search(r"private static String voiceJson.*?\n    }\n", self.main, re.S).group(0)))
        shared_keys = set(json.loads(platform_boot.on_shared_text("unused", "")))
        for callback, sender in (("nativeOnFile", file_keys), ("nativeOnProgress", progress_keys), ("nativeOnVoice", voice_keys),
                                 ("nativeOnShared", shared_keys)):
            with self.subTest(callback=callback):
                read = keys_read(js_function_body(self.js, callback))
                self.assertTrue(read)
                self.assertLessEqual(read, sender, "the page reads a key that its sender never writes")
        self.assertEqual(file_keys, {"ok", "code", "name", "size", "purpose"})
        self.assertEqual(shared_keys, {"ok", "code", "chars", "name", "truncated", "mission_open", "text"})

    # ------------------------------------------------------------------------------------------ limits
    def test_the_limits_agree_everywhere(self):
        attach = int(re.search(r"MAX_ATTACH_BYTES = (\d+)", self.js).group(1))
        self.assertEqual(platform_boot.MAX_OFFERED_CHARS, attach)                 # what Python offers = what the page accepts

        def product(constant):                                                    # "8L * 1024L * 1024L * 1024L" -> 8 GiB
            text = re.search(constant + r" = ([\dL *]+);", self.main).group(1)
            result = 1
            for part in text.split("*"):
                result *= int(part.strip().rstrip("L"))
            return result

        self.assertEqual(product("MAX_MODEL_BYTES"), 8 * 2 ** 30)
        self.assertEqual(product("MAX_MODEL_BYTES"), model_card.MAX_SIZE_BYTES)   # the model store's own ceiling
        self.assertEqual(product("MAX_OTHER_BYTES"), 64 * 2 ** 20)
        self.assertIn("۸ گیگابایت", re.search(r'pickTooLargeModel: "([^"]*)"', self.i18n).group(1))
        self.assertIn("۶۴ مگابایت", re.search(r'pickTooLargeFile: "([^"]*)"', self.i18n).group(1))
        self.assertEqual(re.search(r"MAX_NAME_CHARS = (\d+)", self.main).group(1), "100")          # the activity's name length = the page's rule

    def test_the_model_name_the_page_accepts_is_what_the_inbox_and_the_activity_produce(self):
        literal = re.search(r"MODEL_NAME_RE = /(.*)/i;", self.js).group(1)
        rule = re.compile(literal, re.I | re.A)                                   # JavaScript's /i without the u flag: ASCII case folding
        inbox = builtin_tools._FILE_NAME_RE
        good = ["gemma.task", "gemma-2b-it_gpu.int4.task", "m.gguf", "A1.TASK", "a" * 95 + ".task", "a" * 95 + ".gguf"]       # 100 characters in all
        bad = ["", ".task", "gemma", "gemma.txt", "gemma task.task", "../x.task", "x.task ", "x.task\n", "\nx.task", "a" * 96 + ".task",
               "a" * 96 + ".gguf", "a" * 100 + ".task", "x.task.json", "x.json", "x.tas", "-x.task", "_x.task"]
        for name in good:
            with self.subTest(good=name[:20]):
                self.assertTrue(rule.fullmatch(name))
                self.assertTrue(inbox.match(name))                                # the assistant's own inbox takes the name too
        for name in bad:
            with self.subTest(bad=name[:20]):
                self.assertFalse(rule.fullmatch(name))
        for name in good + bad:                                                   # never wider than the inbox
            if rule.fullmatch(name):
                self.assertTrue(inbox.match(name), name)

    # ------------------------------------------------------------------------------------------ markup
    def test_the_markup_has_the_bar_hidden_until_the_app_says_otherwise(self):
        for ident in ("native-bar", "voice-btn", "model-btn"):
            self.assertRegex(self.html, r'<[a-z]+ [^>]*id="%s"[^>]*\bhidden\b' % ident)
        self.assertLess(self.html.index('id="messages"'), self.html.index('id="native-bar"'))
        self.assertLess(self.html.index('id="native-bar"'), self.html.index('id="input-form"'))
        self.assertNotIn('id="native-bar"', self.html[self.html.index('id="input-form"'):])      # outside the composer: its layout is untouched

    def test_the_labels_in_the_markup_are_the_strings_of_the_string_table(self):
        for ident, key in (("voice-btn", "voiceButton"), ("model-btn", "modelButton")):
            label = re.search(r'id="%s"[^>]*>([^<]*)<' % ident, self.html).group(1)
            self.assertEqual(label, re.search(r'%s: "([^"]*)"' % key, self.i18n).group(1))
        self.assertIn('aria-label="%s"' % re.search(r'voiceLabel: "([^"]*)"', self.i18n).group(1), self.html)
        self.assertIn('aria-label="%s"' % re.search(r'modelLabel: "([^"]*)"', self.i18n).group(1), self.html)

    def test_the_assistants_own_instructions_name_the_pages_button(self):
        label = re.search(r'modelButton: "([^"]*)"', self.i18n).group(1)
        self.assertEqual(label, "📦 فایل مدل")
        self.assertIn("«%s»" % label, hub_messages_llm.import_how())
        self.assertIn("«%s»" % label, hub_messages_llm.import_missing("x.task", []))

    def test_the_page_never_runs_text_it_receives(self):
        for name in ("app.js", "i18n.js"):
            source = read_static(name)
            for banned in ("eval(", "new Function", "innerHTML = text", "document.write", "setTimeout(\"", "setInterval(\""):
                self.assertNotIn(banned, source, name)
        body = " ".join(js_function_body(self.js, n) for n in ("nativeOnVoice", "nativeOnShared", "nativeOnProgress", "nativeOnFile"))
        self.assertNotIn("innerHTML", body)                                        # notes and the box are filled with text only


# ======================================================================================= Node
@needs_node
class DomFreeHelpers(unittest.TestCase):
    def test_sizes_are_written_with_persian_digits_and_units(self):
        cases = ((0, "۰ بایت"), (1023, "۱۰۲۳ بایت"), (1024, "۱٫۰ کیلوبایت"), (1536, "۱٫۵ کیلوبایت"), (1048576, "۱٫۰ مگابایت"),
                 (250 * 2 ** 20, "۲۵۰ مگابایت"), (int(1.2 * 2 ** 30), "۱٫۲ گیگابایت"), (4 * 2 ** 30, "۴٫۰ گیگابایت"), (8 * 2 ** 30, "۸٫۰ گیگابایت"))
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(node_json("T.formatBytes(v[0])", value), expected)

    def test_a_bad_size_is_zero_bytes_never_nan(self):
        for bad in ("null", "undefined", "'12'", "NaN", "-5", "Infinity"):
            with self.subTest(value=bad):
                self.assertEqual(node_json("T.formatBytes(" + bad + ")"), "۰ بایت")

    def test_plain_text_is_put_in_as_it_is_while_names_are_isolated_and_numbers_get_persian_digits(self):
        out = node_json("T.fillTemplate('{a} / {b} / {c} / {d}', {a: T.plain(T.formatBytes(2048)), b: 12, c: 'gemma.task'})")
        self.assertEqual(clean(out), "۲٫۰ کیلوبایت / ۱۲ / gemma.task / {d}")
        self.assertIn(chr(0x2066) + "gemma.task" + chr(0x2069), out)               # a name is isolated left-to-right, plain text is not

    def test_every_new_string_exists_and_is_persian(self):
        strings = node_json("T.STR")
        keys = ("nativeBarLabel", "voiceButton", "voiceLabel", "modelButton", "modelLabel", "voiceUnavailable", "voiceHeard", "voiceNothing",
                "pickUnavailable", "copyProgress", "copyProgressUnknown", "modelCopied", "fileCopied", "importCommand", "pickCancelled",
                "pickBusy", "pickUnsupported", "pickTooLargeModel", "pickTooLargeFile", "pickNoSpace", "pickUnreadable", "pickIoError",
                "pickSizeMismatch", "pickEmpty", "pickNoInbox", "pickFailed", "answerCame", "sharedMission", "sharedReady", "sharedTooLong",
                "sharedCut", "sharedNotText", "sharedEmpty", "sharedFailed")
        for key in keys:
            with self.subTest(key=key):
                self.assertIn(key, strings)
                self.assertRegex(strings[key], "[%s-%s]" % (chr(0x600), chr(0x6ff)))             # Persian text
                self.assertNotRegex(re.sub(r"\{\w+\}|\.task|\.gguf", "", strings[key]), r"[A-Za-z]{2,}")      # no English words in a note

    def test_the_two_automatic_sentences(self):
        self.assertEqual(node_json("T.STR.answerCame"), "جواب آمد")
        self.assertEqual(node_json("T.STR.importCommand.replace('{name}', 'gemma-test.task')"), "مدل gemma-test.task را وارد کن")


# ======================================================================================= the real app
class NativeAppCase(AppCase):
    """The real app (HTTP -> core -> brain -> hub / teacher) with a fake Android under the teacher's native doors."""

    def setUp(self):
        S.reset_process_state(*PACK_IDS)
        boot.reset_for_tests()
        native_facade.reset_for_tests()
        teacher_service.reset_for_tests()
        self.addCleanup(self._clean_process)
        self.jvm = FakeJava(installed={CHATGPT, CLAUDE, OWN}, package=CHATGPT)
        native_facade.set_jvm(self.jvm)
        super().setUp()

    def _clean_process(self):
        S.reset_process_state(*PACK_IDS)
        boot.reset_for_tests()
        native_facade.reset_for_tests()
        teacher_service.reset_for_tests()

    def pm(self):
        return boot.manager_for(self.memory)

    def inbox(self):
        return self.hub.inbox_dir(create=True)

    def stage_model(self, name="gemma-test.task"):
        with open(os.path.join(self.inbox(), name), "wb") as handle:
            handle.write(TASK)
        return name

    def open_request(self):
        """The user asked an assistant app for something and said «بله»: the request now waits for its answer."""
        question = self.ask("از ChatGPT بخواه یه قابلیت ساخت عکس برام بسازه")
        self.assertIn("بفرستم؟ (بله / نه)", question)
        self.assertIn("اشتراک‌گذاری", self.ask("بله"))

    def share(self, text):
        """What the activity does when another app shares `text` into this one; returns the JSON the page receives."""
        return platform_boot.on_shared_text(self.files, text, clock=self.clock)      # the teacher's clock is the app's (fake) clock here


@needs_node
class SentencesTheRealAppUnderstands(NativeAppCase):
    def test_the_import_sentence_opens_the_assistants_own_question_and_nothing_else(self):
        name = self.stage_model()
        sentence = node_json("T.STR.importCommand.replace('{name}', v[0])", name)
        reply = clean(self.ask(sentence))
        for word in (name, "وارد کنم؟", "بله / نه", "SHA-256"):
            self.assertIn(word, reply)
        self.assertEqual(self.hub.list_models(), [])                                # nothing imported before the user's own yes
        self.assertTrue(os.path.exists(os.path.join(self.inbox(), name)))            # and the file was neither read nor moved
        self.assertIn("چیزی تغییر نکرد", clean(self.ask("نه")))
        self.assertEqual(self.hub.list_models(), [])

    def test_the_answer_sentence_reads_the_shared_text_and_only_proposes_what_it_holds(self):
        self.open_request()
        out = json.loads(self.share(S.lang_pack(pid="fa_via_page")))
        self.assertEqual((out["ok"], out["mission_open"], out["text"]), (True, True, ""))
        reply = self.ask(node_json("T.STR.answerCame"))
        self.assertIn("از متنی که به این برنامه اشتراک‌گذاری کردی", reply)
        self.assertIn("هنوز چیزی نصب یا فعال نشده", reply)
        self.assertEqual(self.pm().list(), [])                                       # a shared answer is reviewed, never installed by itself
        self.assertIn("نصب و فعال شد", self.ask("بله"))
        self.assertEqual(self.ask("پایتخت ایران کجاست؟"), "تهران")

    def test_without_a_waiting_request_the_answer_sentence_installs_nothing_and_says_what_to_do(self):
        out = json.loads(self.share(S.lang_pack(pid="fa_via_page")))
        self.assertEqual(out["mission_open"], False)
        reply = self.ask(node_json("T.STR.answerCame"))
        self.assertNotIn("هنوز چیزی نصب یا فعال نشده", reply)
        self.assertEqual(self.pm().list(), [])
        self.assertEqual(self.pm().pending(), [])


# ======================================================================================= Chromium
try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
    _PW = True
except Exception:  # noqa: BLE001
    _PW = False

FALLBACK_FEATURES = ["file_chooser", "permission_request", "voice_input", "accessibility", "share_target", "file_pick"]


def activity_features():
    """The list the activity's features() answers with - read from its own source when the Gradle project is present."""
    if _HAS_PROJECT:
        found = re.search(r"NATIVE_FEATURES\s*=\s*\{([^}]*)\}", code_only(java("MainActivity.java")))
        if found:
            return re.findall(r'"([a-z_]+)"', found.group(1))
    return list(FALLBACK_FEATURES)


# A stand-in for the activity's `window.AndroidBridge`, installed BEFORE the page's own scripts run. It only records what the
# page asks of it (the real one opens Android's speech dialog and document picker); `window.__calls` is that record.
BRIDGE_JS = """(function (cfg) {
  window.__calls = [];
  if (!cfg.present) { return; }
  var bridge = {};
  if (cfg.hasFeatures) {
    bridge.features = function () {
      window.__calls.push(["features"]);
      if (cfg.featuresThrows) { throw new Error("the app cannot tell"); }
      return cfg.features;
    };
  }
  if (cfg.hasVoice) {
    bridge.startVoice = function (language) { window.__calls.push(["startVoice", language]); return cfg.voice; };
  }
  if (cfg.hasPick) {
    bridge.pickFile = function (purpose) { window.__calls.push(["pickFile", purpose]); return cfg.pick; };
  }
  window.AndroidBridge = bridge;
})(__CONFIG__);"""


def bridge_script(present=True, features=None, features_throws=False, has_features=True, has_voice=True, has_pick=True,
                  voice=True, pick=True):
    """`features`: None = the activity's own list; a list = that list; a str = exactly that text (to try junk answers)."""
    answer = features if isinstance(features, str) else json.dumps(features if features is not None else activity_features())
    config = {"present": present, "features": answer, "featuresThrows": features_throws, "hasFeatures": has_features,
              "hasVoice": has_voice, "hasPick": has_pick, "voice": voice, "pick": pick}
    return BRIDGE_JS.replace("__CONFIG__", json.dumps(config))


@unittest.skipUnless(_PW, "Playwright is not installed")
class NativePageInChromium(NativeAppCase):
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

    # ------------------------------------------------------------------ helpers
    def page(self, w=360, h=740, **bridge):
        ctx = self._browser.new_context(viewport={"width": w, "height": h}, is_mobile=True, has_touch=True, locale="fa-IR")
        self.addCleanup(ctx.close)
        ctx.add_init_script(bridge_script(**bridge))
        pg = ctx.new_page()
        errors, sent = [], []
        self.errors, self.sent = errors, sent                                       # what THIS page showed as errors / sent to the app
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("request", lambda r: sent.append(json.loads(r.post_data)["text"])
              if r.url.endswith("/api/message") and r.method == "POST" else None)
        pg.goto(self.url + "/")
        pg.wait_for_selector("#status-dot.dot-live", timeout=10000)
        return pg

    def tell(self, pg, callback, payload):
        """What the activity does: window.<callback>(ONE json text)."""
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        pg.evaluate("([name, text]) => window[name](text)", [callback, text])

    def note(self, pg):
        return clean(pg.inner_text("#attach-note")) if pg.is_visible("#attach-note") else ""

    def last_reply(self, pg):
        return clean(pg.inner_text(".message.assistant:not(.typing) >> nth=-1"))

    def settle(self, pg, posts, timeout_s=60):
        """Waits until the page has sent `posts` messages in all and is idle again; returns the newest answer."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            idle = pg.evaluate("!document.querySelector('.message.typing') && !document.getElementById('send-btn').disabled")
            if len(self.sent) >= posts and idle:
                break
            pg.wait_for_timeout(50)
        self.assertEqual(len(self.sent), posts)
        return self.last_reply(pg)

    def say(self, pg, text, posts):
        """The user types `text` and presses send; `posts` is how many messages the page has sent after this one."""
        pg.fill("#input-box", text)
        pg.click("#send-btn")
        return self.settle(pg, posts)

    def box(self, pg, selector):
        return pg.locator(selector).bounding_box()

    def hold_messages(self, pg):
        """Keeps every POST /api/message of the page on hold until `release` lets it go. (The handler only stores the request: a
        handler that sleeps would still be running when a failing test closes its page, and that breaks the shared browser.)"""
        held = []
        pg.route("**/api/message", lambda route: held.append(route))
        return held

    def release(self, pg, held, timeout_s=30):
        """Lets the oldest held request through (waits until there is one)."""
        deadline = time.time() + timeout_s
        while not held and time.time() < deadline:
            pg.wait_for_timeout(20)
        self.assertTrue(held, "the page has no request waiting to be released")
        held.pop(0).continue_()

    # ------------------------------------------------------------------ the bar and the bridge
    def test_in_an_ordinary_browser_the_bar_stays_hidden_and_nothing_runs(self):
        pg = self.page(present=False)
        self.assertEqual(pg.evaluate("typeof window.AndroidBridge"), "undefined")
        for selector in ("#native-bar", "#voice-btn", "#model-btn"):
            self.assertTrue(pg.is_hidden(selector), selector)
        self.assertEqual(self.errors, [])
        self.assertEqual(self.sent, [])

    def test_with_the_activitys_own_feature_list_both_buttons_show_between_the_messages_and_the_box(self):
        pg = self.page()
        self.assertEqual(self.errors, [])
        self.assertTrue(pg.is_visible("#native-bar"))
        self.assertEqual(pg.inner_text("#voice-btn"), "🎤 گفتار")
        self.assertEqual(pg.inner_text("#model-btn"), "📦 فایل مدل")
        self.assertEqual(pg.evaluate("window.__calls"), [["features"]])             # asked once when the page loads, never polled
        top, mid, bar, form = (self.box(pg, s) for s in (".app-header", "#messages", "#native-bar", "#input-form"))
        self.assertLessEqual(top["y"] + top["height"], mid["y"] + 1)                # header -> messages -> bar -> composer
        self.assertLessEqual(mid["y"] + mid["height"], bar["y"] + 1)
        self.assertLessEqual(bar["y"] + bar["height"], form["y"] + 1)
        for selector in ("#voice-btn", "#model-btn"):
            box = self.box(pg, selector)
            self.assertGreaterEqual(box["height"], 44, selector)                    # a finger-sized target
            self.assertGreaterEqual(box["width"], 44, selector)

    def test_only_the_buttons_the_app_can_serve_are_shown(self):
        cases = ((["voice_input"], True, False), (["file_pick"], False, True), (["voice_input", "file_pick"], True, True),
                 (["file_chooser", "accessibility", "share_target"], False, False), ([], False, False))
        for features, voice, model in cases:
            with self.subTest(features=features):
                pg = self.page(features=features)
                self.assertEqual(pg.is_visible("#voice-btn"), voice)
                self.assertEqual(pg.is_visible("#model-btn"), model)
                self.assertEqual(pg.is_visible("#native-bar"), voice or model)
                self.assertEqual(self.errors, [])

    def test_a_bridge_that_answers_badly_shows_nothing_and_breaks_nothing(self):
        for answer in ("not json at all", "{}", "null", '"voice_input"', "[1, 2]", "", '{"voice_input": true}'):
            with self.subTest(answer=answer):
                pg = self.page(features=answer)
                self.assertTrue(pg.is_hidden("#native-bar"))
                self.assertEqual(self.errors, [])
        pg = self.page(features_throws=True)                                        # the app throws when asked
        self.assertTrue(pg.is_hidden("#native-bar"))
        self.assertEqual(self.errors, [])
        pg = self.page(has_features=False)                                          # an old app: a bridge that cannot even be asked
        self.assertTrue(pg.is_hidden("#native-bar"))
        self.assertEqual(self.errors, [])

    # ------------------------------------------------------------------ the two buttons
    def test_a_tap_asks_the_app_for_one_dialog_with_the_right_arguments_and_sends_nothing(self):
        pg = self.page()
        pg.click("#voice-btn")
        pg.click("#model-btn")
        self.assertEqual(pg.evaluate("window.__calls"), [["features"], ["startVoice", "fa-IR"], ["pickFile", "model"]])
        self.assertEqual(self.note(pg), "")                                         # the dialog opened: nothing to explain
        pg.wait_for_timeout(300)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.errors, [])

    def test_when_the_app_cannot_open_the_dialog_the_page_says_so(self):
        pg = self.page(voice=False, pick=False)
        pg.click("#voice-btn")
        self.assertIn("گفتار روی این گوشی یا در این لحظه در دسترس نیست", self.note(pg))
        pg.click("#model-btn")
        self.assertIn("پنجرهٔ انتخابِ فایل باز نشد", self.note(pg))
        self.assertNotIn("گفتار", self.note(pg))                                    # one line: the new note replaces the old one
        self.assertEqual(self.sent, [])
        self.assertEqual(self.errors, [])
        pg = self.page(has_voice=False, has_pick=False)                             # the list names them, the methods are missing
        pg.click("#voice-btn")
        self.assertIn("در دسترس نیست", self.note(pg))
        pg.click("#model-btn")
        self.assertIn("باز نشد", self.note(pg))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.errors, [])

    # ------------------------------------------------------------------ speech
    def test_what_is_heard_goes_into_the_box_after_what_is_typed_and_is_never_sent(self):
        pg = self.page()
        self.tell(pg, "nativeOnVoice", {"ok": True, "text": "سلام دنیا"})
        self.assertEqual(pg.input_value("#input-box"), "سلام دنیا")
        self.assertIn("(۹ نویسه)", self.note(pg))
        self.assertIn("هنوز چیزی فرستاده نشده", self.note(pg))
        self.tell(pg, "nativeOnVoice", {"ok": True, "text": "  خوبی؟  "})
        self.assertEqual(pg.input_value("#input-box"), "سلام دنیا خوبی؟")             # one space between; the heard text is trimmed
        pg.fill("#input-box", "پیش‌نویس من")
        self.tell(pg, "nativeOnVoice", {"ok": True, "text": "ادامه"})
        self.assertEqual(pg.input_value("#input-box"), "پیش‌نویس من ادامه")
        pg.wait_for_timeout(300)
        self.assertEqual(self.sent, [])
        self.assertIsNone(pg.query_selector(".message.user"))
        self.assertEqual(self.errors, [])

    def test_nothing_heard_or_unusable_text_changes_nothing(self):
        pg = self.page()
        pg.fill("#input-box", "قبلی")
        bad = [{"ok": False, "text": ""}, {"ok": True, "text": "   "}, {"ok": True, "text": "a" + chr(0xFFFD) + "b"},
               {"ok": True, "text": "a" + chr(0) + "b"}, {"ok": True}, {"ok": False, "text": "گفته شد ولی ok نیست"},
               "not json", "null", "[]", "7", ""]
        for payload in bad:
            with self.subTest(payload=str(payload)[:30]):
                self.tell(pg, "nativeOnVoice", payload)
                self.assertIn("چیزی شنیده نشد", self.note(pg))
                self.assertEqual(pg.input_value("#input-box"), "قبلی")
        pg.wait_for_timeout(200)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.errors, [])

    def test_heard_text_that_looks_like_markup_stays_plain_text(self):
        pg = self.page()
        hostile = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script>'
        self.tell(pg, "nativeOnVoice", {"ok": True, "text": hostile})
        self.assertEqual(pg.input_value("#input-box"), hostile)
        pg.click("#send-btn")
        self.settle(pg, 1)
        self.assertEqual(self.sent, [hostile])
        self.assertTrue(pg.evaluate("window.__pwned === undefined"))
        self.assertEqual(pg.evaluate("document.querySelectorAll('#messages img, #messages script, #attach-note img').length"), 0)
        self.assertIn("<img", pg.inner_text(".message.user .bubble"))               # shown as the letters it is made of
        self.assertEqual(self.errors, [])

    # ------------------------------------------------------------------ copying a file
    def test_copy_progress_has_persian_digits_a_percent_and_never_says_done(self):
        pg = self.page()
        self.tell(pg, "nativeOnProgress", {"name": "gemma-test.task", "copied": 524288000, "total": 1048576000})
        note = self.note(pg)
        self.assertIn("در حال کپیِ «gemma-test.task» از گوشی", note)
        self.assertIn("۵۰۰ مگابایت از ۱۰۰۰ مگابایت (۵۰٪)", note)
        self.tell(pg, "nativeOnProgress", {"name": "m.gguf", "copied": 2000, "total": 1000})      # never more than 99 before the end
        self.assertIn("(۹۹٪)", self.note(pg))
        self.tell(pg, "nativeOnProgress", {"name": "m.gguf", "copied": 3 * 2 ** 30, "total": 0})   # the size is not known
        note = self.note(pg)
        self.assertIn("۳٫۰ گیگابایت کپی شد", note)
        self.assertNotIn("٪", note)
        self.tell(pg, "nativeOnProgress", "junk")                                    # junk changes nothing
        self.assertEqual(self.note(pg), note)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.errors, [])

    def test_a_copied_model_file_asks_the_assistants_own_question_and_imports_nothing(self):
        name = self.stage_model()
        pg = self.page()
        self.tell(pg, "nativeOnFile", {"ok": True, "code": "copied", "name": name, "size": len(TASK), "purpose": "model"})
        reply = self.settle(pg, 1)
        self.assertEqual(self.sent, ["مدل %s را وارد کن" % name])
        for word in ("وارد کنم؟", "بله / نه", "SHA-256"):
            self.assertIn(word, reply)
        note = self.note(pg)
        self.assertIn("از گوشی کپی شد", note)
        self.assertIn("بدون «بله»ی خودت چیزی وارد نمی‌شود", note)
        self.assertEqual(self.hub.list_models(), [])                                # a question only: nothing is imported before the user's own yes
        self.assertTrue(os.path.exists(os.path.join(self.inbox(), name)))
        self.assertIn(name, clean(pg.inner_text(".message.user >> nth=-1")))        # the user can SEE what was sent on his behalf
        self.assertIn("فایل وارد شد", self.say(pg, "بله", 2))                       # the yes is the user's own, typed in the page
        self.assertEqual([m.model_id for m in self.hub.list_models()], ["gemma-test"])
        self.assertEqual(self.errors, [])

    def test_a_declined_import_leaves_everything_as_it_was(self):
        name = self.stage_model()
        pg = self.page()
        self.tell(pg, "nativeOnFile", {"ok": True, "code": "copied", "name": name, "size": len(TASK), "purpose": "model"})
        self.settle(pg, 1)
        self.assertIn("چیزی تغییر نکرد", self.say(pg, "نه", 2))
        self.assertEqual(self.hub.list_models(), [])
        self.assertTrue(os.path.exists(os.path.join(self.inbox(), name)))
        self.assertEqual(self.errors, [])

    def test_a_model_name_the_page_would_not_pass_on_is_never_sent(self):
        pg = self.page()
        names = ["evil name.task", "../x.task", "x.txt", "", ".task", "x.task\n", "a" * 96 + ".gguf", "مدل.task", "x.task.json", "-x.task"]
        for name in names:
            with self.subTest(name=name[:20]):
                self.tell(pg, "nativeOnFile", {"ok": True, "code": "copied", "name": name, "size": 10, "purpose": "model"})
                self.assertIn("در پوشهٔ ورودیِ برنامه گذاشته شد", self.note(pg))
                self.assertNotIn("می‌پرسد", self.note(pg))
        for purpose in ("file", "zzz", None):                                        # a model name for another purpose is only saved
            with self.subTest(purpose=purpose):
                payload = {"ok": True, "code": "copied", "name": "gemma.task", "size": 10}
                if purpose is not None:
                    payload["purpose"] = purpose
                self.tell(pg, "nativeOnFile", payload)
                self.assertIn("در پوشهٔ ورودیِ برنامه گذاشته شد", self.note(pg))
        pg.wait_for_timeout(300)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.errors, [])

    def test_upper_case_model_names_are_passed_on_exactly_as_they_are(self):
        pg = self.page()
        name = self.stage_model("Model-A1.TASK")
        self.tell(pg, "nativeOnFile", {"ok": True, "code": "copied", "name": name, "size": len(TASK), "purpose": "model"})
        reply = self.settle(pg, 1)
        self.assertEqual(self.sent, ["مدل Model-A1.TASK را وارد کن"])
        self.assertIn("وارد کنم؟", reply)
        self.assertEqual(self.hub.list_models(), [])

    def test_every_failure_has_its_own_note_and_sends_nothing(self):
        pg = self.page()
        expected = {"cancelled": "لغو شد", "busy": "هنوز ادامه دارد", "unsupported_type": "فایل مدلِ زبانی نیست",
                    "no_space": "جای خالیِ کافی", "unreadable": "اندروید دسترسی نداد", "io_error": "هنگام کپی خطا رخ داد",
                    "size_mismatch": "یکی نبود", "empty": "فایل خالی بود", "no_inbox": "ساخته نشد",
                    "error": "ناموفق بود", "zzz": "ناموفق بود", None: "ناموفق بود"}
        notes = {}
        for code, phrase in expected.items():
            with self.subTest(code=code):
                payload = {"ok": False, "name": "x.task", "size": 0, "purpose": "model"}
                if code is not None:
                    payload["code"] = code
                self.tell(pg, "nativeOnFile", payload)
                notes[code] = self.note(pg)
                self.assertIn(phrase, notes[code])
        self.assertEqual(len({notes[c] for c in expected if c not in ("error", "zzz", None)}), 9)      # nine different problems, nine different notes
        self.tell(pg, "nativeOnFile", {"ok": False, "code": "too_large", "name": "x.task", "purpose": "model"})
        self.assertIn("۸ گیگابایت", self.note(pg))
        self.tell(pg, "nativeOnFile", {"ok": False, "code": "too_large", "name": "x.pdf", "purpose": "file"})
        self.assertIn("۶۴ مگابایت", self.note(pg))
        self.assertEqual(pg.input_value("#input-box"), "")
        pg.wait_for_timeout(300)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.errors, [])

    def test_a_file_name_that_looks_like_markup_is_shown_as_text(self):
        pg = self.page()
        name = '<b onmouseover="window.__pwned=1">x</b>.txt'
        self.tell(pg, "nativeOnFile", {"ok": True, "code": "copied", "name": name, "size": 10, "purpose": "file"})
        self.assertIn(name, self.note(pg))
        self.assertEqual(pg.evaluate("document.querySelectorAll('#attach-note b').length"), 0)
        self.assertTrue(pg.evaluate("window.__pwned === undefined"))
        self.assertEqual(self.sent, [])

    def test_junk_from_the_app_is_ignored_or_called_a_failure_never_an_error(self):
        pg = self.page()
        for callback in ("nativeOnFile", "nativeOnProgress", "nativeOnVoice", "nativeOnShared"):
            for junk in ("not json", "null", "[]", "5", "", "{}", '{"ok": true}', '{"ok": "yes", "name": 5, "size": "big"}'):
                with self.subTest(callback=callback, junk=junk):
                    self.tell(pg, callback, junk)
        pg.wait_for_timeout(300)
        self.assertEqual(self.sent, [])
        self.assertEqual(pg.input_value("#input-box"), "")
        self.assertEqual(self.errors, [])

    # ------------------------------------------------------------------ text shared into the app
    def test_a_shared_pack_goes_into_the_box_waits_for_send_and_installs_only_after_yes(self):
        pg = self.page()
        out = self.share(S.lang_pack(pid="fa_via_page"))
        offered = json.loads(out)
        self.assertEqual((offered["ok"], offered["mission_open"]), (True, False))
        self.tell(pg, "nativeOnShared", out)
        self.assertEqual(pg.input_value("#input-box"), offered["text"])
        self.assertIn("در کادر پیام گذاشته شد", self.note(pg))
        pg.wait_for_timeout(300)
        self.assertEqual(self.sent, [])                                             # shared text only FILLS the box
        pg.click("#send-btn")
        proposal = self.settle(pg, 1)
        [wire] = self.sent
        self.assertTrue(wire.startswith("=== ESCAPED TEXT v1 ==="))                  # the page protected the lines from the chat's folding
        self.assertNotIn("\n", wire)
        self.assertIn("هنوز چیزی نصب یا فعال نشده", proposal)
        self.assertEqual(self.pm().list(), [])
        self.assertIn("نصب و فعال شد", self.say(pg, "بله", 2))
        self.assertEqual(self.say(pg, "پایتخت ایران کجاست؟", 3), "تهران")
        self.assertEqual(self.errors, [])

    def test_a_shared_code_pack_keeps_its_indentation_all_the_way_to_the_running_code(self):
        pg = self.page()
        self.tell(pg, "nativeOnShared", self.share(page_pack()))
        pg.click("#send-btn")
        self.assertIn("هنوز چیزی نصب یا فعال نشده", self.settle(pg, 1))
        self.assertIn("نصب و فعال شد", self.say(pg, "بله", 2))
        self.assertEqual(self.say(pg, "قیمت دلار چنده", 3), PAGE_ANSWER)
        self.assertEqual(self.errors, [])

    def test_a_text_shared_while_a_request_waits_sends_the_one_fixed_sentence_and_only_proposes(self):
        self.open_request()
        pg = self.page()
        out = self.share(S.lang_pack(pid="fa_via_page"))
        self.assertTrue(json.loads(out)["mission_open"])
        self.tell(pg, "nativeOnShared", out)
        reply = self.settle(pg, 1)
        self.assertEqual(self.sent, ["جواب آمد"])
        self.assertEqual(pg.input_value("#input-box"), "")
        self.assertIn("چون درخواستی منتظرِ جواب بود", self.note(pg))
        self.assertIn("از متنی که به این برنامه اشتراک‌گذاری کردی", reply)
        self.assertIn("هنوز چیزی نصب یا فعال نشده", reply)
        self.assertEqual(self.pm().list(), [])
        self.assertIn("نصب و فعال شد", self.say(pg, "بله", 2))
        self.assertEqual(self.say(pg, "پایتخت ایران کجاست؟", 3), "تهران")
        self.assertEqual(self.errors, [])

    def test_a_shared_text_that_cannot_be_offered_says_why_and_puts_nothing_in_the_box(self):
        pg = self.page()
        long_text = {"ok": True, "chars": 300000, "truncated": False, "mission_open": False, "text": ""}
        cut_text = {"ok": True, "chars": 900000, "truncated": True, "mission_open": False, "text": ""}
        odd_text = {"ok": True, "chars": 3, "truncated": False, "mission_open": False, "text": "a" + chr(0xFFFD) + "b"}
        cases = [({"ok": False, "code": "empty"}, "متنِ فرستاده‌شده خالی بود"),
                 ({"ok": False, "code": "error"}, "ذخیرهٔ متنِ فرستاده‌شده ناموفق بود"),
                 ({"ok": False}, "ذخیرهٔ متنِ فرستاده‌شده ناموفق بود"),
                 (long_text, "(۳۰۰۰۰۰ نویسه) برای کادر پیام زیادی بلند است"),
                 (cut_text, "(۹۰۰۰۰۰ نویسه) و فقط بخشِ اولش ذخیره شد"),
                 (odd_text, "نویسهٔ نامعتبر داشت")]
        for payload, phrase in cases:
            with self.subTest(phrase=phrase):
                self.tell(pg, "nativeOnShared", payload)
                self.assertIn(phrase, self.note(pg))
                self.assertEqual(pg.input_value("#input-box"), "")
        before = self.note(pg)
        for junk in ("not json", "null", "5", "", "true"):                           # not an object at all: ignored, the note stays
            self.tell(pg, "nativeOnShared", junk)
            self.assertEqual(self.note(pg), before)
        pg.wait_for_timeout(300)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.errors, [])

    def test_a_really_too_long_share_is_saved_but_not_offered_to_the_box(self):
        pg = self.page()
        out = self.share("ب" * (platform_boot.MAX_OFFERED_CHARS + 1))
        self.assertEqual(json.loads(out)["text"], "")
        self.tell(pg, "nativeOnShared", out)
        self.assertIn("برای کادر پیام زیادی بلند است", self.note(pg))
        self.assertEqual(pg.input_value("#input-box"), "")
        self.assertEqual(self.sent, [])

    def test_shared_text_comes_after_what_the_user_has_already_typed_with_a_blank_line_between(self):
        pg = self.page()
        pg.fill("#input-box", "قبلی")
        self.tell(pg, "nativeOnShared", self.share("متن دوم"))
        self.assertEqual(pg.input_value("#input-box"), "قبلی\n\nمتن دوم")
        self.assertEqual(self.sent, [])

    # ------------------------------------------------------------------ while a message is on its way
    def test_while_a_message_is_on_its_way_the_buttons_rest_and_a_model_file_waits_its_turn(self):
        name = self.stage_model()
        pg = self.page()
        held = self.hold_messages(pg)
        pg.fill("#input-box", "سلام")
        pg.click("#send-btn")
        pg.wait_for_selector(".message.typing", timeout=5000)
        self.assertTrue(pg.is_disabled("#voice-btn"))
        self.assertTrue(pg.is_disabled("#model-btn"))
        self.tell(pg, "nativeOnFile", {"ok": True, "code": "copied", "name": name, "size": len(TASK), "purpose": "model"})
        self.tell(pg, "nativeOnVoice", {"ok": True, "text": "گفتهٔ من"})
        self.assertEqual(pg.input_value("#input-box"), "گفتهٔ من")                  # the box is the user's: filled even now, never sent
        pg.wait_for_timeout(300)
        self.assertEqual(self.sent, ["سلام"])                                       # the model sentence waits: one message on its way at a time
        self.release(pg, held)                                                      # the first answer comes ...
        self.release(pg, held)                                                      # ... and only then the waiting sentence goes out
        reply = self.settle(pg, 2)
        self.assertEqual(self.sent, ["سلام", "مدل %s را وارد کن" % name])
        self.assertIn("وارد کنم؟", reply)
        self.assertEqual(pg.input_value("#input-box"), "گفتهٔ من")
        self.assertFalse(pg.is_disabled("#voice-btn"))
        self.assertFalse(pg.is_disabled("#model-btn"))
        self.assertEqual(self.errors, [])

    def test_at_most_five_waiting_messages_are_kept_and_they_go_out_one_by_one(self):
        pg = self.page()
        held = self.hold_messages(pg)
        pg.fill("#input-box", "سلام")
        pg.click("#send-btn")
        pg.wait_for_selector(".message.typing", timeout=5000)
        for _ in range(8):
            self.tell(pg, "nativeOnShared", {"ok": True, "chars": 10, "truncated": False, "mission_open": True, "text": ""})
        pg.wait_for_timeout(300)
        self.assertEqual(self.sent, ["سلام"])                                       # eight events, none of them sent while the first is on its way
        for _ in range(6):                                                          # the first answer, then the five that were kept - one by one
            self.release(pg, held)
        self.settle(pg, 6)
        pg.wait_for_timeout(600)                                                    # a seventh would have gone out by now
        self.assertEqual(self.sent, ["سلام"] + ["جواب آمد"] * 5)
        self.assertEqual(held, [])
        self.assertEqual(self.errors, [])

    # ------------------------------------------------------------------ phone sizes
    def test_the_bar_fits_every_phone_size_without_moving_the_composer(self):
        for label, (w, h) in self.PHONES.items():
            with self.subTest(phone=label):
                plain = self.page(w, h, present=False)
                composer_plain, messages_plain = self.box(plain, "#input-form"), self.box(plain, "#messages")
                pg = self.page(w, h)
                self.assertTrue(pg.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"))
                for selector in ("#native-bar", "#voice-btn", "#model-btn", "#send-btn", "#attach-btn", "#input-box"):
                    box = self.box(pg, selector)
                    self.assertGreaterEqual(box["x"], -0.5, selector)
                    self.assertLessEqual(box["x"] + box["width"], w + 0.5, selector)
                    self.assertLessEqual(box["y"] + box["height"], h + 0.5, selector)
                composer, messages, bar = self.box(pg, "#input-form"), self.box(pg, "#messages"), self.box(pg, "#native-bar")
                for key in ("x", "y", "width", "height"):
                    self.assertAlmostEqual(composer[key], composer_plain[key], delta=1.0, msg=key)       # the composer neither moves nor shrinks
                self.assertGreaterEqual(messages_plain["height"] - messages["height"], bar["height"] - 1)   # the bar takes room from the messages only

    def test_on_a_short_screen_the_bar_gives_its_room_back(self):
        for w, h, shown in ((640, 360, False), (360, 470, False), (360, 480, False), (360, 481, True)):
            with self.subTest(size=(w, h)):
                pg = self.page(w, h)
                self.assertEqual(pg.is_visible("#native-bar"), shown)
                self.assertTrue(pg.is_visible("#input-form"))
                self.assertTrue(pg.is_visible("#send-btn"))
                self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
