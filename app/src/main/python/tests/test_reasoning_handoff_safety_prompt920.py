"""
Tests for Prompt 920 - Reasoning Handoff Safety.

`RuntimeCore.get_last_reasoning_handoff()` hands the caller an independent
copy: mutating it (top level or nested) never changes the stored runtime
result or what the next call returns. The shape and fields are unchanged and
the handoff stays observe-only.

Run directly:
    python -m unittest tests.test_reasoning_handoff_safety_prompt920 -v
"""

import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime_integration import bridge as ri
from tests.test_reasoning_handoff_prompt918 import HandoffCase, INTRO, QUESTION


class TestCallerMutation(HandoffCase):
    def stored(self):
        return self.core.last_runtime_result["reasoning"]["reasoning_handoff"]

    def test_top_level_mutation_does_not_reach_the_stored_handoff(self):
        self.core.process_input(INTRO)
        before = copy.deepcopy(self.stored())
        handoff = self.core.get_last_reasoning_handoff()
        handoff["executed"] = True
        handoff["consumed_by_runtime"] = True
        handoff["extra"] = "x"
        del handoff["request"]
        self.assertEqual(self.stored(), before)
        self.assertEqual(self.core.get_last_reasoning_handoff(), before)

    def test_nested_mutation_does_not_reach_the_stored_handoff(self):
        self.core.process_input(INTRO)
        before = copy.deepcopy(self.stored())
        handoff = self.core.get_last_reasoning_handoff()
        handoff["request"]["goal"]["intent"] = "changed"
        handoff["request"]["missing"].append("x")
        handoff["decision"]["decision"] = "changed"
        handoff["plan"]["status"] = "changed"
        handoff["capability_boundary"]["next_stage"] = "changed"
        if handoff["decision"]["next_step"] is not None:
            handoff["decision"]["next_step"]["kind"] = "changed"
        self.assertEqual(self.stored(), before)
        self.assertEqual(self.core.last_runtime_result["reasoning"]["decision"], before["decision"]["decision"])

    def test_each_call_returns_a_fresh_independent_copy(self):
        self.core.process_input(INTRO)
        first = self.core.get_last_reasoning_handoff()
        second = self.core.get_last_reasoning_handoff()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first["request"], second["request"])
        self.assertIsNot(first, self.stored())

    def test_contents_and_shape_are_unchanged(self):
        self.core.process_input(INTRO)
        handoff = self.core.get_last_reasoning_handoff()
        self.assertEqual(list(handoff), ["version", "available", "descriptive_only", "request",
                                         "decision", "plan", "capability_boundary", "executed",
                                         "consumed_by_runtime"])
        self.assertEqual(handoff, self.stored())
        json.dumps(handoff)

    def test_flags_stay_false(self):
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "   "):
            self.core.process_input(text)
            handoff = self.core.get_last_reasoning_handoff()
            self.assertIs(handoff["executed"], False, text)
            self.assertIs(handoff["consumed_by_runtime"], False, text)
            self.assertIs(self.core.last_runtime_result["reasoning"].get("executed", False), False)


class TestUnavailableStillSafe(HandoffCase):
    def test_unavailable_handoff_is_independent_and_safe(self):
        self.core.process_input("TEACH sun IS a star")
        handoff = self.core.get_last_reasoning_handoff()
        self.assertEqual(handoff, ri.unavailable_reasoning_handoff("no_nlu_analysis_for_this_turn"))
        handoff["executed"] = True
        handoff["available"] = True
        again = self.core.get_last_reasoning_handoff()
        self.assertIs(again["available"], False)
        self.assertIs(again["executed"], False)
        self.assertIs(again["consumed_by_runtime"], False)
        self.assertEqual(self.core.last_runtime_result["reasoning"],
                         {"available": False, "reason": "no_nlu_analysis_for_this_turn"})

    def test_before_first_message_and_malformed_results(self):
        for result in (None, "garbage", {"reasoning": {"reasoning_handoff": "bad"}}):
            self.core.last_runtime_result = result
            handoff = self.core.get_last_reasoning_handoff()
            self.assertIs(handoff["available"], False)
            self.assertIs(handoff["executed"], False)


if __name__ == "__main__":
    unittest.main()
