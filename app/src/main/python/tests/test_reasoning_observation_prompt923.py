"""
Tests for Prompt 923 - Reasoning Handoff Observation.

`consume_reasoning_handoff_observation(handoff)` is a read-only observation:
it never executes, never consumes and never modifies the handoff.

Run directly:
    python -m unittest tests.test_reasoning_observation_prompt923 -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_integration import bridge as ri
from tests.test_reasoning_handoff_prompt918 import HandoffCase, INTRO, QUESTION

OBSERVED = {"available": True, "status": "observed_ready", "consumed": False,
            "executed": False, "descriptive_only": True}
UNAVAILABLE = {"available": False, "status": "unavailable", "consumed": False,
               "executed": False, "descriptive_only": True}


class TestObservation(HandoffCase):
    def test_valid_ready_handoff(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            self.assertEqual(ri.consume_reasoning_handoff_observation(section["reasoning_handoff"]), OBSERVED)
            self.assertEqual(section["reasoning_observation"], OBSERVED)
            self.assertEqual(ri.consume_reasoning_handoff_observation(
                self.core.get_last_reasoning_handoff()), OBSERVED)

    def test_unavailable_handoff(self):
        self.assertEqual(ri.consume_reasoning_handoff_observation(
            ri.unavailable_reasoning_handoff()), UNAVAILABLE)
        self.core.process_input("TEACH sun IS a star")
        self.assertEqual(ri.consume_reasoning_handoff_observation(
            self.core.get_last_reasoning_handoff()), UNAVAILABLE)
        self.assertNotIn("reasoning_observation", self.core.last_runtime_result["reasoning"])

    def test_malformed_handoff(self):
        self.core.process_input(INTRO)
        good = self.core.get_last_reasoning_handoff()
        for bad in (None, "x", 1, [], {}, {"available": True}):
            self.assertEqual(ri.consume_reasoning_handoff_observation(bad), UNAVAILABLE, bad)
        for mutate in (lambda h: h.pop("request"), lambda h: h.update(version=2),
                       lambda h: h.update(descriptive_only=False),
                       lambda h: h["decision"].update(decision=None),
                       lambda h: h.pop("consumed_by_runtime")):
            h = copy.deepcopy(good)
            mutate(h)
            self.assertEqual(ri.consume_reasoning_handoff_observation(h), UNAVAILABLE)

    def test_executed_true(self):
        self.core.process_input(INTRO)
        h = self.core.get_last_reasoning_handoff()
        h["executed"] = True
        self.assertEqual(ri.consume_reasoning_handoff_observation(h), UNAVAILABLE)

    def test_consumed_by_runtime_true(self):
        self.core.process_input(INTRO)
        for value in (True, None):
            h = self.core.get_last_reasoning_handoff()
            h["consumed_by_runtime"] = value
            self.assertEqual(ri.consume_reasoning_handoff_observation(h), UNAVAILABLE, value)
            self.assertIs(h["consumed_by_runtime"], value)

    def test_repeated_observation_is_stable(self):
        self.core.process_input(INTRO)
        handoff = self.core.get_last_reasoning_handoff()
        results = [ri.consume_reasoning_handoff_observation(handoff) for _ in range(5)]
        for r in results:
            self.assertEqual(r, OBSERVED)
        self.assertIsNot(results[0], results[1])
        results[0]["status"] = "changed"
        self.assertEqual(ri.consume_reasoning_handoff_observation(handoff), OBSERVED)
        self.assertIs(handoff["consumed_by_runtime"], False)

    def test_mutation_safety(self):
        self.core.process_input(INTRO)
        before = copy.deepcopy(self.core.last_runtime_result["reasoning"]["reasoning_handoff"])
        handoff = self.core.get_last_reasoning_handoff()
        ri.consume_reasoning_handoff_observation(handoff)
        self.assertEqual(handoff, before)
        self.assertEqual(self.core.last_runtime_result["reasoning"]["reasoning_handoff"], before)
        self.assertIs(handoff["consumed_by_runtime"], False)
        self.assertIs(handoff["executed"], False)
        bad = {"version": "x"}
        snapshot = copy.deepcopy(bad)
        ri.consume_reasoning_handoff_observation(bad)
        self.assertEqual(bad, snapshot)

    def test_earlier_observations_unchanged(self):
        self.core.process_input(INTRO)
        section = self.core.last_runtime_result["reasoning"]
        self.assertIs(section["reasoning_ready"], True)
        self.assertEqual(section["reasoning_consumption_state"], "consumed")  # Prompt 927: effective state
        self.assertIs(section["executed"], False)
        # Later prompts append further read-only keys after these four.
        keys = list(section)
        start = keys.index("reasoning_handoff")
        self.assertEqual(keys[start:start + 4], ["reasoning_handoff", "reasoning_ready",
                                                 "reasoning_consumption_state", "reasoning_observation"])


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)


if __name__ == "__main__":
    unittest.main()
