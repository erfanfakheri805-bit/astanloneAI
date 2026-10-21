"""Prompt 957 - model_runtime.ModelManager: the honest lifecycle (network MOCKED, the n-gram engine REAL)."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from collections import namedtuple
from types import SimpleNamespace
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_runtime import (LlamaCppRuntime, ModelManager, NgramRuntime, STATES, TRANSITIONS, default_downloader,
                           train_ngram_model, transition_allowed)
from model_runtime.runtimes import InferenceRuntime, LoadedModel, RuntimeAvailability, RuntimeGenerateError, SmokeReport
from net_tools import NETWORK, CallableGate, StaticGate

TEXTS = ["سلام دوست من. امروز هوا خیلی خوب است.", "من به مدرسه می‌روم و کتاب می‌خوانم.", "سلام، حال شما چطور است؟",
         "امروز هوا خوب است و من خوشحالم.", "کتاب خوب دوست خوب است."]
MODEL = train_ngram_model(TEXTS)
SHA = hashlib.sha256(MODEL).hexdigest()
URL = "https://models.example.org/fa-ngram.json"
MID = "fa-ngram"
REL = "files/fa-ngram/1.0/model.bin"
Usage = namedtuple("Usage", "total used free")
PLENTY = lambda _path: Usage(10 ** 12, 0, 10 ** 12)  # noqa: E731
GATE = StaticGate([NETWORK])
NO_LLAMA = lambda: LlamaCppRuntime(spec_finder=lambda name: None)  # noqa: E731 - deterministic: engine absent


def card_dict(**over):
    data = dict(model_id=MID, title="مدل آزمایشی", version="1.0", format="ngram-json", source_url=URL, sha256=SHA,
                size_bytes=len(MODEL), license="mit")
    data.update(over)
    return data


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


class FakeDownloader:
    """Stands in for net_tools.download_file: records the call and writes (or not) what the test wants."""

    def __init__(self, payload=MODEL, ok=True, code="ok", error=None, write_file=True, partial=False):
        self.payload, self.ok, self.code, self.error, self.write_file, self.partial = payload, ok, code, error, write_file, partial
        self.calls = []

    def __call__(self, url, dest_root, rel_dest, *, expected_sha256, max_bytes):
        self.calls.append(dict(url=url, dest_root=dest_root, rel_dest=rel_dest, expected_sha256=expected_sha256,
                               max_bytes=max_bytes))
        target = os.path.join(dest_root, rel_dest)
        if self.partial:
            write(target + ".partial", self.payload[:10])
        if self.error is not None:
            raise self.error
        if self.write_file:
            write(target, self.payload)
        return SimpleNamespace(ok=self.ok, code=self.code)


class ManagerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "models")
        self.events = []
        self.tick = [1000.0]

    def clock(self):
        self.tick[0] += 1.0
        return self.tick[0]

    def fresh_root(self):
        """A new empty models directory inside the same temporary directory (cleaned once, at the end)."""
        self._roots = getattr(self, "_roots", 0) + 1
        self.root = os.path.join(self._tmp.name, "models-%d" % self._roots)

    def manager(self, **kw):
        kw.setdefault("runtimes", [NgramRuntime(), NO_LLAMA()])
        kw.setdefault("downloader", FakeDownloader())
        kw.setdefault("gate", GATE)
        kw.setdefault("free_space_fn", PLENTY)
        kw.setdefault("clock", self.clock)
        kw.setdefault("audit", lambda kind, subject, detail: self.events.append((kind, subject, detail)))
        return ModelManager(self.root, **kw)

    def kinds(self):
        return [event[0] for event in self.events]

    def usable(self, **kw):
        manager = self.manager(**kw)
        self.assertTrue(manager.register(card_dict()).ok)
        self.assertTrue(manager.download(MID, approved=True).ok)
        report = manager.prepare(MID)
        self.assertTrue(report.ok, report)
        return manager

    def registry(self):
        return json.loads(read_bytes(os.path.join(self.root, "registry.json")).decode("utf-8"))


class TransitionTableTests(unittest.TestCase):
    def test_table_is_the_function_for_every_pair(self):
        for old in STATES:
            for new in STATES:
                self.assertEqual(transition_allowed(old, new), new in TRANSITIONS[old], (old, new))
        self.assertFalse(transition_allowed("nonsense", "usable"))
        self.assertFalse(transition_allowed("registered", "nonsense"))

    def test_usable_is_reachable_only_from_compatible_or_itself(self):
        into_usable = sorted(old for old in STATES if transition_allowed(old, "usable"))
        self.assertEqual(into_usable, ["compatible", "usable"])

    def test_no_shortcuts_past_a_stage(self):
        for old, new in (("registered", "verified"), ("registered", "compatible"), ("registered", "usable"),
                         ("downloaded", "compatible"), ("downloaded", "usable"), ("verified", "usable"),
                         ("failed", "verified"), ("failed", "compatible"), ("failed", "usable"),
                         ("downloading", "verified"), ("downloading", "usable")):
            self.assertFalse(transition_allowed(old, new), (old, new))

    def test_failed_can_only_restart_from_the_beginning(self):
        self.assertEqual(sorted(TRANSITIONS["failed"]), ["downloaded", "downloading", "registered"])

    def test_every_state_is_covered(self):
        self.assertEqual(set(TRANSITIONS), set(STATES))
        for targets in TRANSITIONS.values():
            self.assertTrue(targets <= set(STATES))


class MoveGuardTests(ManagerCase):
    def test_the_manager_itself_refuses_an_illegal_transition(self):
        manager = self.manager()
        manager.register(card_dict())
        with self.assertRaises(ValueError):
            manager._move(MID, "usable")
        for target in ("verified", "compatible"):  # not reachable from `registered`, and no smoke-test rule involved
            with self.assertRaises(ValueError):
                manager._move(MID, target)
        self.assertEqual(manager.status(MID).state, "registered")

    def test_usable_without_a_passing_smoke_test_is_refused(self):
        manager = self.manager()
        manager.register(card_dict())
        manager.download(MID, approved=True)
        manager.verify(MID)
        manager.check_compatibility(MID)
        self.assertEqual(manager.status(MID).state, "compatible")
        with self.assertRaises(ValueError):
            manager._move(MID, "usable")
        self.assertEqual(manager.status(MID).state, "compatible")


class RegistrationTests(ManagerCase):
    def test_register_creates_a_registered_unusable_entry_and_persists_it(self):
        manager = self.manager()
        status = manager.register(card_dict())
        self.assertEqual((status.ok, status.state, status.usable, status.file), (True, "registered", False, None))
        self.assertEqual(status.runtime, "ngram")
        self.assertEqual(self.registry()["models"][MID]["state"], "registered")
        again = self.manager()
        self.assertEqual(again.status(MID).state, "registered")
        self.assertEqual([s.model_id for s in again.list_models()], [MID])

    def test_nothing_exists_on_disk_before_the_first_write(self):
        self.manager()
        self.assertFalse(os.path.exists(self.root))

    def test_invalid_card_is_refused_and_not_stored(self):
        manager = self.manager()
        status = manager.register(card_dict(sha256="zz"))
        self.assertEqual((status.ok, status.code, status.state), (False, "invalid_card", "unregistered"))
        self.assertEqual(manager.list_models(), [])
        self.assertIn("register_refused", self.kinds())
        for junk in (None, [], "x", 5):
            self.assertFalse(manager.register(junk).ok)

    def test_registering_the_same_card_twice_is_idempotent(self):
        manager = self.manager()
        manager.register(card_dict())
        self.assertTrue(manager.register(card_dict()).ok)
        self.assertEqual(len(manager.list_models()), 1)

    def test_a_different_card_with_the_same_id_is_refused(self):
        manager = self.manager()
        manager.register(card_dict())
        status = manager.register(card_dict(sha256="b" * 64))
        self.assertEqual((status.ok, status.code), (False, "model_id_taken"))
        self.assertEqual(manager.status(MID).card["sha256"], SHA)

    def test_bad_arguments(self):
        manager = self.manager()
        self.assertEqual(manager.register(card_dict(), origin="root").code, "bad_arguments")
        self.assertEqual(manager.register(card_dict(), license_ack="yes").code, "bad_arguments")
        self.assertEqual(manager.list_models(), [])

    def test_unknown_model_everywhere(self):
        manager = self.manager()
        for call in (manager.status, manager.verify, manager.check_compatibility, manager.load, manager.smoke_test,
                     manager.remove, manager.acknowledge_license):
            status = call("nope-model")
            self.assertEqual((status.ok, status.code, status.usable), (False, "unknown_model", False), call)
        self.assertEqual(manager.download("nope-model", approved=True).code, "unknown_model")
        self.assertEqual(manager.prepare("nope-model").ok, False)
        self.assertFalse(manager.generate("nope-model", "سلام").ok)
        self.assertFalse(manager.is_usable("nope-model"))
        self.assertEqual(manager.model_path("nope-model"), "")

    def test_ids_that_look_like_paths_are_just_unknown(self):
        manager = self.manager()
        for bad in ("../x", "a/b", "..", "", "A" * 5):
            self.assertEqual(manager.remove(bad).code, "unknown_model", bad)

    def test_license_acknowledgement_rules(self):
        manager = self.manager()
        manager.register(card_dict(license="gemma"))
        self.assertTrue(manager.acknowledge_license(MID).ok)
        self.assertTrue(self.registry()["models"][MID]["license_ack"])
        manager.register(card_dict(model_id="mit-one", license="mit"))
        self.assertEqual(manager.acknowledge_license("mit-one").code, "illegal_state")
        manager.register(card_dict(model_id="nc-one", license="cc-by-nc-4.0"))
        self.assertEqual(manager.acknowledge_license("nc-one").code, "illegal_state")
        manager.register(card_dict(model_id="odd-one", license="my-own-terms"))
        self.assertEqual(manager.acknowledge_license("odd-one").code, "illegal_state")

    def test_registering_again_with_license_ack_records_it(self):
        manager = self.manager()
        manager.register(card_dict(license="llama-3"))
        self.assertFalse(self.registry()["models"][MID]["license_ack"])
        self.assertTrue(manager.register(card_dict(license="llama-3"), license_ack=True).ok)
        self.assertTrue(self.registry()["models"][MID]["license_ack"])

    def test_the_status_reports_the_licence_policy_and_the_acknowledgement(self):
        manager = self.manager()
        manager.register(card_dict(license="gemma"))
        before = manager.status(MID)
        self.assertEqual((before.license_policy, before.license_ack), ("needs_review", False))
        manager.acknowledge_license(MID)
        self.assertEqual(manager.status(MID).license_ack, True)
        for model_id, name, policy in (("mit-one", "mit", "permissive"), ("nc-one", "cc-by-nc-4.0", "restricted"),
                                       ("odd-one", "my-own-terms", "unknown")):
            manager.register(card_dict(model_id=model_id, license=name))
            status = manager.status(model_id)
            self.assertEqual((status.license_policy, status.license_ack), (policy, False))
            self.assertEqual(status.to_dict()["license_policy"], policy)
        unknown = manager.status("not-registered")
        self.assertEqual((unknown.license_policy, unknown.license_ack), ("", False))

    def test_remove_deletes_files_and_registry_entry(self):
        manager = self.usable()
        path = manager.model_path(MID)
        self.assertTrue(os.path.isfile(path))
        status = manager.remove(MID)
        self.assertTrue(status.ok)
        self.assertFalse(os.path.exists(os.path.dirname(path)))
        self.assertEqual(manager.status(MID).code, "unknown_model")
        self.assertNotIn(MID, self.registry()["models"])
        self.assertIn("removed", self.kinds())
        self.assertFalse(manager.generate(MID, "سلام").ok)


class DownloadGateTests(ManagerCase):
    def assertNoDownload(self, manager, downloader, code, **call):
        status = manager.download(MID, **call)
        self.assertEqual((status.ok, status.code, status.state), (False, code, "registered"), status)
        self.assertEqual(downloader.calls, [])
        self.assertFalse(os.path.exists(os.path.join(self.root, "files")))

    def test_without_explicit_approval_nothing_is_downloaded(self):
        for approved in (False, None, "yes", 1, "True", [True]):
            self.events.clear()
            fake = FakeDownloader()
            manager = self.manager(downloader=fake)
            manager.register(card_dict())
            self.assertNoDownload(manager, fake, "approval_required", approved=approved)
            self.assertIn("download_refused", self.kinds())

    def test_without_the_network_permission_nothing_is_downloaded(self):
        for gate in (None, StaticGate([]), StaticGate(["microphone"]), CallableGate(lambda name: "yes"),
                     CallableGate(lambda name: 1 / 0)):
            fake = FakeDownloader()
            manager = self.manager(downloader=fake, gate=gate)
            manager.register(card_dict())
            self.assertNoDownload(manager, fake, "permission_denied", approved=True)

    def test_a_gate_that_says_yes_only_for_the_network_name_is_honoured(self):
        seen = []
        gate = CallableGate(lambda name: seen.append(name) or name == NETWORK)
        manager = self.manager(gate=gate)
        manager.register(card_dict())
        self.assertTrue(manager.download(MID, approved=True).ok)
        self.assertEqual(seen, [NETWORK])

    def test_a_model_without_an_address_asks_for_a_local_file(self):
        fake = FakeDownloader()
        manager = self.manager(downloader=fake)
        manager.register(card_dict(source_url="local-import"))
        self.assertNoDownload(manager, fake, "needs_local_file", approved=True)

    def test_licence_gates(self):
        fake = FakeDownloader()
        manager = self.manager(downloader=fake)
        manager.register(card_dict(license="gemma"))
        self.assertNoDownload(manager, fake, "license_needs_ack", approved=True)
        manager.acknowledge_license(MID)
        self.assertTrue(manager.download(MID, approved=True).ok)
        for model_id, lic, code in (("nc-one", "cc-by-nc-4.0", "license_restricted"), ("prop-one", "proprietary", "license_restricted"),
                                    ("odd-one", "my-own-terms", "license_unknown")):
            fake = FakeDownloader()
            manager = self.manager(downloader=fake)
            manager.register(card_dict(model_id=model_id, license=lic), license_ack=True)  # an ack never rescues these
            status = manager.download(model_id, approved=True)
            self.assertEqual((status.ok, status.code, status.state), (False, code, "registered"))
            self.assertEqual(fake.calls, [])

    def test_free_space_is_checked_with_a_margin_before_downloading(self):
        need = len(MODEL) * 1.1 + 1024 * 1024
        for free, expected in ((int(need) - 1, "insufficient_space"), (int(need) + 1, "ok")):
            self.fresh_root()
            fake = FakeDownloader()
            manager = self.manager(downloader=fake, free_space_fn=lambda _p, free=free: Usage(0, 0, free))
            manager.register(card_dict(min_free_mb=1))
            status = manager.download(MID, approved=True)
            self.assertEqual(status.code, expected, (free, status))
            self.assertEqual(len(fake.calls), 0 if expected != "ok" else 1)

    def test_a_download_in_the_wrong_state_is_refused(self):
        manager = self.usable()
        status = manager.download(MID, approved=True)
        self.assertEqual((status.ok, status.code, status.state), (False, "illegal_state", "usable"))


class DownloadOutcomeTests(ManagerCase):
    def test_success_hands_the_downloader_exactly_what_it_must_verify(self):
        fake = FakeDownloader()
        manager = self.manager(downloader=fake)
        manager.register(card_dict())
        status = manager.download(MID, approved=True)
        self.assertEqual((status.ok, status.state, status.stage, status.usable), (True, "downloaded", "download", False))
        self.assertEqual(fake.calls, [dict(url=URL, dest_root=manager.root, rel_dest=REL, expected_sha256=SHA, max_bytes=len(MODEL))])
        self.assertEqual(status.file["rel"], REL)
        self.assertEqual(status.file["size"], len(MODEL))
        self.assertEqual(self.registry()["models"][MID]["state"], "downloaded")
        self.assertEqual([e[2]["to"] for e in self.events if e[0] == "transition"], ["downloading", "downloaded"])

    def test_downloaded_is_not_usable_and_cannot_generate(self):
        manager = self.manager()
        manager.register(card_dict())
        manager.download(MID, approved=True)
        result = manager.generate(MID, "سلام")
        self.assertEqual((result.ok, result.code, result.text), (False, "model_not_usable", ""))
        self.assertFalse(manager.is_usable(MID))

    def test_a_model_that_is_not_usable_is_refused_for_that_reason_even_when_no_engine_knows_its_format(self):
        manager = self.manager(runtimes=[NgramRuntime()])  # no engine for gguf at all
        manager.register(card_dict(model_id="gg-none", format="gguf", sha256="a" * 64, size_bytes=10,
                                   source_url="https://models.example.org/none.gguf"))
        result = manager.generate("gg-none", "سلام")
        self.assertEqual((result.ok, result.code, result.runtime, result.text), (False, "model_not_usable", "", ""))

    def test_a_failed_download_leaves_no_file_and_can_be_retried(self):
        fake = FakeDownloader(ok=False, code="hash_mismatch", partial=True)
        manager = self.manager(downloader=fake)
        manager.register(card_dict())
        status = manager.download(MID, approved=True)
        self.assertEqual((status.ok, status.code, status.state), (False, "download_failed", "failed"))
        self.assertEqual(status.reasons, ("hash_mismatch",))
        directory = os.path.join(self.root, "files", MID, "1.0")
        self.assertEqual(os.listdir(directory) if os.path.isdir(directory) else [], [])
        fake.ok, fake.code, fake.partial = True, "ok", False
        self.assertTrue(manager.download(MID, approved=True).ok)
        self.assertEqual(manager.status(MID).state, "downloaded")

    def test_a_downloader_that_raises_is_a_failed_download(self):
        manager = self.manager(downloader=FakeDownloader(error=RuntimeError("boom"), partial=True))
        manager.register(card_dict())
        status = manager.download(MID, approved=True)
        self.assertEqual((status.ok, status.state, status.code), (False, "failed", "download_failed"))
        self.assertEqual(os.listdir(os.path.join(self.root, "files", MID, "1.0")), [])

    def test_a_downloader_that_claims_success_without_a_correct_file_is_not_believed(self):
        for fake in (FakeDownloader(write_file=False), FakeDownloader(payload=MODEL + b"x"), FakeDownloader(payload=MODEL[:-1])):
            self.fresh_root()
            manager = self.manager(downloader=fake)
            manager.register(card_dict())
            status = manager.download(MID, approved=True)
            self.assertEqual((status.ok, status.state, status.code), (False, "failed", "size_mismatch"))
            self.assertFalse(os.path.exists(manager.model_path(MID)))

    def test_an_interrupted_download_is_recovered_after_a_restart(self):
        manager = self.manager(downloader=FakeDownloader(error=KeyboardInterrupt(), partial=True))
        manager.register(card_dict())
        with self.assertRaises(KeyboardInterrupt):
            manager.download(MID, approved=True)
        restarted = self.manager()
        self.assertEqual(restarted.status(MID).state, "downloading")
        self.assertFalse(restarted.is_usable(MID))
        report = restarted.recover()
        self.assertEqual(report["interrupted"], [MID])
        self.assertIn("%s/model.bin.partial" % MID, report["removed_files"])
        status = restarted.status(MID)
        self.assertEqual((status.state, status.reasons), ("registered", ("interrupted",)))
        self.assertEqual(os.listdir(os.path.join(self.root, "files", MID, "1.0")), [])
        self.assertTrue(restarted.download(MID, approved=True).ok)

    def test_recover_removes_leftover_temporary_registry_files_and_reports_missing_files(self):
        manager = self.usable()
        write(os.path.join(self.root, "registry.json.4242.tmp"), b"{")
        os.unlink(manager.model_path(MID))
        restarted = self.manager()
        report = restarted.recover()
        self.assertEqual(report["missing_files"], [MID])
        self.assertIn("registry.json.4242.tmp", report["removed_files"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "registry.json.4242.tmp")))
        status = restarted.status(MID)
        self.assertEqual((status.state, status.usable, status.file), ("registered", False, None))
        self.assertEqual(status.reasons, ("file_missing",))


class PipelineTests(ManagerCase):
    def test_prepare_runs_every_stage_in_order_and_ends_usable(self):
        manager = self.manager()
        manager.register(card_dict())
        manager.download(MID, approved=True)
        report = manager.prepare(MID)
        self.assertTrue(report.ok)
        self.assertEqual([(s.stage, s.ok) for s in report.stages],
                         [("verify", True), ("compatibility", True), ("load", True), ("smoke", True)])
        status = manager.status(MID)
        self.assertEqual((status.state, status.usable, status.stage), ("usable", True, "smoke"))
        self.assertTrue(manager.is_usable(MID))
        entry = self.registry()["models"][MID]
        self.assertTrue(entry["smoke"]["ok"])
        self.assertEqual(entry["smoke"]["runtime"], "ngram")
        self.assertEqual([e[2]["to"] for e in self.events if e[0] == "transition"],
                         ["downloading", "downloaded", "verified", "compatible", "usable"])

    def test_each_stage_refuses_to_run_out_of_order(self):
        manager = self.manager()
        manager.register(card_dict())
        for call in (manager.verify, manager.check_compatibility, manager.load, manager.smoke_test):
            self.assertEqual(call(MID).code, "illegal_state", call)
        manager.download(MID, approved=True)
        for call in (manager.check_compatibility, manager.load, manager.smoke_test):
            self.assertEqual(call(MID).code, "illegal_state", call)
        self.assertTrue(manager.verify(MID).ok)
        for call in (manager.load, manager.smoke_test):
            self.assertEqual(call(MID).code, "illegal_state", call)
        self.assertTrue(manager.check_compatibility(MID).ok)
        self.assertEqual(manager.status(MID).state, "compatible")
        self.assertFalse(manager.generate(MID, "سلام").ok)  # compatible is still not usable
        self.assertTrue(manager.smoke_test(MID).ok)  # smoke loads on demand
        self.assertTrue(manager.generate(MID, "سلام").ok)

    def test_generate_is_refused_in_every_state_before_usable(self):
        manager = self.manager()
        manager.register(card_dict())
        seen = [manager.generate(MID, "سلام")]
        manager.download(MID, approved=True)
        seen.append(manager.generate(MID, "سلام"))
        manager.verify(MID)
        seen.append(manager.generate(MID, "سلام"))
        manager.check_compatibility(MID)
        seen.append(manager.generate(MID, "سلام"))
        for result in seen:
            self.assertEqual((result.ok, result.code, result.text), (False, "model_not_usable", ""), result)

    def test_generation_is_real_deterministic_and_limited(self):
        manager = self.usable()
        first = manager.generate(MID, "سلام", max_tokens=12, seed=3)
        second = manager.generate(MID, "سلام", max_tokens=12, seed=3)
        self.assertTrue(first.ok, first)
        self.assertEqual((first.code, first.runtime), ("ok", "ngram"))
        self.assertEqual(first.text, second.text)
        self.assertTrue(first.text.strip())
        self.assertLessEqual(len(first.text.split()), 40)
        direct = NgramRuntime()
        loaded = direct.load(manager.model_path(MID), manager._card(manager._ensure()[MID]))
        self.assertEqual(first.text, direct.generate(loaded, "سلام", max_tokens=12, seed=3))

    def test_generate_validates_its_arguments(self):
        manager = self.usable()
        for kwargs in (dict(prompt=""), dict(prompt="   "), dict(prompt=None), dict(prompt=5), dict(prompt="a" * 8001),
                       dict(prompt="سلام", max_tokens=0), dict(prompt="سلام", max_tokens=513), dict(prompt="سلام", max_tokens=True),
                       dict(prompt="سلام", max_tokens="5"), dict(prompt="سلام", seed=True), dict(prompt="سلام", seed="1")):
            result = manager.generate(MID, **kwargs)
            self.assertEqual((result.ok, result.code), (False, "bad_arguments"), kwargs)

    def test_the_prepare_report_stops_at_the_first_failed_stage(self):
        manager = self.manager(runtimes=[NO_LLAMA()])
        manager.register(card_dict())
        manager.download(MID, approved=True)
        report = manager.prepare(MID)
        self.assertFalse(report.ok)
        self.assertEqual([(s.stage, s.ok) for s in report.stages], [("verify", True), ("compatibility", False)])
        self.assertEqual(report.stages[-1].code, "no_runtime_for_format")
        self.assertEqual(report.status.state, "verified")
        self.assertFalse(report.status.usable)


class IntegrityTests(ManagerCase):
    def test_a_wrong_hash_is_quarantined_and_never_loaded(self):
        spy = NgramRuntime()
        spy.load = mock.Mock(wraps=spy.load)
        evil = bytearray(MODEL)
        evil[-3] ^= 0xFF  # same size, different content
        manager = self.manager(runtimes=[spy, NO_LLAMA()], downloader=FakeDownloader(payload=bytes(evil)))
        manager.register(card_dict())
        manager.download(MID, approved=True)  # the fake downloader does not verify; verify() must
        report = manager.prepare(MID)
        self.assertFalse(report.ok)
        self.assertEqual([(s.stage, s.code) for s in report.stages], [("verify", "hash_mismatch")])
        status = manager.status(MID)
        self.assertEqual((status.state, status.usable, status.file), ("failed", False, None))
        spy.load.assert_not_called()
        self.assertFalse(os.path.exists(manager.model_path(MID)))
        rejected = os.listdir(os.path.join(self.root, ".rejected"))
        self.assertEqual(len(rejected), 1)
        self.assertEqual(read_bytes(os.path.join(self.root, ".rejected", rejected[0])), bytes(evil))
        self.assertIn("quarantined", self.kinds())
        self.assertFalse(manager.generate(MID, "سلام").ok)

    def test_a_file_truncated_after_download_is_a_size_mismatch(self):
        manager = self.manager()
        manager.register(card_dict())
        manager.download(MID, approved=True)
        write(manager.model_path(MID), MODEL[:-5])
        status = manager.verify(MID)
        self.assertEqual((status.ok, status.code, status.state), (False, "size_mismatch", "failed"))
        self.assertEqual(len(os.listdir(os.path.join(self.root, ".rejected"))), 1)

    def test_a_card_that_disagrees_with_the_files_size_is_refused_even_when_the_hash_matches(self):
        manager = self.manager()
        manager.register(card_dict())
        manager.download(MID, approved=True)
        manager._ensure()[MID]["card"]["size_bytes"] = len(MODEL) + 1  # the stored card was edited after the download
        status = manager.verify(MID)
        self.assertEqual((status.ok, status.code, status.state), (False, "size_mismatch", "failed"))
        self.assertEqual(len(os.listdir(os.path.join(self.root, ".rejected"))), 1)

    def test_a_missing_file_fails_verification_cleanly(self):
        manager = self.manager()
        manager.register(card_dict())
        manager.download(MID, approved=True)
        os.unlink(manager.model_path(MID))
        status = manager.verify(MID)
        self.assertEqual((status.ok, status.code, status.state), (False, "file_missing", "failed"))

    def test_a_failed_model_can_start_over_from_the_beginning(self):
        fake = FakeDownloader(payload=MODEL[:-1] + b"X")
        manager = self.manager(downloader=fake)
        manager.register(card_dict())
        manager.download(MID, approved=True)
        self.assertEqual(manager.prepare(MID).stages[0].code, "hash_mismatch")
        fake.payload = MODEL
        self.assertTrue(manager.download(MID, approved=True).ok)
        self.assertTrue(manager.prepare(MID).ok)
        self.assertTrue(manager.is_usable(MID))

    def test_verifying_again_after_usable_rehashes_and_resets_the_trust(self):
        manager = self.usable()
        write(manager.model_path(MID), MODEL[:-1] + b"X")
        status = manager.verify(MID)
        self.assertEqual((status.code, status.state), ("hash_mismatch", "failed"))
        self.assertFalse(manager.is_usable(MID))
        self.assertFalse(manager.generate(MID, "سلام").ok)


class CompatibilityTests(ManagerCase):
    def verified(self, manager, **card):
        manager.register(card_dict(**card), license_ack=card.pop("ack", False))
        mid = card.get("model_id", MID)
        manager.download(mid, approved=True)
        self.assertTrue(manager.verify(mid).ok)
        return mid

    def test_missing_engine_is_a_reason_not_a_failure_and_clears_when_the_engine_appears(self):
        present = [False]
        llama = LlamaCppRuntime(spec_finder=lambda name: object() if present[0] else None)
        manager = self.manager(runtimes=[NgramRuntime(), llama])
        mid = self.verified(manager, model_id="gg-one", format="gguf")
        status = manager.check_compatibility(mid)
        self.assertEqual((status.ok, status.code, status.state, status.usable), (False, "dependency_missing", "verified", False))
        self.assertEqual(status.reasons, ("dependency_missing",))
        self.assertIn("compat_blocked", self.kinds())
        present[0] = True
        status = manager.check_compatibility(mid)
        self.assertEqual((status.ok, status.state), (True, "compatible"))

    def test_formats_without_an_engine_are_reported_honestly(self):
        manager = self.manager()
        for fmt in ("onnx", "tflite"):
            mid = self.verified(manager, model_id="x-" + fmt, format=fmt)
            status = manager.check_compatibility(mid)
            self.assertEqual((status.ok, status.code, status.state), (False, "no_runtime_for_format", "verified"), fmt)
            self.assertEqual(status.runtime, "")

    def test_runtime_hint_must_match_the_engine(self):
        manager = self.manager()
        mid = self.verified(manager, runtime_hint="onnxruntime")
        status = manager.check_compatibility(mid)
        self.assertEqual((status.ok, status.code), (False, "runtime_hint_unavailable"))
        manager2 = self.manager()
        manager2.remove(MID)
        manager2.register(card_dict(runtime_hint="ngram"))
        manager2.download(MID, approved=True)
        manager2.verify(MID)
        self.assertTrue(manager2.check_compatibility(MID).ok)

    def test_licence_must_be_acknowledged_before_the_model_becomes_compatible(self):
        manager = self.manager()
        manager.register(card_dict(license="cc-by-sa-4.0"))
        manager._ensure()[MID]["license_ack"] = True  # allow the download, then take the ack away to test this stage alone
        manager.download(MID, approved=True)
        manager.verify(MID)
        manager._ensure()[MID]["license_ack"] = False
        status = manager.check_compatibility(MID)
        self.assertEqual((status.ok, status.code, status.state), (False, "license_needs_ack", "verified"))
        manager.acknowledge_license(MID)
        self.assertTrue(manager.check_compatibility(MID).ok)

    def test_several_reasons_are_all_reported(self):
        manager = self.manager(runtimes=[NO_LLAMA()])
        manager.register(card_dict(model_id="gg-two", format="gguf", license="my-own-terms", runtime_hint="onnxruntime"))
        source = os.path.join(self._tmp.name, "own.gguf")
        write(source, MODEL)
        self.assertTrue(manager.import_local_file("gg-two", source).ok)  # a download would have been refused (unknown licence)
        self.assertTrue(manager.verify("gg-two").ok)
        mid = "gg-two"
        status = manager.check_compatibility(mid)
        self.assertFalse(status.ok)
        self.assertEqual(set(status.reasons), {"license_unknown", "runtime_hint_unavailable", "dependency_missing"})


class ScriptedRuntime(InferenceRuntime):
    """A fake engine whose behaviour each test chooses (the manager must not care which engine it drives)."""
    name = "scripted"
    formats = ("ngram-json",)

    def __init__(self, load_error=None, smoke_ok=True, smoke_raises=False, text="جواب آزمایشی", gen_error=None):
        self.load_error, self.smoke_ok, self.smoke_raises, self.text, self.gen_error = load_error, smoke_ok, smoke_raises, text, gen_error
        self.loads = self.smokes = self.generations = 0

    def availability(self):
        return RuntimeAvailability(True, "ok", "", "")

    def load(self, path, card):
        self.loads += 1
        if self.load_error is not None:
            raise self.load_error
        return LoadedModel(card.model_id, self.name, object(), path)

    def smoke_test(self, loaded):
        self.smokes += 1
        if self.smoke_raises:
            raise RuntimeError("engine crashed")
        return SmokeReport(self.smoke_ok, "scripted", "x" * 500)

    def generate(self, loaded, prompt, *, max_tokens, seed):
        self.generations += 1
        if self.gen_error is not None:
            raise self.gen_error
        return self.text


class EngineOutcomeTests(ManagerCase):
    def prepared(self, runtime):
        manager = self.manager(runtimes=[runtime])
        manager.register(card_dict())
        manager.download(MID, approved=True)
        return manager, manager.prepare(MID)

    def test_a_failing_load_is_a_failed_model(self):
        for error, code in ((RuntimeError("bad"), "engine_load_failed"), (ValueError("worse"), "engine_load_failed")):
            self.fresh_root()
            manager, report = self.prepared(ScriptedRuntime(load_error=error))
            self.assertFalse(report.ok)
            self.assertEqual(report.stages[-1].stage, "load")
            self.assertEqual((report.status.state, report.status.code, report.status.usable), ("failed", code, False))
            self.assertFalse(manager.generate(MID, "سلام").ok)

    def test_a_smoke_test_that_fails_or_crashes_never_makes_a_model_usable(self):
        for runtime in (ScriptedRuntime(smoke_ok=False), ScriptedRuntime(smoke_raises=True)):
            self.fresh_root()
            manager, report = self.prepared(runtime)
            self.assertFalse(report.ok)
            self.assertEqual(report.stages[-1].stage, "smoke")
            self.assertEqual((report.status.state, report.status.code), ("failed", "smoke_failed"))
            self.assertFalse(manager.is_usable(MID))
            self.assertEqual(runtime.generations, 0)
            self.assertNotEqual(self.registry()["models"][MID]["state"], "usable")

    def test_the_engine_output_is_returned_verbatim_and_never_replaced(self):
        runtime = ScriptedRuntime(text="جواب آزمایشی")
        manager, report = self.prepared(runtime)
        self.assertTrue(report.ok)
        result = manager.generate(MID, "سلام")
        self.assertEqual((result.ok, result.text, result.runtime), (True, "جواب آزمایشی", "scripted"))

    def test_a_generation_error_is_a_refusal_not_a_fabricated_answer(self):
        runtime = ScriptedRuntime(gen_error=RuntimeGenerateError("engine_generate_failed", "OSError"))
        manager, report = self.prepared(runtime)
        self.assertTrue(report.ok)
        result = manager.generate(MID, "سلام")
        self.assertEqual((result.ok, result.text), (False, ""))
        self.assertIn("generate_failed", self.kinds())

    def test_smoke_excerpt_is_bounded_in_the_registry(self):
        manager, _ = self.prepared(ScriptedRuntime())
        self.assertLessEqual(len(self.registry()["models"][MID]["smoke"]["excerpt"]), 200)


class RestartTests(ManagerCase):
    def test_usable_survives_a_restart_and_is_re_smoke_tested_once(self):
        first = self.usable()
        expected = first.generate(MID, "سلام", max_tokens=10, seed=1)
        runtime = NgramRuntime()
        runtime.smoke_test = mock.Mock(wraps=runtime.smoke_test)
        restarted = self.manager(runtimes=[runtime, NO_LLAMA()])
        self.assertTrue(restarted.is_usable(MID))
        again = restarted.generate(MID, "سلام", max_tokens=10, seed=1)
        self.assertEqual((again.ok, again.text), (True, expected.text))
        restarted.generate(MID, "سلام", max_tokens=10, seed=1)
        self.assertEqual(runtime.smoke_test.call_count, 1)

    def test_a_file_that_changed_while_the_app_was_off_is_not_trusted(self):
        self.usable()
        path = os.path.join(self.root, REL)
        write(path, MODEL[:-1] + b"X")  # same size, new mtime
        restarted = self.manager()
        result = restarted.generate(MID, "سلام")
        self.assertEqual((result.ok, result.code), (False, "model_not_usable"))
        status = restarted.status(MID)
        self.assertEqual((status.state, status.usable, status.reasons), ("downloaded", False, ("file_changed",)))
        report = restarted.prepare(MID)
        self.assertEqual(report.stages[0].code, "hash_mismatch")
        self.assertEqual(restarted.status(MID).state, "failed")

    def test_a_file_with_another_size_but_the_same_timestamp_is_not_trusted(self):
        self.usable()
        path = os.path.join(self.root, REL)
        before = os.stat(path)
        write(path, MODEL + b"extra")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        restarted = self.manager()
        result = restarted.generate(MID, "سلام")
        self.assertEqual((result.ok, result.code), (False, "model_not_usable"))
        self.assertEqual(restarted.status(MID).reasons, ("file_changed",))

    def test_a_file_that_vanished_is_noticed_on_first_use(self):
        self.usable()
        os.unlink(os.path.join(self.root, REL))
        restarted = self.manager()
        self.assertFalse(restarted.generate(MID, "سلام").ok)
        status = restarted.status(MID)
        self.assertEqual((status.state, status.reasons, status.file), ("registered", ("file_missing",), None))

    def test_a_listing_never_claims_usable_for_a_file_that_changed_or_vanished_while_the_app_was_off(self):
        self.usable()
        path = os.path.join(self.root, REL)
        write(path, MODEL[:-1] + b"X")
        restarted = self.manager()
        listed = restarted.list_models()                      # no generate() yet: the listing itself must not trust the old state
        self.assertEqual([(m.state, m.usable, m.reasons) for m in listed], [("downloaded", False, ("file_changed",))])
        self.assertFalse(restarted.is_usable(MID))
        os.unlink(path)
        again = self.manager()
        status = again.status(MID)
        self.assertEqual((status.state, status.usable, status.reasons, status.file), ("downloaded", False, ("file_changed",), status.file))

    def test_a_listing_still_shows_usable_while_the_file_is_unchanged(self):
        self.usable()
        restarted = self.manager()
        self.assertEqual([(m.state, m.usable) for m in restarted.list_models()], [("usable", True)])

    def test_an_edited_registry_cannot_conjure_a_usable_model(self):
        manager = self.manager()
        manager.register(card_dict())
        manager.download(MID, approved=True)  # downloaded, never verified
        data = self.registry()
        data["models"][MID]["state"] = "usable"
        data["models"][MID]["smoke"] = {"ok": True, "details": "forged", "excerpt": "", "at": 1.0, "runtime": "ngram"}
        write(os.path.join(self.root, "registry.json"), json.dumps(data).encode("utf-8"))
        write(os.path.join(self.root, REL), b"not a model at all")  # and the file is junk of a different size
        restarted = self.manager()
        result = restarted.generate(MID, "سلام")
        self.assertEqual((result.ok, result.code), (False, "model_not_usable"))
        self.assertFalse(restarted.is_usable(MID) and restarted.status(MID).state == "usable")

    def test_an_edited_registry_with_a_forged_smoke_still_cannot_load_junk(self):
        manager = self.usable()
        data = self.registry()
        junk = b"x" * len(MODEL)
        write(os.path.join(self.root, REL), junk)
        stat = os.stat(os.path.join(self.root, REL))
        data["models"][MID]["file"]["mtime_ns"] = stat.st_mtime_ns  # attacker also fixes the recorded mtime
        write(os.path.join(self.root, "registry.json"), json.dumps(data).encode("utf-8"))
        restarted = self.manager()
        result = restarted.generate(MID, "سلام")  # the once-per-process smoke test really loads the file and rejects junk
        self.assertEqual((result.ok, result.code), (False, "model_not_usable"))
        self.assertEqual(restarted.status(MID).state, "failed")


class RegistryDamageTests(ManagerCase):
    def test_a_corrupt_registry_is_set_aside_reported_and_never_trusted(self):
        os.makedirs(self.root)
        garbage = b"{ this is not json"
        write(os.path.join(self.root, "registry.json"), garbage)
        manager = self.manager()
        self.assertEqual(manager.list_models(), [])
        recovery = manager.registry_recovery
        self.assertEqual(recovery["moved_to"], "registry.json.corrupt.1")
        self.assertEqual(read_bytes(os.path.join(self.root, "registry.json.corrupt.1")), garbage)
        self.assertIn("registry_corrupt", self.kinds())
        self.assertTrue(manager.register(card_dict()).ok)  # keeps working afterwards
        self.assertEqual(self.manager().status(MID).state, "registered")

    def test_a_valid_but_forged_registry_structure_is_set_aside(self):
        os.makedirs(self.root)
        write(os.path.join(self.root, "registry.json"), json.dumps({"schema": 1, "models": {MID: {"state": "usable"}}}).encode())
        manager = self.manager()
        self.assertEqual(manager.list_models(), [])
        self.assertIsNotNone(manager.registry_recovery)

    def test_a_failed_registry_write_never_reports_an_unsaved_state(self):
        manager = self.manager()
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                manager.register(card_dict())
        self.assertEqual(manager.status(MID).code, "unknown_model")  # memory was dropped, not left ahead of the disk
        self.assertFalse(os.path.exists(os.path.join(self.root, "registry.json")))
        self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])
        self.assertTrue(manager.register(card_dict()).ok)

    def test_a_failed_write_in_the_middle_of_a_transition_keeps_the_previous_state(self):
        manager = self.manager()
        manager.register(card_dict())
        before = read_bytes(os.path.join(self.root, "registry.json"))
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                manager.download(MID, approved=True)
        self.assertEqual(read_bytes(os.path.join(self.root, "registry.json")), before)
        self.assertEqual(manager.status(MID).state, "registered")

    def test_a_broken_audit_callback_never_breaks_the_manager(self):
        def broken(kind, subject, detail):
            raise RuntimeError("audit sink is down")

        manager = self.manager(audit=broken)
        self.assertTrue(manager.register(card_dict()).ok)
        self.assertTrue(manager.download(MID, approved=True).ok)
        self.assertTrue(manager.prepare(MID).ok)


class ImportTests(ManagerCase):
    def source(self, data=MODEL, name="sideload.bin"):
        path = os.path.join(self._tmp.name, name)
        write(path, data)
        return path

    def test_a_local_file_is_copied_in_and_the_original_is_left_alone(self):
        manager = self.manager()
        manager.register(card_dict(source_url="local-import"))
        src = self.source()
        status = manager.import_local_file(MID, src)
        self.assertEqual((status.ok, status.state, status.stage), (True, "downloaded", "import"))
        self.assertEqual(read_bytes(src), MODEL)
        self.assertEqual(read_bytes(manager.model_path(MID)), MODEL)
        self.assertEqual(os.listdir(os.path.dirname(manager.model_path(MID))), ["model.bin"])
        self.assertTrue(manager.prepare(MID).ok)

    def test_a_model_that_has_a_download_address_can_still_be_sideloaded(self):
        manager = self.manager(downloader=FakeDownloader(), gate=None)  # no internet at all
        manager.register(card_dict())
        self.assertEqual(manager.download(MID, approved=True).code, "permission_denied")
        self.assertTrue(manager.import_local_file(MID, self.source()).ok)
        self.assertTrue(manager.prepare(MID).ok)

    def test_unsafe_or_wrong_sources_are_refused_and_nothing_is_stored(self):
        manager = self.manager()
        manager.register(card_dict())
        link = os.path.join(self._tmp.name, "link.bin")
        os.symlink(self.source(), link)
        for src, code in ((link, "model_file_invalid"), (self._tmp.name, "model_file_invalid"),
                          (os.path.join(self._tmp.name, "absent.bin"), "model_file_invalid"), (None, "model_file_invalid"),
                          (5, "model_file_invalid"), (self.source(MODEL[:-1], "short.bin"), "size_mismatch"),
                          (self.source(MODEL + b"x", "long.bin"), "size_mismatch")):
            status = manager.import_local_file(MID, src)
            self.assertEqual((status.ok, status.code, status.state), (False, code, "registered"), (src, status))
        self.assertFalse(os.path.exists(manager.model_path(MID)))

    def test_import_needs_free_space_and_the_right_state(self):
        manager = self.manager(free_space_fn=lambda _p: Usage(0, 0, 10))
        manager.register(card_dict())
        self.assertEqual(manager.import_local_file(MID, self.source()).code, "insufficient_space")
        ok = self.manager()
        self.assertTrue(ok.import_local_file(MID, self.source()).ok)
        self.assertEqual(ok.import_local_file(MID, self.source()).code, "illegal_state")

    def test_a_copy_that_fails_midway_leaves_nothing_behind(self):
        manager = self.manager()
        manager.register(card_dict())
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            status = manager.import_local_file(MID, self.source())
        self.assertEqual((status.ok, status.code, status.state), (False, "io_error", "registered"))
        directory = os.path.dirname(manager.model_path(MID))
        self.assertEqual(os.listdir(directory), [])

    def test_the_wrong_content_of_the_right_size_is_caught_by_verification(self):
        manager = self.manager()
        manager.register(card_dict())
        self.assertTrue(manager.import_local_file(MID, self.source(b"y" * len(MODEL))).ok)
        report = manager.prepare(MID)
        self.assertEqual([(s.stage, s.code) for s in report.stages], [("verify", "hash_mismatch")])
        self.assertFalse(manager.is_usable(MID))


class FakeLlamaModule:
    """A stand-in for the `llama_cpp` package (a real one cannot exist in this test run)."""

    def __init__(self, text=" سلام دنیا", load_error=None, call_result=None, call_error=None):
        self.text, self.load_error, self.call_result, self.call_error = text, load_error, call_result, call_error
        self.loaded, self.calls = [], []
        outer = self

        class Llama:
            def __init__(inner, model_path, n_ctx, n_threads, verbose):
                if outer.load_error is not None:
                    raise outer.load_error
                outer.loaded.append(dict(model_path=model_path, n_ctx=n_ctx, n_threads=n_threads, verbose=verbose))

            def __call__(inner, prompt, max_tokens, temperature, seed):
                outer.calls.append(dict(prompt=prompt, max_tokens=max_tokens, temperature=temperature, seed=seed))
                if outer.call_error is not None:
                    raise outer.call_error
                if outer.call_result is not None:
                    return outer.call_result
                return {"choices": [{"text": outer.text}]}

        self.Llama = Llama


GGUF = b"GGUF" + bytes(range(256)) * 4
GGUF_SHA = hashlib.sha256(GGUF).hexdigest()


class LlamaEngineTests(ManagerCase):
    def gguf_manager(self, module, payload=GGUF, **card):
        runtime = LlamaCppRuntime(module_loader=lambda name: module, spec_finder=lambda name: object())
        manager = self.manager(runtimes=[NgramRuntime(), runtime], downloader=FakeDownloader(payload=payload))
        manager.register(card_dict(model_id="gg-model", format="gguf", sha256=hashlib.sha256(payload).hexdigest(),
                                   size_bytes=len(payload), source_url="https://models.example.org/m.gguf", **card))
        manager.download("gg-model", approved=True)
        return manager

    def test_a_gguf_model_becomes_usable_only_through_the_engine_and_a_real_call(self):
        module = FakeLlamaModule(text=" سلام دنیا")
        manager = self.gguf_manager(module)
        report = manager.prepare("gg-model")
        self.assertTrue(report.ok, report)
        self.assertEqual(module.loaded[0]["model_path"], manager.model_path("gg-model"))
        self.assertEqual(len(module.calls), 1)  # the smoke test ran the engine for real
        result = manager.generate("gg-model", "سلام", max_tokens=9, seed=4)
        self.assertEqual((result.ok, result.text, result.runtime), (True, " سلام دنیا", "llama_cpp"))
        self.assertEqual(module.calls[-1], dict(prompt="سلام", max_tokens=9, temperature=0.0, seed=4))

    def test_without_the_package_a_gguf_model_stays_blocked_and_nothing_is_generated(self):
        manager = self.manager(runtimes=[NgramRuntime(), NO_LLAMA()], downloader=FakeDownloader(payload=GGUF))
        manager.register(card_dict(model_id="gg-model", format="gguf", sha256=GGUF_SHA, size_bytes=len(GGUF)))
        manager.download("gg-model", approved=True)
        report = manager.prepare("gg-model")
        self.assertFalse(report.ok)
        self.assertEqual(report.status.reasons, ("dependency_missing",))
        self.assertEqual(report.status.state, "verified")
        self.assertEqual(manager.generate("gg-model", "سلام").code, "model_not_usable")

    def test_a_file_that_is_not_gguf_is_refused_by_the_loader(self):
        module = FakeLlamaModule()
        manager = self.gguf_manager(module, payload=b"NOPE" + bytes(range(256)))
        report = manager.prepare("gg-model")
        self.assertFalse(report.ok)
        self.assertEqual((report.stages[-1].stage, report.status.state), ("load", "failed"))
        self.assertEqual(module.loaded, [])  # the native engine never saw it

    def test_engine_failures_are_reported_not_hidden(self):
        for module, code in ((FakeLlamaModule(load_error=RuntimeError("oom")), "engine_load_failed"),
                             (FakeLlamaModule(text="   "), "smoke_failed"),
                             (FakeLlamaModule(call_result={"choices": [{"text": 5}]}), "smoke_failed"),
                             (FakeLlamaModule(call_result={"oops": 1}), "smoke_failed"),
                             (FakeLlamaModule(call_error=OSError("device lost")), "smoke_failed")):
            self.fresh_root()
            manager = self.gguf_manager(module)
            report = manager.prepare("gg-model")
            self.assertFalse(report.ok, code)
            self.assertEqual((report.status.state, report.status.code, report.status.usable), ("failed", code, False))
            self.assertFalse(manager.generate("gg-model", "سلام").ok)

    def test_native_error_details_never_reach_the_status_text(self):
        module = FakeLlamaModule(load_error=RuntimeError("secret path /data/user/0/model.gguf"))
        manager = self.gguf_manager(module)
        report = manager.prepare("gg-model")
        blob = json.dumps(report.status.to_dict(), ensure_ascii=False)
        self.assertNotIn("secret", blob)
        self.assertNotIn("/data/user", blob)


class WebToolsIntegrationTests(ManagerCase):
    """The REAL net_tools.download_file with a scripted stream transport (no socket is ever opened)."""

    def transport(self, *items):
        from tests.test_net_tools_download_prompt957 import FakeStreamTransport
        return FakeStreamTransport(*items)

    def stream(self, data, **kw):
        from tests.test_net_tools_download_prompt957 import split, stream_of
        return stream_of(split(data), declared=kw.pop("declared", len(data)), **kw)

    def manager_with(self, transport, gate=GATE, downloader_gate=None):
        return self.manager(downloader=default_downloader(downloader_gate or gate, transport=transport), gate=gate)

    def test_register_download_verify_load_smoke_generate_end_to_end(self):
        transport = self.transport(self.stream(MODEL))
        manager = self.manager_with(transport)
        self.assertTrue(manager.register(card_dict()).ok)
        status = manager.download(MID, approved=True)
        self.assertEqual((status.ok, status.state), (True, "downloaded"), status)
        self.assertEqual([r.host for r in transport.requests], ["models.example.org"])
        self.assertTrue(manager.prepare(MID).ok)
        result = manager.generate(MID, "سلام", max_tokens=10)
        self.assertTrue(result.ok and result.text.strip(), result)

    def test_a_server_that_sends_other_bytes_is_rejected_by_the_hash_check(self):
        evil = bytearray(MODEL)
        evil[-3] ^= 0xFF
        manager = self.manager_with(self.transport(self.stream(bytes(evil))))
        manager.register(card_dict())
        status = manager.download(MID, approved=True)
        self.assertEqual((status.ok, status.state, status.code), (False, "failed", "download_failed"))
        self.assertEqual(status.reasons, ("hash_mismatch",))
        directory = os.path.join(self.root, "files", MID, "1.0")
        self.assertEqual(os.listdir(directory) if os.path.isdir(directory) else [], [])

    def test_a_server_that_sends_too_much_is_cut_off(self):
        manager = self.manager_with(self.transport(self.stream(MODEL + b"x" * 5000, declared=None)))
        manager.register(card_dict())
        status = manager.download(MID, approved=True)
        self.assertEqual((status.ok, status.state), (False, "failed"))
        self.assertIn(status.reasons[0], ("too_large", "size_mismatch"))
        directory = os.path.join(self.root, "files", MID, "1.0")
        self.assertEqual(os.listdir(directory) if os.path.isdir(directory) else [], [])

    def test_offline_is_a_clear_failure_and_a_retry_works_later(self):
        from net_tools import TransportError

        transport = self.transport(TransportError("offline", "no route"), self.stream(MODEL))
        manager = self.manager_with(transport)
        manager.register(card_dict())
        status = manager.download(MID, approved=True)
        self.assertEqual((status.ok, status.state, status.reasons), (False, "failed", ("offline",)))
        self.assertTrue(manager.download(MID, approved=True).ok)
        self.assertTrue(manager.prepare(MID).ok)

    def test_the_manager_gate_stops_the_download_before_any_request(self):
        transport = self.transport(self.stream(MODEL))
        manager = self.manager_with(transport, gate=StaticGate([]))
        manager.register(card_dict())
        self.assertEqual(manager.download(MID, approved=True).code, "permission_denied")
        self.assertEqual(transport.requests, [])

    def test_the_downloader_has_its_own_gate_and_it_is_also_enforced(self):
        transport = self.transport(self.stream(MODEL))
        manager = self.manager_with(transport, gate=GATE, downloader_gate=StaticGate([]))
        manager.register(card_dict())
        status = manager.download(MID, approved=True)
        self.assertEqual((status.ok, status.state, status.reasons), (False, "failed", ("permission_denied",)))
        self.assertEqual(transport.requests, [])


class BridgeTests(ManagerCase):
    """ManagedModelRuntime behind the EXISTING LocalLanguageModelBackend / provider chain."""

    def setUp(self):
        super().setUp()
        from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
        from language_intelligence.local_model_backend import LocalLanguageModelBackend
        from understanding.engine import UnderstandingEngine
        from model_runtime.bridge import ManagedModelRuntime, build_provider

        self.Backend, self.Runtime, self.build_provider = LocalLanguageModelBackend, ManagedModelRuntime, build_provider
        self.understanding = lambda text: DeterministicFallbackBackend(UnderstandingEngine()).understand(text)

    def test_a_model_that_is_not_usable_reports_not_configured_and_generates_nothing(self):
        manager = self.manager()
        manager.register(card_dict())
        manager.download(MID, approved=True)  # downloaded, not verified
        backend = self.Backend(provider=self.build_provider(manager, MID))
        availability = backend.check_availability()
        self.assertFalse(availability.can_infer)
        self.assertFalse(availability.configured)
        response = backend.generate_response(self.understanding("سلام"))
        self.assertEqual(response.status, "model_not_configured")
        self.assertIsNone(response.response_text)

    def test_an_unregistered_model_is_not_configured_either(self):
        backend = self.Backend(provider=self.build_provider(self.manager(), "ghost-model"))
        self.assertFalse(backend.check_availability().can_infer)
        self.assertIsNone(backend.generate_response(self.understanding("سلام")).response_text)

    def test_a_usable_model_answers_through_the_existing_backend(self):
        manager = self.usable()
        provider = self.build_provider(manager, MID)
        backend = self.Backend(provider=provider)
        availability = backend.check_availability()
        self.assertTrue(availability.can_infer, availability)
        self.assertEqual(availability.runtime_name, "managed-model")
        response = backend.generate_response(self.understanding("سلام"))
        self.assertEqual(response.status, "generated", response.__dict__)
        self.assertTrue(response.response_text and response.response_text.strip())
        direct = manager.generate(MID, "سلام", max_tokens=response.metadata.get("max_output_tokens", 64) if response.metadata else 64)
        self.assertTrue(direct.ok)

    def test_when_the_model_stops_being_usable_the_chain_follows_after_a_refresh(self):
        manager = self.usable()
        runtime = self.Runtime(manager, MID)
        backend = self.Backend(runtime=runtime)
        self.assertTrue(backend.check_availability().can_infer)
        write(manager.model_path(MID), MODEL[:-1] + b"X")
        manager.verify(MID)  # re-hash: failed
        self.assertFalse(manager.is_usable(MID))
        self.assertFalse(runtime.dependency_status()[0])  # live, no refresh needed to refuse
        response = backend.generate_response(self.understanding("سلام"))
        self.assertIsNone(response.response_text)
        self.assertFalse(runtime.refresh())
        self.assertFalse(backend.check_availability().can_infer)

    def test_the_runtime_never_substitutes_an_answer(self):
        manager = self.manager(runtimes=[ScriptedRuntime(text="x")])
        manager.register(card_dict())
        manager.download(MID, approved=True)
        runtime = self.Runtime(manager, MID)
        from language_intelligence.inference import InferenceRequest

        result = runtime.generate(InferenceRequest(user_input="سلام"))
        self.assertNotEqual(result.status, "success")
        self.assertFalse(getattr(result, "text", None))

    def test_understand_stays_explicitly_unsupported(self):
        manager = self.usable()
        backend = self.Backend(provider=self.build_provider(manager, MID))
        with self.assertRaises(NotImplementedError):
            backend.understand("سلام")
