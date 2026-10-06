"""
Tests for Prompt 929 - Reasoning Decision Candidate.

`build_reasoning_decision_candidate(consumption_result)` exposes a small,
non-actionable decision candidate (decision / plan / capability_boundary) from
a valid consumed result. Nothing is executed. RuntimeCore stores the latest
candidate and clears it every turn.

Run directly:
    python -m unittest tests.test_reasoning_decision_candidate_prompt929 -v
"""

import copy
import json
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_integration import bridge as ri
from tests.test_reasoning_handoff_prompt918 import HandoffCase, INTRO, QUESTION

UNAVAILABLE = {"available": False, "status": "unavailable", "actionable": False,
               "executed": False, "descriptive_only": True}
build = ri.build_reasoning_decision_candidate


class TestCandidate(HandoffCase):
    def consumed(self, text=INTRO):
        self.core.process_input(text)
        return self.core.last_runtime_result["reasoning"]["reasoning_consumption_result"]

    def test_valid_consumed_result(self):
        for text in (INTRO, QUESTION):
            result = self.consumed(text)
            cand = build(result)
            self.assertIs(cand["available"], True)
            self.assertEqual(cand["status"], "decision_candidate")
            self.assertIs(cand["actionable"], False)
            self.assertIs(cand["executed"], False)
            self.assertIs(cand["descriptive_only"], True)
            self.assertEqual(set(cand), {"available", "status", "actionable", "executed",
                                         "descriptive_only", "decision", "plan", "capability_boundary"})
            inner = result["internal_input"]
            for key in ("decision", "plan", "capability_boundary"):
                self.assertEqual(cand[key], inner[key], key)
                self.assertIsNot(cand[key], inner[key], key)
            section = self.core.last_runtime_result["reasoning"]
            self.assertEqual(section["reasoning_decision_candidate"], cand)
            json.dumps(cand)

    def test_invalid_and_unavailable(self):
        self.assertEqual(build(ri.consume_internal_reasoning_input(None)), UNAVAILABLE)
        self.core.process_input("TEACH sun IS a star")
        self.assertNotIn("reasoning_decision_candidate", self.core.last_runtime_result["reasoning"])
        good = self.consumed()
        for bad in (None, "x", 1, [], {}, {"available": True}, good["internal_input"]):
            self.assertEqual(build(bad), UNAVAILABLE, bad)
        for mutate in (lambda d: d.pop("internal_input"), lambda d: d.update(internal_input=None),
                       lambda d: d.update(status="x"), lambda d: d.update(available=False),
                       lambda d: d.update(descriptive_only=False),
                       lambda d: d["internal_input"].update(status="x"),
                       lambda d: d["internal_input"].update(plan=None),
                       lambda d: d["internal_input"].pop("decision"),
                       lambda d: d["internal_input"].pop("capability_boundary")):
            d = copy.deepcopy(good)
            mutate(d)
            self.assertEqual(build(d), UNAVAILABLE)

    def test_executed_result(self):
        good = self.consumed()
        d = copy.deepcopy(good)
        d["executed"] = True
        self.assertEqual(build(d), UNAVAILABLE)
        d = copy.deepcopy(good)
        d["internal_input"]["executed"] = True
        self.assertEqual(build(d), UNAVAILABLE)

    def test_non_consumed_result(self):
        good = self.consumed()
        for key, value in (("consumed", False), ("consumed", None), ("status", "internal_input_ready")):
            d = copy.deepcopy(good)
            d[key] = value
            self.assertEqual(build(d), UNAVAILABLE, (key, value))
        d = copy.deepcopy(good)
        d["internal_input"]["consumed"] = True
        self.assertEqual(build(d), UNAVAILABLE)

    def test_mutation_safety(self):
        good = self.consumed()
        before = copy.deepcopy(good)
        cand = build(good)
        cand["decision"]["decision"] = "changed"
        cand["plan"]["status"] = "changed"
        cand["capability_boundary"]["reason"] = "changed"
        cand["actionable"] = True
        self.assertEqual(good, before)
        self.assertEqual(build(good)["plan"], before["internal_input"]["plan"])
        bad = {"status": "x"}
        snapshot = copy.deepcopy(bad)
        build(bad)
        self.assertEqual(bad, snapshot)
        handoff = self.core.last_runtime_result["reasoning"]["reasoning_handoff"]
        self.assertIs(handoff["consumed_by_runtime"], False)
        self.assertIs(handoff["executed"], False)

    def test_storage_and_accessor(self):
        self.assertIsNone(self.core._last_reasoning_decision_candidate)
        self.assertIsNone(self.core.get_last_reasoning_decision_candidate())
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            stored = self.core._last_reasoning_decision_candidate
            self.assertEqual(stored, section["reasoning_decision_candidate"])
            self.assertIsNot(stored, section["reasoning_decision_candidate"])
            a, b = (self.core.get_last_reasoning_decision_candidate() for _ in range(2))
            self.assertEqual(a, stored)
            self.assertIsNot(a, b)
            self.assertIsNot(a["plan"], b["plan"])
            a["plan"]["status"] = "changed"
            a["decision"]["decision"] = "changed"
            self.assertEqual(self.core.get_last_reasoning_decision_candidate(), stored)
            self.assertEqual(self.core._last_reasoning_decision_candidate, section["reasoning_decision_candidate"])

    def test_stale_result_is_cleared(self):
        self.core.process_input(INTRO)
        self.assertIsNotNone(self.core.get_last_reasoning_decision_candidate())
        self.core.process_input("TEACH sun IS a star")
        self.assertIsNone(self.core._last_reasoning_decision_candidate)
        self.assertIsNone(self.core.get_last_reasoning_decision_candidate())
        self.core.process_input(INTRO)
        with mock.patch.object(Core, "process_input", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_reasoning_decision_candidate())
        self.core.process_input(INTRO)
        with mock.patch("runtime_integration.bridge.build_runtime_result", side_effect=RuntimeError("x")):
            self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_reasoning_decision_candidate())

    def test_actionable_stays_false(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            for cand in (section["reasoning_decision_candidate"],
                         self.core.get_last_reasoning_decision_candidate()):
                self.assertIs(cand["actionable"], False)
                self.assertIs(cand["executed"], False)
            self.assertIs(section["executed"], False)
            self.assertIs(self.core.get_last_reasoning_consumption_result()["executed"], False)
        self.assertIs(build(ri.consume_internal_reasoning_input(None))["actionable"], False)


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)
        self.assertFalse(hasattr(plain, "get_last_reasoning_decision_candidate"))


if __name__ == "__main__":
    unittest.main()
