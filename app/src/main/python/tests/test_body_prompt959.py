"""
Prompt 959 (stage B, the body) - `brain_hub.body`: the job registry that keeps ONE foreground service for the long jobs, and the unified
emergency stop.

The phone's service is a fake door that records every call; the hub is a small fake that records what the stop asks of it. The tests prove the
LOGIC of the body - when it asks the phone to hold or release, what it never asks twice, what it stops and in which order - not that Android keeps
a process alive.
"""
import json
import os
import sys
import threading
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import platform_boot
from brain_hub import body as B
from brain_hub import service
from native_bridge import body as native_body
from persian_brain import hub_body, hub_hooks


class Result:
    def __init__(self, ok=True, code="", data=None):
        self.ok, self.code, self.data = ok, code, data


class FakeDoor:
    """The `.body` door: records every call in the shared `log`."""

    def __init__(self, log=None):
        self.log = log if log is not None else []
        self.hold_result = Result(True)
        self.release_result = Result(True)
        self.running_result = Result(True, data={"running": True})
        self.raise_on_hold = False

    def hold(self, title, text, percent):
        self.log.append(("door.hold", title, text, percent))
        if self.raise_on_hold:
            raise RuntimeError("boom")
        return self.hold_result

    def release(self):
        self.log.append(("door.release",))
        return self.release_result

    def running(self):
        self.log.append(("door.running",))
        return self.running_result

    def calls(self, name):
        return [entry for entry in self.log if entry[0] == name]


class FakeDoors:
    def __init__(self, door):
        self.body = door


class FakeOwn:
    def __init__(self, log, result=True):
        self.log, self.result = log, result

    def halt(self):
        self.log.append(("own.halt",))
        return self.result


class PhasedOwn:
    """An own brain that says its phase (`status()`) the way the real one does. `halt()` stops a download only (`halts`); `then` is the phase
    the brain is in right after the halt (a download that ends at this very moment)."""

    def __init__(self, log, phase, halts=False, then=None):
        self.log, self.phase, self.halts, self.then = log, phase, halts, then

    def halt(self):
        self.log.append(("own.halt",))
        if self.then is not None:
            self.phase = self.then
        return self.halts

    def status(self):
        self.log.append(("own.status", self.phase))
        return {"phase": self.phase}


class FakeHub:
    root = "/fake/hub"

    def __init__(self, log=None, cancelled=0, own=None):
        self.log = log if log is not None else []
        self._cancelled = cancelled
        self._own_brain = own
        self.memory = None

    def cancel_model_generation(self):
        self.log.append(("hub.cancel",))
        return self._cancelled


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make(**kwargs):
    log = []
    door = FakeDoor(log)
    clock = Clock()
    hub = FakeHub(log, **kwargs)
    return B.Body(hub, doors=FakeDoors(door), monotonic=clock), door, clock, hub, log


# ============================================================================ the words of the notification
class DescribeTests(unittest.TestCase):
    def test_a_download_with_everything_known(self):
        title, text, percent = B.describe_ownbrain({"phase": "downloading", "percent": 42, "bytes": 1_100_000_000, "total": 2_600_000_000, "eta": 720})
        self.assertEqual(title, "در حال گرفتنِ مغز")
        self.assertEqual(text, "۴۲٪ · ۱٫۱ گیگابایت از ۲٫۶ گیگابایت · حدود ۱۲ دقیقه مانده")
        self.assertEqual(percent, 42)

    def test_an_unknown_total_has_no_percent(self):
        title, text, percent = B.describe_ownbrain({"phase": "downloading", "percent": 50, "bytes": 5_000_000, "total": 0})
        self.assertEqual(percent, -1)
        self.assertNotIn("٪", text)
        self.assertIn("مگابایت", B.describe_ownbrain({"phase": "downloading", "bytes": 5_000_000, "total": 9_000_000})[1])

    def test_nothing_known_says_it_started(self):
        self.assertEqual(B.describe_ownbrain({"phase": "downloading"}), ("در حال گرفتنِ مغز", "شروع شد…", -1))

    def test_installing_and_verifying_have_their_own_words(self):
        title, text, percent = B.describe_ownbrain({"phase": "installing", "percent": 100, "bytes": 5, "total": 5})
        self.assertEqual((title, percent), ("در حال نصبِ مغز", -1))
        self.assertIn("آزمایش", text)
        title, text, percent = B.describe_ownbrain({"phase": "downloading", "sub": "verify", "percent": 100, "bytes": 5, "total": 5})
        self.assertIn("هش", text)
        self.assertEqual(percent, 100)

    def test_the_eta_in_words(self):
        eta = B._eta
        self.assertEqual(eta(20), "کمتر از یک دقیقه مانده")
        self.assertEqual(eta(150), "حدود ۳ دقیقه مانده")
        self.assertEqual(eta(3600), "حدود ۱ ساعت مانده")
        self.assertEqual(eta(3600 + 600), "حدود ۱ ساعت و ۱۰ دقیقه مانده")
        for bad in (None, -1, "x", True, 1.5):
            self.assertEqual(eta(bad), "")

    def test_sizes_in_persian_digits_and_never_a_bad_value(self):
        self.assertEqual(B._size(2_600_000_000), "۲٫۶ گیگابایت")
        self.assertEqual(B._size(450_000_000), "۴۵۰ مگابایت")
        self.assertEqual(B._size(1500), "۲ کیلوبایت")
        for bad in (None, 0, -5, True, "7", 1.5):
            self.assertEqual(B._size(bad), "")

    def test_half_minutes_round_up_the_same_way_every_time(self):
        self.assertEqual([B._eta(s) for s in (90, 150, 210)], ["حدود ۲ دقیقه مانده", "حدود ۳ دقیقه مانده", "حدود ۴ دقیقه مانده"])

    def test_the_notifier_swallows_a_wrong_status(self):
        body, door, _clock, _hub, _log = make()
        body.on_ownbrain({"phase": "downloading", "percent": "x", "bytes": "y", "total": object()})
        body.on_ownbrain(None)
        body.on_ownbrain("nonsense")
        self.assertEqual(door.calls("door.hold"), [])


