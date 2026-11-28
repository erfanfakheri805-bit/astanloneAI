"""
Prompt 959 (stage B3, «مغز خودکار») - the install step has a visible account: which of the four steps it is in, how far, and for how long.

Found on a real phone: after the download the app said "installing" and then nothing for minutes - the user could not tell a working install from a
frozen one, and asked for a percent "like the download". What is pinned here (the engine is a fake; nothing says how long the REAL load takes):

* `status()["install"]` = `{stage, step, steps, percent, stage_percent, elapsed, estimated, slow}`; all zeros outside the install;
* the file check is MEASURED (bytes read); the two engine steps report nothing, so their percent is an ESTIMATE from the time passed, it says so
  (`estimated`), it climbs but never reaches the end of its step - and never 100 before the model has answered a real question;
* the percent never goes backwards; garbage progress is not believed; the time that passed is real;
* a heartbeat refreshes the listener while the step runs and stops with it; a stale account never arrives after a newer one;
* a hub whose `prepare_model` takes no progress function still installs.
"""
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import ownbrain
from brain_hub.ownbrain import INSTALL_STEPS, OwnBrain, StartResult
from tests.ownbrain_support_prompt959 import OwnBrainApp
from tests.test_ownbrain_install_step_prompt959 import InstallingApp
from tests.test_ownbrain_threaded_prompt959 import wait_until

ZERO = {"stage": "", "step": 0, "steps": 4, "percent": 0, "stage_percent": None, "elapsed": 0, "estimated": False, "slow": False}


