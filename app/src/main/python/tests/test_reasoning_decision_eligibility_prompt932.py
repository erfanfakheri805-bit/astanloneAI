"""
Tests for Prompt 932 - Controlled Decision Eligibility Gate.

`reasoning_decision_eligibility(validation)` is a pure state gate over the
Prompt 930 validation result. It approves and executes nothing and is never
actionable. RuntimeCore stores the latest result per turn.

Run directly:
    python -m unittest tests.test_reasoning_decision_eligibility_prompt932 -v
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

ELIGIBLE = {"available": True, "status": "eligible", "eligible": True,
            "actionable": False, "executed": False, "descriptive_only": True}
INELIGIBLE = {"available": False, "status": "ineligible", "eligible": False,
              "actionable": False, "executed": False, "descriptive_only": True}
VALIDATED = {"available": True, "status": "validated", "eligible": True,
             "actionable": False, "executed": False, "descriptive_only": True}
gate = ri.reasoning_decision_eligibility


class TestGate(unittest.TestCase):
    def test_valid_validation_is_eligible(self):
        result = gate(copy.deepcopy(VALIDATED))
        self.assertEqual(result, ELIGIBLE)
        json.dumps(result)

    def test_invalid_validation_is_ineligible(self):
        invalid = {"available": False, "status": "invalid", "eligible": False,
                   "actionable": False, "executed": False, "descriptive_only": True}
        self.assertEqual(gate(invalid), INELIGIBLE)
        self.assertEqual(gate(ri.validate_reasoning_decision_candidate(None)), INELIGIBLE)

    def test_unavailable_and_malformed(self):
        for bad in (None, "x", 1, 1.5, [], (), {}, {"available": True}, object()):
            self.assertEqual(gate(bad), INELIGIBLE, bad)
        for key in VALIDATED:
            v = copy.deepcopy(VALIDATED)
            v.pop(key)
            self.assertEqual(gate(v), INELIGIBLE, key)
        for key, value in (("status", "eligible"), ("status", None), ("available", 1),
                           ("eligible", 1), ("eligible", False), ("descriptive_only", False)):
            v = copy.deepcopy(VALIDATED)
            v[key] = value
            self.assertEqual(gate(v), INELIGIBLE, (key, value))

    def test_unsafe_actionable_or_executed(self):
        for key in ("actionable", "executed"):
            for value in (True, 1, None, "False"):
                v = copy.deepcopy(VALIDATED)
                v[key] = value
                self.assertEqual(gate(v), INELIGIBLE, (key, value))

    def test_does_not_inspect_decision_plan_boundary(self):
        v = copy.deepcopy(VALIDATED)
        v.update(decision="junk", plan=None, capability_boundary=[])
        self.assertEqual(gate(v), ELIGIBLE)

    def test_mutation_safety_and_repeated_calls(self):
        v = copy.deepcopy(VALIDATED)
        before = copy.deepcopy(v)
        results = [gate(v) for _ in range(5)]
        self.assertEqual(v, before)
        for r in results:
            self.assertEqual(r, ELIGIBLE)
        self.assertIsNot(results[0], results[1])
        results[0]["actionable"] = True
        results[0]["status"] = "changed"
        self.assertEqual(gate(v), ELIGIBLE)
        bad = {"status": "x", "n": [1]}
        snapshot = copy.deepcopy(bad)
        gate(bad)
        self.assertEqual(bad, snapshot)
        self.assertEqual(gate(gate(v)), INELIGIBLE)


class TestRuntimeStorage(HandoffCase):
    def test_initially_none(self):
        self.assertIsNone(self.core._last_reasoning_decision_eligibility)
        self.assertIsNone(self.core.get_last_reasoning_decision_eligibility())

    def test_reasoning_section_exposure_and_storage(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            self.assertEqual(section["reasoning_decision_eligibility"], ELIGIBLE)
            keys = list(section)
            self.assertEqual(keys[keys.index("reasoning_decision_validation") + 1],
                             "reasoning_decision_eligibility")
            stored = self.core._last_reasoning_decision_eligibility
            self.assertEqual(stored, ELIGIBLE)
            self.assertIsNot(stored, section["reasoning_decision_eligibility"])
            self.assertEqual(self.core.get_last_reasoning_decision_eligibility(), ELIGIBLE)

    def test_invalid_validation_stores_ineligible(self):
        unavailable = ri.build_reasoning_decision_candidate(None)
        with mock.patch("runtime_integration.bridge.build_reasoning_decision_candidate",
                        return_value=unavailable):
            self.core.process_input(INTRO)
        self.assertEqual(self.core.last_runtime_result["reasoning"]["reasoning_decision_eligibility"], INELIGIBLE)
        self.assertEqual(self.core.get_last_reasoning_decision_eligibility(), INELIGIBLE)

    def test_no_reasoning_turn_is_none(self):
        self.core.process_input("TEACH sun IS a star")
        self.assertNotIn("reasoning_decision_eligibility", self.core.last_runtime_result["reasoning"])
        self.assertIsNone(self.core.get_last_reasoning_decision_eligibility())

    def test_per_turn_clearing(self):
        self.core.process_input(INTRO)
        self.assertEqual(self.core.get_last_reasoning_decision_eligibility(), ELIGIBLE)
        self.core.process_input("   ")
        self.assertIsNone(self.core._last_reasoning_decision_eligibility)
        self.assertIsNone(self.core.get_last_reasoning_decision_eligibility())
        self.core.process_input(INTRO)
        with mock.patch.object(Core, "process_input", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_reasoning_decision_eligibility())
        self.core.process_input(INTRO)
        with mock.patch("runtime_integration.bridge.build_runtime_result", side_effect=RuntimeError("x")):
            self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_reasoning_decision_eligibility())

    def test_independent_copy_and_nested_mutation_safety(self):
        self.core.process_input(INTRO)
        live = copy.deepcopy(self.core.last_runtime_result["reasoning"])
        a = self.core.get_last_reasoning_decision_eligibility()
        b = self.core.get_last_reasoning_decision_eligibility()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a, self.core._last_reasoning_decision_eligibility)
        a["eligible"] = False
        a["actionable"] = True
        a["executed"] = True
        a["extra"] = {"n": [1]}
        self.assertEqual(self.core.get_last_reasoning_decision_eligibility(), ELIGIBLE)
        self.assertEqual(self.core._last_reasoning_decision_eligibility, ELIGIBLE)
        self.assertEqual(self.core.last_runtime_result["reasoning"], live)
        self.core.last_runtime_result["reasoning"]["reasoning_decision_eligibility"]["eligible"] = False
        self.assertEqual(self.core.get_last_reasoning_decision_eligibility(), ELIGIBLE)

    def test_repeated_calls_and_turns(self):
        self.core.process_input(INTRO)
        for _ in range(4):
            self.assertEqual(self.core.get_last_reasoning_decision_eligibility(), ELIGIBLE)
        self.core.process_input(QUESTION)
        self.assertEqual(self.core.get_last_reasoning_decision_eligibility(), ELIGIBLE)

    def test_strictly_descriptive(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            e = self.core.get_last_reasoning_decision_eligibility()
            self.assertIs(e["actionable"], False)
            self.assertIs(e["executed"], False)
            section = self.core.last_runtime_result["reasoning"]
            self.assertIs(section["reasoning_decision_candidate"]["actionable"], False)
            self.assertIs(section["executed"], False)
            handoff = section["reasoning_handoff"]
            self.assertIs(handoff["consumed_by_runtime"], False)
            self.assertIs(handoff["executed"], False)
            self.assertIs(self.core.get_last_reasoning_handoff()["consumed_by_runtime"], False)


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)
        self.assertFalse(hasattr(plain, "get_last_reasoning_decision_eligibility"))


if __name__ == "__main__":
    unittest.main()
