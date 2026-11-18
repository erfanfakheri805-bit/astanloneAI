"""
Prompt 959 (stage B, «مغز خودکار») - the own brain's DOWNLOAD while it really runs in its worker thread.

The chat is driven only through the real front door (HTTP `POST /api/message`); the CDN is scripted and HOLDS the download after 600,000 of
900,000 bytes until the test lets it go, so every message below is sent while a download is truly in progress: the real status and percent,
a pause that keeps the partial file, a continue that asks the server only for the rest (`Range`), the emergency words («ایست» / «ادامه»), and
a removal in the middle. Nothing here says how a real model file, the real engine or a real phone behave: it proves the app's logic.
"""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from persian_brain import hub_messages_ownbrain as BM
from tests.ownbrain_support_prompt959 import ThreadedOwnBrainApp, big_light_data

FREE = "یه سوال عجیب و غریب درباره فلان"
HELD_AT = 500_000                       # at least this much is on the disk when the CDN holds the download (600,000 are delivered; one chunk may still wait)


def wait_until(test, predicate, seconds=15, what="the condition"):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.02)
    test.fail("timed out waiting for %s" % what)


class LiveDownloadTests(ThreadedOwnBrainApp):
    def light(self):
        return self.ob.choice("light")

    def partial(self):
        return self.ob.partial_bytes(self.light())

    def test_the_status_is_the_real_progress_and_the_chat_stays_usable(self):
        reply = self.start_download()
        self.assertIn("شروع کردم", reply)
        began = time.monotonic()
        status = self.ask("وضعیت مغز")
        self.assertLess(time.monotonic() - began, 3.0, "a status question must not wait for the download")
        st = self.ob.status()
        self.assertEqual(st["phase"], "downloading")
        self.assertEqual(st["total"], len(big_light_data()))
        self.assertTrue(HELD_AT * 0.5 <= st["bytes"] < st["total"], st)        # the downloader reports every 256 KiB, so this is a little behind the disk
        self.assertEqual(st["percent"], int(st["bytes"] * 100 / st["total"]))
        self.assertIn("دارم «%s» را می‌گیرم" % self.light().short_fa, status)
        self.assertIn(BM.percent(st["percent"]), status)
        self.assertIn(BM.size(st["bytes"]), status)
        self.assertIn(BM.size(st["total"]), status)

    def test_other_questions_are_answered_while_the_download_is_held(self):
        self.start_download()
        began = time.monotonic()
        replies = [self.ask("ساعت چنده؟"), self.ask("چه کارهایی بلدی؟"), self.ask(FREE)]
        self.assertLess(time.monotonic() - began, 8.0)
        self.assertTrue(all(replies), replies)
        self.assertIn("الان در حال گرفته‌شدن است", replies[1] + replies[2], "the capability list or the free sentence must say the brain is coming")
        self.assertEqual(self.ob.status()["phase"], "downloading", "talking must not disturb the download")

    def test_a_free_sentence_says_the_brain_is_being_fetched_and_what_to_say(self):
        self.start_download()
        reply = self.ask(FREE)
        pct = self.ob.status()["percent"]
        self.assertIn(BM.lead_line("downloading", pct), reply)
        self.assertIn(BM.STATUS, reply)
        self.assertNotIn("آماده است ✅", reply)

    def test_a_pause_keeps_the_partial_file_and_says_so(self):
        self.start_download()
        reply = self.ask(BM.PAUSE)
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("paused", "user_paused"), st)
        held = self.partial()
        self.assertTrue(HELD_AT <= held < len(big_light_data()), held)
        self.assertEqual(st["bytes"], held, "a paused download reports what is really on the disk")
        self.assertIn("متوقف کردم", reply)
        self.assertIn(BM.percent(st["percent"]), reply)
        self.assertIn(BM.RESUME, reply)
        self.assertIn("چیزی پاک نشد", reply)
        self.assertIn(BM.RESUME, self.ask("وضعیت مغز"))

    def test_a_continue_asks_the_server_only_for_the_rest_and_ends_in_a_ready_brain(self):
        self.start_download()
        self.ask(BM.PAUSE)
        held = self.partial()
        before = len(self.cdn.cdn_requests)
        reply = self.ask(BM.RESUME)
        self.assertIn("ادامه دادم", reply)
        self.assertNotIn("شروع کردم", reply)
        wait_until(self, lambda: len(self.cdn.cdn_requests) > before, what="the second request to the CDN")
        self.assertEqual(self.cdn.cdn_requests[before].headers.get("Range"), "bytes=%d-" % held)
        self.open_gate_and_wait()
        st = self.ob.status()
        self.assertEqual(st["phase"], "ready", st)
        self.assertTrue(self.model_status("light").usable)
        self.assertIn("سلام! من مغزِ آزمایشی هستم.", self.ask(FREE))
        self.assertEqual(len(self.bridge.chats), 2, "one real test question at install, one for the user's sentence")

    def test_a_pause_when_nothing_is_downloading_changes_nothing(self):
        self.start_download()
        self.ask(BM.PAUSE)
        state_before = self.ob.status()
        reply = self.ask(BM.PAUSE)
        self.assertIn("الان دانلودی در کار نیست", reply)
        self.assertEqual(self.ob.status(), state_before)

    def test_a_continue_while_it_runs_does_not_start_a_second_download(self):
        self.start_download()
        before = len(self.cdn.requests)
        reply = self.ask(BM.RESUME)
        self.assertIn("همین الان دارم روی مغزِ خودم کار می‌کنم", reply)
        self.assertIn("می‌گیرم", reply, "and the status line says what it is doing")
        self.assertNotIn("دانلودی نیست", reply, "while a download runs «there is no download» is false")
        self.assertEqual(len(self.cdn.requests), before, "no second request may go out")
        self.assertEqual(self.ob.status()["phase"], "downloading")

    def test_the_stop_word_in_a_free_sentence_is_not_a_pause(self):
        self.start_download()
        self.ask("بس کن این حرف‌ها را؛ یه سوال عجیب و غریب درباره فلان دارم")
        self.assertEqual(self.ob.status()["phase"], "downloading")


