"""
Prompt 859 - upgrade commit boundary focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_upgrade_commit_prompt859 -v
"""

import ast
import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade import upgrade_commit as uc
from upgrade.upgrade_commit import _prepare_errors
from upgrade.upgrade_commit import prepare_upgrade_commit as prepare
from upgrade.upgrade_commit import validate_upgrade_commit as validate
from upgrade.upgrade_sandbox import apply_change_set_to_sandbox as apply_cs
from upgrade.upgrade_transaction import begin_upgrade_transaction as begin
from upgrade.upgrade_transaction import finalize_upgrade_transaction as finalize
from upgrade.upgrade_verification import verify_sandbox_result as verify
from tests.test_upgrade_sandbox_prompt857 import change_set, workspace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COMMIT_KEYS = ["version", "transaction_id", "proposal_id", "changes", "status",
               "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]


def scenario(cset=None):
    """(transaction, applied workspace, valid verification result, change set)."""
    cset = cset or change_set(("modify_file", "formatter/style.py"), ("update_capability", "tone"))
    tx = begin(cset)["transaction"]
    ws = apply_cs(workspace(), cset)["workspace"]
    ver = verify(ws, cset)
    assert ver["status"] == "valid", ver
    return tx, ws, ver, cset


def reason(tx, ws, ver):
    errs = _prepare_errors(tx, ws, ver)
    return errs[0]["code"] if errs else None


class PrepareValidTests(unittest.TestCase):
    def test_prepares_ready_commit_with_exact_shape(self):
        tx, ws, ver, cset = scenario()
        c = prepare(tx, ws, ver)
        self.assertEqual(list(c), COMMIT_KEYS)
        self.assertEqual(c["version"], "1")
        self.assertEqual(c["status"], "ready_to_commit")
        self.assertIs(c["execution_allowed"], False)
        self.assertIs(c["executed"], False)
        json.dumps(c)

    def test_identity_fields_come_from_transaction(self):
        tx, ws, ver, cset = scenario()
        c = prepare(tx, ws, ver)
        self.assertEqual(c["transaction_id"], tx["transaction_id"])
        self.assertEqual(c["proposal_id"], cset["proposal_id"])
        self.assertEqual(c["proposal_id"], ver["proposal_id"])

    def test_changes_match_change_set_exactly_in_order(self):
        tx, ws, ver, cset = scenario()
        c = prepare(tx, ws, ver)
        self.assertEqual(c["changes"], cset["changes"])
        self.assertEqual([x["change_id"] for x in c["changes"]], ["change_1", "change_2"])

    def test_commit_validates(self):
        c = prepare(*scenario()[:3])
        r = validate(c)
        self.assertEqual(list(r), VALIDATE_KEYS)
        self.assertEqual((r["valid"], r["errors"]), (True, []))

    def test_deterministic_and_fresh(self):
        tx, ws, ver, _ = scenario()
        a, b = prepare(tx, ws, ver), prepare(tx, ws, ver)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["changes"], b["changes"])
        self.assertIsNot(a["changes"][0], tx["changes"][0])

    def test_inputs_not_modified(self):
        tx, ws, ver, _ = scenario()
        snap = copy.deepcopy((tx, ws, ver))
        c = prepare(tx, ws, ver)
        c["changes"][0]["reason"] = "mutated"
        self.assertEqual((tx, ws, ver), snap)

    def test_other_applied_sets_do_not_interfere(self):
        tx, ws, ver, cset = scenario()
        second = dict(change_set(("modify_file", "formatter/response.py")), proposal_id="plan_second")
        ws2 = apply_cs(ws, second)["workspace"]
        c = prepare(tx, ws2, verify(ws2, cset))
        self.assertEqual(c["proposal_id"], cset["proposal_id"])


