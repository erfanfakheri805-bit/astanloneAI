"""
Tests for Prompt 930 - Reasoning Decision Validation.

`validate_reasoning_decision_candidate(candidate)` checks only the structural
and safety properties that make a candidate eligible for a later controlled
step. It is never actionable, executes nothing, never mutates its input and
never raises.

Run directly:
    python -m unittest tests.test_reasoning_decision_validation_prompt930 -v
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

VALID = {"available": True, "status": "validated", "eligible": True,
         "actionable": False, "executed": False, "descriptive_only": True}
INVALID = {"available": False, "status": "invalid", "eligible": False,
           "actionable": False, "executed": False, "descriptive_only": True}
validate = ri.validate_reasoning_decision_candidate


class TestValidation(HandoffCase):
    def candidate(self, text=INTRO):
        self.core.process_input(text)
        return self.core.last_runtime_result["reasoning"]["reasoning_decision_candidate"]

    def test_valid_candidate(self):
        for text in (INTRO, QUESTION):
            cand = self.candidate(text)
            self.assertEqual(validate(cand), VALID)
            self.assertEqual(validate(self.core.get_last_reasoning_decision_candidate()), VALID)
            section = self.core.last_runtime_result["reasoning"]
            self.assertEqual(section["reasoning_decision_validation"], VALID)
            json.dumps(section["reasoning_decision_validation"])

    def test_unavailable_candidate(self):
        unavailable = ri.build_reasoning_decision_candidate(None)
        self.assertEqual(validate(unavailable), INVALID)
        self.core.process_input("TEACH sun IS a star")
        self.assertNotIn("reasoning_decision_validation", self.core.last_runtime_result["reasoning"])
        self.assertEqual(validate(self.core.get_last_reasoning_decision_candidate()), INVALID)

    def test_malformed_candidate(self):
        good = self.candidate()
        for bad in (None, "x", 1, 1.5, [], (), {}, {"available": True}, object()):
            self.assertEqual(validate(bad), INVALID, bad)
        for mutate in (lambda c: c.update(status="x"), lambda c: c.update(available=False),
                       lambda c: c.update(available=1), lambda c: c.update(descriptive_only=False),
                       lambda c: c.pop("descriptive_only"), lambda c: c.pop("actionable"),
                       lambda c: c.pop("executed"), lambda c: c.update(status=None)):
            c = copy.deepcopy(good)
            mutate(c)
            self.assertEqual(validate(c), INVALID)

    def test_actionable_true(self):
        for value in (True, 1, None, "False"):
            c = copy.deepcopy(self.candidate())
            c["actionable"] = value
            self.assertEqual(validate(c), INVALID, value)

    def test_executed_true(self):
        for value in (True, 1, None):
            c = copy.deepcopy(self.candidate())
            c["executed"] = value
            self.assertEqual(validate(c), INVALID, value)

    def test_missing_decision_plan_boundary(self):
        good = self.candidate()
        for key in ("decision", "plan", "capability_boundary"):
            c = copy.deepcopy(good)
            c.pop(key)
            self.assertEqual(validate(c), INVALID, key)
            for bad in (None, [], "x", 1):
                c = copy.deepcopy(good)
                c[key] = bad
                self.assertEqual(validate(c), INVALID, (key, bad))

    def test_mutation_safety(self):
        good = self.candidate()
        before = copy.deepcopy(good)
        validate(good)
        self.assertEqual(good, before)
        result = validate(good)
        result["eligible"] = False
        result["actionable"] = True
        self.assertEqual(validate(good), VALID)
        bad = {"status": "x", "plan": {"a": 1}}
        snapshot = copy.deepcopy(bad)
        validate(bad)
        self.assertEqual(bad, snapshot)
        handoff = self.core.last_runtime_result["reasoning"]["reasoning_handoff"]
        self.assertIs(handoff["consumed_by_runtime"], False)
        self.assertIs(handoff["executed"], False)

    def test_repeated_validation(self):
        cand = self.candidate()
        results = [validate(cand) for _ in range(5)]
        for r in results:
            self.assertEqual(r, VALID)
        self.assertIsNot(results[0], results[1])
        self.assertEqual(validate(validate(cand)), INVALID)

    def test_never_actionable_or_executed(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            v = section["reasoning_decision_validation"]
            self.assertIs(v["actionable"], False)
            self.assertIs(v["executed"], False)
            self.assertIs(section["reasoning_decision_candidate"]["actionable"], False)
            self.assertIs(section["executed"], False)
            keys = list(section)
            self.assertEqual(keys[keys.index("reasoning_decision_candidate") + 1],
                             "reasoning_decision_validation")


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)


if __name__ == "__main__":
    unittest.main()
