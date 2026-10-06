"""
Tests for Prompt 936 - Final Runtime Integration Checkpoint.

`final_runtime_integration_checkpoint(snapshot, runtime_ready)` is a pure,
read-only structural checkpoint over the Prompt 934 snapshot and Prompt 935
readiness result. It executes, approves and authorizes nothing and is never
actionable. RuntimeCore stores the latest result per turn.

Run directly:
    python -m unittest tests.test_final_runtime_integration_checkpoint_prompt936 -v
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

READY = {"available": True, "status": "integration_ready", "ready": True,
         "actionable": False, "executed": False, "descriptive_only": True}
NOT_READY = {"available": False, "status": "integration_not_ready", "ready": False,
             "actionable": False, "executed": False, "descriptive_only": True}
STATES = ("handoff", "consumption", "decision_candidate", "validation", "eligibility", "checkpoint")
checkpoint = ri.final_runtime_integration_checkpoint
RUNTIME_READY = {"available": True, "status": "runtime_ready", "ready": True,
                 "actionable": False, "executed": False, "descriptive_only": True}


def valid_pair():
    snap = {"available": True, "status": "controlled_ready",
            "actionable": False, "executed": False, "descriptive_only": True}
    for name in STATES:
        snap[name] = {"payload": {"n": [1]}}
    return snap, ri.controlled_reasoning_runtime_ready(snap)


class TestHelper(unittest.TestCase):
    def test_valid_complete_chain_is_integration_ready(self):
        snap, ready = valid_pair()
        self.assertEqual(ready, RUNTIME_READY)
        result = checkpoint(snap, ready)
        self.assertEqual(result, READY)
        self.assertEqual(list(result), list(READY))
        json.dumps(result)

    def test_unavailable_snapshot(self):
        for bad in (None, "x", 1, [], (), {}, object()):
            self.assertEqual(checkpoint(bad, RUNTIME_READY), NOT_READY, bad)
        snap, _ = valid_pair()
        snap.update(available=False, status="not_ready")
        self.assertEqual(checkpoint(snap, RUNTIME_READY), NOT_READY)
        unavailable = ri.build_controlled_reasoning_snapshot(*([None] * 6))
        self.assertEqual(checkpoint(unavailable, ri.controlled_reasoning_runtime_ready(unavailable)),
                         NOT_READY)

    def test_invalid_snapshot(self):
        for key in list(valid_pair()[0]):
            snap, ready = valid_pair()
            snap.pop(key)
            self.assertEqual(checkpoint(snap, ready), NOT_READY, key)
        for key in STATES:
            snap, ready = valid_pair()
            snap[key] = None
            self.assertEqual(checkpoint(snap, ready), NOT_READY, key)
        for key, value in (("available", 1), ("status", "ready"), ("status", None)):
            snap, ready = valid_pair()
            snap[key] = value
            self.assertEqual(checkpoint(snap, ready), NOT_READY, (key, value))

    def test_invalid_runtime_readiness(self):
        snap, ready = valid_pair()
        for bad in (None, "x", 1, [], (), {}, object()):
            self.assertEqual(checkpoint(snap, bad), NOT_READY, bad)
        for key, value in (("available", False), ("available", 1), ("status", "runtime_not_ready"),
                           ("status", None), ("ready", False), ("ready", 1)):
            r = copy.deepcopy(ready)
            r[key] = value
            self.assertEqual(checkpoint(snap, r), NOT_READY, (key, value))
        for key in ready:
            r = copy.deepcopy(ready)
            r.pop(key)
            self.assertEqual(checkpoint(snap, r), NOT_READY, key)
        self.assertEqual(checkpoint(snap, ri.controlled_reasoning_runtime_ready(None)), NOT_READY)

    def test_readiness_must_match_snapshot(self):
        snap, ready = valid_pair()
        snap["descriptive_only"] = False
        self.assertEqual(checkpoint(snap, ready), NOT_READY)
        snap, ready = valid_pair()
        snap["actionable"] = True
        self.assertEqual(checkpoint(snap, ready), NOT_READY)

    def test_actionable_true(self):
        snap, ready = valid_pair()
        for value in (True, 1, "False"):
            r = copy.deepcopy(ready)
            r["actionable"] = value
            self.assertEqual(checkpoint(snap, r), NOT_READY, value)
            s = copy.deepcopy(snap)
            s["actionable"] = value
            self.assertEqual(checkpoint(s, ready), NOT_READY, value)
            self.assertEqual(checkpoint(s, ri.controlled_reasoning_runtime_ready(s)), NOT_READY, value)

    def test_executed_true(self):
        snap, ready = valid_pair()
        for value in (True, 1, "False"):
            r = copy.deepcopy(ready)
            r["executed"] = value
            self.assertEqual(checkpoint(snap, r), NOT_READY, value)
            s = copy.deepcopy(snap)
            s["executed"] = value
            self.assertEqual(checkpoint(s, ready), NOT_READY, value)
            self.assertEqual(checkpoint(s, ri.controlled_reasoning_runtime_ready(s)), NOT_READY, value)

    def test_descriptive_only_false(self):
        snap, ready = valid_pair()
        r = copy.deepcopy(ready)
        r["descriptive_only"] = False
        self.assertEqual(checkpoint(snap, r), NOT_READY)
        s = copy.deepcopy(snap)
        s["descriptive_only"] = False
        self.assertEqual(checkpoint(s, ri.controlled_reasoning_runtime_ready(s)), NOT_READY)

    def test_does_not_inspect_nested_contents(self):
        snap, _ = valid_pair()
        snap["handoff"] = {}
        snap["consumption"] = {"executed": True}
        snap["decision_candidate"] = {"decision": None, "plan": 1}
        self.assertEqual(checkpoint(snap, ri.controlled_reasoning_runtime_ready(snap)), READY)

    def test_malformed_inputs_never_raise(self):
        for bad in (None, "x", 1, [], (), {}, object()):
            self.assertEqual(checkpoint(bad, bad), NOT_READY)

    def test_independent_copy_mutation_and_repeated_calls(self):
        snap, ready = valid_pair()
        before = (copy.deepcopy(snap), copy.deepcopy(ready))
        results = [checkpoint(snap, ready) for _ in range(5)]
        self.assertEqual((snap, ready), before)
        for r in results:
            self.assertEqual(r, READY)
        self.assertIsNot(results[0], results[1])
        results[0]["actionable"] = True
        results[0]["status"] = "changed"
        self.assertEqual(checkpoint(snap, ready), READY)
        self.assertEqual(checkpoint(READY, READY), NOT_READY)


class TestRuntimeStorage(HandoffCase):
    def test_initially_none(self):
        self.assertIsNone(self.core._last_final_runtime_integration_checkpoint)
        self.assertIsNone(self.core.get_last_final_runtime_integration_checkpoint())

    def test_reasoning_section_exposure_and_storage(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            self.assertEqual(section["final_runtime_integration_checkpoint"], READY)
            keys = list(section)
            self.assertEqual(keys[keys.index("controlled_reasoning_runtime_ready") + 1],
                             "final_runtime_integration_checkpoint")
            stored = self.core._last_final_runtime_integration_checkpoint
            self.assertEqual(stored, READY)
            self.assertIsNot(stored, section["final_runtime_integration_checkpoint"])
            self.assertEqual(self.core.get_last_final_runtime_integration_checkpoint(), READY)

    def test_broken_chain_is_not_ready(self):
        unavailable = ri.build_reasoning_decision_candidate(None)
        with mock.patch("runtime_integration.bridge.build_reasoning_decision_candidate",
                        return_value=unavailable):
            self.core.process_input(INTRO)
        self.assertEqual(self.core.last_runtime_result["reasoning"]["final_runtime_integration_checkpoint"],
                         NOT_READY)
        self.assertEqual(self.core.get_last_final_runtime_integration_checkpoint(), NOT_READY)

    def test_no_reasoning_turn_is_none(self):
        self.core.process_input("TEACH sun IS a star")
        self.assertNotIn("final_runtime_integration_checkpoint", self.core.last_runtime_result["reasoning"])
        self.assertIsNone(self.core.get_last_final_runtime_integration_checkpoint())

    def test_per_turn_clearing(self):
        self.core.process_input(INTRO)
        self.assertEqual(self.core.get_last_final_runtime_integration_checkpoint(), READY)
        self.core.process_input("   ")
        self.assertIsNone(self.core._last_final_runtime_integration_checkpoint)
        self.assertIsNone(self.core.get_last_final_runtime_integration_checkpoint())
        self.core.process_input(INTRO)
        with mock.patch.object(Core, "process_input", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_final_runtime_integration_checkpoint())
        self.core.process_input(INTRO)
        with mock.patch("runtime_integration.bridge.build_runtime_result", side_effect=RuntimeError("x")):
            self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_final_runtime_integration_checkpoint())

    def test_accessor_independent_copy(self):
        self.core.process_input(INTRO)
        live = copy.deepcopy(self.core.last_runtime_result["reasoning"])
        a = self.core.get_last_final_runtime_integration_checkpoint()
        b = self.core.get_last_final_runtime_integration_checkpoint()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a, self.core._last_final_runtime_integration_checkpoint)
        a.update(ready=False, available=False, actionable=True, executed=True, extra=[1])
        self.assertEqual(self.core.get_last_final_runtime_integration_checkpoint(), READY)
        self.assertEqual(self.core._last_final_runtime_integration_checkpoint, READY)
        self.assertEqual(self.core.last_runtime_result["reasoning"], live)
        self.core.last_runtime_result["reasoning"]["final_runtime_integration_checkpoint"]["ready"] = False
        self.assertEqual(self.core.get_last_final_runtime_integration_checkpoint(), READY)

    def test_repeated_calls_and_turns(self):
        self.core.process_input(INTRO)
        for _ in range(4):
            self.assertEqual(self.core.get_last_final_runtime_integration_checkpoint(), READY)
        self.core.process_input(QUESTION)
        self.assertEqual(self.core.get_last_final_runtime_integration_checkpoint(), READY)

    def test_strictly_descriptive(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            r = self.core.get_last_final_runtime_integration_checkpoint()
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
        self.assertFalse(hasattr(plain, "get_last_final_runtime_integration_checkpoint"))


if __name__ == "__main__":
    unittest.main()
