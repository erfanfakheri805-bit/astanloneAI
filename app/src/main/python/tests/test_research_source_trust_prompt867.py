"""
Prompt 867 - research source trust evaluation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_research_source_trust_prompt867 -v
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

from research import research_source_trust as t
from research.research_request import build_research_request
from research.research_source import build_research_source
from research.research_source_trust import evaluate_research_source_trust as evaluate
from research.research_source_trust import validate_research_source_trust as validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["status", "trusted", "source_id", "trust_level", "reason",
        "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]


def request(constraints=()):
    r = build_research_request({
        "request_id": "res_001", "goal": "Understand retrieval-augmented generation.",
        "topics": ["rag basics"], "constraints": list(constraints), "requested_by": "developer"})
    assert r["valid"], r["errors"]
    return r["research_request"]


def source(trust="standard", enabled=True, sid="src_1", **over):
    d = {"source_id": sid, "source_type": "local_file", "location": "loc/" + sid,
         "trust_level": trust, "constraints": [], "enabled": enabled}
    d.update(over)
    r = build_research_source(d)
    assert r["valid"], r["errors"]
    return r["source"]


def check_shape(test, r):
    test.assertEqual(list(r), KEYS)
    test.assertIs(r["execution_allowed"], False)
    test.assertIs(r["executed"], False)
    json.dumps(r)
    test.assertEqual(validate(r)["errors"], [])


def ev(constraints, trust, **kw):
    r = evaluate(request(constraints), source(trust, **kw))
    check_shape(unittest.TestCase(), r)
    return r


class NoMinimumTests(unittest.TestCase):
    def test_every_level_passes_without_minimum_when_enabled(self):
        for level in ("trusted", "standard", "untrusted"):
            r = evaluate(request(), source(level))
            check_shape(self, r)
            self.assertEqual((r["status"], r["trusted"], r["reason"]),
                             ("trusted", True, "no_minimum_declared"), level)
            self.assertEqual((r["source_id"], r["trust_level"]), ("src_1", level))

    def test_unrelated_constraints_are_not_a_minimum(self):
        for c in ("source_type:web", "not:source_type:web", "Min_Trust:trusted",
                  "trust:trusted", "minimum trust trusted",
                  "not:min_trust:trusted", "xmin_trust:trusted"):
            r = evaluate(request([c]), source("untrusted"))
            self.assertEqual((r["status"], r["reason"]), ("trusted", "no_minimum_declared"), c)


class MinimumTests(unittest.TestCase):
    def test_trust_ordering_against_each_minimum(self):
        expected = {  # (minimum, level) -> trusted?
            ("trusted", "trusted"): True, ("trusted", "standard"): False,
            ("trusted", "untrusted"): False, ("standard", "trusted"): True,
            ("standard", "standard"): True, ("standard", "untrusted"): False,
            ("untrusted", "trusted"): True, ("untrusted", "standard"): True,
            ("untrusted", "untrusted"): True}
        for (minimum, level), ok in expected.items():
            r = ev(["min_trust:" + minimum], level)
            self.assertIs(r["trusted"], ok, (minimum, level))
            self.assertEqual(r["status"], "trusted" if ok else "not_trusted")
            self.assertEqual(r["reason"], "meets_minimum_trust" if ok else "below_minimum_trust")

    def test_trusted_source_meets_standard_minimum(self):
        r = ev(["min_trust:standard"], "trusted")
        self.assertEqual((r["status"], r["trust_level"]), ("trusted", "trusted"))

    def test_below_minimum_preserves_exact_id_and_level(self):
        r = evaluate(request(["min_trust:trusted"]), source("standard", sid="abc"))
        self.assertEqual((r["status"], r["trusted"], r["source_id"], r["trust_level"]),
                         ("not_trusted", False, "abc", "standard"))

    def test_multiple_minimums_highest_applies(self):
        cs = ["min_trust:untrusted", "min_trust:trusted", "min_trust:standard"]
        self.assertEqual(ev(cs, "standard")["status"], "not_trusted")
        self.assertEqual(ev(cs, "trusted")["status"], "trusted")
        self.assertEqual(ev(["min_trust:standard", "min_trust:standard"], "standard")["status"],
                         "trusted")

    def test_minimum_among_other_constraints(self):
        r = ev(["source_type:local_file", "min_trust:trusted", "x"], "standard")
        self.assertEqual(r["status"], "not_trusted")

    def test_unknown_or_malformed_minimum_makes_request_invalid(self):
        for c in ("min_trust:", "min_trust:high", "min_trust:Trusted", "min_trust:TRUSTED",
                  "min_trust: trusted", "min_trust:trusted:x"):
            r = evaluate(request([c]), source("trusted"))
            self.assertEqual((r["status"], r["trusted"], r["reason"]),
                             ("invalid_request", False, "invalid_request"), c)
            self.assertEqual((r["source_id"], r["trust_level"]), (None, None))

    def test_no_trust_upgrade_from_other_source_fields(self):
        s = source("untrusted", location="https://trusted.example/official", sid="trusted_src",
                   constraints=["trusted", "min_trust:untrusted"])
        s["source_type"] = "local_file"
        r = evaluate(request(["min_trust:standard"]), s)
        self.assertEqual((r["status"], r["trust_level"]), ("not_trusted", "untrusted"))
        for stype in ("local_file", "user_input", "learned_record", "web", "api", "external_model"):
            r = evaluate(request(["min_trust:trusted"]), source("standard", source_type=stype))
            self.assertEqual(r["status"], "not_trusted", stype)


class DisabledAndInvalidTests(unittest.TestCase):
    def test_disabled_source_is_not_trusted_with_or_without_minimum(self):
        for cs in ([], ["min_trust:untrusted"], ["min_trust:trusted"]):
            r = evaluate(request(cs), source("trusted", enabled=False))
            check_shape(self, r)
            self.assertEqual((r["status"], r["trusted"], r["reason"]),
                             ("not_trusted", False, "source_disabled"), cs)
            self.assertEqual((r["source_id"], r["trust_level"]), ("src_1", "trusted"))

    def test_invalid_request_is_never_trusted(self):
        good = request(["min_trust:untrusted"])
        bad = [None, {}, [], "x", 5, True]
        d = copy.deepcopy(good); d["execution_allowed"] = True; bad.append(d)
        d = copy.deepcopy(good); del d["goal"]; bad.append(d)
        d = copy.deepcopy(good); d["constraints"] = "min_trust:trusted"; bad.append(d)
        d = copy.deepcopy(good); d["extra"] = 1; bad.append(d)
        for value in bad:
            r = evaluate(value, source("trusted"))
            check_shape(self, r)
            self.assertEqual((r["status"], r["trusted"], r["source_id"], r["trust_level"],
                              r["reason"]), ("invalid_request", False, None, None, "invalid_request"))

    def test_invalid_source_is_never_trusted(self):
        good = source("trusted")
        bad = [None, {}, [], "x", 5, True]
        for key in good:
            d = copy.deepcopy(good); del d[key]; bad.append(d)
        d = copy.deepcopy(good); d["trust_level"] = "super"; bad.append(d)
        d = copy.deepcopy(good); d["enabled"] = 1; bad.append(d)
        d = copy.deepcopy(good); d["execution_allowed"] = True; bad.append(d)
        d = copy.deepcopy(good); d["extra"] = 1; bad.append(d)
        d = copy.deepcopy(good); d["source_id"] = ""; bad.append(d)
        for value in bad:
            r = evaluate(request(), value)
            check_shape(self, r)
            self.assertEqual((r["status"], r["trusted"], r["source_id"], r["trust_level"],
                              r["reason"]), ("invalid_source", False, None, None, "invalid_source"))

    def test_invalid_request_checked_before_invalid_source(self):
        r = evaluate(None, None)
        self.assertEqual(r["status"], "invalid_request")
        self.assertEqual(evaluate()["status"], "invalid_request")
        self.assertEqual(evaluate(request())["status"], "invalid_source")

    def test_internal_failure_is_trust_evaluation_error(self):
        with mock.patch.object(t, "validate_research_request", side_effect=RuntimeError("x")):
            r = evaluate(request(), source())
        self.assertEqual((r["status"], r["trusted"], r["source_id"], r["trust_level"], r["reason"]),
                         ("trust_evaluation_error", False, None, None, "trust_evaluation_error"))
        check_shape(self, r)


class ImmutabilityTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        req = request(["min_trust:standard", "other"])
        src = source("trusted")
        src["constraints"].append("c")
        rb, sb = copy.deepcopy(req), copy.deepcopy(src)
        evaluate(req, src)
        evaluate(req, dict(src, enabled=False))
        self.assertEqual((req, src), (rb, sb))

    def test_invalid_inputs_not_mutated(self):
        req, src = request(["min_trust:bogus"]), source("trusted")
        src["trust_level"] = "nope"
        rb, sb = copy.deepcopy(req), copy.deepcopy(src)
        evaluate(req, src)
        evaluate(request(), src)
        self.assertEqual((req, src), (rb, sb))

    def test_result_is_fresh_and_deterministic(self):
        req, src = request(["min_trust:standard"]), source("trusted")
        a, b = evaluate(req, src), evaluate(req, src)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)


class ValidationTests(unittest.TestCase):
    def good(self):
        return evaluate(request(["min_trust:standard"]), source("trusted"))

    def test_validate_shape_flags_and_all_statuses(self):
        v = validate(self.good())
        self.assertEqual(list(v), VALIDATE_KEYS)
        self.assertEqual((v["valid"], v["errors"]), (True, []))
        self.assertIs(v["execution_allowed"], False)
        self.assertIs(v["executed"], False)
        seen = set()
        outs = [evaluate(request(), source()), evaluate(request(["min_trust:trusted"]), source()),
                evaluate(None, source()), evaluate(request(), None)]
        with mock.patch.object(t, "validate_research_request", side_effect=ValueError):
            outs.append(evaluate(request(), source()))
        for r in outs:
            self.assertTrue(validate(r)["valid"], r)
            seen.add(r["status"])
        self.assertEqual(seen, set(t.STATUSES))

    def test_rejects_non_dict_and_missing(self):
        self.assertEqual(validate(None)["errors"][0]["code"], "missing_result")
        self.assertEqual(validate()["errors"][0]["code"], "missing_result")
        for value in ([], "x", 3, True):
            self.assertEqual(validate(value)["errors"][0]["code"], "result_not_dict")

    def test_rejects_missing_and_unexpected_fields(self):
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

    def test_rejects_bad_fields(self):
        def codes(r):
            return [e["code"] for e in validate(r)["errors"]]
        r = self.good(); r["status"] = "ok"; self.assertIn("invalid_status", codes(r))
        r = self.good(); r["trusted"] = 1; self.assertIn("invalid_trusted", codes(r))
        r = self.good(); r["trusted"] = False; self.assertIn("invalid_trusted", codes(r))
        r = self.good(); r["reason"] = "because"; self.assertIn("invalid_reason", codes(r))
        for bad in (None, "", 5, "x" * 65):
            r = self.good(); r["source_id"] = bad; self.assertIn("invalid_source_id", codes(r))
        for bad in (None, "super", "Trusted", 1):
            r = self.good(); r["trust_level"] = bad; self.assertIn("invalid_trust_level", codes(r))
        r = evaluate(None, None); r["source_id"] = "a"
        self.assertIn("invalid_source_id", codes(r))
        r = evaluate(None, None); r["trust_level"] = "trusted"
        self.assertIn("invalid_trust_level", codes(r))

    def test_rejects_inconsistent_combinations(self):
        r = self.good(); r["reason"] = "source_disabled"
        self.assertIn("inconsistent_result", [e["code"] for e in validate(r)["errors"]])
        r = evaluate(request(["min_trust:trusted"]), source("standard")); r["reason"] = "meets_minimum_trust"
        self.assertFalse(validate(r)["valid"])
        r = evaluate(request(["min_trust:trusted"]), source("standard")); r["trust_level"] = "trusted"
        self.assertFalse(validate(r)["valid"])  # "trusted" can never be below a minimum
        r = evaluate(None, None); r["reason"] = "invalid_source"
        self.assertFalse(validate(r)["valid"])

    def test_validate_never_mutates_or_raises(self):
        r = self.good(); before = copy.deepcopy(r)
        validate(r)
        self.assertEqual(r, before)
        r["source_id"] = object()
        self.assertFalse(validate(r)["valid"])


class IsolationTests(unittest.TestCase):
    def test_no_io_subprocess_or_network(self):
        def forbidden(*a, **k):
            raise AssertionError("forbidden call")
        req, src = request(["min_trust:standard"]), source("trusted")
        with mock.patch.object(builtins, "open", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(os, "stat", forbidden):
            r = evaluate(req, src)
            validate(r)
            evaluate(None, None)
        self.assertEqual(r["status"], "trusted")

    def test_source_imports_and_public_api(self):
        with open(os.path.join(ROOT, "research", "research_source_trust.py"),
                  encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual(sorted(n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)),
                         ["research.research_request", "research.research_source"])
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Import)])
        public = sorted(n.name for n in tree.body
                        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"))
        self.assertEqual(public, ["evaluate_research_source_trust", "validate_research_source_trust"])
        text = ast.dump(tree)
        for word in ("research_source_matching", "research_source_selection"):
            self.assertNotIn(word, text)  # no matching or selection is performed here

    def test_trust_order_comes_from_the_source_contract(self):
        from research.research_source import TRUST_LEVELS
        self.assertEqual(TRUST_LEVELS, ("untrusted", "standard", "trusted"))
        self.assertIs(t.TRUST_LEVELS, TRUST_LEVELS)


if __name__ == "__main__":
    unittest.main()
