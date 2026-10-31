"""
Prompt 958 - the Python side of what the Android activity calls: `platform_boot`.

* a text another app shares INTO this one (the user presses «Share» in an assistant app and chooses this app) is saved exactly, once, in
  the hub's inbox - nothing is run, installed or sent; the file is what the teacher's «جواب آمد» reads;
* the page is told whether a request is waiting for that answer (`mission_open`) so that it can ask the chat for it;
* nothing here can raise into Java: every outcome is a small JSON string;
* the folder names `platform_boot` uses are the app's own (a test starts the real storage layout and compares).
It proves the Python logic; how the real Share sheet or ChatGPT app behaves is not proven here.
"""

import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import android_entry
import platform_boot
from brain_hub import builtin_tools
from brain_hub import service as hub_service
from memory.memory_system import MemorySystem
from platform_layer import reset_platform, set_platform
from teacher import capture
from teacher.store import TeacherStore
from tests import pack_support_prompt958 as S
from tests.test_persian_teacher_chat_prompt958 import TeacherChatCase

NAME_RE = re.compile(r"^shared_\d{13}_[0-9a-f]{6}\.txt\Z")
PERSIAN_TEXT = "سلام!\nاین جوابِ «دستیار» است 🙂\n```json\n{\"a\": 1}\n```\n"


class PlatformCase(unittest.TestCase):
    def setUp(self):
        self.files = tempfile.mkdtemp(prefix="pb_")
        self.addCleanup(shutil.rmtree, self.files, ignore_errors=True)
        self.inbox = platform_boot.inbox_dir(self.files)

    def share(self, text):
        raw = platform_boot.on_shared_text(self.files, text)
        self.assertIsInstance(raw, str)
        return json.loads(raw)

    def shared_names(self, prefix="shared_"):
        try:
            return sorted(n for n in os.listdir(self.inbox) if n.startswith(prefix) and n.endswith(".txt"))
        except OSError:
            return []


