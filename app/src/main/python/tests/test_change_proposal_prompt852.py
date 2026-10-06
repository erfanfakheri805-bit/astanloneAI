"""
Prompt 852 - upgrade change proposal focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_change_proposal_prompt852 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade import change_proposal as cp
from upgrade.change_proposal import build_change_proposal as build
from upgrade.change_proposal import validate_change_proposal as validate
from upgrade.project_state import build_project_state
from upgrade.upgrade_plan import build_upgrade_plan
from upgrade.upgrade_request import build_upgrade_request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "proposal", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
PROPOSAL_KEYS = ["version", "plan_id", "changes", "affected_files", "affected_capabilities",
                 "constraints", "execution_allowed"]


def make_state(**over):
    d = {"project_id": "proj_001", "revision": "r851",
         "files": [{"path": "formatter/response.py", "kind": "module", "status": "present"},
                   {"path": "formatter/style.py", "kind": "module", "status": "present"}],
         "capabilities": ["response_format", "tone"], "tests": ["tests.test_formatter"],
         "constraints": ["Frozen tests stay unchanged."]}
    d.update(over)
    result = build_project_state(d)
    assert result["valid"], result["errors"]
    return result["project_state"]


def make_plan(scope=("formatter/response.py", "response_format"), state=None, **req):
    d = {"request_id": "upg_001", "goal": "Improve response formatting.",
         "scope": list(scope), "constraints": ["No data loss.", "Keep API stable."],
         "requested_by": "developer"}
    d.update(req)
    request = build_upgrade_request(d)
    assert request["valid"], request["errors"]
    result = build_upgrade_plan(request["upgrade_request"], state or make_state())
    assert result["valid"], result["errors"]
    return result["plan"]


def proposal(**over):
    p = build(make_plan(), make_state())["proposal"]
    p.update(over)
    return p


def codes(result):
    return [(e["code"], e["where"]) for e in result["errors"]]


def check_shape(test, result, keys=BUILD_KEYS):
    test.assertEqual(list(result), keys)
    test.assertIs(result["execution_allowed"], False)
    test.assertIs(result["executed"], False)
    json.dumps(result)


class BuildValidTests(unittest.TestCase):
    def test_valid_proposal(self):
        r = build(make_plan(), make_state())
        check_shape(self, r)
        self.assertIs(r["valid"], True)
        self.assertEqual(r["errors"], [])
        p = r["proposal"]
        self.assertEqual(list(p), PROPOSAL_KEYS)
        self.assertNotIn("executed", p)
        self.assertEqual(p["version"], "1")
        self.assertIs(p["execution_allowed"], False)
        check_shape(self, validate(p), VALIDATE_KEYS)
        self.assertIs(validate(p)["valid"], True)

    def test_multiple_changes_preserve_steps_in_order(self):
        plan = make_plan(scope=["tone", "formatter/style.py", "formatter/response.py"])
        p = build(plan, make_state())["proposal"]
        self.assertEqual(len(p["changes"]), 3)
        for index, (change, step) in enumerate(zip(p["changes"], plan["steps"]), 1):
            self.assertEqual(list(change), ["change_id", "action", "target", "reason"])
            self.assertEqual(change["change_id"], "change_%d" % index)
            for key in ("action", "target", "reason"):
                self.assertEqual(change[key], step[key])
        self.assertEqual([c["target"] for c in p["changes"]],
                         ["tone", "formatter/style.py", "formatter/response.py"])

    def test_affected_lists_and_constraints_preserved_exactly(self):
        plan = make_plan(scope=["tone", "formatter/style.py", "formatter/response.py"])
        p = build(plan, make_state())["proposal"]
        self.assertEqual(p["affected_files"], ["formatter/style.py", "formatter/response.py"])
        self.assertEqual(p["affected_capabilities"], ["tone"])
        self.assertEqual(p["constraints"], plan["constraints"])
        for key in ("affected_files", "affected_capabilities", "constraints"):
            self.assertIsNot(p[key], plan[key])

    def test_nothing_outside_the_plan_is_added(self):
        p = build(make_plan(scope=["tone"]), make_state())["proposal"]
        self.assertEqual([c["target"] for c in p["changes"]], ["tone"])
        self.assertEqual(p["affected_files"], [])

    def test_ids_are_deterministic_and_unique(self):
        plan = make_plan(scope=["tone", "response_format", "formatter/style.py"])
        a, b = build(plan, make_state()), build(plan, make_state())
        self.assertEqual(a, b)
        ids = [c["change_id"] for c in a["proposal"]["changes"]]
        self.assertEqual(ids, ["change_1", "change_2", "change_3"])
        self.assertEqual(len(set(ids)), 3)
        pid = a["proposal"]["plan_id"]
        self.assertRegex(pid, r"^plan_[0-9a-f]{16}$")
        self.assertEqual(pid, cp.derive_plan_id(plan))

    def test_plan_id_depends_only_on_plan_content(self):
        plan = make_plan()
        other_state = make_state(revision="r999", tests=["t"])
        self.assertEqual(build(plan, make_state())["proposal"]["plan_id"],
                         build(plan, other_state)["proposal"]["plan_id"])
        changed = make_plan(goal="Another goal.")
        self.assertNotEqual(cp.derive_plan_id(plan), cp.derive_plan_id(changed))
        self.assertNotEqual(cp.derive_plan_id(plan), cp.derive_plan_id(make_plan(scope=["tone"])))
        non_ascii = make_plan(goal="\u0647\u062f\u0641")
        self.assertRegex(cp.derive_plan_id(non_ascii), r"^plan_[0-9a-f]{16}$")

    def test_fresh_results_and_inputs_untouched(self):
        plan, state = make_plan(), make_state()
        before = copy.deepcopy((plan, state))
        a = build(plan, state)
        a["proposal"]["changes"][0]["target"] = "changed"
        a["proposal"]["affected_files"].append("x")
        self.assertEqual((plan, state), before)
        self.assertEqual(build(plan, state), build(plan, state))
        self.assertIsNot(build(plan, state)["proposal"], build(plan, state)["proposal"])

    def test_maximum_plan_is_bounded(self):
        caps = ["cap_%d" % i for i in range(16)]
        state = make_state(capabilities=caps)
        r = build(make_plan(scope=caps, state=state), state)
        self.assertIs(r["valid"], True)
        self.assertEqual(len(r["proposal"]["changes"]), 16)


class BuildFailureTests(unittest.TestCase):
    def test_invalid_plan(self):
        bad_plans = [None, {}, "x", 1, [], dict(make_plan(), version="2"),
                     dict(make_plan(), steps=[]), dict(make_plan(), execution_allowed=True),
                     dict(make_plan(), extra=1)]
        for bad in bad_plans:
            r = build(bad, make_state())
            check_shape(self, r)
            self.assertEqual(codes(r), [("invalid_upgrade_plan", "upgrade_plan")], repr(bad))
            self.assertIsNone(r["proposal"])

    def test_invalid_project_state(self):
        for bad in (None, {}, "x", [], dict(make_state(), revision=""),
                    dict(make_state(), execution_allowed=True)):
            r = build(make_plan(), bad)
            self.assertEqual(codes(r), [("invalid_project_state", "project_state")], repr(bad))
            self.assertIsNone(r["proposal"])

    def test_both_invalid_and_defaults(self):
        expected = [("invalid_upgrade_plan", "upgrade_plan"),
                    ("invalid_project_state", "project_state")]
        self.assertEqual(codes(build(None, None)), expected)
        self.assertEqual(codes(build()), expected)

    def test_malformed_inputs_never_raise(self):
        class Evil:
            def __eq__(self, o):
                raise RuntimeError("boom")

            def __iter__(self):
                raise RuntimeError("boom")

            def __len__(self):
                raise RuntimeError("boom")

        class D(dict):
            pass

        for bad in (Evil(), D(make_plan()), object(), b"x", (1,)):
            r = build(bad, bad)
            check_shape(self, r)
            self.assertIs(r["valid"], False)
            check_shape(self, validate(bad), VALIDATE_KEYS)

    def test_plan_not_matching_project_state(self):
        # a valid plan whose targets are not (or no longer) in the supplied state
        plan = make_plan(scope=["formatter/response.py", "tone"])
        other = make_state(files=[{"path": "other.py", "kind": "module", "status": "present"}],
                           capabilities=["response_format"])
        r = build(plan, other)
        self.assertEqual(codes(r), [("step_target_not_in_project_state", "steps[0]"),
                                    ("step_target_not_in_project_state", "steps[1]")])
        self.assertIsNone(r["proposal"])

    def test_inconsistent_affected_lists(self):
        plan = make_plan()
        r = build(dict(plan, affected_files=["formatter/style.py"]), make_state())
        self.assertEqual(codes(r), [("affected_files_mismatch", "affected_files")])
        r = build(dict(plan, affected_capabilities=[]), make_state())
        self.assertEqual(codes(r), [("affected_capabilities_mismatch", "affected_capabilities")])
        swapped = make_plan(scope=["formatter/response.py", "formatter/style.py"])
        r = build(dict(swapped, affected_files=list(reversed(swapped["affected_files"]))), make_state())
        self.assertEqual(codes(r), [("affected_files_mismatch", "affected_files")])

    def test_unsupported_action_is_not_guessed(self):
        plan = make_plan()
        plan["steps"][0]["action"] = "delete_everything"
        r = build(plan, make_state())
        self.assertEqual(codes(r)[0], ("unsupported_step_action", "steps[0]"))
        self.assertIsNone(r["proposal"])

    def test_action_target_kind_mismatch(self):
        plan = make_plan()
        plan["steps"][0]["action"] = "update_capability"  # target is a file path
        r = build(plan, make_state())
        self.assertIn(("step_target_not_in_project_state", "steps[0]"), codes(r))


class ValidateProposalTests(unittest.TestCase):
    def test_missing_non_dict_and_unexpected(self):
        self.assertEqual(codes(validate(None)), [("missing_proposal", "proposal")])
        self.assertEqual(codes(validate()), [("missing_proposal", "proposal")])
        for bad in ("p", 1, [], (), b"x", True):
            self.assertEqual(codes(validate(bad)), [("proposal_not_dict", "proposal")], repr(bad))

        class D(dict):
            pass
        self.assertEqual(codes(validate(D(proposal()))), [("proposal_not_dict", "proposal")])
        self.assertEqual(codes(validate(dict(proposal(), executed=False))),
                         [("unexpected_field", "executed")])
        big = {("k%d" % i): 1 for i in range(17)}
        self.assertEqual(codes(validate(big)), [("too_many_fields", "proposal")])
        for field in PROPOSAL_KEYS:
            p = proposal()
            del p[field]
            self.assertEqual(codes(validate(p)), [("missing_field", field)])

    def test_version_and_plan_id(self):
        for bad in ("2", "", 1, None, True):
            self.assertEqual(codes(validate(proposal(version=bad))), [("invalid_version", "version")])
        for bad in ("", " p", "p ", "p\n", None, 5, ["p"], "p" * 65):
            self.assertEqual(codes(validate(proposal(plan_id=bad))), [("invalid_plan_id", "plan_id")])

        class S(str):
            pass
        self.assertEqual(codes(validate(proposal(plan_id=S("plan_x")))), [("invalid_plan_id", "plan_id")])

    def test_changes_container(self):
        self.assertEqual(codes(validate(proposal(changes=[]))), [("empty_changes", "changes")])
        for bad in (None, "c", (), {}):
            self.assertEqual(codes(validate(proposal(changes=bad))), [("invalid_changes", "changes")])
        ch = proposal()["changes"][0]
        many = [dict(ch, change_id="c%d" % i) for i in range(17)]
        self.assertEqual(codes(validate(proposal(changes=many))), [("too_many_items", "changes")])

        class L(list):
            pass
        self.assertEqual(codes(validate(proposal(changes=L([ch])))), [("invalid_changes", "changes")])

    def test_malformed_change(self):
        good = proposal()["changes"][0]
        for bad in (None, "c", ["a"], 1):
            self.assertEqual(codes(validate(proposal(changes=[bad]))), [("invalid_change", "changes[0]")])
        for key in ("change_id", "action", "target", "reason"):
            c = dict(good)
            del c[key]
            self.assertEqual(codes(validate(proposal(changes=[c]))),
                             [("missing_change_field", "changes[0].%s" % key)])
        self.assertEqual(codes(validate(proposal(changes=[dict(good, extra="x")]))),
                         [("unexpected_change_field", "changes[0].extra")])
        wide = {("k%d" % i): "v" for i in range(17)}
        self.assertEqual(codes(validate(proposal(changes=[wide]))), [("too_many_change_fields", "changes[0]")])

        class D(dict):
            pass
        self.assertEqual(codes(validate(proposal(changes=[D(good)]))), [("invalid_change", "changes[0]")])

    def test_malformed_change_values(self):
        good = proposal()["changes"][0]
        limits = {"change_id": 64, "action": 64, "target": 200, "reason": 200}
        for key, limit in limits.items():
            for bad in ("", " x", "x ", "a\tb", None, 5, ["x"], "x" * (limit + 1)):
                r = validate(proposal(changes=[dict(good, **{key: bad})]))
                self.assertEqual(codes(r), [("invalid_change_" + key, "changes[0].%s" % key)], (key, bad))
        ok = dict(good, change_id="c" * 64, action="a" * 64, target="t" * 200, reason="r" * 200)
        self.assertIs(validate(proposal(changes=[ok]))["valid"], True)

    def test_duplicate_change_id(self):
        good = proposal()["changes"][0]
        r = validate(proposal(changes=[good, dict(good)]))
        self.assertEqual(codes(r), [("duplicate_change_id", "changes[1].change_id")])

    def test_order_is_not_a_validator_concern_but_ids_must_stay_unique(self):
        a, b = proposal()["changes"][:2]
        self.assertIs(validate(proposal(changes=[b, a]))["valid"], True)
        self.assertEqual(codes(validate(proposal(changes=[b, dict(a, change_id=b["change_id"])]))),
                         [("duplicate_change_id", "changes[1].change_id")])

    def test_affected_files_and_capabilities(self):
        for field, limit in (("affected_files", 200), ("affected_capabilities", 64)):
            self.assertEqual(codes(validate(proposal(**{field: "x"}))), [("invalid_" + field, field)])
            self.assertEqual(codes(validate(proposal(**{field: ("x",)}))), [("invalid_" + field, field)])
            for bad in ("", " x", "x ", "a\x00b", None, 3, ["x"], "x" * (limit + 1)):
                self.assertEqual(codes(validate(proposal(**{field: ["ok", bad]}))),
                                 [("invalid_item", "%s[1]" % field)], (field, bad))
            self.assertEqual(codes(validate(proposal(**{field: ["x", "x"]}))),
                             [("duplicate_item", "%s[1]" % field)])
            self.assertEqual(codes(validate(proposal(**{field: ["x%d" % i for i in range(17)]}))),
                             [("too_many_items", field)])

    def test_constraints(self):
        self.assertEqual(codes(validate(proposal(constraints="c"))), [("invalid_constraints", "constraints")])
        for bad in ("", " c", None, 1, "c" * 201):
            self.assertEqual(codes(validate(proposal(constraints=["a", bad]))),
                             [("invalid_item", "constraints[1]")])
        self.assertIs(validate(proposal(constraints=["same", "same"]))["valid"], True)
        self.assertEqual(codes(validate(proposal(constraints=["c"] * 17))), [("too_many_items", "constraints")])


class ExecutionAndBoundaryTests(unittest.TestCase):
    def test_execution_attempts_rejected(self):
        for bad in (True, 1, 0, "False", "", None, [], 0.0):
            self.assertEqual(codes(validate(proposal(execution_allowed=bad))),
                             [("invalid_execution_allowed", "execution_allowed")], repr(bad))
        plan = dict(make_plan(), execution_allowed=True)
        self.assertEqual(codes(build(plan, make_state())), [("invalid_upgrade_plan", "upgrade_plan")])

    def test_results_never_allow_or_report_execution(self):
        for r in (build(make_plan(), make_state()), build(None, None), validate(proposal()),
                  validate(None), validate(proposal(execution_allowed=True))):
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_oversized_input_is_capped_and_fresh(self):
        bad = proposal(affected_files=[None] * 16, constraints=[None] * 16)
        r = validate(bad)
        self.assertLessEqual(len(r["errors"]), 16)
        self.assertEqual(r, validate(bad))
        self.assertIsNot(r["errors"], validate(bad)["errors"])
        self.assertEqual(codes(validate(proposal(changes=[{}] * 17))), [("too_many_items", "changes")])

    def test_imports_and_no_io(self):
        tree = ast.parse(inspect.getsource(cp))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                mods.add(n.module)
        self.assertEqual(mods, {"hashlib", "json", "upgrade.project_state", "upgrade.upgrade_plan",
                                "upgrade.upgrade_request"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("open", "exec", "eval", "compile", "__import__", "input", "print"):
            self.assertNotIn(forbidden, names)

    def test_nothing_outside_upgrade_imports_the_proposal_and_earlier_contracts_unchanged(self):
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ("upgrade", "tests", "__pycache__")]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        self.assertNotIn("change_proposal", fh.read(), os.path.join(folder, name))
        from upgrade import project_state, upgrade_plan, upgrade_request
        self.assertEqual((len(upgrade_request.FIELDS), len(project_state.FIELDS),
                          len(upgrade_plan.FIELDS)), (7, 8, 8))


if __name__ == "__main__":
    unittest.main()