class EmergencyWordTests(ThreadedOwnBrainApp):
    def light(self):
        return self.ob.choice("light")

    def test_the_emergency_word_stops_the_download_and_keeps_what_was_fetched(self):
        self.start_download()
        with mock.patch("net_tools.transport.abort_all", return_value=0) as cut:
            reply = self.ask("ایست")
        self.assertTrue(cut.called, "an emergency stop cuts the open connections at once")
        self.assertIn(BM.halted_note(), reply)
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("paused", "halted"), st)
        self.assertTrue(HELD_AT <= self.ob.partial_bytes(self.light()) < len(big_light_data()))
        self.assertIn("با «ایست» متوقف شد", self.ask("وضعیت مغز"))

    def test_the_word_that_ends_the_stop_continues_that_download(self):
        self.start_download()
        self.ask("ایست")
        held = self.ob.partial_bytes(self.light())
        before = len(self.cdn.cdn_requests)
        reply = self.ask("ادامه")
        self.assertIn(BM.resumed_note(), reply)
        wait_until(self, lambda: len(self.cdn.cdn_requests) > before, what="the second request to the CDN")
        self.assertEqual(self.cdn.cdn_requests[before].headers.get("Range"), "bytes=%d-" % held)
        self.open_gate_and_wait()
        self.assertEqual(self.ob.status()["phase"], "ready")

    def test_the_word_that_ends_the_stop_does_not_undo_the_users_own_pause(self):
        self.start_download()
        self.ask(BM.PAUSE)
        halted = self.ask("ایست")
        self.assertNotIn(BM.halted_note(), halted, "nothing was downloading, so no stop of a download may be claimed")
        before = len(self.cdn.requests)
        reply = self.ask("ادامه")
        self.assertNotIn(BM.resumed_note(), reply)
        self.assertEqual(len(self.cdn.requests), before, "a download the user paused himself stays paused")
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("paused", "user_paused"), st)

    def test_the_emergency_word_with_nothing_downloading_changes_nothing(self):
        reply = self.ask("ایست")
        self.assertNotIn(BM.halted_note(), reply)
        self.assertEqual(self.ob.status()["phase"], "idle")
        self.assertFalse(os.path.exists(os.path.join(self.own_dir, "state.json")), "a stop must not create a record")
        self.assertEqual(self.cdn.requests, [])

    def test_an_explicit_continue_works_after_the_emergency_stop(self):
        self.start_download()
        self.ask("ایست")
        reply = self.ask(BM.RESUME)
        self.assertIn("ادامه دادم", reply)
        self.open_gate_and_wait()
        self.assertEqual(self.ob.status()["phase"], "ready")

    def test_a_second_emergency_word_is_harmless(self):
        self.start_download()
        self.ask("ایست")
        state = self.ob.status()
        again = self.ask("ایست")
        self.assertNotIn(BM.halted_note(), again)
        self.assertEqual(self.ob.status(), state)


class DeleteInTheMiddleTests(ThreadedOwnBrainApp):
    def light(self):
        return self.ob.choice("light")

    def test_a_delete_in_the_middle_frees_the_partial_file_and_forgets_the_brain(self):
        self.start_download()
        self.assertGreaterEqual(self.ob.partial_bytes(self.light()), HELD_AT)
        question = self.ask(BM.DELETE)
        self.assertEqual(self.pending_own(), "delete")
        self.assertIn("بله / نه", question)
        reply = self.ask("بله")
        self.assertIn("پاک شد", reply)
        self.assertIn("۶۰۰ کیلوبایت جا آزاد شد", reply, "what was freed is said in numbers (about 600 kB were on the disk)")
        st = self.ob.status()
        self.assertEqual(st["phase"], "idle", st)
        self.assertEqual(self.ob.partial_bytes(self.light()), 0)
        self.assertFalse(self.model_status("light").usable)
        self.assertFalse(self.ob._running(), "the worker must be gone")
        self.assertIn("هنوز مغزی برای خودم نگرفته‌ام", self.ask("وضعیت مغز"))

    def test_saying_no_to_the_delete_question_keeps_downloading(self):
        self.start_download()
        self.ask(BM.DELETE)
        reply = self.ask("نه")
        self.assertIn("چیزی پاک نشد", reply)
        self.assertEqual(self.ob.status()["phase"], "downloading")
        self.open_gate_and_wait()
        self.assertEqual(self.ob.status()["phase"], "ready")

    def test_a_free_sentence_withdraws_the_delete_question(self):
        self.start_download()
        self.ask(BM.DELETE)
        self.ask(FREE)
        self.assertIsNone(self.pending_own())
        self.assertEqual(self.ob.status()["phase"], "downloading")

    def test_after_a_delete_the_same_brain_can_be_fetched_again_from_zero(self):
        self.start_download()
        self.ask(BM.DELETE)
        self.ask("بله")
        self.cdn.gate.clear()
        self.cdn.reached.clear()
        before = len(self.cdn.cdn_requests)
        self.start_download()
        wait_until(self, lambda: len(self.cdn.cdn_requests) > before, what="the new request to the CDN")
        self.assertIsNone(self.cdn.cdn_requests[before].headers.get("Range"), "a fresh start asks for the whole file")
        self.open_gate_and_wait()
        self.assertEqual(self.ob.status()["phase"], "ready")


if __name__ == "__main__":
    unittest.main()
