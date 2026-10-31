"""Prompt 958 - teacher: asking ChatGPT / Claude / ... for what the app cannot do, tested against a fake Android."""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest

from native_bridge import facade as native_facade
from pack_system.registry import Registry
from teacher import assistants as A
from teacher import capture as C
from teacher import recipes as RC
from teacher import request as R
from teacher import service as S
from teacher.facade import for_pack
from teacher.store import TeacherStore
from tests.native_support_prompt958 import ActivityNotFoundException, FakeJava

PACK_TEXT = ("=== PACK lang.v1 ===\nid: demo_teacher_pack\nversion: 1\ntitle: نمونه\ndescription: آزمون\n=== QA ===\n"
             "q: پایتخت فرانسه کجاست | مرکز فرانسه چیست\na: پاریس.\n=== END PACK ===\n")


class FakeHub:
    def __init__(self, root):
        self.root = root
        self.entries = []
        self._inbox = os.path.join(root, "inbox")
        os.makedirs(self._inbox, exist_ok=True)
        outer = self

        class Audit:
            def append(self, kind, subject, detail=None):
                outer.entries.append((kind, subject, detail))
        self.audit = Audit()

    def inbox_dir(self, create=False):
        return self._inbox


def install_chat_script(jvm, answer, package="com.openai.chatgpt", works=True, generating_reads=2):
    """Make the fake accessibility service behave like a chat app: a message field, a Send button, an answer that appears
    after a few reads (with a «Stop generating» label while it is being written), and a Copy button."""
    state = {"typed": "", "sent": False, "reads": 0}
    svc = jvm.classes["com.erfan.standaloneai.PyAccessibilityService"]

    def node(text="", desc="", editable=False, clickable=False):
        return {"t": text, "d": desc, "id": "", "c": "android.widget.EditText" if editable else "android.widget.TextView", "k": clickable,
                "e": editable, "f": editable, "s": False}

    def read(limit):
        nodes = [node("ChatGPT")]
        if not state["sent"]:
            nodes.append(node(state["typed"], "Message", editable=True))
        else:
            state["reads"] += 1
            nodes.append(node(state["typed"][:300]))
            if state["reads"] <= generating_reads:
                nodes += [node("partial answer…"), node("Stop generating", clickable=True)]
            else:
                nodes += [node(answer), node("Copy", clickable=True)]
        return json.dumps({"package": package, "nodes": nodes[:limit], "truncated": False})

    def set_text(hint, view_id, text):
        if not works or hint not in ("", "Message", "Ask anything"):
            return False
        state["typed"] = text
        return True

    def click(text, exact, view_id, last):
        if text in ("Send message", "Send") and state["typed"]:
            state["sent"] = True
            return True
        return False

    svc.readScreen, svc.setText, svc.clickNode = staticmethod(read), staticmethod(set_text), staticmethod(click)
    return state


class TeacherCase(unittest.TestCase):
    def setUp(self):
        native_facade.reset_for_tests()
        S.reset_for_tests()
        self.addCleanup(native_facade.reset_for_tests)
        self.addCleanup(S.reset_for_tests)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.hub = FakeHub(self.tmp)
        self.now = [1_000_000.0]
        self.mono = [0.0]
        self.jvm = FakeJava(installed={"com.openai.chatgpt", "com.anthropic.claude", S.OWN_PACKAGE}, package="com.openai.chatgpt")
        self.doors = native_facade.Doors("app", ("android", "clipboard", "screen"), self.hub, self.jvm, clock=lambda: self.now[0])
        self.svc = self.make_service()

    def make_service(self, **kwargs):
        def sleep(seconds):
            self.mono[0] += seconds
            self.now[0] += seconds
        options = dict(hub=self.hub, clock=lambda: self.now[0], sleep=sleep, monotonic=lambda: self.mono[0], run_async=False)
        options.update(kwargs)
        service = S.TeacherService(self.tmp, self.doors, **options)
        service.install_allow_provider()
        return service


