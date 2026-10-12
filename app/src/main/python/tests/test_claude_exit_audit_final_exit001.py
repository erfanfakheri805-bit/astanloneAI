"""
FINAL-EXIT-001 - the "Claude Exit Audit", end to end through the real Android entry point.

Scenario (all in Persian, over the real HTTP route the WebView uses, against the real
`android_entry.start(files_dir)` running in SEPARATE processes that are killed with SIGKILL
and started again on the same app-private directory):

    "I need a new supported capability that does not currently exist"
      -> the app understands the request, finds the capability missing, asks what it needs,
         designs the change, generates the module, validates it (AST allowlist), tests it
         (differential suite), applies it, persists it, registers it, versions it, audits it;
      -> the process is killed and restarted: the capability, its version and its history are
         still there and answer correctly - with no Claude, no network, no model;
      -> it can be improved (new version), rolled back after negative feedback, and a tampered
         module file is detected after a restart and replaced by the previous healthy version.

Also covered here: the AEL `UPGRADE` statement reaching the Self-Builder, the "I do not have
this - shall I build it?" offer, lazy creation (nothing is created for ordinary conversation),
the application's source tree and the seven hash-pinned production files staying untouched, and
no network / subprocess / external-AI activity in the running application, and the
documentation (docs/self_builder_final_exit.md) still naming only files, limits and archetypes
that exist.

Run directly:
    python -m unittest tests.test_claude_exit_audit_final_exit001 -v
"""

import hashlib
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The production files the earlier prompts pinned: FINAL-EXIT-001 must not change them.
PINNED = {
    "android_entry.py": "ffa9d214a53e4aeb7e043f65ade9a398c4be2fd7d6e2dc69f4e7ce1c6bc40c07",
    "core/core.py": "64dbaef03caba1b1bc43795a21516dfce04c68d01c68f22c1f97ae98b7f77d0b",
    "ael/interpreter.py": "8c96be945ef91e5ba33c7290d6483801d7acd1beba7d14ab846dd9a7f8f3984b",
    "runtime_integration/bridge.py": "4b2177f0153d05741bc07d196f6fbadf7917521da71f4804761588564383bfac",
    "interface/server.py": "97f3f0659fb2881690db4b02340508156ba24039c0846551098fb3343aabb642",
    "runtime_integration/runtime_core.py": "610e0c5c51f47fc95f574cd90958a6a94f61c803f114d388f435cbc85f658cdf",
    "runtime_growth/runtime_growth_cycle.py": "d7015ed497e4fef18280c1b6592c13a5c415ff8226568b349aefa07205dd2bcd",
}

# What the running application must never do (recorded by an audit hook inside the process).
SERVER_SCRIPT = r'''
import os, sys, time
sys.dont_write_bytecode = True
py_root, files_dir, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
sys.path.insert(0, py_root)
os.chdir(files_dir)                      # the real app's working directory is unrelated to its code
_LOCAL = {"127.0.0.1", "::1", "localhost", ""}
def _hook(event, args):
    try:
        if event == "socket.connect":
            addr = args[1]
            host = addr[0] if isinstance(addr, tuple) else str(addr)
            if host not in _LOCAL:
                print("AUDIT connect " + str(host), flush=True)
        elif event in ("socket.getaddrinfo", "socket.gethostbyname"):
            host = args[0]
            if isinstance(host, (bytes, bytearray)):
                host = host.decode("ascii", "replace")
            if host not in _LOCAL and host is not None:
                print("AUDIT resolve " + str(host), flush=True)
        elif event in ("subprocess.Popen", "os.system", "os.posix_spawn", "os.fork", "os.exec", "ctypes.dlopen"):
            print("AUDIT exec " + event, flush=True)
    except Exception:
        pass
sys.addaudithook(_hook)
import android_entry
android_entry.PORT = port
url = android_entry.start(files_dir)
print("READY " + url, flush=True)
while True:
    time.sleep(0.5)
'''

