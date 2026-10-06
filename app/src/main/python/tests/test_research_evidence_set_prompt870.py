"""
Prompt 870 - research evidence set focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_research_evidence_set_prompt870 -v
"""

import ast
import builtins
import copy
import json
import os
import socket
import subprocess
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import research_evidence_set as m
from research.research_evidence import build_research_evidence
from research.research_evidence_set import build_research_evidence_set as build
from research.research_evidence_set import validate_research_evidence_set as validate
from research.research_request import build_research_request
from research.research_source import build_research_source

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "evidence_set", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
SET_KEYS = ["version", "request_id", "source_id", "evidence", "count", "execution_allowed"]


def request(constraints=(), rid="res_001"):
    r = build_research_request({
        "request_id": rid, "goal": "Understand retrieval-augmented generation.",
        "topics": ["rag basics"], "constraints": list(constraints), "requested_by": "developer"})
    assert r["valid"], r["errors"]
    return r["research_request"]


def source(sid="src_1", stype="local_file", trust="standard", enabled=True):
    r = build_research_source({
        "source_id": sid, "source_type": stype, "location": "loc/" + sid, "trust_level": trust,
        "constraints": [], "enabled": enabled})
    assert r["valid"], r["errors"]
    return r["source"]


def ev(eid="ev_001", sid="src_1", **over):
    d = {"evidence_id": eid, "source_id": sid, "claim": "Claim for " + eid,
         "evidence_type": "fact", "confidence": 0.8, "constraints": []}
    d.update(over)
    r = build_research_evidence(d)
    assert r["valid"], r["errors"]
    return r["evidence"]


def items(n, sid="src_1"):
    return [ev("ev_%03d" % i, sid) for i in range(n)]


def good_set(n=2):
    r = build(request(), source(), items(n))
    assert r["valid"], r["errors"]
    return r["evidence_set"]


def codes(result):
    return [e["code"] for e in result["errors"]]


def check_build_shape(test, r):
    test.assertEqual(list(r), BUILD_KEYS)
    test.assertIs(r["execution_allowed"], False)
    test.assertIs(r["executed"], False)
    json.dumps(r)
    if r["valid"]:
        test.assertEqual(validate(r["evidence_set"])["errors"], [])
    else:
        test.assertIsNone(r["evidence_set"])


class ValidBuildTests(unittest.TestCase):
    def test_valid_single_evidence(self):
        r = build(request(), source(), [ev()])
        check_build_shape(self, r)
        self.assertEqual((r["valid"], r["errors"]), (True, []))
        s = r["evidence_set"]
        self.assertEqual(list(s), SET_KEYS)
        self.assertEqual(s, {"version": "1", "request_id": "res_001", "source_id": "src_1",
                             "evidence": [ev()], "count": 1, "execution_allowed": False})

    def test_multiple_items_order_preserved_exactly(self):
        order = ["z", "a", "m", "b", "y"]
        r = build(request(), source(), [ev(e) for e in order])
        check_build_shape(self, r)
        self.assertEqual([e["evidence_id"] for e in r["evidence_set"]["evidence"]], order)

        a = ev("b", claim="same claim", confidence=0.1)
        b = ev("a", claim="same claim", confidence=0.9, evidence_type="observation")
        s = build(request(), source(), [a, b])["evidence_set"]
        self.assertEqual(s["evidence"], [a, b])
        self.assertEqual(s["count"], 2)

    def test_count_equals_length(self):
        for n in (1, 2, 5, 63, 64):
            s = build(request(), source(), items(n))["evidence_set"]
            self.assertEqual((s["count"], len(s["evidence"])), (n, n))

    def test_request_and_source_ids_preserved_exactly(self):
        s = build(request(rid="Request-7"), source("Src.A"), [ev("e", "Src.A")])["evidence_set"]
        self.assertEqual((s["request_id"], s["source_id"]), ("Request-7", "Src.A"))

    def test_all_evidence_types_and_confidence_bounds_kept(self):
        its = [ev("a", evidence_type="fact", confidence=0.0),
               ev("b", evidence_type="observation", confidence=1.0),
               ev("c", evidence_type="user_statement"), ev("d", evidence_type="learned_record")]
        self.assertEqual(build(request(), source(), its)["evidence_set"]["evidence"], its)

    def test_compatible_constraints_accepted(self):
        r = build(request(["source_type:local_file", "min_trust:standard"]), source(), items(3))
        self.assertTrue(r["valid"], r["errors"])

    def test_result_contains_fresh_copies(self):
        its = [ev("a")]
        s = build(request(), source(), its)["evidence_set"]
        self.assertIsNot(s["evidence"][0], its[0])
        self.assertIsNot(s["evidence"][0]["constraints"], its[0]["constraints"])
        its[0]["claim"] = "changed"
        its[0]["constraints"].append("x")
        its.append(ev("b"))
        self.assertEqual(s["evidence"], [ev("a")])
        self.assertEqual(s["count"], 1)

    def test_deterministic_and_fresh(self):
        args = (request(), source(), items(3))
        a, b = build(*args), build(*args)
        self.assertEqual(a, b)
        self.assertIsNot(a["evidence_set"], b["evidence_set"])


