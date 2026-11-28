"""
Prompt 959 (stage B3, «مغز خودکار») - what «مغز را دوباره امتحان کن» says it does is what it does, and a blocked download names the address.

Found on a real phone (a VPN switched on): the download stopped with `blocked_address`; the user said «مغز را دوباره امتحان کن» and the app answered
"I check the file again..." and showed the phase "installing" - while it was really downloading the file again, because the earlier download had never
finished. Pinned here (the download and the engine are fakes):

* a retry whose file is NOT on the phone is in the phase "downloading" and says it downloads again; a retry whose file IS on the phone is in the phase
  "installing", downloads nothing and says so; a retry that finds the stored file unusable and has to download after all flips the phase before it does;
* `OwnBrain.file_on_phone()` tells the chat which of the two it is, before the retry starts;
* `blocked_address` is followed by the address(es) the phone's name lookup gave for the model's site - the cause cannot be seen otherwise (a VPN's fake
  address, the provider's block page, ...) - found by one more lookup of the catalog's own host, only while the internet switch is on, never raising;
* the failure's words say what that usually means and what to try, and never claim to know the cause.
"""
import os
import re
import sys
import unittest
from types import SimpleNamespace

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import ownbrain_catalog as catalog
from brain_hub.ownbrain import OwnBrain, StartResult
from persian_brain import hub_messages_ownbrain as BM
from tests.ownbrain_support_prompt959 import LIGHT_DATA, OwnBrainApp, tiny_choice


def answer(*ips):
    """What `getaddrinfo` returns for these addresses."""
    return lambda host, port, type=0: [((10 if ":" in ip else 2), 1, 6, "", (ip, port)) for ip in ips]


def failing(code="blocked_address", detail="private"):
    return lambda *_args, **_kw: SimpleNamespace(ok=False, code=code, detail=detail)


class Base(OwnBrainApp):
    def wish(self):
        self.ask("مغز خودت را بگیر")
        self.ask("سبک")
        return self.ask("بله")

    def failed_load(self):
        """The file was fetched and stored, only the engine could not load it."""
        self.bridge.load_result = "ERR\nengine_load_failed\nout of memory"
        self.wish()
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"]), ("failed", "engine_load_failed"))
        self.bridge.load_result = "OK\nloaded"

    def spy_phase(self, then=None):
        """Replace the downloader: records the phase at the moment a download starts, then answers with `then` (default: the real downloader)."""
        real, seen = self.ob._downloader, []

        def spy(*args, **kwargs):
            seen.append(self.ob.status()["phase"])
            return then(*args, **kwargs) if then is not None else real(*args, **kwargs)

        self.ob._downloader = spy
        return seen


