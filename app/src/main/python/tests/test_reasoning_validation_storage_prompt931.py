"""
Tests for Prompt 931 - RuntimeCore stores the latest decision validation.

`RuntimeCore._last_reasoning_decision_validation` holds an independent copy of
the latest turn's validation result;
`get_last_reasoning_decision_validation()` returns another independent copy or
None. Nothing is executed and nothing becomes actionable.

Run directly:
    python -m unittest tests.test_reasoning_validation_storage_prompt931 -v
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_integration import bridge as ri
from tests.test_reasoning_handoff_prompt918 import HandoffCase, INTRO, QUESTION

VALID = {"available": True, "status": "validated", "eligible": True,
         "actionable": False, "executed": False, "descriptive_only": True}
INVALID = {"available": False, "status": "invalid", "eligible": False,
           "actionable": False, "executed": False, "descriptive_only": True}


class TestValidationStorage(HandoffCase):
    def test_initially_none(self):
        self.assertIsNone(self.core._last_reasoning_decision_validation)
        self.assertIsNone(self.core.get_last_reasoning_decision_validation())

    def test_valid_candidate_stores_validation(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            stored = self.core._last_reasoning_decision_validation
            self.assertEqual(stored, VALID)
            self.assertEqual(stored, section["reasoning_decision_validation"])
            self.assertIsNot(stored, section["reasoning_decision_validation"])
            self.assertEqual(self.core.get_last_reasoning_decision_validation(), VALID)

    def test_invalid_candidate_stores_invalid_result(self):
        unavailable = ri.build_reasoning_decision_candidate(None)
        with mock.patch("runtime_integration.bridge.build_reasoning_decision_candidate",
                        return_value=unavailable):
            self.core.process_input(INTRO)
        self.assertEqual(self.core.last_runtime_result["reasoning"]["reasoning_decision_validation"], INVALID)
        self.assertEqual(self.core.get_last_reasoning_decision_validation(), INVALID)

    def test_no_candidate_means_none(self):
        self.core.process_input("TEACH sun IS a star")
        self.assertIsNone(self.core.get_last_reasoning_decision_validation())
        self.core.process_input("   ")
        self.assertIsNone(self.core.get_last_reasoning_decision_validation())

    def test_per_turn_clearing(self):
        self.core.process_input(INTRO)
        self.assertEqual(self.core.get_last_reasoning_decision_validation(), VALID)
        self.core.process_input("TEACH sun IS a star")
        self.assertIsNone(self.core._last_reasoning_decision_validation)
        self.assertIsNone(self.core.get_last_reasoning_decision_validation())
        self.core.process_input(INTRO)
        with mock.patch.object(Core, "process_input", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_reasoning_decision_validation())
        self.core.process_input(INTRO)
        with mock.patch("runtime_integration.bridge.build_runtime_result", side_effect=RuntimeError("x")):
            self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_reasoning_decision_validation())

    def test_accessor_returns_independent_copy(self):
        self.core.process_input(INTRO)
        a = self.core.get_last_reasoning_decision_validation()
        b = self.core.get_last_reasoning_decision_validation()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a, self.core._last_reasoning_decision_validation)

    def test_mutation_safety(self):
        self.core.process_input(INTRO)
        live = copy.deepcopy(self.core.last_runtime_result["reasoning"])
        got = self.core.get_last_reasoning_decision_validation()
        got["eligible"] = False
        got["actionable"] = True
        got["executed"] = True
        got["status"] = "changed"
        got["extra"] = {"nested": [1]}
        self.assertEqual(self.core._last_reasoning_decision_validation, VALID)
        self.assertEqual(self.core.get_last_reasoning_decision_validation(), VALID)
        self.assertEqual(self.core.last_runtime_result["reasoning"], live)
        self.core.last_runtime_result["reasoning"]["reasoning_decision_validation"]["eligible"] = False
        self.assertEqual(self.core._last_reasoning_decision_validation, VALID)
        self.core._last_reasoning_decision_validation["status"] = "x"  # internal; accessor copies
        self.assertEqual(self.core.get_last_reasoning_decision_validation()["status"], "x")

    def test_never_actionable_or_executed(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            v = self.core.get_last_reasoning_decision_validation()
            self.assertIs(v["actionable"], False)
            self.assertIs(v["executed"], False)
            section = self.core.last_runtime_result["reasoning"]
            self.assertIs(section["reasoning_decision_candidate"]["actionable"], False)
            self.assertIs(section["executed"], False)
            handoff = section["reasoning_handoff"]
            self.assertIs(handoff["consumed_by_runtime"], False)
            self.assertIs(handoff["executed"], False)

    def test_repeated_calls(self):
        self.core.process_input(INTRO)
        results = [self.core.get_last_reasoning_decision_validation() for _ in range(5)]
        for r in results:
            self.assertEqual(r, VALID)
        for i in range(1, 5):
            self.assertIsNot(results[0], results[i])
        results[0]["status"] = "changed"
        self.assertEqual(self.core.get_last_reasoning_decision_validation(), VALID)
        self.core.process_input(INTRO)
        self.assertEqual(self.core.get_last_reasoning_decision_validation(), VALID)


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)
        self.assertFalse(hasattr(plain, "get_last_reasoning_decision_validation"))


if __name__ == "__main__":
    unittest.main()
