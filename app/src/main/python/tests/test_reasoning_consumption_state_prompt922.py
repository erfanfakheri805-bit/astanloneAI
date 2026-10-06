"""
Tests for Prompt 922 - Reasoning Consumption State.

`reasoning["reasoning_consumption_state"]` is "ready_unconsumed" for a ready,
unconsumed reasoning handoff and "unavailable" otherwise. It only observes:
nothing is consumed and nothing changes.

Run directly:
    python -m unittest tests.test_reasoning_consumption_state_prompt922 -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_integration import bridge as ri
from tests.test_reasoning_handoff_prompt918 import HandoffCase, INTRO, QUESTION

READY, UNAVAILABLE = "ready_unconsumed", "unavailable"


class TestConsumptionState(HandoffCase):
    def test_valid_ready_handoff_is_ready_unconsumed(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            self.assertEqual(section["reasoning_consumption_state"], "consumed", text)  # Prompt 927: effective state
            self.assertEqual(ri.reasoning_consumption_state(section["reasoning_handoff"]), READY)
            self.assertEqual(ri.reasoning_consumption_state(
                self.core.get_last_reasoning_handoff()), READY)

    def test_unavailable_handoff_is_unavailable(self):
        self.assertEqual(ri.reasoning_consumption_state(ri.unavailable_reasoning_handoff()), UNAVAILABLE)
        self.core.process_input("TEACH sun IS a star")
        self.assertEqual(ri.reasoning_consumption_state(self.core.get_last_reasoning_handoff()), UNAVAILABLE)
        self.assertNotIn("reasoning_consumption_state", self.core.last_runtime_result["reasoning"])

    def test_malformed_handoffs_are_unavailable(self):
        self.core.process_input(INTRO)
        good = self.core.get_last_reasoning_handoff()
        for bad in (None, "x", 1, [], {}, {"available": True}):
            self.assertEqual(ri.reasoning_consumption_state(bad), UNAVAILABLE, bad)
        for mutate in (lambda h: h.pop("request"), lambda h: h.update(version=2),
                       lambda h: h.update(available=False), lambda h: h.update(descriptive_only=False),
                       lambda h: h["decision"].update(decision=None), lambda h: h.pop("consumed_by_runtime")):
            h = copy.deepcopy(good)
            mutate(h)
            self.assertEqual(ri.reasoning_consumption_state(h), UNAVAILABLE)

    def test_executed_or_consumed_is_unavailable(self):
        self.core.process_input(INTRO)
        good = self.core.get_last_reasoning_handoff()
        for key, value in (("executed", True), ("consumed_by_runtime", True), ("consumed_by_runtime", None)):
            h = copy.deepcopy(good)
            h[key] = value
            self.assertEqual(ri.reasoning_consumption_state(h), UNAVAILABLE, (key, value))

    def test_nothing_is_consumed_by_observing(self):
        self.core.process_input(INTRO)
        before = copy.deepcopy(self.core.last_runtime_result["reasoning"]["reasoning_handoff"])
        handoff = self.core.get_last_reasoning_handoff()
        for _ in range(3):
            ri.reasoning_consumption_state(handoff)
        self.assertEqual(handoff, before)
        self.assertIs(handoff["consumed_by_runtime"], False)
        self.assertIs(handoff["executed"], False)
        self.assertEqual(self.core.last_runtime_result["reasoning"]["reasoning_consumption_state"], "consumed")  # Prompt 927

    def test_prompt921_behavior_is_unchanged(self):
        self.core.process_input(INTRO)
        section = self.core.last_runtime_result["reasoning"]
        self.assertIs(section["reasoning_ready"], True)
        self.assertIs(ri.reasoning_handoff_ready(section["reasoning_handoff"]), True)
        self.assertIs(section["executed"], False)
        keys = list(section)
        # Later prompts append further read-only keys after these three.
        start = keys.index("reasoning_handoff")
        self.assertEqual(keys[start:start + 3],
                         ["reasoning_handoff", "reasoning_ready", "reasoning_consumption_state"])


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)


if __name__ == "__main__":
    unittest.main()
