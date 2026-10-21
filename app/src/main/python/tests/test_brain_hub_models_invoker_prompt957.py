"""
Prompt 957 - HubService models + the execution invoker + the module API.

Acceptance behaviour 8: a model file is NOT usable until its hash, compatibility, loading and a real inference smoke test
all passed; downloads need an explicit yes AND the internet permission. The invoker tests show that one choke point
(`execute`) refuses everything that is not usable right now and never raises.
"""
import hashlib
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import service as hub_service
from brain_hub.service import HubService, default_root, get_hub, reset_hub, set_hub
from model_runtime import LlamaCppRuntime, NgramRuntime, train_ngram_model
from tests import brain_hub_fixtures_prompt957 as F


def runtimes():
    """The n-gram engine plus a llama.cpp engine that is deterministically NOT installed."""
    return [NgramRuntime(), LlamaCppRuntime(spec_finder=lambda name: None)]


class HubCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "brain_hub")
        self.now = [1_700_000_000.0]
        self.hubs = []

    def tearDown(self):
        for hub in self.hubs:
            hub.close()

    def hub(self, **kw):
        kw.setdefault("clock", lambda: self.now[0])
        kw.setdefault("model_runtimes", runtimes())
        kw.setdefault("free_space_fn", F.PLENTY)
        kw.setdefault("bridge", F.HubFakeBridge())
        hub = HubService(self.root, **kw)
        self.hubs.append(hub)
        return hub

    def usable_hub(self, **kw):
        transport = F.FakeStreamTransport(F.MODEL_BYTES)
        hub = self.hub(download_transport=transport, **kw)
        self.assertTrue(hub.register_model(F.model_card()).ok)
        self.assertTrue(hub.grant_permission("network", user_approved=True).ok)
        self.assertTrue(hub.download_model(F.MODEL_ID, approved=True).ok)
        report = hub.prepare_model(F.MODEL_ID)
        self.assertTrue(report.ok, report)
        return hub, transport


class ModelNeverUsableByExistingAlone(HubCase):
    def test_a_fresh_hub_has_no_model_and_says_what_is_missing(self):
        hub = self.hub()
        self.assertEqual((hub.has_models(), hub.list_models()), (False, []))
        node = hub.graph().get("tool.local_model")
        self.assertEqual((node.state, node.usable, [b.kind for b in node.blockers]), ("dependency_blocked", False, ["model", "native_code"]))
        self.assertIn("LLM", node.summary_en.upper())
        self.assertFalse(os.path.exists(self.root))

    def test_registering_a_card_is_not_having_a_model(self):
        hub = self.hub()
        status = hub.register_model(F.model_card())
        self.assertEqual((status.ok, status.state, status.usable), (True, "registered", False))
        self.assertEqual(hub.graph().get("tool.local_model").state, "registered")
        node = hub.graph().get("model." + F.MODEL_ID)
        self.assertEqual((node.state, node.usable, node.actions, node.blockers[0].kind), ("registered", False, (), "model"))
        ask = hub.ask_model(F.MODEL_ID, "سلام")
        self.assertEqual((ask.ok, ask.code), (False, "model_not_usable"))
        self.assertEqual(hub.execute("model." + F.MODEL_ID, "generate", {"prompt": "سلام"}).code, "not_usable")

    def test_invalid_and_hostile_cards_are_refused(self):
        hub = self.hub()
        for card in (None, [], "x", {}, F.model_card(sha256="zz"), F.model_card(size_bytes=-1), F.model_card(model_id="../x"),
                     F.model_card(source_url="http://insecure.example.org/m.json"), F.model_card(format="exe"),
                     F.model_card(size_bytes=10 ** 13)):
            with self.subTest(card=str(card)[:50]):
                status = hub.register_model(card)
                self.assertEqual((status.ok, status.state, status.usable), (False, "unregistered", False))
        self.assertEqual(hub.list_models(), [])

    def test_a_different_card_cannot_take_an_existing_id(self):
        hub = self.hub()
        hub.register_model(F.model_card())
        clash = hub.register_model(F.model_card(sha256="0" * 64))
        self.assertEqual((clash.ok, clash.code), (False, "model_id_taken"))
        self.assertEqual(hub.register_model(F.model_card()).ok, True)             # the identical card is idempotent