class FailureTests(unittest.TestCase):
    def test_invalid_request(self):
        for bad in (None, {}, [], "x", 5, True):
            r = build(bad, source(), [ev()])
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "invalid_request", "where": "research_request"}])
        d = request(); d["execution_allowed"] = True
        self.assertEqual(codes(build(d, source(), [ev()])), ["invalid_request"])

    def test_invalid_source(self):
        for bad in (None, {}, [], "x", 5):
            r = build(request(), bad, [ev()])
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "invalid_source", "where": "source"}])
        d = source(); d["trust_level"] = "super"
        self.assertEqual(codes(build(request(), d, [ev()])), ["invalid_source"])

    def test_request_checked_before_source_before_evidence(self):
        self.assertEqual(codes(build(None, None, None)), ["invalid_request"])
        self.assertEqual(codes(build(request(), None, None)), ["invalid_source"])
        self.assertEqual(codes(build(request(), source(), None)), ["invalid_evidence_set"])
        self.assertEqual(codes(build()), ["invalid_request"])

    def test_non_list_evidence_collection(self):
        for bad in (None, {}, "x", 5, (ev(),), {"a": ev()}, ev(), iter([ev()]), True):
            r = build(request(), source(), bad)
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "invalid_evidence_set", "where": "evidence_items"}])

    def test_empty_list_rejected(self):
        r = build(request(), source(), [])
        self.assertEqual(r["errors"], [{"code": "invalid_evidence_set", "where": "evidence_items"}])

    def test_invalid_evidence_items(self):
        for bad in (None, {}, [], "x", 5, True, dict(ev(), confidence=True),
                    dict(ev(), confidence=float("nan")), dict(ev(), evidence_type="opinion"),
                    dict(ev(), execution_allowed=True), dict(ev(), extra=1)):
            r = build(request(), source(), [ev("ok"), bad])
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "invalid_evidence", "where": "evidence_items[1]"}])

    def test_raw_unnormalized_evidence_is_not_repaired(self):
        raw = {"evidence_id": "e", "source_id": "src_1", "claim": "c", "evidence_type": "fact",
               "confidence": 0.5, "constraints": []}
        r = build(request(), source(), [raw])
        self.assertEqual(codes(r), ["invalid_evidence"])
        self.assertNotIn("version", raw)

    def test_every_failing_item_reported_in_order(self):
        r = build(request(), source(), [ev("a"), None, ev("a"), {}, ev("b"), ev("b")])
        self.assertEqual(r["errors"], [
            {"code": "invalid_evidence", "where": "evidence_items[1]"},
            {"code": "duplicate_evidence", "where": "evidence_items[2]"},
            {"code": "invalid_evidence", "where": "evidence_items[3]"},
            {"code": "duplicate_evidence", "where": "evidence_items[5]"}])

    def test_duplicate_evidence_ids(self):
        r = build(request(), source(), [ev("a"), ev("b"), ev("a", claim="different claim")])
        check_build_shape(self, r)
        self.assertEqual(r["errors"], [{"code": "duplicate_evidence", "where": "evidence_items[2]"}])
        self.assertEqual(codes(build(request(), source(), [ev("a"), ev("a")])), ["duplicate_evidence"])
        self.assertTrue(build(request(), source(), [ev("a"), ev("A")])["valid"])  # exact comparison

        e = ev("a")
        self.assertEqual(codes(build(request(), source(), [e, e])), ["duplicate_evidence"])

    def test_evidence_limit(self):
        r = build(request(), source(), items(65))
        check_build_shape(self, r)
        self.assertEqual(r["errors"], [{"code": "evidence_limit_exceeded", "where": "evidence_items"}])
        self.assertEqual(m.MAX_EVIDENCE, 64)
        self.assertTrue(build(request(), source(), items(64))["valid"])

        r = build(request(), source(), [None] * 65)
        self.assertEqual(codes(r), ["evidence_limit_exceeded"])
        with mock.patch.object(m, "validate_research_evidence_for_context") as ctx:
            build(request(), source(), [ev()] * 65)
        ctx.assert_not_called()

    def test_source_mismatch(self):
        r = build(request(), source("src_1"), [ev("a", "src_1"), ev("b", "src_2")])
        check_build_shape(self, r)
        self.assertEqual(r["errors"], [{"code": "invalid_evidence", "where": "evidence_items[1]"}])

    def test_disabled_source(self):
        r = build(request(), source(enabled=False), [ev("a"), ev("b")])
        check_build_shape(self, r)
        self.assertEqual(codes(r), ["invalid_evidence", "invalid_evidence"])

    def test_incompatible_source_type_and_trust(self):
        self.assertEqual(codes(build(request(["source_type:web"]), source(), [ev()])),
                         ["invalid_evidence"])
        self.assertEqual(codes(build(request(["not:source_type:local_file"]), source(), [ev()])),
                         ["invalid_evidence"])
        self.assertEqual(codes(build(request(["min_trust:trusted"]), source(), [ev()])),
                         ["invalid_evidence"])

    def test_malformed_constraint_is_a_request_error(self):
        for c in ("source_type:ftp", "min_trust:high"):
            r = build(request([c]), source(), [ev(), ev("b")])
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "invalid_request", "where": "research_request"}])

    def test_internal_failure_is_build_error(self):
        for name in ("validate_research_request", "validate_research_source",
                     "validate_research_evidence_for_context"):
            with mock.patch.object(m, name, side_effect=RuntimeError("x")):
                r = build(request(), source(), [ev()])
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "build_error", "where": "evidence_set"}], name)
        with mock.patch.object(m, "validate_research_evidence_for_context",
                               return_value={"status": "validation_error", "valid": False}):
            self.assertEqual(codes(build(request(), source(), [ev()])), ["build_error"])

    def test_errors_are_bounded(self):
        r = build(request(), source(), [None] * 64)
        self.assertEqual(len(r["errors"]), m.MAX_ERRORS)


class ImmutabilityTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        cases = [(request(["min_trust:standard"]), source(), items(3)),
                 (request(), source(), [ev("a"), ev("a"), None]),
                 (request(), source(enabled=False), items(2)),
                 (request(["min_trust:x"]), source(), items(2)),
                 (request(), source(), items(65)), ({}, {}, {}), (request(), source(), [])]
        for args in cases:
            before = copy.deepcopy(args)
            build(*args)
            self.assertEqual(args, before)

        lst = [ev("c"), ev("a"), ev("b")]
        before = [e["evidence_id"] for e in lst]
        build(request(), source(), lst)
        self.assertEqual([e["evidence_id"] for e in lst], before)


class ValidatorTests(unittest.TestCase):
    def test_validate_good_set_shape_and_flags(self):
        v = validate(good_set())
        self.assertEqual(list(v), VALIDATE_KEYS)
        self.assertEqual((v["valid"], v["errors"]), (True, []))
        self.assertIs(v["execution_allowed"], False)
        self.assertIs(v["executed"], False)
        self.assertTrue(validate(good_set(1))["valid"])
        self.assertTrue(validate(good_set(64))["valid"])

    def test_malformed_set(self):
        self.assertEqual(validate()["errors"], [{"code": "missing_set", "where": "evidence_set"}])
        for bad in ([], "x", 3, True, (), [good_set()]):
            self.assertEqual(validate(bad)["errors"], [{"code": "set_not_dict", "where": "evidence_set"}])
        self.assertEqual(validate({})["errors"][0], {"code": "missing_field", "where": "version"})
        big = {str(i): i for i in range(17)}
        self.assertEqual(validate(big)["errors"], [{"code": "too_many_fields", "where": "evidence_set"}])
        for key in SET_KEYS:
            s = good_set(); del s[key]
            self.assertEqual(validate(s)["errors"], [{"code": "missing_field", "where": key}])
        s = good_set(); s["extra"] = 1
        self.assertEqual(validate(s)["errors"], [{"code": "unexpected_field", "where": "extra"}])
        s = good_set(); s["executed"] = False
        self.assertEqual(validate(s)["errors"], [{"code": "unexpected_field", "where": "executed"}])

    def test_rejects_bad_scalar_fields(self):
        for key, bad, code in (("version", "2", "invalid_version"), ("version", 1, "invalid_version"),
                               ("request_id", "", "invalid_request_id"),
                               ("request_id", " a", "invalid_request_id"),
                               ("request_id", None, "invalid_request_id"),
                               ("source_id", "x" * 65, "invalid_source_id"),
                               ("source_id", 5, "invalid_source_id"),
                               ("execution_allowed", True, "invalid_execution_allowed"),
                               ("execution_allowed", 0, "invalid_execution_allowed")):
            s = good_set(); s[key] = bad
            self.assertIn(code, codes(validate(s)), (key, bad))

    def test_rejects_wrong_count(self):
        for bad in (0, 1, 3, -1, True, 2.0, "2", None):
            s = good_set(2); s["count"] = bad
            self.assertEqual(codes(validate(s)), ["invalid_count"], repr(bad))

    def test_rejects_bad_evidence_collection(self):
        for bad in (None, {}, "x", (), 5):
            s = good_set(); s["evidence"] = bad
            self.assertIn("invalid_evidence_set", codes(validate(s)))
        s = good_set(); s["evidence"] = []; s["count"] = 0
        self.assertEqual(codes(validate(s)), ["invalid_evidence_set"])
        s = good_set(); s["evidence"] = items(65); s["count"] = 65
        self.assertEqual(codes(validate(s)), ["evidence_limit_exceeded"])

    def test_rejects_bad_items_duplicates_and_foreign_source(self):
        s = good_set(3); s["evidence"][1]["confidence"] = True
        self.assertEqual(validate(s)["errors"], [{"code": "invalid_evidence", "where": "evidence[1]"}])
        s = good_set(3); s["evidence"][2] = None
        self.assertEqual(codes(validate(s)), ["invalid_evidence"])
        s = good_set(3); s["evidence"][2]["evidence_id"] = s["evidence"][0]["evidence_id"]
        self.assertEqual(validate(s)["errors"], [{"code": "duplicate_evidence", "where": "evidence[2]"}])
        s = good_set(3); s["evidence"][1] = ev("other", "src_2")
        self.assertEqual(validate(s)["errors"], [{"code": "inconsistent_set", "where": "evidence[1]"}])
        s = good_set(2); s["evidence"][0]["execution_allowed"] = True
        self.assertEqual(codes(validate(s)), ["invalid_evidence"])

    def test_validate_does_not_reorder_mutate_or_raise(self):
        s = good_set(3); s["evidence"].reverse()
        before = copy.deepcopy(s)
        self.assertTrue(validate(s)["valid"])  # order is the caller's, never enforced or changed
        self.assertEqual(s, before)
        s["evidence"] = [object()]; s["count"] = 1
        self.assertFalse(validate(s)["valid"])
        with mock.patch.object(m, "validate_research_evidence", side_effect=RuntimeError):
            self.assertEqual(validate(good_set())["errors"],
                             [{"code": "validation_error", "where": "evidence_set"}])

        s = good_set(); s["count"] = 9
        self.assertEqual(validate(s), validate(s))
        self.assertIsNot(validate(s), validate(s))


