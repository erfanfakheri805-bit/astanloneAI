"""
Prompt 862 - Section 14 (Self-Upgrade Engine) final checkpoint.

End-to-end contract validation of the existing public chain (Prompts 849-861):

  upgrade_request -> project_state -> upgrade_plan -> change_proposal -> upgrade_policy
  -> change_set -> transaction -> sandbox -> verification -> commit
  -> commit_finalization -> audit

No production code is added or changed; these tests only compose the public APIs.

Run (from app/src/main/python/):
    python -m unittest tests.test_section14_upgrade_checkpoint_prompt862 -v
"""

import ast
import builtins
import copy
import hashlib
import os
import socket
import subprocess
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade.change_proposal import build_change_proposal, validate_change_proposal
from upgrade.change_set import build_change_set, validate_change_set
from upgrade.project_state import build_project_state, validate_project_state
from upgrade.upgrade_audit import build_upgrade_audit_record, validate_upgrade_audit_record
from upgrade.upgrade_commit import prepare_upgrade_commit, validate_upgrade_commit
from upgrade.upgrade_commit_finalization import finalize_upgrade_commit, validate_finalized_commit
from upgrade.upgrade_plan import build_upgrade_plan, validate_upgrade_plan
from upgrade.upgrade_policy import evaluate_upgrade_policy, validate_upgrade_policy_result
from upgrade.upgrade_request import build_upgrade_request, validate_upgrade_request
from upgrade.upgrade_sandbox import (
    apply_change_set_to_sandbox,
    build_sandbox_workspace,
    validate_sandbox_workspace,
)
from upgrade.upgrade_transaction import (
    begin_upgrade_transaction,
    finalize_upgrade_transaction,
    validate_upgrade_transaction,
)
from upgrade.upgrade_verification import validate_sandbox_verification, verify_sandbox_result

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHAIN_MODULES = ("upgrade_request", "project_state", "upgrade_plan", "change_proposal",
                 "upgrade_policy", "change_set", "upgrade_transaction", "upgrade_sandbox",
                 "upgrade_verification", "upgrade_commit", "upgrade_commit_finalization",
                 "upgrade_audit")

STATE_SOURCE = {
    "project_id": "proj_001", "revision": "r862",
    "files": [{"path": "formatter/response.py", "kind": "module", "status": "present"},
              {"path": "formatter/style.py", "kind": "module", "status": "present"}],
    "capabilities": ["response_format", "tone"], "tests": ["tests.test_formatter"],
    "constraints": ["Frozen tests stay unchanged."]}

REQUEST_SOURCE = {
    "request_id": "upg_001", "goal": "Improve response formatting.",
    "scope": ["formatter/response.py", "response_format"],
    "constraints": ["No data loss."], "requested_by": "developer"}


def run_chain(success=True):
    """Compose every public stage on valid deterministic fixtures."""
    s = {}
    s["request"] = build_upgrade_request(copy.deepcopy(REQUEST_SOURCE))
    s["state"] = build_project_state(copy.deepcopy(STATE_SOURCE))
    s["plan"] = build_upgrade_plan(s["request"]["upgrade_request"], s["state"]["project_state"])
    s["proposal"] = build_change_proposal(s["plan"]["plan"], s["state"]["project_state"])
    s["policy"] = evaluate_upgrade_policy(s["proposal"]["proposal"], s["state"]["project_state"])
    s["change_set"] = build_change_set(s["proposal"]["proposal"], s["policy"])
    cset = s["change_set"]["change_set"]
    s["begin"] = begin_upgrade_transaction(cset)
    s["workspace0"] = build_sandbox_workspace(s["state"]["project_state"])
    s["applied"] = apply_change_set_to_sandbox(s["workspace0"]["workspace"], cset)
    ws = s["applied"]["workspace"]
    s["verification"] = verify_sandbox_result(ws, cset, s["policy"])
    tx = s["begin"]["transaction"]
    s["commit"] = prepare_upgrade_commit(tx, ws, s["verification"])
    s["final_commit"] = finalize_upgrade_commit(tx, s["commit"], success)
    s["final_tx"] = finalize_upgrade_transaction(tx, success)
    s["audit"] = build_upgrade_audit_record(s["final_tx"]["transaction"], s["final_commit"])
    return s


