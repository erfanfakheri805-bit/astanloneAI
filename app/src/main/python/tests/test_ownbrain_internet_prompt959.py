"""
Prompt 959 (stage B, «مغز خودکار») - the app-wide INTERNET SWITCH and the own brain's download.

«اینترنت را خاموش کن» is the user's master switch: when it is off the app sends nothing. The own brain's download is the biggest thing the app ever
fetches (1-2.6 GB), so it must obey that switch like everything else:

* the gate handed to the downloader says «yes» only while the job runs AND the switch is on;
* the user's «بله» to the consent card (which says so) switches it on - and only a successful start does; a refusal changes no permission;
* «ادامه» / «تلاش دوباره» / the automatic try after a restart never switch it on again by themselves: the user switched it off, so he switches it on;
* switching it off stops a running download at once (the chat command cuts the sockets; a revoke from anywhere else is seen between two chunks)
  and what was fetched stays.

Nothing here says how a real phone, a real network or the real model behave: it proves the app's logic with a scripted download.
"""
import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub.ownbrain import StartResult
from persian_brain import hub_messages as HM
from persian_brain import hub_messages_ownbrain as BM
from tests.ownbrain_support_prompt959 import OwnBrainApp, ThreadedOwnBrainApp, big_light_data, tiny_choice, write_meminfo
from tests.test_ownbrain_threaded_prompt959 import HELD_AT, wait_until

NET_OFF = "اینترنت را خاموش کن"
NET_ON = "اینترنت را روشن کن"
SWITCH_SENTENCE = "«اینترنتِ برنامه» را هم روشن کردم"


class GateTests(OwnBrainApp):
    def test_the_gate_opens_only_while_the_job_runs_and_the_switch_is_on(self):
        gate = self.ob._gate
        self.assertFalse(self.internet_on(), "a fresh app has the internet switched off")
        for job_running in (False, True):
            self.ob._net_open = job_running
            self.assertFalse(gate.allowed("network"), "the switch is off: never (job running: %s)" % job_running)
        self.switch_internet(True)
        self.ob._net_open = False
        self.assertFalse(gate.allowed("network"), "the switch is on but no job runs")
        self.ob._net_open = True
        self.assertTrue(gate.allowed("network"))
        self.assertFalse(gate.allowed("microphone"), "only the network, only for this job")
        self.switch_internet(False)
        self.assertFalse(gate.allowed("network"), "turning the switch off closes the gate at once")

    def test_a_switch_that_cannot_be_read_counts_as_off(self):
        with mock.patch.object(self.hub.permissions, "is_granted", side_effect=OSError("store")):
            self.assertFalse(self.ob.network_on())
            self.assertFalse(self.ob._gate.allowed("network"))


class StartTests(OwnBrainApp):
    def test_the_yes_switches_the_internet_on_and_the_brain_comes(self):
        self.assertFalse(self.internet_on())
        self.assertEqual(self.ob.start("light", consent=True), StartResult(True, "started"))
        self.assertTrue(self.internet_on())
        self.assertEqual(self.ob.status()["phase"], "ready")

    def test_a_start_with_the_switch_already_on_changes_nothing_about_it(self):
        self.switch_internet(True)
        before = self.permission_snapshot()
        self.assertEqual(self.ob.start("light", consent=True), StartResult(True, "started"))
        self.assertEqual(self.permission_snapshot(), before)

    def test_a_refused_start_leaves_the_switch_off(self):
        write_meminfo(self.meminfo, 1_000_000)
        self.assertEqual(self.ob.start("light", consent=True).code, "ram_too_small")
        write_meminfo(self.meminfo, self.ram_kb)
        self.assertEqual(self.ob.start("light", consent=False).code, "consent_required")
        self.assertEqual(self.ob.start("nope", consent=True).code, "unknown_choice")
        self.assertFalse(self.internet_on(), "no refused start may change a permission")
        self.nothing_was_fetched()

    def test_a_switch_that_cannot_be_turned_on_stops_the_start(self):
        refused = SimpleNamespace(ok=False, code="io_error")
        with mock.patch.object(self.hub, "grant_permission", return_value=refused):
            self.assertEqual(self.ob.start("light", consent=True), StartResult(False, "network_failed"))
        self.assertFalse(self.internet_on())
        self.nothing_was_fetched()

    def test_a_grant_that_raises_is_a_refusal_not_a_crash(self):
        with mock.patch.object(self.hub, "grant_permission", side_effect=OSError("disk full")):
            self.assertEqual(self.ob.start("light", consent=True), StartResult(False, "network_failed"))
        self.nothing_was_fetched()

    def test_a_grant_that_says_ok_but_changes_nothing_is_not_believed(self):
        with mock.patch.object(self.hub, "grant_permission", return_value=SimpleNamespace(ok=True, code="")):
            self.assertEqual(self.ob.start("light", consent=True), StartResult(False, "network_failed"))
        self.nothing_was_fetched()