class RetryPhaseTests(Base):
    def test_a_retry_that_has_to_download_again_is_in_the_downloading_phase(self):
        seen = self.spy_phase(then=failing())
        self.ob._resolver = answer()
        self.wish()
        self.assertEqual((self.ob.status()["phase"], self.ob.status()["code"]), ("failed", "blocked_address"))
        self.assertFalse(self.ob.file_on_phone())
        self.assertEqual(self.ob.retry(), StartResult(True, "started"))
        self.assertEqual(seen, ["downloading", "downloading"], "the retry fetches the file again, so it must not call itself «installing»")

    def test_a_retry_with_the_file_on_the_phone_is_in_the_installing_phase_and_downloads_nothing(self):
        self.failed_load()
        self.assertTrue(self.ob.file_on_phone())
        requests, phases, real = len(self.cdn.requests), [], self.hub.prepare_model

        def spy(model_id, progress=None):
            phases.append(self.ob.status()["phase"])
            return real(model_id, progress)

        self.hub.prepare_model = spy
        self.addCleanup(lambda: delattr(self.hub, "prepare_model"))
        self.assertEqual(self.ob.retry(), StartResult(True, "started"))
        self.assertEqual(phases, ["installing"])
        self.assertEqual(len(self.cdn.requests), requests, "nothing was downloaded")
        self.assertEqual(self.ob.status()["phase"], "ready")

    def test_the_retry_itself_names_the_phase_before_the_worker_has_run(self):
        """The chat and the notification read the status the moment `retry` returns, before the worker has done anything (the worker's own flip to
        «downloading» comes later). The worker is held back here, so what is seen is only what `retry` itself wrote."""
        self.seed_download(phase="failed", code="blocked_address", partial=30_000)
        self.start_app()
        self.switch_internet(True)
        self.ob._launch = lambda _choice: None
        self.assertFalse(self.ob.file_on_phone())
        self.assertEqual(self.ob.retry(), StartResult(True, "started"))
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"], st["detail"]), ("downloading", "", ""), "a download again, from the first instant")
        self.assertEqual(st["bytes"], 30_000, "and what the earlier try had fetched is shown, not zero")

    def test_the_retry_of_an_installed_file_names_the_install_before_the_worker_has_run(self):
        self.failed_load()
        self.ob._launch = lambda _choice: None
        self.assertTrue(self.ob.file_on_phone())
        self.assertEqual(self.ob.retry(), StartResult(True, "started"))
        st = self.ob.status()
        self.assertEqual((st["phase"], st["code"], st["detail"]), ("installing", "", ""))
        self.assertEqual(st["bytes"], len(LIGHT_DATA), "the file is whole: nothing is shown as missing")

    def test_a_stored_file_that_cannot_be_reopened_is_fetched_again_under_the_right_name(self):
        self.failed_load()
        path = self.hub.model_file_path(tiny_choice("light").model_id)
        with open(path, "r+b") as handle:                                   # a file of the wrong size cannot be reopened for the checks
            handle.truncate(len(LIGHT_DATA) - 1)
        seen = self.spy_phase()
        self.assertEqual(self.ob.retry(), StartResult(True, "started"))
        self.assertEqual(seen, ["downloading"], "the pipeline had to download after all, and the phase says so before it does")
        self.assertEqual(self.ob.status()["phase"], "ready")

    def test_file_on_phone_follows_the_files_life(self):
        self.assertFalse(self.ob.file_on_phone(), "no brain chosen yet")
        self.assertFalse(self.ob.file_on_phone(self.ob.choice("light")), "chosen but not fetched")
        self.failed_load()
        self.assertTrue(self.ob.file_on_phone())
        self.assertTrue(self.ob.file_on_phone(self.ob.choice("light")))
        self.assertFalse(self.ob.file_on_phone(self.ob.choice("strong")), "the other brain was never fetched")
        os.remove(self.hub.model_file_path(tiny_choice("light").model_id))
        self.assertFalse(self.ob.file_on_phone(), "the file is gone")

    def test_file_on_phone_never_raises(self):
        self.ob._hub = SimpleNamespace(model_status=lambda _id: 1 / 0, root=self.ob._hub.root)
        self.assertFalse(self.ob.file_on_phone(tiny_choice("light")))
        self.assertFalse(self.ob.file_on_phone(None))


class RetryWordsTests(Base):
    def test_the_three_texts_say_three_different_things(self):
        install, download, both = BM.retry_started("install"), BM.retry_started("download"), BM.retry_started()
        self.assertEqual(len({install, download, both}), 3)
        self.assertIn("دوباره دانلودش نمی‌کنم", install)
        self.assertIn("از نو بررسی", install)
        self.assertIn("دانلود را دوباره شروع می‌کنم", download)
        self.assertNotIn("از نو بررسی", download, "nothing is re-checked when the file is not even on the phone")
        self.assertIn("دانلودِ قبلی تمام نشد", download)
        self.assertTrue(both.startswith("دوباره امتحان می‌کنم:"))
        for text in (install, download, both):
            self.assertNotIn("«", text, "no new quoted word that the chat would have to understand")

    def test_an_unknown_kind_gives_the_text_that_says_both(self):
        for kind in ("", None, "other", 5):
            self.assertEqual(BM.retry_started(kind), BM.retry_started())

    def test_the_chat_says_install_when_the_file_is_on_the_phone(self):
        self.failed_load()
        requests = len(self.cdn.requests)
        reply = self.ask(BM.RETRY)
        self.assertTrue(reply.startswith(BM.retry_started("install")), reply)
        self.assertNotIn(BM.retry_started("download"), reply)
        self.assertIn("آماده است", reply)
        self.assertEqual(len(self.cdn.requests), requests)

    def test_the_chat_says_download_when_the_file_is_not_on_the_phone(self):
        seen = self.spy_phase()
        real = self.ob._downloader
        first = {"done": False}

        def blocked_once(*args, **kwargs):
            if not first["done"]:
                first["done"] = True
                seen.append(self.ob.status()["phase"])
                return SimpleNamespace(ok=False, code="blocked_address", detail="private")
            return real(*args, **kwargs)

        self.ob._downloader = blocked_once
        self.ob._resolver = answer("198.18.0.9")
        self.wish()
        self.assertEqual(self.ob.status()["code"], "blocked_address")
        reply = self.ask(BM.RETRY)
        self.assertTrue(reply.startswith(BM.retry_started("download")), reply)
        self.assertNotIn(BM.retry_started("install"), reply)
        self.assertEqual(self.ob.status()["phase"], "ready", "the second try went through (the scripted download works)")

    def test_the_started_text_no_longer_denies_the_notification(self):
        text = BM.started(self.ob.choice("light"))
        self.assertNotIn("هنوز در پس‌زمینه با اعلانِ ثابت ادامه نمی‌دهم", text)
        self.assertIn("اعلانِ ثابت", text)
        self.assertIn("اگر اجازهٔ اعلان داده باشی", text)
        self.assertIn("دفعهٔ بعد که بازش کنی از همان‌جا ادامه می‌دهم", text, "what happens when Android closes the app is still said")