def flags_false(test, value, path="stage"):
    """Every execution_allowed / executed flag found anywhere must be exactly False."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("execution_allowed", "executed"):
                test.assertIs(item, False, "%s.%s" % (path, key))
            flags_false(test, item, "%s.%s" % (path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            flags_false(test, item, "%s[%d]" % (path, index))


def tree_fingerprint():
    digest = hashlib.sha256()
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            path = os.path.join(base, name)
            stat = os.stat(path)
            digest.update(("%s|%d|%d\n" % (os.path.relpath(path, ROOT), stat.st_size,
                                           stat.st_mtime_ns)).encode())
    return digest.hexdigest()


def _forbidden(*args, **kwargs):
    raise AssertionError("forbidden side effect during Section 14 chain")


class SuccessPathTests(unittest.TestCase):
    def test_every_stage_succeeds_on_valid_fixtures(self):
        s = run_chain(True)
        for name in ("request", "state", "plan", "proposal", "change_set", "begin",
                     "workspace0", "final_tx"):
            self.assertTrue(s[name]["valid"], (name, s[name].get("errors")))
        self.assertEqual(s["policy"]["status"], "allowed")
        self.assertEqual(s["applied"]["status"], "applied")
        self.assertEqual(s["verification"]["status"], "valid")

    def test_full_success_path_reaches_committed_audit(self):
        s = run_chain(True)
        self.assertEqual(s["audit"]["status"], "committed")
        self.assertEqual(s["final_commit"]["status"], "committed")
        self.assertEqual(s["final_tx"]["transaction"]["status"], "committed")
        self.assertEqual(s["commit"]["status"], "ready_to_commit")

    def test_rollback_path_reaches_rolled_back_audit(self):
        s = run_chain(False)
        self.assertEqual(s["audit"]["status"], "rolled_back")
        self.assertEqual(s["final_commit"]["status"], "rolled_back")
        self.assertEqual(s["final_tx"]["transaction"]["status"], "rolled_back")

    def test_identities_flow_through_the_whole_chain(self):
        s = run_chain(True)
        proposal_id = s["proposal"]["proposal"]["plan_id"]
        tx_id = s["begin"]["transaction"]["transaction_id"]
        self.assertEqual(s["policy"]["proposal_id"], proposal_id)
        self.assertEqual(s["change_set"]["change_set"]["proposal_id"], proposal_id)
        self.assertEqual(s["begin"]["transaction"]["change_set_id"], proposal_id)
        self.assertEqual(s["verification"]["proposal_id"], proposal_id)
        for record in (s["commit"], s["final_commit"], s["audit"]):
            self.assertEqual(record["proposal_id"], proposal_id)
            self.assertEqual(record["transaction_id"], tx_id)

    def test_changes_identical_and_ordered_end_to_end(self):
        s = run_chain(True)
        expected = s["proposal"]["proposal"]["changes"]
        self.assertTrue(expected)
        self.assertEqual(s["change_set"]["change_set"]["changes"], expected)
        self.assertEqual(s["begin"]["transaction"]["changes"], expected)
        self.assertEqual(s["applied"]["workspace"]["applied"][0]["changes"], expected)
        for record in (s["commit"], s["final_commit"], s["audit"]):
            self.assertEqual(record["changes"], expected)

    def test_all_stage_validators_accept_stage_outputs(self):
        s = run_chain(True)
        checks = [
            validate_upgrade_request(s["request"]["upgrade_request"]),
            validate_project_state(s["state"]["project_state"]),
            validate_upgrade_plan(s["plan"]["plan"]),
            validate_change_proposal(s["proposal"]["proposal"]),
            validate_upgrade_policy_result(s["policy"]),
            validate_change_set(s["change_set"]["change_set"]),
            validate_upgrade_transaction(s["begin"]["transaction"]),
            validate_upgrade_transaction(s["final_tx"]["transaction"]),
            validate_sandbox_workspace(s["applied"]["workspace"]),
            validate_sandbox_verification(s["verification"]),
            validate_upgrade_commit(s["commit"]),
            validate_finalized_commit(s["final_commit"]),
            validate_upgrade_audit_record(s["audit"]),
        ]
        for index, check in enumerate(checks):
            self.assertTrue(check["valid"], (index, check["errors"]))

    def test_chain_is_deterministic(self):
        a, b = run_chain(True), run_chain(True)
        for key in ("proposal", "policy", "change_set", "commit", "final_commit", "audit"):
            self.assertEqual(a[key], b[key], key)

    def test_audit_has_exact_shape(self):
        for success in (True, False):
            audit = run_chain(success)["audit"]
            self.assertEqual(list(audit), ["version", "transaction_id", "proposal_id", "status",
                                           "changes", "execution_allowed", "executed"])


class RejectionPathTests(unittest.TestCase):
    def setUp(self):
        self.s = run_chain(True)

    def test_invalid_request(self):
        r = build_upgrade_request({})
        self.assertFalse(r["valid"])
        self.assertIsNone(r["upgrade_request"])
        plan = build_upgrade_plan(r["upgrade_request"], self.s["state"]["project_state"])
        self.assertFalse(plan["valid"])

    def test_invalid_project_state(self):
        bad = build_project_state({})
        self.assertFalse(bad["valid"])
        self.assertIsNone(bad["project_state"])
        self.assertFalse(build_upgrade_plan(self.s["request"]["upgrade_request"],
                                            bad["project_state"])["valid"])
        self.assertFalse(build_sandbox_workspace(bad["project_state"])["valid"])

    def test_invalid_plan_and_proposal(self):
        self.assertFalse(build_change_proposal(None, self.s["state"]["project_state"])["valid"])
        tampered = dict(self.s["plan"]["plan"], execution_allowed=True)
        self.assertFalse(validate_upgrade_plan(tampered)["valid"])
        self.assertFalse(build_change_proposal(tampered, self.s["state"]["project_state"])["valid"])
        proposal = dict(self.s["proposal"]["proposal"], execution_allowed=True)
        self.assertFalse(validate_change_proposal(proposal)["valid"])

    def test_denied_policy_blocks_change_set(self):
        proposal = dict(self.s["proposal"]["proposal"], affected_files=[])
        policy = evaluate_upgrade_policy(proposal, self.s["state"]["project_state"])
        self.assertEqual(policy["status"], "policy_denied")
        self.assertIs(policy["allowed"], False)
        self.assertFalse(build_change_set(proposal, policy)["valid"])
        self.assertFalse(build_change_set(self.s["proposal"]["proposal"], policy)["valid"])

    def test_invalid_change_set(self):
        cset = self.s["change_set"]["change_set"]
        for bad in (None, dict(cset, execution_allowed=True), dict(cset, changes=[]),
                    dict(cset, version="2")):
            self.assertFalse(validate_change_set(bad)["valid"])
            self.assertFalse(begin_upgrade_transaction(bad)["valid"])

    def test_invalid_transaction(self):
        tx = self.s["begin"]["transaction"]
        for bad in (None, dict(tx, executed=True), dict(tx, transaction_id="tx_" + "0" * 16),
                    dict(tx, status="unknown")):
            self.assertFalse(validate_upgrade_transaction(bad)["valid"])
            self.assertFalse(finalize_upgrade_transaction(bad, True)["valid"])
            self.assertIsNone(prepare_upgrade_commit(bad, self.s["applied"]["workspace"],
                                                     self.s["verification"]))

    def test_sandbox_rejection(self):
        ws = self.s["workspace0"]["workspace"]
        cset = self.s["change_set"]["change_set"]
        unknown = dict(cset, changes=[dict(cset["changes"][0], target="formatter/nope.py",
                                           action="modify_file")])
        r = apply_change_set_to_sandbox(ws, unknown)
        self.assertEqual((r["status"], r["applied"], r["workspace"]), ("rejected", False, None))
        again = apply_change_set_to_sandbox(self.s["applied"]["workspace"], cset)
        self.assertEqual(again["status"], "rejected")
        self.assertEqual(apply_change_set_to_sandbox(None, cset)["status"], "rejected")

    def test_verification_rejection(self):
        cset = self.s["change_set"]["change_set"]
        not_applied = verify_sandbox_result(self.s["workspace0"]["workspace"], cset)
        self.assertEqual(not_applied["status"], "not_applied")
        tampered_ws = copy.deepcopy(self.s["applied"]["workspace"])
        tampered_ws["applied"][0]["changes"][0]["reason"] = "forged"
        self.assertEqual(verify_sandbox_result(tampered_ws, cset)["status"], "tampered")
        self.assertFalse(verify_sandbox_result(None, cset)["valid"])

    def test_invalid_commit_preparation(self):
        tx = self.s["begin"]["transaction"]
        cset = self.s["change_set"]["change_set"]
        failed = verify_sandbox_result(self.s["workspace0"]["workspace"], cset)
        self.assertIsNone(prepare_upgrade_commit(tx, self.s["applied"]["workspace"], failed))
        self.assertIsNone(prepare_upgrade_commit(tx, self.s["workspace0"]["workspace"],
                                                 self.s["verification"]))
        done = self.s["final_tx"]["transaction"]
        self.assertIsNone(prepare_upgrade_commit(done, self.s["applied"]["workspace"],
                                                 self.s["verification"]))

    def test_invalid_finalization(self):
        tx = self.s["begin"]["transaction"]
        commit = self.s["commit"]
        for bad in (1, "True", None):
            self.assertIsNone(finalize_upgrade_commit(tx, commit, bad))
        self.assertIsNone(finalize_upgrade_commit(self.s["final_tx"]["transaction"], commit, True))
        self.assertIsNone(finalize_upgrade_commit(tx, dict(commit, status="committed"), True))
        reordered = copy.deepcopy(commit)
        reordered["changes"].reverse()
        self.assertIsNone(finalize_upgrade_commit(tx, reordered, True))

    def test_audit_rejects_pending_and_mismatched_inputs(self):
        tx = self.s["begin"]["transaction"]
        fc = self.s["final_commit"]
        self.assertIsNone(build_upgrade_audit_record(tx, fc))  # pending transaction
        rolled = finalize_upgrade_transaction(tx, False)["transaction"]
        self.assertIsNone(build_upgrade_audit_record(rolled, fc))  # status mismatch
        self.assertIsNone(build_upgrade_audit_record(self.s["final_tx"]["transaction"],
                                                     dict(fc, status="ready_to_commit")))


class SafetyTests(unittest.TestCase):
    def test_flags_stay_false_on_every_stage_output(self):
        for success in (True, False):
            for name, stage in run_chain(success).items():
                flags_false(self, stage, name)

    def test_flags_stay_false_on_rejection_outputs(self):
        s = run_chain(True)
        cset = s["change_set"]["change_set"]
        outputs = [build_upgrade_request({}), build_project_state({}),
                   verify_sandbox_result(s["workspace0"]["workspace"], cset),
                   apply_change_set_to_sandbox(s["applied"]["workspace"], cset),
                   finalize_upgrade_transaction(s["final_tx"]["transaction"], True),
                   validate_upgrade_commit(None), validate_finalized_commit(None),
                   validate_upgrade_audit_record(None)]
        for index, out in enumerate(outputs):
            flags_false(self, out, "rejection%d" % index)

    def test_chain_causes_no_filesystem_subprocess_or_network_activity(self):
        before = tree_fingerprint()
        with mock.patch.object(builtins, "open", _forbidden), \
                mock.patch.object(subprocess, "Popen", _forbidden), \
                mock.patch.object(os, "system", _forbidden), \
                mock.patch.object(os, "remove", _forbidden), \
                mock.patch.object(os, "rename", _forbidden), \
                mock.patch.object(os, "mkdir", _forbidden), \
                mock.patch.object(socket, "socket", _forbidden):
            for success in (True, False):
                self.assertEqual(run_chain(success)["audit"]["status"],
                                 "committed" if success else "rolled_back")
        self.assertEqual(tree_fingerprint(), before)

    def test_inputs_are_not_modified_by_the_chain(self):
        s = run_chain(True)
        cset = s["change_set"]["change_set"]
        snapshot = copy.deepcopy((s["begin"]["transaction"], s["applied"]["workspace"],
                                  s["verification"], s["commit"], cset))
        for success in (True, False):
            finalize_upgrade_commit(s["begin"]["transaction"], s["commit"], success)
            finalize_upgrade_transaction(s["begin"]["transaction"], success)
        build_upgrade_audit_record(s["final_tx"]["transaction"], s["final_commit"])
        prepare_upgrade_commit(s["begin"]["transaction"], s["applied"]["workspace"],
                               s["verification"])
        self.assertEqual(snapshot, copy.deepcopy((s["begin"]["transaction"],
                                                  s["applied"]["workspace"], s["verification"],
                                                  s["commit"], cset)))
        self.assertEqual(s["begin"]["transaction"]["status"], "pending")

    def test_chain_modules_import_only_upgrade_and_pure_stdlib(self):
        allowed = {"upgrade", "hashlib", "json", "copy"}
        for name in CHAIN_MODULES:
            path = os.path.join(ROOT, "upgrade", name + ".py")
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    roots = {(node.module or "").split(".")[0]}
                else:
                    continue
                self.assertTrue(roots <= allowed, (name, roots - allowed))
                for root in roots:  # explicit: no Core / Memory / AEL link
                    self.assertNotIn(root, {"core", "memory", "ael", "execution", "agent"})

    def test_chain_modules_use_no_io_or_execution_calls(self):
        banned = {"open", "exec", "eval", "compile", "__import__", "input"}
        for name in CHAIN_MODULES:
            with open(os.path.join(ROOT, "upgrade", name + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, banned, name)

    def test_chain_import_does_not_load_core_memory_or_ael(self):
        for module in list(sys.modules):
            if module.startswith("upgrade."):
                mod = sys.modules[module]
                for attr in vars(mod).values():
                    origin = getattr(attr, "__module__", "") or ""
                    self.assertFalse(origin.split(".")[0] in {"core", "memory", "ael"},
                                     (module, origin))


if __name__ == "__main__":
    unittest.main()
