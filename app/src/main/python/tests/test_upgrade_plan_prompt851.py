"""
Prompt 851 - upgrade plan contract focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_upgrade_plan_prompt851 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade import upgrade_plan as up
from upgrade.project_state import build_project_state
from upgrade.upgrade_plan import build_upgrade_plan as build
from upgrade.upgrade_plan import validate_upgrade_plan as validate
from upgrade.upgrade_request import build_upgrade_request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "plan", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
PLAN_KEYS = ["version", "request_id", "goal", "steps", "affected_files",
             "affected_capabilities", "constraints", "execution_allowed"]


def make_request(**over):
    d = {"request_id": "upg_001", "goal": "Improve response formatting.",
         "scope": ["formatter/response.py", "response_format"],
         "constraints": ["No data loss.", "Keep API stable."], "requested_by": "developer"}
    d.update(over)
    result = build_upgrade_request(d)
    assert result["valid"], result["errors"]
    return result["upgrade_request"]


def make_state(**over):
    d = {"project_id": "proj_001", "revision": "r850",
         "files": [{"path": "formatter/response.py", "kind": "module", "status": "present"},
                   {"path": "formatter/style.py", "kind": "module", "status": "present"}],
         "capabilities": ["response_format", "tone"], "tests": ["tests.test_formatter"],
         "constraints": ["Frozen tests stay unchanged."]}
    d.update(over)
    result = build_project_state(d)
    assert result["valid"], result["errors"]
    return result["project_state"]


def plan(**over):
    p = build(make_request(), make_state())["plan"]
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
    def test_valid_request_and_state(self):
        r = build(make_request(), make_state())
        check_shape(self, r)
        self.assertIs(r["valid"], True)
        self.assertEqual(r["errors"], [])
        self.assertEqual(list(r["plan"]), PLAN_KEYS)
        self.assertNotIn("executed", r["plan"])
        self.assertIs(r["plan"]["execution_allowed"], False)
        self.assertEqual(r["plan"]["version"], "1")

    def test_plan_matches_request_exactly(self):
        req = make_request()
        p = build(req, make_state())["plan"]
        self.assertEqual(p["request_id"], req["request_id"])
        self.assertEqual(p["goal"], req["goal"])
        self.assertEqual(p["constraints"], req["constraints"])
        self.assertIsNot(p["constraints"], req["constraints"])

    def test_multi_step_plan(self):
        req = make_request(scope=["formatter/style.py", "tone", "formatter/response.py"])
        p = build(req, make_state())["plan"]
        self.assertEqual(p["steps"], [
            {"step_id": "step_1", "action": "modify_file", "target": "formatter/style.py",
             "reason": "Listed in scope of request upg_001"},
            {"step_id": "step_2", "action": "update_capability", "target": "tone",
             "reason": "Listed in scope of request upg_001"},
            {"step_id": "step_3", "action": "modify_file", "target": "formatter/response.py",
             "reason": "Listed in scope of request upg_001"}])
        self.assertEqual(p["affected_files"], ["formatter/style.py", "formatter/response.py"])
        self.assertEqual(p["affected_capabilities"], ["tone"])

    def test_nothing_outside_scope_is_named(self):
        p = build(make_request(scope=["tone"]), make_state())["plan"]
        self.assertEqual(p["affected_files"], [])
        self.assertEqual(p["affected_capabilities"], ["tone"])
        self.assertEqual(len(p["steps"]), 1)

    def test_built_plan_validates_and_is_json_safe(self):
        p = build(make_request(), make_state())["plan"]
        v = validate(p)
        check_shape(self, v, VALIDATE_KEYS)
        self.assertIs(v["valid"], True)
        json.dumps(p)

    def test_deterministic_fresh_and_inputs_untouched(self):
        req, state = make_request(), make_state()
        before = copy.deepcopy((req, state))
        a, b = build(req, state), build(req, state)
        self.assertEqual(a, b)
        self.assertIsNot(a["plan"], b["plan"])
        self.assertIsNot(a["plan"]["steps"], b["plan"]["steps"])
        a["plan"]["steps"].append("x")
        self.assertEqual(build(req, state), b)
        self.assertEqual((req, state), before)

    def test_maximum_scope_is_bounded(self):
        caps = ["cap_%d" % i for i in range(16)]
        r = build(make_request(scope=caps), make_state(capabilities=caps))
        self.assertIs(r["valid"], True)
        self.assertEqual(len(r["plan"]["steps"]), 16)


class BuildFailureTests(unittest.TestCase):
    def test_invalid_request(self):
        for bad in (None, {}, "x", 1, [], dict(make_request(), goal=""), dict(make_request(), extra=1),
                    dict(make_request(), execution_allowed=True)):
            r = build(bad, make_state())
            check_shape(self, r)
            self.assertEqual(codes(r), [("invalid_upgrade_request", "upgrade_request")], repr(bad))
            self.assertIsNone(r["plan"])

    def test_unnormalized_request_is_not_repaired(self):
        raw = {"request_id": "u", "goal": "g", "scope": ["tone"], "constraints": [],
               "requested_by": "d"}
        self.assertEqual(codes(build(raw, make_state())), [("invalid_upgrade_request", "upgrade_request")])

    def test_invalid_state(self):
        for bad in (None, {}, "x", 1, [], dict(make_state(), revision=""),
                    dict(make_state(), execution_allowed=True)):
            r = build(make_request(), bad)
            self.assertEqual(codes(r), [("invalid_project_state", "project_state")], repr(bad))
            self.assertIsNone(r["plan"])

    def test_both_invalid_reports_both(self):
        r = build(None, None)
        self.assertEqual(codes(r), [("invalid_upgrade_request", "upgrade_request"),
                                    ("invalid_project_state", "project_state")])
        self.assertEqual(codes(build()), codes(r))

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

        for bad in (Evil(), D(make_request()), object(), b"x", (1, 2)):
            r = build(bad, bad)
            check_shape(self, r)
            self.assertIs(r["valid"], False)
            check_shape(self, validate(bad), VALIDATE_KEYS)

    def test_empty_scope_is_unavailable_information(self):
        r = build(make_request(scope=[]), make_state())
        self.assertEqual(codes(r), [("empty_scope", "upgrade_request.scope")])
        self.assertIsNone(r["plan"])

    def test_empty_project_state_is_unavailable_information(self):
        r = build(make_request(), make_state(files=[], capabilities=[]))
        self.assertEqual(codes(r), [("empty_project_state", "project_state")])
        self.assertIsNone(r["plan"])

    def test_unknown_scope_target_is_not_invented(self):
        r = build(make_request(scope=["tone", "missing.py", "ghost"]), make_state())
        self.assertEqual(codes(r), [("unknown_scope_target", "scope[1]"),
                                    ("unknown_scope_target", "scope[2]")])
        self.assertIsNone(r["plan"])
        self._test_no_trim_or_case_inference()

    def _test_no_trim_or_case_inference(self):
        r = build(make_request(scope=["Tone", "formatter/RESPONSE.py"]), make_state())
        self.assertEqual([c for c, _ in codes(r)], ["unknown_scope_target"] * 2)

    def test_duplicate_scope_target_rejected(self):
        r = build(make_request(scope=["tone", "tone"]), make_state())
        self.assertEqual(codes(r), [("duplicate_scope_target", "scope[1]")])
        self._test_ambiguous_target_rejected()

    def _test_ambiguous_target_rejected(self):
        state = make_state(capabilities=["formatter/response.py"])
        r = build(make_request(scope=["formatter/response.py"]), state)
        self.assertEqual(codes(r), [("ambiguous_scope_target", "scope[0]")])


class ValidatePlanTests(unittest.TestCase):
    def test_missing_and_non_dict(self):
        self.assertEqual(codes(validate(None)), [("missing_plan", "plan")])
        self.assertEqual(codes(validate()), [("missing_plan", "plan")])
        for bad in ("p", 1, [], (), b"x", True):
            self.assertEqual(codes(validate(bad)), [("plan_not_dict", "plan")], repr(bad))

        class D(dict):
            pass
        self.assertEqual(codes(validate(D(plan()))), [("plan_not_dict", "plan")])
        self._test_each_field_missing()
        self._test_unexpected_and_oversized_plan()

    def _test_each_field_missing(self):
        for field in PLAN_KEYS:
            p = plan()
            del p[field]
            self.assertEqual(codes(validate(p)), [("missing_field", field)])

    def _test_unexpected_and_oversized_plan(self):
        self.assertEqual(codes(validate(dict(plan(), executed=False))), [("unexpected_field", "executed")])
        big = {("k%d" % i): 1 for i in range(17)}
        self.assertEqual(codes(validate(big)), [("too_many_fields", "plan")])

    def test_scalar_fields(self):
        for bad in ("2", 1, None, True, ""):
            self.assertEqual(codes(validate(plan(version=bad))), [("invalid_version", "version")])
        for bad in ("", " x", None, 1, "r" * 65):
            self.assertEqual(codes(validate(plan(request_id=bad))), [("invalid_request_id", "request_id")])
        for bad in ("", "g\n", None, 1, "g" * 501):
            self.assertEqual(codes(validate(plan(goal=bad))), [("invalid_goal", "goal")])
        self._test_str_subclass_rejected()

    def _test_str_subclass_rejected(self):
        class S(str):
            pass
        self.assertEqual(codes(validate(plan(goal=S("g")))), [("invalid_goal", "goal")])
        self.assertEqual(codes(validate(plan(affected_capabilities=[S("c")]))),
                         [("invalid_item", "affected_capabilities[0]")])

    def test_steps_container_rules(self):
        self.assertEqual(codes(validate(plan(steps=[]))), [("empty_steps", "steps")])
        for bad in (None, "s", (), {}):
            self.assertEqual(codes(validate(plan(steps=bad))), [("invalid_steps", "steps")])
        step = plan()["steps"][0]
        self.assertEqual(codes(validate(plan(steps=[dict(step, step_id="s%d" % i) for i in range(17)]))),
                         [("too_many_items", "steps")])

        class L(list):
            pass
        self.assertEqual(codes(validate(plan(steps=L([step])))), [("invalid_steps", "steps")])
        self._test_malformed_step_shape()

    def _test_malformed_step_shape(self):
        good = plan()["steps"][0]
        for bad in (None, "step", ["a"], 1):
            self.assertEqual(codes(validate(plan(steps=[bad]))), [("invalid_step", "steps[0]")])
        for key in ("step_id", "action", "target", "reason"):
            s = dict(good)
            del s[key]
            self.assertEqual(codes(validate(plan(steps=[s]))), [("missing_step_field", "steps[0].%s" % key)])
        self.assertEqual(codes(validate(plan(steps=[dict(good, extra="x")]))),
                         [("unexpected_step_field", "steps[0].extra")])
        wide = {("k%d" % i): "v" for i in range(17)}
        self.assertEqual(codes(validate(plan(steps=[wide]))), [("too_many_step_fields", "steps[0]")])

        class D(dict):
            pass
        self.assertEqual(codes(validate(plan(steps=[D(good)]))), [("invalid_step", "steps[0]")])

    def test_malformed_step_values(self):
        good = plan()["steps"][0]
        limits = {"step_id": 64, "action": 64, "target": 200, "reason": 200}
        for key, limit in limits.items():
            for bad in ("", " x", "x ", "a\tb", None, 5, ["x"], "x" * (limit + 1)):
                r = validate(plan(steps=[dict(good, **{key: bad})]))
                self.assertEqual(codes(r), [("invalid_step_" + key, "steps[0].%s" % key)], (key, bad))
        ok = dict(good, step_id="s" * 64, action="a" * 64, target="t" * 200, reason="r" * 200)
        self.assertIs(validate(plan(steps=[ok]))["valid"], True)

    def test_duplicate_step_id(self):
        good = plan()["steps"][0]
        r = validate(plan(steps=[good, dict(good)]))
        self.assertEqual(codes(r), [("duplicate_step_id", "steps[1].step_id")])

    def test_affected_files_validation(self):
        self.assertEqual(codes(validate(plan(affected_files="a.py"))), [("invalid_affected_files", "affected_files")])
        self.assertEqual(codes(validate(plan(affected_files=("a.py",)))), [("invalid_affected_files", "affected_files")])
        for bad in ("", " a.py", "a.py ", "a\x00.py", None, 3, ["a.py"], "p" * 201):
            r = validate(plan(affected_files=["ok.py", bad]))
            self.assertEqual(codes(r), [("invalid_item", "affected_files[1]")], bad)
        self.assertEqual(codes(validate(plan(affected_files=["a.py", "a.py"]))),
                         [("duplicate_item", "affected_files[1]")])
        self.assertEqual(codes(validate(plan(affected_files=["f%d" % i for i in range(17)]))),
                         [("too_many_items", "affected_files")])
        self.assertIs(validate(plan(affected_files=["p" * 200]))["valid"], True)
        self._test_affected_capabilities_validation()

    def _test_affected_capabilities_validation(self):
        self.assertEqual(codes(validate(plan(affected_capabilities=None))),
                         [("invalid_affected_capabilities", "affected_capabilities")])
        for bad in ("", "c ", "\nc", None, 1, "c" * 65):
            r = validate(plan(affected_capabilities=["ok", bad]))
            self.assertEqual(codes(r), [("invalid_item", "affected_capabilities[1]")], bad)
        self.assertEqual(codes(validate(plan(affected_capabilities=["c", "c"]))),
                         [("duplicate_item", "affected_capabilities[1]")])
        self.assertEqual(codes(validate(plan(affected_capabilities=["c%d" % i for i in range(17)]))),
                         [("too_many_items", "affected_capabilities")])

    def test_constraints_validation(self):
        self.assertEqual(codes(validate(plan(constraints="c"))), [("invalid_constraints", "constraints")])
        for bad in ("", " c", None, 1, "c" * 201):
            self.assertEqual(codes(validate(plan(constraints=["a", bad]))), [("invalid_item", "constraints[1]")])
        self.assertIs(validate(plan(constraints=["same", "same"]))["valid"], True)
        self.assertIs(validate(plan(constraints=[]))["valid"], True)
        self.assertEqual(codes(validate(plan(constraints=["c"] * 17))), [("too_many_items", "constraints")])


class ExecutionTests(unittest.TestCase):
    def test_execution_attempts_rejected(self):
        for bad in (True, 1, 0, "False", "", None, [], 0.0):
            self.assertEqual(codes(validate(plan(execution_allowed=bad))),
                             [("invalid_execution_allowed", "execution_allowed")], repr(bad))

    def test_request_or_state_cannot_enable_execution(self):
        req = dict(make_request(), execution_allowed=True)
        state = dict(make_state(), execution_allowed=True)
        self.assertEqual(len(build(req, make_state())["errors"]), 1)
        self.assertEqual(len(build(make_request(), state)["errors"]), 1)

    def test_results_never_allow_or_report_execution(self):
        for r in (build(make_request(), make_state()), build(None, None), validate(plan()),
                  validate(None), validate(plan(execution_allowed=True))):
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_error_list_is_capped_and_fresh(self):
        bad = plan(affected_files=[None] * 16, constraints=[None] * 16)
        r = validate(bad)
        self.assertLessEqual(len(r["errors"]), 16)
        self.assertIsNot(r["errors"], validate(bad)["errors"])
        self.assertEqual(r, validate(bad))


class BoundaryTests(unittest.TestCase):
    def test_imports_only_prompt849_850_modules(self):
        tree = ast.parse(inspect.getsource(up))
        mods = [n.module if isinstance(n, ast.ImportFrom) else a.name
                for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (getattr(n, "names", None) or [None])]
        self.assertEqual(sorted(set(mods)), ["upgrade.project_state", "upgrade.upgrade_request"])
        self._test_no_io_or_dynamic_execution()

    def _test_no_io_or_dynamic_execution(self):
        names = {n.id for n in ast.walk(ast.parse(inspect.getsource(up))) if isinstance(n, ast.Name)}
        for forbidden in ("open", "exec", "eval", "compile", "__import__", "input", "print"):
            self.assertNotIn(forbidden, names)

    def test_nothing_outside_upgrade_imports_the_plan(self):
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ("upgrade", "tests", "__pycache__")]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        self.assertNotIn("upgrade_plan", fh.read(), os.path.join(folder, name))

    def test_prompt849_850_contracts_unchanged(self):
        from upgrade import project_state, upgrade_request
        self.assertEqual(len(upgrade_request.FIELDS), 7)
        self.assertEqual(len(project_state.FIELDS), 8)


if __name__ == "__main__":
    unittest.main()