class PrepareRejectTests(unittest.TestCase):
    def test_invalid_transaction(self):
        tx, ws, ver, _ = scenario()
        for bad in (None, [], "tx", dict(tx, version="2"), dict(tx, extra=1)):
            self.assertIsNone(prepare(bad, ws, ver))
        self.assertEqual(reason(None, ws, ver), "invalid_transaction")

    def test_tampered_transaction_id_rejected(self):
        tx, ws, ver, _ = scenario()
        bad = dict(tx, transaction_id="tx_" + "0" * 16)
        self.assertIsNone(prepare(bad, ws, ver))
        self.assertEqual(reason(bad, ws, ver), "invalid_transaction")

    def test_finalized_transactions_rejected(self):
        tx, ws, ver, _ = scenario()
        for success in (True, False):
            fin = finalize(tx, success)["transaction"]
            self.assertIsNone(prepare(fin, ws, ver))
            self.assertEqual(reason(fin, ws, ver), "transaction_not_pending")

    def test_invalid_workspace(self):
        tx, ws, ver, _ = scenario()
        for bad in (None, {}, dict(ws, executed=True), dict(ws, version="2")):
            self.assertIsNone(prepare(tx, bad, ver))
        self.assertEqual(reason(tx, None, ver), "invalid_workspace")

    def test_invalid_verification_structure(self):
        tx, ws, ver, _ = scenario()
        for bad in (None, {}, [], dict(ver, extra=1), dict(ver, executed=True),
                    dict(ver, execution_allowed=True)):
            self.assertIsNone(prepare(tx, ws, bad))
        self.assertEqual(reason(tx, ws, None), "invalid_verification")

    def test_failed_verification_rejected(self):
        tx, ws, _, cset = scenario()
        failed = verify(workspace(), cset)  # not applied in a fresh workspace
        self.assertEqual(failed["status"], "not_applied")
        self.assertIsNone(prepare(tx, ws, failed))
        self.assertEqual(reason(tx, ws, failed), "verification_not_valid")

    def test_verification_for_other_change_set_rejected(self):
        tx, ws, ver, _ = scenario()
        other = dict(change_set(("modify_file", "formatter/response.py")), proposal_id="plan_other")
        ws2 = apply_cs(ws, other)["workspace"]
        other_ver = verify(ws2, other)
        self.assertEqual(other_ver["status"], "valid")
        self.assertIsNone(prepare(tx, ws2, other_ver))
        self.assertEqual(reason(tx, ws2, other_ver), "verification_mismatch")

    def test_change_set_not_applied_rejected(self):
        tx, _, ver, _ = scenario()
        fresh = workspace()
        self.assertIsNone(prepare(tx, fresh, ver))
        self.assertEqual(reason(tx, fresh, ver), "change_set_not_applied")

    def test_workspace_record_tampered_rejected(self):
        tx, ws, ver, _ = scenario()
        bad = copy.deepcopy(ws)
        bad["applied"][0]["changes"][0]["reason"] = "forged"
        self.assertIsNone(prepare(tx, bad, ver))
        self.assertEqual(reason(tx, bad, ver), "applied_changes_mismatch")

    def test_forged_verification_rejected(self):
        # A hand-built "valid" verification for a transaction whose change set was
        # never applied must not be accepted.
        tx, _, _, _ = scenario()
        fresh = workspace()
        forged = {"valid": True, "status": "valid", "errors": [],
                  "proposal_id": tx["change_set_id"], "execution_allowed": False,
                  "executed": False}
        self.assertIsNone(prepare(tx, fresh, forged))

    def test_verification_for_diverged_transaction_rejected(self):
        # Same proposal id, but the transaction's changes no longer match what was
        # applied and verified: the old verification must not authorize a commit.
        tx, ws, ver, _ = scenario()
        # Transaction changes diverge from the applied record -> verification no longer holds.
        other_cset = change_set(("modify_file", "formatter/style.py"))
        other_cset["proposal_id"] = tx["change_set_id"]
        tx2 = begin(other_cset)["transaction"]
        self.assertIsNone(prepare(tx2, ws, ver))

    def test_never_raises_on_garbage(self):
        for args in ((), (1, 2, 3), (object(), object(), object()), ({}, {}, {}),
                     (None, None, None)):
            self.assertIsNone(prepare(*args))