# ============================================================================ the job registry and the service
class JobTests(unittest.TestCase):
    def test_nothing_is_called_until_a_job_exists(self):
        body, door, _clock, _hub, log = make()
        self.assertEqual(log, [])
        self.assertEqual(body.jobs(), [])
        self.assertEqual(body.status(), {"holding": False, "jobs": [], "code": "", "dead": ""})

    def test_a_job_holds_the_service_with_its_words(self):
        body, door, _clock, _hub, _log = make()
        self.assertTrue(body.job("ownbrain", "در حال گرفتنِ مغز", "۴٪", 4))
        self.assertEqual(door.calls("door.hold"), [("door.hold", "در حال گرفتنِ مغز", "۴٪", 4)])
        self.assertTrue(body.status()["holding"])
        self.assertEqual(body.jobs(), ["ownbrain"])

    def test_the_end_of_the_last_job_releases_the_service_once(self):
        body, door, _clock, _hub, _log = make()
        body.job("ownbrain", "t", "x", 1)
        self.assertTrue(body.done("ownbrain"))
        self.assertEqual(len(door.calls("door.release")), 1)
        self.assertFalse(body.done("ownbrain"), "a job that is not there ends nothing")
        self.assertEqual(len(door.calls("door.release")), 1, "and releases nothing again")
        self.assertFalse(body.status()["holding"])

    def test_a_job_that_never_held_the_service_does_not_release_one(self):
        body, door, _clock, _hub, _log = make()
        door.hold_result = Result(False, "not_allowed")
        body.job("ownbrain", "t", "x", 1)
        self.assertFalse(body.status()["holding"])
        body.done("ownbrain")
        self.assertEqual(door.calls("door.release"), [])

    def test_the_same_job_moving_a_little_is_not_passed_on_every_time(self):
        body, door, clock, _hub, _log = make()
        body.job("ownbrain", "در حال گرفتنِ مغز", "۴٪", 4)
        for percent in range(5, 9):
            clock.advance(0.2)
            body.job("ownbrain", "در حال گرفتنِ مغز", "%d٪" % percent, percent)
        self.assertEqual(len(door.calls("door.hold")), 1, "the updates within the gap were held back")
        clock.advance(B.MIN_GAP_SECONDS)
        body.job("ownbrain", "در حال گرفتنِ مغز", "۹٪", 9)
        self.assertEqual(len(door.calls("door.hold")), 2)
        self.assertEqual(door.calls("door.hold")[-1][3], 9)

    def test_a_change_of_kind_always_goes_through(self):
        body, door, clock, _hub, _log = make()
        body.job("ownbrain", "در حال گرفتنِ مغز", "۹۹٪", 99)
        clock.advance(0.01)
        body.job("ownbrain", "در حال نصبِ مغز", "…", -1)
        self.assertEqual([c[1] for c in door.calls("door.hold")], ["در حال گرفتنِ مغز", "در حال نصبِ مغز"])

    def test_the_same_words_twice_are_one_call(self):
        body, door, clock, _hub, _log = make()
        body.job("ownbrain", "t", "x", 1)
        clock.advance(100)
        body.job("ownbrain", "t", "x", 1)
        self.assertEqual(len(door.calls("door.hold")), 1)

    def test_two_jobs_show_the_first_and_count_the_rest(self):
        body, door, _clock, _hub, _log = make()
        body.job("ownbrain", "در حال گرفتنِ مغز", "۴٪", 4)
        body.job("other", "کارِ دیگر", "x", 10)
        last = door.calls("door.hold")[-1]
        self.assertEqual(last[1], "در حال گرفتنِ مغز")
        self.assertIn("و ۱ کارِ دیگر", last[2])
        body.done("ownbrain")
        self.assertEqual(door.calls("door.hold")[-1][1], "کارِ دیگر")
        self.assertEqual(door.calls("door.release"), [], "one job is left, so the service stays")
        body.done("other")
        self.assertEqual(len(door.calls("door.release")), 1)

    def test_the_note_about_other_jobs_survives_a_long_text(self):
        body, door, _clock, _hub, _log = make()
        body.job("ownbrain", "t", "ن" * B.MAX_TEXT, 1)
        body.job("other", "u", "x", 1)
        text = door.calls("door.hold")[-1][2]
        self.assertLessEqual(len(text), B.MAX_TEXT)
        self.assertTrue(text.endswith("و ۱ کارِ دیگر"), text[-30:])

    def test_a_job_that_joins_or_leaves_is_never_held_back_by_the_gap(self):
        body, door, _clock, _hub, _log = make()
        body.job("ownbrain", "t", "x", 1)
        body.job("other", "u", "y", 1)                      # the fake clock has not moved
        body.job("third", "v", "z", 1)
        body.done("other")
        shown = [call[2] for call in door.calls("door.hold")]
        self.assertEqual(shown, ["x", "x · و ۱ کارِ دیگر", "x · و ۲ کارِ دیگر", "x · و ۱ کارِ دیگر"])

    def test_bad_jobs_are_refused_and_call_nothing(self):
        body, door, _clock, _hub, _log = make()
        for args in (("Bad Name", "t", "x", 1), ("", "t", "x", 1), (None, "t", "x", 1), ("a" * 40, "t", "x", 1), ("ok", "", "x", 1),
                     ("ok", "   ", "x", 1), ("ok", "t", "x", 101), ("ok", "t", "x", -2), ("ok", "t", "x", True), ("ok", "t", "x", 1.5), ("1ok", "t", "x", 1)):
            with self.subTest(args):
                self.assertFalse(body.job(*args))
        self.assertEqual(door.log, [])
        self.assertEqual(body.jobs(), [])

    def test_too_many_jobs_are_refused_but_the_old_ones_still_update(self):
        body, door, _clock, _hub, _log = make()
        for n in range(B.MAX_JOBS):
            self.assertTrue(body.job("job%d" % n, "t", "x", 1))
        self.assertFalse(body.job("one_too_many", "t", "x", 1))
        self.assertTrue(body.job("job0", "t", "y", 2))
        self.assertEqual(len(body.jobs()), B.MAX_JOBS)

    def test_long_words_are_cut_to_what_the_phone_accepts(self):
        body, door, _clock, _hub, _log = make()
        body.job("ownbrain", "ع" * 200, "ن" * 500, 1)
        _name, title, text, _percent = door.calls("door.hold")[0]
        self.assertLessEqual(len(title), B.MAX_TITLE)
        self.assertLessEqual(len(text), B.MAX_TEXT)

    def test_the_limits_equal_the_doors_own(self):
        self.assertEqual((B.MAX_TITLE, B.MAX_TEXT), (native_body.MAX_TITLE, native_body.MAX_TEXT))


