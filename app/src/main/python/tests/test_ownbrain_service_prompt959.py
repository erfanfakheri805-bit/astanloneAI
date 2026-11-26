"""
Prompt 959 (stage B, «مغز خودکار») - `brain_hub.ownbrain.OwnBrain` as a service, called directly (the chat tests go through the conversation).

What is pinned here: the exact answer of every refusal (a code and the numbers behind it), consent that must be exactly `True`, the numbers of
the status (speed and time left come from the real samples, never invented), the notifier's sequence, what a restart and a second service
object see, the memory the idle timer gives back, a downloader that blows up, and the free space an already installed brain no longer needs.
The download is scripted and the engine is a fake: nothing here says how the real file or the real engine behave.
"""
import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from android_adapters.bridge import BridgeConnectivity
from brain_hub import ownbrain_state as ST
from brain_hub.ownbrain import OwnBrain, StartResult, get_ownbrain
from tests.ownbrain_support_prompt959 import (DATA, LIGHT_DATA, OwnBrainApp, Usage, tiny_choice, write_meminfo)
from tests.test_ownbrain_threaded_prompt959 import wait_until

TOTAL = len(LIGHT_DATA)


class StartRefusalTests(OwnBrainApp):
    def test_the_users_yes_must_be_exactly_true(self):
        for consent in (False, None, 1, "yes", "بله", 0, [True]):
            with self.subTest(consent=consent):
                self.assertEqual(self.ob.start("light", consent=consent), StartResult(False, "consent_required"))
        self.assertEqual(self.ob.start("light"), StartResult(False, "consent_required"), "no consent argument at all")
        self.nothing_was_fetched()

    def test_an_unknown_brain_is_refused_before_anything_is_read(self):
        for key in ("", "medium", None, 7, "../strong", "LIGHT"):
            self.assertEqual(self.ob.start(key, consent=True), StartResult(False, "unknown_choice"), key)
        self.nothing_was_fetched()

    def test_too_little_memory_names_both_numbers(self):
        write_meminfo(self.meminfo, kb=1_000_000)
        result = self.ob.start("light", consent=True)
        self.assertEqual((result.ok, result.code), (False, "ram_too_small"))
        have, need = result.detail.split("/")
        self.assertEqual((int(have), int(need)), (1_000_000 * 1024, tiny_choice("light").min_ram))
        self.nothing_was_fetched()

    def test_memory_that_cannot_be_read_is_refused_not_guessed(self):
        os.unlink(self.meminfo)
        self.assertEqual(self.ob.start("light", consent=True).code, "ram_unknown")
        self.nothing_was_fetched()

    def test_too_little_free_space_names_both_numbers(self):
        self.hub._free_space_fn = lambda _path: Usage(10 ** 12, 10 ** 12 - 1000, 1000)
        self.start_app_with_space(1000)
        result = self.ob.start("light", consent=True)
        self.assertEqual((result.ok, result.code), (False, "not_enough_space"))
        have, need = result.detail.split("/")
        self.assertEqual(int(have), 1000)
        self.assertGreater(int(need), len(LIGHT_DATA))
        self.nothing_was_fetched()

    def start_app_with_space(self, free):
        self.free_fn = staticmethod(lambda _path: Usage(10 ** 12, 10 ** 12 - free, free))
        self.start_app()

    def test_no_internet_is_refused_before_anything_is_fetched(self):
        self.connectivity = BridgeConnectivity("offline", "none")
        self.start_app()
        self.assertEqual(self.ob.start("light", consent=True), StartResult(False, "offline", ""))
        self.nothing_was_fetched()

    def test_a_build_without_the_engine_is_refused_and_says_which_code(self):
        self.engine_available = False
        self.start_app()
        result = self.ob.start("light", consent=True)
        self.assertEqual((result.ok, result.code), (False, "engine_missing"))
        self.assertTrue(result.detail, "the technical reason travels with the refusal")
        self.nothing_was_fetched()

    def test_an_engine_in_the_apk_that_is_shaped_differently_is_refused_before_anything_is_fetched(self):
        self.bridge.probe_result = "ERR\napi_mismatch\nEngineConfig(String, Backend)"
        self.start_app()
        self.assertEqual(self.ob.start("light", consent=True), StartResult(False, "engine_missing", "api_mismatch"))
        self.assertEqual(self.bridge.loads, [])
        self.nothing_was_fetched()
        facts = self.ob.facts()
        self.assertEqual((facts["engine_ok"], facts["engine_code"]), (False, "api_mismatch"))
        self.assertIn("EngineConfig(String, Backend)", facts["engine_reason_fa"])
        self.assertEqual(facts["engine_api"], "Engine: <init>(EngineConfig); initialize();")          # the engine's real API travels with the refusal
        self.bridge.api_text = "x" * 5000
        self.assertEqual(len(self.ob.facts()["engine_api"]), 1500)

    def test_the_engine_api_listing_is_attached_only_when_the_engine_does_not_match(self):
        self.assertNotIn("engine_api", self.ob.facts())
        self.engine_available = False
        self.start_app()
        self.assertNotIn("engine_api", self.ob.facts())
        rows = [r for r in self.hub.model_runtimes_info() if "litertlm" in r["formats"]]
        self.assertTrue(rows and "api" not in rows[0])

    def test_a_second_start_and_the_other_brain_are_refused_once_one_is_ready(self):
        self.assertEqual(self.ob.start("light", consent=True), StartResult(True, "started"))
        self.assertEqual(self.ob.status()["phase"], "ready")
        self.assertEqual(self.ob.start("light", consent=True), StartResult(False, "already_ready", "light"))
        self.assertEqual(self.ob.start("strong", consent=True), StartResult(False, "have_other", "light"))
        self.assertEqual(len(self.bridge.loads), 1)

    def test_commands_that_need_a_running_or_stopped_job_say_there_is_none(self):
        self.assertEqual(self.ob.resume(), StartResult(False, "nothing_to_resume"))
        self.assertEqual(self.ob.retry(), StartResult(False, "nothing_to_resume"))
        self.assertIsNone(self.ob.resume_after_halt())
        self.assertFalse(self.ob.cancel())
        self.assertFalse(self.ob.halt())
        self.assertEqual(self.ob.status()["phase"], "idle")
        self.nothing_was_fetched()


