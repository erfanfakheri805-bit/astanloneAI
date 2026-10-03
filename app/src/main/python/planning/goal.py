"""
Planning - Goal
=================
`Goal` is the lightweight, structured record the future Planning
Engine will operate on:

    USER INPUT -> ... -> GOAL -> [Planning Engine: not built yet]

This stage only defines the shape of a goal and how one is created
from user input - it does not decide how to satisfy a goal, does not
generate a plan, and does not execute anything. Those responsibilities
belong to the Planning Engine itself, in a later stage.

Same convention already used by UnderstandingResult
(understanding/result.py), LearningResult (learning/learning_result.py),
and ContextEntry (context/context_entry.py): a plain, JSON-shaped
record with a `to_dict()` method, rather than formatted text, so a
caller (a UI, a test, the eventual Planning Engine) gets everything it
needs without re-deriving anything from a message string.
"""

from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Small, fixed vocabulary for goal status (matches the STATUS_* pattern
# used by reasoning/reasoning_result.py) so callers can branch on it
# reliably instead of comparing against free-form strings.
STATUS_PENDING = "pending"        # created, not yet looked at by a Planning Engine
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

ALL_STATUSES = (
    STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED,
)

DEFAULT_GOAL_TYPE = "general"


class Goal:
    """One user-stated goal, captured but not yet acted on.

    `requirements` and `metadata` are always plain lists/dicts (never
    None) so callers can iterate/index them immediately without a None
    check - same convention as UnderstandingResult.entities/relations.
    """

    __slots__ = (
        "goal_id", "original_text", "normalized_text", "goal_type",
        "requirements", "confidence", "status", "created_at", "metadata",
    )

    def __init__(
        self,
        goal_id,
        original_text,
        normalized_text,
        goal_type=None,
        requirements=None,
        confidence=0.0,
        status=STATUS_PENDING,
        created_at=None,
        metadata=None,
    ):
        if status not in ALL_STATUSES:
            raise ValueError(f"Unknown goal status: {status!r}")

        self.goal_id = goal_id
        self.original_text = original_text
        self.normalized_text = normalized_text
        self.goal_type = goal_type if goal_type else DEFAULT_GOAL_TYPE
        self.requirements = list(requirements) if requirements else []
        self.confidence = max(0.0, min(1.0, confidence))
        self.status = status
        self.created_at = created_at if created_at is not None else _now_iso()
        self.metadata = dict(metadata) if metadata else {}

    def __repr__(self):
        return (
            f"Goal(goal_id={self.goal_id!r}, goal_type={self.goal_type!r}, "
            f"status={self.status!r}, confidence={self.confidence:.2f})"
        )

    def to_dict(self):
        """Structured (JSON-shaped) representation - used both as the
        general-purpose serialization and as GoalManager's debugging
        view (see GoalManager.describe_goal)."""
        return {
            "goal_id": self.goal_id,
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "goal_type": self.goal_type,
            "requirements": list(self.requirements),
            "confidence": round(self.confidence, 4),
            "status": self.status,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }
