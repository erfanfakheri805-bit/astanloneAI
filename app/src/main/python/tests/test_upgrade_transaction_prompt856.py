"""
Prompt 856 - upgrade transaction boundary focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_upgrade_transaction_prompt856 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade import upgrade_transaction as ut
from upgrade.upgrade_transaction import begin_upgrade_transaction as begin
from upgrade.upgrade_transaction import derive_transaction_id
from upgrade.upgrade_transaction import finalize_upgrade_transaction as finalize
from upgrade.upgrade_transaction import validate_upgrade_transaction as validate
from tests.test_change_set_prompt855 import make_set

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RESULT_KEYS = ["valid", "errors", "transaction", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
TX_KEYS = ["version", "transaction_id", "change_set_id", "status", "changes",
           "execution_allowed", "executed"]


def pending(change_set=None):
    out = begin(change_set or make_set())
    assert out["valid"], out["errors"]
    return out["transaction"]


def codes(result):
    return [(e["code"], e["where"]) for e in result["errors"]]


def check_shape(test, result, keys=RESULT_KEYS):
    test.assertEqual(list(result), keys)
    test.assertIs(result["execution_allowed"], False)
    test.assertIs(result["executed"], False)
    json.dumps(result)


class BeginTests(unittest.TestCase):
    def test_creates_pending_transaction(self):
        cset = make_set()
        out = begin(cset)
        check_shape(self, out)
        self.assertEqual((out["valid"], out["errors"]), (True, []))
        tx = out["transaction"]
        self.assertEqual(list(tx), TX_KEYS)
        self.assertEqual((tx["version"], tx["status"]), ("1", "pending"))
        self.assertEqual(tx["change_set_id"], cset["proposal_id"])
        self.assertEqual(tx["changes"], cset["changes"])
        self.assertIs(tx["execution_allowed"], False)
        self.assertIs(tx["executed"], False)
        self.assertIs(validate(tx)["valid"], True)

    def test_transaction_id_is_deterministic(self):
        a, b = pending(), pending()
        self.assertEqual(a, b)
        self.assertRegex(a["transaction_id"], r"^tx_[0-9a-f]{16}$")
        self.assertEqual(a["transaction_id"], derive_transaction_id(make_set()))

    def test_transaction_id_depends_only_on_change_set(self):
        base = make_set()
        other = make_set(proposal_id="plan_other")
        self.assertNotEqual(derive_transaction_id(base), derive_transaction_id(other))
        changed = copy.deepcopy(base)
        changed["changes"][0]["reason"] = "different reason"
        self.assertNotEqual(derive_transaction_id(base), derive_transaction_id(changed))
        reordered = dict(reversed(list(base.items())))
        self.assertEqual(derive_transaction_id(base), derive_transaction_id(reordered))

    def test_changes_are_fresh_copies_and_input_untouched(self):
        cset = make_set()
        before = copy.deepcopy(cset)
        tx = begin(cset)["transaction"]
        self.assertEqual(cset, before)
        self.assertIsNot(tx["changes"], cset["changes"])
        for a, b in zip(tx["changes"], cset["changes"]):
            self.assertIsNot(a, b)
        tx["changes"][0]["target"] = "changed"
        self.assertEqual(cset, before)

    def test_multiple_changes_keep_order(self):
        from tests.test_upgrade_policy_prompt854 import make_proposal
        from upgrade.change_set import build_change_set
        from upgrade.upgrade_policy import evaluate_upgrade_policy
        p = make_proposal(scope=["tone", "formatter/style.py", "formatter/response.py"])
        cset = build_change_set(p, evaluate_upgrade_policy(p))["change_set"]
        tx = begin(cset)["transaction"]
        self.assertEqual([c["target"] for c in tx["changes"]],
                         ["tone", "formatter/style.py", "formatter/response.py"])

    def test_invalid_change_set(self):
        for bad in (None, "x", [], {}, make_set(version="2"), make_set(changes=[]),
                    make_set(execution_allowed=True), make_set(proposal_id=""),
                    make_set(changes=[dict(make_set()["changes"][0], action="run_shell")])):
            out = begin(bad)
            check_shape(self, out)
            self.assertEqual((out["valid"], out["transaction"]), (False, None))
            self.assertEqual(codes(out), [("invalid_change_set", "change_set")], repr(bad))
        self.assertEqual(codes(begin()), [("invalid_change_set", "change_set")])

    def test_oversized_change_set_is_bounded(self):
        out = begin(make_set(changes=[{}] * 500))
        self.assertEqual(codes(out), [("invalid_change_set", "change_set")])

    def test_never_raises(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

        for bad in (Boom(), object()):
            out = begin(bad)
            check_shape(self, out)
            self.assertIs(out["valid"], False)


class FinalizeTests(unittest.TestCase):
    def test_commit(self):
        tx = pending()
        out = finalize(tx, True)
        check_shape(self, out)
        self.assertIs(out["valid"], True)
        done = out["transaction"]
        self.assertEqual(done["status"], "committed")
        self.assertIs(done["executed"], False)
        self.assertIs(done["execution_allowed"], False)
        self.assertIs(validate(done)["valid"], True)

    def test_rollback_and_default_is_rollback(self):
        tx = pending()
        self.assertEqual(finalize(tx, False)["transaction"]["status"], "rolled_back")
        self.assertEqual(finalize(tx)["transaction"]["status"], "rolled_back")
        self.assertIs(validate(finalize(tx)["transaction"])["valid"], True)

    def test_identity_and_changes_preserved(self):
        tx = pending()
        for flag in (True, False):
            done = finalize(tx, flag)["transaction"]
            for key in ("version", "transaction_id", "change_set_id", "changes"):
                self.assertEqual(done[key], tx[key])
            self.assertIsNot(done["changes"], tx["changes"])
            self.assertEqual(list(done), TX_KEYS)

    def test_input_never_modified(self):
        tx = pending()
        before = copy.deepcopy(tx)
        finalize(tx, True)
        finalize(tx, False)
        finalize(dict(tx, status="committed"), True)
        self.assertEqual(tx, before)
        self.assertEqual(tx["status"], "pending")

    def test_already_finalized_is_never_changed_again(self):
        for first in (True, False):
            done = finalize(pending(), first)["transaction"]
            before = copy.deepcopy(done)
            for second in (True, False):
                out = finalize(done, second)
                check_shape(self, out)
                self.assertEqual((out["valid"], out["transaction"]), (False, None))
                self.assertEqual(codes(out), [("transaction_already_finalized", "status")])
            self.assertEqual(done, before)

    def test_invalid_success_values(self):
        tx = pending()
        for bad in (1, 0, "True", None, [], 1.0):
            out = finalize(tx, bad)
            self.assertEqual(codes(out), [("invalid_success", "success")], repr(bad))
            self.assertIsNone(out["transaction"])

    def test_invalid_transaction(self):
        for bad in (None, "x", [], {}, dict(pending(), status="running"),
                    dict(pending(), executed=True)):
            out = finalize(bad, True)
            check_shape(self, out)
            self.assertEqual(codes(out), [("invalid_transaction", "transaction")], repr(bad))
        self.assertEqual(codes(finalize()), [("invalid_transaction", "transaction")])
        self.assertEqual(codes(finalize(None, 1)),
                         [("invalid_transaction", "transaction"), ("invalid_success", "success")])

    def test_cannot_finalize_to_arbitrary_status(self):
        out = finalize(dict(pending(), status="committed"), False)
        self.assertEqual(codes(out), [("transaction_already_finalized", "status")])

    def test_results_never_allow_or_report_execution(self):
        tx = pending()
        for out in (begin(make_set()), begin(None), finalize(tx, True), finalize(tx, False),
                    finalize(None), validate(tx), validate(None)):
            self.assertIs(out["execution_allowed"], False)
            self.assertIs(out["executed"], False)


class ValidateTests(unittest.TestCase):
    def test_valid_in_every_status(self):
        tx = pending()
        for status in ut.STATUSES:
            t = dict(tx, status=status)
            v = validate(t)
            check_shape(self, v, VALIDATE_KEYS)
            self.assertEqual((v["valid"], v["errors"]), (True, []), status)

    def test_missing_and_non_dict(self):
        self.assertEqual(codes(validate(None)), [("missing_transaction", "transaction")])
        self.assertEqual(codes(validate()), [("missing_transaction", "transaction")])
        for bad in ("x", [], 1, (), True):
            self.assertEqual(codes(validate(bad)), [("transaction_not_dict", "transaction")])

    def test_missing_unexpected_too_many_fields(self):
        tx = pending()
        for key in TX_KEYS:
            c = dict(tx)
            del c[key]
            self.assertEqual(codes(validate(c)), [("missing_field", key)])
        self.assertEqual(codes(validate(dict(tx, extra=1))), [("unexpected_field", "extra")])
        self.assertEqual(codes(validate({"k%d" % i: i for i in range(17)})),
                         [("too_many_fields", "transaction")])

    def test_version_status_and_ids(self):
        tx = pending()
        for bad in ("2", 1, None, ""):
            self.assertEqual(codes(validate(dict(tx, version=bad))), [("invalid_version", "version")])
        for bad in ("done", "PENDING", "", None, 1, ["pending"]):
            self.assertEqual(codes(validate(dict(tx, status=bad))), [("invalid_status", "status")])
        for field in ("transaction_id", "change_set_id"):
            for bad in (None, "", " x", "x" * 65, 1, "a\nb"):
                self.assertEqual(codes(validate(dict(tx, **{field: bad}))),
                                 [("invalid_" + field, field)], repr(bad))

    def test_mismatched_change_set_identity(self):
        tx = pending()
        self.assertEqual(codes(validate(dict(tx, change_set_id="plan_other"))),
                         [("transaction_id_mismatch", "transaction_id")])
        self.assertEqual(codes(validate(dict(tx, transaction_id="tx_0000000000000000"))),
                         [("transaction_id_mismatch", "transaction_id")])
        changed = copy.deepcopy(tx)
        changed["changes"][0]["reason"] = "tampered"
        self.assertEqual(codes(validate(changed)), [("transaction_id_mismatch", "transaction_id")])

    def test_malformed_changes(self):
        tx = pending()
        c = tx["changes"][0]
        self.assertEqual(codes(validate(dict(tx, changes="x"))), [("invalid_changes", "changes")])
        self.assertEqual(codes(validate(dict(tx, changes=[]))), [("empty_changes", "changes")])
        self.assertEqual(codes(validate(dict(tx, changes=[{}] * 17))), [("too_many_items", "changes")])
        self.assertEqual(codes(validate(dict(tx, changes=[None]))), [("invalid_change", "changes[0]")])
        self.assertEqual(codes(validate(dict(tx, changes=[c, dict(c)]))),
                         [("duplicate_change_id", "changes[1].change_id")])
        self.assertEqual(codes(validate(dict(tx, changes=[dict(c, action="run_shell")]))),
                         [("unsupported_change_action", "changes[0].action")])
        self.assertIn(("invalid_change_target", "changes[0].target"),
                      codes(validate(dict(tx, changes=[dict(c, target="")]))))

    def test_execution_permission_attempts(self):
        tx = pending()
        for bad in (True, 1, 0, "False", None, [], 0.0):
            self.assertEqual(codes(validate(dict(tx, execution_allowed=bad))),
                             [("invalid_execution_allowed", "execution_allowed")], repr(bad))
            self.assertEqual(codes(validate(dict(tx, executed=bad))),
                             [("invalid_executed", "executed")], repr(bad))

    def test_bounded_fresh_and_no_repair(self):
        bad = dict(pending(), version=2, transaction_id=3, change_set_id=4, status=5,
                   changes=[{"change_id": None}] * 16, execution_allowed=6, executed=7)
        before = copy.deepcopy(bad)
        v = validate(bad)
        self.assertEqual(bad, before)
        self.assertLessEqual(len(v["errors"]), 16)
        self.assertEqual(v, validate(bad))
        self.assertIsNot(v["errors"], validate(bad)["errors"])


class BoundaryTests(unittest.TestCase):
    def test_imports_and_no_io(self):
        tree = ast.parse(inspect.getsource(ut))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                mods.add(n.module)
        self.assertEqual(mods, {"hashlib", "json", "upgrade.change_proposal",
                                "upgrade.change_set", "upgrade.upgrade_request"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("open", "exec", "eval", "compile", "__import__", "input", "print"):
            self.assertNotIn(forbidden, names)

    def test_change_set_validation_reused_and_nothing_outside_upgrade_imports_it(self):
        from upgrade import change_set
        self.assertIs(ut.validate_change_set, change_set.validate_change_set)
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ("upgrade", "tests", "__pycache__")]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        self.assertNotIn("upgrade_transaction", fh.read(), os.path.join(folder, name))
        self.assertEqual(len(change_set.FIELDS), 4)


if __name__ == "__main__":
    unittest.main()
