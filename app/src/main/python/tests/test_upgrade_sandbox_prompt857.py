"""
Prompt 857 - upgrade sandbox workspace focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_upgrade_sandbox_prompt857 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade import upgrade_sandbox as sb
from upgrade.upgrade_sandbox import apply_change_set_to_sandbox as apply_cs
from upgrade.upgrade_sandbox import build_sandbox_workspace as build
from upgrade.upgrade_sandbox import validate_sandbox_workspace as validate
from tests.test_change_set_prompt855 import make_set
from tests.test_upgrade_policy_prompt854 import make_state

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "workspace", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
APPLY_KEYS = ["status", "applied", "changes", "workspace", "errors",
              "execution_allowed", "executed"]
WS_KEYS = ["version", "project_state", "applied", "execution_allowed", "executed"]


def workspace():
    out = build(make_state())
    assert out["valid"], out["errors"]
    return out["workspace"]


def change_set(*targets):
    """Change set over (action, target) pairs from the sample project state."""
    base = make_set()
    changes = [{"change_id": "change_%d" % (i + 1), "action": a, "target": t, "reason": "r%d" % i}
               for i, (a, t) in enumerate(targets)]
    return dict(base, changes=changes)


def codes(result):
    return [(e["code"], e["where"]) for e in result["errors"]]


def check_shape(test, result, keys):
    test.assertEqual(list(result), keys)
    test.assertIs(result["execution_allowed"], False)
    test.assertIs(result["executed"], False)
    json.dumps(result)


class BuildTests(unittest.TestCase):
    def test_builds_normalized_workspace(self):
        state = make_state()
        out = build(state)
        check_shape(self, out, BUILD_KEYS)
        self.assertEqual((out["valid"], out["errors"]), (True, []))
        ws = out["workspace"]
        self.assertEqual(list(ws), WS_KEYS)
        self.assertEqual(ws["version"], "1")
        self.assertEqual(ws["project_state"], state)
        self.assertEqual(ws["applied"], [])
        self.assertIs(ws["execution_allowed"], False)
        self.assertIs(ws["executed"], False)
        self.assertIs(validate(ws)["valid"], True)

    def test_declared_files_and_capabilities_with_metadata(self):
        ps = workspace()["project_state"]
        self.assertEqual([d["path"] for d in ps["files"]], ["formatter/response.py", "formatter/style.py"])
        self.assertEqual(ps["files"][0], {"path": "formatter/response.py", "kind": "module", "status": "present"})
        self.assertEqual(ps["capabilities"], ["response_format", "tone"])

    def test_fresh_and_input_untouched(self):
        state = make_state()
        before = copy.deepcopy(state)
        a, b = build(state), build(state)
        self.assertEqual(a, b)
        self.assertEqual(state, before)
        self.assertIsNot(a["workspace"], b["workspace"])
        self.assertIsNot(a["workspace"]["project_state"], state)
        self.assertIsNot(a["workspace"]["project_state"]["files"][0], state["files"][0])
        a["workspace"]["project_state"]["files"][0]["status"] = "changed"
        self.assertEqual(state, before)

    def test_rejects_invalid_project_state(self):
        for bad in (None, "x", [], {}, dict(make_state(), revision=""),
                    dict(make_state(), execution_allowed=True)):
            out = build(bad)
            check_shape(self, out, BUILD_KEYS)
            self.assertEqual((out["valid"], out["workspace"]), (False, None))
            self.assertEqual(codes(out), [("invalid_project_state", "project_state")], repr(bad))
        self.assertEqual(codes(build()), [("invalid_project_state", "project_state")])

    def test_never_raises(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

        for bad in (Boom(), object()):
            out = build(bad)
            check_shape(self, out, BUILD_KEYS)
            self.assertIs(out["valid"], False)


class ApplyTests(unittest.TestCase):
    def test_apply_allowed_change_set(self):
        ws, cset = workspace(), make_set()
        out = apply_cs(ws, cset)
        check_shape(self, out, APPLY_KEYS)
        self.assertEqual((out["status"], out["applied"], out["errors"]), ("applied", True, []))
        self.assertEqual(out["changes"], cset["changes"])
        new = out["workspace"]
        self.assertEqual(new["applied"], [{"proposal_id": cset["proposal_id"], "changes": cset["changes"]}])
        self.assertEqual(new["project_state"], ws["project_state"])
        self.assertIs(validate(new)["valid"], True)

    def test_only_metadata_is_recorded_nothing_invented(self):
        ws = workspace()
        new = apply_cs(ws, make_set())["workspace"]
        self.assertEqual(list(new), WS_KEYS)
        self.assertEqual(list(new["applied"][0]), ["proposal_id", "changes"])
        self.assertEqual(new["project_state"]["files"], ws["project_state"]["files"])

    def test_inputs_never_modified_and_results_fresh(self):
        ws, cset = workspace(), make_set()
        before = copy.deepcopy((ws, cset))
        out = apply_cs(ws, cset)
        self.assertEqual((ws, cset), before)
        self.assertEqual(ws["applied"], [])
        self.assertIsNot(out["workspace"], ws)
        self.assertIsNot(out["workspace"]["project_state"], ws["project_state"])
        for a, b in zip(out["changes"], cset["changes"]):
            self.assertIsNot(a, b)
        for a, b in zip(out["workspace"]["applied"][0]["changes"], out["changes"]):
            self.assertIsNot(a, b)
        out["changes"][0]["target"] = "changed"
        out["workspace"]["applied"][0]["changes"][0]["reason"] = "changed"
        self.assertEqual(cset, before[1])

    def test_deterministic(self):
        ws, cset = workspace(), make_set()
        self.assertEqual(apply_cs(ws, cset), apply_cs(ws, cset))

    def test_multiple_targets_and_sequential_apply(self):
        ws = workspace()
        first = apply_cs(ws, change_set(("modify_file", "formatter/style.py"), ("update_capability", "tone")))
        self.assertIs(first["applied"], True)
        other = dict(change_set(("modify_file", "formatter/response.py")), proposal_id="plan_second")
        second = apply_cs(first["workspace"], other)
        self.assertIs(second["applied"], True)
        self.assertEqual([r["proposal_id"] for r in second["workspace"]["applied"]],
                         [make_set()["proposal_id"], "plan_second"])
        self.assertEqual(len(first["workspace"]["applied"]), 1)

    def test_unknown_targets_rejected(self):
        ws = workspace()
        cases = ((("modify_file", "missing.py"),), (("update_capability", "ghost"),),
                 (("modify_file", "tone"),), (("update_capability", "formatter/style.py"),))
        for case in cases:
            out = apply_cs(ws, change_set(*case))
            check_shape(self, out, APPLY_KEYS)
            self.assertEqual((out["status"], out["applied"], out["changes"], out["workspace"]),
                             ("rejected", False, [], None))
            self.assertEqual(codes(out), [("unknown_target", "changes[0].target")], repr(case))

    def test_all_or_nothing(self):
        ws = workspace()
        out = apply_cs(ws, change_set(("modify_file", "formatter/style.py"), ("modify_file", "nope.py")))
        self.assertEqual(codes(out), [("unknown_target", "changes[1].target")])
        self.assertIsNone(out["workspace"])
        self.assertEqual(ws["applied"], [])

    def test_invalid_change_set_rejected(self):
        ws = workspace()
        bad_sets = (None, "x", [], {}, make_set(version="2"), make_set(changes=[]),
                    make_set(execution_allowed=True),
                    change_set(("run_shell", "formatter/style.py")))
        for bad in bad_sets:
            out = apply_cs(ws, bad)
            self.assertEqual(codes(out), [("invalid_change_set", "change_set")], repr(bad))
            self.assertEqual((out["status"], out["applied"]), ("rejected", False))

    def test_invalid_workspace_rejected(self):
        cset = make_set()
        bad_ws = (None, "x", [], {}, dict(workspace(), version="2"), dict(workspace(), extra=1),
                  dict(workspace(), applied="x"), dict(workspace(), executed=True),
                  dict(workspace(), project_state={}))
        for bad in bad_ws:
            self.assertEqual(codes(apply_cs(bad, cset)), [("invalid_workspace", "workspace")], repr(bad))
        self.assertEqual(codes(apply_cs()), [("invalid_workspace", "workspace"),
                                             ("invalid_change_set", "change_set")])

    def test_duplicate_change_within_change_set(self):
        out = apply_cs(workspace(), change_set(("modify_file", "formatter/style.py"),
                                               ("update_capability", "tone"),
                                               ("modify_file", "formatter/style.py")))
        self.assertEqual(codes(out), [("duplicate_change", "changes[2]")])

    def test_change_set_cannot_be_applied_twice(self):
        cset = make_set()
        first = apply_cs(workspace(), cset)["workspace"]
        again = apply_cs(first, cset)
        self.assertEqual(codes(again), [("change_set_already_applied", "change_set.proposal_id")])
        self.assertEqual(len(first["applied"]), 1)

    def test_identity_mismatch_in_workspace_records(self):
        applied = apply_cs(workspace(), make_set())["workspace"]
        dup = copy.deepcopy(applied)
        dup["applied"].append(copy.deepcopy(dup["applied"][0]))
        self.assertEqual(codes(validate(dup)), [("duplicate_proposal_id", "applied[1].proposal_id")])
        moved = copy.deepcopy(applied)
        moved["project_state"]["capabilities"] = ["tone"]
        self.assertIn(("unknown_target", "applied[0].changes[1].target"), codes(validate(moved)))

    def test_too_many_applied(self):
        ws = workspace()
        for i in range(16):
            ws = apply_cs(ws, dict(change_set(("modify_file", "formatter/style.py")),
                                   proposal_id="plan_%d" % i))["workspace"]
        self.assertEqual(len(ws["applied"]), 16)
        out = apply_cs(ws, dict(make_set(), proposal_id="plan_extra"))
        self.assertEqual(codes(out), [("too_many_applied", "applied")])
        self.assertEqual(len(ws["applied"]), 16)

    def test_oversized_inputs_are_bounded(self):
        out = apply_cs(workspace(), make_set(changes=[{}] * 500))
        self.assertEqual(codes(out), [("invalid_change_set", "change_set")])
        huge = dict(workspace(), applied=[{}] * 500)
        self.assertEqual(codes(validate(huge)), [("too_many_items", "applied")])

    def test_execution_flags_always_false(self):
        ws = workspace()
        for out in (build(make_state()), build(None), apply_cs(ws, make_set()), apply_cs(None, None),
                    validate(ws), validate(None)):
            self.assertIs(out["execution_allowed"], False)
            self.assertIs(out["executed"], False)

    def test_never_raises(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

        for a, b in ((Boom(), Boom()), (object(), object()), (workspace(), Boom())):
            out = apply_cs(a, b)
            check_shape(self, out, APPLY_KEYS)
            self.assertIs(out["applied"], False)


class ValidateTests(unittest.TestCase):
    def test_valid(self):
        for ws in (workspace(), apply_cs(workspace(), make_set())["workspace"]):
            v = validate(ws)
            check_shape(self, v, VALIDATE_KEYS)
            self.assertEqual((v["valid"], v["errors"]), (True, []))

    def test_missing_and_non_dict(self):
        self.assertEqual(codes(validate(None)), [("missing_workspace", "workspace")])
        self.assertEqual(codes(validate()), [("missing_workspace", "workspace")])
        for bad in ("x", [], 1, (), True):
            self.assertEqual(codes(validate(bad)), [("workspace_not_dict", "workspace")])

    def test_missing_unexpected_too_many_fields(self):
        ws = workspace()
        for key in WS_KEYS:
            c = dict(ws)
            del c[key]
            self.assertEqual(codes(validate(c)), [("missing_field", key)])
        self.assertEqual(codes(validate(dict(ws, extra=1))), [("unexpected_field", "extra")])
        self.assertEqual(codes(validate({"k%d" % i: i for i in range(17)})),
                         [("too_many_fields", "workspace")])

    def test_version_state_flags(self):
        ws = workspace()
        for bad in ("2", 1, None):
            self.assertEqual(codes(validate(dict(ws, version=bad))), [("invalid_version", "version")])
        self.assertEqual(codes(validate(dict(ws, project_state=None))),
                         [("invalid_project_state", "project_state")])
        for bad in (True, 1, 0, "False", None):
            self.assertEqual(codes(validate(dict(ws, execution_allowed=bad))),
                             [("invalid_execution_allowed", "execution_allowed")], repr(bad))
            self.assertEqual(codes(validate(dict(ws, executed=bad))),
                             [("invalid_executed", "executed")], repr(bad))

    def test_malformed_applied_records(self):
        ws = workspace()
        rec = {"proposal_id": "plan_x", "changes": make_set()["changes"]}
        self.assertEqual(codes(validate(dict(ws, applied=[None]))), [("invalid_applied_record", "applied[0]")])
        self.assertEqual(codes(validate(dict(ws, applied=[dict(rec, extra=1)]))),
                         [("invalid_applied_field", "applied[0].extra")])
        self.assertEqual(codes(validate(dict(ws, applied=[{"changes": rec["changes"]}]))),
                         [("missing_field", "applied[0].proposal_id")])
        self.assertEqual(codes(validate(dict(ws, applied=[dict(rec, proposal_id="")]))),
                         [("invalid_proposal_id", "applied[0].proposal_id")])
        self.assertEqual(codes(validate(dict(ws, applied=[dict(rec, changes=[])]))),
                         [("empty_changes", "applied[0].changes")])
        bad_action = [dict(rec["changes"][0], action="run_shell")]
        self.assertEqual(codes(validate(dict(ws, applied=[dict(rec, changes=bad_action)]))),
                         [("unsupported_change_action", "applied[0].changes[0].action")])

    def test_bounded_fresh_and_no_repair(self):
        bad = dict(workspace(), version=2, applied=[{"proposal_id": 1, "changes": [{}] * 16}] * 3,
                   execution_allowed=5, executed=6)
        before = copy.deepcopy(bad)
        v = validate(bad)
        self.assertEqual(bad, before)
        self.assertLessEqual(len(v["errors"]), 16)
        self.assertEqual(v, validate(bad))
        self.assertIsNot(v["errors"], validate(bad)["errors"])


class BoundaryTests(unittest.TestCase):
    def test_imports_and_no_io(self):
        tree = ast.parse(inspect.getsource(sb))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                mods.add(n.module)
        self.assertEqual(mods, {"copy", "upgrade.change_proposal", "upgrade.change_set",
                                "upgrade.project_state", "upgrade.upgrade_plan",
                                "upgrade.upgrade_request"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("open", "exec", "eval", "compile", "__import__", "input", "print"):
            self.assertNotIn(forbidden, names)

    def test_validators_reused_and_nothing_outside_upgrade_imports_it(self):
        from upgrade import change_set as cs_mod, project_state
        self.assertIs(sb.validate_project_state, project_state.validate_project_state)
        self.assertIs(sb.validate_change_set, cs_mod.validate_change_set)
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ("upgrade", "tests", "__pycache__")]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        self.assertNotIn("upgrade_sandbox", fh.read(), os.path.join(folder, name))
        self.assertEqual((len(project_state.FIELDS), len(cs_mod.FIELDS)), (8, 4))


if __name__ == "__main__":
    unittest.main()
