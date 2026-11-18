"""
Prompt 959 (stage B, «مغز خودکار») - the step after the download: the finished file is verified, loaded into the engine and asked a real question
for the first time. That step takes minutes on a phone and CANNOT be interrupted, so while it runs:

* every chat message is answered at once (the chat never waits for the install or the first test),
* «pause», «delete» and «ایست» do not pretend to stop it and remove nothing from under it,
* the status and the free-sentence line say that the brain is being installed (not «downloading 100%»),
* and the stop commands that DO act (the emergency stop, a pause after the grace time) cut the connections the way the service promises.

The engine is a fake whose first question is held by the test; nothing here says how the real engine behaves.
"""
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from persian_brain import hub_messages_ownbrain as BM
from tests.ownbrain_support_prompt959 import ThreadedOwnBrainApp
from tests.test_ownbrain_threaded_prompt959 import FREE, wait_until


class InstallingApp(ThreadedOwnBrainApp):
    """A threaded app whose engine holds the first test question until `self.bridge.gate` opens: the brain stays in the installing phase."""

    def setUp(self):
        super().setUp()
        self.bridge.gate = threading.Event()
        self.addCleanup(self.bridge.gate.set)

    def reach_installing(self):
        self.start_download()
        self.cdn.gate.set()
        wait_until(self, lambda: self.ob.status()["phase"] == "installing", what="the installing phase")
        wait_until(self, lambda: bool(self.bridge.chats), what="the first test question reaching the engine")

    def finish_install(self):
        self.bridge.gate.set()
        self.assertTrue(self.ob.wait(30), "the worker did not finish")


class InstallingStepTests(InstallingApp):
    def test_a_pause_says_the_step_cannot_be_interrupted_and_changes_nothing(self):
        self.reach_installing()
        reply = self.ask(BM.PAUSE)
        self.assertEqual(reply, BM.nothing_running(self.ob.status()))
        self.assertIn("نمی‌شود وسطش قطع کرد", reply)
        self.assertEqual(self.ob.status()["phase"], "installing")
        self.assertFalse(self.bridge.gate.is_set())
        self.assertEqual(self.bridge.cancels, 0, "the engine was not told to stop")

    def test_a_delete_does_not_ask_and_removes_nothing_from_under_the_install(self):
        self.reach_installing()
        files_before = sorted(os.listdir(self.own_dir))
        model_file = self.hub.model_file_path(self.ob.choice("light").model_id)
        self.assertTrue(model_file and os.path.isfile(model_file), "the verified file is already in the models folder")
        reply = self.ask(BM.DELETE)
        self.assertEqual(reply, BM.busy_installing())
        self.assertIsNone(self.pending_own(), "no question may be opened for something that cannot be done")
        stray = self.ask("بله")
        self.assertNotIn("پاک شد", stray, "a stray yes is not a delete order")
        self.assertEqual(self.ob.status()["phase"], "installing")
        self.assertEqual(sorted(os.listdir(self.own_dir)), files_before)
        self.assertTrue(os.path.isfile(model_file), "nothing was removed from under the install")
        self.finish_install()
        self.assertEqual(self.ob.status()["phase"], "ready", "the install ended normally, nothing was removed under it")

    def test_the_service_itself_refuses_to_delete_under_the_install(self):
        """The chat answers before it asks; this is the service's own guard (a caller that does not go through the chat)."""
        self.reach_installing()
        model_file = self.hub.model_file_path(self.ob.choice("light").model_id)
        self.assertEqual(self.ob.delete(), {"freed": 0, "had": True, "busy": True})
        self.assertTrue(os.path.isfile(model_file), "the file the install is using is still there")
        self.assertEqual(self.ob.status()["phase"], "installing")
        self.assertFalse(self.ob.cancel(), "nothing is cancelled either: the step cannot be interrupted")
        self.assertFalse(self.ob.halt())
        self.finish_install()
        self.assertEqual(self.ob.status()["phase"], "ready")
        self.assertEqual(self.ob.delete()["busy"], False)
        self.assertEqual(self.ob.status()["phase"], "idle", "once the step has ended the same order works")

    def test_the_emergency_word_does_not_claim_to_stop_the_install_and_says_why(self):
        self.reach_installing()
        reply = self.ask("ایست")
        self.assertNotIn(BM.halted_note(), reply)
        self.assertIn(BM.install_not_stoppable_note(), reply)
        self.assertEqual(self.ob.status()["phase"], "installing")
        self.assertEqual(self.bridge.cancels, 0)
        self.finish_install()
        self.assertEqual(self.ob.status()["phase"], "ready")

    def test_the_status_and_a_free_sentence_say_it_is_being_installed(self):
        self.reach_installing()
        status = self.ask("وضعیت مغز")
        self.assertIn("دارم مغز را نصب و برای بار اول آزمایش می‌کنم", status)
        self.assertNotIn("۱۰۰٪", status)
        free = self.ask(FREE)
        self.assertIn(BM.lead_line("installing"), free)
        self.assertNotIn("در حال گرفته‌شدن", free)
        self.assertNotIn("آماده است ✅", free)

    def test_a_wish_or_a_continue_during_the_install_starts_nothing_new(self):
        self.reach_installing()
        before = len(self.cdn.requests)
        for text in ("مغز خودت را بگیر", BM.RESUME, BM.RETRY):
            reply = self.ask(text)
            self.assertIn("همین الان دارم روی مغزِ خودم کار می‌کنم", reply, text)
            self.assertNotIn("دانلودی نیست", reply, text)
        self.assertEqual(len(self.cdn.requests), before)
        self.assertEqual(len(self.bridge.loads), 1, "the model was loaded once, not again")
        self.finish_install()

    def test_when_the_first_test_answer_arrives_the_brain_is_ready_and_answers(self):
        self.reach_installing()
        self.finish_install()
        st = self.ob.status()
        self.assertEqual(st["phase"], "ready", st)
        reply = self.ask(FREE)
        self.assertIn("سلام! من مغزِ آزمایشی هستم.", reply)
        self.assertEqual(self.ask("وضعیت مغز").count("آماده است ✅"), 1)

    def test_the_chat_never_waits_for_the_install(self):
        self.reach_installing()
        texts = ["سلام", "ساعت چنده؟", "وضعیت مغز", FREE, "چه کارهایی بلدی؟", BM.DELETE, "ایست", "چرا؟"]
        for text in texts:
            began = time.monotonic()
            reply = self.ask(text)
            self.assertLess(time.monotonic() - began, 3.0, "«%s» waited for the install" % text)
            self.assertTrue(reply)
        self.assertEqual(self.ob.status()["phase"], "installing", "still installing: the questions did not disturb it")
        self.assertTrue(self.model_status("light") is not None)                 # the registry can be read while the long step runs
        self.finish_install()


