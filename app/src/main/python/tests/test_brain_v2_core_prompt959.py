"""Prompt 959 (stage A) - the cloud brain core: settings, key vault, privacy filter, history, request building, failure reasons.

Nothing here touches the network: a scripted fake transport plays the provider. The assertions that matter most are the NEGATIVE
ones - what must not be sent, stored or logged.
"""
import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_v2 import BrainV2, cloud, get_brain, persona, privacy, providers, reset_brain
from brain_v2.history import MAX_TURNS, TTL_SECONDS, History
from brain_v2.keyvault import KeyVault, mask
from brain_v2.service import MAX_CALLS_PER_HOUR, MAX_QUESTION_CHARS
from brain_v2.settings import Settings
from net_tools import TransportError, TransportResponse

KEY = "AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q"
JSON = {"content-type": "application/json"}


def openai_answer(text="سلام! چطور کمکت کنم؟", finish="stop"):
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}]},
                      ensure_ascii=False).encode("utf-8")


class FakeAudit:
    def __init__(self):
        self.lines = []

    def append(self, kind, subject="", detail=None):
        self.lines.append((kind, subject, dict(detail or {})))


class Fake:
    """A scripted provider: `script` is a list of (status, body, headers) / Exception / callable(request); the last one repeats."""

    def __init__(self, *script):
        self.script, self.calls = list(script) or [(200, openai_answer(), JSON)], []

    def __call__(self, request):
        self.calls.append(request)
        item = self.script[min(len(self.calls), len(self.script)) - 1]
        if callable(item) and not isinstance(item, tuple):
            item = item(request)
        if isinstance(item, Exception):
            raise item
        status, body, headers = item
        return TransportResponse(status, headers, body, False, "142.250.1.1")


class Clock:
    def __init__(self, now=1_700_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class BrainCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "brain_v2")
        self.net = {"on": True}
        self.audit = FakeAudit()
        self.clock, self.mono = Clock(), Clock(1000.0)

    def make(self, *script, **kw):
        self.fake = Fake(*script)
        kw.setdefault("transport", self.fake)
        return BrainV2(self.root, network_granted=lambda: self.net["on"], audit=self.audit, clock=self.clock,
                       monotonic=self.mono, **kw)

    def ready_brain(self, *script, provider="gemini", base="", key=KEY):
        brain = self.make(*script)
        brain.choose_provider(provider, base)
        brain.give_consent()
        self.assertTrue(brain.set_key(key))
        brain.set_mode("auto")
        return brain

    def every_text_file(self):
        out = {}
        for folder, _, names in os.walk(self.root):
            for name in names:
                with open(os.path.join(folder, name), "rb") as handle:
                    out[name] = handle.read().decode("utf-8", "replace")
        return out


class OffByDefaultTests(BrainCase):
    def test_a_fresh_brain_is_off_sends_nothing_and_writes_nothing(self):
        brain = self.make()
        self.assertEqual(brain.ready(), (False, "off"))
        reply = brain.reply("پایتخت فرانسه کجاست؟")
        self.assertEqual((reply.kind, reply.code), ("not_ready", "off"))
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(os.path.exists(self.root), "asking while off must not create any file")
        st = brain.status()
        self.assertEqual((st["mode"], st["provider"], st["key"], st["consent"], st["ready"]), ("off", "", "", False, False))

    def test_every_missing_condition_blocks_with_its_own_reason(self):
        brain = self.make()
        brain.choose_provider("gemini")
        brain.settings.update(mode="auto")
        self.assertEqual(brain.ready(), (False, "no_consent"))
        brain.give_consent()
        self.assertEqual(brain.ready(), (False, "no_key"))
        brain.set_key(KEY)
        self.net["on"] = False
        self.assertEqual(brain.ready(), (False, "no_network"))
        self.net["on"] = True
        self.assertEqual(brain.ready(), (True, "ok"))
        brain.set_mode("local")
        self.assertEqual(brain.ready(), (False, "local"))
        brain.set_mode("auto")
        brain.halt()
        self.assertEqual(brain.ready(), (False, "halted"))
        self.assertEqual(brain.reply("سلام").kind, "halted")
        brain.resume()
        self.assertEqual(brain.ready(), (True, "ok"))
        self.assertEqual(self.fake.calls, [])

    def test_the_network_gate_is_checked_again_at_the_moment_of_the_call(self):
        brain = self.ready_brain()
        self.net["on"] = False                       # the user switched the internet off after the readiness check
        result = brain._call(persona.system_prompt(), [{"role": "user", "content": "x"}], max_tokens=10, temperature=0.1, what="ask")
        self.assertEqual((result.ok, result.code), (False, "blocked"))
        self.assertEqual(self.fake.calls, [])

    def test_consent_is_bound_to_the_host(self):
        brain = self.ready_brain()
        self.assertTrue(brain._consent_ok())
        brain.choose_provider("openai")              # another host: the old «بله» does not count
        st = brain.status()
        self.assertEqual((st["consent"], st["mode"], st["ready"]), (False, "off", False))
        brain.settings.update(consent={"host": "evil.example.com", "ts": 1.0, "provider": "openai"}, mode="auto")
        self.assertFalse(brain._consent_ok(), "a consent for another host must not unlock this one")
        self.assertEqual(brain.reply("سلام").kind, "not_ready")
        self.assertEqual(self.fake.calls, [])

    def test_choosing_the_same_host_again_keeps_the_consent(self):
        brain = self.ready_brain()
        brain.choose_provider("gemini")
        self.assertTrue(brain.status()["consent"])


