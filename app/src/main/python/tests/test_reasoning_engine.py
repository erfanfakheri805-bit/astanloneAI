"""
Tests for the Stage 5 Reasoning Engine.

Run directly:
    python -m unittest tests.test_reasoning_engine -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)

Each TEST_* method below corresponds 1:1 to an item in the stage spec's
own "19. TESTS" section (TEST A through TEST J).
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from reasoning.reasoning_engine import ReasoningEngine
from reasoning.reasoning_result import (
    STATUS_ANSWERED, STATUS_UNKNOWN, STATUS_AMBIGUOUS, STATUS_CONTRADICTION, STATUS_LIMIT_REACHED,
)
from reasoning.rules import Rule, RuleEngine, validate_rule
from context.conversation_context import ConversationContext
from understanding.engine import UnderstandingEngine
from core.core import Core
from ael.interpreter import AELInterpreter
from learning.learning_system import LearningSystem
from concepts.concept_system import ConceptSystem


def _make_engine():
    """A fresh, isolated (Reasoning Engine, Knowledge System) pair
    backed by a temporary sqlite file - never the real data/ database."""
    db_path = tempfile.mktemp(suffix=".db")
    memory = MemorySystem(db_path)
    knowledge = KnowledgeSystem(memory)
    reasoning = ReasoningEngine(knowledge)
    return reasoning, knowledge, memory


class TestDirectLookup(unittest.TestCase):
    """TEST A - direct lookup."""

    def setUp(self):
        self.reasoning, self.knowledge, _ = _make_engine()

    def test_what_is_answers_from_description(self):
        self.knowledge.learn("Python", "a general-purpose programming language")
        result = self.reasoning.reason("What is Python?")
        self.assertEqual(result.status, STATUS_ANSWERED)
        self.assertIn("programming language", result.answer)
        self.assertGreater(result.confidence, 0.0)

    def test_what_is_falls_back_to_is_a_relationship(self):
        self.knowledge.relate("Python", "Programming Language", "IS_A")
        result = self.reasoning.reason("What is Python?")
        self.assertEqual(result.status, STATUS_ANSWERED)
        self.assertEqual(result.conclusion, {"subject": "Python", "relation": "IS_A", "object": "Programming Language"})

    def test_bare_name_query_behaves_like_ask(self):
        self.knowledge.learn("Python", "a programming language")
        result = self.reasoning.reason("Python")
        self.assertEqual(result.status, STATUS_ANSWERED)


class TestMultiHopReasoning(unittest.TestCase):
    """TEST B - multi-hop reasoning (the stage spec's own worked example)."""

    def setUp(self):
        self.reasoning, self.knowledge, _ = _make_engine()
        self.knowledge.relate("Python", "Programming Language", "IS_A")
        self.knowledge.relate("Programming Language", "Software Development", "USED_FOR")

    def test_derives_used_for_via_is_a_plus_used_for_rule(self):
        result = self.reasoning.reason("What is Python used for?")
        self.assertEqual(result.status, STATUS_ANSWERED)
        self.assertEqual(
            result.conclusion, {"subject": "Python", "relation": "USED_FOR", "object": "Software Development"},
        )
        self.assertIn("is_a_used_for", result.rules_used)
        self.assertTrue(any(step["description"] == "inference" for step in result.reasoning_steps))

    def test_inferred_answer_is_distinguishable_from_direct(self):
        result = self.reasoning.reason("What is Python used for?")
        self.assertIn("inferred", result.answer)
        # A direct fact would never populate rules_used.
        self.assertTrue(result.rules_used)


class TestInvalidTransitivity(unittest.TestCase):
    """TEST C - invalid transitivity: USES is intentionally NOT declared
    transitive (see rules.TRANSITIVE_RELATION_TYPES), so a chain of USES
    edges must never produce a fabricated conclusion."""

    def setUp(self):
        self.reasoning, self.knowledge, _ = _make_engine()
        self.knowledge.relate("Scheduler", "Queue", "USES")
        self.knowledge.relate("Queue", "Mutex", "USES")

    def test_no_conclusion_is_fabricated_across_uses_chain(self):
        result = self.reasoning.reason("Does Scheduler use Mutex?")
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIsNone(result.answer)
        self.assertIsNone(result.conclusion)


class TestRuleEvaluation(unittest.TestCase):
    """TEST D - rule evaluation."""

    def test_custom_rule_produces_expected_inference(self):
        reasoning, knowledge, _ = _make_engine()
        reasoning.rules.register(Rule(
            name="employee_of_department_in_company",
            premises=[("A", "WORKS_IN", "B"), ("B", "PART_OF_ORG", "C")],
            conclusion=("A", "EMPLOYED_BY", "C"),
        ))
        knowledge.relate("Alice", "Engineering", "WORKS_IN")
        knowledge.relate("Engineering", "Acme Corp", "PART_OF_ORG")

        # "EMPLOYED_BY" isn't a recognized surface verb for the small
        # query parser (query_parsing.py only knows a handful of
        # example verbs) - this test is about rule evaluation itself,
        # so it drives that mechanism directly rather than through NL
        # query parsing.
        self.assertTrue(_rule_infers(reasoning, "Alice", "EMPLOYED_BY"))

    def test_rule_validation_rejects_unresolvable_conclusion_variable(self):
        errors = validate_rule(Rule("bad", premises=[("A", "X", "B")], conclusion=("A", "Y", "Z")))
        self.assertTrue(errors)

    def test_rule_validation_accepts_well_formed_rule(self):
        errors = validate_rule(Rule("ok", premises=[("A", "X", "B")], conclusion=("A", "Y", "B")))
        self.assertFalse(errors)


def _rule_infers(reasoning, subject, relation_type):
    """Small helper for TestRuleEvaluation: exercises rule inference
    directly (bypassing the small NL query parser, which doesn't know
    about the test's made-up relation names) and reports whether the
    expected conclusion was produced."""
    from reasoning.reasoning_engine import Budget
    budget = Budget(max_depth=4, max_rules=25, max_facts=200)

    class _Sink:
        warnings = []

    inferred = reasoning._infer(subject, relation_type, None, budget, _Sink())
    return inferred is not None and inferred.relation_type == relation_type


class TestContradictionDetection(unittest.TestCase):
    """TEST E - contradiction."""

    def setUp(self):
        self.reasoning, self.knowledge, _ = _make_engine()
        self.knowledge.relate("Python", "Programming Language", "IS_A")
        self.knowledge.relate("Python", "Programming Language", "IS_NOT_A")

    def test_contradiction_is_reported_not_silently_resolved(self):
        result = self.reasoning.reason("What is Python?")
        self.assertEqual(result.status, STATUS_CONTRADICTION)
        self.assertIsNone(result.answer)
        self.assertEqual(len(result.contradictions), 1)

    def test_check_consistency_reports_the_same_conflict(self):
        report = self.reasoning.check_consistency("Python")
        self.assertFalse(report["consistent"])
        self.assertEqual(len(report["contradictions"]), 1)


class TestUnknownHandling(unittest.TestCase):
    """TEST F - unknown."""

    def test_unknown_entity_never_produces_a_fabricated_answer(self):
        reasoning, _, _ = _make_engine()
        result = reasoning.reason("What is Zorblax?")
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIsNone(result.answer)
        self.assertIsNone(result.conclusion)
        self.assertTrue(result.unknowns)


class TestConfidencePropagation(unittest.TestCase):
    """TEST G - confidence: deterministic, and strictly non-increasing
    as evidence weakens or inference depth grows."""

    def test_confidence_reflects_weakest_evidence(self):
        reasoning, knowledge, _ = _make_engine()
        knowledge.relate("Python", "Programming Language", "IS_A", confidence=0.9)
        knowledge.relate("Programming Language", "Software Development", "USED_FOR", confidence=0.3)
        result = reasoning.reason("What is Python used for?")
        self.assertEqual(result.status, STATUS_ANSWERED)
        # The weaker of the two premise confidences (0.3) should bound
        # the result - never averaged up past it.
        self.assertLessEqual(result.confidence, 0.3)

    def test_confidence_is_deterministic_across_repeated_calls(self):
        reasoning, knowledge, _ = _make_engine()
        knowledge.relate("Python", "Programming Language", "IS_A")
        knowledge.relate("Programming Language", "Software Development", "USED_FOR")
        c1 = reasoning.reason("What is Python used for?").confidence
        c2 = reasoning.reason("What is Python used for?").confidence
        self.assertEqual(c1, c2)

    def test_confidence_decreases_with_inference_depth(self):
        reasoning, knowledge, _ = _make_engine()
        for pair in [("A", "B"), ("B", "C"), ("C", "D")]:
            knowledge.relate(*pair, "DEPENDS_ON")
        two_hop = reasoning.reason("Does A depend on C?", max_depth=5)
        three_hop = reasoning.reason("Does A depend on D?", max_depth=5)
        self.assertEqual(two_hop.status, STATUS_ANSWERED)
        self.assertEqual(three_hop.status, STATUS_ANSWERED)
        self.assertLess(three_hop.confidence, two_hop.confidence)


class TestContextAwareReasoning(unittest.TestCase):
    """TEST H - context."""

    def test_reference_is_resolved_against_recent_context(self):
        reasoning, knowledge, _ = _make_engine()
        context = ConversationContext()
        understanding = UnderstandingEngine()

        first = understanding.understand("Python is a programming language.", context=context)
        context.add_understanding(first, source="understand")
        knowledge.relate("Python", "Programming Language", "IS_A")
        knowledge.relate("Python", "indentation", "USES")

        result = reasoning.reason("What does it use?", context=context)
        self.assertEqual(result.status, STATUS_ANSWERED)
        self.assertEqual(result.conclusion["subject"], "Python")

    def test_reference_without_any_context_is_ambiguous_not_guessed(self):
        reasoning, _, _ = _make_engine()
        result = reasoning.reason("What does it use?")
        self.assertEqual(result.status, STATUS_AMBIGUOUS)
        self.assertIsNone(result.answer)


class TestReasoningLimits(unittest.TestCase):
    """TEST I - reasoning limits."""

    def setUp(self):
        self.reasoning, self.knowledge, _ = _make_engine()
        for pair in [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")]:
            self.knowledge.relate(*pair, "DEPENDS_ON")

    def test_shallow_depth_limit_stops_before_reaching_a_true_answer(self):
        result = self.reasoning.reason("Does A depend on E?", max_depth=2)
        self.assertEqual(result.status, STATUS_LIMIT_REACHED)

    def test_sufficient_depth_reaches_the_same_true_answer(self):
        result = self.reasoning.reason("Does A depend on E?", max_depth=6)
        self.assertEqual(result.status, STATUS_ANSWERED)

    def test_cyclic_graph_never_hangs(self):
        self.knowledge.relate("X", "Y", "DEPENDS_ON")
        self.knowledge.relate("Y", "X", "DEPENDS_ON")
        # Would loop forever without cycle-safety; completing at all
        # (within the test runner's normal time budget) is the assertion.
        result = self.reasoning.reason("Does X depend on Y?")
        self.assertEqual(result.status, STATUS_ANSWERED)


class TestAELCompatibility(unittest.TestCase):
    """TEST J - AEL compatibility: existing AEL behaviour (which already
    depends on ReasoningEngine.check_new_relationship/contradictions_for)
    must be completely unaffected by this stage."""

    def test_ael_teach_relate_and_ask_still_work(self):
        memory = MemorySystem(tempfile.mktemp(suffix=".db"))
        knowledge = KnowledgeSystem(memory)
        concepts = ConceptSystem(knowledge)
        reasoning = ReasoningEngine(knowledge)
        learning = LearningSystem(concepts, knowledge, memory=memory, reasoning_engine=reasoning)
        interpreter = AELInterpreter(learning, skill_system=None, reasoning_engine=reasoning, memory=memory)

        results = interpreter.run(
            "TEACH sun IS a star at the center of the solar system\n"
            "RELATE sun TO solar_system AS PART_OF\n"
            "ASK sun"
        )
        self.assertTrue(all(r.success for r in results))
        self.assertIn("star", results[-1].message)

    def test_ael_still_surfaces_contradictions_via_ask(self):
        memory = MemorySystem(tempfile.mktemp(suffix=".db"))
        knowledge = KnowledgeSystem(memory)
        concepts = ConceptSystem(knowledge)
        reasoning = ReasoningEngine(knowledge)
        learning = LearningSystem(concepts, knowledge, memory=memory, reasoning_engine=reasoning)
        interpreter = AELInterpreter(learning, skill_system=None, reasoning_engine=reasoning, memory=memory)

        interpreter.run("RELATE Python TO Language AS IS_A")
        interpreter.run("RELATE Python TO Language AS IS_NOT_A")
        results = interpreter.run("ASK Python")
        self.assertIn("conflicting info", results[0].message)


class TestCoreIntegration(unittest.TestCase):
    """Core.reason() is available, context-aware, and process_input()'s
    existing AEL/conversation routing is unaffected by its presence."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.core = Core(memory_db_path=self.db_path)

    def test_reason_is_available_and_context_aware(self):
        self.core.learn_from_text("Python is a programming language.")
        self.core.learn_from_text("It uses indentation.")
        result = self.core.reason("What does it use?")
        self.assertEqual(result.status, STATUS_ANSWERED)

    def test_process_input_ael_and_conversation_routing_unaffected(self):
        reply = self.core.process_input("TEACH sun IS a star")
        self.assertIn("Learned concept", reply)
        reply2 = self.core.process_input("an unrecognized statement about an undocumented topic")
        self.assertIn("don't have enough information", reply2)


if __name__ == "__main__":
    unittest.main()
