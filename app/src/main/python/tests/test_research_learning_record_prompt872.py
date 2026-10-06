"""
Prompt 872 - research learning record contract focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_research_learning_record_prompt872 -v
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

from research import research_learning_record as m
from research.research_evidence import build_research_evidence
from research.research_evidence_set import build_research_evidence_set
from research.research_learning_record import build_research_learning_record as build
from research.research_learning_record import validate_research_learning_record as validate
from research.research_request import build_research_request
from research.research_source import build_research_source
from research.research_synthesis import build_research_synthesis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "learning_record", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
REC_KEYS = ["version", "learning_record_id", "request_id", "synthesis_id", "source_id",
            "claims", "evidence_count", "status", "execution_allowed"]


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


def synth(claims=None, rid="res_001", sid="src_1", syn_id="syn_1"):
    claims = claims if claims is not None else ["Claim one."]
    evidence = [ev("e%d" % i, c, sid) for i, c in enumerate(claims)]
    es = build_research_evidence_set(request(rid), source(sid), evidence)
    assert es["valid"], es["errors"]
    r = build_research_synthesis(request(rid), es["evidence_set"], syn_id)
    assert r["valid"], r["errors"]
    return r["synthesis"]


def good(n=2, lid="lr_1"):
    r = build(request(), synth(["Claim %d" % i for i in range(n)]), lid)
    assert r["valid"], r["errors"]
    return r["learning_record"]


def codes(result):
    return [e["code"] for e in result["errors"]]


def check_build_shape(test, r):
    test.assertEqual(list(r), BUILD_KEYS)
    test.assertIs(r["execution_allowed"], False)
    test.assertIs(r["executed"], False)
    json.dumps(r)
    if r["valid"]:
        test.assertEqual(validate(r["learning_record"])["errors"], [])
    else:
        test.assertIsNone(r["learning_record"])


class ValidBuildTests(unittest.TestCase):
    def test_valid_learning_record(self):
        r = build(request(), synth(["First claim.", "Second claim."]), "lr_1")
        check_build_shape(self, r)
        self.assertEqual((r["valid"], r["errors"]), (True, []))
        rec = r["learning_record"]
        self.assertEqual(list(rec), REC_KEYS)
        self.assertEqual(rec, {"version": "1", "learning_record_id": "lr_1",
                               "request_id": "res_001", "synthesis_id": "syn_1",
                               "source_id": "src_1", "claims": ["First claim.", "Second claim."],
                               "evidence_count": 2, "status": "candidate",
                               "execution_allowed": False})

    def test_single_claim(self):
        rec = build(request(), synth(["Only claim."]), "lr")["learning_record"]
        self.assertEqual((rec["claims"], rec["evidence_count"]), (["Only claim."], 1))

    def test_multiple_claims(self):
        for n in (2, 5, 64):
            rec = good(n)
            self.assertEqual((rec["evidence_count"], len(rec["claims"])), (n, n))

    def test_claim_order_preserved_not_sorted(self):
        claims = ["zebra", "apple", "mango", "banana"]
        rec = build(request(), synth(claims), "lr")["learning_record"]
        self.assertEqual(rec["claims"], claims)

    def test_claims_verbatim_duplicates_and_all(self):
        claims = ["Same claim.", "Same claim.", "UPPER and lower", "x" * 500]
        rec = build(request(), synth(claims), "lr")["learning_record"]
        self.assertEqual(rec["claims"], claims)

    def test_request_synthesis_and_source_identity_preserved(self):
        rec = build(request("Req-9"), synth(rid="Req-9", sid="Src.Z", syn_id="Syn-7"),
                    "LR-1")["learning_record"]
        self.assertEqual((rec["request_id"], rec["synthesis_id"], rec["source_id"],
                          rec["learning_record_id"]), ("Req-9", "Syn-7", "Src.Z", "LR-1"))

    def test_evidence_count_preserved_from_synthesis(self):
        s = synth(["a", "b", "c"])
        rec = build(request(), s, "lr")["learning_record"]
        self.assertEqual(rec["evidence_count"], s["evidence_count"])

    def test_status_is_candidate_and_flags_false(self):
        rec = good()
        self.assertEqual(rec["status"], "candidate")
        self.assertIs(rec["execution_allowed"], False)

    def test_executed_only_on_result_not_in_record(self):
        r = build(request(), synth(), "lr")
        self.assertIn("executed", r)
        self.assertNotIn("executed", r["learning_record"])
        self.assertNotIn("evidence_ids", r["learning_record"])

    def test_fresh_and_deterministic(self):
        args = (request(), synth(["a", "b"]), "lr")
        a, b = build(*args), build(*args)
        self.assertEqual(a, b)
        self.assertIsNot(a["learning_record"], b["learning_record"])
        self.assertIsNot(a["learning_record"]["claims"], b["learning_record"]["claims"])

    def test_record_independent_of_synthesis(self):
        s = synth(["a", "b"])
        rec = build(request(), s, "lr")["learning_record"]
        s["claims"][0] = "changed"
        s["claims"].append("x")
        self.assertEqual(rec["claims"], ["a", "b"])


class FailureTests(unittest.TestCase):
    def test_invalid_request(self):
        for bad in (None, {}, [], "x", dict(request(), goal="")):
            r = build(bad, synth(), "lr")
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "invalid_request", "where": "research_request"}])

    def test_invalid_synthesis(self):
        bad_syn = synth(); bad_syn["evidence_count"] = 9
        for bad in (None, {}, [], "x", bad_syn):
            r = build(request(), bad, "lr")
            check_build_shape(self, r)
            self.assertEqual(r["errors"], [{"code": "invalid_synthesis", "where": "synthesis"}])

    def test_request_checked_before_synthesis(self):
        r = build({}, {}, None)
        self.assertEqual(codes(r), ["invalid_request"])

    def test_synthesis_checked_before_id(self):
        self.assertEqual(codes(build(request(), {}, None)), ["invalid_synthesis"])

    def test_request_mismatch(self):
        r = build(request("res_001"), synth(rid="res_002"), "lr")
        check_build_shape(self, r)
        self.assertEqual(r["errors"], [{"code": "request_mismatch", "where": "synthesis"}])

    def test_request_mismatch_before_missing_id(self):
        self.assertEqual(codes(build(request("a"), synth(rid="b"), None)), ["request_mismatch"])

    def test_missing_learning_record_id(self):
        for r in (build(request(), synth()), build(request(), synth(), None),
                  build(request(), synth(), learning_record_id=None)):
            check_build_shape(self, r)
            self.assertEqual(r["errors"],
                             [{"code": "missing_learning_record_id", "where": "learning_record_id"}])

    def test_invalid_learning_record_id(self):
        for bad in ("", " a", "a ", "a\nb", "x" * 65, 5, True, [], {}, b"lr"):
            r = build(request(), synth(), bad)
            check_build_shape(self, r)
            self.assertEqual(r["errors"],
                             [{"code": "invalid_learning_record_id", "where": "learning_record_id"}],
                             repr(bad))
        self.assertTrue(build(request(), synth(), "x" * 64)["valid"])

    def test_id_never_generated(self):
        self.assertIsNone(build(request(), synth())["learning_record"])

    def test_no_args_and_internal_error(self):
        self.assertEqual(codes(build()), ["invalid_request"])
        with mock.patch.object(m, "validate_research_request", side_effect=RuntimeError):
            r = build(request(), synth(), "lr")
        self.assertEqual(r["errors"], [{"code": "build_error", "where": "learning_record"}])
        check_build_shape(self, r)


class ImmutabilityTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        bad_syn = synth(); bad_syn["evidence_count"] = 9
        cases = [(request(), synth(["b", "a"]), "lr"), (request(), synth(), None),
                 (request(), synth(), ""), (request("x"), synth(), "lr"),
                 (request(), bad_syn, "lr"), ({}, {}, {})]
        for args in cases:
            before = copy.deepcopy(args)
            build(*args)
            self.assertEqual(args, before)


class ValidatorTests(unittest.TestCase):
    def test_validate_good_shape_and_flags(self):
        v = validate(good())
        self.assertEqual(list(v), VALIDATE_KEYS)
        self.assertEqual((v["valid"], v["errors"]), (True, []))
        self.assertIs(v["execution_allowed"], False)
        self.assertIs(v["executed"], False)
        for n in (1, 64):
            self.assertTrue(validate(good(n))["valid"])

    def test_validator_needs_only_the_record(self):
        rec = {"version": "1", "learning_record_id": "lr", "request_id": "r",
               "synthesis_id": "s", "source_id": "src", "claims": ["c"],
               "evidence_count": 1, "status": "candidate", "execution_allowed": False}
        self.assertTrue(validate(rec)["valid"])

    def test_malformed_record(self):
        self.assertEqual(validate()["errors"], [{"code": "missing_record", "where": "learning_record"}])
        for bad in ([], "x", 3, True, (), [good()]):
            self.assertEqual(validate(bad)["errors"],
                             [{"code": "record_not_dict", "where": "learning_record"}])
        self.assertEqual(validate({})["errors"][0], {"code": "missing_field", "where": "version"})
        big = {str(i): i for i in range(17)}
        self.assertEqual(validate(big)["errors"],
                         [{"code": "too_many_fields", "where": "learning_record"}])

    def test_missing_and_extra_keys(self):
        for key in REC_KEYS:
            r = good(); del r[key]
            self.assertEqual(validate(r)["errors"], [{"code": "missing_field", "where": key}])
        for extra in ("extra", "executed", "evidence_ids", "summary"):
            r = good(); r[extra] = 1
            self.assertEqual(validate(r)["errors"], [{"code": "unexpected_field", "where": extra}])

    def test_rejects_bad_scalar_fields(self):
        for key, bad, code in (("version", "2", "invalid_version"), ("version", 1, "invalid_version"),
                               ("learning_record_id", "", "invalid_learning_record_id"),
                               ("learning_record_id", None, "invalid_learning_record_id"),
                               ("request_id", " a", "invalid_request_id"),
                               ("synthesis_id", 5, "invalid_synthesis_id"),
                               ("synthesis_id", "", "invalid_synthesis_id"),
                               ("source_id", "x" * 65, "invalid_source_id"),
                               ("source_id", None, "invalid_source_id")):
            r = good(); r[key] = bad
            self.assertEqual(codes(validate(r)), [code], (key, bad))

    def test_rejects_malformed_claims(self):
        for bad in (None, {}, "x", (), 5):
            r = good(); r["claims"] = bad
            self.assertIn("invalid_claims", codes(validate(r)))
        for bad in ("", " a", "a ", "a\tb", None, 5, "x" * 501, ["a"]):
            r = good(3); r["claims"][1] = bad
            self.assertEqual(validate(r)["errors"],
                             [{"code": "invalid_claim", "where": "claims[1]"}], repr(bad))

    def test_rejects_empty_claims_and_limit(self):
        r = good(); r["claims"] = []; r["evidence_count"] = 0
        self.assertEqual(codes(validate(r)), ["empty_claims"])
        r = good(); r["claims"] = ["c"] * 65; r["evidence_count"] = 65
        self.assertEqual(codes(validate(r)), ["evidence_limit_exceeded"])

    def test_rejects_wrong_evidence_count(self):
        for bad in (0, 1, 3, -1, True, 2.0, "2", None):
            r = good(2); r["evidence_count"] = bad
            self.assertEqual(codes(validate(r)), ["invalid_evidence_count"], repr(bad))

    def test_status_only_candidate(self):
        for bad in ("approved", "applied", "stored", "Candidate", "", None, 1, True):
            r = good(); r["status"] = bad
            self.assertEqual(codes(validate(r)), ["invalid_status"], repr(bad))

    def test_rejects_true_execution_flag(self):
        for bad in (True, 1, 0, None, "False"):
            r = good(); r["execution_allowed"] = bad
            v = validate(r)
            self.assertEqual(codes(v), ["invalid_execution_allowed"], repr(bad))
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)

    def test_validate_never_mutates_or_raises_and_is_deterministic(self):
        r = good(); before = copy.deepcopy(r)
        validate(r)
        self.assertEqual(r, before)
        r["claims"] = [object(), object()]
        self.assertFalse(validate(r)["valid"])
        r["evidence_count"] = 7
        self.assertEqual(validate(r), validate(r))
        self.assertIsNot(validate(r), validate(r))
        with mock.patch.object(m, "_check_claims", side_effect=RuntimeError):
            self.assertEqual(validate(good())["errors"],
                             [{"code": "validation_error", "where": "learning_record"}])


class IsolationTests(unittest.TestCase):
    def test_no_io_subprocess_or_network(self):
        def forbidden(*a, **k):
            raise AssertionError("forbidden call")
        args = (request(), synth(["a", "b"]), "lr")
        with mock.patch.object(builtins, "open", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(os, "stat", forbidden):
            r = build(*args)
            validate(r["learning_record"])
            build()
        self.assertTrue(r["valid"])

    def test_source_imports_and_public_api(self):
        with open(os.path.join(ROOT, "research", "research_learning_record.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual(sorted(n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)),
                         ["research.research_evidence", "research.research_evidence_set",
                          "research.research_request", "research.research_source",
                          "research.research_synthesis"])
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Import)])
        public = sorted(n.name for n in tree.body
                        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"))
        self.assertEqual(public, ["build_research_learning_record", "validate_research_learning_record"])

    def test_no_ranking_rewriting_or_generation(self):
        with open(os.path.join(ROOT, "research", "research_learning_record.py"), encoding="utf-8") as fh:
            code = fh.read().split('"""')[2]
        for token in ("sorted(", ".sort(", "set(", "lower(", "upper(", "join(", "format(",
                      "uuid", "random", "time", "startswith", "split("):
            self.assertNotIn(token, code, token)


if __name__ == "__main__":
    unittest.main()
