"""
Tests for LearningSystem.get_learning_analysis() (learning/learning_system.py).

Covers: an empty learning state (no learning_record_store given, and
one given but empty), a learning state with records, and that
get_learning_analysis() never modifies the store or its records. This
is a read-only integration between the existing LearningSystem,
LearningRecordStore, and LearningAnalyzer - nothing here changes how
teach()/relate()/learn_from_understanding() work.

Run directly:
    python -m unittest tests.test_learning_system_analysis -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from learning.learning_record import LearningRecord
from learning.learning_record_store import LearningRecordStore


def _make_learning_system(learning_record_store=None):
    memory = MemorySystem(tempfile.mktemp(suffix=".db"))
    knowledge = KnowledgeSystem(memory)
    concepts = ConceptSystem(knowledge)
    return LearningSystem(concepts, knowledge, memory=memory, learning_record_store=learning_record_store)


class TestEmptyLearningState(unittest.TestCase):
    def test_no_store_given_returns_zero_analysis(self):
        learning = _make_learning_system()

        result = learning.get_learning_analysis()

        self.assertEqual(result, {
            "total_records": 0,
            "average_confidence": 0.0,
            "highest_confidence": 0.0,
        })

    def test_empty_store_returns_zero_analysis(self):
        store = LearningRecordStore()
        learning = _make_learning_system(learning_record_store=store)

        result = learning.get_learning_analysis()

        self.assertEqual(result, {
            "total_records": 0,
            "average_confidence": 0.0,
            "highest_confidence": 0.0,
        })


class TestLearningStateWithRecords(unittest.TestCase):
    def test_analysis_reflects_stored_records(self):
        store = LearningRecordStore()
        store.add(LearningRecord(source="a", pattern="p1", outcome="ok", confidence=0.4))
        store.add(LearningRecord(source="b", pattern="p2", outcome="ok", confidence=0.8))
        learning = _make_learning_system(learning_record_store=store)

        result = learning.get_learning_analysis()

        self.assertEqual(result["total_records"], 2)
        self.assertAlmostEqual(result["average_confidence"], 0.6)
        self.assertEqual(result["highest_confidence"], 0.8)


class TestReadOnly(unittest.TestCase):
    def test_get_learning_analysis_does_not_modify_records(self):
        store = LearningRecordStore()
        store.add(LearningRecord(
            source="a", pattern="p1", outcome="ok", confidence=0.5, record_id="rec-1",
        ))
        learning = _make_learning_system(learning_record_store=store)

        learning.get_learning_analysis()

        stored = store.get("rec-1")
        self.assertEqual(stored.confidence, 0.5)
        self.assertEqual(stored.outcome, "ok")
        self.assertEqual(len(store), 1)

    def test_get_learning_analysis_does_not_create_records(self):
        store = LearningRecordStore()
        learning = _make_learning_system(learning_record_store=store)

        learning.get_learning_analysis()

        self.assertEqual(len(store), 0)


if __name__ == "__main__":
    unittest.main()
