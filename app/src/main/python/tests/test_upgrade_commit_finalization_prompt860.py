"""
Prompt 860 - upgrade commit finalization focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_upgrade_commit_finalization_prompt860 -v
"""

import ast
import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade import upgrade_commit_finalization as ucf
from upgrade.upgrade_commit import prepare_upgrade_commit as prepare
from upgrade.upgrade_commit_finalization import _finalize_errors
from upgrade.upgrade_commit_finalization import finalize_upgrade_commit as finalize
from upgrade.upgrade_commit_finalization import validate_finalized_commit as validate
from upgrade.upgrade_transaction import finalize_upgrade_transaction as finalize_tx
from tests.test_upgrade_commit_prompt859 import scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["version", "transaction_id", "proposal_id", "changes", "status",
        "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]


def ready():
    tx, ws, ver, cset = scenario()
    return tx, prepare(tx, ws, ver), cset


def reason(tx, commit, success=True):
    errs = _finalize_errors(tx, commit, success)
    return errs[0]["code"] if errs else None


class FinalizeValidTests(unittest.TestCase):
    def test_success_true_is_committed(self):
        tx, commit, _ = ready()
        r = finalize(tx, commit, True)
        self.assertEqual(list(r), KEYS)
        self.assertEqual(r["status"], "committed")
        json.dumps(r)

    def test_success_false_is_rolled_back(self):
        tx, commit, _ = ready()
        self.assertEqual(finalize(tx, commit, False)["status"], "rolled_back")

    def test_default_success_is_rolled_back(self):
        tx, commit, _ = ready()
        self.assertEqual(finalize(tx, commit)["status"], "rolled_back")

    def test_flags_always_false(self):
        tx, commit, _ = ready()
        for success in (True, False):
            r = finalize(tx, commit, success)
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_identities_and_changes_preserved(self):
        tx, commit, cset = ready()
        r = finalize(tx, commit, True)
        self.assertEqual(r["version"], "1")
        self.assertEqual(r["transaction_id"], tx["transaction_id"])
        self.assertEqual(r["transaction_id"], commit["transaction_id"])
        self.assertEqual(r["proposal_id"], tx["change_set_id"])
        self.assertEqual(r["changes"], cset["changes"])
        self.assertEqual([c["change_id"] for c in r["changes"]], ["change_1", "change_2"])

    def test_status_agrees_with_prompt856_finalization(self):
        tx, commit, _ = ready()
        for success in (True, False):
            self.assertEqual(finalize(tx, commit, success)["status"],
                             finalize_tx(tx, success)["transaction"]["status"])

    def test_result_validates(self):
        tx, commit, _ = ready()
        for success in (True, False):
            r = validate(finalize(tx, commit, success))
            self.assertEqual(list(r), VALIDATE_KEYS)
            self.assertEqual((r["valid"], r["errors"]), (True, []))

    def test_deterministic_and_fresh(self):
        tx, commit, _ = ready()
        a, b = finalize(tx, commit, True), finalize(tx, commit, True)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["changes"], commit["changes"])
        self.assertIsNot(a["changes"][0], commit["changes"][0])

    def test_inputs_never_modified(self):
        tx, commit, _ = ready()
        snap = copy.deepcopy((tx, commit))
        r = finalize(tx, commit, True)
        r["changes"][0]["reason"] = "mutated"
        self.assertEqual((tx, commit), snap)
        self.assertEqual(tx["status"], "pending")
        self.assertEqual(commit["status"], "ready_to_commit")


