"""
Prompt 959 (stage B, the body) - the emergency-stop button of the CHAT PAGE.

Found while finishing the body: the page disables the send button while an answer is being made (`if (busy) return`), so the user could not send
«ایست» from the page exactly when it matters (a long answer of the local model, a slow cloud request). The server side was right (a second
request is answered at once, see `EmergencyAnswerTests`); only the page did not let the word out. Now the stop button takes the place of the send
button while an answer is being made and sends the word on a request of its own.

Two kinds of test:
  * static - what the markup, the style and the script say (the button is a plain button, hidden at rest, swapped with "send" while busy, uses the
    one existing route, cannot be reached by the Enter key, and the word it sends is a halt word of the brain);
  * a REAL browser - the page is served by the real server, the real brain answers with a fake engine that blocks until it is cancelled, and a real
    Chromium (driven by `browser_stop_driver_prompt959.js` through Node's Playwright) types the question, presses the button twice, and the test
    checks what the page showed, what it sent and what the engine was asked. It is SKIPPED where Node, Playwright or Chromium is missing (the
    GitHub test job has no Playwright), and it says so.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from persian_brain import hub_brain_commands as HBC
from persian_brain import hub_messages_brain as HBr
from persian_brain import normalization as nz
from self_builder import fa_text
from tests.ownbrain_support_prompt959 import OwnBrainApp
from tests.test_body_chat_prompt959 import FREE, BodyMixin, CancellingBridge, wait_until

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(PY_ROOT, "interface", "static")
DRIVER = os.path.join(PY_ROOT, "tests", "browser_stop_driver_prompt959.js")
REPLY_MARK = "به موتورِ مدلِ روی گوشی هم گفتم"      # the part of the stop reply that says the local engine was asked to drop its answer


def read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as handle:
        return handle.read()


def function_body(js, name):
    """The text of `function name(...) { ... }` up to its closing brace (the page's functions are flat, braces balance)."""
    start = js.index("function %s(" % name)
    depth, index = 0, js.index("{", start)
    for position in range(index, len(js)):
        if js[position] == "{":
            depth += 1
        elif js[position] == "}":
            depth -= 1
            if depth == 0:
                return js[start:position + 1]
    raise AssertionError("function %s is not closed" % name)


class StopButtonStaticTests(unittest.TestCase):
    def setUp(self):
        self.js, self.html, self.css, self.i18n = read("app.js"), read("index.html"), read("style.css"), read("i18n.js")

    def button(self):
        match = re.search(r'<button\b([^>]*\bid="stop-btn"[^>]*)>([^<]*)</button>', self.html)
        self.assertIsNotNone(match, "the page has no stop button")
        return match.group(1), match.group(2).strip()

    def test_the_stop_button_is_a_plain_button_hidden_at_rest_after_the_send_button(self):
        attributes, label = self.button()
        self.assertIn('type="button"', attributes, "a submit button would send the form when pressed")
        self.assertRegex(attributes, r"\bhidden\b", "it must not be visible before an answer is being made")
        self.assertIn('aria-label="', attributes)
        self.assertLess(self.html.index('id="send-btn"'), self.html.index('id="stop-btn"'))
        form = self.html[self.html.index('<form class="composer"'):self.html.index("</form>")]
        self.assertIn('id="stop-btn"', form, "the button belongs to the composer (the swap with «ارسال» is a rule of that form)")
        self.assertEqual(label, "ایست")

    def test_the_word_the_button_sends_is_a_halt_word_of_the_brain(self):
        word = re.search(r'^\s*stop:\s*"([^"]+)",', self.i18n, re.M).group(1)
        self.assertEqual(word, "ایست")
        self.assertTrue(HBC.is_halt(fa_text.words(nz.normalize(word))), "the brain does not take it for the emergency word")
        self.assertIn("body: JSON.stringify({ text: S.stop })", function_body(self.js, "requestStop"))

    def test_the_button_follows_the_busy_state_and_the_send_button_stays_disabled(self):
        busy = function_body(self.js, "setBusy")
        for needle in ("sendBtn.disabled = value", "stopBtn.hidden = !value", "stopBtn.disabled = false", "stopping = false",
                       'formEl.setAttribute("aria-busy"'):
            self.assertIn(needle, busy)
        self.assertIn('.composer[aria-busy="true"] .send-btn { display: none; }', self.css)
        self.assertIn(".stop-btn[hidden] { display: none; }", self.css)
        self.assertIn("if (busy) return", self.js)                      # the older pins: a message is still never sent twice

    def test_it_uses_the_one_existing_route_and_only_while_an_answer_is_being_made(self):
        body = function_body(self.js, "requestStop")
        self.assertIn('fetch("/api/message"', body)
        self.assertIn("if (!busy || stopping) return;", body)
        self.assertEqual(set(re.findall(r'fetch\("([^"]+)"', self.js)), {"/api/status", "/api/message"})
        self.assertIn("stopping = true;", body)
        self.assertIn("stopBtn.disabled = true;", body)
        self.assertIn(".catch(function () {", body)
        self.assertIn("stopping = false;", body.split(".catch(function () {", 1)[1], "a failed stop request may be tried again")

    def test_only_a_click_on_the_button_can_stop_nothing_else_does(self):
        self.assertEqual(len(re.findall(r"requestStop", self.js)), 2, "the function and its one listener, nothing else may call it")
        self.assertIn('stopBtn.addEventListener("click", requestStop)', self.js)
        for line in self.js.splitlines():
            if "keydown" in line or "keypress" in line or "keyup" in line:
                self.assertNotIn("requestStop", line)
        submit = function_body(self.js, "submit")
        self.assertNotIn("requestStop", submit, "Enter (a submit) must never be the emergency stop: it would stop an answer by accident")

    def test_the_new_text_is_persian_and_the_page_loads_nothing_from_outside(self):
        self.assertNotRegex(self.html, r"(?:src|href)=\"https?://")
        self.assertNotIn("innerHTML", function_body(self.js, "requestStop"))


def node_and_playwright():
    """(node path, the folder that holds the playwright module or "") - or a reason why the browser test cannot run here."""
    node = shutil.which("node")
    if not node:
        return None, "Node is not installed"
    probe = subprocess.run([node, "-e", "require('playwright')"], capture_output=True, text=True, timeout=60)
    if probe.returncode == 0:
        return (node, ""), ""
    npm = shutil.which("npm")
    if npm:
        root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True, timeout=60).stdout.strip()
        if root and os.path.isdir(os.path.join(root, "playwright")):
            return (node, root), ""
    return None, "Node's Playwright is not installed"


