"""
Prompt 958 - the pack manager: propose -> approve -> activate -> roll back, boot, safe mode, failure handling.

Real manager, real files in a temp folder, real import hook; a "restart" is a new manager on the same files with the
hook, the registry and the imported pack modules reset (and, for module replacement, a real child process).
"""

import json
import os
import stat
import subprocess
import sys
import textwrap
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pack_system import boot, limits, overlay
from pack_system.api import PackAPI, PackPermissionError
from pack_system.errors import PackError
from pack_system.manager import PackManager
from pack_system.registry import REGISTRY
from tests import pack_support_prompt958 as S
from tests.test_pack_system_prompt958 import PackCase


def greeter(version, extra=""):
    return S.text_pack(version=version, source=S.GREETER_SOURCE % {"version": version, "extra": extra})


class LifecycleTests(PackCase):
    def test_proposal_changes_nothing(self):
        out = self.propose(greeter(1))
        self.assertEqual(out["status"], "pending_approval")
        self.assertEqual(out["pack_id"], "demo_greeter")
        self.assertEqual(out["action"], "create")
        self.assertEqual(self.mgr.list(), [])
        self.assertFalse(os.path.isdir(os.path.join(self.root, "store")))
        self.assertIsNone(self.chat("سلام دمو"))
        self.assertEqual(len(self.mgr.pending()), 1)

    def test_approval_must_be_exactly_true(self):
        qid = self.propose(greeter(1))["proposal_id"]
        for value in (False, None, 1, "true", "yes", "بله"):
            self.assertEqual(self.mgr.approve(qid, user_approved=value)["status"], "approval_required")
        self.assertEqual(self.mgr.list(), [])
        self.assertIsNone(self.chat("سلام دمو"))

    def test_approve_installs_loads_and_answers(self):
        out = self.install(greeter(1))
        self.assertEqual(out["status"], "applied")
        self.assertTrue(out["hot"])
        self.assertFalse(out["restart_needed"])
        self.assertEqual(self.chat("سلام دمو"), "سلام از بستهٔ دمو، نسخهٔ 1")
        row = self.mgr.get("demo_greeter")
        self.assertEqual((row["state"], row["active_version"], row["versions"]), ("active", 1, [1]))
        self.assertEqual(self.mgr.pending(), [])

    def test_installed_files_are_read_only_and_hash_verified(self):
        self.install(greeter(1))
        path = os.path.join(self.root, "store", "demo_greeter", "1", "files", "demo_greeter", "main.py")
        self.assertTrue(os.path.isfile(path))
        self.assertFalse(os.stat(path).st_mode & stat.S_IWUSR)
        self.assertEqual(self.mgr.store.verify("demo_greeter", 1), (True, ""))

    def test_update_then_rollback_then_forward_again(self):
        self.install(greeter(1))
        out = self.install(greeter(2))
        self.assertEqual((out["status"], out["previous_version"], out["version"]), ("applied", 1, 2))
        self.assertEqual(self.chat("سلام دمو"), "سلام از بستهٔ دمو، نسخهٔ 2")
        back = self.mgr.rollback("demo_greeter")
        self.assertEqual((back["status"], back["from_version"], back["to_version"]), ("rolled_back", 2, 1))
        self.assertEqual(self.chat("سلام دمو"), "سلام از بستهٔ دمو، نسخهٔ 1")
        again = self.mgr.rollback("demo_greeter", 2)
        self.assertEqual(again["to_version"], 2)
        self.assertEqual(self.chat("سلام دمو"), "سلام از بستهٔ دمو، نسخهٔ 2")
        self.assertEqual(self.mgr.get("demo_greeter")["versions"], [1, 2])

    def test_rollback_without_older_version_or_with_unknown_version(self):
        self.install(greeter(1))
        self.assertEqual(self.mgr.rollback("demo_greeter")["code"], "E_PACK_NO_PREVIOUS")
        self.assertEqual(self.mgr.rollback("demo_greeter", 9)["code"], "E_PACK_NO_VERSION")
        self.assertEqual(self.mgr.rollback("nothing_here")["code"], "E_PACK_NOT_FOUND")

    def test_identical_package_is_a_noop_and_old_version_is_refused(self):
        self.install(greeter(2))
        self.assertEqual(self.propose(greeter(2))["status"], "noop_identical")
        old = self.propose(greeter(1))
        self.assertEqual(old["code"], "E_PACK_VERSION_OLD")
        same_number_other_content = self.propose(S.text_pack(version=2, source=S.GREETER_SOURCE % {"version": 2, "extra": "\nX = 1"}))
        self.assertEqual(same_number_other_content["code"], "E_PACK_VERSION_OLD")

    def test_declined_proposal_is_gone(self):
        qid = self.propose(greeter(1))["proposal_id"]
        self.assertEqual(self.mgr.decline(qid)["status"], "declined")
        self.assertEqual(self.mgr.approve(qid, user_approved=True)["code"], "E_PACK_NO_PROPOSAL")

    def test_proposals_expire_after_a_day(self):
        qid = self.propose(greeter(1))["proposal_id"]
        self.clock.advance(limits.PROPOSAL_TTL_SECONDS + 5)
        self.assertEqual(self.mgr.approve(qid, user_approved=True)["code"], "E_PACK_NO_PROPOSAL")
        self.assertEqual(self.mgr.pending(), [])

    def test_a_proposal_is_rescanned_when_approved(self):
        qid = self.propose(greeter(1))["proposal_id"]
        path = os.path.join(self.root, "proposals", qid + ".json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data["manifest"]["files"]["demo_greeter/main.py"] += "\nimport subprocess\n"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        out = self.mgr.approve(qid, user_approved=True)
        self.assertEqual(out["status"], "rejected")
        self.assertEqual(out["code"], "E_PACK_SCAN")
        self.assertEqual(self.mgr.list(), [])
        self.assertEqual(self.mgr.pending(), [])

    def test_scan_rejection_is_reported_with_the_reason_and_installs_nothing(self):
        out = self.propose(S.text_pack(source="import subprocess\n\ndef register(api):\n    pass\n"))
        self.assertEqual(out["status"], "rejected")
        self.assertEqual(out["code"], "E_SCAN_IMPORT")
        self.assertEqual(self.mgr.list(), [])
        self.assertEqual(self.mgr.pending(), [])

    def test_invalid_text_is_a_plain_error(self):
        out = self.propose("سلام این یک بسته نیست")
        self.assertEqual(out["status"], "rejected")
        self.assertEqual(out["code"], "E_PACK_NONE")

    def test_disable_enable_remove(self):
        self.install(greeter(1))
        out = self.mgr.disable("demo_greeter")
        self.assertEqual(out["status"], "disabled")
        self.assertIsNone(self.chat("سلام دمو"))
        self.assertEqual(self.mgr.get("demo_greeter")["state"], "disabled")
        self.assertEqual(self.mgr.enable("demo_greeter")["status"], "approval_required")
        out = self.mgr.enable("demo_greeter", user_approved=True)
        self.assertEqual(out["status"], "enabled")
        self.assertEqual(self.chat("سلام دمو"), "سلام از بستهٔ دمو، نسخهٔ 1")
        self.assertEqual(self.mgr.remove("demo_greeter")["status"], "approval_required")
        self.assertEqual(self.mgr.remove("demo_greeter", user_approved=True)["status"], "removed")
        self.assertIsNone(self.mgr.get("demo_greeter"))
        self.assertIsNone(self.chat("سلام دمو"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "store", "demo_greeter")))

    def test_old_versions_are_pruned_but_the_active_one_stays(self):
        for v in range(1, limits.KEEP_VERSIONS + 4):
            self.install(greeter(v))
        row = self.mgr.get("demo_greeter")
        self.assertEqual(row["active_version"], limits.KEEP_VERSIONS + 3)
        self.assertEqual(len(row["versions"]), limits.KEEP_VERSIONS)
        self.assertEqual(self.chat("سلام دمو"), "سلام از بستهٔ دمو، نسخهٔ %d" % (limits.KEEP_VERSIONS + 3))

    def test_find_by_id_or_title(self):
        self.install(greeter(1))
        self.assertEqual(self.mgr.find("بستهٔ demo_greeter را خاموش کن")["pack_id"], "demo_greeter")
        self.assertEqual(self.mgr.find("سلام‌کنندهٔ آزمایشی")["pack_id"], "demo_greeter")
        self.assertIsNone(self.mgr.find("چیز دیگری"))

    def test_audit_chain_is_valid_and_has_the_story(self):
        self.install(greeter(1))
        self.install(greeter(2))
        self.mgr.rollback("demo_greeter")
        self.mgr.disable("demo_greeter")
        kinds = [e["kind"] for e in self.mgr.history()]
        for wanted in ("pack.proposed", "pack.installed", "pack.activated", "pack.rolled_back", "pack.disabled"):
            self.assertIn(wanted, kinds)
        self.assertTrue(self.mgr.audit.verify()["ok"])
        self.assertEqual([e["subject"] for e in self.mgr.history("demo_greeter")][0], "demo_greeter")