class AssistantTests(unittest.TestCase):
    def test_names_in_persian_and_latin(self):
        cases = {"از چت جی بی تی بپرس": "chatgpt", "از ChatGPT بپرس": "chatgpt", "چت‌جی‌پی‌تی": "chatgpt", "chat-gpt": "chatgpt",
                 "از کلود بخواه": "claude", "claude": "claude", "جمینای چیه؟": "gemini", "گوگل جمینای": "gemini", "کوپایلت": "copilot",
                 "پرپلکسیتی": "perplexity", "دیپ سیک": "deepseek", "گراک رو باز کن": "grok"}
        for text, expected in cases.items():
            self.assertEqual(A.find_assistant(text), expected, text)

    def test_no_false_positives(self):
        for text in ("بارداری", "هیچ", "", "کلودین", "یک عکس بساز", "بارد یعنی چی"[:3]):
            self.assertIsNone(A.find_assistant(text), text)
        self.assertEqual(A.find_assistant("بارد یعنی چی"), "gemini")           # the old name, as a whole word

    def test_catalog_is_consistent(self):
        ids = [a.assistant_id for a in A.ASSISTANTS]
        self.assertEqual(len(ids), len(set(ids)))
        from native_bridge.doors import valid_https_url, valid_package
        for a in A.ASSISTANTS:
            self.assertTrue(all(valid_package(p) for p in a.packages), a.assistant_id)
            self.assertTrue(valid_https_url(a.site), a.assistant_id)
        seen = {}
        for a in A.ASSISTANTS:
            for alias in a.aliases:
                self.assertNotIn(alias, seen, "%s is used by two assistants" % alias)
                seen[alias] = a.assistant_id
        self.assertEqual(len(A.all_packages()), len(set(A.all_packages())))


class RequestTests(unittest.TestCase):
    def test_three_kinds(self):
        code, kind = R.build("یک قابلیت ساخت عکس", "code", "Claude")
        self.assertEqual(kind, "code")
        self.assertTrue(code.startswith("سلام Claude."))
        self.assertIn("=== PACK code.v1 ===", code)
        self.assertIn("یک قابلیت ساخت عکس", code)
        lang, kind = R.build("پرسش‌وپاسخ دربارهٔ ایران", "lang", "ChatGPT")
        self.assertEqual(kind, "lang")
        self.assertIn("=== PACK lang.v1 ===", lang)
        ask, kind = R.build("تفاوت HTTP و HTTPS چیست؟", "ask", "Gemini")
        self.assertEqual(kind, "ask")
        self.assertIn("سؤال: تفاوت HTTP و HTTPS چیست؟", ask)
        self.assertNotIn("=== PACK", ask)

    def test_unknown_kind_is_a_plain_question_and_empty_wish_is_refused(self):
        self.assertEqual(R.build("سلام", "evil")[1], "ask")
        for bad in ("", "   ", "\x00\x01", None):
            with self.assertRaises(ValueError):
                R.build(bad)

    def test_wish_is_cleaned_and_bounded(self):
        wish = R.clean_wish("  a\x00b\u202e   c\n\n d " + "x" * 2000)
        self.assertLessEqual(len(wish), R.MAX_WISH_CHARS)
        self.assertNotIn("\x00", wish)
        self.assertNotIn("\u202e", wish)
        self.assertTrue(wish.startswith("a b c d"))

    def test_the_request_is_a_pack_the_validator_would_describe(self):
        # the numbers in the request come from the live validator
        from pack_system import limits
        text, _ = R.build("x y", "code", "ChatGPT")
        self.assertIn("حداکثر %d فایل" % limits.MAX_FILES, text)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.now = [5_000_000.0]
        self.store = TeacherStore(self.tmp, lambda: self.now[0])

    def test_create_update_latest_and_persistence(self):
        m = self.store.create("code", "ساخت عکس", "claude", 1234, "abcd")
        self.assertEqual((m["state"], m["assistant"], m["request_chars"]), ("drafted", "claude", 1234))
        self.assertRegex(m["id"], r"^m[0-9a-f]{10}$")
        self.store.update(m["id"], state="sent", route="share", note="ok")
        again = TeacherStore(self.tmp, lambda: self.now[0])
        got = again.get(m["id"])
        self.assertEqual((got["state"], got["route"], got["note"]), ("sent", "share", "ok"))
        self.assertEqual(again.latest()["id"], m["id"])
        self.store.update(m["id"], state="done")
        self.assertIsNone(self.store.latest())
        self.assertEqual(self.store.latest(only_open=False)["id"], m["id"])

    def test_bad_updates_are_refused(self):
        m = self.store.create("ask", "سلام", "chatgpt")
        for bad in ({"state": "weird"}, {"route": "teleport"}, {"hacker": 1}):
            with self.assertRaises(ValueError):
                self.store.update(m["id"], **bad)
        with self.assertRaises(ValueError):
            self.store.create("evil", "x")
        self.assertIsNone(self.store.update("m0000000000", state="done"))

    def test_caps_and_expiry(self):
        for i in range(20):
            self.store.create("ask", "q%d" % i, "chatgpt")
        self.assertEqual(len(self.store.missions()), 12)
        self.now[0] += 8 * 24 * 3600
        self.assertEqual(self.store.missions(), [])

    def test_damaged_file_is_set_aside_not_trusted(self):
        self.store.create("ask", "q", "chatgpt")
        with open(self.store.path, "w") as handle:
            handle.write("{not json")
        self.assertEqual(self.store.missions(), [])
        self.assertTrue(any(n.startswith("state.json.corrupt") for n in os.listdir(self.store.dir)))
        with open(self.store.path, "w") as handle:
            json.dump({"v": 1, "missions": [{"id": "../../x", "kind": "ask", "state": "drafted", "created": 1}, "junk", 5,
                                            {"id": "m0123456789", "kind": "ask", "state": "bogus", "created": self.now[0]}],
                       "allow": {"not a package": 9e9, "com.a.b": "x", "com.ok.app": self.now[0] + 100}}, handle)
        self.assertEqual(self.store.missions(), [])
        self.assertEqual(self.store.allowed_now(), frozenset({"com.ok.app"}))

    def test_allow_list(self):
        expires = self.store.allow("com.openai.chatgpt", 30)
        self.assertEqual(expires, self.now[0] + 1800)
        self.assertEqual(self.store.allowed_now(), frozenset({"com.openai.chatgpt"}))
        self.assertEqual(self.store.allow_list(), [("com.openai.chatgpt", 1800)])
        self.now[0] += 1801
        self.assertEqual(self.store.allowed_now(), frozenset())
        self.store.allow("com.a.b", 10_000)                        # clipped to the maximum
        self.assertEqual(self.store.allow_list()[0][1], 120 * 60)
        with self.assertRaises(ValueError):
            self.store.allow("bad name")
        self.assertEqual(self.store.revoke("com.a.b"), 1)
        self.assertEqual(self.store.revoke("com.a.b"), 0)
        for i in range(12):
            self.store.allow("com.app%d.x" % i, 5)
        self.assertEqual(len(self.store.allowed_now()), 8)
        self.assertEqual(self.store.revoke(), 8)