class BlockedDetailTests(Base):
    def brain(self, downloader=None, resolver=None):
        brain = OwnBrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=False, idle_unload_seconds=0, sleep=lambda _s: None,
                         downloader=downloader or failing(), resolver=resolver)
        self.addCleanup(brain._install_end)
        return brain

    def test_the_address_the_lookup_gave_is_written_after_the_class_word(self):
        brain = self.brain(resolver=answer("198.18.0.5"))
        brain.start("light", consent=True)
        st = brain.status()
        self.assertEqual((st["phase"], st["code"], st["detail"]), ("failed", "blocked_address", "private ip=198.18.0.5"))

    def test_only_the_non_public_addresses_and_at_most_two(self):
        brain = self.brain(resolver=answer("93.184.216.34", "10.10.34.34", "10.10.34.35", "10.10.34.36", "10.10.34.34"))
        brain.start("light", consent=True)
        self.assertEqual(brain.status()["detail"], "private ip=10.10.34.34,10.10.34.35")

    def test_ipv6_is_written_without_its_zone_and_the_detail_stays_short(self):
        brain = self.brain(resolver=lambda *_a, **_k: [(10, 1, 6, "", ("fe80::1%wlan0", 443, 0, 0)),
                                                       (10, 1, 6, "", ("2001:db8:aaaa:bbbb:cccc:dddd:eeee:ffff", 443, 0, 0))])
        brain.start("light", consent=True)
        detail = brain.status()["detail"]
        self.assertEqual(detail, "private ip=fe80::1,2001:db8:aaaa:bbbb:cccc:dddd:eeee:ffff")
        self.assertLessEqual(len(detail), 120)

    def test_an_answer_that_is_now_all_public_leaves_the_detail_as_it_was(self):
        brain = self.brain(resolver=answer("93.184.216.34", "2606:4700::1111"))
        brain.start("light", consent=True)
        self.assertEqual(brain.status()["detail"], "private")

    def test_a_lookup_that_fails_or_answers_garbage_leaves_the_detail_as_it_was(self):
        def boom(*_a, **_k):
            raise OSError("no network")

        for resolver in (boom, lambda *_a, **_k: [], lambda *_a, **_k: [("x",)], lambda *_a, **_k: None, lambda *_a, **_k: [(2, 1, 6, "", ())]):
            with self.subTest(resolver=getattr(resolver, "__name__", "?")):
                brain = self.brain(resolver=resolver)
                brain.start("light", consent=True)
                st = brain.status()
                self.assertEqual((st["phase"], st["code"], st["detail"]), ("failed", "blocked_address", "private"))

    def test_with_the_internet_switch_off_no_lookup_is_made(self):
        calls = []
        brain = self.brain(resolver=lambda *a, **k: calls.append(a) or [])
        self.switch_internet(False)
        self.assertEqual(brain._blocked_detail(tiny_choice("light"), "private"), "private")
        self.assertEqual(calls, [], "the app's own internet switch also covers this one lookup")

    def test_only_the_catalogs_own_host_is_ever_looked_up(self):
        calls = []
        brain = self.brain(resolver=lambda *a, **k: calls.append(a) or [])
        self.switch_internet(True)
        brain._blocked_detail(tiny_choice("light", url="https://evil.example/resolve/main/x.litertlm"), "private")
        self.assertEqual(calls, [])
        brain._blocked_detail(tiny_choice("light"), "private")
        self.assertEqual([call[0] for call in calls], ["huggingface.co"])
        self.assertIn("huggingface.co", catalog.ALLOWED_HOSTS)

    def test_no_other_failure_triggers_a_lookup(self):
        calls = []
        for code, detail in (("http_error", "503"), ("hash_mismatch", ""), ("tls_error", "certificate")):
            with self.subTest(code=code):
                brain = self.brain(downloader=failing(code, detail), resolver=lambda *a, **k: calls.append(a) or [])
                brain.start("light", consent=True)
                st = brain.status()
                self.assertEqual((st["code"], st["detail"]), (code, detail))
        self.assertEqual(calls, [])

    def test_a_peer_refusal_keeps_its_class_word_in_front(self):
        brain = self.brain(downloader=failing(detail="peer_private"), resolver=answer("10.0.0.7"))
        brain.start("light", consent=True)
        self.assertEqual(brain.status()["detail"], "peer_private ip=10.0.0.7")

    def test_the_resolver_is_asked_for_the_site_on_the_https_port(self):
        calls = []
        brain = self.brain(resolver=lambda *a, **k: calls.append((a, k)) or [])
        self.switch_internet(True)
        brain._blocked_detail(tiny_choice("light"), "private")
        (args, kwargs), = calls
        self.assertEqual(args, ("huggingface.co", 443))
        self.assertEqual(kwargs, {"type": 1}, "a stream (TCP) lookup")


