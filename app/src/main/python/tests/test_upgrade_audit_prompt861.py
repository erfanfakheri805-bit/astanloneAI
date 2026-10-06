"""
Prompt 861 - upgrade audit record focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_upgrade_audit_prompt861 -v
"""

import ast
import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade import upgrade_audit as ua
from upgrade.upgrade_audit import _build_errors
from upgrade.upgrade_audit import build_upgrade_audit_record as build
from upgrade.upgrade_audit import validate_upgrade_audit_record as validate
from upgrade.upgrade_commit import prepare_upgrade_commit as prepare
from upgrade.upgrade_commit_finalization import finalize_upgrade_commit
from upgrade.upgrade_transaction import begin_upgrade_transaction as begin
from upgrade.upgrade_transaction import finalize_upgrade_transaction as finalize_tx
from tests.test_upgrade_commit_prompt859 import scenario
from tests.test_upgrade_sandbox_prompt857 import change_set

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["version", "transaction_id", "proposal_id", "status", "changes",
        "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]


def finalized(success=True):
    """(finalized transaction, finalized commit, change set)."""
    tx, ws, ver, cset = scenario()
    commit = prepare(tx, ws, ver)
    fc = finalize_upgrade_commit(tx, commit, success)
    ftx = finalize_tx(tx, success)["transaction"]
    assert fc and ftx
    return ftx, fc, cset


def reason(ftx, fc):
    errs = _build_errors(ftx, fc)
    return errs[0]["code"] if errs else None


class BuildValidTests(unittest.TestCase):
    def test_committed_record(self):
        ftx, fc, _ = finalized(True)
        r = build(ftx, fc)
        self.assertEqual(list(r), KEYS)
        self.assertEqual(r["status"], "committed")
        json.dumps(r)

    def test_rolled_back_record(self):
        ftx, fc, _ = finalized(False)
        self.assertEqual(build(ftx, fc)["status"], "rolled_back")

    def test_status_matches_finalized_result(self):
        for success in (True, False):
            ftx, fc, _ = finalized(success)
            self.assertEqual(build(ftx, fc)["status"], fc["status"])
            self.assertEqual(build(ftx, fc)["status"], ftx["status"])

    def test_identities_and_changes_exact_and_ordered(self):
        ftx, fc, cset = finalized(True)
        r = build(ftx, fc)
        self.assertEqual(r["version"], "1")
        self.assertEqual(r["transaction_id"], ftx["transaction_id"])
        self.assertEqual(r["proposal_id"], ftx["change_set_id"])
        self.assertEqual(r["transaction_id"], fc["transaction_id"])
        self.assertEqual(r["proposal_id"], fc["proposal_id"])
        self.assertEqual(r["changes"], cset["changes"])
        self.assertEqual([c["change_id"] for c in r["changes"]], ["change_1", "change_2"])

    def test_flags_always_false(self):
        for success in (True, False):
            r = build(*finalized(success)[:2])
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_record_validates(self):
        for success in (True, False):
            r = validate(build(*finalized(success)[:2]))
            self.assertEqual(list(r), VALIDATE_KEYS)
            self.assertEqual((r["valid"], r["errors"]), (True, []))

    def test_deterministic_and_fresh(self):
        ftx, fc, _ = finalized()
        a, b = build(ftx, fc), build(ftx, fc)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["changes"], ftx["changes"])
        self.assertIsNot(a["changes"][0], ftx["changes"][0])
        self.assertIsNot(a["changes"][0], fc["changes"][0])

    def test_inputs_never_modified(self):
        ftx, fc, _ = finalized()
        snap = copy.deepcopy((ftx, fc))
        r = build(ftx, fc)
        r["changes"][0]["reason"] = "mutated"
        self.assertEqual((ftx, fc), snap)


