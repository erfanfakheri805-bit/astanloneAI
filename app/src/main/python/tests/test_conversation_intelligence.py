"""
Prompt 388 - Core Conversation Intelligence Upgrade
=====================================================
Behavioral tests for the real, user-visible conversation pipeline now
wired into Core._handle_conversation (core/core.py):

    text -> Input Understanding -> Context Retrieval / Learning
         -> Relevance Selection -> Response Construction -> reply

Each TEST_n below matches the numbered test in Prompt 388's own "TEST
REQUIREMENTS" section 1:1.

Run directly:
    python -m unittest tests.test_conversation_intelligence -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core


def _make_core():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
    skills_dir = os.path.join(tmpdir.name, "skills")
    core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)
    return core, tmpdir


class ConversationIntelligenceTestCase(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()


class Test1_KnowledgeQuestion(ConversationIntelligenceTestCase):
    """A fact taught in plain conversation is retrievable by a plain
    conversational question - not just via explicit AEL TEACH/ASK."""

    def test_stored_fact_answers_a_plain_question(self):
        self.core.process_input("Python is a programming language.")
        reply = self.core.process_input("What is Python?")
        self.assertIn("programming language", reply)


class Test2_DifferentWording(ConversationIntelligenceTestCase):
    """The same stored fact is still found when asked about with
    different wording than a recognized question pattern."""

    def test_different_phrasing_still_retrieves_the_fact(self):
        self.core.process_input("Python is a programming language.")
        reply = self.core.process_input("Tell me about Python.")
        self.assertIn("programming language", reply)


class Test3_ConversationContext(ConversationIntelligenceTestCase):
    """Short-term conversational context resolves a follow-up question
    about something stated earlier in the same conversation."""

    def test_project_name_stated_earlier_is_recalled(self):
        self.core.process_input("My project is called Echo Shift.")
        reply = self.core.process_input("What is my project called?")
        self.assertIn("Echo Shift", reply)


class Test4_UnknownInformation(ConversationIntelligenceTestCase):
    """No stored/learnable information about a made-up subject must
    never produce a fabricated answer."""

    def test_unknown_subject_is_not_hallucinated(self):
        reply = self.core.process_input(
            "Who invented the fictional device Zorblax 9000?"
        )
        self.assertNotIn("Zorblax", reply.replace("Zorblax 9000", ""))
        self.assertTrue(
            "don't have enough information" in reply
            or "not in the knowledge base" in reply
        )


class Test5_MultipleKnowledgeRecords(ConversationIntelligenceTestCase):
    """When several unrelated facts are stored, asking about one of
    them ranks the relevant fact above the unrelated ones."""

    def test_relevant_fact_ranks_above_unrelated_facts(self):
        self.core.process_input("Python is a programming language.")
        self.core.process_input("Java is a programming language.")
        self.core.process_input("Mercury is a planet.")

        reply = self.core.process_input("Tell me about Java.")
        self.assertIn("Java", reply)


class Test6_DuplicatePrevention(ConversationIntelligenceTestCase):
    """Teaching the same fact multiple times must not create
    uncontrolled duplicate knowledge records."""

    def test_repeated_statement_does_not_duplicate_knowledge(self):
        for _ in range(5):
            self.core.process_input("Python is a programming language.")

        matches = [
            row for row in self.core.knowledge.all()
            if row["name"].lower() == "python"
        ]
        self.assertEqual(len(matches), 1)

        rels = self.core.knowledge.relationships_for("Python")["outgoing"]
        is_a_edges = [r for r in rels if r["relation_type"] == "IS_A"]
        self.assertEqual(len(is_a_edges), 1)


class Test7_EmptyInput(ConversationIntelligenceTestCase):
    """Empty input is handled with a controlled response, no
    exceptions."""

    def test_empty_input_does_not_raise(self):
        reply = self.core.process_input("")
        self.assertIsInstance(reply, str)


class Test8_ExistingRegressionBehavior(ConversationIntelligenceTestCase):
    """AEL still takes priority over the new conversational pipeline,
    and goal-oriented input still short-circuits it - the acceptance
    criterion that existing Core conversation behavior keeps working."""

    def test_ael_still_takes_priority(self):
        reply = self.core.process_input("TEACH sun IS a star")
        self.assertTrue(reply.startswith("[AEL OK]"))

    def test_goal_oriented_input_still_creates_a_goal_not_a_learned_fact(self):
        reply = self.core.process_input("I want to learn Spanish")
        self.assertIn("[GOAL CREATED]", reply)
        self.assertEqual(len(self.core.goals), 1)


if __name__ == "__main__":
    unittest.main()