class RecipeValidationTests(unittest.TestCase):
    def test_default_recipe_is_valid(self):
        norm = RC.validate(RC.DEFAULT_RECIPE)
        self.assertEqual(norm["steps"][0], {"op": "open"})
        self.assertLessEqual(len(norm["steps"]), RC.MAX_STEPS)

    def test_rejections(self):
        base = {"steps": [{"op": "open"}]}
        bad = [{"steps": []}, {"steps": "x"}, {"steps": [{"op": "exec"}]}, {"steps": [{"op": "open", "cmd": "rm"}]},
               {"steps": [{"op": "wait", "seconds": 999}]}, {"steps": [{"op": "wait", "seconds": True}]},
               {"steps": [{"op": "click"}]}, {"steps": [{"op": "click", "any": []}]}, {"steps": [{"op": "click", "any": ["x" * 80]}]},
               {"steps": [{"op": "type", "text": "x" * 400}]}, {"steps": [{"op": "key", "name": "power"}]},
               {"steps": [{"op": "scroll", "times": 50}]}, {"steps": [{"op": "open"}] * (RC.MAX_STEPS + 1)},
               dict(base, package="bad package"), dict(base, site="http://x.com"), "not a dict", None, {"steps": ["open"]}]
        for recipe in bad:
            with self.assertRaises(ValueError, msg=str(recipe)[:60]):
                RC.validate(recipe)

    def test_extract_answer_drops_the_echo_and_labels(self):
        request = "لطفاً یک بسته بنویس که عکس بسازد و آن را توضیح بده"
        texts = ["ChatGPT", request[:150], "Copy", "این پاسخ اصلی است و به اندازهٔ کافی بلند است", "Share"]
        self.assertEqual(RC.extract_answer(texts, request), "این پاسخ اصلی است و به اندازهٔ کافی بلند است")


