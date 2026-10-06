"""
Prompt 863 - research request contract focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_research_request_prompt863 -v
"""

import ast
import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import research_request as rr
from research.research_request import build_research_request as build
from research.research_request import validate_research_request as validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "research_request", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
NORMAL_KEYS = ["version", "request_id", "goal", "topics", "constraints", "requested_by",
               "execution_allowed"]


def req(**over):
    d = {"request_id": "res_001", "goal": "Understand retrieval-augmented generation.",
         "topics": ["rag basics", "vector stores", "evaluation"],
         "constraints": ["Peer-reviewed sources only."], "requested_by": "developer"}
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
    def test_valid_build_has_exact_normal_form(self):
        r = build(req())
        check_shape(self, r)
        self.assertEqual((r["valid"], r["errors"]), (True, []))
        self.assertEqual(list(r["research_request"]), NORMAL_KEYS)
        self.assertEqual(r["research_request"]["version"], "1")
        self.assertIs(r["research_request"]["execution_allowed"], False)

    def test_values_are_preserved_exactly_and_in_order(self):
        r = build(req(topics=["zeta", "alpha", "Alpha", "mid"]))["research_request"]
        self.assertEqual(r["topics"], ["zeta", "alpha", "Alpha", "mid"])
        self.assertEqual(r["goal"], "Understand retrieval-augmented generation.")

    def test_optional_version_and_flag_accepted_when_exact(self):
        r = build(req(version="1", execution_allowed=False))
        self.assertTrue(r["valid"])

    def test_empty_and_duplicate_constraints_are_allowed(self):
        self.assertTrue(build(req(constraints=[]))["valid"])
        r = build(req(constraints=["a", "a"]))
        self.assertEqual(r["research_request"]["constraints"], ["a", "a"])

    def test_normalized_request_validates(self):
        r = validate(normal())
        check_shape(self, r, VALIDATE_KEYS)
        self.assertEqual((r["valid"], r["errors"]), (True, []))
        self.assertTrue(validate(build(req())["research_request"])["valid"])

    def test_boundary_sizes_accepted(self):
        topics = ["t%d" % i for i in range(rr.MAX_ITEMS)]
        r = build(req(topics=topics, constraints=["c"] * rr.MAX_ITEMS,
                      request_id="x" * rr.MAX_ID_LENGTH, goal="g" * rr.MAX_GOAL_LENGTH,
                      requested_by="y" * rr.MAX_ID_LENGTH))
        self.assertTrue(r["valid"], r["errors"])
        self.assertTrue(build(req(topics=["z" * rr.MAX_ITEM_LENGTH]))["valid"])


class BuildRejectTests(unittest.TestCase):
    def test_missing_and_non_dict_request(self):
        self.assertEqual(codes(build()), [("missing_request", "request")])
        for bad in ([], "x", 1, (1,), object()):
            r = build(bad)
            check_shape(self, r)
            self.assertEqual(codes(r), [("request_not_dict", "request")])
            self.assertIsNone(r["research_request"])

    def test_missing_required_fields_are_errors_not_defaults(self):
        for key in ("request_id", "goal", "topics", "constraints", "requested_by"):
            d = req()
            del d[key]
            self.assertEqual(codes(build(d)), [("missing_field", key)])

    def test_unexpected_fields_rejected(self):
        self.assertEqual(codes(build(req(extra=1))), [("unexpected_field", "extra")])
        self.assertEqual(codes(build(req(scope=["x"]))), [("unexpected_field", "scope")])

    def test_execution_allowed_true_or_non_false_rejected(self):
        for bad in (True, 1, 0, None, "False", []):
            r = build(req(execution_allowed=bad))
            self.assertEqual(codes(r), [("invalid_execution_allowed", "execution_allowed")])
            self.assertIsNone(r["research_request"])

    def test_invalid_version_rejected(self):
        for bad in ("2", "", 1, None, "1 "):
            self.assertEqual(codes(build(req(version=bad))), [("invalid_version", "version")])

    def test_invalid_text_fields(self):
        bad_values = ("", " x", "x ", "a\nb", "a\x00b", 5, None, ["x"], "x" * 501)
        for field in ("request_id", "goal", "requested_by"):
            for bad in bad_values:
                r = build(req(**{field: bad}))
                self.assertEqual(codes(r), [("invalid_" + field, field)], (field, bad))

    def test_text_length_bounds(self):
        self.assertFalse(build(req(request_id="x" * 65))["valid"])
        self.assertFalse(build(req(requested_by="x" * 65))["valid"])
        self.assertFalse(build(req(goal="x" * 501))["valid"])
        self.assertEqual(codes(build(req(topics=["x" * 201]))), [("invalid_item", "topics[0]")])

    def test_str_subclass_rejected(self):
        class S(str):
            pass
        self.assertEqual(codes(build(req(goal=S("ok")))), [("invalid_goal", "goal")])
        self.assertEqual(codes(build(req(topics=[S("ok")]))), [("invalid_item", "topics[0]")])

    def test_topics_must_be_non_empty_list(self):
        self.assertEqual(codes(build(req(topics=[]))), [("empty_topics", "topics")])
        for bad in ("a", ("a",), {"a"}, None, 1, {"a": 1}):
            self.assertEqual(codes(build(req(topics=bad))), [("invalid_topics", "topics")])

    def test_topic_items_never_coerced(self):
        for bad in (1, None, "", " pad ", ["x"], "a\tb", True):
            self.assertEqual(codes(build(req(topics=["ok", bad]))), [("invalid_item", "topics[1]")])

    def test_duplicate_topics_rejected_exactly(self):
        r = build(req(topics=["a", "b", "a"]))
        self.assertEqual(codes(r), [("duplicate_topic", "topics[2]")])
        self.assertTrue(build(req(topics=["a", "A"]))["valid"])  # case-sensitive, no normalisation

    def test_constraints_malformed_values_rejected(self):
        for bad in ("x", None, ("a",), 1):
            self.assertEqual(codes(build(req(constraints=bad))),
                             [("invalid_constraints", "constraints")])
        for bad in (1, None, "", " x", [], "x" * 201):
            self.assertEqual(codes(build(req(constraints=["ok", bad]))),
                             [("invalid_item", "constraints[1]")])

    def test_too_many_items_rejected(self):
        topics = ["t%d" % i for i in range(rr.MAX_ITEMS + 1)]
        self.assertEqual(codes(build(req(topics=topics))), [("too_many_items", "topics")])
        self.assertEqual(codes(build(req(constraints=["c"] * 17))),
                         [("too_many_items", "constraints")])

    def test_too_many_fields_bounded(self):
        d = {"k%d" % i: i for i in range(rr.MAX_FIELDS + 1)}
        self.assertEqual(codes(build(d)), [("too_many_fields", "request")])

    def test_errors_bounded_and_ordered(self):
        r = build({"request_id": 1, "goal": 2, "topics": 3, "constraints": 4,
                   "requested_by": 5, "junk": 6})
        self.assertEqual([c for c, _ in codes(r)],
                         ["unexpected_field", "invalid_request_id", "invalid_goal",
                          "invalid_topics", "invalid_constraints", "invalid_requested_by"])
        many = build({"k%d" % i: 0 for i in range(rr.MAX_FIELDS)})
        self.assertLessEqual(len(many["errors"]), rr.MAX_ERRORS)

    def test_never_raises_on_hostile_input(self):
        class Boom(dict):
            def __len__(self):
                raise RuntimeError("boom")

        class Evil(str):
            def __eq__(self, other):
                raise RuntimeError("boom")
            __hash__ = str.__hash__
        for bad in (Boom(), {"request_id": Evil("a")}, req(topics=[Evil("a"), Evil("a")])):
            r = build(bad)
            check_shape(self, r)
            self.assertFalse(r["valid"])
            self.assertFalse(validate(bad)["valid"])


