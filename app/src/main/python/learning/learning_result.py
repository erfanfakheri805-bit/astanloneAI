"""
Learning Result
================
The structured object returned by a learning operation - in particular
LearningSystem.learn_from_understanding(). Gives a caller (a UI, a
test, a future auto-learning policy) everything it needs to know what
actually happened without re-querying storage: what was learned, what
concepts/relationships were newly created vs. merely refreshed, what
was skipped and why, and anything that went wrong.
"""


class LearningResult:
    def __init__(self):
        self.success = False
        self.learned_items = []          # newly or repeatedly confirmed (subject, relation, object) triples
        self.created_concepts = []       # concept names created for the first time
        self.created_relationships = []  # brand-new relationship edges
        self.updated_items = []          # relationships that already existed and had metadata refreshed
        self.skipped_items = []          # candidates the Learning Decision rejected, with a reason
        self.warnings = []
        self.confidence = None
        self.errors = []

    def __repr__(self):
        return (
            f"LearningResult(success={self.success}, learned={len(self.learned_items)}, "
            f"created_concepts={len(self.created_concepts)}, "
            f"created_relationships={len(self.created_relationships)}, "
            f"updated={len(self.updated_items)}, skipped={len(self.skipped_items)}, "
            f"errors={len(self.errors)})"
        )

    def to_dict(self):
        return {
            "success": self.success,
            "learned_items": self.learned_items,
            "created_concepts": self.created_concepts,
            "created_relationships": self.created_relationships,
            "updated_items": self.updated_items,
            "skipped_items": self.skipped_items,
            "warnings": self.warnings,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "errors": self.errors,
        }
