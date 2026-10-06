"""
Tests for Prompt 921 - Controlled Reasoning Readiness.

`reasoning["reasoning_ready"]` is a deterministic, read-only observation derived
from the existing reasoning handoff. It triggers nothing.

Run directly:
    python -m unittest tests.test_reasoning_ready_prompt921 -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_integration import bridge as ri
from tests.test_reasoning_handoff_prompt918 import HandoffCase, INTRO, QUESTION


class TestReadyFlag(HandoffCase):
    def test_valid_handoff_is_ready(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            self.assertIs(section["reasoning_ready"], True, text)
            self.assertIs(ri.reasoning_handoff_ready(section["reasoning_handoff"]), True)
            self.assertIs(ri.reasoning_handoff_ready(self.core.get_last_reasoning_handoff()), True)

    def test_flag_is_deterministic(self):
        self.core.process_input(INTRO)
        h = self.core.get_last_reasoning_handoff()
        self.assertEqual([ri.reasoning_handoff_ready(h) for _ in range(3)], [True] * 3)

    def test_unavailable_handoff_is_not_ready(self):
        self.assertIs(ri.reasoning_handoff_ready(ri.unavailable_reasoning_handoff()), False)
        self.core.process_input("TEACH sun IS a star")
        self.assertIs(ri.reasoning_handoff_ready(self.core.get_last_reasoning_handoff()), False)
        self.assertNotIn("reasoning_ready", self.core.last_runtime_result["reasoning"])

    def test_malformed_handoffs_are_not_ready(self):
        self.core.process_input(INTRO)
        good = self.core.get_last_reasoning_handoff()
        for bad in (None, "x", 1, [], {}, {"available": True}):
            self.assertIs(ri.reasoning_handoff_ready(bad), False, bad)
        mutations = [
            lambda h: h.pop("request"), lambda h: h.pop("decision"), lambda h: h.pop("plan"),
            lambda h: h.pop("capability_boundary"), lambda h: h.update(version=2),
            lambda h: h.update(version=True), lambda h: h.update(available=False),
            lambda h: h.update(available=1), lambda h: h.update(descriptive_only=False),
            lambda h: h.update(request="x"), lambda h: h["request"].update(status=""),
            lambda h: h["request"].update(goal=None), lambda h: h["request"].pop("next_action"),
            lambda h: h["decision"].update(decision=None),
        ]
        for mutate in mutations:
            h = copy.deepcopy(good)
            mutate(h)
            self.assertIs(ri.reasoning_handoff_ready(h), False)

    def test_executed_or_consumed_is_not_ready(self):
        self.core.process_input(INTRO)
        good = self.core.get_last_reasoning_handoff()
        for key, value in (("executed", True), ("consumed_by_runtime", True),
                           ("executed", None), ("consumed_by_runtime", 0)):
            h = copy.deepcopy(good)
            h[key] = value
            self.assertIs(ri.reasoning_handoff_ready(h), False, (key, value))
        h = copy.deepcopy(good)
        h["request"]["next_action"]["executed"] = True
        self.assertIs(ri.reasoning_handoff_ready(h), False)

    def test_existing_handoff_fields_are_unchanged(self):
        self.core.process_input(INTRO)
        handoff = self.core.get_last_reasoning_handoff()
        self.assertEqual(list(handoff), ["version", "available", "descriptive_only", "request",
                                         "decision", "plan", "capability_boundary", "executed",
                                         "consumed_by_runtime"])
        self.assertIs(self.core.last_runtime_result["reasoning"]["executed"], False)


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)


if __name__ == "__main__":
    unittest.main()