class FailureTests(unittest.TestCase):
    def test_an_apk_without_the_service_is_asked_once_and_never_again(self):
        for code in ("unavailable_platform", "native_feature_missing", "bad_class_name"):
            with self.subTest(code):
                body, door, clock, _hub, _log = make()
                door.hold_result = Result(False, code)
                body.job("ownbrain", "t", "x", 1)
                self.assertEqual(body.status()["dead"], code)
                for percent in range(2, 6):
                    clock.advance(10)
                    body.job("ownbrain", "t", "x", percent)
                self.assertEqual(len(door.calls("door.hold")), 1)
                body.done("ownbrain")
                self.assertEqual(door.calls("door.release"), [])

    def test_a_refusal_that_may_pass_is_tried_again_with_the_next_update(self):
        body, door, clock, _hub, _log = make()
        door.hold_result = Result(False, "not_allowed")
        body.job("ownbrain", "t", "x", 1)
        self.assertEqual(body.status()["dead"], "")
        self.assertEqual(body.status()["code"], "not_allowed")
        door.hold_result = Result(True)
        clock.advance(10)
        body.job("ownbrain", "t", "x", 2)
        self.assertTrue(body.status()["holding"])

    def test_a_door_that_raises_never_breaks_the_caller(self):
        body, door, _clock, _hub, _log = make()
        door.raise_on_hold = True
        self.assertTrue(body.job("ownbrain", "t", "x", 1))
        self.assertFalse(body.status()["holding"])
        body.done("ownbrain")

    def test_the_phones_own_answer_about_running(self):
        body, door, _clock, _hub, _log = make()
        self.assertTrue(body.running())
        door.running_result = Result(True, data={"running": False})
        self.assertFalse(body.running())
        door.running_result = Result(False, "unavailable_platform")
        self.assertIsNone(body.running())

    def test_a_door_that_cannot_even_be_made_says_unknown(self):
        body = B.Body(FakeHub(), doors=None)
        with mock.patch("native_bridge.facade.for_app", side_effect=RuntimeError("no doors")):
            self.assertIsNone(body.running())
            self.assertTrue(body.job("ownbrain", "t", "x", 1))
            body.done("ownbrain")


