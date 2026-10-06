"""
Prompt 869 - research evidence validation boundary focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_research_evidence_validation_prompt869 -v
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

from research import research_evidence_validation as m
from research.research_evidence import build_research_evidence
from research.research_evidence_validation import validate_research_evidence_context_result as validate
from research.research_evidence_validation import validate_research_evidence_for_context as check
from research.research_request import build_research_request
from research.research_source import build_research_source

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["status", "valid", "evidence_id", "source_id", "reason", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]


def request(constraints=()):
    r = build_research_request({
        "request_id": "res_001", "goal": "Understand retrieval-augmented generation.",
        "topics": ["rag basics"], "constraints": list(constraints), "requested_by": "developer"})
    assert r["valid"], r["errors"]
    return r["research_request"]


def source(sid="src_1", stype="local_file", trust="standard", enabled=True, constraints=()):
    r = build_research_source({
        "source_id": sid, "source_type": stype, "location": "loc/" + sid, "trust_level": trust,
        "constraints": list(constraints), "enabled": enabled})
    assert r["valid"], r["errors"]
    return r["source"]


def evidence(sid="src_1", eid="ev_001", **over):
    d = {"evidence_id": eid, "source_id": sid, "claim": "RAG combines retrieval and generation.",
         "evidence_type": "fact", "confidence": 0.8, "constraints": []}
    d.update(over)
    r = build_research_evidence(d)
    assert r["valid"], r["errors"]
    return r["evidence"]


def run(constraints=(), **src):
    return check(request(constraints), source(**src), evidence())


def check_shape(test, r):
    test.assertEqual(list(r), KEYS)
    test.assertIs(r["execution_allowed"], False)
    test.assertIs(r["executed"], False)
    json.dumps(r)
    test.assertEqual(validate(r)["errors"], [])


class ValidTests(unittest.TestCase):
    def test_valid_combination(self):
        r = check(request(), source(), evidence())
        check_shape(self, r)
        self.assertEqual(r, {"status": "valid", "valid": True, "evidence_id": "ev_001",
                             "source_id": "src_1", "reason": "evidence_accepted",
                             "execution_allowed": False, "executed": False})

    def test_matching_source_id_with_other_ids(self):
        r = check(request(), source("abc"), evidence("abc", "e9"))
        self.assertEqual((r["status"], r["evidence_id"], r["source_id"]), ("valid", "e9", "abc"))

    def test_every_evidence_type_and_confidence_accepted(self):
        for t in ("fact", "observation", "user_statement", "learned_record"):
            for c in (0.0, 1.0):
                r = check(request(), source(), evidence(evidence_type=t, confidence=c))
                self.assertEqual(r["status"], "valid")

    def test_compatible_source_type(self):
        r = run(["source_type:local_file"])
        self.assertEqual(r["status"], "valid")
        self.assertEqual(run(["source_type:web", "source_type:local_file"])["status"], "valid")
        self.assertEqual(run(["not:source_type:web"])["status"], "valid")

    def test_compatible_min_trust(self):
        for minimum, trust in (("standard", "standard"), ("standard", "trusted"),
                               ("untrusted", "untrusted"), ("trusted", "trusted")):
            self.assertEqual(run(["min_trust:" + minimum], trust=trust)["status"], "valid",
                             (minimum, trust))

    def test_both_constraint_kinds_together(self):
        r = run(["source_type:api", "min_trust:standard", "other"], stype="api", trust="trusted")
        self.assertEqual(r["status"], "valid")

    def test_unrelated_constraints_are_ignored(self):
        for c in ("Source_Type:web", "Min_Trust:trusted", "trust:trusted", "anything"):
            self.assertEqual(run([c], trust="untrusted")["status"], "valid", c)

    def test_evidence_constraints_are_not_interpreted(self):
        e = evidence(constraints=["source_type:web", "min_trust:trusted"])
        r = check(request(), source(), e)
        self.assertEqual(r["status"], "valid")

    def test_source_request_negation_conflict_is_not_applied_here(self):
        r = check(request(["x"]), source(constraints=["not:x"]), evidence())
        self.assertEqual(r["status"], "valid")  # only source_type and min_trust are checked


class InvalidInputTests(unittest.TestCase):
    def assert_invalid(self, r, status, reason):
        check_shape(self, r)
        self.assertEqual((r["status"], r["valid"], r["evidence_id"], r["source_id"], r["reason"]),
                         (status, False, None, None, reason))

    def test_invalid_request(self):
        good = request()
        bad = [None, {}, [], "x", 5, True]
        d = copy.deepcopy(good); d["execution_allowed"] = True; bad.append(d)
        d = copy.deepcopy(good); del d["goal"]; bad.append(d)
        d = copy.deepcopy(good); d["topics"] = []; bad.append(d)
        for value in bad:
            self.assert_invalid(check(value, source(), evidence()),
                                "invalid_request", "invalid_request")

    def test_invalid_source(self):
        good = source()
        bad = [None, {}, [], "x", 5, True]
        d = copy.deepcopy(good); d["trust_level"] = "super"; bad.append(d)
        d = copy.deepcopy(good); d["enabled"] = 1; bad.append(d)
        d = copy.deepcopy(good); del d["location"]; bad.append(d)
        d = copy.deepcopy(good); d["execution_allowed"] = True; bad.append(d)
        for value in bad:
            self.assert_invalid(check(request(), value, evidence()),
                                "invalid_source", "invalid_source")

    def test_invalid_evidence(self):
        good = evidence()
        bad = [None, {}, [], "x", 5, True]
        for key, value in (("confidence", True), ("confidence", float("nan")), ("confidence", 1.5),
                           ("evidence_type", "opinion"), ("claim", ""), ("version", "2"),
                           ("execution_allowed", True), ("constraints", "a"), ("evidence_id", "")):
            d = copy.deepcopy(good); d[key] = value; bad.append(d)
        d = copy.deepcopy(good); del d["source_id"]; bad.append(d)
        d = copy.deepcopy(good); d["executed"] = False; bad.append(d)
        for value in bad:
            self.assert_invalid(check(request(), source(), value),
                                "invalid_evidence", "invalid_evidence")

    def test_raw_unnormalized_evidence_is_not_repaired(self):
        raw = {"evidence_id": "e", "source_id": "src_1", "claim": "c", "evidence_type": "fact",
               "confidence": 0.5, "constraints": []}  # lacks version / execution_allowed
        self.assert_invalid(check(request(), source(), raw), "invalid_evidence", "invalid_evidence")
        self.assertNotIn("version", raw)

    def test_no_arguments(self):
        self.assert_invalid(check(), "invalid_request", "invalid_request")

    def test_malformed_constraints_are_invalid_request(self):
        for c in ("source_type:", "source_type:ftp", "source_type:Web", "not:source_type:nope",
                  "min_trust:", "min_trust:high", "min_trust:Trusted", "min_trust: trusted"):
            self.assert_invalid(run([c]), "invalid_request", "invalid_constraint")


class MismatchTests(unittest.TestCase):
    def assert_mismatch(self, r, reason, sid="src_1"):
        check_shape(self, r)
        self.assertEqual((r["status"], r["valid"], r["reason"]), ("context_mismatch", False, reason))
        self.assertEqual((r["evidence_id"], r["source_id"]), ("ev_001", sid))

    def test_mismatched_source_id(self):
        r = check(request(), source("src_1"), evidence("src_2"))
        self.assert_mismatch(r, "source_id_mismatch")
        for other in ("SRC_1", "src_10", "src"):  # exact, case-sensitive comparison
            self.assert_mismatch(check(request(), source("src_1"), evidence(other)),
                                 "source_id_mismatch")

    def test_disabled_source_not_accepted(self):
        for cs in ([], ["source_type:local_file"], ["min_trust:untrusted"]):
            self.assert_mismatch(run(cs, enabled=False), "source_disabled")
        self.assert_mismatch(run(trust="trusted", enabled=False), "source_disabled")

    def test_incompatible_source_type(self):
        self.assert_mismatch(run(["source_type:web"]), "source_type_not_allowed")
        self.assert_mismatch(run(["source_type:web", "source_type:api"]), "source_type_not_allowed")
        self.assert_mismatch(run(["not:source_type:local_file"]), "source_type_excluded")
        self.assert_mismatch(run(["source_type:local_file", "not:source_type:local_file"]),
                             "source_type_excluded")

    def test_incompatible_min_trust(self):
        self.assert_mismatch(run(["min_trust:trusted"], trust="standard"), "min_trust_not_met")
        self.assert_mismatch(run(["min_trust:standard"], trust="untrusted"), "min_trust_not_met")
        self.assert_mismatch(run(["min_trust:untrusted", "min_trust:trusted"], trust="standard"),
                             "min_trust_not_met")

    def test_trust_is_not_upgraded_by_evidence(self):
        e = evidence(confidence=1.0, evidence_type="fact")
        r = check(request(["min_trust:trusted"]), source(trust="untrusted"), e)
        self.assertEqual(r["reason"], "min_trust_not_met")


class OrderingTests(unittest.TestCase):
    def test_failure_order(self):
        bad_req, bad_src, bad_ev = {}, {}, {}
        ok_req, ok_src, ok_ev = request(), source(), evidence()
        self.assertEqual(check(bad_req, bad_src, bad_ev)["status"], "invalid_request")
        self.assertEqual(check(ok_req, bad_src, bad_ev)["status"], "invalid_source")
        self.assertEqual(check(ok_req, ok_src, bad_ev)["status"], "invalid_evidence")

    def test_malformed_constraint_precedes_relationship_checks(self):
        r = check(request(["min_trust:high"]), source(enabled=False), evidence("other"))
        self.assertEqual((r["status"], r["reason"]), ("invalid_request", "invalid_constraint"))

    def test_disabled_precedes_id_mismatch_precedes_type_precedes_trust(self):
        req = request(["source_type:web", "min_trust:trusted"])
        s = lambda **k: source(stype="local_file", trust="untrusted", **k)  # fails type and trust
        self.assertEqual(check(req, s(enabled=False), evidence("other"))["reason"], "source_disabled")
        self.assertEqual(check(req, s(), evidence("other"))["reason"], "source_id_mismatch")
        self.assertEqual(check(req, s(), evidence())["reason"], "source_type_not_allowed")
        self.assertEqual(check(request(["source_type:local_file", "min_trust:trusted"]), s(),
                               evidence())["reason"], "min_trust_not_met")

    def test_deterministic_and_fresh(self):
        args = (request(["min_trust:trusted"]), source(), evidence())
        a, b = check(*args), check(*args)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)


class ImmutabilityTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        cases = [(request(["source_type:local_file", "min_trust:standard"]), source(), evidence()),
                 (request(["min_trust:trusted"]), source(), evidence("other")),
                 (request(["min_trust:bad"]), source(enabled=False), evidence()),
                 ({}, {}, {}), (request(), source(), {"evidence_id": "e"})]
        for args in cases:
            before = copy.deepcopy(args)
            check(*args)
            self.assertEqual(args, before)

    def test_evidence_is_never_repaired_to_become_valid(self):
        e = evidence()
        e["source_id"] = "other"
        r = check(request(), source(), e)
        self.assertEqual(r["reason"], "source_id_mismatch")
        self.assertEqual(e["source_id"], "other")

    def test_internal_failure_is_validation_error(self):
        args = (request(), source(), evidence())
        for name in ("validate_research_request", "validate_research_source",
                     "validate_research_evidence", "match_research_sources",
                     "evaluate_research_source_trust"):
            with mock.patch.object(m, name, side_effect=RuntimeError("x")):
                r = check(*args)
            self.assertEqual((r["status"], r["valid"], r["evidence_id"], r["source_id"], r["reason"]),
                             ("validation_error", False, None, None, "validation_error"), name)
            check_shape(self, r)

    def test_unexpected_helper_status_is_validation_error(self):
        args = (request(), source(), evidence())
        with mock.patch.object(m, "evaluate_research_source_trust",
                               return_value={"status": "weird"}):
            self.assertEqual(check(*args)["status"], "validation_error")


class ResultValidatorTests(unittest.TestCase):
    def good(self):
        return run()

    def test_validate_shape_flags_and_every_status(self):
        v = validate(self.good())
        self.assertEqual(list(v), VALIDATE_KEYS)
        self.assertEqual((v["valid"], v["errors"]), (True, []))
        self.assertIs(v["execution_allowed"], False)
        self.assertIs(v["executed"], False)
        outs = [run(), check({}, source(), evidence()), check(request(), {}, evidence()),
                check(request(), source(), {}), run(["source_type:web"]), run(["min_trust:x"])]
        with mock.patch.object(m, "validate_research_request", side_effect=ValueError):
            outs.append(run())
        for r in outs:
            self.assertTrue(validate(r)["valid"], r)
        self.assertEqual({r["status"] for r in outs}, set(m.STATUSES))
        reasons = {check(request(c), source(**k), evidence()) ["reason"] for c, k in (
            ([], {"enabled": False}), (["source_type:web"], {}), (["not:source_type:local_file"], {}),
            (["min_trust:trusted"], {}))}
        reasons.add(check(request(), source("a"), evidence("b"))["reason"])
        self.assertEqual(reasons, set(m._MISMATCH_REASONS))

    def test_rejects_non_dict_missing_and_fields(self):
        self.assertEqual(validate(None)["errors"][0]["code"], "missing_result")
        self.assertEqual(validate()["errors"][0]["code"], "missing_result")
        for value in ([], "x", 3, True):
            self.assertEqual(validate(value)["errors"][0]["code"], "result_not_dict")
        for key in KEYS:
            r = self.good(); del r[key]
            self.assertIn({"code": "missing_field", "where": key}, validate(r)["errors"])
        r = self.good(); r["extra"] = 1
        self.assertIn({"code": "unexpected_field", "where": "extra"}, validate(r)["errors"])

    def test_rejects_true_execution_flags(self):
        for key in ("execution_allowed", "executed"):
            for bad in (True, 1, 0, None, "False"):
                r = self.good(); r[key] = bad
                v = validate(r)
                self.assertFalse(v["valid"], (key, bad))
                self.assertIn({"code": "invalid_" + key, "where": key}, v["errors"])
                self.assertIs(v["execution_allowed"], False)
                self.assertIs(v["executed"], False)

    def test_rejects_bad_values_and_inconsistencies(self):
        def codes(r):
            return [e["code"] for e in validate(r)["errors"]]
        r = self.good(); r["status"] = "ok"; self.assertIn("invalid_status", codes(r))
        r = self.good(); r["valid"] = False; self.assertIn("invalid_valid", codes(r))
        r = self.good(); r["valid"] = 1; self.assertIn("invalid_valid", codes(r))
        r = self.good(); r["reason"] = "because"; self.assertIn("invalid_reason", codes(r))
        for bad in (None, "", 5, "x" * 65):
            r = self.good(); r["evidence_id"] = bad; self.assertIn("invalid_evidence_id", codes(r))
            r = self.good(); r["source_id"] = bad; self.assertIn("invalid_source_id", codes(r))
        r = self.good(); r["reason"] = "source_disabled"; self.assertIn("inconsistent_result", codes(r))
        r = run(["source_type:web"]); r["reason"] = "evidence_accepted"
        self.assertIn("inconsistent_result", codes(r))
        r = check({}, source(), evidence()); r["evidence_id"] = "leak"
        self.assertIn("invalid_evidence_id", codes(r))  # ids only for valid/context_mismatch
        r = check({}, source(), evidence()); r["source_id"] = "leak"
        self.assertIn("invalid_source_id", codes(r))

    def test_validate_does_not_mutate_or_raise(self):
        r = self.good(); before = copy.deepcopy(r)
        validate(r)
        self.assertEqual(r, before)
        r["source_id"] = object()
        self.assertFalse(validate(r)["valid"])


class IsolationTests(unittest.TestCase):
    def test_no_io_subprocess_or_network(self):
        def forbidden(*a, **k):
            raise AssertionError("forbidden call")
        args = (request(["source_type:local_file", "min_trust:standard"]), source(), evidence())
        with mock.patch.object(builtins, "open", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(os, "stat", forbidden):
            r = check(*args)
            validate(r)
            check()
        self.assertEqual(r["status"], "valid")

    def test_source_imports_and_public_api(self):
        with open(os.path.join(ROOT, "research", "research_evidence_validation.py"),
                  encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual(sorted(n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)),
                         ["research.research_evidence", "research.research_request",
                          "research.research_source", "research.research_source_matching",
                          "research.research_source_trust"])
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Import)])
        public = sorted(n.name for n in tree.body
                        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"))
        self.assertEqual(public, ["validate_research_evidence_context_result",
                                  "validate_research_evidence_for_context"])
        for word in ("retrieve", "fetch", "load", "lookup", "execute"):
            self.assertFalse([n for n in public if word in n], word)

    def test_no_new_constraint_syntax_or_parser(self):
        with open(os.path.join(ROOT, "research", "research_evidence_validation.py"),
                  encoding="utf-8") as fh:
            code = fh.read().split('"""')[2]
        for token in ("startswith", "split(", "re.", "PREFIX", "regex"):
            self.assertNotIn(token, code, token)


if __name__ == "__main__":
    unittest.main()