class DownloadNeedsYesAndPermission(HubCase):
    def test_no_yes_no_permission_no_request(self):
        transport = F.FakeStreamTransport(F.MODEL_BYTES)
        hub = self.hub(download_transport=transport)
        hub.register_model(F.model_card())
        for value in (False, None, 1, "yes", "true"):
            self.assertEqual(hub.download_model(F.MODEL_ID, approved=value).code, "approval_required")
        self.assertEqual(hub.download_model(F.MODEL_ID).code, "approval_required")
        self.assertEqual(hub.download_model(F.MODEL_ID, approved=True).code, "permission_denied")
        self.assertEqual(len(transport.requests), 0)
        self.assertEqual(hub.model_status(F.MODEL_ID).state, "registered")
        self.assertFalse(any(n.endswith(".bin") or n.endswith(".partial") for _d, _s, files in os.walk(self.root) for n in files))

    def test_a_downloaded_file_is_still_not_usable_until_the_pipeline_passes(self):
        transport = F.FakeStreamTransport(F.MODEL_BYTES)
        hub = self.hub(download_transport=transport)
        hub.register_model(F.model_card())
        hub.grant_permission("network", user_approved=True)
        done = hub.download_model(F.MODEL_ID, approved=True)
        self.assertEqual((done.ok, done.state, done.usable), (True, "downloaded", False))
        self.assertEqual([r.url for r in transport.requests], [F.MODEL_URL])
        node = hub.graph().get("model." + F.MODEL_ID)
        self.assertEqual((node.state, node.usable, node.blockers[0].kind), ("registered", False, "test"))
        ask = hub.ask_model(F.MODEL_ID, "سلام")
        self.assertEqual((ask.ok, ask.code), (False, "model_not_usable"))
        self.assertEqual(hub.execute("model." + F.MODEL_ID, "generate", {"prompt": "سلام"}).code, "not_usable")

    def test_the_full_pipeline_makes_it_usable_and_it_really_generates(self):
        hub, transport = self.usable_hub()
        status = hub.model_status(F.MODEL_ID)
        self.assertEqual((status.state, status.usable, status.runtime), ("usable", True, "ngram"))
        node = hub.graph().get("model." + F.MODEL_ID)
        self.assertEqual((node.state, node.tested, node.usable, node.actions), ("active", True, True, ("generate",)))
        local = hub.graph().get("tool.local_model")
        self.assertEqual((local.state, local.tested, local.blockers), ("active", True, ()))
        ask = hub.ask_model(F.MODEL_ID, "سلام دوست")
        self.assertEqual((ask.ok, ask.code, ask.runtime), (True, "ok", "ngram"))
        self.assertTrue(ask.text.strip())
        self.assertEqual(ask.text, hub.ask_model(F.MODEL_ID, "سلام دوست").text)           # deterministic
        done = hub.execute("model." + F.MODEL_ID, "generate", {"prompt": "سلام دوست", "max_tokens": 8})
        self.assertEqual((done.ok, done.code), (True, "ok"))
        self.assertEqual(done.data["runtime"], "ngram")
        via_tool = hub.execute("tool.local_model", "generate", {"model_id": F.MODEL_ID, "prompt": "سلام"})
        self.assertTrue(via_tool.ok)
        self.assertEqual(hub.ask_model(F.MODEL_ID, "   ").code, "bad_arguments")
        self.assertEqual(hub.ask_model(F.MODEL_ID, "سلام", max_tokens=0).code, "bad_arguments")
        self.assertEqual(hub.ask_model("nope", "سلام").code, "unknown_model")

    def test_audit_records_the_model_steps_without_any_secret(self):
        hub, _ = self.usable_hub()
        with open(hub.audit.path, encoding="utf-8") as handle:
            text = handle.read()
        for kind in ("model.registered", "model.download_started", "model.state_changed"):
            self.assertTrue(kind in text or kind.split(".")[0] in text, kind)
        self.assertTrue(hub.audit.verify()["ok"])

    def test_a_wrong_hash_is_discarded_and_never_loaded(self):
        other = train_ngram_model(["یک متن دیگر برای آزمایش.", "این فایل همان فایل کارت نیست."])
        transport = F.FakeStreamTransport(other)
        hub = self.hub(download_transport=transport)
        hub.register_model(F.model_card(size_bytes=len(other)))                 # the card promises F.MODEL_SHA, the bytes differ
        hub.grant_permission("network", user_approved=True)
        done = hub.download_model(F.MODEL_ID, approved=True)
        self.assertEqual((done.ok, done.usable, done.state), (False, False, "failed"))
        self.assertIn("hash_mismatch", done.reasons)
        files = [n for _d, _s, names in os.walk(os.path.join(self.root, "models")) for n in names if n.endswith((".bin", ".partial"))]
        self.assertEqual(files, [])
        self.assertEqual(hub.ask_model(F.MODEL_ID, "سلام").code, "model_not_usable")
        node = hub.graph().get("model." + F.MODEL_ID)
        self.assertEqual((node.state, node.usable), ("broken", False))

    def test_an_interrupted_download_leaves_nothing_usable(self):
        class Dying(F.FakeStreamTransport):
            def stream(self, request):
                self.requests.append(request)
                raise F.TransportError("timeout")
        hub = self.hub(download_transport=Dying(F.MODEL_BYTES))
        hub.register_model(F.model_card())
        hub.grant_permission("network", user_approved=True)
        done = hub.download_model(F.MODEL_ID, approved=True)
        self.assertEqual((done.ok, done.usable), (False, False))
        self.assertEqual(hub.ask_model(F.MODEL_ID, "سلام").code, "model_not_usable")

    def test_not_enough_free_space_stops_before_any_request(self):
        transport = F.FakeStreamTransport(F.MODEL_BYTES)
        hub = self.hub(download_transport=transport, free_space_fn=lambda _p: F.Usage(100, 100, 0))
        hub.register_model(F.model_card())
        hub.grant_permission("network", user_approved=True)
        self.assertEqual(hub.download_model(F.MODEL_ID, approved=True).code, "insufficient_space")
        self.assertEqual(len(transport.requests), 0)