class OwnBrainNotifierTests(unittest.TestCase):
    """`on_ownbrain` is what the own brain calls on every change of its status: the service lives exactly while it downloads or installs."""

    def test_the_service_is_held_while_the_brain_downloads_or_installs(self):
        for phase in ("downloading", "installing"):
            with self.subTest(phase):
                body, door, _clock, _hub, _log = make()
                body.on_ownbrain({"phase": phase, "percent": 10, "bytes": 1_000_000, "total": 10_000_000})
                self.assertEqual(body.jobs(), ["ownbrain"])
                self.assertTrue(body.status()["holding"])
                self.assertEqual(len(door.calls("door.hold")), 1)

    def test_every_other_phase_lets_the_service_go(self):
        for phase in ("idle", "paused", "failed", "ready", "", "weird"):
            with self.subTest(phase):
                body, door, _clock, _hub, _log = make()
                body.on_ownbrain({"phase": "downloading", "percent": 10, "bytes": 1_000_000, "total": 10_000_000})
                body.on_ownbrain({"phase": phase})
                self.assertEqual(body.jobs(), [])
                self.assertFalse(body.status()["holding"])
                self.assertEqual(len(door.calls("door.release")), 1)

    def test_progress_reaches_the_notification_after_the_gap(self):
        body, door, clock, _hub, _log = make()
        body.on_ownbrain({"phase": "downloading", "percent": 10, "bytes": 1_000_000, "total": 10_000_000})
        clock.advance(B.MIN_GAP_SECONDS)
        body.on_ownbrain({"phase": "downloading", "percent": 20, "bytes": 2_000_000, "total": 10_000_000})
        title, text, percent = door.calls("door.hold")[-1][1:]
        self.assertEqual((title, percent), ("در حال گرفتنِ مغز", 20))
        self.assertTrue(text.startswith("۲۰٪"), text)

    def test_the_end_of_the_download_without_a_service_never_touches_the_door(self):
        body, door, _clock, _hub, _log = make()
        body.on_ownbrain({"phase": "ready"})
        self.assertEqual(door.log, [])


class ConcurrencyTests(unittest.TestCase):
    def test_many_threads_end_consistent(self):
        body, door, _clock, _hub, _log = make()
        errors = []

        def work(n):
            try:
                for i in range(40):
                    name = "job%d" % (n % 4)
                    body.job(name, "t%d" % n, "x%d" % i, i % 100)
                    if i % 3 == 0:
                        body.done(name)
            except Exception as exc:                    # pragma: no cover - the test fails below
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        self.assertEqual(errors, [])
        for name in list(body.jobs()):
            body.done(name)
        self.assertEqual(body.jobs(), [])
        self.assertFalse(body.status()["holding"])
        last = [entry for entry in door.log if entry[0] in ("door.hold", "door.release")][-1]
        self.assertEqual(last, ("door.release",), "the phone's service is released at the end, whatever the order of the threads was")


# ============================================================================ the emergency stop
class FakeCloud:
    def __init__(self, log, mode="auto", halted=False):
        self.log = log
        self._settings = {"mode": mode, "halted": halted}

    class _Settings:
        def __init__(self, outer):
            self.outer = outer

        def get(self):
            return dict(self.outer._settings)

    @property
    def settings(self):
        return FakeCloud._Settings(self)

    def halt(self):
        self.log.append(("cloud.halt",))
        self._settings["halted"] = True


