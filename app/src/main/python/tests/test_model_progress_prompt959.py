"""
Prompt 959 (stage B3) - `ModelManager.verify` / `prepare` tell a caller how far the pipeline is.

The own brain's install step (verify -> compatibility -> load -> the first real answer) takes minutes on a phone; to show a percent the model manager
reports, through an optional `progress(stage, fraction, done, total)`:

* when each stage BEGINS (`fraction` 0.0 for the file check, None for the stages that cannot be measured);
* while the file is checked, how many bytes are read (`fraction` = read / size of the card), at most every `_PROGRESS_EVERY` seconds;
* and never anything else: a progress function that raises cannot break the pipeline, no function means the old behaviour exactly.

The n-gram engine is real, the file is the small test model: this proves the reporting, not how long a real 2.6 GB check or load takes.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub.builtin_tools import ToolsMixin
from model_runtime import manager as M
from tests.test_model_runtime_manager_prompt957 import MID, MODEL, ManagerCase, card_dict, write


class Base(ManagerCase):
    def downloaded(self):
        manager = self.manager()
        self.assertTrue(manager.register(card_dict()).ok)
        self.assertTrue(manager.download(MID, approved=True).ok)
        return manager


class TellTests(unittest.TestCase):
    def test_no_function_is_nothing(self):
        self.assertIsNone(M._tell(None, "verify", 0.5, 1, 2))

    def test_the_function_gets_stage_fraction_and_whole_bytes(self):
        seen = []
        M._tell(lambda *args: seen.append(args), "verify", 0.5, 1.9, 3)
        M._tell(lambda *args: seen.append(args), "load")
        self.assertEqual(seen, [("verify", 0.5, 1, 3), ("load", None, 0, 0)])

    def test_a_function_that_raises_is_swallowed(self):
        for error in (RuntimeError("x"), ValueError("y"), ZeroDivisionError(), OSError("z")):
            def broken(*_args, _e=error):
                raise _e

            M._tell(broken, "verify", 0.1, 1, 2)

    def test_values_that_cannot_be_counted_do_not_escape(self):
        M._tell(lambda *_a: None, "verify", 0.5, "x", None)                 # int("x") fails inside: swallowed like any other error


class VerifyProgressTests(Base):
    def read_calls(self, manager, every=0.0, chunk=100):
        calls = []
        with mock.patch.object(M, "_COPY_CHUNK", chunk), mock.patch.object(M, "_PROGRESS_EVERY", every):
            status = manager.verify(MID, lambda *args: calls.append(args))
        return status, calls

    def test_the_bytes_read_are_reported_as_the_file_is_read(self):
        manager = self.downloaded()
        status, calls = self.read_calls(manager)
        self.assertEqual((status.ok, status.state), (True, "verified"))
        self.assertGreaterEqual(len(calls), 3, "the test model is several chunks long")
        self.assertTrue(all(call[0] == "verify" for call in calls))
        done = [call[2] for call in calls]
        self.assertEqual(done, sorted(set(done)), "strictly more bytes every time")
        self.assertEqual(done[-1], len(MODEL))
        self.assertTrue(all(call[3] == len(MODEL) for call in calls), "the total is the card's size")
        fractions = [call[1] for call in calls]
        self.assertEqual(fractions, sorted(fractions))
        self.assertTrue(all(0.0 < f <= 1.0 for f in fractions))
        self.assertEqual(fractions[-1], 1.0)

    def test_the_report_is_limited_by_time_not_by_chunks(self):
        manager = self.downloaded()
        _status, calls = self.read_calls(manager, every=3600.0)
        self.assertEqual(calls, [], "inside the window nothing is reported (the stage's start is `prepare`'s job)")

    def test_no_function_is_the_old_behaviour(self):
        manager = self.downloaded()
        with mock.patch.object(M, "_COPY_CHUNK", 100), mock.patch.object(M, "_PROGRESS_EVERY", 0.0):
            status = manager.verify(MID)
        self.assertEqual((status.ok, status.state), (True, "verified"))

    def test_a_progress_function_that_raises_cannot_break_the_check(self):
        manager = self.downloaded()
        calls = []

        def broken(*args):
            calls.append(args)
            raise RuntimeError("the screen is gone")

        with mock.patch.object(M, "_COPY_CHUNK", 100), mock.patch.object(M, "_PROGRESS_EVERY", 0.0):
            status = manager.verify(MID, broken)
        self.assertEqual((status.ok, status.state), (True, "verified"))
        self.assertGreaterEqual(len(calls), 3, "it was called again after each failure")

    def test_a_corrupt_file_still_fails_and_the_progress_does_not_hide_it(self):
        manager = self.downloaded()
        write(manager.model_path(MID), MODEL[:-1] + b"X")
        status, calls = self.read_calls(manager)
        self.assertEqual((status.code, status.state), ("hash_mismatch", "failed"))
        self.assertEqual(calls[-1][1], 1.0, "the whole file was read before the hash was compared")


class PrepareProgressTests(Base):
    def prepare_calls(self, manager, progress=None):
        calls = []
        report = manager.prepare(MID, progress or (lambda *args: calls.append(args)))
        return report, calls

    def test_every_stage_is_announced_before_it_runs_and_in_order(self):
        manager = self.downloaded()
        report, calls = self.prepare_calls(manager)
        self.assertTrue(report.ok, report)
        self.assertEqual(calls, [("verify", 0.0, 0, 0), ("compatibility", None, 0, 0), ("load", None, 0, 0), ("smoke", None, 0, 0)])
        self.assertEqual([s.stage for s in report.stages], ["verify", "compatibility", "load", "smoke"], "the announced names are the stages' names")

    def test_the_bytes_of_the_file_check_come_between_its_start_and_the_next_stage(self):
        manager = self.downloaded()
        with mock.patch.object(M, "_COPY_CHUNK", 100), mock.patch.object(M, "_PROGRESS_EVERY", 0.0):
            report, calls = self.prepare_calls(manager)
        self.assertTrue(report.ok)
        names = [call[0] for call in calls]
        self.assertEqual(names[0], "verify")
        self.assertEqual(calls[0][1:], (0.0, 0, 0))
        last_verify = max(i for i, name in enumerate(names) if name == "verify")
        self.assertEqual(names[last_verify + 1:], ["compatibility", "load", "smoke"], "nothing of the file check after the next stage began")
        self.assertGreaterEqual(last_verify, 3)

    def test_a_failed_stage_stops_the_announcements(self):
        manager = self.downloaded()
        write(manager.model_path(MID), MODEL[:-1] + b"X")
        report, calls = self.prepare_calls(manager)
        self.assertFalse(report.ok)
        self.assertEqual([call[0] for call in calls], ["verify"])
        self.assertEqual([(s.stage, s.code) for s in report.stages], [("verify", "hash_mismatch")])

    def test_a_progress_function_that_raises_cannot_break_the_pipeline(self):
        manager = self.downloaded()

        def broken(*_args):
            raise RuntimeError("the screen is gone")

        report = manager.prepare(MID, broken)
        self.assertTrue(report.ok, report)
        self.assertTrue(manager.is_usable(MID))

    def test_no_function_is_the_old_behaviour(self):
        manager = self.downloaded()
        report = manager.prepare(MID)
        self.assertTrue(report.ok)
        self.assertTrue(manager.is_usable(MID))

    def test_an_unknown_model_is_refused_and_does_not_raise(self):
        manager = self.manager()
        calls = []
        report = manager.prepare("nope", lambda *args: calls.append(args))
        self.assertFalse(report.ok)
        self.assertEqual(calls, [("verify", 0.0, 0, 0)], "only the first stage was announced, and it was refused")


class HubPassThroughTests(unittest.TestCase):
    def hub(self, manager):
        hub = object.__new__(ToolsMixin)
        hub._model_manager = lambda: manager
        return hub

    def test_the_hub_hands_the_function_to_the_manager(self):
        seen = []
        manager = SimpleNamespace(prepare=lambda model_id, progress=None: seen.append((model_id, progress)) or "report")
        marker = object()
        self.assertEqual(self.hub(manager).prepare_model("m", marker), "report")
        self.assertEqual(seen, [("m", marker)])

    def test_without_a_function_the_hub_asks_as_before(self):
        seen = []
        manager = SimpleNamespace(prepare=lambda model_id, progress=None: seen.append((model_id, progress)) or "report")
        self.assertEqual(self.hub(manager).prepare_model("m"), "report")
        self.assertEqual(seen, [("m", None)])


if __name__ == "__main__":
    unittest.main()
