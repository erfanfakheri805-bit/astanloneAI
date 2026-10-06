"""
Prompt 874 - research learning acceptance contract focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_research_learning_acceptance_prompt874 -v
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

from research import research_learning_acceptance as m
from research.research_evidence import build_research_evidence
from research.research_evidence_set import build_research_evidence_set
from research.research_learning_acceptance import build_research_learning_acceptance as build
from research.research_learning_acceptance import validate_research_learning_acceptance as validate
from research.research_learning_boundary import evaluate_research_learning_boundary
from research.research_learning_record import build_research_learning_record
from research.research_request import build_research_request
from research.research_source import build_research_source
from research.research_synthesis import build_research_synthesis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BUILD_KEYS = ["valid", "errors", "acceptance", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
ACC_KEYS = ["version", "acceptance_id", "learning_record_id", "request_id", "synthesis_id",
            "source_id", "claims", "evidence_count", "status", "execution_allowed"]


def request(rid="res_001"):
    r = build_research_request({
        "request_id": rid, "goal": "Understand retrieval-augmented generation.",
        "topics": ["rag basics"], "constraints": [], "requested_by": "developer"})
    assert r["valid"], r["errors"]
    return r["research_request"]


def record(rid="res_001", lid="lr_1", claims=("Claim one.", "Claim two."), sid="src_1",
           syn_id="syn_1"):
    src = build_research_source({
        "source_id": sid, "source_type": "local_file", "location": "loc/" + sid,
        "trust_level": "standard", "constraints": [], "enabled": True})["source"]
    evidence = [build_research_evidence({
        "evidence_id": "e%d" % i, "source_id": sid, "claim": c, "evidence_type": "fact",
        "confidence": 0.5, "constraints": []})["evidence"] for i, c in enumerate(claims)]
    es = build_research_evidence_set(request(rid), src, evidence)["evidence_set"]
    syn = build_research_synthesis(request(rid), es, syn_id)["synthesis"]
    r = build_research_learning_record(request(rid), syn, lid)
    assert r["valid"], r["errors"]
    return r["learning_record"]


def boundary(req=None, rec=None):
    b = evaluate_research_learning_boundary(req or request(), rec or record())
    return b


def args(**over):
    base = {"research_request": request(), "learning_record": record(),
            "boundary_result": boundary(), "acceptance_id": "acc_1"}
    base.update(over)
    return base


def run(**over):
    return build(**args(**over))


def good(n=2, aid="acc_1"):
    rec = record(claims=tuple("Claim %d" % i for i in range(n)))
    r = build(request(), rec, boundary(request(), rec), aid)
    assert r["valid"], r["errors"]
    return r["acceptance"]


def codes(result):
    return [e["code"] for e in result["errors"]]


def check_build_shape(test, r):
    test.assertEqual(list(r), BUILD_KEYS)
    test.assertIs(r["execution_allowed"], False)
    test.assertIs(r["executed"], False)
    json.dumps(r)
    if r["valid"]:
        test.assertEqual(validate(r["acceptance"])["errors"], [])
    else:
        test.assertIsNone(r["acceptance"])


def not_ready_boundary():
    rec = record(); rec["status"] = "approved"
    with mock.patch("research.research_learning_boundary.validate_research_learning_record",
                    return_value={"valid": True}):
        b = evaluate_research_learning_boundary(request(), rec)
    assert b["status"] == "not_ready", b
    return b


class SuccessTests(unittest.TestCase):
    def test_successful_acceptance(self):
        r = run()
        check_build_shape(self, r)
        self.assertEqual((r["valid"], r["errors"]), (True, []))
        self.assertEqual(r["acceptance"], {
            "version": "1", "acceptance_id": "acc_1", "learning_record_id": "lr_1",
            "request_id": "res_001", "synthesis_id": "syn_1", "source_id": "src_1",
            "claims": ["Claim one.", "Claim two."], "evidence_count": 2,
            "status": "accepted", "execution_allowed": False})
        self.assertEqual(list(r["acceptance"]), ACC_KEYS)
        self.assertNotIn("executed", r["acceptance"])

    def test_single_and_many_claims(self):
        for n in (1, 5, 64):
            a = good(n)
            self.assertEqual((a["evidence_count"], len(a["claims"])), (n, n))

    def test_claims_order_and_content_preserved(self):
        claims = ("zebra", "apple", "apple", "UPPER and lower", "x" * 500)
        rec = record(claims=claims)
        a = build(request(), rec, boundary(request(), rec), "acc")["acceptance"]
        self.assertEqual(a["claims"], list(claims))

    def test_identities_preserved_exactly(self):
        rec = record("Req-9", "LR-9", sid="Src.Z", syn_id="Syn-7")
        a = build(request("Req-9"), rec, boundary(request("Req-9"), rec), "Acc-1")["acceptance"]
        self.assertEqual((a["acceptance_id"], a["learning_record_id"], a["request_id"],
                          a["synthesis_id"], a["source_id"]),
                         ("Acc-1", "LR-9", "Req-9", "Syn-7", "Src.Z"))

    def test_evidence_count_preserved(self):
        rec = record(claims=("a", "b", "c"))
        a = build(request(), rec, boundary(request(), rec), "acc")["acceptance"]
        self.assertEqual(a["evidence_count"], rec["evidence_count"])

    def test_fresh_deterministic_and_independent(self):
        rec = record()
        a, b = run(learning_record=rec), run(learning_record=rec)
        self.assertEqual(a, b)
        self.assertIsNot(a["acceptance"]["claims"], b["acceptance"]["claims"])
        a["acceptance"]["claims"].append("x")
        self.assertEqual(len(rec["claims"]), 2)


class FailureTests(unittest.TestCase):
    def one(self, r, code, where):
        check_build_shape(self, r)
        self.assertEqual(r["errors"], [{"code": code, "where": where}])

    def test_invalid_request(self):
        for bad in (None, {}, [], "x", dict(request(), goal="")):
            self.one(run(research_request=bad), "invalid_request", "research_request")

    def test_invalid_learning_record(self):
        bad_rec = record(); bad_rec["evidence_count"] = 9
        for bad in (None, {}, [], "x", bad_rec):
            self.one(run(learning_record=bad), "invalid_learning_record", "learning_record")

    def test_invalid_boundary(self):
        bad_b = boundary(); bad_b["ready"] = False
        extra_b = boundary(); extra_b["x"] = 1
        for bad in (None, {}, [], "x", bad_b, extra_b):
            self.one(run(boundary_result=bad), "invalid_boundary_result", "boundary_result")

    def test_boundary_not_ready(self):
        self.one(run(boundary_result=not_ready_boundary()), "boundary_not_ready", "boundary_result")

    def test_boundary_ready_flag_and_status_both_required(self):
        b = boundary(); b["ready"] = False  # inconsistent: rejected as an invalid boundary result
        self.one(run(boundary_result=b), "invalid_boundary_result", "boundary_result")
        b = boundary()
        with mock.patch.object(m, "validate_research_learning_boundary_result",
                               return_value={"valid": True}):
            b["ready"] = False
            self.one(run(boundary_result=b), "boundary_not_ready", "boundary_result")
            b = boundary(); b["status"] = "not_ready"
            self.one(run(boundary_result=b), "boundary_not_ready", "boundary_result")

    def test_request_id_mismatch_with_record(self):
        rec = record("res_002")
        self.one(run(learning_record=rec, boundary_result=boundary(request("res_002"), rec)),
                 "request_mismatch", "learning_record")

    def test_request_id_mismatch_with_boundary(self):
        other = boundary(request("res_002"), record("res_002"))
        self.one(run(boundary_result=other), "request_mismatch", "boundary_result")

    def test_learning_record_id_mismatch(self):
        other = boundary(request(), record(lid="lr_other"))
        self.one(run(boundary_result=other), "learning_record_mismatch", "boundary_result")

    def test_missing_acceptance_id(self):
        for r in (build(request(), record(), boundary()), run(acceptance_id=None)):
            self.one(r, "missing_acceptance_id", "acceptance_id")

    def test_invalid_acceptance_id(self):
        for bad in ("", " a", "a ", "a\nb", "x" * 65, 5, True, [], {}, b"a"):
            self.one(run(acceptance_id=bad), "invalid_acceptance_id", "acceptance_id")
        self.assertTrue(run(acceptance_id="x" * 64)["valid"])

    def test_acceptance_id_never_generated(self):
        self.assertIsNone(build(request(), record(), boundary())["acceptance"])
        self.assertIsNone(run(acceptance_id="")["acceptance"])

    def test_validation_order(self):
        self.assertEqual(codes(build()), ["invalid_request"])
        self.assertEqual(codes(build(request())), ["invalid_learning_record"])
        self.assertEqual(codes(build(request(), record())), ["invalid_boundary_result"])
        rec2 = record("res_002")
        # request mismatch precedes learning-record mismatch, readiness and id checks
        r = build(request(), rec2, boundary(request("res_002"), rec2), None)
        self.assertEqual(codes(r), ["request_mismatch"])
        # id mismatch precedes readiness and acceptance id
        nr = not_ready_boundary()
        r = build(request(), record(lid="lr_other"), nr, None)
        self.assertEqual(codes(r), ["learning_record_mismatch"])
        # readiness precedes acceptance id
        self.assertEqual(codes(build(request(), record(), nr, None)), ["boundary_not_ready"])

    def test_internal_error(self):
        for name in ("validate_research_request", "validate_research_learning_record",
                     "validate_research_learning_boundary_result"):
            with mock.patch.object(m, name, side_effect=RuntimeError):
                self.one(run(), "build_error", "acceptance")

    def test_reuses_public_validators(self):
        for name, code in (("validate_research_request", "invalid_request"),
                           ("validate_research_learning_record", "invalid_learning_record"),
                           ("validate_research_learning_boundary_result", "invalid_boundary_result")):
            with mock.patch.object(m, name, return_value={"valid": False}) as v:
                self.assertEqual(codes(run()), [code])
            v.assert_called_once()


class ImmutabilityTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        bad_rec = record(); bad_rec["evidence_count"] = 9
        cases = [args(), args(acceptance_id=None), args(acceptance_id=""),
                 args(research_request=request("x")), args(learning_record=bad_rec),
                 args(boundary_result=not_ready_boundary()),
                 args(boundary_result={}), args(research_request={}, learning_record={})]
        for kwargs in cases:
            before = copy.deepcopy(kwargs)
            build(**kwargs)
            self.assertEqual(kwargs, before)


class ValidatorTests(unittest.TestCase):
    def test_validate_good_shape_and_flags(self):
        v = validate(good())
        self.assertEqual(list(v), VALIDATE_KEYS)
        self.assertEqual((v["valid"], v["errors"]), (True, []))
        self.assertIs(v["execution_allowed"], False)
        self.assertIs(v["executed"], False)
        for n in (1, 64):
            self.assertTrue(validate(good(n))["valid"])

    def test_validator_needs_only_the_acceptance(self):
        acc = {"version": "1", "acceptance_id": "a", "learning_record_id": "l",
               "request_id": "r", "synthesis_id": "s", "source_id": "src", "claims": ["c"],
               "evidence_count": 1, "status": "accepted", "execution_allowed": False}
        self.assertTrue(validate(acc)["valid"])

    def test_malformed_acceptance(self):
        self.assertEqual(validate()["errors"], [{"code": "missing_acceptance", "where": "acceptance"}])
        for bad in ([], "x", 3, True, (), [good()]):
            self.assertEqual(validate(bad)["errors"],
                             [{"code": "acceptance_not_dict", "where": "acceptance"}])
        self.assertEqual(validate({})["errors"][0], {"code": "missing_field", "where": "version"})
        big = {str(i): i for i in range(17)}
        self.assertEqual(validate(big)["errors"], [{"code": "too_many_fields", "where": "acceptance"}])

    def test_missing_and_extra_keys(self):
        for key in ACC_KEYS:
            a = good(); del a[key]
            self.assertEqual(validate(a)["errors"], [{"code": "missing_field", "where": key}])
        for extra in ("extra", "executed", "evidence_ids", "boundary_result"):
            a = good(); a[extra] = 1
            self.assertEqual(validate(a)["errors"], [{"code": "unexpected_field", "where": extra}])

    def test_rejects_bad_version_and_ids(self):
        for key, bad, code in (("version", "2", "invalid_version"), ("version", 1, "invalid_version"),
                               ("acceptance_id", "", "invalid_acceptance_id"),
                               ("acceptance_id", None, "invalid_acceptance_id"),
                               ("learning_record_id", " a", "invalid_learning_record_id"),
                               ("request_id", 5, "invalid_request_id"),
                               ("synthesis_id", "x" * 65, "invalid_synthesis_id"),
                               ("source_id", None, "invalid_source_id")):
            a = good(); a[key] = bad
            self.assertEqual(codes(validate(a)), [code], (key, bad))

    def test_altered_and_malformed_claims(self):
        for bad in (None, {}, "x", (), 5):
            a = good(); a["claims"] = bad
            self.assertIn("invalid_claims", codes(validate(a)))
        for bad in ("", " a", "a ", "a\tb", None, 5, "x" * 501, ["a"]):
            a = good(3); a["claims"][1] = bad
            self.assertEqual(validate(a)["errors"],
                             [{"code": "invalid_claim", "where": "claims[1]"}], repr(bad))
        a = good(); a["claims"] = []; a["evidence_count"] = 0
        self.assertEqual(codes(validate(a)), ["empty_claims"])
        a = good(); a["claims"] = ["c"] * 65; a["evidence_count"] = 65
        self.assertEqual(codes(validate(a)), ["evidence_limit_exceeded"])

    def test_claim_added_or_removed_breaks_count(self):
        a = good(3); a["claims"].pop()
        self.assertEqual(codes(validate(a)), ["invalid_evidence_count"])
        a = good(3); a["claims"].append("extra")
        self.assertEqual(codes(validate(a)), ["invalid_evidence_count"])

    def test_rejects_incorrect_evidence_count(self):
        for bad in (0, 1, 3, -1, True, 2.0, "2", None):
            a = good(2); a["evidence_count"] = bad
            self.assertEqual(codes(validate(a)), ["invalid_evidence_count"], repr(bad))

    def test_status_only_accepted(self):
        for bad in ("candidate", "approved", "applied", "stored", "Accepted", "", None, 1, True):
            a = good(); a["status"] = bad
            self.assertEqual(codes(validate(a)), ["invalid_status"], repr(bad))

    def test_rejects_true_execution_flag(self):
        for bad in (True, 1, 0, None, "False"):
            a = good(); a["execution_allowed"] = bad
            v = validate(a)
            self.assertEqual(codes(v), ["invalid_execution_allowed"], repr(bad))
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)

    def test_validate_never_mutates_or_raises_and_is_deterministic(self):
        a = good(); before = copy.deepcopy(a)
        validate(a)
        self.assertEqual(a, before)
        a["claims"] = [object(), object()]
        self.assertFalse(validate(a)["valid"])
        a["evidence_count"] = 7
        self.assertEqual(validate(a), validate(a))
        self.assertIsNot(validate(a), validate(a))
        with mock.patch.object(m, "_check_claims", side_effect=RuntimeError):
            self.assertEqual(validate(good())["errors"],
                             [{"code": "validation_error", "where": "acceptance"}])


class IsolationTests(unittest.TestCase):
    def test_no_io_subprocess_or_network(self):
        def forbidden(*a, **k):
            raise AssertionError("forbidden call")
        kw = args()
        with mock.patch.object(builtins, "open", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(os, "stat", forbidden):
            r = build(**kw)
            validate(r["acceptance"])
            build()
        self.assertTrue(r["valid"])

    def test_source_imports_and_public_api(self):
        with open(os.path.join(ROOT, "research", "research_learning_acceptance.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual(sorted(n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)),
                         ["research.research_evidence", "research.research_evidence_set",
                          "research.research_learning_boundary", "research.research_learning_record",
                          "research.research_request", "research.research_source"])
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Import)])
        public = sorted(n.name for n in tree.body
                        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"))
        self.assertEqual(public, ["build_research_learning_acceptance",
                                  "validate_research_learning_acceptance"])

    def test_no_ranking_rewriting_or_generation(self):
        with open(os.path.join(ROOT, "research", "research_learning_acceptance.py"), encoding="utf-8") as fh:
            code = fh.read().split('"""')[2]
        for token in ("sorted(", ".sort(", "set(", "lower(", "upper(", "join(", "format(",
                      "uuid", "random", "time", "startswith", "split(", "write", "print("):
            self.assertNotIn(token, code, token)


if __name__ == "__main__":
    unittest.main()
