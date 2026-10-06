"""
Tests for Prompt 927 - Effective Consumption State.

`reasoning_effective_consumption_state(handoff, consumption_result=None)` is
the authoritative runtime state: "consumed" only for a valid successful
consumption result, else the original `reasoning_consumption_state(handoff)`.
The handoff is never mutated.

Run directly:
    python -m unittest tests.test_reasoning_effective_state_prompt927 -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_integration import bridge as ri
from tests.test_reasoning_handoff_prompt918 import HandoffCase, INTRO, QUESTION

effective = ri.reasoning_effective_consumption_state
ALLOWED = {"unavailable", "ready_unconsumed", "consumed"}


class TestEffectiveState(HandoffCase):
    def parts(self, text=INTRO):
        self.core.process_input(text)
        section = self.core.last_runtime_result["reasoning"]
        return section["reasoning_handoff"], section["reasoning_consumption_result"]

    def test_successful_consumption_is_consumed(self):
        for text in (INTRO, QUESTION):
            handoff, result = self.parts(text)
            self.assertEqual(effective(handoff, result), "consumed")
            section = self.core.last_runtime_result["reasoning"]
            self.assertEqual(section["reasoning_consumption_state"], "consumed")

    def test_valid_unconsumed_handoff_is_ready_unconsumed(self):
        handoff, _ = self.parts()
        self.assertEqual(effective(handoff), "ready_unconsumed")
        self.assertEqual(effective(handoff, None), "ready_unconsumed")
        self.assertEqual(effective(handoff, ri.consume_internal_reasoning_input(None)), "ready_unconsumed")

    def test_unavailable_and_malformed_are_unavailable(self):
        self.assertEqual(effective(ri.unavailable_reasoning_handoff()), "unavailable")
        self.core.process_input("TEACH sun IS a star")
        self.assertEqual(effective(self.core.get_last_reasoning_handoff()), "unavailable")
        _, result = self.parts()
        for bad in (None, "x", 1, [], {}, {"available": True}):
            self.assertEqual(effective(bad), "unavailable", bad)
            self.assertEqual(effective(bad, result), "unavailable", bad)

    def test_invalid_consumption_result_never_reports_consumed(self):
        handoff, result = self.parts()
        for bad in ("x", 1, [], {}, {"available": True, "status": "consumed"}):
            self.assertEqual(effective(handoff, bad), "ready_unconsumed", bad)
        for key, value in (("available", False), ("status", "unavailable"), ("consumed", False),
                           ("consumed", None), ("descriptive_only", False), ("available", 1)):
            r = copy.deepcopy(result)
            r[key] = value
            self.assertEqual(effective(handoff, r), "ready_unconsumed", (key, value))
        r = copy.deepcopy(result)
        r.pop("internal_input")
        self.assertEqual(effective(handoff, r), "ready_unconsumed")

    def test_executed_never_produces_consumed(self):
        handoff, result = self.parts()
        r = copy.deepcopy(result)
        r["executed"] = True
        self.assertNotEqual(effective(handoff, r), "consumed")
        r = copy.deepcopy(result)
        r["internal_input"]["executed"] = True
        self.assertNotEqual(effective(handoff, r), "consumed")
        h = copy.deepcopy(handoff)
        h["executed"] = True
        self.assertEqual(effective(h, result), "unavailable")
        h = copy.deepcopy(handoff)
        h["consumed_by_runtime"] = True
        self.assertEqual(effective(h, result), "unavailable")

    def test_only_allowed_values(self):
        handoff, result = self.parts()
        for h in (handoff, None, {}, "x", ri.unavailable_reasoning_handoff()):
            for r in (result, None, {}, "x"):
                self.assertIn(effective(h, r), ALLOWED)

    def test_mutation_safety(self):
        handoff, result = self.parts()
        stored = self.core.last_runtime_result["reasoning"]["reasoning_handoff"]
        h_before, r_before = copy.deepcopy(handoff), copy.deepcopy(result)
        for _ in range(3):
            self.assertEqual(effective(handoff, result), "consumed")
        self.assertEqual(handoff, h_before)
        self.assertEqual(result, r_before)
        self.assertIs(stored["consumed_by_runtime"], False)
        self.assertIs(stored["executed"], False)
        self.assertIs(self.core.get_last_reasoning_handoff()["consumed_by_runtime"], False)

    def test_original_helper_is_backward_compatible(self):
        handoff, result = self.parts()
        self.assertEqual(ri.reasoning_consumption_state(handoff), "ready_unconsumed")
        self.assertEqual(ri.reasoning_consumption_state(ri.unavailable_reasoning_handoff()), "unavailable")
        self.assertEqual(ri.reasoning_consumption_state(None), "unavailable")
        for key, value in (("executed", True), ("consumed_by_runtime", True)):
            h = copy.deepcopy(handoff)
            h[key] = value
            self.assertEqual(ri.reasoning_consumption_state(h), "unavailable")
        section = self.core.last_runtime_result["reasoning"]
        keys = list(section)
        start = keys.index("reasoning_handoff")
        self.assertEqual(keys[start:start + 3],
                         ["reasoning_handoff", "reasoning_ready", "reasoning_consumption_state"])
        self.assertIs(section["executed"], False)
        self.assertIs(section["reasoning_consumption_result"]["executed"], False)


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)


if __name__ == "__main__":
    unittest.main()