class SharedTextTests(PlatformCase):
    def test_the_text_is_saved_exactly_in_the_inbox(self):
        out = self.share(PERSIAN_TEXT)
        self.assertEqual((out["ok"], out["code"], out["truncated"]), (True, "saved", False))
        self.assertEqual(out["chars"], len(PERSIAN_TEXT))
        self.assertRegex(out["name"], NAME_RE)
        with open(os.path.join(self.inbox, out["name"]), "rb") as handle:
            self.assertEqual(handle.read().decode("utf-8"), PERSIAN_TEXT)

    def test_nothing_half_written_is_left_behind(self):
        self.share(PERSIAN_TEXT)
        self.assertEqual([n for n in os.listdir(self.inbox) if n.endswith(".partial")], [])
        self.assertEqual(len(os.listdir(self.inbox)), 1)

    def test_the_teacher_finds_what_was_shared(self):
        out = self.share(PERSIAN_TEXT)
        found = capture.newest_shared_text(self.inbox, time.time() - 60)
        self.assertEqual(found, (out["name"], PERSIAN_TEXT))

    def test_two_shares_are_two_files_and_the_newest_wins(self):
        first = self.share("اول")
        second = self.share("دوم")
        self.assertNotEqual(first["name"], second["name"])
        os.utime(os.path.join(self.inbox, first["name"]), (time.time() - 100, time.time() - 100))
        self.assertEqual(capture.newest_shared_text(self.inbox, time.time() - 1000)[1], "دوم")

    def test_an_empty_or_wrongly_typed_share_is_refused_and_writes_nothing(self):
        for bad in (None, "", "   \n\t", 5, b"bytes", ["x"]):
            out = self.share(bad)
            self.assertEqual((out["ok"], out["code"]), (False, "empty"), repr(bad))
        self.assertFalse(os.path.exists(self.inbox))

    def test_a_very_long_text_is_cut_and_says_so(self):
        out = self.share("ا" * (platform_boot.MAX_SHARED_CHARS + 10))
        self.assertEqual((out["ok"], out["truncated"], out["chars"]), (True, True, platform_boot.MAX_SHARED_CHARS))
        size = os.path.getsize(os.path.join(self.inbox, out["name"]))
        self.assertLessEqual(size, capture.MAX_TEXT_CHARS * 4)               # the teacher still reads it whole

    def test_a_text_with_a_lone_surrogate_or_a_nul_is_still_saved(self):
        out = self.share("a\ud800b\x00c")
        self.assertTrue(out["ok"])
        with open(os.path.join(self.inbox, out["name"]), "rb") as handle:
            self.assertEqual(handle.read().decode("utf-8"), "a?b\x00c")

    def test_old_shared_texts_are_pruned_but_the_newest_stays(self):
        os.makedirs(self.inbox)
        base = time.time() - 10_000
        for index in range(20):
            for prefix in ("shared_", "done_shared_"):
                path = os.path.join(self.inbox, "%s%d_%02d.txt" % (prefix, index, index))
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("x")
                os.utime(path, (base + index, base + index))
        out = self.share("تازه")
        keep = platform_boot.KEEP_SHARED_FILES
        names = self.shared_names()
        self.assertEqual(len(names), keep)
        self.assertIn(out["name"], names)
        self.assertNotIn("shared_0_00.txt", names)
        self.assertIn("shared_19_19.txt", names)
        done = self.shared_names("done_shared_")
        self.assertEqual(len(done), keep)
        self.assertIn("done_shared_19_19.txt", done)
        self.assertNotIn("done_shared_0_00.txt", done)

    def test_other_inbox_files_are_never_touched_by_the_pruning(self):
        os.makedirs(self.inbox)
        for name in ("model.task", "pack.json", "notes.txt"):
            with open(os.path.join(self.inbox, name), "w") as handle:
                handle.write("keep me")
        for _ in range(platform_boot.KEEP_SHARED_FILES + 3):
            self.share("متن")
            time.sleep(0.002)
        for name in ("model.task", "pack.json", "notes.txt"):
            self.assertTrue(os.path.exists(os.path.join(self.inbox, name)), name)

    def test_a_stale_partial_file_is_removed_and_a_fresh_one_is_kept(self):
        os.makedirs(self.inbox)
        stale = os.path.join(self.inbox, "shared_1_aaaaaa.txt.partial")
        fresh = os.path.join(self.inbox, "shared_2_bbbbbb.txt.partial")
        for path in (stale, fresh):
            with open(path, "w") as handle:
                handle.write("half")
        old = time.time() - 3600
        os.utime(stale, (old, old))
        self.share("متن")
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(os.path.exists(fresh))

    def test_a_folder_that_cannot_be_made_is_reported_not_raised(self):
        blocker = os.path.join(self.files, "blocker")
        with open(blocker, "w") as handle:
            handle.write("a file where a folder is needed")
        out = json.loads(platform_boot.on_shared_text(blocker, "متن"))
        self.assertEqual((out["ok"], out["code"]), (False, "io_error"))

    def test_the_answer_always_has_the_same_keys(self):
        keys = {"ok", "code", "chars", "name", "truncated", "mission_open", "text"}
        self.assertEqual(set(self.share(PERSIAN_TEXT)), keys)
        self.assertEqual(set(self.share("")), keys)

    def test_without_a_waiting_request_the_text_itself_goes_back_for_the_message_box(self):
        out = self.share(PERSIAN_TEXT)
        self.assertEqual((out["mission_open"], out["text"]), (False, PERSIAN_TEXT))          # exactly: line breaks, quotes, emoji, code fence
        pack = S.text_pack(source="def register(api):\n    pass\n")
        self.assertEqual(self.share(pack)["text"], pack)                                      # a pack keeps every line break and indent

    def test_the_copy_for_the_page_is_what_the_file_holds_even_with_a_lone_surrogate(self):
        out = self.share("a\ud800b\x00c")
        self.assertEqual(out["text"], "a?b\x00c")
        with open(os.path.join(self.inbox, out["name"]), "rb") as handle:
            self.assertEqual(handle.read().decode("utf-8"), out["text"])

    def test_a_text_longer_than_the_message_box_ceiling_is_kept_but_not_offered(self):
        limit = platform_boot.MAX_OFFERED_CHARS
        at_limit = self.share("ب" * limit)
        self.assertEqual(len(at_limit["text"]), limit)
        over = self.share("ب" * (limit + 1))
        self.assertEqual((over["ok"], over["chars"], over["text"]), (True, limit + 1, ""))
        self.assertTrue(os.path.exists(os.path.join(self.inbox, over["name"])))              # still saved: the chat can read it from there
        cut = self.share("ب" * (platform_boot.MAX_SHARED_CHARS + 5))
        self.assertEqual((cut["truncated"], cut["text"]), (True, ""))

    def test_a_refused_share_offers_nothing(self):
        for bad in (None, "", "  "):
            self.assertEqual(self.share(bad)["text"], "")


