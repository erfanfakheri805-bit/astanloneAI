"""
Tests for Prompt 928 - RuntimeCore stores the latest consumption result.

`RuntimeCore._last_reasoning_consumption_result` holds an independent copy of
the latest turn's successful `reasoning_consumption_result`;
`get_last_reasoning_consumption_result()` returns another independent copy or
None. Nothing is executed and the handoff is never mutated.

Run directly:
    python -m unittest tests.test_reasoning_consumption_storage_prompt928 -v
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_integration.runtime_core import RuntimeCore
from tests.test_reasoning_handoff_prompt918 import HandoffCase, INTRO, QUESTION


class TestStorage(HandoffCase):
    def test_initially_none(self):
        self.assertIsNone(self.core._last_reasoning_consumption_result)
        self.assertIsNone(self.core.get_last_reasoning_consumption_result())

    def test_successful_consumption_is_stored(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            section = self.core.last_runtime_result["reasoning"]
            stored = self.core._last_reasoning_consumption_result
            self.assertEqual(stored, section["reasoning_consumption_result"])
            self.assertIsNot(stored, section["reasoning_consumption_result"])
            self.assertEqual(self.core.get_last_reasoning_consumption_result(), stored)
            self.assertEqual(stored["status"], "consumed")
            self.assertIs(stored["consumed"], True)

    def test_no_reasoning_turn_clears_stale_result(self):
        self.core.process_input(INTRO)
        self.assertIsNotNone(self.core.get_last_reasoning_consumption_result())
        for text in ("TEACH sun IS a star", "   "):
            self.core.process_input(INTRO)
            self.core.process_input(text)
            self.assertIsNone(self.core._last_reasoning_consumption_result, text)
            self.assertIsNone(self.core.get_last_reasoning_consumption_result(), text)

    def test_failed_turn_does_not_expose_previous_result(self):
        self.core.process_input(INTRO)
        self.assertIsNotNone(self.core.get_last_reasoning_consumption_result())
        with mock.patch.object(Core, "process_input", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.core.process_input(QUESTION)
        self.assertIsNone(self.core.last_runtime_result)
        self.assertIsNone(self.core._last_reasoning_consumption_result)
        self.assertIsNone(self.core.get_last_reasoning_consumption_result())

    def test_bridge_error_turn_stores_nothing(self):
        self.core.process_input(INTRO)
        with mock.patch("runtime_integration.bridge.build_runtime_result", side_effect=RuntimeError("x")):
            self.core.process_input(QUESTION)
        self.assertIsNone(self.core.get_last_reasoning_consumption_result())

    def test_accessor_returns_independent_copy(self):
        self.core.process_input(INTRO)
        a = self.core.get_last_reasoning_consumption_result()
        b = self.core.get_last_reasoning_consumption_result()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a, self.core._last_reasoning_consumption_result)
        self.assertIsNot(a["internal_input"], b["internal_input"])

    def test_nested_mutation_safety(self):
        self.core.process_input(INTRO)
        before = copy.deepcopy(self.core._last_reasoning_consumption_result)
        live = copy.deepcopy(self.core.last_runtime_result["reasoning"])
        got = self.core.get_last_reasoning_consumption_result()
        got["consumed"] = False
        got["internal_input"]["request"]["status"] = "changed"
        got["internal_input"]["plan"]["status"] = "changed"
        got["internal_input"]["decision"]["decision"] = "changed"
        got["internal_input"]["capability_boundary"]["reason"] = "changed"
        self.assertEqual(self.core._last_reasoning_consumption_result, before)
        self.assertEqual(self.core.get_last_reasoning_consumption_result(), before)
        self.assertEqual(self.core.last_runtime_result["reasoning"], live)
        stored = self.core._last_reasoning_consumption_result
        self.core.last_runtime_result["reasoning"]["reasoning_consumption_result"]["internal_input"]["plan"]["status"] = "x"
        self.assertEqual(stored, before)

    def test_executed_remains_false(self):
        for text in (INTRO, QUESTION):
            self.core.process_input(text)
            stored = self.core.get_last_reasoning_consumption_result()
            self.assertIs(stored["executed"], False)
            self.assertIs(stored["internal_input"]["executed"], False)
            self.assertIs(self.core.last_runtime_result["reasoning"]["executed"], False)

    def test_original_handoff_unchanged(self):
        self.core.process_input(INTRO)
        handoff = self.core.last_runtime_result["reasoning"]["reasoning_handoff"]
        self.assertIs(handoff["consumed_by_runtime"], False)
        self.assertIs(handoff["executed"], False)
        self.assertIs(self.core.get_last_reasoning_handoff()["consumed_by_runtime"], False)
        self.assertEqual(self.core.last_runtime_result["reasoning"]["reasoning_consumption_state"], "consumed")
        before = copy.deepcopy(handoff)
        self.core.get_last_reasoning_consumption_result()["internal_input"]["request"]["status"] = "x"
        self.assertEqual(handoff, before)


class TestRepliesUnchanged(HandoffCase):
    def test_replies_match_a_plain_core(self):
        plain = self.new_core(Core, "plain")
        for text in (INTRO, QUESTION, "TEACH sun IS a star", "hello there", "   "):
            self.assertEqual(self.core.process_input(text), plain.process_input(text), text)
        self.assertFalse(hasattr(plain, "get_last_reasoning_consumption_result"))


if __name__ == "__main__":
    unittest.main()