class ServiceStateTests(OwnBrainApp):
    def test_a_ready_brain_is_remembered_by_a_second_service_object(self):
        self.install_light()
        again = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0)
        st = again.status()
        self.assertEqual((st["phase"], st["choice"], st["percent"]), ("ready", "light", 100))
        self.assertTrue(again.is_ready())
        self.assertEqual(again.model_id(), tiny_choice("light").model_id)
        self.assertEqual(again.state_note, "")

    def test_a_brain_the_model_commands_removed_is_no_longer_ready(self):
        self.install_light()
        self.assertTrue(self.hub.remove_model(tiny_choice("light").model_id).ok)
        st = self.ob.status(deep=True)
        self.assertEqual(st["phase"], "idle", st)
        self.assertFalse(self.ob.is_ready())
        self.assertEqual(self.ob.model_id(), "")
        self.assertEqual(self.ob.status()["phase"], "idle", "and it stays so")

    def test_the_footprint_is_what_the_brain_really_holds_and_a_delete_frees_it(self):
        self.assertEqual(self.ob.footprint(), 0)
        self.install_light()
        held = self.ob.footprint()
        self.assertEqual(held, len(LIGHT_DATA))
        result = self.ob.delete()
        self.assertEqual(result, {"freed": held, "had": True, "busy": False})
        self.assertEqual(self.ob.footprint(), 0)
        self.assertEqual(self.ob.status()["phase"], "idle")
        self.assertFalse(os.path.exists(os.path.join(self.own_dir, "state.json")))
        self.assertEqual(self.ob.delete(), {"freed": 0, "had": False, "busy": False}, "a second delete finds nothing")

    def test_the_one_service_per_hub_and_nothing_for_things_that_are_not_a_hub(self):
        self.assertIs(get_ownbrain(self.hub), self.ob)
        for junk in (None, object(), "hub", 7):
            self.assertIsNone(get_ownbrain(junk))

    def test_an_installed_brain_is_not_held_up_by_free_space_it_no_longer_needs(self):
        self.install_light()
        state = ST.default_state()
        state.update(choice="light", phase="installing", consent_at=1.0, model_id=tiny_choice("light").model_id, total=TOTAL, bytes=TOTAL)
        self.assertTrue(ST.StateFile(self.own_dir, clock=self.clock).save(state))     # the app died during the install: the file is already in the store
        self.hub._free_space_fn = lambda _path: Usage(10 ** 12, 10 ** 12 - 1000, 1000)
        again = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0)
        self.assertEqual((again.status()["phase"], again.status()["code"]), ("paused", "app_closed"))
        before = len(self.cdn.requests)
        self.assertEqual(again.resume(), StartResult(True, "started"), "nothing is downloaded, so no space is needed for it")
        self.assertEqual(again.status()["phase"], "ready")
        self.assertEqual(len(self.cdn.requests), before, "the file was not fetched again")

    def test_a_brain_whose_load_failed_is_not_held_up_by_free_space_either(self):
        """The model is `failed` but its file is in the store: a retry reopens it and downloads nothing, so no space is needed for it."""
        self.bridge.load_result = "ERR\nengine_load_failed\nout of memory"
        self.assertEqual(self.ob.start("light", consent=True), StartResult(True, "started"))
        self.assertEqual((self.ob.status()["phase"], self.ob.status()["code"]), ("failed", "engine_load_failed"))
        self.assertEqual(self.model_status("light").state, "failed")
        self.hub._free_space_fn = lambda _path: Usage(10 ** 12, 10 ** 12 - 1000, 1000)
        again = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0)
        self.bridge.load_result = "OK\nloaded"
        before = len(self.cdn.requests)
        self.assertEqual(again.resume(), StartResult(True, "started"), "nothing is downloaded, so no space is needed for it")
        self.assertEqual(again.status()["phase"], "ready")
        self.assertEqual(len(self.cdn.requests), before, "the file was not fetched again")

    def test_a_failed_model_whose_file_is_gone_does_need_the_space(self):
        self.bridge.load_result = "ERR\nengine_load_failed\nout of memory"
        self.assertEqual(self.ob.start("light", consent=True), StartResult(True, "started"))
        os.remove(self.hub.model_file_path(tiny_choice("light").model_id))
        self.hub._free_space_fn = lambda _path: Usage(10 ** 12, 10 ** 12 - 1000, 1000)
        again = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0)
        self.assertEqual(again.resume().code, "not_enough_space", "the file has to be fetched again: the space counts")

    def test_the_memory_still_counts_for_an_installed_brain(self):
        self.install_light()
        state = ST.default_state()
        state.update(choice="light", phase="installing", consent_at=1.0, model_id=tiny_choice("light").model_id, total=TOTAL, bytes=TOTAL)
        ST.StateFile(self.own_dir, clock=self.clock).save(state)
        write_meminfo(self.meminfo, kb=1_000_000)
        again = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0)
        self.assertEqual(again.resume().code, "ram_too_small", "a model that cannot be loaded is not resumed")