class EmergencyStopTests(unittest.TestCase):
    def stop(self, *, own=True, cancelled=1, cloud=None, hold=True):
        """Stop one hub whose parts all write into one `log`. `cloud` is None (no cloud brain at all) or `(mode, halted)`."""
        log = []
        door = FakeDoor(log)
        hub = FakeHub(log, cancelled=cancelled, own=FakeOwn(log, own))
        body = B.Body(hub, doors=FakeDoors(door), monotonic=Clock())
        if hold:
            body.job("ownbrain", "t", "x", 1)
            log.append(("---",))
        fake_cloud = FakeCloud(log, *cloud) if cloud is not None else None
        with mock.patch("brain_v2.get_brain", return_value=fake_cloud):
            done = body.emergency_stop()
        return done, body, door, log

    def test_everything_that_runs_is_stopped_and_the_service_goes_last(self):
        done, body, door, log = self.stop(cloud=("auto", False))
        after = log[log.index(("---",)) + 1:]
        self.assertEqual([entry[0] for entry in after], ["own.halt", "hub.cancel", "cloud.halt", "door.release"], "the stops first, the service last")
        self.assertEqual(done, {"stopped": ["download", "engine", "cloud"], "released": True})
        self.assertEqual(body.jobs(), [])
        self.assertFalse(body.status()["holding"])

    def test_only_what_really_ran_is_named(self):
        done, _body, _door, _log = self.stop(own=False, cancelled=0, cloud=None, hold=False)
        self.assertEqual(done, {"stopped": [], "released": False})

    def test_the_cloud_is_halted_only_when_it_is_on_and_not_halted_already(self):
        for mode, halted, expect in (("auto", False, True), ("auto", True, False), ("off", False, False)):
            with self.subTest(mode=mode, halted=halted):
                done, _body, _door, log = self.stop(cloud=(mode, halted))
                self.assertEqual("cloud" in done["stopped"], expect)
                self.assertEqual(("cloud.halt",) in log, expect, "the cloud brain is asked to halt exactly when it is reported as stopped")

    def test_a_cloud_that_cannot_be_reached_is_not_a_problem(self):
        done, _body, _door, _log = self.stop(cloud=None)
        self.assertNotIn("cloud", done["stopped"])
        with mock.patch("brain_v2.get_brain", side_effect=RuntimeError("boom")):
            body, _door, _clock, _hub, _log = make()
            self.assertEqual(body.emergency_stop(), {"stopped": [], "released": False})

    def test_one_part_failing_never_stops_the_others(self):
        log = []

        class BadOwn:
            def halt(self):
                raise RuntimeError("boom")

        hub = FakeHub(log, cancelled=2, own=BadOwn())
        door = FakeDoor(log)
        body = B.Body(hub, doors=FakeDoors(door), monotonic=Clock())
        body.job("ownbrain", "t", "x", 1)
        with mock.patch("brain_v2.get_brain", return_value=FakeCloud(log)):
            done = body.emergency_stop()
        self.assertEqual(done, {"stopped": ["engine", "cloud"], "released": True})

    def test_the_stop_is_safe_to_repeat(self):
        body, door, _clock, hub, _log = make(cancelled=0)
        with mock.patch("brain_v2.get_brain", return_value=None):
            first = body.emergency_stop()
            second = body.emergency_stop()
        self.assertEqual(first, {"stopped": [], "released": False})
        self.assertEqual(second, first)
        self.assertEqual(door.calls("door.release"), [])

    def test_a_service_that_was_never_up_is_not_released_for_nothing(self):
        done, _body, door, _log = self.stop(hold=False)
        self.assertFalse(done["released"])
        self.assertEqual(door.calls("door.release"), [])

    # ---- the step that cannot be interrupted: the own brain installs a finished download (verify, load, the first test question)
    def stop_in_phase(self, phase, *, cloud=None, **own):
        log = []
        door = FakeDoor(log)
        hub = FakeHub(log, cancelled=1, own=PhasedOwn(log, phase, **own))
        body = B.Body(hub, doors=FakeDoors(door), monotonic=Clock())
        body.job("ownbrain", "t", "x", 1)
        log.append(("---",))
        fake_cloud = FakeCloud(log, *cloud) if cloud is not None else None
        with mock.patch("brain_v2.get_brain", return_value=fake_cloud):
            done = body.emergency_stop()
        return done, body, door, log

    def test_the_install_step_is_not_interrupted_and_keeps_its_notification(self):
        done, body, door, log = self.stop_in_phase("installing", cloud=("auto", False))
        self.assertNotIn(("hub.cancel",), log, "the engine must not be asked to drop the first test question of the install")
        self.assertEqual(done, {"stopped": ["cloud"], "released": False, "busy": True}, "the cloud brain is still halted; the install is named nowhere")
        self.assertEqual(body.jobs(), ["ownbrain"], "the install is still a job")
        self.assertTrue(body.status()["holding"], "its notification stays")
        self.assertEqual(door.calls("door.release"), [])

    def test_the_busy_key_is_there_only_during_the_install(self):
        for phase in ("idle", "downloading", "paused", "failed", "ready"):
            with self.subTest(phase=phase):
                done, body, door, log = self.stop_in_phase(phase)
                self.assertNotIn("busy", done)
                self.assertIn(("hub.cancel",), log, "every other phase asks the engine as before")
                self.assertEqual(body.jobs(), [])
                self.assertEqual(len(door.calls("door.release")), 1)

    def test_a_download_that_ends_at_this_very_moment_is_installing_not_stopped(self):
        """The phase is read AFTER the halt: the halt of a download that has just finished returns False and the brain is installing by then."""
        done, body, _door, log = self.stop_in_phase("downloading", then="installing")
        self.assertNotIn(("hub.cancel",), log)
        self.assertEqual(done, {"stopped": [], "released": False, "busy": True})
        self.assertEqual(body.jobs(), ["ownbrain"])
        self.assertLess(log.index(("own.halt",)), [i for i, entry in enumerate(log) if entry[0] == "own.status"][-1], "the halt came first")

    def test_a_download_that_the_halt_stopped_is_released_as_always(self):
        done, body, _door, log = self.stop_in_phase("downloading", halts=True, then="paused")
        self.assertEqual(done, {"stopped": ["download", "engine"], "released": True})
        self.assertEqual(body.jobs(), [])

    def test_a_brain_that_cannot_say_its_phase_never_blocks_the_stop(self):
        class Silent(PhasedOwn):
            def status(self):
                raise RuntimeError("boom")

        log = []
        hub = FakeHub(log, cancelled=1, own=Silent(log, "installing"))
        body = B.Body(hub, doors=FakeDoors(FakeDoor(log)), monotonic=Clock())
        body.job("ownbrain", "t", "x", 1)
        with mock.patch("brain_v2.get_brain", return_value=None):
            done = body.emergency_stop()
        self.assertEqual(done, {"stopped": ["engine"], "released": True})
        for odd in (None, {}, {"phase": None}, {"phase": 7}, [], "installing"):            # a status that is not a plain answer counts as 'not installing'
            with self.subTest(status=odd):
                self.assertFalse(B._installing(type("O", (), {"status": lambda self, odd=odd: odd})()))
        self.assertFalse(B._installing(None))
        self.assertTrue(B._installing(PhasedOwn([], "installing")))


