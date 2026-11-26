"""
Prompt 959 (stage B, the body) - `brain_hub.selftest`: the one report the user can copy and paste back when something does not work on his phone.

The hub and the phone's doors are small fakes that record what is asked of them. The tests pin: the report always comes out (whatever part fails),
it holds the facts that were asked for, and it NEVER holds the chat, a key, a one-time code, a phone number, a file path or the text of an error.
"""
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import selftest as S


class Result:
    def __init__(self, ok=True, code="", data=None):
        self.ok, self.code, self.data = ok, code, data


class Row(dict):
    """A row of the error table (the real one is a `sqlite3.Row`: indexed by column name)."""


class Item:
    def __init__(self, feature_id, state, code=""):
        self.feature_id, self.state, self.code = feature_id, state, code


class Memory:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def recent_errors(self, limit):
        self.calls.append(limit)
        return list(self.rows)[:limit]


class Door:
    """One door object whose every method returns the configured answer and records its name in the shared log."""

    def __init__(self, log, prefix, answers):
        self._log, self._prefix, self._answers = log, prefix, answers

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            self._log.append("%s.%s" % (self._prefix, name))
            answer = self._answers.get(name)
            if isinstance(answer, Exception):
                raise answer
            return answer if answer is not None else Result(False, "unavailable_platform")
        return call


class Doors:
    def __init__(self, log, **answers):
        self.phone = Door(log, "phone", answers.get("phone", {}))
        self.sms = Door(log, "sms", answers.get("sms", {}))
        self.body = Door(log, "body", answers.get("body", {}))


class Permissions:
    def __init__(self, granted=True):
        self.granted = granted

    def is_granted(self, name):
        return self.granted if name == "network" else False


class Network:
    state = "online"


PHONE_ANSWERS = {
    "app_info": Result(True, data={"package": "com.erfan.standaloneai", "version_name": "0.2.0", "version_code": 2, "sdk": 34, "abis": ["arm64-v8a"]}),
    "memory": Result(True, data={"total": 8_000_000_000, "available": 3_000_000_000, "low": False}),
    "battery_optimization": Result(True, data={"ignoring": False, "power_save": True}),
}
SMS_ANSWERS = {"has_permission": Result(True, data={"granted": True})}
BODY_ANSWERS = {"running": Result(True, data={"running": True})}


class FakeHub:
    """The parts of a hub the report reads, each one recorded in the log. Any of them can be replaced by something that raises."""

    root = "/data/user/0/com.erfan.standaloneai/files/hub"

    def __init__(self, log=None, rows=(), engine=None, others=(), statuses=None):
        self.log = log if log is not None else []
        self.memory = Memory(list(rows))
        self.permissions = Permissions()
        self._engine = engine if engine is not None else {"formats": ("litertlm",), "available": True, "code": "ready", "reason_fa": "", "api": "", "name": "LiteRT-LM"}
        self._others = list(others)
        self._statuses = statuses if statuses is not None else [Item("notifications", "granted", "ok"), Item("microphone", "denied", "not_requested"),
                                                                  Item("other_feature", "granted")]

    def clock(self):
        return 1_700_000_000.0

    def model_runtimes_info(self):
        self.log.append("hub.model_runtimes_info")
        return [self._engine] + self._others

    def network_status(self):
        self.log.append("hub.network_status")
        return Network()

    def android_statuses(self):
        self.log.append("hub.android_statuses")
        return list(self._statuses)

    def native_features(self):
        self.log.append("hub.native_features")
        return frozenset({"body_service", "phone"})

    def list_models(self):
        self.log.append("hub.list_models")
        return [object(), object(), object()]


class FakeBrain:
    def __init__(self, status=None):
        self._status = status if status is not None else {"phase": "ready", "sub": "", "choice": "light", "percent": 100, "bytes": 5, "total": 5, "code": "",
                                                           "detail": "", "resumable": False, "consent": True}

    def status(self):
        return self._status

    def facts(self):
        return {"free": 20_000_000_000, "ram": 7_000_000_000}


def collect(hub=None, doors=None, brain=None, log=None):
    log = log if log is not None else []
    hub = hub if hub is not None else FakeHub(log)
    if doors is None:
        doors = Doors(log, phone=PHONE_ANSWERS, sms=SMS_ANSWERS, body=BODY_ANSWERS)
    with mock.patch("brain_hub.ownbrain.get_ownbrain", return_value=brain if brain is not None else FakeBrain()):
        return S.collect(hub, doors=doors)