class ServiceNumbersTests(OwnBrainApp):
    """The status numbers come from real samples: speed from bytes over time, time left from speed."""
    use_thread = True

    def test_speed_and_time_left_are_computed_from_the_samples(self):
        clock = [100.0]
        reached, release = threading.Event(), threading.Event()

        def downloader(url, dest_root, rel_dest, *, progress, should_cancel, **_kw):
            progress("download", 0, 10_000_000)
            clock[0] += 2.0
            progress("download", 2_000_000, 10_000_000)
            reached.set()
            release.wait(20)
            return SimpleNamespace(ok=False, code="cancelled", detail="")

        brain = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=True, idle_unload_seconds=0,
                         downloader=downloader, monotonic=lambda: clock[0], sleep=lambda _s: None)
        self.addCleanup(release.set)
        self.assertEqual(brain.start("light", consent=True), StartResult(True, "started"))
        self.assertTrue(reached.wait(10))
        st = brain.status()
        self.assertEqual((st["phase"], st["sub"]), ("downloading", "download"))
        self.assertEqual((st["bytes"], st["total"], st["percent"]), (2_000_000, 10_000_000, 20))
        self.assertEqual(st["speed"], 1_000_000, "2,000,000 bytes in 2 seconds")
        self.assertEqual(st["eta"], 8, "8,000,000 bytes left at 1,000,000 per second")
        release.set()
        self.assertTrue(brain.wait(10))
        st = brain.status()
        self.assertEqual((st["phase"], st["speed"], st["eta"]), ("paused", 0, None), "no speed is claimed when nothing is downloading")

    def test_the_first_sample_alone_gives_no_speed(self):
        reached, release = threading.Event(), threading.Event()

        def downloader(url, dest_root, rel_dest, *, progress, should_cancel, **_kw):
            progress("download", 500_000, 10_000_000)
            reached.set()
            release.wait(20)
            return SimpleNamespace(ok=False, code="cancelled", detail="")

        brain = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=True, idle_unload_seconds=0,
                         downloader=downloader, sleep=lambda _s: None)
        self.addCleanup(release.set)
        brain.start("light", consent=True)
        self.assertTrue(reached.wait(10))
        st = brain.status()
        self.assertEqual((st["speed"], st["eta"]), (0, None), "one sample says nothing about a speed; none is invented")
        release.set()
        brain.wait(10)

    def test_a_downloader_that_blows_up_leaves_an_honest_failure_not_a_crash(self):
        def downloader(*_args, **_kw):
            raise RuntimeError("boom")

        brain = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=True, idle_unload_seconds=0,
                         downloader=downloader, sleep=lambda _s: None)
        self.assertEqual(brain.start("light", consent=True), StartResult(True, "started"))
        self.assertTrue(brain.wait(10))
        st = brain.status()
        self.assertEqual((st["phase"], st["code"], st["detail"]), ("failed", "unexpected_error", "RuntimeError"))
        self.assertFalse(st["resumable"], "nothing was fetched, so there is nothing to continue from")
        self.assertFalse(brain.is_ready())


