"""
Tests for Prompt 919 - Reasoning Handoff Lifecycle.

`RuntimeCore.get_last_reasoning_handoff()` always reflects the most recent
turn: its handoff when it has one, else the safe unavailable representation.
An older handoff is never exposed after a later turn without one. Nothing
consumes the handoff and nothing is executed.

Run directly:
    python -m unittest tests.test_reasoning_handoff_lifecycle_prompt919 -v
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime_integration import bridge as ri
from tests.test_reasoning_handoff_prompt918 import HandoffCase, INTRO, QUESTION

AEL = "TEACH sun IS a star"


class TestLifecycle(HandoffCase):
    def test_first_turn_has_a_handoff(self):
        self.assertIs(self.core.get_last_reasoning_handoff()["available"], False)
        self.core.process_input(INTRO)
        handoff = self.core.get_last_reasoning_handoff()
        self.assertIs(handoff["available"], True)
        self.assertEqual(handoff["request"]["goal"]["intent"], "introduce_name")
        self.assertIs(handoff["executed"], False)

    def test_second_turn_replaces_the_previous_handoff(self):
        self.core.process_input(INTRO)
        first = self.core.get_last_reasoning_handoff()
        self.core.process_input(QUESTION)
        second = self.core.get_last_reasoning_handoff()
        self.assertIsNot(second, first)
        self.assertEqual(first["decision"]["decision"], "ready")
        self.assertEqual(second["decision"]["decision"], "needs_information")
        self.assertEqual(second, self.core.last_runtime_result["reasoning"]["reasoning_handoff"])

    def test_turn_without_handoff_replaces_the_previous_one(self):
        for text, reason in ((AEL, "no_nlu_analysis_for_this_turn"), ("   ", "no_input_to_analyze")):
            self.core.process_input(INTRO)
            self.assertIs(self.core.get_last_reasoning_handoff()["available"], True)
            self.core.process_input(text)
            self.assertEqual(self.core.get_last_reasoning_handoff(),
                             ri.unavailable_reasoning_handoff(reason))

    def test_failing_reasoning_section_clears_the_previous_handoff(self):
        self.core.process_input(INTRO)
        with mock.patch.object(ri, "build_reasoning_request", side_effect=RuntimeError("x")):
            self.core.process_input(QUESTION)
        self.assertEqual(self.core.get_last_reasoning_handoff(),
                         ri.unavailable_reasoning_handoff("section_error"))

    def test_bridge_failure_clears_the_previous_handoff(self):
        self.core.process_input(INTRO)
        with mock.patch.object(ri, "build_runtime_result", side_effect=RuntimeError("off")):
            self.core.process_input(QUESTION)
        handoff = self.core.get_last_reasoning_handoff()
        self.assertIs(handoff["available"], False)
        self.assertIs(handoff["executed"], False)

    def test_turn_that_raises_does_not_leave_an_old_handoff(self):
        self.core.process_input(INTRO)
        with mock.patch.object(self.core.memory, "log_message", side_effect=RuntimeError("db")):
            with self.assertRaises(RuntimeError):
                self.core.process_input(QUESTION)
        self.assertIsNone(self.core.last_runtime_result)
        self.assertEqual(self.core.get_last_reasoning_handoff(),
                         ri.unavailable_reasoning_handoff())
        self.core.process_input(INTRO)
        self.assertIs(self.core.get_last_reasoning_handoff()["available"], True)


class TestSafeAndNonExecuting(HandoffCase):
    def test_unavailable_handoff_is_safe_and_json_serializable(self):
        for result in (None, "garbage", {}, {"reasoning": None}, {"reasoning": {"available": False}},
                       {"reasoning": {"reasoning_handoff": "bad"}}):
            self.core.last_runtime_result = result
            handoff = self.core.get_last_reasoning_handoff()
            self.assertIs(handoff["available"], False, result)
            self.assertIs(handoff["executed"], False)
            self.assertIs(handoff["consumed_by_runtime"], False)
            json.dumps(handoff)

    def test_executed_stays_false_over_many_turns(self):
        for text in (INTRO, AEL, QUESTION, "   ", "hello there", INTRO):
            self.core.process_input(text)
            handoff = self.core.get_last_reasoning_handoff()
            self.assertIs(handoff["executed"], False, text)
            self.assertIs(handoff["consumed_by_runtime"], False, text)
            if handoff.get("available") is True:
                self.assertIs(handoff["request"]["next_action"]["executed"], False)

    def test_replies_do_not_depend_on_the_handoff(self):
        plain = self.new_core(type(self.core).__mro__[1], "plain")
        for text in (INTRO, AEL, QUESTION, INTRO):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)


if __name__ == "__main__":
    unittest.main()