class RearmingBridge(CancellingBridge):
    """After each answer the gate closes again, so the NEXT question blocks too (two rounds in one page session)."""

    def chat(self, system, history, user, max_tokens):
        try:
            return super().chat(system, history, user, max_tokens)
        finally:
            if self.gate is not None:
                self.gate.clear()


class StopButtonBrowserTests(BodyMixin, OwnBrainApp):
    """The real page, the real server, the real brain, a fake engine that blocks until the stop asks it to drop the answer."""

    rounds = 2

    def setUp(self):
        super().setUp()
        self.bridge = RearmingBridge(answers=self.answers)
        self.start_app()
        self.install_light()

    def run_driver(self):
        found, reason = node_and_playwright()
        if found is None:
            self.skipTest(reason)
        node, root = found
        self.bridge.gate = threading.Event()
        self.addCleanup(self.bridge.gate.set)
        env = dict(os.environ)
        if root:
            env["PLAYWRIGHT_ROOT"] = root
        done = subprocess.run([node, DRIVER, "http://127.0.0.1:%d/" % self.port, FREE, REPLY_MARK, str(self.rounds)], capture_output=True, text=True,
                              timeout=180, env=env)
        lines = [line for line in done.stdout.splitlines() if line.strip()]
        if done.returncode in (3, 4):
            self.skipTest("the browser could not be started here: %s" % (lines[-1] if lines else done.stderr[-200:]))
        self.assertTrue(lines, "the driver printed nothing; stderr: %s" % done.stderr[-500:])
        result = json.loads(lines[-1])
        self.assertEqual(done.returncode, 0, "the browser run failed: %s" % json.dumps(result, ensure_ascii=False)[:800])
        return result

    def test_the_page_stops_a_long_answer_through_the_real_server_and_the_real_brain(self):
        result = self.run_driver()
        before, busy, after = result["before"], result["busy"], result["after"]
        self.assertEqual((before["stopVisible"], before["sendVisible"]), (False, True), "at rest only «ارسال» is there")
        self.assertIn(before["busy"], (None, "false"))                  # the form has no aria-busy before the first message
        self.assertEqual(before["stopType"], "button")
        self.assertEqual((busy["stopVisible"], busy["sendVisible"], busy["busy"]), (True, False, "true"),
                         "while an answer is being made the stop button takes the place of «ارسال»")
        self.assertEqual(busy["stopText"], "ایست")
        self.assertEqual((after["stopVisible"], after["sendVisible"], after["sendDisabled"], after["busy"]), (False, True, False, "false"),
                         "when the first answer is over the page is as before")

        posts = [p for p in result["posts"] if p["path"] == "/api/message"]
        self.assertEqual(len(posts), 2 * self.rounds, "per round: the question and ONE stop word (two quick presses): %s" % result["posts"])
        for round_ in range(self.rounds):
            self.assertEqual(json.loads(posts[2 * round_]["body"]), {"text": FREE})
            self.assertEqual(json.loads(posts[2 * round_ + 1]["body"]), {"text": "ایست"})
        self.assertEqual(self.bridge.cancels, self.rounds, "the engine was asked to drop each answer exactly once")

        texts = [b["text"] for b in result["bubbles"]]
        self.assertEqual(len([t for t in texts if t == FREE]), self.rounds, "each question is in the conversation once")
        stop_replies = [b for b in result["bubbles"] if REPLY_MARK in b["text"]]
        self.assertEqual(len(stop_replies), self.rounds)
        for reply in stop_replies:
            self.assertIn("assistant", reply["role"])
            self.assertIn(HBr.halt_done(), reply["text"])
        self.assertTrue(len([b for b in result["bubbles"] if "assistant" in b["role"]]) >= 1 + 2 * self.rounds,
                        "the greeting, and per round the stop reply and the (cut) answer are all shown: %s" % texts)



