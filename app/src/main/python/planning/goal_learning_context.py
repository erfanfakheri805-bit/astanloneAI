"""
Planning - Goal Learning Context
====================================
`GoalLearningContextAnalyzer` is a small, read-only step that makes
relevant learning context available *during* goal analysis, without
acting on it:

    raw goal text
        -> understanding.normalization.normalize()  (existing, reused
           as-is - same normalization Goal/GoalManager already use)
        -> _derive_pattern_prefix()  (this module: one small,
           deterministic string transform, nothing more)
        -> LearningContextProvider.get_context(records, pattern_prefix)
           (planning/learning_context.py - already does all the real
           learning-analysis work)
        -> {"goal": ..., "normalized_goal": ..., "learning_context": ...}

This is deliberately just an assembly step. It does not re-implement
any prefix matching, evidence counting, confidence averaging,
success-rate math, or ranking - all of that already lives in
`LearningAnalyzer`/`LearningContextProvider` and is reused as-is.
`_derive_pattern_prefix` is the one new piece of logic this module
adds, and it is intentionally tiny: the goal's first whitespace-
separated token, punctuation-stripped and lowercased, with a fixed
fallback so a pattern_prefix is always a valid non-empty string.

`get_goal_learning_context` never mutates the goal text, never
touches a `Goal`, `Plan`, or `PlanStep`, never creates a learning
record, never persists anything, and never executes anything. It
also never lets a failure in the learning system take goal analysis
down with it: a genuine caller mistake (an invalid
`min_success_rate`/`min_confidence`/`min_records`) still raises
`ValueError` exactly as `LearningContextProvider`/`LearningAnalyzer`
already raise it, but any other failure from `learning_context_provider`
(a missing/broken provider, an unexpected exception from whatever
reads `records`) is caught and treated the same as "no relevant
learning exists" - an empty learning context, not a crash.

This stage only makes learning context available for a caller to look
at during goal analysis - it does not feed it back into automatic
plan generation, capability selection, or execution. That wiring is
explicitly out of scope here, same as `planning/learning_context.py`'s
own boundary.
"""

import re

from understanding.normalization import normalize

# Strips leading/trailing punctuation from the derived token (e.g. a
# trailing "?" or "."). \W already matches non-word characters across
# Unicode scripts (including Persian) under Python 3's default regex
# behavior, so no separate Unicode handling is needed here.
_NON_WORD_EDGE_RE = re.compile(r"^\W+|\W+$")

# Used only when the normalized goal has no usable first token (an
# empty goal, or one made only of punctuation) - fixed and
# deterministic, never derived from anything variable.
_FALLBACK_PATTERN_PREFIX = "goal"


def _derive_pattern_prefix(normalized_goal):
    """The goal's first whitespace-separated token, with any leading/
    trailing punctuation stripped and case folded to lowercase -
    deliberately simple and fully deterministic (same
    `normalized_goal` always yields the same prefix). Falls back to
    `_FALLBACK_PATTERN_PREFIX` when there is no first token, or the
    token strips down to nothing, so the result is always a non-empty
    string `LearningContextProvider.get_context` can accept."""
    first_token = (normalized_goal or "").split(" ", 1)[0]
    prefix = _NON_WORD_EDGE_RE.sub("", first_token).lower()
    return prefix or _FALLBACK_PATTERN_PREFIX


class GoalLearningContextAnalyzer:
    """Stateless: holds no data or collaborators of its own between
    calls - the caller supplies the `LearningContextProvider` and the
    `records` for each call, so a single instance (or a fresh one per
    call) both behave identically. `get_goal_learning_context` is the
    only public method."""

    def get_goal_learning_context(
        self, goal_text, learning_context_provider, records,
        min_success_rate=0.7, min_confidence=0.7, min_records=2,
    ):
        """Return a small structured dict combining a goal's
        normalized text with whatever relevant learning context
        currently exists for it:

            {
                "goal": <goal_text, unchanged>,
                "normalized_goal": <str>,
                "learning_context": <dict - same shape
                    LearningContextProvider.get_context/
                    LearningAnalyzer.get_relevant_learning_context
                    already return>,
            }

        Steps (each one delegated, nothing recomputed here):
          1. `normalized_goal` is `understanding.normalization.
             normalize(goal_text).normalized_text` - the exact same
             normalization `GoalManager` already uses to build a
             `Goal`'s own `normalized_text`. Never raises for odd
             input (`None`/non-string `goal_text` normalizes to an
             empty string, same as `normalize` already handles it).
          2. A pattern prefix is derived from `normalized_goal` via
             `_derive_pattern_prefix` - the one small, deterministic
             transform this module adds.
          3. `learning_context_provider.get_context(records,
             pattern_prefix, min_success_rate=min_success_rate,
             min_confidence=min_confidence, min_records=min_records)`
             supplies `learning_context` - all prefix matching,
             learning-eligibility checking, success-rate filtering,
             and ranking happens there, not here.

        `min_success_rate`, `min_confidence`, and `min_records` keep
        the exact validation `LearningContextProvider`/
        `LearningAnalyzer` already apply: a genuinely invalid value
        (out of range, wrong type) raises the same `ValueError` calling
        `learning_context_provider.get_context` directly would raise -
        that validation is reused, not duplicated or swallowed here.

        Any other failure from `learning_context_provider` (for
        example, it is `None`, doesn't implement `get_context`, or
        raises some unrelated exception while reading `records`) is
        caught and treated as "no relevant learning exists": in that
        case `learning_context` is the same empty structure
        `get_relevant_learning_context` returns for no match -
        `{"pattern_prefix": <derived prefix>, "match_count": 0,
        "best_pattern": None, "patterns": []}` - rather than letting
        goal analysis itself fail.

        Never mutates `goal_text`, `records`, any record, a `Goal`, a
        `Plan`, or a `PlanStep`. Pure retrieval/analysis: does not
        execute anything, does not create a learning record, does not
        persist anything, and does not itself change any capability,
        skill, plan, goal, or other system behavior - it only makes
        context available for a caller to look at during goal
        analysis."""
        normalized_goal = normalize(goal_text).normalized_text
        pattern_prefix = _derive_pattern_prefix(normalized_goal)

        try:
            learning_context = learning_context_provider.get_context(
                records,
                pattern_prefix,
                min_success_rate=min_success_rate,
                min_confidence=min_confidence,
                min_records=min_records,
            )
        except ValueError:
            raise
        except Exception:
            learning_context = {
                "pattern_prefix": pattern_prefix,
                "match_count": 0,
                "best_pattern": None,
                "patterns": [],
            }

        return {
            "goal": goal_text,
            "normalized_goal": normalized_goal,
            "learning_context": learning_context,
        }
