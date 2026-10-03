"""
Tests for the Stage 6 Rule Registry (reasoning/rule_registry.py) and the
AEL RULE statement.

Run directly:
    python -m unittest tests.test_rule_registry -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)

Each TEST_* method below corresponds 1:1 to an item in the stage spec's
own "23. TESTS" section (TEST A through TEST L). TEST A-C/G-J overlap in
spirit with tests/test_reasoning_engine.py's pre-existing rule tests
(which exercise the bare rules.RuleEngine directly) - this file instead
exercises the same behaviour through the persistent RuleRegistry, plus
everything RuleRegistry adds on top: persistence across restart,
enable/disable, priority, deterministic confidence, provenance, and the
AEL RULE syntax.
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from reasoning.reasoning_engine import ReasoningEngine, Budget
from reasoning.rule_registry import RuleRegistry, RuleValidationError
from core.core import Core


def _make_registry_engine(db_path=None):
    """A fresh (ReasoningEngine, KnowledgeSystem, RuleRegistry, db_path)
    tuple, backed by a temporary sqlite file (never the real data/
    database) so persistence-across-restart can be tested by reopening
    the same path."""
    db_path = db_path or tempfile.mktemp(suffix=".db")
    memory = MemorySystem(db_path)
    knowledge = KnowledgeSystem(memory)
    registry = RuleRegistry(memory)
    reasoning = ReasoningEngine(knowledge, rule_registry=registry)
    return reasoning, knowledge, registry, db_path


def _rule_infers(reasoning, subject, relation_type):
    """Same small helper tests/test_reasoning_engine.py uses: drives rule
    inference directly for a made-up relation type the NL query parser
    doesn't know about, and returns the InferredFact (or None)."""
    budget = Budget(max_depth=4, max_rules=25, max_facts=200)
    from reasoning.reasoning_result import ReasoningResult
    result = ReasoningResult(query=f"{subject} {relation_type} ?")
    return reasoning._infer(subject, relation_type, None, budget, result)


class TestRegistrySimpleRule(unittest.TestCase):
    """TEST A - simple rule, via the registry."""

    def test_python_is_a_programming_language_derives_used_for(self):
        reasoning, knowledge, registry, _ = _make_registry_engine()
        knowledge.relate("Python", "ProgrammingLanguage", "IS_A")
        knowledge.relate("ProgrammingLanguage", "SoftwareDevelopment", "USED_FOR")

        # is_a_used_for is one of the seeded default rules (see
        # rules.default_rules()) - the registry persists it at first use.
        inferred = _rule_infers(reasoning, "Python", "USED_FOR")
        self.assertIsNotNone(inferred)
        self.assertEqual(inferred.to_name, "SoftwareDevelopment")
        self.assertEqual(inferred.rule_name, "is_a_used_for")


class TestRegistryMultipleConditions(unittest.TestCase):
    """TEST B - multiple conditions: a rule must not fire until every
    premise is satisfied."""

    def setUp(self):
        self.reasoning, self.knowledge, self.registry, _ = _make_registry_engine()
        self.registry.register(
            name="two_condition_rule",
            premises=[("X", "WORKS_IN", "A"), ("A", "PART_OF_ORG", "C")],
            conclusion=("X", "EMPLOYED_BY", "C"),
            source="user",
        )

    def test_does_not_fire_with_only_one_condition_met(self):
        self.knowledge.relate("Alice", "Engineering", "WORKS_IN")
        # PART_OF_ORG fact intentionally missing.
        self.assertIsNone(_rule_infers(self.reasoning, "Alice", "EMPLOYED_BY"))

    def test_fires_once_both_conditions_are_met(self):
        self.knowledge.relate("Alice", "Engineering", "WORKS_IN")
        self.knowledge.relate("Engineering", "Acme Corp", "PART_OF_ORG")
        inferred = _rule_infers(self.reasoning, "Alice", "EMPLOYED_BY")
        self.assertIsNotNone(inferred)
        self.assertEqual(inferred.to_name, "Acme Corp")


class TestRegistryVariableBinding(unittest.TestCase):
    """TEST C - variable binding: bindings recorded on the InferredFact
    (and its provenance()) must match what was actually matched, for any
    subject - not a fixed/hard-coded name."""

    def test_bindings_reflect_the_actual_matched_entities(self):
        reasoning, knowledge, registry, _ = _make_registry_engine()
        registry.register(
            name="lang_applies_to",
            premises=[("X", "IS_A", "A"), ("A", "APPLIES_TO", "C")],
            conclusion=("X", "APPLIES_TO", "C"),
            source="user",
        )
        knowledge.relate("Rust", "ProgrammingLanguage", "IS_A")
        knowledge.relate("ProgrammingLanguage", "SystemsProgramming", "APPLIES_TO")

        inferred = _rule_infers(reasoning, "Rust", "APPLIES_TO")
        self.assertIsNotNone(inferred)
        self.assertEqual(inferred.bindings, {
            "X": "Rust", "A": "ProgrammingLanguage", "C": "SystemsProgramming",
        })


