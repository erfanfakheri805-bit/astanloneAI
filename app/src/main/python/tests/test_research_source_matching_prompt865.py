"""
Prompt 865 - research source matching focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_research_source_matching_prompt865 -v
"""

import ast
import copy
import json
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research import research_source_matching as m
from research.research_request import build_research_request
from research.research_source import build_research_source
from research.research_source_matching import match_research_sources as match
from research.research_source_matching import validate_research_source_match as validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["status", "matched", "candidate_count", "matches", "rejected",
        "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]


def request(constraints=()):
    r = build_research_request({
        "request_id": "res_001", "goal": "Understand retrieval-augmented generation.",
        "topics": ["rag basics"], "constraints": list(constraints), "requested_by": "developer"})
    assert r["valid"], r["errors"]
    return r["research_request"]


def source(sid="src_1", stype="local_file", enabled=True, constraints=(), **over):
    d = {"source_id": sid, "source_type": stype, "location": "loc/" + sid,
         "trust_level": "standard", "constraints": list(constraints), "enabled": enabled}
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


def ids(items):
    return [i["source_id"] for i in items]


class MatchedTests(unittest.TestCase):
    def test_enabled_valid_sources_match_when_request_has_no_type_constraint(self):
        r = match(request(), [source("a"), source("b", "web")])
        check_shape(self, r)
        self.assertEqual((r["status"], r["matched"], r["candidate_count"]), ("matched", True, 2))
        self.assertEqual(ids(r["matches"]), ["a", "b"])
        self.assertEqual(r["rejected"], [])

    def test_declaration_order_preserved(self):
        srcs = [source(s) for s in ("z", "a", "m", "b")]
        self.assertEqual(ids(match(request(), srcs)["matches"]), ["z", "a", "m", "b"])

    def test_disabled_source_rejected(self):
        r = match(request(), [source("a", enabled=False), source("b")])
        check_shape(self, r)
        self.assertEqual(ids(r["matches"]), ["b"])
        self.assertEqual(r["rejected"], [{"source_id": "a", "reason": "disabled"}])
        self.assertEqual(r["candidate_count"], 2)

    def test_allow_list_selects_only_listed_types(self):
        req = request(["source_type:local_file", "source_type:api"])
        r = match(req, [source("a", "local_file"), source("b", "web"), source("c", "api")])
        self.assertEqual(ids(r["matches"]), ["a", "c"])
        self.assertEqual(r["rejected"], [{"source_id": "b", "reason": "source_type_not_allowed"}])
        for t in ("local_file", "user_input", "learned_record", "web", "api", "external_model"):
            self.assertEqual(match(request(["source_type:" + t]), [source("a", t)])["status"],
                             "matched", t)

    def test_exclusion_rejects_type_even_without_allow_list(self):
        r = match(request(["not:source_type:web"]), [source("a", "web"), source("b", "api")])
        self.assertEqual(ids(r["matches"]), ["b"])
        self.assertEqual(r["rejected"], [{"source_id": "a", "reason": "source_type_excluded"}])
        both = match(request(["source_type:web", "not:source_type:web"]), [source("a", "web")])
        self.assertEqual((both["status"], both["rejected"][0]["reason"]),
                         ("no_match", "source_type_excluded"))  # exclusion wins over allow

    def test_exact_negation_is_a_conflict(self):
        r = match(request(["Peer-reviewed only."]),
                  [source("a", constraints=["not:Peer-reviewed only."]), source("b")])
        self.assertEqual(ids(r["matches"]), ["b"])
        self.assertEqual(r["rejected"], [{"source_id": "a", "reason": "constraint_conflict"}])
        r = match(request(["not:Read-only."]), [source("a", constraints=["Read-only."])])
        self.assertEqual(r["rejected"][0]["reason"], "constraint_conflict")  # either direction

    def test_only_exact_negation_conflicts_no_fuzzy_matching(self):
        req = request(["Peer-reviewed only."])
        for near in ("not: Peer-reviewed only.", "NOT:Peer-reviewed only.", "not:peer-reviewed only.",
                     "Not peer-reviewed only.", "Peer-reviewed only.", "unrelated"):
            self.assertEqual(match(req, [source("a", constraints=[near])])["status"], "matched",
                             near)

    def test_type_constraint_matching_is_exact_and_case_sensitive(self):
        # "Source_Type:web" is just an ordinary constraint, not a type rule
        r = match(request(["Source_Type:web"]), [source("a", "api")])
        self.assertEqual(r["status"], "matched")

    def test_trust_level_and_location_do_not_influence_matching(self):
        srcs = [source("a", trust_level="untrusted", location="https://example.invalid/x"),
                source("b", trust_level="trusted", location="/no/such/file")]
        self.assertEqual(ids(match(request(), srcs)["matches"]), ["a", "b"])


class OutcomeStatusTests(unittest.TestCase):
    def test_no_match_when_all_rejected(self):
        r = match(request(), [source("a", enabled=False), source("b", enabled=False)])
        check_shape(self, r)
        self.assertEqual((r["status"], r["matched"], r["candidate_count"]), ("no_match", False, 2))
        self.assertEqual(r["matches"], [])
        self.assertEqual(ids(r["rejected"]), ["a", "b"])

    def test_empty_sources_is_no_valid_match(self):
        r = match(request(), [])
        check_shape(self, r)
        self.assertEqual((r["status"], r["matched"], r["candidate_count"]),
                         ("no_valid_match", False, 0))
        self.assertEqual((r["matches"], r["rejected"]), ([], []))

    def test_first_failing_rule_decides_reason(self):
        req = request(["not:source_type:web", "x"])
        r = match(req, [source("a", "web", enabled=False, constraints=["not:x"])])
        self.assertEqual(r["rejected"][0]["reason"], "disabled")
        r = match(req, [source("a", "web", constraints=["not:x"])])
        self.assertEqual(r["rejected"][0]["reason"], "source_type_excluded")


class InvalidInputTests(unittest.TestCase):
    def test_invalid_request(self):
        self.assertEqual(match(None, None)["status"], "invalid_request")  # request checked first
        for bad in (None, {}, [], "x", dict(request(), execution_allowed=True),
                    dict(request(), topics=[]), dict(request(), extra=1)):
            r = match(bad, [source("a")])
            check_shape(self, r)
            self.assertEqual((r["status"], r["matched"], r["candidate_count"]),
                             ("invalid_request", False, 0))
            self.assertEqual((r["matches"], r["rejected"]), ([], []))

    def test_malformed_source_type_constraint_rejects_request(self):
        for bad in ("source_type:ftp", "source_type:", "source_type:Web", "not:source_type:",
                    "not:source_type:ftp"):
            r = match(request([bad]), [source("a")])
            self.assertEqual(r["status"], "invalid_request", bad)

    def test_invalid_sources(self):
        good = source("a")
        for bad in (None, (good,), "x", {"a": good}, [None], [{}], [dict(good, enabled=1)],
                    [dict(good, execution_allowed=True)], [good, dict(good, extra=1)],
                    [good, good]):
            r = match(request(), bad)
            check_shape(self, r)
            self.assertEqual((r["status"], r["candidate_count"]), ("invalid_sources", 0), bad)
            self.assertEqual((r["matches"], r["rejected"]), ([], []))
        r = match(request(), [source("a"), {"source_id": "b"}])  # nothing is skipped
        self.assertEqual((r["status"], r["matches"]), ("invalid_sources", []))

    def test_too_many_sources(self):
        srcs = [source("s%d" % i) for i in range(m.MAX_SOURCES + 1)]
        self.assertEqual(match(request(), srcs)["status"], "invalid_sources")
        self.assertEqual(match(request(), srcs[:m.MAX_SOURCES])["candidate_count"], m.MAX_SOURCES)

    def test_matching_error_on_unexpected_failure(self):
        with mock.patch.object(m, "_rejection", side_effect=RuntimeError("boom")):
            r = match(request(), [source("a")])
        check_shape(self, r)
        self.assertEqual((r["status"], r["matched"], r["candidate_count"]), ("matching_error", False, 0))

    def test_never_raises_on_hostile_input(self):
        class Boom(dict):
            def __len__(self):
                raise RuntimeError("boom")
        for args in ((), (Boom(), Boom()), (request(), Boom()), (request(), [Boom()]),
                     (object(), object())):
            r = match(*args)
            self.assertEqual(list(r), KEYS)
            self.assertFalse(r["matched"])


class IsolationTests(unittest.TestCase):
    def test_inputs_never_mutated_and_results_fresh(self):
        req = request(["source_type:local_file", "k"])
        srcs = [source("a", constraints=["c"]), source("b", "web")]
        snap = copy.deepcopy((req, srcs))
        a, b = match(req, srcs), match(req, srcs)
        self.assertEqual((req, srcs), snap)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["matches"][0], srcs[0])
        self.assertIsNot(a["matches"][0]["constraints"], srcs[0]["constraints"])
        a["matches"][0]["constraints"].append("mutated")
        a["matches"][0]["enabled"] = False
        self.assertEqual((req, srcs), snap)

    def test_flags_always_false_for_every_status(self):
        good = source("a")
        cases = [match(request(), [good]), match(request(), [source("a", enabled=False)]),
                 match(request(), []), match(None, [good]), match(request(), None)]
        self.assertEqual([c["status"] for c in cases],
                         ["matched", "no_match", "no_valid_match", "invalid_request",
                          "invalid_sources"])
        for c in cases:
            self.assertIs(c["execution_allowed"], False)
            self.assertIs(c["executed"], False)

    def test_matching_does_not_touch_the_filesystem_or_network(self):
        def forbidden(*a, **k):
            raise AssertionError("forbidden side effect")
        import builtins, socket, subprocess
        with mock.patch.object(builtins, "open", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(os, "stat", forbidden):
            r = match(request(), [source("a", "local_file", location="/etc/passwd"),
                                  source("b", "web", location="https://example.invalid/")])
        self.assertEqual(r["status"], "matched")

    def test_module_imports_only_public_research_validators(self):
        with open(os.path.join(ROOT, "research", "research_source_matching.py"),
                  encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [(n.module, [a.name for a in n.names]) for n in ast.walk(tree)
                   if isinstance(n, ast.ImportFrom)]
        self.assertEqual(sorted(imports), [
            ("research.research_request", ["validate_research_request"]),
            ("research.research_source", ["SOURCE_TYPES", "validate_research_source"])])
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Import)])
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__"})


