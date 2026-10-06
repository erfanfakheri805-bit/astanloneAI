"""
Tests for Prompt 935 - Runtime Controlled Reasoning Readiness Gate.

`controlled_reasoning_runtime_ready(snapshot)` is a pure structural gate over the
Prompt 934 snapshot. It executes, approves and authorizes nothing and is never
actionable. RuntimeCore stores the latest result per turn.

Run directly:
    python -m unittest tests.test_reasoning_runtime_ready_prompt935 -v
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

READY = {"available": True, "status": "runtime_ready", "ready": True,
         "actionable": False, "executed": False, "descriptive_only": True}
NOT_READY = {"available": False, "status": "runtime_not_ready", "ready": False,
             "actionable": False, "executed": False, "descriptive_only": True}
STATES = ("handoff", "consumption", "decision_candidate", "validation", "eligibility", "checkpoint")
gate = ri.controlled_reasoning_runtime_ready


def valid_snapshot():
    snap = {"available": True, "status": "controlled_ready",
            "actionable": False, "executed": False, "descriptive_only": True}
    for name in STATES:
        snap[name] = {"payload": {"n": [1]}}
    return snap


class TestGate(unittest.TestCase):
    def test_valid_snapshot_is_runtime_ready(self):
        result = gate(valid_snapshot())
        self.assertEqual(result, READY)
        self.assertEqual(list(result), list(READY))
        json.dumps(result)

    def test_unavailable_snapshot(self):
        for bad in (None, "x", 1, 1.5, [], (), {}, object()):
            self.assertEqual(gate(bad), NOT_READY, bad)
        s = valid_snapshot()
        s.update(available=False, status="not_ready")
        self.assertEqual(gate(s), NOT_READY)
        self.assertEqual(gate(ri.build_controlled_reasoning_snapshot(*([None] * 6))), NOT_READY)

    def test_incomplete_snapshot(self):
        for key in valid_snapshot():
            s = valid_snapshot()
            s.pop(key)
            self.assertEqual(gate(s), NOT_READY, key)

    def test_malformed_fields(self):
        for key in STATES:
            for bad in (None, [], (), "x", 1, True, object()):
                s = valid_snapshot()
                s[key] = bad
                self.assertEqual(gate(s), NOT_READY, (key, bad))
        for key, value in (("available", 1), ("available", None), ("status", "ready"),
                           ("status", None), ("status", "runtime_ready"),
                           ("actionable", 0), ("actionable", None), ("executed", 0),
                           ("descriptive_only", 1), ("descriptive_only", None)):
            s = valid_snapshot()
            s[key] = value
            self.assertEqual(gate(s), NOT_READY, (key, value))

    def test_actionable_true(self):
        for value in (True, 1, "False"):
            s = valid_snapshot()
            s["actionable"] = value
            self.assertEqual(gate(s), NOT_READY, value)

    def test_executed_true(self):
        for value in (True, 1, "False"):
            s = valid_snapshot()
            s["executed"] = value
            self.assertEqual(gate(s), NOT_READY, value)

    def test_descriptive_only_false(self):
        s = valid_snapshot()
        s["descriptive_only"] = False
        self.assertEqual(gate(s), NOT_READY)

    def test_does_not_inspect_nested_contents(self):
        s = valid_snapshot()
        s["handoff"] = {}
        s["consumption"] = {"executed": True, "actionable": True}
        s["decision_candidate"] = {"decision": None, "plan": 1}
        s["checkpoint"] = {"status": "not_ready"}
        s["extra"] = object()
        self.assertEqual(gate(s), READY)

    def test_independent_copy_mutation_and_repeated_calls(self):
        s = valid_snapshot()
        before = copy.deepcopy(s)
        results = [gate(s) for _ in range(5)]
        self.assertEqual(s, before)
        for r in results:
            self.assertEqual(r, READY)
        self.assertIsNot(results[0], results[1])
        results[0]["actionable"] = True
        results[0]["status"] = "changed"
        self.assertEqual(gate(s), READY)
        self.assertEqual(gate(gate(s)), NOT_READY)
        bad = {"status": "x", "n": [1]}
        snapshot = copy.deepcopy(bad)
        gate(bad)
        self.assertEqual(bad, snapshot)


class TestRuntimeStorage(HandoffCase):
    def test_initially_none(self):
        self.assertIsNone(self.core._last_controlled_reasoning_runtime_ready)
        self.assertIsNone(self.core.get_last_controlled_reasoning_runtime_ready())

    def test_reasoning_section_exposure_and_storage(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            self.assertEqual(section["controlled_reasoning_runtime_ready"], READY)
            keys = list(section)
            self.assertEqual(keys[keys.index("controlled_reasoning_snapshot") + 1],
                             "controlled_reasoning_runtime_ready")
            stored = self.core._last_controlled_reasoning_runtime_ready
            self.assertEqual(stored, READY)
            self.assertIsNot(stored, section["controlled_reasoning_runtime_ready"])
            self.assertEqual(self.core.get_last_controlled_reasoning_runtime_ready(), READY)

    def test_broken_chain_is_not_ready(self):
        unavailable = ri.build_reasoning_decision_candidate(None)
        with mock.patch("runtime_integration.bridge.build_reasoning_decision_candidate",
                        return_value=unavailable):
            self.core.process_input(INTRO)
        self.assertEqual(self.core.last_runtime_result["reasoning"]["controlled_reasoning_runtime_ready"],
                         NOT_READY)
        self.assertEqual(self.core.get_last_controlled_reasoning_runtime_ready(), NOT_READY)

    def test_no_reasoning_turn_is_none(self):
        self.core.process_input("TEACH sun IS a star")
        self.assertNotIn("controlled_reasoning_runtime_ready", self.core.last_runtime_result["reasoning"])
        self.assertIsNone(self.core.get_last_controlled_reasoning_runtime_ready())

    def test_per_turn_clearing(self):
        self.core.process_input(INTRO)
        self.assertEqual(self.core.get_last_controlled_reasoning_runtime_ready(), READY)
        self.core.process_input("   ")
        self.assertIsNone(self.core._last_controlled_reasoning_runtime_ready)
        self.assertIsNone(self.core.get_last_controlled_reasoning_runtime_ready())
        self.core.process_input(INTRO)
        with mock.patch.object(Core, "process_input", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_controlled_reasoning_runtime_ready())
        self.core.process_input(INTRO)
        with mock.patch("runtime_integration.bridge.build_runtime_result", side_effect=RuntimeError("x")):
            self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_controlled_reasoning_runtime_ready())

    def test_accessor_independent_copy(self):
        self.core.process_input(INTRO)
        live = copy.deepcopy(self.core.last_runtime_result["reasoning"])
        a = self.core.get_last_controlled_reasoning_runtime_ready()
        b = self.core.get_last_controlled_reasoning_runtime_ready()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a, self.core._last_controlled_reasoning_runtime_ready)
        a.update(ready=False, available=False, actionable=True, executed=True, extra=[1])
        self.assertEqual(self.core.get_last_controlled_reasoning_runtime_ready(), READY)
        self.assertEqual(self.core._last_controlled_reasoning_runtime_ready, READY)
        self.assertEqual(self.core.last_runtime_result["reasoning"], live)
        self.core.last_runtime_result["reasoning"]["controlled_reasoning_runtime_ready"]["ready"] = False
        self.assertEqual(self.core.get_last_controlled_reasoning_runtime_ready(), READY)

    def test_repeated_calls_and_turns(self):
        self.core.process_input(INTRO)
        for _ in range(4):
            self.assertEqual(self.core.get_last_controlled_reasoning_runtime_ready(), READY)
        self.core.process_input(QUESTION)
        self.assertEqual(self.core.get_last_controlled_reasoning_runtime_ready(), READY)

    def test_strictly_descriptive(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            r = self.core.get_last_controlled_reasoning_runtime_ready()
            self.assertIs(r["actionable"], False)
            self.assertIs(r["executed"], False)
            self.assertIs(r["descriptive_only"], True)
            section = self.core.last_runtime_result["reasoning"]
            self.assertIs(section["executed"], False)
            self.assertIs(section["reasoning_handoff"]["consumed_by_runtime"], False)
            self.assertIs(section["reasoning_handoff"]["executed"], False)
            self.assertIs(self.core.get_last_reasoning_handoff()["consumed_by_runtime"], False)


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)
        self.assertFalse(hasattr(plain, "get_last_controlled_reasoning_runtime_ready"))


if __name__ == "__main__":
    unittest.main()