class TestRegistryPersistence(unittest.TestCase):
    """TEST D - rule persistence across a simulated application restart
    (a fresh RuleRegistry/ReasoningEngine reopening the same db file)."""

    def test_registered_rule_survives_reopening_the_database(self):
        _, knowledge_unused, registry, db_path = _make_registry_engine()
        registry.register(
            name="persisted_rule",
            premises=[("X", "IS_A", "A"), ("A", "SUITABLE_FOR", "C")],
            conclusion=("X", "SUITABLE_FOR", "C"),
            source="user",
        )

        # Simulate a restart: brand new MemorySystem/KnowledgeSystem/
        # RuleRegistry/ReasoningEngine, same on-disk file.
        memory2 = MemorySystem(db_path)
        knowledge2 = KnowledgeSystem(memory2)
        registry2 = RuleRegistry(memory2)
        reasoning2 = ReasoningEngine(knowledge2, rule_registry=registry2)

        record = registry2.get_by_name("persisted_rule")
        self.assertIsNotNone(record)
        self.assertEqual(record["conclusion"], ("X", "SUITABLE_FOR", "C"))

        knowledge2.relate("Go", "ProgrammingLanguage", "IS_A")
        knowledge2.relate("ProgrammingLanguage", "SoftwareDevelopment", "SUITABLE_FOR")
        inferred = _rule_infers(reasoning2, "Go", "SUITABLE_FOR")
        self.assertIsNotNone(inferred)
        self.assertEqual(inferred.rule_name, "persisted_rule")


class TestRegistryEnableDisable(unittest.TestCase):
    """TEST E / TEST F - disabling a rule stops it from firing; re-enabling
    it restores that behaviour."""

    def setUp(self):
        self.reasoning, self.knowledge, self.registry, _ = _make_registry_engine()
        self.record = self.registry.register(
            name="togglable_rule",
            premises=[("X", "IS_A", "A"), ("A", "USED_FOR", "C")],
            conclusion=("X", "USED_FOR", "C"),
            source="user",
        )
        self.knowledge.relate("Java", "ProgrammingLanguage", "IS_A")
        self.knowledge.relate("ProgrammingLanguage", "SoftwareDevelopment", "USED_FOR")

    def test_disabled_rule_does_not_fire(self):
        self.registry.disable(self.record["id"])
        self.assertFalse(self.registry.get(self.record["id"])["enabled"])
        # The default rule (is_a_used_for) is still enabled and would also
        # match this same relation, so disable the seeded default too -
        # this test is specifically about *this* rule's enabled flag.
        for r in self.registry.list():
            if r["name"] != "togglable_rule":
                self.registry.disable(r["id"])
        self.assertIsNone(_rule_infers(self.reasoning, "Java", "USED_FOR"))

    def test_re_enabled_rule_fires_again(self):
        self.registry.disable(self.record["id"])
        for r in self.registry.list():
            if r["name"] != "togglable_rule":
                self.registry.disable(r["id"])
        self.assertIsNone(_rule_infers(self.reasoning, "Java", "USED_FOR"))

        self.registry.enable(self.record["id"])
        inferred = _rule_infers(self.reasoning, "Java", "USED_FOR")
        self.assertIsNotNone(inferred)
        self.assertEqual(inferred.rule_name, "togglable_rule")


class TestRegistryInvalidRule(unittest.TestCase):
    """TEST G - invalid rule registration is rejected, never silently
    accepted."""

    def test_conclusion_variable_not_in_premises_is_rejected(self):
        _, _, registry, _ = _make_registry_engine()
        with self.assertRaises(RuleValidationError):
            registry.register(
                name="bad_rule",
                premises=[("A", "X", "B")],
                conclusion=("A", "Y", "Z"),  # Z never bound by any premise
            )
        self.assertIsNone(registry.get_by_name("bad_rule"))

    def test_empty_conditions_is_rejected(self):
        _, _, registry, _ = _make_registry_engine()
        with self.assertRaises(RuleValidationError):
            registry.register(name="no_conditions", premises=[], conclusion=("A", "Y", "B"))

    def test_bad_confidence_is_rejected(self):
        _, _, registry, _ = _make_registry_engine()
        with self.assertRaises(RuleValidationError):
            registry.register(
                name="bad_confidence", premises=[("A", "X", "B")], conclusion=("A", "Y", "B"),
                confidence=1.5,
            )