class ContinueTests(OwnBrainApp):
    """A stopped download that the user continues: the switch is HIS - nothing here turns it on again."""

    def stopped(self, code="net_off", phase="paused"):
        self.seed_download(phase=phase, code=code)
        self.start_app()
        self.assertFalse(self.internet_on())

    def test_resume_with_the_switch_off_is_refused_and_does_not_turn_it_on(self):
        self.stopped()
        self.assertEqual(self.ob.resume(), StartResult(False, "network_off"))
        self.assertFalse(self.internet_on(), "only the user switches the internet on again")
        self.assertEqual(self.cdn.requests, [], "nothing was requested")
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("paused", "net_off"), "and the state still says why it waits")
        self.switch_internet(True)
        self.assertEqual(self.ob.resume(), StartResult(True, "started"))
        self.assertEqual(self.ob.status()["phase"], "ready")

    def test_retry_of_a_failed_download_needs_the_switch_too(self):
        self.stopped(code="interrupted", phase="failed")
        self.assertEqual(self.ob.retry(), StartResult(False, "network_off"))
        self.assertFalse(self.internet_on())
        self.assertEqual(self.cdn.requests, [])
        self.switch_internet(True)
        self.assertEqual(self.ob.retry(), StartResult(True, "started"))
        self.assertEqual(self.ob.status()["phase"], "ready")

    def failed_load(self):
        """The brain was fetched and installed, but the engine could not load it: the model is `failed` and its file stays on the phone."""
        self.bridge.load_result = "ERR\nengine_load_failed\nout of memory"
        self.assertEqual(self.ob.start("light", consent=True), StartResult(True, "started"))
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("failed", "engine_load_failed"))
        self.assertEqual(self.model_status("light").state, "failed")
        self.assertTrue(os.path.isfile(self.hub.model_file_path(tiny_choice("light").model_id)))

    def test_a_failed_model_whose_file_is_gone_needs_the_internet_again(self):
        self.failed_load()
        os.remove(self.hub.model_file_path(tiny_choice("light").model_id))
        self.switch_internet(False)
        self.assertEqual(self.ob.retry(), StartResult(False, "network_off"), "the file has to be fetched again, and the switch is off")
        self.assertFalse(self.internet_on())
        self.assertEqual(self.ob.status()["code"], "engine_load_failed", "a refusal changes nothing")

    def test_a_retest_of_a_brain_that_is_already_on_the_phone_needs_no_internet(self):
        """Nothing is downloaded by a retest, so the switch is none of its business (it is not turned on, and it does not block). This includes a
        model that FAILED after its file was stored: the file is still there and the pipeline reopens it."""
        self.failed_load()
        self.switch_internet(False)
        self.bridge.load_result = "OK\nloaded"
        requests = len(self.cdn.requests)
        self.assertEqual(self.ob.retry(), StartResult(True, "started"))
        self.assertEqual(self.ob.status()["phase"], "ready")
        self.assertEqual(len(self.cdn.requests), requests, "no new download")
        self.assertFalse(self.internet_on(), "and the switch was not touched")

    def test_the_tick_after_a_restart_does_not_resume_with_the_switch_off(self):
        self.stopped(code="app_closed")
        self.assertEqual(self.ob.tick(), StartResult(False, "network_off"))
        self.assertEqual(self.cdn.requests, [])
        self.assertFalse(self.internet_on())
        self.assertIsNone(self.ob.tick(), "one automatic try per service life")
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("paused", "app_closed"))

    def test_a_download_stopped_by_the_switch_is_never_continued_by_a_restart(self):
        self.seed_download(code="net_off")
        self.start_app()
        self.switch_internet(True)                                  # he switched it on again for something else
        self.assertIsNone(self.ob.tick(), "only «the app was closed» is continued by itself")
        self.assertEqual(self.cdn.requests, [])
        self.assertEqual(self.ob.status()["code"], "net_off")