class MissionOpenTests(PlatformCase):
    def store(self):
        return TeacherStore(platform_boot.hub_root(self.files))

    def test_no_teacher_state_means_no_open_request(self):
        self.assertFalse(self.share("متن")["mission_open"])

    def test_only_a_request_that_waits_for_its_answer_counts(self):
        store = self.store()
        mission = store.create("ask", "یک پرسش")
        expected = (("drafted", False), ("sent", True), ("running", True), ("captured", True), ("proposed", False), ("done", False),
                    ("failed", False), ("cancelled", False))
        for state, open_ in expected:
            store.update(mission["id"], state=state)
            self.assertEqual(self.share("متن")["mission_open"], open_, state)

    def test_a_waiting_request_reads_the_file_itself_so_no_copy_is_offered(self):
        store = self.store()
        mission = store.create("ask", "یک پرسش")
        store.update(mission["id"], state="sent")
        out = self.share(PERSIAN_TEXT)
        self.assertEqual((out["ok"], out["mission_open"], out["text"]), (True, True, ""))
        self.assertTrue(os.path.exists(os.path.join(self.inbox, out["name"])))

    def test_a_damaged_teacher_state_never_breaks_the_share(self):
        directory = os.path.join(platform_boot.hub_root(self.files), "teacher")
        os.makedirs(directory)
        with open(os.path.join(directory, "state.json"), "w") as handle:
            handle.write("{ not json")
        out = self.share("متن")
        self.assertEqual((out["ok"], out["mission_open"]), (True, False))


class LayoutMatchesTheAppTests(PlatformCase):
    def test_the_constants_are_the_apps_own(self):
        from persian_brain import hub_teacher
        self.assertEqual(platform_boot.HUB_DIRNAME, hub_service.ROOT_DIRNAME)
        self.assertEqual(platform_boot.INBOX_DIRNAME, builtin_tools.INBOX_DIR)
        self.assertEqual(platform_boot.MAX_SHARED_CHARS, capture.MAX_TEXT_CHARS)
        self.assertEqual(platform_boot._OPEN_FOR_CHAT, hub_teacher.OPEN_FOR_CHAT)
        self.assertEqual(capture.SHARED_PREFIX, "shared_")

    def test_the_inbox_is_the_one_the_real_app_uses_on_the_phone(self):
        set_platform(android_entry.AndroidFilesDirAdapter(self.files))
        self.addCleanup(reset_platform)
        memory = MemorySystem()
        self.addCleanup(memory._conn.close)
        root = hub_service.default_root(memory)
        hub = hub_service.HubService(root, memory=memory)
        self.addCleanup(hub.close)
        self.assertEqual(os.path.abspath(platform_boot.hub_root(self.files)), os.path.abspath(root))
        self.assertEqual(os.path.abspath(platform_boot.inbox_dir(self.files)), os.path.abspath(hub.inbox_dir()))

    def test_prepare_still_never_raises_and_reports(self):
        report = platform_boot.prepare(self.files)
        self.assertIsInstance(report, dict)
        self.assertIn("ok", report)
        from pack_system import boot
        self.addCleanup(boot.reset_for_tests)
        self.assertIsInstance(platform_boot.prepare(os.path.join(self.files, "no", "such", "\0bad")), dict)


class SharedTextReachesTheChatTests(TeacherChatCase):
    """The text saved by `platform_boot.on_shared_text` is exactly what the chat's «جواب آمد» reads."""

    def test_a_shared_answer_is_read_proposed_and_only_installed_after_the_yes(self):
        self.ask_and_confirm()
        self.jvm.clipboard = None
        out = json.loads(platform_boot.on_shared_text(self.tmp, S.lang_pack(pid="fa_via_share"), clock=self.clock))
        self.assertEqual((out["ok"], out["mission_open"]), (True, True))
        reply = self.say("جواب آمد")
        self.assertIn("از متنی که به این برنامه اشتراک‌گذاری کردی", reply)
        self.assertEqual(self.pending()[0], "pack_install")
        self.assertEqual(self.pm().list(), [])                                   # nothing installed before the «بله»
        names = os.listdir(self.inbox())
        self.assertEqual([n for n in names if n.startswith("shared_")], [])
        self.assertEqual(len([n for n in names if n.startswith("done_shared_")]), 1)

    def test_the_pages_flag_follows_the_state_of_the_request(self):
        self.assertFalse(json.loads(platform_boot.on_shared_text(self.tmp, "متن اول", clock=self.clock))["mission_open"])
        self.say("از ChatGPT بخواه یه قابلیت ساخت عکس برام بسازه")
        self.assertFalse(json.loads(platform_boot.on_shared_text(self.tmp, "متن دوم", clock=self.clock))["mission_open"])      # only drafted: nothing sent yet
        self.say("بله")
        self.assertTrue(json.loads(platform_boot.on_shared_text(self.tmp, "متن سوم", clock=self.clock))["mission_open"])


if __name__ == "__main__":
    unittest.main()
