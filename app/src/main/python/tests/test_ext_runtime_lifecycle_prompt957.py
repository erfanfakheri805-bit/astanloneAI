"""
PROMPT 957 - extension runtime: lifecycle of a user-supplied extension.

propose -> test -> explicit approval -> activate -> call from chat text -> update -> rollback -> restart -> corruption.
Covers acceptance behaviours 3-6: a new capability defined through the extension mechanism is validated, tested,
registered and invoked; it survives a restart; a failed or malicious extension is rejected and never active; an update
creates a new version and a rollback restores the previous behaviour.

Run directly:
    python -m unittest tests.test_ext_runtime_lifecycle_prompt957 -v
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ext_runtime import hubstore
from ext_runtime.lifecycle import ExtensionManager, PROPOSAL_TTL_SECONDS


def tip_pkg(factor=100, **over):
    pkg = {
        "schema": "ext.v1", "id": "tip_calc", "title": "محاسبهٔ انعام",
        "description": "مبلغ انعام را از صورتحساب و درصد حساب می‌کند.",
        "inputs": [{"name": "bill", "type": "number", "min": 0}, {"name": "percent", "type": "number", "default": 10, "required": False, "max": 1000}],
        "outputs": [{"name": "tip", "type": "number", "label": "انعام"}],
        "source": "def run(bill, percent):\n    if percent > 100:\n        raise ValueError('too large')\n    return {'tip': round(bill * percent / %d, 2)}\n" % factor,
        "triggers": ["انعام {bill} با {percent} درصد", "انعام {bill}"],
        "tests": [{"name": "fifteen", "inputs": {"bill": 200, "percent": 15}, "expect": {"tip": 200 * 15 / factor}},
                  {"name": "default", "inputs": {"bill": 50}, "expect": {"tip": 50 * 10 / factor}},
                  {"name": "too large", "inputs": {"bill": 10, "percent": 150}, "expect_error": True}],
    }
    pkg.update(over)
    return pkg


def words_pkg():
    return {
        "schema": "ext.v1", "id": "word_counter", "title": "شمارندهٔ کلمات",
        "description": "تعداد کلمات و حروف یک متن را می‌شمارد.",
        "inputs": [{"name": "text", "type": "text"}],
        "outputs": [{"name": "words", "type": "integer", "label": "کلمات"}, {"name": "letters", "type": "integer", "label": "حروف"}],
        "source": "def run(text):\n    parts = text.split()\n    return {'words': len(parts), 'letters': sum(len(p) for p in parts)}\n",
        "triggers": ["کلمات {text} را بشمار"],
        "answer": "{words} کلمه و {letters} حرف",
        "tests": [{"inputs": {"text": "a bb ccc"}, "expect": {"words": 3, "letters": 6}}],
    }


def counter_pkg():
    return {
        "schema": "ext.v1", "id": "visit_counter", "title": "شمارندهٔ بازدید",
        "description": "هر بار صدا زده شود یک واحد می‌شمارد.",
        "inputs": [{"name": "step", "type": "integer", "default": 1, "required": False}],
        "outputs": [{"name": "count", "type": "integer"}, {"name": "at", "type": "number"}],
        "permissions": ["storage", "clock"],
        "source": "def run(step):\n    n = store_get('n', 0) + step\n    store_put('n', n)\n    return {'count': n, 'at': clock_now()}\n",
        "triggers": ["بشمار {step}", "بشمار"],
        "tests": [{"inputs": {"step": 2}, "expect": {"count": 7, "at": 100}}],
        "fixtures": {"clock": 100, "store": {"n": 5}},
    }


def web_pkg():
    return {
        "schema": "ext.v1", "id": "page_title", "title": "عنوان صفحه",
        "description": "عنوان یک صفحهٔ وب را می‌خواند.",
        "inputs": [{"name": "url", "type": "text"}],
        "outputs": [{"name": "title", "type": "text"}],
        "permissions": ["network"],
        "source": "def run(url):\n    page = web_fetch_text(url)\n    start = page.find('<title>')\n    end = page.find('</title>')\n    if start < 0 or end < 0:\n        raise ValueError('no title')\n    return {'title': page[start + 7:end]}\n",
        "triggers": ["عنوان صفحه {url}"],
        "tests": [{"inputs": {"url": "https://a.test/"}, "expect": {"title": "Hello"}}],
        "fixtures": {"web": {"https://a.test/": "<html><title>Hello</title></html>"}},
    }


MALICIOUS = {
    "escape": "def run(bill, percent):\n    return ().__class__.__bases__[0].__subclasses__()\n",
    "import": "import os\ndef run(bill, percent):\n    return os.getcwd()\n",
    "open": "def run(bill, percent):\n    return open('/etc/passwd').read()\n",
    "endless": "def run(bill, percent):\n    while True:\n        pass\n",
}


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hub957_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.now = [1_700_000_000.0]
        self.managers = []

    def tearDown(self):
        for m in self.managers:
            m.close()

    def mgr(self, **kw):
        kw.setdefault("clock", lambda: self.now[0])
        m = ExtensionManager(self.root, **kw)
        self.managers.append(m)
        return m

    def install(self, m, pkg):
        r = m.propose(json.dumps(pkg, ensure_ascii=False))
        self.assertEqual(r["status"], "pending_approval", r)
        a = m.approve(r["proposal_id"])
        self.assertEqual(a["status"], "applied", a)
        return a

    def files(self, sub):
        return sorted(os.listdir(os.path.join(self.root, sub)))


class TestProposeApproveInvoke(Base):
    def test_nothing_is_active_before_the_user_approves(self):
        m = self.mgr()
        r = m.propose(json.dumps(tip_pkg(), ensure_ascii=False))
        self.assertEqual((r["status"], r["capability_id"], r["action"], r["planned_version"]), ("pending_approval", "tip_calc", "create", 1))
        self.assertEqual(r["tests"], {"passed": 3, "total": 3})
        self.assertEqual(m.list_capabilities(), [])
        self.assertEqual(m.match("انعام 200 با 15 درصد")["status"], "none")
        self.assertEqual(m.invoke("tip_calc", {"bill": 1})["status"], "not_found")
        self.assertEqual(self.files("modules") + self.files("manifests"), [])
        self.assertEqual([p["capability_id"] for p in m.pending()], ["tip_calc"])
        self.assertEqual(r["review"]["permissions"], [])

    def test_approving_installs_registers_and_verifies_the_version(self):
        m = self.mgr()
        a = self.install(m, tip_pkg())
        self.assertEqual((a["version"], a["previous_version"], a["permissions_granted"]), (1, None, []))
        self.assertEqual(a["verified"]["loadable"], True)
        self.assertEqual(a["verified"]["tests"], {"passed": 3, "total": 3, "deterministic": True})
        self.assertEqual(self.files("modules"), ["tip_calc_v1.py"])
        self.assertEqual(self.files("manifests"), ["tip_calc_v1.json"])
        info = m.get("tip_calc")
        self.assertEqual((info["state"], info["tested"], info["active_version"], info["kind"]), ("active", True, 1, "extension"))
        self.assertEqual(m.pending(), [])

    def test_a_chat_sentence_reaches_the_extension_and_gets_a_persian_answer(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        hit = m.match("لطفا انعام ۲۰۰ با ۱۵ درصد")
        self.assertEqual((hit["status"], hit["capability_id"], hit["inputs"]), ("invoke", "tip_calc", {"bill": 200, "percent": 15}))
        r = m.invoke(hit["capability_id"], hit["inputs"])
        self.assertTrue(r["ok"])
        self.assertEqual((r["outputs"], r["answer"], r["version"]), ({"tip": 30.0}, "نتیجه: ۳۰", 1))
        self.assertEqual(m.match("انعام صد")["inputs"], {"bill": 100, "percent": 10})

    def test_a_second_unrelated_capability_is_defined_without_any_code_change(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        self.install(m, words_pkg())
        hit = m.match("کلمات «سلام دنیا چطوری» را بشمار")
        self.assertEqual((hit["status"], hit["capability_id"]), ("invoke", "word_counter"))
        r = m.invoke("word_counter", hit["inputs"])
        self.assertEqual((r["outputs"], r["answer"]), ({"words": 3, "letters": 13}, "\u06f3 \u06a9\u0644\u0645\u0647 \u0648 \u06f1\u06f3 \u062d\u0631\u0641"))
        self.assertEqual([c["capability_id"] for c in m.list_capabilities()], ["tip_calc", "word_counter"])

    def test_declining_or_approving_twice_or_unknown_ids(self):
        m = self.mgr()
        r = m.propose(json.dumps(tip_pkg()))
        self.assertEqual(m.decline(r["proposal_id"])["status"], "declined")
        self.assertEqual(m.approve(r["proposal_id"])["status"], "not_pending")
        self.assertEqual(m.list_capabilities(), [])
        self.assertEqual(m.approve("pdoesnotexist")["code"], "E_EXT_NO_PROPOSAL")
        self.assertEqual(m.decline("pdoesnotexist")["code"], "E_EXT_NO_PROPOSAL")
        r2 = m.propose(json.dumps(tip_pkg()))
        self.assertEqual(m.approve(r2["proposal_id"])["status"], "applied")
        self.assertEqual(m.approve(r2["proposal_id"])["status"], "not_pending")
        self.assertEqual(len(m.versions("tip_calc")), 1)

    def test_proposals_expire(self):
        m = self.mgr()
        r = m.propose(json.dumps(tip_pkg()))
        self.now[0] += PROPOSAL_TTL_SECONDS + 5
        self.assertEqual(m.pending(), [])
        self.assertEqual(m.approve(r["proposal_id"])["status"], "not_pending")
        r = m.propose(json.dumps(tip_pkg()))
        self.now[0] += PROPOSAL_TTL_SECONDS + 5
        self.assertEqual(m.approve(r["proposal_id"])["status"], "expired")
        self.assertEqual(m.list_capabilities(), [])

    def test_identical_package_is_a_noop(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        r = m.propose(json.dumps(tip_pkg()))
        self.assertEqual((r["status"], r["version"]), ("noop_identical", 1))
        self.assertEqual(m.pending(), [])

    def test_a_newer_proposal_supersedes_an_older_pending_one(self):
        m = self.mgr()
        a = m.propose(json.dumps(tip_pkg()))
        b = m.propose(json.dumps(tip_pkg(factor=50)))
        self.assertEqual([p["proposal_id"] for p in m.pending()], [b["proposal_id"]])
        self.assertEqual(m.approve(a["proposal_id"])["status"], "not_pending")

    def test_id_collisions_with_other_registries_are_refused(self):
        m = self.mgr(id_exists=lambda cid: cid == "tip_calc")
        r = m.propose(json.dumps(tip_pkg()))
        self.assertEqual((r["status"], r["stage"], r["code"]), ("rejected", "id", "E_EXT_ID_TAKEN"))
        self.assertEqual(m.propose(json.dumps(words_pkg()))["status"], "pending_approval")

    def test_a_tampered_pending_proposal_is_not_installed(self):
        m = self.mgr()
        r = m.propose(json.dumps(tip_pkg()))
        db = sqlite3.connect(os.path.join(self.root, hubstore.HUB_DB))
        row = db.execute("SELECT manifest_json FROM ext_proposals").fetchone()[0]
        db.execute("UPDATE ext_proposals SET manifest_json = ?", (row.replace("/ 100", "/ 1"),))
        db.commit()
        db.close()
        a = m.approve(r["proposal_id"])
        self.assertEqual((a["status"], a["code"]), ("failed", "E_EXT_FINGERPRINT"))
        self.assertEqual(m.list_capabilities(), [])
        self.assertEqual(self.files("modules"), [])

    def test_usage_counters_and_history(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        m.invoke("tip_calc", {"bill": 10})
        m.invoke("tip_calc", {"bill": 10, "percent": 100})
        self.assertEqual(m.invoke("tip_calc", {"bill": 10})["ok"], True)
        self.assertEqual([(u["version"], u["calls"], u["failures"]) for u in m.usage("tip_calc")], [(1, 3, 0)])
        events = [h["event"] for h in m.history("tip_calc")]
        self.assertEqual(events[:2], ["ext.activated", "ext.approved"])
        self.assertIn("ext.proposed", [h["event"] for h in m.history()])


class TestRejection(Base):
    def test_malicious_failing_and_malformed_packages_are_rejected_and_never_active(self):
        m = self.mgr()
        for name, src in MALICIOUS.items():
            with self.subTest(name):
                pkg = tip_pkg(source=src)
                pkg["tests"] = [{"inputs": {"bill": 1, "percent": 1}, "expect": {"tip": 0.01}}]
                r = m.propose(json.dumps(pkg))
                self.assertEqual(r["status"], "rejected", r)
                self.assertIn(r["stage"], ("source", "tests"))
        bad = {
            "failing_test": tip_pkg(tests=[{"inputs": {"bill": 200, "percent": 15}, "expect": {"tip": 31}}]),
            "wrong_output_type": tip_pkg(source="def run(bill, percent):\n    return {'tip': 'x'}\n"),
            "undeclared_permission": tip_pkg(source="def run(bill, percent):\n    return {'tip': clock_now()}\n"),
            "unused_permission": tip_pkg(permissions=["network"]),
            "bad_dependency": tip_pkg(dependencies=["requests"]),
            "unknown_key": tip_pkg(permission=["network"]),
        }
        for name, pkg in bad.items():
            with self.subTest(name):
                self.assertEqual(m.propose(json.dumps(pkg))["status"], "rejected")
        for name, raw in {"not_json": "hello", "duplicate_keys": '{"a":1,"a":2}', "empty": "", "array": "[1]"}.items():
            with self.subTest(name):
                r = m.propose(raw)
                self.assertEqual((r["status"], r["stage"]), ("rejected", "package"))
        self.assertEqual(m.list_capabilities(), [])
        self.assertEqual(m.pending(), [])
        self.assertEqual(self.files("modules") + self.files("manifests"), [])
        rejected = [h for h in m.history(limit=100) if h["event"] == "ext.rejected"]
        self.assertGreaterEqual(len(rejected), 10)
        self.assertTrue(all("issues" in h["detail"] for h in rejected))

    def test_rejection_reports_exact_reasons(self):
        m = self.mgr()
        r = m.propose(json.dumps(tip_pkg(source=MALICIOUS["import"])))
        self.assertEqual(r["stage"], "source")
        self.assertIn("import", {i["code"] for i in r["issues"]})
        r = m.propose(json.dumps(tip_pkg(dependencies=["requests"])))
        self.assertEqual(r["stage"], "manifest")
        self.assertIn("requests", r["issues"][0]["message"])
        r = m.propose(json.dumps(tip_pkg(tests=[{"name": "t", "inputs": {"bill": 200, "percent": 15}, "expect": {"tip": 31}}])))
        self.assertEqual((r["stage"], r["code"]), ("tests", "E_EXT_TESTS"))
        self.assertEqual(r["issues"][0]["path"], "t")

    def test_an_expected_hash_mismatch_is_rejected_before_parsing(self):
        m = self.mgr()
        r = m.propose(json.dumps(tip_pkg()), expected_sha256="0" * 64)
        self.assertEqual((r["status"], r["code"]), ("rejected", "E_PACKAGE_HASH"))

    def test_a_rejected_update_leaves_the_active_version_untouched(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        r = m.propose(json.dumps(tip_pkg(source=MALICIOUS["open"])))
        self.assertEqual(r["status"], "rejected")
        self.assertEqual((m.get("tip_calc")["active_version"], len(m.versions("tip_calc"))), (1, 1))
        self.assertEqual(m.invoke("tip_calc", {"bill": 200, "percent": 15})["outputs"], {"tip": 30.0})

    def test_a_malicious_extension_that_slips_into_a_proposal_cannot_hurt_at_run_time(self):
        # defence in depth: even if a hostile source reached invoke(), the sandbox still contains it
        m = self.mgr()
        self.install(m, tip_pkg())
        m2 = self.mgr()
        self.assertTrue(m2.invoke("tip_calc", {"bill": 5})["ok"])


class TestUpdateAndRollback(Base):
    def test_update_creates_a_new_version_and_keeps_the_old_one(self):
        m = self.mgr()
        self.install(m, tip_pkg(factor=100))
        r = m.propose(json.dumps(tip_pkg(factor=50)))
        self.assertEqual((r["action"], r["planned_version"]), ("update", 2))
        a = m.approve(r["proposal_id"])
        self.assertEqual((a["version"], a["previous_version"]), (2, 1))
        self.assertEqual(m.invoke("tip_calc", {"bill": 200, "percent": 15})["outputs"], {"tip": 60.0})
        self.assertEqual([(v["version"], v["status"]) for v in m.versions("tip_calc")], [(1, "superseded"), (2, "active")])
        self.assertEqual(self.files("modules"), ["tip_calc_v1.py", "tip_calc_v2.py"])

    def test_rollback_restores_the_previous_behaviour_and_roll_forward_is_possible(self):
        m = self.mgr()
        self.install(m, tip_pkg(factor=100))
        self.install(m, tip_pkg(factor=50))
        rb = m.rollback("tip_calc", reason="the new rule was wrong")
        self.assertEqual((rb["status"], rb["from_version"], rb["to_version"]), ("rolled_back", 2, 1))
        self.assertEqual(m.invoke("tip_calc", {"bill": 200, "percent": 15})["outputs"], {"tip": 30.0})
        self.assertEqual([(v["version"], v["status"]) for v in m.versions("tip_calc")], [(1, "active"), (2, "rolled_back")])
        self.assertEqual(m.rollback("tip_calc")["status"], "nothing_to_roll_back")
        fwd = m.rollback("tip_calc", to_version=2)
        self.assertEqual((fwd["status"], fwd["to_version"]), ("rolled_back", 2))
        self.assertEqual(m.invoke("tip_calc", {"bill": 200, "percent": 15})["outputs"], {"tip": 60.0})
        ev = [h for h in m.history("tip_calc") if h["event"] == "ext.rolled_back"]
        self.assertEqual(ev[-1]["detail"]["reason"], "the new rule was wrong")

    def test_rollback_to_a_missing_or_failed_version_is_refused(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        self.assertEqual(m.rollback("nope")["status"], "failed")
        self.assertEqual(m.rollback("tip_calc", to_version=7)["code"], "E_EXT_BAD_TARGET")
        self.assertEqual(m.rollback("tip_calc", to_version=1)["code"], "E_EXT_BAD_TARGET")     # the active one is not a rollback target

    def test_a_version_that_fails_verification_after_install_is_never_left_active(self):
        m = self.mgr()
        self.install(m, tip_pkg(factor=100))
        r = m.propose(json.dumps(tip_pkg(factor=50)))
        real = m.verify_version

        def fail_new(cid, version, run_tests=True):
            return {"ok": False, "reason": "simulated load failure", "checks": {}} if version == 2 else real(cid, version, run_tests)
        with mock.patch.object(m, "verify_version", side_effect=fail_new):
            a = m.approve(r["proposal_id"])
        self.assertEqual((a["status"], a["code"], a["restored_version"]), ("failed", "E_EXT_VERIFY", 1))
        self.assertEqual(m.get("tip_calc")["active_version"], 1)
        self.assertEqual([(v["version"], v["status"]) for v in m.versions("tip_calc")], [(1, "active"), (2, "failed")])
        self.assertEqual(m.invoke("tip_calc", {"bill": 200, "percent": 15})["outputs"], {"tip": 30.0})

    def test_a_first_version_that_fails_verification_leaves_nothing_active(self):
        m = self.mgr()
        r = m.propose(json.dumps(tip_pkg()))
        with mock.patch.object(m, "verify_version", return_value={"ok": False, "reason": "simulated", "checks": {}}):
            a = m.approve(r["proposal_id"])
        self.assertEqual(a["status"], "failed")
        self.assertEqual(m.get("tip_calc")["state"], "disabled")
        self.assertEqual(m.invoke("tip_calc", {"bill": 1})["status"], "disabled")
        self.assertEqual(m.match("انعام 5")["status"], "none")

    def test_updates_that_ask_for_new_permissions_say_so(self):
        m = self.mgr()
        self.install(m, counter_pkg())
        pkg = counter_pkg()
        pkg["permissions"] = ["storage", "clock", "network"]
        pkg["source"] = pkg["source"].replace("return {", "page = web_fetch_text('https://a.test/')\n    return {")
        pkg["fixtures"]["web"] = {"https://a.test/": "x"}
        r = m.propose(json.dumps(pkg))
        self.assertEqual((r["status"], r["permissions"], r["new_permissions"]), ("pending_approval", ["clock", "network", "storage"], ["network"]))

    def test_disable_and_enable(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        self.assertEqual(m.disable("tip_calc")["status"], "disabled")
        self.assertEqual(m.invoke("tip_calc", {"bill": 1})["status"], "disabled")
        self.assertEqual(m.match("انعام 5")["status"], "none")
        self.assertEqual(m.match("انعام 5", include_disabled=True)["status"], "disabled")
        self.assertEqual(m.get("tip_calc")["state"], "disabled")
        self.assertEqual(m.enable("tip_calc")["status"], "enabled")
        self.assertTrue(m.invoke("tip_calc", {"bill": 1})["ok"])
        self.assertEqual(m.disable("nope")["status"], "failed")
        self.assertEqual(m.enable("nope")["status"], "failed")


class TestPersistenceAndRecovery(Base):
    def test_everything_survives_a_restart(self):
        m = self.mgr()
        self.install(m, tip_pkg(factor=100))
        self.install(m, tip_pkg(factor=50))
        self.install(m, counter_pkg())
        m.invoke("visit_counter", {"step": 3})
        m.close()
        m2 = self.mgr()
        report = m2.reconcile()
        self.assertEqual((report["failed_versions"], report["fell_back"], report["disabled"], report["quarantined"]), ([], [], [], []))
        self.assertTrue(report["audit"]["ok"])
        self.assertEqual(m2.invoke("tip_calc", {"bill": 200, "percent": 15})["outputs"], {"tip": 60.0})
        self.assertEqual(m2.match("انعام 200 با 15 درصد")["status"], "invoke")
        self.assertEqual(m2.invoke("visit_counter", {"step": 1})["outputs"]["count"], 4)
        self.assertEqual([(v["version"], v["status"]) for v in m2.versions("tip_calc")], [(1, "superseded"), (2, "active")])
        self.assertEqual(m2.rollback("tip_calc")["to_version"], 1)

    def test_a_tampered_active_source_is_detected_and_the_previous_version_takes_over(self):
        m = self.mgr()
        self.install(m, tip_pkg(factor=100))
        self.install(m, tip_pkg(factor=50))
        path = os.path.join(self.root, "modules", "tip_calc_v2.py")
        with open(path, "a") as f:
            f.write("# malicious edit\n")
        r = m.invoke("tip_calc", {"bill": 200, "percent": 15})
        self.assertTrue(r["ok"])
        self.assertEqual((r["version"], r["outputs"], r["fallback_from"]), (1, {"tip": 30.0}, 2))
        self.assertIn("SHA-256", r["fallback_reason"])
        self.assertEqual([(v["version"], v["status"]) for v in m.versions("tip_calc")], [(1, "active"), (2, "failed")])
        self.assertIn("ext.auto_rollback", [h["event"] for h in m.history("tip_calc")])

    def test_a_tampered_only_version_is_disabled_not_run(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        with open(os.path.join(self.root, "modules", "tip_calc_v1.py"), "w") as f:
            f.write("def run(bill, percent):\n    return {'tip': 999}\n")
        r = m.invoke("tip_calc", {"bill": 1})
        self.assertEqual((r["ok"], r["status"], r["repaired_to"]), (False, "integrity_failed", None))
        self.assertEqual(m.get("tip_calc")["state"], "disabled")
        self.assertEqual(m.invoke("tip_calc", {"bill": 1})["status"], "disabled")
        self.assertIn("ext.auto_disabled", [h["event"] for h in m.history("tip_calc")])

    def test_reconcile_repairs_corruption_found_at_startup(self):
        m = self.mgr()
        self.install(m, tip_pkg(factor=100))
        self.install(m, tip_pkg(factor=50))
        os.remove(os.path.join(self.root, "manifests", "tip_calc_v2.json"))
        m.close()
        m2 = self.mgr()
        rep = m2.reconcile()
        self.assertEqual([(f["version"]) for f in rep["failed_versions"]], [2])
        self.assertEqual(rep["fell_back"], [{"capability_id": "tip_calc", "from_version": 2, "to_version": 1}])
        self.assertEqual(m2.invoke("tip_calc", {"bill": 200, "percent": 15})["outputs"], {"tip": 30.0})
        self.assertEqual([(v["version"], v["status"]) for v in m2.versions("tip_calc")], [(1, "active"), (2, "failed")])

    def test_orphan_and_partial_files_are_quarantined_or_swept_never_executed(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        for sub, name, text in (("modules", "ghost_ext_v1.py", "import os\n"), ("manifests", "ghost_ext_v1.json", "{}"),
                                ("modules", "tip_calc_v9.py.part1234", "partial")):
            with open(os.path.join(self.root, sub, name), "w") as f:
                f.write(text)
        rep = m.reconcile()
        self.assertEqual(len(rep["quarantined"]), 2)
        self.assertEqual(len(rep["partials_removed"]), 1)
        self.assertEqual(self.files("modules"), ["tip_calc_v1.py"])
        self.assertEqual(len(self.files("quarantine")), 2)
        self.assertTrue(m.invoke("tip_calc", {"bill": 1})["ok"])

    def test_a_crash_in_the_middle_of_approval_leaves_a_recoverable_state(self):
        m = self.mgr()
        r = m.propose(json.dumps(tip_pkg()))
        real_audit = m._store.audit

        def crash(event, *a, **k):
            if event == "ext.approved":
                raise RuntimeError("power loss")
            return real_audit(event, *a, **k)
        with mock.patch.object(m._store, "audit", side_effect=crash):
            with self.assertRaises(RuntimeError):
                m.approve(r["proposal_id"])
        self.assertEqual(m.list_capabilities(), [])                       # the registry transaction rolled back
        self.assertEqual(self.files("modules"), ["tip_calc_v1.py"])       # but the files were written first
        m.close()
        m2 = self.mgr()
        rep = m2.reconcile()
        self.assertEqual(len(rep["quarantined"]), 2)                      # orphans are kept as evidence, not loaded
        self.assertEqual(self.files("modules"), [])
        self.assertEqual([p["capability_id"] for p in m2.pending()], ["tip_calc"])      # the proposal is still pending
        a = m2.approve(r["proposal_id"])
        self.assertEqual((a["status"], a["version"]), ("applied", 1))
        self.assertTrue(m2.invoke("tip_calc", {"bill": 10})["ok"])

    def test_the_audit_log_is_a_verifiable_hash_chain(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        self.assertTrue(m.status()["audit"]["ok"])
        db = sqlite3.connect(os.path.join(self.root, hubstore.HUB_DB))
        db.execute("UPDATE audit_log SET detail_json = '{}' WHERE seq = 1")
        db.commit()
        db.close()
        st = m.status()["audit"]
        self.assertFalse(st["ok"])
        self.assertEqual(st["first_bad_seq"], 1)
        self.assertFalse(m.reconcile()["audit"]["ok"])

    def test_status_summary(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        m.propose(json.dumps(words_pkg()))
        st = m.status()
        self.assertEqual((st["schema_version"], st["capabilities"], st["pending_proposals"]), (1, {"active": 1}, 1))


class TestPermissionsAndServices(Base):
    def test_storage_and_clock_helpers_persist_across_calls_and_restarts(self):
        m = self.mgr()
        a = self.install(m, counter_pkg())
        self.assertEqual(sorted(a["permissions_granted"]), ["clock", "storage"])
        self.assertEqual([m.invoke("visit_counter", {"step": 1})["outputs"]["count"] for _ in range(3)], [1, 2, 3])
        self.assertEqual(m.invoke("visit_counter", {})["outputs"], {"count": 4, "at": 1_700_000_000.0})
        m.close()
        m2 = self.mgr()
        self.assertEqual(m2.invoke("visit_counter", {"step": 10})["outputs"]["count"], 14)

    def test_storage_is_private_to_each_capability(self):
        m = self.mgr()
        self.install(m, counter_pkg())
        other = counter_pkg()
        other["id"] = "other_counter"
        other["triggers"] = ["نگه {step}"]
        self.install(m, other)
        m.invoke("visit_counter", {"step": 5})
        self.assertEqual(m.invoke("other_counter", {"step": 1})["outputs"]["count"], 1)

    def test_network_helper_uses_the_host_fetcher_and_reports_failures_honestly(self):
        pages = {"https://a.test/": "<title>Real</title>"}

        def fetch(url):
            if url in pages:
                return pages[url]
            raise OSError("offline: no network")
        m = self.mgr(web_fetch=fetch)
        a = self.install(m, web_pkg())
        self.assertEqual(a["permissions_granted"], ["network"])
        r = m.invoke("page_title", {"url": "https://a.test/"})
        self.assertEqual(r["outputs"], {"title": "Real"})
        r = m.invoke("page_title", {"url": "https://b.test/"})
        self.assertEqual((r["ok"], r["status"], r["error"]["kind"]), (False, "runtime_error", "RuntimeError"))
        self.assertIn("offline", r["error"]["detail"])
        no_network = self.mgr()
        r = no_network.invoke("page_title", {"url": "https://a.test/"})
        self.assertEqual(r["status"], "runtime_error")
        self.assertIn("not available", r["error"]["detail"])

    def test_revoking_a_permission_blocks_the_capability_until_it_is_granted_again(self):
        m = self.mgr(web_fetch=lambda url: "<title>T</title>")
        self.install(m, web_pkg())
        self.assertEqual(m.get("page_title")["state"], "active")
        self.assertEqual(m.revoke("page_title", "network")["status"], "revoked")
        info = m.get("page_title")
        self.assertEqual((info["state"], info["permissions"]["missing"]), ("permission_blocked", ["network"]))
        r = m.invoke("page_title", {"url": "https://a.test/"})
        self.assertEqual((r["ok"], r["status"], r["missing_permissions"]), (False, "blocked_permission", ["network"]))
        self.assertEqual(m.grant("page_title", "storage")["code"], "E_EXT_PERMISSION")       # not declared by the package
        self.assertEqual(m.grant("page_title", "network")["status"], "granted")
        self.assertTrue(m.invoke("page_title", {"url": "https://a.test/"})["ok"])
        self.assertEqual([h["event"] for h in m.history("page_title")][:2], ["ext.permission_granted", "ext.permission_revoked"])

    def test_a_blocked_extension_does_not_run_any_code(self):
        calls = []
        m = self.mgr(web_fetch=lambda url: calls.append(url) or "<title>T</title>")
        self.install(m, web_pkg())
        m.revoke("page_title", "network")
        m.invoke("page_title", {"url": "https://a.test/"})
        self.assertEqual(calls, [])


class TestMatchingFlows(Base):
    def test_missing_and_invalid_inputs_are_reported_precisely(self):
        pkg = tip_pkg(inputs=[{"name": "bill", "type": "number", "min": 0, "label": "مبلغ"}, {"name": "percent", "type": "number", "max": 100, "label": "درصد"}],
                      triggers=["انعام {bill}", "انعام {bill} با {percent} درصد"],
                      tests=[{"inputs": {"bill": 200, "percent": 15}, "expect": {"tip": 30}}])
        m = self.mgr()
        self.install(m, pkg)
        hit = m.match("انعام 200")
        self.assertEqual((hit["status"], [x["name"] for x in hit["missing"]], hit["missing"][0]["label"], hit["have"]), ("needs_inputs", ["percent"], "درصد", {"bill": 200}))
        hit = m.match("انعام 200 با 500 درصد")
        self.assertEqual((hit["status"], hit["problems"][0]["name"], hit["problems"][0]["code"]), ("invalid_inputs", "percent", "range"))
        r = m.invoke("tip_calc", {"bill": 200})
        self.assertEqual((r["ok"], r["status"], r["problems"][0]["code"]), (False, "invalid_inputs", "missing"))

    def test_the_best_matching_extension_wins_and_unrelated_text_matches_nothing(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        other = tip_pkg(id="tip_with_tax", title="انعام با مالیات", triggers=["انعام {bill} با مالیات"])
        other["tests"] = [{"inputs": {"bill": 100, "percent": 10}, "expect": {"tip": 10}}]
        self.install(m, other)
        self.assertEqual(m.match("انعام 100 با مالیات")["capability_id"], "tip_with_tax")
        self.assertEqual(m.match("انعام 100")["capability_id"], "tip_calc")
        for text in ("سلام چطوری", "انعام دادم به گارسون دیشب خیلی بیشتر از معمول", "", "   "):
            self.assertEqual(m.match(text)["status"], "none", text)

    def test_find_capability_by_id_or_title(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        self.install(m, words_pkg())
        self.assertEqual(m.find_capability("قابلیت tip_calc را برگردان"), "tip_calc")
        self.assertEqual(m.find_capability("محاسبهٔ انعام را غیرفعال کن"), "tip_calc")
        self.assertEqual(m.find_capability("شمارندهٔ کلمات"), "word_counter")
        self.assertIsNone(m.find_capability("یک چیز دیگر"))


class TestConcurrency(Base):
    def test_parallel_calls_are_consistent(self):
        m = self.mgr()
        self.install(m, tip_pkg())
        errors, results = [], []

        def worker(n):
            try:
                for i in range(15):
                    r = m.invoke("tip_calc", {"bill": 100 + n, "percent": 10})
                    results.append(r["outputs"]["tip"] == round((100 + n) * 10 / 100, 2))
            except Exception as e:          # pragma: no cover
                errors.append(e)
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(errors, [])
        self.assertEqual((len(results), all(results)), (90, True))
        self.assertEqual(m.usage("tip_calc")[0]["calls"], 90)

    def test_two_managers_on_one_root_serialize_their_changes(self):
        a, b = self.mgr(), self.mgr()
        ra = a.propose(json.dumps(tip_pkg()))
        rb = b.propose(json.dumps(words_pkg()))
        out = []
        ta = threading.Thread(target=lambda: out.append(a.approve(ra["proposal_id"])["status"]))
        tb = threading.Thread(target=lambda: out.append(b.approve(rb["proposal_id"])["status"]))
        ta.start(); tb.start(); ta.join(60); tb.join(60)
        self.assertEqual(sorted(out), ["applied", "applied"])
        self.assertEqual(sorted(c["capability_id"] for c in self.mgr().list_capabilities()), ["tip_calc", "word_counter"])


if __name__ == "__main__":
    unittest.main()