class NothingRunningTests(OwnBrainApp):
    def test_switching_off_with_nothing_downloading_changes_nothing(self):
        before = self.ob.status()
        self.assertFalse(self.ob.net_off())
        self.assertEqual(self.ob.status(), before)

    def test_switching_off_while_ready_leaves_the_brain_ready_and_working(self):
        self.install_light()
        self.assertTrue(self.internet_on())
        reply = self.ask(NET_OFF)
        self.assertEqual(reply, HM.net_off_done(), "a ready brain is local: the reply says nothing about it")
        self.assertEqual(self.ob.status()["phase"], "ready")
        self.assertIn("سلام! من مغزِ آزمایشی هستم.", self.ask("یه سوال عجیب و غریب درباره فلان"), "and it still answers, offline")

    def test_switching_off_after_the_user_paused_adds_nothing(self):
        self.seed_download(code="user_paused")
        self.start_app()
        self.switch_internet(True)
        self.assertEqual(self.ask(NET_OFF), HM.net_off_done())
        self.assertEqual(self.ob.status()["code"], "user_paused", "his own pause stays his pause")


class ChatTests(OwnBrainApp):
    def test_the_consent_card_says_what_the_yes_also_does_and_changes_nothing_yet(self):
        before = self.permission_snapshot()
        card = self.ask("مغز خودت را بگیر")
        self.assertIn("با «بله»، «اینترنتِ برنامه» هم روشن می‌شود", card)
        self.assertIn(NET_OFF, card)
        self.assertEqual(self.permission_snapshot(), before, "a card changes nothing")
        self.assertFalse(self.internet_on())
        self.ask("نه")
        self.assertEqual(self.permission_snapshot(), before, "and a «no» changes nothing either")
        self.nothing_was_fetched()

    def test_a_yes_with_the_switch_off_turns_it_on_and_says_so(self):
        self.ask("مغز خودت را بگیر")
        self.ask("سبک")
        reply = self.ask("بله")
        self.assertIn(SWITCH_SENTENCE, reply)
        self.assertTrue(self.internet_on())
        self.assertEqual(self.ob.status()["phase"], "ready")

    def test_a_yes_with_the_switch_already_on_does_not_claim_to_have_turned_it_on(self):
        self.switch_internet(True)
        self.ask("مغز خودت را بگیر")
        self.ask("سبک")
        reply = self.ask("بله")
        self.assertNotIn(SWITCH_SENTENCE, reply)
        self.assertEqual(self.ob.status()["phase"], "ready")

    def test_a_refused_yes_does_not_claim_the_switch_and_leaves_it_off(self):
        self.ask("مغز خودت را بگیر")
        self.ask("سبک")
        write_meminfo(self.meminfo, 1_000_000)                       # the phone lost its memory between the card and the yes
        reply = self.ask("بله")
        self.assertNotIn(SWITCH_SENTENCE, reply)
        self.assertFalse(self.internet_on())
        self.nothing_was_fetched()

    def test_a_continue_with_the_switch_off_says_so_and_names_the_way_forward(self):
        self.seed_download(code="net_off")
        self.start_app()
        status = self.ask("وضعیت مغز")
        self.assertIn("با خاموش‌شدنِ اینترنتِ برنامه متوقف شد", status)
        self.assertIn("اول «%s» و بعد «%s»" % (NET_ON, BM.RESUME), status)
        reply = self.ask(BM.RESUME)
        self.assertEqual(reply, BM.blocked("network_off"))
        self.assertIn("اینترنتِ برنامه خاموش است", reply)
        self.assertIn(NET_ON, reply)
        self.assertFalse(self.internet_on(), "asking to continue is not switching the internet on")
        self.assertEqual(self.cdn.requests, [])
        # the way forward the text names really works
        self.ask(NET_ON)
        self.ask("بله")
        self.assertTrue(self.internet_on())
        self.assertIn("ادامه دادم", self.ask(BM.RESUME))
        self.assertEqual(self.ob.status()["phase"], "ready")
        ranges = [r.headers.get("Range") for r in self.cdn.requests if r.headers.get("Range")]
        self.assertIn("bytes=30000-", ranges, "from where it stopped")

    def test_the_other_words_for_the_same_thing_are_refused_the_same_way(self):
        self.seed_download(phase="failed", code="interrupted")
        self.start_app()
        for text in (BM.RESUME, BM.RETRY, "مغز خودت را بگیر"):
            reply = self.ask(text)
            self.assertIn(NET_ON, reply, text)
            self.assertFalse(self.internet_on(), text)
        self.assertEqual(self.cdn.requests, [])

    def test_a_ready_brain_asked_to_continue_is_just_ready(self):
        self.install_light()
        self.switch_internet(False)
        reply = self.ask(BM.RESUME)
        self.assertNotIn("اینترنتِ برنامه خاموش است", reply, "nothing needs the internet: the brain is on the phone")


