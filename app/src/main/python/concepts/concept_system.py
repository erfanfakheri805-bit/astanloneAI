"""
Concept System
===============
A concept is a knowledge entry of kind='concept'. This system provides a
graph-shaped view over the Knowledge System: looking up a concept together
with everything it's related to, in one call. It doesn't own its own
storage - it composes the Knowledge System, keeping responsibilities clean.
"""


class ConceptSystem:
    def __init__(self, knowledge_system):
        self.knowledge = knowledge_system

    def define(self, name, description, source="user", confidence=None, source_text=None, learning_method=None):
        return self.knowledge.learn(name, description, kind="concept", source=source, confidence=confidence,
                                     source_text=source_text, learning_method=learning_method)

    def get_with_relations(self, name):
        concept = self.knowledge.get(name)
        if not concept:
            return None
        concept = dict(concept)
        concept["relationships"] = self.knowledge.relationships_for(name)
        return concept

    def link(self, concept_a, concept_b, relation_type, **provenance):
        """Returns True if this created a new relationship, False if it
        was already known (see KnowledgeSystem.relate). `**provenance`
        (confidence/source_type/source_text/learning_method) is passed
        straight through - ConceptSystem doesn't interpret it, just
        keeps the call surface between LearningSystem and KnowledgeSystem
        composable."""
        return self.knowledge.relate(concept_a, concept_b, relation_type, **provenance)

    def find_by_name_case_insensitive(self, name):
        return self.knowledge.find_by_name_case_insensitive(name)

    def all_concepts(self):
        return self.knowledge.all(kind="concept")