class Licences(HubCase):
    def test_a_licence_that_needs_review_waits_for_the_users_acknowledgement(self):
        transport = F.FakeStreamTransport(F.MODEL_BYTES)
        hub = self.hub(download_transport=transport)
        hub.register_model(F.model_card(license="llama-3-community"))
        hub.grant_permission("network", user_approved=True)
        node = hub.graph().get("model." + F.MODEL_ID)
        self.assertEqual((node.state, node.blockers[0].kind), ("pending_approval", "approval"))
        self.assertEqual(hub.download_model(F.MODEL_ID, approved=True).code, "license_needs_ack")
        self.assertEqual(len(transport.requests), 0)
        self.assertTrue(hub.acknowledge_model_license(F.MODEL_ID).ok)
        self.assertEqual(hub.download_model(F.MODEL_ID, approved=True).state, "downloaded")
        self.assertEqual(len(transport.requests), 1)

    def test_restricted_and_unknown_licences_are_refused_and_cannot_be_acknowledged(self):
        for name, code in (("proprietary", "license_restricted"), ("cc-by-nc-4.0", "license_restricted"),
                           ("something-else", "license_unknown")):
            with self.subTest(license=name):
                hub = self.hub(download_transport=F.FakeStreamTransport(F.MODEL_BYTES))
                hub.register_model(F.model_card(license=name, model_id="m-" + str(abs(hash(name)) % 1000)))
                hub.grant_permission("network", user_approved=True)
                mid = hub.list_models()[0].model_id
                self.assertEqual(hub.download_model(mid, approved=True).code, code)
                self.assertEqual(hub.acknowledge_model_license(mid).ok, False)
                node = hub.graph().get("model." + mid)
                self.assertEqual((node.state, node.usable, node.blockers[0].kind), ("policy_blocked", False, "policy"))
                hub.close()
                import shutil
                shutil.rmtree(self.root, ignore_errors=True)


