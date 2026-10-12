"""
FINAL-EXIT-001 - the three older application files that were extended.

The Self-Builder reaches the existing application through exactly three small, defensive hooks:

  skills/skill_system.py          SkillSystem._dynamic_skill        (the Persian conversation seam)
  self_upgrade/upgrade_system.py  UpgradeSystem._propose_self_built (the AEL `UPGRADE` statement)
  self_upgrade/version_system.py  VersionSystem._restore_self_builder / rollback_to
                                                                     (the AEL `ROLLBACK <id>` statement)

These tests drive each hook IN-PROCESS through the real `Core` (so that the lines of the hooks are
really executed and measured), in every scope of the Persian brain, with injected failures:
a complete request is built for real and mirrored into the older tables, everything else keeps
going through the old placeholder lifecycle exactly as before, a failing Self-Builder never breaks
the old behaviour, and a rollback is only ever reported when the capability version was really
restored.

Every test works in its own temporary directory; nothing is ever written into the source tree.

Run directly:
    python -m unittest tests.test_self_builder_legacy_bridges_final_exit001 -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from persian_brain import activation
from self_builder import mirror, request_parser, templates
from self_builder import service as sb_service
from self_builder.service import SelfBuilderService
from self_upgrade.upgrade_system import UpgradeSystem
from self_upgrade.version_system import VersionSystem

WORDS = "ابزاری بساز که تعداد کلمات متن را بشمارد"
KM_MI = "یک مبدل کیلومتر به مایل بساز"
KM_MI_62137 = "مبدلی بساز که هر ۱ کیلومتر برابر ۰٫۶۲۱۳۷ مایل است"          # a tiny change: applied as version 2
KM_MI_06 = "مبدلی بساز که هر ۱ کیلومتر برابر ۰٫۶ مایل است"                    # a big change: needs a confirmation
PLAIN = "improve the matching speed"                                      # not a capability request


class CoreCase(unittest.TestCase):
    """A real Core in a temporary data directory, the plain desktop runtime (brain scope: capabilities)."""

    def setUp(self):
        import platform_layer
        self.tmp = tempfile.mkdtemp(prefix="sb_legacy_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        original = platform_layer.get_platform()
        self.addCleanup(platform_layer.set_platform, original)
        platform_layer.set_platform(platform_layer.DesktopPlatformAdapter(data_dir=self.tmp))
        silence = mock.patch.object(platform_layer.DesktopPlatformAdapter, "log")        # Core's start-up log line
        silence.start()
        self.addCleanup(silence.stop)
        env = dict(os.environ)
        env.pop(activation.ENV_VAR, None)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cores = []
        self.addCleanup(self.close_all)
        self.core = self.open_core()

    def open_core(self, sub="app"):
        base = os.path.join(self.tmp, sub)
        core = Core(memory_db_path=os.path.join(base, "data", "memory.db"),
                    skill_definitions_dir=os.path.join(base, "skills"))
        self.cores.append(core)
        return core

    def close_all(self):
        cores, self.cores = self.cores, []
        for core in cores:
            try:
                sb_service.get_service(core.memory).close()
            finally:
                core.memory._conn.close()

    # ------------------------------------------------------------------ helpers
    def say(self, text):
        return self.core.process_input(text)

    @property
    def memory(self):
        return self.core.memory

    @property
    def service(self):
        return sb_service.get_service(self.memory)

    @property
    def sb_root(self):
        return sb_service.default_root(self.memory)

    def rows(self, sql, *params):
        return [dict(r) for r in self.memory.query(sql, params)]

    def upgrade_rows(self):
        return self.rows("SELECT id, name, stage, status FROM upgrades ORDER BY id")

    def version_row(self, label):
        found = self.rows("SELECT * FROM versions WHERE version_label = ?", label)
        self.assertEqual(len(found), 1, label)
        return found[0]

    def active_labels(self):
        return [r["version_label"] for r in self.rows("SELECT version_label FROM versions WHERE is_active = 1")]

    def registry(self):
        return [(c["id"], c["status"], c["version"]) for c in self.service.capabilities()]

    def km_value(self):
        out = self.service.invoke("unit_km_to_mi", {"value": 10})
        self.assertTrue(out["ok"], out)
        return out["value"], out["version"]

    def assert_nothing_on_disk(self):
        self.assertFalse(os.path.exists(self.sb_root), "the Self-Builder must stay lazy: nothing may be created")


# ============================================================================ UPGRADE
class TestUpgradeStatementReachesTheSelfBuilder(CoreCase):
    def test_a_complete_request_is_built_for_real_and_mirrored_into_the_older_tables(self):
        self.assert_nothing_on_disk()
        self.assertEqual(self.say(f"UPGRADE word_counter IS {WORDS}"),
                         "[AEL OK] Upgrade 'word_counter' -> status: installed (stage: version).")
        self.assertEqual(self.registry(), [("text_count_words", "active", 1)])
        self.assertEqual(self.upgrade_rows(), [{"id": 1, "name": "word_counter", "stage": "version", "status": "installed"}])
        row = self.version_row("text_count_words@v1")
        self.assertEqual(self.active_labels(), ["text_count_words@v1"])
        snapshot = json.loads(row["snapshot"])
        self.assertEqual((snapshot["self_builder"]["capability_id"], snapshot["self_builder"]["version"]),
                         ("text_count_words", 1))
        self.assertEqual(self.rows("SELECT enabled, status FROM capabilities WHERE name = 'text_count_words'"),
                         [{"enabled": 1, "status": "active"}])
        out = self.service.invoke("text_count_words", {"text": "سلام دنیای زیبا"})
        self.assertEqual((out["ok"], out["value"], out["version"]), (True, 3.0, 1))

    def test_the_conversation_uses_what_the_upgrade_built(self):
        self.say(f"UPGRADE word_counter IS {WORDS}")
        self.assertEqual(self.say("تعداد کلمات را بشمار: سلام دنیای زیبا"), "شمارش کلمات: ۳")

    def test_the_returned_record_log_and_summary_are_those_of_the_real_pipeline(self):
        result = self.core.upgrades.propose_upgrade("km", KM_MI)
        self.assertEqual(result["self_builder"], {"status": "applied", "action": "create",
                                                  "capability_id": "unit_km_to_mi", "version": 1, "error": None})
        self.assertEqual((result["upgrade"]["name"], result["upgrade"]["stage"], result["upgrade"]["status"]),
                         ("km", "version", "installed"))
        stages = [entry["self_builder_stage"] for entry in result["log"]]
        self.assertEqual(stages, ["request", "analyze", "spec", "check_capabilities", "identify_gap", "plan",
                                  "generate", "validate", "test", "checkpoint", "apply", "persist", "register",
                                  "version", "audit"])
        self.assertTrue(all(entry["detail"]["ok"] for entry in result["log"]))
        self.assertEqual(self.km_value()[1], 1)

    def test_it_works_in_every_scope_except_off(self):
        for scope in ("capabilities", "full"):
            core = self.open_core(scope)
            activation.enable(core.memory, scope)
            result = core.upgrades.propose_upgrade("km", KM_MI)
            self.assertEqual(result["self_builder"]["status"], "applied", scope)
        off = self.open_core("off")
        activation.disable(off.memory)
        result = off.upgrades.propose_upgrade("km", KM_MI)
        self.assertNotIn("self_builder", result)                                          # the old lifecycle answered
        self.assertFalse(os.path.exists(sb_service.default_root(off.memory)))

    def test_with_the_brain_off_the_statement_keeps_its_old_meaning_and_creates_nothing(self):
        activation.disable(self.memory)
        self.assertEqual(self.say(f"UPGRADE word_counter IS {WORDS}"),
                         "[AEL OK] Upgrade 'word_counter' -> status: installed (stage: version).")
        self.assert_nothing_on_disk()
        self.assertEqual(self.rows("SELECT version_label FROM versions WHERE version_label LIKE '%@v%'"), [])
        self.assertEqual(self.rows("SELECT name FROM capabilities WHERE name = 'text_count_words'"), [])
        self.assertEqual([r["name"] for r in self.upgrade_rows()], ["word_counter"])

    def test_every_other_description_goes_through_the_old_placeholder_lifecycle(self):
        for description in (PLAIN, "make it faster", "یک نرم‌افزار حسابداری بساز", "یک مبدل بساز", ""):
            result = self.core.upgrades.propose_upgrade("legacy", description)
            self.assertNotIn("self_builder", result, description)
            self.assertEqual(result["log"][0], {"stage": "input", "detail": "Upgrade proposal received."})
            self.assertEqual(result["upgrade"]["status"], "installed", description)
        self.assert_nothing_on_disk()

    def test_a_payload_or_a_description_that_is_not_text_is_never_built(self):
        up = self.core.upgrades
        self.assertIsNone(up._propose_self_built("x", KM_MI, {"name": "x"}))
        for description in (None, 123, b"bytes", ["a"], {"a": 1}):
            self.assertIsNone(up._propose_self_built("x", description, None), repr(description))
        result = up.propose_upgrade("with_payload", KM_MI, payload={"name": "with_payload"})
        self.assertNotIn("self_builder", result)
        self.assert_nothing_on_disk()

    def test_a_memory_without_a_data_directory_never_builds(self):
        class Bare:
            db_path = None

            def _run(self, *a, **k):
                raise AssertionError("nothing may be written")

        self.assertIsNone(UpgradeSystem(Bare())._propose_self_built("x", KM_MI, None))

    def test_an_identical_request_is_a_no_op_but_is_still_recorded(self):
        self.say(f"UPGRADE a IS {KM_MI}")
        self.assertEqual(self.say(f"UPGRADE b IS {KM_MI}"), "[AEL OK] Upgrade 'b' -> status: installed (stage: understand).")
        self.assertEqual(self.registry(), [("unit_km_to_mi", "active", 1)])
        self.assertEqual(self.rows("SELECT version_label FROM versions WHERE version_label LIKE '%@v%'"),
                         [{"version_label": "unit_km_to_mi@v1"}])
        self.assertEqual([(r["name"], r["status"]) for r in self.upgrade_rows()], [("a", "installed"), ("b", "installed")])

    def test_a_second_version_supersedes_the_first_in_both_registries(self):
        self.say(f"UPGRADE a IS {KM_MI}")
        self.say(f"UPGRADE b IS {KM_MI_62137}")
        self.assertEqual(self.registry(), [("unit_km_to_mi", "active", 2)])
        self.assertEqual(self.active_labels(), ["unit_km_to_mi@v2"])
        self.assertEqual(self.km_value(), (6.213699999999999, 2))

    def test_a_big_change_waits_for_a_confirmation_and_installs_nothing(self):
        self.say(f"UPGRADE a IS {KM_MI}")
        before = (self.registry(), self.active_labels(), self.km_value())
        result = self.core.upgrades.propose_upgrade("big", KM_MI_06)
        self.assertEqual(result["self_builder"]["status"], "needs_confirmation")
        self.assertEqual((result["upgrade"]["stage"], result["upgrade"]["status"]), ("plan", "pending"))
        note = result["log"][-1]
        self.assertEqual(note["stage"], "plan")
        self.assertEqual(note["detail"]["needs_confirmation"]["reason"], "factor_deviation")
        self.assertEqual((self.registry(), self.active_labels(), self.km_value()), before)
        self.assertEqual(self.say(f"UPGRADE big2 IS {KM_MI_06}"), "[AEL OK] Upgrade 'big2' -> status: pending (stage: plan).")

    def test_a_failing_build_is_reported_as_failed_and_nothing_is_activated(self):
        self.say(f"UPGRADE a IS {KM_MI}")
        real = templates.generate_module
        with mock.patch.object(templates, "generate_module", lambda spec, version: "import os\n" + real(spec, version)):
            result = self.core.upgrades.propose_upgrade("bad", KM_MI_62137)
        self.assertEqual(result["self_builder"]["status"], "failed")
        self.assertEqual(result["self_builder"]["error"]["code"], "E_BUILD_VALIDATION")
        self.assertEqual(result["upgrade"]["status"], "failed")
        self.assertEqual(result["log"][-1], {"stage": "rollback", "detail": "Not installed - the Self-Builder's checks "
                                                                           "failed; nothing was activated."})
        self.assertEqual(self.registry(), [("unit_km_to_mi", "active", 1)])
        self.assertEqual(self.active_labels(), ["unit_km_to_mi@v1"])
        self.assertEqual(self.km_value()[1], 1)

    def test_a_failing_build_through_the_statement_reads_as_failed(self):
        real = templates.generate_module
        with mock.patch.object(templates, "generate_module", lambda spec, version: "import os\n" + real(spec, version)):
            reply = self.say(f"UPGRADE bad IS {KM_MI}")
        self.assertRegex(reply, r"^\[AEL OK\] Upgrade 'bad' -> status: failed \(stage: \w+\)\.$")
        self.assertEqual(self.rows("SELECT version_label FROM versions WHERE version_label LIKE '%@v%'"), [])

    def test_when_the_mirror_cannot_write_the_old_history_is_still_complete(self):
        with mock.patch.object(mirror, "mirror_upgrade", side_effect=RuntimeError("disk is full")):
            result = self.core.upgrades.propose_upgrade("km", KM_MI)
            real = templates.generate_module
            with mock.patch.object(templates, "generate_module", lambda spec, version: "import os\n" + real(spec, version)):
                failed = self.core.upgrades.propose_upgrade("bad", KM_MI_62137)
        self.assertEqual(result["self_builder"]["status"], "applied")
        self.assertEqual((result["upgrade"]["name"], result["upgrade"]["stage"], result["upgrade"]["status"]),
                         ("km", "version", "installed"))
        payload = json.loads(result["upgrade"]["payload"])
        self.assertEqual(payload["self_builder"], {"capability_id": "unit_km_to_mi", "status": "applied"})
        self.assertEqual(failed["self_builder"]["status"], "failed")
        self.assertEqual((failed["upgrade"]["stage"], failed["upgrade"]["status"]), ("sandbox_test", "failed"))
        self.assertEqual(self.registry(), [("unit_km_to_mi", "active", 1)])

    def test_any_failure_inside_the_self_builder_falls_back_to_the_old_lifecycle(self):
        up = self.core.upgrades
        for target in (mock.patch.object(SelfBuilderService, "build", side_effect=RuntimeError("boom")),
                       mock.patch.object(request_parser, "analyze_for_upgrade", side_effect=RuntimeError("boom")),
                       mock.patch.object(sb_service, "get_service", side_effect=RuntimeError("boom")),
                       mock.patch.object(activation, "scope_for", side_effect=RuntimeError("boom")),
                       mock.patch.object(mirror, "stage_log", side_effect=RuntimeError("boom"))):
            with target:
                result = up.propose_upgrade("km", KM_MI)
            self.assertNotIn("self_builder", result)
            self.assertEqual(result["log"][0], {"stage": "input", "detail": "Upgrade proposal received."})
            self.assertEqual(result["upgrade"]["status"], "installed")

    def test_the_built_capability_survives_a_restart_of_the_application(self):
        self.say(f"UPGRADE word_counter IS {WORDS}")
        self.say(f"UPGRADE km IS {KM_MI}")
        self.close_all()
        self.core = self.open_core()
        self.assertEqual(self.say("تعداد کلمات را بشمار: یک دو سه چهار"), "شمارش کلمات: ۴")
        self.assertEqual(sorted(self.registry()), [("text_count_words", "active", 1), ("unit_km_to_mi", "active", 1)])
        self.assertEqual(self.active_labels(), ["unit_km_to_mi@v1"])
        self.assertEqual([r["name"] for r in self.upgrade_rows()], ["word_counter", "km"])


# ============================================================================ ROLLBACK
class TestRollbackStatementRestoresForReal(CoreCase):
    def two_versions(self):
        self.say(f"UPGRADE a IS {KM_MI}")
        self.say(f"UPGRADE b IS {KM_MI_62137}")
        self.assertEqual(self.km_value(), (6.213699999999999, 2))
        return self.version_row("unit_km_to_mi@v1")["id"], self.version_row("unit_km_to_mi@v2")["id"]

    def test_rollback_to_an_older_version_restores_it_really_and_forward_again(self):
        v1, v2 = self.two_versions()
        self.assertEqual(self.say(f"ROLLBACK {v1}"), f"[AEL OK] Rolled back to version 'unit_km_to_mi@v1' (id {v1}).")
        self.assertEqual(self.km_value(), (6.2137119223733395, 1))
        self.assertEqual(self.registry(), [("unit_km_to_mi", "active", 1)])
        self.assertEqual(self.active_labels(), ["unit_km_to_mi@v1"])
        self.assertEqual(self.say(f"ROLLBACK {v2}"), f"[AEL OK] Rolled back to version 'unit_km_to_mi@v2' (id {v2}).")
        self.assertEqual(self.km_value(), (6.213699999999999, 2))
        self.assertEqual(self.active_labels(), ["unit_km_to_mi@v2"])
        reasons = [h["plan"].get("reason") for h in self.service.history() if h["kind"] == "rollback"]
        self.assertEqual(reasons, ["ael_rollback", "ael_rollback"])
        self.assertEqual(self.service.self_check()["ok"], True)

    def test_the_restored_version_is_verified_again_before_it_is_activated(self):
        v1, _ = self.two_versions()
        self.say(f"ROLLBACK {v1}")
        rollback = [h for h in self.service.history() if h["kind"] == "rollback"][0]
        self.assertEqual(rollback["rollback"]["to_version"], 1)
        self.assertEqual(rollback["rollback"]["verified"][0]["tests"]["ok"], True)

    def test_rolling_back_to_the_version_that_is_already_active_changes_nothing(self):
        _, v2 = self.two_versions()
        before = len(self.service.history(limit=50))
        self.assertEqual(self.say(f"ROLLBACK {v2}"), f"[AEL OK] Rolled back to version 'unit_km_to_mi@v2' (id {v2}).")
        self.assertEqual(len(self.service.history(limit=50)), before)
        self.assertEqual(self.km_value()[1], 2)

    def test_an_unknown_version_id_is_reported(self):
        self.two_versions()
        self.assertEqual(self.say("ROLLBACK 999"), "[AEL ERROR] No version found with id 999.")
        self.assertEqual(self.km_value()[1], 2)

    def test_a_marker_row_that_is_not_a_self_builder_version_keeps_the_old_meaning(self):
        v1, v2 = self.two_versions()
        base = self.version_row("0.1.0-foundation")["id"]
        self.assertEqual(self.say(f"ROLLBACK {base}"), f"[AEL OK] Rolled back to version '0.1.0-foundation' (id {base}).")
        self.assertEqual(self.active_labels(), ["0.1.0-foundation"])                       # only the marker moved ...
        self.assertEqual(self.km_value()[1], 2)                                            # ... the capability is untouched

    def test_a_rollback_the_self_builder_cannot_perform_is_never_reported(self):
        v1, v2 = self.two_versions()
        with mock.patch.object(SelfBuilderService, "rollback", return_value={"status": "failed"}):
            self.assertEqual(self.say(f"ROLLBACK {v1}"), f"[AEL ERROR] No version found with id {v1}.")
        self.assertEqual(self.active_labels(), ["unit_km_to_mi@v2"])                       # the markers did not move either
        self.assertEqual(self.km_value()[1], 2)

    def test_a_rollback_target_that_the_registry_does_not_know_is_never_reported(self):
        self.two_versions()
        orphan = self.core.upgrades.versions.create_version(None, "ghost@v7", snapshot={
            "self_builder": {"capability_id": "ghost", "version": 7}})
        self.core.upgrades.versions.create_version(None, "later", snapshot={})
        self.assertEqual(self.say(f"ROLLBACK {orphan['id']}"), f"[AEL ERROR] No version found with id {orphan['id']}.")
        self.assertEqual(self.active_labels(), ["later"])

    def test_with_no_registry_on_disk_a_self_builder_row_cannot_be_restored(self):
        versions = self.core.upgrades.versions
        row = versions.create_version(None, "unit_km_to_mi@v1", snapshot={
            "self_builder": {"capability_id": "unit_km_to_mi", "version": 1}})
        self.assertIsNone(versions.rollback_to(row["id"]))
        self.assert_nothing_on_disk()

    def test_an_error_while_restoring_is_logged_and_never_reported_as_a_rollback(self):
        v1, _ = self.two_versions()
        versions = self.core.upgrades.versions
        with mock.patch.object(sb_service, "get_service", side_effect=RuntimeError("no service")):
            self.assertIsNone(versions.rollback_to(v1))
        errors = self.rows("SELECT * FROM errors ORDER BY id DESC LIMIT 1") if self.has_errors_table() else []
        if errors:
            self.assertIn("RuntimeError", json.dumps(errors[0], ensure_ascii=False))
        with mock.patch.object(sb_service, "get_service", side_effect=RuntimeError("no service")), \
                mock.patch.object(self.memory, "log_error", side_effect=OSError("cannot log")):
            self.assertFalse(versions._restore_self_builder("unit_km_to_mi", 1))           # even a failing log never raises
        self.assertEqual(self.km_value()[1], 2)

    def has_errors_table(self):
        return bool(self.rows("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'errors'"))

    def test_the_old_rollback_is_unchanged_for_versions_that_carry_no_self_builder_data(self):
        versions = self.core.upgrades.versions
        first = versions.create_version(None, "1.0", snapshot={"note": "first"})
        second = versions.create_version(None, "2.0")
        self.assertEqual(versions.current_version()["id"], second["id"])
        self.assertEqual(self.say(f"ROLLBACK {first['id']}"), f"[AEL OK] Rolled back to version '1.0' (id {first['id']}).")
        self.assertEqual(versions.current_version()["version_label"], "1.0")
        self.assertIsNone(versions.rollback_to(424242))
        self.assert_nothing_on_disk()

    def test_the_coordinates_of_a_snapshot_are_read_defensively(self):
        coords = VersionSystem._self_builder_coordinates
        good = json.dumps({"self_builder": {"capability_id": "a", "version": 3}})
        self.assertEqual(coords({"snapshot": good}), ("a", 3))
        for snapshot in (None, "", "{}", "not json", "[]", "[1]", "null", "123", '"text"',
                         json.dumps({"self_builder": "x"}), json.dumps({"self_builder": None}),
                         json.dumps({"self_builder": {}}),
                         json.dumps({"self_builder": {"capability_id": "", "version": 1}}),
                         json.dumps({"self_builder": {"capability_id": "a", "version": "1"}}),
                         json.dumps({"self_builder": {"capability_id": "a"}}),
                         json.dumps({"self_builder": {"capability_id": "a", "version": None}})):
            self.assertIsNone(coords({"snapshot": snapshot}), repr(snapshot))
        self.assertIsNone(coords({}))                                                      # no snapshot key at all
        self.assertIsNone(coords(None))


# ============================================================================ the skill seam
class TestSkillSeamIsDefensive(CoreCase):
    def test_a_failing_brain_never_breaks_the_old_skill_matching(self):
        skills = self.core.skills
        expected = skills.find_matching_skill("hello")
        self.assertIsNotNone(expected)
        import persian_brain
        with mock.patch.object(persian_brain, "dynamic_skill", side_effect=RuntimeError("brain is broken")):
            self.assertEqual(skills.find_matching_skill("hello"), expected)
            self.assertIsNone(skills._dynamic_skill("hello"))
            self.assertTrue(self.say("hello").startswith("Hello!"))

    def test_a_missing_brain_module_never_breaks_the_old_skill_matching(self):
        skills = self.core.skills
        with mock.patch.dict(sys.modules, {"persian_brain": None}):                       # `import` raises ImportError
            self.assertIsNone(skills._dynamic_skill("یک مبدل کیلومتر به مایل بساز"))
            self.assertIsNotNone(skills.find_matching_skill("hello"))

    def test_the_dynamic_skill_is_asked_first_and_wins_when_it_answers(self):
        skills = self.core.skills
        sentinel = {"name": "sentinel", "response": "x", "trigger": {"type": "dynamic"}, "dynamic": True}
        import persian_brain
        with mock.patch.object(persian_brain, "dynamic_skill", return_value=sentinel) as asked:
            self.assertIs(skills.find_matching_skill("hello"), sentinel)
        asked.assert_called_once_with(self.memory, "hello")

    def test_the_brain_answers_a_capability_request_only_once_the_text_is_one(self):
        skills = self.core.skills
        skill = skills.find_matching_skill("یک مبدل کیلومتر به مایل بساز")
        self.assertEqual((skill["name"], skill["dynamic"]), ("persian_conversation", True))
        self.assertIsNone(skills.find_matching_skill("pure english sentence nobody handles"))
        activation.disable(self.memory)
        self.assertIsNone(skills._dynamic_skill("یک مبدل کیلومتر به مایل بساز"))
        self.assertEqual(skills.find_matching_skill("hello")["name"], "greet")      # the stored keyword skills remain


if __name__ == "__main__":
    unittest.main()