class ValidateMatchTests(unittest.TestCase):
    def setUp(self):
        self.ok = match(request(), [source("a"), source("b", enabled=False)])

    def errors(self, result):
        r = validate(result)
        self.assertEqual(list(r), VALIDATE_KEYS)
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)
        return [e["code"] for e in r["errors"]]

    def test_every_status_result_validates(self):
        for r in (self.ok, match(request(), []), match(request(), [source("a", enabled=False)]),
                  match(None, None), match(request(), None)):
            self.assertEqual(self.errors(r), [], r["status"])

    def test_missing_non_dict_and_field_errors(self):
        self.assertEqual(self.errors(None), ["missing_result"])
        self.assertEqual(self.errors([]), ["result_not_dict"])
        self.assertIn("unexpected_field", self.errors(dict(self.ok, extra=1)))
        for key in KEYS:
            r = dict(self.ok)
            del r[key]
            self.assertIn("missing_field", self.errors(r))

    def test_status_matched_and_count_checks(self):
        self.assertIn("invalid_status", self.errors(dict(self.ok, status="found")))
        self.assertIn("invalid_matched", self.errors(dict(self.ok, matched=False)))
        self.assertIn("invalid_matched", self.errors(dict(self.ok, matched=1)))
        for bad in (True, -1, 99, "2", None):
            self.assertIn("invalid_candidate_count", self.errors(dict(self.ok, candidate_count=bad)))
        self.assertEqual(self.errors(dict(self.ok, candidate_count=5)), ["inconsistent_result"])

    def test_flags_must_be_exactly_false(self):
        for key in ("execution_allowed", "executed"):
            for bad in (True, 0, None):
                self.assertEqual(self.errors(dict(self.ok, **{key: bad})), ["invalid_" + key])

    def test_matches_and_rejections_checked(self):
        bad_match = dict(self.ok["matches"][0], enabled=False)
        self.assertEqual(self.errors(dict(self.ok, matches=[bad_match])), ["invalid_match"])
        self.assertEqual(self.errors(dict(self.ok, matches=[{"source_id": "a"}])), ["invalid_match"])
        self.assertEqual(self.errors(dict(self.ok, rejected=[{"source_id": "b", "reason": "x"}])),
                         ["invalid_rejection"])
        self.assertEqual(self.errors(dict(self.ok, rejected=[{"reason": "disabled", "source_id": "b"}])),
                         ["invalid_rejection"])
        self.assertEqual(self.errors(dict(self.ok, matches="x")), ["invalid_matches"])
        self.assertEqual(self.errors(dict(self.ok, rejected=None)), ["invalid_rejected"])

    def test_duplicate_ids_and_per_status_shape(self):
        dup = dict(self.ok, rejected=[{"source_id": "a", "reason": "disabled"}])
        self.assertEqual(self.errors(dup), ["duplicate_source_id"])
        self.assertEqual(self.errors(dict(self.ok, matches=[], candidate_count=1)),
                         ["inconsistent_result"])
        no_match = match(request(), [source("z", enabled=False)])
        self.assertEqual(self.errors(dict(no_match, matches=self.ok["matches"], candidate_count=2)),
                         ["inconsistent_result"])
        empty = match(request(), [])
        self.assertEqual(self.errors(dict(empty, candidate_count=1)), ["inconsistent_result"])

    def test_validation_never_repairs_or_mutates(self):
        bad = dict(self.ok, matched=False, status="found")
        snap = copy.deepcopy(bad)
        self.assertFalse(validate(bad)["valid"])
        self.assertEqual(bad, snap)

        class Boom(dict):
            def __len__(self):
                raise RuntimeError("boom")
        self.assertFalse(validate(Boom())["valid"])  # never raises



if __name__ == "__main__":
    unittest.main()