# ============================================================================ the module API
class ModuleApiTests(unittest.TestCase):
    def test_get_body_is_one_per_hub_and_none_for_what_is_not_a_hub(self):
        for notahub in (None, object(), "x", 5):
            self.assertIsNone(B.get_body(notahub))
        hub = FakeHub()
        first = B.get_body(hub, doors=FakeDoors(FakeDoor()))
        self.assertIsInstance(first, B.Body)
        self.assertIs(B.get_body(hub), first)
        self.assertIs(B.peek_body(hub), first)
        self.assertIsNone(B.peek_body(FakeHub()))
        self.assertIsNone(B.peek_body(None))

    def test_a_new_body_calls_nothing(self):
        log = []
        hub = FakeHub(log)
        B.get_body(hub, doors=FakeDoors(FakeDoor(log)))
        self.assertEqual(log, [])

    def test_emergency_stop_all_reaches_every_hub_and_survives_a_bad_one(self):
        log = []
        hub_a, hub_b, hub_c = FakeHub(log, cancelled=1), FakeHub(log, cancelled=0), FakeHub(log)
        door = FakeDoor(log)
        B.get_body(hub_a, doors=FakeDoors(door)).job("ownbrain", "t", "x", 1)
        B.get_body(hub_b, doors=FakeDoors(door))
        bad = B.get_body(hub_c, doors=FakeDoors(door))
        bad.emergency_stop = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch.object(service, "live_hubs", return_value=[hub_a, object(), hub_b, hub_c]), mock.patch("brain_v2.get_brain", return_value=None):
            done = B.emergency_stop_all()
        self.assertEqual(done, {"hubs": 3, "stopped": ["engine"], "released": True}, "three hubs were asked (the one that failed too); the object that is no hub was not")
        bad.emergency_stop.assert_called_once_with()

    def test_emergency_stop_all_says_busy_only_while_an_install_runs(self):
        log = []
        installing = FakeHub(log, cancelled=1, own=PhasedOwn(log, "installing"))
        idle = FakeHub(log, cancelled=1, own=PhasedOwn(log, "idle"))
        door = FakeDoor(log)
        for hub in (installing, idle):
            B.get_body(hub, doors=FakeDoors(door)).job("ownbrain", "t", "x", 1)
        with mock.patch.object(service, "live_hubs", return_value=[idle]), mock.patch("brain_v2.get_brain", return_value=None):
            self.assertEqual(B.emergency_stop_all(), {"hubs": 1, "stopped": ["engine"], "released": True}, "no busy key when nothing is busy")
        with mock.patch.object(service, "live_hubs", return_value=[installing]), mock.patch("brain_v2.get_brain", return_value=None):
            self.assertEqual(B.emergency_stop_all(), {"hubs": 1, "stopped": [], "released": False, "busy": True})
        B.get_body(idle, doors=FakeDoors(door)).job("ownbrain", "t", "x", 1)
        with mock.patch.object(service, "live_hubs", return_value=[idle, installing]), mock.patch("brain_v2.get_brain", return_value=None):
            self.assertEqual(B.emergency_stop_all(), {"hubs": 2, "stopped": ["engine"], "released": True, "busy": True},
                             "one hub is still installing: the whole answer says so, and what the other hub stopped is still told")

    def test_emergency_stop_all_without_hubs_says_so(self):
        with mock.patch.object(service, "live_hubs", return_value=[]):
            self.assertEqual(B.emergency_stop_all(), {"hubs": 0, "stopped": [], "released": False})
        with mock.patch.object(service, "live_hubs", side_effect=RuntimeError("boom")):
            self.assertEqual(B.emergency_stop_all(), {"hubs": 0, "stopped": [], "released": False})

    def test_live_hubs_is_a_copy_and_never_raises(self):
        hubs = service.live_hubs()
        self.assertIsInstance(hubs, list)
        hubs.append("junk")
        self.assertNotIn("junk", service.live_hubs())
        with mock.patch.object(service, "_HUBS_LOCK", None):
            self.assertEqual(service.live_hubs(), [])

    def test_the_notification_button_gets_plain_json_and_never_an_exception(self):
        with mock.patch.object(service, "live_hubs", return_value=[]):
            result = json.loads(platform_boot.emergency_stop())
        self.assertEqual(result, {"ok": True, "hubs": 0, "stopped": [], "released": False})
        with mock.patch("brain_hub.body.emergency_stop_all", side_effect=RuntimeError("boom")):
            result = json.loads(platform_boot.emergency_stop())
        self.assertEqual(result, {"ok": False, "hubs": 0, "stopped": [], "released": False})

    def test_the_notification_button_says_no_while_the_install_runs_so_the_notification_stays(self):
        log = []
        hub = FakeHub(log, cancelled=1, own=PhasedOwn(log, "installing"))
        B.get_body(hub, doors=FakeDoors(FakeDoor(log))).job("ownbrain", "t", "x", 1)
        with mock.patch.object(service, "live_hubs", return_value=[hub]), mock.patch("brain_v2.get_brain", return_value=None):
            result = json.loads(platform_boot.emergency_stop())
        self.assertEqual(result, {"ok": False, "hubs": 1, "stopped": [], "released": False},
                         "ok is False: Java keeps the notification and says «ایست انجام نشد»; the keys are the same as ever")
        self.assertNotIn(("hub.cancel",), log)

    def test_the_notification_button_reports_what_was_stopped(self):
        log = []
        hub = FakeHub(log, cancelled=1, own=FakeOwn(log))
        B.get_body(hub, doors=FakeDoors(FakeDoor(log))).job("ownbrain", "t", "x", 1)
        with mock.patch.object(service, "live_hubs", return_value=[hub]), mock.patch("brain_v2.get_brain", return_value=None):
            result = json.loads(platform_boot.emergency_stop())
        self.assertEqual(result, {"ok": True, "hubs": 1, "stopped": ["download", "engine"], "released": True})