STAGE_LABELS_IN_ORDER = [
    "دریافت درخواست", "تحلیل درخواست", "تنظیم مشخصات", "بررسی قابلیت‌های موجود", "شناسایی کمبود", "طرح تغییر",
    "تولید فایل‌ها", "اعتبارسنجی امنیتی", "آزمون", "نقطهٔ بازگشت", "اعمال", "ذخیره‌سازی",
    "ثبت در فهرست قابلیت‌ها", "نسخه‌گذاری", "ثبت ممیزی",
]


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_fingerprint(root):
    """(relative path, size, mtime_ns) of every file, ignoring byte-code caches."""
    out = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".pyc"):
                continue
            path = os.path.join(base, name)
            st = os.stat(path)
            out[os.path.relpath(path, root)] = (st.st_size, st.st_mtime_ns)
    return out


class AppProcess:
    """One run of the real Android entry point (android_entry.start) in its own process."""

    def __init__(self, files_dir):
        self.files_dir = files_dir
        self.port = _free_port()
        self.audit = []
        self.lines = []
        self.proc = None

    def start(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        for name in ("STANDALONE_AI_PERSIAN_BRAIN", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy",
                     "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"):
            env.pop(name, None)
        self.proc = subprocess.Popen(
            [sys.executable, "-B", "-c", SERVER_SCRIPT, PY_ROOT, self.files_dir, str(self.port)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env,
            cwd=self.files_dir)
        ready = threading.Event()

        def pump():
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                self.lines.append(line)
                if line.startswith("AUDIT "):
                    self.audit.append(line)
                if line.startswith("READY "):
                    ready.set()
            ready.set()

        self.reader = threading.Thread(target=pump, daemon=True)
        self.reader.start()
        if not ready.wait(90) or not any(l.startswith("READY ") for l in self.lines):
            self.kill()
            raise RuntimeError("application did not start: " + "\n".join(self.lines[-20:]))
        return self

    def say(self, text):
        data = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/message", data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))["reply"]

    def kill(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGKILL)
            self.proc.wait(30)
        reader = getattr(self, "reader", None)
        if reader is not None:
            reader.join(10)                       # the pump ends at EOF; then nothing reads the pipe any more
        if self.proc is not None and self.proc.stdout is not None:
            self.proc.stdout.close()


def persian_digits_to_float(text):
    """'۶٫۲۱۳۷۱۲' -> 6.213712 (the test's own reader of the app's Persian number format)."""
    table = str.maketrans("۰۱۲۳۴۵۶۷۸۹٫", "0123456789.")
    return float(text.translate(table))


def number_after_equals(reply):
    """The first number after '=' in a reply like '۱۰ کیلومتر = ۶٫۲۱۳۷۱۲ مایل'."""
    m = re.search(r"=\s*([۰-۹]+(?:٫[۰-۹]+)?)", reply)
    return persian_digits_to_float(m.group(1)) if m else None


class TestClaudeExitScenario(unittest.TestCase):
    """The whole scenario runs once (setUpClass); each test asserts one requirement."""

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="final_exit001_")
        cls.files_dir = os.path.join(cls.base, "files")
        os.makedirs(cls.files_dir)
        cls.sb_root = os.path.join(cls.files_dir, "data", "self_builder")
        cls.t = {}
        cls.processes = []
        cls.tree_before = tree_fingerprint(PY_ROOT)
        try:
            cls._run_scenario()
        except BaseException:
            cls._cleanup()
            raise
        cls.tree_after = tree_fingerprint(PY_ROOT)

    @classmethod
    def _cleanup(cls):
        for p in cls.processes:
            p.kill()
        shutil.rmtree(cls.base, ignore_errors=True)

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    @classmethod
    def _proc(cls):
        p = AppProcess(cls.files_dir).start()
        cls.processes.append(p)
        return p

    @classmethod
    def _run_scenario(cls):
        t = cls.t
        # ---- process 1: a fresh installation --------------------------------------------------
        p1 = cls._proc()
        t["greet"] = p1.say("سلام")
        t["need_kind"] = p1.say("من یک قابلیت جدید نیاز دارم")
        t["data_before_build"] = sorted(os.listdir(os.path.join(cls.files_dir, "data")))
        t["sb_exists_before_build"] = os.path.exists(cls.sb_root)
        t["built_km"] = p1.say("تبدیل کیلومتر به مایل")
        t["sb_exists_after_build"] = os.path.isdir(cls.sb_root)
        t["km10"] = p1.say("۱۰ کیلومتر چند مایل است؟")
        t["name"] = p1.say("من عرفان هستم")
        t["ask_name"] = p1.say("اسم من چیه؟")
        t["teach"] = p1.say("یاد بگیر که پایتون یک زبان برنامه نویسی است")
        t["know"] = p1.say("پایتون چیست؟")
        t["english"] = p1.say("hello")
        p1.kill()
        # ---- process 2: after the application was killed --------------------------------------
        p2 = cls._proc()
        t["km25"] = p2.say("۲۵ کیلومتر چند مایل است؟")
        t["list2"] = p2.say("چه کارهایی بلدی؟")
        t["ask_name2"] = p2.say("اسم من چیه؟")
        t["know2"] = p2.say("پایتون چیست؟")
        t["greet2"] = p2.say("سلام")
        t["gap_offer"] = p2.say("۳ متر چند فوت است؟")
        t["gap_yes"] = p2.say("بله")
        t["ft_improve"] = p2.say("یک مبدل متر به فوت بساز که هر ۱ متر برابر ۳ فوت است")
        t["ft_confirm"] = p2.say("بله")
        t["ft_v2_answer"] = p2.say("۳ متر چند فوت است؟")
        t["ft_bad"] = p2.say("جواب غلط بود")
        t["ft_rollback"] = p2.say("بله")
        t["ft_v1_answer"] = p2.say("۳ متر چند فوت است؟")
        t["km_improve"] = p2.say("یک مبدل کیلومتر به مایل بساز که هر ۱ کیلومتر برابر ۰٫۶ مایل است")
        t["km_confirm"] = p2.say("بله")
        t["km_v2_answer"] = p2.say("۱۰ کیلومتر چند مایل است؟")
        t["ael_upgrade"] = p2.say("UPGRADE word_counter IS ابزاری بساز که تعداد کلمات متن را بشمارد")
        t["count"] = p2.say("تعداد کلمات را بشمار: سلام دنیای زیبا")
        t["ael_old_upgrade"] = p2.say("UPGRADE faster_matching IS improve the matching speed")
        t["history"] = p2.say("تاریخچه ساخت قابلیت ها")
        t["unsupported"] = p2.say("یک نرم‌افزار حسابداری بساز")
        p2.kill()
        # ---- between runs: somebody modifies the active module file of km->mi (v2) on disk -----
        t["tampered_file"] = cls._tamper_active_module("unit_km_to_mi")
        # ---- process 3 --------------------------------------------------------------------------
        p3 = cls._proc()
        t["km_after_tamper"] = p3.say("۱۰ کیلومتر چند مایل است؟")
        t["detail_km"] = p3.say("جزئیات تبدیل کیلومتر به مایل")
        t["status3"] = p3.say("وضعیت قابلیت‌ها")
        t["ft_after_restart"] = p3.say("۳ متر چند فوت است؟")
        t["count_after_restart"] = p3.say("تعداد کلمات را بشمار: یک دو سه چهار")
        t["list3"] = p3.say("چه کارهایی بلدی؟")
        p3.kill()
        cls.audit_lines = [l for p in cls.processes for l in p.audit]

    @classmethod
    def _tamper_active_module(cls, capability_id):
        db = sqlite3.connect(os.path.join(cls.sb_root, "self_builder.db"))
        try:
            row = db.execute(
                "SELECT v.module_file FROM capability_versions v JOIN capabilities c "
                "ON c.capability_id = v.capability_id AND c.active_version = v.version "
                "WHERE c.capability_id = ?", (capability_id,)).fetchone()
        finally:
            db.close()
        path = os.path.join(cls.sb_root, "modules", row[0])
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n# edited by hand\n")
        return row[0]

    # ------------------------------------------------------------------ the scenario's answers
    def test_01_social_conversation_is_persian(self):
        self.assertTrue(self.t["greet"].startswith("سلام"), self.t["greet"])
        self.assertRegex(self.t["greet"], r"[آ-ی]")
        self.assertNotIn("I'm a very early version", self.t["greet"])

    def test_02_the_missing_capability_request_is_understood_and_clarified(self):
        reply = self.t["need_kind"]
        self.assertIn("چه نوع قابلیتی", reply)
        for kind in ("تبدیل واحد", "فرمول", "ابزار متنی"):
            self.assertIn(kind, reply)

    def test_03_nothing_is_created_for_ordinary_conversation(self):
        self.assertFalse(self.t["sb_exists_before_build"])
        self.assertEqual(self.t["data_before_build"], ["memory.db"])

    def test_04_capability_is_built_validated_tested_and_reported(self):
        reply = self.t["built_km"]
        self.assertIn("ساختم", reply)
        self.assertIn("«تبدیل کیلومتر به مایل»", reply)
        m = re.search(r"آزمون‌های خودکار: ([۰-۹]+) از ([۰-۹]+) موفق", reply)
        self.assertIsNotNone(m, reply)
        passed, total = m.group(1), m.group(2)
        self.assertEqual(passed, total)
        self.assertGreater(persian_digits_to_float(total), 5)
        self.assertIn("در حافظهٔ ماندگار ثبت شد", reply)
        self.assertTrue(self.t["sb_exists_after_build"])

    def test_05_reply_lists_the_real_pipeline_stages_in_order(self):
        line = next(l for l in self.t["built_km"].splitlines() if l.startswith("مراحل:"))
        positions = [line.index(label) for label in STAGE_LABELS_IN_ORDER]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(len(set(positions)), len(positions))

    def test_06_the_new_capability_gives_the_correct_number_at_once(self):
        value = number_after_equals(self.t["km10"])
        self.assertIsNotNone(value, self.t["km10"])
        self.assertAlmostEqual(value, 6.213712, places=6)            # 10 km = 6.2137119 mi
        self.assertIn("مایل", self.t["km10"])

    def test_07_it_still_works_after_the_application_was_killed_and_restarted(self):
        self.assertAlmostEqual(number_after_equals(self.t["km25"]), 15.53428, places=5)   # 25 km
        self.assertIn("«تبدیل کیلومتر به مایل»", self.t["list2"])

    def test_08_memory_and_knowledge_also_survive_the_restart(self):
        self.assertIn("عرفان", self.t["ask_name"])
        self.assertIn("عرفان", self.t["ask_name2"])
        self.assertIn("زبان برنامه", self.t["know"])
        self.assertIn("زبان برنامه", self.t["know2"])
        self.assertIn("عرفان", self.t["greet2"])                    # the greeting uses the stored name

    def test_09_a_missing_capability_is_offered_honestly_then_built_and_used(self):
        offer = self.t["gap_offer"]
        self.assertIn("هنوز ندارم", offer)
        self.assertIn("«تبدیل متر به فوت»", offer)
        self.assertIn("بسازمش", offer)
        built = self.t["gap_yes"]
        self.assertIn("ساختم", built)
        self.assertIn("جواب سؤالت", built)
        self.assertAlmostEqual(number_after_equals(built.split("جواب سؤالت")[1]), 9.84252, places=5)  # 3 m

    def test_10_a_deviating_user_factor_needs_confirmation_then_creates_version_2(self):
        self.assertIn("ضریب", self.t["ft_improve"])
        self.assertIn("(بله / نه)", self.t["ft_improve"])
        self.assertIn("ارتقا دادم", self.t["ft_confirm"])
        self.assertIn("نسخه‌ی ۲", self.t["ft_confirm"])
        self.assertAlmostEqual(number_after_equals(self.t["ft_v2_answer"]), 9.0, places=6)

    def test_11_negative_feedback_offers_a_rollback_and_the_rollback_really_happens(self):
        self.assertIn("بازخوردت را برای همین نسخه ثبت کردم", self.t["ft_bad"])
        self.assertIn("برگردانم", self.t["ft_bad"])
        self.assertIn("برگشتم", self.t["ft_rollback"])
        self.assertIn("راستی‌آزمایی", self.t["ft_rollback"])
        self.assertAlmostEqual(number_after_equals(self.t["ft_v1_answer"]), 9.84252, places=5)

    def test_12_the_rollback_survives_a_restart(self):
        self.assertAlmostEqual(number_after_equals(self.t["ft_after_restart"]), 9.84252, places=5)

    def test_13_ael_upgrade_reaches_the_self_builder_and_old_style_upgrades_still_work(self):
        self.assertIn("[AEL OK]", self.t["ael_upgrade"])
        self.assertIn("status: installed (stage: version)", self.t["ael_upgrade"])
        self.assertIn("شمارش کلمات: ۳", self.t["count"])
        self.assertIn("[AEL OK]", self.t["ael_old_upgrade"])
        self.assertIn("faster_matching", self.t["ael_old_upgrade"])
        self.assertIn("شمارش کلمات: ۴", self.t["count_after_restart"])

    def test_14_unsupported_requests_are_refused_honestly(self):
        reply = self.t["unsupported"]
        self.assertIn("نمی‌توانم", reply)
        self.assertIn("برنامه‌نویس", reply)
        self.assertIn("تبدیل واحد", reply)

    def test_15_history_tells_what_was_built(self):
        self.assertIn("آخرین تغییرات", self.t["history"])
        self.assertIn("ساخت", self.t["history"])
        self.assertIn("«تبدیل متر به فوت»", self.t["history"])

    def test_16_a_tampered_module_is_detected_after_restart_and_the_healthy_version_serves(self):
        self.assertTrue(self.t["tampered_file"].endswith(".py"))
        self.assertEqual(self.t["km_v2_answer"].count("۶ مایل"), 1, self.t["km_v2_answer"])      # v2 = 0.6
        self.assertAlmostEqual(number_after_equals(self.t["km_after_tamper"]), 6.213712, places=6)  # back to v1
        self.assertIn("خراب", self.t["detail_km"])
        self.assertIn("مشکل‌هایی را خودم برطرف کردم", self.t["status3"])
        self.assertIn("زنجیرهٔ ممیزی سالم است", self.t["status3"])

    def test_17_the_capability_list_is_honest_about_what_exists(self):
        for title in ("«تبدیل کیلومتر به مایل»", "«تبدیل متر به فوت»", "«شمارش کلمات»"):
            self.assertIn(title, self.t["list3"])

    def test_18_english_input_is_left_to_the_existing_pipeline(self):
        self.assertIn("Hello!", self.t["english"])

    # ---------------------------------------------------------------- state on disk / safety
    def test_20_registry_on_disk_is_complete_and_the_audit_chain_is_intact(self):
        from self_builder.service import SelfBuilderService
        service = SelfBuilderService(self.sb_root)
        try:
            status = service.status()
            self.assertTrue(status["audit_chain"]["ok"])
            ids = {c["id"]: c for c in service.capabilities()}
            self.assertEqual(set(ids), {"unit_km_to_mi", "unit_m_to_ft", "text_count_words"})
            self.assertTrue(all(c["status"] == "active" for c in ids.values()))
            self.assertEqual(ids["unit_km_to_mi"]["version"], 1)              # v2 was broken -> v1 restored
            km_versions = {v["version"]: v["status"] for v in ids["unit_km_to_mi"]["versions"]}
            self.assertEqual(km_versions, {1: "active", 2: "broken"})
            ft_versions = {v["version"]: v["status"] for v in ids["unit_m_to_ft"]["versions"]}
            self.assertEqual(ft_versions, {1: "active", 2: "rolled_back"})
            self.assertTrue(service.self_check()["ok"])
        finally:
            service.close()

    def test_21_the_tampered_file_was_quarantined_not_deleted(self):
        quarantine = os.path.join(self.sb_root, "quarantine")
        names = os.listdir(quarantine)
        self.assertTrue(any(self.t["tampered_file"] in n for n in names), names)

    def test_22_legacy_registries_in_memory_db_tell_the_truth(self):
        db = sqlite3.connect(os.path.join(self.files_dir, "data", "memory.db"))
        try:
            caps = {r[0]: (r[1], r[2]) for r in db.execute("SELECT name, enabled, status FROM capabilities")}
            for cid in ("unit_km_to_mi", "unit_m_to_ft", "text_count_words"):
                self.assertEqual(caps[cid][0], 1, cid)
            names = [r[0] for r in db.execute("SELECT name FROM upgrades")]
            self.assertIn("word_counter", names)
            self.assertIn("faster_matching", names)
            labels = [r[0] for r in db.execute("SELECT version_label FROM versions")]
            self.assertIn("unit_km_to_mi@v1", labels)
            self.assertIn("text_count_words@v1", labels)
        finally:
            db.close()

    def test_23_no_network_subprocess_or_external_ai_activity_in_the_running_application(self):
        self.assertEqual(self.audit_lines, [])

    def test_24_the_application_source_tree_was_never_written(self):
        self.assertEqual(self.tree_before, self.tree_after)

    def test_25_writable_state_lives_only_under_the_app_private_directory(self):
        top = sorted(os.listdir(self.files_dir))
        self.assertTrue(set(top) <= {"data", "skills_definitions", "tmp"}, top)
        self.assertEqual(sorted(os.listdir(self.sb_root)),
                         sorted(["self_builder.db", "self_builder.lock", "manifest.json", "modules", "tests", "specs",
                                 "checkpoints", "quarantine", "staging"] + [n for n in os.listdir(self.sb_root)
                                                            if n.startswith("self_builder.db-")]))

    def test_26_pinned_production_files_are_byte_identical(self):
        for rel, expected in PINNED.items():
            self.assertEqual(_sha256(os.path.join(PY_ROOT, rel)), expected, rel)


class TestDocumentationMatchesTheCode(unittest.TestCase):
    """docs/self_builder_final_exit.md quotes module names, test files, limits and archetypes: they must stay true."""

    DOC = os.path.abspath(os.path.join(PY_ROOT, "..", "..", "..", "..", "docs", "self_builder_final_exit.md"))

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(cls.DOC):
            raise unittest.SkipTest("the documentation is not part of this checkout layout")
        with open(cls.DOC, encoding="utf-8") as f:
            cls.raw = f.read()
        cls.text = " ".join(cls.raw.split())               # one line: the document wraps its sentences

    def modules_of(self, package):
        return sorted(n for n in os.listdir(os.path.join(PY_ROOT, package)) if n.endswith(".py"))

    def test_every_python_file_the_document_names_exists(self):
        names = set(re.findall(r"`((?:[A-Za-z_]+/)*[A-Za-z_0-9]+\.py)`", self.raw))
        described = set(self.modules_of("self_builder")) - {"__init__.py"}
        self.assertEqual(described - names, set(), "every module of self_builder/ must be described")
        homes = ("", "self_builder", "persian_brain", "tests")
        for name in sorted(names):
            self.assertTrue(any(os.path.isfile(os.path.join(PY_ROOT, home, name)) for home in homes), name)

    def test_the_module_counts_are_those_of_the_packages(self):
        for package in ("self_builder", "persian_brain"):
            self.assertIn(f"## {3 if package == 'self_builder' else 8}. Package `{package}/` "
                          f"({len(self.modules_of(package))} modules)", self.text, package)

    def test_the_test_command_lists_exactly_the_five_test_modules_of_this_task(self):
        listed = re.findall(r"tests\.(test_[a-z_0-9]+_final_exit001)", self.raw)
        on_disk = sorted(n[:-3] for n in os.listdir(os.path.join(PY_ROOT, "tests")) if n.endswith("_final_exit001.py"))
        self.assertEqual(sorted(set(listed)), on_disk)
        self.assertEqual(len(on_disk), 5)

    def test_the_limits_quoted_are_the_limits_enforced(self):
        from self_builder import policy
        quoted = (f"source {policy.MAX_SOURCE_BYTES:,} bytes, tests {policy.MAX_TESTS_BYTES:,} bytes, expression "
                  f"{policy.MAX_EXPR_CHARS} characters / {policy.MAX_EXPR_NODES} nodes / depth {policy.MAX_EXPR_DEPTH}, "
                  f"{policy.MAX_VARIABLES} variables, {policy.MAX_TEST_CASES} test cases, {policy.MAX_CAPABILITIES} "
                  f"capabilities, {policy.MAX_VERSIONS_PER_CAPABILITY} versions per capability, request "
                  f"{policy.MAX_REQUEST_CHARS:,} characters, {policy.MAX_INVOKE_TEXT_CHARS:,} characters of text input "
                  f"per call, {policy.MAX_CALL_SECONDS} s per call")
        self.assertIn(quoted, self.text)
        self.assertIn(f"`MAX_REPAIR_ATTEMPTS = {policy.MAX_REPAIR_ATTEMPTS}`", self.text)

    def test_the_archetypes_quoted_are_the_supported_ones(self):
        from self_builder import policy
        table = re.findall(r"^\| `([a-z_]+)` \| ", self.raw.split("## 2.")[0], flags=re.MULTILINE)
        self.assertEqual(sorted(table), sorted(policy.SUPPORTED_ARCHETYPES))

    def test_the_pinned_files_named_are_the_pinned_files_checked(self):
        section = self.text.split("## 7.")[1].split("## 8.")[0]
        named = set(re.findall(r"`([a-z_/]+\.py)`", section.split("Three existing")[0]))
        self.assertEqual(named, set(PINNED))


if __name__ == "__main__":
    unittest.main()
