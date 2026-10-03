"""Prompt 630 - concise final acceptance for Section 2 (request
understanding). Integrated contract only; lifecycle details live in
Prompts 609-629."""
import os
import tempfile
import unittest

from core.core import Core
from language_intelligence.response_planning import STATUS_RESOLVED, STATUS_UNRESOLVED
from language_intelligence.learned_pattern_teaching import STATUS_CREATED
from language_intelligence.learned_pattern_meaning import STATUS_BOUND, STATUS_ALREADY_BOUND


def _core():
    tmp = tempfile.mkdtemp()
    return Core(memory_db_path=os.path.join(tmp, "c.db"),
                skill_definitions_dir=os.path.join(tmp, "s"))


def _teach(core, pattern, meaning):
    assert core.teach_sentence_pattern("en", pattern).status == STATUS_CREATED
    assert core.bind_pattern_meaning("en", pattern, meaning).status in (
        STATUS_BOUND, STATUS_ALREADY_BOUND)


class TestSection2FinalAcceptance(unittest.TestCase):
    def test_full_contract(self):
        core = _core()
        _teach(core, "good morning", "greeting")

        # success: original preserved, normalized, plan resolved, identity holds
        raw = "Good morning"
        core.process_input(raw)
        u1 = core.get_last_language_understanding()
        n1 = u1.normalized_input
        plan1 = core.get_last_response_plan()
        self.assertEqual(u1.original_input, raw)
        self.assertEqual(n1, "Good morning")
        self.assertIs(plan1, u1.response_plan)
        self.assertIs(core.get_last_response_normalized_input(), n1)
        self.assertEqual(plan1["status"], STATUS_RESOLVED)

        # unresolved/ambiguous request replaces, never merges
        core.process_input("zzqx wibble")
        u2 = core.get_last_language_understanding()
        plan2 = core.get_last_response_plan()
        self.assertIsNot(u2, u1)
        self.assertIsNot(plan2, plan1)
        self.assertEqual(plan2["status"], STATUS_UNRESOLVED)
        self.assertEqual(core.get_last_response_normalized_input(), "zzqx wibble")
        self.assertEqual(plan1["status"], STATUS_RESOLVED)  # earlier state untouched

        # recovery after unresolved
        core.process_input("good morning")
        u3 = core.get_last_language_understanding()
        self.assertEqual(core.get_last_response_plan()["status"], STATUS_RESOLVED)
        self.assertIs(core.get_last_response_plan(), u3.response_plan)

    def test_request_classification_and_intent(self):
        core = _core()
        for text, intent in (("Please explain recursion", "request_action"),
                             ("Explain recursion", "request_action")):
            core.process_input(text)
            u = core.get_last_language_understanding()
            self.assertEqual(u.intent, intent, text)
            self.assertEqual(u.original_input, text)

    def test_legacy_safe_construction_and_reads(self):
        core = _core()
        self.assertIsNone(core.get_last_response_plan())
        self.assertIsNone(core.get_last_response_normalized_input())
        self.assertIsNone(core.get_last_language_understanding())


if __name__ == "__main__":
    unittest.main()
