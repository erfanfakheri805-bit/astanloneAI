"""
Conversation Context - Context Entry
=======================================
`ContextEntry` is the structured record kept for one piece of recent
conversation (one user input and what the Understanding Engine noticed
about it). It is deliberately a plain, JSON-shaped record - the same
"structured information, not just formatted text" convention already
used by UnderstandingResult (understanding/result.py) and LearningResult
(learning/learning_result.py) - so it can be inspected, logged, or
eventually shown in a UI without any special-casing.

A ContextEntry never stores raw RelationCandidate/entity objects from
the Understanding Engine; it stores their already-`.to_dict()`-shaped
form. That keeps this module free of a dependency on understanding/*
internals and keeps every entry trivially serializable.
"""

from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class ContextEntry:
    """One bounded unit of short-term conversational context.

    `entities` / `relations` are lists of plain dicts (already in the
    same shape UnderstandingResult.to_dict() uses for its own entities/
    relations), never live objects - see module docstring.

    `learning_summary`, when present, is a small dict describing what
    the Learning Engine did with this input (see
    ConversationContext.add_understanding's `learning_summary` param) -
    this is the "recent learning operations" piece of context called
    for by the spec, without duplicating LearningResult's full shape.
    """

    __slots__ = (
        "id", "timestamp", "input_text", "normalized_text", "language",
        "sentence_type", "entities", "relations", "confidence",
        "importance", "source", "learning_summary",
    )

    def __init__(
        self,
        entry_id,
        input_text,
        normalized_text,
        language,
        sentence_type,
        entities,
        relations,
        confidence,
        importance,
        source="conversation",
        learning_summary=None,
        timestamp=None,
    ):
        self.id = entry_id
        self.timestamp = timestamp if timestamp is not None else _now_iso()
        self.input_text = input_text
        self.normalized_text = normalized_text
        self.language = language
        self.sentence_type = sentence_type
        self.entities = entities if entities is not None else []
        self.relations = relations if relations is not None else []
        self.confidence = confidence
        self.importance = importance
        self.source = source
        self.learning_summary = learning_summary

    def __repr__(self):
        return (
            f"ContextEntry(id={self.id}, sentence_type={self.sentence_type!r}, "
            f"entities={len(self.entities)}, relations={len(self.relations)}, "
            f"importance={self.importance:.2f})"
        )

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "input_text": self.input_text,
            "normalized_text": self.normalized_text,
            "language": self.language,
            "sentence_type": self.sentence_type,
            "entities": self.entities,
            "relations": self.relations,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "importance": round(self.importance, 4) if self.importance is not None else None,
            "source": self.source,
            "learning_summary": self.learning_summary,
        }
