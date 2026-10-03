"""
Planning - Learning Context Provider
========================================
`LearningContextProvider` is a small, read-only adapter between the
learning system and the planning system:

    [LearningRecord, ...] (a caller already has, e.g. from
        LearningRecordStore.get_all()/find_by_pattern())
        -> LearningContextProvider.get_context(records, pattern_prefix)
        -> the exact structured dict
           LearningAnalyzer.get_relevant_learning_context() returns

This module exists purely to give planning components a stable,
planning-side import path ("planning/learning_context.py") for
reading relevant learned patterns, without planning code needing to
import from - or know anything about the internals of - the
`learning` package directly. It is not planning logic itself: it
adds no filtering, ranking, scoring, or decision-making of its own.
`get_context` is a thin pass-through to
`LearningAnalyzer.get_relevant_learning_context` (learning/
learning_analyzer.py), which already does all prefix matching,
learning-eligibility checking, success-rate filtering, and ranking -
none of that is duplicated here, and neither is its validation
(`pattern_prefix` must be a non-empty string; `min_success_rate`/
`min_confidence` must each be a plain number between `0.0` and `1.0`;
`min_records` must be a plain `int >= 1` - anything else raises
`ValueError`, exactly as `LearningAnalyzer` already raises it).

Same "inert, read-only" boundary the rest of this planning package
already draws around reporting from existing data (see
`ProposalPatternAnalyzer` in proposal_pattern_analyzer.py,
`GoalCompletionEvaluator` in goal_completion.py): never mutates
`records`, never touches a `Goal`, `Plan`, or `PlanStep`, never
executes anything, never creates a learning record, never persists
anything, and never itself decides or changes what a plan or goal
should be - it only exposes learning context a planning component
could later choose to read.

This stage intentionally does not wire this provider into any
automatic planning flow - it only creates the adapter boundary
itself.
"""

from learning.learning_analyzer import LearningAnalyzer


class LearningContextProvider:
    """Stateless: holds only a private `LearningAnalyzer` instance it
    never mutates and never exposes, so a single provider (or a fresh
    one per call) both behave identically. `get_context` is the only
    public method."""

    def __init__(self):
        self._analyzer = LearningAnalyzer()

    def get_context(
        self, records, pattern_prefix,
        min_success_rate=0.7, min_confidence=0.7, min_records=2,
    ):
        """Return the exact structured dict
        `LearningAnalyzer.get_relevant_learning_context(records,
        pattern_prefix, min_success_rate=min_success_rate,
        min_confidence=min_confidence, min_records=min_records)`
        already returns:

            {
                "pattern_prefix": <the pattern_prefix argument, unchanged>,
                "match_count": <int>,
                "best_pattern": <detail dict, or None>,
                "patterns": [<detail dict>, ...],
            }

        This is a direct pass-through with no logic of its own - no
        prefix matching, evidence counting, confidence averaging,
        success-rate math, or ranking is repeated here, and no
        validation is repeated either: `pattern_prefix`,
        `min_success_rate`, `min_confidence`, and `min_records` keep
        the exact validation `LearningAnalyzer.
        get_relevant_learning_context` already applies (anything
        invalid raises the same `ValueError` it would).

        Returns a fresh dict (the exact fresh dict/list structure
        `get_relevant_learning_context` already builds this call,
        never shared/cached) - `match_count: 0`, `best_pattern: None`,
        `patterns: []` for an empty/`None` `records` or when no
        learned pattern's name starts with `pattern_prefix`. Never
        mutates `records`, any record, a `Goal`, a `Plan`, or a
        `PlanStep`. Pure retrieval/analysis: does not execute
        anything, does not create a learning record, does not persist
        anything, and does not itself change any capability, skill,
        plan, goal, or other system behavior - it only hands a
        planning component context it could choose to act on
        elsewhere."""
        return self._analyzer.get_relevant_learning_context(
            records,
            pattern_prefix,
            min_success_rate=min_success_rate,
            min_confidence=min_confidence,
            min_records=min_records,
        )