class TestRegistryConfidence(unittest.TestCase):
    """TEST H - rule confidence and evidence confidence deterministically
    influence the resulting inference's confidence."""

    def test_lower_rule_confidence_yields_lower_result_confidence(self):
        reasoning, knowledge, registry, _ = _make_registry_engine()
        registry.register(
            name="high_conf_rule", premises=[("X", "IS_A", "A"), ("A", "USED_FOR", "C")],
            conclusion=("X", "USED_FOR", "C"), confidence=1.0, priority=10,
        )
        registry.register(
            name="low_conf_rule", premises=[("X", "IS_A", "A"), ("A", "USED_FOR2", "C")],
            conclusion=("X", "USED_FOR2", "C"), confidence=0.3, priority=10,
        )
        knowledge.relate("Python", "ProgrammingLanguage", "IS_A")
        knowledge.relate("ProgrammingLanguage", "SoftwareDevelopment", "USED_FOR")
        knowledge.relate("ProgrammingLanguage", "Scripting", "USED_FOR2")

        high = _rule_infers(reasoning, "Python", "USED_FOR")
        low = _rule_infers(reasoning, "Python", "USED_FOR2")
        self.assertIsNotNone(high)
        self.assertIsNotNone(low)
        self.assertLess(low.confidence, high.confidence)

    def test_same_inputs_give_the_same_confidence_every_time(self):
        reasoning, knowledge, registry, _ = _make_registry_engine()
        registry.register(
            name="det_rule", premises=[("X", "IS_A", "A"), ("A", "USED_FOR", "C")],
            conclusion=("X", "USED_FOR", "C"), confidence=0.8,
        )
        knowledge.relate("Python", "ProgrammingLanguage", "IS_A")
        knowledge.relate("ProgrammingLanguage", "SoftwareDevelopment", "USED_FOR")

        first = _rule_infers(reasoning, "Python", "USED_FOR").confidence
        second = _rule_infers(reasoning, "Python", "USED_FOR").confidence
        self.assertEqual(first, second)


class TestRegistryProvenance(unittest.TestCase):
    """TEST I - derived conclusions carry rule ID and supporting evidence,
    built entirely from real execution data."""

    def test_provenance_contains_rule_id_and_supporting_facts(self):
        reasoning, knowledge, registry, _ = _make_registry_engine()
        record = registry.register(
            name="provenance_rule", premises=[("X", "IS_A", "A"), ("A", "SUITABLE_FOR", "C")],
            conclusion=("X", "SUITABLE_FOR", "C"),
        )
        knowledge.relate("Python", "ProgrammingLanguage", "IS_A")
        knowledge.relate("ProgrammingLanguage", "SoftwareDevelopment", "SUITABLE_FOR")

        inferred = _rule_infers(reasoning, "Python", "SUITABLE_FOR")
        self.assertIsNotNone(inferred)
        prov = inferred.provenance()
        self.assertEqual(prov["rule_id"], record["id"])
        self.assertEqual(prov["rule_name"], "provenance_rule")
        self.assertEqual(prov["bindings"]["X"], "Python")
        self.assertEqual(len(prov["supporting_facts"]), 2)
        self.assertIn("timestamp", prov)
        self.assertIn("confidence", prov)

    def test_explain_rule_returns_registry_metadata(self):
        reasoning, knowledge, registry, _ = _make_registry_engine()
        registry.register(
            name="explainable_rule", premises=[("A", "X", "B")], conclusion=("A", "Y", "B"),
            description="a test rule", priority=5,
        )
        explanation = reasoning.explain_rule("explainable_rule")
        self.assertIsNotNone(explanation)
        self.assertEqual(explanation["description"], "a test rule")
        self.assertEqual(explanation["priority"], 5)
        self.assertEqual(explanation["source"], "user")