class StopExchangeTests(BodyMixin, OwnBrainApp):
    """What the real server does with the stop word that arrives while an answer is being made - exactly the request the page's button sends."""

    def setUp(self):
        super().setUp()
        self.bridge = RearmingBridge(answers=self.answers)
        self.start_app()
        self.install_light()

    def history(self):
        return list(self.memory._conn.execute("SELECT role, content FROM conversation_log ORDER BY rowid"))

    def test_the_stop_exchange_is_stored_like_any_message_before_the_line_of_the_cut_answer(self):
        self.bridge.gate = threading.Event()
        self.addCleanup(self.bridge.gate.set)
        before = len(self.bridge.chats)
        box = {}
        thread = threading.Thread(target=lambda: box.update(reply=self.ask(FREE)), daemon=True)
        thread.start()
        wait_until(self, lambda: len(self.bridge.chats) > before, what="the engine to start the answer")
        reply = self.ask("ایست")                                           # a second request while the first is still open
        thread.join(15)
        self.assertFalse(thread.is_alive(), "the first answer never came back")
        self.assertIn(REPLY_MARK, reply)
        self.assertEqual(self.bridge.cancels, 1)
        tail = self.history()[-4:]
        self.assertEqual([role for role, _ in tail], ["user", "user", "assistant", "assistant"])
        self.assertEqual(tail[0][1], FREE)
        self.assertEqual(tail[1][1], "ایست")
        self.assertEqual(tail[2][1], reply, "the stop reply is in the history, as the page showed it")
        self.assertEqual(tail[3][1], box["reply"], "the line of the answer that was cut comes AFTER the stop exchange")
        self.assertNotEqual(tail[3][1], reply)


if __name__ == "__main__":
    unittest.main()