class NotifierAndIdleTests(OwnBrainApp):
    def test_the_notifier_hears_the_phases_in_order_and_the_last_word_is_ready(self):
        heard = []
        brain = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0,
                         notifier=heard.append, sleep=lambda _s: None)
        self.assertEqual(brain.start("light", consent=True), StartResult(True, "started"))
        phases = [row["phase"] for row in heard]
        self.assertEqual(phases[0], "downloading")
        self.assertIn("installing", phases)
        self.assertEqual(phases[-1], "ready")
        self.assertLess(phases.index("downloading"), phases.index("installing"))
        self.assertLess(phases.index("installing"), len(phases) - 1)
        self.assertEqual(heard[-1]["percent"], 100)
        self.assertTrue(all(isinstance(row, dict) and "title_fa" in row for row in heard))

    def test_a_notifier_that_raises_cannot_stop_the_job(self):
        def broken(_status):
            raise RuntimeError("the screen is gone")

        brain = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0,
                         notifier=broken, sleep=lambda _s: None)
        brain.start("light", consent=True)
        self.assertEqual(brain.status()["phase"], "ready")

    def test_the_idle_timer_gives_the_memory_back_and_the_next_question_loads_again(self):
        self.install_light()
        brain = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0.2)
        self.assertTrue(brain.is_ready())
        self.assertEqual(self.bridge.unloads, 0)
        brain.touch()
        wait_until(self, lambda: self.bridge.unloads >= 1, 10, "the idle unload")
        self.assertTrue(brain.is_ready(), "freeing memory does not take the brain away")
        self.assertIn("سلام! من مغزِ آزمایشی هستم.", self.ask("یه سوال عجیب و غریب درباره فلان"))
        self.assertEqual(len(self.bridge.loads), 2, "loaded again for the question")
        self.assertEqual(self.ob.status()["phase"], "ready")

    def test_touch_restarts_the_idle_timer_and_a_disabled_timer_never_fires(self):
        self.install_light()
        off = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0)
        off.touch()
        time.sleep(0.3)
        self.assertEqual(self.bridge.unloads, 0)
        brain = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0.6)
        brain.touch()
        time.sleep(0.4)
        brain.touch()                                           # used again: the countdown starts over
        time.sleep(0.4)
        self.assertEqual(self.bridge.unloads, 0, "0.8 s after the first touch, but only 0.4 s after the last one")
        wait_until(self, lambda: self.bridge.unloads >= 1, 10, "the idle unload after the last touch")

    def test_the_tick_makes_one_automatic_try_per_service_life(self):
        self.assertTrue(self.hub.grant_permission("network", user_approved=True).ok, "the yes that began this download had switched the internet on")
        state = ST.default_state()
        state.update(choice="light", phase="paused", code="app_closed", consent_at=1.0, model_id=tiny_choice("light").model_id, total=TOTAL, bytes=0)
        os.makedirs(self.own_dir, exist_ok=True)
        ST.StateFile(self.own_dir, clock=self.clock).save(state)
        brain = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0, sleep=lambda _s: None)
        with mock.patch.object(brain, "_online", return_value="offline"):
            first = brain.tick()
        self.assertEqual(first, StartResult(False, "offline", ""), "the automatic try was refused: no internet")
        self.assertEqual(brain.status()["phase"], "paused")
        self.assertIsNone(brain.tick(), "one automatic try per service life; after that only the user's own «ادامه»")
        self.assertIsNone(brain.tick())
        self.assertEqual((brain.status()["phase"], brain.status()["code"]), ("paused", "app_closed"))
        self.assertEqual(self.cdn.requests, [], "nothing was fetched behind the user's back")
        self.assertEqual(brain.resume(), StartResult(True, "started"), "the user's own order still works")
        self.assertEqual(brain.status()["phase"], "ready")

    def test_the_tick_resumes_an_agreed_download_once_and_then_stays_quiet(self):
        self.assertTrue(self.hub.grant_permission("network", user_approved=True).ok, "the yes that began this download had switched the internet on")
        state = ST.default_state()
        state.update(choice="light", phase="paused", code="app_closed", consent_at=1.0, model_id=tiny_choice("light").model_id, total=TOTAL, bytes=0)
        os.makedirs(self.own_dir, exist_ok=True)
        ST.StateFile(self.own_dir, clock=self.clock).save(state)
        brain = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0, sleep=lambda _s: None)
        self.assertEqual(brain.tick(), StartResult(True, "started"))
        self.assertEqual(brain.status()["phase"], "ready")
        self.assertIsNone(brain.tick())


if __name__ == "__main__":
    unittest.main()