class BuildRejectTests(unittest.TestCase):
    def test_invalid_transaction(self):
        ftx, fc, _ = finalized()
        for bad in (None, [], "x", dict(ftx, version="2"), dict(ftx, extra=1),
                    dict(ftx, transaction_id="tx_" + "0" * 16)):
            self.assertIsNone(build(bad, fc))
        self.assertEqual(reason(None, fc), "invalid_transaction")

    def test_pending_transaction_rejected(self):
        ftx, fc, _ = finalized()
        pending = begin(change_set(("modify_file", "formatter/style.py"),
                                   ("update_capability", "tone")))["transaction"]
        self.assertEqual(pending["status"], "pending")
        self.assertIsNone(build(pending, fc))
        self.assertEqual(reason(pending, fc), "transaction_not_finalized")

    def test_invalid_finalized_commit(self):
        ftx, fc, _ = finalized()
        for bad in (None, {}, [], dict(fc, extra=1), dict(fc, executed=True),
                    dict(fc, execution_allowed=True), dict(fc, version="2")):
            self.assertIsNone(build(ftx, bad))
        self.assertEqual(reason(ftx, None), "invalid_finalized_commit")

    def test_ready_to_commit_not_accepted_as_finalized(self):
        ftx, fc, _ = finalized()
        self.assertIsNone(build(ftx, dict(fc, status="ready_to_commit")))
        self.assertIsNone(build(ftx, dict(fc, status="pending")))

    def test_status_mismatch_rejected(self):
        ftx, _, _ = finalized(True)
        _, other, _ = finalized(False)
        self.assertIsNone(build(ftx, other))
        self.assertEqual(reason(ftx, other), "status_mismatch")

    def test_forged_status_rejected(self):
        ftx, fc, _ = finalized(True)
        self.assertIsNone(build(ftx, dict(fc, status="rolled_back")))

    def test_transaction_id_mismatch_rejected(self):
        ftx, fc, _ = finalized()
        other = finalize_tx(begin(change_set(("modify_file", "formatter/response.py")))
                            ["transaction"], True)["transaction"]
        self.assertIsNone(build(other, fc))
        self.assertEqual(reason(other, fc), "transaction_id_mismatch")
        self.assertIsNone(build(ftx, dict(fc, transaction_id="tx_" + "a" * 16)))

    def test_proposal_id_mismatch_rejected(self):
        ftx, fc, _ = finalized()
        self.assertIsNone(build(ftx, dict(fc, proposal_id="plan_other")))

    def test_altered_changes_rejected(self):
        ftx, fc, _ = finalized()
        bad = copy.deepcopy(fc)
        bad["changes"][0]["reason"] = "tampered"
        self.assertIsNone(build(ftx, bad))

    def test_reordered_changes_rejected(self):
        ftx, fc, _ = finalized()
        bad = copy.deepcopy(fc)
        bad["changes"].reverse()
        self.assertIsNone(build(ftx, bad))
        bad_tx = copy.deepcopy(ftx)
        bad_tx["changes"].reverse()
        self.assertIsNone(build(bad_tx, fc))

    def test_never_raises_on_garbage(self):
        for args in ((), (1, 2), (object(), object()), ({}, {}), (None, None)):
            self.assertIsNone(build(*args))


class ValidateRecordTests(unittest.TestCase):
    def setUp(self):
        self.rec = build(*finalized(True)[:2])

    def errors(self, record):
        r = validate(record)
        self.assertEqual(list(r), VALIDATE_KEYS)
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)
        return [e["code"] for e in r["errors"]]

    def test_missing_and_non_dict(self):
        self.assertEqual(self.errors(None), ["missing_commit"])
        for bad in ([], "x", 1):
            self.assertEqual(self.errors(bad), ["commit_not_dict"])

    def test_unexpected_and_missing_fields(self):
        self.assertIn("unexpected_field", self.errors(dict(self.rec, extra=1)))
        for key in KEYS:
            r = dict(self.rec)
            del r[key]
            self.assertIn("missing_field", self.errors(r))

    def test_field_order_is_exact(self):
        shuffled = {k: self.rec[k] for k in reversed(KEYS)}
        self.assertEqual(self.errors(shuffled), ["invalid_field_order"])

    def test_status_must_be_final(self):
        self.assertEqual(self.errors(dict(self.rec, status="rolled_back")), [])
        for bad in ("ready_to_commit", "pending", "COMMITTED", None, 1):
            self.assertEqual(self.errors(dict(self.rec, status=bad)), ["invalid_status"])

    def test_flags_must_be_exactly_false(self):
        for key in ("execution_allowed", "executed"):
            for bad in (True, 0, None, "False"):
                self.assertEqual(self.errors(dict(self.rec, **{key: bad})), ["invalid_" + key])

    def test_identity_and_changes_consistency(self):
        self.assertEqual(self.errors(dict(self.rec, transaction_id="tx_" + "f" * 16)),
                         ["transaction_id_mismatch"])
        self.assertEqual(self.errors(dict(self.rec, proposal_id="plan_other")),
                         ["transaction_id_mismatch"])
        r = copy.deepcopy(self.rec)
        r["changes"][0]["reason"] = "tampered"
        self.assertEqual(self.errors(r), ["transaction_id_mismatch"])
        self.assertTrue(self.errors(dict(self.rec, changes=[])))
        self.assertEqual(self.errors(dict(self.rec, version=1)), ["invalid_version"])

    def test_validation_does_not_repair_or_modify(self):
        bad = dict(self.rec, status="pending")
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
        with open(os.path.join(ROOT, "upgrade", "upgrade_audit.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        banned = {"os", "sys", "subprocess", "socket", "urllib", "http", "requests", "shutil",
                  "pathlib", "importlib", "builtins", "pickle", "sqlite3", "core", "memory", "ael"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], banned)
            elif isinstance(node, ast.ImportFrom):
                self.assertTrue(node.module.startswith("upgrade."), node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__"})

    def test_public_api(self):
        public = sorted(n for n in dir(ua) if not n.startswith("_") and callable(getattr(ua, n))
                        and getattr(getattr(ua, n), "__module__", "") == ua.__name__)
        self.assertEqual(public, ["build_upgrade_audit_record", "validate_upgrade_audit_record"])


if __name__ == "__main__":
    unittest.main()
