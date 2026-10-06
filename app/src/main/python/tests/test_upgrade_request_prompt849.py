"""
Prompt 849 - self-upgrade request contract focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_upgrade_request_prompt849 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade import upgrade_request as ur
from upgrade.upgrade_request import build_upgrade_request as build
from upgrade.upgrade_request import validate_upgrade_request as validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "upgrade_request", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
NORMAL_KEYS = ["version", "request_id", "goal", "scope", "constraints", "requested_by",
               "execution_allowed"]


def req(**over):
    d = {"request_id": "upg_001", "goal": "Improve response formatting.",
         "scope": ["response_formatter"], "constraints": ["No data loss."],
         "requested_by": "developer"}
    d.update(over)
    return d


def normal(**over):
    d = dict(req(), version="1", execution_allowed=False)
    d.update(over)
    return d


def codes(result):
    return [(e["code"], e["where"]) for e in result["errors"]]


def check_shape(test, result, keys=BUILD_KEYS):
    test.assertEqual(list(result), keys)
    test.assertIs(result["execution_allowed"], False)
    test.assertIs(result["executed"], False)
    json.dumps(result)


class ValidRequestTests(unittest.TestCase):
    def test_valid_build(self):
        r = build(req())
        check_shape(self, r)
        self.assertIs(r["valid"], True)
        self.assertEqual(r["errors"], [])
        self.assertEqual(list(r["upgrade_request"]), NORMAL_KEYS)
        self.assertEqual(r["upgrade_request"], normal())

    def test_empty_lists_are_valid_stated_values(self):
        self.assertIs(build(req(scope=[], constraints=[]))["valid"], True)

    def test_validate_normalized_request(self):
        r = validate(normal())
        check_shape(self, r, VALIDATE_KEYS)
        self.assertEqual((r["valid"], r["errors"]), (True, []))


class MissingRequestTests(unittest.TestCase):
    def test_missing_request(self):
        for fn, keys in ((build, BUILD_KEYS), (validate, VALIDATE_KEYS)):
            r = fn()
            check_shape(self, r, keys)
            self.assertIs(r["valid"], False)
            self.assertEqual(codes(r), [("missing_request", "request")])
        self.assertIsNone(build()["upgrade_request"])

    def test_missing_goal(self):
        d = req()
        del d["goal"]
        r = build(d)
        self.assertEqual(codes(r), [("missing_field", "goal")])
        self.assertIsNone(r["upgrade_request"])

    def test_nothing_is_inferred_for_missing_fields(self):
        r = build({})
        self.assertEqual(codes(r), [("missing_field", f) for f in
                                    ("request_id", "goal", "scope", "constraints", "requested_by")])

    def test_validate_requires_all_seven_keys(self):
        d = normal()
        del d["version"]
        self.assertEqual(codes(validate(d)), [("missing_field", "version")])


class FieldErrorTests(unittest.TestCase):
    def test_invalid_goal(self):
        for goal in ("", " ", " x", "x ", "a\nb", None, 5, ["x"], b"x", "x" * 501):
            with self.subTest(goal=goal):
                self.assertEqual(codes(build(req(goal=goal))), [("invalid_goal", "goal")])

    def test_invalid_request_id(self):
        for rid in ("", "  ", " id", None, 7, 1.5, True, ["id"], "x" * 65, "a\tb"):
            with self.subTest(rid=rid):
                self.assertEqual(codes(build(req(request_id=rid))),
                                 [("invalid_request_id", "request_id")])

    def test_invalid_requested_by(self):
        for who in ("", " ", None, 3, {"a": 1}, "x" * 65, "bad\x00"):
            with self.subTest(who=who):
                self.assertEqual(codes(build(req(requested_by=who))),
                                 [("invalid_requested_by", "requested_by")])

    def test_invalid_scope(self):
        for scope in (None, "a", ("a",), {"a"}, {"a": 1}, 5):
            with self.subTest(scope=scope):
                self.assertEqual(codes(build(req(scope=scope))), [("invalid_scope", "scope")])
        self.assertEqual(codes(build(req(scope=["ok", "", 5]))),
                         [("invalid_item", "scope[1]"), ("invalid_item", "scope[2]")])
        self.assertEqual(codes(build(req(scope=["x"] * 17))), [("too_many_items", "scope")])

    def test_invalid_constraints(self):
        for value in (None, "a", ("a",), 0):
            with self.subTest(value=value):
                self.assertEqual(codes(build(req(constraints=value))),
                                 [("invalid_constraints", "constraints")])
        self.assertEqual(codes(build(req(constraints=[" x"]))),
                         [("invalid_item", "constraints[0]")])
        self.assertEqual(codes(build(req(constraints=["x"] * 17))),
                         [("too_many_items", "constraints")])

    def test_invalid_version(self):
        for v in (1, "2", "1.0", " 1", None, True, 1.0):
            with self.subTest(v=v):
                self.assertEqual(codes(build(req(version=v))), [("invalid_version", "version")])

    def test_unexpected_field(self):
        self.assertEqual(codes(build(req(handler="x.y"))), [("unexpected_field", "handler")])
        self.assertEqual(codes(build(dict(req(), **{"": 1}))), [("unexpected_field", "<field>")])
        self.assertEqual(codes(build(dict(req(), **{"x" * 50: 1}))),
                         [("unexpected_field", "<field>")])
        self.assertEqual(codes(build({**req(), 5: 1})), [("unexpected_field", "<field>")])


class ExecutionAllowedTests(unittest.TestCase):
    def test_true_is_rejected_not_ignored(self):
        r = build(req(execution_allowed=True))
        self.assertIs(r["valid"], False)
        self.assertEqual(codes(r), [("invalid_execution_allowed", "execution_allowed")])
        self.assertIs(r["execution_allowed"], False)
        self.assertIsNone(r["upgrade_request"])

    def test_non_false_values_rejected(self):
        for value in (True, 1, 0, "False", "false", None, [], {}):
            with self.subTest(value=value):
                self.assertEqual(codes(build(req(execution_allowed=value))),
                                 [("invalid_execution_allowed", "execution_allowed")])
                self.assertEqual(codes(validate(normal(execution_allowed=value))),
                                 [("invalid_execution_allowed", "execution_allowed")])

    def test_results_never_allow_or_execute(self):
        for result in (build(req()), build(req(execution_allowed=True)), build(), validate(normal()),
                       validate(normal(execution_allowed=True)), validate(None)):
            self.assertIs(result["execution_allowed"], False)
            self.assertIs(result["executed"], False)


class MalformedInputTests(unittest.TestCase):
    def test_non_dict_requests(self):
        class D(dict):
            pass
        for value in (1, "x", [], (), 1.5, True, D(req()), D(normal()), object()):
            with self.subTest(value=value):
                self.assertEqual(codes(build(value)), [("request_not_dict", "request")])
                self.assertEqual(codes(validate(value)), [("request_not_dict", "request")])

    def test_str_subclass_text_is_rejected(self):
        class S(str):
            pass
        self.assertEqual(codes(build(req(goal=S("goal")))), [("invalid_goal", "goal")])
        self.assertEqual(codes(build(req(version=S("1")))), [("invalid_version", "version")])

    def test_never_raises_on_hostile_objects(self):
        class Boom:
            def __getitem__(self, k):
                raise RuntimeError("boom")
            def __eq__(self, o):
                raise RuntimeError("boom")
            __hash__ = None
        for value in (Boom(), req(goal=Boom()), req(scope=[Boom()]), req(scope=Boom()),
                      normal(execution_allowed=Boom()), normal(version=Boom())):
            for fn, keys in ((build, BUILD_KEYS), (validate, VALIDATE_KEYS)):
                r = fn(value)
                self.assertEqual(list(r), keys)
                self.assertIs(r["valid"], False)
                self.assertIs(r["executed"], False)

    def test_validate_rejects_extra_and_unbuilt_shapes(self):
        self.assertEqual(codes(validate(normal(extra=1))), [("unexpected_field", "extra")])
        self.assertEqual(codes(validate(req())), [("missing_field", "version"),
                                                  ("missing_field", "execution_allowed")])


class BoundedValueTests(unittest.TestCase):
    def test_limits_are_accepted_exactly_at_the_bound(self):
        r = build(req(request_id="a" * ur.MAX_ID_LENGTH, requested_by="b" * ur.MAX_ID_LENGTH,
                      goal="g" * ur.MAX_GOAL_LENGTH,
                      scope=["s" * ur.MAX_ITEM_LENGTH] * ur.MAX_ITEMS,
                      constraints=["c" * ur.MAX_ITEM_LENGTH] * ur.MAX_ITEMS))
        self.assertIs(r["valid"], True)

    def test_limits_reject_one_past_the_bound(self):
        self.assertEqual(codes(build(req(request_id="a" * (ur.MAX_ID_LENGTH + 1)))),
                         [("invalid_request_id", "request_id")])
        self.assertEqual(codes(build(req(goal="g" * (ur.MAX_GOAL_LENGTH + 1)))),
                         [("invalid_goal", "goal")])
        self.assertEqual(codes(build(req(scope=["s" * (ur.MAX_ITEM_LENGTH + 1)]))),
                         [("invalid_item", "scope[0]")])

    def test_errors_are_bounded(self):
        r = build(req(scope=[""] * 16, constraints=[""] * 16, goal=0, request_id=0))
        self.assertLessEqual(len(r["errors"]), ur.MAX_ERRORS)
        self.assertEqual(len(r["errors"]), ur.MAX_ERRORS)

    def test_huge_inputs_are_not_scanned(self):
        self.assertEqual(codes(build(req(scope=["x"] * 100000))), [("too_many_items", "scope")])
        big = {str(i): i for i in range(10000)}
        self.assertEqual(codes(build(big)), [("too_many_fields", "request")])
        self.assertEqual(codes(validate(big)), [("too_many_fields", "request")])


class SafetyTests(unittest.TestCase):
    def test_inputs_not_modified(self):
        d = req()
        before = copy.deepcopy(d)
        build(d)
        self.assertEqual(d, before)
        n = normal()
        before = copy.deepcopy(n)
        validate(n)
        self.assertEqual(n, before)

    def test_result_is_fresh_and_not_aliased(self):
        d = req()
        a, b = build(d), build(d)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["upgrade_request"], b["upgrade_request"])
        self.assertIsNot(a["upgrade_request"]["scope"], d["scope"])
        a["upgrade_request"]["scope"].append("mutated")
        self.assertEqual(d["scope"], ["response_formatter"])
        self.assertEqual(build(d)["upgrade_request"]["scope"], ["response_formatter"])


class BoundaryTests(unittest.TestCase):
    def test_module_has_no_imports(self):
        tree = ast.parse(inspect.getsource(ur))
        self.assertEqual([n for n in ast.walk(tree)
                          if isinstance(n, (ast.Import, ast.ImportFrom))], [])

    def test_only_two_public_functions(self):
        public = [n for n, v in vars(ur).items()
                  if inspect.isfunction(v) and v.__module__ == ur.__name__ and not n.startswith("_")]
        self.assertEqual(sorted(public), ["build_upgrade_request", "validate_upgrade_request"])

    def test_not_wired_into_other_packages(self):
        needles = ("from upgrade", "import upgrade", "upgrade.upgrade_request")
        for folder in sorted(os.listdir(ROOT)):
            path = os.path.join(ROOT, folder)
            if folder in ("upgrade", "tests") or not os.path.isdir(path):
                continue
            for d, _, files in os.walk(path):
                for fn in files:
                    if fn.endswith(".py"):
                        with open(os.path.join(d, fn), encoding="utf-8") as f:
                            text = f.read()
                        for needle in needles:
                            self.assertNotIn(needle, text, os.path.join(d, fn))


if __name__ == "__main__":
    unittest.main()
