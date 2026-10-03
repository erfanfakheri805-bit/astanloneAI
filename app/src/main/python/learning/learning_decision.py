"""
Learning Decision
===================
The explicit decision step the project's natural-language-learning
stage calls for, sitting between UNDERSTANDING and PERSISTENCE:

    LearningInput -> LearningDecisionEngine.decide() -> LearningDecision

Deliberately small and deterministic - local rules only, no semantic
reasoning, no machine learning. It considers exactly the signals the
spec asks for: understanding/relation confidence, whether the relation
type is one this stage actually knows how to store, whether the
subject/object look structurally sane, and (via the Reasoning Engine,
if one was supplied) whether the exact opposite relationship is already
recorded between the same two names.

A contradiction is *surfaced*, never *blocking*: this module still
decides to persist, and lets the caller record the conflict (see
LearningSystem.learn_from_understanding). Refusing to store contradicted
information would destroy the "preserve enough information for future
contradiction handling" requirement just as much as silently overwriting
it would - full contradiction resolution is explicitly a later
reasoning-stage responsibility, not this one's.
"""

from .learning_input import SUPPORTED_INPUT_TYPES

# Below this, a relation candidate is treated as too uncertain to become
# permanent knowledge - it can still be shown to a human/reviewer (see
# LearningResult.skipped_items) but is not written to storage.
MIN_CONFIDENCE_TO_LEARN = 0.5

# A subject/object shorter than this is almost certainly a stray token,
# not a real concept name (e.g. a leftover single letter after pattern
# extraction).
MIN_TERM_LENGTH = 2

# The relation vocabulary this stage's extraction patterns
# (understanding/relation_extraction.py) actually produce. Anything
# else reaching this decision step is unrecognized and is rejected
# rather than stored under an unknown edge type.
KNOWN_RELATION_TYPES = {"IS_A", "IS_CALLED", "USES", "HAS", "CONTAINS", "DEPENDS_ON"}

REASON_OK = "ok"
REASON_UNSUPPORTED_INPUT_TYPE = "unsupported_input_type"
REASON_UNKNOWN_RELATION_TYPE = "unknown_relation_type"
REASON_INVALID_SUBJECT = "invalid_subject"
REASON_INVALID_OBJECT = "invalid_object"
REASON_CONFIDENCE_TOO_LOW = "confidence_too_low"


class LearningDecision:
    def __init__(self, should_persist, reason, contradiction=None):
        self.should_persist = should_persist
        self.reason = reason
        self.contradiction = contradiction  # relationship row dict, or None

    def __repr__(self):
        return f"LearningDecision(should_persist={self.should_persist}, reason={self.reason!r})"

    def to_dict(self):
        return {
            "should_persist": self.should_persist,
            "reason": self.reason,
            "contradiction": dict(self.contradiction) if self.contradiction else None,
        }


class LearningDecisionEngine:
    def __init__(self, knowledge_system, reasoning_engine=None):
        self.knowledge = knowledge_system
        self.reasoning = reasoning_engine

    def decide(self, learning_input):
        """Never raises - malformed/empty fields produce a
        should_persist=False decision with a reason, matching the
        Understanding Engine's own error-handling convention."""
        if learning_input.input_type not in SUPPORTED_INPUT_TYPES:
            return LearningDecision(False, REASON_UNSUPPORTED_INPUT_TYPE)

        if learning_input.relation not in KNOWN_RELATION_TYPES:
            return LearningDecision(False, REASON_UNKNOWN_RELATION_TYPE)

        subject = (learning_input.subject or "").strip()
        obj = (learning_input.object or "").strip()
        if len(subject) < MIN_TERM_LENGTH:
            return LearningDecision(False, REASON_INVALID_SUBJECT)
        if len(obj) < MIN_TERM_LENGTH:
            return LearningDecision(False, REASON_INVALID_OBJECT)

        if learning_input.confidence is None or learning_input.confidence < MIN_CONFIDENCE_TO_LEARN:
            return LearningDecision(False, REASON_CONFIDENCE_TOO_LOW)

        contradiction = None
        if self.reasoning:
            contradiction = self.reasoning.check_new_relationship(
                subject, learning_input.relation, obj
            )

        return LearningDecision(True, REASON_OK, contradiction=contradiction)
