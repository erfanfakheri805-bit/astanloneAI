"""
Tests for Prompt 918 - Reasoning Handoff Activation.

The bridge now keeps the existing request/plan/decision/boundary result
together as one descriptive `reasoning_handoff` inside the runtime result's
`reasoning` section (and `RuntimeCore.get_last_reasoning_handoff()`). It is
read-only: nothing consumes it and nothing is executed.

Run directly:
    python -m unittest tests.test_reasoning_handoff_prompt918 -v
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_integration import bridge as ri
from runtime_integration.runtime_core import RuntimeCore
from reasoning.reasoning_foundation import build_reasoning_request
from reasoning.reasoning_decision import decide_reasoning

RESULT_KEYS = ["version", "status", "route", "input", "understood_input", "reasoning",
               "capability", "memory_context", "response", "local_model", "execution", "learning"]
EXECUTION_FALSE_FLAGS = ("allowed", "executed", "capability_executed", "code_modified",
                         "autonomy_chain_executable", "external_service_used")
INTRO = "من عرفان هستم"
QUESTION = "What is Python?"


class HandoffCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.core = self.new_core(RuntimeCore, "runtime")

    def new_core(self, cls, name):
        base = os.path.join(self._tmp.name, name)
        os.makedirs(base, exist_ok=True)
        return cls(memory_db_path=os.path.join(base, "m.sqlite3"),
                   skill_definitions_dir=os.path.join(base, "skills"))


class TestHandoffCreated(HandoffCase):
    def test_conversation_turn_produces_the_handoff(self):
        self.core.process_input(INTRO)
        handoff = self.core.last_runtime_result["reasoning"]["reasoning_handoff"]
        self.assertEqual(handoff["version"], ri.REASONING_HANDOFF_VERSION)
        self.assertIs(handoff["descriptive_only"], True)
        self.assertIs(handoff["consumed_by_runtime"], False)
        self.assertEqual(self.core.get_last_reasoning_handoff(), handoff)
        self.assertIsNot(self.core.get_last_reasoning_handoff(), handoff)
        json.dumps(handoff)

    def test_handoff_carries_the_existing_request_and_decision(self):
        self.core.process_input(INTRO)
        handoff = self.core.get_last_reasoning_handoff()
        request = build_reasoning_request(
            self.core.last_nlu_analysis.reasoning_input(self.core.nlu_context))
        decision = decide_reasoning(request)
        self.assertEqual(handoff["request"], request)
        self.assertEqual(handoff["decision"]["decision"], decision["decision"])
        self.assertEqual(handoff["decision"]["reason"], decision["reason"])
        self.assertEqual(handoff["decision"]["next_step"], decision.get("next_step"))
        section = self.core.last_runtime_result["reasoning"]
        self.assertEqual(handoff["plan"]["status"], section["plan_status"])
        self.assertEqual(handoff["capability_boundary"]["next_stage"],
                         section["capability_boundary"]["next_stage"])

    def test_unknown_goal_handoff_asks_for_information(self):
        self.core.process_input(QUESTION)
        handoff = self.core.get_last_reasoning_handoff()
        self.assertEqual(handoff["decision"]["decision"], "needs_information")
        self.assertEqual(handoff["request"]["next_action"]["action"], "request_information")


class TestNonExecuting(HandoffCase):
    def test_reasoning_stays_non_executing(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            result = self.core.last_runtime_result
            handoff = self.core.get_last_reasoning_handoff()
            self.assertIs(handoff["executed"], False)
            self.assertIs(handoff["request"]["next_action"]["executed"], False)
            self.assertIs(result["reasoning"]["executed"], False)
            self.assertIs(result["reasoning"]["next_action"]["executed"], False)
            for flag in EXECUTION_FALSE_FLAGS:
                self.assertIs(result["execution"][flag], False, flag)
            self.assertIs(result["capability"]["execution_allowed"], False)
            self.assertIs(result["capability"]["executed"], False)

    def test_handoff_is_a_copy_not_a_live_view_of_the_request(self):
        self.core.process_input(INTRO)
        handoff = self.core.get_last_reasoning_handoff()
        handoff["request"]["goal"]["intent"] = "changed"
        again = build_reasoning_request(
            self.core.last_nlu_analysis.reasoning_input(self.core.nlu_context))
        self.assertNotEqual(again["goal"]["intent"], "changed")


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "اسم من چیه؟"):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)

    def test_result_structure_stays_compatible(self):
        for text in (INTRO, "TEACH sun IS a star", "   "):
            self.core.process_input(text)
            self.assertEqual(list(self.core.last_runtime_result), RESULT_KEYS)


class TestAelGoalAndUnavailable(HandoffCase):
    def test_ael_turn_is_unchanged_and_has_no_handoff(self):
        plain = self.new_core(Core, "plain")
        text = "TEACH sun IS a star"
        self.assertEqual(self.core.process_input(text), plain.process_input(text))
        self.assertEqual(self.core.last_runtime_result["reasoning"],
                         {"available": False, "reason": "no_nlu_analysis_for_this_turn"})
        self.assertEqual(self.core.get_last_reasoning_handoff(),
                         ri.unavailable_reasoning_handoff("no_nlu_analysis_for_this_turn"))

    def test_goal_turn_is_unchanged(self):
        from planning.goal_detection import is_goal_oriented
        text = next(t for t in ("I want to build a calculator", "create a plan to learn Python",
                                "I need to write a report") if is_goal_oriented(t))
        plain = self.new_core(Core, "plain")
        reply = self.core.process_input(text)
        self.assertEqual(reply.split("\n")[0], plain.process_input(text).split("\n")[0])
        self.assertEqual(self.core.last_runtime_result["route"], "goal")
        self.assertEqual(list(self.core.last_runtime_result), RESULT_KEYS)
        self.assertIs(self.core.get_last_reasoning_handoff()["executed"], False)

    def test_no_handoff_before_the_first_message(self):
        handoff = self.core.get_last_reasoning_handoff()
        self.assertIs(handoff["available"], False)
        self.assertIs(handoff["executed"], False)

    def test_empty_input_is_safely_unavailable(self):
        self.core.process_input("   ")
        handoff = self.core.get_last_reasoning_handoff()
        self.assertIs(handoff["available"], False)
        self.assertEqual(handoff["reason"], "no_input_to_analyze")

    def test_failing_reasoning_is_safely_represented(self):
        with mock.patch.object(ri, "build_reasoning_request", side_effect=RuntimeError("x")):
            self.core.process_input(INTRO)
        self.assertEqual(self.core.last_runtime_result["reasoning"],
                         {"available": False, "reason": "section_error"})
        handoff = self.core.get_last_reasoning_handoff()
        self.assertEqual(handoff, ri.unavailable_reasoning_handoff("section_error"))

    def test_malformed_turn_gives_unavailable_handoff(self):
        result = ri.build_runtime_result(None)
        self.assertEqual(result["reasoning"], {"available": False, "reason": "bridge_error"})
        self.core.last_runtime_result = result
        self.assertIs(self.core.get_last_reasoning_handoff()["available"], False)
        self.core.last_runtime_result = "garbage"
        self.assertIs(self.core.get_last_reasoning_handoff()["available"], False)


if __name__ == "__main__":
    unittest.main()
