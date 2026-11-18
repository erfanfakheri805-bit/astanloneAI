"""
Prompt 959 (stage B, «مغز خودکار») - the TWO locks of `model_runtime.ModelManager`.

A model answer (or the first test of a freshly installed brain) can take minutes on a phone. While it runs the chat must still be able to read the
registry (status, list, "is it usable"), the emergency stop must reach the engine, and nothing may change the model under the answer. So:

* `_lock` is short (registry and state only): `status`, `list_models`, `is_usable`, `model_path` use nothing else;
* `_op_lock` is long (verify, load, test, answer): every change of a model takes it, so two long things never overlap;
* `cancel_all` takes NO lock; `unload(wait=False)` never waits.

The engine here is a fake that blocks inside `generate` until the test lets it go; nothing says how a real engine behaves.
"""
import os
import random
import sys
import threading
import time
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_runtime.runtimes import InferenceRuntime, LoadedModel, RuntimeAvailability, SmokeReport
from tests.test_model_runtime_manager_prompt957 import MID, ManagerCase, card_dict

WAIT = 15


class GatedRuntime(InferenceRuntime):
    """An engine whose answer can be held: `generate` waits for `release` while `block` is on, and counts who is inside."""

    name = "gated"
    formats = ("ngram-json",)
    supports_chat = False
    description_fa = "موتور آزمایشیِ قفل‌دار"
    description_en = "A gated test engine"

    def __init__(self):
        self.block = False
        self.entered, self.release = threading.Event(), threading.Event()
        self.mutex = threading.Lock()
        self.inside = self.max_inside = 0
        self.cancels = self.loads = self.smokes = self.unloads = 0

    def availability(self):
        return RuntimeAvailability(True, "ok", "آماده", "ready")

    def load(self, path, card):
        with self.mutex:
            self.loads += 1
        return LoadedModel(card.model_id, self.name, object(), path)

    def smoke_test(self, loaded):
        with self.mutex:
            self.smokes += 1
        return SmokeReport(True, "ok", "x")

    def generate(self, loaded, prompt, *, max_tokens, seed):
        with self.mutex:
            self.inside += 1
            self.max_inside = max(self.max_inside, self.inside)
        self.entered.set()
        try:
            if self.block:
                self.release.wait(WAIT)
            return "پاسخ"
        finally:
            with self.mutex:
                self.inside -= 1

    def cancel(self):
        with self.mutex:
            self.cancels += 1
        self.release.set()

    def unload(self, loaded):
        with self.mutex:
            self.unloads += 1
        loaded.handle = None