class LiveSwitchTests(ThreadedOwnBrainApp):
    """A REAL worker thread, a download held in the middle (600,000 of 900,000 bytes), and the switch turned off meanwhile."""

    def light(self):
        return self.ob.choice("light")

    def partial(self):
        return self.ob.partial_bytes(self.light())

    def test_switching_the_internet_off_in_chat_stops_the_running_download_at_once(self):
        self.start_download()
        self.assertTrue(self.internet_on(), "the yes had switched it on")
        with mock.patch("net_tools.transport.abort_all", return_value=1) as cut:
            began = time.monotonic()
            reply = self.ask(NET_OFF)
            self.assertLess(time.monotonic() - began, 5.0)
        self.assertGreaterEqual(cut.call_count, 1, "the open connections are cut, not left to time out")
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("paused", "net_off"), st)
        self.assertFalse(self.internet_on())
        self.assertIn(HM.net_off_done(), reply)
        self.assertIn(BM.net_off_note(st), reply)
        self.assertTrue(HELD_AT <= self.partial() < len(big_light_data()), "what was fetched stays: %d bytes" % self.partial())

    def test_after_the_stop_the_status_the_refusal_and_the_way_forward_are_true(self):
        self.start_download()
        self.ask(NET_OFF)
        held = self.partial()
        status = self.ask("وضعیت مغز")
        self.assertIn("با خاموش‌شدنِ اینترنتِ برنامه متوقف شد", status)
        self.assertIn(BM.percent(self.ob.status()["percent"]), status)
        before = len(self.cdn.cdn_requests)
        self.assertEqual(self.ask(BM.RESUME), BM.blocked("network_off"))
        self.assertEqual(len(self.cdn.cdn_requests), before, "no request while the switch is off")
        self.ask(NET_ON)
        self.ask("بله")
        self.assertIn("ادامه دادم", self.ask(BM.RESUME))
        wait_until(self, lambda: len(self.cdn.cdn_requests) > before, what="the continuing request")
        self.assertEqual(self.cdn.cdn_requests[before].headers.get("Range"), "bytes=%d-" % held, "only the rest is asked for")
        self.open_gate_and_wait()
        self.assertEqual(self.ob.status()["phase"], "ready")
        self.assertTrue(self.model_status("light").usable)

    def test_a_revoke_that_does_not_come_through_the_chat_is_seen_between_two_chunks(self):
        """Any other way the switch can be turned off (a button, another module): no command reaches the service, so the downloader itself looks at
        the switch before every chunk."""
        self.start_download()
        self.switch_internet(False)
        self.assertEqual(self.ob.status()["phase"], "downloading", "nothing has noticed yet: the CDN is holding the connection")
        self.cdn.gate.set()
        wait_until(self, lambda: self.ob.status()["phase"] == "paused", what="the worker to notice the switch")
        self.assertTrue(self.ob.wait(10), "the worker ended")
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("paused", "net_off"), st)
        self.assertLess(self.partial(), len(big_light_data()), "it stopped before the end of the file")
        self.assertGreater(self.partial(), 0, "and what was fetched stays")
        self.assertFalse(self.model_status("light").usable)

    def test_the_users_own_pause_wins_the_name_when_both_happen(self):
        self.start_download()
        self.assertTrue(self.ob.cancel())
        self.switch_internet(False)
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("paused", "user_paused"), st)

    def test_the_install_after_the_download_does_not_need_the_switch(self):
        """The install step loads a file that is already on the phone: turning the switch off then must not break it."""
        self.start_download()
        self.cdn.gate.set()
        wait_until(self, lambda: self.ob.status()["phase"] in ("installing", "ready"), what="the end of the download")
        self.switch_internet(False)
        self.assertTrue(self.ob.wait(30), "the worker did not finish")
        self.assertEqual(self.ob.status()["phase"], "ready", self.ob.status())
        self.assertTrue(self.model_status("light").usable)


if __name__ == "__main__":
    unittest.main()
