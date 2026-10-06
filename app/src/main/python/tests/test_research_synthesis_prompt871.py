"""
Prompt 871 - research synthesis contract focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_research_synthesis_prompt871 -v
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

from research import research_synthesis as m
from research.research_evidence import build_research_evidence
from research.research_evidence_set import build_research_evidence_set
from research.research_request import build_research_request
from research.research_source import build_research_source
from research.research_synthesis import build_research_synthesis as build
from research.research_synthesis import validate_research_synthesis as validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "synthesis", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
SYN_KEYS = ["version", "synthesis_id", "request_id", "source_id", "evidence_ids",
            "evidence_count", "claims", "execution_allowed"]


def request(rid="res_001"):
    r = build_research_request({
        "request_id": rid, "goal": "Understand retrieval-augmented generation.",
        "topics": ["rag basics"], "constraints": [], "requested_by": "developer"})
    assert r["valid"], r["errors"]
    return r["research_request"]


def source(sid="src_1"):
    r = build_research_source({
        "source_id": sid, "source_type": "local_file", "location": "loc/" + sid,
        "trust_level": "standard", "constraints": [], "enabled": True})
    assert r["valid"], r["errors"]
    return r["source"]


def ev(eid, claim=None, sid="src_1"):
    r = build_research_evidence({
        "evidence_id": eid, "source_id": sid, "claim": claim or "Claim " + eid,
        "evidence_type": "fact", "confidence": 0.5, "constraints": []})
    assert r["valid"], r["errors"]
    return r["evidence"]


def eset(evidence=None, rid="res_001", sid="src_1"):
    evidence = evidence if evidence is not None else [ev("e1")]
    r = build_research_evidence_set(request(rid), source(sid), evidence)
    assert r["valid"], r["errors"]
    return r["evidence_set"]


def good(n=2, sid="syn_1"):
    r = build(request(), eset([ev("e%d" % i) for i in range(n)]), sid)
    assert r["valid"], r["errors"]
    return r["synthesis"]


def codes(result):
    return [e["code"] for e in result["errors"]]


def check_build_shape(test, r):
    test.assertEqual(list(r), BUILD_KEYS)
    test.assertIs(r["execution_allowed"], False)
    test.assertIs(r["executed"], False)
    json.dumps(r)
    if r["valid"]:
        test.assertEqual(validate(r["synthesis"])["errors"], [])
    else:
        test.assertIsNone(r["synthesis"])


class ValidBuildTests(unittest.TestCase):
    def test_valid_synthesis(self):
        r = build(request(), eset([ev("e1", "First claim."), ev("e2", "Second claim.")]), "syn_1")
        check_build_shape(self, r)
        self.assertEqual((r["valid"], r["errors"]), (True, []))
        s = r["synthesis"]
        self.assertEqual(list(s), SYN_KEYS)
        self.assertEqual(s, {"version": "1", "synthesis_id": "syn_1", "request_id": "res_001",
                             "source_id": "src_1", "evidence_ids": ["e1", "e2"],
                             "evidence_count": 2, "claims": ["First claim.", "Second claim."],
                             "execution_allowed": False})

    def test_single_evidence_item(self):
        s = build(request(), eset([ev("only", "One claim.")]), "syn_1")["synthesis"]
        self.assertEqual((s["evidence_ids"], s["claims"], s["evidence_count"]),
                         (["only"], ["One claim."], 1))

    def test_multiple_items_and_count(self):
        for n in (2, 5, 64):
            s = good(n)
            self.assertEqual((s["evidence_count"], len(s["evidence_ids"]), len(s["claims"])),
                             (n, n, n))

    def test_order_preserved_not_sorted(self):
        order = ["z", "a", "m", "b"]
        s = build(request(), eset([ev(e, "claim " + e) for e in order]), "s")["synthesis"]
        self.assertEqual(s["evidence_ids"], order)
        self.assertEqual(s["claims"], ["claim " + e for e in order])

    def test_ids_and_claims_correspond_one_to_one(self):
        s = good(4)
        self.assertEqual(s["claims"], ["Claim " + i for i in s["evidence_ids"]])

    def test_claims_kept_verbatim_duplicates_and_all(self):
        claims = ["Same claim.", "Same claim.", "Another, different claim.",
                  "UPPER and lower", "x" * 500]
        s = build(request(), eset([ev("e%d" % i, c) for i, c in enumerate(claims)]), "s")["synthesis"]
        self.assertEqual(s["claims"], claims)  # no dedupe, rewrite, merge or ranking

    def test_request_and_source_ids_preserved(self):
        s = build(request("Req-9"), eset(rid="Req-9", sid="Src.Z", evidence=[ev("e", sid="Src.Z")]),
                  "Syn-1")["synthesis"]
        self.assertEqual((s["request_id"], s["source_id"], s["synthesis_id"]),
                         ("Req-9", "Src.Z", "Syn-1"))

    def test_fresh_and_deterministic(self):
        args = (request(), eset([ev("a"), ev("b")]), "s")
        a, b = build(*args), build(*args)
        self.assertEqual(a, b)
        self.assertIsNot(a["synthesis"], b["synthesis"])
        self.assertIsNot(a["synthesis"]["claims"], b["synthesis"]["claims"])

    def test_synthesis_independent_of_inputs(self):
        es = eset([ev("a")])
        s = build(request(), es, "s")["synthesis"]
        es["evidence"][0]["claim"] = "changed"
        es["evidence"].append(ev("b"))
        self.assertEqual((s["claims"], s["evidence_ids"]), (["Claim a"], ["a"]))
        s["claims"].append("x")
        self.assertEqual(len(es["evidence"]), 2)


class FailureTests(unittest.TestCase):
    def test_invalid_request(self):
        for bad in (None, {}, [], "x", 5, True):
            r = build(bad, eset(), "s")
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "invalid_request", "where": "research_request"}])
        d = request(); d["execution_allowed"] = True
        self.assertEqual(codes(build(d, eset(), "s")), ["invalid_request"])

    def test_invalid_evidence_set(self):
        good_set = eset([ev("a"), ev("b")])
        bad = [None, {}, [], "x", 5, True]
        d = copy.deepcopy(good_set); d["count"] = 5; bad.append(d)
        d = copy.deepcopy(good_set); d["version"] = "2"; bad.append(d)
        d = copy.deepcopy(good_set); d["evidence"][1]["confidence"] = True; bad.append(d)
        d = copy.deepcopy(good_set); d["evidence"][1]["evidence_id"] = "a"; bad.append(d)
        d = copy.deepcopy(good_set); d["execution_allowed"] = True; bad.append(d)
        for value in bad:
            r = build(request(), value, "s")
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "invalid_evidence_set", "where": "evidence_set"}])

    def test_empty_evidence_rejected(self):
        d = eset(); d["evidence"] = []; d["count"] = 0
        r = build(request(), d, "s")
        self.assertEqual(codes(r), ["invalid_evidence_set"])
        check_build_shape(self, r)

    def test_request_id_mismatch(self):
        r = build(request("res_001"), eset(rid="res_002"), "s")
        check_build_shape(self, r)
        self.assertEqual(r["errors"], [{"code": "request_mismatch", "where": "evidence_set"}])
        self.assertEqual(codes(build(request("res_001"), eset(rid="RES_001"), "s")), ["request_mismatch"])

    def test_missing_synthesis_id(self):
        r = build(request(), eset())
        check_build_shape(self, r)
        self.assertEqual(r["errors"], [{"code": "missing_synthesis_id", "where": "synthesis_id"}])
        self.assertEqual(codes(build(request(), eset(), None)), ["missing_synthesis_id"])
        self.assertEqual(codes(build(request(), eset(), synthesis_id=None)), ["missing_synthesis_id"])

    def test_invalid_synthesis_id(self):
        for bad in ("", " ", " a", "a ", "a\nb", "x" * 65, 5, True, [], ["a"], {}, b"a"):
            r = build(request(), eset(), bad)
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "invalid_synthesis_id", "where": "synthesis_id"}],
                             repr(bad))
        self.assertTrue(build(request(), eset(), "x" * 64)["valid"])

    def test_synthesis_id_is_never_generated(self):
        self.assertIsNone(build(request(), eset())["synthesis"])

    def test_failure_order(self):
        self.assertEqual(codes(build()), ["invalid_request"])
        self.assertEqual(codes(build(request())), ["invalid_evidence_set"])
        self.assertEqual(codes(build(request("a"), eset(rid="b"))), ["request_mismatch"])
        self.assertEqual(codes(build(request("a"), eset(rid="b"), "")), ["request_mismatch"])
        self.assertEqual(codes(build(request(), eset())), ["missing_synthesis_id"])

    def test_internal_failure_is_build_error(self):
        for name in ("validate_research_request", "validate_research_evidence_set"):
            with mock.patch.object(m, name, side_effect=RuntimeError("x")):
                r = build(request(), eset(), "s")
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "build_error", "where": "synthesis"}], name)


class ImmutabilityTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        es_bad = eset(); es_bad["count"] = 9
        cases = [(request(), eset([ev("b"), ev("a")]), "s"), (request(), eset(), None),
                 (request(), eset(), ""), (request("x"), eset(), "s"), (request(), es_bad, "s"),
                 ({}, {}, {})]
        for args in cases:
            before = copy.deepcopy(args)
            build(*args)
            self.assertEqual(args, before)

    def test_evidence_records_and_order_untouched(self):
        es = eset([ev("c"), ev("a"), ev("b")])
        before = copy.deepcopy(es)
        build(request(), es, "s")
        self.assertEqual(es, before)
        self.assertEqual([e["evidence_id"] for e in es["evidence"]], ["c", "a", "b"])


class ValidatorTests(unittest.TestCase):
    def test_validate_good_shape_and_flags(self):
        v = validate(good())
        self.assertEqual(list(v), VALIDATE_KEYS)
        self.assertEqual((v["valid"], v["errors"]), (True, []))
        self.assertIs(v["execution_allowed"], False)
        self.assertIs(v["executed"], False)
        for n in (1, 64):
            self.assertTrue(validate(good(n))["valid"])

    def test_malformed_synthesis(self):
        self.assertEqual(validate()["errors"], [{"code": "missing_synthesis", "where": "synthesis"}])
        for bad in ([], "x", 3, True, (), [good()]):
            self.assertEqual(validate(bad)["errors"],
                             [{"code": "synthesis_not_dict", "where": "synthesis"}])
        self.assertEqual(validate({})["errors"][0], {"code": "missing_field", "where": "version"})
        big = {str(i): i for i in range(17)}
        self.assertEqual(validate(big)["errors"], [{"code": "too_many_fields", "where": "synthesis"}])
        for key in SYN_KEYS:
            s = good(); del s[key]
            self.assertEqual(validate(s)["errors"], [{"code": "missing_field", "where": key}])
        for extra in ("extra", "executed", "summary", "evidence"):
            s = good(); s[extra] = 1
            self.assertEqual(validate(s)["errors"], [{"code": "unexpected_field", "where": extra}])

    def test_rejects_bad_scalar_fields(self):
        for key, bad, code in (("version", "2", "invalid_version"), ("version", 1, "invalid_version"),
                               ("synthesis_id", "", "invalid_synthesis_id"),
                               ("synthesis_id", None, "invalid_synthesis_id"),
                               ("request_id", " a", "invalid_request_id"),
                               ("request_id", 5, "invalid_request_id"),
                               ("source_id", "x" * 65, "invalid_source_id"),
                               ("source_id", None, "invalid_source_id")):
            s = good(); s[key] = bad
            self.assertEqual(codes(validate(s)), [code], (key, bad))

    def test_rejects_wrong_count(self):
        for bad in (0, 1, 3, -1, True, 2.0, "2", None):
            s = good(2); s["evidence_count"] = bad
            self.assertEqual(codes(validate(s)), ["invalid_evidence_count"], repr(bad))

    def test_rejects_empty_and_bad_evidence_ids(self):
        s = good(); s["evidence_ids"] = []; s["claims"] = []; s["evidence_count"] = 0
        self.assertEqual(codes(validate(s)), ["empty_evidence"])
        for bad in (None, {}, "x", (), 5):
            s = good(); s["evidence_ids"] = bad
            self.assertIn("invalid_evidence_ids", codes(validate(s)))
        for bad in ("", " a", "a ", None, 5, "x" * 65, ["a"]):
            s = good(3); s["evidence_ids"][1] = bad
            self.assertEqual(validate(s)["errors"],
                             [{"code": "invalid_evidence_id", "where": "evidence_ids[1]"}], repr(bad))
        s = good(3); s["evidence_ids"][2] = s["evidence_ids"][0]
        self.assertEqual(validate(s)["errors"],
                         [{"code": "duplicate_evidence_id", "where": "evidence_ids[2]"}])

    def test_rejects_malformed_claims(self):
        for bad in (None, {}, "x", (), 5):
            s = good(); s["claims"] = bad
            self.assertIn("invalid_claims", codes(validate(s)))
        for bad in ("", " a", "a ", "a\tb", None, 5, "x" * 501, ["a"]):
            s = good(3); s["claims"][1] = bad
            self.assertEqual(validate(s)["errors"],
                             [{"code": "invalid_claim", "where": "claims[1]"}], repr(bad))

    def test_rejects_length_mismatch_and_limit(self):
        s = good(3); s["claims"].pop()
        self.assertEqual(codes(validate(s)), ["length_mismatch"])
        s = good(3); s["claims"].append("extra claim")
        self.assertEqual(codes(validate(s)), ["length_mismatch"])
        s = good(3); s["claims"] = []
        self.assertEqual(codes(validate(s)), ["length_mismatch"])
        s = good(2); s["evidence_ids"] = ["e%d" % i for i in range(65)]; s["evidence_count"] = 65
        self.assertIn("evidence_limit_exceeded", codes(validate(s)))
        s = good(2); s["claims"] = ["c"] * 65
        self.assertIn("evidence_limit_exceeded", codes(validate(s)))

    def test_one_to_one_correspondence_is_positional_only(self):
        s = good(3)
        s["claims"].reverse()  # still one claim per id: the validator cannot (and does not) reorder
        self.assertTrue(validate(s)["valid"])

    def test_rejects_true_execution_flag(self):
        for bad in (True, 1, 0, None, "False"):
            s = good(); s["execution_allowed"] = bad
            v = validate(s)
            self.assertEqual(codes(v), ["invalid_execution_allowed"], repr(bad))
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)

    def test_validate_never_mutates_or_raises_and_is_deterministic(self):
        s = good(); before = copy.deepcopy(s)
        validate(s)
        self.assertEqual(s, before)
        s["claims"] = [object(), object()]
        self.assertFalse(validate(s)["valid"])
        s["evidence_count"] = 7
        self.assertEqual(validate(s), validate(s))
        self.assertIsNot(validate(s), validate(s))
        with mock.patch.object(m, "_check_lists", side_effect=RuntimeError):
            self.assertEqual(validate(good())["errors"],
                             [{"code": "validation_error", "where": "synthesis"}])


class IsolationTests(unittest.TestCase):
    def test_no_io_subprocess_or_network(self):
        def forbidden(*a, **k):
            raise AssertionError("forbidden call")
        args = (request(), eset([ev("a"), ev("b")]), "s")
        with mock.patch.object(builtins, "open", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(os, "stat", forbidden):
            r = build(*args)
            validate(r["synthesis"])
            build()
        self.assertTrue(r["valid"])

    def test_source_imports_and_public_api(self):
        with open(os.path.join(ROOT, "research", "research_synthesis.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual(sorted(n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)),
                         ["research.research_evidence", "research.research_evidence_set",
                          "research.research_request", "research.research_source"])
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Import)])
        public = sorted(n.name for n in tree.body
                        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"))
        self.assertEqual(public, ["build_research_synthesis", "validate_research_synthesis"])

    def test_no_ranking_rewriting_or_generation(self):
        with open(os.path.join(ROOT, "research", "research_synthesis.py"), encoding="utf-8") as fh:
            code = fh.read().split('"""')[2]
        for token in ("sorted(", ".sort(", "set(claims", "lower(", "upper(", "join(", "format(",
                      "uuid", "random", "time", "startswith", "split("):
            self.assertNotIn(token, code, token)


if __name__ == "__main__":
    unittest.main()
