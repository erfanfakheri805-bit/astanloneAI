"""
Planning - Goal Manager
=========================
`GoalManager` is deliberately small: it can create a `Goal` from user
input, keep it in memory, retrieve it by id, and describe it for
debugging. It is the "future Planning Engine's" bookkeeping layer, not
the Planning Engine itself - no plan generation, no execution, and no
external/network calls happen here (see planning/goal.py's module
docstring for where those belong once that stage exists).

Deliberately separate from, and never a replacement for, the project's
persistent storage (memory/memory_system.py) - same pattern already
used by context/conversation_context.py:

    GOAL MANAGER (this module)         PERSISTENT MEMORY/KNOWLEDGE
    ---------------------------------  ---------------------------------
    candidate goals                    learned concepts / facts
    lives only in this process's RAM   lives in the sqlite-backed stores
    cleared on process restart         durable across restarts

Only reuses `understanding.normalization.normalize` (a pure,
in-process string transform with no I/O of its own) to derive
`normalized_text` - the same normalization already used elsewhere in
the project (see understanding/engine.py) - so a Goal's normalized_text
is produced the same way as everywhere else instead of re-implementing
its own variant.
"""

import itertools

from understanding.normalization import normalize

from .goal import Goal, DEFAULT_GOAL_TYPE

# Deterministic confidence weights, same "never randomized, never
# guessed" convention as understanding/engine.py's own confidence
# scoring. These are fixed contributions from actual evidence present
# at goal-creation time.
_CONFIDENCE_BASE = 0.4
_CONFIDENCE_GOAL_TYPE_GIVEN = 0.2
_CONFIDENCE_HAS_REQUIREMENTS = 0.2
_CONFIDENCE_MULTI_WORD_TEXT = 0.2


def _estimate_confidence(normalized_text, goal_type_given, requirements):
    """Simple, deterministic confidence estimate for a freshly created
    Goal. This is intentionally crude (word count / presence checks
    only) - refining how a goal's confidence is judged is Planning
    Engine work, not this stage's."""
    confidence = _CONFIDENCE_BASE
    if goal_type_given:
        confidence += _CONFIDENCE_GOAL_TYPE_GIVEN
    if requirements:
        confidence += _CONFIDENCE_HAS_REQUIREMENTS
    if len(normalized_text.split()) > 2:
        confidence += _CONFIDENCE_MULTI_WORD_TEXT
    return max(0.0, min(1.0, confidence))


class GoalManager:
    """Not thread-safe (matches the rest of the project - see
    context/conversation_context.py's own note). Safe to use one
    instance per Core / per conversation session."""

    def __init__(self):
        self._goals = {}
        self._id_counter = itertools.count(1)

    # ------------------------------------------------------------------
    # Creation / storage
    # ------------------------------------------------------------------
    def create_goal(self, raw_text, goal_type=None, requirements=None, metadata=None):
        """Create a Goal from user input, store it, and return it.

        Raises ValueError on empty/whitespace-only/non-text input
        rather than silently creating a meaningless goal - a Goal
        always represents something the user actually said."""
        normalization = normalize(raw_text)
        if not normalization.normalized_text:
            raise ValueError("Cannot create a goal from empty input.")

        goal_id = f"goal-{next(self._id_counter)}"
        confidence = _estimate_confidence(
            normalization.normalized_text, bool(goal_type), requirements
        )

        goal = Goal(
            goal_id=goal_id,
            original_text=normalization.original_text,
            normalized_text=normalization.normalized_text,
            goal_type=goal_type or DEFAULT_GOAL_TYPE,
            requirements=requirements,
            confidence=confidence,
            metadata=metadata,
        )
        self._goals[goal_id] = goal
        return goal

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get_goal(self, goal_id):
        """Return the Goal for `goal_id`, or None if no such goal
        exists (never raises for an unknown id)."""
        return self._goals.get(goal_id)

    def all_goals(self):
        """All stored Goals, oldest-first (insertion order)."""
        return list(self._goals.values())

    def __len__(self):
        return len(self._goals)

    # ------------------------------------------------------------------
    # Debugging
    # ------------------------------------------------------------------
    def describe_goal(self, goal_id):
        """Structured (JSON-shaped) representation of one goal for
        debugging/inspection, or None if `goal_id` isn't known. Safe to
        hand to a UI, a test, or a log - see Goal.to_dict()."""
        goal = self.get_goal(goal_id)
        return goal.to_dict() if goal else None

    def debug_state(self):
        """Structured snapshot of every goal currently held, for
        debugging/inspection (a developer panel, a test)."""
        return {
            "goal_count": len(self._goals),
            "goals": [g.to_dict() for g in self.all_goals()],
        }
