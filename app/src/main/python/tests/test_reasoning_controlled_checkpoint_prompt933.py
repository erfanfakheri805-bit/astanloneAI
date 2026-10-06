"""
Tests for Prompt 933 - Controlled Reasoning Runtime Checkpoint.

`controlled_reasoning_checkpoint(...)` is a pure structural/runtime-safety
check over the whole controlled reasoning state chain. It executes, approves
and authorizes nothing and is never actionable. RuntimeCore stores the latest
result per turn.

Run directly:
    python -m unittest tests.test_reasoning_controlled_checkpoint_prompt933 -v
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

READY = {"available": True, "status": "controlled_ready", "handoff_ready": True,
         "consumption_valid": True, "candidate_valid": True, "validation_valid": True,
         "eligibility_valid": True, "actionable": False, "executed": False,
         "descriptive_only": True}
FLAGS = ("handoff_ready", "consumption_valid", "candidate_valid",
         "validation_valid", "eligibility_valid")
KEYS = ("reasoning_handoff", "reasoning_consumption_result", "reasoning_decision_candidate",
        "reasoning_decision_validation", "reasoning_decision_eligibility")
checkpoint = ri.controlled_reasoning_checkpoint


def not_ready(**overrides):
    result = {"available": False, "status": "not_ready", "handoff_ready": False,
              "consumption_valid": False, "candidate_valid": False,
              "validation_valid": False, "eligibility_valid": False,
              "actionable": False, "executed": False, "descriptive_only": True}
    result.update(overrides)
    return result


class ChainCase(HandoffCase):
    def chain(self, text=INTRO):
        self.core.process_input(text)
        section = self.core.last_runtime_result["reasoning"]
        return [copy.deepcopy(section[k]) for k in KEYS]


class TestHelper(ChainCase):
    def test_complete_valid_chain_is_controlled_ready(self):
        for text in (INTRO, QUESTION):
            result = checkpoint(*self.chain(text))
            self.assertEqual(result, READY)
            json.dumps(result)

    def test_missing_handoff(self):
        c = self.chain()
        for bad in (None, {}, "x", 5, []):
            c[0] = bad
            self.assertEqual(checkpoint(*c), not_ready(
                consumption_valid=True, candidate_valid=True,
                validation_valid=True, eligibility_valid=True), bad)

    def test_handoff_not_ready(self):
        c = self.chain()
        c[0]["consumed_by_runtime"] = True
        result = checkpoint(*c)
        self.assertIs(result["handoff_ready"], False)
        self.assertEqual(result["status"], "not_ready")

    def test_invalid_consumption(self):
        base = self.chain()
        for mutate in (lambda r: r.update(consumed=False), lambda r: r.update(executed=True),
                       lambda r: r.update(status="unavailable"), lambda r: r.update(available=False),
                       lambda r: r.update(descriptive_only=False),
                       lambda r: r["internal_input"].update(executed=True),
                       lambda r: r.pop("internal_input")):
            c = copy.deepcopy(base)
            mutate(c[1])
            result = checkpoint(*c)
            self.assertEqual(result, not_ready(handoff_ready=True, candidate_valid=True,
                                               validation_valid=True, eligibility_valid=True))
        c = copy.deepcopy(base)
        c[1] = None
        self.assertIs(checkpoint(*c)["consumption_valid"], False)

    def test_invalid_candidate(self):
        base = self.chain()
        for mutate in (lambda r: r.update(status="x"), lambda r: r.update(available=False),
                       lambda r: r.update(descriptive_only=False), lambda r: r.update(plan=None),
                       lambda r: r.update(decision=[]), lambda r: r.pop("capability_boundary")):
            c = copy.deepcopy(base)
            mutate(c[2])
            result = checkpoint(*c)
            self.assertEqual(result, not_ready(handoff_ready=True, consumption_valid=True,
                                               validation_valid=True, eligibility_valid=True))
        c = copy.deepcopy(base)
        c[2] = ri.build_reasoning_decision_candidate(None)
        self.assertIs(checkpoint(*c)["candidate_valid"], False)

    def test_invalid_validation(self):
        base = self.chain()
        for mutate in (lambda r: r.update(status="invalid"), lambda r: r.update(eligible=False),
                       lambda r: r.update(available=False), lambda r: r.update(descriptive_only=False),
                       lambda r: r.pop("status")):
            c = copy.deepcopy(base)
            mutate(c[3])
            result = checkpoint(*c)
            self.assertEqual(result, not_ready(handoff_ready=True, consumption_valid=True,
                                               candidate_valid=True, eligibility_valid=True))
        c = copy.deepcopy(base)
        c[3] = ri.validate_reasoning_decision_candidate(None)
        self.assertIs(checkpoint(*c)["validation_valid"], False)

    def test_invalid_eligibility(self):
        base = self.chain()
        for mutate in (lambda r: r.update(status="ineligible"), lambda r: r.update(eligible=False),
                       lambda r: r.update(available=False), lambda r: r.update(descriptive_only=False)):
            c = copy.deepcopy(base)
            mutate(c[4])
            result = checkpoint(*c)
            self.assertEqual(result, not_ready(handoff_ready=True, consumption_valid=True,
                                               candidate_valid=True, validation_valid=True))
        c = copy.deepcopy(base)
        c[4] = ri.reasoning_decision_eligibility(None)
        self.assertIs(checkpoint(*c)["eligibility_valid"], False)

    def test_actionable_true_anywhere_is_not_ready(self):
        base = self.chain()
        for index, flag in ((1, "actionable"), (2, "actionable"), (3, "actionable"), (4, "actionable")):
            for value in (True, 1, None, "False"):
                c = copy.deepcopy(base)
                c[index][flag] = value
                result = checkpoint(*c)
                self.assertEqual(result["status"], "not_ready", (index, value))
                self.assertIs(result["available"], False)
                self.assertIs(result["actionable"], False)

    def test_executed_true_anywhere_is_not_ready(self):
        base = self.chain()
        for index in range(5):
            for value in (True, 1, None, "False"):
                c = copy.deepcopy(base)
                c[index]["executed"] = value
                result = checkpoint(*c)
                self.assertEqual(result["status"], "not_ready", (index, value))
                self.assertIs(result["available"], False)
                self.assertIs(result["executed"], False)

    def test_malformed_inputs_never_raise(self):
        for bad in (None, "x", 1, 1.5, [], (), {}, object()):
            result = checkpoint(bad, bad, bad, bad, bad)
            self.assertEqual(result, not_ready(), bad)

    def test_does_not_inspect_semantics(self):
        c = self.chain()
        c[2]["decision"] = {"decision": "anything", "junk": [1]}
        c[2]["plan"] = {"whatever": 1}
        c[2]["capability_boundary"] = {}
        self.assertEqual(checkpoint(*c), READY)

    def test_result_is_always_non_actionable_and_descriptive(self):
        base = self.chain()
        for index in range(5):
            c = copy.deepcopy(base)
            c[index] = None
            r = checkpoint(*c)
            self.assertIs(r["actionable"], False)
            self.assertIs(r["executed"], False)
            self.assertIs(r["descriptive_only"], True)
        self.assertEqual(sorted(checkpoint(*base)), sorted(READY))

    def test_mutation_safety_and_repeated_calls(self):
        c = self.chain()
        before = copy.deepcopy(c)
        results = [checkpoint(*c) for _ in range(5)]
        self.assertEqual(c, before)
        for r in results:
            self.assertEqual(r, READY)
        self.assertIsNot(results[0], results[1])
        results[0]["actionable"] = True
        results[0]["status"] = "changed"
        self.assertEqual(checkpoint(*c), READY)
        self.assertIs(c[0]["consumed_by_runtime"], False)
        self.assertIs(c[0]["executed"], False)
        self.assertEqual(ri.reasoning_consumption_state(c[0]), "ready_unconsumed")


class TestRuntimeStorage(ChainCase):
    def test_initially_none(self):
        self.assertIsNone(self.core._last_controlled_reasoning_checkpoint)
        self.assertIsNone(self.core.get_last_controlled_reasoning_checkpoint())

    def test_section_exposure_and_storage(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            self.assertEqual(section["controlled_reasoning_checkpoint"], READY)
            keys = list(section)
            self.assertEqual(keys[keys.index("reasoning_decision_eligibility") + 1],
                             "controlled_reasoning_checkpoint")
            stored = self.core._last_controlled_reasoning_checkpoint
            self.assertEqual(stored, READY)
            self.assertIsNot(stored, section["controlled_reasoning_checkpoint"])
            self.assertEqual(self.core.get_last_controlled_reasoning_checkpoint(), READY)

    def test_broken_chain_stores_not_ready(self):
        unavailable = ri.build_reasoning_decision_candidate(None)
        with mock.patch("runtime_integration.bridge.build_reasoning_decision_candidate",
                        return_value=unavailable):
            self.core.process_input(INTRO)
        section = self.core.last_runtime_result["reasoning"]
        self.assertEqual(section["controlled_reasoning_checkpoint"]["status"], "not_ready")
        stored = self.core.get_last_controlled_reasoning_checkpoint()
        self.assertEqual(stored["status"], "not_ready")
        self.assertIs(stored["available"], False)
        self.assertIs(stored["actionable"], False)
        self.assertIs(stored["executed"], False)

    def test_no_reasoning_turn_is_none(self):
        self.core.process_input("TEACH sun IS a star")
        self.assertNotIn("controlled_reasoning_checkpoint", self.core.last_runtime_result["reasoning"])
        self.assertIsNone(self.core.get_last_controlled_reasoning_checkpoint())

    def test_per_turn_clearing(self):
        self.core.process_input(INTRO)
        self.assertEqual(self.core.get_last_controlled_reasoning_checkpoint(), READY)
        self.core.process_input("   ")
        self.assertIsNone(self.core._last_controlled_reasoning_checkpoint)
        self.assertIsNone(self.core.get_last_controlled_reasoning_checkpoint())
        self.core.process_input(INTRO)
        with mock.patch.object(Core, "process_input", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_controlled_reasoning_checkpoint())
        self.core.process_input(INTRO)
        with mock.patch("runtime_integration.bridge.build_runtime_result", side_effect=RuntimeError("x")):
            self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_controlled_reasoning_checkpoint())

    def test_accessor_copy_safety(self):
        self.core.process_input(INTRO)
        live = copy.deepcopy(self.core.last_runtime_result["reasoning"])
        a = self.core.get_last_controlled_reasoning_checkpoint()
        b = self.core.get_last_controlled_reasoning_checkpoint()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a, self.core._last_controlled_reasoning_checkpoint)
        a["available"] = False
        a["actionable"] = True
        a["executed"] = True
        a["extra"] = {"n": [1]}
        self.assertEqual(self.core.get_last_controlled_reasoning_checkpoint(), READY)
        self.assertEqual(self.core._last_controlled_reasoning_checkpoint, READY)
        self.assertEqual(self.core.last_runtime_result["reasoning"], live)
        self.core.last_runtime_result["reasoning"]["controlled_reasoning_checkpoint"]["available"] = False
        self.assertEqual(self.core.get_last_controlled_reasoning_checkpoint(), READY)

    def test_strictly_descriptive(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            cp = self.core.get_last_controlled_reasoning_checkpoint()
            self.assertIs(cp["actionable"], False)
            self.assertIs(cp["executed"], False)
            self.assertIs(cp["descriptive_only"], True)
            section = self.core.last_runtime_result["reasoning"]
            self.assertIs(section["executed"], False)
            handoff = section["reasoning_handoff"]
            self.assertIs(handoff["consumed_by_runtime"], False)
            self.assertIs(handoff["executed"], False)
            self.assertIs(self.core.get_last_reasoning_handoff()["consumed_by_runtime"], False)


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)
        self.assertFalse(hasattr(plain, "get_last_controlled_reasoning_checkpoint"))


if __name__ == "__main__":
    unittest.main()