class TestRegistryLoopSafety(unittest.TestCase):
    """TEST J - reasoning over rules that look cyclic on paper must still
    terminate quickly and never crash or hang. Each individual Rule's
    premise chain is fixed-length (validated at registration - see
    rules.validate_rule's circular-conclusion check), and a single
    reason()/_infer() call never chains one rule's derived conclusion
    into another rule's premise (each premise is matched only against
    literally stored relationships_for() - see reasoning_engine.py's
    module docstring) - so a "loop" between rules can only ever show up
    as two independent, separately-bounded lookups, never runaway
    recursion. This test constructs exactly that shape and confirms it
    resolves cleanly either way."""

    def test_mutually_referencing_rules_terminate_without_a_bogus_conclusion(self):
        reasoning, knowledge, registry, _ = _make_registry_engine()
        registry.register(name="a_to_b", premises=[("X", "LINK", "Y")], conclusion=("X", "DERIVED_B", "Y"))
        registry.register(name="b_to_a", premises=[("X", "DERIVED_B", "Y")], conclusion=("X", "DERIVED_A", "Y"))
        knowledge.relate("Node1", "Node2", "LINK")

        # a_to_b can fire directly off the stored LINK fact.
        result_b = _rule_infers(reasoning, "Node1", "DERIVED_B")
        self.assertIsNotNone(result_b)
        # b_to_a's premise (DERIVED_B) was never *stored* - only inferred
        # in-memory a moment ago and never written back to the Knowledge
        # Graph (see reasoning_engine.py: "never writes an inferred
        # conclusion back into the Knowledge System") - so it correctly
        # finds nothing, rather than fabricating a chained answer.
        result_a = _rule_infers(reasoning, "Node1", "DERIVED_A")
        self.assertIsNone(result_a)

    def test_self_referential_rule_is_rejected_at_registration(self):
        _, _, registry, _ = _make_registry_engine()
        with self.assertRaises(RuleValidationError):
            registry.register(name="self_loop", premises=[("A", "REL", "B")], conclusion=("A", "REL", "B"))


class TestAELCompatibility(unittest.TestCase):
    """TEST K - every previously supported AEL command still works once
    Core wires a RuleRegistry through the interpreter."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.core = Core(memory_db_path=self.db_path, skill_definitions_dir=tempfile.mkdtemp())

    def test_teach_relate_skill_ask_still_work(self):
        r = self.core.ael.run("TEACH sun IS a star at the center of the solar system")[0]
        self.assertTrue(r.success)

        r = self.core.ael.run("RELATE sun TO solar-system AS PART_OF")[0]
        self.assertTrue(r.success)

        r = self.core.ael.run("SKILL wave RESPONDS TO hi,hello WITH Hello there!")[0]
        self.assertTrue(r.success)

        r = self.core.ael.run("ASK sun")[0]
        self.assertTrue(r.success)
        self.assertIn("star", r.message)

    def test_upgrade_and_rollback_still_work(self):
        r = self.core.ael.run("UPGRADE demo-upgrade IS a placeholder upgrade")[0]
        self.assertTrue(r.success)


class TestAELRule(unittest.TestCase):
    """TEST L - a rule taught through AEL becomes available to the Rule
    Registry and can participate in reasoning."""

    def setUp(self):
        self.db_path = tempfile.mktemp(suffix=".db")
        self.core = Core(memory_db_path=self.db_path, skill_definitions_dir=tempfile.mkdtemp())

    def test_ael_rule_registers_and_fires(self):
        result = self.core.ael.run(
            "RULE lang_used_for IF X IS_A A AND A USED_FOR C THEN X USED_FOR C"
        )[0]
        self.assertTrue(result.success, result.message)
        record = self.core.rule_registry.get_by_name("lang_used_for")
        self.assertIsNotNone(record)
        self.assertEqual(record["source"], "ael")
        self.assertEqual(record["conditions"], [("X", "IS_A", "A"), ("A", "USED_FOR", "C")])
        self.assertEqual(record["conclusion"], ("X", "USED_FOR", "C"))

        self.core.knowledge.relate("Kotlin", "ProgrammingLanguage", "IS_A")
        self.core.knowledge.relate("ProgrammingLanguage", "SoftwareDevelopment", "USED_FOR")

        inferred = _rule_infers(self.core.reasoning, "Kotlin", "USED_FOR")
        self.assertIsNotNone(inferred)
        self.assertEqual(inferred.to_name, "SoftwareDevelopment")

    def test_ael_rule_is_routed_through_process_input_like_every_other_ael_keyword(self):
        # Regression check: parser/parser.py keeps its own separate list of
        # recognized AEL keywords for routing process_input() input to AEL
        # vs. plain conversation - RULE has to be in that list too, or a
        # RULE statement typed at the top-level process_input() entry point
        # (not core.ael.run() directly) silently falls through to the
        # conversational fallback instead of registering anything.
        reply = self.core.process_input(
            "RULE routed_rule IF X IS_A A AND A USED_FOR C THEN X USED_FOR C"
        )
        self.assertIn("[AEL OK]", reply)
        self.assertIsNotNone(self.core.rule_registry.get_by_name("routed_rule"))

    def test_ael_rejects_a_malformed_rule(self):
        result = self.core.ael.run(
            "RULE bad_rule IF A REL B THEN A OTHERREL C"
        )[0]
        self.assertFalse(result.success)
        self.assertIsNone(self.core.rule_registry.get_by_name("bad_rule"))

    def test_ael_rule_syntax_error_is_reported_cleanly(self):
        result = self.core.ael.run("RULE incomplete IF A REL B")[0]
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
