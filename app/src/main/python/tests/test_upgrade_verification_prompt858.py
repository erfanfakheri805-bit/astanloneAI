"""
Prompt 858 - upgrade sandbox verification focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_upgrade_verification_prompt858 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade import upgrade_verification as uv
from upgrade.upgrade_sandbox import apply_change_set_to_sandbox as apply_cs
from upgrade.upgrade_verification import validate_sandbox_verification as validate
from upgrade.upgrade_verification import verify_sandbox_result as verify
from tests.test_change_set_prompt855 import make_set
from tests.test_upgrade_policy_prompt854 import make_proposal
from tests.test_upgrade_sandbox_prompt857 import change_set, workspace
from upgrade.upgrade_policy import evaluate_upgrade_policy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RESULT_KEYS = ["valid", "status", "errors", "proposal_id", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]


def applied(cset=None):
    cset = cset or make_set()
    out = apply_cs(workspace(), cset)
    assert out["applied"], out["errors"]
    return out["workspace"], cset


def policy_for(cset):
    p = make_proposal()
    r = evaluate_upgrade_policy(p)
    assert r["proposal_id"] == cset["proposal_id"]
    return r


def codes(result):
    return [(e["code"], e["where"]) for e in result["errors"]]


def check_shape(test, result):
    test.assertEqual(list(result), RESULT_KEYS)
    test.assertIs(result["execution_allowed"], False)
    test.assertIs(result["executed"], False)
    json.dumps(result)
    test.assertEqual(validate(result)["errors"], [])


class VerifyValidTests(unittest.TestCase):
    def test_applied_change_set_is_valid(self):
        ws, cset = applied()
        r = verify(ws, cset)
        check_shape(self, r)
        self.assertEqual((r["valid"], r["status"], r["errors"]), (True, "valid", []))
        self.assertEqual(r["proposal_id"], cset["proposal_id"])

    def test_valid_with_matching_policy(self):
        ws, cset = applied()
        r = verify(ws, cset, policy_for(cset))
        check_shape(self, r)
        self.assertEqual(r["status"], "valid")

    def test_multiple_applied_sets_verify_independently(self):
        ws, first = applied(change_set(("modify_file", "formatter/style.py"), ("update_capability", "tone")))
        second = dict(change_set(("modify_file", "formatter/response.py")), proposal_id="plan_second")
        ws = apply_cs(ws, second)["workspace"]
        self.assertEqual(verify(ws, first)["status"], "valid")
        self.assertEqual(verify(ws, second)["status"], "valid")

    def test_deterministic_fresh_and_inputs_untouched(self):
        ws, cset = applied()
        pol = policy_for(cset)
        before = copy.deepcopy((ws, cset, pol))
        a, b = verify(ws, cset, pol), verify(ws, cset, pol)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["errors"], b["errors"])
        self.assertEqual((ws, cset, pol), before)

    def test_tampered_workspace_is_not_repaired(self):
        ws, cset = applied()
        ws["applied"][0]["changes"][0]["reason"] = "tampered"
        before = copy.deepcopy(ws)
        verify(ws, cset)
        self.assertEqual(ws, before)


class StatusTests(unittest.TestCase):
    def test_invalid_workspace(self):
        _, cset = applied()
        for bad in (None, "x", [], {}, dict(workspace(), version="2"), dict(workspace(), extra=1),
                    dict(workspace(), executed=True), dict(workspace(), applied="x")):
            r = verify(bad, cset)
            check_shape(self, r)
            self.assertEqual((r["valid"], r["status"]), (False, "invalid_workspace"), repr(bad))
            self.assertTrue(r["errors"])
            self.assertEqual(r["proposal_id"], cset["proposal_id"])

    def test_invalid_change_set(self):
        ws, _ = applied()
        for bad in (None, "x", {}, make_set(version="2"), make_set(changes=[]),
                    make_set(execution_allowed=True)):
            r = verify(ws, bad)
            check_shape(self, r)
            self.assertEqual((r["valid"], r["status"], r["proposal_id"]), (False, "invalid_change_set", None))
            self.assertEqual(codes(r), [("invalid_change_set", "change_set")])
        self.assertEqual(verify(None, None)["status"], "invalid_workspace")  # workspace checked first
        self.assertEqual(verify()["status"], "invalid_workspace")

    def test_invalid_policy(self):
        ws, cset = applied()
        pol = policy_for(cset)
        for bad in ({}, "x", dict(pol, allowed="yes"), dict(pol, execution_allowed=True), 5):
            r = verify(ws, cset, bad)
            check_shape(self, r)
            self.assertEqual((r["status"], codes(r)), ("invalid_policy", [("invalid_policy_result", "policy_result")]))

    def test_policy_denied_or_for_another_change_set(self):
        ws, cset = applied()
        denied = evaluate_upgrade_policy(make_proposal(affected_files=[]))
        r = verify(ws, cset, denied)
        self.assertEqual((r["status"], codes(r)), ("invalid_policy", [("policy_not_allowed", "policy_result")]))
        other = dict(policy_for(cset), proposal_id="plan_other")
        r = verify(ws, cset, other)
        self.assertEqual((r["status"], codes(r)), ("invalid_policy", [("policy_proposal_mismatch", "policy_result")]))

    def test_not_applied(self):
        r = verify(workspace(), make_set())
        check_shape(self, r)
        self.assertEqual((r["valid"], r["status"]), (False, "not_applied"))
        self.assertEqual(codes(r), [("change_set_not_applied", "workspace.applied")])
        ws, _ = applied(change_set(("modify_file", "formatter/style.py")))
        other = dict(make_set(), proposal_id="plan_never_applied")
        self.assertEqual(verify(ws, other)["status"], "not_applied")

    def test_stale_result_for_a_different_change_set(self):
        ws, cset = applied()
        newer = dict(cset, proposal_id="plan_newer")
        self.assertEqual(verify(ws, newer)["status"], "not_applied")


class TamperTests(unittest.TestCase):
    def tampered(self, mutate):
        ws, cset = applied()
        mutate(ws["applied"][0])
        r = verify(ws, cset)
        check_shape(self, r)
        self.assertEqual((r["valid"], r["status"]), (False, "tampered"))
        return r

    def test_field_level_tampering_codes(self):
        cases = (
            (lambda rec: rec["changes"][0].update(reason="other reason"),
             [("reason_changed", "changes[0].reason")]),
            (lambda rec: rec["changes"][0].update(target="formatter/style.py"),
             [("target_changed", "changes[0].target")]),
            (lambda rec: rec["changes"][0].update(target="evil.py"),
             [("unknown_target", "workspace.applied[0].changes[0].target")]),
            (lambda rec: rec["changes"][0].update(action="run_shell"),
             [("unsupported_change_action", "workspace.applied[0].changes[0].action")]),
            (lambda rec: rec["changes"][0].update(change_id="change_9"),
             [("change_id_changed", "changes[0].change_id")]),
            (lambda rec: rec["changes"].pop(), [("changes_length_mismatch", "changes")]),
            (lambda rec: rec["changes"].append(dict(rec["changes"][0], change_id="change_3",
                                                    target="formatter/style.py")),
             [("changes_length_mismatch", "changes")]),
        )
        for mutate, expected in cases:
            self.assertEqual(codes(self.tampered(mutate)), expected)

    def test_changed_action(self):
        r = self.tampered(lambda rec: rec["changes"][1].update(action="modify_file"))
        self.assertEqual(r["status"], "tampered")
        self.assertIn(("unknown_target", "workspace.applied[0].changes[1].target"), codes(r))

    def test_reordered_changes(self):
        r = self.tampered(lambda rec: rec["changes"].reverse())
        self.assertEqual(r["status"], "tampered")
        self.assertIn(("change_id_changed", "changes[0].change_id"), codes(r))

    def test_mismatched_proposal_identity(self):
        ws, cset = applied()
        ws["applied"][0]["proposal_id"] = "plan_forged"
        r = verify(ws, cset)
        self.assertEqual((r["status"], codes(r)), ("not_applied", [("change_set_not_applied", "workspace.applied")]))

    def test_duplicate_application_records(self):
        ws, cset = applied()
        ws["applied"].append(copy.deepcopy(ws["applied"][0]))
        r = verify(ws, cset)
        check_shape(self, r)
        self.assertEqual((r["status"], codes(r)),
                         ("tampered", [("duplicate_proposal_id", "workspace.applied[1].proposal_id")]))

    def test_changed_change_set_after_apply(self):
        ws, cset = applied()
        cset["changes"][0]["reason"] = "edited after apply"
        r = verify(ws, cset)
        self.assertEqual((r["status"], codes(r)), ("tampered", [("reason_changed", "changes[0].reason")]))

    def test_errors_are_bounded(self):
        ws, cset = applied(change_set(*([("modify_file", "formatter/style.py")] * 1)))
        for change in ws["applied"][0]["changes"]:
            for field in ("change_id", "action", "target", "reason"):
                change[field] = change[field] + "x"
        r = verify(ws, cset)
        self.assertEqual(r["status"], "tampered")
        self.assertLessEqual(len(r["errors"]), 16)


class ValidateResultTests(unittest.TestCase):
    def test_all_statuses_produce_valid_results(self):
        ws, cset = applied()
        bad = copy.deepcopy(ws)
        bad["applied"][0]["changes"][0]["reason"] = "t"
        for r in (verify(ws, cset), verify(None, cset), verify(ws, None), verify(ws, cset, {}),
                  verify(workspace(), cset), verify(bad, cset)):
            v = validate(r)
            self.assertEqual(list(v), VALIDATE_KEYS)
            self.assertEqual((v["valid"], v["errors"]), (True, []), r["status"])
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)

    def test_verification_error_status_is_valid(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

        r = verify(Boom(), Boom())
        self.assertIn(r["status"], ("invalid_workspace", "verification_error"))
        explicit = {"valid": False, "status": "verification_error",
                    "errors": [{"code": "validation_error", "where": "verification"}],
                    "proposal_id": None, "execution_allowed": False, "executed": False}
        self.assertEqual(validate(explicit)["errors"], [])

    def test_missing_and_non_dict(self):
        self.assertEqual(codes(validate(None)), [("missing_result", "result")])
        self.assertEqual(codes(validate()), [("missing_result", "result")])
        for bad in ("x", [], 1, ()):
            self.assertEqual(codes(validate(bad)), [("result_not_dict", "result")])

    def test_missing_unexpected_too_many_fields(self):
        r = verify(*applied())
        for key in RESULT_KEYS:
            c = dict(r)
            del c[key]
            self.assertEqual(codes(validate(c)), [("missing_field", key)])
        self.assertEqual(codes(validate(dict(r, extra=1))), [("unexpected_field", "extra")])
        self.assertEqual(codes(validate({"k%d" % i: i for i in range(17)})), [("too_many_fields", "result")])

    def test_status_valid_and_errors_consistency(self):
        r = verify(*applied())
        for bad in ("ok", "VALID", None, 1, ""):
            self.assertIn(("invalid_status", "status"), codes(validate(dict(r, status=bad))))
        for bad in (0, 1, None, "True"):
            self.assertIn(("invalid_valid", "valid"), codes(validate(dict(r, valid=bad))))
        self.assertIn(("invalid_valid", "valid"), codes(validate(dict(r, valid=False))))
        failed = verify(workspace(), make_set())
        self.assertIn(("invalid_valid", "valid"), codes(validate(dict(failed, valid=True))))
        self.assertIn(("invalid_errors", "errors"), codes(validate(dict(failed, errors=[]))))
        self.assertIn(("invalid_errors", "errors"),
                      codes(validate(dict(r, errors=[{"code": "x", "where": "y"}]))))

    def test_malformed_errors(self):
        failed = verify(workspace(), make_set())
        for bad in ("x", None, {}, [None], [{"code": "x"}], [{"code": "x", "where": "y", "z": 1}],
                    [{"code": "", "where": "y"}], [{"code": 1, "where": "y"}],
                    [{"where": "y", "code": "x"}]):
            self.assertFalse(validate(dict(failed, errors=bad))["valid"], repr(bad))
        self.assertEqual(codes(validate(dict(failed, errors=[{"code": "x", "where": "y"}] * 17))),
                         [("too_many_items", "errors")])

    def test_proposal_id_rules(self):
        r = verify(*applied())
        for bad in (None, "", " p", "x" * 65, 1):
            self.assertIn(("invalid_proposal_id", "proposal_id"), codes(validate(dict(r, proposal_id=bad))))
        failed = verify(workspace(), make_set())
        self.assertEqual(validate(dict(failed, proposal_id=None))["errors"], [])
        self.assertIn(("invalid_proposal_id", "proposal_id"), codes(validate(dict(failed, proposal_id=7))))

    def test_execution_flags_must_be_exactly_false(self):
        r = verify(*applied())
        for bad in (True, 1, 0, "False", None, [], 0.0):
            self.assertEqual(codes(validate(dict(r, execution_allowed=bad))),
                             [("invalid_execution_allowed", "execution_allowed")], repr(bad))
            self.assertEqual(codes(validate(dict(r, executed=bad))),
                             [("invalid_executed", "executed")], repr(bad))

    def test_validation_bounded_fresh_no_repair(self):
        bad = {"valid": 1, "status": 2, "errors": 3, "proposal_id": 4, "execution_allowed": 5, "executed": 6}
        before = copy.deepcopy(bad)
        v = validate(bad)
        self.assertEqual(bad, before)
        self.assertLessEqual(len(v["errors"]), 16)
        self.assertEqual(v, validate(bad))
        self.assertIsNot(v["errors"], validate(bad)["errors"])

    def test_results_never_allow_or_report_execution(self):
        ws, cset = applied()
        for r in (verify(ws, cset), verify(None, None), verify(workspace(), cset), validate(None)):
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)


class BoundaryTests(unittest.TestCase):
    def test_imports_and_no_io(self):
        tree = ast.parse(inspect.getsource(uv))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                mods.add(n.module)
        self.assertEqual(mods, {"upgrade.change_set", "upgrade.upgrade_policy",
                                "upgrade.upgrade_request", "upgrade.upgrade_sandbox"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("open", "exec", "eval", "compile", "__import__", "input", "print"):
            self.assertNotIn(forbidden, names)

    def test_validators_reused_and_nothing_outside_upgrade_imports_it(self):
        from upgrade import change_set, upgrade_policy, upgrade_sandbox
        self.assertIs(uv.validate_change_set, change_set.validate_change_set)
        self.assertIs(uv.validate_upgrade_policy_result, upgrade_policy.validate_upgrade_policy_result)
        self.assertIs(uv.validate_sandbox_workspace, upgrade_sandbox.validate_sandbox_workspace)
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ("upgrade", "tests", "__pycache__")]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        self.assertNotIn("upgrade_verification", fh.read(), os.path.join(folder, name))


if __name__ == "__main__":
    unittest.main()
