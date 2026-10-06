"""
Prompt 873 - research learning boundary focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_research_learning_boundary_prompt873 -v
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

from research import research_learning_boundary as m
from research.research_learning_boundary import evaluate_research_learning_boundary as evaluate
from research.research_learning_boundary import validate_research_learning_boundary_result as validate
from research.research_learning_record import build_research_learning_record
from research.research_request import build_research_request
from research.research_synthesis import build_research_synthesis
from research.research_evidence import build_research_evidence
from research.research_evidence_set import build_research_evidence_set
from research.research_source import build_research_source

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RESULT_KEYS = ["status", "ready", "learning_record_id", "request_id", "reason",
               "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]
STATUSES = ["ready", "not_ready", "invalid_request", "invalid_learning_record",
            "context_mismatch", "validation_error"]


def request(rid="res_001"):
    r = build_research_request({
        "request_id": rid, "goal": "Understand retrieval-augmented generation.",
        "topics": ["rag basics"], "constraints": [], "requested_by": "developer"})
    assert r["valid"], r["errors"]
    return r["research_request"]


def record(rid="res_001", lid="lr_1", claims=("Claim one.", "Claim two.")):
    src = build_research_source({
        "source_id": "src_1", "source_type": "local_file", "location": "loc/src_1",
        "trust_level": "standard", "constraints": [], "enabled": True})["source"]
    evidence = [build_research_evidence({
        "evidence_id": "e%d" % i, "source_id": "src_1", "claim": c, "evidence_type": "fact",
        "confidence": 0.5, "constraints": []})["evidence"] for i, c in enumerate(claims)]
    es = build_research_evidence_set(request(rid), src, evidence)["evidence_set"]
    syn = build_research_synthesis(request(rid), es, "syn_1")["synthesis"]
    r = build_research_learning_record(request(rid), syn, lid)
    assert r["valid"], r["errors"]
    return r["learning_record"]


def ready():
    r = evaluate(request(), record())
    assert r["status"] == "ready", r
    return r


def codes(result):
    return [e["code"] for e in result["errors"]]


def check_shape(test, r):
    test.assertEqual(list(r), RESULT_KEYS)
    test.assertIs(r["execution_allowed"], False)
    test.assertIs(r["executed"], False)
    json.dumps(r)
    test.assertEqual(validate(r)["errors"], [])


class EvaluateTests(unittest.TestCase):
    def test_ready_result(self):
        r = evaluate(request(), record())
        check_shape(self, r)
        self.assertEqual(r, {"status": "ready", "ready": True, "learning_record_id": "lr_1",
                             "request_id": "res_001", "reason": m.REASONS["ready"],
                             "execution_allowed": False, "executed": False})

    def test_ready_for_single_and_many_claims(self):
        for claims in (("a",), tuple("c%d" % i for i in range(64))):
            r = evaluate(request(), record(claims=claims))
            check_shape(self, r)
            self.assertEqual((r["status"], r["ready"]), ("ready", True))

    def test_ids_come_from_validated_objects(self):
        r = evaluate(request("Req-9"), record("Req-9", "LR-9"))
        self.assertEqual((r["request_id"], r["learning_record_id"]), ("Req-9", "LR-9"))

    def test_invalid_request(self):
        for bad in (None, {}, [], "x", dict(request(), goal="")):
            r = evaluate(bad, record())
            check_shape(self, r)
            self.assertEqual((r["status"], r["ready"], r["learning_record_id"], r["request_id"]),
                             ("invalid_request", False, None, None))
            self.assertEqual(r["reason"], m.REASONS["invalid_request"])

    def test_invalid_learning_record(self):
        bad_rec = record(); bad_rec["evidence_count"] = 9
        for bad in (None, {}, [], "x", bad_rec):
            r = evaluate(request(), bad)
            check_shape(self, r)
            self.assertEqual((r["status"], r["ready"], r["learning_record_id"], r["request_id"]),
                             ("invalid_learning_record", False, None, "res_001"))

    def test_request_id_mismatch(self):
        r = evaluate(request("res_001"), record("res_002"))
        check_shape(self, r)
        self.assertEqual((r["status"], r["ready"], r["learning_record_id"], r["request_id"]),
                         ("context_mismatch", False, "lr_1", "res_001"))
        self.assertEqual(r["reason"], m.REASONS["context_mismatch"])

    def test_non_candidate_status_via_public_path_is_invalid_record(self):
        # Prompt 872 allows only "candidate", so other statuses fail record validation first.
        for bad in ("approved", "applied", "stored", ""):
            rec = record(); rec["status"] = bad
            self.assertEqual(evaluate(request(), rec)["status"], "invalid_learning_record")

    def test_not_ready_when_record_validator_accepts_other_status(self):
        rec = record(); rec["status"] = "approved"
        with mock.patch.object(m, "validate_research_learning_record",
                               return_value={"valid": True}):
            r = evaluate(request(), rec)
        check_shape(self, r)
        self.assertEqual((r["status"], r["ready"], r["learning_record_id"], r["request_id"]),
                         ("not_ready", False, "lr_1", "res_001"))
        self.assertEqual(r["reason"], m.REASONS["not_ready"])

    def test_order_request_before_record(self):
        self.assertEqual(evaluate({}, {})["status"], "invalid_request")

    def test_order_record_before_mismatch(self):
        rec = record("other"); rec["claims"] = []
        self.assertEqual(evaluate(request(), rec)["status"], "invalid_learning_record")

    def test_order_mismatch_before_status(self):
        rec = record("other"); rec["status"] = "approved"
        with mock.patch.object(m, "validate_research_learning_record",
                               return_value={"valid": True}):
            self.assertEqual(evaluate(request(), rec)["status"], "context_mismatch")

    def test_no_arguments(self):
        self.assertEqual(evaluate()["status"], "invalid_request")

    def test_unexpected_failure_is_validation_error(self):
        for name in ("validate_research_request", "validate_research_learning_record"):
            with mock.patch.object(m, name, side_effect=RuntimeError):
                r = evaluate(request(), record())
            check_shape(self, r)
            self.assertEqual((r["status"], r["ready"], r["learning_record_id"], r["request_id"]),
                             ("validation_error", False, None, None))
            self.assertEqual(r["reason"], m.REASONS["validation_error"])

    def test_reuses_public_validators(self):
        with mock.patch.object(m, "validate_research_request",
                               return_value={"valid": False}) as v:
            self.assertEqual(evaluate(request(), record())["status"], "invalid_request")
        v.assert_called_once()
        with mock.patch.object(m, "validate_research_learning_record",
                               return_value={"valid": False}) as v:
            self.assertEqual(evaluate(request(), record())["status"], "invalid_learning_record")
        v.assert_called_once()

    def test_fresh_and_deterministic(self):
        args = (request(), record())
        a, b = evaluate(*args), evaluate(*args)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)

    def test_inputs_not_mutated(self):
        bad_rec = record(); bad_rec["evidence_count"] = 9
        non_cand = record(); non_cand["status"] = "approved"
        for args in ((request(), record()), (request(), record("x")), (request(), bad_rec),
                     (request(), non_cand), ({}, {}), (None, None)):
            before = copy.deepcopy(args)
            evaluate(*args)
            self.assertEqual(args, before)

    def test_flags_always_false(self):
        rec_bad = record(); rec_bad["status"] = "approved"
        for args in ((request(), record()), (request(), record("x")), (request(), rec_bad),
                     ({}, {}), (request(), {})):
            r = evaluate(*args)
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_all_statuses_have_distinct_reasons(self):
        self.assertEqual(sorted(m.REASONS), sorted(STATUSES))
        self.assertEqual(len(set(m.REASONS.values())), 6)


class ValidatorTests(unittest.TestCase):
    def test_valid_results_for_every_status(self):
        samples = [evaluate(request(), record()), evaluate({}, record()),
                   evaluate(request(), {}), evaluate(request("a"), record("b"))]
        with mock.patch.object(m, "validate_research_learning_record", return_value={"valid": True}):
            rec = record(); rec["status"] = "approved"
            samples.append(evaluate(request(), rec))
        with mock.patch.object(m, "validate_research_request", side_effect=RuntimeError):
            samples.append(evaluate(request(), record()))
        self.assertEqual(sorted(s["status"] for s in samples), sorted(STATUSES))
        for s in samples:
            v = validate(s)
            self.assertEqual(list(v), VALIDATE_KEYS)
            self.assertEqual((v["valid"], v["errors"]), (True, []))
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)

    def test_malformed_result(self):
        self.assertEqual(validate()["errors"], [{"code": "missing_result", "where": "result"}])
        for bad in ([], "x", 3, True, (), [ready()]):
            self.assertEqual(validate(bad)["errors"], [{"code": "result_not_dict", "where": "result"}])
        self.assertEqual(validate({})["errors"][0], {"code": "missing_field", "where": "status"})
        big = {str(i): i for i in range(17)}
        self.assertEqual(validate(big)["errors"], [{"code": "too_many_fields", "where": "result"}])

    def test_missing_and_extra_keys(self):
        for key in RESULT_KEYS:
            r = ready(); del r[key]
            self.assertEqual(validate(r)["errors"], [{"code": "missing_field", "where": key}])
        for extra in ("extra", "valid", "errors", "learning_record"):
            r = ready(); r[extra] = 1
            self.assertEqual(validate(r)["errors"], [{"code": "unexpected_field", "where": extra}])

    def test_incorrect_status(self):
        for bad in ("approved", "Ready", "", None, 1, True, ["ready"]):
            r = ready(); r["status"] = bad
            self.assertIn("invalid_status", codes(validate(r)), repr(bad))

    def test_status_ready_combinations(self):
        for status in STATUSES:
            r = evaluate(request(), record()); r["status"] = status
            r["reason"] = m.REASONS[status]
            if status != "ready":
                self.assertIn("status_ready_mismatch", codes(validate(r)), status)
        r = evaluate({}, record()); r["ready"] = True
        self.assertEqual(codes(validate(r)), ["status_ready_mismatch"])
        for bad in (0, 1, None, "True"):
            r = ready(); r["ready"] = bad
            self.assertEqual(codes(validate(r)), ["invalid_ready"], repr(bad))

    def test_incorrect_ids(self):
        for key, code in (("learning_record_id", "invalid_learning_record_id"),
                          ("request_id", "invalid_request_id")):
            for bad in (None, "", " a", "a\n", 5, True, "x" * 65):
                r = ready(); r[key] = bad
                self.assertEqual(codes(validate(r)), [code], (key, bad))

    def test_ids_must_be_none_where_not_known(self):
        r = evaluate({}, record()); r["request_id"] = "res_001"
        self.assertEqual(codes(validate(r)), ["invalid_request_id"])
        r = evaluate({}, record()); r["learning_record_id"] = "lr_1"
        self.assertEqual(codes(validate(r)), ["invalid_learning_record_id"])
        r = evaluate(request(), {}); r["learning_record_id"] = "lr_1"
        self.assertEqual(codes(validate(r)), ["invalid_learning_record_id"])
        r = evaluate(request(), {}); r["request_id"] = None
        self.assertEqual(codes(validate(r)), ["invalid_request_id"])

    def test_incorrect_reason(self):
        for bad in ("", "other", None, 5, m.REASONS["not_ready"]):
            r = ready(); r["reason"] = bad
            self.assertEqual(codes(validate(r)), ["invalid_reason"], repr(bad))

    def test_incorrect_flags(self):
        for bad in (True, 1, 0, None, "False"):
            r = ready(); r["execution_allowed"] = bad
            v = validate(r)
            self.assertEqual(codes(v), ["invalid_execution_allowed"], repr(bad))
            self.assertIs(v["execution_allowed"], False)
            r = ready(); r["executed"] = bad
            v = validate(r)
            self.assertEqual(codes(v), ["invalid_executed"], repr(bad))
            self.assertIs(v["executed"], False)

    def test_validate_never_mutates_or_raises_and_is_deterministic(self):
        r = ready(); before = copy.deepcopy(r)
        validate(r)
        self.assertEqual(r, before)
        r["reason"] = object(); r["learning_record_id"] = object()
        self.assertFalse(validate(r)["valid"])
        self.assertEqual(validate(r), validate(r))
        self.assertIsNot(validate(r), validate(r))
        with mock.patch.object(m, "_check_id", side_effect=RuntimeError):
            self.assertEqual(validate(ready())["errors"],
                             [{"code": "validation_error", "where": "result"}])


class IsolationTests(unittest.TestCase):
    def test_no_io_subprocess_or_network(self):
        def forbidden(*a, **k):
            raise AssertionError("forbidden call")
        req, rec = request(), record()
        with mock.patch.object(builtins, "open", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(os, "stat", forbidden):
            r = evaluate(req, rec)
            validate(r)
            evaluate()
        self.assertTrue(r["ready"])

    def test_source_imports_and_public_api(self):
        with open(os.path.join(ROOT, "research", "research_learning_boundary.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual(sorted(n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)),
                         ["research.research_learning_record", "research.research_request",
                          "research.research_source"])
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Import)])
        public = sorted(n.name for n in tree.body
                        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"))
        self.assertEqual(public, ["evaluate_research_learning_boundary",
                                  "validate_research_learning_boundary_result"])

    def test_no_generation_or_side_effect_tokens(self):
        with open(os.path.join(ROOT, "research", "research_learning_boundary.py"), encoding="utf-8") as fh:
            code = fh.read().split('"""')[2]
        for token in ("uuid", "random", "time", "open(", "write", "print(", "os.", "sys."):
            self.assertNotIn(token, code, token)


if __name__ == "__main__":
    unittest.main()