# ============================================================================ the stop word that does not wait for the lock
class BypassGuardTests(unittest.TestCase):
    """`hub_hooks.emergency_while_busy` is taken ONLY for a short stop word while another turn holds the brain's lock. (The real stops it starts are
    tested in the chat tests; here `stop_while_busy` is a stand-in that records that it was asked.)"""

    class Stub:
        def __init__(self):
            self._lock = threading.Lock()
            self.errors = []

        def _log_error(self, exc, text):
            self.errors.append(exc)

    def test_the_stop_word_is_taken_only_while_another_turn_holds_the_lock(self):
        brain = self.Stub()
        with mock.patch.object(hub_body, "stop_while_busy", return_value=("brain_halt", "stopped")) as stop:
            self.assertIsNone(hub_hooks.emergency_while_busy(brain, "ایست"), "nobody is busy: the normal path answers")
            self.assertTrue(brain._lock.acquire(blocking=False), "and the check did not keep the lock")
            try:
                self.assertEqual(hub_hooks.emergency_while_busy(brain, "ایست"), ("brain_halt", "stopped"))
                self.assertEqual(stop.call_count, 1)
                for text in ("سلام", "ایست بازرسی یعنی چی", "ایست" + " " * 100, "ی" * 500, "", None, 5, b"x"):
                    with self.subTest(text=text):
                        self.assertIsNone(hub_hooks.emergency_while_busy(brain, text))
                self.assertEqual(stop.call_count, 1, "nothing but the stop word reaches the stop")
            finally:
                brain._lock.release()
        self.assertEqual(brain.errors, [])

    def test_the_length_limit_is_what_the_comment_says(self):
        self.assertEqual(hub_hooks.MAX_EMERGENCY_CHARS, 60)

    def test_a_failing_stop_is_logged_and_the_turn_takes_the_normal_path(self):
        brain = self.Stub()
        brain._lock.acquire()
        try:
            with mock.patch.object(hub_body, "stop_while_busy", side_effect=RuntimeError("boom")):
                self.assertIsNone(hub_hooks.emergency_while_busy(brain, "ایست"))
        finally:
            brain._lock.release()
        self.assertEqual([str(e) for e in brain.errors], ["boom"])