class IsolationTests(unittest.TestCase):
    def test_no_io_subprocess_or_network(self):
        def forbidden(*a, **k):
            raise AssertionError("forbidden call")
        args = (request(["source_type:local_file", "min_trust:standard"]), source(), items(3))
        with mock.patch.object(builtins, "open", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(os, "stat", forbidden):
            r = build(*args)
            validate(r["evidence_set"])
            build()
        self.assertTrue(r["valid"])

    def test_source_imports_and_public_api(self):
        with open(os.path.join(ROOT, "research", "research_evidence_set.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual(sorted(n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)),
                         ["research.research_evidence", "research.research_evidence_validation",
                          "research.research_request", "research.research_source"])
        self.assertEqual([a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names],
                         ["copy"])
        public = sorted(n.name for n in tree.body
                        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"))
        self.assertEqual(public, ["build_research_evidence_set", "validate_research_evidence_set"])

    def test_no_ranking_merging_or_constraint_parsing(self):
        with open(os.path.join(ROOT, "research", "research_evidence_set.py"), encoding="utf-8") as fh:
            code = fh.read().split('"""')[2]
        for token in ("sorted(", ".sort(", "startswith", "split(", "max(", "min(", "claim", "confidence"):
            self.assertNotIn(token, code, token)


if __name__ == "__main__":
    unittest.main()