class ActivationFailureTests(PackCase):
    def test_failing_selftest_goes_back_to_the_previous_version(self):
        self.install(greeter(1))
        bad = greeter(2, "\n\ndef selftest(api):\n    return False\n")
        out = self.install(bad)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["code"], "E_PACK_ACTIVATION")
        self.assertEqual(out["rolled_back_to"], 1)
        row = self.mgr.get("demo_greeter")
        self.assertEqual((row["state"], row["active_version"]), ("active", 1))
        self.assertEqual(self.chat("سلام دمو"), "سلام از بستهٔ دمو، نسخهٔ 1")

    def test_selftest_exception_and_timeout_are_failures(self):
        self.install(greeter(1))
        out = self.install(greeter(2, "\n\ndef selftest(api):\n    raise ValueError('boom')\n"))
        self.assertEqual(out["code"], "E_PACK_ACTIVATION")
        old = limits.SELFTEST_SECONDS
        limits.SELFTEST_SECONDS = 0.2
        self.addCleanup(setattr, limits, "SELFTEST_SECONDS", old)
        out = self.install(greeter(3, "\n\ndef selftest(api):\n    while True:\n        pass\n"))
        self.assertEqual(out["code"], "E_PACK_ACTIVATION")
        self.assertEqual(self.mgr.get("demo_greeter")["active_version"], 1)

    def test_first_install_that_cannot_register_leaves_nothing_active(self):
        out = self.install(S.text_pack(source="def register(api):\n    raise RuntimeError('no')\n"))
        self.assertEqual(out["status"], "failed")
        row = self.mgr.get("demo_greeter")
        self.assertIn(row["state"], ("disabled", "inactive"))
        self.assertIsNone(row["active_version"])
        self.assertEqual(REGISTRY.pack_ids(), [])

    def test_import_error_in_the_pack_is_contained(self):
        out = self.install(S.text_pack(source="import demo_missing_dependency\n\ndef register(api):\n    pass\n"))
        self.assertEqual(out["status"], "failed")

    def test_undeclared_permission_is_refused_at_runtime(self):
        source = "def register(api):\n    api.register_android_action('network_state', 'read', lambda **k: {})\n"
        out = self.install(S.text_pack(source=source))
        self.assertEqual(out["status"], "failed")
        out = self.install(S.text_pack(pid="demo_other", source=source, permissions="android"))
        self.assertEqual(out["status"], "applied")
        self.assertIn("demo_other", REGISTRY.pack_ids())

    def test_permission_error_class(self):
        api = PackAPI("demo_other", 1, (), self.mgr.store, REGISTRY, self.clock)
        for call in (lambda: api.register_runtime(object()), lambda: api.register_recipe("r", {}),
                     lambda: api.net_fetch("https://example.com"), lambda: api.ask_model("x"),
                     lambda: api.android, lambda: api.teacher):
            with self.assertRaises(PackPermissionError):
                call()

    def test_failing_handlers_switch_the_pack_off_after_three_errors(self):
        source = ("def register(api):\n    def match(ctx):\n        return True\n    def handle(ctx):\n        raise RuntimeError('x')\n"
                  "    api.register_chat('bad', match, handle, stage='fallback')\n")
        self.install(S.text_pack(pid="demo_bad", source=source))
        for _ in range(limits.MAX_PACK_FAILURES):
            self.assertIsNone(self.chat("هر چیزی"))
        row = self.mgr.get("demo_bad")
        self.assertEqual(row["state"], "disabled")
        self.assertEqual(REGISTRY.pack_ids(), [])
        self.assertIn("pack.auto_disabled", [e["kind"] for e in self.mgr.history("demo_bad")])


