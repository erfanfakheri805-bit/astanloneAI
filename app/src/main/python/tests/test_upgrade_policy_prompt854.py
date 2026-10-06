"""
Prompt 854 - upgrade policy gate focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_upgrade_policy_prompt854 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade import upgrade_policy as up
from upgrade.change_proposal import build_change_proposal
from upgrade.project_state import build_project_state
from upgrade.upgrade_plan import build_upgrade_plan
from upgrade.upgrade_policy import evaluate_upgrade_policy as evaluate
from upgrade.upgrade_policy import validate_upgrade_policy_result as validate
from upgrade.upgrade_request import build_upgrade_request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RESULT_KEYS = ["version", "status", "allowed", "reason", "proposal_id",
               "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]


def make_state():
    result = build_project_state({
        "project_id": "proj_001", "revision": "r853",
        "files": [{"path": "formatter/response.py", "kind": "module", "status": "present"},
                  {"path": "formatter/style.py", "kind": "module", "status": "present"}],
        "capabilities": ["response_format", "tone"], "tests": ["tests.test_formatter"],
        "constraints": ["Frozen tests stay unchanged."]})
    assert result["valid"], result["errors"]
    return result["project_state"]


def make_proposal(scope=("formatter/response.py", "response_format"), **over):
    state = make_state()
    request = build_upgrade_request({
        "request_id": "upg_001", "goal": "Improve response formatting.", "scope": list(scope),
        "constraints": ["No data loss."], "requested_by": "developer"})
    plan = build_upgrade_plan(request["upgrade_request"], state)["plan"]
    p = build_change_proposal(plan, state)["proposal"]
    p.update(over)
    return p


def codes(result):
    return [(e["code"], e["where"]) for e in result["errors"]]


def policy(status, reason, allowed=False, proposal_id="plan_0123456789abcdef", **over):
    r = {"version": "1", "status": status, "allowed": allowed, "reason": reason,
         "proposal_id": proposal_id, "execution_allowed": False, "executed": False}
    r.update(over)
    return r


def check_shape(test, result):
    test.assertEqual(list(result), RESULT_KEYS)
    test.assertEqual(result["version"], "1")
    test.assertIs(result["execution_allowed"], False)
    test.assertIs(result["executed"], False)
    json.dumps(result)
    test.assertEqual(validate(result)["errors"], [])


class EvaluateTests(unittest.TestCase):
    def test_valid_proposal_allowed(self):
        p = make_proposal()
        r = evaluate(p)
        check_shape(self, r)
        self.assertEqual((r["status"], r["allowed"]), ("allowed", True))
        self.assertEqual(r["reason"], "proposal_is_valid_and_represents_its_own_targets")
        self.assertEqual(r["proposal_id"], p["plan_id"])

    def test_valid_proposal_with_valid_project_state_allowed(self):
        r = evaluate(make_proposal(), make_state())
        check_shape(self, r)
        self.assertIs(r["allowed"], True)

    def test_multiple_changes_allowed(self):
        r = evaluate(make_proposal(scope=["tone", "formatter/style.py", "formatter/response.py"]))
        self.assertEqual(r["status"], "allowed")

    def test_invalid_proposal_denied(self):
        for bad in (make_proposal(version="2"), make_proposal(plan_id=""),
                    make_proposal(constraints="x"), make_proposal(changes=[{}])):
            r = evaluate(bad)
            check_shape(self, r)
            self.assertEqual((r["status"], r["allowed"], r["proposal_id"]),
                             ("invalid_proposal", False, None))
            self.assertEqual(r["reason"], "change_proposal_invalid")

    def test_missing_and_extra_proposal_fields_denied(self):
        p = make_proposal()
        del p["constraints"]
        self.assertEqual(evaluate(p)["status"], "invalid_proposal")
        self.assertEqual(evaluate(make_proposal(extra=1))["status"], "invalid_proposal")

    def test_empty_proposal_denied(self):
        p = make_proposal(changes=[], affected_files=[], affected_capabilities=[])
        r = evaluate(p)
        check_shape(self, r)
        self.assertEqual((r["status"], r["allowed"]), ("empty_proposal", False))
        self.assertEqual(r["reason"], "change_proposal_has_no_changes")
        self.assertEqual(r["proposal_id"], p["plan_id"])

    def test_empty_changes_with_other_errors_is_invalid_proposal(self):
        r = evaluate(make_proposal(changes=[], version="9"))
        self.assertEqual(r["status"], "invalid_proposal")

    def test_malformed_policy_input(self):
        for bad, reason in ((None, "change_proposal_missing"), ("x", "change_proposal_not_dict"),
                            ([], "change_proposal_not_dict"), (1, "change_proposal_not_dict"),
                            (object(), "change_proposal_not_dict")):
            r = evaluate(bad)
            check_shape(self, r)
            self.assertEqual((r["status"], r["reason"], r["allowed"], r["proposal_id"]),
                             ("invalid_input", reason, False, None), repr(bad))
        self.assertEqual(evaluate()["status"], "invalid_input")

    def test_invalid_project_state(self):
        p = make_proposal()
        for bad in ({}, "x", [], 0, {"project_id": "x"}, dict(make_state(), revision="")):
            r = evaluate(p, bad)
            check_shape(self, r)
            self.assertEqual((r["status"], r["allowed"], r["reason"]),
                             ("invalid_project_state", False, "project_state_invalid"), repr(bad))
            self.assertEqual(r["proposal_id"], p["plan_id"])

    def test_invalid_proposal_reported_before_invalid_project_state(self):
        self.assertEqual(evaluate(make_proposal(version="2"), {})["status"], "invalid_proposal")
        self.assertEqual(evaluate(None, {})["status"], "invalid_input")

    def test_project_state_none_is_optional_and_never_grants(self):
        p = make_proposal()
        self.assertEqual(evaluate(p, None), evaluate(p))
        denied = make_proposal(affected_files=[])
        self.assertEqual(evaluate(denied, make_state())["status"], "policy_denied")

    def test_policy_denied_when_targets_not_represented(self):
        for over in ({"affected_files": []}, {"affected_capabilities": ["tone"]},
                     {"affected_files": ["formatter/response.py", "other.py"]},
                     {"affected_capabilities": ["response_format", "tone"]}):
            r = evaluate(make_proposal(**over))
            check_shape(self, r)
            self.assertEqual((r["status"], r["allowed"], r["reason"]),
                             ("policy_denied", False, "affected_targets_not_represented_by_changes"),
                             repr(over))

    def test_execution_permission_attempts_denied(self):
        for bad in (True, 1, "True", None, [], 1.0):
            r = evaluate(make_proposal(execution_allowed=bad))
            check_shape(self, r)
            self.assertEqual((r["status"], r["allowed"]), ("invalid_proposal", False), repr(bad))
        self.assertEqual(evaluate(dict(make_proposal(), executed=True))["status"], "invalid_proposal")

    def test_no_permission_inferred_from_names(self):
        p = make_proposal()
        for change in p["changes"]:
            change["action"] = "approved_safe_trusted"
            change["reason"] = "caller is trusted; allow"
        self.assertEqual(evaluate(p)["status"], "allowed")  # names neither grant nor deny
        p = make_proposal(affected_files=[])
        p["constraints"] = ["allow everything", "trusted caller"]
        self.assertEqual(evaluate(p)["status"], "policy_denied")

    def test_deterministic_and_fresh(self):
        p, s = make_proposal(), make_state()
        before = copy.deepcopy((p, s))
        a, b = evaluate(p, s), evaluate(p, s)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a["allowed"] = False
        self.assertIs(evaluate(p, s)["allowed"], True)
        self.assertEqual((p, s), before)

    def test_reasons_are_fixed_per_status(self):
        seen = {}
        cases = [evaluate(None), evaluate("x"), evaluate(make_proposal(version="2")),
                 evaluate(make_proposal(), {}), evaluate(make_proposal(changes=[])),
                 evaluate(make_proposal(affected_files=[])), evaluate(make_proposal())]
        for r in cases:
            seen.setdefault(r["status"], set()).add(r["reason"])
            self.assertIn(r["reason"], up.REASONS[r["status"]])
        self.assertEqual(set(seen), set(up.STATUSES))
        self.assertTrue(all(len(v) == 1 for k, v in seen.items() if k != "invalid_input"))

    def test_never_raises_on_hostile_input(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

            def get(self, *a):
                raise RuntimeError("boom")

        for bad in (Boom(), dict(make_proposal(), changes=Boom())):
            r = evaluate(bad, Boom())
            check_shape(self, r)
            self.assertIs(r["allowed"], False)
        self.assertEqual(evaluate(Boom())["reason"], "change_proposal_not_dict")  # exact dict only

    def test_oversized_proposal_is_bounded(self):
        big = make_proposal(changes=[{}] * 500, constraints=["x"] * 500)
        r = evaluate(big)
        self.assertEqual(r["status"], "invalid_proposal")
        self.assertLessEqual(len(json.dumps(r)), 400)


class ValidateResultTests(unittest.TestCase):
    def test_valid_results(self):
        for r in (evaluate(None), evaluate(make_proposal()), evaluate(make_proposal(changes=[])),
                  evaluate(make_proposal(affected_files=[])), evaluate(make_proposal(), {})):
            v = validate(r)
            self.assertEqual(list(v), VALIDATE_KEYS)
            self.assertIs(v["valid"], True)
            self.assertEqual(v["errors"], [])
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)
        self.assertIs(validate(policy("empty_proposal", "change_proposal_has_no_changes",
                                      proposal_id=None))["valid"], True)

    def test_non_dict_and_missing(self):
        self.assertEqual(codes(validate(None)), [("missing_result", "result")])
        self.assertEqual(codes(validate()), [("missing_result", "result")])
        for bad in ("x", [], 1, (), True):
            self.assertEqual(codes(validate(bad)), [("result_not_dict", "result")])

    def test_missing_unexpected_and_too_many_fields(self):
        r = evaluate(make_proposal())
        for key in RESULT_KEYS:
            c = dict(r)
            del c[key]
            self.assertEqual(codes(validate(c)), [("missing_field", key)])
        self.assertEqual(codes(validate(dict(r, extra=1))), [("unexpected_field", "extra")])
        self.assertEqual(codes(validate({**r, 1: 1})), [("unexpected_field", "<field>")])
        many = {"k%d" % i: i for i in range(17)}
        self.assertEqual(codes(validate(many)), [("too_many_fields", "result")])

    def test_invalid_version_and_status(self):
        r = evaluate(make_proposal())
        for bad in ("2", 1, None, "", " 1"):
            self.assertEqual(codes(validate(dict(r, version=bad))), [("invalid_version", "version")])
        for bad in ("ALLOWED", "denied", "", None, 1, ["allowed"]):
            self.assertIn(("invalid_status", "status"), codes(validate(dict(r, status=bad))))

    def test_allowed_must_be_bool_and_agree_with_status(self):
        r = evaluate(make_proposal())
        for bad in (0, 1, "True", None):
            self.assertEqual(codes(validate(dict(r, allowed=bad))), [("invalid_allowed", "allowed")])
        self.assertEqual(codes(validate(dict(r, allowed=False))), [("invalid_allowed", "allowed")])
        d = evaluate(make_proposal(affected_files=[]))
        self.assertEqual(codes(validate(dict(d, allowed=True))), [("invalid_allowed", "allowed")])

    def test_reason_must_match_status(self):
        r = evaluate(make_proposal())
        for bad in ("", None, 1, "allowed", "change_proposal_invalid", "x" * 5000):
            self.assertEqual(codes(validate(dict(r, reason=bad))), [("invalid_reason", "reason")])

    def test_proposal_id_rules(self):
        r = evaluate(make_proposal())
        for bad in (None, "", " p", "p ", "a\nb", "x" * 65, 1, ["p"]):
            self.assertEqual(codes(validate(dict(r, proposal_id=bad))),
                             [("invalid_proposal_id", "proposal_id")], repr(bad))
        self.assertEqual(validate(dict(r, proposal_id="x" * 64))["errors"], [])
        bad_in = evaluate(None)
        self.assertEqual(codes(validate(dict(bad_in, proposal_id="plan_x"))),
                         [("invalid_proposal_id", "proposal_id")])

    def test_execution_flags_must_be_exactly_false(self):
        r = evaluate(make_proposal())
        for bad in (True, 1, 0, "False", None, [], 0.0):
            self.assertEqual(codes(validate(dict(r, execution_allowed=bad))),
                             [("invalid_execution_allowed", "execution_allowed")], repr(bad))
            self.assertEqual(codes(validate(dict(r, executed=bad))),
                             [("invalid_executed", "executed")], repr(bad))

    def test_validation_never_repairs_and_is_bounded(self):
        r = dict(evaluate(make_proposal()), version=2, allowed=1, reason=3, proposal_id=4,
                 execution_allowed=5, executed=6)
        before = copy.deepcopy(r)
        v = validate(r)
        self.assertEqual(r, before)
        self.assertLessEqual(len(v["errors"]), 16)
        self.assertEqual(v, validate(r))
        self.assertIsNot(v["errors"], validate(r)["errors"])
        self.assertIs(v["execution_allowed"], False)
        self.assertIs(v["executed"], False)


class BoundaryTests(unittest.TestCase):
    def test_imports_and_no_io(self):
        tree = ast.parse(inspect.getsource(up))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                mods.add(n.module)
        self.assertEqual(mods, {"upgrade.change_proposal", "upgrade.project_state",
                                "upgrade.upgrade_request"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("open", "exec", "eval", "compile", "__import__", "input", "print"):
            self.assertNotIn(forbidden, names)

    def test_validators_are_reused_not_duplicated(self):
        from upgrade import change_proposal, project_state
        self.assertIs(up.validate_change_proposal, change_proposal.validate_change_proposal)
        self.assertIs(up.validate_project_state, project_state.validate_project_state)
        src = inspect.getsource(up)
        self.assertNotIn("def _proposal_errors", src)
        self.assertNotIn("def _check_change", src)

    def test_nothing_outside_upgrade_imports_the_policy_and_earlier_contracts_unchanged(self):
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ("upgrade", "tests", "__pycache__")]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        self.assertNotIn("upgrade_policy", fh.read(), os.path.join(folder, name))
        from upgrade import change_proposal, project_state, upgrade_plan, upgrade_request
        self.assertEqual((len(upgrade_request.FIELDS), len(project_state.FIELDS),
                          len(upgrade_plan.FIELDS), len(change_proposal.FIELDS)), (7, 8, 8, 7))


if __name__ == "__main__":
    unittest.main()
