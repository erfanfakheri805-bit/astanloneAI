"""
Learning Input Contract
=========================
The structured interface between `UnderstandingResult`
(understanding/result.py) and the Learning Engine
(learning/learning_system.py). This is the "LEARNING INPUT CONTRACT"
called for by the project's natural-language-learning stage: the
Learning Engine should receive structured information, not have to
re-parse raw text itself.

`LearningInput` deliberately mirrors the vocabulary AEL already uses at
the instruction level (TEACH -> a fact/definition about one concept,
RELATE -> a relationship between two), so the two entry points converge
on compatible internal shapes instead of duplicating concepts.

INPUT_TYPE_* enumerates the full vocabulary this contract is meant to
grow into (FACT, DEFINITION, CONCEPT, RELATIONSHIP, RULE, PROCEDURE,
EXAMPLE, GOAL, INSTRUCTION, CORRECTION, FEEDBACK) so a later stage can
start producing e.g. INSTRUCTION or GOAL inputs without changing this
module's shape again. Only FACT and RELATIONSHIP are actually built and
acted on this stage (see SUPPORTED_INPUT_TYPES and
learning_decision.py) - everything else is a reserved name, not a fake
capability.
"""

INPUT_TYPE_FACT = "FACT"
INPUT_TYPE_DEFINITION = "DEFINITION"
INPUT_TYPE_CONCEPT = "CONCEPT"
INPUT_TYPE_RELATIONSHIP = "RELATIONSHIP"
INPUT_TYPE_RULE = "RULE"
INPUT_TYPE_PROCEDURE = "PROCEDURE"
INPUT_TYPE_EXAMPLE = "EXAMPLE"
INPUT_TYPE_GOAL = "GOAL"
INPUT_TYPE_INSTRUCTION = "INSTRUCTION"
INPUT_TYPE_CORRECTION = "CORRECTION"
INPUT_TYPE_FEEDBACK = "FEEDBACK"

ALL_INPUT_TYPES = {
    INPUT_TYPE_FACT, INPUT_TYPE_DEFINITION, INPUT_TYPE_CONCEPT, INPUT_TYPE_RELATIONSHIP,
    INPUT_TYPE_RULE, INPUT_TYPE_PROCEDURE, INPUT_TYPE_EXAMPLE, INPUT_TYPE_GOAL,
    INPUT_TYPE_INSTRUCTION, INPUT_TYPE_CORRECTION, INPUT_TYPE_FEEDBACK,
}

# What this stage actually knows how to turn into persistent knowledge.
# See learning_decision.py: anything outside this set is deliberately
# rejected, not guessed at.
SUPPORTED_INPUT_TYPES = {INPUT_TYPE_FACT, INPUT_TYPE_RELATIONSHIP}

# Relation types classified as an "IS_A"-style FACT rather than a more
# general RELATIONSHIP. This is a classification label only - both
# input types are persisted through the exact same relationship-graph
# storage (see LearningSystem.learn_from_understanding); nothing about
# storage depends on this split, it just names the two cases the spec
# distinguishes ("LEARN BASIC FACTS" vs "LEARN RELATIONSHIPS").
_FACT_RELATIONS = {"IS_A"}

DEFAULT_LEARNING_METHOD = "natural_language_understanding"
DEFAULT_SOURCE_TYPE = "understanding_engine"


class LearningInput:
    """One structured, extractable piece of information the Learning
    Engine can decide whether to persist. Carries its own provenance so
    nothing downstream needs the original raw text passed alongside it
    out-of-band."""

    def __init__(self, input_type, subject, relation, obj, confidence,
                 source_type=DEFAULT_SOURCE_TYPE, source_text=None,
                 learning_method=DEFAULT_LEARNING_METHOD):
        self.input_type = input_type
        self.subject = subject
        self.relation = relation
        self.object = obj
        self.confidence = confidence
        self.source_type = source_type
        self.source_text = source_text
        self.learning_method = learning_method

    def __repr__(self):
        return (
            f"LearningInput({self.input_type}, {self.subject!r} {self.relation!r} "
            f"{self.object!r}, confidence={self.confidence:.2f})"
        )

    def to_dict(self):
        return {
            "input_type": self.input_type,
            "subject": self.subject,
            "relation": self.relation,
            "object": self.object,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "source_type": self.source_type,
            "source_text": self.source_text,
            "learning_method": self.learning_method,
        }


def build_learning_inputs(understanding_result):
    """Translate an UnderstandingResult's relation candidates into a
    list of LearningInput - the structured contract the Learning Engine
    consumes instead of raw text. One LearningInput per relation
    candidate found by the Understanding Engine (understanding/
    relation_extraction.py); returns [] if it found none (e.g. a
    question, a command, or a statement with no recognizable pattern).

    Confidence is the minimum of the relation candidate's own pattern
    confidence and the Understanding Engine's overall confidence for
    the sentence - a strong pattern match inside a sentence the engine
    otherwise wasn't sure about (unknown language, no entities) should
    not be treated as fully confident just because the one pattern
    matched cleanly.
    """
    inputs = []
    for candidate in understanding_result.relations:
        input_type = INPUT_TYPE_FACT if candidate.relation in _FACT_RELATIONS else INPUT_TYPE_RELATIONSHIP
        confidence = candidate.confidence
        if understanding_result.confidence is not None:
            confidence = min(confidence, understanding_result.confidence)
        inputs.append(LearningInput(
            input_type=input_type,
            subject=candidate.subject,
            relation=candidate.relation,
            obj=candidate.object,
            confidence=confidence,
            source_text=understanding_result.original_text,
        ))
    return inputs