class RequestShapeTests(BrainCase):
    def test_gemini_request(self):
        brain = self.ready_brain()
        reply = brain.reply("پایتخت فرانسه کجاست؟")
        self.assertEqual((reply.kind, reply.source, reply.text), ("answer", "cloud", "سلام! چطور کمکت کنم؟"))
        req = self.fake.calls[0]
        self.assertEqual((req.method, req.host, req.path_query), ("POST", "generativelanguage.googleapis.com", "/v1beta/openai/chat/completions"))
        self.assertEqual(req.headers["Authorization"], "Bearer " + KEY)
        payload = json.loads(req.body.decode("utf-8"))
        self.assertEqual(payload["model"], "gemini-3.8-flash")
        self.assertEqual([m["role"] for m in payload["messages"]], ["system", "user"])
        self.assertEqual(payload["messages"][1]["content"], "پایتخت فرانسه کجاست؟")
        self.assertIn("max_tokens", payload)
        self.assertIn("temperature", payload)
        self.assertNotIn("stream", payload)
        self.assertIn("هرگز خودت را انسان معرفی نکن", payload["messages"][0]["content"])

    def test_openai_request_uses_the_newer_token_field_and_no_temperature(self):
        brain = self.ready_brain(provider="openai")
        brain.reply("سلام دنیا")
        payload = json.loads(self.fake.calls[0].body.decode("utf-8"))
        self.assertEqual(self.fake.calls[0].host, "api.openai.com")
        self.assertIn("max_completion_tokens", payload)
        self.assertNotIn("max_tokens", payload)
        self.assertNotIn("temperature", payload)

    def test_anthropic_request(self):
        body = json.dumps({"content": [{"type": "text", "text": "درود"}], "stop_reason": "end_turn"}).encode()
        brain = self.ready_brain((200, body, JSON), provider="anthropic")
        reply = brain.reply("سلام")
        self.assertEqual((reply.kind, reply.text), ("answer", "درود"))
        req = self.fake.calls[0]
        self.assertEqual((req.host, req.path_query), ("api.anthropic.com", "/v1/messages"))
        self.assertEqual((req.headers["x-api-key"], req.headers["anthropic-version"]), (KEY, "2023-06-01"))
        self.assertNotIn("Authorization", req.headers)
        payload = json.loads(req.body.decode("utf-8"))
        self.assertIn("system", payload)
        self.assertEqual([m["role"] for m in payload["messages"]], ["user"])

    def test_custom_provider_uses_only_the_validated_https_base(self):
        brain = self.ready_brain(provider="custom", base="https://api.together.xyz/v1")
        brain.settings.update(model="meta/llama-x")
        brain.reply("سلام")
        req = self.fake.calls[0]
        self.assertEqual((req.host, req.path_query), ("api.together.xyz", "/v1/chat/completions"))
        self.assertEqual(json.loads(req.body.decode("utf-8"))["model"], "meta/llama-x")
        for bad in ("http://api.example.com/v1", "https://127.0.0.1/v1", "https://localhost/v1", "https://user:pw@api.example.com/",
                    "https://api.example.com:8443/v1", "https://api.example.com/v1?x=1", "ftp://x.example.com", "api", "", "https://nodot/v1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.make().choose_provider("custom", bad)

    def test_the_second_question_carries_the_first_exchange(self):
        brain = self.ready_brain((200, openai_answer("پاریس"), JSON), (200, openai_answer("حدود ۲ میلیون نفر"), JSON))
        brain.reply("پایتخت فرانسه کجاست؟")
        brain.reply("و جمعیتش؟")
        payload = json.loads(self.fake.calls[1].body.decode("utf-8"))
        self.assertEqual([(m["role"], m["content"]) for m in payload["messages"][1:]],
                         [("user", "پایتخت فرانسه کجاست؟"), ("assistant", "پاریس"), ("user", "و جمعیتش؟")])
        self.assertEqual(brain.clear_history(), 2)
        self.assertEqual(brain.history.count(), 0)

    def test_a_default_model_is_used_until_the_user_sets_one(self):
        brain = self.ready_brain()
        self.assertEqual((brain.model(), brain.status()["model_is_default"]), ("gemini-3.8-flash", True))
        brain.set_model("gemini-9-pro")
        self.assertEqual((brain.model(), brain.status()["model_is_default"]), ("gemini-9-pro", False))
        brain.set_model("")
        self.assertEqual(brain.model(), "gemini-3.8-flash")
        for bad in ("a b", "x;y", "m" * 100, "../x", "مدل"):
            with self.assertRaises(ValueError):
                brain.set_model(bad)


class PrivacyAtTheGateTests(BrainCase):
    def test_a_secret_is_never_sent_stored_or_logged_whatever_the_settings(self):
        brain = self.ready_brain()
        brain.set_share_private(True)
        for text, kind in (("شماره کارتم 6037-9975-1234-5678 است", "card"), ("رمز پویا ۱۲۳۴۵۶ را وارد کردم", "credential"),
                           ("کلیدم sk-proj-abcdefghijklmnopqrstuvwxyz123456 است", "key")):
            with self.subTest(kind=kind):
                reply = brain.reply(text)
                self.assertEqual((reply.kind, reply.code, reply.secret), ("blocked", kind, True))
                self.assertNotIn("6037", reply.label_fa)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(brain.history.count(), 0)
        blob = json.dumps(self.audit.lines, ensure_ascii=False)
        for secret in ("6037", "123456", "sk-proj"):
            self.assertNotIn(secret, blob)
        self.assertTrue(all(kind == "brain.blocked" or kind.startswith("brain.") for kind, _, _ in self.audit.lines))

    def test_personal_details_wait_for_the_users_permission(self):
        brain = self.ready_brain()
        text = "ایمیلم test.user@example.com است، یادداشتش کن"
        self.assertEqual((brain.reply(text).kind, brain.reply(text).secret), ("blocked", False))
        self.assertEqual(self.fake.calls, [])
        brain.set_share_private(True)
        self.assertEqual(brain.reply(text).kind, "answer")
        self.assertEqual(len(self.fake.calls), 1)

    def test_a_too_long_message_stays_home(self):
        brain = self.ready_brain()
        self.assertEqual(brain.reply("سلام " * (MAX_QUESTION_CHARS // 3)).kind, "too_long")
        self.assertEqual(self.fake.calls, [])


class FailureReasonTests(BrainCase):
    def reply_to(self, status, body=b"", headers=JSON):
        brain = self.ready_brain((status, body, headers))
        reply = brain.reply("یک سؤال معمولی")
        self.assertEqual(brain.history.count(), 0, "a failed exchange must not be remembered")
        return reply

    def test_http_failures_get_their_own_code_and_a_plain_reason(self):
        cases = [(401, "bad_key", "کلید"), (403, "bad_key", "کلید"), (404, "no_model", "gemini-3.8-flash"), (429, "quota", "اعتبار"),
                 (402, "quota", "اعتبار"), (503, "provider_down", "۵۰۳"), (500, "provider_down", "۵۰۰"), (400, "bad_request", "نپذیرفت")]
        for status, code, word in cases:
            with self.subTest(status=status):
                reply = self.reply_to(status, json.dumps({"error": {"message": "boom"}}).encode())
                self.assertEqual((reply.kind, reply.code), ("failed", code))
                self.assertIn(word, reply.reason_fa)
                self.assertEqual(reply.detail, "boom")

    def test_region_and_unknown_model_messages_are_recognised_from_the_providers_text(self):
        reply = self.reply_to(400, json.dumps({"error": {"message": "User location is not supported for the API use."}}).encode())
        self.assertEqual(reply.code, "region")
        reply = self.reply_to(400, json.dumps({"error": {"message": "The model `x` does not exist"}}).encode())
        self.assertEqual(reply.code, "no_model")

    def test_the_providers_error_text_never_carries_the_key(self):
        body = json.dumps({"error": {"message": "Incorrect API key provided: %s" % KEY}}).encode()
        reply = self.reply_to(401, body)
        self.assertNotIn(KEY, reply.detail + reply.reason_fa)
        self.assertNotIn(KEY[:8], reply.detail)

    def test_network_failures(self):
        for exc, code in ((TransportError("timeout"), "timeout"), (TransportError("offline"), "unreachable"),
                          (TransportError("dns_failure"), "unreachable"), (TransportError("connect_refused"), "unreachable"),
                          (TransportError("tls_error"), "unreachable")):
            with self.subTest(code=code):
                brain = self.ready_brain(exc)
                reply = brain.reply("یک سؤال معمولی")
                self.assertEqual((reply.kind, reply.code), ("failed", code))
                self.assertTrue(reply.reason_fa)
        self.assertIn("فیلترشکن", cloud.reason("unreachable")[0])

    def test_odd_answers(self):
        cases = [((200, b"not json", JSON), "bad_answer"), ((200, b'{"choices":[]}', JSON), "bad_answer"),
                 ((200, b'{"choices":[{"message":{"content":""}}]}', JSON), "empty"),
                 ((200, b'{"choices":[{"message":{"content":null}}]}', JSON), "empty"),
                 ((200, b'{"x":1}', JSON), "bad_answer"), ((200, b"<html></html>", {"content-type": "text/html"}), "bad_answer"),
                 ((302, b"", {"location": "https://evil.example/"}), "bad_request")]
        for item, code in cases:
            with self.subTest(code=code, body=item[1][:20]):
                brain = self.ready_brain(item)
                reply = brain.reply("یک سؤال معمولی")
                self.assertEqual((reply.kind, reply.code), ("failed", code))
        self.assertEqual(len(self.fake.calls), 1, "a redirect must never be followed")

    def test_content_as_parts_and_the_length_flag(self):
        body = json.dumps({"choices": [{"message": {"content": [{"type": "text", "text": "الف"}, {"type": "text", "text": "ب"}]},
                                        "finish_reason": "length"}]}).encode()
        reply = self.ready_brain((200, body, JSON)).reply("سؤال")
        self.assertEqual((reply.kind, reply.text, reply.truncated), ("answer", "الفب", True))

    def test_markdown_noise_is_removed_from_the_answer(self):
        text = "## عنوان\n**مهم** است\n* یک\n* دو\n```\nکد\n```\n\n\n\nپایان"
        reply = self.ready_brain((200, openai_answer(text), JSON)).reply("سؤال")
        self.assertEqual(reply.text, "عنوان\nمهم است\n• یک\n• دو\n\nکد\n\nپایان")
        self.assertLessEqual(len(cloud.plain("ا" * 20000)), cloud.MAX_ANSWER_CHARS + 1)

    def test_probe_counts_an_empty_answer_with_a_good_status_as_working(self):
        brain = self.ready_brain((200, b'{"choices":[{"message":{"content":""},"finish_reason":"length"}]}', JSON))
        self.assertTrue(brain.probe().ok)
        brain = self.ready_brain((401, b"{}", JSON))
        result = brain.probe()
        self.assertEqual((result.ok, result.code), (False, "bad_key"))


class RateCapTests(BrainCase):
    def test_the_hourly_cap_and_its_reset(self):
        brain = self.ready_brain()
        for _ in range(MAX_CALLS_PER_HOUR):
            self.assertEqual(brain.reply("سؤال معمولی").kind, "answer")
        self.assertEqual(brain.reply("سؤال معمولی").kind, "rate")
        self.assertEqual(len(self.fake.calls), MAX_CALLS_PER_HOUR)
        self.mono.now += 3601
        self.assertEqual(brain.reply("سؤال معمولی").kind, "answer")


class KeyAndFilesTests(BrainCase):
    def test_the_key_lives_only_in_its_own_private_file(self):
        brain = self.ready_brain()
        brain.reply("سلام")
        files = self.every_text_file()
        self.assertIn(KEY, files["key.dat"])
        for name, content in files.items():
            if name != "key.dat":
                self.assertNotIn(KEY, content, name)
                self.assertNotIn(KEY[:12], content, name)
        self.assertNotIn(KEY, json.dumps(self.audit.lines, ensure_ascii=False))
        self.assertNotIn(KEY, json.dumps(brain.status(), ensure_ascii=False))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.root, "key.dat")).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.root, "settings.json")).st_mode), 0o600)
        self.assertEqual(brain.status()["key"], mask(KEY))
        self.assertEqual(mask(KEY), "AIza…6Q")

    def test_forgetting_the_key_switches_everything_off_and_wipes_the_history(self):
        brain = self.ready_brain()
        brain.reply("سلام")
        self.assertEqual(brain.history.count(), 1)
        self.assertTrue(brain.forget_key())
        st = brain.status()
        self.assertEqual((st["key"], st["mode"], st["consent"], st["history"], st["ready"]), ("", "off", False, 0, False))
        self.assertFalse(os.path.exists(os.path.join(self.root, "key.dat")))
        self.assertEqual(brain.reply("سلام").kind, "not_ready")

    def test_unacceptable_keys_are_refused(self):
        vault = KeyVault(os.path.join(self.root, "key.dat"))
        for bad in ("", "short", "has space inside key 1234567890", KEY + "\n" + "X", KEY[:20] + '"' + KEY[20:], "کلید" * 8, "a" * 400, None):
            with self.subTest(bad=bad):
                self.assertFalse(vault.put(bad))
        self.assertFalse(os.path.exists(vault.path))
        self.assertTrue(vault.put(" %s \n" % KEY))
        self.assertEqual(vault.get(), KEY)

    def test_a_tampered_key_file_is_not_trusted(self):
        vault = KeyVault(os.path.join(self.root, "key.dat"))
        vault.put(KEY)
        with open(vault.path, "w", encoding="utf-8") as handle:
            handle.write("not a key because it has spaces\n")
        self.assertEqual((vault.get(), vault.exists()), ("", False))
        os.remove(vault.path)
        os.symlink(os.path.join(self.tmp.name, "elsewhere"), vault.path) if os.name == "posix" else None
        self.assertEqual(vault.get(), "")

    def test_settings_validation_and_recovery(self):
        settings = Settings(os.path.join(self.root, "settings.json"), self.clock)
        for bad in (dict(mode="on"), dict(provider="evil"), dict(model="a b"), dict(consent={"host": "x"}), dict(share_private="yes"),
                    dict(unknown=1), dict(schema=2), dict(base_url="http://x.example.com/")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    settings.update(**bad)
        self.assertEqual(settings.get()["mode"], "off")
        settings.update(mode="auto", provider="gemini")
        with open(settings.path, "w", encoding="utf-8") as handle:
            handle.write('{"schema": 1, "mode": "rm -rf"}')
        fresh = Settings(settings.path, self.clock)
        self.assertEqual(fresh.get()["mode"], "off")
        self.assertIsNotNone(fresh.recovery)
        self.assertTrue(any(name.startswith("settings.json.corrupt") for name in os.listdir(self.root)))

    def test_history_bounds_expiry_and_damage(self):
        history = History(os.path.join(self.root, "history.json"), self.clock)
        self.assertFalse(history.add("", "x"))
        for i in range(MAX_TURNS + 4):
            history.add("سؤال %d" % i, "جواب %d" % i)
        self.assertEqual(history.count(), MAX_TURNS)
        self.assertEqual(history.turns()[0][0], "سؤال 4")
        self.clock.now += TTL_SECONDS + 1
        self.assertEqual(history.turns(), [])
        history.add("تازه", "تازه")
        with open(history.path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        again = History(history.path, self.clock)
        self.assertEqual(again.turns(), [])
        self.assertIsNotNone(again.recovery)
        long = "ا" * 5000
        again.add(long, long)
        self.assertEqual(len(again.turns()[0][0]), 1200)

    def test_provider_helpers(self):
        self.assertEqual(providers.parse_provider_word("گوگل"), "gemini")
        self.assertEqual(providers.parse_provider_word("۲"), "openai")
        self.assertEqual(providers.parse_provider_word("Claude"), "anthropic")
        self.assertEqual(providers.parse_provider_word("چت جی پی تی"), "openai")
        self.assertIsNone(providers.parse_provider_word("نمی‌دانم کدام بهتر است برای من"))
        self.assertIsNone(providers.parse_provider_word("سلام"))
        self.assertEqual([providers.sniff_key(k) for k in ("AIza123", "sk-ant-x", "sk-or-x", "sk-x", "zzz")],
                         ["gemini", "anthropic", "openrouter", "openai", None])
        self.assertEqual(providers.valid_custom_base("https://api.x.example.com/v1/chat/completions")[0], "https://api.x.example.com/v1/")


class HubIntegrationTests(unittest.TestCase):
    def test_get_brain_follows_the_hubs_internet_switch_and_injected_transport(self):
        from brain_hub.service import HubService
        with tempfile.TemporaryDirectory() as tmp:
            fake = Fake()
            hub = HubService(os.path.join(tmp, "brain_hub"), transport=fake)
            brain = get_brain(hub)
            self.assertIs(get_brain(hub), brain)
            self.assertEqual(brain.root, os.path.join(hub.root, "brain_v2"))
            brain.choose_provider("gemini")
            brain.give_consent()
            brain.set_key(KEY)
            brain.set_mode("auto")
            self.assertEqual(brain.ready(), (False, "no_network"))
            self.assertTrue(hub.grant_permission("network", user_approved=True).ok)
            self.assertEqual(brain.reply("سلام").kind, "answer")
            self.assertEqual(len(fake.calls), 1)
            hub.revoke_permission("network")
            self.assertEqual(brain.reply("سلام").kind, "not_ready")
            self.assertEqual(len(fake.calls), 1)
            verdict = hub.audit.verify()
            self.assertTrue(verdict["ok"], "the hub's hash chain must stay intact with brain.* lines in it")
            self.assertGreaterEqual(verdict["entries"], 4)
            with open(hub.audit.path, encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn("brain.ask", text)
            self.assertNotIn(KEY, text)
            self.assertNotIn("سلام", text)
            reset_brain(hub)


class ProtectionTests(unittest.TestCase):
    """The cloud brain holds the user's key and the privacy filter: no pack may replace any of it (a pack can replace ordinary modules)."""

    def test_no_module_of_the_cloud_brain_can_be_replaced_by_a_pack(self):
        from pack_system import limits
        folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brain_v2")
        modules = ["brain_v2"] + ["brain_v2." + n[:-3] for n in sorted(os.listdir(folder)) if n.endswith(".py") and n != "__init__.py"]
        self.assertGreaterEqual(len(modules), 11)
        for module in modules + ["persian_brain.hub_brain", "persian_brain.hub_brain_commands", "persian_brain.hub_messages_brain", "net_tools.post"]:
            self.assertTrue(limits.is_protected(module), module)

    def test_a_pack_that_declares_such_a_replacement_is_refused_by_its_manifest(self):
        from pack_system import intake, manifest
        from pack_system.errors import PackError
        from tests import pack_support_prompt958 as S
        for module in ("brain_v2.keyvault", "brain_v2.privacy", "brain_v2.service", "brain_v2"):
            _schema, raw = intake.find_pack_in_text(S.text_pack(replaces=module, extra_files={module.replace(".", "/") + ".py": "x = 1"}))
            with self.assertRaises(PackError, msg=module) as ctx:
                manifest.normalize(raw)
            self.assertEqual(ctx.exception.code, "E_PACK_PROTECTED", module)

    def test_the_live_pack_prompt_tells_the_assistant_about_it(self):
        from brain_hub import pack_prompt
        self.assertIn("brain_v2", pack_prompt.prompt_facts()["protected_prefixes"])
        self.assertIn("brain_v2", pack_prompt.build_prompt("یک کار", "code"))


if __name__ == "__main__":
    unittest.main()