# ============================================================================ what the report holds
class CollectTests(unittest.TestCase):
    def test_every_section_is_there_and_the_report_is_plain_json(self):
        facts = collect()
        self.assertEqual(set(facts), set(S.SECTIONS) | {"time"})
        self.assertEqual(json.loads(json.dumps(facts)), facts)

    def test_the_facts_come_from_the_phone_and_the_hub(self):
        facts = collect()
        self.assertEqual(facts["app"], {"known": True, "package": "com.erfan.standaloneai", "version_name": "0.2.0", "version_code": 2, "sdk": 34,
                                        "abis": ["arm64-v8a"]})
        self.assertEqual((facts["phone"]["ram_total"], facts["phone"]["ram_available"], facts["phone"]["ram_low"]), (8_000_000_000, 3_000_000_000, False))
        self.assertEqual((facts["phone"]["battery_known"], facts["phone"]["ignoring_battery"], facts["phone"]["power_save"]), (True, False, True))
        self.assertEqual(facts["phone"]["free"], 20_000_000_000)
        self.assertEqual((facts["engine"]["available"], facts["engine"]["code"]), (True, "ready"))
        self.assertEqual((facts["ownbrain"]["known"], facts["ownbrain"]["phase"], facts["ownbrain"]["choice"]), (True, "ready", "light"))
        self.assertEqual(facts["network"], {"app_switch": True, "state": "online"})
        self.assertEqual(facts["permissions"], {"notifications": {"state": "granted", "code": "ok"}, "microphone": {"state": "denied", "code": "not_requested"},
                                                "sms": {"state": "granted"}})
        self.assertEqual((facts["body"]["native"], facts["body"]["running"], facts["body"]["holding"]), (True, True, False))
        self.assertEqual(facts["models"], 3)
        self.assertEqual(facts["time"], time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(1_700_000_000.0)))

    def test_the_phones_memory_wins_and_the_brains_own_guess_fills_a_gap(self):
        facts = collect(doors=Doors([], phone={"memory": Result(False, "error")}))
        self.assertEqual(facts["phone"]["ram_total"], 7_000_000_000, "the number the own brain measured")
        self.assertIsNone(facts["phone"]["ram_low"])

    def test_the_report_asks_only_for_facts(self):
        log = []
        collect(log=log)
        self.assertEqual(sorted(set(entry for entry in log if entry.startswith(("phone.", "sms.", "body.")))),
                         ["body.running", "phone.app_info", "phone.battery_optimization", "phone.memory", "sms.has_permission"],
                         "no inbox, no clipboard, no settings page, no permission dialog")

    def test_an_engine_that_does_not_match_says_why_and_lists_the_others(self):
        hub = FakeHub(engine={"formats": ("litertlm",), "available": False, "code": "api_mismatch", "reason_fa": "با برنامه نمی‌خواند", "api": "Lx/Engine;"},
                      others=[{"name": "MediaPipe", "available": False, "code": "not_built", "formats": ("task",)}])
        engine = collect(hub=hub)["engine"]
        self.assertEqual((engine["available"], engine["code"], engine["reason_fa"], engine["api"]), (False, "api_mismatch", "با برنامه نمی‌خواند", "Lx/Engine;"))
        self.assertEqual(engine["others"], [{"name": "MediaPipe", "available": False, "code": "not_built"}])

    def test_the_engine_listing_is_cut_to_its_size(self):
        hub = FakeHub(engine={"formats": ("litertlm",), "available": False, "code": "x", "reason_fa": "ر" * 900, "api": "a" * 9000})
        engine = collect(hub=hub)["engine"]
        self.assertEqual((len(engine["api"]), len(engine["reason_fa"])), (S.MAX_API_CHARS, 200))

    def test_a_hub_without_a_matching_engine_says_unknown(self):
        hub = FakeHub()
        hub.model_runtimes_info = lambda: []
        self.assertEqual(collect(hub=hub)["engine"], {"available": False, "code": "unknown", "reason_fa": "", "api": "", "others": []})


