"""
Prompt 866 - research source selection focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_research_source_selection_prompt866 -v
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

from research import research_source_selection as s
from research.research_request import build_research_request
from research.research_source import build_research_source
from research.research_source_matching import match_research_sources
from research.research_source_selection import select_research_source as select
from research.research_source_selection import validate_research_source_selection as validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["status", "selected", "candidate_count", "reason", "execution_allowed", "executed"]
VALIDATE_KEYS = ["valid", "errors", "execution_allowed", "executed"]


def request(constraints=()):
    r = build_research_request({
        "request_id": "res_001", "goal": "Understand retrieval-augmented generation.",
        "topics": ["rag basics"], "constraints": list(constraints), "requested_by": "developer"})
    assert r["valid"], r["errors"]
    return r["research_request"]


def source(sid="src_1", trust="standard", stype="local_file", enabled=True, constraints=()):
    r = build_research_source({
        "source_id": sid, "source_type": stype, "location": "loc/" + sid,
        "trust_level": trust, "constraints": list(constraints), "enabled": enabled})
    assert r["valid"], r["errors"]
    return r["source"]


def matched(*sources, constraints=()):
    return match_research_sources(request(constraints), list(sources))


def check_shape(test, r):
    test.assertEqual(list(r), KEYS)
    test.assertIs(r["execution_allowed"], False)
    test.assertIs(r["executed"], False)
    json.dumps(r)
    test.assertEqual(validate(r)["errors"], [])


class SelectionTests(unittest.TestCase):
    def test_single_match_is_selected(self):
        r = select(matched(source("a")))
        check_shape(self, r)
        self.assertEqual((r["status"], r["candidate_count"], r["reason"]),
                         ("selected", 1, "highest_trust_level"))
        self.assertEqual(r["selected"]["source_id"], "a")

    def test_trusted_beats_standard_and_untrusted(self):
        r = select(matched(source("u", "untrusted"), source("s", "standard"),
                           source("t", "trusted")))
        check_shape(self, r)
        self.assertEqual(r["selected"]["source_id"], "t")
        self.assertEqual(r["candidate_count"], 3)

    def test_standard_beats_untrusted(self):
        r = select(matched(source("u", "untrusted"), source("s", "standard")))
        self.assertEqual(r["selected"]["source_id"], "s")

    def test_trusted_later_in_list_still_wins(self):
        r = select(matched(source("a", "standard"), source("b", "standard"),
                           source("c", "trusted")))
        self.assertEqual(r["selected"]["source_id"], "c")

    def test_equal_trust_keeps_original_order(self):
        for trust in ("trusted", "standard", "untrusted"):
            r = select(matched(source("z", trust), source("a", trust), source("m", trust)))
            self.assertEqual(r["selected"]["source_id"], "z", trust)

    def test_equal_top_trust_picks_first_of_the_top_group(self):
        r = select(matched(source("a", "untrusted"), source("b", "trusted"),
                           source("c", "standard"), source("d", "trusted")))
        self.assertEqual(r["selected"]["source_id"], "b")

    def test_rejected_sources_are_never_selected(self):
        r = select(matched(source("t", "trusted", enabled=False), source("s", "standard")))
        self.assertEqual(r["selected"]["source_id"], "s")
        self.assertEqual(r["candidate_count"], 1)

    def test_selected_is_a_deep_copy(self):
        m = matched(source("a", constraints=["c1"]))
        r = select(m)
        self.assertEqual(r["selected"], m["matches"][0])
        self.assertIsNot(r["selected"], m["matches"][0])
        self.assertIsNot(r["selected"]["constraints"], m["matches"][0]["constraints"])
        r["selected"]["constraints"].append("x")
        r["selected"]["trust_level"] = "untrusted"
        self.assertEqual(m["matches"][0]["constraints"], ["c1"])
        self.assertEqual(m["matches"][0]["trust_level"], "standard")

    def test_fresh_result_every_call_and_deterministic(self):
        m = matched(source("a", "trusted"), source("b"))
        r1, r2 = select(m), select(m)
        self.assertEqual(r1, r2)
        self.assertIsNot(r1, r2)
        self.assertIsNot(r1["selected"], r2["selected"])


class NoSelectionTests(unittest.TestCase):
    def assert_none(self, r, status, reason):
        check_shape(self, r) if status != "invalid_input" else self.assertEqual(list(r), KEYS)
        self.assertEqual((r["status"], r["selected"], r["candidate_count"], r["reason"]),
                         (status, None, 0, reason))
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)

    def test_no_match_status_selects_nothing(self):
        m = matched(source("a", enabled=False))
        self.assertEqual(m["status"], "no_match")
        self.assert_none(select(m), "not_selected", "match_status_not_matched")

    def test_no_valid_match_status_selects_nothing(self):
        m = match_research_sources(request(), [])
        self.assertEqual(m["status"], "no_valid_match")
        self.assert_none(select(m), "not_selected", "match_status_not_matched")

    def test_other_valid_non_matched_statuses_select_nothing(self):
        for m in (match_research_sources(None, []),
                  match_research_sources(request(), "not a list")):
            self.assertIn(m["status"], ("invalid_request", "invalid_sources"))
            self.assert_none(select(m), "not_selected", "match_status_not_matched")

    def test_empty_matches_in_matched_status_is_invalid_input(self):
        m = matched(source("a"))
        m["matches"] = []
        m["candidate_count"] = 0
        self.assert_none(select(m), "invalid_input", "invalid_match_result")

    def test_invalid_inputs(self):
        good = matched(source("a"))
        bad = []
        for key in good:
            d = copy.deepcopy(good)
            del d[key]
            bad.append(d)
        d = copy.deepcopy(good); d["extra"] = 1; bad.append(d)
        d = copy.deepcopy(good); d["execution_allowed"] = True; bad.append(d)
        d = copy.deepcopy(good); d["executed"] = True; bad.append(d)
        d = copy.deepcopy(good); d["status"] = "bogus"; bad.append(d)
        d = copy.deepcopy(good); d["candidate_count"] = True; bad.append(d)
        for value in (None, {}, [], "matched", 5, 1.5, True, (), object(), [good]):
            bad.append(value)
        for value in bad:
            self.assert_none(select(value), "invalid_input", "invalid_match_result")
        self.assert_none(select(), "invalid_input", "invalid_match_result")

    def test_malformed_matches_are_invalid_input(self):
        cases = []
        d = matched(source("a")); d["matches"][0]["trust_level"] = "super"; cases.append(d)
        d = matched(source("a")); d["matches"][0]["enabled"] = False; cases.append(d)
        d = matched(source("a")); d["matches"][0]["execution_allowed"] = True; cases.append(d)
        d = matched(source("a")); d["matches"] = "a"; cases.append(d)
        d = matched(source("a")); d["matches"] = [None]; cases.append(d)
        d = matched(source("a"), source("b")); d["matches"][1]["source_id"] = "a"; cases.append(d)
        d = matched(source("a")); d["matches"][0]["location"] = ""; cases.append(d)
        for d in cases:
            self.assert_none(select(d), "invalid_input", "invalid_match_result")

    def test_internal_failure_is_selection_error(self):
        with mock.patch.object(s, "validate_research_source_match", side_effect=RuntimeError("x")):
            r = select(matched(source("a")))
        self.assertEqual((r["status"], r["selected"], r["candidate_count"], r["reason"]),
                         ("selection_error", None, 0, "selection_error"))
        self.assertEqual(list(r), KEYS)
        self.assertEqual(validate(r)["errors"], [])


class ImmutabilityTests(unittest.TestCase):
    def test_input_not_mutated(self):
        m = matched(source("a", "untrusted"), source("b", "trusted", constraints=["k"]),
                    source("c", "standard"))
        before = copy.deepcopy(m)
        select(m)
        self.assertEqual(m, before)

    def test_invalid_input_not_mutated(self):
        m = matched(source("a"))
        m["matches"][0]["trust_level"] = "bogus"
        before = copy.deepcopy(m)
        select(m)
        self.assertEqual(m, before)

    def test_input_unchanged_after_mutating_result(self):
        m = matched(source("a", "trusted"))
        before = copy.deepcopy(m)
        r = select(m)
        r["selected"]["source_id"] = "changed"
        self.assertEqual(m, before)


class ValidationTests(unittest.TestCase):
    def good(self):
        return select(matched(source("a", "trusted"), source("b")))

    def test_validate_shape_and_flags(self):
        v = validate(self.good())
        self.assertEqual(list(v), VALIDATE_KEYS)
        self.assertEqual((v["valid"], v["errors"]), (True, []))
        self.assertIs(v["execution_allowed"], False)
        self.assertIs(v["executed"], False)
        for r in (select(None), select(matched(source("a", enabled=False)))):
            self.assertTrue(validate(r)["valid"])

    def test_every_status_validates(self):
        outcomes = {select(matched(source("a")))["status"],
                    select(None)["status"],
                    select(matched(source("a", enabled=False)))["status"]}
        with mock.patch.object(s, "validate_research_source_match", side_effect=ValueError):
            outcomes.add(select(matched(source("a")))["status"])
        self.assertEqual(outcomes, set(s.STATUSES))

    def test_rejects_non_dict_and_missing(self):
        self.assertEqual(validate(None)["errors"][0]["code"], "missing_result")
        self.assertEqual(validate()["errors"][0]["code"], "missing_result")
        for value in ([], "x", 3, True):
            v = validate(value)
            self.assertFalse(v["valid"])
            self.assertEqual(v["errors"][0]["code"], "result_not_dict")

    def test_rejects_missing_and_unexpected_fields(self):
        for key in KEYS:
            r = self.good(); del r[key]
            v = validate(r)
            self.assertFalse(v["valid"])
            self.assertIn({"code": "missing_field", "where": key}, v["errors"])
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

    def test_rejects_bad_status_reason_count_selected(self):
        r = self.good(); r["status"] = "done"
        self.assertIn("invalid_status", [e["code"] for e in validate(r)["errors"]])
        r = self.good(); r["reason"] = "because"
        self.assertIn("invalid_reason", [e["code"] for e in validate(r)["errors"]])
        for bad in (True, -1, 33, 1.0, "1", None):
            r = self.good(); r["candidate_count"] = bad
            self.assertIn("invalid_candidate_count", [e["code"] for e in validate(r)["errors"]])
        for bad in ("a", {}, [], {"source_id": "a"}):
            r = self.good(); r["selected"] = bad
            self.assertIn("invalid_selected", [e["code"] for e in validate(r)["errors"]])
        r = self.good(); r["selected"]["enabled"] = False
        self.assertIn("invalid_selected", [e["code"] for e in validate(r)["errors"]])
        r = self.good(); r["selected"]["trust_level"] = "super"
        self.assertFalse(validate(r)["valid"])

    def test_rejects_inconsistent_combinations(self):
        r = self.good(); r["selected"] = None
        self.assertIn("inconsistent_result", [e["code"] for e in validate(r)["errors"]])
        r = self.good(); r["candidate_count"] = 0
        self.assertIn("inconsistent_result", [e["code"] for e in validate(r)["errors"]])
        r = self.good(); r["reason"] = "no_matches"
        self.assertIn("inconsistent_result", [e["code"] for e in validate(r)["errors"]])
        r = select(None); r["selected"] = source("a")
        self.assertFalse(validate(r)["valid"])
        r = select(None); r["candidate_count"] = 1
        self.assertFalse(validate(r)["valid"])
        r = select(None); r["status"] = "not_selected"
        self.assertFalse(validate(r)["valid"])

    def test_validate_does_not_mutate_and_never_raises(self):
        r = self.good()
        before = copy.deepcopy(r)
        validate(r)
        self.assertEqual(r, before)
        r["selected"] = object()
        self.assertFalse(validate(r)["valid"])
        with mock.patch.object(s, "validate_research_source", side_effect=RuntimeError):
            self.assertEqual(validate(self.good())["errors"][0]["code"], "validation_error")


class IsolationTests(unittest.TestCase):
    def test_no_io_subprocess_or_network(self):
        def forbidden(*a, **k):
            raise AssertionError("forbidden call")
        m = matched(source("a", "trusted"))
        with mock.patch.object(builtins, "open", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(os, "stat", forbidden):
            r = select(m)
            validate(r)
            select(None)
        self.assertEqual(r["status"], "selected")

    def test_source_imports_and_public_api(self):
        with open(os.path.join(ROOT, "research", "research_source_selection.py"),
                  encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        modules = sorted(n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))
        self.assertEqual(modules, ["research.research_source", "research.research_source_matching"])
        self.assertEqual([a.name for n in ast.walk(tree) if isinstance(n, ast.Import)
                          for a in n.names], ["copy"])
        public = sorted(n.name for n in tree.body
                        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"))
        self.assertEqual(public, ["select_research_source", "validate_research_source_selection"])
        for word in ("execute", "load", "fetch", "retrieve", "open", "discover"):
            self.assertFalse([n for n in public if word in n], word)

    def test_trust_order_comes_from_the_source_contract(self):
        from research.research_source import TRUST_LEVELS
        self.assertEqual(TRUST_LEVELS, ("untrusted", "standard", "trusted"))


if __name__ == "__main__":
    unittest.main()
