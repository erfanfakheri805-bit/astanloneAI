"""
Tests for Prompt 956 - Final Persian Mobile APK Preparation.

A productization / UI-localization check. It verifies that the shipped chat page
and the thin Android layer are Persian-first, RTL, portrait and keyboard-safe, and
that the real runtime behind them (RuntimeCore over the existing HTTP routes) is
unchanged. No production Python is touched by Prompt 956, so every pinned
Prompt 955 file hash is re-asserted here as well.

Groups:
    Static checks   - markup / CSS / JS / Android XML read as text (always run).
    Node checks     - the DOM-free i18n helpers executed by Node (skipped without node).
    Real server     - a real ThreadingHTTPServer over a real RuntimeCore.
    Browser checks  - headless Chromium against that server (skipped unless
                      Playwright and a Chromium build are available).

Run directly:
    python -m unittest tests.test_persian_mobile_ui_prompt956 -v
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface import server as srv
from runtime_integration.runtime_core import RuntimeCore

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.abspath(os.path.join(PY_ROOT, "..", "..", "..", ".."))
STATIC = os.path.join(PY_ROOT, "interface", "static")
MAIN = os.path.join(PROJECT_ROOT, "app", "src", "main")
HAS_PROJECT = os.path.isfile(os.path.join(PROJECT_ROOT, "settings.gradle"))

# Production files Prompts 954/955 pinned; Prompt 956 must not change them.
PINNED = {
    "android_entry.py": "ffa9d214a53e4aeb7e043f65ade9a398c4be2fd7d6e2dc69f4e7ce1c6bc40c07",
    "core/core.py": "64dbaef03caba1b1bc43795a21516dfce04c68d01c68f22c1f97ae98b7f77d0b",
    "ael/interpreter.py": "8c96be945ef91e5ba33c7290d6483801d7acd1beba7d14ab846dd9a7f8f3984b",
    "runtime_integration/bridge.py": "4b2177f0153d05741bc07d196f6fbadf7917521da71f4804761588564383bfac",
    "interface/server.py": "97f3f0659fb2881690db4b02340508156ba24039c0846551098fb3343aabb642",
    "runtime_integration/runtime_core.py": "610e0c5c51f47fc95f574cd90958a6a94f61c803f114d388f435cbc85f658cdf",
    "runtime_growth/runtime_growth_cycle.py": "d7015ed497e4fef18280c1b6592c13a5c415ff8226568b349aefa07205dd2bcd",
}

PERSIAN = re.compile(r"[؀-ۿ]")
LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
# Latin tokens that are allowed to remain visible: the language name and the
# literal AEL command examples the user is meant to type.
ALLOWED_LATIN = {"AEL", "TEACH", "ASK", "IS", "sky", "the", "atmosphere", "above", "earth"}


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def visible_text(html):
    """Text a user can see in the page markup: tags, <script>/<style>, comments and
    attribute values that are not user-facing are dropped; user-facing attributes
    (placeholder, aria-label, title, data-insert excluded) are appended."""
    attrs = re.findall(r'(?:placeholder|aria-label|title)="([^"]*)"', html)
    body = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    body = re.sub(r"(?s)<!--.*?-->", " ", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    return " ".join([body] + attrs)


needs_node = unittest.skipUnless(shutil.which("node"), "node is not installed")


def node_eval(script, *argv):
    """Run a small Node script; arguments are passed as argv, never interpolated."""
    out = subprocess.run(["node", "-e", script, *argv], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError("node failed: " + out.stderr)
    return out.stdout


I18N_PATH = os.path.join(STATIC, "i18n.js")
LOAD = ("const T=require(process.argv[1]);"
        "const input=JSON.parse(process.argv[2]);")


# ----------------------------------------------------------------------------------
# 1. Persian default UI text
# ----------------------------------------------------------------------------------
class PersianDefaultUITests(unittest.TestCase):
    def setUp(self):
        self.html = read(STATIC, "index.html")

    def test_document_language_is_persian(self):
        self.assertRegex(self.html, r'<html[^>]*\blang="fa"')

    def test_page_title_is_persian(self):
        title = re.search(r"<title>(.*?)</title>", self.html, re.S).group(1)
        self.assertRegex(title, PERSIAN)
        self.assertNotRegex(title, LATIN_WORD)

    def test_all_visible_labels_are_persian(self):
        text = visible_text(self.html)
        self.assertRegex(text, PERSIAN)
        leftovers = {w for w in LATIN_WORD.findall(text)} - ALLOWED_LATIN
        self.assertEqual(leftovers, set(), "English words visible in the page markup")

    def test_every_control_has_persian_text(self):
        for label in ("ارسال", "اطلاعات سیستم", "بستن", "پیام خود را بنویسید…", "در حال اتصال…"):
            self.assertIn(label, self.html)

    def test_old_english_ui_strings_are_gone(self):
        for old in ("Developer Panel", "Conversation", "System Online", "Self-Evolving Foundation",
                    "Type a message", "Knowledge Entries", "Upgrade History", "Checking",
                    "ADAPTIVE", "Send</button>", "Local-only"):
            self.assertNotIn(old, self.html)
            self.assertNotIn(old, read(STATIC, "app.js"))

    def test_first_launch_greeting_is_persian(self):
        greeting = re.search(r'id="greeting".*?<div class="bubble"[^>]*>(.*?)</div>', self.html, re.S).group(1)
        self.assertRegex(greeting, PERSIAN)
        self.assertNotRegex(" ".join(re.findall(r"[A-Za-z]+", greeting)).replace("AEL", ""), LATIN_WORD)

    def test_greeting_makes_no_false_capability_claims(self):
        greeting = read(STATIC, "i18n.js")
        start = greeting.index("greeting:")
        greeting = greeting[start:greeting.index('hintsLabel')]
        for forbidden in ("تصویر", "ویدیو", "ویدئو", "بازی", "ویندوز", "نقاشی", "ساخت عکس", "همه‌کاره", "جارویس"):
            self.assertNotIn(forbidden, greeting)
        # It states the real, current abilities and that growth is gradual.
        self.assertIn("گفتگوی ساده", greeting)
        self.assertIn("AEL", greeting)
        self.assertIn("به‌تدریج", greeting)

    @needs_node
    def test_string_table_values_are_persian(self):
        out = node_eval(LOAD + "console.log(JSON.stringify(Object.entries(T.STR)."
                        "flatMap(([k,v])=>typeof v==='string'?[[k,v]]:Object.entries(v).map(([a,b])=>[k+'.'+a,b]))))",
                        I18N_PATH, "{}")
        technical = {"hintTeachText", "hintAskText"}
        entries = json.loads(out)
        self.assertGreater(len(entries), 40)
        for key, value in entries:
            if key in technical:
                continue
            self.assertRegex(value, PERSIAN, key)

    def test_user_visible_android_strings_are_persian(self):
        strings = read(MAIN, "res", "values", "strings.xml")
        label = re.search(r'name="app_name">([^<]+)<', strings).group(1)
        self.assertRegex(label, PERSIAN)
        startup = re.search(r'name="startup_error">([^<]+)<', strings).group(1)
        self.assertRegex(startup, PERSIAN)
        self.assertIn("%1$s", startup)

    def test_java_has_no_hardcoded_english_toast(self):
        java = read(MAIN, "java", "com", "erfan", "standaloneai", "MainActivity.java")
        self.assertNotIn("Startup error", java)
        self.assertIn("R.string.startup_error", java)


# ----------------------------------------------------------------------------------
# 2. RTL behaviour
# ----------------------------------------------------------------------------------
class RTLTests(unittest.TestCase):
    def setUp(self):
        self.html = read(STATIC, "index.html")
        self.css = read(STATIC, "style.css")
        self.js = read(STATIC, "app.js")

    def test_document_direction_is_rtl(self):
        self.assertRegex(self.html, r'<html[^>]*\bdir="rtl"')

    def test_empty_composer_is_rtl_and_follows_content_when_typing(self):
        self.assertRegex(self.html, r'<textarea[^>]*\bdir="rtl"')
        self.assertIn('"auto"', self.js)
        self.assertRegex(self.js, r'setAttribute\("dir",\s*inputEl\.value\.trim\(\)\s*===\s*""\s*\?\s*"rtl"\s*:\s*"auto"\)')

    def test_message_bubbles_resolve_direction_per_message(self):
        self.assertRegex(self.js, r'bubble\.setAttribute\("dir",\s*"auto"\)')
        self.assertRegex(self.html, r'class="bubble"\s+dir="auto"')
        self.assertRegex(self.css, r"\.bubble\s*\{[^}]*unicode-bidi:\s*plaintext")

    def test_css_uses_logical_not_physical_directions(self):
        css = re.sub(r"/\*.*?\*/", "", self.css, flags=re.S)
        physical = re.findall(
            r"(?<![\w-])(?:margin|padding|border)-(?:left|right)\b|(?<![\w-])(?:left|right)\s*:"
            r"|border-(?:top|bottom)-(?:left|right)-radius|text-align:\s*(?:left|right)", css)
        self.assertEqual(physical, [])

    def test_bubble_tails_and_alignment_follow_rtl(self):
        self.assertIn("border-end-end-radius", self.css)     # assistant tail
        self.assertIn("border-end-start-radius", self.css)   # user tail
        self.assertRegex(self.css, r"\.message\.user\s*\{\s*justify-content:\s*flex-start")
        self.assertRegex(self.css, r"\.message\.assistant\s*\{\s*justify-content:\s*flex-end")

    def test_technical_values_stay_left_to_right(self):
        self.assertRegex(self.html, r'id="version-label"\s+dir="ltr"')
        self.assertRegex(self.html, r'id="m-version"\s+dir="ltr"')
        self.assertRegex(self.js, r'nameSpan\.setAttribute\("dir",\s*"ltr"\)')
        # Code-like content in a message is not reordered: bidi is per line.
        self.assertIn("white-space: pre-wrap", self.css)

    def test_long_unbreakable_values_cannot_overflow(self):
        self.assertRegex(self.css, r"\.bubble\s*\{[^}]*overflow-wrap:\s*anywhere")

    def test_android_layout_and_manifest_support_rtl(self):
        layout = read(MAIN, "res", "layout", "activity_main.xml")
        self.assertIn('android:layoutDirection="rtl"', layout)
        self.assertIn('android:supportsRtl="true"', read(MAIN, "AndroidManifest.xml"))

    @needs_node
    def test_persian_digits_only_for_counts_not_for_technical_values(self):
        out = node_eval(LOAD + "console.log(JSON.stringify([T.formatCount(1204),T.formatCount(null),"
                        "T.formatCount('0.2.0'),T.toPersianDigits('v1.2')]))", I18N_PATH, "{}")
        self.assertEqual(json.loads(out), ["۱۲۰۴", "—", "0.2.0", "v۱.۲"])
        # app.js writes versions untouched (Latin digits) and counts through formatCount.
        js = read(STATIC, "app.js")
        self.assertIn('setText("version-label", String(status.app_version))', js)
        self.assertIn("T.formatCount(status.knowledge_count)", js)


# ----------------------------------------------------------------------------------
# 3. Portrait configuration
# ----------------------------------------------------------------------------------
@unittest.skipUnless(HAS_PROJECT, "Gradle project files not present")
class PortraitConfigTests(unittest.TestCase):
    def setUp(self):
        self.manifest = read(MAIN, "AndroidManifest.xml")

    def test_only_activity_is_portrait(self):
        self.assertEqual(self.manifest.count("<activity"), 1)
        self.assertRegex(self.manifest, r'<activity[^>]*android:screenOrientation="portrait"')

    def test_no_landscape_anywhere(self):
        for path in (os.path.join(MAIN, "AndroidManifest.xml"),
                     os.path.join(MAIN, "res", "layout", "activity_main.xml"),
                     os.path.join(STATIC, "index.html")):
            self.assertNotRegex(read(path).lower(), r"landscape")

    def test_no_forced_landscape_css(self):
        self.assertNotIn("orientation: landscape", read(STATIC, "style.css"))

    def test_startup_activity_wiring_untouched(self):
        self.assertRegex(self.manifest, r'android:name="\.MainActivity"')
        self.assertIn("android.intent.category.LAUNCHER", self.manifest)
        self.assertIn('android:exported="true"', self.manifest)

    def test_permissions_unchanged(self):
        perms = re.findall(r'<uses-permission android:name="([^"]+)"', self.manifest)
        self.assertEqual(perms, ["android.permission.INTERNET"])
        self.assertIn('android:usesCleartextTraffic="true"', self.manifest)

    def test_android_entry_not_modified(self):
        self.assertEqual(sha256_file(os.path.join(PY_ROOT, "android_entry.py")), PINNED["android_entry.py"])

    def test_java_layer_still_only_calls_android_entry_start(self):
        java = read(MAIN, "java", "com", "erfan", "standaloneai", "MainActivity.java")
        self.assertEqual(re.findall(r'getModule\("([^"]+)"\)', java), ["android_entry"])
        self.assertEqual(re.findall(r'callAttr\("([^"]+)"', java), ["start"])
        self.assertNotRegex(java, r"https?://")

    def test_gradle_dependencies_unchanged(self):
        gradle = read(PROJECT_ROOT, "app", "build.gradle")
        deps = re.findall(r"^\s*(?:implementation|api|compileOnly|runtimeOnly)\s+['\"]([^'\"]+)", gradle, re.M)
        self.assertEqual(deps, ["androidx.appcompat:appcompat:1.7.0"])

    def test_theme_resources_exist_and_resolve(self):
        styles = read(MAIN, "res", "values", "styles.xml")
        colors = read(MAIN, "res", "values", "colors.xml")
        for ref in re.findall(r"@color/(\w+)", styles + read(MAIN, "res", "layout", "activity_main.xml")):
            self.assertIn(f'name="{ref}"', colors)


# ----------------------------------------------------------------------------------
# 4 + 7. Vertical mobile layout and keyboard-safe layout
# ----------------------------------------------------------------------------------
class VerticalLayoutTests(unittest.TestCase):
    def setUp(self):
        self.html = read(STATIC, "index.html")
        self.css = read(STATIC, "style.css")
        self.js = read(STATIC, "app.js")

    def test_viewport_is_device_width(self):
        self.assertIn("width=device-width", self.html)
        self.assertIn("initial-scale=1.0", self.html)
        self.assertIn("viewport-fit=cover", self.html)

    def test_single_vertical_column_no_sidebar(self):
        self.assertNotIn("<aside", self.html)
        self.assertNotIn("sidebar", self.css)
        self.assertRegex(self.css, r"\.app-shell\s*\{[^}]*flex-direction:\s*column")
        self.assertNotRegex(self.css, r"width:\s*300px")

    def test_dom_order_header_conversation_composer(self):
        i_header = self.html.index('class="app-header"')
        i_messages = self.html.index('id="messages"')
        i_form = self.html.index('id="input-form"')
        self.assertLess(i_header, i_messages)
        self.assertLess(i_messages, i_form)

    def test_conversation_scrolls_vertically_and_fills_remaining_height(self):
        rule = re.search(r"\.messages\s*\{([^}]*)\}", self.css).group(1)
        self.assertIn("flex: 1 1 auto", rule)
        self.assertIn("overflow-y: auto", rule)
        self.assertIn("min-height: 0", rule)
        self.assertIn("flex-direction: column", rule)

    def test_user_and_assistant_messages_are_visually_separated(self):
        self.assertRegex(self.css, r"\.message\.assistant \.bubble\s*\{[^}]*background")
        self.assertRegex(self.css, r"\.message\.user \.bubble\s*\{[^}]*background")
        self.assertNotEqual(
            re.search(r"\.message\.assistant \.bubble\s*\{([^}]*)\}", self.css).group(1),
            re.search(r"\.message\.user \.bubble\s*\{([^}]*)\}", self.css).group(1))
        self.assertRegex(self.css, r"\.message\.user\s*\{\s*justify-content:\s*flex-start")
        self.assertRegex(self.css, r"\.message\.assistant\s*\{\s*justify-content:\s*flex-end")

    def test_input_area_is_pinned_at_the_bottom_and_send_is_reachable(self):
        rule = re.search(r"\.composer\s*\{([^}]*)\}", self.css).group(1)
        self.assertIn("flex: 0 0 auto", rule)
        self.assertRegex(self.html, r'<button type="submit" class="send-btn"')
        self.assertRegex(self.css, r"\.send-btn\s*\{[^}]*min-height:\s*44px")

    def test_touch_targets_are_at_least_44px(self):
        for selector in (r"\.icon-btn", r"\.chip", r"\.send-btn", r"#input-box"):
            rule = re.search(selector + r"\s*\{([^}]*)\}", self.css).group(1)
            self.assertIn("min-height: 44px", rule, selector)

    def test_no_fixed_desktop_widths_or_heights(self):
        css = re.sub(r"/\*.*?\*/", "", self.css, flags=re.S)
        self.assertNotRegex(css, r"(?<![\w-])width:\s*100vw")
        self.assertNotRegex(css, r"(?<![\w-])height:\s*100vh")
        self.assertNotRegex(css, r"min-width:\s*(?:[3-9]\d\d|\d{4,})px")
        self.assertRegex(css, r"max-width:\s*86%")

    def test_small_and_large_screen_rules_exist(self):
        self.assertRegex(self.css, r"@media\s*\(max-width:\s*340px\)")
        self.assertRegex(self.css, r"@media\s*\(max-height:\s*480px\)")
        self.assertRegex(self.css, r"\.app-shell\s*\{[^}]*max-width:\s*760px")

    # ---- keyboard ----
    def test_viewport_resizes_with_the_keyboard(self):
        self.assertIn("interactive-widget=resizes-content", self.html)
        self.assertRegex(self.css, r"height:\s*100dvh")
        manifest = read(MAIN, "AndroidManifest.xml")
        self.assertIn('android:windowSoftInputMode="adjustResize"', manifest)

    def test_composer_respects_safe_areas(self):
        self.assertIn("env(safe-area-inset-bottom)", self.css)
        self.assertIn("env(safe-area-inset-top)", self.css)

    def test_input_font_size_prevents_focus_zoom(self):
        rule = re.search(r"#input-box\s*\{([^}]*)\}", self.css).group(1)
        self.assertIn("font-size: 16px", rule)

    def test_composer_grows_but_is_bounded(self):
        rule = re.search(r"#input-box\s*\{([^}]*)\}", self.css).group(1)
        self.assertIn("max-height: 140px", rule)
        self.assertIn("resize: none", rule)
        self.assertIn("MAX_INPUT_PX = 140", self.js)

    def test_script_keeps_latest_message_visible_with_keyboard(self):
        self.assertIn("visualViewport", self.js)
        self.assertRegex(self.js, r'inputEl\.addEventListener\("focus"')
        self.assertRegex(self.js, r'addEventListener\("resize",\s*scrollToEnd\)')

    def test_enter_handling_is_ime_safe(self):
        self.assertIn("e.isComposing", self.js)
        self.assertIn("229", self.js)
        self.assertIn('enterkeyhint="send"', self.html)


# ----------------------------------------------------------------------------------
# 5 + 6. Chat input/output rendering and mixed Persian/English content
# ----------------------------------------------------------------------------------
class RenderingSafetyTests(unittest.TestCase):
    def setUp(self):
        self.js = read(STATIC, "app.js")

    def test_messages_are_inserted_as_text_never_markup(self):
        self.assertIn("bubble.textContent = text", self.js)
        self.assertNotRegex(self.js, r"\.innerHTML\s*=\s*[^\"';]*(?:text|reply|message)")
        self.assertNotIn("insertAdjacentHTML", self.js)
        self.assertNotIn("document.write", self.js)
        self.assertNotIn("eval(", self.js)

    def test_loading_error_and_empty_states_exist(self):
        for needle in ("showTyping", "hideTyping", "setBusy", "S.thinking", "S.errorNetwork",
                       "restoreDraft", "setOnline"):
            self.assertIn(needle, self.js)
        self.assertIn("hints", read(STATIC, "index.html"))   # empty-conversation starter

    def test_double_submit_is_blocked_while_waiting(self):
        self.assertIn("if (busy) return", self.js)
        self.assertIn("sendBtn.disabled = value", self.js)

    def test_empty_message_is_not_sent(self):
        self.assertIn("if (!text || busy) return", self.js)

    def test_page_loads_no_remote_resources(self):
        for name in ("index.html", "style.css", "app.js", "i18n.js"):
            self.assertNotRegex(read(STATIC, name), r"(?:src|href)=\"https?://|url\(\s*['\"]?https?://|@import")
            self.assertNotRegex(read(STATIC, name), r"fetch\(\s*[\"']https?://")

    def test_only_the_existing_local_api_is_used(self):
        routes = set(re.findall(r'fetch\("([^"]+)"', self.js))
        self.assertEqual(routes, {"/api/status", "/api/message"})

    @needs_node
    def test_fixed_runtime_templates_are_shown_in_persian(self):
        cases = {
            "Say something and I'll try to respond.": "چیزی بنویسید تا پاسخ دهم.",
            "[AEL OK] Learned concept 'sky'.": "[موفق · AEL]\nمفهوم «sky» آموخته شد.",
            "[AEL ERROR] No AEL instructions found.": "[خطا · AEL]\nهیچ دستور AEL پیدا نشد.",
            "I don't have enough information to answer that yet.": "هنوز اطلاعات کافی برای پاسخ به این پرسش ندارم.",
        }
        out = node_eval(LOAD + "console.log(JSON.stringify(input.map(t=>T.localizeReply(t))))",
                        I18N_PATH, json.dumps(list(cases)))
        self.assertEqual(json.loads(out), list(cases.values()))

    @needs_node
    def test_unknown_and_mixed_content_is_preserved_exactly(self):
        samples = [
            "سلام hello 123",
            "فایل app_main.py را در https://example.com/a/b?x=1&y=2 ببین ۱۲۳",
            "<script>alert(1)</script> و <b>bold</b>",
            "def f(x):\n    return x * 2  # تابع",
            "[GOAL CREATED]\ngoal_id: g-1\ngoal_type: task\noriginal_text: Learned concept 'x'.",
            "ASK sun",
        ]
        out = json.loads(node_eval(LOAD + "console.log(JSON.stringify(input.map(t=>T.localizeReply(t))))",
                                   I18N_PATH, json.dumps(samples)))
        for before, after in zip(samples, out):
            if before.startswith("[GOAL CREATED]"):
                self.assertEqual(after, before.replace("[GOAL CREATED]", "[هدف ایجاد شد]", 1))
            else:
                self.assertEqual(after, before)

    @needs_node
    def test_quoted_names_and_text_inside_templates_are_carried_over(self):
        out = json.loads(node_eval(LOAD + "console.log(JSON.stringify(input.map(t=>T.localizeReply(t))))",
                                   I18N_PATH, json.dumps(["[AEL OK] Learned concept 'خورشید sun-2'."])))
        self.assertEqual(out, ["[موفق · AEL]\nمفهوم «خورشید sun-2» آموخته شد."])

    @needs_node
    def test_empty_reply_and_error_mapping(self):
        out = json.loads(node_eval(LOAD + "console.log(JSON.stringify([T.localizeReply(''),T.localizeReply(undefined),"
                                   "T.localizeError('internal server error',500),T.localizeError('request body too large',413),"
                                   "T.localizeError('',404),T.localizeError('',0),T.statusLabel('HEALTHY'),T.statusLabel('weird')]))",
                                   I18N_PATH, "{}"))
        self.assertEqual(out[0], out[1])
        self.assertRegex(out[0], PERSIAN)
        for message in out[2:6]:
            self.assertRegex(message, PERSIAN)
        self.assertEqual(out[6], "سالم")
        self.assertEqual(out[7], "weird")


# ----------------------------------------------------------------------------------
# Real server: the UI is served by, and talks to, the existing runtime
# ----------------------------------------------------------------------------------
class RealRuntimeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.core = RuntimeCore(memory_db_path=os.path.join(self._tmp.name, "m.sqlite3"),
                                skill_definitions_dir=os.path.join(self._tmp.name, "skills"))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(self.core))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

        def stop():
            self.server.shutdown()
            self.server.server_close()
        self.addCleanup(stop)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def post(self, path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))


class ServedPageTests(RealRuntimeCase):
    def test_root_serves_the_persian_rtl_page(self):
        status, ctype, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertEqual(ctype, "text/html; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn('lang="fa"', text)
        self.assertIn('dir="rtl"', text)
        self.assertIn("دستیار هوشمند", text)

    def test_static_assets_are_served_with_correct_types(self):
        for name, ctype in (("style.css", "text/css; charset=utf-8"),
                            ("app.js", "application/javascript; charset=utf-8"),
                            ("i18n.js", "application/javascript; charset=utf-8")):
            status, got, body = self.get("/static/" + name)
            self.assertEqual((status, got), (200, ctype))
            self.assertTrue(body)
            body.decode("utf-8")

    def test_page_scripts_are_in_dependency_order(self):
        html = read(STATIC, "index.html")
        self.assertLess(html.index("/static/i18n.js"), html.index("/static/app.js"))

    def test_every_element_id_the_script_uses_exists_in_the_markup(self):
        html = read(STATIC, "index.html")
        js = read(STATIC, "app.js")
        ids = set(re.findall(r'getElementById\("([^"]+)"\)', js)) | set(re.findall(r'setText\("([^"]+)"', js))
        for dom_id in ids:
            self.assertIn(f'id="{dom_id}"', html, dom_id)

    def test_status_route_feeds_every_panel_field(self):
        status, _, body = self.get("/api/status")
        snap = json.loads(body)
        js = read(STATIC, "app.js")
        for key in set(re.findall(r"status\.(\w+)", js)):
            self.assertIn(key, snap, key)


class RuntimePreservationTests(RealRuntimeCase):
    def test_real_runtime_still_answers_through_the_existing_route(self):
        status, body = self.post("/api/message", {"text": "TEACH sky IS the atmosphere above the earth"})
        self.assertEqual(status, 200)
        self.assertIn("Learned concept 'sky'", body["reply"])
        status, body = self.post("/api/message", {"text": "ASK sky"})
        self.assertIn("atmosphere above the earth", body["reply"])
        self.assertEqual(self.core.recent_messages(4)[-1]["role"], "assistant")

    def test_runtime_replies_are_not_modified_by_the_ui_layer(self):
        # The raw reply the UI receives is still the runtime's own text; only
        # the browser-side presentation maps known templates to Persian.
        status, body = self.post("/api/message", {"text": ""})
        self.assertEqual(body["reply"], "Say something and I'll try to respond.")

    @needs_node
    def test_real_replies_render_in_persian_through_the_ui_layer(self):
        replies = [self.post("/api/message", {"text": t})[1]["reply"]
                   for t in ("TEACH sky IS the atmosphere above the earth", "ASK nothingknown", "")]
        shown = json.loads(node_eval(LOAD + "console.log(JSON.stringify(input.map(t=>T.localizeReply(t))))",
                                     I18N_PATH, json.dumps(replies)))
        for text in shown:
            self.assertRegex(text, PERSIAN)

    def test_runtime_growth_route_still_verified(self):
        status, body = self.post("/api/runtime-growth", {
            "kind": "IMPROVE_RUNTIME", "goal": "Grow the runtime safely",
            "target": "runtime_growth", "reason": "Controlled growth", "source": "runtime"})
        self.assertEqual(status, 200)
        self.assertIs(body["available"], True)
        self.assertEqual(body["status"], "verified")
        self.assertIs(body["persistent"], False)

    def test_unknown_routes_and_traversal_unchanged(self):
        for path in ("/nope", "/static/../core/core.py"):
            try:
                self.get(path)
                self.fail("expected 404")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 404)

    def test_api_error_bodies_unchanged(self):
        status, body = self.post("/api/inspect-code", {"code": 5})
        self.assertEqual((status, body), (400, {"error": "'code' must be a string"}))

    @needs_node
    def test_message_errors_map_to_persian(self):
        out = node_eval(LOAD + "console.log(JSON.stringify(T.localizeError('internal server error',500)))",
                        I18N_PATH, "{}")
        self.assertRegex(json.loads(out), PERSIAN)


class PreservedArchitectureTests(unittest.TestCase):
    def test_pinned_production_files_are_byte_identical(self):
        for rel, digest in PINNED.items():
            self.assertEqual(sha256_file(os.path.join(PY_ROOT, *rel.split("/"))), digest, rel)

    def test_no_new_python_modules_or_dependencies(self):
        new_py = [n for n in os.listdir(STATIC) if n.endswith(".py")]
        self.assertEqual(new_py, [])
        self.assertEqual(sorted(os.listdir(STATIC)), ["app.js", "i18n.js", "index.html", "style.css"])

    def test_no_external_ai_references_in_new_ui_code(self):
        needles = ("claude", "anthropic", "openai", "api_key", "apikey", "gemini", "llm_api",
                   "bearer", "authorization")
        for name in ("index.html", "style.css", "app.js", "i18n.js"):
            low = read(STATIC, name).lower()
            for n in needles:
                self.assertNotIn(n, low, f"{n} in {name}")
        if HAS_PROJECT:
            for rel in (("res", "values", "strings.xml"), ("AndroidManifest.xml",),
                        ("java", "com", "erfan", "standaloneai", "MainActivity.java")):
                low = read(MAIN, *rel).lower()
                for n in needles:
                    self.assertNotIn(n, low)

    def test_no_model_files_or_keys_shipped_with_the_ui(self):
        for root, _, files in os.walk(STATIC):
            for f in files:
                self.assertFalse(f.lower().endswith((".gguf", ".onnx", ".safetensors", ".pt", ".bin", ".tflite")))


# ----------------------------------------------------------------------------------
# Browser checks (real rendering). Skipped when Playwright/Chromium are unavailable.
# ----------------------------------------------------------------------------------
try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
    _PW = True
except Exception:  # noqa: BLE001
    _PW = False


@unittest.skipUnless(_PW, "Playwright is not installed")
class BrowserTests(RealRuntimeCase):
    PHONES = {"small": (320, 568), "normal": (360, 740), "large": (412, 915), "tablet": (800, 1280)}

    @classmethod
    def setUpClass(cls):
        try:
            cls._pw = sync_playwright().start()
            cls._browser = cls._pw.chromium.launch()
        except Exception as e:  # noqa: BLE001
            try:
                cls._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            raise unittest.SkipTest(f"Chromium is not available: {e}")

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()

    def page(self, w, h):
        ctx = self._browser.new_context(viewport={"width": w, "height": h}, is_mobile=True, has_touch=True,
                                        locale="fa-IR")
        self.addCleanup(ctx.close)
        pg = ctx.new_page()
        self.errors = []
        pg.on("pageerror", lambda e: self.errors.append(str(e)))
        pg.goto(f"http://127.0.0.1:{self.port}/")
        pg.wait_for_selector("#status-dot.dot-live", timeout=10000)
        return pg

    def test_first_launch_is_persian_rtl_and_online(self):
        pg = self.page(360, 740)
        self.assertEqual(pg.evaluate("document.documentElement.dir"), "rtl")
        self.assertEqual(pg.evaluate("getComputedStyle(document.body).direction"), "rtl")
        self.assertEqual(pg.inner_text("#status-text"), "آنلاین · محلی")
        self.assertRegex(pg.inner_text("#greeting"), PERSIAN)
        self.assertEqual(pg.get_attribute("#input-box", "placeholder"), "پیام خود را بنویسید…")
        self.assertEqual(pg.evaluate("getComputedStyle(document.getElementById('input-box')).direction"), "rtl")
        self.assertEqual(self.errors, [])

    def test_no_horizontal_overflow_and_composer_visible_on_every_size(self):
        long_text = "این یک پیام بسیار طولانی فارسی است که باید شکسته شود. " * 8
        mixed = "سلام hello 123 https://example.com/very/long/path/that/should/wrap?x=1&y=2 و app_main.py ۱۲۳"
        for name, (w, h) in self.PHONES.items():
            pg = self.page(w, h)
            for text in (mixed, long_text, "x" * 200):
                pg.fill("#input-box", text)
                pg.click("#send-btn")
                pg.wait_for_function("!document.getElementById('send-btn').disabled", timeout=15000)
            m = pg.evaluate("""() => {
                const r = document.getElementById('input-form').getBoundingClientRect();
                const doc = document.documentElement;
                const wide = [...document.querySelectorAll('.bubble')].filter(b => {
                    const x = b.getBoundingClientRect(); return x.left < -0.5 || x.right > doc.clientWidth + 0.5; });
                return {sw: doc.scrollWidth, cw: doc.clientWidth, bottom: r.bottom, vh: innerHeight, wide: wide.length,
                        scrolls: document.getElementById('messages').scrollHeight > document.getElementById('messages').clientHeight};
            }""")
            self.assertLessEqual(m["sw"], m["cw"], name)
            self.assertLessEqual(m["bottom"], m["vh"] + 0.5, name)
            self.assertEqual(m["wide"], 0, name)
            if h < 1000:   # phones: the long conversation must scroll inside the message area
                self.assertTrue(m["scrolls"], name)

    def test_keyboard_open_keeps_composer_and_latest_message_visible(self):
        pg = self.page(360, 740)
        for t in ("ASK a", "ASK b", "ASK c", "ASK d"):
            pg.fill("#input-box", t)
            pg.click("#send-btn")
            pg.wait_for_function("!document.getElementById('send-btn').disabled", timeout=15000)
        pg.set_viewport_size({"width": 360, "height": 340})  # soft keyboard takes the lower half
        pg.focus("#input-box")
        pg.wait_for_timeout(450)
        m = pg.evaluate("""() => {
            const f = document.getElementById('input-form').getBoundingClientRect();
            const last = [...document.querySelectorAll('.message')].pop().getBoundingClientRect();
            const box = document.getElementById('messages').getBoundingClientRect();
            return {formBottom: f.bottom, vh: innerHeight, lastBottom: last.bottom, boxBottom: box.bottom,
                    boxHeight: box.height};
        }""")
        self.assertLessEqual(m["formBottom"], m["vh"] + 0.5)
        self.assertLessEqual(m["lastBottom"], m["boxBottom"] + 1)
        self.assertGreater(m["boxHeight"], 80)

    def test_send_shows_loading_then_renders_both_messages(self):
        pg = self.page(360, 740)
        pg.route("**/api/message", lambda route: (pg.wait_for_timeout(400), route.continue_()))
        pg.fill("#input-box", "TEACH sky IS the atmosphere above the earth")
        pg.click("#send-btn")
        pg.wait_for_selector(".message.typing", timeout=5000)
        self.assertTrue(pg.is_disabled("#send-btn"))
        self.assertEqual(pg.inner_text("#send-btn"), "در حال ارسال…")
        pg.wait_for_selector(".message.assistant:not(.typing) >> nth=1", timeout=15000)
        pg.wait_for_function("!document.getElementById('send-btn').disabled")
        self.assertEqual(pg.query_selector(".message.typing"), None)
        self.assertEqual(pg.inner_text("#send-btn"), "ارسال")
        self.assertEqual(pg.query_selector("#hints"), None)        # empty-state hints leave after the first send
        user = pg.inner_text(".message.user .bubble")
        self.assertEqual(user, "TEACH sky IS the atmosphere above the earth")
        reply = pg.inner_text(".message.assistant:not(.typing) >> nth=1")
        self.assertIn("آموخته شد", reply)
        self.assertEqual(pg.input_value("#input-box"), "")

    def test_html_in_messages_is_text_not_markup(self):
        pg = self.page(360, 740)
        pg.fill("#input-box", "<img src=x onerror=window.__pwned=1> و <b>bold</b>")
        pg.click("#send-btn")
        pg.wait_for_function("!document.getElementById('send-btn').disabled", timeout=15000)
        self.assertEqual(pg.query_selector(".bubble img"), None)
        self.assertEqual(pg.query_selector(".bubble b"), None)
        self.assertIsNone(pg.evaluate("window.__pwned"))
        self.assertIn("<b>bold</b>", pg.inner_text(".message.user .bubble"))

    def test_error_state_is_persian_and_keeps_the_draft(self):
        pg = self.page(360, 740)
        pg.route("**/api/message", lambda route: route.abort())
        pg.fill("#input-box", "پیام مهم من")
        pg.click("#send-btn")
        pg.wait_for_selector(".message.error", timeout=10000)
        self.assertEqual(pg.inner_text(".message.error .bubble"),
                         "ارتباط با سرور محلی برقرار نشد. لطفاً دوباره تلاش کنید.")
        self.assertEqual(pg.input_value("#input-box"), "پیام مهم من")      # draft restored
        self.assertEqual(pg.inner_text("#status-text"), "ارتباط قطع است")
        self.assertFalse(pg.is_disabled("#send-btn"))

    def test_server_error_response_is_persian(self):
        pg = self.page(360, 740)
        pg.route("**/api/message", lambda route: route.fulfill(
            status=500, content_type="application/json", body='{"error": "internal server error"}'))
        pg.fill("#input-box", "سلام")
        pg.click("#send-btn")
        pg.wait_for_selector(".message.error", timeout=10000)
        self.assertEqual(pg.inner_text(".message.error .bubble"), "خطایی در پردازش پیام رخ داد. لطفاً دوباره تلاش کنید.")

    def test_mixed_bidi_message_directions_are_resolved_per_message(self):
        pg = self.page(360, 740)
        pg.fill("#input-box", "hello world")
        pg.click("#send-btn")
        pg.wait_for_function("!document.getElementById('send-btn').disabled", timeout=15000)
        pg.fill("#input-box", "سلام دنیا")
        pg.click("#send-btn")
        pg.wait_for_function("!document.getElementById('send-btn').disabled", timeout=15000)
        dirs = pg.evaluate("[...document.querySelectorAll('.message.user .bubble')]"
                           ".map(b => getComputedStyle(b).direction + ':' + getComputedStyle(b).textAlign)")
        self.assertEqual(dirs[0], "ltr:start")
        self.assertEqual(dirs[1], "rtl:start")
        self.assertEqual(pg.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), True)

    def test_info_sheet_opens_closes_and_is_persian(self):
        pg = self.page(360, 740)
        self.assertTrue(pg.is_hidden("#info-sheet"))
        pg.click("#info-open")
        pg.wait_for_selector("#info-sheet", state="visible")
        self.assertIn("وضعیت سیستم", pg.inner_text("#info-sheet"))
        self.assertEqual(pg.inner_text("#m-status"), "سالم")
        pg.keyboard.press("Escape")
        self.assertTrue(pg.is_hidden("#info-sheet"))

    def test_enter_sends_and_shift_enter_adds_a_line(self):
        pg = self.page(360, 740)
        pg.focus("#input-box")
        pg.keyboard.type("خط اول")
        pg.keyboard.press("Shift+Enter")
        pg.keyboard.type("خط دوم")
        self.assertEqual(pg.input_value("#input-box"), "خط اول\nخط دوم")
        pg.keyboard.press("Enter")
        pg.wait_for_selector(".message.user", timeout=5000)
        self.assertEqual(pg.inner_text(".message.user .bubble"), "خط اول\nخط دوم")


if __name__ == "__main__":
    unittest.main()
