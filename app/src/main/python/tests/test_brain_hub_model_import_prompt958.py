"""
Prompt 958 - importing a model file the user picked himself (hub level: `inbox_model_files`, `import_unknown_model`).

Proven: only plain `.task` / `.gguf` files are offered (a `.json` only when asked for); the app computes the hash itself ("trust on first use")
and builds a card from the file; a licence is never guessed to be a free one from a file name; the same file is never copied twice; a
different file under an id that is taken is refused; the app's own staging copy is removed after a successful import (the model is not kept
twice on the phone); hostile names, links and empty files are refused; and the whole path import -> prepare -> a real (fake-engine) answer works.
NOT proven: that a real Gemma file loads in the real engine on a real phone.
"""

import hashlib
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub.builtin_tools import ToolsMixin
from brain_hub.service import HubService
from model_runtime import MediaPipeLlmRuntime, NgramRuntime
from model_runtime.card import parse_card
from tests import brain_hub_fixtures_prompt957 as F
from tests.llm_support_prompt958 import with_llm_engine
from tests.native_support_prompt958 import FakeJava

TASK_BYTES = b"PK\x03\x04 pretend this is a task bundle " * 50


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "brain_hub")
        self.jvm = FakeJava(installed=set())
        self.engine = with_llm_engine(self.jvm, answers=("جواب آزمایشی.",))
        self.hubs = []
        self.free = F.PLENTY

    def tearDown(self):
        for hub in self.hubs:
            hub.close()

    def hub(self, with_engine=True):
        jvm = self.jvm
        runtimes = [NgramRuntime(), MediaPipeLlmRuntime(jvm_provider=(lambda: jvm) if with_engine else (lambda: None))]
        hub = HubService(self.root, clock=lambda: 1_700_000_000.0, model_runtimes=runtimes, free_space_fn=lambda p: self.free(p),
                         bridge=F.HubFakeBridge())
        self.hubs.append(hub)
        return hub

    def put(self, name, data=TASK_BYTES):
        directory = os.path.join(self.root, "inbox")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def inbox(self, name):
        return os.path.join(self.root, "inbox", name)

    def stored_files(self):
        """The model files the model store holds (not the registry or the audit lines)."""
        base = os.path.join(self.root, "models", "files")
        return sorted(os.path.join(d, f) for d, _, files in os.walk(base) for f in files if not f.endswith(".partial"))


class InboxListing(Base):
    def test_only_plain_task_and_gguf_files_are_offered(self):
        hub = self.hub()
        self.put("gemma-3-1b-it-int4.task")
        self.put("tiny.gguf", b"GGUF" * 100)
        self.put("notes.txt", b"hello")
        self.put("model.json", F.MODEL_BYTES)
        self.put("empty.task", b"")
        self.put("has space.task")
        self.put("badا.task")
        os.makedirs(os.path.join(self.root, "inbox", "folder.task"))
        names = [f["name"] for f in hub.inbox_model_files()]
        self.assertEqual(names, ["gemma-3-1b-it-int4.task", "tiny.gguf"])
        found = {f["name"]: f for f in hub.inbox_model_files()}
        self.assertEqual((found["gemma-3-1b-it-int4.task"]["format"], found["gemma-3-1b-it-int4.task"]["size"]), ("task", len(TASK_BYTES)))
        self.assertEqual(found["tiny.gguf"]["format"], "gguf")

    def test_a_json_file_is_offered_only_when_asked_for(self):
        hub = self.hub()
        self.put("model.json", F.MODEL_BYTES)
        self.assertEqual(hub.inbox_model_files(), [])
        self.assertEqual([f["name"] for f in hub.inbox_model_files(include_json=True)], ["model.json"])

    def test_links_are_never_offered(self):
        hub = self.hub()
        outside = os.path.join(self._tmp.name, "outside.task")
        with open(outside, "wb") as handle:
            handle.write(TASK_BYTES)
        os.makedirs(os.path.join(self.root, "inbox"), exist_ok=True)
        try:
            os.symlink(outside, self.inbox("link.task"))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        self.assertEqual(hub.inbox_model_files(), [])
        self.assertIsNone(hub.find_inbox_file("link.task"))
        self.assertEqual(hub.import_unknown_model("link.task").code, "file_missing")

    def test_no_inbox_folder_is_an_empty_list_and_creates_nothing(self):
        hub = self.hub()
        self.assertEqual(hub.inbox_model_files(), [])
        self.assertFalse(os.path.exists(self.root))

    def test_at_most_twenty_files_are_listed(self):
        hub = self.hub()
        for i in range(30):
            self.put("m%02d.gguf" % i, b"GGUF%d" % i)
        self.assertEqual(len(hub.inbox_model_files()), 20)

    def test_a_file_is_found_by_name_ignoring_letter_case(self):
        hub = self.hub()
        self.put("Gemma-3-1B.task")
        self.assertEqual(hub.find_inbox_file("gemma-3-1b.TASK")["name"], "Gemma-3-1B.task")
        self.assertIsNone(hub.find_inbox_file("other.task"))
        self.assertIsNone(hub.find_inbox_file(""))
        self.assertIsNone(hub.find_inbox_file(None))