# ============================================================================ what the report never holds
class PrivacyTests(unittest.TestCase):
    SECRETS = ("sk-SECRET-KEY-777", "کلمهٔ-محرمانه-۱۷۳", "+989121234567", "428913", "/data/user/0/com.erfan.standaloneai/files/models/secret.litertlm",
               "/storage/emulated/0/Download/private-photo.jpg", "token=abc123", "گوگل-فرستنده")

    def planted(self):
        rows = [
            Row(operation="persian_brain", message="ValueError: the user said کلمهٔ-محرمانه-۱۷۳ and 428913", created_at="2026-11-22 10:00:00", id=1),
            Row(operation="GET /api/history?token=abc123&q=sk-SECRET-KEY-777", message="a bare message with +989121234567", created_at="2026-11-22 10:01:00", id=2),
            Row(operation="POST /api/chat", message="OSError: [Errno 2] No such file: /data/user/0/com.erfan.standaloneai/files/models/secret.litertlm",
                created_at="2026-11-22 10:02:00", id=3),
        ]
        engine = {"formats": ("litertlm",), "available": False, "code": "load_failed", "name": "LiteRT-LM",
                  "reason_fa": "فایل /storage/emulated/0/Download/private-photo.jpg باز نشد", "api": "Lcom/google/ai/edge/litertlm/Engine;->open(Ljava/lang/String;)V at /data/user/0/com.erfan.standaloneai/files/models/secret.litertlm"}
        brain = FakeBrain({"phase": "failed", "sub": "", "choice": "light", "percent": 3, "bytes": 5, "total": 9, "code": "download_failed",
                           "detail": "write failed at /data/user/0/com.erfan.standaloneai/files/models/secret.litertlm", "resumable": True, "consent": True,
                           "token": "sk-SECRET-KEY-777", "path": "/data/user/0/x/y", "url": "https://example.invalid/?token=abc123", "message": "428913",
                           "sender": "گوگل-فرستنده"})
        return FakeHub(rows=rows, engine=engine), brain

    def test_no_secret_is_in_the_report(self):
        hub, brain = self.planted()
        text = json.dumps(collect(hub=hub, brain=brain), ensure_ascii=False)
        for secret in self.SECRETS:
            self.assertNotIn(secret, text)
        self.assertNotIn("/data/", text)
        self.assertNotIn("/storage/", text)

    def test_what_the_report_may_say_about_them_is_still_there(self):
        hub, brain = self.planted()
        facts = collect(hub=hub, brain=brain)
        self.assertEqual({(e["operation"], e["type"]) for e in facts["errors"]},
                         {("persian_brain", "ValueError"), ("GET /api/history", "?"), ("POST /api/chat", "OSError")})
        self.assertIn("Lcom/google/ai/edge/litertlm/Engine;->open(Ljava/lang/String;)V", facts["engine"]["api"], "a class listing is not a path and stays whole")
        self.assertIn("<path>", facts["engine"]["api"])
        self.assertEqual(facts["ownbrain"]["detail"], "write failed at <path>")
        self.assertEqual(facts["ownbrain"]["code"], "download_failed")
        self.assertEqual(set(facts["ownbrain"]), set(("phase", "sub", "choice", "percent", "bytes", "total", "code", "detail", "resumable", "consent", "known")),
                         "no other key of the status is copied")

    def test_the_inbox_the_clipboard_and_the_dialogs_are_never_touched(self):
        log = []
        collect(log=log)
        for forbidden in ("latest_code", "read", "request_permission", "set_text", "open_settings", "get_text"):
            self.assertFalse([entry for entry in log if entry.endswith("." + forbidden)], forbidden)

    def test_the_kind_of_an_error_is_only_a_class_name_before_a_colon(self):
        cases = {
            "ValueError: x": "ValueError", "json.decoder.JSONDecodeError: Expecting value": "json.decoder.JSONDecodeError", "OSError:": "OSError",
            "secret": "?", "secret-word": "?", "two words: x": "?", "": "?", None: "?", "1abc: x": "?", ": x": "?", "'KeyError': x": "?",
            "A" * 80 + ": x": "?", "خطا: ب": "?",
        }
        for message, kind in cases.items():
            with self.subTest(message=message):
                self.assertEqual(S._error_kind(message), kind)

    def test_the_operation_never_carries_a_query_a_fragment_or_odd_characters(self):
        cases = {
            "GET /api/history?token=abc": "GET /api/history", "POST /api/x#frag": "POST /api/x", "persian_brain": "persian_brain", "": "", None: "",
            "GET /a%D8%B3": "GET /a?D8?B3", "GET /ap/ی": "GET /ap/?", "x" * 90: "x" * 40, "a?b?c": "a",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(S._operation(value), expected)

    def test_free_text_loses_every_absolute_path_and_keeps_class_listings(self):
        cases = {
            "at /data/user/0/app/files/m.bin now": "at <path> now",
            "Lcom/google/ai/Engine;->f(Ljava/lang/String;)V": "Lcom/google/ai/Engine;->f(Ljava/lang/String;)V",
            "java.util.List<java/lang/String>": "java.util.List<java/lang/String>",
            "a/b": "a/b", "": "", None: "", "x" * 50: "x" * 10,
            "/storage/emulated/0/x and /sdcard/Download/y.zip": "<path> and <path>",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(S._clean(value, 10 if value == "x" * 50 else 200), expected)

    def test_a_path_is_never_left_half_hidden_by_the_cut(self):
        cleaned = S._clean("ok " + "/data/user/0/" + "q" * 500, 40)
        self.assertEqual(cleaned, "ok <path>")


# ============================================================================ the errors section
class ErrorSectionTests(unittest.TestCase):
    def errors(self, rows):
        return S._errors(FakeHub(rows=rows))

    def test_the_same_kind_is_counted_once_with_the_last_time(self):
        rows = [Row(operation="persian_brain", message="ValueError: a", created_at="2026-11-22 10:00:00"),
                Row(operation="persian_brain", message="ValueError: b", created_at="2026-11-22 10:05:00"),
                Row(operation="persian_brain", message="KeyError: c", created_at="2026-11-22 10:06:00")]
        self.assertEqual(self.errors(rows), [{"operation": "persian_brain", "type": "ValueError", "count": 2, "last": "2026-11-22 10:05:00"},
                                            {"operation": "persian_brain", "type": "KeyError", "count": 1, "last": "2026-11-22 10:06:00"}])

    def test_the_most_frequent_come_first_and_only_a_few_are_kept(self):
        rows = [Row(operation="op%02d" % n, message="E%d: x" % n, created_at="t") for n in range(20)]
        rows += [Row(operation="op19", message="E19: x", created_at="t")] * 3
        shown = self.errors(rows)
        self.assertEqual(len(shown), S.MAX_ERRORS)
        self.assertEqual((shown[0]["operation"], shown[0]["count"]), ("op19", 4))

    def test_an_app_without_a_memory_has_no_errors(self):
        hub = FakeHub()
        hub.memory = None
        self.assertEqual(S._errors(hub), [])

    def test_at_most_sixty_recent_rows_are_read(self):
        hub = FakeHub(rows=[Row(operation="o", message="E: x", created_at="t")] * 100)
        S._errors(hub)
        self.assertEqual(hub.memory.calls, [60])


# ============================================================================ a report always comes out
class NeverRaisesTests(unittest.TestCase):
    HUB_PARTS = ("model_runtimes_info", "network_status", "android_statuses", "native_features", "list_models", "clock")

    def broken(self, name):
        def boom(*args, **kwargs):
            raise RuntimeError("secret " + name)
        return boom

    def test_a_part_of_the_hub_that_fails_is_marked_unknown_and_the_rest_comes_out(self):
        for part in self.HUB_PARTS:
            with self.subTest(part):
                hub = FakeHub()
                setattr(hub, part, self.broken(part))
                facts = collect(hub=hub)
                self.assertEqual(set(facts), set(S.SECTIONS) | {"time"})
                self.assertNotIn("secret", json.dumps(facts, ensure_ascii=False), "the text of the failure is not in the report either")

    def test_the_defaults_say_unknown(self):
        hub = FakeHub()
        for part in self.HUB_PARTS:
            setattr(hub, part, self.broken(part))
        hub.memory = Memory([])
        hub.memory.recent_errors = self.broken("recent_errors")
        hub.permissions.is_granted = self.broken("is_granted")
        facts = collect(hub=hub)
        self.assertEqual(facts["engine"]["code"], "unknown")
        self.assertEqual(facts["network"], {"app_switch": None, "state": "unknown"})
        self.assertEqual(facts["errors"], [])
        self.assertEqual(facts["models"], 0)
        self.assertEqual(facts["time"], "")
        self.assertIn("sms", facts["permissions"], "the phone's own answer does not depend on the hub")
        self.assertFalse(facts["body"]["native"])

    def test_a_status_that_is_not_a_dict_is_unknown(self):
        for bad in ("nonsense", 5, [1], None):
            with self.subTest(bad):
                brain = FakeBrain()
                brain.status = lambda bad=bad: bad
                self.assertEqual(S._ownbrain(brain), {"known": False})
        self.assertEqual(S._ownbrain(None), {"known": False})

    def test_a_brain_whose_status_raises_is_unknown(self):
        brain = FakeBrain()
        brain.status = self.broken("status")
        self.assertEqual(S._ownbrain(brain), {"known": False})

    def test_a_brain_whose_facts_raise_still_gives_the_phones_memory(self):
        brain = FakeBrain()
        brain.facts = self.broken("facts")
        facts = collect(brain=brain)
        self.assertEqual(facts["phone"]["ram_total"], 8_000_000_000)
        self.assertEqual(facts["phone"]["free"], 0)

    def test_doors_that_raise_are_unknown(self):
        errors = {name: RuntimeError("secret " + name) for name in ("app_info", "memory", "battery_optimization")}
        doors = Doors([], phone=errors, sms={"has_permission": RuntimeError("secret sms")}, body={"running": RuntimeError("secret body")})
        facts = collect(doors=doors)
        self.assertEqual(facts["app"], {"known": False, "code": "error"})
        self.assertEqual(facts["permissions"]["sms"], {"state": "unknown"})
        self.assertEqual(facts["body"], {"native": None}, "a door that raises in the middle of the section leaves only the unknown")
        self.assertNotIn("secret", json.dumps(facts, ensure_ascii=False))

    def test_doors_that_answer_no_say_why_in_a_code_only(self):
        doors = Doors([], phone={}, sms={}, body={})
        facts = collect(doors=doors)
        self.assertEqual(facts["app"], {"known": False, "code": "unavailable_platform"})
        self.assertFalse(facts["phone"]["battery_known"])
        self.assertEqual(facts["permissions"]["sms"], {"state": "unknown"})
        self.assertIsNone(facts["body"]["running"])
        self.assertEqual(facts["body"]["running_code"], "unavailable_platform")

    def test_without_doors_nothing_native_is_claimed(self):
        hub = FakeHub()
        with mock.patch("native_bridge.facade.for_app", side_effect=RuntimeError("no doors")), mock.patch("brain_hub.ownbrain.get_ownbrain", return_value=FakeBrain()):
            facts = S.collect(hub)
        self.assertEqual(facts["app"], {"known": False, "code": "no_doors"})
        self.assertEqual(facts["phone"], {})
        self.assertEqual(facts["body"], {"native": None})
        self.assertNotIn("sms", facts["permissions"])
        self.assertEqual(set(facts), set(S.SECTIONS) | {"time"})

    def test_a_brain_that_cannot_be_made_is_unknown(self):
        hub = FakeHub()
        with mock.patch("brain_hub.ownbrain.get_ownbrain", side_effect=RuntimeError("boom")):
            facts = S.collect(hub, doors=Doors([], phone=PHONE_ANSWERS, sms=SMS_ANSWERS, body=BODY_ANSWERS))
        self.assertEqual(facts["ownbrain"], {"known": False})
        self.assertEqual(facts["phone"]["free"], 0)


# ============================================================================ the short form for the checklist
class QuickTests(unittest.TestCase):
    def test_the_few_facts_the_checklist_needs(self):
        log = []
        hub = FakeHub(log)
        quick = S.quick(hub, doors=Doors(log, phone=PHONE_ANSWERS, sms=SMS_ANSWERS))
        self.assertEqual(quick, {"battery": {"known": True, "ignoring": False, "power_save": True}, "notifications": "granted", "sms": "granted"})

    def test_it_stays_light(self):
        log = []
        S.quick(FakeHub(log), doors=Doors(log, phone=PHONE_ANSWERS, sms=SMS_ANSWERS))
        self.assertEqual(sorted(set(log)), ["hub.android_statuses", "phone.battery_optimization", "sms.has_permission"])

    def test_the_sms_permission_in_its_three_states(self):
        for answer, expected in ((Result(True, data={"granted": True}), "granted"), (Result(True, data={"granted": False}), "denied"),
                                 (Result(False, "unavailable_platform"), "unknown"), (Result(True, data=None), "unknown")):
            with self.subTest(expected=expected):
                self.assertEqual(S.quick(FakeHub(), doors=Doors([], phone=PHONE_ANSWERS, sms={"has_permission": answer}))["sms"], expected)

    def test_it_never_raises_and_says_unknown(self):
        hub = FakeHub()
        hub.android_statuses = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        doors = Doors([], phone={"battery_optimization": RuntimeError("boom")}, sms={"has_permission": RuntimeError("boom")})
        self.assertEqual(S.quick(hub, doors=doors), {"battery": {"known": False}, "notifications": "", "sms": "unknown"})

    def test_without_doors_only_the_hubs_part_is_there(self):
        with mock.patch("native_bridge.facade.for_app", side_effect=RuntimeError("no doors")):
            quick = S.quick(FakeHub())
        self.assertEqual(quick, {"battery": {"known": False}, "notifications": "granted", "sms": "unknown"})


if __name__ == "__main__":
    unittest.main()