class BootTests(PackCase):
    def test_active_packs_load_again_after_a_restart(self):
        self.install(greeter(1))
        self.install(S.text_pack(pid="demo_other", source="def register(api):\n    api.register_chat('o', lambda c: 'دیگر' in c.text, lambda c: 'پاسخ دیگر')\n"))
        mgr = self.restart()
        self.assertIsNone(self.chat("سلام دمو"))
        report = mgr.activate_all()
        self.assertEqual(sorted(x["pack_id"] for x in report["loaded"]), ["demo_greeter", "demo_other"])
        self.assertEqual(self.chat("سلام دمو"), "سلام از بستهٔ دمو، نسخهٔ 1")
        self.assertEqual(self.chat("چیز دیگر"), "پاسخ دیگر")

    def test_a_changed_file_is_quarantined_and_the_app_still_starts(self):
        self.install(greeter(1))
        self.install(S.text_pack(pid="demo_other", source="def register(api):\n    api.register_chat('o', lambda c: 'دیگر' in c.text, lambda c: 'پاسخ دیگر')\n"))
        path = os.path.join(self.root, "store", "demo_greeter", "1", "files", "demo_greeter", "main.py")
        os.chmod(path, 0o644)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n# tampered\n")
        mgr = self.restart()
        report = mgr.activate_all()
        self.assertEqual([f["pack_id"] for f in report["failed"]], ["demo_greeter"])
        self.assertTrue(report["failed"][0]["why"].startswith("verify:file_changed"))
        self.assertEqual(mgr.get("demo_greeter")["state"], "quarantined")
        self.assertIsNone(self.chat("سلام دمو"))
        self.assertEqual(self.chat("چیز دیگر"), "پاسخ دیگر")
        self.assertEqual(mgr.enable("demo_greeter", user_approved=True)["code"], "E_PACK_VERIFY")

    def test_a_pack_that_breaks_on_import_is_quarantined_not_fatal(self):
        self.install(greeter(1))
        path = os.path.join(self.root, "store", "demo_greeter", "1", "files", "demo_greeter", "main.py")
        # a pack whose code was fine at install but cannot import now (a dependency vanished): simulate by corrupting + fixing the hash
        os.chmod(path, 0o644)
        broken = "raise RuntimeError('cannot start')\n"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(broken)
        manifest_path = os.path.join(self.root, "store", "demo_greeter", "1", "manifest.json")
        os.chmod(manifest_path, 0o644)
        with open(manifest_path, encoding="utf-8") as handle:
            m = json.load(handle)
        from pack_system.fsutil import sha256_text
        m["file_hashes"]["demo_greeter/main.py"] = sha256_text(broken)
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(m, handle)
        mgr = self.restart()
        report = mgr.activate_all()
        self.assertEqual([f["pack_id"] for f in report["failed"]], ["demo_greeter"])
        self.assertEqual(mgr.get("demo_greeter")["state"], "quarantined")

    def test_prepare_marks_pending_until_the_start_is_good(self):
        report = boot.prepare(self.tmp, self.clock, start_timer=False)
        self.assertTrue(report["ok"])
        mgr = boot.manager()
        self.assertIsNotNone(mgr.state["boot"]["pending"])
        mgr.mark_good()
        self.assertIsNone(mgr.state["boot"]["pending"])
        self.assertEqual(mgr.state["boot"]["crashes"], 0)

    def restart_process(self):
        boot.reset_for_tests()
        S.reset_process_state(*("demo_greeter", "demo_other"))

    def test_first_failed_start_reverts_to_the_last_good_version(self):
        boot.prepare(self.tmp, self.clock, start_timer=False)
        self.mgr = boot.manager()
        self.install(greeter(1))
        self.install(greeter(2))
        # version 2 loaded fine in this process, but the user wants to know it also survives a real start:
        self.mgr.state["last_good"]["demo_greeter"] = 1
        self.mgr.state["boot"]["pending"] = None
        self.mgr.store.save()
        self.restart_process()
        boot.prepare(self.tmp, self.clock, start_timer=False)                 # loads version 2 ... and never becomes good
        self.assertEqual(boot.manager().get("demo_greeter")["active_version"], 2)
        self.restart_process()
        report = boot.prepare(self.tmp, self.clock, start_timer=False)        # the previous start did not finish
        self.assertEqual(report["rolled_back"], 1)
        self.assertEqual(report["safe_level"], 0)
        self.assertEqual(boot.manager().get("demo_greeter")["active_version"], 1)
        self.assertEqual(self.chat("سلام دمو"), "سلام از بستهٔ دمو، نسخهٔ 1")
        self.assertIn("pack.boot_rollback", [e["kind"] for e in boot.manager().history()])

    def test_a_pack_that_never_had_a_good_start_is_switched_off_after_one_failed_start(self):
        boot.prepare(self.tmp, self.clock, start_timer=False)
        self.mgr = boot.manager()
        self.install(greeter(1))
        self.mgr.state["last_good"].pop("demo_greeter", None)               # as if it came in with a replacing update
        self.mgr.state["boot"]["pending"] = None
        self.mgr.store.save()
        self.restart_process()
        boot.prepare(self.tmp, self.clock, start_timer=False)
        self.restart_process()
        report = boot.prepare(self.tmp, self.clock, start_timer=False)
        self.assertEqual(report["rolled_back"], 1)
        self.assertEqual(boot.manager().get("demo_greeter")["state"], "disabled")
        self.assertIsNone(self.chat("سلام دمو"))

    def test_second_failed_start_is_safe_mode_and_leaving_it_loads_the_packs(self):
        boot.prepare(self.tmp, self.clock, start_timer=False)
        self.mgr = boot.manager()
        self.install(greeter(1))
        self.mgr.mark_good()
        for _ in range(limits.SAFE_MODE_AFTER_FAILED_STARTS + 1):               # start, then two that never become good
            self.restart_process()
            report = boot.prepare(self.tmp, self.clock, start_timer=False)
        self.assertEqual(report["safe_level"], 1)
        mgr = boot.manager()
        self.assertEqual(mgr.safe_mode()["level"], 1)
        self.assertEqual(mgr.get("demo_greeter")["state"], "active")           # nothing was deleted or disabled
        self.assertIsNone(self.chat("سلام دمو"))                               # but no code pack is loaded in safe mode
        self.assertEqual(mgr.leave_safe_mode()["status"], "left")
        self.assertEqual(mgr.safe_mode()["level"], 0)
        mgr.activate_all(at_boot=False)
        self.assertEqual(self.chat("سلام دمو"), "سلام از بستهٔ دمو، نسخهٔ 1")

    def test_a_good_start_resets_the_counter(self):
        boot.prepare(self.tmp, self.clock, start_timer=False)
        boot.manager().mark_good()
        boot.reset_for_tests()
        boot.prepare(self.tmp, self.clock, start_timer=False)
        self.assertEqual(boot.manager().state["boot"]["crashes"], 0)
        self.assertEqual(boot.manager().safe_mode()["level"], 0)

    def test_prepare_never_raises(self):
        blocker = os.path.join(self.tmp, "blocked")
        with open(blocker, "w") as handle:
            handle.write("a file where a folder is needed")
        report = boot.prepare(blocker, self.clock, start_timer=False)
        self.assertFalse(report["ok"])
        self.assertTrue(report["error"])

    def test_platform_boot_entry_point(self):
        import platform_boot
        out = platform_boot.prepare(self.tmp)
        self.assertTrue(out["ok"])
        boot.manager().mark_good()

    def test_damaged_state_file_is_set_aside(self):
        self.install(greeter(1))
        with open(os.path.join(self.root, "state.json"), "w") as handle:
            handle.write("{not json")
        mgr = self.restart()
        self.assertEqual(mgr.list(), [])
        self.assertTrue(mgr.store.recovery)
        self.assertTrue([n for n in os.listdir(self.root) if n.startswith("state.json.corrupt")])

    def test_half_written_staging_folders_are_swept(self):
        os.makedirs(os.path.join(self.root, "staging", "demo_greeter-1-aaaa", "files"))
        self.mgr.activate_all()
        self.assertEqual(os.listdir(os.path.join(self.root, "staging")), [])


