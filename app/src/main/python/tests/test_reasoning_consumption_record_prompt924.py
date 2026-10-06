"""
Tests for Prompt 924 - Reasoning Consumption Record.

`build_reasoning_consumption_record(handoff)` builds a small internal record
from the read-only observation. It never marks the handoff consumed, never
executes anything and never changes replies.

Run directly:
    python -m unittest tests.test_reasoning_consumption_record_prompt924 -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_integration import bridge as ri
from tests.test_reasoning_handoff_prompt918 import HandoffCase, INTRO, QUESTION

ACCEPTED = {"available": True, "status": "accepted_for_internal_consumption",
            "consumed": False, "executed": False, "descriptive_only": True}
UNAVAILABLE = {"available": False, "status": "unavailable", "consumed": False,
               "executed": False, "descriptive_only": True}
build = ri.build_reasoning_consumption_record


class TestRecord(HandoffCase):
    def test_valid_ready_handoff(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            self.assertEqual(build(section["reasoning_handoff"]), ACCEPTED, text)
            self.assertEqual(section["reasoning_consumption_record"], ACCEPTED)
            self.assertEqual(build(self.core.get_last_reasoning_handoff()), ACCEPTED)
            self.assertEqual(set(section["reasoning_consumption_record"]), set(ACCEPTED))

    def test_unavailable_handoff(self):
        self.assertEqual(build(ri.unavailable_reasoning_handoff()), UNAVAILABLE)
        self.core.process_input("TEACH sun IS a star")
        self.assertEqual(build(self.core.get_last_reasoning_handoff()), UNAVAILABLE)
        self.assertNotIn("reasoning_consumption_record", self.core.last_runtime_result["reasoning"])

    def test_malformed_handoff(self):
        self.core.process_input(INTRO)
        good = self.core.get_last_reasoning_handoff()
        for bad in (None, "x", 1, [], {}, {"available": True}):
            self.assertEqual(build(bad), UNAVAILABLE, bad)
        for mutate in (lambda h: h.pop("request"), lambda h: h.update(version=2),
                       lambda h: h.update(descriptive_only=False),
                       lambda h: h["decision"].update(decision=None),
                       lambda h: h.pop("consumed_by_runtime")):
            h = copy.deepcopy(good)
            mutate(h)
            self.assertEqual(build(h), UNAVAILABLE)

    def test_executed_handoff(self):
        self.core.process_input(INTRO)
        h = self.core.get_last_reasoning_handoff()
        h["executed"] = True
        self.assertEqual(build(h), UNAVAILABLE)
        self.assertIs(h["executed"], True)

    def test_already_consumed_handoff(self):
        self.core.process_input(INTRO)
        for value in (True, None):
            h = self.core.get_last_reasoning_handoff()
            h["consumed_by_runtime"] = value
            self.assertEqual(build(h), UNAVAILABLE, value)
            self.assertIs(h["consumed_by_runtime"], value)

    def test_repeated_calls(self):
        self.core.process_input(INTRO)
        handoff = self.core.get_last_reasoning_handoff()
        results = [build(handoff) for _ in range(5)]
        for r in results:
            self.assertEqual(r, ACCEPTED)
        self.assertIsNot(results[0], results[1])
        results[0]["status"] = "changed"
        self.assertEqual(build(handoff), ACCEPTED)
        self.assertIs(handoff["consumed_by_runtime"], False)

    def test_mutation_safety(self):
        self.core.process_input(INTRO)
        stored = self.core.last_runtime_result["reasoning"]["reasoning_handoff"]
        before = copy.deepcopy(stored)
        handoff = self.core.get_last_reasoning_handoff()
        build(handoff)
        self.assertEqual(handoff, before)
        self.assertEqual(stored, before)
        self.assertIs(stored["consumed_by_runtime"], False)
        self.assertIs(stored["executed"], False)
        bad = {"version": "x"}
        snapshot = copy.deepcopy(bad)
        build(bad)
        self.assertEqual(bad, snapshot)

    def test_nothing_consumed_in_runtime_result(self):
        self.core.process_input(INTRO)
        section = self.core.last_runtime_result["reasoning"]
        self.assertIs(section["reasoning_handoff"]["consumed_by_runtime"], False)
        self.assertIs(section["reasoning_handoff"]["executed"], False)
        self.assertIs(section["executed"], False)
        self.assertEqual(section["reasoning_observation"]["status"], "observed_ready")
        self.assertEqual(section["reasoning_consumption_state"], "consumed")  # Prompt 927: effective state
        self.assertIs(section["reasoning_ready"], True)
        keys = list(section)
        self.assertEqual(keys[keys.index("reasoning_observation") + 1], "reasoning_consumption_record")


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)


if __name__ == "__main__":
    unittest.main()