class BlockedWordsTests(Base):
    def test_the_failure_names_the_address_the_cause_and_what_to_try(self):
        text = BM.failure_text("blocked_address", "private ip=198.18.0.5")
        for part in ("huggingface.co", "198.18.0.5", "آدرسِ داخلی", "فیلترشکن", "DNS", "blocked_address private 198.18.0.5", BM.RETRY):
            self.assertIn(part, text)
        self.assertIn("با آدرسِ بالا", text)
        self.assertIn("اغلب علتش", text, "it says what is usual, it does not claim to know")
        self.assertNotIn("حتماً", text)

    def test_without_an_address_it_does_not_point_at_one(self):
        text = BM.failure_text("blocked_address", "private")
        self.assertNotIn("با آدرسِ بالا", text)
        self.assertNotIn("آدرسی که گرفت", text)
        self.assertIn("blocked_address private)", text)
        self.assertEqual(BM.failure_text("blocked_address", ""), BM.failure_text("blocked_address"))

    def test_two_addresses_and_the_end_of_the_sentence(self):
        text = BM.failure_text("blocked_address", "private ip=10.10.34.34,10.10.34.35", next_step=False)
        self.assertIn("10.10.34.34، 10.10.34.35", text)
        self.assertNotIn(BM.RETRY, text, "no retry advice when the caller says the next step is elsewhere")

    def test_no_quoted_word_is_new_and_garbage_in_the_detail_cannot_break_it(self):
        for detail in ("private ip=198.18.0.5", "", "ip=", " ip=,,", "x" * 500, None, 5):
            with self.subTest(detail=str(detail)[:20]):
                text = BM.failure_text("blocked_address", detail)
                self.assertIsInstance(text, str)
                self.assertTrue(set(re.findall("«([^»]+)»", text)) <= {BM.RETRY}, text)

    def test_the_status_and_the_chat_show_it_with_the_address(self):
        self.ob._downloader = failing()
        self.ob._resolver = answer("198.18.0.9")
        self.wish()
        text = self.ask("وضعیت مغز")
        self.assertIn("198.18.0.9", text)
        self.assertIn("blocked_address", text)
        self.assertIn(BM.RETRY, text)
        self.assertNotIn("کار با کدِ", text, "no longer the generic «stopped with code» sentence")


if __name__ == "__main__":
    unittest.main()