class StopCommandsTests(ThreadedOwnBrainApp):
    """What `halt` and `cancel` do to the network: the emergency stop cuts the connections at once; a pause waits a grace time for the downloader
    to see the stop by itself and cuts them only if it does not (a worker stuck in a read of a dead connection)."""

    def test_the_emergency_stop_cuts_the_connections_at_once(self):
        self.start_download()
        with mock.patch("brain_hub.ownbrain.GRACE_SECONDS", 30.0), mock.patch("net_tools.transport.abort_all", return_value=1) as cut:
            began = time.monotonic()
            self.assertTrue(self.ob.halt())
            self.assertLess(time.monotonic() - began, 5.0)
        self.assertGreaterEqual(cut.call_count, 1)
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("paused", "halted"), st)

    def test_a_pause_that_the_downloader_sees_does_not_cut_the_connections(self):
        self.start_download()
        with mock.patch("net_tools.transport.abort_all", return_value=0) as cut:
            self.assertTrue(self.ob.cancel())
        self.assertEqual(cut.call_count, 0, "a download that stops by itself needs no cut")
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("paused", "user_paused"), st)

    def test_a_pause_cuts_the_connections_after_the_grace_time_when_the_worker_ignores_the_stop(self):
        self.start_download()
        self.cdn.stop_event = None                                              # the held read does not see the stop (a dead connection)
        calls = []

        def cut():
            calls.append(time.monotonic())
            self.cdn.gate.set()                                                 # cutting the socket frees the stuck read
            return 1

        with mock.patch("brain_hub.ownbrain.GRACE_SECONDS", 0.5), mock.patch("net_tools.transport.abort_all", side_effect=cut):
            began = time.monotonic()
            self.assertTrue(self.ob.cancel())
            ended = time.monotonic()
        self.assertEqual(len(calls), 1, "the connections are cut once")
        self.assertGreaterEqual(calls[0] - began, 0.45, "not before the grace time has passed")
        self.assertLess(ended - began, 10.0)
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("paused", "user_paused"), st)
        self.assertGreater(self.ob.partial_bytes(self.ob.choice("light")), 0, "what was fetched stays")

    def test_a_stop_with_nothing_downloading_cuts_nothing(self):
        with mock.patch("net_tools.transport.abort_all", return_value=0) as cut:
            self.assertFalse(self.ob.halt())
            self.assertFalse(self.ob.cancel())
        self.assertEqual(cut.call_count, 0)


if __name__ == "__main__":
    unittest.main()
