"""
Tests for Prompt 926 - Controlled Internal Consumption.

`consume_internal_reasoning_input(internal_input)` turns a valid
`reasoning_internal_input` into a runtime-local consumption record
(`consumed=True`, `executed=False`). It executes nothing and never marks the
stored handoff consumed.

Run directly:
    python -m unittest tests.test_reasoning_consumption_result_prompt926 -v
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
consume = ri.consume_internal_reasoning_input


class TestConsumption(HandoffCase):
    def internal(self, text=INTRO):
        self.core.process_input(text)
        return self.core.last_runtime_result["reasoning"]["reasoning_internal_input"]

    def test_valid_internal_input(self):
        for text in (INTRO, QUESTION):
            inp = self.internal(text)
            self.assertEqual(inp["status"], "internal_input_ready")
            self.assertIs(inp["consumed"], False)

    def test_successful_controlled_consumption(self):
        for text in (INTRO, QUESTION):
            inp = self.internal(text)
            result = consume(inp)
            self.assertIs(result["available"], True)
            self.assertEqual(result["status"], "consumed")
            self.assertIs(result["consumed"], True)
            self.assertIs(result["executed"], False)
            self.assertIs(result["descriptive_only"], True)
            self.assertEqual(result["internal_input"], inp)
            self.assertIsNot(result["internal_input"], inp)
            self.assertEqual(set(result), {"available", "status", "consumed", "executed",
                                           "descriptive_only", "internal_input"})
            section = self.core.last_runtime_result["reasoning"]
            self.assertEqual(section["reasoning_consumption_result"], result)
            json.dumps(result)

    def test_unavailable_input(self):
        self.assertEqual(consume(ri.build_internal_reasoning_input(
            ri.unavailable_reasoning_handoff())), UNAVAILABLE)
        self.core.process_input("TEACH sun IS a star")
        self.assertNotIn("reasoning_consumption_result", self.core.last_runtime_result["reasoning"])
        self.assertEqual(consume(None), UNAVAILABLE)

    def test_malformed_input(self):
        good = self.internal()
        for bad in (None, "x", 1, [], {}, {"available": True}, self.core.get_last_reasoning_handoff()):
            self.assertEqual(consume(bad), UNAVAILABLE, bad)
        for mutate in (lambda d: d.pop("request"), lambda d: d.update(status="x"),
                       lambda d: d.update(available=False), lambda d: d.update(descriptive_only=False),
                       lambda d: d.update(plan=None), lambda d: d.update(decision=[]),
                       lambda d: d.pop("capability_boundary"), lambda d: d.pop("consumed")):
            d = copy.deepcopy(good)
            mutate(d)
            self.assertEqual(consume(d), UNAVAILABLE)

    def test_already_consumed_input(self):
        good = self.internal()
        for value in (True, None):
            d = copy.deepcopy(good)
            d["consumed"] = value
            self.assertEqual(consume(d), UNAVAILABLE, value)
        self.assertEqual(consume(consume(good)), UNAVAILABLE)

    def test_executed_input(self):
        d = copy.deepcopy(self.internal())
        d["executed"] = True
        self.assertEqual(consume(d), UNAVAILABLE)

    def test_repeated_calls(self):
        inp = self.internal()
        results = [consume(inp) for _ in range(4)]
        for r in results:
            self.assertEqual(r, results[0])
        self.assertIsNot(results[0], results[1])
        self.assertIsNot(results[0]["internal_input"], results[1]["internal_input"])
        results[0]["internal_input"]["request"]["status"] = "changed"
        self.assertEqual(consume(inp), results[1])

    def test_mutation_safety(self):
        inp = self.internal()
        handoff = self.core.last_runtime_result["reasoning"]["reasoning_handoff"]
        inp_before, handoff_before = copy.deepcopy(inp), copy.deepcopy(handoff)
        result = consume(inp)
        result["internal_input"]["plan"]["status"] = "changed"
        result["internal_input"]["request"]["goal"]["x"] = 1
        result["consumed"] = False
        self.assertEqual(inp, inp_before)
        self.assertEqual(handoff, handoff_before)
        self.assertIs(inp["consumed"], False)
        bad = {"status": "x"}
        snapshot = copy.deepcopy(bad)
        consume(bad)
        self.assertEqual(bad, snapshot)

    def test_executed_and_handoff_stay_false(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            self.assertIs(section["reasoning_consumption_result"]["executed"], False)
            self.assertIs(section["reasoning_consumption_result"]["internal_input"]["executed"], False)
            self.assertIs(section["reasoning_handoff"]["executed"], False)
            self.assertIs(section["reasoning_handoff"]["consumed_by_runtime"], False)
            self.assertIs(section["executed"], False)
            self.assertIs(self.core.get_last_reasoning_handoff()["consumed_by_runtime"], False)
            self.assertEqual(section["reasoning_consumption_state"], "consumed")  # Prompt 927: effective state
            keys = list(section)
            self.assertEqual(keys[keys.index("reasoning_internal_input") + 1],
                             "reasoning_consumption_result")


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)


if __name__ == "__main__":
    unittest.main()