class FinalizeRejectTests(unittest.TestCase):
    def test_invalid_transaction(self):
        tx, commit, _ = ready()
        for bad in (None, [], "tx", dict(tx, version="2"), dict(tx, extra=1),
                    dict(tx, transaction_id="tx_" + "0" * 16)):
            self.assertIsNone(finalize(bad, commit, True))
        self.assertEqual(reason(None, commit), "invalid_transaction")

    def test_finalized_transaction_rejected(self):
        tx, commit, _ = ready()
        for ok in (True, False):
            fin = finalize_tx(tx, ok)["transaction"]
            self.assertIsNone(finalize(fin, commit, True))
            self.assertEqual(reason(fin, commit), "transaction_already_finalized")

    def test_invalid_commit_result(self):
        tx, commit, _ = ready()
        for bad in (None, {}, [], dict(commit, extra=1), dict(commit, status="committed"),
                    dict(commit, executed=True), dict(commit, execution_allowed=True),
                    dict(commit, version="2")):
            self.assertIsNone(finalize(tx, bad, True))
        self.assertEqual(reason(tx, None), "invalid_commit")

    def test_finalized_commit_record_is_not_a_ready_commit(self):
        tx, commit, _ = ready()
        done = finalize(tx, commit, True)
        self.assertIsNone(finalize(tx, done, True))

    def test_non_bool_success_rejected(self):
        tx, commit, _ = ready()
        for bad in (1, 0, "True", None, [], 1.0):
            self.assertIsNone(finalize(tx, commit, bad))
            self.assertEqual(reason(tx, commit, bad), "invalid_success")

    def test_transaction_id_mismatch_rejected(self):
        tx, commit, _ = ready()
        other = dict(tx, transaction_id="tx_" + "a" * 16)
        self.assertIsNone(finalize(other, commit, True))
        # a different, fully valid transaction (and commit) pair must not cross over
        from upgrade.upgrade_transaction import begin_upgrade_transaction as begin
        from tests.test_upgrade_sandbox_prompt857 import change_set
        tx2 = begin(change_set(("modify_file", "formatter/response.py")))["transaction"]
        self.assertIsNone(finalize(tx2, commit, True))
        self.assertEqual(reason(tx2, commit), "transaction_id_mismatch")

    def test_proposal_id_mismatch_rejected(self):
        tx, commit, _ = ready()
        # same id and changes, but a different proposal id: the commit's own derived-id
        # check fails, so it is rejected as an invalid commit
        self.assertIsNone(finalize(tx, dict(commit, proposal_id="plan_other"), True))

    def test_changed_changes_rejected(self):
        tx, commit, _ = ready()
        bad = copy.deepcopy(commit)
        bad["changes"][0]["reason"] = "tampered"
        self.assertIsNone(finalize(tx, bad, True))

    def test_reordered_changes_rejected(self):
        tx, commit, _ = ready()
        bad = copy.deepcopy(commit)
        bad["changes"].reverse()
        self.assertIsNone(finalize(tx, bad, True))

    def test_commit_changes_diverging_from_transaction_rejected(self):
        # Valid commit record in itself (consistent id), but built for other changes.
        tx, commit, _ = ready()
        from upgrade.upgrade_transaction import begin_upgrade_transaction as begin
        from tests.test_upgrade_sandbox_prompt857 import change_set
        short = change_set(("modify_file", "formatter/style.py"))
        tx_short = begin(short)["transaction"]
        forged = dict(tx_short, transaction_id=tx["transaction_id"])
        self.assertIsNone(finalize(forged, commit, True))

    def test_never_raises_on_garbage(self):
        for args in ((), (1, 2, 3), (object(), object(), object()), ({}, {}, {}),
                     (None, None, None)):
            self.assertIsNone(finalize(*args))


class ValidateFinalizedTests(unittest.TestCase):
    def setUp(self):
        tx, commit, _ = ready()
        self.final = finalize(tx, commit, True)

    def errors(self, result):
        r = validate(result)
        self.assertEqual(list(r), VALIDATE_KEYS)
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)
        return [e["code"] for e in r["errors"]]

    def test_missing_and_non_dict(self):
        self.assertEqual(self.errors(None), ["missing_commit"])
        for bad in ([], "x", 1):
            self.assertEqual(self.errors(bad), ["commit_not_dict"])

    def test_unexpected_and_missing_fields(self):
        self.assertIn("unexpected_field", self.errors(dict(self.final, extra=1)))
        for key in KEYS:
            r = dict(self.final)
            del r[key]
            self.assertIn("missing_field", self.errors(r))

    def test_only_final_statuses_valid(self):
        self.assertEqual(self.errors(dict(self.final, status="rolled_back")), [])
        for bad in ("ready_to_commit", "pending", "COMMITTED", None, 1):
            self.assertEqual(self.errors(dict(self.final, status=bad)), ["invalid_status"])

    def test_flags_must_be_exactly_false(self):
        for key in ("execution_allowed", "executed"):
            for bad in (True, 0, None, "False"):
                self.assertEqual(self.errors(dict(self.final, **{key: bad})), ["invalid_" + key])

    def test_identity_and_changes_consistency(self):
        self.assertEqual(self.errors(dict(self.final, transaction_id="tx_" + "f" * 16)),
                         ["transaction_id_mismatch"])
        self.assertEqual(self.errors(dict(self.final, proposal_id="plan_other")),
                         ["transaction_id_mismatch"])
        r = copy.deepcopy(self.final)
        r["changes"][0]["reason"] = "tampered"
        self.assertEqual(self.errors(r), ["transaction_id_mismatch"])
        self.assertTrue(self.errors(dict(self.final, changes=[])))
        self.assertEqual(self.errors(dict(self.final, version=1)), ["invalid_version"])

    def test_validation_does_not_repair_or_modify(self):
        bad = dict(self.final, status="ready_to_commit")
        snap = copy.deepcopy(bad)
        self.assertFalse(validate(bad)["valid"])
        self.assertEqual(bad, snap)

    def test_validate_never_raises(self):
        class Boom(dict):
            def __len__(self):
                raise RuntimeError("boom")
        self.assertFalse(validate(Boom())["valid"])


class BoundaryTests(unittest.TestCase):
    def test_module_has_no_forbidden_imports_or_calls(self):
        with open(os.path.join(ROOT, "upgrade", "upgrade_commit_finalization.py"),
                  encoding="utf-8") as fh:
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

    def test_public_api(self):
        public = sorted(n for n in dir(ucf) if not n.startswith("_") and callable(getattr(ucf, n))
                        and getattr(getattr(ucf, n), "__module__", "") == ucf.__name__)
        self.assertEqual(public, ["finalize_upgrade_commit", "validate_finalized_commit"])


if __name__ == "__main__":
    unittest.main()
