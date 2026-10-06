"""
Tests for Prompt 925 - Internal Reasoning Input.

`build_internal_reasoning_input(handoff)` carries independent copies of the
handoff's request/decision/plan/capability_boundary, only for an accepted
consumption record. It never executes anything and never marks the handoff
consumed.

Run directly:
    python -m unittest tests.test_reasoning_internal_input_prompt925 -v
"""

import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_integration import bridge as ri
from tests.test_reasoning_handoff_prompt918 import HandoffCase, INTRO, QUESTION

UNAVAILABLE = {"available": False, "status": "unavailable", "consumed": False,
               "executed": False, "descriptive_only": True}
OBJECTS = ("request", "decision", "plan", "capability_boundary")
build = ri.build_internal_reasoning_input


class TestInternalInput(HandoffCase):
    def test_valid_handoff(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            result = build(section["reasoning_handoff"])
            self.assertIs(result["available"], True)
            self.assertEqual(result["status"], "internal_input_ready")
            self.assertIs(result["consumed"], False)
            self.assertIs(result["executed"], False)
            self.assertIs(result["descriptive_only"], True)
            self.assertEqual(set(result), {"available", "status", "consumed", "executed",
                                           "descriptive_only", *OBJECTS})
            self.assertEqual(section["reasoning_internal_input"], result)
            json.dumps(result)

    def test_four_objects_are_carried_correctly(self):
        self.core.process_input(INTRO)
        handoff = self.core.get_last_reasoning_handoff()
        result = build(handoff)
        for key in OBJECTS:
            self.assertEqual(result[key], handoff[key], key)
            self.assertIsNot(result[key], handoff[key], key)

    def test_unavailable_and_malformed(self):
        self.assertEqual(build(ri.unavailable_reasoning_handoff()), UNAVAILABLE)
        self.core.process_input("TEACH sun IS a star")
        self.assertEqual(build(self.core.get_last_reasoning_handoff()), UNAVAILABLE)
        self.assertNotIn("reasoning_internal_input", self.core.last_runtime_result["reasoning"])
        self.core.process_input(INTRO)
        good = self.core.get_last_reasoning_handoff()
        for bad in (None, "x", 1, [], {}, {"available": True}):
            self.assertEqual(build(bad), UNAVAILABLE, bad)
        for mutate in (lambda h: h.pop("request"), lambda h: h.update(version=2),
                       lambda h: h.update(descriptive_only=False),
                       lambda h: h["decision"].update(decision=None),
                       lambda h: h.pop("plan"), lambda h: h.pop("consumed_by_runtime")):
            h = copy.deepcopy(good)
            mutate(h)
            self.assertEqual(build(h), UNAVAILABLE)

    def test_executed_input(self):
        self.core.process_input(INTRO)
        h = self.core.get_last_reasoning_handoff()
        h["executed"] = True
        self.assertEqual(build(h), UNAVAILABLE)
        self.assertIs(h["executed"], True)

    def test_consumed_input(self):
        self.core.process_input(INTRO)
        for value in (True, None):
            h = self.core.get_last_reasoning_handoff()
            h["consumed_by_runtime"] = value
            self.assertEqual(build(h), UNAVAILABLE, value)
            self.assertIs(h["consumed_by_runtime"], value)

    def test_mutation_safety(self):
        self.core.process_input(INTRO)
        stored = self.core.last_runtime_result["reasoning"]["reasoning_handoff"]
        before = copy.deepcopy(stored)
        result = build(stored)
        result["request"]["goal"]["x"] = 1
        result["request"]["status"] = "changed"
        result["decision"]["decision"] = "changed"
        result["plan"]["status"] = "changed"
        result["capability_boundary"]["reason"] = "changed"
        result["status"] = "changed"
        self.assertEqual(stored, before)
        section = self.core.last_runtime_result["reasoning"]
        self.assertNotIn("x", section["reasoning_internal_input"]["request"]["goal"])
        section["reasoning_internal_input"]["plan"]["status"] = "changed"
        self.assertEqual(stored, before)
        bad = {"version": "x"}
        snapshot = copy.deepcopy(bad)
        build(bad)
        self.assertEqual(bad, snapshot)

    def test_repeated_calls(self):
        self.core.process_input(INTRO)
        handoff = self.core.get_last_reasoning_handoff()
        results = [build(handoff) for _ in range(4)]
        for r in results:
            self.assertEqual(r, results[0])
        self.assertIsNot(results[0], results[1])
        self.assertIsNot(results[0]["request"], results[1]["request"])
        results[0]["request"]["status"] = "changed"
        self.assertEqual(build(handoff), results[1])

    def test_consumed_by_runtime_remains_false(self):
        self.core.process_input(INTRO)
        section = self.core.last_runtime_result["reasoning"]
        self.assertIs(section["reasoning_handoff"]["consumed_by_runtime"], False)
        self.assertIs(section["reasoning_handoff"]["executed"], False)
        self.assertIs(section["executed"], False)
        self.assertIs(self.core.get_last_reasoning_handoff()["consumed_by_runtime"], False)
        self.assertEqual(section["reasoning_consumption_state"], "consumed")  # Prompt 927: effective state
        self.assertEqual(section["reasoning_consumption_record"]["status"],
                         "accepted_for_internal_consumption")
        keys = list(section)
        self.assertEqual(keys[keys.index("reasoning_consumption_record") + 1],
                         "reasoning_internal_input")



class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)


if __name__ == "__main__":
    unittest.main()