class ValidateTests(unittest.TestCase):
    def test_all_seven_fields_required(self):
        for key in NORMAL_KEYS:
            d = normal()
            del d[key]
            self.assertEqual(codes(validate(d)), [("missing_field", key)])

    def test_missing_non_dict_and_extra(self):
        self.assertEqual(codes(validate()), [("missing_request", "request")])
        self.assertEqual(codes(validate([])), [("request_not_dict", "request")])
        self.assertEqual(codes(validate(normal(extra=1))), [("unexpected_field", "extra")])

    def test_execution_flag_must_be_exactly_false(self):
        for bad in (True, 0, None, "False"):
            self.assertEqual(codes(validate(normal(execution_allowed=bad))),
                             [("invalid_execution_allowed", "execution_allowed")])

    def test_structure_rules_match_build(self):
        self.assertEqual(codes(validate(normal(topics=[]))), [("empty_topics", "topics")])
        self.assertEqual(codes(validate(normal(topics=["a", "a"]))),
                         [("duplicate_topic", "topics[1]")])
        self.assertEqual(codes(validate(normal(version="2"))), [("invalid_version", "version")])
        self.assertEqual(codes(validate(normal(goal=""))), [("invalid_goal", "goal")])

    def test_validation_never_repairs_or_mutates(self):
        bad = normal(topics=["a", "a"], goal=" padded ")
        snap = copy.deepcopy(bad)
        r = validate(bad)
        self.assertFalse(r["valid"])
        self.assertEqual(bad, snap)


class IsolationTests(unittest.TestCase):
    def test_build_never_mutates_input_and_returns_fresh_structures(self):
        src = req()
        snap = copy.deepcopy(src)
        a, b = build(src), build(src)
        self.assertEqual(src, snap)
        self.assertEqual(a, b)
        self.assertIsNot(a["research_request"], b["research_request"])
        for key in ("topics", "constraints"):
            self.assertIsNot(a["research_request"][key], src[key])
            self.assertIsNot(a["research_request"][key], b["research_request"][key])
        a["research_request"]["topics"].append("mutated")
        self.assertEqual(src, snap)

    def test_no_forbidden_imports_or_calls(self):
        with open(os.path.join(ROOT, "research", "research_request.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            self.assertNotIsInstance(node, (ast.Import, ast.ImportFrom))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__"})

    def test_public_api_and_version_constant(self):
        public = sorted(n for n in dir(rr) if not n.startswith("_") and callable(getattr(rr, n)))
        self.assertEqual(public, ["build_research_request", "validate_research_request"])
        self.assertEqual(rr.REQUEST_VERSION, "1")



if __name__ == "__main__":
    unittest.main()