class ReplacementTests(PackCase):
    REPLACE = "# replaced module\nMARK = 'from-pack'\n"

    def replace_pack(self):
        return S.text_pack(replaces="persian_brain.messages", extra_files={"persian_brain/messages.py": self.REPLACE})

    def test_replacing_needs_the_second_confirmation_and_a_restart(self):
        proposal = self.propose(self.replace_pack())
        self.assertEqual(proposal["status"], "pending_approval")
        self.assertTrue(proposal["risky"])
        self.assertTrue(proposal["restart_needed"])
        self.assertEqual(self.mgr.approve(proposal["proposal_id"], user_approved=True)["status"], "confirm_required")
        self.assertEqual(self.mgr.list(), [])
        out = self.mgr.approve(proposal["proposal_id"], user_approved=True, confirm_risky=True)
        self.assertEqual((out["status"], out["hot"], out["restart_needed"]), ("applied", False, True))
        self.assertEqual(self.mgr.get("demo_greeter")["state"], "pending_restart")
        self.assertEqual(self.mgr.restart_needed(), ["demo_greeter"])
        self.assertIsNone(self.chat("سلام دمو"))

    def test_replacement_really_takes_effect_in_the_next_process(self):
        self.install_replacement()
        code = textwrap.dedent('''
            import sys
            sys.path.insert(0, %r)
            import platform_boot
            report = platform_boot.prepare(%r)
            from persian_brain import messages
            print("REPORT", report["ok"], report["loaded"], report["failed"])
            print("MARK", getattr(messages, "MARK", None))
        ''' % (S.PY_ROOT, self.tmp))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=self.tmp)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        self.assertIn("REPORT True 1 0", out.stdout)
        self.assertIn("MARK from-pack", out.stdout)

    def install_replacement(self):
        proposal = self.propose(self.replace_pack())
        out = self.mgr.approve(proposal["proposal_id"], user_approved=True, confirm_risky=True)
        self.assertEqual(out["status"], "applied", out)

    def test_safe_mode_runs_the_app_as_shipped(self):
        self.install_replacement()
        code = textwrap.dedent('''
            import sys
            sys.path.insert(0, %r)
            import platform_boot
            from pack_system import boot
            for _ in range(3):                       # a start, then two that never became good
                boot.reset_for_tests()
                report = platform_boot.prepare(%r)
            print("SAFE", report["safe_level"])
            from persian_brain import messages
            print("MARK", getattr(messages, "MARK", None))
        ''' % (S.PY_ROOT, self.tmp))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=self.tmp)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        self.assertIn("SAFE 1", out.stdout)
        self.assertIn("MARK None", out.stdout)

    def test_disabling_a_replacing_pack_asks_for_a_restart(self):
        self.install_replacement()
        out = self.mgr.disable("demo_greeter")
        self.assertTrue(out["restart_needed"])