class NamesAndLicences(Base):
    def test_a_model_id_made_from_any_file_name_is_a_valid_card_id(self):
        for name in ("Gemma-3-1B-it_int4.task", "فایل.task", "alpha.task", "9.gguf", "UPPER CASE (1).gguf", "..x..task", "x" * 100 + ".task"):
            with self.subTest(name=name):
                mid = ToolsMixin.model_id_for_file(name)
                card = {"model_id": mid, "title": "t", "version": "local", "format": "task", "source_url": "local-import",
                        "sha256": "0" * 64, "size_bytes": 1, "license": "user-supplied"}
                self.assertEqual(parse_card(card).model_id, mid)

    def test_only_gemma_and_llama_are_named_everything_else_is_left_to_the_user(self):
        names = {"Gemma-3-1B-it_int4.task": "gemma", "gemma3-1b.task": "gemma", "llama-3.2-1b.gguf": "llama", "llama3.gguf": "llama",
                 "tinyllama-1.1b.gguf": "user-supplied", "dolphin-phi.gguf": "user-supplied", "qwen2.5-0.5b.task": "user-supplied",
                 "phi-3-mini.gguf": "user-supplied", "mystery.task": "user-supplied", "gemmaless.task": "user-supplied"}
        for name, expected in names.items():
            with self.subTest(name=name):
                self.assertEqual(ToolsMixin.license_for_file(name), expected)

    def test_no_file_name_ever_makes_a_licence_permissive(self):
        from model_runtime.card import license_policy
        for name in ("qwen2.5.task", "mit-model.gguf", "apache-2.0.task", "phi-3.gguf", "smollm2.task", "mistral-7b.gguf", "x.task"):
            with self.subTest(name=name):
                self.assertNotEqual(license_policy(ToolsMixin.license_for_file(name)), "permissive")


