"""
Prompt 957 - ACCEPTANCE tests of the installed app, driven only through its real front door
===========================================================================================
Every test starts the app the way the phone does (`android_entry`'s own platform adapter and storage layout, `RuntimeCore`,
the real HTTP handler) and then only types messages: `POST /api/message` -> `RuntimeCore.process_input` -> `Core` ->
skills -> Persian brain -> hub. Only the outside world is scripted (web transport, model download transport, Android bridge,
clock) - see `tests/persian_app_case_prompt957.py`.

  acceptance item                                                            tests
  1  fresh start reaches the real chat UI, a Persian message reaches Core     A01FreshStart
  2  the registry enumerates capabilities and distinguishes their states      A02Registry
  3  a capability nobody hard-coded is defined, validated, tested, registered
     and invoked from a normal request                                        A03NewCapability
  4  it survives a restart                                                    A04Restart
  5  failed / malicious extensions are rejected and never active              A05Rejected
  6  an update makes a new version and rollback restores the old behaviour    A06UpdateRollback
  7  unsupported requests never produce a false "installed/learned/done"      A07Unsupported
  8  a model is not usable until integrity, compatibility, loading and a
     real inference smoke test passed                                         A08Models
  9  network features fail clearly offline / permission-blocked while chat
     and memory keep working                                                  A09Offline
  -  extension code survives the chat's whitespace folding (a real defect
     these tests found)                                                       A10CodeSurvivesTheChat
  1+4 the real entry point `android_entry.start()` in its own process, killed
     and started again on the same folder - no test doubles at all            A12RealEntryPoint
  10 the existing tests pass: the full regression run (not a unit test)
  11 the Android build / APK install: NOT possible in this environment (see docs/brain_hub_prompt957.md)
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub.service import default_root
from persian_brain import activation
from self_builder import fa_text
from tests import brain_hub_fixtures_prompt957 as F
from tests.persian_app_case_prompt957 import (AppCase, LOAN_ASK, LOAN_ROUNDED_VECTORS, LOAN_VECTORS, loan_answer, loan_pkg,
                                              loan_sentence)
from net_tools import TransportError
from net_tools.fetch import message_for

fa = fa_text.fa_number
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERSIAN = re.compile("[؀-ۿ]")
FALSE_CLAIMS = ("ساختم", "ساخته شد", "نصب شد", "فعال شد", "انجام شد", "یاد گرفتم", "قابل استفاده است")


def tabbed(pkg):
    """The same package with its code indented by tabs (what the prompt asks authors for)."""
    pkg = dict(pkg)
    pkg["source"] = pkg["source"].replace("    ", "\t")
    return pkg


# ======================================================================================= 1
class A01FreshStart(AppCase):
    def test_the_first_start_serves_the_real_persian_chat_page(self):
        status, ctype, body = self.get("/")
        page = body.decode("utf-8")
        self.assertEqual((status, ctype), (200, "text/html; charset=utf-8"))
        for needle in ('lang="fa"', 'dir="rtl"', 'id="input-box"', 'id="send-btn"', 'id="attach-btn"', "/static/app.js"):
            self.assertIn(needle, page)
        self.assertEqual(self.get("/static/app.js")[0], 200)
        self.assertEqual(self.get("/static/i18n.js")[0], 200)
        status, body = self.post("/api/message", {"text": ""})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"]["system_status"], "HEALTHY")

    def test_a_persian_message_reaches_core_and_the_persian_brain(self):
        self.assertEqual(activation.scope_for(self.memory), activation.SCOPE_FULL)   # chosen by the adapter, not forced
        self.assertEqual(self.core.recent_messages(10), [])
        reply = self.ask("سلام")
        self.assertRegex(reply, PERSIAN)
        turns = self.core.recent_messages(10)
        self.assertEqual([t["role"] for t in turns], ["user", "assistant"])
        self.assertEqual((turns[0]["content"], turns[1]["content"]), ("سلام", reply))
        self.assertEqual(self.brain.last_trace["intent"]["kind"], "GREETING")          # the Persian brain answered
        self.assertIsInstance(self.core.last_runtime_result, dict)                      # ... through RuntimeCore

    def test_every_file_the_app_creates_lives_in_its_private_folder(self):
        self.ask("سلام")
        self.assertTrue(os.path.abspath(self.memory.db_path).startswith(os.path.abspath(self.files) + os.sep))
        self.assertTrue(os.path.abspath(default_root(self.memory)).startswith(os.path.abspath(self.files) + os.sep))
        self.assertTrue(os.path.isfile(self.memory.db_path))

    def test_the_conversation_does_not_depend_on_the_hub(self):
        self.hub.close()                      # even a hub that was shut down must not take the conversation with it
        self.assertRegex(self.ask("سلام"), PERSIAN)


# ======================================================================================= 2
class A02Registry(AppCase):
    def node(self, node_id):
        return self.hub.graph().get(node_id)

    def test_the_graph_enumerates_everything_and_separates_the_states(self):
        self.assertEqual(self.node("brain.conversation").state, "available")      # nothing served yet: no evidence, so not "active"
        self.ask("سلام")
        graph = self.hub.graph()
        summary = graph.summary()
        self.assertGreaterEqual(summary["total"], 40)
        for state in ("active", "available", "permission_blocked", "dependency_blocked", "policy_blocked", "not_implemented"):
            self.assertIn(state, summary["by_state"], state)
        self.assertEqual(summary["usable"], summary["by_state"]["active"] + summary["by_state"]["available"])
        for n in graph.nodes():
            if n.state == "active":
                self.assertTrue(n.tested, n.node_id)                       # "active" always carries test evidence
            if not n.usable:
                self.assertTrue(n.blockers, n.node_id)                     # "not usable" always says what is missing
        self.assertEqual(self.node("brain.conversation").state, "active")
        self.assertEqual(self.node("tool.web_fetch").state, "permission_blocked")
        self.assertEqual(self.node("tool.local_model").state, "dependency_blocked")
        self.assertEqual(self.node("android.telephony").state, "policy_blocked")
        self.assertIn("permission", [b.kind for b in self.node("tool.web_fetch").blockers])
        self.assertIn("model", [b.kind for b in self.node("gap.image_generation").blockers])

    def test_the_chat_map_tells_the_same_story_as_the_graph(self):
        summary = self.hub.graph().summary()
        reply = self.ask("نقشهٔ قابلیت‌ها را نشان بده")
        self.assertIn("%s مورد ثبت است و %s مورد قابل استفاده است" % (fa(summary["total"]), fa(summary["usable"])), reply)
        for label in ("فعال و آزمایش‌شده", "منتظر مجوز", "نیازمند چیزی که اینجا نیست", "ممنوع یا محدود"):
            self.assertIn(label, reply)
        self.assertIn("چیزهایی که هنوز نمی‌توانم", reply)

    def test_permission_blocked_becomes_usable_only_after_the_user_grants_it(self):
        self.assertFalse(self.node("tool.web_fetch").usable)
        self.assertIn("(بله / نه)", self.ask("اینترنت را روشن کن"))
        self.assertFalse(self.node("tool.web_fetch").usable)               # asking is not granting
        self.assertIn("اینترنت روشن شد", self.ask("بله"))
        self.assertTrue(self.node("tool.web_fetch").usable)
        self.assertIn("اینترنت خاموش شد", self.ask("اینترنت را خاموش کن"))
        self.assertEqual(self.node("tool.web_fetch").state, "permission_blocked")

    def test_a_new_extension_is_listed_as_active_and_tested_and_a_disabled_one_is_not_usable(self):
        self.install(loan_pkg())
        node = self.node("ext.loan_installment")
        self.assertEqual((node.kind, node.state, node.tested, node.version), ("extension", "active", True, 1))
        self.ask("افزونه را غیرفعال کن")
        self.assertIn("غیرفعال شد", self.ask("بله"))
        node = self.node("ext.loan_installment")
        self.assertEqual(node.state, "disabled")
        self.assertFalse(node.usable)
        self.assertNotIn("قسط ماهانه:", self.ask(LOAN_ASK))                    # a disabled extension answers nothing

    def test_a_proposal_is_not_a_capability_until_the_user_says_yes(self):
        self.paste(loan_pkg())
        pending = self.node("ext.loan_installment.pending")
        self.assertEqual(pending.state, "pending_approval")
        self.assertFalse(pending.usable)
        self.assertIsNone(self.node("ext.loan_installment"))
        self.ask("بله")
        self.assertIsNone(self.node("ext.loan_installment.pending"))
        self.assertEqual(self.node("ext.loan_installment").state, "active")


# ======================================================================================= 3
class A03NewCapability(AppCase):
    def test_the_capability_is_not_hard_coded_anywhere_in_the_app(self):
        hits = []
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", "data")]
            for name in files:
                if name.endswith((".py", ".js", ".html", ".json")):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    if "loan_installment" in text or "قسط" in text:
                        hits.append(os.path.join(folder, name))
        self.assertEqual(hits, [])

    def test_defined_validated_tested_registered_then_used_from_a_normal_request(self):
        self.assertNotIn("قسط ماهانه:", self.ask(LOAN_ASK))                    # before: the app does not know it
        self.assertIsNone(self.hub.extension("loan_installment"))
        proposal = self.paste(loan_pkg())
        for fact in ("هنوز چیزی نصب یا فعال نشده", "آزمون‌ها: ۴ از ۴ موفق", "کد در محیط ایزوله اجرا شد", "مجوز اضافه‌ای نمی‌خواهد",
                     "این یک افزونهٔ تازه است"):
            self.assertIn(fact, proposal)
        self.assertIsNone(self.hub.extension("loan_installment"))              # nothing registered before the user agrees
        self.assertNotIn("قسط ماهانه:", self.ask(LOAN_ASK))
        self.paste(loan_pkg())                                                  # the question was withdrawn by that sentence
        done = self.ask("بله")
        for fact in ("نصب و فعال شد (نسخهٔ ۱)", "پس از نصب از دیسک دوباره بررسی شد", "قابل بارگذاری و قابل فراخوانی است",
                     "آزمون‌ها ۴ از ۴ موفق‌اند"):
            self.assertIn(fact, done)
        cap = self.hub.extension("loan_installment")
        self.assertEqual((cap["state"], cap["active_version"]), ("active", 1))
        for amount, percent, months, payment, total in LOAN_VECTORS:
            with self.subTest(amount=amount, percent=percent, months=months):
                reply = self.ask(loan_sentence(amount, percent, months))
                self.assertIn(loan_answer(payment, total), reply)
                self.assertIn("افزونهٔ «قسط ماهانهٔ وام» · نسخهٔ ۱", reply)
        self.assertIn(loan_answer(11_001_599, 132_019_190), self.ask(LOAN_ASK))   # Persian digits are understood as well

    def test_inputs_are_validated_never_guessed(self):
        self.install(loan_pkg())
        for sentence, name in ((loan_sentence(120_000_000, 180, 12), "annual_percent"), (loan_sentence(120_000_000, 18, 0), "months"),
                               (loan_sentence(5, 18, 12), "amount")):
            with self.subTest(sentence=sentence):
                reply = self.ask(sentence)
                self.assertIn("ورودی‌ها برای «قسط ماهانهٔ وام» معتبر نبود", reply)
                self.assertIn(name, reply)
                self.assertIn("چیزی اجرا نشد", reply)
                self.assertNotIn("قسط ماهانه:", reply)

    def test_packages_of_realistic_size_go_through_the_front_door(self):
        for padding in (20_000, 60_000):
            with self.subTest(padding=padding):
                pkg = loan_pkg(padding_bytes=padding, id="loan_big_%d" % padding)
                text = json.dumps(pkg, ensure_ascii=False)
                self.assertGreater(len(text.encode("utf-8")), padding)
                proposal = self.paste(pkg)
                self.assertIn("آزمون‌ها: ۴ از ۴ موفق", proposal)
                self.assertIn("نصب و فعال شد", self.ask("بله"))
                self.assertEqual(self.hub.extension("loan_big_%d" % padding)["state"], "active")
        self.assertIn(loan_answer(11_001_599, 132_019_190), self.ask(LOAN_ASK))

    def test_each_stage_of_the_lifecycle_leaves_evidence(self):
        self.install(loan_pkg())
        history = self.hub.extension_history("loan_installment")
        self.assertEqual([h["event"] for h in reversed(history)], ["ext.proposed", "ext.approved", "ext.activated"])
        proposed, approved, activated = reversed(history)
        self.assertEqual(proposed["detail"]["tests"], "4/4")
        self.assertEqual(approved["detail"]["approver"], "user")
        self.assertEqual(activated["detail"]["tests"], "4/4")
        self.assertEqual(proposed["detail"]["fingerprint"], approved["detail"]["fingerprint"])
        chat = self.ask("تاریخچهٔ افزونه‌ها")
        for label in ("«قسط ماهانهٔ وام»: پیشنهاد شد — نسخهٔ ۱", "«قسط ماهانهٔ وام»: تأیید شد — نسخهٔ ۱", "«قسط ماهانهٔ وام»: فعال شد — نسخهٔ ۱"):
            self.assertIn(label, chat)
        self.assertNotIn("ext.", chat)                                               # the user reads sentences, not event codes
        self.assertTrue(self.hub.audit.verify()["ok"])


# ======================================================================================= 4
class A04Restart(AppCase):
    def test_an_installed_capability_survives_a_restart_and_still_answers(self):
        self.install(loan_pkg())
        before = self.hub.extension("loan_installment")
        self.start_app()
        after = self.hub.extension("loan_installment")
        self.assertEqual((after["state"], after["active_version"]), ("active", 1))
        self.assertEqual(after["fingerprint"] if "fingerprint" in after else before.get("fingerprint"), before.get("fingerprint"))
        self.assertIn(loan_answer(11_001_599, 132_019_190), self.ask(LOAN_ASK))
        self.assertEqual(self.hub.graph().get("ext.loan_installment").state, "active")
        self.assertEqual([h["event"] for h in reversed(self.hub.extension_history("loan_installment"))][:3],
                         ["ext.proposed", "ext.approved", "ext.activated"])

    def test_the_open_question_survives_a_restart_but_nothing_was_installed_before_the_yes(self):
        self.paste(loan_pkg())
        self.start_app()
        self.assertIsNone(self.hub.extension("loan_installment"))
        self.assertIn("نصب و فعال شد", self.ask("بله"))
        self.assertEqual(self.hub.extension("loan_installment")["state"], "active")

    def test_memory_and_taught_knowledge_survive_a_restart_too(self):
        self.assertIn("عرفان", self.ask("من عرفان هستم"))
        self.assertIn("یاد گرفتم", self.ask("یاد بگیر که پایتون یک زبان برنامه‌نویسی است"))
        self.start_app()
        self.assertIn("عرفان", self.ask("اسم من چیست؟"))
        self.assertIn("زبان", self.ask("پایتون چیست؟"))

    def test_the_internet_switch_and_a_switched_off_extension_survive_a_restart(self):
        self.install(loan_pkg())
        self.ask("اینترنت را روشن کن")
        self.ask("بله")
        self.ask("افزونه را غیرفعال کن")
        self.ask("بله")
        self.start_app()
        self.assertTrue(self.hub.permissions.is_granted("network"))
        self.assertEqual(self.hub.extension("loan_installment")["state"], "disabled")
        self.assertNotIn("قسط ماهانه:", self.ask(LOAN_ASK))


# ======================================================================================= 5
class A05Rejected(AppCase):
    REASONS = {"escape": "is not allowed", "import": "import 'os' is not allowed", "open": "'open' is not defined",
               "eval": "'eval' is not defined", "endless": "fuel"}

    def assert_rejected(self, reply, installed=()):
        self.assertIn("بسته را نپذیرفتم", reply)
        self.assertIn("هیچ چیزی نصب یا فعال نشد", reply)
        self.assertNotIn("نصب و فعال شد", reply)
        self.assertEqual(self.installed_ids(), sorted(installed))
        self.assertIn("سؤال بازی ندارم", self.ask("بله"))                      # no open question: a «بله» cannot install it
        self.assertEqual(self.installed_ids(), sorted(installed))

    def test_every_malicious_package_is_rejected_for_its_own_reason_and_never_active(self):
        for kind, reason in self.REASONS.items():
            with self.subTest(kind=kind):
                reply = self.paste(tabbed(F.malicious_pkg(kind)))
                self.assertIn(reason, reply)
                self.assert_rejected(reply)
                self.assertNotIn("تورفتگی خط‌های کد موقع فرستادن از بین رفته است", reply)       # that hint is for indentation only
                self.assertIsNone(self.hub.extension("evil_ext"))
                self.assertIsNone(self.hub.graph().get("ext.evil_ext"))
                self.assertNotIn("ext.evil_ext.pending", [n.node_id for n in self.hub.graph().nodes()])
        self.assertEqual(self.hub.pending_proposals(), [])

    def test_an_endless_loop_is_stopped_at_the_acceptance_tests_not_run_forever(self):
        reply = self.paste(tabbed(F.malicious_pkg("endless")))
        self.assertIn("مرحله: آزمون‌های پذیرش", reply)
        self.assertIn("fuel: work budget exhausted", reply)

    def test_an_invalid_manifest_is_rejected_with_the_reason(self):
        base = loan_pkg()
        cases = {"unknown key": dict(base, shell="rm -rf /"), "no tests": dict(base, tests=[]),
                 "bad id": dict(base, id="../evil"),
                 "camera permission": dict(base, permissions=["camera"]), "os dependency": dict(base, dependencies=["os"]),
                 "wrong input type": dict(base, inputs=[{"name": "amount", "type": "file"}])}
        for name, pkg in cases.items():
            with self.subTest(case=name):
                self.assert_rejected(self.paste(pkg))

    def test_a_package_whose_own_test_is_wrong_never_becomes_active(self):
        wrong = loan_pkg(tests=[{"name": "wrong", "inputs": {"amount": 120_000_000, "annual_percent": 18, "months": 12},
                                 "expect": {"payment": 1, "total": 1}}])
        reply = self.paste(wrong)
        self.assertIn("مرحله: آزمون‌های پذیرش", reply)
        self.assert_rejected(reply)

    def test_oversized_code_and_oversized_packages_are_refused(self):
        self.assert_rejected(self.paste(loan_pkg(padding_bytes=70_000)))                    # the code alone is over 64,000 bytes
        reply = self.paste(loan_pkg(padding_bytes=60_000, filler="ص" * 150_000))            # the whole package is over 200,000 bytes
        self.assertIn("مرحله: بستهٔ ورودی", reply)
        self.assertIn("the package is larger than 200000 bytes", reply)
        self.assert_rejected(reply)
        self.assertRegex(self.ask("سلام"), PERSIAN)

    def test_a_request_body_over_the_servers_cap_is_refused_and_the_app_goes_on(self):
        status, body = self.post("/api/message", {"text": "ص" * 600_000})                   # > 1,000,000 bytes on the wire
        self.assertEqual((status, body), (413, {"error": "request body too large"}))
        self.assertEqual(self.installed_ids(), [])
        self.assertRegex(self.ask("سلام"), PERSIAN)

    def test_a_package_of_another_format_version_is_named_not_ignored(self):
        reply = self.paste(loan_pkg(schema="ext.v9"))
        self.assertIn("«ext.v9»", reply.replace("\u2066", "").replace("\u2069", ""))
        self.assertIn("فقط قالب ext.v1 را می‌شناسد", reply)
        self.assertIn("چیزی نصب یا فعال نشد", reply)
        self.assertEqual(self.installed_ids(), [])

    def test_a_failed_update_keeps_the_working_version_active(self):
        self.install(loan_pkg())
        reply = self.paste(loan_pkg(thousands=True, tests=[{"inputs": {"amount": 120_000_000, "annual_percent": 18, "months": 12},
                                                            "expect": {"payment": 7, "total": 7}}]))
        self.assertIn("مرحله: آزمون‌های پذیرش", reply)
        self.assert_rejected(reply, installed=["loan_installment"])
        self.assertEqual(self.hub.extension("loan_installment")["active_version"], 1)
        self.assertIn(loan_answer(11_001_599, 132_019_190), self.ask(LOAN_ASK))
        self.assertEqual(len(self.hub.extension_versions("loan_installment")), 1)

    def test_after_every_rejection_the_conversation_still_works(self):
        self.paste(tabbed(F.malicious_pkg("eval")))
        self.assertRegex(self.ask("سلام"), PERSIAN)
        self.assertIn("عرفان", self.ask("من عرفان هستم"))
        self.assertIn("عرفان", self.ask("اسم من چیست؟"))


# ======================================================================================= 6
class A06UpdateRollback(AppCase):
    ASK_ROLLBACK = "افزونهٔ قسط ماهانهٔ وام را برگردان"

    def update_to_v2(self):
        self.install(loan_pkg())
        proposal = self.paste(loan_pkg(thousands=True))
        self.assertIn("این به‌روزرسانی یک افزونهٔ نصب‌شده است؛ می‌شود نسخهٔ ۲ و نسخهٔ فعلی نگه داشته می‌شود", proposal)
        self.assertEqual(self.active_version("loan_installment"), 1)                  # not before the yes
        self.assertEqual(len(self.hub.extension_versions("loan_installment")), 1)
        done = self.ask("بله")
        self.assertIn("نصب و فعال شد (نسخهٔ ۲)", done)
        self.assertIn("نسخهٔ قبلی (۱) نگه داشته شد", done)

    def test_an_update_makes_a_new_version_and_rollback_restores_the_old_behaviour(self):
        self.update_to_v2()
        (amount, percent, months, payment, total) = LOAN_ROUNDED_VECTORS[0]
        v2 = self.ask(loan_sentence(amount, percent, months))
        self.assertIn(loan_answer(payment, total), v2)                                  # the new behaviour: rounded to 1,000
        self.assertIn("نسخهٔ ۲", v2)
        versions = {v["version"]: v for v in self.hub.extension_versions("loan_installment")}
        self.assertEqual(sorted(versions), [1, 2])
        self.assertNotEqual(versions[1]["fingerprint"], versions[2]["fingerprint"])
        self.assertEqual(versions[2]["parent_version"], 1)
        ask = self.ask(self.ASK_ROLLBACK)
        self.assertIn("از نسخهٔ ۲ به نسخهٔ ۱ برگردانده شود؟", ask)
        self.assertEqual(self.active_version("loan_installment"), 2)                  # asking is not rolling back
        done = self.ask("بله")
        self.assertIn("از نسخهٔ ۲ به نسخهٔ ۱ برگشت و پس از آن دوباره بررسی شد", done)
        self.assertEqual(self.active_version("loan_installment"), 1)
        old = self.ask(loan_sentence(120_000_000, 18, 12))
        self.assertIn(loan_answer(11_001_599, 132_019_190), old)                        # the old behaviour is back, exactly
        self.assertIn("نسخهٔ ۱", old)
        statuses = {v["version"]: v["status"] for v in self.hub.extension_versions("loan_installment")}
        self.assertEqual(statuses, {1: "active", 2: "rolled_back"})
        self.assertIn("به نسخهٔ قبل برگشت", self.ask("تاریخچهٔ افزونه‌ها"))

    def test_the_rolled_back_state_survives_a_restart(self):
        self.update_to_v2()
        self.ask(self.ASK_ROLLBACK)
        self.ask("بله")
        self.start_app()
        self.assertEqual(self.active_version("loan_installment"), 1)
        self.assertIn(loan_answer(11_001_599, 132_019_190), self.ask(LOAN_ASK))

    def test_declining_the_rollback_changes_nothing(self):
        self.update_to_v2()
        self.ask(self.ASK_ROLLBACK)
        self.assertIn("چیزی تغییر نکرد", self.ask("نه"))
        self.assertEqual(self.active_version("loan_installment"), 2)
        self.assertIn(loan_answer(11_002_000, 132_024_000), self.ask(LOAN_ASK))

    def test_there_is_nothing_to_roll_back_to_without_an_older_version(self):
        self.install(loan_pkg())
        self.assertIn("نسخهٔ قبلیِ سالمی برای برگشتن ندارد", self.ask(self.ASK_ROLLBACK))
        self.assertEqual(self.active_version("loan_installment"), 1)

    def test_the_same_package_again_changes_nothing(self):
        self.install(loan_pkg())
        self.assertIn("دقیقاً یکی است؛ چیزی تغییر نکرد", self.paste(loan_pkg()))
        self.assertEqual(len(self.hub.extension_versions("loan_installment")), 1)


# ======================================================================================= 7
class A07Unsupported(AppCase):
    WISHES = ("برایم یک فیلم انیمیشن از گربه بساز", "می‌تونی آهنگ بسازی؟", "به تماس‌های من جواب بده", "برای من یک بازی سه‌بعدی بساز",
              "ظاهر برنامه را شبانه کن", "هر روز ساعت ۸ در تلگرام برای من پست بگذار")

    def registry(self):
        """{node id: state} of everything except the brain's own nodes (those move with real use: evidence, not a request's effect)."""
        return {n.node_id: n.state for n in self.hub.graph().nodes() if n.kind != "brain"}

    def test_requests_beyond_the_app_get_honest_answers_without_any_false_claim(self):
        before = self.registry()
        for wish in self.WISHES:
            with self.subTest(wish=wish):
                reply = self.ask(wish)
                self.assertIn("این را هنوز نمی‌توانم انجام بدهم", reply)
                self.assertIn("آنچه واقعاً هست", reply)
                self.assertIn("آنچه کم است", reply)
                self.assertIn("قدم بعدی", reply)
                for claim in FALSE_CLAIMS:
                    self.assertNotIn(claim, reply)
        self.assertEqual(self.installed_ids(), [])
        self.assertEqual(self.registry(), before)                                       # asking changed nothing in the registry
        self.assertEqual(self.hub.pending_proposals(), [])

    def test_the_explanation_names_the_exact_missing_piece(self):
        self.assertIn("مدل تولید موسیقی/صدا", self.ask("می‌تونی آهنگ بسازی؟"))
        self.assertIn("برنامهٔ پیش‌فرض تلفن", self.ask("به تماس‌های من جواب بده"))
        self.assertIn("یک APK جدید باید ساخته و نصب شود", self.ask("می‌تونی آهنگ بسازی؟"))

    def test_an_unknown_question_is_not_dressed_up_as_knowledge(self):
        reply = self.ask("پایتون چیست؟")
        self.assertNotIn("یاد گرفتم", reply)
        self.assertNotIn("زبان", reply)
        self.assertIn("یاد گرفتم", self.ask("یاد بگیر که پایتون یک زبان برنامه‌نویسی است"))     # only a real teaching says so
        self.assertIn("زبان", self.ask("پایتون چیست؟"))

    def test_asking_how_to_extend_gives_the_prompt_and_installs_nothing(self):
        reply = self.ask("چطور افزونه اضافه کنم؟")
        self.assertIn("ext.v1", reply)
        for claim in FALSE_CLAIMS:
            self.assertNotIn(claim, reply)
        self.assertEqual(self.installed_ids(), [])


# ======================================================================================= 8
class A08Models(AppCase):
    MID = F.MODEL_ID

    def card(self, **over):
        return json.dumps(F.model_card(**over), ensure_ascii=False)

    def turn_on_internet(self):
        self.ask("اینترنت را روشن کن")
        self.assertIn("اینترنت روشن شد", self.ask("بله"))

    def node(self, node_id):
        return self.hub.graph().get(node_id)

    def test_a_registered_card_is_not_a_usable_model(self):
        self.assertEqual(self.node("tool.local_model").state, "dependency_blocked")      # no model at all
        reply = self.ask(self.card())
        self.assertIn("هنوز هیچ فایلی دریافت نشده و مدل قابل استفاده نیست", reply)
        self.assertEqual(self.stream.requests, [])
        self.assertFalse(self.hub.model_status(self.MID).usable)
        self.assertFalse(self.hub.ask_model(self.MID, "سلام").ok)
        node = self.node("model." + self.MID)
        self.assertEqual((node.state, node.usable, node.tested), ("registered", False, False))
        self.assertIn("model", [b.kind for b in node.blockers])                           # "a model file is missing"

    def test_nothing_is_downloaded_without_the_explicit_yes_and_the_internet_switch(self):
        self.ask(self.card())
        ask = self.ask("مدل %s را دانلود کن" % self.MID)
        self.assertIn("دانلود شود؟ (بله / نه)", ask)
        self.assertEqual(self.stream.requests, [])
        reply = self.ask("بله")                                                         # yes, but the app's internet is off
        self.assertIn("اجازهٔ دسترسی به اینترنت داده نشده", reply)
        self.assertEqual(self.stream.requests, [])
        self.assertFalse(self.hub.model_status(self.MID).usable)

    def test_a_model_becomes_usable_only_after_integrity_compatibility_loading_and_a_real_inference(self):
        self.turn_on_internet()
        self.ask(self.card())
        self.ask("مدل %s را دانلود کن" % self.MID)
        reply = self.ask("بله")
        stages = ("صحت فایل (اندازه و SHA-256): گذشت", "سازگاری با موتورهای موجود: گذشت", "بارگذاری در موتور: گذشت",
                  "آزمون استنتاج واقعی: گذشت", "همهٔ مراحل را گذراند و قابل استفاده است")
        positions = [reply.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))                                  # in this order, none skipped
        status = self.hub.model_status(self.MID)
        self.assertEqual((status.state, status.stage, status.usable), ("usable", "smoke", True))
        self.assertTrue(self.hub.ask_model(self.MID, "سلام").text)
        node = self.node("model." + self.MID)
        self.assertEqual((node.state, node.usable, node.tested), ("active", True, True))
        self.assertIn("generate", node.actions)

    def test_a_file_that_does_not_match_its_card_is_deleted_and_never_usable(self):
        self.turn_on_internet()
        self.stream.data = F.MODEL_BYTES[:-5] + b"abcde"                                # same size, other content
        self.ask(self.card())
        self.ask("مدل %s را دانلود کن" % self.MID)
        reply = self.ask("بله")
        self.assertIn("هش فایل دانلودشده با مقدار مورد انتظار نمی‌خواند", reply)
        self.assertIn("چیزی قابل استفاده نشد", reply)
        self.assertFalse(self.hub.model_status(self.MID).usable)
        self.assertFalse(os.path.isfile(self.hub._model_manager().model_path(self.MID)))
        self.assertFalse(self.node("model." + self.MID).usable)

    def test_a_model_no_engine_here_can_run_is_verified_but_never_usable(self):
        self.turn_on_internet()
        self.ask(self.card(format="gguf", model_id="big-gguf", title="مدل بزرگ"))
        self.ask("مدل big-gguf را دانلود کن")
        reply = self.ask("بله")
        self.assertIn("صحت فایل (اندازه و SHA-256): گذشت", reply)
        self.assertIn("سازگاری با موتورهای موجود: ناموفق", reply)
        self.assertIn("موتور لازم روی این دستگاه نصب نیست. مدل قابل استفاده نیست", reply)
        self.assertNotIn("بارگذاری در موتور", reply)                                    # it never got as far as loading
        status = self.hub.model_status("big-gguf")
        self.assertEqual((status.state, status.usable), ("verified", False))
        self.assertFalse(self.hub.ask_model("big-gguf", "سلام").ok)
        node = self.node("model.big-gguf")
        self.assertEqual((node.state, node.usable), ("dependency_blocked", False))
        self.assertIn("native_code", [b.kind for b in node.blockers])                     # "the engine for this format is not here"

    def test_usable_survives_a_restart_only_while_the_file_is_unchanged(self):
        self.turn_on_internet()
        self.ask(self.card())
        self.ask("مدل %s را دانلود کن" % self.MID)
        self.ask("بله")
        self.start_app()
        self.assertTrue(self.hub.model_status(self.MID).usable)
        path = self.hub._model_manager().model_path(self.MID)
        self.stop_app()
        with open(path, "ab") as handle:
            handle.write(b" ")                                                          # changed behind the app's back
        self.start_app()
        self.assertFalse(self.hub.model_status(self.MID).usable)
        self.assertFalse(self.node("model." + self.MID).usable)
        self.assertIn("هنوز قابل استفاده نیست", self.ask("مدل‌ها را نشان بده"))


# ======================================================================================= 9
class A09Offline(AppCase):
    def turn_on_internet(self):
        self.ask("اینترنت را روشن کن")
        self.assertIn("اینترنت روشن شد", self.ask("بله"))

    def chat_and_memory_work(self):
        self.assertRegex(self.ask("سلام"), PERSIAN)
        self.assertIn("عرفان", self.ask("من عرفان هستم"))
        self.assertIn("اسمت عرفان است", self.ask("اسم من چیست؟"))
        self.assertIn("یاد گرفتم", self.ask("یاد بگیر که پایتون یک زبان برنامه‌نویسی است"))
        self.assertIn("زبان", self.ask("پایتون چیست؟"))

    def test_with_the_internet_switch_off_a_page_is_not_read_nothing_is_sent_and_chat_and_memory_work(self):
        reply = self.ask("صفحهٔ https://example.com/a را بخوان")
        self.assertIn("اینترنت برنامه خاموش است، پس صفحه را نخواندم", reply)
        self.assertEqual(self.fetch.requests, [])
        self.assertIn("چیزی تغییر نکرد", self.ask("نه"))
        self.assertEqual(self.fetch.requests, [])
        self.chat_and_memory_work()

    def test_every_network_failure_is_stated_clearly_and_chat_and_memory_go_on(self):
        self.turn_on_internet()
        for code in ("offline", "timeout", "dns_failure", "tls_error"):
            with self.subTest(code=code):
                self.fetch.items = [TransportError(code, "")]
                reply = self.ask("صفحهٔ https://example.com/x را بخوان")
                self.assertIn(message_for(code)[0], reply)
                self.assertIn("چیزی ذخیره یا اجرا نشد", reply)
                self.assertNotIn("متن صفحه را خواندم", reply)
        self.chat_and_memory_work()

    def test_unsafe_addresses_are_refused_before_any_request(self):
        self.turn_on_internet()
        for url in ("http://example.com/a", "https://127.0.0.1/a", "https://localhost/a", "https://192.168.1.5/a",
                    "file:///etc/passwd", "ftp://example.com/a"):
            with self.subTest(url=url):
                reply = self.ask("صفحهٔ %s را بخوان" % url)
                self.assertNotIn("متن صفحه را خواندم", reply)
        self.assertEqual(self.fetch.requests, [])

    def test_a_network_extension_needs_both_its_own_permission_and_the_app_switch(self):
        self.install(tabbed(F.words_pkg()))
        reply = self.ask("کلمات صفحه https://a.test/")
        self.assertIn("اجازهٔ دسترسی به اینترنت داده نشده", reply)
        self.assertNotIn("نتیجه:", reply)
        self.assertEqual(self.fetch.requests, [])
        self.assertIn("(بله / نه)", reply)                                              # and it asks, never switches on silently
        self.ask("نه")
        self.turn_on_internet()
        self.assertIn("نتیجه: ۲", self.ask("کلمات صفحه https://a.test/"))
        self.assertEqual([r.url for r in self.fetch.requests], ["https://a.test/"])
        self.ask("اینترنت را خاموش کن")
        self.assertNotIn("نتیجه:", self.ask("کلمات صفحه https://a.test/"))
        self.assertEqual(len(self.fetch.requests), 1)

    def test_the_android_status_never_claims_a_device_test(self):
        reply = self.ask("وضعیت اندروید را بگو")
        self.assertIn("هیچ‌کدام روی دستگاه واقعی آزموده نشده", reply)
        self.assertIn("دکمهٔ پیوست", reply)
        self.assertNotIn("آزموده شد", reply)


# ======================================================================================= extension code and the chat
class A10CodeSurvivesTheChat(AppCase):
    """The chat folds every run of whitespace into one space (Core -> InputSystem.normalize), which destroys the
    indentation of Python code inside a pasted package. These tests pin how the app deals with that."""

    @staticmethod
    def code_hash(pkg):
        import hashlib
        return hashlib.sha256(pkg["source"].encode("utf-8")).hexdigest()[:12]

    def test_tab_indented_code_arrives_byte_for_byte(self):
        pkg = loan_pkg(indent="\t")
        self.assertIn(self.code_hash(pkg), self.paste(pkg))                                 # the proposal shows the hash of what arrived

    def test_space_indented_code_sent_raw_is_rejected_with_an_explanation_never_guessed(self):
        reply = self.paste(loan_pkg(indent="    "))
        self.assertIn("بسته را نپذیرفتم", reply)
        self.assertIn("expected an indented block", reply)
        self.assertIn("تورفتگی خط‌های کد موقع فرستادن از بین رفته است", reply)
        self.assertIn("\\t", reply)
        self.assertEqual(self.installed_ids(), [])

    def test_the_prompt_asks_for_tabs_and_its_own_example_installs_through_the_front_door(self):
        prompt = self.ask("پرامپت افزونه برای محاسبهٔ شاخص توده بدنی")
        self.assertIn("فقط با نویسهٔ tab بنویس و در JSON آن را به‌صورت \\t بیاور", prompt)
        blocks = re.findall(r"```json\n(.*?)\n```", prompt, flags=re.S)
        self.assertEqual(len(blocks), 1)
        self.assertIn("\\t", blocks[0])
        self.assertIn("آزمون‌ها: ۲ از ۲ موفق", self.ask("این بسته را بررسی کن:\n```json\n" + blocks[0] + "\n```"))
        self.assertIn("نصب و فعال شد", self.ask("بله"))
        self.assertIn("BMI شما ۲۲٫۹ است.", self.ask("bmi وزن 70 قد 1.75"))


# ======================================================================================= 1 + 4, the real entry point
class A12RealEntryPoint(unittest.TestCase):
    """`android_entry.start(files_dir)` itself - the function MainActivity calls through Chaquopy - in a separate process, started
    twice on the same folder; the first process is KILLED (not stopped politely). No doubles: the web transport is the real one and
    none of these flows uses it (the internet switch stays off), so no network is needed."""

    SCRIPT = ("import os, sys, time\n"
              "sys.dont_write_bytecode = True\n"
              "sys.path.insert(0, sys.argv[3])\n"
              "os.chdir(sys.argv[1])\n"
              "import android_entry\n"
              "android_entry.PORT = int(sys.argv[2])\n"
              "print('READY', android_entry.start(sys.argv[1]), flush=True)\n"
              "while True:\n"
              "    time.sleep(1)\n")

    def setUp(self):
        self.files = tempfile.mkdtemp(prefix="entry_")
        self.log_path = os.path.join(tempfile.gettempdir(), "entry_%d.log" % os.getpid())
        self.addCleanup(shutil.rmtree, self.files, ignore_errors=True)
        self.proc = None
        self.url = ""
        self.addCleanup(self.kill)

    def kill(self):
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)

    def start(self):
        self.kill()
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        with open(self.log_path, "w") as log:
            self.proc = subprocess.Popen([sys.executable, "-B", "-c", self.SCRIPT, self.files, str(port), PY_ROOT],
                                         stdout=log, stderr=subprocess.STDOUT, cwd=self.files)
        self.url = "http://127.0.0.1:%d" % port
        deadline = time.time() + 90
        while time.time() < deadline:
            if self.proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(self.url + "/api/status", timeout=2):
                    return
            except OSError:
                time.sleep(0.2)
        with open(self.log_path, encoding="utf-8", errors="replace") as log:
            self.fail("the app did not come up:\n" + log.read()[-2000:])

    def ask(self, text):
        data = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.url + "/api/message", data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=60) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode("utf-8"))["reply"]

    def test_a_fresh_start_serves_the_page_and_a_persian_message_reaches_the_runtime_and_memory_survives_a_kill(self):
        self.start()
        with urllib.request.urlopen(self.url + "/", timeout=20) as response:
            page = response.read().decode("utf-8")
        for needle in ('lang="fa"', 'id="input-box"', 'id="attach-btn"'):
            self.assertIn(needle, page)
        self.assertRegex(self.ask("سلام"), PERSIAN)
        self.assertIn("عرفان", self.ask("من عرفان هستم"))
        self.assertTrue(os.path.isfile(os.path.join(self.files, "data", "memory.db")))      # app-private storage, laid out by the adapter
        self.start()                                                                         # the first process was killed, not closed
        self.assertIn("اسمت عرفان است", self.ask("اسم من چیست؟"))

    def test_a_capability_added_in_the_running_app_survives_the_process_being_killed(self):
        pkg = loan_pkg(indent="\t")
        self.start()
        self.assertNotIn("قسط ماهانه:", self.ask(LOAN_ASK))
        self.assertIn("هنوز چیزی نصب یا فعال نشده", self.ask("این بسته را بررسی کن:\n```json\n" + json.dumps(pkg, ensure_ascii=False, indent=1) + "\n```"))
        self.assertIn("نصب و فعال شد", self.ask("بله"))
        self.assertIn(loan_answer(11_001_599, 132_019_190), self.ask(LOAN_ASK))
        self.start()
        reply = self.ask(LOAN_ASK)                                                           # no APK rebuild, no re-install, no Claude
        self.assertIn(loan_answer(11_001_599, 132_019_190), reply)
        self.assertIn("افزونهٔ «قسط ماهانهٔ وام» · نسخهٔ ۱", reply)
        listing = self.ask("افزونه‌ها را لیست کن")
        self.assertIn("«قسط ماهانهٔ وام»", listing)
        self.assertIn("— فعال، نسخهٔ ۱، آزمون‌شده", listing)
        self.assertTrue(os.path.isdir(os.path.join(self.files, "data", "brain_hub")))


if __name__ == "__main__":
    unittest.main()