class PackDataTests(PackCase):
    def api(self, pid="demo_data", perms=()):
        self.install(S.text_pack(pid=pid, source="def register(api):\n    pass\n"))
        return PackAPI(pid, 1, perms, self.mgr.store, REGISTRY, self.clock)

    def test_own_data_folder_roundtrip(self):
        api = self.api()
        api.write_json("settings.json", {"a": 1, "نام": "ب"})
        self.assertEqual(api.read_json("settings.json"), {"a": 1, "نام": "ب"})
        api.write_text("sub/notes.txt", "یادداشت")
        self.assertEqual(api.read_text("sub/notes.txt"), "یادداشت")
        self.assertEqual(api.list_data(), ["settings.json", "sub/notes.txt"])
        self.assertTrue(api.delete_data("sub/notes.txt"))
        self.assertIsNone(api.read_text("sub/notes.txt"))
        self.assertEqual(api.read_json("missing.json", {"d": 1}), {"d": 1})

    def test_paths_cannot_escape_the_data_folder(self):
        api = self.api()
        for bad in ("../x", "a/../../x", "/etc/passwd", "a//b", ".hidden", "a b", "x" * 200, ""):
            with self.assertRaises(PackError, msg=bad):
                api.write_text(bad, "x")
        outside = os.path.join(self.tmp, "outside.txt")
        api.write_text("seed.txt", "x")                       # creates the data folder
        link = os.path.join(self.mgr.store.data_dir("demo_data"), "link")
        os.symlink(outside, link)
        with self.assertRaises(PackError):
            api.write_text("link", "x")
        self.assertFalse(os.path.exists(outside))

    def test_size_limits(self):
        api = self.api()
        with self.assertRaises(PackError):
            api.write_text("big.txt", "x" * 1_100_000)

    def test_pack_can_read_its_own_files_only(self):
        api = self.api()
        self.assertIn("def register", api.read_pack_file("demo_data/main.py"))
        with self.assertRaises(FileNotFoundError):
            api.read_pack_file("persian_brain/messages.py")

    def test_inbox_is_read_through_plain_names_only(self):
        api = self.api()
        inbox = os.path.join(self.tmp, "data", "brain_hub", "inbox")      # the hub's inbox: the one inbox of the app
        os.makedirs(inbox)
        with open(os.path.join(inbox, "photo.png"), "wb") as handle:
            handle.write(b"\x89PNG-bytes")
        self.assertEqual(api.inbox_list(), [{"name": "photo.png", "bytes": 10}])
        self.assertEqual(api.inbox_read("photo.png"), b"\x89PNG-bytes")
        for bad in ("../data/packs/state.json", "a/b.png", "..", ".hidden"):
            with self.assertRaises(PackError, msg=bad):
                api.inbox_read(bad)
        api.inbox_take("photo.png", "images/photo.png")
        self.assertEqual(api.list_data(), ["images/photo.png"])
        self.assertEqual(api.inbox_list(), [])