class RecipeRunnerTests(TeacherCase):
    def runner(self, **kwargs):
        return RC.RecipeRunner(self.doors, sleep=lambda s: (self.mono.__setitem__(0, self.mono[0] + s)), clock=lambda: self.mono[0], **kwargs)

    def test_default_recipe_gets_an_answer_from_a_scripted_chat_app(self):
        state = install_chat_script(self.jvm, "این پاسخ کامل و بلند دستیار است که باید برداشته شود")
        native_facade.set_allowed_apps_provider(lambda: {"com.openai.chatgpt"})
        result = self.runner().run(RC.DEFAULT_RECIPE, "سؤال من از دستیار", "com.openai.chatgpt")
        self.assertTrue(result.ok, result.to_dict())
        self.assertIn("این پاسخ کامل و بلند دستیار است", result.text)
        self.assertNotIn("Stop generating", result.text)
        self.assertEqual(state["typed"], "سؤال من از دستیار")
        self.assertEqual(self.jvm.started[0].extras.get("EXTRA_TEXT"), None)           # opened the app, did not share

    def test_not_allowed_stops_at_once(self):
        install_chat_script(self.jvm, "answer text that is long enough")
        native_facade.set_allowed_apps_provider(lambda: set())
        result = self.runner().run(RC.DEFAULT_RECIPE, "q", "com.openai.chatgpt")
        self.assertEqual((result.ok, result.code), (False, "not_allowed"))
        self.assertEqual(self.jvm.clicks, [])

    def test_missing_field_is_reported(self):
        install_chat_script(self.jvm, "answer", works=False)
        native_facade.set_allowed_apps_provider(lambda: {"com.openai.chatgpt"})
        result = self.runner().run(RC.DEFAULT_RECIPE, "q", "com.openai.chatgpt")
        self.assertFalse(result.ok)
        self.assertIn(result.code, ("not_found", "no_input"))

    def test_a_screen_that_never_settles_times_out(self):
        install_chat_script(self.jvm, "answer", generating_reads=10 ** 6)
        native_facade.set_allowed_apps_provider(lambda: {"com.openai.chatgpt"})
        recipe = {"steps": [{"op": "open"}, {"op": "type", "text": "{request}", "hint_any": [""]}, {"op": "click", "any": ["Send"]},
                            {"op": "wait_stable", "seconds": 3, "max_seconds": 20}]}
        result = self.runner().run(recipe, "q", "com.openai.chatgpt")
        self.assertEqual((result.ok, result.code), (False, "timeout"))
        self.assertLess(self.mono[0], 60)

    def test_cancel_between_steps(self):
        install_chat_script(self.jvm, "answer")
        native_facade.set_allowed_apps_provider(lambda: {"com.openai.chatgpt"})
        flag = threading.Event()
        flag.set()
        result = self.runner(cancelled=flag.is_set).run(RC.DEFAULT_RECIPE, "q", "com.openai.chatgpt")
        self.assertEqual((result.ok, result.code), (False, "cancelled"))

    def test_bad_recipe_and_no_package(self):
        self.assertEqual(self.runner().run({"steps": [{"op": "evil"}]}, "q", "a.b").code, "bad_recipe")
        self.assertEqual(self.runner().run({"steps": [{"op": "open"}]}, "q", "").code, "no_package")

    def test_clipboard_capture_step(self):
        self.jvm.clipboard = "copied answer"
        result = self.runner().run({"steps": [{"op": "capture_clipboard"}]}, "q", "a.b")
        self.assertEqual((result.ok, result.text), (True, "copied answer"))


class CaptureTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(C.classify(PACK_TEXT), "pack")
        self.assertEqual(C.classify("=== PACK lang.v1 ===\nid: x"), "pack")
        self.assertEqual(C.classify('{"schema": "code.v9", "id": "x"}'), "other_pack")
        self.assertEqual(C.classify('{"schema": "ext.v1"}'), "extension")
        self.assertEqual(C.classify("hello"), "text")
        self.assertEqual(C.classify("   "), "empty")
        self.assertEqual(C.classify(None), "empty")

    def test_pick_rules(self):
        sha = C.sha16(PACK_TEXT)
        source, text, klass, skipped = C.pick("code", [("clipboard", PACK_TEXT)], sha)
        self.assertIsNone(source)                                  # our own request is never the answer
        self.assertEqual(skipped, [("clipboard", "is_the_request")])
        source, text, klass, skipped = C.pick("code", [("screen", "chatter"), ("clipboard", PACK_TEXT)])
        self.assertEqual((source, klass), ("clipboard", "pack"))
        self.assertEqual(skipped, [("screen", "no_pack")])
        self.assertEqual(C.pick("lang", [("clipboard", "no pack here")])[0], None)
        self.assertEqual(C.pick("ask", [("clipboard", "some answer")])[:3], ("clipboard", "some answer", "text"))
        self.assertEqual(C.pick("ask", [("clipboard", "   ")])[0], None)

    def test_shared_text_must_be_newer_and_named_shared(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        old, new, other = (os.path.join(tmp, n) for n in ("shared_1.txt", "shared_2.txt", "notes.txt"))
        for path, body in ((old, "old"), (new, "new"), (other, "other")):
            with open(path, "w") as handle:
                handle.write(body)
        os.utime(old, (100, 100))
        os.utime(other, (time.time() + 50, time.time() + 50))
        self.assertEqual(C.newest_shared_text(tmp, 1000), ("shared_2.txt", "new"))
        self.assertIsNone(C.newest_shared_text(tmp, time.time() + 1000))
        self.assertIsNone(C.newest_shared_text(os.path.join(tmp, "missing"), 0))
        os.symlink(new, os.path.join(tmp, "shared_3.txt"))
        os.utime(new, (100, 100))
        self.assertIsNone(C.newest_shared_text(tmp, 1000))          # a link is never followed


class ServiceTests(TeacherCase):
    def test_draft_builds_a_mission_without_sending_anything(self):
        r = self.svc.draft("یک قابلیت ساخت عکس", "code", "claude")
        self.assertTrue(r["ok"])
        self.assertEqual((r["assistant"], r["mission"]["state"]), ("claude", "drafted"))
        self.assertGreater(r["request_chars"], 3000)
        self.assertEqual(self.jvm.started, [])
        self.assertEqual(self.jvm.clipboard, None)
        flat = json.dumps(self.hub.entries, ensure_ascii=False)
        self.assertNotIn("ساخت عکس", flat)                          # the wish never goes to the audit log
        self.assertEqual(self.hub.entries[0][0], "teacher.draft")

    def test_default_assistant_and_empty_wish(self):
        self.assertEqual(self.svc.draft("x y", "ask")["assistant"], "chatgpt")
        self.jvm.installed = {"com.anthropic.claude"}
        self.assertEqual(self.svc.default_assistant(), "claude")
        self.jvm.installed = set()
        self.assertEqual(self.svc.default_assistant(), "chatgpt")
        self.assertEqual(self.svc.draft("   ")["code"], "empty_wish")

    def test_assistants_report_what_is_visible(self):
        rows = {r["id"]: r for r in self.svc.assistants()}
        self.assertTrue(rows["chatgpt"]["installed"] and rows["claude"]["installed"])
        self.assertFalse(rows["gemini"]["installed"])
        self.assertEqual(rows["claude"]["package"], "com.anthropic.claude")

    def test_deliver_by_share_goes_straight_into_the_app(self):
        mission = self.svc.draft("یک قابلیت", "code", "claude")["mission"]
        r = self.svc.deliver(mission["id"])
        self.assertEqual((r["ok"], r["route"]), (True, "share"))
        intent = self.jvm.started[0]
        self.assertEqual((intent.action, intent.package), ("SEND", "com.anthropic.claude"))
        self.assertIn("=== PACK code.v1 ===", intent.extras["EXTRA_TEXT"])
        got = self.svc.store.get(mission["id"])
        self.assertEqual((got["state"], got["route"]), ("sent", "share"))

    def test_a_share_that_fails_falls_back_to_copy_and_open(self):
        mission = self.svc.draft("x", "ask", "chatgpt")["mission"]
        self.jvm.raise_on["startActivity"] = [ActivityNotFoundException("no share target")]
        r = self.svc.deliver(mission["id"])
        self.assertEqual((r["ok"], r["route"]), (True, "copy_open"))
        self.assertIn("سؤال: x", self.jvm.clipboard)
        self.assertEqual(self.jvm.started[-1].action, "MAIN")

    def test_an_app_that_is_not_there_uses_the_website(self):
        self.jvm.installed = set()
        mission = self.svc.draft("x", "ask", "gemini")["mission"]
        r = self.svc.deliver(mission["id"])
        self.assertEqual((r["ok"], r["route"]), (True, "site"))
        self.assertIn("سؤال: x", self.jvm.clipboard)
        self.assertEqual((self.jvm.started[-1].action, self.jvm.started[-1].uri.text), ("VIEW", A.get("gemini").site))

    def test_explicit_route_and_failures(self):
        mission = self.svc.draft("x", "ask", "chatgpt")["mission"]
        r = self.svc.deliver(mission["id"], route="copy_open")
        self.assertEqual((r["ok"], r["route"], r["steps"][0][0]), (True, "copy_open", "copy"))
        self.jvm.raise_on["startActivity"] = ActivityNotFoundException("x")
        r = self.svc.deliver(mission["id"], route="site")
        self.assertEqual((r["ok"], r["code"]), (False, "open_failed"))
        self.assertTrue(r["copied"])
        self.assertEqual(self.svc.deliver("m0000000000")["code"], "no_mission")

    def test_capture_does_not_take_our_own_request_back(self):
        mission = self.svc.draft("x", "code", "chatgpt")["mission"]
        self.svc.deliver(mission["id"], route="copy_open")          # the clipboard now holds OUR request
        r = self.svc.capture(mission["id"])
        self.assertEqual((r["ok"], r["code"]), (False, "nothing"))
        self.assertIn(("clipboard", "is_the_request"), r["skipped"])
        self.jvm.clipboard = PACK_TEXT
        r = self.svc.capture(mission["id"])
        self.assertEqual((r["ok"], r["source"], r["klass"]), (True, "clipboard", "pack"))
        self.assertEqual(r["text"], PACK_TEXT)
        self.assertEqual(self.svc.store.get(mission["id"])["state"], "captured")

    def test_capture_prefers_a_shared_file_and_retires_it(self):
        mission = self.svc.draft("x", "code", "chatgpt")["mission"]
        path = os.path.join(self.hub.inbox_dir(), "shared_1700.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(PACK_TEXT)
        os.utime(path, (self.now[0] + 1, self.now[0] + 1))
        self.jvm.clipboard = "something else"
        r = self.svc.capture(mission["id"])
        self.assertEqual((r["ok"], r["source"]), (True, "shared"))
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(os.path.join(self.hub.inbox_dir(), "done_shared_1700.txt")))
        self.assertFalse(self.svc.capture(mission["id"])["ok"])

    def test_capture_of_a_plain_answer(self):
        mission = self.svc.draft("تفاوت HTTP و HTTPS", "ask", "chatgpt")["mission"]
        self.jvm.clipboard = "HTTPS یعنی HTTP با رمزنگاری."
        r = self.svc.capture()                                      # no id: the newest open mission
        self.assertEqual((r["ok"], r["klass"]), (True, "text"))
        done = self.svc.finish(mission["id"], "done", answer=r["text"])
        self.assertEqual((done["state"], done["answer"]), ("done", "HTTPS یعنی HTTP با رمزنگاری."))
        self.assertEqual(self.svc.capture()["code"], "no_mission")

    def test_capture_code_wish_ignores_chatter(self):
        self.svc.draft("x", "code", "chatgpt")
        self.jvm.clipboard = "just some text"
        r = self.svc.capture()
        self.assertEqual((r["ok"], r["skipped"]), (False, [("clipboard", "no_pack")]))

    def test_allowances_expire(self):
        self.svc.allow_app("com.openai.chatgpt", 30)
        self.assertEqual(self.svc.allowed_apps(), [("com.openai.chatgpt", 1800)])
        self.now[0] += 1900
        self.assertEqual(self.svc.allowed_apps(), [])
        self.assertEqual(self.svc.revoke_apps(), 0)

    # ---- the typing run -----------------------------------------------------------------------------------------------
    def test_screen_run_needs_the_service_and_the_users_allowance(self):
        mission = self.svc.draft("x", "ask", "chatgpt")["mission"]
        self.jvm.connected = False
        self.assertEqual(self.svc.start_screen_run(mission["id"])["code"], "not_enabled")
        self.jvm.connected = True
        r = self.svc.start_screen_run(mission["id"])
        self.assertEqual((r["ok"], r["code"], r["package"]), (False, "not_allowed", "com.openai.chatgpt"))
        self.jvm.features = frozenset({"file_chooser"})
        self.assertEqual(self.svc.start_screen_run(mission["id"])["code"], "native_feature_missing")
        self.jvm.features = frozenset({"accessibility"})
        self.jvm.installed = set()
        self.assertEqual(self.svc.start_screen_run(mission["id"])["code"], "no_app")

    def test_screen_run_reads_the_answer(self):
        mission = self.svc.draft("سؤال من", "ask", "chatgpt")["mission"]
        install_chat_script(self.jvm, "این پاسخ کامل و بلند دستیار است که باید برداشته شود")
        self.svc.allow_app("com.openai.chatgpt", 30)
        r = self.svc.start_screen_run(mission["id"])
        self.assertEqual((r["ok"], r["code"], r["recipe"]), (True, "started", "default"))
        got = self.svc.store.get(mission["id"])
        self.assertEqual((got["state"], got["route"]), ("captured", "screen"))
        cap = self.svc.capture(mission["id"])
        self.assertEqual((cap["ok"], cap["source"]), (True, "screen"))
        self.assertIn("پاسخ کامل", cap["text"])
        self.assertEqual(self.jvm.started[-1].action, "MAIN")        # our own app was brought back to the front
        self.assertEqual(len(self.jvm.notified), 1)
        kinds = [e[0] for e in self.hub.entries]
        self.assertIn("teacher.screen_run", kinds)
        self.assertIn("teacher.screen_run_end", kinds)

    def test_a_failed_run_leaves_the_mission_open_with_the_reason(self):
        mission = self.svc.draft("x", "ask", "chatgpt")["mission"]
        install_chat_script(self.jvm, "answer", works=False)
        self.svc.allow_app("com.openai.chatgpt", 30)
        self.svc.start_screen_run(mission["id"])
        got = self.svc.store.get(mission["id"])
        self.assertEqual(got["state"], "sent")
        self.assertTrue(got["note"].startswith("ناموفق"))

    def test_only_one_run_at_a_time(self):
        mission = self.svc.draft("x", "ask", "chatgpt")["mission"]
        install_chat_script(self.jvm, "answer text that is long enough")
        self.svc.allow_app("com.openai.chatgpt", 30)
        blocker = threading.Thread(target=time.sleep, args=(0.4,))
        blocker.start()
        self.svc._thread = blocker
        self.assertEqual(self.svc.start_screen_run(mission["id"])["code"], "busy")
        blocker.join()

    def test_cancel(self):
        self.svc.draft("x", "ask", "chatgpt")
        self.svc.draft("y", "code", "claude")
        self.assertEqual(self.svc.cancel(), 2)
        self.assertIsNone(self.svc.store.latest())

    def test_pack_recipes_are_preferred_and_must_be_valid(self):
        registry = Registry()
        good = {"assistant": "chatgpt", "version": 3, "steps": [{"op": "open"}, {"op": "capture_clipboard"}]}
        registry.add_recipe("pack_a", "r_good", good)
        registry.add_recipe("pack_b", "r_bad", {"assistant": "chatgpt", "version": 9, "steps": [{"op": "exec"}]})
        registry.add_recipe("pack_c", "r_other", {"assistant": "claude", "version": 9, "steps": [{"op": "open"}]})
        svc = self.make_service(registry=registry)
        recipe, origin = svc.recipe_for("chatgpt")
        self.assertEqual((origin, recipe["version"]), ("pack", 3))
        self.assertEqual(svc.recipe_for("gemini")[1], "default")

    def test_get_service_is_cached_per_hub_and_installs_the_allow_provider(self):
        one = S.get_service(self.hub)
        self.assertIs(one, S.get_service(self.hub))
        one.store.allow("com.openai.chatgpt", 5)
        self.assertEqual(native_facade._allowed_now(), frozenset({"com.openai.chatgpt"}))
        self.assertIsNone(S.get_service(object()))


class TeacherFacadeTests(unittest.TestCase):
    def test_what_a_pack_may_do(self):
        registry = Registry()
        registry.add_recipe("p", "r1", {"assistant": "claude", "steps": [{"op": "open"}]})
        api = for_pack("demo_pack", ("teacher",), registry)
        self.assertEqual({a["id"] for a in api.assistants()}, {a.assistant_id for a in A.ASSISTANTS})
        self.assertIn("=== PACK code.v1 ===", api.build_request("یک چیز", "code", "claude"))
        self.assertEqual(len(api.recipes_for("claude")), 1)
        self.assertEqual(api.recipes_for("grok"), [])
        self.assertIs(api.validate_recipe({"steps": [{"op": "open"}]}), True)
        self.assertIn("گام 1", api.validate_recipe({"steps": [{"op": "nope"}]}))
        for private in ("deliver", "start_screen_run", "doors", "store"):
            self.assertFalse(hasattr(api, private), private)


if __name__ == "__main__":
    unittest.main()