class LockCase(ManagerCase):
    def setUp(self):
        super().setUp()
        self.rt = GatedRuntime()
        self.manager_ = self.manager(runtimes=[self.rt])
        self.assertTrue(self.manager_.register(card_dict(runtime_hint="")).ok)
        self.assertTrue(self.manager_.download(MID, approved=True).ok)
        self.assertTrue(self.manager_.prepare(MID).ok)
        self.threads = []
        self.addCleanup(self.finish)

    def finish(self):
        self.rt.release.set()
        for thread in self.threads:
            thread.join(WAIT)

    def start(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def answering(self):
        """Start an answer that the engine holds; returns the dict its result will arrive in."""
        self.rt.block = True
        self.rt.entered.clear()
        self.rt.release.clear()
        box = {}
        self.start(lambda: box.update(result=self.manager_.generate(MID, "سلام", max_tokens=8)))
        self.assertTrue(self.rt.entered.wait(WAIT), "the answer never reached the engine")
        return box

    def let_go(self, box=None):
        self.rt.release.set()
        if box is not None:
            for _ in range(WAIT * 100):
                if "result" in box:
                    break
                time.sleep(0.01)
        return box


class ReadersTests(LockCase):
    def test_the_registry_can_be_read_while_an_answer_is_in_the_engine(self):
        box = self.answering()
        began = time.monotonic()
        for _ in range(100):
            self.assertTrue(self.manager_.is_usable(MID))
            self.assertEqual(self.manager_.status(MID).state, "usable")
            self.assertEqual([s.model_id for s in self.manager_.list_models()], [MID])
            self.assertTrue(self.manager_.model_path(MID).endswith("model.bin"))
        self.assertLess(time.monotonic() - began, 2.0, "readers waited for the answer")
        self.assertNotIn("result", box, "and the answer is still running")
        self.let_go(box)
        self.assertTrue(box["result"].ok)
        self.assertEqual(box["result"].text, "پاسخ")

    def test_the_emergency_stop_reaches_the_engine_without_waiting_for_the_answer(self):
        box = self.answering()
        began = time.monotonic()
        self.assertEqual(self.manager_.cancel_all(), 1)
        self.assertLess(time.monotonic() - began, 1.0)
        self.assertEqual(self.rt.cancels, 1)
        self.let_go(box)
        self.assertTrue(box["result"].ok or box["result"].code, "the held answer ended once the engine was told to stop")

    def test_a_stop_with_nothing_loaded_asks_nobody(self):
        self.assertTrue(self.manager_.unload(MID, wait=True))
        self.assertEqual(self.manager_.cancel_all(), 0)
        self.assertEqual(self.rt.cancels, 0)


class ChangesWaitTests(LockCase):
    def test_unload_without_waiting_leaves_an_answering_model_alone(self):
        box = self.answering()
        began = time.monotonic()
        self.assertFalse(self.manager_.unload(MID))
        self.assertLess(time.monotonic() - began, 1.0, "unload(wait=False) must never wait")
        self.assertEqual(self.rt.unloads, 0)
        self.let_go(box)
        self.assertTrue(box["result"].ok)
        self.assertTrue(self.manager_.unload(MID), "once the answer is over the memory is given back")
        self.assertEqual(self.rt.unloads, 1)
        self.assertTrue(self.manager_.is_usable(MID), "unloading does not take the model away")

    def test_unload_that_waits_waits_for_the_answer_and_then_frees(self):
        box = self.answering()
        done = {}
        thread = self.start(lambda: done.update(freed=self.manager_.unload(MID, wait=True)))
        time.sleep(0.3)
        self.assertTrue(thread.is_alive(), "it must wait while the answer runs")
        self.assertEqual(self.rt.unloads, 0)
        self.let_go(box)
        thread.join(WAIT)
        self.assertEqual(done, {"freed": True})
        self.assertEqual(self.rt.unloads, 1)

    def test_a_removal_waits_for_the_answer_instead_of_pulling_the_file_from_under_it(self):
        box = self.answering()
        path = self.manager_.model_path(MID)
        self.assertTrue(os.path.isfile(path))
        done = {}
        thread = self.start(lambda: done.update(status=self.manager_.remove(MID)))
        time.sleep(0.3)
        self.assertTrue(thread.is_alive(), "removal must wait while the answer runs")
        self.assertTrue(os.path.isfile(path), "the file the engine is using is untouched")
        self.assertEqual(self.manager_.status(MID).state, "usable", "and the registry still tells the truth meanwhile")
        self.let_go(box)
        thread.join(WAIT)
        self.assertTrue(done["status"].ok, done)
        self.assertTrue(box["result"].ok, "the answer that was running finished normally")
        self.assertEqual(self.manager_.status(MID).code, "unknown_model")

    def test_a_second_answer_waits_its_turn_and_both_complete(self):
        box = self.answering()
        second = {}
        self.rt.entered.clear()
        thread = self.start(lambda: second.update(result=self.manager_.generate(MID, "دومی", max_tokens=8)))
        self.assertFalse(self.rt.entered.wait(0.4), "the second answer must not enter the engine while the first is inside")
        self.assertEqual(self.rt.max_inside, 1)
        self.rt.block = False
        self.let_go(box)
        thread.join(WAIT)
        self.assertTrue(box["result"].ok and second["result"].ok)
        self.assertEqual(self.rt.max_inside, 1, "never two answers in the engine at once")

    def test_after_an_unload_the_next_answer_loads_again_and_tests_again_without_deadlock(self):
        self.assertEqual((self.rt.loads, self.rt.smokes), (1, 1))
        self.assertTrue(self.manager_.unload(MID))
        result = self.manager_.generate(MID, "سلام", max_tokens=8)
        self.assertTrue(result.ok, result)
        self.assertEqual((self.rt.loads, self.rt.smokes), (2, 2), "loaded and re-tested once for the new process state")
        self.assertTrue(self.manager_.generate(MID, "سلام", max_tokens=8).ok)
        self.assertEqual((self.rt.loads, self.rt.smokes), (2, 2), "and not again for the second answer")


class StressTests(LockCase):
    def test_many_threads_doing_everything_at_once_never_deadlock_or_overlap(self):
        stop = time.monotonic() + 3.0
        errors, answers = [], []
        rng = random.Random(959)

        def reader():
            while time.monotonic() < stop:
                try:
                    self.manager_.status(MID)
                    self.manager_.list_models()
                    self.manager_.is_usable(MID)
                    self.manager_.model_path(MID)
                except Exception as exc:            # noqa: BLE001 - any exception is a failure of the test
                    errors.append(repr(exc))

        def answerer():
            while time.monotonic() < stop:
                try:
                    answers.append(self.manager_.generate(MID, "سلام", max_tokens=8).ok)
                except Exception as exc:            # noqa: BLE001
                    errors.append(repr(exc))

        def meddler():
            while time.monotonic() < stop:
                try:
                    self.manager_.unload(MID, wait=rng.random() < 0.3)
                    self.manager_.cancel_all()
                    self.manager_.reopen(MID)         # refused (the model is usable), but must be safe
                    time.sleep(0.002)
                except Exception as exc:            # noqa: BLE001
                    errors.append(repr(exc))

        workers = [self.start(reader) for _ in range(3)] + [self.start(answerer) for _ in range(3)] + [self.start(meddler) for _ in range(2)]
        for worker in workers:
            worker.join(WAIT)
        self.assertFalse([w for w in workers if w.is_alive()], "a thread is stuck: a deadlock")
        self.assertEqual(errors, [])
        self.assertEqual(self.rt.max_inside, 1, "two answers were in the engine at the same time")
        self.assertGreater(len(answers), 10)
        self.assertTrue(all(answers), "an answer failed only because another thread unloaded or stopped around it")
        self.assertTrue(self.manager_.generate(MID, "سلام", max_tokens=8).ok, "and the model is still usable afterwards")


if __name__ == "__main__":
    unittest.main()