class PackToolsTests(PackCase):
    def test_tools_and_recipes_register_and_unregister_with_the_pack(self):
        source = ("def register(api):\n    api.register_tool('double', 'دو برابر', lambda x: x * 2, summary_fa='ضرب در دو', params={'x': 'int'})\n"
                  "    api.register_recipe('r1', {'app': 'x'})\n")
        self.install(S.text_pack(pid="demo_tool", source=source, permissions="teacher"))
        tool = REGISTRY.tool("demo_tool", "double")
        self.assertEqual(tool.node_id, "pack.demo_tool.double")
        self.assertEqual(tool.fn(4), 8)
        self.assertEqual(REGISTRY.recipes(), {"r1": {"app": "x"}})
        self.mgr.disable("demo_tool")
        self.assertIsNone(REGISTRY.tool("demo_tool", "double"))
        self.assertEqual(REGISTRY.recipes(), {})

    def test_chat_handler_order_follows_priority(self):
        source = lambda pid, text, prio: ("def register(api):\n    api.register_chat('h', lambda c: True, lambda c: %r, stage='fallback', priority=%d)\n" % (text, prio))
        self.install(S.text_pack(pid="demo_greeter", source=source("a", "الف", 60)))
        self.install(S.text_pack(pid="demo_other", source=source("b", "ب", 40)))
        self.assertEqual(self.chat("هرچه"), "ب")

    def test_early_stage_is_separate_from_fallback(self):
        source = "def register(api):\n    api.register_chat('e', lambda c: True, lambda c: 'زود', stage='early')\n"
        self.install(S.text_pack(source=source))
        self.assertEqual(self.chat("x", "early"), "زود")
        self.assertIsNone(self.chat("x", "fallback"))


if __name__ == "__main__":
    unittest.main()
