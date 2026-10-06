"""
Prompt 855 - sandboxed change set focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_change_set_prompt855 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade import change_set as cs
from upgrade.change_set import build_change_set as build
from upgrade.change_set import validate_change_set as validate
from upgrade.upgrade_policy import evaluate_upgrade_policy as evaluate
from tests.test_upgrade_policy_prompt854 import make_proposal, make_state

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "change_set", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
SET_KEYS = ["version", "proposal_id", "changes", "execution_allowed"]
CHANGE_KEYS = ["change_id", "action", "target", "reason"]


def codes(result):
    return [(e["code"], e["where"]) for e in result["errors"]]


def allowed_pair(**over):
    p = make_proposal(**over)
    return p, evaluate(p)


def make_set(**over):
    p, r = allowed_pair()
    s = build(p, r)["change_set"]
    s.update(over)
    return s


def check_shape(test, result, keys=BUILD_KEYS):
    test.assertEqual(list(result), keys)
    test.assertIs(result["execution_allowed"], False)
    test.assertIs(result["executed"], False)
    json.dumps(result)


class BuildTests(unittest.TestCase):
    def test_allowed_proposal_builds_valid_change_set(self):
        p, r = allowed_pair()
        out = build(p, r)
        check_shape(self, out)
        self.assertIs(out["valid"], True)
        self.assertEqual(out["errors"], [])
        s = out["change_set"]
        self.assertEqual(list(s), SET_KEYS)
        self.assertNotIn("executed", s)
        self.assertEqual((s["version"], s["proposal_id"]), ("1", p["plan_id"]))
        self.assertIs(s["execution_allowed"], False)
        self.assertIs(validate(s)["valid"], True)

    def test_changes_preserved_exactly_and_in_order(self):
        p = make_proposal(scope=["tone", "formatter/style.py", "formatter/response.py"])
        s = build(p, evaluate(p))["change_set"]
        self.assertEqual(s["changes"], p["changes"])
        self.assertEqual([c["target"] for c in s["changes"]],
                         ["tone", "formatter/style.py", "formatter/response.py"])
        for c in s["changes"]:
            self.assertEqual(list(c), CHANGE_KEYS)

    def test_changes_are_fresh_copies(self):
        p, r = allowed_pair()
        s = build(p, r)["change_set"]
        self.assertIsNot(s["changes"], p["changes"])
        for a, b in zip(s["changes"], p["changes"]):
            self.assertIsNot(a, b)
        s["changes"][0]["target"] = "changed"
        self.assertNotEqual(p["changes"][0]["target"], "changed")

    def test_no_changes_added_or_removed(self):
        p, r = allowed_pair()
        self.assertEqual(len(build(p, r)["change_set"]["changes"]), len(p["changes"]))
        self.assertNotIn("affected_files", build(p, r)["change_set"])

    def test_accepts_policy_evaluated_with_project_state(self):
        p = make_proposal()
        self.assertIs(build(p, evaluate(p, make_state()))["valid"], True)

    def test_deterministic_and_inputs_untouched(self):
        p, r = allowed_pair()
        before = copy.deepcopy((p, r))
        a, b = build(p, r), build(p, r)
        self.assertEqual(a, b)
        self.assertIsNot(a["change_set"], b["change_set"])
        self.assertEqual((p, r), before)

    def test_denied_policy(self):
        p = make_proposal(affected_files=[])
        denied = evaluate(p)
        self.assertEqual(denied["status"], "policy_denied")
        out = build(p, denied)
        check_shape(self, out)
        self.assertEqual((out["valid"], out["change_set"]), (False, None))
        self.assertEqual(codes(out), [("policy_not_allowed", "policy_result")])
        empty = make_proposal(changes=[])
        self.assertEqual(codes(build(empty, evaluate(empty))),
                         [("invalid_change_proposal", "change_proposal")])

    def test_invalid_proposal(self):
        for bad in (None, "x", [], make_proposal(version="2"), make_proposal(changes=[{}]),
                    make_proposal(execution_allowed=True)):
            out = build(bad, evaluate(make_proposal()))
            check_shape(self, out)
            self.assertEqual(codes(out), [("invalid_change_proposal", "change_proposal")], repr(bad))
            self.assertIsNone(out["change_set"])

    def test_invalid_policy_result(self):
        p, r = allowed_pair()
        for bad in (None, "x", {}, dict(r, allowed="yes"), dict(r, execution_allowed=True),
                    dict(r, executed=True), dict(r, reason="trusted"), dict(r, status="ok")):
            out = build(p, bad)
            self.assertEqual(codes(out), [("invalid_policy_result", "policy_result")], repr(bad))
        self.assertEqual(codes(build(None, None)),
                         [("invalid_change_proposal", "change_proposal"),
                          ("invalid_policy_result", "policy_result")])
        self.assertEqual(codes(build()), codes(build(None, None)))

    def test_policy_proposal_mismatch(self):
        p, r = allowed_pair()
        other = make_proposal(scope=["tone"])
        self.assertEqual(codes(build(other, r)), [("policy_proposal_mismatch", "policy_result")])
        forged = dict(r, proposal_id="plan_ffffffffffffffff")
        self.assertEqual(codes(build(p, forged)), [("policy_proposal_mismatch", "policy_result")])

    def test_forged_allowed_for_denied_proposal_is_refused(self):
        p = make_proposal(affected_files=[])
        forged = {"version": "1", "status": "allowed", "allowed": True,
                  "reason": "proposal_is_valid_and_represents_its_own_targets",
                  "proposal_id": p["plan_id"], "execution_allowed": False, "executed": False}
        self.assertIs(validate_policy(forged), True)
        self.assertEqual(codes(build(p, forged)), [("policy_proposal_mismatch", "policy_result")])

    def test_unsupported_action_fails_deterministically(self):
        p = make_proposal()
        p["changes"][0]["action"] = "delete_everything"
        out = build(p, evaluate(p))
        self.assertEqual(codes(out), [("unsupported_change_action", "changes[0].action")])
        self.assertIsNone(out["change_set"])

    def test_oversized_input(self):
        big = make_proposal(changes=[{}] * 500)
        out = build(big, evaluate(big))
        self.assertLessEqual(len(out["errors"]), 16)
        self.assertLessEqual(len(json.dumps(out)), 600)

    def test_never_raises(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

        for a, b in ((Boom(), Boom()), (object(), object()), (make_proposal(), Boom())):
            out = build(a, b)
            check_shape(self, out)
            self.assertIs(out["valid"], False)


def validate_policy(result):
    from upgrade.upgrade_policy import validate_upgrade_policy_result
    return validate_upgrade_policy_result(result)["valid"]


class ValidateTests(unittest.TestCase):
    def test_valid(self):
        v = validate(make_set())
        check_shape(self, v, VALIDATE_KEYS)
        self.assertEqual((v["valid"], v["errors"]), (True, []))

    def test_missing_and_non_dict(self):
        self.assertEqual(codes(validate(None)), [("missing_change_set", "change_set")])
        self.assertEqual(codes(validate()), [("missing_change_set", "change_set")])
        for bad in ("x", [], 1, (), True):
            self.assertEqual(codes(validate(bad)), [("change_set_not_dict", "change_set")])

    def test_missing_unexpected_too_many_fields(self):
        s = make_set()
        for key in SET_KEYS:
            c = dict(s)
            del c[key]
            self.assertEqual(codes(validate(c)), [("missing_field", key)])
        self.assertEqual(codes(validate(dict(s, extra=1))), [("unexpected_field", "extra")])
        self.assertEqual(codes(validate({"k%d" % i: i for i in range(17)})),
                         [("too_many_fields", "change_set")])

    def test_version_and_proposal_id(self):
        for bad in ("2", 1, None, "", " 1"):
            self.assertEqual(codes(validate(make_set(version=bad))), [("invalid_version", "version")])
        for bad in (None, "", " p", "x" * 65, 1, "a\nb"):
            self.assertEqual(codes(validate(make_set(proposal_id=bad))),
                             [("invalid_proposal_id", "proposal_id")], repr(bad))

    def test_changes_container(self):
        self.assertEqual(codes(validate(make_set(changes="x"))), [("invalid_changes", "changes")])
        self.assertEqual(codes(validate(make_set(changes=[]))), [("empty_changes", "changes")])
        self.assertEqual(codes(validate(make_set(changes=[{}] * 17))), [("too_many_items", "changes")])

    def test_malformed_change(self):
        for bad in (None, "x", [], 1):
            self.assertEqual(codes(validate(make_set(changes=[bad]))), [("invalid_change", "changes[0]")])
        c = make_set()["changes"][0]
        self.assertIn(("missing_change_field", "changes[0].reason"),
                      codes(validate(make_set(changes=[{k: v for k, v in c.items() if k != "reason"}]))))
        self.assertIn(("unexpected_change_field", "changes[0].extra"),
                      codes(validate(make_set(changes=[dict(c, extra=1)]))))

    def test_malformed_target_and_reason(self):
        c = make_set()["changes"][0]
        for field in ("change_id", "target", "reason"):
            for bad in ("", " x", "x ", None, 1, "a\x00b", "x" * 201):
                self.assertIn(("invalid_change_" + field, "changes[0].%s" % field),
                              codes(validate(make_set(changes=[dict(c, **{field: bad})]))), repr(bad))

    def test_duplicate_change_id(self):
        c = make_set()["changes"][0]
        two = [dict(c), dict(c, target="tone")]
        self.assertEqual(codes(validate(make_set(changes=two))),
                         [("duplicate_change_id", "changes[1].change_id")])

    def test_invalid_actions(self):
        c = make_set()["changes"][0]
        self.assertEqual(codes(validate(make_set(changes=[dict(c, action="run_shell")]))),
                         [("unsupported_change_action", "changes[0].action")])
        for bad in ("", None, 1):
            self.assertEqual(codes(validate(make_set(changes=[dict(c, action=bad)]))),
                             [("invalid_change_action", "changes[0].action")])
        for ok in ("modify_file", "update_capability"):
            self.assertIs(validate(make_set(changes=[dict(c, action=ok)]))["valid"], True)

    def test_execution_attempts_rejected(self):
        for bad in (True, 1, 0, "False", None, [], 0.0):
            self.assertEqual(codes(validate(make_set(execution_allowed=bad))),
                             [("invalid_execution_allowed", "execution_allowed")], repr(bad))
        self.assertEqual(codes(validate(dict(make_set(), executed=True))),
                         [("unexpected_field", "executed")])

    def test_results_never_allow_or_report_execution(self):
        p, r = allowed_pair()
        for out in (build(p, r), build(None, None), validate(make_set()), validate(None),
                    validate(make_set(execution_allowed=True))):
            self.assertIs(out["execution_allowed"], False)
            self.assertIs(out["executed"], False)

    def test_bounded_and_fresh(self):
        bad = make_set(changes=[{"change_id": None}] * 16, version=2, proposal_id=3)
        v = validate(bad)
        self.assertLessEqual(len(v["errors"]), 16)
        self.assertEqual(v, validate(bad))
        self.assertIsNot(v["errors"], validate(bad)["errors"])


class BoundaryTests(unittest.TestCase):
    def test_imports_and_no_io(self):
        tree = ast.parse(inspect.getsource(cs))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                mods.add(n.module)
        self.assertEqual(mods, {"upgrade.change_proposal", "upgrade.upgrade_plan",
                                "upgrade.upgrade_policy", "upgrade.upgrade_request"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("open", "exec", "eval", "compile", "__import__", "input", "print"):
            self.assertNotIn(forbidden, names)

    def test_validators_reused_and_nothing_outside_upgrade_imports_it(self):
        from upgrade import change_proposal, upgrade_policy
        self.assertIs(cs.validate_change_proposal, change_proposal.validate_change_proposal)
        self.assertIs(cs.validate_upgrade_policy_result, upgrade_policy.validate_upgrade_policy_result)
        self.assertIs(cs.evaluate_upgrade_policy, upgrade_policy.evaluate_upgrade_policy)
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ("upgrade", "tests", "__pycache__")]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        self.assertNotIn("change_set", fh.read(), os.path.join(folder, name))
        self.assertEqual((len(change_proposal.FIELDS), len(upgrade_policy.FIELDS)), (7, 7))


if __name__ == "__main__":
    unittest.main()