class AfterEmergencyTests(unittest.TestCase):
    """`hub_body.after_emergency`: the body's own stop that the chat's «ایست» adds after the own brain's line."""

    class Stub:
        def __init__(self):
            self.errors = []

        def _log_error(self, exc, text):
            self.errors.append(exc)

    def setup_body(self, cancelled=1, hold=True):
        log = []
        door = FakeDoor(log)
        hub = FakeHub(log, cancelled=cancelled)
        body = B.get_body(hub, doors=FakeDoors(door))
        if hold:
            body.job("ownbrain", "t", "x", 1)
        return hub, body, door, log

    def run_it(self, hub, brain, mine):
        with mock.patch.object(hub_body, "_hub", return_value=hub), mock.patch("brain_v2.get_brain", return_value=None):
            return hub_body.after_emergency(brain, mine)

    def test_the_stop_words_get_the_bodys_lines(self):
        hub, body, door, log = self.setup_body()
        result = self.run_it(hub, self.Stub(), ("brain_halt", "R"))
        self.assertEqual(result, ("brain_halt", "R\n\n" + hub_body.HB.emergency_extra(["engine"], True)))
        self.assertIn(("hub.cancel",), log)
        self.assertEqual(len(door.calls("door.release")), 1)

    def test_nothing_to_stop_leaves_the_reply_as_it_was(self):
        hub, body, door, log = self.setup_body(cancelled=0, hold=False)
        self.assertEqual(self.run_it(hub, self.Stub(), ("brain_halt", "R")), ("brain_halt", "R"))

    def test_any_other_reply_is_returned_unchanged_and_stops_nothing(self):
        hub, body, door, log = self.setup_body()
        for sub in ("brain_resume", "brain_status", "", None):
            with self.subTest(sub=sub):
                self.assertEqual(self.run_it(hub, self.Stub(), (sub, "R")), (sub, "R"))
        self.assertEqual(log.count(("hub.cancel",)), 0)
        self.assertEqual(door.calls("door.release"), [])

    def test_no_hub_means_no_change(self):
        self.assertEqual(self.run_it(None, self.Stub(), ("brain_halt", "R")), ("brain_halt", "R"))

    def test_a_failing_stop_is_logged_and_the_reply_stays(self):
        hub, body, door, log = self.setup_body()
        brain = self.Stub()
        body.emergency_stop = mock.Mock(side_effect=RuntimeError("boom"))
        self.assertEqual(self.run_it(hub, brain, ("brain_halt", "R")), ("brain_halt", "R"))
        self.assertEqual([str(e) for e in brain.errors], ["boom"])


class ScrubPlanTests(unittest.TestCase):
    """`hub_body._plan_scrub`: the promise to mask a shown code is made only when the plan is on record."""

    class Memory:
        def __init__(self, fails=False):
            self.fails, self.states = fails, {}

        def set_state(self, key, value):
            if self.fails:
                raise RuntimeError("disk full")
            self.states[key] = value

    def brain(self, fails=False):
        return type("Brain", (), {"memory": self.Memory(fails), "_clock": staticmethod(lambda: 1234.0)})()

    def test_a_stored_plan_is_true_holds_a_time_only_and_starts_the_timers(self):
        brain = self.brain()
        with mock.patch.object(hub_body, "SCRUB_DELAYS", (3600.0, 7200.0)):
            before = len(hub_body.pending_timers())
            try:
                self.assertTrue(hub_body._plan_scrub(brain))
                started = hub_body.pending_timers()[before:]
                self.assertEqual(len(started), 2)
            finally:
                for timer in hub_body.pending_timers()[before:]:
                    timer.cancel()
        self.assertEqual(brain.memory.states, {hub_body.SCRUB_KEY: {"ts": 1234.0}})

    def test_a_cancelled_timer_is_not_pending_any_more(self):
        # Prompt 959 (stage B): a cancelled timer never runs its job, and the job is what removed it from the list, so it used to stay "pending" for the
        # rest of the process: a later test that waits for "no pending timers" (the chat tests) then timed out when the two modules ran in this order
        brain = self.brain()
        with mock.patch.object(hub_body, "SCRUB_DELAYS", (3600.0, 7200.0)):
            before = len(hub_body.pending_timers())
            self.assertTrue(hub_body._plan_scrub(brain))
            started = hub_body.pending_timers()[before:]
            self.assertEqual(len(started), 2)
            for timer in started:
                timer.cancel()
        self.assertEqual(len(hub_body.pending_timers()), before)

    def test_a_timer_that_is_still_waiting_stays_pending(self):
        brain = self.brain()
        with mock.patch.object(hub_body, "SCRUB_DELAYS", (3600.0,)):
            before = len(hub_body.pending_timers())
            try:
                self.assertTrue(hub_body._plan_scrub(brain))
                self.assertEqual(len(hub_body.pending_timers()), before + 1)
                self.assertEqual(len(hub_body.pending_timers()), before + 1)       # asking twice changes nothing
            finally:
                for timer in hub_body.pending_timers()[before:]:
                    timer.cancel()
        self.assertEqual(len(hub_body.pending_timers()), before)

    def test_a_plan_that_cannot_be_stored_is_false_and_starts_nothing(self):
        before = len(hub_body.pending_timers())
        self.assertFalse(hub_body._plan_scrub(self.brain(fails=True)))
        self.assertEqual(len(hub_body.pending_timers()), before)


if __name__ == "__main__":
    unittest.main()