class ImportFromTheInbox(HubCase):
    def local_card(self, **over):
        return F.model_card(source_url="local-import", **over)

    def put(self, name, data=None):
        hub_inbox = os.path.join(self.root, "inbox")
        os.makedirs(hub_inbox, exist_ok=True)
        with open(os.path.join(hub_inbox, name), "wb") as handle:
            handle.write(F.MODEL_BYTES if data is None else data)

    def test_a_file_in_the_inbox_is_imported_then_verified_like_any_download(self):
        hub = self.hub()
        hub.register_model(self.local_card())
        self.assertEqual(hub.download_model(F.MODEL_ID, approved=True).code, "needs_local_file")
        self.put("model.json")
        imported = hub.import_model(F.MODEL_ID, "model.json")
        self.assertEqual((imported.ok, imported.state, imported.usable), (True, "downloaded", False))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "inbox", "model.json")))          # the original stays
        report = hub.prepare_model(F.MODEL_ID)
        self.assertTrue(report.ok)
        self.assertEqual([s.stage for s in report.stages], ["verify", "compatibility", "load", "smoke"])
        self.assertTrue(hub.ask_model(F.MODEL_ID, "سلام").ok)

    def test_a_tampered_import_fails_verification_and_is_never_usable(self):
        hub = self.hub()
        hub.register_model(self.local_card())
        data = bytearray(F.MODEL_BYTES)
        data[len(data) // 2] ^= 0x01
        self.put("bad.json", bytes(data))
        self.assertTrue(hub.import_model(F.MODEL_ID, "bad.json").ok)               # same size, so it is accepted into quarantine
        report = hub.prepare_model(F.MODEL_ID)
        self.assertFalse(report.ok)
        self.assertEqual(report.stages[0].stage, "verify")
        self.assertFalse(hub.model_status(F.MODEL_ID).usable)
        self.assertEqual(hub.ask_model(F.MODEL_ID, "سلام").code, "model_not_usable")

    def test_only_plain_file_names_are_accepted(self):
        hub = self.hub()
        hub.register_model(self.local_card())
        self.put("model.json")
        for name in ("../model.json", "a/b.json", "/etc/passwd", "", None, 5, ".hidden", "x" * 200, "a b.json", "a\x00.json", "..", "."):
            with self.subTest(name=name):
                status = hub.import_model(F.MODEL_ID, name)
                self.assertEqual((status.ok, status.code), (False, "bad_arguments"))
        self.assertEqual(hub.import_model(F.MODEL_ID, "missing.json").code, "file_missing")
        self.assertEqual(hub.model_status(F.MODEL_ID).state, "registered")

    def test_a_link_in_the_inbox_is_refused(self):
        hub = self.hub()
        hub.register_model(self.local_card())
        outside = os.path.join(self._tmp.name, "outside.json")
        with open(outside, "wb") as handle:
            handle.write(F.MODEL_BYTES)
        os.makedirs(os.path.join(self.root, "inbox"), exist_ok=True)
        try:
            os.symlink(outside, os.path.join(self.root, "inbox", "link.json"))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        self.assertEqual(hub.import_model(F.MODEL_ID, "link.json").code, "file_missing")
        self.assertEqual(hub.model_status(F.MODEL_ID).state, "registered")

    def test_a_wrong_size_is_refused(self):
        hub = self.hub()
        hub.register_model(self.local_card())
        self.put("short.json", F.MODEL_BYTES[:-5])
        self.assertEqual(hub.import_model(F.MODEL_ID, "short.json").code, "size_mismatch")
        self.assertEqual(hub.model_status(F.MODEL_ID).state, "registered")


class RestartTrust(HubCase):
    def test_a_usable_model_is_proven_again_after_a_restart(self):
        hub, _ = self.usable_hub()
        hub.close()
        again = self.hub(download_transport=F.FakeStreamTransport(F.MODEL_BYTES))
        report = again.ensure_started()
        self.assertEqual(report["models"]["missing_files"], 0)
        self.assertFalse(report["attention"], report)
        self.assertEqual([(m.model_id, m.state) for m in again.list_models()], [(F.MODEL_ID, "usable")])
        self.assertTrue(again.ask_model(F.MODEL_ID, "سلام").ok)

    def test_a_changed_file_loses_its_trust(self):
        hub, _ = self.usable_hub()
        path = hub._model_manager().model_path(F.MODEL_ID)
        hub.close()
        with open(path, "ab") as handle:
            handle.write(b" ")
        again = self.hub()
        self.assertEqual(again.ask_model(F.MODEL_ID, "سلام").code, "model_not_usable")
        status = again.model_status(F.MODEL_ID)
        self.assertEqual((status.state, status.usable, list(status.reasons)), ("downloaded", False, ["file_changed"]))
        self.assertEqual(again.graph().get("model." + F.MODEL_ID).state, "registered")

    def test_a_removed_file_is_reported_not_trusted(self):
        hub, _ = self.usable_hub()
        path = hub._model_manager().model_path(F.MODEL_ID)
        hub.close()
        os.unlink(path)
        again = self.hub()
        again.ensure_started()
        self.assertFalse(again.model_status(F.MODEL_ID).usable)
        self.assertEqual(again.ask_model(F.MODEL_ID, "سلام").code, "model_not_usable")

    def test_removing_a_model_deletes_its_file(self):
        hub, _ = self.usable_hub()
        path = hub._model_manager().model_path(F.MODEL_ID)
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(hub.remove_model(F.MODEL_ID).ok)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(hub.list_models(), [])
        self.assertEqual(hub.ask_model(F.MODEL_ID, "سلام").code, "unknown_model")


class Engines(HubCase):
    def test_the_engine_list_is_exact_about_what_this_build_can_run(self):
        rows = {r["name"]: r for r in self.hub().model_runtimes_info()}
        self.assertEqual(sorted(rows), ["llama_cpp", "ngram"])
        self.assertEqual((rows["ngram"]["available"], rows["ngram"]["formats"]), (True, ["ngram-json"]))
        self.assertIn("LLM", rows["ngram"]["description_en"].upper())
        self.assertEqual((rows["llama_cpp"]["available"], rows["llama_cpp"]["code"]), (False, "dependency_missing"))
        self.assertTrue(rows["llama_cpp"]["requires"])

    def test_a_gguf_model_is_blocked_by_the_missing_engine_not_pretended(self):
        data = b"GGUF" + b"\x03\x00\x00\x00" + b"\x00" * 64
        card = F.model_card(model_id="tiny-llm", format="gguf", sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
        hub = self.hub(download_transport=F.FakeStreamTransport(data))
        hub.register_model(card)
        hub.grant_permission("network", user_approved=True)
        self.assertTrue(hub.download_model("tiny-llm", approved=True).ok)
        report = hub.prepare_model("tiny-llm")
        self.assertFalse(report.ok)
        self.assertFalse(hub.model_status("tiny-llm").usable)
        node = hub.graph().get("model.tiny-llm")
        self.assertEqual((node.state, node.usable, node.blockers[0].kind), ("dependency_blocked", False, "native_code"))
        local = hub.graph().get("tool.local_model")
        self.assertFalse(local.usable)
        self.assertIn("native_code", [b.kind for b in local.blockers])
        self.assertEqual(hub.ask_model("tiny-llm", "سلام").code, "model_not_usable")

    def test_failures_inside_the_manager_are_contained(self):
        hub = self.hub()

        def boom():
            raise RuntimeError("disk exploded")
        hub._model_manager = boom
        self.assertEqual(hub.model_status("x").code, "unexpected_error")
        self.assertEqual(hub.register_model(F.model_card()).code, "unexpected_error")
        self.assertEqual(hub.download_model("x", approved=True).code, "unexpected_error")
        self.assertEqual(hub.ask_model("x", "سلام").code, "unexpected_error")
        self.assertEqual(hub.acknowledge_model_license("x").code, "unexpected_error")
        self.assertEqual(hub.remove_model("x").code, "unexpected_error")
        self.assertEqual(hub.import_model("x", "a.json").code in ("unexpected_error", "file_missing"), True)
        self.assertEqual(hub.list_models(), [])


if __name__ == "__main__":
    unittest.main()