class Mono:
    """A clock the test moves by hand (the service's `monotonic`)."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def heartbeat_threads():
    return [thread for thread in threading.enumerate() if thread.name == "own-brain-heartbeat" and thread.is_alive()]


class Base(OwnBrainApp):
    def setUp(self):
        super().setUp()
        self.mono = Mono()
        self.svc = self.make_brain()

    def make_brain(self, use_thread=False, notifier=None, hub=None):
        brain = OwnBrain(hub or self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=use_thread, idle_unload_seconds=0,
                         monotonic=self.mono, notifier=notifier, sleep=lambda _s: None)
        self.addCleanup(brain._install_end)
        return brain

    def view(self):
        return self.svc._install_view("installing")


class TheStepsTests(unittest.TestCase):
    def test_the_four_steps_are_the_stages_of_the_model_pipeline_in_order(self):
        self.assertEqual([row[0] for row in INSTALL_STEPS], ["verify", "compatibility", "load", "smoke"])

    def test_the_spans_are_contiguous_start_at_zero_and_end_below_100(self):
        self.assertEqual(INSTALL_STEPS[0][1], 0)
        for earlier, later in zip(INSTALL_STEPS, INSTALL_STEPS[1:]):
            self.assertEqual(earlier[2], later[1], "no gap and no overlap between %s and %s" % (earlier[0], later[0]))
        self.assertLess(INSTALL_STEPS[-1][2], 100, "100 is only said by the ready phase, after a real answer")

    def test_only_the_file_check_is_measured(self):
        self.assertIsNone(INSTALL_STEPS[0][3])
        for name, _low, _high, expected in INSTALL_STEPS[1:]:
            self.assertGreater(expected, 0, name)


class InstallViewTests(Base):
    def test_outside_the_install_everything_is_zero(self):
        self.assertEqual(self.view(), ZERO, "no clock has started")
        self.svc._install_begin()
        self.mono.advance(7)
        for phase in ("idle", "asking", "downloading", "paused", "failed", "ready"):
            with self.subTest(phase=phase):
                self.assertEqual(self.svc._install_view(phase), ZERO)
        self.assertEqual(self.svc.status()["install"], ZERO, "an idle brain's account carries the key, all zeros")

    def test_before_the_first_step_only_the_time_runs(self):
        self.svc._install_begin()
        self.mono.advance(3)
        self.assertEqual(self.view(), dict(ZERO, elapsed=3))

    def test_the_file_check_is_measured_not_timed(self):
        self.svc._install_begin()
        self.svc._install_progress("verify", 0.0, 0, 100)
        self.assertEqual(self.view(), dict(ZERO, stage="verify", step=1, percent=0, stage_percent=0))
        self.svc._install_progress("verify", 0.5, 50, 100)
        self.mono.advance(100)
        got = self.view()
        self.assertEqual((got["stage"], got["step"], got["percent"], got["stage_percent"], got["estimated"], got["slow"], got["elapsed"]),
                         ("verify", 1, 15, 50, False, False, 100), "a measured step does not move with the clock")
        self.svc._install_progress("verify", 1.0, 100, 100)
        self.assertEqual((self.view()["percent"], self.view()["stage_percent"]), (30, 100))

    def test_the_engine_steps_are_estimated_from_the_time_and_say_so(self):
        self.svc._install_begin()
        self.svc._install_progress("verify", 1.0, 100, 100)
        self.svc._install_progress("compatibility")
        got = self.view()
        self.assertEqual((got["stage"], got["step"], got["percent"], got["estimated"]), ("compatibility", 2, 30, True))
        self.mono.advance(2)                                                # the expected time of this step: halfway through its span
        self.assertEqual(self.view()["percent"], 31)
        self.svc._install_progress("load")
        self.assertEqual((self.view()["stage"], self.view()["step"], self.view()["percent"]), ("load", 3, 32))
        self.mono.advance(45)                                               # the expected time of the load: halfway through its span
        got = self.view()
        self.assertEqual((got["percent"], got["stage_percent"], got["estimated"], got["slow"]), (57, 50, True, False))
        self.mono.advance(136)                                              # 181 s in the step: more than 4 times what was expected
        got = self.view()
        self.assertEqual((got["percent"], got["slow"], got["elapsed"]), (72, True, 2 + 45 + 136))
        self.svc._install_progress("smoke")
        got = self.view()
        self.assertEqual((got["stage"], got["step"], got["steps"], got["percent"]), ("smoke", 4, 4, 82))
        self.mono.advance(20)
        self.assertEqual(self.view()["percent"], 90)

    def test_an_estimated_step_never_reaches_the_end_of_its_span_nor_100(self):
        for name, _low, high, expected in INSTALL_STEPS[1:]:
            with self.subTest(step=name):
                self.svc._install_end()
                self.svc._install_begin()
                self.svc._install_progress(name)
                self.mono.advance(10 ** 7)
                got = self.view()
                self.assertLess(got["percent"], high, "a step that is still running is not at the end of its span")
                self.assertLess(got["percent"], 100)
                self.assertTrue(got["slow"])
                self.assertGreater(got["percent"], high - 3, "after a very long time it is close to the end, not stuck at the start")

    def test_the_percent_never_goes_backwards(self):
        self.svc._install_begin()
        seen = []
        for stage, fraction, wait in (("verify", 0.2, 1), ("verify", 0.9, 1), ("verify", 0.1, 1), ("compatibility", None, 1), ("load", None, 30),
                                      ("load", None, 0), ("verify", 0.0, 0), ("smoke", None, 5), ("load", None, 0), ("verify", 0.5, 0)):
            self.svc._install_progress(stage, fraction)
            self.mono.advance(wait)
            seen.append(self.view()["percent"])
        self.assertEqual(seen, sorted(seen), seen)
        self.assertLess(max(seen), 100)

    def test_garbage_progress_is_not_believed(self):
        for fraction in (None, "0.9", True, False, float("nan"), [], {}, object()):
            with self.subTest(fraction=repr(fraction)):
                self.svc._install_end()
                self.svc._install_begin()
                self.svc._install_progress("verify", fraction, "x", None)
                got = self.view()
                self.assertEqual((got["stage"], got["percent"], got["stage_percent"]), ("verify", 0, 0))
        for fraction, percent in ((5, 30), (-3, 0), (2 ** 70, 30), (float("inf"), 30)):
            with self.subTest(fraction=fraction):
                self.svc._install_end()
                self.svc._install_begin()
                self.svc._install_progress("verify", fraction)
                self.assertEqual(self.view()["percent"], percent, "a number outside 0..1 is cut to the nearest end")

    def test_a_step_the_service_does_not_know_is_only_the_clock(self):
        self.svc._install_begin()
        for name in ("register", "", "VERIFY", None, 5):
            with self.subTest(name=name):
                self.svc._install_progress(name)
                self.mono.advance(1)
                got = self.view()
                self.assertEqual((got["stage"], got["step"], got["percent"], got["estimated"]), ("", 0, 0, False))
        self.assertEqual(self.view()["elapsed"], 5)

    def test_a_progress_function_that_is_called_wrongly_never_raises(self):
        self.svc._install_progress("verify", 0.5)                         # no install is running
        self.assertEqual(self.view(), ZERO)
        self.svc._install_begin()
        self.svc._install_progress(None)                                    # a step with no name
        self.svc._install_progress("verify", object(), object(), object())

    def test_begin_twice_keeps_the_first_clock_and_end_forgets_it(self):
        self.svc._install_begin()
        self.mono.advance(10)
        self.svc._install_begin()
        self.assertEqual(self.view()["elapsed"], 10, "the second begin did not restart the clock")
        self.svc._install_end()
        self.svc._install_end()                                           # any number of times, at any time
        self.assertEqual(self.view(), ZERO)
        self.svc._install_begin()
        self.assertEqual(self.view()["elapsed"], 0, "a new install starts a new clock")


class HeartbeatTests(Base):
    def test_while_the_step_runs_the_listener_is_told_again_and_again_and_then_not(self):
        heard = []
        brain = self.make_brain(use_thread=True, notifier=heard.append)
        with mock.patch.object(ownbrain, "INSTALL_HEARTBEAT_SECONDS", 0.02):
            brain._install_begin()
            wait_until(self, lambda: len(heard) >= 5, 10, "five heartbeats")
            self.assertEqual(len(heartbeat_threads()), 1)
            brain._install_end()
            wait_until(self, lambda: not heartbeat_threads(), 5, "the heartbeat to end with the install")
        count = len(heard)
        time.sleep(0.2)
        self.assertLessEqual(len(heard) - count, 0, "nothing is told after the install ended")
        self.assertTrue(all(isinstance(row, dict) and "install" in row for row in heard))

    def test_a_synchronous_service_starts_no_heartbeat(self):
        brain = self.make_brain(use_thread=False)
        brain._install_begin()
        self.assertEqual(heartbeat_threads(), [])
        brain._install_end()

    def test_begin_twice_starts_one_heartbeat(self):
        brain = self.make_brain(use_thread=True)
        brain._install_begin()
        brain._install_begin()
        self.assertEqual(len(heartbeat_threads()), 1)
        brain._install_end()
        wait_until(self, lambda: not heartbeat_threads(), 5, "the heartbeat to end")

    def test_a_listener_that_raises_does_not_kill_the_heartbeat(self):
        calls = []

        def broken(account):
            calls.append(account)
            raise RuntimeError("the screen is gone")

        brain = self.make_brain(use_thread=True, notifier=broken)
        with mock.patch.object(ownbrain, "INSTALL_HEARTBEAT_SECONDS", 0.02):
            brain._install_begin()
            wait_until(self, lambda: len(calls) >= 4, 10, "the heartbeat to go on after a listener error")
            brain._install_end()


class NewerAccountWinsTests(Base):
    def test_an_old_account_is_not_delivered_after_a_newer_one(self):
        """The heartbeat can be in the middle of reading the status while the worker ends the install: the old (still "installing") account must
        not reach the listener after the new one, or a finished install would leave its notification up."""
        heard = []
        brain = self.make_brain(notifier=heard.append)
        real_status, entered, gate, calls = brain.status, threading.Event(), threading.Event(), []

        def slow_status(*args, **kwargs):
            account = real_status(*args, **kwargs)
            calls.append(account)
            if len(calls) == 1:
                account["marker"] = "old"
                entered.set()
                gate.wait(10)
            else:
                account["marker"] = "new"
            return account

        brain.status = slow_status
        old = threading.Thread(target=brain._notify, kwargs={"force": True})
        old.start()
        self.assertTrue(entered.wait(10))
        brain._notify(force=True)                                           # the newer account, delivered while the old one is still being read
        gate.set()
        old.join(10)
        self.assertEqual([row["marker"] for row in heard], ["new"], "the stale account was dropped")

    def test_accounts_in_order_are_all_delivered(self):
        heard = []
        brain = self.make_brain(notifier=heard.append)
        for _ in range(3):
            brain._notify(force=True)
        self.assertEqual(len(heard), 3)

    def test_a_throttled_account_is_not_delivered_but_a_forced_one_is(self):
        heard = []
        brain = self.make_brain(notifier=heard.append)
        brain._notify(force=True)
        brain._notify()                                                     # the same instant: inside the throttle window
        self.assertEqual(len(heard), 1)
        brain._notify(force=True)
        self.assertEqual(len(heard), 2)


class InstallAccountThroughThePipelineTests(Base):
    def test_every_step_is_announced_in_order_and_the_last_word_is_ready(self):
        heard = []
        brain = self.make_brain(notifier=heard.append)
        self.assertEqual(brain.start("light", consent=True), StartResult(True, "started"))
        installs = [row["install"] for row in heard if row["phase"] == "installing"]
        stages = []
        for row in installs:
            if row["stage"] and (not stages or stages[-1] != row["stage"]):
                stages.append(row["stage"])
        self.assertEqual(stages, ["verify", "compatibility", "load", "smoke"])
        percents = [row["percent"] for row in installs]
        self.assertEqual(percents, sorted(percents), "the listener never sees the percent go back")
        self.assertLess(max(percents), 100)
        self.assertTrue(all(row["steps"] == 4 for row in installs))
        self.assertEqual(heard[-1]["phase"], "ready")
        self.assertEqual(heard[-1]["install"], ZERO, "a finished install carries no step")
        self.assertEqual(brain.status()["install"], ZERO)

    def test_a_hub_that_takes_no_progress_function_still_installs(self):
        real = self.hub

        class OlderHub:
            """The same hub, except that its `prepare_model` knows nothing of a progress function."""

            def __getattr__(self, name):
                return getattr(real, name)

            def prepare_model(self, model_id):
                return real.prepare_model(model_id)

        brain = self.make_brain(hub=OlderHub())
        self.assertEqual(brain.start("light", consent=True), StartResult(True, "started"))
        self.assertEqual(brain.status()["phase"], "ready")

    def test_a_hub_with_a_progress_function_gets_ours(self):
        seen = []
        real = self.hub

        class NewerHub:
            def __getattr__(self, name):
                return getattr(real, name)

            def prepare_model(self, model_id, progress=None):
                seen.append(progress)
                return real.prepare_model(model_id, progress)

        brain = self.make_brain(hub=NewerHub())
        brain.start("light", consent=True)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].__func__, OwnBrain._install_progress, "the service's own progress function")

    def test_a_failed_install_leaves_no_clock_and_no_heartbeat(self):
        self.bridge.load_result = "ERR\nengine_load_failed\nout of memory"
        brain = self.make_brain(use_thread=True)
        self.assertEqual(brain.start("light", consent=True), StartResult(True, "started"))
        self.assertTrue(brain.wait(30))
        st = brain.status()
        self.assertEqual((st["phase"], st["code"]), ("failed", "engine_load_failed"))
        self.assertEqual(st["install"], ZERO)
        self.assertIsNone(brain._install)
        self.assertIsNone(brain._beat)
        wait_until(self, lambda: not heartbeat_threads(), 5, "no heartbeat after a failed install")

    def test_a_download_that_fails_never_starts_the_install_clock(self):
        brain = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0, sleep=lambda _s: None,
                         downloader=lambda *_a, **_k: type("R", (), {"ok": False, "code": "http_error", "detail": "503"})())
        self.addCleanup(brain._install_end)
        brain.start("light", consent=True)
        st = brain.status()
        self.assertEqual((st["phase"], st["code"]), ("failed", "http_error"))
        self.assertIsNone(brain._install)


class HeldInstallTests(InstallingApp):
    """The real worker thread, the real engine bridge (a fake), and a first question the test holds: the install stays in its last step."""

    def test_the_status_says_which_step_how_far_and_for_how_long(self):
        self.reach_installing()
        st = self.ob.status()
        inst = st["install"]
        self.assertEqual((inst["stage"], inst["step"], inst["steps"], inst["estimated"]), ("smoke", 4, 4, True), inst)
        self.assertTrue(82 <= inst["percent"] <= 98, inst)
        self.assertGreaterEqual(inst["elapsed"], 0)
        self.assertEqual(st["percent"], 100, "the download's own figure is not touched")
        text = self.ask("وضعیت مغز")
        for part in ("⏳ نصب:", "(حدودی)", "مرحلهٔ ۴ از ۴", "آزمایشِ اول", "از شروعِ نصب گذشته", "دارم مغز را نصب و برای بار اول آزمایش می‌کنم"):
            self.assertIn(part, text)
        self.assertNotIn("۱۰۰٪", text)
        self.finish_install()
        done = self.ob.status()
        self.assertEqual((done["phase"], done["install"]), ("ready", ZERO))

    def test_a_heartbeat_keeps_the_listener_told_while_the_first_question_is_held_and_stops_after(self):
        heard = []
        self.ob.set_notifier(heard.append)
        with mock.patch.object(ownbrain, "INSTALL_HEARTBEAT_SECONDS", 0.05):
            self.reach_installing()
            self.assertEqual(len(heartbeat_threads()), 1)
            mark = len([row for row in heard if row["phase"] == "installing"])
            wait_until(self, lambda: len([row for row in heard if row["phase"] == "installing"]) >= mark + 4, 10, "heartbeats during the held step")
            self.finish_install()
            wait_until(self, lambda: not heartbeat_threads(), 5, "the heartbeat to end with the install")
        self.assertEqual(heard[-1]["phase"], "ready")
        installing = [row["install"]["percent"] for row in heard if row["phase"] == "installing"]
        self.assertEqual(installing, sorted(installing), "the percent the listener hears never goes back")
        count = len(heard)
        time.sleep(0.3)
        self.assertEqual(len(heard), count, "nothing more is told once the brain is ready")

    def test_a_free_sentence_and_the_other_commands_are_untouched_by_the_account(self):
        self.reach_installing()
        from persian_brain import hub_messages_ownbrain as BM
        from tests.test_ownbrain_threaded_prompt959 import FREE
        self.assertIn(BM.lead_line("installing"), self.ask(FREE))
        self.assertEqual(self.ask(BM.PAUSE), BM.nothing_running(self.ob.status()))
        self.finish_install()


if __name__ == "__main__":
    unittest.main()