class Importing(Base):
    def test_a_file_is_imported_with_a_hash_the_app_computed_itself(self):
        hub = self.hub()
        self.put("gemma-3-1b-it-int4.task")
        status = hub.import_unknown_model("gemma-3-1b-it-int4.task")
        self.assertEqual((status.ok, status.state, status.usable), (True, "downloaded", False))
        self.assertEqual(status.model_id, "gemma-3-1b-it-int4")
        card = hub.model_status("gemma-3-1b-it-int4").card
        self.assertEqual((card["sha256"], card["size_bytes"], card["format"]), (hashlib.sha256(TASK_BYTES).hexdigest(), len(TASK_BYTES), "task"))
        self.assertEqual((card["source_url"], card["version"], card["license"]), ("local-import", "local", "gemma"))
        self.assertFalse(hub.model_status("gemma-3-1b-it-int4").license_ack)

    def test_the_staging_copy_is_removed_after_the_import_so_the_model_is_not_kept_twice(self):
        hub = self.hub()
        self.put("alpha.task")
        self.assertTrue(hub.import_unknown_model("alpha.task").ok)
        self.assertFalse(os.path.exists(self.inbox("alpha.task")))
        stored = self.stored_files()
        self.assertEqual(len(stored), 1)
        with open(stored[0], "rb") as handle:
            self.assertEqual(handle.read(), TASK_BYTES)

    def test_the_staging_copy_can_be_kept(self):
        hub = self.hub()
        self.put("alpha.task")
        self.assertTrue(hub.import_unknown_model("alpha.task", remove_source=False).ok)
        self.assertTrue(os.path.isfile(self.inbox("alpha.task")))

    def test_a_failed_import_keeps_the_staging_copy(self):
        hub = self.hub()
        self.put("alpha.task")
        self.free = lambda _p: F.Usage(10 ** 6, 10 ** 6 - 10, 10)
        status = hub.import_unknown_model("alpha.task")
        self.assertEqual((status.ok, status.code), (False, "insufficient_space"))
        self.assertTrue(os.path.isfile(self.inbox("alpha.task")))
        self.assertEqual(hub.list_models(), [])                  # no empty, half-made entry is left behind

    def test_the_same_file_again_is_not_copied_twice(self):
        hub = self.hub()
        self.put("alpha.task")
        self.assertTrue(hub.import_unknown_model("alpha.task").ok)
        stored = self.stored_files()
        self.assertEqual(len(stored), 1)
        os.utime(stored[0], ns=(1_000_000_000, 1_000_000_000))        # a marker: a second copy would give the file a new modification time
        self.put("alpha.task")                                        # picked again
        again = hub.import_unknown_model("alpha.task")
        self.assertEqual((again.ok, again.state), (True, "downloaded"))
        self.assertEqual(len(hub.list_models()), 1)
        self.assertEqual(os.stat(self.stored_files()[0]).st_mtime_ns, 1_000_000_000)
        self.assertFalse(os.path.exists(self.inbox("alpha.task")))     # the staging copy of an already-stored file is not kept either

    def test_a_different_file_under_a_taken_id_is_refused_and_nothing_changes(self):
        hub = self.hub()
        self.put("alpha.task")
        self.assertTrue(hub.import_unknown_model("alpha.task").ok)
        before = hub.model_status("alpha").card["sha256"]
        self.put("alpha.task", TASK_BYTES + b"changed")
        refused = hub.import_unknown_model("alpha.task")
        self.assertEqual((refused.ok, refused.code), (False, "model_id_taken"))
        self.assertEqual(hub.model_status("alpha").card["sha256"], before)
        self.assertTrue(os.path.isfile(self.inbox("alpha.task")))      # the user's staged file is not thrown away

    def test_a_licence_acknowledgement_is_recorded_only_when_the_user_gave_it(self):
        hub = self.hub()
        self.put("alpha.task")
        hub.import_unknown_model("alpha.task", license_ack=False)
        self.assertFalse(hub.model_status("alpha").license_ack)
        self.put("bravo.task", TASK_BYTES + b"b")
        hub.import_unknown_model("bravo.task", license_ack=True)
        self.assertTrue(hub.model_status("bravo").license_ack)
        self.put("charlie.task", TASK_BYTES + b"c")
        hub.import_unknown_model("charlie.task", license_ack="yes")        # only a real True counts
        self.assertFalse(hub.model_status("charlie").license_ack)

    def test_hostile_and_unknown_things_are_refused(self):
        hub = self.hub()
        self.put("alpha.task")
        for name in ("../a.task", "a/b.task", "/etc/passwd", "", None, 5, ".hidden.task", "x" * 200 + ".task", "a b.task", "a\x00.task", "a.task\n"):
            with self.subTest(name=name):
                status = hub.import_unknown_model(name)
                self.assertEqual((status.ok, status.code), (False, "bad_arguments"))
        self.put("notes.txt", b"hi")
        self.assertEqual(hub.import_unknown_model("notes.txt").code, "unknown_format")
        self.assertEqual(hub.import_unknown_model("missing.task").code, "file_missing")
        self.put("empty.task", b"")
        self.assertFalse(hub.import_unknown_model("empty.task").ok)
        self.assertEqual(hub.list_models(), [])
        self.assertTrue(os.path.isfile(self.inbox("alpha.task")))

    def test_the_whole_path_import_prepare_ask(self):
        hub = self.hub()
        self.put("gemma-test.task")
        self.assertTrue(hub.import_unknown_model("gemma-test.task", license_ack=True).ok)
        report = hub.prepare_model("gemma-test")
        self.assertTrue(report.ok, report)
        self.assertEqual([s.stage for s in report.stages], ["verify", "compatibility", "load", "smoke"])
        self.assertTrue(hub.model_status("gemma-test").usable)
        answer = hub.ask_model("gemma-test", "سلام", max_tokens=32)
        self.assertEqual((answer.ok, answer.text), (True, "جواب آزمایشی."))
        self.assertTrue(self.engine["options"][0]["model_path"].startswith(os.path.join(self.root, "models")))

    def test_without_the_licence_acknowledgement_the_pipeline_stops_at_compatibility_and_nothing_is_loaded(self):
        hub = self.hub()
        self.put("gemma-test.task")
        self.assertTrue(hub.import_unknown_model("gemma-test.task").ok)
        report = hub.prepare_model("gemma-test")
        self.assertFalse(report.ok)
        self.assertEqual([(s.stage, s.ok) for s in report.stages], [("verify", True), ("compatibility", False)])
        self.assertEqual(report.stages[-1].code, "license_needs_ack")
        self.assertEqual(self.engine["created"], [])
        self.assertTrue(hub.acknowledge_model_license("gemma-test").ok)
        self.assertTrue(hub.prepare_model("gemma-test").ok)

    def test_an_apk_without_the_engine_keeps_the_imported_model_and_says_why_it_cannot_run(self):
        hub = self.hub(with_engine=False)
        self.put("gemma-test.task")
        self.assertTrue(hub.import_unknown_model("gemma-test.task", license_ack=True).ok)
        report = hub.prepare_model("gemma-test")
        self.assertFalse(report.ok)
        self.assertEqual(report.stages[-1].stage, "compatibility")
        self.assertIn(report.stages[-1].code, ("unavailable_platform", "dependency_missing"))
        status = hub.model_status("gemma-test")
        self.assertEqual((status.state, status.usable), ("verified", False))           # the file stays, ready for a build that has the engine

    def test_a_tampered_file_after_the_import_is_caught_by_the_hash_the_app_took(self):
        hub = self.hub()
        self.put("gemma-test.task")
        self.assertTrue(hub.import_unknown_model("gemma-test.task", license_ack=True).ok)
        stored = self.stored_files()[0]
        with open(stored, "rb") as handle:
            data = bytearray(handle.read())
        data[10] ^= 0x01
        with open(stored, "wb") as handle:
            handle.write(bytes(data))
        report = hub.prepare_model("gemma-test")
        self.assertFalse(report.ok)
        self.assertEqual((report.stages[0].stage, report.stages[0].code), ("verify", "hash_mismatch"))
        self.assertFalse(hub.model_status("gemma-test").usable)


if __name__ == "__main__":
    unittest.main()
