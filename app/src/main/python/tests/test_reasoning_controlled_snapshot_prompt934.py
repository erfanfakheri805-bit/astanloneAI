"""
Tests for Prompt 934 - Controlled Reasoning Final State Snapshot.

`build_controlled_reasoning_snapshot(...)` is a pure, read-only snapshot of the
controlled reasoning state. It reuses the Prompt 933 checkpoint, executes,
approves and authorizes nothing, and is never actionable. RuntimeCore stores
the latest snapshot per turn.

Run directly:
    python -m unittest tests.test_reasoning_controlled_snapshot_prompt934 -v
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

KEYS = ("reasoning_handoff", "reasoning_consumption_result", "reasoning_decision_candidate",
        "reasoning_decision_validation", "reasoning_decision_eligibility",
        "controlled_reasoning_checkpoint")
NAMES = ("handoff", "consumption", "decision_candidate", "validation", "eligibility", "checkpoint")
TOP = ("available", "status", "handoff", "consumption", "decision_candidate", "validation",
       "eligibility", "checkpoint", "actionable", "executed", "descriptive_only")
snapshot = ri.build_controlled_reasoning_snapshot


class ChainCase(HandoffCase):
    def chain(self, text=INTRO):
        self.core.process_input(text)
        section = self.core.last_runtime_result["reasoning"]
        return [copy.deepcopy(section[k]) for k in KEYS]


class TestHelper(ChainCase):
    def test_complete_chain_is_controlled_ready(self):
        for text in (INTRO, QUESTION):
            c = self.chain(text)
            result = snapshot(*c)
            self.assertEqual(list(result), list(TOP))
            self.assertIs(result["available"], True)
            self.assertEqual(result["status"], "controlled_ready")
            for name, state in zip(NAMES, c):
                self.assertEqual(result[name], state)
            self.assertEqual(result["checkpoint"]["status"], "controlled_ready")
            self.assertIs(result["actionable"], False)
            self.assertIs(result["executed"], False)
            self.assertIs(result["descriptive_only"], True)
            json.dumps(result)

    def assert_not_ready(self, result):
        self.assertEqual(list(result), list(TOP))
        self.assertIs(result["available"], False)
        self.assertEqual(result["status"], "not_ready")
        self.assertIs(result["actionable"], False)
        self.assertIs(result["executed"], False)
        self.assertIs(result["descriptive_only"], True)

    def test_incomplete_chain(self):
        base = self.chain()
        for index in range(6):
            for bad in (None, {}, "x", 3):
                c = copy.deepcopy(base)
                c[index] = bad
                result = snapshot(*c)
                self.assert_not_ready(result)
                if not isinstance(bad, dict) or bad == {}:
                    if not isinstance(bad, dict):
                        self.assertIsNone(result[NAMES[index]])
                    else:
                        self.assertEqual(result[NAMES[index]], {})

    def test_invalid_checkpoint(self):
        base = self.chain()
        for mutate in (lambda r: r.update(status="not_ready"), lambda r: r.update(available=False),
                       lambda r: r.update(handoff_ready=False), lambda r: r.update(candidate_valid=False),
                       lambda r: r.update(descriptive_only=False), lambda r: r.update(actionable=True),
                       lambda r: r.update(executed=True), lambda r: r.pop("status")):
            c = copy.deepcopy(base)
            mutate(c[5])
            self.assert_not_ready(snapshot(*c))
        # a forged "ready" checkpoint over states that are not ready
        c = copy.deepcopy(base)
        c[4]["status"] = "ineligible"
        c[4]["eligible"] = False
        self.assertEqual(c[5]["status"], "controlled_ready")
        self.assert_not_ready(snapshot(*c))

    def test_state_safety_flags_gate_readiness(self):
        base = self.chain()
        for index in (1, 2, 3, 4):
            for flag in ("actionable", "executed"):
                c = copy.deepcopy(base)
                c[index][flag] = True
                c[5] = ri.controlled_reasoning_checkpoint(*c[:5])
                self.assert_not_ready(snapshot(*c))

    def test_malformed_inputs_never_raise(self):
        for bad in (None, "x", 1, [], (), {}, object()):
            self.assert_not_ready(snapshot(bad, bad, bad, bad, bad, bad))

    def test_nested_copy_and_mutation_safety(self):
        c = self.chain()
        before = copy.deepcopy(c)
        result = snapshot(*c)
        self.assertEqual(c, before)
        for name, state in zip(NAMES, c):
            self.assertIsNot(result[name], state)
        result["handoff"]["request"]["goal"]["x"] = 1
        result["handoff"]["consumed_by_runtime"] = True
        result["consumption"]["internal_input"]["plan"]["junk"] = [1]
        result["decision_candidate"]["decision"]["n"] = 1
        result["validation"]["eligible"] = False
        result["eligibility"]["actionable"] = True
        result["checkpoint"]["executed"] = True
        result["available"] = False
        result["status"] = "changed"
        self.assertEqual(c, before)
        self.assertEqual(ri.reasoning_consumption_state(c[0]), "ready_unconsumed")

    def test_repeated_calls(self):
        c = self.chain()
        results = [snapshot(*c) for _ in range(5)]
        for r in results:
            self.assertEqual(r, results[0])
        self.assertIsNot(results[0], results[1])
        self.assertIsNot(results[0]["handoff"], results[1]["handoff"])
        results[0]["actionable"] = True
        self.assertEqual(snapshot(*c), results[1])
        self.assertIs(snapshot(*c)["actionable"], False)


class TestRuntimeStorage(ChainCase):
    def test_initially_none(self):
        self.assertIsNone(self.core._last_controlled_reasoning_snapshot)
        self.assertIsNone(self.core.get_last_controlled_reasoning_snapshot())

    def test_section_exposure_and_storage(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            snap = section["controlled_reasoning_snapshot"]
            self.assertEqual(snap["status"], "controlled_ready")
            self.assertEqual(snap["checkpoint"], section["controlled_reasoning_checkpoint"])
            self.assertEqual(snap["handoff"], section["reasoning_handoff"])
            keys = list(section)
            self.assertEqual(keys[keys.index("controlled_reasoning_checkpoint") + 1],
                             "controlled_reasoning_snapshot")
            stored = self.core._last_controlled_reasoning_snapshot
            self.assertEqual(stored, snap)
            self.assertIsNot(stored, snap)
            self.assertIsNot(stored["handoff"], section["reasoning_handoff"])
            self.assertEqual(self.core.get_last_controlled_reasoning_snapshot(), snap)

    def test_broken_chain_stores_not_ready(self):
        unavailable = ri.build_reasoning_decision_candidate(None)
        with mock.patch("runtime_integration.bridge.build_reasoning_decision_candidate",
                        return_value=unavailable):
            self.core.process_input(INTRO)
        stored = self.core.get_last_controlled_reasoning_snapshot()
        self.assertEqual(stored["status"], "not_ready")
        self.assertIs(stored["available"], False)
        self.assertIs(stored["actionable"], False)
        self.assertIs(stored["executed"], False)
        self.assertEqual(self.core.last_runtime_result["reasoning"]["controlled_reasoning_snapshot"]["status"],
                         "not_ready")

    def test_no_reasoning_turn_is_none(self):
        self.core.process_input("TEACH sun IS a star")
        self.assertNotIn("controlled_reasoning_snapshot", self.core.last_runtime_result["reasoning"])
        self.assertIsNone(self.core.get_last_controlled_reasoning_snapshot())

    def test_per_turn_clearing(self):
        self.core.process_input(INTRO)
        self.assertEqual(self.core.get_last_controlled_reasoning_snapshot()["status"], "controlled_ready")
        self.core.process_input("   ")
        self.assertIsNone(self.core._last_controlled_reasoning_snapshot)
        self.assertIsNone(self.core.get_last_controlled_reasoning_snapshot())
        self.core.process_input(INTRO)
        with mock.patch.object(Core, "process_input", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_controlled_reasoning_snapshot())
        self.core.process_input(INTRO)
        with mock.patch("runtime_integration.bridge.build_runtime_result", side_effect=RuntimeError("x")):
            self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_controlled_reasoning_snapshot())

    def test_accessor_deep_copy_safety(self):
        self.core.process_input(INTRO)
        live = copy.deepcopy(self.core.last_runtime_result["reasoning"])
        a = self.core.get_last_controlled_reasoning_snapshot()
        b = self.core.get_last_controlled_reasoning_snapshot()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a, self.core._last_controlled_reasoning_snapshot)
        for name in NAMES:
            self.assertIsNot(a[name], b[name])
        a["handoff"]["request"]["goal"]["x"] = 1
        a["consumption"]["internal_input"]["decision"]["n"] = 1
        a["decision_candidate"]["plan"]["n"] = 1
        a["checkpoint"]["available"] = False
        a["eligibility"]["executed"] = True
        a["actionable"] = True
        a["executed"] = True
        a["extra"] = {"n": [1]}
        self.assertEqual(self.core.get_last_controlled_reasoning_snapshot(), b)
        self.assertEqual(self.core._last_controlled_reasoning_snapshot, b)
        self.assertEqual(self.core.last_runtime_result["reasoning"], live)
        self.assertEqual(self.core.get_last_reasoning_handoff(), live["reasoning_handoff"])

    def test_repeated_calls_and_turns(self):
        self.core.process_input(INTRO)
        for _ in range(4):
            self.assertEqual(self.core.get_last_controlled_reasoning_snapshot()["status"], "controlled_ready")
        self.core.process_input(QUESTION)
        self.assertEqual(self.core.get_last_controlled_reasoning_snapshot()["status"], "controlled_ready")

    def test_strictly_descriptive(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            s = self.core.get_last_controlled_reasoning_snapshot()
            self.assertIs(s["actionable"], False)
            self.assertIs(s["executed"], False)
            self.assertIs(s["descriptive_only"], True)
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
        self.assertFalse(hasattr(plain, "get_last_controlled_reasoning_snapshot"))


if __name__ == "__main__":
    unittest.main()