class ValidateCommitTests(unittest.TestCase):
    def setUp(self):
        self.commit = prepare(*scenario()[:3])

    def errors(self, commit):
        r = validate(commit)
        self.assertEqual(list(r), VALIDATE_KEYS)
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)
        return [e["code"] for e in r["errors"]]

    def test_missing_and_non_dict(self):
        self.assertEqual(self.errors(None), ["missing_commit"])
        for bad in ([], "x", 1, (1,)):
            self.assertEqual(self.errors(bad), ["commit_not_dict"])

    def test_unexpected_and_missing_fields(self):
        self.assertIn("unexpected_field", self.errors(dict(self.commit, extra=1)))
        for key in COMMIT_KEYS:
            c = dict(self.commit)
            del c[key]
            self.assertIn("missing_field", self.errors(c))

    def test_status_must_be_exactly_ready_to_commit(self):
        for bad in ("committed", "pending", "READY_TO_COMMIT", None, 1):
            self.assertEqual(self.errors(dict(self.commit, status=bad)), ["invalid_status"])

    def test_flags_must_be_exactly_false(self):
        for key in ("execution_allowed", "executed"):
            for bad in (True, 0, None, "False"):
                self.assertEqual(self.errors(dict(self.commit, **{key: bad})), ["invalid_" + key])

    def test_version_type_and_identity_fields(self):
        self.assertEqual(self.errors(dict(self.commit, version="2")), ["invalid_version"])
        self.assertEqual(self.errors(dict(self.commit, version=1)), ["invalid_version"])
        self.assertEqual(self.errors(dict(self.commit, proposal_id="")), ["invalid_proposal_id"])
        self.assertEqual(self.errors(dict(self.commit, transaction_id=5)), ["invalid_transaction_id"])

    def test_identity_must_match_changes(self):
        self.assertEqual(self.errors(dict(self.commit, transaction_id="tx_" + "f" * 16)),
                         ["transaction_id_mismatch"])
        self.assertEqual(self.errors(dict(self.commit, proposal_id="plan_other")),
                         ["transaction_id_mismatch"])
        c = copy.deepcopy(self.commit)
        c["changes"][0]["reason"] = "tampered"
        self.assertEqual(self.errors(c), ["transaction_id_mismatch"])

    def test_invalid_changes_rejected(self):
        self.assertTrue(self.errors(dict(self.commit, changes=[])))
        self.assertTrue(self.errors(dict(self.commit, changes="x")))
        self.assertTrue(self.errors(dict(self.commit, changes=[{"change_id": "c"}])))
        dup = [self.commit["changes"][0], dict(self.commit["changes"][0])]
        self.assertTrue(self.errors(dict(self.commit, changes=dup)))

    def test_validation_does_not_repair_or_modify(self):
        bad = dict(self.commit, status="committed")
        snap = copy.deepcopy(bad)
        validate(bad)
        self.assertEqual(bad, snap)

    def test_validate_never_raises(self):
        class Boom(dict):
            def __len__(self):
                raise RuntimeError("boom")
        r = validate(Boom())
        self.assertFalse(r["valid"])


class BoundaryTests(unittest.TestCase):
    def test_module_has_no_forbidden_imports_or_calls(self):
        with open(os.path.join(ROOT, "upgrade", "upgrade_commit.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        banned = {"os", "sys", "subprocess", "socket", "urllib", "http", "requests", "shutil",
                  "pathlib", "importlib", "builtins", "pickle", "core", "memory", "ael"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], banned)
            elif isinstance(node, ast.ImportFrom):
                self.assertTrue(node.module.startswith("upgrade."), node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__"})

    def test_public_api_and_constants(self):
        public = sorted(n for n in dir(uc) if not n.startswith("_") and callable(getattr(uc, n))
                        and getattr(getattr(uc, n), "__module__", "") == uc.__name__)
        self.assertEqual(public, ["prepare_upgrade_commit", "validate_upgrade_commit"])
        self.assertEqual(uc.STATUS_READY_TO_COMMIT, "ready_to_commit")


if __name__ == "__main__":
    unittest.main()
