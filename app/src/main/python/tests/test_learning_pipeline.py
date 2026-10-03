"""
Tests for Stage 3: Understanding Engine -> Learning Engine ->
Knowledge/Concept Storage.

Run directly:
    python -m unittest tests.test_learning_pipeline -v
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
from learning.learning_result import LearningResult
from learning.learning_input import build_learning_inputs, INPUT_TYPE_FACT, INPUT_TYPE_RELATIONSHIP


class LearningPipelineTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "test_memory.sqlite3")
        skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()


class TestCaseA_NaturalLanguageFactLearning(LearningPipelineTestCase):
    def test_python_is_a_programming_language(self):
        understanding = self.core.understand("Python is a programming language.")
        self.assertEqual(understanding.relations[0].relation, "IS_A")

        result = self.core.learn_from_text("Python is a programming language.")
        self.assertIsInstance(result, LearningResult)
        self.assertTrue(result.success)
        self.assertFalse(result.errors)
        self.assertEqual(len(result.learned_items), 1)
        self.assertIn("Python", result.created_concepts)
        self.assertIn("programming language", result.created_concepts)
        self.assertEqual(len(result.created_relationships), 1)

        # Concept exists.
        concept = self.core.knowledge.get("Python")
        self.assertIsNotNone(concept)
        self.assertEqual(concept["kind"], "concept")

        # Relationship exists and is queryable (not only a success message).
        rels = self.core.knowledge.relationships_for("Python")["outgoing"]
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0]["relation_type"], "IS_A")
        self.assertEqual(rels[0]["to_name"], "programming language")

        # recall() (the same call AEL's ASK uses) surfaces it too.
        info = self.core.learning.recall("Python")
        self.assertEqual(len(info["relationships"]["outgoing"]), 1)


class TestCaseB_NaturalLanguageRelationshipLearning(LearningPipelineTestCase):
    def test_python_uses_indentation(self):
        result = self.core.learn_from_text("Python uses indentation.")
        self.assertTrue(result.success)
        self.assertEqual(len(result.created_relationships), 1)

        rels = self.core.knowledge.relationships_for("Python")["outgoing"]
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0]["relation_type"], "USES")
        self.assertEqual(rels[0]["to_name"], "indentation")


class TestCaseC_RepeatedLearning(LearningPipelineTestCase):
    def test_teaching_same_fact_multiple_times_does_not_duplicate(self):
        for _ in range(3):
            result = self.core.learn_from_text("Python is a programming language.")
            self.assertTrue(result.success)

        rels = self.core.knowledge.relationships_for("Python")["outgoing"]
        self.assertEqual(len(rels), 1, "repeated learning must not create duplicate edges")

        # First learn created the edge; the following two only refreshed it.
        first = self.core.learn_from_text("Python is a programming language.")
        self.assertEqual(len(first.created_relationships), 0)
        self.assertEqual(len(first.updated_items), 1)

    def test_case_insensitive_concept_identity(self):
        self.core.learn_from_text("Python is a programming language.")
        result = self.core.learn_from_text("python uses indentation.")

        # "python" (lowercase, from the second sentence) must resolve to
        # the same concept as "Python" (created by the first sentence),
        # not create a second concept.
        concept = self.core.knowledge.get("Python")
        self.assertIsNotNone(concept)
        self.assertIsNone(self.core.knowledge.get("python"))  # no duplicate exact-name row

        rels = self.core.knowledge.relationships_for("Python")["outgoing"]
        relation_types = {r["relation_type"] for r in rels}
        self.assertEqual(relation_types, {"IS_A", "USES"})
        self.assertNotIn("python", result.created_concepts)


class TestCaseD_AELCompatibility(LearningPipelineTestCase):
    def test_ael_teach_relate_ask_still_work(self):
        teach_reply = self.core.process_input('TEACH Python IS Programming Language')
        self.assertIn("[AEL OK]", teach_reply)

        relate_reply = self.core.process_input("RELATE Python TO Indentation AS USES")
        self.assertIn("[AEL OK]", relate_reply)

        ask_reply = self.core.process_input("ASK Python")
        self.assertIn("Programming Language", ask_reply)
        self.assertIn("USES", ask_reply)

    def test_ael_relate_keeps_case_sensitive_stub_creation(self):
        # Documented, deliberate difference from the natural-language
        # pipeline's case-insensitive resolution: a bare AEL RELATE
        # still creates stubs using the exact names given.
        self.core.process_input("RELATE Widget TO widget AS USES")
        self.assertIsNotNone(self.core.knowledge.get("Widget"))
        self.assertIsNotNone(self.core.knowledge.get("widget"))


class TestCaseE_RestartPersistence(LearningPipelineTestCase):
    def test_knowledge_survives_reinitializing_core(self):
        self.core.learn_from_text("Python is a programming language.")
        db_path = self.core.memory.db_path

        reopened = Core(memory_db_path=db_path, skill_definitions_dir=self._tmpdir.name + "/skills2")
        concept = reopened.knowledge.get("Python")
        self.assertIsNotNone(concept)
        rels = reopened.knowledge.relationships_for("Python")["outgoing"]
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0]["relation_type"], "IS_A")


class TestCaseF_LowConfidenceOrUnsupportedInput(LearningPipelineTestCase):
    def test_question_produces_no_permanent_knowledge(self):
        before = self.core.memory.counts()
        result = self.core.learn_from_text("What is Python?")
        after = self.core.memory.counts()
        self.assertTrue(result.success)
        self.assertEqual(result.learned_items, [])
        self.assertEqual(before["knowledge_count"], after["knowledge_count"])
        self.assertIsNone(self.core.knowledge.get("Python"))

    def test_low_confidence_relation_is_skipped_not_stored(self):
        inputs = build_learning_inputs(self.core.understand("Python is a programming language."))
        self.assertTrue(inputs)
        original_confidence = inputs[0].confidence
        inputs[0].confidence = 0.05  # force below MIN_CONFIDENCE_TO_LEARN

        from learning.learning_decision import LearningDecisionEngine
        decision = LearningDecisionEngine(self.core.knowledge, self.core.reasoning).decide(inputs[0])
        self.assertFalse(decision.should_persist)
        self.assertEqual(decision.reason, "confidence_too_low")
        self.assertGreater(original_confidence, 0.05)


class TestCaseG_MalformedInput(LearningPipelineTestCase):
    def test_empty_and_none_input_do_not_crash(self):
        result = self.core.learn_from_text("")
        self.assertTrue(result.success)
        self.assertEqual(result.learned_items, [])

        result_none = self.core.learn_from_text(None)
        self.assertTrue(result_none.success)
        self.assertEqual(result_none.learned_items, [])

    def test_gibberish_punctuation_does_not_crash(self):
        result = self.core.learn_from_text("   ??!! ...---   !!!   ")
        self.assertIsInstance(result, LearningResult)  # no exception raised


class TestLearningInputContract(unittest.TestCase):
    def test_is_a_classified_as_fact_others_as_relationship(self):
        from understanding.engine import UnderstandingEngine
        engine = UnderstandingEngine()

        fact_inputs = build_learning_inputs(engine.understand("Python is a programming language."))
        self.assertEqual(fact_inputs[0].input_type, INPUT_TYPE_FACT)

        rel_inputs = build_learning_inputs(engine.understand("Python uses indentation."))
        self.assertEqual(rel_inputs[0].input_type, INPUT_TYPE_RELATIONSHIP)


if __name__ == "__main__":
    unittest.main()
